"""tests/unit/test_product_miner.py — 产品挖掘统计测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "studio"))

from core.product_miner import count_mined_products, validate_mine_config


class TestCountMinedProducts(unittest.TestCase):
    """count_mined_products 挖掘统计测试。"""

    def test_empty_items(self):
        already, pending = count_mined_products([])
        self.assertEqual(already, 0)
        self.assertEqual(pending, 0)

    def test_all_mined(self):
        items = [
            {"features": "性能参数", "selling_points": "核心卖点"},
            {"features": "已挖掘", "selling_points": "热销"},
        ]
        already, pending = count_mined_products(items)
        self.assertEqual(already, 2)
        self.assertEqual(pending, 0)

    def test_none_mined(self):
        items = [
            {"features": "", "selling_points": ""},
            {"features": None, "selling_points": None},
            {},
        ]
        already, pending = count_mined_products(items)
        self.assertEqual(already, 0)
        self.assertEqual(pending, 3)

    def test_mixed(self):
        items = [
            {"features": "参数", "selling_points": "卖点"},
            {"features": "", "selling_points": "卖点"},
            {"features": "参数", "selling_points": ""},
            {"features": "", "selling_points": ""},
        ]
        already, pending = count_mined_products(items)
        self.assertEqual(already, 1)  # only first has both features and selling_points
        self.assertEqual(pending, 3)

    def test_whitespace_only_mined(self):
        items = [
            {"features": "   ", "selling_points": "   "},
        ]
        already, pending = count_mined_products(items)
        self.assertEqual(already, 0)
        self.assertEqual(pending, 1)


class TestValidateMineConfig(unittest.TestCase):
    """validate_mine_config 配置验证测试。"""

    def test_valid_config(self):
        errors = validate_mine_config(model="deepseek-chat", server_url="http://localhost:8000")
        self.assertEqual(errors, [])

    def test_no_model(self):
        errors = validate_mine_config(model="", server_url="http://localhost:8000")
        self.assertEqual(len(errors), 1)
        self.assertIn("模型", errors[0])

    def test_no_server(self):
        errors = validate_mine_config(model="deepseek-chat", server_url="")
        self.assertEqual(len(errors), 1)
        self.assertIn("服务端", errors[0])

    def test_both_missing(self):
        errors = validate_mine_config(model="", server_url="")
        self.assertEqual(len(errors), 2)

    def test_default_model(self):
        errors = validate_mine_config(model="deepseek-chat", server_url="http://s")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
