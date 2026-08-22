"""QSS 纯净性回归：防止 Python linter 指令污染样式表字符串。

历史教训：# noqa: E501 被写入 STYLE_SHEET 三引号字符串内部，
Qt QSS 解析器将 # 当作 ID 选择器，导致从该位置起所有属性选择器失效。
"""
import os
import re
import sys
import unittest

# 必须在导入 PySide6 前设置 offscreen 平台，否则全量测试时无显示器会崩溃
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from ui.gui_styles import STYLE_SHEET  # noqa: E402


class TestQSSPurity(unittest.TestCase):
    """验证 STYLE_SHEET 字符串中不混入 Python 专属内容。"""

    PYTHON_DIRECTIVES = [
        re.compile(r"#\s*noqa"),
        re.compile(r"#\s*type:\s*ignore"),
        re.compile(r"#\s*pragma:"),
        re.compile(r"#\s*pylint:"),
    ]

    def test_no_python_linter_directives(self):
        """STYLE_SHEET 中不得出现 # noqa / # type: ignore 等 Python 指令。"""
        bad = []
        for i, line in enumerate(STYLE_SHEET.split("\n"), 1):
            for pat in self.PYTHON_DIRECTIVES:
                if pat.search(line):
                    bad.append(f"line {i}: {line.strip()[:120]}")
        self.assertEqual(
            bad, [],
            "STYLE_SHEET 中混入了 Python linter 指令，会破坏 QSS 解析:\n" + "\n".join(bad),
        )

    def test_brace_balance(self):
        """大括号必须配对，否则 QSS 解析中断。"""
        opens = STYLE_SHEET.count("{")
        closes = STYLE_SHEET.count("}")
        self.assertEqual(
            opens, closes,
            f"大括号不配对: {{={opens}, }}={closes}，QSS 将解析失败",
        )

    def test_comment_balance(self):
        """CSS 注释 /* */ 必须配对。"""
        opens = STYLE_SHEET.count("/*")
        closes = STYLE_SHEET.count("*/")
        self.assertEqual(
            opens, closes,
            f"注释标记不配对: /* ={opens}, */ ={closes}",
        )

    def test_property_selectors_work(self):
        """关键属性选择器在全量样式表下必须生效（需 offscreen QApplication）。"""
        try:
            from PySide6.QtWidgets import QApplication, QLabel
            from PySide6.QtCore import QCoreApplication
        except ImportError:
            self.skipTest("PySide6 不可用，跳过属性选择器运行时验证")

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        elif not isinstance(app, QApplication):
            self.skipTest("已有非 QApplication 的 QCoreApplication 实例，无法测试样式表")

        app.setStyleSheet(STYLE_SHEET)

        cases = [
            ("ov_value", "level", "ok", "#34d399"),
            ("ov_value", "level", "warn", "#fbbf24"),
            ("ov_value", "level", "bad", "#f87171"),
            ("ov_value", "level", "idle", "#5f6475"),
        ]
        failures = []
        for obj_name, prop, val, expected in cases:
            lbl = QLabel(f"test-{val}")
            lbl.setObjectName(obj_name)
            lbl.setProperty(prop, val)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
            actual = lbl.palette().windowText().color().name()
            if actual.lower() != expected.lower():
                failures.append(
                    f"{obj_name}[{prop}={val}] -> {actual} (expected {expected})"
                )

        self.assertEqual(
            failures, [],
            "属性选择器未生效，可能 QSS 被污染或选择器特异性错误:\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
