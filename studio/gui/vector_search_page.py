# -*- coding: utf-8 -*-
"""
素材检索页面（page 40）

通过服务端 /material/search API 检索素材。
"""
import os
import requests
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QComboBox, QCompleter,
)
from PySide6.QtCore import Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QGuiApplication, QDesktopServices

from gui.base_page import BasePage
from utils.base_worker import BaseWorker


def _get_server_url():
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return "http://192.168.111.18:8000"


class _SearchWorker(BaseWorker):
    """服务端素材检索。"""
    finished = Signal(list, int)

    def __init__(self, query="", brand="", category="", model="", media_type="", limit=50, offset=0):
        super().__init__()
        self.query = query
        self.brand = brand
        self.category = category
        self.model = model
        self.media_type = media_type
        self.limit = limit
        self.offset = offset

    def do_work(self):
        try:
            url = f"{_get_server_url()}/material/search"
            params = {"limit": self.limit, "offset": self.offset}
            if self.query:
                params["query"] = self.query
            if self.brand:
                params["brand"] = self.brand
            if self.category:
                params["category"] = self.category
            if self.model:
                params["model"] = self.model
            if self.media_type:
                params["media_type"] = self.media_type
            resp = requests.post(url, json=params, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            results = data.get("results") or data.get("data") or []
            total = data.get("total") or len(results)
            self.finished.emit(results, total)
        except Exception as e:
            self.error.emit(str(e))


class _BrandLoader(BaseWorker):
    """异步获取品牌去重列表。"""
    finished = Signal(list)

    def do_work(self):
        try:
            url = f"{_get_server_url()}/material/distinct?field=brand"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.finished.emit(data.get("values", []))
                return
        except Exception:
            pass
        self.finished.emit([])


class VectorSearchPage(BasePage):
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("🔍 素材检索")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hdr.addStretch()
        sub = QLabel(f"服务端: {_get_server_url()}")
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        root.addLayout(hdr)

        # 搜索行
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索素材（品牌/型号/文件名等）")
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("primary_button")
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # 筛选行
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("品牌:"))
        self.filter_brand = QComboBox()
        self.filter_brand.setEditable(True)
        self.filter_brand.setPlaceholderText("如 罗技")
        self.filter_brand.setMaximumWidth(160)
        self.filter_brand.setInsertPolicy(QComboBox.NoInsert)
        filter_row.addWidget(self.filter_brand)
        QTimer.singleShot(100, self._load_brands)
        filter_row.addWidget(QLabel("分类:"))
        self.filter_category = QComboBox()
        self.filter_category.addItems(["全部", "鼠标", "鼠标垫", "键盘", "耳机", "摄像头"])
        self.filter_category.setMaximumWidth(100)
        filter_row.addWidget(self.filter_category)
        filter_row.addWidget(QLabel("类型:"))
        self.filter_type = QComboBox()
        self.filter_type.addItems(["全部", "video", "image"])
        self.filter_type.setMaximumWidth(80)
        filter_row.addWidget(self.filter_type)
        filter_row.addWidget(QLabel("每页:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(10, 200)
        self.spin_limit.setValue(50)
        self.spin_limit.setFixedWidth(60)
        filter_row.addWidget(self.spin_limit)
        filter_row.addStretch()
        root.addLayout(filter_row)

        # 结果表格
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(7)
        self.result_table.setHorizontalHeaderLabels(["文件名", "品牌", "型号", "分类", "类型", "大小", "路径"])
        hh = self.result_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        self.result_table.setColumnWidth(0, 200)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.doubleClicked.connect(self._open_file_location)
        root.addWidget(self.result_table, 1)

        # 状态栏
        stat_row = QHBoxLayout()
        self.lbl_stat = QLabel("就绪")
        self.lbl_stat.setObjectName("muted_text")
        stat_row.addWidget(self.lbl_stat, 1)
        self.btn_copy_path = QPushButton("📋 复制路径")
        self.btn_copy_path.setObjectName("secondary_button")
        self.btn_copy_path.clicked.connect(self._copy_selected_path)
        stat_row.addWidget(self.btn_copy_path)
        root.addLayout(stat_row)

        self._results = []
        self._total = 0

    def _load_brands(self):
        w = self.track_worker(_BrandLoader())
        w.finished.connect(self._on_brands_loaded)
        w.start()

    def _on_brands_loaded(self, brands):
        if not brands:
            return
        self.filter_brand.clear()
        self.filter_brand.addItems(brands)
        c = self.filter_brand.completer()
        if c:
            c.setFilterMode(Qt.MatchContains)
            c.setCaseSensitivity(Qt.CaseInsensitive)

    def _do_search(self):
        query = self.search_input.text().strip()
        brand = self.filter_brand.currentText().strip()
        category = self.filter_category.currentText()
        if category == "全部":
            category = ""
        media_type = self.filter_type.currentText()
        if media_type == "全部":
            media_type = ""

        self.btn_search.setEnabled(False)
        self.lbl_stat.setText("搜索中...")
        self.result_table.setRowCount(0)

        w = self.track_worker(_SearchWorker(
            query=query, brand=brand, category=category,
            media_type=media_type, limit=self.spin_limit.value()))
        w.finished.connect(self._on_search_done)
        w.error.connect(lambda m: self._on_search_error(m))
        w.start()

    def _on_search_done(self, results, total):
        self.btn_search.setEnabled(True)
        self._results = results
        self._total = total
        self._fill_table(results)
        self.lbl_stat.setText(f"共 {total} 条结果")

    def _on_search_error(self, msg):
        self.btn_search.setEnabled(True)
        self.lbl_stat.setText(f"❌ {msg}")
        self.result_table.setRowCount(0)

    def _fill_table(self, rows):
        self.result_table.setUpdatesEnabled(False)
        self.result_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            fname = item.get("filename", "")
            brand = item.get("brand") or "—"
            model = item.get("model") or "—"
            category = item.get("product") or item.get("category") or "—"
            mtype = item.get("media_type", "")
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else ""
            path = item.get("path", item.get("filepath", ""))
            self.result_table.setItem(r, 0, QTableWidgetItem(fname))
            self.result_table.setItem(r, 1, QTableWidgetItem(brand))
            self.result_table.setItem(r, 2, QTableWidgetItem(model))
            self.result_table.setItem(r, 3, QTableWidgetItem(category))
            self.result_table.setItem(r, 4, QTableWidgetItem(mtype))
            self.result_table.setItem(r, 5, QTableWidgetItem(size_str))
            self.result_table.setItem(r, 6, QTableWidgetItem(path))
        self.result_table.setUpdatesEnabled(True)

    def _copy_selected_path(self):
        idx = self.result_table.currentRow()
        if idx < 0 or idx >= len(self._results):
            return
        path = self._results[idx].get("path", self._results[idx].get("filepath", ""))
        if path:
            QGuiApplication.clipboard().setText(path)

    def _open_file_location(self, idx):
        row = idx.row()
        if row < 0 or row >= len(self._results):
            return
        path = self._results[row].get("path", self._results[row].get("filepath", ""))
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
