"""通用子进程封装：启动交互式外部应用（浏览器、外部窗口等）。

与 ffmpeg_utils 的分工：
- ffmpeg_utils：媒体处理 / 无黑框后台任务（强制 CREATE_NO_WINDOW、stdin=DEVNULL）
- process_utils：启动外部交互式应用（保留调用方对 creationflags 的完全控制，
  不强制无窗口、不设 stdin 默认值）

GUI 层不直接调用 subprocess，统一走本模块或 ffmpeg_utils。
"""
import os
import subprocess

# ── 供 GUI 层使用的 re-exports（避免 GUI 直接 import subprocess） ──
CREATE_NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
DETACHED_PROCESS = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
CREATE_NEW_PROCESS_GROUP = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def popen(cmd: list, **kwargs) -> subprocess.Popen:
    """启动外部子进程（交互式应用）。

    与 ffmpeg_utils.popen 的区别：本函数不强制无窗口、不设 stdin/creationflags 默认值，
    保留调用方对 creationflags 的完全控制（如 DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP）。
    """
    return subprocess.Popen(cmd, **kwargs)
