"""PlaywrightFetcher 测试（mock Playwright，不启动真实浏览器）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core.browser_fetcher import PlaywrightFetcher  # noqa: E402


def _build_mock_pw(video_json=None, goto_raises=None):
    """构造 sync_playwright 上下文管理器的 mock 链。"""
    mock_pw_instance = mock.MagicMock()
    mock_browser = mock.MagicMock()
    mock_context = mock.MagicMock()
    mock_page = mock.MagicMock()

    # page.expect_response 返回一个上下文管理器，里面有 .value
    mock_resp_info = mock.MagicMock()
    mock_resp_value = mock.MagicMock()
    mock_resp_value.status = 200
    mock_resp_value.url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123"
    mock_resp_value.json.return_value = video_json or {"aweme_detail": {"aweme_id": "123"}}
    type(mock_resp_info).__enter__ = mock.Mock(return_value=mock_resp_info)
    type(mock_resp_info).__exit__ = mock.Mock(return_value=False)
    mock_page.expect_response.return_value = mock_resp_info

    # page.on("response", cb) → 模拟调用回调一次
    def _fire_on_response(evt, cb):
        if evt == "response":
            cb(mock_resp_value)
    mock_page.on = _fire_on_response

    if goto_raises:
        mock_page.goto.side_effect = goto_raises

    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context
    mock_pw_instance.chromium.launch.return_value = mock_browser

    # sync_playwright 本身是上下文管理器
    ctx = mock.MagicMock()
    type(ctx).__enter__ = mock.Mock(return_value=mock_pw_instance)
    type(ctx).__exit__ = mock.Mock(return_value=False)

    def _maker():
        return ctx
    return _maker, mock_browser, mock_context, mock_page


class TestPlaywrightFetcher(unittest.TestCase):
    AWEME_ID = "7350291791045790991"

    def test_headless_flag_passed(self):
        maker, browser, _, _ = _build_mock_pw()
        mock_pw = mock.MagicMock()
        mock_pw.chromium.launch.return_value = browser
        with mock.patch("core.browser_fetcher.sync_playwright") as m_sp:
            # sync_playwright() 返回一个上下文管理器，里面 __enter__ 返回 mock_pw
            ctx = mock.MagicMock()
            type(ctx).__enter__ = mock.Mock(return_value=mock_pw)
            type(ctx).__exit__ = mock.Mock(return_value=False)
            m_sp.return_value = ctx
            fetcher = PlaywrightFetcher(headless=False)
            fetcher.get_video_json(aweme_id=self.AWEME_ID)
        mock_pw.chromium.launch.assert_called_once()
        kwargs = mock_pw.chromium.launch.call_args.kwargs
        self.assertFalse(kwargs["headless"])

    def test_success_intercepts_aweme_detail(self):
        expected = {"aweme_detail": {"aweme_id": self.AWEME_ID, "desc": "ok"}}
        maker, browser, _, _ = _build_mock_pw(video_json=expected)
        with mock.patch("core.browser_fetcher.sync_playwright", maker):
            fetcher = PlaywrightFetcher(headless=True)
            result = fetcher.get_video_json(aweme_id=self.AWEME_ID, timeout=100)
        self.assertEqual(result, expected)
        # browser.close() 被调用（finally 中）
        browser.close.assert_called()

    def test_timeout_does_not_raise(self):
        """page.goto 或 expect_response 抛异常 → 异常被 catch，不向外抛，browser 一定会 close。"""
        maker, browser, _, _ = _build_mock_pw(
            goto_raises=TimeoutError("simulated timeout"))
        with mock.patch("core.browser_fetcher.sync_playwright", maker):
            fetcher = PlaywrightFetcher()
            try:
                fetcher.get_video_json(aweme_id="123", timeout=10)
            except Exception as e:
                self.fail(f"不应抛出: {type(e).__name__}: {e}")
        # 最终必须调用 browser.close()（资源释放关键）
        browser.close.assert_called()


if __name__ == "__main__":
    unittest.main()
