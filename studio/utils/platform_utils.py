import os
import sys
import shutil
import subprocess

IS_WIN = True  # 工程仅支持 Windows

_CREATE_NO_WINDOW = 0x08000000


# ═══════════════════════════════════════════════════════════════
#  二进制名称
# ═══════════════════════════════════════════════════════════════

def binary_name(name: str) -> str:
    """返回平台正确的可执行文件名（Windows 固定加 .exe）。"""
    return f"{name}.exe"


def python_binary() -> str:
    """venv 中的 python 路径。"""
    return "Scripts/python.exe"


# ═══════════════════════════════════════════════════════════════
#  文件/文件夹打开
# ═══════════════════════════════════════════════════════════════

def open_path(path: str):
    """用系统默认程序打开文件或文件夹。"""
    os.startfile(path)


def reveal_in_folder(path: str):
    """在文件管理器中定位文件。"""
    subprocess.run(["explorer", "/select,", os.path.abspath(path)])


# ═══════════════════════════════════════════════════════════════
#  进程管理
# ═══════════════════════════════════════════════════════════════

def kill_process(name_pattern: str, *, tree: bool = False):
    """按名称模式终止进程。"""
    args = ["taskkill", "/F"]
    if tree:
        args.append("/T")
    if name_pattern.endswith(".exe"):
        args += ["/IM", name_pattern]
    else:
        args += ["/FI", f"IMAGENAME eq {name_pattern}"]
    subprocess.run(args, capture_output=True)


def kill_process_by_pid(pid: int, *, tree: bool = False):
    """按 PID 终止进程。"""
    args = ["taskkill", "/F"]
    if tree:
        args.append("/T")
    args += ["/PID", str(pid)]
    subprocess.run(args, capture_output=True)


# ═══════════════════════════════════════════════════════════════
#  subprocess 统一入口（所有子进程调用必须走这里）
# ═══════════════════════════════════════════════════════════════

def run_subprocess(cmd, **kwargs):
    """subprocess.run 统一封装 —— 自动隐藏 Windows 控制台窗口。"""
    kwargs.setdefault("creationflags", 0)
    kwargs["creationflags"] |= _CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen_subprocess(cmd, **kwargs):
    """subprocess.Popen 统一封装 —— 自动隐藏 Windows 控制台窗口。"""
    kwargs.setdefault("creationflags", 0)
    kwargs["creationflags"] |= _CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


# ═══════════════════════════════════════════════════════════════
#  兼容旧调用（逐步迁移）
# ═══════════════════════════════════════════════════════════════

def create_no_window_flag() -> int:
    """返回 Windows CREATE_NO_WINDOW 标志。"""
    return _CREATE_NO_WINDOW


def get_bin(name: str) -> str:
    from config.paths import get_bin as _get_bin
    return _get_bin(name)


def _ffmpeg_fallback_candidates(exe: str) -> list:
    """Return a list of fallback paths to search for ffmpeg/ffprobe executables.

    ffmpeg 是通用工具，标准位置是 studio/bin/<platform>/（由 find_ffmpeg 第一顺位命中）。
    这里只在项目 bin 与系统 PATH 都未命中时，兜底查工程根目录，不再依赖各子应用内部目录。
    """
    try:
        from config.paths import WORKSPACE_ROOT
    except Exception:
        return []
    return [
        os.path.join(WORKSPACE_ROOT, exe),
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
        sibling = os.path.join(os.path.dirname(ffmpeg), binary_name("ffprobe"))
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
    from config.paths import PYTHON_EMBEDED_DIR
    for p in (
        os.path.join(PYTHON_EMBEDED_DIR, "python.exe"),
        os.path.join(PYTHON_EMBEDED_DIR, "bin", "python.exe"),
    ):
        if os.path.isfile(p):
            return os.path.abspath(p)
    return sys.executable


def find_venv_python(base_dir: str) -> str:
    candidates = [
        os.path.join(base_dir, "venv", "python.exe"),
        os.path.join(base_dir, "venv", "Scripts", "python.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return sys.executable

# 兼容旧名
subprocess_run = run_subprocess
subprocess_popen = popen_subprocess
