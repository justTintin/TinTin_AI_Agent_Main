"""tests/unit/test_srt_utils.py — SRT 解析/生成工具测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from utils.srt_utils import SRTSegment, parse_srt, parse_srt_time, segments_to_srt


class TestParseSrtTime(unittest.TestCase):
    """SRT 时间戳 → 秒。"""

    def test_comma_separator(self):
        self.assertAlmostEqual(parse_srt_time("00:00:05,500"), 5.5)

    def test_dot_separator(self):
        self.assertAlmostEqual(parse_srt_time("00:00:05.500"), 5.5)

    def test_hours(self):
        self.assertAlmostEqual(parse_srt_time("01:30:00,000"), 5400.0)

    def test_milliseconds_only_two_digits(self):
        self.assertAlmostEqual(parse_srt_time("00:00:01,05"), 1.005)

    def test_invalid_returns_zero(self):
        self.assertEqual(parse_srt_time("invalid"), 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(parse_srt_time(""), 0.0)


class TestParseSrt(unittest.TestCase):
    """SRT 文本 → segments。"""

    SRT_SAMPLE = """1
00:00:01,000 --> 00:00:04,000
Hello world

2
00:00:05,000 --> 00:00:08,500
This is a test"""

    def test_parse_basic_srt(self):
        segments = parse_srt(self.SRT_SAMPLE)
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0]["start"], 1.0)
        self.assertAlmostEqual(segments[0]["end"], 4.0)
        self.assertEqual(segments[0]["text"], "Hello world")
        self.assertAlmostEqual(segments[1]["start"], 5.0)
        self.assertAlmostEqual(segments[1]["end"], 8.5)
        self.assertEqual(segments[1]["text"], "This is a test")

    def test_parse_empty(self):
        segments = parse_srt("")
        self.assertEqual(segments, [])

    def test_parse_no_timestamp(self):
        segments = parse_srt("just some text\nwithout timestamps")
        self.assertEqual(segments, [])

    def test_parse_with_dot_separator(self):
        srt = "1\n00:00:01.500 --> 00:00:03.750\nTest\n"
        segments = parse_srt(srt)
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]["start"], 1.5)
        self.assertAlmostEqual(segments[0]["end"], 3.75)

    def test_parse_sorts_by_start(self):
        srt = """2
00:00:05,000 --> 00:00:08,000
Second

1
00:00:01,000 --> 00:00:04,000
First"""
        segments = parse_srt(srt)
        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0]["start"], 1.0)
        self.assertEqual(segments[0]["text"], "First")
        self.assertAlmostEqual(segments[1]["start"], 5.0)
        self.assertEqual(segments[1]["text"], "Second")

    def test_parse_skips_empty_text(self):
        srt = "1\n00:00:01,000 --> 00:00:04,000\n\n2\n00:00:05,000 --> 00:00:08,000\nReal text\n"
        segments = parse_srt(srt)
        self.assertEqual(len(segments), 1)

    def test_parse_crlf_line_endings(self):
        srt = "1\r\n00:00:01,000 --> 00:00:04,000\r\nHello\r\n"
        segments = parse_srt(srt)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "Hello")


class TestSegmentsToSrt(unittest.TestCase):
    """segments → SRT 文本。"""

    def test_basic_output(self):
        segments = [
            {"start": 1.0, "end": 4.0, "text": "Hello world"},
            {"start": 5.0, "end": 8.5, "text": "Test"},
        ]
        result = segments_to_srt(segments)
        self.assertIn("00:00:01.000 --> 00:00:04.000", result)
        self.assertIn("Hello world", result)
        self.assertIn("00:00:05.000 --> 00:00:08.500", result)
        self.assertIn("Test", result)
        self.assertIn("1", result)
        self.assertIn("2", result)

    def test_empty_segments(self):
        self.assertEqual(segments_to_srt([]), "")

    def test_roundtrip(self):
        original = """1
00:00:01,000 --> 00:00:04,000
Hello world

2
00:00:05,000 --> 00:00:08,500
This is a test"""
        segments = parse_srt(original)
        output = segments_to_srt(segments)
        self.assertIn("Hello world", output)
        self.assertIn("This is a test", output)
        self.assertIn("00:00:01.000", output)


class TestSRTSegment(unittest.TestCase):
    """SRTSegment 数据类。"""

    def test_creation(self):
        seg = SRTSegment(start=1.5, end=3.0, text="Hello")
        self.assertEqual(seg.start, 1.5)
        self.assertEqual(seg.end, 3.0)
        self.assertEqual(seg.text, "Hello")

    def test_default_values(self):
        seg = SRTSegment()
        self.assertEqual(seg.start, 0.0)
        self.assertEqual(seg.end, 0.0)
        self.assertEqual(seg.text, "")

    def test_as_dict(self):
        seg = SRTSegment(start=1.0, end=2.0, text="Test")
        d = seg.as_dict()
        self.assertEqual(d, {"start": 1.0, "end": 2.0, "text": "Test", "words": []})

    def test_from_dict(self):
        d = {"start": 1.0, "end": 2.0, "text": "Test", "words": ["a", "b"]}
        seg = SRTSegment.from_dict(d)
        self.assertEqual(seg.start, 1.0)
        self.assertEqual(seg.text, "Test")


if __name__ == "__main__":
    unittest.main()
