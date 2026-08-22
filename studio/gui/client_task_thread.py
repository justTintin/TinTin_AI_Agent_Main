"""客户端任务下发闭环线程：周期领取 → 执行 → 上报。

配合 utils.client_task_worker：GET /tasks/assigned/{machine_id} 领取，
执行下载任务（打开客户端素材浏览器引导用户下载）后
POST /tasks/{task_id}/report 上报结果。
"""
import time

from PySide6.QtCore import QThread, Signal
from utils import client_task_worker as ctw
from utils.logger_utils import log


class ClientTaskWorker(QThread):
    """周期轮询领取客户端任务并执行。"""

    task_picked = Signal(dict)          # 领取到任务
    progress = Signal(str)              # 执行过程日志
    task_done = Signal(str, bool)       # (task_id, 上报成功?)

    def __init__(self, machine_id=None, parent=None, poll_interval=5):
        super().__init__(parent)
        self.machine_id = machine_id or ctw._machine_id()
        self.poll_interval = poll_interval
        self.running = True

    def run(self):
        log.info(f"[客户端任务] 领取循环启动 machine_id={self.machine_id} "
                 f"interval={self.poll_interval}s")
        while self.running:
            try:
                tasks = ctw.pickup_tasks(self.machine_id)
            except Exception as e:  # 外部API调用（任务领取 HTTP 请求）
                log.warning(f"[客户端任务] 领取异常: {e}")
                tasks = []
            for task in tasks:
                if not self.running:
                    return
                task_id = (task or {}).get("task_id") or ""
                if not task_id:
                    continue
                self.task_picked.emit(task)
                res = ctw.execute_task(task, on_log=self.progress.emit)
                ok = False
                if res.get("ok"):
                    ok = ctw.report_task(
                        task_id, self.machine_id, status="ok",
                        file_path=res.get("file_path"))
                else:
                    ok = ctw.report_task(
                        task_id, self.machine_id, status="failed",
                        error=res.get("error") or "执行失败")
                self.task_done.emit(task_id, ok)
            # 轮询间隔（可被 stop 打断）
            for _ in range(int(self.poll_interval * 2)):
                if not self.running:
                    return
                time.sleep(0.5)

    def stop(self):
        self.running = False
