# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QFrame, QListWidget, QWidget, QSlider)
from PySide6.QtCore import Qt
from PySide6.QtMultimediaWidgets import QVideoWidget
from gui.montage.base_step_view import BaseStepView
from utils.gui_icons import mdi_button

class Step4FinalView(BaseStepView):
    """步骤 4: 最终音视频合成与剪映草稿导出界面"""
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
        card_layout.setSpacing(12)

        # 1. BGM input
        row_bgm = QHBoxLayout()
        row_bgm.addWidget(QLabel("🎵 背景音乐 (BGM):"))
        self.main_page.bgm_input = QLineEdit()
        self.main_page.bgm_input.setPlaceholderText("选择混剪背景音乐 (mp3/wav)，选空则无BGM...")
        self.main_page.bgm_input.setReadOnly(True)
        row_bgm.addWidget(self.main_page.bgm_input)
        
        btn_sel_bgm = mdi_button("选择背景音乐", "folder")
        btn_sel_bgm.setObjectName("secondary_button")
        btn_sel_bgm.clicked.connect(self.main_page._select_bgm)
        row_bgm.addWidget(btn_sel_bgm)
        card_layout.addLayout(row_bgm)

        # BGM parameters slider (gain)：100%=原音量，可放大到200%，可减到0%
        row_vol = QHBoxLayout()
        row_vol.addWidget(QLabel(" BGM 增益 (0-200%, 100%=原音量):"))
        self.main_page.bgm_volume_slider = QSlider(Qt.Horizontal)
        self.main_page.bgm_volume_slider.setRange(0, 200)
        self.main_page.bgm_volume_slider.setValue(100)
        self.main_page.bgm_volume_slider.setFixedWidth(200)

        self.main_page.lbl_bgm_vol = QLabel("100 %")
        self.main_page.lbl_bgm_vol.setFixedWidth(50)
        # valueChanged：既更新标签，又实时改变播放音量（拖动即生效）
        self.main_page.bgm_volume_slider.valueChanged.connect(
            lambda v: self.main_page.lbl_bgm_vol.setText(f"{v} %")
        )
        self.main_page.bgm_volume_slider.valueChanged.connect(
            self.main_page._on_bgm_volume_changed
        )
        row_vol.addWidget(self.main_page.bgm_volume_slider)
        row_vol.addWidget(self.main_page.lbl_bgm_vol)
        row_vol.addStretch()
        card_layout.addLayout(row_vol)

        # BGM Player control & progress
        row_bgm_play = QHBoxLayout()
        row_bgm_play.setSpacing(8)
        self.main_page.btn_bgm_play = mdi_button("", "play")
        self.main_page.btn_bgm_play.setFixedWidth(56)
        self.main_page.btn_bgm_play.setFixedHeight(28)
        self.main_page.btn_bgm_play.setToolTip("播放/暂停")
        self.main_page.btn_bgm_play.clicked.connect(self.main_page._toggle_bgm_play)
        row_bgm_play.addWidget(self.main_page.btn_bgm_play)

        self.main_page.btn_bgm_stop = mdi_button("", "stop")
        self.main_page.btn_bgm_stop.setFixedWidth(56)
        self.main_page.btn_bgm_stop.setFixedHeight(28)
        self.main_page.btn_bgm_stop.setToolTip("停止播放")
        self.main_page.btn_bgm_stop.clicked.connect(self.main_page._stop_bgm_play)
        row_bgm_play.addWidget(self.main_page.btn_bgm_stop)

        self.main_page.bgm_progress_slider = QSlider(Qt.Horizontal)
        self.main_page.bgm_progress_slider.setRange(0, 0)
        self.main_page.bgm_progress_slider.setFixedHeight(20)
        self.main_page.bgm_progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #27272a;
            }
            QSlider::handle:horizontal {
                background: #3b82f6;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
        """)
        row_bgm_play.addWidget(self.main_page.bgm_progress_slider)
        
        # Connect position and duration signals for the BGM preview player
        self.main_page._bgm_player.positionChanged.connect(self.main_page._on_bgm_position_changed)
        self.main_page._bgm_player.durationChanged.connect(self.main_page._on_bgm_duration_changed)
        self.main_page.bgm_progress_slider.sliderMoved.connect(self.main_page._set_bgm_position)

        self.main_page.lbl_bgm_time = QLabel("00:00 / 00:00")
        self.main_page.lbl_bgm_time.setFixedWidth(90)
        self.main_page.lbl_bgm_time.setAlignment(Qt.AlignCenter)
        self.main_page.lbl_bgm_time.setObjectName("muted_text")
        row_bgm_play.addWidget(self.main_page.lbl_bgm_time)
        card_layout.addLayout(row_bgm_play)

        # Run Final mix
        self.main_page.btn_final_assemble = mdi_button("开始混音合成", "celebration")
        self.main_page.btn_final_assemble.setObjectName("action_button")
        self.main_page.btn_final_assemble.setFixedHeight(40)
        self.main_page.btn_final_assemble.clicked.connect(self.main_page._start_final_mix)
        card_layout.addWidget(self.main_page.btn_final_assemble)

        # Output results
        result_box = QFrame()
        result_box.setStyleSheet("background-color: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px;")
        res_layout = QHBoxLayout(result_box)
        res_layout.setContentsMargins(10, 10, 10, 10)
        res_layout.setSpacing(12)

        # Left: final video list
        left_container = QWidget()
        left_vbox = QVBoxLayout(left_container)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(6)

        left_vbox.addWidget(QLabel("最终合成生成的视频文件:"))
        self.main_page.final_video_list = QListWidget()
        self.main_page.final_video_list.setFixedHeight(150)
        self.main_page.final_video_list.itemDoubleClicked.connect(self.main_page._preview_final_video)
        left_vbox.addWidget(self.main_page.final_video_list)

        # Action layout for buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.main_page.btn_open_final_dir = mdi_button("打开视频输出目录", "folder")
        self.main_page.btn_open_final_dir.setObjectName("secondary_button")
        self.main_page.btn_open_final_dir.setEnabled(False)
        self.main_page.btn_open_final_dir.clicked.connect(self.main_page._open_output_dir)
        btn_layout.addWidget(self.main_page.btn_open_final_dir, 1)

        # 新增按钮：导出剪映专业版草稿
        self.main_page.btn_export_jianying = mdi_button("一键导出到剪映草稿", "share")
        self.main_page.btn_export_jianying.setObjectName("primary_button")
        self.main_page.btn_export_jianying.setEnabled(False)
        self.main_page.btn_export_jianying.clicked.connect(self.main_page._export_to_jianying_draft)
        btn_layout.addWidget(self.main_page.btn_export_jianying, 1)
        # 新增按钮：导出全部到时间轴（带转场）
        self.main_page.btn_export_jianying_all = mdi_button("导出全部到时间轴(带转场)", "film")
        self.main_page.btn_export_jianying_all.setObjectName("secondary_button")
        self.main_page.btn_export_jianying_all.setEnabled(False)
        self.main_page.btn_export_jianying_all.setToolTip("将合成列表中的所有视频按顺序导出为一条剪映时间轴，片段之间自动添加所选转场，每个片段携带各自字幕")
        self.main_page.btn_export_jianying_all.clicked.connect(self.main_page._export_all_to_jianying_draft)
        btn_layout.addWidget(self.main_page.btn_export_jianying_all, 1)

        left_vbox.addLayout(btn_layout)

        # Right: video preview
        right_container = QWidget()
        right_container.setStyleSheet("background-color: #000000; border-radius: 6px; border: 1px solid #27272a;")
        right_vbox = QVBoxLayout(right_container)
        right_vbox.setContentsMargins(4, 4, 4, 4)
        right_vbox.setSpacing(4)

        self.main_page.final_preview_title = QLabel("🎥 视频预览")
        self.main_page.final_preview_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        right_vbox.addWidget(self.main_page.final_preview_title)

        self.main_page.final_video_widget = QVideoWidget()
        # 自动识别视频比例，等比完整显示
        self.main_page.final_video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.main_page.final_video_widget.setMinimumHeight(150)
        right_vbox.addWidget(self.main_page.final_video_widget, 1)

        # Connect preview output
        self.main_page.final_preview_player.setVideoOutput(self.main_page.final_video_widget)

        res_layout.addWidget(left_container, 1)
        res_layout.addWidget(right_container, 1)
        card_layout.addWidget(result_box)
        
        card_layout.addStretch()
        layout.addWidget(card, 1)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：克隆人声", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self.main_page._go_to_step(2))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()
        layout.addLayout(nav_row)
