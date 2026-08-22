"""hwaccel：编码参数构造（纯逻辑部分）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import hwaccel  # noqa: E402


class TestHwaccelArgs(unittest.TestCase):
    def test_force_software_uses_libx264(self):
        args = hwaccel.get_video_encode_args(crf=23, preset="fast", force_software=True)
        self.assertIn("-c:v", args)
        self.assertEqual(args[args.index("-c:v") + 1], "libx264")
        self.assertIn("-crf", args)
        self.assertIn("23", args)
        self.assertEqual(args[-2:], ["-pix_fmt", "yuv420p"])

    def test_preset_mapping(self):
        args = hwaccel.get_video_encode_args(preset="slow", force_software=True)
        idx = args.index("-preset")
        self.assertEqual(args[idx + 1], "slow")

    def test_preset_fallback_unknown(self):
        args = hwaccel.get_video_encode_args(preset="no_such", force_software=True)
        idx = args.index("-preset")
        self.assertIn(args[idx + 1], ("fast", "medium", "slow", "veryslow", "superfast", "veryfast"))

    def test_decode_args_is_list(self):
        self.assertIsInstance(hwaccel.get_hwaccel_decode_args(), list)

    def test_preset_maps_known(self):
        for enc in ("h264_nvenc", "h264_amf", "h264_qsv", "libx264"):
            self.assertIn(enc, hwaccel._PRESET_MAP)
            self.assertIn(enc, hwaccel._QUALITY_FLAG)


if __name__ == "__main__":
    unittest.main()
