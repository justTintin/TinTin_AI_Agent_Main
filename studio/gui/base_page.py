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
import traceback

from PySide6.QtWidgets import QMessageBox
from utils.logger_utils import log


def _show_dev_only(parent_widget):
    """隐藏页面原有所有子控件，并在布局中插入居中的'开发中'提示。

    会把调用栈打到 app.log（[_show_dev_only] 关键字），便于定位谁在触发。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    # 记录调用栈以便定位谁在误调用「开发中」提示
    stack = traceback.format_list(traceback.extract_stack()[:-1])
    log.info("[_show_dev_only] 被调用，parent_widget=%s\n调用栈:\n%s",
             parent_widget, "".join(stack))
    if parent_widget is None:
        return
    layout = parent_widget.layout()
    if layout is None:
        # 父控件没有布局时自动创建，否则后续无法放置错误卡片
        layout = QVBoxLayout(parent_widget)
        log.info("[_show_dev_only] parent_widget 无布局，已自动创建 QVBoxLayout")
    # 递归隐藏原有所有子控件（不销毁，保留原界面以便恢复）
    for child in parent_widget.findChildren(QWidget):
        child.setVisible(False)
    # 清空原布局 (removeItem 不删除 widget，原控件仍由 page 对象持有)
    while layout.count():
        layout.takeAt(0)
    # 上下 stretch + 卡片居中
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    card = QWidget()
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(0, 0, 0, 0)
    card_layout.setSpacing(12)
    icon = QLabel("")
    icon.setAlignment(Qt.AlignCenter)
    icon.setObjectName("dev_icon")
    card_layout.addWidget(icon)
    title = QLabel("该功能正在开发中")
    title.setAlignment(Qt.AlignCenter)
    title.setObjectName("dev_title")
    card_layout.addWidget(title)
    subtitle = QLabel("敬请期待")
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setObjectName("dev_subtitle")
    card_layout.addWidget(subtitle)
    layout.addWidget(card, 0, Qt.AlignCenter)
    layout.addStretch(1)


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
        # 用统一 ErrorDialog（可滚动 + 复制日志），替代 QMessageBox.critical
        # 避免长错误信息（traceback/多失败项/接口响应）撑满屏幕、无法滚动、无法复制
        from gui.error_dialog import show_error_dialog
        show_error_dialog(self.parent_widget, title, message)

    def confirm(self, message, title="确认"):
        return QMessageBox.question(
            self.parent_widget, title, message,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes

    # ---------- 线程 ----------
    def track_worker(self, worker):
        """持有 worker 引用防止被 GC；worker 结束后自动移除。返回 worker 本身。"""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)  # noqa: E501
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
