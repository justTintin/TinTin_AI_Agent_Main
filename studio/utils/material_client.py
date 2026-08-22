"""素材库服务端 API 客户端。

封装所有 /material/* 接口调用，GUI 层不直接拼 URL。
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


def search(params: dict, timeout: int = 20) -> dict | None:
    """POST /material/search — 语义检索素材。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_post(f"{base}/material/search", json=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[material] search → HTTP {r.status_code}")
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] search 失败: {e}")
    return None


def list(params: dict, timeout: int = 20):  # type: ignore[no-redef]
    """GET /material/list — 浏览素材列表（page/size 分页）。返回 dict | list | None。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_get(f"{base}/material/list", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[material] list → HTTP {r.status_code}")
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] list 失败: {e}")
    return None


def serve_url(material_id: str) -> str:
    """构造 /material/serve 流式播放 URL。"""
    base = _server_url()
    if not base:
        return ""
    return f"{base}/material/serve?material_id={material_id}"


def thumbnail_url(material_id: str) -> str:
    """构造 /material/thumbnail 缩略图 URL。"""
    base = _server_url()
    if not base:
        return ""
    return f"{base}/material/thumbnail?material_id={material_id}"


def stats(group: str = "", timeout: int = 10) -> dict | None:
    """GET /material/stats — 素材库统计；group='source' 时按来源分组统计。"""
    base = _server_url()
    if not base:
        return None
    try:
        params = {}
        if group:
            params["group"] = group
        r = http_get(f"{base}/material/stats", params=params or None, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] stats 失败: {e}")
    return None


def distinct(field: str, timeout: int = 15):
    """GET /material/distinct?field=xxx — 去重字段值列表。返回 list。"""
    base = _server_url()
    if not base:
        return []
    try:
        r = http_get(f"{base}/material/distinct", params={"field": field}, timeout=timeout)  # noqa: E501
        if r.status_code == 200:
            return r.json() or []
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] distinct 失败: {e}")
    return []


def stock_search(query: str, kind: str = "image", timeout: int = 20) -> dict | None:
    """POST /material/stock_search — 联网素材搜索（Pexels/Pixabay）。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_post(
            f"{base}/material/stock_search",
            json={"query": query, "kind": kind, "page": 1, "per": 10},
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()
        log.warning(f"[material] stock_search → HTTP {r.status_code}")
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] stock_search 失败: {e}")
    return None


def status(timeout: int = 5, quiet: bool = False) -> dict | None:
    """GET /material/status — 服务状态探测。"""
    base = _server_url()
    if not base:
        return None
    try:
        r = http_get(f"{base}/material/status", timeout=timeout, quiet=quiet)
        if r.status_code == 200:
            return r.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        if not quiet:
            log.error(f"[material] status 失败: {e}")
    return None


def import_plugin(plugin_id: str | None = None, url: str | None = None,
                  category: str = "", tags: list | None = None,
                  timeout: int = 120) -> dict | None:
    """POST /material/import_plugin — 插件素材下载入库。

    返回 {"ok": True, "material_id": ...} 或 {"ok": False, "error": ...}。
    """
    base = _server_url()
    if not base:
        return None
    try:
        payload = {}
        if plugin_id:
            payload["plugin_id"] = plugin_id
        if url:
            payload["url"] = url
        if category:
            payload["category"] = category
        if tags:
            payload["tags"] = list(tags)
        r = http_post(f"{base}/material/import_plugin", json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[material] import_plugin → HTTP {r.status_code}: {r.text[:120]}")
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:120]}"}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[material] import_plugin 失败: {e}")
        return {"ok": False, "error": str(e)}


def list_by_source(source: str, params: dict | None = None, timeout: int = 20):
    """GET /material/list?source=xxx — 按来源筛选素材列表。"""
    p = dict(params or {})
    p["source"] = source
    return list(p, timeout=timeout)


def source_stats(timeout: int = 10) -> dict | None:
    """GET /material/stats?group=source — 按来源分组统计。"""
    return stats(group="source", timeout=timeout)
