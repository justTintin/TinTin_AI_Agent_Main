# -*- coding: utf-8 -*-
"""智能体编排客户端：封装 /agent 接口族（能力注册表 + 编排任务树 + 中间产物）。

服务端「智能体化」契约（权威：服务端 /guide 智能体化章节，客户端 PRD_V2.2 §13）：
- GET  /agent/registry                 能力注册表（31 能力，只读；include_external 附加客户端侧能力）
- POST /agent/tasks                    登记编排任务；mode=execute 提交 plan 由服务端 Orchestrator 自动执行
- GET  /agent/tasks                    列表（默认只列根任务；root_only=false 全部）
- GET  /agent/tasks/{id}               详情 + children 嵌套子任务树（derived_status 聚合推导）
- PATCH /agent/tasks/{id}              更新状态/进度/结果（执行器与客户端共用）
- POST /agent/tasks/{id}/confirm       S4 人工确认：waiting_user_input → queued 继续推进
- POST /agent/tasks/{id}/pause|resume|retry|cancel   S6 任务管理（断点续跑）
- POST /agent/artifacts                手动登记中间产物
- GET  /agent/tasks/{id}/artifacts     任务产物列表（自动 + 手动）

任务 id 前缀 a_；/tasks/unified/{id} 已打通（返回完整子任务树）。
"""
import os

from utils.http_client import http_get, http_post, logged_request
from utils.logger_utils import log
from utils.scheduled_task_client import _server_url


def _machine_id() -> str:
    """当前机器码（会话多租户隔离用）。"""
    try:
        from utils.license import get_machine_id
        return get_machine_id() or ""
    except Exception:
        return ""


def _attach_machine(url, machine_id=None):
    """给 URL 追加 machine_id query 参数（会话归属校验）。"""
    mid = machine_id or _machine_id()
    if not mid:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}machine_id={mid}"

# 编排任务状态取值（服务端 agent_tasks 表）
TASK_STATUSES = ("queued", "running", "waiting_user_input",
                 "completed", "failed", "paused", "cancelled")


# ── 同步 API（供 Worker 调用，全部带超时）──────────────────────────────────
def get_registry(include_external=False, timeout=10):
    """GET /agent/registry → {registry_version, count, capabilities:[...]}。

    失败返回 None。include_external=True 附加客户端本地工具/外部工作流登记项。
    """
    try:
        url = f"{_server_url()}/agent/registry"
        if include_external:
            url += "?include_external=1"
        r = http_get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[智能体] get_registry HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"[智能体] get_registry 失败: {e}")
    return None


def get_capability(capability_id, timeout=10):
    """GET /agent/registry/{capability_id} → 单个能力 dict；不存在/失败返回 None。"""
    try:
        r = http_get(f"{_server_url()}/agent/registry/{capability_id}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning(f"[智能体] get_capability({capability_id}) 失败: {e}")
    return None


def create_task(goal=None, plan=None, capability=None, params=None,
                parent_task_id=None, mode=None, timeout=15):
    """POST /agent/tasks → 登记/提交编排任务，返回新任务 dict（失败返回 None）。

    - mode="execute"：提交 plan（{goal, steps:[{id, capability, params, depends_on,
      needs_user_input}]}），服务端校验后创建父任务 + 每步一个子任务并自动执行，
      响应含 execution="started"。
    - 不带 mode：手动登记单个任务（goal/capability+params/parent_task_id）。
    """
    body = {}
    if goal:
        body["goal"] = goal
    if plan:
        body["plan"] = plan
    if capability:
        body["capability"] = capability
    if params:
        body["params"] = params
    if parent_task_id:
        body["parent_task_id"] = parent_task_id
    if mode:
        body["mode"] = mode
    try:
        r = http_post(f"{_server_url()}/agent/tasks", json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[智能体] create_task HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[智能体] create_task 失败: {e}")
    return None


def list_tasks(root_only=True, status=None, parent_task_id=None, timeout=10):
    """GET /agent/tasks → 编排任务列表 dict {count, tasks}。失败返回 {}。

    root_only=True 只列根任务；status/parent_task_id 可过滤。
    """
    try:
        params = {}
        if not root_only:
            params["root_only"] = "false"
        if status:
            params["status"] = status
        if parent_task_id:
            params["parent_task_id"] = parent_task_id
        r = http_get(f"{_server_url()}/agent/tasks", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[智能体] list_tasks HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"[智能体] list_tasks 失败: {e}")
    return {}


def get_task(task_id, timeout=10):
    """GET /agent/tasks/{id} → 编排任务详情（children 嵌套树）。失败返回 None。"""
    try:
        r = http_get(f"{_server_url()}/agent/tasks/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[智能体] get_task({task_id}) HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"[智能体] get_task({task_id}) 失败: {e}")
    return None


def update_task(task_id, status=None, progress=None, result=None,
                error_msg=None, params=None, timeout=10):
    """PATCH /agent/tasks/{id} → 更新状态/进度/结果/参数，成功返回 True。"""
    body = {}
    if status is not None:
        body["status"] = status
    if progress is not None:
        body["progress"] = progress
    if result is not None:
        body["result"] = result
    if error_msg is not None:
        body["error_msg"] = error_msg
    if params is not None:
        body["params"] = params
    if not body:
        return False
    try:
        r = logged_request("PATCH", f"{_server_url()}/agent/tasks/{task_id}",
                           json=body, timeout=timeout)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"[智能体] update_task({task_id}) 失败: {e}")
        return False


def _action(task_id, action, timeout=10):
    """POST /agent/tasks/{id}/{action} 通用操作（cancel/confirm/pause/resume/retry）。"""
    try:
        r = http_post(f"{_server_url()}/agent/tasks/{task_id}/{action}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[智能体] {action}({task_id}) HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[智能体] {action}({task_id}) 失败: {e}")
    return None


def confirm_task(task_id, timeout=10):
    """S4 人工确认：把 waiting_user_input 的子任务恢复为 queued，执行器继续推进。"""
    return _action(task_id, "confirm", timeout)


def pause_task(task_id, timeout=10):
    """S6 暂停 plan：父任务 running → paused，执行器在当前层收尾后停住。"""
    return _action(task_id, "pause", timeout)


def resume_task(task_id, timeout=10):
    """S6 恢复 plan：paused → running（响应含 executor_respawned 是否重拉执行器）。"""
    return _action(task_id, "resume", timeout)


def retry_task(task_id, timeout=10):
    """S6 重试：仅 failed/cancelled 父任务；failed/cancelled 子任务重置为 queued，
    completed 子任务保留为断点（结果直接复用），父任务回 running 续跑。"""
    return _action(task_id, "retry", timeout)


def cancel_task(task_id, timeout=10):
    """取消编排任务：自身置 cancelled，未终态后代级联取消（执行器同步停止）。"""
    return _action(task_id, "cancel", timeout)


def list_artifacts(task_id, timeout=10):
    """GET /agent/tasks/{id}/artifacts → 任务中间产物列表（自动 + 手动）。失败返回 []。"""
    try:
        r = http_get(f"{_server_url()}/agent/tasks/{task_id}/artifacts", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data.get("artifacts") or data.get("items") or []
        log.warning(f"[智能体] list_artifacts({task_id}) HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"[智能体] list_artifacts({task_id}) 失败: {e}")
    return []


def register_artifact(task_id, kind, file_ref, meta=None, timeout=10):
    """POST /agent/artifacts → 手动登记子任务产物。成功返回 True。"""
    try:
        r = http_post(f"{_server_url()}/agent/artifacts", timeout=timeout, json={
            "task_id": task_id, "kind": kind, "file_ref": file_ref,
            "meta": meta or {},
        })
        return r.status_code == 200
    except Exception as e:
        log.warning(f"[智能体] register_artifact({task_id}) 失败: {e}")
        return False


def agent_chat(message, history=None, agent_id=None, model=None,
               max_rounds=3, mode=None, session_id=None, machine_id=None,
               timeout=180):
    """POST /agent/chat → 智能体对话：自然语言 → 服务端智能体循环 → 回复。

    返回 dict：{"reply", "session_id", "attachments", "tool_calls"}；失败返回 None。
    session_id：传则续接服务端持久化会话（素材池自动注入）；不传则服务端新建会话，
    响应带回 session_id（客户端应保存以便后续轮次续接）。
    mode="plan"：拆解为 plan 提交编排执行（S2），无 reply 而含 task_id 时返回提示文本；
    history 为 OpenAI 风格消息列表（不含本轮 message）。
    """
    body = {"message": message, "max_rounds": max_rounds, "stream": False}
    if history:
        body["history"] = history
    if agent_id:
        body["agent_id"] = agent_id
    if model:
        body["model"] = model
    if mode:
        body["mode"] = mode
    if session_id:
        body["session_id"] = session_id
    if machine_id is None:
        machine_id = _machine_id()
    if machine_id:
        body["machine_id"] = machine_id
    try:
        r = http_post(f"{_server_url()}/agent/chat", json=body, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            reply = data.get("reply") or ""
            if not reply and mode == "plan":
                tid = str(data.get("task_id") or "")
                if tid:
                    reply = (f"✅ 已创建编排任务：`{tid}`，服务端将自动执行。\n"
                             f"可在「编排任务」页查看进度与产物。")
            return {
                "reply": reply,
                "session_id": str(data.get("session_id") or ""),
                "attachments": data.get("attachments") or [],
                "tool_calls": data.get("tool_calls") or [],
            }
        log.warning(f"[智能体] agent_chat HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[智能体] agent_chat 失败: {e}")
    return None


# ── 会话素材池（guide 契约：入池后贯穿会话所有后续消息，服务端自动注入；
#    客户端只提交一次，明确不再使用时调 DELETE 移除）────────────────────

def create_session(message="会话初始化", machine_id=None, timeout=60):
    """无 POST 建会话接口 → 以一条轻量 chat 创建会话，返回 session_id（失败 ""）。"""
    res = agent_chat(message, max_rounds=1, machine_id=machine_id, timeout=timeout)
    if res:
        return res.get("session_id") or ""
    return ""


def delete_session(session_id, machine_id=None, timeout=10):
    """DELETE /agent/sessions/{id} → 删除会话（会话素材池一并清理）。成功返回 True。"""
    if not session_id:
        return False
    try:
        url = _attach_machine(f"{_server_url()}/agent/sessions/{session_id}", machine_id)
        r = logged_request("DELETE", url, timeout=timeout)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"[会话] delete_session({session_id}) 失败: {e}")
        return False


def session_attachments(session_id, machine_id=None, timeout=10):
    """GET /agent/sessions/{id}/attachments → 会话素材池列表（失败 []）。

    条目：{"name", "file_ref", "media_type", "source", "added_at"}。
    """
    if not session_id:
        return []
    try:
        url = _attach_machine(f"{_server_url()}/agent/sessions/{session_id}/attachments",
                              machine_id)
        r = http_get(url, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data.get("attachments") or []
        log.warning(f"[会话] session_attachments({session_id}) HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"[会话] session_attachments({session_id}) 失败: {e}")
    return []


def session_attachment_add(session_id, material_id=None, file_path=None,
                           machine_id=None, timeout=300):
    """素材入池（二选一）：material_id 引用素材库 或 file_path 上传附件（multipart）。

    返回服务端确认的池条目 dict（含 name/file_ref/media_type）；失败返回 None。
    入池后贯穿本会话所有后续消息（服务端自动注入），无需每轮重复提交。
    """
    if not session_id:
        return None
    url = _attach_machine(f"{_server_url()}/agent/sessions/{session_id}/attachments",
                          machine_id)
    try:
        if material_id:
            log.info(f"[会话] 素材入池 session={session_id} material_id={material_id}")
            r = http_post(url, data={"material_id": str(material_id)}, timeout=30)
        elif file_path and os.path.isfile(file_path):
            log.info(f"[会话] 附件入池 session={session_id} file={os.path.basename(file_path)}")
            with open(file_path, "rb") as f:
                r = http_post(url, files={"file": (os.path.basename(file_path), f)},
                              timeout=timeout)
        else:
            return None
        if r.status_code == 200:
            data = r.json()
            att = (data.get("attachment") or data.get("item")
                   or (data.get("attachments") or [None])[-1]) or {}
            if not att.get("file_ref") and material_id:
                att["file_ref"] = str(material_id)  # 素材库引用的删除 key = material_id
            return att
        log.warning(f"[会话] 素材入池 HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[会话] 素材入池失败: {e}")
    return None


def session_attachment_remove(session_id, key, machine_id=None, timeout=10):
    """DELETE /agent/sessions/{id}/attachments/{key} → 从会话素材池移除。

    key = file_ref（附件）或 material_id（素材库引用）；移除后后续消息不再注入，
    本地上传的附件文件服务端同步删除。成功返回 True。
    注意：服务端可能 HTTP 200 但 removed=0（未匹配到条目，如 material 类型
    删除的服务端 bug），此时按失败返回 False，避免 UI 误报删除成功。
    """
    if not session_id or not key:
        return False
    try:
        url = _attach_machine(
            f"{_server_url()}/agent/sessions/{session_id}/attachments/{key}", machine_id)
        r = logged_request("DELETE", url, timeout=timeout)
        if r.status_code == 200:
            try:
                removed = r.json().get("removed")
            except Exception:
                removed = None
            if removed == 0:  # 200 但没删到任何条目 → 视为失败
                log.warning(f"[会话] 素材移除未生效 session={session_id} key={key}（服务端 removed=0）")
                return False
            log.info(f"[会话] 素材移除 session={session_id} key={key}")
            return True
        log.warning(f"[会话] 素材移除 HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.warning(f"[会话] 素材移除({key}) 失败: {e}")
    return False
