"""分镜脚本服务端客户端封装。

服务端接口路径：/api/storyboard/scripts（与 OpenAPI 对齐）。
"""
import requests

from utils.http_client import http_get, http_post
from utils.logger_utils import log


def _server_url():
    try:
        import json
        import os

        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as _f:
                cfg = json.load(_f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def _script_url(base, suffix=""):
    """构造 /api/storyboard/scripts 路径。"""
    base = (base or "").rstrip("/")
    return f"{base}/api/storyboard/scripts{suffix}"


def list_scripts(page=1, page_size=100, timeout=15):
    """GET 分镜脚本列表 → [{id, topic, ratio, shot_count, saved_at}]。"""
    base = _server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址")
    url = _script_url(base)
    try:
        r = http_get(url, params={"page": page, "page_size": page_size}, timeout=timeout)  # noqa: E501
        if r.status_code == 200:
            data = r.json()
            # 兼容 {items:[...]} / {data:[...]} / 裸数组 三种返回结构
            if isinstance(data, list):
                return data
            data = data or {}
            items = data.get("items")
            if items is None:
                items = data.get("data")
            if isinstance(items, list):
                return items
            log.warning(f"[分镜脚本] 列表响应结构异常: {str(data)[:200]}")
            return []
        raise RuntimeError(f"脚本列表接口返回 HTTP {r.status_code}")
    except RuntimeError:
        raise
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"无法连接服务端获取脚本列表: {e}") from e


def get_script(script_id, timeout=15):
    """GET 分镜脚本详情 → dict；失败抛异常。"""
    base = _server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址")
    url = _script_url(base, f"/{script_id}")
    try:
        r = http_get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json() or {}
        raise RuntimeError(f"脚本详情接口返回 HTTP {r.status_code}")
    except RuntimeError:
        raise
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"无法连接服务端获取脚本详情: {e}") from e


def save_script(payload, timeout=20):
    """POST 保存分镜脚本 → True/False。同 topic 覆盖更新。"""
    base = _server_url()
    if not base:
        log.warning("[分镜脚本] 未配置服务端地址，跳过上传")
        return False
    url = _script_url(base)
    try:
        r = http_post(url, json=payload, timeout=timeout)
        if r.status_code in (200, 201):
            return True
        log.warning(f"[分镜脚本] 保存接口 HTTP {r.status_code}: {r.text[:150]}")
        return False
    except requests.exceptions.RequestException as e:
        log.warning(f"[分镜脚本] 保存请求失败({url}): {e}")
        return False
