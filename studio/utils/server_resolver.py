# -*- coding: utf-8 -*-
"""算力服务端地址解析 — 统一读取 + 缓存。

蓝绿发布由 nginx 反向代理实现，客户端只需连接 nginx 地址，
nginx 内部自动路由到 blue(:8000) 或 green(:8001)，对客户端透明。

本模块提供统一的地址读取入口，避免各模块重复解析 ai_config.json。
带 30 秒缓存，减少磁盘 IO。

用法：
    from utils.server_resolver import get_server_url
    url = get_server_url()   # 返回 http://host:port

    # 带参数覆盖（函数调用时指定地址）
    url = get_server_url(explicit="http://192.168.111.30:80")

    # 强制刷新缓存（配置被 UI 修改后调用）
    from utils.server_resolver import invalidate_cache
    invalidate_cache()
"""
import os
import time
import threading

from utils.logger_utils import log

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_CACHE_TTL = 30.0  # 缓存有效期（秒）

_lock = threading.Lock()
_cached_url: str = ""
_cached_at: float = 0.0


def _read_configured_url() -> str:
    """从 ai_config.json 读取 compute_server_url。"""
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def get_server_url(explicit: str = "") -> str:
    """获取算力服务端地址。

    蓝绿发布由 nginx 代理，客户端连接的地址就是 nginx 地址，
    nginx 内部自动切流到 blue/green，客户端无需感知端口变化。

    Args:
        explicit: 如果提供了显式地址，直接返回（不读配置、不走缓存）。
                  用于函数参数覆盖场景。

    Returns:
        服务端地址（如 http://192.168.111.30）

    Raises:
        RuntimeError: 未配置服务端地址
    """
    if explicit:
        return explicit.strip().rstrip("/")

    global _cached_url, _cached_at

    # 检查缓存是否有效
    now = time.time()
    with _lock:
        if _cached_url and (now - _cached_at) < _CACHE_TTL:
            return _cached_url

    # 缓存失效，重新读取配置
    url = _read_configured_url()
    if not url:
        raise RuntimeError(
            "未配置算力服务端地址（compute_server_url），请在系统设置中填写。"
        )

    with _lock:
        _cached_url = url
        _cached_at = now

    return url


def invalidate_cache():
    """清除缓存，下次 get_server_url() 会重新读取配置。

    在 UI 修改了配置并保存后调用。
    """
    global _cached_url, _cached_at
    with _lock:
        _cached_url = ""
        _cached_at = 0.0
    log.debug("[ServerResolver] 缓存已清除")


def peek_configured_url() -> str:
    """读取 ai_config.json 中的原始配置值（不走缓存）。

    用于 UI 显示当前配置的服务端地址。
    """
    return _read_configured_url()
