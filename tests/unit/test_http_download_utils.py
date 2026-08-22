"""http_download_utils 测试（红）。"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import http_download_utils as hdu  # noqa: E402


class _FakeResponse:
    def __init__(self, content=b"", status_code=200, chunks=None):
        self.status_code = status_code
        self.content = content
        self._chunks = chunks or [content]
        self.text = ""

    def raise_for_status(self):
        if self.status_code != 200:  # noqa: PLR2004
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


class TestDownloadFile(unittest.TestCase):
    @mock.patch("utils.http_download_utils.requests.get")
    @mock.patch("utils.http_download_utils.os.path.getsize", return_value=1024)
    @mock.patch("utils.http_download_utils.os.path.isfile", return_value=True)
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_download_success(self, m_open, m_isfile, m_getsize, m_get):
        m_get.return_value = _FakeResponse(content=b"hello world")
        result = hdu.download_file("http://example.com/file.mp4", "/tmp/file.mp4")
        self.assertTrue(result)
        m_get.assert_called_once_with("http://example.com/file.mp4", timeout=120, stream=True)

    @mock.patch("utils.http_download_utils.requests.get")
    @mock.patch("utils.http_download_utils.os.path.getsize", return_value=1024)
    @mock.patch("utils.http_download_utils.os.path.isfile", return_value=True)
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_download_stream_chunks(self, m_open, m_isfile, m_getsize, m_get):
        m_get.return_value = _FakeResponse(
            content=b"abcdef",
            chunks=[b"abc", b"def"]
        )
        result = hdu.download_file("http://example.com/v.mp4", "/tmp/v.mp4", timeout=60)
        self.assertTrue(result)

    @mock.patch("utils.http_download_utils.requests.get")
    @mock.patch("utils.http_download_utils.os.path.getsize", return_value=1024)
    @mock.patch("utils.http_download_utils.os.path.isfile", return_value=True)
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_download_no_stream(self, m_open, m_isfile, m_getsize, m_get):
        m_get.return_value = _FakeResponse(content=b"data")
        result = hdu.download_file("http://example.com/v.mp4", "/tmp/v.mp4", stream=False)
        self.assertTrue(result)
        # stream=False 时不应传 stream 参数
        kwargs = m_get.call_args.kwargs
        self.assertNotIn("stream", kwargs)

    @mock.patch("utils.http_download_utils.requests.get")
    def test_download_http_error(self, m_get):
        m_get.return_value = _FakeResponse(status_code=404)
        result = hdu.download_file("http://example.com/notfound", "/tmp/x.mp4")
        self.assertFalse(result)

    @mock.patch("utils.http_download_utils.requests.get", side_effect=requests.exceptions.RequestException("network error"))
    def test_download_network_error(self, m_get):
        result = hdu.download_file("http://example.com/x", "/tmp/x")
        self.assertFalse(result)

    @mock.patch("utils.http_download_utils.requests.get")
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_download_custom_timeout(self, m_open, m_get):
        m_get.return_value = _FakeResponse(content=b"x")
        hdu.download_file("http://x.com/f", "/tmp/f", timeout=30)
        self.assertEqual(m_get.call_args.kwargs["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
