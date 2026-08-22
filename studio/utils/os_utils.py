"""操作系统工具函数：文件管理器、进程管理。

GUI 层不直接调用 subprocess 执行 explorer/taskkill 等命令，
统一走本模块的封装函数。
"""
import os
import subprocess
import sys

from utils.logger_utils import log


def open_in_explorer(path: str, select: bool = True) -> None:
    """在文件管理器中打开路径。

    Args:
        path: 文件或文件夹路径
        select: True=选中文件（路径为文件时），False=只打开所在文件夹
    """
    path = os.path.normpath(path)
    try:
        if sys.platform == "win32":
            if select and os.path.isfile(path):
                subprocess.Popen(f'explorer /select,"{path}"')
            else:
                subprocess.Popen(f'explorer "{path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path if os.path.isfile(path) else os.path.dirname(path)])  # noqa: E501
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])  # noqa: E501
    except Exception as e:
        log.warning(f"[os_utils] open_in_explorer 失败: {e}")


def kill_process_tree(pid: int) -> bool:
    """终止进程树（Windows: taskkill /F /T /PID, Unix: kill）。"""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=0x08000000)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception as e:
        log.warning(f"[os_utils] kill_process_tree 失败 pid={pid}: {e}")
        return False


def _startupinfo():
    """Windows 下隐藏控制台窗口的 startupinfo。"""
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None
