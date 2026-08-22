"""定时任务管理页（侧边栏「定时任务」菜单，与「工作台」同级的主界面页面）。

两个板块：
1. 本地定时任务：不依赖服务端智能体的本地任务（当前为热点采集），由 Windows 任务计划程序
   （schtasks）注册，可新建/立即运行/注销。
2. 云端智能体：到点读取任务描述 → LLM 拆解 plan → 提交服务端 Orchestrator 按注册的
   智能体自动分解执行（能力清单可点「查看云端智能体」查看）。
3. 服务端成片任务：一键成片/脚本成片的定时调度在服务端，此处提供快捷入口与最近任务概览。
"""
from gui._tab_compat import setup_tab_widget
from gui.elided_label import ElidedLabel
from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from utils import local_scheduler as ls
from utils.gui_icons import mdi_button, table_action_button
from utils.logger_utils import log

# 任务类型（大类）：hotspot=本地定时任务（不依赖服务端智能体）；agent=云端智能体（提交服务端执行）
_TYPE_LABEL = {"hotspot": "本地定时任务", "agent": "云端智能体"}


def _plan_summary(plan):
    """拆解结果 → 可读步骤摘要（能力 + 参数要点），供注册前预览。"""
    lines = []
    for i, s in enumerate(plan.get("steps") or [], 1):
        cap = s.get("capability") or "?"
        params = s.get("params") or {}
        hint = ""
        for k in ("prompt", "content", "text", "topic", "query"):
            v = params.get(k)
            if isinstance(v, str) and v.strip():
                hint = v.strip()[:40]
                break
        lines.append(f"{i}. {cap}" + (f"：{hint}" if hint else ""))
    return "\n".join(lines) if lines else "（空 plan）"
_STATUS_LABEL = {
    "queued": "排队中", "running": "执行中", "waiting_user_input": "等待确认",
    "completed": "已完成", "failed": "失败", "paused": "已暂停", "cancelled": "已取消",
}


class ScheduledTasksMgmtPage(QWidget):
    """定时任务管理页（侧边栏「定时任务」菜单打开，主界面页面）。"""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self._local_worker = None
        self._server_worker = None
        self._agent_worker = None
        self._plan = None  # 云端智能体任务注册前 LLM 拆解出的 plan（保存后到点直接执行）
        self._build_ui()
        self.refresh()

    # ── UI 构建 ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        heading = QLabel("定时任务")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        sub = ElidedLabel("本地定时任务（如热点采集，不依赖服务端智能体）与云端智能体（到点提交服务端自动分解执行）的统一管理。", max_lines=1)  # noqa: E501
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        tab_bar, stack, tabs = setup_tab_widget(root, 1)
        tab_bar.addTab(" 本地定时任务")
        stack.addWidget(self._build_local_tab())
        tab_bar.addTab(" 服务端任务")
        stack.addWidget(self._build_server_tab())

    def _build_local_tab(self):
        """本地定时任务：新建区 + 已注册任务列表。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        # ── 新建区 ──
        create_card = QFrame()
        create_card.setObjectName("card")
        cl = QVBoxLayout(create_card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(8)  # noqa: E501
        cl.addWidget(QLabel("＋ 新建本地定时任务"))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("任务名"))
        self.edit_name = QLineEdit("热点采集")
        self.edit_name.setFixedWidth(140)
        row.addWidget(self.edit_name)
        row.addWidget(QLabel("类型"))
        self.combo_type = QComboBox()
        self.combo_type.addItem("本地定时任务", "hotspot")
        self.combo_type.addItem("云端智能体", "agent")
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(self.combo_type)
        # 任务描述（云端智能体类型）：注册时 LLM 拆解 → 保存执行步骤，到点直接提交服务端
        self.goal_row = QWidget()
        gl = QHBoxLayout(self.goal_row)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)  # noqa: E501
        gl.addWidget(QLabel("任务描述"))
        self.edit_goal = QLineEdit("生成产品文案，做合规复检，再生成分镜脚本并评价")
        gl.addWidget(self.edit_goal, 1)
        self.btn_split = mdi_button("拆解任务", "magic")
        self.btn_split.setObjectName("secondary_button")
        self.btn_split.setFixedHeight(30)
        self.btn_split.setCursor(Qt.PointingHandCursor)
        self.btn_split.clicked.connect(self._on_split_plan)
        gl.addWidget(self.btn_split)
        row.addWidget(self.goal_row, 1)
        # 任务名栏最右侧：查看服务端注册的智能体及其能力/唤醒提示词
        btn_agents = mdi_button("查看云端智能体", "robot")
        btn_agents.setObjectName("secondary_button")
        btn_agents.setFixedHeight(30)
        btn_agents.setCursor(Qt.PointingHandCursor)
        btn_agents.clicked.connect(self._on_view_agents)
        row.addWidget(btn_agents)
        cl.addLayout(row)

        # 拆解结果预览（云端智能体类型）：展示 LLM 拆出的执行步骤
        self.plan_row = QWidget()
        pl = QHBoxLayout(self.plan_row)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)  # noqa: E501
        pl.addWidget(QLabel("拆解步骤"))
        self.plan_preview = QLabel("（尚未拆解）")
        self.plan_preview.setObjectName("muted_text")
        self.plan_preview.setWordWrap(True)
        pl.addWidget(self.plan_preview, 1)
        cl.addWidget(self.plan_row)
        # 类型初始状态（需在 goal_row/plan_row 创建之后，否则属性不存在）
        self._on_type_changed()

        row2 = QHBoxLayout()
        row2.setSpacing(8)
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
        wl = QHBoxLayout(self.week_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(4)  # noqa: E501
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
        list_card = QFrame()
        list_card.setObjectName("card")
        ll = QVBoxLayout(list_card)
        ll.setContentsMargins(12, 10, 12, 10)
        ll.setSpacing(8)  # noqa: E501
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel(" 已注册任务（Windows 任务计划程序）"))
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
        for i in range(7):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        ll.addWidget(self.local_table)
        lay.addWidget(list_card, 1)
        return page

    def _build_server_tab(self):
        """服务端任务：成片定时任务入口 + 最近编排任务概览。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(10)

        tip_card = QFrame()
        tip_card.setObjectName("card")
        tl = QVBoxLayout(tip_card)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.setSpacing(8)  # noqa: E501
        tip = ElidedLabel(
            "「一键成片 / 脚本成片」的定时任务由服务端调度执行："
            "在「一键成片」页配置好产品与文案后，点「添加为定时任务」选择调度方式提交服务端即可。",
            max_lines=2,
        )
        tl.addWidget(tip)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
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

        list_card = QFrame()
        list_card.setObjectName("card")
        ll = QVBoxLayout(list_card)
        ll.setContentsMargins(12, 10, 12, 10)
        ll.setSpacing(8)  # noqa: E501
        ll.addWidget(QLabel(" 最近编排任务（服务端 /agent/tasks，等待确认的节点可在此继续）"))
        self.agent_table = QTableWidget(0, 5)
        self.agent_table.setHorizontalHeaderLabels(["目标", "状态", "进度", "创建时间", "操作"])
        self.agent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.agent_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.agent_table.verticalHeader().setVisible(False)
        ah = self.agent_table.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 5):
            ah.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        ll.addWidget(self.agent_table)
        lay.addWidget(list_card, 1)
        return page

    # ── 本地定时任务 ────────────────────────────────────────────────────
    def _on_type_changed(self):
        """任务类型切换：云端智能体显示任务描述/拆解区，并清空上次拆解结果。"""
        is_agent = self.combo_type.currentData() == "agent"
        self.goal_row.setVisible(is_agent)
        self.plan_row.setVisible(is_agent)
        self._plan = None
        self.plan_preview.setText("（尚未拆解）")

    def _on_mode_changed(self):
        """调度方式切换：每周显示星期选择行。"""
        self.week_row.setVisible(self.combo_mode.currentIndex() == 1)

    def _on_split_plan(self):
        """用云端 LLM 拆解任务描述 → 生成执行步骤（plan），预览并随任务保存。"""
        goal = self.edit_goal.text().strip()
        if not goal:
            QMessageBox.warning(self, "参数不完整", "请先填写任务描述，再拆解任务。")
            return
        self.btn_split.setEnabled(False)
        self.plan_preview.setText("正在调用云端 LLM 拆解任务...")
        from utils.thread_worker import TaskWorker as Worker

        def _do():
            from utils.agent_router import build_plan
            return build_plan(goal)

        def _ok(plan):
            self.btn_split.setEnabled(True)
            if not plan:
                self._plan = None
                self.plan_preview.setText("拆解失败（服务端 LLM 或注册表不可用），请确认服务端在线后重试。")
                return
            self._plan = plan
            self.plan_preview.setText(_plan_summary(plan))

        def _err(e):
            self.btn_split.setEnabled(True)
            self._plan = None
            self.plan_preview.setText(f"拆解失败：{e}")

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._agent_worker = w
        w.start()

    def _on_create(self):
        """注册本地定时任务（后台线程执行 schtasks）。"""
        name = self.edit_name.text().strip()
        task_type = self.combo_type.currentData()
        goal = self.edit_goal.text().strip() if task_type == "agent" else ""
        if task_type == "agent" and not goal:
            QMessageBox.warning(self, "参数不完整", "云端智能体任务需要填写任务描述。")
            return
        if task_type == "agent" and not self._plan:
            QMessageBox.warning(self, "参数不完整", "请先点击「拆解任务」生成执行步骤，再注册任务。")
            return
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
            return ls.create_task(name, task_type, schedule, goal=goal, plan=self._plan)

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
            "已启动素材浏览器采集今日热点。\n" + (r[1] if isinstance(r, tuple) and r and r[0] else str(r))))  # noqa: E501
        w.error.connect(lambda e: QMessageBox.warning(self, "采集失败", str(e)))
        self._local_worker = w
        w.start()

    def _refresh_local(self):
        """后台刷新本地任务列表（schtasks 查询较慢，放线程）。"""
        from utils.thread_worker import TaskWorker as Worker
        worker = getattr(self, "_local_worker", None)
        if worker is not None and worker.isRunning():
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
            if not t.get("registered"):
                name = f"{name}（未注册）"
            self.local_table.setItem(row, 0, QTableWidgetItem(name))
            self.local_table.setItem(row, 1, QTableWidgetItem(_TYPE_LABEL.get(t.get("type", ""), t.get("type", "—"))))  # noqa: E501
            self.local_table.setItem(row, 2, QTableWidgetItem(ls._schedule_text(t.get("schedule"))))  # noqa: E501
            self.local_table.setItem(row, 3, QTableWidgetItem(t.get("next_run") or "—"))
            self.local_table.setItem(row, 4, QTableWidgetItem(t.get("last_run") or "—"))
            self.local_table.setItem(row, 5, QTableWidgetItem(ls._result_text(t.get("last_result"))))  # noqa: E501
            self.local_table.setCellWidget(row, 6, self._make_local_ops(t))

    def _make_local_ops(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if t.get("registered"):
            btn_run = table_action_button("播放", "立即运行一次")
            btn_run.clicked.connect(lambda _=False: self._on_run_now(t.get("task_name")))  # noqa: E501
            lay.addWidget(btn_run)
        btn_del = table_action_button("", "取消定时")
        btn_del.clicked.connect(lambda _=False: self._on_delete(t.get("name")))
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
        if QMessageBox.question(self, "取消定时", f"确定取消定时任务「{name}」吗？\n（任务计划程序中的注册项将一并删除）", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:  # noqa: E501
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

    # ── 服务端任务（成片 + 编排） ────────────────────────────────────────
    def _refresh_server(self):
        from utils.thread_worker import TaskWorker as Worker
        worker = getattr(self, "_server_worker", None)
        if worker is not None and worker.isRunning():
            return
        from utils import scheduled_task_client as stc
        w = Worker(lambda: stc.list_tasks(timeout=6))
        w.finished.connect(self._on_server_loaded)
        w.error.connect(lambda e: log.warning(f"[定时任务] 服务端任务刷新失败: {e}"))
        self._server_worker = w
        w.start()

    def _on_server_loaded(self, items):
        pass  # 服务端成片任务概览已由成片任务页（42）承接，此处仅保留编排任务概览

    def _refresh_agent(self):
        """后台刷新最近编排任务（/agent/tasks 根任务）。"""
        from utils.thread_worker import TaskWorker as Worker
        worker = getattr(self, "_agent_worker", None)
        if worker is not None and worker.isRunning():
            return
        from utils import agent_client as ac
        w = Worker(lambda: ac.list_tasks(root_only=True, timeout=6))
        w.finished.connect(self._on_agent_loaded)
        w.error.connect(lambda e: log.warning(f"[定时任务] 编排任务刷新失败: {e}"))
        self._agent_worker = w
        w.start()

    def _on_agent_loaded(self, data):
        data = data or {}
        items = (data.get("tasks") or [])[:10]
        self.agent_table.setRowCount(0)
        for t in items:
            row = self.agent_table.rowCount()
            self.agent_table.insertRow(row)
            st = t.get("status") or t.get("derived_status") or ""
            self.agent_table.setItem(row, 0, QTableWidgetItem(str(t.get("goal") or t.get("capability") or "—")))  # noqa: E501
            self.agent_table.setItem(row, 1, QTableWidgetItem(_STATUS_LABEL.get(st, st or "—")))  # noqa: E501
            self.agent_table.setItem(row, 2, QTableWidgetItem(f"{int(t.get('progress') or 0)}%"))  # noqa: E501
            self.agent_table.setItem(row, 3, QTableWidgetItem(str(t.get("created_at") or "")[:16]))  # noqa: E501
            self.agent_table.setCellWidget(row, 4, self._make_agent_ops(t))

    def _make_agent_ops(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        tid = t.get("id", "")
        st = t.get("status") or t.get("derived_status") or ""
        if st == "waiting_user_input":
            btn = table_action_button("已", "人工确认，继续执行")
            btn.clicked.connect(lambda _=False, i=tid: self._on_agent_confirm(i))
            lay.addWidget(btn)
        else:
            btn_info = table_action_button("ℹ", "查看详情")
            btn_info.clicked.connect(lambda _=False, i=tid: self._on_agent_detail(i))
            lay.addWidget(btn_info)
        return w

    def _on_agent_confirm(self, tid):
        """waiting_user_input 节点人工确认 → 继续执行。"""
        from utils import agent_client as ac
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ac.confirm_task(tid))
        w.finished.connect(lambda r: self._on_agent_confirm_done(r, tid))
        w.error.connect(lambda e: QMessageBox.warning(self, "确认失败", str(e)))
        self._agent_worker = w
        w.start()

    def _on_agent_confirm_done(self, result, tid):
        if result:
            QMessageBox.information(self, "已确认", f"任务 {tid} 已确认，继续执行。")
        else:
            QMessageBox.warning(self, "确认失败", f"任务 {tid} 确认失败（状态可能已变化）。")
        self._refresh_agent()

    def _on_agent_detail(self, tid):
        """编排任务简要详情弹窗。"""
        from utils import agent_client as ac
        from utils.thread_worker import TaskWorker as Worker
        w = Worker(lambda: ac.get_task(tid))
        w.finished.connect(lambda t: self._show_agent_detail(t, tid))
        w.error.connect(lambda e: QMessageBox.warning(self, "加载失败", str(e)))
        self._agent_worker = w
        w.start()

    def _show_agent_detail(self, task, tid):
        if not task:
            QMessageBox.warning(self, "加载失败", f"任务 {tid} 不存在或已删除。")
            return
        lines = [f"目标：{task.get('goal') or '—'}",
                 f"状态：{_STATUS_LABEL.get(task.get('status') or task.get('derived_status') or '', '—')}",  # noqa: E501
                 f"进度：{int(task.get('progress') or 0)}%"]
        for ch in (task.get("children") or [])[:8]:
            ch_st = ch.get("status") or ""
            lines.append(f"· {ch.get('capability') or ch.get('id')}：{_STATUS_LABEL.get(ch_st, ch_st or '—')}"  # noqa: E501
                         f" {int(ch.get('progress') or 0)}%")
        if task.get("children") and len(task["children"]) > 8:
            lines.append(f"· …… 共 {len(task['children'])} 个子任务")
        QMessageBox.information(self, f"编排任务 {tid}", "\n".join(lines))

    # ── 云端智能体能力查看 ──────────────────────────────────────────────
    def _on_view_agents(self):
        """拉取服务端注册的智能体清单，弹窗展示能力与唤醒提示词。"""
        from utils import agent_client as ac
        from utils.thread_worker import TaskWorker as Worker

        def _do():
            reg = ac.get_registry(timeout=8)
            return (reg or {}).get("capabilities") or []

        def _ok(caps):
            server_caps = [c for c in caps if c.get("executor") == "server"]
            if not server_caps:
                QMessageBox.warning(self, "暂无数据", "服务端未注册任何云端智能体，请确认服务端在线。")
                return
            _AgentCapabilityDialog(server_caps, self).exec()

        def _err(e):
            QMessageBox.warning(self, "加载失败", f"云端智能体列表加载失败：{e}")

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._agent_worker = w
        w.start()

    # ── 公共 ────────────────────────────────────────────────────────────
    def _goto_page(self, idx):
        mw = self.main_window
        if mw is not None and hasattr(mw, "switch_page"):
            mw.switch_page(idx)

    def refresh(self):
        self._refresh_local()
        self._refresh_agent()


class _AgentCapabilityDialog(QDialog):
    """云端智能体能力查看窗口：服务端注册的智能体列表（能力说明 / 唤醒提示词 / 调用接口）。"""

    def __init__(self, caps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("云端智能体能力")
        self.resize(880, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        tip = ElidedLabel(
            "以下为服务端注册的智能体（云端能力）：在「云端智能体」定时任务或工作台输入任务描述时，"
            "可参照「能力说明」中的唤醒提示词表达需求，任务会被自动拆解分配到这里对应的智能体执行。",
            max_lines=2,
        )
        tip.setObjectName("muted_text")
        lay.addWidget(tip)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["智能体", "能力ID", "能力说明（唤醒提示词）", "调用接口"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for c in caps:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(c.get("name") or "—")))
            table.setItem(row, 1, QTableWidgetItem(str(c.get("id") or "—")))
            table.setItem(row, 2, QTableWidgetItem(str(c.get("description") or "—")))
            table.setItem(row, 3, QTableWidgetItem(str(c.get("api") or "—")))
        h = table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setWordWrap(True)
        lay.addWidget(table, 1)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("secondary_button")
        btn_close.setFixedHeight(30)
        btn_close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn_close)
        lay.addLayout(row)
