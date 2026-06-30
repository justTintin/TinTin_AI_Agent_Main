# -*- coding: utf-8 -*-
"""
内嵌 Python 终端页面（page 41）

在应用内提供命令行终端：
- 使用当前 Python 环境（自动替换 pythonw.exe → python.exe）
- 工作目录为本项目 studio 根目录
- 命令历史（↑↓方向键）
- 快捷按钮：pip 安装常用包
- 实时流式输出，stderr 红色高亮
"""
import os
import sys

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QFrame, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QEvent, QObject
from PySide6.QtGui import QFont, QColor, QTextCursor, QKeyEvent

from gui.base_page import BasePage


# ── Python 路径解析（pythonw.exe → python.exe）────────────────────────────────

def _resolve_python() -> str:
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(alt):
            return alt
    return exe


_PYTHON_EXE  = _resolve_python()
_PYTHON_DIR  = os.path.dirname(_PYTHON_EXE)
_SCRIPTS_DIR = os.path.join(_PYTHON_DIR, "Scripts")

# studio 根目录（terminal_page.py 在 studio/gui/ 下）
_STUDIO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 快捷按钮定义 ──────────────────────────────────────────────────────────────

_QUICK_CMDS = [
    ("python 版本",   "python --version"),
    ("pip list",      "python -m pip list"),
    ("pip 升级",      "python -m pip install --upgrade pip"),
    ("装 modelscope", "python -m pip install modelscope -q"),
    ("装 transformers","python -m pip install transformers -q"),
    ("装 torch(cpu)", "python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu -q"),
    ("当前目录",      "dir"),
]


# ── 历史记录事件过滤器（必须是 QObject 子类）──────────────────────────────────

class _HistoryFilter(QObject):
    """处理命令输入框的上下方向键历史翻翹，必须是 QObject 才能用于 installEventFilter。"""
    def __init__(self, line_edit, page):
        super().__init__(line_edit)    # 与 line_edit 生命周期绑定
        self._edit = line_edit
        self._page = page              # TerminalPage 实例，用于访问 _history/_history_idx

    def eventFilter(self, obj, event):
        if obj is self._edit and event.type() == QEvent.KeyPress:
            page = self._page
            key = event.key()
            if key == Qt.Key_Up:
                if page._history and page._history_idx > 0:
                    page._history_idx -= 1
                    self._edit.setText(page._history[page._history_idx])
                return True
            if key == Qt.Key_Down:
                if page._history_idx < len(page._history) - 1:
                    page._history_idx += 1
                    self._edit.setText(page._history[page._history_idx])
                else:
                    page._history_idx = len(page._history)
                    self._edit.clear()
                return True
        return super().eventFilter(obj, event)


# ── 终端页面 ──────────────────────────────────────────────────────────────────

class TerminalPage(BasePage):
    def setup(self):
        self._history:     list  = []
        self._history_idx: int   = 0
        self._process:     QProcess | None = None

        lay = QVBoxLayout(self.parent_widget)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(6)

        # ── 标题行 ──────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("💻 Python 终端")
        title.setObjectName("heading")
        hdr.addWidget(title)
        hdr.addStretch()
        lbl_py = QLabel(_PYTHON_EXE)
        lbl_py.setObjectName("muted_text")
        lbl_py.setWordWrap(False)
        hdr.addWidget(lbl_py)
        lay.addLayout(hdr)

        # ── 快捷按钮行 ──────────────────────────────────────────────────────
        quick_scroll = QScrollArea()
        quick_scroll.setWidgetResizable(True)
        quick_scroll.setFixedHeight(42)
        quick_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        quick_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        quick_scroll.setFrameShape(QFrame.NoFrame)
        quick_inner = QWidget()
        quick_lay = QHBoxLayout(quick_inner)
        quick_lay.setContentsMargins(0, 0, 0, 0)
        quick_lay.setSpacing(4)
        for label, cmd in _QUICK_CMDS:
            btn = QPushButton(label)
            btn.setObjectName("secondary_button")
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda checked=False, c=cmd: self._fill_cmd(c))
            quick_lay.addWidget(btn)
        quick_lay.addStretch()
        btn_clear = QPushButton("🗑 清空")
        btn_clear.setObjectName("secondary_button")
        btn_clear.setFixedHeight(30)
        btn_clear.clicked.connect(self._clear)
        quick_lay.addWidget(btn_clear)
        quick_scroll.setWidget(quick_inner)
        lay.addWidget(quick_scroll)

        # ── 输出显示区 ──────────────────────────────────────────────────────
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 10))
        self.output.setStyleSheet(
            "QTextEdit {"
            "  background: #0c0c0c; color: #d4d4d4;"
            "  border: 1px solid #2a2a2a; border-radius: 6px; padding: 8px;"
            "}"
        )
        lay.addWidget(self.output, 1)

        # ── 输入行 ──────────────────────────────────────────────────────────
        inp_frame = QFrame()
        inp_frame.setObjectName("card")
        inp_lay = QHBoxLayout(inp_frame)
        inp_lay.setContentsMargins(8, 4, 8, 4)
        inp_lay.setSpacing(6)

        self.prompt_lbl = QLabel(">")
        self.prompt_lbl.setFont(QFont("Consolas", 11))
        self.prompt_lbl.setStyleSheet("color: #4ade80; min-width: 16px;")
        inp_lay.addWidget(self.prompt_lbl)

        self.cmd_input = QLineEdit()
        self.cmd_input.setFont(QFont("Consolas", 10))
        self.cmd_input.setPlaceholderText("输入命令，Enter 执行，↑↓ 历史记录")
        self.cmd_input.returnPressed.connect(self._run_cmd)
        self._hist_filter = _HistoryFilter(self.cmd_input, self)
        self.cmd_input.installEventFilter(self._hist_filter)
        inp_lay.addWidget(self.cmd_input, 1)

        self.btn_run = QPushButton("▶ 执行")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.clicked.connect(self._run_cmd)
        inp_lay.addWidget(self.btn_run)

        self.btn_kill = QPushButton("⏹ 终止")
        self.btn_kill.setObjectName("secondary_button")
        self.btn_kill.setEnabled(False)
        self.btn_kill.clicked.connect(self._kill_process)
        inp_lay.addWidget(self.btn_kill)

        lay.addWidget(inp_frame)

        self._print_banner()
        self.cmd_input.setFocus()

    # ── 辅助 ─────────────────────────────────────────────────────────────────

    def _print_banner(self):
        self._append(
            f"Python 终端 — 当前环境\n"
            f"  python.exe : {_PYTHON_EXE}\n"
            f"  工作目录   : {_STUDIO_DIR}\n"
            f"  提示       : 使用 python -m pip install <包名> 安装包\n"
            + "─" * 70 + "\n\n",
            "#4b5563",
        )

    def _clear(self):
        self.output.clear()
        self._print_banner()

    def _fill_cmd(self, cmd: str):
        self.cmd_input.setText(cmd)
        self.cmd_input.setFocus()

    def _append(self, text: str, color: str = "#d4d4d4"):
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _kill_process(self):
        if self._process and self._process.state() == QProcess.Running:
            self._process.kill()
            self._append("\n[已终止]\n", "#f97316")

    # ── 执行命令 ─────────────────────────────────────────────────────────────

    def _run_cmd(self):
        if self._process and self._process.state() == QProcess.Running:
            return
        raw = self.cmd_input.text().strip()
        if not raw:
            return

        self._history.append(raw)
        self._history_idx = len(self._history)
        self.cmd_input.clear()

        # 把 "python" 替换成完整路径（避免 pythonw 找不到控制台）
        cmd = raw
        if cmd == "python" or cmd.startswith("python "):
            cmd = f'"{_PYTHON_EXE}"' + cmd[6:]
        elif cmd == "pip" or cmd.startswith("pip "):
            cmd = f'"{_PYTHON_EXE}" -m ' + cmd

        self._append(f"$ {raw}\n", "#60a5fa")

        # 设置进程环境（Scripts 目录在前）
        env = QProcessEnvironment.systemEnvironment()
        extra = _SCRIPTS_DIR + ";" + _PYTHON_DIR if os.path.isdir(_SCRIPTS_DIR) else _PYTHON_DIR
        env.insert("PATH", extra + ";" + env.value("PATH", ""))
        env.insert("PYTHONIOENCODING", "utf-8")

        self._process = QProcess(self.parent_widget)
        self._process.setWorkingDirectory(_STUDIO_DIR)
        self._process.setProcessEnvironment(env)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)

        self._process.start("cmd.exe", ["/C", cmd])

        self.cmd_input.setEnabled(False)
        self.btn_run.setEnabled(False)
        self.btn_kill.setEnabled(True)
        self.prompt_lbl.setText("⏳")

    def _on_stdout(self):
        raw = bytes(self._process.readAllStandardOutput())
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        self._append(text, "#d4d4d4")

    def _on_stderr(self):
        raw = bytes(self._process.readAllStandardError())
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        self._append(text, "#f87171")

    def _on_finished(self, exit_code: int, _status):
        color = "#4ade80" if exit_code == 0 else "#f87171"
        self._append(f"[退出码: {exit_code}]\n\n", color)
        self.cmd_input.setEnabled(True)
        self.btn_run.setEnabled(True)
        self.btn_kill.setEnabled(False)
        self.prompt_lbl.setText(">")
        self.cmd_input.setFocus()
