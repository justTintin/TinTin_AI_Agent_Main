"""comfyui_client 新增代理模式函数测试：list_workflows / get_workflow_json /
get_proxy_status / upload_image / run_workflow / get_history / download_image。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import comfyui_client as cc  # noqa: E402


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


class TestListWorkflows(unittest.TestCase):
    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"workflows": [{"id": "wf1", "name": "test"}]}))
    def test_success(self, m_get):
        workflows = cc.list_workflows("http://srv", timeout=10)
        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0]["id"], "wf1")

    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {}))
    def test_empty_workflows(self, m_get):
        workflows = cc.list_workflows("http://srv")
        self.assertEqual(workflows, [])

    @mock.patch.object(cc, "http_get", return_value=_Resp(500))
    def test_http_error(self, m_get):
        with self.assertRaises(RuntimeError):
            cc.list_workflows("http://srv")


class TestGetWorkflowJson(unittest.TestCase):
    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"nodes": [], "links": []}))
    def test_success(self, m_get):
        wf = cc.get_workflow_json("http://srv", "path/to/wf.json")
        self.assertEqual(wf, {"nodes": [], "links": []})
        self.assertEqual(m_get.call_args.kwargs["params"], {"path": "path/to/wf.json"})

    @mock.patch.object(cc, "http_get", return_value=_Resp(404))
    def test_not_found(self, m_get):
        with self.assertRaises(RuntimeError):
            cc.get_workflow_json("http://srv", "missing.json")


class TestGetProxyStatus(unittest.TestCase):
    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"online": True, "version": "0.4.2"}))
    def test_online(self, m_get):
        data = cc.get_proxy_status("http://srv", timeout=5)
        self.assertTrue(data["online"])
        self.assertEqual(data["version"], "0.4.2")

    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"online": False}))
    def test_offline(self, m_get):
        data = cc.get_proxy_status("http://srv")
        self.assertFalse(data["online"])

    @mock.patch.object(cc, "http_get", return_value=_Resp(503))
    def test_error(self, m_get):
        with self.assertRaises(RuntimeError):
            cc.get_proxy_status("http://srv")


class TestUploadImage(unittest.TestCase):
    @mock.patch.object(cc, "http_post", return_value=_Resp(200, {"name": "uploaded.png"}))
    @mock.patch("builtins.open", new_callable=mock.mock_open, read_data=b"img")
    def test_success(self, m_open, m_post):
        name = cc.upload_image("http://srv", "/tmp/img.png", timeout=60)
        self.assertEqual(name, "uploaded.png")
        m_open.assert_called_once_with("/tmp/img.png", "rb")
        self.assertEqual(m_post.call_args.kwargs["params"], {"overwrite": "true"})

    @mock.patch.object(cc, "http_post", return_value=_Resp(200, {}))
    @mock.patch("builtins.open", new_callable=mock.mock_open, read_data=b"img")
    def test_no_name_field(self, m_open, m_post):
        """服务端未返回 name → 回退用本地文件名。"""
        name = cc.upload_image("http://srv", "/tmp/myimg.png")
        self.assertEqual(name, "myimg.png")


class TestRunWorkflow(unittest.TestCase):
    @mock.patch.object(cc, "http_post", return_value=_Resp(200, {"prompt_id": "p-123"}))
    def test_success(self, m_post):
        pid = cc.run_workflow("http://srv", {"nodes": []})
        self.assertEqual(pid, "p-123")
        body = m_post.call_args.kwargs["json"]
        self.assertEqual(body["client_id"], "tintin-studio")
        self.assertIn("prompt", body)

    @mock.patch.object(cc, "http_post", return_value=_Resp(200, {"id": "alt-456"}))
    def test_fallback_id_field(self, m_post):
        """prompt_id 缺失时回退取 id。"""
        pid = cc.run_workflow("http://srv", {})
        self.assertEqual(pid, "alt-456")

    @mock.patch.object(cc, "http_post", return_value=_Resp(200, {}))
    def test_no_id(self, m_post):
        pid = cc.run_workflow("http://srv", {})
        self.assertEqual(pid, "")


class TestGetHistory(unittest.TestCase):
    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"p-1": {"status": {"status_str": "success"}}}))
    def test_with_prompt_id(self, m_get):
        hist = cc.get_history("http://srv", prompt_id="p-1")
        self.assertEqual(hist["status"]["status_str"], "success")

    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {"p-1": {}, "p-2": {}}))
    def test_without_prompt_id(self, m_get):
        hist = cc.get_history("http://srv")
        self.assertEqual(len(hist), 2)

    @mock.patch.object(cc, "http_get", return_value=_Resp(200, {}))
    def test_prompt_id_not_found(self, m_get):
        """prompt_id 在历史中不存在时返回 None。"""
        hist = cc.get_history("http://srv", prompt_id="missing")
        self.assertIsNone(hist)


class TestDownloadImage(unittest.TestCase):
    @mock.patch.object(cc, "http_get", return_value=_Resp(200, content=b"png_bytes"))
    def test_success(self, m_get):
        content = cc.download_image("http://srv", "result.png", "output", "sub")
        self.assertEqual(content, b"png_bytes")
        url = m_get.call_args.args[0]
        self.assertIn("filename=result.png", url)
        self.assertIn("type=output", url)
        self.assertIn("subfolder=sub", url)

    @mock.patch.object(cc, "http_get", return_value=_Resp(404))
    def test_not_found(self, m_get):
        with self.assertRaises(RuntimeError):
            cc.download_image("http://srv", "missing.png")


if __name__ == "__main__":
    unittest.main()
