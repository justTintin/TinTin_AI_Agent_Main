"""core.douyin_parser：抖音接口 JSON 解析。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core.douyin_parser import parse_video_detail_json  # noqa: E402


def _sample_detail(desc="测试视频标题"):
    return {
        "aweme_detail": {
            "desc": desc,
            "video": {
                "bit_rate": [
                    {"bit_rate": 2000000, "play_addr": {"url_list": ["http://cdn.example.com/hd.mp4"]}},
                    {"bit_rate": 1000000, "play_addr": {"url_list": ["http://cdn.example.com/sd.mp4"]}},
                ],
                "cover": {"url_list": ["http://cdn.example.com/cover.jpg"]},
            },
            "statistics": {"digg_count": 100, "collect_count": 20, "comment_count": 5},
            "create_time": 1700000000,
        }
    }


class TestDouyinParser(unittest.TestCase):
    def test_parse_valid(self):
        r = parse_video_detail_json(123456, _sample_detail())
        self.assertIsNotNone(r)
        self.assertEqual(r["itemId"], "123456")
        self.assertEqual(r["platform"], "douyin")
        self.assertEqual(r["title"], "测试视频标题")
        # http -> https 升级，且取最高码率
        self.assertEqual(r["originVideo"], "https://cdn.example.com/hd.mp4")
        self.assertEqual(r["likes"], 100)

    def test_title_cleans_newlines(self):
        r = parse_video_detail_json(1, _sample_detail(desc="a\nb\tc\\d"))
        self.assertNotIn("\n", r["title"])
        self.assertNotIn("\t", r["title"])

    def test_no_video_url_returns_entry_without_origin(self):
        j = _sample_detail()
        j["aweme_detail"]["video"] = {"cover": {}}
        r = parse_video_detail_json(2, j)
        self.assertIsNone(r["originVideo"])

    def test_invalid_json_returns_false(self):
        self.assertFalse(parse_video_detail_json(3, {}))
        self.assertFalse(parse_video_detail_json(4, {"aweme_detail": None}))


if __name__ == "__main__":
    unittest.main()
