"""媒体工具：把「图片处理」与「视频处理」两组子功能聚合为「分组卡片菜单」界面。

设计参考：剪贴板卡片式界面——深色卡片（图标 + 标题 + 说明），按「图片 / 视频」分组。
交互：点击卡片进入对应工具页（右上角「← 返回媒体工具」回卡片菜单）；工具页懒加载。

卡片分组：
  图片：封面制作 / 图像抠图 / 图片框选OCR
  视频：视频修复 / 视频转文字 / 声音克隆 / 视频去字幕 / 视频框选OCR / 批量LUT调色
  提示词：图片反推提示词 / 视频反推提示词
"""
import logging
from functools import partial

from gui.base_page import BasePage
from gui.elided_label import ElidedLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from utils.gui_icons import mdi_icon

log = logging.getLogger(__name__)


class _ToolCard(QFrame):
    """媒体工具卡片：图标 + 标题 + 说明，内容居中，左键点击触发 clicked。"""
    clicked = Signal()

    def __init__(self, icon_name, title, desc, parent=None):
        super().__init__(parent)
        self.setObjectName("tool_card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(148)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("""
            #tool_card {
                background: #1c1c24;
                border: 1px solid #2b2b35;
                border-radius: 12px;
            }
            #tool_card:hover {
                border: 1px solid #2ecc71;
                background: #23232e;
            }
            #tool_card_title { font-size: 15px; font-weight: bold; color: #e5e7eb; }
            #tool_card_desc { font-size: 12px; color: #9ca3af; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 18, 16, 18)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignCenter)

        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setPixmap(mdi_icon(icon_name, "#2ecc71").pixmap(44, 44))
        lay.addWidget(self.icon_lbl, 0, Qt.AlignCenter)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("tool_card_title")
        title_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(title_lbl, 0, Qt.AlignCenter)

        desc_lbl = ElidedLabel(desc, max_lines=2)
        desc_lbl.setObjectName("tool_card_desc")
        desc_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(desc_lbl, 0, Qt.AlignCenter)
        lay.addStretch()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MediaToolsPage(BasePage):
    """媒体工具容器：卡片菜单 + 各子工具页（懒加载）。"""

    # (标题, key, 图标名, 说明)
    _IMAGE_TOOLS = [
        ("封面制作", "cover_maker", "image-edit", "商品封面图快速制作"),
        ("图像抠图", "image_matting", "image", "智能抠图 / 去除背景"),
        ("图片框选OCR", "image_folder_ocr", "text-box-search", "批量识别图片文字"),
    ]
    _VIDEO_TOOLS = [
        ("视频修复", "video_tools", "wrench", "画质修复 / 工作流处理"),
        ("视频转文字", "transcription", "subtitles", "视频语音自动转写"),
        ("声音克隆", "voice_clone", "audio", "克隆音色生成配音"),
        ("视频去水印字幕", "subtitle_removal", "closed-caption", "去除字幕 / 台标水印"),
        ("视频框选OCR", "video_ocr", "text-box-search", "视频帧文字识别"),
    ]
    _PROMPT_TOOLS = [
        ("图片反推提示词", "image_prompt", "image", "上传图片，AI 生成绘画提示词"),
        ("视频反推提示词", "video_prompt", "video", "上传视频，框选片段生成提示词"),
    ]

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._built = set()
        self._stack: QStackedWidget | None = None
        # 持有工具页实例引用，防止临时实例被 GC 回收导致信号连接失效
        # （如按钮 clicked → 文件对话框无法弹出）
        self._tool_pages = {}

    def _all_tools(self):
        return self._IMAGE_TOOLS + self._VIDEO_TOOLS + self._PROMPT_TOOLS

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        heading_row = QHBoxLayout()
        heading_lbl = QLabel("媒体工具")
        heading_lbl.setObjectName("heading")
        heading_row.addStretch()
        heading_row.addWidget(heading_lbl)
        heading_row.addStretch()
        root.addLayout(heading_row)

        self._stack = QStackedWidget()

        # ---- 页 0：卡片菜单 ----
        menu_page = QWidget()
        menu_lay = QVBoxLayout(menu_page)
        menu_lay.setContentsMargins(0, 0, 0, 0)
        menu_lay.setSpacing(18)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 10, 0)
        content_lay.setSpacing(16)
        scroll.setWidget(content)
        menu_lay.addWidget(scroll)
        self._stack.addWidget(menu_page)

        content_lay.addWidget(self._group_header("图形"))
        content_lay.addLayout(self._build_card_grid(self._IMAGE_TOOLS, 0))
        content_lay.addSpacing(10)
        content_lay.addWidget(self._group_header("视频"))
        content_lay.addLayout(self._build_card_grid(self._VIDEO_TOOLS, len(self._IMAGE_TOOLS)))  # noqa: E501
        content_lay.addSpacing(10)
        content_lay.addWidget(self._group_header("提示词"))
        content_lay.addLayout(self._build_card_grid(
            self._PROMPT_TOOLS, len(self._IMAGE_TOOLS) + len(self._VIDEO_TOOLS)))
        content_lay.addStretch()

        # ---- 页 1..n：各工具页（懒构建） ----
        for _ in self._all_tools():
            self._stack.addWidget(QWidget())

        root.addWidget(self._stack, 1)
        self._stack.currentChanged.connect(self._ensure_tool)

    def _group_header(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("group_header")
        lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #f0f1f7;"
            "padding: 4px 2px; border-left: 3px solid #2ecc71; padding-left: 10px;"
        )
        return lbl

    def _build_card_grid(self, tools, start_index):
        grid = QGridLayout()
        grid.setSpacing(14)
        cols = 3
        stack = self._stack
        for i, (title, _key, icon_name, desc) in enumerate(tools):
            card = _ToolCard(icon_name, title, desc)
            tool_index = 1 + start_index + i
            if stack is not None:
                card.clicked.connect(lambda idx=tool_index, s=stack: s.setCurrentIndex(idx))  # noqa: E501
            grid.addWidget(card, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(grid.rowCount(), 1)
        return grid

    def _ensure_tool(self, index):
        if index <= 0 or index > len(self._all_tools()) or index in self._built:
            return
        key = self._all_tools()[index - 1][1]
        stack = self._stack
        if stack is None:
            return
        try:
            page = stack.widget(index)
            if page is None:
                return
            self._build_tool(key, page)
            self._built.add(index)
        except Exception as e:  # Qt 工具页构建可能抛出多类异常
            log.error("[媒体工具] 工具页构建失败(%s): %s", key, e)

    def _build_tool(self, key, page):
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        btn_back = QPushButton("← 返回媒体工具")
        btn_back.setObjectName("secondary_button")
        stack = self._stack
        if stack is not None:
            btn_back.clicked.connect(partial(stack.setCurrentIndex, 0))
        bar.addWidget(btn_back)
        bar.addStretch()
        lay.addLayout(bar)

        content = QWidget()
        lay.addWidget(content, 1)

        mw = self.main_window
        if key == "cover_maker":
            try:
                from gui.cover_maker_page import CoverMakerPage
                log.info("[媒体工具] 开始构建封面制作工具")
                tool = CoverMakerPage(content, mw)
                tool.setup()
                log.info("[媒体工具] 封面制作工具构建完成")
                self._tool_pages[key] = tool
            except Exception as e:  # 封面制作构建失败时显示用户可见错误
                log.exception("[媒体工具] 封面制作工具构建异常: %s", e)
                err = QLabel(
                    f"封面制作初始化失败：\n{e}\n\n"
                    f"详情请查看 app.log 中 [媒体工具] 相关日志。"
                )
                err.setWordWrap(True)
                err.setStyleSheet(
                    "padding:20px; color:#fca5a5; font-size:13px;"
                    " background:#1a1518; border:1px solid #7f1d1d; border-radius:8px;"
                )
                content_layout = QVBoxLayout(content)
                content_layout.addWidget(err)
                try:
                    QMessageBox.critical(
                        page,
                        "封面制作初始化失败",
                        f"{e}\n\n详情请查看 app.log",
                    )
                except Exception:
                    pass
        elif key == "image_matting":
            from gui.image_matting_page import ImageMattingPage
            self._tool_pages[key] = ImageMattingPage(content, mw)
        elif key == "image_folder_ocr":
            from gui.image_folder_ocr_page import ImageFolderOcrPage
            self._tool_pages[key] = ImageFolderOcrPage(content, mw)
        elif key == "video_tools":
            self._tool_pages[key] = mw.setup_video_tools_page(content)
        elif key == "transcription":
            from gui.transcription_page import TranscriptionToolPage
            self._tool_pages[key] = TranscriptionToolPage(content, mw)
        elif key == "voice_clone":
            from gui.voice_clone_page import VoiceClonePage
            self._tool_pages[key] = VoiceClonePage(content, mw)
        elif key == "subtitle_removal":
            from gui.subtitle_removal_page_v14 import SubtitleRemovalPageV14
            self._tool_pages[key] = SubtitleRemovalPageV14(content, mw)
        elif key == "video_ocr":
            from gui.video_ocr_page import VideoOcrPage
            self._tool_pages[key] = VideoOcrPage(content, mw)
        elif key == "image_prompt":
            from gui.prompt_reverse_page import ImagePromptReversePage
            self._tool_pages[key] = ImagePromptReversePage(content, mw)
        elif key == "video_prompt":
            from gui.prompt_reverse_page import VideoPromptReversePage
            self._tool_pages[key] = VideoPromptReversePage(content, mw)
        else:
            raise ValueError(f"未知媒体工具: {key}")
        if self._tool_pages.get(key) is not None and key != "cover_maker":
            page_cls = self._tool_pages[key]
            setup_fn = getattr(page_cls, "setup", None)
            if setup_fn is not None:
                setup_fn()
