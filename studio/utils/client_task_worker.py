"""客户端任务下发闭环：领取 → 执行 → 上报。

服务端契约（权威：/guide 与 /tasks/* 接口）：
- GET  /tasks/assigned/{machine_id}   客户端领取入口（领取即置 running）
    返回 {tasks: [{task_id, capability, params, executor}]}；空数组 = 无任务
- POST /tasks/{task_id}/report        客户端上报执行结果（multipart/form-data）
    body: machine_id(必填), status=ok|failed, error?, result?(JSON 字符串), file?(视频)

当前实现能力：
- 下载类任务（params 含 url）：打开客户端素材浏览器引导下载 → 轮询下载目录
  出现新文件 → 上报 file；超时未完成 → 上报 failed
- 其他能力：上报 failed（未实现能力）

心跳/技能登记见 skill_manager（POST /skills）与 AIStatusCheckThread（GET /health）。
"""
import contextlib
import json
import os
import time

import requests

from utils.http_client import http_get, http_post
from utils.logger_utils import log
from utils.scheduled_task_client import _server_url

# 下载类能力的判定关键词（服务端派发的 client 下载任务）
_DOWNLOAD_CAP_HINTS = ("download", "browser", "素材下载", "下载")

# 等用户下载的最长时间（秒）与轮询间隔
_DOWNLOAD_MAX_WAIT = 300
_DOWNLOAD_POLL = 2


def _machine_id() -> str:
    """当前机器码（任务归属，与服务端会话多租户隔离一致）。"""
    try:
        from utils.license import get_machine_id
        return get_machine_id() or ""
    except Exception:  # 外部API调用（import get_machine_id）
        return ""


# ── 领取 ────────────────────────────────────────────────────────────────

def pickup_tasks(machine_id=None, timeout=10):
    """GET /tasks/assigned/{machine_id} → 待执行任务列表（领取即置 running）。

    返回 [{task_id, capability, params, executor}]；失败/无任务返回 []。
    """
    mid = machine_id or _machine_id()
    if not mid:
        log.warning("[客户端任务] 无 machine_id，跳过领取")
        return []
    try:
        r = http_get(f"{_server_url()}/tasks/assigned/{mid}", timeout=timeout, quiet=True)  # noqa: E501
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                return data.get("tasks") or []
            if isinstance(data, list):
                return data
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.warning(f"[客户端任务] pickup 失败: {e}")
    return []


# ── 上报 ────────────────────────────────────────────────────────────────

def report_task(task_id, machine_id=None, status="ok", file_path=None,
                result=None, error=None, timeout=180):
    """POST /tasks/{task_id}/report → 上报执行结果，成功返回 True。

    - 成功 + 视频：file_path 以 multipart file 上传（服务端保存后续接处理）
    - 成功 + 结构化：result 为 JSON 字符串
    - 成功无文件 / 失败：status=ok/failed + error
    """
    mid = machine_id or _machine_id()
    if not mid or not task_id:
        log.warning("[客户端任务] report 缺少 machine_id 或 task_id")
        return False
    data = {"machine_id": mid, "status": status or "ok"}
    if error:
        data["error"] = error
    if result is not None:
        data["result"] = result
    try:
        if file_path and os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                resp = http_post(f"{_server_url()}/tasks/{task_id}/report",
                                 data=data, files={"file": (os.path.basename(file_path), f)},  # noqa: E501
                                 timeout=timeout)
        else:
            resp = http_post(f"{_server_url()}/tasks/{task_id}/report",
                             data=data, timeout=timeout)
        if resp.status_code == 200:
            log.info(f"[客户端任务] 上报成功 task_id={task_id} status={status}")
            return True
        log.warning(f"[客户端任务] report HTTP {resp.status_code}: {resp.text[:150]}")
    except (OSError, requests.exceptions.RequestException) as e:
        log.warning(f"[客户端任务] report 失败 task_id={task_id}: {e}")
    return False


# ── 执行分发 ────────────────────────────────────────────────────────────

def _is_download_task(task):
    cap = str((task or {}).get("capability") or "").lower()
    if any(h in cap for h in _DOWNLOAD_CAP_HINTS):
        return True
    params = (task or {}).get("params") or {}
    url = str(params.get("url") or "").strip()
    return url.startswith(("http://", "https://"))


def _snapshot_dir(d):
    """目录内文件名集合（用于检测新增文件）。"""
    try:
        if not os.path.isdir(d):
            return set()
        return {f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))}
    except OSError:
        return set()


def _wait_download_file(dl_dir, before, max_wait=_DOWNLOAD_MAX_WAIT,
                        poll=_DOWNLOAD_POLL, on_log=None):
    """轮询下载目录，等待出现新文件（用户在素材浏览器下载完成）。"""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        now = _snapshot_dir(dl_dir)
        new_files = sorted(now - before)
        if new_files:
            newest = os.path.join(dl_dir, new_files[-1])
            if on_log:
                with contextlib.suppress(Exception):
                    on_log(f"检测到下载完成：{newest}")
            return newest
        time.sleep(poll)
    return None


def execute_task(task, on_log=None, download_max_wait=_DOWNLOAD_MAX_WAIT):
    """执行单个下发任务，返回 {ok, file_path?, result?, error?}。

    下载类任务：打开客户端素材浏览器引导用户下载 → 轮询下载目录新文件；
    非下载能力：上报 failed（未实现）。
    """
    def _emit(msg):
        if on_log:
            with contextlib.suppress(Exception):
                on_log(msg)
        log.info(f"[客户端任务] {msg}")

    task_id = (task or {}).get("task_id") or ""
    params = (task or {}).get("params") or {}
    url = str(params.get("url") or "").strip()
    if not _is_download_task(task) or not url:
        cap = (task or {}).get("capability") or "?"
        return {"ok": False, "error": f"未实现的客户端能力: {cap}"}

    _emit(f"领取下载任务 {task_id}（{url}）")
    try:
        from utils.viral_clone_client import open_in_asset_browser
    except Exception as e:  # 外部API调用（import素材浏览器模块）
        return {"ok": False, "error": f"素材浏览器组件不可用: {e}"}

    topic = "客户端任务"
    dl_dir = ""
    try:
        ok, msg, dl_dir = open_in_asset_browser(url, topic=topic)
    except Exception:  # 外部API调用
        ok, msg, dl_dir = False, "打开素材浏览器失败", ""
    if not ok:
        return {"ok": False, "error": msg or "打开素材浏览器失败"}

    before = _snapshot_dir(dl_dir) if dl_dir else set()
    _emit("已打开素材浏览器，请在浏览器中下载视频并入库（等待下载文件…）")
    file_path = _wait_download_file(dl_dir, before,
                                    max_wait=download_max_wait, on_log=on_log)
    if not file_path:
        return {"ok": False, "error": "等待下载超时，用户未完成下载"}
    # 上报成功 + 视频文件（服务端保存并续接处理）
    return {"ok": True, "file_path": file_path}
