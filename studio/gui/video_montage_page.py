# -*- coding: utf-8 -*-
"""
智能混剪主页面（控制器层）。

本文件原为 8800+ 行的单体文件，现将可复用部分拆分至 gui/montage/ 子包：
  - utils_media.py        媒体工具函数 + subprocess.Popen 无黑框 patch（导入即生效）
  - widgets.py            可复用控件（双击编辑、拖拽表格）
  - dialogs.py            对话框
  - workers/              各阶段后台 Worker
      split_workers / concat_workers / voice_workers / desc_workers / script_workers

本文件仅保留 VideoMontagePage 主类（UI 控制器），通过 import 复用上述组件。
"""
import os
import shutil
import subprocess
import tempfile
import traceback
import sys
import random
import base64
import requests
import time

# 导入 utils_media 会触发 subprocess.Popen 无黑框 monkey-patch（Windows），必须在任何
# subprocess 调用前完成；下面的 Worker/页面 import 链都会用到 subprocess。
from gui.montage.utils_media import (
    find_ffmpeg, get_media_duration, parse_srt, extract_keyframes,
    format_seconds_to_srt_timestamp, parse_srt_to_descriptions,
    compute_clip_hash, compute_clip_quality,
)

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QListWidget, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QSlider, QDoubleSpinBox, QWidget, QStackedWidget,
                               QSpinBox, QListWidgetItem, QDialog, QPlainTextEdit, QScrollArea, QListView, QMenu)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QAction, QColor, QBrush, QPixmap
from utils.gui_icons import mdi_button, mdi_icon
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from gui.base_page import BasePage

from gui.montage.widgets import (DoubleClickLineEdit, ReadOnlyDoubleClickLineEdit,
                                 ReorderableClipsTable)
from gui.montage.dialogs import (TextEditDialog, ScriptCompareDialog, DubbedVideosDialog,
                                  FinalMixedVideosDialog, ProductCopyInputDialog, VoiceRowDetailWidget,
                                  ClipSelectionDialog)
from gui.montage.workers.split_workers import (PySceneDetectWorker, BestClipWorker,
                                               ServerClipAnalysisWorker)
from gui.montage.workers.concat_workers import (VideoConcatWorker, FinalMixWorker, VideoDubbingWorker)
from gui.montage.workers.voice_workers import VoiceCloneWorker
from gui.montage.workers.desc_workers import (BatchGenerateDescriptionsWorker, LocalVisionDescWorker)
from gui.montage.workers.script_workers import (PunctuationSRTLLMWorker, AITextRewriteWorker,
                                                ProductCopyWorker, SceneCopyWorker, GenScriptWorker,
                                                BatchAITextRewriteWorker, ScriptMatchLLMWorker)



class VideoMontagePage(BasePage):
    """智能混剪主页面（控制器层）。

    本类方法按流程阶段用行内标签分节，便于在 5000+ 行中快速定位。
    每个方法定义行的上一行有形如 ``# [节号·节名]  方法名`` 的标签。
    在 IDE 中搜索 ``# [3·`` 可跳到所有「分割」相关方法，以此类推。

    分节总览：
        [1·初始化]      __init__ / setup / _setup_page_*_legacy（UI 构建）
        [2·基础设施]    分步导航、文件夹选择、worker 管理、LUT 加载等通用工具
        [3·分割]        场景检测、挑精华、镜头评分、哈希/质量计算
        [4·文案脚本]    转写、标点、描述生成、AI 改写、产品/场景文案、脚本匹配
        [5·拼接合成]    标准化转码、xfade 转场、预编排计划、剪映草稿导出
        [6·配音]        声音克隆 TTS、参考音频、单条/批量合成
        [7·混音导出]    配音烧字幕、BGM 混音（人声闪避）、最终合成、对比/导出
        [8·事件回调]    表格单元格、行进度、媒体播放器位置/状态等 UI 事件
        [9·其他]        视频预览、目录打开、全选/反选、UI 装饰等不易归类的小工具

    注：方法在文件中按「添加时间」交错排列，物理上未必连续；
        行内标签的设计正是为了在这种交错布局下仍能快速定位所属阶段。
    """
    # [1·初始化]  __init__
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.concat_worker = None
        self.voice_worker = None
        self.mix_worker = None
        self.dub_worker = None
        self.transcribe_raw_worker = None
        self.punc_srt_worker = None
        self.desc_worker = None
        self.rewrite_worker = None
        self.script_match_worker = None
        
        # State variables
        self.split_descriptions = {} # split video path -> description
        self.rewritten_script = []
        self.split_clips_list = []
        self._available_concat_clips = []
        self._step1_score_threshold = 6.0
        self.assembled_video_path = ""
        self.ai_rewrite_temperature = 0.5
        self.voice_audio_durations = {}
        self.voice_length_mode = {}  # filepath -> "video" or "audio"
        self.per_video_bgm = {}  # filepath -> bgm_path
        self.cloned_voice_path = ""
        self.final_video_path = ""
        
        # Batch Voice Cloning variables
        self.voice_video_paths = []
        self.generated_voice_paths = {} # maps video_path -> voice_wav_path
        self.dubbed_video_paths = {}    # maps video_path -> dubbed_video_path

        # BGM Player dedicated setup
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        self._bgm_player = QMediaPlayer()
        self._bgm_audio_output = QAudioOutput()
        self._bgm_player.setAudioOutput(self._bgm_audio_output)

        # Preview Player dedicated setup
        self.preview_player = QMediaPlayer()
        self.preview_audio_output = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_audio_output)

        # Final Preview Player dedicated setup
        self.final_preview_player = QMediaPlayer()
        self.final_preview_audio = QAudioOutput()
        self.final_preview_player.setAudioOutput(self.final_preview_audio)

        # Split clips metadata cache
        self.split_clips_cache = {}

        # Step 2 precompose state
        self.precompose_plans = []
        self.current_precompose_index = -1
        self._confirming_plan_index = None
        self._confirm_queue = []
        self._preview_sequence_clips = []
        self._preview_sequence_idx = 0
    # [1·初始化]  setup
    def setup(self):
        # Main layout
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)

        # Title
        heading = QLabel("🎬 智能混剪与批量视频制作")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        # Top Progress Step Bar
        self.step_bar = QFrame()
        self.step_bar.setObjectName("step_bar")
        self.step_bar.setStyleSheet("""
            QFrame#step_bar {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 8px;
            }
        """)
        step_layout = QHBoxLayout(self.step_bar)
        step_layout.setContentsMargins(12, 6, 12, 6)
        step_layout.setSpacing(8)
        
        self.step_labels = []
        steps_text = ["1. 镜头智能分割", "2. 镜头重组", "3. 口播配音", "4. 特效包装"]
        for i, text in enumerate(steps_text):
            lbl = QLabel(text)
            lbl.setObjectName("step_label")
            lbl.setAlignment(Qt.AlignCenter)
            if i == 0:
                lbl.setProperty("active", True)
            step_layout.addWidget(lbl)
            self.step_labels.append(lbl)

            if i < len(steps_text) - 1:
                arrow = QLabel("➔")
                arrow.setStyleSheet("color: rgba(255,255,255,0.2); font-weight: bold;")
                arrow.setAlignment(Qt.AlignCenter)
                step_layout.addWidget(arrow)
                
        layout.addWidget(self.step_bar, 0)

        # Wizard QStackedWidget
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("QStackedWidget { background: transparent; }")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.setWidget(self.stacked_widget)

        layout.addWidget(self.scroll_area, 1)

        # Build Wizard Pages (Modularized split)
        from gui.montage.step1_split_view import Step1SplitView
        from gui.montage.step2_concat_view import Step2ConcatView
        from gui.montage.step3_voice_view import Step3VoiceView
        from gui.montage.step4_final_view import Step4FinalView

        self.step1 = Step1SplitView(self)
        self.stacked_widget.addWidget(self.step1)

        self.step2 = Step2ConcatView(self)
        self.sources_detail_widget = ReorderableClipsTable()
        self.sources_detail_widget.setWordWrap(False)
        self.sources_detail_widget.verticalHeader().setDefaultSectionSize(30)
        self.sources_detail_widget.setColumnCount(5)
        self.sources_detail_widget.setHorizontalHeaderLabels(["⠿", "分割文件名", "时间戳", "描述文案", "评分"])
        self.sources_detail_widget.setMinimumHeight(260)
        self.sources_detail_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sources_detail_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sources_detail_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sources_detail_widget.customContextMenuRequested.connect(self._on_source_context_menu)
        self.sources_detail_widget.order_changed.connect(self._on_source_order_changed)
        
        header = self.sources_detail_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.sources_detail_widget.setColumnWidth(4, 50)
        
        self.step2.detail_layout.addWidget(self.sources_detail_widget)
        self.stacked_widget.addWidget(self.step2)

        self.step3 = Step3VoiceView(self)
        self.stacked_widget.addWidget(self.step3)

        self.step4 = Step4FinalView(self)
        self.stacked_widget.addWidget(self.step4)


        # Progress bar & status display at the bottom (shared across pages)
        bottom_status = QFrame()
        bottom_layout = QVBoxLayout(bottom_status)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        self.stage_label = QLabel("就绪")
        self.stage_label.setObjectName("muted_text")
        bottom_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bottom_layout.addWidget(self.progress_bar)
        
        layout.addWidget(bottom_status, 0)

        # Initialize UI indicators
        self.update_step_indicator(0)
        self._populate_ref_audio_samples()
    # [9·其他]  update_step_indicator
    def update_step_indicator(self, index):
        for i, lbl in enumerate(self.step_labels):
            if i == index:
                lbl.setProperty("status", "active")
            elif i < index:
                lbl.setProperty("status", "done")
            else:
                lbl.setProperty("status", "pending")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
    # [2·基础设施]  _go_to_step
    def _go_to_step(self, index):
        # Stop any ongoing media playback when switching steps
        if hasattr(self, "_bgm_player") and self._bgm_player:
            self._stop_bgm_play()
        if hasattr(self, "preview_player") and self.preview_player:
            self.preview_player.stop()
        if hasattr(self, "final_preview_player") and self.final_preview_player:
            self.final_preview_player.stop()
        if hasattr(self, "_media_player") and self._media_player:
            self._media_player.stop()

        self.stacked_widget.setCurrentIndex(index)
        self.update_step_indicator(index)
        self.stage_label.setText("就绪")
        self.progress_bar.setVisible(False)
        
        if index == 2:
            self._on_enter_step_3()
        elif index == 3:
            if hasattr(self, "mix_video_table") and self.mix_video_table.rowCount() == 0:
                self._populate_default_mix_videos()
            else:
                self._update_final_inputs_label()
    # [2·基础设施]  _on_enter_step_3
    def _on_enter_step_3(self):
        dir_path = ""
        confirmed_paths = self._collect_assembled_paths() if hasattr(self, "_collect_assembled_paths") else []
        if confirmed_paths:
            dir_path = os.path.dirname(confirmed_paths[0])
            # 配音表只列本批已合成的预合成视频，避免目录里残留的
            # 其他视频（如历史分割镜头片段）被整目录扫描混入
            self.selected_voice_video_files = list(confirmed_paths)
            self._voice_scan_allow_dir_fallback = True
        else:
            self.selected_voice_video_files = []
            # 本次会话没有已合成的预合成视频（如重启后新建任务）：
            # 禁止整目录扫描回退，避免上次生成的旧视频自动出现在配音表
            self._voice_scan_allow_dir_fallback = False

        if not dir_path:
            src_dir = self.folder_path_input.text().strip()
            if src_dir:
                dir_path = self._get_out_montage_dir(src_dir)
        
        if dir_path and os.path.exists(dir_path):
            self.voice_video_dir_input.blockSignals(True)
            self.voice_video_dir_input.setText(dir_path)
            self.voice_video_dir_input.blockSignals(False)
        
        self._scan_voice_video_dir()

        # 纯远程模式：从 ai_config 读取已保存的远程 TTS API 地址回填
        try:
            ai_config = getattr(self.main_window, "ai_config", {}) or {}
        except Exception:
            ai_config = {}
        saved_url = ai_config.get("vox_api_url", "")
        if saved_url:
            self.api_url_input.setText(saved_url)
        self._populate_ref_audio_samples()

    # ==================== PAGE 0: SMART SPLIT ====================
    # [1·初始化]  _setup_page_split_legacy
    def _setup_page_split_legacy(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        # Input source videos
        row_dir = QHBoxLayout()
        row_dir.addWidget(QLabel("原始素材:"))
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("选择一个或多个视频素材，可多次追加...")
        self.folder_path_input.setReadOnly(True)
        row_dir.addWidget(self.folder_path_input)
        btn_sel = QPushButton("选择素材")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_folder)
        row_dir.addWidget(btn_sel)
        card_layout.addLayout(row_dir)

        # Raw videos list
        card_layout.addWidget(QLabel("已选择的原始视频素材 (双击可播放预览，右键可删除):"))
        self.video_list = QListWidget()
        self.video_list.setFixedHeight(120)
        self.video_list.setTextElideMode(Qt.ElideRight)
        self.video_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.video_list.itemClicked.connect(self._check_split_clips_exist)
        self.video_list.itemDoubleClicked.connect(self._preview_video_item)
        self.video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_list.customContextMenuRequested.connect(self._show_video_context_menu)
        card_layout.addWidget(self.video_list)



        # SceneDetect Config
        split_row = QHBoxLayout()
        split_row.addWidget(QLabel("分割阈值 (10-100):"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(10.0, 100.0)
        self.threshold_spin.setValue(50.0)
        self.threshold_spin.setSingleStep(1.0)
        split_row.addWidget(self.threshold_spin)

        split_row.addWidget(QLabel("最少帧数 (默认15):"))
        self.min_len_spin = QDoubleSpinBox()
        self.min_len_spin.setDecimals(0)
        self.min_len_spin.setRange(5, 100)
        self.min_len_spin.setValue(15)
        split_row.addWidget(self.min_len_spin)
        split_row.addStretch()

        # Dependencies auto check in UI
        try:
            import scenedetect
            self.has_scenedetect_dep = True
        except ImportError:
            self.has_scenedetect_dep = False

        self.dep_status_widget = QWidget()
        dep_layout = QHBoxLayout(self.dep_status_widget)
        dep_layout.setContentsMargins(0, 0, 0, 0)
        
        if self.has_scenedetect_dep:
            lbl_dep = QLabel("✅ 镜头分割依赖就绪")
            lbl_dep.setStyleSheet("color: #2ecc71; font-weight: bold;")
            dep_layout.addWidget(lbl_dep)
        else:
            self.btn_install_deps = mdi_button("安装智能分割依赖", "wrench")
            self.btn_install_deps.setObjectName("secondary_button")
            self.btn_install_deps.clicked.connect(self._install_scenedetect)
            dep_layout.addWidget(self.btn_install_deps)
            
        split_row.addWidget(self.dep_status_widget)

        # 单视频镜头分割
        self.btn_split = mdi_button("开始智能镜头分割", "cut")
        self.btn_split.setObjectName("action_button")
        self.btn_split.setFixedHeight(35)
        self.btn_split.clicked.connect(self._start_split)
        split_row.addWidget(self.btn_split)

        split_row.addSpacing(12)
        split_row.addWidget(QLabel("精华时长:"))
        self.spin_highlight_sec = QDoubleSpinBox()
        self.spin_highlight_sec.setRange(1.0, 30.0)
        self.spin_highlight_sec.setValue(3.0)
        self.spin_highlight_sec.setSingleStep(1.0)
        self.spin_highlight_sec.setSuffix(" 秒")
        self.spin_highlight_sec.setFixedWidth(80)
        self.spin_highlight_sec.setToolTip("从每个视频里挑出多长的精华片段")
        split_row.addWidget(self.spin_highlight_sec)

        self.btn_pick_highlights = mdi_button("批量选精华", "star")
        self.btn_pick_highlights.setObjectName("secondary_button")
        self.btn_pick_highlights.setFixedHeight(35)
        self.btn_pick_highlights.setToolTip(
            "对列表中所有视频，各挑出一段最佳（清晰+适度运动）片段，"
            "写入 splits 作为混剪拼接素材")
        self.btn_pick_highlights.clicked.connect(self._start_pick_highlights)
        split_row.addWidget(self.btn_pick_highlights)
        card_layout.addLayout(split_row)

        # Split results table view
        card_layout.addWidget(QLabel("已分割出的最小单位镜头片段 (双击可播放预览，双击画面描述列可手动修改):"))
        self.split_result_table = QTableWidget()
        self.split_result_table.setWordWrap(False)
        self.split_result_table.verticalHeader().setDefaultSectionSize(30)
        self.split_result_table.setColumnCount(5)
        self.split_result_table.setHorizontalHeaderLabels(["序号", "视频片段", "时间戳", "画面文案描述", "评分"])
        self.split_result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.split_result_table.setMinimumHeight(180)
        self.split_result_table.itemDoubleClicked.connect(self._preview_table_item)
        self.split_result_table.cellChanged.connect(self._on_table_cell_changed)
        
        header = self.split_result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.split_result_table.setColumnWidth(1, 180)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.split_result_table.setColumnWidth(4, 50)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        
        card_layout.addWidget(self.split_result_table)



        layout.addWidget(card, 1)

        # Navigation row (Open split clips directory button moved here!)
        nav_row = QHBoxLayout()
        self.btn_open_splits_dir = mdi_button("打开已分割镜头目录", "folder")
        self.btn_open_splits_dir.setObjectName("secondary_button")
        self.btn_open_splits_dir.clicked.connect(self._open_splits_dir)
        nav_row.addWidget(self.btn_open_splits_dir)

        self.btn_gen_split_descriptions = mdi_button("生成画面文案描述", "pencil")
        self.btn_gen_split_descriptions.setObjectName("secondary_button")
        self.btn_gen_split_descriptions.setToolTip(
            "为每个分割镜头生成文案描述：有字幕的从字幕匹配，无字幕的用视觉AI分析画面")
        self.btn_gen_split_descriptions.clicked.connect(self._gen_split_descriptions)
        nav_row.addWidget(self.btn_gen_split_descriptions)
        
        nav_row.addStretch()
        self.btn_next_to_step_2 = mdi_button("下一步：镜头重组", "right")
        self.btn_next_to_step_2.setObjectName("primary_button")
        self.btn_next_to_step_2.setEnabled(True)
        self.btn_next_to_step_2.clicked.connect(lambda: self._go_to_step(1))
        nav_row.addWidget(self.btn_next_to_step_2)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)

    # ==================== PAGE 1: CLIP ASSEMBLY ====================
    # [1·初始化]  _setup_page_concat_legacy
    def _setup_page_concat_legacy(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)

        # Loaded video clips list header with Select All/None controls
        list_header_row = QHBoxLayout()
        self.clip_count_info_lbl = QLabel("待排列镜头个数: 0  (已勾选: 0)")
        self.clip_count_info_lbl.setStyleSheet("font-weight: bold; font-size: 11pt; color: #f1c40f;")
        list_header_row.addWidget(self.clip_count_info_lbl)
        list_header_row.addStretch()

        # Source split clips directory input
        row_src = QHBoxLayout()
        row_src.addWidget(QLabel("待排列镜头目录:"))
        self.concat_src_dir_input = QLineEdit()
        self.concat_src_dir_input.setPlaceholderText("选择或输入排列视频片段所在的文件夹...")
        self.concat_src_dir_input.editingFinished.connect(self._scan_concat_src_dir)
        row_src.addWidget(self.concat_src_dir_input)
        self.btn_select_concat_src_dir = QPushButton("重新选择素材")
        self.btn_select_concat_src_dir.setObjectName("secondary_button")
        self.btn_select_concat_src_dir.clicked.connect(self._select_concat_src_dir)
        row_src.addWidget(self.btn_select_concat_src_dir)
        card_layout.addLayout(row_src)
        btn_select_all = QPushButton("全选")
        btn_select_all.setObjectName("secondary_button")
        btn_select_all.setFixedWidth(50)
        btn_select_all.clicked.connect(self._select_all_clips)
        list_header_row.addWidget(btn_select_all)
        
        btn_deselect_all = QPushButton("取消全选")
        btn_deselect_all.setObjectName("secondary_button")
        btn_deselect_all.setFixedWidth(80)
        btn_deselect_all.clicked.connect(self._deselect_all_clips)
        list_header_row.addWidget(btn_deselect_all)
        card_layout.addLayout(list_header_row)

        self.concat_clips_list_widget = QTableWidget()
        self.concat_clips_list_widget.setWordWrap(False)
        self.concat_clips_list_widget.verticalHeader().setDefaultSectionSize(30)
        self.concat_clips_list_widget.setColumnCount(6)
        self.concat_clips_list_widget.setHorizontalHeaderLabels(["分割文件名", "时间戳", "描述文案", "评分", "文件目录", "操作"])
        self.concat_clips_list_widget.setFixedHeight(180)
        self.concat_clips_list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.concat_clips_list_widget.itemDoubleClicked.connect(self._preview_concat_table_item)
        self.concat_clips_list_widget.cellChanged.connect(self._on_concat_table_cell_changed)
        
        header = self.concat_clips_list_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)       # 分割文件名
        self.concat_clips_list_widget.setColumnWidth(0, 160)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 时间戳
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # 描述文案
        header.setSectionResizeMode(3, QHeaderView.Fixed)             # 评分
        self.concat_clips_list_widget.setColumnWidth(3, 50)
        header.setSectionResizeMode(4, QHeaderView.Interactive)       # 文件目录
        self.concat_clips_list_widget.setColumnWidth(4, 120)
        header.setSectionResizeMode(5, QHeaderView.Fixed)             # 操作
        self.concat_clips_list_widget.setColumnWidth(5, 30)
        
        card_layout.addWidget(self.concat_clips_list_widget)

        # Parameters row 1
        row_params1 = QHBoxLayout()
        row_params1.addWidget(QLabel("排列逻辑:"))
        self.logic_combo = QComboBox()
        self.logic_combo.addItem("随机洗牌", "random")
        self.logic_combo.addItem("🎯 按文案智能匹配", "script")
        self.logic_combo.setToolTip(
            "随机洗牌：镜头随机排列组合。\n"
            "按文案智能匹配：粘贴口播文案（每行一句），LLM 为每行挑选画面最贴合的镜头并按行序排列。")
        self.logic_combo.currentIndexChanged.connect(self._on_logic_combo_changed)
        row_params1.addWidget(self.logic_combo)

        row_params1.addSpacing(15)
        row_params1.addWidget(QLabel("输出画幅:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("与原视频一致", "source")
        self.layout_combo.addItem("竖屏 (1080x1920 抖音流)", "vertical")
        self.layout_combo.addItem("横屏 (1920x1080 宽屏)", "horizontal")
        self.layout_combo.setCurrentIndex(0)
        row_params1.addWidget(self.layout_combo)

        row_params1.addSpacing(15)
        self.lbl_clip_count = QLabel("排列镜头数量:")
        row_params1.addWidget(self.lbl_clip_count)
        self.clip_count_combo = QComboBox()
        self.clip_count_combo.setStyleSheet("""
            QComboBox {
                background-color: #2c2c2e;
                color: #ecf0f1;
                border: 1px solid #3a3a3c;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox:hover { border: 1px solid #5a5a5c; }
            QComboBox:focus { border: 1px solid #2ecc71; }
            QComboBox QAbstractItemView {
                background-color: #2c2c2e;
                color: #ecf0f1;
                selection-background-color: #3a3a3c;
                border: 1px solid #3a3a3c;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #95a5a6;
                margin-right: 5px;
            }
        """)
        for i in [3, 5, 8, 10, 15, 20]:
            self.clip_count_combo.addItem(f"{i} 个镜头", i)
        self.clip_count_combo.setCurrentIndex(2)
        self.clip_count_combo.currentIndexChanged.connect(self._update_batch_count_recommendation)
        row_params1.addWidget(self.clip_count_combo)

        row_params1.addSpacing(15)
        self.lbl_duration_limit = QLabel("时长限制:")
        row_params1.addWidget(self.lbl_duration_limit)
        self.duration_limit_combo = QComboBox()
        for sec in [20, 30, 40, 50, 60]:
            self.duration_limit_combo.addItem(f"{sec} 秒", sec)
        self.duration_limit_combo.setCurrentIndex(1)
        self.duration_limit_combo.setFixedWidth(80)
        self.duration_limit_combo.setToolTip("每个预合成视频的总时长上限（实际不超此值的 1.1 倍）")
        row_params1.addWidget(self.duration_limit_combo)

        row_params1.addSpacing(15)
        self.lbl_randomness = QLabel("混编随机度:")
        row_params1.addWidget(self.lbl_randomness)
        self.randomness_combo = QComboBox()
        self.randomness_combo.addItem("中 (保留同场景)", "medium")
        self.randomness_combo.addItem("高 (全随机)", "high")
        self.randomness_combo.addItem("低 (顺序无随机)", "low")
        self.randomness_combo.setCurrentIndex(0)
        row_params1.addWidget(self.randomness_combo)
        self.lbl_randomness.setVisible(False)
        self.randomness_combo.setVisible(False)

        row_params1.addStretch()
        card_layout.addLayout(row_params1)

        # Parameters row 2
        row_params2 = QHBoxLayout()
        self.lbl_batch_count = QLabel("生成视频数量 (1-10):")
        row_params2.addWidget(self.lbl_batch_count)
        self.batch_count_spin = QSpinBox()
        self.batch_count_spin.setRange(1, 10)
        self.batch_count_spin.setValue(3)
        self.batch_count_spin.setFixedWidth(60)
        row_params2.addWidget(self.batch_count_spin)

        self.batch_count_hint_lbl = QLabel("推荐: 1")
        self.batch_count_hint_lbl.setObjectName("muted_text")
        row_params2.addWidget(self.batch_count_hint_lbl)

        row_params2.addStretch()

        row_params2.addSpacing(15)
        row_params2.addWidget(QLabel("转场动画:"))
        self.transition_combo = QComboBox()
        self.transition_combo.addItem("模糊", "fade")
        self.transition_combo.addItem("淡入淡出", "dissolve")
        self.transition_combo.addItem("左移", "slideleft")
        self.transition_combo.addItem("右移", "slideright")
        self.transition_combo.addItem("上移", "slideup")
        self.transition_combo.addItem("下移", "slidedown")
        self.transition_combo.addItem("推进", "zoomin")
        self.transition_combo.addItem("拉远", "zoomout")
        self.transition_combo.setCurrentIndex(0)
        self.transition_combo.setFixedWidth(100)
        self.transition_combo.setToolTip("镜头之间的转场动画效果（剪映常用转场）")
        row_params2.addWidget(self.transition_combo)

        row_params2.addSpacing(12)
        row_params2.addWidget(QLabel("LUT 还原:"))
        self.lut_combo = QComboBox()
        self.lut_combo.addItem("无", "")
        self.lut_combo.setFixedWidth(140)
        self.lut_combo.setToolTip("对分割镜头应用 LUT 色彩还原（需先在「运行环境 → 视频配置」中配置 LUT 文件）")
        row_params2.addWidget(self.lut_combo)

        row_params2.addStretch()

        self.btn_assemble_video = mdi_button("镜头重组", "video")
        self.btn_assemble_video.setObjectName("action_button")
        self.btn_assemble_video.setFixedHeight(35)
        self.btn_assemble_video.clicked.connect(self._start_assemble_video)
        row_params2.addWidget(self.btn_assemble_video)

        card_layout.addLayout(row_params2)

        # 智能匹配模式的口播文案输入框（默认隐藏）
        self.match_script_edit = QTextEdit()
        self.match_script_edit.setPlaceholderText(
            "粘贴口播文案，每行一句。\n"
            "智能匹配将为每一行文案从勾选的镜头中挑选画面最贴合的一个，并按行序排列成片。\n"
            "示例：\n这款鼠标采用轻量化设计\n8000DPI 电竞级传感器\n续航长达 70 小时")
        self.match_script_edit.setFixedHeight(96)
        self.match_script_edit.setVisible(False)
        card_layout.addWidget(self.match_script_edit)

        # Intermediate result viewer
        result_box = QFrame()
        result_box.setStyleSheet("background-color: rgba(255,255,255,0.03); border: 1px dashed rgba(255,255,255,0.1); border-radius: 4px;")
        res_layout = QHBoxLayout(result_box)
        res_layout.setContentsMargins(10, 10, 10, 10)
        res_layout.setSpacing(15)

        # Left Column: Lists and Tables (takes 3/4 width)
        left_container = QWidget()
        left_vbox = QVBoxLayout(left_container)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(10)

        assembled_header = QHBoxLayout()
        assembled_header.setContentsMargins(0, 0, 0, 0)
        assembled_header.addWidget(QLabel("预合成视频列表 (双击播放预览，单击选中查看镜头):"), 1)
        left_vbox.addLayout(assembled_header)

        self.assembled_clips_list_widget = QListWidget()
        self.assembled_clips_list_widget.setFixedHeight(120)
        self.assembled_clips_list_widget.setTextElideMode(Qt.ElideRight)
        self.assembled_clips_list_widget.itemDoubleClicked.connect(self._preview_video_item)
        self.assembled_clips_list_widget.itemClicked.connect(self._on_assembled_item_clicked)
        self.assembled_clips_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.assembled_clips_list_widget.customContextMenuRequested.connect(self._show_assembled_context_menu)
        left_vbox.addWidget(self.assembled_clips_list_widget)

        left_vbox.addWidget(QLabel("📋 视频组成镜头详情 (拖动把手调序，右键删除/恢复镜头):"))
        
        self.sources_detail_widget = ReorderableClipsTable()
        self.sources_detail_widget.setWordWrap(False)
        self.sources_detail_widget.verticalHeader().setDefaultSectionSize(30)
        self.sources_detail_widget.setColumnCount(5)
        self.sources_detail_widget.setHorizontalHeaderLabels(["⠿", "分割文件名", "时间戳", "描述文案", "评分"])
        self.sources_detail_widget.setMinimumHeight(260)
        self.sources_detail_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sources_detail_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sources_detail_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sources_detail_widget.customContextMenuRequested.connect(self._on_source_context_menu)
        self.sources_detail_widget.order_changed.connect(self._on_source_order_changed)
        
        header = self.sources_detail_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.sources_detail_widget.setColumnWidth(4, 50)
        
        left_vbox.addWidget(self.sources_detail_widget)

        # Right Column: Video Preview Player (takes 1/4 width)
        player_container = QWidget()
        player_container.setStyleSheet("background-color: #000000; border-radius: 6px; border: 1px solid #27272a;")
        player_vbox = QVBoxLayout(player_container)
        player_vbox.setContentsMargins(6, 6, 6, 6)
        player_vbox.setSpacing(6)
        
        # Video title
        self.preview_title = QLabel("🎥 视频播放预览")
        self.preview_title.setObjectName("muted_text")
        player_vbox.addWidget(self.preview_title)
        
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self.preview_video_widget = QVideoWidget()
        self.preview_video_widget.setMinimumHeight(200)
        player_vbox.addWidget(self.preview_video_widget, 1)

        self.preview_overlay_label = QLabel("#1")
        self.preview_overlay_label.setParent(self.preview_video_widget)
        self.preview_overlay_label.move(8, 8)
        self.preview_overlay_label.setStyleSheet(
            "background-color: rgba(0,0,0,0.55); color: #f8fafc; "
            "border: 1px solid rgba(255,255,255,0.22); border-radius: 10px; "
            "padding: 2px 8px; font-size: 12px; font-weight: bold;")
        self.preview_overlay_label.hide()
        
        # Control buttons row
        player_controls = QHBoxLayout()
        player_controls.setSpacing(6)
        self.btn_preview_play = mdi_button("", "play")
        self.btn_preview_play.setFixedWidth(44)
        self.btn_preview_play.setFixedHeight(24)
        self.btn_preview_play.setStyleSheet("padding: 0px; font-size: 14px;")
        self.btn_preview_play.setToolTip("播放/暂停")
        self.btn_preview_play.clicked.connect(self._toggle_preview_video)
        player_controls.addWidget(self.btn_preview_play)
        
        self.preview_slider = QSlider(Qt.Horizontal)
        self.preview_slider.setRange(0, 0)
        self.preview_slider.setFixedHeight(20)
        self.preview_slider.sliderMoved.connect(self._set_preview_position)
        player_controls.addWidget(self.preview_slider)
        
        player_vbox.addLayout(player_controls)

        # Add left and right columns with stretch factors 3 and 1 (3:1 width ratio, i.e., right takes 25%)
        res_layout.addWidget(left_container, 3)
        res_layout.addWidget(player_container, 1)

        # Initialize preview player connections
        self.preview_player.setVideoOutput(self.preview_video_widget)
        self.preview_player.positionChanged.connect(self._on_preview_position_changed)
        self.preview_player.durationChanged.connect(self._on_preview_duration_changed)
        self.preview_player.mediaStatusChanged.connect(self._on_preview_media_status_changed)

        card_layout.addWidget(result_box)

        layout.addWidget(card, 1)

        # Confirm row (above navigation)
        confirm_row = QHBoxLayout()
        self.btn_confirm_all = QPushButton("确认合成视频")
        self.btn_confirm_all.setObjectName("action_button")
        self.btn_confirm_all.setFixedHeight(35)
        self.btn_confirm_all.setEnabled(False)
        self.btn_confirm_all.clicked.connect(self._confirm_all_precompose)
        confirm_row.addWidget(self.btn_confirm_all)
        self.btn_batch_scene_copy = QPushButton("合成视频生成文案")
        self.btn_batch_scene_copy.setObjectName("secondary_button")
        self.btn_batch_scene_copy.setFixedHeight(35)
        self.btn_batch_scene_copy.setToolTip(
            "为列表中所有组合视频，按各自的画面镜头描述自动生成口播文案"
            "（共用同一份产品背景，保存为同名 .txt，下一步配音自动载入）")
        self.btn_batch_scene_copy.clicked.connect(self._batch_gen_copy_by_scene)
        self.btn_batch_scene_copy.setEnabled(False)
        confirm_row.addWidget(self.btn_batch_scene_copy, 0)
        layout.addLayout(confirm_row)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：镜头分割", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(0))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.btn_next_to_step_3 = mdi_button("下一步：克隆口播", "right")
        self.btn_next_to_step_3.setObjectName("primary_button")
        self.btn_next_to_step_3.setEnabled(True)
        self.btn_next_to_step_3.clicked.connect(lambda: self._go_to_step(2))
        nav_row.addWidget(self.btn_next_to_step_3)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)
        self._on_logic_combo_changed()
    # [1·初始化]  _setup_page_voice_legacy
    def _setup_page_voice_legacy(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(8)  # 收紧行间距，把空间留给视频列表

        # 1. Video Directory Row
        row_vid_dir = QHBoxLayout()
        row_vid_dir.setAlignment(Qt.AlignVCenter)
        row_vid_dir.addWidget(QLabel("📹 视频输入目录:"))
        self.voice_video_dir_input = QLineEdit()
        self.voice_video_dir_input.setPlaceholderText("选择包含排列视频的目录...")
        self.voice_video_dir_input.textChanged.connect(self._on_voice_video_dir_changed)
        row_vid_dir.addWidget(self.voice_video_dir_input)
        btn_sel_vid_dir = QPushButton("选择目录")
        btn_sel_vid_dir.setObjectName("secondary_button")
        btn_sel_vid_dir.clicked.connect(self._select_voice_video_dir)
        row_vid_dir.addWidget(btn_sel_vid_dir)
        card_layout.addLayout(row_vid_dir)

        # 远程 TTS API 地址输入框（纯远程模式；保存时同步到 ai_config）
        self.api_url_input = QLineEdit()
        self.api_url_input.setText("http://192.168.111.18:8000/voxcpm/tts")
        self.api_url_input.setPlaceholderText("http://192.168.111.18:8000/voxcpm/tts")

        # 2a. Reference Voice Row
        row_voice = QHBoxLayout()
        row_voice.setSpacing(8)
        row_voice.setAlignment(Qt.AlignVCenter)

        row_voice.addWidget(QLabel("🗣️ 参考声音:"))
        self.ref_audio_combo = QComboBox()
        self.ref_audio_combo.setView(QListView())
        self.ref_audio_combo.setMinimumWidth(160)
        self.ref_audio_combo.currentIndexChanged.connect(self._on_ref_audio_combo_changed)
        row_voice.addWidget(self.ref_audio_combo)

        self.btn_play_ref = mdi_button("", "volume")
        self.btn_play_ref.setToolTip("播放人声样本")
        self.btn_play_ref.setStyleSheet("padding: 0px; font-size: 14px;")
        self.btn_play_ref.setFixedWidth(30)
        self.btn_play_ref.setFixedHeight(30)
        self.btn_play_ref.setEnabled(False)
        self.btn_play_ref.clicked.connect(self._play_ref_audio)
        row_voice.addWidget(self.btn_play_ref)

        self.btn_upload_ref = mdi_button("上传声音", "folder")
        self.btn_upload_ref.setToolTip("上传本地音频文件作为参考声音 (wav/mp3/m4a)")
        self.btn_upload_ref.setObjectName("secondary_button")
        self.btn_upload_ref.setFixedHeight(30)
        self.btn_upload_ref.clicked.connect(self._select_ref_audio)
        row_voice.addWidget(self.btn_upload_ref)

        row_voice.addStretch(1)
        card_layout.addLayout(row_voice)

        # 2b. Reference Script Row (separate line)
        row_ref_text = QHBoxLayout()
        row_ref_text.setSpacing(8)
        row_ref_text.setAlignment(Qt.AlignVCenter)

        row_ref_text.addWidget(QLabel("📝 参考文案:"))
        self.ref_text_input = QLineEdit()
        self.ref_text_input.setPlaceholderText("可选，填入样本台词...")
        self.ref_text_input.setStyleSheet("""
            QLineEdit {
                background-color: #2c2c2e;
                border: 1px solid #3a3a3c;
                border-radius: 6px;
                padding: 4px 8px;
                color: #ffffff;
            }
        """)
        row_ref_text.addWidget(self.ref_text_input, 1)
        card_layout.addLayout(row_ref_text)
        
        # 3. TTS API 接口地址与推理参数（纯远程模式）
        row_server = QHBoxLayout()
        row_server.setSpacing(10)
        row_server.setAlignment(Qt.AlignVCenter)

        row_server.addWidget(QLabel("🌐 TTS API:"))
        row_server.addWidget(self.api_url_input, 1)

        row_server.addSpacing(12)
        row_server.addWidget(QLabel("推理步数:"))
        from PySide6.QtWidgets import QSpinBox
        self.tts_steps_spin = QSpinBox()
        self.tts_steps_spin.setRange(4, 50)
        self.tts_steps_spin.setValue(10)
        self.tts_steps_spin.setSingleStep(5)
        self.tts_steps_spin.setFixedWidth(52)
        self.tts_steps_spin.setToolTip(
            "VoxCPM 推理步数（4-30，默认10）\n"
            "步数越多音质越细腻，但速度越慢\n"
            "推荐：快速=10，高质量=20-30")
        row_server.addWidget(self.tts_steps_spin)

        row_server.addSpacing(8)
        row_server.addWidget(QLabel("CFG:"))
        from PySide6.QtWidgets import QDoubleSpinBox
        self.tts_cfg_spin = QDoubleSpinBox()
        self.tts_cfg_spin.setRange(0.5, 5.0)
        self.tts_cfg_spin.setValue(2.0)
        self.tts_cfg_spin.setSingleStep(0.5)
        self.tts_cfg_spin.setDecimals(1)
        self.tts_cfg_spin.setFixedWidth(52)
        self.tts_cfg_spin.setToolTip(
            "引导强度（0.5-5.0，默认2.0）\n"
            "越高越贴近参考音色但可能过拟合\n"
            "推荐范围：1.5 - 3.0")
        row_server.addWidget(self.tts_cfg_spin)

        row_server.addSpacing(8)
        row_server.addWidget(QLabel("速率:"))
        self.tts_speed_min_spin = QDoubleSpinBox()
        self.tts_speed_min_spin.setRange(0.5, 1.0)
        self.tts_speed_min_spin.setValue(0.9)
        self.tts_speed_min_spin.setSingleStep(0.05)
        self.tts_speed_min_spin.setDecimals(2)
        self.tts_speed_min_spin.setFixedWidth(52)
        self.tts_speed_min_spin.setToolTip(
            "变速下限（默认0.90）\n"
            "音频比视频长时最多允许拉慢到此倍速\n"
            "超出范围时不再强制调速，保留自然音质")
        row_server.addWidget(self.tts_speed_min_spin)
        row_server.addWidget(QLabel("~"))
        self.tts_speed_max_spin = QDoubleSpinBox()
        self.tts_speed_max_spin.setRange(1.0, 2.0)
        self.tts_speed_max_spin.setValue(1.2)
        self.tts_speed_max_spin.setSingleStep(0.05)
        self.tts_speed_max_spin.setDecimals(2)
        self.tts_speed_max_spin.setFixedWidth(52)
        self.tts_speed_max_spin.setToolTip(
            "变速上限（默认1.20）\n"
            "音频比视频短时最多允许加速到此倍速\n"
            "超出范围时不再强制调速，保留自然音质")
        row_server.addWidget(self.tts_speed_max_spin)

        row_server.addStretch(1)
        card_layout.addLayout(row_server)

        # 5. Videos and script mappings table (batch text area removed)
        row_table_title = QHBoxLayout()
        row_table_title.setContentsMargins(0, 4, 0, 4)
        lbl_title = QLabel("📹 待合成视频列表与配音文案映射 (在配音文案栏直接输入):")
        lbl_title.setObjectName("card_title")
        row_table_title.addWidget(lbl_title)
        row_table_title.addStretch()

        self.btn_ai_rewrite_settings = mdi_button("文案生成设置", "gear")
        self.btn_ai_rewrite_settings.setObjectName("secondary_button")
        self.btn_ai_rewrite_settings.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        self.btn_ai_rewrite_settings.clicked.connect(self._show_ai_rewrite_settings)
        row_table_title.addWidget(self.btn_ai_rewrite_settings)

        self.btn_batch_ai_rewrite = mdi_button("一键AI修改全部文案", "sparkles")
        self.btn_batch_ai_rewrite.setObjectName("action_button")
        self.btn_batch_ai_rewrite.setStyleSheet("padding: 4px 12px; font-size: 12px; font-weight: bold;")
        self.btn_batch_ai_rewrite.clicked.connect(self._batch_ai_rewrite_scripts)
        row_table_title.addWidget(self.btn_batch_ai_rewrite)
        card_layout.addLayout(row_table_title)

        self.voice_table = QTableWidget()
        self.voice_table.setWordWrap(False)
        self.voice_table.setColumnCount(2)
        self.voice_table.setHorizontalHeaderLabels(["序号", "视频/配音/文案/状态/操作"])
        self.voice_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.voice_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.voice_table.verticalHeader().setDefaultSectionSize(140)
        self.voice_table.verticalHeader().setMinimumSectionSize(90)
        self.voice_table.verticalHeader().setVisible(False)
        self.voice_table.setMinimumHeight(350)
        card_layout.addWidget(self.voice_table, 1)  # stretch=1: 表格吃掉剩余垂直空间

        # Subtitle option checkbox
        row_subtitle_opt = QHBoxLayout()
        self.chk_add_subtitles = QCheckBox("在配音视频中同时添加/烧录字幕 (逐行按时间显示, 字号随视频高度自适应, 白色 50%透明背景)")
        self.chk_add_subtitles.setChecked(False)
        self.chk_add_subtitles.setStyleSheet("font-size: 13px; font-weight: bold;")
        row_subtitle_opt.addWidget(self.chk_add_subtitles)
        card_layout.addLayout(row_subtitle_opt)

        # 花字选项（关键信息加重提醒，非字幕）
        row_fancy_text = QHBoxLayout()
        self.chk_fancy_text = QCheckBox("添加花字 (关键信息加重提醒)")
        self.chk_fancy_text.setChecked(False)
        self.chk_fancy_text.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.chk_fancy_text.setToolTip("在视频画面中央叠加花字特效文字，用于突出关键卖点/价格/型号等信息")
        row_fancy_text.addWidget(self.chk_fancy_text)

        row_fancy_text.addWidget(QLabel("样式:"))
        self.fancy_style_combo = QComboBox()
        self.fancy_style_combo.addItem("渐变金", "gold")
        self.fancy_style_combo.addItem("渐变红", "red")
        self.fancy_style_combo.addItem("渐变蓝", "blue")
        self.fancy_style_combo.addItem("渐变紫", "purple")
        self.fancy_style_combo.addItem("霓虹绿", "neon_green")
        self.fancy_style_combo.addItem("白字黑描边", "white_outline")
        self.fancy_style_combo.addItem("黄字红描边", "yellow_red")
        self.fancy_style_combo.setCurrentIndex(0)
        self.fancy_style_combo.setFixedWidth(110)
        row_fancy_text.addWidget(self.fancy_style_combo)

        row_fancy_text.addWidget(QLabel("花字内容:"))
        self.fancy_text_input = QLineEdit()
        self.fancy_text_input.setPlaceholderText("输入要叠加的花字内容，多行用逗号分隔（按镜头顺序轮换）")
        self.fancy_text_input.setToolTip("多个花字用逗号分隔，会按镜头顺序轮换显示。如：超轻量化,8000DPI,续航70小时")
        row_fancy_text.addWidget(self.fancy_text_input, 1)
        card_layout.addLayout(row_fancy_text)

        # 7. Action buttons row
        row_actions = QHBoxLayout()
        self.btn_synthesize_voice = mdi_button("开始批量克隆人声合成", "voice")
        self.btn_synthesize_voice.setObjectName("action_button")
        self.btn_synthesize_voice.setFixedHeight(35)
        self.btn_synthesize_voice.clicked.connect(self._start_synthesize_voice)
        row_actions.addWidget(self.btn_synthesize_voice, 2)

        self.btn_dub_videos = mdi_button("开始给视频配音 (替换原声)", "video")
        self.btn_dub_videos.setObjectName("primary_button")
        self.btn_dub_videos.setFixedHeight(35)
        self.btn_dub_videos.clicked.connect(self._start_dubbing_videos)
        self.btn_dub_videos.setEnabled(False)
        row_actions.addWidget(self.btn_dub_videos, 3)
        card_layout.addLayout(row_actions)

        layout.addWidget(card, 1)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：镜头重组", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(1))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.btn_next_to_step_4 = mdi_button("下一步：特效包装", "right")
        self.btn_next_to_step_4.setObjectName("primary_button")
        self.btn_next_to_step_4.setEnabled(True)
        self.btn_next_to_step_4.clicked.connect(lambda: self._go_to_step(3))
        nav_row.addWidget(self.btn_next_to_step_4)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)

    # ==================== PAGE 3: FINAL MIX ====================
    # [1·初始化]  _setup_page_final_legacy
    def _setup_page_final_legacy(self):
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)

        # Confirm paths from step 2 and step 3 - replaced with video list table
        row_select_video = QHBoxLayout()
        row_select_video.addWidget(QLabel("📹 待合成最终视频列表:"))
        row_select_video.addStretch()
        
        btn_add_mix_vid = mdi_button("选择添加视频", "plus")
        btn_add_mix_vid.setObjectName("secondary_button")
        btn_add_mix_vid.setFixedHeight(28)
        btn_add_mix_vid.clicked.connect(self._add_mix_videos)
        row_select_video.addWidget(btn_add_mix_vid)
        
        btn_clear_mix_vid = mdi_button("清空列表", "trash")
        btn_clear_mix_vid.setObjectName("secondary_button")
        btn_clear_mix_vid.setFixedHeight(28)
        btn_clear_mix_vid.clicked.connect(self._clear_mix_videos)
        row_select_video.addWidget(btn_clear_mix_vid)
        
        card_layout.addLayout(row_select_video)

        # Mix video list table widget
        self.mix_video_table = QTableWidget()
        self.mix_video_table.setWordWrap(False)
        self.mix_video_table.setColumnCount(5)
        self.mix_video_table.setHorizontalHeaderLabels(["序号", "视频文件", "来源/状态", "文件路径", "操作"])
        self.mix_video_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents) # 序号
        self.mix_video_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)      # 视频文件
        self.mix_video_table.setColumnWidth(1, 180)
        self.mix_video_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)      # 来源/状态
        self.mix_video_table.setColumnWidth(2, 120)
        self.mix_video_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)          # 完整路径
        self.mix_video_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents) # 操作
        self.mix_video_table.verticalHeader().setDefaultSectionSize(35)
        self.mix_video_table.setFixedHeight(120)
        card_layout.addWidget(self.mix_video_table)

        # Select BGM (Background Music)
        row_bgm = QHBoxLayout()
        row_bgm.addWidget(QLabel("背景音乐 (BGM):"))
        self.bgm_input = QLineEdit()
        self.bgm_input.setPlaceholderText("选择配乐音频文件...")
        row_bgm.addWidget(self.bgm_input)
        btn_sel_bgm = QPushButton("选择配乐")
        btn_sel_bgm.setObjectName("secondary_button")
        btn_sel_bgm.clicked.connect(self._select_bgm)
        row_bgm.addWidget(btn_sel_bgm)

        row_bgm.addSpacing(15)
        row_bgm.addWidget(QLabel("配乐音量:"))
        self.bgm_volume_slider = QSlider(Qt.Horizontal)
        self.bgm_volume_slider.setRange(0, 100)
        self.bgm_volume_slider.setValue(25)
        self.bgm_volume_slider.setFixedWidth(120)
        row_bgm.addWidget(self.bgm_volume_slider)
        self.volume_label = QLabel("25%")
        self.bgm_volume_slider.valueChanged.connect(self._on_bgm_volume_changed)
        row_bgm.addWidget(self.volume_label)
        card_layout.addLayout(row_bgm)

        # BGM Audition / Preview Row
        row_bgm_play = QHBoxLayout()
        
        self.btn_bgm_play = mdi_button("播放", "play")
        self.btn_bgm_play.setObjectName("secondary_button")
        self.btn_bgm_play.setFixedWidth(80)
        self.btn_bgm_play.setFixedHeight(32)
        self.btn_bgm_play.clicked.connect(self._toggle_bgm_play)
        row_bgm_play.addWidget(self.btn_bgm_play)
        
        self.btn_bgm_stop = mdi_button("停止", "stop")
        self.btn_bgm_stop.setObjectName("secondary_button")
        self.btn_bgm_stop.setFixedWidth(80)
        self.btn_bgm_stop.setFixedHeight(32)
        self.btn_bgm_stop.setEnabled(False)
        self.btn_bgm_stop.clicked.connect(self._stop_bgm_play)
        row_bgm_play.addWidget(self.btn_bgm_stop)
        
        self.bgm_progress_slider = QSlider(Qt.Horizontal)
        self.bgm_progress_slider.setRange(0, 0)
        self.bgm_progress_slider.setMinimumHeight(32)
        self.bgm_progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3c;
                height: 4px;
                background: #2c2c2e;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #3b82f6;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
        """)
        row_bgm_play.addWidget(self.bgm_progress_slider)
        
        # Connect position and duration signals for the BGM preview player
        self._bgm_player.positionChanged.connect(self._on_bgm_position_changed)
        self._bgm_player.durationChanged.connect(self._on_bgm_duration_changed)
        self.bgm_progress_slider.sliderMoved.connect(self._set_bgm_position)

        self.lbl_bgm_time = QLabel("00:00 / 00:00")
        self.lbl_bgm_time.setFixedWidth(90)
        self.lbl_bgm_time.setAlignment(Qt.AlignCenter)
        self.lbl_bgm_time.setObjectName("muted_text")
        row_bgm_play.addWidget(self.lbl_bgm_time)
        
        card_layout.addLayout(row_bgm_play)

        # Run Final mix
        self.btn_final_assemble = mdi_button("开始智能音视配乐一键合成", "celebration")
        self.btn_final_assemble.setObjectName("action_button")
        self.btn_final_assemble.setFixedHeight(40)
        self.btn_final_assemble.clicked.connect(self._start_final_mix)
        card_layout.addWidget(self.btn_final_assemble)

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
        self.final_video_list = QListWidget()
        self.final_video_list.setFixedHeight(150)
        self.final_video_list.itemDoubleClicked.connect(self._preview_final_video)
        left_vbox.addWidget(self.final_video_list)

        self.btn_open_final_dir = mdi_button("打开视频输出目录", "folder")
        self.btn_open_final_dir.setObjectName("secondary_button")
        self.btn_open_final_dir.setEnabled(False)
        self.btn_open_final_dir.clicked.connect(self._open_output_dir)
        left_vbox.addWidget(self.btn_open_final_dir)

        # Right: video preview
        right_container = QWidget()
        right_container.setStyleSheet("background-color: #000000; border-radius: 6px; border: 1px solid #27272a;")
        right_vbox = QVBoxLayout(right_container)
        right_vbox.setContentsMargins(4, 4, 4, 4)
        right_vbox.setSpacing(4)

        self.final_preview_title = QLabel("🎥 视频预览")
        self.final_preview_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        right_vbox.addWidget(self.final_preview_title)

        self.final_video_widget = QVideoWidget()
        self.final_video_widget.setMinimumHeight(150)
        right_vbox.addWidget(self.final_video_widget, 1)

        if not hasattr(self, "final_preview_player") or not self.final_preview_player:
            self.final_preview_player = QMediaPlayer()
            self.final_preview_audio = QAudioOutput()
            self.final_preview_player.setAudioOutput(self.final_preview_audio)
        self.final_preview_player.setVideoOutput(self.final_video_widget)

        res_layout.addWidget(left_container, 1)
        res_layout.addWidget(right_container, 1)
        card_layout.addWidget(result_box)
        
        # Add stretch to card_layout to compress spacing and make elements neat
        card_layout.addStretch()

        layout.addWidget(card, 1)

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = mdi_button("上一步：克隆人声", "left")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(2))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)


    # ==================== STEP HELPER ACTIONS ====================
    # [9·其他]  _decorate_video_item_widget
    def _decorate_video_item_widget(self, item):
        path = item.text().strip()
        if not path:
            return
    # [9·其他]  _show_video_context_menu
    def _show_video_context_menu(self, pos):
        item = self.video_list.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        act = QAction("🗑 从素材列表移除", menu)
        act.triggered.connect(lambda: self._remove_source_video_item(item))
        menu.addAction(act)
        menu.exec_(self.video_list.viewport().mapToGlobal(pos))
    # [9·其他]  _remove_source_video_item
    def _remove_source_video_item(self, item):
        row = self.video_list.row(item)
        if row < 0:
            return
        path = item.text().strip()
        self.video_list.takeItem(row)
        if getattr(self, "processing_video_path", "") == path:
            self.processing_video_path = ""
        # 终止正在运行的分割/挑精华 worker，避免后台残留导致后续操作被静默拦截
        self._kill_running_workers()
        self._refresh_source_root_hint()
        self._check_split_clips_exist()
    # [2·基础设施]  _kill_running_workers
    def _kill_running_workers(self):
        """终止所有可能正在后台运行的 worker（镜头分割 / 批量分割 / 挑精华）。"""
        for attr in ("worker", "highlight_worker"):
            w = getattr(self, attr, None)
            if w and w.isRunning():
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(w.pid)],
                                   capture_output=True, timeout=5)
                except Exception:
                    try:
                        w.terminate()
                    except Exception:
                        pass
                try:
                    w.wait(3000)
                except Exception:
                    pass
                setattr(self, attr, None)
        # 恢复按钮状态
        for btn_attr in ("btn_split", "btn_pick_highlights", "btn_transcribe_raw"):
            btn = getattr(self, btn_attr, None)
            if btn:
                btn.setEnabled(True)
        self.progress_bar.setVisible(False)
    # [2·基础设施]  _refresh_source_root_hint
    def _refresh_source_root_hint(self):
        paths = []
        for i in range(self.video_list.count()):
            p = self.video_list.item(i).text().strip()
            if p:
                paths.append(p)
        if not paths:
            self.folder_path_input.clear()
            return
        try:
            common_dir = os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in paths])
        except Exception:
            common_dir = os.path.dirname(os.path.abspath(paths[0]))
        self.folder_path_input.setText(common_dir)
    # [2·基础设施]  _select_folder
    def _select_folder(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget,
            "选择视频素材",
            "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;所有文件 (*.*)"
        )
        if not file_paths:
            return

        existing = set()
        for i in range(self.video_list.count()):
            t = self.video_list.item(i).text().strip()
            if t:
                existing.add(os.path.abspath(t))

        added = 0
        for p in file_paths:
            ap = os.path.abspath(p)
            if ap in existing:
                continue
            existing.add(ap)
            it = QListWidgetItem(ap)
            self.video_list.addItem(it)
            self._decorate_video_item_widget(it)
            added += 1

        log.info(f"[DIAG _select_folder] selected={len(file_paths)} added={added} list_count={self.video_list.count()}")
        if self.video_list.count() > 0 and self.video_list.currentItem() is None:
            self.video_list.setCurrentRow(0)
        self._refresh_source_root_hint()
        self._check_split_clips_exist()
        if added == 0:
            self.stage_label.setText("所选素材已在列表中，无新增。")
        else:
            self.stage_label.setText(f"已新增 {added} 个素材到列表。")

    # [3·分割]  _get_split_scenes_times
    def _get_split_scenes_times(self, splits_dir, files):
        if hasattr(self, "temp_scenes") and self.temp_scenes and len(self.temp_scenes) == len(files):
            return self.temp_scenes
        
        import cv2
        scenes = []
        current_time = 0.0
        for f in files:
            # f 可能是文件名或完整路径
            p = f if os.path.isabs(f) else os.path.join(splits_dir, f)
            cap = cv2.VideoCapture(p)
            duration = 0.0
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps > 0:
                    duration = frame_count / fps
                cap.release()
            scenes.append((current_time, current_time + duration))
            current_time += duration
        return scenes
    # [3·分割]  _parse_split_filename
    def _parse_split_filename(self, filename):
        import re
        pattern = r"_shot_(\d+)_(\d{2}-\d{2}-\d{2},\d{3})_(\d{2}-\d{2}-\d{2},\d{3})(?:_(.*))?$"
        name_without_ext, _ = os.path.splitext(filename)
        match = re.search(pattern, name_without_ext)
        if match:
            idx = int(match.group(1))
            start_str = match.group(2).replace("-", ":")
            end_str = match.group(3).replace("-", ":")
            desc = match.group(4) or ""
            return idx, start_str, end_str, desc
        return None
    # [2·基础设施]  _get_renamed_path
    def _get_renamed_path(self, old_path, idx, start_sec, end_sec, desc):
        import re
        dir_name = os.path.dirname(old_path)
        base_name = os.path.basename(old_path)
        idx_str = f"_shot_{idx:03d}"
        if idx_str in base_name:
            prefix = base_name.split(idx_str)[0]
        else:
            prefix = os.path.splitext(base_name)[0]
            if "_shot_" in prefix:
                prefix = prefix.split("_shot_")[0]
        start_str = format_seconds_to_srt_timestamp(start_sec).replace(":", "-")
        end_str = format_seconds_to_srt_timestamp(end_sec).replace(":", "-")
        safe_desc = ""
        if desc:
            desc_clean = desc.replace("\n", " ").replace("\r", " ").replace("\t", " ")
            illegal = '\\/:*?\"<>|'
            safe_desc = "".join(c for c in desc_clean if c not in illegal).strip()
            safe_desc = re.sub(r"\s+", " ", safe_desc)[:60].strip()
        if safe_desc:
            new_name = f"{prefix}_shot_{idx:03d}_{start_str}_{end_str}_{safe_desc}.mp4"
        else:
            new_name = f"{prefix}_shot_{idx:03d}_{start_str}_{end_str}.mp4"
        return os.path.abspath(os.path.join(dir_name, new_name))
    # [3·分割]  _rename_all_splits_with_metadata
    def _rename_all_splits_with_metadata(self, splits_dir, scenes, desc_dict=None):
        if not os.path.exists(splits_dir):
            return
        import re
        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
        def get_shot_idx(filename):
            parsed = self._parse_split_filename(filename)
            if parsed:
                return parsed[0]
            match = re.search(r"_shot_(\d+)", filename)
            return int(match.group(1)) if match else 999
        files.sort(key=get_shot_idx)
        new_split_clips_list = []
        new_split_descriptions = {}
        for idx_0, filename in enumerate(files):
            idx = idx_0 + 1
            old_path = os.path.abspath(os.path.join(splits_dir, filename))
            if idx_0 < len(scenes):
                start_sec, end_sec = scenes[idx_0]
            else:
                start_sec, end_sec = 0.0, 0.0
            desc = ""
            if desc_dict:
                desc = desc_dict.get(idx, "")
            if not desc:
                parsed = self._parse_split_filename(filename)
                if parsed:
                    desc = parsed[3]
            if not desc:
                desc = self.split_descriptions.get(old_path, "")
            new_path = self._get_renamed_path(old_path, idx, start_sec, end_sec, desc)
            if old_path != new_path:
                try:
                    if os.path.exists(old_path):
                        if os.path.exists(new_path) and new_path != old_path:
                            os.remove(new_path)
                        os.rename(old_path, new_path)
                        log.info(f"Renamed split: {filename} -> {os.path.basename(new_path)}")
                except Exception as e:
                    log.warning(f"Failed to rename split file {filename}: {e}")
                    new_path = old_path
            new_split_clips_list.append(new_path)
            new_split_descriptions[new_path] = desc
        self.split_clips_list = new_split_clips_list
        for p, d in new_split_descriptions.items():
            self.split_descriptions[p] = d
    # [3·分割]  _update_raw_srt_display_from_splits
    def _update_raw_srt_display_from_splits(self):
        dir_path = self.folder_path_input.text().strip()
        if not dir_path or not os.path.exists(dir_path):
            return
        splits_dir = os.path.join(dir_path, "splits")
        if not os.path.exists(splits_dir):
            return
        
        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
        if not files:
            return
            
        scenes = self._get_split_scenes_times(splits_dir, files)
        
        srt_lines = []
        for idx, f in enumerate(files, 1):
            p = os.path.join(splits_dir, f)
            norm_path = os.path.abspath(p)
            desc = self.split_descriptions.get(norm_path, f"镜头片段 {idx}")
            if idx - 1 < len(scenes):
                start_sec, end_sec = scenes[idx-1]
            else:
                start_sec, end_sec = 0.0, 0.0
                
            start_str = format_seconds_to_srt_timestamp(start_sec)
            end_str = format_seconds_to_srt_timestamp(end_sec)
            
            srt_lines.append(str(idx))
            srt_lines.append(f"{start_str} --> {end_str}")
            srt_lines.append(desc)
            srt_lines.append("")
            
        srt_content = "\n".join(srt_lines)
        if hasattr(self, "raw_srt_display"):
            self.raw_srt_display.setPlainText(srt_content)
    # [3·分割]  _save_split_srt
    def _save_split_srt(self):
        selected_item = self.video_list.currentItem()
        video_path = selected_item.text() if selected_item else ""
        if not video_path and hasattr(self, "processing_video_path") and self.processing_video_path:
            video_path = self.processing_video_path
        if not video_path:
            return
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        video_dir = os.path.dirname(video_path)
        video_workspace_dir = os.path.join(video_dir, video_basename)
        srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
        
        splits_dir = os.path.join(video_workspace_dir, "splits")
        if not os.path.exists(splits_dir):
            return
            
        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
        if not files:
            return
            
        scenes = self._get_split_scenes_times(splits_dir, files)
        
        srt_lines = []
        for idx, f in enumerate(files, 1):
            p = os.path.join(splits_dir, f)
            norm_path = os.path.abspath(p)
            desc = self.split_descriptions.get(norm_path, f"镜头片段 {idx}")
            if idx - 1 < len(scenes):
                start_sec, end_sec = scenes[idx-1]
            else:
                start_sec, end_sec = 0.0, 0.0
                
            start_str = format_seconds_to_srt_timestamp(start_sec)
            end_str = format_seconds_to_srt_timestamp(end_sec)
            
            srt_lines.append(str(idx))
            srt_lines.append(f"{start_str} --> {end_str}")
            srt_lines.append(desc)
            srt_lines.append("")
            
        srt_content = "\n".join(srt_lines)
        try:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            log.info(f"成功保存分割字幕到文件: {srt_path}")
        except Exception as e:
            log.warning(f"保存分割字幕文件失败: {e}")
    # [3·分割]  _check_split_clips_exist
    def _check_split_clips_exist(self, item=None):
        dir_path = self.folder_path_input.text().strip()
        _cur_item = self.video_list.currentItem() if hasattr(self, "video_list") else None
        _cur_text = _cur_item.text().strip() if _cur_item else ""
        _pvp = getattr(self, "processing_video_path", "")
        log.info(f"[DIAG _check_split_clips_exist] folder_path_input='{dir_path}' currentItem='{_cur_text}' processing_video_path='{_pvp}'")
        self.split_clips_list = []

        # Block signals on table during update to avoid triggering cellChanged slot
        self.split_result_table.blockSignals(True)
        self.split_result_table.setRowCount(0)
        self._pending_score_rows = []  # 待后台评分的行

        splits_dir = ""
        if dir_path and os.path.exists(dir_path):
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
            if not video_path and hasattr(self, "processing_video_path") and self.processing_video_path:
                video_path = self.processing_video_path
            log.info(f"[DIAG _check_split_clips_exist] resolved video_path='{video_path}' (source={'currentItem' if selected_item else 'processing_video_path'})")
            if video_path:
                video_basename = os.path.splitext(os.path.basename(video_path))[0]
                video_dir = os.path.dirname(video_path)
                video_workspace_dir = os.path.join(video_dir, video_basename)
                splits_dir = os.path.join(video_workspace_dir, "splits")
            else:
                # 合并分割流程：扫描所有 per-video splits 目录
                splits_dir = os.path.join(dir_path, "splits")  # 回退默认

            # Read files in splits（支持多目录扫描）
            files = []
            merged_dirs = getattr(self, "_last_merged_splits_dirs", [])
            if not video_path and merged_dirs:
                # 从所有 per-video 目录收集片段
                for md in sorted(merged_dirs):
                    if os.path.isdir(md):
                        for f in sorted(os.listdir(md)):
                            if f.lower().endswith((".mp4", ".m4v")):
                                files.append(os.path.join(md, f))
                if files:
                    splits_dir = merged_dirs[0]  # 主目录用于后续逻辑
            elif os.path.exists(splits_dir):
                files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
            log.info(f"[DIAG _check_split_clips_exist] splits_dir='{splits_dir}' files_count={len(files)}")
            
            # Try to restore split descriptions from the srt file if they are not in self.split_descriptions yet
            if files and video_path:
                video_basename = os.path.splitext(os.path.basename(video_path))[0]
                video_dir = os.path.dirname(video_path)
                video_workspace_dir = os.path.join(video_dir, video_basename)
                srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
                if not os.path.exists(srt_path):
                    srt_path = os.path.join(video_dir, f"{video_basename}.srt")
                if os.path.exists(srt_path):
                    try:
                        with open(srt_path, "r", encoding="utf-8") as f:
                            srt_content = f.read()
                        parsed_texts = parse_srt_to_descriptions(srt_content)
                        for idx, f_name in enumerate(files):
                            p_clip = os.path.join(splits_dir, f_name)
                            norm_p = os.path.abspath(p_clip)
                            if norm_p not in self.split_descriptions:
                                if idx < len(parsed_texts):
                                    self.split_descriptions[norm_p] = parsed_texts[idx]
                    except Exception as e:
                        log.warning(f"从SRT加载分割描述失败: {e}")
            
            if files:
                self.split_result_table.setRowCount(len(files))
                scenes = self._get_split_scenes_times(splits_dir, files)
                initial_desc_lines = []
                for idx, f in enumerate(files):
                    # f 可能是文件名（单目录）或完整路径（多目录）
                    if os.path.isabs(f):
                        norm_path = os.path.abspath(f)
                        display_name = os.path.basename(f)
                    else:
                        p = os.path.join(splits_dir, f)
                        norm_path = os.path.abspath(p)
                        display_name = f
                    self.split_clips_list.append(norm_path)
                    
                    parsed = self._parse_split_filename(display_name)
                    if parsed:
                        p_idx, start_str, end_str, desc = parsed
                        time_str = f"{start_str} --> {end_str}"
                    else:
                        p_idx = idx + 1
                        if idx < len(scenes):
                            start_sec, end_sec = scenes[idx]
                        else:
                            start_sec, end_sec = 0.0, 0.0
                        start_str = format_seconds_to_srt_timestamp(start_sec)
                        end_str = format_seconds_to_srt_timestamp(end_sec)
                        time_str = f"{start_str} --> {end_str}"
                        desc = self.split_descriptions.get(norm_path, "")
                    
                    if desc:
                        self.split_descriptions[norm_path] = desc

                    # 缓存先占位（后台异步评分）
                    self.split_clips_cache[norm_path] = {
                        "filename": display_name, "time_str": time_str,
                        "desc": desc, "duration": 0.0, "score": None,
                        "shot_type": "", "product": "", "model": "",
                    }

                    # Col 0: Checkbox
                    chk_item = QTableWidgetItem()
                    chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    chk_item.setCheckState(Qt.Checked)
                    chk_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 0, chk_item)

                    # Col 1: Index
                    idx_item = QTableWidgetItem(str(idx + 1))
                    idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
                    idx_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 1, idx_item)

                    # Col 2: Filename
                    file_item = QTableWidgetItem(display_name)
                    file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
                    file_item.setData(Qt.UserRole, norm_path)
                    file_item.setToolTip(norm_path)
                    self.split_result_table.setItem(idx, 2, file_item)

                    # Col 3: 景别 (shot type)
                    shot_item = QTableWidgetItem("")
                    shot_item.setFlags(shot_item.flags() & ~Qt.ItemIsEditable)
                    shot_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 3, shot_item)

                    # Col 4: 时长 (duration)
                    dur_item = QTableWidgetItem("")
                    dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
                    dur_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 4, dur_item)

                    # Col 5: 主要画面 (description, editable)
                    desc_item = QTableWidgetItem(desc)
                    desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 5, desc_item)

                    # Col 6: 产品
                    prod_item = QTableWidgetItem("")
                    prod_item.setFlags(prod_item.flags() & ~Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 6, prod_item)

                    # Col 7: 型号
                    model_item = QTableWidgetItem("")
                    model_item.setFlags(model_item.flags() & ~Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 7, model_item)

                    # Col 8: 评分 — 等待服务端分析后回填
                    score_item = QTableWidgetItem("—")
                    score_item.setFlags(score_item.flags() & ~Qt.ItemIsEditable)
                    score_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 8, score_item)

                    self._pending_score_rows.append((idx, norm_path))
                    initial_desc_lines.append(desc)
                
                # Update rewritten_srt_display
                if hasattr(self, "rewritten_srt_display"):
                    self.rewritten_srt_display.setPlainText("\n".join(initial_desc_lines))
                # Update subtitle display with split subtitles
                self._update_raw_srt_display_from_splits()
            else:
                # No split files. Display original raw srt if it exists
                if video_path:
                    video_basename = os.path.splitext(os.path.basename(video_path))[0]
                    video_dir = os.path.dirname(video_path)
                    video_workspace_dir = os.path.join(video_dir, video_basename)
                    srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
                    if not os.path.exists(srt_path):
                        srt_path = os.path.join(video_dir, f"{video_basename}.srt")
                    if os.path.exists(srt_path):
                        try:
                            with open(srt_path, "r", encoding="utf-8") as f:
                                raw_srt = f.read().strip()
                            if hasattr(self, "rewritten_srt_display"):
                                self.rewritten_srt_display.setPlainText(raw_srt)
                        except Exception as e:
                            log.warning(f"读取已存在字幕失败: {e}")
                            if hasattr(self, "rewritten_srt_display"):
                                self.rewritten_srt_display.clear()
                    else:
                        if hasattr(self, "rewritten_srt_display"):
                            self.rewritten_srt_display.clear()
                else:
                    if hasattr(self, "rewritten_srt_display"):
                        self.rewritten_srt_display.clear()
                    
        self.split_result_table.blockSignals(False)

        # 本地评分已移除，镜头分析统一通过“生成镜头分析”按钮调用服务端完成
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        # Set default directory for Step 2 and scan it
        if splits_dir and os.path.exists(splits_dir):
            self.concat_src_dir_input.setText(splits_dir)
            self._scan_concat_src_dir()
        else:
            self._available_concat_clips = []
            self._update_concat_count_lbl()
    # [3·分割]  _on_score_ready (legacy: 本地评分已移除，保留兼容)
    def _on_score_ready(self, row_idx, score):
        pass
    # [3·分割]  _on_score_all_done (legacy: 本地评分已移除，保留兼容)
    def _on_score_all_done(self):
        self._pending_score_rows = []
        # 显示之前暂存的结果对话框
        pending = getattr(self, "_pending_dialog", None)
        if pending:
            title, detail = pending
            self._pending_dialog = None
            self.stage_label.setText(f"✅ {title}")
            QMessageBox.information(self.parent_widget, title, detail)
        self.btn_next_to_step_2.setEnabled(True)
    # [3·分割]  _rate_clips (legacy: kept for compatibility, no UI now)
    def _rate_clips(self):
        """对第 2 步的镜头列表进行重新评分（旧版入口，现无可视表格，直接返回）。"""
        return

    def _on_rate_ready(self, idx, score):
        return

    def _on_rate_all_done(self):
        return

    # [3·分割]  _apply_score_filter (legacy: kept for compatibility, no UI now)
    def _apply_score_filter(self):
        return

    # [7·混音导出]  _select_bgm
    def _select_bgm(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择背景配乐",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac);;All Files (*)",
        )
        if path:
            self.bgm_input.setText(path)
    # [2·基础设施]  _select_ref_audio
    def _select_ref_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择人声克隆样本",
            "",
            "Audio Files (*.wav *.mp3 *.m4a);;All Files (*)",
        )
        if path:
            # Check if it already exists in the combo box
            for idx in range(self.ref_audio_combo.count()):
                if self.ref_audio_combo.itemData(idx) == path:
                    self.ref_audio_combo.setCurrentIndex(idx)
                    return
            
            # If not found, insert at index 0 and select it
            name = os.path.basename(path)
            self.ref_audio_combo.insertItem(0, f"本地: {name}", path)
            self.ref_audio_combo.setCurrentIndex(0)
    # [2·基础设施]  _on_ref_audio_combo_changed
    def _on_ref_audio_combo_changed(self, index):
        data = self.ref_audio_combo.currentData()
        if data == "custom":
            self.ref_audio_combo.blockSignals(True)
            self._select_ref_audio()
            self.ref_audio_combo.blockSignals(False)
        else:
            path = data or ""
            self.btn_play_ref.setEnabled(bool(path and os.path.exists(path)))
            
            # Auto-fill reference script if it matches one of our saved samples
            if path:
                from gui.voice_samples_page import load_voice_samples
                samples = load_voice_samples()
                for s in samples:
                    if s.get("path") and os.path.abspath(s.get("path")) == os.path.abspath(path):
                        self.ref_text_input.setText(s.get("ref_text", s.get("text", "")))
                        break
    # [9·其他]  _play_ref_audio
    def _play_ref_audio(self):
        path = self.ref_audio_combo.currentData()
        if path and os.path.exists(path):
            self._play_video(path)
    # [2·基础设施]  _populate_ref_audio_samples
    def _populate_ref_audio_samples(self):
        self.ref_audio_combo.blockSignals(True)
        self.ref_audio_combo.clear()
        from gui.voice_samples_page import load_voice_samples
        samples = load_voice_samples()
        samples.sort(key=lambda x: x.get("name", "").lower())
        
        for s in samples:
            self.ref_audio_combo.addItem(s.get("name"), s.get("path"))
            
        if not samples:
            self.ref_audio_combo.addItem("未找到预设声音样本", "")
            
        self.ref_audio_combo.addItem("选择本地文件...", "custom")
        
        if self.ref_audio_combo.count() > 0:
            self.ref_audio_combo.setCurrentIndex(0)
            
        self.ref_audio_combo.blockSignals(False)
        self._on_ref_audio_combo_changed(self.ref_audio_combo.currentIndex())
    # [6·配音]  _select_voice_video_dir
    def _select_voice_video_dir(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget,
            "选择需要克隆配音的视频",
            "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;所有文件 (*.*)"
        )
        if file_paths:
            dir_path = os.path.dirname(file_paths[0])
            # 先记录选中的文件，再更新输入框，避免信号先触发旧状态的目录扫描
            self.selected_voice_video_files = file_paths
            self._voice_scan_allow_dir_fallback = True
            self.voice_video_dir_input.blockSignals(True)
            self.voice_video_dir_input.setText(dir_path)
            self.voice_video_dir_input.blockSignals(False)
            self._scan_voice_video_dir()
    # [6·配音]  _on_voice_video_dir_changed
    def _on_voice_video_dir_changed(self):
        # 用户手动改目录时，清除旧的文件级选择并恢复目录扫描语义
        self.selected_voice_video_files = []
        self._voice_scan_allow_dir_fallback = True
        self._scan_voice_video_dir()
    # [6·配音]  _scan_voice_video_dir
    def _scan_voice_video_dir(self):
        if getattr(self, "_scanning_voice_dir", False):
            return
        self._scanning_voice_dir = True
        try:
            self._do_scan_voice_video_dir()
        finally:
            self._scanning_voice_dir = False
    # [6·配音]  _do_scan_voice_video_dir
    def _do_scan_voice_video_dir(self):
        dir_path = self.voice_video_dir_input.text().strip()
        self.voice_video_paths = []
        
        # Preserve user text from existing edits
        existing_texts = {}
        if hasattr(self, "row_edits") and self.row_edits:
            for i in range(self.voice_table.rowCount()):
                item_file = self.voice_table.item(i, 1)
                if item_file:
                    filepath = item_file.data(Qt.UserRole)
                    edit = self.row_edits.get(i)
                    if filepath and edit:
                        existing_texts[filepath] = edit.text().strip()

        # Clear table
        self.voice_table.setRowCount(0)
        self.row_edits = {}
        
        if not dir_path or not os.path.exists(dir_path):
            self._adjust_table_height()
            return
            
        # Scan for videos
        exts = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")
        files = []
        
        # If user explicitly selected files (或进入步骤3时自动传入的已合成视频), use them
        if hasattr(self, "selected_voice_video_files") and self.selected_voice_video_files:
            sel = [os.path.abspath(f) for f in self.selected_voice_video_files
                   if f and os.path.isfile(f)]
            if sel:
                parents = {os.path.dirname(f) for f in sel}
                current_dir = os.path.abspath(dir_path)
                if len(parents) == 1:
                    # 单目录：仅当与当前输入目录一致时使用（兼容手动选文件场景）
                    if current_dir in parents:
                        files = sel
                else:
                    # 跨目录的已合成视频（每个视频各自工作目录场景）：
                    # 直接以选中文件为准，不受单一目录限制
                    files = sel

        if not files:
            # 会话内无已合成视频且未手动选择文件/目录时（如重启后新建任务），
            # 不做整目录扫描，避免历史生成的旧视频自动出现在配音表
            if not getattr(self, "_voice_scan_allow_dir_fallback", True):
                self._adjust_table_height()
                return
            try:
                for f in os.listdir(dir_path):
                    if f.lower().endswith(exts):
                        files.append(os.path.join(dir_path, f))
            except Exception as e:
                log.warning(f"扫描视频目录失败: {e}")
                self._adjust_table_height()
                return
            
        # 去重（同一路径只保留一次）+ 存在性过滤，再排序
        files = [f for f in dict.fromkeys(files) if os.path.isfile(f)]
        files.sort(key=lambda x: os.path.basename(x).lower())
        self.voice_video_paths = files
        
        # Determine voices output directory to auto-detect already generated audios
        out_montage_dir = self._get_out_montage_dir(dir_path)
        voices_dir = os.path.join(out_montage_dir, "voices")

        self.voice_table.setRowCount(len(files))
        
        for i, filepath in enumerate(files):
            basename = os.path.basename(filepath)
            
            # Sync generated voice paths if the expected wav exists on disk
            expected_wav_path = os.path.abspath(os.path.join(voices_dir, f"voice_{i + 1}.wav"))
            if os.path.exists(expected_wav_path):
                self.generated_voice_paths[filepath] = expected_wav_path

            # Cache original script text for comparison
            if not hasattr(self, "original_texts"):
                self.original_texts = {}
            if filepath not in self.original_texts:
                original_txt = ""
                companion_txt_path = os.path.splitext(filepath)[0] + ".txt"
                if os.path.exists(companion_txt_path):
                    try:
                        with open(companion_txt_path, "r", encoding="utf-8") as f:
                            original_txt = f.read().strip()
                    except Exception:
                        pass
                self.original_texts[filepath] = original_txt

            # 0: Index
            item_idx = QTableWidgetItem(str(i + 1))
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            self.voice_table.setItem(i, 0, item_idx)
            
            # 1: Video file name
            item_file = QTableWidgetItem("")
            item_file.setToolTip(filepath)
            item_file.setFlags(item_file.flags() & ~Qt.ItemIsEditable)
            item_file.setData(Qt.UserRole, filepath)
            self.voice_table.setItem(i, 1, item_file)
            
            # 2: Script text widget inside custom VoiceRowDetailWidget
            self.voice_table.setRowHeight(i, 140)
            txt = existing_texts.get(filepath, "")
            if not txt:
                txt = self.original_texts.get(filepath, "")
            
            edit = DoubleClickLineEdit(txt)
            edit.setPlaceholderText("双击可弹窗编辑大段文案，留空则不克隆此视频的声音")
            
            # If the voice is already generated, apply the green success background style
            wav_path = self.generated_voice_paths.get(filepath, "")
            if wav_path and os.path.exists(wav_path):
                style = """
                    QLineEdit {
                        background-color: rgba(46, 204, 113, 0.25);
                        border: 1px solid #2ecc71;
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                """
            else:
                style = """
                    QLineEdit {
                        background-color: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                    QLineEdit:focus {
                        border: 1px solid #2ecc71;
                        background-color: rgba(255, 255, 255, 0.08);
                    }
                """
            edit.setStyleSheet(style)
            edit.doubleClicked.connect(lambda r=i: self._on_edit_double_clicked(r))
            
            self.row_edits[i] = edit
            
            original_text = self.original_texts.get(filepath, "")

            # Build status label
            status_text = "未生成"
            status_style = "color: #95a5a6; font-size: 11px;"
            if wav_path and os.path.exists(wav_path):
                status_text = os.path.basename(wav_path)
                status_style = "color: #2ecc71; font-weight: bold; font-size: 11px;"
            lbl_status = QLabel(f" {status_text}")
            lbl_status.setStyleSheet(status_style)

            # Build action buttons
            action_widgets = []

            btn_play = mdi_button("", "volume")
            btn_play.setToolTip("播放克隆的声音")
            btn_play.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_play.setFixedWidth(28)
            btn_play.setFixedHeight(22)
            btn_play.setEnabled(bool(wav_path and os.path.exists(wav_path)))
            btn_play.clicked.connect(lambda checked=False, path=filepath: self._on_btn_play_clicked(path))
            action_widgets.append(btn_play)

            btn_export = mdi_button("", "save")
            btn_export.setToolTip("导出该克隆声音")
            btn_export.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_export.setFixedWidth(28)
            btn_export.setFixedHeight(22)
            btn_export.setEnabled(bool(wav_path and os.path.exists(wav_path)))
            btn_export.clicked.connect(lambda checked=False, path=filepath: self._on_btn_export_clicked(path))
            action_widgets.append(btn_export)

            btn_compare = mdi_button("", "balance-scale")
            btn_compare.setToolTip("对比与编辑文案")
            btn_compare.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_compare.setFixedWidth(28)
            btn_compare.setFixedHeight(22)
            btn_compare.clicked.connect(lambda checked=False, idx=i: self._on_btn_compare_clicked(idx))
            action_widgets.append(btn_compare)

            btn_regen = mdi_button("", "refresh")
            btn_regen.setToolTip("仅重新生成该声音")
            btn_regen.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_regen.setFixedWidth(28)
            btn_regen.setFixedHeight(22)
            btn_regen.clicked.connect(lambda checked=False, path=filepath: self._on_btn_regen_clicked(path))
            action_widgets.append(btn_regen)

            # Length mode toggle button (video-based vs audio-based)
            current_mode = self.voice_length_mode.get(filepath, "video")
            btn_length_mode = mdi_button("", "video" if current_mode == "video" else "audio")
            btn_length_mode.setToolTip(
                "以视频长度为准（点击切换为以音频长度为准）" if current_mode == "video"
                else "以音频长度为准，视频不够用最后一帧补足（点击切回）"
            )
            btn_length_mode.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_length_mode.setFixedWidth(28)
            btn_length_mode.setFixedHeight(22)

            def make_toggle(fp=filepath, btn=btn_length_mode):
                def toggle():
                    current = self.voice_length_mode.get(fp, "video")
                    new_mode = "audio" if current == "video" else "video"
                    self.voice_length_mode[fp] = new_mode
                    btn.setIcon(mdi_icon("audio" if new_mode == "audio" else "video"))
                    btn.setToolTip(
                        "以音频长度为准，视频不够用最后一帧补足（点击切回）" if new_mode == "audio"
                        else "以视频长度为准（点击切换为以音频长度为准）"
                    )
                return toggle

            btn_length_mode.clicked.connect(make_toggle())
            action_widgets.append(btn_length_mode)

            # Play original video button (next to filename in top row)
            btn_play_original = mdi_button("", "play")
            btn_play_original.setToolTip("播放原视频")
            btn_play_original.setStyleSheet("padding: 0px; font-size: 10px;")
            btn_play_original.setFixedWidth(24)
            btn_play_original.setFixedHeight(20)
            btn_play_original.clicked.connect(lambda checked=False, path=filepath: self._play_video(path))

            # Play dubbed video button (last action button)
            dubbed_path = self.dubbed_video_paths.get(filepath, "")
            has_dubbed = bool(dubbed_path and os.path.exists(dubbed_path))
            btn_play_dubbed = mdi_button("", "projector")
            btn_play_dubbed.setToolTip("播放配音后的视频" if has_dubbed else "尚未生成配音视频")
            btn_play_dubbed.setStyleSheet("padding: 0px; font-size: 10px;")
            btn_play_dubbed.setFixedWidth(28)
            btn_play_dubbed.setFixedHeight(22)
            btn_play_dubbed.setEnabled(has_dubbed)
            if has_dubbed:
                btn_play_dubbed.clicked.connect(lambda checked=False, path=dubbed_path: self._play_video(path))
            action_widgets.append(btn_play_dubbed)

            detail_widget = VoiceRowDetailWidget(
                basename, filepath, original_text, edit, wav_path,
                status_widget=lbl_status, action_widgets=action_widgets,
                video_duration_sec=get_media_duration(filepath),
                voice_duration_sec=self.voice_audio_durations.get(filepath, 0.0),
                play_original_btn=btn_play_original
            )
            self.voice_table.setCellWidget(i, 1, detail_widget)

        self._adjust_table_height()
    # [2·基础设施]  _adjust_table_height
    def _adjust_table_height(self):
        row_count = self.voice_table.rowCount()
        if row_count == 0:
            self.voice_table.setFixedHeight(240)
            return

        header_height = self.voice_table.horizontalHeader().height()
        if header_height <= 0:
            header_height = 38
            
        total_rows_height = row_count * 140

        frame_width = self.voice_table.frameWidth() * 2
        margins = self.voice_table.contentsMargins()
        margin_height = margins.top() + margins.bottom()

        # Compute perfect fit height including vertical space margins and borders
        target_height = header_height + total_rows_height + frame_width + margin_height + 4
        # Cap height between a minimum of 350px and a maximum of 600px to ensure scrolling if there are many files
        capped_height = min(max(target_height, 350), 600)
        self.voice_table.setFixedHeight(capped_height)
    # [9·其他]  _on_edit_double_clicked
    def _on_edit_double_clicked(self, row_idx):
        edit = self.row_edits.get(row_idx)
        if edit:
            dialog = TextEditDialog(f"编辑第 {row_idx + 1} 行配音文案", edit.text(), self.parent_widget)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                edit.setText(new_text)
    # [7·混音导出]  _on_btn_compare_clicked
    def _on_btn_compare_clicked(self, row_idx):
        item_file = self.voice_table.item(row_idx, 1)
        if not item_file:
            return
        filepath = item_file.data(Qt.UserRole)
        if not filepath:
            return
            
        original_text = self.original_texts.get(filepath, "")
        edit = self.row_edits.get(row_idx)
        current_text = edit.text().strip() if edit else ""
        
        dialog = ScriptCompareDialog(original_text, current_text, self.parent_widget)
        if dialog.exec() == QDialog.Accepted:
            new_text = dialog.get_text()
            if edit:
                edit.setText(new_text)
    # [8·事件回调]  _on_row_progress
    def _on_row_progress(self, row_idx, value):
        edit = self.row_edits.get(row_idx)
        if edit:
            if value <= 0:
                style = """
                    QLineEdit {
                        background-color: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                    QLineEdit:focus {
                        border: 1px solid #2ecc71;
                        background-color: rgba(255, 255, 255, 0.08);
                    }
                """
            elif value >= 100:
                style = """
                    QLineEdit {
                        background-color: rgba(46, 204, 113, 0.25);
                        border: 1px solid #2ecc71;
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                """
            else:
                ratio = value / 100.0
                style = f"""
                    QLineEdit {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(46, 204, 113, 0.35), stop:{ratio} rgba(46, 204, 113, 0.35), stop:{ratio} rgba(255, 255, 255, 0.05), stop:1 rgba(255, 255, 255, 0.05));
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }}
                """
            edit.setStyleSheet(style)
    # [9·其他]  _on_btn_play_clicked
    def _on_btn_play_clicked(self, video_path):
        wav_path = self.generated_voice_paths.get(video_path, "")
        if wav_path and os.path.exists(wav_path):
            self._play_audio(wav_path)
    # [7·混音导出]  _on_btn_export_clicked
    def _on_btn_export_clicked(self, video_path):
        wav_path = self.generated_voice_paths.get(video_path, "")
        if not wav_path or not os.path.exists(wav_path):
            return
        
        save_path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "导出克隆声音",
            os.path.basename(wav_path),
            "Audio Files (*.wav);;All Files (*)"
        )
        if save_path:
            try:
                shutil.copy2(wav_path, save_path)
                QMessageBox.information(self.parent_widget, "导出成功", f"人声音频成功导出至：\n{save_path}")
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "导出失败", f"无法导出文件: {e}")
    # [6·配音]  _play_audio
    def _play_audio(self, wav_path):
        """试听配音：同一音频 播放→暂停→继续 切换；切换其它音频时重新播放。"""
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtCore import QUrl
            
            if not hasattr(self, "_media_player") or not self._media_player:
                self._media_player = QMediaPlayer()
                self._audio_output = QAudioOutput()
                self._media_player.setAudioOutput(self._audio_output)
            
            target = os.path.normpath(os.path.abspath(wav_path))
            current = os.path.normpath(self._media_player.source().toLocalFile() or "")
            state = self._media_player.playbackState()

            # 同一条音频：播放中→暂停；已暂停→继续播放
            if current == target:
                if state == QMediaPlayer.PlayingState:
                    self._media_player.pause()
                    return
                if state == QMediaPlayer.PausedState:
                    self._media_player.play()
                    return

            # 切换到其它音频：停止当前并从头播放新音频
            self._media_player.stop()
            self._media_player.setSource(QUrl.fromLocalFile(wav_path))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception as e:
            log.error(f"播放音频失败: {e}")
    # [9·其他]  _on_btn_regen_clicked
    def _on_btn_regen_clicked(self, video_path):
        for i in range(self.voice_table.rowCount()):
            item = self.voice_table.item(i, 1)
            if item and item.data(Qt.UserRole) == video_path:
                edit = self.row_edits.get(i)
                text = edit.text().strip() if edit else ""
                if not text:
                    QMessageBox.warning(self.parent_widget, "配音文案为空", "该行文案为空，无法生成克隆人声。")
                    return
                
                self._start_single_synthesize(i, video_path, text)
                break
    # [6·配音]  _start_single_synthesize
    def _start_single_synthesize(self, row_idx, video_path, text):
        if self.voice_worker and self.voice_worker.isRunning():
            QMessageBox.warning(self.parent_widget, "合成中", "当前有克隆人声合成任务正在运行，请等待其完成。")
            return
            
        ref_audio = self.ref_audio_combo.currentData() or ""
        if ref_audio == "custom":
            ref_audio = ""
            
        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未上传声音样本", "请先上传/选择参考声音样本 (wav/mp3)！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")
            return

        dir_path = self.voice_video_dir_input.text().strip()
        out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        
        self.btn_synthesize_voice.setEnabled(False)
        self.btn_next_to_step_4.setEnabled(False)
        self.btn_dub_videos.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText(f"正在重新生成第 {row_idx+1} 个视频 of 克隆人声...")

        # Reset the target progress style
        self._on_row_progress(row_idx, 0)

        out_wav_path = os.path.abspath(os.path.join(out_montage_dir, "voices", f"voice_{row_idx + 1}.wav"))
        tasks = [(row_idx, text, video_path, out_wav_path)]

        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.text().strip(),
            voice_mode="api",
            voice_api_url=self.api_url_input.text().strip(),
            voice_cli_checkpoint="",
            temp_dir=out_montage_dir,
            inference_timesteps=self.tts_steps_spin.value() if hasattr(self, "tts_steps_spin") else 10,
            cfg_value=self.tts_cfg_spin.value() if hasattr(self, "tts_cfg_spin") else 2.0,
            speed_min=self.tts_speed_min_spin.value() if hasattr(self, "tts_speed_min_spin") else 0.9,
            speed_max=self.tts_speed_max_spin.value() if hasattr(self, "tts_speed_max_spin") else 1.2,
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.voice_worker.row_progress.connect(self._on_row_progress)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()
    # [3·分割]  _install_scenedetect
    def _install_scenedetect(self):
        if hasattr(self, "_install_thread") and self._install_thread and self._install_thread.isRunning():
            return

        class InstallThread(BaseWorker):
            stage = Signal(str)
            finished = Signal()

            def run(self):
                try:
                    self.stage.emit("正在安装 scenedetect[opencv]...")
                    cmd = [sys.executable, "-m", "pip", "install", "scenedetect[opencv]"]
                    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
                    if p.returncode != 0:
                        raise RuntimeError(p.stdout + "\n" + p.stderr)
                    self.finished.emit()
                except Exception as e:
                    self.error.emit(str(e))

        if hasattr(self, "btn_install_deps"):
            self.btn_install_deps.setEnabled(False)
            
        self.stage_label.setText("正在执行依赖安装，请稍候...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._install_thread = InstallThread()
        self._install_thread.stage.connect(lambda txt: self.stage_label.setText(txt))
        
        def on_ok():
            if hasattr(self, "btn_install_deps"):
                self.btn_install_deps.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.stage_label.setText("依赖库 scenedetect[opencv] 安装成功！")
            QMessageBox.information(self.parent_widget, "成功", "镜头分割依赖库安装成功！")
            
            # Update dependency indicator
            self.has_scenedetect_dep = True
            self.dep_status_widget.layout().takeAt(0).widget().deleteLater()
            lbl = QLabel("✅ 镜头分割依赖就绪")
            lbl.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self.dep_status_widget.layout().addWidget(lbl)

        def on_err(err):
            if hasattr(self, "btn_install_deps"):
                self.btn_install_deps.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.stage_label.setText("安装失败。")
            QMessageBox.critical(self.parent_widget, "安装失败", f"安装依赖失败：\n{err}")

        self._install_thread.finished.connect(on_ok)
        self._install_thread.error.connect(on_err)
        self._install_thread.start()


    # ==================== CONTROLLER RUN WORKERS ====================

    # --- Step 1 single video split ---
    # [3·分割]  _get_product_prompt
    def _get_product_prompt(self):
        """读取步骤1的「主要产品提示词」（去首尾空白，未创建控件时返回空）。"""
        inp = getattr(self, "product_prompt_input", None)
        return (inp.text().strip() if inp else "")
    # [3·分割]  _start_split
    def _start_split(self):
        """合并后的智能镜头分割入口：对列表中所有视频逐个处理。

        每个视频：先做镜头分割；无法分割（无切点或分割失败）的，
        自动挑取一段精华片段。全部片段统一写入共享 splits 目录。
        """
        if (self.worker and self.worker.isRunning()) or \
           (getattr(self, "highlight_worker", None) and self.highlight_worker.isRunning()):
            QMessageBox.warning(self.parent_widget, "任务进行中",
                                "上一个任务仍在运行中，请等待完成或先停止。")
            return

        paths = []
        for i in range(self.video_list.count()):
            txt = self.video_list.item(i).text().strip()
            if txt:
                paths.append(txt)
        if not paths:
            QMessageBox.warning(self.parent_widget, "无视频", "上方列表中没有可处理的视频。")
            return

        dur = self.spin_highlight_sec.value()

        # 主要产品提示词（选填）：非空时分割完成后自动触发围绕该产品的镜头分析
        product_prompt = self._get_product_prompt()
        self._split_product_prompt = product_prompt
        if product_prompt:
            log.info(f"[智能分割] 主要产品提示词: {product_prompt}")

        # 确定共享根目录（用于界面显示）
        shared_root = self.folder_path_input.text().strip()
        if not shared_root or not os.path.isdir(shared_root):
            try:
                shared_root = os.path.commonpath([os.path.dirname(p) for p in paths])
            except Exception:
                shared_root = os.path.dirname(paths[0])
            self.folder_path_input.setText(shared_root)

        # 每个视频的分割输出到「视频目录/视频名/splits/」（与 _check_split_clips_exist 一致）
        per_video_splits = []
        for p in paths:
            vdir = os.path.dirname(p)
            vbase = os.path.splitext(os.path.basename(p))[0]
            per_video_splits.append(os.path.join(vdir, vbase, "splits"))

        # 显示摘要
        if len(set(per_video_splits)) == 1:
            out_summary = per_video_splits[0]
        else:
            out_summary = f"{len(per_video_splits)} 个视频各自工作目录\n(例: {per_video_splits[0]})"

        prompt_line = ""
        if product_prompt:
            prompt_line = f"· AI 镜头分析将围绕产品「{product_prompt}」精确评分（分割完成后自动分析）；\n"

        reply = QMessageBox.question(
            self.parent_widget, "智能镜头分割",
            f"将对列表中全部 {len(paths)} 个视频逐个处理：\n"
            f"· 能做镜头分割的，先做镜头分割；\n"
            f"· 无法分割的，自动挑出一段约 {dur:.0f} 秒的精华片段。\n"
            f"{prompt_line}\n"
            f"输出目录：{out_summary}\n"
            f"注意：会先清空各目录里已有的分镜片段。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 清空各 per-video splits 目录里旧的分镜片段
        try:
            for sp_dir in set(per_video_splits):
                os.makedirs(sp_dir, exist_ok=True)
                for f in os.listdir(sp_dir):
                    if "_shot_" in f and f.lower().endswith((".mp4", ".m4v")):
                        try:
                            os.remove(os.path.join(sp_dir, f))
                        except Exception:
                            pass
        except Exception as e:
            QMessageBox.warning(self.parent_widget, "无法准备目录", f"创建/清理 splits 目录失败：\n{e}")
            return

        self._merged_queue = list(paths)
        self._merged_total = len(paths)
        self._merged_done = 0
        self._merged_split_ok = 0
        self._merged_hl_ok = 0
        self._merged_fail = 0
        self._merged_fail_msgs = []
        self._merged_per_video_splits = per_video_splits  # 每个视频对应的 splits 目录
        self._merged_hl_duration = dur

        self.btn_split.setEnabled(False)
        if hasattr(self, "btn_gen_shot_analysis"):
            self.btn_gen_shot_analysis.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._process_next_merged_video()
    # [3·分割]  _process_next_merged_video
    def _process_next_merged_video(self):
        if not self._merged_queue:
            self._on_merged_all_finished()
            return

        video_path = self._merged_queue.pop(0)
        self._merged_cur_video = video_path
        idx = self._merged_done + 1
        fname = os.path.basename(video_path)

        # 当前视频的 per-video splits 目录
        cur_splits_dir = self._merged_per_video_splits[self._merged_done]
        self._merged_cur_splits_dir = cur_splits_dir

        if not os.path.exists(video_path):
            self._merged_fail += 1
            self._merged_fail_msgs.append(f"{fname}: 文件不存在")
            self._merged_done += 1
            self._process_next_merged_video()
            return

        self.stage_label.setText(f"智能镜头分割 ({idx}/{self._merged_total})：{fname}")
        self.progress_bar.setValue(int(self._merged_done * 100 / max(1, self._merged_total)))

        self.worker = PySceneDetectWorker(
            video_path=video_path,
            output_dir=cur_splits_dir,
            threshold=self.threshold_spin.value(),
            min_scene_len=int(self.min_len_spin.value())
        )
        self.worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.worker.finished.connect(self._on_merged_split_done)
        self.worker.error.connect(self._on_merged_split_error)
        self.worker.start()
    # [3·分割]  _on_merged_split_done
    def _on_merged_split_done(self, out_dir, count, scenes):
        video_path = getattr(self, "_merged_cur_video", "")
        fname = os.path.basename(video_path) if video_path else ""
        if count > 0:
            self._merged_split_ok += 1
            log.info(f"[合并分割] {fname} 分割出 {count} 个镜头")
            self._rename_video_splits_with_metadata(self._merged_cur_splits_dir, video_path, scenes)
            self._merged_done += 1
            self._process_next_merged_video()
        else:
            log.info(f"[合并分割] {fname} 未检测到镜头切点，改为挑精华")
            self._run_merged_highlight(video_path)
    # [3·分割]  _on_merged_split_error
    def _on_merged_split_error(self, err):
        video_path = getattr(self, "_merged_cur_video", "")
        fname = os.path.basename(video_path) if video_path else ""
        log.warning(f"[合并分割] {fname} 镜头分割失败，改为挑精华: {err}")
        self._run_merged_highlight(video_path)
    # [3·分割]  _run_merged_highlight
    def _run_merged_highlight(self, video_path):
        fname = os.path.basename(video_path)
        idx = self._merged_done + 1
        self.stage_label.setText(f"无法分割，挑取精华 ({idx}/{self._merged_total})：{fname}")
        self.highlight_worker = BestClipWorker(
            video_path=video_path,
            output_dir=self._merged_cur_splits_dir,
            duration_sec=self._merged_hl_duration,
            shot_index=1,
            clear_dir=False,
        )
        self.highlight_worker.finished.connect(self._on_merged_highlight_done)
        self.highlight_worker.error.connect(self._on_merged_highlight_error)
        self.highlight_worker.start()
    # [3·分割]  _on_merged_highlight_done
    def _on_merged_highlight_done(self, out_path, start, end):
        self._merged_hl_ok += 1
        log.info(f"[合并分割] 精华片段已生成：{out_path} [{start:.2f}-{end:.2f}]")
        self._merged_done += 1
        self._process_next_merged_video()
    # [3·分割]  _on_merged_highlight_error
    def _on_merged_highlight_error(self, err):
        video_path = getattr(self, "_merged_cur_video", "")
        fname = os.path.basename(video_path) if video_path else ""
        last_line = (err or "").strip().splitlines()[-1] if err else "未知错误"
        self._merged_fail += 1
        self._merged_fail_msgs.append(f"{fname}: {last_line[:100]}")
        log.error(f"[合并分割] {fname} 挑精华也失败：{err}")
        self._merged_done += 1
        self._process_next_merged_video()
    # [3·分割]  _on_merged_all_finished
    def _on_merged_all_finished(self):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_gen_shot_analysis"):
            self.btn_gen_shot_analysis.setEnabled(True)
            self.btn_gen_shot_analysis.setStyleSheet(
                "background-color: #2d6a4f; color: #b7e4c7; font-weight: bold; "
                "border: 1px solid #40916c; border-radius: 4px; padding: 4px 12px;")
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)

        # 让下方表格读取各 per-video splits 目录
        self.processing_video_path = ""
        self.video_list.setCurrentItem(None)
        self.temp_scenes = []
        # 保存所有 per-video splits 目录，供 _check_split_clips_exist 扫描
        self._last_merged_splits_dirs = list(set(self._merged_per_video_splits))

        msg = (f"处理完成：分割 {self._merged_split_ok} 个，挑精华 {self._merged_hl_ok} 个，"
               f"失败 {self._merged_fail} 个（共 {self._merged_total} 个视频）。")
        detail = msg
        if self._merged_fail_msgs:
            detail += "\n\n失败明细：\n" + "\n".join(self._merged_fail_msgs[:8])

        self.stage_label.setText("✅ " + msg)
        self.progress_bar.setRange(0, 0)
        self._pending_dialog = ("智能镜头分割完成", detail)
        self._check_split_clips_exist()

        # 填写了主要产品提示词时，自动触发围绕该产品的镜头分析
        if getattr(self, "_split_product_prompt", ""):
            log.info(f"[智能分割] 检测到产品提示词，自动触发镜头分析: {self._split_product_prompt}")
            self.stage_label.setText(
                f"✅ {msg} 正在按产品提示词「{self._split_product_prompt}」分析镜头...")
            self._gen_shot_analysis()
    # [3·分割]  _rename_video_splits_with_metadata
    def _rename_video_splits_with_metadata(self, splits_dir, video_path, scenes):
        """重命名单个视频刚分割出的片段（写入时间戳元数据），仅处理该视频前缀的文件。"""
        if not os.path.exists(splits_dir) or not video_path:
            return
        import re
        basename = os.path.splitext(os.path.basename(video_path))[0]
        prefix = f"{basename}_shot_"
        files = [f for f in os.listdir(splits_dir)
                 if f.startswith(prefix) and f.lower().endswith((".mp4", ".m4v"))]
        def get_shot_idx(filename):
            parsed = self._parse_split_filename(filename)
            if parsed:
                return parsed[0]
            match = re.search(r"_shot_(\d+)", filename)
            return int(match.group(1)) if match else 999
        files.sort(key=get_shot_idx)
        for idx_0, filename in enumerate(files):
            idx = idx_0 + 1
            old_path = os.path.abspath(os.path.join(splits_dir, filename))
            if idx_0 < len(scenes):
                start_sec, end_sec = scenes[idx_0]
            else:
                start_sec, end_sec = 0.0, 0.0
            desc = ""
            parsed = self._parse_split_filename(filename)
            if parsed:
                desc = parsed[3]
            if not desc:
                desc = self.split_descriptions.get(old_path, "")
            new_path = self._get_renamed_path(old_path, idx, start_sec, end_sec, desc)
            if old_path != new_path:
                try:
                    if os.path.exists(new_path) and new_path != old_path:
                        os.remove(new_path)
                    os.rename(old_path, new_path)
                except Exception as e:
                    log.warning(f"Failed to rename split file {filename}: {e}")
    # [3·分割]  _on_split_finished（旧单视频入口保留，合并流程不再使用）
    def _on_split_finished(self, out_dir, count, scenes):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self._check_split_clips_exist()

        if count == 0:
            self.progress_bar.setValue(100)
            self.stage_label.setText("⚠ 未检测到镜头切点，请调低分割阈值后重试。")
            QMessageBox.information(
                self.parent_widget, "未检测到镜头切点",
                f"该视频画面切换不明显，PySceneDetect 未能分出任何镜头。\n\n"
                f"当前分割阈值为 {self.threshold_spin.value():.0f}（值越小越敏感）。\n"
                f"建议把阈值调低（如 27 或更低）后重新分割。"
            )
            return

        self.stage_label.setText(f"✅ 镜头分割完成！共切出 {count} 个镜头。正在评分...")
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.temp_scenes = scenes
        self.temp_out_dir = out_dir
        self.temp_count = count
        self._pending_dialog = ("分割完成", f"智能镜头分割完成，共切出 {count} 个镜头。")

        # Rename splits with timestamps
        self._rename_all_splits_with_metadata(out_dir, scenes)
    # [3·分割]  _on_split_error
    def _on_split_error(self, err):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self._check_split_clips_exist()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 运行失败")
        QMessageBox.critical(self.parent_widget, "运行错误", f"处理过程中发生错误：\n{err}")

    # --- Step 1 batch "pick best N seconds" highlights ---
    # [3·分割]  _start_pick_highlights
    def _start_pick_highlights(self):
        if (self.worker and self.worker.isRunning()) or \
           (getattr(self, "highlight_worker", None) and self.highlight_worker.isRunning()):
            QMessageBox.warning(self.parent_widget, "任务进行中",
                                "上一个任务仍在运行中，请等待完成或先停止。")
            return

        paths = []
        for i in range(self.video_list.count()):
            txt = self.video_list.item(i).text().strip()
            if txt:
                paths.append(txt)
        if not paths:
            QMessageBox.warning(self.parent_widget, "无视频", "上方列表中没有可处理的视频。")
            return

        dur = self.spin_highlight_sec.value()

        # 同型号的多个视频，精华片段统一放进一个共享 splits 目录，便于下一步组合混剪。
        # 共享目录 = 扫描目录/splits（与下方表格读取的位置一致）；扫描目录为空时退回视频公共父目录。
        shared_root = self.folder_path_input.text().strip()
        if not shared_root or not os.path.isdir(shared_root):
            try:
                shared_root = os.path.commonpath([os.path.dirname(p) for p in paths])
            except Exception:
                shared_root = os.path.dirname(paths[0])
            # 同步扫描目录框，保证下方表格读取的 splits 与写入位置一致
            self.folder_path_input.setText(shared_root)
        shared_splits = os.path.join(shared_root, "splits")

        reply = QMessageBox.question(
            self.parent_widget, "批量挑精华片段",
            f"将对列表中全部 {len(paths)} 个视频，各挑出一段约 {dur:.0f} 秒的精华片段"
            f"（清晰+适度运动），统一写入：\n{shared_splits}\n"
            f"作为下一步组合混剪的素材。\n\n"
            f"注意：会先清空该 splits 目录里已有的分镜片段。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 一次性清空共享 splits 目录里旧的分镜片段
        try:
            os.makedirs(shared_splits, exist_ok=True)
            for f in os.listdir(shared_splits):
                if "_shot_" in f and f.lower().endswith((".mp4", ".m4v")):
                    try:
                        os.remove(os.path.join(shared_splits, f))
                    except Exception:
                        pass
        except Exception as e:
            QMessageBox.warning(self.parent_widget, "无法准备目录", f"创建/清理 splits 目录失败：\n{e}")
            return

        self._hl_queue = paths
        self._hl_total = len(paths)
        self._hl_done = 0
        self._hl_ok = 0
        self._hl_fail = 0
        self._hl_fail_msgs = []
        self._hl_duration = dur
        self._hl_shared_splits = shared_splits
        self._hl_shot_index = 0

        self.btn_split.setEnabled(False)
        self.btn_pick_highlights.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._pick_highlight_next()
    # [3·分割]  _pick_highlight_next
    def _pick_highlight_next(self):
        if not self._hl_queue:
            self._on_highlights_all_finished()
            return

        video_path = self._hl_queue.pop(0)
        idx = self._hl_done + 1
        fname = os.path.basename(video_path)

        if not os.path.exists(video_path):
            self._hl_fail += 1
            self._hl_fail_msgs.append(f"{fname}: 文件不存在")
            self._hl_done += 1
            self._pick_highlight_next()
            return

        self.stage_label.setText(f"挑精华片段 ({idx}/{self._hl_total})：{fname}")

        # 所有视频写入同一个共享 splits，序号递增，互不覆盖
        self._hl_shot_index += 1
        self.highlight_worker = BestClipWorker(
            video_path=video_path,
            output_dir=self._hl_shared_splits,
            duration_sec=self._hl_duration,
            shot_index=self._hl_shot_index,
            clear_dir=False,
        )
        self.highlight_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.highlight_worker.finished.connect(self._on_highlight_finished)
        self.highlight_worker.error.connect(self._on_highlight_error)
        self.highlight_worker.start()
    # [3·分割]  _on_highlight_finished
    def _on_highlight_finished(self, out_path, start, end):
        self._hl_ok += 1
        log.info(f"精华片段已生成：{out_path}  [{start:.2f}-{end:.2f}]")
        self._hl_done += 1
        self._pick_highlight_next()
    # [3·分割]  _on_highlight_error
    def _on_highlight_error(self, err):
        self._hl_fail += 1
        last_line = (err or "").strip().splitlines()[-1] if err else "未知错误"
        self._hl_fail_msgs.append(last_line[:120])
        log.error(f"批量挑精华单条失败：{err}")
        self._hl_done += 1
        self._pick_highlight_next()
    # [3·分割]  _on_highlights_all_finished
    def _on_highlights_all_finished(self):
        self.btn_split.setEnabled(True)
        self.btn_pick_highlights.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)

        # 让下方表格读取共享 splits
        self.processing_video_path = ""
        self.video_list.setCurrentItem(None)
        self.temp_scenes = []
        self._check_split_clips_exist()

        msg = (f"批量挑精华完成：成功 {self._hl_ok} 个，失败 {self._hl_fail} 个"
               f"（共 {self._hl_total}）。")
        detail = msg
        if self._hl_fail_msgs:
            detail += "\n\n失败明细：\n" + "\n".join(self._hl_fail_msgs[:8])

        self.stage_label.setText("✅ " + msg + " 正在评分...")
        self.progress_bar.setRange(0, 0)
        self._pending_dialog = ("批量挑精华完成", detail)

        # Trigger vision analysis on highlight clips
        if self._hl_ok > 0 and os.path.exists(self._hl_shared_splits):
            files = sorted([f for f in os.listdir(self._hl_shared_splits)
                           if f.lower().endswith((".mp4", ".m4v"))])
            scenes = self._get_split_scenes_times(self._hl_shared_splits, files) if files else []
            self._trigger_vision_on_dir(self._hl_shared_splits, scenes, "批量挑精华")

    # [4·文案脚本]  _trigger_vision_on_dir
    def _trigger_vision_on_dir(self, splits_dir, scenes, source_label="镜头分割"):
        """对指定 splits 目录中的所有片段运行视觉AI画面分析。

        供批量分割、批量挑精华等批量路径复用。
        """
        vision_model = self.main_window.ai_config.get("llm_vision_model", "")

        if not vision_model:
            log.info(f"[{source_label}] 未配置视觉模型，跳过画面描述生成")
            return

        if not os.path.exists(splits_dir):
            return

        files = sorted([f for f in os.listdir(splits_dir)
                       if f.lower().endswith((".mp4", ".m4v"))])
        if not files:
            return

        split_video_paths = [os.path.join(splits_dir, f) for f in files]

        # Try to find SRT for the parent video
        raw_srt = ""
        srt_segments = []
        parent_dir = os.path.dirname(splits_dir)
        if parent_dir:
            for f_name in os.listdir(parent_dir):
                if f_name.endswith(".srt"):
                    srt_path = os.path.join(parent_dir, f_name)
                    try:
                        with open(srt_path, "r", encoding="utf-8") as sf:
                            raw_srt = sf.read().strip()
                        if raw_srt:
                            srt_segments = parse_srt(raw_srt)
                        break
                    except Exception:
                        pass

        status_msg = f"🤖 正在使用本地视觉AI分析{source_label}画面内容..."
        if srt_segments:
            status_msg += "（结合字幕）"
        self.stage_label.setText(status_msg)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Save scenes for the finished handler
        self._trigger_scenes = scenes
        self._trigger_splits_dir = splits_dir

        self.vision_desc_worker = LocalVisionDescWorker(
            vision_model=vision_model,
            split_video_paths=split_video_paths,
            scenes=scenes if scenes else [],
            srt_text=raw_srt,
            srt_segments=srt_segments,
        )
        self.vision_desc_worker.finished.connect(self._on_trigger_vision_finished)
        self.vision_desc_worker.error.connect(self._on_desc_error)
        self.vision_desc_worker.start()
    # [4·文案脚本]  _on_trigger_vision_finished
    def _on_trigger_vision_finished(self, desc_json):
        """批量路径视觉分析完成回调。"""
        import json as _json
        try:
            desc_dict_raw = _json.loads(desc_json)
            desc_dict = {int(k): v for k, v in desc_dict_raw.items()}
        except Exception as e:
            log.warning(f"_on_trigger_vision_finished - JSON解析失败: {e}")
            desc_dict = {}

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 画面文案描述生成完毕！（本地视觉AI）")

        splits_dir = getattr(self, "_trigger_splits_dir", "")
        scenes = getattr(self, "_trigger_scenes", [])
        if splits_dir and os.path.exists(splits_dir) and scenes:
            self._rename_all_splits_with_metadata(splits_dir, scenes, desc_dict)
            self._save_split_srt()

        self._check_split_clips_exist()

    # [4·文案脚本]  _on_desc_error
    def _on_desc_error(self, err):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 画面描述生成失败")
        log.warning(f"大模型批量画面描述生成失败: {err}")
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        if video_path:
            base_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(base_dir, video_basename, "splits")
            if os.path.exists(splits_dir) and hasattr(self, "temp_scenes"):
                self._rename_all_splits_with_metadata(splits_dir, self.temp_scenes)
                self._save_split_srt()
        self._check_split_clips_exist()
        QMessageBox.warning(
            self.parent_widget,
            "描述生成失败",
            f"大模型批量分析描述失败，已采用空白默认值，您可以双击单元格手动编辑描述文案。\n\n错误信息：{err}"
        )
    # [9·其他]  _preview_table_item
    def _preview_table_item(self, item):
        row = item.row()
        file_item = self.split_result_table.item(row, 2)
        if file_item:
            path = file_item.data(Qt.UserRole)
            if path and os.path.exists(path):
                self._preview_shot(path, row)
    # [8·事件回调]  _preview_shot
    def _preview_shot(self, clip_path, row=None):
        """预览单个分镜头。

        优先用 ffplay 从镜头起始时间点直接播放：
        - 镜头文件名带时间戳（_shot_xxx_起_止）时，从原始素材的对应时间点
          定点播放该镜头时长，无需从头等待；
        - 其它情况直接播放镜头片段文件本身。
        找不到 ffplay 时回退为系统默认播放器。
        """
        if not clip_path or not os.path.exists(clip_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到视频文件:\n{clip_path}")
            return

        # 解析镜头在原始素材中的起止时间（优先文件名，其次表格时长列/缓存）
        start_sec, end_sec = 0.0, 0.0
        parsed = self._parse_split_filename(os.path.basename(clip_path))
        if parsed:
            try:
                start_sec = float(parsed[1].replace(",", "."))
                end_sec = float(parsed[2].replace(",", "."))
            except Exception:
                start_sec, end_sec = 0.0, 0.0
        if start_sec <= 0.0 and end_sec <= 0.0 and row is not None:
            cached = self.split_clips_cache.get(os.path.abspath(clip_path))
            if cached:
                time_str = cached.get("time_str", "")
                try:
                    s_part, e_part = time_str.split("-->")
                    def _to_sec(t):
                        t = t.strip().replace(",", ".")
                        h, m, s = t.split(":")
                        return int(h) * 3600 + int(m) * 60 + float(s)
                    start_sec, end_sec = _to_sec(s_part), _to_sec(e_part)
                except Exception:
                    pass

        duration_sec = max(0.5, end_sec - start_sec) if end_sec > start_sec else 0.0

        # 尝试用 ffplay 定点预览（播放完该镜头自动退出）
        try:
            from utils.platform_utils import find_ffplay, create_no_window_flag
            ffplay = find_ffplay()
            if ffplay and os.path.isfile(ffplay):
                window_title = os.path.basename(clip_path)
                cmd = [ffplay, "-autoexit", "-window_title", window_title]
                if start_sec > 0.0 or duration_sec > 0.0:
                    # 优先用镜头片段文件 + 定点起始；无时间戳信息时直接播完整片段
                    if start_sec > 0.0:
                        cmd += ["-ss", f"{start_sec:.3f}"]
                    if duration_sec > 0.0:
                        cmd += ["-t", f"{duration_sec:.3f}"]
                cmd.append(clip_path)
                subprocess.Popen(cmd, creationflags=create_no_window_flag())
                self.stage_label.setText(
                    f"▶ 正在预览镜头（起点 {start_sec:.1f}s，时长 {duration_sec:.1f}s，播完自动关闭）")
                return
        except Exception as e:
            log.warning(f"ffplay 预览失败，回退默认播放器: {e}")

        self._play_video(clip_path)
    # [8·事件回调]  _preview_shot_by_row
    def _preview_shot_by_row(self, row):
        """供表格预览按钮调用：按行号预览对应分镜头。"""
        tbl = getattr(self, "split_result_table", None)
        if tbl is None:
            return
        file_item = tbl.item(row, 2)
        if not file_item:
            return
        path = file_item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self._preview_shot(path, row)
    # [8·事件回调]  _preview_selected_shot
    def _preview_selected_shot(self):
        """「预览选中镜头」按钮入口：预览表格当前选中的分镜头。"""
        tbl = getattr(self, "split_result_table", None)
        if tbl is None:
            return
        row = tbl.currentRow()
        if row < 0:
            QMessageBox.information(self.parent_widget, "未选中镜头",
                                    "请先在表格中单击选中一行镜头，再点「预览选中镜头」。")
            return
        self._preview_shot_by_row(row)
    # [8·事件回调]  _on_table_cell_changed
    def _on_table_cell_changed(self, row, col):
        if col == 5:  # 主要画面列（可编辑）
            file_item = self.split_result_table.item(row, 2)
            desc_item = self.split_result_table.item(row, col)
            if file_item and desc_item:
                old_path = file_item.data(Qt.UserRole)
                if old_path and os.path.exists(old_path):
                    new_desc = desc_item.text().strip()
                    if hasattr(self, "temp_scenes") and row < len(self.temp_scenes):
                        start_sec, end_sec = self.temp_scenes[row]
                    else:
                        start_sec, end_sec = 0.0, 0.0
                    new_path = self._get_renamed_path(old_path, row + 1, start_sec, end_sec, new_desc)
                    if old_path != new_path:
                        try:
                            self.split_result_table.blockSignals(True)
                            if os.path.exists(new_path):
                                os.remove(new_path)
                            os.rename(old_path, new_path)
                            file_item.setData(Qt.UserRole, new_path)
                            file_item.setText(os.path.basename(new_path))
                            if old_path in self.split_descriptions:
                                del self.split_descriptions[old_path]
                            self.split_descriptions[new_path] = new_desc
                            if old_path in self.split_clips_list:
                                idx_clip = self.split_clips_list.index(old_path)
                                self.split_clips_list[idx_clip] = new_path
                            if old_path in self.split_clips_cache:
                                self.split_clips_cache[new_path] = self.split_clips_cache.pop(old_path)
                            self.split_result_table.blockSignals(False)
                            log.info(f"Renamed edited split file: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")
                        except Exception as e:
                            self.split_result_table.blockSignals(False)
                            log.warning(f"Failed to rename edited split file: {e}")
                    else:
                        self.split_descriptions[old_path] = new_desc
                    if hasattr(self, "rewritten_srt_display"):
                        lines = []
                        for r in range(self.split_result_table.rowCount()):
                            d_item = self.split_result_table.item(r, 5)
                            if d_item:
                                lines.append(d_item.text().strip())
                        self.rewritten_srt_display.setPlainText("\n".join(lines))
                    self._save_split_srt()

    # --- Step 1 subtitle generation execution ---
    # [4·文案脚本]  _start_transcribe_raw
    def _start_transcribe_raw(self):
        if hasattr(self, "transcribe_raw_worker") and self.transcribe_raw_worker and self.transcribe_raw_worker.isRunning():
            return

        selected_item = self.video_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self.parent_widget, "请选择视频", "请先在上方列表中选中一个视频文件。")
            return

        video_path = selected_item.text()
        self.processing_video_path = video_path
        if not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "视频不存在", f"未找到该视频文件：\n{video_path}")
            return

        # Ensure transcription dependency is ready
        if not self._transcription_deps_ok():
            QMessageBox.warning(
                self.parent_widget,
                "依赖缺失",
                "未检测到转写依赖（torch 或 whisperx）。\n"
                "请先前往菜单栏中的“环境配置”页面，或者“视频转文字”页面安装对应的依赖环境。"
            )
            return

        from config.paths import TMP_DIR, WHISPER_MODELS_DIR
        video_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        video_workspace_dir = os.path.join(video_dir, video_basename)
        os.makedirs(video_workspace_dir, exist_ok=True)
        
        # Audio temp path inside TMP_DIR
        audio_path = os.path.join(TMP_DIR, f"{video_basename}_raw_audio.wav")
        # Subtitle output in the workspace directory
        output_srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")

        self.btn_split.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        from apps.whisperx.whisperx_worker import WhisperXTranscribeWorker
        self.transcribe_raw_worker = WhisperXTranscribeWorker(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_srt_path,
            model_name="large-v3",
            language=None,  # Auto detect
            task_type="transcribe",
            multi_mode=False,
            download_root=WHISPER_MODELS_DIR,
            device_mode="cuda"  # Default to CUDA for speed
        )

        self.transcribe_raw_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.transcribe_raw_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.transcribe_raw_worker.finished.connect(self._on_transcribe_raw_finished)
        self.transcribe_raw_worker.error.connect(self._on_transcribe_raw_error)
        self.transcribe_raw_worker.start()
    # [4·文案脚本]  _on_transcribe_raw_finished
    def _on_transcribe_raw_finished(self, srt_content, srt_path):
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

        self.pending_srt_path = srt_path
        self.raw_unpunctuated_srt = srt_content

        if llm_model and srt_content.strip():
            self.stage_label.setText("🎙️ 正在使用 AI 模型自动优化字幕标点符号...")
            self.progress_bar.setRange(0, 0) # Infinite spinner
            
            self.punc_srt_worker = PunctuationSRTLLMWorker(llm_model, srt_content)
            self.punc_srt_worker.finished.connect(self._on_punc_srt_finished)
            self.punc_srt_worker.error.connect(self._on_punc_srt_error)
            self.punc_srt_worker.start()
        else:
            self._finalize_transcribe_raw(srt_content, srt_path)
    # [4·文案脚本]  _on_punc_srt_finished
    def _on_punc_srt_finished(self, srt_punctuated):
        try:
            with open(self.pending_srt_path, "w", encoding="utf-8") as f:
                f.write(srt_punctuated)
            self._finalize_transcribe_raw(srt_punctuated, self.pending_srt_path, info_msg=" (AI标点已优化)")
        except Exception as e:
            log.warning(f"保存AI优化后的字幕失败: {e}")
            self._finalize_transcribe_raw(self.raw_unpunctuated_srt, self.pending_srt_path)
    # [4·文案脚本]  _on_punc_srt_error
    def _on_punc_srt_error(self, err):
        log.warning(f"AI优化字幕标点失败: {err}，将采用原始字幕。")
        self._finalize_transcribe_raw(self.raw_unpunctuated_srt, self.pending_srt_path)
    # [4·文案脚本]  _finalize_transcribe_raw
    def _finalize_transcribe_raw(self, srt_content, srt_path, info_msg=""):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText(f"✅ 字幕生成完成{info_msg}")
        if hasattr(self, "raw_srt_display"):
            self.raw_srt_display.setPlainText(srt_content)
        QMessageBox.information(
            self.parent_widget,
            "生成字幕成功",
            f"字幕已成功生成{info_msg}！\n\n已保存至：\n{srt_path}"
        )
        # 如果是从生成画面描述触发的转录，自动继续
        if getattr(self, "_pending_gen_descriptions", False):
            self._pending_gen_descriptions = False
            self._gen_split_descriptions()
    # [4·文案脚本]  _on_transcribe_raw_error
    def _on_transcribe_raw_error(self, err):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 字幕生成失败")
        QMessageBox.critical(
            self.parent_widget,
            "字幕生成错误",
            f"处理过程中发生错误：\n{err}"
        )
    # [4·文案脚本]  _transcription_deps_ok
    def _transcription_deps_ok(self):
        # 纯远程 ASR 模式：转写由远程服务完成，不再依赖本地 torch / whisperx。
        return True


    # --- Step 2 Concat execution ---
    # [5·拼接合成]  _start_assemble_video
    def _start_assemble_video(self):
        if self.concat_worker and self.concat_worker.isRunning():
            return

        if not self.split_clips_list:
            QMessageBox.warning(self.parent_widget, "无可排列镜头",
                                "当前没有勾选任何镜头，无法执行镜头重组。\n\n"
                                "可能原因：镜头评分低于筛选阈值，已被自动取消勾选。\n"
                                "解决方法：在上方镜头列表中手动勾选镜头，或降低评分筛选阈值后重新过滤。")
            return

        dir_path = self.concat_src_dir_input.text().strip()
        if not dir_path or not os.path.exists(dir_path):
            dir_path = self.folder_path_input.text().strip()
            
        if not dir_path:
            QMessageBox.warning(self.parent_widget, "路径无效", "请先选择素材目录或待排列镜头目录。")
            return

        out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        self._pending_out_montage_dir = out_montage_dir

        logic = self.logic_combo.currentData() if hasattr(self, "logic_combo") else "random"

        # ── 🎯 按文案智能匹配：先用 LLM 为每行文案匹配最贴合的镜头，再按行序拼接 ──
        if logic == "script":
            script_text = self.match_script_edit.toPlainText().strip() if hasattr(self, "match_script_edit") else ""
            if not script_text:
                QMessageBox.warning(self.parent_widget, "文案为空",
                                    "智能匹配模式需要口播文案。\n请在文案框中粘贴口播文案（每行一句）。")
                return
            llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")
            if not llm_model:
                QMessageBox.warning(self.parent_widget, "未配置大模型",
                                    "智能匹配需要配置大模型。\n请先在「环境配置」中配置 LLM 模型。")
                return

            # 无描述的镜头无法参与语义匹配，提示但不阻断（LLM 会按文件名兜底）
            no_desc = sum(1 for c in self.split_clips_list
                          if not self.split_descriptions.get(os.path.abspath(c), "").strip()
                          and not self.split_descriptions.get(c, "").strip())
            if no_desc == len(self.split_clips_list):
                QMessageBox.warning(self.parent_widget, "镜头无画面描述",
                                    "勾选的镜头都没有画面描述，无法做语义匹配。\n"
                                    "请先在「镜头分割」步骤生成画面描述文案。")
                return

            self.btn_assemble_video.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.stage_label.setText("🎯 正在用大模型为每句文案匹配最贴合的镜头...")

            self.script_match_worker = ScriptMatchLLMWorker(
                model=llm_model,
                rewritten_text=script_text,
                candidate_clips=list(self.split_clips_list),
                split_descriptions=self.split_descriptions,
            )
            self.script_match_worker.finished.connect(self._on_script_match_finished)
            self.script_match_worker.error.connect(self._on_script_match_error)
            self.script_match_worker.start()
            return

        # ── 随机洗牌：使用全部已选镜头生成“预合成方案”，供人工删改/调序并确认后再正式合成 ──
        target_clip_count = len(self.split_clips_list)

        batch_count = int(self.batch_count_spin.value())
        randomness_val = self.randomness_combo.currentData() if hasattr(self, "randomness_combo") else "medium"
        duration_limit = int(self.duration_limit_combo.currentData()) if hasattr(self, "duration_limit_combo") else 30
        plan_clips_list = self._build_precompose_plans(
            clips=self.split_clips_list,
            target_clip_count=target_clip_count,
            batch_count=batch_count,
            randomness=randomness_val,
            duration_limit_sec=duration_limit,
        )
        if not plan_clips_list:
            QMessageBox.warning(self.parent_widget, "未生成方案", "未能生成预合成方案，请检查是否已勾选镜头。")
            return
        self._load_precompose_plans(plan_clips_list, out_montage_dir)
        self.stage_label.setText(f"✅ 预合成方案已生成：{len(plan_clips_list)} 条，请检查后确认合成")
        self.progress_bar.setVisible(False)
        QMessageBox.information(
            self.parent_widget,
            "预合成完成",
            f"已生成 {len(plan_clips_list)} 条预合成方案。\n"
            "可在下方删除/调序镜头，确认无误后点击“确认合成视频”。"
        )
    # [4·文案脚本]  _on_script_match_finished
    def _on_script_match_finished(self, matched_paths, matched_descs):
        """LLM 匹配完成：生成 1 条按文案顺序的预合成方案，待用户确认合成。"""
        out_montage_dir = getattr(self, "_pending_out_montage_dir", "")
        plan = [{
            "clips": list(matched_paths),
            "deleted_flags": [False] * len(matched_paths),
            "descriptions": list(matched_descs),
            "mode": "script",
        }]
        self._load_precompose_plans(plan, out_montage_dir)
        self.stage_label.setText(f"🎯 匹配完成：{len(matched_paths)} 句文案已配齐，请确认合成")
        self.progress_bar.setVisible(False)
    # [4·文案脚本]  _on_script_match_error
    def _on_script_match_error(self, err):
        self.btn_assemble_video.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 文案镜头匹配失败")
        QMessageBox.critical(self.parent_widget, "智能匹配失败",
                             f"大模型匹配文案与镜头时出错：\n{err}\n\n可切换回「随机洗牌」模式继续。")
    # [5·拼接合成]  _launch_concat_worker
    def _launch_concat_worker(self, selected_clips, out_montage_dir, recombine_mode,
                              target_clip_count, batch_count, randomness,
                              selected_descriptions_list=None,
                              beat_times=None, music_path="", music_range=None):
        self.btn_assemble_video.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.concat_worker = VideoConcatWorker(
            selected_clips=selected_clips,
            output_dir=out_montage_dir,
            layout_mode=self.layout_combo.currentData(),
            recombine_mode=recombine_mode,
            target_clip_count=target_clip_count,
            batch_count=batch_count,
            split_descriptions=self.split_descriptions,
            randomness=randomness,
            selected_descriptions_list=selected_descriptions_list,
            transition=self.transition_combo.currentData() if hasattr(self, "transition_combo") else "fade",
            beat_times=beat_times,
            music_path=music_path,
            music_range=music_range,
        )
        self.concat_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.concat_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.concat_worker.finished.connect(self._on_concat_finished)
        self.concat_worker.error.connect(self._on_concat_error)
        self.concat_worker.start()
    # [8·事件回调]  _on_logic_combo_changed
    def _on_logic_combo_changed(self):
        logic = self.logic_combo.currentData() if hasattr(self, "logic_combo") else "random"
        is_script = (logic == "script")

        # 智能匹配模式：镜头数量由文案行数决定；每批结果相同故固定生成 1 个
        self.lbl_batch_count.setVisible(not is_script)
        self.batch_count_spin.setVisible(not is_script)

        # 时长限制：两种模式都展示（随机模式控制视频时长，文案模式控制生成文案时长）
        if hasattr(self, "lbl_duration_limit") and hasattr(self, "duration_limit_combo"):
            self.lbl_duration_limit.setText("文案时长限制:" if is_script else "时长限制:")
            self.lbl_duration_limit.setVisible(True)
            self.duration_limit_combo.setVisible(True)

        if hasattr(self, "lbl_randomness") and hasattr(self, "randomness_combo"):
            self.lbl_randomness.setVisible(not is_script)
            self.randomness_combo.setVisible(not is_script)

        if hasattr(self, "match_script_edit"):
            self.match_script_edit.setVisible(is_script)

        # AI 生成文案按钮：仅在智能匹配模式下可见
        if hasattr(self, "btn_gen_script"):
            self.btn_gen_script.setVisible(is_script)

        # 「合成视频生成文案」按钮：仅在随机洗牌模式下可见
        if hasattr(self, "btn_batch_scene_copy"):
            self.btn_batch_scene_copy.setVisible(not is_script)

        if not is_script:
            self.batch_count_spin.setEnabled(True)
            self.batch_count_spin.setValue(self._recommend_batch_count())
            if hasattr(self, "randomness_combo"):
                self.randomness_combo.setEnabled(True)
                self.randomness_combo.setCurrentIndex(0) # 中 (保留同场景)
        self._update_batch_count_recommendation()
    # [4·文案脚本]  _on_gen_script_clicked
    def _on_gen_script_clicked(self):
        """智能匹配模式：根据已勾选的镜头素材描述，调用 AI 生成口播文案（受时长限制约束）。"""
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model = (cfg.get("llm_model", "") or "deepseek-v4-flash").strip()
        if not model:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 模型名称。")
            return

        # 收集已勾选的镜头素材及其描述
        checked_clips = []
        clip_descriptions = []
        # 收集已勾选的镜头素材及其描述
        checked_clips = []
        clip_descriptions = []
        for path in self.split_clips_list:
            norm_path = os.path.abspath(path)
            checked_clips.append(norm_path)
            # 获取描述：先查 split_descriptions，再查缓存
            desc = self.split_descriptions.get(norm_path, "").strip()
            if not desc:
                cache = self.split_clips_cache.get(norm_path, {})
                desc = cache.get("desc", "").strip() if isinstance(cache, dict) else ""
            clip_descriptions.append(desc if desc else f"（镜头片段 {os.path.basename(norm_path)}）")

        if not checked_clips:
            QMessageBox.warning(self.parent_widget, "无素材",
                                "请先在待排列镜头列表中勾选要用于生成文案的镜头。")
            return

        # 获取产品信息
        info = self._ensure_shared_product_info()
        if info is None:
            return
        brand, product, model_name, extra = info

        # 获取时长限制
        duration_limit = int(self.duration_limit_combo.currentData()) if hasattr(self, "duration_limit_combo") else 30

        # 禁用按钮防止重复点击
        self.btn_gen_script.setEnabled(False)
        self.stage_label.setText(f"🤖 正在根据 {len(clip_descriptions)} 个镜头素材生成口播文案（时长限制 {duration_limit} 秒）...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # 启动 worker
        self._gen_script_worker = GenScriptWorker(
            "", "", model, clip_descriptions,
            brand, product, model_name, extra, duration_limit
        )
        self._gen_script_worker.finished.connect(self._on_gen_script_finished)
        self._gen_script_worker.error.connect(self._on_gen_script_error)
        self._gen_script_worker.start()
    # [4·文案脚本]  _on_gen_script_finished
    def _on_gen_script_finished(self, script_text):
        """AI 生成文案完成：写入文案框，恢复 UI。"""
        self.btn_gen_script.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ AI 文案生成完成，可编辑后点击「镜头重组」进行智能匹配")

        if hasattr(self, "match_script_edit"):
            self.match_script_edit.setPlainText(script_text)

        QMessageBox.information(
            self.parent_widget, "文案已生成",
            f"AI 已根据 {script_text.count(chr(10)) + 1} 个镜头素材生成口播文案。\n"
            f"可在文案框中编辑调整，确认后点击「镜头重组」进行智能匹配。")
    # [4·文案脚本]  _on_gen_script_error
    def _on_gen_script_error(self, err):
        """AI 生成文案失败：恢复 UI，提示错误。"""
        self.btn_gen_script.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ AI 文案生成失败")
        QMessageBox.critical(self.parent_widget, "文案生成失败",
                             f"调用大模型生成文案时出错：\n{err}")
    # [5·拼接合成]  _on_concat_finished
    def _on_concat_finished(self, paths):
        self.btn_assemble_video.setEnabled(True)
        self.progress_bar.setValue(100)
        if self._confirming_plan_index is not None:
            idx = self._confirming_plan_index
            self._confirming_plan_index = None
            if 0 <= idx < len(self.precompose_plans) and paths:
                out_path = paths[0]
                plan = self.precompose_plans[idx]
                plan["output_path"] = out_path
                plan["confirmed"] = True
                self.stage_label.setText(f"✅ 预合成 {idx + 1} 已确认合成")
                self._refresh_precompose_list(select_index=idx)
                if hasattr(self, "btn_batch_scene_copy"):
                    self.btn_batch_scene_copy.setEnabled(bool(self._collect_assembled_paths()))
                self._update_confirm_all_button()
                if getattr(self, "_confirm_queue", None):
                    self._confirm_next_in_queue()
                else:
                    QMessageBox.information(
                        self.parent_widget,
                        "确认合成成功",
                        f"预合成 {idx + 1} 已输出为视频：\n{out_path}"
                    )
            return

        self.stage_label.setText(f"✅ 批量排列完成，共生成 {len(paths)} 个视频！")
        self.assembled_clips_list_widget.clear()
        self.precompose_plans = []
        if hasattr(self, "btn_batch_scene_copy"):
            self.btn_batch_scene_copy.setEnabled(bool(paths))
        if paths:
            for i, p in enumerate(paths):
                self.precompose_plans.append({
                    "clips": [],
                    "deleted_flags": [],
                    "mode": "random",
                    "descriptions": [],
                    "confirmed": True,
                    "output_path": p,
                    "out_dir": os.path.dirname(p),
                })
                self._add_assembled_row(i, p)

            first_item = self.assembled_clips_list_widget.item(0)
            self.assembled_clips_list_widget.setCurrentItem(first_item)
            self._on_assembled_item_clicked(first_item)
            self._update_confirm_all_button()

            QMessageBox.information(
                self.parent_widget,
                "排列生成成功",
                f"批量镜头排列生成完毕，共生成 {len(paths)} 个视频文件，已保存至输出目录中。"
            )
    # [5·拼接合成]  _on_concat_error
    def _on_concat_error(self, err):
        self.btn_assemble_video.setEnabled(True)
        self._confirming_plan_index = None
        self._confirm_queue = []
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 排列失败")
        QMessageBox.critical(self.parent_widget, "排列错误", f"处理过程中发生错误：\n{err}")


    # --- Step 3 Voice synthesis execution ---
    # [4·文案脚本]  _show_ai_rewrite_settings
    def _show_ai_rewrite_settings(self):
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("文案生成设置")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e5e7eb;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QLabel {
                color: #d1d5db;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QSlider::groove:horizontal {
                border: 1px solid #4b5563;
                height: 8px;
                background: #2d2d2d;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #3b82f6;
                border: 1px solid #2563eb;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(QLabel("文案生成自由度设置"))
        desc = QLabel("控制AI改写文案时的创造性程度：\n80-100% = 最小润色，保持原文字词句式不变\n50-79% = 较大幅度改写，使用不同表达方式，更有网感\n20-49% = 大幅重构，显著改变句式词汇\n0-19% = 彻底重写，完全不同的词句，最大化爆款潜力")
        desc.setStyleSheet("color: #9ca3af; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        row_slider = QHBoxLayout()
        row_slider.addWidget(QLabel("0%"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int((1.0 - self.ai_rewrite_temperature) * 100))
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(10)
        row_slider.addWidget(slider, 1)
        row_slider.addWidget(QLabel("100%"))

        self._freedom_value_label = QLabel(f"当前: {slider.value()}%")
        self._freedom_value_label.setStyleSheet("font-weight: bold; color: #60a5fa; font-size: 14px;")
        self._freedom_value_label.setAlignment(Qt.AlignCenter)

        def on_slider_changed(val):
            self._freedom_value_label.setText(f"当前: {val}%")

        slider.valueChanged.connect(on_slider_changed)
        layout.addLayout(row_slider)
        layout.addWidget(self._freedom_value_label)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: transparent; color: #d1d5db; border: none;")
        btn_cancel.clicked.connect(dialog.reject)
        btn_box.addWidget(btn_cancel)
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(dialog.accept)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

        if dialog.exec() == QDialog.Accepted:
            freedom_pct = slider.value()
            self.ai_rewrite_temperature = 1.0 - (freedom_pct / 100.0)
    # [4·文案脚本]  _batch_ai_rewrite_scripts
    def _batch_ai_rewrite_scripts(self):
        if hasattr(self, "batch_rewrite_worker") and self.batch_rewrite_worker and self.batch_rewrite_worker.isRunning():
            return

        # 1. Check configs
        ai_config = getattr(self.main_window, "ai_config", {})
        model = ai_config.get("llm_model", "").strip()
        
        if not model:
            QMessageBox.warning(self.parent_widget, "未配置AI大模型", "请先在“设置”或“AI模型配置”中配置 LLM 模型名称。")
            return
            
        # 2. Build tasks
        tasks = []
        for i in range(self.voice_table.rowCount()):
            item_file = self.voice_table.item(i, 1)
            if item_file:
                filepath = item_file.data(Qt.UserRole)
                original_text = self.original_texts.get(filepath, "")
                if not original_text:
                    edit = self.row_edits.get(i)
                    original_text = edit.text().strip() if edit else ""
                
                if original_text:
                    tasks.append((i, original_text))
                    
        if not tasks:
            QMessageBox.warning(self.parent_widget, "无可改写内容", "当前列表中没有可改写的视频或文案。")
            return
            
        # 3. Disable UI and start progress
        self.btn_batch_ai_rewrite.setEnabled(False)
        self.btn_synthesize_voice.setEnabled(False)
        self.btn_dub_videos.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("正在调用AI批量修改文案...")
        
        # 4. Start worker
        self.batch_rewrite_worker = BatchAITextRewriteWorker("", "", model, tasks, self.ai_rewrite_temperature)
        self.batch_rewrite_worker.row_finished.connect(self._on_batch_rewrite_row_finished)
        self.batch_rewrite_worker.progress.connect(self.progress_bar.setValue)
        self.batch_rewrite_worker.finished.connect(self._on_batch_rewrite_finished)
        self.batch_rewrite_worker.error.connect(self._on_batch_rewrite_error)
        self.batch_rewrite_worker.start()
    # [4·文案脚本]  _on_batch_rewrite_row_finished
    def _on_batch_rewrite_row_finished(self, row_idx, content):
        edit = self.row_edits.get(row_idx)
        if edit:
            edit.setText(content)
    # [4·文案脚本]  _on_batch_rewrite_finished
    def _on_batch_rewrite_finished(self):
        self.btn_batch_ai_rewrite.setEnabled(True)
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.stage_label.setText("✅ 一键AI修改全部文案完成！")
        QMessageBox.information(self.parent_widget, "成功", "批量AI文案修改润色完成！")
    # [4·文案脚本]  _on_batch_rewrite_error
    def _on_batch_rewrite_error(self, err):
        self.btn_batch_ai_rewrite.setEnabled(True)
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ AI修改文案失败")
        QMessageBox.critical(self.parent_widget, "AI修改失败", f"批量修改失败：\n{err}")
    # [6·配音]  _start_synthesize_voice
    def _start_synthesize_voice(self):
        if self.voice_worker and self.voice_worker.isRunning():
            return

        ref_audio = self.ref_audio_combo.currentData() or ""
        if ref_audio == "custom":
            ref_audio = ""

        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未上传声音样本", "请先上传/选择参考声音样本 (wav/mp3)！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")
            return

        # 检查空闲显存是否足够运行 VoxCPM（约需 6GB），不足则停止 Ollama 释放
        try:
            import subprocess as _sp
            r = _sp.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=0x08000000)
            free_mb = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 99999
            if free_mb < 6144:
                self.stage_label.setText(f"空闲显存 {free_mb}MB 不足，声音克隆可能失败...")
            else:
                self.stage_label.setText(f"空闲显存 {free_mb}MB 充足，开始声音克隆...")
        except Exception as e:
            log.warning(f"显存检查失败（不影响声音克隆）: {e}")

        # Build tasks from the table
        tasks = []
        dir_path = self.voice_video_dir_input.text().strip()
        if not dir_path or not os.path.exists(dir_path):
            QMessageBox.warning(self.parent_widget, "路径无效", "请选择有效的视频输入目录。")
            return

        out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        os.makedirs(os.path.join(out_montage_dir, "voices"), exist_ok=True)

        for i in range(self.voice_table.rowCount()):
            item_file = self.voice_table.item(i, 1)
            edit = self.row_edits.get(i)
            if item_file and edit:
                video_path = item_file.data(Qt.UserRole)
                text = edit.text().strip()
                if text:
                    out_wav_path = os.path.abspath(os.path.join(out_montage_dir, "voices", f"voice_{i+1}.wav"))
                    tasks.append((i, text, video_path, out_wav_path))

        if not tasks:
            QMessageBox.warning(self.parent_widget, "文案为空", "没有检测到任何有配音文案的视频。请在表格的“配音文案”栏输入内容。")
            return

        # Reset all row progress styles
        for i in range(self.voice_table.rowCount()):
            self._on_row_progress(i, 0)

        self.btn_synthesize_voice.setEnabled(False)
        self.btn_next_to_step_4.setEnabled(False)
        self.btn_dub_videos.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.text().strip(),
            voice_mode="api",
            voice_api_url=self.api_url_input.text().strip(),
            voice_cli_checkpoint="",
            temp_dir=out_montage_dir,
            inference_timesteps=self.tts_steps_spin.value() if hasattr(self, "tts_steps_spin") else 10,
            cfg_value=self.tts_cfg_spin.value() if hasattr(self, "tts_cfg_spin") else 2.0,
            speed_min=self.tts_speed_min_spin.value() if hasattr(self, "tts_speed_min_spin") else 0.9,
            speed_max=self.tts_speed_max_spin.value() if hasattr(self, "tts_speed_max_spin") else 1.2,
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.voice_worker.row_progress.connect(self._on_row_progress)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()
    # [6·配音]  _on_voice_finished
    def _on_voice_finished(self, results):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 克隆人声音频生成完成！")

        # Merge results to self.generated_voice_paths
        for vid, wav in results.items():
            self.generated_voice_paths[vid] = wav
            # Calculate and store audio duration
            dur = get_media_duration(wav)
            if dur > 0:
                self.voice_audio_durations[vid] = dur
            
        # Refresh the table display
        self._scan_voice_video_dir()
        
        if self.generated_voice_paths:
            self.btn_next_to_step_4.setEnabled(True)
            self._update_final_inputs_label()

        failures = list(getattr(self.voice_worker, "failures", []) or [])
        if failures:
            self.stage_label.setText(
                f"⚠ 合成完成：成功 {len(results)} 个，失败 {len(failures)} 个（已跳过）")
            detail = "\n".join(f"· 第 {r + 1} 个：{m}" for r, _v, m in failures[:8])
            more = "" if len(failures) <= 8 else f"\n…… 等共 {len(failures)} 个失败"
            QMessageBox.warning(
                self.parent_widget,
                "部分合成失败",
                f"批量人声克隆完成：成功 {len(results)} 个，失败 {len(failures)} 个（已跳过，可单独重试）。\n\n"
                f"{detail}{more}\n\n"
                f"提示：失败多为 VoxCPM 显存不足/文案过长，可重启服务或缩短该条文案后重试。")
        else:
            QMessageBox.information(
                self.parent_widget,
                "合成成功",
                f"批量人声克隆合成完毕，共生成 {len(results)} 个音频文件。"
            )
    # [6·配音]  _on_voice_error
    def _on_voice_error(self, err):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(bool(self.generated_voice_paths))
        self.btn_next_to_step_4.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 合成失败")
        QMessageBox.critical(self.parent_widget, "人声合成错误", f"处理过程中发生错误：\n{err}")
    # [7·混音导出]  _start_dubbing_videos
    def _start_dubbing_videos(self):
        if self.dub_worker and self.dub_worker.isRunning():
            return
            
        dir_path = self.voice_video_dir_input.text().strip()
        if not dir_path or not os.path.exists(dir_path):
            QMessageBox.warning(self.parent_widget, "路径无效", "请选择有效的视频输入目录。")
            return
            
        out_montage_dir = self._get_out_montage_dir(dir_path)
        dubbed_dir = os.path.abspath(os.path.join(out_montage_dir, "dubbed"))
        os.makedirs(dubbed_dir, exist_ok=True)
        
        # Build tasks: (video_path, voice_wav_path, output_video_path, text)
        tasks = []
        add_subs = self.chk_add_subtitles.isChecked()
        # 花字设置
        fancy_enabled = self.chk_fancy_text.isChecked() if hasattr(self, "chk_fancy_text") else False
        fancy_style = self.fancy_style_combo.currentData() if hasattr(self, "fancy_style_combo") else "gold"
        fancy_words = []
        if fancy_enabled and hasattr(self, "fancy_text_input"):
            raw = self.fancy_text_input.text().strip()
            if raw:
                fancy_words = [w.strip() for w in raw.replace("，", ",").split(",") if w.strip()]
        for vid, wav in self.generated_voice_paths.items():
            if os.path.exists(vid) and os.path.exists(wav):
                out_vid_name = f"dubbed_{os.path.basename(vid)}"
                out_vid_path = os.path.join(dubbed_dir, out_vid_name)
                
                # Retrieve matching script text from the voice table for this video
                text = ""
                for r in range(self.voice_table.rowCount()):
                    item_file = self.voice_table.item(r, 1)
                    if item_file and os.path.abspath(item_file.data(Qt.UserRole)) == os.path.abspath(vid):
                        edit = self.row_edits.get(r)
                        if edit:
                            text = edit.text().strip()
                        break
                        
                tasks.append((vid, wav, out_vid_path, text))
                
        if not tasks:
            QMessageBox.warning(self.parent_widget, "缺少音频", "尚未生成任何对应的克隆人声音频。请先点击“开始批量克隆人声合成”进行合成。")
            return
            
        self.btn_synthesize_voice.setEnabled(False)
        self.btn_next_to_step_4.setEnabled(False)
        self.btn_dub_videos.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        self.dub_worker = VideoDubbingWorker(
            tasks, add_subtitles=add_subs, length_modes=self.voice_length_mode,
            fancy_text=fancy_enabled, fancy_style=fancy_style, fancy_words=fancy_words)
        self.dub_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.dub_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.dub_worker.finished.connect(self._on_dubbing_finished)
        self.dub_worker.error.connect(self._on_dubbing_error)
        self.dub_worker.start()
    # [7·混音导出]  _on_dubbing_finished
    def _on_dubbing_finished(self, results):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.btn_next_to_step_4.setEnabled(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 替换视频原声配音完成！")
        
        for vid, dubbed in results.items():
            self.dubbed_video_paths[vid] = dubbed
            
        # Re-populate mix video table with newly dubbed videos automatically
        self._populate_default_mix_videos()
        
        # Pop up playable dubbed videos list dialog
        dlg = DubbedVideosDialog(self.parent_widget, results)
        dlg.exec()
    # [7·混音导出]  _on_dubbing_error
    def _on_dubbing_error(self, err):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.btn_next_to_step_4.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 配音替换失败")
        QMessageBox.critical(self.parent_widget, "配音替换错误", f"替换配音过程中发生错误：\n{err}")


    # --- Step 4 Final mix helpers & execution ---
    # [7·混音导出]  _populate_default_mix_videos
    def _populate_default_mix_videos(self):
        self.mix_video_table.setRowCount(0)
        
        src_vids = []
        source_type = ""
        if self.dubbed_video_paths:
            src_vids = list(self.dubbed_video_paths.values())
            source_type = "已配音视频"
        # 注意：不再回退扫描 outputs 目录——重启/新建任务后，
        # 目录里上次生成的旧视频不应自动出现在成片列表；
        # 如需使用旧视频，可通过「添加视频」手动选择。
                    
        # Add to table
        for filepath in src_vids:
            self._add_video_to_mix_table(filepath, source_type)
            
        self._adjust_mix_table_height()
        self._update_final_inputs_label()
    # [7·混音导出]  _add_video_to_mix_table
    def _add_video_to_mix_table(self, filepath, source_type="手动选择"):
        filepath = os.path.abspath(filepath)
        for r in range(self.mix_video_table.rowCount()):
            item_path = self.mix_video_table.item(r, 3)
            if item_path and os.path.abspath(item_path.text()) == filepath:
                return # Avoid duplicate
                
        row_idx = self.mix_video_table.rowCount()
        self.mix_video_table.insertRow(row_idx)
        
        # 0: Index
        item_idx = QTableWidgetItem(str(row_idx + 1))
        item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
        item_idx.setTextAlignment(Qt.AlignCenter)
        self.mix_video_table.setItem(row_idx, 0, item_idx)
        
        # 1: File name
        item_name = QTableWidgetItem(os.path.basename(filepath))
        item_name.setFlags(item_name.flags() & ~Qt.ItemIsEditable)
        self.mix_video_table.setItem(row_idx, 1, item_name)
        
        # 2: Source / Status
        item_src = QTableWidgetItem(source_type)
        item_src.setFlags(item_src.flags() & ~Qt.ItemIsEditable)
        item_src.setTextAlignment(Qt.AlignCenter)
        self.mix_video_table.setItem(row_idx, 2, item_src)
        
        # 3: Full path
        item_path = QTableWidgetItem(filepath)
        item_path.setFlags(item_path.flags() & ~Qt.ItemIsEditable)
        self.mix_video_table.setItem(row_idx, 3, item_path)
        
        # 4: Play + BGM + Delete buttons
        action_w = QWidget()
        action_layout = QHBoxLayout(action_w)
        action_layout.setContentsMargins(2, 0, 2, 0)
        action_layout.setSpacing(2)

        btn_play_final = mdi_button("", "play")
        btn_play_final.setToolTip("播放该视频")
        btn_play_final.setStyleSheet("padding: 0px; font-size: 10px;")
        btn_play_final.setFixedWidth(26)
        btn_play_final.setFixedHeight(22)
        btn_play_final.clicked.connect(lambda checked=False, path=filepath: self._play_video(path))
        action_layout.addWidget(btn_play_final)

        # Per-video BGM selection
        bgm_path = self.per_video_bgm.get(filepath, "")
        if bgm_path:
            btn_bgm = mdi_button("", "music")
            btn_bgm.setToolTip(f"已选: {os.path.basename(bgm_path)}\n点击更换")
            btn_bgm.setStyleSheet("padding: 0px; font-size: 11px; background-color: rgba(46,204,113,0.2);")
        else:
            btn_bgm = mdi_button("", "music")
            btn_bgm.setToolTip("选择该视频的背景音乐")
            btn_bgm.setStyleSheet("padding: 0px; font-size: 11px;")
        btn_bgm.setFixedWidth(26)
        btn_bgm.setFixedHeight(22)
        def make_bgm_cb(fp, b):
            return lambda checked=False: self._select_per_video_bgm(fp, b)
        btn_bgm.clicked.connect(make_bgm_cb(filepath, btn_bgm))
        action_layout.addWidget(btn_bgm)

        btn_del = mdi_button("", "trash")
        btn_del.setToolTip("从合成列表中移除")
        btn_del.setStyleSheet("padding: 0px; font-size: 11px; color: #e74c3c;")
        btn_del.setFixedWidth(26)
        btn_del.setFixedHeight(22)
        btn_del.clicked.connect(self._remove_mix_video_row)
        action_layout.addWidget(btn_del)

        self.mix_video_table.setCellWidget(row_idx, 4, action_w)
    # [7·混音导出]  _select_per_video_bgm
    def _select_per_video_bgm(self, filepath, button):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择背景音乐",
            os.path.dirname(filepath) if os.path.exists(os.path.dirname(filepath)) else "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac);;All Files (*)"
        )
        if path:
            self.per_video_bgm[filepath] = path
            button.setToolTip(f"已选: {os.path.basename(path)}\n点击更换")
            button.setStyleSheet("padding: 0px; font-size: 11px; background-color: rgba(46,204,113,0.2);")
    # [7·混音导出]  _remove_mix_video_row
    def _remove_mix_video_row(self):
        button = self.parent_widget.sender()
        if button:
            index = self.mix_video_table.indexAt(button.pos())
            if index.isValid():
                self.mix_video_table.removeRow(index.row())
                # Update row indices
                for r in range(self.mix_video_table.rowCount()):
                    item = self.mix_video_table.item(r, 0)
                    if item:
                        item.setText(str(r + 1))
                self._adjust_mix_table_height()
                self._update_final_inputs_label()
    # [7·混音导出]  _add_mix_videos
    def _add_mix_videos(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget,
            "选择添加视频进行最终合成",
            "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;所有文件 (*.*)"
        )
        if file_paths:
            for path in file_paths:
                self._add_video_to_mix_table(path, "手动选择")
            self._adjust_mix_table_height()
            self._update_final_inputs_label()
    # [7·混音导出]  _clear_mix_videos
    def _clear_mix_videos(self):
        self.mix_video_table.setRowCount(0)
        self._adjust_mix_table_height()
        self._update_final_inputs_label()
    # [7·混音导出]  _adjust_mix_table_height
    def _adjust_mix_table_height(self):
        row_count = self.mix_video_table.rowCount()
        if row_count == 0:
            self.mix_video_table.setFixedHeight(100)
            return

        header_height = self.mix_video_table.horizontalHeader().height()
        if header_height <= 0:
            header_height = 35
            
        total_rows_height = 0
        for i in range(row_count):
            h = self.mix_video_table.rowHeight(i)
            if h <= 0:
                h = 35
            total_rows_height += h

        frame_width = self.mix_video_table.frameWidth() * 2
        margins = self.mix_video_table.contentsMargins()
        margin_height = margins.top() + margins.bottom()

        target_height = header_height + total_rows_height + frame_width + margin_height + 4
        capped_height = min(max(target_height, 120), 400)
        self.mix_video_table.setFixedHeight(capped_height)
    # [9·其他]  _update_final_inputs_label
    def _update_final_inputs_label(self):
        pass
    # [9·其他]  _get_out_montage_dir
    def _get_out_montage_dir(self, dir_path):
        dir_path = os.path.abspath(dir_path)
        path_str = dir_path.replace("\\", "/").rstrip("/")
        
        if path_str.endswith("outputs"):
            return dir_path
        if "/outputs/" in path_str + "/":
            idx = path_str.find("/outputs")
            parent = path_str[:idx]
            return os.path.abspath(os.path.join(parent, "outputs"))
            
        base_parent = os.path.abspath(os.path.join(dir_path, ".."))
        return os.path.abspath(os.path.join(base_parent, "outputs"))
    # [9·其他]  _get_out_final_dir
    def _get_out_final_dir(self, first_vid):
        first_vid = os.path.abspath(first_vid)
        path_str = first_vid.replace("\\", "/").rstrip("/")
        
        if "/outputs/" in path_str + "/":
            idx = path_str.find("/outputs")
            parent = path_str[:idx]
            return os.path.abspath(os.path.join(parent, "final"))
            
        base_parent = os.path.abspath(os.path.join(os.path.dirname(first_vid), ".."))
        if os.path.basename(os.path.dirname(first_vid)) in ("dubbed", "outputs"):
            base_parent = os.path.abspath(os.path.join(base_parent, ".."))
        return os.path.abspath(os.path.join(base_parent, "final"))
    # [7·混音导出]  _toggle_bgm_play
    def _toggle_bgm_play(self):
        bgm_path = self.bgm_input.text().strip()
        if not bgm_path or not os.path.exists(bgm_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", "请先选择有效的背景音乐文件！")
            return
            
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            from PySide6.QtCore import QUrl
            
            # Stop general voice playback to prevent overlapping sounds
            if hasattr(self, "_media_player") and self._media_player:
                self._media_player.stop()

            # Set source if it's different or empty
            current_src = self._bgm_player.source().toLocalFile()
            if os.path.abspath(current_src) != os.path.abspath(bgm_path):
                self._bgm_player.setSource(QUrl.fromLocalFile(bgm_path))
                
            if self._bgm_player.playbackState() == QMediaPlayer.PlayingState:
                self._bgm_player.pause()
                self.btn_bgm_play.setText("播放")
            else:
                self._bgm_audio_output.setVolume(1.0)
                self._bgm_player.play()
                self.btn_bgm_play.setText("暂停")
                self.btn_bgm_stop.setEnabled(True)
        except Exception as e:
            log.error(f"播放背景音乐失败: {e}")
            QMessageBox.critical(self.parent_widget, "播放错误", f"播放背景音乐失败: {e}")
    # [7·混音导出]  _stop_bgm_play
    def _stop_bgm_play(self):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            self._bgm_player.stop()
            self.btn_bgm_play.setText("播放")
            self.btn_bgm_stop.setEnabled(False)
            self.bgm_progress_slider.setValue(0)
            self.lbl_bgm_time.setText("00:00 / 00:00")
        except Exception as e:
            log.error(f"停止背景音乐失败: {e}")
    # [7·混音导出]  _on_bgm_position_changed
    def _on_bgm_position_changed(self, position):
        self.bgm_progress_slider.blockSignals(True)
        self.bgm_progress_slider.setValue(position)
        self.bgm_progress_slider.blockSignals(False)
        self._update_bgm_time_label(position, self._bgm_player.duration())
    # [7·混音导出]  _on_bgm_duration_changed
    def _on_bgm_duration_changed(self, duration):
        self.bgm_progress_slider.setRange(0, duration)
        self._update_bgm_time_label(self._bgm_player.position(), duration)
    # [7·混音导出]  _set_bgm_position
    def _set_bgm_position(self, position):
        self._bgm_player.setPosition(position)
    # [7·混音导出]  _update_bgm_time_label
    def _update_bgm_time_label(self, position, duration):
        def format_time(ms):
            s = ms // 1000
            m = s // 60
            s = s % 60
            return f"{m:02d}:{s:02d}"
        self.lbl_bgm_time.setText(f"{format_time(position)} / {format_time(duration)}")
    # [7·混音导出]  _on_bgm_volume_changed
    def _on_bgm_volume_changed(self, value):
        self.volume_label.setText(f"{value}%")
        if hasattr(self, "_bgm_audio_output") and self._bgm_audio_output:
            self._bgm_audio_output.setVolume(value / 100.0)
    # [7·混音导出]  _start_final_mix
    def _start_final_mix(self):
        if self.mix_worker and self.mix_worker.isRunning():
            return

        row_count = self.mix_video_table.rowCount()
        if row_count == 0:
            QMessageBox.warning(self.parent_widget, "列表为空", "待合成视频列表为空，请先在列表中添加视频！")
            return

        tasks = []
        first_vid = ""
        for r in range(row_count):
            item_path = self.mix_video_table.item(r, 3)
            if item_path:
                vid_path = item_path.text().strip()
                if vid_path and os.path.exists(vid_path):
                    if not first_vid:
                        first_vid = vid_path
                    tasks.append(vid_path)

        if not tasks:
            QMessageBox.warning(self.parent_widget, "视频不存在", "列表中指定的视频文件均不存在，请重新添加！")
            return

        # Determine final output dir
        out_final_dir = self._get_out_final_dir(first_vid)
        os.makedirs(out_final_dir, exist_ok=True)

        final_tasks = []
        src_name = os.path.basename(self.folder_path_input.text().strip().rstrip("/\\"))
        for vid in tasks:
            name = os.path.basename(vid)
            if name.startswith("dubbed_"):
                name = name[len("dubbed_"):]
            if src_name:
                output_path = os.path.join(out_final_dir, f"{src_name}_final_{name}")
            else:
                output_path = os.path.join(out_final_dir, f"final_{name}")
            final_tasks.append((vid, output_path))

        self.btn_final_assemble.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        # Stop BGM playback before starting ffmpeg synthesis
        self._stop_bgm_play()

        self.mix_worker = FinalMixWorker(
            tasks=final_tasks,
            bgm_path=self.bgm_input.text().strip(),
            bgm_volume=self.bgm_volume_slider.value()
        )
        self.mix_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.mix_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.mix_worker.finished.connect(self._on_mix_finished)
        self.mix_worker.error.connect(self._on_mix_error)
        self.mix_worker.start()
    # [7·混音导出]  _on_mix_finished
    def _on_mix_finished(self, paths):
        self.btn_final_assemble.setEnabled(True)
        self.btn_open_final_dir.setEnabled(True)
        self.btn_export_jianying.setEnabled(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 最终合成视频完成！")
        
        self.final_video_list.clear()
        if paths:
            self.final_video_path = paths[0]
            for p in paths:
                self.final_video_list.addItem(os.path.basename(p))
                self.final_video_list.item(self.final_video_list.count() - 1).setData(Qt.UserRole, p)
        else:
            self.final_video_path = ""
    # [7·混音导出]  _on_mix_error
    def _on_mix_error(self, err):
        self.btn_final_assemble.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 合成失败")
        QMessageBox.critical(self.parent_widget, "合成错误", f"处理过程中发生错误：\n{err}")
    # [9·其他]  _open_output_dir
    def _open_output_dir(self):
        if self.final_video_path:
            p = os.path.dirname(self.final_video_path)
            if os.path.exists(p):
                try:
                    os.startfile(p)
                except Exception as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", str(e))
    # [5·拼接合成]  _export_to_jianying_draft
    def _export_to_jianying_draft(self):
        """一键导出为剪映工程草稿"""
        selected_item = self.final_video_list.currentItem()
        if not selected_item:
            # 默认取第一个
            if self.final_video_list.count() > 0:
                selected_item = self.final_video_list.item(0)
        
        if not selected_item:
            QMessageBox.warning(self.parent_widget, "未选中视频", "请先在合成列表中选择一个视频！")
            return
            
        video_path = selected_item.data(Qt.UserRole)
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"无法定位该视频的物理文件：\n{video_path}")
            return

        # 查找字幕：通常配音视频会在同级目录下生成同名 .srt 文件
        video_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        srt_path = os.path.join(video_dir, f"{video_basename}.srt")
        
        # 兼容处理：有些视频名为 dubbed_xxx.mp4，但是字幕名为 dubbed_xxx.srt，也可能叫 xxx.srt
        if not os.path.exists(srt_path):
            clean_name = video_basename
            if clean_name.startswith("dubbed_"):
                clean_name = clean_name[len("dubbed_"):]
            elif clean_name.startswith("final_"):
                clean_name = clean_name[len("final_"):]
            
            for folder in [video_dir, os.path.dirname(video_dir)]:
                tmp_srt = os.path.join(folder, f"{clean_name}.srt")
                if os.path.exists(tmp_srt):
                    srt_path = tmp_srt
                    break
        
        if not os.path.exists(srt_path):
            srt_path = None
            log.warning(f"[Jianying] 未找到视频 {video_basename} 的配套 .srt 字幕文件，导出将不含字幕轨道。")

        # 获取 BGM 路径和音量
        bgm_path = self.bgm_input.text().strip()
        bgm_vol = self.bgm_volume_slider.value()

        # 调用工具类进行导出
        from utils.jianying_exporter import JianyingExporter
        
        draft_name = f"螺丝钉剪辑_{video_basename}"
        success, result_path = JianyingExporter.export_to_draft(
            video_path=video_path,
            bgm_path=bgm_path,
            bgm_volume=bgm_vol,
            srt_path=srt_path,
            draft_name=draft_name
        )

        if success:
            QMessageBox.information(
                self.parent_widget,
                "草稿导出成功",
                f"一键导出至剪映专业版成功！\n\n项目名称：{draft_name}\n\n请直接打开您的电脑「剪映专业版」客户端进行精修编辑。\n系统已为您在资源管理器中定位到该草稿文件夹。"
            )
            # 打开对应的草稿文件夹
            try:
                os.startfile(result_path)
            except Exception:
                pass
        else:
            QMessageBox.critical(
                self.parent_widget,
                "导出失败",
                f"导出剪映草稿时发生错误：\n{result_path}"
            )
    # [9·其他]  _preview_final_video
    def _preview_final_video(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            from PySide6.QtCore import QUrl
            self.final_preview_player.setSource(QUrl.fromLocalFile(path))
            self.final_preview_player.play()
            self.final_preview_title.setText(f"🎥 {os.path.basename(path)}")
    # [4·文案脚本]  _run_batch_vision_descriptions
    def _run_batch_vision_descriptions(self, splits_dir, split_files, missing_only=None):
        """用 BatchGenerateDescriptionsWorker 对分割镜头做批量画面分析，生成描述。

        与 _trigger_vision_on_dir 不同，此方法：
        - 使用主 LLM 配置（llm_api_url），而非视觉模型
        - 对每个镜头抽取多张关键帧
        - 支持有/无字幕两种模式
        """
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model = (cfg.get("llm_model", "") or "deepseek-v4-flash").strip()
        if not model:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 模型名称以使用画面描述生成。")
            return

        # 构建场景列表
        scenes = []
        clip_paths = []
        for f_name in split_files:
            p_clip = os.path.join(splits_dir, f_name)
            norm_p = os.path.abspath(p_clip)
            if missing_only and norm_p not in missing_only:
                continue
            parsed = self._parse_split_filename(f_name)
            if parsed:
                start_str, end_str = parsed[1], parsed[2]
                try:
                    start_sec = float(start_str.replace(",", "."))
                    end_sec = float(end_str.replace(",", "."))
                    scenes.append((start_sec, end_sec))
                except Exception:
                    scenes.append((0.0, 5.0))
            else:
                scenes.append((0.0, 5.0))
            clip_paths.append(norm_p)

        if not clip_paths:
            return

        # 尝试找字幕
        raw_srt = ""
        parent_dir = os.path.dirname(splits_dir)
        if parent_dir:
            for f_name in os.listdir(parent_dir):
                if f_name.endswith(".srt"):
                    try:
                        with open(os.path.join(parent_dir, f_name), "r", encoding="utf-8") as sf:
                            raw_srt = sf.read().strip()
                        break
                    except Exception:
                        pass

        self.stage_label.setText(f"正在批量分析 {len(clip_paths)} 个镜头画面...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._batch_desc_worker = BatchGenerateDescriptionsWorker(
            "", "", model, raw_srt, scenes, clip_paths)

        def on_desc_ok(json_str):
            import json as _json
            try:
                desc_dict = _json.loads(json_str)
                for item in desc_dict:
                    idx = item.get("index", 0) - 1
                    desc = item.get("description", "").strip()
                    if 0 <= idx < len(clip_paths) and desc:
                        norm_p = os.path.abspath(clip_paths[idx])
                        self.split_descriptions[norm_p] = desc
                        if norm_p in getattr(self, "split_clips_cache", {}):
                            self.split_clips_cache[norm_p]["desc"] = desc
            except Exception as e:
                log.warning(f"解析批量画面描述失败: {e}")
            self.progress_bar.setValue(100)
            self._check_split_clips_exist()
            self.stage_label.setText("✅ 画面描述生成完成")
            QMessageBox.information(
                self.parent_widget, "描述生成完成",
                f"已为 {len(clip_paths)} 个镜头生成画面描述。")

        def on_desc_err(msg):
            log.warning(f"批量画面描述生成失败: {msg}")
            self.progress_bar.setValue(100)
            self.stage_label.setText("❌ 画面描述生成失败")
            QMessageBox.warning(self.parent_widget, "生成失败",
                                f"画面描述生成失败：\n{msg}")

        self._batch_desc_worker.finished.connect(on_desc_ok)
        self._batch_desc_worker.error.connect(on_desc_err)
        self._batch_desc_worker.start()
    # [3·分割]  _gen_split_descriptions
    def _gen_split_descriptions(self):
        """为当前选中视频的每个分割镜头生成文案描述。

        流程：
        1. 检查是否有字幕文件（.srt），有则按时间戳匹配到每个镜头
        2. 没有字幕则先尝试转录音频生成字幕
        3. 匹配不到的镜头用视觉AI分析画面生成描述
        """
        selected_item = self.video_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self.parent_widget, "请选择视频", "请先在上方列表中选中一个视频文件。")
            return

        video_path = selected_item.text()
        if not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "视频不存在", f"未找到该视频文件：\n{video_path}")
            return

        video_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        splits_dir = os.path.join(video_dir, video_basename, "splits")
        if not os.path.exists(splits_dir):
            QMessageBox.warning(self.parent_widget, "未分割镜头", "请先对当前视频进行镜头分割。")
            return

        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
        if not files:
            QMessageBox.warning(self.parent_widget, "无镜头文件", "分割目录中没有镜头片段文件。")
            return

        # 检查是否有字幕文件
        srt_path = os.path.join(video_dir, video_basename, f"{video_basename}.srt")
        if not os.path.exists(srt_path):
            srt_path = os.path.join(video_dir, f"{video_basename}.srt")

        has_srt = os.path.exists(srt_path) and os.path.getsize(srt_path) > 0

        if not has_srt:
            # 没有字幕，询问是否要先转录音频生成字幕
            reply = QMessageBox.question(
                self.parent_widget, "无字幕文件",
                "该视频没有字幕文件。是否先转录音频生成字幕？\n\n"
                "是 = 转录音频生成字幕后再匹配\n"
                "否 = 直接用视觉AI分析画面生成描述",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                # 标记转录完成后自动继续生成描述
                self._pending_gen_descriptions = True
                self._start_transcribe_raw()
                return
            # 否则用 BatchGenerateDescriptionsWorker 批量分析画面
            self._run_batch_vision_descriptions(splits_dir, files)
            return

        # 有字幕，按时间戳匹配到每个镜头
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()
        except Exception as e:
            QMessageBox.warning(self.parent_widget, "读取字幕失败", f"无法读取字幕文件：\n{e}")
            return

        parsed_texts = parse_srt_to_descriptions(srt_content)
        if not parsed_texts:
            QMessageBox.warning(self.parent_widget, "字幕解析失败", "无法从字幕文件中解析出文本内容。")
            return

        scenes = self._get_split_scenes_times(splits_dir, files)
        updated_count = 0
        missing_clips = []

        for idx, f_name in enumerate(files):
            p_clip = os.path.join(splits_dir, f_name)
            norm_p = os.path.abspath(p_clip)

            if idx < len(parsed_texts) and parsed_texts[idx].strip():
                self.split_descriptions[norm_p] = parsed_texts[idx].strip()
                # 同步到缓存
                if norm_p in getattr(self, "split_clips_cache", {}):
                    self.split_clips_cache[norm_p]["desc"] = parsed_texts[idx].strip()
                updated_count += 1
            else:
                missing_clips.append(norm_p)

        # 刷新显示
        self._check_split_clips_exist()

        if missing_clips:
            # 有匹配不到的镜头，用视觉AI补充
            self.stage_label.setText(f"字幕匹配完成，{len(missing_clips)} 个镜头未匹配到字幕，正在用视觉AI分析...")
            self._run_batch_vision_descriptions(splits_dir, files, missing_clips)
        else:
            self.stage_label.setText(f"✅ 已为全部 {len(files)} 个镜头匹配字幕文案描述")
            QMessageBox.information(
                self.parent_widget, "描述生成完成",
                f"已从字幕匹配到 {updated_count} 个镜头的文案描述。")
    # [3·分割]  _gen_shot_analysis
    def _gen_shot_analysis(self):
        """生成镜头分析：调用服务端 /material/score_clip 逐条分析当前镜头，回填评分与描述。"""
        tbl = getattr(self, "split_result_table", None)
        if tbl is None or tbl.rowCount() == 0:
            QMessageBox.warning(self.parent_widget, "无镜头", "请先执行智能镜头分割，生成镜头片段。")
            return

        clips = []
        for r in range(tbl.rowCount()):
            file_item = tbl.item(r, 2)
            if file_item:
                path = file_item.data(Qt.UserRole)
                if path and os.path.isfile(path):
                    clips.append(path)
        if not clips:
            QMessageBox.warning(self.parent_widget, "无镜头文件", "表格中没有可用的镜头片段文件。")
            return

        server_url = self._get_compute_server_url()
        if not server_url:
            QMessageBox.warning(self.parent_widget, "未配置服务端",
                                "请先在「环境配置」中配置算力服务端地址（compute_server_url）。")
            return

        if getattr(self, "_analysis_worker", None) and self._analysis_worker.isRunning():
            return

        self._analysis_paths = clips
        self.btn_gen_shot_analysis.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText(f"🤖 正在调用服务端分析 {len(clips)} 个镜头...")
        log.info(f"[镜头分析] 开始分析 {len(clips)} 个镜头，服务端地址: {server_url}/material/score_clip")

        self._analysis_worker = ServerClipAnalysisWorker(
            clips, server_url, product_prompt=self._get_product_prompt())
        self._analysis_worker.item_ready.connect(self._on_analysis_item_ready)
        self._analysis_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self._analysis_worker.finished.connect(self._on_analysis_all_done)
        self._analysis_worker.error.connect(self._on_analysis_error)
        self._analysis_worker.start()
    # [2·基础设施]  _get_compute_server_url
    def _get_compute_server_url(self):
        try:
            cfg = getattr(self.main_window, "ai_config", {}) or {}
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
        except Exception:
            pass
        try:
            from config.paths import AI_CONFIG_FILE
            import json as _json
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                return (cfg.get("compute_server_url") or "").strip().rstrip("/")
        except Exception:
            pass
        return ""
    # [3·分割]  _on_analysis_item_ready
    def _on_analysis_item_ready(self, idx, result):
        """服务端分析完成一个镜头，回填表格。result = {score, desc, extra}"""
        paths = getattr(self, "_analysis_paths", [])
        if idx < 0 or idx >= len(paths):
            return
        path = paths[idx]
        score = result.get("score", -1.0)
        desc = result.get("desc", "")
        extra = result.get("extra", {})

        # 提取景别/产品/型号等字段
        shot_type = str(extra.pop("shot_type", extra.pop("shot_scale", extra.pop("景别", ""))) or "")
        product = str(extra.pop("product", extra.pop("product_name", extra.pop("产品", ""))) or "")
        model = str(extra.pop("model", extra.pop("model_number", extra.pop("型号", ""))) or "")
        duration_val = extra.pop("duration", extra.pop("时长", ""))

        if path in self.split_clips_cache:
            self.split_clips_cache[path]["score"] = score
            if desc:
                self.split_clips_cache[path]["desc"] = desc
            if shot_type:
                self.split_clips_cache[path]["shot_type"] = shot_type
            if product:
                self.split_clips_cache[path]["product"] = product
            if model:
                self.split_clips_cache[path]["model"] = model
        if desc:
            self.split_descriptions[path] = desc

        tbl = getattr(self, "split_result_table", None)
        if tbl is not None:
            tbl.blockSignals(True)
            try:
                # Col 3: 景别
                if shot_type:
                    shot_item = tbl.item(idx, 3)
                    if shot_item:
                        shot_item.setText(shot_type)
                # Col 4: 时长
                if duration_val:
                    dur_item = tbl.item(idx, 4)
                    if dur_item:
                        try:
                            dur_item.setText(f"{float(duration_val):.1f}s")
                        except (TypeError, ValueError):
                            dur_item.setText(str(duration_val))
                # Col 5: 主要画面
                if desc:
                    desc_item = tbl.item(idx, 5)
                    if desc_item:
                        desc_item.setText(desc)
                # Col 6: 产品
                if product:
                    prod_item = tbl.item(idx, 6)
                    if prod_item:
                        prod_item.setText(product)
                # Col 7: 型号
                if model:
                    model_item = tbl.item(idx, 7)
                    if model_item:
                        model_item.setText(model)
                # Col 8: 评分
                score_item = tbl.item(idx, 8)
                if score_item:
                    score_item.setText(f"{score:.1f}" if score >= 0 else "—")
                    if score >= 8.0:
                        score_item.setForeground(QColor("#2ecc71"))
                    elif score >= 6.0:
                        score_item.setForeground(QColor("#f1c40f"))
                    elif score >= 0:
                        score_item.setForeground(QColor("#e74c3c"))
                # 剩余 extra 放入 tooltip
                if extra:
                    detail_text = " | ".join(f"{k}: {v}" for k, v in extra.items())
                    file_item = tbl.item(idx, 2)
                    if file_item:
                        old_tip = file_item.toolTip() or ""
                        file_item.setToolTip(f"{old_tip}\n分析详情: {detail_text}")
            finally:
                tbl.blockSignals(False)

        # 同步到下一步的镜头数据
        for clip in getattr(self, "_available_concat_clips", []):
            if clip.get("path") == path:
                clip["score"] = score
                if desc:
                    clip["desc"] = desc

        self._refresh_step1_row_visual(idx)
    # [3·分割]  _on_analysis_all_done
    def _on_analysis_all_done(self, ok, fail):
        if hasattr(self, "btn_gen_shot_analysis"):
            self.btn_gen_shot_analysis.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self._save_split_srt()
        self._apply_step1_score_filter()
        if ok == 0 and fail > 0:
            self.stage_label.setText(f"❌ 镜头分析失败：{fail} 个镜头全部失败，服务端未返回有效数据")
            QMessageBox.warning(
                self.parent_widget, "镜头分析失败",
                f"服务端镜头分析全部失败（{fail} 个镜头）。\n\n"
                f"可能原因：\n"
                f"· 服务端 /material/score_clip 接口未部署或未启动\n"
                f"· 服务端地址配置错误\n"
                f"· 服务端返回了 HTTP 200 但未包含 score/description 字段\n\n"
                f"请查看日志（帮助 → 系统日志）中的 [镜头分析] 详细记录。")
        else:
            self.stage_label.setText(f"✅ 镜头分析完成：成功 {ok} 个，失败 {fail} 个")
            QMessageBox.information(
                self.parent_widget, "镜头分析完成",
                f"服务端镜头分析完成：成功 {ok} 个，失败 {fail} 个。\n"
                f"评分与描述已回填到镜头表格。")
    # [3·分割]  _on_analysis_error
    def _on_analysis_error(self, err):
        if hasattr(self, "btn_gen_shot_analysis"):
            self.btn_gen_shot_analysis.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 镜头分析失败")
        QMessageBox.critical(self.parent_widget, "镜头分析失败",
                             f"调用服务端镜头分析接口失败：\n{err}")

    # [3·分割]  _on_step1_score_filter_changed
    def _on_step1_score_filter_changed(self):
        combo = getattr(self, "step1_score_filter_combo", None)
        if combo is None:
            return
        try:
            self._step1_score_threshold = float(combo.currentData() or 0.0)
        except (TypeError, ValueError):
            self._step1_score_threshold = 0.0
        self._apply_step1_score_filter()
    # [3·分割]  _on_step1_checkbox_changed
    def _on_step1_checkbox_changed(self, item):
        """用户手动勾选/取消勾选镜头时，同步到 _available_concat_clips。"""
        if item.column() != 0:
            return
        row = item.row()
        tbl = getattr(self, "split_result_table", None)
        if tbl is None:
            return
        file_item = tbl.item(row, 2)
        if not file_item:
            return
        path = file_item.data(Qt.UserRole)
        checked = (item.checkState() == Qt.Checked)
        for clip in getattr(self, "_available_concat_clips", []):
            if clip.get("path") == path:
                clip["checked"] = checked
                break
        self._update_concat_count_lbl()
    # [3·分割]  _apply_step1_score_filter
    def _apply_step1_score_filter(self):
        """按评分阈值刷新：步骤1表格置灰未达标行并同步checkbox；步骤2镜头勾选状态同步为过滤结果。"""
        threshold = float(getattr(self, "_step1_score_threshold", 6.0) or 0.0)
        tbl = getattr(self, "split_result_table", None)
        if tbl is not None:
            tbl.blockSignals(True)
            try:
                for r in range(tbl.rowCount()):
                    self._refresh_step1_row_visual(r)
                    # 同步 checkbox
                    file_item = tbl.item(r, 2)
                    if not file_item:
                        continue
                    path = file_item.data(Qt.UserRole)
                    cache = self.split_clips_cache.get(path, {}) if path else {}
                    score = cache.get("score", None) if isinstance(cache, dict) else None
                    passed = (threshold <= 0 or score is None or score < 0 or score >= threshold)
                    chk_item = tbl.item(r, 0)
                    if chk_item:
                        chk_item.setCheckState(Qt.Checked if passed else Qt.Unchecked)
            finally:
                tbl.blockSignals(False)
        if getattr(self, "_available_concat_clips", None):
            for clip in self._available_concat_clips:
                score = clip.get("score", -1)
                clip["checked"] = (threshold <= 0 or score is None
                                   or score < 0 or score >= threshold)
            self._update_concat_count_lbl()
    # [3·分割]  _refresh_step1_row_visual
    def _refresh_step1_row_visual(self, row):
        tbl = getattr(self, "split_result_table", None)
        if tbl is None or row < 0 or row >= tbl.rowCount():
            return
        file_item = tbl.item(row, 2)
        if not file_item:
            return
        path = file_item.data(Qt.UserRole)
        cache = self.split_clips_cache.get(path, {}) if path else {}
        score = cache.get("score", None) if isinstance(cache, dict) else None
        threshold = float(getattr(self, "_step1_score_threshold", 6.0) or 0.0)
        passed = (threshold <= 0 or score is None or score < 0 or score >= threshold)
        for c in range(tbl.columnCount()):
            it = tbl.item(row, c)
            if not it:
                continue
            if not passed:
                it.setForeground(QColor("#6b7280"))
            elif c == 8 and score is not None and score >= 0:
                if score >= 8.0:
                    it.setForeground(QColor("#2ecc71"))
                elif score >= 6.0:
                    it.setForeground(QColor("#f1c40f"))
                else:
                    it.setForeground(QColor("#e74c3c"))
            else:
                it.setForeground(QBrush())
    # [2·基础设施]  _go_next_to_step2
    def _go_next_to_step2(self):
        """点击下一步：从表格checkbox同步选中状态，再进入镜头重组。"""
        self._sync_step1_checkboxes_to_clips()
        self._go_to_step(1)
    # [3·分割]  _sync_step1_checkboxes_to_clips
    def _sync_step1_checkboxes_to_clips(self):
        """从步骤1表格的checkbox列同步勾选状态到 _available_concat_clips。"""
        tbl = getattr(self, "split_result_table", None)
        if tbl is None:
            return
        checked_paths = set()
        for r in range(tbl.rowCount()):
            chk_item = tbl.item(r, 0)
            file_item = tbl.item(r, 2)
            if chk_item and file_item and chk_item.checkState() == Qt.Checked:
                path = file_item.data(Qt.UserRole)
                if path:
                    checked_paths.add(path)
        for clip in getattr(self, "_available_concat_clips", []):
            clip["checked"] = clip.get("path") in checked_paths
        self._update_concat_count_lbl()
    # [3·分割]  _open_splits_dir
    def _open_splits_dir(self):
        selected_item = self.video_list.currentItem()
        if selected_item:
            video_path = selected_item.text()
            video_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(video_dir, video_basename, "splits")
            os.makedirs(splits_dir, exist_ok=True)
            try:
                os.startfile(splits_dir)
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
        else:
            dir_path = self.folder_path_input.text().strip()
            if dir_path and os.path.exists(dir_path):
                splits_dir = os.path.join(dir_path, "splits")
                os.makedirs(splits_dir, exist_ok=True)
                try:
                    os.startfile(splits_dir)
                except Exception as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
            else:
                QMessageBox.warning(self.parent_widget, "路径无效", "请先选择有效的素材目录。")
    # [5·拼接合成]  _select_concat_src_dir
    def _select_concat_src_dir(self):
        default_dir = self.concat_src_dir_input.text().strip()
        if not default_dir or not os.path.exists(default_dir):
            selected_item = self.video_list.currentItem()
            if selected_item:
                video_path = selected_item.text()
                video_dir = os.path.dirname(video_path)
                video_basename = os.path.splitext(os.path.basename(video_path))[0]
                default_dir = os.path.join(video_dir, video_basename, "splits")
            else:
                dir_path = self.folder_path_input.text().strip()
                if dir_path:
                    default_dir = os.path.join(dir_path, "splits")
        
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget,
            "重新选择素材",
            default_dir,
            "图片视频 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v *.jpg *.jpeg *.png *.bmp *.gif *.webp);;视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.webp);;所有文件 (*.*)"
        )
        if file_paths:
            dir_path = os.path.dirname(file_paths[0])
            self.concat_src_dir_input.setText(dir_path)
            self.selected_concat_clips_files = file_paths
            self._scan_concat_src_dir()
    # [5·拼接合成]  _scan_concat_src_dir
    def _scan_concat_src_dir(self):
        dir_path = self.concat_src_dir_input.text().strip()

        if not hasattr(self, "_available_concat_clips"):
            self._available_concat_clips = []

        old_checked = {c["path"] for c in self._available_concat_clips if c.get("checked")}
        self._available_concat_clips = []

        if dir_path and os.path.exists(dir_path):
            files = []
            if hasattr(self, "selected_concat_clips_files") and self.selected_concat_clips_files:
                first_parent = os.path.abspath(os.path.dirname(self.selected_concat_clips_files[0]))
                current_dir = os.path.abspath(dir_path)
                if first_parent == current_dir:
                    files = self.selected_concat_clips_files

            if not files:
                for f in os.listdir(dir_path):
                    if f.lower().endswith((".mp4", ".m4v", ".mov", ".avi", ".mkv", ".flv", ".webm",
                                            ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")):
                        files.append(os.path.join(dir_path, f))

            files.sort(key=lambda x: os.path.basename(x).lower())

            srt_scenes = {}
            srt_descs = {}
            parent_dir = os.path.dirname(dir_path)
            srt_candidates = []
            if os.path.isdir(dir_path):
                for f in os.listdir(dir_path):
                    if f.lower().endswith(".srt"):
                        srt_candidates.append(os.path.join(dir_path, f))
            if os.path.isdir(parent_dir):
                for f in os.listdir(parent_dir):
                    if f.lower().endswith(".srt"):
                        srt_candidates.append(os.path.join(parent_dir, f))
                grandparent_dir = os.path.dirname(parent_dir)
                if os.path.isdir(grandparent_dir):
                    for f in os.listdir(grandparent_dir):
                        if f.lower().endswith(".srt"):
                            srt_candidates.append(os.path.join(grandparent_dir, f))

            best_srt = ""
            if srt_candidates:
                folder_name = os.path.basename(parent_dir)
                for path in srt_candidates:
                    if folder_name.lower() in os.path.basename(path).lower():
                        best_srt = path
                        break
                if not best_srt:
                    best_srt = srt_candidates[0]

            if best_srt and os.path.exists(best_srt):
                try:
                    with open(best_srt, "r", encoding="utf-8") as sf:
                        srt_content = sf.read()
                    segments = parse_srt(srt_content)
                    for seg_idx, (start_s, end_s, text) in enumerate(segments):
                        srt_scenes[seg_idx] = (start_s, end_s)
                        srt_descs[seg_idx] = text
                    log.info(f"Step 2 scan: Loaded {len(segments)} segments from SRT: {best_srt}")
                except Exception as e:
                    log.warning(f"Step 2 scan: Failed to read SRT {best_srt}: {e}")

            scenes = self._get_split_scenes_times(dir_path, [os.path.basename(f) for f in files])

            _old_cache = getattr(self, "split_clips_cache", {}) or {}
            self.split_clips_cache = {}

            for idx, filepath in enumerate(files):
                filename = os.path.basename(filepath)
                file_dir = os.path.dirname(filepath)
                norm_path = os.path.abspath(filepath)

                parsed = self._parse_split_filename(filename)
                if parsed:
                    p_idx, start_str, end_str, desc = parsed
                    time_str = f"{start_str} --> {end_str}"
                else:
                    desc = srt_descs.get(idx, "")
                    if not desc:
                        desc = self.split_descriptions.get(norm_path, "")

                    if idx in srt_scenes:
                        start_sec, end_sec = srt_scenes[idx]
                    else:
                        if idx < len(scenes):
                            start_sec, end_sec = scenes[idx]
                        else:
                            start_sec, end_sec = 0.0, 0.0
                    start_str = format_seconds_to_srt_timestamp(start_sec)
                    end_str = format_seconds_to_srt_timestamp(end_sec)
                    time_str = f"{start_str} --> {end_str}"

                if desc:
                    self.split_descriptions[norm_path] = desc

                clip_dur = get_media_duration(norm_path)

                cached = self.split_clips_cache.get(norm_path, {})
                score = cached.get("score", None)
                if score is None and norm_path in _old_cache:
                    old_entry = _old_cache[norm_path]
                    if isinstance(old_entry, dict):
                        score = old_entry.get("score")
                if score is None:
                    score = self._score_clip(norm_path)

                self.split_clips_cache[norm_path] = {
                    "filename": filename,
                    "time_str": time_str,
                    "desc": desc,
                    "duration": clip_dur,
                    "score": score,
                }

                threshold = float(getattr(self, "_step1_score_threshold", 6.0) or 0.0)
                if threshold <= 0:
                    auto_check = True
                else:
                    auto_check = (score >= 0 and score >= threshold) or score < 0
                checked = norm_path in old_checked or auto_check

                self._available_concat_clips.append({
                    "path": norm_path,
                    "filename": filename,
                    "time_str": time_str,
                    "desc": desc,
                    "duration": clip_dur,
                    "score": score,
                    "checked": checked,
                })

        self._update_concat_count_lbl()

    # [9·其他]  _open_clip_selection_dialog
    def _open_clip_selection_dialog(self):
        if not self._available_concat_clips:
            QMessageBox.information(self.parent_widget, "无可用镜头", "当前目录下没有可选择的镜头片段。")
            return

        selected_paths = [c["path"] for c in self._available_concat_clips if c.get("checked")]
        dialog_clips = [dict(c) for c in self._available_concat_clips]
        dialog = ClipSelectionDialog(
            clips=dialog_clips,
            selected_paths=selected_paths,
            parent=self.parent_widget,
            play_callback=self._play_video,
        )
        if dialog.exec() == QDialog.Accepted:
            self._available_concat_clips = dialog.get_clips()
            for clip in self._available_concat_clips:
                path = clip.get("path")
                desc = clip.get("desc", "")
                if path and desc:
                    self.split_descriptions[path] = desc
                    if path in self.split_clips_cache:
                        self.split_clips_cache[path]["desc"] = desc
            self._save_split_srt()
            self._update_concat_count_lbl()

    # [9·其他]  _select_all_clips
    def _select_all_clips(self):
        for clip in self._available_concat_clips:
            clip["checked"] = True
        self._update_concat_count_lbl()

    # [9·其他]  _deselect_all_clips
    def _deselect_all_clips(self):
        for clip in self._available_concat_clips:
            clip["checked"] = False
        self._update_concat_count_lbl()

    # [5·拼接合成]  _update_concat_count_lbl
    def _update_concat_count_lbl(self):
        self.split_clips_list = []
        checked_count = 0
        total = len(self._available_concat_clips)
        for clip in self._available_concat_clips:
            if clip.get("checked"):
                checked_count += 1
                path = clip.get("path")
                if path:
                    self.split_clips_list.append(path)

        self.clip_count_info_lbl.setText(f"待排列镜头个数: {total}  (已勾选: {checked_count})")
        self._update_batch_count_recommendation()

        # 不再根据勾选数禁用按钮（禁用后无视觉反馈，用户误以为按钮坏了）
        # 0 勾选时点击按钮会弹出引导提示（见 _start_assemble_video）

    # [5·拼接合成]  _recommend_batch_count
    def _recommend_batch_count(self):
        checked = max(1, len(self.split_clips_list))
        recommended = checked // 2
        if recommended <= 0:
            recommended = 1
        return max(1, min(10, recommended))

    # [5·拼接合成]  _update_batch_count_recommendation
    def _update_batch_count_recommendation(self):
        if not hasattr(self, "batch_count_spin"):
            return
        rec = self._recommend_batch_count()
        if hasattr(self, "batch_count_hint_lbl"):
            self.batch_count_hint_lbl.setText(f"推荐: {rec}")
        self.batch_count_spin.setValue(rec)
    # [9·其他]  _get_clip_duration
    def _get_clip_duration(self, clip_path):
        """获取镜头时长（秒），优先从缓存读取。"""
        norm = os.path.abspath(clip_path)
        cache = getattr(self, "split_clips_cache", {})
        cached = cache.get(norm)
        if cached and cached.get("duration", 0) > 0:
            return cached["duration"]
        dur = get_media_duration(norm)
        if dur > 0 and norm in cache:
            cache[norm]["duration"] = dur
        return dur
    # [2·基础设施]  _load_lut_combo
    def _load_lut_combo(self):
        """从 video_config.json 加载 LUT 配置到下拉框。"""
        if not hasattr(self, "lut_combo"):
            return
        from config.paths import VIDEO_CONFIG_FILE
        import json as _json
        current = self.lut_combo.currentData()
        self.lut_combo.blockSignals(True)
        self.lut_combo.clear()
        self.lut_combo.addItem("无", "")
        if os.path.isfile(VIDEO_CONFIG_FILE):
            try:
                with open(VIDEO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                for name, path in data.items():
                    self.lut_combo.addItem(name, path)
            except Exception:
                pass
        # 恢复之前选中的项
        for i in range(self.lut_combo.count()):
            if self.lut_combo.itemData(i) == current:
                self.lut_combo.setCurrentIndex(i)
                break
        self.lut_combo.blockSignals(False)
    # [9·其他]  _get_selected_lut_path
    def _get_selected_lut_path(self):
        """返回当前选中 LUT 的文件路径，无选择返回空串。"""
        if not hasattr(self, "lut_combo"):
            return ""
        return self.lut_combo.currentData() or ""
    # [3·分割]  _score_clip (已移除：本地OpenCV评分已删除，统一使用服务端分析)
    def _score_clip(self, clip_path):
        return -1
    # [5·拼接合成]  _build_precompose_plans
    def _build_precompose_plans(self, clips, target_clip_count, batch_count, randomness, duration_limit_sec):
        base = [os.path.abspath(c) for c in clips if c]
        if not base:
            return []
        unique = list(dict.fromkeys(base))
        if randomness == "low":
            deck = list(unique)
        else:
            deck = list(unique)
            random.shuffle(deck)

        max_total = duration_limit_sec * 1.1 if duration_limit_sec and duration_limit_sec > 0 else 0

        plans = []
        cursor = 0

        # 镜头缓存：hash + quality（同一视频只算一次）
        _hash_cache = {}
        _quality_cache = {}

        def _hash(clip):
            if clip not in _hash_cache:
                _hash_cache[clip] = compute_clip_hash(clip)
            return _hash_cache[clip]

        def _quality(clip):
            if clip not in _quality_cache:
                _quality_cache[clip] = compute_clip_quality(clip)
            return _quality_cache[clip]

        def _hamming(a, b):
            """汉明距离：两个 64-bit hash 的不同位数。"""
            if a is None or b is None:
                return 64
            xor = a ^ b
            dist = 0
            while xor:
                dist += xor & 1
                xor >>= 1
            return dist

        SIMILARITY_THRESHOLD = 8  # 汉明距离 < 8 视为高度相似

        for _i in range(batch_count):
            if randomness == "high":
                random.shuffle(deck)
            seq = []
            seq_hashes = []      # 已入列的镜头 hash
            seq_qualities = []    # 已入列的镜头质量分
            total_dur = 0.0
            _safety = 0
            while len(seq) < target_clip_count:
                _safety += 1
                if _safety > target_clip_count * 6:
                    break
                if cursor >= len(deck):
                    cursor = 0
                    if randomness != "low":
                        random.shuffle(deck)
                need = target_clip_count - len(seq)
                take = min(need, len(deck) - cursor)
                if take <= 0:
                    break
                batch_slice = deck[cursor:cursor + take]
                for clip in batch_slice:
                    if max_total > 0:
                        clip_dur = self._get_clip_duration(clip)
                        if total_dur + clip_dur > max_total and len(seq) > 0:
                            break
                        total_dur += clip_dur

                    h = _hash(clip)
                    q = _quality(clip)

                    # ── 去重检查：和已入列镜头比较 ──
                    replaced = False
                    for j, prev_h in enumerate(seq_hashes):
                        if _hamming(h, prev_h) < SIMILARITY_THRESHOLD:
                            prev_q = seq_qualities[j]
                            if q > prev_q and q > 0:
                                # 新镜头更好 → 替换旧镜头
                                log.info(f"[去重] 替换: {os.path.basename(clip)} (q={q}) → {os.path.basename(seq[j])} (q={prev_q})")
                                seq[j] = clip
                                seq_hashes[j] = h
                                seq_qualities[j] = q
                                replaced = True
                            else:
                                # 新镜头不如旧的 → 跳过
                                log.info(f"[去重] 跳过相似镜头: {os.path.basename(clip)} (q={q}) vs {os.path.basename(seq[j])} (q={prev_q})")
                                replaced = True
                            break

                    if not replaced:
                        seq.append(clip)
                        seq_hashes.append(h)
                        seq_qualities.append(q)

                    if max_total > 0 and total_dur >= max_total:
                        break
                cursor += take
                if max_total > 0 and total_dur >= max_total:
                    break
            if len(seq) < target_clip_count and not max_total:
                while len(seq) < target_clip_count:
                    seq.append(random.choice(unique))
            plans.append({"clips": seq, "deleted_flags": [False] * len(seq), "mode": "random"})
        log.info(f"[DIAG _build_precompose_plans] target={target_clip_count} batch={batch_count} total_clips={len(unique)} plans={len(plans)} plan_sizes={[len(p['clips']) for p in plans]}")
        return plans
    # [5·拼接合成]  _load_precompose_plans
    def _load_precompose_plans(self, plan_specs, out_montage_dir):
        self.precompose_plans = []
        self.current_precompose_index = -1
        self.assembled_video_path = ""
        self.btn_next_to_step_3.setEnabled(False)
        self.assembled_clips_list_widget.clear()
        if hasattr(self, "btn_batch_scene_copy"):
            self.btn_batch_scene_copy.setEnabled(False)
        if hasattr(self, "btn_confirm_all"):
            self.btn_confirm_all.setEnabled(False)
        self.sources_detail_widget.setRowCount(0)

        for idx, spec in enumerate(plan_specs):
            clips = list(spec.get("clips") or [])
            plan = {
                "clips": clips,
                "deleted_flags": [False] * len(clips),
                "mode": spec.get("mode", "random"),
                "descriptions": list(spec.get("descriptions") or []),
                "confirmed": False,
                "output_path": "",
                "out_dir": out_montage_dir,
            }
            # 保留音乐卡点模式所需的字段（供合成时按节拍裁剪 + 叠加音乐片段）
            if spec.get("mode") == "beat":
                plan["beat_times"] = list(spec.get("beat_times") or [])
                plan["music_path"] = spec.get("music_path", "")
                plan["music_range"] = list(spec.get("music_range") or [])
            self.precompose_plans.append(plan)
            self._add_assembled_row(idx, "", plan)

        if self.assembled_clips_list_widget.count() > 0:
            item = self.assembled_clips_list_widget.item(0)
            self.assembled_clips_list_widget.setCurrentItem(item)
            self._on_assembled_item_clicked(item)
        self._update_confirm_all_button()
    # [5·拼接合成]  _add_assembled_row
    def _add_assembled_row(self, index, path, plan=None):
        """在预合成列表中添加一行，支持确认合成状态与单条确认操作。"""
        if plan is None:
            plan = {
                "clips": [],
                "mode": "random",
                "descriptions": [],
                "confirmed": True,
                "output_path": path,
                "out_dir": os.path.dirname(path) if path else "",
            }
        clip_count = len(plan.get("clips") or [])
        out_path = (plan.get("output_path") or path or "").strip()
        confirmed = plan.get("confirmed") and bool(out_path)
        status_txt = "✅已合成" if confirmed else "⏳待确认"
        file_text = os.path.basename(out_path) if out_path else f"{clip_count} 个镜头"
        # 文案状态：用文字而非图标
        copy_preview = self._assembled_copy_preview(out_path) if out_path else ""
        copy_mark = f"  📝{copy_preview}" if copy_preview else ""
        plan_id = plan.get("_plan_id")
        if plan_id is None:
            plan_id = index
            plan["_plan_id"] = index
        text = f"[{index+1}] {file_text}  {status_txt}{copy_mark}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, index)
        item.setData(Qt.UserRole + 1, int(confirmed))
        self.assembled_clips_list_widget.addItem(item)
    # [5·拼接合成]  _show_assembled_context_menu
    def _show_assembled_context_menu(self, pos):
        item = self.assembled_clips_list_widget.itemAt(pos)
        if not item:
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        menu = QMenu()
        act_confirm = QAction("✅ 确认合成视频", menu)
        act_confirm.triggered.connect(lambda: self._confirm_precompose(idx))
        menu.addAction(act_confirm)
        act_copy = QAction("✍ 生成口播文案", menu)
        act_copy.triggered.connect(lambda: self._gen_copy_for_plan(idx))
        menu.addAction(act_copy)
        plan = self.precompose_plans[idx] if 0 <= idx < len(self.precompose_plans) else None
        if plan:
            out_path = (plan.get("output_path") or "").strip()
            has_copy = bool(out_path and self._assembled_has_copy(out_path))
            if has_copy:
                act_view = QAction("📄 查看文案", menu)
                act_view.triggered.connect(lambda: self._view_assembled_copy(idx))
                menu.addAction(act_view)
        menu.exec_(self.assembled_clips_list_widget.viewport().mapToGlobal(pos))
    # [4·文案脚本]  _view_assembled_copy
    def _view_assembled_copy(self, idx):
        if idx < 0 or idx >= len(self.precompose_plans):
            return
        out_path = (self.precompose_plans[idx].get("output_path") or "").strip()
        if not out_path:
            return
        txt = os.path.splitext(out_path)[0] + ".txt"
        if not os.path.exists(txt):
            return
        try:
            with open(txt, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QHBoxLayout
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(f"口播文案 - 预合成 {idx+1}")
        dlg.resize(600, 400)
        lay = QVBoxLayout(dlg)
        te = QPlainTextEdit()
        te.setPlainText(content)
        te.setReadOnly(True)
        lay.addWidget(te)
        btn_row = QHBoxLayout()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)
        dlg.exec_()
    # [4·文案脚本]  _assembled_has_copy
    def _assembled_has_copy(self, path):
        """该组合视频是否已有同名 .txt 文案。"""
        txt = os.path.splitext(path)[0] + ".txt"
        try:
            return os.path.exists(txt) and os.path.getsize(txt) > 0
        except Exception:
            return False
    # [4·文案脚本]  _save_script_meta
    def _save_script_meta(self, video_path, clips, brand="", product="", model_name="", extra=""):
        """保存脚本关联元数据（与 .txt 同名的 .meta.json）。"""
        import json as _json
        from datetime import datetime
        meta_path = os.path.splitext(video_path)[0] + ".meta.json"
        meta = {
            "generated_at": datetime.now().isoformat(),
            "model": self.main_window.ai_config.get("llm_model", ""),
            "source_clips": [os.path.basename(c) for c in clips if c],
            "product": {
                "brand": brand or "",
                "product": product or "",
                "model": model_name or "",
                "extra": extra or "",
            },
        }
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                _json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f"保存脚本元数据失败: {e}")
    # [4·文案脚本]  _load_script_meta
    def _load_script_meta(self, video_path):
        """读取脚本关联元数据。"""
        import json as _json
        meta_path = os.path.splitext(video_path)[0] + ".meta.json"
        try:
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    return _json.load(f)
        except Exception:
            pass
        return None
    # [4·文案脚本]  _assembled_copy_preview
    def _assembled_copy_preview(self, path):
        """获取文案的文字预览（前30字），无文案返回空串。"""
        if not path:
            return ""
        txt = os.path.splitext(path)[0] + ".txt"
        try:
            if os.path.exists(txt) and os.path.getsize(txt) > 0:
                with open(txt, "r", encoding="utf-8") as f:
                    content = f.read().strip().replace("\n", " ")
                return content[:30] + ("…" if len(content) > 30 else "")
        except Exception:
            pass
        return ""
    # [5·拼接合成]  _on_assembled_double_clicked
    def _on_assembled_double_clicked(self, item):
        """双击预合成列表项：展示完整口播文案。"""
        idx = item.data(Qt.UserRole)
        if idx is None or idx < 0 or idx >= len(self.precompose_plans):
            return
        path = (self.precompose_plans[idx].get("output_path") or "").strip()
        if path and self._assembled_has_copy(path):
            self._view_assembled_copy(idx)
    # [4·文案脚本]  _refresh_assembled_copy_buttons
    def _refresh_assembled_copy_buttons(self):
        w = self.assembled_clips_list_widget
        for i in range(w.count()):
            item = w.item(i)
            if not item:
                continue
            idx = item.data(Qt.UserRole)
            if idx is None or idx < 0 or idx >= len(self.precompose_plans):
                continue
            plan = self.precompose_plans[idx]
            out_path = (plan.get("output_path") or "").strip()
            clip_count = len(plan.get("clips") or [])
            confirmed = plan.get("confirmed") and bool(out_path)
            has_copy = bool(out_path and self._assembled_has_copy(out_path))
            status_txt = "✅已合成" if confirmed else "⏳待确认"
            copy_mark = " 📄" if has_copy else ""
            file_text = os.path.basename(out_path) if out_path else f"{clip_count} 个镜头"
            item.setText(f"[{idx+1}] {file_text}  {status_txt}{copy_mark}")
            if has_copy:
                txt = os.path.splitext(out_path)[0] + ".txt"
                try:
                    with open(txt, "r", encoding="utf-8") as f:
                        snippet = f.read(200).strip()
                    item.setToolTip(snippet + ("..." if len(snippet) == 200 else ""))
                except Exception:
                    item.setToolTip("")
            else:
                item.setToolTip("")
    # [5·拼接合成]  _collect_assembled_paths
    def _collect_assembled_paths(self):
        """按列表顺序返回已确认合成的视频路径。"""
        paths = []
        for plan in self.precompose_plans:
            out_path = (plan.get("output_path") or "").strip()
            if plan.get("confirmed") and out_path and os.path.exists(out_path):
                paths.append(out_path)
        return paths
    # [4·文案脚本]  _gen_copy_for_plan
    def _gen_copy_for_plan(self, plan_index):
        if plan_index < 0 or plan_index >= len(self.precompose_plans):
            return
        out_path = (self.precompose_plans[plan_index].get("output_path") or "").strip()
        if not out_path or not os.path.exists(out_path):
            QMessageBox.information(
                self.parent_widget,
                "请先确认合成",
                "该预合成还没有生成实际视频文件，请先点击“确认合成视频”。"
            )
            return
        self._gen_copy_for_assembled(out_path)
    # [5·拼接合成]  _refresh_precompose_list
    def _refresh_precompose_list(self, select_index=None):
        self.assembled_clips_list_widget.clear()
        for idx, plan in enumerate(self.precompose_plans):
            self._add_assembled_row(idx, plan.get("output_path", ""), plan)
        if select_index is None:
            select_index = self.current_precompose_index
        if select_index is not None and 0 <= select_index < self.assembled_clips_list_widget.count():
            item = self.assembled_clips_list_widget.item(select_index)
            self.assembled_clips_list_widget.setCurrentItem(item)
            self._on_assembled_item_clicked(item)
        self._update_confirm_all_button()
    # [9·其他]  _update_confirm_all_button
    def _update_confirm_all_button(self):
        if not hasattr(self, "btn_confirm_all"):
            return
        has_unconfirmed = any(not p.get("confirmed") for p in self.precompose_plans)
        self.btn_confirm_all.setEnabled(has_unconfirmed)
        # 确认合成视频全部完成后，将绿色背景转移到「合成视频生成文案」按钮
        if hasattr(self, "btn_batch_scene_copy"):
            if not has_unconfirmed and self.btn_batch_scene_copy.isEnabled():
                self.btn_batch_scene_copy.setObjectName("action_button")
            else:
                self.btn_batch_scene_copy.setObjectName("secondary_button")
            self.btn_batch_scene_copy.style().unpolish(self.btn_batch_scene_copy)
            self.btn_batch_scene_copy.style().polish(self.btn_batch_scene_copy)
    # [5·拼接合成]  _confirm_all_precompose
    def _confirm_all_precompose(self):
        if self.concat_worker and self.concat_worker.isRunning():
            QMessageBox.information(self.parent_widget, "处理中", "当前已有合成任务在执行，请稍候。")
            return
        unconfirmed = [i for i, p in enumerate(self.precompose_plans) if not p.get("confirmed")]
        if not unconfirmed:
            QMessageBox.information(self.parent_widget, "无需确认", "所有预合成均已确认。")
            return
        self._confirm_queue = unconfirmed
        self._confirm_next_in_queue()
    # [9·其他]  _confirm_next_in_queue
    def _confirm_next_in_queue(self):
        if not self._confirm_queue:
            self._update_confirm_all_button()
            return
        idx = self._confirm_queue.pop(0)
        self._confirm_precompose(idx)
    # [5·拼接合成]  _confirm_precompose
    def _confirm_precompose(self, index):
        if self.concat_worker and self.concat_worker.isRunning():
            return
        if index < 0 or index >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[index]
        all_clips = list(plan.get("clips") or [])
        deleted_flags = list(plan.get("deleted_flags") or [])
        clips = [c for i, c in enumerate(all_clips) if not (i < len(deleted_flags) and deleted_flags[i])]
        if not clips:
            QMessageBox.warning(self.parent_widget, "镜头为空", "该预合成没有可用镜头（可能都被标记删除），请先在下方镜头列表恢复至少 1 个。")
            if getattr(self, "_confirm_queue", None):
                self._confirm_queue = []
            return

        out_montage_dir = plan.get("out_dir") or getattr(self, "_pending_out_montage_dir", "")
        if not out_montage_dir:
            dir_path = self.concat_src_dir_input.text().strip() or self.folder_path_input.text().strip()
            out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        self._confirming_plan_index = index

        selected_descs = []
        for clip in clips:
            desc = self.split_descriptions.get(os.path.abspath(clip), "")
            selected_descs.append(desc)

        self._launch_concat_worker(
            selected_clips=clips,
            out_montage_dir=out_montage_dir,
            recombine_mode=plan.get("mode", "random"),
            target_clip_count=len(clips),
            batch_count=1,
            randomness="low",
            selected_descriptions_list=selected_descs,
            beat_times=plan.get("beat_times") if plan.get("mode") == "beat" else None,
            music_path=plan.get("music_path", "") if plan.get("mode") == "beat" else "",
            music_range=plan.get("music_range") if plan.get("mode") == "beat" else None,
        )
        remaining = len(getattr(self, "_confirm_queue", []) or [])
        self.stage_label.setText(f"🎬 正在确认合成预合成 {index + 1}... (剩余 {remaining} 条待确认)")
    # [2·基础设施]  _refresh_sources_for_plan
    def _refresh_sources_for_plan(self, plan_index):
        self.sources_detail_widget.setRowCount(0)
        if plan_index < 0 or plan_index >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[plan_index]
        clips = list(plan.get("clips") or [])
        deleted_flags = list(plan.get("deleted_flags") or [])
        self.sources_detail_widget.setRowCount(len(clips))
        for idx, src_path in enumerate(clips):
            filename = os.path.basename(src_path)
            cache_item = getattr(self, "split_clips_cache", {}).get(os.path.abspath(src_path))
            if cache_item:
                time_str = cache_item.get("time_str", "N/A")
                desc = cache_item.get("desc", "")
            else:
                parsed = self._parse_split_filename(filename)
                if parsed:
                    _, start_str, end_str, desc = parsed
                    time_str = f"{start_str} --> {end_str}"
                else:
                    time_str = "N/A"
                    desc = self.split_descriptions.get(os.path.abspath(src_path), "")

            grip_item = QTableWidgetItem("⠿")
            grip_item.setTextAlignment(Qt.AlignCenter)
            grip_item.setFlags(grip_item.flags() & ~Qt.ItemIsEditable)
            grip_item.setData(Qt.UserRole, src_path)
            self.sources_detail_widget.setItem(idx, 0, grip_item)

            file_item = QTableWidgetItem(filename)
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 1, file_item)

            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignCenter)
            time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 2, time_item)

            desc_item = QTableWidgetItem(desc)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 3, desc_item)

            # 评分：优先用缓存，否则现场计算
            score = cache_item.get("score") if cache_item else None
            if score is None:
                score = self._score_clip(src_path)
                if cache_item is not None:
                    cache_item["score"] = score
            score_text = f"{score:.1f}" if score >= 0 else "—"
            score_item = QTableWidgetItem(score_text)
            score_item.setTextAlignment(Qt.AlignCenter)
            score_item.setFlags(score_item.flags() & ~Qt.ItemIsEditable)
            if score >= 8.0:
                score_item.setForeground(QColor("#2ecc71"))
            elif score >= 6.0:
                score_item.setForeground(QColor("#f1c40f"))
            elif score >= 0:
                score_item.setForeground(QColor("#e74c3c"))
            self.sources_detail_widget.setItem(idx, 4, score_item)

            is_deleted = idx < len(deleted_flags) and deleted_flags[idx]
            if is_deleted:
                for col in range(5):
                    cell = self.sources_detail_widget.item(idx, col)
                    if cell:
                        cell.setBackground(Qt.red)
    # [9·其他]  _mark_current_plan_dirty
    def _mark_current_plan_dirty(self):
        idx = self.current_precompose_index
        if idx < 0 or idx >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[idx]
        plan["confirmed"] = False
        plan["output_path"] = ""
        self._refresh_precompose_list(select_index=idx)
        if hasattr(self, "btn_batch_scene_copy"):
            self.btn_batch_scene_copy.setEnabled(bool(self._collect_assembled_paths()))
        self._update_confirm_all_button()
    # [2·基础设施]  _on_source_order_changed
    def _on_source_order_changed(self, from_row, to_row):
        idx = self.current_precompose_index
        if idx < 0 or idx >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[idx]
        clips = list(plan.get("clips") or [])
        deleted_flags = list(plan.get("deleted_flags") or [])
        if from_row < 0 or from_row >= len(clips) or to_row < 0 or to_row >= len(clips):
            return
        clip = clips.pop(from_row)
        clips.insert(to_row, clip)
        if from_row < len(deleted_flags):
            flag = deleted_flags.pop(from_row)
            insert_pos = min(to_row, len(deleted_flags))
            deleted_flags.insert(insert_pos, flag)
        plan["clips"] = clips
        plan["deleted_flags"] = deleted_flags
        plan["descriptions"] = []
        self._mark_current_plan_dirty()
        self._refresh_sources_for_plan(idx)
        self.sources_detail_widget.selectRow(to_row)
        self._start_sequence_preview_for_plan(idx)
    # [2·基础设施]  _on_source_context_menu
    def _on_source_context_menu(self, pos):
        row = self.sources_detail_widget.rowAt(pos.y())
        if row < 0:
            return
        idx = self.current_precompose_index
        if idx < 0 or idx >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[idx]
        deleted_flags = list(plan.get("deleted_flags") or [])
        is_deleted = row < len(deleted_flags) and deleted_flags[row]

        menu = QMenu(self.sources_detail_widget)
        if is_deleted:
            act_restore = menu.addAction("↩ 恢复镜头")
        else:
            act_delete = menu.addAction("🗑 标记删除（不参与合成和预览）")
        action = menu.exec(self.sources_detail_widget.viewport().mapToGlobal(pos))
        if action:
            self._toggle_source_deleted(row)
    # [2·基础设施]  _toggle_source_deleted
    def _toggle_source_deleted(self, row):
        idx = self.current_precompose_index
        if idx < 0 or idx >= len(self.precompose_plans):
            return
        plan = self.precompose_plans[idx]
        clips = list(plan.get("clips") or [])
        deleted_flags = list(plan.get("deleted_flags") or [])
        while len(deleted_flags) < len(clips):
            deleted_flags.append(False)
        if row >= len(deleted_flags):
            return
        active_count = sum(1 for f in deleted_flags if not f)
        if not deleted_flags[row] and active_count <= 1:
            QMessageBox.warning(self.parent_widget, "无法删除", "至少保留 1 个有效镜头片段。")
            return
        deleted_flags[row] = not deleted_flags[row]
        plan["deleted_flags"] = deleted_flags
        plan["confirmed"] = False
        plan["output_path"] = ""
        self._refresh_precompose_list(select_index=idx)
        self._refresh_sources_for_plan(idx)
        self._update_confirm_all_button()
        self._start_sequence_preview_for_plan(idx)
    # [5·拼接合成]  _start_sequence_preview_for_plan
    def _start_sequence_preview_for_plan(self, plan_index):
        self.preview_player.stop()
        self._preview_sequence_clips = []
        if plan_index < 0 or plan_index >= len(self.precompose_plans):
            self._preview_sequence_clips = []
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setIcon(mdi_icon("play"))
            return
        plan = self.precompose_plans[plan_index]
        clips = list(plan.get("clips") or [])
        deleted_flags = list(plan.get("deleted_flags") or [])
        active_clips = []
        for i, clip in enumerate(clips):
            is_deleted = i < len(deleted_flags) and deleted_flags[i]
            if not is_deleted and clip and os.path.exists(clip):
                active_clips.append(os.path.abspath(clip))
        self._preview_sequence_clips = active_clips
        if not active_clips:
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setIcon(mdi_icon("play"))
            return
        self._preview_sequence_idx = 0
        self._play_current_sequence_clip()
    # [5·拼接合成]  _start_sequence_preview
    def _start_sequence_preview(self, clips, start_idx=0):
        self._preview_sequence_clips = [os.path.abspath(p) for p in clips if p and os.path.exists(p)]
        if not self._preview_sequence_clips:
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setIcon(mdi_icon("play"))
            return
        self._preview_sequence_idx = max(0, min(start_idx, len(self._preview_sequence_clips) - 1))
        self._play_current_sequence_clip()
    # [9·其他]  _play_current_sequence_clip
    def _play_current_sequence_clip(self):
        if not self._preview_sequence_clips:
            return
        clip = self._preview_sequence_clips[self._preview_sequence_idx]
        from PySide6.QtCore import QUrl
        self.preview_player.setSource(QUrl.fromLocalFile(clip))
        self.preview_player.play()
        self.btn_preview_play.setIcon(mdi_icon("pause"))
        total = len(self._preview_sequence_clips)
        self.preview_overlay_label.setText(f"镜头 {self._preview_sequence_idx + 1}/{total}")
        self.preview_overlay_label.adjustSize()
        self.preview_overlay_label.show()
    # [3·分割]  _get_video_scene_sources
    def _get_video_scene_sources(self, path):
        """读取某组合视频的 _sources.txt，返回源镜头路径列表。"""
        sources_file = os.path.splitext(path)[0] + "_sources.txt"
        if not os.path.exists(sources_file):
            return []
        try:
            with open(sources_file, "r", encoding="utf-8") as sf:
                return [line.strip() for line in sf if line.strip()]
        except Exception:
            return []
    # [3·分割]  _get_video_scene_descriptions
    def _get_video_scene_descriptions(self, path):
        """读取某组合视频的 _sources.txt，按顺序解析出每个镜头画面的描述文案。"""
        scenes = []
        sources_file = os.path.splitext(path)[0] + "_sources.txt"
        if not os.path.exists(sources_file):
            return scenes
        try:
            with open(sources_file, "r", encoding="utf-8") as sf:
                src_paths = [line.strip() for line in sf if line.strip()]
        except Exception as e:
            log.warning(f"读取视频源镜头列表失败: {e}")
            return scenes

        for src_path in src_paths:
            filename = os.path.basename(src_path)
            cache_item = getattr(self, "split_clips_cache", {}).get(os.path.abspath(src_path))
            if cache_item:
                desc = cache_item.get("desc", "")
            else:
                desc = ""
                parsed = self._parse_split_filename(filename)
                if parsed:
                    _, _start_str, _end_str, desc = parsed
                if not desc:
                    desc = self.split_descriptions.get(os.path.abspath(src_path), "")
            scenes.append(desc or "")
        return scenes
    # [4·文案脚本]  _ensure_shared_product_info
    def _ensure_shared_product_info(self, force=False):
        """获取一次共用的产品背景信息（品牌/产品/型号/卖点），缓存后全局复用。

        返回 (brand, product, model_name, extra)；用户取消时返回 None。
        """
        cached = getattr(self, "_shared_product_info", None)
        if cached is not None and not force:
            return cached

        dlg = ProductCopyInputDialog(self.parent_widget)
        if cached is not None:
            # 复用上次填写的内容，便于微调
            b, p, m, e = cached
            dlg.brand_in.setText(b)
            dlg.product_in.setText(p)
            dlg.model_in.setText(m)
            dlg.extra_in.setPlainText(e)
        if dlg.exec() != QDialog.Accepted:
            return None
        info = dlg.get_values()
        self._shared_product_info = info
        return info
    # [4·文案脚本]  _gen_copy_for_assembled
    def _gen_copy_for_assembled(self, path):
        """为某个组合视频，根据其画面镜头描述 + 共用产品背景，用大模型生成口播文案并存同名 .txt。
        如果镜头缺少画面描述，先用视觉 LLM 自动补生成。"""
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model = (cfg.get("llm_model", "") or "deepseek-v4-flash").strip()
        if not model:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 模型名称。")
            return

        scenes = self._get_video_scene_descriptions(path)
        if not scenes:
            QMessageBox.warning(self.parent_widget, "无画面信息",
                                "未找到该视频的镜头画面信息（缺少 _sources.txt），无法按画面生成文案。")
            return

        # 检查是否有镜头缺少描述，如有则先用视觉 LLM 补生成
        sources_file = os.path.splitext(path)[0] + "_sources.txt"
        missing_clips = []
        if os.path.exists(sources_file):
            with open(sources_file, "r", encoding="utf-8") as sf:
                src_paths = [line.strip() for line in sf if line.strip()]
            for i, src_path in enumerate(src_paths):
                desc = scenes[i] if i < len(scenes) else ""
                if not desc or not desc.strip():
                    missing_clips.append(os.path.abspath(src_path))

        if missing_clips:
            vision_model = cfg.get("llm_vision_model", "").strip() or model
            self.stage_label.setText(f"正在为 {len(missing_clips)} 个缺失描述的镜头生成画面描述...")
            self._batch_gen_missing_descriptions(
                missing_clips, "", "", vision_model,
                lambda: self._do_gen_copy_for_assembled(path, cfg, "", "", model))
        else:
            self._do_gen_copy_for_assembled(path, cfg, "", "", model)
    # [4·文案脚本]  _do_gen_copy_for_assembled
    def _do_gen_copy_for_assembled(self, path, cfg, api_url, api_key, model):
        """实际执行单个视频的口播文案生成（描述已就绪后调用）。"""
        scenes = self._get_video_scene_descriptions(path)

        companion_txt = os.path.splitext(path)[0] + ".txt"
        if self._assembled_has_copy(path):
            existing = ""
            try:
                with open(companion_txt, "r", encoding="utf-8") as f:
                    existing = f.read().strip()
            except Exception:
                pass
            preview = existing[:120] + ("..." if len(existing) > 120 else "")
            reply = QMessageBox.question(
                self.parent_widget, "已有文案",
                f"该视频已存在文案：\n\n{preview}\n\n是否重新生成并覆盖？",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        info = self._ensure_shared_product_info()
        if info is None:
            return
        brand, product, model_name, extra = info

        self.stage_label.setText(f"正在根据画面为 {os.path.basename(path)} 生成口播文案...")
        self._scene_copy_worker = SceneCopyWorker(
            api_url, api_key, model, scenes, brand, product, model_name, extra)

        def on_ok(content, ctxt=companion_txt, pth=path):
            try:
                with open(ctxt, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "保存失败", f"写入文案文件失败：\n{e}")
                return
            # 保存关联元数据
            clips = self._get_video_scene_sources(pth)
            self._save_script_meta(pth, clips, brand, product, model_name, extra)
            self.stage_label.setText("✅ 口播文案已按画面生成并保存")
            self._refresh_assembled_copy_buttons()
            QMessageBox.information(
                self.parent_widget, "文案已生成",
                f"已根据画面为 {os.path.basename(pth)} 生成口播文案并保存：\n{ctxt}\n\n"
                f"——\n{content}\n——\n\n进入下一步「口播配音」会自动载入。")

        def on_err(msg):
            self.stage_label.setText("❌ 文案生成失败")
            QMessageBox.critical(self.parent_widget, "生成失败", f"调用大模型失败：\n{msg}")

        self._scene_copy_worker.finished.connect(on_ok)
        self._scene_copy_worker.error.connect(on_err)
        self._scene_copy_worker.start()
    # [3·分割]  _batch_gen_copy_by_scene
    def _batch_gen_copy_by_scene(self):
        """一键为所有已生成的组合视频，按各自画面镜头描述生成口播文案（共用一份产品背景）。
        如果镜头缺少画面描述（如原视频无声音未生成），先用视觉 LLM 自动补生成描述。"""
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model = (cfg.get("llm_model", "") or "deepseek-v4-flash").strip()
        if not model:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 模型名称。")
            return

        paths = self._collect_assembled_paths()
        if not paths:
            QMessageBox.warning(self.parent_widget, "无可生成视频",
                                "请先点击「镜头重组」生成预合成，并至少确认合成 1 条视频。")
            return

        targets = paths
        existing = [p for p in paths if self._assembled_has_copy(p)]
        if existing:
            reply = QMessageBox.question(
                self.parent_widget, "已有部分文案",
                f"共 {len(paths)} 个视频，其中 {len(existing)} 个已存在文案。\n\n"
                f"是 = 覆盖并重新生成全部\n否 = 只为缺失文案的视频生成\n取消 = 不操作",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.No:
                targets = [p for p in paths if not self._assembled_has_copy(p)]
                if not targets:
                    QMessageBox.information(self.parent_widget, "无需生成", "所有视频都已存在文案。")
                    return

        info = self._ensure_shared_product_info(force=True)
        if info is None:
            return

        # 检查所有目标视频的镜头是否有画面描述，收集缺失描述的镜头
        missing_desc_clips = set()
        for path in targets:
            scenes = self._get_video_scene_descriptions(path)
            sources_file = os.path.splitext(path)[0] + "_sources.txt"
            if os.path.exists(sources_file):
                with open(sources_file, "r", encoding="utf-8") as sf:
                    src_paths = [line.strip() for line in sf if line.strip()]
                for i, src_path in enumerate(src_paths):
                    desc = scenes[i] if i < len(scenes) else ""
                    if not desc or not desc.strip():
                        missing_desc_clips.add(os.path.abspath(src_path))

        if missing_desc_clips:
            # 有镜头缺少画面描述，用视觉 LLM 自动生成
            vision_model = cfg.get("llm_vision_model", "").strip() or model
            self._batch_gen_missing_descriptions(
                list(missing_desc_clips), "", "", vision_model,
                lambda: self._start_batch_copy("", "", model, info, targets))
        else:
            self._start_batch_copy("", "", model, info, targets)
    # [4·文案脚本]  _batch_gen_missing_descriptions
    def _batch_gen_missing_descriptions(self, clip_paths, api_url, api_key, model, on_done):
        """用视觉 LLM 为缺少描述的分割镜头批量生成画面描述。"""
        if not clip_paths:
            on_done()
            return

        self.stage_label.setText(f"正在为 {len(clip_paths)} 个缺失描述的镜头生成画面描述...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        # 构建场景列表（时间从文件名解析或用 0）
        scenes = []
        split_paths = []
        for cp in clip_paths:
            parsed = self._parse_split_filename(os.path.basename(cp))
            if parsed:
                start_str, end_str = parsed[1], parsed[2]
                try:
                    start_sec = float(start_str.replace(",", "."))
                    end_sec = float(end_str.replace(",", "."))
                    scenes.append((start_sec, end_sec))
                except Exception:
                    scenes.append((0.0, 5.0))
            else:
                scenes.append((0.0, 5.0))
            split_paths.append(cp)

        self._desc_gen_worker = BatchGenerateDescriptionsWorker(
            api_url, api_key, model, "", scenes, split_paths)

        def on_desc_ok(json_str):
            import json as _json
            try:
                desc_dict = _json.loads(json_str)
                for idx_str, desc in desc_dict.items():
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(clip_paths):
                        clip_path = os.path.abspath(clip_paths[idx])
                        self.split_descriptions[clip_path] = desc
                        # 同步到缓存
                        if clip_path in getattr(self, "split_clips_cache", {}):
                            self.split_clips_cache[clip_path]["desc"] = desc
                log.info(f"已为 {len(desc_dict)} 个镜头补充画面描述")
            except Exception as e:
                log.warning(f"解析镜头描述结果失败: {e}")
            self.progress_bar.setValue(100)
            on_done()

        def on_desc_err(msg):
            log.warning(f"视觉 LLM 生成镜头描述失败: {msg}，将使用空描述继续生成文案")
            self.progress_bar.setValue(100)
            on_done()

        self._desc_gen_worker.finished.connect(on_desc_ok)
        self._desc_gen_worker.error.connect(on_desc_err)
        self._desc_gen_worker.start()
    # [4·文案脚本]  _start_batch_copy
    def _start_batch_copy(self, api_url, api_key, model, info, targets):
        """启动批量口播文案生成。"""
        self._batch_llm = (api_url, api_key, model)
        self._batch_product_info = info
        self._batch_copy_queue = list(targets)
        self._batch_copy_total = len(targets)
        self._batch_copy_done = 0
        self._batch_copy_failures = []
        self.btn_batch_scene_copy.setEnabled(False)
        self._batch_copy_next()
    # [4·文案脚本]  _batch_copy_next
    def _batch_copy_next(self):
        """处理批量队列中的下一个组合视频（逐个串行调用大模型）。"""
        if not self._batch_copy_queue:
            self.btn_batch_scene_copy.setEnabled(True)
            self._refresh_assembled_copy_buttons()
            # Refresh step-3 voice table so newly written .txt files are shown immediately
            self._do_scan_voice_video_dir()
            fails = self._batch_copy_failures
            ok_count = self._batch_copy_total - len(fails)
            if fails:
                self.stage_label.setText(f"⚠ 批量文案生成完成：成功 {ok_count}，失败 {len(fails)}")
                detail = "\n".join(f"· {os.path.basename(p)}：{m}" for p, m in fails[:10])
                more = "" if len(fails) <= 10 else f"\n…… 等共 {len(fails)} 个失败"
                QMessageBox.warning(
                    self.parent_widget, "部分失败",
                    f"批量按画面生成文案完成。\n成功 {ok_count} 个，失败 {len(fails)} 个：\n\n{detail}{more}")
            else:
                self.stage_label.setText(f"✅ 已为全部 {ok_count} 个视频按画面生成口播文案")
                QMessageBox.information(
                    self.parent_widget, "全部完成",
                    f"已根据画面为全部 {ok_count} 个组合视频生成口播文案并保存。\n"
                    f"进入下一步「口播配音」会自动载入。")
            return

        path = self._batch_copy_queue.pop(0)
        idx = self._batch_copy_done + 1
        self.stage_label.setText(
            f"正在按画面生成文案 ({idx}/{self._batch_copy_total})：{os.path.basename(path)}")

        scenes = self._get_video_scene_descriptions(path)
        if not scenes:
            # _sources.txt missing or empty — generate a single-line product copy as fallback
            scenes = ["（无画面描述，请根据产品背景撰写一行主推口播文案）"]

        api_url, api_key, model = self._batch_llm
        brand, product, model_name, extra = self._batch_product_info
        # 获取合成视频总时长，用于文案字数限制
        total_dur = get_media_duration(path) if os.path.isfile(path) else 0.0
        self._scene_copy_worker = SceneCopyWorker(
            api_url, api_key, model, scenes, brand, product, model_name, extra,
            total_duration=total_dur)

        companion_txt = os.path.splitext(path)[0] + ".txt"
        source_clips = self._get_video_scene_sources(path)

        def on_ok(content, ctxt=companion_txt, pth=path, clips=source_clips):
            try:
                with open(ctxt, "w", encoding="utf-8") as f:
                    f.write(content)
                # 保存关联元数据
                self._save_script_meta(pth, clips, brand, product, model_name, extra)
                # Invalidate the step-3 cache entry so the table re-reads the file on next scan
                if hasattr(self, "original_texts"):
                    self.original_texts.pop(pth, None)
            except Exception as e:
                self._batch_copy_failures.append((pth, f"写入失败：{e}"))
            self._batch_copy_done += 1
            self._batch_copy_next()

        def on_err(msg, pth=path):
            self._batch_copy_failures.append((pth, msg))
            self._batch_copy_done += 1
            self._batch_copy_next()

        self._scene_copy_worker.finished.connect(on_ok)
        self._scene_copy_worker.error.connect(on_err)
        self._scene_copy_worker.start()
    # [5·拼接合成]  _on_assembled_item_clicked
    def _on_assembled_item_clicked(self, item):
        idx = item.data(Qt.UserRole)
        if idx is None:
            idx = -1
        self.current_precompose_index = idx

        path = ""
        clips = []
        if 0 <= idx < len(self.precompose_plans):
            plan = self.precompose_plans[idx]
            path = (plan.get("output_path") or "").strip()
            clips = list(plan.get("clips") or [])
        else:
            text = item.text()
            if "   (" in text and text.endswith(")"):
                path = text.split("   (")[-1][:-1]
                if path and os.path.exists(path):
                    clips = [path]

        self.assembled_video_path = path
        self.btn_next_to_step_3.setEnabled(bool(self._collect_assembled_paths()))
        self._update_final_inputs_label()

        self._refresh_sources_for_plan(idx)
        if 0 <= idx < len(self.precompose_plans):
            self._start_sequence_preview_for_plan(idx)
        elif clips:
            self._start_sequence_preview(clips, 0)
        else:
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setIcon(mdi_icon("play"))
    # [8·事件回调]  _toggle_preview_video
    def _toggle_preview_video(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.preview_player.playbackState() == QMediaPlayer.PlayingState:
            self.preview_player.pause()
            self.btn_preview_play.setIcon(mdi_icon("play"))
        else:
            self.preview_player.play()
            self.btn_preview_play.setIcon(mdi_icon("pause"))
    # [9·其他]  _set_preview_position
    def _set_preview_position(self, position):
        self.preview_player.setPosition(position)
    # [8·事件回调]  _on_preview_position_changed
    def _on_preview_position_changed(self, position):
        self.preview_slider.setValue(position)
    # [8·事件回调]  _on_preview_duration_changed
    def _on_preview_duration_changed(self, duration):
        self.preview_slider.setRange(0, duration)
    # [8·事件回调]  _on_preview_media_status_changed
    def _on_preview_media_status_changed(self, status):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            from PySide6.QtCore import QTimer
            if status == QMediaPlayer.EndOfMedia and self._preview_sequence_clips:
                self._preview_sequence_idx += 1
                if self._preview_sequence_idx >= len(self._preview_sequence_clips):
                    self._preview_sequence_idx = 0
                # 用 QTimer 延迟播放下一个，避免在 mediaStatusChanged 信号内
                # 直接调 setSource() 导致 Qt 内部死锁 / 界面卡死
                QTimer.singleShot(50, self._play_current_sequence_clip)
            elif status == QMediaPlayer.InvalidMedia:
                # 当前片段无法播放，跳过并尝试下一个
                if self._preview_sequence_clips:
                    log.warning(f"[预览] 无法播放片段: {self._preview_sequence_clips[self._preview_sequence_idx]}")
                    QTimer.singleShot(50, self._skip_to_next_preview_clip)
        except Exception:
            pass
    # [9·其他]  _skip_to_next_preview_clip
    def _skip_to_next_preview_clip(self):
        """跳过当前无法播放的片段，播下一个。"""
        if not self._preview_sequence_clips:
            return
        self._preview_sequence_idx += 1
        if self._preview_sequence_idx >= len(self._preview_sequence_clips):
            self._preview_sequence_idx = 0
        self._play_current_sequence_clip()
    # [8·事件回调]  _preview_video_item
    def _preview_video_item(self, item):
        path = ""
        idx = item.data(Qt.UserRole)
        if idx is not None and 0 <= idx < len(self.precompose_plans):
            plan = self.precompose_plans[idx]
            out_path = (plan.get("output_path") or "").strip()
            if out_path and os.path.exists(out_path):
                path = out_path
            else:
                clips = list(plan.get("clips") or [])
                if clips:
                    path = clips[0]
        if not path:
            text = item.text()
            if "   (" in text and text.endswith(")"):
                path = text.split("   (")[-1][:-1]
            else:
                path = text
        
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "无法播放", f"播放视频失败:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到该视频文件:\n{path}")
    # [9·其他]  _play_video
    def _play_video(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到视频文件:\n{path}")
    # [9·其他]  _make_play_slot
    def _make_play_slot(self, filepath):
        return lambda: self._play_video(filepath)
    # [5·拼接合成]  _preview_concat_table_item
    def _preview_concat_table_item(self, item):
        if not getattr(self, "concat_clips_list_widget", None):
            return
        row = item.row()
        col = item.column()
        
        # Col 2 (描述文案): double-click shows popup with full description
        if col == 2:
            desc_item = self.concat_clips_list_widget.item(row, 2)
            full_desc = desc_item.text().strip() if desc_item else ""
            file_item = self.concat_clips_list_widget.item(row, 0)
            filename = file_item.text() if file_item else "未知"
            
            dlg = QDialog(self.parent_widget)
            dlg.setWindowTitle(f"镜头描述 — {filename}")
            dlg.setMinimumWidth(500)
            dlg.setMinimumHeight(250)
            layout = QVBoxLayout(dlg)
            
            desc_edit = QTextEdit()
            desc_edit.setPlainText(full_desc)
            desc_edit.setStyleSheet("""
                QTextEdit {
                    background-color: #1c1c1e;
                    color: #ecf0f1;
                    border: 1px solid #3a3a3c;
                    border-radius: 6px;
                    padding: 10px;
                    font-size: 14px;
                    line-height: 1.6;
                }
            """)
            layout.addWidget(desc_edit)
            
            btn_row = QHBoxLayout()
            btn_save = mdi_button("保存修改", "save")
            btn_save.setObjectName("primary_button")
            btn_close = QPushButton("关闭")
            btn_close.setObjectName("secondary_button")
            
            def do_save():
                new_text = desc_edit.toPlainText().strip()
                if desc_item:
                    desc_item.setText(new_text)
                    # Trigger save to split_descriptions
                    path = file_item.data(Qt.UserRole) if file_item else ""
                    if path:
                        self.split_descriptions[os.path.abspath(path)] = new_text
                    self._save_split_srt()
                dlg.accept()
            
            btn_save.clicked.connect(do_save)
            btn_close.clicked.connect(dlg.reject)
            btn_row.addWidget(btn_save)
            btn_row.addWidget(btn_close)
            layout.addLayout(btn_row)
            
            dlg.exec()
            return
        
        # Default: play video on double-click
        file_item = self.concat_clips_list_widget.item(row, 0)
        if file_item:
            path = file_item.data(Qt.UserRole)
            if path:
                self._play_video(path)
    # [5·拼接合成]  _on_concat_table_cell_changed
    def _on_concat_table_cell_changed(self, row, col):
        if not getattr(self, "concat_clips_list_widget", None):
            return
        if col == 0:
            self._update_concat_count_lbl()
        elif col == 2:
            file_item = self.concat_clips_list_widget.item(row, 0)
            desc_item = self.concat_clips_list_widget.item(row, 2)
            if file_item and desc_item:
                path = file_item.data(Qt.UserRole)
                if path:
                    new_desc = desc_item.text().strip()
                    self.split_descriptions[os.path.abspath(path)] = new_desc
                    self._save_split_srt()
