"""服务端 RunningHub 接口客户端。

数字人任务由客户端直连 RunningHub，本模块仅保留服务端侧的两个辅助接口：

  POST /runninghub/workflow/{workflow_id}/json    工作流 JSON（识别输入节点）
  GET  /runninghub/status                         RunningHub 连接状态 + 配置
"""
import json
import os

import requests


def _get_server_url():
    """读取 ai_config.json 中的统一计算节点地址。"""
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
    except requests.exceptions.RequestException:
        return None


def get_workflow_json(workflow_id):
    """获取工作流 JSON（识别参数节点），失败返回 None。"""
    base = _get_server_url()
    if not base:
        return None
    try:
        resp = requests.post(f"{base}/runninghub/workflow/{workflow_id}/json", timeout=30)  # noqa: E501
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        for k in ("workflow", "data"):
            if isinstance(data.get(k), dict):
                return data[k]
        if any(isinstance(v, dict) and "class_type" in v for v in data.values()):
            return data
        return None
    except requests.exceptions.RequestException:
        return None
