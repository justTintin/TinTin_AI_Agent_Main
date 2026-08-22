"""shot_analysis_cache：镜头分析缓存（内容指纹 + 持久化）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils.shot_analysis_cache import ShotAnalysisCache, _clip_key  # noqa: E402


class TestShotAnalysisCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sac_test_")
        self.clip = os.path.join(self.tmp, "clip_001.mp4")
        with open(self.clip, "wb") as f:
            f.write(b"0123456789" * 1000)
        self.cache = ShotAnalysisCache(self.tmp, "video_basename")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upsert_and_get(self):
        self.cache.upsert(self.clip, {"score": 8, "desc": "中景"})
        entry = self.cache.get(self.clip)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["score"], 8)
        self.assertIn("updated_at", entry)

    def test_persist_across_instances(self):
        self.cache.upsert(self.clip, {"score": 9})
        cache2 = ShotAnalysisCache(self.tmp, "video_basename")
        self.assertEqual(cache2.get(self.clip)["score"], 9)

    def test_content_addressable_key(self):
        # 内容相同、文件名不同 → 命中同一 key
        clip2 = os.path.join(self.tmp, "clip_002.mp4")
        with open(clip2, "wb") as f:
            f.write(b"0123456789" * 1000)
        self.assertEqual(_clip_key(self.clip), _clip_key(clip2))
        self.cache.upsert(self.clip, {"score": 7})
        self.assertEqual(self.cache.get(clip2)["score"], 7)

    def test_missing_file_key_falls_back_to_path(self):
        missing = os.path.join(self.tmp, "nope.mp4")
        self.assertEqual(_clip_key(missing), missing)

    def test_load_corrupt_file(self):
        with open(os.path.join(self.tmp, "video_basename_shots.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        cache = ShotAnalysisCache(self.tmp, "video_basename")
        self.assertEqual(cache._items, {})


if __name__ == "__main__":
    unittest.main()
