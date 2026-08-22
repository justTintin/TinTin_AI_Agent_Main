"""
音频素材页面（媒体库 → 音频素材）。

音频与图片/视频不同：不绑定具体产品，而是与场景/情绪关联，
按 音效(SFX) / 配音(VO) / 音乐(Music) 三类组织。

数据源：
- 全部（复用素材库接口）：
  - 浏览：GET /material/list?media_type=audio（无关键词）
  - 语义检索：POST /material/search（有关键词，带 media_type=audio）
  - 试听：GET /material/serve?material_id=xx（服务端 Range 流式播放）
- BGM 库：/audio/library, /audio/bgm/tags, /audio/bgm/upload
- 音效库：/sfx/library, /sfx/analyze
- AI 生成：/audio/gen/bgm (MusicGen), /audio/gen/sfx (AudioLDM2)
- 口播管理：/audio/library?type=voice
"""
import contextlib
import os

import requests.exceptions
from gui.base_page import BasePage
from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from utils import audio_library_client as alc
from utils import material_client
from utils.base_worker import BaseWorker
from utils.gui_icons import icon_button, mdi_icon, std_icon
from utils.http_client import http_get


def _set_button_icon(btn, name):
    """优先使用 Qt 标准图标，缺失则回退到 mdi 图标。"""
    icon = std_icon(name)
    if icon.isNull():
        icon = mdi_icon(name)
    btn.setIcon(icon)


def _make_audio_icon():
    """音频列表占位图标。"""
    pm = QPixmap(QSize(48, 48))
    pm.fill(QColor("#3b2f5b"))
    p = QPainter(pm)
    p.setPen(QColor("#ffffff"))
    f = p.font()
    f.setPointSize(16)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "")
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


def _ext_from_content_type(ct):
    """根据 Content-Type 推断本地缓存文件的扩展名。"""
    ct = (ct or "").lower()
    for mime, ext in [("audio/mpeg", ".mp3"), ("audio/mp3", ".mp3"),
                      ("audio/wav", ".wav"), ("audio/x-wav", ".wav"),
                      ("audio/ogg", ".ogg"), ("audio/mp4", ".m4a"),
                      ("audio/aac", ".aac"), ("audio/flac", ".flac")]:
        if mime in ct:
            return ext
    return ".mp3"


def _fmt_sec(seconds):
    """秒 -> M:SS"""
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


def _fmt_ms(ms):
    """毫秒 -> M:SS"""
    return _fmt_sec(int(ms / 1000))


class _AudioPreviewWorker(BaseWorker):
    """后台下载音频到本地临时文件，再交给 QMediaPlayer 播放。"""
    finished = Signal(str)  # 本地临时文件路径

    def __init__(self, url, mid):
        super().__init__()
        self.url = url
        self.mid = mid

    def do_work(self):
        import tempfile
        resp = http_get(self.url, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"服务端返回 HTTP {resp.status_code}")
        data = resp.content
        if not data:
            raise RuntimeError("服务端返回空内容")
        ext = _ext_from_content_type(resp.headers.get("Content-Type", ""))
        cache_dir = os.path.join(tempfile.gettempdir(), "audio_preview")
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"{self.mid}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        self.finished.emit(path)


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
        try:
            if self.query:
                params = {"query": self.query, "media_type": "audio",
                          "limit": self.limit, "offset": self.offset}
                if self.tag:
                    params["tag"] = self.tag
                data = material_client.search(params, timeout=20)
                if data is None:
                    raise RuntimeError("服务端素材检索失败")
                results = data.get("results") or data.get("data") or []
                total = data.get("total") or len(results)
            else:
                # 服务端 /material/list 使用 page/size 分页（limit/offset 无效）
                params = {"media_type": "audio", "size": self.limit,
                          "page": (self.offset // self.limit) + 1 if self.limit else 1}
                if self.tag:
                    params["tag"] = self.tag
                data = material_client.list(params, timeout=20)
                if data is None:
                    raise RuntimeError("服务端素材列表获取失败")
                results = data.get("items") or []
                total = data.get("total") or len(results)
            self.finished.emit(results, int(total))
        except requests.exceptions.RequestException as e:
            self.error.emit(str(e))


# ════════════════════════════════════════════════════════════════════════════
#  BGM 库 Worker
# ════════════════════════════════════════════════════════════════════════════
class _BgmListWorker(BaseWorker):
    """BGM 库列表加载。"""
    finished = Signal(list, int)

    def __init__(self, page=1, size=50, tag="", scene="", mood=""):
        super().__init__()
        self.page = page
        self.size = size
        self.tag = tag
        self.scene = scene
        self.mood = mood

    def do_work(self):
        data = alc.bgm_list(self.page, self.size, self.tag, self.scene, self.mood)
        if data is None:
            raise RuntimeError("服务端 BGM 库获取失败")
        results = data.get("items") or data.get("results") or []
        total = data.get("total") or len(results)
        self.finished.emit(results, int(total))


class _BgmTagsWorker(BaseWorker):
    """获取 BGM 标签体系。"""
    finished = Signal(dict)

    def do_work(self):
        data = alc.bgm_tags()
        self.finished.emit(data or {})


class _BgmUploadWorker(BaseWorker):
    """上传 BGM 文件。"""
    finished = Signal(dict)

    def __init__(self, file_path, tag="", scene="", mood=""):
        super().__init__()
        self.file_path = file_path
        self.tag = tag
        self.scene = scene
        self.mood = mood

    def do_work(self):
        data = alc.bgm_upload(self.file_path, self.tag, self.scene, self.mood)
        if data is None:
            raise RuntimeError("上传失败")
        self.finished.emit(data)


# ════════════════════════════════════════════════════════════════════════════
#  音效库 Worker
# ════════════════════════════════════════════════════════════════════════════
class _SfxListWorker(BaseWorker):
    """音效库列表加载。"""
    finished = Signal(list, int)

    def __init__(self, category="", tag="", page=1, size=50):
        super().__init__()
        self.category = category
        self.tag = tag
        self.page = page
        self.size = size

    def do_work(self):
        data = alc.sfx_list(self.category, self.tag, self.page, self.size)
        if data is None:
            raise RuntimeError("服务端音效库获取失败")
        results = data.get("items") or data.get("results") or []
        total = data.get("total") or len(results)
        self.finished.emit(results, int(total))


# ════════════════════════════════════════════════════════════════════════════
#  AI 生成 Worker
# ════════════════════════════════════════════════════════════════════════════
class _GenBgmWorker(BaseWorker):
    """AI 生成 BGM (MusicGen)。"""
    finished = Signal(dict)

    def __init__(self, prompt, style="auto", duration=30):
        super().__init__()
        self.prompt = prompt
        self.style = style
        self.duration = duration

    def do_work(self):
        data = alc.gen_bgm(self.prompt, self.style, self.duration)
        if data is None:
            raise RuntimeError("BGM 生成失败")
        self.finished.emit(data)


class _GenSfxWorker(BaseWorker):
    """AI 生成音效 (AudioLDM2)。"""
    finished = Signal(dict)

    def __init__(self, prompt, duration=3):
        super().__init__()
        self.prompt = prompt
        self.duration = duration

    def do_work(self):
        data = alc.gen_sfx(self.prompt, self.duration)
        if data is None:
            raise RuntimeError("音效生成失败")
        self.finished.emit(data)


# ════════════════════════════════════════════════════════════════════════════
#  口播管理 Worker
# ════════════════════════════════════════════════════════════════════════════
class _VoiceListWorker(BaseWorker):
    """口播音频列表加载。"""
    finished = Signal(list, int)

    def __init__(self, page=1, size=50, tag=""):
        super().__init__()
        self.page = page
        self.size = size
        self.tag = tag

    def do_work(self):
        data = alc.voice_list(self.page, self.size, self.tag)
        if data is None:
            raise RuntimeError("服务端口播库获取失败")
        results = data.get("items") or data.get("results") or []
        total = data.get("total") or len(results)
        self.finished.emit(results, int(total))


class _VoiceUploadWorker(BaseWorker):
    """上传口播音频。"""
    finished = Signal(dict)

    def __init__(self, file_path, tag="", voice_name=""):
        super().__init__()
        self.file_path = file_path
        self.tag = tag
        self.voice_name = voice_name

    def do_work(self):
        data = alc.voice_upload(self.file_path, self.tag, self.voice_name)
        if data is None:
            raise RuntimeError("口播上传失败")
        self.finished.emit(data)


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
        self._playing_name = ""
        self._preview_worker = None
        self._preview_mid: str | None = None
        self._pending_play = False
        self._seeking = False
        self._beat_worker = None
        self._beat_pending = []

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # ── 标题 ──
        title = QLabel(" 音频素材")
        title.setObjectName("heading")
        title.setFixedHeight(28)
        title.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        root.addWidget(title, 0, Qt.AlignLeft)

        # ── Tab 容器 ──
        tab_container = QWidget()
        tab_layout = QVBoxLayout(tab_container)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        self._tab_bar = QTabBar()
        self._tab_bar.setDocumentMode(True)
        tab_layout.addWidget(self._tab_bar)

        self._stack = QStackedWidget()
        tab_layout.addWidget(self._stack, 1)

        root.addWidget(tab_container, 1)

        # ── Tab: 全部（原有素材库功能）──
        self._tab_all = QWidget()
        self._build_tab_all(self._tab_all)
        self._tab_bar.addTab(" 全部")
        self._stack.addWidget(self._tab_all)

        # ── Tab: BGM 库 ──
        self._tab_bgm = QWidget()
        self._build_tab_bgm(self._tab_bgm)
        self._tab_bar.addTab(" BGM 库")
        self._stack.addWidget(self._tab_bgm)

        # ── Tab: 音效库 ──
        self._tab_sfx = QWidget()
        self._build_tab_sfx(self._tab_sfx)
        self._tab_bar.addTab(" 音效库")
        self._stack.addWidget(self._tab_sfx)

        # ── Tab: AI 生成 ──
        self._tab_ai = QWidget()
        self._build_tab_ai(self._tab_ai)
        self._tab_bar.addTab(" AI 生成")
        self._stack.addWidget(self._tab_ai)

        # ── Tab: 口播管理 ──
        self._tab_voice = QWidget()
        self._build_tab_voice(self._tab_voice)
        self._tab_bar.addTab(" 口播管理")
        self._stack.addWidget(self._tab_voice)

        self._tab_bar.currentChanged.connect(self._stack.setCurrentIndex)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)

        # ── 统一播放控制条（所有 tab 共享）──
        play_row = QHBoxLayout()
        play_row.setSpacing(6)
        self.btn_play_pause = icon_button("play", "播放 / 暂停")
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.clicked.connect(self._toggle_play_pause)
        play_row.addWidget(self.btn_play_pause)
        self.btn_stop = icon_button("stop", "停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_preview)
        play_row.addWidget(self.btn_stop)
        self.slider_progress = QSlider(Qt.Horizontal)
        self.slider_progress.setRange(0, 0)
        self.slider_progress.setEnabled(False)
        self.slider_progress.sliderMoved.connect(self._on_seek)
        play_row.addWidget(self.slider_progress, 1)
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setObjectName("muted_text")
        self.lbl_time.setMinimumWidth(84)
        play_row.addWidget(self.lbl_time)
        root.addLayout(play_row)

        self.lbl_now_playing = QLabel("未在播放")
        self.lbl_now_playing.setObjectName("muted_text")
        root.addWidget(self.lbl_now_playing)

        self._pm_audio = _make_audio_icon()
        QTimer.singleShot(100, self._do_search)

    # ════════════════════════════════════════════════════════════════════════
    #  Tab: 全部 — 原有素材库功能
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab_all(self, tab):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # 搜索
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索音频（语义检索，如：激昂的背景音乐）")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        self.btn_search = QPushButton(" 搜索")
        self.btn_search.setObjectName("primary_button")
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        layout.addLayout(search_row)

        # 分类 + 标签 + 状态
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
        self.tag_input.setPlaceholderText("情绪/场景标签")
        self.tag_input.setMaximumWidth(200)
        self.tag_input.returnPressed.connect(self._do_search)
        row.addWidget(self.tag_input)
        row.addStretch(1)
        self.lbl_stat = QLabel("")
        self.lbl_stat.setObjectName("muted_text")
        row.addWidget(self.lbl_stat)
        layout.addLayout(row)

        # 音频列表
        self._COL_HEADERS = ["", "文件名", "分类", "时长", "大小", "用途", "描述", "标签"]
        self._COL_CHECK = 0
        self._COL_FNAME = 1
        self._COL_KIND = 2
        self._COL_DUR = 3
        self._COL_SIZE = 4
        self._COL_USE = 5
        self._COL_DESC = 6
        self._COL_TAGS = 7
        self._col_widths = [38, 240, 70, 60, 70, 80, 180, 120]
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._COL_HEADERS))
        self.table.setHorizontalHeaderLabels(self._COL_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(250)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.setStyleSheet(
            "QTableWidget { background: #1a1a24; border: 1px solid #2e2e38; border-radius: 8px; font-size: 13px; }"
            "QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #26262e; }"
            "QTableWidget::item:selected { background: #2b3a63; color: #ffffff; }"
            "QHeaderView::section { background: #222230; color: #8b90a3; border: none; "
            "border-bottom: 1px solid #2e2e38; padding: 5px 6px; font-size: 12px; }")
        hdr = self.table.horizontalHeader()
        for ci, w in enumerate(self._col_widths):
            self.table.setColumnWidth(ci, w)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(self._COL_FNAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self._COL_DESC, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        # 操作行
        sel_row = QHBoxLayout()
        self.btn_select_all = QPushButton(" 全选")
        self.btn_select_all.setObjectName("secondary_button")
        self.btn_select_all.clicked.connect(self._select_all)
        sel_row.addWidget(self.btn_select_all)
        self.btn_deselect_all = QPushButton(" 取消全选")
        self.btn_deselect_all.setObjectName("secondary_button")
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        sel_row.addWidget(self.btn_deselect_all)
        sel_row.addStretch(1)
        self.lbl_hint = QLabel(" 双击试听 · 勾选后可发送到卡点成片")
        self.lbl_hint.setObjectName("muted_text")
        sel_row.addWidget(self.lbl_hint)
        self.btn_beat = QPushButton(" 卡点成片")
        self.btn_beat.setObjectName("primary_button")
        self.btn_beat.clicked.connect(self._send_to_beat_montage)
        sel_row.addWidget(self.btn_beat)
        layout.addLayout(sel_row)



        # 分页
        page_row = QHBoxLayout()
        self.btn_prev = icon_button("previous", "上一页")
        self.btn_prev.clicked.connect(self._go_prev_page)
        page_row.addWidget(self.btn_prev)
        self.lbl_page = QLabel("")
        self.lbl_page.setObjectName("muted_text")
        page_row.addWidget(self.lbl_page)
        self.btn_next = icon_button("next", "下一页")
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
        layout.addLayout(page_row)

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
        self.lbl_stat.setText(f"失败：{friendly}")
        self.table.setRowCount(0)
        self._results = []
        self._total = 0
        self._update_page_label()

    # ── 列表 ──
    # --- list ---
    def _fill_list(self, rows):
        self.table.setRowCount(0)
        kind = (self._last_params or {}).get("kind", "")
        _KIND_TEXT = {"sfx": "音效", "voice": "配音", "music": "音乐"}  # noqa: N806
        display_rows = []
        for item in rows:
            if kind and classify_audio(item) != kind:
                continue
            mid = str(item.get("id") or item.get("material_id") or "")
            fname = item.get("filename", "") or "未命名"
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else "—"
            dur = item.get("duration_s")
            dur_str = _fmt_sec(dur) if dur else "—"
            kind_code = classify_audio(item)
            kind_name = _KIND_TEXT.get(kind_code, "未分类")
            use_case = item.get("use_case") or ""
            brand = item.get("brand") or ""
            scene = item.get("scene_desc_primary") or ""
            tags = item.get("tags") or []
            tags_str = ", ".join(str(t) for t in tags[:3]) if tags else ""
            score = item.get("score")
            tip_parts = [f" {fname}", f"分类: {kind_name}",
                         f"时长: {dur_str}", f"大小: {size_str}"]
            if use_case:
                tip_parts.append(f"用途: {use_case}")
            if brand:
                tip_parts.append(f"品牌: {brand}")
            if scene:
                tip_parts.append(f"描述: {scene}")
            if tags_str:
                tip_parts.append(f"标签: {tags_str}")
            if score is not None:
                tip_parts.append(f"相关度: {float(score):.3f}")
            tooltip = "\n".join(tip_parts)
            display_rows.append({
                "mid": mid, "fname": fname, "kind_name": kind_name,
                "dur_str": dur_str, "size_str": size_str,
                "use_case": use_case, "scene": scene, "tags_str": tags_str,
                "tooltip": tooltip, "raw": item,
            })
        self.table.setRowCount(len(display_rows))
        for ri, d in enumerate(display_rows):
            ck = QTableWidgetItem()
            ck.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            ck.setCheckState(Qt.Unchecked)
            ck.setData(Qt.UserRole, {"mid": d["mid"], "filename": d["fname"], "raw": d["raw"]})  # noqa: E501
            self.table.setItem(ri, self._COL_CHECK, ck)
            it_name = QTableWidgetItem(d["fname"])
            it_name.setIcon(self._pm_audio)
            it_name.setToolTip(d["tooltip"])
            self.table.setItem(ri, self._COL_FNAME, it_name)
            self.table.setItem(ri, self._COL_KIND, QTableWidgetItem(d["kind_name"]))
            self.table.setItem(ri, self._COL_DUR, QTableWidgetItem(d["dur_str"]))
            self.table.setItem(ri, self._COL_SIZE, QTableWidgetItem(d["size_str"]))
            self.table.setItem(ri, self._COL_USE, QTableWidgetItem(d["use_case"] or "—"))  # noqa: E501
            self.table.setItem(ri, self._COL_DESC, QTableWidgetItem(d["scene"] or "—"))
            self.table.setItem(ri, self._COL_TAGS, QTableWidgetItem(d["tags_str"] or "—"))  # noqa: E501
            self.table.setRowHeight(ri, 28)
        self.lbl_stat.setText(
            f"共 {self._total} 条音频（本页显示 {len(display_rows)} 条）")

    def _select_all(self):
        for i in range(self.table.rowCount()):
            it = self.table.item(i, self._COL_CHECK)
            if it:
                it.setCheckState(Qt.Checked)

    def _deselect_all(self):
        for i in range(self.table.rowCount()):
            it = self.table.item(i, self._COL_CHECK)
            if it:
                it.setCheckState(Qt.Unchecked)

    def _ensure_player(self):
        """创建新的 QMediaPlayer，避免切换源时后端状态污染导致卡死。"""
        if self._player is not None:
            with contextlib.suppress(Exception):
                self._player.stop()
            self._player.deleteLater()
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        return self._player

    def _on_cell_double_clicked(self, row, col):
        """Double-click row: same track toggles pause/play, different track switches."""
        ck = self.table.item(row, self._COL_CHECK)
        if ck is None:
            return
        data = ck.data(Qt.UserRole) or {}
        mid = str(data.get("mid") or "")
        if not mid:
            return
        if self._playing_mid == mid and self._player is not None:
            state = self._player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
            return
        self._play_by_mid(mid, data)

    def _toggle_play_pause(self):
        if self._player is None or self._playing_mid is None:
            row = self.table.currentRow()
            if row >= 0:
                ck = self.table.item(row, self._COL_CHECK)
                if ck:
                    self._play_by_mid(str((ck.data(Qt.UserRole) or {}).get("mid", "")),
                                       ck.data(Qt.UserRole) or {})
            return
        player = self._player
        if player is None:
            return
        state = player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
        else:
            player.play()

    def _play_by_mid(self, mid, data):
        if not mid:
            return
        if self._playing_mid is not None:
            self._stop_preview()
        if (self._preview_worker is not None
                and self._preview_worker.isRunning()
                and self._preview_mid == mid):
            return
        self._playing_mid = mid
        self._playing_name = data.get("filename", mid)
        self._preview_mid = mid
        self.lbl_now_playing.setText(f"加载中: {self._playing_name}…")
        _set_button_icon(self.btn_play_pause, "play")
        self._update_play_button()
        self._preview_worker = _AudioPreviewWorker(material_client.serve_url(mid), mid)
        self._preview_worker.finished.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_preview_ready(self, path):
        if self._playing_mid is None:
            return
        player = self._ensure_player()
        self._pending_play = True
        player.setSource(QUrl.fromLocalFile(path))
        if player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia:
            self._pending_play = False
            player.play()
            name = self._playing_name or ''
            self.lbl_now_playing.setText(f"播放中: {name}")
            # 更新所有 tab 的状态标签
            self._update_tab_status_labels(f"播放中: {name}")
        self.btn_stop.setEnabled(True)
        self.slider_progress.setEnabled(True)

    def _update_tab_status_labels(self, text):
        """更新所有 tab 的播放状态标签。"""
        for lbl in [getattr(self, 'lbl_bgm_now', None),
                    getattr(self, 'lbl_sfx_now', None),
                    getattr(self, 'lbl_voice_now', None)]:
            if lbl is not None:
                lbl.setText(text)

    def _on_preview_error(self, msg):
        self._preview_mid = None
        self._playing_mid = None
        self._playing_name = ""
        err_text = f"播放失败: {msg}"
        self.lbl_now_playing.setText(err_text)
        self._update_tab_status_labels(err_text)
        self._update_play_button()

    def _stop_preview(self):
        self._pending_play = False
        if self._player is not None:
            self._player.stop()
        self._playing_mid = None
        self._playing_name = ""
        self.lbl_now_playing.setText("未在播放")
        self._update_tab_status_labels("未在播放")
        self.slider_progress.setRange(0, 0)
        self.slider_progress.setValue(0)
        self.slider_progress.setEnabled(False)
        self.lbl_time.setText("0:00 / 0:00")
        self.btn_stop.setEnabled(False)
        self._update_play_button()

    def _on_position_changed(self, pos):
        if not self._seeking:
            self.slider_progress.blockSignals(True)
            self.slider_progress.setValue(pos)
            self.slider_progress.blockSignals(False)
        dur = self.slider_progress.maximum()
        self.lbl_time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_duration_changed(self, dur):
        self.slider_progress.setRange(0, dur)
        self.lbl_time.setText(f"0:00 / {_fmt_ms(dur)}")

    def _on_seek(self, pos):
        if self._player is not None:
            self._seeking = True
            self._player.setPosition(pos)
            self._seeking = False
            dur = self.slider_progress.maximum()
            self.lbl_time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_playback_state_changed(self, _state):
        self._update_play_button()

    def _update_play_button(self):
        if self._player is None or self._playing_mid is None:
            _set_button_icon(self.btn_play_pause, "play")
            self.btn_play_pause.setEnabled(False)
            return
        self.btn_play_pause.setEnabled(True)
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            _set_button_icon(self.btn_play_pause, "pause")
            name = self._playing_name or ''
            self.lbl_now_playing.setText(f"播放中: {name}")
        else:
            _set_button_icon(self.btn_play_pause, "play")
            name = self._playing_name or ''
            if self._pending_play:
                self.lbl_now_playing.setText(f"加载中: {name}…")
            else:
                self.lbl_now_playing.setText(f"已暂停: {name}")

    def _on_media_status(self, status):
        if (status == QMediaPlayer.MediaStatus.LoadedMedia
                and getattr(self, "_pending_play", False)):
            self._pending_play = False
            if self._player is not None:
                self._player.play()
                self.lbl_now_playing.setText(
                    f"播放 播放中: {self._playing_name or ''}")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._pending_play = False
            self.slider_progress.setValue(0)
            name = self._playing_name or ''
            self.lbl_now_playing.setText(f"播放结束: {name}")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._playing_mid = None
            self._playing_name = ""
            self._pending_play = False
            self.lbl_now_playing.setText(
                "无法播放该音频（格式不支持或文件损坏）")
            self._update_play_button()

    def _on_player_error(self, error, error_string):
        """QMediaPlayer 报错时清理状态，避免卡住播放状态。"""
        self._playing_mid = None
        self._playing_name = ""
        self._pending_play = False
        self.lbl_now_playing.setText(f"播放失败: {error_string}")
        self._update_play_button()

    # ── 卡点成片 ──
    def _send_to_beat_montage(self):
        """Send checked audios to beat montage (download first, then switch page)."""
        checked = []
        for i in range(self.table.rowCount()):
            ck = self.table.item(i, self._COL_CHECK)
            if ck and ck.checkState() == Qt.Checked:
                data = ck.data(Qt.UserRole) or {}
                mid = str(data.get("mid") or "")
                if mid:
                    checked.append(data)
        if not checked:
            QMessageBox.information(
                self.parent_widget, "提示",
                "请先勾选至少一条音频。")
            return
        mw = getattr(self, "main_window", None)
        if mw is None:
            QMessageBox.warning(self.parent_widget, "错误",
                                "无法访问主窗口。")
            return
        first = checked[0]
        mid = first["mid"]
        fname = first.get("filename", mid)
        self._beat_pending = checked
        self.lbl_now_playing.setText(f"正在下载 {fname} 以用于卡点成片…")
        self._beat_worker = _AudioPreviewWorker(material_client.serve_url(mid), mid)
        self._beat_worker.finished.connect(self._on_beat_download_done)
        self._beat_worker.error.connect(self._on_beat_download_error)
        self._beat_worker.start()

    def _on_beat_download_done(self, path):
        mw = getattr(self, "main_window", None)
        if mw is None:
            return
        try:
            mw.switch_page(33)
            tool = getattr(mw, "compile_video_tool", None)
            if tool is None:
                mw.switch_page(45)
                self.lbl_now_playing.setText("失败：一键成片页未加载")
                return
            bc = getattr(tool, "beat_controller", None)
            if bc is not None:
                tabs = getattr(tool, "tabs", None)
                if tabs is not None:
                    for i in range(tabs.count()):
                        if "卡点" in tabs.tabText(i):
                            tabs.setCurrentIndex(i)
                            break
                bc.beat_music_path.setText(path)
                if hasattr(bc, "btn_beat_detect"):
                    bc.btn_beat_detect.setEnabled(True)
                if hasattr(bc, "beat_status_lbl"):
                    extra = ""
                    if len(self._beat_pending) > 1:
                        extra = f"（另有 {len(self._beat_pending) - 1} 首已选）"
                    bc.beat_status_lbl.setText(
                        f"已从音频素材带入: {os.path.basename(path)}{extra}")
                if hasattr(bc, "step_beat"):
                    bc.step_beat.load_music(path)
            self.lbl_now_playing.setText(
                f"已跳转到卡点成片: {os.path.basename(path)}")
        except (AttributeError, KeyError, TypeError) as e:
            self.lbl_now_playing.setText(f"失败：跳转失败: {e}")

    def _on_beat_download_error(self, msg):
        self.lbl_now_playing.setText(f"失败：下载音频失败: {msg}")

    # ── 分页 ──
    def _update_page_label(self):
        page_size = self._page_size or 1
        cur_page = (self._offset // page_size) + 1 if self._total > 0 else 0
        total_pages = max(1, (self._total + page_size - 1) // page_size) if self._total > 0 else 0  # noqa: E501
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

    # ════════════════════════════════════════════════════════════════════════
    #  Tab 切换
    # ════════════════════════════════════════════════════════════════════════
    def _on_tab_changed(self, index):
        tab_name = self._tab_bar.tabText(index).strip()
        if tab_name == "BGM 库":
            if not getattr(self, "_bgm_loaded", False):
                self._load_bgm_list()
                self._bgm_loaded = True
        elif tab_name == "音效库":
            if not getattr(self, "_sfx_loaded", False):
                self._load_sfx_list()
                self._sfx_loaded = True
        elif tab_name == "口播管理":
            if not getattr(self, "_voice_loaded", False):
                self._load_voice_list()
                self._voice_loaded = True

    # ════════════════════════════════════════════════════════════════════════
    #  Tab: BGM 库
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab_bgm(self, tab):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # 筛选行
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("场景:"))
        self.bgm_scene_combo = QComboBox()
        self.bgm_scene_combo.addItem("全部", "")
        filter_row.addWidget(self.bgm_scene_combo)
        filter_row.addWidget(QLabel("情绪:"))
        self.bgm_mood_combo = QComboBox()
        self.bgm_mood_combo.addItem("全部", "")
        filter_row.addWidget(self.bgm_mood_combo)
        filter_row.addWidget(QLabel("标签:"))
        self.bgm_tag_input = QLineEdit()
        self.bgm_tag_input.setPlaceholderText("搜索标签")
        self.bgm_tag_input.setMaximumWidth(150)
        self.bgm_tag_input.returnPressed.connect(self._load_bgm_list)
        filter_row.addWidget(self.bgm_tag_input)
        self.btn_bgm_search = QPushButton(" 搜索")
        self.btn_bgm_search.setObjectName("primary_button")
        self.btn_bgm_search.clicked.connect(self._load_bgm_list)
        filter_row.addWidget(self.btn_bgm_search)
        filter_row.addStretch(1)
        self.btn_bgm_upload = QPushButton(" 上传 BGM")
        self.btn_bgm_upload.setObjectName("secondary_button")
        self.btn_bgm_upload.clicked.connect(self._on_bgm_upload)
        filter_row.addWidget(self.btn_bgm_upload)
        layout.addLayout(filter_row)

        self.lbl_bgm_stat = QLabel("")
        self.lbl_bgm_stat.setObjectName("muted_text")
        layout.addWidget(self.lbl_bgm_stat)

        # BGM 列表表格
        self._bgm_headers = ["文件名", "时长", "大小", "场景", "情绪", "标签", "操作"]
        self._bgm_table = QTableWidget()
        self._bgm_table.setColumnCount(len(self._bgm_headers))
        self._bgm_table.setHorizontalHeaderLabels(self._bgm_headers)
        self._bgm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._bgm_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._bgm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._bgm_table.verticalHeader().setVisible(False)
        self._bgm_table.setShowGrid(False)
        self._bgm_table.setMinimumHeight(250)
        self._bgm_table.setStyleSheet(
            "QTableWidget { background: #1a1a24; border: 1px solid #2e2e38; border-radius: 8px; font-size: 13px; }"
            "QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #26262e; }"
            "QTableWidget::item:selected { background: #2b3a63; color: #ffffff; }"
            "QHeaderView::section { background: #222230; color: #8b90a3; border: none; "
            "border-bottom: 1px solid #2e2e38; padding: 5px 6px; font-size: 12px; }")
        bgm_hdr = self._bgm_table.horizontalHeader()
        bgm_widths = [240, 70, 70, 100, 100, 120, 80]
        for ci, w in enumerate(bgm_widths):
            self._bgm_table.setColumnWidth(ci, w)
        bgm_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._bgm_table, 1)

        # 双击播放 + 发送按钮
        self._bgm_table.cellDoubleClicked.connect(self._on_bgm_cell_double_clicked)
        bgm_action_row = QHBoxLayout()
        bgm_action_row.addStretch(1)
        self.lbl_bgm_now = QLabel("未在播放")
        self.lbl_bgm_now.setObjectName("muted_text")
        bgm_action_row.addWidget(self.lbl_bgm_now)
        self.btn_bgm_to_beat = QPushButton(" 发送到卡点成片")
        self.btn_bgm_to_beat.setObjectName("primary_button")
        self.btn_bgm_to_beat.clicked.connect(self._send_bgm_to_beat)
        bgm_action_row.addWidget(self.btn_bgm_to_beat)
        layout.addLayout(bgm_action_row)

        # 分页
        bgm_page_row = QHBoxLayout()
        self.btn_bgm_prev = icon_button("previous", "上一页")
        self.btn_bgm_prev.clicked.connect(self._load_bgm_prev)
        bgm_page_row.addWidget(self.btn_bgm_prev)
        self.lbl_bgm_page = QLabel("")
        self.lbl_bgm_page.setObjectName("muted_text")
        bgm_page_row.addWidget(self.lbl_bgm_page)
        self.btn_bgm_next = icon_button("next", "下一页")
        self.btn_bgm_next.clicked.connect(self._load_bgm_next)
        bgm_page_row.addWidget(self.btn_bgm_next)
        bgm_page_row.addStretch(1)
        self._bgm_page = 1
        self._bgm_total = 0
        layout.addLayout(bgm_page_row)

    def _load_bgm_list(self):
        self.btn_bgm_search.setEnabled(False)
        self.lbl_bgm_stat.setText("加载中...")
        tag = self.bgm_tag_input.text().strip()
        scene = self.bgm_scene_combo.currentData() or ""
        mood = self.bgm_mood_combo.currentData() or ""
        w = self.track_worker(_BgmListWorker(
            page=self._bgm_page, size=50, tag=tag, scene=scene, mood=mood))
        w.finished.connect(self._on_bgm_list_done)
        w.error.connect(lambda msg: self._on_bgm_list_error(msg))
        w.start()

    def _on_bgm_list_done(self, results, total):
        self.btn_bgm_search.setEnabled(True)
        self._bgm_total = total
        self._fill_bgm_table(results)
        self._update_bgm_page_label()
        self.lbl_bgm_stat.setText(f"共 {total} 条 BGM（本页 {len(results)} 条）")

    def _on_bgm_list_error(self, msg):
        self.btn_bgm_search.setEnabled(True)
        self.lbl_bgm_stat.setText(f"失败：{msg}")

    def _fill_bgm_table(self, rows):
        self._bgm_table.setRowCount(0)
        for ri, item in enumerate(rows):
            fname = item.get("filename") or item.get("name") or "未命名"
            dur = item.get("duration_s") or item.get("duration")
            dur_str = _fmt_sec(dur) if dur else "—"
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else "—"
            scene = item.get("scene") or item.get("scene_name") or "—"
            mood = item.get("mood") or item.get("mood_name") or "—"
            tags = item.get("tags") or []
            tags_str = ", ".join(str(t) for t in tags[:3]) if tags else "—"
            audio_id = str(item.get("id") or item.get("audio_id") or "")

            self._bgm_table.insertRow(ri)
            it_fname = QTableWidgetItem(fname)
            it_fname.setData(Qt.UserRole, {"audio_id": audio_id, "raw": item})
            self._bgm_table.setItem(ri, 0, it_fname)
            self._bgm_table.setItem(ri, 1, QTableWidgetItem(dur_str))
            self._bgm_table.setItem(ri, 2, QTableWidgetItem(size_str))
            self._bgm_table.setItem(ri, 3, QTableWidgetItem(scene))
            self._bgm_table.setItem(ri, 4, QTableWidgetItem(mood))
            self._bgm_table.setItem(ri, 5, QTableWidgetItem(tags_str))
            btn_play = QPushButton("试听")
            btn_play.setMaximumWidth(60)
            btn_play.clicked.connect(lambda _=False, r=ri: self._play_bgm_row(r))
            self._bgm_table.setCellWidget(ri, 6, btn_play)
            self._bgm_table.setRowHeight(ri, 28)

    # ── 双击处理 ──
    def _on_bgm_cell_double_clicked(self, row, col):
        """BGM 库双击行：切换播放/暂停/切换曲目。"""
        it = self._bgm_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        if self._playing_mid == audio_id and self._player is not None:
            state = self._player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
            return
        self._play_bgm_row(row)

    def _on_sfx_cell_double_clicked(self, row, col):
        """音效库双击行：切换播放/暂停/切换曲目。"""
        it = self._sfx_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        sfx_id = str(data.get("sfx_id") or "")
        if not sfx_id:
            return
        if self._playing_mid == sfx_id and self._player is not None:
            state = self._player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
            return
        self._play_sfx_row(row)

    def _on_voice_cell_double_clicked(self, row, col):
        """口播管理双击行：切换播放/暂停/切换曲目。"""
        it = self._voice_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        if self._playing_mid == audio_id and self._player is not None:
            state = self._player.playbackState()
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
            return
        self._play_voice_row(row)

    def _play_bgm_row(self, row=-1):
        if row < 0:
            row = self._bgm_table.currentRow()
        if row < 0:
            return
        it = self._bgm_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        raw = data.get("raw") or {}
        mid = raw.get("source_material_id") or raw.get("material_id")
        if mid:
            from utils import material_client
            url = material_client.serve_url(str(mid))
        else:
            url = alc.bgm_serve_url(audio_id)
        self._play_audio(audio_id, it.text(), url, self.lbl_bgm_now)

    def _play_sfx_row(self, row=-1):
        if row < 0:
            row = self._sfx_table.currentRow()
        if row < 0:
            return
        it = self._sfx_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        sfx_id = str(data.get("sfx_id") or "")
        if not sfx_id:
            return
        raw = data.get("raw") or {}
        mid = raw.get("source_material_id") or raw.get("material_id")
        if mid:
            from utils import material_client
            url = material_client.serve_url(str(mid))
        elif hasattr(alc, "sfx_serve_url"):
            url = alc.sfx_serve_url(sfx_id)
        else:
            from utils import material_client
            url = material_client.serve_url(sfx_id)
        self._play_audio(sfx_id, it.text(), url, self.lbl_sfx_now)

    def _play_voice_row(self, row=-1):
        if row < 0:
            row = self._voice_table.currentRow()
        if row < 0:
            return
        it = self._voice_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        raw = data.get("raw") or {}
        mid = raw.get("source_material_id") or raw.get("material_id")
        if mid:
            from utils import material_client
            url = material_client.serve_url(str(mid))
        else:
            url = alc.bgm_serve_url(audio_id)
        self._play_audio(audio_id, it.text(), url, self.lbl_voice_now)

    def _play_audio(self, audio_id, name, url, status_label):
        """统一的音频播放方法。"""
        if self._playing_mid is not None:
            self._stop_preview()
        if (self._preview_worker is not None
                and self._preview_worker.isRunning()
                and self._preview_mid == audio_id):
            return
        self._playing_mid = audio_id
        self._playing_name = name
        self._preview_mid = audio_id
        self.lbl_now_playing.setText(f"加载中: {name}…")
        status_label.setText(f"加载中: {name}…")
        _set_button_icon(self.btn_play_pause, "play")
        self._update_play_button()
        self._preview_worker = _AudioPreviewWorker(url, audio_id)
        self._preview_worker.finished.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _send_bgm_to_beat(self):
        row = self._bgm_table.currentRow()
        if row < 0:
            QMessageBox.information(self.parent_widget, "提示", "请先选择一条 BGM。")
            return
        it = self._bgm_table.item(row, 0)
        data = (it.data(Qt.UserRole) or {}) if it else {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        raw = data.get("raw") or {}
        mid = raw.get("source_material_id") or raw.get("material_id")
        if mid:
            from utils import material_client
            url = material_client.serve_url(str(mid))
        else:
            url = alc.bgm_serve_url(audio_id)
        self._preview_worker = _AudioPreviewWorker(url, audio_id)
        self._preview_worker.finished.connect(self._on_bgm_to_beat_downloaded)
        self._preview_worker.error.connect(
            lambda msg: self.lbl_bgm_now.setText(f"下载失败: {msg}"))
        self._preview_worker.start()

    def _on_bgm_to_beat_downloaded(self, path):
        mw = getattr(self, "main_window", None)
        if mw is None:
            return
        try:
            mw.switch_page(33)
            tool = getattr(mw, "compile_video_tool", None)
            if tool is None:
                mw.switch_page(45)
                self.lbl_bgm_now.setText("失败：一键成片页未加载")
                return
            bc = getattr(tool, "beat_controller", None)
            if bc is not None:
                tabs = getattr(tool, "tabs", None)
                if tabs is not None:
                    for i in range(tabs.count()):
                        if "卡点" in tabs.tabText(i):
                            tabs.setCurrentIndex(i)
                            break
                bc.beat_music_path.setText(path)
                if hasattr(bc, "btn_beat_detect"):
                    bc.btn_beat_detect.setEnabled(True)
                if hasattr(bc, "beat_status_lbl"):
                    bc.beat_status_lbl.setText(
                        f"已从 BGM 库带入: {os.path.basename(path)}")
                if hasattr(bc, "step_beat"):
                    bc.step_beat.load_music(path)
            self.lbl_bgm_now.setText(
                f"已跳转到卡点成片: {os.path.basename(path)}")
        except (AttributeError, KeyError, TypeError) as e:
            self.lbl_bgm_now.setText(f"跳转失败: {e}")

    def _on_bgm_upload(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择 BGM 文件", "",
            "音频文件 (*.mp3 *.wav *.ogg *.m4a *.flac *.aac)")
        if not file_path:
            return
        dlg = _BgmUploadDialog(self.parent_widget, file_path)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.btn_bgm_upload.setEnabled(False)
        self.btn_bgm_upload.setText("上传中...")
        w = self.track_worker(_BgmUploadWorker(
            file_path, tag=dlg.tag_edit.text().strip(),
            scene=dlg.scene_edit.text().strip(),
            mood=dlg.mood_edit.text().strip()))
        w.finished.connect(self._on_bgm_upload_done)
        w.error.connect(self._on_bgm_upload_error)
        w.start()

    def _on_bgm_upload_done(self, data):
        self.btn_bgm_upload.setEnabled(True)
        self.btn_bgm_upload.setText(" 上传 BGM")
        QMessageBox.information(self.parent_widget, "成功",
                                f"BGM 上传成功！\n{data}")
        self._load_bgm_list()

    def _on_bgm_upload_error(self, msg):
        self.btn_bgm_upload.setEnabled(True)
        self.btn_bgm_upload.setText(" 上传 BGM")
        QMessageBox.warning(self.parent_widget, "失败",
                            f"BGM 上传失败：{msg}")

    def _update_bgm_page_label(self):
        page_size = 50
        cur = self._bgm_page
        total = max(1, (self._bgm_total + page_size - 1) // page_size) if self._bgm_total else 0
        self.lbl_bgm_page.setText(f"第 {cur} / {total} 页")
        self.btn_bgm_prev.setEnabled(self._bgm_page > 1)
        self.btn_bgm_next.setEnabled(self._bgm_page * page_size < self._bgm_total)

    def _load_bgm_prev(self):
        if self._bgm_page <= 1:
            return
        self._bgm_page -= 1
        self._load_bgm_list()

    def _load_bgm_next(self):
        if self._bgm_page * 50 >= self._bgm_total:
            return
        self._bgm_page += 1
        self._load_bgm_list()

    # ════════════════════════════════════════════════════════════════════════
    #  Tab: 音效库
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab_sfx(self, tab):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("分类:"))
        self.sfx_category_combo = QComboBox()
        self.sfx_category_combo.addItem("全部", "")
        for cat in ("环境", "人物", "动物", "机械", "自然", "交通", "其他"):
            self.sfx_category_combo.addItem(cat, cat)
        filter_row.addWidget(self.sfx_category_combo)
        filter_row.addWidget(QLabel("标签:"))
        self.sfx_tag_input = QLineEdit()
        self.sfx_tag_input.setPlaceholderText("搜索标签")
        self.sfx_tag_input.setMaximumWidth(150)
        self.sfx_tag_input.returnPressed.connect(self._load_sfx_list)
        filter_row.addWidget(self.sfx_tag_input)
        self.btn_sfx_search = QPushButton(" 搜索")
        self.btn_sfx_search.setObjectName("primary_button")
        self.btn_sfx_search.clicked.connect(self._load_sfx_list)
        filter_row.addWidget(self.btn_sfx_search)
        filter_row.addStretch(1)
        self.btn_sfx_ai_gen = QPushButton(" AI 生成音效")
        self.btn_sfx_ai_gen.setObjectName("secondary_button")
        self.btn_sfx_ai_gen.clicked.connect(
            lambda: self._tab_bar.setCurrentIndex(self._stack.indexOf(self._tab_ai)))
        filter_row.addWidget(self.btn_sfx_ai_gen)
        layout.addLayout(filter_row)

        self.lbl_sfx_stat = QLabel("")
        self.lbl_sfx_stat.setObjectName("muted_text")
        layout.addWidget(self.lbl_sfx_stat)

        self._sfx_headers = ["名称", "分类", "时长", "标签", "操作"]
        self._sfx_table = QTableWidget()
        self._sfx_table.setColumnCount(len(self._sfx_headers))
        self._sfx_table.setHorizontalHeaderLabels(self._sfx_headers)
        self._sfx_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._sfx_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._sfx_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._sfx_table.verticalHeader().setVisible(False)
        self._sfx_table.setShowGrid(False)
        self._sfx_table.setMinimumHeight(250)
        self._sfx_table.setStyleSheet(
            "QTableWidget { background: #1a1a24; border: 1px solid #2e2e38; border-radius: 8px; font-size: 13px; }"
            "QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #26262e; }"
            "QTableWidget::item:selected { background: #2b3a63; color: #ffffff; }"
            "QHeaderView::section { background: #222230; color: #8b90a3; border: none; "
            "border-bottom: 1px solid #2e2e38; padding: 5px 6px; font-size: 12px; }")
        sfx_hdr = self._sfx_table.horizontalHeader()
        sfx_widths = [250, 80, 70, 150, 60]
        for ci, w in enumerate(sfx_widths):
            self._sfx_table.setColumnWidth(ci, w)
        sfx_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._sfx_table, 1)

        self._sfx_table.cellDoubleClicked.connect(self._on_sfx_cell_double_clicked)
        sfx_action_row = QHBoxLayout()
        self.lbl_sfx_now = QLabel("未在播放")
        self.lbl_sfx_now.setObjectName("muted_text")
        sfx_action_row.addWidget(self.lbl_sfx_now)
        sfx_action_row.addStretch(1)
        layout.addLayout(sfx_action_row)

        sfx_page_row = QHBoxLayout()
        self.btn_sfx_prev = icon_button("previous", "上一页")
        self.btn_sfx_prev.clicked.connect(self._load_sfx_prev)
        sfx_page_row.addWidget(self.btn_sfx_prev)
        self.lbl_sfx_page = QLabel("")
        self.lbl_sfx_page.setObjectName("muted_text")
        sfx_page_row.addWidget(self.lbl_sfx_page)
        self.btn_sfx_next = icon_button("next", "下一页")
        self.btn_sfx_next.clicked.connect(self._load_sfx_next)
        sfx_page_row.addWidget(self.btn_sfx_next)
        sfx_page_row.addStretch(1)
        self._sfx_page = 1
        self._sfx_total = 0
        layout.addLayout(sfx_page_row)

    def _load_sfx_list(self):
        self.btn_sfx_search.setEnabled(False)
        self.lbl_sfx_stat.setText("加载中...")
        category = self.sfx_category_combo.currentData() or ""
        tag = self.sfx_tag_input.text().strip()
        w = self.track_worker(_SfxListWorker(
            category=category, tag=tag, page=self._sfx_page, size=50))
        w.finished.connect(self._on_sfx_list_done)
        w.error.connect(lambda msg: self._on_sfx_list_error(msg))
        w.start()

    def _on_sfx_list_done(self, results, total):
        self.btn_sfx_search.setEnabled(True)
        self._sfx_total = total
        self._fill_sfx_table(results)
        self._update_sfx_page_label()
        self.lbl_sfx_stat.setText(f"共 {total} 条音效（本页 {len(results)} 条）")

    def _on_sfx_list_error(self, msg):
        self.btn_sfx_search.setEnabled(True)
        self.lbl_sfx_stat.setText(f"失败：{msg}")

    def _fill_sfx_table(self, rows):
        self._sfx_table.setRowCount(0)
        for ri, item in enumerate(rows):
            name = item.get("name") or item.get("filename") or "未命名"
            cat = item.get("category") or item.get("category_name") or "—"
            dur = item.get("duration_s") or item.get("duration")
            dur_str = _fmt_sec(dur) if dur else "—"
            tags = item.get("tags") or []
            tags_str = ", ".join(str(t) for t in tags[:3]) if tags else "—"
            sfx_id = str(item.get("id") or item.get("sfx_id") or "")

            self._sfx_table.insertRow(ri)
            it_name = QTableWidgetItem(name)
            it_name.setData(Qt.UserRole, {"sfx_id": sfx_id, "raw": item})
            self._sfx_table.setItem(ri, 0, it_name)
            self._sfx_table.setItem(ri, 1, QTableWidgetItem(cat))
            self._sfx_table.setItem(ri, 2, QTableWidgetItem(dur_str))
            self._sfx_table.setItem(ri, 3, QTableWidgetItem(tags_str))
            btn_play = QPushButton("试听")
            btn_play.setMaximumWidth(60)
            btn_play.clicked.connect(lambda _=False, r=ri: self._play_sfx_row(r))
            self._sfx_table.setCellWidget(ri, 4, btn_play)
            self._sfx_table.setRowHeight(ri, 28)

    def _play_sfx_row(self, row=-1):
        if row < 0:
            row = self._sfx_table.currentRow()
        if row < 0:
            return
        it = self._sfx_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        sfx_id = str(data.get("sfx_id") or "")
        if not sfx_id:
            return
        url = alc.sfx_serve_url(sfx_id)
        self._playing_mid = sfx_id
        self._playing_name = it.text()
        self.lbl_sfx_now.setText(f"加载中: {self._playing_name}…")
        self._preview_worker = _AudioPreviewWorker(url, sfx_id)
        self._preview_worker.finished.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _update_sfx_page_label(self):
        page_size = 50
        cur = self._sfx_page
        total = max(1, (self._sfx_total + page_size - 1) // page_size) if self._sfx_total else 0
        self.lbl_sfx_page.setText(f"第 {cur} / {total} 页")
        self.btn_sfx_prev.setEnabled(self._sfx_page > 1)
        self.btn_sfx_next.setEnabled(self._sfx_page * page_size < self._sfx_total)

    def _load_sfx_prev(self):
        if self._sfx_page <= 1:
            return
        self._sfx_page -= 1
        self._load_sfx_list()

    def _load_sfx_next(self):
        if self._sfx_page * 50 >= self._sfx_total:
            return
        self._sfx_page += 1
        self._load_sfx_list()

    # ════════════════════════════════════════════════════════════════════════
    #  Tab: AI 生成
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab_ai(self, tab):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # BGM 生成
        bgm_group = QGroupBox(" AI 生成 BGM（MusicGen）")
        bgm_layout = QVBoxLayout(bgm_group)
        bgm_layout.setSpacing(6)

        bgm_prompt_row = QHBoxLayout()
        bgm_prompt_row.addWidget(QLabel("描述:"))
        self.ai_bgm_prompt = QLineEdit()
        self.ai_bgm_prompt.setPlaceholderText("描述你想要的 BGM 风格，如：激昂的电子音乐，适合科技感视频")
        bgm_prompt_row.addWidget(self.ai_bgm_prompt, 1)
        bgm_layout.addLayout(bgm_prompt_row)

        bgm_params_row = QHBoxLayout()
        bgm_params_row.addWidget(QLabel("风格:"))
        self.ai_bgm_style = QComboBox()
        self.ai_bgm_style.addItem("自动", "auto")
        self.ai_bgm_style.addItem("电子", "electronic")
        self.ai_bgm_style.addItem("古典", "classical")
        self.ai_bgm_style.addItem("摇滚", "rock")
        self.ai_bgm_style.addItem("爵士", "jazz")
        self.ai_bgm_style.addItem("氛围", "ambient")
        self.ai_bgm_style.addItem("Lo-Fi", "lofi")
        bgm_params_row.addWidget(self.ai_bgm_style)
        bgm_params_row.addWidget(QLabel("时长(秒):"))
        self.ai_bgm_duration = QSpinBox()
        self.ai_bgm_duration.setRange(5, 120)
        self.ai_bgm_duration.setValue(30)
        self.ai_bgm_duration.setSingleStep(5)
        bgm_params_row.addWidget(self.ai_bgm_duration)
        bgm_params_row.addStretch(1)
        self.btn_ai_bgm_gen = QPushButton(" 生成 BGM")
        self.btn_ai_bgm_gen.setObjectName("primary_button")
        self.btn_ai_bgm_gen.clicked.connect(self._on_gen_bgm)
        bgm_params_row.addWidget(self.btn_ai_bgm_gen)
        bgm_layout.addLayout(bgm_params_row)

        self.ai_bgm_progress = QProgressBar()
        self.ai_bgm_progress.setVisible(False)
        bgm_layout.addWidget(self.ai_bgm_progress)

        self.ai_bgm_result_label = QLabel("")
        self.ai_bgm_result_label.setObjectName("muted_text")
        self.ai_bgm_result_label.setWordWrap(True)
        bgm_layout.addWidget(self.ai_bgm_result_label)

        bgm_action_row = QHBoxLayout()
        self.btn_ai_bgm_play = icon_button("play", "播放生成的 BGM")
        self.btn_ai_bgm_play.setEnabled(False)
        self.btn_ai_bgm_play.clicked.connect(self._on_play_ai_bgm)
        bgm_action_row.addWidget(self.btn_ai_bgm_play)
        self.btn_ai_bgm_save = QPushButton(" 保存到 BGM 库")
        self.btn_ai_bgm_save.setObjectName("secondary_button")
        self.btn_ai_bgm_save.setEnabled(False)
        self.btn_ai_bgm_save.clicked.connect(self._on_save_bgm_to_lib)
        bgm_action_row.addWidget(self.btn_ai_bgm_save)
        bgm_action_row.addStretch(1)
        bgm_layout.addLayout(bgm_action_row)

        layout.addWidget(bgm_group)

        # 音效生成
        sfx_group = QGroupBox(" AI 生成音效（AudioLDM2）")
        sfx_layout = QVBoxLayout(sfx_group)
        sfx_layout.setSpacing(6)

        sfx_prompt_row = QHBoxLayout()
        sfx_prompt_row.addWidget(QLabel("描述:"))
        self.ai_sfx_prompt = QLineEdit()
        self.ai_sfx_prompt.setPlaceholderText("描述你想要的音效，如：门铃声、打字声、雨声、爆炸效果")
        sfx_prompt_row.addWidget(self.ai_sfx_prompt, 1)
        sfx_layout.addLayout(sfx_prompt_row)

        sfx_params_row = QHBoxLayout()
        sfx_params_row.addWidget(QLabel("时长(秒):"))
        self.ai_sfx_duration = QSpinBox()
        self.ai_sfx_duration.setRange(1, 15)
        self.ai_sfx_duration.setValue(3)
        sfx_params_row.addWidget(self.ai_sfx_duration)
        sfx_params_row.addStretch(1)
        self.btn_ai_sfx_gen = QPushButton(" 生成音效")
        self.btn_ai_sfx_gen.setObjectName("primary_button")
        self.btn_ai_sfx_gen.clicked.connect(self._on_gen_sfx)
        sfx_params_row.addWidget(self.btn_ai_sfx_gen)
        sfx_layout.addLayout(sfx_params_row)

        self.ai_sfx_progress = QProgressBar()
        self.ai_sfx_progress.setVisible(False)
        sfx_layout.addWidget(self.ai_sfx_progress)

        self.ai_sfx_result_label = QLabel("")
        self.ai_sfx_result_label.setObjectName("muted_text")
        self.ai_sfx_result_label.setWordWrap(True)
        sfx_layout.addWidget(self.ai_sfx_result_label)

        sfx_action_row = QHBoxLayout()
        self.btn_ai_sfx_play = icon_button("play", "播放生成的音效")
        self.btn_ai_sfx_play.setEnabled(False)
        self.btn_ai_sfx_play.clicked.connect(self._on_play_ai_sfx)
        sfx_action_row.addWidget(self.btn_ai_sfx_play)
        self.btn_ai_sfx_save = QPushButton(" 保存到音效库")
        self.btn_ai_sfx_save.setObjectName("secondary_button")
        self.btn_ai_sfx_save.setEnabled(False)
        self.btn_ai_sfx_save.clicked.connect(self._on_save_sfx_to_lib)
        sfx_action_row.addWidget(self.btn_ai_sfx_save)
        sfx_action_row.addStretch(1)
        sfx_layout.addLayout(sfx_action_row)

        layout.addWidget(sfx_group)
        layout.addStretch(1)

        self._ai_bgm_result = None
        self._ai_sfx_result = None

    def _on_gen_bgm(self):
        prompt = self.ai_bgm_prompt.text().strip()
        if not prompt:
            QMessageBox.information(self.parent_widget, "提示", "请输入 BGM 描述。")
            return
        self.btn_ai_bgm_gen.setEnabled(False)
        self.ai_bgm_progress.setVisible(True)
        self.ai_bgm_progress.setRange(0, 0)
        self.ai_bgm_result_label.setText("BGM 生成中，可能需要 30-60 秒...")
        style = self.ai_bgm_style.currentData() or "auto"
        duration = self.ai_bgm_duration.value()
        w = self.track_worker(_GenBgmWorker(prompt, style, duration))
        w.finished.connect(self._on_gen_bgm_done)
        w.error.connect(self._on_gen_bgm_error)
        w.start()

    def _on_gen_bgm_done(self, data):
        self.btn_ai_bgm_gen.setEnabled(True)
        self.ai_bgm_progress.setVisible(False)
        self._ai_bgm_result = data
        url = data.get("url") or data.get("audio_url") or data.get("file_url") or ""
        name = data.get("filename") or data.get("name") or "AI 生成 BGM"
        self.ai_bgm_result_label.setText(
            f"生成成功！{name}\n时长: {data.get('duration', '—')} 秒\nURL: {url}")
        self.btn_ai_bgm_play.setEnabled(bool(url))
        self.btn_ai_bgm_save.setEnabled(bool(url))
        self._ai_bgm_url = url
        self._ai_bgm_name = name

    def _on_gen_bgm_error(self, msg):
        self.btn_ai_bgm_gen.setEnabled(True)
        self.ai_bgm_progress.setVisible(False)
        self.ai_bgm_result_label.setText(f"BGM 生成失败：{msg}")

    def _on_play_ai_bgm(self):
        url = getattr(self, "_ai_bgm_url", "")
        name = getattr(self, "_ai_bgm_name", "AI 生成 BGM")
        if not url:
            return
        self._play_audio("ai_bgm", name, url, self.ai_bgm_result_label)

    def _on_save_bgm_to_lib(self):
        url = getattr(self, "_ai_bgm_url", "")
        name = getattr(self, "_ai_bgm_name", "ai_bgm")
        if not url:
            return
        self.btn_ai_bgm_save.setEnabled(False)
        self.btn_ai_bgm_save.setText("保存中...")
        from utils.thread_worker import TaskWorker as Worker
        def _do_upload():
            import tempfile

            import requests as req
            resp = req.get(url, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"下载失败 HTTP {resp.status_code}")
            ext = ".mp3"
            cd = resp.headers.get("Content-Type", "")
            if "wav" in cd:
                ext = ".wav"
            tmp = os.path.join(tempfile.gettempdir(), f"ai_bgm_{os.getpid()}{ext}")
            with open(tmp, "wb") as f:
                f.write(resp.content)
            r = alc.bgm_upload(tmp, tag="AI生成", scene="", mood="")
            if r is None:
                raise RuntimeError("上传到库失败")
            return r
        worker = Worker(_do_upload)
        def _ok(data):
            self.btn_ai_bgm_save.setEnabled(True)
            self.btn_ai_bgm_save.setText(" 保存到 BGM 库")
            QMessageBox.information(self.parent_widget, "成功",
                                    f"已保存到 BGM 库！\n{data}")
        def _err(e):
            self.btn_ai_bgm_save.setEnabled(True)
            self.btn_ai_bgm_save.setText(" 保存到 BGM 库")
            QMessageBox.warning(self.parent_widget, "失败",
                                f"保存失败：{e}")
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker)
        worker.start()

    def _on_gen_sfx(self):
        prompt = self.ai_sfx_prompt.text().strip()
        if not prompt:
            QMessageBox.information(self.parent_widget, "提示", "请输入音效描述。")
            return
        self.btn_ai_sfx_gen.setEnabled(False)
        self.ai_sfx_progress.setVisible(True)
        self.ai_sfx_progress.setRange(0, 0)
        self.ai_sfx_result_label.setText("音效生成中，可能需要 15-30 秒...")
        duration = self.ai_sfx_duration.value()
        w = self.track_worker(_GenSfxWorker(prompt, duration))
        w.finished.connect(self._on_gen_sfx_done)
        w.error.connect(self._on_gen_sfx_error)
        w.start()

    def _on_gen_sfx_done(self, data):
        self.btn_ai_sfx_gen.setEnabled(True)
        self.ai_sfx_progress.setVisible(False)
        self._ai_sfx_result = data
        url = data.get("url") or data.get("audio_url") or data.get("file_url") or ""
        name = data.get("name") or data.get("filename") or "AI 生成音效"
        self.ai_sfx_result_label.setText(
            f"生成成功！{name}\n时长: {data.get('duration', '—')} 秒\nURL: {url}")
        self.btn_ai_sfx_play.setEnabled(bool(url))
        self.btn_ai_sfx_save.setEnabled(bool(url))
        self._ai_sfx_url = url
        self._ai_sfx_name = name

    def _on_gen_sfx_error(self, msg):
        self.btn_ai_sfx_gen.setEnabled(True)
        self.ai_sfx_progress.setVisible(False)
        self.ai_sfx_result_label.setText(f"音效生成失败：{msg}")

    def _on_play_ai_sfx(self):
        url = getattr(self, "_ai_sfx_url", "")
        name = getattr(self, "_ai_sfx_name", "AI 生成音效")
        if not url:
            return
        self._play_audio("ai_sfx", name, url, self.ai_sfx_result_label)

    def _on_save_sfx_to_lib(self):
        url = getattr(self, "_ai_sfx_url", "")
        if not url:
            return
        self.btn_ai_sfx_save.setEnabled(False)
        self.btn_ai_sfx_save.setText("保存中...")
        from utils.thread_worker import TaskWorker as Worker
        def _do_upload():
            import tempfile

            import requests as req
            resp = req.get(url, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"下载失败 HTTP {resp.status_code}")
            ext = ".wav"
            cd = resp.headers.get("Content-Type", "")
            if "mpeg" in cd or "mp3" in cd:
                ext = ".mp3"
            tmp = os.path.join(tempfile.gettempdir(), f"ai_sfx_{os.getpid()}{ext}")
            with open(tmp, "wb") as f:
                f.write(resp.content)
            r = alc.sfx_analyze(tmp)
            if r is None:
                raise RuntimeError("音效分析入库失败")
            return r
        worker = Worker(_do_upload)
        def _ok(data):
            self.btn_ai_sfx_save.setEnabled(True)
            self.btn_ai_sfx_save.setText(" 保存到音效库")
            QMessageBox.information(self.parent_widget, "成功",
                                    f"已保存到音效库！\n{data}")
        def _err(e):
            self.btn_ai_sfx_save.setEnabled(True)
            self.btn_ai_sfx_save.setText(" 保存到音效库")
            QMessageBox.warning(self.parent_widget, "失败",
                                f"保存失败：{e}")
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker)
        worker.start()

    # ════════════════════════════════════════════════════════════════════════
    #  Tab: 口播管理
    # ════════════════════════════════════════════════════════════════════════
    def _build_tab_voice(self, tab):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("标签:"))
        self.voice_tag_input = QLineEdit()
        self.voice_tag_input.setPlaceholderText("搜索标签")
        self.voice_tag_input.setMaximumWidth(200)
        self.voice_tag_input.returnPressed.connect(self._load_voice_list)
        filter_row.addWidget(self.voice_tag_input)
        self.btn_voice_search = QPushButton(" 搜索")
        self.btn_voice_search.setObjectName("primary_button")
        self.btn_voice_search.clicked.connect(self._load_voice_list)
        filter_row.addWidget(self.btn_voice_search)
        filter_row.addStretch(1)
        self.btn_voice_upload = QPushButton(" 上传口播")
        self.btn_voice_upload.setObjectName("secondary_button")
        self.btn_voice_upload.clicked.connect(self._on_voice_upload)
        filter_row.addWidget(self.btn_voice_upload)
        layout.addLayout(filter_row)

        self.lbl_voice_stat = QLabel("")
        self.lbl_voice_stat.setObjectName("muted_text")
        layout.addWidget(self.lbl_voice_stat)

        self._voice_headers = ["名称", "时长", "大小", "标签", "操作"]
        self._voice_table = QTableWidget()
        self._voice_table.setColumnCount(len(self._voice_headers))
        self._voice_table.setHorizontalHeaderLabels(self._voice_headers)
        self._voice_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._voice_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._voice_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._voice_table.verticalHeader().setVisible(False)
        self._voice_table.setShowGrid(False)
        self._voice_table.setMinimumHeight(250)
        self._voice_table.setStyleSheet(
            "QTableWidget { background: #1a1a24; border: 1px solid #2e2e38; border-radius: 8px; font-size: 13px; }"
            "QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #26262e; }"
            "QTableWidget::item:selected { background: #2b3a63; color: #ffffff; }"
            "QHeaderView::section { background: #222230; color: #8b90a3; border: none; "
            "border-bottom: 1px solid #2e2e38; padding: 5px 6px; font-size: 12px; }")
        voice_hdr = self._voice_table.horizontalHeader()
        voice_widths = [280, 70, 70, 150, 60]
        for ci, w in enumerate(voice_widths):
            self._voice_table.setColumnWidth(ci, w)
        voice_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._voice_table, 1)

        self._voice_table.cellDoubleClicked.connect(self._on_voice_cell_double_clicked)
        voice_action_row = QHBoxLayout()
        self.lbl_voice_now = QLabel("未在播放")
        self.lbl_voice_now.setObjectName("muted_text")
        voice_action_row.addWidget(self.lbl_voice_now)
        voice_action_row.addStretch(1)
        layout.addLayout(voice_action_row)

        voice_page_row = QHBoxLayout()
        self.btn_voice_prev = icon_button("previous", "上一页")
        self.btn_voice_prev.clicked.connect(self._load_voice_prev)
        voice_page_row.addWidget(self.btn_voice_prev)
        self.lbl_voice_page = QLabel("")
        self.lbl_voice_page.setObjectName("muted_text")
        voice_page_row.addWidget(self.lbl_voice_page)
        self.btn_voice_next = icon_button("next", "下一页")
        self.btn_voice_next.clicked.connect(self._load_voice_next)
        voice_page_row.addWidget(self.btn_voice_next)
        voice_page_row.addStretch(1)
        self._voice_page = 1
        self._voice_total = 0
        layout.addLayout(voice_page_row)

    def _load_voice_list(self):
        self.btn_voice_search.setEnabled(False)
        self.lbl_voice_stat.setText("加载中...")
        tag = self.voice_tag_input.text().strip()
        w = self.track_worker(_VoiceListWorker(
            page=self._voice_page, size=50, tag=tag))
        w.finished.connect(self._on_voice_list_done)
        w.error.connect(lambda msg: self._on_voice_list_error(msg))
        w.start()

    def _on_voice_list_done(self, results, total):
        self.btn_voice_search.setEnabled(True)
        self._voice_total = total
        self._fill_voice_table(results)
        self._update_voice_page_label()
        self.lbl_voice_stat.setText(f"共 {total} 条口播（本页 {len(results)} 条）")

    def _on_voice_list_error(self, msg):
        self.btn_voice_search.setEnabled(True)
        self.lbl_voice_stat.setText(f"失败：{msg}")

    def _fill_voice_table(self, rows):
        self._voice_table.setRowCount(0)
        for ri, item in enumerate(rows):
            name = item.get("voice_name") or item.get("filename") or item.get("name") or "未命名"
            dur = item.get("duration_s") or item.get("duration")
            dur_str = _fmt_sec(dur) if dur else "—"
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else "—"
            tags = item.get("tags") or []
            tags_str = ", ".join(str(t) for t in tags[:3]) if tags else "—"
            audio_id = str(item.get("id") or item.get("audio_id") or "")

            self._voice_table.insertRow(ri)
            it_name = QTableWidgetItem(name)
            it_name.setData(Qt.UserRole, {"audio_id": audio_id, "raw": item})
            self._voice_table.setItem(ri, 0, it_name)
            self._voice_table.setItem(ri, 1, QTableWidgetItem(dur_str))
            self._voice_table.setItem(ri, 2, QTableWidgetItem(size_str))
            self._voice_table.setItem(ri, 3, QTableWidgetItem(tags_str))
            btn_play = QPushButton("试听")
            btn_play.setMaximumWidth(60)
            btn_play.clicked.connect(lambda _=False, r=ri: self._play_voice_row(r))
            self._voice_table.setCellWidget(ri, 4, btn_play)
            self._voice_table.setRowHeight(ri, 28)

    def _play_voice_row(self, row=-1):
        if row < 0:
            row = self._voice_table.currentRow()
        if row < 0:
            return
        it = self._voice_table.item(row, 0)
        if it is None:
            return
        data = it.data(Qt.UserRole) or {}
        audio_id = str(data.get("audio_id") or "")
        if not audio_id:
            return
        url = alc.bgm_serve_url(audio_id)
        self._playing_mid = audio_id
        self._playing_name = it.text()
        self.lbl_voice_now.setText(f"加载中: {self._playing_name}…")
        self._preview_worker = _AudioPreviewWorker(url, audio_id)
        self._preview_worker.finished.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.start()

    def _on_voice_upload(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择口播音频文件", "",
            "音频文件 (*.mp3 *.wav *.ogg *.m4a)")
        if not file_path:
            return
        dlg = _VoiceUploadDialog(self.parent_widget, file_path)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.btn_voice_upload.setEnabled(False)
        self.btn_voice_upload.setText("上传中...")
        w = self.track_worker(_VoiceUploadWorker(
            file_path, tag=dlg.tag_edit.text().strip(),
            voice_name=dlg.name_edit.text().strip()))
        w.finished.connect(self._on_voice_upload_done)
        w.error.connect(self._on_voice_upload_error)
        w.start()

    def _on_voice_upload_done(self, data):
        self.btn_voice_upload.setEnabled(True)
        self.btn_voice_upload.setText(" 上传口播")
        QMessageBox.information(self.parent_widget, "成功",
                                f"口播上传成功！\n{data}")
        self._load_voice_list()

    def _on_voice_upload_error(self, msg):
        self.btn_voice_upload.setEnabled(True)
        self.btn_voice_upload.setText(" 上传口播")
        QMessageBox.warning(self.parent_widget, "失败",
                            f"口播上传失败：{msg}")

    def _update_voice_page_label(self):
        page_size = 50
        cur = self._voice_page
        total = max(1, (self._voice_total + page_size - 1) // page_size) if self._voice_total else 0
        self.lbl_voice_page.setText(f"第 {cur} / {total} 页")
        self.btn_voice_prev.setEnabled(self._voice_page > 1)
        self.btn_voice_next.setEnabled(self._voice_page * page_size < self._voice_total)

    def _load_voice_prev(self):
        if self._voice_page <= 1:
            return
        self._voice_page -= 1
        self._load_voice_list()

    def _load_voice_next(self):
        if self._voice_page * 50 >= self._voice_total:
            return
        self._voice_page += 1
        self._load_voice_list()


# ════════════════════════════════════════════════════════════════════════════
#  上传对话框
# ════════════════════════════════════════════════════════════════════════════
class _BgmUploadDialog(QDialog):
    """BGM 上传对话框：填写场景/情绪/标签三维标签。"""

    def __init__(self, parent=None, file_path=""):
        super().__init__(parent)
        self.setWindowTitle("上传 BGM")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"文件：{os.path.basename(file_path)}"))

        form = QVBoxLayout()
        form.addWidget(QLabel("标签（逗号分隔）:"))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("如：科技感, 激昂")
        form.addWidget(self.tag_edit)
        form.addWidget(QLabel("场景:"))
        self.scene_edit = QLineEdit()
        self.scene_edit.setPlaceholderText("如：产品展示、旅游风景")
        form.addWidget(self.scene_edit)
        form.addWidget(QLabel("情绪:"))
        self.mood_edit = QLineEdit()
        self.mood_edit.setPlaceholderText("如：温馨、紧张、振奋")
        form.addWidget(self.mood_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


class _VoiceUploadDialog(QDialog):
    """口播上传对话框：填写名称/标签。"""

    def __init__(self, parent=None, file_path=""):
        super().__init__(parent)
        self.setWindowTitle("上传口播")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"文件：{os.path.basename(file_path)}"))

        form = QVBoxLayout()
        form.addWidget(QLabel("口播名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("如：产品介绍旁白")
        form.addWidget(self.name_edit)
        form.addWidget(QLabel("标签（逗号分隔）:"))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("如：专业, 亲切")
        form.addWidget(self.tag_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
