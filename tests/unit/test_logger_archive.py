# -*- coding: utf-8 -*-
"""logger_utils 日志归档:启动切分/按日期保留/历史读取。"""
import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils import logger_utils as lu


class TestLoggerArchive(unittest.TestCase):
    def setUp(self):
        self._orig_dir = lu.LOG_DIR
        self.tmp = tempfile.mkdtemp(prefix="dsh_logger_test_")
        lu.LOG_DIR = self.tmp

    def tearDown(self):
        lu.LOG_DIR = self._orig_dir

    def test_split_session_log(self):
        app = os.path.join(self.tmp, "app.log")
        with open(app, "w", encoding="utf-8") as f:
            f.write("old line\n")
        lu._split_session_log(self.tmp)
        archived = [f for f in os.listdir(self.tmp) if f.startswith("app-")]
        self.assertEqual(len(archived), 1)
        self.assertTrue(archived[0].startswith("app-"))
        self.assertFalse(os.path.exists(app), "app.log 应已被改名归档")

    def test_split_no_app_log(self):
        lu._split_session_log(self.tmp)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_list_and_read_history(self):
        app = os.path.join(self.tmp, "app.log")
        with open(app, "w", encoding="utf-8") as f:
            f.write("new1\nnew2\n")
        lu._split_session_log(self.tmp)
        hist_name = [f for f in os.listdir(self.tmp) if f.startswith("app-")][0]
        with open(app, "w", encoding="utf-8") as f:
            f.write("cur1\n")
        files = lu.list_log_files()
        names = [n for n, _ in files]
        self.assertEqual(names[0], "app.log")
        self.assertIn(hist_name, names)
        hist = lu.get_last_logs(10, path=os.path.join(self.tmp, hist_name))
        self.assertIn("new2", hist)
        self.assertNotIn("cur1", hist)
        cur = lu.get_last_logs(10, path=None)
        self.assertIn("cur1", cur)

    def test_cleanup_by_date(self):
        app = os.path.join(self.tmp, "app.log")
        with open(app, "w", encoding="utf-8") as f:
            f.write("x\n")
        lu._split_session_log(self.tmp)
        fresh = [f for f in os.listdir(self.tmp) if f.startswith("app-")][0]
        old_ts = time.strftime("%Y-%m-%d_%H-%M-%S",
                               time.localtime(time.time() - 40 * 86400))
        old_path = os.path.join(self.tmp, f"app-{old_ts}.log")
        with open(old_path, "w", encoding="utf-8") as f:
            f.write("y\n")
        lu._cleanup_old_logs(self.tmp)
        self.assertFalse(os.path.exists(old_path), "超龄归档应被清理")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, fresh)),
                        "新归档不应被误删")

    def test_label(self):
        self.assertEqual(lu.log_file_label("app.log"), "本次会话")
        lbl = lu.log_file_label("app-2026-08-17_11-15-30.log")
        self.assertEqual(lbl, "2026-08-17 11:15 启动")


if __name__ == "__main__":
    unittest.main()
