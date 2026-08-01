# -*- coding: utf-8 -*-
"""媒体工具：把「图片处理」与「视频处理」两组子页面聚合为一个标签页界面。

侧边栏只保留一个入口「媒体工具」，内部用 QTabWidget 承载：
  封面制作 / 图像抠图 / 图片框选OCR / 视频修复 / 视频转文字 /
  声音克隆 / 视频去字幕 / 视频框选OCR / 批量LUT调色
各标签懒加载：首次切换到该标签时才构建页面，缩短启动时间。
"""
import logging

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

log = logging.getLogger(__name__)


class MediaToolsPage(QWidget):
    """媒体工具容器（图片处理 + 视频处理聚合）。"""

    # (标签标题, 构建 key)
    _TABS = [
        ("封面制作", "cover_maker"),
        ("图像抠图", "image_matting"),
        ("图片框选OCR", "image_folder_ocr"),
        ("视频修复", "video_tools"),
        ("视频转文字", "transcription"),
        ("声音克隆", "voice_clone"),
        ("视频去字幕", "subtitle_removal"),
        ("视频框选OCR", "video_ocr"),
        ("批量LUT调色", "video_lut"),
    ]

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget)
        self.main_window = main_window
        self._built = set()
        self._containers = []
        self.tabs = None

    def setup(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for title, _key in self._TABS:
            container = QWidget()
            self._containers.append(container)
            self.tabs.addTab(container, title)
        root.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._ensure_tab)

    def _ensure_tab(self, index):
        if index < 0 or index >= len(self._TABS) or index in self._built:
            return
        self._built.add(index)
        key = self._TABS[index][1]
        try:
            self._build_tab(key, self._containers[index])
        except Exception as e:
            log.error("[媒体工具] 标签页构建失败(%s): %s", key, e)

    def _build_tab(self, key, container):
        mw = self.main_window
        if key == "cover_maker":
            from gui.cover_maker_page import CoverMakerPage
            CoverMakerPage(container, mw).setup()
        elif key == "image_matting":
            from gui.image_matting_page import ImageMattingPage
            ImageMattingPage(container, mw).setup()
        elif key == "image_folder_ocr":
            from gui.image_folder_ocr_page import ImageFolderOcrPage
            ImageFolderOcrPage(container, mw).setup()
        elif key == "video_tools":
            # 视频修复是内联 UI（PageSetupMixin.setup_video_tools_page），
            # 直接以标签容器为目标构建一次。
            mw.setup_video_tools_page(container)
        elif key == "transcription":
            from gui.transcription_page import TranscriptionToolPage
            TranscriptionToolPage(container, mw).setup()
        elif key == "voice_clone":
            from gui.voice_clone_page import VoiceClonePage
            VoiceClonePage(container, mw).setup()
        elif key == "subtitle_removal":
            from gui.subtitle_removal_page_v14 import SubtitleRemovalPageV14
            SubtitleRemovalPageV14(container, mw).setup()
        elif key == "video_ocr":
            from gui.video_ocr_page import VideoOcrPage
            VideoOcrPage(container, mw).setup()
        elif key == "video_lut":
            from gui.video_lut_page import VideoLutPage
            VideoLutPage(container, mw).setup()
        else:
            raise ValueError("未知媒体工具标签: %s" % key)