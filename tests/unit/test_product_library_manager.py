"""ProductLibraryManager 新增方法测试：sync / sync_status / mine / mine_status / get_item。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils.product_library_manager import ProductLibraryManager  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    @property
    def text(self):
        return str(self._data or "")

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(f"HTTP {self.status_code}")


class TestSync(unittest.TestCase):
    def setUp(self):
        self.mgr = ProductLibraryManager.__new__(ProductLibraryManager)
        self.mgr.machine_id = "test-mid"
        self.mgr.items = []
        self.mgr._cache_time = 0
        self.mgr._load_thread = None

    @mock.patch.object(ProductLibraryManager, "_http_post", return_value={"ok": True, "added": 5, "updated": 2})
    def test_sync_trigger_success(self, m_post):
        result = self.mgr.sync()
        self.assertTrue(result.get("ok"))
        m_post.assert_called_once_with("/sync", timeout=10)

    @mock.patch.object(ProductLibraryManager, "_http_post", return_value=None)
    def test_sync_trigger_failure(self, m_post):
        result = self.mgr.sync()
        self.assertIsNone(result)


class TestSyncStatus(unittest.TestCase):
    def setUp(self):
        self.mgr = ProductLibraryManager.__new__(ProductLibraryManager)
        self.mgr.machine_id = "test-mid"
        self.mgr.items = []
        self.mgr._cache_time = 0
        self.mgr._load_thread = None

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"running": False, "added": 3, "updated": 1})
    def test_sync_status_done(self, m_get):
        st = self.mgr.sync_status()
        self.assertFalse(st["running"])
        self.assertEqual(st["added"], 3)
        m_get.assert_called_once_with("/sync/status", timeout=10)

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"running": True, "fetched": 10, "total": 50})
    def test_sync_status_running(self, m_get):
        st = self.mgr.sync_status()
        self.assertTrue(st["running"])
        self.assertEqual(st["fetched"], 10)

    @mock.patch.object(ProductLibraryManager, "_http_get", return_value=None)
    def test_sync_status_unreachable(self, m_get):
        st = self.mgr.sync_status()
        self.assertIsNone(st)


class TestMine(unittest.TestCase):
    def setUp(self):
        self.mgr = ProductLibraryManager.__new__(ProductLibraryManager)
        self.mgr.machine_id = "test-mid"
        self.mgr.items = []
        self.mgr._cache_time = 0
        self.mgr._load_thread = None

    @mock.patch.object(ProductLibraryManager, "_http_post", return_value={"ok": True})
    def test_mine_single_item(self, m_post):
        result = self.mgr.mine(item_ids=["item-1"], model="deepseek-v4")
        self.assertTrue(result.get("ok"))
        body = m_post.call_args.kwargs["json_data"]
        self.assertEqual(body["item_ids"], ["item-1"])
        self.assertEqual(body["model"], "deepseek-v4")

    @mock.patch.object(ProductLibraryManager, "_http_post", return_value={"ok": True})
    def test_mine_batch(self, m_post):
        result = self.mgr.mine(item_ids=[], model="deepseek-chat")
        self.assertTrue(result.get("ok"))
        body = m_post.call_args.kwargs["json_data"]
        self.assertEqual(body["item_ids"], [])

    @mock.patch.object(ProductLibraryManager, "_http_post", return_value=None)
    def test_mine_failure(self, m_post):
        result = self.mgr.mine(item_ids=["x"], model="m")
        self.assertIsNone(result)


class TestMineStatus(unittest.TestCase):
    def setUp(self):
        self.mgr = ProductLibraryManager.__new__(ProductLibraryManager)
        self.mgr.machine_id = "test-mid"
        self.mgr.items = []
        self.mgr._cache_time = 0
        self.mgr._load_thread = None

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"running": False, "done": 5, "total": 10})
    def test_mine_status_done(self, m_get):
        st = self.mgr.mine_status()
        self.assertFalse(st["running"])
        self.assertEqual(st["done"], 5)
        m_get.assert_called_once_with("/mine/status", timeout=10)

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"running": True, "done": 3, "total": 10})
    def test_mine_status_running(self, m_get):
        st = self.mgr.mine_status()
        self.assertTrue(st["running"])

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"running": False, "error": "LLM 超时"})
    def test_mine_status_error(self, m_get):
        st = self.mgr.mine_status()
        self.assertFalse(st["running"])
        self.assertEqual(st["error"], "LLM 超时")


class TestGetItem(unittest.TestCase):
    def setUp(self):
        self.mgr = ProductLibraryManager.__new__(ProductLibraryManager)
        self.mgr.machine_id = "test-mid"
        self.mgr.items = []
        self.mgr._cache_time = 0
        self.mgr._load_thread = None

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"ok": True, "item": {"id": "i1", "brand": "Logitech", "features": "2.4G"}})
    def test_get_item_from_server(self, m_get):
        item = self.mgr.get_item("i1")
        self.assertEqual(item["brand"], "Logitech")
        self.assertEqual(item["features"], "2.4G")
        m_get.assert_called_once_with("/items/i1", timeout=10)

    @mock.patch.object(ProductLibraryManager, "_http_get", return_value=None)
    def test_get_item_unreachable(self, m_get):
        item = self.mgr.get_item("missing")
        self.assertIsNone(item)

    @mock.patch.object(ProductLibraryManager, "_http_get",
                      return_value={"ok": True, "item": {}})
    def test_get_item_empty(self, m_get):
        item = self.mgr.get_item("empty")
        self.assertIsNone(item)


if __name__ == "__main__":
    unittest.main()
