"""tests/unit/test_agent_router.py — 智能体路由与编排测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()


class TestKeywordRoute(unittest.TestCase):
    """_keyword_route 关键词路由测试。"""

    def test_match_first_keyword(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("我想做一个一键成片")
        self.assertEqual(result["page"], 33)
        self.assertEqual(result["intent"], "成片")

    def test_match_voice_clone(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("帮我做声音克隆")
        self.assertEqual(result["page"], 20)
        self.assertEqual(result["intent"], "声音")

    def test_match_cover(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("生成一个封面")
        self.assertEqual(result["page"], 32)
        self.assertEqual(result["intent"], "封面")

    def test_match_mg_animation(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("做一个MG动画")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 3)
        self.assertEqual(result["intent"], "mg动画")

    def test_match_hot_clip(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("直播切片")
        self.assertEqual(result["page"], 18)

    def test_match_with_english_mg(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("做MG动画")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 3)

    def test_match_agent_script(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("用数字人做一个口播")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 2)

    def test_match_material_generation(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("生成一些素材")
        self.assertEqual(result["page"], 38)
        self.assertEqual(result["intent"], "素材")

    def test_match_product_image(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("生成产品图")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 1)

    def test_default_fallback(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("完全不相关的内容xyzabc")
        self.assertEqual(result["page"], 33)
        self.assertEqual(result["tab"], None)
        self.assertEqual(result["intent"], "一键成片")
        self.assertFalse(result["multi_agent"])

    def test_empty_text(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("")
        self.assertEqual(result["page"], 33)

    def test_substring_match(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("做一个直播相关的切片内容")
        self.assertEqual(result["page"], 18)

    def test_case_insensitive(self):
        from utils.agent_router import _keyword_route
        result = _keyword_route("做MG动画")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 3)


class TestRouteText(unittest.TestCase):
    """route_text 路由入口测试。"""

    def test_empty_text_default(self):
        from utils.agent_router import route_text
        result = route_text("")
        self.assertEqual(result["page"], 33)
        self.assertEqual(result["intent"], "一键成片")

    def test_none_text_default(self):
        from utils.agent_router import route_text
        result = route_text(None)
        self.assertEqual(result["page"], 33)

    def test_whitespace_text_default(self):
        from utils.agent_router import route_text
        result = route_text("   ")
        self.assertEqual(result["page"], 33)

    @mock.patch("utils.agent_router._llm_route")
    def test_llm_success(self, m_llm):
        from utils.agent_router import route_text
        m_llm.return_value = {"page": 33, "tab": None, "intent": "一键成片", "multi_agent": False}
        result = route_text("做一个视频")
        self.assertEqual(result["intent"], "一键成片")

    @mock.patch("utils.agent_router._llm_route")
    @mock.patch("utils.agent_router._keyword_route")
    def test_llm_fallback_to_keyword(self, m_kw, m_llm):
        from utils.agent_router import route_text
        m_llm.return_value = None
        m_kw.return_value = {"page": 20, "tab": None, "intent": "声音", "multi_agent": False}
        result = route_text("做声音克隆")
        self.assertEqual(result["page"], 20)
        m_kw.assert_called_once()

    @mock.patch("utils.agent_router._keyword_route")
    def test_skip_llm(self, m_kw):
        from utils.agent_router import route_text
        m_kw.return_value = {"page": 32, "tab": None, "intent": "封面", "multi_agent": False}
        result = route_text("做封面", use_llm=False)
        self.assertEqual(result["page"], 32)


class TestLlmRoute(unittest.TestCase):
    """_llm_route LLM 路由测试。"""

    def test_successful_route(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {"intent": "一键成片", "multi_agent": False}
            result = _llm_route("做一个视频")
        self.assertEqual(result["page"], 33)
        self.assertEqual(result["intent"], "一键成片")
        self.assertFalse(result["multi_agent"])

    def test_multi_agent_route(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {"intent": "数字人", "multi_agent": True}
            result = _llm_route("数字人口播带货")
        self.assertEqual(result["page"], 31)
        self.assertEqual(result["tab"], 2)
        self.assertTrue(result["multi_agent"])

    def test_unknown_intent_returns_none(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {"intent": "不存在的功能", "multi_agent": False}
            result = _llm_route("做一个未知功能")
        self.assertIsNone(result)

    def test_non_dict_returns_none(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = "not a dict"
            result = _llm_route("做一个视频")
        self.assertIsNone(result)

    def test_empty_intent_returns_none(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {"intent": "", "multi_agent": False}
            result = _llm_route("做一个视频")
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        from utils.agent_router import _llm_route
        with mock.patch("utils.llm_proxy.llm_chat_json", side_effect=RuntimeError("LLM error")):
            result = _llm_route("做一个视频")
        self.assertIsNone(result)


class TestBuildPlan(unittest.TestCase):
    """build_plan 智能体编排测试。"""

    def test_empty_text_returns_none(self):
        from utils.agent_router import build_plan
        result = build_plan("")
        self.assertIsNone(result)

    def test_none_text_returns_none(self):
        from utils.agent_router import build_plan
        result = build_plan(None)
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_no_server_caps_returns_none(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "local_cap", "executor": "local"},
        ]}
        result = build_plan("做一个视频")
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_empty_registry_returns_none(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {}
        result = build_plan("做一个视频")
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_successful_plan(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server", "description": "搜索素材"},
            {"id": "asr_transcribe", "name": "语音转写", "executor": "server", "description": "转写音频"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {
                "goal": "转写视频",
                "steps": [
                    {"id": "s1", "capability": "material_search", "params": {"query": "视频"}, "depends_on": [], "needs_user_input": False},
                    {"id": "s2", "capability": "asr_transcribe", "params": {"file_path": "test.mp4"}, "depends_on": ["s1"], "needs_user_input": False},
                ],
            }
            result = build_plan("帮我转写这个视频")
        self.assertIsNotNone(result)
        self.assertEqual(result["goal"], "转写视频")
        self.assertEqual(len(result["steps"]), 2)

    @mock.patch("utils.agent_client.get_registry")
    def test_plan_with_unknown_capability_rejected(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {
                "goal": "生成视频",
                "steps": [
                    {"id": "s1", "capability": "unknown_cap", "params": {}, "depends_on": [], "needs_user_input": False},
                ],
            }
            result = build_plan("生成视频")
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_llm_returns_non_dict_returns_none(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = "not a dict"
            result = build_plan("搜索素材")
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_llm_returns_empty_steps_returns_none(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {"goal": "test", "steps": []}
            result = build_plan("搜索素材")
        self.assertIsNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_llm_exception_returns_none(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json", side_effect=RuntimeError("LLM error")):
            result = build_plan("搜索素材")
        self.assertIsNone(result)

    def test_registry_from_param(self):
        from utils.agent_router import build_plan
        custom_registry = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {
                "goal": "搜索",
                "steps": [
                    {"id": "s1", "capability": "material_search", "params": {"query": "test"}, "depends_on": [], "needs_user_input": False},
                ],
            }
            result = build_plan("搜索", registry=custom_registry)
        self.assertIsNotNone(result)

    @mock.patch("utils.agent_client.get_registry")
    def test_invalid_step_structure_rejected(self, m_reg):
        from utils.agent_router import build_plan
        m_reg.return_value = {"capabilities": [
            {"id": "material_search", "name": "素材检索", "executor": "server"},
        ]}
        with mock.patch("utils.llm_proxy.llm_chat_json") as m_chat:
            m_chat.return_value = {
                "goal": "test",
                "steps": ["not a dict step"],
            }
            result = build_plan("搜索素材")
        self.assertIsNone(result)
