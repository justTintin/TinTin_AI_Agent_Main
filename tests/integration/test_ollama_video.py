"""Ollama 视频分析集成测试（需要 --online 且能访问局域网 Ollama）。"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

SKILL_SCRIPT = r"C:\Users\TinTin\.codex\skills\ollama-video\scripts\analyze_video.py"
ONLINE = os.environ.get("RUN_ONLINE") == "1"


@unittest.skipUnless(ONLINE, "需要 --online（联网访问局域网 Ollama）")
class TestOllamaVideo(unittest.TestCase):
    def test_api_tags_has_model(self):
        import requests
        base = testutil.ollama_base_url()
        r = requests.get(base + "/api/tags", timeout=15)
        self.assertEqual(r.status_code, 200)
        names = [m.get("name") for m in r.json().get("models", [])]
        self.assertIn("qwen2.5vl:7b-16k", names)

    def test_analyze_sample_video(self):
        if not os.path.isfile(SKILL_SCRIPT):
            self.skipTest("未找到 ollama-video 技能脚本")
        r = subprocess.run(
            [sys.executable, SKILL_SCRIPT, testutil.SAMPLE_VIDEO, "--frames", "4",
             "--prompt", "请用中文简要描述这些连续帧的画面及随时间的变化。"],
            capture_output=True, text=True, timeout=600,
        )
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue(len(r.stdout.strip()) > 0, "模型未返回内容")


if __name__ == "__main__":
    unittest.main()
