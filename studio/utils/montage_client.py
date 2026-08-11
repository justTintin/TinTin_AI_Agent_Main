# -*- coding: utf-8 -*-
"""智能混剪服务端客户端 — 镜头画面描述批量生成。

describe_shots(): 逐条调用服务端 /material/score_clip（analyze_shot=true），
轮询统一任务接口 /tasks/unified/{task_id}，取回画面描述文案。

返回 {"1": "desc1", "2": "desc2", ...}（键为 1 起始的镜头序号字符串，
与 clip_paths 顺序一致）。单条失败不阻断整体，该条回退为「镜头片段 N」。
"""
import os
import time

import requests

from utils.logger_utils import log

_POLL_INTERVAL = 2.0       # 轮询间隔（秒）
_POLL_TIMEOUT = 300.0      # 单条镜头最大等待时间（秒）


def _server_url(server_url: str = "") -> str:
    """获取算力服务端地址（参数优先，其次读 ai_config.json 的 compute_server_url）。"""
    if server_url:
        return server_url.strip().rstrip("/")
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
    raise RuntimeError("未配置算力服务端地址（compute_server_url），请在系统设置中填写。")


def _extract_desc(result_payload) -> str:
    """从任务 result 中提取画面描述文案（兼容多种字段结构）。"""
    if not isinstance(result_payload, dict):
        return ""
    inner = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else result_payload
    desc = (inner.get("description") or inner.get("desc")
            or inner.get("analysis") or inner.get("text") or "")
    desc = str(desc).strip()
    if not desc:
        sa = inner.get("shot_analysis")
        if isinstance(sa, dict):
            desc = str(sa.get("scene_primary") or "").strip()
    return desc


def _describe_one(clip_path: str, base: str) -> str:
    """提交单个镜头 → 轮询 → 返回描述文案。失败抛出异常。"""
    fname = os.path.basename(clip_path)
    submit_url = f"{base}/material/score_clip"

    with open(clip_path, "rb") as f:
        resp = requests.post(
            submit_url,
            files={"file": (fname, f, "video/mp4")},
            data={"analyze_shot": "true", "product_mode": "true"},
            timeout=60,
        )
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"提交失败 HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        submit_data = resp.json()
    except Exception:
        raise RuntimeError(f"提交响应非 JSON: {resp.text[:200]}")

    task_id = (submit_data.get("task_id") or submit_data.get("id")
               or submit_data.get("job_id") or "")
    if not task_id:
        # 同步模式兼容：响应里直接包含结果
        desc = _extract_desc(submit_data)
        if desc:
            return desc
        raise RuntimeError(f"服务端未返回 task_id 也无描述结果: {str(submit_data)[:200]}")

    poll_url = f"{base}/tasks/unified/{task_id}"
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            pr = requests.get(poll_url, timeout=15)
        except Exception as e:
            log.warning(f"[describe_shots] {fname} 轮询异常: {e}")
            continue
        if pr.status_code != 200:
            continue
        try:
            pdata = pr.json()
        except Exception:
            continue
        task_obj = pdata.get("data") if isinstance(pdata.get("data"), dict) else pdata
        status = str(task_obj.get("status") or task_obj.get("state") or "").lower()
        if status in ("completed", "done", "success", "finished"):
            raw_result = task_obj.get("result") or task_obj
            desc = _extract_desc(raw_result)
            if desc:
                return desc
            raise RuntimeError(f"任务完成但无描述字段: {str(task_obj)[:200]}")
        if status in ("failed", "error", "cancelled"):
            err_msg = (task_obj.get("error_msg") or task_obj.get("error")
                       or task_obj.get("message") or "未知错误")
            raise RuntimeError(f"服务端任务失败: {err_msg}")
    raise RuntimeError(f"轮询超时（{_POLL_TIMEOUT:.0f}s），task_id={task_id}")


def describe_shots(clip_paths, server_url: str = "") -> dict:
    """批量生成镜头画面描述。

    Args:
        clip_paths: 镜头片段文件路径列表
        server_url: 服务端地址（留空读 ai_config.json 的 compute_server_url）

    Returns:
        {"1": "desc1", "2": "desc2", ...} 键为 1 起始的序号字符串
    """
    base = _server_url(server_url)
    result = {}
    for idx, clip_path in enumerate(clip_paths, 1):
        try:
            if not clip_path or not os.path.isfile(clip_path):
                raise RuntimeError(f"文件不存在: {clip_path}")
            desc = _describe_one(clip_path, base)
            result[str(idx)] = desc
            log.info(f"[describe_shots] {idx}/{len(clip_paths)} 完成: {desc[:50]}")
        except Exception as e:
            log.warning(f"[describe_shots] 镜头 {idx} 描述生成失败: {e}")
            result[str(idx)] = f"镜头片段 {idx}"
    return result
