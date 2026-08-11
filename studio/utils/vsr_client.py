# -*- coding: utf-8 -*-
"""服务端 VSR 去字幕客户端 — POST /vsr/remove（异步任务 + 轮询 + 下载）。

流程（服务端文档: docs/SERVER_API.md §七）：
  1. POST /vsr/remove 上传视频（inpaint_mode + sub_areas）→ 返回 task_id
  2. GET  /tasks/unified/{task_id} 轮询直到 completed/failed
  3. GET  /vsr/download/{filename} 下载结果视频并保存到本地

客户端不再依赖本地 VSR 二进制（apps/vsr-*），去字幕推理统一由算力服务端执行。
"""
import os
import time

import requests

from utils.logger_utils import log

_POLL_INTERVAL = 3.0       # 轮询间隔（秒）
_POLL_TIMEOUT = 1800.0     # 最长等待（去字幕较慢，给足 30 分钟）


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


def vsr_remove_remote(video_path, inpaint_mode="sttn_det", sub_areas=None,
                      out_path="", server_url="", timeout=_POLL_TIMEOUT,
                      progress_cb=None):
    """调用服务端去字幕并下载结果到本地。

    Args:
        video_path: 输入视频路径
        inpaint_mode: 算法（sttn_det / sttn_auto / sttn / lama / propainter 等，服务端支持为准）
        sub_areas: 字幕区域列表 [(ymin, ymax, xmin, xmax), ...]，为空时服务端自动检测
        out_path: 结果保存路径（留空则保存为「原目录/原名_no_sub.mp4」）
        server_url: 服务端地址（留空读 ai_config.json）
        timeout: 轮询超时秒数
        progress_cb: 可选回调 progress_cb(stage_text)，用于更新 UI 状态

    Returns:
        本地结果文件路径

    Raises:
        RuntimeError: 上传/轮询/下载任一环节失败
    """
    base = _server_url(server_url)

    if not out_path:
        stem, _ = os.path.splitext(video_path)
        out_path = f"{stem}_no_sub.mp4"

    def _stage(text):
        log.info(f"[VSR远程] {text}")
        if progress_cb:
            try:
                progress_cb(text)
            except Exception:
                pass

    # ── 第 1 步：上传视频提交任务 ──
    _stage("正在上传视频到服务端去字幕...")
    import json as _json
    data = {"inpaint_mode": inpaint_mode or "sttn_det"}
    if sub_areas:
        areas = [[int(a[0]), int(a[1]), int(a[2]), int(a[3])] for a in sub_areas]
        data["sub_areas"] = _json.dumps(areas)

    with open(video_path, "rb") as f:
        resp = requests.post(
            f"{base}/vsr/remove",
            files={"file": (os.path.basename(video_path), f, "video/mp4")},
            data=data,
            timeout=600,
        )
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"服务端返回 {resp.status_code}: {resp.text[:200]}")
    try:
        submit_data = resp.json()
    except Exception:
        raise RuntimeError(f"提交响应非 JSON: {resp.text[:200]}")

    task_id = (submit_data.get("task_id") or submit_data.get("id")
               or submit_data.get("job_id") or "")
    if not task_id:
        raise RuntimeError(f"服务端未返回任务 ID: {str(submit_data)[:200]}")

    # ── 第 2 步：轮询任务状态 ──
    _stage(f"服务端处理中（task={task_id}）...")
    poll_url = f"{base}/tasks/unified/{task_id}"
    deadline = time.time() + timeout
    filename = ""
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            pr = requests.get(poll_url, timeout=15)
        except Exception:
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
            result = task_obj.get("result") if isinstance(task_obj.get("result"), dict) else {}
            filename = (task_obj.get("filename") or task_obj.get("output")
                        or result.get("filename") or result.get("output") or "")
            break
        if status in ("failed", "error", "cancelled"):
            err = (task_obj.get("error_msg") or task_obj.get("error")
                   or task_obj.get("message") or "未知错误")
            raise RuntimeError(f"去字幕任务失败: {err}")
    else:
        raise RuntimeError(f"去字幕任务超时({timeout:.0f}s)，task_id={task_id}")

    if not filename:
        filename = f"{task_id}.mp4"

    # ── 第 3 步：下载结果视频 ──
    _stage("正在下载去字幕结果视频...")
    dl_url = f"{base}/vsr/download/{filename}"
    try:
        dr = requests.get(dl_url, timeout=600, stream=True)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"下载结果失败: {e}")
    if dr.status_code != 200:
        raise RuntimeError(f"下载结果失败 HTTP {dr.status_code}: {dl_url}")

    tmp_path = out_path + ".part"
    try:
        with open(tmp_path, "wb") as f:
            for chunk in dr.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        os.replace(tmp_path, out_path)
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise RuntimeError(f"保存结果视频失败: {e}")

    _stage(f"完成: {out_path}")
    return out_path
