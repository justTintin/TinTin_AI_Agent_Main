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
from utils.http_client import resilient_post, http_post

from utils.logger_utils import log
from utils.api_error import ApiError


def repair_wav_bytes(wav_bytes: bytes) -> bytes:
    """修复 WAV RIFF/data 头：若声明的 data 长度小于实际音频字节，播放器会提前停止（尾部裁断）。
    仅在头部错误时重写 data 大小与 RIFF 大小；正常时原样返回。
    """
    try:
        if not wav_bytes or len(wav_bytes) < 12:
            return wav_bytes
        if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            return wav_bytes
        pos = 12
        while pos + 8 <= len(wav_bytes):
            cid = wav_bytes[pos:pos + 4]
            size = int.from_bytes(wav_bytes[pos + 4:pos + 8], "little")
            if cid == b"data":
                declared = size
                actual = len(wav_bytes) - (pos + 8)
                if actual > declared:
                    out = bytearray(wav_bytes)
                    out[pos + 4:pos + 8] = actual.to_bytes(4, "little")
                    out[4:8] = (len(out) - 8).to_bytes(4, "little")
                    log.info(f"[VoxCPM] WAV data 头修复 {declared} -> {actual}")
                    return bytes(out)
                return wav_bytes
            pos += 8 + size + (size & 1)
    except Exception as e:
        log.warning(f"WAV 头修复异常: {e}")
    return wav_bytes


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
        http_post(tts_url(), json={"text": ""}, timeout=timeout)
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
    url = tts_url()
    log.info(f"[VoxCPM] 请求 TTS: {url} text_len={len(text)}")

    try:
        r = resilient_post(url, json=payload, timeout=timeout, service="voxcpm")
        log.info(f"[VoxCPM] 响应 HTTP {r.status_code} ({len(r.content)//1024}KB)")
    except ApiError:
        raise  # resilient_post 已封装为 ApiError（含 URL+参数），直接透传
    except requests.exceptions.RequestException as e:
        log.error(f"[VoxCPM] 连接失败: {url}")
        raise ApiError(url, method="POST", params=payload, cause=e, service="voxcpm")

    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error", "")
        except Exception:
            pass
        raise ApiError(url, method="POST", params=payload,
                       status_code=r.status_code,
                       response_text=msg or r.text, service="voxcpm")

    data = repair_wav_bytes(r.content)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    log.info(f"[VoxCPM] TTS 合成完成: {out_path} ({len(data) // 1024}KB)")
    return out_path
