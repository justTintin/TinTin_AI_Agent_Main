# -*- coding: utf-8 -*-
"""图标名到文字标签的映射（qtawesome 可用时使用 MDI 图标，否则回退为文字标签）。

用法：
    btn = mdi_button("播放", "play")
    icon = mdi_icon("save")
"""
from PySide6.QtWidgets import QPushButton, QLabel, QApplication, QStyle
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

# ── Qt 标准图标映射（不依赖 qtawesome，保证所有平台都有图标）──
_STD_ICON_MAP = {
    "play":     QStyle.SP_MediaPlay,
    "pause":    QStyle.SP_MediaPause,
    "stop":     QStyle.SP_MediaStop,
    "previous": QStyle.SP_MediaSkipBackward,
    "next":     QStyle.SP_MediaSkipForward,
    "backward": QStyle.SP_MediaSeekBackward,
    "forward":  QStyle.SP_MediaSeekForward,
    "left":     QStyle.SP_ArrowLeft,
    "right":    QStyle.SP_ArrowRight,
    "up":       QStyle.SP_ArrowUp,
    "down":     QStyle.SP_ArrowDown,
}


def std_icon(name: str) -> QIcon:
    """返回 Qt 标准图标（名称大小写不敏感），未映射时返回空图标。"""
    key = name.lower()
    if key not in _STD_ICON_MAP:
        return QIcon()
    app = QApplication.instance()
    if app is None:
        return QIcon()
    return app.style().standardIcon(_STD_ICON_MAP[key])

# ── 文字标签映射（qtawesome 不可用时，作为按钮前缀提示）──
ICON_LABEL = {
    # 媒体
    "play":        "播放",
    "stop":        "停止",
    "pause":       "暂停",
    "record":      "录制",
    "forward":     "前进",
    "backward":    "后退",
    "next":        "下一个",
    "previous":    "上一个",
    # 操作
    "save":        "保存",
    "search":      "搜索",
    "refresh":     "刷新",
    "close":       "关闭",
    "plus":        "添加",
    "minus":       "移除",
    "edit":        "编辑",
    "pencil":      "编辑",
    "delete":      "删除",
    "copy":        "复制",
    "paste":       "粘贴",
    "cut":         "剪切",
    "undo":        "撤销",
    "check":       "完成",
    "download":    "下载",
    "upload":      "上传",
    "folder":      "文件夹",
    "file":        "文件",
    "open":        "打开",
    "share":       "链接",
    # 方向
    "left":        "左",
    "right":       "右",
    "arrow_up":    "上",
    "arrow_down":  "下",
    "expand":      "展开",
    "collapse":    "收起",
    # 工具
    "cog":         "设置",
    "gear":        "设置",
    "wrench":      "修复",
    "rocket":      "启动",
    "flash":       "闪电",
    "broom":       "清理",
    "lightbulb":   "提示",
    "pin":         "固定",
    "lock":        "锁定",
    "unlock":      "解锁",
    "key":         "密钥",
    # 媒体类型
    "video":       "视频",
    "film":        "视频",
    "audio":       "音频",
    "mic":         "音频",
    "music":       "音乐",
    "image":       "图片",
    "camera":      "相机",
    "palette":     "调色",
    "voice":       "语音",
    "clipboard":   "剪贴板",
    "subtitles":   "字幕",
    "closed-caption": "字幕",
    "movie-open":  "视频",
    "broadcast":   "广播",
    "content-cut": "剪切",
    "clock-outline": "时间",
    # AI / 智能
    "robot":       "AI",
    "brain":       "AI",
    "robot2":      "AI",
    "magic":       "魔法",
    "sparkles":    "特效",
    "chart-line":  "图表",
    "megaphone":   "喇叭",
    "puzzle":      "插件",
    "help-circle": "帮助",
    "web":         "网页",
    "book":        "资料",
    "database":    "资料",
    "package":     "包裹",
    "type":        "文本",
    "format-list-checks": "清单",
    "text-box-search": "搜索",
    # 状态
    "star":        "收藏",
    "heart":       "喜欢",
    "info":        "信息",
    "warning":     "警告",
    "error":       "错误",
    "success":     "成功",
    "question":    "帮助",
    "hourglass":   "时间",
    "clock":       "时间",
    "eye":         "查看",
    "eyes":        "查看",
    # 系统
    "home":        "首页",
    "menu":        "菜单",
    "server":      "服务器",
    "link":        "链接",
    "download2":   "下载",
    "upload2":     "上传",
    "fullscreen":  "服务器",
    "restore":     "还原",
    "layers":      "资料",
    "select_all":      "全选",
    "deselect_all":    "取消",
    "sort":        "排序",
    "filter":      "筛选",
    "autofix":     "修复",
    "projector":   "投影",
    "celebration": "庆祝",
    "balance-scale": "平衡",
    "volume":      "音量",
    "mute":        "静音",
    # 复选框
    "checkbox_marked": "全选",
    "checkbox_blank":  "取消",
}

# qtawesome 作为增强（可选，未安装也不影响使用）
try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:
    _HAS_QTA = False


def mdi_icon(name: str, color: str = "#8b90a3") -> QIcon:
    """获取图标。优先 qtawesome，回退空图标（文字由按钮文本提供）。"""
    if _HAS_QTA:
        # 部分别名：历史代码用了非标准 mdi 图标名，这里统一映射到有效名，
        # 避免逐个改各页面调用点。映射不命中则原样加 mdi. 前缀。
        _ALIAS = {
            "audio": "volume-high", "backward": "skip-backward",
            "balance-scale": "scale", "celebration": "party-popper",
            "cut": "content-cut", "edit": "pencil", "gear": "cog",
            "left": "arrow-left", "mic": "microphone", "magic": "creation",
            "right": "arrow-right",
            "save": "content-save", "search": "magnify", "trash": "trash-can",
            "voice": "account-voice", "volume": "volume-high",
        }
        normalized = _ALIAS.get(name, name).replace("_", "-")
        mdi_name = "mdi." + normalized
        try:
            return qta.icon(mdi_name, color=color)
        except Exception:
            # 图标名在当前字体版本不存在（如 magic 已被新版 MDI 移除）：
            # 回退空图标，避免异常穿透导致页面构建崩溃（懒加载失败后页面永久空白）
            pass
    return QIcon()


def mdi_button(text: str, icon_name: str = "", parent=None,
               color: str = "#8b90a3", size: int = 18) -> QPushButton:
    """创建带图标的按钮。qtawesome 可用时用 MDI 图标，否则回退为文字标签前缀。"""
    label = ICON_LABEL.get(icon_name, "")
    if icon_name:
        if _HAS_QTA:
            btn = QPushButton(text, parent)
            icon = mdi_icon(icon_name, color)
            if icon.isNull() and label:
                # 图标名无效回退后，用文字标签补前缀保持可识别性
                if not text.startswith(label):
                    text = label + " " + text
                btn = QPushButton(text, parent)
            else:
                btn.setIcon(icon)
                btn.setIconSize(QSize(size, size))
            return btn
        elif label:
            # qtawesome 不可用 → 文字标签回退
            if not text.startswith(label):
                text = label + " " + text
    return QPushButton(text, parent)


def icon_button(name: str, tooltip: str = "", parent=None, size: int = 20) -> QPushButton:
    """创建纯图标按钮（无文字）。优先 Qt 标准图标，其次 MDI，最后回退文字标签。

    用于播放/暂停/停止/翻页等空间受限的控件，避免中文标签被截断。
    """
    label = ICON_LABEL.get(name, "")
    btn_size = max(32, size + 12)
    btn = QPushButton(parent)
    btn.setFixedSize(btn_size, btn_size)
    btn.setObjectName("icon_only_button")

    icon = std_icon(name)
    if icon.isNull():
        icon = mdi_icon(name)
    if icon.isNull() and label:
        btn.setText(label)
    else:
        btn.setIcon(icon)
        btn.setIconSize(QSize(size, size))

    btn.setToolTip(tooltip or label)
    return btn


def emoji_icon(name: str) -> str:
    """返回图标名对应的文字标签，用于 QLabel 等。"""
    return ICON_LABEL.get(name, "")


def emoji_button(text: str, emoji: str = "", parent=None) -> QPushButton:
    """创建纯文字标签按钮（不依赖 qtawesome）。"""
    if emoji:
        text = emoji + " " + text
    return QPushButton(text, parent)


def table_action_button(text: str, tooltip: str = "", parent=None) -> QPushButton:
    """表格操作列专用扁平按钮（无边框，icon+文字，不挤压行高）。
    用法: btn = table_action_button('删除', '删除')
    """
    btn = QPushButton(text, parent)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setFlat(True)
    btn.setObjectName("table_action_button")
    return btn
