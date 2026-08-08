# -*- coding: utf-8 -*-
"""运营模式首页：智能体工作台（一句话需求 + 高频任务卡片 + 最近任务概览）。

P0 落地（PRD 第十二章 12.3）：目标导向入口。运营用户无需理解专业概念，
从首页任务卡片一键直达对应功能页；最近任务概览复用服务端成片任务接口。
"""
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QLineEdit, QFrame, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView, QGridLayout)
from utils.gui_icons import mdi_icon, mdi_button
from utils.logger_utils import log

# 示例需求（点击填入输入框）
# (示例文案, 直达目标页 index)
_ASK_CHIPS = [("带货 15 秒竖屏", 33), ("直播切片", 18), ("声音克隆", 20), ("封面制作", 32)]

# 一句话需求关键词 -> 目标页 index（简单意图路由）
_INTENT_PAGE = [
    (("直播", "切片"), 18),
    (("声音", "克隆", "配音", "音色"), 20),
    (("封面",), 32),
    (("营销",), 40),
    (("评价", "预测", "数据"), 34),
    (("混剪", "拼接", "镜头"), 14),
    (("任务", "进度", "队列"), 42),
]

# (标题, 图标, 描述, 目标页 index)
_TASK_CARDS = [
    ("一键成片", "rocket", "选产品或贴文案，自动配素材配音生成成片", 33),
    ("智能混剪", "cut", "多镜头素材自动拼接成片，支持转场配音", 14),
    ("声音克隆", "mic", "粘贴文案、选音色，克隆整段语音", 20),
    ("直播切片", "video", "从直播回放自动切出精彩片段配字幕", 18),
    ("封面制作", "camera", "输入标题卖点，自动生成视频封面", 32),
    ("营销检测", "sparkles", "上传视频，检查营销卖点是否到位", 40),
    ("视频评价", "film", "预测成片数据表现，给出优化建议", 34),
    ("成片任务", "folder", "查看所有成片/混剪任务进度", 42),
]

_STATUS_TEXT = {
    "pending": "排队中", "queued": "排队中", "waiting": "排队中",
    "running": "进行中", "processing": "进行中",
    "done": "已完成", "success": "已完成", "completed": "已完成",
    "failed": "失败", "error": "失败",
}


class _TaskListThread(QThread):
    """后台加载最近任务，避免阻塞 UI。"""
    done = Signal(list)

    def run(self):
        try:
            from utils.scheduled_task_client import list_tasks
            self.done.emit(list_tasks(timeout=6))
        except Exception as e:
            log.warning(f"运营首页加载最近任务失败: {e}")
            self.done.emit([])


class _TaskCard(QPushButton):
    """任务卡片：图标 + 标题 + 描述，可点击。"""

    def __init__(self, title, icon, desc, parent=None):
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(96)
        self.setStyleSheet(
            "QPushButton { background:#171a21; border:1px solid #262b36; "
            "border-radius:12px; text-align:left; } "
            "QPushButton:hover { border-color:#60a5fa; background:#1a1e28; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(mdi_icon(icon, "#60a5fa").pixmap(20, 20))
        head.addWidget(ico)
        t = QLabel(title)
        t.setStyleSheet("background:transparent; border:none; font-size:14px; font-weight:700; color:#e6e9f0;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("background:transparent; border:none; color:#8b93a3; font-size:12px;")
        lay.addWidget(d)


class AgentHomePage:
    """运营模式智能体工作台首页（P0）。"""

    def __init__(self, parent_widget, main_window):
        self.parent_widget = parent_widget
        self.main_window = main_window
        self._task_thread = None
        self.setup()

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(14)

        heading = QLabel("✨ 螺丝钉智能体工作台")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading)
        sub = QLabel("说一句话，或点一个任务卡片——剩下的交给智能体。")
        sub.setStyleSheet("color:#8b93a3; font-size:13px;")
        layout.addWidget(sub)

        # 一句话需求
        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText("例如：帮我把这段文案做成带货视频，用老怀的声音，竖屏 15 秒")
        self.ask_input.setFixedHeight(40)
        self.ask_input.returnPressed.connect(self._on_ask_go)
        ask_row.addWidget(self.ask_input, 1)
        btn_go = mdi_button("开始", "rocket")
        btn_go.setObjectName("primary_button")
        btn_go.setFixedHeight(40)
        btn_go.clicked.connect(self._on_ask_go)
        ask_row.addWidget(btn_go)
        layout.addLayout(ask_row)

        # 示例 chips
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for text, target in _ASK_CHIPS:
            c = QPushButton(text)
            c.setFixedHeight(28)
            c.setCursor(Qt.PointingHandCursor)
            c.setStyleSheet(
                "QPushButton { background:#1d212b; border:1px solid #262b36; "
                "border-radius:14px; color:#8b93a3; padding:2px 12px; font-size:12px; } "
                "QPushButton:hover { border-color:#60a5fa; color:#60a5fa; }")
            c.clicked.connect(lambda checked=False, t=target: self.main_window.switch_page(t))
            chips.addWidget(c)
        chips.addStretch()
        layout.addLayout(chips)

        # 高频任务卡片
        card_title = QLabel("高频任务")
        card_title.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(card_title)
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (title, icon, desc, idx) in enumerate(_TASK_CARDS):
            card = _TaskCard(title, icon, desc)
            card.clicked.connect(lambda checked=False, i=idx: self.main_window.switch_page(i))
            grid.addWidget(card, i // 4, i % 4)
        layout.addLayout(grid)

        # 最近任务概览
        task_title = QLabel("最近任务")
        task_title.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(task_title)
        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["任务", "类型", "状态", "时间"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.setMaximumHeight(230)
        layout.addWidget(self.task_table, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        btn_tasks = mdi_button("打开成片任务", "folder")
        btn_tasks.setObjectName("secondary_button")
        btn_tasks.clicked.connect(lambda: self.main_window.switch_page(42))
        foot.addWidget(btn_tasks)
        layout.addLayout(foot)

    def refresh_tasks(self):
        """后台加载最近任务（进入页面时由 trigger_page_logic 调用）。"""
        if self._task_thread and self._task_thread.isRunning():
            return
        self._task_thread = _TaskListThread()
        self._task_thread.done.connect(self._on_tasks_loaded)
        self._task_thread.start()

    def _on_tasks_loaded(self, items):
        self.task_table.setRowCount(0)
        for item in (items or [])[:10]:
            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            title = str(item.get("title") or item.get("task_id") or item.get("id") or "")
            ttype = str(item.get("task_type") or item.get("type") or "")
            status = str(item.get("status") or "")
            ts = str(item.get("created_at") or item.get("tm_draft_create") or item.get("create_time") or "")
            self.task_table.setItem(row, 0, QTableWidgetItem(title))
            self.task_table.setItem(row, 1, QTableWidgetItem(ttype))
            self.task_table.setItem(row, 2, QTableWidgetItem(_STATUS_TEXT.get(status, status)))
            self.task_table.setItem(row, 3, QTableWidgetItem(ts))

    def _on_ask_go(self):
        text = self.ask_input.text().strip()
        if not text:
            return
        # 简单意图路由：按关键词落到对应功能页；未命中默认一键成片
        for keys, page in _INTENT_PAGE:
            if any(k in text for k in keys):
                self.main_window.switch_page(page)
                return
        self.main_window.switch_page(33)