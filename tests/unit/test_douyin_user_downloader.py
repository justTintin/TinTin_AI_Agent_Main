"""DouyinUserDownloader 测试。

重点覆盖纯解析/纯逻辑（不需要真实网络）：
- _extract_aweme_id（URL 提取视频 ID）
- _extract_sec_uid（本地正则提取 sec_uid，重定向走 mock）
- _load_cookies（读取 cookie 文件）
- aweme_id vs sec_uid 分支
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core.douyin_user_downloader import DouyinUserDownloader  # noqa: E402


class TestExtractAwemeId(unittest.TestCase):
    def test_video_id(self):
        dl = DouyinUserDownloader("https://www.douyin.com/video/7350291791045790991", cookie_str="a=b")
        self.assertEqual(dl.aweme_id, "7350291791045790991")
        self.assertIsNone(dl.sec_uid)

    def test_note_id(self):
        dl = DouyinUserDownloader("https://www.douyin.com/note/7366231405833063719", cookie_str="a=b")
        self.assertEqual(dl.aweme_id, "7366231405833063719")
        self.assertIsNone(dl.sec_uid)

    def test_modal_id(self):
        dl = DouyinUserDownloader(
            "https://www.douyin.com/user/MS4wLjAB?modal_id=7360123456789012345",
            cookie_str="a=b")
        # 优先走 /video/ 没匹配 → /note/ 没匹配 → 最后 modal_id
        self.assertEqual(dl.aweme_id, "7360123456789012345")

    def test_no_match(self):
        dl = DouyinUserDownloader("https://www.douyin.com/user/MS4wLjAB", cookie_str="a=b")
        self.assertIsNone(dl.aweme_id)
        self.assertIsNotNone(dl.sec_uid)


class TestExtractSecUid(unittest.TestCase):
    def test_user_home_sec_uid(self):
        dl = DouyinUserDownloader(
            "https://www.douyin.com/user/MS4wLjABAAAAnExampleSecUid",
            cookie_str="a=b")
        self.assertEqual(dl.sec_uid, "MS4wLjABAAAAnExampleSecUid")

    def test_sec_uid_url_without_dot(self):
        """user/<alphanumeric_and_dash> 应匹配。"""
        dl = DouyinUserDownloader(
            "https://www.douyin.com/user/MS4wLjAB-123_abc",
            cookie_str="a=b")
        self.assertEqual(dl.sec_uid, "MS4wLjAB-123_abc")

    def test_sec_uid_from_query_param(self):
        """无法匹配 user/xxx 片段，则从 ?sec_user_id=... 提取。"""
        dl = DouyinUserDownloader(
            "https://www.douyin.com/?sec_user_id=PARAM_SEC_123",
            cookie_str="a=b")
        self.assertEqual(dl.sec_uid, "PARAM_SEC_123")

    @mock.patch("core.douyin_user_downloader.http_get")
    def test_v_douyin_com_short_link_redirect(self, m_get):
        """v.douyin.com 短链接 → 重定向到 user/xxx 页面。"""
        class _R:
            url = "https://www.douyin.com/user/REDIRECTED_SEC_456"

        m_get.return_value = _R()
        dl = DouyinUserDownloader(
            "https://v.douyin.com/iJkLmN/", cookie_str="a=b")
        self.assertEqual(dl.sec_uid, "REDIRECTED_SEC_456")

    @mock.patch("core.douyin_user_downloader.http_get", side_effect=requests.exceptions.RequestException("network down"))
    def test_short_link_redirect_fail_graceful(self, m_get):
        """重定向异常 → 从原 URL 提取（如果不能提取返回 None）。"""
        dl = DouyinUserDownloader(
            "https://v.douyin.com/iJkLmN/", cookie_str="a=b")
        self.assertIsNone(dl.sec_uid)


class TestLoadCookies(unittest.TestCase):
    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("  sessionid=xyz; ttwid=123  \n")
            path = f.name
        try:
            dl = DouyinUserDownloader(
                "https://www.douyin.com/user/X", cookie_file=path)
            self.assertEqual(dl.cookies_str, "sessionid=xyz; ttwid=123")
            self.assertIn("Cookie", dl.headers)
            self.assertIn("sessionid=xyz", dl.headers["Cookie"])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_cookie_str_overrides_file(self):
        """构造时传入 cookie_str 优先，不读文件（哪怕不存在）。"""
        dl = DouyinUserDownloader(
            "https://www.douyin.com/user/X",
            cookie_file="/no/such/file.txt",
            cookie_str="direct=yes")
        self.assertEqual(dl.cookies_str, "direct=yes")

    def test_missing_cookie_file_empty_str(self):
        """cookie 文件不存在 → cookies_str 为 ""。"""
        dl = DouyinUserDownloader(
            "https://www.douyin.com/user/X",
            cookie_file="/no/such/file_c712f3.txt")
        self.assertEqual(dl.cookies_str, "")


class TestAwemeVsSec(unittest.TestCase):
    @mock.patch.object(DouyinUserDownloader, "_fetch_single_video",
                       return_value=[{"aweme_id": "1"}])
    def test_fetch_single_when_aweme_present(self, m_fetch):
        dl = DouyinUserDownloader(
            "https://www.douyin.com/video/7350291791045790991", cookie_str="a=b")
        res = dl.fetch_all_videos()
        self.assertEqual(len(res), 1)
        m_fetch.assert_called_once_with("7350291791045790991")

    def test_fetch_all_missing_both_raises(self):
        """既无 aweme_id 又 sec_uid 解析失败 → 抛异常。"""
        dl = DouyinUserDownloader("https://example.com/not-dy", cookie_str="a=b")
        with self.assertRaises(Exception):  # noqa: B017
            dl.fetch_all_videos()


if __name__ == "__main__":
    unittest.main()
