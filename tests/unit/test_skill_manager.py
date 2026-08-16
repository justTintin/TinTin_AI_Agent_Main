# -*- coding: utf-8 -*-
"""本地技能安装/管理：目录、zip、卸载、路径安全。"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from utils import skill_manager as sm


SKILL_MD = """---
name: 文案风格改写
description: 按给定品牌风格改写商品文案
version: 1.0.0
author: test
tags: [文案, 改写]
---
严格按品牌风格改写，保留卖点，输出 3 个版本。
"""


class TestSkillManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skill_test_")
        self._orig_dir = sm.SKILLS_DIR
        self._orig_index = sm.SKILLS_INDEX_FILE
        sm.SKILLS_DIR = os.path.join(self.tmp, "skills")
        sm.SKILLS_INDEX_FILE = os.path.join(self.tmp, "skills_index.json")

    def tearDown(self):
        sm.SKILLS_DIR = self._orig_dir
        sm.SKILLS_INDEX_FILE = self._orig_index
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_skill_dir(self, base=None):
        base = base or os.path.join(self.tmp, "src_skill")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(SKILL_MD)
        with open(os.path.join(base, "asset.txt"), "w", encoding="utf-8") as f:
            f.write("asset")
        return base

    def test_install_directory(self):
        src = self._make_skill_dir()
        entry = sm.install_skill(src)
        self.assertEqual(entry["name"], "文案风格改写")
        self.assertIn("严格按品牌风格改写", entry["instruction"])
        skills = sm.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertTrue(os.path.isfile(os.path.join(sm.SKILLS_DIR, entry["id"], "asset.txt")))

    def test_install_single_md_file(self):
        md_path = os.path.join(self.tmp, "High-Retention-Video-Hook.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# 高留存视频钩子\n\n先给结果，再给理由，最后给行动指引。")
        entry = sm.install_skill(md_path)
        self.assertEqual(entry["name"], "High-Retention-Video-Hook")
        self.assertIn("高留存视频钩子", entry["instruction"])
        self.assertTrue(os.path.isfile(
            os.path.join(sm.SKILLS_DIR, entry["id"], "SKILL.md")))

    def test_install_directory_with_single_md(self):
        d = os.path.join(self.tmp, "hook_skill")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "hook.md"), "w", encoding="utf-8") as f:
            f.write("钩子技能正文")
        entry = sm.install_skill(d)
        self.assertEqual(entry["name"], "hook")
        self.assertEqual(len(sm.list_skills()), 1)

    def test_install_zip(self):
        zip_path = os.path.join(self.tmp, "skill.zip")
        src = self._make_skill_dir(os.path.join(self.tmp, "zip_src", "my-skill"))
        with zipfile.ZipFile(zip_path, "w") as z:
            for root, _dirs, files in os.walk(src):
                for f in files:
                    p = os.path.join(root, f)
                    z.write(p, os.path.relpath(p, os.path.join(self.tmp, "zip_src")))
        entry = sm.install_skill(zip_path)
        self.assertEqual(entry["name"], "文案风格改写")
        self.assertEqual(len(sm.list_skills()), 1)

    def test_remove_skill(self):
        src = self._make_skill_dir()
        entry = sm.install_skill(src)
        self.assertTrue(sm.remove_skill(entry["id"]))
        self.assertEqual(sm.list_skills(), [])
        self.assertFalse(os.path.isdir(os.path.join(sm.SKILLS_DIR, entry["id"])))

    def test_reject_zip_traversal(self):
        zip_path = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("../evil.txt", "bad")
        with self.assertRaises(RuntimeError):
            sm.install_skill(zip_path)

    def test_missing_skill_md(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        with self.assertRaises(FileNotFoundError):
            sm.install_skill(empty)

    def test_reject_multiple_md_in_dir(self):
        d = os.path.join(self.tmp, "multi")
        os.makedirs(d, exist_ok=True)
        for name in ("a.md", "b.md"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("x")
        with self.assertRaises(ValueError):
            sm.install_skill(d)

    @mock.patch.object(sm, "is_builtin", return_value=True)
    def test_remove_builtin_rejected(self, m_is_builtin):
        """内置技能（客户端功能）不允许卸载。"""
        self.assertFalse(sm.remove_skill("viral-video-download"))
        m_is_builtin.assert_called_once_with("viral-video-download")

    def test_is_builtin_detects_packaged_skill(self):
        """仓库内置技能包（爆款视频下载）应被识别为内置。"""
        self.assertTrue(sm.is_builtin("viral-video-download"))

    def test_is_builtin_unknown_false(self):
        self.assertFalse(sm.is_builtin("no-such-skill"))
        self.assertFalse(sm.is_builtin(""))


if __name__ == "__main__":
    unittest.main()
