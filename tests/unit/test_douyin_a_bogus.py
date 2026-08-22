"""douyin_a_bogus 测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core import douyin_a_bogus  # noqa: E402


class _FakeProc:
    """模拟 Popen 对象。p.stdout 直接是 bytes 子类，支持 .read() 和链式 .strip().decode()。"""
    def __init__(self, stdout_bytes: bytes):
        class FakeStdout:
            def __init__(self): self._data = stdout_bytes
            def read(self): return self._data
        self.stdout = FakeStdout()


class TestGetAb(unittest.TestCase):
    @mock.patch("core.douyin_a_bogus.subprocess.Popen",
                return_value=_FakeProc(b"some log\na_bogus: abc123xyz"))
    def test_extract_ab_from_stdout(self, m_popen):
        result = douyin_a_bogus.get_ab("http://t?a=1", "UA", "k=v")
        self.assertEqual(result, "abc123xyz")
        args = m_popen.call_args.args[0]
        self.assertEqual(args[0], "node")
        self.assertIn("douyin_a_bogus.js", args[1])

    @mock.patch("core.douyin_a_bogus.subprocess.Popen", side_effect=[
        _FakeProc(b"no match here\n"),     # 第1次: 正则无匹配 → 抛 AttributeError → except
        _FakeProc(b"a_bogus: second_chance\n"),  # 第2次: 成功
    ])
    def test_retry_on_first_failure(self, m_popen):
        """第一次 stdout 不含 a_bogus，re.search 抛 AttributeError → 重试第2次。"""
        result = douyin_a_bogus.get_ab("http://t", "UA", "cookie")
        self.assertEqual(result, "second_chance")
        self.assertEqual(m_popen.call_count, 2)

    @mock.patch("core.douyin_a_bogus.subprocess.Popen",
                side_effect=FileNotFoundError("node not installed"))
    def test_both_fail_returns_false(self, m_popen):
        """两次都异常 → 返回 False。"""
        result = douyin_a_bogus.get_ab("http://t", "UA", "cookie")
        self.assertIs(result, False)
        self.assertEqual(m_popen.call_count, 2)

    @mock.patch("core.douyin_a_bogus.subprocess.Popen",
                return_value=_FakeProc(b"a_bogus: DEF456"))
    def test_args_passed_through(self, m_popen):
        url = "http://dy?a=1&b=2"
        ua = "Mozilla Chrome"
        ck = "sessionid=abc"
        douyin_a_bogus.get_ab(url, ua, ck)
        args = m_popen.call_args.args[0]
        self.assertEqual(args[2], url)
        self.assertEqual(args[3], ua)
        self.assertEqual(args[4], ck)


if __name__ == "__main__":
    unittest.main()
