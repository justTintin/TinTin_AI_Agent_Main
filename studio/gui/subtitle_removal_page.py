# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import traceback
import time
import gc
import av
from PIL import Image, ImageDraw

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QSlider, QSplitter, QWidget, QTextEdit, QSizePolicy)
from PySide6.QtCore import Signal, QThread, Qt, QTimer, QSize
from utils.base_worker import BaseWorker
from PySide6.QtGui import QImage, QPixmap, QIcon
from utils.logger_utils import log
from config.paths import TMP_DIR, VSR_DIR
from utils.platform_utils import python_binary, IS_WIN

class SubtitleRemovalWorker(BaseWorker):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, vsr_python, vsr_script, video_path, ymin, ymax, xmin, xmax, mode, skip_detect, lama_fast, h264, preview_path):
        super().__init__()
        self.vsr_python = vsr_python
        self.vsr_script = vsr_script
        self.video_path = video_path
        self.ymin = ymin
        self.ymax = ymax
        self.xmin = xmin
        self.xmax = xmax
        self.mode = mode
        self.skip_detect = skip_detect
        self.lama_fast = lama_fast
        self.h264 = h264
        self.preview_path = preview_path
        self.process = None

    def run(self):
        cmd = [
            self.vsr_python,
            self.vsr_script,
            "--video", self.video_path,
            "--ymin", str(self.ymin),
            "--ymax", str(self.ymax),
            "--xmin", str(self.xmin),
            "--xmax", str(self.xmax),
            "--mode", self.mode,
            "--preview_path", self.preview_path
        ]
        if self.skip_detect:
            cmd.append("--skip_detect")
        if self.lama_fast:
            cmd.append("--lama_fast")
        if self.h264:
            cmd.append("--h264")

        self.status_updated.emit("正在准备启动 AI 去字幕算法包...")
        self.log_received.emit(f"执行后端命令: {' '.join(cmd)}")
        
        try:
            # Hide the command prompt console window on Windows
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                bufsize=1,
                cwd=os.path.dirname(self.vsr_script)
            )
            
            while self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    continue
                line = line.strip()
                self.log_received.emit(line)
                
                if line.startswith("[PROGRESS]"):
                    try:
                        prog = int(line.split()[1])
                        self.progress_updated.emit(prog)
                    except Exception:
                        pass
                elif line.startswith("[STARTING]"):
                    self.status_updated.emit("AI 正在深度擦除字幕并重绘视频区域...")
            
            # Read remaining output
            for line in self.process.stdout:
                line = line.strip()
                self.log_received.emit(line)
                if line.startswith("[PROGRESS]"):
                    try:
                        prog = int(line.split()[1])
                        self.progress_updated.emit(prog)
                    except Exception:
                        pass
                elif line.startswith("[STARTING]"):
                    self.status_updated.emit("AI 正在深度擦除字幕并重绘视频区域...")
                
            ret_code = self.process.returncode
            if ret_code == 0:
                # Find output path. VSR outputs to {vd_name}_no_sub.mp4 in the same directory
                base_dir = os.path.dirname(self.video_path)
                vd_name = os.path.splitext(os.path.basename(self.video_path))[0]
                ext = os.path.splitext(self.video_path)[1].lower()
                is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]
                if is_pic:
                    out_path = os.path.join(base_dir, "no_sub", f"{vd_name}{ext}")
                else:
                    out_path = os.path.join(base_dir, f"{vd_name}_no_sub.mp4")
                self.finished.emit(True, out_path)
            else:
                self.finished.emit(False, f"去字幕引擎非正常退出，错误码: {ret_code}")
                
        except Exception as e:
            self.finished.emit(False, str(e))

    def stop(self):
        if self.process:
            try:
                if sys.platform == "win32":
                    # 使用 taskkill /T 确保终止包含 CUDA 子进程在内的整个进程树
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        capture_output=True
                    )
                    try:
                        self.process.wait(timeout=5)
                    except Exception:
                        pass
                else:
                    self.process.terminate()
                    self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                # 进程终止后释放 GPU 缓存
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        gc.collect()
                except Exception:
                    pass


class InteractivePreviewLabel(QLabel):
    boundsChanged = Signal(int, int, int, int)
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #0b1220; border-radius: 8px; border: 1px solid #2e2e32;")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        
    def sizeHint(self):
        return QSize(400, 300)
        
        self.sel_x = 0
        self.sel_y = 0
        self.sel_w = 100
        self.sel_h = 100
        
        self.frame_w = 0
        self.frame_h = 0
        
        self.target_w = 0
        self.target_h = 0
        self.px_offset_x = 0
        self.px_offset_y = 0
        
        self.drag_mode = None
        self.drag_start_pos = None
        self.drag_start_rect = None

    def set_selection(self, x, y, w, h):
        self.sel_x = x
        self.sel_y = y
        self.sel_w = w
        self.sel_h = h

    def get_handle_under_mouse(self, pos):
        if self.frame_w <= 0 or self.frame_h <= 0 or self.target_w <= 0 or self.target_h <= 0:
            return None
            
        mx, my = pos.x(), pos.y()
        
        w_ratio = self.target_w / self.frame_w
        h_ratio = self.target_h / self.frame_h
        
        rx0 = self.px_offset_x + self.sel_x * w_ratio
        ry0 = self.px_offset_y + self.sel_y * h_ratio
        rx1 = self.px_offset_x + (self.sel_x + self.sel_w) * w_ratio
        ry1 = self.px_offset_y + (self.sel_y + self.sel_h) * h_ratio
        
        threshold = 10 # pixels
        
        near_left = abs(mx - rx0) < threshold
        near_right = abs(mx - rx1) < threshold
        near_top = abs(my - ry0) < threshold
        near_bottom = abs(my - ry1) < threshold
        
        if near_left and near_top:
            return 'top-left'
        if near_right and near_top:
            return 'top-right'
        if near_left and near_bottom:
            return 'bottom-left'
        if near_right and near_bottom:
            return 'bottom-right'
            
        if near_left and ry0 <= my <= ry1:
            return 'left'
        if near_right and ry0 <= my <= ry1:
            return 'right'
        if near_top and rx0 <= mx <= rx1:
            return 'top'
        if near_bottom and rx0 <= mx <= rx1:
            return 'bottom'
            
        if rx0 < mx < rx1 and ry0 < my < ry1:
            return 'move'
            
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.get_handle_under_mouse(event.pos())
            if handle is not None:
                self.drag_mode = handle
                self.drag_start_pos = event.pos()
                self.drag_start_rect = (self.sel_x, self.sel_y, self.sel_w, self.sel_h)

    def mouseMoveEvent(self, event):
        if self.drag_mode is not None and self.drag_start_pos is not None:
            delta_x_widget = event.pos().x() - self.drag_start_pos.x()
            delta_y_widget = event.pos().y() - self.drag_start_pos.y()
            
            w_ratio = self.frame_w / self.target_w
            h_ratio = self.frame_h / self.target_h
            
            delta_x = int(delta_x_widget * w_ratio)
            delta_y = int(delta_y_widget * h_ratio)
            
            sx, sy, sw, sh = self.drag_start_rect
            
            if self.drag_mode == 'move':
                nx = sx + delta_x
                ny = sy + delta_y
                nx = max(0, min(nx, self.frame_w - sw))
                ny = max(0, min(ny, self.frame_h - sh))
                self.sel_x = nx
                self.sel_y = ny
            else:
                x0 = sx
                y0 = sy
                x1 = sx + sw
                y1 = sy + sh
                
                min_size = 10
                
                if 'left' in self.drag_mode:
                    x0 = max(0, min(x0 + delta_x, x1 - min_size))
                if 'right' in self.drag_mode:
                    x1 = min(self.frame_w, max(x1 + delta_x, x0 + min_size))
                if 'top' in self.drag_mode:
                    y0 = max(0, min(y0 + delta_y, y1 - min_size))
                if 'bottom' in self.drag_mode:
                    y1 = min(self.frame_h, max(y1 + delta_y, y0 + min_size))
                    
                self.sel_x = x0
                self.sel_y = y0
                self.sel_w = x1 - x0
                self.sel_h = y1 - y0
                
            self.boundsChanged.emit(self.sel_x, self.sel_y, self.sel_w, self.sel_h)
        else:
            handle = self.get_handle_under_mouse(event.pos())
            if handle in ('top-left', 'bottom-right'):
                self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ('top-right', 'bottom-left'):
                self.setCursor(Qt.SizeBDiagCursor)
            elif handle in ('left', 'right'):
                self.setCursor(Qt.SizeHorCursor)
            elif handle in ('top', 'bottom'):
                self.setCursor(Qt.SizeVerCursor)
            elif handle == 'move':
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_mode = None
            self.drag_start_pos = None
            self.drag_start_rect = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


from gui.base_page import BasePage


class SubtitleRemovalPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.timer = None
        self.original_frame = None
        self.frame_width = 1280
        self.frame_height = 720
        self.preview_img_path = ""

    def setup(self):
        # Create temp dir if not exists
        tmp_dir = TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        self.preview_img_path = os.path.join(tmp_dir, "vsr_preview.jpg")

        # Page main layout (QSplitter for adjustable panels)
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(16)

        # Title
        heading = QLabel("🎬 视频 AI 智能去字幕 (VSR)")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        main_layout.addWidget(splitter, 1)

        # --- Left Panel: Controls & Options ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)
        
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(14)

        # Video path picker
        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("输入视频/图片:"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("选择视频 (.mp4/.avi) 或图片 ...")
        self.video_path_input.textChanged.connect(self._on_video_path_changed)
        inp_row.addWidget(self.video_path_input)
        btn_sel = QPushButton("选择文件")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_video)
        inp_row.addWidget(btn_sel)
        card_layout.addLayout(inp_row)

        # Area Sliders
        area_group = QFrame()
        area_group.setStyleSheet("QFrame { background-color: #26262a; border-radius: 8px; }")
        area_layout = QVBoxLayout(area_group)
        area_layout.setContentsMargins(14, 12, 14, 12)
        
        area_title = QLabel("✂️ 字幕选区范围坐标调整:")
        area_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        area_layout.addWidget(area_title)

        hint_lbl = QLabel("💡 提示：您也可以直接在右侧预览画面上通过拖动或拉伸绿框来调整选区。")
        hint_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px; margin-top: -4px;")
        hint_lbl.setWordWrap(True)
        area_layout.addWidget(hint_lbl)

        # Sliders grid
        sliders_layout = QVBoxLayout()
        sliders_layout.setSpacing(8)

        # X Slider
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("起始横坐标 X:"))
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(0, 100)
        self.x_slider.valueChanged.connect(self.update_preview)
        x_row.addWidget(self.x_slider)
        self.x_val_lbl = QLabel("0")
        x_row.addWidget(self.x_val_lbl)
        sliders_layout.addLayout(x_row)

        # W Slider
        w_row = QHBoxLayout()
        w_row.addWidget(QLabel("字幕选区宽 W:"))
        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.setRange(1, 100)
        self.w_slider.valueChanged.connect(self.update_preview)
        w_row.addWidget(self.w_slider)
        self.w_val_lbl = QLabel("1")
        w_row.addWidget(self.w_val_lbl)
        sliders_layout.addLayout(w_row)

        # Y Slider
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("起始纵坐标 Y:"))
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(0, 100)
        self.y_slider.valueChanged.connect(self.update_preview)
        y_row.addWidget(self.y_slider)
        self.y_val_lbl = QLabel("0")
        y_row.addWidget(self.y_val_lbl)
        sliders_layout.addLayout(y_row)

        # H Slider
        h_row = QHBoxLayout()
        h_row.addWidget(QLabel("字幕选区高 H:"))
        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.setRange(1, 100)
        self.h_slider.valueChanged.connect(self.update_preview)
        h_row.addWidget(self.h_slider)
        self.h_val_lbl = QLabel("1")
        h_row.addWidget(self.h_val_lbl)
        sliders_layout.addLayout(h_row)

        area_layout.addLayout(sliders_layout)

        # Reset button
        self.btn_reset_area = QPushButton("🔄 重置到默认字幕下方范围")
        self.btn_reset_area.setObjectName("secondary_button")
        self.btn_reset_area.clicked.connect(self.reset_default_area)
        area_layout.addWidget(self.btn_reset_area)
        
        card_layout.addWidget(area_group)

        # Algorithm selection
        algo_row = QHBoxLayout()
        algo_row.addWidget(QLabel("重绘填充算法:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("STTN 算法 (速度快，对真人视频好)", "sttn")
        self.mode_combo.addItem("Lama 算法 (效果强，对动画视频好)", "lama")
        self.mode_combo.addItem("ProPainter 算法 (显存要求极高，极剧烈运动)", "propainter")
        algo_row.addWidget(self.mode_combo)
        card_layout.addLayout(algo_row)

        # Checkboxes
        self.skip_detect_chk = QCheckBox("⏩ 跳过文字检测 (对框选区域强制覆盖重绘，仅STTN有效)")
        self.skip_detect_chk.setChecked(True)
        card_layout.addWidget(self.skip_detect_chk)

        self.lama_fast_chk = QCheckBox("⚡ LAMA极速模式 (直接擦除，忽略精细过渡)")
        self.lama_fast_chk.setChecked(False)
        card_layout.addWidget(self.lama_fast_chk)

        self.h264_chk = QCheckBox("📱 使用 H.264 兼容编码 (方便移动端/手机播放)")
        self.h264_chk.setChecked(True)
        card_layout.addWidget(self.h264_chk)

        # Status & progress
        self.status_lbl = QLabel("状态: 就绪")
        self.status_lbl.setObjectName("muted_text")
        card_layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        # Run buttons
        btn_action_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始去除字幕")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_removal)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_removal)
        btn_action_layout.addWidget(self.btn_stop)
        card_layout.addLayout(btn_action_layout)

        left_layout.addWidget(card)
        left_widget.setMaximumWidth(450)
        splitter.addWidget(left_widget)

        # --- Right Panel: Live Preview & Console Output ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(14)

        # Video Preview card
        preview_card = QFrame()
        preview_card.setObjectName("card")
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        
        p_title = QLabel("🖼️ 实时预览画面 (绿框内为字幕擦除重绘选区):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title)

        self.preview_label = InteractivePreviewLabel()
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.resized.connect(self.update_preview)
        p_layout.addWidget(self.preview_label)

        # Video progress slider for scrubbing / previewing frames
        seek_row = QHBoxLayout()
        self.btn_prev_frame = QPushButton("◀")
        self.btn_prev_frame.setFixedWidth(30)
        self.btn_prev_frame.setStyleSheet("QPushButton { font-size: 10px; padding: 2px 4px; }")
        self.btn_prev_frame.clicked.connect(self._step_prev_frame)
        seek_row.addWidget(self.btn_prev_frame)
        
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_row.addWidget(self.seek_slider)
        
        self.btn_next_frame = QPushButton("▶")
        self.btn_next_frame.setFixedWidth(30)
        self.btn_next_frame.setStyleSheet("QPushButton { font-size: 10px; padding: 2px 4px; }")
        self.btn_next_frame.clicked.connect(self._step_next_frame)
        seek_row.addWidget(self.btn_next_frame)
        
        self.lbl_seek_time = QLabel("00:00 / 00:00")
        self.lbl_seek_time.setFixedWidth(90)
        self.lbl_seek_time.setAlignment(Qt.AlignCenter)
        self.lbl_seek_time.setStyleSheet("color: #9ca3af; font-size: 11px;")
        seek_row.addWidget(self.lbl_seek_time)
        
        p_layout.addLayout(seek_row)
        right_layout.addWidget(preview_card)

        # Console Output Log
        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel("📝 处理引擎实时运行日志:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(160)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card)

        splitter.addWidget(right_widget)

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择输入视频或图片",
            "",
            "Media Files (*.mp4 *.avi *.mov *.mkv *.png *.jpg *.jpeg);;All Files (*)"
        )
        if path:
            self.video_path_input.setText(path)

    def _on_video_path_changed(self, path):
        path = path.strip()
        if not path or not os.path.exists(path):
            self.original_frame = None
            self.preview_label.clear()
            self.preview_label.setText("请选择有效的媒体文件")
            return

        try:
            # Check if it is image or video
            ext = os.path.splitext(path)[1].lower()
            is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]
            if is_pic:
                img = Image.open(path)
                self.original_frame = img
                self.frame_width, self.frame_height = img.size
                
                self.seek_slider.setEnabled(False)
                self.seek_slider.setValue(0)
                self.lbl_seek_time.setText("图片无进度")
                self.btn_prev_frame.setEnabled(False)
                self.btn_next_frame.setEnabled(False)
            else:
                container = av.open(path)
                video_stream = next(s for s in container.streams if s.type == 'video')
                self.frame_width = video_stream.width
                self.frame_height = video_stream.height
                
                # Read first frame
                for frame in container.decode(video_stream):
                    self.original_frame = frame.to_image()
                    break
                
                total_sec = container.duration / 1000000.0 if container.duration else 0.0
                self.lbl_seek_time.setText(f"00:00 / {self._format_time(total_sec)}")
                container.close()
                
                self.seek_slider.setEnabled(True)
                self.seek_slider.setValue(0)
                self.btn_prev_frame.setEnabled(True)
                self.btn_next_frame.setEnabled(True)
                
            # Block sliders signals during bounds setup
            self.x_slider.blockSignals(True)
            self.w_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            self.h_slider.blockSignals(True)

            self.x_slider.setRange(0, self.frame_width)
            self.w_slider.setRange(1, self.frame_width)
            self.y_slider.setRange(0, self.frame_height)
            self.h_slider.setRange(1, self.frame_height)

            self.preview_label.frame_w = self.frame_width
            self.preview_label.frame_h = self.frame_height

            # Set VSR defaults: Y = 78%, H = 21%, X = 5%, W = 90%
            self.x_slider.setValue(int(self.frame_width * 0.05))
            self.w_slider.setValue(int(self.frame_width * 0.90))
            self.y_slider.setValue(int(self.frame_height * 0.78))
            self.h_slider.setValue(int(self.frame_height * 0.21))

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            self.update_preview()
        except Exception as e:
            log.error(f"Failed to load video preview: {e}")
            self.original_frame = None
            self.preview_label.setText(f"预览加载失败: {e}")

    def reset_default_area(self):
        if self.original_frame is not None:
            self.x_slider.blockSignals(True)
            self.w_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            self.h_slider.blockSignals(True)

            self.x_slider.setValue(int(self.frame_width * 0.05))
            self.w_slider.setValue(int(self.frame_width * 0.90))
            self.y_slider.setValue(int(self.frame_height * 0.78))
            self.h_slider.setValue(int(self.frame_height * 0.21))

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            self.update_preview()

    def update_preview(self):
        if self.worker and self.worker.isRunning():
            return
            
        x = self.x_slider.value()
        w = self.w_slider.value()
        y = self.y_slider.value()
        h = self.h_slider.value()

        # Update text labels
        self.x_val_lbl.setText(str(x))
        self.w_val_lbl.setText(str(w))
        self.y_val_lbl.setText(str(y))
        self.h_val_lbl.setText(str(h))

        # Update the interactive preview label coordinates
        self.preview_label.set_selection(x, y, w, h)

        if self.original_frame is not None:
            # Fit to widget layout keeping aspect ratio
            display_w = self.preview_label.width()
            display_h = self.preview_label.height()
            if display_w < 100 or display_h < 100:
                display_w, display_h = 720, 405

            w_img, h_img = self.original_frame.size
            ratio = min(display_w / w_img, display_h / h_img)
            target_w = int(w_img * ratio)
            target_h = int(h_img * ratio)
            if target_w < 1: target_w = 1
            if target_h < 1: target_h = 1

            # Update interactive preview label target size and offsets
            self.preview_label.target_w = target_w
            self.preview_label.target_h = target_h
            self.preview_label.px_offset_x = (display_w - target_w) // 2
            self.preview_label.px_offset_y = (display_h - target_h) // 2

            # PIL resize first (LANCZOS for high quality downscaling)
            resized_img = self.original_frame.resize((target_w, target_h), Image.Resampling.LANCZOS)

            # Draw green rectangle bounds on the resized PIL image directly
            draw = ImageDraw.Draw(resized_img)
            rx0 = int(x * target_w / w_img)
            ry0 = int(y * target_h / h_img)
            rx1 = int((x + w) * target_w / w_img)
            ry1 = int((y + h) * target_h / h_img)
            draw.rectangle([rx0, ry0, rx1, ry1], outline="#00ff00", width=3)

            # Convert PIL image to QImage - specifying bytesPerLine prevents shearing/skew/tilting deforms!
            rgb_img = resized_img.convert("RGB")
            data = rgb_img.tobytes("raw", "RGB")
            qImg = QImage(data, target_w, target_h, target_w * 3, QImage.Format_RGB888)
            self.preview_label.setPixmap(QPixmap.fromImage(qImg))

    def _on_label_bounds_changed(self, x, y, w, h):
        self.x_slider.blockSignals(True)
        self.w_slider.blockSignals(True)
        self.y_slider.blockSignals(True)
        self.h_slider.blockSignals(True)

        self.x_slider.setValue(x)
        self.w_slider.setValue(w)
        self.y_slider.setValue(y)
        self.h_slider.setValue(h)

        self.x_val_lbl.setText(str(x))
        self.w_val_lbl.setText(str(w))
        self.y_val_lbl.setText(str(y))
        self.h_val_lbl.setText(str(h))

        self.x_slider.blockSignals(False)
        self.w_slider.blockSignals(False)
        self.y_slider.blockSignals(False)
        self.h_slider.blockSignals(False)
        
        self.update_preview()

    def start_removal(self):
        video_path = self.video_path_input.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "参数错误", "请先选择有效的输入视频或图片！")
            return

        # Resolve paths to VSR local modules
        vsr_dir = VSR_DIR
        vsr_python = os.path.join(vsr_dir, "Python", python_binary())
        vsr_script = os.path.join(vsr_dir, "resources", "vsr_run.py")

        # On Linux, the bundled Python is Windows-only; fall back to project venv
        if not os.path.exists(vsr_python) and not IS_WIN:
            vsr_python = sys.executable

        if not os.path.exists(vsr_python) or not os.path.exists(vsr_script):
            QMessageBox.critical(
                self.parent_widget,
                "文件丢失",
                f"未能定位到去字幕算法包及其关联的 Python 环境，请检查以下目录是否完整存在：\n\n{vsr_dir}"
            )
            return

        # Remove previous preview file
        if os.path.exists(self.preview_img_path):
            try:
                os.remove(self.preview_img_path)
            except Exception:
                pass

        # Disable controls during execution
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.video_path_input.setEnabled(False)
        self.x_slider.setEnabled(False)
        self.w_slider.setEnabled(False)
        self.y_slider.setEnabled(False)
        self.h_slider.setEnabled(False)
        self.btn_reset_area.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.skip_detect_chk.setEnabled(False)
        self.lama_fast_chk.setEnabled(False)
        self.h264_chk.setEnabled(False)
        self.seek_slider.setEnabled(False)
        self.btn_prev_frame.setEnabled(False)
        self.btn_next_frame.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_view.clear()

        # Instantiate background worker
        self.worker = SubtitleRemovalWorker(
            vsr_python=vsr_python,
            vsr_script=vsr_script,
            video_path=video_path,
            ymin=self.y_slider.value(),
            ymax=self.y_slider.value() + self.h_slider.value(),
            xmin=self.x_slider.value(),
            xmax=self.x_slider.value() + self.w_slider.value(),
            mode=self.mode_combo.currentData(),
            skip_detect=self.skip_detect_chk.isChecked(),
            lama_fast=self.lama_fast_chk.isChecked(),
            h264=self.h264_chk.isChecked(),
            preview_path=self.preview_img_path
        )
        self.worker.progress_updated.connect(self.on_worker_progress)
        self.worker.status_updated.connect(self.on_worker_status)
        self.worker.log_received.connect(self.on_worker_log)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

        # Timer to update preview frames from file (runs every 400ms)
        self.timer = QTimer()
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll_preview_image)
        self.timer.start()

    def stop_removal(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_lbl.setText("状态: 已被用户终止。")
            self.log_view.append("\n[WARN] 去字幕引擎任务已被用户终止。")
            self.cleanup_ui()

    def on_worker_progress(self, val):
        self.progress_bar.setValue(val)

    def on_worker_status(self, text):
        self.status_lbl.setText(f"状态: {text}")

    def on_worker_log(self, text):
        self.log_view.append(text)

    def on_worker_finished(self, success, out_path):
        self.cleanup_ui()
        if success:
            self.status_lbl.setText("状态: 字幕擦除完毕！")
            QMessageBox.information(
                self.parent_widget,
                "去字幕成功",
                f"字幕擦除并画面重绘成功！\n新生成的媒体文件已保存至：\n\n{out_path}"
            )
            # Load the new video first frame as the preview
            self._on_video_path_changed(out_path)
            self.video_path_input.setText(out_path)
        else:
            self.status_lbl.setText(f"状态: 出错。")
            QMessageBox.critical(
                self.parent_widget,
                "处理失败",
                f"去字幕执行过程中发生错误：\n\n{out_path}"
            )

    def poll_preview_image(self):
        # Read the file by loading it into memory to avoid OS file locks
        if os.path.exists(self.preview_img_path):
            try:
                pix = QPixmap()
                with open(self.preview_img_path, "rb") as f:
                    data = f.read()
                pix.loadFromData(data)
                if not pix.isNull():
                    self.preview_label.setPixmap(pix.scaled(
                        self.preview_label.size(), 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    ))
            except Exception:
                pass

    def cleanup_ui(self):
        if self.timer:
            self.timer.stop()
            self.timer = None
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.video_path_input.setEnabled(True)
        self.x_slider.setEnabled(True)
        self.w_slider.setEnabled(True)
        self.y_slider.setEnabled(True)
        self.h_slider.setEnabled(True)
        self.btn_reset_area.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.skip_detect_chk.setEnabled(True)
        self.lama_fast_chk.setEnabled(True)
        self.h264_chk.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Restore seek controls based on if it's a video
        video_path = self.video_path_input.text().strip()
        ext = os.path.splitext(video_path)[1].lower() if video_path else ""
        is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]
        self.seek_slider.setEnabled(not is_pic and bool(video_path))
        self.btn_prev_frame.setEnabled(not is_pic and bool(video_path))
        self.btn_next_frame.setEnabled(not is_pic and bool(video_path))

    def _seek_to_ratio(self, ratio):
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
            
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".bmp"]:
            return
            
        try:
            container = av.open(path)
            video_stream = next(s for s in container.streams if s.type == 'video')
            
            duration = video_stream.duration
            if duration is None or duration <= 0:
                duration_sec = container.duration / 1000000.0
                target_sec = ratio * duration_sec
                target_ts = int(target_sec / float(video_stream.time_base))
            else:
                target_ts = int(ratio * duration)
                
            container.seek(target_ts, stream=video_stream)
            
            frame_found = False
            for frame in container.decode(video_stream):
                self.original_frame = frame.to_image()
                frame_found = True
                break
                
            container.close()
            
            if frame_found:
                self.update_preview()
                
                total_sec = container.duration / 1000000.0 if container.duration else 0.0
                curr_sec = ratio * total_sec
                self.lbl_seek_time.setText(f"{self._format_time(curr_sec)} / {self._format_time(total_sec)}")
                
        except Exception as e:
            log.error(f"Seek failed: {e}")

    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _on_seek_moved(self, value):
        ratio = value / 1000.0
        self._seek_to_ratio(ratio)

    def _on_seek_released(self):
        ratio = self.seek_slider.value() / 1000.0
        self._seek_to_ratio(ratio)

    def _step_prev_frame(self):
        val = self.seek_slider.value()
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            container = av.open(path)
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            if total_sec > 0:
                ratio_step = 1.0 / total_sec
                new_ratio = max(0.0, (val / 1000.0) - ratio_step)
                self.seek_slider.setValue(int(new_ratio * 1000))
                self._seek_to_ratio(new_ratio)
        except Exception:
            pass

    def _step_next_frame(self):
        val = self.seek_slider.value()
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            container = av.open(path)
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            if total_sec > 0:
                ratio_step = 1.0 / total_sec
                new_ratio = min(1.0, (val / 1000.0) + ratio_step)
                self.seek_slider.setValue(int(new_ratio * 1000))
                self._seek_to_ratio(new_ratio)
        except Exception:
            pass
