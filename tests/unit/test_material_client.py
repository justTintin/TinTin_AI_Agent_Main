"""material_client 测试：search / list / serve_url / thumbnail_url / stats /
distinct / stock_search / status。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import material_client as mc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data
        self.text = str(data or "")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(f"HTTP {self.status_code}")


class TestSearch(unittest.TestCase):
    @mock.patch.object(mc, "http_post", return_value=_Resp(200, {"results": [{"id": "m1"}], "total": 1}))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_search_success(self, m_url, m_post):
        data = mc.search({"keyword": "鼠标", "media_type": "image"}, timeout=20)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["results"]), 1)

    @mock.patch.object(mc, "http_post", return_value=_Resp(500))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_search_http_error(self, m_url, m_post):
        data = mc.search({"keyword": "test"})
        self.assertIsNone(data)

    @mock.patch.object(mc, "_server_url", return_value="")
    def test_search_no_server(self, m_url):
        data = mc.search({"keyword": "test"})
        self.assertIsNone(data)


class TestList(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, {"items": [{"id": "m1"}], "total": 50}))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_list_success(self, m_url, m_get):
        data = mc.list({"page": 1, "size": 50}, timeout=20)
        self.assertEqual(data["total"], 50)

    @mock.patch.object(mc, "http_get", return_value=_Resp(200, []))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_list_empty(self, m_url, m_get):
        data = mc.list({"page": 1})
        self.assertEqual(data, [])


class TestServeUrl(unittest.TestCase):
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_serve_url(self, m_url):
        url = mc.serve_url("m123")
        self.assertEqual(url, "http://srv/material/serve?material_id=m123")

    @mock.patch.object(mc, "_server_url", return_value="")
    def test_serve_url_no_server(self, m_url):
        url = mc.serve_url("m123")
        self.assertEqual(url, "")


class TestThumbnailUrl(unittest.TestCase):
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_thumbnail_url(self, m_url):
        url = mc.thumbnail_url("m456")
        self.assertEqual(url, "http://srv/material/thumbnail?material_id=m456")


class TestStats(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, {"total": 100, "images": 60, "videos": 40}))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_stats_success(self, m_url, m_get):
        data = mc.stats(timeout=10)
        self.assertEqual(data["total"], 100)

    @mock.patch.object(mc, "http_get", return_value=_Resp(500))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_stats_error(self, m_url, m_get):
        data = mc.stats()
        self.assertIsNone(data)


class TestDistinct(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, ["罗技", "雷蛇", "达尔优"]))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_distinct_success(self, m_url, m_get):
        values = mc.distinct("brand", timeout=15)
        self.assertEqual(len(values), 3)
        self.assertIn("罗技", values)

    @mock.patch.object(mc, "http_get", return_value=_Resp(500))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_distinct_error(self, m_url, m_get):
        values = mc.distinct("brand")
        self.assertEqual(values, [])


class TestStockSearch(unittest.TestCase):
    @mock.patch.object(mc, "http_post", return_value=_Resp(200, {"results": [{"url": "http://x.jpg"}], "total": 1}))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_stock_search_success(self, m_url, m_post):
        data = mc.stock_search("无线鼠标", "image", timeout=20)
        self.assertEqual(data["total"], 1)
        body = m_post.call_args.kwargs["json"]
        self.assertEqual(body["query"], "无线鼠标")
        self.assertEqual(body["kind"], "image")

    @mock.patch.object(mc, "http_post", return_value=_Resp(500))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_stock_search_error(self, m_url, m_post):
        data = mc.stock_search("test", "video")
        self.assertIsNone(data)


class TestStatus(unittest.TestCase):
    @mock.patch.object(mc, "http_get", return_value=_Resp(200, {"status": "ok", "ocr": True}))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_status_ok(self, m_url, m_get):
        data = mc.status(timeout=5)
        self.assertEqual(data["status"], "ok")

    @mock.patch.object(mc, "http_get", return_value=_Resp(503))
    @mock.patch.object(mc, "_server_url", return_value="http://srv")
    def test_status_error(self, m_url, m_get):
        data = mc.status()
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
