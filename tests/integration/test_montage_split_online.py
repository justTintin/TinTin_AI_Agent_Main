"""智能混剪镜头分割在线冒烟：POST /montage/split 上传样本视频，校验返回结构（--online）。"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

ONLINE = os.environ.get("RUN_ONLINE") == "1"


@unittest.skipUnless(ONLINE, "需要 --online（联网访问服务端 /montage/split）")
class TestMontageSplitOnline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="montage_split_")
        cls.mp4 = os.path.join(cls.tmp, "sample.mp4")
        from utils.platform_utils import find_ffmpeg
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise unittest.SkipTest("未找到 ffmpeg")
        r = subprocess.run(
            [ffmpeg, "-y", "-i", testutil.SAMPLE_VIDEO,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "2", cls.mp4],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0 or not os.path.isfile(cls.mp4):
            raise unittest.SkipTest("样本转 mp4 失败: " + r.stderr[-300:])

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_montage_split_returns_shots(self):
        import requests
        base = testutil.server_base_url()
        self.assertTrue(base, "未配置 compute_server_url")
        with open(self.mp4, "rb") as f:
            r = requests.post(
                base + "/montage/split",
                files={"file": ("sample.mp4", f, "video/mp4")},
                data={"threshold": "27", "min_scene_len": "0.5", "dedup": "true"},
                timeout=180,
            )
        self.assertEqual(r.status_code, 200, r.text[:500])
        data = r.json()
        self.assertIn("task_id", data)
        self.assertIn("shots", data)
        self.assertIsInstance(data["shots"], list)
        self.assertGreaterEqual(data.get("total_shots", 0), 0)


if __name__ == "__main__":
    unittest.main()
