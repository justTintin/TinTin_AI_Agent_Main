# -*- coding: utf-8 -*-
"""
MG 动画服务端渲染 Worker（按 OpenAPI /mg/generate + /mg/status + /mg/result 实现）。
"""
import os
import time
from datetime import datetime

from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.mg_server_client import submit_mg_task, get_mg_status, download_mg_result, _ensure_url
from config.paths import MG_OUTPUT_DIR


class MGServerRenderWorker(BaseWorker):
    """提交 MG 服务端渲染任务，轮询 /mg/status，完成后 /mg/result 下载。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(str)   # 本地文件路径

    def __init__(self, request: dict, title=""):
        super().__init__()
        self.request = request
        self.title = title
        self.task_id = None

    def do_work(self):
        self.phase.emit("提交 MG 渲染任务到服务端…")
        self.task_id = submit_mg_task(self.request)
        if not self.task_id:
            raise RuntimeError("提交 MG 任务失败，请检查服务端地址与网络。")
        self.phase.emit(f"任务已提交：{self.task_id}")

        while True:
            time.sleep(2)
            data = get_mg_status(self.task_id)
            if not data:
                raise RuntimeError(f"查询任务 {self.task_id} 状态失败。")
            status = (data.get("status") or "").lower()
            progress = data.get("progress") or 0
            self.progress.emit(int(progress))
            self.phase.emit(f"[{self.task_id}] {status} {progress}%")
            if status in ("completed", "done", "success"):
                # 服务端 output_url 在 result.output_url，也可能是相对路径
                output_url = (
                    data.get("output_url")
                    or (data.get("result") or {}).get("output_url")
                    or data.get("url")
                    or data.get("video_url")
                )
                filename = f"mg_{self.request.get('template', 'scene')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                local_path = os.path.join(MG_OUTPUT_DIR, filename)
                self.phase.emit("正在下载 MG 成片…")
                try:
                    if output_url:
                        import requests
                        full = _ensure_url(output_url)
                        r = requests.get(full, stream=True, timeout=120)
                        r.raise_for_status()
                        if r.status_code != 200:
                            raise RuntimeError(f"下载失败 HTTP {r.status_code}: {r.text[:200]}")
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                    else:
                        download_mg_result(self.task_id, local_path)
                except Exception as e:
                    raise RuntimeError(f"下载 MG 成片失败：{e}")
                self.finished.emit(local_path)
                return
            if status in ("failed", "error"):
                msg = data.get("error_msg") or data.get("error") or data.get("message") or "未知错误"
                raise RuntimeError(f"MG 渲染失败：{msg}")
