"""仿爆款客户端（viral_clone_client）：flow/analyze/plan/素材浏览器下载引导/占位。"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import viral_clone_client as vcc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = str(data)

    def json(self):
        return self._data


STRUCTURE = {"meta": {"duration": 15.0, "shot_count": 8},
             "shots": [{"index": 1, "duration": 1.2, "shot_type": "特写"}]}
SCRIPT = {"goal": "仿制爆款", "shots": [{"index": 1, "replace": "product"}]}


class TestViralCloneAnalyze(unittest.TestCase):
    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, STRUCTURE))
    def test_analyze_material_id(self, m_post):
        out = vcc.analyze(material_id=42)
        self.assertEqual(out, STRUCTURE)
        body = m_post.call_args.kwargs["json"]
        self.assertEqual(body, {"material_id": 42})

    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, STRUCTURE))
    def test_analyze_video_path(self, m_post):
        out = vcc.analyze(video_path="output/abc.mp4")
        self.assertEqual(out, STRUCTURE)
        self.assertEqual(m_post.call_args.kwargs["json"], {"video_path": "output/abc.mp4"})

    def test_analyze_no_source(self):
        self.assertIsNone(vcc.analyze())

    @mock.patch.object(vcc, "http_post", return_value=_Resp(500, {"detail": "boom"}))
    def test_analyze_http_error(self, m_post):
        self.assertIsNone(vcc.analyze(material_id=1))

    @mock.patch.object(vcc, "http_post", side_effect=requests.exceptions.RequestException("timeout"))
    def test_analyze_exception(self, m_post):
        self.assertIsNone(vcc.analyze(material_id=1))


class TestViralClonePlan(unittest.TestCase):
    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, SCRIPT))
    def test_plan(self, m_post):
        out = vcc.plan(STRUCTURE, "罗技 G502 无线鼠标，60克轻量")
        self.assertEqual(out, SCRIPT)
        body = m_post.call_args.kwargs["json"]
        self.assertEqual(body["structure"], STRUCTURE)
        self.assertIn("罗技", body["product_info"])

    def test_plan_bad_structure(self):
        self.assertIsNone(vcc.plan("not-a-dict", "产品"))


class TestViralCloneFlow(unittest.TestCase):
    @mock.patch.object(vcc, "http_post",
                       return_value=_Resp(200, {"ok": True, "structure": STRUCTURE, "script": SCRIPT}))
    def test_flow_ok(self, m_post):
        out = vcc.flow(material_id=42, product_info="罗技鼠标")
        self.assertTrue(out["ok"])
        self.assertEqual(out["structure"], STRUCTURE)
        self.assertEqual(out["script"], SCRIPT)
        body = m_post.call_args.kwargs["json"]
        self.assertEqual(body["material_id"], 42)
        self.assertNotIn("url", body)  # 客户端不传 url，避免服务端下载

    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, {"need_login": True}))
    def test_flow_need_login(self, m_post):
        out = vcc.flow(material_id=42)
        self.assertFalse(out["ok"])
        self.assertTrue(out["need_login"])
        self.assertIn("登录", out["error"])

    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, {"captcha": True}))
    def test_flow_captcha(self, m_post):
        out = vcc.flow(material_id=42)
        self.assertFalse(out["ok"])
        self.assertTrue(out["captcha"])
        self.assertIn("滑块", out["error"])

    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, {"ok": False, "error": "boom"}))
    def test_flow_not_ok(self, m_post):
        out = vcc.flow(material_id=42)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "boom")

    @mock.patch.object(vcc, "http_post", return_value=_Resp(200, {"ok": True}))
    def test_flow_no_args(self, m_post):
        out = vcc.flow()
        self.assertFalse(out["ok"])
        m_post.assert_not_called()


class TestViralCloneSource(unittest.TestCase):
    def test_normalize_material_id_int(self):
        r = vcc.normalize_source(42)
        self.assertTrue(r["ok"])
        self.assertEqual(r["analyze_kwargs"], {"material_id": 42})

    def test_normalize_material_id_str(self):
        r = vcc.normalize_source("123")
        self.assertTrue(r["ok"])
        self.assertEqual(r["analyze_kwargs"], {"material_id": 123})

    def test_normalize_server_path(self):
        r = vcc.normalize_source("output/clone/abc.mp4")
        self.assertTrue(r["ok"])
        self.assertEqual(r["analyze_kwargs"], {"video_path": "output/clone/abc.mp4"})

    def test_normalize_link_needs_client_download(self):
        """链接不再走服务端下载：必须由客户端素材浏览器下载后填素材 ID。"""
        r = vcc.normalize_source("https://www.douyin.com/video/123")
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("need_download"))
        self.assertIn("素材浏览器", r["note"])

    def test_normalize_local_file_rejected(self):
        r = vcc.normalize_source("D:\videos\baokuan.mp4")
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("need_download"))

    def test_normalize_empty(self):
        r = vcc.normalize_source("")
        self.assertFalse(r["ok"])


class TestViralCloneAssetBrowser(unittest.TestCase):
    @mock.patch("utils.asset_browser_client.launch_for_topic",
                return_value=(True, "已打开", r"D:\media\爆款仿制"))
    def test_open_in_asset_browser_with_url(self, m_launch):
        ok, msg, dl = vcc.open_in_asset_browser("https://v.douyin.com/abc", topic="爆款仿制")
        self.assertTrue(ok)
        m_launch.assert_called_once()
        args = m_launch.call_args
        self.assertEqual(args.args[0], "爆款仿制")
        self.assertEqual(args.kwargs.get("keyword"), "https://v.douyin.com/abc")
        self.assertEqual(args.kwargs.get("platform"), "douyin")

    @mock.patch("utils.asset_browser_client.launch",
                return_value=(True, "已打开素材浏览器"))
    def test_open_in_asset_browser_no_url(self, m_launch):
        ok, msg, dl = vcc.open_in_asset_browser("")
        self.assertTrue(ok)
        m_launch.assert_called_once()


class TestViralCloneRun(unittest.TestCase):
    @mock.patch.object(vcc, "flow",
                       return_value={"ok": True, "structure": STRUCTURE, "script": SCRIPT})
    def test_run_clone_flow_ok(self, m_flow):
        out = vcc.run_clone(42, "罗技鼠标")
        self.assertTrue(out["ok"])
        self.assertEqual(out["structure"], STRUCTURE)
        self.assertEqual(out["script"], SCRIPT)
        m_flow.assert_called_once_with(timeout=900, product_info="罗技鼠标", material_id=42)

    @mock.patch.object(vcc, "flow",
                       return_value={"ok": False, "error": "flow 不可用"})
    @mock.patch.object(vcc, "plan", return_value=SCRIPT)
    @mock.patch.object(vcc, "analyze", return_value=STRUCTURE)
    def test_run_clone_fallback_analyze_plan(self, m_analyze, m_plan, m_flow):
        out = vcc.run_clone(42, "罗技鼠标")
        self.assertTrue(out["ok"])
        m_analyze.assert_called_once_with(timeout=900, material_id=42)
        m_plan.assert_called_once()

    @mock.patch.object(vcc, "flow",
                       return_value={"ok": False, "need_login": True, "error": "抖音未登录"})
    def test_run_clone_need_login(self, m_flow):
        out = vcc.run_clone(42, "罗技鼠标")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("need_login"))

    def test_run_clone_link_requires_download(self):
        out = vcc.run_clone("https://v.douyin.com/abc", "罗技鼠标")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("need_download"))
        self.assertIn("素材浏览器", out["error"])


class TestViralClonePlaceholders(unittest.TestCase):
    def test_generate_placeholder(self):
        r = vcc.generate(SCRIPT)
        self.assertFalse(r["ok"])
        self.assertIn("E-3.0", r["reason"])

    def test_montage_placeholder(self):
        r = vcc.montage(["a.mp4"])
        self.assertFalse(r["ok"])
        self.assertIn("E-3.0", r["reason"])

    def test_review_placeholder(self):
        r = vcc.review("output/clone.mp4")
        self.assertFalse(r["ok"])
        self.assertIn("E-3.0", r["reason"])


if __name__ == "__main__":
    unittest.main()
