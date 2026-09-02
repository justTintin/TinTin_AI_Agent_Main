from gui.montage.base_step_view import BaseStepView
from gui.searchable_combo import SearchableComboBox
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)
from utils.gui_icons import mdi_button


class Step3VoiceView(BaseStepView):
    """步骤 3: 口播配音/克隆人声界面"""
    def __init__(self, main_page):
        super().__init__(main_page)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(8)

        # 1. Video Directory Row
        row_vid_dir = QHBoxLayout()
        row_vid_dir.setAlignment(Qt.AlignVCenter)
        row_vid_dir.addWidget(QLabel(" 视频输入目录:"))
        self.main_page.voice_video_dir_input = QLineEdit()
        self.main_page.voice_video_dir_input.setPlaceholderText("选择包含排列视频的目录...")
        self.main_page.voice_video_dir_input.textChanged.connect(self.main_page._on_voice_video_dir_changed)  # noqa: E501
        row_vid_dir.addWidget(self.main_page.voice_video_dir_input)

        btn_sel_vid_dir = mdi_button("选择目录", "folder")
        btn_sel_vid_dir.setObjectName("secondary_button")
        btn_sel_vid_dir.clicked.connect(self.main_page._select_voice_video_dir)
        row_vid_dir.addWidget(btn_sel_vid_dir)
        card_layout.addLayout(row_vid_dir)

        # 远程 TTS API 地址输入框（纯远程模式；保存时同步到 ai_config）
        # 初值跟随系统设置里的 vox_api_url（与 compute_server_url 一致），
        # 配置为空时用占位符提示，不写死任何地址。
        self.main_page.api_url_input = QLineEdit()
        try:
            _cfg = getattr(self.main_page.main_window, "ai_config", {}) or {}
        except (AttributeError, TypeError):
            _cfg = {}
        _saved_vox = (_cfg.get("vox_api_url") or "").strip()
        if _saved_vox:
            self.main_page.api_url_input.setText(_saved_vox)
        self.main_page.api_url_input.setPlaceholderText("跟随系统设置 → VoxCPM/TTS 地址（形如 http://<服务端>:8000/voxcpm/tts）")  # noqa: E501

        # 2a. Reference Voice Row
        row_voice = QHBoxLayout()
        row_voice.setSpacing(8)
        row_voice.setAlignment(Qt.AlignVCenter)
        row_voice.addWidget(QLabel(" 参考声音:"))

        self.main_page.ref_audio_combo = SearchableComboBox(placeholder="输入声音名称搜索…")
        self.main_page.ref_audio_combo.setView(QListView())
        self.main_page.ref_audio_combo.setMinimumWidth(160)
        self.main_page.ref_audio_combo.currentIndexChanged.connect(self.main_page._on_ref_audio_combo_changed)  # noqa: E501
        row_voice.addWidget(self.main_page.ref_audio_combo)

        self.main_page.btn_play_ref = mdi_button("", "volume")
        self.main_page.btn_play_ref.setToolTip("播放人声样本")
        self.main_page.btn_play_ref.setStyleSheet("padding: 0px; font-size: 14px;")
        self.main_page.btn_play_ref.setFixedWidth(30)
        self.main_page.btn_play_ref.setFixedHeight(30)
        self.main_page.btn_play_ref.setEnabled(False)
        self.main_page.btn_play_ref.clicked.connect(self.main_page._play_ref_audio)
        row_voice.addWidget(self.main_page.btn_play_ref)

        self.main_page.btn_upload_ref = mdi_button("上传声音", "folder")
        self.main_page.btn_upload_ref.setToolTip("上传本地音频文件作为参考声音 (wav/mp3/m4a)")
        self.main_page.btn_upload_ref.setObjectName("secondary_button")
        self.main_page.btn_upload_ref.setFixedHeight(30)
        self.main_page.btn_upload_ref.clicked.connect(self.main_page._select_ref_audio)
        row_voice.addWidget(self.main_page.btn_upload_ref)
        row_voice.addStretch(1)
        card_layout.addLayout(row_voice)

        # 2b. Reference Script Row
        row_ref_text = QHBoxLayout()
        row_ref_text.setSpacing(8)
        row_ref_text.setAlignment(Qt.AlignVCenter)
        row_ref_text.addWidget(QLabel(" 参考文案:"))
        self.main_page.ref_text_input = QLineEdit()
        self.main_page.ref_text_input.setPlaceholderText("可选，填入样本台词...")
        self.main_page.ref_text_input.setStyleSheet("""
            QLineEdit {
                background-color: #2c2c2e;
                border: 1px solid #3a3a3c;
                border-radius: 6px;
                padding: 4px 8px;
                color: #ffffff;
            }
        """)
        row_ref_text.addWidget(self.main_page.ref_text_input, 1)
        card_layout.addLayout(row_ref_text)

        # 3. TTS API 接口地址与推理参数
        row_server = QHBoxLayout()
        row_server.setSpacing(10)
        row_server.setAlignment(Qt.AlignVCenter)
        row_server.addWidget(QLabel(" TTS API:"))
        row_server.addWidget(self.main_page.api_url_input, 1)

        row_server.addSpacing(12)
        row_server.addWidget(QLabel("推理步数:"))
        self.main_page.tts_steps_spin = QSpinBox()
        self.main_page.tts_steps_spin.setRange(4, 50)
        self.main_page.tts_steps_spin.setValue(10)
        self.main_page.tts_steps_spin.setSingleStep(5)
        self.main_page.tts_steps_spin.setFixedWidth(52)
        self.main_page.tts_steps_spin.setToolTip(
            "VoxCPM 推理步数（4-30，默认10）\n"
            "步数越多音质越细腻，但速度越慢\n"
            "推荐：快速=10，高质量=20-30")
        row_server.addWidget(self.main_page.tts_steps_spin)

        row_server.addSpacing(8)
        row_server.addWidget(QLabel("CFG:"))
        self.main_page.tts_cfg_spin = QDoubleSpinBox()
        self.main_page.tts_cfg_spin.setRange(0.5, 5.0)
        self.main_page.tts_cfg_spin.setValue(2.0)
        self.main_page.tts_cfg_spin.setSingleStep(0.5)
        self.main_page.tts_cfg_spin.setDecimals(1)
        self.main_page.tts_cfg_spin.setFixedWidth(52)
        self.main_page.tts_cfg_spin.setToolTip(
            "引导强度（0.5-5.0，默认2.0）\n"
            "越高越贴近参考音色但可能过拟合\n"
            "推荐范围：1.5 - 3.0")
        row_server.addWidget(self.main_page.tts_cfg_spin)

        row_server.addSpacing(8)
        row_server.addWidget(QLabel("速率:"))
        self.main_page.tts_speed_min_spin = QDoubleSpinBox()
        self.main_page.tts_speed_min_spin.setRange(0.5, 1.0)
        self.main_page.tts_speed_min_spin.setValue(0.9)
        self.main_page.tts_speed_min_spin.setSingleStep(0.05)
        self.main_page.tts_speed_min_spin.setDecimals(2)
        self.main_page.tts_speed_min_spin.setFixedWidth(52)
        self.main_page.tts_speed_min_spin.setToolTip(
            "变速下限（默认0.90）\n"
            "音频比视频长时最多允许拉慢到此倍速\n"
            "超出范围时不再强制调速，保留自然音质")
        row_server.addWidget(self.main_page.tts_speed_min_spin)
        row_server.addWidget(QLabel("~"))

        self.main_page.tts_speed_max_spin = QDoubleSpinBox()
        self.main_page.tts_speed_max_spin.setRange(1.0, 2.0)
        self.main_page.tts_speed_max_spin.setValue(1.2)
        self.main_page.tts_speed_max_spin.setSingleStep(0.05)
        self.main_page.tts_speed_max_spin.setDecimals(2)
        self.main_page.tts_speed_max_spin.setFixedWidth(52)
        self.main_page.tts_speed_max_spin.setToolTip(
            "变速上限（默认1.20）\n"
            "音频比视频短时最多允许加速到此倍速\n"
            "超出范围时不再强制调速，保留自然音质")
        row_server.addWidget(self.main_page.tts_speed_max_spin)
        row_server.addStretch(1)
        card_layout.addLayout(row_server)

        # Videos and script table mapping
        row_table_title = QHBoxLayout()
        row_table_title.setContentsMargins(0, 4, 0, 4)
        lbl_title = QLabel(" 待合成视频列表与配音文案映射 (在配音文案栏直接输入):")
        lbl_title.setObjectName("card_title")
        row_table_title.addWidget(lbl_title)
        row_table_title.addStretch()

        self.main_page.btn_ai_rewrite_settings = mdi_button("文案生成设置", "gear")
        self.main_page.btn_ai_rewrite_settings.setObjectName("secondary_button")
        self.main_page.btn_ai_rewrite_settings.setStyleSheet("padding: 4px 10px; font-size: 12px;")  # noqa: E501
        self.main_page.btn_ai_rewrite_settings.clicked.connect(self.main_page._show_ai_rewrite_settings)  # noqa: E501
        row_table_title.addWidget(self.main_page.btn_ai_rewrite_settings)

        self.main_page.btn_batch_ai_rewrite = mdi_button("一键AI修改全部文案", "sparkles")
        self.main_page.btn_batch_ai_rewrite.setObjectName("action_button")
        self.main_page.btn_batch_ai_rewrite.setStyleSheet("padding: 4px 12px; font-size: 12px; font-weight: bold;")  # noqa: E501
        self.main_page.btn_batch_ai_rewrite.clicked.connect(self.main_page._batch_ai_rewrite_scripts)  # noqa: E501
        row_table_title.addWidget(self.main_page.btn_batch_ai_rewrite)
        card_layout.addLayout(row_table_title)

        self.main_page.voice_table = QTableWidget()
        self.main_page.voice_table.setWordWrap(False)
        self.main_page.voice_table.setColumnCount(2)
        self.main_page.voice_table.setHorizontalHeaderLabels(["序号", "视频/配音/文案/状态/操作"])
        self.main_page.voice_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # noqa: E501
        self.main_page.voice_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # noqa: E501
        self.main_page.voice_table.verticalHeader().setDefaultSectionSize(140)
        self.main_page.voice_table.verticalHeader().setMinimumSectionSize(90)
        self.main_page.voice_table.verticalHeader().setVisible(False)
        self.main_page.voice_table.setMinimumHeight(350)
        card_layout.addWidget(self.main_page.voice_table, 1)

        # Subtitle option checkbox
        row_subtitle_opt = QHBoxLayout()
        row_subtitle_opt.setSpacing(8)
        row_subtitle_opt.setAlignment(Qt.AlignVCenter)
        self.main_page.chk_add_subtitles = QCheckBox("烧制字幕（逐行按时间显示，字号随视频高度自适应，白色 50% 透明背景）")  # noqa: E501
        self.main_page.chk_add_subtitles.setChecked(False)
        self.main_page.chk_add_subtitles.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.main_page.chk_add_subtitles.setToolTip(
            "字幕字体取自服务端字体库（GET /config/fonts）。\n"
            "走服务端合成时，会把 font_id / fontname / burn_subtitle 一并提交给服务端烧制；\n"
            "服务端尚未支持该参数时，回退到本地 ffmpeg 烧制（按同名解析本机已装字体）。")
        row_subtitle_opt.addWidget(self.main_page.chk_add_subtitles)

        row_subtitle_opt.addSpacing(12)
        row_subtitle_opt.addWidget(QLabel("字幕字体:"))
        self.main_page.subtitle_font_combo = SearchableComboBox(placeholder="输入字体名搜索…")  # noqa: E501
        self.main_page.subtitle_font_combo.setMinimumWidth(230)
        self.main_page.subtitle_font_combo.setToolTip("字体列表来自服务端 /config/fonts，可输入关键字过滤")  # noqa: E501
        row_subtitle_opt.addWidget(self.main_page.subtitle_font_combo)

        self.main_page.btn_refresh_fonts = mdi_button("刷新字体", "refresh")
        self.main_page.btn_refresh_fonts.setObjectName("secondary_button")
        self.main_page.btn_refresh_fonts.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        self.main_page.btn_refresh_fonts.setToolTip("重新从服务端拉取字体列表")
        self.main_page.btn_refresh_fonts.clicked.connect(self.main_page._refresh_server_fonts)  # noqa: E501
        row_subtitle_opt.addWidget(self.main_page.btn_refresh_fonts)
        row_subtitle_opt.addStretch()
        card_layout.addLayout(row_subtitle_opt)

        # 花字选项
        row_fancy_text = QHBoxLayout()
        self.main_page.chk_fancy_text = QCheckBox("添加花字 (关键信息加重提醒)")
        self.main_page.chk_fancy_text.setChecked(False)
        self.main_page.chk_fancy_text.setStyleSheet("font-size: 13px; font-weight: bold;")  # noqa: E501
        self.main_page.chk_fancy_text.setToolTip("在视频画面中央叠加花字特效文字，用于突出关键卖点/价格/型号等信息")
        row_fancy_text.addWidget(self.main_page.chk_fancy_text)

        row_fancy_text.addWidget(QLabel("样式:"))
        self.main_page.fancy_style_combo = QComboBox()
        self.main_page.fancy_style_combo.addItem("渐变金", "gold")
        self.main_page.fancy_style_combo.addItem("渐变红", "red")
        self.main_page.fancy_style_combo.addItem("渐变蓝", "blue")
        self.main_page.fancy_style_combo.addItem("渐变紫", "purple")
        self.main_page.fancy_style_combo.addItem("霓虹绿", "neon_green")
        self.main_page.fancy_style_combo.addItem("白字黑描边", "white_outline")
        self.main_page.fancy_style_combo.addItem("黄字红描边", "yellow_red")
        self.main_page.fancy_style_combo.setCurrentIndex(0)
        self.main_page.fancy_style_combo.setFixedWidth(110)
        row_fancy_text.addWidget(self.main_page.fancy_style_combo)

        row_fancy_text.addWidget(QLabel("花字内容:"))
        self.main_page.fancy_text_input = QLineEdit()
        self.main_page.fancy_text_input.setPlaceholderText("输入要叠加的花字内容，多行用逗号分隔（按镜头顺序轮换）")  # noqa: E501
        self.main_page.fancy_text_input.setToolTip("多个花字用逗号分隔，会按镜头顺序轮换显示。如：超轻量化,8000DPI,续航70小时")  # noqa: E501
        row_fancy_text.addWidget(self.main_page.fancy_text_input, 1)
        card_layout.addLayout(row_fancy_text)

        # Actions
        row_actions = QHBoxLayout()
        self.main_page.btn_synthesize_voice = mdi_button("开始批量克隆人声合成", "voice")
        self.main_page.btn_synthesize_voice.setObjectName("action_button")
        self.main_page.btn_synthesize_voice.setFixedHeight(35)
        self.main_page.btn_synthesize_voice.clicked.connect(self.main_page._start_synthesize_voice)  # noqa: E501
        row_actions.addWidget(self.main_page.btn_synthesize_voice, 2)

        self.main_page.btn_dub_videos = mdi_button("开始给视频配音 (替换原声)", "video")
        self.main_page.btn_dub_videos.setObjectName("primary_button")
        self.main_page.btn_dub_videos.setFixedHeight(35)
        self.main_page.btn_dub_videos.clicked.connect(self.main_page._start_dubbing_videos)  # noqa: E501
        self.main_page.btn_dub_videos.setEnabled(False)
        row_actions.addWidget(self.main_page.btn_dub_videos, 3)
        card_layout.addLayout(row_actions)
        layout.addWidget(card, 1)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：镜头重组", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self.main_page._go_to_step(1))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.main_page.btn_next_to_step_4 = mdi_button("下一步：特效包装", "right")
        self.main_page.btn_next_to_step_4.setObjectName("primary_button")
        self.main_page.btn_next_to_step_4.setEnabled(True)
        self.main_page.btn_next_to_step_4.clicked.connect(lambda: self.main_page._go_to_step(3))  # noqa: E501
        nav_row.addWidget(self.main_page.btn_next_to_step_4)
        layout.addLayout(nav_row)
