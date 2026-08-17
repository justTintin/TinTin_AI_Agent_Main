# -*- coding: utf-8 -*-
"""可复用的多行省略标签。

行为与 QLabel 基本一致，但会把文本限制在最多 ``max_lines`` 行；超出最后一行时以
``…`` 结尾省略（Qt.ElideRight）。内部固定启用自动换行。

当 ``max_lines <= 0`` 时，回退到普通 QLabel 的完整绘制与尺寸行为，保持向后兼容。
"""
from PySide6.QtCore import Qt, QSize, QPointF
from PySide6.QtGui import QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None, max_lines=2):
        super().__init__(text, parent)
        self._max_lines = max_lines
        self.setWordWrap(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def setMaxLineCount(self, n):
        """设置最大显示行数；<= 0 时退化为普通 QLabel 行为。"""
        if self._max_lines == n:
            return
        self._max_lines = n
        self.updateGeometry()
        self.update()

    def maxLineCount(self):
        """返回当前最大显示行数。"""
        return self._max_lines

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        if self._max_lines <= 0:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.setPen(self.palette().text().color())
        painter.setFont(self.font())

        cr = self.contentsRect()
        layout = QTextLayout(self.text(), self.font(), self)

        option = QTextOption()
        option.setWrapMode(QTextOption.WordWrap)
        option.setAlignment(self.alignment())
        layout.setTextOption(option)
        layout.setCacheEnabled(True)

        fm = self.fontMetrics()
        line_height = fm.lineSpacing()

        layout.beginLayout()
        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(cr.width())
            line.setPosition(QPointF(0, 0))
            lines.append(line)
        layout.endLayout()

        total_lines = len(lines)
        visible_lines = min(total_lines, self._max_lines)
        block_height = visible_lines * line_height
        # 内容不足最大行数时整体垂直居中，使单行描述与旁边大标题对齐
        y = cr.top() + max(0, (cr.height() - block_height) // 2)
        for i, line in enumerate(lines):
            if i >= self._max_lines:
                break

            if i == self._max_lines - 1 and total_lines > self._max_lines:
                # 最后一行且还有更多内容：用省略号截断
                start = line.textStart()
                length = line.textLength()
                line_text = self.text()[start:start + length]
                elided = fm.elidedText(line_text, Qt.ElideRight, cr.width())
                flags = int(self.alignment()) | int(Qt.TextSingleLine)
                painter.drawText(cr.left(), y, cr.width(), line_height, flags, elided)
            else:
                line.draw(painter, QPointF(cr.left(), y))

            y += line_height

        painter.end()

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------
    def sizeHint(self):
        if self._max_lines <= 0:
            return super().sizeHint()

        sh = super().sizeHint()
        fm = self.fontMetrics()
        margins = self.contentsMargins()
        height = self._max_lines * fm.lineSpacing() + margins.top() + margins.bottom()
        width = min(sh.width(), 1400)
        return QSize(width, height)

    def minimumSizeHint(self):
        if self._max_lines <= 0:
            return super().minimumSizeHint()

        fm = self.fontMetrics()
        margins = self.contentsMargins()
        height = self._max_lines * fm.lineSpacing() + margins.top() + margins.bottom()
        return QSize(0, height)
