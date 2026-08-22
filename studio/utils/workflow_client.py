# -*- coding: utf-8 -*-
"""服务端「统一工作流」接口客户端。

封装 /workflows* 与 /workflows/task 接口，供客户端发现、提交、轮询工作流：

  GET  /workflows                        列出客户端可用工作流（client_api/backend/type…）
  POST /workflows/{workflow_id}/run      统一提交工作流（multipart: image/audio/instance_type）
  GET  /workflows/task/{task_id}         统一任务查询（按记录自动路由 runninghub/comfyui）

契约见服务端 /guide 2.9.1 / 2.9.3，字段以实测契约为准，不臆造。
"""
import json
import os

import requests

from utils.http_client import http_get, http_post
from utils.logger_utils import log


def _get_server_url() -> str:
    """读取 ai_config.json 中的统一计算节点地址（compute_server_url）。

    与 scheduled_task_client / digital_human_client 等保持一致：读失败或无配置返回空串。
    """
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def list_workflows(scope: str = "client", timeout: int = 15) -> dict:
    """GET /workflows — 列出客户端可见工作流。

    scope: client（默认，仅返回客户端可用）| all（含 internal）。
    返回 {"workflows": [...], "total": N, "scope": "client"}；失败返回 {}。
    """
    base = _get_server_url()
    if not base:
        log.warning("[workflow] 未配置 compute_server_url，无法列出工作流")
        return {}
    url = f"{base}/workflows"
    try:
        r = http_get(url, params={"scope": scope}, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        return data if isinstance(data, dict) else {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[workflow] list_workflows 失败: {e}")
        return {}


def normalize_server_workflow(w) -> dict | None:
    """把 GET /workflows 返回的工作流项归一化为客户端使用的形状。

    服务端字段（workflow_id/instance_type）→ 客户端本地字段（id/instanceType），
    以便数字人 Tab 下拉选择器与 _rh_find_workflow_config 复用同一套结构。
    非 dict 或无 workflow_id 返回 None。
    """
    if not isinstance(w, dict):
        return None
    wf_id = w.get("workflow_id")
    if not wf_id:
        return None
    return {
        "id": wf_id,
        "name": w.get("name") or wf_id,
        "type": w.get("type") or "其他",
        "instanceType": w.get("instance_type") or "default",
        "description": w.get("description") or "",
        "client_api": w.get("client_api") or "",
        "image_nodes": w.get("image_nodes") or [],
        "audio_nodes": w.get("audio_nodes") or [],
        "backend": w.get("backend") or "",
        "scope": w.get("scope") or "client",
        # 服务端固定的输出类型字段：image / video
        "output_type": w.get("output_type") or "",
        # 统一工作流输入组件清单（kind: image/video/audio/text/select；key=multipart 字段名）
        "inputs": w.get("inputs") or [],
        "io": w.get("io") or {},
    }


def _add_file(files: dict, field: str, path: str,
              mime: str = "application/octet-stream") -> None:
    """向 multipart files dict 追加一个文件字段；路径为空或不存在则跳过。"""
    if path and os.path.isfile(path):
        files[field] = (os.path.basename(path), open(path, "rb"), mime)


def run_workflow(workflow_id: str, files: dict | None = None, values: dict | None = None,
                 instance_type: str = "default", timeout: int = 300,
                 image_path: str = "", audio_path: str = "") -> dict:
    """POST /workflows/{workflow_id}/run — 统一提交工作流（multipart）。

    输入按工作流 inputs 组件清单（GET /workflows 返回）动态提交：
      - 文件类组件（kind=image/video/audio）：multipart 文件，字段名 = 组件 key
      - 文本/选择器组件（kind=text/select）：multipart 字符串，字段名 = 组件 key
      - instance_type：实例档位（default/plus 等，435 未找到独占实例服务端自动重试 plus）

    参数：
      files  : {key: 本地文件路径}，key 为组件清单里的字段名（image/audio/video…）
      values : {key: 字符串}，用于 text/select 组件
      image_path/audio_path：向后兼容旧调用（等同 files={"image":…,"audio":…}）

    返回服务端响应 dict（如 {"ok": True, "task_id": ..., "workflow_id": ..., "backend": ...}），
    失败返回 {}。
    """
    base = _get_server_url()
    if not base:
        log.error("[workflow] 未配置 compute_server_url，无法提交工作流")
        return {}
    url = f"{base}/workflows/{workflow_id}/run"
    mp_files: dict = {}
    for _key, _path in (files or {}).items():
        _add_file(mp_files, _key, _path)
    # 兼容旧调用
    _add_file(mp_files, "image", image_path)
    _add_file(mp_files, "audio", audio_path)
    data = dict(values or {})
    data["instance_type"] = instance_type or "default"
    try:
        r = http_post(url, data=data, files=mp_files, timeout=timeout)
        r.raise_for_status()
        resp = r.json() or {}
        return resp if isinstance(resp, dict) else {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[workflow] run_workflow 失败: {e}")
        return {}
    finally:
        for _f in mp_files.values():
            try:
                _f[1].close()
            except Exception:
                pass


def task_status(task_id: str, timeout: int = 15) -> dict:
    """GET /workflows/task/{task_id} — 统一任务查询。

    返回完整响应 dict（如 {"code": 0, "data": {"taskId": ..., "status": "SUCCESS",
    "results": [...]}}），失败或非 200 返回 {}。
    """
    base = _get_server_url()
    if not base:
        return {}
    url = f"{base}/workflows/task/{task_id}"
    try:
        r = http_get(url, timeout=timeout)
        r.raise_for_status()
        resp = r.json() or {}
        return resp if isinstance(resp, dict) else {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[workflow] task_status 失败: {e}")
        return {}
