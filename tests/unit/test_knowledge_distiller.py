"""tests/unit/test_knowledge_distiller.py"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from utils.knowledge_distiller import (
    _parse_json,
    _sample_text,
    _tag_batch,
    _extract_style,
    run_distillation,
    SAMPLE_TEXT_CAP,
    MAX_GROUP_SAMPLES,
    TAG_BATCH,
    MIN_GROUP_SAMPLES,
)
from utils.my_knowledge_manager import (
    CONTENT_TYPE_OPTIONS,
    PRODUCT_CAT_OPTIONS,
    INDUSTRY_OPTIONS,
    REFERENCE_TYPE,
    STYLIZATION_TYPE,
    STYLE_DIMS,
    MyKnowledgeManager,
)


def make_sample(content="test content", creator="", source_url=""):
    return {
        "id": "test-id",
        "type": REFERENCE_TYPE,
        "content": content,
        "source": {"creator": creator, "url": source_url},
        "_style_tags": {},
    }


class TestParseJson(unittest.TestCase):
    """_parse_json — 纯函数测试。"""

    def test_parses_pure_json_array(self):
        result = _parse_json("[1, 2, 3]")
        self.assertEqual(result, [1, 2, 3])

    def test_parses_pure_json_object(self):
        result = _parse_json('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_parses_json_wrapped_in_code_blocks(self):
        text = "```json\n[1, 2, 3]\n```"
        result = _parse_json(text)
        self.assertEqual(result, [1, 2, 3])

    def test_extracts_json_from_surrounding_text(self):
        text = "Here is the result:\n[1, 2, 3]\nDone."
        result = _parse_json(text)
        self.assertEqual(result, [1, 2, 3])

    def test_extracts_object_from_surrounding_text(self):
        text = "before {\"a\": 1, \"b\": 2} after"
        result = _parse_json(text)
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_returns_none_for_empty_input(self):
        self.assertIsNone(_parse_json(None))
        self.assertIsNone(_parse_json(""))
        self.assertIsNone(_parse_json("   "))

    def test_returns_none_for_invalid_json(self):
        result = _parse_json("not valid json {{{")
        self.assertIsNone(result)

    def test_returns_none_when_no_json_found(self):
        result = _parse_json("hello world, no json here")
        self.assertIsNone(result)

    def test_handles_nested_json(self):
        text = '{"a": {"b": [1, 2, {"c": 3}]}}'
        result = _parse_json(text)
        self.assertEqual(result, {"a": {"b": [1, 2, {"c": 3}]}})

    def test_handles_nested_json_in_code_block(self):
        text = "```json\n{\"a\": {\"b\": [1]}}\n```"
        result = _parse_json(text)
        self.assertEqual(result, {"a": {"b": [1]}})


class TestSampleText(unittest.TestCase):
    """_sample_text — 纯函数测试。"""

    def test_returns_truncated_content(self):
        item = {"content": "a" * 300}
        result = _sample_text(item)
        self.assertEqual(len(result), SAMPLE_TEXT_CAP)
        self.assertEqual(result, "a" * SAMPLE_TEXT_CAP)

    def test_strips_newlines(self):
        item = {"content": "line1\nline2\nline3"}
        result = _sample_text(item)
        self.assertNotIn("\n", result)
        self.assertEqual(result, "line1 line2 line3")

    def test_returns_empty_for_missing_content(self):
        item = {}
        result = _sample_text(item)
        self.assertEqual(result, "")

    def test_returns_empty_for_empty_content(self):
        item = {"content": ""}
        result = _sample_text(item)
        self.assertEqual(result, "")

    def test_returns_empty_for_whitespace_only_content(self):
        item = {"content": "   \n  \n  "}
        result = _sample_text(item)
        self.assertEqual(result, "")

    def test_returns_truncated_when_exceeds_cap(self):
        item = {"content": "x" * (SAMPLE_TEXT_CAP + 50)}
        result = _sample_text(item)
        self.assertEqual(len(result), SAMPLE_TEXT_CAP)
        self.assertEqual(result, "x" * SAMPLE_TEXT_CAP)

    def test_short_content_unchanged(self):
        item = {"content": "hello world"}
        result = _sample_text(item)
        self.assertEqual(result, "hello world")


class TestTagBatch(unittest.TestCase):
    """_tag_batch — 打标函数测试（mock _chat 和 _parse_json）。"""

    def test_returns_tags_aligned_with_batch(self):
        batch = [make_sample("c1"), make_sample("c2"), make_sample("c3")]
        parsed = [
            {"i": 0, "content_type": ["科技类"], "product_cat": ["AI类"], "industry": ["科技类"]},
            {"i": 1, "content_type": ["科普类"], "product_cat": [], "industry": []},
            {"i": 2, "content_type": [], "product_cat": ["笔电"], "industry": []},
        ]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["content_type"], ["科技类"])
        self.assertEqual(result[0]["product_cat"], ["AI类"])
        self.assertEqual(result[0]["industry"], ["科技类"])
        self.assertEqual(result[1]["content_type"], ["科普类"])
        self.assertEqual(result[1]["product_cat"], [])
        self.assertEqual(result[2]["product_cat"], ["笔电"])

    def test_filters_invalid_tag_values(self):
        batch = [make_sample("c1")]
        parsed = [
            {"i": 0, "content_type": ["科技类", "INVALID_TYPE"],
             "product_cat": ["笔电", "INVALID_CAT"],
             "industry": ["科技类", "INVALID_IND"]}
        ]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(result[0]["content_type"], ["科技类"])
        self.assertEqual(result[0]["product_cat"], ["笔电"])
        self.assertEqual(result[0]["industry"], ["科技类"])

    def test_handles_empty_batch(self):
        batch = []
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "[]"
            mock_parse.return_value = []
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(result, [])

    def test_handles_llm_returning_fewer_items(self):
        batch = [make_sample("c1"), make_sample("c2"), make_sample("c3")]
        parsed = [
            {"i": 0, "content_type": ["科技类"], "product_cat": [], "industry": []},
        ]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["content_type"], ["科技类"])
        self.assertEqual(result[1]["content_type"], [])
        self.assertEqual(result[2]["content_type"], [])

    def test_handles_malformed_data(self):
        batch = [make_sample("c1"), make_sample("c2")]
        parsed = "not a list"
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"content_type": [], "product_cat": [], "industry": []})
        self.assertEqual(result[1], {"content_type": [], "product_cat": [], "industry": []})

    def test_handles_non_dict_elements_in_list(self):
        batch = [make_sample("c1"), make_sample("c2")]
        parsed = ["string_element", 42, None]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"content_type": [], "product_cat": [], "industry": []})
        self.assertEqual(result[1], {"content_type": [], "product_cat": [], "industry": []})

    def test_handles_missing_i_key(self):
        batch = [make_sample("c1"), make_sample("c2")]
        parsed = [
            {"content_type": ["科技类"], "product_cat": [], "industry": []},
            {"i": 1, "content_type": ["科普类"], "product_cat": [], "industry": []},
        ]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = parsed
            cfg = {"model": "test"}
            result = _tag_batch(cfg, batch)
        self.assertEqual(result[0]["content_type"], [])
        self.assertEqual(result[1]["content_type"], ["科普类"])

    def test_calls_chat_with_correct_temperature(self):
        batch = [make_sample("c1")]
        with patch("utils.knowledge_distiller._chat") as mock_chat, \
             patch("utils.knowledge_distiller._parse_json") as mock_parse:
            mock_chat.return_value = "ignored"
            mock_parse.return_value = []
            cfg = {"model": "test"}
            _tag_batch(cfg, batch)
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args[1]
        self.assertEqual(call_kwargs.get("temperature"), 0.2)


class TestExtractStyle(unittest.TestCase):
    """_extract_style — 风格提炼测试（mock _chat）。"""

    def test_returns_llm_output(self):
        samples = [make_sample("test content")]
        with patch("utils.knowledge_distiller._chat") as mock_chat:
            mock_chat.return_value = "① 开头钩子：用数字冲击\n② 语气口吻：激情"
            cfg = {"model": "test"}
            result = _extract_style(cfg, "account", "test_creator", samples)
        self.assertEqual(result, "① 开头钩子：用数字冲击\n② 语气口吻：激情")

    def test_passes_correct_dimension_label(self):
        samples = [make_sample("test content")]
        with patch("utils.knowledge_distiller._chat") as mock_chat:
            mock_chat.return_value = "style output"
            cfg = {"model": "test"}
            _extract_style(cfg, "account", "test_creator", samples)
        mock_chat.assert_called_once()
        system_arg = mock_chat.call_args[0][1]
        self.assertIn("账号风格", system_arg)
        self.assertIn("test_creator", system_arg)

    def test_passes_correct_dim_label_content_type(self):
        samples = [make_sample("test")]
        with patch("utils.knowledge_distiller._chat") as mock_chat:
            mock_chat.return_value = "style"
            cfg = {"model": "test"}
            _extract_style(cfg, "content_type", "科技类", samples)
        system_arg = mock_chat.call_args[0][1]
        self.assertIn("内容类型", system_arg)
        self.assertIn("科技类", system_arg)

    def test_limits_samples_to_max_group_samples(self):
        samples = [make_sample(f"content {i}") for i in range(MAX_GROUP_SAMPLES + 10)]
        with patch("utils.knowledge_distiller._chat") as mock_chat:
            mock_chat.return_value = "style output"
            cfg = {"model": "test"}
            _extract_style(cfg, "account", "test_creator", samples)
        user_arg = mock_chat.call_args[0][2]
        self.assertIn(f"共 {len(samples)} 条样本", user_arg)
        line_count = [l for l in user_arg.split("\n") if l.startswith("- ")]
        self.assertEqual(len(line_count), MAX_GROUP_SAMPLES)

    def test_includes_sample_count_in_user_prompt(self):
        samples = [make_sample(f"c{i}") for i in range(5)]
        with patch("utils.knowledge_distiller._chat") as mock_chat:
            mock_chat.return_value = "style"
            cfg = {"model": "test"}
            _extract_style(cfg, "industry", "科技类", samples)
        user_arg = mock_chat.call_args[0][2]
        self.assertIn("共 5 条样本", user_arg)


class MockKnowledgeManager:
    """run_distillation 用的简易 manager mock。"""

    def __init__(self, items=None):
        self.items = items or []

    def all_items(self):
        return list(self.items)

    def save(self):
        pass


class TestRunDistillation(unittest.TestCase):
    """run_distillation — 主流程测试。"""

    def test_returns_error_when_model_not_configured(self):
        manager = MockKnowledgeManager()
        cfg = {}
        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertIn("未配置 LLM 模型", msg)

    def test_returns_error_when_no_reference_samples(self):
        manager = MockKnowledgeManager(items=[
            {"id": "1", "type": "其他", "content": "not a reference"},
        ])
        cfg = {"model": "test-model"}
        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertIn("没有可提炼", msg)

    def test_returns_error_when_samples_have_no_content(self):
        manager = MockKnowledgeManager(items=[
            make_sample(content=""),
            make_sample(content="   "),
        ])
        cfg = {"model": "test-model"}
        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertIn("没有可提炼", msg)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_successfully_processes_all_four_dimensions(self, mock_tag, mock_style):
        samples = [
            make_sample("tech content", creator="alice", source_url="url1"),
            make_sample("code content", creator="bob", source_url="url2"),
            make_sample("AI news", creator="alice", source_url="url3"),
            make_sample("finance tip", creator="charlie", source_url="url4"),
            make_sample("laptop review", creator="dave", source_url="url5"),
            make_sample("finance news", creator="eve", source_url="url6"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": ["科技类"], "product_cat": ["AI类"], "industry": ["科技类"]},
            {"content_type": ["科技类"], "product_cat": ["笔电"], "industry": []},
            {"content_type": ["科技类"], "product_cat": ["AI类"], "industry": ["科技类"]},
            {"content_type": [], "product_cat": [], "industry": ["财经类"]},
            {"content_type": ["科技类"], "product_cat": ["笔电"], "industry": []},
            {"content_type": [], "product_cat": [], "industry": ["财经类"]},
        ]
        mock_style.return_value = "① 开头钩子：数字冲击\n② 语气口吻：专业"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(updated, 0)
        self.assertGreater(created, 0)
        self.assertIn("风格化提炼完成", msg)

        dims_created = {(it["dim"], it["dim_value"])
                        for it in manager.items if it.get("distilled")}
        self.assertIn(("account", "alice"), dims_created)
        self.assertIn(("account", "bob"), dims_created)
        self.assertIn(("account", "charlie"), dims_created)
        self.assertIn(("account", "dave"), dims_created)
        self.assertIn(("account", "eve"), dims_created)
        self.assertIn(("content_type", "科技类"), dims_created)
        self.assertIn(("product_cat", "AI类"), dims_created)
        self.assertIn(("product_cat", "笔电"), dims_created)
        self.assertIn(("industry", "科技类"), dims_created)
        self.assertIn(("industry", "财经类"), dims_created)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_groups_items_by_creator(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
            make_sample("content 2", creator="alice"),
            make_sample("content 3", creator="bob"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": [], "product_cat": [], "industry": []},
            {"content_type": [], "product_cat": [], "industry": []},
            {"content_type": [], "product_cat": [], "industry": []},
        ]
        mock_style.return_value = "style output for alice\nalice style"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertGreater(created, 0)

        alice_entries = [it for it in manager.items
                         if it.get("dim") == "account"
                         and it.get("dim_value") == "alice"]
        self.assertEqual(len(alice_entries), 1)
        self.assertEqual(alice_entries[0]["source_count"], 2)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_creates_new_entries_for_new_dim_combos(self, mock_tag, mock_style):
        samples = [
            make_sample("tech content", creator="alice"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": ["科技类"], "product_cat": ["AI类"], "industry": ["科技类"]},
        ]
        mock_style.return_value = "style output"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertGreater(created, 0)
        self.assertEqual(updated, 0)

        stylized = [it for it in manager.items if it.get("distilled")]
        for it in stylized:
            self.assertIn("id", it)
            self.assertIn("name", it)
            self.assertEqual(it["type"], STYLIZATION_TYPE)
            self.assertTrue(it["distilled"])
            self.assertIn("score", it)
            self.assertIn("like_count", it)
            self.assertEqual(it["like_count"], 0)
            self.assertIn("dislike_count", it)
            self.assertEqual(it["dislike_count"], 0)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_updates_existing_entries(self, mock_tag, mock_style):
        existing_score = MyKnowledgeManager.initial_score(3)
        existing_entry = {
            "id": "existing-id",
            "name": "【账号风格】alice",
            "type": STYLIZATION_TYPE,
            "content": "old style content",
            "distilled": True,
            "dim": "account",
            "dim_value": "alice",
            "source_count": 3,
            "source_urls": [],
            "score": existing_score,
            "like_count": 0,
            "dislike_count": 0,
            "created_at": 1000,
            "updated_at": 1000,
        }
        samples = [
            make_sample("new content 1", creator="alice", source_url="url1"),
            make_sample("new content 2", creator="alice", source_url="url2"),
            make_sample("new content 3", creator="alice", source_url="url3"),
        ]
        all_items = samples + [existing_entry]
        manager = MockKnowledgeManager(items=all_items)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": [], "product_cat": [], "industry": []},
            {"content_type": [], "product_cat": [], "industry": []},
            {"content_type": [], "product_cat": [], "industry": []},
        ]
        mock_style.return_value = "updated style content"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertGreater(updated, 0)
        self.assertIn("更新", msg)

        self.assertEqual(existing_entry["content"], "updated style content")
        self.assertEqual(existing_entry["source_count"], 3)
        self.assertEqual(existing_entry["type"], STYLIZATION_TYPE)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_handles_llm_tag_failure_gracefully(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
            make_sample("content 2", creator="bob"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.side_effect = Exception("LLM API error")
        mock_style.return_value = "style output"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertGreater(created, 0)
        self.assertIn("风格化提炼完成", msg)

        account_entries = [it for it in manager.items if it.get("dim") == "account"]
        self.assertGreaterEqual(len(account_entries), 1)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_handles_llm_style_failure_gracefully(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": ["科技类"], "product_cat": [], "industry": []},
        ]
        mock_style.side_effect = Exception("Style LLM error")

        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertIn("风格化提炼完成", msg)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_calls_progress_cb(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": [], "product_cat": [], "industry": []},
        ]
        mock_style.return_value = "style output"

        progress_messages = []

        def progress_cb(msg):
            progress_messages.append(msg)

        run_distillation(manager, cfg, progress_cb=progress_cb)
        self.assertGreater(len(progress_messages), 1)
        self.assertTrue(any("打标" in m for m in progress_messages))
        self.assertTrue(any("提炼" in m for m in progress_messages))
        self.assertTrue(any("完成" in m for m in progress_messages))

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_handles_empty_style_response(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": [], "product_cat": [], "industry": []},
        ]
        mock_style.return_value = ""

        created, updated, msg = run_distillation(manager, cfg)
        self.assertEqual(created, 0)
        self.assertIn("风格化提炼完成", msg)

    @patch("utils.knowledge_distiller._extract_style")
    @patch("utils.knowledge_distiller._tag_batch")
    def test_filters_groups_below_minimum_threshold(self, mock_tag, mock_style):
        samples = [
            make_sample("content 1", creator="alice"),
            make_sample("content 2", creator="alice"),
        ]
        manager = MockKnowledgeManager(items=samples)
        cfg = {"model": "test-model"}

        mock_tag.return_value = [
            {"content_type": ["科技类"], "product_cat": [], "industry": []},
            {"content_type": [], "product_cat": [], "industry": []},
        ]
        mock_style.return_value = "style output"

        created, updated, msg = run_distillation(manager, cfg)
        self.assertGreater(created, 0)

        ct_entries = [it for it in manager.items
                      if it.get("dim") == "content_type"]
        self.assertEqual(len(ct_entries), 0)


if __name__ == "__main__":
    unittest.main()