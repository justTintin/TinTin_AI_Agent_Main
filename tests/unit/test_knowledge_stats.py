"""tests/unit/test_knowledge_stats.py — 知识库统计测试。"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from core.knowledge_stats import (
    compute_knowledge_stats,
    determine_warning_level,
    read_browser_counts,
)


class TestComputeKnowledgeStats(unittest.TestCase):
    """compute_knowledge_stats 知识库统计测试。"""

    def test_empty_items(self):
        result = compute_knowledge_stats([], "stylization", "reference")
        self.assertEqual(result["stylizations"], 0)
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["downloaded_kb"], 0)
        self.assertEqual(result["days_ago"], 9999)

    def test_count_by_type(self):
        items = [
            {"type": "stylization", "updated_at": 1000},
            {"type": "stylization", "updated_at": 2000},
            {"type": "reference", "updated_at": 3000},
            {"type": "other", "updated_at": 4000},
        ]
        result = compute_knowledge_stats(items, "stylization", "reference")
        self.assertEqual(result["stylizations"], 2)
        self.assertEqual(result["samples"], 1)

    def test_days_ago_calculation(self):
        now = time.time()
        items = [
            {"type": "stylization", "updated_at": now - 86400},  # 1 day ago
            {"type": "stylization", "updated_at": now - 2 * 86400},  # 2 days ago
        ]
        result = compute_knowledge_stats(items, "stylization", "reference")
        self.assertEqual(result["stylizations"], 2)
        self.assertGreaterEqual(result["days_ago"], 1)
        self.assertLessEqual(result["days_ago"], 2)

    def test_no_stylizations(self):
        result = compute_knowledge_stats([], "stylization", "reference")
        self.assertEqual(result["days_ago"], 9999)

    def test_downloaded_kb_count(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            real_path = f.name
        try:
            items = [
                {"type": "reference", "source": {"media_path": real_path}},
                {"type": "reference", "source": {"media_path": ""}},
                {"type": "reference", "source": {}},
                {"type": "reference"},
            ]
            result = compute_knowledge_stats(items, "stylization", "reference")
            self.assertEqual(result["downloaded_kb"], 1)
        finally:
            os.unlink(real_path)

    def test_last_update_from_max(self):
        items = [
            {"type": "stylization", "updated_at": 1000},
            {"type": "stylization", "updated_at": 5000},
            {"type": "stylization", "updated_at": 3000},
        ]
        result = compute_knowledge_stats(items, "stylization", "reference")
        self.assertEqual(result["last_ts"], 5000)


class TestDetermineWarningLevel(unittest.TestCase):
    """determine_warning_level 阈值判断测试。"""

    def test_normal(self):
        color, level = determine_warning_level(10, 0, 3)
        self.assertEqual(color, "#4CAF50")
        self.assertEqual(level, "normal")

    def test_warning_unimported(self):
        color, level = determine_warning_level(10, 5, 3)
        self.assertEqual(color, "#FF9800")
        self.assertEqual(level, "warning")

    def test_warning_stale(self):
        color, level = determine_warning_level(10, 0, 10)
        self.assertEqual(color, "#FF9800")
        self.assertEqual(level, "warning")

    def test_danger_no_stylizations(self):
        color, level = determine_warning_level(0, 0, 9999)
        self.assertEqual(color, "#F44336")
        self.assertEqual(level, "danger")

    def test_danger_many_unimported(self):
        color, level = determine_warning_level(10, 31, 3)
        self.assertEqual(color, "#F44336")
        self.assertEqual(level, "danger")

    def test_danger_very_stale(self):
        color, level = determine_warning_level(10, 0, 15)
        self.assertEqual(color, "#F44336")
        self.assertEqual(level, "danger")

    def test_exact_thresholds(self):
        # 30 unimported → still warning (danger requires > 30)
        color, _ = determine_warning_level(10, 30, 3)
        self.assertEqual(color, "#FF9800")

        # 31 → danger
        color, _ = determine_warning_level(10, 31, 3)
        self.assertEqual(color, "#F44336")

        # 7 days → normal (warning requires > 7)
        color, _ = determine_warning_level(10, 0, 7)
        self.assertEqual(color, "#4CAF50")

        # 8 days → warning
        color, _ = determine_warning_level(10, 0, 8)
        self.assertEqual(color, "#FF9800")

        # 14 days → still warning (danger requires > 14)
        color, _ = determine_warning_level(10, 0, 14)
        self.assertEqual(color, "#FF9800")

        # 15 days → danger
        color, _ = determine_warning_level(10, 0, 15)
        self.assertEqual(color, "#F44336")


class TestReadBrowserCounts(unittest.TestCase):
    """read_browser_counts 浏览器数据读取测试。"""

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, sync = read_browser_counts(tmp, tmp)
            self.assertEqual(items, 0)
            self.assertEqual(sync, 0)

    def test_valid_items_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            items_path = os.path.join(tmp, "kb_items.json")
            with open(items_path, "w", encoding="utf-8-sig") as f:
                json.dump([1, 2, 3], f)
            items, sync = read_browser_counts(tmp, tmp)
            self.assertEqual(items, 3)

    def test_valid_sync_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync_path = os.path.join(tmp, "kb_sync.json")
            with open(sync_path, "w", encoding="utf-8-sig") as f:
                json.dump([{"id": 1}, {"id": 2}], f)
            items, sync = read_browser_counts(tmp, tmp)
            self.assertEqual(sync, 2)

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            items_path = os.path.join(tmp, "kb_items.json")
            with open(items_path, "w", encoding="utf-8-sig") as f:
                f.write("not json")
            items, sync = read_browser_counts(tmp, tmp)
            self.assertEqual(items, 0)

    def test_non_list_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            items_path = os.path.join(tmp, "kb_items.json")
            with open(items_path, "w", encoding="utf-8-sig") as f:
                json.dump({"key": "value"}, f)
            items, sync = read_browser_counts(tmp, tmp)
            self.assertEqual(items, 0)

    def test_fallback_to_media_dir(self):
        with tempfile.TemporaryDirectory() as materials_dir:
            media_dir = tempfile.mkdtemp()
            try:
                items_path = os.path.join(media_dir, "kb_items.json")
                with open(items_path, "w", encoding="utf-8-sig") as f:
                    json.dump([1, 2, 3, 4], f)
                items, sync = read_browser_counts(materials_dir, media_dir)
                self.assertEqual(items, 4)
            finally:
                import shutil
                shutil.rmtree(media_dir)


if __name__ == "__main__":
    unittest.main()
