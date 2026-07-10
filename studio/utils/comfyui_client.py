import os
import sys
import time
import threading
import subprocess

import requests

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


def resolve_addr(ai_config: dict, auto_start: bool = True) -> str | None:
    """解析可用的 ComfyUI 后端地址。返回地址或 None。"""
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


def upload_file(ai_config, file_path):
    addr = resolve_addr(ai_config)
    if not addr:
        raise RuntimeError("ComfyUI 后端不可用")
    with open(file_path, "rb") as f:
        resp = requests.post(f"{addr}/upload/image", files={"image": f}, timeout=60)
    resp.raise_for_status()
    return resp.json().get("name", os.path.basename(file_path))


def submit_prompt(ai_config, workflow_json):
    addr = resolve_addr(ai_config)
    if not addr:
        raise RuntimeError("ComfyUI 后端不可用")
    resp = requests.post(f"{addr}/prompt", json={"prompt": workflow_json}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("prompt_id")


def get_history(ai_config, prompt_id):
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return None
    resp = requests.get(f"{addr}/history/{prompt_id}", timeout=10)
    if resp.status_code == 200:
        return resp.json().get(prompt_id)
    return None


def view_url(addr, filename, file_type="output", subfolder=""):
    addr = (addr or "").strip().rstrip("/")
    return f"{addr}/view?filename={filename}&type={file_type}&subfolder={subfolder}"


def system_stats(ai_config):
    addr = resolve_addr(ai_config, auto_start=False)
    if not addr:
        return {}
    try:
        resp = requests.get(f"{addr}/system_stats", timeout=5)
        return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {}
