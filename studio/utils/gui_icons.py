# -*- coding: utf-8 -*-
"""Material Design 扁平图标（qdawesome mdi 系列）。

所有图标统一 24dp 大小，与 Google Material Design 规范一致。
按钮使用方式：btn = mdi_button("播放", "play")
"""
import qtawesome as qta
from PySide6.QtWidgets import QPushButton, QLabel
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

# 图标名 → mdi 名称映射
MDI = {
    "play":       "mdi.play",
    "stop":       "mdi.stop",
    "save":       "mdi.content-save",
    "search":     "mdi.magnify",
    "refresh":    "mdi.refresh",
    "rocket":     "mdi.rocket-launch",
    "flash":      "mdi.flash",
    "folder":     "mdi.folder-open",
    "cut":        "mdi.content-cut",
    "cog":        "mdi.cog",
    "left":       "mdi.chevron-left",
    "right":      "mdi.chevron-right",
    "undo":       "mdi.undo",
    "check":      "mdi.check",
    "close":      "mdi.close",
    "plus":       "mdi.plus",
    "minus":      "mdi.minus",
    "download":   "mdi.download",
    "upload":     "mdi.upload",
    "edit":       "mdi.pencil",
    "delete":     "mdi.delete",
    "copy":       "mdi.content-copy",
    "link":       "mdi.link-variant",
    "eye":        "mdi.eye",
    "lock":       "mdi.lock",
    "unlock":     "mdi.lock-open",
    "home":       "mdi.home",
    "menu":       "mdi.menu",
    "arrow_up":   "mdi.arrow-up",
    "arrow_down": "mdi.arrow-down",
    "open":       "mdi.open-in-new",
    "server":     "mdi.server",
    "image":      "mdi.image",
    "video":      "mdi.video",
    "audio":      "mdi.microphone",
    "voice":      "mdi.account-voice",
    "robot":      "mdi.robot",
    "brain":      "mdi.brain",  # for AI
    "checkbox_marked": "mdi.checkbox-marked",
    "checkbox_blank":  "mdi.checkbox-blank-outline",
    "star":       "mdi.star",
    "info":       "mdi.information",
    "warning":    "mdi.alert",
    "error":      "mdi.alert-circle",
    "success":    "mdi.check-circle",
    "filter":     "mdi.filter-variant",
    "sort":       "mdi.sort",
    "expand":     "mdi.chevron-down",
    "collapse":   "mdi.chevron-up",
    "layers":     "mdi.layers",
    "palette":    "mdi.palette",
    "fullscreen": "mdi.fullscreen",
    "pip":        "mdi.picture-in-picture-bottom-right",
    "restore":    "mdi.restore",
    "autofix":    "mdi.auto-fix",
    "select_all":     "mdi.select-all",
    "deselect_all":   "mdi.select-remove",
}


def mdi_icon(name: str, color: str = "#c9cdd4") -> QIcon:
    """取 Material Design 图标。"""
    mdi_name = MDI.get(name, "mdi.help-circle")
    return qta.icon(mdi_name, color=color)


def mdi_button(text: str, icon_name: str = "", parent=None, color: str = "#c9cdd4", size: int = 18) -> QPushButton:
    """创建带 Material 图标的按钮。"""
    btn = QPushButton(text, parent)
    if icon_name:
        btn.setIcon(mdi_icon(icon_name, color))
        btn.setIconSize(QSize(size, size))
    return btn
