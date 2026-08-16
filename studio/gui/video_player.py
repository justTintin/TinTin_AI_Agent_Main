# -*- coding: utf-8 -*-
"""统一视频播放器控件：等比显示 + 播放/暂停/停止 + 进度条 + 时间显示。

全工程复用（模板预览、素材预览、混剪预览等），
避免各处各写一套 QMediaPlayer/QVideoWidget 导致
比例不识别、无控制条、行为不一致。
"""
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel,
    QDialogButtonBox,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from utils.gui_icons import icon_button, std_icon, mdi_icon


def _set_button_icon(btn, name):
    """优先使用 Qt 标准图标，缺失则回退到 mdi 图标。"""
    icon = std_icon(name)
    if icon.isNull():
        icon = mdi_icon(name)
    btn.setIcon(icon)


def format_ms(ms):
    """毫秒 -> mm:ss。"""
    ms = max(0, int(ms or 0))
    total_s = ms // 1000
    return f"{total_s // 60:02d}:{total_s % 60:02d}"


class VideoPlayerWidget(QWidget):
    """内嵌视频播放器：等比显示 + 播放/暂停 + 停止 + 进度条 + 时间。"""

    def __init__(self, parent=None, autoplay=True, show_controls=True):
        super().__init__(parent)
        self._dragging = False

        self.video_widget = QVideoWidget(self)
        # 关键：自动识别视频比例，等比缩放完整显示（不拉伸、不裁剪）
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.video_widget.setStyleSheet("background:#000;")

        self.player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self.player.setAudioOutput(self._audio)
        self.player.setVideoOutput(self.video_widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.video_widget, 1)

        self._controls = QWidget(self)
        ctrl = QHBoxLayout(self._controls)
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(6)

        self.btn_play = icon_button("play", "播放 / 暂停")
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_stop = icon_button("stop", "停止并回到头")
        self.btn_stop.clicked.connect(self.stop)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False)
        self.slider.setToolTip("拖动跳转")
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setMinimumWidth(110)
        self.lbl_time.setAlignment(Qt.AlignCenter)

        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_stop)
        ctrl.addWidget(self.slider, 1)
        ctrl.addWidget(self.lbl_time)
        layout.addWidget(self._controls)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_error)

        self.autoplay = autoplay
        if not show_controls:
            self._controls.hide()

    # ── 对外 API ──
    def set_source(self, path_or_url):
        """设置视频源（本地路径或网络 URL），支持自动播放。"""
        self.stop()
        if isinstance(path_or_url, str) and "://" in path_or_url:
            url = QUrl(path_or_url)
        else:
            url = QUrl.fromLocalFile(os.path.abspath(path_or_url))
        # 先清空再设置，避免 QMediaPlayer 切换源时卡死
        self.player.setSource(QUrl())
        self.player.setSource(url)
        if self.autoplay:
            self.play()

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        _set_button_icon(self.btn_play, "play")
        self.lbl_time.setText("00:00 / 00:00")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def set_volume(self, percent):
        """0-100。"""
        try:
            self._audio.setVolume(max(0.0, min(100.0, float(percent))) / 100.0)
        except (TypeError, ValueError):
            pass

    def clear_source(self):
        self.stop()
        self.player.setSource(QUrl())

    def has_source(self):
        return self.player.source().isValid()

    # ── 内部槽 ──
    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        _set_button_icon(self.btn_play, "pause" if playing else "play")

    def _on_position(self, pos):
        if self._dragging:
            return
        dur = self.player.duration()
        if dur > 0:
            self.slider.setValue(int(pos * 1000 / dur))
        self.lbl_time.setText(f"{format_ms(pos)} / {format_ms(dur)}")

    def _on_duration(self, dur):
        self.slider.setEnabled(dur > 0)

    def _on_slider_pressed(self):
        self._dragging = True

    def _on_slider_released(self):
        self._dragging = False
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(self.slider.value() * dur / 1000))

    def _on_media_status(self, status):
        try:
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                # 播放完毕后回到头并停止，等待下次播放
                self.player.stop()
                self.slider.setValue(0)
                _set_button_icon(self.btn_play, "play")
                self.lbl_time.setText(f"00:00 / {format_ms(self.player.duration())}")
            elif status == QMediaPlayer.MediaStatus.InvalidMedia:
                self.lbl_time.setText("无法播放该视频")
        except Exception:
            pass

    def _on_error(self, _err, err_str):
        self.lbl_time.setText(f"播放失败: {err_str or '播放失败'}")


class VideoPreviewDialog(QDialog):
    """独立视频预览窗口：统一播放器 + 关闭按钮。"""

    def __init__(self, path=None, parent=None, title="视频预览", size=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        if size:
            self.resize(*size)
        else:
            self.resize(560, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.player_widget = VideoPlayerWidget(self, autoplay=True)
        lay.addWidget(self.player_widget, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.finished.connect(lambda *_: self.player_widget.stop())
        if path:
            self.player_widget.set_source(path)

    def set_source(self, path_or_url):
        self.player_widget.set_source(path_or_url)

    def closeEvent(self, event):
        self.player_widget.stop()
        super().closeEvent(event)
