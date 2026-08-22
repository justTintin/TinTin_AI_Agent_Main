import contextlib
import json
import os
import subprocess
import threading
import time

import requests
from config.paths import APPS_DIR, LOG_DIR

from utils.http_client import http_get, http_post, resilient_get, resilient_post
from utils.logger_utils import log
from utils.platform_utils import create_no_window_flag, find_python

COMFYUI_DIR = os.path.join(APPS_DIR, "comfyui")
COMFYUI_MAIN = os.path.join(COMFYUI_DIR, "main.py")
COMFYUI_RUNNER = os.path.join(COMFYUI_DIR, "_run_local.py")

LOCAL_HOST = "X.X.X.X"
LOCAL_PORT = 8188
LOCAL_ADDR = f"http://{LOCAL_HOST}:{LOCAL_PORT}"

DEFAULT_EXTERNAL_ADDR = "http://X.X.X.X:8188"

_CREATE_NO_WINDOW = create_no_window_flag()

_PROXY_CACHE = None


def _read_proxy_addr() -> str | None:
    """从 ai_config 读取 compute_server_url（服务端代理地址）。"""
    global _PROXY_CACHE
    if _PROXY_CACHE is not None:
        return _PROXY_CACHE
    try:
        import json

        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                _PROXY_CACHE = url
                return url
    except (OSError, json.JSONDecodeError):
        pass
    _PROXY_CACHE = ""
    return None


def _is_proxy_alive(timeout: float = 3) -> bool:
    """检测服务端 ComfyUI 代理是否可用。"""
    proxy = _read_proxy_addr()
    if not proxy:
        return False
    try:
        r = http_get(f"{proxy}/comfyui/status", timeout=timeout)
        return r.status_code == 200 and r.json().get("online", False)
    except requests.exceptions.ConnectionError:
        log.warning(f"[ComfyUI] 服务端 {proxy} 连接失败")
        return False
    except requests.exceptions.Timeout:
        log.warning(f"[ComfyUI] 服务端 {proxy} 响应超时")
        return False
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return False


def is_alive(addr: str, timeout: float = 2) -> bool:
    addr = (addr or "").strip().rstrip("/")
    if not addr:
        return False
    try:
        r = http_get(f"{addr}/system_stats", timeout=timeout)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


class ComfyUILocal:
    _instance = None

    @classmethod
    def get(cls) -> "ComfyUILocal":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def is_present(self) -> bool:
        return os.path.isfile(COMFYUI_MAIN)

    def is_running(self, timeout: float = 2) -> bool:
        return is_alive(LOCAL_ADDR, timeout=timeout)

    def _embedded_python(self) -> str:
        return find_python()

    def start(self) -> tuple[bool, str]:
        if not self.is_present():
            return False, (f"未找到本地 ComfyUI（{COMFYUI_MAIN}）。\n"
                           "请将 ComfyUI 源码克隆到 apps/comfyui/ 目录：\n"
                           "git clone https://github.com/comfyanonymous/ComfyUI apps/comfyui")  # noqa: E501
        if self.is_running():
            return False, "本地 ComfyUI 已在运行"

        python = self._embedded_python()
        if not os.path.isfile(python):
            return False, f"未找到 Python 解释器: {python}"

        script = COMFYUI_RUNNER if os.path.isfile(COMFYUI_RUNNER) else COMFYUI_MAIN
        cmd = [python, script, "--listen", LOCAL_HOST, "--port", str(LOCAL_PORT),
               "--disable-auto-launch"]
        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(os.path.join(LOG_DIR, "comfyui.log"), "a", encoding="utf-8")  # noqa: SIM115

        with self._lock:
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=COMFYUI_DIR, stdout=logf, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW,
                )
                log.info(f"ComfyUI 进程已启动 PID={self._proc.pid}")
            except Exception as e:  # 外部API调用（subprocess）
                return False, f"启动失败: {e}"

        deadline = time.time() + 60
        while time.time() < deadline:
            if self.is_running():
                return True, "本地 ComfyUI 启动成功"
            time.sleep(1)
        return False, "ComfyUI 启动超时（60 秒）"

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                self._proc = None

            for img in ["python.exe", "pythonw.exe"]:
                with contextlib.suppress(Exception):
                    subprocess.call(
                        ["taskkill", "/F", "/IM", img, "/FI",
                         f"COMMANDLINE eq '*{COMFYUI_MAIN.replace('/', os.sep)}*'"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=_CREATE_NO_WINDOW, timeout=5,
                    )
            log.info("ComfyUI 进程已停止")


def resolve_addr(ai_config: dict, auto_start: bool = True, force_proxy: bool = False) -> str | None:  # noqa: E501
    """解析可用的 ComfyUI 后端地址。返回地址或 None。

    优先级：
    1. 服务端代理（/comfyui/...）
    2. 外部直连地址（comfyui_addr）
    3. 本地 ComfyUI（auto_start=True 时自动启动）
    """
    # 服务端代理优先
    if _is_proxy_alive():
        proxy = _read_proxy_addr()
        log.info(f"使用服务端 ComfyUI 代理: {proxy}")
        return proxy

    external = (ai_config or {}).get("comfyui_addr", "").strip().rstrip("/")

    if external and is_alive(external):
        log.info(f"使用外部 ComfyUI: {external}")
        return external

    if auto_start:
        local = ComfyUILocal.get()
        if local.is_present():
            if not local.is_running():
                log.info("尝试启动本地 ComfyUI…")
                ok, msg = local.start()
                if ok:
                    return LOCAL_ADDR
                log.warning(f"本地 ComfyUI 启动失败: {msg}")
            else:
                return LOCAL_ADDR

    if external:
        log.info(f"外部 ComfyUI 不可达，回退: {external}")
        return external
    return None


def _is_proxy_addr(addr: str) -> bool:
    """判断 addr 是否为服务端代理地址（非直连 ComfyUI）。"""
    return bool(addr) and addr != LOCAL_ADDR and addr != DEFAULT_EXTERNAL_ADDR


def _proxy_url(addr: str, path: str) -> str:
    return f"{addr.rstrip('/')}/comfyui/{path.lstrip('/')}"


def upload_file(ai_config, file_path):
    addr = resolve_addr(ai_config)
    if not addr:
        raise RuntimeError("ComfyUI 后端不可用")
    url = _proxy_url(addr, "upload/image") if _is_proxy_addr(addr) else f"{addr}/upload/image"
    with open(file_path, "rb") as f:
        resp = resilient_post(url, files={"image": f}, timeout=60, service="comfyui")
    resp.raise_for_status()
    return resp.json().get("name", os.path.basename(file_path))


def submit_prompt(ai_config, workflow_json):
    addr = resolve_addr(ai_config)
    if not addr:
        raise RuntimeError("ComfyUI 后端不可用")
    if _is_proxy_addr(addr):
        url = _proxy_url(addr, "run")
        payload = {"prompt": workflow_json}
    else:
        url = f"{addr}/prompt"
        payload = {"prompt": workflow_json}
    resp = resilient_post(url, json=payload, timeout=30, service="comfyui")
    resp.raise_for_status()
    return resp.json().get("prompt_id")


def get_queue(ai_config):
    """获取 ComfyUI 队列（支持代理）。"""
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return {"queue_running": [], "queue_pending": []}
    if _is_proxy_addr(addr):
        url = _proxy_url(addr, "queue")
    else:
        return None
    try:
        resp = resilient_get(url, timeout=10, service="comfyui", circuit_breaker=False)
        return resp.json() if resp.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        log.warning(f"[ComfyUI] 获取队列失败: {e}")
        return None


def get_history(ai_config, prompt_id=None):
    """获取 ComfyUI 执行历史。

    - prompt_id 指定时返回单个任务历史
    - prompt_id 为 None 且使用代理时返回全部历史列表
    """
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return None
    if _is_proxy_addr(addr):
        url = _proxy_url(addr, f"history/{prompt_id}") if prompt_id else _proxy_url(addr, "history")
    else:
        if prompt_id:
            url = f"{addr}/history/{prompt_id}"
        else:
            return None  # 直连 ComfyUI 不支持无参数查询全部历史
    resp = resilient_get(url, timeout=10, service="comfyui", circuit_breaker=False)
    if resp.status_code == 200:
        data = resp.json()
        if prompt_id:
            return data.get(prompt_id) if isinstance(data, dict) else data
        return data if isinstance(data, dict) else {}
    return None


def view_url(addr, filename, file_type="output", subfolder=""):
    addr = (addr or "").strip().rstrip("/")
    if _is_proxy_addr(addr):
        return _proxy_url(addr, f"view?filename={filename}&type={file_type}&subfolder={subfolder}")  # noqa: E501
    return f"{addr}/view?filename={filename}&type={file_type}&subfolder={subfolder}"


def system_stats(ai_config):
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return {}
    try:
        url = _proxy_url(addr, "status") if _is_proxy_addr(addr) else f"{addr}/system_stats"
        resp = resilient_get(url, timeout=5, service="comfyui", circuit_breaker=False)
        return resp.json() if resp.status_code == 200 else {}
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return {}


# ════════════════════════════════════════════════════════════════════════════
#  应用注册层（/apps 架构）— 对接 docs/comfyui-integration.md 第 4、6.1 节
#
#  实测约定（2026-07）：
#    · 应用发现/执行/状态查询 走服务端代理 8000：/apps、/apps/{id}/run、/apps/{id}/status/{id}
#    · 文件上传/下载走 ComfyUI 直连 8188：/upload/image（multipart field=image）、/view
#      （8000 代理的 /comfyui/upload/image 实测 422，故上传下载用直连地址）
# ════════════════════════════════════════════════════════════════════════════


def _comfyui_direct_addr(ai_config: dict) -> str | None:
    """解析 ComfyUI 直连地址（用于上传/下载）。

    优先级：服务端 status 返回里的 host → ai_config.comfyui_addr → 本地 8188。
    服务端 /comfyui/status 返回的 host 字段指向真实 ComfyUI 实例。
    """
    # 1. 优先从服务端 status 拿到真实 ComfyUI host
    proxy = _read_proxy_addr()
    if proxy:
        try:
            r = http_get(f"{proxy}/comfyui/status", timeout=5)
            if r.status_code == 200:
                host = (r.json().get("host") or "").strip().rstrip("/")
                if host and not host.startswith("http"):
                    host = f"http://{host}"
                if host and is_alive(host):
                    return host
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            pass
    # 2. 外部直连
    external = (ai_config or {}).get("comfyui_addr", "").strip().rstrip("/")
    if external and is_alive(external):
        return external
    # 3. 本地
    if is_alive(LOCAL_ADDR):
        return LOCAL_ADDR
    return None


class ComfyUIClient:
    """对接应用注册层（/apps）的客户端。

    addr = 服务端地址（默认从 ai_config.compute_server_url 解析），用于 /apps 发现与执行。
    上传/下载自动用 ComfyUI 直连地址（见 _comfyui_direct_addr）。
    """

    def __init__(self, server_addr: str = "", ai_config: dict | None = None):
        self.server_addr = (server_addr or _read_proxy_addr() or "").rstrip("/")
        self.ai_config = ai_config or {}

    # ── 地址 ──
    def _direct(self) -> str | None:
        """ComfyUI 直连地址（上传/下载用）。惰性解析并缓存。"""
        cached = getattr(self, "_direct_cache", None)
        if cached is None:
            self._direct_cache = _comfyui_direct_addr(self.ai_config)
        return self._direct_cache

    def _app_url(self, path: str) -> str:
        return f"{self.server_addr}/apps/{path.lstrip('/')}"

    # ── 健康检查 ──
    def is_alive(self) -> bool:
        if not self.server_addr:
            return False
        try:
            r = http_get(f"{self.server_addr}/apps", timeout=5)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ── 应用发现 ──
    def list_apps(self) -> list:
        """GET /apps — 已发布应用列表（摘要）。"""
        r = resilient_get(self._app_url(""), timeout=10, service="comfyui", circuit_breaker=False)  # noqa: E501
        if r.status_code == 200:
            return r.json().get("apps", [])
        raise RuntimeError(f"GET /apps 失败 HTTP {r.status_code}: {r.text[:200]}")

    def get_app(self, app_id: str) -> dict:
        """GET /apps/{app_id} — 应用详情（含完整 input/output schema）。"""
        r = resilient_get(self._app_url(app_id), timeout=10, service="comfyui", circuit_breaker=False)  # noqa: E501
        if r.status_code == 200:
            return r.json()
        raise RuntimeError(f"GET /apps/{app_id} 失败 HTTP {r.status_code}: {r.text[:200]}")  # noqa: E501

    # ── 文件上传/下载（走 ComfyUI 直连）──
    def upload_file(self, file_path: str, accept: str = "image") -> str:
        """上传文件到 ComfyUI input 目录，返回服务端文件名。

        实测 ComfyUI 原生 /upload/image 接受 multipart，field 名固定为 'image'
        （无论图片/音频/视频，ComfyUI 统一用 image 字段）。
        :param accept: image|audio|video（目前 ComfyUI 原生都用 'image' field）
        """
        addr = self._direct()
        if not addr:
            raise RuntimeError("无可用 ComfyUI 直连地址，无法上传文件。")
        url = f"{addr}/upload/image"
        with open(file_path, "rb") as f:
            resp = resilient_post(
                url, files={"image": (os.path.basename(file_path), f)},
                data={"type": "input", "subfolder": ""},
                timeout=120, service="comfyui",
            )
        if resp.status_code != 200:
            raise RuntimeError(f"上传失败 HTTP {resp.status_code}: {resp.text[:200]}")
        name = resp.json().get("name")
        if not name:
            raise RuntimeError(f"上传响应缺少 name 字段: {resp.text[:200]}")
        log.info(f"[ComfyUI] 上传成功: {file_path} → {name}")
        return name

    def download_output(self, filename: str, file_type: str = "output", subfolder: str = "") -> bytes:  # noqa: E501
        """下载生成的文件，返回二进制内容。"""
        addr = self._direct()
        if not addr:
            raise RuntimeError("无可用 ComfyUI 直连地址，无法下载文件。")
        url = view_url(addr, filename, file_type, subfolder)
        resp = http_get(url, timeout=120)
        resp.raise_for_status()
        return resp.content

    def output_url(self, filename: str, file_type: str = "output", subfolder: str = "") -> str:  # noqa: E501
        """返回生成文件的下载 URL（供浏览器/播放器直接访问）。"""
        addr = self._direct()
        if not addr:
            raise RuntimeError("无可用 ComfyUI 直连地址。")
        return view_url(addr, filename, file_type, subfolder)

    def submit_raw_prompt(self, workflow_json: dict) -> str:
        """直接提交原始 ComfyUI workflow（走 /comfyui/run 代理），返回 prompt_id。

        仅供"无对应 /apps 应用、需手动改节点后提交"的场景使用（如视频工具）。
        正常应用请优先用 run_app()。
        """
        if not self.server_addr:
            raise RuntimeError("无服务端地址，无法提交 workflow。")
        url = _proxy_url(self.server_addr, "run")
        resp = resilient_post(url, json={"prompt": workflow_json}, timeout=30, service="comfyui")  # noqa: E501
        if resp.status_code != 200:
            raise RuntimeError(f"提交 workflow 失败 HTTP {resp.status_code}: {resp.text[:200]}")  # noqa: E501
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"提交响应缺少 prompt_id: {resp.text[:200]}")
        return prompt_id

    # ── 应用执行 ──
    def run_app(self, app_id: str, params: dict) -> str:
        """POST /apps/{app_id}/run — 执行应用，返回 prompt_id。

        :param params: 应用参数（文件类参数需先 upload_file 拿到文件名再传入）。
        """
        url = self._app_url(f"{app_id}/run")
        resp = resilient_post(url, json={"params": params}, timeout=30, service="comfyui")  # noqa: E501
        if resp.status_code != 200:
            raise RuntimeError(f"执行应用 {app_id} 失败 HTTP {resp.status_code}: {resp.text[:200]}")  # noqa: E501
        data = resp.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"执行响应缺少 prompt_id: {data}")
        log.info(f"[ComfyUI] 应用 {app_id} 已提交, prompt_id={prompt_id}")
        return prompt_id

    def get_status(self, app_id: str, prompt_id: str) -> dict:
        """GET /apps/{app_id}/status/{prompt_id} — 查询执行状态。

        返回 {"status": "running|completed|failed", "progress"?, "outputs"?, "error"?}。
        """
        url = self._app_url(f"{app_id}/status/{prompt_id}")
        r = resilient_get(url, timeout=15, service="comfyui", circuit_breaker=False)
        if r.status_code == 200:
            return r.json()
        raise RuntimeError(f"查询状态失败 HTTP {r.status_code}: {r.text[:200]}")

    def wait_for_result(self, app_id: str, prompt_id: str,
                        interval: float = 3.0, timeout: float = 1800.0,
                        progress_cb=None) -> dict:
        """轮询直到执行完成（completed/failed），返回最终 status 响应。

        :param progress_cb: 可选回调 fn(status_dict) 用于上报进度。
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.get_status(app_id, prompt_id)
            st = last.get("status")
            if progress_cb:
                with contextlib.suppress(Exception):
                    progress_cb(last)
            if st == "completed" or st == "failed":
                return last
            time.sleep(interval)
        raise RuntimeError(f"等待应用 {app_id} 执行超时（{timeout}s），最后状态: {last}")


def get_client(ai_config: dict | None = None) -> ComfyUIClient:
    """工厂：根据 ai_config 创建 ComfyUIClient。"""
    return ComfyUIClient(server_addr=_read_proxy_addr() or "", ai_config=ai_config or {})  # noqa: E501


# ── 服务端代理模式快捷函数（供 GUI Worker 调用）──────────────────────────────

def list_workflows(server_url: str, timeout: int = 10) -> list:
    """GET /comfyui/workflows — 列出服务端可用工作流。"""
    url = f"{server_url.rstrip('/')}/comfyui/workflows"
    r = http_get(url, timeout=timeout)
    r.raise_for_status()
    return r.json().get("workflows", [])


def get_workflow_json(server_url: str, wf_path: str, timeout: int = 10) -> dict:
    """GET /comfyui/workflow?path=xx — 获取工作流 JSON 定义。"""
    url = f"{server_url.rstrip('/')}/comfyui/workflow"
    r = http_get(url, params={"path": wf_path}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_proxy_status(server_url: str, timeout: int = 5) -> dict:
    """GET /comfyui/status — 服务端 ComfyUI 代理状态。"""
    url = f"{server_url.rstrip('/')}/comfyui/status"
    r = http_get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def upload_image(server_url: str, image_path: str, timeout: int = 60):
    """POST /comfyui/upload/image — 上传产品图到服务端，返回文件名。"""
    url = f"{server_url.rstrip('/')}/comfyui/upload/image"
    with open(image_path, "rb") as f:
        resp = http_post(url, files={"image": f},
                         params={"overwrite": "true"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("name", os.path.basename(image_path)) or ""


def run_workflow(server_url: str, workflow: dict, client_id: str = "tintin-studio",
                 timeout: int = 30) -> str:
    """POST /comfyui/run — 提交工作流执行，返回 prompt_id。"""
    url = f"{server_url.rstrip('/')}/comfyui/run"
    resp = http_post(url, json={"prompt": workflow, "client_id": client_id}, timeout=timeout)  # noqa: E501
    resp.raise_for_status()
    result = resp.json()
    return result.get("prompt_id") or result.get("id") or ""


def get_history(server_url: str, prompt_id=None, timeout: int = 10):  # type: ignore[no-redef]  # noqa: E501 F811
    """GET /comfyui/history — 执行历史（代理模式）。

    prompt_id 指定时返回该任务的历史 dict；为 None 时返回全部历史。
    """
    url = f"{server_url.rstrip('/')}/comfyui/history"
    r = http_get(url, timeout=timeout)
    r.raise_for_status()
    hist = r.json()
    if prompt_id:
        return hist.get(prompt_id) if isinstance(hist, dict) else None
    return hist or {}


def download_image(server_url: str, filename: str, img_type: str = "output",
                   subfolder: str = "", timeout: int = 30) -> bytes:
    """GET /comfyui/view?filename=... — 下载生成的图片，返回二进制内容。"""
    url = (f"{server_url.rstrip('/')}/comfyui/view"
           f"?filename={filename}&type={img_type}&subfolder={subfolder}")
    r = http_get(url, timeout=timeout)
    r.raise_for_status()
    return r.content
