# -*- coding: utf-8 -*-
"""extreme_words：极限词检测。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from utils.extreme_words import EXTREME_WORDS, check_extreme_words


class TestExtremeWords(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(check_extreme_words(""), [])
        self.assertEqual(check_extreme_words(None), [])

    def test_detects_word_and_position(self):
        word = EXTREME_WORDS[0]
        text = "前缀" + word + "后缀"
        hits = check_extreme_words(text)
        self.assertTrue(any(h["word"] == word for h in hits))
        h = next(h for h in hits if h["word"] == word)
        self.assertEqual(text[h["start"]:h["end"]], word)

    def test_multiple_hits(self):
        hits = check_extreme_words("最好 最差")
        words = {h["word"] for h in hits}
        self.assertIn("最好", words)
        self.assertIn("最差", words)

    def test_result_structure(self):
        for h in check_extreme_words("顶级品质"):
            self.assertIn("word", h)
            self.assertIn("start", h)
            self.assertIn("end", h)
            self.assertGreaterEqual(h["end"], h["start"])


if __name__ == "__main__":
    unittest.main()