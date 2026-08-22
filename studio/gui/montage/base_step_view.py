# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QWidget

class BaseStepView(QWidget):
    """智能混剪四步骤的通用 UI 基类"""
    def __init__(self, main_page):
        """
        :param main_page: 传入主页面 VideoMontagePage 的引用，用以分发导航和共享状态
        """
        super().__init__(main_page.parent_widget)
        self.main_page = main_page

    def on_enter(self):
        """进入该步骤页面时的生命周期回调"""
        pass

    def on_leave(self):
        """离开该步骤页面（切换到其它步骤）时的生命周期回调"""
        pass
