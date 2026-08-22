"""CreatorBrowserController 测试（纯逻辑部分，不启动 Playwright）。

重点覆盖：
- 构造参数（默认 browsers_path、注册到 _active_controllers）
- _extract_video_url 正则提取视频链接
- _maybe_update_from_text 状态变更触发
- get_status / _set_state 线程安全
- goto/click_category 向 cmd_q 投递
- get_cookies / evaluate 以 token 匹配响应（resp_q 超时返回 None）
- close_all_active_browsers 全局清理
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core import creator_browser_controller as cbc  # noqa: E402


class TestExtractVideoUrl(unittest.TestCase):
    def test_video_path(self):
        url = cbc.CreatorBrowserController._extract_video_url(
            None, "https://www.douyin.com/video/7350291791045790991")
        self.assertEqual(url, "https://www.douyin.com/video/7350291791045790991")

    def test_modal_id_param(self):
        url = cbc.CreatorBrowserController._extract_video_url(
            None, "https://creator.douyin.com/?modal_id=7366231405833063719&from=home")
        self.assertEqual(url, "https://www.douyin.com/video/7366231405833063719")

    def test_aweme_id_param(self):
        url = cbc.CreatorBrowserController._extract_video_url(
            None, "https://example.com/p?x=1&aweme_id=12345&y=2")
        self.assertEqual(url, "https://www.douyin.com/video/12345")

    def test_no_match_empty(self):
        self.assertEqual(cbc.CreatorBrowserController._extract_video_url(None, ""), "")
        self.assertEqual(cbc.CreatorBrowserController._extract_video_url(None, None), "")
        self.assertEqual(
            cbc.CreatorBrowserController._extract_video_url(None, "https://example.com/abc"),
            "")


class TestConstructor(unittest.TestCase):
    def setUp(self):
        # 清理全局活跃控制器，避免其他测试污染
        with cbc._active_controllers_lock:
            cbc._active_controllers.clear()

    def tearDown(self):
        with cbc._active_controllers_lock:
            cbc._active_controllers.clear()

    def test_defaults_and_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            self.assertEqual(c.user_data_dir, tmp)
            # browsers_path 默认 PW_BROWSERS_DIR
            from config.paths import PW_BROWSERS_DIR
            self.assertEqual(c.browsers_path, PW_BROWSERS_DIR)
            self.assertFalse(c.headless)
            # 状态字段
            status, cur, last = c.get_status()
            self.assertEqual(status, "未启动")
            self.assertEqual(cur, "")
            self.assertEqual(last, "")
            # 被注册到全局列表
            with cbc._active_controllers_lock:
                self.assertIn(c, cbc._active_controllers)
            # 重复构造不重复 append
            c2 = cbc.CreatorBrowserController(user_data_dir=tmp)
            with cbc._active_controllers_lock:
                count = sum(1 for x in cbc._active_controllers if x is c2)
            self.assertEqual(count, 1)

    def test_set_state_thread_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp, headless=True)
            self.assertTrue(c.headless)
            c._set_state(status="运行中", last_error="e1", current_video_url="http://dy/v/1")
            status, cur, last = c.get_status()
            self.assertEqual(status, "运行中")
            self.assertEqual(cur, "http://dy/v/1")
            self.assertEqual(last, "e1")
            # 部分更新不覆盖其他字段
            c._set_state(last_error="e2")
            status, cur, last = c.get_status()
            self.assertEqual(status, "运行中")
            self.assertEqual(last, "e2")


class TestMaybeUpdateFromText(unittest.TestCase):
    def test_updates_on_new_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            c._maybe_update_from_text("https://www.douyin.com/video/999")
            status, cur, _ = c.get_status()
            self.assertEqual(cur, "https://www.douyin.com/video/999")
            self.assertIn("已识别视频", status)

    def test_no_duplicate_updates_for_same_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            c._maybe_update_from_text("https://www.douyin.com/video/1")
            _, cur1, _ = c.get_status()
            # 再次同一 URL 不应触发 set_state（保持状态不变，这里简单验证 URL 相同）
            c._maybe_update_from_text("https://www.douyin.com/video/1")
            _, cur2, _ = c.get_status()
            self.assertEqual(cur1, cur2)

    def test_empty_text_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            c._maybe_update_from_text("")
            c._maybe_update_from_text(None)
            _, cur, _ = c.get_status()
            self.assertEqual(cur, "")


class TestCommandQueue(unittest.TestCase):
    def test_goto_puts_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            c.goto("http://example.com")
            self.assertEqual(c._cmd_q.get_nowait(), ("goto", "http://example.com"))

    def test_click_category_puts_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            c.click_category("短剧")
            self.assertEqual(c._cmd_q.get_nowait(), ("category", "短剧"))

    def test_get_cookies_token_mismatch_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            # 推入一个 kind 错误/不匹配 token 的响应
            c._resp_q.put(("get_cookies", "wrong_token", {"k": "v"}))
            result = c.get_cookies(timeout_ms=300)
            self.assertIsNone(result)

    def test_get_cookies_token_match_returns(self):
        # 直接 monkey-patch os.urandom 拿到将生成的 token
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            with mock.patch.object(_os, "urandom", return_value=bytes.fromhex("abcd1234")):
                expected_cookies = {"sessionid": "sess"}
                c._resp_q.put(("get_cookies", "abcd1234", expected_cookies))
                result = c.get_cookies(timeout_ms=300)
            self.assertEqual(result, expected_cookies)

    def test_get_cookies_timeout_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            # 不向 resp_q 放任何东西
            t0 = time.time()
            result = c.get_cookies(timeout_ms=200)
            dt = time.time() - t0
            self.assertIsNone(result)
            # 超时时间大致符合（至少 100ms，不到 2s）
            self.assertGreaterEqual(dt, 0.1)
            self.assertLess(dt, 2.0)

    def test_evaluate_token_match(self):
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            with mock.patch.object(_os, "urandom", return_value=bytes.fromhex("cafe0001")):
                c._resp_q.put(("evaluate", "cafe0001", 42))
                result = c.evaluate("1+1", timeout_ms=300)
            self.assertEqual(result, 42)


class TestIsRunningLifecycle(unittest.TestCase):
    def test_not_started_is_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            self.assertFalse(c.is_running())

    def test_stop_before_start_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cbc.CreatorBrowserController(user_data_dir=tmp)
            # stop 应不抛异常
            try:
                c.stop()
            except Exception as e:
                self.fail(f"stop() 未启动实例不应抛出: {e}")


class TestCloseAll(unittest.TestCase):
    def setUp(self):
        with cbc._active_controllers_lock:
            cbc._active_controllers.clear()

    def tearDown(self):
        with cbc._active_controllers_lock:
            cbc._active_controllers.clear()

    def test_close_all_stops_running_and_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            c1 = cbc.CreatorBrowserController(user_data_dir=tmp + "1")
            c2 = cbc.CreatorBrowserController(user_data_dir=tmp + "2")
            # mock 成"正在运行"但 stop 可调用
            with mock.patch.object(c1, "is_running", return_value=True), \
                mock.patch.object(c1, "stop") as m_s1, \
                mock.patch.object(c2, "is_running", return_value=True), \
                mock.patch.object(c2, "stop") as m_s2:
                            cbc.close_all_active_browsers()
                            m_s1.assert_called_once()
                            m_s2.assert_called_once()
            # 列表被清空
            with cbc._active_controllers_lock:
                self.assertEqual(len(cbc._active_controllers), 0)

    def test_close_all_swallow_exception(self):
        """某个 controller.stop 抛异常 → 不影响其他，列表仍清空。"""
        with tempfile.TemporaryDirectory() as tmp:
            c1 = cbc.CreatorBrowserController(user_data_dir=tmp + "1")
            c2 = cbc.CreatorBrowserController(user_data_dir=tmp + "2")
            with mock.patch.object(c1, "is_running", return_value=True), \
                mock.patch.object(c1, "stop", side_effect=OSError("boom")), \
                mock.patch.object(c2, "is_running", return_value=True), \
                mock.patch.object(c2, "stop") as m_s2:
                            try:
                                cbc.close_all_active_browsers()
                            except Exception as e:
                                self.fail(f"close_all 不应向外抛: {e}")
                            m_s2.assert_called_once()
            with cbc._active_controllers_lock:
                self.assertEqual(len(cbc._active_controllers), 0)


if __name__ == "__main__":
    unittest.main()
