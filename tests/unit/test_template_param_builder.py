"""tests/unit/test_template_param_builder.py — 模板参数构造器测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from utils.template_param_builder import (
    build_mg_request,
    collect_script_params,
    extract_script_summary,
)


class TestCollectScriptParams(unittest.TestCase):
    """_collect_script_params 下沉测试。"""

    def test_basic(self):
        script = {
            "name": "test_script",
            "shots": [
                {"index": 0, "shot_type": "intro", "duration": 3, "visual": "img.jpg", "narration": "hello"},
                {"index": 1, "shot_type": "body", "duration": 5, "visual": "", "audio": "world"},
            ],
        }
        params = collect_script_params(
            script=script,
            count=3,
            ratio="9:16",
            platform="douyin",
            autocheck=True,
        )
        self.assertEqual(len(params["shots"]), 2)
        self.assertEqual(params["shots"][0]["audio"], "hello")
        self.assertEqual(params["shots"][1]["audio"], "world")
        self.assertEqual(params["count"], 3)
        self.assertEqual(params["ratio"], "9:16")
        self.assertEqual(params["predict_platform"], "douyin")
        self.assertTrue(params["autocheck"])

    def test_empty_script(self):
        params = collect_script_params(
            script={},
            count=1,
            ratio="16:9",
            platform="",
            autocheck=False,
        )
        self.assertEqual(params["shots"], [])
        self.assertEqual(params["voice_settings"], {"speaker": "default"})

    def test_narration_to_audio_mapping(self):
        script = {
            "shots": [
                {"index": 0, "narration": "test narration"},
            ],
        }
        params = collect_script_params(
            script=script, count=1, ratio="1:1", platform="", autocheck=False
        )
        self.assertEqual(params["shots"][0]["audio"], "test narration")

    def test_audio_takes_priority_over_narration(self):
        script = {
            "shots": [
                {"index": 0, "audio": "audio text", "narration": "narration text"},
            ],
        }
        params = collect_script_params(
            script=script, count=1, ratio="1:1", platform="", autocheck=False
        )
        self.assertEqual(params["shots"][0]["audio"], "audio text")


class TestExtractScriptSummary(unittest.TestCase):
    """_extract_script_summary 下沉测试。"""

    def test_basic(self):
        template = {
            "storyboard": {
                "shots": [
                    {
                        "duration": 3,
                        "visual": "img.jpg",
                        "audio": "hello world",
                    },
                ],
            },
        }
        summary = extract_script_summary(template)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["shot_count"], 1)
        self.assertAlmostEqual(summary["total_duration"], 3.0)
        self.assertTrue(len(summary["materials"]) > 0)

    def test_no_script(self):
        template = {"no_script_field": True}
        summary = extract_script_summary(template)
        self.assertIsNone(summary)

    def test_shots_top_level(self):
        template = {
            "shots": [
                {"duration": 2, "visual": "a.jpg", "narration": "text"},
            ],
        }
        summary = extract_script_summary(template)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["shot_count"], 1)

    def test_material_name_fn(self):
        template = {
            "shots": [
                {"duration": 1, "visual": "path/to/image.jpg"},
            ],
        }
        summary = extract_script_summary(template, material_name_fn=lambda x: os.path.basename(x))
        self.assertEqual(summary["materials"][0], "image.jpg")

    def test_sfx_extraction(self):
        template = {
            "shots": [
                {"duration": 1, "sfx": "sfx_pop.wav"},
            ],
        }
        summary = extract_script_summary(template, material_name_fn=lambda x: str(x))
        self.assertEqual(len(summary["sfx_files"]), 1)


class TestBuildMGRequest(unittest.TestCase):
    """_build_request 下沉测试。"""

    def test_basic(self):
        template = {"id": "mg_scene", "is_builtin": True}
        values = {"title": "Hello", "subtitle": "World"}
        common = {"ratio": "9:16", "scale": 1.0, "color": "#FFF", "bg": "#000", "font_size": 24, "duration": 3.0}
        req = build_mg_request(
            template=template,
            values=values,
            common=common,
        )
        self.assertEqual(req["template"], "mg_scene")
        self.assertEqual(req["title"], "Hello")
        self.assertEqual(req["subtitle"], "World")
        self.assertEqual(req["ratio"], "9:16")

    def test_with_scenes(self):
        template = {"id": "mg_scene", "is_builtin": True}
        values = {}
        common = {"ratio": "9:16", "scale": 1.0, "color": "#FFF", "bg": "#000", "font_size": 24, "duration": 3.0}
        scenes = [{"text": "Scene 1", "duration": 2}]
        req = build_mg_request(
            template=template,
            values=values,
            common=common,
            scenes=scenes,
        )
        self.assertIn("scenes", req)
        self.assertEqual(len(req["scenes"]), 1)

    def test_values_override_common(self):
        template = {"id": "mg_test", "is_builtin": True}
        values = {"ratio": "16:9"}
        common = {"ratio": "9:16", "scale": 1.0, "color": "#FFF", "bg": "#000", "font_size": 24, "duration": 3.0}
        req = build_mg_request(
            template=template,
            values=values,
            common=common,
        )
        self.assertEqual(req["ratio"], "16:9")

    def test_custom_backend(self):
        template = {"id": "custom_template", "backend": "mg_custom", "is_builtin": False}
        common = {"ratio": "9:16", "scale": 1.0, "color": "#FFF", "bg": "#000", "font_size": 24, "duration": 3.0}
        req = build_mg_request(
            template=template,
            values={},
            common=common,
        )
        self.assertEqual(req["template"], "mg_custom")

    def test_none_and_empty_values_skipped(self):
        template = {"id": "mg_test", "is_builtin": True}
        values = {"title": "", "subtitle": None, "text": "content"}
        common = {"ratio": "9:16", "scale": 1.0, "color": "#FFF", "bg": "#000", "font_size": 24, "duration": 3.0}
        req = build_mg_request(
            template=template,
            values=values,
            common=common,
        )
        # 空字符串和 None 不应覆盖 common 中的值
        self.assertEqual(req.get("template"), "mg_test")
        self.assertEqual(req.get("text"), "content")


if __name__ == "__main__":
    import os
    unittest.main()
