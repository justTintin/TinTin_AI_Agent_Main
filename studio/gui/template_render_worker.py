# -*- coding: utf-8 -*-
"""模板成片渲染 Worker（按统一模板接口 /templates/render 返回的任务 ID 轮询）。

统一模板渲染任务优先用 GET /templates/render/result/{task_id} 查询状态、
GET /templates/render/download/{task_id} 下载；失败再回退统一任务查询
/tasks/unified/{task_id}、成片队列 /scheduled/tasks/{id}、编辑器 /editor/render/{id}。
"""
import os
import time
from datetime import datetime

from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.http_client import http_get
from utils.mg_server_client import _ensure_url
from config.paths import MG_OUTPUT_DIR


class TemplateRenderWorker(BaseWorker):
    """提交模板生成任务，轮询状态，下载结果。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(str)   # 本地文件路径

    def __init__(self, task_id: str, out_name: str = ""):
        super().__init__()
        self.task_id = task_id
        self.out_name = out_name or f"template_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    def _server_url(self):
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

    def _get_status(self):
        """尝试 /templates/render/result/{id}，失败回退统一/成片/编辑器接口。"""
        url = self._server_url()
        if not url:
            return None
        # 优先统一模板渲染 result，再回退统一任务查询/成片队列/编辑器渲染
        for endpoint in (f"{url}/templates/render/result/{self.task_id}",
                         f"{url}/tasks/unified/{self.task_id}",
                         f"{url}/scheduled/tasks/{self.task_id}",
                         f"{url}/editor/render/{self.task_id}"):
            try:
                r = http_get(endpoint, timeout=10)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        return None

    def _download(self, output_url, local_path):
        import requests
        full = _ensure_url(output_url)
        r = requests.get(full, stream=True, timeout=120)
        r.raise_for_status()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return local_path

    def do_work(self):
        self.phase.emit(f"模板生成任务已提交：{self.task_id}")
        while True:
            time.sleep(2)
            data = self._get_status()
            if not data:
                raise RuntimeError(f"查询任务 {self.task_id} 状态失败。")
            status = (data.get("status") or "").lower()
            progress = data.get("progress") or 0
            self.progress.emit(int(progress))
            self.phase.emit(f"[{self.task_id}] {status} {progress}%")
            if status in ("completed", "done", "success"):
                output_url = (
                    data.get("output_url")
                    or (data.get("result") or {}).get("output_url")
                    or data.get("url")
                    or data.get("video_url")
                )
                local_path = os.path.join(MG_OUTPUT_DIR, self.out_name)
                if output_url:
                    self.phase.emit("正在下载模板成片…")
                    self._download(output_url, local_path)
                else:
                    # 兜底：统一模板渲染任务可直接用 /templates/render/download/{task_id}
                    base = self._server_url()
                    if not base:
                        raise RuntimeError("任务完成但无 output_url，且未配置 compute_server_url")
                    self.phase.emit("正在下载模板成片（统一渲染 download）…")
                    self._download(f"{base}/templates/render/download/{self.task_id}", local_path)
                self.finished.emit(local_path)
                return
            if status in ("failed", "error"):
                msg = data.get("error_msg") or data.get("error") or data.get("message") or "未知错误"
                raise RuntimeError(f"模板生成失败：{msg}")
