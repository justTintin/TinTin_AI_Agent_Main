"""统一错误弹窗：可滚动显示长错误信息（不撑满屏幕）+ 一键复制日志按钮。

用于替代 QMessageBox.critical 显示长错误（traceback、多失败项拼接、接口响应等）。
QMessageBox 无法滚动、无法复制、长信息会撑满屏幕，故改用此自定义对话框。

设计要点：
  · QPlainTextEdit 只读 + 自带垂直滚动条 → 长信息可滚动，不撑满
  · 限制最大高度（屏幕 70%）→ 即使 traceback 极长也不撑满屏幕
  · 「 复制日志」按钮 → 一键复制完整错误到剪贴板，便于反馈排查
  · 等宽字体 → traceback / 接口错误对齐易读
  · 暗色主题 → 与工程其它弹窗一致
"""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout


class ErrorDialog(QDialog):
    """统一错误弹窗：可滚动 + 复制日志。

    用法:
        ErrorDialog("合成错误", err_text, parent).exec()
    或便捷函数:
        show_error_dialog(parent, "合成错误", err_text)
    """

    # 复制成功后，按钮文字临时变更的持续时间（毫秒）
    _COPIED_FEEDBACK_MS = 1500

    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        self._message = message or "(无错误信息)"
        self.setWindowTitle(title or "错误")
        self.setMinimumSize(560, 320)
        self.resize(680, 460)
        # 限制最大高度为屏幕的 70%，避免长 traceback 撑满屏幕
        try:
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.setMaximumHeight(int(geo.height() * 0.7))
                self.setMaximumWidth(int(geo.width() * 0.9))
        except Exception:  # Qt 屏幕几何计算可能失败
            pass

        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #e5e7eb; }
            QLabel { color: #fca5a5; font-size: 14px; font-weight: bold; }
            QPlainTextEdit {
                background-color: #111827;
                color: #f3f4f6;
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 13px;
                padding: 10px;
            }
            QPushButton {
                background-color: #3b82f6; color: white; border: none;
                padding: 8px 20px; border-radius: 4px;
                font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #4b5563; }
            QPushButton[objectName="secondary_button"] {
                background-color: #4b5563;
            }
            QPushButton[objectName="secondary_button"]:hover {
                background-color: #6b7280;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # 标题（红色，醒目）
        title_lbl = QLabel(f"失败： {title or '错误'}")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        # 错误内容（只读，等宽字体，自带滚动条）
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(self._message)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)  # 横向滚动，保留 traceback 对齐
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.text_edit.setFont(mono)
        layout.addWidget(self.text_edit, 1)  # stretch=1 吃掉主要空间

        # 按钮行：[ 复制日志] [stretch] [关闭]
        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton(" 复制日志")
        self.btn_copy.setToolTip("复制完整错误信息到剪贴板")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch()

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("secondary_button")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _copy_to_clipboard(self):
        """复制完整错误信息到剪贴板，按钮文字短暂反馈"已复制"。"""
        try:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self._message)
        except Exception:  # Qt 剪贴板操作可能失败
            pass
        # 按钮文字短暂变为"已 已复制"，1.5 秒后恢复
        original = self.btn_copy.text()
        self.btn_copy.setText("已 已复制")
        self.btn_copy.setEnabled(False)
        QTimer.singleShot(self._COPIED_FEEDBACK_MS,
                          lambda: (self.btn_copy.setText(original),
                                   self.btn_copy.setEnabled(True)))


def show_error_dialog(parent, title, message):
    """便捷函数：显示统一错误弹窗（可滚动 + 复制日志）。

    用于替代 QMessageBox.critical(parent, title, message)。
    短提示请继续用 QMessageBox.warning/information。
    """
    dlg = ErrorDialog(title, message, parent)
    dlg.exec()
