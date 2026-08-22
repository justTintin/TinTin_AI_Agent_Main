"""montage_client 测试：split / concat / beat / result_url / download_result /
poll_unified。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import montage_client as mc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None, content=b""):
        self.status_code = status_code
        self._data = data
        self._content = content
        self.text = str(data or "")

    def json(self):
        return self._data

    @property
    def content(self):
        return self._content

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self._content

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestSplit(unittest.TestCase):
    @mock.patch.object(mc, "http_post", return_value=_Resp(200, {"shots": [{"start": 0, "end": 5}]}))
    def test_split_success(self, m_post):
        resp = mc.split("http://srv", files={"file": ("v.mp4", b"data", "video/mp4")},
                        data={"mode": "auto"}, timeout=590)
        self.assertEqual(len(resp["shots"]), 1)

    @mock.patch.object(mc, "http_post", return_value=_Resp(500))
    def test_split_http_error(self, m_post):
        with self.assertRaises(RuntimeError):
            mc.split("http://srv", files={"file": ("v.mp4", b"data", "video/mp4")},
                     data={}, timeout=590)


class TestConcat(unittest.TestCase):
    @mock.patch.object(mc, "http_post", return_value=_Resp(200, {"task_id": "c-1"}))
    def test_concat_success(self, m_post):
        resp = mc.concat("http://srv", files=[("files", ("c1.mp4", b"")), ],
                         data={"fps": "30"}, timeout=120)
        self.assertEqual(resp["task_id"], "c-1")

    @mock.patch.object(mc, "http_post", return_value=_Resp(500))
    def test_concat_error(self, m_post):
        with self.assertRaises(RuntimeError):
            mc.concat("http://srv", files=[], data={}, timeout=60)


class TestBeat(unittest.TestCase):
    @mock.patch.object(mc, "http_post", return_value=_Resp(200, {"task_id": "b-1"}))
    def test_beat_success(self, m_post):
        resp = mc.beat("http://srv", files=[("files", ("c1.mp4", b"")), ],
                       data={"bpm": "120"}, timeout=120)
        self.assertEqual(resp["task_id"], "b-1")

    @mock.patch.object(mc, "http_post", return_value=_Resp(500))
    def test_beat_error(self, m_post):
        with self.assertRaises(RuntimeError):
            mc.beat("http://srv", files=[], data={}, timeout=60)


class TestResultUrl(unittest.TestCase):
    def test_result_url_no_variant(self):
        url = mc.result_url("http://srv", "t-1")
        self.assertEqual(url, "http://srv/montage/result/t-1")

    def test_result_url_with_variant(self):
        url = mc.result_url("http://srv", "t-1", variant=2)
        self.assertEqual(url, "http://srv/montage/result/t-1/2")

    def test_result_url_empty_server(self):
        url = mc.result_url("", "t-1")
        self.assertEqual(url, "")


class TestDownloadResult(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, content=b"video_data"))
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("os.makedirs")
    def test_download_success(self, m_makedirs, m_open, m_get):
        result = mc.download_result("http://srv/montage/result/t-1", "/tmp/out.mp4", timeout=300)
        self.assertEqual(result, "/tmp/out.mp4")
        m_open.assert_called_once()

    @mock.patch.object(mc, "http_get", return_value=_Resp(404))
    @mock.patch("os.makedirs")
    def test_download_http_error(self, m_makedirs, m_get):
        result = mc.download_result("http://srv/missing", "/tmp/out.mp4")
        self.assertIsNone(result)


class TestPollUnified(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, {"status": "completed", "progress": 100}))
    def test_poll_success(self, m_get):
        data = mc.poll_unified("http://srv", "t-1", timeout=15)
        self.assertEqual(data["status"], "completed")

    @mock.patch.object(mc, "http_get", return_value=_Resp(200, {"status": "running", "progress": 30}))
    def test_poll_running(self, m_get):
        data = mc.poll_unified("http://srv", "t-1")
        self.assertEqual(data["status"], "running")

    @mock.patch.object(mc, "http_get", return_value=_Resp(500))
    def test_poll_error(self, m_get):
        data = mc.poll_unified("http://srv", "t-1")
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
