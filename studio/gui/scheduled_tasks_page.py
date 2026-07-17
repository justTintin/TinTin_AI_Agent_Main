# -*- coding: utf-8 -*-
"""
定时任务页：监控服务端 /scheduled/tasks 的执行状态与输出结果。

架构（thin client）：
- 任务的存储/调度/执行全部在服务端，本页只 GET 列表 + 展示状态/结果 + 删除
- 后台轮询 Worker 每 N 秒刷新一次（任务进行中时自动更新 progress/status）
- 「立即运行」= 提交一个立即执行的任务（task_type=video_montage）给服务端

服务端任务字段：id, task_type, title, params, status, progress, error_msg,
                result({video_url}), created_at, updated_at, completed_at
"""
import os

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextBrowser, QWidget,
)
from PySide6.QtCore import Qt, QTimer

from gui.base_page import BasePage
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from utils import scheduled_task_client as stc


class ScheduledTasksPage(BasePage):
    """定时任务监控页（数据来自服务端 /scheduled/tasks）。"""

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        heading = QLabel("⏰ 成片任务")
        heading.setObjectName("heading")
        root.addWidget(heading)
        sub = QLabel("监控服务端成片任务（产品成片 / 脚本成片）的执行状态与输出结果。任务由服务端调度执行，客户端仅提交与监控。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 任务列表 ───────────────────────────────────────────────────────
        list_card = QFrame(); list_card.setObjectName("card")
        ll = QVBoxLayout(list_card); ll.setContentsMargins(12, 10, 12, 10); ll.setSpacing(8)

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("📋 成片任务列表（来自服务端）"))
        list_header.addStretch()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self.refresh)
        list_header.addWidget(self.btn_refresh)
        ll.addLayout(list_header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "标题", "类型", "状态", "进度", "创建时间", "操作"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_row_clicked)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # ID
        h.setSectionResizeMode(1, QHeaderView.Stretch)             # 标题
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)   # 类型
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)   # 状态
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # 进度
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)   # 时间
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # 操作
        ll.addWidget(self.table)
        root.addWidget(list_card, 2)

        # ── 选中任务详情 ───────────────────────────────────────────────────
        detail_card = QFrame(); detail_card.setObjectName("card")
        dl = QVBoxLayout(detail_card); dl.setContentsMargins(12, 10, 12, 10); dl.setSpacing(6)
        dl.addWidget(QLabel("🔍 任务详情（参数 / 结果）"))
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumHeight(120)
        self.detail.setPlaceholderText("点击上方任务行查看其参数与执行结果…")
        dl.addWidget(self.detail, 1)
        root.addWidget(detail_card, 1)

        # ── 自动轮询定时器：任务进行中时每 5 秒刷新 ────────────────────────
        self._poll_timer = QTimer(self.parent_widget)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self.refresh)

        # 首次加载
        self.refresh()

    # ── 数据刷新（调服务端）──────────────────────────────────────────────
    def refresh(self):
        """从服务端拉取任务列表并刷新表格。"""
        items = stc.list_tasks()
        self.table.setRowCount(len(items))
        self.table.clearContents()
        has_active = False  # 是否有 pending/running 任务（决定是否继续轮询）
        for i, t in enumerate(items):
            tid = t.get("id", "")
            status = t.get("status", "")
            # ID
            self.table.setItem(i, 0, QTableWidgetItem(str(tid)))
            # 标题
            name_item = QTableWidgetItem(t.get("title", "") or "—")
            name_item.setData(Qt.UserRole, tid)
            self.table.setItem(i, 1, name_item)
            # 类型
            self.table.setItem(i, 2, QTableWidgetItem(self._type_label(t.get("task_type", ""))))
            # 状态（带颜色）
            status_item = QTableWidgetItem(self._status_label(status))
            status_item.setForeground(self._status_color(status))
            self.table.setItem(i, 3, status_item)
            # 进度
            self.table.setItem(i, 4, QTableWidgetItem(f"{t.get('progress', 0)}%"))
            # 创建时间
            self.table.setItem(i, 5, QTableWidgetItem(self._fmt_time(t.get("created_at"))))
            # 操作列：查看结果/下载（completed）+ 删除
            self.table.setCellWidget(i, 6, self._make_ops_widget(t))
            if status in ("pending", "running"):
                has_active = True

        self.detail.setMarkdown("*点击任务行查看参数与结果*")
        # 有进行中任务 → 启动轮询；否则停止
        if has_active and not self._poll_timer.isActive():
            self._poll_timer.start()
        elif not has_active and self._poll_timer.isActive():
            self._poll_timer.stop()

    def _on_row_clicked(self, row, _col):
        name_item = self.table.item(row, 1)
        if not name_item:
            return
        tid = name_item.data(Qt.UserRole)
        t = stc.get_task(tid)
        if t:
            self.detail.setMarkdown(self._render_detail(t))

    def _render_detail(self, t):
        params = t.get("params", {}) or {}
        result = t.get("result", {}) or {}
        lines = [
            f"### {t.get('title', '')}",
            "",
            f"- **任务 ID**：{t.get('id')}",
            f"- **类型**：{self._type_label(t.get('task_type', ''))}",
            f"- **状态**：{self._status_label(t.get('status', ''))}（{t.get('progress', 0)}%）",
            f"- **创建**：{self._fmt_time(t.get('created_at'))}",
            f"- **完成**：{self._fmt_time(t.get('completed_at'))}",
        ]
        if t.get("error_msg"):
            lines.append(f"- **错误**：`{t.get('error_msg')}`")
        if result:
            lines.append(f"- **结果**：`{result}`")
        lines += ["", "#### 参数"]
        if params:
            for k, v in params.items():
                vs = str(v)
                if len(vs) > 80:
                    vs = vs[:80] + "…"
                lines.append(f"- **{k}**：{vs}")
        else:
            lines.append("（无）")
        return "\n".join(lines)

    # ── 操作列 ────────────────────────────────────────────────────────────
    def _make_ops_widget(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(4)
        status = t.get("status", "")
        result = t.get("result", {}) or {}
        # 完成且有 video_url → 「下载/打开」按钮
        video_url = result.get("video_url") or result.get("url")
        if status == "completed" and video_url:
            btn_open = QPushButton("打开结果")
            btn_open.setObjectName("secondary_button")
            btn_open.setFixedWidth(72)
            btn_open.clicked.connect(lambda _=False, u=video_url: self._open_result(u))
            lay.addWidget(btn_open)
        btn_del = QPushButton("删除")
        btn_del.setFixedWidth(44)
        btn_del.clicked.connect(lambda _=False, tid=t.get("id"): self._delete(tid))
        lay.addWidget(btn_del)
        return w

    def _open_result(self, video_url):
        """打开服务端返回的成片结果。video_url 是相对路径，拼到服务端地址。"""
        from utils.scheduled_task_client import _server_url
        full = video_url
        if video_url.startswith("/"):
            full = _server_url() + video_url
        try:
            if os.name == "nt":
                os.startfile(full)  # noqa
            else:
                import webbrowser
                webbrowser.open(full)
        except Exception as e:
            self.show_error(f"打开结果失败：{e}\n地址：{full}", "错误")

    def _delete(self, tid):
        if not self.confirm(f"确定删除任务 {tid}？"):
            return
        if stc.delete_task(tid):
            self.refresh()
        else:
            self.show_warning("删除失败，请检查服务端连接。")

    # ── 页面切换钩子：进入页面时刷新 + 启动轮询 ──────────────────────────
    def on_page_enter(self):
        """由 MainWindow 切换到本页时调用（若接入了）。"""
        self.refresh()

    # ── 格式化 helper ─────────────────────────────────────────────────────
    @staticmethod
    def _type_label(t):
        return {"video_montage": "产品成片", "compile_video": "产品成片",
                "storyboard_montage": "脚本成片",
                "script_montage": "脚本成片"}.get(t, t or "—")

    @staticmethod
    def _status_label(s):
        return {"pending": "排队中", "running": "执行中", "completed": "已完成",
                "failed": "失败"}.get(s, s or "—")

    @staticmethod
    def _status_color(s):
        from PySide6.QtGui import QColor
        return {"running": QColor("#f39c12"), "completed": QColor("#2ecc71"),
                "failed": QColor("#e74c3c"), "pending": QColor("#888")}.get(s, QColor("#aaa"))

    @staticmethod
    def _fmt_time(s):
        """服务端返回 '2026-07-18 00:19:37.114321'，截到分钟。"""
        if not s:
            return "—"
        return str(s)[:16]
