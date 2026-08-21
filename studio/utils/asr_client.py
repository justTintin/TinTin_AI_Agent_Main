# -*- coding: utf-8 -*-
"""远程 ASR（语音转写）客户端。

封装"提取音频 → 上传远程 Whisper 服务 → 拿回 segments → 格式化"全流程。
与 ollama/VoxCPM 的 remote 模式一致：服务端由外部部署，客户端只负责对接。
"""
import os
import json
import subprocess
import tempfile
from typing import Optional, Callable

from utils.logger_utils import log


# ═══════════════════════════════════════════════════════════════
#  配置读取
# ═══════════════════════════════════════════════════════════════

def _read_ai_config() -> dict:
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def read_asr_url() -> str:
    """远程 ASR 服务地址。优先 whisper_api_url，否则走统一服务端地址。"""
    cfg = _read_ai_config()
    url = (cfg.get("whisper_api_url") or "").strip()
    if not url:
        from utils.server_resolver import get_server_url
        try:
            url = get_server_url()
        except RuntimeError:
            pass
    return url


# ═══════════════════════════════════════════════════════════════
#  时间戳格式化
# ═══════════════════════════════════════════════════════════════

def format_srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ═══════════════════════════════════════════════════════════════
#  segments → 各格式转换
# ═══════════════════════════════════════════════════════════════

def segments_to_srt(segments: list) -> str:
    """segments → SRT 文本。"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_srt_timestamp(seg.get("start", 0))
        end = format_srt_timestamp(seg.get("end", 0))
        text = (seg.get("text") or "").strip()
        speaker = seg.get("speaker")
        if speaker:
            text = f"[{speaker}]: {text}"
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines).strip()


def segments_to_plain(segments: list) -> str:
    """segments → 纯文本（无时间戳）。"""
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        speaker = seg.get("speaker")
        if speaker:
            text = f"[{speaker}]: {text}"
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def segments_to_vtt(segments: list) -> str:
    """segments → WebVTT 文本。"""
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = format_vtt_timestamp(seg.get("start", 0))
        end = format_vtt_timestamp(seg.get("end", 0))
        text = (seg.get("text") or "").strip()
        speaker = seg.get("speaker")
        if speaker:
            text = f"[{speaker}]: {text}"
        lines.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(lines).strip()


# ═══════════════════════════════════════════════════════════════
#  音频提取 + 远程转写
# ═══════════════════════════════════════════════════════════════

def _extract_audio(video_path: str, ffmpeg_path: str) -> str:
    """用 ffmpeg 从视频提取 16k 单声道 wav 到临时文件，返回路径。"""
    tmp_wav = tempfile.mktemp(suffix=".wav")
    cmd = [
        ffmpeg_path, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        tmp_wav,
    ]
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="ignore",
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    if r.returncode != 0 or not os.path.isfile(tmp_wav):
        raise RuntimeError(f"音频提取失败:\n{r.stderr[:500] if r.stderr else ''}")
    return tmp_wav


def transcribe_remote(
    video_path: str,
    asr_url: str,
    language: str = "",
    task_type: str = "transcribe",
    diarize: bool = False,
    timeout: int = 600,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> list:
    """远程转写：提取音频 → POST 到远程 ASR 服务 → 返回 segments 列表。

    远程服务需接受 multipart/form-data：
        - audio: wav 文件
        - language: 语言代码（可选）
        - task_type: transcribe/translate
        - diarize: 是否说话人分离

    返回 [{"start": float, "end": float, "text": str, "speaker"?: str}, ...]

    异常时抛出 RuntimeError。
    """
    if not asr_url:
        raise RuntimeError("未配置远程 ASR 服务地址，请在系统设置中填写 Whisper API 地址。")

    from utils.platform_utils import find_ffmpeg
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
        raise RuntimeError("未检测到 ffmpeg，远程转写需要本地 ffmpeg 提取音频。")

    # 1. 提取音频
    tmp_wav = None
    try:
        if progress_cb:
            progress_cb("正在提取音频...")
        tmp_wav = _extract_audio(video_path, ffmpeg_path)
        log.info(f"[ASR] 音频提取完成: {tmp_wav} ({os.path.getsize(tmp_wav) // 1024}KB)")

        # 2. 确保模型已加载
        from utils.http_client import resilient_post
        base = asr_url.rstrip("/")
        if progress_cb:
            progress_cb("正在加载 Whisper 模型...")
        try:
            ensure_url = f"{base}/models/ensure/whisper"
            log.info(f"[ASR] 确保模型加载: {ensure_url}")
            er = resilient_post(ensure_url, timeout=60, service="whisper", circuit_breaker=False)
            log.info(f"[ASR] 模型加载状态: HTTP {er.status_code}")
        except Exception as e:
            log.warning(f"[ASR] 确保模型加载失败(继续尝试转写): {e}")

        # 3. POST 到远程
        url = f"{base}/whisper/transcribe"

        if progress_cb:
            progress_cb("正在上传音频到服务端...")

        with open(tmp_wav, "rb") as f:
            files = {"file": (os.path.basename(tmp_wav), f, "audio/wav")}
            data = {"fmt": "json"}
            if language:
                data["language"] = language
            if task_type:
                data["task_type"] = task_type
            if diarize:
                data["diarize"] = "true"

            log.info(f"[ASR] 上传到远程: {url} (文件大小: {os.path.getsize(tmp_wav)//1024}KB)")
            if progress_cb:
                progress_cb("正在等待服务端处理...")
            resp = resilient_post(url, files=files, data=data, timeout=timeout, service="whisper")
            log.info(f"[ASR] 服务端返回 HTTP {resp.status_code}, 耗时 {resp.elapsed.total_seconds():.1f}s")

        if resp.status_code != 200:
            log.error(f"[ASR] 服务端返回错误 HTTP {resp.status_code}: {resp.text[:300]}")
            raise RuntimeError(f"远程 ASR 返回 HTTP {resp.status_code}: {resp.text[:200]}")

        result = resp.json()
        segments = result.get("segments") or result.get("result", {}).get("segments") or []
        if not segments:
            # 某些实现可能直接返回 {"text": "..."} 无 segments
            if result.get("text"):
                segments = [{"start": 0, "end": 0, "text": result["text"]}]

        log.info(f"[ASR] 远程转写完成，{len(segments)} 段")
        return segments

    finally:
        if tmp_wav and os.path.isfile(tmp_wav):
            try:
                os.remove(tmp_wav)
            except Exception:
                pass
