# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import traceback
from PIL import Image, ImageDraw

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QSlider, QSplitter, QWidget, QTextEdit, QSizePolicy)
from PySide6.QtCore import Signal, QThread, Qt, QSize
from utils.base_worker import BaseWorker
from PySide6.QtGui import QImage, QPixmap
from utils.logger_utils import log
from config.paths import TMP_DIR, OUTPUTS_DIR, PADDLEOCR_PYTHON, IMAGE_FOLDER_OCR_SCRIPT
from gui.video_ocr_page import InteractivePreviewLabelOCR

class ImageFolderOcrWorker(BaseWorker):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str) # success, output_path_or_error

    def __init__(self, vsr_python, ocr_script, folder_path, key_text, output_path):
        super().__init__()
        self.vsr_python = vsr_python
        self.ocr_script = ocr_script
        self.folder_path = folder_path
        self.key_text = key_text
        self.output_path = output_path
        self.process = None
        self.is_aborted = False

    def run(self):
        cmd = [
            self.vsr_python,
            self.ocr_script,
            "--folder", self.folder_path,
            "--key", self.key_text,
            "--output", self.output_path
        ]

        self.status_updated.emit("正在初始化 OCR 推理引擎...")
        self.log_received.emit("[INFO] 开始图片文件夹批量 OCR 识别任务")
        self.log_received.emit(f"[INFO] 文件夹路径: {self.folder_path}")
        self.log_received.emit(f"[INFO] 定位关键词: {self.key_text}")
        self.log_received.emit(f"[INFO] 执行后端命令: {' '.join(cmd)}")

        startupinfo = None
        if sys.platform == "win32":
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

            saved_path = self.output_path
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
                    self.status_updated.emit("OCR 引擎批量运行中...")
                elif line.startswith("[OCR]"):
                    self.status_updated.emit(f"正在识别中: {line.split('|')[0].replace('[OCR] Image:', '').strip()}")
                elif line.startswith("[SUCCESS]"):
                    import re
                    match = re.search(r"Results saved to:\s*(.*)$", line)
                    if match:
                        saved_path = match.group(1).strip()

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
                elif line.startswith("[SUCCESS]"):
                    import re
                    match = re.search(r"Results saved to:\s*(.*)$", line)
                    if match:
                        saved_path = match.group(1).strip()

            ret_code = self.process.returncode
            if self.is_aborted:
                self.finished.emit(False, "用户终止运行。")
            elif ret_code == 0:
                self.finished.emit(True, saved_path)
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


class ImageOcrTestWorker(BaseWorker):
    finished = Signal(bool, str) # success, text_or_error

    def __init__(self, vsr_python, ocr_script, image_path, box):
        super().__init__()
        self.vsr_python = vsr_python
        self.ocr_script = ocr_script
        self.image_path = image_path
        self.box = box # [ymin, ymax, xmin, xmax]

    def run(self):
        ymin, ymax, xmin, xmax = self.box
        cmd = [
            self.vsr_python,
            self.ocr_script,
            "--test_mode",
            "--image", self.image_path,
            "--ymin", str(ymin),
            "--ymax", str(ymax),
            "--xmin", str(xmin),
            "--xmax", str(xmax)
        ]

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0 # SW_HIDE

        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                cwd=os.path.dirname(self.ocr_script)
            )
            
            output, _ = p.communicate()
            
            # Find test result line
            test_result = ""
            for line in output.splitlines():
                if line.startswith("[TEST_RESULT] Text:"):
                    test_result = line.replace("[TEST_RESULT] Text:", "").strip()
                    break
                    
            if p.returncode == 0:
                self.finished.emit(True, test_result if test_result else "(无识别文本)")
            else:
                self.finished.emit(False, f"测试进程异常退出，错误码: {p.returncode}\n日志: {output}")
        except Exception as e:
            self.finished.emit(False, str(e))


from gui.base_page import BasePage


class ImageFolderOcrPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.test_worker = None
        
        self.template_image_path = ""
        self.image_files = []
        self.img_width = 1280
        self.img_height = 720
        self.box = [0, 0, 0, 0] # [x, y, w, h]

    def setup(self):
        # Main layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(16)

        # Header Title
        heading = QLabel("🔍 图片文件夹框选 OCR 识别")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        main_layout.addWidget(splitter, 1)

        # --- Left Panel ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)
        
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 20, 0, 20)
        card_layout.setSpacing(14)

        # Folder Selector
        folder_container = QWidget()
        folder_container_layout = QVBoxLayout(folder_container)
        folder_container_layout.setContentsMargins(24, 0, 24, 0)
        folder_container_layout.setSpacing(14)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("选择图片文件夹:"))
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("请选择包含图片的文件夹...")
        self.folder_path_input.textChanged.connect(self._on_folder_path_changed)
        folder_row.addWidget(self.folder_path_input)
        btn_sel = QPushButton("浏览")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_folder)
        folder_row.addWidget(btn_sel)
        folder_container_layout.addLayout(folder_row)
        card_layout.addWidget(folder_container)

        # Bounding Box Sliders
        box_group = QFrame()
        box_group.setObjectName("box_manage_group")
        box_group.setStyleSheet("#box_manage_group { background-color: #26262a; border-top: 1px solid #2e2e32; border-bottom: 1px solid #2e2e32; border-radius: 0px; }")
        box_layout = QVBoxLayout(box_group)
        box_layout.setContentsMargins(24, 16, 24, 16)
        box_layout.setSpacing(14)

        box_title = QLabel("📦 OCR 模板识别选区设置:")
        box_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        box_layout.addWidget(box_title)

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
        sliders_layout.addLayout(create_slider_row("识别区域宽 W:", self.w_slider, self.w_val_lbl))

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("识别区域高 H:", self.h_slider, self.h_val_lbl))

        box_layout.addLayout(sliders_layout)
        card_layout.addWidget(box_group)

        # Options Container
        bottom_container = QWidget()
        bottom_container_layout = QVBoxLayout(bottom_container)
        bottom_container_layout.setContentsMargins(24, 0, 24, 0)
        bottom_container_layout.setSpacing(14)

        # Key text matching input & Test button
        key_label_row = QHBoxLayout()
        key_label_row.addWidget(QLabel("定位关键词 (Key):"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("例如: 订单编码")
        key_label_row.addWidget(self.key_input)
        
        self.btn_test_ocr = QPushButton("🧪 测试识别选区")
        self.btn_test_ocr.setObjectName("secondary_button")
        self.btn_test_ocr.clicked.connect(self.test_selection_ocr)
        key_label_row.addWidget(self.btn_test_ocr)
        bottom_container_layout.addLayout(key_label_row)

        # Save format configuration
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("保存表格格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItem("CSV 电子表格 (*.csv)", "csv")
        self.format_combo.addItem("TXT 纯文本 (*.txt)", "txt")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(self.format_combo)
        bottom_container_layout.addLayout(format_row)

        # Output Path Input
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出保存路径:"))
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("默认输出到 outputs 目录...")
        out_row.addWidget(self.output_path_input)
        btn_save_as = QPushButton("浏览")
        btn_save_as.setObjectName("secondary_button")
        btn_save_as.clicked.connect(self._select_output_path)
        out_row.addWidget(btn_save_as)
        bottom_container_layout.addLayout(out_row)

        # Progress / Status
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
        self.btn_start = QPushButton("🚀 开始批量 OCR")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_batch_ocr)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_batch_ocr)
        btn_action_layout.addWidget(self.btn_stop)
        bottom_container_layout.addLayout(btn_action_layout)

        self.btn_open_dir = QPushButton("📂 打开输出文件目录")
        self.btn_open_dir.setObjectName("secondary_button")
        self.btn_open_dir.clicked.connect(self.open_output_directory)
        bottom_container_layout.addWidget(self.btn_open_dir)

        card_layout.addWidget(bottom_container, 1)
        left_layout.addWidget(card)
        left_widget.setMaximumWidth(480)
        splitter.addWidget(left_widget)

        # --- Right Panel ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(14)

        # Interactive selection preview label
        preview_card = QFrame()
        preview_card.setObjectName("card")
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        
        p_title = QLabel("🖼️ 模板图片框选预览 (在画面上拖拽选择需要 OCR 的框):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title)

        self.preview_label = InteractivePreviewLabelOCR()
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.resized.connect(self.update_preview)
        p_layout.addWidget(self.preview_label)
        right_layout.addWidget(preview_card)

        # Logs Viewer
        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel("📝 批量 OCR 推理引擎实时日志与匹配数据:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(200)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card)

        # Tips Card
        help_card = QFrame()
        help_card.setObjectName("card")
        help_layout = QVBoxLayout(help_card)
        help_card.setContentsMargins(16, 12, 16, 12)
        help_lbl = QLabel(
            "💡 **图片批量 OCR 提取说明**:\n"
            "1. **定位原理**：不同图片的字段排版可能会有微调偏移。系统首先在模板图片上通过框选进行 OCR，确定要找的定位关键词（如“订单编码”）。\n"
            "2. **距离匹配**：在批量执行时，系统对每张图片做全局 OCR。定位到该关键词后，算法会自动计算空间距离，提取与其**右侧**或**下方**空间位置最邻近的文本块内容作为结果，防止错位提取。\n"
            "3. 本功能使用本地 PaddleOCR 加密模型，完全离线运行，数据绝对安全。"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("font-size: 11px; line-height: 16px; color: #a1a1aa;")
        help_layout.addWidget(help_lbl)
        right_layout.addWidget(help_card)

        splitter.addWidget(right_widget)

    def _select_folder(self):
        path = QFileDialog.getExistingDirectory(
            self.parent_widget,
            "选择图片文件夹",
            ""
        )
        if path:
            self.folder_path_input.setText(path)

    def _on_folder_path_changed(self, path):
        path = path.strip()
        if not path or not os.path.exists(path) or not os.path.isdir(path):
            self.template_image_path = ""
            self.image_files = []
            self.preview_label.clear()
            self.preview_label.setText("请选择有效的图片文件夹")
            return

        # Find valid images in the directory
        valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff")
        self.image_files = []
        try:
            for file in os.listdir(path):
                if file.lower().endswith(valid_exts):
                    self.image_files.append(os.path.join(path, file))
        except Exception as e:
            log.error(f"遍历文件夹失败: {e}")

        if not self.image_files:
            self.template_image_path = ""
            self.preview_label.clear()
            self.preview_label.setText("未在选择的文件夹中找到有效图片文件")
            return

        # Load first image as template preview
        self.template_image_path = self.image_files[0]
        try:
            with Image.open(self.template_image_path) as img:
                self.img_width, self.img_height = img.size
                
            self.box = [
                int(self.img_width * 0.25),
                int(self.img_height * 0.25),
                int(self.img_width * 0.50),
                int(self.img_height * 0.50)
            ]

            # Adjust slider ranges
            self.x_slider.blockSignals(True)
            self.w_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            self.h_slider.blockSignals(True)

            self.x_slider.setRange(0, self.img_width)
            self.w_slider.setRange(1, self.img_width)
            self.y_slider.setRange(0, self.img_height)
            self.h_slider.setRange(1, self.img_height)

            self.preview_label.frame_w = self.img_width
            self.preview_label.frame_h = self.img_height

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            self._sync_sliders_to_box()
            self.update_preview()

            # Suggest default output path
            folder_name = os.path.basename(os.path.normpath(path))
            fmt = self.format_combo.currentData()
            ext = f".{fmt}"
            self.output_path_input.setText(os.path.join(OUTPUTS_DIR, f"{folder_name}_ocr_result{ext}"))

        except Exception as e:
            log.error(f"加载模板图片失败: {e}")
            self.preview_label.setText(f"模板图片加载失败: {e}")

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

        # Boundary constraints
        if x + w > self.img_width:
            w = self.img_width - x
            self.w_slider.setValue(w)
        if y + h > self.img_height:
            h = self.img_height - y
            self.h_slider.setValue(h)

        self.x_val_lbl.setText(str(x))
        self.w_val_lbl.setText(str(w))
        self.y_val_lbl.setText(str(y))
        self.h_val_lbl.setText(str(h))

        self.box = [x, y, w, h]
        self.preview_label.set_box(self.box)

        if self.template_image_path and os.path.exists(self.template_image_path):
            try:
                display_w = self.preview_label.width()
                display_h = self.preview_label.height()
                if display_w < 100 or display_h < 100:
                    display_w, display_h = 720, 405

                # Read and resize
                with Image.open(self.template_image_path) as pil_img:
                    w_img, h_img = pil_img.size
                    ratio = min(display_w / w_img, display_h / h_img)
                    target_w = int(w_img * ratio)
                    target_h = int(h_img * ratio)
                    if target_w < 1: target_w = 1
                    if target_h < 1: target_h = 1

                    self.preview_label.target_w = target_w
                    self.preview_label.target_h = target_h
                    self.preview_label.px_offset_x = (display_w - target_w) // 2
                    self.preview_label.px_offset_y = (display_h - target_h) // 2

                    resized_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    
                    # Draw selection rectangle
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
            except Exception as e:
                log.error(f"绘图预览错误: {e}")

    def _on_label_bounds_changed(self, x, y, w, h):
        self.box = [x, y, w, h]
        self._sync_sliders_to_box()
        self.update_preview()

    def _on_format_changed(self):
        path = self.output_path_input.text().strip()
        if path:
            fmt = self.format_combo.currentData()
            base, _ = os.path.splitext(path)
            self.output_path_input.setText(f"{base}.{fmt}")

    def _select_output_path(self):
        fmt = self.format_combo.currentData()
        filter_str = "CSV Files (*.csv)" if fmt == "csv" else "Text Files (*.txt)"
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "选择保存位置",
            self.output_path_input.text().strip(),
            f"{filter_str};;All Files (*)"
        )
        if path:
            self.output_path_input.setText(path)

    def test_selection_ocr(self):
        if not self.template_image_path or not os.path.exists(self.template_image_path):
            QMessageBox.warning(self.parent_widget, "提示", "请先选择包含有效图片的文件夹。")
            return

        vsr_python = PADDLEOCR_PYTHON
        ocr_script = IMAGE_FOLDER_OCR_SCRIPT

        if not os.path.exists(vsr_python) or not os.path.exists(ocr_script):
            QMessageBox.warning(
                self.parent_widget,
                "环境未就绪",
                "未检测到 PaddleOCR 专属运行环境，请先前往「⚙️ 环境配置」部署专属环境。"
            )
            return

        x, y, w, h = self.box
        ymin = y
        ymax = y + h
        xmin = x
        xmax = x + w
        box_tuple = (ymin, ymax, xmin, xmax)

        self.btn_test_ocr.setEnabled(False)
        self.btn_test_ocr.setText("🧪 正在测试中...")
        self.status_lbl.setText("状态: 正在测试选区 OCR...")

        self.test_worker = ImageOcrTestWorker(
            vsr_python=vsr_python,
            ocr_script=ocr_script,
            image_path=self.template_image_path,
            box=box_tuple
        )
        self.test_worker.finished.connect(self.on_test_finished)
        self.test_worker.start()

    def on_test_finished(self, success, text_or_error):
        self.btn_test_ocr.setEnabled(True)
        self.btn_test_ocr.setText("🧪 测试识别选区")
        self.status_lbl.setText("状态: 测试完成")

        if success:
            self._append_log(f"[INFO] 模板选区 OCR 测试成功！识别文本: {text_or_error}")
            
            # Smart suggestion for the Key text field
            # Look for separators like :, ： or spaces to split key and value
            import re
            match = re.match(r"^(.+?)(:|：|\s|=)(.*)$", text_or_error)
            suggested_key = text_or_error.strip()
            if match:
                possible_key = match.group(1).strip()
                if possible_key:
                    suggested_key = possible_key
            
            # Fill the key text input field
            self.key_input.setText(suggested_key)
            QMessageBox.information(
                self.parent_widget,
                "测试成功",
                f"选区识别成功！\n\n识别文本：\n{text_or_error}\n\n已自动为您提取定位关键词：\n\"{suggested_key}\""
            )
        else:
            self._append_log(f"[ERROR] 选区 OCR 测试失败: {text_or_error}")
            QMessageBox.critical(self.parent_widget, "测试失败", f"选区测试失败，错误原因：\n{text_or_error}")

    def start_batch_ocr(self):
        folder_path = self.folder_path_input.text().strip()
        if not folder_path or not os.path.exists(folder_path):
            QMessageBox.warning(self.parent_widget, "错误", "请先选择有效的输入图片文件夹。")
            return

        key_text = self.key_input.text().strip()
        if not key_text:
            QMessageBox.warning(self.parent_widget, "错误", "请填写定位关键词 (Key)。")
            return

        out_path = self.output_path_input.text().strip()
        if not out_path:
            QMessageBox.warning(self.parent_widget, "错误", "请指定输出表格保存路径。")
            return

        vsr_python = PADDLEOCR_PYTHON
        ocr_script = IMAGE_FOLDER_OCR_SCRIPT

        if not os.path.exists(vsr_python) or not os.path.exists(ocr_script):
            QMessageBox.warning(
                self.parent_widget,
                "环境未就绪",
                "未检测到 PaddleOCR 专属运行环境，请先部署专属环境。"
            )
            return

        self.log_view.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_test_ocr.setEnabled(False)
        self.folder_path_input.setEnabled(False)
        self.output_path_input.setEnabled(False)
        self.key_input.setEnabled(False)
        self.format_combo.setEnabled(False)
        
        self.x_slider.setEnabled(False)
        self.w_slider.setEnabled(False)
        self.y_slider.setEnabled(False)
        self.h_slider.setEnabled(False)

        # Spawn worker thread
        self.worker = ImageFolderOcrWorker(
            vsr_python=vsr_python,
            ocr_script=ocr_script,
            folder_path=folder_path,
            key_text=key_text,
            output_path=out_path
        )
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.status_updated.connect(self.status_lbl.setText)
        self.worker.log_received.connect(self._append_log)
        self.worker.finished.connect(self.on_batch_finished)
        self.worker.start()

    def stop_batch_ocr(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.btn_stop.setEnabled(False)

    def on_batch_finished(self, success, result):
        self.progress_bar.setVisible(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_test_ocr.setEnabled(True)
        self.folder_path_input.setEnabled(True)
        self.output_path_input.setEnabled(True)
        self.key_input.setEnabled(True)
        self.format_combo.setEnabled(True)
        
        self.x_slider.setEnabled(True)
        self.w_slider.setEnabled(True)
        self.y_slider.setEnabled(True)
        self.h_slider.setEnabled(True)

        if success:
            self.status_lbl.setText("状态: 批量识别完成！")
            QMessageBox.information(
                self.parent_widget, 
                "任务成功", 
                f"图片文件夹批量 OCR 扫描成功完成！\n\n数据结果已输出至电子表格：\n{result}"
            )
            # Try to select the output file in explorer
            try:
                subprocess.Popen(f'explorer /select,"{os.path.normpath(result)}"')
            except Exception:
                pass
        else:
            self.status_lbl.setText("状态: OCR 识别中断或出错。")
            QMessageBox.critical(self.parent_widget, "扫描失败", f"批量 OCR 扫描失败：\n{result}")

    def _append_log(self, text):
        self.log_view.append(text)
        self.log_view.moveCursor(self.log_view.textCursor().End)

    def open_output_directory(self):
        path = self.output_path_input.text().strip()
        if path:
            dir_path = os.path.dirname(os.path.abspath(path))
            if os.path.exists(dir_path):
                try:
                    subprocess.Popen(f'explorer "{os.path.normpath(dir_path)}"')
                except Exception as e:
                    log.error(f"无法打开目录: {e}")
            else:
                QMessageBox.warning(self.parent_widget, "提示", "输出目录目前不存在，请先运行识别生成文件。")
        else:
            QMessageBox.warning(self.parent_widget, "提示", "输出路径为空，请先选择文件夹或路径。")
