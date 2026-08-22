from gui.montage.base_step_view import BaseStepView
from PySide6.QtCore import Qt
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.gui_icons import mdi_button


class Step2ConcatView(BaseStepView):
    """步骤 2: 镜头重组界面"""
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
        card_layout.setSpacing(16)

        # ── 参数设置组（统一边框背景）──
        params_group = QFrame()
        params_group.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12); "  # noqa: E501
            "border-radius: 6px; }")
        params_group_layout = QVBoxLayout(params_group)
        params_group_layout.setContentsMargins(12, 10, 12, 10)
        params_group_layout.setSpacing(10)

        # Parameters row 1
        row_params1 = QHBoxLayout()
        row_params1.addWidget(QLabel("排列逻辑:"))
        self.main_page.logic_combo = QComboBox()
        self.main_page.logic_combo.addItem("智能重排", "random")
        # self.main_page.logic_combo.addItem(" 按文案智能匹配", "script")  # 暂时隐藏
        self.main_page.logic_combo.setToolTip(
            "智能重排：镜头智能排列组合。")
        self.main_page.logic_combo.currentIndexChanged.connect(self.main_page._on_logic_combo_changed)  # noqa: E501
        row_params1.addWidget(self.main_page.logic_combo)

        row_params1.addSpacing(15)
        row_params1.addWidget(QLabel("输出画幅:"))
        self.main_page.layout_combo = QComboBox()
        self.main_page.layout_combo.addItem("与原视频一致", "source")
        self.main_page.layout_combo.addItem("竖屏 (1080x1920 抖音流)", "vertical")
        self.main_page.layout_combo.addItem("横屏 (1920x1080 宽屏)", "horizontal")
        self.main_page.layout_combo.setCurrentIndex(0)
        row_params1.addWidget(self.main_page.layout_combo)

        row_params1.addSpacing(15)
        self.main_page.lbl_duration_limit = QLabel("时长限制:")
        row_params1.addWidget(self.main_page.lbl_duration_limit)
        self.main_page.duration_limit_combo = QComboBox()
        for sec in [10, 20, 30, 40, 50]:
            self.main_page.duration_limit_combo.addItem(f"{sec} 秒", sec)
        self.main_page.duration_limit_combo.setCurrentIndex(2)  # 默认 30 秒
        self.main_page.duration_limit_combo.setFixedWidth(80)
        self.main_page.duration_limit_combo.setToolTip("每个预合成视频的总时长上限（实际不超此值的 1.1 倍）")
        row_params1.addWidget(self.main_page.duration_limit_combo)

        row_params1.addSpacing(15)
        self.main_page.lbl_batch_count = QLabel("生成视频数量 (1-10):")
        row_params1.addWidget(self.main_page.lbl_batch_count)
        self.main_page.batch_count_spin = QSpinBox()
        self.main_page.batch_count_spin.setRange(1, 10)
        self.main_page.batch_count_spin.setValue(3)
        self.main_page.batch_count_spin.setFixedWidth(60)
        row_params1.addWidget(self.main_page.batch_count_spin)
        self.main_page.batch_count_hint_lbl = QLabel("推荐: 1")
        self.main_page.batch_count_hint_lbl.setObjectName("muted_text")
        row_params1.addWidget(self.main_page.batch_count_hint_lbl)

        row_params1.addSpacing(15)
        self.main_page.lbl_randomness = QLabel("混编随机度:")
        row_params1.addWidget(self.main_page.lbl_randomness)
        self.main_page.randomness_combo = QComboBox()
        self.main_page.randomness_combo.addItem("中 (保留同场景)", "medium")
        self.main_page.randomness_combo.addItem("高 (全随机)", "high")
        self.main_page.randomness_combo.addItem("低 (顺序无随机)", "low")
        self.main_page.randomness_combo.setCurrentIndex(0)
        row_params1.addWidget(self.main_page.randomness_combo)
        self.main_page.lbl_randomness.setVisible(False)
        self.main_page.randomness_combo.setVisible(False)

        row_params1.addStretch()
        params_group_layout.addLayout(row_params1)

        # Parameters row 2
        row_params2 = QHBoxLayout()
        row_params2.addWidget(QLabel("转场动画:"))
        self.main_page.transition_combo = QComboBox()
        self.main_page.transition_combo.addItem("模糊", "fade")
        self.main_page.transition_combo.addItem("淡入淡出", "dissolve")
        self.main_page.transition_combo.addItem("左移", "slideleft")
        self.main_page.transition_combo.addItem("右移", "slideright")
        self.main_page.transition_combo.addItem("上移", "slideup")
        self.main_page.transition_combo.addItem("下移", "slidedown")
        self.main_page.transition_combo.addItem("推进", "zoomin")
        self.main_page.transition_combo.addItem("拉远", "zoomout")
        self.main_page.transition_combo.setCurrentIndex(0)
        self.main_page.transition_combo.setFixedWidth(100)
        self.main_page.transition_combo.setToolTip("镜头之间的转场动画效果（剪映常用转场）")
        row_params2.addWidget(self.main_page.transition_combo)
        row_params2.addStretch()
        params_group_layout.addLayout(row_params2)

        card_layout.addWidget(params_group)

        # 智能匹配模式的口播文案输入框
        self.main_page.match_script_edit = QTextEdit()
        self.main_page.match_script_edit.setPlaceholderText(
            "粘贴口播文案，每行一句。\n"
            "智能匹配将为每一行文案从勾选的镜头中挑选画面最贴合的一个，并按行序排列成片。\n"
            "示例：\n这款鼠标采用轻量化设计\n8000DPI 电竞级传感器\n续航长达 70 小时")
        self.main_page.match_script_edit.setFixedHeight(96)
        self.main_page.match_script_edit.setVisible(False)
        card_layout.addWidget(self.main_page.match_script_edit)

        # ── 脚本工具栏：待排列镜头个数 + AI 生成文案 + 镜头重组（两种模式共用）──
        script_toolbar = QHBoxLayout()
        self.main_page.clip_count_info_lbl = QLabel("待排列镜头个数: 0  (已勾选: 0)")
        self.main_page.clip_count_info_lbl.setStyleSheet("font-weight: bold; font-size: 11pt; color: #f1c40f;")  # noqa: E501
        script_toolbar.addWidget(self.main_page.clip_count_info_lbl)
        script_toolbar.addSpacing(20)
        self.main_page.btn_gen_script = mdi_button(" AI 生成文案", "sparkles")
        self.main_page.btn_gen_script.setObjectName("primary_button")
        self.main_page.btn_gen_script.setFixedHeight(35)
        self.main_page.btn_gen_script.setToolTip("根据已勾选的镜头素材描述，调用大模型自动生成口播文案（受时长限制约束）")
        self.main_page.btn_gen_script.clicked.connect(self.main_page._on_gen_script_clicked)  # noqa: E501
        self.main_page.btn_gen_script.setVisible(False)
        script_toolbar.addWidget(self.main_page.btn_gen_script)
        script_toolbar.addStretch()
        self.main_page.btn_assemble_video = mdi_button("镜头重组", "video")
        self.main_page.btn_assemble_video.setObjectName("action_button")
        self.main_page.btn_assemble_video.setFixedHeight(35)
        self.main_page.btn_assemble_video.clicked.connect(self.main_page._start_assemble_video)  # noqa: E501
        script_toolbar.addWidget(self.main_page.btn_assemble_video)
        card_layout.addLayout(script_toolbar)

        # Intermediate result viewer
        result_box = QFrame()
        result_box.setStyleSheet("background-color: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.1); border-radius: 4px;")  # noqa: E501
        res_layout = QHBoxLayout(result_box)
        res_layout.setContentsMargins(10, 10, 10, 10)
        res_layout.setSpacing(15)

        # Left Column: Lists and Tables
        left_container = QWidget()
        left_vbox = QVBoxLayout(left_container)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(10)

        assembled_header = QHBoxLayout()
        assembled_header.setContentsMargins(0, 0, 0, 0)
        assembled_header.addWidget(QLabel("预合成视频列表 (双击播放预览，单击选中查看镜头):"), 1)
        left_vbox.addLayout(assembled_header)

        self.main_page.assembled_clips_list_widget = QListWidget()
        self.main_page.assembled_clips_list_widget.setMinimumHeight(180)
        self.main_page.assembled_clips_list_widget.setTextElideMode(Qt.ElideRight)
        self.main_page.assembled_clips_list_widget.itemDoubleClicked.connect(self.main_page._on_assembled_double_clicked)  # noqa: E501
        self.main_page.assembled_clips_list_widget.itemClicked.connect(self.main_page._on_assembled_item_clicked)  # noqa: E501
        self.main_page.assembled_clips_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)  # noqa: E501
        self.main_page.assembled_clips_list_widget.customContextMenuRequested.connect(self.main_page._show_assembled_context_menu)  # noqa: E501
        left_vbox.addWidget(self.main_page.assembled_clips_list_widget)

        left_vbox.addWidget(QLabel(" 视频组成镜头详情 (拖动把手调序，右键删除/恢复镜头):"))

        # 引用 ReorderableClipsTable (由于是在主页面导入，主页面 setup 会对其进行实例化赋给 sources_detail_widget)  # noqa: E501
        # 这里我们在主页面中对其进行初始化：
        # 我们在这里先创建一个占位符容器，由主页面注入
        self.detail_container = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_container)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        left_vbox.addWidget(self.detail_container)

        # Right Column: Video Preview Player
        player_container = QWidget()
        player_container.setStyleSheet("background-color: #000000; border-radius: 6px; border: 1px solid #27272a;")  # noqa: E501
        player_vbox = QVBoxLayout(player_container)
        player_vbox.setContentsMargins(6, 6, 6, 6)
        player_vbox.setSpacing(6)

        self.main_page.preview_title = QLabel(" 视频播放预览")
        self.main_page.preview_title.setObjectName("muted_text")
        player_vbox.addWidget(self.main_page.preview_title)

        self.main_page.preview_video_widget = QVideoWidget()
        # 自动识别视频比例，等比完整显示（不拉伸、不裁剪）
        self.main_page.preview_video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.main_page.preview_video_widget.setMinimumHeight(200)
        player_vbox.addWidget(self.main_page.preview_video_widget, 1)

        self.main_page.preview_overlay_label = QLabel("#1")
        self.main_page.preview_overlay_label.setParent(self.main_page.preview_video_widget)  # noqa: E501
        self.main_page.preview_overlay_label.move(8, 8)
        self.main_page.preview_overlay_label.setStyleSheet(
            "background-color: rgba(0,0,0,0.55); color: #f8fafc; "
            "border: 1px solid rgba(255,255,255,0.22); border-radius: 10px; "
            "padding: 2px 8px; font-size: 12px; font-weight: bold;")
        self.main_page.preview_overlay_label.hide()

        player_controls = QHBoxLayout()
        player_controls.setSpacing(6)
        self.main_page.btn_preview_play = mdi_button("", "play")
        self.main_page.btn_preview_play.setFixedWidth(44)
        self.main_page.btn_preview_play.setFixedHeight(24)
        self.main_page.btn_preview_play.setStyleSheet("padding: 0px; font-size: 14px;")
        self.main_page.btn_preview_play.setToolTip("播放/暂停")
        self.main_page.btn_preview_play.clicked.connect(self.main_page._toggle_preview_video)  # noqa: E501
        player_controls.addWidget(self.main_page.btn_preview_play)

        self.main_page.preview_slider = QSlider(Qt.Horizontal)
        self.main_page.preview_slider.setRange(0, 0)
        self.main_page.preview_slider.setFixedHeight(20)
        self.main_page.preview_slider.sliderMoved.connect(self.main_page._set_preview_position)  # noqa: E501
        player_controls.addWidget(self.main_page.preview_slider)

        player_vbox.addLayout(player_controls)

        res_layout.addWidget(left_container, 3)
        res_layout.addWidget(player_container, 1)

        # Wire preview player components on main page
        self.main_page.preview_player.setVideoOutput(self.main_page.preview_video_widget)  # noqa: E501
        self.main_page.preview_player.positionChanged.connect(self.main_page._on_preview_position_changed)  # noqa: E501
        self.main_page.preview_player.durationChanged.connect(self.main_page._on_preview_duration_changed)  # noqa: E501
        self.main_page.preview_player.mediaStatusChanged.connect(self.main_page._on_preview_media_status_changed)  # noqa: E501

        card_layout.addWidget(result_box)
        layout.addWidget(card, 1)

        # Confirm row
        confirm_row = QHBoxLayout()
        self.main_page.btn_confirm_all = QPushButton("确认合成视频")
        self.main_page.btn_confirm_all.setObjectName("action_button")
        self.main_page.btn_confirm_all.setFixedHeight(35)
        self.main_page.btn_confirm_all.setEnabled(False)
        self.main_page.btn_confirm_all.clicked.connect(self.main_page._confirm_all_precompose)  # noqa: E501
        confirm_row.addWidget(self.main_page.btn_confirm_all)

        self.main_page.btn_batch_scene_copy = QPushButton("生成口播文案")
        self.main_page.btn_batch_scene_copy.setObjectName("secondary_button")
        self.main_page.btn_batch_scene_copy.setFixedHeight(35)
        self.main_page.btn_batch_scene_copy.setToolTip(
            "为列表中所有组合视频，按各自的画面镜头描述自动生成口播文案"
            "（共用同一份产品背景，保存为同名 .txt，下一步配音自动载入）")
        self.main_page.btn_batch_scene_copy.clicked.connect(self.main_page._batch_gen_copy_by_scene)  # noqa: E501
        self.main_page.btn_batch_scene_copy.setEnabled(False)
        confirm_row.addWidget(self.main_page.btn_batch_scene_copy, 0)
        layout.addLayout(confirm_row)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：镜头分割", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self.main_page._go_to_step(0))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.main_page.btn_next_to_step_3 = mdi_button("下一步：克隆口播", "right")
        self.main_page.btn_next_to_step_3.setObjectName("primary_button")
        self.main_page.btn_next_to_step_3.setEnabled(False)
        self.main_page.btn_next_to_step_3.clicked.connect(lambda: self.main_page._go_to_step(2))  # noqa: E501
        nav_row.addWidget(self.main_page.btn_next_to_step_3)
        layout.addLayout(nav_row)

        # 加载 LUT 配置到下拉框
        self.main_page._load_lut_combo()
