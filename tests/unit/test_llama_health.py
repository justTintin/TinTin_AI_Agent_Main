"""llama-server 健康检查离线测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils.llama_health import check_health, find_llama_process, probe_server  # noqa: E402


class FakeProc:
    def __init__(self, pid, name):
        self.info = {"pid": pid, "name": name}


class TestLlamaHealth(unittest.TestCase):
    def test_find_llama_process_matches_known_names(self):
        fake = FakeProc(1234, "llama-server.exe")
        with mock.patch("utils.llama_health.psutil.process_iter", return_value=[fake]):
            proc = find_llama_process()
        self.assertIsNotNone(proc)
        self.assertEqual(proc.info["pid"], 1234)

    def test_find_llama_process_returns_none_when_missing(self):
        with mock.patch("utils.llama_health.psutil.process_iter", return_value=[]):
            proc = find_llama_process()
        self.assertIsNone(proc)

    def test_probe_server_ok(self):
        with mock.patch("utils.llama_health.requests.get") as mg:
            mg.return_value.status_code = 200
            result = probe_server("http://test/api/tags", timeout=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertIsNotNone(result["elapsed_ms"])

    def test_probe_server_timeout(self):
        import requests as req
        with mock.patch("utils.llama_health.requests.get",
                        side_effect=req.Timeout("timeout")):
            result = probe_server("http://test/api/tags", timeout=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")

    def test_check_health_healthy_when_cpu_low_and_probe_ok(self):
        fake = FakeProc(1234, "llama-server.exe")
        with mock.patch("utils.llama_health.find_llama_process", return_value=fake), \
             mock.patch("utils.llama_health.sample_cpu_percent", return_value=10.0), \
             mock.patch("utils.llama_health.probe_server",
                        return_value={"ok": True, "status_code": 200, "elapsed_ms": 50, "error": None}):
            res = check_health()
        self.assertTrue(res["healthy"])
        self.assertIn("接口响应", res["reason"])

    def test_check_health_detects_hang_when_cpu_high_and_probe_timeout(self):
        fake = FakeProc(1234, "llama-server.exe")
        with mock.patch("utils.llama_health.find_llama_process", return_value=fake), \
             mock.patch("utils.llama_health.sample_cpu_percent", return_value=99.0), \
             mock.patch("utils.llama_health.probe_server",
                        return_value={"ok": False, "status_code": None, "elapsed_ms": None, "error": "timeout"}):
            res = check_health()
        self.assertFalse(res["healthy"])
        self.assertIn("疑似卡死", res["reason"])
        self.assertIn("CPU 99.0%", res["reason"])

    def test_check_health_no_process(self):
        with mock.patch("utils.llama_health.find_llama_process", return_value=None):
            res = check_health()
        self.assertFalse(res["healthy"])
        self.assertIn("未找到", res["reason"])


if __name__ == "__main__":
    unittest.main()
