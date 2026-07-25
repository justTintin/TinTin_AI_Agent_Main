import os
import sys
import time
import threading
import subprocess

import requests
from utils.http_client import resilient_get, resilient_post

from config.paths import APPS_DIR, PYTHON_EMBEDED_DIR, LOG_DIR
from utils.logger_utils import log
from utils.platform_utils import find_python, create_no_window_flag

COMFYUI_DIR = os.path.join(APPS_DIR, "comfyui")
COMFYUI_MAIN = os.path.join(COMFYUI_DIR, "main.py")
COMFYUI_RUNNER = os.path.join(COMFYUI_DIR, "_run_local.py")

LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 8188
LOCAL_ADDR = f"http://{LOCAL_HOST}:{LOCAL_PORT}"

DEFAULT_EXTERNAL_ADDR = "http://192.168.111.36:8188"

_CREATE_NO_WINDOW = create_no_window_flag()

_PROXY_CACHE = None


def _read_proxy_addr() -> str | None:
    """从 ai_config 读取 compute_server_url（服务端代理地址）。"""
    global _PROXY_CACHE
    if _PROXY_CACHE is not None:
        return _PROXY_CACHE
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                _PROXY_CACHE = url
                return url
    except Exception:
        pass
    _PROXY_CACHE = ""
    return None


def _is_proxy_alive(timeout: float = 3) -> bool:
    """检测服务端 ComfyUI 代理是否可用。"""
    proxy = _read_proxy_addr()
    if not proxy:
        return False
    try:
        r = requests.get(f"{proxy}/comfyui/status", timeout=timeout)
        return r.status_code == 200 and r.json().get("online", False)
    except requests.exceptions.ConnectionError:
        log.warning(f"[ComfyUI] 服务端 {proxy} 连接失败")
        return False
    except requests.exceptions.Timeout:
        log.warning(f"[ComfyUI] 服务端 {proxy} 响应超时")
        return False
    except Exception:
        return False


def is_alive(addr: str, timeout: float = 2) -> bool:
    addr = (addr or "").strip().rstrip("/")
    if not addr:
        return False
    try:
        r = requests.get(f"{addr}/system_stats", timeout=timeout)
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
                           "git clone https://github.com/comfyanonymous/ComfyUI apps/comfyui")
        if self.is_running():
            return False, "本地 ComfyUI 已在运行"

        python = self._embedded_python()
        if not os.path.isfile(python):
            return False, f"未找到 Python 解释器: {python}"

        script = COMFYUI_RUNNER if os.path.isfile(COMFYUI_RUNNER) else COMFYUI_MAIN
        cmd = [python, script, "--listen", LOCAL_HOST, "--port", str(LOCAL_PORT),
               "--disable-auto-launch"]
        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(os.path.join(LOG_DIR, "comfyui.log"), "a", encoding="utf-8")

        with self._lock:
            try:
                self._proc = subprocess.Popen(
                    cmd, cwd=COMFYUI_DIR, stdout=logf, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW,
                )
                log.info(f"ComfyUI 进程已启动 PID={self._proc.pid}")
            except Exception as e:
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
                try:
                    subprocess.call(
                        ["taskkill", "/F", "/IM", img, "/FI",
                         f"COMMANDLINE eq '*{COMFYUI_MAIN.replace('/', os.sep)}*'"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=_CREATE_NO_WINDOW, timeout=5,
                    )
                except Exception:
                    pass
            log.info("ComfyUI 进程已停止")


def resolve_addr(ai_config: dict, auto_start: bool = True, force_proxy: bool = False) -> str | None:
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
    return addr and addr != LOCAL_ADDR and addr != DEFAULT_EXTERNAL_ADDR


def _proxy_url(addr: str, path: str) -> str:
    return f"{addr.rstrip('/')}/comfyui/{path.lstrip('/')}"


def upload_file(ai_config, file_path):
    addr = resolve_addr(ai_config)
    if not addr:
        raise RuntimeError("ComfyUI 后端不可用")
    if _is_proxy_addr(addr):
        url = _proxy_url(addr, "upload/image")
    else:
        url = f"{addr}/upload/image"
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
        if prompt_id:
            url = _proxy_url(addr, f"history/{prompt_id}")
        else:
            url = _proxy_url(addr, "history")
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
        return _proxy_url(addr, f"view?filename={filename}&type={file_type}&subfolder={subfolder}")
    return f"{addr}/view?filename={filename}&type={file_type}&subfolder={subfolder}"


def system_stats(ai_config):
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return {}
    try:
        if _is_proxy_addr(addr):
            url = _proxy_url(addr, "status")
        else:
            url = f"{addr}/system_stats"
        resp = resilient_get(url, timeout=5, service="comfyui", circuit_breaker=False)
        return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}
