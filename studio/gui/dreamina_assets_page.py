# -*- coding: utf-8 -*-
import os
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QLineEdit,
    QFileDialog, QListWidget, QListWidgetItem, QTextEdit,
)

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from config.paths import MATERIALS_DIR


class _IndexAnalyzeWorker(BaseWorker):
    log_line = Signal(str)
    finished = Signal(dict)

    def __init__(self, directory: str):
        super().__init__()
        self.directory = directory

    def do_work(self):
        result = {
            "index_ok": 0,
            "index_skip": 0,
            "index_fail": 0,
        }
        with MaterialClipIndexer(progress_cb=self.log_line.emit) as idx:
            ok, skip, fail = idx.index_directory_meta(self.directory, force=False)
            result["index_ok"] = ok
            result["index_skip"] = skip
            result["index_fail"] = fail
        self.finished.emit(result)


class DreaminaAssetsPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.media = MediaLibraryManager()
        self._current_dir = os.path.join(MATERIALS_DIR, "dreamina_assets")
        os.makedirs(self._current_dir, exist_ok=True)

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(14)

        heading = QLabel("🧺 即梦素材")
        heading.setObjectName("heading")
        root.addWidget(heading)

        tip = QLabel("浏览即梦素材请点击『打开即梦素材浏览器』。下载到本地后，可在本页一键入库。")
        tip.setObjectName("muted_text")
        tip.setWordWrap(True)
        root.addWidget(tip)

        root.addWidget(self._build_dir_card())
        root.addWidget(self._build_files_card(), 1)
        root.addWidget(self._build_log_card(), 1)

        self._scan_local_files()

    def _build_dir_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("下载目录"))
        self.edit_dir = QLineEdit(self._current_dir)
        row.addWidget(self.edit_dir, 1)
        btn_choose = QPushButton("选择")
        btn_choose.setObjectName("secondary_button")
        btn_choose.clicked.connect(self._choose_dir)
        row.addWidget(btn_choose)
        btn_open_dir = QPushButton("打开目录")
        btn_open_dir.setObjectName("secondary_button")
        btn_open_dir.clicked.connect(self._open_dir)
        row.addWidget(btn_open_dir)
        lay.addLayout(row)

        acts = QHBoxLayout()
        self.btn_open_browser = QPushButton("🌐 打开即梦素材浏览器")
        self.btn_open_browser.setObjectName("primary_button")
        self.btn_open_browser.clicked.connect(self._open_dreamina_browser)
        acts.addWidget(self.btn_open_browser)

        self.btn_add_media = QPushButton("📥 加入素材管理")
        self.btn_add_media.setObjectName("secondary_button")
        self.btn_add_media.clicked.connect(self._add_to_media)
        acts.addWidget(self.btn_add_media)

        self.btn_refresh = QPushButton("↺ 刷新文件列表")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self._scan_local_files)
        acts.addWidget(self.btn_refresh)
        acts.addStretch()
        lay.addLayout(acts)
        return card

    def _build_files_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.lbl_stat = QLabel("共 0 个可入库文件")
        self.lbl_stat.setObjectName("muted_text")
        top.addWidget(self.lbl_stat, 1)

        self.btn_index = QPushButton("⚡ 一键入库")
        self.btn_index.setObjectName("primary_button")
        self.btn_index.clicked.connect(self._start_index)
        top.addWidget(self.btn_index)

        lay.addLayout(top)

        self.file_list = QListWidget()
        lay.addWidget(self.file_list, 1)
        return card

    def _build_log_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)
        lay.addWidget(QLabel("操作日志"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        lay.addWidget(self.log_box, 1)
        return card

    def _dir(self) -> str:
        d = self.edit_dir.text().strip() or self._current_dir
        return os.path.abspath(d)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择即梦素材下载目录", self._dir())
        if not d:
            return
        self.edit_dir.setText(os.path.abspath(d))
        self._scan_local_files()

    def _open_dir(self):
        d = self._dir()
        os.makedirs(d, exist_ok=True)
        if os.name == "nt":
            os.startfile(d)  # noqa

    def _open_dreamina_browser(self):
        d = self._dir()
        os.makedirs(d, exist_ok=True)
        try:
            from utils import asset_browser_client as abrowser
            ok, msg, _ = abrowser.launch_dreamina_assets(d)
            if ok:
                self.log_box.append(f"✅ {msg}\n下载目录：{d}")
            else:
                self.show_warning(msg, "无法打开素材浏览器")
        except Exception as e:
            self.show_error(f"打开素材浏览器失败：\n{e}")

    def _scan_local_files(self):
        d = self._dir()
        os.makedirs(d, exist_ok=True)
        self._current_dir = d
        self.file_list.clear()

        media_exts = set(IMAGE_EXTS) | set(VIDEO_EXTS)
        files = []
        for root, _, fs in os.walk(d):
            for name in fs:
                ext = os.path.splitext(name)[1].lower()
                if ext in media_exts:
                    files.append(os.path.join(root, name))

        files.sort()
        for fp in files:
            rel = os.path.relpath(fp, d)
            self.file_list.addItem(QListWidgetItem(rel))
        self.lbl_stat.setText(f"共 {len(files)} 个可入库文件")

    def _add_to_media(self):
        d = self._dir()
        os.makedirs(d, exist_ok=True)
        ok, msg, _ = self.media.add_mount(d, kind="项目", group="即梦素材", tags=["即梦", "下载素材"])
        self.show_info(msg if ok else f"未添加：{msg}")

    def _set_busy(self, busy: bool):
        self.btn_index.setEnabled(not busy)
        self.btn_index_ai.setEnabled(not busy)
        self.btn_open_browser.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)

    def _start_index(self):
        d = self._dir()
        if not os.path.isdir(d):
            self.show_warning("请先选择有效的下载目录。")
            return

        self._set_busy(True)
        self.log_box.append(f"\n[{datetime.now().strftime('%H:%M:%S')}] 开始一键入库: {d}")

        w = self.track_worker(_IndexAnalyzeWorker(d))
        w.log_line.connect(self.log_box.append)
        w.finished.connect(self._on_index_done)
        w.error.connect(self._on_index_error)
        w.start()

    def _on_index_done(self, result: dict):
        self._set_busy(False)
        self.log_box.append(
            f"\n✅ 入库完成  新增:{result.get('index_ok',0)}  跳过:{result.get('index_skip',0)}  失败:{result.get('index_fail',0)}"
        )
        self._scan_local_files()

    def _on_index_error(self, msg: str):
        self._set_busy(False)
        self.log_box.append(f"\n❌ 操作失败: {msg}")
        self.show_error(f"执行失败：\n{msg}")
