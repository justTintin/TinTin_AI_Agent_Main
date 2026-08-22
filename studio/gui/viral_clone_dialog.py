"""爆款仿制（Viral Clone）：链接/素材 ID → 拆解结构 → 复刻脚本。

- 拆解/复刻走服务端 /viral/clone/analyze + /viral/clone/plan（flow 一条调用优先）
- 视频下载一律由客户端素材浏览器完成（不走服务端）：填链接 → 点
  「在素材浏览器中下载」→ 下载入库后填素材 ID
- 生成（三替换）/组装（剪辑）为占位按钮：服务端 E-3.0 节点引擎就绪后开放
- 右侧新增服务端视频编辑工作流选择器：按 output_type="video" 过滤，
  支持动态表单（image/video/audio/text/select）并通过 workflow_client 统一提交

ViralClonePage：可复用 QWidget 组件（工作台对话框 / 一键成片 Tab 均使用）；
ViralCloneDialog：对话框包装（工作台「爆款仿制」卡片入口）。
"""
from gui.common_widgets import DropZone
from gui.searchable_combo import SearchableComboBox
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from utils import viral_clone_client as vcc
from utils.base_worker import BaseWorker
from utils.file_dialog_utils import pick_file
from utils.gui_icons import mdi_button
from utils.json_utils import to_editor_text
from utils.logger_utils import log


class CloneWorker(QThread):
    """后台执行 run_clone（拆解 + 复刻规划），进度经 signal 回传 UI 线程。"""
    progress = Signal(str)
    result = Signal(object)

    def __init__(self, video_ref, product_info, parent=None):
        super().__init__(parent)
        self.video_ref = video_ref
        self.product_info = product_info

    def run(self):
        try:
            res = vcc.run_clone(self.video_ref, self.product_info,
                                on_log=self.progress.emit)
        except Exception as e:  # 外部 API 调用
            log.exception(f"[仿爆款] 后台执行异常: {e}")
            res = {"ok": False, "error": f"客户端异常：{e}"}
        self.result.emit(res)


class _ProductLoader(QThread):
    """后台加载产品库条目（服务端 /grouped 优先，失败返回空）。"""
    loaded = Signal(object)

    def run(self):
        mgr = None
        items = []
        try:
            from utils.product_library_manager import ProductLibraryManager
            mgr = ProductLibraryManager()
            items = list(mgr.all_items())[:300]
        except Exception as e:  # 动态导入/外部库
            log.warning(f"[仿爆款] 产品库加载失败: {e}")
        self.loaded.emit((mgr, items))


class _LoadVideoWorkflowsWorker(BaseWorker):
    """后台加载服务端视频类工作流（output_type == "video"）。"""
    finished = Signal(list)

    def do_work(self):
        from utils import workflow_client as wfc
        data = wfc.list_workflows(scope="client")
        workflows = (data or {}).get("workflows") or []
        out = []
        for w in workflows:
            if not isinstance(w, dict):
                continue
            item = wfc.normalize_server_workflow(w)
            if item and item.get("output_type") == "video":
                out.append(item)
        self.finished.emit(out)


class _EditWorker(BaseWorker):
    """提交视频编辑工作流 → 轮询结果 → 返回结果。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(dict)

    def __init__(self, workflow_id, files, values):
        super().__init__()
        self.workflow_id = workflow_id
        self.files = files
        self.values = values

    def do_work(self):
        from utils import workflow_client as wfc

        self.phase.emit("正在提交编辑任务…")
        self.progress.emit(10)

        resp = wfc.run_workflow(
            self.workflow_id,
            files=self.files,
            values=self.values,
            timeout=300,
        )
        if not resp or not resp.get("ok"):
            self.error.emit(
                f"提交失败：{resp.get('error', '未知错误') if resp else '无响应'}")
            return

        task_id = resp.get("task_id")
        if not task_id:
            self.error.emit("提交失败：未返回 task_id")
            return
        log.info(f"[仿爆款-编辑] 任务已提交 task_id={task_id}")

        self.phase.emit("编辑中，请稍候…")
        self.progress.emit(30)

        # 轮询任务状态（最多 30 分钟）
        import time
        max_wait = 1800
        start = time.time()
        last_pct = 30
        while time.time() - start < max_wait:
            status = wfc.task_status(task_id, timeout=15)
            data = (status or {}).get("data") or {}
            st = data.get("status") or status.get("status") or ""
            if st in ("SUCCESS", "success", "done", "DONE", "completed"):
                self.progress.emit(100)
                self.phase.emit("编辑完成")
                results = data.get("results") or status.get("results") or []
                self.finished.emit({
                    "ok": True,
                    "task_id": task_id,
                    "results": results,
                    "raw": status,
                })
                return
            if st in ("FAILED", "failed", "error", "ERROR"):
                err = data.get("error") or status.get("error") or "任务失败"
                self.error.emit(f"编辑失败：{err}")
                return
            # 进度推进（平滑显示）
            pct = data.get("progress") or status.get("progress")
            if isinstance(pct, (int, float)) and 0 <= pct <= 100:
                pct = max(last_pct, min(100, int(pct)))
            else:
                elapsed = time.time() - start
                pct = max(last_pct, min(90, 30 + int(elapsed / max_wait * 60)))
            if pct != last_pct:
                self.progress.emit(pct)
                last_pct = pct
            time.sleep(3)

        self.error.emit("编辑超时：任务超过 30 分钟未完成")


class ViralClonePage(QWidget):
    """爆款仿制页面组件。

    左右分栏布局：
      左侧：来源输入 → 操作按钮行（拆解并复刻等）→ 本店产品 → 拆解结果
      右侧：视频编辑工作流选择 → 动态表单 → 提交编辑 → 编辑结果

    可嵌入任意容器（一键成片 Tab / 对话框）。show_close=True 时底部显示关闭按钮
    （对话框模式），作为页面嵌入时不显示。
    """

    def __init__(self, parent_widget=None, main_window=None, show_close=False):
        super().__init__(parent_widget)
        self.main_window = main_window
        self.show_close = show_close
        self._result = None
        self._product_mgr = None
        self._worker = None
        self._loader = None
        self._edit_worker = None
        self._wf_loader = None
        self._workflows = []            # 服务端加载的视频工作流列表
        self._current_workflow = None   # 当前选中的工作流 dict
        self._edit_form_entries = []    # 动态表单条目
        self._added_videos = []         # 已添加的本地视频路径列表
        self.build()

    # ── UI ────────────────────────────────────────────────────────────
    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # 顶部标题
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("爆款仿制（Viral Clone）")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        root.addLayout(title_row)

        sub = QLabel("给一条爆款视频链接或素材 ID → 自动拆解结构（镜头/文案/节奏）→ 生成复刻脚本（保留结构、替换本店产品）；右侧可基于下载视频选择服务端工作流进行编辑处理。")  # noqa: E501
        sub.setStyleSheet("color:#8b93a3; font-size:12px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 左右分栏 ────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        # 左侧：拆解复刻
        left_widget = QWidget()
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)
        self._build_left_pane(left_lay)
        splitter.addWidget(left_widget)

        # 右侧：视频编辑工作流
        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)
        self._build_right_pane(right_lay)
        splitter.addWidget(right_widget)

        # 右侧占满更多空间：左侧 35%，右侧 65%
        splitter.setStretchFactor(0, 35)
        splitter.setStretchFactor(1, 65)
        splitter.setSizes([420, 980])
        root.addWidget(splitter, 1)

        if self.show_close:
            self.btn_close = mdi_button("关闭", "close")
            self.btn_close.clicked.connect(self._on_close)
            root.addWidget(self.btn_close, 0, Qt.AlignRight)

        self._load_products()
        self._load_edit_workflows()

    def _build_left_pane(self, lay: QVBoxLayout):
        """构建左侧：来源 → 按钮行 → 产品 → 状态/输出。"""
        # 爆款视频来源
        src_box = QGroupBox("① 爆款视频来源（链接下载 / 拖入视频 二选一）")
        src_lay = QVBoxLayout(src_box)
        src_lay.setSpacing(10)

        # 方式A：链接 + 素材浏览器中下载（保留原方法）
        link_section = QFrame()
        link_section.setStyleSheet(
            "QFrame { background:#12141d; border:1px solid #252a3d; border-radius:8px; }")
        link_lay = QGridLayout(link_section)
        link_lay.setContentsMargins(10, 10, 10, 10)
        link_lay.setSpacing(8)
        link_lay.addWidget(QLabel("A. 链接下载："), 0, 0)
        self.edit_link = QLineEdit()
        self.edit_link.setPlaceholderText("抖音 / B站 / YouTube / 快手 等链接")
        link_row = QHBoxLayout()
        link_row.setSpacing(6)
        link_row.addWidget(self.edit_link, 1)
        self.btn_download = mdi_button("在素材浏览器中下载", "download")
        self.btn_download.setToolTip(
            "打开客户端素材浏览器下载该视频；下载入库后在下方列表中可看到（下载不走服务端）")
        self.btn_download.clicked.connect(self._on_download)
        link_row.addWidget(self.btn_download)
        link_lay.addLayout(link_row, 0, 1)
        src_lay.addWidget(link_section)

        # 方式B：拖入视频（智能混剪风格的 DropZone）
        drop_section = QFrame()
        drop_section.setStyleSheet(
            "QFrame { background:#12141d; border:1px solid #252a3d; border-radius:8px; }")
        drop_lay = QVBoxLayout(drop_section)
        drop_lay.setContentsMargins(10, 10, 10, 10)
        drop_lay.setSpacing(6)
        drop_lay.addWidget(QLabel("B. 拖入本地视频 / 点击选择："))
        self.video_drop_zone = DropZone(
            ("mp4", "mov", "avi", "mkv", "flv", "webm", "m4v"),
            hint="拖入视频素材 或 点击选择",
            min_height=72,
        )
        self.video_drop_zone.clicked.connect(self._pick_local_video)
        self.video_drop_zone.file_dropped.connect(self._on_local_videos_dropped)
        drop_lay.addWidget(self.video_drop_zone)
        # 兼容保留原来的素材ID输入（隐藏的，用于已有逻辑填充）
        self.edit_material = QLineEdit()
        self.edit_material.setVisible(False)  # 保留字段但不显示
        self.edit_material.textChanged.connect(self._on_material_changed)
        drop_lay.addWidget(self.edit_material)
        src_lay.addWidget(drop_section)

        # 已添加/已下载的视频预览列表
        self.video_list_label = QLabel("已添加视频（0 个）：")
        self.video_list_label.setStyleSheet("color:#8b93a3; font-size:12px;")
        src_lay.addWidget(self.video_list_label)
        self.video_list_widget = QListWidget()
        self.video_list_widget.setViewMode(QListWidget.IconMode)
        self.video_list_widget.setResizeMode(QListWidget.Adjust)
        self.video_list_widget.setMovement(QListWidget.Static)
        self.video_list_widget.setIconSize(QSize(160, 90))
        self.video_list_widget.setSpacing(8)
        self.video_list_widget.setUniformItemSizes(False)
        self.video_list_widget.setFixedHeight(130)
        self.video_list_widget.setStyleSheet(
            "QListWidget { background:#12141d; border:1px solid #252a3d; border-radius:8px;"
            " padding:6px; }"
            " QListWidget::item { background:#1a1e2e; border:1px solid #2c3344;"
            " border-radius:6px; padding:4px; color:#c8cbd6; font-size:11px; }"
            " QListWidget::item:selected { border-color:#5b6cff; }"
        )
        src_lay.addWidget(self.video_list_widget)

        hint = QLabel("提示：链接下载一律由客户端素材浏览器完成（不走服务端）；本地视频拖入后自动作为拆解来源，同时会同步到右侧编辑工作流的 video 字段。")  # noqa: E501
        hint.setStyleSheet("color:#6b7280; font-size:11px;")
        hint.setWordWrap(True)
        src_lay.addWidget(hint)
        lay.addWidget(src_box)

        # 操作按钮行（放在本店产品上方，需求 #1）
        ops_box = QFrame()
        ops_box.setStyleSheet(
            "QFrame { background:#151827; border:1px solid #252a3d; border-radius:10px; }")
        ops_lay = QHBoxLayout(ops_box)
        ops_lay.setContentsMargins(12, 10, 12, 10)
        ops_lay.setSpacing(8)
        self.btn_run = mdi_button("拆解并复刻", "fire")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.setFixedHeight(34)
        self.btn_run.clicked.connect(self._on_run)
        ops_lay.addWidget(self.btn_run)
        self.btn_generate = mdi_button("生成素材（占位）", "creation")
        self.btn_generate.setToolTip("三替换素材生成：服务端 E-3.0 节点引擎就绪后开放")
        self.btn_generate.clicked.connect(self._on_generate)
        ops_lay.addWidget(self.btn_generate)
        self.btn_montage = mdi_button("组装成片（占位）", "film")
        self.btn_montage.setToolTip("复刻素材组装：服务端 E-3.0 节点引擎就绪后开放")
        self.btn_montage.clicked.connect(self._on_montage)
        ops_lay.addWidget(self.btn_montage)
        self.btn_copy = mdi_button("复制复刻脚本", "content-copy")
        self.btn_copy.setToolTip("把当前复刻脚本 JSON 复制到剪贴板")
        self.btn_copy.clicked.connect(self._on_copy)
        ops_lay.addWidget(self.btn_copy)
        ops_lay.addStretch(1)
        lay.addWidget(ops_box)

        # 本店产品
        prod_box = QGroupBox("② 本店产品（替换爆款中的产品）")
        prod_lay = QGridLayout(prod_box)
        prod_lay.setSpacing(8)
        self.combo_product = SearchableComboBox(placeholder="搜索选择本店产品…")
        prod_lay.addWidget(QLabel("产品："), 0, 0)
        prod_lay.addWidget(self.combo_product, 0, 1)
        self.edit_product = QLineEdit()
        self.edit_product.setPlaceholderText("或手动输入产品描述（品牌/型号/核心卖点）…")
        prod_lay.addWidget(QLabel("自定义："), 1, 0)
        prod_lay.addWidget(self.edit_product, 1, 1)
        lay.addWidget(prod_box)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#8b93a3; font-size:12px;")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.output = QTextBrowser()
        self.output.setOpenExternalLinks(True)
        self.output.setStyleSheet(
            "QTextBrowser { background:#12141d; border:1px solid #2c3344;"
            " border-radius:8px; padding:10px; font-family:Consolas,monospace; font-size:12px; }"
        )
        lay.addWidget(self.output, 1)

    def _build_right_pane(self, lay: QVBoxLayout):
        """构建右侧：视频编辑工作流选择 + 动态表单 + 提交 + 结果。"""
        edit_box = QGroupBox("③ 视频编辑工作流（处理下载/拆解的视频）")
        edit_lay = QVBoxLayout(edit_box)
        edit_lay.setSpacing(10)
        edit_lay.setContentsMargins(14, 14, 14, 14)

        # 工作流选择行
        wf_row = QHBoxLayout()
        wf_row.setSpacing(8)
        wf_row.addWidget(QLabel("选择工作流："))
        self.wf_selector = SearchableComboBox(placeholder="加载中…")
        self.wf_selector.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.wf_selector.currentIndexChanged.connect(self._on_wf_changed)
        wf_row.addWidget(self.wf_selector, 1)
        self.btn_wf_refresh = mdi_button("刷新", "refresh")
        self.btn_wf_refresh.setToolTip("重新从服务端加载视频编辑工作流")
        self.btn_wf_refresh.clicked.connect(self._load_edit_workflows)
        wf_row.addWidget(self.btn_wf_refresh)
        edit_lay.addLayout(wf_row)

        # 工作流描述
        self.lbl_wf_desc = QLabel("（请先选择一个工作流）")
        self.lbl_wf_desc.setStyleSheet(
            "color:#6b7280; font-size:11px; background:#12141d;"
            " border:1px solid #252a3d; border-radius:6px; padding:8px;")
        self.lbl_wf_desc.setWordWrap(True)
        self.lbl_wf_desc.setMinimumHeight(44)
        edit_lay.addWidget(self.lbl_wf_desc)

        # 动态表单容器
        self.edit_form_widget = QWidget()
        self.edit_form_widget.setStyleSheet(
            "QWidget { background:#12141d; border:1px solid #252a3d; border-radius:8px; }"
        )
        self.edit_form_layout = QGridLayout(self.edit_form_widget)
        self.edit_form_layout.setContentsMargins(12, 12, 12, 12)
        self.edit_form_layout.setSpacing(8)
        edit_lay.addWidget(self.edit_form_widget)

        # 提交按钮
        submit_row = QHBoxLayout()
        submit_row.setSpacing(8)
        self.btn_edit_submit = mdi_button("提交编辑任务", "play-circle")
        self.btn_edit_submit.setObjectName("primary_button")
        self.btn_edit_submit.setFixedHeight(34)
        self.btn_edit_submit.clicked.connect(self._on_edit_submit)
        self.btn_edit_submit.setEnabled(False)
        submit_row.addWidget(self.btn_edit_submit)
        submit_row.addStretch(1)
        edit_lay.addLayout(submit_row)

        # 进度条
        self.edit_progress = QProgressBar()
        self.edit_progress.setRange(0, 100)
        self.edit_progress.setValue(0)
        self.edit_progress.setTextVisible(True)
        self.edit_progress.setFixedHeight(20)
        self.edit_progress.setStyleSheet(
            "QProgressBar { background:#12141d; border:1px solid #2c3344; border-radius:6px;"
            " text-align:center; color:#8b93a3; font-size:11px; }"
            " QProgressBar::chunk { background:linear-gradient(90deg,#5b6cff,#8b5cf6);"
            " border-radius:6px; }"
        )
        edit_lay.addWidget(self.edit_progress)

        # 状态/结果
        self.lbl_edit_status = QLabel("等待提交…")
        self.lbl_edit_status.setStyleSheet("color:#8b93a3; font-size:12px;")
        self.lbl_edit_status.setWordWrap(True)
        edit_lay.addWidget(self.lbl_edit_status)

        self.edit_output = QTextBrowser()
        self.edit_output.setOpenExternalLinks(True)
        self.edit_output.setStyleSheet(
            "QTextBrowser { background:#12141d; border:1px solid #2c3344;"
            " border-radius:8px; padding:10px; font-family:Consolas,monospace; font-size:12px; }"
        )
        self.edit_output.setMinimumHeight(180)
        edit_lay.addWidget(self.edit_output, 1)

        lay.addWidget(edit_box, 1)

    # ── 关闭（对话框模式）─────────────────────────────────────────────
    def _on_close(self):
        dlg = self.window()
        if isinstance(dlg, QDialog):
            dlg.reject()

    # ── 产品库加载 ────────────────────────────────────────────────────
    def _load_products(self):
        self._loader = _ProductLoader(self)
        self._loader.loaded.connect(self._on_products_loaded)
        self._loader.start()

    def _on_products_loaded(self, payload):
        mgr, items = payload
        self._product_mgr = mgr
        self.combo_product.setItems([
            (f"{it.get('brand','')} / {it.get('model') or it.get('name') or it.get('title','')}".strip(" /"),  # noqa: E501
             it)
            for it in items
            if it.get("brand") or it.get("model") or it.get("name") or it.get("title")
        ])
        if items:
            self.lbl_status.setText(f"就绪（产品库已加载 {len(items)} 条）")
        else:
            self.lbl_status.setText("就绪（产品库为空，可使用自定义产品描述）")

    # ── 视频编辑工作流加载 ────────────────────────────────────────────
    def _load_edit_workflows(self):
        """从服务端加载视频工作流列表。"""
        self.btn_wf_refresh.setEnabled(False)
        self.wf_selector.clear()
        self.wf_selector.setPlaceholderText("正在从服务端加载工作流…")
        self._current_workflow = None
        self.btn_edit_submit.setEnabled(False)
        self._clear_edit_form()
        if getattr(self, "_wf_loader", None) is not None:
            try:
                self._wf_loader.abort()
            except Exception:
                pass

        loader = _LoadVideoWorkflowsWorker()
        self._wf_loader = loader

        def on_done(items):
            self._workflows = items or []
            self.btn_wf_refresh.setEnabled(True)
            if not self._workflows:
                self.wf_selector.setPlaceholderText("服务端暂无视频编辑工作流")
                self.lbl_edit_status.setText(
                    "未加载到工作流：请确认 compute_server_url 配置且服务端已启动"
                    " 并存在 output_type=video 的工作流")
                return
            self.wf_selector.setItems([
                (f"{w.get('name') or w.get('id')}{'  [' + w['backend'] + ']' if w.get('backend') else ''}",  # noqa: E501
                 w)
                for w in self._workflows
            ])
            self.lbl_edit_status.setText(
                f"已加载 {len(self._workflows)} 个视频编辑工作流，请选择并填写参数后提交")

        loader.finished.connect(on_done)
        loader.start()

    def _on_wf_changed(self, idx: int):
        """工作流选择变化 → 更新描述 + 重建动态表单。"""
        item = self.wf_selector.currentData()
        if not isinstance(item, dict):
            self._current_workflow = None
            self.lbl_wf_desc.setText("（请先选择一个工作流）")
            self._clear_edit_form()
            self.btn_edit_submit.setEnabled(False)
            return
        self._current_workflow = item
        desc = item.get("description") or "（工作流未提供描述）"
        backend = item.get("backend") or "-"
        itype = item.get("instanceType") or item.get("instance_type") or "default"
        self.lbl_wf_desc.setText(f"【{backend.upper()}】实例：{itype}\n{desc}")
        self._build_edit_form(item)
        self.btn_edit_submit.setEnabled(True)

    def _clear_edit_form(self):
        while self.edit_form_layout.count():
            child = self.edit_form_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        self._edit_form_entries = []

    def _build_edit_form(self, workflow: dict):
        """根据工作流 inputs 构建动态表单（image/video/audio/text/select）。"""
        self._clear_edit_form()
        inputs = workflow.get("inputs") or []
        row = 0

        # 默认预置 video 字段：取左侧素材 ID / 链接，若为空留空让用户填
        default_video_path = ""
        mid = (self.edit_material.text() or "").strip()
        if mid:
            default_video_path = mid
        elif (self.edit_link.text() or "").strip():
            # 链接还没下载入库时不作为默认值（避免用户误用）
            default_video_path = ""

        # 若工作流没有显式 inputs，提供一个默认的 video 字段
        if not inputs:
            inputs = [{
                "key": "video",
                "kind": "video",
                "label": "视频文件/素材 ID",
                "required": True,
                "placeholder": "填入素材库 ID 或本地视频绝对路径",
            }]

        for inp in inputs:
            key = inp.get("key") or f"field_{row}"
            kind = (inp.get("kind") or "text").lower()
            label = inp.get("label") or key
            required = bool(inp.get("required", False))
            placeholder = inp.get("placeholder") or ""
            suffix = " *" if required else ""
            lbl_widget = QLabel(f"{label}{suffix}:")
            lbl_widget.setStyleSheet("color:#c8cbd6; font-size:12px;")
            self.edit_form_layout.addWidget(lbl_widget, row, 0)

            if kind in ("image", "video", "audio"):
                # 文件类：路径输入 + 选择按钮
                line = QLineEdit()
                line.setPlaceholderText(placeholder or f"选择{kind}文件路径 / 素材 ID")
                if kind == "video" and default_video_path:
                    line.setText(default_video_path)
                pick_btn = mdi_button("…", "folder-open-outline")
                pick_btn.setToolTip(f"选择本地{kind}文件")
                pick_btn.setFixedWidth(36)
                pick_btn.clicked.connect(
                    lambda _checked=False, k=key, w=line, kd=kind: self._pick_edit_file(k, w, kd))
                field_row = QHBoxLayout()
                field_row.setSpacing(4)
                field_row.addWidget(line, 1)
                field_row.addWidget(pick_btn)
                self.edit_form_layout.addLayout(field_row, row, 1)
                self._edit_form_entries.append({
                    "key": key, "kind": kind, "widget": line, "required": required,
                })
            elif kind == "select":
                combo = QComboBox()
                options = inp.get("options") or []
                for opt in options:
                    if isinstance(opt, (list, tuple)) and len(opt) >= 2:
                        combo.addItem(str(opt[0]), opt[1])
                    else:
                        combo.addItem(str(opt), opt)
                default_val = inp.get("default")
                if default_val is not None:
                    i = combo.findData(default_val)
                    if i < 0:
                        i = combo.findText(str(default_val))
                    if i >= 0:
                        combo.setCurrentIndex(i)
                self.edit_form_layout.addWidget(combo, row, 1)
                self._edit_form_entries.append({
                    "key": key, "kind": kind, "widget": combo, "required": required,
                })
            else:
                # 文本类
                line = QLineEdit()
                line.setPlaceholderText(placeholder or f"输入{label}")
                default_val = inp.get("default")
                if default_val is not None:
                    line.setText(str(default_val))
                self.edit_form_layout.addWidget(line, row, 1)
                self._edit_form_entries.append({
                    "key": key, "kind": kind, "widget": line, "required": required,
                })
            row += 1

        # 占位一行防止表单过空
        if row == 0:
            tip = QLabel("（当前工作流无可配置参数，可直接提交）")
            tip.setStyleSheet("color:#6b7280; font-size:11px;")
            self.edit_form_layout.addWidget(tip, 0, 0, 1, 2)

    def _pick_edit_file(self, key: str, widget: QLineEdit, kind: str):
        """文件选择按钮回调：填入路径到指定 widget。"""
        if kind == "image":
            filters = "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        elif kind == "audio":
            filters = "音频 (*.mp3 *.wav *.aac *.flac *.m4a *.ogg)"
        else:
            filters = "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.flv)"
        path = pick_file(self, f"选择{kind}文件", "", filters)
        if path:
            widget.setText(path)

    # ── 本地视频拖入/选择（智能混剪风格）─────────────────────────────
    def _pick_local_video(self):
        """点击 DropZone → 弹出文件选择对话框选择本地视频。"""
        filters = "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v)"
        paths = pick_file(self, "选择本地视频", "", filters, multi=True)
        if paths:
            self._add_local_videos(list(paths) if isinstance(paths, (list, tuple)) else [paths])

    def _on_local_videos_dropped(self, paths):
        """DropZone 拖入视频 → 去重加入已添加列表。"""
        if not paths:
            return
        self._add_local_videos(list(paths))

    def _add_local_videos(self, paths):
        """把一组本地视频路径去重加入到列表 → 刷新预览 → 同步到右侧表单。"""
        import os
        added_any = False
        for p in paths:
            p = p.strip()
            if not p:
                continue
            if not os.path.isfile(p):
                self.lbl_status.setText(f"跳过不存在的文件：{os.path.basename(p)}")
                continue
            if p not in self._added_videos:
                self._added_videos.append(p)
                added_any = True
        if added_any:
            self._refresh_video_list_widget()
            # 取第一个视频路径自动填充到右侧 video 字段
            first = self._added_videos[0]
            # 同时写 edit_material，让现有 _on_material_changed 逻辑也能触发
            self.edit_material.setText(first)

    def _refresh_video_list_widget(self):
        """根据 self._added_videos 刷新预览列表。"""
        import os
        widget = self.video_list_widget
        widget.clear()
        for path in self._added_videos:
            name = os.path.basename(path)
            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
            except OSError:
                size_mb = 0
            label_text = f"{name}\n{size_mb:.1f}MB"
            item = QListWidgetItem(label_text)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            widget.addItem(item)
        self.video_list_label.setText(
            f"已添加视频（{len(self._added_videos)} 个）：点击列表项可移除"
        )

    # ── 下载（客户端素材浏览器，不走服务端）─────────────────────────
    def _on_download(self):
        url = self.edit_link.text().strip()
        ok, msg, dl_dir = vcc.open_in_asset_browser(url or None, topic="爆款仿制")
        self.lbl_status.setText(msg)
        self.output.append(f"\n{msg}")
        if ok and dl_dir:
            self.output.append(f"下载目录：{dl_dir}")
            # 扫描下载目录中的视频文件，自动加入预览列表（用户也可手动拖入）
            import os
            v_ext = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v"}
            found = []
            try:
                for name in os.listdir(dl_dir):
                    p = os.path.join(dl_dir, name)
                    if os.path.isfile(p) and os.path.splitext(name)[1].lower() in v_ext:
                        found.append(p)
            except OSError as e:
                self.output.append(f"[提示] 扫描下载目录失败：{e}")
            if found:
                self._add_local_videos(found)
                self.output.append(f"[自动] 发现 {len(found)} 个视频，已加入下方预览列表")
        if ok:
            self.output.append("下载完成后可在下方列表中直接选择视频；或在素材浏览器中入库后填素材 ID 继续")

    def _on_material_changed(self, text: str):
        """素材 ID 变化 → 同步填充到右侧编辑表单的 video 字段（若存在）。"""
        if not text:
            return
        for ent in self._edit_form_entries:
            if ent.get("kind") == "video" and ent.get("key") == "video":
                w = ent.get("widget")
                if isinstance(w, QLineEdit) and not (w.text() or "").strip():
                    w.setText(text.strip())
                    break

    # ── 输入组装 ──────────────────────────────────────────────────────
    def _video_ref(self):
        # 优先：本地拖入的视频（使用第一个路径）
        if self._added_videos:
            return self._added_videos[0]
        link = self.edit_link.text().strip()
        mid = self.edit_material.text().strip()
        if mid:
            return mid
        return link

    def _product_info(self):
        item = self.combo_product.currentData()
        if item is not None and self._product_mgr is not None:
            try:
                return self._product_mgr.to_prompt_text(item)
            except (KeyError, TypeError, AttributeError):
                pass
        custom = self.edit_product.text().strip()
        if custom:
            return custom
        return ""

    def _set_running(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_generate.setEnabled(not running)
        self.btn_montage.setEnabled(not running)

    def _collect_edit_payload(self):
        """收集动态表单值 → (files, values, error_msg)。"""
        files: dict = {}
        values: dict = {}
        errors = []
        for ent in self._edit_form_entries:
            key = ent["key"]
            kind = ent["kind"]
            widget = ent["widget"]
            required = ent.get("required", False)

            if kind in ("image", "video", "audio"):
                path = (widget.text() or "").strip() if hasattr(widget, "text") else ""
                if not path:
                    if required:
                        errors.append(f"{ent.get('label') or key} 为必填项")
                    continue
                # 判断是本地路径（含分隔符或扩展名）还是素材 ID（纯数字）
                if ("/" in path or "\\" in path
                        or path.lower().rsplit(".", 1)[-1]
                        in {"mp4", "mov", "mkv", "avi", "webm", "flv",
                            "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff",
                            "mp3", "wav", "aac", "flac", "m4a", "ogg"}):
                    import os
                    if os.path.isfile(path):
                        files[key] = path
                    else:
                        if required:
                            errors.append(f"{ent.get('label') or key} 文件不存在：{path}")
                        else:
                            # 非必填文件不存在 → 当素材 ID 或字符串参数透传
                            values[key] = path
                else:
                    # 素材 ID / 远程标识 → 作为 value 传递，由服务端解析
                    values[key] = path
            elif kind == "select":
                v = widget.currentData() if hasattr(widget, "currentData") else None
                if v is None and hasattr(widget, "currentText"):
                    v = widget.currentText()
                if v is None or (isinstance(v, str) and not v.strip()):
                    if required:
                        errors.append(f"{ent.get('label') or key} 请选择一个选项")
                    continue
                values[key] = str(v)
            else:
                v = (widget.text() or "").strip() if hasattr(widget, "text") else ""
                if not v:
                    if required:
                        errors.append(f"{ent.get('label') or key} 为必填项")
                    continue
                values[key] = v
        return files, values, ("；".join(errors) if errors else "")

    # ── 动作：拆解复刻 ────────────────────────────────────────────────
    def _on_run(self):
        ref = self._video_ref()
        if not ref:
            QMessageBox.warning(self, "缺少输入", "请填写爆款视频链接或素材 ID")
            return
        if not self._product_info():
            QMessageBox.warning(self, "缺少产品", "请选择本店产品或填写自定义产品描述")
            return
        self._set_running(True)
        self.lbl_status.setText("正在拆解爆款…（链接需先下载入库，可能较久）")
        self.output.clear()
        self._result = None
        self._worker = CloneWorker(ref, self._product_info(), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_result)
        self._worker.start()

    def _on_progress(self, msg):
        self.lbl_status.setText(msg)
        self.output.append(f"{msg}")

    def _on_result(self, res):
        self._set_running(False)
        self._result = res
        if not res.get("ok"):
            if res.get("need_download"):
                msg = (res.get("error") or "请先在客户端素材浏览器中下载视频") + "；点「在素材浏览器中下载」完成下载入库后，填素材 ID 重试"  # noqa: E501
                self.lbl_status.setText(msg)
                self.output.append(f"\n{msg}")
            elif res.get("need_login") or res.get("captcha"):
                self.lbl_status.setText(res.get("error") or "抖音风控，请先完成登录/验证")
                self.output.append(f"\n{res.get('error') or '抖音风控'}")
            else:
                self.lbl_status.setText(f"{res.get('error') or '执行失败'}")
                self.output.append(f"\n{res.get('error') or '执行失败'}")
            return
        self.lbl_status.setText("拆解 + 复刻脚本完成（生成/组装待服务端 E-3.0 开放）")
        self._render_result(res)

    def _render_result(self, res):
        parts = []
        parts.append("══ 爆款结构（structure）══")
        parts.append(to_editor_text(res.get("structure") or {}))
        parts.append("")
        parts.append("══ 复刻脚本（script）══")
        parts.append(to_editor_text(res.get("script") or {}))
        self.output.setPlainText("\n".join(parts))

    def _on_generate(self):
        if not self._result or not self._result.get("script"):
            QMessageBox.information(self, "占位", "请先执行「拆解并复刻」拿到复刻脚本")
            return
        res = vcc.generate(self._result["script"])
        self.lbl_status.setText(f"生成素材：{res['reason']}")
        self.output.append(f"\n生成素材（占位）：{res['reason']}")

    def _on_montage(self):
        if not self._result:
            QMessageBox.information(self, "占位", "请先执行「拆解并复刻」")
            return
        res = vcc.montage({"script": self._result.get("script")})
        self.lbl_status.setText(f"组装成片：{res['reason']}")
        self.output.append(f"\n组装成片（占位）：{res['reason']}")

    def _on_copy(self):
        if not self._result or not self._result.get("script"):
            QMessageBox.information(self, "复制", "暂无可复制的复刻脚本")
            return
        QApplication.clipboard().setText(
            to_editor_text(self._result["script"]))
        self.lbl_status.setText("复刻脚本已复制到剪贴板")

    # ── 动作：视频编辑工作流提交 ─────────────────────────────────────
    def _on_edit_submit(self):
        if not self._current_workflow:
            QMessageBox.warning(self, "未选择工作流", "请先在右侧选择一个视频编辑工作流")
            return
        files, values, err = self._collect_edit_payload()
        if err:
            QMessageBox.warning(self, "参数不完整", err)
            return
        if not files and not values:
            QMessageBox.warning(self, "缺少输入", "请至少填写一个编辑参数（视频文件/素材 ID）")
            return

        # 中止已在运行的编辑任务
        if getattr(self, "_edit_worker", None) is not None:
            try:
                self._edit_worker.abort()
            except Exception:
                pass

        self.btn_edit_submit.setEnabled(False)
        self.btn_wf_refresh.setEnabled(False)
        self.edit_progress.setValue(0)
        self.lbl_edit_status.setText(f"正在提交编辑工作流：{self._current_workflow.get('name')}")
        self.edit_output.append(
            f"\n═══ {self._current_workflow.get('name')} "
            f"(id={self._current_workflow.get('id')}) ===")
        self.edit_output.append(f"提交文件字段：{list(files.keys())}")
        self.edit_output.append(f"提交值字段：{sorted(values.keys())}")

        wf_id = self._current_workflow["id"]
        itype = self._current_workflow.get("instanceType") or "default"
        values_w_itype = dict(values)
        values_w_itype.setdefault("instance_type", itype)

        worker = _EditWorker(wf_id, files, values_w_itype)
        self._edit_worker = worker

        def on_phase(msg):
            self.lbl_edit_status.setText(msg)
            self.edit_output.append(msg)

        def on_progress(pct):
            self.edit_progress.setValue(max(0, min(100, int(pct))))

        def on_done(payload):
            self.btn_edit_submit.setEnabled(True)
            self.btn_wf_refresh.setEnabled(True)
            self.edit_progress.setValue(100)
            ok = bool(payload and payload.get("ok"))
            task_id = (payload or {}).get("task_id", "")
            self.lbl_edit_status.setText(
                f"编辑任务完成：{task_id}" if ok else "编辑失败")
            self.edit_output.append("")
            self.edit_output.append("══ 编辑结果 ══")
            if payload:
                self.edit_output.append(to_editor_text(payload))
            else:
                self.edit_output.append("（无返回结果）")

        def on_error(msg):
            self.btn_edit_submit.setEnabled(True)
            self.btn_wf_refresh.setEnabled(True)
            self.lbl_edit_status.setText(f"编辑失败：{msg}")
            self.edit_output.append(f"\n[错误] {msg}")
            try:
                QMessageBox.critical(self, "编辑失败", msg)
            except Exception:
                pass

        worker.phase.connect(on_phase)
        worker.progress.connect(on_progress)
        worker.finished.connect(on_done)
        worker.error.connect(on_error)
        worker.start()


class ViralCloneDialog(QDialog):
    """爆款仿制对话框（工作台「爆款仿制」卡片入口），内部复用 ViralClonePage。"""

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("爆款仿制（Viral Clone）")
        self.resize(1400, 880)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.page = ViralClonePage(self, main_window=main_window, show_close=True)
        lay.addWidget(self.page)
