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
from config.paths import (WORKSPACE_ROOT, APPS_DIR, PYTHON_EMBEDED_DIR, WHISPER_MODELS_DIR,
                           VSR_DIR, VOXCPM2_DIR, KNOWLEDGE_MATERIALS_DIR,
                           DATA_DIR, MATERIALS_DIR, CONFIG_INI_FILE)

def get_voxcpm_python():
    from utils.platform_utils import find_venv_python
    from config.paths import VOXCPM2_DIR
    return find_venv_python(VOXCPM2_DIR)

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
            
            self.stage.emit("正在安装 WhisperX 引擎相关依赖及其配套 NVIDIA DLL 链接库...")
            self.run_command([
                sys.executable, "-m", "pip", "install", "faster-whisper", "transformers", "pyannote-audio",
                "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
            ])
            
            self.stage.emit("依赖安装/修复完成！正在刷新环境状态...")
            self.busy.emit(False)
            self.finished.emit(True, "系统环境配置一键修复成功！已成功为您安装 CUDA 版 PyTorch 与 GPU 转写相关的所有依赖。")
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
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
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
        scroll_widget.setStyleSheet("background: transparent;")
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

        # Group 8: 素材向量库数据库配置
        group_matdb = QGroupBox("🗄️ 素材向量库数据库配置（PostgreSQL + pgvector）")
        group_matdb.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #8b5cf6; }
        """)
        layout_matdb = QVBoxLayout(group_matdb)
        layout_matdb.setContentsMargins(16, 20, 16, 16)
        layout_matdb.setSpacing(10)

        matdb_desc = QLabel(
            "供「向量素材库」页面连接的 PostgreSQL 数据库（需安装 pgvector 扩展）。\n"
            "配置后点击「保存」即生效，无需重启。"
        )
        matdb_desc.setObjectName("muted_text")
        matdb_desc.setWordWrap(True)
        layout_matdb.addWidget(matdb_desc)

        row_matdb1 = QHBoxLayout()
        row_matdb1.addWidget(QLabel("主机地址："))
        self.edit_matdb_host = QLineEdit()
        self.edit_matdb_host.setPlaceholderText("192.168.111.17")
        row_matdb1.addWidget(self.edit_matdb_host, 2)
        row_matdb1.addWidget(QLabel("端口："))
        self.spin_matdb_port = QSpinBox()
        self.spin_matdb_port.setRange(1, 65535)
        self.spin_matdb_port.setValue(15432)
        self.spin_matdb_port.setFixedWidth(80)
        row_matdb1.addWidget(self.spin_matdb_port)
        row_matdb1.addWidget(QLabel("数据库名："))
        self.edit_matdb_name = QLineEdit()
        self.edit_matdb_name.setPlaceholderText("material_index")
        row_matdb1.addWidget(self.edit_matdb_name, 1)
        layout_matdb.addLayout(row_matdb1)

        row_matdb2 = QHBoxLayout()
        row_matdb2.addWidget(QLabel("用户名："))
        self.edit_matdb_user = QLineEdit()
        self.edit_matdb_user.setPlaceholderText("postgres")
        row_matdb2.addWidget(self.edit_matdb_user, 1)
        row_matdb2.addWidget(QLabel("密码："))
        self.edit_matdb_pass = QLineEdit()
        self.edit_matdb_pass.setEchoMode(QLineEdit.Password)
        self.edit_matdb_pass.setPlaceholderText("数据库密码")
        row_matdb2.addWidget(self.edit_matdb_pass, 1)
        layout_matdb.addLayout(row_matdb2)

        row_matdb3 = QHBoxLayout()
        self.lbl_matdb_status = QLabel("")
        self.lbl_matdb_status.setObjectName("muted_text")
        row_matdb3.addWidget(self.lbl_matdb_status, 1)
        btn_test_matdb = QPushButton("🔌 测试连接")
        btn_test_matdb.setObjectName("secondary_button")
        btn_test_matdb.clicked.connect(self._test_matdb_connection)
        row_matdb3.addWidget(btn_test_matdb)
        btn_save_matdb = QPushButton("💾 保存数据库配置")
        btn_save_matdb.setObjectName("secondary_button")
        btn_save_matdb.clicked.connect(self._save_matdb_config)
        row_matdb3.addWidget(btn_save_matdb)
        layout_matdb.addLayout(row_matdb3)

        # CLIP 模型路径
        sep_clip = QFrame()
        sep_clip.setFrameShape(QFrame.HLine)
        sep_clip.setStyleSheet("color: #2e2e32;")
        layout_matdb.addWidget(sep_clip)

        lbl_clip_hint = QLabel(
            "Chinese-CLIP 模型路径（点「一键下载」后自动填入，无需任何手动操作）："
        )
        lbl_clip_hint.setObjectName("muted_text")
        layout_matdb.addWidget(lbl_clip_hint)

        self.edit_clip_model_dir = QLineEdit()
        self.edit_clip_model_dir.setPlaceholderText("点「⬇ 一键下载模型」后此处自动填写")
        self.edit_clip_model_dir.setReadOnly(True)
        layout_matdb.addWidget(self.edit_clip_model_dir)

        # 模型状态行
        self.lbl_clip_model_status = QLabel("模型状态：未初始化")
        self.lbl_clip_model_status.setObjectName("muted_text")
        self.lbl_clip_model_status.setWordWrap(True)
        layout_matdb.addWidget(self.lbl_clip_model_status)

        row_clip2 = QHBoxLayout()
        self.lbl_clip_status = QLabel("")
        self.lbl_clip_status.setObjectName("muted_text")
        self.lbl_clip_status.setWordWrap(True)
        row_clip2.addWidget(self.lbl_clip_status, 1)
        btn_dl_clip = QPushButton("⬇ 一键下载模型（ModelScope）")
        btn_dl_clip.setObjectName("secondary_button")
        btn_dl_clip.setToolTip("在后台用 ModelScope 下载 Chinese-CLIP ViT-B-16 模型到工程本地")
        btn_dl_clip.clicked.connect(self._download_clip_model)
        row_clip2.addWidget(btn_dl_clip)
        self.btn_preload_clip = QPushButton("🔥 加载/预热模型")
        self.btn_preload_clip.setObjectName("primary_button")
        self.btn_preload_clip.setToolTip("将模型加载到内存，后续检索时无需等待")
        self.btn_preload_clip.clicked.connect(self._preload_clip_model)
        row_clip2.addWidget(self.btn_preload_clip)
        btn_save_clip = QPushButton("💾 保存模型路径")
        btn_save_clip.setObjectName("secondary_button")
        btn_save_clip.clicked.connect(self._save_clip_model_dir)
        row_clip2.addWidget(btn_save_clip)
        layout_matdb.addLayout(row_clip2)

        scroll_layout.addWidget(group_matdb)

        # Group 9: NAS 素材入库目录
        group_nasdirs = QGroupBox("📁 NAS 素材入库目录（向量库）")
        group_nasdirs.setStyleSheet("""
            QGroupBox { font-size: 13px; font-weight: bold; border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #8b5cf6; }
        """)
        layout_nasdirs = QVBoxLayout(group_nasdirs)
        layout_nasdirs.setContentsMargins(16, 20, 16, 16)
        layout_nasdirs.setSpacing(10)

        nasdirs_desc = QLabel(
            "配置 NAS 根目录和要入库的资源目录列表。\n"
            "「向量素材库」页面将从此处读取，无需每次手动填写路径。"
        )
        nasdirs_desc.setObjectName("muted_text")
        nasdirs_desc.setWordWrap(True)
        layout_nasdirs.addWidget(nasdirs_desc)

        row_nas_root = QHBoxLayout()
        row_nas_root.addWidget(QLabel("NAS 根目录："))
        self.edit_nas_root = QLineEdit()
        self.edit_nas_root.setPlaceholderText(r"例：\\192.168.111.17  （用于路径标签解析）")
        row_nas_root.addWidget(self.edit_nas_root, 1)
        btn_browse_nas_root = QPushButton("浏览…")
        btn_browse_nas_root.setObjectName("secondary_button")
        btn_browse_nas_root.clicked.connect(self._browse_nas_root)
        row_nas_root.addWidget(btn_browse_nas_root)
        layout_nasdirs.addLayout(row_nas_root)

        layout_nasdirs.addWidget(QLabel("入库资源目录列表："))
        self.list_index_dirs = QListWidget()
        self.list_index_dirs.setMaximumHeight(140)
        self.list_index_dirs.setAlternatingRowColors(True)
        layout_nasdirs.addWidget(self.list_index_dirs)

        row_dir_btns = QHBoxLayout()
        btn_add_dir = QPushButton("＋ 添加目录")
        btn_add_dir.setObjectName("secondary_button")
        btn_add_dir.clicked.connect(self._add_index_dir)
        row_dir_btns.addWidget(btn_add_dir)
        btn_remove_dir = QPushButton("－ 删除选中")
        btn_remove_dir.setObjectName("secondary_button")
        btn_remove_dir.clicked.connect(self._remove_index_dir)
        row_dir_btns.addWidget(btn_remove_dir)
        row_dir_btns.addStretch()
        self.lbl_nasdirs_status = QLabel("")
        self.lbl_nasdirs_status.setObjectName("muted_text")
        row_dir_btns.addWidget(self.lbl_nasdirs_status)
        btn_save_nasdirs = QPushButton("💾 保存目录配置")
        btn_save_nasdirs.setObjectName("secondary_button")
        btn_save_nasdirs.clicked.connect(self._save_nasdirs_config)
        row_dir_btns.addWidget(btn_save_nasdirs)
        layout_nasdirs.addLayout(row_dir_btns)

        scroll_layout.addWidget(group_nasdirs)

        scroll_area.setWidget(scroll_widget)
        card_layout.addWidget(scroll_area)

        layout.addWidget(self.card, 1)
        self._load_matdb_config()

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

        # 3. WhisperX
        info["whisper_version"] = "未安装"
        info["whisper_ok"] = False
        try:
            # Add apps to sys.path to check if whisperx can be loaded
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(curr_dir)
            workspace_root = os.path.dirname(project_root)
            apps_dir = os.path.join(workspace_root, "apps")
            if apps_dir not in sys.path:
                sys.path.insert(0, apps_dir)
            import whisperx
            info["whisper_version"] = "已就绪"
            info["whisper_ok"] = True
        except ImportError:
            pass

        # 4. DLLs
        info["dll_ok"] = False
        info["dll_status"] = "未安装"
        site_packages = os.path.join(PYTHON_EMBEDED_DIR, "Lib", "site-packages")
        nvidia_dir = os.path.join(site_packages, "nvidia")
        if os.path.isdir(nvidia_dir):
            cublas_bin = os.path.join(nvidia_dir, "cublas", "bin")
            cudnn_bin = os.path.join(nvidia_dir, "cudnn", "bin")
            if os.path.isdir(cublas_bin) and os.path.isdir(cudnn_bin):
                info["dll_ok"] = True
                info["dll_status"] = "已就绪 (已发现 nvidia-cublas 与 nvidia-cudnn DLL 目录)"
            else:
                info["dll_status"] = "部分缺失 (缺少 bin 运行目录)"
        else:
            info["dll_status"] = "未安装 (缺少 nvidia-cublas-cu12 与 nvidia-cudnn-cu12)"

        # 5. FFmpeg
        curr_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(curr_dir)
        workspace_root = os.path.dirname(project_root)
        candidates = [
            os.path.join(curr_dir, "ffmpeg.exe"),
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

        # 6. Whisper Models
        models_dir = WHISPER_MODELS_DIR
        info["models_dir"] = models_dir
        found_models = []
        if os.path.isdir(models_dir):
            if os.path.isfile(os.path.join(models_dir, "model.bin")) and os.path.isfile(os.path.join(models_dir, "config.json")):
                found_models.append("已直接在根目录下放置模型文件")
            for fn in os.listdir(models_dir):
                sub_path = os.path.join(models_dir, fn)
                if os.path.isdir(sub_path):
                    if fn.startswith("models--"):
                        found_models.append(f"HF缓存格式: {fn.replace('models--Systran--faster-whisper-', '')}")
                    elif os.path.isfile(os.path.join(sub_path, "model.bin")):
                        found_models.append(f"标准格式: {fn}")
        info["found_models"] = found_models if found_models else ["暂无本地模型（首次运行时将自动下载镜像模型）"]

        # 7. VSR Subtitle Remover
        vsr_dir = VSR_DIR
        vsr_python = os.path.join(vsr_dir, "Python", "python.exe")
        vsr_script = os.path.join(vsr_dir, "resources", "vsr_run.py")
        if os.path.isdir(vsr_dir) and os.path.isfile(vsr_python) and os.path.isfile(vsr_script):
            info["vsr_ok"] = True
            info["vsr_status"] = f"已就绪 (内嵌环境: {vsr_python})"
        else:
            info["vsr_ok"] = False
            info["vsr_status"] = "未就绪 (缺少 apps/vsr-v1.1.1-windows-nvidia-cuda 主目录或内嵌 Python 环境)"

        # 8. VoxCPM
        info["voxcpm_installed"] = False
        info["voxcpm_ok"] = False
        info["voxcpm_status"] = "未安装"
        try:
            subprocess.check_call(
                [get_voxcpm_python(), "-c", "import voxcpm"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            info["voxcpm_installed"] = True
        except Exception:
            pass

        port = 7861
        try:
            config = configparser.ConfigParser()
            config.read(CONFIG_INI_FILE, encoding='utf-8')
            if config.has_section('VoxCPM'):
                port = config.getint('VoxCPM', 'Port', fallback=7861)
        except Exception:
            pass

        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect(("127.0.0.1", port))
            s.close()
            info["voxcpm_ok"] = True
            info["voxcpm_status"] = f"正在运行 (监听端口: {port})"
        except Exception:
            if info["voxcpm_installed"]:
                info["voxcpm_status"] = f"已安装但未启动 (端口 {port} 空闲, 环境: {get_voxcpm_python()})"
            else:
                info["voxcpm_status"] = f"未安装 (在环境 {get_voxcpm_python()} 中未找到 'voxcpm')"

        # 9. PaddleOCR Isolated Environment & Models
        from config.paths import PADDLEOCR_PYTHON, PADDLEOCR_SCRIPT
        info["paddleocr_ok"] = False
        info["paddleocr_status"] = "未安装"
        if os.path.isfile(PADDLEOCR_PYTHON):
            try:
                result = subprocess.run(
                    [PADDLEOCR_PYTHON, "-c", "import paddleocr, paddlex, aiohttp"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode == 0:
                    info["paddleocr_ok"] = True
                    info["paddleocr_status"] = "已就绪"
                else:
                    err = result.stderr.strip() or result.stdout.strip()
                    info["paddleocr_status"] = f"依赖缺失: {err[:120]}"
            except Exception as e:
                info["paddleocr_status"] = f"依赖缺失: {str(e)[:120]}"
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
                
        if hasattr(self, "btn_refresh_py_gpu") and self.btn_refresh_py_gpu:
            self.btn_refresh_py_gpu.setEnabled(False)
        if hasattr(self, "btn_refresh_codecs") and self.btn_refresh_codecs:
            self.btn_refresh_codecs.setEnabled(False)
            
        self.check_worker = EnvCheckWorker(self.check_environment)
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_finished(self, info):
        if hasattr(self, "btn_refresh_py_gpu") and self.btn_refresh_py_gpu:
            self.btn_refresh_py_gpu.setEnabled(True)
        if hasattr(self, "btn_refresh_codecs") and self.btn_refresh_codecs:
            self.btn_refresh_codecs.setEnabled(True)
            
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
                f"配置已写入 ai_config.json 和 material_index_config.json。\n"
                f"（注：若 Ollama 已经在运行，需要重启应用或重启 Ollama 才能使并发限制生效）"
            )
            QMessageBox.information(self.parent_widget, "硬件自适应优化成功", msg)
            self._load_matdb_config()
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
        self._refresh_clip_model_status()

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

    # ── 素材向量库数据库配置 ──

    def _load_matdb_config(self):
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "config", "material_index_config.json")
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
                self.edit_matdb_host.setText(cfg.get("db_host", "192.168.111.17"))
                self.spin_matdb_port.setValue(int(cfg.get("db_port", 15432)))
                self.edit_matdb_name.setText(cfg.get("db_name", "material_index"))
                self.edit_matdb_user.setText(cfg.get("db_user", "postgres"))
                self.edit_matdb_pass.setText(cfg.get("db_password", ""))
                # NAS 入库目录配置
                self.edit_nas_root.setText(cfg.get("nas_root", ""))
                self.list_index_dirs.clear()
                from utils.material_clip_indexer import to_relative_path
                nas_root = cfg.get("nas_root", "")
                for d in cfg.get("index_directories", []):
                    if isinstance(d, dict):
                        local_path = d.get("local_path", "")
                        nas_folder = d.get("nas_folder", "")
                    else:
                        local_path = str(d)
                        nas_folder = to_relative_path(local_path, nas_root)
                        if not nas_folder or nas_folder == local_path:
                            nas_folder = os.path.basename(local_path.rstrip("/\\")) or local_path
                    
                    item_text = f"{local_path} ➔ {nas_folder}"
                    list_item = QListWidgetItem(item_text)
                    list_item.setData(Qt.UserRole, {"local_path": local_path, "nas_folder": nas_folder})
                    self.list_index_dirs.addItem(list_item)
                self.edit_clip_model_dir.setText(cfg.get("clip_model_dir") or "")
        except Exception as e:
            log.error(f"加载素材向量库数据库配置失败: {e}")
        # 显示当前模型状态
        self._refresh_clip_model_status()

    def _save_matdb_config(self):
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "config", "material_index_config.json")
        try:
            cfg = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
            cfg["db_host"]     = self.edit_matdb_host.text().strip()
            cfg["db_port"]     = self.spin_matdb_port.value()
            cfg["db_name"]     = self.edit_matdb_name.text().strip()
            cfg["db_user"]     = self.edit_matdb_user.text().strip()
            cfg["db_password"] = self.edit_matdb_pass.text()
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_matdb_status.setText("✅ 配置已保存")
        except Exception as e:
            self.lbl_matdb_status.setText(f"❌ 保存失败: {e}")
            log.error(f"保存素材向量库数据库配置失败: {e}")

    # ── CLIP 模型配置 ──

    def _refresh_clip_model_status(self):
        """刷新并显示当前模型加载状态（在 UI 线程调用）。"""
        try:
            from utils.material_clip_indexer import get_encoder_status
            st = get_encoder_status()
            if st["loaded"]:
                self.lbl_clip_model_status.setText(f"模型状态：✅ {st['status']}")
            elif st["error"]:
                first = st["error"].split("\n")[0]
                self.lbl_clip_model_status.setText(f"模型状态：❌ {first}")
            else:
                self.lbl_clip_model_status.setText("模型状态：⏸ 未加载（点「🔥 加载/预热模型」）")
        except Exception as e:
            self.lbl_clip_model_status.setText(f"模型状态：— ({e})")

    def _preload_clip_model(self):
        """
        后台线程：
        1. 检测缺少的依赖包（modelscope / torch / transformers），自动用 pip 安装
        2. 安装完成后加载 CLIP 模型到内存
        """
        self.btn_preload_clip.setEnabled(False)
        self.btn_preload_clip.setText("⏳ 准备中…")
        self.lbl_clip_model_status.setText("模型状态：⏳ 正在检查依赖包…")
        self.lbl_clip_status.setText("")

        def _set(status_text, detail_text=""):
            self.lbl_clip_model_status.setText(status_text)
            if detail_text:
                self.lbl_clip_status.setText(detail_text)

        def _do():
            import sys
            import subprocess
            import importlib

            # ── Step 1: 判断模型格式，确定需要安装哪些包 ─────────────────────
            import json as _json_inner
            cfg_path_inner = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "material_index_config.json",
            )
            model_dir_cur = ""
            try:
                if os.path.isfile(cfg_path_inner):
                    with open(cfg_path_inner, encoding="utf-8") as f:
                        model_dir_cur = (_json_inner.load(f).get("clip_model_dir") or "")
            except Exception:
                pass

            is_hf_format = (
                bool(model_dir_cur)
                and os.path.isdir(model_dir_cur)
                and os.path.isfile(os.path.join(model_dir_cur, "config.json"))
            )
            is_ms_format = (
                bool(model_dir_cur)
                and os.path.isdir(model_dir_cur)
                and os.path.isfile(os.path.join(model_dir_cur, "configuration.json"))
                and not os.path.isfile(os.path.join(model_dir_cur, "config.json"))
            )

            need_install = []
            try:
                import torch  # noqa: F401
            except ImportError:
                need_install.append("torch")

            if is_ms_format:
                # ModelScope 格式：需要 modelscope 包（优先从本地源安装）
                try:
                    import modelscope  # noqa: F401
                except ImportError:
                    need_install.append("modelscope")
            elif is_hf_format:
                # HF 格式只需 transformers（通常已安装）
                try:
                    import transformers  # noqa: F401
                except ImportError:
                    need_install.append("transformers")
            else:
                # 未知格式 / 未下载：提示先下载
                _set(
                    "模型状态：⚠️ 未检测到已下载的模型",
                    "⚠️ 请先点「⬇ 一键下载模型」下载模型",
                )
                self.btn_preload_clip.setEnabled(True)
                self.btn_preload_clip.setText("🔥 加载/预热模型")
                return

            if need_install:
                pkgs = " ".join(need_install)
                _set(
                    f"模型状态：⏳ 正在安装 {pkgs}（首次约需 1-5 分钟，请耐心等待）…",
                    f"⏳ 正在自动安装：{pkgs}…",
                )
                try:
                    # modelscope 优先从 apps/modelscope 本地源安装（无需网络）
                    ms_local_src = os.path.join(APPS_DIR, "modelscope")
                    ms_has_local = os.path.isfile(os.path.join(ms_local_src, "setup.py"))
                    pkgs_to_install = []
                    for pkg in need_install:
                        if pkg == "modelscope" and ms_has_local:
                            pkgs_to_install.append(ms_local_src)
                        else:
                            pkgs_to_install.append(pkg)
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install"] + pkgs_to_install + ["-q",
                         "--disable-pip-version-check"],
                        capture_output=True, text=True, timeout=600,
                    )
                    if result.returncode != 0:
                        err_tail = (result.stderr or result.stdout or "")[-300:].strip()
                        _set(
                            f"模型状态：❌ 安装 {pkgs} 失败",
                            f"❌ pip 安装失败：\n{err_tail}",
                        )
                        self.btn_preload_clip.setEnabled(True)
                        self.btn_preload_clip.setText("🔥 加载/预热模型")
                        return
                    importlib.invalidate_caches()
                    _set(f"模型状态：⏳ {pkgs} 安装完成，正在加载模型…", f"✅ {pkgs} 安装完成")
                except subprocess.TimeoutExpired:
                    _set("模型状态：❌ 安装超时", "❌ 安装超时，请重试")
                    self.btn_preload_clip.setEnabled(True)
                    self.btn_preload_clip.setText("🔥 加载/预热模型")
                    return
                except Exception as e:
                    _set(f"模型状态：❌ 安装失败：{e}")
                    self.btn_preload_clip.setEnabled(True)
                    self.btn_preload_clip.setText("🔥 加载/预热模型")
                    return
            else:
                _set("模型状态：⏳ 加载中，请稍候（首次约需 10-60 秒）…")

            # ── Step 2: 加载模型 ───────────────────────────────────────────────
            # 安装了新包后必须重置编码器，清除上次的 _ms_missing / _load_error 缓存
            from utils.material_clip_indexer import reset_encoder, preload_encoder, get_encoder_status
            reset_encoder()
            preload_encoder()
            st = get_encoder_status()

            self.btn_preload_clip.setEnabled(True)
            self.btn_preload_clip.setText("🔥 加载/预热模型")
            if st["loaded"]:
                _set(
                    f"模型状态：✅ {st['status']}",
                    "✅ 模型已成功加载到内存，可直接使用向量检索功能",
                )
            else:
                err = st.get("error") or "未知原因"
                first = err.split("\n")[0]
                _set(f"模型状态：❌ {first}", f"❌ 加载失败：{err}")

        import threading
        threading.Thread(target=_do, daemon=True).start()

    def _browse_clip_model_dir(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择 Chinese-CLIP 本地模型目录")
        if d:
            self.edit_clip_model_dir.setText(d)

    def _save_clip_model_dir(self):
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "config", "material_index_config.json")
        try:
            cfg = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
            val = self.edit_clip_model_dir.text().strip()
            cfg["clip_model_dir"] = val if val else None
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_clip_status.setText("✅ 模型路径已保存")
            # 路径变更后重置全局编码器（下次预热/搜索时会用新路径重建）
            try:
                from utils.material_clip_indexer import reset_encoder
                reset_encoder()
                self.lbl_clip_model_status.setText("模型状态：路径已更新，请点「🔥 加载/预热模型」")
            except Exception:
                pass
        except Exception as e:
            self.lbl_clip_status.setText(f"❌ 保存失败: {e}")

    def _download_clip_model(self):
        """
        下载 Chinese-CLIP ViT-B-16（ModelScope 格式）。
        modelscope 包优先从 apps/modelscope 本地源安装，无需联网安装依赖。
        """
        self.lbl_clip_status.setText("⏳ 准备下载…")
        self.lbl_clip_model_status.setText("模型状态：⏳ 准备中…")

        import threading
        import json as _json

        def _do_download():
            import sys, subprocess, importlib

            # ── Step 1: 确保 modelscope 已安装，优先从本地源 apps/modelscope ──────────
            try:
                import modelscope  # noqa: F401
            except ImportError:
                ms_local_src = os.path.join(APPS_DIR, "modelscope")
                if os.path.isfile(os.path.join(ms_local_src, "setup.py")):
                    install_src = ms_local_src
                    self.lbl_clip_status.setText("⏳ 正在从本地源安装 modelscope（无需网络）…")
                else:
                    install_src = "modelscope"
                    self.lbl_clip_status.setText("⏳ 正在安装 modelscope…")
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", install_src,
                     "-q", "--disable-pip-version-check"],
                    capture_output=True, text=True, timeout=600,
                )
                if r.returncode != 0:
                    self.lbl_clip_status.setText(
                        f"❌ 安装 modelscope 失败：{(r.stderr or r.stdout)[-300:]}"
                    )
                    return
                importlib.invalidate_caches()

            # ── Step 2: 用 ModelScope 下载模型 ────────────────────────────────────────
            try:
                from modelscope.hub.snapshot_download import snapshot_download as ms_dl

                clip_cache = os.path.join(APPS_DIR, "clip-models")
                os.makedirs(clip_cache, exist_ok=True)

                self.lbl_clip_status.setText(
                    "⏳ 正在通过 ModelScope 下载 Chinese-CLIP（约 400 MB，请稍候）…"
                )
                save_dir = ms_dl(
                    "damo/multi-modal_clip-vit-base-patch16_zh",
                    cache_dir=clip_cache,
                )

                # 写入配置
                cfg_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "config", "material_index_config.json",
                )
                cfg = {}
                if os.path.isfile(cfg_path):
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg = _json.load(f)
                cfg["clip_model_dir"] = save_dir
                with open(cfg_path, "w", encoding="utf-8") as f:
                    _json.dump(cfg, f, ensure_ascii=False, indent=2)

                self.edit_clip_model_dir.setText(save_dir)
                self.lbl_clip_status.setText("✅ 下载完成，路径已自动配置")

                # ── Step 3: 自动加载模型 ─────────────────────────────────────────────
                self.lbl_clip_model_status.setText("模型状态：⏳ 正在加载模型…")
                from utils.material_clip_indexer import reset_encoder, preload_encoder, get_encoder_status
                reset_encoder()
                preload_encoder()
                st = get_encoder_status()
                if st["loaded"]:
                    self.lbl_clip_model_status.setText(f"模型状态：✅ {st['status']}")
                    self.lbl_clip_status.setText("✅ 模型下载并加载完成，可直接使用向量检索功能")
                else:
                    err_first = (st.get("error") or "").split("\n")[0]
                    self.lbl_clip_model_status.setText(f"模型状态：❌ {err_first}")

            except Exception as e:
                self.lbl_clip_status.setText(f"❌ 下载失败: {e}")
                self.lbl_clip_model_status.setText("模型状态：❌ 下载失败")

        threading.Thread(target=_do_download, daemon=True).start()

    # ── NAS 入库目录配置 ──

    def _browse_nas_root(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择 NAS 根目录")
        if d:
            self.edit_nas_root.setText(d)

    def _add_index_dir(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择要入库的资源目录")
        if not d:
            return
        
        nas_root = self.edit_nas_root.text().strip()
        from utils.material_clip_indexer import to_relative_path
        default_folder = to_relative_path(d, nas_root)
        if not default_folder or default_folder == d:
            default_folder = os.path.basename(d.rstrip("/\\")) or d
            
        folder_name, ok = QInputDialog.getText(
            self.parent_widget,
            "确认 NAS 文件夹名称",
            f"请输入该目录在 NAS 中对应的文件夹名称：\n本地路径：{d}",
            QLineEdit.Normal,
            default_folder
        )
        if not ok or not folder_name.strip():
            return
            
        nas_folder = folder_name.strip()
        
        existing_paths = []
        for i in range(self.list_index_dirs.count()):
            item = self.list_index_dirs.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, dict):
                existing_paths.append(data.get("local_path", ""))
            else:
                existing_paths.append(item.text().split(" ➔ ")[0])
                
        if d not in existing_paths:
            item_text = f"{d} ➔ {nas_folder}"
            list_item = QListWidgetItem(item_text)
            list_item.setData(Qt.UserRole, {"local_path": d, "nas_folder": nas_folder})
            self.list_index_dirs.addItem(list_item)

    def _remove_index_dir(self):
        for item in self.list_index_dirs.selectedItems():
            self.list_index_dirs.takeItem(self.list_index_dirs.row(item))

    def _save_nasdirs_config(self):
        import json as _json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "config", "material_index_config.json")
        try:
            cfg = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
            cfg["nas_root"] = self.edit_nas_root.text().strip()
            
            index_directories = []
            for i in range(self.list_index_dirs.count()):
                item = self.list_index_dirs.item(i)
                data = item.data(Qt.UserRole)
                if isinstance(data, dict):
                    index_directories.append(data)
                else:
                    parts = item.text().split(" ➔ ")
                    local_path = parts[0]
                    nas_folder = parts[1] if len(parts) > 1 else ""
                    index_directories.append({"local_path": local_path, "nas_folder": nas_folder})
                    
            cfg["index_directories"] = index_directories
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_nasdirs_status.setText("✅ 已保存")
        except Exception as e:
            self.lbl_nasdirs_status.setText(f"❌ {e}")
            log.error(f"保存 NAS 入库目录配置失败: {e}")

    def _test_matdb_connection(self):
        self._save_matdb_config()
        self.lbl_matdb_status.setText("正在连接…")
        host = self.edit_matdb_host.text().strip()
        port = self.spin_matdb_port.value()
        dbname = self.edit_matdb_name.text().strip()
        user = self.edit_matdb_user.text().strip()
        password = self.edit_matdb_pass.text()
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=host, port=port, dbname=dbname,
                user=user, password=password, connect_timeout=5
            )
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM materials")
            cnt = cur.fetchone()[0]
            conn.close()
            self.lbl_matdb_status.setText(
                f"<font color='#16a34a'>✅ 连接成功，materials 表共 {cnt} 条记录</font>"
            )
        except Exception as e:
            self.lbl_matdb_status.setText(
                f"<font color='#dc2626'>❌ 连接失败: {e}</font>"
            )
