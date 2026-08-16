# -*- coding: utf-8 -*-
"""智能混剪 - 可复用控件：双击编辑控件、可拖拽重排表格。"""
from PySide6.QtWidgets import (QLineEdit, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QDrag, QColor



class DoubleClickLineEdit(QLineEdit):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self.doubleClicked.emit()



class ReadOnlyDoubleClickLineEdit(QLineEdit):
    """只读单行输入框，双击弹出完整文本查看对话框。"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self._full_text = text
        self.setStyleSheet("""
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                color: #d1d5db;
                padding: 4px 8px;
                font-size: 11px;
            }
            QLineEdit:hover {
                border: 1px solid rgba(255, 255, 255, 0.25);
                background-color: rgba(255, 255, 255, 0.07);
            }
        """)
        self.setToolTip("双击查看完整原文")
        self.setCursorPosition(0)

    def set_full_text(self, text):
        self._full_text = text
        self.setText(text)
        self.setCursorPosition(0)

    def mouseDoubleClickEvent(self, event):
        # Show full text in a read-only popup dialog
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QPushButton, QLabel, QHBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(" 原文 - 完整内容")
        dlg.setMinimumSize(500, 300)
        dlg.resize(580, 350)
        dlg.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #e5e7eb; }
            QLabel { color: #9ca3af; font-size: 13px; font-weight: bold; }
            QPlainTextEdit {
                background-color: #111827;
                color: #f3f4f6;
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 7px 18px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        v.addWidget(QLabel(" 原始视频文案（只读）:"))
        te = QPlainTextEdit()
        te.setPlainText(self._full_text)
        te.setReadOnly(True)
        v.addWidget(te)
        h = QHBoxLayout()
        h.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        h.addWidget(btn_close)
        v.addLayout(h)
        dlg.exec()



class ReorderableClipsTable(QTableWidget):
    """镜头片段表格：左列为拖拽把手，支持拖动调序，右键删除/恢复。"""
    order_changed = Signal(int, int)  # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self._drag_start_row = -1

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and item.column() == 0:
                self._drag_start_row = item.row()
            else:
                self._drag_start_row = -1

    def mouseMoveEvent(self, event):
        if self._drag_start_row >= 0 and (event.buttons() & Qt.LeftButton):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(str(self._drag_start_row))
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)
            self._drag_start_row = -1
        else:
            super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.source() == self:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.source() == self:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() == self:
            target_row = self.rowAt(event.pos().y())
            if target_row < 0:
                target_row = self.rowCount() - 1
            source_row = self._drag_start_row
            self._drag_start_row = -1
            if source_row >= 0 and target_row >= 0 and target_row != source_row:
                self.order_changed.emit(source_row, target_row)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
