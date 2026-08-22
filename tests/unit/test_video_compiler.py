"""tests/unit/test_video_compiler.py — video_compiler 业务逻辑测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from utils.video_compiler import scan_storyboard_scripts, split_groups


class TestSplitGroups(unittest.TestCase):
    """split_groups 分组算法测试。"""

    def test_equal_split(self):
        images = ["a", "b", "c", "d", "e", "f"]
        groups = split_groups(images, 3)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups, [["a", "b"], ["c", "d"], ["e", "f"]])

    def test_unequal_split(self):
        images = ["a", "b", "c", "d", "e"]
        groups = split_groups(images, 2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups, [["a", "b", "c"], ["d", "e"]])

    def test_more_groups_than_images(self):
        images = ["a", "b"]
        groups = split_groups(images, 5)
        self.assertEqual(len(groups), 5)
        for g in groups:
            self.assertEqual(len(g), 1)

    def test_empty_images(self):
        groups = split_groups([], 3)
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g, [])

    def test_single_group(self):
        images = ["a", "b", "c"]
        groups = split_groups(images, 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups, [["a", "b", "c"]])

    def test_single_image_equal_split(self):
        images = ["a"]
        groups = split_groups(images, 1)
        self.assertEqual(groups, [["a"]])


class TestScanStoryboardScripts(unittest.TestCase):
    """scan_storyboard_scripts 分镜扫描测试。"""

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_no_storyboard_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = os.path.join(tmp, "topic1")
            os.makedirs(topic_dir)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_valid_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            script = {
                "topic": "测试主题",
                "ratio": "9:16",
                "total_duration": 30,
                "shot_count": 3,
                "shots": [{"text": "镜头1"}, {"text": "镜头2"}, {"text": "镜头3"}],
                "saved_at": 1234567890,
            }
            fp = os.path.join(sb_dir, "test_script.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(len(results), 1)
            r = results[0]
            self.assertEqual(r["name"], "test_script")
            self.assertEqual(r["topic"], "测试主题")
            self.assertEqual(r["ratio"], "9:16")
            self.assertEqual(r["total_duration"], 30)
            self.assertEqual(r["shot_count"], 3)

    def test_invalid_json_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            fp = os.path.join(sb_dir, "bad.json")
            with open(fp, "w", encoding="utf-8") as f:
                f.write("not valid json{{{")
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_no_shots_key_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            script = {"topic": "测试", "ratio": "16:9"}
            fp = os.path.join(sb_dir, "no_shots.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(script, f)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_non_dict_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            fp = os.path.join(sb_dir, "list.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump([1, 2, 3], f)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_multiple_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            for topic in ["topic_a", "topic_b"]:
                sb_dir = os.path.join(tmp, topic, "storyboard")
                os.makedirs(sb_dir)
                fp = os.path.join(sb_dir, f"{topic}_script.json")
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump({"shots": [{"text": "shot1"}], "topic": topic}, f)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(len(results), 2)

    def test_non_json_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            txt_fp = os.path.join(sb_dir, "readme.txt")
            with open(txt_fp, "w") as f:
                f.write("not a json")
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(results, [])

    def test_default_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb_dir = os.path.join(tmp, "topic1", "storyboard")
            os.makedirs(sb_dir)
            script = {"shots": [{"text": "shot1"}]}
            fp = os.path.join(sb_dir, "minimal.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(script, f)
            results = scan_storyboard_scripts(tmp)
            self.assertEqual(len(results), 1)
            r = results[0]
            self.assertEqual(r["ratio"], "9:16")
            self.assertEqual(r["total_duration"], 0)
            self.assertEqual(r["topic"], "topic1")


if __name__ == "__main__":
    unittest.main()
