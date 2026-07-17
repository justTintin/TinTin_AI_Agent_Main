# -*- coding: utf-8 -*-
"""Windows 原生风格图标（Emoji 回退 + qtawesome 可选）。

所有图标优先使用 Emoji（Windows 原生渲染，无需额外字体），
qtawesome 作为可选增强。图标尺寸 18px。

用法：
    btn = mdi_button("播放", "play")
    icon = mdi_icon("save")
"""
from PySide6.QtWidgets import QPushButton, QLabel
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

# ── Emoji 映射（Windows 原生，不依赖任何第三方包）──
EMOJI = {
    # 媒体
    "play":        "▶️",
    "stop":        "⏹️",
    "pause":       "⏸️",
    "record":      "⏺️",
    "forward":     "⏩",
    "backward":    "⏪",
    "next":        "⏭️",
    "previous":    "⏮️",
    # 操作
    "save":        "💾",
    "search":      "🔍",
    "refresh":     "🔄",
    "close":       "❌",
    "plus":        "➕",
    "minus":       "➖",
    "edit":        "✏️",
    "pencil":      "✏️",
    "delete":      "🗑️",
    "copy":        "📋",
    "paste":       "📋",
    "cut":         "✂️",
    "undo":        "↩️",
    "check":       "✅",
    "download":    "⬇️",
    "upload":      "⬆️",
    "folder":      "📁",
    "file":        "📄",
    "open":        "📂",
    "share":       "🔗",
    # 方向
    "left":        "◀️",
    "right":       "▶️",
    "arrow_up":    "⬆️",
    "arrow_down":  "⬇️",
    "expand":      "🔽",
    "collapse":    "🔼",
    # 工具
    "cog":         "⚙️",
    "gear":        "⚙️",
    "wrench":      "🔧",
    "rocket":      "🚀",
    "flash":       "⚡",
    "broom":       "🧹",
    "lightbulb":   "💡",
    "pin":         "📌",
    "lock":        "🔒",
    "unlock":      "🔓",
    "key":         "🔑",
    # 媒体类型
    "video":       "🎬",
    "film":        "🎞️",
    "audio":       "🎵",
    "mic":         "🎤",
    "music":       "🎶",
    "image":       "🖼️",
    "camera":      "📷",
    "palette":     "🎨",
    "voice":       "🗣️",
    "clipboard":   "📋",
    # AI / 智能
    "robot":       "🤖",
    "brain":       "🧠",
    "robot2":      "🤖",
    "magic":       "🪄",
    "sparkles":    "✨",
    # 状态
    "star":        "⭐",
    "heart":       "❤️",
    "info":        "ℹ️",
    "warning":     "⚠️",
    "error":       "🚫",
    "success":     "✅",
    "question":    "❓",
    "hourglass":   "⏳",
    "clock":       "🕐",
    "eye":         "👁️",
    "eyes":        "👀",
    # 系统
    "home":        "🏠",
    "menu":        "☰",
    "server":      "🖥️",
    "link":        "🔗",
    "download2":   "📥",
    "upload2":     "📤",
    "fullscreen":  "🖥️",
    "restore":     "🪟",
    "layers":      "📚",
    "select_all":      "☑️",
    "deselect_all":    "☐",
    "sort":        "↕️",
    "filter":      "🔍",
    "autofix":     "🔧",
    "projector":   "📽️",
    "celebration": "🎉",
    "balance-scale": "⚖️",
    "volume":      "🔊",
    "mute":        "🔇",
    # 复选框
    "checkbox_marked": "☑️",
    "checkbox_blank":  "☐",
}

# qtawesome 作为增强（可选，未安装也不影响使用）
try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:
    _HAS_QTA = False


def mdi_icon(name: str, color: str = "#c9cdd4") -> QIcon:
    """获取图标。优先 qtawesome，回退 emoji。"""
    if _HAS_QTA:
        # 部分别名：历史代码用了非标准 mdi 图标名，这里统一映射到有效名，
        # 避免逐个改各页面调用点。映射不命中则原样加 mdi. 前缀。
        _ALIAS = {
            "audio": "volume-high", "backward": "skip-backward",
            "balance-scale": "scale", "celebration": "party-popper",
            "cut": "content-cut", "edit": "pencil", "gear": "cog",
            "left": "arrow-left", "mic": "microphone", "right": "arrow-right",
            "save": "content-save", "search": "magnify", "trash": "trash-can",
            "voice": "account-voice", "volume": "volume-high",
        }
        normalized = _ALIAS.get(name, name).replace("_", "-")
        mdi_name = "mdi." + normalized
        return qta.icon(mdi_name, color=color)
    # emoji fallback — 创建空图标（文字由按钮文本提供）
    return QIcon()


def mdi_button(text: str, icon_name: str = "", parent=None,
               color: str = "#c9cdd4", size: int = 18) -> QPushButton:
    """创建带图标的按钮。Emoji 直接加在文本前面。"""
    if icon_name and icon_name in EMOJI:
        text = EMOJI[icon_name] + " " + text
    btn = QPushButton(text, parent)
    if icon_name and _HAS_QTA:
        btn.setIcon(mdi_icon(icon_name, color))
        btn.setIconSize(QSize(size, size))
    return btn


def emoji_icon(name: str) -> str:
    """直接返回 emoji 字符，用于 QLabel 等。"""
    return EMOJI.get(name, "❓")


def emoji_button(text: str, emoji: str = "", parent=None) -> QPushButton:
    """创建纯 Emoji 按钮（不依赖 qtawesome）。"""
    if emoji:
        text = emoji + " " + text
    return QPushButton(text, parent)
