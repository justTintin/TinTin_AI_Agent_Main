# -*- coding: utf-8 -*-
"""config.paths：路径常量与目录结构。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from config import paths


class TestPaths(unittest.TestCase):
    def test_root_constants(self):
        self.assertTrue(paths.PROJECT_ROOT.endswith("studio"))
        self.assertEqual(paths.WORKSPACE_ROOT, testutil.PROJECT_ROOT)

    def test_required_dirs_exist(self):
        for name in ("LOG_DIR", "TMP_DIR", "COOKIES_DIR", "ACCOUNTS_DIR", "DATA_DIR", "OUTPUTS_DIR"):
            d = getattr(paths, name)
            self.assertTrue(os.path.isdir(d), f"{name}={d} 不存在")

    def test_key_files_defined(self):
        for name in ("AI_CONFIG_FILE", "PRODUCT_LIBRARY_FILE", "MEDIA_LIBRARY_FILE",
                     "HOTSPOTS_FILE", "BRAND_DICTIONARY_FILE", "CONFIG_INI_FILE"):
            self.assertTrue(getattr(paths, name), name)

    def test_platform_dirs(self):
        self.assertIn("win", paths.BIN_PLATFORM_DIR)
        self.assertEqual(paths.APPS_DIR, os.path.join(paths.WORKSPACE_ROOT, "apps"))


if __name__ == "__main__":
    unittest.main()