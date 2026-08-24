import contextlib
import os
import shutil

from config.paths import OUTPUTS_DIR, TMP_DIR
from gui.base_page import BasePage
from gui.common_widgets import DropZone
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.file_dialog_utils import pick_file, pick_save_file
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from utils.srt_utils import parse_srt_to_segments

from .utils import (
    _set_button_icon,
)
from .widgets import AudioPlayerWidget, ClipListItemWidget
from .workers import (
    AudioExtractWorker,
    CoverGeneratorWorker,
    FinalExportWorker,
    HotSpotAnalyzer,
    VideoClipWorker,
)


class LiveClipPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self._stop_requested = False
        self._workers = []  # 所有可停止的 worker 列表
        self.hotspots = []
        self.transcript_segments = []
        self.audio_path = ""
        self.clipped_results = []
        self.covers_info = []
        self.output_dir = ""
        self.video_path = ""
        self.srt_path = ""

        self.cover_images = {}
        self.cover_title_inputs = {}
        self.clip_item_widgets = []
        self.selected_clip_idx = -1

    def _get_step_font(self, active=False):
        font = QFont("Microsoft YaHei", 10)
        font.setBold(active)
        return font

    def _update_step_indicator(self, index):
        for i, lbl in enumerate(self.step_labels):
            if i == index:
                lbl.setFont(self._get_step_font(True))
                lbl.setProperty("status", "active")
            elif i < index:
                lbl.setFont(self._get_step_font(False))
                lbl.setProperty("status", "done")
            else:
                lbl.setFont(self._get_step_font(False))
                lbl.setProperty("status", "pending")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _go_to_step(self, index):
        self.pause_all_players_except(-1)
        if hasattr(self, "audio_player"):
            self.audio_player.player.pause()
            _set_button_icon(self.audio_player.btn_play, "play")

        if index == 0:
            self.progress_bar = self.progress_bar_p0
            self.stage_lbl = self.stage_lbl_p0
        else:
            self.progress_bar = self.progress_bar_p1
            self.stage_lbl = self.stage_lbl_p1
            # Update selected count label for Step 2
            selected_count = sum(1 for i in range(self.hotspot_table.rowCount())
                                 if self.hotspot_table.item(i, 0) and self.hotspot_table.item(i, 0).checkState() == Qt.Checked)  # noqa: E501
            self.clip_status_lbl.setText(f"已选 {selected_count} 个片段待切片")
            self.btn_clip.setEnabled(selected_count > 0)
            self._init_clip_list()

        self.stacked.setCurrentIndex(index)
        self._update_step_indicator(index)
        self.stage_lbl.setText("")
        self.progress_bar.setVisible(False)

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(14)

        heading = QLabel("\U0001F4E1 直播智能切片")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        # Step bar
        self.step_bar = QFrame()
        self.step_bar.setObjectName("step_bar")
        self.step_bar.setStyleSheet(
            "QFrame#step_bar { background-color: rgba(255,255,255,0.02); "
            "border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 16px; }")  # noqa: E501
        sl = QHBoxLayout(self.step_bar)
        self.step_labels = []
        for i, text in enumerate(["1. 视频分析与热点发现", "2. 切片与封面生成"]):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("export_step_label")
            lbl.setFont(self._get_step_font(i == 0))
            sl.addWidget(lbl)
            self.step_labels.append(lbl)
            layout.addWidget(self.step_bar, 0)

            # 初始化第一步为激活状态
            QTimer.singleShot(0, lambda: self._update_step_indicator(0))

        # Stacked widget
        self.stacked = QStackedWidget()
        layout.addWidget(self.stacked, 1)

        self._setup_page_analysis()
        self._setup_page_clip()

        # Set default references
        self.progress_bar = self.progress_bar_p0
        self.stage_lbl = self.stage_lbl_p0

    # ===== Page 0: Analysis =====
    def _setup_page_analysis(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setSpacing(10)
        cl.setContentsMargins(12, 10, 12, 10)

        # Row 1: Video selection with drag-and-drop
        self.video_path_input = DropZone(
            ("mp4", "mov", "avi", "mkv", "flv", "ts", "webm", "m4v"),
            hint="拖入直播录像 或 点击选择（支持 40GB+，流式处理）",
            min_height=60
        )
        self.video_path_input.clicked.connect(self._select_video)
        self.video_path_input.file_dropped.connect(self._on_video_dropped)
        cl.addWidget(self.video_path_input)

        self.video_info_lbl = QLabel("")
        self.video_info_lbl.setObjectName("video_info_label")
        cl.addWidget(self.video_info_lbl)

        # Row 2: Audio player for seek and playback
        pr = QHBoxLayout()
        pr.addWidget(QLabel("音频预览:"))
        self.audio_player = AudioPlayerWidget()
        pr.addWidget(self.audio_player, 1)
        cl.addLayout(pr)

        # Row 3: Analysis method, transcription engine and Start button in one line
        ar = QHBoxLayout()
        ar.addWidget(QLabel("分析方法:"))
        self.analysis_mode = QComboBox()
        self.analysis_mode.addItem(" AI 大模型 (DeepSeek/OpenAI)", "llm")
        self.analysis_mode.addItem(" 内置算法 (无需 API)", "rule")
        ar.addWidget(self.analysis_mode)

        # Transcribe Language Selection
        ar.addWidget(QLabel("转写语言:"))
        self.transcribe_lang = QComboBox()
        self.transcribe_lang.addItem("中文 (简体)", "zh")
        self.transcribe_lang.addItem("自动识别", "auto")
        self.transcribe_lang.addItem("英语", "en")
        self.transcribe_lang.setCurrentIndex(0)  # Default to Chinese
        ar.addWidget(self.transcribe_lang)

        self.chk_reextract = QCheckBox("强制重新提取音频")
        self.chk_reextract.setToolTip("勾选后每次重新用 ffmpeg 提取音频")
        ar.addWidget(self.chk_reextract)

        self.btn_analyze = mdi_button("开始提取并分析", "mic")
        self.btn_analyze.setObjectName("action_button")
        self.btn_analyze.setFixedHeight(30)
        self.btn_analyze.clicked.connect(self._start_analysis_pipeline)
        ar.addWidget(self.btn_analyze, 1)

        self.btn_stop = mdi_button("停止", "stop")
        self.btn_stop.setObjectName("secondary_button")
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_analysis)
        ar.addWidget(self.btn_stop)
        cl.addLayout(ar)

        layout.addWidget(card)

        # Lower section: Left (Subtitles) and Right (Hotspots) layout
        lower_layout = QHBoxLayout()
        lower_layout.setSpacing(12)

        # Left: Subtitle Preview
        sub_card = QFrame()
        sub_card.setObjectName("card")
        sub_vl = QVBoxLayout(sub_card)
        sub_vl.setSpacing(8)
        sub_vl.setContentsMargins(12, 10, 12, 10)
        sub_header = QHBoxLayout()
        sub_header.addWidget(QLabel("<b> 字幕预览</b>"))
        sub_header.addStretch()
        self.btn_export_sub = mdi_button("导出字幕", "save")
        self.btn_export_sub.setObjectName("secondary_button")
        self.btn_export_sub.setEnabled(False)
        self.btn_export_sub.clicked.connect(self._export_subtitles)
        sub_header.addWidget(self.btn_export_sub)
        sub_vl.addLayout(sub_header)

        self.transcript_preview = QTextEdit()
        self.transcript_preview.setReadOnly(True)
        self.transcript_preview.setObjectName("log_viewer")
        self.transcript_preview.setPlaceholderText("转写完成后在此预览字幕...")
        sub_vl.addWidget(self.transcript_preview)

        lower_layout.addWidget(sub_card, 1)

        # Right: Hotspot list
        list_card = QFrame()
        list_card.setObjectName("card")
        ll = QVBoxLayout(list_card)
        ll.setSpacing(8)
        ll.setContentsMargins(12, 10, 12, 10)

        lh = QHBoxLayout()
        lh.addWidget(QLabel("<b>\U0001F4CA 发现的热点片段</b>"))
        lh.addStretch()

        # Score filter dropdown
        lh.addWidget(QLabel("评分过滤:"))
        self.score_filter = QComboBox()
        self.score_filter.addItem("显示所有", 0.0)
        self.score_filter.addItem(">= 3.0", 3.0)
        self.score_filter.addItem(">= 5.0", 5.0)
        self.score_filter.addItem(">= 6.0", 6.0)
        self.score_filter.addItem(">= 7.0", 7.0)
        self.score_filter.addItem(">= 8.0", 8.0)
        self.score_filter.addItem(">= 9.0", 9.0)
        self.score_filter.setCurrentIndex(6)  # 默认设置为 >= 9.0
        self.score_filter.currentIndexChanged.connect(self._filter_hotspots)
        lh.addWidget(self.score_filter)

        self.selected_count_lbl = QLabel("已选: 0")
        self.selected_count_lbl.setObjectName("success_text")
        lh.addWidget(self.selected_count_lbl)

        sel_btns = QHBoxLayout()
        ba = QPushButton("全选")
        ba.setObjectName("secondary_button")
        ba.clicked.connect(self._select_all)  # noqa: E501
        bd = QPushButton("取消")
        bd.setObjectName("secondary_button")
        bd.clicked.connect(self._deselect_all)  # noqa: E501
        sel_btns.addWidget(ba)
        sel_btns.addWidget(bd)
        sel_btns.addStretch()
        lh.addLayout(sel_btns)
        ll.addLayout(lh)

        self.hotspot_table = QTableWidget(0, 5)
        self.hotspot_table.setHorizontalHeaderLabels(["选择", "时间段", "时长", "评分", "标题"])
        self.hotspot_table.verticalHeader().setVisible(False)
        self.hotspot_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hotspot_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hotspot_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)  # noqa: E501
        self.hotspot_table.setColumnWidth(0, 50)
        self.hotspot_table.setColumnWidth(1, 110)
        self.hotspot_table.setColumnWidth(2, 60)
        self.hotspot_table.setColumnWidth(3, 50)
        self.hotspot_table.cellClicked.connect(self._on_hotspot_clicked)
        self.hotspot_table.cellChanged.connect(lambda r, c: self._update_count() if c == 0 else None)  # noqa: E501
        ll.addWidget(self.hotspot_table)

        # Removed hotspot_detail text edit since it is no longer needed

        lower_layout.addWidget(list_card, 1)

        layout.addLayout(lower_layout, 1)

        # Bottom status, progress and navigation row for Page 0
        bot_layout = QHBoxLayout()

        self.stage_lbl_p0 = QLabel("就绪 - 请选择直播视频")
        self.stage_lbl_p0.setObjectName("muted_text")
        bot_layout.addWidget(self.stage_lbl_p0)

        self.progress_bar_p0 = QProgressBar()
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p0.setRange(0, 100)
        bot_layout.addWidget(self.progress_bar_p0, 1)

        self.btn_to_step2 = mdi_button("下一步：切片与封面", "right")
        self.btn_to_step2.setObjectName("primary_button")
        self.btn_to_step2.setEnabled(False)
        self.btn_to_step2.clicked.connect(lambda: self._go_to_step(1))
        bot_layout.addWidget(self.btn_to_step2)

        layout.addLayout(bot_layout)

        self.stacked.addWidget(page)

    # ===== Page 1: Clip & Cover =====
    def _setup_page_clip(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Unified Card for Step 2
        clip_list_card = QFrame()
        clip_list_card.setObjectName("card")
        ccl = QVBoxLayout(clip_list_card)
        ccl.setSpacing(12)
        ccl.setContentsMargins(16, 16, 16, 16)

        # Header controls row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        title_lbl = QLabel("<b>\u2702 自动切片与封面编辑</b>")
        title_lbl.setObjectName("clip_page_title")
        header_layout.addWidget(title_lbl)

        self.clip_status_lbl = QLabel("已选 0 个片段待切片")
        self.clip_status_lbl.setObjectName("clip_status_label")
        header_layout.addWidget(self.clip_status_lbl)

        self.btn_open_output = mdi_button("打开输出目录", "folder")
        self.btn_open_output.setObjectName("secondary_button")
        self.btn_open_output.setFixedHeight(30)
        self.btn_open_output.clicked.connect(self._open_output)
        self.btn_open_output.setEnabled(False)
        header_layout.addWidget(self.btn_open_output)

        ccl.addLayout(header_layout)

        # Scroll Area for the list of clips
        self.cover_scroll = QScrollArea()
        self.cover_scroll.setWidgetResizable(True)
        self.cover_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cover_scroll.setFrameShape(QScrollArea.NoFrame)
        self.cover_scroll.setStyleSheet("background-color: transparent;")

        self.cover_container = QWidget()
        self.cover_container.setStyleSheet("background-color: transparent;")
        self.clips_list_layout = QGridLayout(self.cover_container)
        self.clips_list_layout.setContentsMargins(0, 0, 0, 0)
        self.clips_list_layout.setSpacing(12)
        self.clips_list_layout.setAlignment(Qt.AlignTop)

        self.cover_scroll.setWidget(self.cover_container)
        ccl.addWidget(self.cover_scroll, 1)

        layout.addWidget(clip_list_card, 1)

        # Export card
        export_card = QFrame()
        export_card.setObjectName("card")
        evl = QVBoxLayout(export_card)
        evl.setSpacing(8)
        evl.addWidget(QLabel("<b>\U0001F4E4 最终导出</b>"))

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_clip = mdi_button("开始切片", "cut")
        self.btn_clip.setObjectName("action_button")
        self.btn_clip.setFixedHeight(40)
        self.btn_clip.clicked.connect(self._start_clip_pipeline)
        btn_layout.addWidget(self.btn_clip, 1)

        self.btn_export = mdi_button("确认封面并导出最终视频", "rocket")
        self.btn_export.setObjectName("action_button")
        self.btn_export.setFixedHeight(40)
        self.btn_export.clicked.connect(self._start_final_export)
        self.btn_export.setEnabled(False)
        btn_layout.addWidget(self.btn_export, 1)

        evl.addLayout(btn_layout)

        self.export_result_lbl = QLabel("")
        self.export_result_lbl.setWordWrap(True)
        self.export_result_lbl.setObjectName("export_result_label")
        evl.addWidget(self.export_result_lbl)

        layout.addWidget(export_card)

        # Progress & Status for Page 1
        self.stage_lbl_p1 = QLabel("")
        self.stage_lbl_p1.setObjectName("muted_text")
        layout.addWidget(self.stage_lbl_p1)

        self.progress_bar_p1 = QProgressBar()
        self.progress_bar_p1.setVisible(False)
        self.progress_bar_p1.setRange(0, 100)
        layout.addWidget(self.progress_bar_p1)

        # Nav
        nav = QHBoxLayout()
        nav.addWidget(mdi_button("上一步：视频分析", "left"))
        nav.itemAt(0).widget().setObjectName("secondary_button")
        nav.itemAt(0).widget().clicked.connect(lambda: self._go_to_step(0))
        nav.addStretch()
        layout.addLayout(nav)

        self.stacked.addWidget(page)

        # ===== Actions =====

    def _select_video(self):
        path, _ = pick_file(self.parent_widget, "选择直播视频", "",
                                              "Video (*.mp4 *.flv *.ts *.mov *.avi *.mkv);;All (*)")  # noqa: E501
        if path:
            self._set_video_path(path)

    def _on_video_dropped(self, paths):
        """处理拖放的文件。"""
        if paths and len(paths) > 0:
            self._set_video_path(paths[0])

    def _set_video_path(self, path):
        """设置视频路径并更新相关 UI。"""
        self.video_path = path
        gb = os.path.getsize(path) / (1024 ** 3)
        self.video_info_lbl.setText(f"\U0001F4E6 文件: {gb:.1f} GB  |  流式处理，内存安全")

        # Auto-check if audio was already extracted previously
        vname = os.path.splitext(os.path.basename(path))[0]
        self.audio_path = os.path.join(TMP_DIR, f"{vname}_audio.wav")
        if os.path.exists(self.audio_path) and os.path.getsize(self.audio_path) > 0:
            self.audio_player.set_audio_path(self.audio_path)
        else:
            self.audio_player.setEnabled(False)
            self.audio_player.lbl_time.setText("等待提取音频...")

    def _start_analysis_pipeline(self):
        self._stop_requested = False
        log.info("[LiveClip] _start_analysis_pipeline")
        video_path = self.video_path or ""
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "错误", "请先选择视频文件")
            return
        self.video_path = video_path
        self.btn_export_sub.setEnabled(False)

        os.makedirs(TMP_DIR, exist_ok=True)
        vname = os.path.splitext(os.path.basename(video_path))[0]
        self.audio_path = os.path.join(TMP_DIR, f"{vname}_audio.wav")
        self._audio_meta_path = os.path.join(TMP_DIR, f"{vname}_audio.meta")

        def _do_transcribe(audio_path):
            log.info(f"[LiveClip] _do_transcribe audio_path={audio_path}")
            out_dir = os.path.join(OUTPUTS_DIR, "transcription")
            os.makedirs(out_dir, exist_ok=True)
            vn = os.path.splitext(os.path.basename(self.video_path))[0]
            out = os.path.join(out_dir, f"{vn}.srt")
            self.srt_path = out
            self.stage_lbl.setText("正在上传音频到服务端...")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setVisible(True)
            lang_choice = self.transcribe_lang.currentData()
            language = None if lang_choice == "auto" else lang_choice
            from utils.asr_client import read_asr_url, transcribe_remote
            from utils.base_worker import BaseWorker
            class _RemoteWorker(BaseWorker):
                stage = Signal(str)
                progress = Signal(int)
                finished = Signal(str)
                error = Signal(str)
                def __init__(self, vp, op, lg):
                    super().__init__()
                    self.video_path = vp
                    self.output_path = op
                    self.language = lg
                def do_work(self):
                    if self.isInterruptionRequested():
                        return
                    try:
                        log.info(f"[_RemoteWorker] 开始 file={self.video_path}")
                        def _progress_cb(m: str) -> None:
                            self.stage.emit(m)
                            log.info(f"[_RemoteWorker] {m}")
                        segs = transcribe_remote(self.video_path, read_asr_url(),
                            language=self.language,
                            progress_cb=_progress_cb)
                        if self.isInterruptionRequested():
                            return
                        lines = []
                        for i, s in enumerate(segs):
                            t = s.get("text","").strip().replace("\n"," ")
                            lines.append(f"{i+1}")
                            lines.append(f"{int(s.get('start',0)//3600):02d}:{int(s.get('start',0)%3600//60):02d}:{s.get('start',0)%60:06.3f} --> {int(s.get('end',0)//3600):02d}:{int(s.get('end',0)%3600//60):02d}:{s.get('end',0)%60:06.3f}")  # noqa: E501
                            lines.append(t)
                            lines.append("")
                        with open(self.output_path, "w", encoding="utf-8") as fp:
                            fp.write("\n".join(lines))
                        self.stage.emit("转写完成")
                        self.finished.emit(self.output_path)
                    except Exception as e:  # remote ASR API
                        self.error.emit(str(e))
            self._tw = _RemoteWorker(audio_path, out, language)
            self._workers.append(self._tw)
            self.audio_player.set_audio_path(audio_path)
            self._tw.stage.connect(self.stage_lbl.setText)
            self._tw.finished.connect(self._do_analyze)
            self._tw.error.connect(self._on_err)
            self._tw.start()

        # 音频缓存：存在且未勾选"重新提取"且视频源未变更则跳过
        reextract = getattr(self, "chk_reextract", None) and self.chk_reextract.isChecked()  # noqa: E501
        cache_valid = False
        if os.path.exists(self.audio_path) and os.path.getsize(self.audio_path) > 0 and not reextract:  # noqa: E501
            # 校验缓存对应的视频源是否一致（mtime + size）
            try:
                vstat = os.stat(video_path)
                cur_meta = f"{vstat.st_mtime_ns}_{vstat.st_size}_{video_path}"
                if os.path.exists(self._audio_meta_path):
                    with open(self._audio_meta_path, encoding="utf-8") as mf:
                        saved_meta = mf.read().strip()
                    cache_valid = (saved_meta == cur_meta)
                if not cache_valid:
                    log.info("[LiveClip] 视频源已变更，缓存音频失效，重新提取")
            except OSError:
                cache_valid = False
        if cache_valid:
            log.info(f"[LiveClip] 使用缓存音频: {self.audio_path}")
            self.btn_analyze.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_to_step2.setEnabled(False)
            self.stage_lbl.setText("使用已提取的音频...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.audio_player.set_audio_path(self.audio_path)
            _do_transcribe(self.audio_path)
            return

        # 勾选了重新提取或首次运行，删除旧文件
        if os.path.exists(self.audio_path):
            with contextlib.suppress(OSError):
                os.remove(self.audio_path)

        self.btn_analyze.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_to_step2.setEnabled(False)
        self.stage_lbl.setText("正在读取视频并转换为声音文件...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        log.info(f"[LiveClip] 创建 AudioExtractWorker, video={video_path}")
        self._audio_worker = AudioExtractWorker(video_path, self.audio_path)
        self._workers.append(self._audio_worker)
        self._audio_worker.stage.connect(self.stage_lbl.setText)
        self._audio_worker.progress.connect(self.progress_bar.setValue)

        def _on_audio_extracted(p):
            # 提取完成后保存视频源元数据，供下次缓存校验
            try:
                vstat = os.stat(video_path)
                meta = f"{vstat.st_mtime_ns}_{vstat.st_size}_{video_path}"
                with open(self._audio_meta_path, "w", encoding="utf-8") as mf:
                    mf.write(meta)
            except OSError:
                pass
            _do_transcribe(p)

        self._audio_worker.finished.connect(_on_audio_extracted)
        self._audio_worker.error.connect(self._on_err)
        self._audio_worker.start()

    def _stop_analysis(self):
        log.info("[LiveClip] _stop_analysis 用户请求停止")
        self._stop_requested = True
        # 杀死所有 worker
        for w in list(self._workers):
            if hasattr(w, "kill_ffmpeg"):
                w.kill_ffmpeg()
            if w and w.isRunning():
                w.requestInterruption()
                w.terminate()
                w.wait(2000)
        self._workers.clear()
        self._reset_ui()
        self.stage_lbl.setText("已停止")
        log.info("[LiveClip] _stop_analysis 完成")

    def _do_analyze(self, srt_path):
        """转写完成后的分析入口。srt_path 是 SRT 文件路径。"""
        try:
            with open(srt_path, encoding="utf-8") as f:
                srt_content = f.read()
        except OSError:
            log.error(f"[LiveClip] 读取 SRT 失败: {srt_path}")
            QMessageBox.warning(self.parent_widget, "错误", "读取字幕文件失败")
            self._reset_ui()
            return
        self.transcript_segments = parse_srt_to_segments(srt_content)
        self._update_transcript_preview_html()
        self.btn_export_sub.setEnabled(True)

        if not self.transcript_segments:
            QMessageBox.warning(self.parent_widget, "提示", "未识别到语音内容")
            self._reset_ui()
            return

        mode = self.analysis_mode.currentData()
        use_llm = (mode == "llm")
        llm_model = ""
        if use_llm:
            cfg = getattr(self.main_window, "ai_config", {})
            llm_model = cfg.get("llm_model", "deepseek-chat")
            if not llm_model:
                QMessageBox.warning(self.parent_widget, "未配置LLM",
                                    "请在 'AI 设置' 中配置大模型。\n将使用内置算法。")
                use_llm = False

        if use_llm:
            self.stage_lbl.setText("正在使用大模型分析热点...")
        else:
            self.stage_lbl.setText("正在使用内置算法分析热点...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._analyzer = HotSpotAnalyzer(self.transcript_segments,
                                         use_llm=use_llm, llm_model=llm_model)
        self._workers.append(self._analyzer)
        self._analyzer.stage.connect(self.stage_lbl.setText)
        self._analyzer.progress.connect(self.progress_bar.setValue)
        self._analyzer.finished.connect(self._on_analysis)
        self._analyzer.error.connect(self._on_err)
        self._analyzer.start()

    def _on_analysis(self, hotspots):
        self.hotspots = hotspots
        self.btn_analyze.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.stage_lbl.setText(f"发现 {len(hotspots)} 个热点片段")

        self.hotspot_table.setRowCount(len(hotspots))
        for i, hs in enumerate(hotspots):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)  # noqa: E501
            chk.setCheckState(Qt.Checked)
            self.hotspot_table.setItem(i, 0, chk)
            self.hotspot_table.setItem(i, 1, QTableWidgetItem(f"{hs['start_str']} - {hs['end_str']}"))  # noqa: E501
            d = hs["duration"]
            ds = f"{d // 60}m{d % 60}s" if d >= 60 else f"{d}s"
            self.hotspot_table.setItem(i, 2, QTableWidgetItem(ds))
            si = QTableWidgetItem(str(hs["score"]))
            if hs["score"] >= 7:
                si.setForeground(Qt.green)
            elif hs["score"] >= 5:
                si.setForeground(Qt.yellow)
            self.hotspot_table.setItem(i, 3, si)
            self.hotspot_table.setItem(i, 4, QTableWidgetItem(hs["title"]))

        self.btn_to_step2.setEnabled(len(hotspots) > 0)
        self._filter_hotspots()

    def _on_hotspot_clicked(self, r, c):
        if r < len(self.hotspots):
            hs = self.hotspots[r]

            # Scroll left transcript preview to the start of the hotspot
            hs_start = hs["start"]
            best_idx = 1
            min_diff = 999999.0
            for idx, seg in enumerate(self.transcript_segments, 1):
                diff = abs(seg.start - hs_start)
                if diff < min_diff:
                    min_diff = diff
                    best_idx = idx

            self.transcript_preview.scrollToAnchor(f"seg_{best_idx}")

    def _update_count(self):
        c = sum(1 for i in range(self.hotspot_table.rowCount())
                if self.hotspot_table.item(i, 0) and self.hotspot_table.item(i, 0).checkState() == Qt.Checked)  # noqa: E501
        self.selected_count_lbl.setText(f"已选: {c}")

    def _select_all(self):
        for i in range(self.hotspot_table.rowCount()):
            if not self.hotspot_table.isRowHidden(i) and self.hotspot_table.item(i, 0):
                self.hotspot_table.item(i, 0).setCheckState(Qt.Checked)
        self._update_count()

    def _deselect_all(self):
        for i in range(self.hotspot_table.rowCount()):
            if not self.hotspot_table.isRowHidden(i) and self.hotspot_table.item(i, 0):
                self.hotspot_table.item(i, 0).setCheckState(Qt.Unchecked)
        self._update_count()

    def _filter_hotspots(self):
        min_score = self.score_filter.currentData() if hasattr(self, 'score_filter') else 0.0  # noqa: E501
        for i in range(self.hotspot_table.rowCount()):
            if i < len(self.hotspots):
                score = self.hotspots[i]["score"]
                should_hide = score < min_score
                self.hotspot_table.setRowHidden(i, should_hide)

                # Automatically synchronize check state with visibility
                if self.hotspot_table.item(i, 0):
                    if should_hide:
                        self.hotspot_table.item(i, 0).setCheckState(Qt.Unchecked)
                    else:
                        self.hotspot_table.item(i, 0).setCheckState(Qt.Checked)
        self._update_count()
        self._update_transcript_preview_html()

    def _format_timestamp(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms == 1000:
            ms = 0
            s += 1
            if s == 60:
                s = 0
                m += 1
                if m == 60:
                    m = 0
                    h += 1
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _update_transcript_preview_html(self):
        if not self.transcript_segments:
            return

        min_score = self.score_filter.currentData() if hasattr(self, 'score_filter') else 0.0  # noqa: E501

        html_lines = [
            "<html><head><style>"
            "p { margin: 0px 0px 10px 0px; line-height: 1.4; font-size: 13px; color: #e2e8f0; }"  # noqa: E501
            "span.timestamp { color: #94a3b8; font-family: monospace; font-size: 11px; }"  # noqa: E501
            "</style></head><body style='background-color: #18181b; margin: 10px;'>"
        ]

        for idx, seg in enumerate(self.transcript_segments, 1):
            # Check if this segment overlaps with any active hotspot (score >= min_score)  # noqa: E501
            best_score = -1
            for hs in self.hotspots:
                if hs["score"] >= min_score and seg.start < hs["end"] and seg.end > hs["start"]:  # noqa: SIM102
                    if hs["score"] > best_score:
                        best_score = hs["score"]

            # Determine background color based on score
            bg_style = ""
            if best_score >= 10.0:
                bg_style = "background-color: rgba(153, 27, 27, 0.45); padding: 2px 4px; border-radius: 3px;" # Deep red (10分)  # noqa: E501
            elif best_score >= 9.0:
                bg_style = "background-color: rgba(234, 88, 12, 0.4); padding: 2px 4px; border-radius: 3px;" # Orange red (9分)  # noqa: E501
            elif best_score >= 8.0:
                bg_style = "background-color: rgba(217, 119, 6, 0.35); padding: 2px 4px; border-radius: 3px;" # Orange yellow (8分)  # noqa: E501
            elif best_score >= 6.0:
                bg_style = "background-color: rgba(46, 204, 113, 0.25); padding: 2px 4px; border-radius: 3px;" # Soft green  # noqa: E501
            elif best_score >= 3.0:
                bg_style = "background-color: rgba(52, 152, 219, 0.25); padding: 2px 4px; border-radius: 3px;" # Soft blue  # noqa: E501

            start_str = self._format_timestamp(seg.start)
            end_str = self._format_timestamp(seg.end)

            anchor_html = f"<a name='seg_{idx}'></a>"

            text_html = f"<span style='{bg_style}'>{seg.text}</span>" if bg_style else f"<span>{seg.text}</span>"

            html_lines.append(
                f"<p>{anchor_html}<b>{idx}</b><br>"
                f"<span class='timestamp'>{start_str} --> {end_str}</span><br>"
                f"{text_html}</p>"
            )

        html_lines.append("</body></html>")
        self.transcript_preview.setHtml("".join(html_lines))

    def _export_subtitles(self):
        if not getattr(self, "srt_path", "") or not os.path.exists(self.srt_path):
            QMessageBox.warning(self.parent_widget, "提示", "未找到生成的字幕文件。")
            return

        vname = os.path.splitext(os.path.basename(self.video_path))[0] if getattr(self, "video_path", "") else "transcript"  # noqa: E501
        default_dir = os.path.dirname(os.path.abspath(self.video_path)) if getattr(self, "video_path", "") and os.path.exists(self.video_path) else ""  # noqa: E501
        default_path = os.path.join(default_dir, f"{vname}.srt")

        path, _ = pick_save_file(
            self.parent_widget,
            "保存字幕文件",
            default_path,
            "SRT Subtitle Files (*.srt);;All Files (*)"
        )
        if path:
            try:
                shutil.copy(self.srt_path, path)
                QMessageBox.information(self.parent_widget, "导出成功", f"字幕文件已成功保存到：\n{path}")  # noqa: E501
            except OSError as e:
                QMessageBox.critical(self.parent_widget, "导出失败", f"无法保存文件：\n{e}")

    def _start_clip_pipeline(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self.parent_widget, "错误", f"视频文件不存在，请重新选择视频文件。\n路径: {self.video_path or '未选择'}")  # noqa: E501
            return

        selected = []
        for widget in getattr(self, "clip_item_widgets", []):
            clip_data = dict(widget.clip_info)
            clip_data["burn_subtitles"] = widget.chk_subtitles.isChecked()
            clip_data["index"] = widget.clip_index
            selected.append(clip_data)

        if not selected:
            QMessageBox.warning(self.parent_widget, "未选择", "当前没有可切片的片段")
            return

        vname = os.path.splitext(os.path.basename(self.video_path))[0]
        self.output_dir = os.path.join(OUTPUTS_DIR, "live_clips", vname)
        os.makedirs(self.output_dir, exist_ok=True)

        self.btn_clip.setEnabled(False)
        for widget in getattr(self, "clip_item_widgets", []):
            widget.btn_slice_single.setEnabled(False)
            widget.btn_slice_single.setText("批量切片中")
        self.clip_status_lbl.setText(f"正在切片 {len(selected)} 个片段...")
        self.stage_lbl.setText("切片中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        self._clip_worker = VideoClipWorker(
            self.video_path, selected, self.output_dir,
            srt_path=getattr(self, "srt_path", "")
        )
        self._clip_worker.stage.connect(self.stage_lbl.setText)
        self._clip_worker.progress.connect(self.progress_bar.setValue)
        self._clip_worker.finished.connect(self._on_clip_done)
        self._clip_worker.error.connect(self._on_err)
        self._clip_worker.start()

    def _on_clip_done(self, results):
        self.clipped_results = results
        self.clip_status_lbl.setText(f"\u2705 切片完成：{len(results)} 个视频")
        self.stage_lbl.setText("正在生成封面...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._cover_worker = CoverGeneratorWorker(results, self.output_dir)
        self._cover_worker.stage.connect(self.stage_lbl.setText)
        self._cover_worker.progress.connect(self.progress_bar.setValue)
        self._cover_worker.cover_ready.connect(self._on_cover_ready)
        self._cover_worker.finished.connect(self._on_covers_done)
        self._cover_worker.error.connect(self._on_err)
        self._cover_worker.start()

    def _init_clip_list(self):
        while self.clips_list_layout.count():
            item = self.clips_list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self.clip_item_widgets = []
        self.selected_clip_idx = -1

        selected_hotspots = []
        for i in range(self.hotspot_table.rowCount()):
            it = self.hotspot_table.item(i, 0)
            if it and it.checkState() == Qt.Checked and i < len(self.hotspots):
                hs_copy = dict(self.hotspots[i])
                selected_hotspots.append(hs_copy)

        for idx, hs in enumerate(selected_hotspots):
            widget = ClipListItemWidget(hs, idx, self)
            row = idx // 3
            col = idx % 3
            self.clips_list_layout.addWidget(widget, row, col)
            self.clip_item_widgets.append(widget)

    def select_clip_item(self, index):
        if index < 0 or index >= len(self.clip_item_widgets):
            return

        self.selected_clip_idx = index
        for i, widget in enumerate(self.clip_item_widgets):
            widget.set_selected(i == index)

    def on_clip_info_updated(self, index, new_title, cover_path, cover_vertical_path=None):  # noqa: E501
        for ci in self.covers_info:
            if ci["index"] == index:
                ci["title"] = new_title
                ci["cover_path"] = cover_path
                if cover_vertical_path:
                    ci["cover_vertical_path"] = cover_vertical_path
                break

    def pause_all_players_except(self, active_index):
        for widget in getattr(self, "clip_item_widgets", []):
            if widget.clip_index != active_index:
                widget.pause_audio()

    def update_covers_info_for_index(self, index, ci_data):
        if not hasattr(self, "covers_info") or self.covers_info is None:
            self.covers_info = []

        found = False
        for i, item in enumerate(self.covers_info):
            if item["index"] == index:
                self.covers_info[i] = ci_data
                found = True
                break
        if not found:
            self.covers_info.append(ci_data)

        self.btn_export.setEnabled(len(self.covers_info) > 0)

    def _on_cover_ready(self, idx, cover_path):
        self.cover_images[idx] = cover_path
        if idx < len(self.clip_item_widgets):
            self.clip_item_widgets[idx].clip_info["cover_path"] = cover_path

    def _on_covers_done(self, covers_info):
        self.covers_info = covers_info
        self.btn_clip.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.stage_lbl.setText(f"完成： 封面生成完成：{len(covers_info)} 个")

        for ci in covers_info:
            idx = ci["index"]
            if idx < len(self.clip_item_widgets):
                self.clip_item_widgets[idx].clip_info["cover_path"] = ci["cover_path"]
                self.clip_item_widgets[idx].clip_info["cover_vertical_path"] = ci.get("cover_vertical_path", "")  # noqa: E501
                self.clip_item_widgets[idx].clip_info["frame_path"] = ci["frame_path"]
                self.clip_item_widgets[idx].clip_info["video_path"] = ci["video_path"]
                self.clip_item_widgets[idx].clip_info["title"] = ci["title"]
                self.clip_item_widgets[idx].enable_playback(ci["video_path"])

        if self.clip_item_widgets:
            self.select_clip_item(0)

    def _start_final_export(self):
        if not self.clip_item_widgets or not self.covers_info:
            return

        for widget in self.clip_item_widgets:
            idx = widget.clip_index
            new_title = widget.clip_info["title"].strip()
            for ci in self.covers_info:
                if ci["index"] == idx:
                    ci["title"] = new_title
        self.btn_export.setEnabled(False)
        self.stage_lbl.setText("导出最终视频（嵌入封面首帧）...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        self._export_worker = FinalExportWorker(self.covers_info, self.output_dir)
        self._export_worker.stage.connect(self.stage_lbl.setText)
        self._export_worker.progress.connect(self.progress_bar.setValue)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.error.connect(self._on_err)
        self._export_worker.start()

    def _on_export_done(self, paths):
        self.btn_export.setEnabled(True)
        self.btn_open_output.setEnabled(True)
        self.progress_bar.setVisible(False)
        final_dir = os.path.join(self.output_dir, "final")
        self.export_result_lbl.setText(f"\u2705 导出完成！{len(paths)} 个视频已保存到:\n{final_dir}")  # noqa: E501
        self.stage_lbl.setText(f"导出完成，共 {len(paths)} 个视频")
        QMessageBox.information(self.parent_widget, "导出完成",
                                f"成功导出 {len(paths)} 个带封面的视频！\n\n{final_dir}")

    def _on_err(self, err):
        self.btn_analyze.setEnabled(True)
        self.btn_clip.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p1.setVisible(False)
        self.stage_lbl.setText("操作失败")

        for widget in getattr(self, "clip_item_widgets", []):
            if not widget.clip_info.get("video_path"):
                widget.btn_slice_single.setEnabled(True)
                widget.btn_slice_single.setText("单独切片")

        s = ""
        for line in (err or "").splitlines()[::-1]:
            if line.strip():
                s = line.strip()
                break
        QMessageBox.critical(self.parent_widget, "错误", f"操作失败:\n{s or err[:500]}")

    def _reset_ui(self):
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_to_step2.setEnabled(False)
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p1.setVisible(False)
        self.btn_export_sub.setEnabled(False)

    def _open_output(self):
        if not self.output_dir:
            log.warning("[直播切片] 输出目录未设置，无法打开")
            QMessageBox.information(self.parent_widget, "提示", "输出目录未设置，请先完成导出。")
            return

        d = os.path.join(self.output_dir, "final")
        if os.path.exists(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
            log.info("[直播切片] 打开输出目录(final): %s", d)
        elif os.path.exists(self.output_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))
            log.info("[直播切片] 打开输出目录: %s", self.output_dir)
        else:
            log.warning("[直播切片] 输出目录不存在: %s", self.output_dir)
            QMessageBox.warning(
                self.parent_widget, "提示",
                f"输出目录不存在：\n{self.output_dir}\n\n请先完成导出操作。",
            )
