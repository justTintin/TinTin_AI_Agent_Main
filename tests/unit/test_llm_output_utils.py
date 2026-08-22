"""llm_output_utils 测试（红）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import llm_output_utils as lou  # noqa: E402


class TestExtractJsonBlock(unittest.TestCase):
    def test_plain_json_object(self):
        text = '{"name": "hello", "score": 95}'
        self.assertEqual(lou.extract_json_block(text),
                         {"name": "hello", "score": 95})

    def test_plain_json_array(self):
        text = '[{"a":1}, {"a":2}]'
        self.assertEqual(lou.extract_json_block(text), [{"a": 1}, {"a": 2}])

    def test_markdown_code_block_json(self):
        text = '好的分析结果如下：\n```json\n{"items": [1,2,3]}\n```\n如有疑问请回复。'
        self.assertEqual(lou.extract_json_block(text), {"items": [1, 2, 3]})

    def test_code_block_with_leading_newline(self):
        text = '```\n{"x": 1}\n```'
        self.assertEqual(lou.extract_json_block(text), {"x": 1})

    def test_non_json_code_block_fallback_regex_obj(self):
        text = '结论：\n```\n结果对象：{"ok": true, "v": 1}\n```\n'
        # 整个 code block 内容不是纯 JSON → 回退 regex 抓 {...}
        self.assertEqual(lou.extract_json_block(text), {"ok": True, "v": 1})

    def test_no_code_block_regex_object(self):
        text = '这里是一些说明，最终结论 {"foo": "bar"} 嵌入文本中。'
        self.assertEqual(lou.extract_json_block(text), {"foo": "bar"})

    def test_no_code_block_regex_array(self):
        text = '推荐三个片段：[[1, 2], [3, 4]]'
        self.assertEqual(lou.extract_json_block(text), [[1, 2], [3, 4]])

    def test_live_clip_array_pattern(self):
        """live_clip_page 用 [\\s\\S]* 抓 [ ... ]，里面可能有中文描述。"""
        text = '分析结果：[{"start":"00:10","end":"00:30","score":9.2},{"start":"01:00","end":"01:20"}] 以上是精彩片段。'
        res = lou.extract_json_block(text)
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["start"], "00:10")

    def test_nested_braces_object(self):
        text = '外层说明 {"level1": {"level2": 2}} 结尾'
        self.assertEqual(lou.extract_json_block(text),
                         {"level1": {"level2": 2}})

    def test_nested_braces_array(self):
        text = '列表=[[{"a":[1,2]}, {"b":[3,4]}]]'
        self.assertEqual(lou.extract_json_block(text),
                         [[{"a": [1, 2]}, {"b": [3, 4]}]])

    def test_empty_or_junk_returns_none(self):
        self.assertIsNone(lou.extract_json_block(""))
        self.assertIsNone(lou.extract_json_block("hello world no json"))
        self.assertIsNone(lou.extract_json_block("```not json```"))

    def test_chinese_in_json(self):
        text = '结果：```json\\n{"姓名": "张三", "得分": 99}\\n```'
        self.assertEqual(lou.extract_json_block(text),
                         {"姓名": "张三", "得分": 99})

    def test_top_level_value_only_not_regex(self):
        """如果没有 {} / [] 包围，则仅尝试 loads 纯文本；否则返回 None。"""
        self.assertIsNone(lou.extract_json_block("just a string"))


class TestSafeJsonParse(unittest.TestCase):
    def test_directly_parseable(self):
        self.assertEqual(lou.safe_json_parse('[1,2,3]'), [1, 2, 3])

    def test_fallback_to_extract_block(self):
        text = '预解析说明：{"k": "v"} 附言'
        # 整个 text loads 失败 → 回退 extract_json_block
        self.assertEqual(lou.safe_json_parse(text), {"k": "v"})

    def test_returns_none_when_impossible(self):
        self.assertIsNone(lou.safe_json_parse("hello world"))

    def test_ensure_ascii_not_needed_chinese(self):
        # 纯 JSON 字符串含中文
        self.assertEqual(lou.safe_json_parse('{"词": "云"}'), {"词": "云"})


class TestExtractFirst(unittest.TestCase):
    def test_extract_first_object(self):
        text = 'x {"a": 1} y {"b": 2}'
        self.assertEqual(lou.extract_first_object(text), {"a": 1})

    def test_extract_first_array(self):
        text = 'abc [1, 2] def [3]'
        self.assertEqual(lou.extract_first_array(text), [1, 2])

    def test_extract_object_none(self):
        self.assertIsNone(lou.extract_first_object(""))
        self.assertIsNone(lou.extract_first_object("no braces"))

    def test_extract_array_none(self):
        self.assertIsNone(lou.extract_first_array(""))


if __name__ == "__main__":
    unittest.main()
