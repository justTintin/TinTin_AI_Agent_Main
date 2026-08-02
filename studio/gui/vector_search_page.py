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
    QSpinBox, QDialog, QFrame, QSplitter, QWidget, QSlider, QTextEdit,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QUrl, QRect
from PySide6.QtGui import QGuiApplication, QPixmap, QPainter, QColor, QPen, QCursor
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
    """内置视频播放器：通过 /material/serve 流式播放服务端素材（支持 Range），右侧反推提示词面板。"""

    def __init__(self, url, title="", material_id="", media_type="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"▶ 视频预览 - {title}")
        self.resize(1120, 620)
        self.setObjectName("videoPreviewDialog")

        root_lay = QHBoxLayout(self)
        root_lay.setContentsMargins(10, 10, 10, 10)
        root_lay.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(8)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background:#000; border-radius:6px;")
        left.addWidget(self.video_widget, 1)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        left.addWidget(self.slider)

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
        left.addLayout(ctrl)

        root_lay.addLayout(left, 1)
        self.prompt_panel = PromptReversePanel(material_id, media_type)
        root_lay.addWidget(self.prompt_panel, 0)

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
                # 浏览模式：服务端 /material/list 用 page/size 分页（limit/offset 无效）
                params = {"size": self.limit,
                          "page": (self.offset // self.limit) + 1 if self.limit else 1}
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


class _FullImageWorker(BaseWorker):
    """原图加载（/material/serve）：预览时用原图，确保清晰度。"""
    finished = Signal(str, bytes)  # material_id, image_bytes

    def __init__(self, material_id):
        super().__init__()
        self.material_id = str(material_id)

    def do_work(self):
        try:
            resp = http_get(_serve_url(self.material_id), timeout=30)
            if resp.status_code == 200 and resp.content:
                self.finished.emit(self.material_id, resp.content)
        except Exception:
            pass


class _PromptWorker(BaseWorker):
    """服务端反推提示词：POST /prompt/image 或 /prompt/video（multipart material_id）。"""
    finished = Signal(str, str, str)  # 正向提示词, 负向提示词, 错误信息

    def __init__(self, material_id, media_type):
        super().__init__()
        self.material_id = str(material_id)
        self.media_type = (media_type or "image").lower()

    def do_work(self):
        endpoint = "video" if self.media_type == "video" else "image"
        url = f"{_get_server_url()}/prompt/{endpoint}"
        try:
            resp = http_post(url, files={"material_id": (None, self.material_id)}, timeout=180)
            if resp.status_code != 200:
                self.finished.emit("", "", f"服务端返回 {resp.status_code}")
                return
            data = resp.json() or {}
            prompt = (data.get("prompt") or "").strip()
            neg = (data.get("negative_prompt") or "").strip()
            self.finished.emit(prompt, neg, "")
        except Exception as e:
            self.finished.emit("", "", str(e))


class PromptReversePanel(QFrame):
    """预览对话框右侧：反推按钮在上，正/负向提示词分开显示与复制。"""

    def __init__(self, material_id, media_type, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(360)
        self._mid = material_id
        self._mtype = (media_type or "image").lower()
        self._worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        title = QLabel("🤖 反推提示词")
        title.setObjectName("section_header")
        lay.addWidget(title)

        # 反推按钮放在提示词文本框上方
        self.btn_reverse = QPushButton("🔮 反推提示词")
        self.btn_reverse.setObjectName("primary_button")
        self.btn_reverse.clicked.connect(self._reverse_prompt)
        lay.addWidget(self.btn_reverse)

        # 正向提示词
        row_pos = QHBoxLayout()
        lbl_pos = QLabel("正向提示词")
        lbl_pos.setObjectName("muted_text")
        row_pos.addWidget(lbl_pos)
        row_pos.addStretch(1)
        self.btn_copy_pos = QPushButton("📋 复制正向")
        self.btn_copy_pos.setObjectName("secondary_button")
        self.btn_copy_pos.clicked.connect(self._copy_positive)
        row_pos.addWidget(self.btn_copy_pos)
        lay.addLayout(row_pos)

        self.txt_prompt = QTextEdit()
        self.txt_prompt.setPlaceholderText("点击「反推提示词」生成正向提示词…")
        self.txt_prompt.setAcceptRichText(False)
        self.txt_prompt.setMinimumHeight(110)
        lay.addWidget(self.txt_prompt, 2)

        # 负向提示词
        row_neg = QHBoxLayout()
        lbl_neg = QLabel("负向提示词")
        lbl_neg.setObjectName("muted_text")
        row_neg.addWidget(lbl_neg)
        row_neg.addStretch(1)
        self.btn_copy_neg = QPushButton("📋 复制负向")
        self.btn_copy_neg.setObjectName("secondary_button")
        self.btn_copy_neg.clicked.connect(self._copy_negative)
        row_neg.addWidget(self.btn_copy_neg)
        lay.addLayout(row_neg)

        self.txt_negative = QTextEdit()
        self.txt_negative.setPlaceholderText("负向提示词（可为空）…")
        self.txt_negative.setAcceptRichText(False)
        self.txt_negative.setMinimumHeight(80)
        lay.addWidget(self.txt_negative, 1)

    def _reverse_prompt(self):
        if not self._mid:
            self.txt_prompt.setPlainText("⚠ 缺少素材ID")
            return
        self.btn_reverse.setEnabled(False)
        self.txt_prompt.setPlainText("⏳ 正在反推提示词…")
        self.txt_negative.clear()
        self._worker = _PromptWorker(self._mid, self._mtype)
        self._worker.finished.connect(self._on_prompt_done)
        self._worker.start()

    def _on_prompt_done(self, prompt, neg, err):
        self.btn_reverse.setEnabled(True)
        if err:
            self.txt_prompt.setPlainText(f"❌ 反推失败：{err}")
            self.txt_negative.clear()
            return
        self.txt_prompt.setPlainText(prompt)
        self.txt_negative.setPlainText(neg)

    def _copy_positive(self):
        QGuiApplication.clipboard().setText(self.txt_prompt.toPlainText())

    def _copy_negative(self):
        QGuiApplication.clipboard().setText(self.txt_negative.toPlainText())


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
        self.grid.setSelectionMode(QAbstractItemView.NoSelection)
        self.grid.setUniformItemSizes(True)
        self.grid.setStyleSheet("QListWidget { background: #16161f; border: 1px solid #333; border-radius: 4px; }"
                                " QListWidget::item { background: #1c1c24; border-radius: 6px; }"
                                " QListWidget::item:selected { background: #2a3340; border: 1px solid #2ecc71; }")
        self.grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.grid.itemClicked.connect(self._on_item_clicked)
        right_lay.addWidget(self.grid, 1)
        self._selected_mids = set()
        self._last_clicked_mid = None

        # 选择工具栏：全选/取消全选（仅对当前页生效）
        sel_row = QHBoxLayout()
        btn_sel_all = QPushButton("☑ 全选本页")
        btn_sel_all.setObjectName("secondary_button")
        btn_sel_all.setFixedWidth(110)
        btn_sel_all.clicked.connect(self._select_all_page)
        sel_row.addWidget(btn_sel_all)
        btn_sel_none = QPushButton("☐ 取消全选")
        btn_sel_none.setObjectName("secondary_button")
        btn_sel_none.setFixedWidth(110)
        btn_sel_none.clicked.connect(self._clear_all_page)
        sel_row.addWidget(btn_sel_none)
        self.lbl_sel_count = QLabel("已选 0 项")
        self.lbl_sel_count.setObjectName("muted_text")
        sel_row.addWidget(self.lbl_sel_count, 1)
        sel_row.addStretch()
        self.btn_copy_url = QPushButton("🚀 一键成片")
        self.btn_copy_url.setObjectName("primary_button")
        self.btn_copy_url.setToolTip("把选中的素材（图片/视频混合可多选）作为成片素材来源，跳转到「一键成片」自动填充。")
        self.btn_copy_url.clicked.connect(self._send_to_compile)
        sel_row.addWidget(self.btn_copy_url)
        self.btn_montage = QPushButton("🎬 智能混剪")
        self.btn_montage.setObjectName("primary_button")
        self.btn_montage.setToolTip("把选中的视频素材发送到「智能混剪」进行分镜/拼接（素材需在本地/NAS 可访问）。")
        self.btn_montage.clicked.connect(self._send_to_montage)
        sel_row.addWidget(self.btn_montage)
        right_lay.addLayout(sel_row)

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
        self.lbl_stat = QLabel("")
        self.lbl_stat.setObjectName("muted_text")
        page_row.addWidget(self.lbl_stat)
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
        self._active_thumb_count = 0
        self._selected_mids = set()
        self._last_clicked_mid = None      # 当前在途缩略图 worker 数
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

            self._apply_icon(mid, lw_item)
            if mtype != "audio" and mid and mid not in self._thumb_cache:
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
                self._apply_icon(mid, item)
        # 继续排空队列
        self._drain_thumb_queue()

    # ══════════════════════════════════════════
    #  交互：双击预览 / 复制地址
    # ══════════════════════════════════════════
    def _selected_mid(self):
        item = self.grid.currentItem()
        if not item and getattr(self, "_last_clicked_mid", None):
            item = self._item_by_mid.get(self._last_clicked_mid)
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

    def _build_selected_materials(self):
        """收集当前选中的素材为统一 dict 列表；无有效素材返回 None。"""
        items = self._selected_items()
        if not items:
            self.lbl_stat.setText("⚠ 请先在缩略图右上角方框选择素材")
            return None
        materials = []
        for it in items:
            d = it.data(Qt.UserRole) or {}
            mid = d.get("mid")
            raw = d.get("item") or {}
            if not mid:
                continue
            mtype = (d.get("media_type") or raw.get("media_type") or "image").lower()
            materials.append({
                "material_id": str(mid),
                "filename": raw.get("filename") or it.text() or str(mid),
                "media_type": mtype,
                "path": raw.get("path") or "",
                "url": _serve_url(mid),
                # 产品信息（可能为空，用于一键成片自动匹配产品）
                "brand": raw.get("brand") or "",
                "model": raw.get("model") or raw.get("product") or "",
                "product": raw.get("product") or raw.get("category") or "",
                "category": raw.get("category") or "",
            })
        if not materials:
            self.lbl_stat.setText("⚠ 未选择到有效素材")
            return None
        return materials

    def _send_to_compile(self):
        """把选中素材发送到「一键成片」（支持多个，图片+视频混合）。"""
        materials = self._build_selected_materials()
        if not materials:
            return
        mw = getattr(self, "main_window", None)
        if mw is None:
            self.lbl_stat.setText("❌ 无法访问主窗口")
            return
        # 切换到一键成片页（第 34 页）并填充素材列表
        try:
            mw.switch_page(34)
            tool = getattr(mw, "compile_video_tool", None)
            if tool is None:
                # 恢复当前页面
                mw.switch_page(39)
                self.lbl_stat.setText("❌ 一键成片页未加载")
                return
            tool.import_materials(materials)
        except Exception as e:
            self.lbl_stat.setText(f"❌ 跳转失败: {e}")

    def _send_to_montage(self):
        """把选中的视频素材发送到「智能混剪」（支持多选，需本地/NAS 可访问路径）。"""
        materials = self._build_selected_materials()
        if not materials:
            return
        mw = getattr(self, "main_window", None)
        if mw is None:
            self.lbl_stat.setText("❌ 无法访问主窗口")
            return
        try:
            mw.switch_page(15)
            tool = getattr(mw, "video_montage_tool", None)
            if tool is None:
                mw.switch_page(39)
                self.lbl_stat.setText("❌ 智能混剪页未加载")
                return
            tool.set_external_materials(materials)
        except Exception as e:
            self.lbl_stat.setText(f"❌ 跳转失败: {e}")

    def _on_item_double_clicked(self, item):
        """双击卡片：图片弹大图预览（右侧反推提示词），视频弹播放器预览。"""
        d = item.data(Qt.UserRole) or {}
        mid = d.get("mid")
        mtype = (d.get("media_type") or "").lower()
        if not mid:
            return
        if mtype == "video":
            dlg = VideoPreviewDialog(_serve_url(mid), item.text(), mid, mtype, self.parent_widget)
            dlg.exec()
            return
        # 图片：异步加载原图并弹大图预览（左图右提示词面板）
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(f"预览 - {item.text()}")
        dlg.setMinimumSize(900, 560)
        dlg.resize(1120, 680)
        root_lay = QHBoxLayout(dlg)
        root_lay.setContentsMargins(8, 8, 8, 8)
        root_lay.setSpacing(8)

        img_area = QVBoxLayout()
        lbl = QLabel("加载中…")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("background:#000;color:#888;")
        img_area.addWidget(lbl, 1)
        root_lay.addLayout(img_area, 1)

        panel = PromptReversePanel(mid, mtype)
        root_lay.addWidget(panel, 0)

        def on_loaded(_mid, data):
            if not data:
                lbl.setText("加载失败")
                return
            pm = QPixmap()
            if pm.loadFromData(data) and not pm.isNull():
                sc = pm.scaled(lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(sc)

        w = self.track_worker(_FullImageWorker(mid))
        w.finished.connect(on_loaded)
        w.start()
        dlg.exec()

    # ── 本页多选（全选/取消全选，仅对当前页生效）─────────────────────
    # ── 本页多选（相册式：右上角角标，单击切换）────────────────────────
    @staticmethod
    def _draw_corner_badge(base_pm, checked):
        """在缩略图右上角绘制选择方框复选框（未选=空方框，选中=绿底+白勾）。"""
        pm = QPixmap(base_pm)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        box = 22
        x = pm.width() - box - 6
        y = 6
        rect = QRect(x, y, box, box)
        if checked:
            p.setBrush(QColor("#2ecc71"))
            p.setPen(QPen(QColor("white"), 1.6))
            p.drawRoundedRect(rect, 4, 4)
            pen = QPen(QColor("white"), 2.6)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(x + 5, y + box * 0.55, x + box * 0.42, y + box * 0.82)
            p.drawLine(x + box * 0.42, y + box * 0.82, x + box * 0.78, y + box * 0.22)
        else:
            p.setBrush(QColor(15, 15, 20, 190))
            p.setPen(QPen(QColor("#c3c6d2"), 1.4))
            p.drawRoundedRect(rect, 4, 4)
        p.end()
        return pm

    def _apply_icon(self, mid, lw_item):
        """按当前选择状态设置缩略图（选中时叠加右上角角标）。"""
        if mid and mid in self._thumb_cache:
            base = self._thumb_cache[mid]
        else:
            meta = (lw_item.data(Qt.UserRole) or {}) if lw_item is not None else {}
            mtype = (meta.get("media_type") or "").lower()
            base = self._pm_audio if mtype == "audio" else (self._pm_video if mtype == "video" else self._pm_placeholder)
        if mid:
            base = self._draw_corner_badge(base, mid in self._selected_mids)
        lw_item.setIcon(base)

    def _on_item_clicked(self, item):
        """单击：仅点击右上角选择方框区域才切换选择；其余单击仅记录当前项（双击预览）。"""
        d = item.data(Qt.UserRole) or {}
        mid = d.get("mid")
        if not mid:
            return
        self._last_clicked_mid = mid
        # 判断点击是否落在右上角选择区域（图标右上角 ~40x40）
        vp_pos = self.grid.viewport().mapFromGlobal(QCursor.pos())
        item_rect = self.grid.visualItemRect(item)
        badge_zone = QRect(item_rect.right() - 42, item_rect.top() + 2, 40, 40)
        if not badge_zone.contains(vp_pos):
            return
        if mid in self._selected_mids:
            self._selected_mids.discard(mid)
        else:
            self._selected_mids.add(mid)
        self._apply_icon(mid, item)
        self._refresh_selected_label()

    def _refresh_selected_label(self):
        self.lbl_sel_count.setText(f"已选 {len(self._selected_mids)} 项")

    def _select_all_page(self):
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            mid = (it.data(Qt.UserRole) or {}).get("mid")
            if mid:
                self._selected_mids.add(mid)
                self._apply_icon(mid, it)
        self._refresh_selected_label()

    def _clear_all_page(self):
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            mid = (it.data(Qt.UserRole) or {}).get("mid")
            if mid:
                self._selected_mids.discard(mid)
                self._apply_icon(mid, it)
        self._refresh_selected_label()

    def _selected_items(self):
        """返回当前页右上角角标选中的 item 列表。"""
        out = []
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            mid = (it.data(Qt.UserRole) or {}).get("mid")
            if mid and mid in self._selected_mids:
                out.append(it)
        return out

    def _on_item_changed(self, _item):
        self._refresh_selected_label()
