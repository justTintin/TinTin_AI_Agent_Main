"""Ollama 图片识别集成测试（需要 --online 且能访问局域网 Ollama）。"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

SKILL_SCRIPT = r"C:\Users\TinTin\.codex\skills\image-recognition\scripts\analyze_image.py"
ONLINE = os.environ.get("RUN_ONLINE") == "1"


@unittest.skipUnless(ONLINE, "需要 --online（联网访问局域网 Ollama）")
class TestOllamaImageRecognition(unittest.TestCase):
    def test_analyze_sample_image(self):
        if not os.path.isfile(SKILL_SCRIPT):
            self.skipTest("未找到 image-recognition 技能脚本")
        if not os.path.isfile(testutil.SAMPLE_IMAGE):
            self.skipTest("缺少样本图片")
        r = subprocess.run(
            [sys.executable, SKILL_SCRIPT, testutil.SAMPLE_IMAGE,
             "--prompt", "请用中文简要描述这张图片。"],
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue(len(r.stdout.strip()) > 0, "模型未返回内容")


if __name__ == "__main__":
    unittest.main()
