from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.logger_utils import log


class TaskWorker(BaseWorker):
    finished = Signal(object)
    progress = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        log.info(f"TaskWorker thread started for: {self.func.__name__}")
        try:
            result = self.func(*self.args, **self.kwargs)
            log.success(f"Task {self.func.__name__} finished successfully.")
            self.finished.emit(result)
        except Exception as e:
            log.exception(f"Error in TaskWorker thread ({self.func.__name__}): {e}")
            self.error.emit(str(e))
