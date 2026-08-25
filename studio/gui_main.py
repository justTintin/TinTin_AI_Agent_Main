import contextlib
import os

# Configure CUDA/cuDNN DLL paths for Windows embedded Python immediately at startup
# (Must be done before importing torch or other libraries that rely on CUDA DLLs)
import site
import sys
from typing import Any

packages_dirs = []
with contextlib.suppress(Exception):
    packages_dirs.extend(site.getsitepackages())
with contextlib.suppress(Exception):
    packages_dirs.append(site.getusersitepackages())
try:
    base_dir = os.path.dirname(sys.executable)
    packages_dirs.append(os.path.join(base_dir, "Lib", "site-packages"))
    packages_dirs.append(os.path.join(base_dir, "lib", "site-packages"))
except (TypeError, AttributeError):  # sys.executable 可能为 None
    pass
for p in packages_dirs:
    if p and os.path.isdir(p):
        nvidia_base = os.path.join(p, "nvidia")
        if os.path.isdir(nvidia_base):
            for sub in ["cublas", "cudnn"]:
                bin_path = os.path.join(nvidia_base, sub, "bin")
                if os.path.isdir(bin_path):
                    if bin_path not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = (
                        bin_path + os.pathsep + os.environ.get("PATH", "")
                    )  # noqa: E501
                    if hasattr(os, "add_dll_directory"):
                        with contextlib.suppress(OSError):
                            os.add_dll_directory(bin_path)

# Set domestic Hugging Face mirror to prevent hanging and speed up model downloads
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# Set explicit AppUserModelID for Windows taskbar icon support
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "luosiding.ecommerce.agent.matrix.2.0"
    )  # noqa: E501
except Exception:  # ctypes.windll Windows 外部API，跨平台兼容
    pass
import subprocess  # noqa: E402


class _patched_Popen(subprocess.Popen):  # noqa: N801
    def __init__(self, *args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["creationflags"] |= subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
subprocess.Popen = _patched_Popen  # type: ignore[misc]

# Prevent crash when sys.stdout or sys.stderr is None (under pythonw.exe)
if sys.stdout is None:
    with contextlib.suppress(OSError):
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    with contextlib.suppress(OSError):
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

# Check NVIDIA Management Library availability
try:
    import pynvml as _pynvml
    _pynvml  # noqa: B018
    HAS_NVML = True
except Exception:
    HAS_NVML = False

# Add project root and workspace root to Python path
# to ensure local and app modules are found  # noqa: E501
# frozen（PyInstaller 打包）模式下依赖已内嵌，跳过源码目录注入
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import COOKIES_DIR, LOG_DIR, PROJECT_ROOT, PW_BROWSERS_DIR, RUNTIME_DIR, TMP_DIR  # noqa: E402, E501
from version import __app_name__, get_version  # noqa: E402

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
            print(f"Successfully migrated pw-browsers from {old_dir} to: {PW_BROWSERS_DIR}")  # noqa: E501
            # Clean up empty parent apps folder in subproject if needed
            subproject_apps = os.path.join(PROJECT_ROOT, "apps")
            if os.path.exists(subproject_apps) and not os.listdir(subproject_apps):
                os.rmdir(subproject_apps)
        except OSError as _e:
            print(f"Failed to migrate pw-browsers directory from {old_dir}: {_e}")

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", PW_BROWSERS_DIR)


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
    except OSError:
        pass

print_env_info()

try:
    import json
    import subprocess
    import time

    import requests
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    # Try to provide advice based on the missing module
    if "requests" in str(e):
        print("Please install 'requests' using: pip install requests")
    sys.exit(1)
try:  # noqa: F401 — startup dependency check
    from PySide6.QtCore import (  # noqa: F401
        QEvent,  # noqa: F401
        QSharedMemory,  # noqa: F401
        QSize,  # noqa: F401
        Qt,
        QThread,
        QTimer,
        QUrl,  # noqa: F401
        Signal,  # noqa: F401
    )
    from PySide6.QtGui import (
        QColor,
        QFont,
        QIcon,
        QPixmap,
        QSyntaxHighlighter,
        QTextCharFormat,  # noqa: F401
    )
    from PySide6.QtWidgets import (  # noqa: F401
        QAbstractItemView,  # noqa: F401
        QApplication,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,  # noqa: F401
        QGridLayout,
        QGroupBox,
        QHBoxLayout,  # noqa: F401
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,  # noqa: F401
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,  # noqa: F401
        QPushButton,
        QScrollArea,  # noqa: F401
        QSizePolicy,
        QSpinBox,  # noqa: F401
        QSplitter,
        QStackedWidget,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,  # noqa: F401
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:
    print(f"CRITICAL ERROR: Missing dependency: {e}")
    print("Please install PySide6 using: pip install PySide6 shiboken6")
    sys.exit(1)

from utils.file_dialog_utils import pick_directory  # noqa: E402


class LogHighlighter(QSyntaxHighlighter):
    """用 QSyntaxHighlighter 给日志按级别着色，比 setHtml 稳定。"""
    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []
        for level, color in [("CRITICAL","#dc2626"),("ERROR","#ef4444"),
                              ("WARNING","#f59e0b"),("INFO","#e4e4e7"),("DEBUG","#6b7280")]:  # noqa: E501
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._rules.append((f"| {level: <8} |", fmt))

    def highlightBlock(self, text):  # noqa: N802
        for pattern, fmt in self._rules:
            if pattern in text:
                self.setFormat(0, len(text), fmt)
                return


from core.creator_browser_controller import CreatorBrowserController  # noqa: E402
from utils.account_manager import AccountManager  # noqa: E402
from utils.gui_icons import mdi_button  # noqa: E402
from utils.logger_utils import get_last_logs, log  # noqa: E402

try:
    import psutil
except ImportError:
    psutil = None

from gui.threads import AIStatusCheckThread  # noqa: E402
from utils.thread_worker import TaskWorker as Worker  # noqa: E402


class _StatsCollector(QThread):
    """后台线程：从远程服务器 /health 采集 CPU/RAM/GPU 资源状态。"""
    stats_ready = Signal(float, float, float, float, str)  # cpu, ram, up, down, gpu_vram  # noqa: E501

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
                url = (cfg.get("compute_server_url") or cfg.get("llm_vision_api_url") or "").strip()  # noqa: E501
                if url:
                    return url.rstrip("/")
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        return ""

    def run(self):
        from utils.http_client import http_get
        consecutive_failures = 0
        while self._running:
            ok = False
            try:
                base = self._get_server_url()
                cpu = ram = 0.0
                up = down = 0.0
                gpu_vram = "--"

                if base:
                    try:
                        resp = http_get(f"{base}/health", timeout=4, quiet=True)
                        if resp.status_code == 200:
                            ok = True
                            d = resp.json()
                            cpu = float(d.get("cpu", {}).get("percent", 0))
                            mem = d.get("memory", {})
                            ram = float(mem.get("percent", 0))
                            gpu = d.get("gpu")
                            if gpu:
                                vram_used = float(gpu.get("vram_used_mb", 0)) / 1024.0
                                vram_total = float(gpu.get("vram_total_mb", 0)) / 1024.0
                                gpu_util = int(gpu.get("gpu_util_percent", 0))
                                gpu_vram = f"{vram_used:.1f}G/{vram_total:.1f}G {gpu_util}%"  # noqa: E501
                    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError):  # noqa: E501
                        pass

                self.stats_ready.emit(cpu, ram, up, down, gpu_vram)
            except Exception:  # 线程主循环安全网，防止线程意外退出
                pass
            # 指数退避：服务不可达时 3s→6s→12s→…封顶 60s，恢复后回到 3s；
            # 未配置地址不算失败，保持基础频率以便配置改动尽快生效
            if not base or ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
            delay = 3 if consecutive_failures == 0 else min(
                3 * (2 ** (consecutive_failures - 1)), 60)
            end = time.time() + delay
            while self._running and time.time() < end:
                time.sleep(0.25)

    def stop(self):
        self._running = False
from gui.dialogs import StartupSplash  # noqa: E402


class SystemStatusOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_overlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(8)

        # 服务器入口（状态点 + 名称）：服务端连接状态实时反映在圆点上
        self.server_dot = QLabel("●")
        self.server_dot.setObjectName("ov_server_dot")
        self.server_dot.setToolTip("服务端连接状态")
        layout.addWidget(self.server_dot)
        self.server_lbl = QLabel(" 服务器状态")
        self.server_lbl.setObjectName("ov_server")
        layout.addWidget(self.server_lbl)

        # 资源指标：图标 + 名称 + 数值（数值按负载分级着色）
        def metric(icon, name):
            chip = QWidget()
            chip.setObjectName("ov_chip")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(0, 0, 0, 0)
            chip_layout.setSpacing(4)
            icon_lbl = QLabel(icon)
            icon_lbl.setObjectName("ov_icon")
            name_lbl = QLabel(name)
            name_lbl.setObjectName("ov_name")
            value_lbl = QLabel("--")
            value_lbl.setObjectName("ov_value")
            chip_layout.addWidget(icon_lbl)
            chip_layout.addWidget(name_lbl)
            chip_layout.addWidget(value_lbl)
            layout.addWidget(chip)
            return value_lbl
        # 服务端资源监控（来自 /health gpu 字段）：显存占用 / GPU 利用率
        self.cpu_lbl = metric("", "CPU")
        self.ram_lbl = metric("", "内存")
        self.vram_lbl = metric("", "显存")
        self.server_gpu_lbl = metric("", "GPU")

        def create_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFrameShadow(QFrame.Plain)
            sep.setFixedWidth(1)
            sep.setObjectName("status_separator")
            return sep

        # AI 服务状态（Ollama/视觉/语音/向量/克隆）已按需求移除，仅保留资源指标

        # 兼容别名（旧代码可能引用）
        self.gpu_lbl = self.server_lbl
        self.net_lbl = self.vram_lbl

        self.setFixedHeight(30)
        self.adjustSize()

        # 后台线程采集 CPU/RAM/网速和 GPU 显存
        self._collector = _StatsCollector(self)
        self._collector.stats_ready.connect(self._on_stats_ready)
        self._collector.start()

    @staticmethod
    def set_server_state(self, ok):
        """服务端连接状态 → 状态点颜色：正常绿、不可用红。"""
        if not hasattr(self, "server_dot"):
            return
        self.server_dot.setProperty("state", "ok" if ok else "bad")
        self.server_dot.style().unpolish(self.server_dot)
        self.server_dot.style().polish(self.server_dot)
        self.server_dot.setToolTip("服务端连接正常" if ok else "无法连接服务端，部分功能不可用")

    @staticmethod
    def _set_level(label, level):
        """通过动态属性驱动 QSS 状态色，主题自适应。"""
        label.setProperty("level", level)
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    def _load_level(value):
        if value >= 85:
            return "bad"
        if value >= 60:
            return "warn"
        return "ok"

    def update_server_status(self, status):
        """更新服务端资源监控（来自心跳 /health 的 gpu 字段），不含模型状态。"""
        health = status.get("health") if isinstance(status, dict) else None
        gpu = (health or {}).get("gpu") if isinstance(health, dict) else None
        if not isinstance(gpu, dict):
            self.server_gpu_lbl.setText("--")
            self._set_level(self.server_gpu_lbl, "idle")
            return
        vram_pct = gpu.get("vram_percent")
        util_pct = gpu.get("gpu_util_percent")
        if vram_pct is None:
            self.server_gpu_lbl.setText("--")
            self._set_level(self.server_gpu_lbl, "idle")
            return
        text = f"{vram_pct:.0f}%"
        if util_pct is not None:
            text += f" {util_pct:.0f}%"
        self.server_gpu_lbl.setText(text)
        self._set_level(self.server_gpu_lbl, self._load_level(vram_pct))
        self.adjustSize()

    def _on_stats_ready(self, cpu, ram, up, down, gpu_vram):
        self.cpu_lbl.setText(f"{cpu:.0f}%")
        self._set_level(self.cpu_lbl, self._load_level(cpu))
        self.ram_lbl.setText(f"{ram:.0f}%")
        self._set_level(self.ram_lbl, self._load_level(ram))
        self.vram_lbl.setText(gpu_vram if gpu_vram != "--" else "--")
        self._set_level(self.vram_lbl, "idle")
        self.adjustSize()


from gui.main_window_accounts import AccountsMixin  # noqa: E402
from gui.main_window_aiconfig import AIConfigMixin  # noqa: E402
from gui.main_window_aigen import AIGenMixin  # noqa: E402
from gui.main_window_installers import InstallersMixin  # noqa: E402
from gui.main_window_pages import PageSetupMixin  # noqa: E402
from gui.main_window_services import ServicesMixin  # noqa: E402
from gui.main_window_sidebar import SidebarMixin  # noqa: E402


class MainWindow(QMainWindow, PageSetupMixin, ServicesMixin, AccountsMixin, AIGenMixin, SidebarMixin, InstallersMixin, AIConfigMixin):  # noqa: E501
    def __init__(self, splash=None):
        super().__init__()
        self.splash = splash
        self._update_splash("正在初始化窗口参数...", 15)
        self.setWindowTitle(f"{__app_name__} v{get_version()}")
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

        # RunningHub 配置由服务端管理，客户端不再直连
        self.runninghub = None  # 已迁移到服务端管理
        self.rh_pending_tasks = []
        self.rh_submitted_tasks = {}
        self.rh_queue_paused = False
        self.rh_poll_timer = None
        self.rh_image_nodes = []
        self.rh_audio_nodes = []
        self.playwright_profile_path = os.path.join(PROJECT_ROOT, "playwright_profile")
        os.makedirs(self.playwright_profile_path, exist_ok=True)

        self.creator_pw_controller = None
        self.downloader_pw_controller = None
        self.system_default_login_controller: Any = None
        self.creator_guidance_url = "https://creator.douyin.com/creator-micro/creative-guidance"  # noqa: E501
        self.creator_added_urls = []
        self.creator_current_video_url = ""
        self.creator_pw_poll_timer = QTimer(self)
        self._pw_install_running = False
        self._pw_auto_install_attempted = False
        self._pw_ready = False
        self.account_pw_controllers = {}

        self._avatar_workers = []
        self.active_workers = []
        self.task_progress_bars = {}
        self.task_status_items = {}
        self.task_outputs = {}
        self._task_registry = {}
        self.download_tasks = []

        self._update_splash("正在构建主界面 UI 元素 (组件较多，可能耗时数秒)...", 65)
        self.setup_ui()
        self._setup_tray()

        # System status overlay
        self.status_overlay = SystemStatusOverlay(self)
        self.status_overlay.show()

        # 服务端连接警告横幅：不可用时红色常驻顶端（同资源监控停靠）；
        # 恢复可用时变绿色提示，3 秒后自动消失。
        # 服务端连接状态：已集成到资源监控栏的状态点（SystemStatusOverlay.set_server_state）,
        self._update_splash("正在检测 Playwright 运行状态...", 85)
        self.ensure_playwright_chromium_ready()

        self._update_splash("正在建立后台通信与系统资源监控服务...", 95)

        self.comfy_ws = None

        # 启动服务端心跳监测（只关心服务端状态，不检测具体模型）
        self.ai_status_collector = AIStatusCheckThread(self.ai_config_file)

        # 客户端任务下发闭环：周期领取（微信等 → 本机下载任务）并执行上报
        try:
            from gui.client_task_thread import ClientTaskWorker
            self.client_task_worker = ClientTaskWorker(parent=self)
            self.client_task_worker.progress.connect(
                lambda msg: log.info(f"[客户端任务] {msg}"))
            self.client_task_worker.task_picked.connect(self._on_client_task_picked)
            self.client_task_worker.start()
        except Exception as e:  # Qt 线程启动涉及外部模块导入，无法预知所有异常
            log.warning(f"[客户端任务] 领取线程启动失败: {e}")
            self.client_task_worker = None

        def handle_ai_status(status):
            if hasattr(self, "status_overlay") and self.status_overlay:
                self.status_overlay.update_server_status(status)
            # 服务端可达性 → 顶部警告横幅显示/隐藏
            self._update_server_warning(status.get("server_ok", False))

        self.ai_status_collector.status_updated.connect(handle_ai_status)
        self.ai_status_collector.start()

        self._update_splash("系统准备就绪，正在展现主界面...", 100)

    def _update_splash(self, text, value):
        if hasattr(self, 'splash') and self.splash:
            try:
                self.splash.status_lbl.setText(text)
                self.splash.progress.setValue(value)
                QApplication.processEvents()
            except Exception:  # Qt 界面操作安全网
                pass

    def _on_theme_changed(self):
        """主题切换回调：保存设置并立即应用到全部窗口（无需重启）。"""
        theme = self.theme_combo.currentData()
        from utils.theme_manager import apply_theme, save_theme
        save_theme(theme)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app)
        self.theme_hint.setText(f" 已切换到「{self.theme_combo.currentText()}」，立即生效")

    def _on_client_task_picked(self, task):
        """领取到客户端任务（下载）：系统托盘提示用户操作。"""
        try:
            params = (task or {}).get("params") or {}
            url = str(params.get("url") or "")
            cap = (task or {}).get("capability") or ""
            msg = f"收到客户端任务：{cap}\n{url}" if url else f"收到客户端任务：{cap}"
            log.info(f"[客户端任务] 领取任务: {msg}")
            if hasattr(self, "tray") and self.tray is not None:
                self.tray.showMessage("客户端任务", msg,
                                      QSystemTrayIcon.Information, 6000)
        except (KeyError, TypeError, AttributeError) as e:
            log.warning(f"[客户端任务] 任务提示失败: {e}")

    def _update_server_warning(self, server_ok):
        """服务端连通状态 → 资源监控栏状态点。

        - 不可用：状态点红色常驻；
        - 恢复可用：状态点绿色 3 秒后回到中性色（常驻栏内颜色变化，无弹窗）。
        """
        overlay = getattr(self, "status_overlay", None)
        if overlay is None:
            return
        if server_ok:
            overlay.set_server_state(True)
            if not hasattr(self, "_server_ok_timer"):
                from PySide6.QtCore import QTimer
                self._server_ok_timer = QTimer(self)
                self._server_ok_timer.setSingleShot(True)
                self._server_ok_timer.setInterval(3000)
                self._server_ok_timer.timeout.connect(lambda: overlay.set_server_state("idle"))  # noqa: E501
            self._server_ok_timer.start()
        else:
            if hasattr(self, "_server_ok_timer") and self._server_ok_timer.isActive():
                self._server_ok_timer.stop()
            overlay.set_server_state(False)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "status_overlay") and self.status_overlay:
            margin_right = 20
            margin_top = 20
            w = self.status_overlay.width()
            self.status_overlay.move(self.width() - w - margin_right, margin_top)

    def _setup_tray(self):
        """系统托盘：关闭窗口时最小化到托盘，仅托盘「退出」走确认关闭流程。"""
        self._tray_quit = False
        self._tray_hint_shown = False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = os.path.join(PROJECT_ROOT, "assets", "app_icon.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        self.tray_icon.setToolTip("螺丝钉-电商智能体矩阵")
        menu = QMenu()
        act_show = menu.addAction("显示主界面")
        act_show.triggered.connect(self._restore_from_tray)
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit_from_tray)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):  # noqa: N802
        """F11 全屏/退出全屏（修复全屏右缘出屏问题的可控入口）。"""
        if event.key() == Qt.Key.Key_F11:
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            # 先确保窗口在当前屏幕可视区内，再进入全屏，避免右缘出屏
            try:
                from PySide6.QtGui import QGuiApplication as _QGA  # noqa: N814
                frame = self.frameGeometry()
                scr = _QGA.screenAt(frame.center()) or _QGA.primaryScreen()
                if scr is not None:
                    avail = scr.availableGeometry()
                    if not avail.intersects(frame):
                        self.move(avail.center() - self.rect().center())
            except Exception:  # Qt 屏幕几何计算，依赖窗口管理器状态
                pass
            self.showFullScreen()

    def _quit_from_tray(self):
        # 标记为真正退出，closeEvent 走原有的确认对话框
        self._tray_quit = True
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.close()

    def closeEvent(self, event):  # noqa: N802
        # 点窗口 X：最小化到托盘，不退出（仅托盘右键「退出」才真正关闭）
        if not getattr(self, "_tray_quit", False):  # noqa: SIM102
            tray_icon = getattr(self, "tray_icon", None)
            if tray_icon is not None and tray_icon.isVisible():
                event.ignore()
                self.hide()
                if not self._tray_hint_shown:
                    self._tray_hint_shown = True
                    tray_icon.showMessage(
                        "螺丝钉-电商智能体矩阵",
                        "程序已最小化到系统托盘，右键托盘图标选择「退出」可关闭。",
                        QSystemTrayIcon.Information, 3000)
                return

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
        except Exception:  # 外部浏览器控制器 stop() 可能抛出多种异常
            pass
        try:
            for _, ctrl in list(getattr(self, "account_pw_controllers", {}).items()):
                with contextlib.suppress(Exception):
                    ctrl.stop()
        except (TypeError, AttributeError):
            pass
        try:
            if hasattr(self, "monitor") and self.monitor:
                self.monitor.running = False
                self.monitor.wait()
        except Exception:  # 线程 wait() 可能因内部状态抛出异常
            pass
        try:
            if hasattr(self, "ai_status_collector") and self.ai_status_collector:
                self.ai_status_collector.running = False
                self.ai_status_collector.wait()
        except Exception:  # 线程 wait() 可能因内部状态抛出异常
            pass
        try:
            if getattr(self, "client_task_worker", None) is not None:
                self.client_task_worker.stop()
                self.client_task_worker.wait(3000)
        except Exception:  # 线程 stop/wait 涉及内部状态
            pass
        try:
            if hasattr(self, "comfy_ws") and self.comfy_ws:
                self.comfy_ws.running = False
                self.comfy_ws.wait()
        except Exception:  # WebSocket 线程 stop/wait
            pass
        try:
            if hasattr(self, "extension_bridge") and self.extension_bridge:
                self.extension_bridge.stop()
        except Exception:  # 扩展桥接 stop() 外部API
            pass

        try:
            from core.creator_browser_controller import close_all_active_browsers
            close_all_active_browsers()
        except Exception:  # 浏览器关闭外部API
            pass

        try:
            tray_icon = getattr(self, "tray_icon", None)
            if tray_icon is not None:
                tray_icon.hide()
        except Exception:  # Qt托盘 hide() 安全网
            pass
        try:
            super().closeEvent(event)
        except Exception:  # Qt closeEvent 链式调用安全网
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
        # Default page: workbench (agent home)
        self.switch_page(46)


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
        self.content_stack.addWidget(self.page_digital_human)

        # 4: Library/Downloads (Disabled)
        self.page_library = QWidget()
        self.content_stack.addWidget(self.page_library)

        # 5: Douyin Login
        self.page_login = QWidget()
        self.setup_login_page()
        self.content_stack.addWidget(self.page_login)

        # 6: 关于（系统信息 / 关于与版本 / 外观）
        self.page_about = QWidget()
        self.content_stack.addWidget(self.page_about)
        self._register_lazy_page(6, self.setup_about_page)

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
        # 视频修复已并入「媒体工具」标签页（media_tools_page），不再启动时构建
        self.content_stack.addWidget(self.page_video_tools)

        # 12: Transcription Tool (Video → Text)
        self.page_transcription = QWidget()
        self.setup_transcription_page()
        self.content_stack.addWidget(self.page_transcription)

        # 13: Environment Configuration
        self.page_env_config = QWidget()
        self.content_stack.addWidget(self.page_env_config)

        # 15: Video Montage Tool (Smart Cut & Assemble)
        self.page_video_montage = QWidget()
        self.content_stack.addWidget(self.page_video_montage)
        self._register_lazy_page(14, self.setup_video_montage_page)

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
        self.content_stack.addWidget(self.page_video_ai_rename)
        self._register_lazy_page(25, self.setup_video_ai_rename_page)

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

        # 32: Material Generation (素材生成) Page
        self.page_dreamina = QWidget()
        self.content_stack.addWidget(self.page_dreamina)
        self._register_lazy_page(31, self.setup_dreamina_page)

        # 33: Cover Maker (封面制作) Page — 懒加载，首次进入时才构建
        self.page_cover_maker = QWidget()
        self.content_stack.addWidget(self.page_cover_maker)
        self._register_lazy_page(32, self.setup_cover_maker_page)

        # 34: One-click Compile Video (一键成片) Page
        self.page_compile_video = QWidget()
        self.content_stack.addWidget(self.page_compile_video)
        self._register_lazy_page(33, self.setup_compile_video_page)

        # 35: Hook Score (开头黄金3秒评分) Page
        self.page_hook_score = QWidget()
        self.setup_hook_score_page()
        self.content_stack.addWidget(self.page_hook_score)

        # 36: MG Animation (Remotion) Page
        self.page_mg_animation = QWidget()
        self.content_stack.addWidget(self.page_mg_animation)

        # 37: Data Backup / Restore Page
        self.page_backup = QWidget()
        self.setup_env_maintenance_page()
        self.content_stack.addWidget(self.page_backup)

        # 38: Storyboard (分镜脚本) Page（原热点追踪页已彻底移除，功能并入素材浏览器）
        self.page_storyboard = QWidget()
        self.setup_storyboard_page()
        self.content_stack.addWidget(self.page_storyboard)

        # 40: Vector Search (向量检索) Page
        self.page_vector_search = QWidget()
        self.setup_vector_search_page()
        self.content_stack.addWidget(self.page_vector_search)

        # 39: Terminal Page placeholder (page_terminal removed, keep index slot)
        self.page_terminal_placeholder = QWidget()
        self.content_stack.addWidget(self.page_terminal_placeholder)

        # 42: Marketing Video Detection Page
        self.page_marketing_detect = QWidget()
        self.setup_marketing_detect_page()
        self.content_stack.addWidget(self.page_marketing_detect)

        # 43: Dreamina Assets (即梦素材) Page
        self.page_dreamina_assets = QWidget()
        self.setup_dreamina_assets_page()
        self.content_stack.addWidget(self.page_dreamina_assets)

        # 43: Scheduled Tasks (定时任务) Page —— 监控服务端定时任务
        self.page_scheduled_tasks = QWidget()
        self.setup_scheduled_tasks_page()
        self.content_stack.addWidget(self.page_scheduled_tasks)

        # 44: Extension Plugins (扩展插件) Page —— 浏览器采集扩展管理
        self.page_extension = QWidget()
        self.setup_extension_page()
        self.content_stack.addWidget(self.page_extension)

        # 45: 音频素材（媒体库独立菜单，懒加载）
        self.page_audio_material = QWidget()
        self.content_stack.addWidget(self.page_audio_material)
        self._register_lazy_page(44, self.setup_audio_material_page)

        # 46: 媒体工具（图片处理 + 视频处理 聚合标签页，懒加载）
        self.page_media_tools = QWidget()
        self.content_stack.addWidget(self.page_media_tools)
        self._register_lazy_page(45, self.setup_media_tools_page)

        # Agent home (ops workbench), appended at stack tail index 46
        self._agent_home_index = 46
        self.page_agent_home = QWidget()
        self.content_stack.addWidget(self.page_agent_home)
        self._register_lazy_page(46, self.setup_agent_home_page)

        # 47: 定时任务管理（本地 schtasks + 智能体编排任务，懒加载）
        self.page_scheduled_tasks_mgmt = QWidget()
        self.content_stack.addWidget(self.page_scheduled_tasks_mgmt)
        self._register_lazy_page(47, self.setup_scheduled_tasks_mgmt_page)

        # 浏览器扩展桥接服务：按配置随客户端自动启动
        try:
            from utils.extension_bridge import get_bridge
            self.extension_bridge = get_bridge()
            if self.extension_bridge.config.get("auto_start", True):
                self.extension_bridge.start()
        except Exception as e:  # 扩展桥接 start() 涉及外部进程
            log.error(f"[扩展桥接] 自动启动失败: {e}")

        # 进入定时任务页时刷新（拉取最新服务端状态）
        def _on_page_change(idx):
            if idx == 42 and hasattr(self, "scheduled_tasks_tool"):
                self.scheduled_tasks_tool.refresh()
            if idx == 47 and hasattr(self, "scheduled_tasks_mgmt_tool"):
                self.scheduled_tasks_mgmt_tool.refresh()
        self.content_stack.currentChanged.connect(_on_page_change)


    def trigger_page_logic(self, index):
        """Triggers data refresh or UI reset for specific pages"""
        if hasattr(self, "refresh_timer") and self.refresh_timer.isActive():
            self.refresh_timer.stop()

        # 热点页面：只在活跃时轮询，离开后立即停止（减少主线程常驻 2次/秒 事件回调）
        if index == 1:
            if hasattr(self, "creator_pw_poll_timer") and not self.creator_pw_poll_timer.isActive():  # noqa: E501
                self.creator_pw_poll_timer.start()
        else:
            if hasattr(self, "creator_pw_poll_timer") and self.creator_pw_poll_timer.isActive():  # noqa: E501
                self.creator_pw_poll_timer.stop()

        if index == 8: # Accounts
            self.refresh_accounts_list()
        elif index == 12: # Transcription
            pass
        elif index == 36:  # 环境与维护（含系统日志 Tab）
            if hasattr(self, "env_config_tool"):
                self.env_config_tool.refresh_status()
            self.refresh_logs()
        elif index == 7: # System Config
            if hasattr(self, "refresh_llm_page_status"):
                self.refresh_llm_page_status()
        elif index == 20: # Voice Clone
            if hasattr(self, "voice_clone_tool"):
                self.voice_clone_tool._populate_ref_audio_samples()
        elif index == 34: # Hook Score
            if hasattr(self, "hook_score_tool"):
                self.hook_score_tool.update_vision_model_display()
        elif index == 40: # Marketing Video Detection
            if hasattr(self, "marketing_detect_tool"):
                self.marketing_detect_tool.update_vision_model_display()
        elif index == 43: # 扩展插件
            if hasattr(self, "extension_tool"):
                self.extension_tool.refresh()
        elif index == 44:  # 音频素材
            if hasattr(self, "audio_material_tool"):
                self.audio_material_tool.refresh()
        elif index == 38:  # 素材检索（进入页面时若上次加载失败自动重试；Tab2 即梦素材一并刷新）
            if hasattr(self, "vector_search_tool"):
                try:
                    self.vector_search_tool.refresh()
                except Exception as e:  # 外部工具 refresh() 实现未知
                    log.error(f"刷新素材检索失败: {e}")
            if hasattr(self, "dreamina_assets_tool"):
                try:
                    self.dreamina_assets_tool._scan_local_files()
                except Exception as e:  # 外部工具扫描文件实现未知
                    log.error(f"刷新即梦素材列表失败: {e}")
        elif index == 37: # Storyboard
            if hasattr(self, "storyboard_tool"):
                self.storyboard_tool.reload_sources()
        elif index == 21: # 本地配置
            if hasattr(self, "voice_samples_tool"):
                self.voice_samples_tool._load_table_data()
            if hasattr(self, "_load_lut_config"):
                self._load_lut_config()








    def setup_subtitle_removal_page_v14(self):
        from gui.subtitle_removal_page_v14 import SubtitleRemovalPageV14
        self.subtitle_removal_tool_v14 = SubtitleRemovalPageV14(self.page_subtitle_removal_v14, self)  # noqa: E501
        self.subtitle_removal_tool_v14.setup()























    def refresh_creator_guidance(self):
        if not self.creator_pw_controller or not self.creator_pw_controller.is_running():  # noqa: E501
            self.open_creator_guidance_browser()
            return
        self.creator_pw_controller.goto(self.creator_guidance_url)

    def apply_creator_guidance_category(self, category):
        if not self.creator_pw_controller or not self.creator_pw_controller.is_running():  # noqa: E501
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

        if self.creator_pw_controller and self.is_pw_controller_usable(self.creator_pw_controller):  # noqa: E501
            self.creator_pw_controller.goto(self.creator_guidance_url)
            return
        if self.creator_pw_controller and not self.is_pw_controller_usable(self.creator_pw_controller):  # noqa: E501
            with contextlib.suppress(Exception):
                self.creator_pw_controller.stop()
            self.creator_pw_controller = None

        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", profile_id)  # noqa: E501
        os.makedirs(user_data_dir, exist_ok=True)

        self.creator_pw_controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=PW_BROWSERS_DIR,
            headless=False,
        )
        self.creator_pw_controller.start()
        QTimer.singleShot(300, lambda: self.creator_pw_controller.goto(self.creator_guidance_url) if self.creator_pw_controller else None)  # noqa: E501

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
            btn_rm.clicked.connect(lambda checked=False, u=url: self.remove_creator_queue_url(u))  # noqa: E501
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





    def open_system_default_browser(self):
        if not self.is_playwright_chromium_present():
            QMessageBox.information(self, "提示", "正在准备 Playwright Chromium 内核，请先完成内核安装。")
            self.ensure_playwright_chromium_ready()
            return

        if self.system_default_login_controller and self.system_default_login_controller.is_running():  # noqa: E501
            self.system_default_login_controller.goto("https://www.douyin.com")
            return

        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", "system_default_profile")  # noqa: E501
        os.makedirs(user_data_dir, exist_ok=True)

        from core.creator_browser_controller import CreatorBrowserController
        self.system_default_login_controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=PW_BROWSERS_DIR,
            headless=False
        )
        self.system_default_login_controller.start()
        QTimer.singleShot(500, lambda: self.system_default_login_controller.goto("https://www.douyin.com"))  # noqa: E501
        QMessageBox.information(self, "提示", "已为您在外部启动独立登录窗口。\n请在弹出的 Chromium 窗口内登录抖音，完成后点击「提取并同步 Cookie」。")  # noqa: E501

    def sync_system_default_cookie(self):
        if not self.system_default_login_controller or not self.system_default_login_controller.is_running():  # noqa: E501
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
        except Exception as e:  # 文件I/O + 外部控制器 stop()，无法单一类型覆盖
            QMessageBox.critical(self, "错误", f"保存 Cookie 失败: {e}")

    def add_task_to_list(self, prompt_id, status="正在运行", task_type="ComfyUI", source="服务端", extra=None):  # noqa: E501
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        item_id = QTableWidgetItem(prompt_id[:12])
        self.task_table.setItem(row, 0, item_id)
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

        # 任务元数据
        task_data = {
            "id": prompt_id,
            "task_id": prompt_id,
            "type": task_type,
            "source": source,
            "status": status,
            "progress": 0,
            "params": extra or {},
            "result": None,
            "results": None,
            "error": None,
        }
        if extra:
            task_data.update(extra)
        item_id.setData(0x0100, task_data)

        # 操作列
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(5, 2, 5, 2)
        actions_layout.setSpacing(5)

        registry = {"row": row, "task_id": prompt_id, "task_type": task_type, "extra": extra}  # noqa: E501

        btn_preview = mdi_button("", "eye")
        btn_preview.setToolTip("预览")
        btn_preview.setFixedSize(30, 24)
        btn_preview.setEnabled(False)
        btn_preview.clicked.connect(lambda: self.preview_result(prompt_id))
        registry["preview_btn"] = btn_preview

        btn_download = mdi_button("", "save")
        btn_download.setToolTip("下载")
        btn_download.setFixedSize(30, 24)
        btn_download.setEnabled(False)
        if task_type == "RunningHub":
            btn_download.clicked.connect(lambda: self.download_rh_result(prompt_id))
        else:
            btn_download.clicked.connect(lambda: self.download_result(prompt_id))
        registry["download_btn"] = btn_download

        actions_layout.addWidget(btn_preview)
        actions_layout.addWidget(btn_download)

        if task_type == "RunningHub":
            btn_pause = mdi_button("", "pause")
            btn_pause.setToolTip("暂停")
            btn_pause.setFixedSize(30, 24)
            btn_pause.clicked.connect(lambda: self.pause_rh_task(prompt_id))
            registry["pause_btn"] = btn_pause

            btn_resume = mdi_button("", "play")
            btn_resume.setToolTip("恢复")
            btn_resume.setFixedSize(30, 24)
            btn_resume.setEnabled(False)
            btn_resume.clicked.connect(lambda: self.resume_rh_task(prompt_id))
            registry["resume_btn"] = btn_resume

            actions_layout.addWidget(btn_pause)
            actions_layout.addWidget(btn_resume)

        btn_delete = mdi_button("", "delete")
        btn_delete.setToolTip("删除")
        btn_delete.setFixedSize(30, 24)
        btn_delete.clicked.connect(lambda: self.delete_task_row(prompt_id))
        registry["delete_btn"] = btn_delete
        actions_layout.addWidget(btn_delete)

        self.task_table.setCellWidget(row, 6, actions_widget)
        self._task_registry[prompt_id] = registry

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
        webbrowser.open(url) # Simplest for now, as QWebEngine might be overkill for quick preview  # noqa: E501

    def download_result(self, prompt_id):
        outputs = self.task_outputs.get(prompt_id, [])
        if not outputs:
            return

        from utils import comfyui_client as comfy
        comfyui_addr = comfy.resolve_addr(self.ai_config, auto_start=False)
        save_dir = pick_directory(self, "选择保存目录")
        if not save_dir:
            return

        for out in outputs:
            url = comfy.view_url(comfyui_addr, out['filename'], out['type'])
            local_path = os.path.join(save_dir, out['filename'])

            def do_download(u=url, p=local_path):
                try:
                    from utils.http_client import http_get
                    r = http_get(u, stream=True)
                    with open(p, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return True, p
                except (requests.exceptions.RequestException, OSError) as e:
                    return False, str(e)

            def on_finished(res):
                success, info = res
                if success:
                    log.info(f"Downloaded: {info}")
                else:
                    QMessageBox.warning(self, "下载失败", f"文件下载失败: {info}")

            worker = Worker(do_download)
            worker.finished.connect(on_finished)
            # 必须持有 Worker：QThread 运行中被 Python GC 回收会触发 Qt fatal 崩溃（0xc0000409）
            self.active_workers.append(worker)
            worker.finished.connect(
                lambda _w=worker: self.active_workers.remove(_w) if _w in self.active_workers else None)  # noqa: E501
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
                from utils.http_client import http_get
                response = http_get(url, timeout=5)
                if response.status_code == 200:
                    return response.content
            except requests.exceptions.RequestException as e:
                log.error(f"Failed to fetch image {url}: {e}")
            return None

        def on_fetched(data):
            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                if not pixmap.isNull():
                    label.setPixmap(pixmap.scaled(size[0], size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation))  # noqa: E501
                    label.setStyleSheet(f"border-radius: {size[0]//2}px; border: 2px solid #fff;")  # noqa: E501

        worker = Worker(fetch_image)
        worker.finished.connect(on_fetched)
        self.active_workers.append(worker) # Keep reference
        worker.start()






    def is_pw_controller_usable(self, controller):
        if not controller or not controller.is_running():
            return False
        try:
            status, _, err = controller.get_status()
        except Exception:  # 浏览器控制器 get_status() 外部API
            return False
        if not status:
            return False
        bad_status = ("已停止" in status) or ("启动失败" in status) or ("已关闭" in status)
        bad_err = bool(err) and (("Target closed" in err) or ("has been closed" in err) or ("Browser has been closed" in err))  # noqa: E501
        return not (bad_status or bad_err)






    # ── 并发控制：最多同时运行 3 个 AI 任务 ──
    MAX_CONCURRENT_WORKERS = 3

    def start_worker(self, func, on_finished=None, on_error=None):
        """Helper to start a worker thread and keep it alive until finished.
        同时最多 3 个并发，超出的自动排队等待。"""
        active_count = len([w for w in self.active_workers if w.isRunning()])
        if active_count >= self.MAX_CONCURRENT_WORKERS:
            QTimer.singleShot(500, lambda: self.start_worker(func, on_finished, on_error))  # noqa: E501
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
        level_text = level_filter.currentText() if level_filter else "全部"

        # 历史日志下拉框：选中文件路径存于 itemData，空时读当前会话 app.log
        log_combo = getattr(self, "log_file_combo", None)
        log_path = ""
        if log_combo is not None and log_combo.currentIndex() >= 0:
            log_path = log_combo.itemData(log_combo.currentIndex()) or ""

        raw = get_last_logs(2000, path=log_path or None)
        lines = raw.splitlines()

        if level_text != "全部":
            lines = [line for line in lines if f"| {level_text: <8} |" in line or f"| {level_text}" in line]  # noqa: E501

        keyword = keyword_filter.text().strip() if keyword_filter else ""

        if keyword:
            lines = [line for line in lines if keyword.lower() in line.lower()]

        lines = lines[-500:]

        self.log_viewer.setPlainText("\n".join(lines))
        # 底部标签同步当前查看的日志文件
        try:
            cur_name = log_combo.currentText() if log_combo is not None else "app.log"
            if hasattr(self, "log_path_label"):
                self.log_path_label.setText(f"完整日志: .runtime/logs/{cur_name}")
        except Exception:  # Qt 标签操作安全网
            pass
        # 首次调用时挂上高亮器（只挂一次）
        if not hasattr(self, "_log_highlighter"):
            self._log_highlighter = LogHighlighter(self.log_viewer.document())
        self.log_viewer.verticalScrollBar().setValue(
            self.log_viewer.verticalScrollBar().maximum()
        )

    def _log_viewer_context_menu(self, pos):
        """系统日志右键菜单：清空 / 复制 / 全选"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_clear = menu.addAction(" 清空日志")
        act_copy = menu.addAction(" 复制选中")
        act_select_all = menu.addAction("完成： 全选")
        chosen = menu.exec(self.log_viewer.mapToGlobal(pos))
        if chosen == act_clear:
            self.log_viewer.clear()
        elif chosen == act_copy:
            self.log_viewer.copy()
        elif chosen == act_select_all:
            self.log_viewer.selectAll()







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
        get_machine_id,
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
        # 调试用：设置环境变量 TINTIN_SKIP_SINGLE_INSTANCE=1 可跳过单例检查
        if os.environ.get("TINTIN_SKIP_SINGLE_INSTANCE") == "1":
            pass
        else:
            _is_already_running = False
            # Windows: 命名互斥量，进程退出/崩溃时OS自动释放，无残留无延迟
            import ctypes as _ctypes
            _mutex = _ctypes.windll.kernel32.CreateMutexW(None, False, "luosiding.ecommerce.agent.matrix.single_instance")  # noqa: E501
            if _ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                _is_already_running = True
            if _is_already_running:
                from PySide6.QtWidgets import QMessageBox as _QMB  # noqa: N814
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
        except Exception:  # Qt QFont 创建可能失败
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
            screen_w = screen.width()
            screen_h = screen.height()
            win_w = 1300
            win_h = 900
            if screen_w < win_w:
                win_w = int(screen_w * 0.95)
            if screen_h < win_h:
                win_h = int(screen_h * 0.95)
            x = screen.x() + (screen_w - win_w) // 2
            y = screen.y() + (screen_h - win_h) // 2
            window.resize(win_w, win_h)
            window.move(x, y)
            log.info(f"Centered window on screen {active_screen.name()} at ({x}, {y}) size {win_w}x{win_h}")  # noqa: E501
        except Exception as e:  # Qt 屏幕/几何计算依赖窗口管理器
            log.error(f"Failed to center window: {e}")

        splash.close()
        window.show()

        # 修复：窗口可能被 Windows 恢复到屏幕外（上次位置失效 / 多显示器断开 / DPI 变化），
        # 导致最大化/全屏时右缘跑出屏幕、需二次全屏才复原。显示后延迟校正一次，
        # 把窗口完整拉回当前屏幕可视区（等待窗口管理器完成布局，避免与 WM 恢复位置竞争）。
        try:
            from PySide6.QtCore import QTimer as _QTimer
            from PySide6.QtGui import QGuiApplication as _QGA  # noqa: N814

            def _ensure_window_visible():
                try:
                    if window.isFullScreen() or window.isMaximized():
                        return
                    frame = window.frameGeometry()
                    scr = _QGA.screenAt(frame.center()) or _QGA.primaryScreen()
                    if scr is None:
                        return
                    avail = scr.availableGeometry()
                    win_w = min(frame.width(), avail.width())
                    win_h = min(frame.height(), avail.height())
                    x = max(avail.left(), min(frame.left(), avail.right() - win_w + 1))
                    y = max(avail.top(), min(frame.top(), avail.bottom() - win_h + 1))
                    if (x, y, win_w, win_h) != (frame.left(), frame.top(), frame.width(), frame.height()):  # noqa: E501
                        window.setGeometry(x, y, win_w, win_h)
                        log.info(f"Corrected window bounds -> ({x}, {y}) {win_w}x{win_h}")  # noqa: E501
                except Exception as e:  # Qt 窗口几何校正安全网
                    log.error(f"校正窗口位置失败: {e}")

            _QTimer.singleShot(80, _ensure_window_visible)
        except Exception as e:  # Qt 定时器初始化安全网
            log.error(f"窗口校正初始化失败: {e}")

        log.info("MainWindow shown successfully.")

        # 启动时后台清理中间产物（不阻塞 UI；NAS 上大量文件时清理耗时）
        try:
            from threading import Thread

            from utils.asset_cleanup import cleanup_on_startup
            Thread(target=cleanup_on_startup, daemon=True, name="startup-cleanup").start()  # noqa: E501
        except Exception as e:  # 后台线程启动安全网
            log.warning(f"启动清理任务未能启动: {e}")

        sys.exit(app.exec())
    except Exception as e:  # 应用启动顶层安全网
        import traceback
        traceback.print_exc()
        log.critical(f"FATAL ERROR during startup: {e}")
        print(f"FATAL ERROR: {e}")
        sys.exit(1)

    def download_rh_result(self, task_id):
        """下载单个 RunningHub 任务结果。"""
        from utils import config_manager as cm
        default_dir = cm.get_setting("local_config", "cache_dir", "") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "materials")  # noqa: E501
        os.makedirs(default_dir, exist_ok=True)
        save_dir = pick_directory(self, "选择保存目录", default_dir)
        if not save_dir:
            return

        # 从任务表详情中提取 results
        results = []
        for row in range(self.task_table.rowCount()):
            item = self.task_table.item(row, 0)
            if not item:
                continue
            t = item.data(0x0100) or {}
            if t.get("task_id") == task_id or item.text() == task_id[:12]:
                results = t.get("results") or []
                break

        if not results:
            QMessageBox.information(self, "提示", "未找到可下载的结果。")
            return

        from datetime import datetime

        import requests
        downloaded = 0
        for res in results:
            if not isinstance(res, dict):
                continue
            url = res.get("url")
            if not url:
                continue
            ext = res.get("outputType", "bin")
            name = f"{task_id}_{datetime.now().strftime('%H%M%S')}.{ext}"
            path = os.path.join(save_dir, name)
            try:
                r = requests.get(url, timeout=120)
                if r.status_code == 200:
                    with open(path, "wb") as f:
                        f.write(r.content)
                    downloaded += 1
                else:
                    QMessageBox.warning(self, "下载失败", f"HTTP {r.status_code}: {url}")
            except (requests.exceptions.RequestException, OSError) as e:
                QMessageBox.warning(self, "下载失败", f"{url}\n{e}")
        if downloaded:
            QMessageBox.information(self, "下载完成", f"成功下载 {downloaded} 个文件到\n{save_dir}")

    def cancel_rh_task_row(self, task_id):
        """从任务表中取消/移除一个 RunningHub 任务行（委托给 AIGenMixin 的 cancel_rh_task）。"""
        self.cancel_rh_task(task_id)

    def delete_task_row(self, task_id):
        """删除任意任务行（RunningHub 同时清队列，其它类型只移除列表）。"""
        registry = self._task_registry.get(task_id) or {}
        if registry.get("task_type") == "RunningHub":
            self.cancel_rh_task(task_id)
            return
        for row in range(self.task_table.rowCount() - 1, -1, -1):
            item = self.task_table.item(row, 0)
            if not item:
                continue
            t = item.data(0x0100) or {}
            if t.get("task_id") == task_id or item.text() == task_id[:12]:
                self.task_table.removeRow(row)
                break
        self._task_registry.pop(task_id, None)
        self.task_outputs.pop(task_id, None)
        self.task_status_items.pop(task_id, None)
        self.task_progress_bars.pop(task_id, None)
