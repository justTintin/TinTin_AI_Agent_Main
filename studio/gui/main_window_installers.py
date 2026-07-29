# -*- coding: utf-8 -*-
"""MainWindow 的安装器 mixin（Playwright / PaddleOCR 修复），从 gui_main 拆出。"""

import subprocess
import time
import json
import zipfile
import shutil
from config.paths import BUNDLED_PW_BROWSERS_ZIP
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT
)
import threading
import uuid
import configparser
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
from gui.subtitle_removal_page import SubtitleRemovalPage
from gui.live_clip_page import LiveClipPage
from gui.voice_clone_page import VoiceClonePage
from gui.voice_samples_page import VoiceSamplesPage
from gui.video_ocr_page import VideoOcrPage
from gui.image_folder_ocr_page import ImageFolderOcrPage
from utils.logger_utils import log, get_last_logs
from utils.account_manager import AccountManager
from core.creator_browser_controller import CreatorBrowserController
from utils.thread_worker import TaskWorker as Worker
from gui.threads import SystemMonitorThread, ComfyWSThread
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QDialog, QListWidget, 
                                 QListWidgetItem, QGridLayout, QFileDialog, 
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont


class PaddleOcrInstallWorker(QThread):
    """OCR 已迁移至服务端 POST /material/ocr，本地安装逻辑已废弃。

    此类仅作兼容保留（部分旧引用可能仍在），不再执行任何本地 PaddleOCR 安装。
    """
    log_line = Signal(str)
    stage = Signal(str)
    busy = Signal(bool)
    finished = Signal(bool, str)

    def run(self):
        self.busy.emit(True)
        self.stage.emit("OCR 已切换为服务端模式，无需本地部署")
        self.log_line.emit("[INFO] OCR 现由算力服务端 /material/ocr 提供，无需本地 PaddleOCR 环境。")
        self.busy.emit(False)
        self.finished.emit(True, "OCR 已为服务端模式，无需本地部署")


class InstallersMixin:
    def is_playwright_chromium_present(self):
        if not os.path.isdir(PW_BROWSERS_DIR):
            return False
        for root, dirs, files in os.walk(PW_BROWSERS_DIR):
            if "chrome.exe" in files:
                return True
        return False

    def ensure_playwright_chromium_ready(self):
        self._pw_ready = self.is_playwright_chromium_present()
        if self._pw_ready:
            return
        if not self._pw_install_running:
            self.install_playwright_chromium()

    def install_playwright_chromium(self):
        if self._pw_install_running:
            return
        self._pw_install_running = True
        if hasattr(self, "cg_install_btn"):
            self.cg_install_btn.setEnabled(False)
        if hasattr(self, "cg_status_label"):
            self.cg_status_label.setText("正在安装 Chromium 内核（首次可能较慢）...")

        def run_install():
            try:
                if os.path.exists(BUNDLED_PW_BROWSERS_ZIP):
                    os.makedirs(PW_BROWSERS_DIR, exist_ok=True)
                    with zipfile.ZipFile(BUNDLED_PW_BROWSERS_ZIP, "r") as zf:
                        zf.extractall(PW_BROWSERS_DIR)
                    return {"code": 0, "out": "unzipped"}
            except Exception as e:
                return {"code": 2, "out": f"unzip_failed: {e}"}

            env = os.environ.copy()
            env["PLAYWRIGHT_BROWSERS_PATH"] = PW_BROWSERS_DIR
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            return {"code": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}

        def on_done(res):
            code = res.get("code")
            out = res.get("out", "")
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if code == 0:
                self._pw_ready = True
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装完成")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText("")
            else:
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装失败")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText(out[-800:])

        def on_err(err):
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if hasattr(self, "cg_error_label"):
                self.cg_error_label.setText(err)
            if hasattr(self, "cg_status_label"):
                self.cg_status_label.setText("Chromium 内核安装失败")

        self.start_worker(run_install, on_finished=on_done, on_error=on_err)

    def start_paddle_repair(self):
        """OCR 已为服务端模式，无需本地部署。此方法仅作兼容保留。"""
        QMessageBox.information(self, "无需部署", "OCR 已切换为服务端模式（/material/ocr），无需本地 PaddleOCR 环境。")
