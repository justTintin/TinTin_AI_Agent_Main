"""ytdlp_utils 测试：update_ytdlp 封装 yt-dlp -U 自更新。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import ytdlp_utils as yu  # noqa: E402


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestUpdateYtdlp(unittest.TestCase):
    @mock.patch("utils.ytdlp_utils.subprocess.run",
               return_value=_FakeProc(0, stdout="yt-dlp is up to date (2024.01.01)"))
    def test_update_success(self, m_run):
        ok, msg = yu.update_ytdlp("C:/bin/yt-dlp.exe")
        self.assertTrue(ok)
        self.assertIn("up to date", msg)
        # 确认调用参数
        args, kwargs = m_run.call_args
        self.assertEqual(args[0], ["C:/bin/yt-dlp.exe", "-U"])
        self.assertTrue(kwargs.get("capture_output"))
        self.assertEqual(kwargs.get("timeout"), 300)

    @mock.patch("utils.ytdlp_utils.subprocess.run",
               return_value=_FakeProc(0, stdout="", stderr="Updating to version 2024.02.01 ..."))
    def test_update_success_from_stderr(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp")
        self.assertTrue(ok)
        self.assertIn("2024.02.01", msg)

    @mock.patch("utils.ytdlp_utils.subprocess.run",
               return_value=_FakeProc(1, stdout="", stderr="ERROR: unable to update"))
    def test_update_failure_returncode(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp")
        self.assertFalse(ok)
        self.assertIn("unable to update", msg)

    @mock.patch("utils.ytdlp_utils.subprocess.run",
               return_value=_FakeProc(0, stdout="line1\nline2\nlast_line", stderr=""))
    def test_update_returns_last_line(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp")
        self.assertTrue(ok)
        self.assertEqual(msg, "last_line")

    @mock.patch("utils.ytdlp_utils.subprocess.run",
               return_value=_FakeProc(0, stdout="", stderr=""))
    def test_update_empty_output(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp")
        self.assertTrue(ok)
        self.assertEqual(msg, "完成")

    @mock.patch("utils.ytdlp_utils.subprocess.run", side_effect=TimeoutError("timeout"))
    def test_update_timeout(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp", timeout=10)
        self.assertFalse(ok)
        self.assertIn("timeout", msg.lower())

    @mock.patch("utils.ytdlp_utils.subprocess.run", side_effect=Exception("boom"))
    def test_update_generic_exception(self, m_run):
        ok, msg = yu.update_ytdlp("yt-dlp")
        self.assertFalse(ok)
        self.assertIn("boom", msg)


if __name__ == "__main__":
    unittest.main()
