# -*- coding: utf-8 -*-
"""
MainWindow 的页面装配 mixin（从 gui_main.py 拆出）。

仅包含「实例化页面工具并 setup」的纯委托方法；均操作 MainWindow 的 self，
行为与原先完全一致，只是定义移到此处以给 gui_main 瘦身。
"""


import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT,
    DREAMINA_OUTPUT_DIR, DREAMINA_EXE,
    MATERIALS_DIR, KNOWLEDGE_MATERIALS_DIR, DATA_DIR
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
                                  QSpinBox, QDoubleSpinBox, QTabWidget)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont
from utils.gui_icons import mdi_button, mdi_icon


class PageSetupMixin:
    def setup_transcription_page(self):
        self.transcription_tool = TranscriptionToolPage(self.page_transcription, self)
        self.transcription_tool.setup()

    def setup_env_config_page(self):
        self.env_config_tool = EnvConfigPage(self.page_env_config, self)
        self.env_config_tool.setup()

    def setup_subtitle_removal_page(self):
        self.subtitle_removal_tool = SubtitleRemovalPage(self.page_subtitle_removal, self)
        self.subtitle_removal_tool.setup()

    def setup_video_montage_page(self):
        from gui.video_montage_page import VideoMontagePage
        self.video_montage_tool = VideoMontagePage(self.page_video_montage, self)
        self.video_montage_tool.setup()

    def setup_image_matting_page(self):
        from gui.image_matting_page import ImageMattingPage
        self.image_matting_tool = ImageMattingPage(self.page_image_matting, self)
        self.image_matting_tool.setup()

    def setup_image_layered_page(self):
        from gui.image_layered_page import ImageLayeredPage
        self.image_layered_tool = ImageLayeredPage(self.page_image_layered, self)
        self.image_layered_tool.setup()

    def setup_live_clip_page(self):
        self.live_clip_tool = LiveClipPage(self.page_live_clip, self)
        self.live_clip_tool.setup()

    def setup_ai_script_page(self):
        from gui.ai_script_page import AIScriptPage
        self.ai_script_tool = AIScriptPage(self.page_ai_script, self)
        self.ai_script_tool.setup()

    def setup_voice_clone_page(self):
        from gui.voice_clone_page import VoiceClonePage
        self.voice_clone_tool = VoiceClonePage(self.page_voice_clone, self)
        self.voice_clone_tool.setup()

    def setup_voice_samples_page(self):
        layout = QVBoxLayout(self.page_voice_samples)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; QWidget { background: transparent; } } QTabBar::tab { padding: 8px 18px; font-size: 13px; } QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")

        # Tab 1: 声音样本
        p1 = QWidget(); p1.setStyleSheet("QWidget { background: transparent; }")
        from gui.voice_samples_page import VoiceSamplesPage
        self.voice_samples_tool = VoiceSamplesPage(p1, self); self.voice_samples_tool.setup()
        tabs.addTab(p1, "🎭 声音样本")

        layout.addWidget(tabs, 1)

    def setup_video_ocr_page(self):
        from gui.video_ocr_page import VideoOcrPage
        self.video_ocr_tool = VideoOcrPage(self.page_video_ocr, self)
        self.video_ocr_tool.setup()

    def setup_image_folder_ocr_page(self):
        from gui.image_folder_ocr_page import ImageFolderOcrPage
        self.image_folder_ocr_tool = ImageFolderOcrPage(self.page_image_folder_ocr, self)
        self.image_folder_ocr_tool.setup()

    def setup_video_ai_rename_page(self):
        from gui.video_ai_rename_page import VideoAiRenamePage
        self.video_ai_rename_tool = VideoAiRenamePage(self.page_video_ai_rename, self)
        self.video_ai_rename_tool.setup()

    def setup_video_lut_page(self):
        from gui.video_lut_page import VideoLutPage
        self.video_lut_tool = VideoLutPage(self.page_video_lut, self)
        self.video_lut_tool.setup()

    def setup_product_library_page(self):
        from gui.product_library_page import ProductLibraryPage
        self.product_library_tool = ProductLibraryPage(self.page_product_library, self)
        self.product_library_tool.setup()

    def setup_my_knowledge_page(self):
        from gui.my_knowledge_page import MyKnowledgePage
        self.my_knowledge_tool = MyKnowledgePage(self.page_my_knowledge, self)
        self.my_knowledge_tool.setup()

    def setup_product_script_page(self):
        from gui.product_script_page import ProductScriptPage
        self.product_script_tool = ProductScriptPage(self.page_product_script, self)
        self.product_script_tool.setup()

    def setup_storyboard_page(self):
        from gui.storyboard_page import StoryboardPage
        self.storyboard_tool = StoryboardPage(self.page_storyboard, self)
        self.storyboard_tool.setup()


    def setup_vector_search_page(self):
        from gui.vector_search_page import VectorSearchPage
        self.vector_search_tool = VectorSearchPage(self.page_vector_search, self)
        self.vector_search_tool.setup()

    def setup_terminal_page(self):
        from gui.terminal_page import TerminalPage
        self.terminal_tool = TerminalPage(self.page_terminal, self)
        self.terminal_tool.setup()

    def setup_dreamina_page(self):
        from gui.dreamina_page import DreaminaPage
        self.dreamina_tool = DreaminaPage(self.page_dreamina, self)
        self.dreamina_tool.setup()

    def setup_dreamina_assets_page(self):
        from gui.dreamina_assets_page import DreaminaAssetsPage
        self.dreamina_assets_tool = DreaminaAssetsPage(self.page_dreamina_assets, self)
        self.dreamina_assets_tool.setup()

    def setup_cover_maker_page(self):
        from gui.cover_maker_page import CoverMakerPage
        self.cover_maker_tool = CoverMakerPage(self.page_cover_maker, self)
        self.cover_maker_tool.setup()

    def setup_compile_video_page(self):
        from gui.compile_video_page import CompileVideoPage
        self.compile_video_tool = CompileVideoPage(self.page_compile_video, self)
        self.compile_video_tool.setup()

    def setup_hook_score_page(self):
        from gui.hook_score_page import HookScorePage
        self.hook_score_tool = HookScorePage(self.page_hook_score, self)
        self.hook_score_tool.setup()

    def setup_mg_animation_page(self):
        from gui.mg_animation_page import MGAnimationPage
        self.mg_animation_tool = MGAnimationPage(self.page_mg_animation, self)
        self.mg_animation_tool.setup()

    def setup_marketing_detect_page(self):
        from gui.marketing_detect_page import MarketingDetectPage
        self.marketing_detect_tool = MarketingDetectPage(self.page_marketing_detect, self)
        self.marketing_detect_tool.setup()


    def setup_video_tools_page(self):
            layout = QVBoxLayout(self.page_video_tools)
            layout.setContentsMargins(40, 40, 40, 40)
        
            # Heading
            self.vt_main_heading = QLabel("视频修复")
            self.vt_main_heading.setObjectName("heading")
            layout.addWidget(self.vt_main_heading, 0)
        
            card_config = QFrame()
            card_config.setObjectName("card")
            config_layout = QVBoxLayout(card_config)
            config_layout.setContentsMargins(30, 30, 30, 30)
        
            # Backend Selection (Lock to ComfyUI for now)
            config_layout.addWidget(QLabel("选择生成后端:"))
            self.vt_backend_selector = QComboBox()
            self.vt_backend_selector.addItems(["ComfyUI (本地/局域网)"])
            config_layout.addWidget(self.vt_backend_selector)
        
            config_layout.addSpacing(15)

            # Workflow Selection
            config_layout.addWidget(QLabel("选择工作流 (assets/workflow):"))
            self.vt_workflow_selector = QComboBox()
            self.refresh_vt_workflows()
        
            self.vt_workflow_status = QLabel("请选择工作流并加载")
            config_layout.addWidget(self.vt_workflow_status)
        
            self.vt_workflow_selector.currentIndexChanged.connect(self.on_vt_workflow_changed)
            config_layout.addWidget(self.vt_workflow_selector)
        
            config_layout.addSpacing(20)

            # Video Input Section
            self.vt_video_input_label = QLabel("输入视频:")
            config_layout.addWidget(self.vt_video_input_label)
            video_row = QHBoxLayout()
            self.vt_video_path_input = QLineEdit()
            self.vt_video_path_input.setPlaceholderText("请选择视频文件...")
            video_row.addWidget(self.vt_video_path_input)
            btn_sel_video = QPushButton("浏览")
            btn_sel_video.clicked.connect(self.select_vt_video)
            video_row.addWidget(btn_sel_video)
            config_layout.addLayout(video_row)
        
            config_layout.addSpacing(20)
        
            self.btn_run_vt = mdi_button("提交视频处理任务", "rocket")
            self.btn_run_vt.setObjectName("action_button")
            self.btn_run_vt.setFixedHeight(50)
            self.btn_run_vt.clicked.connect(self.run_video_tool_task)
            config_layout.addWidget(self.btn_run_vt)
        
            layout.addWidget(card_config, 0)
            layout.addStretch()

            # Default select face detail fix workflow
            idx = self.vt_workflow_selector.findText("输入视频-修复脸部细节-20260113.json")
            if idx >= 0:
                self.vt_workflow_selector.setCurrentIndex(idx)
            else:
                self.on_vt_workflow_changed(self.vt_workflow_selector.currentIndex())

    def setup_hotspots_page(self):
            layout = QVBoxLayout(self.page_hotspots)
            layout.setContentsMargins(20, 8, 20, 16)
            layout.setSpacing(8)

            heading = QLabel("创作热点发现")
            heading.setObjectName("heading")
            layout.addWidget(heading)

            top_bar = QHBoxLayout()
            top_bar.setSpacing(10)
            top_bar.addStretch()

            btn_open = QPushButton("打开创作热点")
            btn_open.setObjectName("primary_button")
            btn_open.clicked.connect(self.open_creator_guidance_browser)
            top_bar.addWidget(btn_open)

            btn_install = QPushButton("安装/修复浏览器内核")
            btn_install.setObjectName("secondary_button")
            btn_install.clicked.connect(self.install_playwright_chromium)
            self.cg_install_btn = btn_install
            top_bar.addWidget(btn_install)

            btn_close = QPushButton("关闭外部浏览器")
            btn_close.setObjectName("secondary_button")
            btn_close.clicked.connect(self.close_creator_guidance_browser)
            top_bar.addWidget(btn_close)

            btn_refresh = QPushButton("刷新页面")
            btn_refresh.setObjectName("secondary_button")
            btn_refresh.clicked.connect(self.refresh_creator_guidance)
            top_bar.addWidget(btn_refresh)
            layout.addLayout(top_bar)

            self.cg_status_label = QLabel("就绪")
            self.cg_status_label.setObjectName("muted_text")
            layout.addWidget(self.cg_status_label)

            splitter = QSplitter(Qt.Horizontal)

            left_card = QFrame()
            left_card.setObjectName("card")
            left_layout = QVBoxLayout(left_card)
            left_layout.setContentsMargins(12, 12, 12, 12)
            left_layout.setSpacing(10)

            left_layout.addWidget(QLabel("使用外部 Chromium（Playwright）打开创作者热点页面。"))

            self.cg_current_url_edit = QLineEdit()
            self.cg_current_url_edit.setReadOnly(True)
            self.cg_current_url_edit.setPlaceholderText("未识别到视频链接")
            left_layout.addWidget(self.cg_current_url_edit)

            self.cg_add_btn = QPushButton("加入下载队列")
            self.cg_add_btn.setObjectName("action_button")
            self.cg_add_btn.setEnabled(False)
            self.cg_add_btn.clicked.connect(self.add_current_creator_video_to_queue)
            left_layout.addWidget(self.cg_add_btn)

            self.cg_error_label = QLabel("")
            self.cg_error_label.setObjectName("muted_text")
            left_layout.addWidget(self.cg_error_label)

            splitter.addWidget(left_card)

            right_card = QFrame()
            right_card.setObjectName("card")
            right_layout = QVBoxLayout(right_card)
            right_layout.setContentsMargins(12, 12, 12, 12)
            right_layout.setSpacing(10)

            right_header = QHBoxLayout()
            right_header.setSpacing(10)
            right_header.addWidget(QLabel("📥 已加入下载队列"))
            right_header.addStretch()
            self.cg_queue_count = QLabel("0")
            self.cg_queue_count.setObjectName("muted_text")
            right_header.addWidget(self.cg_queue_count)
            right_layout.addLayout(right_header)

            self.cg_queue_table = QTableWidget(0, 2)
            self.cg_queue_table.setHorizontalHeaderLabels(["视频链接", "操作"])
            self.cg_queue_table.verticalHeader().setVisible(False)
            self.cg_queue_table.setAlternatingRowColors(True)
            self.cg_queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.cg_queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.cg_queue_table.verticalHeader().setDefaultSectionSize(44)
            self.cg_queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.cg_queue_table.setColumnWidth(1, 90)
            right_layout.addWidget(self.cg_queue_table)

            splitter.addWidget(right_card)
            splitter.setStretchFactor(0, 2)
            splitter.setStretchFactor(1, 3)
            layout.addWidget(splitter, 1)

            self.refresh_creator_queue_table()
            self.creator_pw_poll_timer.setInterval(500)
            self.creator_pw_poll_timer.timeout.connect(self.poll_creator_browser_state)
            # 不在此处启动：仅在切换到热点页面时才 start，离开时 stop，避免主线程常驻 2次/秒 回调

    def setup_login_page(self):
            layout = QVBoxLayout(self.page_login)
            layout.setContentsMargins(40, 40, 40, 40)
        
            heading = QLabel("系统默认登录 (用于视频下载/搜索/热点)")
            heading.setObjectName("heading")
            layout.addWidget(heading)
        
            notice = QLabel("⚠️ 注意：此处登录的账号将作为系统抓取任务的默认全局身份。")
            notice.setStyleSheet("color: #e67e22; font-size: 13px; margin-bottom: 20px;")
            layout.addWidget(notice)
        
            acc_frame = QFrame()
            acc_frame.setObjectName("card")
            acc_layout = QVBoxLayout(acc_frame)
            acc_layout.setContentsMargins(30, 30, 30, 30)
            acc_layout.setSpacing(20)
        
            # Status Card Info
            self.lbl_default_login_status = QLabel("登录状态: 正在检测...")
            self.lbl_default_login_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #f39c12;")
            acc_layout.addWidget(self.lbl_default_login_status)
        
            self.lbl_default_cookie_path = QLabel(f"Cookie 存放路径: {os.path.join(PROJECT_ROOT, 'douyin_cookies.txt')}")
            self.lbl_default_cookie_path.setStyleSheet("color: #7f8c8d; font-size: 13px;")
            acc_layout.addWidget(self.lbl_default_cookie_path)
        
            # Guide info
            guide_lbl = QLabel(
                "说明：点击下方「打开独立登录窗口」后，系统将在外部启动一个独立的 Chromium 浏览器 (CEF)。\n"
                "在浏览器中登录您的抖音账号后，点击「提取并同步 Cookie」即可完成绑定。"
            )
            guide_lbl.setStyleSheet("color: #bdc3c7; font-size: 13px; line-height: 1.5;")
            acc_layout.addWidget(guide_lbl)
        
            # Action Buttons Layout
            btn_layout = QHBoxLayout()
            self.btn_open_default_browser = QPushButton("🌐 打开独立登录窗口")
            self.btn_open_default_browser.setObjectName("primary_button")
            self.btn_open_default_browser.clicked.connect(self.open_system_default_browser)
            btn_layout.addWidget(self.btn_open_default_browser)
        
            self.btn_sync_default_cookie = QPushButton("🍪 提取并同步 Cookie")
            self.btn_sync_default_cookie.clicked.connect(self.sync_system_default_cookie)
            btn_layout.addWidget(self.btn_sync_default_cookie)
            btn_layout.addStretch()
        
            acc_layout.addLayout(btn_layout)
            acc_layout.addStretch()
            layout.addWidget(acc_frame, 1)
        
            self.system_default_login_controller = None
            # QTimer triggers check after initialization
            QTimer.singleShot(200, self.update_system_default_login_status)

    # ═══════════════════════════════════════════════════════════════
    #  ⚙️ 系统设置 — 多 Tab，每 Tab 一个模块
    # ═══════════════════════════════════════════════════════════════
    def setup_ai_settings_page(self):
        layout = QVBoxLayout(self.page_ai_settings)
        layout.setContentsMargins(20, 20, 20, 20)
        heading = QLabel("⚙️ 模型配置"); heading.setObjectName("heading")
        layout.addWidget(heading, 0)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; QWidget { background: transparent; } } QTabBar::tab { padding: 8px 18px; font-size: 13px; } QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")

        def _page(): w = QWidget(); w.setStyleSheet("QWidget { background: transparent; }"); return w
        def _lr(p, w): r = QHBoxLayout(); r.addWidget(QLabel(p)); w(r); r.addStretch()
        def _row(w): r = QHBoxLayout(); w(r); return r
        # ───── Tab 1: LLM ─────
        p1 = _page(); l1 = QVBoxLayout(p1); l1.setContentsMargins(16,20,16,16); l1.setSpacing(10)
        g1 = QGroupBox("🤖 LLM 大语言模型"); g1.setObjectName("model_groupbox"); g1.setProperty("section", "llm"); lg1 = QVBoxLayout(g1); lg1.setSpacing(10)
        def _rl(l, p, w): r = QHBoxLayout(); r.addWidget(QLabel(p)); w(r); r.addStretch(); l.addLayout(r)
        def _inp(l, p, a, ph): e = QLineEdit(); e.setPlaceholderText(ph); setattr(self,a,e); _rl(l, p, lambda r: r.addWidget(e))
        _rl(lg1, "提供商:", lambda r: (setattr(self,'llm_provider_combo',QComboBox()), self.llm_provider_combo.setView(QListView()),
            self.llm_provider_combo.addItem("DeepSeek (推荐)","deepseek"), self.llm_provider_combo.addItem("OpenAI 兼容接口","openai"),
            self.llm_provider_combo.addItem("自定义","custom"), self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed), r.addWidget(self.llm_provider_combo)))
        _inp(lg1, "API 地址:", "llm_api_url_input", "https://api.deepseek.com")
        _inp(lg1, "API Key:", "llm_api_key_input", "sk-xxxxxxxxxxxxxxxx")
        
        # Configure API Key EchoMode and show/hide action
        self.llm_api_key_input.setEchoMode(QLineEdit.Password)
        self._llm_key_visible = False
        
        from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
        from PySide6.QtCore import Qt
        def make_eye_icon(visible):
            pix = QPixmap(16, 16)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(160, 160, 160), 1.5))
            # Eye outline
            painter.drawArc(1, 3, 14, 10, 45 * 16, 90 * 16)
            painter.drawArc(1, 3, 14, 10, 225 * 16, 90 * 16)
            # Pupil
            painter.setBrush(QColor(160, 160, 160))
            painter.drawEllipse(6, 6, 4, 4)
            if not visible:
                # Crossed out slash
                painter.drawLine(3, 3, 13, 13)
            painter.end()
            return QIcon(pix)
            
        self._llm_key_action = self.llm_api_key_input.addAction(make_eye_icon(False), QLineEdit.TrailingPosition)
        
        def toggle_key_visibility():
            self._llm_key_visible = not self._llm_key_visible
            self.llm_api_key_input.setEchoMode(QLineEdit.Normal if self._llm_key_visible else QLineEdit.Password)
            self._llm_key_action.setIcon(make_eye_icon(self._llm_key_visible))
            
        self._llm_key_action.triggered.connect(toggle_key_visibility)

        _inp(lg1, "文本模型:", "llm_model_input", "deepseek-v4-flash")
        rr1 = QHBoxLayout(); rr1.addStretch()
        self.btn_test_llm = mdi_button("测试连接", "search"); self.btn_test_llm.setObjectName("secondary_button"); self.btn_test_llm.setFixedWidth(110); self.btn_test_llm.clicked.connect(self._test_llm_connection); rr1.addWidget(self.btn_test_llm)
        b2 = mdi_button("保存", "save"); b2.setObjectName("primary_button"); b2.setFixedWidth(90); b2.clicked.connect(self.save_llm_config); rr1.addWidget(b2)
        lg1.addLayout(rr1)
        self.llm_status_lbl = QLabel(""); lg1.addWidget(self.llm_status_lbl)
        l1.addWidget(g1); l1.addStretch(); tabs.addTab(p1, "🤖 LLM")

        # ───── Tab 2: VoxCPM ─────
        p3 = _page(); l3 = QVBoxLayout(p3); l3.setContentsMargins(16,20,16,16); l3.setSpacing(10)
        g3 = QGroupBox("🗣️ 声音克隆 VoxCPM（远程）"); g3.setObjectName("model_groupbox"); g3.setProperty("section", "vox"); lg3 = QVBoxLayout(g3); lg3.setSpacing(10)
        _rl(lg3, "API 地址:", lambda r: (setattr(self,'vox_api_url_input',QLineEdit()), self.vox_api_url_input.setPlaceholderText("http://远程服务器IP:7861/v1/tts"), r.addWidget(self.vox_api_url_input)))
        lg3.addLayout(_row(lambda r: (r.addWidget(QLabel("推理步数:")), setattr(self,'vox_timesteps_spin',QSpinBox()), self.vox_timesteps_spin.setRange(5,100), self.vox_timesteps_spin.setValue(20), self.vox_timesteps_spin.setFixedWidth(70), r.addWidget(self.vox_timesteps_spin), r.addSpacing(20),
            r.addWidget(QLabel("CFG:")), setattr(self,'vox_cfg_spin',QDoubleSpinBox()), self.vox_cfg_spin.setRange(0.5,10.0), self.vox_cfg_spin.setSingleStep(0.1), self.vox_cfg_spin.setValue(2.0), self.vox_cfg_spin.setFixedWidth(70), r.addWidget(self.vox_cfg_spin), r.addStretch())))
        rr3 = QHBoxLayout()
        self.llm_vox_status_val = QLabel("服务状态: 请填写远程 API 地址并保存"); self.llm_vox_status_val.setObjectName("muted_text"); rr3.addWidget(self.llm_vox_status_val); rr3.addStretch()
        b3_test = mdi_button("测试连接", "search"); b3_test.setObjectName("secondary_button"); b3_test.setFixedWidth(110); b3_test.clicked.connect(self._test_vox_connection); rr3.addWidget(b3_test)
        b3 = mdi_button("保存", "save"); b3.setObjectName("secondary_button"); b3.setFixedWidth(80); b3.clicked.connect(self.save_voxcpm_config); rr3.addWidget(b3)
        lg3.addLayout(rr3)
        l3.addWidget(g3); l3.addStretch(); tabs.addTab(p3, "🗣️ VoxCPM")

        # ───── Tab 4: Ollama ─────
        p4 = _page(); l4 = QVBoxLayout(p4); l4.setContentsMargins(16,20,16,16); l4.setSpacing(10)
        g4 = QGroupBox("🖥️ Ollama 远程视觉服务"); g4.setObjectName("model_groupbox"); lg4 = QVBoxLayout(g4); lg4.setSpacing(10)
        lg4.addLayout(_row(lambda r: (setattr(self,'ollama_status_lbl',QLabel("● 未检测")), self.ollama_status_lbl.setObjectName("ollama_status_lbl"),
            setattr(self,'ollama_models_lbl',QLabel("已下载模型: (未检测)")), self.ollama_models_lbl.setObjectName("ollama_models_lbl"), self.ollama_models_lbl.setWordWrap(True), r.addWidget(self.ollama_models_lbl), r.addStretch())))
        lg4.addLayout(_row(lambda r: (
            setattr(self,'btn_ollama_refresh',mdi_button("刷新", "refresh")), self.btn_ollama_refresh.setObjectName("secondary_button"), self.btn_ollama_refresh.setFixedWidth(70), self.btn_ollama_refresh.clicked.connect(self._ollama_refresh_status),
            r.addWidget(self.btn_ollama_refresh), r.addStretch())))

        # ── 视觉模型配置（Ollama 托管的视觉模型，合并到此 Tab）──
        g_vm = QGroupBox("👁️ 当前视觉模型（由 Ollama 提供）"); g_vm.setObjectName("model_groupbox"); g_vm.setProperty("section", "vision"); lg_vm = QVBoxLayout(g_vm); lg_vm.setSpacing(10)
        _inp(lg_vm, "视觉模型地址:", "llm_vision_api_url_input", "http://127.0.0.1:11434")
        _rl(lg_vm, "视觉模型:", lambda r: (setattr(self,'llm_vision_model_input',QComboBox()), self.llm_vision_model_input.setEditable(True),
            self.llm_vision_model_input.setInsertPolicy(QComboBox.NoInsert),
            self.llm_vision_model_input.lineEdit().setPlaceholderText("启动 Ollama 后自动列出已下载模型"), r.addWidget(self.llm_vision_model_input)))
        rr_vm = QHBoxLayout(); rr_vm.addStretch()
        b_vm_test = mdi_button("测试连接", "search"); b_vm_test.setObjectName("secondary_button"); b_vm_test.setFixedWidth(110); b_vm_test.clicked.connect(self._test_vision_connection); rr_vm.addWidget(b_vm_test)
        b_vm_save = mdi_button("保存", "save"); b_vm_save.setObjectName("primary_button"); b_vm_save.setFixedWidth(90); b_vm_save.clicked.connect(self.save_llm_config); rr_vm.addWidget(b_vm_save)
        lg_vm.addLayout(rr_vm)
        self.vision_status_lbl = QLabel(""); lg_vm.addWidget(self.vision_status_lbl)
        l4.addWidget(g4)
        l4.addWidget(g_vm)

        l4.addStretch(); tabs.addTab(p4, "🖥️ Ollama")

        # ───── Tab 5: Whisper（纯远程 ASR 服务）─────
        p5 = _page(); l5 = QVBoxLayout(p5); l5.setContentsMargins(16,20,16,16); l5.setSpacing(10)
        g5 = QGroupBox("🎙️ Whisper 语音转写（远程 ASR 服务）"); g5.setObjectName("model_groupbox"); g5.setProperty("section", "whisper"); lg5 = QVBoxLayout(g5); lg5.setSpacing(10)
        whisper_desc = QLabel("工程已切换为纯远程 ASR 模式，语音转写由远程 Whisper 服务完成，无需本地模型。"); whisper_desc.setObjectName("muted_text"); whisper_desc.setWordWrap(True); lg5.addWidget(whisper_desc)
        _rl(lg5, "ASR 服务地址:", lambda r: (setattr(self,'whisper_api_url_input',QLineEdit()), self.whisper_api_url_input.setPlaceholderText("http://192.168.x.x:9000/asr"), r.addWidget(self.whisper_api_url_input)))
        lg5.addLayout(_row(lambda r: (setattr(self,'btn_test_whisper',mdi_button("测试连接", "search")), self.btn_test_whisper.setObjectName("secondary_button"), self.btn_test_whisper.setFixedWidth(110), self.btn_test_whisper.clicked.connect(self._test_whisper_connection),
            r.addWidget(self.btn_test_whisper),
            setattr(self,'btn_save_whisper',mdi_button("保存", "save")), self.btn_save_whisper.setObjectName("primary_button"), self.btn_save_whisper.setFixedWidth(90), self.btn_save_whisper.clicked.connect(self.save_llm_config), r.addWidget(self.btn_save_whisper), r.addStretch())))
        self.whisper_status_lbl = QLabel(""); self.whisper_status_lbl.setObjectName("muted_text"); lg5.addWidget(self.whisper_status_lbl)
        l5.addWidget(g5); l5.addStretch(); tabs.addTab(p5, "🎙️ Whisper")

        # ───── Tab 6: PaddleOCR ─────
        p6 = _page(); l6 = QVBoxLayout(p6); l6.setContentsMargins(16,20,16,16); l6.setSpacing(10)
        g6 = QGroupBox("🔍 PaddleOCR 文本识别"); g6.setObjectName("model_groupbox"); g6.setProperty("section", "ocr"); lg6 = QVBoxLayout(g6); lg6.setSpacing(10)
        _rl(lg6, "环境:", lambda r: (setattr(self,'llm_paddle_status_val',QLabel("正在检测...")), r.addWidget(self.llm_paddle_status_val)))
        _rl(lg6, "模型:", lambda r: (setattr(self,'llm_paddle_models_val',QLabel("正在检测...")), r.addWidget(self.llm_paddle_models_val)))
        setattr(self,'paddle_stage_label',QLabel("系统就绪")); self.paddle_stage_label.setObjectName("muted_text"); lg6.addWidget(self.paddle_stage_label)
        setattr(self,'paddle_progress_bar',QProgressBar()); self.paddle_progress_bar.setVisible(False); self.paddle_progress_bar.setRange(0,100); lg6.addWidget(self.paddle_progress_bar)
        lg6.addLayout(_row(lambda r: (setattr(self,'btn_refresh_paddle',mdi_button("刷新", "refresh")), self.btn_refresh_paddle.setObjectName("secondary_button"), self.btn_refresh_paddle.clicked.connect(self.refresh_llm_page_status),
            setattr(self,'btn_install_paddle',mdi_button("一键部署/修复", "rocket")), self.btn_install_paddle.setObjectName("primary_button"), self.btn_install_paddle.clicked.connect(self.start_paddle_repair),
            r.addWidget(self.btn_refresh_paddle), r.addWidget(self.btn_install_paddle), r.addStretch())))
        setattr(self,'paddle_log_view',QTextEdit()); self.paddle_log_view.setObjectName("log_viewer"); self.paddle_log_view.setReadOnly(True); self.paddle_log_view.setFixedHeight(100); self.paddle_log_view.setPlaceholderText("部署日志..."); lg6.addWidget(self.paddle_log_view)
        l6.addWidget(g6); l6.addStretch(); tabs.addTab(p6, "🔍 PaddleOCR")

        # ───── Tab 7: CLIP（远程 embedding 服务）─────
        p7 = _page(); l7 = QVBoxLayout(p7); l7.setContentsMargins(16,20,16,16); l7.setSpacing(10)
        g7 = QGroupBox("🖼️ CLIP 向量检索（远程 embedding 服务）"); g7.setObjectName("model_groupbox"); g7.setProperty("section", "clip"); lg7 = QVBoxLayout(g7); lg7.setSpacing(10)
        clip_desc = QLabel("向量检索的 CLIP embedding 已切换为纯远程模式，由远程 embedding 服务完成图文向量编码，无需本地模型。"); clip_desc.setObjectName("muted_text"); clip_desc.setWordWrap(True); lg7.addWidget(clip_desc)
        _rl(lg7, "CLIP API 地址:", lambda r: (setattr(self,'clip_api_url_input',QLineEdit()), self.clip_api_url_input.setPlaceholderText("http://192.168.x.x:8001"), r.addWidget(self.clip_api_url_input)))
        lg7.addLayout(_row(lambda r: (setattr(self,'btn_test_clip',mdi_button("测试连接", "search")), self.btn_test_clip.setObjectName("secondary_button"), self.btn_test_clip.setFixedWidth(110), self.btn_test_clip.clicked.connect(self._test_clip_connection),
            r.addWidget(self.btn_test_clip),
            setattr(self,'btn_save_clip',mdi_button("保存", "save")), self.btn_save_clip.setObjectName("primary_button"), self.btn_save_clip.setFixedWidth(90), self.btn_save_clip.clicked.connect(self.save_llm_config), r.addWidget(self.btn_save_clip), r.addStretch())))
        self.clip_status_lbl = QLabel(""); self.clip_status_lbl.setObjectName("muted_text"); lg7.addWidget(self.clip_status_lbl)
        l7.addWidget(g7); l7.addStretch(); tabs.addTab(p7, "🖼️ CLIP")

        layout.addWidget(tabs, 1)
        # Load data
        prov = self.ai_config.get("llm_provider","deepseek"); idx = self.llm_provider_combo.findData(prov)
        if idx>=0: self.llm_provider_combo.setCurrentIndex(idx)
        self.llm_api_url_input.setText(self.ai_config.get("llm_api_url","https://api.deepseek.com"))
        self.llm_api_key_input.setText(self.ai_config.get("llm_api_key",""))
        self.llm_model_input.setText(self.ai_config.get("llm_model","deepseek-v4-flash"))
        self.llm_vision_api_url_input.setText(self.ai_config.get("llm_vision_api_url","http://127.0.0.1:11434"))
        self.llm_vision_model_input.setCurrentText(self.ai_config.get("llm_vision_model",""))
        self.load_voxcpm_config()
        # Whisper ASR 地址初始化（纯远程模式）
        self.whisper_api_url_input.setText(self.ai_config.get("whisper_api_url", ""))
        # CLIP API 地址初始化（纯远程模式）
        self.clip_api_url_input.setText(self.ai_config.get("clip_api_url", ""))
        self.refresh_llm_page_status()

    # ═══════════════════════════════════════════════════════════════
    #  平台接入 — ComfyUI / RunningHub / 飞书 / 即梦
    # ═══════════════════════════════════════════════════════════════
    def setup_llm_settings_page(self):
        layout = QVBoxLayout(self.page_llm_settings)
        layout.setContentsMargins(20, 20, 20, 20)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; QWidget { background: transparent; } } QTabBar::tab { padding: 8px 18px; font-size: 13px; } QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")

        def _inp(lbl, attr, ph, parent_layout, echo=None):
            r = QHBoxLayout(); r.addWidget(QLabel(lbl))
            e = QLineEdit(); e.setPlaceholderText(ph); setattr(self, attr, e)
            if echo: e.setEchoMode(echo)
            r.addWidget(e); r.addStretch(); parent_layout.addLayout(r)

        # ── Tab 1: ComfyUI ──
        p1 = QWidget(); l1 = QVBoxLayout(p1); l1.setContentsMargins(30,30,30,30)
        l1.addWidget(QLabel("ComfyUI 服务地址（留空则使用工程自带的本地 ComfyUI）:"))
        self.comfyui_input = QLineEdit(); self.comfyui_input.setPlaceholderText("留空=本地 127.0.0.1:8188；或填外部如 http://192.168.111.36:8188")
        self.comfyui_input.setText(self.ai_config.get("comfyui_addr","http://192.168.111.36:8188")); l1.addWidget(self.comfyui_input)
        self.comfyui_local_status = QLabel(); self.comfyui_local_status.setObjectName("comfyui_local_status"); l1.addWidget(self.comfyui_local_status)
        try: self.refresh_comfyui_local_status()
        except Exception: pass
        self.btn_open_comfyui_editor = QPushButton("🎨 打开 ComfyUI 节点编辑器（调试工作流）"); self.btn_open_comfyui_editor.clicked.connect(self.open_comfyui_editor); l1.addWidget(self.btn_open_comfyui_editor)
        r1 = QHBoxLayout(); r1.addStretch()
        b_save_comfy = mdi_button("保存 ComfyUI 配置", "save"); b_save_comfy.setObjectName("primary_button"); b_save_comfy.clicked.connect(self.save_ai_config); r1.addWidget(b_save_comfy)
        l1.addLayout(r1)
        l1.addStretch(); tabs.addTab(p1, "🎨 ComfyUI")

        # ── Tab 2: 飞书 ──
        p3 = QWidget(); l3 = QVBoxLayout(p3); l3.setContentsMargins(30,30,30,30)
        _inp("App ID:", "edit_feishu_appid", "cli_xxxxxxxxxxxxxxx", l3)
        _inp("App Secret:", "edit_feishu_appsecret", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", l3, echo=QLineEdit.Password)
        _inp("多维表格 App Token:", "edit_feishu_apptoken", "bascnxxxxxxxxxxxxxxxxxxxxxx", l3)
        _inp("数据表 Table ID:", "edit_feishu_tableid", "tblxxxxxxxxxxxxxx", l3)
        _inp("选题列名称:", "edit_feishu_topicfield", "默认: 选题", l3)
        _inp("脚本列名称:", "edit_feishu_scriptfield", "默认: 脚本", l3)
        _inp("文档保存文件夹 Token:", "edit_feishu_foldertoken", "fldcnxxxxxxxxxxxxxxxxxxxxxx (选填)", l3)
        self.edit_feishu_topicfield.setText("选题")
        self.edit_feishu_scriptfield.setText("脚本")
        r3 = QHBoxLayout(); r3.addStretch()
        b3 = mdi_button("保存飞书配置", "save"); b3.setObjectName("primary_button"); b3.clicked.connect(self.save_feishu_config); r3.addWidget(b3)
        b4 = mdi_button("测试连接", "link"); b4.setObjectName("secondary_button"); b4.clicked.connect(self._test_feishu); r3.addWidget(b4)
        l3.addLayout(r3)
        self.fs_test_status = QLabel(""); self.fs_test_status.setObjectName("muted_text"); l3.addWidget(self.fs_test_status)
        l3.addStretch(); tabs.addTab(p3, "📝 飞书")

        # ── Tab 4: 即梦 ──
        p4 = QWidget(); l4 = QVBoxLayout(p4); l4.setContentsMargins(30,30,30,30)
        l4.addWidget(QLabel("即梦 (Dreamina) AI 图片生成"))
        l4.addWidget(QLabel(f"输出目录: {DREAMINA_OUTPUT_DIR}"))
        has = "✅ 已就位" if os.path.isfile(DREAMINA_EXE) else f"❌ 未找到 ({DREAMINA_EXE})"
        l4.addWidget(QLabel(f"引擎: {has}"))
        self.dr_status = QLabel(""); self.dr_status.setObjectName("muted_text"); l4.addWidget(self.dr_status)
        r4 = QHBoxLayout()
        b_login = QPushButton("🔑 登录"); b_login.setObjectName("primary_button"); b_login.clicked.connect(self._dreamina_login); r4.addWidget(b_login)
        b_check = mdi_button("检测状态", "link"); b_check.setObjectName("secondary_button"); b_check.clicked.connect(self._dreamina_check); r4.addWidget(b_check)
        r4.addStretch(); l4.addLayout(r4)
        l4.addStretch(); tabs.addTab(p4, "🌈 即梦")

        # ── Tab 5: 旺店通 ERP ──
        p5 = QWidget(); l5 = QVBoxLayout(p5); l5.setContentsMargins(30,30,30,30)
        l5.addWidget(QLabel("旺店通 ERP 配置。产品资料从仓库同步时使用，留空则不启用。"))
        l5.addSpacing(10)
        _inp("API 地址:", "erp_url_input", "https://api.wangdian.cn/openapi2/", l5)
        _inp("AppKey:", "erp_appkey_input", "旺店通 appkey", l5)
        _inp("AppSecret:", "erp_appsecret_input", "旺店通 appsecret", l5, echo=QLineEdit.Password)
        _inp("SID:", "erp_sid_input", "旺店通商家编码", l5)
        r5 = QHBoxLayout(); r5.addStretch()
        b_save_erp = mdi_button("保存配置", "save"); b_save_erp.setObjectName("primary_button")
        b_save_erp.clicked.connect(self._save_erp_platform_cfg)
        r5.addWidget(b_save_erp)
        self.lbl_erp_status = QLabel(""); self.lbl_erp_status.setObjectName("muted_text"); r5.addWidget(self.lbl_erp_status)
        r5.addStretch(); l5.addLayout(r5)
        l5.addStretch(); tabs.addTab(p5, "🏪 旺店通")

        layout.addWidget(tabs, 1)
        # Load feishu config
        self.load_feishu_config()
        # Load ERP config
        try: self.load_erp_platform_cfg()
        except Exception: pass

    def setup_digital_human_page(self):
            layout = QVBoxLayout(self.page_digital_human)
            layout.setContentsMargins(40, 40, 40, 40)
        
            heading = QLabel("数字人克隆生成")
            heading.setObjectName("heading")
            layout.addWidget(heading)
        
            card = QFrame()
            card.setObjectName("card")
            config_layout = QVBoxLayout(card)
            config_layout.setContentsMargins(30, 30, 30, 30)
        
	        # Backend Selection
            config_layout.addWidget(QLabel("生成后端:"))
            self.backend_label = QLabel("ComfyUI (本地/局域网)")
            self.backend_label.setObjectName("muted_text")
            config_layout.addWidget(self.backend_label)
        
            config_layout.addSpacing(15)

            # --- ComfyUI Section ---
            self.comfy_section = QWidget()
            comfy_layout = QVBoxLayout(self.comfy_section)
            comfy_layout.setContentsMargins(0, 0, 0, 0)
        
            self.workflow_status = QLabel("正在自动加载工作流...")
            comfy_layout.addWidget(self.workflow_status)
        
            comfy_layout.addSpacing(15)
        
            # Image Input (Only for ComfyUI)
            comfy_layout.addWidget(QLabel("人物图片:"))
            img_row = QHBoxLayout()
            self.img_path_input = QLineEdit()
            self.img_path_input.setPlaceholderText("请选择图片...")
            img_row.addWidget(self.img_path_input)
            btn_sel_img = QPushButton("浏览")
            btn_sel_img.clicked.connect(self.select_image)
            img_row.addWidget(btn_sel_img)
            comfy_layout.addLayout(img_row)
        
            # Audio Input (Only for ComfyUI)
            comfy_layout.addWidget(QLabel("驱动语音:"))
            aud_row = QHBoxLayout()
            self.aud_path_input = QLineEdit()
            self.aud_path_input.setPlaceholderText("请选择音频...")
            aud_row.addWidget(self.aud_path_input)
            btn_sel_aud = QPushButton("浏览")
            btn_sel_aud.clicked.connect(self.select_audio)
            aud_row.addWidget(btn_sel_aud)
            comfy_layout.addLayout(aud_row)
        
            self.btn_run_local = mdi_button("提交本地生成任务", "rocket")
            self.btn_run_local.setObjectName("action_button")
            self.btn_run_local.setEnabled(False)
            self.btn_run_local.setFixedHeight(50)
            self.btn_run_local.clicked.connect(self.run_comfyui_task)
            comfy_layout.addSpacing(20)
            comfy_layout.addWidget(self.btn_run_local)
        
            config_layout.addWidget(self.comfy_section)

            layout.addWidget(card)
            layout.addStretch()
        
            self.current_workflow_data = None
            # Auto-load default workflow for Digital Human
            QTimer.singleShot(500, self.auto_load_default_dh_workflow)

    def setup_task_list_page(self):
            layout = QVBoxLayout(self.page_task_list)
            layout.setContentsMargins(30, 30, 30, 30)
        
            # --- Top: Monitoring Section ---
            mon_card = QFrame()
            mon_card.setObjectName("card")
            mon_card.setFixedHeight(80)
            mon_layout = QHBoxLayout(mon_card)
            mon_layout.addWidget(QLabel("📊 系统资源:"))
            self.cpu_label = QLabel("CPU: --%")
            self.ram_label = QLabel("内存: --%")
            self.gpu_label = QLabel("显存: --")
            for lbl in [self.cpu_label, self.ram_label, self.gpu_label]:
                lbl.setStyleSheet("font-weight: bold; color: #3498db; margin-right: 20px;")
                mon_layout.addWidget(lbl)
            mon_layout.addStretch()
            layout.addWidget(mon_card)
        
            # --- Task List ---
            task_card = QFrame()
            task_card.setObjectName("card")
            task_layout = QVBoxLayout(task_card)
        
            header = QHBoxLayout()
            header.addWidget(QLabel("📋 任务队列"))
            self.lbl_task_status = QLabel("")
            self.lbl_task_status.setObjectName("muted_text")
            header.addWidget(self.lbl_task_status, 1)
            btn_sync = mdi_button("同步服务端", "refresh")
            btn_sync.setFixedWidth(100)
            btn_sync.clicked.connect(self._sync_server_tasks)
            header.addWidget(btn_sync)
            btn_clear = mdi_button("清除已完成", "close")
            btn_clear.setFixedWidth(100)
            btn_clear.clicked.connect(self._clear_done_tasks)
            header.addWidget(btn_clear)
            header.addStretch()
            task_layout.addLayout(header)
        
            self.task_table = QTableWidget(0, 7)
            self.task_table.setHorizontalHeaderLabels(["任务 ID", "任务类型", "来源", "状态", "进度", "时间", "操作"])
            self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
            self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
            self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
            self.task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
            self.task_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            self.task_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
            self.task_table.setColumnWidth(0, 180)
            self.task_table.setColumnWidth(1, 120)
            self.task_table.setColumnWidth(3, 120)
            self.task_table.setColumnWidth(5, 140)
            self.task_table.setColumnWidth(6, 100)
            self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            task_layout.addWidget(self.task_table)
        
            layout.addWidget(task_card, 1)
    
    def _sync_server_tasks_async(self):
        """异步版本：把 HTTP 请求放到 Worker 线程，不阻塞界面。"""
        from utils.thread_worker import TaskWorker as Worker

        def _do_sync():
            self._sync_server_tasks()
            return None

        w = Worker(_do_sync)
        w.start()

    def _sync_server_tasks(self):
        """从服务端 GET /tasks 拉取本机任务列表并入表格。"""
        import requests as _req
        import socket as _socket
        try:
            from config.paths import AI_CONFIG_FILE
            import json as _json
            base_url = "http://192.168.111.18:8000"
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r") as f:
                    cfg = _json.load(f)
                url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
                if url:
                    base_url = url
            resp = _req.get(f"{base_url}/tasks", timeout=10)
            if resp.status_code != 200:
                return
            tasks = resp.json()
            if not isinstance(tasks, list):
                return

            # 获取本机 IP
            local_ip = ""
            try:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                s.connect((base_url.replace("http://","").replace("https://","").split(":")[0], 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                pass

            # 已存在的任务 ID 集合
            existing = set()
            for row in range(self.task_table.rowCount()):
                item = self.task_table.item(row, 0)
                if item:
                    existing.add(item.text())

            added = 0
            filtered = 0
            for t in tasks:
                # 只显示本机 IP 的任务
                task_ip = (t.get("client_ip") or "").strip()
                if local_ip and task_ip and task_ip != local_ip:
                    filtered += 1
                    continue

                tid = (t.get("id") or "")[:12]
                if not tid or tid in existing:
                    continue
                # 格式化时间
                created_ts = t.get("created_at") or t.get("started_at") or 0
                if created_ts:
                    import datetime as _dt
                    time_str = _dt.datetime.fromtimestamp(created_ts).strftime("%m-%d %H:%M")
                else:
                    time_str = ""
                row = self.task_table.rowCount()
                self.task_table.insertRow(row)
                self.task_table.setItem(row, 0, QTableWidgetItem(tid))
                self.task_table.setItem(row, 1, QTableWidgetItem(t.get("type", "未知")))
                source_item = QTableWidgetItem("服务端")
                source_item.setForeground(QColor("#60a5fa"))
                self.task_table.setItem(row, 2, source_item)
                status = t.get("status", "unknown")
                status_map = {"completed": "✅ 完成", "processing": "⏳ 处理中", "pending": "⏳ 排队中", "failed": "❌ 失败", "error": "❌ 错误"}
                self.task_table.setItem(row, 3, QTableWidgetItem(status_map.get(status, status)))
                p_bar = QProgressBar()
                p_bar.setValue(t.get("progress", 0) if status == "processing" else (100 if status == "completed" else 0))
                p_bar.setTextVisible(True)
                self.task_table.setCellWidget(row, 4, p_bar)
                self.task_table.setItem(row, 5, QTableWidgetItem(time_str))
                self.task_table.setCellWidget(row, 6, QWidget())
                existing.add(tid)
                added += 1

            if added > 0:
                self.lbl_task_status.setText(f"✅ 已同步 {added} 条本机任务")
            elif filtered > 0:
                self.lbl_task_status.setText(f"💡 服务端有 {filtered} 条其他客户端的任务已过滤")
        except Exception as e:
            print(f"同步服务端任务失败: {e}")
    
    def _clear_done_tasks(self):
        """清除所有已完成/失败的任务行。"""
        for row in range(self.task_table.rowCount() - 1, -1, -1):
            status_text = self.task_table.item(row, 3).text() if self.task_table.item(row, 3) else ""
            if "完成" in status_text or "失败" in status_text or "错误" in status_text:
                self.task_table.removeRow(row)

    def setup_accounts_page(self):
            layout = QVBoxLayout(self.page_accounts)
            layout.setContentsMargins(40, 40, 40, 40)
        
            header = QHBoxLayout()
            heading = QLabel("抖音账户管理")
            heading.setObjectName("heading")
            header.addWidget(heading)
        
            btn_add = mdi_button("添加新账户", "plus")
            btn_add.setObjectName("primary_button")
            btn_add.setFixedWidth(150)
            btn_add.clicked.connect(self.trigger_add_account)
            header.addWidget(btn_add)
            header.addStretch()
            layout.addLayout(header)
        
            # Grid layout for accounts
            self.accounts_grid_container = QWidget()
            self.accounts_grid = QGridLayout(self.accounts_grid_container)
            self.accounts_grid.setSpacing(20)
        
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.accounts_grid_container)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            layout.addWidget(scroll, 1)

    def setup_account_detail_page(self):
            layout = QVBoxLayout(self.page_account_detail)
            layout.setContentsMargins(40, 40, 40, 40)
        
            header = QHBoxLayout()
            self.detail_back_btn = mdi_button("返回列表", "left")
            self.detail_back_btn.clicked.connect(lambda: self.switch_page(8))
            header.addWidget(self.detail_back_btn)
        
            self.detail_title = QLabel("账户详情")
            self.detail_title.setObjectName("heading")
            header.addWidget(self.detail_title)
            header.addStretch()
        
            self.detail_refresh_btn = mdi_button("刷新数据", "refresh")
            self.detail_refresh_btn.setFixedWidth(120)
            self.detail_refresh_btn.clicked.connect(lambda: self.refresh_account_videos(self.current_selected_account))
            header.addWidget(self.detail_refresh_btn)
        
            layout.addLayout(header)
        
            info_card = QFrame()
            info_card.setObjectName("card")
            info_card.setFixedHeight(100)
            info_layout = QHBoxLayout(info_card)
            # Avatar and basic info
            self.detail_avatar = QLabel()
            self.detail_avatar.setFixedSize(80, 80)
            self.detail_avatar.setStyleSheet("background-color: #f0f2f5; border-radius: 40px; border: 3px solid #fff;")
            info_layout.addWidget(self.detail_avatar)
        
            text_info = QVBoxLayout()
            self.detail_nickname = QLabel("正在加载...")
            self.detail_nickname.setObjectName("card_title")
            text_info.addWidget(self.detail_nickname)
        
            self.detail_uid = QLabel("UID: --")
            self.detail_uid.setStyleSheet("color: #7f8c8d; font-size: 13px;")
            text_info.addWidget(self.detail_uid)
        
            info_layout.addLayout(text_info)
            info_layout.addStretch()
            layout.addWidget(info_card)
        
            layout.addSpacing(20)
            layout.addWidget(QLabel("发布视频清单:"))
        
            self.account_videos_table = QTableWidget(0, 5)
            self.account_videos_table.setHorizontalHeaderLabels(["视频标题", "发布日期", "播放量", "点赞量", "评论量"])
            self.account_videos_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            layout.addWidget(self.account_videos_table, 1)

    def setup_logs_page(self):
        layout = QVBoxLayout(self.page_logs)
        layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(0)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; QWidget { background: transparent; } } QTabBar::tab { padding: 8px 18px; font-size: 13px; } QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")

        # Tab 1: 日志
        p1 = QWidget(); p1.setStyleSheet("QWidget { background: transparent; }")
        l1 = QVBoxLayout(p1); l1.setContentsMargins(16,16,16,16)
        frow = QHBoxLayout(); l1.addLayout(frow)
        b = mdi_button("刷新", "refresh"); b.setObjectName("primary_button"); b.setFixedWidth(90); b.clicked.connect(self.refresh_logs); frow.addWidget(b)
        frow.addWidget(QLabel("  级别:"))
        self.log_level_filter = QComboBox()
        self.log_level_filter.addItems(["全部", "INFO", "WARNING", "ERROR", "DEBUG"])
        self.log_level_filter.currentIndexChanged.connect(self.refresh_logs)
        frow.addWidget(self.log_level_filter)
        frow.addWidget(QLabel("关键词:"))
        self.log_keyword_input = QLineEdit()
        self.log_keyword_input.setPlaceholderText("输入关键词过滤，如 [ASR]")
        self.log_keyword_input.setMinimumWidth(160)
        self.log_keyword_input.returnPressed.connect(self.refresh_logs)
        frow.addWidget(self.log_keyword_input)
        self.btn_server_log = mdi_button("服务端", "server")
        self.btn_server_log.setObjectName("secondary_button")
        self.btn_server_log.setCheckable(True)
        self.btn_server_log.setChecked(False)
        self.btn_server_log.clicked.connect(self.refresh_logs)
        frow.addWidget(self.btn_server_log)
        frow.addStretch()
        self.log_viewer = QTextEdit(); self.log_viewer.setReadOnly(True); self.log_viewer.setObjectName("log_viewer"); l1.addWidget(self.log_viewer, 1)
        l1.addWidget(QLabel("完整日志: .runtime/logs/app.log"))
        tabs.addTab(p1, "📊 日志")

        # Tab 2: 系统信息
        p2 = QWidget(); p2.setStyleSheet("QWidget { background: transparent; }")
        l2 = QVBoxLayout(p2); l2.setContentsMargins(30,30,30,30); l2.setSpacing(12)
        l2.addWidget(QLabel("系统硬件信息")); l2.addWidget(self._info_row("操作系统:", "os_ver"))
        l2.addWidget(self._info_row("处理器:", "cpu_info"))
        l2.addWidget(self._info_row("内存:", "ram_info"))
        l2.addWidget(self._info_row("显卡:", "gpu_info"))
        l2.addWidget(self._info_row("Python:", "python_ver"))
        l2.addWidget(self._info_row("PyTorch:", "torch_ver"))
        l2.addWidget(self._info_row("CUDA:", "cuda_info"))
        l2.addStretch()
        QTimer.singleShot(200, self._refresh_help_sysinfo)
        tabs.addTab(p2, "🖥️ 系统信息")

        # Tab 3: 关于与版本
        p3 = QWidget(); p3.setStyleSheet("QWidget { background: transparent; }")
        l3 = QVBoxLayout(p3); l3.setContentsMargins(30, 20, 30, 20); l3.setSpacing(14)

        # Brand / Developer Info Card
        brand_card = QFrame()
        brand_card.setObjectName("brand_card")
        brand_card.setStyleSheet("""
            #brand_card {
                background-color: #1a1a24;
                border: 1px solid #2e2e38;
                border-radius: 12px;
            }
        """)
        brand_layout = QVBoxLayout(brand_card)
        brand_layout.setContentsMargins(20, 20, 20, 20)
        brand_layout.setSpacing(10)

        app_title = QLabel("🔩 螺丝钉-电商智能体矩阵")
        app_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        brand_layout.addWidget(app_title)

        dev_info = QLabel("此智能体由 <b>大怪工作室</b> 开发")
        dev_info.setStyleSheet("font-size: 13px; color: #a1a1aa;")
        brand_layout.addWidget(dev_info)

        contact_info = QLabel("📞 联系电话：<span style='color: #3b82f6; font-weight: bold;'>17361907260</span>（微信同号）")
        contact_info.setStyleSheet("font-size: 13px; color: #e4e4e7;")
        brand_layout.addWidget(contact_info)
        
        l3.addWidget(brand_card)

        # Get machine code and license signature info
        from utils.license import get_machine_id
        machine_id = get_machine_id()
        
        license_status = "已激活 (客户端免激活)"
        licensee_name = "服务端统一授权验证"
        expiry_date = "自适应计算服务端授权状态"

        # License Info Card
        license_card = QFrame()
        license_card.setObjectName("license_card")
        license_card.setStyleSheet("""
            #license_card {
                background-color: #1a1a24;
                border: 1px solid #2e2e38;
                border-radius: 12px;
            }
        """)
        license_layout = QVBoxLayout(license_card)
        license_layout.setContentsMargins(20, 16, 20, 16)
        license_layout.setSpacing(10)

        license_title = QLabel("🔑 软件授权与激活")
        license_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #10b981; margin-bottom: 4px;")
        license_layout.addWidget(license_title)

        # Machine ID Row with Copy button
        mac_row = QHBoxLayout()
        mac_row.setContentsMargins(0, 0, 0, 0)
        mac_lbl = QLabel("本机机器码:")
        mac_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        mac_val = QLineEdit(machine_id)
        mac_val.setReadOnly(True)
        mac_val.setStyleSheet("color: #3b82f6; font-size: 12px; font-family: monospace; background: #15151e; border: 1px solid #2e2e38; border-radius: 4px; padding: 2px 6px;")
        
        btn_copy = QPushButton("📋 复制机器码")
        btn_copy.setFixedWidth(100)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #ffffff;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                font-size: 11px;
                padding: 3px 6px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
                border-color: #3b82f6;
            }
        """)
        
        def copy_mac():
            QApplication.clipboard().setText(machine_id)
            QMessageBox.information(self, "复制成功", "机器码已成功复制到剪贴板！")
            
        btn_copy.clicked.connect(copy_mac)
        
        mac_row.addWidget(mac_lbl)
        mac_row.addWidget(mac_val, 1)
        mac_row.addWidget(btn_copy)
        license_layout.addLayout(mac_row)

        # License status row
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_lbl = QLabel("授权状态:")
        status_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        
        status_val = QLabel(license_status)
        if "已激活" in license_status:
            status_val.setStyleSheet("color: #10b981; font-size: 12px; font-weight: bold;")
        else:
            status_val.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: bold;")
            
        status_row.addWidget(status_lbl)
        status_row.addWidget(status_val, 1)
        license_layout.addLayout(status_row)

        # Licensee row
        licensee_row = QHBoxLayout()
        licensee_row.setContentsMargins(0, 0, 0, 0)
        licensee_lbl = QLabel("激活签名:")
        licensee_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        licensee_val = QLabel(licensee_name)
        licensee_val.setStyleSheet("color: #d1d1d6; font-size: 12px;")
        licensee_row.addWidget(licensee_lbl)
        licensee_row.addWidget(licensee_val, 1)
        license_layout.addLayout(licensee_row)

        # Expiration row
        expire_row = QHBoxLayout()
        expire_row.setContentsMargins(0, 0, 0, 0)
        expire_lbl = QLabel("有效期至:")
        expire_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        expire_val = QLabel(expiry_date)
        expire_val.setStyleSheet("color: #d1d1d6; font-size: 12px;")
        expire_row.addWidget(expire_lbl)
        expire_row.addWidget(expire_val, 1)
        license_layout.addLayout(expire_row)

        l3.addWidget(license_card)

        # System & Version Info Card
        version_card = QFrame()
        version_card.setObjectName("version_card")
        version_card.setStyleSheet("""
            #version_card {
                background-color: #15151e;
                border: 1px solid #26262e;
                border-radius: 10px;
            }
        """)
        version_layout = QVBoxLayout(version_card)
        version_layout.setContentsMargins(20, 16, 20, 16)
        version_layout.setSpacing(8)

        version_title = QLabel("📋 系统与版本信息")
        version_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #3b82f6; margin-bottom: 4px;")
        version_layout.addWidget(version_title)

        import sys as _s, platform as _p
        def add_version_row(label, val):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
            v_val = QLabel(val)
            v_val.setStyleSheet("color: #d1d1d6; font-size: 12px;")
            v_val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(v_val, 1)
            version_layout.addLayout(row)

        add_version_row("应用版本:", "v2.0.0 RC")
        add_version_row("Python 版本:", _s.version)
        add_version_row("运行系统:", f"{_p.system()} {_p.release()} ({_p.version()})")
        
        try:
            from PySide6 import __version__ as _v
            add_version_row("PySide6 版本:", _v)
        except Exception:
            pass
            
        add_version_row("工作目录:", WORKSPACE_ROOT)
        
        l3.addWidget(version_card)
        l3.addStretch()
        tabs.addTab(p3, "ℹ️ 关于")

        # Tab 4: 外观主题
        p4 = QWidget(); l4 = QVBoxLayout(p4); l4.setContentsMargins(30, 30, 30, 30)
        l4.addWidget(QLabel("🎨 界面主题"))
        l4.addWidget(QLabel("选择应用程序的外观配色方案："))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("🌓 跟随系统", "system")
        self.theme_combo.addItem("🌙 暗黑主题", "dark")
        self.theme_combo.addItem("☀️ 炫白主题", "light")
        self.theme_combo.setFixedWidth(200)
        from utils.theme_manager import get_saved_theme
        current = get_saved_theme()
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        l4.addWidget(self.theme_combo)
        l4.addSpacing(10)
        self.theme_hint = QLabel("主题将在下次启动应用时完全生效（部分窗口可能需要重启）。")
        self.theme_hint.setObjectName("muted_text")
        self.theme_hint.setWordWrap(True)
        l4.addWidget(self.theme_hint)
        l4.addStretch()
        tabs.addTab(p4, "🎨 外观")

        layout.addWidget(tabs, 1)

    def _info_row(self, label, key):
        w = QLabel(f"{label} 检测中..."); w.setObjectName(key); w.setStyleSheet("font-size:14px;"); return w

    def _refresh_help_sysinfo(self):
        import platform as _p
        for w in self.page_logs.findChildren(QLabel):
            if w.objectName() == "os_ver":
                w.setText(f"操作系统: {_p.system()} {_p.release()} ({_p.version()})")
            if w.objectName() == "cpu_info":
                w.setText(f"处理器: {_p.processor() or '检测中...'}")
            if w.objectName() == "ram_info":
                try:
                    import psutil; m = psutil.virtual_memory()
                    w.setText(f"内存: {m.total//(1024**3)} GB (可用 {m.available//(1024**3)} GB)")
                except Exception:
                    w.setText("内存: 检测中...")
            if w.objectName() == "gpu_info":
                try:
                    import subprocess, sys
                    r = subprocess.run(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    w.setText(f"显卡: {r.stdout.strip()}")
                except Exception:
                    w.setText("显卡: 检测中...")
            if w.objectName() == "python_ver":
                w.setText(f"Python: {_p.python_version()}")
            if w.objectName() == "torch_ver":
                try: import torch; w.setText(f"PyTorch: {torch.__version__} (CUDA: {torch.cuda.is_available()})")
                except Exception: w.setText("PyTorch: 未安装")
            if w.objectName() == "cuda_info":
                try: import torch; w.setText(f"CUDA: {'可用' if torch.cuda.is_available() else '不可用'}")
                except Exception: w.setText("CUDA: 未检测")

    def setup_backup_page(self):
        layout = QVBoxLayout(self.page_backup)
        layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(0)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; QWidget { background: transparent; } } QTabBar::tab { padding: 8px 18px; font-size: 13px; } QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")

        p1 = QWidget(); p1.setStyleSheet("QWidget { background: transparent; }")
        from gui.env_config_page import EnvConfigPage
        self.env_config_tool = EnvConfigPage(p1, self); self.env_config_tool.setup()
        tabs.addTab(p1, "🖥️ 运行环境")

        p2 = QWidget(); p2.setStyleSheet("QWidget { background: transparent; }")
        from gui.terminal_page import TerminalPage
        self.terminal_tool = TerminalPage(p2, self); self.terminal_tool.setup()
        tabs.addTab(p2, "💻 终端")

        p3 = QWidget(); p3.setStyleSheet("QWidget { background: transparent; }")
        from gui.backup_page import BackupPage
        self.backup_tool = BackupPage(p3, self); self.backup_tool.setup()
        tabs.addTab(p3, "💾 备份管理")

        layout.addWidget(tabs, 1)

    # ── 素材资源配置 ──
