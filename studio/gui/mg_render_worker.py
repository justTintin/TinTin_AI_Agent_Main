"""
MG 动画服务端渲染 Worker（按 OpenAPI /mg/generate + /mg/status + /mg/result 实现）。
"""
import os
import time
from datetime import datetime

from config.paths import MG_OUTPUT_DIR
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.http_download_utils import download_file
from utils.mg_server_client import _ensure_url, download_mg_result, get_mg_status, submit_mg_task


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
                filename = f"mg_{self.request.get('template', 'scene')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"  # noqa: E501
                local_path = os.path.join(MG_OUTPUT_DIR, filename)
                self.phase.emit("正在下载 MG 成片…")
                try:
                    if output_url:
                        full = _ensure_url(output_url)
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        if not download_file(full, local_path, timeout=120, stream=True):  # noqa: E501
                            raise RuntimeError(f"下载失败 HTTP: {full}")
                    else:
                        download_mg_result(self.task_id, local_path)
                except Exception as e:  # 外部API调用（MG 成片下载涉及 HTTP + 文件 I/O）
                    raise RuntimeError(f"下载 MG 成片失败：{e}") from e
                self.finished.emit(local_path)
                return
            if status in ("failed", "error"):
                msg = data.get("error_msg") or data.get("error") or data.get("message") or "未知错误"  # noqa: E501
                raise RuntimeError(f"MG 渲染失败：{msg}")
