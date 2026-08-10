# -*- coding: utf-8 -*-
"""服务端数字人 / RunningHub 接口客户端。

服务端已实现并配置 RunningHub（/runninghub/status → configured=true），
客户端数字人任务从"直连 www.runninghub.cn"改为优先走服务端统一接口：

  POST /digital-human/submit                      multipart: image + audio + workflow_id + instance_type + backend → task_id
  GET  /digital-human/task/{task_id}              任务状态（服务端透传 RunningHub 响应）
  GET  /digital-human/workflows                   服务端订阅的工作流列表
  POST /runninghub/workflow/{workflow_id}/json    工作流 JSON（识别输入节点）
  GET  /runninghub/status                         RunningHub 连接状态 + 配置

openapi 中这些接口未声明 response schema（resp200 为空），
按描述与实际响应做多层兜底解析（参考 /agent/chat 先例：以实测为准）。
"""
import json
import os

import requests


def _get_server_url():
    """读取 ai_config.json 中的统一计算节点地址。"""
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _pick(data, *keys):
    """从 dict 中依次尝试 keys 定位目标值，未命中返回 None。"""
    if not isinstance(data, dict):
        return None
    for k in keys:
        if k in data:
            return data[k]
    return None


def get_server_status():
    """查询服务端 RunningHub 连接状态。返回 {"configured": bool, ...} 或 None。"""
    base = _get_server_url()
    if not base:
        return None
    try:
        resp = requests.get(f"{base}/runninghub/status", timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def submit_digital_human(image, audio, workflow_id, instance_type="default", backend="runninghub"):
    """一步提交数字人任务（人物图 + 驱动音频），服务端负责上传 RunningHub 并 run_workflow。

    返回 (task_id, None) 成功；失败返回 (None, 错误信息)。服务端地址未配置时返回 (None, "")，
    调用方据此静默回退直连 RunningHub。
    """
    base = _get_server_url()
    if not base:
        return None, ""
    try:
        with open(image, "rb") as fi, open(audio, "rb") as fa:
            resp = requests.post(
                f"{base}/digital-human/submit",
                files={
                    "image": (os.path.basename(image), fi),
                    "audio": (os.path.basename(audio), fa),
                },
                data={
                    "workflow_id": workflow_id,
                    "instance_type": instance_type,
                    "backend": backend,
                },
                timeout=300)
        if resp.status_code != 200:
            return None, f"服务端返回 {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        if not isinstance(data, dict):
            return None, "服务端响应格式异常"
        if data.get("ok") is False or data.get("success") is False:
            return None, str(data.get("message") or data.get("error") or "服务端拒绝提交")
        # 兼容 {task_id} / {data:{task_id}} / {data:{id}} / {code:0,data:{...}}
        task_id = _pick(data, "task_id", "taskId", "id")
        if task_id is None and isinstance(data.get("data"), dict):
            task_id = _pick(data["data"], "task_id", "taskId", "id")
        if task_id:
            return str(task_id), None
        return None, f"服务端未返回 task_id: {json.dumps(data, ensure_ascii=False)[:300]}"
    except FileNotFoundError as e:
        return None, f"文件不存在: {e}"
    except Exception as e:
        return None, str(e)


def get_task_status(task_id):
    """查询数字人任务状态（服务端透传 RunningHub 响应），失败返回 None。"""
    base = _get_server_url()
    if not base:
        return None
    try:
        resp = requests.get(f"{base}/digital-human/task/{task_id}", timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_workflows():
    """获取服务端订阅的 RunningHub 工作流列表，失败返回 None。

    返回条目字段：id / name / type / instance_type / image_nodes / audio_nodes。
    """
    base = _get_server_url()
    if not base:
        return None
    try:
        resp = requests.get(f"{base}/digital-human/workflows", timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        items = data.get("workflows")
        if items is None and isinstance(data.get("data"), dict):
            items = data["data"].get("workflows")
        return items if isinstance(items, list) else None
    except Exception:
        return None


def get_workflow_json(workflow_id):
    """获取工作流 JSON（识别参数节点），失败返回 None。"""
    base = _get_server_url()
    if not base:
        return None
    try:
        resp = requests.post(f"{base}/runninghub/workflow/{workflow_id}/json", timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        # 兼容 {workflow: {...}} / {data: {...}} / 直接返回 workflow dict
        for k in ("workflow", "data"):
            if isinstance(data.get(k), dict):
                return data[k]
        if any(isinstance(v, dict) and "class_type" in v for v in data.values()):
            return data
        return None
    except Exception:
        return None
