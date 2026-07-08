# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import traceback
import sys
import random
import base64
import requests
import time

# Prevent black command prompt windows from popping up on Windows when running CLI tasks
if sys.platform == 'win32':
    class _patched_Popen(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            if 'creationflags' not in kwargs:
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            else:
                kwargs['creationflags'] |= subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)
    subprocess.Popen = _patched_Popen

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QListWidget, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QSlider, QDoubleSpinBox, QWidget, QStackedWidget,
                               QSpinBox, QListWidgetItem, QGroupBox, QDialog, QDialogButtonBox, QPlainTextEdit, QScrollArea,
                               QListView, QMenu)
from PySide6.QtCore import Signal, QThread, Qt, QMimeData
from PySide6.QtGui import QDrag, QAction
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from config.paths import WORKSPACE_ROOT, VOXCPM2_DIR, PROJECT_ROOT

def get_voxcpm_python():
    """返回可用于启动 VoxCPM API 服务器的 Python 路径。

    使用 voxcpm2 venv 自带的 Python（3.12），以保证 numpy/torch 等
    编译扩展与解释器版本匹配；嵌入式 Python（3.11）无法加载 cp312 的 C 扩展。
    """
    from utils.platform_utils import find_venv_python
    return find_venv_python(VOXCPM2_DIR)


def find_ffmpeg():
    from utils.platform_utils import find_ffmpeg as _ff
    return _ff()


def get_media_duration(filepath):
    try:
        from utils.platform_utils import find_ffprobe, create_no_window_flag
        creationflags = create_no_window_flag()
        ffprobe_exe = find_ffprobe()
        if not os.path.isfile(ffprobe_exe):
            ffprobe_exe = find_ffmpeg().replace("ffmpeg", "ffprobe")
        if not os.path.isfile(ffprobe_exe):
            return 0.0
        cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", filepath]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0.0


class DoubleClickLineEdit(QLineEdit):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self.doubleClicked.emit()


class ReadOnlyDoubleClickLineEdit(QLineEdit):
    """只读单行输入框，双击弹出完整文本查看对话框。"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self._full_text = text
        self.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                color: #d1d5db;
                padding: 4px 8px;
                font-size: 11px;
            }
            QLineEdit:hover {
                border: 1px solid rgba(255, 255, 255, 0.25);
                background-color: rgba(255, 255, 255, 0.07);
            }
        """)
        self.setToolTip("双击查看完整原文")
        self.setCursorPosition(0)

    def set_full_text(self, text):
        self._full_text = text
        self.setText(text)
        self.setCursorPosition(0)

    def mouseDoubleClickEvent(self, event):
        # Show full text in a read-only popup dialog
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QLabel, QHBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("📝 原文 - 完整内容")
        dlg.setMinimumSize(500, 300)
        dlg.resize(580, 350)
        dlg.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #e5e7eb; }
            QLabel { color: #9ca3af; font-size: 13px; font-weight: bold; }
            QPlainTextEdit {
                background-color: #111827;
                color: #f3f4f6;
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 7px 18px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        v.addWidget(QLabel("📝 原始视频文案（只读）:"))
        te = QPlainTextEdit()
        te.setPlainText(self._full_text)
        te.setReadOnly(True)
        v.addWidget(te)
        h = QHBoxLayout()
        h.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        h.addWidget(btn_close)
        v.addLayout(h)
        dlg.exec()


class TextEditDialog(QDialog):
    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(450, 250)
        self.resize(500, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Theme-consistent dialog: only style widget-specific elements
        self.setStyleSheet("""
            QTextEdit {
                border: 1px solid rgba(128,128,128,0.15);
                border-radius: 4px;
                font-size: 13px;
                padding: 6px;
            }
            QTextEdit:focus {
                border: 1px solid #2ecc71;
            }
        """)

        lbl = QLabel("配音文案编辑:")
        layout.addWidget(lbl)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        layout.addWidget(self.text_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2ecc71;
                    color: white;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #27ae60;
                }
            """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_text(self):
        return self.text_edit.toPlainText().strip()


class VoiceRowDetailWidget(QWidget):
    def __init__(self, basename, filepath, original_text, edit, wav_path=None,
                 status_widget=None, action_widgets=None, video_duration_sec=0.0,
                 voice_duration_sec=0.0, play_original_btn=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        
        # Line 1: video filename + play original + status + action buttons
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        
        lbl_video = QLabel(f"🎥 视频: {basename}")
        lbl_video.setObjectName("card_title")
        lbl_video.setToolTip(filepath)
        top_layout.addWidget(lbl_video)

        if play_original_btn:
            top_layout.addWidget(play_original_btn)

        top_layout.addStretch()

        if status_widget:
            top_layout.addWidget(status_widget, 0)
        if action_widgets:
            for w in action_widgets:
                top_layout.addWidget(w, 0)
        
        layout.addLayout(top_layout)
        
        # Line 2: Original script + video duration
        row_original = QHBoxLayout()
        row_original.setContentsMargins(0, 0, 0, 0)
        lbl_orig_tag = QLabel("📝 原文: ")
        lbl_orig_tag.setObjectName("muted_text")
        lbl_orig_tag.setFixedWidth(48)
        orig_val = ReadOnlyDoubleClickLineEdit(original_text if original_text else "(无)")
        row_original.addWidget(lbl_orig_tag)
        row_original.addWidget(orig_val, 1)
        if video_duration_sec > 0:
            vid_dur_str = f"{int(video_duration_sec // 60)}:{int(video_duration_sec % 60):02d}"
            lbl_vid_dur = QLabel(f"⏱ {vid_dur_str}")
            lbl_vid_dur.setStyleSheet("color: #f1c40f; font-size: 11px; font-weight: bold;")
            lbl_vid_dur.setFixedWidth(60)
            row_original.addWidget(lbl_vid_dur)
        layout.addLayout(row_original)
        
        # Line 3: AI-modified script + voice duration
        row_edit = QHBoxLayout()
        row_edit.setContentsMargins(0, 0, 0, 0)
        lbl_edit_tag = QLabel("✨ 修改后: ")
        lbl_edit_tag.setObjectName("accent_text")
        row_edit.addWidget(lbl_edit_tag)
        row_edit.addWidget(edit, 1)
        voice_dur_str = ""
        if voice_duration_sec > 0:
            voice_dur_str = f"{int(voice_duration_sec // 60)}:{int(voice_duration_sec % 60):02d}"
            voice_dur_style = "color: #2ecc71; font-size: 11px; font-weight: bold;"
        else:
            voice_dur_str = "--:--"
            voice_dur_style = "color: #7f8c8d; font-size: 11px;"
        self.lbl_voice_duration = QLabel(f"⏱ {voice_dur_str}")
        self.lbl_voice_duration.setStyleSheet(voice_dur_style)
        self.lbl_voice_duration.setFixedWidth(60)
        row_edit.addWidget(self.lbl_voice_duration)
        layout.addLayout(row_edit)


class ScriptCompareDialog(QDialog):
    def __init__(self, original_text, current_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚖️ 配音文案对比")
        self.setMinimumSize(700, 400)
        self.resize(800, 480)
        
        # Theme-consistent dialog style
        self.setStyleSheet("""
            QPlainTextEdit {
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 13px;
                line-height: 1.4;
                padding: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        title_lbl = QLabel("📖 左右对比：左侧为原视频文案，右侧为AI修改/当前配音文案")
        title_lbl.setStyleSheet("font-size: 14px; color: #60a5fa; font-weight: bold;")
        layout.addWidget(title_lbl)
        
        # Splitter or side-by-side layout
        h_layout = QHBoxLayout()
        h_layout.setSpacing(12)
        
        # Left: Original
        left_widget = QWidget()
        left_vbox = QVBoxLayout(left_widget)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(6)
        left_vbox.addWidget(QLabel("📝 原始文案 (原视频内容):"))
        self.original_edit = QPlainTextEdit()
        self.original_edit.setPlainText(original_text)
        self.original_edit.setReadOnly(True)
        left_vbox.addWidget(self.original_edit)
        h_layout.addWidget(left_widget)
        
        # Right: Current/Modified
        right_widget = QWidget()
        right_vbox = QVBoxLayout(right_widget)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(6)
        right_vbox.addWidget(QLabel("✨ AI修改后 / 当前文案:"))
        self.current_edit = QPlainTextEdit()
        self.current_edit.setPlainText(current_text)
        right_vbox.addWidget(self.current_edit)
        h_layout.addWidget(right_widget)
        
        layout.addLayout(h_layout)
        
        # Bottom buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_use_original = QPushButton("⏪ 还原为原始文案")
        btn_use_original.setStyleSheet("""
            QPushButton {
                background-color: #4b5563;
            }
            QPushButton:hover {
                background-color: #374151;
            }
        """)
        btn_use_original.clicked.connect(self._use_original)
        btn_box.addWidget(btn_use_original)
        
        btn_save = QPushButton("💾 保存修改")
        btn_save.clicked.connect(self.accept)
        btn_box.addWidget(btn_save)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #d1d5db;
                border: 1px solid #4b5563;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        
        layout.addLayout(btn_box)
        
    def _use_original(self):
        self.current_edit.setPlainText(self.original_edit.toPlainText())
        
    def get_text(self):
        return self.current_edit.toPlainText().strip()



class DubbedVideosDialog(QDialog):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.setWindowTitle("🎉 配音替换完成")
        self.setMinimumSize(600, 400)
        self.resize(650, 450)
        
        # Theme-consistent dialog (no custom QDialog/QPushButton base style)
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid #2e2e32;
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton#primary_button {
                font-weight: 700;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header_lbl = QLabel("✨ <b>所有视频配音替换完毕！已成功为您生成以下配音文件：</b>")
        header_lbl.setStyleSheet("font-size: 14px; color: #2ecc71;")
        layout.addWidget(header_lbl)

        if results:
            first_path = list(results.values())[0]
            out_dir = os.path.dirname(first_path)
            dir_lbl = QLabel(f"📂 <b>保存目录：</b> <font color='#3498db'>{out_dir}</font>")
            dir_lbl.setWordWrap(True)
            dir_lbl.setStyleSheet("font-size: 12px;")
            layout.addWidget(dir_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        for orig_path, dubbed_path in results.items():
            item = QListWidgetItem()
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 4, 8, 4)
            item_layout.setSpacing(10)

            name_lbl = QLabel(os.path.basename(dubbed_path))
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            name_lbl.setToolTip(f"原视频: {orig_path}\n配音视频: {dubbed_path}")
            item_layout.addWidget(name_lbl, 1)

            btn_play = QPushButton("▶️ 播放视频")
            btn_play.clicked.connect(lambda checked=False, path=dubbed_path: self._play_video(path))
            item_layout.addWidget(btn_play)

            btn_locate = QPushButton("📂 打开所在目录")
            btn_locate.clicked.connect(lambda checked=False, path=dubbed_path: self._locate_video(path))
            item_layout.addWidget(btn_locate)

            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        btn_open_all = QPushButton("📂 打开整体输出文件夹")
        if results:
            btn_open_all.clicked.connect(lambda checked=False, path=out_dir: self._open_dir(path))
        footer_layout.addWidget(btn_open_all)

        btn_ok = QPushButton("确认并返回")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        footer_layout.addWidget(btn_ok)

        layout.addLayout(footer_layout)

    def _play_video(self, path):
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _locate_video(self, path):
        dir_p = os.path.dirname(path)
        self._open_dir(dir_p)

    def _open_dir(self, path):
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "打开失败", f"无法打开该目录:\n{e}")



class FinalMixedVideosDialog(QDialog):
    def __init__(self, parent, paths):
        super().__init__(parent)
        self.setWindowTitle("🎉 最终合成视频列表")
        self.setMinimumSize(600, 400)
        self.resize(650, 450)
        
        # Theme-consistent dialog (no custom QDialog/QPushButton base style)
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid #2e2e32;
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton#primary_button {
                font-weight: 700;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header_lbl = QLabel("✨ <b>批量音视频及配乐合成完毕！已成功为您生成以下视频文件：</b>")
        header_lbl.setStyleSheet("font-size: 14px; color: #2ecc71;")
        layout.addWidget(header_lbl)

        if paths:
            out_dir = os.path.dirname(paths[0])
            dir_lbl = QLabel(f"📂 <b>保存目录：</b> <font color='#3498db'>{out_dir}</font>")
            dir_lbl.setWordWrap(True)
            dir_lbl.setStyleSheet("font-size: 12px;")
            layout.addWidget(dir_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        for path in paths:
            item = QListWidgetItem()
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 4, 8, 4)
            item_layout.setSpacing(10)

            name_lbl = QLabel(os.path.basename(path))
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            name_lbl.setToolTip(f"输出视频: {path}")
            item_layout.addWidget(name_lbl, 1)

            btn_play = QPushButton("▶️ 播放视频")
            btn_play.clicked.connect(lambda checked=False, p=path: self._play_video(p))
            item_layout.addWidget(btn_play)

            btn_locate = QPushButton("📂 打开所在目录")
            btn_locate.clicked.connect(lambda checked=False, p=path: self._locate_video(p))
            item_layout.addWidget(btn_locate)

            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        btn_open_all = QPushButton("📂 打开整体输出文件夹")
        if paths:
            btn_open_all.clicked.connect(lambda checked=False, p=out_dir: self._open_dir(p))
        footer_layout.addWidget(btn_open_all)

        btn_ok = QPushButton("确认并返回")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        footer_layout.addWidget(btn_ok)

        layout.addLayout(footer_layout)

    def _play_video(self, path):
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _locate_video(self, path):
        if os.path.exists(path):
            try:
                p = os.path.dirname(path)
                if sys.platform == "win32":
                    subprocess.Popen(f'explorer /select,"{path}"')
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", path])
                else:
                    subprocess.Popen(["xdg-open", p])
            except Exception as e:
                QMessageBox.warning(self, "定位失败", f"无法定位该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _open_dir(self, path):
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "打开失败", f"无法打开该目录:\n{e}")


class PySceneDetectWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    busy = Signal(bool)
    finished = Signal(str, int, list)  # Output directory, number of scenes, list of (start_sec, end_sec)

    def __init__(self, video_path, output_dir, threshold, min_scene_len):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.threshold = threshold
        self.min_scene_len = min_scene_len

    def run(self):
        try:
            self.stage.emit("正在检查 PySceneDetect 环境")
            self.progress.emit(10)
            self.busy.emit(True)

            try:
                from scenedetect import open_video, SceneManager, split_video_ffmpeg
                from scenedetect.detectors import ContentDetector
            except ImportError:
                raise RuntimeError("未检测到 scenedetect 依赖。")

            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            # Setup ffmpeg environment for scenedetect
            if os.path.isfile(ffmpeg_path):
                ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_path))
                if ffmpeg_dir not in os.environ["PATH"]:
                    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
                try:
                    import scenedetect.output.video
                    scenedetect.output.video._FFMPEG_PATH = ffmpeg_path
                except Exception as e:
                    log.warning(f"无法为 scenedetect 设置 _FFMPEG_PATH: {e}")

            self.stage.emit("正在分析镜头切点...")
            self.progress.emit(30)

            # 打开视频并进行场景检测
            video = open_video(self.video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=self.threshold, min_scene_len=self.min_scene_len))
            scene_manager.detect_scenes(video, show_progress=False)
            scene_list = scene_manager.get_scene_list()

            if not scene_list:
                self.stage.emit("未检测到明显的镜头切点")
                self.progress.emit(100)
                self.finished.emit(self.output_dir, 0, [])
                return

            self.stage.emit(f"检测到 {len(scene_list)} 个镜头，正在分割输出...")
            self.progress.emit(60)

            os.makedirs(self.output_dir, exist_ok=True)
            video_basename = os.path.splitext(os.path.basename(self.video_path))[0]
            output_template = f"{video_basename}_shot_%d.mp4"

            # 调用 PySceneDetect 进行分段视频导出
            split_video_ffmpeg(
                self.video_path,
                scene_list,
                output_dir=self.output_dir,
                output_file_template=output_template,
                show_progress=False
            )

            # 验证输出文件是否生成，防止 ffmpeg 调用失败无输出却显示成功
            created_files = []
            if os.path.exists(self.output_dir):
                created_files = [f for f in os.listdir(self.output_dir) if f.lower().endswith(".mp4")]
            
            if not created_files:
                raise RuntimeError(
                    "未能生成分割后的镜头视频文件。请检查 ffmpeg 是否工作正常。\n"
                    "也可以尝试将 ffmpeg.exe 复制到软件根目录下。"
                )

            scenes_sec = [(s[0].get_seconds(), s[1].get_seconds()) for s in scene_list]
            self.stage.emit("分割导出完成")
            self.progress.emit(100)
            self.finished.emit(self.output_dir, len(scene_list), scenes_sec)

        except Exception:
            self.busy.emit(False)
            log.exception("镜头分割失败")
            self.error.emit(traceback.format_exc())


class BestClipWorker(BaseWorker):
    """从整段视频里挑出"比较好的 N 秒"（清晰+适度运动），裁剪成单个片段。

    评分：对画面按约 3fps 抽样，计算锐度(Laplacian 方差)与相邻帧运动量，
    归一化后 score = 0.6*锐度 + 0.4*运动，过暗/过曝帧扣分；
    滑动 N 秒窗口取平均分最高的一段。
    """
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(str, float, float)  # 输出片段路径, 起始秒, 结束秒

    def __init__(self, video_path, output_dir, duration_sec, shot_index=1, clear_dir=False):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.duration_sec = float(duration_sec)
        self.shot_index = int(shot_index)
        self.clear_dir = clear_dir

    def run(self):
        try:
            self.stage.emit("正在分析画面，挑选精华片段...")
            self.progress.emit(10)
            start, end = self._find_best_window()
            self.progress.emit(60)
            out_path = self._cut(start, end)
            self.progress.emit(100)
            self.finished.emit(out_path, start, end)
        except Exception:
            self.error.emit(traceback.format_exc())

    def _find_best_window(self):
        import cv2
        import numpy as np
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError("无法打开视频文件")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if fps <= 0 or fps > 1000:
            fps = 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_dur = total / fps if total > 0 else 0.0

        # 视频比目标时长还短：直接用整段
        if total <= 0 or video_dur <= self.duration_sec:
            cap.release()
            return 0.0, (video_dur if video_dur > 0 else self.duration_sec)

        sample_fps = 3.0
        step = max(1, int(round(fps / sample_fps)))
        times, sharp_l, motion_l, bright_l = [], [], [], []
        prev_gray = None
        i = 0
        while True:
            if not cap.grab():
                break
            if i % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if w > 320:
                    nh = max(1, int(h * 320 / w))
                    frame = cv2.resize(frame, (320, nh))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                bright = float(gray.mean())
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    motion = float(np.mean(cv2.absdiff(gray, prev_gray)))
                else:
                    motion = 0.0
                prev_gray = gray
                times.append(i / fps)
                sharp_l.append(sharp)
                motion_l.append(motion)
                bright_l.append(bright)
            i += 1
        cap.release()

        if not times:
            return 0.0, self.duration_sec

        sharp_a = np.array(sharp_l)
        motion_a = np.array(motion_l)
        bright_a = np.array(bright_l)
        times_a = np.array(times)

        def _norm(a):
            mn, mx = float(a.min()), float(a.max())
            return (a - mn) / (mx - mn) if mx > mn else np.zeros_like(a)

        score = 0.6 * _norm(sharp_a) + 0.4 * _norm(motion_a)
        # 过暗/过曝惩罚
        score = score - np.where((bright_a < 40) | (bright_a > 225), 0.5, 0.0)

        last_start = max(0.0, video_dur - self.duration_sec)
        win_step = 0.5
        best_s, best_score = 0.0, -1e9
        s = 0.0
        while s <= last_start + 1e-6:
            mask = (times_a >= s) & (times_a < s + self.duration_sec)
            if mask.any():
                wscore = float(score[mask].mean())
                if wscore > best_score:
                    best_score = wscore
                    best_s = s
            s += win_step
        return best_s, best_s + self.duration_sec

    def _cut(self, start, end):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或加入 PATH。")
        os.makedirs(self.output_dir, exist_ok=True)

        # 精华模式每个视频只产出一段，先清掉该目录里旧的分镜片段，避免混剪混入多余素材
        if self.clear_dir:
            try:
                for f in os.listdir(self.output_dir):
                    if "_shot_" in f and f.lower().endswith((".mp4", ".m4v")):
                        try:
                            os.remove(os.path.join(self.output_dir, f))
                        except Exception:
                            pass
            except Exception:
                pass

        basename = os.path.splitext(os.path.basename(self.video_path))[0]
        s_str = format_seconds_to_srt_timestamp(start).replace(":", "-")
        e_str = format_seconds_to_srt_timestamp(end).replace(":", "-")
        out_name = f"{basename}_shot_{self.shot_index:03d}_{s_str}_{e_str}.mp4"
        out_path = os.path.abspath(os.path.join(self.output_dir, out_name))
        dur = max(0.1, end - start)

        creationflags = 0x08000000 if sys.platform == "win32" else 0
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", self.video_path,
               "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", creationflags=creationflags)
        if r.returncode != 0 or not os.path.exists(out_path):
            tail = (r.stderr or "")[-400:]
            raise RuntimeError(f"ffmpeg 裁剪失败:\n{tail}")
        return out_path


class PunctuationSRTLLMWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, api_url, api_key, model, srt_content):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.srt_content = srt_content

    def run(self):
        try:
            import requests
            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "你是一个字幕标点符号恢复专家。给定的内容是一个SRT字幕文件，其中包含时间轴和字幕文本。你的任务是给字幕文本添加合适的中文标点符号（，。！？：等），"
                "使阅读更清晰自然。请注意：\n"
                "1. 绝对不要修改时间轴（如 00:00:01,000 --> 00:00:04,500）或行号，必须原样保留。\n"
                "2. 绝对不要修改、增加或删除原字幕文本的任何汉字或英文单词，只能在文本中合理地插入标点符号。\n"
                "3. 直接输出加完标点符号后的完整SRT文件内容，不要用 markdown 包裹，不要有任何解释或废话。"
            )
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self.srt_content}
                ],
                "temperature": 0.2
            }
            log.info(f"PunctuationSRTLLMWorker - 开始恢复字幕标点。模型: {self.model}, 字符数: {len(self.srt_content)}")
            res = requests.post(url, json=payload, headers=headers, timeout=45)
            log.info(f"PunctuationSRTLLMWorker - API 响应状态码: {res.status_code}")
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}, Response: {res.text}")
            
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Empty response from LLM")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            log.info("PunctuationSRTLLMWorker - 字幕标点优化成功。")
            self.finished.emit(content)
        except Exception as e:
            log.exception("PunctuationSRTLLMWorker 运行异常")
            self.error.emit(str(e))

def parse_srt(srt_text):
    import re
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:[^\n]+\n*)+)"
    matches = re.findall(pattern, srt_text)
    segments = []
    
    def srt_time_to_seconds(t_str):
        parts = t_str.replace(",", ".").split(":")
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

    for m in matches:
        try:
            start_sec = srt_time_to_seconds(m[1])
            end_sec = srt_time_to_seconds(m[2])
            text = m[3].strip()
            segments.append((start_sec, end_sec, text))
        except Exception:
            pass
    return segments

def extract_keyframes(video_path, num_frames=3):
    import cv2
    import base64
    import os
    
    if not video_path or not os.path.exists(video_path):
        return []
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []
        
    keyframes_b64 = []
    # Extract frames at 20%, 50%, 80% marks
    ratios = [0.2, 0.5, 0.8]
    for r in ratios:
        frame_idx = int(total_frames * r)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            # Resize frame to save bandwidth/tokens (max size 384px)
            h, w = frame.shape[:2]
            max_size = 384
            if h > max_size or w > max_size:
                if h > w:
                    new_h, new_w = max_size, int(w * max_size / h)
                else:
                    new_h, new_w = int(h * max_size / w), max_size
                frame = cv2.resize(frame, (new_w, new_h))
            
            # Encode as JPG
            ret_jpg, buffer = cv2.imencode('.jpg', frame)
            if ret_jpg:
                b64_str = base64.b64encode(buffer).decode('utf-8')
                keyframes_b64.append(b64_str)
    cap.release()
    return keyframes_b64

class BatchGenerateDescriptionsWorker(BaseWorker):
    finished = Signal(str)  # JSON string: {"1": "desc1", "2": "desc2", ...}

    def __init__(self, api_url, api_key, model, srt_text, scenes, split_video_paths):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.srt_text = srt_text
        self.scenes = scenes # list of (start_sec, end_sec)
        self.split_video_paths = split_video_paths

    def run(self):
        try:
            import requests
            import json
            import re
            
            log.info(f"BatchGenerateDescriptionsWorker - 启动整体镜头描述分析。模型: {self.model}, 视频分段数: {len(self.scenes)}")
            
            desc_dict = {}
            is_vision = any(kw in self.model.lower() for kw in ["vision", "gpt-4o", "gpt-4-turbo", "claude-3", "gemini", "vl", "qwen-vl"])
            
            # 1. Prepare scenes info
            scenes_info = []
            for idx, (scene_start, scene_end) in enumerate(self.scenes, 1):
                scenes_info.append(f"镜头 {idx} 时间段: {scene_start:.2f}秒 --> {scene_end:.2f}秒")
            scenes_text = "\n".join(scenes_info)
            
            # 2. Build system and user prompt
            if self.srt_text.strip():
                # We have subtitles, perform global text alignment and optimization
                system_prompt = (
                    "你是一个优秀的视频剪辑文案配合分析与生成专家。\n"
                    "给你一段视频的原始字幕文案作为背景，以及该视频被分割出的所有镜头的时间段列表。\n"
                    "请将这段字幕文案合理、自然地拆分、分配并润色到各个对应的时间段镜头中，让每个镜头都有一句通顺、且有营销卖点的画面描述文案。\n"
                    "请注意：\n"
                    "1. 必须为【每个】镜头生成一句画面描述（控制在10-25字之间）。\n"
                    "2. 如果某些时间段视频里没有说话声音（比如是背景镜头），请根据整体视频卖点设计一句合适的画面描述（如：产品细节特写、模特手持特写、大字提示卖点等）。\n"
                    "3. 保持镜头描述在语意上的连贯性和整体性。\n"
                    "请严格以 JSON 格式输出，不得包含 markdown 标记或任何解释文字，格式如下：\n"
                    "[\n"
                    "  {\"index\": 1, \"description\": \"第一镜头的描述文案\"},\n"
                    "  {\"index\": 2, \"description\": \"第二镜头的描述文案\"}\n"
                    "]"
                )
                user_content = (
                    f"视频字幕背景内容：\n{self.srt_text}\n\n"
                    f"镜头时间段列表：\n{scenes_text}\n\n"
                    "请直接输出分配好后的 JSON 数组。"
                )
            else:
                # Silent video, we must generate description from visual keyframes
                system_prompt = (
                    "你是一个视频画面描述专家。给定一个无声视频被分割出的所有镜头时间段，以及每个镜头的关键帧图片。\n"
                    "请为每一个镜头设计一句简短的画面描述文案（字数控制在10-25字之间，用以说明该镜头展示了什么内容或概念，如：产品外观展示、运动特写、价格对比等）。\n"
                    "请注意镜头之间的衔接和整体文案的吸引力。\n"
                    "请严格以 JSON 格式输出，不得包含 markdown 标记或任何解释文字，格式如下：\n"
                    "[\n"
                    "  {\"index\": 1, \"description\": \"第一镜头的描述文案\"},\n"
                    "  {\"index\": 2, \"description\": \"第二镜头的描述文案\"}\n"
                    "]"
                )
                
                # Extract keyframes for all scenes
                user_content = []
                user_content.append({"type": "text", "text": "以下是视频中所有分割镜头的关键帧图片：\n\n"})
                for idx, (scene_start, scene_end) in enumerate(self.scenes, 1):
                    clip_path = ""
                    if idx - 1 < len(self.split_video_paths):
                        clip_path = self.split_video_paths[idx - 1]
                    
                    keyframes = []
                    if clip_path:
                        try:
                            keyframes = extract_keyframes(clip_path)
                            log.info(f"BatchGenerateDescriptionsWorker - 镜头 {idx} 成功抽帧 {len(keyframes)} 张关键图片。")
                        except Exception as e:
                            log.warning(f"提取视频关键帧失败: {clip_path}, 错误: {e}")
                    
                    user_content.append({"type": "text", "text": f"镜头 {idx} ({scene_start:.2f}s --> {scene_end:.2f}s):\n"})
                    if keyframes and is_vision:
                        for kf_b64 in keyframes:
                            user_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{kf_b64}"
                                }
                            })
                    user_content.append({"type": "text", "text": "\n\n"})
                
            # Call LLM API
            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2
            }
            
            log.info(f"BatchGenerateDescriptionsWorker - 正在请求大模型 API: {url}，以整体方式生成镜头描述。")
            res = requests.post(url, json=payload, headers=headers, timeout=60)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}, Response: {res.text}")
            
            data = res.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            log.info(f"BatchGenerateDescriptionsWorker - 大模型返回内容:\n{content}")
            
            # Clean markdown codeblocks
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            # Extract JSON array
            if not content.startswith("["):
                start_idx = content.find("[")
                end_idx = content.rfind("]")
                if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                    content = content[start_idx:end_idx+1]
            
            results = json.loads(content)
            for item in results:
                desc_dict[int(item["index"])] = item["description"]
            
            # Fill missing indices with default
            for idx in range(1, len(self.scenes) + 1):
                if idx not in desc_dict:
                    desc_dict[idx] = f"镜头片段 {idx}"
                    
            log.info(f"BatchGenerateDescriptionsWorker - 整体文案对齐生成成功，共 {len(desc_dict)} 个镜头描述。")
            self.finished.emit(json.dumps({str(k): v for k, v in desc_dict.items()}, ensure_ascii=False))
            
        except Exception as e:
            log.exception("BatchGenerateDescriptionsWorker 运行发生异常")
            self.error.emit(str(e))


class LocalVisionDescWorker(BaseWorker):
    """使用本地 Ollama 视觉模型（qwen2.5vl）分析每个分割镜头的画面内容，生成画面描述文案。

    有字幕时：结合字幕文案 + 画面截图，生成带营销感的描述。
    无字幕时：纯画面视觉分析。
    """

    finished = Signal(str)  # JSON string: {"1": "desc1", "2": "desc2", ...}

    def __init__(self, vision_api_url, vision_model, split_video_paths, scenes,
                 srt_text="", srt_segments=None):
        super().__init__()
        self.vision_api_url = vision_api_url.rstrip("/")
        self.vision_model = vision_model
        self.split_video_paths = split_video_paths
        self.scenes = scenes
        self.srt_text = srt_text
        self.srt_segments = srt_segments or []  # list of (start_sec, end_sec, text)

    def _find_subtitle_for_shot(self, shot_start, shot_end):
        """找到与该镜头时间重叠的字幕文本。"""
        matched_texts = []
        for seg_start, seg_end, text in self.srt_segments:
            # 有重叠即匹配
            if seg_start < shot_end and seg_end > shot_start:
                text = text.strip()
                if text:
                    matched_texts.append(text)
        return " ".join(matched_texts) if matched_texts else ""

    def _extract_mid_frame(self, video_path):
        """从视频中间位置抽取一帧，返回 base64 jpg。"""
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return None
        mid = total_frames // 2
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        # Resize to max 512px for token efficiency
        h, w = frame.shape[:2]
        max_size = 512
        if h > max_size or w > max_size:
            if h > w:
                new_h, new_w = max_size, int(w * max_size / h)
            else:
                new_h, new_w = int(h * max_size / w), max_size
            frame = cv2.resize(frame, (new_w, new_h))
        ret_jpg, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret_jpg:
            return None
        return base64.b64encode(buffer).decode("utf-8")

    def run(self):
        try:
            import json as _json
            desc_dict = {}
            total = len(self.split_video_paths)
            has_subtitles = bool(self.srt_segments)

            system_prompt_vision_only = (
                "你是一个视频画面描述专家。请仔细观察这张视频截图，用一句简短的中文（10-25字）"
                "描述画面中的核心视觉内容，包括：主体对象、动作/姿态、场景/环境。"
                "只输出描述文字，不要编号、不要引号、不要任何额外解释。"
            )
            system_prompt_with_srt = (
                "你是一个短视频营销文案专家。请结合下方提供的【口播字幕文案】和这张【视频截图】，"
                "生成一句简短有营销感的中文画面描述（10-25字）。"
                "描述应提炼画面中的视觉卖点，并与字幕内容呼应。"
                "只输出描述文字，不要编号、不要引号、不要任何额外解释。"
            )

            for idx, clip_path in enumerate(self.split_video_paths, 1):
                try:
                    frame_b64 = self._extract_mid_frame(clip_path)
                    if not frame_b64:
                        desc_dict[idx] = f"镜头片段 {idx}"
                        continue

                    # Check for subtitle text aligned to this shot
                    shot_start, shot_end = (0.0, 0.0)
                    if idx - 1 < len(self.scenes):
                        shot_start, shot_end = self.scenes[idx - 1]
                    sub_text = self._find_subtitle_for_shot(shot_start, shot_end)

                    if sub_text:
                        system_prompt = system_prompt_with_srt
                        user_text = f"【口播字幕文案】{sub_text}\n\n请结合截图生成画面描述。"
                    else:
                        system_prompt = system_prompt_vision_only
                        user_text = "请描述这张截图的画面内容。"

                    payload = {
                        "model": self.vision_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text,
                             "images": [frame_b64]},
                        ],
                        "stream": False,
                        "options": {"num_ctx": 4096},
                    }
                    resp = requests.post(
                        f"{self.vision_api_url}/api/chat",
                        json=payload,
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data.get("message", {}).get("content", "").strip()
                        content = content.strip("'\"\"'").split("\n")[0].strip()
                        if content:
                            desc_dict[idx] = content[:30]
                        else:
                            desc_dict[idx] = f"镜头片段 {idx}"
                    else:
                        log.warning(f"Vision API error for clip {idx}: HTTP {resp.status_code}")
                        desc_dict[idx] = f"镜头片段 {idx}"
                except Exception as e:
                    log.warning(f"Vision analysis failed for clip {idx}: {e}")
                    desc_dict[idx] = f"镜头片段 {idx}"

            log.info(f"LocalVisionDescWorker - 完成 {len(desc_dict)}/{total} 个镜头画面分析"
                     + ("（结合字幕）" if has_subtitles else "（纯画面）"))
            self.finished.emit(_json.dumps({str(k): v for k, v in desc_dict.items()}, ensure_ascii=False))
        except Exception as e:
            log.exception("LocalVisionDescWorker 运行发生异常")
            self.error.emit(str(e))


class AITextRewriteWorker(BaseWorker):
    finished = Signal(str)  # Emits the rewritten text

    def __init__(self, api_url, api_key, model, input_text):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.input_text = input_text

    def run(self):
        try:
            import requests
            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "你是一个顶尖的短视频脚本与广告文案改写、润色与重构专家。\n"
                "请对用户提供的一段短视频配音文案（每行对应一个画面的旁白/配音）进行整体性的改写和润色，使其更具有爆款短视频的吸引力、更通顺、更有销售力或表现力。\n"
                "要求：\n"
                "1. 保持原有的行数，不要合并或删减行，因为每一行将严格对应视频中的一个画面镜头段。\n"
                "2. 针对每一行，输出改写优化后的新文案（控制在10-25字之间）。\n"
                "3. 保持整体文案在逻辑与情感上的连贯性，使其朗朗上口。\n"
                "4. 请直接按行返回改写后的纯文本，不要用 markdown 包裹，千万不要返回任何多余的解释、问候或废话！"
            )
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self.input_text}
                ],
                "temperature": 0.3
            }
            
            res = requests.post(url, json=payload, headers=headers, timeout=45)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}")
            
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Empty response from LLM")
            content = choices[0].get("message", {}).get("content", "").strip()
            
            # Clean up markdown code blocks if any
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
                
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))


class ProductCopyWorker(BaseWorker):
    """根据品牌/产品/型号，调用大模型生成电商短视频口播文案（纯文本，每行一句）。"""
    finished = Signal(str)  # 生成的口播文案

    def __init__(self, api_url, api_key, model, brand, product, model_name, extra=""):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.brand = brand
        self.product = product
        self.model_name = model_name
        self.extra = extra

    def run(self):
        try:
            import requests
            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "你是资深电商短视频口播文案撰稿人。用户会给出产品的品牌、品类/产品、型号以及可选卖点。\n"
                "请基于你对该产品的了解，撰写一段用于电商带货短视频的口播文案（旁白）。\n"
                "要求：\n"
                "1. 直接输出口播文案纯文本，每行一句，共 5-7 行，每行约 10-22 字，口语化、有节奏、有卖点和号召力。\n"
                "2. 突出该型号产品的核心卖点/参数/适用场景；若不确定具体参数，用准确的通用描述，切勿编造虚假数字。\n"
                "3. 不要 markdown、不要标题、不要解释说明，只输出文案本身，每句独占一行。"
            )
            user_msg = (
                f"品牌：{self.brand or '未提供'}\n"
                f"产品/品类：{self.product or '未提供'}\n"
                f"型号：{self.model_name or '未提供'}\n"
                f"补充卖点：{self.extra or '无'}\n\n"
                "请按要求生成口播文案。"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.6
            }
            res = requests.post(url, json=payload, headers=headers, timeout=60)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API 请求失败: HTTP {res.status_code} {res.text[:200]}")
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("大模型返回为空")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            # 去掉空行
            content = "\n".join([ln.strip() for ln in content.splitlines() if ln.strip()])
            if not content:
                raise RuntimeError("大模型未生成有效文案")
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))


class SceneCopyWorker(BaseWorker):
    """根据组合视频的画面镜头描述（按顺序）+ 可选的共同产品背景，调用大模型生成口播文案。

    输出每行对应一个镜头画面，按顺序排列，便于后续逐镜头配音映射。
    """
    finished = Signal(str)  # 生成的口播文案

    def __init__(self, api_url, api_key, model, scene_descriptions,
                 brand="", product="", model_name="", extra=""):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.scene_descriptions = scene_descriptions or []
        self.brand = brand
        self.product = product
        self.model_name = model_name
        self.extra = extra

    def run(self):
        try:
            import requests
            n = len(self.scene_descriptions)
            if n == 0:
                raise RuntimeError("该视频没有可用的画面镜头描述，无法按画面生成文案。")

            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "你是资深电商短视频口播文案撰稿人。用户会给出一个产品的共同背景信息（品牌/品类/型号/卖点），"
                "以及该条组合视频按顺序排列的每一个镜头画面描述。\n"
                "请为这条视频撰写一段用于电商带货的口播文案（旁白），要求：\n"
                f"1. 严格输出 {n} 行，第 i 行对应第 i 个镜头画面，顺序不可打乱。\n"
                "2. 每行文案要贴合对应镜头画面的内容（如产品外观、特写、使用场景、价格对比等），口语化、有节奏、有卖点和号召力，每行约 10-22 字。\n"
                "3. 所有行围绕同一款产品（同一型号）展开，整体文案在逻辑与情感上连贯、朗朗上口。\n"
                "4. 若不确定具体参数，用准确的通用描述，切勿编造虚假数字。\n"
                "5. 不要 markdown、不要标题、不要编号、不要解释说明，只输出文案本身，每句独占一行。"
            )
            scenes_str = "\n".join(
                f"{i + 1}. {desc.strip() or '（无画面描述，请根据上下文合理发挥）'}"
                for i, desc in enumerate(self.scene_descriptions)
            )
            user_msg = (
                "产品共同背景：\n"
                f"品牌：{self.brand or '未提供'}\n"
                f"产品/品类：{self.product or '未提供'}\n"
                f"型号：{self.model_name or '未提供'}\n"
                f"补充卖点：{self.extra or '无'}\n\n"
                f"本条视频共有 {n} 个镜头画面，按顺序如下：\n{scenes_str}\n\n"
                f"请按要求生成口播文案，严格输出 {n} 行。"
            )
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.6
            }
            res = requests.post(url, json=payload, headers=headers, timeout=90)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API 请求失败: HTTP {res.status_code} {res.text[:200]}")
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("大模型返回为空")
            content = choices[0].get("message", {}).get("content", "").strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            # 去掉空行
            content = "\n".join([ln.strip() for ln in content.splitlines() if ln.strip()])
            if not content:
                raise RuntimeError("大模型未生成有效文案")
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))


class ProductCopyInputDialog(QDialog):
    """输入品牌/产品/型号/补充卖点，用于生成口播文案。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✍ 生成口播文案")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel("输入产品信息，由大模型生成该组合视频的口播文案："))

        def _row(lbl_text, placeholder):
            r = QHBoxLayout()
            l = QLabel(lbl_text)
            l.setFixedWidth(64)
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            r.addWidget(l)
            r.addWidget(e, 1)
            layout.addLayout(r)
            return e

        self.brand_in = _row("品牌：", "如 罗技 / Logitech")
        self.product_in = _row("产品：", "如 鼠标 / 键盘 / 无线耳机")
        self.model_in = _row("型号：", "如 G502 / MX Master 3S")

        layout.addWidget(QLabel("补充卖点（可选）："))
        self.extra_in = QTextEdit()
        self.extra_in.setPlaceholderText("如 8K回报率、轻量化、长续航……（可留空）")
        self.extra_in.setFixedHeight(60)
        layout.addWidget(self.extra_in)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("生成")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def get_values(self):
        return (self.brand_in.text().strip(), self.product_in.text().strip(),
                self.model_in.text().strip(), self.extra_in.toPlainText().strip())


class BatchAITextRewriteWorker(BaseWorker):
    row_finished = Signal(int, str)  # row_idx, rewritten_text
    progress = Signal(int)           # progress value (0-100)
    finished = Signal()

    def __init__(self, api_url, api_key, model, tasks, temperature=0.5):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.tasks = tasks # list of (row_idx, text)
        self.temperature = temperature

    def run(self):
        try:
            import requests
            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            freedom_pct = int((1.0 - self.temperature) * 100)
            
            if freedom_pct >= 80:
                rewrite_instruction = (
                    "请对用户提供的文案进行最小幅度的润色，尽量保持原文字词和句式不变，只修正明显的语病或不通顺之处。"
                )
            elif freedom_pct >= 50:
                rewrite_instruction = (
                    "请对用户提供的文案进行较大幅度的改写和润色，可以使用不同的表达方式和词汇，使其更朗朗上口、更生动、更有网感，但必须保留原有的核心意思。"
                )
            elif freedom_pct >= 20:
                rewrite_instruction = (
                    "请对用户提供的文案进行大幅改写和重构，显著改变表达方式和句式结构，大胆使用新词汇，大幅提升感染力和传播力，只保留最核心的主题不变。"
                )
            else:
                rewrite_instruction = (
                    "请对用户提供的文案进行彻底的重写和创作，完全抛弃原文的用词和句式，用全新的、极具冲击力的方式表达核心意思，最大化网感和爆款潜力。"
                )

            system_prompt = (
                "你是一个顶尖的短视频脚本与广告文案改写、润色与重构专家。\n"
                + rewrite_instruction + "\n"
                "要求：\n"
                "1. 如果用户提供了多行文案，请对每一行分别进行改写优化，并保持与原行一一对应的行数。\n"
                "2. 每行改写后的文案控制在15-35字之间。\n"
                "3. 请直接返回改写后的纯文本（保持多行格式，每行对应原输入的一行），千万不要返回任何多余的解释、问候、序号或包裹符号（不要有markdown的引文框）！"
            )
            
            total = len(self.tasks)
            for index, (row_idx, input_text) in enumerate(self.tasks):
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": input_text}
                    ],
                    "temperature": self.temperature
                }
                res = requests.post(url, json=payload, headers=headers, timeout=20)
                if res.status_code != 200:
                    raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}")
                
                data = res.json()
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError("Empty response from LLM")
                
                content = choices[0].get("message", {}).get("content", "").strip()
                # Clean up markdown code blocks if any
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                
                # strip quotes
                if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
                    content = content[1:-1].strip()
                if (content.startswith('“') and content.endswith('”')) or (content.startswith('‘') and content.endswith('’')):
                    content = content[1:-1].strip()
                    
                self.row_finished.emit(row_idx, content)
                self.progress.emit(int((index + 1) / total * 100))
                
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))




class ScriptMatchLLMWorker(BaseWorker):
    finished = Signal(list, list)  # Emits (matched_paths, matched_descriptions)

    def __init__(self, api_url, api_key, model, rewritten_text, candidate_clips, split_descriptions):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.rewritten_text = rewritten_text
        self.candidate_clips = candidate_clips
        self.split_descriptions = split_descriptions

    def run(self):
        try:
            import requests
            import json
            
            rewritten_lines = [line.strip() for line in self.rewritten_text.split("\n") if line.strip()]
            if not rewritten_lines:
                raise ValueError("改写后的文案为空。")

            candidate_list_str = ""
            for idx, clip in enumerate(self.candidate_clips, 1):
                desc = self.split_descriptions.get(clip, "无描述")
                filename = os.path.basename(clip)
                candidate_list_str += f"{idx}. 视频: {filename}, 画面描述: {desc}\n"

            rewritten_list_str = ""
            for idx, line in enumerate(rewritten_lines, 1):
                rewritten_list_str += f"{idx}. {line}\n"

            url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            system_prompt = (
                "你是一个视频智能剪辑匹配专家。你的任务是分析改写后的文案（按行分开），以及待排列的视频镜头候选列表（包含编号、文件名和画面描述）。\n"
                "请为改写后文案的每一行，从待排列候选镜头中找出最匹配的一个镜头。请按顺序匹配，并严格以 JSON 格式返回结果。\n"
                "JSON 格式要求如下：一个包含对象的数组，每个对象包含 'line_index'（从1开始的文案行号）和 'best_match_shot_index'（最匹配的候选镜头编号，1到候选总数之间）。\n"
                "例如：\n"
                "[{\"line_index\": 1, \"best_match_shot_index\": 3}, {\"line_index\": 2, \"best_match_shot_index\": 1}]\n"
                "请只返回 JSON 数据本身，不要用 markdown 包裹，不要有任何其他解释或废话。"
            )
            user_content = (
                f"待排列镜头候选列表：\n{candidate_list_str}\n\n"
                f"改写后的新文案列表：\n{rewritten_list_str}"
            )

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.1
            }
            
            res = requests.post(url, json=payload, headers=headers, timeout=45)
            if res.status_code != 200:
                raise RuntimeError(f"LLM API request failed: HTTP {res.status_code}")
            
            data = res.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Empty response from LLM")
            content = choices[0].get("message", {}).get("content", "").strip()
            
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            match_results = json.loads(content)
            
            matched_paths = []
            matched_descs = []
            for item in match_results:
                shot_idx = int(item["best_match_shot_index"]) - 1
                line_idx = int(item["line_index"]) - 1
                desc = rewritten_lines[line_idx] if 0 <= line_idx < len(rewritten_lines) else ""
                
                if 0 <= shot_idx < len(self.candidate_clips):
                    matched_paths.append(self.candidate_clips[shot_idx])
                else:
                    matched_paths.append(self.candidate_clips[0])
                matched_descs.append(desc)
            
            if not matched_paths:
                raise ValueError("未能匹配到任何有效镜头。")
                
            self.finished.emit(matched_paths, matched_descs)
            
        except Exception as e:
            self.error.emit(str(e))



class VideoConcatWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Emits list of generated files absolute paths

    def __init__(self, selected_clips, output_dir, layout_mode, recombine_mode, target_clip_count, batch_count, split_descriptions=None, randomness="medium", selected_descriptions_list=None, transition="fade"):
        super().__init__()
        self.selected_clips = selected_clips
        self.output_dir = output_dir
        self.layout_mode = layout_mode
        self.recombine_mode = recombine_mode
        self.target_clip_count = target_clip_count
        self.batch_count = batch_count
        self.split_descriptions = split_descriptions or {}
        self.randomness = randomness
        self.selected_descriptions_list = selected_descriptions_list
        self.transition = transition or "fade"

    def _probe_resolution(self, clip):
        """用 ffprobe 读取视频显示分辨率（已考虑旋转），失败返回 None。"""
        import re as _re
        try:
            from utils.platform_utils import find_ffprobe
            ffprobe = find_ffprobe()
            if not os.path.isfile(ffprobe):
                ff = find_ffmpeg()
                ffprobe = ff.replace("ffmpeg", "ffprobe")
            cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
                   "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", clip]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=cf, timeout=15)
            m = _re.search(r"(\d+)x(\d+)", (r.stdout or "").strip())
            if m:
                w, h = int(m.group(1)), int(m.group(2))
                if w > 0 and h > 0:
                    return w, h
        except Exception as e:
            log.warning(f"探测原视频分辨率失败: {e}")
        return None

    # ffmpeg xfade 转场类型映射
    _XFADE_MAP = {
        "fade": "fade",
        "dissolve": "dissolve",
        "slideleft": "slideleft",
        "slideright": "slideright",
        "slideup": "slideup",
        "slidedown": "slidedown",
        "zoomin": "zoomin",
        "zoomout": "zoomout",
    }

    def _concat_with_transition(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx):
        """用 ffmpeg xfade 滤镜拼接镜头，实现转场动画。"""
        if not clips:
            return subprocess.CompletedProcess(args=[], returncode=1, stderr="no clips")

        # 单个镜头直接复制
        if len(clips) == 1:
            cmd = [ffmpeg_path, "-y", "-i", clips[0], "-c", "copy", out_file]
            return subprocess.run(cmd, capture_output=True, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

        xfade_type = self._XFADE_MAP.get(self.transition, "fade")
        transition_dur = 0.5  # 转场时长 0.5 秒

        # 获取每个片段的时长
        durations = []
        for clip in clips:
            dur = 0.0
            try:
                cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", clip]
                pr = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if pr.returncode == 0 and pr.stdout.strip():
                    dur = float(pr.stdout.strip())
            except Exception:
                pass
            if dur <= 0:
                dur = 5.0
            durations.append(dur)

        # 构建 xfade 滤镜链
        # xfade 语法: [v0][v1]xfade=transition=fade:duration=0.5:offset=4.5[v01]
        # offset = 前一个片段结束时间 - 转场时长
        n = len(clips)
        filter_parts = []
        inputs = []
        for clip in clips:
            inputs += ["-i", clip]

        # 第一个转场
        prev_label = "0:v"
        accumulated = durations[0]
        for i in range(1, n):
            offset = max(0, accumulated - transition_dur)
            out_label = f"v{i:02d}"
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition={xfade_type}:duration={transition_dur}:offset={offset:.3f}[{out_label}]"
            )
            prev_label = out_label
            accumulated = offset + transition_dur + (durations[i] - transition_dur)

        # 音频用 concat 拼接（简单交叉不需要复杂音频转场）
        audio_filter_parts = []
        for i in range(n):
            audio_filter_parts.append(f"[{i}:a]")
        audio_filter_parts.append(f"concat=n={n}:v=0:a=1[aout]")
        audio_filter = "".join(audio_filter_parts)

        final_vlabel = prev_label
        filter_complex = ";".join(filter_parts) + ";" + audio_filter

        cmd = [ffmpeg_path, "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{final_vlabel}]",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out_file
        ]
        return subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            from utils.platform_utils import find_ffprobe
            ffprobe_path = find_ffprobe()
            if not os.path.isfile(ffprobe_path):
                ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

            if not self.selected_clips:
                raise RuntimeError("未选择任何镜头素材。")

            self.stage.emit("准备标准化转码工作...")
            self.progress.emit(5)

            # Establish temp working dir inside output_dir
            temp_dir = os.path.join(self.output_dir, ".temp_concat")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)

            if self.layout_mode == "vertical":
                width, height = 1080, 1920
            elif self.layout_mode == "horizontal":
                width, height = 1920, 1080
            else:  # "source": 与原视频一致，取第一个素材的分辨率
                res = self._probe_resolution(self.selected_clips[0])
                if res:
                    width, height = res
                    width -= width % 2      # 保证为偶数，libx264 要求
                    height -= height % 2
                    self.stage.emit(f"输出画幅与原视频一致：{width}x{height}")
                else:
                    width, height = 1080, 1920  # 探测失败回退竖屏

            # Step 1: Transcode all selected candidate clips once to temporary folder
            normalized_list = []
            norm_to_desc = {}
            skipped_clips = []
            for i, clip in enumerate(self.selected_clips):
                # 先用 ffprobe 快速检测文件是否完整（moov atom 存在），跳过损坏文件
                clip_abspath = os.path.abspath(clip)
                if not os.path.isfile(clip_abspath) or os.path.getsize(clip_abspath) < 1024:
                    self.stage.emit(f"⚠ 跳过损坏/过小文件: {os.path.basename(clip)}")
                    skipped_clips.append(clip)
                    continue
                probe_cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", clip_abspath]
                try:
                    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15,
                                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                    if probe_r.returncode != 0 or not probe_r.stdout.strip():
                        self.stage.emit(f"⚠ 跳过无法读取的文件: {os.path.basename(clip)}")
                        skipped_clips.append(clip)
                        continue
                except Exception:
                    self.stage.emit(f"⚠ 跳过探测失败的文件: {os.path.basename(clip)}")
                    skipped_clips.append(clip)
                    continue

                self.stage.emit(f"规格标准化转码并标记 ({i+1}/{len(self.selected_clips)}): {os.path.basename(clip)}")
                norm_out = os.path.join(temp_dir, f"norm_{i:04d}.mp4")

                # No sequence overlay watermark
                vf_scale_pad = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30"
                vf_filter = vf_scale_pad

                cmd = [
                    ffmpeg_path, "-y", "-i", clip_abspath,
                    "-vf", vf_filter,
                    "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    norm_out
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if r.returncode != 0:
                    log.warning(f"标准化转码单镜头失败，跳过: {clip}\n{r.stderr[-300:]}")
                    self.stage.emit(f"⚠ 转码失败，跳过: {os.path.basename(clip)}")
                    skipped_clips.append(clip)
                    continue

                normalized_list.append(norm_out)
                if self.selected_descriptions_list is not None and i < len(self.selected_descriptions_list):
                    norm_to_desc[norm_out] = self.selected_descriptions_list[i]
                else:
                    norm_to_desc[norm_out] = self.split_descriptions.get(os.path.abspath(clip), "")
                prog = 10 + int((i + 1) / len(self.selected_clips) * 70)
                self.progress.emit(prog)

            if not normalized_list:
                raise RuntimeError("所有镜头文件均损坏或转码失败，无法合成视频。请重新进行镜头分割。")
            if skipped_clips:
                self.stage.emit(f"⚠ 共跳过 {len(skipped_clips)} 个损坏文件，继续合成剩余 {len(normalized_list)} 个镜头")

            # Step 2: Batch generate fast concatenations
            generated_paths = []
            for batch_idx in range(self.batch_count):
                self.stage.emit(f"无损拼接第 {batch_idx+1}/{self.batch_count} 个视频...")
                
                batch_clips = list(normalized_list)
                if self.recombine_mode == "random":
                    if self.randomness == "high":
                        random.shuffle(batch_clips)
                    elif self.randomness == "medium":
                        # Group consecutive clips with same description
                        groups = []
                        current_group = []
                        current_desc = None
                        for n_clip in batch_clips:
                            desc = norm_to_desc.get(n_clip, "").strip()
                            if not current_group:
                                current_group.append(n_clip)
                                current_desc = desc
                            else:
                                if desc == current_desc and desc != "":
                                    current_group.append(n_clip)
                                else:
                                    groups.append(current_group)
                                    current_group = [n_clip]
                                    current_desc = desc
                        if current_group:
                            groups.append(current_group)
                        
                        # Shuffle the groups
                        random.shuffle(groups)
                        # Flatten
                        batch_clips = [c for group in groups for c in group]
                    elif self.randomness == "low":
                        # Low randomness = no shuffling, keep sequential order
                        pass
                
                if len(batch_clips) > self.target_clip_count:
                    batch_clips = batch_clips[:self.target_clip_count]
                elif len(batch_clips) < self.target_clip_count:
                    extra_needed = self.target_clip_count - len(batch_clips)
                    for _ in range(extra_needed):
                        batch_clips.append(random.choice(normalized_list))
                
                # Generate combined script for this batch
                batch_desc_lines = []
                for n_clip in batch_clips:
                    desc = norm_to_desc.get(n_clip, "").strip()
                    if desc:
                        batch_desc_lines.append(desc)
                batch_script = "\n".join(batch_desc_lines)

                out_file = os.path.join(self.output_dir, f"montage_concat_{random.randint(1000, 9999)}_{batch_idx+1}.mp4")

                # 使用 xfade 滤镜实现转场动画（非 copy 模式，需要重新编码）
                r = self._concat_with_transition(ffmpeg_path, ffprobe_path, batch_clips, out_file, temp_dir, batch_idx)
                if r.returncode != 0:
                    # 转场拼接失败，回退到无损 concat
                    log.warning(f"转场拼接失败，回退到普通拼接: {r.stderr[-200:]}")
                    concat_txt = os.path.join(temp_dir, f"concat_{batch_idx}.txt")
                    with open(concat_txt, "w", encoding="utf-8") as f:
                        for n_clip in batch_clips:
                            safe_path = n_clip.replace("\\", "/")
                            f.write(f"file '{safe_path}'\n")
                    cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_file]
                    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                    if r.returncode != 0:
                        raise RuntimeError(f"拼接第 {batch_idx+1} 个视频失败：\n{r.stderr}")
                
                # Save the combined script to a companion .txt file next to the video
                txt_file = os.path.splitext(out_file)[0] + ".txt"
                try:
                    with open(txt_file, "w", encoding="utf-8") as tf:
                        tf.write(batch_script)
                except Exception as e:
                    log.warning(f"保存视频合成文案失败: {e}")

                # Save the list of original source clips that make up this generated video
                sources_file = os.path.splitext(out_file)[0] + "_sources.txt"
                try:
                    original_sources = []
                    for n_clip in batch_clips:
                        filename = os.path.basename(n_clip)
                        if filename.startswith("norm_") and filename.endswith(".mp4"):
                            try:
                                idx = int(filename.split("_")[1].split(".")[0])
                                if 0 <= idx < len(self.selected_clips):
                                    original_sources.append(self.selected_clips[idx])
                            except Exception:
                                pass
                    with open(sources_file, "w", encoding="utf-8") as sf:
                        for src in original_sources:
                            sf.write(src + "\n")
                except Exception as e:
                    log.warning(f"保存视频源镜头列表失败: {e}")

                generated_paths.append(out_file)
                self.progress.emit(80 + int((batch_idx + 1) / self.batch_count * 20))

            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

            self.stage.emit(f"批量拼接完成，共生成 {self.batch_count} 个视频！")
            self.progress.emit(100)
            self.finished.emit(generated_paths)

        except Exception:
            log.exception("批量拼接合并失败")
            self.error.emit(traceback.format_exc())

class VoiceCloneWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    row_progress = Signal(int, int) # row_idx, value (0-100)
    finished = Signal(dict)  # Outputs a dict mapping: video_path -> voice_wav_path

    def __init__(self, tasks, voice_ref_audio, voice_ref_text, voice_mode, voice_api_url, voice_cli_checkpoint, temp_dir, task_type="video",
                 inference_timesteps=10, cfg_value=2.0, speed_min=0.9, speed_max=1.2):
        super().__init__()
        self.tasks = tasks  # list of tuples: (row_idx, text, video_path, output_wav_path)
        self.voice_ref_audio = voice_ref_audio
        self.voice_ref_text = voice_ref_text
        self.voice_mode = voice_mode
        self.voice_api_url = voice_api_url
        self.voice_cli_checkpoint = voice_cli_checkpoint
        self.temp_dir = temp_dir
        self.task_type = task_type
        self.inference_timesteps = inference_timesteps
        self.cfg_value = cfg_value
        self.speed_min = speed_min  # 变速下限：音频过长时最多拉慢到此倍速，超出不调整
        self.speed_max = speed_max  # 变速上限：音频过短时最多加速到此倍速，超出不调整
        self.failures = []  # [(row_idx, video_path, error_msg)] 单条失败记录（不中断整批）

    def _health_url(self):
        """由 TTS 接口地址推导出 /health 健康检查地址。"""
        try:
            u = self.voice_api_url
            for suffix in ("/v1/tts", "/tts"):
                if u.endswith(suffix):
                    return u[: -len(suffix)] + "/health"
            # 兜底：取 scheme://host:port + /health
            from urllib.parse import urlparse
            p = urlparse(u)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}/health"
        except Exception:
            pass
        return None

    def _wait_for_server_recovery(self, max_wait=20.0):
        """连接中断后，轮询 /health 等待服务恢复；返回是否恢复。"""
        health = self._health_url()
        if not health:
            time.sleep(min(3.0, max_wait))
            return False
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                r = requests.get(health, timeout=3)
                if r.status_code == 200 and r.json().get("model_loaded"):
                    return True
            except Exception:
                pass
            time.sleep(2.0)
        return False

    @staticmethod
    def _preprocess_tts_text(text: str) -> str:
        """预处理发往 TTS 的文本：阿拉伯数字转中文、大写英文缩写拆为逐字母。

        解决的问题：
        - "8000 DPI" → VoxCPM 可能读成"八零零零"或跳过 → 预处理为"八千 D P I"
        - "LIGHTSPEED" 等品牌词被跳过 → 拆为"L I G H T S P E E D"逐字播报
        - "Type-C" → "Type C"（去连字符，避免停顿异常）
        """
        import re

        CN_DIGITS = "零一二三四五六七八九"

        def int_to_cn(n: int) -> str:
            if n == 0:
                return "零"
            units = [
                (100_000_000, "亿"), (10_000, "万"),
                (1_000, "千"), (100, "百"), (10, "十"), (1, ""),
            ]
            result = ""
            need_zero = False
            for val, name in units:
                d = n // val
                n %= val
                if d:
                    if need_zero:
                        result += "零"
                        need_zero = False
                    if not (val == 10 and d == 1 and not result):
                        result += CN_DIGITS[d]
                    result += name
                elif result:
                    need_zero = True
            return result

        # 1. 整数 → 中文（先处理小数 x.y → 中文x点中文y，再处理整数）
        def replace_decimal(m):
            try:
                int_part = int_to_cn(int(m.group(1)))
                frac_part = int_to_cn(int(m.group(2)))
                return f"{int_part}点{frac_part}"
            except Exception:
                return m.group(0)

        def replace_int(m):
            try:
                return int_to_cn(int(m.group(0)))
            except Exception:
                return m.group(0)

        text = re.sub(r'\b(\d+)\.(\d+)\b', replace_decimal, text)
        text = re.sub(r'\b\d+\b', replace_int, text)

        # 2. 全大写英文缩写（2字母以上）→ 字母间加空格，便于逐字播报
        _keep_units = {"Hz", "MHz", "GHz", "kHz"}
        def space_caps(m):
            w = m.group(0)
            return w if w in _keep_units else " ".join(list(w))
        text = re.sub(r'\b[A-Z]{2,}\b', space_caps, text)

        # 3. 英文连字符 → 空格（Type-C → Type C）
        text = re.sub(r'([A-Za-z])-([A-Za-z])', r'\1 \2', text)

        return text

    def _post_tts(self, text, ref_audio_b64, row_idx, label=""):
        """向 VoxCPM 发起一次合成请求，带连接级/503 重试，返回 wav 字节；失败抛异常。"""
        payload = {
            "text": self._preprocess_tts_text(text),
            "format": "wav",
            "normalize": True,
            "inference_timesteps": self.inference_timesteps,
            "cfg_value": self.cfg_value,
        }
        if ref_audio_b64:
            payload["references"] = [{
                "audio": ref_audio_b64,
                "text": self.voice_ref_text or ""
            }]
        max_attempts = 3
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                res = requests.post(self.voice_api_url, json=payload, timeout=180)
                if res.status_code == 503:
                    raise RuntimeError(f"接口繁忙/显存不足 (503): {res.text[:200]}")
                if res.status_code != 200:
                    raise RuntimeError(f"接口返回错误 ({res.status_code}): {res.text[:200]}")
                return res.content
            except requests.exceptions.RequestException as e:
                # 连接被重置/超时：服务可能崩溃，等待恢复后重试
                last_err = e
                if attempt < max_attempts:
                    self.stage.emit(
                        f"第 {row_idx + 1} 个声音{label}连接中断，等待服务恢复后重试 "
                        f"({attempt}/{max_attempts - 1})...")
                    if not self._wait_for_server_recovery(max_wait=20.0):
                        time.sleep(2.0)
                    continue
                raise RuntimeError(f"连接失败（已重试 {max_attempts} 次）：{e}") from e
            except RuntimeError as e:
                last_err = e
                # 仅对 503（显存不足）重试，其它确定性错误直接抛出
                if "503" in str(e) and attempt < max_attempts:
                    self.stage.emit(
                        f"第 {row_idx + 1} 个声音{label}显存不足，稍后重试 "
                        f"({attempt}/{max_attempts - 1})...")
                    self._wait_for_server_recovery(max_wait=15.0)
                    time.sleep(2.0)
                    continue
                raise
        raise RuntimeError(f"合成失败：{last_err}")

    @staticmethod
    def _split_sentences(text):
        """将（可能多行的）文案切分为可朗读的短句，过滤掉只含标点/符号的片段。"""
        import re
        segs = []
        for line in (text or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            for part in re.split(r"(?<=[。！？!?；;…])", line):
                part = part.strip()
                if part:
                    segs.append(part)
        # 仅保留含有中文/字母/数字（可朗读内容）的片段
        return [s for s in segs if re.search(r"[一-鿿A-Za-z0-9]", s)]

    @staticmethod
    def _concat_wav_bytes(wav_list, gap_sec=0.15):
        """把多段 wav 字节按顺序拼接为一段（句间插入少量静音），返回 wav 字节。"""
        import io
        import wave
        if not wav_list:
            raise RuntimeError("没有可拼接的音频片段")
        out_io = io.BytesIO()
        writer = None
        params = None
        try:
            for i, wb in enumerate(wav_list):
                with wave.open(io.BytesIO(wb), "rb") as w:
                    p = w.getparams()
                    frames = w.readframes(w.getnframes())
                if writer is None:
                    params = p
                    writer = wave.open(out_io, "wb")
                    writer.setparams(p)
                writer.writeframes(frames)
                if gap_sec > 0 and i < len(wav_list) - 1:
                    nsil = int(gap_sec * params.framerate)
                    writer.writeframes(b"\x00" * (nsil * params.sampwidth * params.nchannels))
        finally:
            if writer is not None:
                writer.close()
        return out_io.getvalue()

    @staticmethod
    def _wav_bytes_duration(wav_bytes) -> float:
        """读取一段 wav 字节的时长（秒）。"""
        import io
        import wave
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            fr = w.getframerate() or 1
            return w.getnframes() / float(fr)

    @staticmethod
    def _write_timing_sidecar(wav_path, timing):
        """把句级时间轴写到 wav 同名 .timing.json（供字幕精确对轴）。"""
        import json as _json
        try:
            with open(wav_path + ".timing.json", "w", encoding="utf-8") as f:
                _json.dump(timing, f, ensure_ascii=False, indent=1)
        except Exception:
            log.warning(f"写入句级时间轴失败: {wav_path}.timing.json")

    @staticmethod
    def _scale_timing_sidecar(wav_path, factor):
        """音频整体变速后，按 factor 缩放句级时间轴（new = old * factor）。"""
        import json as _json
        p = wav_path + ".timing.json"
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                timing = _json.load(f)
            for t in timing:
                t["start"] = round(float(t.get("start", 0)) * factor, 3)
                t["end"] = round(float(t.get("end", 0)) * factor, 3)
            with open(p, "w", encoding="utf-8") as f:
                _json.dump(timing, f, ensure_ascii=False, indent=1)
        except Exception:
            log.warning(f"缩放句级时间轴失败: {p}")

    def _synthesize_item(self, text, ref_audio_b64, out_wav_path, row_idx):
        """合成一条文案为 wav 文件。

        多句文案 → 逐句合成并记录每句真实时长（写入 .timing.json，供字幕精确对轴），
        再拼接为整段；逐句失败或单句文案 → 整体合成（时间轴退化为整段一条）。
        """
        gap = 0.15
        segs = self._split_sentences(text)

        # 逐句合成：拿到每句真实起止时间，字幕不再靠字数估算
        if len(segs) >= 2:
            try:
                wavs = []
                timing = []
                cursor = 0.0
                for si, seg in enumerate(segs):
                    self.stage.emit(f"第 {row_idx + 1} 个声音逐句合成 {si + 1}/{len(segs)}...")
                    wb = self._post_tts(seg, ref_audio_b64, row_idx, label="逐句")
                    dur = self._wav_bytes_duration(wb)
                    timing.append({"text": seg, "start": round(cursor, 3), "end": round(cursor + dur, 3)})
                    cursor += dur + gap
                    wavs.append(wb)
                    time.sleep(0.2)
                combined = self._concat_wav_bytes(wavs, gap_sec=gap)
                with open(out_wav_path, "wb") as f:
                    f.write(combined)
                self._write_timing_sidecar(out_wav_path, timing)
                return
            except Exception:
                self.stage.emit(f"第 {row_idx + 1} 个声音逐句合成失败，回退整体合成...")

        # 整体合成（单句文案 / 逐句失败回退）
        merged_text = text.strip()
        if "\n" in merged_text:
            lines = [l.strip() for l in merged_text.split("\n") if l.strip()]
            merged_text = "。".join(lines) + "。"
        content = self._post_tts(merged_text, ref_audio_b64, row_idx)
        with open(out_wav_path, "wb") as f:
            f.write(content)
        try:
            total_dur = self._wav_bytes_duration(content)
            if len(segs) <= 1:
                timing = [{"text": merged_text, "start": 0.0, "end": round(total_dur, 3)}]
            else:
                # 回退场景：整段音频内按字数比例分配句时间（比无时间轴强）
                char_counts = [max(1, len(s)) for s in segs]
                total_chars = sum(char_counts)
                timing = []
                cursor = 0.0
                for s, c in zip(segs, char_counts):
                    d = total_dur * c / total_chars
                    timing.append({"text": s, "start": round(cursor, 3), "end": round(cursor + d, 3)})
                    cursor += d
            self._write_timing_sidecar(out_wav_path, timing)
        except Exception:
            pass

    def run(self):
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            voices_dir = os.path.join(self.temp_dir, "voices")
            os.makedirs(voices_dir, exist_ok=True)
            
            results = {}
            total = len(self.tasks)
            
            ref_audio_b64 = None
            if self.voice_ref_audio and os.path.exists(self.voice_ref_audio):
                with open(self.voice_ref_audio, "rb") as f:
                    ref_audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            for index, (row_idx, text, video_path, out_wav_path) in enumerate(self.tasks):
                if not text.strip():
                    continue
                
                if self.task_type == "voice":
                    self.stage.emit(f"正在克隆第 {row_idx + 1} 个声音片段 ({index + 1}/{total})...")
                else:
                    self.stage.emit(f"正在合成第 {row_idx + 1} 个视频的克隆人声 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                self.row_progress.emit(row_idx, 15)
                
                os.makedirs(os.path.dirname(out_wav_path), exist_ok=True)

                try:
                    self.row_progress.emit(row_idx, 50)

                    self._synthesize_item(text, ref_audio_b64, out_wav_path, row_idx)

                    self.row_progress.emit(row_idx, 90)

                    # Adjust audio speed to match video duration.
                    # Clamped to [speed_min, speed_max] to prevent extreme atempo distortion.
                    # If the required ratio falls outside this range, audio is left as-is and
                    # the final step (step 4) handles the remaining mismatch.
                    if os.path.exists(video_path) and video_path.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")):
                        vid_dur = get_media_duration(video_path)
                        aud_dur = get_media_duration(out_wav_path)
                        if vid_dur > 0 and aud_dur > 0 and abs(vid_dur - aud_dur) / vid_dur > 0.02:
                            speed_ratio = aud_dur / vid_dur
                            # Clamp to allowed range — beyond this the distortion is unacceptable
                            clamped = max(self.speed_min, min(self.speed_max, speed_ratio))
                            if abs(clamped - 1.0) > 0.005:
                                temp_wav = out_wav_path + ".tmp.wav"
                                ffmpeg_exe = find_ffmpeg()
                                creationflags = 0x08000000 if sys.platform == "win32" else 0
                                speed_cmd = [
                                    ffmpeg_exe, "-y", "-i", out_wav_path,
                                    "-filter:a", f"atempo={clamped:.4f}",
                                    temp_wav
                                ]
                                sr = subprocess.run(speed_cmd, capture_output=True, creationflags=creationflags)
                                if sr.returncode == 0 and os.path.exists(temp_wav):
                                    os.replace(temp_wav, out_wav_path)
                                    # 音频变速后，句级时间轴同步缩放（atempo=X → 时长×1/X）
                                    self._scale_timing_sidecar(out_wav_path, 1.0 / clamped)

                    results[video_path] = out_wav_path
                    self.row_progress.emit(row_idx, 100)
                except Exception as e:
                    # 单条失败不再中断整批：记录失败、跳过，继续合成其余视频。
                    self.row_progress.emit(row_idx, 0)
                    log.exception(f"第 {row_idx + 1} 个声音克隆失败")
                    self.failures.append((row_idx, video_path, str(e)))
                    self.stage.emit(f"⚠ 第 {row_idx + 1} 个声音克隆失败，已跳过继续...")

                # Brief pause between tasks to let server reset GPU state
                time.sleep(0.3)

            self.progress.emit(100)

            if self.failures and not results:
                # 全部失败：作为整体错误抛出，给出明确原因与处置建议
                detail = "\n".join(
                    f"· 第 {r + 1} 个：{m}" for r, _v, m in self.failures[:8])
                more = "" if len(self.failures) <= 8 else f"\n…… 等共 {len(self.failures)} 个失败"
                self.error.emit(
                    "全部声音克隆均失败。\n"
                    "常见原因：VoxCPM 服务崩溃 / 显存不足 / 文案过长。\n"
                    "建议：① 确认 VoxCPM API 服务仍在运行（可点「停止/启动服务」重启）；"
                    "② 缩短配音文案；③ 稍候重试。\n\n"
                    f"{detail}{more}")
                return

            if self.failures:
                self.stage.emit(
                    f"声音克隆完成：成功 {len(results)} 个，失败 {len(self.failures)} 个（已跳过）")
            else:
                self.stage.emit("声音克隆合成成功")
            self.finished.emit(results)

        except Exception:
            log.exception("声音克隆失败")
            self.error.emit(traceback.format_exc())


class FinalMixWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Returns a list of final video paths

    def __init__(self, tasks, bgm_path, bgm_volume):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, output_path)
        self.bgm_path = bgm_path
        self.bgm_volume = bgm_volume

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            has_bgm = bool(self.bgm_path and os.path.exists(self.bgm_path))
            bgm_vol = self.bgm_volume / 100.0
            
            results = []
            total = len(self.tasks)
            
            for index, (video_path, output_path) in enumerate(self.tasks):
                self.stage.emit(f"正在进行最终合成配乐 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                if has_bgm:
                    # Check if the input video has an audio stream
                    has_audio = False
                    try:
                        ffprobe_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "csv=p=0", video_path
                        ]
                        p_probe = subprocess.run(ffprobe_cmd, capture_output=True, text=True, creationflags=creationflags)
                        if "audio" in p_probe.stdout:
                            has_audio = True
                    except Exception:
                        has_audio = True

                    # BGM 淡入淡出：开头 1s 淡入，结尾 2s 淡出（按视频时长定位）
                    vid_dur = get_media_duration(video_path)
                    fade_out_start = max(0.0, vid_dur - 2.0)
                    bgm_fades = f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start:.3f}:d=2.0" if vid_dur > 0 else "afade=t=in:st=0:d=1.0"

                    if has_audio:
                        # 人声闪避（sidechain ducking）：BGM 在人声出现时自动压低，
                        # 人声停顿时回升；最终 loudnorm 统一响度（EBU R128 -16 LUFS）。
                        filter_complex = (
                            f"[0:a]asplit=2[vo][sc];"
                            f"[1:a]volume={bgm_vol},{bgm_fades}[bg];"
                            f"[bg][sc]sidechaincompress=threshold=0.05:ratio=8:attack=50:release=400[duck];"
                            f"[vo][duck]amix=inputs=2:duration=first:normalize=0,"
                            f"loudnorm=I=-16:TP=-1.5:LRA=11[a]"
                        )
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", filter_complex,
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                    else:
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", f"[1:a]volume={bgm_vol},{bgm_fades},loudnorm=I=-16:TP=-1.5:LRA=11[bgm]",
                            "-map", "0:v", "-map", "[bgm]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-c", "copy",
                        output_path
                    ]
                
                r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
                if r.returncode != 0:
                    raise RuntimeError(f"最后合成视频失败：\n{r.stderr}")
                    
                results.append(output_path)
                
            self.stage.emit("所有视频及配乐最终合成完成！")
            self.progress.emit(100)
            self.finished.emit(results)
            
        except Exception:
            log.exception("最终合成失败")
            self.error.emit(traceback.format_exc())


class VideoDubbingWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(dict)  # Outputs a dict mapping: original_video_path -> dubbed_video_path

    def __init__(self, tasks, add_subtitles=True, length_modes=None,
                 fancy_text=False, fancy_style="gold", fancy_words=None):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, voice_wav_path, output_video_path, text)
        self.add_subtitles = add_subtitles
        self.length_modes = length_modes or {}  # video_path -> "video" or "audio"
        self.fancy_text = fancy_text
        self.fancy_style = fancy_style
        self.fancy_words = fancy_words or []  # list of strings to overlay

    @staticmethod
    def _load_timing_sidecar(voice_wav_path):
        """读取逐句 TTS 生成的句级时间轴（.timing.json）；无效则返回 None。"""
        import json as _json
        p = (voice_wav_path or "") + ".timing.json"
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                timing = _json.load(f)
            if (isinstance(timing, list) and timing
                    and all(isinstance(t, dict) and t.get("text") for t in timing)):
                return timing
        except Exception:
            pass
        return None

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            results = {}
            total = len(self.tasks)
            
            for index, (video_path, voice_wav_path, output_video_path, text) in enumerate(self.tasks):
                self.stage.emit(f"正在进行视频原声替换配音 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                
                os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

                length_mode = self.length_modes.get(video_path, "video")
                video_dur = get_media_duration(video_path)
                audio_dur = get_media_duration(voice_wav_path)
                use_audio_length = (length_mode == "audio" and audio_dur > video_dur > 0)
                extra_dur = audio_dur - video_dur if use_audio_length else 0.0
                display_dur = audio_dur if use_audio_length else video_dur

                # Build video filter chain
                video_filters = []
                video_label = "0:v"
                audio_label = "1:a:0"
                need_audio_speed = (not use_audio_length and audio_dur > video_dur > 0)

                if use_audio_length:
                    # Extend video with last frame clone to match audio length
                    video_filters.append(f"[{video_label}]tpad=stop_mode=clone:stop_duration={extra_dur:.3f}[v_padded]")
                    video_label = "v_padded"

                if self.add_subtitles and text:
                    # Resolve Microsoft YaHei font path on Windows
                    font_path = "C\\:/Windows/Fonts/msyh.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
                        font_path = "msyh"

                    # 优先使用逐句 TTS 的真实句级时间轴（字幕与语音精确同步）
                    timing = self._load_timing_sidecar(voice_wav_path)
                    if timing:
                        raw_lines = [str(t["text"]).strip() for t in timing]
                        line_starts = [float(t.get("start", 0)) for t in timing]
                        line_ends = [float(t.get("end", 0)) for t in timing]
                        # 本步骤内音频被 atempo 加速对齐视频时 → 时间轴按同比例缩放
                        if need_audio_speed and audio_dur > 0:
                            f_scale = video_dur / audio_dur
                            line_starts = [s * f_scale for s in line_starts]
                            line_ends = [e * f_scale for e in line_ends]
                        if display_dur > 0:
                            line_ends = [min(e, display_dur) for e in line_ends]
                    else:
                        # 回退：无时间轴时按字数比例估算（旧行为）
                        raw_lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                        if not raw_lines:
                            raw_lines = [text.strip()]
                        char_counts = [max(1, len(line)) for line in raw_lines]
                        total_chars = sum(char_counts)
                        cum_t = 0.0
                        line_starts, line_ends = [], []
                        for c in char_counts:
                            t0 = cum_t
                            t1 = cum_t + (display_dur * c / total_chars if display_dur > 0 else 5.0)
                            line_starts.append(t0)
                            line_ends.append(t1)
                            cum_t = t1

                    # Build drawtext filters
                    drawtexts = []
                    for i, line_text in enumerate(raw_lines):
                        start_t = line_starts[i]
                        end_t = line_ends[i]
                        escaped = line_text.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')
                        dt = (
                            f"drawtext=fontfile='{font_path}':"
                            f"text='{escaped}':"
                            f"fontsize=h*0.025:fontcolor=white:"
                            f"box=1:boxcolor=black@0.5:boxborderw=6:"
                            f"x=(w-text_w)/2:y=h-text_h-h*0.06:"
                            f"enable='between(t,{start_t:.3f},{end_t:.3f})'"
                        )
                        drawtexts.append(dt)
                    video_filters.append(f"[{video_label}]{','.join(drawtexts)}[v]")
                    video_label = "v"

                # 花字叠加（关键信息加重提醒，大号彩色描边特效文字）
                if self.fancy_text and self.fancy_words and display_dur > 0:
                    font_path = "C\\:/Windows/Fonts/msyhbd.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
                        font_path = "C\\:/Windows/Fonts/msyh.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
                        font_path = "msyh"

                    # 花字样式预设：fontcolor + borderw + bordercolor + shadow
                    fancy_styles = {
                        "gold":          "fontcolor=0xF0C040:borderw=4:bordercolor=0x6B3000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "red":           "fontcolor=0xFF4040:borderw=4:bordercolor=0x800000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "blue":          "fontcolor=0x40A0FF:borderw=4:bordercolor=0x003080:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "purple":        "fontcolor=0xC060FF:borderw=4:bordercolor=0x300060:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "neon_green":    "fontcolor=0x40FF80:borderw=3:bordercolor=0x004020:shadowx=3:shadowy=3:shadowcolor=0x00FF80@0.5",
                        "white_outline": "fontcolor=white:borderw=5:bordercolor=black:shadowx=2:shadowy=2:shadowcolor=0x000000@0.6",
                        "yellow_red":    "fontcolor=0xFFFF00:borderw=5:bordercolor=0xCC0000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                    }
                    style_str = fancy_styles.get(self.fancy_style, fancy_styles["gold"])

                    fancy_drawtexts = []
                    # 每个花字在整个视频时长内均匀分布轮换显示
                    n_words = len(self.fancy_words)
                    if n_words > 0:
                        seg_dur = display_dur / n_words
                        for wi, word in enumerate(self.fancy_words):
                            word = word.strip()
                            if not word:
                                continue
                            ft_start = wi * seg_dur
                            ft_end = min((wi + 1) * seg_dur, display_dur)
                            escaped = word.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')
                            # 花字：大号字体，居中偏上，带描边和阴影
                            dt = (
                                f"drawtext=fontfile='{font_path}':"
                                f"text='{escaped}':"
                                f"fontsize=h*0.08:{style_str}:"
                                f"x=(w-text_w)/2:y=h*0.3:"
                                f"enable='between(t,{ft_start:.3f},{ft_end:.3f})'"
                            )
                            fancy_drawtexts.append(dt)
                    if fancy_drawtexts:
                        video_filters.append(f"[{video_label}]{','.join(fancy_drawtexts)}[vf]")
                        video_label = "vf"

                if need_audio_speed:
                    # Speed up audio to match video duration using atempo chain
                    ratio = audio_dur / video_dur
                    atempo_parts = []
                    remaining = ratio
                    while remaining > 2.0:
                        atempo_parts.append("atempo=2.0")
                        remaining /= 2.0
                    if remaining < 0.5:
                        atempo_parts.append(f"atempo=0.5")
                        remaining /= 0.5
                    if abs(remaining - 1.0) > 0.001:
                        atempo_parts.append(f"atempo={remaining:.4f}")
                    if atempo_parts:
                        if video_filters:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")
                            audio_label = "a"
                        else:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")
                            audio_label = "a"
                            # Need a dummy video pass-through so filter_complex can map both
                            video_filters.insert(0, f"[{video_label}]null[v]")
                            video_label = "v"

                if video_filters:
                    filter_complex = ";".join(video_filters)
                    audio_map = f"[{audio_label}]" if audio_label == "a" else audio_label
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                        "-filter_complex", filter_complex,
                        "-map", f"[{video_label}]", "-map", audio_map,
                        "-c:v", "libx264", "-preset", "superfast", "-c:a", "aac",
                    ]
                    # "以声音为准"时严格裁剪输出到音频时长：
                    #   audio > video → tpad 已把视频延长到 audio_dur，-t 再确认一次（无害）
                    #   audio < video → tpad 未触发，必须靠 -t 裁掉多余的视频
                    if length_mode == "audio" and audio_dur > 0:
                        cmd += ["-t", f"{audio_dur:.3f}"]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                    ]
                cmd.append(output_video_path)
                
                r = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if r.returncode != 0:
                    err = r.stderr or r.stdout or "(无输出)"
                    raise RuntimeError(f"视频原声替换配音失败：\n{err}\n命令: {' '.join(cmd)}")
                    
                results[video_path] = output_video_path
                
            self.stage.emit("所有视频替换配音完成！")
            self.progress.emit(100)
            self.finished.emit(results)
            
        except Exception:
            log.exception("视频替换配音失败")
            self.error.emit(traceback.format_exc())


def format_seconds_to_srt_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds >= 1000:
        milliseconds -= 1000
        secs += 1
        if secs >= 60:
            secs -= 60
            minutes += 1
            if minutes >= 60:
                minutes -= 60
                hours += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def parse_srt_to_descriptions(srt_content):
    import re
    content = srt_content.replace("\r\n", "\n").strip()
    blocks = re.split(r'\n\s*\n', content)
    texts = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) >= 3:
            time_idx = -1
            for idx, line_str in enumerate(lines):
                if "-->" in line_str:
                    time_idx = idx
                    break
            if time_idx != -1 and time_idx + 1 < len(lines):
                text = " ".join(lines[time_idx + 1:])
                texts.append(text)
    return texts


from gui.base_page import BasePage


class ReorderableClipsTable(QTableWidget):
    """镜头片段表格：左列为拖拽把手，支持拖动调序，右键删除/恢复。"""
    order_changed = Signal(int, int)  # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self._drag_start_row = -1

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and item.column() == 0:
                self._drag_start_row = item.row()
            else:
                self._drag_start_row = -1

    def mouseMoveEvent(self, event):
        if self._drag_start_row >= 0 and (event.buttons() & Qt.LeftButton):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(str(self._drag_start_row))
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)
            self._drag_start_row = -1
        else:
            super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.source() == self:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.source() == self:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() == self:
            target_row = self.rowAt(event.pos().y())
            if target_row < 0:
                target_row = self.rowCount() - 1
            source_row = self._drag_start_row
            self._drag_start_row = -1
            if source_row >= 0 and target_row >= 0 and target_row != source_row:
                self.order_changed.emit(source_row, target_row)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class VideoMontagePage(BasePage):
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
        
        # Fish Speech background server process
        self.api_server_process = None
        self.api_server_log_file = None
        self.api_server_log_path = ""
        self.api_status_timer = None

        # BGM Player dedicated setup
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        self._bgm_player = QMediaPlayer()
        self._bgm_audio_output = QAudioOutput()
        self._bgm_player.setAudioOutput(self._bgm_audio_output)

        # Preview Player dedicated setup
        self.preview_player = QMediaPlayer()
        self.preview_audio_output = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_audio_output)

        # Split clips metadata cache
        self.split_clips_cache = {}

        # Step 2 precompose state
        self.precompose_plans = []
        self.current_precompose_index = -1
        self._confirming_plan_index = None
        self._confirm_queue = []
        self._preview_sequence_clips = []
        self._preview_sequence_idx = 0

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

        # Build Wizard Pages
        self._setup_page_split()     # Index 0
        self._setup_page_concat()    # Index 1
        self._setup_page_voice()     # Index 2
        self._setup_page_final()     # Index 3

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

    def update_step_indicator(self, index):
        for i, lbl in enumerate(self.step_labels):
            if i == index:
                lbl.setProperty("active", True)
            else:
                lbl.setProperty("active", False)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _go_to_step(self, index):
        # Stop background music playback if leaving Step 4 (index 3)
        if hasattr(self, "_bgm_player") and self._bgm_player:
            self._stop_bgm_play()

        # 离开声音克隆步骤（step 2）进入下一步时，停止 VoxCPM 服务释放显存
        if self.stacked_widget.currentIndex() == 2 and index != 2:
            self._stop_voxcpm_after_voice()

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

    def _on_enter_step_3(self):
        dir_path = ""
        confirmed_paths = self._collect_assembled_paths() if hasattr(self, "_collect_assembled_paths") else []
        if confirmed_paths:
            dir_path = os.path.dirname(confirmed_paths[0])
        
        if not dir_path:
            src_dir = self.folder_path_input.text().strip()
            if src_dir:
                dir_path = self._get_out_montage_dir(src_dir)
        
        if dir_path and os.path.exists(dir_path):
            self.voice_video_dir_input.blockSignals(True)
            self.voice_video_dir_input.setText(dir_path)
            self.voice_video_dir_input.blockSignals(False)
        
        self._scan_voice_video_dir()

        # Sync VoxCPM configured port and model path from config.ini
        import configparser
        port = 7861
        try:
            config = configparser.ConfigParser()
            config.read('config.ini', encoding='utf-8')
            if config.has_section('VoxCPM'):
                port = config.getint('VoxCPM', 'Port', fallback=7861)
        except Exception:
            pass

        self.api_url_input.setText(f"http://127.0.0.1:{port}/v1/tts")
        self._populate_models()

        # Check if API server is already running externally and monitor it
        api_url = self.api_url_input.text().strip()
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(api_url)
            host = parsed.hostname or "127.0.0.1"
            port_to_check = parsed.port or 8000
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect((host, port_to_check))
            s.close()
            
            # Port is listening! Set status and start the timer monitor.
            self.server_status_lbl.setText("服务状态: 正在运行 (检测到外部进程)")
            self.server_status_lbl.setStyleSheet("color: #2ecc71;")
            self.btn_toggle_server.setText("⏹️ 停止本地 API 服务")
            if not hasattr(self, "api_status_timer") or not self.api_status_timer:
                from PySide6.QtCore import QTimer
                self.api_status_timer = QTimer()
                self.api_status_timer.timeout.connect(self._check_api_server_status)
            self.api_status_timer.start(3000)
        except Exception:
            pass
        self._populate_ref_audio_samples()

    # ==================== PAGE 0: SMART SPLIT ====================
    def _setup_page_split(self):
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
            self.btn_install_deps = QPushButton("🔧 安装智能分割依赖")
            self.btn_install_deps.setObjectName("secondary_button")
            self.btn_install_deps.clicked.connect(self._install_scenedetect)
            dep_layout.addWidget(self.btn_install_deps)
            
        split_row.addWidget(self.dep_status_widget)

        # 仅保留批量分割入口（单条智能分割按钮隐藏，仅用于兼容旧逻辑）
        self.btn_split = QPushButton("✂️ 开始智能镜头分割")
        self.btn_split.setObjectName("action_button")
        self.btn_split.setFixedHeight(35)
        self.btn_split.clicked.connect(self._start_split)
        self.btn_split.setVisible(False)

        self.btn_split_all = QPushButton("📚 批量分割镜头")
        self.btn_split_all.setObjectName("action_button")
        self.btn_split_all.setFixedHeight(35)
        self.btn_split_all.setToolTip("对列表中所有视频依次进行镜头分割（不自动转写/描述）")
        self.btn_split_all.clicked.connect(self._start_split_all)
        split_row.addWidget(self.btn_split_all)

        split_row.addSpacing(12)
        split_row.addWidget(QLabel("精华时长:"))
        self.spin_highlight_sec = QDoubleSpinBox()
        self.spin_highlight_sec.setRange(1.0, 30.0)
        self.spin_highlight_sec.setValue(5.0)
        self.spin_highlight_sec.setSingleStep(1.0)
        self.spin_highlight_sec.setSuffix(" 秒")
        self.spin_highlight_sec.setFixedWidth(80)
        self.spin_highlight_sec.setToolTip("从每个视频里挑出多长的精华片段")
        split_row.addWidget(self.spin_highlight_sec)

        self.btn_pick_highlights = QPushButton("🌟 批量选精华")
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
        self.split_result_table.setColumnCount(4)
        self.split_result_table.setHorizontalHeaderLabels(["序号", "视频片段", "时间戳", "画面文案描述"])
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
        header.setStretchLastSection(False)
        
        card_layout.addWidget(self.split_result_table)



        layout.addWidget(card, 1)

        # Navigation row (Open split clips directory button moved here!)
        nav_row = QHBoxLayout()
        self.btn_open_splits_dir = QPushButton("📂 打开已分割镜头目录")
        self.btn_open_splits_dir.setObjectName("secondary_button")
        self.btn_open_splits_dir.clicked.connect(self._open_splits_dir)
        nav_row.addWidget(self.btn_open_splits_dir)
        
        nav_row.addStretch()
        self.btn_next_to_step_2 = QPushButton("下一步：镜头重组 ➔")
        self.btn_next_to_step_2.setObjectName("primary_button")
        self.btn_next_to_step_2.setEnabled(True)
        self.btn_next_to_step_2.clicked.connect(lambda: self._go_to_step(1))
        nav_row.addWidget(self.btn_next_to_step_2)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)

    # ==================== PAGE 1: CLIP ASSEMBLY ====================
    def _setup_page_concat(self):
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
        self.concat_clips_list_widget.setColumnCount(5)
        self.concat_clips_list_widget.setHorizontalHeaderLabels(["分割文件名", "时间戳", "描述文案", "文件目录", "操作"])
        self.concat_clips_list_widget.setFixedHeight(180)
        self.concat_clips_list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.concat_clips_list_widget.itemDoubleClicked.connect(self._preview_concat_table_item)
        self.concat_clips_list_widget.cellChanged.connect(self._on_concat_table_cell_changed)
        
        header = self.concat_clips_list_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)       # 分割文件名
        self.concat_clips_list_widget.setColumnWidth(0, 160)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 时间戳
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # 描述文案
        header.setSectionResizeMode(3, QHeaderView.Interactive)       # 文件目录
        self.concat_clips_list_widget.setColumnWidth(3, 120)
        header.setSectionResizeMode(4, QHeaderView.Fixed)             # 操作
        self.concat_clips_list_widget.setColumnWidth(4, 30)
        
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

        row_params2.addStretch()

        self.btn_assemble_video = QPushButton("🎬 镜头重组")
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
        self.sources_detail_widget.setColumnCount(4)
        self.sources_detail_widget.setHorizontalHeaderLabels(["⠿", "分割文件名", "时间戳", "描述文案"])
        self.sources_detail_widget.setFixedHeight(220)
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
        self.btn_preview_play = QPushButton("▶")
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
        btn_prev = QPushButton("⇠ 上一步：镜头分割")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(0))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.btn_next_to_step_3 = QPushButton("下一步：克隆口播 ➔")
        self.btn_next_to_step_3.setObjectName("primary_button")
        self.btn_next_to_step_3.setEnabled(True)
        self.btn_next_to_step_3.clicked.connect(lambda: self._go_to_step(2))
        nav_row.addWidget(self.btn_next_to_step_3)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)
        self._on_logic_combo_changed()

    def _setup_page_voice(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

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

        # Define advanced elements in background
        self.voice_mode_combo = QComboBox()
        self.voice_mode_combo.addItem("API 接口服务调用", "api")
        self.voice_mode_combo.addItem("本地命令行直接调用 (Local CLI)", "cli")
        self.voice_mode_combo.currentIndexChanged.connect(self._on_voice_mode_changed)

        self.api_url_input = QLineEdit()
        self.api_url_input.setText("http://127.0.0.1:8000/v1/tts")

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

        self.btn_play_ref = QPushButton("🔊")
        self.btn_play_ref.setToolTip("播放人声样本")
        self.btn_play_ref.setStyleSheet("padding: 0px; font-size: 14px;")
        self.btn_play_ref.setFixedWidth(30)
        self.btn_play_ref.setFixedHeight(30)
        self.btn_play_ref.setEnabled(False)
        self.btn_play_ref.clicked.connect(self._play_ref_audio)
        row_voice.addWidget(self.btn_play_ref)

        self.btn_upload_ref = QPushButton("📂 上传声音")
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
        
        # 3. Model selection and Server control group row
        row_server = QHBoxLayout()
        row_server.setSpacing(10)
        row_server.setAlignment(Qt.AlignVCenter)
        
        row_server.addWidget(QLabel("🤖 模型:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(160)
        row_server.addWidget(self.model_combo)
        self.model_combo.currentIndexChanged.connect(self._on_model_selected)
        
        row_server.addSpacing(10)
        row_server.addWidget(QLabel("服务控制:"))
        self.btn_toggle_server = QPushButton("▶️ 启动服务")
        self.btn_toggle_server.setObjectName("primary_button")
        self.btn_toggle_server.setStyleSheet("padding: 4px 10px; font-size: 12px; font-weight: bold;")
        self.btn_toggle_server.clicked.connect(self._toggle_api_server)
        row_server.addWidget(self.btn_toggle_server)
        
        self.server_status_lbl = QLabel("已停止")
        self.server_status_lbl.setObjectName("muted_text")
        self.server_status_lbl.setStyleSheet("color: #e74c3c; font-size: 12px; font-weight: bold; margin-left: 5px; margin-right: 5px;")
        row_server.addWidget(self.server_status_lbl)
        
        self.btn_view_server_log = QPushButton("📄")
        self.btn_view_server_log.setToolTip("查看日志")
        self.btn_view_server_log.setStyleSheet("padding: 0px; font-size: 12px;")
        self.btn_view_server_log.setFixedWidth(30)
        self.btn_view_server_log.setFixedHeight(30)
        self.btn_view_server_log.clicked.connect(self._view_server_log)
        row_server.addWidget(self.btn_view_server_log)
        
        # Advanced settings button
        self.btn_advanced_settings = QPushButton("⚙️")
        self.btn_advanced_settings.setToolTip("高级配置 (调用方式、接口地址)")
        self.btn_advanced_settings.setStyleSheet("padding: 0px; font-size: 12px;")
        self.btn_advanced_settings.setFixedWidth(30)
        self.btn_advanced_settings.setFixedHeight(30)
        self.btn_advanced_settings.clicked.connect(self._show_advanced_voxcpm_dialog)
        row_server.addWidget(self.btn_advanced_settings)
        
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

        self.voice_mode_combo.currentIndexChanged.connect(self._on_voice_mode_changed)

        # 5. Videos and script mappings table (batch text area removed)
        row_table_title = QHBoxLayout()
        row_table_title.setContentsMargins(0, 4, 0, 4)
        lbl_title = QLabel("📹 待合成视频列表与配音文案映射 (在配音文案栏直接输入):")
        lbl_title.setObjectName("card_title")
        row_table_title.addWidget(lbl_title)
        row_table_title.addStretch()

        self.btn_ai_rewrite_settings = QPushButton("⚙️ 文案生成设置")
        self.btn_ai_rewrite_settings.setObjectName("secondary_button")
        self.btn_ai_rewrite_settings.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        self.btn_ai_rewrite_settings.clicked.connect(self._show_ai_rewrite_settings)
        row_table_title.addWidget(self.btn_ai_rewrite_settings)

        self.btn_batch_ai_rewrite = QPushButton("✨ 一键AI修改全部文案")
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
        card_layout.addWidget(self.voice_table)

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
        self.btn_synthesize_voice = QPushButton("🗣️ 开始批量克隆人声合成")
        self.btn_synthesize_voice.setObjectName("action_button")
        self.btn_synthesize_voice.setFixedHeight(35)
        self.btn_synthesize_voice.clicked.connect(self._start_synthesize_voice)
        row_actions.addWidget(self.btn_synthesize_voice, 2)

        self.btn_dub_videos = QPushButton("🎬 开始给视频配音 (替换原声)")
        self.btn_dub_videos.setObjectName("primary_button")
        self.btn_dub_videos.setFixedHeight(35)
        self.btn_dub_videos.clicked.connect(self._start_dubbing_videos)
        self.btn_dub_videos.setEnabled(False)
        row_actions.addWidget(self.btn_dub_videos, 3)
        card_layout.addLayout(row_actions)

        layout.addWidget(card, 1)

        # Scan models directory
        self._populate_models()

        # Navigation row
        nav_row = QHBoxLayout()
        btn_prev = QPushButton("⇠ 上一步：镜头重组")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(1))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()

        self.btn_next_to_step_4 = QPushButton("下一步：特效包装 ➔")
        self.btn_next_to_step_4.setObjectName("primary_button")
        self.btn_next_to_step_4.setEnabled(True)
        self.btn_next_to_step_4.clicked.connect(lambda: self._go_to_step(3))
        nav_row.addWidget(self.btn_next_to_step_4)
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)

    def _populate_models(self):
        self.model_combo.clear()
        
        # Load custom model path from config.ini
        import configparser
        custom_model_path = ""
        try:
            config = configparser.ConfigParser()
            config.read('config.ini', encoding='utf-8')
            if config.has_section('VoxCPM'):
                custom_model_path = config.get('VoxCPM', 'ModelPath', fallback="").strip()
        except Exception:
            pass

        if not custom_model_path or not os.path.isdir(custom_model_path):
            default_path = os.path.join(VOXCPM2_DIR, "models", "openbmb__VoxCPM2")
            if os.path.isdir(default_path):
                custom_model_path = os.path.abspath(default_path)

        modules_dir = os.path.abspath(os.path.join(WORKSPACE_ROOT, "modules"))
        found_folders = []
        
        # Add configured custom model path first if it exists
        if custom_model_path and os.path.isdir(custom_model_path):
            basename = os.path.basename(custom_model_path) or custom_model_path
            self.model_combo.addItem(f"⚙️ 配置模型: {basename}", custom_model_path)

        # Add default HuggingFace model
        self.model_combo.addItem("🌐 默认模型: openbmb/VoxCPM2 (HuggingFace)", "openbmb/VoxCPM2")

        if os.path.exists(modules_dir):
            for d in os.listdir(modules_dir):
                if os.path.isdir(os.path.join(modules_dir, d)):
                    full_p = os.path.join(modules_dir, d)
                    # Avoid duplicate if it matches custom_model_path
                    if custom_model_path and os.path.abspath(full_p) == os.path.abspath(custom_model_path):
                        continue
                    if "voxcpm" in d.lower():
                        found_folders.append(d)
                        self.model_combo.addItem(f"📁 {d}", full_p)
        
        self.model_combo.addItem("浏览其他模型文件夹...", "custom")
        
        # If we added custom_model_path, select it (index 0)
        if custom_model_path and os.path.isdir(custom_model_path):
            self.model_combo.setCurrentIndex(0)
        else:
            if found_folders:
                offset = 1 if (custom_model_path and os.path.isdir(custom_model_path)) else 0
                self.model_combo.setCurrentIndex(offset + 1)
            else:
                offset = 1 if (custom_model_path and os.path.isdir(custom_model_path)) else 0
                self.model_combo.setCurrentIndex(offset)

    def _on_model_selected(self, index):
        data = self.model_combo.currentData()
        if data == "custom":
            dir_path = QFileDialog.getExistingDirectory(self.parent_widget, "选择权重文件夹", "")
            if dir_path:
                name = os.path.basename(dir_path) or dir_path
                self.model_combo.insertItem(0, f"📌 {name}", dir_path)
                self.model_combo.setCurrentIndex(0)
            else:
                if self.model_combo.count() > 1:
                    self.model_combo.setCurrentIndex(0)

    # ==================== PAGE 3: FINAL MIX ====================
    def _setup_page_final(self):
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
        
        btn_add_mix_vid = QPushButton("➕ 选择添加视频")
        btn_add_mix_vid.setObjectName("secondary_button")
        btn_add_mix_vid.setFixedHeight(28)
        btn_add_mix_vid.clicked.connect(self._add_mix_videos)
        row_select_video.addWidget(btn_add_mix_vid)
        
        btn_clear_mix_vid = QPushButton("🗑️ 清空列表")
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
        
        self.btn_bgm_play = QPushButton("▶️ 播放")
        self.btn_bgm_play.setObjectName("secondary_button")
        self.btn_bgm_play.setFixedWidth(80)
        self.btn_bgm_play.setFixedHeight(32)
        self.btn_bgm_play.clicked.connect(self._toggle_bgm_play)
        row_bgm_play.addWidget(self.btn_bgm_play)
        
        self.btn_bgm_stop = QPushButton("⏹️ 停止")
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
        self.btn_final_assemble = QPushButton("🎉 开始智能音视配乐一键合成")
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

        self.btn_open_final_dir = QPushButton("📂 打开视频输出目录")
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
        btn_prev = QPushButton("⇠ 上一步：克隆人声")
        btn_prev.setObjectName("secondary_button")
        btn_prev.clicked.connect(lambda: self._go_to_step(2))
        nav_row.addWidget(btn_prev)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        self.stacked_widget.addWidget(page)


    # ==================== STEP HELPER ACTIONS ====================
    def _decorate_video_item_widget(self, item):
        path = item.text().strip()
        if not path:
            return

    def _show_video_context_menu(self, pos):
        item = self.video_list.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        act = QAction("🗑 从素材列表移除", menu)
        act.triggered.connect(lambda: self._remove_source_video_item(item))
        menu.addAction(act)
        menu.exec_(self.video_list.viewport().mapToGlobal(pos))

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

    def _kill_running_workers(self):
        """终止所有可能正在后台运行的 worker（镜头分割 / 批量分割 / 挑精华）。"""
        for attr in ("worker", "batch_worker", "highlight_worker"):
            w = getattr(self, attr, None)
            if w and w.isRunning():
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(w.pid)],
                                       capture_output=True, timeout=5)
                    else:
                        w.terminate()
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
        for btn_attr in ("btn_split", "btn_split_all", "btn_pick_highlights", "btn_transcribe_raw"):
            btn = getattr(self, btn_attr, None)
            if btn:
                btn.setEnabled(True)
        self.progress_bar.setVisible(False)

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

    def _scan_folder(self):
        # 兼容旧调用：当前版本不再扫描目录，只基于用户选择的素材列表。
        for i in range(self.video_list.count()):
            it = self.video_list.item(i)
            if it:
                self._decorate_video_item_widget(it)
        self._refresh_source_root_hint()
        self._check_split_clips_exist()

    def _get_split_scenes_times(self, splits_dir, files):
        if hasattr(self, "temp_scenes") and self.temp_scenes and len(self.temp_scenes) == len(files):
            return self.temp_scenes
        
        import cv2
        scenes = []
        current_time = 0.0
        for f in files:
            p = os.path.join(splits_dir, f)
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
                splits_dir = os.path.join(dir_path, "splits")

            # Read files in splits
            files = []
            if os.path.exists(splits_dir):
                files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
            log.info(f"[DIAG _check_split_clips_exist] splits_dir='{splits_dir}' exists={os.path.exists(splits_dir)} files_count={len(files)}")
            
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
                    p = os.path.join(splits_dir, f)
                    norm_path = os.path.abspath(p)
                    self.split_clips_list.append(norm_path)
                    
                    parsed = self._parse_split_filename(f)
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
                        
                    # Col 0: Index (1-based)
                    idx_item = QTableWidgetItem(str(idx + 1))
                    idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable) # Read-only
                    idx_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 0, idx_item)
                    
                    # Col 1: Filename
                    file_item = QTableWidgetItem(f)
                    file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable) # Read-only
                    file_item.setData(Qt.UserRole, norm_path) # Save full path in UserRole
                    file_item.setToolTip(norm_path)
                    self.split_result_table.setItem(idx, 1, file_item)
                    
                    # Col 2: Timestamp
                    time_item = QTableWidgetItem(time_str)
                    time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable) # Read-only
                    time_item.setTextAlignment(Qt.AlignCenter)
                    self.split_result_table.setItem(idx, 2, time_item)
                    
                    # Col 3: Scene Description
                    desc_item = QTableWidgetItem(desc)
                    # Keep description editable
                    desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
                    self.split_result_table.setItem(idx, 3, desc_item)
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

        # Set default directory for Step 2 and scan it
        if splits_dir and os.path.exists(splits_dir):
            self.concat_src_dir_input.setText(splits_dir)
            self._scan_concat_src_dir()
        else:
            self.concat_clips_list_widget.clearContents()
            self.concat_clips_list_widget.setRowCount(0)
            self.clip_count_info_lbl.setText("待排列镜头个数: 0  (已勾选: 0)")
            self.btn_assemble_video.setEnabled(False)

        self.btn_next_to_step_2.setEnabled(True)

    def _select_bgm(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择背景配乐",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac);;All Files (*)",
        )
        if path:
            self.bgm_input.setText(path)

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

    def _play_ref_audio(self):
        path = self.ref_audio_combo.currentData()
        if path and os.path.exists(path):
            self._play_video(path)

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

    def _select_voice_video_dir(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
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

    def _on_voice_video_dir_changed(self):
        self._scan_voice_video_dir()

    def _scan_voice_video_dir(self):
        if getattr(self, "_scanning_voice_dir", False):
            return
        self._scanning_voice_dir = True
        try:
            self._do_scan_voice_video_dir()
        finally:
            self._scanning_voice_dir = False

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
        if hasattr(self, "selected_voice_video_files") and self.selected_voice_video_files:
            first_parent = os.path.abspath(os.path.dirname(self.selected_voice_video_files[0]))
            current_dir = os.path.abspath(dir_path)
            if first_parent == current_dir:
                files = [os.path.abspath(f) for f in self.selected_voice_video_files]

        if not files:
            try:
                for f in os.listdir(dir_path):
                    if f.lower().endswith(exts):
                        files.append(os.path.join(dir_path, f))
            except Exception as e:
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

            btn_play = QPushButton("🔊")
            btn_play.setToolTip("播放克隆的声音")
            btn_play.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_play.setFixedWidth(28)
            btn_play.setFixedHeight(22)
            btn_play.setEnabled(bool(wav_path and os.path.exists(wav_path)))
            btn_play.clicked.connect(lambda checked=False, path=filepath: self._on_btn_play_clicked(path))
            action_widgets.append(btn_play)

            btn_export = QPushButton("💾")
            btn_export.setToolTip("导出该克隆声音")
            btn_export.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_export.setFixedWidth(28)
            btn_export.setFixedHeight(22)
            btn_export.setEnabled(bool(wav_path and os.path.exists(wav_path)))
            btn_export.clicked.connect(lambda checked=False, path=filepath: self._on_btn_export_clicked(path))
            action_widgets.append(btn_export)

            btn_compare = QPushButton("⚖️")
            btn_compare.setToolTip("对比与编辑文案")
            btn_compare.setStyleSheet("padding: 0px; font-size: 12px;")
            btn_compare.setFixedWidth(28)
            btn_compare.setFixedHeight(22)
            btn_compare.clicked.connect(lambda checked=False, idx=i: self._on_btn_compare_clicked(idx))
            action_widgets.append(btn_compare)

            btn_regen = QPushButton("🔄")
            btn_regen.setToolTip("仅重新生成该声音")
            btn_regen.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_regen.setFixedWidth(28)
            btn_regen.setFixedHeight(22)
            btn_regen.clicked.connect(lambda checked=False, path=filepath: self._on_btn_regen_clicked(path))
            action_widgets.append(btn_regen)

            # Length mode toggle button (video-based vs audio-based)
            current_mode = self.voice_length_mode.get(filepath, "video")
            btn_length_mode = QPushButton("🎬" if current_mode == "video" else "🎙")
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
                    btn.setText("🎙" if new_mode == "audio" else "🎬")
                    btn.setToolTip(
                        "以音频长度为准，视频不够用最后一帧补足（点击切回）" if new_mode == "audio"
                        else "以视频长度为准（点击切换为以音频长度为准）"
                    )
                return toggle

            btn_length_mode.clicked.connect(make_toggle())
            action_widgets.append(btn_length_mode)

            # Play original video button (next to filename in top row)
            btn_play_original = QPushButton("▶")
            btn_play_original.setToolTip("播放原视频")
            btn_play_original.setStyleSheet("padding: 0px; font-size: 10px;")
            btn_play_original.setFixedWidth(24)
            btn_play_original.setFixedHeight(20)
            btn_play_original.clicked.connect(lambda checked=False, path=filepath: self._play_video(path))

            # Play dubbed video button (last action button)
            dubbed_path = self.dubbed_video_paths.get(filepath, "")
            has_dubbed = bool(dubbed_path and os.path.exists(dubbed_path))
            btn_play_dubbed = QPushButton("📽")
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

    def _on_edit_double_clicked(self, row_idx):
        edit = self.row_edits.get(row_idx)
        if edit:
            dialog = TextEditDialog(f"编辑第 {row_idx + 1} 行配音文案", edit.text(), self.parent_widget)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                edit.setText(new_text)

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

    def _on_btn_play_clicked(self, video_path):
        wav_path = self.generated_voice_paths.get(video_path, "")
        if wav_path and os.path.exists(wav_path):
            self._play_audio(wav_path)

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

    def _play_audio(self, wav_path):
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtCore import QUrl
            
            if not hasattr(self, "_media_player") or not self._media_player:
                self._media_player = QMediaPlayer()
                self._audio_output = QAudioOutput()
                self._media_player.setAudioOutput(self._audio_output)
            
            if self._media_player.playbackState() == QMediaPlayer.PlayingState:
                self._media_player.stop()
                if self._media_player.source().toLocalFile() == os.path.abspath(wav_path):
                    return
            
            self._media_player.setSource(QUrl.fromLocalFile(wav_path))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception as e:
            log.error(f"播放音频失败: {e}")

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

        model_path = self.model_combo.currentData()
        if model_path == "custom":
            model_path = ""

        out_wav_path = os.path.abspath(os.path.join(out_montage_dir, "voices", f"voice_{row_idx + 1}.wav"))
        tasks = [(row_idx, text, video_path, out_wav_path)]
        
        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.text().strip(),
            voice_mode=self.voice_mode_combo.currentData(),
            voice_api_url=self.api_url_input.text().strip(),
            voice_cli_checkpoint=model_path,
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

    # --- Step 1 splits execution ---
    def _start_split(self):
        if self.worker and self.worker.isRunning():
            return
        
        selected_item = self.video_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self.parent_widget, "请选择视频", "请先在上方列表中选中一个视频文件。")
            return

        video_path = selected_item.text()
        self.processing_video_path = video_path
        base_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        output_dir = os.path.join(base_dir, video_basename, "splits")

        self.btn_split.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.worker = PySceneDetectWorker(
            video_path=video_path,
            output_dir=output_dir,
            threshold=self.threshold_spin.value(),
            min_scene_len=int(self.min_len_spin.value())
        )
        self.worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.worker.finished.connect(self._on_split_finished)
        self.worker.error.connect(self._on_split_error)
        self.worker.start()

    def _on_split_finished(self, out_dir, count, scenes):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setValue(100)

        self.temp_scenes = scenes
        self.temp_out_dir = out_dir
        self.temp_count = count

        # 未检测到任何镜头切点：明确提示用户调低阈值，不再继续后续步骤
        if count == 0:
            cur_threshold = self.threshold_spin.value()
            self.stage_label.setText("⚠ 未检测到镜头切点，请调低分割阈值后重试。")
            QMessageBox.information(
                self, "未检测到镜头切点",
                f"该视频画面切换不明显，PySceneDetect 未能分出任何镜头。\n\n"
                f"当前分割阈值为 {cur_threshold:.0f}（值越小越敏感）。\n"
                f"建议把阈值调低（如 27 或更低）后重新分割。"
            )
            return

        self.stage_label.setText(f"✅ 镜头分割完成！共切出 {count} 个镜头。")

        # Rename splits with timestamps immediately!
        self._rename_all_splits_with_metadata(out_dir, scenes)
        
        # Check if raw srt is empty, if so auto-transcribe
        raw_srt = ""
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
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
                except Exception as e:
                    log.warning(f"读取已存在字幕失败: {e}")

        if hasattr(self, "raw_srt_display"):
            if raw_srt:
                self.raw_srt_display.setPlainText(raw_srt)
            else:
                raw_srt = self.raw_srt_display.toPlainText().strip()

        if not raw_srt:
            self.stage_label.setText("正在自动生成原视频字幕...")
            self._start_auto_transcription()
        else:
            self._generate_scene_descriptions(scenes)

    def _on_split_error(self, err):
        self.btn_split.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self._check_split_clips_exist()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 运行失败")
        QMessageBox.critical(self.parent_widget, "运行错误", f"处理过程中发生错误：\n{err}")

    # --- Step 1 batch splits (split + rename only, no transcribe/description) ---
    def _start_split_all(self):
        if (self.worker and self.worker.isRunning()) or \
           (getattr(self, "batch_worker", None) and self.batch_worker.isRunning()) or \
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

        reply = QMessageBox.question(
            self.parent_widget, "批量镜头分割",
            f"将对列表中全部 {len(paths)} 个视频依次进行镜头分割。\n"
            f"（系统会自动整理片段文件名，便于后续步骤识别时间戳）\n"
            f"（不会自动转写字幕/生成画面描述）\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._batch_queue = paths
        self._batch_total = len(paths)
        self._batch_done = 0
        self._batch_ok = 0
        self._batch_zero = 0
        self._batch_fail = 0
        self._batch_fail_msgs = []

        self.btn_split.setEnabled(False)
        self.btn_split_all.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._batch_process_next()

    def _batch_process_next(self):
        if not self._batch_queue:
            self._on_batch_all_finished()
            return

        video_path = self._batch_queue.pop(0)
        idx = self._batch_done + 1
        fname = os.path.basename(video_path)

        if not os.path.exists(video_path):
            self._batch_fail += 1
            self._batch_fail_msgs.append(f"{fname}: 文件不存在")
            self._batch_done += 1
            self._batch_process_next()
            return

        base_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        output_dir = os.path.join(base_dir, video_basename, "splits")

        self.stage_label.setText(f"批量分割 ({idx}/{self._batch_total})：{fname}")

        self.batch_worker = PySceneDetectWorker(
            video_path=video_path,
            output_dir=output_dir,
            threshold=self.threshold_spin.value(),
            min_scene_len=int(self.min_len_spin.value())
        )
        self.batch_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.batch_worker.finished.connect(self._on_batch_split_finished)
        self.batch_worker.error.connect(self._on_batch_split_error)
        self.batch_worker.start()

    def _on_batch_split_finished(self, out_dir, count, scenes):
        if count > 0:
            try:
                self._rename_all_splits_with_metadata(out_dir, scenes)
                self._batch_ok += 1
                # Track last successful batch split for vision analysis
                self._last_batch_splits_dir = out_dir
                self._last_batch_scenes = scenes
            except Exception as e:
                self._batch_fail += 1
                self._batch_fail_msgs.append(f"{os.path.basename(out_dir)}: 重命名失败 {e}")
        else:
            self._batch_zero += 1
        self._batch_done += 1
        self._batch_process_next()

    def _on_batch_split_error(self, err):
        self._batch_fail += 1
        # err 是完整 traceback，取最后一行做摘要
        last_line = (err or "").strip().splitlines()[-1] if err else "未知错误"
        self._batch_fail_msgs.append(last_line[:120])
        log.error(f"批量分割单条失败：{err}")
        self._batch_done += 1
        self._batch_process_next()

    def _on_batch_all_finished(self):
        self.btn_split.setEnabled(True)
        self.btn_split_all.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setValue(100)
        self._check_split_clips_exist()

        msg = (f"批量分割完成：成功 {self._batch_ok} 个，"
               f"未检测到切点 {self._batch_zero} 个，失败 {self._batch_fail} 个"
               f"（共 {self._batch_total}）。")
        self.stage_label.setText("✅ " + msg)
        detail = msg
        if self._batch_zero:
            detail += "\n\n「未检测到切点」的视频画面切换不明显，可调低分割阈值后重试。"
        if self._batch_fail_msgs:
            detail += "\n\n失败明细：\n" + "\n".join(self._batch_fail_msgs[:8])

        # Trigger vision analysis on the last batch-split video's splits
        if self._batch_ok > 0 and hasattr(self, "_last_batch_splits_dir"):
            self._trigger_vision_on_dir(
                self._last_batch_splits_dir,
                self._last_batch_scenes if hasattr(self, "_last_batch_scenes") else [],
                "批量分割"
            )

        QMessageBox.information(self.parent_widget, "批量分割完成", detail)

    # --- Step 1 batch "pick best N seconds" highlights ---
    def _start_pick_highlights(self):
        if (self.worker and self.worker.isRunning()) or \
           (getattr(self, "batch_worker", None) and self.batch_worker.isRunning()) or \
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
        self.btn_split_all.setEnabled(False)
        self.btn_pick_highlights.setEnabled(False)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self._pick_highlight_next()

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

    def _on_highlight_finished(self, out_path, start, end):
        self._hl_ok += 1
        log.info(f"精华片段已生成：{out_path}  [{start:.2f}-{end:.2f}]")
        self._hl_done += 1
        self._pick_highlight_next()

    def _on_highlight_error(self, err):
        self._hl_fail += 1
        last_line = (err or "").strip().splitlines()[-1] if err else "未知错误"
        self._hl_fail_msgs.append(last_line[:120])
        log.error(f"批量挑精华单条失败：{err}")
        self._hl_done += 1
        self._pick_highlight_next()

    def _on_highlights_all_finished(self):
        self.btn_split.setEnabled(True)
        self.btn_split_all.setEnabled(True)
        self.btn_pick_highlights.setEnabled(True)
        if hasattr(self, "btn_transcribe_raw"):
            self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setValue(100)

        # 让下方表格读取共享 splits：清掉单视频选中态，使 _check_split_clips_exist 落到 <扫描目录>/splits
        self.processing_video_path = ""
        self.video_list.setCurrentItem(None)
        self.temp_scenes = []
        self._check_split_clips_exist()

        msg = (f"批量挑精华完成：成功 {self._hl_ok} 个，失败 {self._hl_fail} 个"
               f"（共 {self._hl_total}）。已统一写入 {self._hl_shared_splits}，下方列表已刷新，可直接进入下一步组合混剪。")
        self.stage_label.setText("✅ " + msg)
        detail = msg
        if self._hl_fail_msgs:
            detail += "\n\n失败明细：\n" + "\n".join(self._hl_fail_msgs[:8])

        # Trigger vision analysis on highlight clips
        if self._hl_ok > 0 and os.path.exists(self._hl_shared_splits):
            # Build scenes from split files
            files = sorted([f for f in os.listdir(self._hl_shared_splits)
                           if f.lower().endswith((".mp4", ".m4v"))])
            scenes = self._get_split_scenes_times(self._hl_shared_splits, files) if files else []
            self._trigger_vision_on_dir(self._hl_shared_splits, scenes, "批量挑精华")

        QMessageBox.information(self.parent_widget, "批量挑精华完成", detail)

    def _start_auto_transcription(self):
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        if not video_path:
            self._generate_scene_descriptions(self.temp_scenes)
            return

        if not os.path.exists(video_path):
            self._generate_scene_descriptions(self.temp_scenes)
            return

        if not self._transcription_deps_ok():
            log.warning("未检测到转写依赖，跳过自动转写，直接进行画面描述分析。")
            self._generate_scene_descriptions(self.temp_scenes)
            return

        from config.paths import TMP_DIR, WHISPER_MODELS_DIR
        video_dir = os.path.dirname(video_path)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        video_workspace_dir = os.path.join(video_dir, video_basename)
        os.makedirs(video_workspace_dir, exist_ok=True)
        
        audio_path = os.path.join(TMP_DIR, f"{video_basename}_raw_audio.wav")
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
            language=None,
            task_type="transcribe",
            multi_mode=False,
            download_root=WHISPER_MODELS_DIR,
            device_mode="cuda"
        )
        self.transcribe_raw_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.transcribe_raw_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.transcribe_raw_worker.finished.connect(self._on_auto_transcribe_finished)
        self.transcribe_raw_worker.error.connect(self._on_auto_transcribe_error)
        self.transcribe_raw_worker.start()

    def _on_auto_transcribe_finished(self, srt_content, srt_path):
        llm_api_url = self.main_window.ai_config.get("llm_api_url", "")
        llm_api_key = self.main_window.ai_config.get("llm_api_key", "")
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

        self.pending_srt_path = srt_path
        self.raw_unpunctuated_srt = srt_content

        if llm_api_url and llm_api_key and srt_content.strip():
            self.stage_label.setText("🎙️ 正在自动优化字幕标点符号...")
            self.progress_bar.setRange(0, 0)
            
            self.punc_srt_worker = PunctuationSRTLLMWorker(llm_api_url, llm_api_key, llm_model, srt_content)
            
            def on_auto_punc_ok(srt_punctuated):
                try:
                    with open(self.pending_srt_path, "w", encoding="utf-8") as f:
                        f.write(srt_punctuated)
                    if hasattr(self, "raw_srt_display"):
                        self.raw_srt_display.setPlainText(srt_punctuated)
                    self._generate_scene_descriptions(self.temp_scenes)
                except Exception as e:
                    log.warning(f"保存AI优化后的字幕失败: {e}")
                    if hasattr(self, "raw_srt_display"):
                        self.raw_srt_display.setPlainText(self.raw_unpunctuated_srt)
                    self._generate_scene_descriptions(self.temp_scenes)

            def on_auto_punc_err(err):
                log.warning(f"AI优化字幕标点失败: {err}，将采用原始字幕。")
                if hasattr(self, "raw_srt_display"):
                    self.raw_srt_display.setPlainText(self.raw_unpunctuated_srt)
                self._generate_scene_descriptions(self.temp_scenes)

            self.punc_srt_worker.finished.connect(on_auto_punc_ok)
            self.punc_srt_worker.error.connect(on_auto_punc_err)
            self.punc_srt_worker.start()
        else:
            if hasattr(self, "raw_srt_display"):
                self.raw_srt_display.setPlainText(srt_content)
            self._generate_scene_descriptions(self.temp_scenes)

    def _on_auto_transcribe_error(self, err):
        log.warning(f"自动转写字幕失败: {err}")
        self._generate_scene_descriptions(self.temp_scenes)

    def _trigger_vision_on_dir(self, splits_dir, scenes, source_label="镜头分割"):
        """对指定 splits 目录中的所有片段运行视觉AI画面分析。

        供批量分割、批量挑精华等批量路径复用。
        """
        vision_api_url = self.main_window.ai_config.get("llm_vision_api_url", "")
        vision_model = self.main_window.ai_config.get("llm_vision_model", "")

        if not vision_api_url or not vision_model:
            log.info(f"[{source_label}] 未配置本地视觉模型，跳过画面描述生成")
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
            vision_api_url=vision_api_url,
            vision_model=vision_model,
            split_video_paths=split_video_paths,
            scenes=scenes if scenes else [],
            srt_text=raw_srt,
            srt_segments=srt_segments,
        )
        self.vision_desc_worker.finished.connect(self._on_trigger_vision_finished)
        self.vision_desc_worker.error.connect(self._on_desc_error)
        self.vision_desc_worker.start()

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

    def _generate_scene_descriptions(self, scenes):
        llm_api_url = self.main_window.ai_config.get("llm_api_url", "")
        llm_api_key = self.main_window.ai_config.get("llm_api_key", "")
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")
        vision_api_url = self.main_window.ai_config.get("llm_vision_api_url", "")
        vision_model = self.main_window.ai_config.get("llm_vision_model", "")

        # Read raw srt from .srt file in workspace or parent directory
        raw_srt = ""
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
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
                except Exception as e:
                    log.warning(f"读取已存在字幕失败: {e}")

        if not raw_srt and hasattr(self, "raw_srt_display"):
            raw_srt = self.raw_srt_display.toPlainText().strip()

        # Resolve split video paths
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        split_video_paths = []
        if video_path:
            base_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(base_dir, video_basename, "splits")
            if os.path.exists(splits_dir):
                files = sorted([f for f in os.listdir(splits_dir) if f.lower().endswith((".mp4", ".m4v"))])
                split_video_paths = [os.path.join(splits_dir, f) for f in files]

        has_vision = bool(vision_api_url and vision_model and split_video_paths)
        has_llm = bool(llm_api_url and llm_api_key)

        if not has_vision and not has_llm:
            self.stage_label.setText("未配置大模型API，已跳过画面描述生成。")
            self._check_split_clips_exist()
            QMessageBox.information(
                self.parent_widget,
                "分割完成",
                f"镜头分割导出成功！共 {self.temp_count} 个镜头，已跳过画面描述生成。"
            )
            return

        # Parse SRT into time-aligned segments for vision + subtitle combination
        srt_segments = []
        if raw_srt:
            try:
                srt_segments = parse_srt(raw_srt)
            except Exception as e:
                log.warning(f"解析SRT时间轴失败: {e}")

        # Prefer local vision model for visual content analysis
        if has_vision:
            status_msg = "🤖 正在使用本地视觉AI逐镜头分析画面内容..."
            if srt_segments:
                status_msg += "（结合字幕）"
            self.stage_label.setText(status_msg)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)

            self.vision_desc_worker = LocalVisionDescWorker(
                vision_api_url=vision_api_url,
                vision_model=vision_model,
                split_video_paths=split_video_paths,
                scenes=scenes,
                srt_text=raw_srt,
                srt_segments=srt_segments,
            )
            self.vision_desc_worker.finished.connect(self._on_vision_desc_finished)
            self.vision_desc_worker.error.connect(self._on_desc_error)
            self.vision_desc_worker.start()
            return

        # Fallback: text-based LLM analysis (existing flow)
        self.stage_label.setText("🤖 正在使用大模型批量生成镜头画面描述文案...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self.desc_worker = BatchGenerateDescriptionsWorker(
            api_url=llm_api_url,
            api_key=llm_api_key,
            model=llm_model,
            srt_text=raw_srt,
            scenes=scenes,
            split_video_paths=split_video_paths
        )
        self.desc_worker.finished.connect(self._on_desc_finished)
        self.desc_worker.error.connect(self._on_desc_error)
        self.desc_worker.start()

    def _on_vision_desc_finished(self, desc_json):
        """处理本地视觉AI分析完成的结果。"""
        import json as _json
        try:
            desc_dict_raw = _json.loads(desc_json)
            desc_dict = {int(k): v for k, v in desc_dict_raw.items()}
        except Exception as e:
            log.warning(f"_on_vision_desc_finished - JSON解析失败: {e}")
            desc_dict = {}
        log.info(f"_on_vision_desc_finished - 视觉分析完成，共 {len(desc_dict)} 条描述")

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 画面文案描述生成完毕！（本地视觉AI）")

        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        if video_path:
            base_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(base_dir, video_basename, "splits")
            if os.path.exists(splits_dir) and hasattr(self, "temp_scenes"):
                self._rename_all_splits_with_metadata(splits_dir, self.temp_scenes, desc_dict)
                self._save_split_srt()

        self._check_split_clips_exist()

        QMessageBox.information(
            self.parent_widget,
            "分割及视觉描述生成完毕",
            f"镜头分割和画面描述文案生成已顺利完成！\n共生成 {self.temp_count} 个描述性片段。"
        )

    def _on_desc_finished(self, desc_json):
        import json as _json
        try:
            desc_dict_raw = _json.loads(desc_json)
            # Convert string keys back to int keys
            desc_dict = {int(k): v for k, v in desc_dict_raw.items()}
        except Exception as e:
            log.warning(f"_on_desc_finished - JSON解析失败: {e}, 原始数据: {desc_json!r}")
            desc_dict = {}
        log.info(f"_on_desc_finished - 收到描述数据，共 {len(desc_dict)} 条")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 画面文案描述生成完毕！")
        
        video_path = getattr(self, "processing_video_path", "")
        if not video_path:
            selected_item = self.video_list.currentItem()
            video_path = selected_item.text() if selected_item else ""
        _ci = self.video_list.currentItem()
        _ci_text = _ci.text().strip() if _ci else ""
        log.info(f"[DIAG _on_desc_finished] processing_video_path='{getattr(self,'processing_video_path','')}' currentItem='{_ci_text}' using='{video_path}' match={getattr(self,'processing_video_path','')==_ci_text}")
        if video_path:
            base_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(base_dir, video_basename, "splits")
            if os.path.exists(splits_dir) and hasattr(self, "temp_scenes"):
                self._rename_all_splits_with_metadata(splits_dir, self.temp_scenes, desc_dict)
                # Save split srt!
                self._save_split_srt()
        
        self._check_split_clips_exist()
        
        QMessageBox.information(
            self.parent_widget,
            "分割及描述生成完毕",
            f"镜头分割和画面描述文案生成已顺利完成！\n共生成 {self.temp_count} 个描述性片段。"
        )

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

    def _preview_table_item(self, item):
        row = item.row()
        file_item = self.split_result_table.item(row, 1)
        if file_item:
            path = file_item.data(Qt.UserRole)
            if path and os.path.exists(path):
                self._play_video(path)

    def _on_table_cell_changed(self, row, col):
        if col == 3:
            file_item = self.split_result_table.item(row, 1)
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
                            d_item = self.split_result_table.item(r, 3)
                            if d_item:
                                lines.append(d_item.text().strip())
                        self.rewritten_srt_display.setPlainText("\n".join(lines))
                    self._save_split_srt()

    # --- Step 1 subtitle generation execution ---
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

    def _on_transcribe_raw_finished(self, srt_content, srt_path):
        llm_api_url = self.main_window.ai_config.get("llm_api_url", "")
        llm_api_key = self.main_window.ai_config.get("llm_api_key", "")
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

        self.pending_srt_path = srt_path
        self.raw_unpunctuated_srt = srt_content

        if llm_api_url and llm_api_key and srt_content.strip():
            self.stage_label.setText("🎙️ 正在使用 AI 模型自动优化字幕标点符号...")
            self.progress_bar.setRange(0, 0) # Infinite spinner
            
            self.punc_srt_worker = PunctuationSRTLLMWorker(llm_api_url, llm_api_key, llm_model, srt_content)
            self.punc_srt_worker.finished.connect(self._on_punc_srt_finished)
            self.punc_srt_worker.error.connect(self._on_punc_srt_error)
            self.punc_srt_worker.start()
        else:
            self._finalize_transcribe_raw(srt_content, srt_path)

    def _on_punc_srt_finished(self, srt_punctuated):
        try:
            with open(self.pending_srt_path, "w", encoding="utf-8") as f:
                f.write(srt_punctuated)
            self._finalize_transcribe_raw(srt_punctuated, self.pending_srt_path, info_msg=" (AI标点已优化)")
        except Exception as e:
            log.warning(f"保存AI优化后的字幕失败: {e}")
            self._finalize_transcribe_raw(self.raw_unpunctuated_srt, self.pending_srt_path)

    def _on_punc_srt_error(self, err):
        log.warning(f"AI优化字幕标点失败: {err}，将采用原始字幕。")
        self._finalize_transcribe_raw(self.raw_unpunctuated_srt, self.pending_srt_path)

    def _finalize_transcribe_raw(self, srt_content, srt_path, info_msg=""):
        self.btn_split.setEnabled(True)
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

    def _on_transcribe_raw_error(self, err):
        self.btn_split.setEnabled(True)
        self.btn_transcribe_raw.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 字幕生成失败")
        QMessageBox.critical(
            self.parent_widget,
            "字幕生成错误",
            f"处理过程中发生错误：\n{err}"
        )

    def _transcription_deps_ok(self):
        try:
            import torch  # noqa: F401
            import sys
            import os
            # Ensure apps path is in sys.path
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(curr_dir)
            workspace_root = os.path.dirname(project_root)
            apps_dir = os.path.join(workspace_root, "apps")
            if apps_dir not in sys.path:
                sys.path.insert(0, apps_dir)
            import whisperx  # noqa: F401
            return True
        except Exception:
            return False


    # --- Step 2 Concat execution ---
    def _start_assemble_video(self):
        if self.concat_worker and self.concat_worker.isRunning():
            return

        if not self.split_clips_list:
            QMessageBox.warning(self.parent_widget, "无可排列镜头", "请先在待排列镜头视频列表中勾选要用于排列的镜头片段。")
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
            llm_api_url = self.main_window.ai_config.get("llm_api_url", "")
            llm_api_key = self.main_window.ai_config.get("llm_api_key", "")
            llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")
            if not llm_api_url or not llm_api_key:
                QMessageBox.warning(self.parent_widget, "未配置大模型",
                                    "智能匹配需要大模型 API。\n请先在「环境配置」中配置 LLM API 地址与密钥。")
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
                api_url=llm_api_url, api_key=llm_api_key, model=llm_model,
                rewritten_text=script_text,
                candidate_clips=list(self.split_clips_list),
                split_descriptions=self.split_descriptions,
            )
            self.script_match_worker.finished.connect(self._on_script_match_finished)
            self.script_match_worker.error.connect(self._on_script_match_error)
            self.script_match_worker.start()
            return

        # ── 随机洗牌：先生成“预合成方案”，供人工删改/调序并确认后再正式合成 ──
        target_clip_count = int(self.clip_count_combo.currentData())
        if len(self.split_clips_list) < target_clip_count:
            QMessageBox.warning(
                self.parent_widget,
                "可选镜头不足",
                f"您勾选了 {len(self.split_clips_list)} 个镜头，但排列镜头数量配置为 {target_clip_count} 个。\n"
                f"请再多勾选一些镜头，或者减小“排列镜头数量”配置。"
            )
            return

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

    def _on_script_match_error(self, err):
        self.btn_assemble_video.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 文案镜头匹配失败")
        QMessageBox.critical(self.parent_widget, "智能匹配失败",
                             f"大模型匹配文案与镜头时出错：\n{err}\n\n可切换回「随机洗牌」模式继续。")

    def _launch_concat_worker(self, selected_clips, out_montage_dir, recombine_mode,
                              target_clip_count, batch_count, randomness,
                              selected_descriptions_list=None):
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
        )
        self.concat_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.concat_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.concat_worker.finished.connect(self._on_concat_finished)
        self.concat_worker.error.connect(self._on_concat_error)
        self.concat_worker.start()

    def _on_logic_combo_changed(self):
        logic = self.logic_combo.currentData() if hasattr(self, "logic_combo") else "random"
        is_script = (logic == "script")

        # 智能匹配模式：镜头数量由文案行数决定；每批结果相同故固定生成 1 个
        self.lbl_clip_count.setVisible(not is_script)
        self.clip_count_combo.setVisible(not is_script)
        self.lbl_batch_count.setVisible(not is_script)
        self.batch_count_spin.setVisible(not is_script)

        if hasattr(self, "lbl_duration_limit") and hasattr(self, "duration_limit_combo"):
            self.lbl_duration_limit.setVisible(not is_script)
            self.duration_limit_combo.setVisible(not is_script)

        if hasattr(self, "lbl_randomness") and hasattr(self, "randomness_combo"):
            self.lbl_randomness.setVisible(not is_script)
            self.randomness_combo.setVisible(not is_script)

        if hasattr(self, "match_script_edit"):
            self.match_script_edit.setVisible(is_script)

        if not is_script:
            self.clip_count_combo.setEnabled(True)
            self.batch_count_spin.setEnabled(True)
            self.batch_count_spin.setValue(self._recommend_batch_count())
            if hasattr(self, "randomness_combo"):
                self.randomness_combo.setEnabled(True)
                self.randomness_combo.setCurrentIndex(0) # 中 (保留同场景)
        self._update_batch_count_recommendation()

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

    def _on_concat_error(self, err):
        self.btn_assemble_video.setEnabled(True)
        self._confirming_plan_index = None
        self._confirm_queue = []
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 排列失败")
        QMessageBox.critical(self.parent_widget, "排列错误", f"处理过程中发生错误：\n{err}")


    # --- Step 3 Voice synthesis execution ---
    def _on_voice_mode_changed(self):
        mode = self.voice_mode_combo.currentData()
        is_api = (mode == "api")
        self.btn_toggle_server.setVisible(is_api)
        self.server_status_lbl.setVisible(is_api)
        self.btn_view_server_log.setVisible(is_api)

    def _show_advanced_voxcpm_dialog(self):
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("⚙️ VoxCPM 高级配置")
        dialog.setMinimumSize(450, 180)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Row 1: Calling mode
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("调用方式:"))
        row_mode.addWidget(self.voice_mode_combo)
        layout.addLayout(row_mode)
        
        # Row 2: API URL
        row_url = QHBoxLayout()
        row_url.addWidget(QLabel("VoxCPM API 接口地址:"))
        row_url.addWidget(self.api_url_input)
        layout.addLayout(row_url)
        
        # Close button
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)
        
        dialog.exec()

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

    def _batch_ai_rewrite_scripts(self):
        if hasattr(self, "batch_rewrite_worker") and self.batch_rewrite_worker and self.batch_rewrite_worker.isRunning():
            return

        # 1. Check configs
        ai_config = getattr(self.main_window, "ai_config", {})
        api_key = ai_config.get("llm_api_key", "").strip()
        api_url = ai_config.get("llm_api_url", "").strip()
        model = ai_config.get("llm_model", "").strip()
        
        if not api_key:
            QMessageBox.warning(self.parent_widget, "未配置AI大模型", "请先在“设置”或“AI模型配置”中配置 LLM API Key。")
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
        self.batch_rewrite_worker = BatchAITextRewriteWorker(api_url, api_key, model, tasks, self.ai_rewrite_temperature)
        self.batch_rewrite_worker.row_finished.connect(self._on_batch_rewrite_row_finished)
        self.batch_rewrite_worker.progress.connect(self.progress_bar.setValue)
        self.batch_rewrite_worker.finished.connect(self._on_batch_rewrite_finished)
        self.batch_rewrite_worker.error.connect(self._on_batch_rewrite_error)
        self.batch_rewrite_worker.start()
        
    def _on_batch_rewrite_row_finished(self, row_idx, content):
        edit = self.row_edits.get(row_idx)
        if edit:
            edit.setText(content)
            
    def _on_batch_rewrite_finished(self):
        self.btn_batch_ai_rewrite.setEnabled(True)
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.stage_label.setText("✅ 一键AI修改全部文案完成！")
        QMessageBox.information(self.parent_widget, "成功", "批量AI文案修改润色完成！")
        
    def _on_batch_rewrite_error(self, err):
        self.btn_batch_ai_rewrite.setEnabled(True)
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ AI修改文案失败")
        QMessageBox.critical(self.parent_widget, "AI修改失败", f"批量修改失败：\n{err}")

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
                        creationflags=0x08000000 if sys.platform == "win32" else 0)
            free_mb = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 99999
            if free_mb < 6144:
                self.stage_label.setText(f"空闲显存 {free_mb}MB 不足，正在停止 Ollama 释放显存...")
                from utils.ollama_manager import OllamaManager
                mgr = OllamaManager.get()
                if mgr.is_running():
                    mgr.stop()
                    time.sleep(3)
                    self.stage_label.setText("Ollama 已停止，开始声音克隆...")
                else:
                    self.stage_label.setText("Ollama 未运行，显存可能被其他程序占用...")
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

        # Get checkpoint path from model selection dropdown
        model_path = self.model_combo.currentData()
        if model_path == "custom":
            model_path = "" # Reverts to default or empty if not set

        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.text().strip(),
            voice_mode=self.voice_mode_combo.currentData(),
            voice_api_url=self.api_url_input.text().strip(),
            voice_cli_checkpoint=model_path,
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

    def _on_voice_error(self, err):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(bool(self.generated_voice_paths))
        self.btn_next_to_step_4.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 合成失败")
        QMessageBox.critical(self.parent_widget, "人声合成错误", f"处理过程中发生错误：\n{err}")

    def _stop_voxcpm_after_voice(self):
        """声音克隆任务完成后停止 VoxCPM 服务，释放 GPU 显存。"""
        try:
            if hasattr(self, "api_server_process") and self.api_server_process:
                log.info("声音克隆完成，停止 VoxCPM 服务释放显存")
                self.stop_api_server(show_prompt=False)
        except Exception as e:
            log.warning(f"停止 VoxCPM 服务失败: {e}")

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

    def _on_dubbing_error(self, err):
        self.btn_synthesize_voice.setEnabled(True)
        self.btn_dub_videos.setEnabled(True)
        self.btn_next_to_step_4.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 配音替换失败")
        QMessageBox.critical(self.parent_widget, "配音替换错误", f"替换配音过程中发生错误：\n{err}")


    # --- Step 4 Final mix helpers & execution ---
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
                    src_vids = [os.path.join(out_montage_dir, f) for f in os.listdir(out_montage_dir) 
                                if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"))]
                    source_type = "排列视频"
                    
        # Add to table
        for filepath in src_vids:
            self._add_video_to_mix_table(filepath, source_type)
            
        self._adjust_mix_table_height()
        self._update_final_inputs_label()

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

        btn_play_final = QPushButton("▶")
        btn_play_final.setToolTip("播放该视频")
        btn_play_final.setStyleSheet("padding: 0px; font-size: 10px;")
        btn_play_final.setFixedWidth(26)
        btn_play_final.setFixedHeight(22)
        btn_play_final.clicked.connect(lambda checked=False, path=filepath: self._play_video(path))
        action_layout.addWidget(btn_play_final)

        # Per-video BGM selection
        bgm_path = self.per_video_bgm.get(filepath, "")
        if bgm_path:
            btn_bgm = QPushButton("🎵")
            btn_bgm.setToolTip(f"已选: {os.path.basename(bgm_path)}\n点击更换")
            btn_bgm.setStyleSheet("padding: 0px; font-size: 11px; background-color: rgba(46,204,113,0.2);")
        else:
            btn_bgm = QPushButton("🎵")
            btn_bgm.setToolTip("选择该视频的背景音乐")
            btn_bgm.setStyleSheet("padding: 0px; font-size: 11px;")
        btn_bgm.setFixedWidth(26)
        btn_bgm.setFixedHeight(22)
        def make_bgm_cb(fp, b):
            return lambda checked=False: self._select_per_video_bgm(fp, b)
        btn_bgm.clicked.connect(make_bgm_cb(filepath, btn_bgm))
        action_layout.addWidget(btn_bgm)

        btn_del = QPushButton("🗑️")
        btn_del.setToolTip("从合成列表中移除")
        btn_del.setStyleSheet("padding: 0px; font-size: 11px; color: #e74c3c;")
        btn_del.setFixedWidth(26)
        btn_del.setFixedHeight(22)
        btn_del.clicked.connect(self._remove_mix_video_row)
        action_layout.addWidget(btn_del)

        self.mix_video_table.setCellWidget(row_idx, 4, action_w)

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

    def _clear_mix_videos(self):
        self.mix_video_table.setRowCount(0)
        self._adjust_mix_table_height()
        self._update_final_inputs_label()

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

    def _update_final_inputs_label(self):
        pass

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
                self.btn_bgm_play.setText("▶️ 播放")
            else:
                self._bgm_audio_output.setVolume(1.0)
                self._bgm_player.play()
                self.btn_bgm_play.setText("⏸️ 暂停")
                self.btn_bgm_stop.setEnabled(True)
        except Exception as e:
            log.error(f"播放背景音乐失败: {e}")
            QMessageBox.critical(self.parent_widget, "播放错误", f"播放背景音乐失败: {e}")

    def _stop_bgm_play(self):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            self._bgm_player.stop()
            self.btn_bgm_play.setText("▶️ 播放")
            self.btn_bgm_stop.setEnabled(False)
            self.bgm_progress_slider.setValue(0)
            self.lbl_bgm_time.setText("00:00 / 00:00")
        except Exception as e:
            log.error(f"停止背景音乐失败: {e}")

    def _on_bgm_position_changed(self, position):
        self.bgm_progress_slider.blockSignals(True)
        self.bgm_progress_slider.setValue(position)
        self.bgm_progress_slider.blockSignals(False)
        self._update_bgm_time_label(position, self._bgm_player.duration())

    def _on_bgm_duration_changed(self, duration):
        self.bgm_progress_slider.setRange(0, duration)
        self._update_bgm_time_label(self._bgm_player.position(), duration)

    def _set_bgm_position(self, position):
        self._bgm_player.setPosition(position)

    def _update_bgm_time_label(self, position, duration):
        def format_time(ms):
            s = ms // 1000
            m = s // 60
            s = s % 60
            return f"{m:02d}:{s:02d}"
        self.lbl_bgm_time.setText(f"{format_time(position)} / {format_time(duration)}")

    def _on_bgm_volume_changed(self, value):
        self.volume_label.setText(f"{value}%")
        if hasattr(self, "_bgm_audio_output") and self._bgm_audio_output:
            self._bgm_audio_output.setVolume(value / 100.0)

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

    def _on_mix_finished(self, paths):
        self.btn_final_assemble.setEnabled(True)
        self.btn_open_final_dir.setEnabled(True)
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

    def _on_mix_error(self, err):
        self.btn_final_assemble.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 合成失败")
        QMessageBox.critical(self.parent_widget, "合成错误", f"处理过程中发生错误：\n{err}")

    def _open_output_dir(self):
        if self.final_video_path:
            p = os.path.dirname(self.final_video_path)
            if os.path.exists(p):
                try:
                    if sys.platform == "win32":
                        os.startfile(p)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", p])
                    else:
                        subprocess.Popen(["xdg-open", p])
                except Exception as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", str(e))

    def _preview_final_video(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            from PySide6.QtCore import QUrl
            self.final_preview_player.setSource(QUrl.fromLocalFile(path))
            self.final_preview_player.play()
            self.final_preview_title.setText(f"🎥 {os.path.basename(path)}")

    # ==================== LOCAL API SERVER MANAGEMENT ====================
    def _toggle_api_server(self):
        if (hasattr(self, "api_server_process") and self.api_server_process and self.api_server_process.poll() is None) or \
           (self.btn_toggle_server.text().startswith("⏹️") and (not hasattr(self, "api_server_process") or not self.api_server_process)):
            self.stop_api_server()
        else:
            self.start_api_server()

    def start_api_server(self):
        # 1. Check if the server is already active at api_url using socket connect
        api_url = self.api_url_input.text().strip()
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(api_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8000
            
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            s.connect((host, port))
            s.close()
            
            # Port is already open! Skip startup and monitor it.
            log.info(f"VoxCPM API server is already running at port {port}. Skipping startup.")
            self.server_status_lbl.setText("服务状态: 正在运行 (检测到外部进程)")
            self.server_status_lbl.setStyleSheet("color: #2ecc71;")
            self.btn_toggle_server.setText("⏹️ 停止本地 API 服务")
            if not hasattr(self, "api_status_timer") or not self.api_status_timer:
                from PySide6.QtCore import QTimer
                self.api_status_timer = QTimer()
                self.api_status_timer.timeout.connect(self._check_api_server_status)
            self.api_status_timer.start(3000)
            return
        except Exception:
            pass

        # Always use the VoxCPM virtual environment Python
        python_exe = get_voxcpm_python()
        
        # Get checkpoint path from dropdown selection
        checkpoint = self.model_combo.currentData()
        if not checkpoint or checkpoint == "custom":
            checkpoint = "openbmb/VoxCPM2"
            
        api_url = self.api_url_input.text().strip()

        listen_addr = "127.0.0.1:8000"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(api_url)
            if parsed.netloc:
                listen_addr = parsed.netloc
        except Exception:
            pass

        # Script path to voxcpm_api_server.py
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        api_server_script = os.path.abspath(os.path.join(root_dir, "studio", "voxcpm_api_server.py"))

        cmd = [
            python_exe,
            api_server_script,
            "--listen", listen_addr,
            "--checkpoint-path", checkpoint
        ]

        try:
            log_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "logs"))
            os.makedirs(log_dir, exist_ok=True)
            self.api_server_log_path = os.path.join(log_dir, "voxcpm_api.log")

            self.api_server_log_file = open(self.api_server_log_path, "a", encoding="utf-8")

            self.api_server_process = subprocess.Popen(
                cmd,
                stdout=self.api_server_log_file,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            if not hasattr(self, "api_status_timer") or not self.api_status_timer:
                from PySide6.QtCore import QTimer
                self.api_status_timer = QTimer()
                self.api_status_timer.timeout.connect(self._check_api_server_status)
            self.api_status_timer.start(3000)

            self.server_status_lbl.setText("服务状态: 启动中...")
            self.server_status_lbl.setStyleSheet("color: #f39c12;")
            self.btn_toggle_server.setText("⏹️ 停止本地 API 服务")
            log.info(f"VoxCPM API server started with command: {' '.join(cmd)} at cwd: {root_dir}")
        except Exception as e:
            QMessageBox.critical(self.parent_widget, "启动失败", f"无法启动 VoxCPM API 服务:\n{e}")
            log.exception("启动 VoxCPM API 服务失败")

    def _check_api_server_status(self):
        if hasattr(self, "api_server_process") and self.api_server_process:
            ret = self.api_server_process.poll()
            if ret is None:
                self.server_status_lbl.setText(f"服务状态: 正在运行 (PID: {self.api_server_process.pid})")
                self.server_status_lbl.setStyleSheet("color: #2ecc71;")
                self.btn_toggle_server.setText("⏹️ 停止本地 API 服务")
            else:
                self.server_status_lbl.setText(f"服务状态: 已停止 (返回码: {ret})")
                self.server_status_lbl.setStyleSheet("color: #e74c3c;")
                self.btn_toggle_server.setText("▶️ 启动本地 API 服务")
                if hasattr(self, "api_status_timer") and self.api_status_timer and self.api_status_timer.isActive():
                    self.api_status_timer.stop()

                if hasattr(self, "api_server_log_file") and self.api_server_log_file:
                    try:
                        self.api_server_log_file.close()
                    except Exception:
                        pass
                    self.api_server_log_file = None
            return

        # Check external service status via socket
        api_url = self.api_url_input.text().strip()
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(api_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8000
            
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            s.connect((host, port))
            s.close()
            
            self.server_status_lbl.setText("服务状态: 正在运行 (检测到外部进程)")
            self.server_status_lbl.setStyleSheet("color: #2ecc71;")
            self.btn_toggle_server.setText("⏹️ 停止本地 API 服务")
        except Exception:
            self.server_status_lbl.setText("服务状态: 已停止")
            self.server_status_lbl.setStyleSheet("color: #7f8c8d;")
            self.btn_toggle_server.setText("▶️ 启动本地 API 服务")
            if hasattr(self, "api_status_timer") and self.api_status_timer and self.api_status_timer.isActive():
                self.api_status_timer.stop()

    def stop_api_server(self, show_prompt=True):
        if hasattr(self, "api_server_process") and self.api_server_process:
            proc = self.api_server_process
            self.api_server_process = None
            if proc.poll() is None:
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                    else:
                        proc.terminate()
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

            if hasattr(self, "api_server_log_file") and self.api_server_log_file:
                try:
                    self.api_server_log_file.close()
                except Exception:
                    pass
                self.api_server_log_file = None
        else:
            # If we didn't start the server, show a helpful hint and disconnect GUI monitor
            if show_prompt:
                QMessageBox.information(
                    self.parent_widget,
                    "提示",
                    "当前检测到的 VoxCPM API 服务是由外部独立启动运行的进程，无法在软件中停止。请在外部控制台或管理器中关闭它。"
                )

        if hasattr(self, "api_status_timer") and self.api_status_timer and self.api_status_timer.isActive():
            self.api_status_timer.stop()

        self.server_status_lbl.setText("服务状态: 已停止")
        self.server_status_lbl.setStyleSheet("color: #7f8c8d;")
        self.btn_toggle_server.setText("▶️ 启动本地 API 服务")
        log.info("VoxCPM API server stopped")

    def _view_server_log(self):
        if hasattr(self, "api_server_log_path") and os.path.exists(self.api_server_log_path):
            try:
                if sys.platform == "win32":
                    os.startfile(self.api_server_log_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", self.api_server_log_path])
                else:
                    subprocess.Popen(["xdg-open", self.api_server_log_path])
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "无法打开日志", f"无法打开日志文件:\n{e}")
        else:
            QMessageBox.information(self.parent_widget, "无日志", "目前没有生成任何本地服务日志。请先启动服务。")

    def _open_splits_dir(self):
        selected_item = self.video_list.currentItem()
        if selected_item:
            video_path = selected_item.text()
            video_dir = os.path.dirname(video_path)
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            splits_dir = os.path.join(video_dir, video_basename, "splits")
            os.makedirs(splits_dir, exist_ok=True)
            try:
                if sys.platform == "win32":
                    os.startfile(splits_dir)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", splits_dir])
                else:
                    subprocess.Popen(["xdg-open", splits_dir])
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
        else:
            dir_path = self.folder_path_input.text().strip()
            if dir_path and os.path.exists(dir_path):
                splits_dir = os.path.join(dir_path, "splits")
                os.makedirs(splits_dir, exist_ok=True)
                try:
                    if sys.platform == "win32":
                        os.startfile(splits_dir)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", splits_dir])
                    else:
                        subprocess.Popen(["xdg-open", splits_dir])
                except Exception as e:
                    QMessageBox.warning(self.parent_widget, "打开失败", f"无法打开文件夹:\n{e}")
            else:
                QMessageBox.warning(self.parent_widget, "路径无效", "请先选择有效的素材目录。")

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

    def _scan_concat_src_dir(self):
        dir_path = self.concat_src_dir_input.text().strip()
        
        self.concat_clips_list_widget.blockSignals(True)
        self.concat_clips_list_widget.clearContents()
        self.concat_clips_list_widget.setRowCount(0)
        self.concat_clips_list_widget.blockSignals(False)
        
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
            
            # Sort naturally
            files.sort(key=lambda x: os.path.basename(x).lower())
            
            # Try to find a companion srt file to retrieve precise timestamps and descriptions
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

            # Retrieve timestamps fallback
            scenes = self._get_split_scenes_times(dir_path, [os.path.basename(f) for f in files])
            
            self.concat_clips_list_widget.blockSignals(True)
            self.concat_clips_list_widget.setRowCount(len(files))
            
            self.split_clips_cache = {}
            for idx, filepath in enumerate(files):
                filename = os.path.basename(filepath)
                file_dir = os.path.dirname(filepath)
                norm_path = os.path.abspath(filepath)
                
                # Parse from filename first
                parsed = self._parse_split_filename(filename)
                if parsed:
                    p_idx, start_str, end_str, desc = parsed
                    time_str = f"{start_str} --> {end_str}"
                else:
                    # Get description
                    desc = srt_descs.get(idx, "")
                    if not desc:
                        desc = self.split_descriptions.get(norm_path, "")
                    
                    # Col 1: 时间戳 (ReadOnly)
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
                self.split_clips_cache[norm_path] = {
                    "filename": filename,
                    "time_str": time_str,
                    "desc": desc,
                    "duration": clip_dur,
                }
                
                # Col 0: 分割文件名 (Checkable)
                file_item = QTableWidgetItem(filename)
                file_item.setFlags(file_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                file_item.setCheckState(Qt.Checked)
                file_item.setData(Qt.UserRole, norm_path) # Store full path
                file_item.setToolTip(norm_path)
                self.concat_clips_list_widget.setItem(idx, 0, file_item)
                
                # Col 1: 时间戳 (ReadOnly)
                time_item = QTableWidgetItem(time_str)
                time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable) # Read-only
                time_item.setTextAlignment(Qt.AlignCenter)
                self.concat_clips_list_widget.setItem(idx, 1, time_item)
                
                # Col 2: 描述文案 (Editable, with ellipsis + tooltip + double-click popup)
                desc_item = QTableWidgetItem(desc)
                desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                desc_item.setToolTip(desc if desc else "（双击可编辑/查看完整文案）")
                self.concat_clips_list_widget.setItem(idx, 2, desc_item)
                
                # Col 3: 文件目录 (ReadOnly)
                dir_item = QTableWidgetItem(file_dir)
                dir_item.setFlags(dir_item.flags() & ~Qt.ItemIsEditable) # Read-only
                dir_item.setToolTip(norm_path)
                self.concat_clips_list_widget.setItem(idx, 3, dir_item)
                
                # Col 4: 操作 (Play button)
                play_btn = QPushButton("▶")
                play_btn.setToolTip("播放该镜头")
                play_btn.setFixedWidth(28)
                play_btn.setFixedHeight(20)
                play_btn.setStyleSheet("border: none; color: #9ca3af; font-size: 12px; padding: 0;")
                play_btn.clicked.connect(self._make_play_slot(norm_path))
                self.concat_clips_list_widget.setCellWidget(idx, 4, play_btn)
                
            self.concat_clips_list_widget.blockSignals(False)
        
        self._update_concat_count_lbl()

    def _select_all_clips(self):
        self.concat_clips_list_widget.blockSignals(True)
        for r in range(self.concat_clips_list_widget.rowCount()):
            item = self.concat_clips_list_widget.item(r, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self.concat_clips_list_widget.blockSignals(False)
        self._update_concat_count_lbl()

    def _deselect_all_clips(self):
        self.concat_clips_list_widget.blockSignals(True)
        for r in range(self.concat_clips_list_widget.rowCount()):
            item = self.concat_clips_list_widget.item(r, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self.concat_clips_list_widget.blockSignals(False)
        self._update_concat_count_lbl()

    def _update_concat_count_lbl(self):
        self.split_clips_list = []
        checked_count = 0
        total = self.concat_clips_list_widget.rowCount()
        for r in range(total):
            item = self.concat_clips_list_widget.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                checked_count += 1
                path = item.data(Qt.UserRole)
                if path:
                    self.split_clips_list.append(path)
        
        self.clip_count_info_lbl.setText(f"待排列镜头个数: {total}  (已勾选: {checked_count})")
        
        # Update clip_count_combo to include total as default option
        if total > 0:
            self.clip_count_combo.blockSignals(True)
            self.clip_count_combo.clear()
            self.clip_count_combo.addItem(f"全部 ({total} 个镜头)", total)
            for i in [3, 5, 8, 10, 15, 20]:
                if i != total:
                    self.clip_count_combo.addItem(f"{i} 个镜头", i)
            self.clip_count_combo.setCurrentIndex(0)
            self.clip_count_combo.blockSignals(False)
        self._update_batch_count_recommendation()
        
        if checked_count > 0:
            self.btn_assemble_video.setEnabled(True)
        else:
            self.btn_assemble_video.setEnabled(False)

    def _recommend_batch_count(self):
        checked = max(1, len(self.split_clips_list))
        recommended = checked // 2
        if recommended <= 0:
            recommended = 1
        return max(1, min(10, recommended))

    def _update_batch_count_recommendation(self):
        if not hasattr(self, "batch_count_spin"):
            return
        rec = self._recommend_batch_count()
        if hasattr(self, "batch_count_hint_lbl"):
            self.batch_count_hint_lbl.setText(f"推荐: {rec} (中等重复度)")
        cur = int(self.batch_count_spin.value())
        if cur > 10:
            self.batch_count_spin.setValue(10)
        if cur != rec:
            self.batch_count_spin.setValue(rec)

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

    def _build_precompose_plans(self, clips, target_clip_count, batch_count, randomness="medium", duration_limit_sec=0):
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
        for _i in range(batch_count):
            if randomness == "high":
                random.shuffle(deck)
            seq = []
            total_dur = 0.0
            _safety = 0
            while len(seq) < target_clip_count:
                _safety += 1
                if _safety > target_clip_count * 4:
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
                    seq.append(clip)
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
            self.precompose_plans.append(plan)
            self._add_assembled_row(idx, "", plan)

        if self.assembled_clips_list_widget.count() > 0:
            item = self.assembled_clips_list_widget.item(0)
            self.assembled_clips_list_widget.setCurrentItem(item)
            self._on_assembled_item_clicked(item)
        self._update_confirm_all_button()

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
        has_copy = bool(out_path and self._assembled_has_copy(out_path))
        copy_mark = " 📄" if has_copy else ""
        plan_id = plan.get("_plan_id")
        if plan_id is None:
            plan_id = index
            plan["_plan_id"] = index
        text = f"[{index+1}] {file_text}  {status_txt}{copy_mark}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, index)
        item.setData(Qt.UserRole + 1, int(confirmed))
        self.assembled_clips_list_widget.addItem(item)

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

    def _assembled_has_copy(self, path):
        """该组合视频是否已有同名 .txt 文案。"""
        txt = os.path.splitext(path)[0] + ".txt"
        try:
            return os.path.exists(txt) and os.path.getsize(txt) > 0
        except Exception:
            return False

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

    def _collect_assembled_paths(self):
        """按列表顺序返回已确认合成的视频路径。"""
        paths = []
        for plan in self.precompose_plans:
            out_path = (plan.get("output_path") or "").strip()
            if plan.get("confirmed") and out_path and os.path.exists(out_path):
                paths.append(out_path)
        return paths

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

    def _confirm_next_in_queue(self):
        if not self._confirm_queue:
            self._update_confirm_all_button()
            return
        idx = self._confirm_queue.pop(0)
        self._confirm_precompose(idx)

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
        )
        remaining = len(getattr(self, "_confirm_queue", []) or [])
        self.stage_label.setText(f"🎬 正在确认合成预合成 {index + 1}... (剩余 {remaining} 条待确认)")

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

            is_deleted = idx < len(deleted_flags) and deleted_flags[idx]
            if is_deleted:
                for col in range(4):
                    cell = self.sources_detail_widget.item(idx, col)
                    if cell:
                        cell.setBackground(Qt.red)

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

    def _start_sequence_preview_for_plan(self, plan_index):
        self.preview_player.stop()
        self._preview_sequence_clips = []
        if plan_index < 0 or plan_index >= len(self.precompose_plans):
            self._preview_sequence_clips = []
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setText("▶")
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
            self.btn_preview_play.setText("▶")
            return
        self._preview_sequence_idx = 0
        self._play_current_sequence_clip()

    def _start_sequence_preview(self, clips, start_idx=0):
        self._preview_sequence_clips = [os.path.abspath(p) for p in clips if p and os.path.exists(p)]
        if not self._preview_sequence_clips:
            self.preview_player.stop()
            self.preview_overlay_label.hide()
            self.btn_preview_play.setText("▶")
            return
        self._preview_sequence_idx = max(0, min(start_idx, len(self._preview_sequence_clips) - 1))
        self._play_current_sequence_clip()

    def _play_current_sequence_clip(self):
        if not self._preview_sequence_clips:
            return
        clip = self._preview_sequence_clips[self._preview_sequence_idx]
        from PySide6.QtCore import QUrl
        self.preview_player.setSource(QUrl.fromLocalFile(clip))
        self.preview_player.play()
        self.btn_preview_play.setText("⏸")
        total = len(self._preview_sequence_clips)
        self.preview_overlay_label.setText(f"镜头 {self._preview_sequence_idx + 1}/{total}")
        self.preview_overlay_label.adjustSize()
        self.preview_overlay_label.show()

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

    def _gen_copy_for_assembled(self, path):
        """为某个组合视频，根据其画面镜头描述 + 共用产品背景，用大模型生成口播文案并存同名 .txt。
        如果镜头缺少画面描述，先用视觉 LLM 自动补生成。"""
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        api_url = cfg.get("llm_api_url", "").strip()
        api_key = cfg.get("llm_api_key", "").strip()
        model = (cfg.get("llm_model", "") or "deepseek-chat").strip()
        if not api_url or not api_key:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 接口地址和密钥。")
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
            vision_url = cfg.get("llm_vision_api_url", "").strip() or api_url
            vision_key = cfg.get("llm_api_key", "").strip() or api_key
            vision_model = cfg.get("llm_vision_model", "").strip() or model
            self.stage_label.setText(f"正在为 {len(missing_clips)} 个缺失描述的镜头生成画面描述...")
            self._batch_gen_missing_descriptions(
                missing_clips, vision_url, vision_key, vision_model,
                lambda: self._do_gen_copy_for_assembled(path, cfg, api_url, api_key, model))
        else:
            self._do_gen_copy_for_assembled(path, cfg, api_url, api_key, model)

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

    def _batch_gen_copy_by_scene(self):
        """一键为所有已生成的组合视频，按各自画面镜头描述生成口播文案（共用一份产品背景）。
        如果镜头缺少画面描述（如原视频无声音未生成），先用视觉 LLM 自动补生成描述。"""
        cfg = getattr(self.main_window, "ai_config", {}) or {}
        api_url = cfg.get("llm_api_url", "").strip()
        api_key = cfg.get("llm_api_key", "").strip()
        model = (cfg.get("llm_model", "") or "deepseek-chat").strip()
        if not api_url or not api_key:
            QMessageBox.warning(self.parent_widget, "未配置大模型",
                                "请先在设置中配置 LLM 接口地址和密钥。")
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
            vision_url = cfg.get("llm_vision_api_url", "").strip() or api_url
            vision_key = cfg.get("llm_api_key", "").strip() or api_key
            vision_model = cfg.get("llm_vision_model", "").strip() or model
            self._batch_gen_missing_descriptions(
                list(missing_desc_clips), vision_url, vision_key, vision_model,
                lambda: self._start_batch_copy(api_url, api_key, model, info, targets))
        else:
            self._start_batch_copy(api_url, api_key, model, info, targets)

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
        self._scene_copy_worker = SceneCopyWorker(
            api_url, api_key, model, scenes, brand, product, model_name, extra)

        companion_txt = os.path.splitext(path)[0] + ".txt"

        def on_ok(content, ctxt=companion_txt, pth=path):
            try:
                with open(ctxt, "w", encoding="utf-8") as f:
                    f.write(content)
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
            self.btn_preview_play.setText("▶")

    def _toggle_preview_video(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.preview_player.playbackState() == QMediaPlayer.PlayingState:
            self.preview_player.pause()
            self.btn_preview_play.setText("▶")
        else:
            self.preview_player.play()
            self.btn_preview_play.setText("⏸")
            
    def _set_preview_position(self, position):
        self.preview_player.setPosition(position)
        
    def _on_preview_position_changed(self, position):
        self.preview_slider.setValue(position)
        
    def _on_preview_duration_changed(self, duration):
        self.preview_slider.setRange(0, duration)

    def _on_preview_media_status_changed(self, status):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.EndOfMedia and self._preview_sequence_clips:
                self._preview_sequence_idx += 1
                if self._preview_sequence_idx >= len(self._preview_sequence_clips):
                    self._preview_sequence_idx = 0
                self._play_current_sequence_clip()
        except Exception:
            pass

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
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "无法播放", f"播放视频失败:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到该视频文件:\n{path}")

    def _play_video(self, path):
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self.parent_widget, "文件不存在", f"找不到视频文件:\n{path}")

    def _make_play_slot(self, filepath):
        return lambda: self._play_video(filepath)

    def _preview_concat_table_item(self, item):
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
            btn_save = QPushButton("💾 保存修改")
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

    def _on_concat_table_cell_changed(self, row, col):
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
