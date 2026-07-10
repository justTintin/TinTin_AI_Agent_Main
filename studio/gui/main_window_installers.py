# -*- coding: utf-8 -*-
"""MainWindow 的安装器 mixin（Playwright / PaddleOCR 修复），从 gui_main 拆出。"""

import subprocess
import time
import json
import zipfile
import shutil
from config.paths import BUNDLED_PW_BROWSERS_ZIP
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT
)
import threading
import uuid
import configparser
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
from gui.subtitle_removal_page import SubtitleRemovalPage
from gui.live_clip_page import LiveClipPage
from gui.voice_clone_page import VoiceClonePage
from gui.voice_samples_page import VoiceSamplesPage
from gui.video_ocr_page import VideoOcrPage
from gui.image_folder_ocr_page import ImageFolderOcrPage
from utils.logger_utils import log, get_last_logs
from utils.account_manager import AccountManager
from core.creator_browser_controller import CreatorBrowserController
from utils.thread_worker import TaskWorker as Worker
from gui.threads import SystemMonitorThread, ComfyWSThread
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QDialog, QListWidget, 
                                 QListWidgetItem, QGridLayout, QFileDialog, 
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont


class PaddleOcrInstallWorker(QThread):
    log_line = Signal(str)
    stage = Signal(str)
    busy = Signal(bool)
    finished = Signal(bool, str)

    def run(self):
        try:
            self.busy.emit(True)
            from config.paths import PADDLEOCR_VENV_DIR, PADDLEOCR_PYTHON, WORKSPACE_ROOT
            import sys
            import subprocess
            
            self.stage.emit("正在检测与修复专属 Python 运行环境...")
            self.log_line.emit(f"[INFO] 专属运行环境路径: {PADDLEOCR_VENV_DIR}\n")
            
            self.stage.emit("正在升级 pip 版本...")
            cmd_pip = [PADDLEOCR_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            self.run_command(cmd_pip)
            
            # 检测硬件 GPU 与驱动情况
            has_gpu = False
            try:
                import torch
                has_gpu = torch.cuda.is_available()
                if has_gpu:
                    self.log_line.emit(f"[INFO] 检测到本机 CUDA GPU 可用: {torch.cuda.get_device_name(0)}\n")
                else:
                    self.log_line.emit("[INFO] 未检测到可用 CUDA GPU，将直接采用 CPU 模式安装。\n")
            except Exception as e:
                self.log_line.emit(f"[INFO] 检测 GPU 可用性时发生异常: {e}，将采用 CPU 模式安装。\n")
            
            paddle_ok = False
            if has_gpu:
                try:
                    self.stage.emit("正在安装 PaddlePaddle 深度学习框架 (GPU加速版)...")
                    cmd_paddle = [PADDLEOCR_PYTHON, "-m", "pip", "install", "paddlepaddle-gpu==3.0.0", "-i", "https://www.paddlepaddle.org.cn/packages/stable/cu126/"]
                    self.run_command(cmd_paddle)
                    
                    self.stage.emit("正在验证 GPU 版 PaddlePaddle 是否正常加载...")
                    subprocess.check_call(
                        [PADDLEOCR_PYTHON, "-c", "import paddle"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    self.log_line.emit("[INFO] GPU 版 PaddlePaddle 验证成功，支持 GPU 加速识别！\n")
                    paddle_ok = True
                except Exception as e:
                    self.log_line.emit(f"[WARNING] GPU 版 PaddlePaddle 安装或导入测试失败: {e}。将自动回退安装 CPU 版本...\n")
                    paddle_ok = False
            
            if not paddle_ok:
                self.stage.emit("正在安装 PaddlePaddle 深度学习框架 (CPU版)...")
                cmd_paddle_cpu = [PADDLEOCR_PYTHON, "-m", "pip", "install", "paddlepaddle==3.0.0", "-i", "https://www.paddlepaddle.org.cn/packages/stable/cpu/"]
                try:
                    self.run_command(cmd_paddle_cpu)
                except Exception as e_cpu:
                    self.log_line.emit(f"[WARNING] 采用官方 CPU 镜像安装失败: {e_cpu}，正在尝试清华源安装...\n")
                    cmd_paddle_tsinghua = [PADDLEOCR_PYTHON, "-m", "pip", "install", "paddlepaddle==3.0.0", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
                    self.run_command(cmd_paddle_tsinghua)
                
                # 验证 CPU 版本
                try:
                    subprocess.check_call(
                        [PADDLEOCR_PYTHON, "-c", "import paddle"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    self.log_line.emit("[INFO] CPU 版 PaddlePaddle 验证成功！\n")
                except Exception as e_test:
                    self.log_line.emit(f"[ERROR] CPU 版 PaddlePaddle 验证失败: {e_test}\n")
                    raise RuntimeError(f"CPU 版 PaddlePaddle 验证失败: {e_test}")
            
            self.stage.emit("正在安装 Paddlex 模型引擎...")
            cmd_paddlex = [PADDLEOCR_PYTHON, "-m", "pip", "install", "paddlex==3.6.1", "aiohttp", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            self.run_command(cmd_paddlex)
            
            self.stage.emit("正在安装 PaddleOCR 余下依赖依赖项...")
            req_file = os.path.join(WORKSPACE_ROOT, "apps", "PaddleOCR", "requirements.txt")
            cmd_req = [PADDLEOCR_PYTHON, "-m", "pip", "install", "-r", req_file, "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            self.run_command(cmd_req)

            self.stage.emit("正在安装 PaddleOCR 引擎包...")
            paddleocr_src = os.path.join(WORKSPACE_ROOT, "apps", "PaddleOCR")
            # 先卸载旧的可编辑安装（可能指向已删除的路径）
            self.run_command_silent([PADDLEOCR_PYTHON, "-m", "pip", "uninstall", "-y", "paddleocr"])
            cmd_ocr = [PADDLEOCR_PYTHON, "-m", "pip", "install", "-e", paddleocr_src, "--no-deps", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            self.run_command(cmd_ocr)

            # 验证安装
            self.stage.emit("正在验证 PaddleOCR 环境...")
            try:
                # Dynamically inject the path inside python command to bypass embedded Python ignoring PYTHONPATH
                cmd_str = f"import sys; sys.path.insert(0, r'{paddleocr_src}'); import paddleocr, paddlex, aiohttp"
                subprocess.check_call(
                    [PADDLEOCR_PYTHON, "-c", cmd_str],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.log_line.emit("[INFO] PaddleOCR 环境验证通过（paddleocr/paddlex/aiohttp 均可正常导入）\n")
            except Exception as e:
                self.log_line.emit(f"[WARNING] PaddleOCR 环境验证异常: {e}\n")

            self.stage.emit("PaddleOCR 专属环境部署成功！")
            self.busy.emit(False)
            self.finished.emit(True, "PaddleOCR 专属 Python 运行环境一键部署/安装成功！")
        except Exception as e:
            self.busy.emit(False)
            self.stage.emit("❌ 部署失败")
            self.finished.emit(False, f"专属环境部署失败：\n{str(e)}")

    def run_command(self, cmd):
        self.log_line.emit(f"[执行命令] {' '.join(cmd)}\n")
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        while True:
            line = p.stdout.readline()
            if not line and p.poll() is not None:
                break
            if line:
                self.log_line.emit(line.strip())
        rc = p.poll()
        if rc != 0:
            raise RuntimeError(f"命令执行返回非零退出码: {rc}")

    def run_command_silent(self, cmd):
        subprocess.run(cmd, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW)


class InstallersMixin:
    def is_playwright_chromium_present(self):
        if not os.path.isdir(PW_BROWSERS_DIR):
            return False
        for root, dirs, files in os.walk(PW_BROWSERS_DIR):
            if "chrome.exe" in files:
                return True
        return False

    def ensure_playwright_chromium_ready(self):
        self._pw_ready = self.is_playwright_chromium_present()
        if self._pw_ready:
            return
        if not self._pw_install_running:
            self.install_playwright_chromium()

    def install_playwright_chromium(self):
        if self._pw_install_running:
            return
        self._pw_install_running = True
        if hasattr(self, "cg_install_btn"):
            self.cg_install_btn.setEnabled(False)
        if hasattr(self, "cg_status_label"):
            self.cg_status_label.setText("正在安装 Chromium 内核（首次可能较慢）...")

        def run_install():
            try:
                if os.path.exists(BUNDLED_PW_BROWSERS_ZIP):
                    os.makedirs(PW_BROWSERS_DIR, exist_ok=True)
                    with zipfile.ZipFile(BUNDLED_PW_BROWSERS_ZIP, "r") as zf:
                        zf.extractall(PW_BROWSERS_DIR)
                    return {"code": 0, "out": "unzipped"}
            except Exception as e:
                return {"code": 2, "out": f"unzip_failed: {e}"}

            env = os.environ.copy()
            env["PLAYWRIGHT_BROWSERS_PATH"] = PW_BROWSERS_DIR
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            return {"code": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}

        def on_done(res):
            code = res.get("code")
            out = res.get("out", "")
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if code == 0:
                self._pw_ready = True
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装完成")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText("")
            else:
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装失败")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText(out[-800:])

        def on_err(err):
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if hasattr(self, "cg_error_label"):
                self.cg_error_label.setText(err)
            if hasattr(self, "cg_status_label"):
                self.cg_status_label.setText("Chromium 内核安装失败")

        self.start_worker(run_install, on_finished=on_done, on_error=on_err)

    def start_paddle_repair(self):
        self.btn_install_paddle.setEnabled(False)
        self.btn_refresh_paddle.setEnabled(False)
        self.paddle_progress_bar.setVisible(True)
        self.paddle_progress_bar.setValue(0)
        self.paddle_log_view.clear()
        
        self.paddle_worker = PaddleOcrInstallWorker()
        self.paddle_worker.log_line.connect(self._append_paddle_log)
        self.paddle_worker.stage.connect(self.paddle_stage_label.setText)
        self.paddle_worker.finished.connect(self.on_paddle_repair_finished)
        self.paddle_worker.start()

    def _append_paddle_log(self, text):
        self.paddle_log_view.append(text)
        self.paddle_log_view.moveCursor(self.paddle_log_view.textCursor().End)
        
        stage_text = self.paddle_stage_label.text()
        if "创建" in stage_text:
            self.paddle_progress_bar.setValue(20)
        elif "升级" in stage_text:
            self.paddle_progress_bar.setValue(40)
        elif "PaddlePaddle" in stage_text:
            self.paddle_progress_bar.setValue(60)
        elif "Paddlex" in stage_text:
            self.paddle_progress_bar.setValue(80)
        elif "余下依赖" in stage_text:
            self.paddle_progress_bar.setValue(90)

    def on_paddle_repair_finished(self, success, message):
        self.paddle_progress_bar.setVisible(False)
        self.btn_install_paddle.setEnabled(True)
        self.btn_refresh_paddle.setEnabled(True)
        
        if success:
            self.paddle_stage_label.setText("系统就绪")
            QMessageBox.information(self, "成功", message)
        else:
            self.paddle_stage_label.setText("安装失败")
            QMessageBox.critical(self, "安装失败", message)
            
        self.refresh_llm_page_status()

    def integrate_paddle_models_action(self):
        user_paddlex_dir = os.path.join(os.path.expanduser("~"), ".paddlex", "official_models")
        from config.paths import APPS_DIR
        local_paddlex_dir = os.path.join(APPS_DIR, "PaddleOCR", "paddle-models", "official_models")
        
        if not os.path.exists(user_paddlex_dir):
            QMessageBox.warning(
                self,
                "未发现缓存模型",
                f"在系统默认缓存路径中未找到已下载的 PaddleOCR 模型：\n{user_paddlex_dir}\n\n您可以直接运行 OCR 功能，系统在首次使用时会自动下载模型到工程目录中。"
            )
            return
            
        if os.path.exists(local_paddlex_dir):
            reply = QMessageBox.question(
                self,
                "重复集成确认",
                f"工程目录中已存在集成的模型文件夹：\n{local_paddlex_dir}\n\n是否重新从用户缓存目录迁移集成？这会覆盖已有模型。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
                
        self.paddle_stage_label.setText("正在复制迁移本地缓存模型...")
        QApplication.processEvents()
        
        try:
            if os.path.exists(local_paddlex_dir):
                shutil.rmtree(local_paddlex_dir)
            os.makedirs(local_paddlex_dir, exist_ok=True)
            for item in os.listdir(user_paddlex_dir):
                s_path = os.path.join(user_paddlex_dir, item)
                d_path = os.path.join(local_paddlex_dir, item)
                if os.path.isdir(s_path):
                    shutil.copytree(s_path, d_path)
                else:
                    shutil.copy2(s_path, d_path)
            self.paddle_stage_label.setText("系统就绪")
            QMessageBox.information(self, "集成成功", f"PaddleOCR 模型文件已全部成功集成迁移至工程专属目录！\n\n位置：\n{local_paddlex_dir}")
        except Exception as e:
            self.paddle_stage_label.setText("集成出错")
            QMessageBox.critical(self, "集成失败", f"模型迁移集成的过程中发生错误：\n{e}")
            
        self.refresh_llm_page_status()
