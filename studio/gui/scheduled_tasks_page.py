# -*- coding: utf-8 -*-
"""
定时任务页：监控「一键成片」等定时任务的状态、完成情况、参数配置。

布局：
    任务列表（QTableWidget: 名称/动作/调度/状态/上次/下次/操作）
    + 选中任务详情（QTextBrowser 显示参数）

数据来自 ScheduledTaskManager（data/scheduled_tasks.json）。
任务的实际执行（到点触发）由 MainWindow._on_scheduled_task_due 处理：
切到一键成片页 + 填参 + 执行；本页只负责展示与手动管理（启用/禁用/立即运行/删除）。

注：应用内置调度，需保持应用运行；应用关闭后任务不会执行。
"""
import os
import json

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextBrowser, QWidget,
)
from PySide6.QtCore import Qt

from gui.base_page import BasePage
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from utils.scheduled_task_manager import (
    ScheduledTaskManager, SCHEDULE_MODES, WEEKDAY_NAMES,
    format_next_run, format_last_run,
)


class ScheduledTasksPage(BasePage):
    """定时任务监控页。
    外部（MainWindow）在调度线程触发任务、或执行完成后，可调 refresh() 刷新列表。
    注：BasePage 不继承 QObject，故页面间通信用直接调用 main_window 方法（项目惯例）。"""

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._mgr = ScheduledTaskManager()

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        heading = QLabel("⏰ 定时任务")
        heading.setObjectName("heading")
        root.addWidget(heading)
        sub = QLabel("监控「一键成片」定时任务的状态与参数。到点会自动切到「一键成片」页执行。"
                     "⚠ 需保持应用运行，应用关闭后任务不会执行。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 任务列表 ───────────────────────────────────────────────────────
        list_card = QFrame(); list_card.setObjectName("card")
        ll = QVBoxLayout(list_card); ll.setContentsMargins(12, 10, 12, 10); ll.setSpacing(8)

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("📋 任务列表"))
        list_header.addStretch()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self.refresh)
        list_header.addWidget(self.btn_refresh)
        ll.addLayout(list_header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["名称", "动作", "调度", "状态", "上次执行", "下次执行", "操作"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_row_clicked)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)       # 名称
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # 动作
        h.setSectionResizeMode(2, QHeaderView.Stretch)       # 调度
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # 状态
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # 上次
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # 下次
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # 操作
        ll.addWidget(self.table)
        root.addWidget(list_card, 2)

        # ── 选中任务详情 ───────────────────────────────────────────────────
        detail_card = QFrame(); detail_card.setObjectName("card")
        dl = QVBoxLayout(detail_card); dl.setContentsMargins(12, 10, 12, 10); dl.setSpacing(6)
        dl.addWidget(QLabel("🔍 任务参数详情"))
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumHeight(120)
        self.detail.setPlaceholderText("点击上方任务行查看其完整参数配置…")
        dl.addWidget(self.detail, 1)
        root.addWidget(detail_card, 1)

        self.refresh()

    # ── 数据刷新 ──────────────────────────────────────────────────────────
    def refresh(self):
        """重新加载 scheduled_tasks.json 并刷新表格。"""
        self._mgr.load()
        items = self._mgr.all_items()
        self.table.setRowCount(len(items))
        self.table.clearContents()
        for i, t in enumerate(items):
            sch = t.get("schedule", {}) or {}
            # 名称
            name_item = QTableWidgetItem(t.get("name", ""))
            name_item.setData(Qt.UserRole, t.get("id"))
            self.table.setItem(i, 0, name_item)
            # 动作
            self.table.setItem(i, 1, QTableWidgetItem(self._action_label(t.get("action", ""))))
            # 调度描述
            self.table.setItem(i, 2, QTableWidgetItem(self._schedule_desc(sch)))
            # 状态（带颜色）
            status = t.get("status", "idle")
            status_item = QTableWidgetItem(self._status_label(status))
            status_item.setForeground(self._status_color(status))
            self.table.setItem(i, 3, status_item)
            # 上次/下次
            self.table.setItem(i, 4, QTableWidgetItem(format_last_run(t.get("last_run", 0))))
            self.table.setItem(i, 5, QTableWidgetItem(format_next_run(t.get("next_run", 0))))
            # 操作列：启用/禁用 + 立即运行 + 删除
            self.table.setCellWidget(i, 6, self._make_ops_widget(t))
        # 清空详情
        self.detail.setMarkdown("*点击任务行查看参数详情*")

    # ── 行点击：显示详情 ──────────────────────────────────────────────────
    def _on_row_clicked(self, row, _col):
        name_item = self.table.item(row, 0)
        if not name_item:
            return
        tid = name_item.data(Qt.UserRole)
        t = self._mgr.get(tid)
        if not t:
            return
        self.detail.setMarkdown(self._render_detail(t))

    def _render_detail(self, t):
        """把一条任务渲染成 Markdown 文本。"""
        sch = t.get("schedule", {}) or {}
        params = t.get("params", {}) or {}
        lines = [
            f"### {t.get('name', '')}",
            "",
            f"- **动作**：{self._action_label(t.get('action', ''))}",
            f"- **状态**：{self._status_label(t.get('status', 'idle'))}",
            f"- **调度**：{self._schedule_desc(sch)}",
            f"- **启用**：{'是' if sch.get('enabled', True) else '否'}",
            f"- **上次执行**：{format_last_run(t.get('last_run', 0))}",
            f"- **下次执行**：{format_next_run(t.get('next_run', 0))}",
            f"- **上次结果**：{t.get('last_result', '') or '—'}",
            "",
            "#### 任务参数",
            f"- **产品**：{params.get('product_label', '') or params.get('product_id', '—')}",
            f"- **素材目录**：{params.get('folder', '') or '（自动匹配）'}",
            f"- **配音音频**：{params.get('audio', '') or '无'}",
            f"- **封面**：{params.get('cover', '') or '无'}",
            f"- **开场视频**：{params.get('intro', '') or '无'}",
            f"- **比例**：{params.get('ratio', '9:16')}",
            f"- **视频条数**：{params.get('count', 1)}",
            f"- **每张时长**：{params.get('per_dur', 3.0)} 秒",
            f"- **视频总时长**：{params.get('total_dur', 0.0)} 秒",
            f"- **预测平台**：{params.get('predict_platform', '抖音')}",
            f"- **字幕文案**：{(params.get('subtitle', '') or '无')[:60]}{'…' if len(params.get('subtitle','') or '')>60 else ''}",
        ]
        return "\n".join(lines)

    # ── 操作列控件 ────────────────────────────────────────────────────────
    def _make_ops_widget(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(4)
        sch = t.get("schedule", {}) or {}
        enabled = sch.get("enabled", True)
        btn_toggle = QPushButton("禁用" if enabled else "启用")
        btn_toggle.setObjectName("secondary_button")
        btn_toggle.setFixedWidth(50)
        btn_toggle.clicked.connect(lambda _=False, tid=t["id"], en=enabled: self._toggle(tid, en))
        lay.addWidget(btn_toggle)

        btn_run = QPushButton("立即运行")
        btn_run.setObjectName("secondary_button")
        btn_run.setFixedWidth(64)
        btn_run.clicked.connect(lambda _=False, tid=t["id"]: self._run(tid))
        lay.addWidget(btn_run)

        btn_del = QPushButton("删除")
        btn_del.setFixedWidth(44)
        btn_del.clicked.connect(lambda _=False, tid=t["id"]: self._delete(tid))
        lay.addWidget(btn_del)
        return w

    def _toggle(self, tid, currently_enabled):
        self._mgr.update_item(tid, {"schedule": {"enabled": not currently_enabled}})
        # update_item 会归一化 schedule，但需要保留其它字段——重新读原 schedule 合并
        t = self._mgr.get(tid)
        if t:
            sch = t.get("schedule", {}) or {}
            sch["enabled"] = not currently_enabled
            self._mgr.update_item(tid, {"schedule": sch})
        self.refresh()

    def _run(self, tid):
        """立即运行：直接调 MainWindow 的触发方法（切到一键成片页 + 载入参数 + 执行）。"""
        handler = getattr(self.main_window, "_on_scheduled_task_due", None)
        if handler:
            handler(tid)
        else:
            log.warning("[定时任务] main_window 未提供 _on_scheduled_task_due，无法运行")

    def _delete(self, tid):
        if not self.confirm("确定删除该定时任务？"):
            return
        self._mgr.remove_item(tid)
        self.refresh()

    # ── 格式化 helper ─────────────────────────────────────────────────────
    @staticmethod
    def _action_label(action):
        return {"compile_video": "一键成片"}.get(action, action or "—")

    @staticmethod
    def _status_label(status):
        return {"idle": "待执行", "running": "执行中", "done": "已完成",
                "failed": "失败"}.get(status, status or "—")

    @staticmethod
    def _status_color(status):
        from PySide6.QtGui import QColor
        return {
            "running": QColor("#f39c12"),
            "done": QColor("#2ecc71"),
            "failed": QColor("#e74c3c"),
        }.get(status, QColor("#aaa"))

    @staticmethod
    def _schedule_desc(sch):
        mode = sch.get("mode", "daily")
        if mode == "daily":
            return f"每天 {sch.get('time', '09:00')}"
        if mode == "once":
            return f"单次 {sch.get('date', '')} {sch.get('time', '')}"
        if mode == "weekly":
            wds = sch.get("weekdays") or []
            days = "/".join(WEEKDAY_NAMES[d] for d in wds if 0 <= d < 7) or "—"
            return f"每周 {days} {sch.get('time', '')}"
        if mode == "interval":
            return f"每 {sch.get('interval_hours', 24)} 小时"
        return mode
