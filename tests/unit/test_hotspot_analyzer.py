"""tests/unit/test_hotspot_analyzer.py — 热点分析算法测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from core.hotspot_analyzer import HOT_KEYWORDS_CN, rule_analyze


class TestHotKeywords(unittest.TestCase):
    """热点关键词常量测试。"""

    def test_keywords_not_empty(self):
        self.assertTrue(len(HOT_KEYWORDS_CN) > 0)

    def test_keywords_contains_core_terms(self):
        self.assertIn("重点", HOT_KEYWORDS_CN)
        self.assertIn("干货", HOT_KEYWORDS_CN)
        self.assertIn("AI", HOT_KEYWORDS_CN)


class TestRuleAnalyze(unittest.TestCase):
    """rule_analyze 算法测试。"""

    def _make_segments(self, texts, dur_per_seg=5.0):
        """创建模拟的 segments 列表。"""
        segs = []
        t = 0.0
        for text in texts:
            segs.append(type("S", (), {"start": t, "end": t + dur_per_seg, "text": text})())
            t += dur_per_seg
        return segs

    def test_empty_segments(self):
        results = rule_analyze([])
        self.assertEqual(results, [])

    def test_no_hot_keywords(self):
        texts = ["hello world"] * 20
        segs = self._make_segments(texts)
        results = rule_analyze(segs)
        self.assertEqual(results, [])

    def test_with_hot_keywords(self):
        # 每个 segment 包含多个关键词
        texts = ["重点 关键 核心 重要 注意 记住 一定要 必须 干货 技巧 方法 步骤 AI 算法 模型"] * 5 + ["这是一个普通的句子。"] * 15
        segs = self._make_segments(texts)
        results = rule_analyze(segs)
        self.assertTrue(len(results) > 0)
        self.assertIn("title", results[0])

    def test_result_structure(self):
        texts = ["重点 关键 核心 重要 注意 记住 一定要 必须 干货 技巧 方法 步骤 AI 算法 模型"] * 20
        segs = self._make_segments(texts)
        results = rule_analyze(segs)
        self.assertTrue(len(results) > 0)
        r = results[0]
        self.assertIn("start", r)
        self.assertIn("end", r)
        self.assertIn("start_str", r)
        self.assertIn("end_str", r)
        self.assertIn("duration", r)
        self.assertIn("score", r)
        self.assertIn("title", r)
        self.assertIn("preview", r)

    def test_duration_within_range(self):
        texts = ["重点 关键 核心 重要 注意 记住 一定要 必须 干货 技巧 方法 步骤 AI 算法 模型"] * 50
        segs = self._make_segments(texts, dur_per_seg=10.0)
        results = rule_analyze(segs)
        for r in results:
            self.assertGreaterEqual(r["duration"], 15)
            self.assertLessEqual(r["duration"], 300)

    def test_score_positive(self):
        texts = ["重点 关键 核心 重要 注意 记住 一定要 必须 干货 技巧 方法 步骤 AI 算法 模型"] * 10
        segs = self._make_segments(texts)
        results = rule_analyze(segs)
        for r in results:
            self.assertGreater(r["score"], 0)

    def test_results_sorted_by_score(self):
        texts = ["重点 关键 核心 重要 注意 记住 一定要 必须 干货 技巧 方法 步骤 AI 算法 模型"] * 30
        segs = self._make_segments(texts, dur_per_seg=3.0)
        results = rule_analyze(segs)
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i]["score"], results[i + 1]["score"])


if __name__ == "__main__":
    unittest.main()
