"""os_utils 测试：open_in_explorer + kill_process_tree。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import os_utils as ou  # noqa: E402


class TestOpenInExplorer(unittest.TestCase):
    @mock.patch("subprocess.Popen")
    def test_open_dir_windows(self, m_popen):
        with mock.patch.object(sys, "platform", "win32"):
            ou.open_in_explorer("/tmp/folder", select=False)
        cmd = m_popen.call_args.args[0]
        self.assertTrue(cmd.startswith("explorer "))
        self.assertIn("folder", cmd)
        self.assertNotIn("/select,", cmd)

    @mock.patch("subprocess.Popen")
    def test_select_file_windows(self, m_popen):
        with mock.patch("os.path.isfile", return_value=True), mock.patch.object(sys, "platform", "win32"):
            ou.open_in_explorer("C:\\videos\\a.mp4", select=True)
        cmd = m_popen.call_args.args[0]
        self.assertIn('/select,', cmd)
        self.assertIn('a.mp4', cmd)

    @mock.patch("subprocess.Popen")
    def test_open_dir_linux(self, m_popen):
        with mock.patch("os.path.isfile", return_value=False), mock.patch.object(sys, "platform", "linux2"):
            ou.open_in_explorer("/tmp/folder", select=False)
        args = m_popen.call_args.args[0]
        self.assertEqual(args[0], "xdg-open")
        self.assertIn("folder", args[1])

    @mock.patch("subprocess.Popen")
    def test_open_file_linux_opens_dirname(self, m_popen):
        with mock.patch("os.path.isfile", return_value=True), mock.patch.object(sys, "platform", "linux2"):
            ou.open_in_explorer("/tmp/v/a.mp4", select=True)
        args = m_popen.call_args.args[0]
        self.assertEqual(args[0], "xdg-open")
        # xdg-open 只能开目录不能选文件，应返回目录
        self.assertNotIn("a.mp4", args[1])
        self.assertIn("v", args[1])

    @mock.patch("subprocess.Popen", side_effect=OSError("explorer not found"))
    def test_exception_no_raise(self, m_popen):
        """异常应被 log 记录但不抛出。"""
        try:
            with mock.patch.object(sys, "platform", "win32"):
                ou.open_in_explorer("/tmp")
        except Exception as e:
            self.fail(f"不应抛出异常，实际：{e}")


class TestKillProcessTree(unittest.TestCase):
    @mock.patch("subprocess.run")
    def test_kill_windows(self, m_run):
        with mock.patch.object(sys, "platform", "win32"):
            result = ou.kill_process_tree(1234)
        self.assertTrue(result)
        args = m_run.call_args.args[0]
        self.assertIn("taskkill", args)
        self.assertIn("/PID", args)
        self.assertIn("1234", args)
        self.assertIn("/F", args)
        self.assertIn("/T", args)

    @mock.patch("os.kill")
    def test_kill_unix(self, m_kill):
        with mock.patch.object(sys, "platform", "linux2"):
            result = ou.kill_process_tree(5678)
        self.assertTrue(result)
        m_kill.assert_called_once()
        self.assertEqual(m_kill.call_args.args[0], 5678)

    @mock.patch("subprocess.run", side_effect=OSError("boom"))
    def test_kill_exception_returns_false(self, m_run):
        with mock.patch.object(sys, "platform", "win32"):
            result = ou.kill_process_tree(1)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
