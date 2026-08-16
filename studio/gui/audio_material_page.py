# -*- coding: utf-8 -*-
"""
音频素材页面（媒体库 → 音频素材）。

音频与图片/视频不同：不绑定具体产品，而是与场景/情绪关联，
按 音效(SFX) / 配音(VO) / 音乐(Music) 三类组织。

数据源（复用素材库接口）：
- 浏览：GET /material/list?media_type=audio（无关键词）
- 语义检索：POST /material/search（有关键词，带 media_type=audio）
- 试听：GET /material/serve?material_id=xx（服务端 Range 流式播放）
"""
import os
from utils.http_client import http_get, http_post

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSpinBox, QSlider, QFrame, QWidget, QMessageBox,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QUrl
from PySide6.QtWidgets import QHeaderView
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.gui_icons import icon_button, std_icon, mdi_icon


def _set_button_icon(btn, name):
    """优先使用 Qt 标准图标，缺失则回退到 mdi 图标。"""
    icon = std_icon(name)
    if icon.isNull():
        icon = mdi_icon(name)
    btn.setIcon(icon)


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
                resp = http_post(f"{base}/material/search", json=params, timeout=20)
                if resp.status_code != 200:
                    raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                results = data.get("results") or data.get("data") or []
                total = data.get("total") or len(results)
            else:
                # 服务端 /material/list 使用 page/size 分页（limit/offset 无效）
                params = {"media_type": "audio", "size": self.limit,
                          "page": (self.offset // self.limit) + 1 if self.limit else 1}
                if self.tag:
                    params["tag"] = self.tag
                resp = http_get(f"{base}/material/list", params=params, timeout=20)
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
        self._playing_name = ""
        self._preview_worker = None
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

        # ── 搜索 ──
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
        root.addLayout(search_row)

        # ── 分类 + 标签 + 状态 ──
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

        # ── 音频列表（表格分列，带勾选框，双击试听）──
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
        self.table.setMinimumHeight(300)
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
        root.addWidget(self.table, 1)

        # ── 全选 / 取消全选 ──
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
        root.addLayout(sel_row)

        # ── 播放控制条 ──
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
        self.btn_beat = QPushButton(" 卡点成片")
        self.btn_beat.setObjectName("primary_button")
        self.btn_beat.clicked.connect(self._send_to_beat_montage)
        play_row.addWidget(self.btn_beat)
        root.addLayout(play_row)

        # ── 正在播放 ──
        self.lbl_now_playing = QLabel("未在播放")
        self.lbl_now_playing.setObjectName("muted_text")
        root.addWidget(self.lbl_now_playing)

        # ── 分页 ──
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
        self.lbl_stat.setText(f"失败： {friendly}")
        self.table.setRowCount(0)
        self._results = []
        self._total = 0
        self._update_page_label()

    # ── 列表 ──
    # --- list ---
    def _fill_list(self, rows):
        self.table.setRowCount(0)
        kind = (self._last_params or {}).get("kind", "")
        _KIND_TEXT = {"sfx": "音效", "voice": "配音", "music": "音乐"}
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
            ck.setData(Qt.UserRole, {"mid": d["mid"], "filename": d["fname"], "raw": d["raw"]})
            self.table.setItem(ri, self._COL_CHECK, ck)
            it_name = QTableWidgetItem(d["fname"])
            it_name.setIcon(self._pm_audio)
            it_name.setToolTip(d["tooltip"])
            self.table.setItem(ri, self._COL_FNAME, it_name)
            self.table.setItem(ri, self._COL_KIND, QTableWidgetItem(d["kind_name"]))
            self.table.setItem(ri, self._COL_DUR, QTableWidgetItem(d["dur_str"]))
            self.table.setItem(ri, self._COL_SIZE, QTableWidgetItem(d["size_str"]))
            self.table.setItem(ri, self._COL_USE, QTableWidgetItem(d["use_case"] or "—"))
            self.table.setItem(ri, self._COL_DESC, QTableWidgetItem(d["scene"] or "—"))
            self.table.setItem(ri, self._COL_TAGS, QTableWidgetItem(d["tags_str"] or "—"))
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
            try:
                self._player.stop()
            except Exception:
                pass
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
        if (getattr(self, "_preview_worker", None)
                and self._preview_worker.isRunning()
                and getattr(self, "_preview_mid", "") == mid):
            return
        self._playing_mid = mid
        self._playing_name = data.get("filename", mid)
        self._preview_mid = mid
        self.lbl_now_playing.setText(f"加载中: {self._playing_name}…")
        _set_button_icon(self.btn_play_pause, "play")
        self._update_play_button()
        self._preview_worker = _AudioPreviewWorker(_serve_url(mid), mid)
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
            self.lbl_now_playing.setText(
                f"播放中: {self._playing_name or ''}")
        self.btn_stop.setEnabled(True)
        self.slider_progress.setEnabled(True)

    def _on_preview_error(self, msg):
        self._preview_mid = None
        self._playing_mid = None
        self._playing_name = ""
        self.lbl_now_playing.setText(
            f"播放失败: {msg}")
        self._update_play_button()

    def _stop_preview(self):
        self._pending_play = False
        if self._player is not None:
            self._player.stop()
        self._playing_mid = None
        self._playing_name = ""
        self.lbl_now_playing.setText("未在播放")
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
        self._beat_worker = _AudioPreviewWorker(_serve_url(mid), mid)
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
                self.lbl_now_playing.setText("失败： 一键成片页未加载")
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
                f" 已跳转到卡点成片: {os.path.basename(path)}")
        except Exception as e:
            self.lbl_now_playing.setText(f"失败： 跳转失败: {e}")

    def _on_beat_download_error(self, msg):
        self.lbl_now_playing.setText(f"失败： 下载音频失败: {msg}")

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
