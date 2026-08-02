# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QProgressBar, QMessageBox, QFrame, QListWidget, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QDoubleSpinBox, QWidget,
                               QComboBox)
from PySide6.QtCore import Qt
from gui.montage.base_step_view import BaseStepView
from utils.gui_icons import mdi_button

class Step1SplitView(BaseStepView):
    """步骤 1: 镜头智能分割界面"""
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

        # Input source videos
        row_dir = QHBoxLayout()
        row_dir.addWidget(QLabel("原始素材:"))
        self.main_page.folder_path_input = QLineEdit()
        self.main_page.folder_path_input.setPlaceholderText("选择一个或多个视频素材，可多次追加...")
        self.main_page.folder_path_input.setReadOnly(True)
        row_dir.addWidget(self.main_page.folder_path_input)
        
        btn_sel = mdi_button("选择素材", "folder")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self.main_page._select_folder)
        row_dir.addWidget(btn_sel)
        card_layout.addLayout(row_dir)

        # Raw videos list
        card_layout.addWidget(QLabel("已选择的原始视频素材 (双击可播放预览，右键可删除):"))
        self.main_page.video_list = QListWidget()
        self.main_page.video_list.setFixedHeight(120)
        self.main_page.video_list.setTextElideMode(Qt.ElideRight)
        self.main_page.video_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.main_page.video_list.itemClicked.connect(self.main_page._check_split_clips_exist)
        self.main_page.video_list.itemDoubleClicked.connect(self.main_page._preview_video_item)
        self.main_page.video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.main_page.video_list.customContextMenuRequested.connect(self.main_page._show_video_context_menu)
        card_layout.addWidget(self.main_page.video_list)

        # SceneDetect Config
        split_row = QHBoxLayout()
        split_row.addWidget(QLabel("分割阈值 (10-100):"))
        self.main_page.threshold_spin = QDoubleSpinBox()
        self.main_page.threshold_spin.setRange(10.0, 100.0)
        self.main_page.threshold_spin.setValue(50.0)
        self.main_page.threshold_spin.setSingleStep(1.0)
        split_row.addWidget(self.main_page.threshold_spin)

        split_row.addWidget(QLabel("最少帧数 (默认15):"))
        self.main_page.min_len_spin = QDoubleSpinBox()
        self.main_page.min_len_spin.setDecimals(0)
        self.main_page.min_len_spin.setRange(5, 100)
        self.main_page.min_len_spin.setValue(15)
        split_row.addWidget(self.main_page.min_len_spin)

        split_row.addSpacing(12)
        split_row.addWidget(QLabel("精华时长:"))
        self.main_page.spin_highlight_sec = QDoubleSpinBox()
        self.main_page.spin_highlight_sec.setRange(1.0, 30.0)
        self.main_page.spin_highlight_sec.setValue(3.0)
        self.main_page.spin_highlight_sec.setSingleStep(1.0)
        self.main_page.spin_highlight_sec.setSuffix(" 秒")
        self.main_page.spin_highlight_sec.setFixedWidth(80)
        self.main_page.spin_highlight_sec.setToolTip("无法分割的视频，自动挑出多长的精华片段")
        split_row.addWidget(self.main_page.spin_highlight_sec)

        split_row.addStretch()

        # Dependencies auto check in UI
        try:
            import scenedetect
            self.main_page.has_scenedetect_dep = True
        except ImportError:
            self.main_page.has_scenedetect_dep = False

        self.main_page.dep_status_widget = QWidget()
        dep_layout = QHBoxLayout(self.main_page.dep_status_widget)
        dep_layout.setContentsMargins(0, 0, 0, 0)
        
        if self.main_page.has_scenedetect_dep:
            lbl_dep = QLabel("✅ 镜头分割依赖就绪")
            lbl_dep.setStyleSheet("color: #2ecc71; font-weight: bold;")
            dep_layout.addWidget(lbl_dep)
        else:
            self.main_page.btn_install_deps = mdi_button("安装智能分割依赖", "wrench")
            self.main_page.btn_install_deps.setObjectName("secondary_button")
            self.main_page.btn_install_deps.clicked.connect(self.main_page._install_scenedetect)
            dep_layout.addWidget(self.main_page.btn_install_deps)
            
        split_row.addWidget(self.main_page.dep_status_widget)

        # 单视频镜头分割（合并挑精华：可分割的先分割，无法分割的自动挑精华）
        self.main_page.btn_split = mdi_button("开始智能镜头分割", "cut")
        self.main_page.btn_split.setObjectName("action_button")
        self.main_page.btn_split.setFixedHeight(35)
        self.main_page.btn_split.setToolTip(
            "对列表中所有视频逐个处理：能做镜头分割的先做镜头分割，\n"
            "无法分割的视频自动挑出一段精华片段，统一写入 splits 目录。")
        self.main_page.btn_split.clicked.connect(self.main_page._start_split)
        split_row.addWidget(self.main_page.btn_split)

        self.main_page.btn_gen_shot_analysis = mdi_button("生成镜头分析", "sparkles")
        self.main_page.btn_gen_shot_analysis.setObjectName("secondary_button")
        self.main_page.btn_gen_shot_analysis.setFixedHeight(35)
        self.main_page.btn_gen_shot_analysis.setToolTip(
            "调用服务端 /material/score_clip 对每个镜头做 AI 分析，\n"
            "返回的评分与画面描述自动填入下方表格。")
        self.main_page.btn_gen_shot_analysis.clicked.connect(self.main_page._gen_shot_analysis)
        split_row.addWidget(self.main_page.btn_gen_shot_analysis)
        card_layout.addLayout(split_row)

        # Split results table view (with score filter row above)
        table_header_row = QHBoxLayout()
        table_header_row.addWidget(QLabel("已分割出的最小单位镜头片段 (双击可播放预览，双击画面描述列可手动修改):"), 1)
        table_header_row.addStretch()
        table_header_row.addWidget(QLabel("评分过滤:"))
        self.main_page.step1_score_filter_combo = QComboBox()
        self.main_page.step1_score_filter_combo.addItem("不过滤", 0.0)
        for s in [1, 2, 3, 4, 5, 6, 7, 8, 9]:
            self.main_page.step1_score_filter_combo.addItem(f"≥ {s} 分", float(s))
        self.main_page.step1_score_filter_combo.setCurrentIndex(6)  # 默认 ≥ 6 分
        self.main_page.step1_score_filter_combo.setToolTip(
            "按评分筛选镜头：达到阈值的镜头才会作为选中素材带入下一步镜头重组。")
        self.main_page.step1_score_filter_combo.currentIndexChanged.connect(
            self.main_page._on_step1_score_filter_changed)
        table_header_row.addWidget(self.main_page.step1_score_filter_combo)
        card_layout.addLayout(table_header_row)
        self.main_page.split_result_table = QTableWidget()
        self.main_page.split_result_table.setWordWrap(False)
        self.main_page.split_result_table.verticalHeader().setDefaultSectionSize(30)
        self.main_page.split_result_table.setColumnCount(9)
        self.main_page.split_result_table.setHorizontalHeaderLabels(
            ["☑", "序号", "视频片段", "景别", "时长", "主要画面", "产品", "型号", "评分"])
        self.main_page.split_result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.main_page.split_result_table.setMinimumHeight(180)
        self.main_page.split_result_table.itemDoubleClicked.connect(self.main_page._preview_table_item)
        self.main_page.split_result_table.cellChanged.connect(self.main_page._on_table_cell_changed)
        self.main_page.split_result_table.itemChanged.connect(self.main_page._on_step1_checkbox_changed)
        
        header = self.main_page.split_result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.main_page.split_result_table.setColumnWidth(0, 32)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.main_page.split_result_table.setColumnWidth(2, 160)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.main_page.split_result_table.setColumnWidth(3, 60)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.main_page.split_result_table.setColumnWidth(4, 50)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.main_page.split_result_table.setColumnWidth(6, 80)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        self.main_page.split_result_table.setColumnWidth(7, 80)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self.main_page.split_result_table.setColumnWidth(8, 50)
        header.setStretchLastSection(False)
        
        card_layout.addWidget(self.main_page.split_result_table)
        layout.addWidget(card, 1)

        # Navigation row
        nav_row = QHBoxLayout()
        self.main_page.btn_open_splits_dir = mdi_button("打开已分割镜头目录", "folder")
        self.main_page.btn_open_splits_dir.setObjectName("secondary_button")
        self.main_page.btn_open_splits_dir.clicked.connect(self.main_page._open_splits_dir)
        nav_row.addWidget(self.main_page.btn_open_splits_dir)

        nav_row.addStretch()
        self.main_page.btn_next_to_step_2 = mdi_button("下一步：镜头重组", "right")
        self.main_page.btn_next_to_step_2.setObjectName("primary_button")
        self.main_page.btn_next_to_step_2.setEnabled(True)
        self.main_page.btn_next_to_step_2.clicked.connect(self.main_page._go_next_to_step2)
        nav_row.addWidget(self.main_page.btn_next_to_step_2)

        layout.addLayout(nav_row)
