"""智能混剪服务端拼接 Worker：离线 mock 测试（不连真服务端）。

验证 MontageConcatServerWorker 的：
- /montage/concat 提交参数（multipart files / lut / form 字段转字符串）
- 任务轮询与成品下载 / _sources.txt 写入
- 错误分支（缺文件、无 task_id、任务失败、产物过小）
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from gui.montage.workers.montage_concat_server_worker import (  # noqa: E402
    MontageConcatServerWorker,
    _looks_like_server_lost_upload,
)
from utils import scheduled_task_client as stc  # noqa: E402

# 真实服务端回传的错误（上传目录基准/落盘文件名不一致）
_SERVER_LOST_UPLOAD_MSG = (
    "素材不存在: /home/tintin/Project/TinTin_AI_Agent_Server (V2.0)/server/api/../uploads/"
    "montage/concat_15afe52b1b2b/clip_001.mp4\nTraceback (most recent call last):\n"
    "  File \"/home/freya/Project/TinTin_AI_Agent_Server/server/workers/montage_compose.py\", "
    "line 67, in _resolve_to_local\n    raise FileNotFoundError(f\"素材不存在: {url_or_path}\")\n"
    "FileNotFoundError: 素材不存在: .../clip_001.mp4"
)


class TestMontageConcatWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="montage_worker_")
        self.clip1 = os.path.join(self.tmp, "clip_001.mp4")
        self.clip2 = os.path.join(self.tmp, "clip_002.mp4")
        self.lut = os.path.join(self.tmp, "look.cube")
        self.out = os.path.join(self.tmp, "out", "result.mp4")
        for p in (self.clip1, self.clip2, self.lut):
            with open(p, "wb") as f:
                f.write(b"x" * 4096)
        self.emitted = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _worker(self, **kw):
        kw.setdefault("local_output_path", self.out)
        kw.setdefault("clips", [self.clip1, self.clip2])
        w = MontageConcatServerWorker(**kw)
        w.stage.connect(self.emitted.append)
        w.progress.connect(self.emitted.append)
        w.concat_finished.connect(self.emitted.append)
        return w

    def test_submit_concat_multipart_contract(self):
        w = self._worker(options={"transition": "fade", "fps": 30, "width": 720})
        with mock.patch("gui.montage.workers.montage_concat_server_worker.concat",
                        return_value={"id": "task-abc"}) as m:
            task_id = w._submit_concat()
        self.assertEqual(task_id, "task-abc")
        self.assertEqual(m.call_count, 1)
        # concat(server_url, files, data, timeout) — montage_client 内部拼 /montage/concat
        server, files, data, _timeout = m.call_args.args
        self.assertTrue(server)
        # form 字段必须是字符串
        self.assertEqual(data, {"transition": "fade", "fps": "30", "width": "720"})
        # files：两个 clips
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0][1][0], "clip_001.mp4")
        self.assertEqual(files[1][1][0], "clip_002.mp4")

    def test_submit_concat_with_lut(self):
        w = self._worker(lut_path=self.lut)
        with mock.patch("gui.montage.workers.montage_concat_server_worker.concat",
                        return_value={"id": "t1"}) as m:
            w._submit_concat()
        # concat(server_url, files, data, timeout) — files 在第二个位置参数
        files = m.call_args.args[1]
        names = [f[1][0] for f in files]
        self.assertIn("look.cube", names)
        lut_parts = [f for f in files if f[0] == "lut"]
        self.assertEqual(len(lut_parts), 1)

    def test_submit_missing_clip_raises(self):
        w = self._worker(clips=[os.path.join(self.tmp, "nope.mp4")])
        with self.assertRaises(RuntimeError):
            w._submit_concat()

    def test_submit_missing_lut_raises(self):
        w = self._worker(lut_path=os.path.join(self.tmp, "missing.cube"))
        with self.assertRaises(RuntimeError):
            w._submit_concat()

    def test_submit_no_task_id_raises(self):
        w = self._worker()
        with mock.patch("gui.montage.workers.montage_concat_server_worker.concat",
                        return_value={"status": "ok"}), self.assertRaises(RuntimeError):
            w._submit_concat()

    def test_poll_download_and_sources(self):
        w = self._worker(source_clips=["src_1.mp4", "src_2.mp4"], task_id="task-1")
        completed = {"status": "completed", "progress": 100,
                     "result": {"video_url": "/files/result.mp4"}}
        content = b"z" * 2048

        def _fake_download(url, path, timeout):
            with open(path, "wb") as f:
                f.write(content)
            return path

        with mock.patch.object(stc, "get_task", return_value=completed), \
             mock.patch("gui.montage.workers.montage_concat_server_worker.download_result",
                        side_effect=_fake_download) as mg:
            w.do_work()
        # download_result 的 URL 拼接了服务端地址
        self.assertTrue(mg.call_args.args[0].startswith("http://"))
        self.assertTrue(mg.call_args.args[0].endswith("/files/result.mp4"))
        self.assertTrue(os.path.isfile(self.out))
        self.assertEqual(os.path.getsize(self.out), len(content))
        src_file = os.path.splitext(self.out)[0] + "_sources.txt"
        self.assertTrue(os.path.isfile(src_file))
        with open(src_file, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["src_1.mp4", "src_2.mp4"])

    def test_task_failed_raises(self):
        w = self._worker(task_id="task-x")
        with mock.patch.object(stc, "get_task",
                               return_value={"status": "failed", "error_msg": "boom"}), \
                 self.assertRaises(RuntimeError) as ctx:
                    w.do_work()
        self.assertIn("boom", str(ctx.exception))

    def test_server_lost_upload_falls_back_to_local(self):
        """服务端找不到自己接收的镜头文件 → 不报错，回退本地合成。"""
        w = self._worker(task_id="task-457")
        reasons = []
        w.fallback_to_local.connect(reasons.append)
        with mock.patch.object(stc, "get_task",
                               return_value={"status": "failed", "error_msg": _SERVER_LOST_UPLOAD_MSG}):
            w.do_work()  # 不应抛异常
        self.assertEqual(len(reasons), 1)
        self.assertIn("本地合成", reasons[0])

    def test_server_lost_upload_with_material_urls_still_raises(self):
        """含 material:// 片段时不能回退（本地没有那些素材，会静默缺镜头）。"""
        w = self._worker(task_id="task-458", clip_urls=["material://m_1"])
        reasons = []
        w.fallback_to_local.connect(reasons.append)
        with mock.patch.object(stc, "get_task",
                               return_value={"status": "failed", "error_msg": _SERVER_LOST_UPLOAD_MSG}), \
                 self.assertRaises(RuntimeError) as ctx:
                    w.do_work()
        self.assertIn("素材不存在", str(ctx.exception))
        self.assertEqual(reasons, [])

    def test_looks_like_server_lost_upload(self):
        self.assertTrue(_looks_like_server_lost_upload(_SERVER_LOST_UPLOAD_MSG))
        self.assertTrue(_looks_like_server_lost_upload("FileNotFoundError: no such file or directory"))  # noqa: E501
        self.assertFalse(_looks_like_server_lost_upload("boom"))
        self.assertFalse(_looks_like_server_lost_upload(""))
        self.assertFalse(_looks_like_server_lost_upload(None))

    def test_download_too_small_raises(self):
        w = self._worker(task_id="task-y")
        completed = {"status": "completed", "result": {"video_url": "/files/small.mp4"}}

        def _fake_download(url, path, timeout):
            with open(path, "wb") as f:
                f.write(b"tiny")
            return path

        with mock.patch.object(stc, "get_task", return_value=completed), \
             mock.patch("gui.montage.workers.montage_concat_server_worker.download_result",
                        side_effect=_fake_download), \
             self.assertRaises(RuntimeError):
            w.do_work()

    def test_stopped_raises(self):
        w = self._worker(task_id="task-z")
        w.stop()
        with self.assertRaises(RuntimeError):
            w.do_work()


if __name__ == "__main__":
    unittest.main()
