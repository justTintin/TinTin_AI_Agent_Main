# -*- coding: utf-8 -*-
"""UI 静态回归：验证近期改动的约定（无裸"就绪"文案、字幕文案位置、分镜自动生成 JSON）。"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

GUI_DIR = os.path.join(testutil.STUDIO_DIR, "gui")

# 无意义的默认状态文案（近期改动目标：全部清空）
BARE_READY_PATTERNS = [
    re.compile(r'QLabel\(\s*"就绪"\s*\)'),
    re.compile(r'QLabel\(\s*"状态:\s*就绪"\s*\)'),
    re.compile(r'QLabel\(\s*"状态:\s*准备就绪"\s*\)'),
    re.compile(r'\.setText\(\s*"就绪"\s*\)'),
]


def _gui_files():
    return [os.path.join(GUI_DIR, f) for f in os.listdir(GUI_DIR) if f.endswith(".py")]


class TestUIRegression(unittest.TestCase):
    def test_no_bare_ready_labels(self):
        bad = []
        for fp in _gui_files():
            for i, line in enumerate(open(fp, encoding="utf-8", errors="replace"), 1):
                for pat in BARE_READY_PATTERNS:
                    if pat.search(line):
                        bad.append("%s:%d: %s" % (os.path.basename(fp), i, line.strip()))
        self.assertEqual(bad, [], "仍存在无意义的默认「就绪」文案:\n" + "\n".join(bad))

    def test_compile_video_subtitle_above_folder(self):
        src = open(os.path.join(GUI_DIR, "compile_video_page.py"), encoding="utf-8").read()
        lines = src.splitlines()
        line_sub = next(i for i, l in enumerate(lines, 1) if "self.in_subtitle = QTextEdit" in l)
        line_folder = next(i for i, l in enumerate(lines, 1) if "self.in_folder = self._file_row" in l)
        self.assertLess(line_sub, line_folder, "字幕文案控件应位于镜头素材目录控件上方")
        self.assertEqual(src.count("self.in_subtitle = QTextEdit"), 1, "in_subtitle 只能定义一次")

    def test_storyboard_auto_json(self):
        src = open(os.path.join(GUI_DIR, "storyboard_page.py"), encoding="utf-8").read()
        self.assertIn('json_path = os.path.join(out_dir, base_name + ".json")', src)
        self.assertIn("_export_storyboard_json(json_path, topic, ratio, total_dur, shots)", src)
        self.assertIn("（已自动生成 .json，可在「一键成片 → 脚本成片」中刷新后选择）", src)



class TestMenuStructure(unittest.TestCase):
    """侧边栏菜单结构：媒体工具聚合图片/视频处理子页面。"""

    def _sidebar_src(self):
        return open(os.path.join(testutil.STUDIO_DIR, "gui", "main_window_sidebar.py"),
                    encoding="utf-8").read()

    def test_media_tools_entry_exists(self):
        src = self._sidebar_src()
        self.assertIn('("媒体工具", 46, "tools")', src)

    def test_old_image_video_sections_removed(self):
        src = self._sidebar_src()
        self.assertNotIn('QLabel("图形处理")', src)
        self.assertNotIn('QLabel("视频处理")', src)

    def test_media_tools_has_nine_cards(self):
        src = open(os.path.join(testutil.STUDIO_DIR, "gui", "media_tools_page.py"),
                   encoding="utf-8").read()
        for title in ("封面制作", "图像抠图", "图片框选OCR", "视频修复", "视频转文字",
                      "声音克隆", "视频去字幕", "视频框选OCR", "批量LUT调色"):
            self.assertIn(title, src)

    def test_media_tools_grouped_image_video(self):
        src = open(os.path.join(testutil.STUDIO_DIR, "gui", "media_tools_page.py"),
                   encoding="utf-8").read()
        self.assertIn('_IMAGE_TOOLS', src)
        self.assertIn('_VIDEO_TOOLS', src)
        self.assertIn('self._group_header("图片")', src)
        self.assertIn('self._group_header("视频")', src)
        # 卡片式交互：点击卡片进入工具页 + 返回按钮
        self.assertIn("_ToolCard", src)
        self.assertIn("← 返回媒体工具", src)
        self.assertIn("QStackedWidget", src)


if __name__ == "__main__":
    unittest.main()
