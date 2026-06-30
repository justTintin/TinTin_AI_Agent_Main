# -*- coding: utf-8 -*-
"""
素材下载浏览器（apps/asset-browser，Electron）客户端。

职责：把「选题 → 关键词」交给嗅探式浏览器，让它打开对应平台搜索页、
并把下载目录指到本选题专属文件夹（outputs/materials/<选题>），
用户在浏览器里浏览/嗅探/下载，产物随后由「素材管理」按目录索引入库。

握手协议（studio → 浏览器）：写 apps/asset-browser/handoff.json
    { "topic": "选题名", "keyword": "搜索词", "platform": "douyin",
      "downloadDir": "<绝对路径>", "ts": <epoch> }
浏览器启动时读取并消费（用后即删），据此打开搜索页 + 设定下载目录。
"""
import os
import re
import sys
import json
import time
import subprocess

from config.paths import ASSET_BROWSER_DIR, MATERIALS_DIR, KNOWLEDGE_MATERIALS_DIR
from utils.logger_utils import log
from utils.platform_utils import create_no_window_flag

MAIN_JS = os.path.join(ASSET_BROWSER_DIR, "main.js")
HANDOFF_FILE = os.path.join(ASSET_BROWSER_DIR, "handoff.json")

# 支持的平台 → 中文名（供 UI 下拉）
PLATFORMS = {
    "douyin": "抖音",
    "bilibili": "B 站",
    "xiaohongshu": "小红书",
    "tiktok": "TikTok",
    "youtube": "YouTube",
}


def is_present() -> bool:
    """素材浏览器是否已就位（含 Electron 依赖）。"""
    return os.path.isfile(MAIN_JS) and os.path.isdir(
        os.path.join(ASSET_BROWSER_DIR, "node_modules", "electron"))


def _electron_exe() -> str | None:
    """定位可用的 electron 启动器（优先工程内 node_modules）。"""
    candidates = [
        os.path.join(ASSET_BROWSER_DIR, "node_modules", ".bin",
                     "electron.cmd" if sys.platform == "win32" else "electron"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def safe_name(name: str) -> str:
    """把选题名清洗成可作目录名的字符串。"""
    name = (name or "未命名选题").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name[:80] or "未命名选题"


def topic_dir(topic: str) -> str:
    """返回某选题的素材落地目录（绝对路径，已建好）。
    使用用户配置的素材根目录（与浏览器下载目录对齐）。"""
    d = os.path.join(KNOWLEDGE_MATERIALS_DIR, safe_name(topic))
    os.makedirs(d, exist_ok=True)
    return d


def launch_for_topic(topic: str, keyword: str | None = None,
                     platform: str = "douyin") -> tuple[bool, str, str]:
    """
    为某选题启动素材浏览器。返回 (ok, msg, download_dir)。

    keyword 缺省用 topic 本身；platform 见 PLATFORMS。
    """
    if not is_present():
        return False, (f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。\n"
                       "请确认 apps/asset-browser 已就位且已 npm install。"), ""

    exe = _electron_exe()
    if not exe:
        return False, "未找到 electron 启动器（node_modules/.bin/electron）。", ""

    dl_dir = topic_dir(topic)
    handoff = {
        "topic": topic,
        "keyword": (keyword or topic).strip(),
        "platform": platform,
        "downloadDir": dl_dir,
        "ts": int(time.time()),
    }
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump(handoff, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, f"写入握手文件失败: {e}", ""

    flags = create_no_window_flag()  # CREATE_NO_WINDOW（隐藏控制台，Electron 自带窗口）
    try:
        subprocess.Popen([exe, "."], cwd=ASSET_BROWSER_DIR, creationflags=flags)
        log.info(f"素材浏览器已启动：topic={topic} platform={platform} dir={dl_dir}")
    except Exception as e:
        return False, f"启动素材浏览器失败: {e}", ""

    return True, f"已为选题「{topic}」打开{PLATFORMS.get(platform, platform)}搜索页", dl_dir


def launch() -> tuple[bool, str]:
    """直接打开素材浏览器（普通浏览模式，无握手）。返回 (ok, msg)。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    exe = _electron_exe()
    if not exe:
        return False, "未找到 electron 启动器（node_modules/.bin/electron）。"
    # 清掉可能残留的握手，确保以普通浏览模式打开
    try:
        if os.path.exists(HANDOFF_FILE):
            os.remove(HANDOFF_FILE)
    except Exception:
        pass
    flags = create_no_window_flag()
    try:
        subprocess.Popen([exe, "."], cwd=ASSET_BROWSER_DIR, creationflags=flags)
        log.info("素材浏览器已启动（普通浏览模式）")
    except Exception as e:
        return False, f"启动素材浏览器失败: {e}"
    return True, "已打开素材浏览器"


def launch_hotspot_capture(auto_quit: bool = False) -> tuple[bool, str]:
    """启动素材浏览器并自动采集今日各平台热榜。auto_quit=True 时采集完自动关闭（供每日定时任务）。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    exe = _electron_exe()
    if not exe:
        return False, "未找到 electron 启动器。"
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "hotspot", "autoQuit": auto_quit, "ts": int(time.time())},
                      f, ensure_ascii=False)
    except Exception as e:
        return False, f"写入握手文件失败: {e}"
    flags = create_no_window_flag()
    try:
        subprocess.Popen([exe, "."], cwd=ASSET_BROWSER_DIR, creationflags=flags)
        log.info(f"素材浏览器已启动（热点采集模式 autoQuit={auto_quit}）")
    except Exception as e:
        return False, f"启动素材浏览器失败: {e}"
    return True, "已启动热点采集（依次打开各平台热榜页，采集完成写入清单）"


def launch_knowledge_sync() -> tuple[bool, str]:
    """启动素材浏览器并直接进入「关注同步（我的知识库）」模式。返回 (ok, msg)。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    exe = _electron_exe()
    if not exe:
        return False, "未找到 electron 启动器（node_modules/.bin/electron）。"
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "knowledge", "ts": int(time.time())}, f, ensure_ascii=False)
    except Exception as e:
        return False, f"写入握手文件失败: {e}"
    flags = create_no_window_flag()
    try:
        subprocess.Popen([exe, "."], cwd=ASSET_BROWSER_DIR, creationflags=flags)
        log.info("素材浏览器已启动（关注同步模式）")
    except Exception as e:
        return False, f"启动素材浏览器失败: {e}"
    return True, "已打开素材浏览器（关注同步模式）"
