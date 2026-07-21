# -*- coding: utf-8 -*-
"""步骤 5（独立分支）: 音乐卡点混剪界面

流程：选择音乐 → 播放预览 → 服务端检测节拍 → 显示声波波形图(含节拍线) → 分配镜头 → 确认合成
"""
import os
import struct
import subprocess
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QFrame, QComboBox, QWidget, QScrollArea, QSizePolicy, QSlider)
from PySide6.QtCore import Qt, Signal, QRectF, QThread
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QFont,
                           QLinearGradient, QPolygonF)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl, QPointF
from gui.montage.base_step_view import BaseStepView
from utils.gui_icons import mdi_button
from utils.logger_utils import log


# ═══════════════════════════════════════════════════════════
# 波形峰值提取（后台线程，ffmpeg 解码）
# ═══════════════════════════════════════════════════════════

class WaveformPeakWorker(QThread):
    """用 ffmpeg 解码音频为 PCM，计算波形峰值包络。

    信号: peaks_ready(list[float], float)  → (峰值列表 0~1, 时长秒)
    """
    peaks_ready = Signal(list, float)
    error = Signal(str)

    NUM_PEAKS = 3000  # 整轨峰值桶数

    def __init__(self, audio_path, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path

    def run(self):
        try:
            from utils.platform_utils import find_ffmpeg, create_no_window_flag
            ffmpeg_exe = find_ffmpeg()
            cmd = [ffmpeg_exe, "-i", self.audio_path,
                   "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", "-"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=create_no_window_flag())
            raw = proc.stdout.read()
            proc.wait()
            if not raw or len(raw) < 4:
                self.error.emit("音频解码失败，无法提取波形")
                return

            n_samples = len(raw) // 2
            samples = struct.unpack(f"<{n_samples}h", raw[:n_samples * 2])

            # 估算时长 (44100Hz 采样率)
            sample_rate = 44100
            duration = n_samples / sample_rate

            # 分桶取峰值
            peaks = []
            bucket_size = max(1, n_samples // self.NUM_PEAKS)
            for i in range(0, n_samples, bucket_size):
                chunk = samples[i:i + bucket_size]
                peak = max(abs(s) for s in chunk) / 32768.0
                peaks.append(peak)

            log.info(f"[音乐卡点] 波形提取完成: {len(peaks)} 个峰值, 时长 {duration:.1f}s")
            self.peaks_ready.emit(peaks, duration)
        except Exception as e:
            log.error(f"[音乐卡点] 波形提取异常: {e}")
            self.error.emit(f"波形提取失败: {e}")


# ═══════════════════════════════════════════════════════════
# 声波波形图控件（青色振幅 + 白色节拍线 + 播放游标）
# ═══════════════════════════════════════════════════════════

class WaveformBeatWidget(QWidget):
    """真实声波波形图控件。

    视觉样式（参照专业音频编辑器）：
    - 青色(cyan)填充振幅波形，上下对称
    - 白色细横线为波形边界
    - 白色竖线标记节拍点
    - 红色竖线 + 三角为当前播放位置
    - 音乐过长时显示局部窗口，随播放位置/滑块自动滚动
    """
    slot_clicked = Signal(int)  # 用户点击某个节拍区间

    # 可视窗口时长（秒），超过此时长的音乐将滚动显示
    VIEW_WINDOW_SEC = 30.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._peaks = []          # 整轨峰值列表 (0~1)
        self._duration = 0.0      # 音频总时长(秒)
        self._beats = []          # 节拍时间戳(秒)
        self._clip_slots = []     # 每个节拍间隔对应的镜头文件名
        self._play_pos = 0.0      # 当前播放位置(秒)
        self._view_start = 0.0    # 可视窗口起始时间(秒)

    # ─── 数据接口 ───

    def set_peaks(self, peaks, duration):
        """设置波形峰值数据和总时长。"""
        self._peaks = peaks
        self._duration = duration
        self._view_start = 0.0
        self.update()

    def set_beats(self, beats, duration=0):
        """设置节拍时间戳列表。"""
        self._beats = sorted(beats)
        if duration and duration > 0:
            self._duration = duration
        elif not self._duration and beats:
            self._duration = beats[-1] + 1.0
        self._clip_slots = [""] * max(0, len(self._beats) - 1)
        self.update()

    def set_clip_slot(self, slot_idx, clip_name):
        if 0 <= slot_idx < len(self._clip_slots):
            self._clip_slots[slot_idx] = clip_name
            self.update()

    def set_all_clip_slots(self, names):
        self._clip_slots = list(names)
        self.update()

    def set_play_position(self, pos_sec):
        """设置播放位置并自动滚动可视窗口。"""
        self._play_pos = pos_sec
        self._ensure_visible(pos_sec)
        self.update()

    def seek_view(self, pos_sec):
        """滑块拖动时定位视图中心。"""
        self._ensure_visible(pos_sec)
        self.update()

    def _ensure_visible(self, t):
        """确保时间 t 在可视窗口内，必要时滚动。"""
        view_w = min(self.VIEW_WINDOW_SEC, self._duration) if self._duration > 0 else self.VIEW_WINDOW_SEC
        if self._duration <= view_w:
            self._view_start = 0.0
            return
        margin = view_w * 0.15
        if t < self._view_start + margin:
            self._view_start = max(0.0, t - view_w * 0.5)
        elif t > self._view_start + view_w - margin:
            self._view_start = min(t - view_w * 0.5, self._duration - view_w)
        self._view_start = max(0.0, self._view_start)

    def _view_window(self):
        """返回 (start_sec, end_sec) 可视时间窗口。"""
        if self._duration <= 0:
            return 0.0, 1.0
        view_w = min(self.VIEW_WINDOW_SEC, self._duration)
        start = max(0.0, min(self._view_start, self._duration - view_w))
        return start, start + view_w

    def _time_to_x(self, t, w):
        start, end = self._view_window()
        span = end - start
        if span <= 0:
            return 0
        return (t - start) / span * w

    def _x_to_time(self, x, w):
        start, end = self._view_window()
        if w <= 0:
            return start
        return start + x / w * (end - start)

    def _x_to_slot(self, x, w):
        """根据 x 坐标返回节拍槽位索引。"""
        if len(self._beats) < 2:
            return -1
        t = self._x_to_time(x, w)
        for i in range(len(self._beats) - 1):
            if self._beats[i] <= t < self._beats[i + 1]:
                return i
        return -1

    # ─── 绘制 ───

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()

        # 深色背景
        painter.fillRect(0, 0, w, h, QColor("#141422"))

        pad_top, pad_bottom = 8, 24  # 底部留空给槽位标签
        wave_top = pad_top
        wave_bottom = h - pad_bottom
        wave_h = wave_bottom - wave_top
        mid_y = wave_top + wave_h / 2

        if not self._peaks and not self._beats:
            painter.setPen(QColor("#666"))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, "选择音乐后自动加载波形，检测节拍后显示节拍线")
            painter.end()
            return

        # ── 白色边界线（上下） ──
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.drawLine(0, wave_top, w, wave_top)
        painter.drawLine(0, wave_bottom, w, wave_bottom)

        # ── 青色波形填充 ──
        if self._peaks:
            start_t, end_t = self._view_window()
            n_peaks = len(self._peaks)
            # 峰值索引范围
            idx_start = int(start_t / self._duration * n_peaks) if self._duration > 0 else 0
            idx_end = int(end_t / self._duration * n_peaks) + 1 if self._duration > 0 else n_peaks
            idx_start = max(0, min(idx_start, n_peaks - 1))
            idx_end = max(idx_start + 1, min(idx_end, n_peaks))

            visible_peaks = self._peaks[idx_start:idx_end]
            n_vis = len(visible_peaks)
            if n_vis > 0:
                # 构建波形多边形（上半部分从左到右，下半部分从右到左）
                poly = QPolygonF()
                half_h = wave_h / 2 - 2
                step_x = w / max(1, n_vis - 1) if n_vis > 1 else w

                for i, p in enumerate(visible_peaks):
                    x = i * step_x
                    amp = p * half_h
                    poly.append(QPointF(x, mid_y - amp))
                for i in range(n_vis - 1, -1, -1):
                    x = i * step_x
                    amp = visible_peaks[i] * half_h
                    poly.append(QPointF(x, mid_y + amp))

                # 青色渐变填充
                gradient = QLinearGradient(0, wave_top, 0, wave_bottom)
                gradient.setColorAt(0.0, QColor(0, 220, 220, 220))
                gradient.setColorAt(0.5, QColor(0, 180, 200, 255))
                gradient.setColorAt(1.0, QColor(0, 220, 220, 220))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawPolygon(poly)

                # 中线
                painter.setPen(QPen(QColor(0, 255, 255, 100), 1))
                painter.drawLine(0, int(mid_y), w, int(mid_y))

        # ── 白色节拍竖线 ──
        if self._beats:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            for bt in self._beats:
                x = self._time_to_x(bt, w)
                if 0 <= x <= w:
                    painter.drawLine(int(x), wave_top, int(x), wave_bottom)

            # 底部节拍间隔标签（镜头槽位）
            painter.setFont(QFont("Consolas", 7))
            for i in range(len(self._beats) - 1):
                x1 = self._time_to_x(self._beats[i], w)
                x2 = self._time_to_x(self._beats[i + 1], w)
                if x2 < 0 or x1 > w or (x2 - x1) < 20:
                    continue
                name = self._clip_slots[i] if i < len(self._clip_slots) else ""
                label = name[:8] if name else str(i + 1)
                color = QColor("#2ecc71") if name else QColor("#888")
                painter.setPen(color)
                cx = (max(0, x1) + min(w, x2)) / 2
                painter.drawText(QRectF(cx - 30, wave_bottom + 4, 60, 16),
                                 Qt.AlignCenter, label)

        # ── 红色播放游标 ──
        if self._duration > 0:
            px = self._time_to_x(self._play_pos, w)
            if 0 <= px <= w:
                painter.setPen(QPen(QColor("#e74c3c"), 2))
                painter.drawLine(int(px), wave_top - 4, int(px), wave_bottom + 4)
                # 顶部三角
                painter.setBrush(QBrush(QColor("#e74c3c")))
                painter.setPen(Qt.NoPen)
                painter.drawPolygon([
                    QPointF(px - 5, wave_top - 8),
                    QPointF(px + 5, wave_top - 8),
                    QPointF(px, wave_top - 1),
                ])

        painter.end()

    def mousePressEvent(self, event):
        idx = self._x_to_slot(int(event.position().x()), self.width())
        if idx >= 0:
            self.slot_clicked.emit(idx)
        else:
            super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════
# 音乐卡点页面
# ═══════════════════════════════════════════════════════════

class StepBeatView(BaseStepView):
    """音乐卡点混剪页面"""

    def __init__(self, main_page):
        super().__init__(main_page)
        self._peak_worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)

        # ── 标题 ──
        title_row = QHBoxLayout()
        title_lbl = QLabel("🎵 音乐卡点混剪")
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: bold; color: #f9c74f;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        card_layout.addLayout(title_row)

        # ── 已选分割镜头行（顶部，可重新选择）──
        clips_row = QHBoxLayout()
        self.main_page.beat_clips_info_lbl = QLabel("已选分割镜头: 0 个")
        self.main_page.beat_clips_info_lbl.setStyleSheet("color: #2ecc71; font-weight: bold;")
        clips_row.addWidget(self.main_page.beat_clips_info_lbl)
        clips_row.addStretch()
        self.main_page.btn_beat_reselect = mdi_button("重新选择镜头", "refresh")
        self.main_page.btn_beat_reselect.setObjectName("secondary_button")
        self.main_page.btn_beat_reselect.clicked.connect(self.main_page._open_clip_selection_dialog)
        clips_row.addWidget(self.main_page.btn_beat_reselect)
        card_layout.addLayout(clips_row)

        # ── 音乐选择行 ──
        music_row = QHBoxLayout()
        music_row.addWidget(QLabel("卡点音乐:"))
        self.main_page.beat_music_path = QLineEdit()
        self.main_page.beat_music_path.setPlaceholderText("选择音乐文件（mp3/wav/m4a/aac/flac）...")
        self.main_page.beat_music_path.setReadOnly(True)
        music_row.addWidget(self.main_page.beat_music_path, 1)

        self.main_page.btn_beat_browse = QPushButton("选择音乐")
        self.main_page.btn_beat_browse.setObjectName("secondary_button")
        self.main_page.btn_beat_browse.clicked.connect(self.main_page._beat_browse_music)
        music_row.addWidget(self.main_page.btn_beat_browse)

        self.main_page.btn_beat_detect = mdi_button("检测节拍", "audio")
        self.main_page.btn_beat_detect.setObjectName("primary_button")
        self.main_page.btn_beat_detect.setEnabled(False)
        self.main_page.btn_beat_detect.clicked.connect(self.main_page._beat_start_detect)
        music_row.addWidget(self.main_page.btn_beat_detect)
        card_layout.addLayout(music_row)

        # ── 声波波形图（含节拍线）──
        self.main_page.beat_waveform = WaveformBeatWidget()
        self.main_page.beat_waveform.slot_clicked.connect(self.main_page._beat_on_slot_clicked)
        card_layout.addWidget(self.main_page.beat_waveform)

        # ── 播放控制行（波形下方）──
        player_row = QHBoxLayout()
        self.main_page.btn_beat_play = QPushButton("▶")
        self.main_page.btn_beat_play.setObjectName("secondary_button")
        self.main_page.btn_beat_play.setFixedSize(40, 32)
        self.main_page.btn_beat_play.setEnabled(False)
        self.main_page.btn_beat_play.clicked.connect(self._toggle_play)
        player_row.addWidget(self.main_page.btn_beat_play)

        self.main_page.beat_time_lbl = QLabel("0:00")
        self.main_page.beat_time_lbl.setFixedWidth(45)
        self.main_page.beat_time_lbl.setStyleSheet("font-family: Consolas; font-size: 10pt;")
        player_row.addWidget(self.main_page.beat_time_lbl)

        self.main_page.beat_duration_lbl = QLabel("/ 0:00")
        self.main_page.beat_duration_lbl.setFixedWidth(55)
        self.main_page.beat_duration_lbl.setObjectName("muted_text")
        self.main_page.beat_duration_lbl.setStyleSheet("font-family: Consolas;")
        player_row.addWidget(self.main_page.beat_duration_lbl)
        player_row.addStretch()
        card_layout.addLayout(player_row)

        # ── 大定位滑动条（快速定位当前播放点）──
        self.main_page.beat_progress_slider = QSlider(Qt.Horizontal)
        self.main_page.beat_progress_slider.setRange(0, 1000)
        self.main_page.beat_progress_slider.setValue(0)
        self.main_page.beat_progress_slider.setEnabled(False)
        self.main_page.beat_progress_slider.setMinimumHeight(30)
        self.main_page.beat_progress_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 10px; background: #2d2d44; border-radius: 5px; }
            QSlider::handle:horizontal { width: 20px; height: 20px; margin: -5px 0;
                                         background: #00d4dc; border-radius: 10px; }
            QSlider::sub-page:horizontal { background: #00a8b0; border-radius: 5px; }
        """)
        self.main_page.beat_progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.main_page.beat_progress_slider.sliderReleased.connect(self._on_slider_released)
        self.main_page.beat_progress_slider.sliderMoved.connect(self._on_slider_moved)
        card_layout.addWidget(self.main_page.beat_progress_slider)

        # 初始化播放器
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.8)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_player_position)
        self._player.durationChanged.connect(self._on_player_duration)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)
        self._slider_pressed = False

        # ── 镜头槽位详情列表 ──
        self.main_page.beat_slots_scroll = QScrollArea()
        self.main_page.beat_slots_scroll.setWidgetResizable(True)
        self.main_page.beat_slots_scroll.setFixedHeight(160)
        self.main_page.beat_slots_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #333; border-radius: 4px; background: #1e1e2e; }")
        self.main_page.beat_slots_container = QWidget()
        self.main_page.beat_slots_layout = QVBoxLayout(self.main_page.beat_slots_container)
        self.main_page.beat_slots_layout.setContentsMargins(8, 8, 8, 8)
        self.main_page.beat_slots_layout.setSpacing(4)
        self.main_page.beat_slots_scroll.setWidget(self.main_page.beat_slots_container)
        card_layout.addWidget(self.main_page.beat_slots_scroll)

        # ── 状态信息 ──
        self.main_page.beat_status_lbl = QLabel("请先选择音乐文件，然后点击「检测节拍」")
        self.main_page.beat_status_lbl.setObjectName("muted_text")
        card_layout.addWidget(self.main_page.beat_status_lbl)

        # ── 镜头分配工具栏 ──
        assign_row = QHBoxLayout()
        self.main_page.btn_beat_auto_assign = mdi_button("自动分配镜头", "refresh")
        self.main_page.btn_beat_auto_assign.setObjectName("secondary_button")
        self.main_page.btn_beat_auto_assign.setEnabled(False)
        self.main_page.btn_beat_auto_assign.setToolTip("将已勾选的镜头按评分顺序自动填入各节拍槽位")
        self.main_page.btn_beat_auto_assign.clicked.connect(self.main_page._beat_auto_assign)
        assign_row.addWidget(self.main_page.btn_beat_auto_assign)

        assign_row.addSpacing(12)
        assign_row.addWidget(QLabel("转场:"))
        self.main_page.beat_transition_combo = QComboBox()
        self.main_page.beat_transition_combo.addItem("淡入淡出", "dissolve")
        self.main_page.beat_transition_combo.addItem("模糊", "fade")
        self.main_page.beat_transition_combo.addItem("左移", "slideleft")
        self.main_page.beat_transition_combo.addItem("右移", "slideright")
        self.main_page.beat_transition_combo.addItem("推进", "zoomin")
        self.main_page.beat_transition_combo.setFixedWidth(100)
        assign_row.addWidget(self.main_page.beat_transition_combo)

        assign_row.addStretch()

        self.main_page.btn_beat_confirm = mdi_button("确认卡点合成", "check")
        self.main_page.btn_beat_confirm.setObjectName("action_button")
        self.main_page.btn_beat_confirm.setFixedHeight(35)
        self.main_page.btn_beat_confirm.setEnabled(False)
        self.main_page.btn_beat_confirm.clicked.connect(self.main_page._beat_confirm_compose)
        assign_row.addWidget(self.main_page.btn_beat_confirm)
        card_layout.addLayout(assign_row)

        layout.addWidget(card, 1)

        # ── 导航行 ──
        nav_row = QHBoxLayout()
        btn_back = mdi_button("上一步：镜头分割", "left")
        btn_back.setObjectName("secondary_button")
        btn_back.clicked.connect(lambda: self.main_page._go_to_step(0))
        nav_row.addWidget(btn_back)
        nav_row.addStretch()
        layout.addLayout(nav_row)

    # ──────────────── 波形提取 ────────────────

    def extract_waveform(self, path):
        """后台提取音频波形峰值。"""
        if self._peak_worker and self._peak_worker.isRunning():
            self._peak_worker.terminate()
            self._peak_worker.wait(2000)
        self._peak_worker = WaveformPeakWorker(path, self)
        self._peak_worker.peaks_ready.connect(self._on_peaks_ready)
        self._peak_worker.error.connect(
            lambda e: log.warning(f"[音乐卡点] {e}"))
        self._peak_worker.start()

    def _on_peaks_ready(self, peaks, duration):
        """波形数据就绪，更新波形图。"""
        self.main_page.beat_waveform.set_peaks(peaks, duration)
        if duration > 0:
            self.main_page.beat_duration_lbl.setText(f"/ {self._fmt_time(int(duration * 1000))}")

    # ──────────────── 音乐播放控制 ────────────────

    def load_music(self, path):
        """加载音乐文件到播放器并提取波形。"""
        if not path or not os.path.isfile(path):
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self.main_page.btn_beat_play.setEnabled(True)
        self.main_page.beat_progress_slider.setEnabled(True)
        # 后台提取波形
        self.extract_waveform(path)

    def _toggle_play(self):
        """播放/暂停切换。"""
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self.main_page.btn_beat_play.setText("▶")
        else:
            self._player.play()
            self.main_page.btn_beat_play.setText("⏸")

    def _on_player_position(self, pos_ms):
        """播放进度更新。"""
        if self._slider_pressed:
            return
        dur = self._player.duration() or 1
        self.main_page.beat_progress_slider.setValue(int(pos_ms / dur * 1000))
        self.main_page.beat_time_lbl.setText(self._fmt_time(pos_ms))
        # 更新波形图播放游标（自动滚动视图）
        self.main_page.beat_waveform.set_play_position(pos_ms / 1000.0)

    def _on_player_duration(self, dur_ms):
        """总时长更新。"""
        self.main_page.beat_duration_lbl.setText(f"/ {self._fmt_time(dur_ms)}")

    def _on_media_status(self, status):
        """播放结束处理。"""
        if status == QMediaPlayer.EndOfMedia:
            self.main_page.btn_beat_play.setText("▶")
            self.main_page.beat_progress_slider.setValue(0)
            self.main_page.beat_waveform.set_play_position(0)

    def _on_player_error(self, error, error_string):
        """播放器错误处理。"""
        log.error(f"[音乐卡点] 播放器错误: {error} - {error_string}")
        self.main_page.btn_beat_play.setText("▶")
        self.main_page.beat_status_lbl.setText(f"❌ 播放失败: {error_string}")

    def _on_slider_pressed(self):
        self._slider_pressed = True

    def _on_slider_moved(self, value):
        """拖动滑块时实时预览定位（波形视图跟随）。"""
        dur = self._player.duration() or 1
        pos_sec = value / 1000 * dur / 1000.0
        self.main_page.beat_time_lbl.setText(self._fmt_time(int(value / 1000 * dur)))
        self.main_page.beat_waveform.seek_view(pos_sec)

    def _on_slider_released(self):
        self._slider_pressed = False
        dur = self._player.duration() or 1
        pos = int(self.main_page.beat_progress_slider.value() / 1000 * dur)
        self._player.setPosition(pos)

    @staticmethod
    def _fmt_time(ms):
        """毫秒转 m:ss 格式。"""
        s = int(ms / 1000)
        return f"{s // 60}:{s % 60:02d}"
