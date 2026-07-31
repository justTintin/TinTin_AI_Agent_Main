# -*- coding: utf-8 -*-
"""
音频素材页面（媒体库 → 音频素材）。

音频与图片/视频不同：不绑定具体产品，而是与场景/情绪关联，
按 音效(SFX) / 配音(VO) / 音乐(Music) 三类组织。

数据源（复用素材库接口）：
- 浏览：GET /material/list?media_type=audio（无关键词）
- 语义检索：POST /material/search（有关键词，带 media_type=audio）
- 试听：GET /material/serve?material_id=xx（服务端 Range 流式播放）

分类说明：优先使用服务端 audio_kind/kind/category 字段；
服务端尚未支持音频分类字段时，按文件名/描述关键词做本地兜底过滤。
"""
import os
import requests

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QSpinBox, QFrame, QWidget,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QUrl
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from gui.base_page import BasePage
from utils.base_worker import BaseWorker


def _get_server_url():
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _serve_url(material_id):
    """素材原文件的服务端流式 URL（试听用）。"""
    return f"{_get_server_url()}/material/serve?material_id={material_id}"


def _make_audio_icon():
    """音频列表占位图标。"""
    pm = QPixmap(QSize(48, 48))
    pm.fill(QColor("#3b2f5b"))
    p = QPainter(pm)
    p.setPen(QColor("#ffffff"))
    f = p.font()
    f.setPointSize(16)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "🎵")
    p.end()
    return pm


# 分类关键词（服务端无 audio_kind 字段时的本地兜底）
_KIND_ALIASES = {
    "sfx": ("sfx", "fx", "effect", "sound", "whoosh", "click", "tap", "swish",
            "impact", "boom", "pop", "ding", "alert", "音效", "提示音", "过渡", "特效音"),
    "voice": ("voice", "vo", "narration", "speech", "voiceover", "口播",
              "配音", "旁白", "人声", "播报", "解说"),
    "music": ("music", "bgm", "ost", "track", "beat", "instrumental", "melody",
              "音乐", "配乐", "卡点", "纯音乐", "背景音乐"),
}


def classify_audio(item):
    """返回 'sfx' / 'voice' / 'music' / ''：服务端分类字段优先，其次文件名/描述关键词。"""
    for field in ("audio_kind", "kind", "category"):
        v = str(item.get(field) or "").lower()
        if not v or v in ("其他", "other", "未分类"):
            continue
        for kind in ("sfx", "voice", "music"):
            if any(a in v for a in _KIND_ALIASES[kind][:4]):
                return kind
    hay = " ".join([
        str(item.get("filename") or ""),
        str(item.get("scene_desc_primary") or ""),
    ]).lower()
    for kind, aliases in _KIND_ALIASES.items():
        if any(a in hay for a in aliases):
            return kind
    return ""


class _AudioListWorker(BaseWorker):
    """音频素材列表：无关键词走 /material/list，有关键词走 /material/search。"""
    finished = Signal(list, int)

    def __init__(self, query="", tag="", limit=50, offset=0):
        super().__init__()
        self.query = query
        self.tag = tag
        self.limit = limit
        self.offset = offset

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址，请在系统设置中填写统一计算节点地址。")
            return
        try:
            if self.query:
                params = {"query": self.query, "media_type": "audio",
                          "limit": self.limit, "offset": self.offset}
                if self.tag:
                    params["tag"] = self.tag
                resp = requests.post(f"{base}/material/search", json=params, timeout=20)
                if resp.status_code != 200:
                    raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                results = data.get("results") or data.get("data") or []
                total = data.get("total") or len(results)
            else:
                params = {"media_type": "audio", "limit": self.limit, "offset": self.offset}
                if self.tag:
                    params["tag"] = self.tag
                resp = requests.get(f"{base}/material/list", params=params, timeout=20)
                if resp.status_code != 200:
                    raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                results = data.get("items") or []
                total = data.get("total") or len(results)
            self.finished.emit(results, int(total))
        except Exception as e:
            self.error.emit(str(e))


class AudioMaterialPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._results = []
        self._total = 0
        self._offset = 0
        self._page_size = 50
        self._last_params = None
        self._player = None
        self._audio_output = None
        self._playing_mid = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # ── 第一行：仅标题（右侧无控件）──
        title = QLabel("🎵 音频素材")
        title.setObjectName("heading")
        root.addWidget(title)

        # ── 第二行：搜索（独立换行显示）──
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索音频（语义检索，如：激昂的背景音乐）")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.setObjectName("primary_button")
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # ── 分类 + 状态 ──
        row = QHBoxLayout()
        row.addWidget(QLabel("分类:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("全部", "")
        self.kind_combo.addItem("音效（场景/氛围音）", "sfx")
        self.kind_combo.addItem("配音（口播/旁白）", "voice")
        self.kind_combo.addItem("音乐（BGM/配乐）", "music")
        self.kind_combo.currentIndexChanged.connect(self._do_search)
        row.addWidget(self.kind_combo)
        row.addSpacing(12)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("情绪/场景标签（如：科技感、温馨）")
        self.tag_input.setMaximumWidth(200)
        self.tag_input.returnPressed.connect(self._do_search)
        row.addWidget(self.tag_input)
        row.addStretch(1)
        self.lbl_stat = QLabel("")
        self.lbl_stat.setObjectName("muted_text")
        row.addWidget(self.lbl_stat)
        root.addLayout(row)

        # ── 音频列表（双击试听）──
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._play_item)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setStyleSheet(
            "QListWidget { background: #1a1a24; border: 1px solid #2e2e38; border-radius: 8px; font-size: 13px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #26262e; }"
            "QListWidget::item:selected { background: #2b3a63; }")
        root.addWidget(self.list_widget, 1)
        self.lbl_hint = QLabel("💡 双击条目试听；再次双击同一条目停止。")
        self.lbl_hint.setObjectName("muted_text")
        root.addWidget(self.lbl_hint)

        # ── 播放控制 ──
        play_row = QHBoxLayout()
        self.lbl_now_playing = QLabel("未在播放")
        self.lbl_now_playing.setObjectName("muted_text")
        play_row.addWidget(self.lbl_now_playing, 1)
        btn_stop = QPushButton("⏹ 停止")
        btn_stop.setObjectName("secondary_button")
        btn_stop.clicked.connect(self._stop_preview)
        play_row.addWidget(btn_stop)
        root.addLayout(play_row)

        # ── 分页 ──
        page_row = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 上一页")
        self.btn_prev.setObjectName("secondary_button")
        self.btn_prev.clicked.connect(self._go_prev_page)
        page_row.addWidget(self.btn_prev)
        self.lbl_page = QLabel("")
        self.lbl_page.setObjectName("muted_text")
        page_row.addWidget(self.lbl_page)
        self.btn_next = QPushButton("下一页 ▶")
        self.btn_next.setObjectName("secondary_button")
        self.btn_next.clicked.connect(self._go_next_page)
        page_row.addWidget(self.btn_next)
        page_row.addStretch(1)
        page_row.addWidget(QLabel("每页:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(10, 200)
        self.spin_limit.setValue(50)
        self.spin_limit.setSingleStep(10)
        self.spin_limit.valueChanged.connect(self._do_search)
        page_row.addWidget(self.spin_limit)
        root.addLayout(page_row)

        self._pm_audio = _make_audio_icon()
        QTimer.singleShot(100, self._do_search)

    # ── 检索 ──
    def _collect_params(self):
        return {
            "query": self.search_input.text().strip(),
            "tag": self.tag_input.text().strip(),
            "kind": self.kind_combo.currentData() or "",
        }

    def _do_search(self):
        params = self._collect_params()
        self._last_params = params
        self._page_size = self.spin_limit.value()
        self._offset = 0
        self._run_search()

    def refresh(self):
        """重新拉取当前筛选条件（进入页面/手动刷新时调用）。"""
        if self._last_params:
            self._run_search()

    def _run_search(self):
        if not self._last_params:
            return
        p = self._last_params
        self.btn_search.setEnabled(False)
        self.lbl_stat.setText("加载中...")
        w = self.track_worker(_AudioListWorker(
            query=p["query"], tag=p["tag"],
            limit=self._page_size, offset=self._offset))
        w.finished.connect(self._on_search_done)
        w.error.connect(self._on_search_error)
        w.start()

    def _on_search_done(self, results, total):
        self.btn_search.setEnabled(True)
        self._results = results
        self._total = total
        self._fill_list(results)
        self._update_page_label()

    def _on_search_error(self, msg):
        self.btn_search.setEnabled(True)
        friendly = msg
        if "Connection" in msg or "timed out" in msg or "Max retries" in msg:
            friendly = "无法连接服务端，请检查服务端是否在线"
        self.lbl_stat.setText(f"❌ {friendly}")
        self.list_widget.clear()
        self._results = []
        self._total = 0
        self._update_page_label()

    # ── 列表 ──
    def _fill_list(self, rows):
        self.list_widget.clear()
        kind = (self._last_params or {}).get("kind", "")
        shown = 0
        for item in rows:
            if kind and classify_audio(item) != kind:
                continue
            mid = str(item.get("id") or item.get("material_id") or "")
            fname = item.get("filename", "") or "未命名"
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else "—"
            kind_name = {"sfx": "音效", "voice": "配音", "music": "音乐"}.get(
                classify_audio(item), "未分类")
            tip = (f"🎵 {fname}\n分类: {kind_name}\n大小: {size_str}")
            score = item.get("score")
            if score is not None:
                tip += f"\n相关度: {float(score):.3f}"
            scene = item.get("scene_desc_primary") or ""
            if scene:
                tip += f"\n描述: {str(scene)[:100]}"
            lw = QListWidgetItem()
            lw.setText(f"[{kind_name}] {fname[:44]}")
            lw.setToolTip(tip)
            lw.setIcon(self._pm_audio)
            lw.setData(Qt.UserRole, {"mid": mid, "filename": fname})
            self.list_widget.addItem(lw)
            shown += 1
        self.lbl_stat.setText(
            f"共 {self._total} 条音频（本页显示 {shown} 条）")

    # ── 试听 ──
    def _ensure_player(self):
        if self._player is None:
            self._audio_output = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        return self._player

    def _on_item_clicked(self, item):
        self._play_item(item)

    def _play_item(self, item):
        data = item.data(Qt.UserRole) or {}
        mid = str(data.get("mid") or "")
        if not mid:
            return
        player = self._ensure_player()
        if (self._playing_mid == mid
                and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
            self._stop_preview()
            return
        player.setSource(QUrl(_serve_url(mid)))
        player.play()
        self._playing_mid = mid
        self.lbl_now_playing.setText(f"▶ 播放中: {data.get('filename', mid)}")

    def _stop_preview(self):
        if self._player is not None:
            self._player.stop()
        self._playing_mid = None
        self.lbl_now_playing.setText("未在播放")

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._playing_mid = None
            self.lbl_now_playing.setText("播放完成")

    # ── 分页 ──
    def _update_page_label(self):
        page_size = self._page_size or 1
        cur_page = (self._offset // page_size) + 1 if self._total > 0 else 0
        total_pages = max(1, (self._total + page_size - 1) // page_size) if self._total > 0 else 0
        self.lbl_page.setText(f"第 {cur_page} / {total_pages} 页")
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(self._offset + self._page_size < self._total)

    def _go_prev_page(self):
        if self._offset <= 0 or not self._last_params:
            return
        self._page_size = self.spin_limit.value()
        self._offset = max(0, self._offset - self._page_size)
        self._run_search()

    def _go_next_page(self):
        if not self._last_params:
            return
        self._page_size = self.spin_limit.value()
        if self._offset + self._page_size >= self._total:
            return
        self._offset += self._page_size
        self._run_search()
