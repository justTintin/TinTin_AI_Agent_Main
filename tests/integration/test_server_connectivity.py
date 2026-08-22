"""服务端连通性集成测试（需要 --online，地址从 ai_config.compute_server_url 读取）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

ONLINE = os.environ.get("RUN_ONLINE") == "1"


@unittest.skipUnless(ONLINE, "需要 --online（联网访问服务端）")
class TestServerConnectivity(unittest.TestCase):
    def test_server_health(self):
        import requests
        base = testutil.server_base_url()
        self.assertTrue(base, "未在 ai_config.json 配置 compute_server_url")
        r = requests.get(base + "/health", timeout=15)
        self.assertEqual(r.status_code, 200, base + "/health -> " + str(r.status_code))

    def test_guide_doc_reachable(self):
        import requests
        base = testutil.server_base_url()
        self.assertTrue(base)
        r = requests.get(base + "/guide", stream=True, timeout=15)
        self.assertLess(r.status_code, 400, base + "/guide -> " + str(r.status_code))
        r.close()


if __name__ == "__main__":
    unittest.main()
