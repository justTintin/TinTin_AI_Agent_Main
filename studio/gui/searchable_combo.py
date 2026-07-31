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
        """页面更换弹出视图：仅透传给 QComboBox；completer 使用自己的独立弹窗。"""
        super().setView(view)

    def showPopup(self):
        """点击下拉箭头：显示完整列表供选择（重置过滤为空），不要求先输入。

        说明：若把 completer 的弹窗设成 QComboBox 自己的视图，箭头点击会被
        completer 接管而不再弹出。这里改为 completer 独立弹窗 + 显式弹出。
        """
        comp = self.completer()
        if comp is not None:
            comp.setCompletionPrefix("")   # 空前缀 = 显示全部候选项
            comp.complete()
        else:
            super().showPopup()

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
