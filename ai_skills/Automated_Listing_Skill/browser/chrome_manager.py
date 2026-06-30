# -*- coding: utf-8 -*-
"""
chrome_manager.py
Chrome 浏览器启动与 CDP 连接管理
"""

import os
import subprocess
import time
import urllib.request
from pathlib import Path

import sys
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import get_chrome_exe


def is_cdp_ready(port: int) -> bool:
    """检查 Chrome CDP 调试端口是否就绪"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except Exception:
        return False


def ensure_debug_chrome(port: int, user_data_dir: str) -> None:
    """
    确保 Chrome 以调试模式运行。
    若端口已就绪则直接返回；否则自动启动 Chrome 并等待端口就绪。
    """
    if is_cdp_ready(port):
        return

    chrome_exe = get_chrome_exe()
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-infobars",
        "--disable-features=TranslateUI,BlinkGenPropertyTrees",
        "--disable-features=OptimizationGuideModelDownloading,OptimizationHints,OptimizationHintsFetching",
        "--disable-default-apps",
        "--hide-crash-restore-bubble",
        "--disable-blink-features=AutomationControlled",
        "about:blank",
    ]
    
    # 在 Windows 下防止弹出黑框
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW

    subprocess.Popen(
        args, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL, 
        close_fds=True,
        creationflags=creationflags
    )

    for _ in range(40):
        if is_cdp_ready(port):
            return
        time.sleep(0.25)
    raise RuntimeError("Chrome 已启动，但调试端口未就绪")


# 向后兼容的别名（供 batch_publish.py 旧调用方使用）
_is_cdp_ready = is_cdp_ready
_ensure_debug_chrome = ensure_debug_chrome
