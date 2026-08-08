# -*- coding: utf-8 -*-
"""运营工作台首页：一句话需求（LLM 意图路由）+ 高频任务卡片 + 最近任务概览。

一句话需求 → utils.agent_router.route_text()：
  1. 优先 LLM 意图识别（服务端 /llm/chat/completions）；
  2. 超时/失败回退本地关键词匹配；
  3. 返回 (页面 index, tab index) 或标记「多智能体组合任务」。
支持跳页后自动切到目标 Tab（如 素材生成 → 数字人）。
"""
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QLineEdit, QFrame, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView, QGridLayout,
                               QMessageBox, QTabWidget, QWidget)
from utils.gui_icons import mdi_icon, mdi_button, table_action_button
from utils.logger_utils import log
from config.paths import OUTPUTS_DIR
import os

# (示例文案, 直达目标页 index)
_ASK_CHIPS = [("带货 15 秒竖屏", 33), ("直播切片", 18), ("声音克隆", 20), ("封面制作", 32)]

# (标题, 图标, 描述, 目标页 index, 强调色)
_TASK_CARDS = [
    ("一键成片", "rocket", "选产品或贴文案，自动配素材配音生成成片", 33, "#3b82f6"),
    ("智能混剪", "cut", "多镜头素材自动拼接成片，支持转场配音", 14, "#8b5cf6"),
    ("声音克隆", "mic", "粘贴文案、选音色，克隆整段语音", 20, "#d946ef"),
    ("直播切片", "video", "从直播回放自动切出精彩片段配字幕", 18, "#f97316"),
    ("封面制作", "camera", "输入标题卖点，自动生成视频封面", 32, "#06b6d4"),
    ("营销检测", "sparkles", "上传视频，检查营销卖点是否到位", 40, "#10b981"),
    ("视频评价", "film", "预测成片数据表现，给出优化建议", 34, "#f59e0b"),
    ("成片任务", "folder", "查看所有成片/混剪任务进度", 42, "#64748b"),
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


class _IntentThread(QThread):
    """后台执行一句话意图路由（LLM + 关键词兜底），不阻塞 UI。"""
    done = Signal(object)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text

    def run(self):
        try:
            from utils.agent_router import route_text
            self.done.emit(route_text(self._text))
        except Exception as e:
            log.warning(f"意图路由失败: {e}")
            self.done.emit(None)


class _TaskCard(QPushButton):
    """任务卡片：顶部强调色条 + 渐变图标块 + 标题 + 描述，可点击。"""

    def __init__(self, title, icon, desc, accent="#3b82f6", parent=None):
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        self.setStyleSheet(
            f"QPushButton {{"
            f" background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"   stop:0 #1b1f2d, stop:1 #161924);"
            f" border:1px solid #2c3344; border-top:3px solid {accent};"
            f" border-radius:12px; text-align:left; }}"
            f" QPushButton:hover {{"
            f"  border:1px solid {accent}; border-top:3px solid {accent};"
            f"  background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"    stop:0 #202536, stop:1 #1a1e2c); }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(9)
        ico = QLabel()
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"  stop:0 {accent}, stop:1 #334155); border-radius:10px;")
        ico.setPixmap(mdi_icon(icon, "#ffffff").pixmap(22, 22))
        head.addWidget(ico)
        t = QLabel(title)
        t.setStyleSheet("background:transparent; border:none; font-size:15px; font-weight:700; color:#f0f1f7;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("background:transparent; border:none; color:#9aa3b2; font-size:12px; line-height:1.5;")
        lay.addWidget(d)


class AgentHomePage:
    """运营工作台首页（一句话需求 + 高频任务卡片 + 最近任务概览）。"""

    def __init__(self, parent_widget, main_window):
        self.parent_widget = parent_widget
        self.main_window = main_window
        self._task_thread = None
        self._intent_thread = None
        self._ask_go_btn = None
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
        self.ask_input.setPlaceholderText("例如：帮我把这段文案做成带货视频；或：生成一个数字人视频")
        self.ask_input.setFixedHeight(40)
        self.ask_input.returnPressed.connect(self._on_ask_go)
        ask_row.addWidget(self.ask_input, 1)
        btn_go = mdi_button("开始", "rocket")
        btn_go.setObjectName("primary_button")
        btn_go.setFixedHeight(40)
        btn_go.clicked.connect(self._on_ask_go)
        self._ask_go_btn = btn_go
        ask_row.addWidget(btn_go)
        layout.addLayout(ask_row)

        # 示例 chips（点击直达对应功能）
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
            c.clicked.connect(lambda checked=False, t=target: self._goto(t))
            chips.addWidget(c)
        chips.addStretch()
        layout.addLayout(chips)

        # 高频任务卡片
        card_title = QLabel("高频任务")
        card_title.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(card_title)
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (title, icon, desc, idx, accent) in enumerate(_TASK_CARDS):
            card = _TaskCard(title, icon, desc, accent)
            card.clicked.connect(lambda checked=False, i=idx: self._goto(i))
            grid.addWidget(card, i // 4, i % 4)
        layout.addLayout(grid)

        # 最近任务概览
        task_title = QLabel("最近任务")
        task_title.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(task_title)
        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["任务", "类型", "状态", "时间", "操作"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.setMaximumHeight(230)
        # 双击任务行 = 播放成片结果（与操作列播放按钮同逻辑，安全兜底）
        self.task_table.cellDoubleClicked.connect(self._on_task_double_clicked)
        layout.addWidget(self.task_table, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        btn_tasks = mdi_button("打开成片任务", "folder")
        btn_tasks.setObjectName("secondary_button")
        btn_tasks.clicked.connect(lambda: self._goto(42))
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
            if not isinstance(item, dict):
                continue
            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            title = str(item.get("title") or item.get("task_id") or item.get("id") or "")
            ttype = str(item.get("task_type") or item.get("type") or "")
            status = str(item.get("status") or "")
            ts = str(item.get("created_at") or item.get("tm_draft_create") or item.get("create_time") or "")[:19]
            # 任务名 item 携带完整任务数据（供双击播放/操作列使用）
            name_item = QTableWidgetItem(title)
            name_item.setData(Qt.UserRole, item)
            self.task_table.setItem(row, 0, name_item)
            self.task_table.setItem(row, 1, QTableWidgetItem(ttype))
            self.task_table.setItem(row, 2, QTableWidgetItem(_STATUS_TEXT.get(status, status)))
            self.task_table.setItem(row, 3, QTableWidgetItem(ts))
            self.task_table.setCellWidget(row, 4, self._make_play_widget(item))

    # ── 最近任务：播放成片结果 ───────────────────────────────────────────
    def _make_play_widget(self, task):
        """操作列：已完成且有成片结果 → 播放按钮；否则显示占位文案。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        status = str(task.get("status") or "")
        result = task.get("result") or {}
        video_url = result.get("video_url") or result.get("url") or ""
        if status in ("done", "success", "completed") and video_url:
            btn = table_action_button("▶", "播放成片结果")
            btn.clicked.connect(lambda _=False, t=task: self._play_task(t))
            lay.addWidget(btn)
        else:
            text = "未完成" if status not in ("done", "success", "completed", "failed", "error") else "无结果"
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#5b6472; font-size:12px;")
            lay.addWidget(lbl)
        return w

    def _on_task_double_clicked(self, row, _col):
        """双击任务行：尝试播放该任务成片结果。"""
        name_item = self.task_table.item(row, 0)
        if not name_item:
            return
        task = name_item.data(Qt.UserRole)
        if isinstance(task, dict):
            self._play_task(task)

    def _play_task(self, task):
        """播放任务成片结果：本地文件走默认播放器，服务端相对路径拼完整地址。

        全流程 try/except 兜底，播放失败只提示不崩溃。
        """
        try:
            result = task.get("result") or {}
            video_url = result.get("video_url") or result.get("url") or ""
            if not video_url:
                QMessageBox.information(self.parent_widget, "提示", "该任务暂无成片结果，无法播放。")
                return
            if not isinstance(video_url, str):
                video_url = str(video_url)
            target = video_url
            if video_url.startswith("/"):
                # 服务端相对路径 → 拼服务端地址
                from utils.scheduled_task_client import _server_url
                target = _server_url() + video_url
            elif not video_url.startswith(("http://", "https://")):
                # 本地相对路径 → 优先按输出目录解析；不存在则保持原样交给系统
                local = os.path.join(OUTPUTS_DIR, video_url)
                target = local if os.path.isfile(local) else video_url
            if os.name == "nt":
                os.startfile(target)  # noqa: 本地文件→默认播放器，URL→默认浏览器
            else:
                import webbrowser
                webbrowser.open(target)
            log.info(f"[工作台] 播放任务结果: {target}")
        except Exception as e:
            log.warning(f"[工作台] 播放任务结果失败: {e}")
            QMessageBox.warning(self.parent_widget, "播放失败", f"无法播放该任务结果：{e}")

    # ── 一句话需求路由 ─────────────────────────────────────
    def _on_ask_go(self):
        text = self.ask_input.text().strip()
        if not text:
            return
        if self._intent_thread and self._intent_thread.isRunning():
            return
        self._intent_thread = _IntentThread(text)
        self._intent_thread.done.connect(self._on_intent_ready)
        self._intent_thread.start()
        if self._ask_go_btn is not None:
            self._ask_go_btn.setEnabled(False)
            self._ask_go_btn.setText("⏳ 识别中...")

    def _on_intent_ready(self, result):
        if self._ask_go_btn is not None:
            self._ask_go_btn.setEnabled(True)
            self._ask_go_btn.setText("开始")
        if not result:
            return
        if result.get("multi_agent"):
            QMessageBox.information(
                self.parent_widget,
                "智能体编排",
                "这条需求需要组合多个能力（例如：数字人 + 配音 + 成片 + 封面）。\n"
                "多智能体编排正在规划中（P2），先带你去最相关的入口。",
            )
        self._goto(result.get("page", 33), result.get("tab"))

    def _goto(self, page, tab=None):
        """跳转到指定页面，若目标页有 Tab 则自动切到对应 Tab。"""
        self.main_window.switch_page(page)
        if tab is not None:
            QTimer.singleShot(0, lambda: self._activate_tab(page, tab))

    def _activate_tab(self, page, tab):
        try:
            w = self.main_window.content_stack.widget(page)
            if w is None:
                return
            tabs = w.findChild(QTabWidget)
            if tabs is not None and 0 <= tab < tabs.count():
                tabs.setCurrentIndex(tab)
        except Exception as e:
            log.warning(f"激活页面 Tab 失败: {e}")