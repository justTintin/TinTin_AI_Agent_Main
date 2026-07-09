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


def _hide_widget_tree(widget):
    """递归隐藏一个 widget 及其所有子孙控件"""
    if widget is None:
        return
    widget.setVisible(False)
    children = widget.findChildren(QWidget) if hasattr(widget, "findChildren") else []
    for child in children:
        child.setVisible(False)


def _show_dev_only(parent_widget):
    """隐藏页面原有所有子控件，并在布局中插入居中的'开发中'提示（独立函数，供非BasePage的inline页面使用）"""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from PySide6.QtCore import Qt
    if parent_widget is None:
        return
    layout = parent_widget.layout()
    if layout is None:
        return
    # 递归隐藏原有布局中所有子控件及其子孙（不销毁，保留原界面以便恢复）
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item else None
        if w is not None:
            _hide_widget_tree(w)
    # 构建提示卡片：透明背景融入页面，无色块
    card = QWidget()
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(48, 40, 48, 40)
    card_layout.setSpacing(12)
    icon = QLabel("🚧")
    icon.setAlignment(Qt.AlignCenter)
    icon.setStyleSheet("font-size: 48px; background: transparent; border: none;")
    card_layout.addWidget(icon)
    title = QLabel("该功能正在开发中")
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-size: 20px; font-weight: bold; color: #9E9E9E; background: transparent; border: none;")
    card_layout.addWidget(title)
    subtitle = QLabel("敬请期待")
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setStyleSheet("font-size: 14px; color: #BDBDBD; background: transparent; border: none;")
    card_layout.addWidget(subtitle)
    # 插入到原布局，居中显示
    layout.addWidget(card, 0, Qt.AlignCenter)


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
