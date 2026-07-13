# -*- coding: utf-8 -*-
"""
MG 动画（Remotion）页。

用 Remotion（编程式）渲染 MG 动态图形素材：动态标题 / 逐字弹出字幕 / 数字增长 / 下三分之一字幕条。
选模板 → 填参数 → 渲染出 mp4 → 可加入素材管理。首次需点「安装依赖」。

客户端见 utils/remotion_client.py，工程在 studio/remotion/。
"""
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame, QWidget,
    QComboBox, QSpinBox, QFormLayout, QColorDialog, QProgressBar,
)
from PySide6.QtCore import Signal

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.remotion_client import TEMPLATES, install, render, is_installed, node_ok
from config.paths import MG_OUTPUT_DIR


class MGInstallWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(bool)

    def do_work(self):
        install(on_line=lambda ln: self.phase.emit(ln[-80:]))
        self.finished.emit(True)


class MGRenderWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, comp_id, props, out_path):
        super().__init__()
        self.comp_id = comp_id; self.props = props; self.out_path = out_path

    def do_work(self):
        render(self.comp_id, self.props, self.out_path, on_line=lambda ln: self.phase.emit(ln[-80:]))
        self.finished.emit(self.out_path)


class MGAnimationPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.media = MediaLibraryManager()
        self.param_widgets = {}     # key -> (widget, type)
        self.worker = None
        self._last_out = ""

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(14)

        heading = QLabel("🎞️ MG 动画（Remotion）")
        heading.setObjectName("heading")
        root.addWidget(heading)
        sub = QLabel("编程式渲染 MG 动态图形素材：动态标题 / 逐字字幕 / 数字增长 / 下三分之一。首次请先「安装依赖」。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        # 依赖状态条
        dep = QHBoxLayout()
        self.lbl_dep = QLabel("")
        dep.addWidget(self.lbl_dep, 1)
        self.btn_install = QPushButton("⬇️ 安装依赖")
        self.btn_install.setObjectName("secondary_button")
        self.btn_install.clicked.connect(self._install)
        dep.addWidget(self.btn_install)
        root.addLayout(dep)

        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(20, 16, 20, 16); cl.setSpacing(10)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("模板"))
        self.combo_template = QComboBox()
        for t in TEMPLATES:
            self.combo_template.addItem(t["name"], t["id"])
        self.combo_template.currentIndexChanged.connect(self._rebuild_form)
        trow.addWidget(self.combo_template, 1)
        cl.addLayout(trow)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setSpacing(8)
        cl.addWidget(self.form_host)

        brow = QHBoxLayout()
        brow.addStretch()
        self.btn_render = QPushButton("🎬 渲染 MG 素材")
        self.btn_render.setObjectName("primary_button")
        self.btn_render.clicked.connect(self._render)
        brow.addWidget(self.btn_render)
        cl.addLayout(brow)
        root.addWidget(card)

        rrow = QHBoxLayout()
        self.status = QLabel("就绪"); self.status.setObjectName("muted_text")
        rrow.addWidget(self.status, 1)
        self.pbar = QProgressBar(); self.pbar.setVisible(False); self.pbar.setRange(0, 0); self.pbar.setMaximumWidth(160)
        rrow.addWidget(self.pbar)
        self.btn_open = QPushButton("打开"); self.btn_open.setObjectName("secondary_button")
        self.btn_open.clicked.connect(self._open); self.btn_open.setEnabled(False)
        rrow.addWidget(self.btn_open)
        self.btn_media = QPushButton("加入素材管理"); self.btn_media.setObjectName("secondary_button")
        self.btn_media.clicked.connect(self._to_media); self.btn_media.setEnabled(False)
        rrow.addWidget(self.btn_media)
        root.addLayout(rrow)
        root.addStretch()

        self._rebuild_form()
        self._refresh_dep()

    # ---------- 依赖 ----------
    def _refresh_dep(self):
        if not node_ok():
            self.lbl_dep.setText("⚠️ 未检测到 Node/npm，请先安装 Node.js。")
            self.btn_install.setEnabled(False)
        elif is_installed():
            self.lbl_dep.setText("✅ Remotion 依赖已就绪。")
            self.btn_install.setEnabled(True); self.btn_install.setText("重新安装依赖")
        else:
            self.lbl_dep.setText("⬇️ 首次使用请先安装 Remotion 依赖（较大，含无头 Chrome）。")
            self.btn_install.setEnabled(True)

    def _install(self):
        self.btn_install.setEnabled(False); self.pbar.setVisible(True)
        self.status.setText("正在安装 Remotion 依赖（可能数分钟）…")
        w = MGInstallWorker()
        w.phase.connect(self.status.setText)
        w.finished.connect(lambda ok: (self.pbar.setVisible(False), self.status.setText("依赖安装完成。"), self._refresh_dep()))
        w.error.connect(lambda e: (self.pbar.setVisible(False), self.btn_install.setEnabled(True),
                                   self.show_error(str(e), "安装失败")))
        self.track_worker(w); w.start()

    # ---------- 参数表单 ----------
    def _current_template(self):
        tid = self.combo_template.currentData()
        return next((t for t in TEMPLATES if t["id"] == tid), TEMPLATES[0])

    def _rebuild_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.param_widgets = {}
        for p in self._current_template()["params"]:
            t = p["type"]
            if t == "number":
                w = QSpinBox(); w.setRange(-1000000000, 1000000000); w.setValue(int(p["default"]))
            elif t == "color":
                w = self._color_field(str(p["default"]))
            else:
                w = QLineEdit(str(p["default"]))
            self.param_widgets[p["key"]] = (w, t)
            self.form.addRow(QLabel(p["label"]), w)

    def _color_field(self, default_hex):
        box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        edit = QLineEdit(default_hex)
        btn = QPushButton("🎨"); btn.setObjectName("secondary_button"); btn.setFixedWidth(40)
        btn.clicked.connect(lambda: self._pick_color(edit))
        h.addWidget(edit, 1); h.addWidget(btn)
        box._edit = edit  # 便于取值
        return box

    def _pick_color(self, edit):
        from PySide6.QtGui import QColor
        c = QColorDialog.getColor(QColor(edit.text() or "#FFFFFF"), self.parent_widget, "选择颜色")
        if c.isValid():
            edit.setText(c.name().upper())

    def _collect_props(self):
        props = {}
        for key, (w, t) in self.param_widgets.items():
            if t == "number":
                props[key] = w.value()
            elif t == "color":
                props[key] = w._edit.text().strip() or "#FFFFFF"
            else:
                props[key] = w.text()
        return props

    def set_default_text(self, text):
        """供分镜等处跳转时预填主文本参数（title/text/label 优先）。"""
        if not text:
            return
        for key in ("title", "text", "label"):
            if key in self.param_widgets:
                w, t = self.param_widgets[key]
                if t == "text":
                    w.setText(text)
                    return

    # ---------- 渲染 ----------
    def _render(self):
        if not is_installed():
            self.show_warning("请先点『安装依赖』安装 Remotion。")
            return
        comp = self.combo_template.currentData()
        out = os.path.join(MG_OUTPUT_DIR, datetime.now().strftime(f"mg_{comp}_%Y%m%d_%H%M%S.mp4"))
        self.btn_render.setEnabled(False); self.pbar.setVisible(True)
        self.btn_open.setEnabled(False); self.btn_media.setEnabled(False)
        self.status.setText("正在渲染 MG 素材…")
        self.worker = MGRenderWorker(comp, self._collect_props(), out)
        self.worker.phase.connect(self.status.setText)
        self.worker.finished.connect(self._done)
        self.worker.error.connect(self._err)
        self.track_worker(self.worker); self.worker.start()

    def _done(self, out):
        self._last_out = out
        self.btn_render.setEnabled(True); self.pbar.setVisible(False)
        self.btn_open.setEnabled(True); self.btn_media.setEnabled(True)
        self.status.setText(f"✅ MG 素材已生成：{out}")

    def _err(self, e):
        self.btn_render.setEnabled(True); self.pbar.setVisible(False)
        self.status.setText("渲染失败。")
        self.show_error(str(e), "MG 渲染失败")

    def _open(self):
        if self._last_out and os.path.isfile(self._last_out) and os.name == "nt":
            os.startfile(self._last_out)  # noqa

    def _to_media(self):
        if self._last_out and os.path.isfile(self._last_out):
            self.media.add_mount(MG_OUTPUT_DIR, kind="项目", group="MG动画", tags=["MG", "Remotion"])
            self.show_info("已把 MG 输出目录加入素材管理。")
