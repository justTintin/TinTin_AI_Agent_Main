"""storyboard_client 路径清理测试。

服务端 OpenAPI 只存在 /api/storyboard/scripts，没有 /storyboard/scripts（无前缀）。
清理后应：
1. _script_urls 只返回旧路径 1 条
2. list_scripts / get_script / save_script 只发起 1 次请求（不再先 404 再回退）
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import storyboard_client as sc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data
        self.text = str(data or "")

    def json(self):
        return self._data


class TestScriptUrl(unittest.TestCase):
    def test_only_legacy_path(self):
        """清理后 _script_url 只返回旧路径（/api/storyboard/scripts），不再尝试双路径。"""
        url = sc._script_url("http://srv")
        self.assertIn("/api/storyboard/scripts", url)
        # 不应包含无前缀的 /storyboard/scripts（无 /api）
        self.assertNotIn("/storyboard/scripts", url.replace("/api/storyboard/scripts", ""))

    def test_with_suffix(self):
        url = sc._script_url("http://srv", "/abc123")
        self.assertTrue(url.endswith("/api/storyboard/scripts/abc123"))

    def test_trailing_slash_stripped(self):
        url = sc._script_url("http://srv/")
        self.assertFalse("//api" in url)


class TestListScriptsSingleRequest(unittest.TestCase):
    @mock.patch.object(sc, "http_get", return_value=_Resp(200, {"items": [{"id": "s1"}]}))
    @mock.patch.object(sc, "_server_url", return_value="http://srv")
    def test_only_one_request(self, m_url, m_get):
        """list_scripts 成功时应只发 1 次请求。"""
        result = sc.list_scripts(page=1, page_size=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "s1")
        self.assertEqual(m_get.call_count, 1,
                         f"应只调用 1 次 http_get，实际={m_get.call_count}次（双路径回退会调用2次）")
        # 确认请求的是旧路径
        called_url = m_get.call_args.args[0]
        self.assertIn("/api/storyboard/scripts", called_url)

    @mock.patch.object(sc, "http_get", return_value=_Resp(200, [{"id": "s2"}]))
    @mock.patch.object(sc, "_server_url", return_value="http://srv")
    def test_raw_list_response(self, m_url, m_get):
        """裸数组响应应直接返回。"""
        result = sc.list_scripts()
        self.assertEqual(len(result), 1)
        self.assertEqual(m_get.call_count, 1)


class TestGetScriptSingleRequest(unittest.TestCase):
    @mock.patch.object(sc, "http_get", return_value=_Resp(200, {"id": "s3", "topic": "test"}))
    @mock.patch.object(sc, "_server_url", return_value="http://srv")
    def test_only_one_request(self, m_url, m_get):
        """get_script 成功时应只发 1 次请求。"""
        data = sc.get_script("s3")
        self.assertEqual(data["topic"], "test")
        self.assertEqual(m_get.call_count, 1)
        called_url = m_get.call_args.args[0]
        self.assertIn("/api/storyboard/scripts/s3", called_url)


class TestSaveScriptSingleRequest(unittest.TestCase):
    @mock.patch.object(sc, "http_post", return_value=_Resp(200, {"ok": True}))
    @mock.patch.object(sc, "_server_url", return_value="http://srv")
    def test_only_one_request(self, m_url, m_post):
        """save_script 成功时应只发 1 次请求。"""
        ok = sc.save_script({"topic": "t", "shots": []})
        self.assertTrue(ok)
        self.assertEqual(m_post.call_count, 1)
        called_url = m_post.call_args.args[0]
        self.assertIn("/api/storyboard/scripts", called_url)


if __name__ == "__main__":
    unittest.main()
