import contextlib
import os
import shutil
import tempfile
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from utils.ffmpeg_utils import (
    extract_frame as ffmpeg_extract_frame,
)
from utils.gui_icons import icon_button, mdi_button
from utils.logger_utils import log

from .utils import _set_button_icon, generate_cover_image


class CoverEditDialog(QDialog):
    def __init__(self, video_path, title, frame_path, cover_path, cover_vertical_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑视频封面")
        self.resize(1100, 650)
        self.setModal(True)
        self.setObjectName("cover_edit_dialog")

        self.video_path = video_path
        self.original_title = title
        self.original_frame_path = frame_path
        self.original_cover_path = cover_path
        self.original_cover_vertical_path = cover_vertical_path or cover_path.replace("cover_", "cover_vertical_")

        self.temp_dir = tempfile.mkdtemp()
        self.temp_frame_path = os.path.join(self.temp_dir, "temp_frame.jpg")
        self.temp_cover_path = os.path.join(self.temp_dir, "temp_cover.jpg")
        self.temp_cover_vertical_path = os.path.join(self.temp_dir, "temp_cover_vertical.jpg")

        if os.path.exists(frame_path):
            shutil.copy(frame_path, self.temp_frame_path)
        if os.path.exists(cover_path):
            shutil.copy(cover_path, self.temp_cover_path)
        if os.path.exists(self.original_cover_vertical_path):
            shutil.copy(self.original_cover_vertical_path, self.temp_cover_vertical_path)

        self.current_title = title
        self.saved = False

        self.last_seek_time = 0.0
        self.pending_seek_pos = None
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.timeout.connect(self._do_throttled_seek)

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(20)

        col1_widget = QWidget()
        col1_layout = QVBoxLayout(col1_widget)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        col1_layout.setSpacing(10)

        player_title = QLabel("<b> 视频截取区域 (拖动滑块定帧)</b>")
        player_title.setObjectName("cover_section_title")
        col1_layout.addWidget(player_title)

        self.video_widget = QVideoWidget()
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.video_widget.setObjectName("cover_video_widget")
        col1_layout.addWidget(self.video_widget, 1)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px
                background: #27272a;
                border-radius: 4px
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 4px
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 3px solid #3b82f6;
                width: 22px
                height: 22px
                margin-top: -7px
                margin-bottom: -7px
                border-radius: 11px
            }
            QSlider::handle:horizontal:hover {
                background: #3b82f6;
                border: 3px solid #ffffff;
            }
        """)
        col1_layout.addWidget(self.slider)

        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(10)

        self.btn_play = icon_button("play", "播放 / 暂停")
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.btn_play)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(100)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setObjectName("cover_time_label")
        ctrl_layout.addWidget(self.lbl_time)

        ctrl_layout.addStretch()

        self.btn_capture = mdi_button("选择当前帧为封面", "camera")
        self.btn_capture.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none
                border-radius: 4px
                padding: 6px 16px
                font-weight: bold
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_capture.clicked.connect(self.capture_current_frame)
        ctrl_layout.addWidget(self.btn_capture)

        col1_layout.addLayout(ctrl_layout)
        main_layout.addWidget(col1_widget, 1)

        col2_widget = QWidget()
        col2_layout = QVBoxLayout(col2_widget)
        col2_layout.setContentsMargins(0, 0, 0, 0)
        col2_layout.setSpacing(12)
        col2_layout.setAlignment(Qt.AlignTop)

        h_cover_title = QLabel("<b> 横屏封面预览 (16:9)</b>")
        h_cover_title.setObjectName("cover_section_title")
        col2_layout.addWidget(h_cover_title)

        self.lbl_cover_preview_h = QLabel()
        self.lbl_cover_preview_h.setFixedSize(320, 180)
        self.lbl_cover_preview_h.setObjectName("cover_preview_h")
        self.lbl_cover_preview_h.setAlignment(Qt.AlignCenter)
        col2_layout.addWidget(self.lbl_cover_preview_h, 0, Qt.AlignCenter)

        if os.path.exists(self.temp_cover_path):
            pix_h = QPixmap(self.temp_cover_path)
            self.lbl_cover_preview_h.setPixmap(pix_h.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_cover_preview_h.setText("暂无横屏封面，请在左侧截图")

        col2_layout.addSpacing(10)
        col2_layout.addWidget(QLabel("封面标题 (不超过10个字):"))
        self.title_input = QLineEdit(self.current_title)
        self.title_input.setMaxLength(10)
        self.title_input.setPlaceholderText("请输入标题文案...")
        self.title_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 4px
                padding: 6px
                color: #f8fafc;
                font-size: 13px
            }
        """)
        self.title_input.textChanged.connect(self.on_title_changed)
        col2_layout.addWidget(self.title_input)

        main_layout.addWidget(col2_widget, 1)

        col3_widget = QWidget()
        col3_layout = QVBoxLayout(col3_widget)
        col3_layout.setContentsMargins(0, 0, 0, 0)
        col3_layout.setSpacing(12)
        col3_layout.setAlignment(Qt.AlignTop)

        v_cover_title = QLabel("<b> 竖屏封面预览 (9:16)</b>")
        v_cover_title.setObjectName("cover_section_title")
        col3_layout.addWidget(v_cover_title)

        self.lbl_cover_preview_v = QLabel()
        self.lbl_cover_preview_v.setFixedSize(180, 320)
        self.lbl_cover_preview_v.setObjectName("cover_preview_v")
        self.lbl_cover_preview_v.setAlignment(Qt.AlignCenter)
        col3_layout.addWidget(self.lbl_cover_preview_v, 0, Qt.AlignCenter)

        if os.path.exists(self.temp_cover_vertical_path):
            pix_v = QPixmap(self.temp_cover_vertical_path)
            self.lbl_cover_preview_v.setPixmap(pix_v.scaled(180, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_cover_preview_v.setText("暂无竖屏封面，请在左侧截图")

        col3_layout.addSpacing(10)

        actions_layout = QHBoxLayout()
        self.btn_save = QPushButton("确定保存")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none
                border-radius: 4px
                padding: 8px 20px
                font-weight: bold
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_save.clicked.connect(self.save_and_close)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 4px
                padding: 8px 20px
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)

        actions_layout.addWidget(self.btn_save)
        actions_layout.addWidget(self.btn_cancel)
        col3_layout.addLayout(actions_layout)

        main_layout.addWidget(col3_widget, 1)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderMoved.connect(self.set_position)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)

        self.player.setSource(QUrl.fromLocalFile(self.video_path))
        self.player.play()

    def on_slider_pressed(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")
        else:
            self.player.play()
            _set_button_icon(self.btn_play, "pause")

    def set_position(self, position):
        self.pending_seek_pos = position
        now = time.time()
        if now - self.last_seek_time > 0.05:
            self._do_throttled_seek()
        else:
            if not self.seek_timer.isActive():
                self.seek_timer.start(30)

    def _do_throttled_seek(self):
        if self.pending_seek_pos is not None:
            self.player.setPosition(self.pending_seek_pos)
            self.last_seek_time = time.time()
            self.pending_seek_pos = None

    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)

    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000
        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60
        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60
        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")

    def capture_current_frame(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")

        time_sec = self.player.position() / 1000.0
        self.btn_capture.setEnabled(False)
        self.btn_capture.setText("正在截取中...")
        self.btn_capture.repaint()

        try:
            if not ffmpeg_extract_frame(self.video_path, time_sec, self.temp_frame_path, quality=2):
                raise RuntimeError(f"提取帧失败: {self.video_path}")
            self.regenerate_cover()
        except Exception as e:
            QMessageBox.warning(self, "截图失败", f"无法捕获当前帧:\n{str(e)}")
        finally:
            self.btn_capture.setEnabled(True)
            self.btn_capture.setText("选择当前帧为封面")

    def on_title_changed(self, text):
        self.current_title = text.strip()
        self.regenerate_cover()

    def regenerate_cover(self):
        if not os.path.exists(self.temp_frame_path):
            return
        try:
            generate_cover_image(self.temp_frame_path, self.current_title, self.temp_cover_path, size=(1280, 720))
            generate_cover_image(self.temp_frame_path, self.current_title, self.temp_cover_vertical_path, size=(720, 1280))

            pix_h = QPixmap(self.temp_cover_path)
            self.lbl_cover_preview_h.setPixmap(pix_h.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))

            pix_v = QPixmap(self.temp_cover_vertical_path)
            self.lbl_cover_preview_v.setPixmap(pix_v.scaled(180, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            log.exception("生成临时封面失败")

    def save_and_close(self):
        try:
            if not os.path.exists(self.temp_frame_path):
                QMessageBox.warning(self, "提示", "请先截取一帧画面作为封面背景")
                return
            shutil.copy(self.temp_frame_path, self.original_frame_path)
            shutil.copy(self.temp_cover_path, self.original_cover_path)
            shutil.copy(self.temp_cover_vertical_path, self.original_cover_vertical_path)
            self.saved = True
            self.accept()
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"无法保存封面修改:\n{str(e)}")

    def closeEvent(self, event):
        self.player.stop()
        with contextlib.suppress(OSError):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().closeEvent(event)