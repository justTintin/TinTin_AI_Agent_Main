# -*- coding: utf-8 -*-
"""
📈 热点追踪页。

看各平台(抖音/小红书/B站)今日热榜 + 趋势(上榜天数/排名变化)，按 科技/数码/AI 筛选，
并把热点蒸馏归纳为「选题方向」写入「我的知识库」。

采集在素材浏览器(Electron)里做；本页负责 导入趋势库 / 查看 / 蒸馏。
"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)
from PySide6.QtCore import Qt, Signal

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.hotspot_manager import HotspotManager
from utils.my_knowledge_manager import MyKnowledgeManager
from utils import asset_browser_client as abrowser
from utils import knowledge_distiller

PLATFORM_CN = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}


class _HotspotDistillWorker(BaseWorker):
    finished = Signal(tuple)
    progress = Signal(str)

    def __init__(self, hot_mgr, kb_mgr, cfg):
        super().__init__()
        self.hot_mgr, self.kb_mgr, self.cfg = hot_mgr, kb_mgr, cfg

    def do_work(self):
        res = knowledge_distiller.distill_hotspots(
            self.hot_mgr, self.kb_mgr, self.cfg, progress_cb=lambda m: self.progress.emit(m))
        self.finished.emit(res)


class HotspotPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.manager = HotspotManager()

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(16)

        heading = QLabel("📈 热点追踪")
        heading.setObjectName("heading")
        root.addWidget(heading)
	        sub = QLabel("跟踪 抖音 / 小红书 / B站 每日热榜并记录趋势（上榜天数·排名变化），"
                     "聚焦 科技 / 数码 / AI，可一键蒸馏为「选题方向」知识。")
        sub.setObjectName("muted_text")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # 操作条
        bar = QHBoxLayout()
        btn_capture = QPushButton("🌐 抓取今日热点")
        btn_capture.setObjectName("secondary_button")
        btn_capture.setToolTip("启动素材浏览器，依次打开各平台热榜页采集")
        btn_capture.clicked.connect(self._capture)
        bar.addWidget(btn_capture)
        btn_import = QPushButton("⬇️ 导入最新")
        btn_import.setObjectName("primary_button")
        btn_import.clicked.connect(self._import)
        bar.addWidget(btn_import)
        self.btn_distill = QPushButton("🧪 蒸馏热点选题")
        self.btn_distill.setObjectName("secondary_button")
        self.btn_distill.clicked.connect(self._distill)
        bar.addWidget(self.btn_distill)
        self.status = QLabel("")
        self.status.setObjectName("muted_text")
        bar.addWidget(self.status)
        bar.addStretch(1)
        root.addLayout(bar)

        # 筛选条
        filt = QHBoxLayout()
        filt.addWidget(QLabel("平台"))
        self.f_platform = QComboBox()
        self.f_platform.addItem("全部", None)
        for k, v in PLATFORM_CN.items():
            self.f_platform.addItem(v, k)
        self.f_platform.currentIndexChanged.connect(self.refresh_table)
        filt.addWidget(self.f_platform)
        filt.addWidget(QLabel("分类"))
        self.f_cat = QComboBox()
        self.f_cat.addItem("仅 科技/数码/AI", "__tech__")
        self.f_cat.addItem("全部", None)
        for c in ("AI", "数码", "科技"):
            self.f_cat.addItem(c, c)
        self.f_cat.currentIndexChanged.connect(self.refresh_table)
        filt.addWidget(self.f_cat)
        self.f_kw = QLineEdit()
        self.f_kw.setPlaceholderText("搜索标题…")
        self.f_kw.textChanged.connect(self.refresh_table)
        filt.addWidget(self.f_kw, 1)
        root.addLayout(filt)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["平台", "标题", "最新排名", "上榜天数", "最佳排名", "分类", "热度"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        # 打开时静默合并定时任务采集到的最新快照（无新数据时无声忽略）
        try:
            self.manager.import_snapshots()
        except Exception:
            pass
        self.refresh_table()

    # ---------------- 数据 ----------------
    def refresh_table(self):
        cat_data = self.f_cat.currentData()
        tech_only = cat_data == "__tech__"
        category = None if cat_data in ("__tech__", None) else cat_data
        rows = self.manager.query(
            category=category, platform=self.f_platform.currentData(),
            keyword=self.f_kw.text(), tech_only=tech_only)
        self.table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            vals = [
                PLATFORM_CN.get(t.get("platform"), t.get("platform", "")),
                t.get("title", ""),
                str(t.get("latest_rank") if t.get("latest_rank") is not None else "-"),
                str(t.get("days_on_board", 1)),
                str(t.get("best_rank") if t.get("best_rank") is not None else "-"),
                "/".join(t.get("categories") or []) or "-",
                str((t.get("history") or [{}])[-1].get("hot", "")),
            ]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.status.setText(f"共 {len(rows)} 条话题（库内 {len(self.manager.all_topics())} 条）")

    def _capture(self):
        ok, msg = abrowser.launch_hotspot_capture(auto_quit=False)
        if ok:
            self.show_info(f"{msg}\n\n采集完成后回本页点「⬇️ 导入最新」更新趋势。", "已启动采集")
        else:
            self.show_error(msg, "无法启动采集")

    def _import(self):
        new_n, upd_n, dates, msg = self.manager.import_snapshots()
        self.refresh_table()
        (self.show_info if (new_n or upd_n) else self.show_warning)(msg, "导入")

    def _distill(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        cfg = {"api_url": ai.get("llm_api_url", ""), "api_key": ai.get("llm_api_key", ""),
               "model": ai.get("llm_model", "deepseek-chat")}
        if not (cfg["api_url"] and cfg["api_key"]):
            self.show_warning("请先在「AI 设置」配置 LLM。", "未配置 LLM")
            return
        if not self.manager.query(tech_only=True):
            self.show_warning("热点库里还没有 科技/数码/AI 话题。请先采集并导入。", "无可蒸馏热点")
            return
        self.btn_distill.setEnabled(False)
        self.status.setText("正在把热点蒸馏为选题方向…")
        self._dw = _HotspotDistillWorker(self.manager, MyKnowledgeManager(), cfg)
        self._dw.progress.connect(lambda m: self.status.setText(m))

        def on_done(res):
            created, updated, msg = res
            self.btn_distill.setEnabled(True)
            self.status.setText("")
            self.show_info(msg + "\n已写入「我的知识库」→ 选题方向。", "热点蒸馏完成")

        def on_err(e):
            self.btn_distill.setEnabled(True)
            self.status.setText("")
            self.show_error(f"蒸馏失败：{e}")

        self._dw.finished.connect(on_done)
        self._dw.error.connect(on_err)
        self._dw.start()
