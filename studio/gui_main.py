# -*- coding: utf-8 -*-
import sys
import os

# Configure CUDA/cuDNN DLL paths for Windows embedded Python immediately at startup
# (Must be done before importing torch or other libraries that rely on CUDA DLLs)
import site
packages_dirs = []
try:
    packages_dirs.extend(site.getsitepackages())
except Exception:
    pass
try:
    packages_dirs.append(site.getusersitepackages())
except Exception:
    pass
try:
    base_dir = os.path.dirname(sys.executable)
    packages_dirs.append(os.path.join(base_dir, "Lib", "site-packages"))
    packages_dirs.append(os.path.join(base_dir, "lib", "site-packages"))
except Exception:
    pass
for p in packages_dirs:
    if p and os.path.isdir(p):
        nvidia_base = os.path.join(p, "nvidia")
        if os.path.isdir(nvidia_base):
            for sub in ["cublas", "cudnn"]:
                bin_path = os.path.join(nvidia_base, sub, "bin")
                if os.path.isdir(bin_path):
                    if bin_path not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(bin_path)
                        except Exception:
                            pass

# Set domestic Hugging Face mirror to prevent hanging and speed up model downloads
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# Set explicit AppUserModelID for Windows taskbar icon support
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("luosiding.ecommerce.agent.matrix.2.0")
except Exception:
    pass

# Prevent black command prompt windows from popping up on Windows when running CLI tasks
import subprocess
class _patched_Popen(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["creationflags"] |= subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
subprocess.Popen = _patched_Popen

# Prevent crash when sys.stdout or sys.stderr is None (under pythonw.exe)
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

# Add project root and workspace root to Python path to ensure local and app modules are found
# frozen（PyInstaller 打包）模式下依赖已内嵌，跳过源码目录注入
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT, CONFIG_DIR
)

os.environ.setdefault("TMP", TMP_DIR)
os.environ.setdefault("TEMP", TMP_DIR)
os.environ.setdefault("TMPDIR", TMP_DIR)

# One-time migration of pw-browsers from old locations to the root apps directory
_old_pw_dir = os.path.join(RUNTIME_DIR, "pw-browsers")
_subproject_pw_dir = os.path.join(PROJECT_ROOT, "apps", "pw-browsers")

for old_dir in [_old_pw_dir, _subproject_pw_dir]:
    if os.path.exists(old_dir) and not os.path.exists(PW_BROWSERS_DIR):
        try:
            import shutil
            os.makedirs(os.path.dirname(PW_BROWSERS_DIR), exist_ok=True)
            shutil.move(old_dir, PW_BROWSERS_DIR)
            print(f"Successfully migrated pw-browsers from {old_dir} to: {PW_BROWSERS_DIR}")
            # Clean up empty parent apps folder in subproject if needed
            subproject_apps = os.path.join(PROJECT_ROOT, "apps")
            if os.path.exists(subproject_apps) and not os.listdir(subproject_apps):
                os.rmdir(subproject_apps)
        except Exception as _e:
            print(f"Failed to migrate pw-browsers directory from {old_dir}: {_e}")

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", PW_BROWSERS_DIR)

import threading
import uuid
import configparser

# --- Environment Diagnostic ---
def print_env_info():
    try:
        log_file = os.path.join(LOG_DIR, "app.log")
        with open(log_file, "a", encoding="utf-8") as f:
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n[{now}] DEBUG: Python Executable: {sys.executable}\n")
            f.write(f"[{now}] DEBUG: sys.path: {sys.path}\n")
        print(f"Python Executable: {sys.executable}")
    except:
        pass

print_env_info()

try:
    import json
    import time
    import random
    import re
    import requests
    import subprocess
    import zipfile
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    # Try to provide advice based on the missing module
    if "requests" in str(e):
        print("Please install 'requests' using: pip install requests")
    sys.exit(1)
try:
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QDialog, QListWidget, 
                                 QListWidgetItem, QGridLayout, QFileDialog, 
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox)
    from PySide6.QtGui import QIcon, QFont, QPixmap, QSyntaxHighlighter, QTextCharFormat, QColor
    from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent, QSharedMemory
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    print("Please install PySide6 using: pip install PySide6 shiboken6")
    sys.exit(1)


class LogHighlighter(QSyntaxHighlighter):
    """用 QSyntaxHighlighter 给日志按级别着色，比 setHtml 稳定。"""
    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []
        for level, color in [("CRITICAL","#dc2626"),("ERROR","#ef4444"),
                              ("WARNING","#f59e0b"),("INFO","#e4e4e7"),("DEBUG","#6b7280")]:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._rules.append((f"| {level: <8} |", fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            if pattern in text:
                self.setFormat(0, len(text), fmt)
                return


from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
from gui.subtitle_removal_page import SubtitleRemovalPage
from gui.live_clip_page import LiveClipPage
from gui.voice_clone_page import VoiceClonePage
from gui.voice_samples_page import VoiceSamplesPage
from gui.video_ocr_page import VideoOcrPage
from gui.image_folder_ocr_page import ImageFolderOcrPage
from utils.logger_utils import log, get_last_logs
from utils.gui_icons import mdi_button, mdi_icon
from utils.account_manager import AccountManager
from core.creator_browser_controller import CreatorBrowserController
try:
    import psutil
except ImportError:
    psutil = None

from utils.thread_worker import TaskWorker as Worker



from gui.threads import SystemMonitorThread, ComfyWSThread, AIStatusCheckThread


class _StatsCollector(QThread):
    """后台线程：从远程服务器 /health 采集 CPU/RAM/GPU 资源状态。"""
    stats_ready = Signal(float, float, float, float, str)  # cpu, ram, up, down, gpu_vram

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def _get_server_url(self):
        """从 ai_config 读远程服务地址。"""
        try:
            import json as _json
            from config.paths import AI_CONFIG_FILE
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                    cfg = _json.load(f)
                url = (cfg.get("compute_server_url") or cfg.get("llm_vision_api_url") or "").strip()
                if url:
                    return url.rstrip("/")
        except Exception:
            pass
        return ""

    def run(self):
        import requests as _req
        while self._running:
            try:
                base = self._get_server_url()
                cpu = ram = 0.0
                up = down = 0.0
                gpu_vram = "--"

                if base:
                    try:
                        resp = _req.get(f"{base}/health", timeout=4)
                        if resp.status_code == 200:
                            d = resp.json()
                            cpu = float(d.get("cpu", {}).get("percent", 0))
                            mem = d.get("memory", {})
                            ram = float(mem.get("percent", 0))
                            gpu = d.get("gpu")
                            if gpu:
                                vram_used = float(gpu.get("vram_used_mb", 0)) / 1024.0
                                vram_total = float(gpu.get("vram_total_mb", 0)) / 1024.0
                                gpu_util = int(gpu.get("gpu_util_percent", 0))
                                gpu_vram = f"{vram_used:.1f}G/{vram_total:.1f}G {gpu_util}%"
                    except Exception:
                        pass

                self.stats_ready.emit(cpu, ram, up, down, gpu_vram)
            except Exception:
                pass
            time.sleep(3)

    def stop(self):
        self._running = False
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog


class SystemStatusOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_overlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)
        
        self.ollama_lbl = QLabel("Ollama: 🔴")
        self.vision_lbl = QLabel("视觉: 🔴")
        self.whisper_lbl = QLabel("语音: 🟢")
        self.clip_lbl = QLabel("向量: 🟢")
        self.clone_lbl = QLabel("克隆: 🔴")
        
        self.cpu_lbl = QLabel()
        self.ram_lbl = QLabel()
        self.gpu_lbl = QLabel()
        self.net_lbl = QLabel()
        
        def create_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFrameShadow(QFrame.Plain)
            sep.setFixedWidth(1)
            sep.setObjectName("status_separator")
            return sep
            
        layout.addWidget(self.ollama_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.vision_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.whisper_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.clip_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.clone_lbl)
        layout.addWidget(create_sep())
        
        layout.addWidget(self.cpu_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.ram_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.gpu_lbl)
        layout.addWidget(create_sep())
        layout.addWidget(self.net_lbl)
        
        self.setFixedSize(895, 26)
        
        self._cached_vram = "VRAM: --"

        # 后台线程采集 CPU/RAM/网速和 GPU 显存
        self._collector = _StatsCollector(self)
        self._collector.stats_ready.connect(self._on_stats_ready)
        self._collector.start()

    def update_ai_status(self, status):
        def _color(ok):
            return "<font color='#22c55e'>🟢</font>" if ok else "<font color='#ef4444'>🔴</font>"
        self.ollama_lbl.setText(f"Ollama: {_color(status.get('ollama_ok'))}")
        self.vision_lbl.setText(f"视觉: {_color(status.get('vision_ok'))}")
        self.whisper_lbl.setText(f"语音: {_color(status.get('whisper_ok'))}")
        self.clip_lbl.setText(f"向量: {_color(status.get('clip_ok'))}")
        self.clone_lbl.setText(f"克隆: {_color(status.get('clone_ok'))}")

    def _on_stats_ready(self, cpu, ram, up, down, gpu_vram):
        self.cpu_lbl.setText(f"CPU: <font color='#facc15'>{cpu:.0f}%</font>")
        self.ram_lbl.setText(f"RAM: <font color='#facc15'>{ram:.0f}%</font>")
        self.net_lbl.setText(f"<font color='#facc15'>{gpu_vram}</font>")
        self.gpu_lbl.setText(f"<font color='#8b949e'>🖥️ 服务器</font>")

    def update_stats(self):
        pass  # kept for compatibility

    def format_speed(self, bytes_per_sec):
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f}B"
        elif bytes_per_sec < 1024 * 1024:
            return f"{bytes_per_sec/1024:.1f}K"
        else:
            return f"{bytes_per_sec/1024/1024:.1f}M"


from gui.main_window_pages import PageSetupMixin


from gui.main_window_services import ServicesMixin


from gui.main_window_accounts import AccountsMixin


from gui.main_window_aigen import AIGenMixin


from gui.main_window_sidebar import SidebarMixin


from gui.main_window_installers import InstallersMixin
from gui.main_window_aiconfig import AIConfigMixin


class MainWindow(QMainWindow, PageSetupMixin, ServicesMixin, AccountsMixin, AIGenMixin, SidebarMixin, InstallersMixin, AIConfigMixin):
    def __init__(self, splash=None):
        super().__init__()
        self.splash = splash
        self._update_splash("正在初始化窗口参数...", 15)
        self.setWindowTitle("螺丝钉-电商智能体矩阵 v2.0.0 RC")
        self.resize(1300, 900)
        # Set Window Icon
        icon_path = os.path.join(PROJECT_ROOT, "assets", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self._update_splash("正在加载账号管理组件...", 30)
        self.account_manager = AccountManager()
        self.current_parsed_videos = []
        self.ai_config_file = os.path.join(PROJECT_ROOT, "config", "ai_config.json")
        self.ai_config_legacy_file = os.path.join(PROJECT_ROOT, "ai_config.json")
        self.load_ai_config()

        self._update_splash("正在配置独立浏览器 Profile...", 45)
        self.playwright_profile_path = os.path.join(PROJECT_ROOT, "playwright_profile")
        os.makedirs(self.playwright_profile_path, exist_ok=True)

        self.creator_pw_controller = None
        self.downloader_pw_controller = None
        self.creator_guidance_url = "https://creator.douyin.com/creator-micro/creative-guidance"
        self.creator_added_urls = []
        self.creator_current_video_url = ""
        self.creator_pw_poll_timer = QTimer(self)
        self._pw_install_running = False
        self._pw_auto_install_attempted = False
        self._pw_ready = False
        self.account_pw_controllers = {}

        self.refresh_timer = QTimer(self)
        self._avatar_workers = []
        self.active_workers = []
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self.refresh_server_tasks)
        
        self.task_progress_bars = {}
        self.task_status_items = {}
        self.download_tasks = []
        
        self._update_splash("正在构建主界面 UI 元素 (组件较多，可能耗时数秒)...", 65)
        self.setup_ui()
        
        # System status overlay
        self.status_overlay = SystemStatusOverlay(self)
        self.status_overlay.show()
        
        self._update_splash("正在检测 Playwright 运行状态...", 85)
        self.ensure_playwright_chromium_ready()
        
        self._update_splash("正在建立后台通信与系统资源监控服务...", 95)
        from utils import comfyui_client as comfy
        # 监控为被动探活：不为看状态而启动本地（auto_start=False），外部优先、本地已跑则用本地
        self.monitor = SystemMonitorThread(
            lambda: comfy.resolve_addr(self.ai_config, auto_start=False))
        self.monitor.stats_updated.connect(self.update_system_stats)
        # ComfyUI 默认不启动检测，用户可在「AI 设置」手动开启
        # self.monitor.start()
        
        self.comfy_ws = None
        # self.start_comfyui_websocket()
        
        # 启动后台大模型状态监测线程
        self._models_ready = False
        self.ai_status_collector = AIStatusCheckThread(self.ai_config_file)
        
        def handle_ai_status(status):
            if hasattr(self, "status_overlay") and self.status_overlay:
                self.status_overlay.update_ai_status(status)
            self._models_ready = status.get("ollama_ok", False) and status.get("vision_ok", False)

        self.ai_status_collector.status_updated.connect(handle_ai_status)
        self.ai_status_collector.start()

        self._update_splash("系统准备就绪，正在展现主界面...", 100)

    def _update_splash(self, text, value):
        if hasattr(self, 'splash') and self.splash:
            try:
                self.splash.status_lbl.setText(text)
                self.splash.progress.setValue(value)
                QApplication.processEvents()
            except Exception:
                pass

    def _on_theme_changed(self):
        """主题切换回调（立即保存，重启生效）。"""
        theme = self.theme_combo.currentData()
        from utils.theme_manager import save_theme
        save_theme(theme)
        self.theme_hint.setText(f"✅ 已保存为「{self.theme_combo.currentText()}」(重启后生效)")
        


    def update_system_stats(self, stats):
        if hasattr(self, 'cpu_label'):
            self.cpu_label.setText(f"CPU: {stats['cpu']}%")
            self.gpu_label.setText(f"显存: {stats['gpu']}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "status_overlay") and self.status_overlay:
            margin_right = 20
            margin_top = 20
            w = self.status_overlay.width()
            h = self.status_overlay.height()
            self.status_overlay.move(self.width() - w - margin_right, margin_top)

    def closeEvent(self, event):
        # Pop up confirmation dialog
        reply = QMessageBox.question(
            self,
            "退出确认",
            "您确定要退出程序吗？\n确认后，系统将自动安全关闭本软件启动的所有本地运行环境及后端服务。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            event.ignore()
            return

        # 静默清理后台服务（不弹 CloseSplash 窗口）
        try:
            if hasattr(self, "creator_pw_controller") and self.creator_pw_controller:
                self.creator_pw_controller.stop()
        except Exception:
            pass
        try:
            for _, ctrl in list(getattr(self, "account_pw_controllers", {}).items()):
                try:
                    ctrl.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(self, "monitor") and self.monitor:
                self.monitor.running = False
                self.monitor.wait()
        except Exception:
            pass
        try:
            if hasattr(self, "ai_status_collector") and self.ai_status_collector:
                self.ai_status_collector.running = False
                self.ai_status_collector.wait()
        except Exception:
            pass
        try:
            if hasattr(self, "comfy_ws") and self.comfy_ws:
                self.comfy_ws.running = False
                self.comfy_ws.wait()
        except Exception:
            pass
        try:
            from core.creator_browser_controller import close_all_active_browsers
            close_all_active_browsers()
        except Exception:
            pass

        try:
            super().closeEvent(event)
        except Exception:
            event.accept()


    def on_ws_progress(self, pid, percent):
        if pid in self.task_progress_bars:
            self.task_progress_bars[pid].setValue(percent)

    def on_ws_status(self, pid, status):
        log.info(f"WS Status: {pid} -> {status}")
        if pid in self.task_status_items:
            self.task_status_items[pid].setText(status)

    def setup_ui(self):
        # Stylesheet is applied globally by apply_theme() at startup
        
        # Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create Sidebar
        self.setup_sidebar()
        
        # Create Content Area
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("content_area")
        self.main_layout.addWidget(self.content_stack)
        
        # Setup Pages
        self.setup_pages()
        
        # Default Page
        self.switch_page(0)


    def setup_pages(self):
        # 0: Downloader (Disabled)
        self.page_downloader = QWidget()
        self.content_stack.addWidget(self.page_downloader)
        
        # 1: Hotspots
        self.page_hotspots = QWidget()
        self.setup_hotspots_page()
        self.content_stack.addWidget(self.page_hotspots)
        
        # 2: Search (Disabled)
        self.page_search = QWidget()
        self.content_stack.addWidget(self.page_search)
        
        # 3: Digital Human
        self.page_digital_human = QWidget()
        self.setup_digital_human_page()
        self.content_stack.addWidget(self.page_digital_human)
        
        # 4: Library/Downloads (Disabled)
        self.page_library = QWidget()
        self.content_stack.addWidget(self.page_library)
        
        # 5: Douyin Login
        self.page_login = QWidget()
        self.setup_login_page()
        self.content_stack.addWidget(self.page_login)

        # 6: System Logs
        self.page_logs = QWidget()
        self.setup_logs_page()
        self.content_stack.addWidget(self.page_logs)

        # 7: AI Settings
        self.page_ai_settings = QWidget()
        self.setup_ai_settings_page()
        self.content_stack.addWidget(self.page_ai_settings)

        # 8: Account Management
        self.page_accounts = QWidget()
        self.setup_accounts_page()
        self.content_stack.addWidget(self.page_accounts)

        # 9: Task List (New)
        self.page_task_list = QWidget()
        self.setup_task_list_page()
        self.content_stack.addWidget(self.page_task_list)

        # 10: Account Detail (New) - Adjusted index
        self.page_account_detail = QWidget()
        self.setup_account_detail_page()
        self.content_stack.addWidget(self.page_account_detail)

        # 11: Video Tools (New)
        self.page_video_tools = QWidget()
        self.setup_video_tools_page()
        self.content_stack.addWidget(self.page_video_tools)

        # 12: Transcription Tool (Video → Text)
        self.page_transcription = QWidget()
        self.setup_transcription_page()
        self.content_stack.addWidget(self.page_transcription)

        # 13: Environment Configuration
        self.page_env_config = QWidget()
        self.setup_env_config_page()
        self.content_stack.addWidget(self.page_env_config)

        # 14: Subtitle Removal Page
        self.page_subtitle_removal = QWidget()
        self.setup_subtitle_removal_page()
        self.content_stack.addWidget(self.page_subtitle_removal)

        # 15: Video Montage Tool (Smart Cut & Assemble)
        self.page_video_montage = QWidget()
        self.setup_video_montage_page()
        self.content_stack.addWidget(self.page_video_montage)

        # 16: Image Matting Page (Alpha Matting Cutout)
        self.page_image_matting = QWidget()
        self.setup_image_matting_page()
        self.content_stack.addWidget(self.page_image_matting)

        # 17: Image Layered Page (AI Image Layered Decomposition)
        self.page_image_layered = QWidget()
        self.setup_image_layered_page()
        self.content_stack.addWidget(self.page_image_layered)

        # 18: Subtitle Removal Page V14
        self.page_subtitle_removal_v14 = QWidget()
        self.setup_subtitle_removal_page_v14()
        self.content_stack.addWidget(self.page_subtitle_removal_v14)

        # 19: Live Clip Page
        self.page_live_clip = QWidget()
        self.setup_live_clip_page()
        self.content_stack.addWidget(self.page_live_clip)

        # 20: AI Video Script Page
        self.page_ai_script = QWidget()
        self.setup_ai_script_page()
        self.content_stack.addWidget(self.page_ai_script)

        # 21: Voice Cloning Page
        self.page_voice_clone = QWidget()
        self.setup_voice_clone_page()
        self.content_stack.addWidget(self.page_voice_clone)

        # 22: Voice Samples Page
        self.page_voice_samples = QWidget()
        self.setup_voice_samples_page()
        self.content_stack.addWidget(self.page_voice_samples)

        # 23: Large Model Configuration Page
        self.page_llm_settings = QWidget()
        self.setup_llm_settings_page()
        self.content_stack.addWidget(self.page_llm_settings)

        # 24: Video Box OCR Page
        self.page_video_ocr = QWidget()
        self.setup_video_ocr_page()
        self.content_stack.addWidget(self.page_video_ocr)

        # 25: Image Folder OCR Page
        self.page_image_folder_ocr = QWidget()
        self.setup_image_folder_ocr_page()
        self.content_stack.addWidget(self.page_image_folder_ocr)

        # 26: Video AI Rename Page
        self.page_video_ai_rename = QWidget()
        self.setup_video_ai_rename_page()
        self.content_stack.addWidget(self.page_video_ai_rename)

        # 27: Video LUT Batch Conversion Page
        self.page_video_lut = QWidget()
        self.setup_video_lut_page()
        self.content_stack.addWidget(self.page_video_lut)

        # 28: Product Knowledge Base Page
        self.page_product_library = QWidget()
        self.setup_product_library_page()
        self.content_stack.addWidget(self.page_product_library)

        # 29: My Knowledge Base Page
        self.page_my_knowledge = QWidget()
        self.setup_my_knowledge_page()
        self.content_stack.addWidget(self.page_my_knowledge)

        # 30: Product Script (copywriting) Page
        self.page_product_script = QWidget()
        self.setup_product_script_page()
        self.content_stack.addWidget(self.page_product_script)

        # 31: Media Library (素材管理) Page (Disabled/Removed)
        self.page_media_library = QWidget()
        self.content_stack.addWidget(self.page_media_library)

        # 32: Dreamina (即梦生成) Page
        self.page_dreamina = QWidget()
        self.setup_dreamina_page()
        self.content_stack.addWidget(self.page_dreamina)

        # 33: Cover Maker (封面制作) Page
        self.page_cover_maker = QWidget()
        self.setup_cover_maker_page()
        self.content_stack.addWidget(self.page_cover_maker)

        # 34: One-click Compile Video (一键成片) Page
        self.page_compile_video = QWidget()
        self.setup_compile_video_page()
        self.content_stack.addWidget(self.page_compile_video)

        # 35: Hook Score (开头黄金3秒评分) Page
        self.page_hook_score = QWidget()
        self.setup_hook_score_page()
        self.content_stack.addWidget(self.page_hook_score)

        # 36: MG Animation (Remotion) Page
        self.page_mg_animation = QWidget()
        self.setup_mg_animation_page()
        self.content_stack.addWidget(self.page_mg_animation)

        # 37: Data Backup / Restore Page
        self.page_backup = QWidget()
        self.setup_backup_page()
        self.content_stack.addWidget(self.page_backup)

        # 38: Storyboard (分镜脚本) Page（原热点追踪页已彻底移除，功能并入素材浏览器）
        self.page_storyboard = QWidget()
        self.setup_storyboard_page()
        self.content_stack.addWidget(self.page_storyboard)

        # 40: Vector Search (向量检索) Page
        self.page_vector_search = QWidget()
        self.setup_vector_search_page()
        self.content_stack.addWidget(self.page_vector_search)

        # 41: Python Terminal (内嵌终端) Page
        self.page_terminal = QWidget()
        self.setup_terminal_page()
        self.content_stack.addWidget(self.page_terminal)

        # 42: Marketing Video Detection Page
        self.page_marketing_detect = QWidget()
        self.setup_marketing_detect_page()
        self.content_stack.addWidget(self.page_marketing_detect)

        # 43: Dreamina Assets (即梦素材) Page
        self.page_dreamina_assets = QWidget()
        self.setup_dreamina_assets_page()
        self.content_stack.addWidget(self.page_dreamina_assets)

        # 44: Scheduled Tasks (定时任务) Page —— 监控服务端定时任务
        self.page_scheduled_tasks = QWidget()
        self.setup_scheduled_tasks_page()
        self.content_stack.addWidget(self.page_scheduled_tasks)

        # 进入定时任务页时刷新（拉取最新服务端状态）
        def _on_page_change(idx):
            if idx == 44 and hasattr(self, "scheduled_tasks_tool"):
                self.scheduled_tasks_tool.refresh()
        self.content_stack.currentChanged.connect(_on_page_change)


    def trigger_page_logic(self, index):
        """Triggers data refresh or UI reset for specific pages"""
        if index == 9: # Task List
            self.refresh_server_tasks()
            # _sync_server_tasks 异步执行（不在主线程阻塞）
            QTimer.singleShot(100, self._sync_server_tasks_async)
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

        # 热点页面：只在活跃时轮询，离开后立即停止（减少主线程常驻 2次/秒 事件回调）
        if index == 1:
            if hasattr(self, "creator_pw_poll_timer") and not self.creator_pw_poll_timer.isActive():
                self.creator_pw_poll_timer.start()
        else:
            if hasattr(self, "creator_pw_poll_timer") and self.creator_pw_poll_timer.isActive():
                self.creator_pw_poll_timer.stop()

        if index == 6: # Logs
            self.refresh_logs()
        elif index == 8: # Accounts
            self.refresh_accounts_list()
        elif index == 12: # Transcription
            pass
        elif index == 37: # 运行环境
            if hasattr(self, "env_config_tool"):
                self.env_config_tool.refresh_status()
        elif index == 7: # System Config
            if hasattr(self, "refresh_llm_page_status"):
                self.refresh_llm_page_status()
        elif index == 21: # Voice Clone
            if hasattr(self, "voice_clone_tool"):
                self.voice_clone_tool._populate_ref_audio_samples()
        elif index == 35: # Hook Score
            if hasattr(self, "hook_score_tool"):
                self.hook_score_tool.update_vision_model_display()
        elif index == 41: # Marketing Video Detection
            if hasattr(self, "marketing_detect_tool"):
                self.marketing_detect_tool.update_vision_model_display()
        elif index == 43: # 即梦素材
            if hasattr(self, "dreamina_assets_tool"):
                try:
                    self.dreamina_assets_tool._scan_local_files()
                except Exception as e:
                    log.error(f"刷新即梦素材列表失败: {e}")
        elif index == 38: # Storyboard
            if hasattr(self, "storyboard_tool"):
                self.storyboard_tool.reload_sources()
        elif index == 22: # 资源配置
            if hasattr(self, "voice_samples_tool"):
                self.voice_samples_tool._load_table_data()
            if hasattr(self, "_load_lut_config"):
                self._load_lut_config()








    def setup_subtitle_removal_page_v14(self):
        from gui.subtitle_removal_page_v14 import SubtitleRemovalPageV14
        self.subtitle_removal_tool_v14 = SubtitleRemovalPageV14(self.page_subtitle_removal_v14, self)
        self.subtitle_removal_tool_v14.setup()























    def refresh_creator_guidance(self):
        if not self.creator_pw_controller or not self.creator_pw_controller.is_running():
            self.open_creator_guidance_browser()
            return
        self.creator_pw_controller.goto(self.creator_guidance_url)

    def apply_creator_guidance_category(self, category):
        if not self.creator_pw_controller or not self.creator_pw_controller.is_running():
            self.open_creator_guidance_browser()
        if self.creator_pw_controller:
            self.creator_pw_controller.click_category(category)

    def open_creator_guidance_browser(self):
        if not self.is_playwright_chromium_present():
            if hasattr(self, "cg_status_label"):
                self.cg_status_label.setText("正在准备 Playwright Chromium 内核，请稍后重试打开。")
            if not self._pw_install_running:
                self.install_playwright_chromium()
            return
            
        profile_id = "system_default_profile"

        if self.creator_pw_controller and self.is_pw_controller_usable(self.creator_pw_controller):
            self.creator_pw_controller.goto(self.creator_guidance_url)
            return
        if self.creator_pw_controller and not self.is_pw_controller_usable(self.creator_pw_controller):
            try:
                self.creator_pw_controller.stop()
            except Exception:
                pass
            self.creator_pw_controller = None

        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", profile_id)
        os.makedirs(user_data_dir, exist_ok=True)
        
        self.creator_pw_controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=PW_BROWSERS_DIR,
            headless=False,
        )
        self.creator_pw_controller.start()
        QTimer.singleShot(300, lambda: self.creator_pw_controller.goto(self.creator_guidance_url) if self.creator_pw_controller else None)

    def close_creator_guidance_browser(self):
        if self.creator_pw_controller:
            self.creator_pw_controller.stop()
            self.creator_pw_controller = None

    def poll_creator_browser_state(self):
        if not self.creator_pw_controller:
            if hasattr(self, "cg_add_btn"):
                self.cg_add_btn.setEnabled(False)
            return
        status, video_url, last_error = self.creator_pw_controller.get_status()
        self.creator_current_video_url = video_url or ""
        missing_chromium = bool(
            last_error
            and (
                "Executable doesn't exist" in last_error
                or "playwright install" in last_error
                or "chromium" in last_error.lower()
            )
        )
        if missing_chromium:
            status = "未检测到 Playwright Chromium 内核：将自动下载/解压内置 Chromium"
            if not self._pw_auto_install_attempted and not self._pw_install_running:
                self._pw_auto_install_attempted = True
                QTimer.singleShot(200, self.install_playwright_chromium)
        if hasattr(self, "cg_status_label"):
            self.cg_status_label.setText(status)
        if hasattr(self, "cg_current_url_edit"):
            self.cg_current_url_edit.setText(self.creator_current_video_url)
        if hasattr(self, "cg_add_btn"):
            self.cg_add_btn.setEnabled(bool(self.creator_current_video_url))
        if hasattr(self, "cg_error_label"):
            self.cg_error_label.setText(last_error or "")


    def add_current_creator_video_to_queue(self):
        url = self.creator_current_video_url
        if not url:
            QMessageBox.information(self, "提示", "当前无法识别视频链接。")
            return

        self.add_videos_to_download_queue([url], switch_page=False, show_message=False)
        if url not in self.creator_added_urls:
            self.creator_added_urls.append(url)
            self.refresh_creator_queue_table()
        if hasattr(self, "cg_status_label"):
            self.cg_status_label.setText("已加入下载队列")

    def refresh_creator_queue_table(self):
        if not hasattr(self, "cg_queue_table"):
            return
        self.cg_queue_table.setRowCount(0)
        for i, url in enumerate(self.creator_added_urls):
            self.cg_queue_table.insertRow(i)
            it = QTableWidgetItem(url)
            it.setToolTip(url)
            self.cg_queue_table.setItem(i, 0, it)
            btn_rm = QPushButton("移除")
            btn_rm.setObjectName("secondary_button")
            btn_rm.clicked.connect(lambda checked=False, u=url: self.remove_creator_queue_url(u))
            self.cg_queue_table.setCellWidget(i, 1, btn_rm)
        if hasattr(self, "cg_queue_count"):
            self.cg_queue_count.setText(str(len(self.creator_added_urls)))

    def remove_creator_queue_url(self, url):
        if not url:
            return
        if url in self.creator_added_urls:
            self.creator_added_urls = [u for u in self.creator_added_urls if u != url]
            self.refresh_creator_queue_table()
            if hasattr(self, "cg_status_label"):
                self.cg_status_label.setText("已移除")

    def select_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        if file:
            self.img_path_input.setText(file)

    def select_audio(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择音频", "", "Audio (*.mp3 *.wav)")
        if file:
            self.aud_path_input.setText(file)





    def open_system_default_browser(self):
        if not self.is_playwright_chromium_present():
            QMessageBox.information(self, "提示", "正在准备 Playwright Chromium 内核，请先完成内核安装。")
            self.ensure_playwright_chromium_ready()
            return
            
        if self.system_default_login_controller and self.system_default_login_controller.is_running():
            self.system_default_login_controller.goto("https://www.douyin.com")
            return
            
        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", "system_default_profile")
        os.makedirs(user_data_dir, exist_ok=True)
        
        from core.creator_browser_controller import CreatorBrowserController
        self.system_default_login_controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=PW_BROWSERS_DIR,
            headless=False
        )
        self.system_default_login_controller.start()
        QTimer.singleShot(500, lambda: self.system_default_login_controller.goto("https://www.douyin.com"))
        QMessageBox.information(self, "提示", "已为您在外部启动独立登录窗口。\n请在弹出的 Chromium 窗口内登录抖音，完成后点击「提取并同步 Cookie」。")

    def sync_system_default_cookie(self):
        if not self.system_default_login_controller or not self.system_default_login_controller.is_running():
            QMessageBox.warning(self, "错误", "登录浏览器未运行或已关闭，请先点击「打开独立登录窗口」。")
            return
            
        cookies = self.system_default_login_controller.get_cookies()
        if not cookies:
            QMessageBox.warning(self, "提示", "未读取到 Cookie，请确认已在外部浏览器登录成功。")
            return
            
        jar = {}
        for c in cookies:
            domain = str(c.get("domain", "") or "")
            if "douyin.com" not in domain:
                continue
            name = c.get("name")
            value = c.get("value")
            if not name:
                continue
            if name not in jar:
                jar[name] = value if value is not None else ""
                
        cookie_str = "; ".join([f"{k}={v}" for k, v in jar.items()])
        if not cookie_str:
            QMessageBox.warning(self, "提示", "未筛选到可用的 douyin.com Cookie。")
            return
            
        try:
            cookie_path_root = os.path.join(PROJECT_ROOT, "douyin_cookies.txt")
            cookie_path_runtime = os.path.join(COOKIES_DIR, "douyin_cookies.txt")
            
            with open(cookie_path_root, "w", encoding="utf-8") as f:
                f.write(cookie_str)
            with open(cookie_path_runtime, "w", encoding="utf-8") as f:
                f.write(cookie_str)
                
            self.system_default_login_controller.stop()
            self.update_system_default_login_status()
            QMessageBox.information(self, "成功", "系统默认 Cookie 同步并保存成功！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 Cookie 失败: {e}")

    def add_task_to_list(self, prompt_id, status="正在运行", task_type="ComfyUI", source="服务端"):
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        self.task_table.setItem(row, 0, QTableWidgetItem(prompt_id[:12]))
        self.task_table.setItem(row, 1, QTableWidgetItem(task_type))
        source_item = QTableWidgetItem(source)
        if source == "本地":
            source_item.setForeground(QColor("#4ade80"))
        else:
            source_item.setForeground(QColor("#60a5fa"))
        self.task_table.setItem(row, 2, source_item)
        
        status_item = QTableWidgetItem(status)
        self.task_table.setItem(row, 3, status_item)
        self.task_status_items[prompt_id] = status_item
        
        p_bar = QProgressBar()
        p_bar.setValue(0)
        p_bar.setTextVisible(True)
        self.task_table.setCellWidget(row, 4, p_bar)
        self.task_progress_bars[prompt_id] = p_bar

        # 创建时间
        from datetime import datetime
        time_str = datetime.now().strftime("%m-%d %H:%M")
        self.task_table.setItem(row, 5, QTableWidgetItem(time_str))

        # Action column
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(5, 2, 5, 2)
        actions_layout.setSpacing(5)

        btn_preview = mdi_button("", "eye")
        btn_preview.setToolTip("预览")
        btn_preview.setFixedSize(30, 24)
        btn_preview.setEnabled(False)
        btn_preview.clicked.connect(lambda: self.preview_result(prompt_id))

        btn_download = mdi_button("", "save")
        btn_download.setToolTip("下载")
        btn_download.setFixedSize(30, 24)
        btn_download.setEnabled(False)
        btn_download.clicked.connect(lambda: self.download_result(prompt_id))

        actions_layout.addWidget(btn_preview)
        actions_layout.addWidget(btn_download)
        self.task_table.setCellWidget(row, 6, actions_widget)

    def update_task_actions(self, prompt_id):
        for row in range(self.task_table.rowCount()):
            if self.task_table.item(row, 0).text() == prompt_id[:12]:
                w = self.task_table.cellWidget(row, 6)
                if w:
                    for btn in w.findChildren(QPushButton):
                        btn.setEnabled(True)
                break

    def preview_result(self, prompt_id):
        outputs = self.task_outputs.get(prompt_id, [])
        if not outputs:
             QMessageBox.information(self, "提示", "未找到输出文件。")
             return
             
        from utils import comfyui_client as comfy
        comfyui_addr = comfy.resolve_addr(self.ai_config, auto_start=False)
        # Pick first output for preview
        out = outputs[0]
        url = comfy.view_url(comfyui_addr, out['filename'], out['type'])
        
        import webbrowser
        webbrowser.open(url) # Simplest for now, as QWebEngine might be overkill for quick preview

    def download_result(self, prompt_id):
        outputs = self.task_outputs.get(prompt_id, [])
        if not outputs: return
        
        from utils import comfyui_client as comfy
        comfyui_addr = comfy.resolve_addr(self.ai_config, auto_start=False)
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if not save_dir: return

        for out in outputs:
            url = comfy.view_url(comfyui_addr, out['filename'], out['type'])
            local_path = os.path.join(save_dir, out['filename'])
            
            def do_download(u=url, p=local_path):
                try:
                    import requests
                    r = requests.get(u, stream=True)
                    with open(p, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return True, p
                except Exception as e:
                    return False, str(e)

            def on_finished(res):
                success, info = res
                if success:
                    log.info(f"Downloaded: {info}")
                else:
                    QMessageBox.warning(self, "下载失败", f"文件下载失败: {info}")

            worker = Worker(do_download)
            worker.finished.connect(on_finished)
            worker.start()

    def extract_and_save_cookies(self):
        self.browser.page().runJavaScript("document.cookie", self.save_cookies_to_file)

    def save_cookies_to_file(self, cookie_str):
        if cookie_str:
            cookie_path = os.path.join(COOKIES_DIR, "douyin_cookies.txt")
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(cookie_str)
            QMessageBox.information(self, "成功", f"Cookie 已同步并保存至: {cookie_path}")

    def set_remote_image(self, url, label, size=(64, 64)):
        """Helper to fetch and set a remote image on a QLabel asynchronously"""
        def fetch_image():
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return response.content
            except Exception as e:
                log.error(f"Failed to fetch image {url}: {e}")
            return None

        def on_fetched(data):
            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                if not pixmap.isNull():
                    label.setPixmap(pixmap.scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    label.setStyleSheet("border-radius: %dpx; border: 2px solid #fff;" % (size[0]//2))

        worker = Worker(fetch_image)
        worker.finished.connect(on_fetched)
        self.active_workers.append(worker) # Keep reference
        worker.start()






    def is_pw_controller_usable(self, controller):
        if not controller or not controller.is_running():
            return False
        try:
            status, _, err = controller.get_status()
        except Exception:
            return False
        if not status:
            return False
        bad_status = ("已停止" in status) or ("启动失败" in status) or ("已关闭" in status)
        bad_err = bool(err) and (("Target closed" in err) or ("has been closed" in err) or ("Browser has been closed" in err))
        return not (bad_status or bad_err)






    # ── 并发控制：最多同时运行 3 个 AI 任务 ──
    MAX_CONCURRENT_WORKERS = 3

    def start_worker(self, func, on_finished=None, on_error=None):
        """Helper to start a worker thread and keep it alive until finished.
        同时最多 3 个并发，超出的自动排队等待。"""
        active_count = len([w for w in self.active_workers if w.isRunning()])
        if active_count >= self.MAX_CONCURRENT_WORKERS:
            QTimer.singleShot(500, lambda: self.start_worker(func, on_finished, on_error))
            log.info(f"[并发控制] 当前 {active_count} 个任务运行中，排队等待...")
            return None

        worker = Worker(func)
        self.active_workers.append(worker)
        
        if on_finished:
            worker.finished.connect(on_finished)
        if on_error:
            worker.error.connect(on_error)
            
        def cleanup():
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.finished.connect(cleanup)
        worker.error.connect(lambda _: cleanup())
        worker.start()
        return worker




    def refresh_logs(self):
        level_filter = getattr(self, "log_level_filter", None)
        keyword_filter = getattr(self, "log_keyword_input", None)
        btn_server = getattr(self, "btn_server_log", None)
        level_text = level_filter.currentText() if level_filter else "全部"
        keyword = keyword_filter.text().strip() if keyword_filter else ""

        # 服务端日志按钮勾选时，自动加上服务端相关关键词
        if btn_server and btn_server.isChecked():
            server_keys = ["[ASR]", "[_RemoteWorker]", "[RemoteTranscribeWorker]", "[VoxCPM]", "POST ", "HTTP "]
            if keyword:
                keyword = f"({keyword})|{'|'.join(server_keys)}"
            else:
                keyword = "|".join(server_keys)
            keyword_filter.setText(f"[服务端] {keyword[:50]}")

        raw = get_last_logs(2000)
        lines = raw.split("\n")

        if level_text != "全部":
            lines = [l for l in lines if f"| {level_text: <8} |" in l or f"| {level_text}" in l]

        if keyword:
            lines = [l for l in lines if keyword.lower() in l.lower()]

        lines = lines[-500:]

        self.log_viewer.setPlainText("\n".join(lines))
        # 首次调用时挂上高亮器（只挂一次）
        if not hasattr(self, "_log_highlighter"):
            self._log_highlighter = LogHighlighter(self.log_viewer.document())
        self.log_viewer.verticalScrollBar().setValue(
            self.log_viewer.verticalScrollBar().maximum()
        )







if __name__ == "__main__":
    # COSMIC Wayland 下 QComboBox 弹窗定位有 bug，强制 X11 后端
    import os as _os
    if _os.environ.get("XDG_SESSION_TYPE") == "wayland":
        _os.environ["QT_QPA_PLATFORM"] = "xcb"

    # ── 试用白名单 + License 验证 ──
    # 安全说明：曾经有 TINTIN_NO_LICENSE=1 环境变量可一键绕过全部校验，
    # 那是个严重后门，已彻底移除——验证逻辑无条件执行，任何环境变量都不再有效。
    # 开发调试如需免激活，请把机器码加入 studio/config/trial_whitelist.json。
    from utils.license import (
        get_machine_id, check_trial_whitelist,
        verify_license, LicenseError,
        load_activation_cache,
    )
    _access_granted = True
    _machine_id = get_machine_id()
    log.info("[License] 服务端采用激活机制，客户端免激活放行。")

    log.info("Application starting...")
    try:
        app = QApplication(sys.argv)

        # ── 激活对话框（无有效授权时弹出）──
        if not _access_granted:
            from gui.dialogs import ActivationDialog
            _dialog = ActivationDialog(_machine_id)
            _dialog.exec()
            if not _dialog.is_activated():
                sys.exit(0)

        # ── 单例保护：只允许运行一个实例 ──
        _is_already_running = False
        # Windows: 命名互斥量，进程退出/崩溃时OS自动释放，无残留无延迟
        import ctypes as _ctypes
        _mutex = _ctypes.windll.kernel32.CreateMutexW(None, False, "luosiding.ecommerce.agent.matrix.single_instance")
        if _ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            _is_already_running = True
        if _is_already_running:
            from PySide6.QtWidgets import QMessageBox as _QMB
            _QMB.warning(None, "提示", "电商智能体矩阵已在运行中，请勿重复启动。")
            sys.exit(0)

        app.setAttribute(Qt.AA_DontUseNativeDialogs, True)  # 主题对话框
        app.setStyle("Fusion")
        from utils.theme_manager import apply_theme
        apply_theme(app)
        try:
            from PySide6.QtGui import QFont
            font = QFont("Microsoft YaHei UI", 10)
            app.setFont(font)
        except Exception:
            pass
        
        # Show startup loading splash window
        splash = StartupSplash()
        splash.show()
        QApplication.processEvents()
        
        # Pass splash instance to MainWindow constructor
        window = MainWindow(splash=splash)
        
        # Center the window before showing to avoid flash
        try:
            from PySide6.QtGui import QCursor
            active_screen = QApplication.screenAt(QCursor.pos())
            if not active_screen:
                active_screen = QApplication.primaryScreen()
            screen = active_screen.geometry()
            screen_w = screen.width(); screen_h = screen.height()
            win_w = 1300; win_h = 900
            if screen_w < win_w: win_w = int(screen_w * 0.95)
            if screen_h < win_h: win_h = int(screen_h * 0.95)
            x = screen.x() + (screen_w - win_w) // 2
            y = screen.y() + (screen_h - win_h) // 2
            window.resize(win_w, win_h)
            window.move(x, y)
            log.info(f"Centered window on screen {active_screen.name()} at ({x}, {y}) size {win_w}x{win_h}")
        except Exception as e:
            log.error(f"Failed to center window: {e}")

        splash.close()
        window.show()
            
        log.info("MainWindow shown successfully.")
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        traceback.print_exc()
        log.critical(f"FATAL ERROR during startup: {e}")
        print(f"FATAL ERROR: {e}")
        sys.exit(1)
