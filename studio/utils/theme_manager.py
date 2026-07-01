"""
主题管理器 — 支持跟随系统 / 暗黑 / 炫白三套主题。
"""
import json
import os
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

_THEME_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "theme.json")

THEME_OPTIONS = ["system", "dark", "light"]


def get_saved_theme() -> str:
    """读取保存的主题设置，默认 'system'。"""
    try:
        with open(_THEME_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        theme = data.get("theme", "system")
        if theme in THEME_OPTIONS:
            return theme
    except Exception:
        pass
    return "system"


def save_theme(theme: str):
    """保存主题设置。"""
    os.makedirs(os.path.dirname(_THEME_CONFIG_FILE), exist_ok=True)
    with open(_THEME_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"theme": theme}, f)


def _is_system_dark() -> bool:
    """检测系统是否为深色模式。"""
    try:
        import darkdetect
        return darkdetect.isDark()
    except ImportError:
        return True  # 默认深色


def get_effective_theme() -> str:
    """获取实际生效的主题（system 时自动判断）。"""
    theme = get_saved_theme()
    if theme == "system":
        return "dark" if _is_system_dark() else "light"
    return theme


def _create_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1a1a1c"))
    palette.setColor(QPalette.WindowText, QColor("#ffffff"))
    palette.setColor(QPalette.Base, QColor("#222224"))
    palette.setColor(QPalette.AlternateBase, QColor("#1c1c1e"))
    palette.setColor(QPalette.Text, QColor("#ffffff"))
    palette.setColor(QPalette.Button, QColor("#2c2c2e"))
    palette.setColor(QPalette.ButtonText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#3b82f6"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1a1a1c"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor("#3b82f6"))
    palette.setColor(QPalette.LinkVisited, QColor("#8b5cf6"))
    return palette


def _create_light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#ffffff"))
    palette.setColor(QPalette.WindowText, QColor("#1a1a1c"))
    palette.setColor(QPalette.Base, QColor("#f8f9fa"))
    palette.setColor(QPalette.AlternateBase, QColor("#f0f1f3"))
    palette.setColor(QPalette.Text, QColor("#1a1a1c"))
    palette.setColor(QPalette.Button, QColor("#e9ecef"))
    palette.setColor(QPalette.ButtonText, QColor("#1a1a1c"))
    palette.setColor(QPalette.Highlight, QColor("#3b82f6"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#1a1a1c"))
    palette.setColor(QPalette.Link, QColor("#3b82f6"))
    palette.setColor(QPalette.LinkVisited, QColor("#8b5cf6"))
    return palette


def apply_theme(app: QApplication):
    """根据保存的设置应用主题（调色板 + QSS 样式表）。"""
    effective = get_effective_theme()
    if effective == "light":
        app.setPalette(_create_light_palette())
        from ui.gui_styles_light import LIGHT_STYLE_SHEET
        app.setStyleSheet(LIGHT_STYLE_SHEET)
    else:
        app.setPalette(_create_dark_palette())
        from ui.gui_styles import STYLE_SHEET
        app.setStyleSheet(STYLE_SHEET)
