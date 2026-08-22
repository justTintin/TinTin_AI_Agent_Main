"""ffmpeg_utils 测试：run / extract_frame / cut_video / change_audio_speed / probe / popen。"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import ffmpeg_utils as fu  # noqa: E402


class _FakeProc:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRun(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(0))
    def test_run_basic(self, m_run):
        rc = fu.run(["ffmpeg", "-version"])
        self.assertEqual(rc.returncode, 0)
        # stdin 默认 DEVNULL
        self.assertEqual(m_run.call_args.kwargs["stdin"], __import__("subprocess").DEVNULL)

    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(0))
    def test_run_capture(self, m_run):
        fu.run(["ffmpeg", "-y", "-i", "in.mp4"], capture_output=True, text=True)
        self.assertTrue(m_run.call_args.kwargs["capture_output"])

    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(1, stderr=b"error"))
    def test_run_nonzero_returncode(self, m_run):
        rc = fu.run(["ffmpeg", "bad"])
        self.assertEqual(rc.returncode, 1)


class TestExtractFrame(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(0))
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    @mock.patch("os.path.isfile", return_value=True)
    def test_extract_frame_success(self, m_isfile, m_ff, m_run):
        result = fu.extract_frame("video.mp4", 5.0, "out.jpg")
        self.assertTrue(result)
        cmd = m_run.call_args.args[0]
        self.assertIn("ffmpeg", cmd[0])  # first element is ffmpeg path
        self.assertIn("-ss", cmd)
        self.assertIn("5.0", cmd)
        self.assertIn("out.jpg", cmd)

    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(1))
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    @mock.patch("os.path.isfile", return_value=False)
    def test_extract_frame_file_not_created(self, m_isfile, m_ff, m_run):
        result = fu.extract_frame("video.mp4", 0.0, "out.jpg")
        self.assertFalse(result)

    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="")
    def test_extract_frame_no_ffmpeg(self, m_ff):
        result = fu.extract_frame("video.mp4", 0.0, "out.jpg")
        self.assertFalse(result)


class TestCutVideo(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(0))
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    @mock.patch("os.path.isfile", return_value=True)
    @mock.patch("os.path.getsize", return_value=1024)
    def test_cut_success(self, m_size, m_isfile, m_ff, m_run):
        result = fu.cut_video("in.mp4", 1.0, 5.0, "out.mp4")
        self.assertTrue(result)
        cmd = m_run.call_args.args[0]
        self.assertIn("-ss", cmd)
        self.assertIn("-to", cmd)
        self.assertIn("1.0", cmd)
        self.assertIn("5.0", cmd)

    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(1))
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    @mock.patch("os.path.isfile", return_value=False)
    def test_cut_output_missing(self, m_isfile, m_ff, m_run):
        result = fu.cut_video("in.mp4", 0.0, 1.0, "out.mp4")
        self.assertFalse(result)


class TestChangeAudioSpeed(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.subprocess.run", return_value=_FakeProc(0))
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    @mock.patch("os.path.isfile", return_value=True)
    @mock.patch("os.path.getsize", return_value=512)
    def test_speed_success(self, m_size, m_isfile, m_ff, m_run):
        result = fu.change_audio_speed("in.wav", 1.5, "out.wav")
        self.assertTrue(result)
        cmd = m_run.call_args.args[0]
        self.assertIn("atempo=1.5", cmd)

    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="")
    def test_speed_no_ffmpeg(self, m_ff):
        result = fu.change_audio_speed("in.wav", 1.5, "out.wav")
        self.assertFalse(result)


class TestGetVideoResolution(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.run")
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_resolution_parsed(self, m_ff, m_run):
        m_run.return_value = _FakeProc(0, stderr=", 1920x1080 [SAR 1:1 DAR 16:9]")
        w, h = fu.get_video_resolution("video.mp4")
        self.assertEqual((w, h), (1920, 1080))

    @mock.patch("utils.ffmpeg_utils.run")
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_resolution_fallback(self, m_ff, m_run):
        m_run.return_value = _FakeProc(0, stderr="no resolution info")
        w, h = fu.get_video_resolution("video.mp4")
        self.assertEqual((w, h), (1280, 720))

    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="")
    def test_resolution_no_ffmpeg(self, m_ff):
        w, h = fu.get_video_resolution("video.mp4")
        self.assertEqual((w, h), (1280, 720))


class TestGetVideoFps(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.run")
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_fps_parsed(self, m_ff, m_run):
        m_run.return_value = _FakeProc(0, stderr="30 fps, 48000 Hz")
        fps = fu.get_video_fps("video.mp4")
        self.assertAlmostEqual(fps, 30.0)

    @mock.patch("utils.ffmpeg_utils.run")
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_fps_fractional(self, m_ff, m_run):
        m_run.return_value = _FakeProc(0, stderr="29.97 fps")
        fps = fu.get_video_fps("video.mp4")
        self.assertAlmostEqual(fps, 29.97)

    @mock.patch("utils.ffmpeg_utils.run")
    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_fps_fallback(self, m_ff, m_run):
        m_run.return_value = _FakeProc(0, stderr="no fps info")
        fps = fu.get_video_fps("video.mp4")
        self.assertAlmostEqual(fps, 30.0)

    @mock.patch("utils.ffmpeg_utils.find_ffmpeg", return_value="")
    def test_fps_no_ffmpeg(self, m_ff):
        fps = fu.get_video_fps("video.mp4")
        self.assertAlmostEqual(fps, 30.0)


class TestPopen(unittest.TestCase):
    @mock.patch("utils.ffmpeg_utils.subprocess.Popen")
    def test_popen_basic(self, m_popen):
        m_popen.return_value = mock.MagicMock()
        proc = fu.popen(["ffmpeg", "-y", "-i", "in.mp4"])
        self.assertIsNotNone(proc)
        kwargs = m_popen.call_args.kwargs
        # Windows 下应带 creationflags
        if os.name == "nt":
            self.assertIn("creationflags", kwargs)

    @mock.patch("utils.ffmpeg_utils.subprocess.Popen")
    def test_popen_with_stdout_pipe(self, m_popen):
        m_popen.return_value = mock.MagicMock()
        fu.popen(["ffmpeg", "-y", "-i", "in.mp4"], stdout=subprocess.PIPE)
        self.assertEqual(m_popen.call_args.kwargs["stdout"], subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
