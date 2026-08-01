# -*- coding: utf-8 -*-
"""语法/导入健康检查：全部 studio Python 文件可编译，关键模块可导入。"""
import os
import py_compile
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

STUDIO_DIR = testutil.STUDIO_DIR
SKIP_DIRS = {".runtime", "__pycache__", "backups", ".idea"}

PURE_MODULES = [
    ("config", "paths"),
    ("utils", "config_manager"),
    ("utils", "brand_normalizer"),
    ("utils", "extreme_words"),
    ("utils", "hwaccel"),
    ("utils", "shot_analysis_cache"),
    ("utils", "http_client"),
    ("utils", "backup_manager"),
    ("utils", "platform_utils"),
    ("utils", "logger_utils"),
    ("utils", "data_registry"),
    ("core", "douyin_parser"),
]


def _all_py_files():
    out = []
    for root, dirs, files in os.walk(STUDIO_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return out


class TestSyntaxImports(unittest.TestCase):
    def test_all_python_files_compile(self):
        failed = []
        for fp in _all_py_files():
            try:
                py_compile.compile(fp, doraise=True)
            except py_compile.PyCompileError as e:
                failed.append(str(e))
        self.assertEqual(failed, [], "编译失败:\n" + "\n".join(failed[:20]))

    def test_pure_modules_import(self):
        testutil.ensure_studio_on_path()
        failed = []
        for pkg, mod in PURE_MODULES:
            try:
                __import__(f"{pkg}.{mod}")
            except Exception as e:
                failed.append(f"{pkg}.{mod}: {type(e).__name__}: {e}")
        self.assertEqual(failed, [], "导入失败:\n" + "\n".join(failed))

    def test_http_client_interface(self):
        testutil.ensure_studio_on_path()
        from utils.http_client import http_get, http_post, resilient_get, resilient_post
        self.assertTrue(callable(http_get))
        self.assertTrue(callable(http_post))


if __name__ == "__main__":
    unittest.main()