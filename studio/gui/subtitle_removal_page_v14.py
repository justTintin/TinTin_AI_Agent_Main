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
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QSlider, QSplitter, QWidget, QTextEdit, QSizePolicy, QListWidget)
from PySide6.QtCore import Signal, QThread, Qt, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon
from utils.logger_utils import log
from utils.base_worker import BaseWorker
from config.paths import TMP_DIR, VSR_V14_DIR
from utils.platform_utils import python_binary

class SubtitleRemovalWorkerV14(QThread):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, vsr_python, vsr_script, video_path, boxes, mode, skip_detect, lama_fast, h264, preview_path, max_load_num=0):
        """
        :param boxes: list of (ymin, ymax, xmin, xmax) tuples
        :param max_load_num: STTN max frames per batch. 0 = use backend default (50).
        """
        super().__init__()
        self.vsr_python = vsr_python
        self.vsr_script = vsr_script
        self.video_path = video_path
        self.boxes = boxes
        self.mode = mode
        self.skip_detect = skip_detect
        self.lama_fast = lama_fast
        self.h264 = h264
        self.preview_path = preview_path
        self.max_load_num = max_load_num
        self.process = None
        self.is_aborted = False

    def run(self):
        num_boxes = len(self.boxes)
        if num_boxes == 0:
            self.finished.emit(False, "错误: 未指定任何字幕擦除选区。")
            return

        current_input = self.video_path
        temp_files_to_clean = []

        base_dir = os.path.dirname(self.video_path)
        vd_name = os.path.splitext(os.path.basename(self.video_path))[0]
        ext = os.path.splitext(self.video_path)[1].lower()
        is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]

        # Final output
        if is_pic:
            final_output = os.path.join(base_dir, "no_sub", f"{vd_name}{ext}")
        else:
            final_output = os.path.join(base_dir, f"{vd_name}_no_sub.mp4")

        self.is_aborted = False
        success = True
        err_msg = ""

        # Hide console window on Windows
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE

        for idx, box in enumerate(self.boxes):
            if self.is_aborted:
                success = False
                err_msg = "用户终止运行。"
                break

            ymin, ymax, xmin, xmax = box
            
            # Determine output path for this step
            if idx == num_boxes - 1:
                current_output = final_output
            else:
                suffix = ext
                current_output = os.path.join(TMP_DIR, f"vsr_temp_{idx}_{int(time.time())}{suffix}")
                temp_files_to_clean.append(current_output)

            cmd = [
                self.vsr_python,
                self.vsr_script,
                "--video", current_input,
                "--ymin", str(ymin),
                "--ymax", str(ymax),
                "--xmin", str(xmin),
                "--xmax", str(xmax),
                "--mode", self.mode,
                "--preview_path", self.preview_path,
                "--output", current_output
            ]
            if self.skip_detect:
                cmd.append("--skip_detect")
            if self.lama_fast:
                cmd.append("--lama_fast")
            if self.h264:
                cmd.append("--h264")
            if self.max_load_num > 0 and self.max_load_num != 50:
                cmd.extend(["--max_load_num", str(self.max_load_num)])

            self.status_updated.emit(f"正在处理第 {idx+1}/{num_boxes} 个字幕选区...")
            self.log_received.emit(f"\n[INFO] 开始处理选区 {idx+1}/{num_boxes}: (YMin={ymin}, YMax={ymax}, XMin={xmin}, XMax={xmax})")
            self.log_received.emit(f"[INFO] 执行后端命令: {' '.join(cmd)}")

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    startupinfo=startupinfo,
                    bufsize=1,
                    cwd=os.path.dirname(self.vsr_script),
                    env=dict(os.environ, QPT_MODE="Debug")
                )

                while self.process.poll() is None:
                    if self.is_aborted:
                        # 异步终止，不阻塞工作线程
                        try:
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            si.wShowWindow = 0
                            subprocess.Popen(
                                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                startupinfo=si
                            )
                        except Exception:
                            pass
                        break
                        
                    line = self.process.stdout.readline()
                    if not line:
                        continue
                    line = line.strip()
                    self.log_received.emit(line)
                    
                    if line.startswith("[PROGRESS]"):
                        try:
                            prog = int(line.split()[1])
                            # Overall progress calculation
                            overall_prog = int((idx * 100 + prog) / num_boxes)
                            self.progress_updated.emit(overall_prog)
                        except Exception:
                            pass
                    elif line.startswith("[STARTING]"):
                        self.status_updated.emit(f"AI 正在深度擦除第 {idx+1}/{num_boxes} 个选区字幕...")

                # Read remaining output
                for line in self.process.stdout:
                    line = line.strip()
                    self.log_received.emit(line)
                    if line.startswith("[PROGRESS]"):
                        try:
                            prog = int(line.split()[1])
                            overall_prog = int((idx * 100 + prog) / num_boxes)
                            self.progress_updated.emit(overall_prog)
                        except Exception:
                            pass

                ret_code = self.process.returncode
                if ret_code != 0:
                    success = False
                    err_msg = f"选区 {idx+1} 处理失败，错误码: {ret_code}"
                    break

                # Input of next step is output of current step
                current_input = current_output

            except Exception as e:
                success = False
                err_msg = f"处理选区 {idx+1} 时发生异常: {str(e)}"
                break

        # Cleanup intermediate temp files
        for fpath in temp_files_to_clean:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass

        if success:
            self.finished.emit(True, final_output)
        else:
            self.finished.emit(False, err_msg)

    def stop(self):
        self.is_aborted = True
        if self.process:
            try:
                # 异步运行 taskkill 防止 GUI 主线程卡死
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0 # SW_HIDE
                subprocess.Popen(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=startupinfo
                )
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


class InteractivePreviewLabelV14(QLabel):
    boundsChanged = Signal(int, int, int, int, int) # index, x, y, w, h
    selectionChanged = Signal(int) # active_index
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #0b1220; border-radius: 8px; border: 1px solid #2e2e32;")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        
        self.boxes = [] # Each item is a list: [x, y, w, h]
        self.active_box_index = -1
        
        self.frame_w = 0
        self.frame_h = 0
        
        self.target_w = 0
        self.target_h = 0
        self.px_offset_x = 0
        self.px_offset_y = 0
        
        self.drag_mode = None
        self.drag_start_pos = None
        self.drag_start_rect = None

    def sizeHint(self):
        return QSize(400, 300)

    def set_boxes(self, boxes, active_index):
        self.boxes = boxes
        self.active_box_index = active_index

    def get_handle_under_mouse(self, pos):
        if self.frame_w <= 0 or self.frame_h <= 0 or self.target_w <= 0 or self.target_h <= 0 or not self.boxes:
            return None, -1
            
        mx, my = pos.x(), pos.y()
        w_ratio = self.target_w / self.frame_w
        h_ratio = self.target_h / self.frame_h
        threshold = 10 # pixels
        
        # Check active box first
        box_indices = list(range(len(self.boxes)))
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            box_indices.remove(self.active_box_index)
            box_indices.insert(0, self.active_box_index)
            
        for idx in box_indices:
            x, y, w, h = self.boxes[idx]
            rx0 = self.px_offset_x + x * w_ratio
            ry0 = self.px_offset_y + y * h_ratio
            rx1 = self.px_offset_x + (x + w) * w_ratio
            ry1 = self.px_offset_y + (y + h) * h_ratio
            
            near_left = abs(mx - rx0) < threshold
            near_right = abs(mx - rx1) < threshold
            near_top = abs(my - ry0) < threshold
            near_bottom = abs(my - ry1) < threshold
            
            is_active = (idx == self.active_box_index)
            
            if is_active:
                if near_left and near_top:
                    return 'top-left', idx
                if near_right and near_top:
                    return 'top-right', idx
                if near_left and near_bottom:
                    return 'bottom-left', idx
                if near_right and near_bottom:
                    return 'bottom-right', idx
                    
                if near_left and ry0 <= my <= ry1:
                    return 'left', idx
                if near_right and ry0 <= my <= ry1:
                    return 'right', idx
                if near_top and rx0 <= mx <= rx1:
                    return 'top', idx
                if near_bottom and rx0 <= mx <= rx1:
                    return 'bottom', idx
            
            if rx0 < mx < rx1 and ry0 < my < ry1:
                return 'move', idx
                
        return None, -1

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle, idx = self.get_handle_under_mouse(event.pos())
            if handle is not None:
                if idx != self.active_box_index:
                    self.active_box_index = idx
                    self.selectionChanged.emit(idx)
                self.drag_mode = handle
                self.drag_start_pos = event.pos()
                self.drag_start_rect = list(self.boxes[idx])

    def mouseMoveEvent(self, event):
        if self.drag_mode is not None and self.drag_start_pos is not None and self.active_box_index >= 0:
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
                self.boxes[self.active_box_index] = [nx, ny, sw, sh]
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
                    
                self.boxes[self.active_box_index] = [x0, y0, x1 - x0, y1 - y0]
                
            bx = self.boxes[self.active_box_index]
            self.boundsChanged.emit(self.active_box_index, bx[0], bx[1], bx[2], bx[3])
        else:
            handle, idx = self.get_handle_under_mouse(event.pos())
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


class SubtitleRemovalPageV14(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.timer = None
        self.original_frame = None
        self.frame_width = 1280
        self.frame_height = 720
        self.preview_img_path = ""
        self.boxes = [] # List of [x, y, w, h] boxes
        self.active_box_index = -1

    def setup(self):
        tmp_dir = TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        self.preview_img_path = os.path.join(tmp_dir, "vsr_preview.jpg")

        # Page main layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(16)

        # Title
        heading = QLabel("视频去字幕")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        main_layout.addWidget(splitter, 1)

        # --- Left Panel: File Selection & Preview ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)

        # Select file card (top part of left side)
        select_card = QFrame()
        select_card.setObjectName("card")
        select_layout = QVBoxLayout(select_card)
        select_layout.setContentsMargins(16, 16, 16, 16)
        select_layout.setSpacing(10)

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
        select_layout.addLayout(inp_row)
        left_layout.addWidget(select_card, 0)

        # Video Preview card (bottom part of left side)
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        p_layout.setSpacing(10)

        p_title = QLabel("🖼️ 实时预览画面 (多选区: 绿框为当前选中，蓝框为其他选区):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title)

        self.preview_label = InteractivePreviewLabelV14()
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.selectionChanged.connect(self._on_label_selection_changed)
        self.preview_label.resized.connect(self.update_preview)
        p_layout.addWidget(self.preview_label, 1)

        # Video progress slider for scrubbing / previewing frames
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        
        button_style = """
            QPushButton {
                background-color: #1a1a24;
                color: #a1a1aa;
                border: 1px solid #2e2e38;
                border-radius: 4px;
                font-size: 11px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #2e2e38;
                color: #ffffff;
                border-color: #3b82f6;
            }
            QPushButton:disabled {
                background-color: #13131a;
                color: #4b5563;
                border-color: #1f2937;
            }
        """

        self.btn_prev_frame = QPushButton("◀")
        self.btn_prev_frame.setFixedWidth(30)
        self.btn_prev_frame.setStyleSheet(button_style)
        self.btn_prev_frame.clicked.connect(self._step_prev_frame)
        seek_row.addWidget(self.btn_prev_frame)
        
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #27272a;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #3b82f6;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #3b82f6;
                border: 2px solid #ffffff;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
        """)
        seek_row.addWidget(self.seek_slider)
        
        self.btn_next_frame = QPushButton("▶")
        self.btn_next_frame.setFixedWidth(30)
        self.btn_next_frame.setStyleSheet(button_style)
        self.btn_next_frame.clicked.connect(self._step_next_frame)
        seek_row.addWidget(self.btn_next_frame)
        
        self.lbl_seek_time = QLabel("00:00 / 00:00")
        self.lbl_seek_time.setFixedWidth(90)
        self.lbl_seek_time.setAlignment(Qt.AlignCenter)
        self.lbl_seek_time.setStyleSheet("""
            QLabel {
                font-family: 'Courier New', monospace;
                font-weight: bold;
                color: #3b82f6;
                background-color: #16161e;
                border: 1px solid #2e2e38;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }
        """)
        seek_row.addWidget(self.lbl_seek_time)

        p_layout.addLayout(seek_row)
        left_layout.addWidget(preview_card, 1)

        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        splitter.addWidget(left_widget)

        # --- Right Panel: Control Area & Processing Log ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_widget.setMinimumWidth(380)

        # Control card (top part of right side)
        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(0, 20, 0, 20)
        controls_layout.setSpacing(14)

        # Combined Subtitle Area Manager & Editor (Visual Design Optimized)
        box_manage_group = QFrame()
        box_manage_group.setObjectName("box_manage_group")
        box_manage_group.setStyleSheet("#box_manage_group { background-color: #26262a; border-top: 1px solid #2e2e32; border-bottom: 1px solid #2e2e32; border-radius: 0px; }")
        box_manage_layout = QVBoxLayout(box_manage_group)
        box_manage_layout.setContentsMargins(24, 16, 24, 16)
        box_manage_layout.setSpacing(14)

        # Header: Title (uses standard style)
        box_manage_title = QLabel("📦 字幕选区管理:")
        box_manage_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        box_manage_layout.addWidget(box_manage_title)

        # List Widget
        self.box_list_widget = QListWidget()
        self.box_list_widget.setMaximumHeight(95)
        self.box_list_widget.currentRowChanged.connect(self._on_box_list_row_changed)
        self.box_list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #28282c;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: white;
            }
        """)
        box_manage_layout.addWidget(self.box_list_widget)

        # Action Buttons
        btn_box_layout = QHBoxLayout()
        btn_box_layout.setSpacing(10)

        self.btn_add_box = QPushButton("➕ 添加选区")
        self.btn_add_box.setObjectName("secondary_button")
        self.btn_add_box.clicked.connect(self._add_box)
        btn_box_layout.addWidget(self.btn_add_box)

        self.btn_delete_box = QPushButton("➖ 删除选区")
        self.btn_delete_box.setObjectName("secondary_button")
        self.btn_delete_box.clicked.connect(self._delete_box)
        btn_box_layout.addWidget(self.btn_delete_box)

        box_manage_layout.addLayout(btn_box_layout)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("background-color: #2e2e32; max-height: 1px;")
        box_manage_layout.addWidget(sep)

        # Coordinate sliders
        sliders_layout = QVBoxLayout()
        sliders_layout.setSpacing(14)

        def create_slider_row(label_text, slider, val_lbl):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(100)
            row.addWidget(lbl)
            slider.setRange(0, 100)
            row.addWidget(slider)
            val_lbl.setStyleSheet("font-weight: bold; min-width: 30px;")
            row.addWidget(val_lbl)
            return row

        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.valueChanged.connect(self.update_preview)
        self.x_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始横坐标 X:", self.x_slider, self.x_val_lbl))

        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.valueChanged.connect(self.update_preview)
        self.w_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("字幕选区宽 W:", self.w_slider, self.w_val_lbl))

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("字幕选区高 H:", self.h_slider, self.h_val_lbl))

        box_manage_layout.addLayout(sliders_layout)
        controls_layout.addWidget(box_manage_group)

        # Options & action buttons (bottom of control card)
        bottom_container = QWidget()
        bottom_container_layout = QVBoxLayout(bottom_container)
        bottom_container_layout.setContentsMargins(24, 0, 24, 0)
        bottom_container_layout.setSpacing(14)

        # Algorithm selection
        algo_row = QHBoxLayout()
        algo_row.addWidget(QLabel("重绘填充算法:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("STTN 算法 (速度快，对真人视频好)", "sttn")
        self.mode_combo.addItem("Lama 算法 (效果强，对动画视频好)", "lama")
        self.mode_combo.addItem("ProPainter 算法 (显存要求极高，极剧烈运动)", "propainter")
        algo_row.addWidget(self.mode_combo)
        bottom_container_layout.addLayout(algo_row)

        # Checkboxes
        self.skip_detect_chk = QCheckBox("⏩ 切换为去水印模式 (跳过检测，对框选全区强制覆盖重绘)")
        self.skip_detect_chk.setToolTip(
            "【去字幕模式】(未勾选)：使用精准文字检测，只涂抹字幕笔画本身，保护背景，适合动态字幕。\n"
            "【去水印模式】(已勾选)：跳过文字检测直接重绘整个框选矩形区域，适合静态台标、LOGO水印。"
        )
        self.skip_detect_chk.setChecked(True)
        bottom_container_layout.addWidget(self.skip_detect_chk)

        self.lama_fast_chk = QCheckBox("⚡ LAMA极速模式 (直接擦除，忽略精细过渡)")
        self.lama_fast_chk.setChecked(False)
        bottom_container_layout.addWidget(self.lama_fast_chk)

        self.h264_chk = QCheckBox("📱 使用 H.264 兼容编码 (方便移动端/手机播放)")
        self.h264_chk.setChecked(True)
        bottom_container_layout.addWidget(self.h264_chk)

        # 服务端模式（默认开启：去字幕推理统一由算力服务端执行，本机无需部署算法包）
        server_row = QHBoxLayout()
        self.chk_server_mode = QCheckBox("☁️ 使用服务端处理（推荐，本机无需部署去字幕算法包）")
        self.chk_server_mode.setChecked(True)
        self.chk_server_mode.setStyleSheet("padding: 4px 8px;")
        server_row.addWidget(self.chk_server_mode)
        self.lbl_server_status = QLabel("")
        self.lbl_server_status.setObjectName("muted_text")
        server_row.addWidget(self.lbl_server_status)
        server_row.addStretch()
        bottom_container_layout.addLayout(server_row)

        # STTN batch size control (key for high-resolution videos)
        batch_row = QHBoxLayout()
        batch_lbl = QLabel("🎞️ STTN 每批处理帧数:")
        batch_lbl.setStyleSheet("font-size: 12px; color: #a1a1aa;")
        batch_row.addWidget(batch_lbl)
        from PySide6.QtWidgets import QSpinBox
        self.sttn_max_load_spinbox = QSpinBox()
        self.sttn_max_load_spinbox.setRange(5, 300)
        self.sttn_max_load_spinbox.setValue(50)
        self.sttn_max_load_spinbox.setSingleStep(5)
        self.sttn_max_load_spinbox.setToolTip(
            "控制 STTN 每批次处理的视频帧数。\n"
            "默认 50 帧，适用于 1080p 以下视频。\n"
            "处理 4K 或高分辨率视频时如崩溃，\n"
            "请将此值降低到 10~20（减少 GPU 显存占用）。"
        )
        self.sttn_max_load_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #1a1a24;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 12px;
                min-width: 60px;
            }
            QSpinBox:focus { border-color: #3b82f6; }
        """)
        batch_row.addWidget(self.sttn_max_load_spinbox)
        batch_hint = QLabel("帧  (4K视频建议10~20)")
        batch_hint.setStyleSheet("font-size: 11px; color: #71717a;")
        batch_row.addWidget(batch_hint)
        batch_row.addStretch()
        bottom_container_layout.addLayout(batch_row)

        bottom_container_layout.addStretch(1)

        # Status & progress
        self.status_lbl = QLabel("状态: 就绪")
        self.status_lbl.setObjectName("muted_text")
        bottom_container_layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #2e2e38;
                border-radius: 6px;
                background-color: #15151e;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: QLinearGradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 5px;
            }
        """)
        bottom_container_layout.addWidget(self.progress_bar)

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
        bottom_container_layout.addLayout(btn_action_layout)

        controls_layout.addWidget(bottom_container, 1)
        right_layout.addWidget(controls_card, 0)

        # Processing Log (bottom part of right side)
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel("📝 处理日志:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card, 1)  # ← log_card 加入右侧布局（修复：原来缺失此行）
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

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

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            # Initialize first default box
            self.boxes = [
                [
                    int(self.frame_width * 0.05),
                    int(self.frame_height * 0.78),
                    int(self.frame_width * 0.90),
                    int(self.frame_height * 0.21)
                ]
            ]
            self.active_box_index = 0
            self._update_box_list_widget()
            
            # Force layout activation & events processing to quickly determine correct preview size
            if self.parent_widget.layout():
                self.parent_widget.layout().activate()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            self.update_preview()
            
            # Schedule a short deferred update as well
            QTimer.singleShot(50, self.update_preview)
        except Exception as e:
            log.error(f"Failed to load video preview: {e}")
            self.original_frame = None
            self.preview_label.setText(f"预览加载失败: {e}")

    def _update_box_list_widget(self):
        self.box_list_widget.blockSignals(True)
        self.box_list_widget.clear()
        for idx, box in enumerate(self.boxes):
            x, y, w, h = box
            self.box_list_widget.addItem(f"选区 {idx+1}: X={x}, Y={y}, W={w}, H={h}")
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            self.box_list_widget.setCurrentRow(self.active_box_index)
        self.box_list_widget.blockSignals(False)
        self._sync_sliders_to_active_box()

    def _sync_sliders_to_active_box(self):
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            x, y, w, h = self.boxes[self.active_box_index]
            
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

            self.btn_delete_box.setEnabled(len(self.boxes) > 1)
        else:
            self.btn_delete_box.setEnabled(False)

    def _on_box_list_row_changed(self, row):
        if row >= 0 and row < len(self.boxes):
            self.active_box_index = row
            self._sync_sliders_to_active_box()
            self.update_preview()

    def _add_box(self):
        if not self.video_path_input.text().strip() or self.original_frame is None:
            return
            
        default_box = [
            int(self.frame_width * 0.05),
            int(self.frame_height * 0.78),
            int(self.frame_width * 0.90),
            int(self.frame_height * 0.21)
        ]
        
        if self.boxes:
            last_box = self.boxes[-1]
            default_box[0] = last_box[0]
            default_box[2] = last_box[2]
            # Shift vertically upwards slightly so it doesn't overlap completely
            default_box[1] = max(0, last_box[1] - 40)
            default_box[3] = last_box[3]
            
        self.boxes.append(default_box)
        self.active_box_index = len(self.boxes) - 1
        self._update_box_list_widget()
        self.update_preview()

    def _delete_box(self):
        if len(self.boxes) <= 1:
            return
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            self.boxes.pop(self.active_box_index)
            self.active_box_index = min(self.active_box_index, len(self.boxes) - 1)
            self._update_box_list_widget()
            self.update_preview()

    def update_preview(self):
        if self.worker and self.worker.isRunning():
            return
            
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            x = self.x_slider.value()
            w = self.w_slider.value()
            y = self.y_slider.value()
            h = self.h_slider.value()

            # Update text labels
            self.x_val_lbl.setText(str(x))
            self.w_val_lbl.setText(str(w))
            self.y_val_lbl.setText(str(y))
            self.h_val_lbl.setText(str(h))

            # Update active box
            self.boxes[self.active_box_index] = [x, y, w, h]
            
            # Update list item text quietly
            self.box_list_widget.blockSignals(True)
            item = self.box_list_widget.item(self.active_box_index)
            if item:
                item.setText(f"选区 {self.active_box_index+1}: X={x}, Y={y}, W={w}, H={h}")
            self.box_list_widget.blockSignals(False)

        # Pass boxes to interactive label
        self.preview_label.set_boxes(self.boxes, self.active_box_index)

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

            self.preview_label.target_w = target_w
            self.preview_label.target_h = target_h
            self.preview_label.px_offset_x = (display_w - target_w) // 2
            self.preview_label.px_offset_y = (display_h - target_h) // 2

            # PIL resize
            resized_img = self.original_frame.resize((target_w, target_h), Image.Resampling.LANCZOS)

            # Draw all bounding boxes
            draw = ImageDraw.Draw(resized_img)
            for idx, box in enumerate(self.boxes):
                bx, by, bw, bh = box
                rx0 = int(bx * target_w / w_img)
                ry0 = int(by * target_h / h_img)
                rx1 = int((bx + bw) * target_w / w_img)
                ry1 = int((by + bh) * target_h / h_img)
                
                if idx == self.active_box_index:
                    draw.rectangle([rx0, ry0, rx1, ry1], outline="#00ff00", width=3)
                else:
                    draw.rectangle([rx0, ry0, rx1, ry1], outline="#00ffff", width=2)

            # Convert to QImage
            rgb_img = resized_img.convert("RGB")
            data = rgb_img.tobytes("raw", "RGB")
            qImg = QImage(data, target_w, target_h, target_w * 3, QImage.Format_RGB888)
            self.preview_label.setPixmap(QPixmap.fromImage(qImg))

    def _on_label_bounds_changed(self, idx, x, y, w, h):
        self.active_box_index = idx
        self.boxes[idx] = [x, y, w, h]
        
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
        
        # Update list item text quietly
        self.box_list_widget.blockSignals(True)
        item = self.box_list_widget.item(idx)
        if item:
            item.setText(f"选区 {idx+1}: X={x}, Y={y}, W={w}, H={h}")
        self.box_list_widget.setCurrentRow(idx)
        self.box_list_widget.blockSignals(False)
        
        self.update_preview()

    def _on_label_selection_changed(self, idx):
        self.active_box_index = idx
        self.box_list_widget.blockSignals(True)
        self.box_list_widget.setCurrentRow(idx)
        self.box_list_widget.blockSignals(False)
        self._sync_sliders_to_active_box()

    def start_removal(self):
        video_path = self.video_path_input.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "参数错误", "请先选择有效的输入视频或图片！")
            return

        if not self.boxes:
            QMessageBox.warning(self.parent_widget, "参数错误", "请先设置至少一个擦除选区！")
            return

        # 服务端模式：上传 → 服务端去字幕 → 下载结果到本地
        if getattr(self, "chk_server_mode", None) is not None and self.chk_server_mode.isChecked():
            self._start_remote_removal(video_path)
            return

        vsr_dir = VSR_V14_DIR
        vsr_python = os.path.join(vsr_dir, "Python", python_binary())
        # QPT 打包的嵌入式 Python 没有 Scripts/ 子目录，python.exe 直接在 Python/ 下
        if not os.path.exists(vsr_python):
            vsr_python = os.path.join(vsr_dir, "Python", "python.exe")
        vsr_script = os.path.join(vsr_dir, "vsr_run.py")

        if not os.path.exists(vsr_python) or not os.path.exists(vsr_script):
            QMessageBox.critical(
                self.parent_widget,
                "文件丢失",
                f"未能定位到 1.4 去字幕包的 Python 环境或脚本，请检查：\n\n{vsr_dir}"
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
        self.btn_add_box.setEnabled(False)
        self.btn_delete_box.setEnabled(False)
        self.box_list_widget.setEnabled(False)
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

        # Convert [x, y, w, h] to (ymin, ymax, xmin, xmax) for the backend
        worker_boxes = []
        for box in self.boxes:
            bx, by, bw, bh = box
            worker_boxes.append((by, by + bh, bx, bx + bw))

        # Instantiate background worker
        self.worker = SubtitleRemovalWorkerV14(
            vsr_python=vsr_python,
            vsr_script=vsr_script,
            video_path=video_path,
            boxes=worker_boxes,
            mode=self.mode_combo.currentData(),
            skip_detect=self.skip_detect_chk.isChecked(),
            lama_fast=self.lama_fast_chk.isChecked(),
            h264=self.h264_chk.isChecked(),
            preview_path=self.preview_img_path,
            max_load_num=self.sttn_max_load_spinbox.value()
        )
        self.worker.progress_updated.connect(self.on_worker_progress)
        self.worker.status_updated.connect(self.on_worker_status)
        self.worker.log_received.connect(self.on_worker_log)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

        # Timer to poll preview frames from file (runs every 400ms)
        self.timer = QTimer()
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll_preview_image)
        self.timer.start()

    def _start_remote_removal(self, video_path):
        """使用服务端 API 去除字幕（上传 → 轮询 → 下载结果到本地）。"""
        # v14 本地算法名 → 服务端 inpaint_mode（sttn 映射为 sttn_auto 自动检测模式）
        mode = self.mode_combo.currentData() or "sttn"
        if mode == "sttn":
            mode = "sttn_auto"

        # boxes 为 [x, y, w, h]，转为服务端 (ymin, ymax, xmin, xmax)
        sub_areas = [(by, by + bh, bx, bx + bw) for (bx, by, bw, bh) in self.boxes]

        self.btn_start.setEnabled(False)
        self.chk_server_mode.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.log_view.clear()
        self.lbl_server_status.setText("⏳ 上传中...")

        stem, _ = os.path.splitext(video_path)
        out_path = f"{stem}_no_sub.mp4"

        class _RemoteVSRWorkerV14(BaseWorker):
            finished = Signal(str)
            error = Signal(str)
            stage = Signal(str)

            def __init__(self, path, mode, sub_areas, out_path):
                super().__init__()
                self.path = path
                self.mode = mode
                self.sub_areas = sub_areas
                self.out_path = out_path

            def do_work(self):
                try:
                    from utils.vsr_client import vsr_remove_remote
                    result = vsr_remove_remote(
                        self.path,
                        inpaint_mode=self.mode,
                        sub_areas=self.sub_areas,
                        out_path=self.out_path,
                        progress_cb=lambda t: self.stage.emit(t),
                    )
                    self.finished.emit(result)
                except Exception as e:
                    self.error.emit(str(e))

        w = _RemoteVSRWorkerV14(video_path, mode, sub_areas, out_path)
        self._remote_worker = w
        w.stage.connect(lambda t: self.lbl_server_status.setText(t))
        w.finished.connect(lambda p: self._on_remote_done(p))
        w.error.connect(lambda msg: self._on_remote_error(msg))
        w.start()

    def _on_remote_done(self, out_path):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_server_status.setText("✅ 处理完成")
        self.btn_start.setEnabled(True)
        self.chk_server_mode.setEnabled(True)
        self.status_lbl.setText("状态: 字幕擦除完毕！")

        msg_box = QMessageBox(self.parent_widget)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("去字幕完成")
        msg_box.setText(f"视频去字幕已完成！\n结果已保存至：\n\n{out_path}")
        open_btn = msg_box.addButton("打开文件夹", QMessageBox.ActionRole)
        msg_box.addButton("确定", QMessageBox.AcceptRole)
        msg_box.exec()
        if msg_box.clickedButton() == open_btn:
            try:
                import subprocess
                subprocess.Popen(f'explorer /select,"{os.path.normpath(out_path)}"')
            except Exception as e:
                log.error(f"打开输出目录失败: {e}")
        self.update_preview()

    def _on_remote_error(self, msg):
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_server_status.setText(f"❌ 失败: {str(msg)[:80]}")
        self.btn_start.setEnabled(True)
        self.chk_server_mode.setEnabled(True)
        QMessageBox.critical(self.parent_widget, "错误", f"服务端处理失败:\n{msg}")

    def stop_removal(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_lbl.setText("状态: 正在终止中，请稍候...")
            self.log_view.append("\n[WARN] 已发出停止指令，等待引擎退出...") 
            # 不在这里调用 cleanup_ui()，等 worker 的 finished 信号触发 on_worker_finished 统一处理

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
            
            msg_box = QMessageBox(self.parent_widget)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setWindowTitle("去字幕成功")
            msg_box.setText(f"字幕擦除并画面重绘成功！\n新生成的媒体文件已保存至：\n\n{out_path}")
            
            open_btn = msg_box.addButton("打开文件夹", QMessageBox.ActionRole)
            ok_btn = msg_box.addButton("确定", QMessageBox.AcceptRole)
            
            msg_box.exec()
            
            if msg_box.clickedButton() == open_btn:
                try:
                    import subprocess
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(out_path)}"')
                except Exception as e:
                    log.error(f"Failed to open output directory: {e}")

            # Restore original video preview with selection boxes overlaid
            self.update_preview()
        else:
            if self.worker and self.worker.is_aborted:
                self.status_lbl.setText("状态: 已被用户终止。")
                self.update_preview()
                return

            self.status_lbl.setText(f"状态: 出错。")
            QMessageBox.critical(
                self.parent_widget,
                "处理失败",
                f"去字幕执行过程中发生错误：\n\n{out_path}"
            )
            # Restore original preview on failure as well
            self.update_preview()

    def poll_preview_image(self):
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
        self.btn_add_box.setEnabled(True)
        self.btn_delete_box.setEnabled(len(self.boxes) > 1)
        self.box_list_widget.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.skip_detect_chk.setEnabled(True)
        self.lama_fast_chk.setEnabled(True)
        self.h264_chk.setEnabled(True)
        self.progress_bar.setValue(0)

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
                
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            
            if frame_found:
                self.update_preview()
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
