# -*- coding: utf-8 -*-
"""
浏览器扩展本地桥接服务（仿 Billfish/Eagle 的 localhost API）。

螺丝钉客户端内嵌一个仅监听 127.0.0.1 的 HTTP 服务，浏览器扩展
（studio/assets/extension/）采集网页素材后 POST 到这里，由客户端
负责下载落盘，并可选择触发服务端 /material/scan 入库。

接口：
    GET  /ping          连通性检测
    GET  /status        运行状态（保存目录/已采集计数）
    POST /collect       采集单个素材 {"url", "media_type", "page_url", "page_title", "referer"}
    POST /collect_batch 批量采集 {"items": [...]}

配置持久化在 data/extension_bridge.json，采集记录持久化在
data/extension_collected.json（保留最近 200 条）。
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, Signal

from config.paths import AI_CONFIG_FILE, APPS_DIR, DATA_DIR, MATERIALS_DIR, TMP_DIR, get_bin
from utils.logger_utils import log

DEFAULT_PORT = 51233
MAX_RECORDS = 200
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # 512 MB 上限，防止误采超大文件
SCAN_MIN_INTERVAL = 60.0  # 触发服务端扫描的最小间隔（秒）
STALL_TIMEOUT = 90  # yt-dlp 无输出超时（秒）：超过则判定卡死（如 YouTube 反爬），主动终止


class _DownloadStalled(RuntimeError):
    """yt-dlp 下载卡死（无进度/解析阶段超时），需向上传播以跳过后续直链兜底。"""

_CONFIG_FILE = os.path.join(DATA_DIR, "extension_bridge.json")
_RECORDS_FILE = os.path.join(DATA_DIR, "extension_collected.json")

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp", "image/svg+xml": ".svg",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "audio/mpeg": ".mp3", "audio/wav": ".wav",
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_HLS_RE = re.compile(r"\.m3u8(\?|#|$)", re.IGNORECASE)

# requests 用 socks5 代理需 PySocks 依赖（yt-dlp/ffmpeg 子进程不受影响，自带 socks 支持）
try:
    import socks  # noqa: F401  PySocks
    _HAS_PYSOCKS = True
except Exception:
    _HAS_PYSOCKS = False

# 平台识别（按页面域名归组素材目录）
_PLATFORM_MAP = [
    ("douyin.com", "抖音"), ("iesdouyin.com", "抖音"),
    ("bilibili.com", "B站"), ("b23.tv", "B站"),
    ("xiaohongshu.com", "小红书"), ("xhslink.com", "小红书"),
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"), ("googlevideo.com", "YouTube"),
    ("tiktok.com", "TikTok"),
    ("kuaishou.com", "快手"),
    ("weibo.com", "微博"),
    ("weixin.qq.com", "微信"), ("channels.weixin.qq.com", "视频号"),
    ("jimeng", "即梦"),
]


def _platform_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    for key, name in _PLATFORM_MAP:
        if key in host:
            return name
    return "其他"


def _is_youtube(url: str, page_url: str = "", referer: str = "") -> bool:
    """判断下载是否属于 YouTube 场景（页面/来源/直链任一命中 YouTube）。"""
    return _platform_of(page_url or referer or url) == "YouTube"


def _find_ytdlp() -> str:
    """定位 yt-dlp（优先素材浏览器自带的，其次 PATH）。"""
    c = os.path.join(APPS_DIR, "asset-browser", "bin", "yt-dlp.exe")
    if os.path.isfile(c):
        return c
    found = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    return found or ""


def _find_ffmpeg() -> str:
    """定位 ffmpeg（优先工程内置 bin/win，其次素材浏览器自带，最后 PATH）。"""
    try:
        p = get_bin("ffmpeg")
        if os.path.isfile(p):
            return p
    except Exception:
        pass
    c = os.path.join(APPS_DIR, "asset-browser", "bin", "ffmpeg.exe")
    if os.path.isfile(c):
        return c
    found = shutil.which("ffmpeg")
    return found or ""


def _find_node() -> str:
    """定位 node.js（YouTube n 签名挑战求解需要 JS 运行时；yt_dlp_ejs 求解脚本已内置）。

    优先素材浏览器自带的 node.exe（与 yt-dlp / ffmpeg 同目录），其次 PATH。
    YouTube 新版播放器需要 JS 运行时解 n 参数签名，否则只能拿到 storyboard（缩略图）、
    报 "n challenge solving failed" / "Only images are available"。
    """
    c = os.path.join(APPS_DIR, "asset-browser", "bin", "node.exe")
    if os.path.isfile(c):
        return c
    found = shutil.which("node") or shutil.which("node.exe")
    return found or ""


def _normalize_proxy(addr: str) -> str:
    """规整用户填写的代理地址为 yt-dlp/requests 可识别的形式。

    只填了 host:port 时默认按 http 补全（http 代理兼容性最好：yt-dlp/ffmpeg/
    requests 原生支持，无需 PySocks 依赖；Clash 的混合端口、v2rayN 的 http
    端口都是 http 代理）。已带 scheme(http/https/socks5/socks5h) 则原样返回。

    若你的代理软件只开了 socks5 端口，请显式写成 socks5://127.0.0.1:端口。
    """
    addr = (addr or "").strip()
    if not addr:
        return ""
    if "://" not in addr:
        addr = "http://" + addr
    return addr


_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                   "http_proxy", "https_proxy", "all_proxy")


def _build_dl_env(proxy: str) -> dict:
    """构造下载子进程的环境变量：注入代理（全链路继承）。

    以环境变量方式注入 —— yt-dlp / ffmpeg / requests 统一继承，无需分别传命令行参数。
    同时设置 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 三个变量，覆盖不同库的读取约定
    （requests 读 HTTP_PROXY/HTTPS_PROXY；yt-dlp 两者都读；socks 代理用 ALL_PROXY）。

    未配置代理时主动剔除环境里已存在的代理变量，保证"直连"不受宿主环境
    （企业网/全局代理等）影响，子进程行为完全由本函数决定。
    """
    env = os.environ.copy()
    for k in _PROXY_ENV_KEYS:
        env.pop(k, None)
    p = _normalize_proxy(proxy)
    if p:
        for k in _PROXY_ENV_KEYS:
            env[k] = p
    return env


def default_config() -> dict:
    return {
        "port": DEFAULT_PORT,
        "save_dir": os.path.join(MATERIALS_DIR, "collected"),
        "auto_start": True,
        # 服务端可见的扫描目录（NAS 路径，留空则不触发服务端入库扫描）
        "server_scan_dir": "",
        # 本地映射网盘目录（与 server_scan_dir 对应），下载成功后同步复制到此
        "nas_sync_dir": "",
        # yt-dlp 读取 cookies 的浏览器（YouTube 等站点防机器人校验需要）：""=不用 chrome/edge/firefox
        "cookies_browser": "",
        # 视频下载完成后自动生成字幕（调用服务端 Whisper）
        "auto_subtitle": False,
        # 代理地址（用户自己的代理软件暴露的本地端口），如 socks5://127.0.0.1:1080
        # 留空不走代理。仅 YouTube 下载时使用代理，其他站点（B站/抖音等）直连。
        # YouTube 需翻墙，未配置代理时 yt-dlp 直连超时、反复卡在
        # "Downloading webpage"，最终被判卡死而失败。
        "proxy": "",
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        if os.path.isfile(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[扩展桥接] 保存配置失败: {e}")


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip().strip(".")
    return name[:120] or "file"


def _guess_extension(url: str, content_type: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    if ext and 1 < len(ext) <= 6 and re.fullmatch(r"\.[A-Za-z0-9]+", ext):
        return ext.lower()
    return _CONTENT_TYPE_EXT.get((content_type or "").split(";")[0].strip().lower(), ".bin")


def _compute_server_url() -> str:
    try:
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return (json.load(f).get("compute_server_url") or "").strip().rstrip("/")
    except Exception:
        pass
    return ""


class _Handler(BaseHTTPRequestHandler):
    bridge = None  # 由 ExtensionBridge.start 注入

    def log_message(self, fmt, *args):  # 静音默认 stderr 日志
        pass

    # ── 工具 ──
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 8 * 1024 * 1024:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ── 路由 ──
    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        b = self.bridge
        if self.path.startswith("/ping"):
            self._send_json({"ok": True, "name": "luosiding-collect", "version": 1,
                             "port": b.port if b else 0})
        elif self.path.startswith("/status"):
            self._send_json({
                "ok": True,
                "running": bool(b and b.is_running),
                "collected": b.collected_count if b else 0,
                "failed": b.failed_count if b else 0,
                "save_dir": b.save_dir if b else "",
            })
        elif self.path.startswith("/tasks"):
            self._send_json({"ok": True, "tasks": b.tasks_snapshot() if b else []})
        elif self.path.startswith("/task/"):
            parts = self.path.strip("/").split("/")
            if len(parts) >= 3:
                tid = parts[1]
                action = parts[2]
                if action == "cancel" and b:
                    b.cancel_task(tid)
                    self._send_json({"ok": True})
                elif action == "retry" and b:
                    b.retry_task(tid)
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "unknown_action"}, 404)
            else:
                self._send_json({"ok": False, "error": "invalid_path"}, 404)
        else:
            self._send_json({"ok": False, "error": "not_found"}, 404)

    def do_POST(self):
        b = self.bridge
        if b is None:
            self._send_json({"ok": False, "error": "bridge_down"}, 503)
            return
        if self.path.startswith("/collect_batch"):
            items = (self._read_json().get("items") or [])[:200]
            task_ids = [tid for tid in (b.enqueue(it) for it in items) if tid]
            self._send_json({"ok": bool(task_ids), "queued": len(task_ids), "task_ids": task_ids})
        elif self.path.startswith("/open_dir"):
            self._send_json({"ok": b.open_save_dir()})
        elif self.path.startswith("/collect"):
            tid = b.enqueue(self._read_json())
            self._send_json({"ok": bool(tid), "queued": 1 if tid else 0, "task_id": tid})
        else:
            self._send_json({"ok": False, "error": "not_found"}, 404)


class ExtensionBridge(QObject):
    """本地桥接服务：接收扩展采集请求 → 后台下载落盘 → 可选触发服务端扫描。"""

    log_message = Signal(str)
    record_added = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._thread = None
        self._queue = queue.Queue()
        self._workers = []
        self._records = deque(maxlen=MAX_RECORDS)
        self._seen_urls = set()
        self._lock = threading.Lock()
        self._dl_tasks = {}       # task_id -> 下载任务进度
        self._dl_lock = threading.Lock()
        self._task_seq = 0
        self.collected_count = 0
        self.failed_count = 0
        self._last_scan_ts = 0.0
        self.config = load_config()
        self._load_records()

    # ── 属性 ──
    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return int(self.config.get("port") or DEFAULT_PORT)

    @property
    def save_dir(self) -> str:
        return self.config.get("save_dir") or ""

    @property
    def records(self) -> list:
        with self._lock:
            return list(self._records)

    # ── 配置 ──
    def update_config(self, **kwargs):
        self.config.update(kwargs)
        save_config(self.config)

    # ── 生命周期 ──
    def start(self) -> tuple[bool, str]:
        if self.is_running:
            return True, "已在运行"
        try:
            os.makedirs(self.save_dir, exist_ok=True)
        except Exception as e:
            return False, f"采集保存目录不可用: {e}"
        try:
            _Handler.bridge = self
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except OSError as e:
            self._server = None
            return False, f"端口 {self.port} 启动失败: {e}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.5}, daemon=True)
        self._thread.start()
        if not self._workers:
            for _ in range(2):
                t = threading.Thread(target=self._download_loop, daemon=True)
                t.start()
                self._workers.append(t)
        msg = f"[扩展桥接] 服务已启动 http://127.0.0.1:{self.port} 保存目录: {self.save_dir}"
        log.info(msg)
        self.log_message.emit(msg)
        return True, "已启动"

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            log.info("[扩展桥接] 服务已停止")
            self.log_message.emit("[扩展桥接] 服务已停止")

    def open_save_dir(self) -> bool:
        """在文件管理器中打开采集保存目录（供扩展「打开目录」按钮调用）。"""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            os.startfile(self.save_dir)
            return True
        except Exception as e:
            log.error(f"[扩展桥接] 打开目录失败: {e}")
            return False

    # ── 采集 ──
    def enqueue(self, item: dict):
        url = (item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return ""
        if url in self._seen_urls:
            return ""
        self._seen_urls.add(url)
        self._task_seq += 1
        task_id = f"t{self._task_seq}_{int(time.time() * 1000) % 100000}"
        # 初始文件名优先用页面标题（yt-dlp 解析出真实标题后会替换）
        initial_name = ""
        title = (item.get("page_title") or "").strip()
        if title:
            initial_name = _sanitize_filename(title)[:80] + ".mp4"
        elif url.startswith(("http://", "https://")):
            try:
                base = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
                if base and len(base) > 2:
                    initial_name = _sanitize_filename(base)[:80] + ".mp4"
            except Exception:
                pass
        with self._dl_lock:
            now = time.time()
            self._dl_tasks[task_id] = {
                "id": task_id, "url": url, "media_type": item.get("media_type") or "file",
                "filename": initial_name, "percent": -1, "received": 0, "total": 0,
                "speed_str": "", "status": "queued", "error": "",
                "ts": now,           # 任务创建时间（排序用）
                "status_ts": now,    # 状态变更时间（清理 done/fail 任务用）
                "proc_id": -1,  # 子进程 PID，供取消时终止
            }
        self._queue.put((task_id, {
            "url": url,
            "media_type": item.get("media_type") or "file",
            "page_url": item.get("page_url") or "",
            "page_title": item.get("page_title") or "",
            "referer": item.get("referer") or item.get("page_url") or "",
            # 扩展通过 chrome.cookies 导出的 Netscape cookies 文本（YouTube 等站点用）
            "cookies": item.get("cookies") or "",
            # 扩展从页面 JS 提取的 YouTube PO Token（绕过锁库）
            "po_token": item.get("po_token") or "",
        }))
        return task_id

    def cancel_task(self, task_id: str) -> bool:
        """取消下载任务：终止子进程，标记为 fail。"""
        with self._dl_lock:
            t = self._dl_tasks.get(task_id)
            if t is None or t["status"] in ("done", "fail"):
                return False
            proc_id = t.get("proc_id", -1)
            t["status"] = "fail"
            t["error"] = "用户取消"
            t["status_ts"] = time.time()  # 标记变更时间，供 tasks_snapshot 清理
        if proc_id > 0:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc_id)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        return True

    def retry_task(self, task_id: str):
        """重新下载失败的/已完成的任务，入列重试。"""
        with self._dl_lock:
            t = self._dl_tasks.get(task_id)
            if t is None:
                return
            url = t["url"]
            media_type = t["media_type"]
            self._dl_tasks.pop(task_id, None)
        self.enqueue({"url": url, "media_type": media_type,
                       "page_url": "", "page_title": "", "referer": "", "cookies": ""})

    def tasks_snapshot(self):
        """下载任务快照（供扩展轮询进度）；已完成/失败超过 30 秒的自动清理。

        清理按 status_ts（状态变更时间）判断，而非任务创建时间 ts——
        这样取消/失败的任务会在变更后 30 秒消失，而不是创建满 2 分钟才消失。
        """
        now = time.time()
        with self._dl_lock:
            stale = [tid for tid, t in self._dl_tasks.items()
                     if t["status"] in ("done", "fail")
                     and now - t.get("status_ts", t["ts"]) > 30]
            for tid in stale:
                self._dl_tasks.pop(tid, None)
            tasks = sorted(self._dl_tasks.values(), key=lambda t: t["ts"], reverse=True)
            return [{k: v for k, v in t.items() if k != "proc_id"} for t in tasks[:20]]

    def _upd_task(self, task_id, **kwargs):
        with self._dl_lock:
            t = self._dl_tasks.get(task_id)
            if t is not None:
                t.update(kwargs)
                # status 变化时记录变更时间（供 tasks_snapshot 清理 done/fail 任务）
                if "status" in kwargs:
                    t["status_ts"] = time.time()

    def _upd_task_speed(self, task_id, received, total_now, elapsed):
        speed_bps = received / max(elapsed, 0.001)
        if speed_bps > 1024 * 1024:
            speed_str = f"{speed_bps / (1024*1024):.1f} MB/s"
        else:
            speed_str = f"{speed_bps / 1024:.0f} KB/s"
        with self._dl_lock:
            t = self._dl_tasks.get(task_id)
            if t is not None:
                t["speed_str"] = speed_str
                t["received"] = received
                t["total"] = total_now

    def _download_loop(self):
        import requests
        while True:
            task_id, item = self._queue.get()
            try:
                self._upd_task(task_id, status="downloading")
                self._download_one(requests, item, task_id)
            except Exception as e:
                log.error(f"[扩展桥接] 下载异常: {e}")
                self._upd_task(task_id, status="fail", error=str(e)[:200])
            finally:
                self._queue.task_done()

    def _download_one(self, requests, item: dict, task_id: str = ""):
        url = item["url"]
        rec = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "media_type": item["media_type"],
            "page_url": item["page_url"],
            "page_title": item["page_title"],
            "filename": "",
            "status": "fail",
            "error": "",
            "synced": "",
        }
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            path = None
            # 视频/音频/HLS：走 yt-dlp / ffmpeg（对齐素材浏览器的下载能力）
            if item["media_type"] in ("video", "audio") or _HLS_RE.search(url):
                path = self._download_media(url, item, task_id)
            if not path:
                try:
                    path = self._direct_download(requests, url, item, task_id)
                except Exception as e:
                    # 直链失效（签名过期/探测流）→ 自动回退整页解析，无需用户选择下载方式
                    page = item.get("page_url") or item.get("referer") or ""
                    if (item["media_type"] in ("video", "audio") and page.startswith("http")
                            and page != url):
                        log.info(f"[扩展桥接] 直链下载失败({e})，回退整页解析: {page}")
                        self.log_message.emit("[扩展桥接] 流地址已失效，自动改用整页解析下载…")
                        path = self._download_media(page, item, task_id)
                    if not path:
                        raise
            rec.update(filename=os.path.basename(path), status="ok")
            self._upd_task(task_id, status="done", percent=100,
                           filename=os.path.basename(path))
            self.collected_count += 1
            msg = f"[扩展桥接] 已采集: {rec['filename']} ← {item['page_title'] or url}"
            log.info(msg)
            self.log_message.emit(msg)
            self._sync_to_nas(path, rec)
            self._maybe_generate_subtitle(path, rec)
            self._maybe_trigger_server_scan()
        except Exception as e:
            rec["error"] = str(e)[:200]
            self._upd_task(task_id, status="fail", error=str(e)[:200])
            self.failed_count += 1
            msg = f"[扩展桥接] 采集失败 {url}: {e}"
            log.error(msg)
            self.log_message.emit(msg)
        self._append_record(rec)

    # ── 下载策略 ──

    def _unique_path(self, directory: str, filename: str) -> str:
        """目录内重名避让：name.ext → name (1).ext"""
        base, ext = os.path.splitext(filename)
        path = os.path.join(directory, filename)
        n = 1
        while os.path.exists(path):
            path = os.path.join(directory, f"{base} ({n}){ext}")
            n += 1
        return path

    def _direct_download(self, requests, url: str, item: dict, task_id: str = "") -> str:
        """常规 HTTP 直链下载（图片/文件/单视频），返回保存路径。

        目录结构：保存目录/<平台>/_未分组/<文件名>_<日期>.<ext>
        """
        from utils.http_client import http_get
        headers = {"User-Agent": _UA}
        if item["referer"]:
            headers["Referer"] = item["referer"]
        # 仅 YouTube 下载使用代理，其他平台直连，避免国内站点被代理拖慢/拦截。
        proxy = _normalize_proxy(self.config.get("proxy", "")) if _is_youtube(
            url, item.get("page_url") or "", item.get("referer") or "") else ""
        # requests 用 socks 代理需 PySocks 依赖；未装时对 requests 跳过 socks 代理
        # （不影响 yt-dlp/ffmpeg 子进程——它们已通过运行环境 env 统一走代理）。
        # 显式传 {"http": None, "https": None} 可屏蔽 requests 对环境变量代理的回退，
        # 保证非 YouTube 下载是真实直连（与 _build_dl_env 剔除代理变量保持一致）。
        proxies = {"http": None, "https": None}
        if proxy and not (proxy.startswith("socks") and not _HAS_PYSOCKS):
            proxies = {"http": proxy, "https": proxy}
        with http_get(url, headers=headers, stream=True,
                      timeout=(10, 60), allow_redirects=True, proxies=proxies) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            # 媒体流校验：返回 HTML/JSON/文本说明是错误页或无效探测流，不是真实媒体
            is_media = item["media_type"] in ("video", "audio")
            if is_media and ("text/" in ctype or "json" in ctype or "html" in ctype):
                raise RuntimeError(f"无效的媒体响应({ctype})，该流地址已失效或需要整页解析下载")
            ext = _guess_extension(url, ctype)
            base = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
            if not base or len(base) < 2:
                base = re.sub(r"\s+", "_", (item["page_title"] or "material").strip())[:40] or "material"
            platform = _platform_of(item.get("page_url") or item.get("referer") or url)
            sub_dir = os.path.join(self.save_dir, platform, "_未分组")
            os.makedirs(sub_dir, exist_ok=True)
            name = f"{_sanitize_filename(base)}_{time.strftime('%Y%m%d')}{ext}"
            path = self._unique_path(sub_dir, name)
            if task_id:
                self._upd_task(task_id, filename=name,
                               total=int(resp.headers.get("Content-Length") or 0))
            _speed_ts = time.time()
            _speed_bytes = 0
            total = 0
            with open(path, "wb") as f:
                for chunk in resp.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("文件超过 512MB 上限，已放弃")
                    f.write(chunk)
                    if task_id:
                        cap = int(resp.headers.get("Content-Length") or 0)
                        self._upd_task(task_id, received=total,
                                       percent=round(total * 100 / cap, 1) if cap else -1)
                        _speed_bytes += len(chunk)
                        now = time.time()
                        if now - _speed_ts > 0.5:
                            self._upd_task_speed(task_id, _speed_bytes, cap, now - _speed_ts)
                            _speed_ts = now
                            _speed_bytes = 0
        # 媒体流体积校验：几十字节的"视频"必为无效响应，删除并报错
        if is_media and total < 100 * 1024:
            try:
                os.remove(path)
            except OSError:
                pass
            raise RuntimeError(f"媒体文件异常小({total}B)，该流地址已失效；建议用「下载本页视频」整页解析")
        return path

    def _download_media(self, url: str, item: dict, task_id: str = "") -> str:
        """视频/音频下载：yt-dlp（DASH/HLS/音视频合并）→ ffmpeg（仅 HLS）。失败返回 ""。"""
        path = self._try_ytdlp(url, item, task_id)
        if not path and _HLS_RE.search(url):
            path = self._try_ffmpeg_hls(url, item)
        return path or ""

    def _media_out_base(self, item: dict, url: str) -> str:
        base = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
        if not base or len(base) < 2 or base.lower() == "playlist":
            base = re.sub(r"\s+", "_", (item["page_title"] or "video").strip())[:40] or "video"
        return _sanitize_filename(base)

    def _try_ytdlp(self, url: str, item: dict, task_id: str = "") -> str:
        ytdlp = _find_ytdlp()
        if not ytdlp:
            return ""
        platform = _platform_of(item.get("page_url") or item.get("referer") or url)
        use_proxy = _is_youtube(url, item.get("page_url") or "", item.get("referer") or "")
        # 目录结构：<保存目录>/<平台>/<UP主>/<标题>_[<上传日期>].<ext>
        out_tmpl = os.path.join(
            self.save_dir, platform, "%(uploader|unknown)s",
            "%(title).80s_[%(upload_date>%Y%m%d|nodate)s].%(ext)s")
        base_cmd = [ytdlp, "--no-playlist", "--no-warnings",
                    "--windows-filenames", "--newline",
                    "-f", "bv*+ba/b", "--merge-output-format", "mp4",
                    "--retries", "3", "--socket-timeout", "15", "-o", out_tmpl]
        if item["referer"]:
            base_cmd += ["--referer", item["referer"]]
        base_cmd += ["--user-agent", _UA]
        # YouTube PO Token（通过扩展内容脚本从页面 JS 提取，绕过 --cookies-from-browser 锁库问题）
        # 正确格式见下方 _extractor_args()：player-client=default;po_token=web+TOKEN
        # （旧代码 youtube:po_token=XXX 是非法格式；单独 web 客户端拿不到格式，必须用 default）
        po_token = (item.get("po_token") or "").strip()
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            base_cmd += ["--ffmpeg-location", os.path.dirname(ffmpeg)]

        # JS 运行时（YouTube n 签名挑战求解必需）：
        # 新版 yt-dlp 默认只启用 deno 运行时，未装 deno 时 YouTube 的 n 参数签名无法解开，
        # 导致 "n challenge solving failed" → 只拿到 storyboard 缩略图 → "Only images are available"。
        # 用内置 node.exe 作为 JS 运行时（yt_dlp_ejs 挑战求解脚本已内置，0.8.0）。
        # 注意：必须 --no-js-runtimes 先清默认，再显式启用 node，否则默认的 deno 优先级会盖过。
        node_bin = _find_node()
        if node_bin:
            base_cmd += ["--no-js-runtimes", "--js-runtimes", f"node:{node_bin}"]

        # cookies 策略：
        # 1) 扩展导出的 cookies 文件优先（不受浏览器锁库/App-Bound 加密限制）
        # 2) 仅当用户【显式配置】了 cookies_browser 时，才用该浏览器读取 cookies；
        #    未配置则不试任何浏览器（无脑试 edge/chrome/firefox 会在浏览器运行时
        #    因 cookie 数据库被锁而逐个失败、浪费大量时间，最后还得回退无 cookie）。
        cookie_file = ""
        if item.get("cookies"):
            try:
                cookie_file = os.path.join(TMP_DIR, f"ext_cookies_{abs(hash(url)) % 100000}.txt")
                with open(cookie_file, "w", encoding="utf-8") as f:
                    f.write(item["cookies"])
            except Exception as e:
                log.error(f"[扩展桥接] 写 cookies 临时文件失败: {e}")
                cookie_file = ""
        cookie_tries = []
        if cookie_file:
            cookie_tries.append(("file", cookie_file))
        configured = (self.config.get("cookies_browser") or "").strip().lower()
        if configured in ("chrome", "edge", "firefox", "brave", "opera"):
            cookie_tries.append(("browser", configured))

        # 构造可选的 extractor-args：有 PO Token 时用 web 客户端绑定 token（合法格式），
        # 否则不强制 player_client —— 让 yt-dlp 用内置多客户端策略（实测最稳，能拿到格式）
        def _extractor_args(po_token):
            if po_token:
                return ["--extractor-args", f"youtube:player-client=default;po_token=web+{po_token}"]
            return []  # 默认客户端：不传 extractor-args（web/tv_embedded/mweb 客户端实测拿不到格式）

        last_err = ""
        found = ""
        for kind, val in cookie_tries:
            cmd = list(base_cmd) + _extractor_args(po_token)
            if kind == "file":
                cmd += ["--cookies", val]
            elif val:
                cmd += ["--cookies-from-browser", val]
            cmd.append(url)
            found = self._run_ytdlp(cmd, task_id, use_proxy=use_proxy)
            if found:
                # yt-dlp generic 提取器也可能"成功"下载几十字节的错误页，按无效处理
                try:
                    fsize = os.path.getsize(found)
                except OSError:
                    fsize = 0
                if item["media_type"] in ("video", "audio") and fsize < 100 * 1024:
                    log.error(f"[扩展桥接] yt-dlp 产物异常小({fsize}B)，按无效流处理: {found}")
                    try:
                        os.remove(found)
                    except OSError:
                        pass
                    found = ""
            if found:
                if cookie_file:
                    try:
                        os.remove(cookie_file)
                    except OSError:
                        pass
                return found
            last_err = self._ytdlp_last_error
            # 非校验类错误（如无此视频）不必再试其他 cookies
            if last_err and not re.search(r"bot|sign in|cookies|403|429|private|login", last_err, re.I):
                break
        # 所有带 token/cookies 的尝试均失败 → 最终兜底：默认客户端（不传 extractor-args）。
        # 注意：旧的 tv_embedded/android player_client 兜底已废弃 —— 这两个客户端在当前
        # YouTube 已拿不到格式（实测格式列表为空），会导致 "Requested format is not available"。
        # 默认客户端让 yt-dlp 用内置多客户端策略（android/web 等），实测能拿到完整格式列表。
        if not found:
            # 兜底不再带 po_token（token 若有效第一次就成功了；带它反而可能因格式问题失败）
            cmd = list(base_cmd) + [url]
            found = self._run_ytdlp(cmd, task_id, use_proxy=use_proxy)
            if found:
                try:
                    fsize = os.path.getsize(found)
                except OSError:
                    fsize = 0
                if item["media_type"] in ("video", "audio") and fsize < 100 * 1024:
                    try:
                        os.remove(found)
                    except OSError:
                        pass
                    found = ""
        if found:
            if cookie_file:
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass
            return found
        if cookie_file:
            try:
                os.remove(cookie_file)
            except OSError:
                pass
        if last_err:
            log.error(f"[扩展桥接] yt-dlp 失败: {last_err[:200]}")
        return ""

    _ytdlp_last_error = ""

    def _run_ytdlp(self, cmd: list, task_id: str = "", use_proxy: bool = False) -> str:
        """执行一次 yt-dlp 下载（带进度解析+速度解析），成功返回文件路径，失败返回 ""。

        内置无进度超时（两种卡死场景）：
        1) 进程无任何输出超过 STALL_TIMEOUT 秒（网络完全无响应）
        2) 进程有输出但长时间停留在解析阶段（如 YouTube 反爬时反复
           "Downloading webpage"），超过 STALL_TIMEOUT 秒仍未进入实际下载
        命中任一即主动终止子进程，避免 UI 永久卡在"下载中 0%"。
        """
        try:
            start_ts = time.time()
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=_build_dl_env(self.config.get("proxy", "") if use_proxy else ""))
            if task_id:
                with self._dl_lock:
                    t = self._dl_tasks.get(task_id)
                    if t:
                        t["proc_id"] = proc.pid
            tail = []
            last_output_ts = time.time()
            download_started = False  # 是否已进入实际下载（看到 [download] 进度）
            stalled = False
            while True:
                line = proc.stdout.readline()
                if line == "":
                    # EOF：进程输出结束
                    if proc.poll() is not None:
                        break
                    # 进程还活着但无输出 → 检查是否卡死（场景1）
                    if time.time() - last_output_ts > STALL_TIMEOUT:
                        stalled = True
                        break
                    time.sleep(0.2)
                    continue
                last_output_ts = time.time()
                line = line.strip()
                if line:
                    tail.append(line)
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m and task_id:
                    self._upd_task(task_id, percent=float(m.group(1)), status="downloading")
                # 解析速度: "at 1.2MiB/s" 或 "at 3.2 MB/s"
                sm = re.search(r"at\s+([\d.]+)\s*(\w?i?B)/s", line)
                if sm and task_id:
                    self._upd_task(task_id, speed_str=f"{sm.group(1)} {sm.group(2)}/s")
                if task_id and ("[Merger]" in line or "Merging formats" in line):
                    self._upd_task(task_id, status="merging")
                # 标记已进入实际下载阶段（看到下载进度或 Destination 行）
                if m or "[download]" in line or "[Merger]" in line or "Destination" in line:
                    download_started = True
                # 场景2：有输出但长时间停留在解析阶段未进入下载
                # （YouTube 反爬时反复输出 Downloading webpage，但永远到不了 download 阶段）
                if not download_started and time.time() - start_ts > STALL_TIMEOUT:
                    stalled = True
                    break
            if stalled:
                try:
                    proc.kill()
                except Exception:
                    pass
                self._ytdlp_last_error = f"下载卡住无响应（{STALL_TIMEOUT}秒无进度，可能被站点反爬拦截，建议配置 cookies）"
                log.error(f"[扩展桥接] yt-dlp 无进度超时终止: {self._ytdlp_last_error}")
                # 抛专用异常向上传播：让 _download_one 直接标记 fail 并保留此错误信息，
                # 避免后续 _direct_download 覆盖成"无效媒体响应"等无关错误
                raise _DownloadStalled(self._ytdlp_last_error)
            proc.wait(timeout=300)
            if proc.returncode == 0:
                found = self._find_new_file(start_ts)
                if found:
                    if task_id:
                        self._upd_task(task_id, filename=os.path.basename(found), percent=99)
                    return found
            self._ytdlp_last_error = tail[-1] if tail else "未知错误"
        except _DownloadStalled:
            raise  # stall 异常向上传播，由 _download_one 处理
        except Exception as e:
            self._ytdlp_last_error = str(e)
            log.error(f"[扩展桥接] yt-dlp 异常: {e}")
        return ""

    def _find_new_file(self, start_ts: float) -> str:
        """在保存目录中找 start_ts 之后新生成的媒体文件（适配平台/UP主子目录结构）。"""
        newest, newest_mt = "", 0.0
        for root, _dirs, files in os.walk(self.save_dir):
            for f in files:
                if f.endswith((".part", ".ytdl", ".tmp")):
                    continue
                fp = os.path.join(root, f)
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                if mt >= start_ts - 5 and mt > newest_mt:
                    newest, newest_mt = fp, mt
        return newest

    def _try_ffmpeg_hls(self, url: str, item: dict) -> str:
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            return ""
        platform = _platform_of(item.get("page_url") or item.get("referer") or url)
        use_proxy = _is_youtube(url, item.get("page_url") or "", item.get("referer") or "")
        sub_dir = os.path.join(self.save_dir, platform, "_未分组")
        os.makedirs(sub_dir, exist_ok=True)
        out_path = self._unique_path(
            sub_dir, f"{self._media_out_base(item, url)}_{time.strftime('%Y%m%d')}.mp4")
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        if item["referer"]:
            cmd += ["-headers", f"Referer: {item['referer']}\r\n"]
        cmd += ["-user_agent", _UA, "-i", url, "-c", "copy",
                "-bsf:a", "aac_adtstoasc", out_path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               env=_build_dl_env(self.config.get("proxy", "") if use_proxy else ""))
            if r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return out_path
            tail = (r.stderr or "").strip().splitlines()
            log.error(f"[扩展桥接] ffmpeg HLS 失败: {(tail[-1] if tail else '未知')[:200]}")
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
        except Exception as e:
            log.error(f"[扩展桥接] ffmpeg HLS 异常: {e}")
        return ""

    # ── 字幕生成（可选）──

    def _maybe_generate_subtitle(self, video_path: str, rec: dict):
        """视频下载完成后，调用服务端 Whisper 生成同名 .srt（后台线程，不阻塞下载）。"""
        if not self.config.get("auto_subtitle"):
            return
        if rec.get("media_type") != "video":
            return
        threading.Thread(target=self._do_generate_subtitle,
                         args=(video_path,), daemon=True).start()

    def _do_generate_subtitle(self, video_path: str):
        try:
            from utils.asr_client import transcribe_remote, read_asr_url, segments_to_srt
            asr_url = read_asr_url()
            if not asr_url:
                log.warning("[扩展桥接] 未配置 Whisper/服务端地址，跳过字幕生成")
                return
            name = os.path.basename(video_path)
            self.log_message.emit(f"[扩展桥接] 正在生成字幕: {name}")
            log.info(f"[扩展桥接] 字幕生成开始: {video_path}")
            segments = transcribe_remote(video_path, asr_url, language="zh", timeout=1800)
            if not segments:
                log.warning(f"[扩展桥接] 字幕生成为空: {name}")
                return
            srt_path = os.path.splitext(video_path)[0] + ".srt"
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(segments_to_srt(segments))
            msg = f"[扩展桥接] 字幕已生成: {os.path.basename(srt_path)} ({len(segments)} 段)"
            log.info(msg)
            self.log_message.emit(msg)
            # 字幕随视频同结构同步到 NAS
            self._sync_to_nas(srt_path, {"synced": "", "error": ""})
        except Exception as e:
            log.error(f"[扩展桥接] 字幕生成失败 {video_path}: {e}")
            self.log_message.emit(f"[扩展桥接] 字幕生成失败: {e}")

    # ── NAS 同步 ──

    def _sync_to_nas(self, path: str, rec: dict):
        """下载成功后同步复制到本地映射的 NAS 目录（与保存目录相同的平台/UP主结构）。"""
        nas_dir = (self.config.get("nas_sync_dir") or "").strip()
        if not nas_dir:
            return
        try:
            # 保存目录本身就是 NAS 映射目录时无需再复制
            if os.path.normcase(os.path.abspath(os.path.dirname(path))) == \
                    os.path.normcase(os.path.abspath(nas_dir)):
                rec["synced"] = path
                return
            # 保持与保存目录一致的相对结构（平台/UP主/文件）
            try:
                rel = os.path.relpath(path, self.save_dir)
            except ValueError:
                rel = os.path.basename(path)  # 跨盘符时退化为平铺
            dest_dir = os.path.join(nas_dir, os.path.dirname(rel))
            os.makedirs(dest_dir, exist_ok=True)
            dest = self._unique_path(dest_dir, os.path.basename(path))
            shutil.copy2(path, dest)
            rec["synced"] = dest
            msg = f"[扩展桥接] 已同步到 NAS: {dest}"
            log.info(msg)
            self.log_message.emit(msg)
        except Exception as e:
            rec["error"] = (rec["error"] + f" | NAS同步失败: {e}").strip(" |")
            log.error(f"[扩展桥接] NAS 同步失败: {e}")

    # ── 服务端扫描（可选）──
    def _maybe_trigger_server_scan(self):
        scan_dir = (self.config.get("server_scan_dir") or "").strip()
        if not scan_dir:
            return
        now = time.time()
        if now - self._last_scan_ts < SCAN_MIN_INTERVAL:
            return
        self._last_scan_ts = now
        threading.Thread(target=self._do_server_scan, args=(scan_dir,), daemon=True).start()

    def _do_server_scan(self, scan_dir: str):
        base = _compute_server_url()
        if not base:
            return
        try:
            from utils.http_client import http_post
            resp = http_post(f"{base}/material/scan", json={"path": scan_dir}, timeout=15)
            log.info(f"[扩展桥接] 已触发服务端扫描 {scan_dir}: HTTP {resp.status_code}")
        except Exception as e:
            log.error(f"[扩展桥接] 触发服务端扫描失败: {e}")

    # ── 记录持久化 ──
    def clear_all_records(self) -> int:
        """清除所有采集记录（成功和失败）。返回清除条数。"""
        with self._lock:
            before = len(self._records)
            self._records = deque(maxlen=MAX_RECORDS)
            removed = before - len(self._records)
            snapshot = list(self._records)
        self.collected_count = 0
        self.failed_count = 0
        self._seen_urls.clear()
        try:
            with open(_RECORDS_FILE, "w", encoding="utf-8") as f:
                json.dump({"records": snapshot}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        return removed

    def clear_done_records(self) -> int:
        """清除已完成（含已同步 NAS）的采集记录，保留失败记录。返回清除条数。"""
        with self._lock:
            before = len(self._records)
            self._records = deque(
                (r for r in self._records if r.get("status") != "ok"),
                maxlen=MAX_RECORDS)
            removed = before - len(self._records)
            snapshot = list(self._records)
        self.collected_count = sum(1 for r in snapshot if r.get("status") == "ok")
        self.failed_count = sum(1 for r in snapshot if r.get("status") != "ok")
        try:
            with open(_RECORDS_FILE, "w", encoding="utf-8") as f:
                json.dump({"records": snapshot}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        return removed

    def _load_records(self):
        try:
            if os.path.isfile(_RECORDS_FILE):
                with open(_RECORDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for rec in data.get("records", [])[-MAX_RECORDS:]:
                    self._records.append(rec)
                    if rec.get("url"):
                        self._seen_urls.add(rec["url"])
                    if rec.get("status") == "ok":
                        self.collected_count += 1
                    else:
                        self.failed_count += 1
        except Exception:
            pass

    def _append_record(self, rec: dict):
        with self._lock:
            self._records.append(rec)
            snapshot = list(self._records)
        try:
            with open(_RECORDS_FILE, "w", encoding="utf-8") as f:
                json.dump({"records": snapshot}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        self.record_added.emit(rec)


_BRIDGE = None


def get_bridge() -> ExtensionBridge:
    """进程级单例（页面与 MainWindow 共用）。"""
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = ExtensionBridge()
    return _BRIDGE
