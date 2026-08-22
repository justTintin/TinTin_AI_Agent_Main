# -*- coding: utf-8 -*-
"""workflow_client（服务端统一工作流接口）单测：mock http_get/http_post/_get_server_url。"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import workflow_client as wfc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text or str(data or "")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class TestListWorkflows(unittest.TestCase):
    @mock.patch.object(wfc, "http_get", return_value=_Resp(200, {
        "workflows": [{"workflow_id": "comfy-dh-001", "backend": "comfyui", "type": "数字人"}],
        "total": 1, "scope": "client"}))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_success(self, m_url, m_get):
        data = wfc.list_workflows()
        self.assertEqual(m_get.call_count, 1)
        self.assertEqual(m_get.call_args[1]["params"], {"scope": "client"})
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["workflows"][0]["workflow_id"], "comfy-dh-001")

    @mock.patch.object(wfc, "_get_server_url", return_value="")
    def test_no_server(self, m_url):
        self.assertEqual(wfc.list_workflows(), {})

    @mock.patch.object(wfc, "http_get", side_effect=requests.exceptions.RequestException("boom"))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_http_error(self, m_url, m_get):
        self.assertEqual(wfc.list_workflows(), {})


class TestRunWorkflow(unittest.TestCase):
    @mock.patch.object(wfc, "http_post", return_value=_Resp(200, {
        "ok": True, "task_id": "t-1", "backend": "runninghub"}))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_no_files_success(self, m_url, m_post):
        resp = wfc.run_workflow("wf1")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["task_id"], "t-1")
        # 无文件路径 → files 为空 dict，data 里带 instance_type 默认值
        self.assertEqual(m_post.call_args[1]["files"], {})
        self.assertEqual(m_post.call_args[1]["data"]["instance_type"], "default")

    def test_files_attached(self):
        import os as _os
        from config.paths import TMP_DIR
        img = _os.path.join(TMP_DIR, "test_wf_img.png")
        aud = _os.path.join(TMP_DIR, "test_wf_aud.mp3")
        for p in (img, aud):
            with open(p, "wb") as f:
                f.write(b"x")
        try:
            with mock.patch.object(wfc, "http_post", return_value=_Resp(200, {"ok": True, "task_id": "t-2"})) as m_post, \
                 mock.patch.object(wfc, "_get_server_url", return_value="http://srv"):
                wfc.run_workflow("wf2", image_path=img, audio_path=aud, instance_type="plus")
                files = m_post.call_args[1]["files"]
                self.assertIn("image", files)
                self.assertIn("audio", files)
                self.assertEqual(files["image"][0], "test_wf_img.png")
                self.assertEqual(files["audio"][0], "test_wf_aud.mp3")
                self.assertEqual(m_post.call_args[1]["data"]["instance_type"], "plus")
        finally:
            for p in (img, aud):
                if _os.path.isfile(p):
                    _os.remove(p)

    @mock.patch.object(wfc, "_get_server_url", return_value="")
    def test_no_server(self, m_url):
        self.assertEqual(wfc.run_workflow("wf1", image_path="p.png"), {})

    @mock.patch.object(wfc, "http_post", side_effect=requests.exceptions.RequestException("boom"))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_http_error(self, m_url, m_post):
        self.assertEqual(wfc.run_workflow("wf1", image_path="p.png"), {})

    def test_files_values_dynamic(self):
        import os as _os
        from config.paths import TMP_DIR
        vid = _os.path.join(TMP_DIR, "test_wf_vid.mp4")
        img = _os.path.join(TMP_DIR, "test_wf_img2.png")
        for p in (vid, img):
            with open(p, "wb") as f:
                f.write(b"x")
        try:
            with mock.patch.object(wfc, "http_post", return_value=_Resp(200, {"ok": True, "task_id": "t-dyn"})) as m_post, \
                 mock.patch.object(wfc, "_get_server_url", return_value="http://srv"):
                wfc.run_workflow("wf9", files={"video": vid, "image": img},
                                 values={"text": "hello"}, instance_type="plus")
                files = m_post.call_args[1]["files"]
                self.assertIn("video", files)
                self.assertIn("image", files)
                self.assertEqual(files["video"][0], "test_wf_vid.mp4")
                data = m_post.call_args[1]["data"]
                self.assertEqual(data["text"], "hello")
                self.assertEqual(data["instance_type"], "plus")
        finally:
            for p in (vid, img):
                if _os.path.isfile(p):
                    _os.remove(p)


class TestNormalizeServerWorkflow(unittest.TestCase):
    def test_full_entry(self):
        item = wfc.normalize_server_workflow({
            "workflow_id": "2085292185062297602", "name": "数字人",
            "type": "数字人", "instance_type": "plus", "description": "云端",
            "client_api": "/workflows/2085292185062297602/run",
            "image_nodes": [["180", "image"]], "audio_nodes": [["6", "audio"]],
            "backend": "runninghub"})
        self.assertEqual(item["id"], "2085292185062297602")
        self.assertEqual(item["instanceType"], "plus")
        self.assertEqual(item["image_nodes"], [["180", "image"]])
        self.assertEqual(item["backend"], "runninghub")

    def test_missing_workflow_id(self):
        self.assertIsNone(wfc.normalize_server_workflow({"name": "x", "type": "数字人"}))

    def test_non_dict(self):
        self.assertIsNone(wfc.normalize_server_workflow("str"))
        self.assertIsNone(wfc.normalize_server_workflow(None))

    def test_default_type_and_instance(self):
        item = wfc.normalize_server_workflow({"workflow_id": "abc"})
        self.assertEqual(item["name"], "abc")
        self.assertEqual(item["type"], "其他")
        self.assertEqual(item["instanceType"], "default")
        self.assertEqual(item["inputs"], [])
        self.assertEqual(item["io"], {})

    def test_inputs_passthrough(self):
        inputs = [{"key": "video", "kind": "video", "label": "video", "required": True, "options": []}]
        item = wfc.normalize_server_workflow({
            "workflow_id": "wf9", "inputs": inputs, "io": {"inputs": ["video"], "outputs": ["video"]}})
        self.assertEqual(item["inputs"], inputs)
        self.assertEqual(item["io"]["outputs"], ["video"])


class TestTaskStatus(unittest.TestCase):
    @mock.patch.object(wfc, "http_get", return_value=_Resp(200, {
        "code": 0, "data": {"taskId": "t-1", "status": "SUCCESS",
                            "results": [{"url": "https://x/mp4", "outputType": "mp4"}]}}))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_success(self, m_url, m_get):
        resp = wfc.task_status("t-1")
        self.assertEqual(resp["code"], 0)
        self.assertEqual(resp["data"]["status"], "SUCCESS")
        self.assertEqual(m_get.call_args[0][0], "http://srv/workflows/task/t-1")

    @mock.patch.object(wfc, "http_get", side_effect=requests.exceptions.RequestException("boom"))
    @mock.patch.object(wfc, "_get_server_url", return_value="http://srv")
    def test_http_error(self, m_url, m_get):
        self.assertEqual(wfc.task_status("t-1"), {})


if __name__ == "__main__":
    unittest.main()
