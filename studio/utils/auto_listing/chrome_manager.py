# -*- coding: utf-8 -*-
"""Chrome 调试模式启动与 CDP 端口检测。"""
import os
import subprocess
import time
import urllib.request


def is_cdp_ready(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except Exception:
        return False


def ensure_debug_chrome(chrome_exe: str, port: int, user_data_dir: str) -> None:
    if is_cdp_ready(port):
        return
    if not chrome_exe or not os.path.isfile(chrome_exe):
        raise FileNotFoundError(
            f"未找到 Chrome/Edge 可执行文件：{chrome_exe or '(空)'}。请安装 Chrome 或手动指定路径。")

    os.makedirs(user_data_dir, exist_ok=True)
    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-infobars",
        "--disable-default-apps",
        "--hide-crash-restore-bubble",
        "--disable-blink-features=AutomationControlled",
        "about:blank",
    ]
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(args, **kwargs)

    for _ in range(48):
        if is_cdp_ready(port):
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Chrome 调试端口未就绪（127.0.0.1:{port}）。"
        "如果 Chrome 已打开，请先关闭使用同一用户目录的 Chrome 后再重试。")

