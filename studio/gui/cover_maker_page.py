# -*- coding: utf-8 -*-
"""
封面制作页（分层封面编辑器 + 基础 AI 建议文字）。

- 可上传封面模板（参考）与视频；从视频抽帧、抠图(rembg)、上传、即梦生成 作为图层图片来源。
- 图层化：背景 / 主体 / 标题 / 副标题（可增删、拖动、缩放、调透明度、改 z 序、单独编辑）。
- AI 建议：用配置的（视觉/文本）大模型，结合模板/视频帧/文案，建议标题与副标题文字。
- 导出 PNG，并可一键加入素材管理。

构图复刻（按模板版式自动排布）为后续步骤。
复用：抠图 gui.image_matting_page.RembgWorker；即梦 gui.dreamina_page.Text2ImageWorker。
"""
import os
import json
import base64
import subprocess
import shutil
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFrame,
    QWidget, QComboBox, QListWidget, QListWidgetItem, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsRectItem, QFileDialog, QSlider,
    QSpinBox, QColorDialog, QCheckBox, QInputDialog, QProgressBar, QSplitter, QTabWidget, QGroupBox, QFormLayout, QScrollArea,
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QFont, QPen
from PySide6.QtCore import Qt, Signal

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button, mdi_icon
from config.paths import COVER_OUTPUT_DIR, TMP_DIR, PROJECT_ROOT, WORKSPACE_ROOT
from gui.mg_template_utils import (
    RATIOS, FALLBACK_TEMPLATES, _param_meta, _template_backend, create_value_widget,
    widget_value, set_widget_value, color_row, merge_templates,
    fill_template_list, select_template_by_id,
)
from utils.template_server_client import list_templates as list_cover_templates, generate as generate_cover
from gui.template_render_worker import TemplateRenderWorker

class CoverTemplateLoadWorker(BaseWorker):
    """异步从服务端 /template/list?category=cover 拉取封面模板。"""
    finished = Signal(list)
    phase = Signal(str)

    def do_work(self):
        self.phase.emit("正在加载封面模板列表...")
        templates = list_cover_templates(category="cover", timeout=8)
        self.finished.emit(templates)




CANVAS_SIZES = {"16:9（横版）": (1280, 720), "9:16（竖版）": (720, 1280), "1:1（方形）": (1080, 1080)}
# 安全区内边距（左, 上, 右, 下，占画布比例）。竖版按短视频平台预留右侧按钮、底部字幕/进度。
SAFE_INSETS = {
    "16:9（横版）": (0.05, 0.05, 0.05, 0.08),
    "9:16（竖版）": (0.04, 0.08, 0.14, 0.18),
    "1:1（方形）": (0.05, 0.05, 0.05, 0.05),
}
# 平台预设：各朝向的安全区内边距（左,上,右,下 比例）。
SAFE_PRESETS = {
    "通用": SAFE_INSETS,
    "抖音": {"16:9（横版）": (0.05, 0.05, 0.05, 0.10), "9:16（竖版）": (0.04, 0.10, 0.16, 0.20),
             "1:1（方形）": (0.05, 0.05, 0.05, 0.06)},
    "视频号": {"16:9（横版）": (0.05, 0.05, 0.05, 0.08), "9:16（竖版）": (0.04, 0.08, 0.12, 0.16),
              "1:1（方形）": (0.05, 0.05, 0.05, 0.05)},
    "小红书": {"16:9（横版）": (0.05, 0.05, 0.05, 0.08), "9:16（竖版）": (0.05, 0.06, 0.06, 0.10),
              "1:1（方形）": (0.05, 0.05, 0.05, 0.08)},
}


def _find_ffmpeg():
    from utils.platform_utils import find_ffmpeg as _ff
    return _ff()


class FrameExtractWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, video_path, time_sec, out_path):
        super().__init__()
        self.video_path = video_path
        self.time_sec = time_sec
        self.out_path = out_path

    def do_work(self):
        os.makedirs(os.path.dirname(self.out_path), exist_ok=True)
        cmd = [_find_ffmpeg(), "-y", "-ss", str(self.time_sec), "-i", self.video_path,
               "-vframes", "1", "-q:v", "2", self.out_path]
        flags = 0x08000000 if os.name == "nt" else 0
        r = subprocess.run(cmd, capture_output=True, creationflags=flags)
        if r.returncode != 0 or not os.path.isfile(self.out_path):
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-300:] or "抽帧失败")
        self.finished.emit(self.out_path)


class CoverTextAIWorker(BaseWorker):
    """用（视觉/文本）大模型，结合文案与参考图，建议标题/副标题。"""
    finished = Signal(str, str)   # title, subtitle

    def __init__(self, ai_config, copy_text, ref_image=None):
        super().__init__()
        self.cfg = ai_config or {}
        self.copy_text = copy_text
        self.ref_image = ref_image  # 模板或视频帧路径（可选）

    def do_work(self):
        from utils.llm_proxy import llm_chat, llm_chat_messages
        use_vision = bool(self.ref_image and os.path.isfile(self.ref_image)
                          and self.cfg.get("llm_vision_model"))
        model = self.cfg.get("llm_vision_model") if use_vision else self.cfg.get("llm_model", "deepseek-v4-flash")

        sys_prompt = ("你是短视频封面文案专家。根据提供的文案（以及参考封面/视频帧）"
                      "提炼封面用的【标题】与【副标题】：标题≤10字、强冲击；副标题≤16字、补充信息。"
                      '只输出 JSON：{"title": "...", "subtitle": "..."}，不要多余内容。')
        user_text = f"文案：\n{self.copy_text or '（无）'}"
        if use_vision:
            with open(self.ref_image, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content = [
                {"type": "text", "text": user_text + "\n参考图见附件，可借鉴其风格与重点。"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
            text = llm_chat_messages(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": content}],
                model=model, temperature=0.6, timeout=90)
        else:
            text = llm_chat(sys_prompt, user_text, model=model, temperature=0.6, timeout=90)

        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
            self.finished.emit(str(data.get("title", "")).strip(), str(data.get("subtitle", "")).strip())
        except Exception:
            # 解析失败则把整段作为标题返回
            self.finished.emit(text[:20], "")


class CoverLayoutAIWorker(BaseWorker):
    """视觉模型分析模板【构图】：返回标题/副标题块的 归一化位置+字号比例+颜色（不含文字）。"""
    finished = Signal(dict)

    def __init__(self, ai_config, template_path):
        super().__init__()
        self.cfg = ai_config or {}
        self.template_path = template_path

    def do_work(self):
        from utils.llm_proxy import llm_chat_messages
        model = self.cfg.get("llm_vision_model", "")
        if not model:
            raise RuntimeError("构图复刻需要『视觉模型』。请到『大模型配置』填写视觉模型名称。")
        if not (self.template_path and os.path.isfile(self.template_path)):
            raise RuntimeError("请先上传封面模板。")
        with open(self.template_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        sys_prompt = (
            "你是封面版式分析专家。只分析这张封面模板图的【构图/版式】，定位 标题、副标题 文字块"
            "以及 主体(人物/产品) 区域的位置、大小、颜色。不要生成或臆测文字内容。严格只输出 JSON：\n"
            '{"title":{"x":0.0,"y":0.0,"size":0.0,"color":"#RRGGBB"},'
            '"subtitle":{"x":0.0,"y":0.0,"size":0.0,"color":"#RRGGBB"},'
            '"subject":{"x":0.0,"y":0.0,"size":0.0},'
            '"background":{"color":"#RRGGBB"}}\n'
            "文字块：x,y 为左上角归一化坐标(0~1)，size 为字高占画布高的比例。"
            "subject：x,y 为主体区域左上角归一化坐标，size 为主体宽度占画布宽的比例。"
            "background.color 为背景主色。")
        content = [
            {"type": "text", "text": "请分析此封面模板的 标题/副标题/主体/背景 构图（位置、大小、颜色）。"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
        text = llm_chat_messages(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": content}],
            model=model, temperature=0.4, timeout=120)
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        self.finished.emit(json.loads(text))


class CoverMakerPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.layers = []            # [{name, type, item, source, geom{ratio:{x,y,scale,font,visible}}}]
        self.current_video = ""
        self.template_path = ""
        self._prev_ratio = None
        self._worker = None
        self._templates = []
        self._current_template = None
        self._template_form_widgets = {}
        self._last_cover_png = ""
        self.safe_insets = {k: list(v) for k, v in SAFE_INSETS.items()}  # 可被用户/预设修改

    # ---------------- UI ----------------
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        heading = QLabel("🖼️ 封面制作（分层）")
        heading.setObjectName("heading")
        root.addWidget(heading)

        root.addWidget(self._build_top_bar())

        # 底部状态栏控件需先创建：「模板封面」tab 构建时（_load_templates）会引用 self.status / self.pbar
        srow = QHBoxLayout()
        self.status = QLabel(""); self.status.setObjectName("muted_text")
        srow.addWidget(self.status, 1)
        self.pbar = QProgressBar(); self.pbar.setVisible(False); self.pbar.setRange(0, 0); self.pbar.setMaximumWidth(160)
        srow.addWidget(self.pbar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_layer_tab(), "图层编辑")
        self.tabs.addTab(self._build_template_tab(), "模板封面")
        root.addWidget(self.tabs, 1)
        root.addLayout(srow)

        self._init_default_layers()
        self._sync_safe_spins()

    def _build_top_bar(self):
        card = QFrame(); card.setObjectName("card")
        lay = QHBoxLayout(card); lay.setContentsMargins(16, 10, 16, 10); lay.setSpacing(8)
        lay.addWidget(QLabel("画布"))
        self.combo_ratio = QComboBox(); self.combo_ratio.addItems(list(CANVAS_SIZES.keys()))
        self.combo_ratio.currentTextChanged.connect(self._on_ratio_changed)
        lay.addWidget(self.combo_ratio)
        b1 = QPushButton("上传模板(参考)"); b1.setObjectName("secondary_button"); b1.clicked.connect(self._upload_template)
        lay.addWidget(b1)
        b2 = QPushButton("上传视频"); b2.setObjectName("secondary_button"); b2.clicked.connect(self._upload_video)
        lay.addWidget(b2)
        self.chk_safe = QCheckBox("安全区"); self.chk_safe.setChecked(True)
        self.chk_safe.stateChanged.connect(self._update_safe_rect)
        lay.addWidget(self.chk_safe)
        self.lbl_src = QLabel("（未选模板/视频）"); self.lbl_src.setObjectName("muted_text")
        lay.addWidget(self.lbl_src, 1)
        b3 = mdi_button("文案→标题/副标题", "robot"); b3.setObjectName("secondary_button"); b3.clicked.connect(self._ai_suggest)
        lay.addWidget(b3)
        b5 = mdi_button("模板→复刻构图", "search"); b5.setObjectName("secondary_button"); b5.clicked.connect(self._replicate_layout)
        lay.addWidget(b5)
        b4 = mdi_button("导出当前", "save"); b4.setObjectName("secondary_button"); b4.clicked.connect(self._export)
        lay.addWidget(b4)
        b6 = mdi_button("导出横+竖", "save"); b6.setObjectName("primary_button"); b6.clicked.connect(self._export_both)
        lay.addWidget(b6)
        return card

    def _build_layers_panel(self):
        panel = QFrame(); panel.setObjectName("card")
        lay = QVBoxLayout(panel); lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(8)
        lay.addWidget(QLabel("图层"))
        self.layer_list = QListWidget()
        self.layer_list.currentRowChanged.connect(self._on_layer_selected)
        lay.addWidget(self.layer_list, 1)
        r1 = QHBoxLayout()
        ba = mdi_button("图片", "plus"); ba.setObjectName("secondary_button"); ba.clicked.connect(lambda: self._add_layer("image"))
        r1.addWidget(ba)
        bt = mdi_button("文字", "plus"); bt.setObjectName("secondary_button"); bt.clicked.connect(lambda: self._add_layer("text"))
        r1.addWidget(bt)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        for txt, fn in (("↑", lambda: self._move_layer(-1)), ("↓", lambda: self._move_layer(1)),
                        ("🗑", self._delete_layer)):
            b = QPushButton(txt); b.setObjectName("secondary_button"); b.setFixedWidth(40); b.clicked.connect(fn)
            r2.addWidget(b)
        self.chk_visible = QCheckBox("显示"); self.chk_visible.setChecked(True)
        self.chk_visible.stateChanged.connect(self._toggle_visible)
        r2.addWidget(self.chk_visible)
        lay.addLayout(r2)

        # 参考：模板缩略图 + 文案
        lay.addWidget(QLabel("参考"))
        self.tpl_thumb = QLabel("（未上传模板）")
        self.tpl_thumb.setObjectName("muted_text")
        self.tpl_thumb.setFixedHeight(90)
        self.tpl_thumb.setAlignment(Qt.AlignCenter)
        self.tpl_thumb.setStyleSheet("border:1px solid #3a3a3a; border-radius:4px;")
        lay.addWidget(self.tpl_thumb)
        self.copy_input = QTextEdit()
        self.copy_input.setPlaceholderText("封面参考文案（用于 AI 建议 / 构图复刻）…")
        self.copy_input.setFixedHeight(70)
        lay.addWidget(self.copy_input)
        bup = QPushButton("上传文案(txt)")
        bup.setObjectName("secondary_button")
        bup.clicked.connect(self._upload_copy)
        lay.addWidget(bup)
        return panel

    def _build_canvas(self):
        panel = QFrame(); panel.setObjectName("card")
        lay = QVBoxLayout(panel); lay.setContentsMargins(8, 8, 8, 8)
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.scene.selectionChanged.connect(self._on_scene_selection)
        # 安全区参考框（虚线、不可选、不参与导出，高 z 置顶）
        self.safe_rect = QGraphicsRectItem()
        pen = QPen(QColor("#00E0A0")); pen.setStyle(Qt.DashLine); pen.setWidthF(2.0); pen.setCosmetic(True)
        self.safe_rect.setPen(pen)
        self.safe_rect.setZValue(100000)
        self.scene.addItem(self.safe_rect)
        lay.addWidget(self.view)

        # 安全区可调：平台预设 + 左/上/右/下 内边距
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("安全区"))
        self.combo_safe = QComboBox(); self.combo_safe.addItems(list(SAFE_PRESETS.keys()))
        self.combo_safe.currentTextChanged.connect(self._apply_safe_preset)
        ctrl.addWidget(self.combo_safe)
        self.spin_safe = {}
        for key, lab in (("l", "左"), ("t", "上"), ("r", "右"), ("b", "下")):
            ctrl.addWidget(QLabel(lab))
            sp = QSpinBox(); sp.setRange(0, 49); sp.setSuffix("%")
            sp.valueChanged.connect(self._on_safe_spin)
            self.spin_safe[key] = sp
            ctrl.addWidget(sp)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        return panel

    def _build_edit_panel(self):
        panel = QFrame(); panel.setObjectName("card")
        self.edit_layout = QVBoxLayout(panel)
        self.edit_layout.setContentsMargins(12, 12, 12, 12); self.edit_layout.setSpacing(8)
        self.edit_title = QLabel("图层属性"); self.edit_title.setObjectName("card_title")
        self.edit_layout.addWidget(self.edit_title)

        # 图片图层控件
        self.img_box = QWidget(); ib = QVBoxLayout(self.img_box); ib.setContentsMargins(0, 0, 0, 0); ib.setSpacing(6)
        ib.addWidget(QLabel("图片来源"))
        for txt, fn in (("📁 上传图片", self._src_upload), ("🎞️ 视频抽帧", self._src_frame),
                        ("✂️ 抠图去背景", self._src_matting), ("🎨 即梦生成", self._src_dreamina)):
            b = QPushButton(txt); b.setObjectName("secondary_button"); b.clicked.connect(fn)
            ib.addWidget(b)
        ib.addWidget(QLabel("缩放"))
        self.img_scale = QSlider(Qt.Horizontal); self.img_scale.setRange(10, 300); self.img_scale.setValue(100)
        self.img_scale.valueChanged.connect(self._on_img_scale)
        ib.addWidget(self.img_scale)
        self.edit_layout.addWidget(self.img_box)

        # 文字图层控件
        self.txt_box = QWidget(); tb = QVBoxLayout(self.txt_box); tb.setContentsMargins(0, 0, 0, 0); tb.setSpacing(6)
        tb.addWidget(QLabel("文字内容"))
        self.txt_input = QTextEdit(); self.txt_input.setFixedHeight(70); self.txt_input.textChanged.connect(self._on_text_changed)
        tb.addWidget(self.txt_input)
        row = QHBoxLayout(); row.addWidget(QLabel("字号"))
        self.txt_size = QSpinBox(); self.txt_size.setRange(8, 400); self.txt_size.setValue(64); self.txt_size.valueChanged.connect(self._on_text_style)
        row.addWidget(self.txt_size)
        self.chk_bold = QCheckBox("粗体"); self.chk_bold.setChecked(True); self.chk_bold.stateChanged.connect(self._on_text_style)
        row.addWidget(self.chk_bold)
        self.btn_color = QPushButton("颜色"); self.btn_color.setObjectName("secondary_button"); self.btn_color.clicked.connect(self._pick_color)
        row.addWidget(self.btn_color)
        tb.addLayout(row)
        self.edit_layout.addWidget(self.txt_box)

        # 通用：不透明度
        self.edit_layout.addWidget(QLabel("不透明度"))
        self.opacity = QSlider(Qt.Horizontal); self.opacity.setRange(0, 100); self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self._on_opacity)
        self.edit_layout.addWidget(self.opacity)
        self.edit_layout.addStretch()
        self.img_box.setVisible(False); self.txt_box.setVisible(False)
        return panel

    # ---------------- 画布 / 图层 ----------------
    def _canvas_size(self):
        return CANVAS_SIZES[self.combo_ratio.currentText()]

    def _apply_canvas_rect(self):
        w, h = self._canvas_size()
        self.scene.setSceneRect(0, 0, w, h)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_safe_rect()

    def _update_safe_rect(self, *_):
        if not hasattr(self, "safe_rect"):
            return
        ratio = self.combo_ratio.currentText()
        w, h = CANVAS_SIZES[ratio]
        l, t, r, b = self.safe_insets.get(ratio, (0.05, 0.05, 0.05, 0.05))
        self.safe_rect.setRect(l * w, t * h, (1 - l - r) * w, (1 - t - b) * h)
        self.safe_rect.setVisible(self.chk_safe.isChecked())

    def _on_ratio_changed(self, new):
        # 切换朝向：先存旧朝向版式，再载入新朝向（首次则沿用当前位置）
        if self._prev_ratio and self._prev_ratio != new:
            self._save_geom(self._prev_ratio)
        self._apply_canvas_rect()
        self._load_geom(new)
        self._sync_safe_spins()
        self._prev_ratio = new

    def _sync_safe_spins(self):
        if not hasattr(self, "spin_safe"):
            return
        l, t, r, b = self.safe_insets[self.combo_ratio.currentText()]
        for key, val in (("l", l), ("t", t), ("r", r), ("b", b)):
            sp = self.spin_safe[key]
            sp.blockSignals(True); sp.setValue(int(round(val * 100))); sp.blockSignals(False)

    def _on_safe_spin(self, *_):
        ratio = self.combo_ratio.currentText()
        self.safe_insets[ratio] = [self.spin_safe[k].value() / 100.0 for k in ("l", "t", "r", "b")]
        self._update_safe_rect()

    def _apply_safe_preset(self, name):
        preset = SAFE_PRESETS.get(name)
        if not preset:
            return
        for ratio in self.safe_insets:
            if ratio in preset:
                self.safe_insets[ratio] = list(preset[ratio])
        self._sync_safe_spins()
        self._update_safe_rect()

    def _save_geom(self, ratio):
        for ly in self.layers:
            it = ly["item"]
            ly.setdefault("geom", {})[ratio] = {
                "x": it.x(), "y": it.y(),
                "scale": it.scale(),
                "font": it.font().pointSize() if ly["type"] == "text" else 0,
                "visible": it.isVisible(),
            }

    def _load_geom(self, ratio):
        for ly in self.layers:
            g = ly.get("geom", {}).get(ratio)
            if not g:
                continue
            it = ly["item"]
            it.setPos(g["x"], g["y"])
            it.setScale(g.get("scale", 1.0))
            it.setVisible(g.get("visible", True))
            if ly["type"] == "text" and g.get("font"):
                f = it.font(); f.setPointSize(g["font"]); it.setFont(f)

    def _init_default_layers(self):
        self._apply_canvas_rect()
        self._prev_ratio = self.combo_ratio.currentText()
        w, h = self._canvas_size()
        self._new_image_layer("背景")
        self._new_image_layer("主体")
        self._new_text_layer("标题", "标题", size=int(h * 0.09), y=int(h * 0.66))
        self._new_text_layer("副标题", "副标题", size=int(h * 0.05), y=int(h * 0.80))
        self._refresh_layer_list()
        if self.layer_list.count():
            self.layer_list.setCurrentRow(self.layer_list.count() - 1)

    def _new_image_layer(self, name):
        item = QGraphicsPixmapItem()
        item.setFlags(QGraphicsPixmapItem.ItemIsMovable | QGraphicsPixmapItem.ItemIsSelectable)
        self.scene.addItem(item)
        self.layers.append({"name": name, "type": "image", "item": item, "source": ""})
        self._reassign_z()
        return self.layers[-1]

    def _new_text_layer(self, name, text, size=64, y=0):
        item = QGraphicsTextItem(text)
        f = QFont(); f.setPointSize(size); f.setBold(True); item.setFont(f)
        item.setDefaultTextColor(QColor("#FFFFFF"))
        item.setFlags(QGraphicsTextItem.ItemIsMovable | QGraphicsTextItem.ItemIsSelectable)
        item.setPos(60, y or 60)
        self.scene.addItem(item)
        self.layers.append({"name": name, "type": "text", "item": item, "source": ""})
        self._reassign_z()
        return self.layers[-1]

    def _reassign_z(self):
        for i, ly in enumerate(self.layers):
            ly["item"].setZValue(i)

    def _refresh_layer_list(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for ly in self.layers:
            icon = "🖼️" if ly["type"] == "image" else "🅣"
            self.layer_list.addItem(QListWidgetItem(f"{icon} {ly['name']}"))
        self.layer_list.blockSignals(False)

    def _current_layer(self):
        row = self.layer_list.currentRow()
        if 0 <= row < len(self.layers):
            return self.layers[row]
        return None

    def _add_layer(self, kind):
        if kind == "image":
            self._new_image_layer(f"图片{len(self.layers)+1}")
        else:
            self._new_text_layer(f"文字{len(self.layers)+1}", "文字", size=48, y=120)
        self._refresh_layer_list()
        self.layer_list.setCurrentRow(len(self.layers) - 1)

    def _delete_layer(self):
        ly = self._current_layer()
        if not ly:
            return
        self.scene.removeItem(ly["item"])
        self.layers.remove(ly)
        self._reassign_z()
        self._refresh_layer_list()

    def _move_layer(self, delta):
        row = self.layer_list.currentRow()
        new = row + delta
        if row < 0 or new < 0 or new >= len(self.layers):
            return
        self.layers[row], self.layers[new] = self.layers[new], self.layers[row]
        self._reassign_z()
        self._refresh_layer_list()
        self.layer_list.setCurrentRow(new)

    def _toggle_visible(self, _state):
        ly = self._current_layer()
        if ly:
            ly["item"].setVisible(self.chk_visible.isChecked())

    # ---------------- 选中 / 属性面板 ----------------
    def _on_layer_selected(self, row):
        ly = self._current_layer()
        if not ly:
            self.img_box.setVisible(False); self.txt_box.setVisible(False)
            return
        self.scene.clearSelection()
        ly["item"].setSelected(True)
        self.edit_title.setText(f"图层属性 · {ly['name']}")
        self.chk_visible.setChecked(ly["item"].isVisible())
        self.opacity.blockSignals(True); self.opacity.setValue(int(ly["item"].opacity() * 100)); self.opacity.blockSignals(False)
        is_img = ly["type"] == "image"
        self.img_box.setVisible(is_img); self.txt_box.setVisible(not is_img)
        if is_img:
            self.img_scale.blockSignals(True); self.img_scale.setValue(int(ly["item"].scale() * 100)); self.img_scale.blockSignals(False)
        else:
            self.txt_input.blockSignals(True); self.txt_input.setPlainText(ly["item"].toPlainText()); self.txt_input.blockSignals(False)
            f = ly["item"].font()
            self.txt_size.blockSignals(True); self.txt_size.setValue(f.pointSize() if f.pointSize() > 0 else 64); self.txt_size.blockSignals(False)
            self.chk_bold.blockSignals(True); self.chk_bold.setChecked(f.bold()); self.chk_bold.blockSignals(False)

    def _on_scene_selection(self):
        items = self.scene.selectedItems()
        if not items:
            return
        for i, ly in enumerate(self.layers):
            if ly["item"] is items[0]:
                if self.layer_list.currentRow() != i:
                    self.layer_list.setCurrentRow(i)
                break

    def _on_opacity(self, v):
        ly = self._current_layer()
        if ly:
            ly["item"].setOpacity(v / 100.0)

    def _on_img_scale(self, v):
        ly = self._current_layer()
        if ly and ly["type"] == "image":
            ly["item"].setScale(v / 100.0)

    def _on_text_changed(self):
        ly = self._current_layer()
        if ly and ly["type"] == "text":
            ly["item"].setPlainText(self.txt_input.toPlainText())

    def _on_text_style(self):
        ly = self._current_layer()
        if ly and ly["type"] == "text":
            f = ly["item"].font(); f.setPointSize(self.txt_size.value()); f.setBold(self.chk_bold.isChecked())
            ly["item"].setFont(f)

    def _pick_color(self):
        ly = self._current_layer()
        if not ly or ly["type"] != "text":
            return
        c = QColorDialog.getColor(ly["item"].defaultTextColor(), self.parent_widget, "选择文字颜色")
        if c.isValid():
            ly["item"].setDefaultTextColor(c)

    # ---------------- 图片来源 ----------------
    def _set_current_image(self, path):
        ly = self._current_layer()
        if not ly or ly["type"] != "image" or not path or not os.path.isfile(path):
            return
        pm = QPixmap(path)
        if pm.isNull():
            self.show_warning("无法加载该图片。")
            return
        w, _h = self._canvas_size()
        if ly["name"] == "背景" and pm.width():
            ly["item"].setScale(1.0)
            pm = pm.scaledToWidth(w, Qt.SmoothTransformation)
        ly["item"].setPixmap(pm)
        ly["source"] = path
        self.status.setText(f"已设置图层「{ly['name']}」图片")

    def _src_upload(self):
        if not self._require_image_layer():
            return
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择图片", "",
                                           "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if f:
            self._set_current_image(f)

    def _src_frame(self):
        if not self._require_image_layer():
            return
        if not self.current_video:
            self.show_warning("请先在上方『上传视频』。")
            return
        t, ok = QInputDialog.getDouble(self.parent_widget, "抽帧时间", "从第几秒抽帧：", 1.0, 0.0, 100000.0, 1)
        if not ok:
            return
        out = os.path.join(TMP_DIR, f"cover_frame_{datetime.now().strftime('%H%M%S')}.png")
        self._run(FrameExtractWorker(self.current_video, t, out),
                  lambda p: self._set_current_image(p), "正在抽帧…")

    def _src_matting(self):
        ly = self._current_layer()
        if not self._require_image_layer():
            return
        if not ly.get("source"):
            self.show_warning("请先给该图层设置一张图片，再抠图去背景。")
            return
        try:
            from gui.image_matting_page import RembgWorker
        except Exception as e:
            self.show_error(f"无法加载抠图模块：{e}")
            return
        out = os.path.join(TMP_DIR, f"cover_cut_{datetime.now().strftime('%H%M%S')}.png")
        w = RembgWorker(ly["source"], out)
        self.pbar.setVisible(True); self.status.setText("正在抠图去背景…")
        w.finished.connect(lambda ok, path, err: (
            self._set_current_image(path) if ok else self.show_error(err or "抠图失败"),
            self.pbar.setVisible(False)))
        self.track_worker(w); w.start()

    def _src_dreamina(self):
        if not self._require_image_layer():
            return
        prompt, ok = QInputDialog.getText(self.parent_widget, "即梦生成", "画面提示词：")
        if not ok or not prompt.strip():
            return
        try:
            from gui.dreamina_page import Text2ImageWorker
        except Exception as e:
            self.show_error(f"无法加载即梦模块：{e}")
            return
        out_dir = os.path.join(TMP_DIR, f"cover_jm_{datetime.now().strftime('%H%M%S')}")
        w = Text2ImageWorker(prompt.strip(), "9:16", "", "", out_dir)
        self.pbar.setVisible(True); self.status.setText("即梦生成中…（需已登录）")

        def done(files, _sid):
            self.pbar.setVisible(False)
            if files:
                self._set_current_image(files[0])
        w.finished.connect(done)
        w.error.connect(lambda e: (self.pbar.setVisible(False),
                                   self.show_error(f"即梦生成失败：{e}\n可先到『即梦生成』页登录。")))
        self.track_worker(w); w.start()

    def _require_image_layer(self):
        ly = self._current_layer()
        if not ly or ly["type"] != "image":
            self.show_warning("请先在左侧选中一个【图片】图层。")
            return False
        return True

    # ---------------- 上传 / AI / 导出 ----------------
    def _upload_template(self):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择封面模板", "",
                                           "图片 (*.png *.jpg *.jpeg *.webp)")
        if f:
            self.template_path = f
            pm = QPixmap(f)
            if not pm.isNull():
                self.tpl_thumb.setPixmap(pm.scaledToHeight(86, Qt.SmoothTransformation))
            self._update_src_label()

    def _upload_copy(self):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择文案文件", "", "文本 (*.txt *.md)")
        if not f:
            return
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                self.copy_input.setPlainText(fh.read())
        except Exception as e:
            self.show_error(f"读取失败：{e}")

    def _upload_video(self):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择视频", "",
                                           "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.flv)")
        if f:
            self.current_video = f
            self._update_src_label()

    def _update_src_label(self):
        t = os.path.basename(self.template_path) if self.template_path else "无模板"
        v = os.path.basename(self.current_video) if self.current_video else "无视频"
        self.lbl_src.setText(f"模板：{t}　视频：{v}")

    def _ai_suggest(self):
        copy_text = self.copy_input.toPlainText().strip()
        if not copy_text:
            self.show_warning("请先在左侧『参考』填入文案（标题/副标题将据此生成）。")
            return
        # 文案 → 文字（纯文本，不参考模板）
        w = CoverTextAIWorker(self.ai_config, copy_text, None)
        self.pbar.setVisible(True); self.status.setText("AI 正在建议标题/副标题…")

        def done(title, subtitle):
            self.pbar.setVisible(False)
            self._set_text_layer("标题", title)
            self._set_text_layer("副标题", subtitle)
            self.status.setText("已填入 AI 建议，可继续编辑。")
        w.finished.connect(done)
        w.error.connect(lambda e: (self.pbar.setVisible(False), self.show_error(str(e), "AI 建议失败")))
        self.track_worker(w); w.start()

    def _set_text_layer(self, name, text):
        if not text:
            return
        for i, ly in enumerate(self.layers):
            if ly["type"] == "text" and ly["name"] == name:
                ly["item"].setPlainText(text)
                if self.layer_list.currentRow() == i:
                    self.txt_input.blockSignals(True); self.txt_input.setPlainText(text); self.txt_input.blockSignals(False)
                return

    def _replicate_layout(self):
        if not self.template_path:
            self.show_warning("请先在上方『上传模板(参考)』。")
            return
        w = CoverLayoutAIWorker(self.ai_config, self.template_path)
        self.pbar.setVisible(True); self.status.setText("正在按模板分析并复刻构图…")
        w.finished.connect(self._apply_layout)
        w.error.connect(lambda e: (self.pbar.setVisible(False), self.show_error(str(e), "构图复刻失败")))
        self.track_worker(w); w.start()

    def _apply_layout(self, data):
        self.pbar.setVisible(False)
        w, h = self._canvas_size()
        for name, key in (("标题", "title"), ("副标题", "subtitle")):
            d = data.get(key) or {}
            ly = next((l for l in self.layers if l["type"] == "text" and l["name"] == name), None)
            if not ly:
                continue
            it = ly["item"]
            try:
                if d.get("x") is not None and d.get("y") is not None:
                    it.setPos(float(d["x"]) * w, float(d["y"]) * h)
                if d.get("size"):
                    f = it.font(); f.setPointSize(max(8, int(float(d["size"]) * h))); it.setFont(f)
                if d.get("color"):
                    c = QColor(str(d["color"]))
                    if c.isValid():
                        it.setDefaultTextColor(c)
            except (ValueError, TypeError):
                pass
        # 主体：定位 + 按宽度比例缩放（图层已有图片才缩放）
        subj = data.get("subject") or {}
        sly = next((l for l in self.layers if l["type"] == "image" and l["name"] == "主体"), None)
        if sly and subj:
            it = sly["item"]
            try:
                if subj.get("x") is not None and subj.get("y") is not None:
                    it.setPos(float(subj["x"]) * w, float(subj["y"]) * h)
                pm = it.pixmap()
                if subj.get("size") and not pm.isNull() and pm.width():
                    it.setScale(max(0.05, float(subj["size"]) * w / pm.width()))
            except (ValueError, TypeError):
                pass
        # 背景：若背景图层为空且模板给了主色，则用纯色填充背景
        bg = data.get("background") or {}
        bly = next((l for l in self.layers if l["type"] == "image" and l["name"] == "背景"), None)
        if bly and bg.get("color") and bly["item"].pixmap().isNull():
            c = QColor(str(bg["color"]))
            if c.isValid():
                pm = QPixmap(w, h); pm.fill(c)
                bly["item"].setPixmap(pm); bly["item"].setScale(1.0); bly["item"].setPos(0, 0)
                bly["source"] = "(纯色背景)"
        self._on_layer_selected(self.layer_list.currentRow())
        self.status.setText("已按模板复刻构图（标题/副标题/主体位置·大小，背景主色；文字不变）。可微调。")

    def _run(self, worker, on_finished, busy_text):
        self.pbar.setVisible(True); self.status.setText(busy_text)
        worker.finished.connect(lambda *a: (self.pbar.setVisible(False), on_finished(*a)))
        worker.error.connect(lambda e: (self.pbar.setVisible(False), self.show_error(str(e))))
        self.track_worker(worker); worker.start()

    def _export(self):
        self.scene.clearSelection()
        w, h = self._canvas_size()
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.safe_rect.setVisible(False)
        self.scene.render(painter, target=img.rect(), source=self.scene.sceneRect())
        self._update_safe_rect()
        painter.end()
        os.makedirs(COVER_OUTPUT_DIR, exist_ok=True)
        out = os.path.join(COVER_OUTPUT_DIR, datetime.now().strftime("cover_%Y%m%d_%H%M%S.png"))
        if img.save(out, "PNG"):
            self.status.setText(f"已导出：{out}")
        else:
            self.show_error("导出失败。")

    def _render_ratio_to_png(self, ratio, out_path):
        w, h = CANVAS_SIZES[ratio]
        img = QImage(w, h, QImage.Format_ARGB32); img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.scene.clearSelection()
        self.safe_rect.setVisible(False)
        self.scene.render(painter, target=img.rect(), source=self.scene.sceneRect())
        painter.end()
        return img.save(out_path, "PNG")

    def _export_both(self):
        """按每个朝向各自的版式，导出横版 + 竖版两张封面。"""
        cur = self.combo_ratio.currentText()
        self._save_geom(cur)
        os.makedirs(COVER_OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outs = []
        for ratio, tag in (("16:9（横版）", "h"), ("9:16（竖版）", "v")):
            self.scene.setSceneRect(0, 0, *CANVAS_SIZES[ratio])
            self._load_geom(ratio)
            out = os.path.join(COVER_OUTPUT_DIR, f"cover_{ts}_{tag}.png")
            if self._render_ratio_to_png(ratio, out):
                outs.append(out)
        # 还原到操作前的朝向
        self.combo_ratio.setCurrentText(cur)
        self.scene.setSceneRect(0, 0, *CANVAS_SIZES[cur])
        self._load_geom(cur)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_safe_rect()
        if outs:
            self.status.setText("已导出：" + "、".join(os.path.basename(o) for o in outs))
        else:
            self.show_error("导出失败。")

    # -------------- 图层编辑标签页（原有能力保留） --------------
    def _build_layer_tab(self):
        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._build_layers_panel())
        body.addWidget(self._build_canvas())
        body.addWidget(self._build_edit_panel())
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 3)
        body.setStretchFactor(2, 1)
        return body

    # -------------- 模板封面标签页（服务端 /template/generate 渲染） --------------
    def _build_template_tab(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 左侧：模板库
        left = QFrame()
        left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 12, 12, 12)
        left_lay.setSpacing(8)
        left_lay.addWidget(QLabel("🎬 模板库"))
        self.list_templates = QListWidget()
        self.list_templates.currentItemChanged.connect(self._on_template_selected)
        left_lay.addWidget(self.list_templates, 1)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setObjectName("secondary_button")
        btn_refresh.clicked.connect(self._load_templates)
        left_lay.addWidget(btn_refresh)
        layout.addWidget(left, 1)

        # 中间：预览图
        mid = QFrame()
        mid.setObjectName("card")
        mid_lay = QVBoxLayout(mid)
        mid_lay.setContentsMargins(8, 8, 8, 8)
        self.lbl_template_preview = QLabel("选择模板并点击预览")
        self.lbl_template_preview.setAlignment(Qt.AlignCenter)
        self.lbl_template_preview.setMinimumHeight(240)
        self.lbl_template_preview.setStyleSheet("background:#1a1a1a;color:#888;")
        self.lbl_template_preview.setWordWrap(True)
        mid_lay.addWidget(self.lbl_template_preview)
        layout.addWidget(mid, 3)

        # 右侧：参数 + 预览/导出
        right = QFrame()
        right.setObjectName("card")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(8)
        right_lay.addWidget(QLabel("🎛 封面参数"))

        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("比例"))
        self.combo_template_ratio = QComboBox()
        self.combo_template_ratio.addItems(RATIOS)
        self.combo_template_ratio.setCurrentText("9:16")
        ratio_row.addWidget(self.combo_template_ratio)
        ratio_row.addStretch()
        right_lay.addLayout(ratio_row)

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
        right_lay.addWidget(self.template_params_group)
        self.template_params_group.setVisible(False)

        btn_row = QHBoxLayout()
        btn_preview = QPushButton("🔍 预览")
        btn_preview.setObjectName("secondary_button")
        btn_preview.clicked.connect(self._preview_template)
        btn_row.addWidget(btn_preview)
        btn_export = QPushButton("💾 导出封面")
        btn_export.setObjectName("primary_button")
        btn_export.clicked.connect(self._export_template)
        btn_row.addWidget(btn_export)
        right_lay.addLayout(btn_row)
        right_lay.addStretch()
        layout.addWidget(right, 2)

        self._load_templates()
        return panel

    # -------------- 模板相关方法 --------------
    def _load_templates(self):
        self._templates = list(FALLBACK_TEMPLATES)
        fill_template_list(self.list_templates, self._templates)
        w = CoverTemplateLoadWorker()
        w.finished.connect(self._on_templates_loaded)
        w.phase.connect(self.status.setText)
        self.track_worker(w)
        w.start()

    def _on_templates_loaded(self, server_templates):
        if not server_templates:
            self.status.setText("⚠ 未从服务端加载到模板，使用内置模板")
        self._templates = merge_templates(server_templates, FALLBACK_TEMPLATES)
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
        self.template_params_group.setVisible(True)
        defaults = template.get("defaults") or {}
        for key, val in defaults.items():
            if key in self._template_form_widgets:
                wtype, widget = self._template_form_widgets[key]
                set_widget_value(widget, wtype, val)

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

    def _build_template_request(self):
        if not self._current_template:
            raise ValueError("请先选择模板")
        template_id = self._current_template.get("id") or _template_backend(self._current_template)
        params = self._collect_template_params()
        # 封面模板生成使用 /template/generate；topic 可选，params 由服务端模板消费
        return {
            "template_id": template_id,
            "topic": params.get("title") or params.get("text") or "",
        }

    def _preview_template(self):
        try:
            req = self._build_template_request()
        except Exception as e:
            self.show_warning(str(e))
            return
        if not req.get("template_id"):
            self.show_warning("请先选择模板。")
            return
        self.pbar.setVisible(True)
        self.status.setText("正在提交封面模板生成任务...")

        def _submit():
            return generate_cover(req["template_id"], topic=req.get("topic", ""), top_k=1)

        from utils.thread_worker import TaskWorker as Worker
        worker = Worker(_submit)
        def _on_task_id(task_id):
            if not task_id:
                self.pbar.setVisible(False)
                self.status.setText("封面生成任务提交失败")
                self.show_error("封面模板生成任务提交失败，请检查服务端连接。", "错误")
                return
            self.status.setText(f"封面任务已提交：{task_id}")
            render_worker = TemplateRenderWorker(task_id, out_name=f"cover_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
            render_worker.phase.connect(self.status.setText)
            render_worker.progress.connect(self.pbar.setValue)
            render_worker.finished.connect(self._on_template_rendered)
            render_worker.error.connect(self._on_template_error)
            self._worker = render_worker
            self.track_worker(render_worker)
            render_worker.start()
        def _on_err(e):
            self.pbar.setVisible(False)
            self.status.setText("封面任务提交异常")
            self.show_error(f"提交异常：{e}", "错误")
        worker.finished.connect(_on_task_id)
        worker.error.connect(_on_err)
        self.track_worker(worker)
        worker.start()

    def _on_template_rendered(self, mp4_path):
        out = os.path.join(TMP_DIR, f"cover_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        self.status.setText("正在提取封面帧...")
        worker = FrameExtractWorker(mp4_path, 0, out)

        def _done(path):
            self.pbar.setVisible(False)
            self._set_template_preview(path)

        worker.finished.connect(_done)
        worker.error.connect(lambda e: (self.pbar.setVisible(False), self.show_error(str(e), "封面帧提取失败")))
        self.track_worker(worker)
        worker.start()

    def _on_template_error(self, e):
        self.pbar.setVisible(False)
        self.show_error(str(e), "封面渲染失败")

    def _set_template_preview(self, png_path):
        self._last_cover_png = png_path
        pm = QPixmap(png_path)
        if not pm.isNull():
            self.lbl_template_preview.setPixmap(
                pm.scaledToWidth(self.lbl_template_preview.width() - 20, Qt.SmoothTransformation)
            )
            self.status.setText(f"预览完成: {os.path.basename(png_path)}")
        else:
            self.lbl_template_preview.setText("无法显示预览")
            self.status.setText("预览图无效")

    def _export_template(self):
        if not self._last_cover_png or not os.path.isfile(self._last_cover_png):
            self.status.setText("先生成预览，再导出")
            self._preview_template()
            return
        os.makedirs(COVER_OUTPUT_DIR, exist_ok=True)
        out = os.path.join(COVER_OUTPUT_DIR, datetime.now().strftime("cover_%Y%m%d_%H%M%S.png"))
        import shutil
        shutil.copy(self._last_cover_png, out)
        self.status.setText(f"已导出: {out}")
