"""tests/unit/test_rh_queue_processor.py — RunningHub 队列统计测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from core.rh_queue_processor import build_pending_task, compute_queue_stats


class TestComputeQueueStats(unittest.TestCase):
    """compute_queue_stats 队列统计测试。"""

    def test_empty_tasks(self):
        stats = compute_queue_stats([])
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["submitted"], 0)
        self.assertEqual(stats["downloaded"], 0)
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["running"], 0)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["pct"], 0)

    def test_all_pending(self):
        tasks = [
            {"state": "pending", "submit_count": 0, "downloaded": False},
            {"state": "pending", "submit_count": 0, "downloaded": False},
        ]
        stats = compute_queue_stats(tasks)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["submitted"], 0)
        self.assertEqual(stats["pct"], 0)

    def test_mixed_states(self):
        tasks = [
            {"state": "pending", "submit_count": 0, "downloaded": False},
            {"state": "submitted", "submit_count": 1, "downloaded": False},
            {"state": "done", "submit_count": 1, "downloaded": True},
            {"state": "failed", "submit_count": 2, "downloaded": False},
        ]
        stats = compute_queue_stats(tasks)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["running"], 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["submitted"], 3)

    def test_progress_percentage(self):
        tasks = [
            {"state": "done", "submit_count": 1, "downloaded": True},
            {"state": "failed", "submit_count": 1, "downloaded": False},
            {"state": "pending", "submit_count": 0, "downloaded": False},
        ]
        stats = compute_queue_stats(tasks)
        self.assertEqual(stats["pct"], 66)  # (1+1)/3 * 100 = 66

    def test_zero_division(self):
        stats = compute_queue_stats([])
        self.assertEqual(stats["pct"], 0)

    def test_submitted_count_logic(self):
        tasks = [
            {"state": "pending", "submit_count": 0, "downloaded": False},
            {"state": "pending", "submit_count": 1, "downloaded": False},
            {"state": "pending", "submit_count": 0, "downloaded": True, "note": "state!=pending or submit_count>0"},
            {"state": "done", "submit_count": 0, "downloaded": True},
        ]
        stats = compute_queue_stats(tasks)
        # submitted = submit_count > 0 OR state != pending
        self.assertEqual(stats["submitted"], 2)


class TestBuildPendingTask(unittest.TestCase):
    """build_pending_task 任务构建测试。"""

    def test_video_task(self):
        task = build_pending_task(
            idx=0, wf_id="wf_1", img_file="img.jpg",
            vid_file="vid.mp4", audio_files=None,
            image_nodes=["node1"], video_nodes=["node2"],
            audio_nodes=[], duration_nodes=["node3"],
            duration_value=5, instance_type="default",
        )
        self.assertEqual(task["idx"], 0)
        self.assertEqual(task["wf_id"], "wf_1")
        self.assertEqual(task["img_file"], "img.jpg")
        self.assertEqual(task["vid_file"], "vid.mp4")
        self.assertEqual(task["state"], "pending")
        self.assertEqual(task["retry_count"], 0)
        self.assertEqual(task["submit_count"], 0)
        self.assertFalse(task["downloaded"])

    def test_audio_task(self):
        task = build_pending_task(
            idx=2, wf_id="wf_2", img_file="img2.jpg",
            vid_file=None, audio_files=["aud1.mp3", "aud2.mp3"],
            image_nodes=["n1"], video_nodes=[],
            audio_nodes=["n2"], duration_nodes=[],
            duration_value=3, instance_type="fast",
        )
        self.assertEqual(task["idx"], 2)
        self.assertEqual(task["aud_file"], "aud1.mp3")
        self.assertEqual(task["instance_type"], "fast")

    def test_default_instance_type(self):
        task = build_pending_task(
            idx=0, wf_id="wf_1", img_file="img.jpg",
            vid_file=None, audio_files=None,
            image_nodes=[], video_nodes=[],
            audio_nodes=[], duration_nodes=[],
            duration_value=0, instance_type=None,
        )
        self.assertEqual(task["instance_type"], "default")

    def test_submit_fields_default(self):
        task = build_pending_task(
            idx=0, wf_id="wf_1", img_file="img.jpg",
            vid_file=None, audio_files=None,
            image_nodes=[], video_nodes=[],
            audio_nodes=[], duration_nodes=[],
            duration_value=0, instance_type=None,
        )
        self.assertIsNone(task["task_id"])
        self.assertIsNone(task["error"])
        self.assertEqual(task["next_attempt_at"], 0)


if __name__ == "__main__":
    unittest.main()
