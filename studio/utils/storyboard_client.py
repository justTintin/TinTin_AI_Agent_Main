# -*- coding: utf-8 -*-
"""分镜脚本服务端客户端封装（双路径兼容）。

命名规范（docs/NAMING-CONVENTIONS.md）：
  API 前缀统一不带 /api —— 新路径 /storyboard/scripts；
  历史遗留 /api/storyboard/scripts 逐步迁移。
因此这里所有请求先试新路径，404 时回退旧路径，保证两端都能取到数据。
"""
from utils.http_client import http_get, http_post
from utils.logger_utils import log


def _server_url():
    try:
        import json
        from config.paths import AI_CONFIG_FILE
        import os
        if os.path.isfile(AI_CONFIG_FILE):
            cfg = json.load(open(AI_CONFIG_FILE, "r", encoding="utf-8"))
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _script_urls(base, suffix=""):
    """返回候选 URL：新规范（不带 /api）优先，历史 /api 路径回退。"""
    base = (base or "").rstrip("/")
    return [
        f"{base}/storyboard/scripts{suffix}",
        f"{base}/api/storyboard/scripts{suffix}",
    ]


def list_scripts(page=1, page_size=100, timeout=15):
    """GET 分镜脚本列表 → [{id, topic, ratio, shot_count, saved_at}]。

    服务端正常但无脚本时返回 []；配置缺失/网络失败/接口不存在时抛异常，
    由调用方走 error 分支展示原因。
    """
    base = _server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址")
    last_err = None
    for url in _script_urls(base):
        try:
            r = http_get(url, params={"page": page, "page_size": page_size}, timeout=timeout)
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
            if r.status_code != 404:
                raise RuntimeError(f"脚本列表接口返回 HTTP {r.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            log.warning(f"[分镜脚本] 列表请求失败({url}): {e}")
    if last_err:
        raise RuntimeError(f"无法连接服务端获取脚本列表: {last_err}")
    raise RuntimeError("脚本列表接口不存在（HTTP 404），请确认服务端已实现 /storyboard/scripts")


def get_script(script_id, timeout=15):
    """GET 分镜脚本详情 → dict；失败抛异常。"""
    base = _server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址")
    last_err = None
    for url in _script_urls(base, f"/{script_id}"):
        try:
            r = http_get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json() or {}
            if r.status_code != 404:
                raise RuntimeError(f"脚本详情接口返回 HTTP {r.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            log.warning(f"[分镜脚本] 详情请求失败({url}): {e}")
    if last_err:
        raise RuntimeError(f"无法连接服务端获取脚本详情: {last_err}")
    raise RuntimeError("脚本详情接口不存在（HTTP 404），请确认服务端已实现 /storyboard/scripts/{id}")


def save_script(payload, timeout=20):
    """POST 保存分镜脚本 → True/False。同 topic 覆盖更新。"""
    base = _server_url()
    if not base:
        log.warning("[分镜脚本] 未配置服务端地址，跳过上传")
        return False
    last_err = None
    for url in _script_urls(base):
        try:
            r = http_post(url, json=payload, timeout=timeout)
            if r.status_code in (200, 201):
                return True
            if r.status_code != 404:
                log.warning(f"[分镜脚本] 保存接口 HTTP {r.status_code}: {r.text[:150]}")
                return False
        except Exception as e:
            last_err = e
            log.warning(f"[分镜脚本] 保存请求失败({url}): {e}")
    if last_err:
        log.warning(f"[分镜脚本] 保存接口全部失败: {last_err}")
    return False
