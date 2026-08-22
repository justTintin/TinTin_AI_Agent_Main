"""scheduled_task_client 新增函数测试：evaluate_by_task / download_result_file。"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import scheduled_task_client as stc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None, content=b"", headers=None):
        self.status_code = status_code
        self._data = data
        self._content = content
        self.headers = headers or {}

    def json(self):
        return self._data

    @property
    def content(self):
        return self._content

    def iter_content(self, chunk_size=8192):
        yield self._content

    def close(self):
        pass


class TestEvaluateByTask(unittest.TestCase):
    @mock.patch.object(stc, "http_get", return_value=_Resp(200, {"evaluation": {"total": 85, "breakdown": {}}}))
    @mock.patch.object(stc, "_server_url", return_value="http://srv")
    def test_success(self, m_url, m_get):
        ev = stc.evaluate_by_task("task-1")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["total"], 85)

    @mock.patch.object(stc, "http_get", return_value=_Resp(200, {"evaluation": {"foo": "bar"}}))
    @mock.patch.object(stc, "_server_url", return_value="http://srv")
    def test_no_total_field(self, m_url, m_get):
        """evaluation 缺少 total 字段 → 返回 None。"""
        ev = stc.evaluate_by_task("task-2")
        self.assertIsNone(ev)

    @mock.patch.object(stc, "http_get", return_value=_Resp(404))
    @mock.patch.object(stc, "_server_url", return_value="http://srv")
    def test_http_error(self, m_url, m_get):
        ev = stc.evaluate_by_task("task-3")
        self.assertIsNone(ev)

    @mock.patch.object(stc, "http_get", side_effect=requests.exceptions.RequestException("timeout"))
    @mock.patch.object(stc, "_server_url", return_value="http://srv")
    def test_exception(self, m_url, m_get):
        ev = stc.evaluate_by_task("task-4")
        self.assertIsNone(ev)


class TestDownloadResultFile(unittest.TestCase):
    @mock.patch.object(stc, "http_get", return_value=_Resp(200, content=b"video_bytes"))
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("os.makedirs")
    def test_download_binary(self, m_makedirs, m_open, m_get):
        result = stc.download_result_file("http://srv/out.mp4", "/tmp/out.mp4")
        self.assertEqual(result, "/tmp/out.mp4")
        m_open.assert_called_once()

    @mock.patch.object(stc, "http_get", side_effect=[
        _Resp(200, data={"url": "http://srv/real.mp4"},
              headers={"Content-Type": "application/json"}),
        _Resp(200, content=b"real_video"),
    ])
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("os.makedirs")
    def test_download_json_redirect(self, m_makedirs, m_open, m_get):
        """服务端返回 JSON {url:...} 时应取地址重试。"""
        result = stc.download_result_file("http://srv/redirect", "/tmp/out.mp4")
        self.assertEqual(result, "/tmp/out.mp4")
        self.assertEqual(m_get.call_count, 2)

    @mock.patch.object(stc, "http_get", return_value=_Resp(404))
    @mock.patch("os.makedirs")
    def test_download_http_error(self, m_makedirs, m_get):
        with self.assertRaises(RuntimeError):
            stc.download_result_file("http://srv/missing.mp4", "/tmp/out.mp4")


if __name__ == "__main__":
    unittest.main()
