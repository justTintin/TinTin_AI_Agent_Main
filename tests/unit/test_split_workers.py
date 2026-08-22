"""智能混剪镜头分割 Worker 离线测试（不连真实服务端）。

覆盖今天卡死的链路：ServerSplitWorker 的 HTTP 请求、下载、降级、
analysis_ready/finished 信号顺序、文件句柄释放。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from gui.montage.workers.split_workers import ServerSplitWorker  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self._content = content
        self.content = content
        self.text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)

    def json(self):
        return self._payload() if callable(self._payload) else self._payload

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]


class TestServerSplitWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="split_worker_")
        self.video = os.path.join(self.tmp, "sample.mp4")
        with open(self.video, "wb") as f:
            f.write(b"fake video bytes")
        self.out_dir = os.path.join(self.tmp, "splits")
        self.emitted = {"stage": [], "progress": [], "busy": [],
                        "finished": [], "analysis_ready": [], "error": []}
        self._emit_order = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _worker(self, **kw):
        kw.setdefault("video_path", self.video)
        kw.setdefault("output_dir", self.out_dir)
        kw.setdefault("server_url", "http://test-server")
        w = ServerSplitWorker(**kw)
        w.stage.connect(lambda t: self.emitted["stage"].append(t))
        w.progress.connect(lambda v: self.emitted["progress"].append(v))
        w.busy.connect(lambda b: self.emitted["busy"].append(b))
        w.finished.connect(lambda *a: (self.emitted["finished"].append(a), self._emit_order.append("finished")))
        w.analysis_ready.connect(lambda m: (self.emitted["analysis_ready"].append(m), self._emit_order.append("analysis_ready")))
        w.error.connect(lambda e: self.emitted["error"].append(e))
        return w

    def _make_shots(self, count=2, with_download=True):
        shots = []
        for i in range(count):
            shots.append({
                "shot_index": i + 1,
                "start_sec": float(i),
                "end_sec": float(i + 1),
                "filename": f"sample_shot_{i + 1:03d}.mp4",
                "download_url": f"/files/shot_{i + 1}.mp4" if with_download else None,
                "aesthetic_score": {"total": 8.5},
                "shot_analysis": {"shot_type": "中景"},
                "description": f"desc {i + 1}",
            })
        return shots

    def test_split_success_downloads_shots_and_emits_analysis_before_finished(self):
        """核心契约：analysis_ready 必须在 finished 之前发出，且片段正确落地。"""
        shots = self._make_shots(2)
        w = self._worker()
        content = b"mp4data"

        def _fake_download(url, path, timeout):
            with open(path, "wb") as f:
                f.write(content)
            return path

        with mock.patch("gui.montage.workers.split_workers.split",
                        return_value={"task_id": "t1", "total_shots": 2, "shots": shots}), \
             mock.patch("gui.montage.workers.split_workers.download_result",
                        side_effect=_fake_download) as mg:
            w.run()

        self.assertEqual(len(self.emitted["finished"]), 1)
        out_dir, count, scenes = self.emitted["finished"][0]
        self.assertEqual(count, 2)
        self.assertEqual(len(scenes), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.out_dir, "sample_shot_001.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(self.out_dir, "sample_shot_002.mp4")))
        # 信号顺序：analysis_ready 先于 finished
        self.assertEqual(len(self.emitted["analysis_ready"]), 1)
        self.assertEqual(self._emit_order, ["analysis_ready", "finished"])
        # download_result 用 download_url 下载（URL 拼接了 server_url）
        self.assertEqual(mg.call_count, 2)
        mg.assert_any_call("http://test-server/files/shot_1.mp4", mock.ANY, 300)
        mg.assert_any_call("http://test-server/files/shot_2.mp4", mock.ANY, 300)

    def test_split_uses_connection_close_and_closes_session(self):
        """迁移到 montage_client 后 worker 不再持有 Session；每次请求由 http_client 一次性发完即释放，避免连接池空闲。"""
        shots = self._make_shots(1)
        w = self._worker()

        def _fake_download(url, path, timeout):
            with open(path, "wb") as f:
                f.write(b"x")
            return path

        with mock.patch("gui.montage.workers.split_workers.split",
                        return_value={"shots": shots}) as ms, \
             mock.patch("gui.montage.workers.split_workers.download_result",
                        side_effect=_fake_download):
            w.run()
        # worker 不再直接管理 Session；split 调用一次，请求一次性完成
        self.assertEqual(ms.call_count, 1)
        self.assertEqual(len(self.emitted["finished"]), 1)
        self.assertEqual(len(self.emitted["error"]), 0)

    def test_split_upload_file_closed_after_request(self):
        """上传大文件时句柄不能泄漏，否则 Windows 下二次写入会失败。"""
        shots = self._make_shots(1)
        w = self._worker()
        fake_file = mock.MagicMock()
        fake_file.closed = False
        real_open = open

        def _fake_open(path, mode="r", *args, **kwargs):
            if path == self.video and mode == "rb":
                return fake_file
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=_fake_open) as mo, mock.patch("requests.Session") as mock_session:
            session = mock_session.return_value
            session.post.return_value = FakeResponse(200, {"shots": shots})
            session.headers = {}
            with mock.patch("utils.http_client.http_get",
                            return_value=FakeResponse(200, content=b"x")):
                w.run()
        # open 被调用来读取上传文件
        mo.assert_any_call(self.video, "rb")
        fake_file.close.assert_called()

    def test_split_empty_shots_emits_zero_before_finished(self):
        """服务端未检测到镜头时，应正确结束而不是卡住。"""
        w = self._worker()
        with mock.patch("gui.montage.workers.split_workers.split",
                        return_value={"shots": []}):
            w.run()
        self.assertEqual(len(self.emitted["finished"]), 1)
        self.assertEqual(self.emitted["finished"][0][1], 0)
        self.assertEqual(self._emit_order, ["analysis_ready", "finished"])

    def test_split_server_error_emits_error(self):
        """服务端 500 时必须 emit error，不能静默吞掉。"""
        w = self._worker()
        with mock.patch("requests.Session") as mock_session:
            session = mock_session.return_value
            session.post.return_value = FakeResponse(500, "Internal Server Error")
            session.headers = {}
            w.run()
        self.assertEqual(len(self.emitted["error"]), 1)
        self.assertEqual(len(self.emitted["finished"]), 0)

    def test_split_download_failure_falls_back_to_local_cut(self):
        """下载失败时，如果本地有源文件，应回退 ffmpeg 重裁。"""
        shots = self._make_shots(1, with_download=True)
        w = self._worker()
        with mock.patch("gui.montage.workers.split_workers.split",
                        return_value={"shots": shots}), \
             mock.patch("gui.montage.workers.split_workers.download_result",
                        side_effect=requests.exceptions.RequestException("network down")), \
             mock.patch.object(w, "_local_cut", return_value=True) as mlc:
            w.run()
        # 本地重裁被调用
        mlc.assert_called_once()
        args, _ = mlc.call_args
        self.assertEqual(args[:2], (0.0, 1.0))
        self.assertEqual(len(self.emitted["finished"]), 1)
        self.assertEqual(self.emitted["finished"][0][1], 1)

    def test_split_material_id_does_not_upload_file(self):
        """素材库素材应传 material_id，而不是打开本地文件。"""
        w = self._worker(video_path="", material_id="mat_123")
        with mock.patch("gui.montage.workers.split_workers.split",
                        return_value={"shots": []}) as ms:
            w.run()
        # split(server_url, files, data, timeout) — files 在第二个位置参数
        _server, files, data, _timeout = ms.call_args.args
        self.assertEqual(data["material_id"], "mat_123")
        # files 应为 None（未上传）
        self.assertIsNone(files)


if __name__ == "__main__":
    unittest.main()
