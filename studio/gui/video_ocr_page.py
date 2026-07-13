# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import traceback
import time
from PIL import Image, ImageDraw

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QSlider, QSplitter, QWidget, QTextEdit, QSizePolicy, QListWidget)
from PySide6.QtCore import Signal, QThread, Qt, QTimer, QSize
from utils.base_worker import BaseWorker
from PySide6.QtGui import QImage, QPixmap, QIcon
from utils.logger_utils import log
from config.paths import TMP_DIR, VSR_V14_DIR, OUTPUTS_DIR, PADDLEOCR_PYTHON, PADDLEOCR_SCRIPT

class VideoOcrWorker(BaseWorker):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str) # success, output_path_or_error

    def __init__(self, vsr_python, ocr_script, video_path, box, sample_interval, filter_mode, output_path, preview_path):
        """
        :param box: list of (ymin, ymax, xmin, xmax)
        """
        super().__init__()
        self.vsr_python = vsr_python
        self.ocr_script = ocr_script
        self.video_path = video_path
        self.box = box
        self.sample_interval = sample_interval
        self.filter_mode = filter_mode
        self.output_path = output_path
        self.preview_path = preview_path
        self.process = None
        self.is_aborted = False

    def run(self):
        ymin, ymax, xmin, xmax = self.box
        
        cmd = [
            self.vsr_python,
            self.ocr_script,
            "--video", self.video_path,
            "--ymin", str(ymin),
            "--ymax", str(ymax),
            "--xmin", str(xmin),
            "--xmax", str(xmax),
            "--sample_interval", str(self.sample_interval),
            "--filter_mode", self.filter_mode,
            "--preview_path", self.preview_path,
            "--output", self.output_path
        ]

        self.status_updated.emit("正在初始化 OCR 推理引擎...")
        self.log_received.emit(f"[INFO] 开始 OCR 识别任务")
        self.log_received.emit(f"[INFO] 视频文件: {self.video_path}")
        self.log_received.emit(f"[INFO] 框选选区: YMin={ymin}, YMax={ymax}, XMin={xmin}, XMax={xmax}")
        self.log_received.emit(f"[INFO] 执行后端命令: {' '.join(cmd)}")

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE

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
                cwd=os.path.dirname(self.ocr_script)
            )

            while self.process.poll() is None:
                if self.is_aborted:
                    self.process.terminate()
                    break
                    
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
                    self.status_updated.emit("OCR 引擎启动中...")
                elif line.startswith("[OCR]"):
                    self.status_updated.emit(f"正在识别中: {line.split('|')[-2].strip()}")

            # Read remaining stdout
            for line in self.process.stdout:
                line = line.strip()
                self.log_received.emit(line)
                if line.startswith("[PROGRESS]"):
                    try:
                        prog = int(line.split()[1])
                        self.progress_updated.emit(prog)
                    except Exception:
                        pass

            ret_code = self.process.returncode
            if self.is_aborted:
                self.finished.emit(False, "用户终止运行。")
            elif ret_code == 0:
                self.finished.emit(True, self.output_path)
            else:
                self.finished.emit(False, f"OCR 进程退出异常，错误码: {ret_code}")

        except Exception as e:
            self.finished.emit(False, f"执行 OCR 时发生异常: {str(e)}")

    def stop(self):
        self.is_aborted = True
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


class InteractivePreviewLabelOCR(QLabel):
    boundsChanged = Signal(int, int, int, int) # x, y, w, h
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #0b1220; border-radius: 8px; border: 1px solid #2e2e32;")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        
        self.box = [0, 0, 0, 0] # [x, y, w, h]
        
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

    def set_box(self, box):
        self.box = box

    def get_handle_under_mouse(self, pos):
        if self.frame_w <= 0 or self.frame_h <= 0 or self.target_w <= 0 or self.target_h <= 0 or not self.box:
            return None
            
        mx, my = pos.x(), pos.y()
        w_ratio = self.target_w / self.frame_w
        h_ratio = self.target_h / self.frame_h
        threshold = 10 # px threshold for grab handle
        
        x, y, w, h = self.box
        rx0 = self.px_offset_x + x * w_ratio
        ry0 = self.px_offset_y + y * h_ratio
        rx1 = self.px_offset_x + (x + w) * w_ratio
        ry1 = self.px_offset_y + (y + h) * h_ratio
        
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
                self.drag_start_rect = list(self.box)

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
                self.box = [nx, ny, sw, sh]
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
                    
                self.box = [x0, y0, x1 - x0, y1 - y0]
                
            self.boundsChanged.emit(self.box[0], self.box[1], self.box[2], self.box[3])
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


class VideoOcrPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.original_frame = None
        self.frame_width = 1280
        self.frame_height = 720
        self.preview_img_path = ""
        self.box = [0, 0, 0, 0] # [x, y, w, h]

    def setup(self):
        tmp_dir = TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        self.preview_img_path = os.path.join(tmp_dir, "ocr_roi_preview.jpg")

        # Main Page layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(16)

        # Title Header
        heading = QLabel("🔍 视频框选 OCR 扫描识别")
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
        card_layout.setContentsMargins(0, 20, 0, 20)
        card_layout.setSpacing(14)

        # Video picker
        inp_container = QWidget()
        inp_container_layout = QVBoxLayout(inp_container)
        inp_container_layout.setContentsMargins(24, 0, 24, 0)
        inp_container_layout.setSpacing(14)

        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("选择输入视频:"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("请选择 .mp4/.avi/.mov 视频文件...")
        self.video_path_input.textChanged.connect(self._on_video_path_changed)
        inp_row.addWidget(self.video_path_input)
        btn_sel = QPushButton("浏览")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_video)
        inp_row.addWidget(btn_sel)
        inp_container_layout.addLayout(inp_row)
        card_layout.addWidget(inp_container)

        # Bounding box selection controls
        box_manage_group = QFrame()
        box_manage_group.setObjectName("box_manage_group")
        box_manage_group.setStyleSheet("#box_manage_group { background-color: #26262a; border-top: 1px solid #2e2e32; border-bottom: 1px solid #2e2e32; border-radius: 0px; }")
        box_manage_layout = QVBoxLayout(box_manage_group)
        box_manage_layout.setContentsMargins(24, 16, 24, 16)
        box_manage_layout.setSpacing(14)
        
        box_manage_title = QLabel("📦 OCR 识别区域坐标设置:")
        box_manage_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        box_manage_layout.addWidget(box_manage_title)

        # Coordinate Sliders
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

        # X Slider
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.valueChanged.connect(self.update_preview)
        self.x_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始横坐标 X:", self.x_slider, self.x_val_lbl))

        # W Slider
        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.valueChanged.connect(self.update_preview)
        self.w_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("识别区域宽 W:", self.w_slider, self.w_val_lbl))

        # Y Slider
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))

        # H Slider
        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("识别区域高 H:", self.h_slider, self.h_val_lbl))

        box_manage_layout.addLayout(sliders_layout)
        card_layout.addWidget(box_manage_group)

        # Options Container
        bottom_container = QWidget()
        bottom_container_layout = QVBoxLayout(bottom_container)
        bottom_container_layout.setContentsMargins(24, 0, 24, 0)
        bottom_container_layout.setSpacing(14)

        # OCR Filter Options
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("文字过滤模式:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("识别区域内所有文本 (All)", "all")
        self.filter_combo.addItem("仅提取数字与数值 (如温度、计数等)", "numeric")
        filter_row.addWidget(self.filter_combo)
        bottom_container_layout.addLayout(filter_row)

        # Sample rate selection
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("帧扫描间隔:"))
        self.rate_combo = QComboBox()
        self.rate_combo.addItem("逐帧扫描 (最慢, 最精准)", 1)
        self.rate_combo.addItem("每隔 2 帧扫描", 2)
        self.rate_combo.addItem("每隔 5 帧扫描 (推荐)", 5)
        self.rate_combo.addItem("每隔 10 帧扫描", 10)
        self.rate_combo.addItem("每隔 30 帧扫描 (最快)", 30)
        self.rate_combo.setCurrentIndex(2) # Default 5 frames
        rate_row.addWidget(self.rate_combo)
        bottom_container_layout.addLayout(rate_row)

        # Excel output info details
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出保存路径:"))
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("默认输出到 outputs 目录...")
        out_row.addWidget(self.output_path_input)
        bottom_container_layout.addLayout(out_row)

        # Status & Progress bar
        self.status_lbl = QLabel("状态: 就绪")
        self.status_lbl.setObjectName("muted_text")
        bottom_container_layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bottom_container_layout.addWidget(self.progress_bar)

        # Start / Stop Buttons
        btn_action_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始 OCR 扫描")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_ocr_scan)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_ocr_scan)
        btn_action_layout.addWidget(self.btn_stop)

        self.chk_server_ocr = QCheckBox("使用服务端OCR")
        self.chk_server_ocr.setToolTip("勾选后上传图片到服务端识别")
        btn_action_layout.addWidget(self.chk_server_ocr)
        btn_action_layout.addStretch()
        bottom_container_layout.addLayout(btn_action_layout)

        card_layout.addWidget(bottom_container, 1)
        left_layout.addWidget(card)
        left_widget.setMaximumWidth(450)
        splitter.addWidget(left_widget)

        # --- Right Panel: Video preview + Log Viewer ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(14)

        # Preview Label Card
        preview_card = QFrame()
        preview_card.setObjectName("card")
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        
        p_title = QLabel("🖼️ 实时预览画面 (在画面上拖拽选择需要 OCR 的框):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title)

        self.preview_label = InteractivePreviewLabelOCR()
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

        # Console logs output card
        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel("📝 OCR 扫描引擎实时日志与识别数据:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(180)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card)

        # System model prompt
        help_card = QFrame()
        help_card.setObjectName("card")
        help_layout = QVBoxLayout(help_card)
        help_card.setContentsMargins(16, 12, 16, 12)
        help_lbl = QLabel(
            "💡 **大模型与本地 OCR 提示**:\n"
            "PaddleOCR 使用本地内置的深度学习模型进行文本提取，完全免费且离线运行，**不需要下载大语言模型 (LLM)**。 "
            "权重会自动从百度官方国内镜像下载。\n"
            "如果您需要更高级的提取功能（如将识别数据翻译、分类或交给大模型分析），请使用主菜单的 **「🤖 大模型配置」** 页面来接入国内主流大模型 API 服务。"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("font-size: 11px; line-height: 16px; color: #a1a1aa;")
        help_layout.addWidget(help_lbl)
        right_layout.addWidget(help_card)

        splitter.addWidget(right_widget)

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择输入视频文件",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)"
        )
        if path:
            self.video_path_input.setText(path)

    def _on_video_path_changed(self, path):
        path = path.strip()
        if not path or not os.path.exists(path):
            self.original_frame = None
            self.preview_label.clear()
            self.preview_label.setText("请选择有效的视频文件")
            self.seek_slider.setEnabled(False)
            self.seek_slider.setValue(0)
            self.lbl_seek_time.setText("00:00 / 00:00")
            self.btn_prev_frame.setEnabled(False)
            self.btn_next_frame.setEnabled(False)
            return

        try:
            import av
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

            # Set default bounding box ROI (e.g. center box)
            self.box = [
                int(self.frame_width * 0.25),
                int(self.frame_height * 0.25),
                int(self.frame_width * 0.50),
                int(self.frame_height * 0.50)
            ]

            # Adjust slider ranges
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

            self._sync_sliders_to_box()
            self.update_preview()
            
            # Set default output path
            vd_name = os.path.splitext(os.path.basename(path))[0]
            default_out = os.path.join(OUTPUTS_DIR, f"{vd_name}_ocr_result.csv")
            self.output_path_input.setText(default_out)

        except Exception as e:
            log.error(f"加载视频预览失败: {e}")
            self.original_frame = None
            self.preview_label.setText(f"视频预览加载失败: {e}")
            self.seek_slider.setEnabled(False)
            self.seek_slider.setValue(0)
            self.lbl_seek_time.setText("00:00 / 00:00")
            self.btn_prev_frame.setEnabled(False)
            self.btn_next_frame.setEnabled(False)

    def _sync_sliders_to_box(self):
        x, y, w, h = self.box
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

    def update_preview(self):
        if self.worker and self.worker.isRunning():
            return
            
        x = self.x_slider.value()
        w = self.w_slider.value()
        y = self.y_slider.value()
        h = self.h_slider.value()

        # Constraints
        if x + w > self.frame_width:
            w = self.frame_width - x
            self.w_slider.setValue(w)
        if y + h > self.frame_height:
            h = self.frame_height - y
            self.h_slider.setValue(h)

        self.x_val_lbl.setText(str(x))
        self.w_val_lbl.setText(str(w))
        self.y_val_lbl.setText(str(y))
        self.h_val_lbl.setText(str(h))

        self.box = [x, y, w, h]
        self.preview_label.set_box(self.box)

        if self.original_frame is not None:
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

            resized_img = self.original_frame.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            # Draw green bounding box on image
            draw = ImageDraw.Draw(resized_img)
            rx0 = int(x * target_w / w_img)
            ry0 = int(y * target_h / h_img)
            rx1 = int((x + w) * target_w / w_img)
            ry1 = int((y + h) * target_h / h_img)
            draw.rectangle([rx0, ry0, rx1, ry1], outline="#00ff00", width=3)

            rgb_img = resized_img.convert("RGB")
            data = rgb_img.tobytes("raw", "RGB")
            qImg = QImage(data, target_w, target_h, target_w * 3, QImage.Format_RGB888)
            self.preview_label.setPixmap(QPixmap.fromImage(qImg))

    def _on_label_bounds_changed(self, x, y, w, h):
        self.box = [x, y, w, h]
        self._sync_sliders_to_box()
        self.update_preview()

    def start_ocr_scan(self):
        video_path = self.video_path_input.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "错误", "请先选择有效的输入视频。")
            return

        out_path = self.output_path_input.text().strip()
        if not out_path:
            QMessageBox.warning(self.parent_widget, "错误", "请指定输出 CSV 保存路径。")
            return

        vsr_python = PADDLEOCR_PYTHON
        ocr_script = PADDLEOCR_SCRIPT

        if not os.path.exists(vsr_python) or not os.path.exists(ocr_script):
            QMessageBox.warning(
                self.parent_widget,
                "环境未就绪",
                "未检测到 PaddleOCR 专属运行环境，请先前往「🤖 大模型配置」或「⚙️ 环境配置」菜单下一键部署创建专属环境！"
            )
            return

        # Get settings
        sample_interval = self.rate_combo.currentData()
        filter_mode = self.filter_combo.currentData()
        
        # Bounding box is in ymin, ymax, xmin, xmax
        x, y, w, h = self.box
        ymin = y
        ymax = y + h
        xmin = x
        xmax = x + w
        box_tuple = (ymin, ymax, xmin, xmax)

        self.log_view.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.video_path_input.setEnabled(False)
        self.output_path_input.setEnabled(False)
        self.x_slider.setEnabled(False)
        self.w_slider.setEnabled(False)
        self.y_slider.setEnabled(False)
        self.h_slider.setEnabled(False)
        self.seek_slider.setEnabled(False)
        self.btn_prev_frame.setEnabled(False)
        self.btn_next_frame.setEnabled(False)

        # Spawn worker
        self.worker = VideoOcrWorker(
            vsr_python=vsr_python,
            ocr_script=ocr_script,
            video_path=video_path,
            box=box_tuple,
            sample_interval=sample_interval,
            filter_mode=filter_mode,
            output_path=out_path,
            preview_path=self.preview_img_path
        )
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.status_updated.connect(self.status_lbl.setText)
        self.worker.log_received.connect(self._append_log)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.start()

    def _append_log(self, text):
        self.log_view.append(text)
        # Move cursor to end
        self.log_view.moveCursor(self.log_view.textCursor().End)

    def stop_ocr_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.btn_stop.setEnabled(False)

    def on_scan_finished(self, success, result):
        self.progress_bar.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.video_path_input.setEnabled(True)
        self.output_path_input.setEnabled(True)
        self.x_slider.setEnabled(True)
        self.w_slider.setEnabled(True)
        self.y_slider.setEnabled(True)
        self.h_slider.setEnabled(True)
        
        # Restore seek controls
        video_path = self.video_path_input.text().strip()
        self.seek_slider.setEnabled(bool(video_path))
        self.btn_prev_frame.setEnabled(bool(video_path))
        self.btn_next_frame.setEnabled(bool(video_path))

        if success:
            self.status_lbl.setText("状态: 扫描识别已完成！")
            QMessageBox.information(
                self.parent_widget, 
                "任务成功", 
                f"视频 OCR 框选扫描已全部完成！\n\n结果已输出至电子表格：\n{result}"
            )
            # Try to select the output file in explorer
            try:
                subprocess.Popen(f'explorer /select,"{os.path.normpath(result)}"')
            except Exception:
                pass
        else:
            self.status_lbl.setText(f"状态: OCR 识别中断或出错。")
            QMessageBox.critical(self.parent_widget, "扫描失败", f"OCR 扫描失败：\n{result}")

    def _seek_to_ratio(self, ratio):
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
            
        try:
            import av
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
            import av
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
            import av
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
