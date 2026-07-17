# -*- coding: utf-8 -*-
"""
产品资料管理页。

把鼠标 / 键盘等外设按「品类 → 品牌 → 型号」统一归类管理：
- 基础数据从旺店通 ERP 仓库（库存接口 stock_query）一键同步
- 左侧树状浏览 + 关键词搜索
- 右侧表单可对单条做手工归类 / 补充（品类、备注等）/ 删除

数据层见 utils/product_library_manager.py，仓库客户端见 utils/wdt_client.py。
文案创作对接为后续步骤（manager.to_prompt_text 已预留）。
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QFrame, QWidget, QTreeWidget, QTreeWidgetItem, QMessageBox, QComboBox,
    QSplitter, QScrollArea, QFormLayout, QSizePolicy, QFileDialog,
)
from PySide6.QtCore import Qt, QThread, Signal
from utils.base_worker import BaseWorker

from utils.logger_utils import log
from utils.product_library_manager import ProductLibraryManager, FIELDS, REQUIRED_FIELDS, WAREHOUSE_FIELDS
from utils.wdt_client import WdtClient, map_stocks_to_kb


class StockSyncWorker(BaseWorker):
    """后台线程：从旺店通仓库拉取库存 + 货品品类，映射成产品资料条目。"""
    phase = Signal(str)              # 阶段文字
    progress = Signal(int, int)      # fetched, total
    finished = Signal(list, dict)    # mapped KB dicts, goods_no->{category,brand}

    def run(self):
        try:
            client = WdtClient()
            self.phase.emit("正在拉取库存...")
            records, err = client.fetch_all_stocks(
                progress_cb=lambda f, t: self.progress.emit(f, t)
            )
            if err:
                self.error.emit(err)
                return
            mapped = map_stocks_to_kb(records)
            # 自动归类：按本次涉及的 goods_no 拉取品类映射
            needed = {m.get("goods_no", "").strip() for m in mapped if m.get("goods_no", "").strip()}
            self.phase.emit("正在获取品类（货品档案）...")
            goods_map, _ = client.fetch_goods_class_map(
                needed_goods_no=needed,
                progress_cb=lambda n: self.phase.emit(f"正在获取品类... 已识别 {n} 个货品"),
            )
            self.finished.emit(mapped, goods_map)
        except Exception as e:
            self.error.emit(str(e))


from gui.base_page import BasePage


class BulkMineWorker(BaseWorker):
    """后台线程：遍历所有产品，逐条调用大模型挖掘性能参数与核心卖点。"""
    progress = Signal(int, int, str)   # done, total, current_name
    finished = Signal(int, int)        # success_count, skip_count

    def __init__(self, manager, model, skip_mined=True):
        super().__init__()
        self.manager = manager
        self.model = model
        self.skip_mined = skip_mined

    def run(self):
        from utils.llm_proxy import llm_chat_messages
        import re, json as json_mod
        items = self.manager.all_items()
        total = len(items)
        success = skip = 0
        system_prompt = (
            '你是一个专业的产品规划与营销专家。根据用户提供的产品基本信息，'
            '整理出该产品的【性能参数】与【核心卖点】。\n'
            '严格以纯 JSON 格式输出，不要 Markdown 包装：\n'
            '{"features": "性能参数（Markdown 列表/表格）",'
            ' "selling_points": "核心卖点（3-5点，Markdown 列表）"}'
        )
        for i, item in enumerate(items):
            if self._should_stop:
                break
            name = f"{item.get('brand','')} {item.get('model','')}".strip() or item.get('goods_no','')
            if self.skip_mined and item.get("features", "").strip() and item.get("selling_points", "").strip():
                skip += 1
                self.progress.emit(i + 1, total, f"[跳过] {name}")
                continue
            user_prompt = (
                f'品类：{item.get("category","")}\n品牌：{item.get("brand","")}\n'
                f'型号/货品名称：{item.get("model","")}\n规格名称：{item.get("spec_name","")}\n'
                f'备注：{item.get("notes","")}\n\n请挖掘该产品的【性能参数】与【核心卖点】。'
            )
            try:
                content = llm_chat_messages(
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
                    model=self.model, temperature=0.7, timeout=60
                )
                c = content.strip()
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", c, re.DOTALL)
                c = m.group(1) if m else c[c.find('{'):c.rfind('}')+1] if '{' in c else ""
                parsed = json_mod.loads(c) if c else None
                if parsed and isinstance(parsed, dict):
                    updated = dict(item)
                    updated["features"] = parsed.get("features", "").strip()
                    updated["selling_points"] = parsed.get("selling_points", "").strip()
                    self.manager.update_item(item["id"], updated)
                    success += 1
                    self.progress.emit(i + 1, total, f"[完成] {name}")
                else:
                    self.progress.emit(i + 1, total, f"[解析失败] {name}")
            except Exception as e:
                self.progress.emit(i + 1, total, f"[错误] {name}: {e}")
        self.finished.emit(success, skip)

    _should_stop = False

    def stop(self):
        self._should_stop = True


class ProductLibraryPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.manager = ProductLibraryManager()
        self.current_id = None          # 当前编辑条目 id；None = 新增模式
        self.inputs = {}                # field key -> 输入控件
        self.sync_worker = None
        self.bulk_mine_worker = None

    # ---------------- UI 构建 ----------------
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(16)

        heading = QLabel("📦 产品资料")
        heading.setObjectName("heading")
        root.addWidget(heading)

        subtitle = QLabel("基础数据从旺店通仓库同步（库存 + 品类自动归类），按 品类 → 品牌 → 型号 统一管理，供后续 AI 文案创作调用")
        subtitle.setObjectName("muted_text")
        root.addWidget(subtitle)

        # 顶部：仓库同步条
        sync_bar = QHBoxLayout()
        self.btn_sync = QPushButton("🔄 从仓库同步")
        self.btn_sync.setObjectName("primary_button")
        self.btn_sync.clicked.connect(self._on_sync)
        sync_bar.addWidget(self.btn_sync)
        self.btn_import_excel = QPushButton("📥 导入表格")
        self.btn_import_excel.setObjectName("secondary_button")
        self.btn_import_excel.clicked.connect(self._on_import_excel)
        sync_bar.addWidget(self.btn_import_excel)
        self.btn_export_template = QPushButton("📄 导出模板")
        self.btn_export_template.setObjectName("secondary_button")
        self.btn_export_template.clicked.connect(self._on_export_template)
        sync_bar.addWidget(self.btn_export_template)
        self.btn_mine_all = QPushButton("⚡ 挖掘")
        self.btn_mine_all.setObjectName("secondary_button")
        self.btn_mine_all.setToolTip("批量为所有产品自动挖掘性能参数和核心卖点")
        self.btn_mine_all.clicked.connect(self._on_mine_all)
        sync_bar.addWidget(self.btn_mine_all)
        self.sync_status = QLabel("")
        self.sync_status.setObjectName("muted_text")
        sync_bar.addWidget(self.sync_status, 1)
        root.addLayout(sync_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.refresh_tree()

    def _build_left_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("产品库")
        title.setObjectName("card_title")
        layout.addWidget(title)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 品牌 / 型号 / 编码 / 条码 ...")
        self.search_input.textChanged.connect(self.refresh_tree)
        layout.addWidget(self.search_input)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        layout.addWidget(self.tree, 1)

        btn_new = QPushButton("➕ 新增型号（清空表单）")
        btn_new.setObjectName("secondary_button")
        btn_new.clicked.connect(self.clear_form)
        layout.addWidget(btn_new)

        return panel

    def _build_right_panel(self):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        # Create vertical splitter
        v_splitter = QSplitter(Qt.Vertical)
        
        # --- Top frame: Basic Info ---
        top_panel = QFrame()
        top_panel.setObjectName("card")
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(16, 16, 16, 16)
        top_layout.setSpacing(10)

        title_basic = QLabel("📋 产品基本资料")
        title_basic.setObjectName("card_title")
        top_layout.addWidget(title_basic)

        tip = QLabel("仓库同步的产品：仅「商品名称/型号、品类、备注」可改，其余为仓库只读数据；"
                     "所有修改仅保存在本地，不会回写仓库。")
        tip.setObjectName("muted_text")
        tip.setWordWrap(True)
        top_layout.addWidget(tip)

        form_container = QWidget()
        form_grid = QGridLayout(form_container)
        form_grid.setSpacing(6)
        form_grid.setContentsMargins(0, 0, 0, 0)
        
        # Set stretch factors for the 4 widget columns (1, 3, 5, 7) to distribute space evenly
        form_grid.setColumnStretch(1, 1)
        form_grid.setColumnStretch(3, 1)
        form_grid.setColumnStretch(5, 1)
        form_grid.setColumnStretch(7, 1)

        existing_cats = self.manager.categories()
        basic_fields = [(k, l, m) for k, l, m in FIELDS if k not in ("features", "selling_points")]
        
        # Exact positions for a compact 3-row layout (row, widget_col_index, widget_span)
        # widget_col_index is 0, 1, 2, or 3.
        field_positions = {
            "category":      (0, 0, 1),
            "brand":         (0, 1, 1),
            "model":         (0, 2, 1),
            "goods_no":      (0, 3, 1),
            
            "spec_no":       (1, 0, 1),
            "spec_name":     (1, 1, 1),
            "barcode":       (1, 2, 1),
            "stock_num":     (1, 3, 1),
            
            "available_num": (2, 0, 1),
            "warehouse":     (2, 1, 1),
            "notes":         (2, 2, 2), # Spans widget columns index 2 and 3 (grid columns 5, 6, 7)
        }

        for key, label, multiline in basic_fields:
            req = " *" if key in REQUIRED_FIELDS else ""
            if key == "category":
                w = QComboBox(); w.setEditable(True); w.addItems(existing_cats); w.setCurrentText("")
            elif key == "notes":
                # Convert notes to QLineEdit to fit perfectly on Row 3 alongside other single-line fields
                w = QLineEdit()
            else:
                w = QLineEdit()
            
            self.inputs[key] = w
            lbl = QLabel(label + req)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            row, col_idx, col_span = field_positions[key]
            lbl_col = col_idx * 2
            widget_col = col_idx * 2 + 1
            
            form_grid.addWidget(lbl, row, lbl_col)
            if col_span > 1:
                # Spans multiple columns (specifically for notes: widget_col is 5, spans 3 columns to cover 5, 6, 7)
                form_grid.addWidget(w, row, widget_col, 1, col_span * 2 - 1)
            else:
                form_grid.addWidget(w, row, widget_col)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(form_container)
        top_layout.addWidget(scroll, 1)

        v_splitter.addWidget(top_panel)

        # --- Bottom frame: AI Mining ---
        bottom_panel = QFrame()
        bottom_panel.setObjectName("card")
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(16, 16, 16, 16)
        bottom_layout.setSpacing(10)

        bottom_title_bar = QHBoxLayout()
        title_ai = QLabel("✨ 智能挖掘 (性能参数 & 核心卖点)")
        title_ai.setObjectName("card_title")
        bottom_title_bar.addWidget(title_ai)
        
        self.btn_mine = QPushButton("🪄 智能挖掘")
        self.btn_mine.setObjectName("primary_button")
        self.btn_mine.clicked.connect(self._on_mine)
        bottom_title_bar.addWidget(self.btn_mine)
        bottom_layout.addLayout(bottom_title_bar)

        # Grid layout for AI parameters to support vertical stretching
        grid_ai = QGridLayout()
        grid_ai.setSpacing(10)
        grid_ai.setContentsMargins(0, 0, 0, 0)
        grid_ai.setColumnStretch(1, 1)
        grid_ai.setRowStretch(0, 1)
        grid_ai.setRowStretch(1, 1)

        # Create input widgets for AI fields
        lbl_features = QLabel("性能参数")
        lbl_features.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.inputs["features"] = QTextEdit()
        self.inputs["features"].setPlaceholderText("点击【智能挖掘】自动从大模型获取性能参数，或在此手动输入...")
        self.inputs["features"].setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.inputs["features"].setMinimumHeight(80)
        grid_ai.addWidget(lbl_features, 0, 0)
        grid_ai.addWidget(self.inputs["features"], 0, 1)

        lbl_selling = QLabel("核心卖点")
        lbl_selling.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.inputs["selling_points"] = QTextEdit()
        self.inputs["selling_points"].setPlaceholderText("点击【智能挖掘】自动从大模型获取核心卖点，或在此手动输入...")
        self.inputs["selling_points"].setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.inputs["selling_points"].setMinimumHeight(80)
        grid_ai.addWidget(lbl_selling, 1, 0)
        grid_ai.addWidget(self.inputs["selling_points"], 1, 1)

        bottom_layout.addLayout(grid_ai)
        v_splitter.addWidget(bottom_panel)

        # Set default splitter sizes (e.g. 180px for 3-row top basic info, rest 420px for AI Mining)
        v_splitter.setSizes([180, 420])
        container_layout.addWidget(v_splitter, 1)

        # --- Bottom Button Bar (outside splitter for consistency) ---
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存（新增）")
        self.btn_save.setObjectName("primary_button")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        self.btn_delete = QPushButton("🗑️ 删除")
        self.btn_delete.setObjectName("secondary_button")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_delete)

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("secondary_button")
        btn_clear.clicked.connect(self.clear_form)
        btn_row.addWidget(btn_clear)

        btn_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted_text")
        btn_row.addWidget(self.status_label)
        container_layout.addLayout(btn_row)

        return container

    def _on_mine(self):
        # 1. 确保大模型配置存在
        ai = self.ai_config
        model = ai.get("llm_model", "deepseek-v4-flash")
        if not model:
            QMessageBox.warning(self.parent_widget, "大模型未配置",
                                "请先在“AI 设置 / 大模型配置”中选择模型名称。")
            return

        # 2. 收集当前界面的产品资料作为查询输入
        category = self._get_widget_value(self.inputs.get("category"))
        brand = self._get_widget_value(self.inputs.get("brand"))
        model_name = self._get_widget_value(self.inputs.get("model"))
        spec_name = self._get_widget_value(self.inputs.get("spec_name"))
        notes = self._get_widget_value(self.inputs.get("notes"))

        if not brand or not model_name:
            QMessageBox.warning(self.parent_widget, "信息不足", "请确保产品“品牌”和“型号/货品名称”已填写！")
            return

        # 构建 Prompt
        system_prompt = (
            "你是一个专业的产品规划与营销专家。你的任务是根据用户提供的产品基本信息，进行深度挖掘，整理出该产品的“性能参数”与“核心卖点”。\n"
            "请严格以 JSON 格式输出，不要包含任何 Markdown 格式块包装（如 ```json ... ``` 这种标记，只输出纯 JSON 字符串）。\n"
            "JSON 格式要求如下：\n"
            "{\n"
            "  \"features\": \"产品的性能参数、技术指标、主要材质、规格尺寸等，使用清晰易读的格式（如 Markdown 列表或表格）\",\n"
            "  \"selling_points\": \"核心卖点（针对受众的痛点、核心竞争优势、购买理由，建议列出 3-5 点，使用 Markdown 列表格式）\"\n"
            "}"
        )

        user_prompt = (
            f"产品基本信息如下：\n"
            f"品类：{category}\n"
            f"品牌：{brand}\n"
            f"型号/货品名称：{model_name}\n"
            f"规格名称：{spec_name}\n"
            f"备注：{notes}\n\n"
            f"请帮我挖掘并整理该产品的“性能参数”与“核心卖点”。"
        )

        self.btn_mine.setEnabled(False)
        self.btn_mine.setText("⏳ 正在挖掘...")
        self._set_status("正在调用大模型挖掘产品性能参数与核心卖点...")

        from gui.ai_script_page import LLMWorker

        self.mine_worker = LLMWorker("", "", model, system_prompt, user_prompt)

        def _on_mine_done(content):
            self.btn_mine.setEnabled(True)
            self.btn_mine.setText("🪄 智能挖掘")
            
            # 解析 JSON
            import re
            import json
            parsed = None
            content_clean = content.strip()
            # 兼容带有 ```json 开头的情况
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content_clean, re.DOTALL)
            if match:
                content_clean = match.group(1)
            else:
                start = content_clean.find('{')
                end = content_clean.rfind('}')
                if start != -1 and end != -1:
                    content_clean = content_clean[start:end+1]
            try:
                parsed = json.loads(content_clean)
            except Exception as e:
                log.error(f"解析挖掘结果 JSON 失败: {e}, 原始返回: {content}")

            if parsed and isinstance(parsed, dict):
                features = parsed.get("features", "").strip()
                selling_points = parsed.get("selling_points", "").strip()
                
                self._set_widget_value(self.inputs["features"], features)
                self._set_widget_value(self.inputs["selling_points"], selling_points)
                self._set_status("AI 挖掘成功！请检查并点击“保存修改”保存。")
            else:
                # 解析失败，把原文填充到性能参数中，并给提示
                self._set_widget_value(self.inputs["features"], content)
                self._set_status("AI 挖掘返回格式非标准 JSON，已将原文填入性能参数栏中。")

        def _on_mine_err(err_msg):
            self.btn_mine.setEnabled(True)
            self.btn_mine.setText("🪄 智能挖掘")
            self._set_status(f"挖掘失败：{err_msg}")
            QMessageBox.critical(self.parent_widget, "挖掘失败", f"大模型请求失败：\n{err_msg}")

        self.track_worker(self.mine_worker)
        self.mine_worker.finished.connect(_on_mine_done)
        self.mine_worker.error.connect(_on_mine_err)
        self.mine_worker.start()

    # ---------------- 控件读写 ----------------
    def _get_widget_value(self, w):
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QTextEdit):
            return w.toPlainText().strip()
        return w.text().strip()

    def _set_widget_value(self, w, value):
        value = str(value or "")
        if isinstance(w, QComboBox):
            w.setCurrentText(value)
        elif isinstance(w, QTextEdit):
            w.setPlainText(value)
        else:
            w.setText(value)

    def _collect_form(self):
        return {key: self._get_widget_value(w) for key, w in self.inputs.items()}

    def _fill_form(self, data):
        for key, w in self.inputs.items():
            self._set_widget_value(w, data.get(key, ""))

    # 仓库只读字段：仓库同步的产品里这些不可手工改（仅 商品名称/型号、品类、备注 可改）。
    LOCKABLE_FIELDS = ("brand", "goods_no", "spec_no", "spec_name",
                       "barcode", "stock_num", "available_num", "warehouse")

    def _apply_field_locks(self, warehouse):
        """warehouse=True（仓库同步来的产品）时锁定只读字段；新增/手工录入时全部可改。"""
        for key in self.LOCKABLE_FIELDS:
            w = self.inputs.get(key)
            if w is None:
                continue
            if isinstance(w, QComboBox):
                w.setEnabled(not warehouse)
            else:
                w.setReadOnly(warehouse)

    # ---------------- 树 ----------------
    def refresh_tree(self):
        keyword = self.search_input.text().strip() if hasattr(self, "search_input") else ""
        self.tree.clear()
        if keyword:
            for it in self.manager.search(keyword):
                label = f"{it.get('brand','')} {it.get('model','')}".strip() or "(未命名)"
                node = QTreeWidgetItem([label])
                node.setData(0, Qt.UserRole, it.get("id"))
                self.tree.addTopLevelItem(node)
            self.tree.expandAll()
            return
        tree = self.manager.grouped()
        for cat in sorted(tree.keys()):
            cat_node = QTreeWidgetItem([f"📂 {cat}"])
            cat_node.setData(0, Qt.UserRole, None)
            self.tree.addTopLevelItem(cat_node)
            for brand in sorted(tree[cat].keys()):
                brand_node = QTreeWidgetItem([f"🏷️ {brand}"])
                brand_node.setData(0, Qt.UserRole, None)
                cat_node.addChild(brand_node)
                for it in sorted(tree[cat][brand], key=lambda x: x.get("model", "")):
                    label = it.get("model", "") or it.get("goods_no", "") or "(未命名)"
                    leaf = QTreeWidgetItem([label])
                    leaf.setData(0, Qt.UserRole, it.get("id"))
                    brand_node.addChild(leaf)
        self.tree.expandAll()

    def _on_tree_clicked(self, item, _col):
        item_id = item.data(0, Qt.UserRole)
        if not item_id:
            return
        record = self.manager.get(item_id)
        if not record:
            return
        self.current_id = item_id
        self._fill_form(record)
        is_warehouse = bool(record.get("goods_no") or record.get("spec_no"))
        self._apply_field_locks(is_warehouse)
        self.btn_save.setText("💾 保存修改")
        self._set_status(f"正在编辑：{record.get('brand','')} {record.get('model','')}"
                         + ("（仓库产品：仅可改 商品名称/品类/备注）" if is_warehouse else ""))

    # ---------------- 手动增删改 ----------------
    def clear_form(self):
        self.current_id = None
        for w in self.inputs.values():
            self._set_widget_value(w, "")
        self._apply_field_locks(False)  # 新增/手工录入：全部可改
        self.btn_save.setText("💾 保存（新增）")
        self._set_status("新增模式")

    def _on_save(self):
        data = self._collect_form()
        if self.current_id:
            ok, msg, _ = self.manager.update_item(self.current_id, data)
        else:
            ok, msg, item = self.manager.add_item(data)
            if ok:
                self.current_id = item["id"]
                self.btn_save.setText("💾 保存修改")
        self._set_status(msg)
        if ok:
            self._refresh_combo_choices()
            self.refresh_tree()
        else:
            QMessageBox.warning(self.parent_widget, "无法保存", msg)

    def _on_delete(self):
        if not self.current_id:
            self._set_status("当前为新增模式，无可删除条目。")
            return
        record = self.manager.get(self.current_id)
        name = f"{record.get('brand','')} {record.get('model','')}".strip() if record else ""
        reply = QMessageBox.question(
            self.parent_widget, "确认删除",
            f"确定删除「{name}」吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self.manager.remove_item(self.current_id):
            self._set_status("已删除。")
            self.clear_form()
            self.refresh_tree()
        else:
            self._set_status("删除失败。")

    def _refresh_combo_choices(self):
        for key, getter in (("category", self.manager.categories), ("brand", lambda: self.manager.brands())):
            w = self.inputs.get(key)
            if isinstance(w, QComboBox):
                cur = w.currentText()
                w.blockSignals(True)
                w.clear(); w.addItems(getter()); w.setCurrentText(cur)
                w.blockSignals(False)

    # ---------------- 仓库同步 ----------------
    def _on_sync(self):
        if self.sync_worker and self.sync_worker.isRunning():
            return
        self.btn_sync.setEnabled(False)
        self._set_sync_status("正在连接旺店通仓库...")
        self.sync_worker = StockSyncWorker()
        self.sync_worker.phase.connect(self._set_sync_status)
        self.sync_worker.progress.connect(self._on_sync_progress)
        self.sync_worker.finished.connect(self._on_sync_done)
        self.sync_worker.error.connect(self._on_sync_err)
        self.sync_worker.start()

    def _on_sync_progress(self, fetched, total):
        self._set_sync_status(f"正在拉取库存：{fetched}/{total or '?'}")

    def _on_sync_done(self, mapped_items, goods_map):
        self.btn_sync.setEnabled(True)
        added, updated = self.manager.upsert_stocks(mapped_items)
        categorized = self.manager.apply_categories(goods_map) if goods_map else 0
        self._set_sync_status(
            f"同步完成：新增 {added}、更新 {updated}、自动归类 {categorized}，"
            f"共 {len(self.manager.all_items())} 条。"
        )
        self._refresh_combo_choices()
        self.refresh_tree()

    def _on_sync_err(self, err):
        self.btn_sync.setEnabled(True)
        self._set_sync_status(f"同步失败：{err}")
        log.error(f"仓库库存同步失败: {err}")
        QMessageBox.critical(self.parent_widget, "同步失败",
                             f"从旺店通仓库同步库存失败：\n{err}\n\n"
                             "请检查 config/erp_config.json 中的 appkey/sid/密钥，"
                             "以及当前网络出口 IP 是否在旺店通白名单内。")

    # ---------------- 一键挖掘 ----------------
    def _on_mine_all(self):
        if self.bulk_mine_worker and self.bulk_mine_worker.isRunning():
            self.bulk_mine_worker.stop()
            self.btn_mine_all.setText("⚡ 一键挖掘")
            self.btn_mine_all.setToolTip("批量为所有产品自动挖掘性能参数和核心卖点（跳过已有数据的产品）")
            self._set_sync_status("已请求停止…")
            return
        ai = self.ai_config
        model = ai.get("llm_model", "deepseek-chat")
        if not model:
            QMessageBox.warning(self.parent_widget, "大模型未配置",
                                '请先在【AI 设置 / 大模型配置】中填写模型名称。')
            return
        total = len(self.manager.all_items())
        if total == 0:
            QMessageBox.information(self.parent_widget, "无产品", "产品库为空，请先同步仓库库存。")
            return
        already = sum(1 for it in self.manager.all_items()
                      if it.get("features", "").strip() and it.get("selling_points", "").strip())
        pending = total - already
        reply = QMessageBox.question(
            self.parent_widget, "一键挖掘确认",
            f"共 {total} 个产品，其中 {already} 个已有挖掘数据（将跳过），"
            f"即将为 {pending} 个产品调用大模型挖掘性能参数与核心卖点。\n\n确认开始？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.btn_mine_all.setText("⏹ 停止挖掘")
        self.btn_mine_all.setToolTip("点击停止批量挖掘")
        self._set_sync_status(f"一键挖掘中…（0/{pending}）")
        self.bulk_mine_worker = BulkMineWorker(self.manager, model, skip_mined=True)
        self.bulk_mine_worker.progress.connect(self._on_mine_all_progress)
        self.bulk_mine_worker.finished.connect(self._on_mine_all_done)
        self.bulk_mine_worker.error.connect(self._on_mine_all_err)
        self.track_worker(self.bulk_mine_worker)
        self.bulk_mine_worker.start()

    def _on_mine_all_progress(self, done, total, msg):
        self._set_sync_status(f"一键挖掘中…（{done}/{total}）{msg}")

    def _on_mine_all_done(self, success, skipped):
        self.btn_mine_all.setText("⚡ 一键挖掘")
        self.btn_mine_all.setToolTip("批量为所有产品自动挖掘性能参数和核心卖点（跳过已有数据的产品）")
        self._set_sync_status(f"一键挖掘完成：成功 {success} 条，跳过 {skipped} 条（已有数据）。")
        self.refresh_tree()
        if self.current_id:
            record = self.manager.get(self.current_id)
            if record:
                self._fill_form(record)

    def _on_mine_all_err(self, err):
        self.btn_mine_all.setText("⚡ 一键挖掘")
        self.btn_mine_all.setToolTip("批量为所有产品自动挖掘性能参数和核心卖点（跳过已有数据的产品）")
        self._set_sync_status(f"一键挖掘出错：{err}")

    # ---------------- Excel 导入导出 ----------------

    def _on_export_template(self):
        """导出 Excel 导入模板（当前数据格式）。"""
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        from utils.product_library_manager import FIELDS
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget, "导出导入模板", "产品资料导入模板.xlsx",
            "Excel 文件 (*.xlsx)")
        if not path:
            return
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "产品资料"
        keys = [f[0] for f in FIELDS]    # 内部字段名
        labels = [f[1] for f in FIELDS]  # 中文显示名
        # 表头（中文名）
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col, label in enumerate(labels, 1):
            cell = ws.cell(row=1, column=col, value=label)
            cell.fill = header_fill
            cell.font = header_font
        # 填入一行示例数据
        for col, key in enumerate(keys, 1):
            sample_map = {"category": "鼠标", "brand": "罗技", "model": "G502",
                          "goods_no": "示例GD001", "spec_no": "示例SP001",
                          "spec_name": "示例规格", "barcode": "6901234567890"}
            ws.cell(row=2, column=col, value=sample_map.get(key, f"示例{labels[col-1]}"))
        # 设置列宽
        for col in range(1, len(keys) + 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
        wb.save(path)
        QMessageBox.information(self.parent_widget, "提示",
                                f"模板已导出到：{path}\n\n请按表头格式填写数据，然后使用「导入表格」功能导入。")

    def _on_import_excel(self):
        """从 Excel 导入产品数据。"""
        import openpyxl
        from utils.product_library_manager import ProductLibraryManager, FIELDS
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择 Excel 文件", "",
            "Excel 文件 (*.xlsx *.xls)")
        if not path:
            return
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True))
            field_keys = [f[0] for f in FIELDS]
            imported = 0
            errors = []
            mgr = ProductLibraryManager()
            for i, row in enumerate(rows, 2):
                if all(v is None or str(v).strip() == "" for v in row):
                    continue  # 跳过空行
                item = {}
                for col, key in enumerate(field_keys):
                    val = row[col] if col < len(row) else None
                    item[key] = str(val).strip() if val is not None else ""
                # 至少要有分类+品牌
                if not item.get("category") or not item.get("brand"):
                    errors.append(f"第 {i} 行：分类和品牌不能为空")
                    continue
                mgr.upsert_stocks([item])
                imported += 1
            if imported > 0:
                mgr.save()
                self.refresh_tree()
            msg = f"导入完成：成功 {imported} 条"
            if errors:
                msg += f"\n失败 {len(errors)} 条：\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    msg += f"\n... 还有 {len(errors)-10} 条错误"
            QMessageBox.information(self.parent_widget, "导入结果", msg)
        except Exception as e:
            QMessageBox.critical(self.parent_widget, "导入失败", f"文件读取失败：{e}")

    # ---------------- 杂项 ----------------
    def _set_status(self, text):
        if hasattr(self, "status_label"):
            self.status_label.setText(text)

    def _set_sync_status(self, text):
        if hasattr(self, "sync_status"):
            self.sync_status.setText(text)
