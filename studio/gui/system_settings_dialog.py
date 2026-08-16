# -*- coding: utf-8 -*-
"""「系统设置」独立窗口：侧边栏底部「 系统设置」入口打开。

主侧边栏不再直接展示系统配置菜单，统一收纳到本窗口的二级菜单：
左侧菜单（模型配置/平台接入/本地配置/环境与维护/扩展插件/关于）+ 右侧页面区。
页面对象仍由主窗口构建（self.page_xxx），首次打开时 reparent 到本窗口的
stack 中，页面内部对 main_window 的引用不受影响；关闭窗口仅隐藏，页面常驻。
"""
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QStackedWidget, QFrame, QPushButton,
    QWidget,
)
from PySide6.QtCore import Qt

from utils.logger_utils import log
from utils.gui_icons import mdi_button

# 菜单项：(显示名, 图标, 主窗口页面索引)
SETTINGS_MENUS = [
    ("模型配置", "cog", 7),
    ("平台接入", "link", 22),
    ("本地配置", "download", 21),
    ("环境与维护", "server", 36),
    ("扩展插件", "puzzle", 43),
    ("任务队列", "format-list-checks", 9),
    ("关于", "information", 6),
]


class SystemSettingsDialog(QDialog):
    """系统设置二级菜单窗口（非模态，页面常驻复用）。"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("系统设置")
        self.resize(1200, 800)
        self.setMinimumSize(980, 660)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左侧菜单面板 ──
        menu_panel = QFrame()
        menu_panel.setObjectName("settings_menu_panel")
        menu_panel.setFixedWidth(200)
        ml = QVBoxLayout(menu_panel)
        ml.setContentsMargins(10, 20, 10, 14)
        ml.setSpacing(4)

        title = QLabel("系统设置")
        title.setObjectName("heading")
        ml.addWidget(title)
        ml.addSpacing(10)

        self._menu_btns = []
        for text, icon, idx in SETTINGS_MENUS:
            btn = mdi_button(text, icon)
            btn.setObjectName("nav_button")
            btn.setProperty("target_index", idx)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, i=idx: self._switch(i))
            ml.addWidget(btn)
            self._menu_btns.append(btn)
        ml.addStretch()
        root.addWidget(menu_panel)

        # ── 右侧页面区（主窗口的系统页面 reparent 进来）──
        self._stack = QStackedWidget()
        self._stack.setObjectName("settings_stack")
        root.addWidget(self._stack, 1)

    # ──────────────────────────── 页面挂载 ────────────────────────────
    def attach_pages(self, main_window):
        """把主窗口的系统页面挂进右侧 stack（首次打开时调用）。

        页面从主窗口 content_stack 迁出时，原位置先插入空占位再移除页面，
        保证主窗口其余页面索引（如工作台 46）不漂移；此后页面常驻本窗口。
        """
        # 关于页是懒加载页面：确保已构建
        if hasattr(main_window, "_ensure_page_built"):
            try:
                main_window._ensure_page_built(6)
            except Exception as e:
                log.warning(f"[系统设置] 关于页构建失败: {e}")
        attr_map = {
            7: "ai_settings", 22: "llm_settings", 21: "voice_samples",
            36: "backup", 43: "extension", 9: "task_list", 6: "about",
        }
        stack = main_window.content_stack
        self._page_index = {}
        for _text, _icon, idx in SETTINGS_MENUS:
            page = getattr(main_window, "page_" + attr_map[idx], None)
            if page is None:
                continue
            # 从主窗口 stack 迁出：先用占位顶住原索引，再移除页面
            pos = stack.indexOf(page)
            if pos >= 0:
                holder = QWidget()
                holder.setObjectName("settings_placeholder")
                stack.insertWidget(pos, holder)
                stack.removeWidget(page)
            self._stack.addWidget(page)
            self._page_index[idx] = self._stack.count() - 1
        # 默认进入模型配置
        self._switch(7)

    # ──────────────────────────── 菜单切换 ────────────────────────────
    def _switch(self, idx):
        pos = self._page_index.get(idx)
        if pos is None:
            return
        self._stack.setCurrentIndex(pos)
        for btn in self._menu_btns:
            active = str(btn.property("target_index")) == str(idx)
            new_val = "true" if active else "false"
            if btn.property("active") != new_val:
                btn.setProperty("active", new_val)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        self._trigger_refresh(idx)

    def _trigger_refresh(self, idx):
        """切换菜单时刷新页面数据（对齐原 trigger_page_logic 对应分支）。"""
        mw = self.main_window
        try:
            if idx == 9:
                if hasattr(mw, "refresh_server_tasks"):
                    mw.refresh_server_tasks()
                if hasattr(mw, "refresh_timer"):
                    mw.refresh_timer.start()
            else:
                if hasattr(mw, "refresh_timer"):
                    mw.refresh_timer.stop()
            if idx == 7 and hasattr(mw, "refresh_llm_page_status"):
                mw.refresh_llm_page_status()
            elif idx == 36:
                if hasattr(mw, "env_config_tool"):
                    mw.env_config_tool.refresh_status()
                if hasattr(mw, "refresh_logs"):
                    mw.refresh_logs()
            elif idx == 21:
                if hasattr(mw, "voice_samples_tool"):
                    mw.voice_samples_tool._load_table_data()
                if hasattr(mw, "_load_lut_config"):
                    mw._load_lut_config()
            elif idx == 43 and hasattr(mw, "extension_tool"):
                mw.extension_tool.refresh()
        except Exception as e:
            log.warning(f"[系统设置] 菜单刷新失败 index={idx}: {e}")

    def closeEvent(self, event):
        """关闭设置窗口时停止任务队列轮询，避免后台继续请求。"""
        mw = self.main_window
        if hasattr(mw, "refresh_timer"):
            mw.refresh_timer.stop()
        super().closeEvent(event)
