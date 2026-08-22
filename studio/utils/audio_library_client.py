"""音频库服务端 API 客户端。

封装 /audio/* 和 /sfx/* 接口调用，GUI 层不直接拼 URL。
覆盖：BGM 库浏览/分类/上传、音效库、AI 音频生成(BGM+SFX)、卡点 BGM、口播管理。
"""
from __future__ import annotations

import json
import os

import requests

from utils.http_client import http_get, http_post
from utils.logger_utils import log


def _server_url() -> str:
    """读取 ai_config.json 中的统一服务端地址。"""
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return ""


# ── BGM 库 ──────────────────────────────────────────────────────────────
def bgm_list(page: int = 1, size: int = 50, tag: str = "",
             scene: str = "", mood: str = "", timeout: int = 15) -> dict | None:
    """GET /audio/library?type=bgm — BGM 库列表。"""
    base = _server_url()
    if not base:
        return None
    params: dict = {"type": "bgm", "page": page, "size": size}
    if tag:
        params["tag"] = tag
    if scene:
        params["scene"] = scene
    if mood:
        params["mood"] = mood
    try:
        r = http_get(f"{base}/audio/library", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] bgm_list → HTTP {r.status_code}: {r.text[:120]}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] bgm_list 失败: {e}")
    return None


def bgm_tags(timeout: int = 10) -> dict | None:
    """GET /audio/bgm/tags — 获取 BGM 标签体系（场景/情绪/风格）。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_get(f"{base}/audio/bgm/tags", timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] bgm_tags → HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] bgm_tags 失败: {e}")
    return None


def bgm_upload(file_path: str, tag: str = "", scene: str = "",
               mood: str = "", timeout: int = 60) -> dict | None:
    """POST /audio/bgm/upload — 上传 BGM 文件到音频库。"""
    base = _server_url()
    if not base:
        return None
    if not os.path.isfile(file_path):
        log.error(f"[audio_lib] bgm_upload 文件不存在: {file_path}")
        return None
    try:
        with open(file_path, "rb") as f:
            data = {"tag": tag, "scene": scene, "mood": mood}
            r = requests.post(
                f"{base}/audio/bgm/upload",
                files={"file": (os.path.basename(file_path), f)},
                data=data,
                timeout=timeout,
            )
        if r.status_code in (200, 201):
            return r.json()
        log.warning(f"[audio_lib] bgm_upload → HTTP {r.status_code}: {r.text[:120]}")
    except (requests.exceptions.RequestException, OSError) as e:
        log.error(f"[audio_lib] bgm_upload 失败: {e}")
    return None


def bgm_serve_url(audio_id: str) -> str:
    """构造音频流式播放 URL。"""
    base = _server_url()
    if not base:
        return ""
    return f"{base}/audio/library/serve?audio_id={audio_id}"


# ── 音效库 ──────────────────────────────────────────────────────────────
def sfx_list(category: str = "", tag: str = "", page: int = 1,
             size: int = 50, timeout: int = 15) -> dict | None:
    """GET /sfx/library — 音效库列表。"""
    base = _server_url()
    if not base:
        return None
    params: dict = {"page": page, "size": size}
    if category:
        params["category"] = category
    if tag:
        params["tag"] = tag
    try:
        r = http_get(f"{base}/sfx/library", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] sfx_list → HTTP {r.status_code}: {r.text[:120]}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] sfx_list 失败: {e}")
    return None


def sfx_analyze(file_path: str, timeout: int = 30) -> dict | None:
    """POST /sfx/analyze — 分析音效文件（PANNs 自动标注）。"""
    base = _server_url()
    if not base:
        return None
    if not os.path.isfile(file_path):
        log.error(f"[audio_lib] sfx_analyze 文件不存在: {file_path}")
        return None
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                f"{base}/sfx/analyze",
                files={"file": (os.path.basename(file_path), f)},
                timeout=timeout,
            )
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] sfx_analyze → HTTP {r.status_code}: {r.text[:120]}")
    except (requests.exceptions.RequestException, OSError) as e:
        log.error(f"[audio_lib] sfx_analyze 失败: {e}")
    return None


def sfx_serve_url(sfx_id: str) -> str:
    """构造音效流式播放 URL。"""
    base = _server_url()
    if not base:
        return ""
    return f"{base}/sfx/library/serve?sfx_id={sfx_id}"


# ── AI 音频生成 ──────────────────────────────────────────────────────────
def gen_bgm(prompt: str, style: str = "auto", duration: int = 30,
            timeout: int = 120) -> dict | None:
    """POST /audio/gen/bgm — MusicGen 生成 BGM。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_post(
            f"{base}/audio/gen/bgm",
            json={"prompt": prompt, "style": style, "duration": duration},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] gen_bgm → HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] gen_bgm 失败: {e}")
    return None


def gen_sfx(prompt: str, duration: int = 3,
            timeout: int = 60) -> dict | None:
    """POST /audio/gen/sfx — AudioLDM2 生成音效。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_post(
            f"{base}/audio/gen/sfx",
            json={"prompt": prompt, "duration": duration},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] gen_sfx → HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] gen_sfx 失败: {e}")
    return None


# ── 卡点 BGM ────────────────────────────────────────────────────────────
def get_beatmap(audio_id: str, timeout: int = 15) -> dict | None:
    """GET /audio/beatmap?audio_id=xxx — 获取音频卡点标记。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_get(f"{base}/audio/beatmap",
                     params={"audio_id": audio_id}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] get_beatmap → HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] get_beatmap 失败: {e}")
    return None


# ── 口播管理 ────────────────────────────────────────────────────────────
def voice_list(page: int = 1, size: int = 50, tag: str = "",
               timeout: int = 15) -> dict | None:
    """GET /audio/library?type=voice — 口播音频库列表。"""
    base = _server_url()
    if not base:
        return None
    params: dict = {"type": "voice", "page": page, "size": size}
    if tag:
        params["tag"] = tag
    try:
        r = http_get(f"{base}/audio/library", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[audio_lib] voice_list → HTTP {r.status_code}: {r.text[:120]}")
    except requests.exceptions.RequestException as e:
        log.error(f"[audio_lib] voice_list 失败: {e}")
    return None


def voice_upload(file_path: str, tag: str = "", voice_name: str = "",
                 timeout: int = 60) -> dict | None:
    """POST /audio/bgm/upload (type=voice) — 上传口播音频到库。"""
    base = _server_url()
    if not base:
        return None
    if not os.path.isfile(file_path):
        log.error(f"[audio_lib] voice_upload 文件不存在: {file_path}")
        return None
    try:
        with open(file_path, "rb") as f:
            data = {"tag": tag, "type": "voice", "voice_name": voice_name}
            r = requests.post(
                f"{base}/audio/bgm/upload",
                files={"file": (os.path.basename(file_path), f)},
                data=data,
                timeout=timeout,
            )
        if r.status_code in (200, 201):
            return r.json()
        log.warning(f"[audio_lib] voice_upload → HTTP {r.status_code}: {r.text[:120]}")
    except (requests.exceptions.RequestException, OSError) as e:
        log.error(f"[audio_lib] voice_upload 失败: {e}")
    return None