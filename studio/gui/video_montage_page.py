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
import contextlib
import json
import os
import random
import shutil
import subprocess
import time
from typing import Any

from gui.base_page import BasePage
from gui.error_dialog import show_error_dialog
from gui.montage.dialogs import (
    ClipSelectionDialog,
    DubbedVideosDialog,
    ProductCopyInputDialog,
    ScriptCompareDialog,
    TextEditDialog,
    VoiceRowDetailWidget,
)

# 导入 utils_media 会触发 subprocess.Popen 无黑框 monkey-patch（Windows），必须在任何
# subprocess 调用前完成；下面的 Worker/页面 import 链都会用到 subprocess。
from gui.montage.utils_media import (
    MAX_SOURCE_VIDEOS,
    SHOT_TYPE_COLORS,
    SHOT_TYPE_LABELS,
    VIDEO_EXTS,
    apply_shot_layout_order,
    classify_shot_type,
    collect_video_files,
    compute_clip_hash,
    compute_clip_quality,
    find_ffmpeg,
    format_seconds_to_srt_timestamp,
    get_media_duration,
    parse_srt,
    parse_srt_to_descriptions,
    safe_source_name,
)
from gui.montage.widgets import DoubleClickLineEdit, ReorderableClipsTable
from gui.montage.workers.concat_workers import FinalMixWorker, VideoConcatWorker, VideoDubbingWorker
from gui.montage.workers.desc_workers import BatchGenerateDescriptionsWorker, LocalVisionDescWorker
from gui.montage.workers.montage_concat_server_worker import MontageConcatServerWorker
from gui.montage.workers.script_workers import (
    BatchAITextRewriteWorker,
    GenScriptWorker,
    PunctuationSRTLLMWorker,
    SceneCopyWorker,
    ScriptMatchLLMWorker,
)
from gui.montage.workers.split_workers import BestClipWorker
from gui.montage.workers.voice_workers import VoiceCloneWorker
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils import scheduled_task_client as stc
from utils.base_worker import BaseWorker
from utils.ffmpeg_utils import CREATE_NO_WINDOW, run
from utils.file_dialog_utils import pick_directory, pick_file, pick_files, pick_save_file
from utils.gui_icons import mdi_button, mdi_icon
from utils.logger_utils import log
from utils.montage_cache import (
    clear_montage_cache,
    job_root,
    job_splits_dir,
    load_manifest,
    new_job_id,
    save_manifest,
)
from utils.os_utils import kill_process_tree


class VideoMontagePage(BasePage):
    # 是否把镜头合成提交到服务端 montage_concat 执行器。
    # 服务端部署完成后设为 True；未部署前保持 False，走本地 VideoConcatWorker。
    USE_SERVER_CONCAT = True  # 默认启用服务端合成
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
        # 混剪任务级缓存（方案二）：job_id 索引 + manifest 素材清单
        self._montage_job_id = ""
        self._montage_manifest = None
        self._last_merged_splits_dirs = []
        self.external_clip_urls = []
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
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self._bgm_player = QMediaPlayer()
        self._bgm_audio_output = QAudioOutput()
        self._bgm_player.setAudioOutput(self._bgm_audio_output)

        # Preview Player dedicated setup（双播放器缓冲：切换正在播放的片段时不阻塞主线程）
        self.preview_player = QMediaPlayer()
        self.preview_audio_output = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_audio_output)
        # 备用播放器：新片段先加载进备用播放器，就绪后把视频输出瞬间切过去，
        # 再在后台销毁旧会话，避免 Windows Media Foundation 的 setSource/stop
        # 在 GUI 主线程同步拆除活跃会话导致「播放中切换卡死」。
        self._preview_standby_player = QMediaPlayer()
        self._preview_standby_audio = QAudioOutput()
        self._preview_standby_audio.setMuted(True)
        self._preview_standby_player.setAudioOutput(self._preview_standby_audio)
        self._preview_video_widget = None
        self._preview_pending_clip = ""  # 备用播放器预加载中、待换出的目标片段
        for _pv in (self.preview_player, self._preview_standby_player):
            _pv.positionChanged.connect(lambda pos, _o=_pv: self._route_preview_position(pos, _o))
            _pv.durationChanged.connect(lambda dur, _o=_pv: self._route_preview_duration(dur, _o))
            _pv.mediaStatusChanged.connect(lambda st, _o=_pv: self._route_preview_status(st, _o))

        # Final Preview Player dedicated setup
        self.final_preview_player = QMediaPlayer()
        self.final_preview_audio = QAudioOutput()
        self.final_preview_player.setAudioOutput(self.final_preview_audio)

        # Split clips metadata cache
        self.split_clips_cache = {}
        # 镜头→景别缓存（按源视频命名识别，见 _shot_type_for_clip）
        self._clip_shot_type_cache = {}
        # 源视频「目录名→景别」映射（随 video_list 变更失效，见 _source_shot_type_map）
        self._source_shot_type_cache = None

        # Step 2 precompose state
        self.precompose_plans = []
        self.current_precompose_index = -1
        self._confirming_plan_index = None
        self._confirm_queue = []
        self._preview_sequence_clips = []
        self._preview_sequence_idx = 0
        self._preview_auto_advance = True  # 序列预览：默认自动连播（各片段合计约 30s）；切换方案卡顿另因 _clip_duration_text 重复 ffprobe，已修复回写缓存  # noqa: E501

        # Conditionally initialized attributes (for mypy type inference)
        self._pending_play_clip: str = ""
        self._play_request_id: int = 0  # 预览播放请求代号（用于丢弃过期的延迟回调）
        self._last_preview_load_clip: str = ""  # 上一次尝试加载的片段（防同一文件反复重试）
        self._preview_load_retry: int = 0
        self._releasing_preview: bool = False  # 预览会话释放中标志（屏蔽信号重入换源，防 WMF 拆会话死锁）
        self._pending_final_preview_timer: Any = None
        self._pending_final_preview_path: str = ""
        self._media_player: Any = None
        self._audio_output: Any = None
        self.row_edits: dict = {}
        self.original_texts: dict = {}
        self.highlight_worker: Any = None
        self._plan_worker: Any = None
        self.batch_rewrite_worker: Any = None
        # 服务端字体库（GET /config/fonts）：下拉框 itemData 只存 font_id，完整 dict 另建映射
        self._server_fonts: list = []
        self._server_fonts_by_id: dict = {}
        self._fonts_worker: Any = None
        self._fonts_loaded: bool = False
    # [1·初始化]  setup
    def setup(self):
        # Main layout
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(12)

        # Title
        heading = QLabel(" 智能混剪与批量视频制作")
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
                arrow = QLabel("")
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
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")  # noqa: E501
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
        self.sources_detail_widget.setColumnCount(6)
        self.sources_detail_widget.setHorizontalHeaderLabels(["⠿", "分割文件名", "时长", "景别", "描述文案", "评分"])  # noqa: E501
        self.sources_detail_widget.setMinimumHeight(260)
        self.sources_detail_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sources_detail_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sources_detail_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sources_detail_widget.customContextMenuRequested.connect(self._on_source_context_menu)  # noqa: E501
        self.sources_detail_widget.order_changed.connect(self._on_source_order_changed)

        header = self.sources_detail_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.sources_detail_widget.setColumnWidth(2, 60)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.sources_detail_widget.setColumnWidth(3, 60)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.sources_detail_widget.setColumnWidth(5, 50)

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

        self.stage_label = QLabel("")
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
            # 离开预览场景：停播并释放会话（顺便放开片段文件句柄）
            self._release_preview_sessions("切步骤")
            # 作废待加载片段的延迟回调（防止页面离开后 singleShot 仍触发播旧片段）
            self._play_request_id = getattr(self, "_play_request_id", 0) + 1
            self._pending_play_clip = ""
            self._preview_pending_clip = ""
        if hasattr(self, "final_preview_player") and self.final_preview_player:
            self.final_preview_player.stop()
        if hasattr(self, "_media_player") and self._media_player:
            self._media_player.stop()
            from utils.wav_player import stop_wav
            stop_wav()

        self.stacked_widget.setCurrentIndex(index)
        self.update_step_indicator(index)
        self.stage_label.setText("")
        self.progress_bar.setVisible(False)

        if index == 2:
            self._on_enter_step_3()
        elif index == 3:
            # 第④步：显示待混音合成的视频数量（不再依赖 legacy mix_video_table）
            try:
                n = len(self._collect_mix_candidates())
                if n > 0:
                    self.stage_label.setText(f"准备就绪：待混音合成 {n} 个视频，点击「开始混音合成」")
                else:
                    self.stage_label.setText("暂无待合成视频，请先完成「口播配音」")
            except (KeyError, TypeError, AttributeError):
                pass
    # [2·基础设施]  _cleanup_stale_montage_outputs
    def _cleanup_stale_montage_outputs(self, confirmed_paths):
        """进入第③步前，清理 outputs 目录里不属于本次确认列表的旧 montage_concat_* 产物。

        避免历次合成的旧视频累积进来（否则第③步配音列表会把历史视频全扫进来）。
        安全边界：只删 montage_concat_ 前缀的文件（混剪专属命名），保留本次确认列表
        里的视频及其附属文件（.txt / _sources.txt / .meta.json）。
        """
        if not confirmed_paths:
            return
        try:
            out_dir = os.path.dirname(os.path.abspath(confirmed_paths[0]))
        except (TypeError, ValueError):
            return
        if not out_dir or not os.path.isdir(out_dir):
            return
        # 本次确认列表的视频 stem 集合（去掉扩展名），用于保留附属文件
        keep_stems = set()
        for p in confirmed_paths:
            mp4_stem = os.path.splitext(os.path.abspath(p))[0]
            keep_stems.add(mp4_stem)
            # 附属文件 stem（_sources.txt → 多 _sources；.meta.json → 多 .meta）
            keep_stems.add(mp4_stem + "_sources")
            keep_stems.add(mp4_stem + ".meta")
        try:
            for f in os.listdir(out_dir):
                if not f.startswith("montage_concat_"):
                    continue  # 只动混剪专属命名，不碰用户其它视频
                full = os.path.abspath(os.path.join(out_dir, f))
                stem = os.path.splitext(full)[0]  # 去掉最后一个扩展名
                if stem in keep_stems:
                    continue  # 属于本次确认列表，保留
                try:
                    os.remove(full)
                    log.info(f"[清理旧产物] 删除 {f}")
                except OSError as e:
                    log.warning(f"[清理旧产物] 删除失败 {f}: {e}")
        except OSError as e:
            log.warning(f"清理旧混剪产物失败: {e}")

    # [2·基础设施]  _on_enter_step_3
    def _on_enter_step_3(self):
        dir_path = ""
        confirmed_paths = self._collect_assembled_paths() if hasattr(self, "_collect_assembled_paths") else []  # noqa: E501
        if confirmed_paths:
            dir_path = os.path.dirname(confirmed_paths[0])
            # 清理 outputs 里不属于本次确认列表的旧 montage_concat_* 产物，
            # 避免第③步配音列表把历次合成的旧视频全扫进来（34个变9个的根因）。
            self._cleanup_stale_montage_outputs(confirmed_paths)

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
        except (AttributeError, TypeError):
            ai_config = {}
        saved_url = ai_config.get("vox_api_url", "")
        if saved_url:
            self.api_url_input.setText(saved_url)
        self._populate_ref_audio_samples()
        # 字幕字体列表来自服务端，进 Step3 预拉一次（后台线程，不阻塞 UI）
        if not getattr(self, "_fonts_loaded", False):
            self._refresh_server_fonts()

    # ==================== PAGE 0: SMART SPLIT ====================
    # ==================== PAGE 1: CLIP ASSEMBLY ====================
    # ==================== PAGE 3: FINAL MIX ====================
    # ==================== STEP HELPER ACTIONS ====================
    # [9·其他]  _decorate_video_item_widget
    def _decorate_video_item_widget(self, item):
        path = item.text().strip()
        if not path:
            return
        # 按文件夹/文件名识别景别（入场/出场/中景/特写）：颜色+悬停双重可见；
        # 未按命名规范归档的素材不标注（保持默认色），编排时当中间镜头处理。
        st = classify_shot_type(path)
        if st:
            item.setToolTip(f"{path}\n景别：{SHOT_TYPE_LABELS[st]}")
            item.setForeground(QBrush(QColor(SHOT_TYPE_COLORS[st])))
    # [9·其他]  _show_video_context_menu
    def _show_video_context_menu(self, pos):
        item = self.video_list.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        act = QAction(" 从素材列表移除", menu)
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
        self._invalidate_shot_type_caches()
        # 终止正在运行的分割/挑精华 worker，避免后台残留导致后续操作被静默拦截
        self._kill_running_workers()
        self._refresh_source_root_hint()
        # 移除素材后重建 manifest 的 local/server 条目（派生片段保留）
        self._ensure_montage_job()
        self._check_split_clips_exist()
    # [2·基础设施]  _kill_running_workers
    def _kill_running_workers(self):
        """终止所有可能正在后台运行的 worker（镜头分割 / 批量分割 / 挑精华）。"""
        ctrl = getattr(getattr(self, "step1", None), "controller", None)
        workers = []
        if ctrl:
            workers.extend([getattr(ctrl, "worker", None), getattr(ctrl, "highlight_worker", None)])  # noqa: E501
        for w in workers:
            if w and w.isRunning():
                if not kill_process_tree(w.pid):
                    with contextlib.suppress(OSError, RuntimeError):
                        w.terminate()
                with contextlib.suppress(OSError, RuntimeError):
                    w.wait(3000)
                if ctrl is not None:
                    ctrl._retire_worker(w)
                if ctrl is not None and w is getattr(ctrl, "worker", None):
                    ctrl.worker = None
                elif ctrl is not None and w is getattr(ctrl, "highlight_worker", None):
                    ctrl.highlight_worker = None
        # 恢复按钮状态
        ctrl = getattr(getattr(self, "step1", None), "controller", None)
        if ctrl:
            ctrl._set_split_buttons_enabled(True)
        else:
            for btn_attr in ("btn_split", "btn_pick_highlights", "btn_transcribe_raw"):
                btn = getattr(self, btn_attr, None)
                if btn:
                    btn.setEnabled(True)
        self.progress_bar.setVisible(False)
    # [2·基础设施]  _refresh_source_root_hint
    def _refresh_source_root_hint(self):
        paths = []
        for i in range(self.video_list.count()):
            if self._is_local_file_item(self.video_list.item(i)):
                paths.append(self.video_list.item(i).text().strip())
        if not paths:
            self.folder_path_input.clear()
            return
        try:
            common_dir = os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in paths])  # noqa: E501
        except (ValueError, TypeError):
            common_dir = os.path.dirname(os.path.abspath(paths[0]))
        self.folder_path_input.setText(common_dir)
    # [2·基础设施]  _invalidate_shot_type_caches
    def _invalidate_shot_type_caches(self):
        """素材列表变更后失效景别缓存（_shot_type_for_clip / _source_shot_type_map）。"""
        self._clip_shot_type_cache = {}
        self._source_shot_type_cache = None

    # [2·基础设施]  _add_paths_to_video_list
    def _add_paths_to_video_list(self, paths):
        """把一批本地视频路径加入 video_list（去重），供选择/拖拽共用入口。

        返回新增数量；无新增时也刷新扫描（保持与 _select_folder 行为一致）。
        """
        if not paths:
            return 0
        existing = set()
        for i in range(self.video_list.count()):
            if self._is_local_file_item(self.video_list.item(i)):
                existing.add(os.path.abspath(self.video_list.item(i).text().strip()))
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap in existing:
                continue
            existing.add(ap)
            it = QListWidgetItem(ap)
            self.video_list.addItem(it)
            self._decorate_video_item_widget(it)
            added += 1
        if added:
            self._invalidate_shot_type_caches()
        if True:
            self._ensure_montage_job()
            self._last_merged_splits_dirs = self._collect_merged_splits_dirs()
            self.processing_video_path = ""
            self.video_list.setCurrentItem(None)
            self._refresh_source_root_hint()
            self._check_split_clips_exist()
        log.info(f"[DIAG _add_paths] paths={len(paths)} added={added} list_count={self.video_list.count()}")  # noqa: E501
        return added

    # [2·基础设施]  _on_drop_videos
    def _on_drop_videos(self, paths):
        """拖放区拖入素材的回调：文件夹递归展开为全部视频，去重加入列表并刷新。"""
        if not paths:
            return
        files = self._expand_dropped_paths(paths)
        if not files:
            if hasattr(self, "stage_label"):
                self.stage_label.setText("拖入的内容里没有可用的视频文件。")
            return
        added = self._add_paths_to_video_list(files)
        if hasattr(self, "stage_label"):
            self.stage_label.setText(
                f"已新增 {added} 个素材到列表。" if added else "所选素材已在列表中，无新增。")

    # [2·基础设施]  _expand_dropped_paths
    @staticmethod
    def _expand_dropped_paths(paths):
        """拖入路径 → 视频文件列表（目录按子文件夹递归遍历，文件按扩展名过滤）。

        同时拖入文件夹和夹内视频时只保留一份（保持拖入顺序，去重交给绝对路径）。
        """
        files = []
        seen = set()
        for p in paths:
            if os.path.isdir(p):
                candidates = collect_video_files(p)
            elif p.lower().endswith(VIDEO_EXTS):
                candidates = [os.path.abspath(p)]
            else:
                continue
            for fp in candidates:
                if fp not in seen:
                    seen.add(fp)
                    files.append(fp)
        return files

    # [2·基础设施]  _select_folder
    def _select_folder(self):
        """选择素材文件夹：递归遍历该文件夹（含全部子文件夹）下的视频加入素材列表。

        以往要逐层进入存放视频的末级目录再多选文件，现在选一个顶层目录即可
        把整批素材一次导入（跳过隐藏目录与 splits/outputs 等混剪派生目录）。
        """
        folder = pick_directory(self.parent_widget, "选择视频素材文件夹（含子文件夹全部导入）", "")
        if not folder:
            return
        file_paths = collect_video_files(folder)
        if not file_paths:
            self.stage_label.setText("该文件夹（含子文件夹）内未找到视频文件。")
            QMessageBox.information(
                self.parent_widget, "未发现视频",
                f"在所选文件夹及其子文件夹中未找到视频文件。\n{folder}\n"
                f"支持格式：{', '.join(VIDEO_EXTS)}")
            log.info(f"[DIAG _select_folder] folder={folder} scanned=0")
            return
        added = self._add_paths_to_video_list(file_paths)
        log.info(f"[DIAG _select_folder] folder={folder} scanned={len(file_paths)} added={added}")
        if len(file_paths) >= MAX_SOURCE_VIDEOS:
            self.stage_label.setText(
                f"扫描已达单次上限 {MAX_SOURCE_VIDEOS} 个，仅导入前面的素材，建议按子目录分开选。")
        elif added == 0:
            self.stage_label.setText("该文件夹的视频已在列表中，无新增。")
        else:
            # 景别分布统计：让用户在导入时就知道命名/归档是否被正确识别
            counts = {}
            for _p in file_paths:
                _key = SHOT_TYPE_LABELS.get(classify_shot_type(_p), "未标注")
                counts[_key] = counts.get(_key, 0) + 1
            dist = "、".join(f"{k} {v}" for k, v in counts.items())
            self.stage_label.setText(
                f"已遍历文件夹，新增 {added} 个素材到列表（共扫描 {len(file_paths)} 个｜景别分布：{dist}）。")

    @staticmethod
    def _is_local_file_item(item):
        """列表项是否为本地可访问文件（material:// 等地址项返回 False）。"""
        if item is None:
            return False
        p = item.text().strip()
        return bool(p) and not p.startswith("material://") and os.path.isfile(p)

    # [2·基础设施]  混剪任务级缓存（方案二）辅助方法
    def _montage_job_root(self):
        """当前混剪任务缓存目录；未创建任务时返回空。"""
        jid = getattr(self, "_montage_job_id", "")
        if not jid:
            return ""
        return job_root(jid)

    def _montage_splits_root(self):
        """任务缓存的 splits 整体目录（各视频的派生片段分子目录在其下）。"""
        jid = getattr(self, "_montage_job_id", "")
        if not jid:
            return ""
        return job_splits_dir(jid)

    def _montage_per_video_splits_dir(self, video_path):
        """单个本地视频的派生分割片段目录。

        任务缓存已创建时写到
        .runtime/montage_cache/<job_id>/splits/<短视频名>/，
        不复制原始素材、不污染源视频目录；
        未创建任务时回退旧式目录以兼容历史分镜。
        短名与片段文件名共用 safe_source_name（防超长路径，全链路一致）。
        """
        from gui.montage.utils_media import safe_source_name
        base = safe_source_name(video_path)
        sp_root = self._montage_splits_root()
        if sp_root:
            return os.path.join(sp_root, base)
        vdir = os.path.dirname(video_path)
        return os.path.join(vdir, base, "splits")

    def _collect_merged_splits_dirs(self):
        """收集列表中所有本地视频的 splits 目录（合并扫描用）。"""
        dirs = []
        for i in range(self.video_list.count()):
            it = self.video_list.item(i)
            if self._is_local_file_item(it):
                dirs.append(self._montage_per_video_splits_dir(it.text().strip()))
        return dirs

    def _manifest_entries_from_list(self):
        """按当前素材列表生成 local/server 两类清单条目（local_clip 另行维护）。"""
        entries = []
        for i in range(self.video_list.count()):
            it = self.video_list.item(i)
            if it is None:
                continue
            t = it.text().strip()
            if not t:
                continue
            if self._is_local_file_item(it):
                entries.append({
                    "kind": "local",
                    "source_path": os.path.abspath(t),
                    "display": os.path.basename(t),
                })
            elif t.startswith("material://"):
                mid = t[len("material://"):].split(" ")[0].strip()
                _meta = it.data(Qt.UserRole) or {}
                entries.append({
                    "kind": "server",
                    "material_id": mid,
                    "clip_url": f"material://{mid}",
                    "display": t,
                    "media_type": (_meta.get("media_type") or "").lower(),
                    "ai_status": _meta.get("ai_status") or "",
                    "scene_desc_primary": _meta.get("scene_desc_primary") or "",
                    "scene_desc_secondary": _meta.get("scene_desc_secondary") or "",
                    "quality_score": _meta.get("quality_score"),
                    "shot_type": _meta.get("shot_type") or "",
                })
        return entries

    def _ensure_montage_job(self):
        """确保存在任务级缓存 job_id + manifest。

        以当前素材列表重建 local/server 条目；原始素材只写引用（不拷贝），
        已生成的派生 local_clip 片段继续保留。返回 manifest dict。
        """
        if not getattr(self, "_montage_job_id", ""):
            self._montage_job_id = new_job_id()
        old = load_manifest(self._montage_job_id)
        old_clips = [e for e in (old.get("entries") or []) if e.get("kind") == "local_clip"]  # noqa: E501
        manifest = {
            "job_id": self._montage_job_id,
            "created_at": old.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
            "entries": self._manifest_entries_from_list() + old_clips,
            "concat_task_id": old.get("concat_task_id"),
        }
        save_manifest(self._montage_job_id, manifest)
        self._montage_manifest = manifest
        return manifest

    def _sync_manifest_local_clips(self):
        """分割完成后：把缓存 splits/ 下生成的派生片段同步进 manifest。"""
        if not getattr(self, "_montage_job_id", ""):
            return None
        old = load_manifest(self._montage_job_id)
        base_entries = [e for e in (old.get("entries") or []) if e.get("kind") != "local_clip"]  # noqa: E501
        sp_root = self._montage_splits_root()
        clip_entries = []
        if sp_root and os.path.isdir(sp_root):
            for vbase in sorted(os.listdir(sp_root)):
                d = os.path.join(sp_root, vbase)
                if not os.path.isdir(d):
                    continue
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith((".mp4", ".m4v")):
                        clip_entries.append({
                            "kind": "local_clip",
                            "source_video": vbase,
                            "filename": f,
                            "clip_path": os.path.abspath(os.path.join(d, f)),
                        })
        manifest = {
            "job_id": self._montage_job_id,
            "created_at": old.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
            "entries": base_entries + clip_entries,
            "concat_task_id": old.get("concat_task_id"),
        }
        save_manifest(self._montage_job_id, manifest)
        self._montage_manifest = manifest
        return manifest

    def _manifest_clip_urls(self):
        """从 manifest 取 server 条目（material://），供 concat 的 clip_urls 使用。"""
        man = self._montage_manifest
        if man is None and self._montage_job_id:
            man = load_manifest(self._montage_job_id)
            self._montage_manifest = man
        urls = []
        if man:
            for e in man.get("entries") or []:
                if e.get("kind") == "server" and e.get("clip_url"):
                    urls.append(e["clip_url"])
        if not urls:
            urls = list(getattr(self, "external_clip_urls", None) or [])
        return urls

    def _clear_montage_cache(self):
        """清空混剪任务缓存（只删派生片段/清单，不动原素材）。"""
        reply = QMessageBox.question(
            self.parent_widget, "清空混剪缓存",
            "将删除本地混剪任务缓存中的所有派生分割片段与素材清单\n"
            "（不会删除任何原始素材文件，素材检索地址素材仍保存在服务端）。\n\n确认清空？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        removed = clear_montage_cache()
        self._montage_job_id = ""
        self._montage_manifest = None
        self._last_merged_splits_dirs = []
        self.external_clip_urls = []
        self.split_clips_list = []
        # 同时清空「已添加的素材列表」及其源目录与派生缓存（只移出列表/清内存态，不删原始素材文件）。
        # 之前只删了磁盘任务目录与分割结果表，video_list 未清，导致点「清空混剪缓存」后素材仍留在列表。
        if hasattr(self, "video_list"):
            self.video_list.clear()
        if hasattr(self, "folder_path_input"):
            self.folder_path_input.clear()
        self.split_clips_cache = {}
        self.split_descriptions = {}
        self._clip_duration_cache = {}
        if hasattr(self, "_clip_shot_type_cache"):
            self._invalidate_shot_type_caches()
        self.processing_video_path = ""
        self.temp_scenes = []
        self._available_concat_clips = []
        if hasattr(self, "split_result_table"):
            self.split_result_table.setRowCount(0)
        self.stage_label.setText(f"已清空混剪缓存（{removed} 个任务目录），素材列表已重置")
        log.info(f"[智能混剪] 用户清空混剪缓存，移除 {removed} 个任务目录，并重置素材列表")

    def set_external_materials(self, materials):
        """从「素材检索」带入多个素材（仅本地/NAS 可访问路径会加入）。

        materials: [{material_id, filename, media_type, path, url, ...}]
        注：镜头分割由服务端完成，素材需在本地/NAS 挂载或素材库可访问；
        只有服务端 URL 的素材会被跳过并提示。
        """
        if not materials:
            return
        existing = set()
        for i in range(self.video_list.count()):
            t = self.video_list.item(i).text().strip()
            if t:
                existing.add(os.path.abspath(t))
        added = 0
        skipped = 0
        paths = []
        # 素材检索地址（material://{id}）：直接作 concat 的 clip_urls（服务端按素材库解析），并统一显示在素材列表
        self.external_clip_urls = []
        for mt in materials:
            p = (mt.get("path") or "").strip()
            mid = mt.get("material_id")
            mtype = (mt.get("media_type") or "").lower()
            is_img = mtype in ("image", "jpg", "jpeg", "png", "webp", "bmp")
            # 图片素材一律走 material://（服务端自动转静态片段），避免进本地分割
            if (not is_img) and p and os.path.isfile(p):
                ap = os.path.abspath(p)
                if ap in existing:
                    continue
                existing.add(ap)
                it = QListWidgetItem(ap)
                self.video_list.addItem(it)
                self._decorate_video_item_widget(it)
                paths.append(ap)
                added += 1
            elif mid:
                self.external_clip_urls.append(f"material://{mid}")
                label = f"material://{mid} · {mt.get('filename') or mid}"
                if label not in existing:
                    existing.add(label)
                    it = QListWidgetItem(label)
                    # 保留素材库分析字段（图片免分剰复用 / 视频传 material_id 分剰）
                    it.setData(Qt.UserRole, {
                        "material_id": str(mid),
                        "media_type": mtype,
                        "filename": mt.get("filename") or "",
                        "ai_status": mt.get("ai_status") or "",
                        "scene_desc_primary": mt.get("scene_desc_primary") or "",
                        "scene_desc_secondary": mt.get("scene_desc_secondary") or "",
                        "quality_score": mt.get("quality_score"),
                        "shot_type": mt.get("shot_type") or "",
                    })
                    self.video_list.addItem(it)
                    added += 1
            else:
                skipped += 1
        if added:
            common_dir = ""
            if paths:
                try:
                    common_dir = os.path.commonpath([os.path.dirname(os.path.abspath(x)) for x in paths])  # noqa: E501
                except (ValueError, TypeError):
                    common_dir = os.path.dirname(os.path.abspath(paths[0]))
            if common_dir:
                self.folder_path_input.setText(common_dir)
            self._invalidate_shot_type_caches()
            self._ensure_montage_job()
            self._last_merged_splits_dirs = self._collect_merged_splits_dirs()
            self.processing_video_path = ""
            self.video_list.setCurrentItem(None)
            self._refresh_source_root_hint()
            self._check_split_clips_exist()
        parts = []
        if added:
            parts.append(f"{added} 个素材已加入（含素材检索地址）")
        if skipped:
            parts.append(f"{skipped} 个无效素材已跳过")
        msg = "已从素材检索带入： " + "；".join(parts) if parts else "未带入素材"
        self.stage_label.setText(msg)
        log.info(f"[素材检索→智能混剪] {msg}")

    # [3·分割]  _get_split_scenes_times
    def _get_split_scenes_times(self, splits_dir, files):
        """获取片段起止时间列表（累积时间轴）。

        时长来源优先级（全部避免在 UI 主线程批量 ffprobe/cv2，防卡死）：
        1. 从文件名解析时间戳（服务端返回的片段名已包含起止时间）
        2. 从 _clip_duration_cache 读取
        3. cv2 兜底：仅当待兜底片段数 ≤ _CV2_FALLBACK_MAX 时同步读取，超出则时长留空(0)，
           由后台异步评分补充（绝不在主线程对大量片段跑 cv2/ffprobe）。
        """
        if hasattr(self, "temp_scenes") and self.temp_scenes and len(self.temp_scenes) == len(files):  # noqa: E501
            return self.temp_scenes

        # 缓存已计算的时长，避免重复 cv2 读取
        if not hasattr(self, "_clip_duration_cache"):
            self._clip_duration_cache = {}

        # 单次刷新允许 cv2 兜底探测的最大片段数：超过则跳过 cv2，避免主线程长时间阻塞
        _CV2_FALLBACK_MAX = 8  # noqa: N806

        # 第一遍：解析文件名 / 读缓存，得到每个片段的时长（0 表示待兜底）
        durations: list[float] = []
        pending_cv2: list[tuple[int, str]] = []  # (下标, 绝对路径)
        for i, f in enumerate(files):
            fname = os.path.basename(f)
            p = f if os.path.isabs(f) else os.path.join(splits_dir, f)
            norm_p = os.path.abspath(p)

            duration = 0.0
            # 尝试从文件名解析时间戳（格式：_shot_XXX_HH-MM-SS,mmm_HH-MM-SS,mmm_）
            parsed = self._parse_split_filename(fname)
            if parsed:
                _idx, start_str, end_str, _desc = parsed
                _s = self._srt_ts_to_seconds(start_str)
                _e = self._srt_ts_to_seconds(end_str)
                if _s is not None and _e is not None and _e > _s:
                    duration = _e - _s
            # 文件名无法解析时，尝试从缓存读取
            if duration <= 0:
                duration = self._clip_duration_cache.get(norm_p, 0.0)

            durations.append(duration)
            if duration <= 0:
                pending_cv2.append((i, norm_p))

        # 第二遍：仅对少量无法从文件名/缓存得到时长的片段用 cv2 兜底（有界，防卡死）
        # 不再用 ffprobe（get_media_duration）兜底——那会在主线程 spawn 子进程导致 (Not Responding)。
        if pending_cv2 and len(pending_cv2) <= _CV2_FALLBACK_MAX:
            import cv2
            for i, norm_p in pending_cv2:
                duration = 0.0
                try:
                    cap = cv2.VideoCapture(norm_p)
                    if cap.isOpened():
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                        if fps > 0:
                            duration = frame_count / fps
                        cap.release()
                except Exception:  # cv2 读取异常不得冒泡到 UI
                    duration = 0.0
                if duration > 0:
                    durations[i] = duration
                    self._clip_duration_cache[norm_p] = duration
        elif pending_cv2:
            log.info(f"[分割时长] {len(pending_cv2)} 个片段文件名无时间戳且无缓存，超过 cv2 兜底上限 {_CV2_FALLBACK_MAX}，跳过同步探测（时长留空由后台异步补）")  # noqa: E501

        # 单次累积成时间轴（不再对每个兜底片段 O(n²) 重算）
        scenes = []
        current_time = 0.0
        for dur in durations:
            scenes.append((current_time, current_time + dur))
            current_time += dur

        return scenes
    # [3·分割]  _parse_split_filename
    def _parse_split_filename(self, filename):
        import re
        pattern = r"_shot_(\d+)_(\d{2}-\d{2}-\d{2},\d{3})_(\d{2}-\d{2}-\d{2},\d{3})(?:_(.*))?$"  # noqa: E501
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
        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])  # noqa: E501
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
            if end_sec <= start_sec:
                # scenes 缺失/全 0（如 cv2 读不出时长）时，保留文件名里已有的有效时间戳
                parsed_ts = self._parse_split_filename(filename)
                if parsed_ts:
                    _s = self._srt_ts_to_seconds(parsed_ts[1])
                    _e = self._srt_ts_to_seconds(parsed_ts[2])
                    if _s is not None and _e is not None and _e > _s:
                        start_sec, end_sec = _s, _e
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
                        log.info(f"Renamed split: {filename} -> {os.path.basename(new_path)}")  # noqa: E501
                except OSError as e:
                    log.warning(f"Failed to rename split file {filename}: {e}")
                    new_path = old_path
            new_split_clips_list.append(new_path)
            new_split_descriptions[new_path] = desc
        self.split_clips_list = new_split_clips_list
        for p, d in new_split_descriptions.items():
            self.split_descriptions[p] = d
    # [3·分割]  _update_raw_srt_display_from_splits
    def _update_raw_srt_display_from_splits(self):
        files = [os.path.abspath(p) for p in getattr(self, "split_clips_list", [])]
        if not files:
            return
        scenes = self._get_split_scenes_times("", files)

        srt_lines = []
        for idx, p in enumerate(files, 1):
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
        if not video_path and hasattr(self, "processing_video_path") and self.processing_video_path:  # noqa: E501
            video_path = self.processing_video_path
        if not video_path:
            return
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        splits_dir = self._montage_per_video_splits_dir(video_path)
        video_workspace_dir = os.path.dirname(splits_dir)
        srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
        if not os.path.exists(splits_dir):
            return

        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])  # noqa: E501
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
        except OSError as e:
            log.warning(f"保存分割字幕文件失败: {e}")
    # [3·分割]  _check_split_clips_exist
    def _check_split_clips_exist(self, item=None):
        dir_path = self.folder_path_input.text().strip()
        _cur_item = self.video_list.currentItem() if hasattr(self, "video_list") else None  # noqa: E501
        _cur_text = _cur_item.text().strip() if _cur_item else ""
        _pvp = getattr(self, "processing_video_path", "")
        log.info(f"[DIAG _check_split_clips_exist] folder_path_input='{dir_path}' currentItem='{_cur_text}' processing_video_path='{_pvp}'")  # noqa: E501
        self.split_clips_list = []

        # Block signals on table during update to avoid triggering cellChanged slot
        self.split_result_table.blockSignals(True)
        self.split_result_table.setRowCount(0)
        self._pending_score_rows = []  # 待后台评分的行

        splits_dir = ""
        if dir_path and os.path.exists(dir_path):
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if (selected_item and self._is_local_file_item(selected_item)) else ""  # noqa: E501
            if not video_path and hasattr(self, "processing_video_path") and self.processing_video_path:  # noqa: E501
                video_path = self.processing_video_path
            log.info(f"[DIAG _check_split_clips_exist] resolved video_path='{video_path}' (source={'currentItem' if selected_item else 'processing_video_path'})")  # noqa: E501
            if video_path:
                splits_dir = self._montage_per_video_splits_dir(video_path)
                video_workspace_dir = os.path.dirname(splits_dir)
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
                files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])  # noqa: E501
            log.info(f"[DIAG _check_split_clips_exist] splits_dir='{splits_dir}' files_count={len(files)}")  # noqa: E501

            # 镜头分析 sidecar 缓存：按镜头内容指纹命中，恢复 score/景别/产品/型号
            try:
                from utils.shot_analysis_cache import ShotAnalysisCache
                shot_caches: dict | None = {}
            except (ImportError, ModuleNotFoundError) as e:
                log.warning(f"导入镜头分析缓存失败: {e}")
                shot_caches = None

            # Try to restore split descriptions from the srt file if they are not in self.split_descriptions yet  # noqa: E501
            if files and video_path:
                video_basename = os.path.splitext(os.path.basename(video_path))[0]
                video_dir = os.path.dirname(video_path)
                video_workspace_dir = os.path.dirname(splits_dir)
                if shot_caches is not None:
                    self._shot_cache: ShotAnalysisCache | None = ShotAnalysisCache(video_workspace_dir, video_basename)  # noqa: E501
                    shot_caches[(video_workspace_dir, video_basename)] = self._shot_cache  # noqa: E501
                else:
                    self._shot_cache = None
                srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
                if not os.path.exists(srt_path):
                    srt_path = os.path.join(video_dir, f"{video_basename}.srt")
                if os.path.exists(srt_path):
                    try:
                        with open(srt_path, encoding="utf-8") as f:
                            srt_content = f.read()
                        parsed_texts = parse_srt_to_descriptions(srt_content)
                        for idx, f_name in enumerate(files):
                            p_clip = os.path.join(splits_dir, f_name)
                            norm_p = os.path.abspath(p_clip)
                            if norm_p not in self.split_descriptions:  # noqa: SIM102
                                if idx < len(parsed_texts):
                                    self.split_descriptions[norm_p] = parsed_texts[idx]
                    except (OSError, KeyError, TypeError, IndexError) as e:
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
                        _p_idx, start_str, end_str, desc = parsed
                        time_str = f"{start_str} --> {end_str}"
                    else:
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

                    # 尝试命中镜头分析 sidecar 缓存：恢复 score/景别/产品/型号/描述
                    cached = None
                    sc = getattr(self, "_shot_cache", None)
                    if sc is not None:
                        try:
                            cached = sc.get(norm_path)
                        except (KeyError, TypeError, AttributeError):
                            cached = None
                    # 合并扫描时每个片段可能来自不同源视频，按片段路径找对应缓存
                    if not cached and shot_caches is not None:
                        try:
                            _sc = self._get_shot_cache_for_clip(norm_path)
                            if _sc is not None:
                                cached = _sc.get(norm_path)
                        except (KeyError, TypeError, AttributeError):
                            cached = None

                    # 缓存优先于 SRT/文件名解析的画面描述
                    if cached:
                        c_desc = cached.get("desc") or ""
                        if c_desc:
                            desc = c_desc
                            self.split_descriptions[norm_path] = desc

                    # 由起止时间戳推算时长（秒），本地即可得出，不依赖服务端
                    _s_sec = self._srt_ts_to_seconds(start_str)
                    _e_sec = self._srt_ts_to_seconds(end_str)
                    duration_sec = (max(0.0, _e_sec - _s_sec)
                                    if (_s_sec is not None and _e_sec is not None) else 0.0)  # noqa: E501
                    if duration_sec <= 0 and cached:
                        try:
                            duration_sec = float(cached.get("duration") or 0.0)
                        except (TypeError, ValueError):
                            duration_sec = 0.0
                    # 不再在 UI 主线程调用 get_media_duration()（会 spawn ffprobe 子进程导致卡死）
                    # 时长为 0 时显示 "—"，后续由后台异步评分时补充

                    # 缓存先占位（后台异步评分）；命中缓存则预填已有字段
                    self.split_clips_cache[norm_path] = {
                        "filename": display_name, "time_str": time_str,
                        "desc": desc, "duration": duration_sec,
                        "score": cached.get("score") if cached else None,
                        "shot_type": (cached.get("shot_type", "") if cached else ""),
                        "product": (cached.get("product", "") if cached else ""),
                        "model": (cached.get("model", "") if cached else ""),
                    }

                    # Col 0: Checkbox
                    chk_item = QTableWidgetItem()
                    chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)  # noqa: E501
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
                    shot_item = QTableWidgetItem(cached.get("shot_type", "") if cached else "")  # noqa: E501
                    shot_item.setFlags(shot_item.flags() & ~Qt.ItemIsEditable)
                    shot_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 3, shot_item)

                    # Col 4: 时长 (duration)
                    dur_item = QTableWidgetItem(f"{duration_sec:.1f}s" if duration_sec > 0 else "")  # noqa: E501
                    dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
                    dur_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 4, dur_item)

                    # Col 5: 画幅 (resolution) — 从缓存或探测第一个片段获取
                    resolution_text = ""
                    if cached and cached.get("resolution"):
                        resolution_text = cached["resolution"]
                    elif not getattr(self, "_probed_resolution", None):
                        # 首次探测：从第一个片段获取分辨率（后续片段复用）
                        try:
                            from utils.platform_utils import find_ffprobe
                            ffprobe = find_ffprobe()
                            if not os.path.isfile(ffprobe):
                                ffprobe = find_ffmpeg().replace("ffmpeg", "ffprobe")
                            cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
                                   "-show_entries", "stream=width,height",
                                   "-of", "csv=p=0:s=x", norm_path]
                            r = run(cmd, capture_output=True, text=True,
                                    creationflags=CREATE_NO_WINDOW, timeout=10)
                            if r.returncode == 0 and r.stdout.strip():
                                parts = r.stdout.strip().split("x")
                                if len(parts) == 2:
                                    w, h = int(parts[0]), int(parts[1])
                                    # 检查旋转元数据
                                    cmd2 = [ffprobe, "-v", "error", "-select_streams", "v:0",
                                            "-show_entries", "stream=side_data_list,tag:rotate",
                                            "-of", "json", norm_path]
                                    r2 = run(cmd2, capture_output=True, text=True,
                                             creationflags=CREATE_NO_WINDOW, timeout=10)
                                    if r2.returncode == 0 and r2.stdout.strip():
                                        import json as _json
                                        d2 = _json.loads(r2.stdout)
                                        s2 = (d2.get("streams") or [{}])[0]
                                        rot = 0
                                        for sd in (s2.get("side_data_list") or []):
                                            rv = sd.get("rotation")
                                            if rv is not None:
                                                try: rot = int(float(rv))
                                                except: pass
                                                break
                                        if rot == 0:
                                            tr = s2.get("tags", {}).get("rotate")
                                            if tr:
                                                try: rot = int(float(tr))
                                                except: pass
                                        if rot in (90, -90, 270, -270):
                                            w, h = h, w
                                    resolution_text = f"{w}x{h}"
                                    self._probed_resolution = resolution_text
                                    # 回写缓存
                                    if cached:
                                        cached["resolution"] = resolution_text
                        except Exception:
                            pass
                    elif getattr(self, "_probed_resolution", None):
                        resolution_text = self._probed_resolution
                    res_item = QTableWidgetItem(resolution_text)
                    res_item.setFlags(res_item.flags() & ~Qt.ItemIsEditable)
                    res_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 5, res_item)

                    # Col 6: 主要画面 (description, editable)
                    desc_item = QTableWidgetItem(desc)
                    desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 6, desc_item)

                    # Col 7: 产品
                    prod_item = QTableWidgetItem(cached.get("product", "") if cached else "")  # noqa: E501
                    prod_item.setFlags(prod_item.flags() & ~Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 7, prod_item)

                    # Col 8: 型号
                    model_item = QTableWidgetItem(cached.get("model", "") if cached else "")  # noqa: E501
                    model_item.setFlags(model_item.flags() & ~Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 8, model_item)

                    # Col 9: 评分 — 命中缓存则回填，否则等待服务端分析
                    cached_score = cached.get("score") if cached else None
                    if cached_score is not None:
                        score_item = QTableWidgetItem(f"{cached_score:.1f}" if cached_score >= 0 else "—")  # noqa: E501
                        if cached_score >= 8.0:
                            score_item.setForeground(QColor("#2ecc71"))
                        elif cached_score >= 6.0:
                            score_item.setForeground(QColor("#f1c40f"))
                        elif cached_score >= 0:
                            score_item.setForeground(QColor("#e74c3c"))
                    else:
                        score_item = QTableWidgetItem("—")
                    score_item.setFlags(score_item.flags() & ~Qt.ItemIsEditable)
                    score_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 9, score_item)

                    # 已命中缓存的镜头不进后台评分队列（已有评分，避免重复调服务端）
                    if not cached:
                        self._pending_score_rows.append((idx, norm_path))
                    initial_desc_lines.append(desc)

                # Update rewritten_srt_display
                if hasattr(self, "rewritten_srt_display"):
                    self.rewritten_srt_display.setPlainText("\n".join(initial_desc_lines))  # noqa: E501
                # Update subtitle display with split subtitles
                self._update_raw_srt_display_from_splits()
            else:
                # No split files. Display original raw srt if it exists
                if video_path:
                    video_basename = os.path.splitext(os.path.basename(video_path))[0]
                    video_dir = os.path.dirname(video_path)
                    video_workspace_dir = (os.path.dirname(splits_dir) if splits_dir
                                           else os.path.join(video_dir, video_basename))
                    srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")  # noqa: E501
                    if not os.path.exists(srt_path):
                        srt_path = os.path.join(video_dir, f"{video_basename}.srt")
                    if os.path.exists(srt_path):
                        try:
                            with open(srt_path, encoding="utf-8") as f:
                                raw_srt = f.read().strip()
                            if hasattr(self, "rewritten_srt_display"):
                                self.rewritten_srt_display.setPlainText(raw_srt)
                        except OSError as e:
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
            inp = getattr(self, "concat_src_dir_input", None)
            if inp is not None:
                inp.setText(splits_dir)
            self._scan_concat_src_dir()
        else:
            self._available_concat_clips = []
            self._update_concat_count_lbl()
    # [3·分割]  _on_score_all_done (legacy: 本地评分已移除，保留兼容)
    def _on_score_all_done(self):
        self._pending_score_rows = []
        # 显示之前暂存的结果对话框
        pending = getattr(self, "_pending_dialog", None)
        if pending:
            title, detail = pending
            self._pending_dialog = None
            self.stage_label.setText(f"完成： {title}")
            QMessageBox.information(self.parent_widget, title, detail)
        self.btn_next_to_step_2.setEnabled(True)
    def _on_rate_all_done(self):
        return

    # [7·混音导出]  _select_bgm
    def _select_bgm(self):
        path, _ = pick_file(
            self.parent_widget,
            "选择背景配乐",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac);;All Files (*)",
        )
        if path:
            self.bgm_input.setText(path)
    # [2·基础设施]  _select_ref_audio
    def _select_ref_audio(self):
        path, _ = pick_file(
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
                    if s.get("path") and os.path.abspath(s.get("path")) == os.path.abspath(path):  # noqa: E501
                        self.ref_text_input.setText(s.get("ref_text", s.get("text", "")))  # noqa: E501
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
        file_paths, _ = pick_files(
            self.parent_widget,
            "选择需要克隆配音的视频",
            "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;所有文件 (*.*)"
        )
        if file_paths:
            dir_path = os.path.dirname(file_paths[0])
            self.voice_video_dir_input.setText(dir_path)
            self.selected_voice_video_files = file_paths
            self._scan_voice_video_dir()
    # [6·配音]  _on_voice_video_dir_changed
    def _on_voice_video_dir_changed(self):
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

        # If user explicitly selected files, use them if they match current dir_path
        if hasattr(self, "selected_voice_video_files") and self.selected_voice_video_files:  # noqa: E501
            first_parent = os.path.abspath(os.path.dirname(self.selected_voice_video_files[0]))  # noqa: E501
            current_dir = os.path.abspath(dir_path)
            if first_parent == current_dir:
                files = [os.path.abspath(f) for f in self.selected_voice_video_files]

        if not files:
            try:
                for f in os.listdir(dir_path):
                    if f.lower().endswith(exts):
                        files.append(os.path.join(dir_path, f))
            except OSError as e:
                log.warning(f"扫描视频目录失败: {e}")
                self._adjust_table_height()
                return

        # Sort naturally or alphabetically
        files.sort(key=lambda x: os.path.basename(x).lower())
        self.voice_video_paths = files

        # Determine voices output directory to auto-detect already generated audios
        out_montage_dir = self._get_out_montage_dir(dir_path)
        voices_dir = os.path.join(out_montage_dir, "voices")

        self.voice_table.setRowCount(len(files))

        for i, filepath in enumerate(files):
            basename = os.path.basename(filepath)

            # Sync generated voice paths if the expected wav exists on disk
            expected_wav_path = os.path.abspath(os.path.join(voices_dir, f"voice_{i + 1}.wav"))  # noqa: E501
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
                        with open(companion_txt_path, encoding="utf-8") as f:
                            original_txt = f.read().strip()
                    except OSError:
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

            # If the voice is already generated, apply the green success background style  # noqa: E501
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
            btn_play.clicked.connect(lambda checked=False, path=filepath: self._on_btn_play_clicked(path))  # noqa: E501
            action_widgets.append(btn_play)

            btn_export = mdi_button("", "save")
            btn_export.setToolTip("导出该克隆声音")
            btn_export.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_export.setFixedWidth(28)
            btn_export.setFixedHeight(22)
            btn_export.setEnabled(bool(wav_path and os.path.exists(wav_path)))
            btn_export.clicked.connect(lambda checked=False, path=filepath: self._on_btn_export_clicked(path))  # noqa: E501
            action_widgets.append(btn_export)

            btn_compare = mdi_button("", "balance-scale")
            btn_compare.setToolTip("对比与编辑文案")
            btn_compare.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_compare.setFixedWidth(28)
            btn_compare.setFixedHeight(22)
            btn_compare.clicked.connect(lambda checked=False, idx=i: self._on_btn_compare_clicked(idx))  # noqa: E501
            action_widgets.append(btn_compare)

            btn_regen = mdi_button("", "refresh")
            btn_regen.setToolTip("仅重新生成该声音")
            btn_regen.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_regen.setFixedWidth(28)
            btn_regen.setFixedHeight(22)
            btn_regen.clicked.connect(lambda checked=False, path=filepath: self._on_btn_regen_clicked(path))  # noqa: E501
            action_widgets.append(btn_regen)

            # Length mode toggle button (video-based vs audio-based)
            current_mode = self.voice_length_mode.get(filepath, "video")
            btn_length_mode = mdi_button("", "video" if current_mode == "video" else "audio")  # noqa: E501
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

            # Play video button (next to filename in top row)
            # 优先播放配音后的视频（配音完成后用户想看配音效果），未配音时播放原视频
            btn_play_original = mdi_button("", "play")
            btn_play_original.setToolTip("播放视频（配音后优先）")
            btn_play_original.setStyleSheet("padding: 0px; font-size: 10px;")
            btn_play_original.setFixedWidth(24)
            btn_play_original.setFixedHeight(20)
            btn_play_original.clicked.connect(lambda checked=False, path=filepath: self._on_play_row_video(path))  # noqa: E501

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
                btn_play_dubbed.clicked.connect(lambda checked=False, path=dubbed_path: self._play_video(path))  # noqa: E501
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
        target_height = header_height + total_rows_height + frame_width + margin_height + 4  # noqa: E501
        # Cap height between a minimum of 350px and a maximum of 600px to ensure scrolling if there are many files  # noqa: E501
        capped_height = min(max(target_height, 350), 600)
        self.voice_table.setFixedHeight(capped_height)
    # [9·其他]  _on_edit_double_clicked
    def _on_edit_double_clicked(self, row_idx):
        edit = self.row_edits.get(row_idx)
        if edit:
            dialog = TextEditDialog(f"编辑第 {row_idx + 1} 行配音文案", edit.text(), self.parent_widget)  # noqa: E501
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
                        background: qlineargradient(
                            x1:0, y1:0, x2:1, y2:0,
                            stop:0 rgba(46, 204, 113, 0.35),
                            stop:{ratio} rgba(46, 204, 113, 0.35),
                            stop:{ratio} rgba(255, 255, 255, 0.05),
                            stop:1 rgba(255, 255, 255, 0.05)
                        );
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

        save_path, _ = pick_save_file(
            self.parent_widget,
            "导出克隆声音",
            os.path.basename(wav_path),
            "Audio Files (*.wav);;All Files (*)"
        )
        if save_path:
            try:
                shutil.copy2(wav_path, save_path)
                QMessageBox.information(self.parent_widget, "导出成功", f"人声音频成功导出至：\n{save_path}")  # noqa: E501
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "导出失败", f"无法导出文件: {e}")
    # [6·配音]  _play_audio
    def _play_audio(self, wav_path):
        try:
            if wav_path.lower().endswith(".wav"):
                # Qt 的 QMediaPlayer / QSoundEffect 在部分 Windows 上会把 WAV 尾部截断
                # （例如克隆声音“特”被吞成“ti”）。winsound 走系统原生播放，可完整播完。
                from utils.wav_player import play_wav
                play_wav(wav_path)
                return
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            if not hasattr(self, "_media_player") or not self._media_player:
                self._media_player = QMediaPlayer()
                self._audio_output = QAudioOutput()
                self._media_player.setAudioOutput(self._audio_output)

            if self._media_player.playbackState() == QMediaPlayer.PlayingState:
                self._media_player.stop()
                if self._media_player.source().toLocalFile() == os.path.abspath(wav_path):  # noqa: E501
                    return

            self._media_player.setSource(QUrl.fromLocalFile(wav_path))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except (OSError, RuntimeError) as e:
            log.error(f"播放音频失败: {e}")
    # [9·其他]  _on_btn_regen_clicked
    def _on_btn_regen_clicked(self, video_path):
        for i in range(self.voice_table.rowCount()):
            item = self.voice_table.item(i, 1)
            if item and item.data(Qt.UserRole) == video_path:
                edit = self.row_edits.get(i)
                text = edit.text().strip() if edit else ""
                if not text:
                    QMessageBox.warning(self.parent_widget, "配音文案为空", "该行文案为空，无法生成克隆人声。")  # noqa: E501
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
            QMessageBox.warning(self.parent_widget, "未上传声音样本", "请先上传/选择参考声音样本 (wav/mp3)！")  # noqa: E501
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")  # noqa: E501
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

        out_wav_path = os.path.abspath(os.path.join(out_montage_dir, "voices", f"voice_{row_idx + 1}.wav"))  # noqa: E501
        tasks = [(row_idx, text, video_path, out_wav_path)]

        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.text().strip(),
            voice_mode="api",
            voice_api_url=self.api_url_input.text().strip(),
            voice_cli_checkpoint="",
            temp_dir=out_montage_dir,
            inference_timesteps=self.tts_steps_spin.value() if hasattr(self, "tts_steps_spin") else 10,  # noqa: E501
            cfg_value=self.tts_cfg_spin.value() if hasattr(self, "tts_cfg_spin") else 2.0,  # noqa: E501
            speed_min=self.tts_speed_min_spin.value() if hasattr(self, "tts_speed_min_spin") else 0.9,  # noqa: E501
            speed_max=self.tts_speed_max_spin.value() if hasattr(self, "tts_speed_max_spin") else 1.2,  # noqa: E501
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.voice_worker.row_progress.connect(self._on_row_progress)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()
    # ==================== CONTROLLER RUN WORKERS ====================

    # --- Step 1 single video split ---
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
            if end_sec <= start_sec:
                # scenes 缺失/全 0（如 cv2 读不出时长）时，保留文件名里已有的有效时间戳
                parsed_ts = self._parse_split_filename(filename)
                if parsed_ts:
                    _s = self._srt_ts_to_seconds(parsed_ts[1])
                    _e = self._srt_ts_to_seconds(parsed_ts[2])
                    if _s is not None and _e is not None and _e > _s:
                        start_sec, end_sec = _s, _e
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
                except OSError as e:
                    log.warning(f"Failed to rename split file {filename}: {e}")
    # [3·分割]  _on_split_error
    def _on_split_error(self, err):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self._check_split_clips_exist()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("失败： 运行失败")
        self._show_long_error("运行错误", f"处理过程中发生错误：\n{err}")

    # --- Step 1 batch "pick best N seconds" highlights ---
    # [3·分割]  _start_pick_highlights
    def _start_pick_highlights(self):
        ctrl = getattr(getattr(self, "step1", None), "controller", None)
        split_running = bool(ctrl and ctrl.worker and ctrl.worker.isRunning())
        hl_running = bool(ctrl and ctrl.highlight_worker and ctrl.highlight_worker.isRunning())  # noqa: E501
        batch_hl_running = bool(getattr(self, "highlight_worker", None) and self.highlight_worker.isRunning())  # noqa: E501
        if split_running or hl_running or batch_hl_running:
            QMessageBox.warning(self.parent_widget, "任务进行中",
                                "上一个任务仍在运行中，请等待完成或先停止。")
            return

        paths = []
        for i in range(self.video_list.count()):
            if self._is_local_file_item(self.video_list.item(i)):
                paths.append(self.video_list.item(i).text().strip())
        if not paths:
            QMessageBox.warning(self.parent_widget, "无视频", "上方列表中没有可本地分割的视频（素材检索地址素材将直用于服务端拼接）。")  # noqa: E501
            return

        dur = self.spin_highlight_sec.value()

        # 同型号的多个视频，精华片段统一放进一个共享 splits 目录，便于下一步组合混剪。
        # 任务缓存已创建时写入 <缓存目录>/montage_cache/<job_id>/splits/highlights/，
        # 否则退回旧式「扫描目录/splits」（与下方表格读取位置一致）。
        self._ensure_montage_job()
        sp_root = self._montage_splits_root()
        if sp_root:
            shared_splits = os.path.join(sp_root, "highlights")
        else:
            shared_root = self.folder_path_input.text().strip()
            if not shared_root or not os.path.isdir(shared_root):
                try:
                    shared_root = os.path.commonpath([os.path.dirname(p) for p in paths])  # noqa: E501
                except (ValueError, TypeError):
                    shared_root = os.path.dirname(paths[0])
                # 同步扫描目录框，保证下方表格读取的 splits 与写入位置一致
                self.folder_path_input.setText(shared_root)
            shared_splits = os.path.join(shared_root, "splits")
        self._last_merged_splits_dirs = [shared_splits]

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
                    with contextlib.suppress(OSError):
                        os.remove(os.path.join(shared_splits, f))
        except OSError as e:
            QMessageBox.warning(self.parent_widget, "无法准备目录", f"创建/清理 splits 目录失败：\n{e}")  # noqa: E501
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
        # 把精华片段同步进 manifest（派生片段条目）
        self._sync_manifest_local_clips()

        msg = (f"批量挑精华完成：成功 {self._hl_ok} 个，失败 {self._hl_fail} 个"
               f"（共 {self._hl_total}）。")
        detail = msg
        if self._hl_fail_msgs:
            detail += "\n\n失败明细：\n" + "\n".join(self._hl_fail_msgs[:8])

        self.stage_label.setText("完成： " + msg + " 正在评分...")
        self.progress_bar.setRange(0, 0)
        self._pending_dialog = ("批量挑精华完成", detail)

        # Trigger vision analysis on highlight clips
        if self._hl_ok > 0 and os.path.exists(self._hl_shared_splits):
            files = sorted([f for f in os.listdir(self._hl_shared_splits)
                           if f.lower().endswith((".mp4", ".m4v"))])
            scenes = self._get_split_scenes_times(self._hl_shared_splits, files) if files else []  # noqa: E501
            self._trigger_vision_on_dir(self._hl_shared_splits, scenes, "批量挑精华")

    # [4·文案脚本]  _trigger_vision_on_dir
    def _trigger_vision_on_dir(self, splits_dir, scenes, source_label="镜头分割"):
        """对指定 splits 目录中的所有片段运行视觉AI画面分析。

        供批量分割、批量挑精华等批量路径复用。
        """
        if not os.path.exists(splits_dir):
            return

        files = sorted([f for f in os.listdir(splits_dir)
                       if f.lower().endswith((".mp4", ".m4v"))])
        if not files:
            return

        split_video_paths = [os.path.join(splits_dir, f) for f in files]

        # 方案B：服务端 /montage/split 已返回 description（已写入 split_descriptions/缓存），
        # 服务端 LLM 视觉接口（/llm/chat/completions，客户端本地只抽帧）仅对仍无描述的片段兜底，避免重复调用大模型
        missing = [p for p in split_video_paths
                   if not (self.split_descriptions.get(os.path.abspath(p)) or "").strip()]  # noqa: E501
        if not missing:
            log.info(f"[{source_label}] 全部片段已有画面描述（来自服务端分析），跳过 LLM 视觉描述")
            return
        split_video_paths = missing

        # Try to find SRT for the parent video
        raw_srt = ""
        srt_segments = []
        parent_dir = os.path.dirname(splits_dir)
        if parent_dir:
            for f_name in os.listdir(parent_dir):
                if f_name.endswith(".srt"):
                    srt_path = os.path.join(parent_dir, f_name)
                    try:
                        with open(srt_path, encoding="utf-8") as sf:
                            raw_srt = sf.read().strip()
                        if raw_srt:
                            srt_segments = parse_srt(raw_srt)
                        break
                    except OSError:
                        pass

        status_msg = f" 正在使用服务端视觉AI分析{source_label}画面内容..."
        if srt_segments:
            status_msg += "（结合字幕）"
        self.stage_label.setText(status_msg)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        # Save scenes for the finished handler
        self._trigger_scenes = scenes
        self._trigger_splits_dir = splits_dir

        self.vision_desc_worker = LocalVisionDescWorker(
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
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            log.warning(f"_on_trigger_vision_finished - JSON解析失败: {e}")
            desc_dict = {}

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("完成： 画面文案描述生成完毕！（服务端视觉AI）")

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
        self.stage_label.setText("失败： 画面描述生成失败")
        log.warning(f"大模型批量画面描述生成失败: {err}")
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        if video_path:
            splits_dir = self._montage_per_video_splits_dir(video_path)
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
                self._play_video(path)
    # [8·事件回调]  _on_table_cell_changed
    def _on_table_cell_changed(self, row, col):
        if col == 6:  # 主要画面列（可编辑）
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
                    new_path = self._get_renamed_path(old_path, row + 1, start_sec, end_sec, new_desc)  # noqa: E501
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
                                self.split_clips_cache[new_path] = self.split_clips_cache.pop(old_path)  # noqa: E501
                            self.split_result_table.blockSignals(False)
                            log.info(f"Renamed edited split file: {os.path.basename(old_path)} -> {os.path.basename(new_path)}")  # noqa: E501
                        except (OSError, KeyError, TypeError, ValueError) as e:
                            self.split_result_table.blockSignals(False)
                            log.warning(f"Failed to rename edited split file: {e}")
                    else:
                        self.split_descriptions[old_path] = new_desc
                    if hasattr(self, "rewritten_srt_display"):
                        lines = []
                        for r in range(self.split_result_table.rowCount()):
                            d_item = self.split_result_table.item(r, 6)
                            if d_item:
                                lines.append(d_item.text().strip())
                        self.rewritten_srt_display.setPlainText("\n".join(lines))
                    self._save_split_srt()

    # --- Step 1 subtitle generation execution ---
    # [4·文案脚本]  _start_transcribe_raw
    def _start_transcribe_raw(self):
        if hasattr(self, "transcribe_raw_worker") and self.transcribe_raw_worker and self.transcribe_raw_worker.isRunning():  # noqa: E501
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

        # 远程 ASR 模式：需配置 ASR 服务地址
        from utils.asr_client import read_asr_url
        asr_url = read_asr_url()
        if not asr_url:
            QMessageBox.warning(
                self.parent_widget,
                "未配置 ASR 服务",
                "未配置远程 ASR 服务地址，无法进行语音转写。\n"
                "请在系统设置中填写 Whisper API 地址或计算服务地址。"
            )
            return

        video_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        video_workspace_dir = os.path.join(video_dir, video_basename)
        os.makedirs(video_workspace_dir, exist_ok=True)

        # Subtitle output in the workspace directory
        output_srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")

        self.btn_split.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定进度（远程转写无逐帧进度）
        self.stage_label.setText("正在调用远程 ASR 转写视频音频...")

        # 远程 ASR worker：transcribe_remote → segments → 写 SRT
        class RemoteTranscribeWorker(BaseWorker):
            finished = Signal(str, str)   # srt_content, srt_path
            error = Signal(str)

            def __init__(self, video_path, srt_path):
                super().__init__()
                self.video_path = video_path
                self.srt_path = srt_path

            def do_work(self):
                try:
                    from utils.asr_client import segments_to_srt, transcribe_remote
                    segments = transcribe_remote(
                        self.video_path, asr_url,
                        language="",
                    )
                    srt_content = segments_to_srt(segments)
                    with open(self.srt_path, "w", encoding="utf-8") as f:
                        f.write(srt_content)
                    self.finished.emit(srt_content, self.srt_path)
                except Exception as e:  # 远程ASR转写失败
                    self.error.emit(str(e))

        self.transcribe_raw_worker = RemoteTranscribeWorker(video_path, output_srt_path)

        self.transcribe_raw_worker.finished.connect(self._on_transcribe_raw_finished)
        self.transcribe_raw_worker.error.connect(self._on_transcribe_raw_error)
        self.transcribe_raw_worker.start()
    # [4·文案脚本]  _on_transcribe_raw_finished
    def _on_transcribe_raw_finished(self, srt_content, srt_path):
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

        self.pending_srt_path = srt_path
        self.raw_unpunctuated_srt = srt_content

        if llm_model and srt_content.strip():
            self.stage_label.setText(" 正在使用 AI 模型自动优化字幕标点符号...")
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
            self._finalize_transcribe_raw(srt_punctuated, self.pending_srt_path, info_msg=" (AI标点已优化)")  # noqa: E501
        except OSError as e:
            log.warning(f"保存AI优化后的字幕失败: {e}")
            self._finalize_transcribe_raw(self.raw_unpunctuated_srt, self.pending_srt_path)  # noqa: E501
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
        self.stage_label.setText(f"完成： 字幕生成完成{info_msg}")
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
        self.stage_label.setText("失败： 字幕生成失败")
        self._show_long_error(
            "字幕生成错误",
            f"处理过程中发生错误：\n{err}")
    # [4·文案脚本]  _transcription_deps_ok
    def _transcription_deps_ok(self):
        # 纯远程 ASR 模式：转写由远程服务完成，不再依赖本地 torch / whisperx。
        return True


    # --- Step 2 Concat execution ---
    # [5·拼接合成]  _start_assemble_video
    def _start_assemble_video(self):
        if self.concat_worker and self.concat_worker.isRunning():
            return

        # 防止上一次预合成方案线程未结束时再次点击导致重复启动/GC
        if getattr(self, "_plan_worker", None) and self._plan_worker.isRunning():
            return

        if not self.split_clips_list:
            QMessageBox.warning(self.parent_widget, "无可排列镜头",
                                "当前没有勾选任何镜头，无法执行镜头重组。\n\n"
                                "可能原因：镜头评分低于筛选阈值，已被自动取消勾选。\n"
                                "解决方法：在上方镜头列表中手动勾选镜头，或降低评分筛选阈值后重新过滤。")
            return

        dir_path = self._concat_src_dir()
        if not dir_path or not os.path.exists(dir_path):
            dir_path = self.folder_path_input.text().strip()

        if not dir_path:
            QMessageBox.warning(self.parent_widget, "路径无效", "请先选择素材目录或待排列镜头目录。")
            return

        out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        self._pending_out_montage_dir = out_montage_dir

        logic = self.logic_combo.currentData() if hasattr(self, "logic_combo") else "random"  # noqa: E501

        # ──  按文案智能匹配：先用 LLM 为每行文案匹配最贴合的镜头，再按行序拼接 ──
        if logic == "script":
            script_text = self.match_script_edit.toPlainText().strip() if hasattr(self, "match_script_edit") else ""  # noqa: E501
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
                          if not self.split_descriptions.get(os.path.abspath(c), "").strip()  # noqa: E501
                          and not self.split_descriptions.get(c, "").strip())
            if no_desc == len(self.split_clips_list):
                QMessageBox.warning(self.parent_widget, "镜头无画面描述",
                                    "勾选的镜头都没有画面描述，无法做语义匹配。\n"
                                    "请先在「镜头分割」步骤生成画面描述文案。")
                return

            self.btn_assemble_video.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.stage_label.setText(" 正在用大模型为每句文案匹配最贴合的镜头...")

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

        # ── 随机洗牌：生成预合成方案（后台线程，避免镜头本地分析阻塞 UI）──
        target_clip_count = len(self.split_clips_list)

        batch_count = int(self.batch_count_spin.value())
        randomness_val = self.randomness_combo.currentData() if hasattr(self, "randomness_combo") else "medium"  # noqa: E501
        duration_limit = int(self.duration_limit_combo.currentData()) if hasattr(self, "duration_limit_combo") else 30  # noqa: E501

        # _build_precompose_plans 对每个镜头做 hash/质量/时长分析（本地打开视频，
        # 每镜头约 1 秒），在 UI 线程同步执行会卡死界面（按钮点了没反应）。
        # 移到后台线程，完成后再加载方案。
        self.btn_assemble_video.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.stage_label.setText(f"正在生成预合成方案（分析 {target_clip_count} 个镜头）…")
        from utils.thread_worker import TaskWorker as _PlanWorker
        _clips = list(self.split_clips_list)
        _bc = batch_count
        _rv = randomness_val
        _dl = duration_limit
        _tc = target_clip_count
        _out_dir = out_montage_dir
        # 景别映射必须在主线程预取（_shot_type_for_clip 要读 video_list 控件），
        # 后台线程只做纯计算
        _st = self._collect_clip_shot_types(_clips)

        def _plan_work():
            return self._build_precompose_plans(
                clips=_clips,
                target_clip_count=_tc,
                batch_count=_bc,
                randomness=_rv,
                duration_limit_sec=_dl,
                shot_types=_st,
            )

        def _plan_done(plan_clips_list):
            self.btn_assemble_video.setEnabled(True)
            self.progress_bar.setVisible(False)
            if not plan_clips_list:
                QMessageBox.warning(self.parent_widget, "未生成方案", "未能生成预合成方案，请检查是否已勾选镜头。")  # noqa: E501
                return
            self._load_precompose_plans(plan_clips_list, _out_dir)
            self.stage_label.setText(f"完成： 预合成方案已生成：{len(plan_clips_list)} 条，请检查后确认合成")
            QMessageBox.information(
                self.parent_widget,
                "预合成完成",
                f"已生成 {len(plan_clips_list)} 条预合成方案。\n"
                "可在下方删除/调序镜头，确认无误后点击“确认合成视频”。"
            )

        def _plan_err(e):
            self.btn_assemble_video.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.stage_label.setText("失败： 预合成方案生成失败")
            self._show_long_error("生成方案失败", str(e))

        self._plan_worker = _PlanWorker(_plan_work)
        self._plan_worker.finished.connect(_plan_done, type=Qt.QueuedConnection)
        self._plan_worker.error.connect(_plan_err, type=Qt.QueuedConnection)
        self._plan_worker.start()
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
        self.stage_label.setText(f" 匹配完成：{len(matched_paths)} 句文案已配齐，请确认合成")
        self.progress_bar.setVisible(False)
    # [4·文案脚本]  _on_script_match_error
    def _on_script_match_error(self, err):
        self.btn_assemble_video.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("失败： 文案镜头匹配失败")
        self._show_long_error("智能匹配失败",
                             f"大模型匹配文案与镜头时出错：\n{err}\n\n可切换回「随机洗牌」模式继续。")
    # [5·拼接合成]  _launch_concat_worker
    def _launch_concat_worker(self, selected_clips, out_montage_dir, recombine_mode,
                              target_clip_count, batch_count, randomness,
                              selected_descriptions_list=None,
                              beat_times=None, music_path="", music_range=None):
        """入口：根据开关决定走服务端合成还是本地合成。"""
        self.btn_assemble_video.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        if self.USE_SERVER_CONCAT:
            self._submit_concat_to_server(
                selected_clips=selected_clips,
                out_montage_dir=out_montage_dir,
                recombine_mode=recombine_mode,
                target_clip_count=target_clip_count,
                batch_count=batch_count,
                randomness=randomness,
                selected_descriptions_list=selected_descriptions_list,
                beat_times=beat_times,
                music_path=music_path,
                music_range=music_range,
            )
        else:
            self._launch_local_concat_worker(
                selected_clips=selected_clips,
                out_montage_dir=out_montage_dir,
                recombine_mode=recombine_mode,
                target_clip_count=target_clip_count,
                batch_count=batch_count,
                randomness=randomness,
                selected_descriptions_list=selected_descriptions_list,
                beat_times=beat_times,
                music_path=music_path,
                music_range=music_range,
            )

    def _launch_local_concat_worker(self, selected_clips, out_montage_dir, recombine_mode,  # noqa: E501
                                      target_clip_count, batch_count, randomness,
                                      selected_descriptions_list=None,
                                      beat_times=None, music_path="", music_range=None):
        """本地 ffmpeg 合成（fallback）。"""
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
            transition=self.transition_combo.currentData() if hasattr(self, "transition_combo") else "fade",  # noqa: E501
            beat_times=beat_times,
            music_path=music_path,
            music_range=music_range,
            lut_path=self._get_selected_lut_path(),
        )
        self.concat_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.concat_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.concat_worker.finished.connect(self._on_concat_finished)
        self.concat_worker.error.connect(self._on_concat_error)
        self.concat_worker.start()

    def _probe_first_clip_resolution(self, clips):
        """探测第一个有效镜头的显示分辨率（已考虑旋转），用于 layout_mode=source 时回传给服务端。

        服务端 montage_concat 只认 width/height，不认 layout_mode，所以 source 模式
        需要客户端主动把第一个镜头的宽高传过去，才能保持"与原视频一致"的行为。
        注意：手机竖拍视频 stream 存的是横屏像素（如 1920x1080），但带 rotate=90 元数据，
        必须读取旋转角度后交换宽高，才能得到正确的显示分辨率。
        """
        for clip in clips:
            if not os.path.isfile(clip):
                continue
            try:
                ffprobe = find_ffmpeg().replace("ffmpeg", "ffprobe")
                cmd = [
                    ffprobe, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,side_data_list,tag:rotate",
                    "-of", "json",
                    clip,
                ]
                r = run(
                    cmd, capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW, timeout=15,
                )
                if r.returncode == 0 and r.stdout.strip():
                    import json as _json
                    data = _json.loads(r.stdout)
                    streams = data.get("streams", [])
                    if not streams:
                        continue
                    s = streams[0]
                    w = int(s.get("width", 0) or 0)
                    h = int(s.get("height", 0) or 0)
                    if w <= 0 or h <= 0:
                        continue
                    # 检测旋转角度：优先从 side_data 读，回退到 tag:rotate
                    rotation = 0
                    # side_data_list 中 displaymatrix 的 rotation 字段
                    for sd in (s.get("side_data_list") or []):
                        rot_val = sd.get("rotation")
                        if rot_val is not None:
                            try:
                                rotation = int(float(rot_val))
                            except (TypeError, ValueError):
                                pass
                            break
                    if rotation == 0:
                        tag_rot = s.get("tags", {}).get("rotate")
                        if tag_rot:
                            try:
                                rotation = int(float(tag_rot))
                            except (TypeError, ValueError):
                                pass
                    # 90/270 度旋转时交换宽高
                    if rotation in (90, -90, 270, -270):
                        w, h = h, w
                    return w, h
            except (OSError, subprocess.SubprocessError, Exception):
                pass
        return 0, 0

    def _dedup_concat_clips(self, clips):
        """提交前过滤重复镜头：同路径 / 同大小+内容指纹。

        服务端 /montage/concat 对内容完全相同的片段会拒绝/失败
        （实测任务 progress=45 失败）；客户端先在本地抛掉明显重复项。
        返回 (deduped_list, dropped_count)。
        """
        import hashlib
        seen_paths = set()
        seen_fp = {}
        out = []
        dropped = 0
        for c in clips or []:
            p = os.path.abspath(c)
            if p in seen_paths:
                dropped += 1
                continue
            seen_paths.add(p)
            fp = None
            if os.path.isfile(p):
                try:
                    size = os.path.getsize(p)
                    h = hashlib.md5()
                    _SAMPLE = 256 * 1024  # noqa: N806
                    with open(p, "rb") as f:
                        if size <= _SAMPLE * 2:
                            h.update(f.read())
                        else:
                            h.update(f.read(_SAMPLE))
                            f.seek(-_SAMPLE, os.SEEK_END)
                            h.update(f.read(_SAMPLE))
                    fp = f"{size}|{h.hexdigest()}"
                except OSError:
                    fp = None
            if fp is not None:
                if fp in seen_fp:
                    dropped += 1
                    continue
                seen_fp[fp] = p
            out.append(c)
        return out, dropped

    def _submit_concat_to_server(self, selected_clips, out_montage_dir, recombine_mode,
                                 target_clip_count, batch_count, randomness,
                                 selected_descriptions_list=None,
                                 beat_times=None, music_path="", music_range=None):
        """提交镜头合成任务到服务端 montage_concat 执行器。

        严格对齐 /guide 2.10 镜头拼接（montage_concat）接口：
          - POST /montage/concat（multipart/form-data），同时上传 files / lut(可选) / 参数
          - options 只包含文档列出的字段，避免传 layout_mode / output_dir / audio_fade 等
            服务端可能不认识或误用的字段。
          - 转场名称按服务端支持列表做安全映射。
          - source 模式由本地上传第一个镜头的分辨率，不再传 0x0。
        """
        # 过滤重复镜头（同路径/同内容），避免服务端 concat 拒绝
        selected_clips, _dropped = self._dedup_concat_clips(selected_clips)
        if _dropped:
            log.info(f"[montage_concat] 已过滤 {_dropped} 个重复镜头，剩余 {len(selected_clips)} 个")  # noqa: E501
            self.stage_label.setText(f"注意： 已过滤 {_dropped} 个重复镜头，剩余 {len(selected_clips)} 个")  # noqa: E501

        # 构建输出文件名
        filename = f"montage_concat_server_{random.randint(1000, 9999)}_{batch_count}.mp4"  # noqa: E501
        local_output_path = os.path.join(out_montage_dir, filename)

        layout_mode = self.layout_combo.currentData() if hasattr(self, "layout_combo") else "vertical"  # noqa: E501
        transition = self.transition_combo.currentData() if hasattr(self, "transition_combo") else "fade"  # noqa: E501
        lut_path = self._get_selected_lut_path() if hasattr(self, "_get_selected_lut_path") else ""  # noqa: E501

        # 服务端支持的转场名称与 UI 的 xfade 命名略有差异，做安全映射；
        # 若遇到未列出的转场，回退到 fade 以避免服务端 422 / 本地回退导致假死。
        SERVER_TRANSITION_MAP = {  # noqa: N806
            "fade": "fade",
            "dissolve": "dissolve",
            "slideleft": "wipeleft",
            "slideright": "wiperight",
            "slideup": "slideup",
            "slidedown": "slidedown",
            "zoomin": "circleopen",
            "zoomout": "radial",
            "none": "none",
        }
        server_transition = SERVER_TRANSITION_MAP.get(transition, "fade")
        if server_transition != transition:
            log.info(f"[montage_concat] 转场名称映射：{transition} -> {server_transition}")

        # 输出分辨率：按接口文档只传 width/height，不再传 layout_mode
        width, height = 1080, 1920
        if layout_mode == "horizontal":
            width, height = 1920, 1080
        elif layout_mode == "source":
            # 优先使用服务端分割时返回的原片分辨率，回退到本地探测
            src_res = getattr(self, "_source_resolution", None)
            if src_res and isinstance(src_res, (list, tuple)) and len(src_res) == 2:
                width, height = int(src_res[0]), int(src_res[1])
            elif src_res and isinstance(src_res, str) and "x" in src_res:
                parts = src_res.split("x")
                if len(parts) == 2:
                    width, height = int(parts[0]), int(parts[1])
            else:
                width, height = self._probe_first_clip_resolution(selected_clips)
            if width <= 0 or height <= 0:
                width, height = 1080, 1920

        # 服务端 /montage/concat 只支持这些参数，且通过 multipart 同镜头一起上传
        options = {
            "transition": server_transition,
            "transition_duration": 0.5,
            "width": width,
            "height": height,
            "fps": 30,
            "crf": 23,
            "preset": "superfast",
        }

        # 字幕烧制与字体偏好：随 options 全量摊平进 multipart form（见
        # montage_concat_server_worker._submit_concat 的 {k: str(v) ...}）。
        # 服务端目前尚未声明这些字段，多传会被 FastAPI 忽略；按
        # docs/服务端字幕烧制与字体参数需求.md 加好后即自动生效。
        _font_id, _font_name = self._selected_subtitle_font()
        options["burn_subtitle"] = bool(
            getattr(self, "chk_add_subtitles", None) and self.chk_add_subtitles.isChecked())
        if _font_id:
            options["font_id"] = _font_id
        if _font_name:
            options["fontname"] = _font_name

        # 景别标注：随 options 摊平为 form 字段 clip_shot_types（JSON：文件名→景别），
        # 服务端按 docs/服务端景别分类与镜头编排需求.md 实现编排/加速后即生效；
        # 未支持时 FastAPI 忽略该字段，不影响现有合成。
        try:
            _st_payload = {
                os.path.basename(c): self._shot_type_for_clip(c)
                for c in selected_clips if c
            }
            if any(_st_payload.values()):
                options["clip_shot_types"] = json.dumps(_st_payload, ensure_ascii=False)
        except (OSError, ValueError, TypeError) as _e:
            log.warning(f"[montage_concat] 景别标注生成失败（忽略）: {_e}")

        # 出入场加速倍速（服务端字段 edge_speedup）：仅当用户选择加速时发送。
        # 服务端只对 clip_shot_types 里 entrance/exit 的片段应用 setpts/atempo；
        # 未启用景别标注时发送该字段无效果（无入口可判定哪些片段加速）。
        _edge_speed = self._selected_edge_speedup()
        if _edge_speed > 1.0:
            options["edge_speedup"] = _edge_speed

        # 卡点 / LUT 当前服务端接口不支持，回退本地处理
        if recombine_mode == "beat" and beat_times:
            self.stage_label.setText("注意： 卡点模式暂不支持服务端合成，回退到本地合成")
            self._launch_local_concat_worker(
                selected_clips=selected_clips,
                out_montage_dir=out_montage_dir,
                recombine_mode=recombine_mode,
                target_clip_count=target_clip_count,
                batch_count=batch_count,
                randomness=randomness,
                selected_descriptions_list=selected_descriptions_list,
                beat_times=beat_times,
                music_path=music_path,
                music_range=music_range,
            )
            return

        if not stc._server_url():
            self.stage_label.setText(" 未配置服务端地址，回退到本地合成")
            self._launch_local_concat_worker(
                selected_clips=selected_clips,
                out_montage_dir=out_montage_dir,
                recombine_mode=recombine_mode,
                target_clip_count=target_clip_count,
                batch_count=batch_count,
                randomness=randomness,
                selected_descriptions_list=selected_descriptions_list,
                beat_times=beat_times,
                music_path=music_path,
                music_range=music_range,
            )
            return

        self.stage_label.setText(" 正在上传镜头并提交服务端合成...")
        # 素材清单（manifest）是唯一数据源：server 条目提供 clip_urls（material://）
        clip_urls = self._manifest_clip_urls()
        if clip_urls:
            self.stage_label.setText(f" 正在提交服务端合成（本地镜头 {len(selected_clips)} 个 + 素材检索地址 {len(clip_urls)} 个）...")  # noqa: E501

        # 保存本地回退所需参数（服务端 402 等异常时自动回退）
        self._server_concat_fallback_params = {
            "selected_clips": list(selected_clips),
            "out_montage_dir": out_montage_dir,
            "recombine_mode": recombine_mode,
            "target_clip_count": target_clip_count,
            "batch_count": batch_count,
            "randomness": randomness,
            "selected_descriptions_list": selected_descriptions_list,
            "beat_times": beat_times,
            "music_path": music_path,
            "music_range": music_range,
        }

        self.concat_worker = MontageConcatServerWorker(
            local_output_path=local_output_path,
            clips=list(selected_clips),
            options=options,
            lut_path=lut_path,
            source_clips=list(selected_clips),
            clip_urls=clip_urls,
        )
        self.concat_worker.stage.connect(lambda t: self.stage_label.setText(t), type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.progress.connect(lambda v: self.progress_bar.setValue(v), type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.concat_finished.connect(lambda p: self._on_concat_finished([p]), type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.error.connect(self._on_concat_error, type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.task_id_obtained.connect(self._on_concat_task_id, type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.fallback_to_local.connect(self._on_server_concat_fallback, type=Qt.QueuedConnection)  # noqa: E501
        self.concat_worker.start()


    # [8·事件回调]  _on_logic_combo_changed
    def _on_logic_combo_changed(self):
        logic = self.logic_combo.currentData() if hasattr(self, "logic_combo") else "random"  # noqa: E501
        is_script = (logic == "script")

        # 智能匹配模式：镜头数量由文案行数决定；每批结果相同故固定生成 1 个
        self.lbl_batch_count.setVisible(not is_script)
        self.batch_count_spin.setVisible(not is_script)

        # 时长限制：两种模式都展示（随机模式控制视频时长，文案模式控制生成文案时长）
        if hasattr(self, "lbl_duration_limit") and hasattr(self, "duration_limit_combo"):  # noqa: E501
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

        # 「生成口播文案」按钮：仅在随机洗牌模式下可见
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
        checked_clips: list[str] = []
        clip_descriptions: list[str] = []
        for path in self.split_clips_list:
            norm_path = os.path.abspath(path)
            checked_clips.append(norm_path)
            # 获取描述：先查 split_descriptions，再查缓存
            desc = self.split_descriptions.get(norm_path, "").strip()
            if not desc:
                cache = self.split_clips_cache.get(norm_path, {})
                desc = cache.get("desc", "").strip() if isinstance(cache, dict) else ""
            clip_descriptions.append(desc if desc else f"（镜头片段 {os.path.basename(norm_path)}）")  # noqa: E501

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
        duration_limit = int(self.duration_limit_combo.currentData()) if hasattr(self, "duration_limit_combo") else 30  # noqa: E501

        # 禁用按钮防止重复点击
        self.btn_gen_script.setEnabled(False)
        self.stage_label.setText(f" 正在根据 {len(clip_descriptions)} 个镜头素材生成口播文案（时长限制 {duration_limit} 秒）...")  # noqa: E501
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
        self.stage_label.setText("完成： AI 文案生成完成，可编辑后点击「镜头重组」进行智能匹配")

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
        self.stage_label.setText("失败： AI 文案生成失败")
        self._show_long_error("文案生成失败",
                             f"调用大模型生成文案时出错：\n{err}")
    # [5·拼接合成]  _on_concat_task_id
    def _on_concat_task_id(self, task_id):
        """服务端合成任务提交成功后，把服务端 task_id 记入 manifest。"""
        if not task_id:
            return
        if not getattr(self, "_montage_job_id", ""):
            return
        try:
            man = load_manifest(self._montage_job_id)
            man["concat_task_id"] = str(task_id)
            save_manifest(self._montage_job_id, man)
            self._montage_manifest = man
            log.info(f"[智能混剪] 已记录服务端合成任务 id={task_id} 到 manifest")
        except OSError as e:
            log.warning(f"记录服务端合成任务 id 到 manifest 失败: {e}")

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
                self.stage_label.setText(f"完成： 预合成 {idx + 1} 已确认合成")
                # 只更新该条列表项文字，避免整表刷新触发预览重载/卡死
                item = self.assembled_clips_list_widget.item(idx)
                if item is not None:
                    clip_count = len(plan.get("clips") or [])
                    confirmed = plan.get("confirmed") and bool(out_path)
                    status_txt = "已合成" if confirmed else "待确认"
                    file_text = os.path.basename(out_path) if out_path else f"{clip_count} 个镜头"  # noqa: E501
                    copy_preview = self._assembled_copy_preview(out_path) if out_path else ""  # noqa: E501
                    copy_mark = f"  {copy_preview}" if copy_preview else ""
                    item.setText(f"[{idx+1}] {file_text}  {status_txt}{copy_mark}")
                    item.setData(Qt.UserRole + 1, int(confirmed))
                self.current_precompose_index = idx
                self.assembled_video_path = out_path
                self.btn_next_to_step_3.setEnabled(bool(self._collect_assembled_paths()))  # noqa: E501
                if hasattr(self, "btn_batch_scene_copy"):
                    self.btn_batch_scene_copy.setEnabled(bool(self._collect_assembled_paths()))  # noqa: E501
                self._update_confirm_all_button()
                if getattr(self, "_confirm_queue", None):
                    QTimer.singleShot(0, self._confirm_next_in_queue)
                else:
                    QMessageBox.information(
                        self.parent_widget,
                        "确认合成成功",
                        f"预合成 {idx + 1} 已输出为视频：\n{out_path}"
                    )
            return

        self.stage_label.setText(f"完成： 批量排列完成，共生成 {len(paths)} 个视频！")
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
        self.stage_label.setText("失败： 排列失败")
        self._show_long_error("排列错误", f"处理过程中发生错误：\n{err}")
    # [5·拼接合成]  _on_server_concat_fallback
    def _on_server_concat_fallback(self, reason):
        """服务端合成不可用（402 等），自动回退到本地合成。"""
        log.info(f"[montage_concat] 服务端回退本地合成: {reason}")
        if self._selected_edge_speedup() > 1.0:
            reason += "（注意：本地回退合成不支持出入场加速，该设置在本次回退中不生效）"
        self.stage_label.setText(f"注意： {reason}")
        params = getattr(self, "_server_concat_fallback_params", None)
        if not params:
            self._on_concat_error("服务端回退本地合成，但缺少必要参数")
            return
        self._launch_local_concat_worker(**params)


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
        desc = QLabel("控制AI改写文案时的创造性程度：\n80-100% = 最小润色，保持原文字词句式不变\n50-79% = 较大幅度改写，使用不同表达方式，更有网感\n20-49% = 大幅重构，显著改变句式词汇\n0-19% = 彻底重写，完全不同的词句，最大化爆款潜力")  # noqa: E501
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
        self._freedom_value_label.setStyleSheet("font-weight: bold; color: #60a5fa; font-size: 14px;")  # noqa: E501
        self._freedom_value_label.setAlignment(Qt.AlignCenter)

        def on_slider_changed(val):
            self._freedom_value_label.setText(f"当前: {val}%")

        slider.valueChanged.connect(on_slider_changed)
        layout.addLayout(row_slider)
        layout.addWidget(self._freedom_value_label)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("background-color: transparent; color: #d1d5db; border: none;")  # noqa: E501
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
        if hasattr(self, "batch_rewrite_worker") and self.batch_rewrite_worker and self.batch_rewrite_worker.isRunning():  # noqa: E501
            return

        # 1. Check configs
        ai_config = getattr(self.main_window, "ai_config", {})
        model = ai_config.get("llm_model", "").strip()

        if not model:
            QMessageBox.warning(self.parent_widget, "未配置AI大模型", "请先在“设置”或“AI模型配置”中配置 LLM 模型名称。")  # noqa: E501
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
        self.batch_rewrite_worker = BatchAITextRewriteWorker("", "", model, tasks, self.ai_rewrite_temperature)  # noqa: E501
        self.batch_rewrite_worker.row_finished.connect(self._on_batch_rewrite_row_finished)  # noqa: E501
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
        self.stage_label.setText("完成： 一键AI修改全部文案完成！")
        QMessageBox.information(self.parent_widget, "成功", "批量AI文案修改润色完成！")
    # [4·文案脚本]  _on_batch_rewrite_error
    def _on_batch_rewrite_error(self, err):
        self.btn_batch_ai_rewrite.setEnabled(True)
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.progress_bar.setValue(0)
        self.stage_label.setText("失败： AI修改文案失败")
        self._show_long_error("AI修改失败", f"批量修改失败：\n{err}")
    # [6·配音]  _start_synthesize_voice
    def _start_synthesize_voice(self):
        if self.voice_worker and self.voice_worker.isRunning():
            return

        ref_audio = self.ref_audio_combo.currentData() or ""
        if ref_audio == "custom":
            ref_audio = ""

        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未上传声音样本", "请先上传/选择参考声音样本 (wav/mp3)！")  # noqa: E501
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")  # noqa: E501
            return

        # 检查空闲显存是否足够运行 VoxCPM（约需 6GB），不足则停止 Ollama 释放
        try:
            r = run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],  # noqa: E501
                    capture_output=True, text=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW)
            free_mb = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 99999  # noqa: E501
            if free_mb < 6144:
                self.stage_label.setText(f"空闲显存 {free_mb}MB 不足，声音克隆可能失败...")
            else:
                self.stage_label.setText(f"空闲显存 {free_mb}MB 充足，开始声音克隆...")
        except (OSError, subprocess.SubprocessError) as e:
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
                    out_wav_path = os.path.abspath(os.path.join(out_montage_dir, "voices", f"voice_{i+1}.wav"))  # noqa: E501
                    tasks.append((i, text, video_path, out_wav_path))

        if not tasks:
            QMessageBox.warning(self.parent_widget, "文案为空", "没有检测到任何有配音文案的视频。请在表格的“配音文案”栏输入内容。")  # noqa: E501
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
            inference_timesteps=self.tts_steps_spin.value() if hasattr(self, "tts_steps_spin") else 10,  # noqa: E501
            cfg_value=self.tts_cfg_spin.value() if hasattr(self, "tts_cfg_spin") else 2.0,  # noqa: E501
            speed_min=self.tts_speed_min_spin.value() if hasattr(self, "tts_speed_min_spin") else 0.9,  # noqa: E501
            speed_max=self.tts_speed_max_spin.value() if hasattr(self, "tts_speed_max_spin") else 1.2,  # noqa: E501
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
        self.stage_label.setText("完成： 克隆人声音频生成完成！")

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
                f"注意： 合成完成：成功 {len(results)} 个，失败 {len(failures)} 个（已跳过）")
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
        self.stage_label.setText("失败： 合成失败")
        self._show_long_error("人声合成错误", f"处理过程中发生错误：\n{err}")
    # [6·配音]  服务端字体库（GET /config/fonts）
    def _refresh_server_fonts(self):
        """从服务端拉取字体列表填充「字幕字体」下拉框。

        必须在后台线程做：同步 HTTP 放在 UI 主线程会卡住界面（本项目已多次踩此坑）。
        失败/未配服务端地址时降级为空列表，不阻断配音与烧字幕流程。
        """
        combo = getattr(self, "subtitle_font_combo", None)
        if combo is None:
            return
        if self._fonts_worker is not None and self._fonts_worker.isRunning():
            return
        server_url = stc._server_url()
        if not server_url:
            self._populate_font_combo([])
            if self.stage_label:
                self.stage_label.setText("未配置服务端地址，字幕将使用默认字体")
            return

        keep_id = str(combo.currentData() or "")
        combo.setEnabled(False)
        if self.stage_label:
            self.stage_label.setText("正在从服务端加载字体列表…")

        from utils.montage_client import list_fonts
        from utils.thread_worker import TaskWorker

        def _done(fonts, _combo=combo, _keep=keep_id):
            try:
                _combo.setEnabled(True)
            except RuntimeError:  # 页面已销毁
                return
            self._populate_font_combo(fonts or [], keep_id=_keep)
            self._fonts_loaded = True
            n = len(self._server_fonts)
            if self.stage_label:
                self.stage_label.setText(
                    f"已从服务端加载 {n} 个字体" if n else "服务端未返回字体，字幕将使用默认字体")  # noqa: E501

        def _err(e):
            with contextlib.suppress(RuntimeError):
                combo.setEnabled(True)
            self._populate_font_combo([])
            log.warning(f"拉取服务端字体列表失败: {e}")
            if self.stage_label:
                self.stage_label.setText("拉取服务端字体失败，字幕将使用默认字体")

        self._fonts_worker = TaskWorker(list_fonts, server_url)
        self._fonts_worker.finished.connect(_done, type=Qt.QueuedConnection)
        self._fonts_worker.error.connect(_err, type=Qt.QueuedConnection)
        self._fonts_worker.start()

    def _populate_font_combo(self, fonts, keep_id=""):
        """把服务端字体写入下拉框：itemData 存 font_id，dict 放 _server_fonts_by_id。"""
        combo = getattr(self, "subtitle_font_combo", None)
        if combo is None:
            return
        self._server_fonts = [f for f in (fonts or []) if isinstance(f, dict)]
        self._server_fonts_by_id = {}
        items = [("默认（不指定字体）", "")]
        seen_family = set()
        for f in self._server_fonts:
            fid = str(f.get("id") or "").strip()
            family = str(f.get("family") or f.get("filename") or "").strip()
            if not fid or not family:
                continue
            self._server_fonts_by_id[fid] = f
            # 同族名多个字重/文件时追加文件名区分
            label = f"{family}（{f.get('filename')}）" if family in seen_family else family
            seen_family.add(family)
            items.append((label, fid))
        combo.setItems(items)
        idx = 0
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == (keep_id or ""):
                idx = i
                break
        combo.setCurrentIndex(idx)

    def _selected_subtitle_font(self):
        """返回当前选定的 (font_id, fontname)；未选或无列表时返回 ("", "")。"""
        combo = getattr(self, "subtitle_font_combo", None)
        if combo is None:
            return "", ""
        fid = str(combo.currentData() or "")
        if not fid:
            return "", ""
        f = self._server_fonts_by_id.get(fid) or {}
        return fid, str(f.get("family") or "")

    def _selected_edge_speedup(self):
        """UI 选中的出入场加速倍速（Step2 下拉框）；未初始化/异常回退 1.0=不加速。"""
        combo = getattr(self, "edge_speedup_combo", None)
        if combo is None:
            return 1.0
        try:
            return float(combo.currentData() or 1.0)
        except (TypeError, ValueError):
            return 1.0

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
        fancy_enabled = self.chk_fancy_text.isChecked() if hasattr(self, "chk_fancy_text") else False  # noqa: E501
        fancy_style = self.fancy_style_combo.currentData() if hasattr(self, "fancy_style_combo") else "gold"  # noqa: E501
        fancy_words = []
        if fancy_enabled and hasattr(self, "fancy_text_input"):
            raw = self.fancy_text_input.text().strip()
            if raw:
                fancy_words = [w.strip() for w in raw.replace("，", ",").split(",") if w.strip()]  # noqa: E501
        for vid, wav in self.generated_voice_paths.items():
            if os.path.exists(vid) and os.path.exists(wav):
                out_vid_name = f"dubbed_{os.path.basename(vid)}"
                out_vid_path = os.path.join(dubbed_dir, out_vid_name)

                # Retrieve matching script text from the voice table for this video
                text = ""
                for r in range(self.voice_table.rowCount()):
                    item_file = self.voice_table.item(r, 1)
                    if item_file and os.path.abspath(item_file.data(Qt.UserRole)) == os.path.abspath(vid):  # noqa: E501
                        edit = self.row_edits.get(r)
                        if edit:
                            text = edit.text().strip()
                        break

                tasks.append((vid, wav, out_vid_path, text))

        if not tasks:
            QMessageBox.warning(self.parent_widget, "缺少音频", "尚未生成任何对应的克隆人声音频。请先点击“开始批量克隆人声合成”进行合成。")  # noqa: E501
            return

        self.btn_synthesize_voice.setEnabled(False)
        self.btn_next_to_step_4.setEnabled(False)
        self.btn_dub_videos.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.dub_worker = VideoDubbingWorker(
            tasks, add_subtitles=add_subs, length_modes=self.voice_length_mode,
            fancy_text=fancy_enabled, fancy_style=fancy_style, fancy_words=fancy_words,
            subtitle_font=self._selected_subtitle_font()[1] if add_subs else "")
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
        self.stage_label.setText("完成： 替换视频原声配音完成！")

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
        self.stage_label.setText("失败： 配音替换失败")
        self._show_long_error("配音替换错误", f"替换配音过程中发生错误：\n{err}")


    # --- Step 4 Final mix helpers & execution ---
    # [7·混音导出]  _populate_default_mix_videos
    def _populate_default_mix_videos(self):
        self.mix_video_table.setRowCount(0)

        src_vids = []
        source_type = ""
        if self.dubbed_video_paths:
            src_vids = list(self.dubbed_video_paths.values())
            source_type = "已配音视频"
        else:
            dir_path = self.voice_video_dir_input.text().strip()
            if not dir_path:
                dir_path = self.folder_path_input.text().strip()
            if dir_path:
                out_montage_dir = self._get_out_montage_dir(dir_path)
                if os.path.exists(out_montage_dir):
                    src_vids = [os.path.join(out_montage_dir, f) for f in os.listdir(out_montage_dir)  # noqa: E501
                                if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"))]  # noqa: E501
                    source_type = "排列视频"

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
        btn_play_final.clicked.connect(lambda checked=False, path=filepath: self._play_video(path))  # noqa: E501
        action_layout.addWidget(btn_play_final)

        # Per-video BGM selection
        bgm_path = self.per_video_bgm.get(filepath, "")
        if bgm_path:
            btn_bgm = mdi_button("", "music")
            btn_bgm.setToolTip(f"已选: {os.path.basename(bgm_path)}\n点击更换")
            btn_bgm.setStyleSheet("padding: 0px; font-size: 11px; background-color: rgba(46,204,113,0.2);")  # noqa: E501
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
        path, _ = pick_file(
            self.parent_widget,
            "选择背景音乐",
            os.path.dirname(filepath) if os.path.exists(os.path.dirname(filepath)) else "",  # noqa: E501
            "Audio Files (*.mp3 *.wav *.m4a *.aac);;All Files (*)"
        )
        if path:
            self.per_video_bgm[filepath] = path
            button.setToolTip(f"已选: {os.path.basename(path)}\n点击更换")
            button.setStyleSheet("padding: 0px; font-size: 11px; background-color: rgba(46,204,113,0.2);")  # noqa: E501
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
        file_paths, _ = pick_files(
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

        target_height = header_height + total_rows_height + frame_width + margin_height + 4  # noqa: E501
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
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer

            # Stop general voice playback to prevent overlapping sounds
            if hasattr(self, "_media_player") and self._media_player:
                self._media_player.stop()
                from utils.wav_player import stop_wav
                stop_wav()

            # Set source if it's different or empty
            current_src = self._bgm_player.source().toLocalFile()
            if os.path.abspath(current_src) != os.path.abspath(bgm_path):
                self._bgm_player.setSource(QUrl.fromLocalFile(bgm_path))

            if self._bgm_player.playbackState() == QMediaPlayer.PlayingState:
                self._bgm_player.pause()
                # 图标切换，避免 setText 文字被窄按钮截断
                self.btn_bgm_play.setIcon(mdi_icon("play"))
            else:
                # 应用当前 BGM 增益（滑块 0-200%，/100 还原为 0-2.0 的增益系数）
                gain = self.bgm_volume_slider.value() / 100.0 if hasattr(self, "bgm_volume_slider") else 1.0  # noqa: E501
                self._bgm_audio_output.setVolume(gain)
                self._bgm_player.play()
                self.btn_bgm_play.setIcon(mdi_icon("pause"))
                self.btn_bgm_stop.setEnabled(True)
        except (OSError, RuntimeError) as e:
            log.error(f"播放背景音乐失败: {e}")
            QMessageBox.critical(self.parent_widget, "播放错误", f"播放背景音乐失败: {e}")
    # [7·混音导出]  _stop_bgm_play
    def _stop_bgm_play(self):
        try:
            self._bgm_player.stop()
            self.btn_bgm_play.setIcon(mdi_icon("play"))
            self.btn_bgm_stop.setEnabled(False)
            self.bgm_progress_slider.setValue(0)
            self.lbl_bgm_time.setText("00:00 / 00:00")
        except (OSError, RuntimeError) as e:
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
        # 兼容两种标签控件名：legacy 用 volume_label，step4 用 lbl_bgm_vol
        if hasattr(self, "volume_label") and self.volume_label:
            self.volume_label.setText(f"{value}%")
        if hasattr(self, "lbl_bgm_vol") and self.lbl_bgm_vol:
            self.lbl_bgm_vol.setText(f"{value} %")
        if hasattr(self, "_bgm_audio_output") and self._bgm_audio_output:
            self._bgm_audio_output.setVolume(value / 100.0)
    # [7·混音导出]  _start_final_mix
    def _collect_mix_candidates(self):
        """收集第④步待混音合成的视频列表。

        优先用第③步配音产生的 dubbed 视频（self.dubbed_video_paths）；
        若无，回退扫描 outputs 目录里的排列视频（montage_concat_*）。
        返回去重后的绝对路径列表（仅含实际存在的文件）。
        原 legacy mix_video_table 已随 Step4FinalView 重构移除，这里不依赖它。
        """
        tasks = []
        # 1) 优先：已配音视频
        dubbed = getattr(self, "dubbed_video_paths", None) or {}
        for p in dubbed.values():
            if p and os.path.exists(p):
                tasks.append(os.path.abspath(p))
        # 2) 回退：扫描 outputs 排列视频
        if not tasks:
            dir_path = ""
            if hasattr(self, "voice_video_dir_input"):
                dir_path = (self.voice_video_dir_input.text().strip() or "")
            if not dir_path and hasattr(self, "folder_path_input"):
                dir_path = self.folder_path_input.text().strip()
            if dir_path:
                try:
                    out_montage_dir = self._get_out_montage_dir(dir_path)
                    if os.path.isdir(out_montage_dir):
                        for f in os.listdir(out_montage_dir):
                            if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")):  # noqa: E501
                                fp = os.path.join(out_montage_dir, f)
                                if os.path.isfile(fp):
                                    tasks.append(os.path.abspath(fp))
                except OSError as e:
                    log.warning(f"扫描排列视频目录失败: {e}")
        # 去重（保持顺序）
        seen = set()
        unique = []
        for t in tasks:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    def _start_final_mix(self):
        if self.mix_worker and self.mix_worker.isRunning():
            return

        # 收集待合成视频：优先用第③步配音产生的 dubbed 视频，否则回退扫描 outputs 排列视频。
        # 原 legacy mix_video_table 已随 Step4FinalView 重构移除，这里直接收集，不再依赖它。
        tasks = self._collect_mix_candidates()
        if not tasks:
            QMessageBox.warning(self.parent_widget, "无待合成视频",
                "未找到待合成的视频。\n请先完成第③步「口播配音」生成配音视频，"
                "或确认第②步的排列视频已生成。")
            return

        first_vid = tasks[0]
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
        self.btn_export_jianying_all.setEnabled(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("完成： 最终合成视频完成！")

        self.final_video_list.clear()
        if paths:
            self.final_video_path = paths[0]
            for p in paths:
                self.final_video_list.addItem(os.path.basename(p))
                self.final_video_list.item(self.final_video_list.count() - 1).setData(Qt.UserRole, p)  # noqa: E501
        else:
            self.final_video_path = ""
    # [7·混音导出]  _on_mix_error
    def _on_mix_error(self, err):
        self.btn_final_assemble.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("失败： 合成失败")
        self._show_long_error("合成错误", f"处理过程中发生错误：\n{err}")
    # [9·其他]  _open_output_dir
    def _open_output_dir(self):
        if self.final_video_path:
            p = os.path.dirname(self.final_video_path)
            if os.path.exists(p):
                try:
                    os.startfile(p)
                except OSError as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", str(e))
    # [5·拼接合成]  _export_to_jianying_draft
    def _export_to_jianying_draft(self):
        """一键导出为剪映工程草稿（导出当前选中的单个视频）"""
        selected_item = self.final_video_list.currentItem()
        if not selected_item:  # noqa: SIM102
            # 默认取第一个
            if self.final_video_list.count() > 0:
                selected_item = self.final_video_list.item(0)

        if not selected_item:
            QMessageBox.warning(self.parent_widget, "未选中视频", "请先在合成列表中选择一个视频！")
            return

        video_path = selected_item.data(Qt.UserRole)
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"无法定位该视频的物理文件：\n{video_path}")  # noqa: E501
            return

        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        srt_path = self._find_srt_for_video(video_path)
        if not srt_path:
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
                f"混剪工程导出完成！\n\n项目名称：{draft_name}\n\n请直接打开您的电脑「剪映专业版」客户端进行精修编辑。\n系统已为您在资源管理器中定位到该草稿文件夹。"  # noqa: E501
            )
            # 打开对应的草稿文件夹
            with contextlib.suppress(OSError):
                os.startfile(result_path)
        else:
            self._show_long_error(
                "导出失败",
                f"导出剪映草稿时发生错误：\n{result_path}")

    # [7·混音导出]  _find_srt_for_video
    def _find_srt_for_video(self, video_path):
        """查找视频同目录下配套的 .srt 字幕文件（兼容 dubbed_/final_ 前缀）"""
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
            return None
        return srt_path

    # [7·混音导出]  _export_all_to_jianying_draft
    def _export_all_to_jianying_draft(self):
        """将合成列表中的所有视频按顺序导出为一条剪映时间轴（带转场 + 各自字幕）"""
        video_paths = []
        srt_paths = []
        for i in range(self.final_video_list.count()):
            it = self.final_video_list.item(i)
            p = it.data(Qt.UserRole) if it else None
            if p and os.path.exists(p):
                video_paths.append(p)
                srt_paths.append(self._find_srt_for_video(p))

        if not video_paths:
            QMessageBox.warning(self.parent_widget, "未选中视频", "合成列表为空，请先生成视频！")
            return

        # 转场类型沿用第 2 步「转场动画」下拉框的选择
        trans_combo = getattr(self, "transition_combo", None)
        transition = trans_combo.currentData() if trans_combo is not None else None
        if not transition:
            transition = "fade"

        # 获取 BGM 路径和音量
        bgm_path = self.bgm_input.text().strip()
        bgm_vol = self.bgm_volume_slider.value()

        from utils.jianying_exporter import JianyingExporter

        draft_name = f"螺丝钉剪辑_多片段时间轴({len(video_paths)}段)"
        success, result_path = JianyingExporter.export_multi_to_draft(
            video_paths=video_paths,
            transitions=transition,
            bgm_path=bgm_path,
            bgm_volume=bgm_vol,
            srt_paths=srt_paths,
            draft_name=draft_name
        )

        if success:
            QMessageBox.information(
                self.parent_widget,
                "草稿导出成功",
                f"已将 {len(video_paths)} 个片段导出为剪映时间轴（转场：{transition}）！\n\n"
                f"项目名称：{draft_name}\n\n"
                f"请直接打开您的电脑「剪映专业版」客户端进行精修编辑。\n"
                f"系统已为您在资源管理器中定位到该草稿文件夹。"
            )
            # 打开对应的草稿文件夹
            with contextlib.suppress(OSError):
                os.startfile(result_path)
        else:
            self._show_long_error(
                "导出失败",
                f"导出剪映草稿时发生错误：\n{result_path}")
    # [9·其他]  _preview_final_video
    def _preview_final_video(self, item):
        """双击最终视频列表：异步加载新源，避免同步 setSource 导致 Qt 卡死。"""
        path = item.data(Qt.UserRole)
        if not (path and os.path.exists(path)):
            return
        from PySide6.QtCore import QTimer, QUrl
        self._pending_final_preview_path = path
        try:
            self.final_preview_player.stop()
            # 先清空源，触发 NoMedia 后再加载新视频；同步 setSource 会导致 Qt 内部死锁/卡死
            self.final_preview_player.setSource(QUrl())
        except (OSError, RuntimeError) as e:
            log.warning(f"停止最终预览失败: {e}")
        # 兜底：部分 Qt 版本/文件占用下不触发 NoMedia，200ms 后主动加载
        if self._pending_final_preview_timer is not None:
            self._pending_final_preview_timer.stop()
        self._pending_final_preview_timer = QTimer.singleShot(200, self._on_final_preview_no_media)  # noqa: E501

    def _on_final_preview_no_media(self):
        """final_preview_player 源释放完成（NoMedia 或兜底定时器）后加载目标视频。"""
        try:
            import shiboken6 as _sb
            if not (_sb.isValid(self) and _sb.isValid(self.final_preview_player)):
                self._pending_final_preview_path = ""
                return
        except (ImportError, ModuleNotFoundError):
            self._pending_final_preview_path = ""
            return
        if self._pending_final_preview_timer is not None:
            self._pending_final_preview_timer.stop()
            self._pending_final_preview_timer = None
        path = getattr(self, "_pending_final_preview_path", "")
        self._pending_final_preview_path = ""
        if not path or not os.path.isfile(path):
            return
        from PySide6.QtCore import QUrl
        try:
            self.final_preview_title.setText(f"  {os.path.basename(path)}")
            self.final_preview_player.setSource(QUrl.fromLocalFile(path))
            self.final_preview_player.play()
        except (OSError, RuntimeError) as e:
            log.warning(f"最终视频预览加载失败: {e}")

    def _on_final_preview_media_status_changed(self, status):
        """监听 final_preview_player 的 NoMedia 信号，异步加载目标视频。"""
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.NoMedia:
                self._on_final_preview_no_media()
        except (ImportError, ModuleNotFoundError):
            pass

    def _run_batch_vision_descriptions(self, splits_dir, split_files, missing_only=None):  # noqa: E501
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
                except (ValueError, TypeError):
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
                        with open(os.path.join(parent_dir, f_name), encoding="utf-8") as sf:  # noqa: E501
                            raw_srt = sf.read().strip()
                        break
                    except OSError:
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
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                log.warning(f"解析批量画面描述失败: {e}")
            self.progress_bar.setValue(100)
            self._check_split_clips_exist()
            self.stage_label.setText("完成： 画面描述生成完成")
            QMessageBox.information(
                self.parent_widget, "描述生成完成",
                f"已为 {len(clip_paths)} 个镜头生成画面描述。")

        def on_desc_err(msg):
            log.warning(f"批量画面描述生成失败: {msg}")
            self.progress_bar.setValue(100)
            self.stage_label.setText("失败： 画面描述生成失败")
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
        splits_dir = self._montage_per_video_splits_dir(video_path)
        if not os.path.exists(splits_dir):
            QMessageBox.warning(self.parent_widget, "未分割镜头", "请先对当前视频进行镜头分割。")
            return

        files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])  # noqa: E501
        if not files:
            QMessageBox.warning(self.parent_widget, "无镜头文件", "分割目录中没有镜头片段文件。")
            return

        # 检查是否有字幕文件（优先查缓存工作目录，再回退源视频目录）
        video_workspace_dir = os.path.dirname(splits_dir)
        srt_path = os.path.join(video_workspace_dir, f"{video_basename}.srt")
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
            with open(srt_path, encoding="utf-8") as f:
                srt_content = f.read()
        except OSError as e:
            QMessageBox.warning(self.parent_widget, "读取字幕失败", f"无法读取字幕文件：\n{e}")
            return

        parsed_texts = parse_srt_to_descriptions(srt_content)
        if not parsed_texts:
            QMessageBox.warning(self.parent_widget, "字幕解析失败", "无法从字幕文件中解析出文本内容。")
            return

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
            self.stage_label.setText(f"字幕匹配完成，{len(missing_clips)} 个镜头未匹配到字幕，正在用视觉AI分析...")  # noqa: E501
            self._run_batch_vision_descriptions(splits_dir, files, missing_clips)
        else:
            self.stage_label.setText(f" 已为全部 {len(files)} 个镜头匹配字幕文案描述")
            QMessageBox.information(
                self.parent_widget, "描述生成完成",
                f"已从字幕匹配到 {updated_count} 个镜头的文案描述。")
    # [2·基础设施]  _get_compute_server_url
    def _get_compute_server_url(self):
        try:
            cfg = getattr(self.main_window, "ai_config", {}) or {}
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
        except (AttributeError, TypeError):
            pass
        try:
            import json as _json

            from config.paths import AI_CONFIG_FILE
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                    cfg = _json.load(f)
                return (cfg.get("compute_server_url") or "").strip().rstrip("/")
        except (OSError, json.JSONDecodeError):
            pass
        return ""
    # [3·分割]  _get_shot_cache_for_clip
    def _get_shot_cache_for_clip(self, clip_path):
        """根据镜头片段路径返回对应源视频的 ShotAnalysisCache（按需创建）。

        不再依赖文件名反推 vbase（片段会被 _rename_video_splits_with_metadata 重命名，
        反推的前缀可能与写入时的 vbase 不一致导致查不到）。改为：
        扫描 workspace 下所有 *_shots.json，逐个加载并用内容指纹（_clip_key）匹配，
        只要片段内容对得上就能命中，与文件名无关。
        """
        if not clip_path:
            return None
        try:
            from utils.shot_analysis_cache import ShotAnalysisCache, _clip_key
            clip_path = os.path.abspath(clip_path)
            clip_splits_dir = os.path.dirname(clip_path)
            clip_workspace_dir = os.path.dirname(clip_splits_dir)
            if not clip_workspace_dir or not os.path.isdir(clip_workspace_dir):
                return None
            # 目标片段的内容指纹（size|md5），不依赖文件名
            target_key = _clip_key(clip_path)
            # 工作区下所有 *_shots.json
            import glob as _glob
            cache_files = sorted(_glob.glob(os.path.join(clip_workspace_dir, "*_shots.json")))  # noqa: E501
            for cf in cache_files:
                cache_key = (clip_workspace_dir, os.path.basename(cf)[:-11])
                caches = getattr(self, "_shot_cache_pool", {})
                if cache_key not in caches:
                    caches[cache_key] = ShotAnalysisCache(clip_workspace_dir, os.path.basename(cf)[:-11])  # noqa: E501
                    self._shot_cache_pool = caches
                cache = caches[cache_key]
                if target_key in cache._items:
                    return cache
            # 未命中任何缓存文件：返回第一个（若无，返回 None）
            if cache_files:
                bname = os.path.basename(cache_files[0])[:-11]
                caches = getattr(self, "_shot_cache_pool", {})
                ck = (clip_workspace_dir, bname)
                if ck not in caches:
                    caches[ck] = ShotAnalysisCache(clip_workspace_dir, bname)
                    self._shot_cache_pool = caches
                return caches[ck]
            return None
        except (OSError, KeyError, TypeError) as e:
            log.warning(f"获取镜头分析缓存失败({clip_path}): {e}")
            return None

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
                    score = cache.get("score", None) if isinstance(cache, dict) else None  # noqa: E501
                    passed = (threshold <= 0 or score is None or score < 0 or score >= threshold)  # noqa: E501
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
        """点击下一步：从表格 checkbox 同步选中状态，再进入镜头重组。"""
        self._sync_step1_checkboxes_to_clips()
        self._detect_and_show_source_resolution()
        self._go_to_step(1)
    # [3·分割]  _sync_step1_checkboxes_to_clips
    def _sync_step1_checkboxes_to_clips(self):
        """从步骤1表格重建 _available_concat_clips 并同步勾选状态。

        多素材合并分割后，_scan_concat_src_dir 只能扫单个目录，会导致第②步
        只看到第一个视频的片段。这里直接从步骤1表格（已含全部合并片段）重建列表，
        确保进入第②步能看到全部勾选的镜头。
        """
        tbl = getattr(self, "split_result_table", None)
        if tbl is None:
            return
        # 先记录第②步里用户已手动勾选的（进入第②步后保留其选择）
        prev_checked = {c.get("path") for c in getattr(self, "_available_concat_clips", [])  # noqa: E501
                        if c.get("checked")}
        new_clips = []
        for r in range(tbl.rowCount()):
            chk_item = tbl.item(r, 0)
            file_item = tbl.item(r, 2)
            if not file_item:
                continue
            path = file_item.data(Qt.UserRole)
            if not path:
                continue
            cache = getattr(self, "split_clips_cache", {}).get(path, {})
            # 勾选状态：以步骤1表格为准；若第②步之前勾过也保留，避免来回切换丢勾选
            checked = (bool(chk_item) and chk_item.checkState() == Qt.Checked) or (path in prev_checked)  # noqa: E501
            new_clips.append({
                "path": path,
                "filename": cache.get("filename") or file_item.text(),
                "time_str": cache.get("time_str", ""),
                "desc": cache.get("desc", ""),
                "duration": cache.get("duration", 0.0),
                "score": cache.get("score"),
                "checked": checked,
            })
        self._available_concat_clips = new_clips
        self._update_concat_count_lbl()

    # [2·基础设施]  _detect_and_show_source_resolution
    def _detect_and_show_source_resolution(self):
        """检测分割片段的原始画幅并显示在镜头重组 UI 上，同时连接画幅切换信号。"""
        # 1. 优先使用服务端分割时返回的原片分辨率
        resolution_text = ""
        src_res = getattr(self, "_source_resolution", None)
        if src_res:
            if isinstance(src_res, (list, tuple)) and len(src_res) == 2:
                resolution_text = f"{int(src_res[0])}x{int(src_res[1])}"
            elif isinstance(src_res, str) and "x" in src_res:
                resolution_text = src_res
        # 2. 回退到本地缓存或探测
        if not resolution_text:
            resolution_text = getattr(self, "_probed_resolution", None) or ""
        if not resolution_text:
            cache = getattr(self, "split_clips_cache", {})
            for norm_path, item in cache.items():
                if isinstance(item, dict) and item.get("resolution"):
                    resolution_text = item["resolution"]
                    break
        if not resolution_text:
            tbl = getattr(self, "split_result_table", None)
            if tbl and tbl.rowCount() > 0:
                file_item = tbl.item(0, 2)
                if file_item:
                    path = file_item.data(Qt.UserRole)
                    if path and os.path.isfile(path):
                        w, h = self._probe_first_clip_resolution([path])
                        if w > 0 and h > 0:
                            resolution_text = f"{w}x{h}"
                            self._probed_resolution = resolution_text
        # 2. 更新 UI 标签
        lbl = getattr(self, "lbl_source_resolution", None)
        if lbl:
            if resolution_text:
                lbl.setText(f"原片: {resolution_text}")
                # 更新 combo 第一项的提示
                combo = getattr(self, "layout_combo", None)
                if combo and combo.count() > 0:
                    combo.setItemText(0, f"与原视频一致 ({resolution_text})")
            else:
                lbl.setText("原片: 未知")
        # 3. 连接画幅切换信号，更新标签显示
        combo = getattr(self, "layout_combo", None)
        if combo:
            try:
                combo.currentIndexChanged.disconnect(self._on_layout_combo_changed)
            except (TypeError, RuntimeError):
                pass
            combo.currentIndexChanged.connect(self._on_layout_combo_changed)

    # [2·基础设施]  _on_layout_combo_changed
    def _on_layout_combo_changed(self, index):
        """画幅切换时更新提示标签，让用户知道实际输出的分辨率。"""
        combo = getattr(self, "layout_combo", None)
        lbl = getattr(self, "lbl_source_resolution", None)
        if not combo or not lbl:
            return
        mode = combo.currentData()
        resolution_text = getattr(self, "_probed_resolution", None) or ""
        if mode == "source":
            if resolution_text:
                lbl.setText(f"输出: {resolution_text} (与原片一致)")
            else:
                lbl.setText("输出: 1080x1920 (原片未知，回退竖屏)")
        elif mode == "vertical":
            lbl.setText("输出: 1080x1920 (竖屏)")
        elif mode == "horizontal":
            lbl.setText("输出: 1920x1080 (横屏)")
    # [3·分割]  _open_splits_dir
    def _open_splits_dir(self):
        sp_root = self._montage_splits_root()
        if sp_root:
            # 任务级缓存已创建：优先打开缓存中的分割片段目录
            selected_item = self.video_list.currentItem()
            if selected_item and self._is_local_file_item(selected_item):
                target = self._montage_per_video_splits_dir(selected_item.text().strip())  # noqa: E501
            else:
                target = sp_root
            os.makedirs(target, exist_ok=True)
            try:
                os.startfile(target)
                return
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
                return
        selected_item = self.video_list.currentItem()
        if selected_item and self._is_local_file_item(selected_item):
            video_path = selected_item.text()
            video_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(video_dir, video_basename, "splits")
            os.makedirs(splits_dir, exist_ok=True)
            try:
                os.startfile(splits_dir)
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
        else:
            dir_path = self.folder_path_input.text().strip()
            if dir_path and os.path.exists(dir_path):
                splits_dir = os.path.join(dir_path, "splits")
                os.makedirs(splits_dir, exist_ok=True)
                try:
                    os.startfile(splits_dir)
                except OSError as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
            else:
                QMessageBox.warning(self.parent_widget, "路径无效", "请先选择有效的素材目录。")
    def _concat_src_dir(self):
        """当前镜头重组源目录（concat_src_dir_input 已移除时回退 folder_path_input）。"""
        inp = getattr(self, "concat_src_dir_input", None)
        if inp is not None:
            return inp.text().strip()
        return self.folder_path_input.text().strip()

    # [5·拼接合成]  _select_concat_src_dir
    def _select_concat_src_dir(self):
        default_dir = self._concat_src_dir()
        if not default_dir or not os.path.exists(default_dir):
            sp_root = self._montage_splits_root()
            if sp_root and os.path.isdir(sp_root):
                selected_item = self.video_list.currentItem()
                if selected_item and self._is_local_file_item(selected_item):
                    default_dir = self._montage_per_video_splits_dir(selected_item.text().strip())  # noqa: E501
                else:
                    default_dir = sp_root
            else:
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

        file_paths, _ = pick_files(
            self.parent_widget,
            "重新选择素材",
            default_dir,
            "图片视频 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v *.jpg *.jpeg *.png *.bmp *.gif *.webp);;视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;图片文件 (*.jpg *.jpeg *.png *.bmp *.gif *.webp);;所有文件 (*.*)"  # noqa: E501
        )
        if file_paths:
            dir_path = os.path.dirname(file_paths[0])
            inp = getattr(self, "concat_src_dir_input", None)
            if inp is not None:
                inp.setText(dir_path)
            self.selected_concat_clips_files = file_paths
            self._scan_concat_src_dir()
    # [5·拼接合成]  _scan_concat_src_dir
    def _scan_concat_src_dir(self):
        dir_path = self._concat_src_dir()

        if not hasattr(self, "_available_concat_clips"):
            self._available_concat_clips = []

        old_checked = {c["path"] for c in self._available_concat_clips if c.get("checked")}  # noqa: E501
        self._available_concat_clips = []

        if dir_path and os.path.exists(dir_path):
            files = []
            if hasattr(self, "selected_concat_clips_files") and self.selected_concat_clips_files:  # noqa: E501
                first_parent = os.path.abspath(os.path.dirname(self.selected_concat_clips_files[0]))  # noqa: E501
                current_dir = os.path.abspath(dir_path)
                if first_parent == current_dir:
                    files = self.selected_concat_clips_files

            if not files:
                for f in os.listdir(dir_path):
                    if f.lower().endswith((".mp4", ".m4v", ".mov", ".avi", ".mkv", ".flv", ".webm",  # noqa: E501
                                            ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")):  # noqa: E501
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
                    with open(best_srt, encoding="utf-8") as sf:
                        srt_content = sf.read()
                    segments = parse_srt(srt_content)
                    for seg_idx, (start_s, end_s, text) in enumerate(segments):
                        srt_scenes[seg_idx] = (start_s, end_s)
                        srt_descs[seg_idx] = text
                    log.info(f"Step 2 scan: Loaded {len(segments)} segments from SRT: {best_srt}")  # noqa: E501
                except (OSError, ValueError) as e:
                    log.warning(f"Step 2 scan: Failed to read SRT {best_srt}: {e}")

            scenes = self._get_split_scenes_times(dir_path, [os.path.basename(f) for f in files])  # noqa: E501

            _old_cache = getattr(self, "split_clips_cache", {}) or {}
            self.split_clips_cache = {}

            for idx, filepath in enumerate(files):
                filename = os.path.basename(filepath)
                norm_path = os.path.abspath(filepath)

                parsed = self._parse_split_filename(filename)
                if parsed:
                    _p_idx, start_str, end_str, desc = parsed
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

                # 不再在 UI 主线程对每个片段调用 get_media_duration()（会 spawn ffprobe
                # 子进程导致卡死）；时长由起止时间戳推算，缺失时读缓存，仍无则留空由后台异步补。
                _s_sec = self._srt_ts_to_seconds(start_str)
                _e_sec = self._srt_ts_to_seconds(end_str)
                clip_dur = (max(0.0, _e_sec - _s_sec)
                            if (_s_sec is not None and _e_sec is not None) else 0.0)
                if clip_dur <= 0:
                    clip_dur = float(getattr(self, "_clip_duration_cache", {}).get(norm_path, 0.0) or 0.0)  # noqa: E501

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
                auto_check = True if threshold <= 0 else score >= 0 and score >= threshold or score < 0
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

        selected_paths = [c["path"] for c in self._available_concat_clips if c.get("checked")]  # noqa: E501
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
        import json as _json

        from config.paths import VIDEO_CONFIG_FILE
        current = self.lut_combo.currentData()
        self.lut_combo.blockSignals(True)
        self.lut_combo.clear()
        self.lut_combo.addItem("无", "")
        if os.path.isfile(VIDEO_CONFIG_FILE):
            try:
                with open(VIDEO_CONFIG_FILE, encoding="utf-8") as f:
                    data = _json.load(f)
                for name, path in data.items():
                    self.lut_combo.addItem(name, path)
            except (OSError, json.JSONDecodeError):
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
    # [5·拼接合成]  _shot_type_for_clip
    def _shot_type_for_clip(self, clip_path):
        """镜头片段 → 景别键（entrance/exit/medium/closeup，未识别返回 ""）。

        片段自身名（clip_001.mp4 等）不带景别，归属看源视频：片段目录名是
        safe_source_name(源视频)，查「目录名→景别」映射（单遍历素材列表懒构建，
        防止每个未缓存片段都全量扫 video_list 做 isfile stat —— 大量片段时
        O(片段数×素材数) 次磁盘访问会卡死主线程，同 #020 家族）；
        查不到归属再按片段自身路径兕底。结果缓存（含空值）。
        """
        ap = os.path.abspath(clip_path or "")
        if not ap:
            return ""
        cache = getattr(self, "_clip_shot_type_cache", None)
        if cache is None:
            cache = self._clip_shot_type_cache = {}
        if ap in cache:
            return cache[ap]
        st = ""
        parent = os.path.basename(os.path.dirname(ap))
        if parent:
            st = self._source_shot_type_map().get(parent, "")
        if not st:
            st = classify_shot_type(ap)
        cache[ap] = st
        return st

    def _source_shot_type_map(self):
        """{safe_source_name(源视频): 景别} 映射（懒构建+缓存，单次遍历素材列表）。"""
        mapping = getattr(self, "_source_shot_type_cache", None)
        if mapping is not None:
            return mapping
        mapping = {}
        for i in range(self.video_list.count()):
            it = self.video_list.item(i)
            if it is None or not self._is_local_file_item(it):
                continue
            v = it.text().strip()
            if not v:
                continue
            mapping.setdefault(safe_source_name(v), classify_shot_type(v))
        self._source_shot_type_cache = mapping
        return mapping

    # [5·拼接合成]  _collect_clip_shot_types
    def _collect_clip_shot_types(self, clips):
        """批量取镜头景别映射（主线程调，供后台建方案/提交体使用）。"""
        return {os.path.abspath(c): self._shot_type_for_clip(c) for c in clips if c}

    def _build_precompose_plans(self, clips: list[str], target_clip_count: int, batch_count: int, randomness: str, duration_limit_sec: float, shot_types: dict | None = None) -> list:  # noqa: E501
        base: list[str] = [os.path.abspath(c) for c in clips if c]
        if not base:
            return []
        unique: list[str] = []
        _seen: set[str] = set()
        for _b in base:
            if _b not in _seen:
                _seen.add(_b)
                unique.append(_b)
        if randomness == "low":
            deck = list(unique)
        else:
            deck = list(unique)
            random.shuffle(deck)

        max_total = duration_limit_sec * 1.1 if duration_limit_sec and duration_limit_sec > 0 else 0  # noqa: E501

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

        SIMILARITY_THRESHOLD = 8  # 汉明距离 < 8 视为高度相似  # noqa: N806

        for _i in range(batch_count):
            if randomness == "high":
                random.shuffle(deck)
            seq: list[str] = []
            seq_hashes: list = []      # 已入列的镜头 hash
            seq_qualities: list = []   # 已入列的镜头质量分
            total_dur = 0.0            # 仅累计「真正入列」片段的时长
            scanned = 0
            ci = cursor
            # 候选扫描上限：预算填不满时避免无限循环
            max_scan = max(len(deck) * 3, target_clip_count * 3, 1)
            while len(seq) < target_clip_count and scanned < max_scan:
                if max_total > 0 and total_dur >= max_total:
                    break
                scanned += 1
                clip = deck[ci % len(deck)]
                ci += 1
                clip_dur = self._get_clip_duration(clip) if max_total > 0 else 0.0
                # 时长预算：非首个片段且放不下 → 继续试更短的（不 break 整批，避免远未填满就停）
                if max_total > 0 and seq and total_dur + clip_dur > max_total:
                    continue

                h = _hash(clip)
                q = _quality(clip)

                # ── 去重：与已入列镜头高度相似则跳过/择优替换 ──
                dup_idx = -1
                for j, prev_h in enumerate(seq_hashes):
                    if _hamming(h, prev_h) < SIMILARITY_THRESHOLD:
                        dup_idx = j
                        break
                if dup_idx >= 0:
                    prev_q = seq_qualities[dup_idx]
                    if q > prev_q and q > 0:
                        # 新镜头更好 → 替换旧镜头，时长预算按「新-旧」差额调整
                        log.info(f"[去重] 替换: {os.path.basename(clip)} (q={q}) → {os.path.basename(seq[dup_idx])} (q={prev_q})")  # noqa: E501
                        if max_total > 0:
                            old_dur = self._get_clip_duration(seq[dup_idx])
                            total_dur += (clip_dur - old_dur)
                        seq[dup_idx] = clip
                        seq_hashes[dup_idx] = h
                        seq_qualities[dup_idx] = q
                    else:
                        # 新镜头不如旧的 → 跳过（不计入时长，修复「预算被丢弃片段吃掉」导致成片偏短）
                        log.info(f"[去重] 跳过相似镜头: {os.path.basename(clip)} (q={q}) vs {os.path.basename(seq[dup_idx])} (q={prev_q})")  # noqa: E501
                    continue

                # 正常入列：只有这里才累加时长
                seq.append(clip)
                seq_hashes.append(h)
                seq_qualities.append(q)
                if max_total > 0:
                    total_dur += clip_dur
            cursor = ci % len(deck)
            # 无时长上限时：补足到目标镜头数（与原逻辑一致，允许循环取用）
            if max_total <= 0 and len(seq) < target_clip_count and unique:
                while len(seq) < target_clip_count:
                    seq.append(random.choice(unique))
            # 兕底：极端情况（全部相似/时长解析异常）下至少保证 1 个镜头
            if not seq and unique:
                seq.append(unique[0] if randomness == "low" else random.choice(unique))
            # 景别编排：入场镜头放头部、出场镜头放尾部，中景/特写（含未标注）
            # 居中混排；无任何出入场标注时保持原序不变。
            # shot_types 由主线程预传入（Worker 线程不能碰 Qt 控件反查素材列表），
            # 缺项按片段自身路径纯字符串匹配兕底。
            _st_map = dict(shot_types or {})
            for _c in seq:
                if _c not in _st_map:
                    _st_map[_c] = classify_shot_type(_c)
            if any(_st_map.get(_c) for _c in seq):
                seq = apply_shot_layout_order(seq, _st_map)
            plans.append({"clips": seq, "deleted_flags": [False] * len(seq), "mode": "random"})  # noqa: E501
        log.info(f"[DIAG _build_precompose_plans] target={target_clip_count} batch={batch_count} total_clips={len(unique)} plans={len(plans)} plan_sizes={[len(p['clips']) for p in plans]}")  # type: ignore[arg-type]  # noqa: E501
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
        status_txt = "已合成" if confirmed else "待确认"
        file_text = os.path.basename(out_path) if out_path else f"{clip_count} 个镜头"
        # 文案状态：用文字而非图标
        copy_preview = self._assembled_copy_preview(out_path) if out_path else ""
        copy_mark = f"  {copy_preview}" if copy_preview else ""
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
        act_confirm = QAction("完成： 确认合成视频", menu)
        act_confirm.triggered.connect(lambda: self._confirm_precompose(idx))
        menu.addAction(act_confirm)
        act_copy = QAction(" 生成口播文案", menu)
        act_copy.triggered.connect(lambda: self._gen_copy_for_plan(idx))
        menu.addAction(act_copy)
        plan = self.precompose_plans[idx] if 0 <= idx < len(self.precompose_plans) else None  # noqa: E501
        if plan:
            out_path = (plan.get("output_path") or "").strip()
            has_copy = bool(out_path and self._assembled_has_copy(out_path))
            if has_copy:
                act_view = QAction(" 查看文案", menu)
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
            QMessageBox.information(
                self.parent_widget, "尚未生成口播文案",
                "该视频尚未生成口播文案。\n\n请点击底部「生成口播文案」按钮，"
                "选择产品信息后由 AI 根据画面生成口播文案。")
            return
        try:
            with open(txt, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout
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
        except OSError:
            return False
    # [4·文案脚本]  _save_script_meta
    def _save_script_meta(self, video_path, clips, brand="", product="", model_name="", extra=""):  # noqa: E501
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
        except (OSError, TypeError) as e:
            log.warning(f"保存脚本元数据失败: {e}")
    # [4·文案脚本]  _load_script_meta
    def _load_script_meta(self, video_path):
        """读取脚本关联元数据。"""
        import json as _json
        meta_path = os.path.splitext(video_path)[0] + ".meta.json"
        try:
            if os.path.exists(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    return _json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        return None
    # [4·文案脚本]  _assembled_copy_preview
    def _assembled_copy_preview(self, path):
        """获取口播文案的文字预览（前30字）。

        未生成口播文案（.txt 不存在）时返回占位提示，便于用户在列表里一眼看出
        哪些视频还没生成口播文案。
        """
        if not path:
            return "未生成口播文案"
        txt = os.path.splitext(path)[0] + ".txt"
        try:
            if os.path.exists(txt) and os.path.getsize(txt) > 0:
                with open(txt, encoding="utf-8") as f:
                    content = f.read().strip().replace("\n", " ")
                return content[:30] + ("…" if len(content) > 30 else "")
        except OSError:
            pass
        return "未生成口播文案"
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
            status_txt = "已合成" if confirmed else "待确认"
            # 文案预览：统一用 _assembled_copy_preview（和 _add_assembled_row 一致）
            # 已生成显示前30字，未生成显示占位，避免刷新后文字预览丢失
            copy_preview = self._assembled_copy_preview(out_path) if out_path else "未生成口播文案"  # noqa: E501
            copy_mark = f"  {copy_preview}" if copy_preview else ""
            file_text = os.path.basename(out_path) if out_path else f"{clip_count} 个镜头"
            item.setText(f"[{idx+1}] {file_text}  {status_txt}{copy_mark}")
            if has_copy:
                txt = os.path.splitext(out_path)[0] + ".txt"
                try:
                    with open(txt, encoding="utf-8") as f:
                        snippet = f.read(200).strip()
                    item.setToolTip(snippet + ("..." if len(snippet) == 200 else ""))
                except OSError:
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
        if select_index is not None and 0 <= select_index < self.assembled_clips_list_widget.count():  # noqa: E501
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
        # 确认合成视频全部完成后，将绿色背景转移到「生成口播文案」按钮
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
        unconfirmed = [i for i, p in enumerate(self.precompose_plans) if not p.get("confirmed")]  # noqa: E501
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
        clips = [c for i, c in enumerate(all_clips) if not (i < len(deleted_flags) and deleted_flags[i])]  # noqa: E501
        if not clips:
            QMessageBox.warning(self.parent_widget, "镜头为空", "该预合成没有可用镜头（可能都被标记删除），请先在下方镜头列表恢复至少 1 个。")  # noqa: E501
            if getattr(self, "_confirm_queue", None):
                self._confirm_queue = []
            return

        out_montage_dir = plan.get("out_dir") or getattr(self, "_pending_out_montage_dir", "")  # noqa: E501
        if not out_montage_dir:
            dir_path = self._concat_src_dir()
            out_montage_dir = self._get_out_montage_dir(dir_path)
        os.makedirs(out_montage_dir, exist_ok=True)
        self._confirming_plan_index = index

        # 停止预览播放（不做同步 setSource(QUrl()) 释放：旧媒体释放是异步的，
        # 在 UI 线程同步清源会阻塞界面导致"确认合成时卡死"。文件句柄释放由
        # 后台合成 worker 上传时自然完成）。
        with contextlib.suppress(OSError, RuntimeError):
            self.preview_player.stop()

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
        self.stage_label.setText(f" 正在确认合成预合成 {index + 1}... (剩余 {remaining} 条待确认)")
    # [2·基础设施]  _srt_ts_to_seconds
    @staticmethod
    def _srt_ts_to_seconds(ts):
        """'HH:MM:SS,mmm' -> 秒(float)，解析失败返回 None。"""
        try:
            h, m, rest = str(ts).strip().split(":")
            s, ms = rest.replace(".", ",").split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        except (ValueError, TypeError):
            return None
    def _clip_duration_text(self, cache_item, time_str, path=""):
        """优先用镜头分析缓存的 duration，其次由 time_str('起 --> 止')推算，
        最后用 ffprobe 直接探测片段文件（cv2 读不了 10-bit/特殊编码时兜底）。

        探测结果无条件回写 split_clips_cache：切换预合成方案时（_refresh_sources_for_plan）
        避免对每个镜头重复 ffprobe 导致 UI 卡死。
        """
        dur = 0.0
        if cache_item:
            try:
                dur = float(cache_item.get("duration") or 0.0)
            except (TypeError, ValueError):
                dur = 0.0
        # 优先读 split_clips_cache（_build_precompose_plans 后台线程已预填），
        # 避免在 UI 主线程对每个镜头 spawn ffprobe 子进程导致卡死。
        if dur <= 0 and path:
            norm = os.path.abspath(path)
            cache = getattr(self, "split_clips_cache", {})
            cached = cache.get(norm)
            if cached and isinstance(cached, dict) and cached.get("duration", 0) > 0:
                dur = cached["duration"]
        if dur <= 0 and time_str and "-->" in time_str:
            s = self._srt_ts_to_seconds(time_str.split("-->")[0])
            e = self._srt_ts_to_seconds(time_str.split("-->")[1])
            if s is not None and e is not None:
                dur = max(0.0, e - s)
        # 不再在 UI 主线程调用 get_media_duration()（会 spawn ffprobe 子进程导致卡死）
        # 时长为 0 时显示 "—"，后续由后台异步评分时补充
        return f"{dur:.1f}s" if dur > 0 else "—"
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
            cache_item = getattr(self, "split_clips_cache", {}).get(os.path.abspath(src_path))  # noqa: E501
            if cache_item:
                time_str = cache_item.get("time_str", "")
                desc = cache_item.get("desc", "")
            else:
                parsed = self._parse_split_filename(filename)
                if parsed:
                    _, start_str, end_str, desc = parsed
                    time_str = f"{start_str} --> {end_str}"
                else:
                    time_str = ""
                    desc = self.split_descriptions.get(os.path.abspath(src_path), "")

            grip_item = QTableWidgetItem("⠿")
            grip_item.setTextAlignment(Qt.AlignCenter)
            grip_item.setFlags(grip_item.flags() & ~Qt.ItemIsEditable)
            grip_item.setData(Qt.UserRole, src_path)
            self.sources_detail_widget.setItem(idx, 0, grip_item)

            file_item = QTableWidgetItem(filename)
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 1, file_item)

            dur_item = QTableWidgetItem(self._clip_duration_text(cache_item, time_str, src_path))  # noqa: E501
            dur_item.setTextAlignment(Qt.AlignCenter)
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 2, dur_item)

            shot_type = str(cache_item.get("shot_type", "") if cache_item else "") or "—"  # noqa: E501
            shot_item = QTableWidgetItem(shot_type)
            shot_item.setTextAlignment(Qt.AlignCenter)
            shot_item.setFlags(shot_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 3, shot_item)

            desc_item = QTableWidgetItem(desc)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.sources_detail_widget.setItem(idx, 4, desc_item)

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
            self.sources_detail_widget.setItem(idx, 5, score_item)

            is_deleted = idx < len(deleted_flags) and deleted_flags[idx]
            if is_deleted:
                for col in range(self.sources_detail_widget.columnCount()):
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
            menu.addAction("↩ 恢复镜头")
        else:
            menu.addAction(" 标记删除（不参与合成和预览）")
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
    # [5·拼接合成]  _stop_preview_playback
    def _stop_preview_playback(self):
        """停止预览播放并复位控件（两个播放器一并停止）。"""
        self._preview_sequence_clips = []
        self._pending_play_clip = ""
        self._preview_pending_clip = ""
        self._play_request_id = getattr(self, "_play_request_id", 0) + 1
        self._release_preview_sessions("停播")
        self.preview_overlay_label.hide()
        self.btn_preview_play.setIcon(mdi_icon("play"))

    # [5·拼接合成]  _release_preview_sessions
    def _release_preview_sessions(self, reason="停播"):
        """停止两个播放器并清源，释放片段媒体会话与文件句柄。

        只能在「没有画面在渲染」时调（停播/切步骤）：WMF 拆会话是 GUI 线程同步
        操作，播放中拆会卡住主线程，所以双播放器换手退役的播放器不在切换时拆，
        统一由这里兜底释放。

        释放前必须先作废所有待播状态并置「正在释放」标志：stop()/setSource() 会
        同步抛 mediaStatusChanged(NoMedia)，若此时仍留有 _pending_play_clip /
        _preview_sequence_clips / _preview_pending_clip，信号槽会重入
        _load_preview_clip 再对同一个正在被拆的播放器 setSource，WMF 同步拆两个
        会话直接死锁（切步骤离开预览时必现，日志只剩「清源 开始」无耗时行）。
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        self._releasing_preview = True
        self._preview_sequence_clips = []
        self._pending_play_clip = ""
        self._preview_pending_clip = ""
        self._play_request_id = getattr(self, "_play_request_id", 0) + 1
        try:
            for _attr in ("preview_player", "_preview_standby_player"):
                _p = getattr(self, _attr, None)
                if _p is None:
                    continue
                try:
                    _p.stop()
                    # 只要还挂着一个源（含已播完的 EndOfMedia）就清掉，否则文件句柄始终不释放
                    if _p.mediaStatus() not in (QMediaPlayer.NoMedia, QMediaPlayer.InvalidMedia):
                        self._timed_mf(f"{reason}清源({_attr})", _p.setSource, QUrl())
                except (RuntimeError, OSError):
                    pass
        finally:
            self._releasing_preview = False

    # [5·拼接合成]  _start_sequence_preview_for_plan
    def _start_sequence_preview_for_plan(self, plan_index):
        self._preview_sequence_clips = []
        if plan_index < 0 or plan_index >= len(self.precompose_plans):
            self._stop_preview_playback()
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
            self._stop_preview_playback()
            return
        self._preview_sequence_idx = 0
        self._play_current_sequence_clip()
    # [5·拼接合成]  _start_sequence_preview
    def _start_sequence_preview(self, clips, start_idx=0):
        self._preview_sequence_clips = [os.path.abspath(p) for p in clips if p and os.path.exists(p)]  # noqa: E501
        if not self._preview_sequence_clips:
            self._stop_preview_playback()
            return
        self._preview_sequence_idx = max(0, min(start_idx, len(self._preview_sequence_clips) - 1))  # noqa: E501
        self._play_current_sequence_clip()
    # [9·其他]  _play_current_sequence_clip
    def _play_current_sequence_clip(self):
        """播放序列中的当前片段。"""
        # 防止页面已销毁后由 EndOfMedia timer 触发访问已释放对象：仅用对象有效性判断
        # （不能用 isVisible()：页面在 QStackedWidget 中切换步骤时可能不可见，会误杀正常播放）
        try:
            import shiboken6 as _sb
            if _sb.isValid(self) and _sb.isValid(self.preview_player) and self._preview_sequence_clips:  # noqa: E501
                pass
            else:
                return
        except (ImportError, ModuleNotFoundError):
            return

        if not self._preview_sequence_clips:
            return
        clip = self._preview_sequence_clips[self._preview_sequence_idx]
        from PySide6.QtCore import QTimer as _QT  # noqa: N814
        # 记录待加载片段（若已有待加载则覆盖，防止连播快速切换时旧定时器串号）
        self._pending_play_clip = clip
        # 自增代号：旧的延迟回调执行时会先比对代号，不匹配则直接丢弃，
        # 避免快速连续点击时多个 singleShot 串号播错镜头
        self._play_request_id = getattr(self, "_play_request_id", 0) + 1
        req_id = self._play_request_id
        # 用 QTimer 延迟执行换源+播放，避免在列表点击槽函数里同步调用导致卡死
        _QT.singleShot(50, lambda: self._do_play_sequence_clip(req_id))
        # 兜底 watchdog：3s 后仍未加载成功则记日志，便于定位“预览黑屏”类问题
        _QT.singleShot(3000, self._warn_if_preview_stuck)

    def _warn_if_preview_stuck(self):
        """预览看门狗：3s 后仍无媒体且无待加载片段，说明加载链断了（打日志便于定位）。"""
        try:
            import shiboken6 as _sb
            if not (_sb.isValid(self) and _sb.isValid(self.preview_player)):
                return
        except (ImportError, ModuleNotFoundError):
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if (getattr(self, "_preview_sequence_clips", [])
                    and not getattr(self, "_pending_play_clip", "")
                    and self.preview_player.mediaStatus() == QMediaPlayer.NoMedia):
                log.warning("[预览] 3s 内未成功加载任何片段，预览区保持黑屏（检查解码器/文件路径）")  # noqa: E501
        except (RuntimeError, ImportError, ModuleNotFoundError):
            pass

    def _on_preview_no_media(self):
        """mediaStatusChanged == NoMedia 时回调：加载待播放片段。"""
        clip = getattr(self, "_pending_play_clip", "")
        self._pending_play_clip = ""
        if clip:
            self._load_preview_clip(clip)

    def _load_preview_clip(self, clip):
        """加载并播放一个预览片段：空闲直接换源；正在播放则走双播放器缓冲换源，避免主线程卡死。"""
        # 回调可能来自定时器或 Qt 信号：用 shiboken 确认对象未销毁
        # （不用 isVisible()：步骤切换时页面可能不可见但播放应继续）
        try:
            import shiboken6 as _sb
            if not (_sb.isValid(self) and _sb.isValid(self.preview_player)):
                return
        except (ImportError, ModuleNotFoundError):
            return
        if not clip or not os.path.isfile(clip):
            log.warning(f"[预览] 待播放片段不存在: {clip}")
            return
        # 防循环：同一个片段连续加载失败（解码器不支持/文件损坏）时停止重试，
        # 避免信号与兜底加载互相触发导致 CPU 飙升 / 主线程卡死
        if getattr(self, "_last_preview_load_clip", "") == clip:
            self._preview_load_retry = getattr(self, "_preview_load_retry", 0) + 1
        else:
            self._last_preview_load_clip = clip
            self._preview_load_retry = 0
        if self._preview_load_retry >= 3:
            log.warning(f"[预览] 片段反复加载失败，停止重试: {clip}")
            self._last_preview_load_clip = ""
            self._preview_load_retry = 0
            return
        active = self.preview_player
        # 当前播放器空闲（首次加载 / 已停止）：没有活跃会话可拆，直接换源，不阻塞
        if self._is_player_idle(active):
            self._preview_pending_clip = ""
            self._apply_source_and_play(active, clip)
            self._update_preview_overlay()
            return
        # 正在播放：把新片段加载进备用播放器，就绪后由 _on_standby_media_status 换出
        standby = self._preview_standby_player
        from PySide6.QtCore import QUrl
        self._preview_pending_clip = clip
        # 备用播放器若残留上次会话，直接 setSource 替换（不在点击路径上调 stop()，避免阻塞）
        self._timed_mf(f"备用换源 {os.path.basename(clip)}", standby.setSource, QUrl.fromLocalFile(clip))
        # 兜底：若备用迟迟不报就绪（MF 慢/异常），800ms 后强制换出，避免停在旧画面
        QTimer.singleShot(800, self._force_swap_if_pending)

    # [5·拼接合成]  _timed_mf
    def _timed_mf(self, tag, fn, *args):
        """执行一次播放器调用并留痕耗时。

        Windows WMF 后端的换源/释放媒体会话是在 GUI 线程同步做的，是「预览卡死」
        的高发点；先打「开始」再打耗时，万一调用直接死锁，app.log 里只剩「开始」
        没有耗时行，就能定位到卡在哪一步。
        """
        log.info(f"[预览] {tag} 开始")
        t0 = time.perf_counter()
        try:
            return fn(*args)
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            if ms >= 300:
                log.warning(f"[预览][耗时] {tag} 阻塞主线程 {ms:.0f}ms")
            else:
                log.info(f"[预览][耗时] {tag} {ms:.0f}ms")

    # [5·拼接合成]  _is_player_idle
    def _is_player_idle(self, player):
        """播放器是否处于「无活跃渲染会话」（此时在它自身上换源不会阻塞主线程）。

        EndOfMedia 也算空闲：片段自然播完时 WMF 已自行停止渲染，同一个播放器
        直接换下一个片段就是普通播放列表用法；若把它当「正在播放」去走双播放器
        换手，就要拆旧会话，而新画面此时正在向同一个控件渲染——连播到第 2 个
        镜头时卡死就出在这里。
        """
        from PySide6.QtMultimedia import QMediaPlayer
        try:
            if player.mediaStatus() in (QMediaPlayer.NoMedia, QMediaPlayer.InvalidMedia,
                                        QMediaPlayer.EndOfMedia):
                return True
            # 已停止（stop() 不会把 mediaStatus 改回 NoMedia）同样没有活跃会话
            return player.playbackState() == QMediaPlayer.StoppedState
        except (RuntimeError, OSError):
            return True

    def _apply_source_and_play(self, player, clip):
        from PySide6.QtCore import QUrl
        self._timed_mf(f"换源 {os.path.basename(clip)}", player.setSource, QUrl.fromLocalFile(clip))
        player.play()

    def _update_preview_overlay(self):
        self.btn_preview_play.setIcon(mdi_icon("pause"))
        total = len(self._preview_sequence_clips)
        self.preview_overlay_label.setText(f"镜头 {self._preview_sequence_idx + 1}/{total}")  # noqa: E501
        self.preview_overlay_label.adjustSize()
        self.preview_overlay_label.show()

    # [5·拼接合成]  双播放器信号路由（两个播放器共用一套槽，按来源对象分发）
    def _route_preview_position(self, pos, src):
        if src is self.preview_player:
            self._on_preview_position_changed(pos)

    def _route_preview_duration(self, dur, src):
        if src is self.preview_player:
            self._on_preview_duration_changed(dur)

    def _route_preview_status(self, status, src):
        # 释放会话期间屏蔽所有状态回调：否则 stop()/setSource() 触发的 NoMedia 会
        # 重入 _load_preview_clip，对正在被拆的播放器再次换源 → WMF 同步拆会话死锁
        if getattr(self, "_releasing_preview", False):
            return
        if src is self.preview_player:
            self._on_preview_media_status_changed(status)
        elif src is self._preview_standby_player:
            self._on_standby_media_status(status)

    def _on_standby_media_status(self, status):
        """备用播放器加载就绪 → 把画面瞬间切过去；加载失败 → 退回直接换源。"""
        from PySide6.QtMultimedia import QMediaPlayer
        if not getattr(self, "_preview_pending_clip", ""):
            return
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._do_preview_swap()
        elif status == QMediaPlayer.InvalidMedia:
            # 备用加载失败：宁可短暂阻塞也要在当前播放器上出画面
            clip = self._preview_pending_clip
            self._preview_pending_clip = ""
            self._apply_source_and_play(self.preview_player, clip)
            self._update_preview_overlay()

    def _force_swap_if_pending(self):
        """备用迟迟未报就绪时的兜底换出。"""
        try:
            import shiboken6 as _sb
            if not (_sb.isValid(self) and _sb.isValid(self.preview_player)):
                return
        except (ImportError, ModuleNotFoundError):
            return
        if getattr(self, "_preview_pending_clip", ""):
            self._do_preview_swap()

    def _do_preview_swap(self):
        """把画面输出从当前播放器瞬间切到已就绪的备用播放器，旧播放器退为备用。"""
        clip = getattr(self, "_preview_pending_clip", "")
        if not clip:
            return
        self._preview_pending_clip = ""
        standby = self._preview_standby_player
        old = self.preview_player
        widget = self._preview_video_widget
        # 把画面输出切到备用并播放（备用无活跃会话，setVideoOutput/play 不阻塞）
        if widget is not None:
            with contextlib.suppress(RuntimeError, OSError):
                self._timed_mf("换手 setVideoOutput", standby.setVideoOutput, widget)
        self._preview_standby_audio.setMuted(False)
        self._timed_mf("换手 play", standby.play)
        # 角色互换：备用转正，原活跃退为备用（连同音频输出一起换，保持播放器↔音频配对）
        self.preview_player, self._preview_standby_player = standby, old
        self.preview_audio_output, self._preview_standby_audio = self._preview_standby_audio, self.preview_audio_output
        # 退役播放器：静音 + pause() + 摘掉画面输出，三者都不拆媒体会话，故不阻塞。
        # 关键：不在切换时释放它的会话（原先是 QTimer(120) → setSource(QUrl())）——
        # WMF 拆会话是 GUI 线程同步操作，而此刻新活跃播放器正向同一个 QVideoWidget
        # 渲染，拆旧会话会与它抢 sink，直接把主线程挂住（连播到第 2 个镜头时
        # 标题栏 Not Responding 即此）。旧会话留到下次把它当备用播放器换源时顺带
        # 替换（那时它已摘离画面），或由 _stop_preview_playback / 切步骤时兜底释放。
        self._preview_standby_audio.setMuted(True)
        with contextlib.suppress(RuntimeError, OSError):
            old.pause()
        with contextlib.suppress(RuntimeError, OSError):
            self._timed_mf("退役摘画面", old.setVideoOutput, None)
        self._update_preview_overlay()

    def _do_play_sequence_clip(self, req_id=None):
        """实际执行播放序列片段（由定时器延迟调用，避免 UI 卡死）。"""
        try:
            import shiboken6 as _sb
            if not (_sb.isValid(self) and _sb.isValid(self.preview_player)):
                return
        except (ImportError, ModuleNotFoundError):
            return
        # 过期回调（用户已点到其他片段）直接丢弃
        if req_id is not None and req_id != getattr(self, "_play_request_id", 0):
            return
        clip = getattr(self, "_pending_play_clip", "")
        if not clip:
            return
        self._pending_play_clip = ""
        self._load_preview_clip(clip)

    def _get_video_scene_sources(self, path):
        """读取某组合视频的 _sources.txt，返回源镜头路径列表。"""
        sources_file = os.path.splitext(path)[0] + "_sources.txt"
        if not os.path.exists(sources_file):
            return []
        try:
            with open(sources_file, encoding="utf-8") as sf:
                return [line.strip() for line in sf if line.strip()]
        except OSError:
            return []
    # [3·分割]  _get_video_scene_descriptions
    def _get_video_scene_descriptions(self, path):
        """读取某组合视频的 _sources.txt，按顺序解析出每个镜头画面的描述文案。"""
        scenes: list[str] = []
        sources_file = os.path.splitext(path)[0] + "_sources.txt"
        if not os.path.exists(sources_file):
            return scenes
        try:
            with open(sources_file, encoding="utf-8") as sf:
                src_paths = [line.strip() for line in sf if line.strip()]
        except OSError as e:
            log.warning(f"读取源镜头列表失败: {e}")
            return scenes

        for src_path in src_paths:
            filename = os.path.basename(src_path)
            cache_item = getattr(self, "split_clips_cache", {}).get(os.path.abspath(src_path))  # noqa: E501
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
    def _load_shared_product_info(self):
        """从磁盘加载上次保存的产品信息（跨会话保留）。失败返回 None。"""
        try:
            import json as _json

            from config.paths import CONFIG_DIR
            cache_file = os.path.join(CONFIG_DIR, "product_info_cache.json")
            if os.path.isfile(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    data = _json.load(f)
                # 校验为 4 元组结构
                if isinstance(data, dict) and all(
                    isinstance(data.get(k), str) for k in ("brand", "product", "model", "extra")  # noqa: E501
                ):
                    return (data["brand"], data["product"], data["model"], data["extra"])  # noqa: E501
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"加载产品信息缓存失败: {e}")
        return None

    def _save_shared_product_info(self, info):
        """把产品信息持久化到磁盘，下次启动仍可预填。"""
        try:
            import json as _json

            from config.paths import CONFIG_DIR
            cache_file = os.path.join(CONFIG_DIR, "product_info_cache.json")
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = {"brand": info[0], "product": info[1], "model": info[2], "extra": info[3]}  # noqa: E501
            with open(cache_file, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            log.warning(f"保存产品信息缓存失败: {e}")

    def _ensure_shared_product_info(self, force=False):
        """获取一次共用的产品背景信息（品牌/产品/型号/卖点），缓存后全局复用。

        返回 (brand, product, model_name, extra)；用户取消时返回 None。
        force=True 时【无条件弹窗】（跳过缓存），用于「生成口播文案」批量按钮，
        确保用户每次点击都能看到并修改产品信息。
        缓存优先级：内存 > 磁盘（跨会话保留）。
        """
        cached = getattr(self, "_shared_product_info", None)
        if cached is None:
            # 内存无缓存时，尝试从磁盘加载（跨会话保留上次填写内容）
            cached = self._load_shared_product_info()
            if cached is not None:
                self._shared_product_info = cached
        if cached is not None and not force:
            return cached

        # force=True 或无缓存：直接弹窗（预填上次内容便于微调）
        dlg = ProductCopyInputDialog(self.parent_widget)
        if cached is not None:
            # 复用上次填写的内容，便于微调
            b, p, m, e = cached
            dlg.brand_in.setText(b)
            dlg.product_in.setText(p)
            dlg.model_in.setText(m)
            dlg.extra_in.setPlainText(e)
        # 诊断：确认对话框构造完成、parent 有效
        log.info(f"[批量文案] 准备 exec 对话框, parent={self.parent_widget!r}, cached={cached is not None}")  # noqa: E501
        try:
            result = dlg.exec()
        except (OSError, RuntimeError) as e:
            log.exception(f"[批量文案] dlg.exec() 抛异常: {e}")
            return None
        log.info(f"[批量文案] dlg.exec() 返回={result}, Accepted={QDialog.Accepted}")
        if result != QDialog.Accepted:
            log.info(f"[批量文案] 用户未确认（返回 {result}），中止")
            return None
        info = dlg.get_values()
        self._shared_product_info = info
        self._save_shared_product_info(info)  # 持久化，下次启动可预填
        log.info(f"[批量文案] 已采集产品信息: {info}")
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
            with open(sources_file, encoding="utf-8") as sf:
                src_paths = [line.strip() for line in sf if line.strip()]
            for i, src_path in enumerate(src_paths):
                desc = scenes[i] if i < len(scenes) else ""
                if not desc or not desc.strip():
                    missing_clips.append(os.path.abspath(src_path))

        if missing_clips:
            self.stage_label.setText(f"正在为 {len(missing_clips)} 个缺失描述的镜头生成画面描述...")
            self._batch_gen_missing_descriptions(
                missing_clips, "", "", None,
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
                with open(companion_txt, encoding="utf-8") as f:
                    existing = f.read().strip()
            except OSError:
                pass
            preview = existing[:120] + ("..." if len(existing) > 120 else "")
            reply = QMessageBox.question(
                self.parent_widget, "已有文案",
                f"该视频已存在文案：\n\n{preview}\n\n是否重新生成并覆盖？",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        info = self._ensure_shared_product_info(force=True)
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
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "保存失败", f"写入文案文件失败：\n{e}")
                return
            # 保存关联元数据
            clips = self._get_video_scene_sources(pth)
            self._save_script_meta(pth, clips, brand, product, model_name, extra)
            self.stage_label.setText("完成： 口播文案已按画面生成并保存")
            self._refresh_assembled_copy_buttons()
            QMessageBox.information(
                self.parent_widget, "文案已生成",
                f"已根据画面为 {os.path.basename(pth)} 生成口播文案并保存：\n{ctxt}\n\n"
                f"——\n{content}\n——\n\n进入下一步「口播配音」会自动载入。")

        def on_err(msg):
            self.stage_label.setText("失败： 文案生成失败")
            self._show_long_error("生成失败", f"调用大模型失败：\n{msg}")

        self._scene_copy_worker.finished.connect(on_ok)
        self._scene_copy_worker.error.connect(on_err)
        self._scene_copy_worker.start()
    # [3·分割]  _batch_gen_copy_by_scene
    def _batch_gen_copy_by_scene(self):
        """一键为所有已生成的组合视频，按各自画面镜头描述生成口播文案（共用一份产品背景）。
        如果镜头缺少画面描述（如原视频无声音未生成），先用视觉 LLM 自动补生成描述。"""
        log.info("[批量文案] 「生成口播文案」按钮已点击，进入 handler")
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
        # 注：预合成视频生成时已自带画面描述拼接的 .txt（concat_workers 写入），
        # 因此 _assembled_has_copy 对每个视频恒为 True，原先的“已有部分文案”中间框
        # 会每次都弹并极易误点“取消/否”导致产品窗没机会弹出。这里直接进入产品信息采集，
        # 让用户先选产品，再统一覆盖生成口播文案。

        # 强制每次都弹产品信息对话框（预填上次内容），确保用户能输入/修改产品信息。
        # 加诊断日志：万一某环境下不弹窗，能从日志定位卡在哪一步。
        log.info(f"[批量文案] 进入产品信息采集 force=True, 缓存={getattr(self, '_shared_product_info', None)!r}")  # noqa: E501
        info = self._ensure_shared_product_info(force=True)
        if info is None:
            log.info("[批量文案] 用户取消了产品信息对话框，中止")
            return
        log.info(f"[批量文案] 产品信息已采集: brand={info[0]!r}, product={info[1]!r}, model={info[2]!r}")  # noqa: E501
        # 若用户什么都没填直接点生成，给出确认（产品信息可选，不强制阻断）
        if not any(info):
            reply = QMessageBox.question(
                self.parent_widget, "未填写产品信息",
                "你没有填写任何产品信息（品牌/产品/型号/卖点）。\n\n"
                "是 = 仍然生成（AI 仅根据画面自由发挥，可能不够精准）\n"
                "否 = 返回填写",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return  # 用户回去填写；重新点按钮会再次弹窗（force=True）

        # 检查所有目标视频的镜头是否有画面描述，收集缺失描述的镜头
        missing_desc_clips = set()
        for path in targets:
            scenes = self._get_video_scene_descriptions(path)
            sources_file = os.path.splitext(path)[0] + "_sources.txt"
            if os.path.exists(sources_file):
                with open(sources_file, encoding="utf-8") as sf:
                    src_paths = [line.strip() for line in sf if line.strip()]
                for i, src_path in enumerate(src_paths):
                    desc = scenes[i] if i < len(scenes) else ""
                    if not desc or not desc.strip():
                        missing_desc_clips.add(os.path.abspath(src_path))

        if missing_desc_clips:
            # 有镜头缺少画面描述，用视觉 LLM 自动生成
            self._batch_gen_missing_descriptions(
                list(missing_desc_clips), "", "", None,
                lambda: self._start_batch_copy("", "", model, info, targets))
        else:
            self._start_batch_copy("", "", model, info, targets)
    # [4·文案脚本]  _batch_gen_missing_descriptions
    def _batch_gen_missing_descriptions(self, clip_paths, api_url, api_key, model, on_done):  # noqa: E501
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
                except (ValueError, TypeError):
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
            except (ValueError, TypeError, json.JSONDecodeError) as e:
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
            # Refresh step-3 voice table so newly written .txt files are shown immediately  # noqa: E501
            self._do_scan_voice_video_dir()
            fails = self._batch_copy_failures
            ok_count = self._batch_copy_total - len(fails)
            if fails:
                self.stage_label.setText(f"注意： 批量文案生成完成：成功 {ok_count}，失败 {len(fails)}")
                detail = "\n".join(f"· {os.path.basename(p)}：{m}" for p, m in fails[:10])  # noqa: E501
                more = "" if len(fails) <= 10 else f"\n…… 等共 {len(fails)} 个失败"
                QMessageBox.warning(
                    self.parent_widget, "部分失败",
                    f"批量按画面生成文案完成。\n成功 {ok_count} 个，失败 {len(fails)} 个：\n\n{detail}{more}")  # noqa: E501
            else:
                self.stage_label.setText(f" 已为全部 {ok_count} 个视频按画面生成口播文案")
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
            # _sources.txt missing or empty — generate a single-line product copy as fallback  # noqa: E501
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
                # Invalidate the step-3 cache entry so the table re-reads the file on next scan  # noqa: E501
                if hasattr(self, "original_texts"):
                    self.original_texts.pop(pth, None)
            except (OSError, KeyError, TypeError) as e:
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
            self._stop_preview_playback()
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
        # 成功拿到时长 = 媒体已真正加载，重置预览加载重试计数
        if duration > 0:
            self._last_preview_load_clip = ""
            self._preview_load_retry = 0
    # [8·事件回调]  _on_preview_media_status_changed
    def _on_preview_media_status_changed(self, status):
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.EndOfMedia and self._preview_sequence_clips:
                # 默认自动连播（各片段合计约 30s）；_play_current_sequence_clip 内已
                # stop + 清源再换源，避免直接换源卡死。
                if getattr(self, "_preview_auto_advance", True):
                    self._preview_sequence_idx += 1
                    if self._preview_sequence_idx >= len(self._preview_sequence_clips):
                        self._preview_sequence_idx = 0
                    # 用 QTimer 延迟播放下一个，避免在 mediaStatusChanged 信号内
                    # 直接调 setSource() 导致 Qt 内部死锁 / 界面卡死
                    QTimer.singleShot(50, self._play_current_sequence_clip)
                else:
                    # 关闭连播时停在当前片段末尾
                    self.preview_player.setPosition(0)
                    self.btn_preview_play.setIcon(mdi_icon("play"))
            elif status == QMediaPlayer.NoMedia:
                # 旧源已释放，加载待播放片段（信号驱动，避免固定延时不可靠）
                # 仅当有待播放片段时才加载，避免无限循环
                if getattr(self, "_pending_play_clip", ""):
                    self._on_preview_no_media()
    
            elif status == QMediaPlayer.InvalidMedia:  # noqa: SIM102
                # 当前片段无法播放，跳过并尝试下一个
                if self._preview_sequence_clips:
                    log.warning(f"[预览] 无法播放片段：{self._preview_sequence_clips[self._preview_sequence_idx]}")  # noqa: E501
                    QTimer.singleShot(50, self._skip_to_next_preview_clip)
        except (OSError, RuntimeError):
            pass
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
            path = text.split("   (")[-1][:-1] if "   (" in text and text.endswith(")") else text

        if os.path.exists(path):
            try:
                os.startfile(path)
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "无法播放", f"播放视频失败:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到该视频文件:\n{path}")
    # [9·其他]  _play_video
    def _play_video(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except OSError as e:
                QMessageBox.warning(self.parent_widget, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到视频文件:\n{path}")
    # [9·其他]  _show_long_error
    def _show_long_error(self, title, err):
        """显示长错误信息（traceback/多失败项/接口响应）的统一入口。

        用可滚动 ErrorDialog 替代 QMessageBox.critical，避免撑满屏幕，
        并提供"复制日志"按钮。短提示仍用 QMessageBox.warning。
        """
        show_error_dialog(self.parent_widget, title, str(err))
    # [6·配音]  _on_play_row_video
    def _on_play_row_video(self, filepath):
        """配音表格行文件名旁的播放按钮：优先播放配音后的视频（dubbed_*.mp4），
        未配音时才播放原视频。这样配音完成后用户点此按钮自然看到带配音的效果。
        """
        dubbed = self.dubbed_video_paths.get(filepath, "") if hasattr(self, "dubbed_video_paths") else ""  # noqa: E501
        if dubbed and os.path.exists(dubbed):
            self._play_video(dubbed)
        else:
            self._play_video(filepath)
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
