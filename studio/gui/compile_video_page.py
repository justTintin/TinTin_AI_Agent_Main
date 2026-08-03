# -*- coding: utf-8 -*-
"""
一键成片页。

整体布局（上左右下三段式）：
    ┌─ heading ────────────────────────────────────────────┐
    ├─ 上段（QSplitter 横向）                              │
    │   左：产品选择（必选，任务起点）+ 性能参数/核心卖点      │
    │   右：可选设置（字幕文案/素材目录/配音/TTS/开场/封面） │
    ├─ 设置段（QGroupBox）：视频条数/总时长/比例/平台 + 执行  │
    └─ 输出段：结果列表 + 执行日志 + 进度条                  │

产品库读取用 ProductLibraryManager；远程素材匹配用 /material/search；
重型剪辑仍走「智能混剪」；本页面向"快速出片"。
逻辑见 utils/video_compiler.py。
"""
import os
import json
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFrame,
    QComboBox, QDoubleSpinBox, QSpinBox, QFileDialog, QProgressBar, QCheckBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTextBrowser, QWidget, QTabWidget, QButtonGroup,
    QRadioButton, QDialog, QDialogButtonBox, QFormLayout, QTimeEdit,
    QListWidget, QListWidgetItem, QScrollArea,
)
from PySide6.QtCore import Signal, Qt, QTimer

from gui.base_page import BasePage
from gui.montage.beat_montage_controller import BeatMontageController
from gui.montage.step_beat_view import StepBeatView
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button, table_action_button
from utils.logger_utils import log
from utils.video_compiler import compile_video, collect_images, RATIO_SIZES
from utils.voxcpm_client import synthesize_tts
from utils.video_prediction_manager import PLATFORMS, VideoPredictionManager
from utils.product_library_manager import ProductLibraryManager
from gui.searchable_combo import SearchableComboBox
from gui.mg_template_utils import (
    _param_meta, create_value_widget,
    widget_value, set_widget_value, color_row, merge_templates,
    fill_template_list,
)
from utils.template_server_client import list_templates as list_video_templates
from config.paths import FINAL_OUTPUT_DIR, KNOWLEDGE_MEDIA_DIR, TMP_DIR


# ─── 远程素材服务地址（与 vector_search_page 一致） ─────────────────────────
from utils.file_dialog_utils import pick_directory, pick_file
def _get_server_url():
    try:
        import json
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            cfg = json.load(open(AI_CONFIG_FILE, "r", encoding="utf-8"))
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


class TTSWorker(BaseWorker):
    phase = Signal(str)
    done = Signal(str)

    def __init__(self, text, ref_wav, out_path):
        super().__init__()
        self.text = text; self.ref_wav = ref_wav; self.out_path = out_path

    def do_work(self):
        self.phase.emit("正在合成配音…")
        synthesize_tts(self.text, self.ref_wav, self.out_path)
        self.done.emit(self.out_path)


class MaterialMatchWorker(BaseWorker):
    """按产品 brand/model/category 调远程 /material/search，返回素材目录路径。
    成功 emit 一个目录字符串；失败 emit 空字符串。"""
    result_ready = Signal(str)
    log_line = Signal(str)

    def __init__(self, brand, model, category):
        super().__init__()
        self.brand = brand; self.model = model; self.category = category

    def do_work(self):
        from utils.http_client import http_post
        try:
            url = f"{_get_server_url()}/material/search"
            params = {"limit": 200, "offset": 0}
            if self.brand:
                params["brand"] = self.brand
            if self.category:
                params["category"] = self.category
            if self.model:
                params["model"] = self.model
            self.log_line.emit(f"🔎 远程匹配素材: brand={self.brand!r} category={self.category!r}")
            resp = http_post(url, json=params, timeout=15)
            if resp.status_code != 200:
                self.log_line.emit(f"⚠ 服务端返回 {resp.status_code}")
                self.result_ready.emit("")
                return
            results = resp.json().get("results") or resp.json().get("data") or []
            if not results:
                self.log_line.emit("⚠ 远程未匹配到任何素材")
                self.result_ready.emit("")
                return
            # 收集所有 path，取公共父目录作为素材目录
            paths = [r.get("path", "") for r in results if r.get("path")]
            paths = [p for p in paths if p]
            if not paths:
                self.log_line.emit("⚠ 匹配结果无可用 path 字段")
                self.result_ready.emit("")
                return
            common = os.path.commonpath(paths) if len(paths) > 1 else os.path.dirname(paths[0])
            # commonpath 可能指向文件，确保是目录：若指向文件则取其父
            if os.path.isfile(common):
                common = os.path.dirname(common)
            self.log_line.emit(f"✅ 匹配到 {len(paths)} 个素材，目录: {common}")
            self.result_ready.emit(common)
        except Exception as e:
            self.log_line.emit(f"⚠ 远程匹配失败: {e}")
            # 异常交由 BaseWorker.run() 统一 emit error；这里发空结果让 UI 回落
            self.result_ready.emit("")


class CompileVideoWorker(BaseWorker):
    """一键成片 Worker。支持一次生成 N 个独立成片。
    done 信号发射成片路径列表（list[str]）。"""
    phase = Signal(str)
    progress = Signal(int)          # 0-100
    log_line = Signal(str)
    done = Signal(list)

    def __init__(self, folder, out_dir, audio, cover, subtitle, ratio, per_dur,
                 count=1, total_dur=0.0, intro=""):
        super().__init__()
        self.folder = folder
        self.out_dir = out_dir
        self.audio = audio; self.cover = cover; self.subtitle = subtitle
        self.ratio = ratio; self.per_dur = per_dur
        self.count = max(1, int(count))
        self.total_dur = float(total_dur or 0.0)
        self.intro = intro

    def do_work(self):
        images = collect_images(self.folder)
        if not images:
            raise RuntimeError("素材目录里没有图片（支持 jpg/png/webp 等）。")

        # 总时长换算 per_dur（无配音时）：覆盖入参 per_dur
        per_dur = float(self.per_dur)
        has_audio = bool(self.audio and os.path.isfile(self.audio))
        if not has_audio and self.total_dur > 0:
            per_dur = max(0.8, self.total_dur / len(images))
            self.log_line.emit(f"📏 按总时长 {self.total_dur}s / {len(images)} 张 → 每张 {per_dur:.2f}s")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results = []

        if self.count == 1:
            out_path = os.path.join(self.out_dir, f"final_{timestamp}.mp4")
            self.phase.emit("正在生成成片…")
            self.progress.emit(20)
            self._compile_one(images, out_path, per_dur, has_audio)
            results.append(out_path)
            self.log_line.emit(f"✅ 成片: {os.path.basename(out_path)}")
        else:
            # N 个成片：把 images 分成 N 组（不足循环填充）
            groups = self._split_groups(images, self.count)
            total = self.count
            for i, group in enumerate(groups):
                out_path = os.path.join(self.out_dir, f"final_{timestamp}_{i + 1}.mp4")
                self.phase.emit(f"正在生成第 {i + 1}/{total} 个成片…")
                self.progress.emit(int(i / total * 100))
                try:
                    self._compile_one(group, out_path, per_dur, has_audio)
                    results.append(out_path)
                    self.log_line.emit(f"✅ [{i + 1}/{total}] {os.path.basename(out_path)}")
                except Exception as e:
                    self.log_line.emit(f"❌ [{i + 1}/{total}] 失败: {e}")
                    log.warning(f"成片 {i + 1} 失败: {e}")

        self.progress.emit(100)
        self.done.emit(results)

    def _compile_one(self, images, out_path, per_dur, has_audio):
        compile_video(images, out_path, audio=self.audio, cover=self.cover,
                      subtitle_text=self.subtitle, ratio=self.ratio, per_dur=per_dur,
                      intro=self.intro, progress=self.log_line.emit)

    @staticmethod
    def _split_groups(images, n):
        """把 images 尽量均分成 n 组；不足 n 时循环填充。"""
        if len(images) >= n:
            # 均分
            k, m = divmod(len(images), n)
            groups = []
            start = 0
            for i in range(n):
                size = k + (1 if i < m else 0)
                groups.append(images[start:start + size])
                start += size
            return groups
        else:
            # 不足：循环填充到 n 组
            return [images[i % len(images):i % len(images) + 1] if not images[i % len(images):]
                    else [images[i % len(images)]] for i in range(n)] if images else [[] for _ in range(n)]


# 成片模板兜底（type=video，独立于动效模板 type=motion）
VIDEO_FALLBACK_TEMPLATES = [
    {
        "id": "ecom_15s",
        "name": "电商带货-15s",
        "type": "video",
        "category": "ecommerce",
        "description": "电商带货 15 秒成片：钩子→卖点→细节→CTA（素材服务端按主题匹配）",
        "is_builtin": True,
        "params": [
            {"name": "topic", "type": "string", "default": "", "label": "主题"},
            {"name": "bgm", "type": "string", "default": "欢快", "label": "BGM风格"},
        ],
        "effects": {"template": "ecom_15s"},
    },
    {
        "id": "brand_30s",
        "name": "品牌故事-30s",
        "type": "video",
        "category": "brand",
        "description": "品牌故事 30 秒成片：标识→故事→亮点→价值→口号",
        "is_builtin": True,
        "params": [
            {"name": "topic", "type": "string", "default": "", "label": "主题"},
            {"name": "bgm", "type": "string", "default": "大气", "label": "BGM风格"},
        ],
        "effects": {"template": "brand_30s"},
    },
]


class VideoTemplateLoadWorker(BaseWorker):
    """异步从统一接口 GET /templates?type=video 拉取成片模板（区别于动效 /mg/*）。"""
    finished = Signal(list)
    phase = Signal(str)

    def do_work(self):
        self.phase.emit("正在加载成片模板…")
        templates = list_video_templates(category="video", timeout=8)
        self.finished.emit(templates)


class TemplatePreviewWorker(BaseWorker):
    """渲染成片模板并下载预览视频（/templates/render → result → download）。"""
    progress = Signal(int)
    phase = Signal(str)
    finished = Signal(str)   # 本地 mp4 路径

    def __init__(self, template_id, params, ratio):
        super().__init__()
        self.template_id = template_id
        self.params = params or {}
        self.ratio = ratio

    def do_work(self):
        from utils.template_server_client import (
            render as _render, render_result as _result, render_download as _download,
        )
        self.phase.emit("正在提交预览渲染…")
        task_id = _render(self.template_id, params=self.params, ratio=self.ratio)
        if not task_id:
            raise RuntimeError("预览渲染提交失败，请检查服务端连接。")
        deadline = time.time() + 900
        while time.time() < deadline:
            time.sleep(2)
            st = _result(task_id)
            status = (st.get("status") or "").lower()
            try:
                prog = int(st.get("progress") or 0)
            except Exception:
                prog = 0
            self.progress.emit(prog)
            self.phase.emit(f"预览渲染中… {prog}%")
            if status in ("completed", "done", "success"):
                resp = _download(task_id)
                if resp is None:
                    raise RuntimeError("预览渲染完成但下载失败。")
                out = os.path.join(TMP_DIR, f"tpl_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "wb") as f:
                    f.write(resp.content)
                self.finished.emit(out)
                return
            if status in ("failed", "error"):
                raise RuntimeError(f"预览渲染失败：{st.get('error') or '未知错误'}")
        raise RuntimeError("预览渲染超时（15 分钟）。")


class ScriptListLoader(BaseWorker):
    """从服务端 GET /api/storyboard/scripts 拉取分镜脚本列表摘要。"""
    finished = Signal(list)

    def do_work(self):
        from utils.http_client import http_get
        base = _get_server_url()
        if not base:
            raise RuntimeError("未配置服务端地址")
        r = http_get(f"{base}/api/storyboard/scripts",
                     params={"page": 1, "page_size": 100}, timeout=15)
        if r.status_code == 200:
            items = (r.json() or {}).get("items") or []
            self.finished.emit(items)
            return
        raise RuntimeError(f"脚本列表接口返回 HTTP {r.status_code}")


class ScriptDetailLoader(BaseWorker):
    """从服务端 GET /api/storyboard/scripts/{id} 拉取完整分镜脚本。"""
    finished = Signal(dict)

    def __init__(self, script_id):
        super().__init__()
        self.script_id = script_id

    def do_work(self):
        from utils.http_client import http_get
        base = _get_server_url()
        if not base:
            raise RuntimeError("未配置服务端地址")
        r = http_get(f"{base}/api/storyboard/scripts/{self.script_id}", timeout=15)
        if r.status_code == 200:
            self.finished.emit(r.json() or {})
            return
        raise RuntimeError(f"脚本详情接口返回 HTTP {r.status_code}")


class CompileVideoPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self._product_mgr = ProductLibraryManager()
        self._last_results = []          # 最近一次成片路径列表
        self._self_check_data = None
        self._materials = []
        self._templates = []
        self._current_template = None
        self._template_form_widgets = {}
        self._features_text = ""
        self._selling_text = ""
             # 从素材检索带过来的素材列表

    # ════════════════════════════════════════════════════════════════════════
    #  setup：构建界面（顶层 QTabWidget：产品成片 + 脚本成片）
    # ════════════════════════════════════════════════════════════════════════
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # 顶层 tab：产品成片（选产品）+ 脚本成片（选分镜脚本）
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: none; } "
            "QTabBar::tab { padding: 8px 18px; font-size: 13px; } "
            "QTabBar::tab:selected { color: #3b82f6; font-weight: bold; }")
        root.addWidget(self.tabs, 1)

        # tab1：产品成片（原有完整界面）
        tab_product = QWidget()
        self._setup_product_tab(tab_product)
        self.tabs.addTab(tab_product, "📦 产品成片")

        # tab2：脚本成片（选分镜脚本提交服务端）
        tab_script = QWidget()
        self._setup_script_tab(tab_script)
        self.tabs.addTab(tab_script, "📜 脚本成片")

        # tab3：卡点成片（音乐卡点 + 服务端逐段生成视频）
        tab_beat = QWidget()
        self._setup_beat_tab(tab_beat)
        self.tabs.addTab(tab_beat, "🎵 卡点成片")

    # ════════════════════════════════════════════════════════════
    #  卡点成片 tab（独立控制器 + StepBeatView）
    # ════════════════════════════════════════════════════════════
    def _setup_beat_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(12)

        # 自包含控制器（充当 StepBeatView 的 main_page 角色）
        self.beat_controller = BeatMontageController(self.parent_widget, self.main_window)
        beat_view = StepBeatView(self.beat_controller)
        self.beat_controller.step_beat = beat_view
        root.addWidget(beat_view, 1)

    # ════════════════════════════════════════════════════════════════════════
    #  产品成片 tab（原有界面，整体挂到 container）
    # ════════════════════════════════════════════════════════════════════════
    def _setup_product_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(12)

        sub = QLabel("选择产品（必选，任务起点）→ 可选设置/自动匹配素材 → 设置条数与时长 → 开始执行。复杂剪辑请用「智能混剪」。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 上段：左右分割（左=产品，右=可选设置）──────────────────────────
        top_splitter = QSplitter(Qt.Horizontal)

        # 左：产品选择 + 性能/卖点
        left_card = QFrame(); left_card.setObjectName("card")
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(16, 14, 16, 14); left_lay.setSpacing(10)

        left_title = QLabel("📦 产品选择（必选）"); left_title.setStyleSheet("font-weight:bold;")
        left_lay.addWidget(left_title)

        prod_row = QHBoxLayout()
        self.combo_product = SearchableComboBox(placeholder="输入品牌/型号搜索产品…")
        prod_row.addWidget(self.combo_product, 1)
        self.btn_reload_product = mdi_button("刷新", "refresh")
        self.btn_reload_product.setObjectName("secondary_button")
        self.btn_reload_product.clicked.connect(lambda: self._populate_products())
        prod_row.addWidget(self.btn_reload_product)
        # 卖点文案放在「刷新」后面（弹窗查看原始卖点/参数），不再单独占一行
        self.btn_show_selling = mdi_button("卖点文案", "clipboard")
        self.btn_show_selling.setObjectName("secondary_button")
        self.btn_show_selling.clicked.connect(self._show_selling_dialog)
        prod_row.addWidget(self.btn_show_selling)
        left_lay.addLayout(prod_row)

        # 模板库（成片模板，独立于动效模板；header 行内放 预览播放/刷新，不再单独占行）
        tmpl_header = QHBoxLayout()
        tmpl_header.addWidget(QLabel("🎬 成片模板"))
        tmpl_header.addStretch(1)
        self.btn_preview_play = mdi_button("预览播放", "play")
        self.btn_preview_play.setObjectName("secondary_button")
        self.btn_preview_play.setToolTip("渲染当前成片模板并预览播放")
        self.btn_preview_play.clicked.connect(self._preview_template)
        tmpl_header.addWidget(self.btn_preview_play)
        self.btn_refresh_templates = mdi_button("刷新", "refresh")
        self.btn_refresh_templates.setObjectName("secondary_button")
        self.btn_refresh_templates.clicked.connect(self._load_templates)
        tmpl_header.addWidget(self.btn_refresh_templates)
        left_lay.addLayout(tmpl_header)
        self.list_templates = QListWidget()
        self.list_templates.currentItemChanged.connect(self._on_template_selected)
        self.list_templates.setMaximumHeight(170)
        left_lay.addWidget(self.list_templates)

        top_splitter.addWidget(left_card)

        # 右：可选设置
        right_card = QFrame(); right_card.setObjectName("card")
        right_lay = QVBoxLayout(right_card)
        right_lay.setContentsMargins(16, 14, 16, 14); right_lay.setSpacing(8)

        # 模板参数按内容分组为 Tab，避免全部堆在一个长布局里
        self.tabs_params = QTabWidget()

        # ── Tab1 素材：镜头素材目录 / 素材列表 ──
        tab_material = QWidget()
        lay_material = QVBoxLayout(tab_material)
        lay_material.setContentsMargins(8, 8, 8, 8); lay_material.setSpacing(8)
        self.in_folder = self._file_row(lay_material, "镜头素材目录（留空=按产品自动匹配）",
                                        self._browse_folder, folder=True,
                                        placeholder="留空则按产品自动从素材库匹配")
        mat_header = QHBoxLayout()
        mat_header.addWidget(QLabel("📁 素材列表（来自素材检索，可选）"))
        mat_header.addStretch(1)
        self.btn_clear_materials = mdi_button("清空", "delete")
        self.btn_clear_materials.setObjectName("secondary_button")
        self.btn_clear_materials.clicked.connect(self._clear_materials)
        mat_header.addWidget(self.btn_clear_materials)
        lay_material.addLayout(mat_header)
        self.material_list = QListWidget()
        self.material_list.setMaximumHeight(120)
        lay_material.addWidget(self.material_list)
        self.lbl_material_count = QLabel("已选 0 个素材（可在「素材检索」选择后点击「一键成片」带入）")
        self.lbl_material_count.setObjectName("muted_text")
        self.lbl_material_count.setWordWrap(True)
        lay_material.addWidget(self.lbl_material_count)
        lay_material.addStretch(1)
        self.tabs_params.addTab(tab_material, "素材")

        # ── Tab2 文案：字幕文案 / 配音文案 ──
        tab_copy = QWidget()
        lay_copy = QVBoxLayout(tab_copy)
        lay_copy.setContentsMargins(8, 8, 8, 8); lay_copy.setSpacing(8)
        lay_copy.addWidget(QLabel("字幕文案 / 配音文案(可选)"))
        self.in_subtitle = QTextEdit(); self.in_subtitle.setFixedHeight(90)
        self.in_subtitle.setPlaceholderText("粘贴文案；按句均匀分布为字幕，并可一键 TTS 配音。留空则不加。")
        lay_copy.addWidget(self.in_subtitle)
        lay_copy.addStretch(1)
        self.tabs_params.addTab(tab_copy, "文案")

        # ── Tab3 音频：配音音频 / TTS 音色 ──
        tab_audio = QWidget()
        lay_audio = QVBoxLayout(tab_audio)
        lay_audio.setContentsMargins(8, 8, 8, 8); lay_audio.setSpacing(8)
        self.in_audio = self._file_row(lay_audio, "配音音频(可选)", self._browse_audio,
                                       placeholder="wav/mp3/m4a，留空则无声")
        tts_row = QHBoxLayout()
        tts_row.addWidget(QLabel("TTS 音色"))
        self.combo_voice = SearchableComboBox(placeholder="输入音色名称搜索…")
        tts_row.addWidget(self.combo_voice, 1)
        self.btn_tts = mdi_button("用文案生成配音", "audio")
        self.btn_tts.setObjectName("secondary_button")
        self.btn_tts.clicked.connect(self._tts_generate)
        tts_row.addWidget(self.btn_tts)
        lay_audio.addLayout(tts_row)
        lay_audio.addStretch(1)
        self.tabs_params.addTab(tab_audio, "音频")

        # ── Tab4 开场封面：开场视频 + 封面 ──
        tab_cover = QWidget()
        lay_cover = QVBoxLayout(tab_cover)
        lay_cover.setContentsMargins(8, 8, 8, 8); lay_cover.setSpacing(8)
        self.in_intro = self._file_row(lay_cover, "开场视频(可选)", self._browse_intro,
                                       placeholder="片头开场视频，拼在最前面")
        intro_row = QHBoxLayout(); intro_row.addStretch()
        self.btn_mg_intro = mdi_button("用动态标题生成开场(MG)", "film")
        self.btn_mg_intro.setObjectName("secondary_button")
        self.btn_mg_intro.clicked.connect(self._gen_mg_intro)
        intro_row.addWidget(self.btn_mg_intro)
        lay_cover.addLayout(intro_row)
        self.in_cover = self._file_row(lay_cover, "封面(可选)", self._browse_cover,
                                       placeholder="片头封面图，显示 2 秒")
        lay_cover.addStretch(1)
        self.tabs_params.addTab(tab_cover, "开场封面")

        # ── Tab5 其它：模板自定义参数 ──
        tab_other = QWidget()
        lay_other = QVBoxLayout(tab_other)
        lay_other.setContentsMargins(8, 8, 8, 8); lay_other.setSpacing(8)
        self.template_params_group = QGroupBox("模板自定义参数")
        tpl_form_lay = QVBoxLayout(self.template_params_group)
        self.scroll_template_form = QScrollArea()
        self.scroll_template_form.setWidgetResizable(True)
        self.scroll_template_form.setFrameShape(QFrame.NoFrame)
        self.template_form_container = QWidget()
        self.template_form_layout = QFormLayout(self.template_form_container)
        self.template_form_layout.setSpacing(8)
        self.scroll_template_form.setWidget(self.template_form_container)
        tpl_form_lay.addWidget(self.scroll_template_form)
        lay_other.addWidget(self.template_params_group)
        lay_other.addStretch(1)
        self.tabs_params.addTab(tab_other, "其它")

        # 模板参数放在左侧「成片模板」下面
        tpl_title_row = QHBoxLayout()
        tpl_title_row.addWidget(QLabel("🎛 模板参数"))
        tpl_title_row.addStretch()
        self.btn_template_defaults = mdi_button("设置默认", "refresh")
        self.btn_template_defaults.setObjectName("secondary_button")
        self.btn_template_defaults.setToolTip("将模板参数恢复为默认值")
        self.btn_template_defaults.clicked.connect(self._set_template_defaults)
        self.btn_template_defaults.setEnabled(False)
        tpl_title_row.addWidget(self.btn_template_defaults)
        left_lay.addLayout(tpl_title_row)
        left_lay.addWidget(self.tabs_params, 1)
        self.template_params_group.setVisible(False)

        top_splitter.addWidget(right_card)
        # 左右比例 3:7（左=产品/模板/模板参数，右=设置/输出/日志）
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 7)
        top_splitter.setSizes([300, 700])
        root.addWidget(top_splitter, 2)

        # ── 设置段 ────────────────────────────────────────────────────────
        setting_group = QGroupBox("设置")
        s_lay = QVBoxLayout(setting_group); s_lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("变体数量"))
        self.spin_count = QSpinBox(); self.spin_count.setRange(1, 10); self.spin_count.setValue(5)
        self.spin_count.setToolTip("服务端生成 N 个变体（不同风格/节奏），用进化机制选最优的 1 个输出。\n数值越大选择空间越大但耗时越长。")
        row1.addWidget(self.spin_count)
        row1.addSpacing(12)
        row1.addWidget(QLabel("视频总时长"))
        self.spin_total_dur = QDoubleSpinBox()
        self.spin_total_dur.setRange(0.0, 600.0); self.spin_total_dur.setValue(0.0)
        self.spin_total_dur.setSuffix(" 秒")
        self.spin_total_dur.setToolTip("仅无配音时生效：按总时长/图片数计算每张时长。0=用「每张时长」。")
        row1.addWidget(self.spin_total_dur)
        row1.addSpacing(12)
        row1.addWidget(QLabel("每张时长(无配音时)"))
        self.spin_dur = QDoubleSpinBox(); self.spin_dur.setRange(0.5, 30.0); self.spin_dur.setValue(3.0)
        self.spin_dur.setSuffix(" 秒")
        row1.addWidget(self.spin_dur)
        row1.addSpacing(12)
        row1.addWidget(QLabel("比例"))
        self.combo_ratio = QComboBox(); self.combo_ratio.addItems(list(RATIO_SIZES.keys()))
        row1.addWidget(self.combo_ratio)
        row1.addStretch()
        s_lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_autocheck = QCheckBox("成片后自动视频评价预测")
        self.chk_autocheck.setChecked(True)
        row2.addWidget(self.chk_autocheck)
        row2.addWidget(QLabel("平台"))
        self.combo_predict_platform = QComboBox(); self.combo_predict_platform.addItems(PLATFORMS)
        self.combo_predict_platform.setFixedWidth(96)
        row2.addWidget(self.combo_predict_platform)
        row2.addStretch()
        self.btn_make = mdi_button("🚀 开始执行", "video"); self.btn_make.setObjectName("primary_button")
        self.btn_make.setFixedHeight(36)
        self.btn_make.clicked.connect(self._make)
        row2.addWidget(self.btn_make)
        self.btn_add_task = QPushButton("📌 添加为定时任务")
        self.btn_add_task.setFixedHeight(36)
        self.btn_add_task.setToolTip("把当前配置提交给服务端，由服务端定时执行（可在「定时任务」页监控状态）")
        self.btn_add_task.clicked.connect(self._add_scheduled_task)
        row2.addWidget(self.btn_add_task)
        s_lay.addLayout(row2)
        right_lay.addWidget(setting_group)

        # ── 输出段：结果列表 + 日志 + 进度条 ───────────────────────────────
        out_splitter = QSplitter(Qt.Horizontal)

        # 左：结果列表 + 进度条
        out_left = QWidget()
        ol_lay = QVBoxLayout(out_left); ol_lay.setContentsMargins(0, 0, 0, 0); ol_lay.setSpacing(6)
        ol_lay.addWidget(QLabel("🎞️ 输出结果"))
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["序号", "文件名", "状态", "操作"])
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.verticalHeader().setVisible(False)
        rh = self.result_table.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        rh.setSectionResizeMode(1, QHeaderView.Stretch)
        rh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        rh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        ol_lay.addWidget(self.result_table, 1)

        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        ol_lay.addWidget(self.progress_bar)
        self.stage_label = QLabel(""); self.stage_label.setObjectName("muted_text")
        ol_lay.addWidget(self.stage_label)
        out_splitter.addWidget(out_left)

        # 右：执行日志
        out_right = QWidget()
        or_lay = QVBoxLayout(out_right); or_lay.setContentsMargins(0, 0, 0, 0); or_lay.setSpacing(6)
        # 执行日志：默认折叠隐藏，点击标题展开/收起
        self.btn_toggle_log = QPushButton("📜 执行日志（点击展开）")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setObjectName("secondary_button")
        self.btn_toggle_log.clicked.connect(self._toggle_log_visible)
        or_lay.addWidget(self.btn_toggle_log)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background: #1a1a2e; color: #c8d6e5; font-size: 12px; border-radius: 6px;")
        self.log_box.setVisible(False)  # 默认折叠
        or_lay.addWidget(self.log_box, 1)
        out_splitter.addWidget(out_right)

        out_splitter.setStretchFactor(0, 1)
        out_splitter.setStretchFactor(1, 1)
        out_splitter.setSizes([420, 420])
        right_lay.addWidget(out_splitter, 1)

        # 评分预测状态行
        score_row = QHBoxLayout()
        self.score_label = QLabel("")
        self.score_label.setObjectName("muted_text"); self.score_label.setWordWrap(True)
        score_row.addWidget(self.score_label, 1)
        self.btn_detail = mdi_button("查看详情/建议", "right")
        self.btn_detail.setObjectName("secondary_button")
        self.btn_detail.clicked.connect(self._open_detail)
        self.btn_detail.setVisible(False)
        score_row.addWidget(self.btn_detail)
        root.addLayout(score_row)

        # 信号绑定
        self.combo_product.currentIndexChanged.connect(self._on_product_changed)

        # 初始化数据
        self._populate_products()
        self._populate_voices()
        self._load_templates()

    def _toggle_log_visible(self):
        """执行日志展开/收起。"""
        show = self.btn_toggle_log.isChecked()
        self.log_box.setVisible(show)
        self.btn_toggle_log.setText("📜 执行日志（点击折叠）" if show else "📜 执行日志（点击展开）")

    # ════════════════════════════════════════════════════════════════════════
    #  脚本成片 tab（选分镜脚本 → 提交服务端成片）
    # ════════════════════════════════════════════════════════════════════════
    def _setup_script_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(10)

        sub = QLabel("选择一个已保存的分镜脚本（含素材+文案），直接提交服务端成片。脚本在「分镜脚本」页保存为 JSON 格式生成。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 脚本选择行 ─────────────────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("选择脚本"))
        self.combo_script = SearchableComboBox(placeholder="输入脚本名称搜索…")
        self.combo_script.setMinimumWidth(360)
        self.combo_script.currentIndexChanged.connect(self._on_script_changed)
        sel_row.addWidget(self.combo_script, 1)
        self.btn_reload_script = QPushButton("刷新")
        self.btn_reload_script.setObjectName("secondary_button")
        self.btn_reload_script.clicked.connect(self._populate_scripts)
        sel_row.addWidget(self.btn_reload_script)
        root.addLayout(sel_row)

        # ── 脚本预览 ───────────────────────────────────────────────────────
        root.addWidget(QLabel("📋 脚本预览"))
        self.script_preview = QTextBrowser()
        self.script_preview.setOpenExternalLinks(False)
        self.script_preview.setMinimumHeight(220)
        self.script_preview.setPlaceholderText("选择上方脚本后，这里显示镜头表（镜号|时长|画面|文案|素材路径）")
        root.addWidget(self.script_preview, 1)

        # ── 设置行 ─────────────────────────────────────────────────────────
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("比例"))
        self.script_combo_ratio = QComboBox(); self.script_combo_ratio.addItems(list(RATIO_SIZES.keys()))
        opt_row.addWidget(self.script_combo_ratio)
        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("变体数量"))
        self.script_spin_count = QSpinBox(); self.script_spin_count.setRange(1, 10); self.script_spin_count.setValue(5)
        self.script_spin_count.setToolTip("服务端生成 N 个变体（不同风格/节奏），进化机制选最优 1 个输出")
        opt_row.addWidget(self.script_spin_count)
        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("平台"))
        self.script_combo_platform = QComboBox(); self.script_combo_platform.addItems(PLATFORMS)
        self.script_combo_platform.setFixedWidth(96)
        opt_row.addWidget(self.script_combo_platform)
        opt_row.addSpacing(12)
        self.script_chk_autocheck = QCheckBox("成片后评价预测")
        self.script_chk_autocheck.setChecked(True)
        opt_row.addWidget(self.script_chk_autocheck)
        opt_row.addStretch()
        root.addLayout(opt_row)

        # ── 执行按钮行 ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_script_make = mdi_button("🚀 开始执行", "video")
        self.btn_script_make.setObjectName("primary_button")
        self.btn_script_make.setFixedHeight(36)
        self.btn_script_make.clicked.connect(lambda: self._submit_script(immediate=True))
        btn_row.addWidget(self.btn_script_make)
        self.btn_script_add_task = QPushButton("📌 添加为定时任务")
        self.btn_script_add_task.setFixedHeight(36)
        self.btn_script_add_task.clicked.connect(self._add_script_scheduled_task)
        btn_row.addWidget(self.btn_script_add_task)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── 状态/日志 ──────────────────────────────────────────────────────
        self.script_status = QLabel(""); self.script_status.setObjectName("muted_text")
        root.addWidget(self.script_status)

        # 首次加载脚本列表
        self._populate_scripts()

    def _populate_scripts(self):
        """从服务端拉取分镜脚本列表（失败回退本地扫描）。"""
        self.combo_script.blockSignals(True)
        self.combo_script.clear()
        self.combo_script.addItem("— 请选择脚本 —", None)
        self.combo_script.setCurrentIndex(0)
        self.combo_script.blockSignals(False)
        self._current_script_data = None
        self.script_status.setText("正在从服务端加载脚本…")
        w = self.track_worker(ScriptListLoader())
        w.finished.connect(self._on_scripts_loaded)
        w.error.connect(self._on_scripts_load_error)
        w.start()

    def _on_scripts_loaded(self, items):
        scripts = []
        for it in items or []:
            sid = it.get("id")
            if not sid:
                continue
            scripts.append({
                "id": sid,
                "topic": it.get("topic", ""),
                "ratio": it.get("ratio", "9:16"),
                "shot_count": it.get("shot_count", 0),
                "saved_at": it.get("saved_at", ""),
            })
        self.combo_script.blockSignals(True)
        self.combo_script.clear()
        self.combo_script.addItem("— 请选择脚本 —", None)
        for s in scripts:
            label = f"[{s['topic']}] {s['shot_count']}镜"
            if s.get("saved_at"):
                label += f" · {s['saved_at']}"
            self.combo_script.addItem(label, s)
        self.combo_script.setCurrentIndex(0)
        self.combo_script.blockSignals(False)
        if scripts:
            self.script_preview.setMarkdown("*选择上方脚本查看预览*")
            self.script_status.setText(f"共 {len(scripts)} 个脚本（来自服务端）")
        else:
            self.script_preview.setMarkdown(
                "## ⚠ 服务端暂无分镜脚本\n\n"
                "在「分镜脚本创作」页生成脚本并保存（会自动上传服务端）后，回到本页点「刷新」即可看到。")
            self.script_status.setText("服务端暂无脚本")

    def _on_scripts_load_error(self, msg):
        log.warning(f"从服务端加载脚本失败，回退本地扫描: {msg}")
        scripts = self._scan_storyboard_scripts()
        self.combo_script.blockSignals(True)
        self.combo_script.clear()
        self.combo_script.addItem("— 请选择脚本 —", None)
        for s in scripts:
            label = f"[{s['topic']}] {s['name']}（{s['shot_count']}镜/{s['total_duration']}s）"
            self.combo_script.addItem(label, s)
        self.combo_script.setCurrentIndex(0)
        self.combo_script.blockSignals(False)
        if scripts:
            self.script_preview.setMarkdown("*选择上方脚本查看预览*")
            self.script_status.setText(f"服务端不可用，已回退本地（{len(scripts)} 个脚本）")
        else:
            self.script_preview.setMarkdown("## ⚠ 暂无可用的分镜脚本\n\n服务端不可用且本地也未找到脚本。")
            self.script_status.setText("未找到脚本（服务端不可用）")

    @staticmethod
    def _scan_storyboard_scripts():
        """扫描所有分镜 JSON 脚本。返回 [{name, path, topic, ratio, total_duration, shot_count, shots}]。"""
        results = []
        try:
            base = KNOWLEDGE_MEDIA_DIR
            if not base or not os.path.isdir(base):
                return results
            for topic_dir in sorted(os.listdir(base)):
                sb_dir = os.path.join(base, topic_dir, "storyboard")
                if not os.path.isdir(sb_dir):
                    continue
                for fn in sorted(os.listdir(sb_dir)):
                    if not fn.lower().endswith(".json"):
                        continue
                    fp = os.path.join(sb_dir, fn)
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        # 兼容性检查：必须有 shots 数组
                        if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
                            continue
                        results.append({
                            "name": os.path.splitext(fn)[0],
                            "path": fp,
                            "topic": data.get("topic", topic_dir),
                            "ratio": data.get("ratio", "9:16"),
                            "total_duration": data.get("total_duration", 0),
                            "shot_count": data.get("shot_count", len(data.get("shots", []))),
                            "shots": data.get("shots", []),
                            "saved_at": data.get("saved_at", 0),
                        })
                    except Exception as e:
                        log.warning(f"读取脚本失败 {fp}: {e}")
        except Exception as e:
            log.warning(f"扫描脚本失败: {e}")
        return results

    def _current_script(self):
        """返回当前选中的完整脚本 dict（无则 None）。"""
        if getattr(self, "_current_script_data", None):
            return self._current_script_data
        return self.combo_script.currentData() if hasattr(self, "combo_script") else None

    def _on_script_changed(self, _idx):
        s = self._current_script()
        if not s:
            self._current_script_data = None
            self.script_preview.setMarkdown("*选择上方脚本查看预览*")
            return
        sid = s.get("id")
        if sid:
            # 服务端脚本：异步拉取完整内容
            self._current_script_data = None
            self.script_preview.setMarkdown("*正在加载脚本内容…*")
            w = self.track_worker(ScriptDetailLoader(sid))
            w.finished.connect(self._on_script_detail_loaded)
            w.error.connect(lambda e, _sid=sid: self._on_script_detail_error(e, _sid))
            w.start()
        else:
            # 本地回退脚本：直接使用
            self._current_script_data = s
            self._apply_script_to_ui(s)

    def _on_script_detail_loaded(self, script):
        if not script:
            return
        self._current_script_data = script
        self._apply_script_to_ui(script)

    def _on_script_detail_error(self, err, sid):
        log.warning(f"加载脚本详情失败({sid}): {err}")
        self.script_preview.setMarkdown(f"⚠ 脚本加载失败：{err}")

    def _apply_script_to_ui(self, s):
        # 比例默认取脚本里的
        idx = self.script_combo_ratio.findText(s.get("ratio", "9:16"))
        if idx >= 0:
            self.script_combo_ratio.setCurrentIndex(idx)
        self.script_preview.setMarkdown(self._render_script_preview(s))

    @staticmethod
    def _render_script_preview(s):
        shots = s.get("shots", [])
        lines = [
            f"### {s.get('topic','')}",
            "",
            f"- **画幅**：{s.get('ratio','9:16')}　**总时长**：{s.get('total_duration',0)}s　**镜头数**：{s.get('shot_count',0)}",
            "",
            "| 镜号 | 时长 | 画面描述 | 旁白文案 | 素材路径 |",
            "|:---:|:---:|---|---|---|",
        ]
        for sh in shots:
            vis = str(sh.get("visual", "")).replace("|", "｜").replace("\n", " ").strip()
            nar = str(sh.get("audio", "") or sh.get("narration", "")).replace("|", "｜").replace("\n", " ").strip()
            mat = str(sh.get("material_path", "")).replace("|", "｜").strip()
            lines.append(f"| {sh.get('index','')} | {sh.get('duration','')}s | {vis} | {nar or '—'} | {mat or '—'} |")
        return "\n".join(lines)

    def _collect_script_params(self):
        """收集脚本成片的提交参数（适配服务端 storyboard_montage 执行器契约）。

        服务端契约（实测 /scheduled/tasks id=12/15）：
          params = {shots:[{index,shot_type,duration,visual,audio}], voice_settings:{speaker}}
        注意：文案字段服务端叫 `audio`（不是 storyboard 的 narration）；服务端自己做
        素材匹配，不收 material_path（保留无害）。
        """
        s = self._current_script() or {}
        raw_shots = s.get("shots", [])
        # 转成服务端期望的字段：narration → audio
        server_shots = []
        for sh in raw_shots:
            server_shots.append({
                "index": sh.get("index", 0),
                "shot_type": sh.get("shot_type", ""),
                "duration": sh.get("duration", 3),
                "visual": sh.get("visual", ""),
                "audio": sh.get("audio", "") or sh.get("narration", ""),  # 文案字段对齐（服务端脚本已是 audio）
                # 以下服务端不一定用，但保留供未来扩展（如服务端支持指定素材）
                "material_path": sh.get("material_path", ""),
                "material_type": sh.get("material_type", ""),
                "sfx": sh.get("sfx", ""),
            })
        return {
            # 服务端 storyboard_montage 执行器识别的核心字段
            "shots": server_shots,
            "voice_settings": {"speaker": "default"},
            "count": self.script_spin_count.value(),   # 变体数量（服务端进化选最优）
            # 客户端附加信息（服务端按需取用，不影响执行）
            "script_name": s.get("name", "") or s.get("id", ""),
            "script_path": s.get("path", ""),
            "topic": s.get("topic", ""),
            "ratio": self.script_combo_ratio.currentText(),
            "total_duration": s.get("total_duration", 0),
            "shot_count": s.get("shot_count", 0),
            "predict_platform": self.script_combo_platform.currentText(),
            "autocheck": self.script_chk_autocheck.isChecked(),
        }

    def _submit_script(self, immediate, schedule=None, title=""):
        """提交脚本成片任务到服务端（task_type=storyboard_montage）。"""
        from utils import scheduled_task_client as stc
        from utils.thread_worker import TaskWorker as Worker

        s = self._current_script()
        if not s:
            self.show_warning("请先选择一个脚本。")
            return
        params = self._collect_script_params()
        task_title = title or f"{s.get('topic','')}-{s.get('name','')}-脚本成片"

        self.btn_script_make.setEnabled(False); self.btn_script_add_task.setEnabled(False)
        self.script_status.setText("正在提交到服务端…" if immediate else "正在提交定时任务…")

        def _do():
            return stc.create_task("storyboard_montage", task_title, params, schedule=schedule)

        worker = Worker(_do)
        def _ok(tid):
            self.btn_script_make.setEnabled(True); self.btn_script_add_task.setEnabled(True)
            if tid:
                self.script_status.setText(f"✅ 已提交服务端，任务 ID={tid}")
                self.show_info(f"任务已提交服务端（ID={tid}）。\n\n"
                               + ("服务端正在执行，可在「成片任务」页查看进度。" if immediate
                                  else "服务端将按计划定时执行，可在「成片任务」页监控。"))
            else:
                self.script_status.setText("⚠ 提交失败")
                self.show_warning("提交服务端失败，请确认服务端在线后重试。")
        def _err(e):
            self.btn_script_make.setEnabled(True); self.btn_script_add_task.setEnabled(True)
            self.script_status.setText("⚠ 提交异常")
            self.show_error(f"提交异常：{e}", "错误")

        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker); worker.start()

    def _add_script_scheduled_task(self):
        """脚本成片的「添加为定时任务」：弹窗选调度，提交服务端定时执行。"""
        s = self._current_script()
        if not s:
            self.show_warning("请先选择一个脚本。")
            return
        from datetime import datetime as _dt
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("添加为定时任务（脚本成片，提交服务端）")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(f"{s.get('topic','')}-{s.get('name','')}")
        form.addRow("任务名称", name_edit)
        combo_mode = QComboBox()
        combo_mode.addItems({"daily": "每天（按时刻）", "once": "单次（指定日期时间）",
                             "weekly": "每周（指定星期）", "interval": "间隔（每 N 小时）"}.values())
        form.addRow("调度方式", combo_mode)
        time_edit = QTimeEdit(); time_edit.setTime(_dt.now().time().replace(second=0, microsecond=0))
        time_edit.setDisplayFormat("HH:mm"); form.addRow("执行时刻", time_edit)
        date_edit = QLineEdit(_dt.now().strftime("%Y-%m-%d")); date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("执行日期", date_edit)
        interval_spin = QSpinBox(); interval_spin.setRange(1, 168); interval_spin.setValue(24)
        form.addRow("间隔小时", interval_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        mode_map = {0: "daily", 1: "once", 2: "weekly", 3: "interval"}
        mode = mode_map[combo_mode.currentIndex()]
        hhmm = time_edit.time().toString("HH:mm")
        schedule = {"mode": mode, "time": hhmm}
        if mode == "once":
            schedule["date"] = date_edit.text().strip()
        elif mode == "weekly":
            schedule["weekdays"] = [0, 1, 2, 3, 4]
        elif mode == "interval":
            schedule["interval_hours"] = interval_spin.value()
        self._submit_script(immediate=False, schedule=schedule, title=name_edit.text().strip())

    # ════════════════════════════════════════════════════════════════════════
    #  产品选择
    # ════════════════════════════════════════════════════════════════════════
    def _populate_products(self):
        self.combo_product.blockSignals(True)
        self.combo_product.clear()
        try:
            grouped = self._product_mgr.grouped()
            # 先放一个占位空项
            self.combo_product.addItem("— 请选择产品 —", "")
            for cat, brands in grouped.items():
                for brand, items in brands.items():
                    for it in items:
                        model = it.get("model", "").strip() or it.get("goods_no", "")
                        label = f"[{cat}] {brand} / {model}"
                        self.combo_product.addItem(label, it.get("id", ""))
        except Exception as e:
            log.error(f"载入产品库失败: {e}")
            self._log(f"⚠ 载入产品库失败: {e}")
        self.combo_product.setCurrentIndex(0)
        self.combo_product.blockSignals(False)

    def _on_product_changed(self, _idx):
        item_id = self.combo_product.currentData() or ""
        if not item_id:
            self._features_text = ""
            self._selling_text = ""
            return
        it = self._product_mgr.get(item_id) or {}
        feat = (it.get("features") or "").strip()
        sell = (it.get("selling_points") or "").strip()
        self._features_text = feat
        self._selling_text = sell
        # 自动化：产品变化后把卖点首行自动填入模板 topic 参数（若为空）
        self._autofill_topic_from_selling()

    def _autofill_topic_from_selling(self):
        """把产品卖点首行自动填入模板 topic 参数（表单已生成且 topic 为空时）。"""
        if not self._current_template:
            return
        w = self._template_form_widgets.get("topic")
        if not w:
            return
        wtype, widget = w
        try:
            if widget_value(widget, wtype):
                return  # 用户已填则不覆盖
        except Exception:
            return
        sell = (self._selling_text or "").strip().splitlines()
        if sell:
            set_widget_value(widget, wtype, sell[0][:60])

    def _auto_open_task_monitor(self):
        """提交立即执行任务后，自动切到「成片任务」页并开启自动刷新。"""
        mw = getattr(self, "main_window", None)
        if mw is None:
            return
        tool = getattr(mw, "scheduled_tasks_tool", None)
        if tool is not None and hasattr(tool, "chk_autorefresh"):
            try:
                tool.chk_autorefresh.setChecked(True)
            except Exception:
                pass
        if hasattr(mw, "switch_page"):
            QTimer.singleShot(500, lambda: mw.switch_page(43))

    def _current_product(self):
        """返回当前选中产品 dict（无则 None）。"""
        item_id = self.combo_product.currentData() or ""
        if not item_id:
            return None
        return self._product_mgr.get(item_id)

    # ════════════════════════════════════════════════════════════════════════
    #  音色
    # ════════════════════════════════════════════════════════════════════════
    def _populate_voices(self):
        self.combo_voice.clear()
        self.combo_voice.addItem("默认音色（无参考）", "")
        try:
            from gui.voice_samples_page import load_voice_samples
            for s in load_voice_samples():
                name = s.get("name") or s.get("filename") or "样本"
                path = s.get("path", "")
                if path:
                    self.combo_voice.addItem(name, path)
        except Exception as e:
            log.error(f"载入音色样本失败: {e}")

    # ════════════════════════════════════════════════════════════════════════
    #  TTS / MG 开场
    # ════════════════════════════════════════════════════════════════════════
    def _tts_generate(self):
        text = self.in_subtitle.toPlainText().strip()
        if not text:
            self.show_warning("请先在『字幕文案 / 配音文案』里填入要配音的文案。")
            return
        ref = self.combo_voice.currentData() or ""
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("tts_%Y%m%d_%H%M%S.wav"))
        self.btn_tts.setEnabled(False); self.progress_bar.setVisible(True)
        self.stage_label.setText("准备配音…")
        worker = TTSWorker(text, ref, out)
        worker.phase.connect(self.stage_label.setText)

        def done(path):
            self.btn_tts.setEnabled(True); self.progress_bar.setVisible(False)
            self.in_audio.setText(path)
            self.stage_label.setText(f"✅ 配音已生成并填入：{os.path.basename(path)}")
            self._log(f"✅ 配音已生成: {path}")

        worker.done.connect(done)
        worker.error.connect(lambda e: (self.btn_tts.setEnabled(True), self.progress_bar.setVisible(False),
                                        self.show_error(str(e), "TTS 配音失败")))
        self.track_worker(worker); worker.start()

    def _gen_mg_intro(self):
        from PySide6.QtWidgets import QInputDialog
        default = (self.in_subtitle.toPlainText().strip().splitlines() or [""])[0][:16]
        title, ok = QInputDialog.getText(self.parent_widget, "动态标题开场", "标题文字：", text=default)
        if not ok or not title.strip():
            return
        from gui.mg_render_worker import MGServerRenderWorker
        from utils.mg_server_client import make_mg_request
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("mgintro_%Y%m%d_%H%M%S.mp4"))
        self.btn_mg_intro.setEnabled(False); self.progress_bar.setVisible(True)
        self.stage_label.setText("正在渲染动态标题开场（MG）…")
        request = make_mg_request(
            template="mg_intro",
            ratio="9:16",
            title=title.strip(),
            subtitle="",
            color="#FFFFFF",
            bg="#101418",
            duration=3,
        )
        w = MGServerRenderWorker(request, title="一键成片-MG开场")
        w.phase.connect(self.stage_label.setText)
        os.makedirs(os.path.dirname(out), exist_ok=True)

        def done(path):
            self.btn_mg_intro.setEnabled(True); self.progress_bar.setVisible(False)
            self.in_intro.setText(path)
            self.stage_label.setText(f"✅ 开场动画已生成：{os.path.basename(path)}")
            self._log(f"✅ MG 开场已生成: {path}")
        w.finished.connect(done)
        w.error.connect(lambda e: (self.btn_mg_intro.setEnabled(True), self.progress_bar.setVisible(False),
                                   self.show_error(str(e), "MG 开场生成失败")))
        self.track_worker(w); w.start()
    def _collect_params(self):
        """收集当前界面完整参数为 dict（提交给服务端，服务端按需取用）。"""
        product = self._current_product() or {}
        return {
            # 服务端 product_montage 执行器识别的参数
            "products": [{
                "brand": product.get("brand", ""),
                "model": product.get("model", ""),
                "features": self._split_md_lines(product.get("features", "")),
                "selling_points": self._split_md_lines(product.get("selling_points", "")),
                "category": product.get("category", ""),
                "goods_no": product.get("goods_no", ""),
            }],
            "script_hint": self.in_subtitle.toPlainText().strip() or
                            (product.get("selling_points", "") or "")[:120],
            "max_duration": int(self.spin_total_dur.value()) if self.spin_total_dur.value() > 0 else 30,
            # 客户端完整参数（服务端按自身实现取用）
            "product_id": product.get("id", ""),
            "product_label": self.combo_product.currentText(),
            "folder": self.in_folder.text().strip(),
            "audio": self.in_audio.text().strip(),
            "cover": self.in_cover.text().strip(),
            "subtitle": self.in_subtitle.toPlainText().strip(),
            "ratio": self.combo_ratio.currentText(),
            "per_dur": self.spin_dur.value(),
            "count": self.spin_count.value(),
            "total_dur": self.spin_total_dur.value(),
            "intro": self.in_intro.text().strip(),
            "predict_platform": self.combo_predict_platform.currentText(),
            "autocheck": self.chk_autocheck.isChecked(),
            "materials": self._materials or [],
            "template_id": self._current_template.get("id", "") if self._current_template else "",
            "template_params": self._collect_template_params(),
        }

    @staticmethod
    def _split_md_lines(md_text):
        """把 Markdown 列表文本拆成要点列表（服务端 products.features 期望 list）。"""
        if not md_text:
            return []
        out = []
        for line in str(md_text).splitlines():
            s = line.strip().lstrip("-").lstrip("*").strip()
            if s:
                out.append(s)
        return out

    def _make(self):
        """开始执行 = 提交服务端立即执行（task_type=product_montage）。"""
        product = self._current_product()
        if not product:
            self.show_warning("请先选择产品（产品是一键成片的起点）。")
            return
        self._submit_to_server(schedule=None, immediate=True)

    def _add_scheduled_task(self):
        """添加为定时任务 = 提交服务端定时执行。弹窗输入任务名 + 调度配置。"""
        product = self._current_product()
        if not product:
            self.show_warning("请先选择产品（产品是一键成片的起点）。")
            return
        from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QSpinBox, QTimeEdit, QComboBox, QLineEdit
        from datetime import datetime as _dt

        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("添加为定时任务（提交服务端）")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        name_edit.setText(f"{product.get('model','') or product.get('brand','')}-成片")
        form.addRow("任务名称", name_edit)
        combo_mode = QComboBox()
        combo_mode.addItems({"daily": "每天（按时刻）", "once": "单次（指定日期时间）",
                             "weekly": "每周（指定星期）", "interval": "间隔（每 N 小时）"}.values())
        form.addRow("调度方式", combo_mode)
        time_edit = QTimeEdit()
        time_edit.setTime(_dt.now().time().replace(second=0, microsecond=0))
        time_edit.setDisplayFormat("HH:mm")
        form.addRow("执行时刻", time_edit)
        date_edit = QLineEdit(_dt.now().strftime("%Y-%m-%d"))
        date_edit.setPlaceholderText("YYYY-MM-DD（单次模式用）")
        form.addRow("执行日期", date_edit)
        interval_spin = QSpinBox(); interval_spin.setRange(1, 168); interval_spin.setValue(24)
        form.addRow("间隔小时", interval_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return

        mode_map = {0: "daily", 1: "once", 2: "weekly", 3: "interval"}
        mode = mode_map[combo_mode.currentIndex()]
        hhmm = time_edit.time().toString("HH:mm")
        schedule = {"mode": mode, "time": hhmm}
        if mode == "once":
            schedule["date"] = date_edit.text().strip()
        elif mode == "weekly":
            schedule["weekdays"] = [0, 1, 2, 3, 4]
        elif mode == "interval":
            schedule["interval_hours"] = interval_spin.value()

        self._submit_to_server(schedule=schedule, immediate=False,
                               title=name_edit.text().strip())

    def _submit_to_server(self, schedule, immediate, title=""):
        """提交任务到服务端 /scheduled/tasks。immediate=True 立即执行；False 按 schedule 定时。"""
        from utils import scheduled_task_client as stc
        product = self._current_product() or {}
        params = self._collect_params()
        task_title = title or f"{product.get('model','') or product.get('brand','')}-成片"

        self.btn_make.setEnabled(False)
        self.btn_add_task.setEnabled(False)
        self.stage_label.setText("正在提交到服务端…")
        self._log(f"📤 提交任务到服务端：{task_title}（{'立即执行' if immediate else '定时执行'}）")

        # 用 TaskWorker 异步提交（避免阻塞 UI）
        from utils.thread_worker import TaskWorker as Worker
        def _do_submit():
            tid = stc.create_task("product_montage", task_title, params, schedule=schedule)
            return tid

        worker = Worker(_do_submit)
        def _on_done(tid):
            self.btn_make.setEnabled(True); self.btn_add_task.setEnabled(True)
            if tid:
                self.stage_label.setText(f"✅ 已提交服务端，任务 ID={tid}")
                self._log(f"✅ 服务端已接收，任务 ID={tid}。可在「成片任务」页监控状态。")
                self.show_info(f"任务已提交服务端（ID={tid}）。\n\n"
                               + ("服务端正在执行，已自动打开「成片任务」页监控进度。"
                                  if immediate else
                                  "服务端将按计划定时执行，可在「成片任务」页监控。"))
                if immediate:
                    self._auto_open_task_monitor()
            else:
                self.stage_label.setText("⚠ 提交失败")
                self._log("❌ 服务端提交失败，请检查服务端连接")
                self.show_warning("提交服务端失败，请确认服务端在线后重试。")
        def _on_err(e):
            self.btn_make.setEnabled(True); self.btn_add_task.setEnabled(True)
            self.stage_label.setText("⚠ 提交失败")
            self._log(f"❌ 提交异常: {e}")
            self.show_error(f"提交异常：{e}", "错误")

        worker.finished.connect(_on_done)
        worker.error.connect(_on_err)
        self.track_worker(worker); worker.start()

    def _match_material_then_make(self, product):
        """异步远程匹配素材目录，成功后继续 _do_make。"""
        self.btn_make.setEnabled(False)
        self.stage_label.setText("正在按产品远程匹配素材目录…")
        brand = product.get("brand", "")
        model = product.get("model", "")
        category = product.get("category", "")
        mw = MaterialMatchWorker(brand, model, category)
        mw.log_line.connect(self._log)

        def on_done(folder):
            self.btn_make.setEnabled(True)
            if folder and os.path.isdir(folder):
                self.in_folder.setText(folder)
                self.stage_label.setText(f"✅ 已匹配素材目录: {folder}")
                self._do_make(folder)
            else:
                self.stage_label.setText("⚠ 未能自动匹配素材目录")
                self.show_warning("未能自动匹配到素材目录，请手动选择「镜头素材目录」。")

        def on_err(e):
            self.btn_make.setEnabled(True)
            self.stage_label.setText("⚠ 素材匹配失败")
            self.show_warning(f"素材匹配失败：{e}\n请手动选择「镜头素材目录」。")

        mw.result_ready.connect(on_done)
        mw.error.connect(on_err)
        self.track_worker(mw); mw.start()

    def _do_make(self, folder):
        out_dir = FINAL_OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        count = self.spin_count.value()
        total_dur = self.spin_total_dur.value()
        self.btn_make.setEnabled(False)
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)
        self._last_results = []

        self.worker = CompileVideoWorker(
            folder, out_dir,
            self.in_audio.text().strip(),
            self.in_cover.text().strip(),
            self.in_subtitle.toPlainText().strip(),
            self.combo_ratio.currentText(),
            self.spin_dur.value(),
            count=count,
            total_dur=total_dur,
            intro=self.in_intro.text().strip(),
        )
        self.worker.phase.connect(self.stage_label.setText)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log_line.connect(self._log)
        self.worker.done.connect(self._done)
        self.worker.error.connect(self._err)
        self.track_worker(self.worker); self.worker.start()

    def _done(self, results):
        self._last_results = results or []
        self.btn_make.setEnabled(True)
        # 填充结果列表
        self.result_table.setRowCount(len(self._last_results))
        for i, path in enumerate(self._last_results):
            self.result_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.result_table.setItem(i, 1, QTableWidgetItem(os.path.basename(path)))
            status_item = QTableWidgetItem("✅ 完成")
            status_item.setForeground(Qt.GlobalColor.green)
            self.result_table.setItem(i, 2, status_item)
            btn = table_action_button("📂", "打开")
            btn.clicked.connect(lambda _=False, p=path: self._open_file(p))
            self.result_table.setCellWidget(i, 3, btn)
        self.stage_label.setText(f"✅ 完成：共生成 {len(self._last_results)} 个成片")
        self._log(f"═══ 全部完成：{len(self._last_results)} 个成片 ═══")

        # 自动视频评价预测（只对第一个成片）
        if self.chk_autocheck.isChecked() and self._last_results:
            cfg = self.ai_config
            if cfg.get("llm_vision_api_url") and cfg.get("llm_vision_model"):
                from gui.hook_score_page import HookScoreWorker
                platform = self.combo_predict_platform.currentText()
                self._predict_platform = platform
                try:
                    calib = VideoPredictionManager().calibration_text(platform=platform)
                except Exception:
                    calib = ""
                self.score_label.setText(f"⏳ 正在按「{platform}」做视频评价预测…")
                out = self._last_results[0]
                sw = HookScoreWorker(out, cfg, platform=platform, calibration=calib)
                sw.finished.connect(self._on_self_check)
                sw.error.connect(lambda e: self.score_label.setText(f"视频预测失败：{e}"))
                self.track_worker(sw); sw.start()
            else:
                self.score_label.setText("（未配置视觉模型，跳过视频评价预测。）")

    def _on_self_check(self, data):
        self._self_check_data = data
        total = data.get("total", "—")
        level = data.get("play_level", "")
        comment = str(data.get("comment", ""))
        self.score_label.setText(f"📈 视频预测：综合 {total} 分 · 预测{level}　{comment}")
        self.btn_detail.setVisible(True)
        try:
            if self._last_results:
                VideoPredictionManager().add_prediction(
                    self._last_results[0], getattr(self, "_predict_platform", "抖音"), data)
        except Exception:
            pass

    def _open_detail(self):
        tool = getattr(self.main_window, "hook_score_tool", None)
        try:
            self.main_window.switch_page(35)  # 开头黄金3秒评分
            if tool and hasattr(tool, "show_result") and self._last_results:
                tool.show_result(self._last_results[0], self._self_check_data)
        except Exception as e:
            self.show_error(f"跳转失败：{e}")

    def _err(self, e):
        self.btn_make.setEnabled(True)
        self.stage_label.setText("成片失败。")
        self._log(f"❌ 失败: {e}")
        self.show_error(str(e), "一键成片失败")

    # ════════════════════════════════════════════════════════════════════════
    #  辅助
    # ════════════════════════════════════════════════════════════════════════
    def _log(self, text):
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {text}")
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _auto_select_product(self, materials):
        """根据素材中出现最多的品牌/型号自动选择产品（无匹配则保持原选项）。"""
        if not materials:
            return
        from collections import Counter
        pairs = Counter()
        for m in materials:
            brand = (m.get("brand") or "").strip()
            model = (m.get("model") or "").strip()
            if brand or model:
                pairs[(brand, model)] += 1
        if not pairs:
            return
        (target_brand, target_model), _ = pairs.most_common(1)[0]
        try:
            # 遍历产品下拉框，按数据(id)反查产品库匹配品牌/型号
            for i in range(self.combo_product.count()):
                pid = self.combo_product.itemData(i)
                if not pid:
                    continue
                it = self._product_mgr.get(pid) or {}
                b = (it.get("brand") or "").strip()
                mo = (it.get("model") or "").strip() or (it.get("goods_no") or "").strip()
                if target_brand and target_model:
                    if b == target_brand and (mo == target_model or target_model in mo or mo in target_model):
                        self.combo_product.setCurrentIndex(i)
                        self._log(f"📦 已根据素材自动选择产品: {self.combo_product.currentText()}")
                        return
                elif target_brand and b == target_brand:
                    self.combo_product.setCurrentIndex(i)
                    self._log(f"📦 已根据素材品牌自动选择产品: {self.combo_product.currentText()}")
                    return
        except Exception as e:
            log.error(f"自动选择产品失败: {e}")

    def import_materials(self, materials):
        """从素材检索带入素材列表（支持多个、图片+视频混合）。"""
        self._materials = list(materials or [])
        self.material_list.clear()
        for m in self._materials:
            fname = m.get("filename") or m.get("material_id") or ""
            mtype = (m.get("media_type") or "").lower()
            icon = {"video": "🎬", "image": "🖼️", "audio": "🎵"}.get(mtype, "📁")
            item = QListWidgetItem(f"{icon} {fname}")
            item.setData(Qt.UserRole, m)
            self.material_list.addItem(item)
        self.lbl_material_count.setText(f"已选 {len(self._materials)} 个素材（图片/视频混合）")
        self._auto_select_product(materials)

    def _clear_materials(self):
        self._materials = []
        self.material_list.clear()
        self.lbl_material_count.setText("已选 0 个素材（可在「素材检索」选择后点击「一键成片」带入）")

    def _file_row(self, parent, label, on_browse, folder=False, placeholder=""):
        parent.addWidget(QLabel(label))
        row = QHBoxLayout()
        edit = QLineEdit(); edit.setPlaceholderText(placeholder)
        row.addWidget(edit, 1)
        btn = mdi_button("浏览…", "folder"); btn.setObjectName("secondary_button")
        btn.clicked.connect(lambda: on_browse(edit))
        row.addWidget(btn)
        parent.addLayout(row)
        return edit

    def _browse_folder(self, edit):
        d = pick_directory(self.parent_widget, "选择素材目录")
        if d:
            edit.setText(d)

    def _browse_audio(self, edit):
        f, _ = pick_file(self.parent_widget, "选择配音", "", "音频 (*.wav *.mp3 *.m4a *.aac *.flac)")
        if f:
            edit.setText(f)

    def _browse_cover(self, edit):
        f, _ = pick_file(self.parent_widget, "选择封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if f:
            edit.setText(f)

    def _browse_intro(self, edit):
        f, _ = pick_file(self.parent_widget, "选择开场视频", "",
                                           "视频 (*.mp4 *.mov *.mkv *.webm)")
        if f:
            edit.setText(f)

    def _open_file(self, path):
        if path and os.path.isfile(path) and os.name == "nt":
                os.startfile(path)  # noqa

    # -------------- 模板相关方法 --------------
    def _load_templates(self):
        """加载成片模板库（统一接口 /templates?type=video + 内置兜底）。"""
        self._templates = list(VIDEO_FALLBACK_TEMPLATES)
        fill_template_list(self.list_templates, self._templates)
        w = VideoTemplateLoadWorker()
        w.finished.connect(self._on_templates_loaded)
        w.phase.connect(self._log)
        self.track_worker(w)
        w.start()

    def _on_templates_loaded(self, server_templates):
        if not server_templates:
            self._log("⚠ 未从服务端加载到成片模板，使用内置模板")
        self._templates = merge_templates(server_templates, VIDEO_FALLBACK_TEMPLATES)
        current_id = self._current_template.get("id") if self._current_template else None
        fill_template_list(self.list_templates, self._templates, current_id=current_id)

    def _on_template_selected(self, current, previous):
        if current is None:
            return
        template = current.data(Qt.UserRole)
        if not template:
            return
        self._current_template = template
        self._apply_template_to_editor(template)

    def _apply_template_to_editor(self, template):
        self._build_template_form(template)
        self.btn_template_defaults.setEnabled(True)
        self.template_params_group.setVisible(True)
        defaults = template.get("defaults") or {}
        for key, val in defaults.items():
            if key in self._template_form_widgets:
                wtype, widget = self._template_form_widgets[key]
                set_widget_value(widget, wtype, val)
        # 自动化：选中模板后若已选产品，自动填 topic 参数
        self._autofill_topic_from_selling()

    def _build_template_form(self, template):
        while self.template_form_layout.count():
            item = self.template_form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._template_form_widgets.clear()
        params = template.get("params") or []
        for param in params:
            key, wtype, label, default = _param_meta(param)
            if not key:
                continue
            if wtype == "scenes":
                continue
            widget = create_value_widget(wtype, default)
            self._template_form_widgets[key] = (wtype, widget)
            if wtype == "color":
                self.template_form_layout.addRow(label, color_row(widget))
            else:
                self.template_form_layout.addRow(label, widget)

    def _collect_template_params(self):
        values = {}
        for key, (wtype, widget) in self._template_form_widgets.items():
            values[key] = widget_value(widget, wtype)
        return values

    def _set_template_defaults(self):
        if not self._current_template:
            return
        defaults = self._current_template.get("defaults") or {}
        for key, val in defaults.items():
            if key in self._template_form_widgets:
                wtype, widget = self._template_form_widgets[key]
                set_widget_value(widget, wtype, val)
        # also fill template-defined params default
        for param in self._current_template.get("params") or []:
            key, wtype, label, default = _param_meta(param)
            if key and key in self._template_form_widgets:
                wtype, widget = self._template_form_widgets[key]
                set_widget_value(widget, wtype, default)

    def _preview_template(self):
        """预览播放：渲染当前成片模板（/templates/render）→ 轮询 → 下载 → 本地播放。"""
        if not self._current_template:
            self.show_warning("请先选择成片模板。")
            return
        template_id = self._current_template.get("id")
        params = dict(self._collect_template_params())
        if not params.get("topic"):
            product = self._current_product() or {}
            selling = (product.get("selling_points") or "").strip().splitlines()
            if selling:
                params["topic"] = selling[0][:60]
        ratio = self.combo_ratio.currentText()
        self.btn_preview_play.setEnabled(False)
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.stage_label.setText("正在渲染成片模板（预览）…")
        self._log(f"🎬 预览渲染：template={template_id} ratio={ratio} params={params}")
        w = TemplatePreviewWorker(template_id, params, ratio)
        w.progress.connect(self.progress_bar.setValue)
        w.phase.connect(self.stage_label.setText)

        def _done(out):
            self.btn_preview_play.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.stage_label.setText(f"✅ 预览已生成：{os.path.basename(out)}")
            self._log(f"✅ 成片模板预览：{out}")
            self._play_preview(out)

        def _err(e):
            self.btn_preview_play.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.stage_label.setText("⚠ 预览渲染失败")
            self.show_error(str(e), "预览渲染失败")

        w.finished.connect(_done)
        w.error.connect(_err)
        self.track_worker(w); w.start()

    def _play_preview(self, path):
        """用统一播放器预览成片（等比显示 + 播放/暂停/停止 + 进度条 + 时间）；失败回退系统播放器。"""
        try:
            from gui.video_player import VideoPreviewDialog
            dlg = VideoPreviewDialog(path=path, parent=self.parent_widget,
                                     title="成片模板预览", size=(560, 760))
            dlg.exec()
        except Exception as e:
            self._log(f"⚠ 内置播放失败，改用系统播放器: {e}")
            try:
                os.startfile(os.path.abspath(path))  # noqa
            except Exception:
                self.show_warning(f"预览文件已生成：{path}")

    def _show_selling_dialog(self):
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("卖点文案 / 性能参数")
        dlg.setMinimumSize(420, 320)
        layout = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        feat = self._features_text or "*该产品暂无性能参数*"
        sell = self._selling_text or "*该产品暂无核心卖点*"
        browser.setMarkdown(f"## 性能参数\n\n{feat}\n\n## 核心卖点\n\n{sell}")
        layout.addWidget(browser)
        btn = QDialogButtonBox(QDialogButtonBox.Ok)
        btn.accepted.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()
