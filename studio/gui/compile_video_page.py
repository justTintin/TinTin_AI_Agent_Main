"""
一键成片页。

整体布局（上左右下三段式）：
    ┌─ heading ────────────────────────────────────────────┐
    ├─ 上段（QSplitter 横向）                              │
    │   左：产品选择（必选，任务起点）+ 成片模板/模板参数      │
    │   右：概述（模板信息，不含分镜脚本）+ 输出结果 + 日志   │
    ├─ 底部：变体数量/总时长/比例/平台 + 执行按钮            │
    └─ 输出段：结果列表 + 执行日志 + 进度条                  │

产品库读取用 ProductLibraryManager；远程素材匹配用 /material/search；
重型剪辑仍走「智能混剪」；本页面向"快速出片"。
逻辑见 utils/video_compiler.py。
"""
import contextlib
import os
import time
from collections import Counter
from datetime import datetime

import requests.exceptions
from config.paths import FINAL_OUTPUT_DIR, KNOWLEDGE_MEDIA_DIR, TMP_DIR
from gui._tab_compat import setup_tab_widget
from gui.base_page import BasePage
from gui.elided_label import ElidedLabel
from gui.montage.beat_montage_controller import BeatMontageController
from gui.montage.step_beat_view import StepBeatView
from gui.searchable_combo import SearchableComboBox
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from utils import material_client
from utils.base_worker import BaseWorker
from utils.file_dialog_utils import pick_directory, pick_file
from utils.gui_icons import icon_button, mdi_button, table_action_button
from utils.json_utils import compact_text
from utils.logger_utils import log
from utils.product_library_manager import ProductLibraryManager
from utils.template_param_builder import collect_script_params, extract_script_summary
from utils.template_server_client import list_templates as list_video_templates
from utils.video_compiler import RATIO_SIZES, collect_images, compile_video, scan_storyboard_scripts, split_groups
from utils.video_prediction_manager import PLATFORMS, VideoPredictionManager
from utils.voxcpm_client import synthesize_tts


class TTSWorker(BaseWorker):
    phase = Signal(str)
    done = Signal(str)

    def __init__(self, text, ref_wav, out_path):
        super().__init__()
        self.text = text
        self.ref_wav = ref_wav
        self.out_path = out_path

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
        self.brand = brand
        self.model = model
        self.category = category

    def do_work(self):
        try:
            params = {"limit": 200, "offset": 0}
            if self.brand:
                params["brand"] = self.brand
            if self.category:
                params["category"] = self.category
            if self.model:
                params["model"] = self.model
            self.log_line.emit(f" 远程匹配素材: brand={self.brand!r} category={self.category!r}")  # noqa: E501
            data = material_client.search(params, timeout=15)
            if data is None:
                self.log_line.emit("注意： 服务端素材检索失败")
                self.result_ready.emit("")
                return
            results = data.get("results") or data.get("data") or []
            if not results:
                self.log_line.emit("注意： 远程未匹配到任何素材")
                self.result_ready.emit("")
                return
            # 收集所有 path，取公共父目录作为素材目录
            paths = [r.get("path", "") for r in results if r.get("path")]
            paths = [p for p in paths if p]
            if not paths:
                self.log_line.emit("注意： 匹配结果无可用 path 字段")
                self.result_ready.emit("")
                return
            common = os.path.commonpath(paths) if len(paths) > 1 else os.path.dirname(paths[0])  # noqa: E501
            # commonpath 可能指向文件，确保是目录：若指向文件则取其父
            if os.path.isfile(common):
                common = os.path.dirname(common)
            self.log_line.emit(f" 匹配到 {len(paths)} 个素材，目录: {common}")
            self.result_ready.emit(common)
        except (requests.exceptions.RequestException, KeyError, TypeError, AttributeError, OSError) as e:  # noqa: E501
            self.log_line.emit(f"注意： 远程匹配失败: {e}")
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
        self.audio = audio
        self.cover = cover
        self.subtitle = subtitle
        self.ratio = ratio
        self.per_dur = per_dur
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
            self.log_line.emit(f" 按总时长 {self.total_dur}s / {len(images)} 张 → 每张 {per_dur:.2f}s")  # noqa: E501

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results = []

        if self.count == 1:
            out_path = os.path.join(self.out_dir, f"final_{timestamp}.mp4")
            self.phase.emit("正在生成成片…")
            self.progress.emit(20)
            self._compile_one(images, out_path, per_dur, has_audio)
            results.append(out_path)
            self.log_line.emit(f"完成： 成片: {os.path.basename(out_path)}")
        else:
            # N 个成片：把 images 分成 N 组（不足循环填充）
            groups = split_groups(images, self.count)
            total = self.count
            for i, group in enumerate(groups):
                out_path = os.path.join(self.out_dir, f"final_{timestamp}_{i + 1}.mp4")
                self.phase.emit(f"正在生成第 {i + 1}/{total} 个成片…")
                self.progress.emit(int(i / total * 100))
                try:
                    self._compile_one(group, out_path, per_dur, has_audio)
                    results.append(out_path)
                    self.log_line.emit(f"完成： [{i + 1}/{total}] {os.path.basename(out_path)}")  # noqa: E501
                except Exception as e:  # 视频编译外部调用，可能涉及多种异常
                    self.log_line.emit(f"失败： [{i + 1}/{total}] 失败: {e}")
                    log.warning(f"成片 {i + 1} 失败: {e}")

        self.progress.emit(100)
        self.done.emit(results)

    def _compile_one(self, images, out_path, per_dur, has_audio):
        compile_video(images, out_path, audio=self.audio, cover=self.cover,
                      subtitle_text=self.subtitle, ratio=self.ratio, per_dur=per_dur,
                      intro=self.intro, progress=self.log_line.emit)

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
            render as _render,
        )
        from utils.template_server_client import (
            render_download as _download,
        )
        from utils.template_server_client import (
            render_result as _result,
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
            except (KeyError, TypeError, ValueError):
                prog = 0
            self.progress.emit(prog)
            self.phase.emit(f"预览渲染中… {prog}%")
            if status in ("completed", "done", "success"):
                resp = _download(task_id)
                if resp is None:
                    raise RuntimeError("预览渲染完成但下载失败。")
                out = os.path.join(TMP_DIR, f"tpl_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")  # noqa: E501
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "wb") as f:
                    f.write(resp.content)
                self.finished.emit(out)
                return
            if status in ("failed", "error"):
                raise RuntimeError(f"预览渲染失败：{st.get('error') or '未知错误'}")
        raise RuntimeError("预览渲染超时（15 分钟）。")


class ScriptListLoader(BaseWorker):
    """从服务端拉取分镜脚本列表摘要（双路径兼容，见 utils.storyboard_client）。"""
    finished = Signal(list)

    def do_work(self):
        from utils.storyboard_client import list_scripts
        self.finished.emit(list_scripts(page=1, page_size=100))


class ScriptDetailLoader(BaseWorker):
    """从服务端拉取完整分镜脚本（双路径兼容，见 utils.storyboard_client）。"""
    finished = Signal(dict)

    def __init__(self, script_id):
        super().__init__()
        self.script_id = script_id

    def do_work(self):
        from utils.storyboard_client import get_script
        self.finished.emit(get_script(self.script_id))


class ScriptTaskPollWorker(BaseWorker):
    """轮询服务端成片任务状态，直到完成/失败或超时。

    每隔 poll_interval 秒调用 /tasks/unified/{id}，emit progress/status 信号。
    """
    progress = Signal(int, str)       # (0-100, stage_label)
    status_changed = Signal(str)      # status: pending/running/completed/failed
    completed = Signal(dict)         # 完整任务数据
    failed = Signal(str)              # 错误信息

    STAGE_MAP = {
        "pending": "排队中",
        "material_matching": "素材匹配中",
        "tts": "TTS 配音中",
        "compiling": "视频合成中",
        "quality_check": "质量评分中",
        "completed": "已完成",
        "failed": "失败",
    }

    def __init__(self, task_id, poll_interval=3, timeout=900):
        super().__init__()
        self.task_id = task_id
        self.poll_interval = poll_interval
        self.timeout = timeout

    def do_work(self):
        from utils import scheduled_task_client as stc
        deadline = time.time() + self.timeout
        last_status = ""
        while time.time() < deadline:
            task = stc.get_task(self.task_id)
            if task is None:
                self.failed.emit("无法获取任务状态")
                return
            status = (task.get("status") or "").lower()
            progress_val = int(task.get("progress") or 0)
            stage = self.STAGE_MAP.get(status, status or "处理中")
            self.progress.emit(progress_val, stage)
            if status != last_status:
                last_status = status
                self.status_changed.emit(status)
            if status in ("completed", "done", "success"):
                self.completed.emit(task)
                return
            if status in ("failed", "error"):
                err = task.get("error_msg") or task.get("error") or "未知错误"
                self.failed.emit(str(err))
                return
            time.sleep(self.poll_interval)
        self.failed.emit("任务轮询超时（15 分钟）")


class _TemplateMatchWorker(BaseWorker):
    """模板引擎：按 slot 的 tag 列表调用 /montage/match 智能匹配素材。"""
    progress = Signal(int, str)

    def __init__(self, slots, top_k=5):
        super().__init__()
        self.slots = slots
        self.top_k = top_k

    def do_work(self):
        from utils.template_server_client import match_materials
        self.progress.emit(0, "开始智能匹配素材…")
        result = match_materials(self.slots, top_k=self.top_k, timeout=30)
        if not result:
            self.progress.emit(100, "匹配完成（无结果）")
            self.finished.emit({})
            return
        self.progress.emit(100, "匹配完成")
        self.finished.emit(result)


class _TemplateGenerateWorker(BaseWorker):
    """模板引擎：提交 /template/generate 并轮询进度。"""
    phase = Signal(str)
    progress = Signal(int)
    status_changed = Signal(str)
    completed = Signal(dict)
    failed = Signal(str)

    STAGE_MAP = {
        "pending": "排队中",
        "material_prepare": "素材准备中",
        "rendering": "渲染中",
        "compositing": "合成中",
        "completed": "已完成",
        "failed": "失败",
    }

    def __init__(self, template_id, slot_materials, params=None, ratio="9:16"):
        super().__init__()
        self.template_id = template_id
        self.slot_materials = slot_materials
        self.params = params or {}
        self.ratio = ratio

    def do_work(self):
        from utils import scheduled_task_client as stc
        from utils.template_server_client import generate_template
        self.phase.emit("正在提交模板成片任务…")
        task_id = generate_template(
            self.template_id, self.slot_materials,
            params=self.params, ratio=self.ratio, timeout=60,
        )
        if not task_id:
            self.failed.emit("模板成片任务提交失败")
            return
        self.phase.emit(f"任务已提交：{task_id}")
        deadline = time.time() + 900
        last_status = ""
        while time.time() < deadline:
            time.sleep(3)
            task = stc.get_task(task_id)
            if task is None:
                self.failed.emit("无法获取任务状态")
                return
            status = (task.get("status") or "").lower()
            progress_val = int(task.get("progress") or 0)
            stage = self.STAGE_MAP.get(status, status or "处理中")
            self.progress.emit(progress_val)
            self.phase.emit(f"{stage} ({progress_val}%)")
            if status != last_status:
                last_status = status
                self.status_changed.emit(status)
            if status in ("completed", "done", "success"):
                self.completed.emit(task)
                return
            if status in ("failed", "error"):
                err = task.get("error_msg") or task.get("error") or "未知错误"
                self.failed.emit(str(err))
                return
        self.failed.emit("任务轮询超时（15 分钟）")


class _TemplateImportWorker(BaseWorker):
    """异步导入剪映/PR 模板文件。"""

    def __init__(self, file_path, name, category, description):
        super().__init__()
        self.file_path = file_path
        self.name = name
        self.category = category
        self.description = description

    def do_work(self):
        from utils.template_server_client import import_template_file
        result = import_template_file(
            self.file_path, self.name, self.category, self.description,
        )
        if result is None:
            raise RuntimeError("模板导入失败")
        self.finished.emit(result)


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
        self._features_text = ""
        self._selling_text = ""
        # 脚本成片内嵌进度/结果
        self._script_player = None
        self._script_audio_output = None
        self._script_current_task_id = None
        self._script_poll_worker = None
        # 模板引擎状态
        self._tpl_templates = []
        self._tpl_current_template = None
        self._tpl_matched_slots = {}       # {slot: [{material_id, score, ...}, ...]}
        self._tpl_selected_materials = {}   # {slot: material_id}
        self._tpl_generate_worker = None
        self._tpl_player = None
        self._tpl_audio_output = None
        self._tpl_video_url = ""

    # ════════════════════════════════════════════════════════════════════════
    #  setup：构建界面（顶层 TabBar+Stack：产品成片 + 脚本成片）
    # ════════════════════════════════════════════════════════════════════════
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QLabel(" 一键成片")
        title.setObjectName("heading")
        title.setFixedHeight(28)
        root.addWidget(title, 0, Qt.AlignLeft)

        self._tab_bar, self._stack, self.tabs = setup_tab_widget(root, 1)

        # tab1：产品成片（原有完整界面）
        # 产品成片 tab 暂时隐藏（功能当前不可用）
        # tab_product = QWidget()
        # self._setup_product_tab(tab_product)
        # self._tab_bar.addTab(" 产品成片")
        # self._stack.addWidget(tab_product)

        # tab2：脚本成片（选分镜脚本提交服务端）
        tab_script = QWidget()
        self._setup_script_tab(tab_script)
        self._tab_bar.addTab(" 脚本成片")
        self._stack.addWidget(tab_script)

        # tab3：卡点成片（音乐卡点 + 服务端逐段生成视频）
        tab_beat = QWidget()
        self._setup_beat_tab(tab_beat)
        self._tab_bar.addTab(" 卡点成片")
        self._stack.addWidget(tab_beat)

        # tab4：爆款仿制（复用 ViralClonePage 组件，与工作台对话框同一实现）
        tab_viral = QWidget()
        from gui.viral_clone_dialog import ViralClonePage
        self.viral_clone_page = ViralClonePage(tab_viral, self.main_window, show_close=False)  # noqa: E501
        self._tab_bar.addTab(" 爆款仿制")
        self._stack.addWidget(tab_viral)

        # tab5：模板成片（模板引擎：素材智能匹配 + 一键编译成片）
        tab_tpl = QWidget()
        self._setup_template_engine_tab(tab_tpl)
        self._tab_bar.addTab(" 模板成片")
        self._stack.addWidget(tab_tpl)

    # ════════════════════════════════════════════════════════════
    #  卡点成片 tab（独立控制器 + StepBeatView）
    # ════════════════════════════════════════════════════════════
    def _setup_beat_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(12)

        # 自包含控制器（充当 StepBeatView 的 main_page 角色）
        self.beat_controller = BeatMontageController(self.parent_widget, self.main_window)  # noqa: E501
        beat_view = StepBeatView(self.beat_controller)
        self.beat_controller.step_beat = beat_view
        root.addWidget(beat_view, 1)

    # ════════════════════════════════════════════════════════════════════════
    #  模板成片 tab（模板引擎：素材智能匹配 + 一键编译成片）
    # ════════════════════════════════════════════════════════════════════════
    def _setup_template_engine_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(10)

        sub = ElidedLabel("选择模板 → 智能匹配素材（CLIP 向量检索）→ 替换/确认素材 → 一键编译成片 → 预览下载", max_lines=1)  # noqa: E501
        sub.setObjectName("muted_text")
        root.addWidget(sub)

        # ── 上段：左右分割（左=模板列表+筛选，右=模板详情+素材匹配+生成）──────
        top_splitter = QSplitter(Qt.Horizontal)

        # 左：模板浏览器
        left_card = QFrame()
        left_card.setObjectName("card")
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(8)

        left_title = QLabel(" 模板浏览器")
        left_title.setStyleSheet("font-weight:bold;")
        left_lay.addWidget(left_title)

        # 筛选行
        filter_row = QHBoxLayout()
        self.tpl_edit_filter = QLineEdit()
        self.tpl_edit_filter.setPlaceholderText("按名称/分类过滤…")
        self.tpl_edit_filter.textChanged.connect(self._tpl_apply_filter)
        filter_row.addWidget(self.tpl_edit_filter, 1)
        self.tpl_btn_refresh = mdi_button("刷新", "refresh")
        self.tpl_btn_refresh.setObjectName("secondary_button")
        self.tpl_btn_refresh.clicked.connect(self._tpl_load_templates)
        filter_row.addWidget(self.tpl_btn_refresh)
        self.tpl_btn_import = mdi_button("导入", "import")
        self.tpl_btn_import.setObjectName("secondary_button")
        self.tpl_btn_import.setToolTip("导入剪映(.drt)/PR(.xml) 模板文件")
        self.tpl_btn_import.clicked.connect(self._tpl_open_import_dialog)
        filter_row.addWidget(self.tpl_btn_import)
        left_lay.addLayout(filter_row)

        # 模板列表
        self.tpl_list = QListWidget()
        self.tpl_list.currentRowChanged.connect(self._tpl_on_template_selected)
        left_lay.addWidget(self.tpl_list, 1)

        # 模板统计
        self.tpl_lbl_count = QLabel("加载中…")
        self.tpl_lbl_count.setObjectName("muted_text")
        left_lay.addWidget(self.tpl_lbl_count)

        top_splitter.addWidget(left_card)

        # 右：模板详情 + 素材匹配 + 生成
        right_card = QFrame()
        right_card.setObjectName("card")
        right_lay = QVBoxLayout(right_card)
        right_lay.setContentsMargins(16, 14, 16, 14)
        right_lay.setSpacing(8)

        # 模板信息
        self.tpl_info_text = QTextBrowser()
        self.tpl_info_text.setOpenExternalLinks(False)
        self.tpl_info_text.setMinimumHeight(80)
        self.tpl_info_text.setPlaceholderText("选择模板后查看详情")
        right_lay.addWidget(self.tpl_info_text)

        # Slot 素材匹配区
        slot_header = QHBoxLayout()
        slot_header.addWidget(QLabel(" Slot 素材（按模板标签自动匹配）"))
        slot_header.addStretch(1)
        self.tpl_btn_match = QPushButton("智能匹配素材")
        self.tpl_btn_match.setObjectName("secondary_button")
        self.tpl_btn_match.clicked.connect(self._tpl_start_match)
        slot_header.addWidget(self.tpl_btn_match)
        self.tpl_btn_match_all = QPushButton("一键全匹配")
        self.tpl_btn_match_all.setObjectName("secondary_button")
        self.tpl_btn_match_all.clicked.connect(self._tpl_start_match_all)
        slot_header.addWidget(self.tpl_btn_match_all)
        right_lay.addLayout(slot_header)

        self.tpl_slot_table = QTableWidget(0, 5)
        self.tpl_slot_table.setHorizontalHeaderLabels(["Slot", "类型", "标签", "已选素材", "操作"])
        self.tpl_slot_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tpl_slot_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tpl_slot_table.verticalHeader().setVisible(False)
        hdr = self.tpl_slot_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self.tpl_slot_table.setColumnWidth(4, 80)
        self.tpl_slot_table.setMaximumHeight(200)
        right_lay.addWidget(self.tpl_slot_table, 1)

        # 匹配进度
        self.tpl_match_progress = QProgressBar()
        self.tpl_match_progress.setRange(0, 100)
        self.tpl_match_progress.setValue(0)
        self.tpl_match_progress.setFixedHeight(14)
        self.tpl_match_progress.setVisible(False)
        right_lay.addWidget(self.tpl_match_progress)
        self.tpl_match_stage = QLabel("")
        self.tpl_match_stage.setObjectName("muted_text")
        right_lay.addWidget(self.tpl_match_stage)

        top_splitter.addWidget(right_card)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 7)
        top_splitter.setSizes([300, 700])
        root.addWidget(top_splitter, 1)

        # ── 参数/生成行 ────────────────────────────────────────────────
        action_frame = QFrame()
        action_frame.setObjectName("card")
        action_lay = QHBoxLayout(action_frame)
        action_lay.setContentsMargins(16, 14, 16, 14)
        action_lay.setSpacing(12)

        # 比例选择
        action_lay.addWidget(QLabel("比例"))
        self.tpl_combo_ratio = QComboBox()
        self.tpl_combo_ratio.addItems(list(RATIO_SIZES.keys()))
        action_lay.addWidget(self.tpl_combo_ratio)

        # 变体数量
        action_lay.addWidget(QLabel("变体"))
        self.tpl_spin_count = QSpinBox()
        self.tpl_spin_count.setRange(1, 10)
        self.tpl_spin_count.setValue(1)
        action_lay.addWidget(self.tpl_spin_count)

        action_lay.addStretch()

        # 生成按钮
        self.tpl_btn_generate = mdi_button(" 一键生成", "video")
        self.tpl_btn_generate.setObjectName("primary_button")
        self.tpl_btn_generate.setFixedHeight(36)
        self.tpl_btn_generate.clicked.connect(self._tpl_start_generate)
        action_lay.addWidget(self.tpl_btn_generate)

        # 预览按钮
        self.tpl_btn_preview = mdi_button(" 预览模板", "eye")
        self.tpl_btn_preview.setObjectName("secondary_button")
        self.tpl_btn_preview.setFixedHeight(36)
        self.tpl_btn_preview.clicked.connect(self._tpl_preview_template)
        action_lay.addWidget(self.tpl_btn_preview)

        root.addWidget(action_frame)

        # ── 生成进度 + 结果 ───────────────────────────────────────────
        self.tpl_progress_bar = QProgressBar()
        self.tpl_progress_bar.setRange(0, 100)
        self.tpl_progress_bar.setValue(0)
        self.tpl_progress_bar.setFixedHeight(14)
        self.tpl_progress_bar.setVisible(False)
        root.addWidget(self.tpl_progress_bar)

        self.tpl_stage_label = QLabel("")
        self.tpl_stage_label.setObjectName("muted_text")
        root.addWidget(self.tpl_stage_label)

        # 结果面板
        self.tpl_result_group = QGroupBox("成片结果")
        self.tpl_result_group.setVisible(False)
        trg_lay = QVBoxLayout(self.tpl_result_group)
        trg_lay.setSpacing(8)
        trg_lay.setContentsMargins(12, 12, 12, 12)

        self.tpl_video_widget = QVideoWidget()
        self.tpl_video_widget.setMinimumHeight(200)
        self.tpl_video_widget.setStyleSheet("background: #000; border-radius: 6px;")
        trg_lay.addWidget(self.tpl_video_widget)

        trg_row = QHBoxLayout()
        self.tpl_btn_download = mdi_button("下载成片", "download")
        self.tpl_btn_download.setObjectName("primary_button")
        self.tpl_btn_download.setEnabled(False)
        self.tpl_btn_download.clicked.connect(self._tpl_download_result)
        trg_row.addWidget(self.tpl_btn_download)

        self.tpl_btn_open_folder = mdi_button("打开输出目录", "folder")
        self.tpl_btn_open_folder.setObjectName("secondary_button")
        self.tpl_btn_open_folder.setEnabled(False)
        self.tpl_btn_open_folder.clicked.connect(self._tpl_open_output_dir)
        trg_row.addWidget(self.tpl_btn_open_folder)

        self.tpl_result_label = QLabel("")
        self.tpl_result_label.setObjectName("muted_text")
        trg_row.addWidget(self.tpl_result_label, 1)
        trg_lay.addLayout(trg_row)
        root.addWidget(self.tpl_result_group)

        # 首次加载模板
        self._tpl_load_templates()

    # ════════════════════════════════════════════════════════════════════════
    #  模板引擎：模板加载/选择
    # ════════════════════════════════════════════════════════════════════════
    def _tpl_load_templates(self):
        self.tpl_lbl_count.setText("正在加载模板…")
        w = self.track_worker(VideoTemplateLoadWorker())
        w.finished.connect(self._tpl_on_templates_loaded)
        w.error.connect(lambda e: self.tpl_lbl_count.setText(f"加载失败：{e}"))
        w.start()

    def _tpl_on_templates_loaded(self, templates):
        self._tpl_templates = templates or []
        self._tpl_rebuild_template_list()
        self.tpl_lbl_count.setText(f"共 {len(self._tpl_templates)} 个模板")

    def _tpl_rebuild_template_list(self):
        self.tpl_list.blockSignals(True)
        self.tpl_list.clear()
        text = self.tpl_edit_filter.text().strip().lower()
        shown = 0
        for idx, t in enumerate(self._tpl_templates):
            name = t.get("name") or f"模板-{idx}"
            cat = t.get("category") or ""
            ttype = t.get("type") or ""
            if text and text not in name.lower() and text not in cat.lower():
                continue
            display = f"[{cat or ttype or 'video'}] {name}"
            lw = QListWidgetItem(display)
            lw.setData(Qt.UserRole, idx)
            desc = t.get("description") or ""
            if desc:
                lw.setToolTip(desc[:200])
            self.tpl_list.addItem(lw)
            shown += 1
        self.tpl_lbl_count.setText(f"显示 {shown} / {len(self._tpl_templates)} 个模板")
        self.tpl_list.blockSignals(False)

    def _tpl_apply_filter(self, _text):
        self._tpl_rebuild_template_list()

    def _tpl_on_template_selected(self, row):
        if row < 0 or row >= len(self._tpl_templates):
            self._tpl_current_template = None
            self.tpl_info_text.setMarkdown("*选择模板后查看详情*")
            self._tpl_clear_slot_table()
            return
        self._tpl_current_template = self._tpl_templates[row]
        self._tpl_update_info_text()
        self._tpl_rebuild_slot_table()

    def _tpl_update_info_text(self):
        t = self._tpl_current_template
        if not t:
            return
        lines = [
            f"### {t.get('name', '')}",
            "",
            f"- **ID**: {t.get('id', '')}",
            f"- **类型**: {t.get('type', '')} / **分类**: {t.get('category', '')}",
        ]
        if t.get("description"):
            lines.append(f"- **描述**: {t['description']}")
        canvas = t.get("canvas") or {}
        if canvas:
            lines.append(f"- **画布**: {canvas.get('width','?')}×{canvas.get('height','?')} @ {canvas.get('fps','?')}fps")
        if t.get("duration"):
            lines.append(f"- **时长**: {t['duration']}s")
        params = t.get("params") or []
        if params:
            lines.append("")
            lines.append("**参数**:")
            for p in params:
                key = p.get("name") or p.get("key") or "-"
                label = p.get("label") or key
                ptype = p.get("type") or "-"
                default = p.get("default")
                default_txt = str(default)[:60] if default is not None else "-"
                lines.append(f"- {label}（{key}）: {ptype}，默认 {default_txt}")
        slots = self._tpl_extract_slots(t)
        if slots:
            lines.append("")
            lines.append(f"**Slot ({len(slots)} 个)**:")
            for s in slots:
                tags = ", ".join(s.get("tags", [])[:3])
                lines.append(f"- {s.get('slot','')} [{s.get('type','')}]: {tags}")
        self.tpl_info_text.setMarkdown("\n".join(lines))

    @staticmethod
    def _tpl_extract_slots(template):
        """从模板中提取 slot 列表。

        支持多种字段名：slots, slots_definition, material_slots, 或 storyboard/shots 推导。
        """
        if not template:
            return []
        # 直接使用 slots 字段
        for key in ("slots", "slots_definition", "material_slots"):
            slots = template.get(key) or []
            if slots:
                if isinstance(slots, list):
                    return slots
        # 从 storyboard / shots 推导
        storyboard = template.get("storyboard") or template.get("scenes") or template.get("shots") or template.get("script")
        if not storyboard:
            return []
        slots = []
        if isinstance(storyboard, list):
            for idx, shot in enumerate(storyboard):
                if isinstance(shot, dict):
                    tags = shot.get("tags") or shot.get("tag") or []
                    if isinstance(tags, str):
                        tags = [tags]
                    shot_type = shot.get("type") or shot.get("media_type") or "image"
                    visual = shot.get("visual") or shot.get("description") or ""
                    if visual and visual not in tags:
                        tags = list(tags) + [visual[:30]]
                    slots.append({
                        "slot": shot.get("slot") or shot.get("name") or f"slot_{idx}",
                        "type": shot_type,
                        "tags": tags,
                        "required": shot.get("required", True),
                    })
        return slots

    # ════════════════════════════════════════════════════════════════════════
    #  模板引擎：Slot 素材匹配
    # ════════════════════════════════════════════════════════════════════════
    def _tpl_rebuild_slot_table(self):
        t = self._tpl_current_template
        self._tpl_matched_slots = {}
        self._tpl_selected_materials = {}
        self._tpl_clear_slot_table()
        if not t:
            return
        slots = self._tpl_extract_slots(t)
        if not slots:
            self.tpl_slot_table.setRowCount(0)
            return
        self.tpl_slot_table.setRowCount(len(slots))
        for row, slot in enumerate(slots):
            self.tpl_slot_table.setItem(row, 0, QTableWidgetItem(slot.get("slot", f"slot_{row}")))
            self.tpl_slot_table.setItem(row, 1, QTableWidgetItem(slot.get("type", "")))
            tags = slot.get("tags", [])
            tag_text = ", ".join(str(t) for t in tags[:5]) if tags else ""
            item_tags = QTableWidgetItem(tag_text)
            item_tags.setToolTip(tag_text)
            self.tpl_slot_table.setItem(row, 2, item_tags)
            item_selected = QTableWidgetItem("（未匹配）")
            item_selected.setToolTip("点击「智能匹配素材」或「选择素材」来绑定此 slot 的素材")
            self.tpl_slot_table.setItem(row, 3, item_selected)
            # 操作按钮
            btn_widget = QWidget()
            btn_lay = QHBoxLayout(btn_widget)
            btn_lay.setContentsMargins(2, 2, 2, 2)
            btn_lay.setSpacing(2)
            btn_choose = QPushButton("选择")
            btn_choose.setObjectName("secondary_button")
            btn_choose.setFixedWidth(40)
            btn_choose.clicked.connect(lambda _=False, r=row: self._tpl_choose_material_for_slot(r))
            btn_lay.addWidget(btn_choose)
            self.tpl_slot_table.setCellWidget(row, 4, btn_widget)
            self._tpl_selected_materials[slot.get("slot", f"slot_{row}")] = None

    def _tpl_clear_slot_table(self):
        self.tpl_slot_table.setRowCount(0)

    def _tpl_start_match(self):
        """对当前选中模板的所有 slot 执行智能匹配。"""
        t = self._tpl_current_template
        if not t:
            self.show_warning("请先选择一个模板。")
            return
        slots = self._tpl_extract_slots(t)
        if not slots:
            self.show_warning("该模板没有可匹配的 slot。")
            return
        self.tpl_match_progress.setVisible(True)
        self.tpl_match_progress.setValue(0)
        self.tpl_match_stage.setText("开始智能匹配素材…")
        self.tpl_btn_match.setEnabled(False)
        self.tpl_btn_match_all.setEnabled(False)
        w = _TemplateMatchWorker(slots, top_k=5)
        w.progress.connect(self._tpl_on_match_progress)
        w.finished.connect(self._tpl_on_match_done)
        w.error.connect(lambda e: self._tpl_on_match_error(e))
        self.track_worker(w)
        w.start()

    def _tpl_start_match_all(self):
        self._tpl_start_match()

    def _tpl_on_match_progress(self, progress, stage):
        self.tpl_match_progress.setValue(progress)
        self.tpl_match_stage.setText(stage)

    def _tpl_on_match_done(self, result):
        self.tpl_btn_match.setEnabled(True)
        self.tpl_btn_match_all.setEnabled(True)
        self.tpl_match_stage.setText("匹配完成")
        if not result:
            self.show_warning("未匹配到任何素材，请检查素材库是否有相关素材。")
            self.tpl_match_progress.setVisible(False)
            return
        self._tpl_matched_slots = result
        # 自动为每个 slot 选择第一个候选
        for slot_key, candidates in result.items():
            if candidates:
                best = candidates[0] if isinstance(candidates, list) else candidates
                if isinstance(best, dict):
                    mid = best.get("material_id") or best.get("id") or best.get("path") or ""
                else:
                    mid = str(best)
                self._tpl_selected_materials[slot_key] = str(mid)
        # 更新表格显示
        self._tpl_refresh_slot_display()
        self.tpl_match_progress.setValue(100)
        QTimer.singleShot(2000, lambda: self.tpl_match_progress.setVisible(False))

    def _tpl_on_match_error(self, err):
        self.tpl_btn_match.setEnabled(True)
        self.tpl_btn_match_all.setEnabled(True)
        self.tpl_match_stage.setText(f"匹配失败：{err}")
        self.tpl_match_progress.setVisible(False)
        self.show_error(f"智能匹配失败：{err}", "错误")

    def _tpl_refresh_slot_display(self):
        """刷新 slot 表格中已选素材的显示。"""
        t = self._tpl_current_template
        if not t:
            return
        slots = self._tpl_extract_slots(t)
        for row, slot in enumerate(slots):
            slot_key = slot.get("slot", f"slot_{row}")
            mid = self._tpl_selected_materials.get(slot_key)
            candidates = self._tpl_matched_slots.get(slot_key, [])
            if mid:
                display = f"✓ {str(mid)[:40]}"
                if candidates and isinstance(candidates, list):
                    for c in candidates:
                        if isinstance(c, dict) and str(c.get("material_id") or c.get("id") or "") == str(mid):
                            score = c.get("score", "")
                            if score:
                                display += f" (score={score})"
                            break
                self.tpl_slot_table.item(row, 3).setText(display)
                self.tpl_slot_table.item(row, 3).setToolTip(f"已选素材: {mid}")
            else:
                self.tpl_slot_table.item(row, 3).setText("（未匹配）")
                self.tpl_slot_table.item(row, 3).setToolTip("")

    def _tpl_choose_material_for_slot(self, row):
        """手动为指定 slot 选择素材（从素材库中选）。"""
        t = self._tpl_current_template
        if not t:
            return
        slots = self._tpl_extract_slots(t)
        if row < 0 or row >= len(slots):
            return
        slot = slots[row]
        slot_key = slot.get("slot", f"slot_{row}")
        candidates = self._tpl_matched_slots.get(slot_key, [])
        # 从候选列表中选择，或打开素材库
        if candidates and isinstance(candidates, list):
            items = []
            for c in candidates:
                if isinstance(c, dict):
                    mid = c.get("material_id") or c.get("id") or c.get("path") or ""
                    name = c.get("name") or c.get("filename") or str(mid)[:40]
                    score = c.get("score", "")
                    label = f"{name}" + (f" (score={score})" if score else "")
                    items.append((label, str(mid)))
            if items:
                dlg = QDialog(self.parent_widget)
                dlg.setWindowTitle(f"选择素材 - {slot_key}")
                dlg.setMinimumWidth(360)
                dlg.setMinimumHeight(280)
                lay = QVBoxLayout(dlg)
                lst = QListWidget()
                for label, mid in items:
                    lw = QListWidgetItem(label)
                    lw.setData(Qt.UserRole, mid)
                    lst.addItem(lw)
                lay.addWidget(lst)
                btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                btns.accepted.connect(dlg.accept)
                btns.rejected.connect(dlg.reject)
                lay.addWidget(btns)
                if dlg.exec() == QDialog.Accepted:
                    selected = lst.currentItem()
                    if selected:
                        self._tpl_selected_materials[slot_key] = selected.data(Qt.UserRole)
                        self._tpl_refresh_slot_display()
                return
        # 无候选，打开素材检索页
        self.show_info(f"请在「素材检索」页选择素材后点击「一键成片」带入此 slot ({slot_key})。\n\n或先点击「智能匹配素材」自动匹配。")

    # ════════════════════════════════════════════════════════════════════════
    #  模板引擎：预览/生成
    # ════════════════════════════════════════════════════════════════════════
    def _tpl_preview_template(self):
        """渲染模板预览视频（走 TemplatePreviewWorker）。"""
        t = self._tpl_current_template
        if not t:
            self.show_warning("请先选择一个模板。")
            return
        self.tpl_stage_label.setText("正在生成预览…")
        self.tpl_progress_bar.setVisible(True)
        self.tpl_progress_bar.setValue(0)
        params = self._collect_template_params()
        w = TemplatePreviewWorker(t.get("id"), params, self.tpl_combo_ratio.currentText())
        w.progress.connect(lambda p: self.tpl_progress_bar.setValue(p))
        w.phase.connect(lambda s: self.tpl_stage_label.setText(s))
        w.finished.connect(self._tpl_on_preview_ready)
        w.error.connect(lambda e: (
            self.tpl_stage_label.setText("预览失败"),
            self.show_error(f"模板预览失败：{e}", "错误"),
        ))
        self.track_worker(w)
        w.start()

    def _tpl_on_preview_ready(self, path):
        self.tpl_stage_label.setText("预览生成完成")
        self.tpl_progress_bar.setValue(100)
        self._play_preview(path)

    def _tpl_start_generate(self):
        """提交模板成片生成任务。"""
        t = self._tpl_current_template
        if not t:
            self.show_warning("请先选择一个模板。")
            return
        # 检查是否所有 slot 都已绑定素材
        slots = self._tpl_extract_slots(t)
        unbound = []
        slot_materials = {}
        for slot in slots:
            slot_key = slot.get("slot", "")
            mid = self._tpl_selected_materials.get(slot_key)
            if mid:
                slot_materials[slot_key] = str(mid)
            elif slot.get("required", True):
                unbound.append(slot_key)
        if unbound:
            self.show_warning(f"以下 slot 尚未绑定素材：{', '.join(unbound)}\n请先点击「智能匹配素材」或手动选择素材。")
            return
        params = self._collect_template_params()
        ratio = self.tpl_combo_ratio.currentText()
        self.tpl_progress_bar.setVisible(True)
        self.tpl_progress_bar.setValue(0)
        self.tpl_stage_label.setText("正在提交模板成片任务…")
        self.tpl_btn_generate.setEnabled(False)
        self.tpl_btn_preview.setEnabled(False)

        self._tpl_generate_worker = _TemplateGenerateWorker(
            t.get("id"), slot_materials, params=params, ratio=ratio,
        )
        self._tpl_generate_worker.progress.connect(self.tpl_progress_bar.setValue)
        self._tpl_generate_worker.phase.connect(self.tpl_stage_label.setText)
        self._tpl_generate_worker.status_changed.connect(lambda s: None)
        self._tpl_generate_worker.completed.connect(self._tpl_on_generate_completed)
        self._tpl_generate_worker.failed.connect(self._tpl_on_generate_failed)
        self.track_worker(self._tpl_generate_worker)
        self._tpl_generate_worker.start()

    def _tpl_on_generate_completed(self, task_data):
        self.tpl_progress_bar.setValue(100)
        self.tpl_stage_label.setText("成片生成完成！")
        self.tpl_btn_generate.setEnabled(True)
        self.tpl_btn_preview.setEnabled(True)
        self._tpl_show_result(task_data)

    def _tpl_on_generate_failed(self, error):
        self.tpl_stage_label.setText(f"生成失败：{error}")
        self.tpl_btn_generate.setEnabled(True)
        self.tpl_btn_preview.setEnabled(True)
        self.show_error(f"模板成片生成失败：{error}", "错误")

    def _tpl_show_result(self, task_data):
        result = task_data.get("result") or {}
        video_url = (
            result.get("video_url")
            or result.get("output_url")
            or result.get("url")
            or result.get("file_url")
            or task_data.get("video_url")
            or task_data.get("output_url")
            or ""
        )
        if not video_url:
            self.tpl_result_label.setText("完成但未返回视频地址")
            return
        self._tpl_video_url = video_url
        self.tpl_result_group.setVisible(True)
        self.tpl_btn_download.setEnabled(True)
        self.tpl_btn_open_folder.setEnabled(True)
        self.tpl_result_label.setText(f"视频地址: {video_url}")
        self._tpl_play_video(video_url)

    def _tpl_play_video(self, url):
        if self._tpl_player is None:
            self._tpl_player = QMediaPlayer(self)
            self._tpl_audio_output = QAudioOutput(self)
            self._tpl_audio_output.setVolume(80)
            self._tpl_player.setAudioOutput(self._tpl_audio_output)
            self._tpl_player.videoOutputChanged.connect(self._tpl_on_video_output_changed)
        self._tpl_player.setSource(QUrl(url))
        self._tpl_player.play()

    def _tpl_on_video_output_changed(self, video_output):
        if video_output is not None:
            video_output.setSurface(self.tpl_video_widget.videoSurface())

    def _tpl_download_result(self):
        url = self._tpl_video_url
        if not url:
            return
        from utils import scheduled_task_client as stc
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(FINAL_OUTPUT_DIR, f"template_montage_{ts}.mp4")
        try:
            stc.download_result_file(url, local_path)
            self.show_info(f"成片已下载到：\n{local_path}")
        except Exception as e:
            self.show_error(f"下载失败：{e}", "错误")

    def _tpl_open_output_dir(self):
        if os.path.isdir(FINAL_OUTPUT_DIR) and os.name == "nt":
            os.startfile(FINAL_OUTPUT_DIR)

    def _tpl_open_import_dialog(self):
        """打开模板导入对话框，支持剪映(.drt)/PR(.xml) 文件。"""
        file_path, _ = pick_file(
            self.parent_widget,
            "选择模板文件",
            "",
            "模板文件 (*.drt *.xml *.json);;所有文件 (*.*)",
        )
        if not file_path:
            return
        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("导入模板")
        dlg.setMinimumWidth(420)
        form = QFormLayout(dlg)
        name_edit = QLineEdit(os.path.basename(file_path))
        form.addRow("模板名称", name_edit)
        category_combo = QComboBox()
        category_combo.setEditable(True)
        category_combo.addItems(["ecommerce", "brand", "tutorial", "vlog", "gaming", "education", "other"])
        category_combo.setCurrentText("ecommerce")
        form.addRow("分类", category_combo)
        desc_edit = QTextEdit()
        desc_edit.setFixedHeight(60)
        desc_edit.setPlaceholderText("模板描述（可选）")
        form.addRow("描述", desc_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("开始导入")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        name = name_edit.text().strip()
        category = category_combo.currentText().strip()
        description = desc_edit.toPlainText().strip()
        self._tpl_do_import(file_path, name, category, description)

    def _tpl_do_import(self, file_path, name, category, description):
        self.tpl_lbl_count.setText(f"正在导入 {os.path.basename(file_path)}…")
        self.tpl_btn_import.setEnabled(False)
        w = _TemplateImportWorker(file_path, name, category, description)
        w.finished.connect(self._tpl_on_import_done)
        w.error.connect(self._tpl_on_import_error)
        self.track_worker(w)
        w.start()

    def _tpl_on_import_done(self, result):
        self.tpl_btn_import.setEnabled(True)
        if result:
            new_id = result.get("id") or result.get("template_id") or ""
            self.tpl_lbl_count.setText(f"导入成功：{result.get('name', new_id)}")
            self._tpl_load_templates()
            self.show_info(f"模板导入成功！\n\nID: {new_id}\n名称: {result.get('name', '')}")
        else:
            self.tpl_lbl_count.setText("导入失败")
            self.show_warning("模板导入失败，请检查文件格式是否正确。")

    def _tpl_on_import_error(self, err):
        self.tpl_btn_import.setEnabled(True)
        self.tpl_lbl_count.setText(f"导入失败：{err}")
        self.show_error(f"模板导入失败：{err}", "错误")

    # ════════════════════════════════════════════════════════════════════════
    #  产品成片 tab（原有界面，整体挂到 container）
    # ════════════════════════════════════════════════════════════════════════
    def _setup_product_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(12)

        sub = ElidedLabel("选择产品（必选，任务起点）→ 可选设置/自动匹配素材 → 设置条数与时长 → 开始执行。复杂剪辑请用「智能混剪」。", max_lines=1)  # noqa: E501
        sub.setObjectName("muted_text")
        root.addWidget(sub)

        # ── 上段：左右分割（左=产品，右=可选设置）──────────────────────────
        top_splitter = QSplitter(Qt.Horizontal)

        # 左：产品选择 + 性能/卖点
        left_card = QFrame()
        left_card.setObjectName("card")
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(10)

        left_title = QLabel(" 产品选择（必选）")
        left_title.setStyleSheet("font-weight:bold;")
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

        # 模板库（成片模板，独立于动效模板；header 行内放 刷新，每个模板后放预览播放）
        tmpl_header = QHBoxLayout()
        tmpl_header.addWidget(QLabel(" 成片模板"))
        tmpl_header.addStretch(1)
        self.btn_refresh_templates = mdi_button("刷新", "refresh")
        self.btn_refresh_templates.setObjectName("secondary_button")
        self.btn_refresh_templates.clicked.connect(self._load_templates)
        tmpl_header.addWidget(self.btn_refresh_templates)
        left_lay.addLayout(tmpl_header)
        self.list_templates = QTableWidget(0, 2)
        self.list_templates.setHorizontalHeaderLabels(["模板", "预览"])
        self.list_templates.verticalHeader().setVisible(False)
        self.list_templates.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_templates.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_templates.currentItemChanged.connect(self._on_template_item_changed)
        self.list_templates.setMaximumHeight(220)
        self.list_templates.setColumnWidth(1, 60)
        self.list_templates.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # noqa: E501
        self.list_templates.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)  # noqa: E501
        left_lay.addWidget(self.list_templates)

        top_splitter.addWidget(left_card)

        # 右：概述 + 输出结果
        right_card = QFrame()
        right_card.setObjectName("card")
        right_lay = QVBoxLayout(right_card)
        right_lay.setContentsMargins(16, 14, 16, 14)
        right_lay.setSpacing(8)

        # 模板参数按内容分组为 Tab，避免全部堆在一个长布局里
        self._pbar, self._pstack, self.tabs_params = setup_tab_widget(left_lay, 1)

        # ── Tab1 素材：镜头素材目录 / 素材列表 ──
        tab_material = QWidget()
        lay_material = QVBoxLayout(tab_material)
        lay_material.setContentsMargins(8, 8, 8, 8)
        lay_material.setSpacing(8)
        self.in_folder = self._file_row(lay_material, "镜头素材目录（留空=按产品自动匹配）",
                                        self._browse_folder, folder=True,
                                        placeholder="留空则按产品自动从素材库匹配")
        mat_header = QHBoxLayout()
        mat_header.addWidget(QLabel(" 素材列表（来自素材检索，可选）"))
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
        self._pbar.addTab("素材")
        self._pstack.addWidget(tab_material)

        # ── Tab2 文案：字幕文案 / 配音文案 ──
        tab_copy = QWidget()
        lay_copy = QVBoxLayout(tab_copy)
        lay_copy.setContentsMargins(8, 8, 8, 8)
        lay_copy.setSpacing(8)
        lay_copy.addWidget(QLabel("字幕文案 / 配音文案(可选)"))
        self.in_subtitle = QTextEdit()
        self.in_subtitle.setFixedHeight(90)
        self.in_subtitle.setPlaceholderText("粘贴文案；按句均匀分布为字幕，并可一键 TTS 配音。留空则不加。")
        lay_copy.addWidget(self.in_subtitle)
        lay_copy.addStretch(1)
        self._pbar.addTab("文案")
        self._pstack.addWidget(tab_copy)

        # ── Tab3 音频：配音音频 / TTS 音色 ──
        tab_audio = QWidget()
        lay_audio = QVBoxLayout(tab_audio)
        lay_audio.setContentsMargins(8, 8, 8, 8)
        lay_audio.setSpacing(8)
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
        self._pbar.addTab("音频")
        self._pstack.addWidget(tab_audio)

        # ── Tab4 开场封面：开场视频 + 封面 ──
        tab_cover = QWidget()
        lay_cover = QVBoxLayout(tab_cover)
        lay_cover.setContentsMargins(8, 8, 8, 8)
        lay_cover.setSpacing(8)
        self.in_intro = self._file_row(lay_cover, "开场视频(可选)", self._browse_intro,
                                       placeholder="片头开场视频，拼在最前面")
        intro_row = QHBoxLayout()
        intro_row.addStretch()
        self.btn_mg_intro = mdi_button("用动态标题生成开场(MG)", "film")
        self.btn_mg_intro.setObjectName("secondary_button")
        self.btn_mg_intro.clicked.connect(self._gen_mg_intro)
        intro_row.addWidget(self.btn_mg_intro)
        lay_cover.addLayout(intro_row)
        self.in_cover = self._file_row(lay_cover, "封面(可选)", self._browse_cover,
                                       placeholder="片头封面图，显示 2 秒")
        lay_cover.addStretch(1)
        self._pbar.addTab("开场封面")
        self._pstack.addWidget(tab_cover)

        left_lay.addWidget(QLabel(" 模板参数"))

        top_splitter.addWidget(right_card)
        # 左右比例 3:7（左=产品/模板/模板参数，右=概述/输出/日志）
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 7)
        top_splitter.setSizes([300, 700])
        root.addWidget(top_splitter, 2)

        action_frame = QFrame()
        action_frame.setObjectName("card")
        action_layout = QVBoxLayout(action_frame)
        action_layout.setSpacing(10)
        action_layout.setContentsMargins(16, 14, 16, 14)  # noqa: E501

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("变体数量"))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 10)
        self.spin_count.setValue(5)  # noqa: E501
        self.spin_count.setToolTip("服务端生成 N 个变体（不同风格/节奏），用进化机制选最优的 1 个输出。\n数值越大选择空间越大但耗时越长。")  # noqa: E501
        row1.addWidget(self.spin_count)
        row1.addStretch()
        action_layout.addLayout(row1)
        # 视频总时长/每张时长/比例由模板定义，不在客户端暴露设置
        self.spin_total_dur = 0.0
        self.spin_dur = 3.0
        self.combo_ratio = '9:16'

        row2 = QHBoxLayout()
        self.chk_autocheck = QCheckBox("成片后自动视频评价预测")
        self.chk_autocheck.setChecked(True)
        row2.addWidget(self.chk_autocheck)
        row2.addWidget(QLabel("平台"))
        self.combo_predict_platform = QComboBox()
        self.combo_predict_platform.addItems(PLATFORMS)  # noqa: E501
        self.combo_predict_platform.setFixedWidth(96)
        row2.addWidget(self.combo_predict_platform)
        row2.addStretch()
        self.btn_make = mdi_button(" 开始执行", "video")
        self.btn_make.setObjectName("primary_button")  # noqa: E501
        self.btn_make.setFixedHeight(36)
        self.btn_make.clicked.connect(self._make)
        row2.addWidget(self.btn_make)
        self.btn_add_task = QPushButton(" 添加为定时任务")
        self.btn_add_task.setFixedHeight(36)
        self.btn_add_task.setToolTip("把当前配置提交给服务端，由服务端定时执行（可在「定时任务」页监控状态）")
        self.btn_add_task.clicked.connect(self._add_scheduled_task)
        row2.addWidget(self.btn_add_task)
        action_layout.addLayout(row2)
        root.addWidget(action_frame)


        # ── 模板概述（不含分镜脚本信息，抽取脚本中的素材/口播/音频）────
        self.overview_group = QGroupBox("概述")
        ov_lay = QVBoxLayout(self.overview_group)
        ov_lay.setSpacing(8)
        ov_lay.setContentsMargins(8, 8, 8, 8)  # noqa: E501
        self.overview_scroll = QScrollArea()
        self.overview_scroll.setWidgetResizable(True)
        self.overview_scroll.setFrameShape(QFrame.NoFrame)
        self.overview_container = QWidget()
        self.overview_form = QFormLayout(self.overview_container)
        self.overview_form.setSpacing(8)
        self.overview_scroll.setWidget(self.overview_container)
        ov_lay.addWidget(self.overview_scroll)
        right_lay.addWidget(self.overview_group)

        # ── 输出结果（占主要空间，供预览）─────────────────────────────────
        out_left = QWidget()
        ol_lay = QVBoxLayout(out_left)
        ol_lay.setContentsMargins(0, 0, 0, 0)
        ol_lay.setSpacing(6)  # noqa: E501
        ol_lay.addWidget(QLabel(" 输出结果"))
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

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)  # noqa: E501
        self.progress_bar.setFixedHeight(16)
        ol_lay.addWidget(self.progress_bar)
        self.stage_label = QLabel("")
        self.stage_label.setObjectName("muted_text")
        ol_lay.addWidget(self.stage_label)

        # 评分预测状态行（放在输出结果卡片内，避免底部空行）
        score_widget = QWidget()
        score_row = QHBoxLayout(score_widget)
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(6)  # noqa: E501
        self.score_label = QLabel("")
        self.score_label.setObjectName("muted_text")
        self.score_label.setWordWrap(True)
        score_row.addWidget(self.score_label, 1)
        self.btn_detail = mdi_button("查看详情/建议", "right")
        self.btn_detail.setObjectName("secondary_button")
        self.btn_detail.clicked.connect(self._open_detail)
        self.btn_detail.setVisible(False)
        score_row.addWidget(self.btn_detail)
        self.score_widget = score_widget
        self.score_widget.setVisible(False)
        ol_lay.addWidget(score_widget)
        right_lay.addWidget(out_left, 1)

        # ── 执行日志：放最下面，固定小高度，默认折叠（空间让给输出结果）──
        self.btn_toggle_log = QPushButton(" 执行日志（点击展开）")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setObjectName("secondary_button")
        self.btn_toggle_log.clicked.connect(self._toggle_log_visible)
        right_lay.addWidget(self.btn_toggle_log)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background: #1a1a2e; color: #c8d6e5; font-size: 12px; border-radius: 6px;")  # noqa: E501
        self.log_box.setFixedHeight(120)   # 展开后也只占底部小高度
        self.log_box.setVisible(False)     # 默认折叠
        right_lay.addWidget(self.log_box)

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
        self.btn_toggle_log.setText(" 执行日志（点击折叠）" if show else " 执行日志（点击展开）")

    # ════════════════════════════════════════════════════════════════════════
    #  脚本成片 tab（选分镜脚本 → 提交服务端成片）
    # ════════════════════════════════════════════════════════════════════════
    def _setup_script_tab(self, container):
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(10)

        sub = ElidedLabel("选择一个已保存的分镜脚本（含素材+文案），直接提交服务端成片。脚本在「分镜脚本」页保存为 JSON 格式生成。", max_lines=1)  # noqa: E501
        sub.setObjectName("muted_text")
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
        root.addWidget(QLabel(" 脚本预览"))
        self.script_preview = QTextBrowser()
        self.script_preview.setOpenExternalLinks(False)
        self.script_preview.setMinimumHeight(220)
        self.script_preview.setPlaceholderText("选择上方脚本后，这里显示镜头表（镜号|时长|画面|文案|素材路径）")
        root.addWidget(self.script_preview, 1)

        # ── 设置行 ─────────────────────────────────────────────────────────
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("比例"))
        self.script_combo_ratio = QComboBox()
        self.script_combo_ratio.addItems(list(RATIO_SIZES.keys()))  # noqa: E501
        opt_row.addWidget(self.script_combo_ratio)
        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("变体数量"))
        self.script_spin_count = QSpinBox()
        self.script_spin_count.setRange(1, 10)
        self.script_spin_count.setValue(5)  # noqa: E501
        self.script_spin_count.setToolTip("服务端生成 N 个变体（不同风格/节奏），进化机制选最优 1 个输出")
        opt_row.addWidget(self.script_spin_count)
        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("音色"))
        self.script_combo_voice = SearchableComboBox(placeholder="默认音色")
        self.script_combo_voice.setMinimumWidth(120)
        opt_row.addWidget(self.script_combo_voice)
        opt_row.addSpacing(12)
        opt_row.addWidget(QLabel("平台"))
        self.script_combo_platform = QComboBox()
        self.script_combo_platform.addItems(PLATFORMS)  # noqa: E501
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
        self.btn_script_make = mdi_button(" 开始执行", "video")
        self.btn_script_make.setObjectName("primary_button")
        self.btn_script_make.setFixedHeight(36)
        self.btn_script_make.clicked.connect(lambda: self._submit_script(immediate=True))  # noqa: E501
        btn_row.addWidget(self.btn_script_make)
        self.btn_script_add_task = QPushButton(" 添加为定时任务")
        self.btn_script_add_task.setFixedHeight(36)
        self.btn_script_add_task.clicked.connect(self._add_script_scheduled_task)
        btn_row.addWidget(self.btn_script_add_task)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── 状态/日志 ──────────────────────────────────────────────────────
        self.script_status = QLabel("")
        self.script_status.setObjectName("muted_text")
        root.addWidget(self.script_status)

        # ── 内嵌进度条 ────────────────────────────────────────────────────
        self.script_progress_bar = QProgressBar()
        self.script_progress_bar.setRange(0, 100)
        self.script_progress_bar.setValue(0)
        self.script_progress_bar.setFixedHeight(14)
        self.script_progress_bar.setVisible(False)
        root.addWidget(self.script_progress_bar)
        self.script_stage_label = QLabel("")
        self.script_stage_label.setObjectName("muted_text")
        root.addWidget(self.script_stage_label)

        # ── 结果面板（视频播放 + 下载）─────────────────────────────────────
        self.script_result_group = QGroupBox("成片结果")
        self.script_result_group.setVisible(False)
        srg_lay = QVBoxLayout(self.script_result_group)
        srg_lay.setSpacing(8)
        srg_lay.setContentsMargins(12, 12, 12, 12)
        # 视频播放器
        self.script_video_widget = QVideoWidget()
        self.script_video_widget.setMinimumHeight(240)
        self.script_video_widget.setStyleSheet("background: #000; border-radius: 6px;")
        srg_lay.addWidget(self.script_video_widget)
        # 操作行
        srg_row = QHBoxLayout()
        self.script_btn_download = mdi_button("下载成片", "download")
        self.script_btn_download.setObjectName("primary_button")
        self.script_btn_download.setEnabled(False)
        self.script_btn_download.clicked.connect(self._download_script_result)
        srg_row.addWidget(self.script_btn_download)
        self.script_btn_open_folder = mdi_button("打开输出目录", "folder")
        self.script_btn_open_folder.setObjectName("secondary_button")
        self.script_btn_open_folder.setEnabled(False)
        self.script_btn_open_folder.clicked.connect(self._open_script_output_dir)
        srg_row.addWidget(self.script_btn_open_folder)
        self.script_result_label = QLabel("")
        self.script_result_label.setObjectName("muted_text")
        srg_row.addWidget(self.script_result_label, 1)
        srg_lay.addLayout(srg_row)
        root.addWidget(self.script_result_group)

        # 首次加载脚本列表 + 音色
        self._populate_scripts()
        self._populate_script_voices()

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
                "## 注意： 服务端暂无分镜脚本\n\n"
                "在「分镜脚本创作」页生成脚本并保存（会自动上传服务端）后，回到本页点「刷新」即可看到。")
            self.script_status.setText("服务端暂无脚本")

    def _on_scripts_load_error(self, msg):
        log.warning(f"从服务端加载脚本失败，回退本地扫描: {msg}")
        self.script_status.setText(f"注意： 服务端脚本加载失败：{msg}（已回退本地扫描）")
        scripts = scan_storyboard_scripts(KNOWLEDGE_MEDIA_DIR)
        self.combo_script.blockSignals(True)
        self.combo_script.clear()
        self.combo_script.addItem("— 请选择脚本 —", None)
        for s in scripts:
            label = f"[{s['topic']}] {s['name']}（{s['shot_count']}镜/{s['total_duration']}s）"  # noqa: E501
            self.combo_script.addItem(label, s)
        self.combo_script.setCurrentIndex(0)
        self.combo_script.blockSignals(False)
        if scripts:
            self.script_preview.setMarkdown("*选择上方脚本查看预览*")
            self.script_status.setText(f"服务端不可用，已回退本地（{len(scripts)} 个脚本）")
        else:
            self.script_preview.setMarkdown("## 注意： 暂无可用的分镜脚本\n\n服务端不可用且本地也未找到脚本。")
            self.script_status.setText("未找到脚本（服务端不可用）")

    def _current_script(self):
        """返回当前选中的完整脚本 dict（无则 None）。"""
        if getattr(self, "_current_script_data", None):
            return self._current_script_data
        return self.combo_script.currentData() if hasattr(self, "combo_script") else None  # noqa: E501

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
        self.script_preview.setMarkdown(f"注意： 脚本加载失败：{err}")

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
            f"- **画幅**：{s.get('ratio','9:16')}　**总时长**：{s.get('total_duration',0)}s　**镜头数**：{s.get('shot_count',0)}",  # noqa: E501
            "",
            "| 镜号 | 时长 | 画面描述 | 旁白文案 | 素材路径 |",
            "|:---:|:---:|---|---|---|",
        ]
        for sh in shots:
            vis = str(sh.get("visual", "")).replace("|", "｜").replace("\n", " ").strip()
            nar = str(sh.get("audio", "") or sh.get("narration", "")).replace("|", "｜").replace("\n", " ").strip()  # noqa: E501
            mat = str(sh.get("material_path", "")).replace("|", "｜").strip()
            lines.append(f"| {sh.get('index','')} | {sh.get('duration','')}s | {vis} | {nar or '—'} | {mat or '—'} |")  # noqa: E501
        return "\n".join(lines)

    def _submit_script(self, immediate, schedule=None, title=""):
        """提交脚本成片任务到服务端（task_type=storyboard_montage）。

        immediate=True: 提交后轮询进度并在本页展示结果（不再跳转成片任务页）
        immediate=False: 提交定时任务，仍走原逻辑
        """
        from utils import scheduled_task_client as stc
        from utils.thread_worker import TaskWorker as Worker

        s = self._current_script()
        if not s:
            self.show_warning("请先选择一个脚本。")
            return
        params = collect_script_params(
            script=s,
            count=self.script_spin_count.value(),
            ratio=self.script_combo_ratio.currentText(),
            platform=self.script_combo_platform.currentText(),
            autocheck=self.script_chk_autocheck.isChecked(),
        )
        # 附加音色参数
        voice_ref = self.script_combo_voice.currentData() or ""
        if voice_ref:
            params["voice_reference_path"] = voice_ref
        task_title = title or f"{s.get('topic','')}-{s.get('name','')}-脚本成片"

        self.btn_script_make.setEnabled(False)
        self.btn_script_add_task.setEnabled(False)
        self.script_status.setText("正在提交到服务端…" if immediate else "正在提交定时任务…")
        self.script_progress_bar.setVisible(False)
        self.script_stage_label.setText("")
        self.script_result_group.setVisible(False)

        def _do():
            return stc.create_task("storyboard_montage", task_title, params, schedule=schedule)

        worker = Worker(_do)

        def _ok(tid):
            self.btn_script_make.setEnabled(True)
            self.btn_script_add_task.setEnabled(True)
            if tid:
                self._script_current_task_id = tid
                if immediate:
                    self.script_status.setText(f" 已提交服务端，任务 ID={tid}")
                    self._start_script_polling(tid)
                else:
                    self.script_status.setText(f" 定时任务已提交，任务 ID={tid}")
                    self.show_info(f"定时任务已提交服务端（ID={tid}）。\n\n服务端将按计划定时执行，可在「成片任务」页监控。")
            else:
                self.script_status.setText("注意： 提交失败")
                self.show_warning("提交服务端失败，请确认服务端在线后重试。")

        def _err(e):
            self.btn_script_make.setEnabled(True)
            self.btn_script_add_task.setEnabled(True)
            self.script_status.setText("注意： 提交异常")
            self.show_error(f"提交异常：{e}", "错误")

        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self.track_worker(worker)
        worker.start()

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
        time_edit = QTimeEdit()
        time_edit.setTime(_dt.now().time().replace(second=0, microsecond=0))  # noqa: E501
        time_edit.setDisplayFormat("HH:mm")
        form.addRow("执行时刻", time_edit)
        date_edit = QLineEdit(_dt.now().strftime("%Y-%m-%d"))
        date_edit.setPlaceholderText("YYYY-MM-DD")  # noqa: E501
        form.addRow("执行日期", date_edit)
        interval_spin = QSpinBox()
        interval_spin.setRange(1, 168)
        interval_spin.setValue(24)  # noqa: E501
        form.addRow("间隔小时", interval_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
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
        self._submit_script(immediate=False, schedule=schedule, title=name_edit.text().strip())  # noqa: E501

    # ════════════════════════════════════════════════════════════════════════
    #  脚本成片内嵌进度轮询 + 结果展示
    # ════════════════════════════════════════════════════════════════════════
    def _start_script_polling(self, task_id):
        """启动轮询 Worker，监控脚本成片任务进度。"""
        self.script_progress_bar.setVisible(True)
        self.script_progress_bar.setValue(0)
        self.script_stage_label.setText("排队中…")
        self._script_poll_worker = ScriptTaskPollWorker(task_id, poll_interval=3, timeout=900)
        self._script_poll_worker.progress.connect(self._on_script_progress)
        self._script_poll_worker.status_changed.connect(self._on_script_status_changed)
        self._script_poll_worker.completed.connect(self._on_script_completed)
        self._script_poll_worker.failed.connect(self._on_script_failed)
        self.track_worker(self._script_poll_worker)
        self._script_poll_worker.start()

    def _on_script_progress(self, progress, stage):
        self.script_progress_bar.setValue(progress)
        self.script_stage_label.setText(f"{stage} ({progress}%)")

    def _on_script_status_changed(self, status):
        stage = ScriptTaskPollWorker.STAGE_MAP.get(status, status)
        self.script_status.setText(f"任务状态: {stage}")

    def _on_script_completed(self, task_data):
        self.script_progress_bar.setValue(100)
        self.script_stage_label.setText("已完成 (100%)")
        self.script_status.setText("成片生成完成！")
        self._show_script_result(task_data)

    def _on_script_failed(self, error):
        self.script_stage_label.setText("失败")
        self.script_status.setText(f"成片失败：{error}")
        self.show_error(f"脚本成片失败：{error}", "错误")

    def _show_script_result(self, task_data):
        """解析任务结果并展示视频播放器。"""
        result = task_data.get("result") or {}
        video_url = (
            result.get("video_url")
            or result.get("output_url")
            or result.get("url")
            or result.get("file_url")
            or task_data.get("video_url")
            or task_data.get("output_url")
            or ""
        )
        if not video_url:
            self.script_result_label.setText("完成但未返回视频地址")
            return
        self._script_video_url = video_url
        self._script_result_group.setVisible(True)
        self.script_btn_download.setEnabled(True)
        self.script_btn_open_folder.setEnabled(True)
        self.script_result_label.setText(f"视频地址: {video_url}")
        self._play_script_video(video_url)

    def _play_script_video(self, url):
        """在本页内嵌播放视频。"""
        if self._script_player is None:
            self._script_player = QMediaPlayer(self)
            self._script_audio_output = QAudioOutput(self)
            self._script_audio_output.setVolume(80)
            self._script_player.setAudioOutput(self._script_audio_output)
            self._script_player.videoOutputChanged.connect(self._on_script_video_output_changed)
        self._script_player.setSource(QUrl(url))
        self._script_player.play()

    def _on_script_video_output_changed(self, video_output):
        if video_output is not None:
            video_output.setSurface(self.script_video_widget.videoSurface())

    def _download_script_result(self):
        """下载成片结果到本地。"""
        url = getattr(self, "_script_video_url", "")
        if not url:
            return
        from utils import scheduled_task_client as stc
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(FINAL_OUTPUT_DIR, f"script_montage_{ts}.mp4")
        try:
            stc.download_result_file(url, local_path)
            self.show_info(f"成片已下载到：\n{local_path}")
        except Exception as e:
            self.show_error(f"下载失败：{e}", "错误")

    def _open_script_output_dir(self):
        """打开成片输出目录。"""
        if os.path.isdir(FINAL_OUTPUT_DIR) and os.name == "nt":
            os.startfile(FINAL_OUTPUT_DIR)

    # ════════════════════════════════════════════════════════════════════════
    #  产品选择
    # ════════════════════════════════════════════════════════════════════════
    def _populate_products(self):
        from utils.thread_worker import TaskWorker as Worker
        self.combo_product.blockSignals(True)
        self.combo_product.clear()
        # 先放一个占位空项
        self.combo_product.addItem("— 请选择产品 —", "")
        self.combo_product.setCurrentIndex(0)
        self.combo_product.blockSignals(False)
        # grouped() 会同步请求服务端 /grouped，必须放后台线程，避免服务端异常时卡界面
        w = Worker(self._product_mgr.grouped)
        w.finished.connect(self._on_products_loaded)
        w.error.connect(self._on_products_error)
        self.track_worker(w)
        w.start()

    def _on_products_loaded(self, grouped):
        grouped = grouped or {}
        self.combo_product.blockSignals(True)
        self.combo_product.clear()
        try:
            self.combo_product.addItem("— 请选择产品 —", "")
            for cat, brands in grouped.items():
                for brand, items in brands.items():
                    for it in items:
                        model = it.get("model", "").strip() or it.get("goods_no", "")
                        label = f"[{cat}] {brand} / {model}"
                        self.combo_product.addItem(label, it.get("id", ""))
        except (KeyError, TypeError, AttributeError) as e:
            log.error(f"载入产品库失败: {e}")
            self._log(f"注意： 载入产品库失败: {e}")
        self.combo_product.setCurrentIndex(0)
        self.combo_product.blockSignals(False)

    def _on_products_error(self, msg):
        log.error(f"载入产品库失败: {msg}")
        self._log(f"注意： 载入产品库失败: {msg}")

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
    def _auto_open_task_monitor(self):
        """提交立即执行任务后，自动切到「成片任务」页并开启自动刷新。"""
        mw = getattr(self, "main_window", None)
        if mw is None:
            return
        tool = getattr(mw, "scheduled_tasks_tool", None)
        if tool is not None and hasattr(tool, "chk_autorefresh"):
            with contextlib.suppress(AttributeError, TypeError):
                tool.chk_autorefresh.setChecked(True)
        if hasattr(mw, "switch_page"):
            QTimer.singleShot(500, lambda: mw.switch_page(42))

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
        except (ImportError, OSError, KeyError, TypeError, AttributeError) as e:
            log.error(f"载入音色样本失败: {e}")

    def _populate_script_voices(self):
        self.script_combo_voice.clear()
        self.script_combo_voice.addItem("默认音色", "")
        try:
            from gui.voice_samples_page import load_voice_samples
            for s in load_voice_samples():
                name = s.get("name") or s.get("filename") or "样本"
                path = s.get("path", "")
                if path:
                    self.script_combo_voice.addItem(name, path)
        except (ImportError, OSError, KeyError, TypeError, AttributeError) as e:
            log.error(f"载入脚本音色样本失败: {e}")

    # ════════════════════════════════════════════════════════════════════════
    #  TTS / MG 开场
    # ════════════════════════════════════════════════════════════════════════
    def _tts_generate(self):
        text = self.in_subtitle.toPlainText().strip()
        if not text:
            self.show_warning("请先在『字幕文案 / 配音文案』里填入要配音的文案。")
            return
        ref = self.combo_voice.currentData() or ""
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("tts_%Y%m%d_%H%M%S.wav"))  # noqa: E501
        self.btn_tts.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.stage_label.setText("准备配音…")
        worker = TTSWorker(text, ref, out)
        worker.phase.connect(self.stage_label.setText)

        def done(path):
            self.btn_tts.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.in_audio.setText(path)
            self.stage_label.setText(f"完成： 配音已生成并填入：{os.path.basename(path)}")
            self._log(f"完成： 配音已生成: {path}")

        worker.done.connect(done)
        worker.error.connect(lambda e: (self.btn_tts.setEnabled(True), self.progress_bar.setVisible(False),  # noqa: E501
                                        self.show_error(str(e), "TTS 配音失败")))
        self.track_worker(worker)
        worker.start()

    def _gen_mg_intro(self):
        from PySide6.QtWidgets import QInputDialog
        default = (self.in_subtitle.toPlainText().strip().splitlines() or [""])[0][:16]
        title, ok = QInputDialog.getText(self.parent_widget, "动态标题开场", "标题文字：", text=default)  # noqa: E501
        if not ok or not title.strip():
            return
        from gui.mg_render_worker import MGServerRenderWorker
        from utils.mg_server_client import make_mg_request
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("mgintro_%Y%m%d_%H%M%S.mp4"))  # noqa: E501
        self.btn_mg_intro.setEnabled(False)
        self.progress_bar.setVisible(True)
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
            self.btn_mg_intro.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.in_intro.setText(path)
            self.stage_label.setText(f"完成： 开场动画已生成：{os.path.basename(path)}")
            self._log(f"完成： MG 开场已生成: {path}")
        w.finished.connect(done)
        w.error.connect(lambda e: (self.btn_mg_intro.setEnabled(True), self.progress_bar.setVisible(False),  # noqa: E501
                                   self.show_error(str(e), "MG 开场生成失败")))
        self.track_worker(w)
        w.start()
    def _collect_params(self):
        """收集当前界面完整参数为 dict（提交给服务端，服务端按需取用）。"""
        product = self._current_product() or {}
        return {
            # 服务端 product_montage 执行器识别的参数
            "products": [{
                "brand": product.get("brand", ""),
                "model": product.get("model", ""),
                "features": self._split_md_lines(product.get("features", "")),
                "selling_points": self._split_md_lines(product.get("selling_points", "")),  # noqa: E501
                "category": product.get("category", ""),
                "goods_no": product.get("goods_no", ""),
            }],
            "script_hint": self.in_subtitle.toPlainText().strip() or
                            (product.get("selling_points", "") or "")[:120],
            "max_duration": int(self.spin_total_dur) if self.spin_total_dur > 0 else 30,
            # 客户端完整参数（服务端按自身实现取用）
            "product_id": product.get("id", ""),
            "product_label": self.combo_product.currentText(),
            "folder": self.in_folder.text().strip(),
            "audio": self.in_audio.text().strip(),
            "cover": self.in_cover.text().strip(),
            "subtitle": self.in_subtitle.toPlainText().strip(),
            "ratio": self.combo_ratio,
            "per_dur": self.spin_dur,
            "count": self.spin_count.value(),
            "total_dur": self.spin_total_dur,
            "intro": self.in_intro.text().strip(),
            "predict_platform": self.combo_predict_platform.currentText(),
            "autocheck": self.chk_autocheck.isChecked(),
            "materials": self._materials or [],
            "template_id": self._current_template.get("id", "") if self._current_template else "",  # noqa: E501
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
        from datetime import datetime as _dt

        from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QSpinBox, QTimeEdit

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
        interval_spin = QSpinBox()
        interval_spin.setRange(1, 168)
        interval_spin.setValue(24)  # noqa: E501
        form.addRow("间隔小时", interval_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
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
        self._log(f" 提交任务到服务端：{task_title}（{'立即执行' if immediate else '定时执行'}）")

        # 用 TaskWorker 异步提交（避免阻塞 UI）
        from utils.thread_worker import TaskWorker as Worker
        def _do_submit():
            tid = stc.create_task("product_montage", task_title, params, schedule=schedule)  # noqa: E501
            return tid

        worker = Worker(_do_submit)
        def _on_done(tid):
            self.btn_make.setEnabled(True)
            self.btn_add_task.setEnabled(True)
            if tid:
                self.stage_label.setText(f" 已提交服务端，任务 ID={tid}")
                self._log(f"完成： 服务端已接收，任务 ID={tid}。可在「成片任务」页监控状态。")
                self.show_info(f"任务已提交服务端（ID={tid}）。\n\n"
                               + ("服务端正在执行，已自动打开「成片任务」页监控进度。"
                                  if immediate else
                                  "服务端将按计划定时执行，可在「成片任务」页监控。"))
                if immediate:
                    self._auto_open_task_monitor()
            else:
                self.stage_label.setText("注意： 提交失败")
                self._log("失败： 服务端提交失败，请检查服务端连接")
                self.show_warning("提交服务端失败，请确认服务端在线后重试。")
        def _on_err(e):
            self.btn_make.setEnabled(True)
            self.btn_add_task.setEnabled(True)
            self.stage_label.setText("注意： 提交失败")
            self._log(f"失败： 提交异常: {e}")
            self.show_error(f"提交异常：{e}", "错误")

        worker.finished.connect(_on_done)
        worker.error.connect(_on_err)
        self.track_worker(worker)
        worker.start()

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
                self.stage_label.setText(f" 已匹配素材目录: {folder}")
                self._do_make(folder)
            else:
                self.stage_label.setText(" 未能自动匹配素材目录")
                self.show_warning("未能自动匹配到素材目录，请手动选择「镜头素材目录」。")

        def on_err(e):
            self.btn_make.setEnabled(True)
            self.stage_label.setText("注意： 素材匹配失败")
            self.show_warning(f"素材匹配失败：{e}\n请手动选择「镜头素材目录」。")

        mw.result_ready.connect(on_done)
        mw.error.connect(on_err)
        self.track_worker(mw)
        mw.start()

    def _do_make(self, folder):
        out_dir = FINAL_OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        count = self.spin_count.value()
        total_dur = self.spin_total_dur
        self.btn_make.setEnabled(False)
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)
        self._last_results = []

        self.worker = CompileVideoWorker(
            folder, out_dir,
            self.in_audio.text().strip(),
            self.in_cover.text().strip(),
            self.in_subtitle.toPlainText().strip(),
            self.combo_ratio,
            self.spin_dur,
            count=count,
            total_dur=total_dur,
            intro=self.in_intro.text().strip(),
        )
        self.worker.phase.connect(self.stage_label.setText)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log_line.connect(self._log)
        self.worker.done.connect(self._done)
        self.worker.error.connect(self._err)
        self.track_worker(self.worker)
        self.worker.start()

    def _done(self, results):
        self._last_results = results or []
        self.btn_make.setEnabled(True)
        # 填充结果列表
        self.result_table.setRowCount(len(self._last_results))
        for i, path in enumerate(self._last_results):
            self.result_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.result_table.setItem(i, 1, QTableWidgetItem(os.path.basename(path)))
            status_item = QTableWidgetItem(" 完成")
            status_item.setForeground(Qt.GlobalColor.green)
            self.result_table.setItem(i, 2, status_item)
            btn = table_action_button("", "打开")
            btn.clicked.connect(lambda _=False, p=path: self._open_file(p))
            self.result_table.setCellWidget(i, 3, btn)
        self.stage_label.setText(f" 完成：共生成 {len(self._last_results)} 个成片")
        self._log(f"═══ 全部完成：{len(self._last_results)} 个成片 ═══")

        # 自动视频评价预测（只对第一个成片）
        if self.chk_autocheck.isChecked() and self._last_results:
            cfg = self.ai_config
            if cfg.get("llm_vision_api_url"):
                from gui.hook_score_page import HookScoreWorker
                platform = self.combo_predict_platform.currentText()
                self._predict_platform = platform
                try:
                    calib = VideoPredictionManager().calibration_text(platform=platform)
                except Exception:  # 外部API调用，calibration_text 可能涉及网络/配置等多种异常
                    calib = ""
                self.score_label.setText(f"正在按「{platform}」做视频评价预测…")
                self.score_widget.setVisible(True)
                out = self._last_results[0]
                sw = HookScoreWorker(out, cfg, platform=platform, calibration=calib)
                sw.finished.connect(self._on_self_check)
                sw.error.connect(lambda e: self.score_label.setText(f"视频预测失败：{e}"))
                self.track_worker(sw)
                sw.start()
            else:
                self.score_label.setText("（未配置视觉模型，跳过视频评价预测。）")
                self.score_widget.setVisible(True)

    def _on_self_check(self, data):
        self.score_widget.setVisible(True)
        self._self_check_data = data
        total = data.get("total", "—")
        level = data.get("play_level", "")
        comment = str(data.get("comment", ""))
        self.score_label.setText(f" 视频预测：综合 {total} 分 · 预测{level}　{comment}")
        self.btn_detail.setVisible(True)
        try:
            if self._last_results:
                VideoPredictionManager().add_prediction(
                    self._last_results[0], getattr(self, "_predict_platform", "抖音"), data)  # noqa: E501
        except Exception:  # 外部API调用，add_prediction 可能涉及网络/存储等多种异常
            pass

    def _open_detail(self):
        tool = getattr(self.main_window, "hook_score_tool", None)
        try:
            self.main_window.switch_page(34)  # 开头黄金3秒评分
            if tool and hasattr(tool, "show_result") and self._last_results:
                tool.show_result(self._last_results[0], self._self_check_data)
        except (AttributeError, TypeError) as e:
            self.show_error(f"跳转失败：{e}")

    def _err(self, e):
        self.btn_make.setEnabled(True)
        self.stage_label.setText("成片失败。")
        self._log(f" 失败: {e}")
        self.show_error(str(e), "一键成片失败")

    # ════════════════════════════════════════════════════════════════════════
    #  辅助
    # ════════════════════════════════════════════════════════════════════════
    def _log(self, text):
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {text}")
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())  # noqa: E501

    def _auto_select_product(self, materials):
        """根据素材中出现最多的品牌/型号自动选择产品（无匹配则保持原选项）。"""
        if not materials:
            return
        pairs: Counter = Counter()
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
                mo = (it.get("model") or "").strip() or (it.get("goods_no") or "").strip()  # noqa: E501
                if target_brand and target_model:
                    if b == target_brand and (mo == target_model or target_model in mo or mo in target_model):  # noqa: E501
                        self.combo_product.setCurrentIndex(i)
                        self._log(f" 已根据素材自动选择产品: {self.combo_product.currentText()}")
                        return
                elif target_brand and b == target_brand:
                    self.combo_product.setCurrentIndex(i)
                    self._log(f" 已根据素材品牌自动选择产品: {self.combo_product.currentText()}")
                    return
        except (KeyError, TypeError, AttributeError) as e:
            log.error(f"自动选择产品失败: {e}")

    def import_materials(self, materials):
        """从素材检索带入素材列表（支持多个、图片+视频混合）。"""
        self._materials = list(materials or [])
        self.material_list.clear()
        for m in self._materials:
            fname = m.get("filename") or m.get("material_id") or ""
            mtype = (m.get("media_type") or "").lower()
            icon = {"video": "", "image": "", "audio": ""}.get(mtype, "")
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
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        row.addWidget(edit, 1)
        btn = mdi_button("浏览…", "folder")
        btn.setObjectName("secondary_button")
        btn.clicked.connect(lambda: on_browse(edit))
        row.addWidget(btn)
        parent.addLayout(row)
        return edit

    def _browse_folder(self, edit):
        d = pick_directory(self.parent_widget, "选择素材目录")
        if d:
            edit.setText(d)

    def _browse_audio(self, edit):
        f, _ = pick_file(self.parent_widget, "选择配音", "", "音频 (*.wav *.mp3 *.m4a *.aac *.flac)")  # noqa: E501
        if f:
            edit.setText(f)

    def _browse_cover(self, edit):
        f, _ = pick_file(self.parent_widget, "选择封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")  # noqa: E501
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


    def _video_url_for_template(self, template):
        """从模板字段中提取预览视频地址。"""
        if not template:
            return ""
        for key in ("video_url", "preview_url", "download_url", "url",
                    "video", "preview", "output_url", "media_url", "file"):
            v = template.get(key)
            if isinstance(v, dict):
                for sub in ("url", "download_url", "video_url", "path"):
                    sv = v.get(sub)
                    if isinstance(sv, str) and sv.strip():
                        return sv.strip()
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _play_template_video(self, url):
        """播放模板返回的视频地址。"""
        if not url:
            return
        self._log(f"播放 播放模板预览: {url}")
        self._play_preview(url)

    def _fill_template_list(self, templates, current_id=None):
        """用表格展示模板，每行后面带一个播放按钮。"""
        self.list_templates.clearContents()
        self.list_templates.setRowCount(0)
        builtins = [t for t in templates if t.get("is_builtin") or t.get("builtin")]
        customs = [t for t in templates if not (t.get("is_builtin") or t.get("builtin"))]  # noqa: E501
        current_row = 0

        def _add_header(label):
            nonlocal current_row
            self.list_templates.insertRow(current_row)
            header_item = QTableWidgetItem(label)
            header_item.setFlags(Qt.NoItemFlags)
            header_item.setForeground(Qt.GlobalColor.gray)
            self.list_templates.setItem(current_row, 0, header_item)
            self.list_templates.setSpan(current_row, 0, 1, 2)
            current_row += 1

        def _add_template(t):
            nonlocal current_row
            self.list_templates.insertRow(current_row)
            name = t.get("name") or t.get("id", "")
            backend = t.get("backend")
            if backend:
                name += f" [{backend}]"
            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, t)
            item.setToolTip(t.get("description", ""))
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.list_templates.setItem(current_row, 0, item)
            url = self._video_url_for_template(t)
            if url:
                btn = icon_button("play", f"播放预览: {url}")
                btn.clicked.connect(lambda checked=False, u=url: self._play_template_video(u))  # noqa: E501
            else:
                btn = QLabel("—")
                btn.setAlignment(Qt.AlignCenter)
            self.list_templates.setCellWidget(current_row, 1, btn)
            current_row += 1

        if builtins:
            _add_header("━━ 内置模板 ━━")
            for t in builtins:
                _add_template(t)
        if customs:
            _add_header("━━ 自定义模板 ━━")
            for t in customs:
                _add_template(t)

        for row in range(self.list_templates.rowCount()):
            item = self.list_templates.item(row, 0)
            if item and item.flags() & Qt.ItemIsSelectable:
                self.list_templates.setCurrentCell(row, 0)
                break

        if current_id:
            for row in range(self.list_templates.rowCount()):
                item = self.list_templates.item(row, 0)
                if item:
                    t = item.data(Qt.UserRole)
                    if t and t.get("id") == current_id:
                        self.list_templates.setCurrentCell(row, 0)
                        break
    # -------------- 模板相关方法 --------------
    def _load_templates(self):
        """加载成片模板库（统一接口 /templates?type=video + 内置兜底）。"""
        self._templates = list(VIDEO_FALLBACK_TEMPLATES)
        self._fill_template_list(self._templates)
        w = VideoTemplateLoadWorker()
        w.finished.connect(self._on_templates_loaded)
        w.phase.connect(self._log)
        self.track_worker(w)
        w.start()

    def _on_templates_loaded(self, server_templates):
        # 模板以服务端 /templates 返回为准；本地内置仅在服务端不可用时回退，
        # 避免“内置模板(本地兜底) + 自定义模板(服务端)”来源混杂同时显示。
        if server_templates:
            self._templates = list(server_templates)
            self._log(f" 已加载服务端成片模板 {len(server_templates)} 个")
        else:
            self._log(" 未从服务端加载到成片模板，使用内置模板")
            self._templates = list(VIDEO_FALLBACK_TEMPLATES)
        current_id = self._current_template.get("id") if self._current_template else None  # noqa: E501
        self._fill_template_list(self._templates, current_id=current_id)

    def _on_template_item_changed(self, current, previous):
        if current is None:
            return
        item = self.list_templates.item(current.row(), 0)
        if item is None:
            return
        template = item.data(Qt.UserRole)
        if not template:
            return
        self._current_template = template
        self._apply_template_to_editor(template)

    def _apply_template_to_editor(self, template):
        # 更新右侧概述（不含分镜脚本信息）
        self._update_template_overview(template)
        # 把模板内脚本的素材/口播/音频同步到左侧模板参数
        self._apply_script_to_params(template)

    def _add_overview_row(self, label, value, tooltip=None):
        """在概述表单里添加一行标签+只读值。"""
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #8b90a3; font-size: 12px;")
        val = QLabel(value)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setStyleSheet("color: #e2e4ea; font-size: 12px;")
        if tooltip:
            val.setToolTip(tooltip)
        self.overview_form.addRow(lbl, val)

    def _material_name(self, m):
        """把素材条目统一成可读名称。"""
        if isinstance(m, dict):
            return (m.get("name") or m.get("filename") or m.get("path")
                    or m.get("url") or m.get("id") or str(m))
        return str(m)

    def _apply_script_to_params(self, template):
        """把模板脚本中的素材、口播、音频同步到左侧模板参数。"""
        summary = extract_script_summary(template, material_name_fn=self._material_name)
        if not summary:
            return
        # 素材
        if summary.get("materials"):
            mats = []
            for m in summary["materials"]:
                ext = os.path.splitext(str(m))[1].lower()
                if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                    mtype = "video"
                elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
                    mtype = "image"
                else:
                    mtype = "video"
                mats.append({
                    "material_id": str(m),
                    "media_type": mtype,
                    "filename": os.path.basename(str(m)) or str(m),
                    "path": str(m),
                })
            self.import_materials(mats)
        # 文案
        if summary.get("narrations"):
            self.in_subtitle.setPlainText("\n".join(summary["narrations"]))
        # 配音音频
        if summary.get("audio_files"):
            self.in_audio.setText(summary["audio_files"][0])

    def _update_template_overview(self, template):
        """在右侧面板展示模板关键信息（模板不可编辑）。"""
        while self.overview_form.count():
            item = self.overview_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not template:
            self._add_overview_row("提示", "请选择一个成片模板以查看概述。")
            return

        self._add_overview_row("名称", "{name}  ({tid})".format(
            name=template.get("name", "-"), tid=template.get("id", "-")))
        self._add_overview_row("类型/分类",
            "{tp} / {cat}".format(tp=template.get("type", "-"),
                                  cat=template.get("category", "-")))
        if template.get("description"):
            self._add_overview_row("描述", template["description"])
        self._add_overview_row("内置", "是" if template.get("is_builtin") else "否")

        # 服务端 API 定义的模板字段
        canvas = template.get("canvas") or {}
        if canvas:
            self._add_overview_row(
                "画布",
                "{w}×{h} @ {fps}".format(
                    w=canvas.get("width", "-"), h=canvas.get("height", "-"),
                    fps=canvas.get("fps", "-")))
        if template.get("duration"):
            self._add_overview_row("时长", f"{template['duration']} 秒")

        params = template.get("params") or []
        if params:
            param_lines = []
            for p in params:
                key = p.get("name") or p.get("key") or "-"
                label = p.get("label") or key
                ptype = p.get("type") or "-"
                default = p.get("default")
                default_txt = compact_text(default) if default is not None else "-"
                param_lines.append(
                    f"• {label}（{key}）类型 {ptype}，默认 {default_txt}")
            self._add_overview_row("参数", "\n".join(param_lines))

        effects = template.get("effects")
        if effects:
            self._add_overview_row(
                "效果", compact_text(effects))

        # 兼容自定义模板携带的分镜脚本数据
        summary = extract_script_summary(template, material_name_fn=self._material_name)
        if summary:
            self._add_overview_row(
                "脚本摘要",
                "{shots} 镜 / {dur:.1f}s / {ratio}".format(
                    shots=summary["shot_count"],
                    dur=summary["total_duration"],
                    ratio=summary.get("ratio") or "-"))
            if summary.get("materials"):
                mat_text = "、".join(summary["materials"][:10])
                if len(summary["materials"]) > 10:
                    mat_text += " 等 {n} 个".format(n=len(summary["materials"]))
                self._add_overview_row(
                    "素材 ({n})".format(n=len(summary["materials"])),
                    mat_text, "\n".join(summary["materials"]))
            if summary.get("narrations"):
                nar_text = "\n".join(summary["narrations"])
                if len(nar_text) > 300:
                    nar_text = nar_text[:300] + "…"
                self._add_overview_row(
                    "口播 ({n} 句)".format(n=len(summary["narrations"])),
                    nar_text)
            if summary.get("audio_files"):
                self._add_overview_row(
                    "配音 ({n})".format(n=len(summary["audio_files"])),
                    "、".join(summary["audio_files"]))
            if summary.get("sfx_files"):
                self._add_overview_row(
                    "音效 ({n})".format(n=len(summary["sfx_files"])),
                    "、".join(summary["sfx_files"]))
        else:
            self._add_overview_row(
                "脚本数据",
                "当前模板未携带分镜脚本字段；素材/文案/音频/开场封面请在左侧「模板参数」中手动填写。")

        # 其余字段
        excluded = {
            "name", "id", "type", "category", "description", "is_builtin",
            "params", "effects", "canvas", "duration",
            "storyboard", "scenes", "script", "shots", "分镜脚本",
            "storyboard_script", "storyboard_text", "storyboard_json",
        }
        for key, val in sorted(template.items()):
            if key in excluded or val is None or val == {} or val == []:
                continue
            if isinstance(val, (dict, list)):
                val = compact_text(val)
            self._add_overview_row(key, str(val))
    def _collect_template_params(self):
        """使用模板默认参数；topic 为空时从产品卖点自动填入。"""
        if not self._current_template:
            return {}
        # 服务端 TemplateIn 的 params 数组里每个 ParamDef 带 default
        params = {}
        for p in (self._current_template.get("params") or []):
            key = p.get("name") or p.get("key")
            if key and p.get("default") is not None:
                params[key] = p["default"]
        if not params.get("topic"):
            product = self._current_product() or {}
            selling = (product.get("selling_points") or "").strip().splitlines()
            if selling:
                params["topic"] = selling[0][:60]
        return params

    def _play_preview(self, path):
        """用统一播放器预览成片（等比显示 + 播放/暂停/停止 + 进度条 + 时间）；失败回退系统播放器。"""
        try:
            from gui.video_player import VideoPreviewDialog
            dlg = VideoPreviewDialog(path=path, parent=self.parent_widget,
                                     title="成片模板预览", size=(560, 760))
            dlg.exec()
        except Exception as e:  # UI组件操作，VideoPreviewDialog 可能涉及多种Qt异常
            self._log(f"注意： 内置播放失败，改用系统播放器: {e}")
            try:
                os.startfile(os.path.abspath(path))  # noqa
            except OSError:
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
