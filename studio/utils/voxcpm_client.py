import os
import base64
import configparser

from config.paths import PROJECT_ROOT


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
        raise RuntimeError(f"无法连接 VoxCPM 远程服务（{tts_url()}）。"
                           "请到『大模型配置』→『声音克隆』页检查 API 地址是否正确，并确认远程服务已启动。")
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
