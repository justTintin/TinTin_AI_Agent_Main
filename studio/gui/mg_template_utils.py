# -*- coding: utf-8 -*-
"""MG / template driven pages shared helpers.

Provides:
- Built-in fallback templates and parameter metadata
- Generic template parameter form widgets
- A worker to load /mg/templates from the server
- UI helpers for QListWidget based template libraries
"""
import json
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QTextEdit,
    QWidget, QListWidget, QListWidgetItem, QColorDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from utils.base_worker import BaseWorker
from utils.mg_server_client import list_templates
from utils.logger_utils import log

RATIOS = ["9:16", "16:9", "1:1", "3:4", "4:3"]
ANIMATIONS = ["fade", "slide_up", "scale", "typewriter", "pulse"]
CUSTOM_BACKENDS = [
    "mg_scene", "mg_intro", "mg_outro", "mg_countdown", "mg_quote",
]

FALLBACK_TEMPLATES = [
    {"id": "mg_scene", "name": "通用场景", "description": "通过 scenes 列表渲染多段文字", "is_builtin": True},
    {"id": "mg_intro", "name": "片头", "description": "大标题 + 副标题开场", "is_builtin": True},
    {"id": "mg_outro", "name": "片尾", "description": "结尾文字 + 关注语", "is_builtin": True},
    {"id": "mg_countdown", "name": "倒计时", "description": "数字倒计时，0 显示 GO", "is_builtin": True},
    {"id": "mg_quote", "name": "名言金句", "description": "名言引用：金句 + 作者", "is_builtin": True},
]

BUILTIN_PARAM_META = {
    "title": ("line", "标题"),
    "subtitle": ("line", "副标题"),
    "text": ("line", "正文"),
    "subtext": ("line", "辅助文字"),
    "quote": ("line", "名言内容"),
    "author": ("line", "作者/来源"),
    "start": ("int", "起始值"),
    "end": ("int", "结束值"),
    "scenes": ("scenes", "场景列表"),
    "color": ("color", "文字颜色"),
    "bg": ("color", "背景颜色"),
    "fontSize": ("int", "字号"),
    "duration": ("float", "时长(秒)"),
    "ratio": ("ratio", "比例"),
    "scale": ("float", "缩放"),
}

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
        "title": "标题文案",
        "subtitle": "副标题文案",
        "text": "正文",
        "subtext": "辅助文字",
        "quote": "名言内容",
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


def _parse_json_default(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return value
    return str(value)


def _param_meta(param):
    """Normalize a template param definition to (key, widget_type, label, default)."""
    if isinstance(param, str):
        key = param
        meta = BUILTIN_PARAM_META.get(key, ("line", key))
        return key, meta[0], meta[1], _default_for_builtin(key)
    if isinstance(param, dict):
        key = param.get("name") or param.get("key")
        t = (param.get("type") or "string").lower()
        widget_type = CUSTOM_TYPE_MAP.get(t, "line")
        label = param.get("label") or param.get("desc") or key or "参数"
        default = param.get("default")
        if widget_type == "json":
            default = _parse_json_default(default)
        return key, widget_type, label, default
    return None, None, None, None


def _template_backend(template):
    """Return the Remotion backend id for a template.

    Built-ins use their own id; custom templates use their backend field.
    """
    if template.get("is_builtin") or template.get("builtin"):
        return template.get("id")
    return template.get("backend") or template.get("id")


def create_value_widget(wtype, default, parent=None):
    """Create a value widget for a given parameter type."""
    if wtype == "line":
        w = QLineEdit(parent)
        w.setText(str(default or ""))
        return w
    if wtype == "int":
        w = QSpinBox(parent)
        w.setRange(0, 99999)
        try:
            w.setValue(int(default or 0))
        except Exception:
            w.setValue(0)
        return w
    if wtype == "float":
        w = QDoubleSpinBox(parent)
        w.setRange(0, 9999)
        w.setSingleStep(0.5)
        try:
            w.setValue(float(default or 0))
        except Exception:
            w.setValue(0.0)
        return w
    if wtype == "color":
        w = QLineEdit(parent)
        w.setText(str(default or "#FFFFFF"))
        return w
    if wtype == "ratio":
        w = QComboBox(parent)
        w.addItems(RATIOS)
        w.setCurrentText(str(default or "9:16"))
        return w
    if wtype == "bool":
        w = QCheckBox(parent)
        w.setChecked(bool(default))
        return w
    if wtype == "json":
        w = QTextEdit(parent)
        w.setPlainText(_parse_json_default(default))
        w.setMaximumHeight(120)
        return w
    # fallback
    w = QLineEdit(parent)
    w.setText(str(default or ""))
    return w


def widget_value(widget, wtype):
    """Read current value from a widget created by create_value_widget."""
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
        try:
            return json.loads(txt)
        except Exception:
            return txt
    return None


def set_widget_value(widget, wtype, value):
    """Set widget value."""
    if wtype == "line":
        widget.setText(str(value))
    elif wtype == "int":
        try:
            widget.setValue(int(value))
        except Exception:
            pass
    elif wtype == "float":
        try:
            widget.setValue(float(value))
        except Exception:
            pass
    elif wtype == "color":
        widget.setText(str(value))
    elif wtype == "ratio":
        if str(value) in RATIOS:
            widget.setCurrentText(str(value))
    elif wtype == "bool":
        widget.setChecked(bool(value))
    elif wtype == "json":
        widget.setPlainText(_parse_json_default(value))


def color_row(edit, parent=None):
    """Return a widget row with a color line edit + color picker button."""
    row = QWidget(parent)
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    edit.setFixedWidth(120)
    h.addWidget(edit)
    btn = QPushButton("选")
    btn.setObjectName("secondary_button")
    btn.setFixedWidth(40)

    def _pick():
        c = QColorDialog.getColor(QColor(edit.text() or "#FFFFFF"), row, "选择颜色")
        if c.isValid():
            edit.setText(c.name().upper())

    btn.clicked.connect(_pick)
    h.addWidget(btn)
    h.addStretch()
    return row


def merge_templates(server_templates, fallback_templates):
    """Merge server templates with fallback builtins.

    Server entries override fallbacks. Missing name/description/params are
    backfilled from the fallback entry when available.
    """
    merged = {t["id"]: t for t in fallback_templates}
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
    return list(merged.values())


def fill_template_list(list_widget, templates, current_id=None):
    """Populate a QListWidget with built-in/custom template sections."""
    list_widget.clear()
    builtins = [t for t in templates if t.get("is_builtin") or t.get("builtin")]
    customs = [t for t in templates if not (t.get("is_builtin") or t.get("builtin"))]

    if builtins:
        header = QListWidgetItem("━━ 内置模板 ━━")
        header.setFlags(Qt.NoItemFlags)
        header.setForeground(Qt.GlobalColor.gray)
        list_widget.addItem(header)
        for t in builtins:
            item = QListWidgetItem(t.get("name", t.get("id", "")))
            item.setData(Qt.UserRole, t)
            item.setToolTip(t.get("description", ""))
            list_widget.addItem(item)

    if customs:
        header = QListWidgetItem("━━ 自定义模板 ━━")
        header.setFlags(Qt.NoItemFlags)
        header.setForeground(Qt.GlobalColor.gray)
        list_widget.addItem(header)
        for t in customs:
            backend = t.get("backend", "")
            label = t.get("name", t.get("id", ""))
            if backend:
                label += f" [{backend}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, t)
            item.setToolTip(t.get("description", ""))
            list_widget.addItem(item)

    # select first selectable item
    for i in range(list_widget.count()):
        if list_widget.item(i).flags() & Qt.ItemIsSelectable:
            list_widget.setCurrentRow(i)
            break

    if current_id:
        select_template_by_id(list_widget, current_id)


def select_template_by_id(list_widget, template_id):
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        t = item.data(Qt.UserRole)
        if t and t.get("id") == template_id:
            list_widget.setCurrentItem(item)
            return True
    return False


class MGTemplateLoadWorker(BaseWorker):
    """Asynchronously fetch /mg/templates."""
    finished = Signal(list)
    phase = Signal(str)

    def do_work(self):
        self.phase.emit("正在加载 MG 模板列表...")
        templates = list_templates(timeout=8)
        self.finished.emit(templates)