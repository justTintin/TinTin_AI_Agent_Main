"""公共可复用控件。

DropZone：可拖入文件或点击触发的放置区（无业务逻辑，行为由信号连接方决定）。
  - file_dropped(list)：拖入的文件路径列表（已按 exts 过滤）
  - clicked()：鼠标左键点击
用法：
    dz = DropZone((".mp4", ".mov"), min_height=100, hint="拖入视频 或 点击选择")
    dz.file_dropped.connect(lambda paths: handle(paths))
    dz.clicked.connect(open_picker)
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class DropZone(QFrame):
    """可拖入文件或点击触发的放置区。

    拖入时按 exts 过滤出本地文件路径并发出 file_dropped(list)；
    鼠标左键点击发出 clicked()。组件自身不处理业务，
    由使用方连接信号决定后续行为（如添加素材、上传、预览）。
    """
    file_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, exts, hint="拖入文件 或 点击选择", min_height=100, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("drop_zone")
        self.setMinimumHeight(min_height)
        self._exts = tuple(("." + e.lstrip(".")).lower() for e in exts)
        self.setStyleSheet("""
            #drop_zone {
                background: #1c1c24; border: 2px dashed #3a3a48;
                border-radius: 10px;
            }
            #drop_zone:hover { border-color: #2ecc71; background: #1f1f2a; }
        """)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        hint_lbl = QLabel(hint)
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setStyleSheet("color: #6b7280; font-size: 14px;")
        lay.addWidget(hint_lbl)

    # ── 交互 ──
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(self._accepts(u.toLocalFile()) for u in urls):
                event.acceptProposedAction()
                self._set_active(True)

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_active(False)

    def dropEvent(self, event):  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        accepted = [p for p in paths if self._accepts(p)]
        if accepted:
            self.file_dropped.emit(accepted)
        event.acceptProposedAction()
        self._set_active(False)

    # ── 内部 ──
    def _accepts(self, path):
        return bool(path) and path.lower().endswith(self._exts)

    def _set_active(self, active):
        if active:
            self.setStyleSheet(
                "#drop_zone { background: #1f2a24; border: 2px dashed #2ecc71;"
                " border-radius: 10px; }")
        else:
            self.setStyleSheet(
                "#drop_zone { background: #1c1c24; border: 2px dashed #3a3a48;"
                " border-radius: 10px; }"
                "#drop_zone:hover { border-color: #2ecc71; background: #1f1f2a; }")
