# -*- coding: utf-8 -*-
"""
向量检索页面（page 40）

三个搜索模式（Tab）：
  文字语义检索 — Chinese-CLIP 文字向量搜索
  标签检索     — 按品牌 / 型号 / 类别 / AI状态 精确或模糊查询
  目录查询     — 按路径前缀列出数据库中该目录下所有素材及标签
"""
import os
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSpinBox, QComboBox, QFileDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QColor

from gui.base_page import BasePage
from utils.base_worker import BaseWorker


# ── Workers ───────────────────────────────────────────────────────────────────

class _VectorSearchWorker(BaseWorker):
    """Chinese-CLIP 文字向量检索。"""
    finished = Signal(list)

    def __init__(self, query: str, top_k: int, path_prefix: str,
                 brand: str, category: str, hash_prefix: str = ""):
        super().__init__()
        self.query       = query
        self.top_k       = top_k
        self.path_prefix = path_prefix
        self.brand       = brand or None
        self.category    = category or None
        self.hash_prefix = hash_prefix

    def do_work(self):
        from utils.material_clip_indexer import search_by_text
        results = search_by_text(
            self.query, top_k=self.top_k,
            filter_brand=self.brand,
            filter_category=self.category,
        )
        if self.path_prefix:
            prefix = self.path_prefix.strip()
            results = [r for r in results if r.get("path", "").startswith(prefix)]
        if self.hash_prefix:
            hp = self.hash_prefix.strip().lower()
            results = [r for r in results if r.get("file_hash", "").lower().startswith(hp)]
        self.finished.emit(results)


class _TagSearchWorker(BaseWorker):
    """按品牌/型号/类别/状态标签查询数据库。"""
    finished = Signal(list)

    def __init__(self, brand: str, model: str, category: str,
                 ai_status: str, limit: int, hash_prefix: str = ""):
        super().__init__()
        self.brand       = brand or None
        self.model       = model or None
        self.category    = category or None
        self.ai_status   = ai_status or None
        self.limit       = limit
        self.hash_prefix = hash_prefix

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer() as idx:
            rows = idx.search_by_tags(
                brand=self.brand, model=self.model,
                category=self.category, ai_status=self.ai_status,
                limit=self.limit, hash_prefix=self.hash_prefix,
            )
        self.finished.emit(rows)


class _DirQueryWorker(BaseWorker):
    """按路径前缀从 DB 列出素材。"""
    finished = Signal(list)

    def __init__(self, path_prefix: str, limit: int = 100, hash_prefix: str = ""):
        super().__init__()
        self.path_prefix = path_prefix
        self.limit       = limit
        self.hash_prefix = hash_prefix

    def do_work(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer() as idx:
            rows = idx.list_materials(
                path_prefix=self.path_prefix,
                limit=self.limit,
                hash_prefix=self.hash_prefix
            )
        self.finished.emit(rows)


class _KeywordSearchWorker(BaseWorker):
    """关键词模糊搜索：对文件名/描述/品牌/型号做 LIKE 匹配。"""
    finished = Signal(list)

    def __init__(self, keyword: str, limit: int = 100,
                 file_type: str = "", brand: str = "", model: str = "",
                 category: str = "", ai_status: str = ""):
        super().__init__()
        self.keyword = keyword.strip()
        self.limit = limit
        self.file_type = file_type
        self.brand = brand.strip() or None
        self.model = model.strip() or None
        self.category = category.strip() or None
        self.ai_status = ai_status or None

    def do_work(self):
        if not self.keyword:
            self.finished.emit([])
            return
        from utils.material_clip_indexer import MaterialClipIndexer
        with MaterialClipIndexer() as idx:
            rows = idx.search_by_keyword(
                self.keyword, self.limit,
                file_type=self.file_type, brand=self.brand,
                model=self.model, category=self.category,
                ai_status=self.ai_status)
        self.finished.emit(rows)


# ── 主页面 ────────────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "pending":  "#f59e0b",
    "analyzed": "#22c55e",
    "failed":   "#ef4444",
}

_TABLE_COLS     = ["文件名", "主要画面描述", "次要画面描述", "品牌", "型号", "类别", "置信度", "相似度", "AI状态", "Hash", "路径"]
_TABLE_COLS_IDX = {n: i for i, n in enumerate(_TABLE_COLS)}


class VectorSearchPage(BasePage):
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("🔍 向量检索")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hdr.addStretch()
        sub = QLabel("语义搜索 · 标签筛选 · 目录查询")
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        root.addLayout(hdr)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_text_tab(),     "🔎 文字语义检索")
        self._tabs.addTab(self._build_tag_tab(),      "🏷️ 标签检索")
        self._tabs.addTab(self._build_keyword_tab(),  "🔤 关键词检索")
        self._tabs.addTab(self._build_dir_tab(),      "📂 目录查询")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, 1)

        self._load_tag_options()

    def _on_tab_changed(self, index):
        if index == 1:
            self._load_tag_options()

    # ── Tab 1：文字语义检索 ───────────────────────────────────────────────────

    def _build_text_tab(self):
        panel = QFrame()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        hint = QLabel("通过自然语言描述画面内容，使用 Chinese-CLIP 向量相似度检索素材")
        hint.setObjectName("muted_text")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # 搜索行
        q_row = QHBoxLayout()
        self.txt_query = QLineEdit()
        self.txt_query.setPlaceholderText("描述画面内容，例如：罗技无线鼠标 白色 手持 特写")
        self.txt_query.returnPressed.connect(self._do_text_search)
        q_row.addWidget(self.txt_query, 1)
        self.txt_btn = QPushButton("搜索")
        self.txt_btn.setObjectName("primary_button")
        self.txt_btn.clicked.connect(self._do_text_search)
        q_row.addWidget(self.txt_btn)
        lay.addLayout(q_row)

        # 筛选行
        flt = QHBoxLayout()
        flt.addWidget(QLabel("路径前缀："))
        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("可选，限定搜索目录范围")
        flt.addWidget(self.txt_path, 1)
        flt.addWidget(QLabel("品牌："))
        self.txt_brand = QLineEdit()
        self.txt_brand.setPlaceholderText("留空=不限")
        self.txt_brand.setFixedWidth(80)
        flt.addWidget(self.txt_brand)
        flt.addWidget(QLabel("Hash："))
        self.txt_hash = QLineEdit()
        self.txt_hash.setPlaceholderText("Hash 过滤")
        self.txt_hash.setFixedWidth(100)
        flt.addWidget(self.txt_hash)
        flt.addWidget(QLabel("返回："))
        self.txt_topk = QSpinBox()
        self.txt_topk.setRange(1, 200)
        self.txt_topk.setValue(100)
        self.txt_topk.setFixedWidth(56)
        flt.addWidget(self.txt_topk)
        lay.addLayout(flt)

        self.txt_table, self.txt_stat = self._make_result_table()
        lay.addWidget(self.txt_table, 1)
        lay.addWidget(self.txt_stat)

        bot = QHBoxLayout()
        bot.addWidget(self.txt_stat, 1)
        btn_copy = QPushButton("📋 复制路径")
        btn_copy.setObjectName("secondary_button")
        btn_copy.clicked.connect(lambda: self._copy_path(self.txt_table))
        bot.addWidget(btn_copy)
        btn_open = QPushButton("🗂 打开目录")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(lambda: self._open_dir(self.txt_table))
        bot.addWidget(btn_open)
        lay.addLayout(bot)

        return panel

    # ── Tab 2：标签检索 ───────────────────────────────────────────────────────

    def _build_tag_tab(self):
        panel = QFrame()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        hint = QLabel("按品牌 / 型号 / 类别标签直接查询数据库，支持模糊匹配（留空不限）")
        hint.setObjectName("muted_text")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # 标签筛选行
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("品牌："))
        self.tag_brand = QComboBox()
        row1.addWidget(self.tag_brand, 1)
        row1.addWidget(QLabel("型号："))
        self.tag_model = QComboBox()
        row1.addWidget(self.tag_model, 1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("类别："))
        self.tag_category = QComboBox()
        row2.addWidget(self.tag_category, 1)
        row2.addWidget(QLabel("AI状态："))
        self.tag_status = QComboBox()
        self.tag_status.addItem("全部", "")
        self.tag_status.addItem("待分析", "pending")
        self.tag_status.addItem("已分析", "analyzed")
        self.tag_status.addItem("失败", "failed")
        row2.addWidget(self.tag_status, 1)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Hash："))
        self.tag_hash = QLineEdit()
        self.tag_hash.setPlaceholderText("Hash 过滤")
        row3.addWidget(self.tag_hash, 1)
        row3.addWidget(QLabel("限制："))
        self.tag_limit = QSpinBox()
        self.tag_limit.setRange(10, 2000)
        self.tag_limit.setValue(100)
        self.tag_limit.setFixedWidth(65)
        row3.addWidget(self.tag_limit)
        self.tag_btn = QPushButton("查询")
        self.tag_btn.setObjectName("primary_button")
        self.tag_btn.clicked.connect(self._do_tag_search)
        row3.addWidget(self.tag_btn)
        lay.addLayout(row3)

        self.tag_table, self.tag_stat = self._make_result_table()
        lay.addWidget(self.tag_table, 1)

        bot = QHBoxLayout()
        bot.addWidget(self.tag_stat, 1)
        btn_copy = QPushButton("📋 复制路径")
        btn_copy.setObjectName("secondary_button")
        btn_copy.clicked.connect(lambda: self._copy_path(self.tag_table))
        bot.addWidget(btn_copy)
        btn_open = QPushButton("🗂 打开目录")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(lambda: self._open_dir(self.tag_table))
        bot.addWidget(btn_open)
        lay.addLayout(bot)

        return panel

    # ── Tab 3：关键词检索 ───────────────────────────────────────────────────

    def _build_keyword_tab(self):
        panel = QFrame()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        hint = QLabel("在文件名、画面描述、品牌、型号、路径中模糊匹配关键词，不依赖向量模型。")
        hint.setObjectName("muted_text"); hint.setWordWrap(True)
        lay.addWidget(hint)

        q_row = QHBoxLayout()
        self.kw_input = QLineEdit()
        self.kw_input.setPlaceholderText("输入关键词，例如：罗技 G502 无线鼠标")
        self.kw_input.returnPressed.connect(self._do_kw_search)
        q_row.addWidget(self.kw_input, 1)
        self.kw_btn = QPushButton("搜索")
        self.kw_btn.setObjectName("primary_button")
        self.kw_btn.clicked.connect(self._do_kw_search)
        q_row.addWidget(self.kw_btn)
        lay.addLayout(q_row)

        # 过滤行
        flt = QHBoxLayout()
        flt.addWidget(QLabel("类型:")); self.kw_type = QComboBox()
        self.kw_type.addItems(["全部", "视频", "图片"]); self.kw_type.setFixedWidth(70)
        flt.addWidget(self.kw_type)
        flt.addWidget(QLabel("品牌:")); self.kw_brand = QLineEdit()
        self.kw_brand.setPlaceholderText("可选"); self.kw_brand.setFixedWidth(90)
        flt.addWidget(self.kw_brand)
        flt.addWidget(QLabel("型号:")); self.kw_model = QLineEdit()
        self.kw_model.setPlaceholderText("可选"); self.kw_model.setFixedWidth(90)
        flt.addWidget(self.kw_model)
        flt.addWidget(QLabel("类目:")); self.kw_category = QLineEdit()
        self.kw_category.setPlaceholderText("可选"); self.kw_category.setFixedWidth(80)
        flt.addWidget(self.kw_category)
        flt.addWidget(QLabel("AI:")); self.kw_aistat = QComboBox()
        self.kw_aistat.addItems(["全部","pending","analyzed","failed"]); self.kw_aistat.setFixedWidth(80)
        flt.addWidget(self.kw_aistat)
        flt.addStretch()
        lay.addLayout(flt)

        self.kw_table, self.kw_stat = self._make_result_table()
        lay.addWidget(self.kw_table, 1)
        lay.addWidget(self.kw_stat)

        bot = QHBoxLayout()
        btn_copy = QPushButton("📋 复制路径"); btn_copy.setObjectName("secondary_button")
        btn_copy.clicked.connect(lambda: self._copy_path(self.kw_table)); bot.addWidget(btn_copy)
        btn_open = QPushButton("🗂 打开目录"); btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(lambda: self._open_dir(self.kw_table)); bot.addWidget(btn_open)
        lay.addLayout(bot)
        return panel

    def _do_kw_search(self):
        kw = self.kw_input.text().strip()
        if not kw: return
        self.kw_btn.setEnabled(False)
        self.kw_table.setRowCount(0)
        self.kw_stat.setText("搜索中…")
        ft = "" if self.kw_type.currentIndex() == 0 else self.kw_type.currentText()
        ai = "" if self.kw_aistat.currentIndex() == 0 else self.kw_aistat.currentText()
        w = self.track_worker(_KeywordSearchWorker(
            kw, 200, file_type=ft,
            brand=self.kw_brand.text().strip(),
            model=self.kw_model.text().strip(),
            category=self.kw_category.text().strip(),
            ai_status=ai))
        w.finished.connect(lambda rows: self._on_kw_done(rows))
        w.error.connect(lambda m: self._on_search_err(m, self.kw_btn, self.kw_stat))
        w.start()

    def _on_kw_done(self, rows):
        self.kw_btn.setEnabled(True)
        self._fill_table(self.kw_table, rows, has_score=False)
        self.kw_stat.setText(f"共 {len(rows)} 条结果，双击文件名播放，双击其他单元格打开目录")

    # ── Tab 4：目录查询 ───────────────────────────────────────────────────────

    def _build_dir_tab(self):
        panel = QFrame()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        hint = QLabel("输入目录路径，从向量库数据库中列出该目录下所有已索引素材及其标签信息")
        hint.setObjectName("muted_text")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("目录路径："))
        self.dir_path = QLineEdit()
        self.dir_path.setPlaceholderText(r"例如 R:\鼠标\罗技  或  \\NAS\素材\产品")
        self.dir_path.returnPressed.connect(self._do_dir_query)
        dir_row.addWidget(self.dir_path, 1)
        btn_browse = QPushButton("选择…")
        btn_browse.setObjectName("secondary_button")
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)
        self.dir_btn = QPushButton("查询")
        self.dir_btn.setObjectName("primary_button")
        self.dir_btn.clicked.connect(self._do_dir_query)
        dir_row.addWidget(self.dir_btn)
        lay.addLayout(dir_row)

        dir_filter_row = QHBoxLayout()
        dir_filter_row.addWidget(QLabel("Hash 过滤："))
        self.dir_hash = QLineEdit()
        self.dir_hash.setPlaceholderText("输入 hash 前缀筛选")
        dir_filter_row.addWidget(self.dir_hash, 1)
        dir_filter_row.addWidget(QLabel("限制："))
        self.dir_limit = QSpinBox()
        self.dir_limit.setRange(10, 2000)
        self.dir_limit.setValue(100)
        self.dir_limit.setFixedWidth(65)
        dir_filter_row.addWidget(self.dir_limit)
        lay.addLayout(dir_filter_row)

        self.dir_table, self.dir_stat = self._make_result_table()
        lay.addWidget(self.dir_table, 1)

        bot = QHBoxLayout()
        bot.addWidget(self.dir_stat, 1)
        btn_copy = QPushButton("📋 复制路径")
        btn_copy.setObjectName("secondary_button")
        btn_copy.clicked.connect(lambda: self._copy_path(self.dir_table))
        bot.addWidget(btn_copy)
        btn_open = QPushButton("🗂 打开目录")
        btn_open.setObjectName("secondary_button")
        btn_open.clicked.connect(lambda: self._open_dir(self.dir_table))
        bot.addWidget(btn_open)
        lay.addLayout(bot)

        return panel

    # ── 通用：结果表格 ────────────────────────────────────────────────────────

    def _make_result_table(self):
        table = QTableWidget()
        table.setColumnCount(len(_TABLE_COLS))
        table.setHorizontalHeaderLabels(_TABLE_COLS)
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(10, QHeaderView.Stretch)   # 路径列拉伸
        for c in range(10):
            if c == 0:  # 文件名列
                hh.setSectionResizeMode(c, QHeaderView.Interactive)
                table.setColumnWidth(c, 400)
            elif c in (1, 2):  # 主要画面描述, 次要画面描述
                hh.setSectionResizeMode(c, QHeaderView.Interactive)
                table.setColumnWidth(c, 150)
            elif c == 9:  # Hash 列
                hh.setSectionResizeMode(c, QHeaderView.Interactive)
                table.setColumnWidth(c, 250)
            else:
                hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.doubleClicked.connect(lambda idx, t=table: self._open_dir_by_index(t, idx))
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self._show_table_context_menu(t, pos))

        stat = QLabel("共 0 条")
        stat.setObjectName("muted_text")
        stat.setWordWrap(False)
        stat.setMaximumHeight(24)
        return table, stat

    def _fill_table(self, table: QTableWidget, rows: list, has_score: bool = False):
        table.setUpdatesEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            fname  = row.get("filename") or os.path.basename(row.get("path", ""))
            desc_p = row.get("scene_desc_primary") or "—"
            desc_s = row.get("scene_desc_secondary") or "—"
            brand  = row.get("brand") or "—"
            model  = row.get("model") or "—"
            cat    = row.get("category") or row.get("product") or "—"
            conf   = row.get("ai_confidence")
            conf_t = f"{conf:.0%}" if conf is not None else "—"
            score  = row.get("score")
            score_t= f"{score:.3f}" if (has_score and score is not None) else "—"
            status = row.get("ai_status") or "pending"
            fhash  = row.get("file_hash") or "—"
            path   = row.get("path") or "—"

            vals = [fname, desc_p, desc_s, brand, model, cat, conf_t, score_t, status, fhash, path]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(str(v))
                cell.setData(Qt.UserRole, row)
                if c == 6 and conf is not None:  # 置信度着色
                    color = "#22c55e" if conf >= 0.7 else ("#f59e0b" if conf >= 0.4 else "#ef4444")
                    cell.setForeground(QColor(color))
                if c == 8:  # AI状态着色
                    cell.setForeground(QColor(_STATUS_COLOR.get(status, "#9ca3af")))
                table.setItem(r, c, cell)
        table.setUpdatesEnabled(True)

    # ── 搜索动作 ─────────────────────────────────────────────────────────────

    def _do_text_search(self):
        query = self.txt_query.text().strip()
        if not query:
            return
        self.txt_btn.setEnabled(False)
        self.txt_table.setRowCount(0)
        self.txt_stat.setText("检索中…")
        w = self.track_worker(_VectorSearchWorker(
            query, self.txt_topk.value(),
            self.txt_path.text().strip(),
            self.txt_brand.text().strip(), "",
            hash_prefix=self.txt_hash.text().strip(),
        ))
        w.finished.connect(lambda rows: self._on_text_done(rows))
        w.error.connect(lambda m: self._on_search_err(m, self.txt_btn, self.txt_stat))
        w.start()

    def _on_text_done(self, rows: list):
        self.txt_btn.setEnabled(True)
        self._fill_table(self.txt_table, rows, has_score=True)
        self.txt_stat.setText(f"共 {len(rows)} 条结果，双击文件名播放，双击其他单元格打开目录")

    def _do_tag_search(self):
        self.tag_btn.setEnabled(False)
        self.tag_table.setRowCount(0)
        self.tag_stat.setText("查询中…")

        brand = self.tag_brand.currentText()
        if brand == "全部":
            brand = ""
        model = self.tag_model.currentText()
        if model == "全部":
            model = ""
        category = self.tag_category.currentText()
        if category == "全部":
            category = ""

        w = self.track_worker(_TagSearchWorker(
            brand,
            model,
            category,
            self.tag_status.currentData(),
            self.tag_limit.value(),
            hash_prefix=self.tag_hash.text().strip(),
        ))
        w.finished.connect(lambda rows: self._on_tag_done(rows))
        w.error.connect(lambda m: self._on_search_err(m, self.tag_btn, self.tag_stat))
        w.start()

    def _on_tag_done(self, rows: list):
        self.tag_btn.setEnabled(True)
        self._fill_table(self.tag_table, rows, has_score=False)
        self.tag_stat.setText(f"共 {len(rows)} 条结果，双击文件名播放，双击其他单元格打开目录")

    def _do_dir_query(self):
        path = self.dir_path.text().strip()
        if not path:
            self.show_warning("请输入要查询的目录路径。", "未填目录")
            return
        self.dir_btn.setEnabled(False)
        self.dir_table.setRowCount(0)
        self.dir_stat.setText("查询中…")
        w = self.track_worker(_DirQueryWorker(
            path,
            limit=self.dir_limit.value(),
            hash_prefix=self.dir_hash.text().strip(),
        ))
        w.finished.connect(lambda rows: self._on_dir_done(rows))
        w.error.connect(lambda m: self._on_search_err(m, self.dir_btn, self.dir_stat))
        w.start()

    def _on_dir_done(self, rows: list):
        self.dir_btn.setEnabled(True)
        self._fill_table(self.dir_table, rows, has_score=False)
        self.dir_stat.setText(f"共 {len(rows)} 条记录，双击文件名播放，双击其他单元格打开目录")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择要查询的目录")
        if d:
            self.dir_path.setText(d)

    def _on_search_err(self, msg: str, btn: QPushButton, stat: QLabel):
        btn.setEnabled(True)
        first = msg.split("\n")[0].strip()
        stat.setText(f"❌ {first}")
        if "Chinese-CLIP" in msg or "无法加载" in msg:
            self.show_error(
                "CLIP 模型未加载，无法进行向量检索。\n\n"
                "请前往「环境配置」→「向量库 / CLIP 模型」\n"
                "点击「⬇ 一键下载模型」后重新搜索。",
                "模型未就绪",
            )
        elif len(msg) > 120:
            self.show_error(msg, "查询失败")

    # ── 通用行操作 ────────────────────────────────────────────────────────────

    def _get_row_data(self, table: QTableWidget, row: int = None) -> dict:
        r = row if row is not None else table.currentRow()
        if r < 0:
            return {}
        item = table.item(r, 0)
        return item.data(Qt.UserRole) if item else {}

    def _get_nas_root(self) -> str:
        import json as _json
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "material_index_config.json"
        )
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
                return cfg.get("nas_root", "")
            except Exception:
                pass
        return ""

    def _play_file_by_path(self, path: str):
        if not path or path == "—" or not os.path.isfile(path):
            self.show_warning(f"文件不存在或无法播放：\n{path}", "文件不存在")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self.show_error(f"播放文件失败：\n{e}")

    def _open_dir_by_path(self, path: str):
        if not path or path == "—":
            return
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            import subprocess
            subprocess.Popen(f'explorer "{folder}"')
        else:
            self.show_warning(f"目录不可访问：\n{folder}", "无法打开")

    def _open_dir_by_index(self, table: QTableWidget, index):
        data = self._get_row_data(table, index.row())
        path = data.get("path", "")
        if not path or path == "—":
            return
        nas_root = self._get_nas_root()
        if nas_root:
            full_path = os.path.normpath(os.path.join(nas_root, path.lstrip("/\\")))
        else:
            full_path = path

        # 双击文件名(列0)时播放，双击其他列时打开所在目录
        if index.column() == 0:
            self._play_file_by_path(full_path)
        else:
            self._open_dir_by_path(full_path)

    def _open_dir(self, table: QTableWidget):
        r = table.currentRow()
        if r < 0:
            return
        data = self._get_row_data(table, r)
        path = data.get("path", "")
        if not path or path == "—":
            return
        nas_root = self._get_nas_root()
        if nas_root:
            full_path = os.path.normpath(os.path.join(nas_root, path.lstrip("/\\")))
        else:
            full_path = path
        self._open_dir_by_path(full_path)

    def _copy_path(self, table: QTableWidget):
        data = self._get_row_data(table)
        if data:
            path = data.get("path", "")
            nas_root = self._get_nas_root()
            if nas_root and path:
                full_path = os.path.normpath(os.path.join(nas_root, path.lstrip("/\\")))
            else:
                full_path = path
            QGuiApplication.clipboard().setText(full_path)

    def _load_tag_options(self):
        from utils.material_clip_indexer import MaterialClipIndexer
        curr_brand = self.tag_brand.currentText()
        curr_model = self.tag_model.currentText()
        curr_cat = self.tag_category.currentText()

        brands = ["全部"]
        models = ["全部"]
        categories = ["全部"]
        try:
            with MaterialClipIndexer() as idx:
                idx._connect()
                with idx._conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT brand FROM materials WHERE brand IS NOT NULL AND brand != '' ORDER BY brand")
                    brands.extend([r[0] for r in cur.fetchall()])
                    cur.execute("SELECT DISTINCT model FROM materials WHERE model IS NOT NULL AND model != '' ORDER BY model")
                    models.extend([r[0] for r in cur.fetchall()])
                    cur.execute("SELECT DISTINCT category FROM materials WHERE category IS NOT NULL AND category != '' ORDER BY category")
                    categories.extend([r[0] for r in cur.fetchall()])
        except Exception as e:
            print(f"加载标签选项失败: {e}")

        self.tag_brand.blockSignals(True)
        self.tag_model.blockSignals(True)
        self.tag_category.blockSignals(True)

        self.tag_brand.clear()
        self.tag_brand.addItems(brands)
        idx_b = self.tag_brand.findText(curr_brand)
        if idx_b >= 0:
            self.tag_brand.setCurrentIndex(idx_b)

        self.tag_model.clear()
        self.tag_model.addItems(models)
        idx_m = self.tag_model.findText(curr_model)
        if idx_m >= 0:
            self.tag_model.setCurrentIndex(idx_m)

        self.tag_category.clear()
        self.tag_category.addItems(categories)
        idx_c = self.tag_category.findText(curr_cat)
        if idx_c >= 0:
            self.tag_category.setCurrentIndex(idx_c)

        self.tag_brand.blockSignals(False)
        self.tag_model.blockSignals(False)
        self.tag_category.blockSignals(False)

    def _show_table_context_menu(self, table: QTableWidget, pos):
        item = table.itemAt(pos)
        if not item:
            return
        row_idx = item.row()
        data = self._get_row_data(table, row_idx)
        if not data:
            return

        path = data.get("path", "")
        nas_root = self._get_nas_root()
        if nas_root and path:
            full_path = os.path.normpath(os.path.join(nas_root, path.lstrip("/\\")))
        else:
            full_path = path

        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QGuiApplication

        menu = QMenu(self.parent_widget)

        act_play = QAction("▶ 播放文件", menu)
        act_play.triggered.connect(lambda: self._play_file_by_path(full_path))
        menu.addAction(act_play)

        act_open_dir = QAction("🗂 打开文件所在目录", menu)
        act_open_dir.triggered.connect(lambda: self._open_dir_by_path(full_path))
        menu.addAction(act_open_dir)

        menu.addSeparator()

        txt = item.text().strip()
        if txt:
            act_copy_val = QAction(f"📋 复制当前单元格: '{txt}'", menu)
            act_copy_val.triggered.connect(lambda: QGuiApplication.clipboard().setText(txt))
            menu.addAction(act_copy_val)

        fname = data.get("filename") or os.path.basename(path)
        if fname:
            act_copy_name = QAction("📋 复制文件名", menu)
            act_copy_name.triggered.connect(lambda: QGuiApplication.clipboard().setText(fname))
            menu.addAction(act_copy_name)

        if full_path:
            act_copy_path = QAction("📋 复制完整绝对路径", menu)
            act_copy_path.triggered.connect(lambda: QGuiApplication.clipboard().setText(full_path))
            menu.addAction(act_copy_path)

        fhash = data.get("file_hash", "")
        if fhash and fhash != "—":
            act_copy_hash = QAction("📋 复制 Hash 值", menu)
            act_copy_hash.triggered.connect(lambda: QGuiApplication.clipboard().setText(fhash))
            menu.addAction(act_copy_hash)

        menu.exec_(table.viewport().mapToGlobal(pos))
