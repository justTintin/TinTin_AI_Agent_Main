# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import traceback

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QTextEdit, QProgressBar, QFrame, QMessageBox,
                               QGroupBox, QScrollArea, QWidget, QLineEdit,
                               QSpinBox, QFileDialog, QListWidget, QListWidgetItem, QInputDialog)
from PySide6.QtCore import Signal, QThread, Qt
from utils.base_worker import BaseWorker
import configparser
from utils.logger_utils import log
from config.paths import (WORKSPACE_ROOT, APPS_DIR,
                           VSR_DIR, KNOWLEDGE_MATERIALS_DIR,
                           DATA_DIR, MATERIALS_DIR, CONFIG_INI_FILE, CONFIG_DIR, PROJECT_ROOT)


class EnvInstallWorker(BaseWorker):
    log_line = Signal(str)
    stage = Signal(str)
    busy = Signal(bool)
    finished = Signal(bool, str)

    def run(self):
        try:
            self.busy.emit(True)
            self.stage.emit("正在卸载 CPU 版 PyTorch 库...")
            self.run_command([sys.executable, "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"])

            self.stage.emit("正在通过官方源安装 CUDA 12.1 版 PyTorch (包体积较大，下载需要几分钟)...")
            self.run_command([
                sys.executable, "-m", "pip", "install", "torch==2.5.1+cu121",
                "--index-url", "https://download.pytorch.org/whl/cu121"
            ])

            self.stage.emit("依赖安装/修复完成！正在刷新环境状态...")
            self.busy.emit(False)
            self.finished.emit(True, "系统环境配置一键修复成功！已成功为您安装 CUDA 版 PyTorch。")
        except Exception as e:
            self.busy.emit(False)
            self.stage.emit("❌ 修复失败")
            self.finished.emit(False, f"环境修复失败：\n{str(e)}")

    def run_command(self, cmd):
        self.log_line.emit(f"\n[执行命令] {' '.join(cmd)}\n")
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


class EnvCheckWorker(BaseWorker):
    finished = Signal(dict)

    def __init__(self, check_func):
        super().__init__()
        self.check_func = check_func

    def run(self):
        try:
            info = self.check_func()
            self.finished.emit(info)
        except Exception as e:
            log.error(f"环境异步检测失败: {e}")
            self.finished.emit({})


from gui.base_page import BasePage


class EnvConfigPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.check_worker = None
        self.cached_info = None
        self.pending_callbacks = []

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        # Title
        heading = QLabel("⚙️ 系统环境配置与参数设置")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        # Status Display Card
        self.card = QFrame()
        self.card.setObjectName("card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(16)

        self.status_labels = {}

        # Scroll Area for Categories
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_area.setMinimumHeight(300)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("QWidget { background: transparent; }")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # Group 1: Python & GPU 基础运行环境
        group_py_gpu = QGroupBox("🐍 Python & GPU 基础运行环境")
        group_py_gpu.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #3b82f6; }
        """)
        layout_py_gpu = QVBoxLayout(group_py_gpu)
        layout_py_gpu.setContentsMargins(16, 20, 16, 16)
        layout_py_gpu.setSpacing(10)
        self._add_status_row(layout_py_gpu, "python", "🐍 Python 运行环境")
        self._add_status_row(layout_py_gpu, "gpu", "🎮 显卡 (NVIDIA GPU) 硬件")
        self._add_status_row(layout_py_gpu, "cuda", "⚡ CUDA (PyTorch) 开启状态")
        
        # Add local refresh button for Python & GPU
        self.btn_refresh_py_gpu = QPushButton("🔄 刷新 Python & GPU 检测")
        self.btn_refresh_py_gpu.setObjectName("secondary_button")
        self.btn_refresh_py_gpu.setFixedWidth(200)
        self.btn_refresh_py_gpu.clicked.connect(self.refresh_python_gpu)
        layout_py_gpu.addWidget(self.btn_refresh_py_gpu)
        
        scroll_layout.addWidget(group_py_gpu)

        # Group 1.5: 系统硬件与版本信息
        group_sys_info = QGroupBox("💻 系统硬件与版本信息")
        group_sys_info.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #3b82f6; }
        """)
        layout_sys_info = QVBoxLayout(group_sys_info)
        layout_sys_info.setContentsMargins(16, 20, 16, 16)
        layout_sys_info.setSpacing(10)
        self._add_status_row(layout_sys_info, "os_ver", "🖥️ 操作系统版本")
        self._add_status_row(layout_sys_info, "cpu_info", "🧠 处理器 (CPU)")
        self._add_status_row(layout_sys_info, "ram_info", "💾 运行内存 (RAM)")
        self._add_status_row(layout_sys_info, "gpu_info", "🎮 显卡 (GPU) 与显存")
        
        self.btn_auto_optimize = QPushButton("⚡ 根据硬件自动优化 AI 并行配置")
        self.btn_auto_optimize.setObjectName("primary_button")
        self.btn_auto_optimize.setFixedWidth(240)
        self.btn_auto_optimize.clicked.connect(self.auto_optimize_hardware)
        layout_sys_info.addWidget(self.btn_auto_optimize)
        
        scroll_layout.addWidget(group_sys_info)

        # Group 4: 其他音视频编解码与去水印算法环境
        group_other = QGroupBox("🎞️ 其他音视频编解码与去水印算法环境")
        group_other.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #f97316; }
        """)
        layout_other = QVBoxLayout(group_other)
        layout_other.setContentsMargins(16, 20, 16, 16)
        layout_other.setSpacing(10)
        self._add_status_row(layout_other, "ffmpeg", "🎞️ FFmpeg 编解码器")
        self._add_status_row(layout_other, "vsr", "✂️ VSR 去字幕算法组件")
        
        # Add local refresh button for codecs
        self.btn_refresh_codecs = QPushButton("🔄 刷新音视频编解码检测")
        self.btn_refresh_codecs.setObjectName("secondary_button")
        self.btn_refresh_codecs.setFixedWidth(200)
        self.btn_refresh_codecs.clicked.connect(self.refresh_codecs)
        layout_other.addWidget(self.btn_refresh_codecs)
        
        scroll_layout.addWidget(group_other)

        # Group 7: RustFS 对象存储配置
        group_rustfs = QGroupBox("🗄️ RustFS 对象存储配置")
        group_rustfs.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #0ea5e9; }
        """)
        layout_rustfs = QVBoxLayout(group_rustfs)
        layout_rustfs.setContentsMargins(16, 20, 16, 16)
        layout_rustfs.setSpacing(10)

        rustfs_desc = QLabel(
            "RustFS 兼容 S3/MinIO 协议，用于素材文件的云端对象存储。\n"
            "配置后可在「素材管理」页将本地素材目录同步到对象存储桶。"
        )
        rustfs_desc.setObjectName("muted_text")
        rustfs_desc.setWordWrap(True)
        layout_rustfs.addWidget(rustfs_desc)

        row_rustfs1 = QHBoxLayout()
        row_rustfs1.addWidget(QLabel("服务地址："))
        self.edit_rustfs_endpoint = QLineEdit()
        self.edit_rustfs_endpoint.setPlaceholderText("http://192.168.111.17:9000")
        row_rustfs1.addWidget(self.edit_rustfs_endpoint, 2)
        row_rustfs1.addWidget(QLabel("默认存储桶："))
        self.edit_rustfs_bucket = QLineEdit()
        self.edit_rustfs_bucket.setPlaceholderText("materials")
        row_rustfs1.addWidget(self.edit_rustfs_bucket, 1)
        layout_rustfs.addLayout(row_rustfs1)

        row_rustfs2 = QHBoxLayout()
        row_rustfs2.addWidget(QLabel("Access Key："))
        self.edit_rustfs_access_key = QLineEdit()
        self.edit_rustfs_access_key.setPlaceholderText("rustfsadmin")
        row_rustfs2.addWidget(self.edit_rustfs_access_key, 1)
        row_rustfs2.addWidget(QLabel("Secret Key："))
        self.edit_rustfs_secret_key = QLineEdit()
        self.edit_rustfs_secret_key.setEchoMode(QLineEdit.Password)
        self.edit_rustfs_secret_key.setPlaceholderText("密码/Secret Key")
        row_rustfs2.addWidget(self.edit_rustfs_secret_key, 1)
        layout_rustfs.addLayout(row_rustfs2)

        row_rustfs3 = QHBoxLayout()
        self.lbl_rustfs_status = QLabel("")
        self.lbl_rustfs_status.setObjectName("muted_text")
        row_rustfs3.addWidget(self.lbl_rustfs_status, 1)
        btn_test_rustfs = QPushButton("🔌 测试连接")
        btn_test_rustfs.setObjectName("secondary_button")
        btn_test_rustfs.clicked.connect(self._test_rustfs_connection)
        row_rustfs3.addWidget(btn_test_rustfs)
        btn_save_rustfs = QPushButton("💾 保存 RustFS 配置")
        btn_save_rustfs.setObjectName("secondary_button")
        btn_save_rustfs.clicked.connect(self._save_rustfs_config)
        row_rustfs3.addWidget(btn_save_rustfs)
        layout_rustfs.addLayout(row_rustfs3)

        # RustFS 配置组暂时隐藏，尚未接入对象存储
        # scroll_layout.addWidget(group_rustfs)

        # 注：素材向量库 PostgreSQL 数据库配置已移至「平台接入」→「🗄️ 数据库」标签页，此处不再重复。
        # CLIP 向量检索已切换为纯远程 embedding 服务模式，
        # 服务地址请在「AI 模型配置」→「🖼️ CLIP」标签页中填写。

        scroll_layout.addWidget(scroll_widget)

        card_layout.addWidget(scroll_area)

        layout.addWidget(self.card, 1)

        # Run initial check asynchronously
        self.refresh_status_async()

    def _add_status_row(self, layout, key, name):
        row = QHBoxLayout()
        label_name = QLabel(f"<b>{name}:</b>")
        label_name.setStyleSheet("font-size: 13px;")
        label_val = QLabel("正在检测...")
        label_val.setStyleSheet("font-size: 13px;")
        row.addWidget(label_name)
        row.addWidget(label_val)
        row.addStretch()
        layout.addLayout(row)
        self.status_labels[key] = label_val

    # ── 素材目录配置 ──

    def _choose_materials_dir(self):
        new_dir = QFileDialog.getExistingDirectory(
            self.parent_widget,
            "选择素材存储目录（可以是外置盘或映射盘）",
            self.edit_mat_dir.text()
        )
        if not new_dir:
            return
        import json as _json
        cfg_path = os.path.join(DATA_DIR, "knowledge_dir.json")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump({"materials_dir": new_dir}, f, ensure_ascii=False, indent=2)
            self.edit_mat_dir.setText(new_dir)
            QMessageBox.information(
                self.parent_widget, "素材目录已设置",
                f"素材存储目录已设置为：\n{new_dir}\n\n请重启应用以完全生效。\n"
                "（浏览器下载、视频转写字幕文件均将写入此目录）"
            )
        except Exception as e:
            QMessageBox.critical(self.parent_widget, "保存失败", f"写入配置失败：{e}")

    def _reset_materials_dir(self):
        import json as _json
        cfg_path = os.path.join(DATA_DIR, "knowledge_dir.json")
        try:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)
        except Exception:
            pass
        default = os.path.join(MATERIALS_DIR, "knowledge")
        self.edit_mat_dir.setText(default)
        QMessageBox.information(
            self.parent_widget, "已恢复默认",
            f"已恢复为默认素材目录：\n{default}\n\n请重启应用以完全生效。"
        )

    def check_environment(self):
        info = {}
        
        # 1. Python
        info["python_path"] = sys.executable
        info["python_ok"] = True
        
        # 2. CUDA & PyTorch
        info["cuda_available"] = False
        info["cuda_device"] = "无"
        info["torch_version"] = "未安装"
        info["torch_ok"] = False
        try:
            import torch
            info["torch_version"] = torch.__version__
            if torch.cuda.is_available():
                info["cuda_available"] = True
                info["cuda_device"] = torch.cuda.get_device_name(0)
                info["torch_ok"] = True
            else:
                if "+cpu" in torch.__version__:
                    info["cuda_device"] = "当前为 CPU 版 PyTorch，无法启用 GPU 加速"
                else:
                    info["cuda_device"] = "PyTorch 已安装，但无法成功加载 CUDA (GPU) 驱动"
        except ImportError:
            pass

        # 3. FFmpeg
        project_root = PROJECT_ROOT
        workspace_root = WORKSPACE_ROOT
        candidates = [
            os.path.join(project_root, "gui", "ffmpeg.exe"),
            os.path.join(project_root, "ffmpeg.exe"),
            os.path.join(workspace_root, "ffmpeg.exe"),
            os.path.join(workspace_root, "python_embeded", "ffmpeg.exe"),
            os.path.join(workspace_root, "python_embeded", "Scripts", "ffmpeg.exe"),
        ]
        ffmpeg_path = None
        for c in candidates:
            if os.path.exists(c) and os.path.isfile(c):
                ffmpeg_path = os.path.abspath(c)
                break
        if not ffmpeg_path:
            ffmpeg_path = shutil.which("ffmpeg")

        if ffmpeg_path:
            info["ffmpeg_ok"] = True
            info["ffmpeg_path"] = ffmpeg_path
        else:
            info["ffmpeg_ok"] = False
            info["ffmpeg_path"] = "未在系统环境或软件目录中检测到 ffmpeg.exe"

        # 6. VSR Subtitle Remover
        vsr_dir = VSR_DIR
        vsr_python = os.path.join(vsr_dir, "Python", "python.exe")
        vsr_script = os.path.join(vsr_dir, "resources", "vsr_run.py")
        if os.path.isdir(vsr_dir) and os.path.isfile(vsr_python) and os.path.isfile(vsr_script):
            info["vsr_ok"] = True
            info["vsr_status"] = f"已就绪 (内嵌环境: {vsr_python})"
        else:
            info["vsr_ok"] = False
            info["vsr_status"] = "未就绪 (缺少 apps/vsr-v1.1.1-windows-nvidia-cuda 主目录或内嵌 Python 环境)"

        # 8. VoxCPM（纯远程模式）
        info["voxcpm_installed"] = True
        info["voxcpm_ok"] = True
        info["voxcpm_status"] = "远程模式（由 ai_config 配置 vox_api_url）"

        # 9. PaddleOCR Isolated Environment & Models
        from config.paths import PADDLEOCR_PYTHON, PADDLEOCR_SCRIPT
        info["paddleocr_ok"] = False
        info["paddleocr_status"] = "未安装"
        if os.path.isfile(PADDLEOCR_PYTHON):
            try:
                # Dynamically inject the path inside python command to bypass embedded Python ignoring PYTHONPATH
                paddleocr_src = os.path.abspath(os.path.join(WORKSPACE_ROOT, "apps", "PaddleOCR"))
                cmd_str = f"import sys; sys.path.insert(0, r'{paddleocr_src}'); import paddleocr, paddlex, aiohttp"
                result = subprocess.run(
                    [PADDLEOCR_PYTHON, "-c", cmd_str],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    info["paddleocr_ok"] = True
                    info["paddleocr_status"] = "已就绪"
                else:
                    err = result.stderr.strip() or result.stdout.strip()
                    last_line = err.splitlines()[-1] if err else "未知错误"
                    info["paddleocr_status"] = f"依赖缺失: {last_line}"
            except Exception as e:
                info["paddleocr_status"] = f"依赖缺失: {str(e)}"
        else:
            info["paddleocr_status"] = "未安装 (缺少专属虚拟环境)"

        local_paddlex_dir = os.path.join(APPS_DIR, "PaddleOCR", "paddle-models", "official_models")
        info["paddleocr_models_dir"] = local_paddlex_dir
        found_p_models = []
        if os.path.isdir(local_paddlex_dir):
            for fn in os.listdir(local_paddlex_dir):
                sub_path = os.path.join(local_paddlex_dir, fn)
                if os.path.isdir(sub_path):
                    found_p_models.append(fn)
        info["paddleocr_models"] = found_p_models if found_p_models else ["暂无集成模型 (运行或一键集成时会自动加载)"]

        # 10. Hardware Info
        try:
            from utils.hardware_utils import get_system_hardware_info, auto_adjust_concurrency_configs
            hw = get_system_hardware_info()
            info["os_ver"] = hw["os"]
            info["cpu_info"] = f"{hw['cpu_name']} ({hw['cpu_cores']})"
            info["ram_info"] = f"{hw['ram']} GB"
            info["gpu_info"] = f"{hw['gpu_name']} (显存: {hw['gpu_vram']} GB)"
            # Automatically run auto-adjustment silently if configuration keys are missing
            auto_adjust_concurrency_configs(force=False)
        except Exception as e:
            log.error(f"环境检测获取硬件配置失败: {e}")
            info["os_ver"] = "未知"
            info["cpu_info"] = "未知"
            info["ram_info"] = "未知"
            info["gpu_info"] = "未知"

        return info

    def refresh_status_async(self, callback=None):
        if callback:
            self.pending_callbacks.append(callback)
            
        if self.cached_info:
            self.update_ui_with_info(self.cached_info)
            while self.pending_callbacks:
                cb = self.pending_callbacks.pop(0)
                try:
                    cb(self.cached_info)
                except Exception as e:
                    log.error(f"执行环境检测回调失败: {e}")
            
        if self.check_worker and self.check_worker.isRunning():
            return
            
        if not self.cached_info:
            for key, lbl in self.status_labels.items():
                lbl.setText("正在检测...")
                
        try:
            if hasattr(self, "btn_refresh_py_gpu") and self.btn_refresh_py_gpu:
                self.btn_refresh_py_gpu.setEnabled(False)
        except RuntimeError:
            pass
        try:
            if hasattr(self, "btn_refresh_codecs") and self.btn_refresh_codecs:
                self.btn_refresh_codecs.setEnabled(False)
        except RuntimeError:
            pass
            
        self.check_worker = EnvCheckWorker(self.check_environment)
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_finished(self, info):
        try:
            if hasattr(self, "btn_refresh_py_gpu") and self.btn_refresh_py_gpu:
                self.btn_refresh_py_gpu.setEnabled(True)
        except RuntimeError:
            pass
        try:
            if hasattr(self, "btn_refresh_codecs") and self.btn_refresh_codecs:
                self.btn_refresh_codecs.setEnabled(True)
        except RuntimeError:
            pass
            
        if not info:
            return
            
        self.cached_info = info
        self.update_ui_with_info(info)
        
        while self.pending_callbacks:
            cb = self.pending_callbacks.pop(0)
            try:
                cb(info)
            except Exception as e:
                log.error(f"执行环境检测回调失败: {e}")

    def update_ui_with_info(self, info):
        try:
            if "python" in self.status_labels:
                py_status = f"<font color='#16a34a'><b>✅ 独立嵌入式环境</b></font> (位置: {info['python_path']})"
                self.status_labels["python"].setText(py_status)

            if "gpu" in self.status_labels:
                if info.get("cuda_available", False):
                    gpu_status = f"<font color='#16a34a'><b>✅ 已就绪</b></font> ({info.get('cuda_device', '无')})"
                else:
                    from gui_main import HAS_NVML
                    if HAS_NVML:
                        try:
                            import pynvml
                            pynvml.nvmlInit()
                            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                            name = pynvml.nvmlDeviceGetName(handle)
                            if isinstance(name, bytes):
                                name = name.decode("utf-8")
                            gpu_status = f"<font color='#d97706'><b>⚠️ 硬件已连接，但 PyTorch 未加载</b></font> ({name})"
                        except Exception:
                            gpu_status = "<font color='#dc2626'><b>❌ 未检测到支持 CUDA 的 NVIDIA 显卡</b></font>"
                    else:
                        gpu_status = "<font color='#dc2626'><b>❌ 未检测到支持 CUDA 的 NVIDIA 显卡</b></font>"
                self.status_labels["gpu"].setText(gpu_status)

            if "cuda" in self.status_labels:
                if info.get("cuda_available", False):
                    cuda_status = f"<font color='#16a34a'><b>✅ 可用</b></font> (PyTorch: {info.get('torch_version', '未安装')})"
                else:
                    cuda_status = f"<font color='#dc2626'><b>❌ 未启用 GPU</b></font> (原因: {info.get('cuda_device', '无')})"
                self.status_labels["cuda"].setText(cuda_status)

            if "ffmpeg" in self.status_labels:
                if info.get("ffmpeg_ok", False):
                    ffmpeg_status = f"<font color='#16a34a'><b>✅ 已就绪</b></font> (路径: {info.get('ffmpeg_path', '')})"
                else:
                    ffmpeg_status = f"<font color='#dc2626'><b>❌ {info.get('ffmpeg_path', '')}</b></font>"
                self.status_labels["ffmpeg"].setText(ffmpeg_status)

            if "vsr" in self.status_labels:
                if info.get("vsr_ok", False):
                    vsr_status = f"<font color='#16a34a'><b>✅ 已就绪</b></font> ({info.get('vsr_status', '')})"
                else:
                    vsr_status = f"<font color='#dc2626'><b>❌ 未就绪</b></font> ({info.get('vsr_status', '')})"
                self.status_labels["vsr"].setText(vsr_status)

            if "os_ver" in self.status_labels:
                self.status_labels["os_ver"].setText(info.get("os_ver", "未知"))
            if "cpu_info" in self.status_labels:
                self.status_labels["cpu_info"].setText(info.get("cpu_info", "未知"))
            if "ram_info" in self.status_labels:
                self.status_labels["ram_info"].setText(info.get("ram_info", "未知"))
            if "gpu_info" in self.status_labels:
                self.status_labels["gpu_info"].setText(info.get("gpu_info", "未知"))
        except RuntimeError:
            pass

    def auto_optimize_hardware(self):
        try:
            from utils.hardware_utils import auto_adjust_concurrency_configs
            res = auto_adjust_concurrency_configs(force=True)
            
            msg = (
                f"系统硬件优化完成！已根据您的配置进行了以下参数优化调整：\n\n"
                f"优化级别：{res['level']}\n"
                f"1. 本地 Ollama 并行数 (ollama_num_parallel) ➔ {res['ollama_num_parallel']} 并发\n"
                f"2. 多线程视觉分析数 (vision_concurrency) ➔ {res['vision_concurrency']} 并发\n"
                f"3. 向量编码批处理大小 (batch_size) ➔ {res['clip_batch_size']} 批处理\n\n"
                f"配置已写入 ai_config.json 和 material_index_config.json (已移除)。\n"
                f"（注：若 Ollama 已经在运行，需要重启应用或重启 Ollama 才能使并发限制生效）"
            )
            QMessageBox.information(self.parent_widget, "硬件自适应优化成功", msg)
        except Exception as e:
            QMessageBox.critical(self.parent_widget, "优化失败", f"运行自适应优化失败：\n{e}")

    def refresh_python_gpu(self):
        self.cached_info = None
        self.refresh_status_async()

    def refresh_codecs(self):
        self.cached_info = None
        self.refresh_status_async()

    def refresh_status(self):
        self.refresh_status_async()

    # ── RustFS 对象存储配置 ──

    def _load_rustfs_config(self):
        from utils.rustfs_manager import get_rustfs_config
        cfg = get_rustfs_config()
        self.edit_rustfs_endpoint.setText(cfg.get("endpoint", ""))
        self.edit_rustfs_access_key.setText(cfg.get("access_key", ""))
        self.edit_rustfs_secret_key.setText(cfg.get("secret_key", ""))
        self.edit_rustfs_bucket.setText(cfg.get("bucket", ""))

    def _save_rustfs_config(self):
        from utils.rustfs_manager import save_rustfs_config
        ok = save_rustfs_config(
            self.edit_rustfs_endpoint.text(),
            self.edit_rustfs_access_key.text(),
            self.edit_rustfs_secret_key.text(),
            self.edit_rustfs_bucket.text(),
        )
        if ok:
            self.lbl_rustfs_status.setText("✅ 配置已保存")
        else:
            self.lbl_rustfs_status.setText("❌ 保存失败，请检查日志")

    def _test_rustfs_connection(self):
        self._save_rustfs_config()
        self.lbl_rustfs_status.setText("正在连接…")
        from utils.rustfs_manager import test_connection
        ok, msg = test_connection()
        color = "#16a34a" if ok else "#dc2626"
        icon = "✅" if ok else "❌"
        self.lbl_rustfs_status.setText(f"<font color='{color}'>{icon} {msg}</font>")

    # ── 旺店通 ERP 配置 ──
