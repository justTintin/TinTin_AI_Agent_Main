"""json_utils 测试（红）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import json_utils as ju  # noqa: E402


class TestDeepCopy(unittest.TestCase):
    def test_list_deep_copy_independent(self):
        original = [{"a": [1, 2]}, {"b": [3, 4]}]
        cloned = ju.deep_copy(original)
        self.assertEqual(cloned, original)
        # 修改 cloned 不影响 original
        cloned[0]["a"].append(99)
        self.assertEqual(original[0]["a"], [1, 2])

    def test_dict_deep_copy_independent(self):
        original = {"nodes": {"n1": {"inputs": [{"v": 1}]}}}
        cloned = ju.deep_copy(original)
        cloned["nodes"]["n1"]["inputs"][0]["v"] = 999
        self.assertEqual(original["nodes"]["n1"]["inputs"][0]["v"], 1)

    def test_primitives_passthrough(self):
        self.assertEqual(ju.deep_copy(42), 42)
        self.assertEqual(ju.deep_copy("hello"), "hello")
        self.assertEqual(ju.deep_copy(None), None)

    def test_workflow_json_deep_copy_pattern(self):
        """替代 json.loads(json.dumps(x)) 模式的等价性验证。"""
        wf = {"1": {"class_type": "CLIPTextEncode",
                     "inputs": {"text": "a prompt", "clip": ["2", 0]}}}
        cloned = ju.deep_copy(wf)
        cloned["1"]["inputs"]["text"] = "changed"
        self.assertEqual(wf["1"]["inputs"]["text"], "a prompt")
        self.assertNotEqual(wf, cloned)


class TestToEditorText(unittest.TestCase):
    def test_dict_default(self):
        self.assertEqual(ju.to_editor_text({"a": 1}), '{\n  "a": 1\n}')

    def test_chinese_passthrough(self):
        s = ju.to_editor_text({"姓名": "张三"})
        self.assertIn("张三", s)
        self.assertNotIn("\\u5f20", s)  # 不允许 ASCII 转义

    def test_custom_indent(self):
        self.assertEqual(ju.to_editor_text({"a": 1}, indent=4),
                         '{\n    "a": 1\n}')

    def test_list(self):
        self.assertEqual(ju.to_editor_text([1, 2, 3]), "[\n  1,\n  2,\n  3\n]")

    def test_primitives(self):
        self.assertEqual(ju.to_editor_text("x"), '"x"')
        self.assertEqual(ju.to_editor_text(None), "null")
        self.assertEqual(ju.to_editor_text(True), "true")


class TestFromEditorText(unittest.TestCase):
    def test_valid_dict(self):
        self.assertEqual(ju.from_editor_text('{"a": 1}'), {"a": 1})

    def test_valid_list(self):
        self.assertEqual(ju.from_editor_text('[1, 2]'), [1, 2])

    def test_invalid_returns_default_none(self):
        self.assertIsNone(ju.from_editor_text("{not valid"))

    def test_invalid_returns_custom_default(self):
        sentinel = {"items": []}
        self.assertIs(ju.from_editor_text("bad json", default=sentinel), sentinel)

    def test_whitespace_tolerant(self):
        self.assertEqual(ju.from_editor_text('  \n{"a":1}\n  '), {"a": 1})

    def test_empty_string_returns_default(self):
        self.assertIsNone(ju.from_editor_text(""))
        self.assertIsNone(ju.from_editor_text("    "))


class TestCompactText(unittest.TestCase):
    def test_dict_compact_no_indent(self):
        self.assertEqual(ju.compact_text({"a": 1}), '{"a": 1}')

    def test_list_compact(self):
        self.assertEqual(ju.compact_text([1, 2, 3]), "[1, 2, 3]")

    def test_nested_compact(self):
        self.assertEqual(ju.compact_text({"a": [1, {"b": 2}]}),
                         '{"a": [1, {"b": 2}]}')

    def test_chinese_passthrough(self):
        s = ju.compact_text({"姓名": "张三"})
        self.assertIn("张三", s)
        self.assertNotIn("\\u5f20", s)

    def test_differs_from_to_editor_text(self):
        self.assertNotIn("\n", ju.compact_text({"a": 1}))
        self.assertIn("\n", ju.to_editor_text({"a": 1}))

    def test_primitives(self):
        self.assertEqual(ju.compact_text("x"), '"x"')
        self.assertEqual(ju.compact_text(None), "null")
        self.assertEqual(ju.compact_text(True), "true")
        self.assertEqual(ju.compact_text(42), "42")


class TestParseJsonDefault(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(ju.parse_json_default(None), "")

    def test_dict_returns_editor_text(self):
        self.assertEqual(ju.parse_json_default({"a": 1}),
                         ju.to_editor_text({"a": 1}))

    def test_list_returns_editor_text(self):
        self.assertEqual(ju.parse_json_default([1, 2]),
                         ju.to_editor_text([1, 2]))

    def test_valid_json_str_returns_as_is(self):
        s = '{"a": 1}'
        self.assertEqual(ju.parse_json_default(s), s)

    def test_invalid_json_str_returns_as_is(self):
        s = "not a json"
        self.assertEqual(ju.parse_json_default(s), s)

    def test_empty_str_returns_as_is(self):
        self.assertEqual(ju.parse_json_default(""), "")

    def test_other_types_returns_str(self):
        self.assertEqual(ju.parse_json_default(42), "42")
        self.assertEqual(ju.parse_json_default(3.14), "3.14")
        self.assertEqual(ju.parse_json_default(True), "True")


if __name__ == "__main__":
    unittest.main()
