"""QTabWidget → QTabBar + QStackedWidget 兼容层。

用法：
    from gui._tab_compat import TabWidgetCompat, setup_tab_widget

    # 替换前：
    self.tabs = QTabWidget()
    self.tabs.addTab(page1, "Tab 1")
    self.tabs.addTab(page2, "Tab 2")
    layout.addWidget(self.tabs, 1)

    # 替换后：
    self._tab_bar, self._stack, self.tabs = setup_tab_widget(layout, 1)
    self._tab_bar.addTab("Tab 1")
    self._stack.addWidget(page1)
    self._tab_bar.addTab("Tab 2")
    self._stack.addWidget(page2)
"""
from PySide6.QtWidgets import QStackedWidget, QTabBar, QVBoxLayout, QWidget


class TabWidgetCompat:
    """QTabWidget 的极简兼容层，底层用 QTabBar + QStackedWidget。

    仅实现项目中使用的 API 子集：addTab / setCurrentWidget /
    setCurrentIndex / currentIndex / count / tabText / setDocumentMode /
    indexOf / currentChanged。
    """

    def __init__(self, tab_bar: QTabBar, stack: QStackedWidget):
        self._bar = tab_bar
        self._stack = stack
        self.currentChanged = tab_bar.currentChanged
        tab_bar.currentChanged.connect(stack.setCurrentIndex)

    def addTab(self, widget, text):  # noqa: N802
        self._bar.addTab(text)
        self._stack.addWidget(widget)

    def setCurrentWidget(self, widget):  # noqa: N802
        idx = self._stack.indexOf(widget)
        if idx >= 0:
            self._bar.setCurrentIndex(idx)

    def setCurrentIndex(self, index):  # noqa: N802
        self._bar.setCurrentIndex(index)

    def currentIndex(self):  # noqa: N802
        return self._bar.currentIndex()

    def count(self):
        return self._bar.count()

    def tabText(self, index):  # noqa: N802
        return self._bar.tabText(index)

    def setDocumentMode(self, v):  # noqa: N802
        self._bar.setDocumentMode(v)

    def indexOf(self, widget):  # noqa: N802
        return self._stack.indexOf(widget)

    def setTabsClosable(self, v):  # noqa: N802
        pass


def setup_tab_widget(parent_layout, stretch=0):
    """在父布局中创建 QTabBar + QStackedWidget 组合，替代 QTabWidget。

    返回 (tab_bar, stack, compat) 三元组，其中 compat 可作为 QTabWidget 的
    直接替身（支持 addTab / setCurrentIndex 等常用方法）。
    """
    container = QWidget()
    cl = QVBoxLayout(container)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)

    tab_bar = QTabBar()
    tab_bar.setDocumentMode(True)
    cl.addWidget(tab_bar)

    stack = QStackedWidget()
    cl.addWidget(stack, 1)

    parent_layout.addWidget(container, stretch)

    compat = TabWidgetCompat(tab_bar, stack)
    return tab_bar, stack, compat
