# -*- coding: utf-8 -*-
"""智能体编排窗口（侧边栏「智能体编排」菜单入口）。

服务端「智能体化」（PRD §13 / /guide 智能体化章节）就绪后，客户端只做：
提交 / 轮询 / 人工确认 / 展示。本窗口三块能力：

1. 编排任务：GET /agent/tasks 列表（根任务），操作：暂停/恢复/取消/重试；
2. 任务详情：GET /agent/tasks/{id} 子任务树（derived_status 聚合），
   waiting_user_input 子任务 → confirm 继续；查看中间产物（S4/S5）；
3. 能力注册表：GET /agent/registry 展示服务端可编排能力清单（离线缓存兜底）。

任务 id 前缀 a_，/tasks/unified 已打通，树状状态与「成片任务」页同一套轮询体系。
"""
import os
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QWidget, QComboBox,
    QLineEdit, QPlainTextEdit, QCheckBox, QRadioButton, QDialogButtonBox,
    QMessageBox, QTextBrowser,
)

from config.paths import DATA_DIR
from utils.gui_icons import mdi_button, table_action_button
from utils.logger_utils import log
from utils import agent_client as ac

_STATUS_LABEL = {
    "queued": "排队中", "running": "执行中", "waiting_user_input": "等待确认",
    "completed": "已完成", "failed": "失败", "paused": "已暂停", "cancelled": "已取消",
}
_STATUS_COLOR = {
    "queued": "#888888", "running": "#f39c12", "waiting_user_input": "#3b82f6",
    "completed": "#2ecc71", "failed": "#e74c3c", "paused": "#8b5cf6", "cancelled": "#888888",
}

_REGISTRY_CACHE = os.path.join(DATA_DIR, "agent_registry.json")

_PLAN_TEMPLATE = (
    "{\n"
    '  "goal": "文案合规复检",\n'
    '  "steps": [\n'
    '    {"id": "s1", "capability": "review_check", "params": {"content": "正品保障"}, "depends_on": []},\n'
    '    {"id": "s2", "capability": "review_check",\n'
    '     "params": {"content": "上一步结论：${s1.verdict}"}, "depends_on": ["s1"],\n'
    '     "needs_user_input": false}\n'
    "  ]\n"
    "}\n"
)


def _cache_registry(reg):
    """能力注册表落盘缓存（离线兜底）。"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_REGISTRY_CACHE, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log.warning(f"[智能体编排] 注册表缓存写入失败: {e}")


def _load_registry_cache():
    try:
        if os.path.isfile(_REGISTRY_CACHE):
            with open(_REGISTRY_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"[智能体编排] 注册表缓存读取失败: {e}")
    return None


class AgentOrchestrationDialog(QDialog):
    """智能体编排窗口（侧边栏「智能体编排」菜单打开）。"""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("🤖 智能体编排")
        self.resize(1040, 660)
        self._list_worker = None
        self._detail_worker = None
        self._reg_worker = None
        self._current_task = None      # 当前展示详情的根任务
        self._current_node_task = None  # 当前选中树节点的任务 dict
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._poll_once)
        self._build_ui()

    # ── UI 构建 ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        heading = QLabel("🤖 智能体编排")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        sub = QLabel("一句话需求 → 服务端 Orchestrator 拆解执行；能力可注册、任务树可监控、支持人工确认与断点续跑。")
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        tabs = QTabWidget()
        tabs.addTab(self._build_tasks_tab(), "编排任务")
        tabs.addTab(self._build_detail_tab(), "任务详情")
        tabs.addTab(self._build_registry_tab(), "能力注册表")
        tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs = tabs
        root.addWidget(tabs, 1)

        self.refresh()

    def _build_tasks_tab(self):
        """编排任务列表：新建 + 自动刷新 + 操作（暂停/恢复/取消/重试）。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10); cl.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("📋 编排任务（根任务列表）"))
        hdr.addStretch()
        btn_new = mdi_button("新建编排", "robot")
        btn_new.setObjectName("primary_button")
        btn_new.setFixedHeight(32)
        btn_new.clicked.connect(self._on_new_orchestration)
        hdr.addWidget(btn_new)
        self.chk_autorefresh = QCheckBox("自动刷新")
        self.chk_autorefresh.setChecked(True)
        hdr.addWidget(self.chk_autorefresh)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("secondary_button")
        btn_refresh.clicked.connect(self.refresh)
        hdr.addWidget(btn_refresh)
        cl.addLayout(hdr)

        self.task_table = QTableWidget(0, 6)
        self.task_table.setHorizontalHeaderLabels(["目标", "任务 ID", "状态", "进度", "创建时间", "操作"])
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.cellClicked.connect(self._on_task_row_clicked)
        h = self.task_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        cl.addWidget(self.task_table)
        lay.addWidget(card, 1)
        return page

    def _build_detail_tab(self):
        """任务详情：子任务树 + 人工确认/产物操作。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        tip = QLabel("点击左侧列表任务行加载详情；等待确认的子任务可在此确认继续，产物可查看/打开。")
        tip.setObjectName("muted_text")
        lay.addWidget(tip)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["任务", "能力", "状态", "进度", "摘要"])
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 70)
        self.tree.setColumnWidth(4, 340)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        lay.addWidget(self.tree, 1)

        ops = QHBoxLayout(); ops.setSpacing(8)
        self.btn_confirm = mdi_button("确认继续", "check")
        self.btn_confirm.setObjectName("primary_button")
        self.btn_confirm.setFixedHeight(32)
        self.btn_confirm.clicked.connect(self._on_confirm_node)
        self.btn_confirm.setVisible(False)
        ops.addWidget(self.btn_confirm)
        self.btn_artifacts = mdi_button("查看产物", "package")
        self.btn_artifacts.setObjectName("secondary_button")
        self.btn_artifacts.setFixedHeight(32)
        self.btn_artifacts.clicked.connect(self._on_view_artifacts)
        self.btn_artifacts.setVisible(False)
        ops.addWidget(self.btn_artifacts)
        self.detail_info = QLabel("")
        self.detail_info.setObjectName("muted_text")
        self.detail_info.setWordWrap(True)
        ops.addWidget(self.detail_info, 1)
        lay.addLayout(ops)
        return page

    def _build_registry_tab(self):
        """能力注册表：服务端可编排能力清单（S1 验收：展示可编排智能体）。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10); cl.setSpacing(8)
        hdr = QHBoxLayout()
        self.reg_count = QLabel("🛠 能力注册表（服务端可编排智能体）")
        hdr.addWidget(self.reg_count)
        hdr.addStretch()
        btn_reg = QPushButton("刷新")
        btn_reg.setObjectName("secondary_button")
        btn_reg.clicked.connect(self._refresh_registry)
        hdr.addWidget(btn_reg)
        cl.addLayout(hdr)

        self.reg_table = QTableWidget(0, 6)
        self.reg_table.setHorizontalHeaderLabels(["ID", "名称", "执行器", "同步", "需确认", "描述"])
        self.reg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.reg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.reg_table.verticalHeader().setVisible(False)
        h = self.reg_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        cl.addWidget(self.reg_table)
        lay.addWidget(card, 1)

        note = QLabel("执行器：server=服务端能力 ｜ client_tool=客户端本地工具 ｜ external=外部工作流。include_external 时附加客户端侧能力。")
        note.setObjectName("muted_text")
        lay.addWidget(note)
        return page

    # ── 任务列表 ────────────────────────────────────────────────────────
    def refresh(self):
        self._refresh_tasks()
        self._refresh_registry()

    def _refresh_tasks(self):
        """后台拉取编排任务列表（避免服务端异常时卡界面）。"""
        from utils.thread_worker import TaskWorker as Worker
        if getattr(self, "_list_worker", None) and self._list_worker.isRunning():
            return
        w = Worker(lambda: ac.list_tasks(root_only=True))
        self._list_worker = w
        w.finished.connect(self._on_tasks_loaded)
        w.error.connect(lambda e: log.warning(f"[智能体编排] 任务列表刷新失败: {e}"))
        w.start()

    def _on_tasks_loaded(self, data):
        data = data or {}
        items = data.get("tasks") or []
        self.task_table.setRowCount(0)
        has_active = False
        for t in items:
            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            goal = str(t.get("goal") or t.get("capability") or t.get("id") or "—")
            status = str(t.get("derived_status") or t.get("status") or "")
            progress = t.get("children_progress")
            if progress is None:
                progress = t.get("progress", 0)
            goal_item = QTableWidgetItem(goal)
            goal_item.setData(Qt.UserRole, t.get("id"))
            self.task_table.setItem(row, 0, goal_item)
            self.task_table.setItem(row, 1, QTableWidgetItem(str(t.get("id") or "—")))
            status_item = QTableWidgetItem(_STATUS_LABEL.get(status, status or "—"))
            status_item.setForeground(_STATUS_COLOR.get(status, Qt.gray))
            self.task_table.setItem(row, 2, status_item)
            self.task_table.setItem(row, 3, QTableWidgetItem(
                f"{int(progress)}%" if progress is not None else "—"))
            self.task_table.setItem(row, 4, QTableWidgetItem(str(t.get("created_at") or "")[:16]))
            self.task_table.setCellWidget(row, 5, self._make_ops_widget(t))
            if status in ("queued", "running", "waiting_user_input"):
                has_active = True

        # 有活跃任务且自动刷新开启 → 轮询；否则停止
        if has_active and self.chk_autorefresh.isChecked() and not self._poll_timer.isActive():
            self._poll_timer.start()
        elif (not has_active or not self.chk_autorefresh.isChecked()) and self._poll_timer.isActive():
            self._poll_timer.stop()

    def _poll_once(self):
        self._refresh_tasks()

    def _make_ops_widget(self, t):
        """操作列：详情 + 按状态显示暂停/恢复/取消/重试。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        tid = t.get("id")
        status = str(t.get("derived_status") or t.get("status") or "")
        btn_detail = table_action_button("🔍", "查看详情")
        btn_detail.clicked.connect(lambda _=False, i=tid: self._load_detail(i))
        lay.addWidget(btn_detail)
        if status == "running":
            btn = table_action_button("⏸", "暂停")
            btn.clicked.connect(lambda _=False, i=tid: self._do_action("pause", i))
            lay.addWidget(btn)
        elif status == "paused":
            btn = table_action_button("▶", "恢复")
            btn.clicked.connect(lambda _=False, i=tid: self._do_action("resume", i))
            lay.addWidget(btn)
        if status in ("failed", "cancelled"):
            btn = table_action_button("↻", "重试")
            btn.clicked.connect(lambda _=False, i=tid: self._do_action("retry", i))
            lay.addWidget(btn)
        if status not in ("completed", "failed", "cancelled"):
            btn = table_action_button("✕", "取消")
            btn.clicked.connect(lambda _=False, i=tid: self._do_action("cancel", i))
            lay.addWidget(btn)
        return w

    def _do_action(self, action, tid):
        """暂停/恢复/取消/重试编排任务（后台线程，task_id 进日志与错误提示）。"""
        name = {"pause": "暂停", "resume": "恢复", "cancel": "取消", "retry": "重试"}.get(action, action)
        if action in ("cancel", "retry") and not QMessageBox.question(
                self, name, f"确定{name}编排任务 {tid} 吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            return
        from utils.thread_worker import TaskWorker as Worker
        fn = {"pause": ac.pause_task, "resume": ac.resume_task,
              "cancel": ac.cancel_task, "retry": ac.retry_task}[action]

        def _do():
            return fn(tid)

        def _ok(result):
            if result:
                log.info(f"[智能体编排] {name}成功 task_id={tid}")
                self._refresh_tasks()
            else:
                QMessageBox.warning(self, f"{name}失败", f"编排任务（task_id: {tid}）{name}失败，请稍后重试。")

        def _err(e):
            QMessageBox.warning(self, f"{name}失败", f"编排任务（task_id: {tid}）{name}异常：{e}")

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._list_worker = w  # 持有引用：QThread 被 GC 回收会触发 Qt fatal 崩溃
        w.start()

    def _on_task_row_clicked(self, row, _col):
        item = self.task_table.item(row, 0)
        if item:
            self._load_detail(item.data(Qt.UserRole))

    def _load_detail(self, tid):
        """加载任务详情树并切到详情 Tab。"""
        if not tid:
            return
        from utils.thread_worker import TaskWorker as Worker
        self.tree.clear()
        self.detail_info.setText(f"正在加载任务 {tid}…")
        self._current_task = {"id": tid}
        self._tabs.setCurrentIndex(1)
        w = Worker(lambda: ac.get_task(tid))
        w.finished.connect(self._on_detail_loaded)
        w.error.connect(lambda e: log.warning(f"[智能体编排] 任务详情加载失败 task_id={tid}: {e}"))
        self._detail_worker = w
        w.start()

    def _on_detail_loaded(self, task):
        if not task:
            self.detail_info.setText("加载详情失败（任务可能已不存在）。")
            return
        self._current_task = task
        self.tree.clear()
        root_item = self._build_tree_item(task, top=True)
        self.tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self._expand_children(root_item)
        self.detail_info.setText(
            f"任务 {task.get('id')} ｜ 目标：{task.get('goal') or task.get('capability') or '—'} ｜ "
            f"状态：{_STATUS_LABEL.get(task.get('derived_status') or task.get('status'), '—')} ｜ "
            f"进度：{task.get('children_progress') or task.get('progress') or 0}%")
        self.btn_confirm.setVisible(False)
        self.btn_artifacts.setVisible(False)
        self._current_node_task = None

    def _expand_children(self, parent_item):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setExpanded(True)
            self._expand_children(child)

    def _build_tree_item(self, t, top=False):
        """任务 dict → 树节点（携带完整 dict 供确认/产物操作）。"""
        status = str(t.get("derived_status") or t.get("status") or "")
        label = (t.get("goal") or t.get("capability") or t.get("id")) if top else t.get("id")
        item = QTreeWidgetItem([
            str(label or "—"),
            str(t.get("capability") or ""),
            _STATUS_LABEL.get(status, status or "—"),
            f"{t.get('children_progress') or t.get('progress') or 0}%",
            self._summary(t),
        ])
        item.setData(0, Qt.UserRole, t)
        if status in _STATUS_COLOR:
            item.setForeground(2, _STATUS_COLOR[status])
        for child in t.get("children") or []:
            item.addChild(self._build_tree_item(child))
        return item

    @staticmethod
    def _summary(t):
        params = t.get("params") or {}
        result = t.get("result") or {}
        parts = []
        if params:
            parts.append("参数：" + json.dumps(params, ensure_ascii=False)[:120])
        if result:
            parts.append("结果：" + json.dumps(result, ensure_ascii=False)[:120])
        if t.get("error_msg"):
            parts.append(f"错误：{t.get('error_msg')[:100]}")
        return " ｜ ".join(parts)

    def _on_tree_selection(self):
        """选中树节点：waiting_user_input → 显示确认按钮；有产物 → 显示产物按钮。"""
        self.btn_confirm.setVisible(False)
        self.btn_artifacts.setVisible(False)
        self._current_node_task = None
        items = self.tree.selectedItems()
        if not items:
            return
        t = items[0].data(0, Qt.UserRole)
        if not isinstance(t, dict):
            return
        self._current_node_task = t
        if t.get("status") == "waiting_user_input":
            self.btn_confirm.setVisible(True)
            self.btn_confirm.setText(f"确认继续（{t.get('id')}）")
        self.btn_artifacts.setVisible(True)
        self.btn_artifacts.setText(f"查看产物（{t.get('id')}）")

    def _on_confirm_node(self):
        """S4 人工确认：waiting_user_input 子任务 → confirm 恢复执行。"""
        t = self._current_node_task
        if not t:
            return
        tid = t.get("id")
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ac.confirm_task(tid))
        w.finished.connect(lambda r: self._on_confirm_done(r, tid))
        w.error.connect(lambda e: QMessageBox.warning(
            self, "确认失败", f"确认任务（task_id: {tid}）失败：{e}"))
        self._detail_worker = w
        w.start()

    def _on_confirm_done(self, result, tid):
        if result:
            log.info(f"[智能体编排] 人工确认成功 task_id={tid}")
            self._load_detail(tid)
        else:
            QMessageBox.warning(self, "确认失败", f"确认任务（task_id: {tid}）失败，请稍后重试。")

    def _on_view_artifacts(self):
        """S5 查看选中任务（子任务）的中间产物。"""
        t = self._current_node_task
        if not t:
            return
        tid = t.get("id")
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ac.list_artifacts(tid))
        w.finished.connect(lambda arts: self._show_artifacts(arts, tid))
        w.error.connect(lambda e: QMessageBox.warning(self, "加载失败", str(e)))
        self._detail_worker = w
        w.start()

    def _show_artifacts(self, artifacts, tid):
        artifacts = artifacts or []
        dlg = QDialog(self)
        dlg.setWindowTitle(f"中间产物 - {tid}")
        dlg.resize(720, 420)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        if not artifacts:
            tb.setPlainText("（该任务暂无登记的中间产物）")
        else:
            lines = []
            for a in artifacts:
                lines.append(f"- **{a.get('kind', 'other')}**　`{a.get('file_ref', '')}`")
                if a.get("meta"):
                    lines.append(f"  元数据：`{a.get('meta')}`")
            tb.setMarkdown("\n".join(lines) if lines else "（空）")
        lay.addWidget(tb, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.exec()

    # ── 新建编排 ─────────────────────────────────────────────────────────
    def _on_new_orchestration(self):
        """新建编排：手动登记目标 或 提交 plan 由服务端执行。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("新建智能体编排")
        dlg.resize(720, 520)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        lay.addWidget(QLabel("目标（一句话描述要完成的事）"))
        goal_edit = QLineEdit()
        goal_edit.setPlaceholderText("例如：对产品资料做合规复检并生成报告")
        lay.addWidget(goal_edit)

        lay.addWidget(QLabel("提交方式"))
        rb_goal = QRadioButton("登记目标（只建任务，不自动执行）")
        rb_plan = QRadioButton("提交 plan（服务端 Orchestrator 自动执行）")
        rb_plan.setChecked(True)
        lay.addWidget(rb_goal)
        lay.addWidget(rb_plan)

        lay.addWidget(QLabel("plan（steps 的 capability 必须是注册表 server 能力）"))
        plan_edit = QPlainTextEdit()
        plan_edit.setPlaceholderText("留空则自动生成示例 plan（可改）")
        plan_edit.setPlainText(_PLAN_TEMPLATE)
        plan_edit.setMinimumHeight(240)
        lay.addWidget(plan_edit, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("提交")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        goal = goal_edit.text().strip()
        if rb_plan.isChecked():
            try:
                plan = json.loads(plan_edit.toPlainText().strip() or _PLAN_TEMPLATE)
            except Exception as e:
                QMessageBox.warning(self, "plan 格式错误", f"plan 不是合法 JSON：{e}")
                return
            if goal and not plan.get("goal"):
                plan["goal"] = goal
            self._submit_create(goal=plan.get("goal"), plan=plan)
        else:
            self._submit_create(goal=goal or None)

    def _submit_create(self, goal=None, plan=None):
        from utils.thread_worker import TaskWorker as Worker

        def _do():
            return ac.create_task(goal=goal, plan=plan,
                                  mode="execute" if plan else None)

        def _ok(t):
            if t:
                tid = t.get("id")
                log.info(f"[智能体编排] 创建成功 task_id={tid}")
                QMessageBox.information(
                    self, "已提交",
                    f"编排任务已创建（task_id: {tid}）\n"
                    + ("服务端 Orchestrator 正在执行，可在「任务详情」查看子任务树。"
                       if t.get("execution") == "started"
                       else "已登记，可在「任务详情」查看。"))
                self._refresh_tasks()
                self._load_detail(tid)
            else:
                QMessageBox.warning(self, "提交失败", "编排任务创建失败，请确认服务端在线后重试。")

        def _err(e):
            QMessageBox.warning(self, "提交失败", f"编排任务创建异常：{e}")

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._list_worker = w
        w.start()

    # ── 能力注册表（C6）──────────────────────────────────────────────────
    def _refresh_registry(self):
        from utils.thread_worker import TaskWorker as Worker
        if getattr(self, "_reg_worker", None) and self._reg_worker.isRunning():
            return
        w = Worker(lambda: ac.get_registry(include_external=True))
        w.finished.connect(self._on_registry_loaded)
        w.error.connect(lambda e: log.warning(f"[智能体编排] 注册表刷新失败: {e}"))
        self._reg_worker = w
        w.start()

    def _on_registry_loaded(self, reg):
        if not reg:
            reg = _load_registry_cache()
            if not reg:
                self.reg_count.setText("🛠 能力注册表（拉取失败，且无离线缓存）")
                return
            self.reg_count.setText("🛠 能力注册表（离线缓存）")
        else:
            _cache_registry(reg)
            self.reg_count.setText(
                f"🛠 能力注册表（registry_version {reg.get('registry_version', '—')}，"
                f"共 {reg.get('count', 0)} 个可编排能力）")
        caps = reg.get("capabilities") or []
        self.reg_table.setRowCount(0)
        for c in caps:
            row = self.reg_table.rowCount()
            self.reg_table.insertRow(row)
            self.reg_table.setItem(row, 0, QTableWidgetItem(str(c.get("id") or "—")))
            self.reg_table.setItem(row, 1, QTableWidgetItem(str(c.get("name") or "—")))
            self.reg_table.setItem(row, 2, QTableWidgetItem(
                {"server": "服务端", "client_tool": "客户端", "external": "外部"}.get(
                    str(c.get("executor") or ""), str(c.get("executor") or "—"))))
            self.reg_table.setItem(row, 3, QTableWidgetItem("同步" if c.get("sync") else "异步"))
            self.reg_table.setItem(row, 4, QTableWidgetItem("是" if c.get("needs_user_input") else "否"))
            self.reg_table.setItem(row, 5, QTableWidgetItem(str(c.get("description") or "")))

    def _on_tab_changed(self, idx):
        if idx == 2:
            self._refresh_registry()

    # ── 窗口生命周期 ─────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._poll_timer.stop()
        super().closeEvent(event)

    def refresh(self):
        self._refresh_tasks()
        if getattr(self, "_tabs", None) is not None and self._tabs.currentIndex() == 2:
            self._refresh_registry()
