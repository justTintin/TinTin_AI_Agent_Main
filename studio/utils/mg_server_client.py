# -*- coding: utf-8 -*-
"""MG 动画服务端客户端（按 OpenAPI /mg/* 实现）。

当前服务端 /mg/* 仅暴露：
  GET /mg/templates          可用模板列表（含参数说明）
  POST /mg/generate           提交渲染任务
  GET /mg/status/{task_id}    查询进度
  GET /mg/result/{task_id}    下载成片

注意：服务端 MGRequest schema 未声明 specs/bars 等额外字段，也没有
/mg/preview、/mg/analyze-video、/mg/templates/{id} 等端点。调用这些
端点会 404/422。如需支持 mg_benchmark 等模板，请先让服务端在
MGRequest schema 中新增对应字段（或开启 additionalProperties）。
"""
import os
from datetime import datetime

from utils.http_client import http_get, http_post
from utils.logger_utils import log


def _server_url():
    """读取 compute_server_url（与 scheduled_task_client 一致）。"""
    try:
        import json
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            cfg = json.load(open(AI_CONFIG_FILE, "r", encoding="utf-8"))
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _ensure_url(url):
    """如果传入相对路径，补全服务端前缀。"""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    server = _server_url()
    if not server:
        raise RuntimeError("未配置 compute_server_url，且返回的 output_url 不是完整 URL")
    return f"{server}{url if url.startswith('/') else '/' + url}"


def _safe_json(resp):
    """尝试解析响应 JSON，失败返回 {} 并记录。"""
    try:
        return resp.json()
    except Exception as e:
        log.warning(f"[MG] JSON parse failed: {e}")
        return {}


def list_templates(timeout=10):
    """GET /mg/templates，返回可用模板列表（list[dict]）。失败返回 []。"""
    url = _server_url()
    if not url:
        return []
    try:
        r = http_get(f"{url}/mg/templates", timeout=timeout)
        if r.status_code == 200:
            data = _safe_json(r)
            if isinstance(data, list):
                return data
            return data.get("items") or data.get("data") or data.get("templates") or []
    except Exception as e:
        log.warning(f"[MG] list_templates failed: {e}")
    return []


def submit_mg_task(request: dict, timeout=15):
    """提交 MG 渲染任务。返回 task_id（str），失败返回 None。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url，请先在系统设置中填写服务端地址")
    if not isinstance(request, dict):
        raise TypeError("MG request 必须是 dict")
    try:
        r = http_post(f"{url}/mg/generate", json=request, timeout=timeout)
        if r.status_code == 200:
            data = _safe_json(r)
            task_id = data.get("id") or data.get("task_id")
            log.info(f"[MG] submit task_id={task_id}, template={request.get('template')}")
            return task_id
        log.warning(f"[MG] submit HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"[MG] submit failed: {e}")
    return None


def get_mg_status(task_id, timeout=10):
    """查询 MG 渲染任务状态。返回 dict，失败返回 None。"""
    url = _server_url()
    if not url:
        return None
    try:
        r = http_get(f"{url}/mg/status/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
        log.warning(f"[MG] status HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"[MG] status failed: {e}")
    return None


def download_mg_result(task_id, local_path, timeout=120):
    """通过 GET /mg/result/{task_id} 下载渲染完成的 MG 视频到本地。返回 local_path。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url，无法下载 MG 结果")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    full = f"{url}/mg/result/{task_id}"
    import requests as _requests
    r = _requests.get(full, stream=True, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"下载 MG 结果失败 HTTP {r.status_code}: {r.text[:200]}")
    with open(local_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return local_path


def make_mg_request(
    template="mg_scene",
    ratio="9:16",
    scale=1,
    title="",
    subtitle="",
    text="",
    subtext="",
    quote="",
    author="",
    color="#FFFFFF",
    bg="",
    font_size=96,
    duration=3,
    scenes=None,
    width=None,
    height=None,
    start=None,
    end=None,
    **kwargs,
):
    """构造一个标准的 MGRequest 字典。服务端模板与字段对应：
    mg_scene -> scenes[]; mg_intro -> title/subtitle;
    mg_outro -> text/subtext; mg_countdown -> start/end/title;
    mg_quote -> quote/author。

    mg_benchmark 需要服务端在 MGRequest 中新增 specs/bars 字段（或开启
    additionalProperties）后才能使用；当前 schema 会拒绝这些额外字段。
    额外参数通过 kwargs 传入（如 specs、bars），但需确认服务端已支持。
    """
    req = {
        "template": template,
        "ratio": ratio,
        "scale": scale,
        "title": title,
        "subtitle": subtitle,
        "text": text,
        "subtext": subtext,
        "quote": quote,
        "author": author,
        "color": color,
        "bg": bg,
        "fontSize": font_size,
        "duration": duration,
    }
    if scenes:
        req["scenes"] = scenes
    if width is not None:
        req["width"] = width
    if height is not None:
        req["height"] = height
    if start is not None:
        req["start"] = start
    if end is not None:
        req["end"] = end
    # 仅当服务端已支持额外字段时才传入；否则 FastAPI 会报 422。
    req.update(kwargs)
    return req


def make_mg_scene(
    text,
    color="#FFFFFF",
    bg="transparent",
    font_size=96,
    animation="fade",
    duration=2,
):
    """构造一个标准的 MGScene 字典。"""
    return {
        "text": text,
        "color": color,
        "bg": bg,
        "fontSize": font_size,
        "animation": animation,
        "duration": duration,
    }


def build_request_from_params(template_id, params: dict, canvas=None):
    """根据模板 id 和参数值构造 MGRequest。
    template_id: 模板 id
    params: 参数字典，键为 params 中的 name
    canvas: 可选，画布信息 {width, height, ratio}
    """
    req = {"template": template_id}
    if canvas:
        ratio = canvas.get("ratio")
        if ratio:
            req["ratio"] = ratio
        if canvas.get("width"):
            req["width"] = canvas["width"]
        if canvas.get("height"):
            req["height"] = canvas["height"]
    req.update(params)
    return req
