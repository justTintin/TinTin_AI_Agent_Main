# -*- coding: utf-8 -*-
import os
import sys
import shutil
import traceback
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFileDialog, QProgressBar, QMessageBox, QFrame,
                               QComboBox, QSplitter, QWidget, QStackedWidget, QButtonGroup)
from PySide6.QtCore import Signal, QThread, Qt, QRectF
from utils.base_worker import BaseWorker
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from utils.logger_utils import log
from config.paths import TMP_DIR, REMBG_DIR

class RembgWorker(BaseWorker):
    progress = Signal(str)
    finished = Signal(bool, str, str) # success, output_path, error_msg
    
    def __init__(self, img_path, out_path, model_name="u2net"):
        super().__init__()
        self.img_path = img_path
        self.out_path = out_path
        self.model_name = model_name
        
    def run(self):
        try:
            self.progress.emit("正在配置 rembg 抠图运行环境...")
            import sys
            import os
            # Add rembg directory to Python path dynamically
            rembg_dir = REMBG_DIR
            
            if rembg_dir not in sys.path:
                sys.path.insert(0, rembg_dir)
                
            # Configure U2NET_HOME to support integrated green portability
            if "U2NET_HOME" not in os.environ:
                default_home = os.path.expanduser(os.path.join("~", ".u2net"))
                model_filename = f"{self.model_name}.onnx"
                default_model_path = os.path.join(default_home, model_filename)
                
                if not os.path.exists(default_model_path):
                    from config.paths import WORKSPACE_ROOT
                    local_home = os.path.join(WORKSPACE_ROOT, "apps", "rembg", "models")
                    os.makedirs(local_home, exist_ok=True)
                    os.environ["U2NET_HOME"] = local_home
                    
            from rembg import remove, new_session
            from PIL import Image
            
            self.progress.emit(f"正在加载 AI 模型: {self.model_name} (首次使用会自动下载)...")
            session = new_session(self.model_name)
            
            self.progress.emit("AI 正在深度擦除背景并分析边缘...")
            input_image = Image.open(self.img_path)
            output_image = remove(input_image, session=session)
            
            self.progress.emit("正在保存透明抠图结果...")
            output_image.save(self.out_path, format="PNG")
            
            self.finished.emit(True, self.out_path, "")
            
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Rembg processing failed: {e}\n{tb}")
            self.finished.emit(False, "", str(e))


class ImagePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        
    def set_image(self, image_or_path):
        if isinstance(image_or_path, str):
            self.image = QImage(image_or_path)
        else:
            self.image = image_or_path
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(26, 26, 28)) # Match dark background
        
        if not self.image.isNull():
            W, H = self.width(), self.height()
            img_w, img_h = self.image.width(), self.image.height()
            
            factor_w = W / img_w
            factor_h = H / img_h
            scale_factor = min(factor_w, factor_h)
            
            display_w = img_w * scale_factor
            display_h = img_h * scale_factor
            offset_x = (W - display_w) / 2
            offset_y = (H - display_h) / 2
            
            display_rect = QRectF(offset_x, offset_y, display_w, display_h)
            painter.drawImage(display_rect, self.image)


class ResultPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        
    def set_image(self, image):
        self.image = image
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        W, H = self.width(), self.height()
        
        # 1. Paint Dark Checkerboard Background
        tile_size = 12
        color1 = QColor(32, 32, 34)
        color2 = QColor(44, 44, 46)
        for x in range(0, W, tile_size):
            for y in range(0, H, tile_size):
                if ((x // tile_size) + (y // tile_size)) % 2 == 0:
                    painter.fillRect(x, y, tile_size, tile_size, color1)
                else:
                    painter.fillRect(x, y, tile_size, tile_size, color2)
                    
        # 2. Paint cutout result image
        if not self.image.isNull():
            img_w, img_h = self.image.width(), self.image.height()
            factor_w = W / img_w
            factor_h = H / img_h
            scale_factor = min(factor_w, factor_h)
            
            display_w = img_w * scale_factor
            display_h = img_h * scale_factor
            offset_x = (W - display_w) / 2
            offset_y = (H - display_h) / 2
            
            display_rect = QRectF(offset_x, offset_y, display_w, display_h)
            painter.drawImage(display_rect, self.image)


from gui.base_page import BasePage


class ImageMattingPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.parent = parent_widget  # 兼容旧引用
        self.selected_img_path = None
        self.matting_worker = None
        self.output_temp_path = None
        
    def setup(self):
        # Main Layout
        main_layout = QVBoxLayout(self.parent)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)
        
        # 1. Header Section
        header_layout = QHBoxLayout()
        heading = QLabel("AI 图像一键抠图 (Automatic Background Removal)")
        heading.setObjectName("heading")
        header_layout.addWidget(heading)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)
        
        # 2. Workspace splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        
        # Left Panel (Controls)
        left_panel = QFrame()
        left_panel.setObjectName("card")
        left_panel.setFixedWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)
        
        # Image Upload Section
        left_layout.addWidget(QLabel("1. 选择原始图像:"))
        self.btn_select_image = QPushButton("📁 上传本地图像")
        self.btn_select_image.setObjectName("secondary_button")
        self.btn_select_image.setCursor(Qt.PointingHandCursor)
        self.btn_select_image.clicked.connect(self.choose_image)
        left_layout.addWidget(self.btn_select_image)
        
        self.lbl_image_info = QLabel("未载入任何图像，请先上传。")
        self.lbl_image_info.setObjectName("muted_text")
        self.lbl_image_info.setWordWrap(True)
        left_layout.addWidget(self.lbl_image_info)
        
        left_layout.addWidget(self.create_separator())
        
        # Model Selection Section
        left_layout.addWidget(QLabel("2. 选择抠图 AI 模型:"))
        self.combo_model = QComboBox()
        self.models_list = [
            ("u2net (通用主体 - 推荐)", "u2net"),
            ("u2netp (通用轻量 - 快速)", "u2netp"),
            ("u2net_human_seg (人像分割)", "u2net_human_seg"),
            ("u2net_cloth_seg (衣服分割)", "u2net_cloth_seg"),
            ("isnet-general-use (高精度通用)", "isnet-general-use"),
            ("isnet-anime (动漫/二次元人像)", "isnet-anime"),
            ("silueta (极速轻量模型)", "silueta"),
            ("bria-rmbg (SOTA 通用抠图)", "bria-rmbg")
        ]
        for name, key in self.models_list:
            self.combo_model.addItem(name, key)
        left_layout.addWidget(self.combo_model)
        
        left_layout.addWidget(self.create_separator())
        
        # Execution & Actions
        left_layout.addWidget(QLabel("3. 执行自动抠图:"))
        self.lbl_status = QLabel("状态: 准备就绪")
        self.lbl_status.setObjectName("muted_text")
        left_layout.addWidget(self.lbl_status)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)
        
        self.btn_run = QPushButton("⚡ 开始自动抠图")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_matting)
        left_layout.addWidget(self.btn_run)
        
        self.btn_save = QPushButton("💾 保存抠图结果")
        self.btn_save.setObjectName("action_button")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_cutout)
        left_layout.addWidget(self.btn_save)
        
        left_layout.addStretch()
        
        tips = QLabel("💡 提示：本功能基于深度学习，完全自动抠除背景。首次使用对应模型时会自动联网下载权重文件到用户主目录下的 .u2net 文件夹中，请保持网络畅通。")
        tips.setWordWrap(True)
        tips.setObjectName("muted_text")
        tips.setStyleSheet("font-size: 11px; line-height: 14px;")
        left_layout.addWidget(tips)
        
        splitter.addWidget(left_panel)
        
        # Right Panel (Preview Card)
        right_panel = QFrame()
        right_panel.setObjectName("card")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(12)
        
        # Tab View Switcher
        view_tabs_layout = QHBoxLayout()
        self.btn_view_orig = QPushButton("🎨 原始图像 (Original)")
        self.btn_view_orig.setObjectName("pill_button")
        self.btn_view_orig.setCheckable(True)
        self.btn_view_orig.setChecked(True)
        self.btn_view_orig.setCursor(Qt.PointingHandCursor)
        
        self.btn_view_result = QPushButton("🖼️ 抠图结果 (Cutout)")
        self.btn_view_result.setObjectName("pill_button")
        self.btn_view_result.setCheckable(True)
        self.btn_view_result.setCursor(Qt.PointingHandCursor)
        
        view_tabs_layout.addWidget(self.btn_view_orig)
        view_tabs_layout.addWidget(self.btn_view_result)
        view_tabs_layout.addStretch()
        
        self.view_group = QButtonGroup(self.parent)
        self.view_group.addButton(self.btn_view_orig)
        self.view_group.addButton(self.btn_view_result)
        self.view_group.setExclusive(True)
        
        self.btn_view_orig.clicked.connect(lambda: self.switch_view(0))
        self.btn_view_result.clicked.connect(lambda: self.switch_view(1))
        right_layout.addLayout(view_tabs_layout)
        
        # Stacked display container
        self.preview_stack = QStackedWidget()
        
        # Page 0: Original Image Preview
        self.orig_preview = ImagePreviewWidget()
        self.preview_stack.addWidget(self.orig_preview)
        
        # Page 1: Result Preview (Checkerboard grid background)
        self.result_preview = ResultPreviewWidget()
        self.preview_stack.addWidget(self.result_preview)
        
        right_layout.addWidget(self.preview_stack, 1)
        splitter.addWidget(right_panel)
        
        main_layout.addWidget(splitter, 1)
        
    def create_separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #2e2e32; max-height: 1px;")
        return line
        
    def choose_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            self.selected_img_path = file_path
            self.orig_preview.set_image(file_path)
            
            # Load metadata
            img = QImage(file_path)
            if not img.isNull():
                self.lbl_image_info.setText(
                    f"图片路径: {os.path.basename(file_path)}\n分辨率: {img.width()} x {img.height()}"
                )
                self.lbl_status.setText("状态: 已载入图片，可开始自动抠图。")
                self.btn_run.setEnabled(True)
                self.btn_save.setEnabled(False)
                self.output_temp_path = None
                
                # Switch view back to original layer
                self.btn_view_orig.setChecked(True)
                self.switch_view(0)
            else:
                QMessageBox.critical(self.parent, "错误", "无法载入图片，请确保文件完好且格式正确。")
                self.lbl_image_info.setText("图片加载失败。")
                self.btn_run.setEnabled(False)
                
    def switch_view(self, index):
        self.preview_stack.setCurrentIndex(index)
        
    def run_matting(self):
        if not self.selected_img_path:
            return
            
        # Get selected model
        model_name = self.combo_model.currentData()
        
        # Prepare runtime directories
        tmp_dir = TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        
        self.output_temp_path = os.path.join(tmp_dir, "rembg_output.png")
        
        # UI Progress configurations
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.btn_run.setEnabled(False)
        self.btn_select_image.setEnabled(False)
        self.btn_save.setEnabled(False)
        
        # Launch worker thread
        self.matting_worker = RembgWorker(self.selected_img_path, self.output_temp_path, model_name)
        self.matting_worker.progress.connect(self.on_worker_progress)
        self.matting_worker.finished.connect(self.on_worker_finished)
        self.matting_worker.start()
        
    def on_worker_progress(self, msg):
        self.lbl_status.setText(f"状态: {msg}")
        
    def on_worker_finished(self, success, out_path, err_msg):
        self.progress_bar.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_select_image.setEnabled(True)
        
        if success:
            self.lbl_status.setText("状态: 自动抠图已完成！")
            
            # Load result image
            out_img = QImage(out_path)
            self.result_preview.set_image(out_img)
            
            # Switch preview stack to result page
            self.btn_view_result.setChecked(True)
            self.switch_view(1)
            
            # Enable save button
            self.btn_save.setEnabled(True)
        else:
            self.lbl_status.setText("状态: 抠图失败。")
            QMessageBox.critical(self.parent, "抠图失败", f"自动抠图失败：\n{err_msg}")
            
    def save_cutout(self):
        if not self.output_temp_path or not os.path.exists(self.output_temp_path):
            return
            
        save_path, _ = QFileDialog.getSaveFileName(
            self.parent, "保存抠图结果为透明 PNG", "", "透明图像 (*.png)"
        )
        if save_path:
            try:
                shutil.copy2(self.output_temp_path, save_path)
                QMessageBox.information(self.parent, "成功", f"抠图结果已成功另存为：\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self.parent, "错误", f"另存为图片文件失败：\n{e}")
