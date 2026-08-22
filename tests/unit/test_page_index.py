"""页面索引一致性回归：验证侧边栏菜单索引与 content_stack 页面对齐。

历史教训：page_terminal 被删除后 content_stack 少了一个 addWidget，
后续所有页面索引偏移 -1，但侧边栏索引未同步更新，导致菜单错位。
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

STUDIO = testutil.STUDIO_DIR
GUI_MAIN = os.path.join(STUDIO, "gui_main.py")
SIDEBAR = os.path.join(STUDIO, "gui", "main_window_sidebar.py")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class TestPageIndexConsistency(unittest.TestCase):
    """静态分析：侧边栏索引 ↔ content_stack widget 顺序必须对齐。"""

    @classmethod
    def setUpClass(cls):
        cls.gui_main_src = _read(GUI_MAIN)
        cls.sidebar_src = _read(SIDEBAR)
        cls.stack_pages = cls._extract_stack_order(cls.gui_main_src)
        cls.sidebar_indices = cls._extract_sidebar_indices(cls.sidebar_src)

    @staticmethod
    def _extract_stack_order(src):
        """从 gui_main.py 中按出现顺序提取 content_stack.addWidget(self.page_XXX) 的页面名。"""
        pattern = re.compile(r"content_stack\.addWidget\(self\.(page_\w+)\)")
        return pattern.findall(src)

    @staticmethod
    def _extract_sidebar_indices(src):
        """从 main_window_sidebar.py 中提取所有 switch_page(INDEX) 调用和菜单元组中的索引。"""
        indices = set()
        # switch_page(N) 直接调用
        for m in re.finditer(r"switch_page\((\d+)\)", src):
            indices.add(int(m.group(1)))
        # ("菜单名", INDEX, "icon") 元组
        for m in re.finditer(r'\(\s*"[^"]+"\s*,\s*(\d+)\s*,', src):
            indices.add(int(m.group(1)))
        # target_index = N
        for m in re.finditer(r'target_index["\']?\s*,?\s*(\d+)', src):
            indices.add(int(m.group(1)))
        return indices

    def test_stack_has_enough_pages(self):
        """content_stack 中的页面数应覆盖侧边栏引用的最大索引。"""
        if not self.sidebar_indices:
            self.skipTest("未提取到侧边栏索引")
        max_index = max(self.sidebar_indices)
        self.assertGreater(
            len(self.stack_pages), max_index,
            f"content_stack 只有 {len(self.stack_pages)} 个页面，"
            f"但侧边栏引用了索引 {max_index}（越界）",
        )

    def test_sidebar_index_maps_to_named_page(self):
        """每个侧边栏索引应映射到一个有意义的页面（非占位 widget）。"""
        placeholder_names = {"page_terminal_placeholder"}
        for idx in sorted(self.sidebar_indices):
            if idx >= len(self.stack_pages):
                self.fail(f"侧边栏索引 {idx} 超出 content_stack 范围（共 {len(self.stack_pages)} 页）")
            page_name = self.stack_pages[idx]
            self.assertNotIn(
                page_name, placeholder_names,
                f"侧边栏索引 {idx} 映射到占位页面 {page_name}，"
                f"该索引对应的真实页面可能已被删除但索引未更新",
            )

    def test_lazy_page_indices_within_range(self):
        """_register_lazy_page 的索引必须在 content_stack 范围内。"""
        pattern = re.compile(r"_register_lazy_page\((\d+),")
        for m in pattern.finditer(self.gui_main_src):
            idx = int(m.group(1))
            self.assertLess(
                idx, len(self.stack_pages),
                f"_register_lazy_page({idx}, ...) 索引超出 content_stack 范围"
                f"（共 {len(self.stack_pages)} 页）",
            )

    def test_no_orphan_placeholder(self):
        """占位页面不应被侧边栏引用（如果引用了说明索引错位）。"""
        # 如果将来有新的占位页面，加到这里
        known_placeholders = {"page_terminal_placeholder"}
        for idx, name in enumerate(self.stack_pages):
            if name in known_placeholders:
                # 确认没有侧边栏菜单直接引用这个占位索引
                self.assertNotIn(
                    idx, self.sidebar_indices,
                    f"侧边栏引用了占位页面索引 {idx}（{name}），"
                    f"说明删除页面后索引未对齐",
                )


if __name__ == "__main__":
    unittest.main()
