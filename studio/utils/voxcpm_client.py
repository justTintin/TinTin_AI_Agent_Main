import os
import sys
import time
import base64
import subprocess
import configparser

from config.paths import PROJECT_ROOT, WORKSPACE_ROOT, VOXCPM2_DIR
from utils.platform_utils import find_venv_python, create_no_window_flag

_proc = None


def tts_port():
    port = 7861
    cfg_path = os.path.join(PROJECT_ROOT, "config.ini")
    try:
        if os.path.isfile(cfg_path):
            cfg = configparser.ConfigParser()
            cfg.read(cfg_path, encoding="utf-8")
            if cfg.has_section("VoxCPM"):
                port = cfg.getint("VoxCPM", "Port", fallback=7861)
    except Exception:
        pass
    return port


def tts_url():
    return f"http://127.0.0.1:{tts_port()}/v1/tts"


def is_running(timeout=2):
    import requests
    try:
        requests.post(tts_url(), json={"text": ""}, timeout=timeout)
        return True
    except requests.exceptions.RequestException:
        return False


def _voxcpm_python():
    return find_venv_python(VOXCPM2_DIR)


def _checkpoint():
    cfg_path = os.path.join(PROJECT_ROOT, "config.ini")
    try:
        if os.path.isfile(cfg_path):
            cfg = configparser.ConfigParser()
            cfg.read(cfg_path, encoding="utf-8")
            mp = cfg.get("VoxCPM", "ModelPath", fallback="").strip()
            if mp:
                if not os.path.isabs(mp):
                    mp = os.path.join(WORKSPACE_ROOT, mp)
                if os.path.isdir(mp):
                    return os.path.abspath(mp)
    except Exception:
        pass

    from config.paths import VOXCPM2_DIR
    default_path = os.path.join(VOXCPM2_DIR, "models", "openbmb__VoxCPM2")
    if os.path.isdir(default_path):
        return os.path.abspath(default_path)
    return "openbmb/VoxCPM2"


def start_server():
    if is_running():
        return False, "服务已在运行"
    script = os.path.join(WORKSPACE_ROOT, "studio", "voxcpm_api_server.py")
    if not os.path.isfile(script):
        raise RuntimeError("找不到 voxcpm_api_server.py。")
    cmd = [_voxcpm_python(), script, "--listen", f"127.0.0.1:{tts_port()}",
           "--checkpoint-path", _checkpoint()]
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logf = open(os.path.join(log_dir, "voxcpm_api.log"), "a", encoding="utf-8")
    flags = create_no_window_flag()
    global _proc
    _proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT, creationflags=flags)
    return True, "已启动，正在加载模型…"


def stop_server():
    global _proc
    stopped = False
    try:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
            stopped = True
    except Exception:
        pass
    _proc = None
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*voxcpm_api_server.py*' } "
             "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            creationflags=create_no_window_flag(), timeout=10, capture_output=True)
        stopped = True
    except Exception:
        pass
    return stopped, "已停止" if stopped else "未发现运行中的服务"


def ensure_running(wait=300, on_phase=None):
    if is_running():
        return True
    start_server()
    deadline = time.time() + wait
    while time.time() < deadline:
        if on_phase:
            on_phase("正在启动 VoxCPM 服务并加载模型，请稍候…")
        time.sleep(3)
        if is_running():
            return True
    return False


def synthesize_tts(text, ref_wav, out_path, timeout=600):
    import requests
    text = (text or "").strip()
    if not text:
        raise RuntimeError("配音文案为空。")
    payload = {"text": text, "normalize": True}
    if ref_wav and os.path.isfile(ref_wav):
        with open(ref_wav, "rb") as f:
            payload["references"] = [{"audio": base64.b64encode(f.read()).decode()}]
    try:
        r = requests.post(tts_url(), json=payload, timeout=timeout)
    except requests.exceptions.RequestException:
        raise RuntimeError(f"无法连接 VoxCPM 本地服务（{tts_url()}）。"
                           "请先到『声音克隆』页启动本地 API 服务后再试。")
    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except Exception:
            pass
        raise RuntimeError(f"TTS 失败（HTTP {r.status_code}）：{msg or r.text[:200]}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path
