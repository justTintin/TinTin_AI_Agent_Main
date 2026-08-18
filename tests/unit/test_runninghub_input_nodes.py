# -*- coding: utf-8 -*-
"""RunningHub workflow JSON 输入节点解析单元测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

import unittest
from gui.main_window_aigen import _classify_runninghub_input_nodes


class TestRunningHubInputNodes(unittest.TestCase):
    def test_empty_and_invalid_input(self):
        self.assertEqual(_classify_runninghub_input_nodes(None), {"image": [], "audio": [], "video": [], "duration": []})
        self.assertEqual(_classify_runninghub_input_nodes({}), {"image": [], "audio": [], "video": [], "duration": []})

    def test_detect_image_and_audio_nodes(self):
        wf = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "portrait.png"}},
            "2": {"class_type": "VHS_LoadAudioUpload", "inputs": {"audio": "voice.mp3", "duration": 0}},
        }
        result = _classify_runninghub_input_nodes(wf)
        self.assertEqual(result["image"], [("1", "LoadImage", "image", "portrait.png")])
        self.assertEqual(result["audio"], [("2", "VHS_LoadAudioUpload", "audio", "voice.mp3")])

    def test_detect_video_nodes(self):
        wf = {
            "3": {"class_type": "LoadVideo", "inputs": {"video": "input.mp4"}},
            "4": {"class_type": "VHS_LoadVideo", "inputs": {"video": "input2.mov"}},
        }
        result = _classify_runninghub_input_nodes(wf)
        self.assertEqual(len(result["video"]), 2)
        self.assertEqual(result["video"][0], ("3", "LoadVideo", "video", "input.mp4"))

    def test_detect_duration_nodes(self):
        wf = {
            "5": {"class_type": "IntNode", "inputs": {"duration": 8}},
            "6": {"class_type": "PrimitiveNode", "inputs": {"seconds": 15.5}},
            "7": {"class_type": "LoadVideo", "inputs": {"video": "x.mp4", "duration": 0}},
        }
        result = _classify_runninghub_input_nodes(wf)
        # LoadVideo / LoadAudio 等上传节点内部的 duration/seconds 不作为可配置生成时长
        self.assertEqual(result["duration"], [
            ("5", "IntNode", "duration", 8),
            ("6", "PrimitiveNode", "seconds", 15.5),
        ])
        self.assertEqual(len(result["video"]), 1)

    def test_ignore_linked_values(self):
        wf = {
            "8": {"class_type": "LoadImage", "inputs": {"image": ["9", 0]}},
        }
        result = _classify_runninghub_input_nodes(wf)
        self.assertEqual(result["image"], [])


if __name__ == "__main__":
    unittest.main()
