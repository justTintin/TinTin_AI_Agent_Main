# -*- coding: utf-8 -*-
"""video_compiler：一键成片管线测试（纯逻辑 + 离线 ffmpeg 冒烟）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from utils.video_compiler import _tc, _split_text, _write_srt, collect_images, compile_video, _probe_duration


class TestVideoCompilerPure(unittest.TestCase):
    def test_tc_format(self):
        self.assertEqual(_tc(0), "00:00:00,000")
        self.assertEqual(_tc(3661.5), "01:01:01,500")

    def test_split_text_balanced(self):
        parts = _split_text("句子一。句子二！句子三？", 3)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(parts))

    def test_split_text_empty_and_pad(self):
        self.assertEqual(_split_text("", 2), ["", ""])
        short = _split_text("只有一句", 3)
        self.assertEqual(len(short), 3)
        self.assertEqual(short[1:], ["", ""])

    def test_write_srt(self):
        with tempfile.TemporaryDirectory(prefix="srt_") as tmp:
            p = os.path.join(tmp, "a.srt")
            _write_srt(p, "你好。世界。", 2, 1.0)
            content = open(p, encoding="utf-8").read()
            self.assertIn("00:00:00,000 --> 00:00:01,000", content)
            self.assertIn("你好", content)

    def test_collect_images(self):
        with tempfile.TemporaryDirectory(prefix="img_") as tmp:
            for name in ("a.png", "b.jpg", "c.txt"):
                open(os.path.join(tmp, name), "w").close()
            os.makedirs(os.path.join(tmp, "sub"))
            open(os.path.join(tmp, "sub", "d.jpeg"), "w").close()
            self.assertEqual(len(collect_images(tmp)), 3)


@unittest.skipUnless(os.path.isfile(testutil.SAMPLE_IMAGE), "缺少样本图片")
class TestCompileVideoSmoke(unittest.TestCase):
    """端到端冒烟：样本图片 + 内置 ffmpeg → 生成短视频（含字幕环节）。"""

    def test_compile_video_offline(self):
        from utils.platform_utils import find_ffmpeg
        ffmpeg = find_ffmpeg()
        self.assertTrue(ffmpeg, "未找到 ffmpeg（应在 studio/bin/win）")
        with tempfile.TemporaryDirectory(prefix="vc_smoke_") as tmp:
            images = [testutil.SAMPLE_IMAGE] * 3
            out = os.path.join(tmp, "out.mp4")
            result = compile_video(
                images, out, ratio="9:16", per_dur=0.5, fps=15,
                subtitle_text="这是一键成片测试。验证字幕与合成。",
            )
            self.assertEqual(result, out)
            self.assertTrue(os.path.isfile(out), "未生成输出视频")
            self.assertGreater(os.path.getsize(out), 0)
            dur = _probe_duration(out)
            if dur is not None:
                self.assertGreater(dur, 0)
            else:
                self.skipTest("ffprobe 不可用，跳过时长校验")


if __name__ == "__main__":
    unittest.main()