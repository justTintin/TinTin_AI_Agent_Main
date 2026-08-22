"""template_server_client 新增函数测试：poll_render_status / download_render_result。"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import template_server_client as tsc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None, content=b"", text=""):
        self.status_code = status_code
        self._data = data
        self._content = content
        self.text = text or str(data or "")

    def json(self):
        return self._data

    @property
    def content(self):
        return self._content

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self._content

    def close(self):
        pass


class TestPollRenderStatus(unittest.TestCase):
    @mock.patch.object(tsc, "http_get", return_value=_Resp(200, {"status": "running", "progress": 30}))
    @mock.patch.object(tsc, "_server_url", return_value="http://srv")
    def test_first_endpoint_success(self, m_url, m_get):
        data = tsc.poll_render_status("task-1")
        self.assertEqual(data, {"status": "running", "progress": 30})
        self.assertIn("/templates/render/result/task-1", m_get.call_args.args[0])

    @mock.patch.object(tsc, "http_get", side_effect=[
        _Resp(404),  # templates/render/result 失败
        _Resp(200, {"status": "completed", "progress": 100}),  # tasks/unified 成功
    ])
    @mock.patch.object(tsc, "_server_url", return_value="http://srv")
    def test_fallback_to_unified(self, m_url, m_get):
        data = tsc.poll_render_status("task-2")
        self.assertEqual(data["status"], "completed")
        self.assertEqual(m_get.call_count, 2)

    @mock.patch.object(tsc, "http_get", side_effect=requests.exceptions.RequestException("network"))
    @mock.patch.object(tsc, "_server_url", return_value="http://srv")
    def test_all_endpoints_fail(self, m_url, m_get):
        data = tsc.poll_render_status("task-3")
        self.assertIsNone(data)

    @mock.patch.object(tsc, "_server_url", return_value="")
    def test_no_server_url(self, m_url):
        data = tsc.poll_render_status("task-4")
        self.assertIsNone(data)

    @mock.patch.object(tsc, "_server_url", return_value="http://srv")
    def test_empty_task_id(self, m_url):
        data = tsc.poll_render_status("")
        self.assertIsNone(data)


class TestDownloadRenderResult(unittest.TestCase):
    @mock.patch.object(tsc, "http_get", return_value=_Resp(200, content=b"fake_video_data"))
    @mock.patch("utils.mg_server_client._ensure_url", return_value="http://srv/output.mp4")
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("os.makedirs")
    def test_download_success(self, m_makedirs, m_open, m_ensure, m_get):
        result = tsc.download_render_result("http://srv/output.mp4", "/tmp/out.mp4")
        self.assertEqual(result, "/tmp/out.mp4")
        m_get.assert_called_once()
        m_open.assert_called_once()

    @mock.patch.object(tsc, "http_get", return_value=_Resp(404))
    @mock.patch("utils.mg_server_client._ensure_url", return_value="http://srv/missing.mp4")
    @mock.patch("os.makedirs")
    def test_download_http_error(self, m_makedirs, m_ensure, m_get):
        result = tsc.download_render_result("http://srv/missing.mp4", "/tmp/out.mp4")
        self.assertIsNone(result)

    @mock.patch.object(tsc, "http_get", side_effect=requests.exceptions.RequestException("timeout"))
    @mock.patch("utils.mg_server_client._ensure_url", return_value="http://srv/timeout.mp4")
    @mock.patch("os.makedirs")
    def test_download_exception(self, m_makedirs, m_ensure, m_get):
        result = tsc.download_render_result("http://srv/timeout.mp4", "/tmp/out.mp4")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
