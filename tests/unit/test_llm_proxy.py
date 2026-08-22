"""tests/unit/test_llm_proxy.py — LLM 代理客户端测试。"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()


class _Resp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text or (str(data) if data else "")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestReadConfig(unittest.TestCase):
    def test_read_config_file(self):
        from utils.llm_proxy import _read_config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"compute_server_url": "http://srv", "llm_model": "test-model"}')
            cfg_path = f.name
        try:
            with mock.patch("config.paths.AI_CONFIG_FILE", cfg_path):
                cfg = _read_config()
            self.assertEqual(cfg.get("compute_server_url"), "http://srv")
            self.assertEqual(cfg.get("llm_model"), "test-model")
        finally:
            os.unlink(cfg_path)

    def test_read_config_missing_file(self):
        from utils.llm_proxy import _read_config
        with mock.patch("config.paths.AI_CONFIG_FILE", "/nonexistent/path/config.json"):
            cfg = _read_config()
        self.assertEqual(cfg, {})

    def test_read_config_invalid_json(self):
        from utils.llm_proxy import _read_config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            cfg_path = f.name
        try:
            with mock.patch("config.paths.AI_CONFIG_FILE", cfg_path):
                cfg = _read_config()
            self.assertEqual(cfg, {})
        finally:
            os.unlink(cfg_path)


class TestGetServerUrl(unittest.TestCase):
    def test_with_config(self):
        from utils.llm_proxy import _get_server_url
        with mock.patch("utils.llm_proxy._read_config", return_value={"compute_server_url": "http://srv:8000"}):
            url = _get_server_url()
        self.assertEqual(url, "http://srv:8000")

    def test_with_trailing_slash(self):
        from utils.llm_proxy import _get_server_url
        with mock.patch("utils.llm_proxy._read_config", return_value={"compute_server_url": "http://srv/"}):
            url = _get_server_url()
        self.assertEqual(url, "http://srv")

    def test_no_config(self):
        from utils.llm_proxy import _get_server_url
        with mock.patch("utils.llm_proxy._read_config", return_value={}):
            url = _get_server_url()
        self.assertEqual(url, "")


class TestGetDefaultModel(unittest.TestCase):
    def test_with_config(self):
        from utils.llm_proxy import _get_default_model
        with mock.patch("utils.llm_proxy._read_config", return_value={"llm_model": "custom-model"}):
            model = _get_default_model()
        self.assertEqual(model, "custom-model")

    def test_default_fallback(self):
        from utils.llm_proxy import _get_default_model
        with mock.patch("utils.llm_proxy._read_config", return_value={}):
            model = _get_default_model()
        self.assertEqual(model, "deepseek-v4-flash")


class TestLlmChat(unittest.TestCase):
    def test_success_choices_format(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {
                "choices": [{"message": {"content": "hello world"}}]
            })
            result = llm_chat("system", "user")
        self.assertEqual(result, "hello world")

    def test_success_content_format(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "plain text"})
            result = llm_chat("system", "user")
        self.assertEqual(result, "plain text")

    def test_success_result_format(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"result": "result text"})
            result = llm_chat("system", "user")
        self.assertEqual(result, "result text")

    def test_no_server_url(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value=""):
            with self.assertRaises(RuntimeError) as ctx:
                llm_chat("system", "user")
            self.assertIn("未配置服务端地址", str(ctx.exception))

    def test_http_error(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(500, text="server error")
            with self.assertRaises(RuntimeError):
                llm_chat("system", "user")

    def test_model_default(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy._get_default_model", return_value="default-m"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "ok"})
            llm_chat("system", "user", model="")
            call_kwargs = m_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["model"], "default-m")

    def test_model_explicit(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "ok"})
            llm_chat("system", "user", model="gpt-4")
            call_kwargs = m_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["model"], "gpt-4")

    def test_max_tokens(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "ok"})
            llm_chat("system", "user", max_tokens=100)
            call_kwargs = m_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["max_tokens"], 100)

    def test_max_tokens_zero_not_sent(self):
        from utils.llm_proxy import llm_chat
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "ok"})
            llm_chat("system", "user", max_tokens=0)
            call_kwargs = m_post.call_args[1]
            self.assertNotIn("max_tokens", call_kwargs["json"])


class TestLlmChatMessages(unittest.TestCase):
    def test_success(self):
        from utils.llm_proxy import llm_chat_messages
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {
                "choices": [{"message": {"content": "response"}}]
            })
            messages = [{"role": "user", "content": "hi"}]
            result = llm_chat_messages(messages)
        self.assertEqual(result, "response")

    def test_payload_structure(self):
        from utils.llm_proxy import llm_chat_messages
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_post") as m_post:
            m_post.return_value = _Resp(200, {"content": "ok"})
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
            ]
            llm_chat_messages(messages)
            call_kwargs = m_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["messages"], messages)

    def test_no_server_url(self):
        from utils.llm_proxy import llm_chat_messages
        with mock.patch("utils.llm_proxy._get_server_url", return_value=""):
            with self.assertRaises(RuntimeError):
                llm_chat_messages([{"role": "user", "content": "hi"}])


class TestLlmChatJson(unittest.TestCase):
    def test_valid_json(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = '{"key": "value"}'
            result = llm_chat_json("sys", "user")
        self.assertEqual(result, {"key": "value"})

    def test_code_block_json(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = '```json\n{"key": "value"}\n```'
            result = llm_chat_json("sys", "user")
        self.assertEqual(result, {"key": "value"})

    def test_json_with_surrounding_text(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = 'Here is the result: {"key": "value"} as requested.'
            result = llm_chat_json("sys", "user")
        self.assertEqual(result, {"key": "value"})

    def test_empty_response(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = ""
            result = llm_chat_json("sys", "user")
        self.assertIsNone(result)

    def test_invalid_json(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = "not json at all"
            result = llm_chat_json("sys", "user")
        self.assertIsNone(result)

    def test_array_json(self):
        from utils.llm_proxy import llm_chat_json
        with mock.patch("utils.llm_proxy.llm_chat") as m_chat:
            m_chat.return_value = '[1, 2, 3]'
            result = llm_chat_json("sys", "user")
        self.assertEqual(result, [1, 2, 3])


class TestListLlmModels(unittest.TestCase):
    def test_success(self):
        from utils.llm_proxy import list_llm_models
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_get") as m_get:
            m_get.return_value = _Resp(200, {
                "models": [{"id": "m1"}, {"id": "m2"}]
            })
            models = list_llm_models()
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["id"], "m1")

    def test_no_server(self):
        from utils.llm_proxy import list_llm_models
        with mock.patch("utils.llm_proxy._get_server_url", return_value=""):
            models = list_llm_models()
        self.assertEqual(models, [])

    def test_http_error(self):
        from utils.llm_proxy import list_llm_models
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_get") as m_get:
            m_get.return_value = _Resp(500)
            models = list_llm_models()
        self.assertEqual(models, [])

    def test_request_exception(self):
        from utils.llm_proxy import list_llm_models
        import requests
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_get", side_effect=requests.RequestException):
            models = list_llm_models()
        self.assertEqual(models, [])

    def test_models_key_missing(self):
        from utils.llm_proxy import list_llm_models
        with mock.patch("utils.llm_proxy._get_server_url", return_value="http://srv"), \
             mock.patch("utils.llm_proxy.resilient_get") as m_get:
            m_get.return_value = _Resp(200, {})
            models = list_llm_models()
        self.assertEqual(models, [])
