"""brand_normalizer：品牌归一化。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import brand_normalizer as bn  # noqa: E402


class TestBrandNormalizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bn.reload_dictionary()
        cls.dict_path = bn._dict_path

    def test_dictionary_loaded(self):
        self.assertTrue(os.path.isfile(self.dict_path))
        self.assertTrue(len(bn._alias_to_canonical) > 0)

    def test_alias_maps_to_canonical(self):
        # 从字典取第一个品牌，验证其首个别名能归一到 canonical
        import json
        with open(self.dict_path, encoding="utf-8") as f:
            data = json.load(f)
        brands = data.get("brands", {})
        if not brands:
            self.skipTest("brand_dictionary 为空")
        key = next(iter(brands))
        entry = brands[key]
        canonical = entry.get("canonical", key)
        aliases = entry.get("aliases", [])
        self.assertEqual(bn.canonical_name(key), canonical)
        if aliases:
            self.assertEqual(bn.canonical_name(aliases[0]), canonical)

    def test_unknown_passes_through(self):
        self.assertEqual(bn.canonical_name("SomeUnknownBrandXYZ"), "SomeUnknownBrandXYZ")

    def test_empty_returns_same(self):
        self.assertIsNone(bn.canonical_name(None))
        self.assertEqual(bn.canonical_name("   "), "   ")

    def test_reload_idempotent(self):
        bn.reload_dictionary()
        self.assertTrue(len(bn._alias_to_canonical) > 0)


if __name__ == "__main__":
    unittest.main()
