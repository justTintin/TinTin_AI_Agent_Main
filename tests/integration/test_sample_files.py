# -*- coding: utf-8 -*-
"""样本数据有效性（离线）：样本存在、格式可解析、生成器幂等。"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil


class TestSampleFiles(unittest.TestCase):
    def test_samples_exist(self):
        for p in (testutil.SAMPLE_VIDEO, testutil.SAMPLE_IMAGE, testutil.SAMPLE_AUDIO):
            self.assertTrue(os.path.isfile(p), f"样本缺失: {p}")
            self.assertGreater(os.path.getsize(p), 0)

    def test_video_valid_via_ffprobe(self):
        ffprobe = testutil.find_tool("ffprobe")
        if not ffprobe:
            self.skipTest("未找到 ffprobe")
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_name,width,height,nb_frames",
             "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1",
             testutil.SAMPLE_VIDEO],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("codec_name=rawvideo", out)
        self.assertIn("width=320", out)
        self.assertIn("height=240", out)
        self.assertIn("nb_frames=30", out)
        self.assertIn("duration=2.000000", out)

    def test_image_is_png(self):
        with open(testutil.SAMPLE_IMAGE, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_audio_is_wav(self):
        import wave
        with wave.open(testutil.SAMPLE_AUDIO) as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnframes(), 16000)

    def test_generator_idempotent(self):
        gen = os.path.join(testutil.TESTS_DIR, "samples", "generate_samples.py")
        r = subprocess.run([sys.executable, gen], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()