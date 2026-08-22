"""tests/unit/test_video_indexer.py — video_indexer 单元测试。"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from utils.video_indexer import (
    VideoIndexWorker,
    WhisperFillWorker,
    call_vision_for_tags,
    classify_aspect,
    compute_video_hash,
    frame_to_b64,
    probe_color_metadata,
    probe_media_size,
)

from PySide6.QtCore import QCoreApplication

_app = QCoreApplication.instance()
if _app is None:
    _app = QCoreApplication([])


# ─── 1. classify_aspect ──────────────────────────────────────────────

class TestClassifyAspect(unittest.TestCase):

    def test_square(self):
        self.assertEqual(classify_aspect(1080, 1080), "1:1")

    def test_landscape(self):
        self.assertEqual(classify_aspect(1920, 1080), "16:9")

    def test_portrait(self):
        self.assertEqual(classify_aspect(1080, 1920), "9:16")

    def test_near_square_4_3(self):
        result = classify_aspect(4, 3)
        self.assertIn(result, ("1:1", "16:9"))

    def test_near_square_3_4(self):
        result = classify_aspect(3, 4)
        self.assertIn(result, ("1:1", "9:16"))

    def test_zero_width_defaults_to_1_1(self):
        self.assertEqual(classify_aspect(0, 1080), "1:1")

    def test_zero_height_defaults_to_1_1(self):
        self.assertEqual(classify_aspect(1080, 0), "1:1")

    def test_both_zero_defaults_to_1_1(self):
        self.assertEqual(classify_aspect(0, 0), "1:1")

    def test_extreme_landscape(self):
        self.assertEqual(classify_aspect(10000, 1), "16:9")

    def test_extreme_portrait(self):
        self.assertEqual(classify_aspect(1, 10000), "9:16")

    def test_almost_square_within_tolerance(self):
        self.assertEqual(classify_aspect(100, 95), "1:1")
        self.assertEqual(classify_aspect(95, 100), "1:1")

    def test_boundary_just_square(self):
        self.assertEqual(classify_aspect(1000, 1000), "1:1")

    def test_none_values(self):
        self.assertEqual(classify_aspect(None, 1080), "1:1")
        self.assertEqual(classify_aspect(1080, None), "1:1")

    def test_r_just_above_1_08(self):
        self.assertEqual(classify_aspect(108, 100), "1:1")

    def test_r_at_1_2_exact(self):
        self.assertEqual(classify_aspect(121, 100), "16:9")


# ─── 2. compute_video_hash ──────────────────────────────────────────

class TestComputeVideoHash(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_hash_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_correct_hash_for_known_file(self):
        fpath = os.path.join(self.tmp, "test.bin")
        data = b"hello world"
        with open(fpath, "wb") as f:
            f.write(data)
        expected = hashlib.md5(data).hexdigest()
        self.assertEqual(compute_video_hash(fpath), expected)

    def test_empty_file(self):
        fpath = os.path.join(self.tmp, "empty.bin")
        with open(fpath, "wb") as f:
            pass
        expected = hashlib.md5(b"").hexdigest()
        self.assertEqual(compute_video_hash(fpath), expected)

    def test_nonexistent_file(self):
        self.assertEqual(compute_video_hash(os.path.join(self.tmp, "no_such_file.mp4")), "")

    def test_empty_path(self):
        self.assertEqual(compute_video_hash(""), "")

    def test_none_path(self):
        self.assertEqual(compute_video_hash(None), "")

    @patch("os.path.isfile", return_value=True)
    @patch("builtins.open", side_effect=OSError("Permission denied"))
    def test_oserror_returns_empty(self, _mock_open, _mock_isfile):
        result = compute_video_hash("/fake/path/video.mp4")
        self.assertEqual(result, "")


# ─── 3. frame_to_b64 ────────────────────────────────────────────────

class TestFrameToB64(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_b64_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_correct_base64_encoding(self):
        fpath = os.path.join(self.tmp, "frame.jpg")
        data = b"test image data"
        with open(fpath, "wb") as f:
            f.write(data)
        expected = base64.b64encode(data).decode()
        self.assertEqual(frame_to_b64(fpath), expected)

    def test_binary_content(self):
        fpath = os.path.join(self.tmp, "binary.bin")
        data = bytes(range(256))
        with open(fpath, "wb") as f:
            f.write(data)
        expected = base64.b64encode(data).decode()
        self.assertEqual(frame_to_b64(fpath), expected)

    def test_empty_file(self):
        fpath = os.path.join(self.tmp, "empty.jpg")
        with open(fpath, "wb") as f:
            pass
        self.assertEqual(frame_to_b64(fpath), "")


# ─── 4. probe_media_size ────────────────────────────────────────────

class TestProbeMediaSize(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_probe_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_png_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL 不可用")
        img_path = os.path.join(self.tmp, "test.png")
        img = Image.new("RGB", (640, 480), color="red")
        img.save(img_path)
        result = probe_media_size(img_path)
        self.assertEqual(result, (640, 480))

    def test_valid_jpg_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL 不可用")
        img_path = os.path.join(self.tmp, "test.jpg")
        img = Image.new("RGB", (1920, 1080), color="blue")
        img.save(img_path, "JPEG")
        result = probe_media_size(img_path)
        self.assertEqual(result, (1920, 1080))

    def test_nonexistent_file(self):
        self.assertIsNone(probe_media_size(os.path.join(self.tmp, "no_such.png")))

    def test_empty_path(self):
        self.assertIsNone(probe_media_size(""))

    def test_none_path(self):
        self.assertIsNone(probe_media_size(None))

    def test_non_image_video_without_ffprobe(self):
        fpath = os.path.join(self.tmp, "test.mp4")
        with open(fpath, "wb") as f:
            f.write(b"fake video data")
        with patch("utils.platform_utils.find_ffprobe", return_value=None):
            result = probe_media_size(fpath)
            self.assertIsNone(result)

    def test_non_image_unknown_ext(self):
        fpath = os.path.join(self.tmp, "test.xyz")
        with open(fpath, "wb") as f:
            f.write(b"unknown content")
        with patch("utils.platform_utils.find_ffprobe", return_value=None):
            result = probe_media_size(fpath)
            self.assertIsNone(result)

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    @patch("utils.platform_utils.find_ffprobe")
    def test_video_with_ffprobe_success(self, mock_find, mock_run, _mock_isfile):
        mock_find.return_value = "C:/ffprobe.exe"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"streams": [{"width": 1920, "height": 1080}]}),
        )
        fpath = os.path.join(self.tmp, "test.mp4")
        with open(fpath, "wb") as f:
            f.write(b"fake video")
        result = probe_media_size(fpath)
        self.assertEqual(result, (1920, 1080))

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    @patch("utils.platform_utils.find_ffprobe")
    def test_video_ffprobe_failure(self, mock_find, mock_run, _mock_isfile):
        mock_find.return_value = "C:/ffprobe.exe"
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        fpath = os.path.join(self.tmp, "test.mp4")
        with open(fpath, "wb") as f:
            f.write(b"fake video")
        result = probe_media_size(fpath)
        self.assertIsNone(result)


# ─── 5. probe_color_metadata ────────────────────────────────────────

class TestProbeColorMetadata(unittest.TestCase):

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_successful_probe(self, mock_run, _mock_isfile):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "streams": [{
                    "color_transfer": "bt709",
                    "color_primaries": "bt709",
                    "color_space": "bt709",
                    "pix_fmt": "yuv420p",
                    "width": 1920,
                    "height": 1080,
                }],
            }),
        )
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="/usr/bin/ffprobe")
        self.assertEqual(result["color_transfer"], "bt709")
        self.assertEqual(result["width"], 1920)
        self.assertEqual(result["height"], 1080)

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_subprocess_error(self, mock_run, _mock_isfile):
        mock_run.side_effect = OSError("ffprobe not found")
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="/usr/bin/ffprobe")
        self.assertEqual(result, {})

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_json_parse_error(self, mock_run, _mock_isfile):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not valid json",
        )
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="/usr/bin/ffprobe")
        self.assertEqual(result, {})

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_nonzero_returncode(self, mock_run, _mock_isfile):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="/usr/bin/ffprobe")
        self.assertEqual(result, {})

    def test_no_ffprobe_returns_empty(self):
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="")
        self.assertEqual(result, {})

    @patch("utils.platform_utils.find_ffprobe")
    @patch("utils.platform_utils.find_ffmpeg")
    def test_ffprobe_not_available(self, mock_ffmpeg, mock_ffprobe):
        mock_ffprobe.return_value = None
        mock_ffmpeg.return_value = None
        result = probe_color_metadata("/fake/video.mp4")
        self.assertEqual(result, {})

    @patch("os.path.isfile", return_value=True)
    @patch("subprocess.run")
    def test_empty_streams(self, mock_run, _mock_isfile):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"streams": []}),
        )
        result = probe_color_metadata("/fake/video.mp4", ffprobe_path="/usr/bin/ffprobe")
        self.assertEqual(result, {})


# ─── 6. call_vision_for_tags ────────────────────────────────────────

class TestCallVisionForTags(unittest.TestCase):

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(call_vision_for_tags([], model="test"), [])

    def test_none_input_returns_empty_list(self):
        self.assertEqual(call_vision_for_tags(None, model="test"), [])

    @patch("utils.llm_proxy.llm_chat_messages")
    def test_successful_tag_parsing(self, mock_llm):
        mock_llm.return_value = '["键盘", "机械轴", "白色"]'
        result = call_vision_for_tags(["fake_b64"], model="test-model")
        self.assertEqual(result, ["键盘", "机械轴", "白色"])

    @patch("utils.llm_proxy.llm_chat_messages")
    def test_markdown_code_block_stripping(self, mock_llm):
        mock_llm.return_value = '```json\n["键盘", "白色"]\n```'
        result = call_vision_for_tags(["fake_b64"], model="test-model")
        self.assertEqual(result, ["键盘", "白色"])

    @patch("utils.llm_proxy.llm_chat_messages")
    def test_llm_error_returns_empty(self, mock_llm):
        mock_llm.side_effect = RuntimeError("API error")
        result = call_vision_for_tags(["fake_b64"], model="test-model")
        self.assertEqual(result, [])

    @patch("utils.llm_proxy.llm_chat_messages")
    def test_invalid_json_returns_empty(self, mock_llm):
        mock_llm.return_value = "not a json array"
        result = call_vision_for_tags(["fake_b64"], model="test-model")
        self.assertEqual(result, [])

    @patch("utils.llm_proxy.llm_chat_messages")
    def test_mixed_content_with_extra_text(self, mock_llm):
        mock_llm.return_value = "根据分析，标签为：[\"键盘\", \"白色\"] 等"
        result = call_vision_for_tags(["fake_b64"], model="test-model")
        self.assertEqual(result, ["键盘", "白色"])


# ─── 7. VideoIndexWorker ────────────────────────────────────────────

class TestVideoIndexWorker(unittest.TestCase):

    def test_stores_constructor_parameters(self):
        worker = VideoIndexWorker(
            "/path/to/video.mp4",
            num_frames=10,
            run_whisper=True,
            whisper_model="large-v3",
            skip_if_indexed=False,
        )
        self.assertEqual(worker.video_path, "/path/to/video.mp4")
        self.assertEqual(worker.num_frames, 10)
        self.assertTrue(worker.run_whisper)
        self.assertEqual(worker.whisper_model, "large-v3")
        self.assertFalse(worker.skip_if_indexed)

    def test_default_parameters(self):
        worker = VideoIndexWorker("/path/to/video.mp4")
        self.assertEqual(worker.num_frames, 8)
        self.assertFalse(worker.run_whisper)
        self.assertEqual(worker.whisper_model, "small")
        self.assertTrue(worker.skip_if_indexed)

    def test_hash_failure_raises_runtime_error(self):
        worker = VideoIndexWorker("/fake/video.mp4")
        emitted_errors = []
        worker.error.connect(lambda e: emitted_errors.append(e))
        worker.run()
        self.assertEqual(len(emitted_errors), 1)
        self.assertIn("哈希计算失败", emitted_errors[0])

    @patch("utils.video_indexer.frame_to_b64", return_value="ZmFrZQ==")
    @patch("utils.video_indexer.call_vision_for_tags", return_value=["测试标签"])
    @patch("utils.video_indexer.transcribe_audio", return_value="这是转写文本")
    @patch("utils.video_indexer.extract_frames_to_files", return_value=["/tmp/fake_frame_001.jpg"])
    @patch("utils.video_indexer.compute_video_hash", return_value="abc123def456")
    @patch("utils.rustfs_manager._ensure_bucket")
    @patch("utils.rustfs_manager._build_client")
    @patch("utils.rustfs_manager.get_rustfs_config", return_value={"bucket": "test-bucket"})
    def test_finished_signal_emits_correct_entry(
        self, _rustfs_cfg, _build_client, _ensure_bucket,
        _mock_hash, _mock_extract, _mock_transcribe,
        _mock_tags, _mock_tags_b64,
    ):
        _build_client.return_value = (MagicMock(), None)

        tmp_dir = tempfile.mkdtemp(prefix="test_ai_cfg_")
        ai_config_path = os.path.join(tmp_dir, "ai_config.json")
        with open(ai_config_path, "w", encoding="utf-8") as f:
            json.dump({"vision_llm_model": "test-model"}, f)

        with patch("config.paths.AI_CONFIG_FILE", ai_config_path):
            worker = VideoIndexWorker(
                "/fake/video.mp4",
                num_frames=8,
                run_whisper=True,
            )
            emitted_entries = []
            worker.finished.connect(lambda e: emitted_entries.append(e))
            worker.do_work()

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertEqual(len(emitted_entries), 1)
        entry = emitted_entries[0]
        self.assertEqual(entry["video_id"], "abc123def456")
        self.assertEqual(entry["nas_smb_path"], "/fake/video.mp4")
        self.assertEqual(entry["ai_tags"], ["测试标签"])
        self.assertEqual(entry["audio_script"], "这是转写文本")
        self.assertEqual(entry["s3_bucket"], "test-bucket")
        self.assertEqual(entry["s3_frame_prefix"], "abc123def456/")


# ─── 8. WhisperFillWorker ───────────────────────────────────────────

class TestWhisperFillWorker(unittest.TestCase):

    def test_stores_entry_and_model(self):
        entry = {"nas_smb_path": "/path/to/video.mp4", "audio_script": ""}
        worker = WhisperFillWorker(entry, whisper_model="large-v3")
        self.assertEqual(worker.entry, entry)
        self.assertEqual(worker.whisper_model, "large-v3")

    def test_default_model(self):
        entry = {"nas_smb_path": "/path/to/video.mp4"}
        worker = WhisperFillWorker(entry)
        self.assertEqual(worker.whisper_model, "small")

    def test_missing_nas_smb_path_raises(self):
        entry = {"some_other_field": "value"}
        worker = WhisperFillWorker(entry)
        emitted_errors = []
        worker.error.connect(lambda e: emitted_errors.append(e))
        worker.run()
        self.assertEqual(len(emitted_errors), 1)
        self.assertIn("nas_smb_path", emitted_errors[0])

    @patch("utils.video_indexer.transcribe_audio", return_value="转写完成文本")
    def test_successful_transcription_emits_finished(self, _mock_transcribe):
        entry = {"nas_smb_path": "/fake/video.mp4", "audio_script": ""}
        worker = WhisperFillWorker(entry)
        emitted_entries = []
        worker.finished.connect(lambda e: emitted_entries.append(e))
        worker.do_work()
        self.assertEqual(len(emitted_entries), 1)
        self.assertEqual(emitted_entries[0]["audio_script"], "转写完成文本")

    @patch("utils.video_indexer.transcribe_audio", return_value="")
    def test_transcribe_returns_empty_string(self, _mock_transcribe):
        entry = {"nas_smb_path": "/fake/video.mp4", "audio_script": "旧文本"}
        worker = WhisperFillWorker(entry)
        emitted_entries = []
        worker.finished.connect(lambda e: emitted_entries.append(e))
        worker.do_work()
        self.assertEqual(len(emitted_entries), 1)
        self.assertEqual(emitted_entries[0]["audio_script"], "")


if __name__ == "__main__":
    unittest.main()
