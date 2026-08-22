"""客户端任务下发闭环：领取/执行/上报（mock）。"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import client_task_worker as ctw  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = str(data)

    def json(self):
        return self._data


class TestPickup(unittest.TestCase):
    @mock.patch.object(ctw, "http_get", return_value=_Resp(200, {"tasks": [{"task_id": "t1", "capability": "browser_download", "params": {"url": "https://v.douyin.com/abc"}}]}))
    def test_pickup_ok(self, m_get):
        tasks = ctw.pickup_tasks("m1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_id"], "t1")
        self.assertIn("/tasks/assigned/m1", m_get.call_args.args[0])

    @mock.patch.object(ctw, "http_get", return_value=_Resp(200, {"tasks": []}))
    def test_pickup_empty(self, m_get):
        self.assertEqual(ctw.pickup_tasks("m1"), [])

    @mock.patch.object(ctw, "http_get", side_effect=requests.exceptions.RequestException("down"))
    def test_pickup_error(self, m_get):
        self.assertEqual(ctw.pickup_tasks("m1"), [])

    @mock.patch.object(ctw, "_machine_id", return_value="")
    def test_pickup_no_machine(self, m_mid):
        self.assertEqual(ctw.pickup_tasks(), [])


class TestReport(unittest.TestCase):
    def test_report_with_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x")
            tmp = f.name
        try:
            with mock.patch.object(ctw, "http_post", return_value=_Resp(200)) as m_post:
                ok = ctw.report_task("t1", "m1", status="ok", file_path=tmp)
            self.assertTrue(ok)
            args, kwargs = m_post.call_args
            self.assertIn("/tasks/t1/report", args[0])
            self.assertEqual(kwargs["data"]["machine_id"], "m1")
            self.assertIn("file", kwargs["files"])
        finally:
            os.unlink(tmp)

    def test_report_failed(self):
        with mock.patch.object(ctw, "http_post", return_value=_Resp(200)) as m_post:
            ok = ctw.report_task("t1", "m1", status="failed", error="超时")
        self.assertTrue(ok)
        self.assertEqual(m_post.call_args.kwargs["data"]["status"], "failed")
        self.assertEqual(m_post.call_args.kwargs["data"]["error"], "超时")

    @mock.patch.object(ctw, "http_post", return_value=_Resp(500))
    def test_report_http_error(self, m_post):
        self.assertFalse(ctw.report_task("t1", "m1", status="failed", error="x"))


class TestExecute(unittest.TestCase):
    def test_unsupported_capability(self):
        res = ctw.execute_task({"task_id": "t9", "capability": "client_ffmpeg", "params": {}})
        self.assertFalse(res["ok"])
        self.assertIn("未实现", res["error"])

    @mock.patch.object(ctw, "_wait_download_file", return_value="/tmp/new.mp4")
    @mock.patch("utils.viral_clone_client.open_in_asset_browser",
                return_value=(True, "已打开", "D:\\media\\客户端任务"))
    def test_download_flow_ok(self, m_open, m_wait):
        task = {"task_id": "t2", "capability": "browser_download",
                "params": {"url": "https://v.douyin.com/abc"}}
        res = ctw.execute_task(task)
        self.assertTrue(res["ok"])
        self.assertEqual(res["file_path"], "/tmp/new.mp4")
        m_open.assert_called_once()

    @mock.patch("utils.viral_clone_client.open_in_asset_browser",
                return_value=(False, "素材浏览器不可用", ""))
    def test_download_open_fail(self, m_open):
        task = {"task_id": "t3", "capability": "browser_download",
                "params": {"url": "https://v.douyin.com/abc"}}
        res = ctw.execute_task(task)
        self.assertFalse(res["ok"])
        self.assertIn("素材浏览器不可用", res["error"])

    @mock.patch.object(ctw, "_wait_download_file", return_value=None)
    @mock.patch("utils.viral_clone_client.open_in_asset_browser",
                return_value=(True, "已打开", "D:\\media\\客户端任务"))
    def test_download_timeout(self, m_open, m_wait):
        task = {"task_id": "t4", "capability": "browser_download",
                "params": {"url": "https://v.douyin.com/abc"}}
        res = ctw.execute_task(task, download_max_wait=1)
        self.assertFalse(res["ok"])
        self.assertIn("超时", res["error"])


if __name__ == "__main__":
    unittest.main()
