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
        self.main_page.chk_add_subtitles = QCheckBox("烧制字幕（逐行按时间显示，字号随视频高度自适应）")  # noqa: E501
        self.main_page.chk_add_subtitles.setChecked(False)
        self.main_page.chk_add_subtitles.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.main_page.chk_add_subtitles.setToolTip(
            "字幕字体取自服务端字体库（GET /config/fonts）。\n"
            "走服务端合成时，会把 font_id / fontname / burn_subtitle / subtitle_style 一并提交；\n"
            "服务端尚未支持该参数时，回退到本地 ffmpeg 烧制（按同名解析本机已装字体）。")
        row_subtitle_opt.addWidget(self.main_page.chk_add_subtitles)

        row_subtitle_opt.addSpacing(12)
        row_subtitle_opt.addWidget(QLabel("背景:"))
        self.main_page.subtitle_bg_combo = QComboBox()
        for _txt, _val in (("无背景", 0.0), ("20% 透明黑", 0.2), ("35% 透明黑", 0.35),
                           ("50% 透明黑 (默认)", 0.5), ("65% 透明黑", 0.65),
                           ("80% 透明黑", 0.8)):
            self.main_page.subtitle_bg_combo.addItem(_txt, _val)
        self.main_page.subtitle_bg_combo.setCurrentIndex(3)
        self.main_page.subtitle_bg_combo.setFixedWidth(130)
        self.main_page.subtitle_bg_combo.setToolTip(
            "字幕背景色为黑色，此项调背景不透明度（0=无背景框）。\n"
            "值越高背景越实；走服务端合成时随 subtitle_style 一并提交。")
        row_subtitle_opt.addWidget(self.main_page.subtitle_bg_combo)

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
        # 勾选状态变化 → 刷新所有行的花字预览提示
        self.main_page.chk_fancy_text.toggled.connect(
            self.main_page._refresh_all_fancy_previews)
        self.main_page.chk_fancy_text.setToolTip(
            "在视频画面叠加花字特效文字（可选出现位置），用于突出关键卖点/价格/型号等信息。\n"
            "花字内容自动从口播文案中逐行提取卖点（价格 > 数字参数 > 关键词），无需手动输入；\n"
            "每个花字随对应字幕提前 0.3 秒出现、该句字幕结束即消失。")
        row_fancy_text.addWidget(self.main_page.chk_fancy_text)

        row_fancy_text.addWidget(QLabel("模板:"))
        self.main_page.fancy_template_combo = QComboBox()
        self.main_page.fancy_template_combo.addItem("自定义 (下方样式)", None)
        from utils.fancy_templates import list_fancy_templates
        for _tpl in list_fancy_templates(force_reload=True):
            self.main_page.fancy_template_combo.addItem(
                _tpl["name"], _tpl.get("template_id"))
        self.main_page.fancy_template_combo.setCurrentIndex(0)
        self.main_page.fancy_template_combo.setFixedWidth(130)
        self.main_page.fancy_template_combo.setToolTip(
            "花字模板 = 样式 + 入场动画 + 出现音效 + 出现时机。\n"
            "选「自定义」时用下方样式/位置；选模板时以模板样式为准。\n"
            "模板的剪映入场动画映射为本地动画（滑→滑入、弹/跳/晃/摆→弹跳、\n"
            "其它→淡入）；右侧预览标签展示渲染效果。\n"
            "模板文件在 assets/fancy/templates/，可把剪映提取的 effect_id 填入新增模板。")
        row_fancy_text.addWidget(self.main_page.fancy_template_combo)

        # 模板预览标签：当前选中模板的样式渲染图（后台 ffmpeg 生成，所见即所得）
        self.main_page.fancy_template_preview_lbl = QLabel("预览生成中…")
        self.main_page.fancy_template_preview_lbl.setFixedSize(124, 34)
        self.main_page.fancy_template_preview_lbl.setAlignment(Qt.AlignCenter)
        self.main_page.fancy_template_preview_lbl.setStyleSheet(
            "background-color: #202020; color: #666; font-size: 10px; border-radius: 3px;")  # noqa: E501
        self.main_page.fancy_template_preview_lbl.setToolTip(
            "花字模板预览（按模板样式渲染样本字）；悬停查看动画/音效/时机信息。")
        row_fancy_text.addWidget(self.main_page.fancy_template_preview_lbl)
        self.main_page.fancy_template_combo.currentIndexChanged.connect(
            self.main_page._update_fancy_template_preview)
        # 后台生成预览图（已有缓存直接回填；缺失的 ffmpeg 渲染后刷新）
        self.main_page._start_fancy_preview_loader()

        # 模板同步：把本机花字模板包增量上传到服务端模板库（3.3，未部署时提示）
        self.main_page.btn_sync_fancy_server = mdi_button("同步服务端", "upload")
        self.main_page.btn_sync_fancy_server.setObjectName("secondary_button")
        self.main_page.btn_sync_fancy_server.setStyleSheet("padding: 4px 10px; font-size: 12px;")  # noqa: E501
        self.main_page.btn_sync_fancy_server.setToolTip(
            "把本机花字模板包批量上传到服务端模板库（POST /fancy/templates，增量同步）。\n"
            "服务端按 docs/服务端花字烧制需求.md 3.3 实现后生效；未部署时会提示。")
        self.main_page.btn_sync_fancy_server.clicked.connect(
            self.main_page._sync_fancy_templates_to_server)
        row_fancy_text.addWidget(self.main_page.btn_sync_fancy_server)

        # 花字预览：按每个视频当前文案，弹窗展示将生成的花字（与烧制同一提取逻辑）
        self.main_page.btn_preview_fancy = mdi_button("花字预览", "eye")
        self.main_page.btn_preview_fancy.setObjectName("secondary_button")
        self.main_page.btn_preview_fancy.setStyleSheet("padding: 4px 10px; font-size: 12px;")  # noqa: E501
        self.main_page.btn_preview_fancy.setToolTip(
            "按每个视频当前的口播文案预览将生成的花字（自动提取卖点）。\n"
            "文案改动后重新点击即可刷新。")
        self.main_page.btn_preview_fancy.clicked.connect(
            self.main_page._preview_fancy_words)
        row_fancy_text.addWidget(self.main_page.btn_preview_fancy)

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

        row_fancy_text.addWidget(QLabel("位置:"))
        self.main_page.fancy_position_combo = QComboBox()
        for _txt, _val in (("中上 (默认)", "upper_middle"), ("顶部居中", "top"),
                           ("画面正中", "center"), ("底部居中", "bottom"),
                           ("左上角", "top_left"), ("右上角", "top_right"),
                           ("左下角", "bottom_left"), ("右下角", "bottom_right")):
            self.main_page.fancy_position_combo.addItem(_txt, _val)
        self.main_page.fancy_position_combo.setCurrentIndex(0)
        self.main_page.fancy_position_combo.setFixedWidth(110)
        self.main_page.fancy_position_combo.setToolTip(
            "花字在画面中出现的位置。\n"
            "底部两个位置与逐行字幕可能重叠，字幕开启时建议选顶部/中上/四角。")
        row_fancy_text.addWidget(self.main_page.fancy_position_combo)

        row_fancy_text.addWidget(QLabel("花字内容:"))
        # 花字内容不再手动输入：渲染时自动从口播文案逐行提取卖点（concat_workers.extract_fancy_word）
        self.main_page.fancy_content_label = QLabel(
            "自动提取口播文案卖点（价格/数字参数/关键词），随对应字幕提前 0.3 秒出现、字幕结束消失")  # noqa: E501
        self.main_page.fancy_content_label.setStyleSheet("color: #888; font-size: 12px;")
        row_fancy_text.addWidget(self.main_page.fancy_content_label, 1)
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
