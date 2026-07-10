# -*- coding: utf-8 -*-
"""VoxCPM 远程客户端（纯远程模式）。

服务端接口：POST /voxcpm/tts
  Body: {"text": "...", "prompt_audio": "base64...", "speaker": "default"}
  Response: audio/wav bytes
"""
import os
import json
import base64
import requests

from utils.logger_utils import log


def _read_vox_url() -> str:
    """从 ai_config 读 vox_api_url。优先 vox_api_url，否则从 compute_server_url + /voxcpm/tts 派生。"""
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("vox_api_url") or "").strip()
            if not url:
                base = (cfg.get("compute_server_url") or "").strip()
                if base:
                    url = base.rstrip("/") + "/voxcpm/tts"
            return url
    except Exception:
        pass
    return ""


def tts_url() -> str:
    """当前 TTS 服务地址。"""
    url = _read_vox_url()
    return url or "http://127.0.0.1:8000/voxcpm/tts"


def is_running(timeout=2):
    """检测远程 VoxCPM 是否可用（发空文本探测）。"""
    try:
        requests.post(tts_url(), json={"text": ""}, timeout=timeout)
        return True
    except requests.exceptions.RequestException:
        return False


def synthesize_tts(text: str, ref_wav: str = "", out_path: str = "",
                   timeout: int = 600) -> str:
    """远程 TTS 合成，返回输出路径。

    服务端 API：POST /voxcpm/tts
      {"text": "...", "prompt_audio": "base64...", "speaker": "default"}
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("配音文案为空。")

    prompt_audio = None
    if ref_wav and os.path.isfile(ref_wav):
        with open(ref_wav, "rb") as f:
            prompt_audio = base64.b64encode(f.read()).decode()

    payload = {"text": text, "prompt_audio": prompt_audio, "speaker": "default"}

    try:
        r = requests.post(tts_url(), json=payload, timeout=timeout)
    except requests.exceptions.RequestException:
        raise RuntimeError(
            f"无法连接 VoxCPM 远程服务（{tts_url()}）。"
            "请到『大模型配置』→『声音克隆』页检查 API 地址是否正确，"
            "并确认远程服务已启动。"
        )

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
    log.info(f"[VoxCPM] TTS 合成完成: {out_path} ({len(r.content) // 1024}KB)")
    return out_path
