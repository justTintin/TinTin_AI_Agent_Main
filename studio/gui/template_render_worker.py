"""模板成片渲染 Worker（按统一模板接口 /templates/render 返回的任务 ID 轮询）。

统一模板渲染任务优先用 GET /templates/render/result/{task_id} 查询状态、
GET /templates/render/download/{task_id} 下载；失败再回退统一任务查询
/tasks/unified/{task_id}、成片队列 /scheduled/tasks/{id}、编辑器 /editor/render/{id}。
"""
import os
import time
from datetime import datetime

from config.paths import MG_OUTPUT_DIR
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.template_server_client import download_render_result, poll_render_status


class TemplateRenderWorker(BaseWorker):
    """提交模板生成任务，轮询状态，下载结果。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(str)   # 本地文件路径

    def __init__(self, task_id: str, out_name: str = ""):
        super().__init__()
        self.task_id = task_id
        self.out_name = out_name or f"template_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"  # noqa: E501

    def do_work(self):
        self.phase.emit(f"模板生成任务已提交：{self.task_id}")
        while True:
            time.sleep(2)
            data = poll_render_status(self.task_id)
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
                    download_render_result(output_url, local_path)
                else:
                    # 兜底：统一模板渲染任务可直接用 /templates/render/download/{task_id}
                    from utils.template_server_client import _server_url, render_download
                    base = _server_url()
                    if not base:
                        raise RuntimeError("任务完成但无 output_url，且未配置 compute_server_url")
                    self.phase.emit("正在下载模板成片（统一渲染 download）…")
                    resp = render_download(self.task_id, timeout=120)
                    if resp is not None:
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                    else:
                        raise RuntimeError(f"下载任务 {self.task_id} 结果失败。")
                self.finished.emit(local_path)
                return
            if status in ("failed", "error"):
                msg = data.get("error_msg") or data.get("error") or data.get("message") or "未知错误"  # noqa: E501
                raise RuntimeError(f"模板生成失败：{msg}")
