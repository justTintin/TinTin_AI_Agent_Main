# -*- coding: utf-8 -*-
"""
音频素材页面（媒体库 → 音频素材）。

音频与图片/视频不同：不绑定具体产品，而是与场景/情绪关联，
按 音效(SFX) / 口播(VO) / 音乐(Music) 三类组织。

数据源（音频库独立表 /audio/library）：
- 浏览：GET /audio/library（分页 + category/tag/emotion/style/genre 筛选）
- 搜索：GET /audio/library?keyword=xxx（文件名/路径模糊）
- 试听：GET /audio/library/{id}/file（服务端 Range 流式播放）
- 分析：POST /audio/library/{id}/analyze（PANNs 情感/风格）+ analyze_all 批量

分类说明：优先使用服务端 emotion/styles/genre 字段；
服务端未分析时按文件名/描述关键词做本地兜底过滤。
"""
import os
import requests
from utils.http_client import http_get, http_post

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QSpinBox, QFrame, QWidget, QMessageBox,
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


def _serve_url(audio_id):
    """音频试听 URL（/audio/library/{id}/file，Range 支持）。"""
    return f"{_get_server_url()}/audio/library/{audio_id}/file"


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


# 分类关键词（服务端无 styles/genre 字段时的本地兜底）
_KIND_ALIASES = {
    "sfx": ("sfx", "fx", "effect", "sound", "whoosh", "click", "tap", "swish",
            "impact", "boom", "pop", "ding", "alert", "音效", "提示音", "过渡", "特效音"),
    "voice": ("voice", "vo", "narration", "speech", "voiceover", "口播",
              "配音", "旁白", "人声", "播报", "解说"),
    "music": ("music", "bgm", "ost", "track", "beat", "instrumental", "melody",
              "音乐", "配乐", "卡点", "纯音乐", "背景音乐"),
}

# 服务端风格/情感 → 三类映射
_STYLE_TO_KIND = {
    "电子": "music", "摇滚": "music", "金属": "music", "朋克": "music",
    "爵士": "music", "布鲁斯": "music", "灵魂乐": "music", "放克": "music",
    "雷鬼": "music", "嘻哈": "music", "说唱": "music", "流行": "music",
    "乡村": "music", "民谣": "music", "拉丁": "music", "雷鬼顿": "music",
    "氛围": "music", "新世纪": "music", "配乐": "music", "主题曲": "music",
    "融合": "music", "管弦乐": "music", "合唱": "music", "歌剧": "music",
    "古典": "music", "钢琴": "music", "吉他": "music", "小提琴": "music",
    "大提琴": "music", "长笛": "music", "萨克斯": "music", "小号": "music",
    "竖琴": "music", "二胡": "music", "古筝": "music", "琵琶": "music",
    "西塔琴": "music", "古琴": "music", "笛子": "music", "塔布拉": "music",
    "太鼓": "music", "传统": "music",
    "演唱": "voice", "哼唱": "voice", "吟唱": "voice", "轻柔": "voice",
    "音效": "sfx", "打击乐": "sfx", "架子鼓": "sfx", "贝斯": "sfx",
    "镲": "sfx", "踩镲": "sfx", "铃声": "sfx", "风铃": "sfx",
    "马林巴": "sfx", "木琴": "sfx",
    "人群": "sfx", "雨声": "sfx", "雷声": "sfx", "风声": "sfx",
    "水流": "sfx", "鸟鸣": "sfx", "火焰": "sfx", "噼啪": "sfx",
    "警报": "sfx", "爆炸": "sfx", "枪声": "sfx", "掌声": "sfx",
    "静音": "sfx", "心跳": "sfx",
}

# 情感 → 音乐子类（服务端 emotion 字段）
_EMOTION_TO_MUSIC = {
    "强烈": "燃向", "动感": "动感", "舒缓": "舒缓", "空灵": "空灵",
    "慵懒": "舒缓", "忧郁": "抒情", "大气": "大气", "恢宏": "大气",
    "激昂": "燃向", "平缓": "舒缓",
}


def classify_audio(item):
    """返回 'sfx' / 'voice' / 'music' / ''：服务端 styles/genre/emotion 优先，其次文件名/描述关键词。"""
    # 服务端风格字段
    styles = item.get("styles") or []
    genre = str(item.get("genre") or "")
    emotion = str(item.get("emotion") or "")
    candidates = []
    if isinstance(styles, (list, tuple)):
        candidates.extend(str(s) for s in styles)
    if genre:
        candidates.append(genre)
    for c in candidates:
        kind = _STYLE_TO_KIND.get(c)
        if kind:
            return kind
    if emotion and emotion in _EMOTION_TO_MUSIC:
        return "music"
    # 兼容旧 audio_kind/kind/category 字段
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
    """音频库列表：走 /audio/library（分页 + keyword/emotion/style/genre 筛选）。"""
    finished = Signal(list, int)

    def __init__(self, query="", kind="", tag="", emotion="", style="",
                 limit=50, offset=0):
        super().__init__()
        self.query = query
        self.kind = kind
        self.tag = tag
        self.emotion = emotion
        self.style = style
        self.limit = limit
        self.offset = offset

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址，请在系统设置中填写统一计算节点地址。")
            return
        try:
            params = {"size": self.limit, "page": (self.offset // self.limit) + 1}
            if self.query:
                params["keyword"] = self.query
            if self.tag:
                params["tag"] = self.tag
            if self.emotion:
                params["emotion"] = self.emotion
            if self.style:
                params["style"] = self.style
            resp = http_get(f"{base}/audio/library", params=params, timeout=20)
            if resp.status_code != 200:
                raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            results = data.get("items") or []
            total = data.get("total") or len(results)
            self.finished.emit(results, int(total))
        except Exception as e:
            self.error.emit(str(e))


class _AudioAnalyzeWorker(BaseWorker):
    """单条音频 PANNs 分析。"""
    finished = Signal(int, dict)

    def __init__(self, audio_id):
        super().__init__()
        self.audio_id = audio_id

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址")
            return
        try:
            resp = http_post(f"{base}/audio/library/{self.audio_id}/analyze", timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
            self.finished.emit(self.audio_id, resp.json())
        except Exception as e:
            self.error.emit(str(e))


class _AudioAnalyzeAllWorker(BaseWorker):
    """批量分析待分析音频。"""
    finished = Signal(dict)

    def __init__(self):
        super().__init__()

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址")
            return
        try:
            resp = http_post(f"{base}/audio/library/analyze_all", timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
            self.finished.emit(resp.json())
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
        title = QLabel("🎵 音频分析")
        title.setObjectName("heading")
        root.addWidget(title)

        # ── 第二行：搜索（独立换行显示）──
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索音频（文件名/路径，如：激昂的背景音乐）")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        self.btn_search = QPushButton("🔍 搜索")
        self.btn_search.setObjectName("primary_button")
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        self.btn_analyze_all = QPushButton("⚡ 批量分析")
        self.btn_analyze_all.setObjectName("primary_button")
        self.btn_analyze_all.clicked.connect(self._analyze_all)
        search_row.addWidget(self.btn_analyze_all)
        root.addLayout(search_row)

        # ── 分类 + 情感 + 状态 ──
        row = QHBoxLayout()
        row.addWidget(QLabel("分类:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("全部", "")
        self.kind_combo.addItem("音效（场景/氛围音）", "sfx")
        self.kind_combo.addItem("口播（配音/旁白）", "voice")
        self.kind_combo.addItem("音乐（BGM/配乐）", "music")
        self.kind_combo.currentIndexChanged.connect(self._do_search)
        row.addWidget(self.kind_combo)
        row.addSpacing(10)
        row.addWidget(QLabel("情感:"))
        self.emotion_combo = QComboBox()
        self.emotion_combo.addItem("全部", "")
        for emo in ("强烈", "动感", "舒缓", "空灵", "忧郁", "大气", "激昂", "平缓"):
            self.emotion_combo.addItem(emo, emo)
        self.emotion_combo.currentIndexChanged.connect(self._do_search)
        row.addWidget(self.emotion_combo)
        row.addSpacing(10)
        row.addWidget(QLabel("风格:"))
        self.style_combo = QComboBox()
        self.style_combo.addItem("全部", "")
        for st in ("电子", "摇滚", "古典", "流行", "民谣", "配乐", "氛围", "爵士", "钢琴", "音效", "说唱"):
            self.style_combo.addItem(st, st)
        self.style_combo.currentIndexChanged.connect(self._do_search)
        row.addWidget(self.style_combo)
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
            query=p["query"], kind=p.get("kind", ""), tag=p.get("tag", ""),
            emotion=p.get("emotion", ""), style=p.get("style", ""),
            limit=self._page_size, offset=self._offset))
        w.finished.connect(self._on_search_done)
        w.error.connect(self._on_search_error)
        w.start()

    def _collect_params(self):
        return {
            "query": self.search_input.text().strip(),
            "kind": self.kind_combo.currentData() or "",
            "emotion": self.emotion_combo.currentData() or "",
            "style": self.style_combo.currentData() or "",
        }

    def _analyze_all(self):
        """批量分析待分析音频（服务端后台任务）。"""
        self.btn_analyze_all.setEnabled(False)
        self.lbl_stat.setText("⏳ 正在提交批量分析...")
        w = self.track_worker(_AudioAnalyzeAllWorker())
        w.finished.connect(self._on_analyze_all_done)
        w.error.connect(lambda m: self._on_analyze_all_error(str(m)))
        w.start()

    def _on_analyze_all_done(self, data):
        self.btn_analyze_all.setEnabled(True)
        d = data or {}
        self.lbl_stat.setText(
            f"批量分析已提交（task_id={d.get('task_id') or '?'}）")
        QTimer.singleShot(2000, self._do_search)

    def _on_analyze_all_error(self, msg):
        self.btn_analyze_all.setEnabled(True)
        friendly = msg
        if "Connection" in msg or "timed out" in msg or "Max retries" in msg:
            friendly = "无法连接服务端，请检查服务端是否在线"
        self.lbl_stat.setText(f"❌ 批量分析失败: {friendly}")

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
            kind_name = {"sfx": "音效", "voice": "口播", "music": "音乐"}.get(
                classify_audio(item), "未分类")
            # 分析结果（独立 audio_analysis 表最新一条）
            analysis = item.get("analysis") or {}
            emotion = analysis.get("emotion") or ""
            styles = analysis.get("styles") or []
            style_str = "/".join(str(s) for s in styles) if styles else ""
            status = item.get("analysis_status") or "pending"
            status_name = {"analyzed": "已分析", "pending": "待分析", "failed": "失败"}.get(status, status)
            tip = (f"🎵 {fname}\n分类: {kind_name}\n大小: {size_str}\n"
                   f"分析: {status_name}")
            if emotion:
                tip += f"\n情感: {emotion}"
            if style_str:
                tip += f"\n风格: {style_str}"
            if analysis.get("tempo_bpm"):
                tip += f"\nBPM: {analysis['tempo_bpm']}"
            lw = QListWidgetItem()
            # 文本：分类 + 文件名 + 情感/风格 + 分析状态标记
            extra = ""
            if emotion:
                extra += f" [{emotion}]"
            if style_str:
                extra += f" {style_str}"
            status_mark = {"analyzed": "✓", "pending": "○", "failed": "✗"}.get(status, "○")
            lw.setText(f"[{kind_name}] {fname[:30]}{extra}  {status_mark}")
            lw.setToolTip(tip)
            lw.setIcon(self._pm_audio)
            lw.setData(Qt.UserRole, {"mid": mid, "filename": fname, "id": mid})
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
