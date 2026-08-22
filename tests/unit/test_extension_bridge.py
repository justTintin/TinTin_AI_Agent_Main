"""tests/unit/test_extension_bridge.py — 扩展桥接纯函数测试。"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()


class TestPlatformOf(unittest.TestCase):
    """_platform_of 平台识别测试。"""

    def test_douyin(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.douyin.com/video/123"), "抖音")

    def test_iesdouyin(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://iesdouyin.com/abc"), "抖音")

    def test_bilibili(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.bilibili.com/video/BV123"), "B站")

    def test_b23(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://b23.tv/abc"), "B站")

    def test_xiaohongshu(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.xiaohongshu.com/explore/abc"), "小红书")

    def test_xhslink(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://xhslink.com/abc"), "小红书")

    def test_youtube(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.youtube.com/watch?v=abc"), "YouTube")

    def test_youtu_be(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://youtu.be/abc"), "YouTube")

    def test_tiktok(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.tiktok.com/@user/video/123"), "TikTok")

    def test_kuaishou(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://www.kuaishou.com/abc"), "快手")

    def test_weibo(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://weibo.com/abc"), "微博")

    def test_weixin(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://weixin.qq.com/abc"), "微信")

    def test_channels_weixin(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://channels.weixin.qq.com/abc"), "微信")

    def test_unknown_platform(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://example.com/video/123"), "其他")

    def test_empty_url(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of(""), "其他")

    def test_jimeng_keyword(self):
        from utils.extension_bridge import _platform_of
        self.assertEqual(_platform_of("https://jimeng.com/abc"), "即梦")


class TestIsYoutube(unittest.TestCase):
    """_is_youtube YouTube 判断测试。"""

    def test_youtube_url(self):
        from utils.extension_bridge import _is_youtube
        self.assertTrue(_is_youtube("https://www.youtube.com/watch?v=abc"))

    def test_youtu_be_url(self):
        from utils.extension_bridge import _is_youtube
        self.assertTrue(_is_youtube("https://youtu.be/abc"))

    def test_non_youtube(self):
        from utils.extension_bridge import _is_youtube
        self.assertFalse(_is_youtube("https://www.bilibili.com/video/BV123"))

    def test_empty_urls(self):
        from utils.extension_bridge import _is_youtube
        self.assertFalse(_is_youtube(""))

    def test_youtube_in_page_url(self):
        from utils.extension_bridge import _is_youtube
        self.assertTrue(_is_youtube("https://cdn.example.com/video.mp4", page_url="https://www.youtube.com/watch?v=abc"))

    def test_youtube_in_referer(self):
        from utils.extension_bridge import _is_youtube
        self.assertTrue(_is_youtube("https://cdn.example.com/video.mp4", referer="https://www.youtube.com/watch?v=abc"))


class TestNormalizeProxy(unittest.TestCase):
    """_normalize_proxy 代理地址规整测试。"""

    def test_empty(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy(""), "")

    def test_none(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy(None), "")

    def test_host_port_only(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("127.0.0.1:1080"), "http://127.0.0.1:1080")

    def test_already_http(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("http://127.0.0.1:1080"), "http://127.0.0.1:1080")

    def test_already_https(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("https://127.0.0.1:1080"), "https://127.0.0.1:1080")

    def test_socks5(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("socks5://127.0.0.1:1080"), "socks5://127.0.0.1:1080")

    def test_socks5h(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("socks5h://127.0.0.1:1080"), "socks5h://127.0.0.1:1080")

    def test_with_whitespace(self):
        from utils.extension_bridge import _normalize_proxy
        self.assertEqual(_normalize_proxy("  127.0.0.1:1080  "), "http://127.0.0.1:1080")


class TestBuildDlEnv(unittest.TestCase):
    """_build_dl_env 下载环境变量构造测试。"""

    def test_no_proxy(self):
        from utils.extension_bridge import _build_dl_env
        env = _build_dl_env("")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            self.assertNotIn(key, env)

    def test_with_proxy(self):
        from utils.extension_bridge import _build_dl_env
        env = _build_dl_env("http://127.0.0.1:1080")
        self.assertEqual(env.get("HTTP_PROXY"), "http://127.0.0.1:1080")
        self.assertEqual(env.get("HTTPS_PROXY"), "http://127.0.0.1:1080")
        self.assertEqual(env.get("ALL_PROXY"), "http://127.0.0.1:1080")

    def test_normalizes_proxy(self):
        from utils.extension_bridge import _build_dl_env
        env = _build_dl_env("127.0.0.1:1080")
        self.assertEqual(env.get("HTTP_PROXY"), "http://127.0.0.1:1080")

    def test_removes_existing_proxy(self):
        from utils.extension_bridge import _build_dl_env
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://old-proxy:8080"}, clear=True):
            env = _build_dl_env("")
            self.assertNotIn("HTTP_PROXY", env)


class TestSanitizeFilename(unittest.TestCase):
    """_sanitize_filename 文件名清理测试。"""

    def test_normal_name(self):
        from utils.extension_bridge import _sanitize_filename
        self.assertEqual(_sanitize_filename("my_video"), "my_video")

    def test_special_chars(self):
        from utils.extension_bridge import _sanitize_filename
        result = _sanitize_filename('file/name:*?"<>|test')
        self.assertNotIn('/', result)
        self.assertNotIn('\\', result)
        self.assertNotIn(':', result)
        self.assertNotIn('*', result)
        self.assertNotIn('?', result)
        self.assertNotIn('"', result)
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
        self.assertNotIn('|', result)

    def test_trailing_dots(self):
        from utils.extension_bridge import _sanitize_filename
        self.assertEqual(_sanitize_filename("file..."), "file")

    def test_newlines(self):
        from utils.extension_bridge import _sanitize_filename
        result = _sanitize_filename("line1\r\nline2")
        self.assertNotIn('\r', result)
        self.assertNotIn('\n', result)

    def test_empty_after_sanitize(self):
        from utils.extension_bridge import _sanitize_filename
        result = _sanitize_filename("::::")
        self.assertEqual(result, "_")

    def test_long_name(self):
        from utils.extension_bridge import _sanitize_filename
        long_name = "a" * 200
        result = _sanitize_filename(long_name)
        self.assertLessEqual(len(result), 120)


class TestGuessExtension(unittest.TestCase):
    """_guess_extension 文件扩展名推断测试。"""

    def test_url_with_extension(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("https://example.com/video.mp4", ""), ".mp4")

    def test_url_with_jpg(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("https://example.com/image.jpg", ""), ".jpg")

    def test_url_without_extension(self):
        from utils.extension_bridge import _guess_extension
        result = _guess_extension("https://example.com/video/123", "video/mp4")
        self.assertEqual(result, ".mp4")

    def test_content_type_jpeg(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("", "image/jpeg"), ".jpg")

    def test_content_type_png(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("", "image/png"), ".png")

    def test_content_type_webm(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("", "video/webm"), ".webm")

    def test_content_type_mp3(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("", "audio/mpeg"), ".mp3")

    def test_content_type_with_params(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("", "video/mp4; charset=utf-8"), ".mp4")

    def test_no_info_fallback(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("https://example.com/video", ""), ".bin")

    def test_url_query_param_ignored(self):
        from utils.extension_bridge import _guess_extension
        self.assertEqual(_guess_extension("https://example.com/video.mp4?t=123", ""), ".mp4")


class TestDefaultConfig(unittest.TestCase):
    """default_config 默认配置测试。"""

    def test_default_values(self):
        from utils.extension_bridge import default_config, DEFAULT_PORT
        cfg = default_config()
        self.assertEqual(cfg["port"], DEFAULT_PORT)
        self.assertTrue(cfg["auto_start"])
        self.assertFalse(cfg["auto_subtitle"])
        self.assertEqual(cfg["proxy"], "")
        self.assertEqual(cfg["cookies_browser"], "")
        self.assertIn("save_dir", cfg)
        self.assertIn("server_scan_dir", cfg)
        self.assertIn("nas_sync_dir", cfg)


class TestLoadSaveConfig(unittest.TestCase):
    """load_config / save_config 配置读写测试。"""

    def test_load_default_when_no_file(self):
        from utils.extension_bridge import load_config
        with mock.patch("utils.extension_bridge._CONFIG_FILE", "/nonexistent/config.json"):
            cfg = load_config()
        self.assertIn("port", cfg)
        self.assertIn("save_dir", cfg)

    def test_load_invalid_json(self):
        from utils.extension_bridge import load_config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json{{{")
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge._CONFIG_FILE", cfg_path):
                cfg = load_config()
            self.assertIn("port", cfg)
        finally:
            os.unlink(cfg_path)

    def test_save_and_load(self):
        from utils.extension_bridge import load_config, save_config
        test_cfg = {"port": 51233, "save_dir": "/test/dir", "proxy": "http://test:1080"}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge._CONFIG_FILE", cfg_path):
                save_config(test_cfg)
                loaded = load_config()
            self.assertEqual(loaded["port"], 51233)
            self.assertEqual(loaded["save_dir"], "/test/dir")
            self.assertEqual(loaded["proxy"], "http://test:1080")
        finally:
            os.unlink(cfg_path)


class TestComputeServerUrl(unittest.TestCase):
    """_compute_server_url 服务端地址计算测试。"""

    def test_reads_config(self):
        from utils.extension_bridge import _compute_server_url
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"compute_server_url": "http://srv:8000"}')
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge.AI_CONFIG_FILE", cfg_path):
                url = _compute_server_url()
            self.assertEqual(url, "http://srv:8000")
        finally:
            os.unlink(cfg_path)

    def test_strips_trailing_slash(self):
        from utils.extension_bridge import _compute_server_url
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"compute_server_url": "http://srv:8000/"}')
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge.AI_CONFIG_FILE", cfg_path):
                url = _compute_server_url()
            self.assertEqual(url, "http://srv:8000")
        finally:
            os.unlink(cfg_path)

    def test_missing_config(self):
        from utils.extension_bridge import _compute_server_url
        with mock.patch("utils.extension_bridge.AI_CONFIG_FILE", "/nonexistent/ai_config.json"):
            url = _compute_server_url()
        self.assertEqual(url, "")

    def test_invalid_json(self):
        from utils.extension_bridge import _compute_server_url
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge.AI_CONFIG_FILE", cfg_path):
                url = _compute_server_url()
            self.assertEqual(url, "")
        finally:
            os.unlink(cfg_path)

    def test_empty_url_in_config(self):
        from utils.extension_bridge import _compute_server_url
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"compute_server_url": ""}')
            cfg_path = f.name
        try:
            with mock.patch("utils.extension_bridge.AI_CONFIG_FILE", cfg_path):
                url = _compute_server_url()
            self.assertEqual(url, "")
        finally:
            os.unlink(cfg_path)


class TestEnqueue(unittest.TestCase):
    """ExtensionBridge.enqueue 入队测试。"""

    def setUp(self):
        from utils.extension_bridge import ExtensionBridge
        self.bridge = ExtensionBridge()

    def test_enqueue_valid_url(self):
        task_id = self.bridge.enqueue({"url": "https://example.com/video.mp4", "media_type": "video"})
        self.assertTrue(task_id)
        self.assertTrue(task_id.startswith("t"))

    def test_enqueue_invalid_url(self):
        task_id = self.bridge.enqueue({"url": "ftp://example.com/video.mp4"})
        self.assertEqual(task_id, "")

    def test_enqueue_empty_url(self):
        task_id = self.bridge.enqueue({"url": ""})
        self.assertEqual(task_id, "")

    def test_enqueue_no_url(self):
        task_id = self.bridge.enqueue({})
        self.assertEqual(task_id, "")

    def test_enqueue_duplicate_url(self):
        item = {"url": "https://example.com/video.mp4"}
        id1 = self.bridge.enqueue(item)
        id2 = self.bridge.enqueue(item)
        self.assertTrue(id1)
        self.assertEqual(id2, "")

    def test_enqueue_sets_task(self):
        task_id = self.bridge.enqueue({"url": "https://example.com/video.mp4"})
        with self.bridge._dl_lock:
            task = self.bridge._dl_tasks.get(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["url"], "https://example.com/video.mp4")
        self.assertEqual(task["status"], "queued")

    def test_enqueue_with_title(self):
        task_id = self.bridge.enqueue({
            "url": "https://example.com/video.mp4",
            "page_title": "Test Video Title",
        })
        with self.bridge._dl_lock:
            task = self.bridge._dl_tasks.get(task_id)
        self.assertIn("Test Video Title", task["filename"])

    def test_enqueue_auto_increment_id(self):
        id1 = self.bridge.enqueue({"url": "https://example.com/video1.mp4"})
        id2 = self.bridge.enqueue({"url": "https://example.com/video2.mp4"})
        self.assertNotEqual(id1, id2)
