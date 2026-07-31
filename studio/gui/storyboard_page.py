# -*- coding: utf-8 -*-
"""
「分镜脚本创作」页

流程：输入/接收视频文案 → 生成分镜脚本（竖向列表，每镜头含镜别/时长/音效/画面描述/旁白）
      → 每镜头可引用素材（本地/即梦/MG/联网） → 批量生成即梦镜头图 → 飞书同步
"""
import json
import os
import time
from datetime import datetime

import configparser

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QFrame, QWidget, QComboBox, QMessageBox, QProgressBar, QScrollArea,
    QSplitter, QDialog, QListWidget, QListWidgetItem, QTabWidget, QSpinBox,
    QRadioButton, QButtonGroup, QCheckBox, QDialogButtonBox,
)
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtCore import Qt, Signal, QUrl

from utils.logger_utils import log
from utils.base_worker import BaseWorker
from utils.my_knowledge_manager import MyKnowledgeManager, STYLIZATION_TYPE
from utils.dreamina_client import DreaminaClient
from config.paths import DREAMINA_OUTPUT_DIR, CONFIG_INI_FILE, MATERIALS_DIR, KNOWLEDGE_MATERIALS_DIR, KNOWLEDGE_MEDIA_DIR
from gui.ai_script_page import LLMWorker, FeishuUploadWorker, WebSearchWorker
from gui.base_page import BasePage
from gui.searchable_combo import SearchableComboBox

SHOT_TYPES = ["特写", "近景", "中景", "远景", "全景", "俯拍", "仰拍", "主观", "空镜"]


# ─────────────────────────────── Workers ────────────────────────────────────

class BatchShotImageWorker(BaseWorker):
    """逐镜头调用即梦 text2image 出图。"""
    phase = Signal(str)
    shot_done = Signal(int, str)
    finished = Signal(list)

    def __init__(self, shots, ratio, out_dir):
        super().__init__()
        self.shots = shots   # [(idx, prompt)]
        self.ratio = ratio
        self.out_dir = out_dir

    def do_work(self):
        client = DreaminaClient()
        if not client.is_installed():
            raise RuntimeError("未找到即梦 CLI，请先在『即梦生成』页安装二进制。")
        logged, _ = client.is_logged_in()
        if not logged:
            raise RuntimeError("即梦未登录，请先到『即梦生成』页登录。")
        total = len(self.shots)
        all_files = []
        for n, (idx, prompt) in enumerate(self.shots, 1):
            self.phase.emit(f"镜头 {n}/{total} 提交中…")
            _, info = client.text2image(prompt, ratio=self.ratio, poll=0)
            submit_id = info.get("submit_id", "")
            if not submit_id:
                self.phase.emit(f"镜头 {n}/{total} 提交失败，跳过")
                continue
            shot_dir = os.path.join(self.out_dir, f"shot_{idx:02d}")
            for _ in range(40):
                info2, files = client.query_result(submit_id, download_dir=shot_dir)
                if files:
                    all_files.extend(files)
                    self.shot_done.emit(idx, files[0])
                    break
                if info2.get("gen_status") == "fail":
                    self.phase.emit(f"镜头 {n}/{total} 生成失败")
                    break
                self.phase.emit(f"镜头 {n}/{total} 出图中…")
                time.sleep(6)
        self.finished.emit(all_files)


class SingleShotImageWorker(BaseWorker):
    """单镜头即梦 text2image（供「引用素材」对话框使用）。"""
    done = Signal(str)   # 生成图片的本地路径

    def __init__(self, prompt, ratio, out_dir):
        super().__init__()
        self.prompt = prompt
        self.ratio = ratio
        self.out_dir = out_dir

    def do_work(self):
        client = DreaminaClient()
        if not client.is_installed():
            raise RuntimeError("未找到即梦 CLI")
        _, info = client.text2image(self.prompt, ratio=self.ratio, poll=0)
        submit_id = info.get("submit_id", "")
        if not submit_id:
            raise RuntimeError("即梦提交失败")
        os.makedirs(self.out_dir, exist_ok=True)
        for _ in range(40):
            info2, files = client.query_result(submit_id, download_dir=self.out_dir)
            if files:
                self.done.emit(files[0])
                return
            if info2.get("gen_status") == "fail":
                raise RuntimeError("即梦生成失败")
            time.sleep(6)
        raise RuntimeError("即梦生成超时（>4 分钟）")


# ─────────────────────────── 相似度检索 Worker ──────────────────────────────

class _SimilarSearchWorker(BaseWorker):
    """按文案做 CLIP 向量相似度检索，返回按 score 排序的素材（已按 material 去重）。"""
    finished = Signal(list)   # [dict, ...]

    def __init__(self, query: str, top_k: int = 30,
                 filter_brand: str = "", filter_category: str = "",
                 filter_path_prefix: str = ""):
        super().__init__()
        self.query = query
        self.top_k = top_k
        self.filter_brand = filter_brand or None
        self.filter_category = filter_category or None
        self.filter_path_prefix = filter_path_prefix or None

    def do_work(self):
        None  # material_clip_indexer removed
        rows, _total = search_by_text(
            self.query,
            top_k=max(self.top_k * 3, self.top_k),   # 多取一些用于按文件去重
            filter_brand=self.filter_brand,
            filter_category=self.filter_category,
            filter_path_prefix=self.filter_path_prefix,
            comprehensive=True,
        )
        # 按 material_id / path 去重，保留每个素材的最高分帧
        best = {}
        for r in rows:
            key = r.get("material_id") or r.get("path")
            if key is None:
                continue
            if key not in best or r.get("score", 0) > best[key].get("score", 0):
                best[key] = r
        merged = sorted(best.values(), key=lambda x: x.get("score", 0), reverse=True)
        self.finished.emit(merged[: self.top_k])


class _AutoBindShotsWorker(BaseWorker):
    """为每个镜头按其画面描述做相似度检索，自动匹配最相似素材。"""
    progress = Signal(int, int)          # done, total
    finished = Signal(dict)              # {shot_index: material_dict}

    def __init__(self, shots: list, min_score: float = 0.0,
                 filter_brand: str = "", filter_category: str = "",
                 filter_path_prefix: str = ""):
        super().__init__()
        # shots: [(shot_index, query_text), ...]
        self.shots = shots
        self.min_score = min_score
        self.filter_brand = filter_brand or None
        self.filter_category = filter_category or None
        self.filter_path_prefix = filter_path_prefix or None

    def do_work(self):
        None  # material_clip_indexer removed
        result = {}
        total = len(self.shots)
        for n, (shot_idx, query) in enumerate(self.shots, 1):
            self.progress.emit(n, total)
            q = (query or "").strip()
            if not q:
                continue
            try:
                rows, _total = search_by_text(
                    q, top_k=5,
                    filter_brand=self.filter_brand,
                    filter_category=self.filter_category,
                    filter_path_prefix=self.filter_path_prefix,
                    comprehensive=True,
                )
            except Exception:
                rows = []
            if not rows:
                continue
            top = rows[0]
            score = float(top.get("score", 0) or 0)
            if score < self.min_score:
                continue
            result[shot_idx] = {
                "type": "local",
                "path": top.get("path", ""),
                "name": top.get("filename", ""),
                "hash": top.get("file_hash", ""),
                "score": score,
            }
        self.finished.emit(result)


# ─────────────────────────── 引用素材对话框 ─────────────────────────────────

class ShotMaterialDialog(QDialog):
    """每个镜头的「引用素材」弹窗，包含四个来源：本地素材/即梦生成/MG动画/联网素材。"""

    def __init__(self, shot_desc="", ratio="9:16", main_window=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("引用素材")
        self.resize(1300, 850)
        self.setMinimumSize(1100, 750)
        self.selected_material = None
        self._web_worker = None
        self._img_worker = None
        self._ratio = ratio
        self._main_window = main_window
        self._setup(shot_desc)

    def _setup(self, shot_desc):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.tabs = QTabWidget()

        # ── Tab 1: 本地素材 ──────────────────────────────────────────
        local_tab = QWidget()
        lt = QVBoxLayout(local_tab)
        lt.setSpacing(8)
        row = QHBoxLayout()
        self.local_input = QLineEdit()
        self.local_input.setPlaceholderText("按镜头文案做相似度检索素材库（CLIP 向量匹配）")
        self.local_input.setText(shot_desc[:120] if shot_desc else "")
        self.local_input.returnPressed.connect(self._search_local)
        row.addWidget(self.local_input, 1)
        btn_local = QPushButton("🎯 相似度检索")
        btn_local.clicked.connect(self._search_local)
        row.addWidget(btn_local)
        lt.addLayout(row)
        self.local_list = QListWidget()
        self.local_list.itemDoubleClicked.connect(self._select_local_item)
        self.local_list.itemSelectionChanged.connect(self._on_local_sel_changed)
        lt.addWidget(self.local_list, 1)
        lt.addWidget(self._muted("按相似度从高到低排序，双击选择；相似度越高越贴合镜头画面描述"))
        self.tabs.addTab(local_tab, "🗂️ 素材库")

        # ── Tab 2: 即梦生成 ──────────────────────────────────────────
        dreamina_tab = QWidget()
        dt = QVBoxLayout(dreamina_tab)
        dt.setSpacing(8)
        dt.addWidget(self._muted(f"以镜头画面描述为提示词，调用即梦生成镜头参考图（画幅 {self._ratio}）"))
        prow = QHBoxLayout()
        self.dreamina_input = QTextEdit()
        self.dreamina_input.setPlainText(shot_desc)
        self.dreamina_input.setFixedHeight(70)
        self.dreamina_input.setPlaceholderText("即梦生图提示词（英文/中文均可）")
        prow.addWidget(self.dreamina_input, 1)
        dt.addLayout(prow)
        gen_row = QHBoxLayout()
        self.btn_dreamina_gen = QPushButton("🎨 生成镜头参考图（即梦）")
        self.btn_dreamina_gen.setObjectName("primary_button")
        self.btn_dreamina_gen.clicked.connect(self._dreamina_gen)
        gen_row.addWidget(self.btn_dreamina_gen)
        self.dreamina_pbar = QProgressBar()
        self.dreamina_pbar.setRange(0, 0)
        self.dreamina_pbar.setVisible(False)
        gen_row.addWidget(self.dreamina_pbar)
        gen_row.addStretch()
        dt.addLayout(gen_row)
        self.dreamina_thumb = QLabel("（未生成）")
        self.dreamina_thumb.setAlignment(Qt.AlignCenter)
        self.dreamina_thumb.setFixedHeight(200)
        self.dreamina_thumb.setStyleSheet("border:1px solid #3a3a3a; border-radius:4px;")
        self.dreamina_thumb.setObjectName("muted_text")
        dt.addWidget(self.dreamina_thumb, 1)
        self.btn_dreamina_select = QPushButton("✅ 选择此图作为镜头素材")
        self.btn_dreamina_select.setObjectName("secondary_button")
        self.btn_dreamina_select.setEnabled(False)
        self.btn_dreamina_select.clicked.connect(self._select_dreamina)
        dt.addWidget(self.btn_dreamina_select)
        self._dreamina_file = None
        self.tabs.addTab(dreamina_tab, "🎨 即梦生成")

        # ── Tab 3: MG 动画 ───────────────────────────────────────────
        mg_tab = QWidget()
        mg = QVBoxLayout(mg_tab)
        mg.setSpacing(12)
        mg.addStretch()
        mg_lbl = QLabel("MG 动画素材适合用作开场/标题/卡点/数字增长等动态素材，\n"
                         "请在「MG 动画」页完成制作后，回到此处通过「本地素材」选项卡选取。")
        mg_lbl.setAlignment(Qt.AlignCenter)
        mg_lbl.setWordWrap(True)
        mg.addWidget(mg_lbl)
        btn_mg_jump = QPushButton("🎞️ 跳转到 MG 动画页")
        btn_mg_jump.setObjectName("secondary_button")
        btn_mg_jump.clicked.connect(self._open_mg)
        mg.addWidget(btn_mg_jump, 0, Qt.AlignCenter)
        mg.addStretch()
        self.tabs.addTab(mg_tab, "🎞️ MG动画")

        # ── Tab 4: 联网素材 ──────────────────────────────────────────
        web_tab = QWidget()
        wt = QVBoxLayout(web_tab)
        wt.setSpacing(8)
        web_row = QHBoxLayout()
        self.web_input = QLineEdit()
        self.web_input.setPlaceholderText("输入搜索词，联网查找参考素材（DuckDuckGo）")
        self.web_input.setText(shot_desc[:80] if shot_desc else "")
        self.web_input.returnPressed.connect(self._search_web)
        web_row.addWidget(self.web_input, 1)
        self.btn_web = QPushButton("联网搜索")
        self.btn_web.clicked.connect(self._search_web)
        web_row.addWidget(self.btn_web)
        wt.addLayout(web_row)
        self.web_pbar = QProgressBar()
        self.web_pbar.setRange(0, 0)
        self.web_pbar.setVisible(False)
        wt.addWidget(self.web_pbar)
        self.web_results = QTextEdit()
        self.web_results.setReadOnly(True)
        self.web_results.setPlaceholderText("点击「联网搜索」查找相关参考资料...")
        wt.addWidget(self.web_results, 1)
        self.tabs.addTab(web_tab, "🌐 联网素材")

        layout.addWidget(self.tabs, 1)

        # ── 底部按钮 ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_confirm = QPushButton("✅ 确认选择")
        self.btn_confirm.setObjectName("primary_button")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._confirm)
        btn_row.addWidget(self.btn_confirm)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._search_local()   # auto-load local on open

    @staticmethod
    def _muted(text):
        lbl = QLabel(text)
        lbl.setObjectName("muted_text")
        lbl.setWordWrap(True)
        return lbl

    # ── 本地素材（CLIP 相似度检索）────────────────────────────────────
    def _search_local(self):
        query = self.local_input.text().strip()
        self.local_list.clear()
        self.btn_confirm.setEnabled(False)
        if not query:
            self.local_list.addItem(QListWidgetItem("请输入或保留镜头文案后点「相似度检索」"))
            return

        self.local_list.addItem(QListWidgetItem("正在做相似度检索…"))
        self._sim_worker = _SimilarSearchWorker(query, top_k=30)
        self._sim_worker.finished.connect(self._on_similar_results)
        self._sim_worker.error.connect(self._on_similar_error)
        self._sim_worker.start()

    def _on_similar_error(self, msg):
        self.local_list.clear()
        self.local_list.addItem(QListWidgetItem(f"检索失败: {msg}"))

    def _on_similar_results(self, found):
        self.local_list.clear()
        if not found:
            self.local_list.addItem(QListWidgetItem("未找到相似素材，请调整镜头文案或先入库分析素材"))
            return
        for f in found:
            b = f.get("brand", "") or ""
            m = f.get("model", "") or ""
            info = f"{b} {m}".strip()
            score = float(f.get("score", 0) or 0)
            label = f"[{score*100:5.1f}%]  [{f.get('media_type','?')}]  {f.get('filename','?')}"
            if info:
                label += f"  —  {info}"
            item = QListWidgetItem(label)
            # 归一化成本地素材选择所需字段
            item.setData(Qt.UserRole, {
                "path": f.get("path", ""),
                "filename": f.get("filename", ""),
                "file_hash": f.get("file_hash", ""),
                "media_type": f.get("media_type", ""),
                "brand": b, "model": m,
                "product": f.get("product", ""),
                "score": score,
            })
            item.setToolTip(
                f"{f.get('path','')}\n相似度: {score*100:.1f}%\n"
                f"画面: {f.get('scene_desc_primary','') or '—'}"
            )
            self.local_list.addItem(item)

    def _on_local_sel_changed(self):
        if self.tabs.currentIndex() != 0:
            return
        items = self.local_list.selectedItems()
        self.btn_confirm.setEnabled(bool(items and items[0].data(Qt.UserRole)))

    def _select_local_item(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.selected_material = {
                "type": "local",
                "path": data.get("path", ""),
                "name": data.get("filename", ""),
                "hash": data.get("file_hash", ""),
            }
            self.accept()

    # ── 即梦生成 ─────────────────────────────────────────────────────
    def _dreamina_gen(self):
        prompt = self.dreamina_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示词为空", "请填写即梦生图提示词。")
            return
        self.btn_dreamina_gen.setEnabled(False)
        self.dreamina_pbar.setVisible(True)
        self.dreamina_thumb.setText("生成中，请稍候（约 1-4 分钟）...")
        self._dreamina_file = None
        self.btn_dreamina_select.setEnabled(False)

        out_dir = os.path.join(DREAMINA_OUTPUT_DIR, "shot_ref_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        self._img_worker = SingleShotImageWorker(prompt, self._ratio, out_dir)

        def on_done(path):
            self.btn_dreamina_gen.setEnabled(True)
            self.dreamina_pbar.setVisible(False)
            self._dreamina_file = path
            pm = QPixmap(path)
            if not pm.isNull():
                self.dreamina_thumb.setPixmap(
                    pm.scaled(self.dreamina_thumb.width(), 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.btn_dreamina_select.setEnabled(True)

        def on_err(msg):
            self.btn_dreamina_gen.setEnabled(True)
            self.dreamina_pbar.setVisible(False)
            self.dreamina_thumb.setText(f"生成失败：{msg}")

        self._img_worker.done.connect(on_done)
        self._img_worker.error.connect(on_err)
        self._img_worker.start()

    def _select_dreamina(self):
        if self._dreamina_file:
            self.selected_material = {
                "type": "dreamina",
                "path": self._dreamina_file,
                "name": os.path.basename(self._dreamina_file),
            }
            self.accept()

    # ── MG 动画 ──────────────────────────────────────────────────────
    def _open_mg(self):
        try:
            if self._main_window:
                self._main_window.switch_page(36)
        except Exception:
            pass
        self.reject()

    # ── 联网搜索 ─────────────────────────────────────────────────────
    def _search_web(self):
        query = self.web_input.text().strip()
        if not query:
            return
        self.btn_web.setEnabled(False)
        self.web_pbar.setVisible(True)
        self.web_results.setPlainText("正在搜索，请稍候...")
        self._web_worker = WebSearchWorker(query)
        self._web_worker.finished.connect(lambda t: (
            self.btn_web.setEnabled(True),
            self.web_pbar.setVisible(False),
            self.web_results.setPlainText(t or "未找到结果"),
        ))
        self._web_worker.error.connect(lambda m: (
            self.btn_web.setEnabled(True),
            self.web_pbar.setVisible(False),
            self.web_results.setPlainText(f"搜索失败：{m}"),
        ))
        self._web_worker.start()

    # ── Tab 切换时更新确认按钮 ───────────────────────────────────────
    def _on_tab_changed(self, idx):
        if idx == 0:
            self._on_local_sel_changed()
        elif idx == 1:
            self.btn_confirm.setEnabled(self._dreamina_file is not None)
        else:
            self.btn_confirm.setEnabled(False)

    # ── 确认 ─────────────────────────────────────────────────────────
    def _confirm(self):
        tab = self.tabs.currentIndex()
        if tab == 0:
            items = self.local_list.selectedItems()
            if items:
                data = items[0].data(Qt.UserRole)
                if data:
                    self.selected_material = {
                        "type": "local",
                        "path": data.get("path", ""),
                        "name": data.get("filename") or data.get("name", ""),
                        "hash": data.get("file_hash", ""),
                    }
                    self.accept()
        elif tab == 1:
            self._select_dreamina()


# ─────────────────────────────── Main Page ──────────────────────────────────

class StoryboardPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.shot_cards = []
        self._selected_stylization = None
        self.feishu_record = None

    # ──────────────────────────── UI ────────────────────────────────
    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # 标题行：仅标题（长描述独立一行，避免被右上角资源监控遮挡）
        heading = QLabel("🎬 分镜脚本创作")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        desc = QLabel("视频分镜设计 + 即梦 / MG 动画素材生成")
        desc.setObjectName("muted_text")
        layout.addWidget(desc)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("themeSplitter")
        left = self._build_left()
        right = self._build_right()
        # 左栏固定最小宽度，避免被压缩/遮盖（参考图像抠图页的左卡面板）
        left.setMinimumWidth(320)
        right.setMinimumWidth(420)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)   # 左栏不随窗口拉伸
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 920])
        layout.addWidget(splitter, 1)

        status_row = QHBoxLayout()
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("muted_text")
        status_row.addWidget(self.lbl_status)
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setRange(0, 0)
        self.pbar.setMaximumWidth(200)
        status_row.addWidget(self.pbar)
        layout.addLayout(status_row)

        self._reload_stylizations()

    def _build_left(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 10, 0)
        col.setSpacing(14)

        # ── 风格化 ────────────────────────────────────────────
        card_style = QFrame()
        card_style.setObjectName("card")
        sp = QVBoxLayout(card_style)
        sp.setContentsMargins(20, 16, 20, 16)
        sp.setSpacing(10)

        sp.addWidget(self._card_title("🎨 风格化（可选）"))

        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("风格化"))
        self.combo_stylization = SearchableComboBox(placeholder="输入风格名称搜索…")
        self.combo_stylization.addItem("── 不使用风格化 ──", None)
        self.combo_stylization.currentIndexChanged.connect(self._on_stylization_selected)
        ratio_row.addWidget(self.combo_stylization, 1)
        sp.addLayout(ratio_row)

        sp.addWidget(self._muted_lbl("风格画像："))
        self.text_style_portrait = QTextEdit()
        self.text_style_portrait.setReadOnly(True)
        self.text_style_portrait.setFixedHeight(75)
        self.text_style_portrait.setPlaceholderText("选择风格化后在此显示...")
        sp.addWidget(self.text_style_portrait)

        sp.addWidget(self._muted_lbl("附加提示词（调整文案）："))
        self.edit_extra_prompt = QTextEdit()
        self.edit_extra_prompt.setFixedHeight(55)
        self.edit_extra_prompt.setPlaceholderText("可输入补充要求，配合风格化通过大模型重新调整视频文案...")
        sp.addWidget(self.edit_extra_prompt)

        self.btn_adjust_copy = QPushButton("🔄 大模型调整文案")
        self.btn_adjust_copy.setObjectName("secondary_button")
        self.btn_adjust_copy.clicked.connect(self._adjust_copy)
        sp.addWidget(self.btn_adjust_copy)

        col.addWidget(card_style)

        # ── 视频文案 ──────────────────────────────────────────────────
        card_copy = QFrame()
        card_copy.setObjectName("card")
        cp = QVBoxLayout(card_copy)
        cp.setContentsMargins(20, 16, 20, 16)
        cp.setSpacing(10)

        cp.addWidget(self._card_title("📝 视频文案（可在此处精简或重新编辑）"))

        self.edit_copy = QTextEdit()
        self.edit_copy.setPlaceholderText(
            "请在此输入需要拆解分镜的视频文案；或由产品文案创作页点击「前往分镜设计」自动传入。"
        )
        self.edit_copy.setMinimumHeight(260)
        cp.addWidget(self.edit_copy, 1)

        self.btn_gen_sb = QPushButton("生成分镜脚本")
        self.btn_gen_sb.setObjectName("primary_button")
        self.btn_gen_sb.clicked.connect(self._generate_storyboard)
        cp.addWidget(self.btn_gen_sb)

        col.addWidget(card_copy, 1)
        scroll.setWidget(container)
        return scroll

    def _build_right(self):
        panel = QWidget()
        col = QVBoxLayout(panel)
        col.setContentsMargins(10, 0, 0, 0)
        col.setSpacing(10)

        # ── 分镜脚本头部 ──────────────────────────────────────────────
        card_sb = QFrame()
        card_sb.setObjectName("card")
        sb = QVBoxLayout(card_sb)
        sb.setContentsMargins(20, 14, 20, 14)
        sb.setSpacing(10)

        # 头信息行
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("🎬 分镜脚本（可直接编辑各镜头字段）"))
        hdr.addStretch()

        self.btn_auto_bind = QPushButton("🎯 相似度自动绑定")
        self.btn_auto_bind.setObjectName("secondary_button")
        self.btn_auto_bind.setToolTip("按每个镜头的画面描述做 CLIP 相似度检索，自动绑定最相似素材")
        self.btn_auto_bind.clicked.connect(self._auto_bind_materials)
        hdr.addWidget(self.btn_auto_bind)

        lbl_ratio = QLabel("画幅")
        lbl_ratio.setObjectName("muted_text")
        hdr.addWidget(lbl_ratio)
        
        self.combo_shot_ratio = QComboBox()
        self.combo_shot_ratio.addItems(["9:16", "16:9", "1:1"])
        self.combo_shot_ratio.setFixedWidth(80)
        self.combo_shot_ratio.currentTextChanged.connect(self._update_sb_header)
        hdr.addWidget(self.combo_shot_ratio)
        
        sb.addLayout(hdr)

        # 另起一行放画幅、时长等信息（使用橙色）
        self.lbl_sb_info = QLabel("总时长：0 s  |  0 镜  （竖屏）")
        self.lbl_sb_info.setStyleSheet("color: #ff9800; font-weight: bold; font-size: 12px; margin-left: 2px;")
        sb.addWidget(self.lbl_sb_info)

        # 镜头列表（垂直滚动，每镜头一行）
        self.sb_scroll = QScrollArea()
        self.sb_scroll.setWidgetResizable(True)
        self.sb_scroll.setFrameShape(QScrollArea.NoFrame)
        self.sb_container = QWidget()
        self.sb_col = QVBoxLayout(self.sb_container)
        self.sb_col.setSpacing(8)
        self.sb_col.setContentsMargins(0, 0, 0, 0)
        self.sb_col.addStretch()
        self.sb_scroll.setWidget(self.sb_container)
        sb.addWidget(self.sb_scroll, 1)

        # 飞书同步行
        feishu_row = QHBoxLayout()
        self.lbl_feishu_info = QLabel("飞书关联：无")
        self.lbl_feishu_info.setObjectName("muted_text")
        feishu_row.addWidget(self.lbl_feishu_info)
        feishu_row.addStretch()
        self.btn_sync_bitable = QPushButton("📊 同步到多维表格")
        self.btn_sync_bitable.setObjectName("secondary_button")
        self.btn_sync_bitable.setEnabled(False)
        self.btn_sync_bitable.clicked.connect(lambda: self._upload_to_feishu("bitable"))
        feishu_row.addWidget(self.btn_sync_bitable)
        self.btn_sync_docx = QPushButton("📝 创建飞书文档")
        self.btn_sync_docx.setObjectName("secondary_button")
        self.btn_sync_docx.setEnabled(False)
        self.btn_sync_docx.clicked.connect(lambda: self._upload_to_feishu("docx"))
        feishu_row.addWidget(self.btn_sync_docx)
        sb.addLayout(feishu_row)

        appid, appsecret, *_ = self._get_feishu_config()
        if appid and appsecret:
            self.btn_sync_bitable.setEnabled(True)
            self.btn_sync_docx.setEnabled(True)

        # 底部操作行
        bottom_row = QHBoxLayout()
        btn_save = QPushButton("💾 保存分镜脚本")
        btn_save.setObjectName("secondary_button")
        btn_save.setToolTip("将分镜脚本（JSON + 文本）保存到素材管理目录")
        btn_save.clicked.connect(self._save_storyboard)
        bottom_row.addWidget(btn_save)
        bottom_row.addStretch()
        sb.addLayout(bottom_row)

        col.addWidget(card_sb, 1)
        return panel

    # ──────────────────── 小部件辅助 ────────────────────────────────
    @staticmethod
    def _card_title(text):
        lbl = QLabel(text)
        lbl.setObjectName("card_title")
        return lbl

    @staticmethod
    def _muted_lbl(text):
        lbl = QLabel(text)
        lbl.setObjectName("muted_text")
        return lbl

    # ──────────────────── 数据传递 ──────────────────────────────────
    def set_copywriting(self, text, feishu_record=None, ratio=None, stylization_id=None):
        self.edit_copy.setPlainText(text)
        self.feishu_record = feishu_record
        if feishu_record:
            self.lbl_feishu_info.setText(f"🔗 已关联飞书选题: {feishu_record.get('topic', '')}")
            self.btn_sync_bitable.setEnabled(True)
            self.btn_sync_docx.setEnabled(True)
            self.lbl_status.setText("已载入飞书选题文案，请点击「生成分镜脚本」开始拆解。")
        else:
            self.lbl_feishu_info.setText("飞书关联：无")
            self.btn_sync_bitable.setEnabled(False)
            appid, appsecret, *_ = self._get_feishu_config()
            self.btn_sync_docx.setEnabled(bool(appid and appsecret))
            self.lbl_status.setText("已载入文案，请点击「生成分镜脚本」。")

        if ratio and ratio in ["9:16", "16:9", "1:1"]:
            self.combo_shot_ratio.setCurrentText(ratio)

        if stylization_id:
            for i in range(self.combo_stylization.count()):
                data = self.combo_stylization.itemData(i)
                if isinstance(data, dict) and data.get("id") == stylization_id:
                    self.combo_stylization.setCurrentIndex(i)
                    break

    def reload_sources(self):
        self._reload_stylizations()

    # ──────────────────── 保存分镜脚本 ──────────────────────────────
    def _default_storyboard_name(self):
        """从文案首行 + 日期生成默认文件名。"""
        import re as _re
        date_str = datetime.now().strftime("%Y%m%d")
        title = ""
        if self.feishu_record:
            title = self.feishu_record.get("topic", "")
        if not title:
            copy = self.edit_copy.toPlainText().strip()
            for line in copy.split("\n"):
                line = line.strip()
                if len(line) >= 4:
                    title = line[:20]
                    break
        title = _re.sub(r'[\\/:*?"<>|\r\n\t#*【】\[\]]', "_", title).strip("_") or "分镜脚本"
        return f"{date_str}_{title}"

    def _collect_shots(self):
        shots = []
        for c in self.shot_cards:
            mat = c.get("material") or {}
            shots.append({
                "index": c["idx"],
                "shot_type": c["combo_type"].currentText(),
                "duration": c["spin_dur"].value(),
                "sfx": c["edit_sfx"].text().strip(),
                "visual": c["desc"].toPlainText().strip(),
                "narration": c["narration"].toPlainText().strip(),
                "material_type": mat.get("type", ""),
                "material_path": mat.get("path", ""),
                "material_hash": mat.get("hash", ""),
            })
        return shots

    def _save_storyboard(self):
        if not self.shot_cards:
            self.show_warning("当前没有分镜内容，请先生成分镜脚本。", "无内容")
            return

        default_name = self._default_storyboard_name()
        ratio = self.combo_shot_ratio.currentText()
        style_name = self._selected_stylization.get("name", "") if self._selected_stylization else ""
        shots = self._collect_shots()
        orient = {"9:16": "竖屏", "16:9": "横屏", "1:1": "方形"}.get(ratio, ratio)
        total_dur = sum(s["duration"] for s in shots)
        topic = (self.feishu_record or {}).get("topic", "") or default_name

        # ── 保存选项对话框 ──
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("保存分镜脚本")
        dlg.setMinimumWidth(380)
        dl = QVBoxLayout(dlg)
        dl.setSpacing(10)

        dl.addWidget(QLabel(f"共 {len(shots)} 镜 · {total_dur}s · {orient}（{ratio}）"))

        dl.addWidget(QLabel("文件名（不含扩展名）："))
        name_edit = QLineEdit(default_name)
        dl.addWidget(name_edit)

        dl.addWidget(QLabel("导出格式："))
        bg = QButtonGroup(dlg)
        fmt_excel = QRadioButton("Excel（.xlsx）— 默认")
        fmt_md = QRadioButton("Markdown（.md）")
        fmt_json = QRadioButton("JSON（.json，供脚本成片）")
        fmt_both = QRadioButton("Excel + Markdown")
        fmt_all = QRadioButton("Excel + Markdown + JSON")
        fmt_excel.setChecked(True)
        for rb in (fmt_excel, fmt_md, fmt_json, fmt_both, fmt_all):
            bg.addButton(rb)
            dl.addWidget(rb)

        # ── 飞书同步选项 ──
        chk_feishu = QCheckBox("同步到飞书文档")
        appid, appsecret, *_ = self._get_feishu_config()
        chk_feishu.setEnabled(bool(appid and appsecret))
        chk_feishu.setToolTip("" if (appid and appsecret) else "请先在「环境配置」页配置飞书 AppID/AppSecret")
        dl.addWidget(chk_feishu)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("保存")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return

        base_name = name_edit.text().strip() or default_name
        do_excel = fmt_excel.isChecked() or fmt_both.isChecked() or fmt_all.isChecked()
        do_md = fmt_md.isChecked() or fmt_both.isChecked() or fmt_all.isChecked()
        do_json = fmt_json.isChecked() or fmt_all.isChecked()
        do_feishu = chk_feishu.isChecked()

        # 保存到配置的素材目录（与浏览器下载目录对齐）
        import re as _re
        safe_topic = _re.sub(r'[\\/:*?"<>|\r\n\t]', "_", topic)[:40]
        out_dir = os.path.join(KNOWLEDGE_MEDIA_DIR, safe_topic, "storyboard")
        os.makedirs(out_dir, exist_ok=True)

        saved_files = []

        if do_excel:
            xlsx_path = os.path.join(out_dir, base_name + ".xlsx")
            self._export_storyboard_excel(xlsx_path, topic, ratio, orient, style_name, total_dur, shots)
            saved_files.append(xlsx_path)

        if do_md:
            md_path = os.path.join(out_dir, base_name + ".md")
            self._export_storyboard_md(md_path, topic, ratio, orient, style_name, total_dur, shots)
            saved_files.append(md_path)

        if do_json:
            json_path = os.path.join(out_dir, base_name + ".json")
            self._export_storyboard_json(json_path, topic, ratio, total_dur, shots)
            saved_files.append(json_path)

        if not saved_files:  # fallback
            xlsx_path = os.path.join(out_dir, base_name + ".xlsx")
            self._export_storyboard_excel(xlsx_path, topic, ratio, orient, style_name, total_dur, shots)
            saved_files.append(xlsx_path)

        if do_feishu:
            self._upload_to_feishu("docx")

        self.show_info(
            f"分镜脚本已保存至：\n{out_dir}\n\n" + "\n".join(os.path.basename(f) for f in saved_files),
            "保存成功",
        )

    def _export_storyboard_excel(self, path, topic, ratio, orient, style_name, total_dur, shots):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        except ImportError:
            raise RuntimeError("缺少 openpyxl，请运行：pip install openpyxl")

        wb = openpyxl.Workbook()

        # Sheet 1：概览
        ws_info = wb.active
        ws_info.title = "概览"
        header_font = Font(bold=True, size=12)
        ws_info.column_dimensions["A"].width = 16
        ws_info.column_dimensions["B"].width = 40
        rows_info = [
            ("选题", topic), ("画幅", f"{orient}（{ratio}）"),
            ("风格化", style_name or "—"), ("总时长", f"{total_dur}s"),
            ("镜头数", len(shots)), ("生成日期", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ]
        for r, (k, v) in enumerate(rows_info, 1):
            ws_info.cell(r, 1, k).font = header_font
            ws_info.cell(r, 2, str(v))

        # Sheet 2：分镜脚本
        ws = wb.create_sheet("分镜脚本")
        cols = ["镜号", "镜别", "时长(s)", "音效", "画面描述", "旁白/台词", "引用素材", "素材Hash"]
        widths = [6, 8, 8, 16, 40, 40, 30, 20]
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        hdr_fill = PatternFill("solid", fgColor="1E3A5F")
        hdr_font = Font(bold=True, color="FFFFFF")
        for ci, (col, w) in enumerate(zip(cols, widths), 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w
            cell = ws.cell(1, ci, col)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 22

        alt_fill = PatternFill("solid", fgColor="F5F7FA")
        for ri, s in enumerate(shots, 2):
            row_data = [
                s["index"], s["shot_type"], s["duration"],
                s["sfx"], s["visual"], s["narration"], s["material_path"], s.get("material_hash", ""),
            ]
            fill = alt_fill if ri % 2 == 0 else None
            for ci, val in enumerate(row_data, 1):
                cell = ws.cell(ri, ci, val)
                cell.border = border
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if fill:
                    cell.fill = fill
            ws.row_dimensions[ri].height = max(40, len(str(s["visual"])) // 3)

        wb.save(path)

    def _export_storyboard_md(self, path, topic, ratio, orient, style_name, total_dur, shots):
        lines = [
            f"# 分镜脚本 — {topic}",
            "",
            f"**画幅**：{orient}（{ratio}）　**风格**：{style_name or '—'}　**总时长**：{total_dur}s　**镜头数**：{len(shots)}",
            "",
            f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            "---",
            "",
            "| 镜号 | 镜别 | 时长 | 音效 | 画面描述 | 旁白/台词 | 引用素材 | 素材Hash |",
            "|:---:|:---:|:---:|------|---------|-----------|---------|---------|",
        ]
        for s in shots:
            def _esc(v):
                return str(v).replace("|", "｜").replace("\n", " ").strip()
            lines.append(
                f"| {s['index']} | {_esc(s['shot_type'])} | {s['duration']}s "
                f"| {_esc(s['sfx']) or '—'} | {_esc(s['visual'])} "
                f"| {_esc(s['narration']) or '—'} | {_esc(s['material_path']) or '—'} | {_esc(s.get('material_hash','')) or '—'} |"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _export_storyboard_json(self, path, topic, ratio, total_dur, shots):
        """导出为 JSON（供「一键成片 > 脚本成片」tab 选择并提交服务端）。
        结构：{topic, ratio, total_duration, shot_count, shots:[{index,shot_type,duration,sfx,visual,narration,material_type,material_path,material_hash}], saved_at}
        """
        import json as _json
        import time as _time
        data = {
            "topic": topic,
            "ratio": ratio,
            "total_duration": total_dur,
            "shot_count": len(shots),
            "shots": shots,   # _collect_shots() 的输出，已含素材路径+文案
            "saved_at": int(_time.time()),
        }
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)

    # ──────────────────── 风格化 ────────────────────────────────────
    def _reload_stylizations(self):
        mgr = MyKnowledgeManager()
        items = [it for it in mgr.items if it.get("type") == STYLIZATION_TYPE]
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        self.combo_stylization.blockSignals(True)
        prev_id = (self._selected_stylization or {}).get("id")
        self.combo_stylization.clear()
        self.combo_stylization.addItem("── 不使用风格化 ──", None)
        restore_idx = 0
        for it in items:
            label = it.get("name", "（无名）")
            score = it.get("score", 0)
            if score:
                label += f"  ★{score}"
            self.combo_stylization.addItem(label, it)
            if it.get("id") == prev_id:
                restore_idx = self.combo_stylization.count() - 1
        self.combo_stylization.setCurrentIndex(restore_idx)
        self.combo_stylization.blockSignals(False)
        self._on_stylization_selected()

    def _on_stylization_selected(self):
        data = self.combo_stylization.currentData()
        self._selected_stylization = data if isinstance(data, dict) else None
        self.text_style_portrait.setPlainText(
            self._selected_stylization.get("content", "") if self._selected_stylization else ""
        )

    # ──────────────────── 文案调整 ──────────────────────────────────
    def _adjust_copy(self):
        copy_text = self.edit_copy.toPlainText().strip()
        if not copy_text:
            QMessageBox.warning(self.parent_widget, "文案为空", "请先填写视频文案。")
            return
        extra = self.edit_extra_prompt.toPlainText().strip()
        style_text = (self._selected_stylization.get("content") or "").strip() if self._selected_stylization else ""
        parts = [f"原始视频文案：\n{copy_text}"]
        if style_text:
            parts.append(f"风格化要求（HOW to write）：\n{style_text}")
        if extra:
            parts.append(f"额外要求：\n{extra}")
        parts.append("请根据以上要求重新输出优化后的视频文案，保持核心信息不变，只调整表达风格和措辞。")
        self._run_llm(
            "你是专业的短视频文案创作者，根据用户要求对视频文案进行优化和调整。",
            "\n\n".join(parts),
            lambda c: (self.edit_copy.setPlainText(c),
                       self.lbl_status.setText("文案调整完成，可继续生成分镜脚本。")),
            self.btn_adjust_copy, "AI 正在调整文案…",
        )

    # ──────────────────── 分镜卡片 ──────────────────────────────────
    def _make_shot_card(self, idx, shot_type="近景", visual="", audio="", sfx="", duration=5):
        frame = QFrame()
        frame.setObjectName("card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)

        # 头部行：镜头号 镜别 时长 音效 [引用素材]
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel(f"<b>镜头 {idx}</b>"))

        hdr.addWidget(QLabel("镜别"))
        combo_type = QComboBox()
        combo_type.addItems(SHOT_TYPES)
        if shot_type in SHOT_TYPES:
            combo_type.setCurrentText(shot_type)
        combo_type.setFixedWidth(70)
        hdr.addWidget(combo_type)

        hdr.addSpacing(8)
        hdr.addWidget(QLabel("时长"))
        spin_dur = QSpinBox()
        spin_dur.setRange(1, 120)
        spin_dur.setValue(int(duration) if duration else 5)
        spin_dur.setSuffix(" s")
        spin_dur.setFixedWidth(65)
        spin_dur.valueChanged.connect(self._update_sb_header)
        hdr.addWidget(spin_dur)

        hdr.addSpacing(8)
        hdr.addWidget(QLabel("音效"))
        edit_sfx = QLineEdit()
        edit_sfx.setText(sfx)
        edit_sfx.setPlaceholderText("如：轻松背景音乐、键盘敲击声…")
        hdr.addWidget(edit_sfx, 1)

        hdr.addSpacing(12)
        mat_lbl = QLabel("")
        mat_lbl.setObjectName("muted_text")
        mat_lbl.setMaximumWidth(130)
        hdr.addWidget(mat_lbl)
        btn_mat = QPushButton("🔍 引用素材")
        btn_mat.setObjectName("secondary_button")
        btn_mat.setFixedHeight(26)
        hdr.addWidget(btn_mat)
        v.addLayout(hdr)

        # 内容行：画面描述 + 旁白（左） | 缩略图（右）
        content_row = QHBoxLayout()
        content_row.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        text_col.addWidget(self._muted_lbl("画面描述"))
        desc = QTextEdit()
        desc.setPlainText(visual)
        desc.setFixedHeight(58)
        desc.setPlaceholderText("镜头画面内容描述（即梦出图提示词，可直接编辑）")
        text_col.addWidget(desc)
        text_col.addWidget(self._muted_lbl("旁白台词"))
        narration = QTextEdit()
        narration.setPlainText(audio)
        narration.setFixedHeight(38)
        narration.setPlaceholderText("旁白/台词")
        text_col.addWidget(narration)
        content_row.addLayout(text_col, 1)

        thumb = QLabel("未出图")
        thumb.setObjectName("muted_text")
        thumb.setFixedSize(120, 90)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("border:1px solid #3a3a3a; border-radius:4px;")
        content_row.addWidget(thumb, 0, Qt.AlignTop)

        v.addLayout(content_row)

        card = {
            "frame": frame, "idx": idx,
            "combo_type": combo_type, "spin_dur": spin_dur,
            "edit_sfx": edit_sfx, "desc": desc, "narration": narration,
            "thumb": thumb, "file": "", "material": None, "mat_lbl": mat_lbl,
        }
        btn_mat.clicked.connect(lambda: self._open_material_dialog(card))
        return card

    def _open_material_dialog(self, card):
        shot_desc = card["desc"].toPlainText().strip()
        ratio = self.combo_shot_ratio.currentText()
        dlg = ShotMaterialDialog(
            shot_desc=shot_desc, ratio=ratio,
            main_window=self.main_window,
            parent=self.parent_widget,
        )
        if dlg.exec() == QDialog.Accepted and dlg.selected_material:
            mat = dlg.selected_material
            card["material"] = mat
            # if it's a generated image, also update the thumbnail
            if mat["type"] == "dreamina":
                pm = QPixmap(mat["path"])
                if not pm.isNull():
                    card["thumb"].setPixmap(pm.scaled(120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                card["file"] = mat["path"]
            name = mat.get("name", "")
            card["mat_lbl"].setText(name[:18] + ("…" if len(name) > 18 else ""))
            card["mat_lbl"].setToolTip(mat.get("path", ""))

    # ── 相似度自动绑定（全部镜头）────────────────────────────────────
    def _auto_bind_materials(self):
        if not self.shot_cards:
            self.show_warning("当前没有分镜内容，请先生成分镜脚本。", "无内容")
            return

        # 收集每个镜头的检索文案：优先画面描述，其次旁白台词
        shots = []
        for c in self.shot_cards:
            desc = c["desc"].toPlainText().strip()
            narr = c["narration"].toPlainText().strip()
            query = desc or narr
            if query:
                shots.append((c["idx"], query))

        if not shots:
            self.show_warning("所有镜头都没有画面描述/旁白，无法做相似度检索。", "无可用文案")
            return

        self.btn_auto_bind.setEnabled(False)
        self.pbar.setVisible(True)
        self.pbar.setRange(0, len(shots))
        self.pbar.setValue(0)
        self.lbl_status.setText("正在按镜头文案做相似度自动绑定…")

        self._bind_worker = _AutoBindShotsWorker(shots, min_score=0.0)
        self._bind_worker.progress.connect(self._on_auto_bind_progress)
        self._bind_worker.finished.connect(self._on_auto_bind_finished)
        self._bind_worker.error.connect(self._on_auto_bind_error)
        self._bind_worker.start()

    def _on_auto_bind_progress(self, done, total):
        self.pbar.setRange(0, total)
        self.pbar.setValue(done)
        self.lbl_status.setText(f"相似度自动绑定中… {done}/{total}")

    def _on_auto_bind_error(self, msg):
        self.btn_auto_bind.setEnabled(True)
        self.pbar.setVisible(False)
        self.lbl_status.setText(f"自动绑定失败：{msg}")

    def _on_auto_bind_finished(self, result):
        self.btn_auto_bind.setEnabled(True)
        self.pbar.setVisible(False)
        bound = 0
        for c in self.shot_cards:
            mat = result.get(c["idx"])
            if not mat:
                continue
            c["material"] = mat
            name = mat.get("name", "") or ""
            score = float(mat.get("score", 0) or 0)
            c["mat_lbl"].setText((name[:14] + ("…" if len(name) > 14 else "")) + f" {score*100:.0f}%")
            c["mat_lbl"].setToolTip(
                f"{mat.get('path','')}\n相似度: {score*100:.1f}%\nHash: {mat.get('hash','')}"
            )
            bound += 1
        total = len(self.shot_cards)
        self.lbl_status.setText(f"相似度自动绑定完成：{bound}/{total} 个镜头已绑定素材。")
        self.show_message(
            f"相似度自动绑定完成！\n已绑定 {bound} / {total} 个镜头。\n"
            f"未绑定的镜头多为无相似素材，可手动点「引用素材」补充。"
        )

    def _render_shots(self, shots):
        for c in self.shot_cards:
            c["frame"].setParent(None)
        self.shot_cards = []
        # remove stretch
        item = self.sb_col.takeAt(self.sb_col.count() - 1)
        del item
        for i, shot in enumerate(shots):
            try:
                idx = int(shot.get("index", i + 1))
            except (ValueError, TypeError):
                idx = i + 1
            card = self._make_shot_card(
                idx,
                shot_type=str(shot.get("shot_type", "近景")),
                visual=str(shot.get("visual", "")),
                audio=str(shot.get("audio", "")),
                sfx=str(shot.get("sfx", "")),
                duration=shot.get("duration", 5),
            )
            self.sb_col.addWidget(card["frame"])
            self.shot_cards.append(card)
        self.sb_col.addStretch()
        self._update_sb_header()

    def _update_sb_header(self):
        total = sum(c["spin_dur"].value() for c in self.shot_cards)
        ratio = self.combo_shot_ratio.currentText()
        orient = {"9:16": "竖屏", "16:9": "横屏", "1:1": "方形"}.get(ratio, ratio)
        self.lbl_sb_info.setText(f"总时长：{total} s  |  {len(self.shot_cards)} 镜  （{orient}）")

    def _on_shot_done(self, idx, file_path):
        for c in self.shot_cards:
            if c["idx"] == idx:
                pm = QPixmap(file_path)
                if not pm.isNull():
                    c["thumb"].setPixmap(pm.scaled(120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                c["file"] = file_path
                break

    # ──────────────────── LLM 调用 ──────────────────────────────────
    def _ai_cfg(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        model = ai.get("llm_model", "deepseek-v4-flash")
        if not model:
            QMessageBox.warning(self.parent_widget, "大模型未配置",
                                "请先在「AI 设置 / 大模型配置」中选择模型名称。")
            return None
        return "", "", model

    def _run_llm(self, system_prompt, user_prompt, on_done, busy_btn, busy_text):
        cfg = self._ai_cfg()
        if not cfg:
            return
        url, key, model = cfg
        busy_btn.setEnabled(False)
        self.lbl_status.setText(busy_text)
        self.pbar.setVisible(True)
        self.worker = LLMWorker(url, key, model, system_prompt, user_prompt)

        def _done(content):
            busy_btn.setEnabled(True)
            self.pbar.setVisible(False)
            on_done(content.strip())

        def _err(msg):
            busy_btn.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText("生成失败。")
            QMessageBox.critical(self.parent_widget, "大模型异常", f"请求失败：\n{msg}")

        self.worker.finished.connect(_done)
        self.worker.error.connect(_err)
        self.worker.start()

    # ──────────────────── 分镜生成 ──────────────────────────────────
    def _generate_storyboard(self):
        copy_text = self.edit_copy.toPlainText().strip()
        if not copy_text:
            QMessageBox.warning(self.parent_widget, "文案为空", "请先填写或生成视频文案。")
            return

        ratio = self.combo_shot_ratio.currentText()
        orient = {"9:16": "竖屏（9:16）", "16:9": "横屏（16:9）", "1:1": "方形（1:1）"}.get(ratio, ratio)

        system_prompt = (
            "你是专业短视频导演，把视频文案拆解为专业分镜脚本。"
            "每个镜头需要包含镜别、画面描述、旁白台词、音效建议、建议时长（秒）。"
        )
        user_prompt = (
            f"请把以下短视频文案拆解为分镜脚本（{orient}画幅），约 9 个镜头，"
            "以 JSON 数组输出，每个元素含以下字段：\n"
            '  "index"(整型镜头序号), "shot_type"(镜别，如特写/近景/中景/远景/全景/俯拍/仰拍/主观/空镜), '
            '"visual"(画面描述，可作为即梦出图提示词), "audio"(旁白/台词), '
            '"sfx"(音效建议，如无则留空字符串), "duration"(建议时长秒数，整型)。\n'
            "严格只输出 JSON 数组，不要 ```json 包裹。\n\n文案：\n" + copy_text
        )
        self._run_llm(system_prompt, user_prompt, self._fill_storyboard,
                      self.btn_gen_sb, "AI 正在拆解分镜…")

    def _fill_storyboard(self, content):
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            shots = json.loads(text)
            if not isinstance(shots, list):
                raise ValueError("非 JSON 数组")
        except Exception as e:
            log.error(f"分镜 JSON 解析失败: {e}")
            self.lbl_status.setText("分镜解析失败，已将原始结果放入第一格。")
            self._render_shots([{"index": 1, "visual": content, "audio": "", "sfx": "", "duration": 5}])
            return
        self._render_shots(shots)
        total = sum(s.get("duration", 5) for s in shots if isinstance(s.get("duration"), (int, float)))
        self.lbl_status.setText(
            f"分镜已生成（{len(shots)} 个镜头，约 {total}s），可直接编辑各镜头字段，或点击「引用素材」关联本地/即梦/联网素材。"
        )

    def _open_mg(self):
        try:
            self.main_window.switch_page(36)
            tool = getattr(self.main_window, "mg_animation_tool", None)
            if tool and self.shot_cards and hasattr(tool, "set_default_text"):
                tool.set_default_text(self.shot_cards[0]["desc"].toPlainText().strip()[:20])
        except Exception as e:
            self.show_error(f"跳转失败：{e}")

    # ──────────────────── 即梦批量生成 ─────────────────────────────
    def _generate_shot_images(self):
        shots = [(c["idx"], c["desc"].toPlainText().strip()) for c in self.shot_cards
                 if c["desc"].toPlainText().strip()]
        if not shots:
            self.show_warning("请先生成分镜脚本。")
            return
        ratio = self.combo_shot_ratio.currentText()
        out_dir = os.path.join(DREAMINA_OUTPUT_DIR, "shots_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.btn_gen_shots.setEnabled(False)
        self.pbar.setVisible(True)
        self.lbl_status.setText(f"开始批量生成 {len(shots)} 个镜头素材（{ratio}）…")
        worker = BatchShotImageWorker(shots, ratio, out_dir)
        worker.phase.connect(self.lbl_status.setText)
        worker.shot_done.connect(self._on_shot_done)

        def done(files):
            self.btn_gen_shots.setEnabled(True)
            self.pbar.setVisible(False)
            if files:
                self.lbl_status.setText(f"✅ 已生成 {len(files)} 张镜头素材：{out_dir}")
            else:
                self.lbl_status.setText("未生成任何素材（可能未登录或全部失败）。")

        worker.finished.connect(done)
        worker.error.connect(lambda e: (
            self.btn_gen_shots.setEnabled(True),
            self.pbar.setVisible(False),
            self.show_error(str(e), "镜头素材生成失败"),
        ))
        self.track_worker(worker)
        worker.start()

    # ──────────────────── 飞书同步 ──────────────────────────────────
    def _get_feishu_config(self):
        """从 CONFIG_INI_FILE 读取飞书配置。"""
        import configparser
        config = configparser.ConfigParser()
        appid = appsecret = apptoken = tableid = ""
        topicfield = "选题"
        scriptfield = "脚本"
        foldertoken = ""
        try:
            config.read(CONFIG_INI_FILE, encoding="utf-8")
            if config.has_section("Feishu"):
                appid = config.get("Feishu", "AppId", fallback="")
                appsecret = config.get("Feishu", "AppSecret", fallback="")
                apptoken = config.get("Feishu", "AppToken", fallback="")
                tableid = config.get("Feishu", "TableId", fallback="")
                topicfield = config.get("Feishu", "TopicField", fallback="选题")
                scriptfield = config.get("Feishu", "ScriptField", fallback="脚本")
                foldertoken = config.get("Feishu", "FolderToken", fallback="")
        except Exception:
            pass
        return appid, appsecret, apptoken, tableid, topicfield, scriptfield, foldertoken

    def _get_script_table_as_text(self):
        """将当前分镜脚本格式化为文本，供飞书同步。"""
        lines = []
        for card in self.shot_cards:
            idx = card["idx"]
            shot_type = card["combo_type"].currentText()
            duration = card["spin_dur"].value()
            sfx = card["edit_sfx"].text().strip()
            visual = card["desc"].toPlainText().strip()
            narration = card["narration"].toPlainText().strip()
            mat = card.get("material") or {}
            mat_path = mat.get("path", "")
            lines.append(
                f"【镜头{idx}】{shot_type} | {duration}s | 音效：{sfx or '—'}\n"
                f"画面：{visual}\n"
                f"旁白：{narration}\n"
                f"素材：{mat_path}\n"
            )
        return "\n".join(lines)

    def _upload_to_feishu(self, mode):
        """将分镜脚本同步到飞书（bitable 或 docx）。"""
        appid, appsecret, apptoken, tableid, topicfield, scriptfield, foldertoken = self._get_feishu_config()
        if not appid or not appsecret:
            QMessageBox.warning(self.parent_widget, "配置未完成",
                                "请先在「环境配置」页配置飞书 AppID 和 AppSecret。")
            return
        record_id = None
        topic_name = "新分镜脚本"
        if self.feishu_record:
            record_id = self.feishu_record.get("id")
            topic_name = self.feishu_record.get("topic", "新分镜脚本")
        if mode == "bitable" and (not record_id or not apptoken or not tableid):
            QMessageBox.warning(self.parent_widget, "无法同步",
                                "飞书多维表格配置不完整或未关联选题。\n请先在 AI 文案页同步选题。")
            return
        script_text = self._get_script_table_as_text()
        self.lbl_status.setText(f"正在同步到飞书（{mode}）…")
        self.pbar.setVisible(True)
        self.upload_worker = FeishuUploadWorker(
            app_id=appid, app_secret=appsecret, mode=mode,
            app_token=apptoken, table_id=tableid, record_id=record_id,
            script_field=scriptfield, script_text=script_text,
            folder_token=foldertoken, topic_name=topic_name,
        )

        def on_done(msg):
            self.pbar.setVisible(False)
            self.lbl_status.setText("飞书同步完成。")
            self.show_info(msg)

        def on_err(err_msg):
            self.pbar.setVisible(False)
            self.lbl_status.setText("飞书同步失败。")
            QMessageBox.critical(self.parent_widget, "飞书同步失败", err_msg)

        self.upload_worker.finished.connect(on_done)
        self.upload_worker.error.connect(on_err)
        self.upload_worker.start()
