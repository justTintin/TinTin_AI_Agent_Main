"""素材检索：插件下载对话框。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .workers import _ImportPluginWorker, _PluginListWorker


class PluginDownloadDialog(QDialog):
    """插件下载对话框：浏览插件素材列表 + 批量下载入库。

    通过 /material/list?source=plugin 获取插件来源素材列表，
    支持选择多个条目后调用 /material/import_plugin 批量入库。
    """

    def __init__(self, parent=None, search_page=None):
        super().__init__(parent)
        self.setWindowTitle("插件素材下载")
        self.resize(720, 560)
        self._search_page = search_page
        self._items = []
        self._selected: set[int] = set()
        self._loader = None
        self._importer = None
        self._build()
        self._load_list()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        tip = QLabel("浏览插件来源素材 → 选择需要的条目 → 批量下载入库")
        tip.setStyleSheet("color:#8b93a3; font-size:12px;")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # 过滤器
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("按名称/分类过滤…")
        self.edit_filter.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.edit_filter, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self._load_list)
        filter_row.addWidget(self.btn_refresh)
        lay.addLayout(filter_row)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.list_widget, 1)

        # 状态
        self.lbl_status = QLabel("加载中…")
        self.lbl_status.setStyleSheet("color:#8b93a3; font-size:12px;")
        lay.addWidget(self.lbl_status)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.setObjectName("secondary_button")
        self.btn_select_all.clicked.connect(self._select_all)
        btn_row.addWidget(self.btn_select_all)
        self.btn_select_none = QPushButton("取消全选")
        self.btn_select_none.setObjectName("secondary_button")
        self.btn_select_none.clicked.connect(self._select_none)
        btn_row.addWidget(self.btn_select_none)
        btn_row.addStretch()

        self.lbl_selected = QLabel("已选 0 项")
        self.lbl_selected.setStyleSheet("color:#8b93a3;")
        btn_row.addWidget(self.lbl_selected)

        self.btn_import = QPushButton("下载入库")
        self.btn_import.setObjectName("primary_button")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._start_import)
        btn_row.addWidget(self.btn_import)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_close)

        lay.addLayout(btn_row)

    def _load_list(self):
        self.lbl_status.setText("加载插件素材列表…")
        self.list_widget.clear()
        self._items = []
        self._selected.clear()
        self._loader = _PluginListWorker()
        self._loader.finished.connect(self._on_list_loaded)
        self._loader.start()

    def _on_list_loaded(self, items):
        self._items = items or []
        self._rebuild_list()
        self.lbl_status.setText(f"共 {len(self._items)} 个插件素材")

    def _rebuild_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        text_filter = self.edit_filter.text().strip().lower()
        shown = 0
        for idx, item in enumerate(self._items):
            name = item.get("name") or item.get("filename") or item.get("title") or f"插件-{idx}"
            category = item.get("category") or item.get("type") or ""
            url = item.get("url") or item.get("download_url") or ""
            if text_filter and text_filter not in str(name).lower() and text_filter not in str(category).lower():
                continue
            labels = []
            if category:
                labels.append(f"[{category}]")
            if url:
                labels.append("🔗")
            display = f"{' '.join(labels)} {name}" if labels else name
            lw = QListWidgetItem(display)
            lw.setData(Qt.UserRole, idx)
            tip = f"名称: {name}\n分类: {category or '—'}\nURL: {url or '—'}"
            lw.setToolTip(tip)
            self.list_widget.addItem(lw)
            shown += 1
        self.lbl_status.setText(f"显示 {shown} / {len(self._items)} 个插件素材")
        self.list_widget.blockSignals(False)

    def _apply_filter(self, _text):
        self._rebuild_list()

    def _on_selection_changed(self):
        self._selected.clear()
        for item in self.list_widget.selectedItems():
            idx = item.data(Qt.UserRole)
            if idx is not None:
                self._selected.add(int(idx))
        self.lbl_selected.setText(f"已选 {len(self._selected)} 项")
        self.btn_import.setEnabled(len(self._selected) > 0 and self._importer is None)

    def _select_all(self):
        self.list_widget.selectAll()

    def _select_none(self):
        self.list_widget.clearSelection()

    def _start_import(self):
        if not self._selected:
            return
        items = [self._items[i] for i in sorted(self._selected) if 0 <= i < len(self._items)]
        if not items:
            return
        self.btn_import.setEnabled(False)
        self.lbl_status.setText(f"开始下载 {len(items)} 个插件素材…")
        self._importer = _ImportPluginWorker(items)
        self._importer.finished.connect(self._on_import_done)
        self._importer.start()

    def _on_import_done(self, result):
        self._importer = None
        total = result.get("total", 0)
        success = result.get("success", 0)
        self.lbl_status.setText(f"下载完成：成功 {success}/{total}")
        # 刷新列表
        self._load_list()
        if success > 0 and self._search_page:
            self.accept()
