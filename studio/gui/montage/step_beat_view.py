# -*- coding: utf-8 -*-
"""卡点成片界面（一键成片 → 卡点成片 tab）

流程：选择音乐 + 镜头素材目录 → 检测卡点（/audio/beatmap 返回片段）→ 按片段生成 N 个波形卡片
      → 服务端 /montage/beat 逐段生成视频并下载 → 播放片段即播放对应卡点视频（右侧视频预览）→ 导出视频
本界面控件挂载到 BeatMontageController（充当 main_page 角色）。
"""
import os
import struct
import subprocess
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                               QFrame, QComboBox, QWidget, QScrollArea, QSizePolicy, QSpinBox,
                               QProgressBar)
from PySide6.QtCore import Qt, Signal, QRectF, QThread, QUrl, QPointF
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QFont,
                           QLinearGradient, QPolygonF, QPixmap)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
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
# 片段波形控件（青色振幅 + 白色节拍线 + 可拖拽红色游标把手）
# ═══════════════════════════════════════════════════════════

class SegmentWaveformWidget(QWidget):
    """单个音乐片段的波形控件。

    - 青色渐变填充振幅波形（从整轨峰值按片段时间范围切片渲染）
    - 白色竖线标记片段内节拍点 + 底部槽位标签
    - 红色加高游标 + 顶部把手，可拖动作为进度条定位
    - 点击槽位（非游标）触发镜头分配
    """
    slot_clicked = Signal(int)        # 点击某个槽位（全局槽位索引）
    seek_requested = Signal(float)    # 拖动游标请求定位（绝对时间秒）

    HANDLE_HIT = 14  # 游标把手命中容差(px)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setMaximumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

        self._full_peaks = []       # 整轨峰值 (0~1)
        self._full_duration = 0.0   # 整轨时长(秒)
        self._seg_start = 0.0       # 片段起始(秒)
        self._seg_end = 0.0         # 片段结束(秒)
        self._beats = []            # 片段内节拍绝对时间(秒)
        self._slot_start = 0        # 片段首个槽位的全局索引
        self._slot_names = []       # 各槽位已分配镜头文件名
        self._play_pos = 0.0        # 当前播放位置(绝对秒)
        self._dragging = False
        self._slots_enabled = True  # 是否启用槽位标签与点击分配

    # ─── 数据接口 ───

    def set_data(self, full_peaks, full_duration, seg_start, seg_end, beats_abs, slot_start):
        self._full_peaks = list(full_peaks or [])
        self._full_duration = float(full_duration or 0.0)
        self._seg_start = float(seg_start)
        self._seg_end = float(seg_end)
        self._beats = sorted(float(b) for b in (beats_abs or []))
        self._slot_start = int(slot_start)
        self._slot_names = [""] * max(0, len(self._beats) - 1)
        self._play_pos = self._seg_start
        self.update()

    def set_slot_name(self, local_idx, name):
        if 0 <= local_idx < len(self._slot_names):
            self._slot_names[local_idx] = name or ""
            self.update()

    def set_all_slot_names(self, names):
        self._slot_names = list(names or [])
        self.update()

    def set_play_pos(self, abs_sec):
        self._play_pos = float(abs_sec)
        self.update()

    def set_slots_enabled(self, enabled):
        """启用/禁用槽位标签显示与点击分配（整体预览卡片禁用）。"""
        self._slots_enabled = bool(enabled)
        self.update()

    # ─── 坐标换算 ───

    def _time_to_x(self, t, w):
        span = self._seg_end - self._seg_start
        if span <= 0:
            return 0
        return (t - self._seg_start) / span * w

    def _x_to_time(self, x, w):
        span = self._seg_end - self._seg_start
        if w <= 0:
            return self._seg_start
        t = self._seg_start + x / w * span
        return max(self._seg_start, min(self._seg_end, t))

    def _x_to_global_slot(self, x, w):
        if len(self._beats) < 2:
            return -1
        t = self._x_to_time(x, w)
        for i in range(len(self._beats) - 1):
            if self._beats[i] <= t < self._beats[i + 1]:
                return self._slot_start + i
        return -1

    # ─── 绘制 ───

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor("#141422"))

        pad_top, pad_bottom = 12, 18
        wave_top = pad_top
        wave_bottom = h - pad_bottom
        wave_h = wave_bottom - wave_top
        mid_y = wave_top + wave_h / 2

        # 白色边界线
        painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
        painter.drawLine(0, wave_top, w, wave_top)
        painter.drawLine(0, wave_bottom, w, wave_bottom)

        # 青色波形（从整轨峰值按片段范围切片）
        if self._full_peaks and self._full_duration > 0 and self._seg_end > self._seg_start:
            n_peaks = len(self._full_peaks)
            idx_start = int(self._seg_start / self._full_duration * n_peaks)
            idx_end = int(self._seg_end / self._full_duration * n_peaks) + 1
            idx_start = max(0, min(idx_start, n_peaks - 1))
            idx_end = max(idx_start + 1, min(idx_end, n_peaks))
            vis = self._full_peaks[idx_start:idx_end]
            n_vis = len(vis)
            if n_vis > 0:
                poly = QPolygonF()
                half_h = wave_h / 2 - 2
                step_x = w / max(1, n_vis - 1) if n_vis > 1 else w
                for i, p in enumerate(vis):
                    poly.append(QPointF(i * step_x, mid_y - p * half_h))
                for i in range(n_vis - 1, -1, -1):
                    poly.append(QPointF(i * step_x, mid_y + vis[i] * half_h))
                gradient = QLinearGradient(0, wave_top, 0, wave_bottom)
                gradient.setColorAt(0.0, QColor(0, 220, 220, 220))
                gradient.setColorAt(0.5, QColor(0, 180, 200, 255))
                gradient.setColorAt(1.0, QColor(0, 220, 220, 220))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawPolygon(poly)
                painter.setPen(QPen(QColor(0, 255, 255, 90), 1))
                painter.drawLine(0, int(mid_y), w, int(mid_y))

        # 白色节拍竖线 + 底部槽位标签
        if self._beats:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
            for bt in self._beats:
                x = self._time_to_x(bt, w)
                if 0 <= x <= w:
                    painter.drawLine(int(x), wave_top, int(x), wave_bottom)
            if self._slots_enabled:
                painter.setFont(QFont("Consolas", 7))
                for i in range(len(self._beats) - 1):
                    x1 = self._time_to_x(self._beats[i], w)
                    x2 = self._time_to_x(self._beats[i + 1], w)
                    if x2 < 0 or x1 > w or (x2 - x1) < 18:
                        continue
                    name = self._slot_names[i] if i < len(self._slot_names) else ""
                    label = (name[:8] if name else str(self._slot_start + i + 1))
                    painter.setPen(QColor("#2ecc71") if name else QColor("#888"))
                    cx = (max(0, x1) + min(w, x2)) / 2
                    painter.drawText(QRectF(cx - 30, wave_bottom + 2, 60, 14),
                                     Qt.AlignCenter, label)

        # 红色播放游标（加粗 + 大号顶部把手，可拖动）
        if self._seg_end > self._seg_start:
            px = self._time_to_x(self._play_pos, w)
            if 0 <= px <= w:
                handle_top = 1
                handle_bottom = h - 1
                painter.setPen(QPen(QColor("#e74c3c"), 3))
                painter.drawLine(int(px), handle_top + 12, int(px), handle_bottom)
                # 顶部把手（大三角 + 圆点）
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor("#e74c3c")))
                painter.drawPolygon([
                    QPointF(px - 9, handle_top),
                    QPointF(px + 9, handle_top),
                    QPointF(px, handle_top + 13),
                ])
                painter.drawEllipse(QPointF(px, handle_top), 4, 4)

        painter.end()

    # ─── 鼠标交互：拖动游标定位 / 点击槽位分配 ───

    def mousePressEvent(self, event):
        x = int(event.position().x())
        w = self.width()
        px = self._time_to_x(self._play_pos, w)
        if abs(x - px) <= self.HANDLE_HIT:
            self._dragging = True
            self.seek_requested.emit(self._x_to_time(x, w))
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.seek_requested.emit(self._x_to_time(int(event.position().x()), self.width()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.seek_requested.emit(self._x_to_time(int(event.position().x()), self.width()))
            return
        if self._slots_enabled:
            idx = self._x_to_global_slot(int(event.position().x()), self.width())
            if idx >= 0:
                self.slot_clicked.emit(idx)
        super().mouseReleaseEvent(event)


# ═══════════════════════════════════════════════════════════
# 片段卡片（波形 + 播放按钮 + 进度条 + 内置播放器）
# ═══════════════════════════════════════════════════════════

class BeatSegmentCard(QFrame):
    """单个音乐片段卡片：波形图 + 播放控制 + 进度条，内置独立 QMediaPlayer。

    播放时仅播放本片段 [seg_start, seg_end] 区间，超出自动暂停并回退到起点。
    """
    slot_clicked = Signal(int)             # 全局槽位索引
    play_started = Signal(object)          # 本卡片开始播放（card）
    position_changed = Signal(object, float)  # 播放进度（card, 绝对秒）
    finished = Signal(object)              # 播放到片段末尾（card）

    def __init__(self, index, seg_start, seg_end, beats_abs, slot_start, music_path,
                 is_full_track=False, parent=None):
        super().__init__(parent)
        self.index = index
        self.seg_start = float(seg_start)
        self.seg_end = float(seg_end)
        self.beats = list(beats_abs or [])
        self.slot_start = int(slot_start)
        self.music_path = music_path
        self.is_full_track = is_full_track
        # 服务端下载的卡点视频（有则优先播放视频，否则回退播放音乐）
        self._video_path = None
        self._in_video_mode = False
        self._current_src = None

        self.setObjectName("segment_card")
        self.setStyleSheet(
            "#segment_card { border: 1px solid #33334d; border-radius: 6px; background: #1b1b28; }")

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 6, 8, 6)
        vbox.setSpacing(4)

        # 标题行
        if is_full_track:
            n_bp = max(0, len(self.beats) - 1)
            if n_bp > 0:
                title_text = (f"🎵 整体卡点（全曲 {self.seg_start:.1f}s ~ {self.seg_end:.1f}s，"
                              f"共 {n_bp} 个卡点）")
            else:
                title_text = f"🎵 全曲预览（{self.seg_start:.1f}s ~ {self.seg_end:.1f}s）"
        else:
            title_text = (f"🎬 片段 {index + 1}：{self.seg_start:.1f}s ~ {self.seg_end:.1f}s  "
                          f"({self.seg_end - self.seg_start:.1f}s) → 将生成视频 {index + 1}")
        title = QLabel(title_text)
        title.setStyleSheet("color: #f9c74f; font-weight: bold; font-size: 12px;")
        vbox.addWidget(title)

        # 主体：左侧按钮列 + 右侧（波形 + 时间）
        body = QHBoxLayout()
        body.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        left_col.addStretch()
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("secondary_button")
        if is_full_track:
            self.btn_play.setFixedSize(64, 64)
            self.btn_play.setStyleSheet("font-size: 22px;")
        else:
            self.btn_play.setFixedSize(56, 42)
            self.btn_play.setStyleSheet("font-size: 16px;")
        self.btn_play.clicked.connect(self.toggle_play)
        left_col.addWidget(self.btn_play)

        left_col.addStretch()
        body.addLayout(left_col)

        right_col = QVBoxLayout()
        right_col.setSpacing(1)
        self.waveform = SegmentWaveformWidget()
        if is_full_track:
            self.waveform.set_slots_enabled(False)
        self.waveform.slot_clicked.connect(lambda gi: self.slot_clicked.emit(gi))
        self.waveform.seek_requested.connect(self._on_seek_requested)
        right_col.addWidget(self.waveform, 1)

        # 时间刻度条（波形图最下方，一行字高度，黄色字体）
        self.time_lbl = QLabel(self._fmt_range(self.seg_start))
        self.time_lbl.setFixedHeight(18)
        self.time_lbl.setAlignment(Qt.AlignCenter)
        self.time_lbl.setStyleSheet(
            "background: #2d2d44; color: #f9c74f; font-family: Consolas; "
            "font-size: 9pt; font-weight: bold; border-radius: 3px;")
        right_col.addWidget(self.time_lbl)
        body.addLayout(right_col, 1)

        vbox.addLayout(body, 1)

        # 内置播放器
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.8)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_position)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(
            lambda e, s: log.warning(f"[音乐卡点] 片段{index + 1}播放错误: {s}"))
        if music_path and os.path.isfile(music_path):
            self._player.setSource(QUrl.fromLocalFile(music_path))
            self._current_src = music_path

    # ─── 视频支持（服务端下载的卡点视频）───

    def set_video(self, path):
        """设置本片段已下载的卡点视频，播放时优先使用该视频。"""
        self._video_path = path

    def set_video_output(self, video_widget):
        """将播放器视频输出路由到共享预览控件（QVideoWidget）。"""
        try:
            self._player.setVideoOutput(video_widget)
        except Exception as e:
            log.warning(f"[音乐卡点] 设置视频输出失败: {e}")

    # ─── 播放控制 ───

    def toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            self.play()

    def play(self):
        use_video = bool(self._video_path and os.path.isfile(self._video_path))
        self._in_video_mode = use_video
        if use_video:
            # 视频模式：播放服务端下载的卡点视频（含画面+音乐），
            # 视频时间轴 0 对应波形 seg_start
            if self._current_src != self._video_path:
                self._player.setSource(QUrl.fromLocalFile(self._video_path))
                self._current_src = self._video_path
                self._player.setPosition(0)
                self.waveform.set_play_pos(self.seg_start)
                self.time_lbl.setText(self._fmt_range(self.seg_start))
        else:
            # 音乐模式：播放整轨音乐的 [seg_start, seg_end] 区间，
            # 游标不在本片段内（初始 0 / 已到片段末尾）先回到片段起点
            pos = self._player.position() / 1000.0
            if pos < self.seg_start - 0.05 or pos >= self.seg_end - 0.05:
                self._player.setPosition(int(self.seg_start * 1000))
                self.waveform.set_play_pos(self.seg_start)
                self.time_lbl.setText(self._fmt_range(self.seg_start))
        self._player.play()
        self.btn_play.setText("⏸")
        self.play_started.emit(self)

    def pause(self):
        self._player.pause()
        self.btn_play.setText("▶")

    def stop(self):
        self._player.stop()
        self.btn_play.setText("▶")

    def is_playing(self):
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def seek(self, abs_sec):
        abs_sec = max(self.seg_start, min(self.seg_end, float(abs_sec)))
        if self._in_video_mode:
            # 视频模式：把片段绝对位置等比映射到变体视频自身时间轴
            span = self.seg_end - self.seg_start
            vdur = self._player.duration() / 1000.0
            ratio = ((abs_sec - self.seg_start) / span) if span > 0 else 0.0
            self._player.setPosition(int(ratio * vdur * 1000))
            self.time_lbl.setText(f"{self._fmt(ratio * vdur)} / {self._fmt(vdur)}")
        else:
            self._player.setPosition(int(abs_sec * 1000))
            self.time_lbl.setText(self._fmt_range(abs_sec))
        self.waveform.set_play_pos(abs_sec)

    def position(self):
        return self._player.position() / 1000.0

    # ─── 槽位 ───

    def set_slot(self, local_idx, clip_name):
        self.waveform.set_slot_name(local_idx, clip_name)

    def refresh_slots_from_assignments(self, assignments):
        n = max(0, len(self.beats) - 1)
        names = []
        for j in range(n):
            gi = self.slot_start + j
            path = assignments[gi] if gi < len(assignments) else None
            names.append(os.path.basename(path) if path else "")
        self.waveform.set_all_slot_names(names)

    # ─── 内部回调 ───

    def _on_position(self, pos_ms):
        if self._in_video_mode:
            # 视频模式：变体视频是整段音乐成片，按视频自身时长播放（0..vdur），
            # 游标按视频进度在片段波形 [seg_start, seg_end] 上等比移动（仅作可视化反馈）
            rel = pos_ms / 1000.0
            vdur = self._player.duration() / 1000.0
            if vdur > 0.1 and rel >= vdur - 0.05:
                self._player.pause()
                self._player.setPosition(0)
                self.btn_play.setText("▶")
                self.waveform.set_play_pos(self.seg_start)
                self.time_lbl.setText(f"{self._fmt(0.0)} / {self._fmt(vdur)}")
                self.finished.emit(self)
                return
            ratio = (rel / vdur) if vdur > 0.1 else 0.0
            span = self.seg_end - self.seg_start
            abs_sec = self.seg_start + ratio * span
            self.waveform.set_play_pos(abs_sec)
            self.time_lbl.setText(f"{self._fmt(rel)} / {self._fmt(vdur if vdur > 0.1 else rel)}")
            self.position_changed.emit(self, abs_sec)
            return
        # 音乐模式：pos 是整轨绝对时间
        abs_sec = pos_ms / 1000.0
        if abs_sec >= self.seg_end:
            self._player.pause()
            self._player.setPosition(int(self.seg_start * 1000))
            self.btn_play.setText("▶")
            self.waveform.set_play_pos(self.seg_start)
            self.time_lbl.setText(self._fmt_range(self.seg_start))
            self.finished.emit(self)
            return
        self.waveform.set_play_pos(abs_sec)
        self.time_lbl.setText(self._fmt_range(abs_sec))
        self.position_changed.emit(self, abs_sec)

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.btn_play.setText("▶")
            self.finished.emit(self)

    def _on_seek_requested(self, abs_sec):
        self.seek(abs_sec)
        self.position_changed.emit(self, abs_sec)

    def _fmt_range(self, abs_sec):
        rel = max(0.0, abs_sec - self.seg_start)
        total = self.seg_end - self.seg_start
        return f"{self._fmt(rel)} / {self._fmt(total)}"

    @staticmethod
    def _fmt(sec):
        s = int(sec)
        return f"{s // 60}:{s % 60:02d}"


# ═══════════════════════════════════════════════════════════
# 音乐卡点页面
# ═══════════════════════════════════════════════════════════

class StepBeatView(BaseStepView):
    """音乐卡点混剪页面"""

    def __init__(self, main_page):
        super().__init__(main_page)
        self._peak_worker = None
        self._full_peaks = []
        self._full_duration = 0.0
        self._music_path = ""
        self.segment_cards = []
        self._active_card = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)
        card_layout.setContentsMargins(12, 8, 12, 10)

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
        card_layout.addLayout(music_row)

        # ── 镜头素材 + 导出目录行 ──
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("镜头素材:"))
        self.main_page.beat_materials_input = QLineEdit()
        self.main_page.beat_materials_input.setPlaceholderText("选择一个或多个视频/图片素材（图片默认 2 秒，随音乐卡点变化）...")
        self.main_page.beat_materials_input.setReadOnly(True)
        dir_row.addWidget(self.main_page.beat_materials_input, 1)
        btn_sel_materials = QPushButton("选择素材")
        btn_sel_materials.setObjectName("secondary_button")
        btn_sel_materials.clicked.connect(self.main_page._beat_select_materials)
        dir_row.addWidget(btn_sel_materials)
        btn_arrange_materials = QPushButton("整理素材")
        btn_arrange_materials.setObjectName("secondary_button")
        btn_arrange_materials.clicked.connect(self.main_page._beat_arrange_materials)
        dir_row.addWidget(btn_arrange_materials)
        dir_row.addSpacing(16)
        dir_row.addWidget(QLabel("导出目录:"))
        self.main_page.beat_out_dir_input = QLineEdit()
        self.main_page.beat_out_dir_input.setPlaceholderText("可选，导出时选择")
        self.main_page.beat_out_dir_input.setReadOnly(True)
        dir_row.addWidget(self.main_page.beat_out_dir_input, 1)
        btn_browse_out = QPushButton("选择目录")
        btn_browse_out.setObjectName("secondary_button")
        btn_browse_out.clicked.connect(self.main_page._beat_browse_out_dir)
        dir_row.addWidget(btn_browse_out)
        card_layout.addLayout(dir_row)

        # ── 参数设置行（已选镜头 + 时长 → 转场 → 视频个数 → 检测卡点，设置整体右移）──
        settings_row = QHBoxLayout()
        self.main_page.beat_clips_info_lbl = QLabel("镜头素材: 0 个")
        self.main_page.beat_clips_info_lbl.setStyleSheet("color: #2ecc71; font-weight: bold;")
        settings_row.addWidget(self.main_page.beat_clips_info_lbl)
        settings_row.addStretch()
        settings_row.addWidget(QLabel("时长:"))
        self.main_page.beat_duration_combo = QComboBox()
        for _sec in (10, 15, 20, 30):
            self.main_page.beat_duration_combo.addItem(f"{_sec} 秒", _sec)
        self.main_page.beat_duration_combo.setCurrentIndex(1)  # 默认 15 秒
        self.main_page.beat_duration_combo.setFixedWidth(80)
        self.main_page.beat_duration_combo.setToolTip("每个成片的时长上限（传给服务端 time_limit）")
        settings_row.addWidget(self.main_page.beat_duration_combo)

        settings_row.addSpacing(12)
        settings_row.addWidget(QLabel("画面比例:"))
        self.main_page.beat_aspect_combo = QComboBox()
        self.main_page.beat_aspect_combo.addItem("方屏 1:1", "1:1")
        self.main_page.beat_aspect_combo.addItem("横屏 16:9", "16:9")
        self.main_page.beat_aspect_combo.addItem("竖屏 9:16", "9:16")
        self.main_page.beat_aspect_combo.setCurrentIndex(0)  # 默认 1:1
        self.main_page.beat_aspect_combo.setFixedWidth(110)
        self.main_page.beat_aspect_combo.setToolTip("成片画面比例（选择素材后自动检测；不一致时需手动选择）")
        self.main_page.beat_aspect_combo.currentIndexChanged.connect(
            lambda _i: self._beat_apply_preview_aspect(self.main_page.beat_aspect_combo.currentData() or "1:1"))
        settings_row.addWidget(self.main_page.beat_aspect_combo)

        settings_row.addSpacing(12)
        settings_row.addWidget(QLabel("转场:"))
        self.main_page.beat_transition_combo = QComboBox()
        self.main_page.beat_transition_combo.addItem("淡入淡出", "fade")
        self.main_page.beat_transition_combo.addItem("溶解", "dissolve")
        self.main_page.beat_transition_combo.addItem("左擦除", "wipeleft")
        self.main_page.beat_transition_combo.addItem("右擦除", "wiperight")
        self.main_page.beat_transition_combo.addItem("上滑动", "slideup")
        self.main_page.beat_transition_combo.addItem("下滑动", "slidedown")
        self.main_page.beat_transition_combo.addItem("径向扫过", "radial")
        self.main_page.beat_transition_combo.addItem("随机", "random")
        self.main_page.beat_transition_combo.addItem("硬切", "none")
        self.main_page.beat_transition_combo.setFixedWidth(100)
        settings_row.addWidget(self.main_page.beat_transition_combo)

        settings_row.addSpacing(12)
        settings_row.addWidget(QLabel("视频个数:"))
        self.main_page.beat_video_count_spin = QSpinBox()
        self.main_page.beat_video_count_spin.setRange(1, 5)
        self.main_page.beat_video_count_spin.setValue(3)
        self.main_page.beat_video_count_spin.setFixedWidth(60)
        self.main_page.beat_video_count_spin.setToolTip("要生成的卡点视频数量（一次上传，服务端 variant_count 上限 5）")
        settings_row.addWidget(self.main_page.beat_video_count_spin)

        settings_row.addSpacing(12)
        self.main_page.btn_beat_detect = mdi_button("检测卡点", "audio")
        self.main_page.btn_beat_detect.setObjectName("primary_button")
        self.main_page.btn_beat_detect.setEnabled(False)
        self.main_page.btn_beat_detect.clicked.connect(self.main_page._beat_start_detect)
        settings_row.addWidget(self.main_page.btn_beat_detect)
        card_layout.addLayout(settings_row)

        # ── 全曲预览（单独一行，占满整行宽度）──
        self.full_card_container = QWidget()
        self.full_card_layout = QVBoxLayout(self.full_card_container)
        self.full_card_layout.setContentsMargins(0, 0, 0, 0)
        self.full_card_layout.setSpacing(0)
        card_layout.addWidget(self.full_card_container)

        # ── 主体：左侧片段卡片滚动区 + 右侧播放器面板 ──
        body = QHBoxLayout()
        body.setSpacing(10)

        # 片段卡片滚动区
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #333; border-radius: 4px; background: #16161f; }")
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(8, 8, 8, 8)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()
        self.cards_scroll.setWidget(self.cards_container)
        body.addWidget(self.cards_scroll, 1)

        # 右侧：播放器面板（幻灯片预览，位于三个片段右侧）
        preview_panel = QFrame()
        preview_panel.setObjectName("preview_panel")
        preview_panel.setMaximumWidth(560)
        preview_panel.setStyleSheet(
            "#preview_panel { border: 1px solid #333; border-radius: 4px; background: #16161f; }")
        self.preview_panel = preview_panel
        pvbox = QVBoxLayout(preview_panel)
        pvbox.setContentsMargins(8, 8, 8, 8)
        pvbox.setSpacing(6)
        self.main_page.beat_preview_title = QLabel("预览播放器")
        self.main_page.beat_preview_title.setStyleSheet("color: #f9c74f; font-weight: bold;")
        pvbox.addWidget(self.main_page.beat_preview_title)
        # 视频预览（播放服务端下载的卡点视频）
        self.main_page.beat_preview_video = QVideoWidget()
        self.main_page.beat_preview_video.setMinimumSize(200, 150)
        self.main_page.beat_preview_video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_page.beat_preview_video.setStyleSheet("background: #000;")
        pvbox.addWidget(self.main_page.beat_preview_video, 1)
        body.addWidget(preview_panel)
        # 按默认比例（1:1）初始化预览面板尺寸
        self._beat_apply_preview_aspect("1:1")

        card_layout.addLayout(body, 1)

        # ── 进度条（服务端生成视频时显示）──
        self.main_page.progress_bar = QProgressBar()
        self.main_page.progress_bar.setVisible(False)
        self.main_page.progress_bar.setRange(0, 100)
        self.main_page.progress_bar.setValue(0)
        card_layout.addWidget(self.main_page.progress_bar)

        # ── 状态信息 ──
        self.main_page.beat_status_lbl = QLabel("请先选择音乐文件，然后点击「检测卡点」")
        self.main_page.beat_status_lbl.setObjectName("muted_text")
        card_layout.addWidget(self.main_page.beat_status_lbl)

        layout.addWidget(card, 1)

        # ── 导航行（导出视频靠右）──
        nav_row = QHBoxLayout()
        nav_row.addStretch()
        self.main_page.btn_beat_confirm = mdi_button("导出视频", "check")
        self.main_page.btn_beat_confirm.setObjectName("action_button")
        self.main_page.btn_beat_confirm.setFixedHeight(35)
        self.main_page.btn_beat_confirm.setEnabled(False)
        self.main_page.btn_beat_confirm.setToolTip("将生成的卡点视频导出到目录并打开")
        self.main_page.btn_beat_confirm.clicked.connect(self.main_page._beat_export_videos)
        nav_row.addWidget(self.main_page.btn_beat_confirm)
        layout.addLayout(nav_row)

    # ──────────────── 预览面板比例自适应 ────────────────

    def _beat_apply_preview_aspect(self, ratio):
        """按画面比例调整右侧预览面板宽度与视频控件尺寸。

        QVideoWidget 自身用 KeepAspectRatio 渲染（视频内容不会变形），故只需让外层
        容器尺寸匹配当前比例，即可保证三种比例都能正常显示、无明显黑边。
        """
        if not hasattr(self, "preview_panel"):
            return
        panel_w, video_h = {
            "9:16": (300, 480),   # 竖屏：窄而高（300-16=284, 284/480≈9:16）
            "16:9": (520, 293),   # 横屏：宽而矮（504/293≈16:9）
            "1:1":  (380, 380),   # 方屏：正方形
        }.get(ratio, (380, 380))
        self.preview_panel.setFixedWidth(panel_w)
        vw = self.main_page.beat_preview_video
        # panel_w-16（左右内边距）让视频控件横向贴满；setFixedSize 锁定精确比例
        vw.setFixedSize(panel_w - 16, video_h)

    # ──────────────── 波形提取 ────────────────

    def extract_waveform(self, path):
        """后台提取音频波形峰值。"""
        if self._peak_worker and self._peak_worker.isRunning():
            self._peak_worker.terminate()
            self._peak_worker.wait(2000)
        self._peak_worker = WaveformPeakWorker(path, self)
        self._peak_worker.peaks_ready.connect(self._on_peaks_ready)
        self._peak_worker.error.connect(lambda e: log.warning(f"[音乐卡点] {e}"))
        self._peak_worker.start()

    def _on_peaks_ready(self, peaks, duration):
        """波形数据就绪：缓存整轨峰值，未检测卡点时构建单张整体预览卡片。"""
        self._full_peaks = peaks
        self._full_duration = duration
        # 尚未检测卡点（无片段）→ 构建一张整体预览卡片用于音乐试听
        if not getattr(self.main_page, "_beat_segments", []):
            self.build_segment_cards([], peaks, duration, full_beats=[])

    # ──────────────── 片段卡片管理 ────────────────

    def build_segment_cards(self, segments, full_peaks, full_duration, full_beats=None):
        """根据片段列表重建波形卡片（检测完成后调用）。

        full_beats: 若不为 None，则额外在最上方生成一张「整体卡点」全曲预览卡片
                    （仅音乐播放，红色游标可拖动定位，不可分配槽位）。
        """
        self._full_peaks = list(full_peaks or [])
        self._full_duration = float(full_duration or 0.0)
        # 清空旧卡片（全曲预览行 + 片段滚动区）
        for c in list(self.segment_cards):
            c.stop()
            c.deleteLater()
        self.segment_cards = []
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        while self.full_card_layout.count():
            item = self.full_card_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # 整体卡点卡片（全曲预览，单独一行，仅音乐播放，不可分配槽位）
        if full_beats is not None:
            full_end = self._full_duration if self._full_duration > 0 else (
                full_beats[-1] + 1.0 if full_beats else 0.0)
            full_card = BeatSegmentCard(
                index=-1,
                seg_start=0.0,
                seg_end=full_end,
                beats_abs=full_beats,
                slot_start=0,
                music_path=self._music_path,
                is_full_track=True,
            )
            full_card.waveform.set_data(
                self._full_peaks, self._full_duration, 0.0, full_end, full_beats, 0)
            full_card.play_started.connect(self._on_card_play_started)
            full_card.position_changed.connect(self._on_card_position)
            self.full_card_layout.addWidget(full_card)
            self.segment_cards.append(full_card)

        for i, seg in enumerate(segments):
            card = BeatSegmentCard(
                index=i,
                seg_start=seg.get("start", 0.0),
                seg_end=seg.get("end", 0.0),
                beats_abs=seg.get("beats", []),
                slot_start=seg.get("slot_start", 0),
                music_path=self._music_path,
            )
            # 素材由服务端自动指派：槽位仅显示节拍线，不可点击分配
            card.waveform.set_slots_enabled(False)
            card.waveform.set_data(
                self._full_peaks, self._full_duration,
                seg.get("start", 0.0), seg.get("end", 0.0),
                seg.get("beats", []), seg.get("slot_start", 0))
            card.play_started.connect(self._on_card_play_started)
            card.position_changed.connect(self._on_card_position)
            self.cards_layout.addWidget(card)
            self.segment_cards.append(card)
        self.cards_layout.addStretch()

    def update_slot(self, global_idx, clip_name):
        """某全局槽位分配变化时，刷新对应卡片。"""
        for c in self.segment_cards:
            if c.is_full_track:
                continue
            n = max(0, len(c.beats) - 1)
            local = global_idx - c.slot_start
            if 0 <= local < n:
                c.set_slot(local, clip_name)
                return

    def refresh_all_slots(self, assignments):
        for c in self.segment_cards:
            if not c.is_full_track:
                c.refresh_slots_from_assignments(assignments)

    def _on_card_play_started(self, card):
        """同一时刻只允许一个卡片播放。"""
        self._active_card = card
        for c in self.segment_cards:
            if c is not card and c.is_playing():
                c.pause()
        self.main_page._beat_on_card_play_started(card)

    def _on_card_position(self, card, abs_sec):
        if self._active_card is card:
            self.main_page._beat_on_card_position(card, abs_sec)

    # ──────────────── 音乐加载 ────────────────

    def load_music(self, path):
        """加载音乐文件并提取波形。"""
        if not path or not os.path.isfile(path):
            return
        self._music_path = path
        # 新音乐：重置上一首的节拍数据、片段
        self.main_page._beat_data_full = []
        self.main_page._beat_data = []
        self.main_page._beat_clips = []
        self.main_page._beat_segments = []
        self.main_page._beat_clip_assignments = []
        self.main_page._beat_music_range = (0.0, 0.0)
        self.main_page.btn_beat_confirm.setEnabled(False)
        self.main_page.btn_beat_detect.setEnabled(True)
        self.main_page.beat_status_lbl.setText(f"已选择: {os.path.basename(path)}，点击「检测卡点」")
        # 清空旧卡片（待波形/节拍就绪后重建）
        for c in list(self.segment_cards):
            c.stop()
            c.deleteLater()
        self.segment_cards = []
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards_layout.addStretch()
        while self.full_card_layout.count():
            item = self.full_card_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # 后台提取波形
        self.extract_waveform(path)
