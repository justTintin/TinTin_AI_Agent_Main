"""
定时任务页：监控服务端 /scheduled/tasks 的执行状态与输出结果。

架构（thin client）：
- 任务的存储/调度/执行全部在服务端，本页只 GET 列表 + 展示状态/结果 + 删除
- 后台轮询 Worker 每 N 秒刷新一次（任务进行中时自动更新 progress/status）
- 「立即运行」= 提交一个立即执行的任务（task_type=product_montage）给服务端

服务端任务字段：id, task_type, title, params, status, progress, error_msg,
                result({video_url}), created_at, updated_at, completed_at
"""
import os

import requests.exceptions
from gui.base_page import BasePage
from gui.elided_label import ElidedLabel
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from utils import scheduled_task_client as stc
from utils.gui_icons import icon_button, table_action_button
from utils.logger_utils import log


class _VideoPlayerDialog(QDialog):
    """成片视频播放器：直接播放服务端 URL（FastAPI FileResponse 原生支持 Range，可拖动进度）。"""

    def __init__(self, url, title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"播放 播放成片 - {title[:40]}")
        self.resize(960, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._video = QVideoWidget()
        lay.addWidget(self._video, 1)
        self._audio = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

        ctl = QHBoxLayout()
        ctl.setSpacing(8)
        self._btn_toggle = QPushButton("暂停 暂停")
        self._btn_toggle.setObjectName("secondary_button")
        self._btn_toggle.setFixedWidth(90)
        self._btn_toggle.clicked.connect(self._toggle_play)
        ctl.addWidget(self._btn_toggle)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setEnabled(False)
        self._slider.sliderMoved.connect(self._player.setPosition)
        ctl.addWidget(self._slider, 1)
        self._time_lbl = QLabel("00:00 / 00:00")
        self._time_lbl.setStyleSheet("color:#8b93a3;")
        ctl.addWidget(self._time_lbl)
        btn_close = QPushButton("关闭")
        btn_close.setObjectName("secondary_button")
        btn_close.clicked.connect(self.reject)
        ctl.addWidget(btn_close)
        lay.addLayout(ctl)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)
        self._player.setSource(QUrl(url))
        self._player.play()

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self._btn_toggle.setText("暂停 暂停" if playing else "播放 播放")

    def _on_duration(self, ms):
        if ms > 0:
            self._slider.setRange(0, ms)
            self._slider.setEnabled(True)
            self._time_lbl.setText(f"00:00 / {_fmt_ms(ms)}")

    def _on_position(self, ms):
        self._slider.setValue(ms)
        self._time_lbl.setText(f"{_fmt_ms(ms)} / {_fmt_ms(self._player.duration())}")

    def _on_error(self, err, msg):
        QMessageBox.warning(self, "播放失败",
                            f"无法播放成片（{msg}）。\n可改用「下载成片」保存到本地播放。")
        self._btn_toggle.setEnabled(False)

    def closeEvent(self, event):  # noqa: N802
        self._player.stop()
        super().closeEvent(event)


def _fmt_ms(ms):
    """毫秒 -> M:SS"""
    s = int(ms or 0) // 1000
    return f"{s // 60}:{s % 60:02d}"


class ScheduledTasksPage(BasePage):
    """定时任务监控页（数据来自服务端 /scheduled/tasks）。"""

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        heading = QLabel("成片任务")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        sub = ElidedLabel("监控服务端成片任务（产品成片/脚本成片）执行状态与输出结果；任务由服务端调度执行。", max_lines=1)  # noqa: E501
        sub.setObjectName("muted_text")
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── 任务列表 ───────────────────────────────────────────────────────
        list_card = QFrame()
        list_card.setObjectName("card")
        ll = QVBoxLayout(list_card)
        ll.setContentsMargins(12, 10, 12, 10)
        ll.setSpacing(8)  # noqa: E501

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel(" 成片任务列表（来自服务端）"))
        list_header.addStretch()
        # ── 批量操作按钮（全选/下载/打包）──────────────────────────────────
        self.btn_select_all = QPushButton(" 全选")
        self.btn_select_all.setObjectName("secondary_button")
        self.btn_select_all.setToolTip("勾选 / 取消勾选列表全部任务（表格第一列 ）")
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        list_header.addWidget(self.btn_select_all)
        self.btn_download_selected = QPushButton("⬇ 下载所选")
        self.btn_download_selected.setObjectName("secondary_button")
        self.btn_download_selected.setToolTip("下载所有已勾选任务的成片视频到指定目录")
        self.btn_download_selected.clicked.connect(self._download_selected)
        list_header.addWidget(self.btn_download_selected)
        self.btn_download_selected_pkg = QPushButton(" 打包所选")
        self.btn_download_selected_pkg.setObjectName("secondary_button")
        self.btn_download_selected_pkg.setToolTip(
            "下载所有已勾选且支持打包任务（成片+全部素材+manifest.json）")
        self.btn_download_selected_pkg.clicked.connect(self._download_selected_package)
        list_header.addWidget(self.btn_download_selected_pkg)
        from PySide6.QtWidgets import QCheckBox
        self.chk_autorefresh = QCheckBox("自动刷新")
        self.chk_autorefresh.setChecked(True)   # 默认开启：有进行中任务时每 5 秒自动刷新
        self.chk_autorefresh.setToolTip("有进行中任务时自动每 5 秒刷新列表")
        list_header.addWidget(self.chk_autorefresh)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.clicked.connect(self.refresh)
        list_header.addWidget(self.btn_refresh)
        ll.addLayout(list_header)

        # 列表改为 11 列，新增「总分」列
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(
            ["", "task_id", "标题", "类型", "状态", "进度", "总分", "播放", "下载", "创建时间", "操作"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_row_clicked)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)   #  勾选
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)   # ID
        h.setSectionResizeMode(2, QHeaderView.Interactive)        # 标题（可拖动）
        self.table.setColumnWidth(2, 300)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)   # 类型
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # 状态
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)   # 进度
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # 总分
        self.table.setColumnWidth(6, 80)
        h.setSectionResizeMode(7, QHeaderView.Interactive)   # 播放
        self.table.setColumnWidth(7, 130)
        h.setSectionResizeMode(8, QHeaderView.Interactive)        # 下载
        self.table.setColumnWidth(8, 130)
        h.setSectionResizeMode(9, QHeaderView.ResizeToContents)   # 时间
        h.setSectionResizeMode(10, QHeaderView.Stretch)           # 操作（占满剩余）
        self._last_items = []        # 最近一次列表数据（供勾选行反查任务）
        self._all_checked = False    # 全选状态
        ll.addWidget(self.table)
        root.addWidget(list_card, 2)

        # ── 选中任务详情 ───────────────────────────────────────────────────
        detail_card = QFrame()
        detail_card.setObjectName("card")
        dl = QVBoxLayout(detail_card)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(6)  # noqa: E501
        dl.addWidget(QLabel(" 任务详情（参数 / 结果）"))
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumHeight(100)
        self.detail.setPlaceholderText("点击上方任务行查看其参数与执行结果…")
        dl.addWidget(self.detail, 1)

        # 变体打分区（仅当任务已完成且有 all_variants 时显示）
        self.variants_title = QLabel(" 变体打分（对本次成片的好/坏反馈，供服务端进化选择）")
        self.variants_title.setStyleSheet("font-weight:bold; color:#3b82f6;")
        self.variants_title.setVisible(False)
        dl.addWidget(self.variants_title)
        self.variants_container = QWidget()   # 动态填充打分行的容器
        self.variants_layout = QVBoxLayout(self.variants_container)
        self.variants_layout.setContentsMargins(0, 0, 0, 0)
        self.variants_layout.setSpacing(4)  # noqa: E501
        self.variants_container.setVisible(False)
        dl.addWidget(self.variants_container)
        self._current_task_id = None   # 当前展示详情的任务 id（供打分回调用）
        self._agent_link = {}          # 执行层任务号 → 编排层任务号（a_ 前缀）
        self._agent_eval = {}          # 编排层任务号 → 服务端深度评审 evaluation dict
        self._task_eval = {}           # 执行层任务号 → 深度评审（/evaluate/by-task 直接命中）

        # 维度打分区（仅当任务已完成且有深度评审时显示）
        self.dim_title = QLabel(" 维度打分反馈（逐维改分，驱动服务端进化）")
        self.dim_title.setStyleSheet("font-weight:bold; color:#f39c12;")
        self.dim_title.setVisible(False)
        dl.addWidget(self.dim_title)
        self._dim_widgets = {}  # {dim_key: {"label": ..., "spin": ..., "orig_score": ...}}
        self._dim_spins_group = QWidget()
        self._dim_spins_layout = QHBoxLayout(self._dim_spins_group)
        self._dim_spins_layout.setContentsMargins(0, 0, 0, 0)
        self._dim_spins_layout.setSpacing(12)
        self._dim_spins_group.setVisible(False)
        dl.addWidget(self._dim_spins_group)
        self.btn_dim_submit = QPushButton(" 提交维度反馈")
        self.btn_dim_submit.setObjectName("primary_button")
        self.btn_dim_submit.setVisible(False)
        self.btn_dim_submit.clicked.connect(self._on_dimension_feedback_submit)
        dl.addWidget(self.btn_dim_submit)

        root.addWidget(detail_card, 1)

        # ── 自动轮询定时器：任务进行中时每 5 秒刷新 ────────────────────────
        self._poll_timer = QTimer(self.parent_widget)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self.refresh)

        # 首次加载
        self.refresh()

    # ── 数据刷新（调服务端）──────────────────────────────────────────────
    def refresh(self):
        """从服务端拉取任务列表并刷新表格（HTTP 放后台线程，避免服务端异常时卡界面）。
        同时拉取编排任务列表，建立 执行号 → 编排任务号（a_）映射。"""
        from utils.thread_worker import TaskWorker as Worker
        self._refresh_worker: Worker | None = None
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            return

        def _fetch_all():
            items = stc.list_tasks() or []
            link, evals, task_evals = {}, {}, self._fetch_task_evaluations(items)
            try:
                from utils import agent_client
                link = self._build_agent_link(agent_client.list_tasks(root_only=False) or {})  # noqa: E501
                evals = self._fetch_evaluations(set(link.values()))
            except requests.exceptions.RequestException as e:
                log.warning(f"[成片任务] 编排任务映射/评审获取失败（不影响列表）: {e}")
            return items, link, evals, task_evals

        w = Worker(_fetch_all)
        self._refresh_worker = w
        w.finished.connect(self._on_refresh_done)
        w.error.connect(self._on_refresh_error)
        w.start()

    @staticmethod
    def _build_agent_link(agent_data):
        """由编排任务列表建立 {执行层任务号: 编排根任务号} 映射。
        编排子任务（auto_pipeline/scheduled_montage 等）的 result.id 即执行层任务号；
        沿 parent_task_id 上溯到根任务（对话创建的 a_ 任务号）。"""
        tasks = agent_data.get("tasks") or []
        by_id = {t.get("id"): t for t in tasks if t.get("id")}

        def _root(tid):
            seen = set()
            cur = by_id.get(tid)
            while cur and cur.get("parent_task_id") and cur["parent_task_id"] in by_id \
                    and cur["id"] not in seen:
                seen.add(cur["id"])
                cur = by_id[cur["parent_task_id"]]
            return cur.get("id") if cur else tid

        link = {}
        for t in tasks:
            rid = (t.get("result") or {}).get("id") if isinstance(t.get("result"), dict) else None  # noqa: E501
            # 执行层任务号为纯数字；a_/script_ 等属编排层自身产物，不纳入映射
            if rid is not None and str(rid).isdigit():
                link[str(rid)] = _root(t.get("id"))
        return link

    @staticmethod
    def _fetch_evaluations(agent_ids):
        """逐个查询编排任务的深度评审（GET /tasks/unified/a_xxx 顶层 evaluation 字段）。
        服务端仅在单任务详情中返回 evaluation，列表接口不携带。"""
        out = {}
        for aid in agent_ids:
            try:
                u = stc.get_task(aid)
                ev = (u or {}).get("evaluation")
                if isinstance(ev, dict):
                    out[aid] = ev
            except requests.exceptions.RequestException:
                continue
        return out

    @staticmethod
    def _fetch_task_evaluations(items):
        """按执行层任务号直查深度评审（GET /evaluate/by-task/{id}）。
        成片类任务完成后服务端自动投递评价，数字任务不依赖编排映射也能命中。"""
        out = {}
        for t in items or []:
            tid = t.get("id")
            if tid is None or t.get("status") != "completed":
                continue
            try:
                ev = stc.evaluate_by_task(tid)
                if ev is not None:
                    out[str(tid)] = ev
            except requests.exceptions.RequestException:
                continue
        return out

    def _on_refresh_error(self, msg):
        log.warning(f"[成片任务] 刷新失败: {msg}")

    def _on_refresh_done(self, fetched):
        """后台拉取完成，主线程刷新表格（保持原有逻辑）。"""
        if isinstance(fetched, tuple) and len(fetched) == 4:
            items, self._agent_link, self._agent_eval, self._task_eval = fetched
        elif isinstance(fetched, tuple) and len(fetched) == 3:
            items, self._agent_link, self._agent_eval = fetched
        elif isinstance(fetched, tuple):
            items, self._agent_link = fetched
        else:   # 兼容旧回调签名
            items = fetched
        items = items or []
        self.table.setRowCount(len(items))
        self.table.clearContents()
        self._last_items = items
        has_active = False  # 是否有 pending/running 任务（决定是否继续轮询）
        for i, t in enumerate(items):
            tid = t.get("id", "")
            status = t.get("status", "")
            #  勾选
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, check_item)
            # ID：优先展示编排任务号（a_），执行号作辅助（悬停可见）
            agent_tid = self._agent_link.get(str(tid))
            id_item = QTableWidgetItem(f"{agent_tid}\n#{tid}" if agent_tid else str(tid))  # noqa: E501
            id_item.setToolTip(
                f"编排任务号：{agent_tid or '—（非对话发起）'}\n执行任务号：{tid}" if agent_tid
                else f"执行任务号：{tid}")
            self.table.setItem(i, 1, id_item)
            # 标题（收窄列，悬停显示全标题）
            title = t.get("title", "") or "—"
            name_item = QTableWidgetItem(title)
            name_item.setData(Qt.UserRole, tid)
            name_item.setToolTip(title)
            self.table.setItem(i, 2, name_item)
            # 类型
            self.table.setItem(i, 3, QTableWidgetItem(self._type_label(t.get("task_type", ""))))  # noqa: E501
            # 状态（带颜色）
            status_item = QTableWidgetItem(self._status_label(status))
            status_item.setForeground(self._status_color(status))
            self.table.setItem(i, 4, status_item)
            # 进度
            self.table.setItem(i, 5, QTableWidgetItem(f"{t.get('progress', 0)}%"))
            # 总分：服务端深度评审优先 → 成片质量评分兜底
            #   - 深度评审接口字段: ev.total / ev.total_score
            #   - storyboard_montage result.quality_score.total
            #   - 变体打分首条: variants[0].score
            total_score = ""
            eval_obj = self._task_eval.get(str(tid))
            if not isinstance(eval_obj, dict) and agent_tid:
                eval_obj = self._agent_eval.get(str(agent_tid))
            if isinstance(eval_obj, dict):
                # 成片评审（服务端深度评审）主字段：total 才是 2.51/10 这种
                for _k in ("total", "total_score", "score", "overall_score"):
                    v = eval_obj.get(_k)
                    if v is not None:
                        try:
                            total_score = f"{float(v):.2f}"
                        except (TypeError, ValueError):
                            total_score = str(v)
                        break
            if not total_score:
                qs = (t.get("result") or {}).get("quality_score") if isinstance(t.get("result"), dict) else None  # noqa: E501
                if isinstance(qs, dict):
                    for _k in ("total", "total_score"):
                        v = qs.get(_k)
                        if v is not None:
                            try:
                                total_score = f"{float(v):.2f}"
                            except (TypeError, ValueError):
                                total_score = str(v)
                            break
            if not total_score:
                variants = t.get("all_variants") or (t.get("result") or {}).get("all_variants") or t.get("variants") or []  # noqa: E501
                if isinstance(variants, list) and variants:
                    first = variants[0] if isinstance(variants[0], dict) else {}
                    s = first.get("score")
                    if s is not None:
                        try:
                            total_score = f"{float(s):.2f}"
                        except (TypeError, ValueError):
                            total_score = str(s)
            if not total_score:
                for _k in ("total_score", "score", "quality_score", "overall_score", "total"):
                    v = t.get(_k)
                    if v is not None and not isinstance(v, dict):
                        try:
                            total_score = f"{float(v):.2f}"
                        except (TypeError, ValueError):
                            total_score = str(v)
                        break
            score_item = QTableWidgetItem(total_score)
            score_item.setTextAlignment(Qt.AlignCenter)
            # 高分(>=7)绿色 / 低分(<5)红色，和结论颜色一致
            if total_score:
                try:
                    ts = float(total_score)
                    if ts >= 7.0:
                        score_item.setForeground(QColor("#10b981"))
                    elif ts < 5.0:
                        score_item.setForeground(QColor("#ef4444"))
                except (TypeError, ValueError):
                    pass
            self.table.setItem(i, 6, score_item)
            # 播放/下载列（completed 且有视频结果才显示）
            url = self._resolve_video_url(t)
            if status == "completed" and url:
                btn_play = table_action_button("播放", "播放成片")
                btn_play.clicked.connect(lambda _=False, u=url: self._play_video(u))
                self.table.setCellWidget(i, 7, btn_play)
                self.table.setCellWidget(i, 8, self._make_download_cell(t))
            # 创建时间
            self.table.setItem(i, 9, QTableWidgetItem(self._fmt_time(t.get("created_at"))))  # noqa: E501
            # 操作列：删除
            self.table.setCellWidget(i, 10, self._make_del_widget(t))
            if status in ("pending", "running"):
                has_active = True

        self.detail.setMarkdown("*点击任务行查看参数与结果*")
        self._current_task_full = None
        self._hide_dimension_feedback()
        # 列表刷新后重置全选状态
        self._all_checked = False
        if hasattr(self, "btn_select_all"):
            self.btn_select_all.setText(" 全选")
        # 有进行中任务 且 自动刷新开启 → 启动轮询；否则停止
        if has_active and self.chk_autorefresh.isChecked() and not self._poll_timer.isActive():  # noqa: E501
            self._poll_timer.start()
        elif (not has_active or not self.chk_autorefresh.isChecked()) and self._poll_timer.isActive():  # noqa: E501
            self._poll_timer.stop()

    def _on_row_clicked(self, row, col):
        if col == 0:
            return   #  勾选列：只切换勾选，不加载详情
        name_item = self.table.item(row, 2)
        if not name_item:
            return
        tid = name_item.data(Qt.UserRole)
        from utils.thread_worker import TaskWorker as Worker
        self.detail.setMarkdown(f"*正在加载任务 {tid} 详情…*")
        w = Worker(lambda: stc.get_task(tid))
        w.finished.connect(self._on_task_detail_loaded)
        w.error.connect(lambda e: log.warning(f"[成片任务] 加载详情失败: {e}"))
        # 必须持有 Worker：QThread 运行中被 Python GC 回收会触发 Qt fatal 崩溃（0xc0000409）
        self.track_worker(w)
        w.start()

    def _on_task_detail_loaded(self, t):
        if t:
            self._current_task_full = t
            self.detail.setMarkdown(self._render_detail(t))
            self._populate_variants(t)   # 填充变体打分区
            self._populate_dimension_feedback(t)   # 填充维度打分区

    def _render_detail(self, t):
        params = t.get("params", {}) or {}
        result = t.get("result", {}) or {}
        lines = [
            f"### {t.get('title', '')}",
            "",
        ]
        agent_tid = self._agent_link.get(str(t.get('id')))
        if agent_tid:
            lines.append(f"- **任务 ID**：{agent_tid}（执行号 #{t.get('id')}）")
        else:
            lines.append(f"- **任务 ID**：{t.get('id')}")
        lines += [
            f"- **类型**：{self._type_label(t.get('task_type', ''))}",
            f"- **状态**：{self._status_label(t.get('status', ''))}（{t.get('progress', 0)}%）",  # noqa: E501
            f"- **创建**：{self._fmt_time(t.get('created_at'))}",
            f"- **完成**：{self._fmt_time(t.get('completed_at'))}",
        ]
        if t.get("error_msg"):
            lines.append(f"- **错误**：`{t.get('error_msg')}`")
        # ── 评审信息：服务端深度评审（优先执行号直查，编排任务兜底）──
        ev = self._task_eval.get(str(t.get("id")))
        if not isinstance(ev, dict):
            agent_tid2 = self._agent_link.get(str(t.get("id")))
            ev = self._agent_eval.get(agent_tid2) if agent_tid2 else None
        if isinstance(ev, dict):
            verdict_map = {"pass": "完成： 通过", "rejected": "失败： 不通过",
                           "excellent": " 优秀", "marginal": "注意： 边缘"}
            lines += ["", "####  成片评审（服务端深度评审）"]
            lines.append(f"- **总分**：**{ev.get('total')}** / 10　**结论**："
                         f"{verdict_map.get(str(ev.get('verdict', '')), str(ev.get('verdict', '')) or '—')}"  # noqa: E501
                         f"（置信度 {ev.get('confidence')}，引擎：{ev.get('engine') or '—'}）")
            layer_labels = (("technical", "技术质量"), ("editing", "剪辑节奏"),
                            ("narrative", "叙事表达"), ("aesthetic", "美学画面"),
                            ("audio", "音频质量"), ("compliance", "合规性"))
            ls = ev.get("layer_scores") or {}
            for k, label in layer_labels:
                if ls.get(k) is not None:
                    lines.append(f"- {label}：{ls.get(k)}")
            vetoes = ev.get("vetoes") or []
            if vetoes:
                vs = "；".join(
                    str(v.get("detail") or v.get("reason") or v) for v in vetoes[:3])
                lines.append(f"-  否决项：{vs}")
            if ev.get("comment"):
                lines.append(f"-  总评：{ev.get('comment')}")
        # ── 评审信息：成片质量评分（storyboard_montage result.quality_score）──
        qs = result.get("quality_score") if isinstance(result, dict) else None
        if isinstance(qs, dict):
            lines += ["", "####  评审评分（成片质量评分）"]
            lines.append(f"- **总分**：**{qs.get('total')}** / 10（评分引擎：{qs.get('engine') or '—'}）")  # noqa: E501
            for k, label in (("clarity", "清晰度"), ("texture", "质感"), ("aesthetics", "美学"),  # noqa: E501
                             ("composition", "构图"), ("color_quality", "色彩质量"),
                             ("figure_quality", "人物质量"), ("subject_prominence", "主体突出度")):  # noqa: E501
                if qs.get(k) is not None:
                    lines.append(f"- {label}：{qs.get(k)}")
        # ── 关键结果：成片路径/时长/大小/镜头数 ──
        if isinstance(result, dict) and result:
            lines += ["", "#### 结果"]
            vid = result.get("output_url") or result.get("video_path") or result.get("output_path") or ""  # noqa: E501
            if vid:
                lines.append(f"- **成片视频**：{vid}")
            pkg = result.get("package_url") or ""
            if pkg:
                lines.append(f"- **打包下载（成片+素材+manifest）**：{pkg}")
            dur = result.get("total_duration") or result.get("duration")
            if dur:
                lines.append(f"- **时长**：{dur}s")
            sz = result.get("video_size_mb") or result.get("size_mb")
            if sz:
                lines.append(f"- **大小**：{sz} MB")
            if result.get("shots") is not None:
                lines.append(f"- **镜头数**：{result.get('shots')}")
            if result.get("clip_count") is not None:
                lines.append(f"- **片段数**：{result.get('clip_count')}")
            if result.get("narration"):
                lines.append(f"- **旁白**：{result.get('narration')}")
            if result.get("warnings"):
                lines.append(f"- **警告**：`{result.get('warnings')}`")
            assets = result.get("assets") or []
            if assets:
                lines += ["", "#### 素材资产"]
                for a in assets:
                    lines.append(
                        f"- **{a.get('type')}**｜{a.get('filename')}｜"
                        f"{a.get('duration')}s｜`{a.get('source_uri')}`")
        elif result:
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

    def _view_task_log(self):
        """弹窗查看任务服务端执行日志（logs / error_msg）——兼容旧调用，使用当前选中任务。"""
        t = getattr(self, "_current_task_full", None)
        if not t:
            return
        self._view_task_log_for(t)

    def _view_task_log_for(self, t):
        """弹窗查看指定任务的服务端执行日志（logs / error_msg）。"""
        if not t:
            return
        logs = t.get("logs") or ""
        err = t.get("error_msg") or ""
        text = logs if logs else (err if err else "（该任务暂无日志）")
        if not isinstance(text, str):
            text = str(text)
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(f"任务日志 - {t.get('id')}")
        dlg.resize(760, 480)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setPlainText(text)
        lay.addWidget(tb, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.exec()

    # ── 变体打分区 ──────────────────────────────────────────────────────────
    def _populate_variants(self, t):
        """根据任务 result.all_variants 填充变体打分区。
        仅当任务已完成且 result 含 all_variants 时显示；否则隐藏。"""
        # 清空旧的打分行
        while self.variants_layout.count():
            child = self.variants_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        res = t.get("result") or {}
        variants = res.get("all_variants") or []
        best = res.get("best_variant")
        is_done = t.get("status") == "completed"

        if not is_done or not variants:
            # 无变体可打分（任务未完成，或单变体 count=1）
            self.variants_title.setVisible(False)
            self.variants_container.setVisible(False)
            self._current_task_id = None
            return

        self._current_task_id = t.get("id")
        self.variants_title.setVisible(True)
        self.variants_container.setVisible(True)
        self.variants_title.setText(
            f" 变体打分（任务 {self._current_task_id}：对成片好/坏反馈，供服务端进化）　"
            f"最优变体：{best or '—'}")

        # 每个变体一行：变体名/风格/节奏/评分 +  +
        for v in variants:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            rl.setSpacing(8)
            name = v.get("variant", "")
            is_best = (name == best)
            tag = "" if is_best else "  "
            rl.addWidget(QLabel(f"{tag} 变体 {name}"))
            rl.addWidget(QLabel(f"风格：{v.get('style','—')}"))
            rl.addWidget(QLabel(f"节奏：{v.get('pacing','—')}"))
            rl.addWidget(QLabel(f"评分：{v.get('score','—')}"))
            rl.addStretch()
            btn_good = QPushButton(" 好")
            btn_good.setObjectName("secondary_button")
            btn_good.setFixedWidth(64)
            btn_good.clicked.connect(lambda _=False, fb="good": self._on_variant_feedback(fb))  # noqa: E501
            rl.addWidget(btn_good)
            btn_bad = QPushButton(" 差")
            btn_bad.setFixedWidth(64)
            btn_bad.clicked.connect(lambda _=False, fb="bad": self._on_variant_feedback(fb))  # noqa: E501
            rl.addWidget(btn_bad)
            self.variants_layout.addWidget(row)

    def _on_variant_feedback(self, feedback):
        """提交变体好坏反馈到服务端。"""
        tid = self._current_task_id
        if not tid:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._feedback_btns_set_enabled(False)
        worker = Worker(lambda: stc.evolution_feedback(tid, feedback))
        def _ok(updated):
            self._feedback_btns_set_enabled(True)
            if updated:
                self.show_info(f"已反馈「{'好' if feedback=='good' else '差'}」，服务端将据此进化。")
            else:
                self.show_warning("反馈未生效（任务 id 可能无效）。")
        def _err(e):
            self._feedback_btns_set_enabled(True)
            self.show_error(f"反馈提交失败：{e}", "错误")
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker)
        worker.start()

    def _feedback_btns_set_enabled(self, enabled):
        """禁用/启用所有变体打分按钮（提交中防重复点击）。"""
        for i in range(self.variants_layout.count()):
            w = self.variants_layout.itemAt(i).widget()
            if w:
                for btn in w.findChildren(QPushButton):
                    btn.setEnabled(enabled)

    # ── 维度打分反馈 ──────────────────────────────────────────────────────
    _DIMENSION_LABELS = {
        "technical": "技术质量",
        "editing": "剪辑节奏",
        "narrative": "叙事表达",
        "aesthetic": "美学画面",
        "audio": "音频质量",
        "compliance": "合规性",
    }

    def _populate_dimension_feedback(self, t):
        """根据任务深度评审填充维度打分区。
        仅当任务已完成且有 layer_scores 时显示；否则隐藏。"""
        while self._dim_spins_layout.count():
            child = self._dim_spins_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._dim_widgets = {}

        ev = self._task_eval.get(str(t.get("id")))
        if not isinstance(ev, dict):
            agent_tid = self._agent_link.get(str(t.get("id")))
            ev = self._agent_eval.get(agent_tid) if agent_tid else None
        ls = (ev or {}).get("layer_scores") or {}
        is_done = t.get("status") == "completed"

        if not is_done or not ls:
            self.dim_title.setVisible(False)
            self._dim_spins_group.setVisible(False)
            self.btn_dim_submit.setVisible(False)
            return

        self.dim_title.setVisible(True)
        self._dim_spins_group.setVisible(True)
        self.btn_dim_submit.setVisible(True)
        self._current_task_id = t.get("id")

        for key, label in self._DIMENSION_LABELS.items():
            box = QFrame()
            box.setStyleSheet(
                "QFrame { background:#151722; border:1px solid #2b3040; border-radius:6px; }")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(8, 4, 8, 4)
            bl.setSpacing(6)
            bl.addWidget(QLabel(f"{label}："))
            orig = ls.get(key)
            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setSingleStep(1)
            spin.setValue(int(orig) if orig is not None else 5)
            spin.setFixedWidth(55)
            spin.setToolTip(f"当前服务端评分：{orig if orig is not None else '未评分'}")
            bl.addWidget(spin)
            self._dim_widgets[key] = {"spin": spin, "orig": orig}
            self._dim_spins_layout.addWidget(box)

    def _on_dimension_feedback_submit(self):
        """提交维度改分到服务端。"""
        tid = self._current_task_id
        if not tid:
            return
        scores = {}
        for key, wd in self._dim_widgets.items():
            spin = wd.get("spin")
            if spin:
                scores[key] = spin.value()
        if not scores:
            self.show_warning("没有可提交的维度分数。")
            return
        self.btn_dim_submit.setEnabled(False)
        self.btn_dim_submit.setText("提交中…")
        from utils.thread_worker import TaskWorker as Worker
        worker = Worker(lambda: stc.submit_dimension_feedback(tid, scores))
        def _ok(updated):
            self.btn_dim_submit.setEnabled(True)
            self.btn_dim_submit.setText("提交维度反馈")
            if updated:
                self.show_info("维度反馈已提交，服务端将据此优化评审模型。")
            else:
                self.show_warning("反馈未生效（任务 id 或接口无效）。")
        def _err(e):
            self.btn_dim_submit.setEnabled(True)
            self.btn_dim_submit.setText("提交维度反馈")
            self.show_error(f"维度反馈提交失败：{e}", "错误")
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker)
        worker.start()

    def _hide_dimension_feedback(self):
        """隐藏维度打分区（刷新/清空详情时调用）。"""
        self.dim_title.setVisible(False)
        self._dim_spins_group.setVisible(False)
        self.btn_dim_submit.setVisible(False)
        self._dim_widgets = {}

    # ── 操作列 ────────────────────────────────────────────────────────────
    def _make_del_widget(self, t):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        # 查看日志按钮（每个任务行都可见，带 logs 或 error_msg 时才可点击）
        btn_log = table_action_button("日志", "查看任务执行日志")
        logs = t.get("logs") or t.get("error_msg") or ""
        if not logs:
            btn_log.setEnabled(False)
            btn_log.setToolTip("该任务暂无日志")
        btn_log.clicked.connect(lambda _=False, tk=t: self._view_task_log_for(tk))
        lay.addWidget(btn_log)
        btn_del = icon_button("delete", "删除任务", size=16)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.clicked.connect(lambda _=False: self._delete(t.get("id")))
        lay.addWidget(btn_del)
        lay.addStretch()
        return w

    def _make_download_cell(self, task):
        """下载列：视频下载 + 打包下载两个按钮。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        btn_video = table_action_button("⬇ 视频", "下载成片视频")
        btn_video.clicked.connect(
            lambda _=False, t=task: self._download_video(t))
        lay.addWidget(btn_video)
        if _resolve_package_url(task):
            btn_pkg = table_action_button(
                " 打包", "打包下载：成片+素材+manifest.json")
            btn_pkg.clicked.connect(
                lambda _=False, t=task: self._download_package(t))
            lay.addWidget(btn_pkg)
        lay.addStretch()
        return w

    def _resolve_video_url(self, t):
        """从任务 result 解析出可访问的成片 URL。

        兼容 result.video_url / url / output_url / output_file 等相对路径
        （如 '/editor/render/192/result/'），相对路径拼服务端地址；
        绝对 http(s) 地址直接使用。
        """
        return _resolve_task_video_url(t)

    def _play_video(self, url, title=""):
        dlg = _VideoPlayerDialog(url, title, self.parent_widget)
        self._player_dialog = dlg   # 持有引用防 GC
        dlg.exec()

    def _download_video(self, task):
        """下载单个任务的成片视频。"""
        tid = task.get("id") or ""
        url = self._resolve_video_url(task)
        if not url:
            self.show_warning("该任务没有可下载的成片地址。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget, "保存成片视频",
            os.path.join(os.path.expanduser("~"), "Desktop", f"render_{tid}.mp4"),
            "视频文件 (*.mp4 *.mov *.webm);;所有文件 (*.*)")
        if not path:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._dl_worker = Worker(lambda: _download_to_file(url, path))
        self._dl_worker.finished.connect(
            lambda p: self.show_info(f"完成： 成片视频已保存：{p}"))
        self._dl_worker.error.connect(lambda e: self.show_error(f"下载失败：{e}", "错误"))
        self.track_worker(self._dl_worker)
        self._dl_worker.start()
        self.show_info("开始下载成片视频，请稍候…")

    def _download_package(self, task):
        """下载单个任务的成片包（成片+全部素材+manifest.json）。"""
        package_url = _resolve_package_url(task)
        if not package_url:
            self.show_info("该任务暂无打包下载接口（package_url）。")
            return
        tid = task.get("id") or ""
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget, "保存成片包（成片+素材+manifest）",
            os.path.join(os.path.expanduser("~"), "Desktop",
                         f"render_{tid}_package.zip"),
            "ZIP 文件 (*.zip)")
        if not path:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._dl_worker = Worker(lambda: _download_to_file(package_url, path))
        self._dl_worker.finished.connect(
            lambda p: self.show_info(f"完成： 成片+素材包已保存：{p}"))
        self._dl_worker.error.connect(
            lambda e: self.show_error(f"下载失败：{e}", "错误"))
        self.track_worker(self._dl_worker)
        self._dl_worker.start()
        self.show_info("开始下载成片+素材包，请稍候…")

    def _toggle_select_all(self):
        """全选 / 取消全选表格任务（ 列）。"""
        state = Qt.Unchecked if self._all_checked else Qt.Checked
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it:
                it.setCheckState(state)
        self._all_checked = not self._all_checked
        self.btn_select_all.setText(" 取消全选" if self._all_checked else " 全选")

    def _download_selected(self):
        """批量下载所有已勾选任务的成片视频到所选目录。"""
        rows = []
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it and it.checkState() == Qt.Checked and 0 <= i < len(self._last_items):
                task = self._last_items[i]
                if self._resolve_video_url(task):
                    rows.append(task)
        if not rows:
            self.show_warning("请先勾选要下载的任务（表格第一列 ）。")
            return
        save_dir = QFileDialog.getExistingDirectory(self.parent_widget, "选择保存目录")
        if not save_dir:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._dl_worker = Worker(lambda: _download_many(rows, save_dir))
        self._dl_worker.finished.connect(lambda msg: self.show_info(msg))
        self._dl_worker.error.connect(lambda e: self.show_error(f"批量下载失败：{e}", "错误"))
        self.track_worker(self._dl_worker)
        self._dl_worker.start()
        self.show_info(f"开始下载 {len(rows)} 个成片视频到 {save_dir}，请稍候…")

    def _download_selected_package(self):
        """批量下载已勾选任务的成片包（zip）。"""
        rows = []
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it and it.checkState() == Qt.Checked and 0 <= i < len(self._last_items):
                task = self._last_items[i]
                if _resolve_package_url(task):
                    rows.append(task)
        if not rows:
            self.show_warning("请先勾选支持打包下载的任务（表格第一列 ）。")
            return
        save_dir = QFileDialog.getExistingDirectory(self.parent_widget, "选择保存目录")
        if not save_dir:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._dl_worker = Worker(lambda: _download_many_packages(rows, save_dir))
        self._dl_worker.finished.connect(lambda msg: self.show_info(msg))
        self._dl_worker.error.connect(
            lambda e: self.show_error(f"批量打包失败：{e}", "错误"))
        self.track_worker(self._dl_worker)
        self._dl_worker.start()
        self.show_info(f"开始下载 {len(rows)} 个成片包到 {save_dir}，请稍候…")

    @staticmethod
    def _do_download(url, path):
        """后台下载：流式写文件；若端点返回 JSON（如 {url:...}）则取其地址重试一次。"""
        return _download_to_file(url, path)

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
        return {"product_montage": "产品成片", "video_montage": "产品成片", "compile_video": "产品成片",  # noqa: E501
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
                "failed": QColor("#e74c3c"), "pending": QColor("#888")}.get(s, QColor("#aaa"))  # noqa: E501

    @staticmethod
    def _fmt_time(s):
        """服务端返回 '2026-07-18 00:19:37.114321'，截到分钟。"""
        if not s:
            return "—"
        return str(s)[:16]


def _download_to_file(url, path):
    """下载服务端文件到本地（委托 scheduled_task_client.download_result_file）。"""
    return stc.download_result_file(url, path)


def _resolve_task_video_url(task):
    """从任务 result 解析成片 URL（相对路径拼服务端地址）。"""
    result = task.get("result") or {}
    raw = (result.get("video_url") or result.get("url")
           or result.get("output_url") or result.get("output_file")
           or result.get("file_url") or "")
    raw = str(raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    base = stc._server_url()
    if not base:
        return ""
    return base + raw if raw.startswith("/") else f"{base}/{raw}"


def _resolve_package_url(task):
    """从任务 result 解析打包下载 URL（成片+全部素材+manifest.json）。"""
    result = task.get("result") or {}
    raw = str(result.get("package_url") or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    base = stc._server_url()
    if not base:
        return ""
    return base + raw if raw.startswith("/") else f"{base}/{raw}"


def _download_many(tasks, save_dir):
    """批量下载成片视频到目录，单个失败继续；返回结果摘要文本。"""
    ok, fail = 0, []
    for task in tasks:
        tid = task.get("id") or ""
        try:
            url = _resolve_task_video_url(task)
            if not url:
                raise RuntimeError("任务没有可下载的成片地址")
            _download_to_file(
                url, os.path.join(save_dir, f"render_{tid}.mp4"))
            ok += 1
        except (OSError, requests.exceptions.RequestException, RuntimeError) as e:
            fail.append(f"{tid}: {e}")
    msg = f" 已下载 {ok} 个成片视频到：{save_dir}"
    if fail:
        msg += f"\n\n失败（{len(fail)} 个）：\n" + "\n".join(fail)
    return msg


def _download_many_packages(tasks, save_dir):
    """批量下载成片包（zip）到目录，单个失败继续；返回结果摘要文本。"""
    ok, fail = 0, []
    for task in tasks:
        tid = task.get("id") or ""
        try:
            url = _resolve_package_url(task)
            if not url:
                raise RuntimeError("任务没有打包下载地址")
            _download_to_file(
                url, os.path.join(save_dir, f"render_{tid}_package.zip"))
            ok += 1
        except (OSError, requests.exceptions.RequestException, RuntimeError) as e:
            fail.append(f"{tid}: {e}")
    msg = f" 已下载 {ok} 个成片包到：{save_dir}"
    if fail:
        msg += f"\n\n失败（{len(fail)} 个）：\n" + "\n".join(fail)
    return msg
