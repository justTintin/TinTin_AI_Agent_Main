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
from config.paths import TMP_DIR, VSR_V14_DIR, OUTPUTS_DIR
from utils.ocr_client import check_server_ocr
from utils.ocr_workers import VideoOcrWorker


from utils.file_dialog_utils import pick_file
from gui.elided_label import ElidedLabel
from utils.gui_icons import mdi_button
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
        # Main Page layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Title Header
        heading = QLabel(" 视频框选 OCR 扫描识别")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        main_layout.addWidget(splitter, 1)

        # ─── Left Panel (Video Picker & Preview) ───
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(16)

        # Card 1: Video Picker
        inp_card = QFrame()
        inp_card.setObjectName("card")
        inp_layout = QVBoxLayout(inp_card)
        inp_card.setContentsMargins(16, 16, 16, 16)
        inp_layout.setSpacing(10)

        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("选择输入视频:"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("请选择 .mp4/.avi/.mov 视频文件...")
        self.video_path_input.textChanged.connect(self._on_video_path_changed)
        inp_row.addWidget(self.video_path_input)
        btn_sel = mdi_button("浏览", "folder")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_video)
        inp_row.addWidget(btn_sel)
        inp_layout.addLayout(inp_row)
        left_layout.addWidget(inp_card, 0)

        # Card 2: Interactive Preview Card (Expanding to bottom)
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        p_layout.setSpacing(10)

        p_title = QLabel(" 实时预览画面 (在画面上拖拽选择需要 OCR 的框):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title, 0)

        self.preview_label = InteractivePreviewLabelOCR()
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.resized.connect(self.update_preview)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout.addWidget(self.preview_label, 1)

        # Video progress slider for scrubbing
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
        
        self.btn_next_frame = QPushButton("播放")
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
        splitter.addWidget(left_widget)

        # ─── Right Panel (Controls Card & Logs Card) ───
        right_widget = QWidget()
        right_widget.setMinimumWidth(380)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(16)

        # Card 1: Controls Card
        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(0, 16, 0, 16)
        controls_layout.setSpacing(14)

        # Title
        c_title = QLabel(" OCR 模板识别选区及设置")
        c_title.setStyleSheet("font-weight: bold; font-size: 14px; padding-left: 20px; color: #3b82f6;")
        controls_layout.addWidget(c_title)

        # Bounding Box Sliders Group
        box_group = QWidget()
        box_layout = QVBoxLayout(box_group)
        box_layout.setContentsMargins(20, 0, 20, 0)
        box_layout.setSpacing(12)

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
        box_layout.addLayout(create_slider_row("起始横坐标 X:", self.x_slider, self.x_val_lbl))

        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.valueChanged.connect(self.update_preview)
        self.w_val_lbl = QLabel("1")
        box_layout.addLayout(create_slider_row("识别区域宽 W:", self.w_slider, self.w_val_lbl))

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        box_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        box_layout.addLayout(create_slider_row("识别区域高 H:", self.h_slider, self.h_val_lbl))

        controls_layout.addWidget(box_group)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("background-color: #2e2e32; max-height: 1px;")
        controls_layout.addWidget(sep)

        # Options layout
        options_widget = QWidget()
        options_layout = QVBoxLayout(options_widget)
        options_layout.setContentsMargins(20, 0, 20, 0)
        options_layout.setSpacing(12)

        # OCR Filter Options
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("文字过滤模式:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("识别区域内所有文本 (All)", "all")
        self.filter_combo.addItem("仅提取数字与数值 (如温度、计数等)", "numeric")
        filter_row.addWidget(self.filter_combo)
        options_layout.addLayout(filter_row)

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
        options_layout.addLayout(rate_row)

        # Excel output info details
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出保存路径:"))
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("默认输出到 outputs 目录...")
        out_row.addWidget(self.output_path_input)
        options_layout.addLayout(out_row)

        # Status & Progress bar
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("muted_text")
        options_layout.addWidget(self.status_lbl)

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
        options_layout.addWidget(self.progress_bar)

        # Start / Stop Buttons
        btn_action_layout = QHBoxLayout()
        self.btn_start = QPushButton(" 开始 OCR 扫描")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_ocr_scan)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_ocr_scan)
        btn_action_layout.addWidget(self.btn_stop)
        options_layout.addLayout(btn_action_layout)

        controls_layout.addWidget(options_widget)
        right_layout.addWidget(controls_card, 0)

        # Card 2: Logs Viewer
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel(" OCR 扫描引擎实时日志与识别数据:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card, 1)

        # System model prompt
        help_card = QFrame()
        help_card.setObjectName("card")
        help_layout = QVBoxLayout(help_card)
        help_card.setContentsMargins(16, 12, 16, 12)
        help_lbl = ElidedLabel(
            " **大模型与本地 OCR 提示**:\n"
            "PaddleOCR 使用本地内置的深度学习模型进行文本提取，完全免费且离线运行，**不需要下载大语言模型 (LLM)**。 "
            "权重会自动从百度官方国内镜像下载。\n"
            "如果您需要更高级的提取功能（如将识别数据翻译、分类或交给大模型分析），请使用主菜单的 **「 大模型配置」** 页面来接入国内主流大模型 API 服务。",
            max_lines=2,
        )
        help_lbl.setStyleSheet("font-size: 11px; line-height: 16px; color: #a1a1aa;")
        help_layout.addWidget(help_lbl)
        right_layout.addWidget(help_card)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

    def _select_video(self):
        path, _ = pick_file(
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
            QMessageBox.warning(self.parent_widget, "错误", "请先指定输出 CSV 保存路径。")
            return

        if not check_server_ocr():
            QMessageBox.warning(
                self.parent_widget,
                "服务端未就绪",
                "无法连接 OCR 服务端，请检查算力服务端是否在线。"
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

        # Spawn worker（走服务端 OCR）
        self.worker = VideoOcrWorker(
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
            self.status_lbl.setText("状态: 正在终止中，请稍候...")
            self._append_log("\n[WARN] 已发出停止指令，等待引擎退出...")
            # 不调用 wait()，避免主线程阻塞；由 worker 的 finished 信号统一恢复 UI

    def on_scan_finished(self, success, result):
        self.progress_bar.setValue(0)
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
            if self.worker and self.worker.is_aborted:
                self.status_lbl.setText("状态: 已被用户终止。")
                return

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
