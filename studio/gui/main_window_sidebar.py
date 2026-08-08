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
from version import get_version
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
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
from utils.gui_icons import mdi_button, mdi_icon


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
        scroll_content.setObjectName("scroll_page")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(8, 12, 8, 12)
        scroll_layout.setSpacing(12)
        
        self.nav_buttons = []
        # Role-mode switch (ops / pro) at the top of the sidebar
        self._build_role_switcher(scroll_layout)

        # Full professional nav container (pro mode); hidden in ops mode
        self._nav_full = QWidget()
        self._nav_full_lay = QVBoxLayout(self._nav_full)
        self._nav_full_lay.setContentsMargins(0, 0, 0, 0)
        self._nav_full_lay.setSpacing(12)
        scroll_layout.addWidget(self._nav_full)

        # Ops workbench entry at the very top (available in both modes)
        btn_home = mdi_button("运营工作台", "home")
        btn_home.setObjectName("nav_button")
        btn_home.setProperty("target_index", 46)
        btn_home.setCursor(Qt.PointingHandCursor)
        btn_home.clicked.connect(lambda checked=False: self.switch_page(46))
        self._nav_full_lay.addWidget(btn_home)
        self.nav_buttons.append(btn_home)

        # 素材浏览器（菜单最顶部，直接打开外部 Electron 应用，非页面切换）
        btn_browser = mdi_button("素材浏览器", "web")
        btn_browser.setObjectName("nav_button")
        btn_browser.setCursor(Qt.PointingHandCursor)
        btn_browser.clicked.connect(lambda checked=False: self.open_asset_browser())
        self._nav_full_lay.addWidget(btn_browser)

        # 3. 账户平台 Section (暂时隐藏)
        # account_card = QFrame()
        # account_card.setProperty("section_type", "account")
        # account_layout = QVBoxLayout(account_card)
        # account_layout.setContentsMargins(6, 8, 6, 8)
        # account_layout.setSpacing(2)
        #
        # account_header = QLabel("账户平台")
        # account_header.setObjectName("section_header")
        # account_layout.addWidget(account_header)
        #
        # account_btn = QPushButton("👥 抖音账户")
        # account_btn.setObjectName("nav_button")
        # account_btn.setProperty("target_index", 8)
        # account_btn.setCursor(Qt.PointingHandCursor)
        # account_btn.clicked.connect(lambda checked=False: self.switch_page(8))
        # account_layout.addWidget(account_btn)
        # self.nav_buttons.append(account_btn)
        # scroll_layout.addWidget(account_card)

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
            ("我的知识库", 28, "book"),
            ("产品资料", 27, "database"),
            ("产品文案创作", 29, "text"),
            ("飞书脚本创作", 19, "clipboard-text"),
            ("分镜脚本创作", 37, "movie-open"),
        ]
        for text, index, icon_name in script_menus:
            if icon_name:
                btn = mdi_button(text, icon_name)
            else:
                btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            script_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self._nav_full_lay.addWidget(script_card)

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
            ("素材生成", 31, "palette"),
            ("素材检索", 38, "text-box-search"),
            ("音频素材", 44, "music"),
            ("即梦素材", 41, "image-multiple"),
            ("任务队列", 9, "format-list-checks"),
            ("媒体工具", 45, "tools"),
        ]
        for text, index, icon_name in media_menus:
            if icon_name:
                btn = mdi_button(text, icon_name)
            else:
                btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            media_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self._nav_full_lay.addWidget(media_card)

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
            ("成片任务", 42, "clock-outline"),
            ("一键成片", 33, "rocket"),
            ("智能混剪", 14, "content-cut"),
            ("直播切片", 18, "broadcast"),
        ]
        for text, index, icon_name in compose_menus:
            if icon_name:
                btn = mdi_button(text, icon_name)
            else:
                btn = QPushButton(text)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            compose_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self._nav_full_lay.addWidget(compose_card)

        # 7. 视频运营 Section
        ops_card = QFrame()
        ops_card.setProperty("section_type", "ai")
        ops_layout = QVBoxLayout(ops_card)
        ops_layout.setContentsMargins(6, 8, 6, 8)
        ops_layout.setSpacing(2)

        ops_header = QLabel("视频运营")
        ops_header.setObjectName("section_header")
        ops_layout.addWidget(ops_header)

        ops_menus = [
            ("视频评价预测", 34, "chart-line"),
            ("视频营销检测", 40, "bullhorn"),
        ]
        for text, index, icon_name in ops_menus:
            btn = mdi_button(text, icon_name)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            ops_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self._nav_full_lay.addWidget(ops_card)

        # 5. 系统配置 Section
        system_card = QFrame()
        system_card.setProperty("section_type", "system")
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(6, 8, 6, 8)
        system_layout.setSpacing(2)
        
        system_header = QLabel("系统设置")
        system_header.setObjectName("section_header")
        system_layout.addWidget(system_header)
        
        other_menus = [
            ("模型配置", 7, "cog"),
            ("平台接入", 22, "link"),
            ("本地配置", 21, "download"),
            ("环境与维护", 36, "server"),
            ("扩展插件", 43, "puzzle"),
            ("关于", 6, "information"),
        ]
        for text, index, icon_name in other_menus:
            btn = mdi_button(text, icon_name)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", index)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
            system_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self._nav_full_lay.addWidget(system_card)
            
        self._nav_full_lay.addStretch()
        # Ops compact nav (ops mode)
        self._nav_ops = QWidget()
        self._nav_ops_lay = QVBoxLayout(self._nav_ops)
        self._nav_ops_lay.setContentsMargins(0, 0, 0, 0)
        self._nav_ops_lay.setSpacing(2)
        self._add_ops_section("高频任务", [
            ("一键成片", 33, "rocket"),
            ("智能混剪", 14, "cut"),
            ("声音克隆", 20, "mic"),
            ("直播切片", 18, "video"),
            ("封面制作", 32, "camera"),
            ("营销检测", 40, "sparkles"),
            ("视频评价", 34, "film"),
        ])
        self._add_ops_section("任务", [
            ("成片任务", 42, "folder"),
        ])
        self._add_ops_section("系统设置", [
            ("模型配置", 7, "cog"),
            ("平台接入", 22, "link"),
            ("本地配置", 21, "download"),
            ("环境与维护", 36, "server"),
            ("关于", 6, "information"),
        ])
        self._nav_ops_lay.addStretch()
        scroll_layout.addWidget(self._nav_ops)

        # Apply persisted role mode (ops home / pro full nav)
        self.set_role_mode(self._load_role_mode())
        scroll.setWidget(scroll_content)
        self.sidebar_layout.addWidget(scroll)
        
        footer = QLabel(f"v{get_version()}")
        footer.setObjectName("sidebar_footer")
        self.sidebar_layout.addWidget(footer)
        self.main_layout.addWidget(self.sidebar)

    def _build_role_switcher(self, layout):
        """顶部角色模式切换（运营 / 剪辑）。"""
        box = QFrame()
        box.setStyleSheet("QFrame { background:#1d212b; border:1px solid #262b36; border-radius:10px; }")
        h = QHBoxLayout(box)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(3)
        self._role_ops_btn = QPushButton("运营模式")
        self._role_pro_btn = QPushButton("剪辑模式")
        for b in (self._role_ops_btn, self._role_pro_btn):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton { border:0; border-radius:7px; padding:6px 8px; color:#8b93a3; font-size:12px; font-weight:600; background:transparent; } QPushButton:checked { background:#3b82f6; color:#fff; }")
        self._role_ops_btn.clicked.connect(lambda: self.set_role_mode("ops"))
        self._role_pro_btn.clicked.connect(lambda: self.set_role_mode("pro"))
        h.addWidget(self._role_ops_btn)
        h.addWidget(self._role_pro_btn)
        layout.addWidget(box)

    def _add_ops_section(self, title, items):
        card = QFrame()
        card.setProperty("section_type", "ai")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(2)
        header = QLabel(title)
        header.setObjectName("section_header")
        lay.addWidget(header)
        for text, index, icon in items:
            self._add_ops_nav_item(lay, text, index, icon)
        self._nav_ops_lay.addWidget(card)

    def _add_ops_nav_item(self, lay, text, index, icon_name):
        btn = mdi_button(text, icon_name)
        btn.setObjectName("nav_button")
        btn.setProperty("target_index", index)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda checked=False, i=index: self.switch_page(i))
        lay.addWidget(btn)
        self.nav_buttons.append(btn)

    def set_role_mode(self, mode):
        """切换运营/剪辑模式：切换侧边栏形态并持久化到本地配置。"""
        mode = mode if mode in ("ops", "pro") else "pro"
        self._role_mode = mode
        self._save_role_mode(mode)
        if hasattr(self, "_nav_ops") and hasattr(self, "_nav_full"):
            self._nav_ops.setVisible(mode == "ops")
            self._nav_full.setVisible(mode == "pro")
        if hasattr(self, "_role_ops_btn"):
            self._role_ops_btn.setChecked(mode == "ops")
            self._role_pro_btn.setChecked(mode == "pro")

    def _role_cfg_file(self):
        return os.path.join(PROJECT_ROOT, "config", "local_config.json")

    def _load_role_mode(self):
        try:
            import json
            if os.path.isfile(self._role_cfg_file()):
                data = json.load(open(self._role_cfg_file(), "r", encoding="utf-8"))
                mode = data.get("role_mode", "pro")
                return mode if mode in ("ops", "pro") else "pro"
        except Exception:
            pass
        return "pro"

    def _save_role_mode(self, mode):
        try:
            import json
            p = self._role_cfg_file()
            data = {}
            if os.path.isfile(p):
                data = json.load(open(p, "r", encoding="utf-8"))
            data["role_mode"] = mode
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"保存角色模式失败: {e}")

    def open_python_terminal(self):
        """
        打开一个外部终端，自动激活当前 Python 环境：
        优先 Windows Terminal (wt.exe) → PowerShell → cmd.exe
        工作目录为本项目根目录，PATH 前置当前 Python 的 Scripts 目录。
        """
        import sys, os, subprocess

        python_exe  = sys.executable                        # e.g. D:\venv\Scripts\python.exe
        python_dir  = os.path.dirname(python_exe)           # e.g. D:\venv\Scripts
        project_dir = PROJECT_ROOT  # studio 根目录（由 paths.py 管理）

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
        if hasattr(self, "_ensure_page_built"):
            self._ensure_page_built(index)
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
