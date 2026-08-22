# -*- coding: utf-8 -*-
"""
所有后台 QThread 任务的统一基类。

项目里有 40+ 个 QThread 子类，普遍重复着同一套样板：
    error = Signal(str)
    def run(self):
        try: ...业务...
        except Exception as e: self.error.emit(str(e))

BaseWorker 把这套收敛起来：
- 统一提供 `error = Signal(str)` 信号（子类不必再各自声明）。
- 提供 `run()` 模板：自动 try/except，异常时记日志并 emit error。
  **新 worker 只需实现 `do_work()`**，并自定义所需的 `finished` 信号（类型各异，保留在子类）。
- 旧 worker 迁移时若保留自己的 `run()`，会自然覆盖模板、行为不变，仍统一到本基类下。

注意：各业务的 `finished` 信号载荷类型不同（str / list / dict / 多参…），
因此 finished 不在基类声明，由子类按需定义。
"""
from PySide6.QtCore import QThread, Signal

from utils.logger_utils import log


class BaseWorker(QThread):
    error = Signal(str)

    def run(self):
        try:
            self.do_work()
        except Exception as e:
            log.error(f"{type(self).__name__} 执行失败: {e}")
            self.error.emit(str(e))

    def do_work(self):
        raise NotImplementedError("BaseWorker 子类需实现 do_work() 或重写 run()")
