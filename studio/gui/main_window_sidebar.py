# -*- coding: utf-8 -*-
"""MainWindow 的侧边栏/导航 mixin（setup_sidebar / switch_page / update_nav_focus），从 gui_main 拆出。"""

import subprocess
import time
import json
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


class SidebarMixin:
    def setup_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(0)
        
        # Create scroll area for menu items to handle the larger 22px font size cleanly
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(8, 12, 8, 12)
        scroll_layout.setSpacing(12)
        
        self.nav_buttons = []



        # 3. 账户平台 Section
        account_card = QFrame()
        account_card.setProperty("section_type", "account")
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(6, 8, 6, 8)
        account_layout.setSpacing(2)

        account_header = QLabel("账户平台")
        account_header.setObjectName("section_header")
        account_layout.addWidget(account_header)

        account_btn = QPushButton("👥 抖音账户")
        account_btn.setObjectName("nav_button")
        account_btn.setProperty("target_index", 8)
        account_btn.setCursor(Qt.PointingHandCursor)
        account_btn.clicked.connect(lambda checked=False: self.switch_page(8))
        account_layout.addWidget(account_btn)
        self.nav_buttons.append(account_btn)
        scroll_layout.addWidget(account_card)

        # 4. 方案脚本 Section
        script_card = QFrame()
        script_card.setProperty("section_type", "ai")
        script_layout = QVBoxLayout(script_card)
        script_layout.setContentsMargins(6, 8, 6, 8)
        script_layout.setSpacing(2)
        
        script_header = QLabel("方案脚本")
        script_header.setObjectName("section_header")
        script_layout.addWidget(script_header)
        
        script_menus = [
            ("📚 我的知识库", 29),
            ("📦 产品资料", 28),
            ("🛒 产品文案创作", 30),
            ("📝 分镜脚本创作", 38),
            ("✍️ 飞书选题文案", 20),
        ]
        for text, index in script_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            script_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        scroll_layout.addWidget(script_card)

        # 媒体库 Section
        media_card = QFrame()
        media_card.setProperty("section_type", "ai")
        media_layout = QVBoxLayout(media_card)
        media_layout.setContentsMargins(6, 8, 6, 8)
        media_layout.setSpacing(2)

        media_header = QLabel("媒体库")
        media_header.setObjectName("section_header")
        media_layout.addWidget(media_header)

        media_menus = [
            ("🎨 即梦生成", 32),
            ("🪄 MG 动画", 36),
            ("🗄️ 素材管理", 42),
            ("🔍 向量检索", 39),
            ("📋 任务列表", 9),
        ]
        for text, index in media_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            media_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        # 直接打开素材浏览器（外部 Electron 应用，非页面切换）
        btn_browser = QPushButton("🌐 素材浏览器")
        btn_browser.setObjectName("nav_button")
        btn_browser.setCursor(Qt.PointingHandCursor)
        btn_browser.clicked.connect(lambda checked=False: self.open_asset_browser())
        media_layout.addWidget(btn_browser)
        scroll_layout.addWidget(media_card)

        # 成片制作 Section
        compose_card = QFrame()
        compose_card.setProperty("section_type", "ai")
        compose_layout = QVBoxLayout(compose_card)
        compose_layout.setContentsMargins(6, 8, 6, 8)
        compose_layout.setSpacing(2)

        compose_header = QLabel("成片制作")
        compose_header.setObjectName("section_header")
        compose_layout.addWidget(compose_header)

        compose_menus = [
            ("🚀 一键成片", 34),
            ("✂️ 智能混剪", 15),
            ("📡 直播切片", 19),
        ]
        for text, index in compose_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            compose_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        scroll_layout.addWidget(compose_card)

        # 5. 图形处理 Section
        graphics_card = QFrame()
        graphics_card.setProperty("section_type", "ai")
        graphics_layout = QVBoxLayout(graphics_card)
        graphics_layout.setContentsMargins(6, 8, 6, 8)
        graphics_layout.setSpacing(2)
        
        graphics_header = QLabel("图形处理")
        graphics_header.setObjectName("section_header")
        graphics_layout.addWidget(graphics_header)
        
        graphics_menus = [
            ("🖼️ 封面制作", 33),
            ("👤 图像抠图", 16),
            ("🗂️ 智能分层", 17),
            ("👁️ 图片框选 OCR", 25),
        ]
        for text, index in graphics_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            graphics_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        scroll_layout.addWidget(graphics_card)

        # 6. 视频处理 Section
        video_card = QFrame()
        video_card.setProperty("section_type", "ai")
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(6, 8, 6, 8)
        video_layout.setSpacing(2)
        
        video_header = QLabel("视频处理")
        video_header.setObjectName("section_header")
        video_layout.addWidget(video_header)
        
        video_menus = [
            ("🗣️ 数字人", 3),
            ("💬 视频转文字", 12),
            ("🎙️ 声音克隆", 21),
            ("🎞️ 视频去字幕", 18),
            ("✨ 视频修复", 11),
            ("🔎 视频框选 OCR", 24),
            ("🏷️ 视频智能重命名", 26),
            ("🌈 批量 LUT 调色", 27),
            ("📈 视频预测评价", 35),
            ("📢 营销视频检测", 41),
        ]
        for text, index in video_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            video_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        scroll_layout.addWidget(video_card)

        # 5. 系统配置 Section
        system_card = QFrame()
        system_card.setProperty("section_type", "system")
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(6, 8, 6, 8)
        system_layout.setSpacing(2)
        
        system_header = QLabel("系统配置")
        system_header.setObjectName("section_header")
        system_layout.addWidget(system_header)
        
        other_menus = [
            ("⚙️ 模型配置", 7),
            ("🔌 平台接入", 23),
            ("📦 资源配置", 22),
            ("🖥️ 运行环境", 37),
            ("❓ 帮助", 6)
        ]
        for text, index in other_menus:
            btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            system_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        scroll_layout.addWidget(system_card)
            
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        self.sidebar_layout.addWidget(scroll)
        
        footer = QLabel("v2.0.0 RC")
        footer.setObjectName("sidebar_footer")
        self.sidebar_layout.addWidget(footer)
        self.main_layout.addWidget(self.sidebar)

    def open_python_terminal(self):
        """
        打开一个外部终端，自动激活当前 Python 环境：
        优先 Windows Terminal (wt.exe) → PowerShell → cmd.exe
        工作目录为本项目根目录，PATH 前置当前 Python 的 Scripts 目录。
        """
        import sys, os, subprocess

        python_exe  = sys.executable                        # e.g. D:\venv\Scripts\python.exe
        python_dir  = os.path.dirname(python_exe)           # e.g. D:\venv\Scripts
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录

        activate    = os.path.join(python_dir, "activate.bat")
        if os.path.isfile(activate):
            # 在 venv 里：先 activate 再进交互
            init_cmd = f'call "{activate}" && cd /d "{project_dir}"'
        else:
            # 非 venv：只把 Scripts 目录加到 PATH
            init_cmd = f'set PATH={python_dir};%PATH% && cd /d "{project_dir}"'

        banner = f'echo [Python 终端] {python_exe} && python --version'
        full_cmd = f'{init_cmd} && {banner}'

        # 尝试顺序：Windows Terminal → PowerShell → CMD
        try:
            subprocess.Popen(
                ["wt.exe", "--", "cmd.exe", "/K", full_cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        except FileNotFoundError:
            pass

        try:
            ps_init = (
                f'$env:PATH = "{python_dir};" + $env:PATH; '
                f'Set-Location "{project_dir}"; '
                f'Write-Host "[Python 终端] {python_exe}" -ForegroundColor Cyan; '
                f'python --version'
            )
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", ps_init],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        except FileNotFoundError:
            pass

        # 最终 fallback：CMD
        subprocess.Popen(
            ["cmd.exe", "/K", full_cmd],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    def open_asset_browser(self):
        """直接打开素材浏览器（外部 Electron 应用）。"""
        try:
            from utils import asset_browser_client as abrowser
            ok, msg = abrowser.launch()
            if not ok:
                QMessageBox.warning(self, "无法打开素材浏览器", msg)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开素材浏览器失败：{e}")

    def switch_page(self, index):
        # Update Content Stack
        self.content_stack.setCurrentIndex(index)
        
        # 1. Update Navigation Focus (Visual Only)
        self.update_nav_focus(index)
        
        # 2. Trigger Page Specific Logic
        self.trigger_page_logic(index)

    def update_nav_focus(self, index):
        """Purely handles the visual active state of sidebar buttons"""
        for btn in self.nav_buttons:
            target = btn.property("target_index")
            is_active = (str(target) == str(index))
            if str(target) == "8" and str(index) == "10":
                is_active = True
            new_val = "true" if is_active else "false"
            # Only repaint buttons whose state actually changed (avoids 60+ style ops per switch)
            if btn.property("active") != new_val:
                btn.setProperty("active", new_val)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
