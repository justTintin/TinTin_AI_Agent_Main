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
from version import __app_name__, get_version
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
from PySide6.QtWidgets import (QTextBrowser,QApplication, QMainWindow, QWidget, QVBoxLayout,
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


from utils.file_dialog_utils import pick_directory, pick_file
class PageSetupMixin:
    def _register_lazy_page(self, index, setup_method):
        """登记懒加载页面：首次切换到该页时才调用 setup_method 构建。

        页面容器（self.page_xxx = QWidget()）仍在 setup_ui 阶段创建并加入
        content_stack，保证栈索引与侧边栏一致；只是把耗时的页面构建推迟到
        用户真正进入该页时执行，缩短启动时间。
        """
        if not hasattr(self, "_lazy_pages"):
            self._lazy_pages = {}
        self._lazy_pages[index] = setup_method

    def _ensure_page_built(self, index):
        """确保 index 对应的懒加载页面已构建（只构建一次）。"""
        setup_method = getattr(self, "_lazy_pages", {}).pop(index, None)
        if setup_method is None:
            return
        try:
            setup_method()
        except Exception as e:
            log.error(f"[页面懒加载] index={index} 构建失败: {e}")

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

        # Tab 1: 声音样本
        p1 = QWidget(); p1.setObjectName("tab_page")
        from gui.voice_samples_page import VoiceSamplesPage
        self.voice_samples_tool = VoiceSamplesPage(p1, self); self.voice_samples_tool.setup()
        tabs.addTab(p1, "🎭 声音样本")

        # Tab 2: 视频配置（LUT 还原）
        p2 = QWidget(); p2.setObjectName("tab_page")
        self._setup_video_config_tab(p2)
        tabs.addTab(p2, "🎬 视频配置")

        # Tab 3: 本地配置（缓存目录）
        p3 = QWidget(); p3.setObjectName("tab_page")
        self._setup_local_config_tab(p3)
        tabs.addTab(p3, "📁 本地配置")

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
        layout = QVBoxLayout(self.page_dreamina)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)
        tabs = QTabWidget()

        # Tab 1: 即梦生成
        from gui.dreamina_page import DreaminaPage
        p1 = QWidget(); p1.setObjectName("tab_page")
        self.dreamina_tool = DreaminaPage(p1, self); self.dreamina_tool.setup()
        tabs.addTab(p1, "🎨 即梦生成")

        # Tab 2: 产品生图
        from gui.product_image_page import ProductImagePage
        p2 = QWidget(); p2.setObjectName("tab_page")
        self.product_image_tool = ProductImagePage(p2, self); self.product_image_tool.setup()
        tabs.addTab(p2, "🆕 产品生图")

        # Tab 3: 数字人
        p3 = QWidget(); p3.setObjectName("tab_page")
        self._build_digital_human_tab(p3)
        tabs.addTab(p3, "🤖 数字人")

        # Tab 4: MG 动画
        p4 = QWidget(); p4.setObjectName("tab_page")
        from gui.mg_animation_page import MGAnimationPage
        self.mg_animation_tool = MGAnimationPage(p4, self)
        self.mg_animation_tool.setup()
        tabs.addTab(p4, "🪄 MG 动画")

        layout.addWidget(tabs)

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

    def setup_scheduled_tasks_page(self):
        from gui.scheduled_tasks_page import ScheduledTasksPage
        self.scheduled_tasks_tool = ScheduledTasksPage(self.page_scheduled_tasks, self)
        self.scheduled_tasks_tool.setup()

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

    def setup_extension_page(self):
        from gui.extension_page import ExtensionPage
        self.extension_tool = ExtensionPage(self.page_extension, self)
        self.extension_tool.setup()

    def setup_audio_material_page(self):
        from gui.audio_material_page import AudioMaterialPage
        self.audio_material_tool = AudioMaterialPage(self.page_audio_material, self)
        self.audio_material_tool.setup()


    def setup_media_tools_page(self):
        from gui.media_tools_page import MediaToolsPage
        self.media_tools_tool = MediaToolsPage(self.page_media_tools, self)
        self.media_tools_tool.setup()

    def setup_video_tools_page(self, container=None):
        """构建「视频修复」UI。container 缺省为目标页面容器；媒体工具标签页可传入标签容器。"""
        container = container or getattr(self, "page_video_tools", None)
        if container is None:
            return
        layout = QVBoxLayout(container)
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
        btn_sel_video = mdi_button("浏览", "folder")
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

            self.cg_status_label = QLabel("")
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

        # ── 统一服务端地址（各Tab独立API地址可基于此派生或单独填写）──
        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        server_lbl = QLabel("🌐 服务端地址（统一配置）:")
        server_lbl.setObjectName("muted_text")
        server_row.addWidget(server_lbl)
        self.compute_server_input = QLineEdit()
        self.compute_server_input.setPlaceholderText("http://<服务器IP>:8000（统一计算节点地址）")
        self.compute_server_input.textChanged.connect(self._on_server_url_changed)
        server_row.addWidget(self.compute_server_input, 1)
        self.btn_save_server = mdi_button("保存全部", "save")
        self.btn_save_server.setObjectName("primary_button")
        self.btn_save_server.setFixedWidth(100)
        self.btn_save_server.clicked.connect(self._save_all_ai_config)
        server_row.addWidget(self.btn_save_server)
        layout.addLayout(server_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setObjectName("scroll_page")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)

        def _rl(l, p, w): r = QHBoxLayout(); r.addWidget(QLabel(p)); w(r); r.addStretch(); l.addLayout(r)
        def _row(w): r = QHBoxLayout(); w(r); return r
        def _inp(l, p, a, ph): e = QLineEdit(); e.setPlaceholderText(ph); setattr(self,a,e); _rl(l, p, lambda r: r.addWidget(e))
        # ───── LLM ─────
        g1 = QGroupBox("🤖 LLM 大语言模型"); g1.setObjectName("model_groupbox"); g1.setProperty("section", "llm"); lg1 = QVBoxLayout(g1); lg1.setSpacing(10)
        _rl(lg1, "提供商:", lambda r: (setattr(self,'llm_provider_combo',QComboBox()), self.llm_provider_combo.setView(QListView()),
            self.llm_provider_combo.addItem("DeepSeek (推荐)","deepseek"),
            self.llm_provider_combo.addItem("OpenAI 兼容接口","openai"),
            self.llm_provider_combo.addItem("Ollama 本地","ollama"),
            self.llm_provider_combo.addItem("阿里云 DashScope","dashscope"),
            self.llm_provider_combo.addItem("智谱 GLM","zhipu"),
            self.llm_provider_combo.addItem("Moonshot (Kimi)","moonshot"),
            self.llm_provider_combo.addItem("自定义","custom"),
            self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed), r.addWidget(self.llm_provider_combo)))
        _inp(lg1, "API 地址:", "llm_api_url_input", "https://api.deepseek.com")
        # API Key 已隐藏，保留属性避免保存/测试代码崩溃
        self.llm_api_key_input = QLineEdit(); self.llm_api_key_input.setVisible(False)
        _inp(lg1, "文本模型:", "llm_model_input", "deepseek-v4-flash")
        rr1 = QHBoxLayout(); rr1.addStretch()
        self.btn_test_llm = mdi_button("测试连接", "search"); self.btn_test_llm.setObjectName("secondary_button"); self.btn_test_llm.setFixedWidth(110); self.btn_test_llm.clicked.connect(self._test_llm_connection); rr1.addWidget(self.btn_test_llm)
        b2 = mdi_button("保存", "save"); b2.setObjectName("primary_button"); b2.setFixedWidth(90); b2.clicked.connect(self.save_llm_config); rr1.addWidget(b2)
        lg1.addLayout(rr1)
        self.llm_status_lbl = QLabel(""); lg1.addWidget(self.llm_status_lbl)
        scroll_layout.addWidget(g1)

        # ───── VoxCPM ─────
        g3 = QGroupBox("🗣️ 声音克隆 VoxCPM（远程）"); g3.setObjectName("model_groupbox"); g3.setProperty("section", "vox"); lg3 = QVBoxLayout(g3); lg3.setSpacing(10)
        _rl(lg3, "API 地址:", lambda r: (setattr(self,'vox_api_url_input',QLineEdit()), self.vox_api_url_input.setPlaceholderText("http://远程服务器IP:7861/v1/tts"), r.addWidget(self.vox_api_url_input)))
        lg3.addLayout(_row(lambda r: (r.addWidget(QLabel("推理步数:")), setattr(self,'vox_timesteps_spin',QSpinBox()), self.vox_timesteps_spin.setRange(5,100), self.vox_timesteps_spin.setValue(20), self.vox_timesteps_spin.setFixedWidth(70), r.addWidget(self.vox_timesteps_spin), r.addSpacing(20),
            r.addWidget(QLabel("CFG:")), setattr(self,'vox_cfg_spin',QDoubleSpinBox()), self.vox_cfg_spin.setRange(0.5,10.0), self.vox_cfg_spin.setSingleStep(0.1), self.vox_cfg_spin.setValue(2.0), self.vox_cfg_spin.setFixedWidth(70), r.addWidget(self.vox_cfg_spin), r.addStretch())))
        rr3 = QHBoxLayout(); rr3.addStretch()
        b3_test = mdi_button("测试连接", "search"); b3_test.setObjectName("secondary_button"); b3_test.setFixedWidth(110); b3_test.clicked.connect(self._test_vox_connection); rr3.addWidget(b3_test)
        b3 = mdi_button("保存", "save"); b3.setObjectName("primary_button"); b3.setFixedWidth(90); b3.clicked.connect(self.save_voxcpm_config); rr3.addWidget(b3)
        lg3.addLayout(rr3)
        self.llm_vox_status_val = QLabel("服务状态: 请填写远程 API 地址并保存"); self.llm_vox_status_val.setObjectName("muted_text"); lg3.addWidget(self.llm_vox_status_val)
        scroll_layout.addWidget(g3)

        # ───── 视觉模型（Ollama 托管）—— 合并原「Ollama 远程视觉服务」与「当前视觉模型」两个分组 ─────
        g4 = QGroupBox("👁️ 视觉模型（Ollama）"); g4.setObjectName("model_groupbox"); g4.setProperty("section", "vision"); lg4 = QVBoxLayout(g4); lg4.setSpacing(10)
        # 状态行：连通状态 + 已下载模型列表 + 刷新按钮
        lg4.addLayout(_row(lambda r: (setattr(self,'ollama_status_lbl',QLabel("● 未检测")), self.ollama_status_lbl.setObjectName("ollama_status_lbl"),
            setattr(self,'ollama_models_lbl',QLabel("已下载模型: (未检测)")), self.ollama_models_lbl.setObjectName("ollama_models_lbl"), self.ollama_models_lbl.setWordWrap(True), r.addWidget(self.ollama_models_lbl),
            setattr(self,'btn_ollama_refresh',mdi_button("刷新", "refresh")), self.btn_ollama_refresh.setObjectName("secondary_button"), self.btn_ollama_refresh.setFixedWidth(70), self.btn_ollama_refresh.clicked.connect(self._ollama_refresh_status),
            r.addWidget(self.btn_ollama_refresh))))
        # 地址（模型由服务端选择）
        _inp(lg4, "视觉模型地址:", "llm_vision_api_url_input", "http://127.0.0.1:11434")
        rr_vm = QHBoxLayout(); rr_vm.addStretch()
        b_vm_test = mdi_button("测试连接", "search"); b_vm_test.setObjectName("secondary_button"); b_vm_test.setFixedWidth(110); b_vm_test.clicked.connect(self._test_vision_connection); rr_vm.addWidget(b_vm_test)
        b_vm_save = mdi_button("保存", "save"); b_vm_save.setObjectName("primary_button"); b_vm_save.setFixedWidth(90); b_vm_save.clicked.connect(self.save_llm_config); rr_vm.addWidget(b_vm_save)
        lg4.addLayout(rr_vm)
        self.vision_status_lbl = QLabel(""); lg4.addWidget(self.vision_status_lbl)
        scroll_layout.addWidget(g4)

        # ───── Whisper ─────
        g5 = QGroupBox("🎙️ Whisper 语音转写（远程 ASR 服务）"); g5.setObjectName("model_groupbox"); g5.setProperty("section", "whisper"); lg5 = QVBoxLayout(g5); lg5.setSpacing(10)
        whisper_desc = QLabel("工程已切换为纯远程 ASR 模式，语音转写由远程 Whisper 服务完成，无需本地模型。"); whisper_desc.setObjectName("muted_text"); whisper_desc.setWordWrap(True); lg5.addWidget(whisper_desc)
        _rl(lg5, "ASR 服务地址:", lambda r: (setattr(self,'whisper_api_url_input',QLineEdit()), self.whisper_api_url_input.setPlaceholderText("http://192.168.x.x:9000/asr"), r.addWidget(self.whisper_api_url_input)))
        lg5.addLayout(_row(lambda r: (r.addStretch(),
            setattr(self,'btn_test_whisper',mdi_button("测试连接", "search")), self.btn_test_whisper.setObjectName("secondary_button"), self.btn_test_whisper.setFixedWidth(110), self.btn_test_whisper.clicked.connect(self._test_whisper_connection),
            r.addWidget(self.btn_test_whisper),
            setattr(self,'btn_save_whisper',mdi_button("保存", "save")), self.btn_save_whisper.setObjectName("primary_button"), self.btn_save_whisper.setFixedWidth(90), self.btn_save_whisper.clicked.connect(self.save_llm_config), r.addWidget(self.btn_save_whisper))))
        self.whisper_status_lbl = QLabel(""); self.whisper_status_lbl.setObjectName("muted_text"); lg5.addWidget(self.whisper_status_lbl)
        scroll_layout.addWidget(g5)

        # ───── PaddleOCR（服务端 OCR，与 Whisper/CLIP 一致的远程配置样式）─────
        g6 = QGroupBox("🔍 PaddleOCR 文本识别（服务端 OCR）"); g6.setObjectName("model_groupbox"); g6.setProperty("section", "ocr"); lg6 = QVBoxLayout(g6); lg6.setSpacing(10)
        paddle_desc = QLabel("OCR 已切换为纯服务端模式，由算力服务端 POST /material/ocr 完成识别，无需本地模型或专属环境。"); paddle_desc.setObjectName("muted_text"); paddle_desc.setWordWrap(True); lg6.addWidget(paddle_desc)
        _rl(lg6, "OCR 服务地址:", lambda r: (setattr(self,'ocr_api_url_input',QLineEdit()), self.ocr_api_url_input.setPlaceholderText("http://192.168.x.x:8000（与统一服务端地址同步）"), r.addWidget(self.ocr_api_url_input)))
        lg6.addLayout(_row(lambda r: (r.addStretch(),
            setattr(self,'btn_test_ocr',mdi_button("测试连接", "search")), self.btn_test_ocr.setObjectName("secondary_button"), self.btn_test_ocr.setFixedWidth(110), self.btn_test_ocr.clicked.connect(self._test_ocr_connection),
            r.addWidget(self.btn_test_ocr),
            setattr(self,'btn_save_ocr',mdi_button("保存", "save")), self.btn_save_ocr.setObjectName("primary_button"), self.btn_save_ocr.setFixedWidth(90), self.btn_save_ocr.clicked.connect(self.save_llm_config), r.addWidget(self.btn_save_ocr))))
        # 兼容旧字段：状态/模型（env_config 仍会更新 llm_paddle_status_val）
        _rl(lg6, "状态:", lambda r: (setattr(self,'llm_paddle_status_val',QLabel("正在检测...")), r.addWidget(self.llm_paddle_status_val)))
        _rl(lg6, "模型:", lambda r: (setattr(self,'llm_paddle_models_val',QLabel("由服务端提供")), r.addWidget(self.llm_paddle_models_val)))
        self.ocr_status_lbl = QLabel(""); self.ocr_status_lbl.setObjectName("muted_text"); lg6.addWidget(self.ocr_status_lbl)
        scroll_layout.addWidget(g6)

        # ───── CLIP ─────
        g7 = QGroupBox("🖼️ CLIP 向量检索（远程 embedding 服务）"); g7.setObjectName("model_groupbox"); g7.setProperty("section", "clip"); lg7 = QVBoxLayout(g7); lg7.setSpacing(10)
        clip_desc = QLabel("向量检索的 CLIP embedding 已切换为纯远程模式，由远程 embedding 服务完成图文向量编码，无需本地模型。"); clip_desc.setObjectName("muted_text"); clip_desc.setWordWrap(True); lg7.addWidget(clip_desc)
        _rl(lg7, "CLIP API 地址:", lambda r: (setattr(self,'clip_api_url_input',QLineEdit()), self.clip_api_url_input.setPlaceholderText("http://192.168.x.x:8001"), r.addWidget(self.clip_api_url_input)))
        lg7.addLayout(_row(lambda r: (r.addStretch(),
            setattr(self,'btn_test_clip',mdi_button("测试连接", "search")), self.btn_test_clip.setObjectName("secondary_button"), self.btn_test_clip.setFixedWidth(110), self.btn_test_clip.clicked.connect(self._test_clip_connection),
            r.addWidget(self.btn_test_clip),
            setattr(self,'btn_save_clip',mdi_button("保存", "save")), self.btn_save_clip.setObjectName("primary_button"), self.btn_save_clip.setFixedWidth(90), self.btn_save_clip.clicked.connect(self.save_llm_config), r.addWidget(self.btn_save_clip))))
        self.clip_status_lbl = QLabel(""); self.clip_status_lbl.setObjectName("muted_text"); lg7.addWidget(self.clip_status_lbl)
        scroll_layout.addWidget(g7)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)
        # Load data
        prov = self.ai_config.get("llm_provider","deepseek"); idx = self.llm_provider_combo.findData(prov)
        if idx>=0: self.llm_provider_combo.setCurrentIndex(idx)
        self.llm_api_url_input.setText(self.ai_config.get("llm_api_url","https://api.deepseek.com"))
        self.llm_api_key_input.setText(self.ai_config.get("llm_api_key",""))
        self.llm_model_input.setText(self.ai_config.get("llm_model","deepseek-v4-flash"))
        self.llm_vision_api_url_input.setText(self.ai_config.get("llm_vision_api_url","http://127.0.0.1:11434"))
        self.load_voxcpm_config()
        # 统一服务端地址初始化（会联动同步 Whisper/CLIP/PaddleOCR 的地址）
        self.compute_server_input.setText(self.ai_config.get("compute_server_url", ""))

        # ── 统一管理：模型专属 API 地址置灰只读展示，禁止手动编辑 ──
        # LLM API 地址输入框在「自定义」模式下可编辑，其余模式只读
        _readonly_style = (
            "QLineEdit { background-color: #3a3a3a; color: #909090; border: 1px solid #555; }"
        )
        for inp in [
            self.llm_vision_api_url_input,
            getattr(self, "vox_api_url_input", None),
            getattr(self, "whisper_api_url_input", None),
            getattr(self, "clip_api_url_input", None),
            getattr(self, "ocr_api_url_input", None),
        ]:
            if inp:
                inp.setReadOnly(True)
                inp.setStyleSheet(_readonly_style)
        # LLM API 地址：根据当前提供商决定是否只读
        if prov != "custom":
            self.llm_api_url_input.setReadOnly(True)
            self.llm_api_url_input.setStyleSheet(_readonly_style)

        self.refresh_llm_page_status()

    # ═══════════════════════════════════════════════════════════════
    #  平台接入 — ComfyUI / RunningHub / 飞书 / 即梦
    # ═══════════════════════════════════════════════════════════════
    def setup_llm_settings_page(self):
        layout = QVBoxLayout(self.page_llm_settings)
        layout.setContentsMargins(20, 20, 20, 20)
        tabs = QTabWidget()

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
        # ── Tab 2: RunningHub ──
        p2 = QWidget(); l2 = QVBoxLayout(p2); l2.setContentsMargins(30,30,30,30)
        l2.addWidget(QLabel("RunningHub API Key（在 RunningHub 个人中心获取）:"))
        self.runninghub_api_key_input = QLineEdit(); self.runninghub_api_key_input.setPlaceholderText("rh_xxxxxxxx..."); self.runninghub_api_key_input.setEchoMode(QLineEdit.Password); self.runninghub_api_key_input.setText(self.ai_config.get("runninghub_api_key", "")); l2.addWidget(self.runninghub_api_key_input)
        l2.addWidget(QLabel("RunningHub 基础地址（一般保持默认）:"))
        self.runninghub_base_url_input = QLineEdit(); self.runninghub_base_url_input.setPlaceholderText("https://www.runninghub.cn"); self.runninghub_base_url_input.setText(self.ai_config.get("runninghub_base_url", "https://www.runninghub.cn")); l2.addWidget(self.runninghub_base_url_input)
        l2.addWidget(QLabel("在线工作流 ComfyUI 协议会话凭证（登录浏览器控制台 localStorage 获取）:"))
        self.runninghub_comfy_auth_input = QLineEdit(); self.runninghub_comfy_auth_input.setPlaceholderText("Rh-Comfy-Auth"); self.runninghub_comfy_auth_input.setToolTip("localStorage.getItem('Rh-Comfy-Auth')"); self.runninghub_comfy_auth_input.setText(self.ai_config.get("runninghub_comfy_auth", "")); l2.addWidget(self.runninghub_comfy_auth_input)
        self.runninghub_comfy_identify_input = QLineEdit(); self.runninghub_comfy_identify_input.setPlaceholderText("Rh-Identify"); self.runninghub_comfy_identify_input.setToolTip("localStorage.getItem('Rh-Identify')"); self.runninghub_comfy_identify_input.setText(self.ai_config.get("runninghub_comfy_identify", "")); l2.addWidget(self.runninghub_comfy_identify_input)
        self.runninghub_access_token_input = QLineEdit(); self.runninghub_access_token_input.setPlaceholderText("Rh-Accesstoken"); self.runninghub_access_token_input.setToolTip("localStorage.getItem('Rh-Accesstoken')"); self.runninghub_access_token_input.setText(self.ai_config.get("runninghub_access_token", "")); l2.addWidget(self.runninghub_access_token_input)
        self.runninghub_use_personal_queue_check = QCheckBox("使用个人独占队列（企业级-独占 Key 建议开启）"); self.runninghub_use_personal_queue_check.setToolTip("usePersonalQueue；独占机器请保持勾选，否则任务可能不会被分配到你租的机器"); self.runninghub_use_personal_queue_check.setChecked(bool(self.ai_config.get("runninghub_use_personal_queue", True))); l2.addWidget(self.runninghub_use_personal_queue_check)
        r2 = QHBoxLayout(); r2.addStretch()
        b_save_rh = mdi_button("保存 RunningHub 配置", "save"); b_save_rh.setObjectName("primary_button"); b_save_rh.clicked.connect(self.save_ai_config); r2.addWidget(b_save_rh)
        b_test_rh = mdi_button("测试连接", "link"); b_test_rh.setObjectName("secondary_button"); b_test_rh.clicked.connect(self._test_runninghub_config); r2.addWidget(b_test_rh)
        b_test_comfy = mdi_button("测试 ComfyUI 协议", "link"); b_test_comfy.setObjectName("secondary_button"); b_test_comfy.clicked.connect(self._test_runninghub_comfy_protocol); r2.addWidget(b_test_comfy)
        l2.addLayout(r2)
        self.rh_config_status = QLabel(""); self.rh_config_status.setObjectName("muted_text"); l2.addWidget(self.rh_config_status)
        self.rh_comfy_status = QLabel(""); self.rh_comfy_status.setObjectName("muted_text"); l2.addWidget(self.rh_comfy_status)

        # ── RunningHub 工作流管理 ──
        l2.addSpacing(20)
        wf_group = QGroupBox("☁️ 工作流管理"); wf_group.setObjectName("model_groupbox")
        wf_layout = QVBoxLayout(wf_group); wf_layout.setSpacing(10)

        wf_layout.addWidget(QLabel("工作流列表（带类型，可编辑。点击「刷新」尝试从 RunningHub 读取）："))
        self.rh_workflow_table = QTableWidget(0, 4)
        self.rh_workflow_table.setHorizontalHeaderLabels(["名称", "类型", "工作流 ID", "实例类型"])
        self.rh_workflow_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rh_workflow_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.rh_workflow_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.rh_workflow_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.rh_workflow_table.verticalHeader().setVisible(False)
        self.rh_workflow_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rh_workflow_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rh_workflow_table.setMinimumHeight(120)
        self.rh_workflow_table.setMaximumHeight(180)
        self.rh_workflow_table.itemSelectionChanged.connect(self._rh_on_workflow_selection_changed)
        wf_layout.addWidget(self.rh_workflow_table)

        wf_btn_row = QHBoxLayout()
        btn_refresh_wf = mdi_button("刷新工作流列表", "refresh")
        btn_refresh_wf.setToolTip("尝试从 RunningHub API 拉取该账号下的工作流列表")
        btn_refresh_wf.clicked.connect(self._rh_refresh_workflow_list)
        wf_btn_row.addWidget(btn_refresh_wf)
        btn_add_wf = mdi_button("添加", "plus")
        btn_add_wf.setToolTip("添加一个新的工作流（可设置名称、类型、ID）")
        btn_add_wf.clicked.connect(self._rh_show_add_workflow_dialog)
        wf_btn_row.addWidget(btn_add_wf)
        btn_edit_wf = mdi_button("编辑", "pencil")
        btn_edit_wf.setToolTip("编辑选中工作流的名称、类型、ID")
        btn_edit_wf.clicked.connect(self._rh_show_edit_workflow_dialog)
        wf_btn_row.addWidget(btn_edit_wf)
        btn_view_wf = mdi_button("显示节点", "eye")
        btn_view_wf.setToolTip("在下方显示选中工作流的所有节点、输入、输出连接")
        btn_view_wf.clicked.connect(self._rh_view_workflow_nodes)
        wf_btn_row.addWidget(btn_view_wf)
        btn_del_wf = mdi_button("删除", "delete")
        btn_del_wf.setToolTip("从本地保存的工作流列表中移除")
        btn_del_wf.clicked.connect(self._rh_remove_workflow)
        wf_btn_row.addWidget(btn_del_wf)
        wf_btn_row.addStretch()
        wf_layout.addLayout(wf_btn_row)

        # 选中工作流后在此区域显示其节点（不弹窗）
        wf_layout.addWidget(QLabel("工作流节点详情（选择工作流后自动显示）："))
        self.rh_workflow_node_display = QTextBrowser()
        self.rh_workflow_node_display.setText("选择上方工作流后，节点信息会显示在这里。")
        self.rh_workflow_node_display.setMinimumHeight(120)
        self.rh_workflow_node_display.setMaximumHeight(200)
        wf_layout.addWidget(self.rh_workflow_node_display)

        self.rh_workflow_list_status = QLabel("")
        self.rh_workflow_list_status.setObjectName("muted_text")
        wf_layout.addWidget(self.rh_workflow_list_status)

        l2.addWidget(wf_group)
        # 加载已保存的工作流列表
        if hasattr(self, "_rh_load_workflow_list"):
            self._rh_load_workflow_list()
        l2.addStretch(); tabs.addTab(p2, "☁️ RunningHub")


        # ── Tab 2: 飞书（已隐藏，代码保留）──
        p3 = QWidget(); l3 = QVBoxLayout(p3); l3.setContentsMargins(30,30,30,30)
        l3.addWidget(QLabel("飞书配置（用于同步选题 / 脚本到飞书多维表格）:"))
        _inp("App ID:", "edit_feishu_appid", "飞书开放平台自建应用的 App ID", l3)
        _inp("App Secret:", "edit_feishu_appsecret", "App Secret", l3, echo=QLineEdit.Password)
        _inp("App Token:", "edit_feishu_apptoken", "飞书多维表格的 app_token", l3)
        _inp("数据表 Table ID:", "edit_feishu_tableid", "tblxxxxxxxxxxxxxx", l3)
        _inp("选题字段名:", "edit_feishu_topicfield", "默认: 选题", l3)
        _inp("脚本字段名:", "edit_feishu_scriptfield", "默认: 脚本", l3)
        _inp("文档保存文件夹 Token:", "edit_feishu_foldertoken", "fldcnxxxxxxxxxxxxxxxxxxxxxx (选填)", l3)
        self.edit_feishu_topicfield.setText("选题")
        self.edit_feishu_scriptfield.setText("脚本")
        r3 = QHBoxLayout(); r3.addStretch()
        b3 = mdi_button("保存飞书配置", "save"); b3.setObjectName("primary_button"); b3.clicked.connect(self.save_feishu_config); r3.addWidget(b3)
        b4 = mdi_button("测试连接", "link"); b4.setObjectName("secondary_button"); b4.clicked.connect(self._test_feishu); r3.addWidget(b4)
        l3.addLayout(r3)
        self.fs_test_status = QLabel(""); self.fs_test_status.setObjectName("muted_text"); l3.addWidget(self.fs_test_status)
        l3.addStretch()
        tabs.addTab(p3, "✈️ 飞书")

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

        # ── Tab 5: 旺店通 ERP（已移除，ERP 配置由服务端统一管理）──

        layout.addWidget(tabs, 1)
        # Load feishu config
        self.load_feishu_config()

    def _build_digital_human_tab(self, parent):
            layout = QVBoxLayout(parent)
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
            self.backend_selector = QComboBox()
            self.backend_selector.addItems(["ComfyUI (本地/局域网)", "RunningHub (云端)"])
            self.backend_selector.currentIndexChanged.connect(self._on_dh_backend_changed)
            config_layout.addWidget(self.backend_selector)
        
            config_layout.addSpacing(15)

            # --- ComfyUI Section ---
            self.comfy_section = QWidget()
            comfy_layout = QVBoxLayout(self.comfy_section)
            comfy_layout.setContentsMargins(0, 0, 0, 0)
        
            self.workflow_status = QLabel("正在自动加载工作流...")
            comfy_layout.addWidget(self.workflow_status)
        
            comfy_layout.addSpacing(15)
        
            comfy_layout.addWidget(QLabel("人物图片:"))
            img_row = QHBoxLayout()
            self.img_path_input = QLineEdit()
            self.img_path_input.setPlaceholderText("请选择图片...")
            img_row.addWidget(self.img_path_input)
            btn_sel_img = mdi_button("浏览", "folder")
            btn_sel_img.clicked.connect(self.select_image)
            img_row.addWidget(btn_sel_img)
            comfy_layout.addLayout(img_row)
        
            comfy_layout.addWidget(QLabel("驱动语音:"))
            aud_row = QHBoxLayout()
            self.aud_path_input = QLineEdit()
            self.aud_path_input.setPlaceholderText("请选择音频...")
            aud_row.addWidget(self.aud_path_input)
            btn_sel_aud = mdi_button("浏览", "folder")
            btn_sel_aud.clicked.connect(self.select_audio)
            aud_row.addWidget(btn_sel_aud)
            comfy_layout.addLayout(aud_row)
        
            config_layout.addWidget(self.comfy_section)

            # --- RunningHub Section ---
            self.rh_section = QWidget()
            rh_layout = QVBoxLayout(self.rh_section)
            rh_layout.setContentsMargins(0, 0, 0, 0)

            rh_layout.addWidget(QLabel("RunningHub 数字人工作流:"))
            rh_id_row = QHBoxLayout()
            self.rh_workflow_selector = QComboBox()
            self.rh_workflow_selector.setView(QListView())
            self.rh_workflow_selector.currentIndexChanged.connect(self._on_rh_dh_workflow_changed)
            rh_id_row.addWidget(self.rh_workflow_selector, 1)

            # 保留隐藏的 ID 输入框，供现有逻辑读取
            self.rh_workflow_id_input = QLineEdit()
            self.rh_workflow_id_input.setVisible(False)
            rh_id_row.addWidget(self.rh_workflow_id_input)

            btn_refresh_dh_wf = mdi_button("刷新", "refresh")
            btn_refresh_dh_wf.setToolTip("刷新数字人工作流列表")
            btn_refresh_dh_wf.clicked.connect(self._rh_refresh_dh_workflow_selector)
            rh_id_row.addWidget(btn_refresh_dh_wf)
            btn_fetch_rh = mdi_button("获取工作流节点", "refresh")
            btn_fetch_rh.setToolTip("重新获取当前选中工作流的节点")
            btn_fetch_rh.clicked.connect(self.view_rh_api_detail)
            rh_id_row.addWidget(btn_fetch_rh)
            btn_open_rh_web = mdi_button("打开网页", "open-in-new")
            btn_open_rh_web.setToolTip("在浏览器打开 RunningHub 该工作流 API 页面")
            btn_open_rh_web.clicked.connect(self.open_rh_web_interface)
            rh_id_row.addWidget(btn_open_rh_web)
            rh_id_row.addStretch()
            rh_layout.addLayout(rh_id_row)

            self.rh_workflow_info = QLabel("填写工作流 ID 后点击「获取工作流节点」")
            self.rh_workflow_info.setObjectName("muted_text")
            self.rh_workflow_info.setWordWrap(True)
            rh_layout.addWidget(self.rh_workflow_info)

            # 工作流节点列表（带复选框，勾选需要映射的节点）
            rh_layout.addWidget(QLabel("工作流输入节点（勾选需要映射的节点）:"))
            self.rh_node_list = QListWidget()
            self.rh_node_list.setMinimumHeight(120)
            self.rh_node_list.setMaximumHeight(180)
            self.rh_node_list.itemChanged.connect(self._on_rh_node_checked)
            rh_layout.addWidget(self.rh_node_list)

            # 动态输入面板：根据勾选的节点类型显示对应输入组件
            self.rh_input_panel = QWidget()
            rh_input_layout = QVBoxLayout(self.rh_input_panel)
            rh_input_layout.setContentsMargins(0, 0, 0, 0)
            rh_input_layout.setSpacing(12)

            # 图片输入组
            self.rh_img_input_group = QWidget()
            rh_img_group_layout = QVBoxLayout(self.rh_img_input_group)
            rh_img_group_layout.setContentsMargins(0, 0, 0, 0)
            rh_img_group_layout.addWidget(QLabel("人物图片（所有勾选的图片节点共用）:"))
            rh_img_row = QHBoxLayout()
            self.rh_img_path_input = QLineEdit()
            self.rh_img_path_input.setPlaceholderText("请选择一张图片...")
            rh_img_row.addWidget(self.rh_img_path_input)
            btn_sel_rh_img = mdi_button("浏览", "folder")
            btn_sel_rh_img.clicked.connect(self.select_rh_image)
            rh_img_row.addWidget(btn_sel_rh_img)
            rh_img_group_layout.addLayout(rh_img_row)
            rh_input_layout.addWidget(self.rh_img_input_group)

            # 音频输入组
            self.rh_audio_input_group = QWidget()
            rh_audio_group_layout = QVBoxLayout(self.rh_audio_input_group)
            rh_audio_group_layout.setContentsMargins(0, 0, 0, 0)
            rh_audio_group_layout.addWidget(QLabel("驱动语音（批量，每个音频生成一个任务，所有勾选的音频节点共用）:"))
            rh_audio_row = QHBoxLayout()
            self.rh_audio_list = QListWidget()
            self.rh_audio_list.setMinimumHeight(80)
            self.rh_audio_list.setMaximumHeight(140)
            rh_audio_row.addWidget(self.rh_audio_list, 1)
            rh_audio_btn_col = QVBoxLayout()
            btn_add_rh_aud = mdi_button("添加", "plus")
            btn_add_rh_aud.clicked.connect(self.add_rh_audio)
            rh_audio_btn_col.addWidget(btn_add_rh_aud)
            btn_del_rh_aud = mdi_button("移除", "minus")
            btn_del_rh_aud.clicked.connect(self.remove_rh_audio)
            rh_audio_btn_col.addWidget(btn_del_rh_aud)
            rh_audio_btn_col.addStretch()
            rh_audio_row.addLayout(rh_audio_btn_col)
            rh_audio_group_layout.addLayout(rh_audio_row)
            rh_input_layout.addWidget(self.rh_audio_input_group)

            rh_layout.addWidget(self.rh_input_panel)
            self.rh_queue_stats_label = QLabel("任务队列: 共 0 | 成功 0 | 失败 0 | 运行中 0 | 待处理 0 | 进度 0%")
            self.rh_queue_stats_label.setObjectName("muted_text")
            rh_layout.addWidget(self.rh_queue_stats_label)
            rh_layout.addStretch()

            config_layout.addWidget(self.rh_section)
            self.rh_section.hide()

            # --- Shared Submit Button ---
            self.btn_run_workflow = mdi_button("提交生成任务", "rocket")
            self.btn_run_workflow.setObjectName("action_button")
            self.btn_run_workflow.setEnabled(False)
            self.btn_run_workflow.setFixedHeight(50)
            self.btn_run_workflow.clicked.connect(self.run_digital_human_task)
            config_layout.addSpacing(20)
            config_layout.addWidget(self.btn_run_workflow)

            # --- Log Output ---
            self.log_area = QTextEdit()
            self.log_area.setReadOnly(True)
            self.log_area.setPlaceholderText("任务日志...")
            self.log_area.setMinimumHeight(80)
            config_layout.addWidget(self.log_area)

            layout.addWidget(card)
            layout.addStretch()
        
            self.current_workflow_data = None
            # Auto-load default workflow for Digital Human
            QTimer.singleShot(500, self.auto_load_default_dh_workflow)
            QTimer.singleShot(600, lambda: self._on_dh_backend_changed(self.backend_selector.currentIndex()))
    def select_image(self):
        """数字人 ComfyUI：选择人物图片。"""
        file, _ = pick_file(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        if file:
            self.img_path_input.setText(file)

    def select_audio(self):
        """数字人 ComfyUI：选择驱动语音。"""
        file, _ = pick_file(self, "选择音频", "", "Audio (*.mp3 *.wav)")
        if file:
            self.aud_path_input.setText(file)

    def select_rh_image(self):
        """数字人 RunningHub：选择人物图片。"""
        file, _ = pick_file(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        if file:
            self.rh_img_path_input.setText(file)

    def add_rh_audio(self):
        """数字人 RunningHub：批量添加驱动音频。"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择音频", "", "Audio (*.mp3 *.wav *.flac *.aac *.m4a)")
        for f in files:
            if f and not self.rh_audio_list.findItems(f, Qt.MatchExactly):
                self.rh_audio_list.addItem(f)
        if self.backend_selector.currentIndex() == 1:
            self._on_dh_backend_changed(1)

    def remove_rh_audio(self):
        """数字人 RunningHub：移除选中的驱动音频。"""
        for item in self.rh_audio_list.selectedItems():
            self.rh_audio_list.takeItem(self.rh_audio_list.row(item))
        if self.backend_selector.currentIndex() == 1:
            self._on_dh_backend_changed(1)

    def setup_task_list_page(self):
            layout = QVBoxLayout(self.page_task_list)
            layout.setContentsMargins(30, 30, 30, 30)

            # 统一标题
            heading = QLabel("📋 任务队列")
            heading.setObjectName("heading")
            layout.addWidget(heading)

            # --- Task List ---
            task_card = QFrame()
            task_card.setObjectName("card")
            task_layout = QVBoxLayout(task_card)

            header = QHBoxLayout()
            self.lbl_task_status = QLabel("")
            self.lbl_task_status.setObjectName("muted_text")
            header.addWidget(self.lbl_task_status, 1)
            btn_sync = mdi_button("同步服务端", "refresh")
            btn_sync.setFixedWidth(100)
            btn_sync.clicked.connect(self._sync_server_tasks_async)
            header.addWidget(btn_sync)
            btn_clear = mdi_button("清除已完成", "close")
            btn_clear.setFixedWidth(100)
            btn_clear.clicked.connect(self._clear_done_tasks)
            header.addWidget(btn_clear)
            btn_export_rh = mdi_button("导出 RunningHub 结果", "download")
            btn_export_rh.setFixedWidth(150)
            btn_export_rh.clicked.connect(self.export_all_rh_results)
            header.addWidget(btn_export_rh)
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
            self.task_table.setColumnWidth(6, 160)
            self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.task_table.cellClicked.connect(self._on_task_row_clicked)
            task_layout.addWidget(self.task_table)
        
            layout.addWidget(task_card, 2)

            # ── 任务详情（点击选中任务行时显示）────────────────────────────
            detail_card = QFrame(); detail_card.setObjectName("card")
            dl = QVBoxLayout(detail_card); dl.setContentsMargins(12, 10, 12, 10); dl.setSpacing(6)
            dl.addWidget(QLabel("🔍 任务详情（点击上方任务行查看）"))
            self.task_detail = QTextBrowser()
            self.task_detail.setMinimumHeight(120)
            self.task_detail.setPlaceholderText("点击上方任务行查看其参数与执行结果…")
            dl.addWidget(self.task_detail, 1)
            layout.addWidget(detail_card, 1)

    def _on_task_row_clicked(self, row, _col):
        """点击任务行：在下方详情区展示该任务的参数/结果/错误。"""
        item = self.task_table.item(row, 0)
        if not item:
            return
        t = item.data(0x0100)  # 完整任务 dict（同步时存入）
        if not t:
            return
        lines = [
            f"### {t.get('title') or t.get('type') or '任务'}",
            "",
            f"- **任务 ID**：`{t.get('id') or ''}`",
            f"- **类型**：{t.get('type', '')}",
            f"- **状态**：{t.get('status', '')}",
            f"- **进度**：{t.get('progress', 0)}%",
        ]
        if t.get("client_ip"):
            lines.append(f"- **来源 IP**：{t.get('client_ip')}")
        if t.get("error"):
            lines.append(f"- **错误**：`{t.get('error')}`")
        if t.get("params"):
            lines.append(f"- **参数**：`{str(t.get('params'))[:400]}`")
        if t.get("result"):
            lines.append(f"- **结果**：`{str(t.get('result'))[:400]}`")
        self.task_detail.setMarkdown("\n".join(lines))

    def _sync_server_tasks_async(self):
        """异步版本：HTTP 请求放 Worker 线程，UI 更新回主线程。"""
        from utils.thread_worker import TaskWorker as Worker

        def _fetch():
            """仅做 HTTP 请求，返回数据，不碰 UI。"""
            from utils.http_client import http_get
            import socket as _socket
            try:
                from utils import config_manager as _cm
                base_url = ""
                url = (_cm.get_setting("ai_config", "compute_server_url") or "").strip().rstrip("/")
                if url:
                    base_url = url
                if not base_url:
                    return None
                resp = http_get(f"{base_url}/tasks", timeout=10)
                if resp.status_code != 200:
                    return None
                tasks = resp.json()
                if not isinstance(tasks, list):
                    return None

                # 获取本机 IP
                local_ip = ""
                try:
                    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                    s.connect((base_url.replace("http://", "").replace("https://", "").split(":")[0], 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    pass

                # 过滤本机任务
                my_tasks = []
                for t in tasks:
                    task_ip = (t.get("client_ip") or "").strip()
                    if local_ip and task_ip and task_ip != local_ip:
                        continue
                    my_tasks.append(t)
                return my_tasks
            except Exception as e:
                print(f"同步服务端任务失败: {e}")
                return None

        def _on_done(tasks):
            """主线程回调：更新 UI。"""
            if not tasks:
                return
            existing = set()
            for row in range(self.task_table.rowCount()):
                item = self.task_table.item(row, 0)
                if item:
                    existing.add(item.text())

            added = 0
            import datetime as _dt
            for t in tasks:
                tid = (t.get("id") or "")[:12]
                if not tid or tid in existing:
                    continue
                created_ts = t.get("created_at") or t.get("started_at") or 0
                time_str = _dt.datetime.fromtimestamp(created_ts).strftime("%m-%d %H:%M") if created_ts else ""
                row = self.task_table.rowCount()
                self.task_table.insertRow(row)
                item0 = QTableWidgetItem(tid)
                item0.setData(0x0100, t)  # 存完整任务 dict，供详情展示
                self.task_table.setItem(row, 0, item0)
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

        self._sync_worker = Worker(_fetch)
        self._sync_worker.finished.connect(_on_done)
        self._sync_worker.start()
    
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
            header.addStretch()
            layout.addLayout(header)

            # 标题行不放其它控件（避免被资源监控悬浮层遮挡），按钮独立一行
            add_row = QHBoxLayout()
            add_row.addStretch()
            btn_add = mdi_button("添加新账户", "plus")
            btn_add.setObjectName("primary_button")
            btn_add.setFixedWidth(150)
            btn_add.clicked.connect(self.trigger_add_account)
            add_row.addWidget(btn_add)
            layout.addLayout(add_row)
        
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

    def _build_log_tab(self, parent):
        """系统日志 Tab：日志查看器 + 级别/关键词过滤 + 服务端日志开关。"""
        l1 = QVBoxLayout(parent); l1.setContentsMargins(16,16,16,16)
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
        # 右键菜单：清空日志
        self.log_viewer.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_viewer.customContextMenuRequested.connect(self._log_viewer_context_menu)
        l1.addWidget(QLabel("完整日志: .runtime/logs/app.log"))

    def _build_sysinfo_tab(self, parent):
        """系统信息 Tab：本机硬件 / Python / CUDA 环境检测。"""
        self.page_sysinfo = parent
        l2 = QVBoxLayout(parent); l2.setContentsMargins(30,30,30,30); l2.setSpacing(12)
        l2.addWidget(QLabel("系统硬件信息")); l2.addWidget(self._info_row("操作系统:", "os_ver"))
        l2.addWidget(self._info_row("处理器:", "cpu_info"))
        l2.addWidget(self._info_row("内存:", "ram_info"))
        l2.addWidget(self._info_row("显卡:", "gpu_info"))
        l2.addWidget(self._info_row("Python:", "python_ver"))
        l2.addWidget(self._info_row("PyTorch:", "torch_ver"))
        l2.addWidget(self._info_row("CUDA:", "cuda_info"))
        l2.addStretch()
        QTimer.singleShot(200, self._refresh_help_sysinfo)

    def _build_about_tab(self, parent):
        """关于与版本 Tab：品牌 / 授权 / 版本信息。"""
        l3 = QVBoxLayout(parent); l3.setContentsMargins(30, 20, 30, 20); l3.setSpacing(14)

        # Brand / Developer Info Card
        brand_card = QFrame()
        brand_card.setObjectName("brand_card")
        brand_layout = QVBoxLayout(brand_card)
        brand_layout.setContentsMargins(20, 20, 20, 20)
        brand_layout.setSpacing(10)

        app_title = QLabel("🔩 螺丝钉-电商智能体矩阵")
        app_title.setObjectName("about_app_title")
        brand_layout.addWidget(app_title)

        dev_info = QLabel("此智能体由 <b>大怪工作室</b> 开发")
        dev_info.setObjectName("about_dev_info")
        brand_layout.addWidget(dev_info)

        contact_info = QLabel("📞 联系电话：<span style='color: #3b82f6; font-weight: bold;'>17361907260</span>（微信同号）")
        contact_info.setObjectName("about_contact")
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
        license_layout = QVBoxLayout(license_card)
        license_layout.setContentsMargins(20, 16, 20, 16)
        license_layout.setSpacing(10)

        license_title = QLabel("🔑 软件授权与激活")
        license_title.setObjectName("about_license_title")
        license_layout.addWidget(license_title)

        # Machine ID Row with Copy button
        mac_row = QHBoxLayout()
        mac_row.setContentsMargins(0, 0, 0, 0)
        mac_lbl = QLabel("本机机器码:")
        mac_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        mac_val = QLineEdit(machine_id)
        mac_val.setReadOnly(True)
        mac_val.setObjectName("about_machine_id")
        
        btn_copy = QPushButton("📋 复制机器码")
        btn_copy.setFixedWidth(100)
        btn_copy.setObjectName("about_copy_btn")
        
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
        licensee_val.setObjectName("about_section_value")
        licensee_row.addWidget(licensee_lbl)
        licensee_row.addWidget(licensee_val, 1)
        license_layout.addLayout(licensee_row)

        # Expiration row
        expire_row = QHBoxLayout()
        expire_row.setContentsMargins(0, 0, 0, 0)
        expire_lbl = QLabel("有效期至:")
        expire_lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
        expire_val = QLabel(expiry_date)
        expire_val.setObjectName("about_section_value")
        expire_row.addWidget(expire_lbl)
        expire_row.addWidget(expire_val, 1)
        license_layout.addLayout(expire_row)

        l3.addWidget(license_card)

        # System & Version Info Card
        version_card = QFrame()
        version_card.setObjectName("version_card")
        version_layout = QVBoxLayout(version_card)
        version_layout.setContentsMargins(20, 16, 20, 16)
        version_layout.setSpacing(8)

        version_title = QLabel("📋 系统与版本信息")
        version_title.setObjectName("about_version_title")
        version_layout.addWidget(version_title)

        import sys as _s, platform as _p
        def add_version_row(label, val):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #8e8e93; font-size: 12px; font-weight: bold; min-width: 80px;")
            v_val = QLabel(val)
            v_val.setObjectName("about_section_value")
            v_val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(v_val, 1)
            version_layout.addLayout(row)

        add_version_row("应用版本:", f"v{get_version()}")
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

    def _build_theme_tab(self, parent):
        """外观主题 Tab。"""
        l4 = QVBoxLayout(parent); l4.setContentsMargins(30, 30, 30, 30)
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
        self.theme_hint = QLabel("切换主题后立即生效，无需重启；个别旧弹窗会在下次打开时应用最新样式。")
        self.theme_hint.setObjectName("muted_text")
        self.theme_hint.setWordWrap(True)
        l4.addWidget(self.theme_hint)
        l4.addStretch()

    def setup_about_page(self):
        """关于页（侧边栏『关于』入口）：系统信息 / 关于与版本 / 外观 三个子 Tab。"""
        layout = QVBoxLayout(self.page_about)
        layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(0)
        tabs = QTabWidget()

        p1 = QWidget(); p1.setObjectName("tab_page")
        self._build_sysinfo_tab(p1)
        tabs.addTab(p1, "🖥️ 系统信息")

        p2 = QWidget(); p2.setObjectName("tab_page")
        self._build_about_tab(p2)
        tabs.addTab(p2, "ℹ️ 关于与版本")

        p3 = QWidget(); p3.setObjectName("tab_page")
        self._build_theme_tab(p3)
        tabs.addTab(p3, "🎨 外观")

        layout.addWidget(tabs, 1)

    def _info_row(self, label, key):
        w = QLabel(f"{label} 检测中..."); w.setObjectName(key); w.setStyleSheet("font-size:14px;"); return w

    def _refresh_help_sysinfo(self):
        import platform as _p
        target = getattr(self, "page_sysinfo", None)
        if target is None:
            return
        for w in target.findChildren(QLabel):
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
        layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(16)

        tabs = QTabWidget()

        # Tab 1: 系统日志
        p0 = QWidget(); p0.setObjectName("tab_page")
        self._build_log_tab(p0)
        tabs.addTab(p0, "📋 系统日志")

        # Tab 2: 运行环境
        p1 = QWidget(); p1.setObjectName("tab_page")
        from gui.env_config_page import EnvConfigPage
        self.env_config_tool = EnvConfigPage(p1, self); self.env_config_tool.setup()
        tabs.addTab(p1, "🖥️ 运行环境")

        # Tab 3: 终端
        p2 = QWidget(); p2.setObjectName("tab_page")
        from gui.terminal_page import TerminalPage
        self.terminal_tool = TerminalPage(p2, self); self.terminal_tool.setup()
        tabs.addTab(p2, "💻 终端")

        # Tab 4: 备份管理
        p3 = QWidget(); p3.setObjectName("tab_page")
        from gui.backup_page import BackupPage
        self.backup_tool = BackupPage(p3, self); self.backup_tool.setup()
        tabs.addTab(p3, "💾 备份管理")

        # Tab 5: 系统配置
        p4 = QWidget(); p4.setObjectName("tab_page")
        self._setup_system_tab(p4)
        tabs.addTab(p4, "⚙️ 系统配置")

        layout.addWidget(tabs)

    def _setup_system_tab(self, parent_widget):
        """系统配置 Tab：开机自动运行等系统级开关。"""
        from utils import autostart as _autostart
        from utils import config_manager as _cm

        layout = QVBoxLayout(parent_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("⚙️ 系统配置")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hint = QLabel("系统级运行开关，改动立即生效（写入 Windows 注册表 Run 键）。")
        hint.setObjectName("muted_text")
        hint.setWordWrap(True)
        hint.setMaximumWidth(1400)  # 一行显示，右侧留白避让资源监控
        hdr.addWidget(hint)
        hdr.addStretch()
        layout.addLayout(hdr)

        # 开机自动运行（默认开启）
        self.autostart_chk = QCheckBox("🚀 开机自动运行（登录 Windows 后自动启动本程序）")
        self.autostart_chk.setChecked(True)
        layout.addWidget(self.autostart_chk)

        self.autostart_status = QLabel("")
        self.autostart_status.setObjectName("muted_text")
        layout.addWidget(self.autostart_status)

        def _load_cfg() -> dict:
            return _cm.load_config("local_config")

        def _on_autostart_toggled(checked):
            if not _cm.set_setting("local_config", "auto_start", bool(checked)):
                self.autostart_status.setText("❌ 配置保存失败")
                return
            ok = _autostart.set_enabled(checked)
            self.autostart_status.setText(
                "✅ 已开启开机自启" if (checked and ok)
                else "已关闭开机自启" if not checked
                else "❌ 注册表写入失败")

        self.autostart_chk.toggled.connect(_on_autostart_toggled)

        # 加载配置（默认 True）并同步一次注册表
        self.autostart_chk.setChecked(bool(_load_cfg().get("auto_start", True)))
        _autostart.set_enabled(self.autostart_chk.isChecked())
        layout.addStretch()

    def _setup_local_config_tab(self, parent_widget):
        """本地配置 Tab：设置本地缓存/生成目录。"""
        from utils import config_manager as _cm

        layout = QVBoxLayout(parent_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("📁 本地缓存配置")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hint = QLabel("设置本地缓存目录，智能混剪、分割等生成的中间文件将统一存放在此目录下。")
        hint.setObjectName("muted_text")
        hint.setWordWrap(True)
        hint.setMaximumWidth(1400)  # 一行显示，右侧留白避让资源监控
        hdr.addWidget(hint)
        hdr.addStretch()
        layout.addLayout(hdr)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("缓存目录:"))
        self.local_cache_dir_input = QLineEdit()
        self.local_cache_dir_input.setPlaceholderText("默认为 outputs 目录，可自定义...")
        dir_row.addWidget(self.local_cache_dir_input, 1)
        btn_browse = mdi_button("浏览...", "folder")
        btn_browse.clicked.connect(lambda: self._browse_local_cache_dir())
        dir_row.addWidget(btn_browse)
        layout.addLayout(dir_row)

        self.local_cache_status = QLabel("")
        self.local_cache_status.setObjectName("muted_text")
        layout.addWidget(self.local_cache_status)

        # 加载已有配置
        cache_dir = _cm.get_setting("local_config", "cache_dir", "")
        if cache_dir:
            self.local_cache_dir_input.setText(cache_dir)
            self.local_cache_status.setText("已加载配置")

        btn_save = QPushButton("💾 保存")
        btn_save.setObjectName("primary_button")
        btn_save.setFixedWidth(90)
        btn_save.clicked.connect(lambda: self._save_local_config())

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)
        layout.addStretch()

    def _browse_local_cache_dir(self):
        d = pick_directory(self.local_cache_dir_input, "选择本地缓存目录")
        if d:
            self.local_cache_dir_input.setText(d)

    def _save_local_config(self):
        from utils import config_manager as _cm
        cache_dir = self.local_cache_dir_input.text().strip()
        try:
            _cm.set_setting("local_config", "cache_dir", cache_dir)
            self.local_cache_status.setText("✅ 已保存")
        except Exception as e:
            self.local_cache_status.setText(f"❌ 保存失败: {e}")

    def get_local_cache_dir(self):
        """获取配置的本地缓存目录，未配置返回空。"""
        from utils import config_manager as _cm
        try:
            d = _cm.get_setting("local_config", "cache_dir", "").strip()
            if d and os.path.isdir(d):
                return d
        except Exception:
            pass
        return ""

    def _setup_video_config_tab(self, parent_widget):
        """视频配置 Tab：管理 LUT 还原文件映射（文件名 → LUT 路径）。"""
        from config.paths import VIDEO_CONFIG_FILE
        import json as _json

        layout = QVBoxLayout(parent_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("🎬 视频 LUT 还原配置")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hint = QLabel("配置各相机/风格的 LUT 还原文件。在智能混剪镜头重组时可选择应用；格式支持：.cube / .3dl / .lut")
        hint.setObjectName("muted_text")
        hint.setMaximumWidth(1400)  # 一行显示，右侧留白避让资源监控
        hdr.addWidget(hint)
        hdr.addStretch()
        layout.addLayout(hdr)

        # 列表
        self.lut_list = QListWidget()
        self.lut_list.setAlternatingRowColors(True)
        layout.addWidget(self.lut_list, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_add = mdi_button("添加 LUT 文件", "folder")
        btn_add.setObjectName("primary_button")
        btn_add.clicked.connect(self._add_lut_entry)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("🗑 删除选中")
        btn_del.setObjectName("secondary_button")
        btn_del.clicked.connect(self._del_lut_entry)
        btn_row.addWidget(btn_del)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 状态
        self.lut_status = QLabel("")
        self.lut_status.setObjectName("muted_text")
        layout.addWidget(self.lut_status)

        # 加载已有配置
        self._load_lut_config()

    def _load_lut_config(self):
        from utils import config_manager as _cm
        self.lut_list.clear()
        data = _cm.load_config("video_config")
        try:
            for name, path in data.items():
                item = QListWidgetItem(f"{name}  →  {path}")
                item.setData(Qt.UserRole, {"name": name, "path": path})
                self.lut_list.addItem(item)
            self.lut_status.setText(f"已加载 {self.lut_list.count()} 个 LUT 配置")
        except Exception as e:
            self.lut_status.setText(f"加载失败: {e}")

    def _add_lut_entry(self):
        path, _ = pick_file(
            self.lut_list, "选择 LUT 还原文件", "",
            "LUT 文件 (*.cube *.3dl *.lut);;所有文件 (*.*)")
        if not path:
            return
        name = os.path.splitext(os.path.basename(path))[0]
        name, ok = QInputDialog.getText(self.lut_list, "LUT 名称",
                                         "输入此 LUT 的显示名称（如 S-Log3、D-Log）：",
                                         text=name)
        if not ok or not name.strip():
            return
        name = name.strip()
        # 写入列表
        item = QListWidgetItem(f"{name}  →  {path}")
        item.setData(Qt.UserRole, {"name": name, "path": path})
        self.lut_list.addItem(item)
        self._save_lut_config()

    def _del_lut_entry(self):
        for item in self.lut_list.selectedItems():
            self.lut_list.takeItem(self.lut_list.row(item))
        self._save_lut_config()

    def _save_lut_config(self):
        from utils import config_manager as _cm
        data = {}
        for i in range(self.lut_list.count()):
            item = self.lut_list.item(i)
            d = item.data(Qt.UserRole)
            if d:
                data[d["name"]] = d["path"]
        try:
            if not _cm.save_config("video_config", data):
                raise RuntimeError("写入失败")
            self.lut_status.setText(f"已保存 {len(data)} 个 LUT 配置")
        except Exception as e:
            self.lut_status.setText(f"保存失败: {e}")
