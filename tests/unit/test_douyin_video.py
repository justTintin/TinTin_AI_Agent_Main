"""douyin_video 测试（封装层逻辑）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from core import douyin_video  # noqa: E402


class TestGetDouyinOriginVideo(unittest.TestCase):
    AWEME_ID = "7350291791045790991"

    @mock.patch.object(douyin_video, "parse_video_detail_json")
    @mock.patch.object(douyin_video, "PlaywrightFetcher")
    def test_success_path(self, m_cls, m_parse):
        """fetcher.get_video_json 返回非空 → 调用 parse_video_detail_json → 返回结果。"""
        fake_data = {"aweme_detail": {"aweme_id": self.AWEME_ID}}
        m_cls.return_value.get_video_json.return_value = fake_data
        expected = {"aweme_id": self.AWEME_ID, "title": "hello"}
        m_parse.return_value = expected

        result = douyin_video.get_douyin_origin_video(aweme_id=self.AWEME_ID)

        self.assertEqual(result, expected)
        # PlaywrightFetcher 构造参数 headless=True
        m_cls.assert_called_once_with(headless=True)
        m_cls.return_value.get_video_json.assert_called_once_with(aweme_id=self.AWEME_ID)
        m_parse.assert_called_once_with(aweme_id=self.AWEME_ID, json_res=fake_data)

    @mock.patch.object(douyin_video, "parse_video_detail_json")
    @mock.patch.object(douyin_video, "PlaywrightFetcher")
    def test_fetcher_returns_none(self, m_cls, m_parse):
        """fetcher 没拿到数据 → 返回 False，不调 parser。"""
        m_cls.return_value.get_video_json.return_value = None
        result = douyin_video.get_douyin_origin_video(aweme_id="abc")
        self.assertIs(result, False)
        m_parse.assert_not_called()

    @mock.patch.object(douyin_video, "parse_video_detail_json")
    @mock.patch.object(douyin_video, "PlaywrightFetcher")
    def test_fetcher_returns_empty_dict(self, m_cls, m_parse):
        """fetcher 返回 {}（falsy，但类型是 dict）→ 应走 falsy 分支返回 False。"""
        m_cls.return_value.get_video_json.return_value = {}
        result = douyin_video.get_douyin_origin_video(aweme_id="abc")
        self.assertIs(result, False)
        m_parse.assert_not_called()

    @mock.patch.object(douyin_video, "PlaywrightFetcher")
    def test_exception_swallowed(self, m_cls):
        """任何异常被 logger 记录并返回 False，不抛出。"""
        m_cls.side_effect = RuntimeError("browser not installed")
        try:
            result = douyin_video.get_douyin_origin_video(aweme_id="abc")
        except Exception as e:
            self.fail(f"不应抛出异常，实际 {type(e).__name__}: {e}")
        self.assertIs(result, False)


if __name__ == "__main__":
    unittest.main()
