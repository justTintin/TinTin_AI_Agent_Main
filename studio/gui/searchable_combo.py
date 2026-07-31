# -*- coding: utf-8 -*-
"""
可搜索下拉选择框（SearchableComboBox）。

QComboBox 子类，API 与 QComboBox 完全兼容
（addItem / clear / currentData / currentIndexChanged / setCurrentIndex /
 blockSignals / setPlaceholderText），额外提供"输入即实时过滤"：
- 在编辑框输入关键字时，下拉按「包含匹配」实时过滤候选；
- ↑/↓ 选择，回车或点击立即选中（触发 currentIndexChanged，currentData 即为该项 data）。

用法（替换原来的 QComboBox 即可）：
    combo = SearchableComboBox(placeholder="输入品牌/型号搜索…")
    combo.addItem("戴尔 / Dell 键盘", "id-1")
    combo.currentIndexChanged.connect(handler)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None, placeholder="输入关键字搜索…"):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setCurrentIndex(-1)
        if placeholder:
            self.setPlaceholderText(placeholder)

        # 输入即实时过滤：QCompleter 直接使用下拉列表的 model
        completer = QCompleter(self)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)   # Qt ≥ 6.3：包含匹配
        completer.setModel(self.model())
        completer.setPopup(self.view())             # 弹出与下拉共用同一列表视图
        self.setCompleter(completer)
        completer.activated.connect(self._on_completer_activated)

    def setItems(self, items):
        """批量填充 [(label, data), ...]，期间不触发 currentIndexChanged。"""
        self.blockSignals(True)
        self.clear()
        for label, data in items:
            self.addItem(str(label), data)
        if self.count() > 0:
            self.setCurrentIndex(0)
        self.blockSignals(False)

    def set_items(self, items):
        """setItems 的小写别名。"""
        return self.setItems(items)

    def setView(self, view):
        """页面更换弹出视图时，同步 completer 的弹窗视图（避免引用已销毁视图）。"""
        super().setView(view)
        completer = self.completer()
        if completer is not None:
            completer.setPopup(view)

    def addItem(self, text, userData=None):
        """保留 QComboBox 语义：可编辑模式下首个 addItem 自动选中第 0 项。"""
        was_blocked = self.signalsBlocked()
        if userData is None:
            super().addItem(text)
        else:
            super().addItem(text, userData)
        if self.currentIndex() < 0 and self.count() > 0:
            if not was_blocked:
                self.blockSignals(True)
                self.setCurrentIndex(0)
                self.blockSignals(False)
            else:
                self.setCurrentIndex(0)

    def _on_completer_activated(self, text):
        """从过滤结果中选中：同步到真实行，确保 currentData 与显示文本一致。"""
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
