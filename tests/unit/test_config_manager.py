# -*- coding: utf-8 -*-
"""config_manager：JSON/INI 配置读写、容错。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from utils import config_manager as cm


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cm_test_")
        self._orig = dict(cm._JSON_FILES)
        cm._JSON_FILES["test_cfg"] = os.path.join(self.tmp, "test_cfg.json")
        self._orig_ini = cm.CONFIG_INI_FILE
        cm.CONFIG_INI_FILE = os.path.join(self.tmp, "config.ini")

    def tearDown(self):
        cm._JSON_FILES.clear()
        cm._JSON_FILES.update(self._orig)
        cm.CONFIG_INI_FILE = self._orig_ini
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_load_roundtrip(self):
        self.assertTrue(cm.save_config("test_cfg", {"a": 1, "b": "中文"}))
        self.assertEqual(cm.load_config("test_cfg"), {"a": 1, "b": "中文"})

    def test_load_missing_returns_default(self):
        cm._JSON_FILES["missing"] = os.path.join(self.tmp, "nope.json")
        self.assertEqual(cm.load_config("missing"), {})
        self.assertEqual(cm.load_config("missing", {"x": 1}), {"x": 1})

    def test_load_corrupt_returns_default(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        cm._JSON_FILES["bad"] = p
        self.assertEqual(cm.load_config("bad"), {})

    def test_set_setting_persists(self):
        cm.set_setting("test_cfg", "media_dir", "D:/media")
        self.assertEqual(cm.get_setting("test_cfg", "media_dir"), "D:/media")
        self.assertEqual(cm.get_setting("test_cfg", "nope", 42), 42)

    def test_unknown_config_name_raises(self):
        with self.assertRaises(ValueError):
            cm._path_of("no_such_config")

    def test_ini_save_load(self):
        import configparser
        p = configparser.ConfigParser()
        p["server"] = {"host": "192.168.111.28", "port": "8000"}
        self.assertTrue(cm.save_ini(p))
        p2 = cm.load_ini()
        self.assertEqual(p2["server"]["host"], "192.168.111.28")


if __name__ == "__main__":
    unittest.main()