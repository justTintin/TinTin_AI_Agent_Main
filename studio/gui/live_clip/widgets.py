import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from utils.gui_icons import icon_button, mdi_button

from .dialogs import CoverEditDialog
from .utils import _set_button_icon
from .workers import CoverGeneratorWorker, VideoClipWorker


class AudioPlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_play = icon_button("play", "播放 / 暂停")
        self.btn_play.clicked.connect(self.toggle_play)
        layout.addWidget(self.btn_play)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(100)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_time)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px
                background: #2e2e32;
                border-radius: 3px
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 3px
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px
                margin-top: -4px
                margin-bottom: -4px
                border-radius: 7px
            }
        """)
        layout.addWidget(self.slider)

        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)

        self.audio_path = None
        self.setEnabled(False)

    def set_audio_path(self, audio_path):
        if not audio_path or not os.path.exists(audio_path):
            self.setEnabled(False)
            return
        self.audio_path = audio_path
        self.player.setSource(QUrl.fromLocalFile(audio_path))
        self.setEnabled(True)
        _set_button_icon(self.btn_play, "play")
        self.lbl_time.setText("00:00 / 00:00")
        self.slider.setValue(0)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")
        else:
            self.player.play()
            _set_button_icon(self.btn_play, "pause")

    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)

    def set_position(self, position):
        self.player.setPosition(position)

    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000

        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60

        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60

        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")


class ClipListItemWidget(QFrame):
    def __init__(self, clip_info, index, main_page, parent=None):
        super().__init__(parent)
        self.clip_info = clip_info
        self.clip_index = index
        self.main_page = main_page
        self.selected = False

        self.setObjectName("clip_list_item")
        self.setFrameShape(QFrame.StyledPanel)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_layout = QHBoxLayout()
        self.lbl_title = QLabel(f"<b>{self.clip_info.get('title', '精彩片段')}</b>")
        self.lbl_title.setObjectName("clip_list_item_title")
        self.lbl_title.setWordWrap(True)
        top_layout.addWidget(self.lbl_title, 1)

        score = self.clip_info.get('score', 0.0)
        self.lbl_score = QLabel(f"评分 {score}")
        self.lbl_score.setObjectName("clip_list_item_score")
        top_layout.addWidget(self.lbl_score)
        layout.addLayout(top_layout)

        meta_layout = QHBoxLayout()
        meta_text = f"{self.clip_info.get('start_str', '00:00')} - {self.clip_info.get('end_str', '00:00')} ({self.clip_info.get('duration', 0)}s)"
        self.lbl_meta = QLabel(meta_text)
        self.lbl_meta.setObjectName("clip_list_item_meta")
        meta_layout.addWidget(self.lbl_meta, 1)

        self.chk_subtitles = QCheckBox("加字幕")
        self.chk_subtitles.setStyleSheet("""
            QCheckBox {
                color: #94a3b8;
                font-size: 11px
            }
        """)
        self.chk_subtitles.setChecked(False)
        meta_layout.addWidget(self.chk_subtitles)
        layout.addLayout(meta_layout)

        self.slice_layout = QHBoxLayout()
        self.slice_layout.setSpacing(8)

        self.pbar_slice = QProgressBar()
        self.pbar_slice.setRange(0, 100)
        self.pbar_slice.setValue(0)
        self.pbar_slice.setFixedHeight(10)
        self.pbar_slice.setVisible(False)
        self.pbar_slice.setStyleSheet("""
            QProgressBar {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 4px
                text-align: center
                color: #ffffff;
                font-size: 9px
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 3px
            }
        """)
        self.slice_layout.addWidget(self.pbar_slice, 1)

        self.btn_slice_single = mdi_button("单独切片", "cut")
        self.btn_slice_single.setStyleSheet("""
            QPushButton {
                background-color: #d97706;
                color: #ffffff;
                border: none
                border-radius: 4px
                padding: 4px 10px
                font-size: 11px
                font-weight: bold
            }
            QPushButton:hover {
                background-color: #b45309;
            }
            QPushButton:disabled {
                background-color: #27272a;
                color: #71717a;
                border: 1px solid #27272a;
            }
        """)
        self.btn_slice_single.setFixedWidth(80)
        self.btn_slice_single.clicked.connect(self.start_individual_slice)
        self.slice_layout.addWidget(self.btn_slice_single)

        layout.addLayout(self.slice_layout)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setObjectName("clip_list_separator")
        layout.addWidget(sep)

        play_layout = QHBoxLayout()
        play_layout.setSpacing(6)

        self.btn_play = icon_button("play", "播放声音")
        self.btn_play.setEnabled(False)
        play_layout.addWidget(self.btn_play)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setObjectName("clip_list_item_time")
        self.lbl_time.setFixedWidth(80)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        play_layout.addWidget(self.lbl_time)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px
                background: #2e2e32;
                border-radius: 2px
            }
            QSlider::sub-page:horizontal {
                background: #10b981;
                border-radius: 2px
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 10px
                height: 10px
                margin-top: -3px
                margin-bottom: -3px
                border-radius: 5px
            }
        """)
        play_layout.addWidget(self.slider)

        self.btn_edit_cover = mdi_button("编辑封面", "palette")
        self.btn_edit_cover.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none
                border-radius: 4px
                padding: 4px 8px
                font-size: 11px
                font-weight: bold
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:disabled {
                background-color: #27272a;
                color: #52525b;
                border: 1px solid #27272a;
            }
        """)
        self.btn_edit_cover.setFixedWidth(80)
        self.btn_edit_cover.setEnabled(False)
        play_layout.addWidget(self.btn_edit_cover)

        layout.addLayout(play_layout)

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_edit_cover.clicked.connect(self.open_cover_editor)
        self.slider.sliderMoved.connect(self.set_position)

        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)

        self.update_style()

    def mousePressEvent(self, event):
        self.main_page.select_clip_item(self.clip_index)
        super().mousePressEvent(event)

    def update_style(self):
        if self.selected:
            self.setStyleSheet("""
                QFrame#clip_list_item {
                    background-color: #1e293b;
                    border: 2px solid #3b82f6;
                    border-radius: 8px
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#clip_list_item {
                    background-color: #18181b;
                    border: 1px solid #2e2e32;
                    border-radius: 8px
                }
                QFrame#clip_list_item:hover {
                    border: 1px solid #4b5563;
                }
            """)

    def set_selected(self, selected):
        self.selected = selected
        self.update_style()

    def enable_playback(self, video_path):
        self.clip_info["video_path"] = video_path
        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.btn_play.setEnabled(True)
        self.btn_edit_cover.setEnabled(True)
        self.slider.setEnabled(True)

        self.btn_slice_single.setText("已切片")
        self.btn_slice_single.setEnabled(False)
        self.pbar_slice.setVisible(False)

    def toggle_play(self):
        if not self.clip_info.get("video_path") or not os.path.exists(self.clip_info["video_path"]):
            return

        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")
        else:
            self.main_page.pause_all_players_except(self.clip_index)
            self.player.play()
            _set_button_icon(self.btn_play, "pause")

    def pause_audio(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            _set_button_icon(self.btn_play, "play")

    def open_cover_editor(self):
        video_path = self.clip_info.get("video_path")
        if not video_path or not os.path.exists(video_path):
            return

        self.pause_audio()
        self.main_page.pause_all_players_except(-1)

        cover_path = self.clip_info.get("cover_path", "")
        cover_vertical_path = self.clip_info.get("cover_vertical_path", "")
        if not cover_vertical_path and cover_path:
            cover_vertical_path = cover_path.replace("cover_", "cover_vertical_")

        dialog = CoverEditDialog(
            video_path=video_path,
            title=self.clip_info.get("title", ""),
            frame_path=self.clip_info.get("frame_path", ""),
            cover_path=cover_path,
            cover_vertical_path=cover_vertical_path,
            parent=self.main_page.parent_widget
        )
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.clip_info["title"] = dialog.current_title
            self.clip_info["cover_path"] = dialog.original_cover_path
            self.clip_info["cover_vertical_path"] = dialog.original_cover_vertical_path
            self.lbl_title.setText(f"<b>{dialog.current_title}</b>")
            self.main_page.on_clip_info_updated(
                self.clip_index,
                dialog.current_title,
                dialog.original_cover_path,
                dialog.original_cover_vertical_path
            )

    def start_individual_slice(self):
        if not self.main_page.video_path or not os.path.exists(self.main_page.video_path):
            QMessageBox.warning(self.main_page.parent_widget, "错误", f"视频文件不存在，请重新选择视频文件。\n路径: {self.main_page.video_path or '未选择'}")
            return

        self.btn_slice_single.setEnabled(False)
        self.btn_slice_single.setText("正在切片...")
        self.pbar_slice.setValue(0)
        self.pbar_slice.setVisible(True)

        if not self.main_page.output_dir:
            from config.paths import OUTPUTS_DIR
            import os as _os
            vname = _os.path.splitext(_os.path.basename(self.main_page.video_path))[0]
            self.main_page.output_dir = _os.path.join(OUTPUTS_DIR, "live_clips", vname)
            _os.makedirs(self.main_page.output_dir, exist_ok=True)

        clip_data = dict(self.clip_info)
        clip_data["burn_subtitles"] = self.chk_subtitles.isChecked()
        clip_data["index"] = self.clip_index
        self.worker_clip = VideoClipWorker(
            self.main_page.video_path, [clip_data], self.main_page.output_dir,
            srt_path=getattr(self.main_page, "srt_path", "")
        )
        self.worker_clip.progress.connect(self.pbar_slice.setValue)
        self.worker_clip.finished.connect(self.on_individual_clip_done)
        self.worker_clip.error.connect(self.on_individual_slice_error)
        self.worker_clip.start()

    def on_individual_slice_error(self, err):
        self.btn_slice_single.setEnabled(True)
        self.btn_slice_single.setText("单独切片")
        self.pbar_slice.setVisible(False)
        from gui.error_dialog import show_error_dialog
        show_error_dialog(self.main_page.parent_widget, "单独切片失败", f"单独切片失败:\n{err}")

    def on_individual_clip_done(self, results):
        if not results:
            self.on_individual_slice_error("没有生成切片视频")
            return

        video_path = results[0]["path"]
        self.clip_info["video_path"] = video_path
        self.btn_slice_single.setText("生成封面...")

        ci = {
            "path": video_path,
            "title": self.clip_info.get("title", ""),
            "index": self.clip_index,
            "start": self.clip_info.get("start", 0),
            "end": self.clip_info.get("end", 0),
            "start_str": self.clip_info.get("start_str", ""),
            "end_str": self.clip_info.get("end_str", ""),
            "duration": self.clip_info.get("duration", 0),
            "score": self.clip_info.get("score", 0),
        }

        self.worker_cover = CoverGeneratorWorker([ci], self.main_page.output_dir)
        self.worker_cover.finished.connect(self.on_individual_cover_done)
        self.worker_cover.error.connect(self.on_individual_slice_error)
        self.worker_cover.start()

    def on_individual_cover_done(self, covers_info):
        if not covers_info:
            self.on_individual_slice_error("没有生成封面")
            return

        ci = covers_info[0]
        self.clip_info["cover_path"] = ci["cover_path"]
        self.clip_info["cover_vertical_path"] = ci.get("cover_vertical_path", "")
        self.clip_info["frame_path"] = ci["frame_path"]
        self.clip_info["video_path"] = ci["video_path"]
        self.clip_info["title"] = ci["title"]

        self.enable_playback(ci["video_path"])
        self.main_page.update_covers_info_for_index(self.clip_index, ci)

        self.btn_slice_single.setText("已切片")

    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)

    def set_position(self, position):
        self.player.setPosition(position)

    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000
        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60
        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60
        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")