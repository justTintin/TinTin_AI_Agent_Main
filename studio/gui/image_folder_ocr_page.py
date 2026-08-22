import contextlib
import os

from config.paths import OUTPUTS_DIR

# ImageFolderOcrWorker / ImageOcrTestWorker 已迁移至 utils.ocr_workers（走服务端 OCR）
from gui.base_page import BasePage
from gui.video_ocr_page import InteractivePreviewLabelOCR
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.file_dialog_utils import pick_directory, pick_save_file
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from utils.ocr_client import check_server_ocr
from utils.ocr_workers import ImageFolderOcrWorker, ImageOcrTestWorker
from utils.os_utils import open_in_explorer


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
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Header Title
        heading = QLabel(" 图片文件夹框选 OCR 识别")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")  # noqa: E501
        main_layout.addWidget(splitter, 1)

        # ─── Left Panel (Folder Selection & Interactive Preview) ───
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(16)

        # Card 1: Folder Selection
        folder_card = QFrame()
        folder_card.setObjectName("card")
        folder_layout = QVBoxLayout(folder_card)
        folder_layout.setContentsMargins(16, 16, 16, 16)
        folder_layout.setSpacing(10)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("选择图片文件夹:"))
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("请选择包含图片的文件夹...")
        self.folder_path_input.textChanged.connect(self._on_folder_path_changed)
        folder_row.addWidget(self.folder_path_input)
        btn_sel = mdi_button("浏览", "folder")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_folder)
        folder_row.addWidget(btn_sel)
        folder_layout.addLayout(folder_row)
        left_layout.addWidget(folder_card, 0)

        # Card 2: Interactive Preview Card (Expanding to bottom)
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        p_layout.setSpacing(10)

        p_title = QLabel(" 模板图片框选预览 (在画面上拖拽选择需要 OCR 的框):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title, 0)

        self.preview_label = InteractivePreviewLabelOCR()
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.resized.connect(self.update_preview)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout.addWidget(self.preview_label, 1)
        left_layout.addWidget(preview_card, 1)

        splitter.addWidget(left_widget)

        # ─── Right Panel (Controls Card & Processing Log) ───
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
        c_title.setStyleSheet("font-weight: bold; font-size: 14px; padding-left: 20px; color: #3b82f6;")  # noqa: E501
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
        box_layout.addLayout(create_slider_row("起始横坐标 X:", self.x_slider, self.x_val_lbl))  # noqa: E501

        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.valueChanged.connect(self.update_preview)
        self.w_val_lbl = QLabel("1")
        box_layout.addLayout(create_slider_row("识别区域宽 W:", self.w_slider, self.w_val_lbl))  # noqa: E501

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        box_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))  # noqa: E501

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        box_layout.addLayout(create_slider_row("识别区域高 H:", self.h_slider, self.h_val_lbl))  # noqa: E501

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

        # Key text matching input & Test button
        key_label_row = QHBoxLayout()
        key_label_row.addWidget(QLabel("定位关键词 (Key):"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("例如: 订单编码")
        key_label_row.addWidget(self.key_input)

        self.btn_test_ocr = QPushButton(" 测试选区")
        self.btn_test_ocr.setObjectName("secondary_button")
        self.btn_test_ocr.setFixedWidth(90)
        self.btn_test_ocr.clicked.connect(self.test_selection_ocr)
        key_label_row.addWidget(self.btn_test_ocr)
        options_layout.addLayout(key_label_row)

        # Save format configuration
        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("保存表格格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItem("CSV 电子表格 (*.csv)", "csv")
        self.format_combo.addItem("TXT 纯文本 (*.txt)", "txt")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(self.format_combo)
        options_layout.addLayout(format_row)

        # Output Path Input
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出保存路径:"))
        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText("默认输出到 outputs 目录...")
        out_row.addWidget(self.output_path_input)
        btn_save_as = mdi_button("浏览", "folder")
        btn_save_as.setObjectName("secondary_button")
        btn_save_as.setFixedWidth(60)
        btn_save_as.clicked.connect(self._select_output_path)
        out_row.addWidget(btn_save_as)
        options_layout.addLayout(out_row)

        # Status & Progress
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
                background-color: QLinearGradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);  # noqa: E501
                border-radius: 5px;
            }
        """)
        options_layout.addWidget(self.progress_bar)

        # Action Buttons Row
        btn_action_layout = QHBoxLayout()
        self.btn_start = QPushButton(" 开始批量 OCR")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_batch_ocr)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_batch_ocr)
        btn_action_layout.addWidget(self.btn_stop)
        options_layout.addLayout(btn_action_layout)

        # Open Out Dir Button
        self.btn_open_dir = QPushButton(" 打开输出文件目录")
        self.btn_open_dir.setObjectName("secondary_button")
        self.btn_open_dir.clicked.connect(self.open_output_directory)
        options_layout.addWidget(self.btn_open_dir)

        controls_layout.addWidget(options_widget)
        right_layout.addWidget(controls_card, 0)

        # Card 2: Logs Viewer
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel(" 批量 OCR 实时日志与匹配数据:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card, 1)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

    def _select_folder(self):
        path = pick_directory(
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
        except OSError as e:
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
            self.output_path_input.setText(os.path.join(OUTPUTS_DIR, f"{folder_name}_ocr_result{ext}"))  # noqa: E501

        except OSError as e:
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
                    if target_w < 1:
                        target_w = 1
                    if target_h < 1:
                        target_h = 1

                    self.preview_label.target_w = target_w
                    self.preview_label.target_h = target_h
                    self.preview_label.px_offset_x = (display_w - target_w) // 2
                    self.preview_label.px_offset_y = (display_h - target_h) // 2

                    resized_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)  # noqa: E501

                    # Draw selection rectangle
                    draw = ImageDraw.Draw(resized_img)
                    rx0 = int(x * target_w / w_img)
                    ry0 = int(y * target_h / h_img)
                    rx1 = int((x + w) * target_w / w_img)
                    ry1 = int((y + h) * target_h / h_img)
                    draw.rectangle([rx0, ry0, rx1, ry1], outline="#00ff00", width=3)

                    rgb_img = resized_img.convert("RGB")
                    data = rgb_img.tobytes("raw", "RGB")
                    qImg = QImage(data, target_w, target_h, target_w * 3, QImage.Format_RGB888)  # noqa: E501 N806
                    self.preview_label.setPixmap(QPixmap.fromImage(qImg))
            except OSError as e:
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
        path, _ = pick_save_file(
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

        if not check_server_ocr():
            QMessageBox.warning(
                self.parent_widget,
                "服务端未就绪",
                "无法连接 OCR 服务端，请检查算力服务端是否在线。"
            )
            return

        x, y, w, h = self.box
        ymin = y
        ymax = y + h
        xmin = x
        xmax = x + w
        box_tuple = (ymin, ymax, xmin, xmax)

        self.btn_test_ocr.setEnabled(False)
        self.btn_test_ocr.setText(" 正在测试中...")
        self.status_lbl.setText("状态: 正在测试选区 OCR...")

        self.test_worker = ImageOcrTestWorker(
            image_path=self.template_image_path,
            box=box_tuple
        )
        self.test_worker.finished.connect(self.on_test_finished)
        self.test_worker.start()

    def on_test_finished(self, success, text_or_error):
        self.btn_test_ocr.setEnabled(True)
        self.btn_test_ocr.setText(" 测试识别选区")
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
                f"选区识别成功！\n\n识别文本：\n{text_or_error}\n\n已自动为您提取定位关键词：\n\"{suggested_key}\""  # noqa: E501
            )
        else:
            self._append_log(f"[ERROR] 选区 OCR 测试失败: {text_or_error}")
            QMessageBox.critical(self.parent_widget, "测试失败", f"选区测试失败，错误原因：\n{text_or_error}")  # noqa: E501

    def start_batch_ocr(self):
        folder_path = self.folder_path_input.text().strip()
        if not folder_path or not os.path.exists(folder_path):
            QMessageBox.warning(self.parent_widget, "错误", "请先选择有效的输入图片文件夹。")
            return
        key_text = self.key_input.text().strip()

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

        self.log_view.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("状态: 正在初始化 OCR 批量任务（服务端）...")

        out_path = self.output_path_input.text().strip()

        # Spawn worker thread（走服务端 OCR）
        self.worker = ImageFolderOcrWorker(
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

    def on_batch_finished(self, success, result):
        self.progress_bar.setValue(0)
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
            with contextlib.suppress(OSError):
                open_in_explorer(result, select=True)
        else:
            if self.worker and getattr(self.worker, 'is_aborted', False):
                self.status_lbl.setText("状态: 已被用户终止。")
                return
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
                    open_in_explorer(dir_path, select=False)
                except OSError as e:
                    log.error(f"无法打开目录: {e}")
            else:
                QMessageBox.warning(self.parent_widget, "提示", "输出目录目前不存在，请先运行识别生成文件。")
        else:
            QMessageBox.warning(self.parent_widget, "提示", "输出路径为空，请先选择文件夹或路径。")
