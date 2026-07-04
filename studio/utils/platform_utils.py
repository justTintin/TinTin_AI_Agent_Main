import os
import sys
import shutil
import subprocess

IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform == "linux"
IS_MAC = sys.platform == "darwin"

_CREATE_NO_WINDOW = 0x08000000


# ═══════════════════════════════════════════════════════════════
#  二进制名称
# ═══════════════════════════════════════════════════════════════

def binary_name(name: str) -> str:
    """返回平台正确的可执行文件名。"""
    return f"{name}.exe" if IS_WIN else name


def python_binary() -> str:
    """venv 中的 python 路径。"""
    return "Scripts/python.exe" if IS_WIN else "bin/python"


# ═══════════════════════════════════════════════════════════════
#  文件/文件夹打开
# ═══════════════════════════════════════════════════════════════

def open_path(path: str):
    """用系统默认程序打开文件或文件夹（跨平台）。"""
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


def reveal_in_folder(path: str):
    """在文件管理器中定位文件。"""
    if IS_WIN:
        subprocess.run(["explorer", "/select,", os.path.abspath(path)])
    elif IS_MAC:
        subprocess.run(["open", "-R", path])
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)])


# ═══════════════════════════════════════════════════════════════
#  进程管理
# ═══════════════════════════════════════════════════════════════

def kill_process(name_pattern: str, *, tree: bool = False):
    """跨平台终止进程（按名称模式）。"""
    if IS_WIN:
        args = ["taskkill", "/F"]
        if tree:
            args.append("/T")
        if name_pattern.endswith(".exe"):
            args += ["/IM", name_pattern]
        else:
            args += ["/FI", f"IMAGENAME eq {name_pattern}"]
        subprocess.run(args, capture_output=True)
    else:
        flag = "-f" if tree else ""
        subprocess.run(["pkill", flag, name_pattern],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_process_by_pid(pid: int, *, tree: bool = False):
    """跨平台按 PID 终止进程。"""
    if IS_WIN:
        args = ["taskkill", "/F"]
        if tree:
            args.append("/T")
        args += ["/PID", str(pid)]
        subprocess.run(args, capture_output=True)
    else:
        import signal
        try:
            if tree:
                subprocess.run(["kill", "-TERM", "--", f"-{pid}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


# ═══════════════════════════════════════════════════════════════
#  subprocess 统一入口（所有子进程调用必须走这里）
# ═══════════════════════════════════════════════════════════════

def run_subprocess(cmd, **kwargs):
    """subprocess.run 统一封装 —— 自动处理 Windows 控制台隐藏。"""
    if IS_WIN:
        kwargs.setdefault("creationflags", 0)
        kwargs["creationflags"] |= _CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen_subprocess(cmd, **kwargs):
    """subprocess.Popen 统一封装 —— 自动处理 Windows 控制台隐藏。"""
    if IS_WIN:
        kwargs.setdefault("creationflags", 0)
        kwargs["creationflags"] |= _CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


# ═══════════════════════════════════════════════════════════════
#  兼容旧调用（逐步迁移）
# ═══════════════════════════════════════════════════════════════

def create_no_window_flag() -> int:
    """返回 Windows CREATE_NO_WINDOW 标志，非 Windows 返回 0。"""
    return _CREATE_NO_WINDOW if IS_WIN else 0


def get_bin(name: str) -> str:
    from config.paths import get_bin as _get_bin
    return _get_bin(name)


def _ffmpeg_platform_dir() -> str:
    """Return the platform-specific subdirectory name used under apps/*/ffmpeg/."""
    if IS_WIN:
        return "win_x64"
    else:
        return "linux_x64"


def _ffmpeg_fallback_candidates(exe: str) -> list:
    """Return a list of fallback paths to search for ffmpeg/ffprobe executables."""
    try:
        from config.paths import WORKSPACE_ROOT
    except Exception:
        return []
    plat = _ffmpeg_platform_dir()
    return [
        os.path.join(WORKSPACE_ROOT, exe),
        os.path.join(WORKSPACE_ROOT, "apps", "asset-browser", "bin", exe),
        os.path.join(WORKSPACE_ROOT, "apps", "vsr-v1.4.0", "backend", "ffmpeg", plat, exe),
        os.path.join(WORKSPACE_ROOT, "apps", "vsr-v1.1.1-windows-nvidia-cuda", "resources", "backend", "ffmpeg", plat, exe),
    ]


def find_ffmpeg() -> str:
    exe = binary_name("ffmpeg")
    local = get_bin("ffmpeg")
    if os.path.isfile(local):
        return local
    found = shutil.which(exe)
    if found:
        return os.path.abspath(found)

    # Fallbacks for finding ffmpeg in project root or sub-applications
    for c in _ffmpeg_fallback_candidates(exe):
        if os.path.isfile(c):
            return os.path.abspath(c)

    return exe


def find_ffprobe() -> str:
    exe = binary_name("ffprobe")
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = ffmpeg.replace("ffmpeg", "ffprobe")
        if os.path.isfile(sibling):
            return sibling
    found = shutil.which(exe)
    if found:
        return os.path.abspath(found)

    # Fallbacks for finding ffprobe in project root or sub-applications
    for c in _ffmpeg_fallback_candidates(exe):
        if os.path.isfile(c):
            return os.path.abspath(c)

    return exe


def find_python() -> str:
    from config.paths import PYTHON_EMBEDED_DIR, WORKSPACE_ROOT
    if IS_WIN:
        for p in (
            os.path.join(PYTHON_EMBEDED_DIR, "python.exe"),
            os.path.join(PYTHON_EMBEDED_DIR, "bin", "python.exe"),
        ):
            if os.path.isfile(p):
                return os.path.abspath(p)
    else:
        venv_python = os.path.join(WORKSPACE_ROOT, ".venv", "bin", "python")
        if os.path.isfile(venv_python):
            return venv_python
    return sys.executable


def find_venv_python(base_dir: str) -> str:
    if IS_WIN:
        candidates = [
            os.path.join(base_dir, "venv", "python.exe"),
            os.path.join(base_dir, "venv", "Scripts", "python.exe"),
        ]
    else:
        candidates = [
            os.path.join(base_dir, "venv", "bin", "python"),
        ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return sys.executable


# 兼容旧名
subprocess_run = run_subprocess
subprocess_popen = popen_subprocess
