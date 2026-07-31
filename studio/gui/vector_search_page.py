# -*- coding: utf-8 -*-
"""
素材检索页面（page 39）— Rao.Pics(Rua)/Eagle 式布局。

布局：顶部搜索栏 + 左侧筛选边栏（库统计/类型/品牌/分类）+ 缩略图网格。
- 无关键词时浏览全库（GET /material/list），有关键词时语义检索（POST /material/search）
- 缩略图走轻量 GET /material/thumbnail（失败回退 /material/serve）
- 双击图片弹大图预览，右键/按钮复制素材地址
"""
import os
import requests
from utils.http_client import http_get, http_post
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QSpinBox, QDialog, QFrame, QSplitter, QWidget, QSlider,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QUrl
from PySide6.QtGui import QGuiApplication, QPixmap, QPainter, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from gui.base_page import BasePage
from utils.base_worker import BaseWorker


# ── 并发节流：同时进行的缩略图请求数上限 ──
_MAX_THUMB_WORKERS = 6
_THUMB_ICON_SIZE = QSize(160, 160)


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
    """素材原文件的服务端流式 URL。"""
    return f"{_get_server_url()}/material/serve?material_id={material_id}"


def _thumb_url(material_id):
    """素材缩略图 URL（服务端生成的小图，比原图快一个数量级）。"""
    return f"{_get_server_url()}/material/thumbnail?material_id={material_id}"


def _make_placeholder_pixmap(text="?", color="#3a3a3c"):
    """生成纯色占位缩略图（带文字，用于图片加载前/视频占位）。"""
    pm = QPixmap(_THUMB_ICON_SIZE)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.setPen(QColor("#888"))
    f = p.font()
    f.setPointSize(20)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return pm


def _fmt_ms(ms):
    """毫秒 → m:ss。"""
    total = max(0, int(ms or 0)) // 1000
    return f"{total // 60}:{total % 60:02d}"


class VideoPreviewDialog(QDialog):
    """内置视频播放器：通过 /material/serve 流式播放服务端素材（支持 Range）。"""

    def __init__(self, url, title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"▶ 视频预览 - {title}")
        self.resize(960, 600)
        self.setObjectName("videoPreviewDialog")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background:#000; border-radius:6px;")
        lay.addWidget(self.video_widget, 1)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        lay.addWidget(self.slider)

        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setObjectName("primary_button")
        self.btn_play.setFixedWidth(90)
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.btn_play)
        ctrl.addStretch(1)
        self.lbl_time = QLabel("加载中…")
        self.lbl_time.setObjectName("muted_text")
        ctrl.addWidget(self.lbl_time)
        lay.addLayout(ctrl)

        self._dragging = False
        self.player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self.player.setAudioOutput(self._audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.setSource(QUrl(url))
        self.player.play()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("⏸ 暂停" if playing else "▶ 播放")

    def _on_position(self, pos):
        if self._dragging:
            return
        dur = self.player.duration()
        if dur > 0:
            self.slider.setValue(int(pos * 1000 / dur))
        self.lbl_time.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_duration(self, dur):
        self.slider.setEnabled(dur > 0)

    def _on_slider_pressed(self):
        self._dragging = True

    def _on_slider_released(self):
        self._dragging = False
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(self.slider.value() * dur / 1000))

    def _on_error(self, _error, error_string):
        self.btn_play.setText("▶ 重试")
        self.lbl_time.setText(f"❌ 播放失败: {error_string}")

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)


class _SearchWorker(BaseWorker):
    """素材检索：有关键词走 /material/search（语义），否则走 /material/list（浏览）。"""
    finished = Signal(list, int)

    def __init__(self, query="", brand="", category="", media_type="", limit=50, offset=0):
        super().__init__()
        self.query = query
        self.brand = brand
        self.category = category
        self.media_type = media_type
        self.limit = limit
        self.offset = offset

    def do_work(self):
        try:
            base = _get_server_url()
            if self.query:
                params = {"query": self.query, "limit": self.limit, "offset": self.offset}
                if self.brand:
                    params["brand"] = self.brand
                if self.category:
                    params["category"] = self.category
                if self.media_type:
                    params["media_type"] = self.media_type
                resp = http_post(f"{base}/material/search", json=params, timeout=20)
                if resp.status_code != 200:
                    raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                results = data.get("results") or data.get("data") or []
                total = data.get("total") or len(results)
            else:
                params = {"limit": self.limit, "offset": self.offset}
                if self.brand:
                    params["brand"] = self.brand
                if self.category:
                    params["category"] = self.category
                if self.media_type:
                    params["media_type"] = self.media_type
                resp = http_get(f"{base}/material/list", params=params, timeout=20)
                if resp.status_code != 200:
                    raise RuntimeError(f"服务器返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                results = data.get("items") or []
                total = data.get("total") or len(results)
            self.finished.emit(results, int(total))
        except Exception as e:
            self.error.emit(str(e))


class _DistinctLoader(BaseWorker):
    """异步获取字段去重列表（品牌/分类）。"""
    finished = Signal(str, list)  # field, values

    def __init__(self, field):
        super().__init__()
        self.field = field

    def do_work(self):
        try:
            url = f"{_get_server_url()}/material/distinct?field={self.field}"
            resp = http_get(url, timeout=15)
            if resp.status_code == 200:
                self.finished.emit(self.field, resp.json().get("values", []))
                return
        except Exception:
            pass
        self.finished.emit(self.field, [])


class _StatsLoader(BaseWorker):
    """异步获取素材库统计。"""
    finished = Signal(dict)

    def do_work(self):
        try:
            resp = http_get(f"{_get_server_url()}/material/stats", timeout=10)
            if resp.status_code == 200:
                self.finished.emit(resp.json())
                return
        except Exception:
            pass
        self.finished.emit({})


class _ThumbWorker(BaseWorker):
    """单个素材缩略图加载（/material/thumbnail，失败回退 /material/serve）。"""
    finished = Signal(str, bytes)  # material_id, image_bytes

    def __init__(self, material_id):
        super().__init__()
        self.material_id = str(material_id)

    def do_work(self):
        try:
            resp = http_get(_thumb_url(self.material_id), timeout=10)
            if resp.status_code != 200 or not resp.content:
                resp = http_get(_serve_url(self.material_id), timeout=10)
            if resp.status_code == 200 and resp.content:
                self.finished.emit(self.material_id, resp.content)
        except Exception:
            pass  # 失败时不 emit finished；BaseWorker.run() 会 emit error，由页面恢复计数


class VectorSearchPage(BasePage):
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # ── 顶部：标题 + 搜索栏 ──
        hdr = QHBoxLayout()
        title = QLabel("🔍 素材检索")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词语义搜索（留空 = 浏览全部素材）")
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setObjectName("primary_button")
        self.btn_search.clicked.connect(self._do_search)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # ── 主体：左筛选边栏 + 右缩略图网格（Rua/Eagle 式）──
        splitter = QSplitter(Qt.Horizontal)

        sidebar = QFrame()
        sidebar.setObjectName("card")
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(240)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(12, 12, 12, 12)
        sb_lay.setSpacing(6)

        # 库统计
        sb_lay.addWidget(self._side_header("📊 素材库"))
        self.lbl_stats = QLabel("加载中…")
        self.lbl_stats.setObjectName("muted_text")
        self.lbl_stats.setWordWrap(True)
        sb_lay.addWidget(self.lbl_stats)

        # 类型
        sb_lay.addWidget(self._side_header("类型"))
        self.type_list = QListWidget()
        self.type_list.setObjectName("side_list")
        for text, data in [("全部", ""), ("🖼 图片", "image"), ("🎬 视频", "video")]:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, data)
            self.type_list.addItem(it)
        self.type_list.setCurrentRow(0)
        self.type_list.setMaximumHeight(88)
        self.type_list.currentRowChanged.connect(self._on_side_filter_changed)
        sb_lay.addWidget(self.type_list)

        # 品牌（带快速过滤）
        sb_lay.addWidget(self._side_header("品牌"))
        self.brand_filter_input = QLineEdit()
        self.brand_filter_input.setPlaceholderText("过滤品牌…")
        self.brand_filter_input.textChanged.connect(self._apply_brand_text_filter)
        sb_lay.addWidget(self.brand_filter_input)
        self.brand_list = QListWidget()
        self.brand_list.setObjectName("side_list")
        self.brand_list.currentRowChanged.connect(self._on_side_filter_changed)
        sb_lay.addWidget(self.brand_list, 1)

        # 分类
        sb_lay.addWidget(self._side_header("分类"))
        self.category_list = QListWidget()
        self.category_list.setObjectName("side_list")
        self.category_list.currentRowChanged.connect(self._on_side_filter_changed)
        sb_lay.addWidget(self.category_list, 1)

        splitter.addWidget(sidebar)

        # 结果缩略图网格
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(_THUMB_ICON_SIZE)
        self.grid.setGridSize(QSize(185, 215))   # 图标 160 + 文件名行高
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)  # 不允许拖动重排
        self.grid.setSpacing(8)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setUniformItemSizes(True)
        self.grid.setStyleSheet("QListWidget { background: #16161f; border: 1px solid #333; border-radius: 4px; }"
                                " QListWidget::item { background: #1c1c24; border-radius: 6px; }"
                                " QListWidget::item:selected { background: #2a3340; border: 1px solid #2ecc71; }")
        self.grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        right_lay.addWidget(self.grid, 1)

        # 分页控件行
        page_row = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 上一页")
        self.btn_prev.setObjectName("secondary_button")
        self.btn_prev.clicked.connect(self._go_prev_page)
        page_row.addWidget(self.btn_prev)
        self.lbl_page = QLabel("第 0 / 0 页")
        self.lbl_page.setObjectName("muted_text")
        page_row.addWidget(self.lbl_page)
        self.btn_next = QPushButton("下一页 ▶")
        self.btn_next.setObjectName("secondary_button")
        self.btn_next.clicked.connect(self._go_next_page)
        page_row.addWidget(self.btn_next)
        page_row.addWidget(QLabel("每页:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(10, 200)
        self.spin_limit.setValue(50)
        self.spin_limit.setFixedWidth(60)
        page_row.addWidget(self.spin_limit)
        page_row.addStretch()
        self.lbl_stat = QLabel("就绪")
        self.lbl_stat.setObjectName("muted_text")
        page_row.addWidget(self.lbl_stat)
        self.btn_copy_url = QPushButton("📋 复制地址")
        self.btn_copy_url.setObjectName("secondary_button")
        self.btn_copy_url.clicked.connect(self._copy_selected_url)
        page_row.addWidget(self.btn_copy_url)
        right_lay.addLayout(page_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # ── 状态 ──
        self._results = []
        self._total = 0
        self._offset = 0
        self._page_size = 50
        self._last_params = None          # 上次搜索的 query/筛选条件（翻页复用）
        self._thumb_cache = {}            # {material_id: QPixmap}
        self._item_by_mid = {}            # {material_id: QListWidgetItem}（worker 回填用）
        self._thumb_queue = []            # 待加载 material_id 队列
        self._active_thumb_count = 0      # 当前在途缩略图 worker 数
        self._brand_values = []           # 品牌全量（供文本过滤）
        self._loading_filters = 0

        # 占位图标（图片加载前 / 视频 / 音频占位）
        self._pm_placeholder = _make_placeholder_pixmap("…")
        self._pm_video = _make_placeholder_pixmap("🎬", "#243b55")
        self._pm_audio = _make_placeholder_pixmap("🎵", "#3b2f5b")

        # 初始：加载统计 + 筛选选项 + 默认浏览全库
        QTimer.singleShot(100, self._init_load)

    def _side_header(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 4px;")
        return lbl

    # ══════════════════════════════════════════
    #  初始化：统计 / 筛选项 / 默认浏览
    # ══════════════════════════════════════════
    def _init_load(self):
        w = self.track_worker(_StatsLoader())
        w.finished.connect(self._on_stats_loaded)
        w.start()
        for field in ("brand", "category"):
            w = self.track_worker(_DistinctLoader(field))
            w.finished.connect(self._on_distinct_loaded)
            w.start()
        self._do_search()  # 空关键词 → 浏览全部

    def _on_stats_loaded(self, stats):
        if not stats:
            self.lbl_stats.setText("统计不可用")
            return
        total = stats.get("total", 0)
        by_type = stats.get("by_type", {})
        self.lbl_stats.setText(
            f"共 {total:,} 个素材\n图片 {by_type.get('image', 0):,} · 视频 {by_type.get('video', 0):,}")

    def _on_distinct_loaded(self, field, values):
        values = [v for v in (values or []) if v and str(v).strip()]
        if field == "brand":
            self._brand_values = values
            self._rebuild_brand_list("")
        elif field == "category":
            self.category_list.blockSignals(True)
            self.category_list.clear()
            it_all = QListWidgetItem("全部")
            it_all.setData(Qt.UserRole, "")
            self.category_list.addItem(it_all)
            for v in values:
                it = QListWidgetItem(str(v))
                it.setData(Qt.UserRole, str(v))
                self.category_list.addItem(it)
            self.category_list.setCurrentRow(0)
            self.category_list.blockSignals(False)

    # ══════════════════════════════════════════
    #  侧边栏筛选
    # ══════════════════════════════════════════
    def _rebuild_brand_list(self, text_filter):
        cur = self._current_data(self.brand_list)
        self.brand_list.blockSignals(True)
        self.brand_list.clear()
        it_all = QListWidgetItem("全部")
        it_all.setData(Qt.UserRole, "")
        self.brand_list.addItem(it_all)
        tf = (text_filter or "").lower()
        shown = 0
        for v in self._brand_values:
            if tf and tf not in str(v).lower():
                continue
            it = QListWidgetItem(str(v))
            it.setData(Qt.UserRole, str(v))
            self.brand_list.addItem(it)
            shown += 1
            if shown >= 300:  # 品牌量巨大，过滤后仍截断，避免卡顿
                break
        # 尽量恢复之前选中的品牌
        self.brand_list.setCurrentRow(0)
        if cur:
            for i in range(self.brand_list.count()):
                if self.brand_list.item(i).data(Qt.UserRole) == cur:
                    self.brand_list.setCurrentRow(i)
                    break
        self.brand_list.blockSignals(False)

    def _apply_brand_text_filter(self, text):
        self._rebuild_brand_list(text)

    @staticmethod
    def _current_data(list_widget):
        it = list_widget.currentItem()
        return it.data(Qt.UserRole) if it else ""

    def _on_side_filter_changed(self, *_args):
        # 初始化填充列表期间不触发搜索
        if not hasattr(self, "_last_params"):
            return
        self._do_search()

    # ══════════════════════════════════════════
    #  搜索 + 分页
    # ══════════════════════════════════════════
    def _collect_params(self):
        """收集当前筛选条件（搜索与翻页共用）。"""
        return {
            "query": self.search_input.text().strip(),
            "brand": self._current_data(self.brand_list) or "",
            "category": self._current_data(self.category_list) or "",
            "media_type": self._current_data(self.type_list) or "",
        }

    def _do_search(self):
        params = self._collect_params()
        self._last_params = params
        self._page_size = self.spin_limit.value()
        self._offset = 0  # 新搜索回到第一页
        self._run_search()

    def _run_search(self):
        """用 _last_params + _offset/_page_size 执行一次检索。"""
        if not self._last_params:
            return
        p = self._last_params
        self.btn_search.setEnabled(False)
        self.lbl_stat.setText("加载中...")
        self.grid.clear()
        self._item_by_mid.clear()
        self._thumb_queue.clear()

        w = self.track_worker(_SearchWorker(
            query=p["query"], brand=p["brand"], category=p["category"],
            media_type=p["media_type"], limit=self._page_size, offset=self._offset))
        w.finished.connect(self._on_search_done)
        w.error.connect(lambda m: self._on_search_error(m))
        w.start()

    def _on_search_done(self, results, total):
        self.btn_search.setEnabled(True)
        self._results = results
        self._total = total
        self._fill_grid(results)
        self._update_page_label()

    def _on_search_error(self, msg):
        self.btn_search.setEnabled(True)
        friendly = msg
        if "Connection" in msg or "timed out" in msg or "Max retries" in msg:
            friendly = "无法连接服务端，请检查服务端是否在线"
        self.lbl_stat.setText(f"❌ {friendly}")
        self.grid.clear()
        self._total = 0
        self._update_page_label()

    def _update_page_label(self):
        page_size = self._page_size or 1
        cur_page = (self._offset // page_size) + 1 if self._total > 0 else 0
        total_pages = max(1, (self._total + page_size - 1) // page_size) if self._total > 0 else 0
        self.lbl_page.setText(f"第 {cur_page} / {total_pages} 页")
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(self._offset + self._page_size < self._total)
        self.lbl_stat.setText(f"共 {self._total} 条结果")

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

    # ══════════════════════════════════════════
    #  缩略图网格
    # ══════════════════════════════════════════
    def _fill_grid(self, rows):
        """填充缩略图网格：图片异步加载缩略图，视频用占位图标。"""
        self.grid.clear()
        self._item_by_mid.clear()
        self._thumb_queue.clear()
        self._active_thumb_count = 0

        to_load = []
        for item in rows:
            mid = str(item.get("id") or item.get("material_id") or "")
            fname = item.get("filename", "") or "未命名"
            mtype = (item.get("media_type") or "").lower()
            brand = item.get("brand") or "—"
            model = item.get("model") or "—"
            category = item.get("product") or item.get("category") or "—"
            fsize = item.get("file_size", 0)
            size_str = f"{fsize / 1048576:.1f}MB" if fsize else "—"
            score = item.get("score")

            # tooltip：完整信息
            type_name = {"video": "视频", "audio": "音频", "image": "图片"}.get(mtype, mtype)
            tip = (f"📁 {fname}\n品牌: {brand}\n型号: {model}\n"
                   f"分类: {category}\n类型: {type_name}\n大小: {size_str}")
            if score is not None:
                tip += f"\n相关度: {float(score):.3f}"

            lw_item = QListWidgetItem()
            lw_item.setText(fname if len(fname) <= 18 else fname[:17] + "…")
            lw_item.setToolTip(tip)
            lw_item.setForeground(QColor("#d1d5db"))
            lw_item.setData(Qt.UserRole, {"mid": mid, "media_type": mtype, "item": item})

            if mtype == "audio":
                lw_item.setIcon(self._pm_audio)
            elif mid and mid in self._thumb_cache:
                lw_item.setIcon(self._thumb_cache[mid])
            else:
                # 图片/视频：先占位，异步加载缩略图（服务端为视频生成首帧图）
                lw_item.setIcon(self._pm_video if mtype == "video" else self._pm_placeholder)
                if mid:
                    to_load.append(mid)

            self.grid.addItem(lw_item)
            if mid:
                self._item_by_mid[mid] = lw_item

        # 排队异步加载未命中的缩略图（并发节流）
        self._thumb_queue = list(to_load)
        self._drain_thumb_queue()

    def _drain_thumb_queue(self):
        """按并发上限从队列启动缩略图 worker。"""
        while self._active_thumb_count < _MAX_THUMB_WORKERS and self._thumb_queue:
            mid = self._thumb_queue.pop(0)
            # 防御：已缓存或 item 已不在（翻页清空）则跳过
            if mid in self._thumb_cache or mid not in self._item_by_mid:
                continue
            self._active_thumb_count += 1
            w = self.track_worker(_ThumbWorker(mid))
            w.finished.connect(self._on_thumb_done)
            w.error.connect(lambda _msg: self._on_thumb_done("", b""))  # 失败也要恢复计数+排空
            w.start()

    def _on_thumb_done(self, mid, data):
        self._active_thumb_count -= 1
        mid = str(mid)
        pm = QPixmap()
        if data and pm.loadFromData(data) and not pm.isNull():
            # 缩放到图标尺寸（保持比例）
            pm = pm.scaled(_THUMB_ICON_SIZE.width(), _THUMB_ICON_SIZE.height(),
                           Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            # 居中裁剪到正方形，避免 IconMode 下拉伸变形
            if pm.width() != _THUMB_ICON_SIZE.width() or pm.height() != _THUMB_ICON_SIZE.height():
                cropped = QPixmap(_THUMB_ICON_SIZE)
                cropped.fill(QColor("#16161f"))
                p = QPainter(cropped)
                x = (_THUMB_ICON_SIZE.width() - pm.width()) // 2
                y = (_THUMB_ICON_SIZE.height() - pm.height()) // 2
                p.drawPixmap(x, y, pm)
                p.end()
                pm = cropped
            self._thumb_cache[mid] = pm
            item = self._item_by_mid.get(mid)
            if item is not None:
                item.setIcon(pm)
        # 继续排空队列
        self._drain_thumb_queue()

    # ══════════════════════════════════════════
    #  交互：双击预览 / 复制地址
    # ══════════════════════════════════════════
    def _selected_mid(self):
        item = self.grid.currentItem()
        if not item:
            return None, None
        d = item.data(Qt.UserRole) or {}
        return d.get("mid"), d.get("media_type")

    def _copy_selected_url(self):
        mid, _ = self._selected_mid()
        if not mid:
            self.lbl_stat.setText("⚠ 请先选中一个素材")
            return
        url = _serve_url(mid)
        QGuiApplication.clipboard().setText(url)
        self.lbl_stat.setText(f"已复制地址: {url}")

    def _on_item_double_clicked(self, item):
        """双击卡片：图片弹大图预览，视频提示用地址打开。"""
        d = item.data(Qt.UserRole) or {}
        mid = d.get("mid")
        mtype = (d.get("media_type") or "").lower()
        if not mid:
            return
        if mtype == "video":
            dlg = VideoPreviewDialog(_serve_url(mid), item.text(), self.parent_widget)
            dlg.exec()
            return
        # 图片：异步加载原图并弹大图预览
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(f"预览 - {item.text()}")
        dlg.setMinimumSize(500, 500)
        dlg.resize(720, 720)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel("加载中…")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("background:#000;color:#888;")
        lay.addWidget(lbl, 1)

        def on_loaded(_mid, data):
            if not data:
                lbl.setText("加载失败")
                return
            pm = QPixmap()
            if pm.loadFromData(data) and not pm.isNull():
                sc = pm.scaled(lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(sc)

        w = self.track_worker(_ThumbWorker(mid))
        w.finished.connect(on_loaded)
        w.start()
        dlg.exec()
