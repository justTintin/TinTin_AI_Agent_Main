# -*- coding: utf-8 -*-
"""定时任务管理窗口（侧边栏「定时任务」菜单入口）。

两个 Tab：
1. 本地定时任务：Windows 任务计划程序（schtasks）注册的内置任务（如每日热点采集），
   替代手工 bat + 任务计划程序配置；可新建/立即运行/注销。
2. 服务端成片任务：一键成片/脚本成片的定时调度在服务端（「一键成片」页配置后
   「添加为定时任务」提交），此处提供快捷入口与最近任务概览。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QLineEdit, QComboBox, QTimeEdit, QCheckBox, QTabWidget, QWidget,
    QMessageBox,
)
from PySide6.QtCore import QTime

from utils.gui_icons import mdi_button, table_action_button
from utils.logger_utils import log
from utils import local_scheduler as ls

_TYPE_LABEL = {"hotspot": "热点采集"}


class ScheduledTasksDialog(QDialog):
    """定时任务管理窗口（侧边栏「定时任务」菜单打开）。"""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("⏰ 定时任务")
        self.resize(920, 580)
        self._local_worker = None
        self._server_worker = None
        self._build_ui()

    # ── UI 构建 ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        heading = QLabel("⏰ 定时任务")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        sub = QLabel("本地定时（热点采集自动运行）与服务端定时成片任务的统一管理入口。")
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        tabs = QTabWidget()
        tabs.addTab(self._build_local_tab(), "本地定时任务")
        tabs.addTab(self._build_server_tab(), "服务端成片任务")
        root.addWidget(tabs, 1)

        self.refresh()

    def _build_local_tab(self):
        """本地定时任务：新建区 + 已注册任务列表。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        # ── 新建区 ──
        create_card = QFrame(); create_card.setObjectName("card")
        cl = QVBoxLayout(create_card); cl.setContentsMargins(12, 10, 12, 10); cl.setSpacing(8)
        cl.addWidget(QLabel("＋ 新建本地定时任务"))

        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(QLabel("任务名"))
        self.edit_name = QLineEdit("热点采集")
        self.edit_name.setFixedWidth(140)
        row.addWidget(self.edit_name)
        row.addWidget(QLabel("类型"))
        self.lbl_type = QLabel("热点采集（自动打开素材浏览器采集抖音/小红书/B站热榜，采完自动退出）")
        self.lbl_type.setObjectName("muted_text")
        row.addWidget(self.lbl_type, 1)
        cl.addLayout(row)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(QLabel("调度"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["每天", "每周"])
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        row2.addWidget(self.combo_mode)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime(9, 0))
        row2.addWidget(self.time_edit)
        # 星期行（每周模式显示）
        self.week_row = QWidget()
        wl = QHBoxLayout(self.week_row); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(4)
        wl.addWidget(QLabel("星期"))
        self._day_checks = []
        for i, d in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            cb = QCheckBox(d)
            cb.setChecked(i < 5)
            self._day_checks.append(cb)
            wl.addWidget(cb)
        wl.addStretch()
        row2.addWidget(self.week_row)
        row2.addStretch()
        self.btn_create = mdi_button("注册任务", "clock")
        self.btn_create.setObjectName("primary_button")
        self.btn_create.setFixedHeight(32)
        self.btn_create.clicked.connect(self._on_create)
        row2.addWidget(self.btn_create)
        cl.addLayout(row2)
        lay.addWidget(create_card)

        # ── 已注册任务列表 ──
        list_card = QFrame(); list_card.setObjectName("card")
        ll = QVBoxLayout(list_card); ll.setContentsMargins(12, 10, 12, 10); ll.setSpacing(8)
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("📋 已注册任务（Windows 任务计划程序）"))
        list_header.addStretch()
        btn_capture = mdi_button("立即采集今日热点", "broadcast")
        btn_capture.setObjectName("secondary_button")
        btn_capture.clicked.connect(self._on_capture_now)
        list_header.addWidget(btn_capture)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("secondary_button")
        btn_refresh.clicked.connect(self.refresh)
        list_header.addWidget(btn_refresh)
        ll.addLayout(list_header)

        self.local_table = QTableWidget(0, 7)
        self.local_table.setHorizontalHeaderLabels(
            ["任务名称", "类型", "调度", "下次运行", "上次运行", "上次结果", "操作"])
        self.local_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.local_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.local_table.verticalHeader().setVisible(False)
        h = self.local_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        ll.addWidget(self.local_table)
        lay.addWidget(list_card, 1)
        return page

    def _build_server_tab(self):
        """服务端成片任务：说明 + 快捷入口 + 最近任务概览。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        tip_card = QFrame(); tip_card.setObjectName("card")
        tl = QVBoxLayout(tip_card); tl.setContentsMargins(12, 10, 12, 10); tl.setSpacing(8)
        tip = QLabel(
            "「一键成片 / 脚本成片」的定时任务由服务端调度执行："
            "在「一键成片」页配置好产品与文案后，点「添加为定时任务」选择调度方式提交服务端即可。"
            "本页集中提供入口与最近任务概览。")
        tip.setWordWrap(True)
        tl.addWidget(tip)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        btn_compile = mdi_button("去一键成片页添加定时任务", "rocket")
        btn_compile.setObjectName("primary_button")
        btn_compile.clicked.connect(lambda: self._goto_page(33))
        btn_row.addWidget(btn_compile)
        btn_monitor = mdi_button("打开成片任务页", "folder")
        btn_monitor.setObjectName("secondary_button")
        btn_monitor.clicked.connect(lambda: self._goto_page(42))
        btn_row.addWidget(btn_monitor)
        btn_row.addStretch()
        tl.addLayout(btn_row)
        lay.addWidget(tip_card)

        list_card = QFrame(); list_card.setObjectName("card")
        ll = QVBoxLayout(list_card); ll.setContentsMargins(12, 10, 12, 10); ll.setSpacing(8)
        ll.addWidget(QLabel("📋 最近任务（服务端 /scheduled/tasks）"))
        self.server_table = QTableWidget(0, 4)
        self.server_table.setHorizontalHeaderLabels(["标题", "类型", "状态", "创建时间"])
        self.server_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.server_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.server_table.verticalHeader().setVisible(False)
        h = self.server_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        ll.addWidget(self.server_table)
        lay.addWidget(list_card, 1)
        return page

    # ── 本地定时任务 ────────────────────────────────────────────────────
    def _on_mode_changed(self):
        """调度方式切换：每周显示星期选择行。"""
        self.week_row.setVisible(self.combo_mode.currentIndex() == 1)

    def _on_create(self):
        """注册本地定时任务（后台线程执行 schtasks）。"""
        name = self.edit_name.text().strip()
        mode = "daily" if self.combo_mode.currentIndex() == 0 else "weekly"
        time_str = self.time_edit.time().toString("HH:mm")
        schedule = {"mode": mode, "time": time_str}
        if mode == "weekly":
            weekdays = [i for i, cb in enumerate(self._day_checks) if cb.isChecked()]
            if not weekdays:
                QMessageBox.warning(self, "参数不完整", "每周模式至少选择一个星期。")
                return
            schedule["weekdays"] = weekdays

        self.btn_create.setEnabled(False)
        from utils.thread_worker import TaskWorker as Worker

        def _do():
            return ls.create_task(name, "hotspot", schedule)

        def _ok(result):
            self.btn_create.setEnabled(True)
            ok, msg = result
            if ok:
                QMessageBox.information(
                    self, "已注册",
                    f"定时任务已注册：{msg}\n已写入 Windows 任务计划程序，可随时在此取消。")
                self.refresh()
            else:
                QMessageBox.warning(self, "注册失败", msg)

        def _err(e):
            self.btn_create.setEnabled(True)
            QMessageBox.warning(self, "注册失败", str(e))

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        # 持有引用：QThread 运行中被 GC 回收会触发 Qt fatal 崩溃
        self._local_worker = w
        w.start()

    def _on_capture_now(self):
        """立即采集一次今日热点（打开素材浏览器自动采集，采完自动退出）。"""
        from utils import asset_browser_client as abc
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: abc.launch_hotspot_capture(auto_quit=True))
        w.finished.connect(lambda r: QMessageBox.information(
            self, "热点采集",
            "已启动素材浏览器采集今日热点。\n" + (r[1] if isinstance(r, tuple) and r and r[0] else str(r))))
        w.error.connect(lambda e: QMessageBox.warning(self, "采集失败", str(e)))
        self._local_worker = w
        w.start()

    def _refresh_local(self):
        """后台刷新本地任务列表（schtasks 查询较慢，放线程）。"""
        from utils.thread_worker import TaskWorker as Worker
        if getattr(self, "_local_worker", None) and self._local_worker.isRunning():
            return
        w = Worker(ls.list_tasks)
        w.finished.connect(self._on_local_loaded)
        w.error.connect(lambda e: log.warning(f"[定时任务] 本地任务刷新失败: {e}"))
        self._local_worker = w
        w.start()

    def _on_local_loaded(self, tasks):
        self.local_table.setRowCount(0)
        for t in tasks or []:
            row = self.local_table.rowCount()
            self.local_table.insertRow(row)
            name = t.get("name", "")
            task_name = t.get("task_name", "")
            if not t.get("registered"):
                name = f"{name}（未注册）"
            self.local_table.setItem(row, 0, QTableWidgetItem(name))
            self.local_table.setItem(row, 1, QTableWidgetItem(_TYPE_LABEL.get(t.get("type", ""), t.get("type", "—"))))
            self.local_table.setItem(row, 2, QTableWidgetItem(ls._schedule_text(t.get("schedule"))))
            self.local_table.setItem(row, 3, QTableWidgetItem(t.get("next_run") or "—"))
            self.local_table.setItem(row, 4, QTableWidgetItem(t.get("last_run") or "—"))
            self.local_table.setItem(row, 5, QTableWidgetItem(ls._result_text(t.get("last_result"))))
            self.local_table.setCellWidget(row, 6, self._make_local_ops(t))

    def _make_local_ops(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if t.get("registered"):
            btn_run = table_action_button("▶", "立即运行一次")
            btn_run.clicked.connect(lambda _=False, tn=t.get("task_name"): self._on_run_now(tn))
            lay.addWidget(btn_run)
        btn_del = table_action_button("🗑", "取消定时")
        btn_del.clicked.connect(lambda _=False, n=t.get("name"): self._on_delete(n))
        lay.addWidget(btn_del)
        return w

    def _on_run_now(self, task_name):
        """立即运行已注册的本地任务。"""
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ls.run_now(task_name))
        w.finished.connect(lambda r: QMessageBox.information(
            self, "立即运行",
            f"任务 {task_name}：{'已触发执行' if r[0] else r[1]}"))
        w.error.connect(lambda e: QMessageBox.warning(self, "运行失败", str(e)))
        self._local_worker = w
        w.start()

    def _on_delete(self, name):
        if not QMessageBox.question(self, "取消定时",
                                    f"确定取消定时任务「{name}」吗？\n（任务计划程序中的注册项将一并删除）",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            return
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ls.delete_task(name))
        w.finished.connect(lambda r: self._on_delete_done(r, name))
        w.error.connect(lambda e: QMessageBox.warning(self, "取消失败", str(e)))
        self._local_worker = w
        w.start()

    def _on_delete_done(self, result, name):
        ok, msg = result
        if ok:
            QMessageBox.information(self, "已取消", f"定时任务「{name}」已取消。")
            self.refresh()
        else:
            QMessageBox.warning(self, "取消失败", msg)

    # ── 服务端成片任务 ──────────────────────────────────────────────────
    def _refresh_server(self):
        from utils.thread_worker import TaskWorker as Worker
        if getattr(self, "_server_worker", None) and self._server_worker.isRunning():
            return
        from utils import scheduled_task_client as stc
        w = Worker(lambda: stc.list_tasks(timeout=6))
        w.finished.connect(self._on_server_loaded)
        w.error.connect(lambda e: log.warning(f"[定时任务] 服务端任务刷新失败: {e}"))
        self._server_worker = w
        w.start()

    def _on_server_loaded(self, items):
        self.server_table.setRowCount(0)
        for t in (items or [])[:8]:
            row = self.server_table.rowCount()
            self.server_table.insertRow(row)
            self.server_table.setItem(row, 0, QTableWidgetItem(str(t.get("title") or "—")))
            self.server_table.setItem(row, 1, QTableWidgetItem(str(t.get("task_type") or "—")))
            self.server_table.setItem(row, 2, QTableWidgetItem(str(t.get("status") or "—")))
            self.server_table.setItem(row, 3, QTableWidgetItem(str(t.get("created_at") or "")[:16]))

    def _goto_page(self, idx):
        mw = self.main_window
        if mw is not None and hasattr(mw, "switch_page"):
            mw.switch_page(idx)
        self.close()

    # ── 公共 ────────────────────────────────────────────────────────────
    def refresh(self):
        self._refresh_local()
        self._refresh_server()
