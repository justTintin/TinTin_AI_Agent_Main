# -*- coding: utf-8 -*-
"""自动上架配置：持久化、店铺映射、Chrome 检测。"""
import json
import os
import shutil

from config.paths import (
    AUTO_LISTING_CHROME_USER_DATA,
    AUTO_LISTING_CONFIG_FILE,
    AUTO_LISTING_DIR,
    AUTO_LISTING_RESULTS_DIR,
    AUTO_LISTING_SYNC_DIR,
)

DEFAULT_DEBUG_PORT = 9222

DOUYIN_STORES = {
    "juyou": {
        "name": "桔柚数码外设严选",
        "aliases": ["桔柚", "juyou"],
        "homepage_url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
    },
    "555_battery": {
        "name": "555井韵电池店铺",
        "aliases": ["555", "井韵"],
        "homepage_url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
    },
}


def detect_chrome_exe() -> str:
    """返回已安装的 Chrome/Edge 可执行文件；找不到返回空串。"""
    env = (os.environ.get("ALS_CHROME_EXE_PATH") or os.environ.get("CHROME_EXE_PATH") or "").strip()
    if env and os.path.isfile(env):
        return env

    found = shutil.which("chrome.exe") or shutil.which("chrome")
    if found and os.path.isfile(found):
        return found

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    la = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pfx, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(la, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pfx, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""


def default_config() -> dict:
    return {
        "chrome_exe": detect_chrome_exe(),
        "debug_port": DEFAULT_DEBUG_PORT,
        "user_data_dir": AUTO_LISTING_CHROME_USER_DATA,
        "result_dir": AUTO_LISTING_RESULTS_DIR,
        "sync_dir": AUTO_LISTING_SYNC_DIR,
        "shop_key": "juyou",
        "publish_after_save": False,
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        if os.path.isfile(AUTO_LISTING_CONFIG_FILE):
            with open(AUTO_LISTING_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    merged = default_config()
    merged.update(cfg or {})
    for d in (AUTO_LISTING_DIR, AUTO_LISTING_SYNC_DIR, AUTO_LISTING_RESULTS_DIR):
        os.makedirs(d, exist_ok=True)
    with open(AUTO_LISTING_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged

