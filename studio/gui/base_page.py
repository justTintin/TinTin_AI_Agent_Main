# -*- coding: utf-8 -*-
"""
所有功能页的公共基类。

本项目的页面是「装饰一个 QWidget 容器」的控制器类，统一约定：
    XxxPage(parent_widget, main_window).setup()

BasePage 收敛了各页重复的构造样板，并提供通用能力：
- self.parent_widget / self.main_window
- ai_config 访问
- 统一的消息框 / 确认框（自动挂在 parent_widget 上）
- track_worker：持有 QThread 引用，防止其被 GC 提前回收
- log 快捷方法

子类只需实现 setup()。若子类重写 __init__，请调用 super().__init__(parent_widget, main_window)。
"""
from PySide6.QtWidgets import QMessageBox

from utils.logger_utils import log


def _show_dev_only(parent_widget):
    """清空页面原有内容，只显示'开发中'提示（独立函数，供非BasePage的inline页面使用）"""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from PySide6.QtCore import Qt
    if parent_widget is None:
        return
    # 移除旧布局及其所有子控件
    old_layout = parent_widget.layout()
    if old_layout is not None:
        QWidget().setLayout(old_layout)  # 将旧布局转移给临时对象，Qt 随即回收
    # 新建只含提示的布局
    layout = QVBoxLayout(parent_widget)
    layout.setContentsMargins(40, 40, 40, 40)
    layout.addStretch()
    banner = QLabel("🚧 该功能正在开发中，敬请期待")
    banner.setObjectName("dev_banner")
    banner.setAlignment(Qt.AlignCenter)
    banner.setStyleSheet("""
        QLabel#dev_banner {
            background-color: #FFF3CD;
            color: #856404;
            padding: 20px 32px;
            border-radius: 8px;
            font-size: 18px;
            font-weight: bold;
        }
    """)
    layout.addWidget(banner, alignment=Qt.AlignCenter)
    layout.addStretch()


class BasePage:
    def __init__(self, parent_widget, main_window):
        self.parent_widget = parent_widget
        self.main_window = main_window
        self._workers = []

    def setup(self):
        raise NotImplementedError("页面必须实现 setup() 构建界面")

    # ---------- 配置 ----------
    @property
    def ai_config(self):
        return getattr(self.main_window, "ai_config", {}) or {}

    # ---------- 消息框 ----------
    def show_info(self, message, title="提示"):
        QMessageBox.information(self.parent_widget, title, message)

    def show_warning(self, message, title="提示"):
        QMessageBox.warning(self.parent_widget, title, message)

    def show_error(self, message, title="错误"):
        QMessageBox.critical(self.parent_widget, title, message)

    def confirm(self, message, title="确认"):
        return QMessageBox.question(
            self.parent_widget, title, message,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes

    # ---------- 线程 ----------
    def track_worker(self, worker):
        """持有 worker 引用防止被 GC；worker 结束后自动移除。返回 worker 本身。"""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        return worker

    # ---------- 日志 ----------
    def log_info(self, msg):
        log.info(msg)

    def log_error(self, msg):
        log.error(msg)

    # ---------- 开发中提示 ----------
    def _show_dev_only(self):
        """清空页面原有内容，只显示'开发中'提示"""
        _show_dev_only(self.parent_widget)
