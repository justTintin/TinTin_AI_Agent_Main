"""
MG 动画页（服务端渲染版，按 OpenAPI /mg/* 实现）。
业务流：
  1. 左侧展示内置模板 + 服务端模板。
  2. 选择模板后，根据 template.params 动态生成参数表单。
  3. 点击"生成"调用 /mg/generate -> /mg/status -> /mg/result 下载 MP4。

注意：服务端 /mg/* 仅暴露 list/generate/status/result；没有 preview、
analyze-video、templates/{id} 等端点，因此本页不再提供预览与自定义模板
保存/删除。mg_benchmark 需服务端在 MGRequest 中新增 specs/bars 字段后启用。
"""
import contextlib
import os
from datetime import datetime

from gui.base_page import BasePage
from gui.elided_label import ElidedLabel
from gui.mg_render_worker import MGServerRenderWorker
from gui.searchable_combo import SearchableComboBox
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.base_worker import BaseWorker
from utils.json_utils import from_editor_text, parse_json_default, to_editor_text
from utils.llm_output_utils import safe_json_parse
from utils.mg_server_client import (
    list_templates,
)
from utils.template_param_builder import build_mg_request

# 内置模板兜底（id 需与服务端保持一致）
FALLBACK_TEMPLATES = [
    {"id": "mg_scene", "name": "通用场景", "description": "基于 scenes 列表渲染多段文字动画", "is_builtin": True},  # noqa: E501
    {"id": "mg_intro", "name": "片头", "description": "大标题 + 副标题开场", "is_builtin": True},
    {"id": "mg_outro", "name": "片尾", "description": "结束语 + 引导关注", "is_builtin": True},
    {"id": "mg_countdown", "name": "倒计时", "description": "数字倒计时，0 表示 GO", "is_builtin": True},  # noqa: E501
    {"id": "mg_quote", "name": "金句引用", "description": "名言金句：引用 + 作者", "is_builtin": True},  # noqa: E501
]

RATIOS = ["9:16", "16:9", "1:1", "3:4", "4:3"]
ANIMATIONS = ["fade", "slide_up", "scale", "typewriter", "pulse"]
CUSTOM_BACKENDS = ["mg_scene", "mg_intro", "mg_outro", "mg_countdown", "mg_quote"]

# 已知内置参数名 -> (widget_type, label)
BUILTIN_PARAM_META = {
    "title": ("line", "标题"),
    "subtitle": ("line", "副标题"),
    "text": ("line", "正文"),
    "subtext": ("line", "辅助文字"),
    "quote": ("line", "引用内容"),
    "author": ("line", "作者/来源"),
    "start": ("int", "起始值"),
    "end": ("int", "结束值"),
    "scenes": ("scenes", "场景列表"),
    "color": ("color", "文字颜色"),
    "bg": ("color", "背景颜色"),
    "fontSize": ("int", "字号"),
    "duration": ("float", "总时长(秒)"),
    "ratio": ("ratio", "比例"),
    "scale": ("float", "缩放"),
}

# 自定义模板参数类型 -> widget_type
CUSTOM_TYPE_MAP = {
    "string": "line", "text": "line", "line": "line",
    "int": "int", "integer": "int",
    "float": "float", "number": "float",
    "bool": "bool", "boolean": "bool",
    "color": "color",
    "ratio": "ratio",
    "json": "json",
    "scenes": "scenes",
}


def _default_for_builtin(key):
    defaults = {
        "title": "主标题",
        "subtitle": "副标题",
        "text": "正文",
        "subtext": "辅助文字",
        "quote": "引用内容",
        "author": "作者",
        "start": 5,
        "end": 0,
        "color": "#FFFFFF",
        "bg": "#101418",
        "fontSize": 96,
        "duration": 3.0,
        "ratio": "9:16",
        "scale": 1.0,
    }
    return defaults.get(key, "")


def _param_meta(param):
    """统一把模板参数转成 (key, widget_type, label, default)。"""
    if isinstance(param, str):
        key = param
        meta = BUILTIN_PARAM_META.get(key, ("line", key))
        return key, meta[0], meta[1], _default_for_builtin(key)
    if isinstance(param, dict):
        key = param.get("name") or param.get("key") or ""
        t = (param.get("type") or "string").lower()
        widget_type = CUSTOM_TYPE_MAP.get(t, "line")
        label = param.get("label") or param.get("desc") or key or "参数"
        default = param.get("default")
        if widget_type == "json":
            default = parse_json_default(default)
        return key, widget_type, label, default
    return None, None, None, None


def _template_backend(template):
    """获取模板渲染时使用的后端 template id。内置用自身 id；自定义用 backend。"""
    if template.get("is_builtin") or template.get("builtin"):
        return template.get("id")
    return template.get("backend") or template.get("id")


class MGTemplateLoadWorker(BaseWorker):
    """异步从服务端拉取 /mg/templates。"""
    finished = Signal(list)
    phase = Signal(str)

    def do_work(self):
        self.phase.emit("正在加载 MG 模板列表...")
        templates = list_templates(timeout=8)
        self.finished.emit(templates)



class MGScriptAIWorker(BaseWorker):
    """调用服务端 LLM 代理，根据文案生成当前模板可用的参数值。"""
    finished = Signal(dict)
    phase = Signal(str)

    def __init__(self, template, user_text):
        super().__init__()
        self.template = template
        self.user_text = user_text

    def do_work(self):
        from utils.llm_proxy import llm_chat
        self.phase.emit("正在生成 MG 参数...")
        backend = _template_backend(self.template)
        params = self.template.get("params") or []
        param_desc = []
        for p in params:
            key, wtype, label, default = _param_meta(p)
            if not key:
                continue
            param_desc.append(f"{key}({label}, {wtype}, 默认:{default})")

        system = (
            "你是电商短视频 MG 动画参数生成器。根据用户提供的原始文案，"
            "直接返回一个纯 JSON 对象（不要 markdown 代码块）。"
            "字段需符合当前模板所需参数，总时长控制在 3~5 秒。"
            f"当前模板后端: {backend}\n"
            "需要填写的参数：\n" + "\n".join(param_desc) + "\n"
            "注意：scenes 参数应为数组，每个元素含 text(必填，最长200字)、"
            "animation(fade/slide_up/scale/typewriter/pulse)、duration(秒，0.5~20)、"
            "color、bg、fontSize。specs 为对象 {cpu,gpu,ram,ssd}，bars 为数组 "
            "[{label,avgFps,maxFps,color}]。"
        )
        user = (
            f"指定模板：{backend}\n"
            f"原始文案：{self.user_text}\n"
            "请直接返回 JSON，不要解释。"
        )
        reply = llm_chat(system=system, user=user, temperature=0.3)
        props = safe_json_parse(reply)
        if props is None:
            raise RuntimeError(f"LLM 返回不是合法 JSON:\n{reply[:300]}")
        if not isinstance(props, dict):
            raise RuntimeError("LLM 返回不是 JSON 对象")
        self.finished.emit(props)


class MGAnimationPage(BasePage):
    """MG 动画业务页：模板库 + 动态表单 + 预览/生成。"""
    mg_ready = Signal(str, str)   # template_id, local_path

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self._tasks = []
        self._last_out = ""
        self._templates = []
        self._current_template = None
        self._form_widgets = {}  # {key: (widget_type, widget)}

    def setup(self, show_heading=True):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        if show_heading:
            hdr = QHBoxLayout()
            heading = QLabel(" MG 动画")
            heading.setObjectName("heading")
            hdr.addWidget(heading)

            sub = ElidedLabel("选择模板、填写参数，服务端渲染 MG 动画。", max_lines=1)
            sub.setObjectName("muted_text")
            hdr.addWidget(sub)
            hdr.addStretch()
            root.addLayout(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 780])
        root.addWidget(splitter, 1)

        # 状态栏
        status_row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted_text")
        status_row.addWidget(self.status, 1)
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setRange(0, 100)
        self.pbar.setMaximumWidth(180)
        status_row.addWidget(self.pbar)
        root.addLayout(status_row)

        QTimer.singleShot(100, self._load_templates)

    def _build_left_panel(self):
        panel = QGroupBox("模板库")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # 工具栏
        toolbar = QHBoxLayout()
        self.btn_refresh = QPushButton(" 刷新")
        self.btn_refresh.setObjectName("secondary_button")
        self.btn_refresh.setToolTip("从服务端重新加载模板列表")
        self.btn_refresh.clicked.connect(self._load_templates)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # 模板库：可搜索下拉框
        self.combo_template = SearchableComboBox(placeholder="搜索模板名称…")
        self.combo_template.currentIndexChanged.connect(self._on_template_selected)
        layout.addWidget(self.combo_template)

        # 模板信息：选择后显示在下拉框下面
        meta = QGroupBox("模板信息")
        ml = QFormLayout(meta)
        ml.setSpacing(8)
        self.edit_meta_id = QLineEdit()
        self.edit_meta_id.setReadOnly(True)
        self.edit_meta_id.setToolTip("模板 id")
        self.edit_meta_name = QLineEdit()
        self.edit_meta_name.setReadOnly(True)
        self.edit_meta_name.setToolTip("模板名称")
        self.edit_meta_desc = QLineEdit()
        self.edit_meta_desc.setReadOnly(True)
        self.edit_meta_desc.setToolTip("模板描述")
        self.combo_meta_backend = QComboBox()
        self.combo_meta_backend.addItems(CUSTOM_BACKENDS)
        self.combo_meta_backend.setEnabled(False)
        self.edit_meta_params = QTextEdit()
        self.edit_meta_params.setToolTip("模板参数定义（JSON 数组）")
        self.edit_meta_params.setMaximumHeight(90)
        self.edit_meta_params.setReadOnly(True)

        ml.addRow("模板 ID", self.edit_meta_id)
        ml.addRow("名称", self.edit_meta_name)
        ml.addRow("描述", self.edit_meta_desc)
        ml.addRow("后端", self.combo_meta_backend)
        ml.addRow("参数定义", self.edit_meta_params)
        layout.addWidget(meta)
        # 通用样式
        common = QGroupBox("通用样式")
        cl = QFormLayout(common)
        cl.setSpacing(8)
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItems(RATIOS)
        self.combo_ratio.setCurrentText("9:16")
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.2, 1.0)
        self.spin_scale.setSingleStep(0.1)
        self.spin_scale.setValue(1.0)
        self.spin_scale.setToolTip("预览/快速出图用 0.5，最终成片用 1.0")
        self.edit_color = QLineEdit("#FFFFFF")
        self.edit_bg = QLineEdit("#101418")
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(12, 300)
        self.spin_font_size.setValue(96)
        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(0.5, 30.0)
        self.spin_duration.setSingleStep(0.5)
        self.spin_duration.setValue(3.0)

        cl.addRow("比例", self.combo_ratio)
        cl.addRow("缩放", self.spin_scale)
        cl.addRow("文字颜色", self._color_row(self.edit_color))
        cl.addRow("背景颜色", self._color_row(self.edit_bg))
        cl.addRow("字号", self.spin_font_size)
        cl.addRow("总时长(秒)", self.spin_duration)
        layout.addWidget(common)

        # 动态参数表单
        form_group = QGroupBox("模板参数")
        fgl = QVBoxLayout(form_group)
        self.scroll_form = QScrollArea()
        self.scroll_form.setWidgetResizable(True)
        self.scroll_form.setFrameShape(QFrame.NoFrame)
        self.form_container = QWidget()
        self.form_layout = QFormLayout(self.form_container)
        self.form_layout.setSpacing(8)
        self.scroll_form.setWidget(self.form_container)
        fgl.addWidget(self.scroll_form)
        layout.addWidget(form_group, 1)



        return panel

    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)


        # Scenes 编辑器（仅含 scenes 参数时显示）
        self.scenes_group = QGroupBox("Scenes（多段文字动画，最多 30 段）")
        sgl = QVBoxLayout(self.scenes_group)
        self.list_scenes = QListWidget()
        self.list_scenes.setMaximumHeight(160)
        sgl.addWidget(self.list_scenes)
        scenes_btn_row = QHBoxLayout()
        self.edit_scene_text = QLineEdit()
        self.edit_scene_text.setPlaceholderText("输入一段文字...")
        scenes_btn_row.addWidget(self.edit_scene_text, 1)
        self.combo_scene_anim = QComboBox()
        self.combo_scene_anim.addItems(ANIMATIONS)
        scenes_btn_row.addWidget(QLabel("动画"))
        scenes_btn_row.addWidget(self.combo_scene_anim)
        self.spin_scene_duration = QDoubleSpinBox()
        self.spin_scene_duration.setRange(0.5, 20.0)
        self.spin_scene_duration.setSingleStep(0.5)
        self.spin_scene_duration.setValue(2.0)
        scenes_btn_row.addWidget(QLabel("时长"))
        scenes_btn_row.addWidget(self.spin_scene_duration)
        self.btn_add_scene = QPushButton(" 添加")
        self.btn_add_scene.clicked.connect(self._add_scene)
        scenes_btn_row.addWidget(self.btn_add_scene)
        self.btn_del_scene = QPushButton(" 删除")
        self.btn_del_scene.clicked.connect(self._del_scene)
        scenes_btn_row.addWidget(self.btn_del_scene)
        sgl.addLayout(scenes_btn_row)
        layout.addWidget(self.scenes_group)

        # AI + 生成
        action_row = QHBoxLayout()
        self.edit_ai_prompt = QLineEdit()
        self.edit_ai_prompt.setPlaceholderText("输入原始文案，让 AI 生成参数...")
        action_row.addWidget(self.edit_ai_prompt, 1)
        self.btn_ai = QPushButton(" AI 生成参数")
        self.btn_ai.setObjectName("secondary_button")
        self.btn_ai.clicked.connect(self._generate_script)
        action_row.addWidget(self.btn_ai)

        self.btn_render = QPushButton(" 提交渲染")
        self.btn_render.setObjectName("primary_button")
        self.btn_render.clicked.connect(self._on_render)
        action_row.addWidget(self.btn_render)
        layout.addLayout(action_row)

        # 生成结果提示
        result_group = QGroupBox("生成结果")
        rgl = QVBoxLayout(result_group)
        self.lbl_result = QLabel("提交渲染后在此处显示成片路径")
        self.lbl_result.setAlignment(Qt.AlignCenter)
        self.lbl_result.setMinimumHeight(120)
        self.lbl_result.setStyleSheet("background:#1a1a1a;color:#888;")
        self.lbl_result.setWordWrap(True)
        rgl.addWidget(self.lbl_result)
        layout.addWidget(result_group)

        # 任务列表
        task_group = QGroupBox("渲染任务")
        tgl = QVBoxLayout(task_group)
        self.table_tasks = QTableWidget(0, 7)
        self.table_tasks.setHorizontalHeaderLabels(["时间", "任务ID", "模板", "比例", "状态", "进度", "操作"])  # noqa: E501
        self.table_tasks.horizontalHeader().setStretchLastSection(True)
        self.table_tasks.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_tasks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_tasks.cellClicked.connect(self._on_task_cell_clicked)
        tgl.addWidget(self.table_tasks)
        layout.addWidget(task_group, 1)

        return panel

    def _color_row(self, edit):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        edit.setFixedWidth(120)
        h.addWidget(edit)
        btn = QPushButton("")
        btn.setObjectName("secondary_button")
        btn.setFixedWidth(40)
        btn.clicked.connect(lambda: self._pick_color(edit))
        h.addWidget(btn)
        h.addStretch()
        return row

    def _pick_color(self, edit):
        from PySide6.QtGui import QColor
        c = QColorDialog.getColor(QColor(edit.text() or "#FFFFFF"), self.parent_widget, "选择颜色")  # noqa: E501
        if c.isValid():
            edit.setText(c.name().upper())

    def _load_templates(self):
        """先显示默认列表，再异步从服务端拉取更新。"""
        self._templates = list(FALLBACK_TEMPLATES)
        self._fill_template_list()
        self.status.setText("正在加载模板列表...")
        w = MGTemplateLoadWorker()
        w.finished.connect(self._on_templates_loaded)
        w.phase.connect(self.status.setText)
        self.track_worker(w)
        w.start()

    def _fill_template_list(self):
        builtins = [t for t in self._templates if t.get("is_builtin") or t.get("builtin")]  # noqa: E501
        customs = [t for t in self._templates if not (t.get("is_builtin") or t.get("builtin"))]  # noqa: E501
        items = []
        for t in builtins + customs:
            label = t.get("name", t.get("id", ""))
            if not (t.get("is_builtin") or t.get("builtin")):
                backend = t.get("backend", "")
                if backend:
                    label += f" [{backend}]"
            items.append((label, t))
        # setItems 期间不触发 currentIndexChanged，随后默认选中第一项并应用模板信息
        self.combo_template.setItems(items)
        if self.combo_template.count() > 0:
            self._on_template_selected(self.combo_template.currentIndex())

    def _on_templates_loaded(self, server_templates):
        self.status.setText("")
        if not server_templates:
            return
        merged = {t["id"]: t for t in FALLBACK_TEMPLATES}
        for t in server_templates:
            tid = t.get("id")
            if not tid:
                continue
            t["is_builtin"] = t.get("is_builtin", t.get("builtin", False))
            if tid in merged:
                fallback = merged[tid]
                if not t.get("params"):
                    t["params"] = fallback.get("params")
                if not t.get("name"):
                    t["name"] = fallback.get("name")
                if not t.get("description"):
                    t["description"] = fallback.get("description")
            merged[tid] = t
        self._templates = list(merged.values())
        current_id = self._current_template.get("id") if self._current_template else None  # noqa: E501
        self._fill_template_list()
        if current_id:
            self._select_template_by_id(current_id)

    def _select_template_by_id(self, template_id):
        for i in range(self.combo_template.count()):
            t = self.combo_template.itemData(i)
            if t and t.get("id") == template_id:
                self.combo_template.setCurrentIndex(i)
                return

    def _on_template_selected(self, index):
        if index < 0:
            return
        template = self.combo_template.itemData(index)
        if not template:
            return
        self._current_template = template
        self._apply_template_to_editor(template)

    def _apply_template_to_editor(self, template):
        self.edit_meta_id.setText(template.get("id", ""))
        self.edit_meta_name.setText(template.get("name", ""))
        self.edit_meta_desc.setText(template.get("description", ""))
        backend = template.get("backend") or template.get("id") or ""
        idx = self.combo_meta_backend.findText(backend)
        if idx >= 0:
            self.combo_meta_backend.setCurrentIndex(idx)

        # 元信息只读显示
        params = template.get("params") or []
        self.edit_meta_params.setPlainText(to_editor_text(params))

        self._build_form(template)
        self._apply_default_common_values(template)

    def _apply_default_common_values(self, template):
        defaults = template.get("defaults") or {}
        if defaults.get("ratio") in RATIOS:
            self.combo_ratio.setCurrentText(defaults["ratio"])
        if defaults.get("color"):
            self.edit_color.setText(defaults["color"])
        if defaults.get("bg"):
            self.edit_bg.setText(defaults["bg"])
        if defaults.get("fontSize") is not None:
            self.spin_font_size.setValue(int(defaults["fontSize"]))
        if defaults.get("duration") is not None:
            self.spin_duration.setValue(float(defaults["duration"]))

    def _on_params_definition_changed(self):
        """参数定义已只读，无需动态重建表单。"""
        pass

    def _build_form(self, template):
        """根据 template.params 动态构建参数表单。"""
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._form_widgets.clear()

        params = template.get("params") or []
        has_scenes = False
        for param in params:
            key, wtype, label, default = _param_meta(param)
            if not key:
                continue
            if wtype == "scenes":
                has_scenes = True
                continue
            widget = self._create_value_widget(wtype, default)
            self._form_widgets[key] = (wtype, widget)
            if wtype == "color":
                self.form_layout.addRow(label, self._color_row(widget))
            else:
                self.form_layout.addRow(label, widget)

        self.scenes_group.setVisible(has_scenes)
        if has_scenes:
            self.list_scenes.clear()

    def _create_value_widget(self, wtype, default):
        if wtype == "line":
            w = QLineEdit()
            w.setText(str(default or ""))
            return w
        if wtype == "int":
            w = QSpinBox()
            w.setRange(0, 99999)
            try:
                w.setValue(int(default or 0))
            except (ValueError, TypeError):
                w.setValue(0)
            return w
        if wtype == "float":
            w = QDoubleSpinBox()
            w.setRange(0, 9999)
            w.setSingleStep(0.5)
            try:
                w.setValue(float(default or 0))
            except (ValueError, TypeError):
                w.setValue(0.0)
            return w
        if wtype == "color":
            w = QLineEdit()
            w.setText(str(default or "#FFFFFF"))
            return w
        if wtype == "ratio":
            w = QComboBox()
            w.addItems(RATIOS)
            w.setCurrentText(str(default or "9:16"))
            return w
        if wtype == "bool":
            w = QCheckBox()
            w.setChecked(bool(default))
            return w
        if wtype == "json":
            w = QTextEdit()
            w.setPlainText(parse_json_default(default))
            w.setMaximumHeight(120)
            return w
        # fallback
        w = QLineEdit()
        w.setText(str(default or ""))
        return w

    def _collect_form_values(self):
        values = {}
        for key, (wtype, widget) in self._form_widgets.items():
            values[key] = self._widget_value(widget, wtype)
        return values

    def _widget_value(self, widget, wtype):
        if wtype == "line":
            return widget.text().strip()
        if wtype == "int":
            return widget.value()
        if wtype == "float":
            return widget.value()
        if wtype == "color":
            return widget.text().strip()
        if wtype == "ratio":
            return widget.currentText()
        if wtype == "bool":
            return widget.isChecked()
        if wtype == "json":
            txt = widget.toPlainText().strip()
            parsed = from_editor_text(txt)
            return parsed if parsed is not None else txt
        return None

    def _collect_scenes(self):
        scenes = []
        for i in range(self.list_scenes.count()):
            item = self.list_scenes.item(i)
            if item and item.data(Qt.UserRole):
                scenes.append(item.data(Qt.UserRole))
        return scenes

    def _add_scene_item(self, scene):
        if not isinstance(scene, dict):
            return
        text = scene.get("text", "")
        if not text:
            return
        if self.list_scenes.count() >= 30:
            self.show_warning("最多 30 段 scenes。")
            return
        display = f"{scene.get('animation', 'fade')} {scene.get('duration', 2)}s | {text[:30]}"  # noqa: E501
        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, {
            "text": text,
            "color": scene.get("color", self.edit_color.text().strip() or "#FFFFFF"),
            "bg": scene.get("bg", "transparent"),
            "fontSize": int(scene.get("fontSize", self.spin_font_size.value())),
            "animation": scene.get("animation", "fade"),
            "duration": float(scene.get("duration", 2)),
        })
        self.list_scenes.addItem(item)

    def _add_scene(self):
        text = self.edit_scene_text.text().strip()
        if not text:
            return
        self._add_scene_item({
            "text": text,
            "animation": self.combo_scene_anim.currentText(),
            "duration": self.spin_scene_duration.value(),
            "color": self.edit_color.text().strip() or "#FFFFFF",
            "bg": "transparent",
            "fontSize": self.spin_font_size.value(),
        })
        self.edit_scene_text.clear()

    def _del_scene(self):
        for item in self.list_scenes.selectedItems():
            self.list_scenes.takeItem(self.list_scenes.row(item))

    def _apply_param_values(self, values):
        """将 AI 生成的参数值回填到表单和 scenes。"""
        if not values:
            return
        for key, val in values.items():
            if key in self._form_widgets:
                wtype, widget = self._form_widgets[key]
                self._set_widget_value(widget, wtype, val)
            elif key == "scenes":
                self.list_scenes.clear()
                for s in (val or []):
                    self._add_scene_item(s)
            elif key == "ratio" and val in RATIOS:
                self.combo_ratio.setCurrentText(val)
            elif key == "color":
                self.edit_color.setText(str(val))
            elif key == "bg":
                self.edit_bg.setText(str(val))
            elif key == "fontSize":
                with contextlib.suppress(ValueError, TypeError):
                    self.spin_font_size.setValue(int(val))
            elif key == "duration":
                with contextlib.suppress(ValueError, TypeError):
                    self.spin_duration.setValue(float(val))

    def _set_widget_value(self, widget, wtype, value):
        if wtype == "line":
            widget.setText(str(value))
        elif wtype == "int":
            with contextlib.suppress(ValueError, TypeError):
                widget.setValue(int(value))
        elif wtype == "float":
            with contextlib.suppress(ValueError, TypeError):
                widget.setValue(float(value))
        elif wtype == "color":
            widget.setText(str(value))
        elif wtype == "ratio":
            if str(value) in RATIOS:
                widget.setCurrentText(str(value))
        elif wtype == "bool":
            widget.setChecked(bool(value))
        elif wtype == "json":
            widget.setPlainText(parse_json_default(value))


    def _generate_script(self):
        if not self._current_template:
            self.show_warning("请先选择模板。")
            return
        text = self.edit_ai_prompt.text().strip()
        if not text:
            self.show_warning("请输入原始文案。")
            return
        self.btn_ai.setEnabled(False)
        self.btn_render.setEnabled(False)
        self.status.setText("正在生成 MG 参数...")
        w = MGScriptAIWorker(self._current_template, text)
        w.phase.connect(self.status.setText)
        w.finished.connect(self._on_script_generated)
        w.error.connect(self._on_worker_error)
        self.track_worker(w)
        w.start()

    def _on_script_generated(self, values):
        self._apply_param_values(values)
        self.btn_ai.setEnabled(True)
        self.btn_render.setEnabled(True)
        self.status.setText("AI 参数已生成，请检查后提交渲染。")


    def _on_render(self):
        if not self._current_template:
            self.show_warning("请先选择模板。")
            return
        try:
            values = self._collect_form_values()
            common = {
                "ratio": self.combo_ratio.currentText(),
                "scale": self.spin_scale.value(),
                "color": self.edit_color.text().strip() or "#FFFFFF",
                "bg": self.edit_bg.text().strip() or "#101418",
                "font_size": self.spin_font_size.value(),
                "duration": self.spin_duration.value(),
            }
            scenes = self._collect_scenes() if self.scenes_group.isVisible() else None
            request = build_mg_request(
                template=self._current_template,
                values=values,
                common=common,
                scenes=scenes,
            )
        except (KeyError, TypeError, ValueError) as e:
            self.show_warning(str(e))
            return
        has_content = bool(
            request.get("title") or request.get("text") or request.get("quote") or
            request.get("scenes") or request.get("subtitle")
        )
        if not has_content:
            self.show_warning("请至少填写标题、文案、引用或添加一个 scene。")
            return
        self.btn_render.setEnabled(False)
        self.btn_ai.setEnabled(False)
        self.pbar.setVisible(True)
        self.pbar.setValue(0)
        self.status.setText("正在提交 MG 渲染任务...")
        title = f"MG-{request.get('template', 'scene')}-{datetime.now().strftime('%m%d%H%M')}"  # noqa: E501
        self.worker = MGServerRenderWorker(request, title=title)
        self.worker.phase.connect(self.status.setText)
        self.worker.progress.connect(self.pbar.setValue)
        self.worker.finished.connect(self._on_render_done)
        self.worker.error.connect(self._on_worker_error)
        self.track_worker(self.worker)
        self.worker.start()

    def _on_render_done(self, local_path):
        self._last_out = local_path
        self.btn_render.setEnabled(True)
        self.btn_ai.setEnabled(True)
        self.pbar.setVisible(False)
        self.status.setText(f"完成： MG 素材已生成: {os.path.basename(local_path)}")
        self.lbl_result.setText(f"成片路径: {local_path}")
        template_id = self._current_template.get("id", "") if self._current_template else ""  # noqa: E501
        self._add_task_record(
            task_id=self.worker.task_id if self.worker else "",
            template=template_id,
            ratio=self.combo_ratio.currentText(),
            status="完成",
            progress=100,
            local_path=local_path,
        )
        self.mg_ready.emit(template_id, local_path)

    def _on_worker_error(self, e):
        self.btn_ai.setEnabled(True)
        self.btn_render.setEnabled(True)
        self.pbar.setVisible(False)
        self.status.setText(" 失败")
        self.show_error(str(e), "MG 处理失败")

    def _add_task_record(self, task_id, template, ratio, status, progress, local_path=""):  # noqa: E501
        self._tasks.insert(0, {
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "task_id": task_id,
            "template": template,
            "ratio": ratio,
            "status": status,
            "progress": progress,
            "local_path": local_path,
        })
        self._refresh_task_table()

    def _refresh_task_table(self):
        self.table_tasks.setRowCount(len(self._tasks))
        for i, rec in enumerate(self._tasks):
            self.table_tasks.setItem(i, 0, QTableWidgetItem(rec["time"]))
            self.table_tasks.setItem(i, 1, QTableWidgetItem(str(rec.get("task_id", ""))))  # noqa: E501
            self.table_tasks.setItem(i, 2, QTableWidgetItem(rec["template"]))
            self.table_tasks.setItem(i, 3, QTableWidgetItem(rec["ratio"]))
            self.table_tasks.setItem(i, 4, QTableWidgetItem(rec["status"]))
            self.table_tasks.setItem(i, 5, QTableWidgetItem(f"{rec['progress']}%"))
            action = "打开" if rec["local_path"] and os.path.isfile(rec["local_path"]) else ""  # noqa: E501
            self.table_tasks.setItem(i, 6, QTableWidgetItem(action))
        self.table_tasks.resizeColumnsToContents()

    def _on_task_cell_clicked(self, row, col):
        if col != 6 or row >= len(self._tasks):
            return
        path = self._tasks[row].get("local_path")
        if path and os.path.isfile(path) and os.name == "nt":
            os.startfile(path)

    # ---------- 外部调用入口 ----------
    def set_default_text(self, text):
        """供其他页面跳转时预填 AI 文案。"""
        self.edit_ai_prompt.setText(text or "")

    def set_template(self, template_id):
        """供其他页面指定模板，如 mg_intro / mg_countdown。"""
        self._select_template_by_id(template_id)

    def get_last_output(self):
        return self._last_out if self._last_out and os.path.isfile(self._last_out) else ""  # noqa: E501
