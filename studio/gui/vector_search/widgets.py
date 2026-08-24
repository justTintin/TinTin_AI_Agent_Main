"""素材检索：自定义控件（网格布局过滤器、视频预览、提示词面板）。"""
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from gui.video_player import VideoPlayerWidget

# ── 常量 ──
_THUMB_ICON_SIZE = QSize(160, 160)
_MAX_THUMB_WORKERS = 6


def _make_placeholder_pixmap(text="?", color="#3a3a3c"):
    """生成纯色占位缩略图（带文字，用于图片加载前/视频占位）。"""
    pm = QPixmap(_THUMB_ICON_SIZE)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.setPen(QColor("#888"))
    f = p.font()
    f.setPointSize(20)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return pm


class _GridRowsFilter(QObject):
    """让素材网格每行固定显示 cols 个素材：随视口宽度动态调整列宽，行高保持合理。"""

    def __init__(self, grid, cols=10):
        super().__init__(grid)
        self.grid = grid
        self.cols = max(3, cols)
        self._timer = None  # 防抖定时器

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Resize, QEvent.Show):
            # 延迟调用，确保窗口大小稳定后再计算
            self._schedule_apply()
        return False

    def _schedule_apply(self):
        """防抖：只在最后一次 resize 后 50ms 才真正调用 apply()。"""
        if self._timer is not None:
            self._timer.stop()
        self._timer = QTimer(self.grid)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self._timer.start(50)

    def apply(self):
        vp = self.grid.viewport()
        if vp is None:
            return
        w = vp.width()
        if w <= 0:
            return
        # 先关闭 uniformItemSizes，强制 Qt 丢弃缓存的 item 大小
        self.grid.setUniformItemSizes(False)
        # account for inter-cell spacing so exactly `cols` columns fit
        spacing = self.grid.spacing()
        total_gap = spacing * (self.cols - 1)
        col_w = max(90, (w - total_gap) // self.cols)
        icon = max(80, col_w - 2)
        row_h = icon + 24   # 图标 + 文件名行高
        new_size = QSize(col_w, row_h)
        self.grid.setGridSize(new_size)
        self.grid.setIconSize(QSize(icon, icon))
        # 恢复 uniformItemSizes 以优化性能
        self.grid.setUniformItemSizes(True)
        # 如果有数据，强制重排
        if self.grid.count() > 0:
            self.grid.doItemsLayout()


class VideoPreviewDialog(QDialog):
    """内置视频播放器：通过 /material/serve 流式播放服务端素材（支持 Range），右侧反推提示词面板。"""

    def __init__(self, url, title="", material_id="", media_type="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"播放 视频预览 - {title}")
        self.resize(1120, 620)
        self.setObjectName("videoPreviewDialog")

        root_lay = QHBoxLayout(self)
        root_lay.setContentsMargins(10, 10, 10, 10)
        root_lay.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(8)

        # 统一视频播放器：等比显示 + 播放/暂停/停止 + 进度条 + 时间
        self.player_widget = VideoPlayerWidget(self, autoplay=True)
        left.addWidget(self.player_widget, 1)

        root_lay.addLayout(left, 1)
        self.prompt_panel = PromptReversePanel(material_id, media_type)
        root_lay.addWidget(self.prompt_panel, 0)

        self.player_widget.set_source(url)

    def closeEvent(self, event):  # noqa: N802
        self.player_widget.stop()
        super().closeEvent(event)


class PromptReversePanel(QFrame):
    """预览对话框右侧：反推按钮在上，正/负向提示词分开显示与复制。"""

    def __init__(self, material_id, media_type, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(360)
        self._mid = material_id
        self._mtype = (media_type or "image").lower()
        self._worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        title = QLabel("反推提示词")
        title.setObjectName("section_header")
        lay.addWidget(title)

        # 反推按钮放在提示词文本框上方
        self.btn_reverse = QPushButton("反推提示词")
        self.btn_reverse.setObjectName("primary_button")
        self.btn_reverse.clicked.connect(self._reverse_prompt)
        lay.addWidget(self.btn_reverse)

        # 正向提示词
        row_pos = QHBoxLayout()
        lbl_pos = QLabel("正向提示词")
        lbl_pos.setObjectName("muted_text")
        row_pos.addWidget(lbl_pos)
        row_pos.addStretch(1)
        self.btn_copy_pos = QPushButton("复制正向")
        self.btn_copy_pos.setObjectName("secondary_button")
        self.btn_copy_pos.clicked.connect(self._copy_positive)
        row_pos.addWidget(self.btn_copy_pos)
        lay.addLayout(row_pos)

        self.txt_prompt = QTextEdit()
        self.txt_prompt.setPlaceholderText("点击「反推提示词」生成正向提示词…")
        self.txt_prompt.setAcceptRichText(False)
        self.txt_prompt.setMinimumHeight(110)
        lay.addWidget(self.txt_prompt, 2)

        # 负向提示词
        row_neg = QHBoxLayout()
        lbl_neg = QLabel("负向提示词")
        lbl_neg.setObjectName("muted_text")
        row_neg.addWidget(lbl_neg)
        row_neg.addStretch(1)
        self.btn_copy_neg = QPushButton("复制负向")
        self.btn_copy_neg.setObjectName("secondary_button")
        self.btn_copy_neg.clicked.connect(self._copy_negative)
        row_neg.addWidget(self.btn_copy_neg)
        lay.addLayout(row_neg)

        self.txt_negative = QTextEdit()
        self.txt_negative.setPlaceholderText("负向提示词（可为空）…")
        self.txt_negative.setAcceptRichText(False)
        self.txt_negative.setMinimumHeight(80)
        lay.addWidget(self.txt_negative, 1)

    def _reverse_prompt(self):
        if not self._mid:
            self.txt_prompt.setPlainText("缺少素材ID")
            return
        self.btn_reverse.setEnabled(False)
        self.txt_prompt.setPlainText("正在反推提示词…")
        self.txt_negative.clear()
        from .workers import _PromptWorker
        self._worker = _PromptWorker(self._mid, self._mtype)
        self._worker.finished.connect(self._on_prompt_done)
        self._worker.start()

    def _on_prompt_done(self, prompt, neg, err):
        self.btn_reverse.setEnabled(True)
        if err:
            self.txt_prompt.setPlainText(f"反推失败：{err}")
            self.txt_negative.clear()
            return
        self.txt_prompt.setPlainText(prompt)
        self.txt_negative.setPlainText(neg)

    def _copy_positive(self):
        QGuiApplication.clipboard().setText(self.txt_prompt.toPlainText())

    def _copy_negative(self):
        QGuiApplication.clipboard().setText(self.txt_negative.toPlainText())
