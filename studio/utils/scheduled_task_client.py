"""
定时任务服务端客户端：封装 /scheduled/tasks 接口。

定时任务的「存储 + 调度 + 执行」全部在服务端完成，客户端只负责：
- 提交任务（一键成片的「开始执行」=立即执行；「添加为定时任务」=定时执行）
- 监控任务状态/结果（定时任务页轮询 GET）
- 删除/查看任务

不引入本地 json 存储、不引入本地调度线程——这些都由服务端做。

服务端任务字段（实测 /scheduled/tasks 返回）：
    id, task_type, title, params, status(pending/running/completed/failed),
    progress(0-100), error_msg, result({video_url:...}), client_ip,
    created_at, updated_at, completed_at
"""
import requests

from utils.http_client import http_delete, http_get, http_post
from utils.logger_utils import log


def _server_url():
    """读取 compute_server_url（与 vector_search_page / compile_video_page 一致）。"""
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


# ── 同步 API（供 Worker 调用，全部带超时）──────────────────────────────────
def list_tasks(timeout=10):
    """GET /scheduled/tasks → 返回任务列表 [{...}, ...]。失败返回 []。"""
    try:
        r = http_get(f"{_server_url()}/scheduled/tasks", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data.get("items") or data.get("data") or []
        log.warning(f"[定时任务] list_tasks HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] list_tasks 失败: {e}")
    return []


def get_task(task_id, timeout=10):
    """GET /tasks/unified/{id} → 返回单任务 dict。失败返回 None。

    按 /guide 4.4 说明，客户端统一走 unified 轮询；unified 失败时回退到
    /scheduled/tasks/{id} 保持兼容。
    """
    try:
        r = http_get(f"{_server_url()}/tasks/unified/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] unified get_task({task_id}) 失败: {e}")

    try:
        r = http_get(f"{_server_url()}/scheduled/tasks/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] get_task({task_id}) 失败: {e}")
    return None


def create_task(task_type, title, params, schedule=None, timeout=15):
    """POST /scheduled/tasks → 提交任务，返回新任务 id（失败返回 None）。

    task_type: 服务端执行器类型，一键成片用 'product_montage'（命名规范 NAMING-CONVENTIONS）
    title: 任务标题
    params: 客户端完整参数 dict（产品/素材/配音/字幕/条数/时长...，服务端按需取用）
    schedule: 定时配置 dict（None 或不含调度字段 = 立即执行）；
        含 mode/time/date/weekdays/interval_hours 等 = 定时执行
    """
    body = {
        "task_type": task_type,
        "title": title or "未命名任务",
        "params": params or {},
    }
    if schedule:
        body["schedule"] = schedule
    try:
        r = http_post(f"{_server_url()}/scheduled/tasks", json=body, timeout=timeout)
        if r.status_code == 200:
            new_id = r.json().get("id")
            log.info(f"[定时任务] create_task 成功, task_id={new_id}, type={task_type}")
            return new_id
        log.warning(f"[定时任务] create_task HTTP {r.status_code}: {r.text[:150]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] create_task 失败: {e}")
    return None


def delete_task(task_id, timeout=10):
    """DELETE /scheduled/tasks/{id} → 成功返回 True。"""
    try:
        r = http_delete(f"{_server_url()}/scheduled/tasks/{task_id}", timeout=timeout)
        return r.status_code == 200
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] delete_task({task_id}) 失败: {e}")
        return False


# ── 进化机制（变体打分）─────────────────────────────────────────────────────
def evolution_feedback(task_id, feedback, timeout=10):
    """POST /scheduled/tasks/evolution/feedback → 对某次成片（变体）的好坏反馈。

    task_id: 成片任务 id（服务端用其字符串形式作 evolution_id）
    feedback: 'good' 或 'bad'
    返回 True 表示服务端已记录（status:updated）；False 表示 id 无效或失败。
    """
    try:
        r = http_post(f"{_server_url()}/scheduled/tasks/evolution/feedback",
                      json={"evolution_id": str(task_id), "feedback": feedback},
                      timeout=timeout)
        if r.status_code == 200:
            return r.json().get("status") == "updated"
        log.warning(f"[定时任务] evolution_feedback task_id={task_id} HTTP {r.status_code}: {r.text[:120]}")  # noqa: E501
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] evolution_feedback task_id={task_id} 失败: {e}")
    return False


def evolution_stats(timeout=10):
    """GET /scheduled/tasks/evolution/stats → 进化统计 dict。
    返回 {total_generations, strategies:[{script_style,pacing,count,avg_score,max_score}],
          good_feedback, bad_feedback}。失败返回 {}。"""
    try:
        r = http_get(f"{_server_url()}/scheduled/tasks/evolution/stats", timeout=timeout)  # noqa: E501
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] evolution_stats 失败: {e}")
    return {}


# ── 深度评审 ─────────────────────────────────────────────────────────────────
def evaluate_by_task(task_id, timeout=10):
    """GET /evaluate/by-task/{task_id} → 返回评价 dict，失败返回 None。

    成片类任务完成后服务端自动投递评价。
    """
    try:
        r = http_get(f"{_server_url()}/evaluate/by-task/{task_id}", timeout=timeout)
        if r.status_code == 200:
            ev = (r.json() or {}).get("evaluation")
            if isinstance(ev, dict) and ev.get("total") is not None:
                return ev
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] evaluate_by_task({task_id}) 失败: {e}")
    return None


# ── 维度化反馈 ─────────────────────────────────────────────────────────────────
def submit_dimension_feedback(task_id, dimension_scores, timeout=10):
    """POST /evaluate/feedback/dimensions → 逐维改分提交。

    task_id: 成片任务 id
    dimension_scores: dict like {"technical": 8, "editing": 7, "aesthetic": 9}
    返回 True 表示服务端已更新；False 表示失败。
    """
    try:
        r = http_post(f"{_server_url()}/evaluate/feedback/dimensions",
                      json={"task_id": str(task_id), "dimensions": dimension_scores},
                      timeout=timeout)
        if r.status_code == 200:
            return True
        log.warning(f"[定时任务] submit_dimension_feedback task_id={task_id} HTTP {r.status_code}: {r.text[:120]}")  # noqa: E501
    except requests.exceptions.RequestException as e:
        log.warning(f"[定时任务] submit_dimension_feedback task_id={task_id} 失败: {e}")
    return False


# ── 结果下载 ─────────────────────────────────────────────────────────────────
def download_result_file(url, path, timeout=180):
    """下载服务端文件到本地。

    流式写文件；若端点返回 JSON（如 {url:...}）则取其地址重试一次。
    """
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    r = http_get(url, timeout=timeout, stream=True)
    try:
        if r.status_code != 200:
            raise RuntimeError(f"服务端返回 HTTP {r.status_code}")
        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            data = r.json()
            inner = (data.get("url") or data.get("video_url")
                     or data.get("output_url") or data.get("file_url") or "")
            if not inner:
                raise RuntimeError("结果端点返回 JSON 但无视频地址字段")
            base = _server_url()
            if isinstance(inner, str) and inner.startswith("/") and base:
                inner = base + inner
            return download_result_file(inner, path, timeout=timeout)
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
    finally:
        r.close()
    return path
