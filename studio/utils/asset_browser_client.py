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
import json
import os
import re
import shutil
import subprocess
import time

from config.paths import ASSET_BROWSER_DIR, KNOWLEDGE_MEDIA_DIR

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
    # "youtube": "YouTube",  # 暂时隐藏
}


def is_present() -> bool:
    """素材浏览器是否已就位（含 Electron 依赖）。"""
    return os.path.isfile(MAIN_JS) and os.path.isdir(
        os.path.join(ASSET_BROWSER_DIR, "node_modules", "electron"))


def _electron_exe() -> str | None:
    """定位可用的 electron 启动器（优先工程内 node_modules）。"""
    candidates = [
        os.path.join(ASSET_BROWSER_DIR, "node_modules", "electron", "dist",
                     "electron.exe"),
        os.path.join(ASSET_BROWSER_DIR, "node_modules", ".bin",
                     "electron.cmd"),
        os.path.join(ASSET_BROWSER_DIR, "node_modules", ".bin", "electron"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                if os.path.getsize(p) <= 0:
                    continue
            except OSError:
                continue
            return p
    return None


def _launch_asset_browser_process() -> tuple[bool, str]:
    """启动素材浏览器进程；优先 electron 启动器，失败则回退 npm.cmd start。"""
    flags = create_no_window_flag()
    exe = _electron_exe()
    launch_errors = []

    if exe:
        try:
            p = subprocess.Popen([exe, "."], cwd=ASSET_BROWSER_DIR, creationflags=flags)
            time.sleep(1.0)
            if p.poll() is None:
                return True, "ok"
            launch_errors.append(f"electron 进程异常退出(code={p.returncode})")
        except (OSError, subprocess.SubprocessError) as e:
            launch_errors.append(f"electron 启动失败: {e}")

    npm_candidates = []
    npm_candidates.extend([
        os.path.join(ASSET_BROWSER_DIR, "bin", "npm.cmd"),
        os.path.join(ASSET_BROWSER_DIR, "bin", "node_modules", "npm", "bin", "npm-cli.js"),  # noqa: E501
        shutil.which("npm.cmd") or "",
    ])

    for npm in [x for x in npm_candidates if x]:
        try:
            if npm.lower().endswith("npm-cli.js"):
                node_exe = os.path.join(ASSET_BROWSER_DIR, "bin", "node.exe")
                if not os.path.isfile(node_exe):
                    continue
                p = subprocess.Popen([node_exe, npm, "start"], cwd=ASSET_BROWSER_DIR, creationflags=flags)  # noqa: E501
            else:
                p = subprocess.Popen([npm, "start"], cwd=ASSET_BROWSER_DIR, creationflags=flags)  # noqa: E501
            time.sleep(1.0)
            if p.poll() is not None:
                launch_errors.append(f"npm 进程异常退出(code={p.returncode})")
                continue
            return True, "ok"
        except (OSError, subprocess.SubprocessError) as e:
            launch_errors.append(f"npm 启动失败({npm}): {e}")

    detail = "；".join(launch_errors) if launch_errors else "未找到可用的 electron 或 npm 启动器"
    return False, detail


def safe_name(name: str) -> str:
    """把选题名清洗成可作目录名的字符串。"""
    name = (name or "未命名选题").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name[:80] or "未命名选题"


def topic_dir(topic: str) -> str:
    """返回某选题的素材落地目录（绝对路径，已建好）。
    使用用户配置的媒体存储目录（与浏览器下载目录对齐）。"""
    d = os.path.join(KNOWLEDGE_MEDIA_DIR, safe_name(topic))
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
    except OSError as e:
        return False, f"写入握手文件失败: {e}", ""

    ok_launch, msg_launch = _launch_asset_browser_process()
    if not ok_launch:
        return False, f"启动素材浏览器失败: {msg_launch}", ""
    log.info(f"素材浏览器已启动：topic={topic} platform={platform} dir={dl_dir}")

    return True, f"已为选题「{topic}」打开{PLATFORMS.get(platform, platform)}搜索页", dl_dir


def launch() -> tuple[bool, str]:
    """直接打开素材浏览器（普通浏览模式，无握手）。返回 (ok, msg)。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    # 清掉可能残留的握手，确保以普通浏览模式打开
    try:
        if os.path.exists(HANDOFF_FILE):
            os.remove(HANDOFF_FILE)
    except OSError:
        pass
    ok_launch, msg_launch = _launch_asset_browser_process()
    if not ok_launch:
        return False, f"启动素材浏览器失败: {msg_launch}"
    log.info("素材浏览器已启动（普通浏览模式）")
    return True, "已打开素材浏览器"


def launch_dreamina_assets(download_dir: str) -> tuple[bool, str, str]:
    """打开素材浏览器并直达即梦页面，下载目录指向 download_dir。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。", ""
    dl_dir = os.path.abspath(download_dir or "").strip()
    if not dl_dir:
        return False, "下载目录不能为空。", ""
    os.makedirs(dl_dir, exist_ok=True)

    handoff = {
        "topic": "即梦素材",
        "platform": "jimeng",
        "searchUrl": "https://jimeng.jianying.com/ai-tool/image/generate",
        "downloadDir": dl_dir,
        "ts": int(time.time()),
    }
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump(handoff, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return False, f"写入握手文件失败: {e}", ""

    ok_launch, msg_launch = _launch_asset_browser_process()
    if not ok_launch:
        return False, f"启动素材浏览器失败: {msg_launch}", ""
    log.info(f"素材浏览器已启动（即梦素材模式）dir={dl_dir}")

    return True, "已打开素材浏览器并切到即梦页面", dl_dir


def launch_hotspot_capture(auto_quit: bool = False) -> tuple[bool, str]:
    """启动素材浏览器并自动采集今日各平台热榜。auto_quit=True 时采集完自动关闭（供每日定时任务）。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "hotspot", "autoQuit": auto_quit, "ts": int(time.time())},  # noqa: E501
                      f, ensure_ascii=False)
    except OSError as e:
        return False, f"写入握手文件失败: {e}"
    ok_launch, msg_launch = _launch_asset_browser_process()
    if not ok_launch:
        return False, f"启动素材浏览器失败: {msg_launch}"
    log.info(f"素材浏览器已启动（热点采集模式 autoQuit={auto_quit}）")
    return True, "已启动热点采集（依次打开各平台热榜页，采集完成写入清单）"


def launch_knowledge_sync() -> tuple[bool, str]:
    """启动素材浏览器并直接进入「关注同步（我的知识库）」模式。返回 (ok, msg)。"""
    if not is_present():
        return False, f"未找到素材浏览器或其依赖（{ASSET_BROWSER_DIR}）。"
    try:
        with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": "knowledge", "ts": int(time.time())}, f, ensure_ascii=False)  # noqa: E501
    except OSError as e:
        return False, f"写入握手文件失败: {e}"
    ok_launch, msg_launch = _launch_asset_browser_process()
    if not ok_launch:
        return False, f"启动素材浏览器失败: {msg_launch}"
    log.info("素材浏览器已启动（关注同步模式）")
    return True, "已打开素材浏览器（关注同步模式）"
