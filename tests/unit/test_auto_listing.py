"""自动上架：数据包校验、sku.xlsx 解析、ZIP 导入。"""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils.auto_listing import validation  # noqa: E402
from utils.auto_listing.validation import ValidationError, inspect_package, prepare_package  # noqa: E402


def make_png(width=1, height=1):
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class TestAutoListingValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auto_listing_test_")
        self.pkg = os.path.join(self.tmp, "桔柚-测试上架")
        os.makedirs(os.path.join(self.pkg, "主图"))
        os.makedirs(os.path.join(self.pkg, "详情页"))
        os.makedirs(os.path.join(self.pkg, "sku图"))
        with open(os.path.join(self.pkg, "主图", "主图_1.png"), "wb") as f:
            f.write(make_png(1, 1))
        with open(os.path.join(self.pkg, "详情页", "详情图片_01.png"), "wb") as f:
            f.write(make_png(1, 1))
        with open(os.path.join(self.pkg, "sku图", "桔柚高功率-5（12）.png"), "wb") as f:
            f.write(make_png(1, 1))

        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws1 = wb.active
            ws1.title = "SKU"
            ws1.append(["sku图片名", "商家编码", "品牌"])
            ws1.append(["桔柚高功率-5（12）", "dyc-080", "桔柚"])
            ws2 = wb.create_sheet("属性")
            ws2.append(["字段", "商品标题"])
            ws2.append(["型号", "高功率-5"])
            ws2.append(["生产厂家", "桔柚工厂"])
            wb.save(os.path.join(self.pkg, "sku.xlsx"))
        except Exception as e:  # pragma: no cover
            self.fail(f"创建测试 xlsx 失败: {e}")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inspect_package_valid(self):
        info = inspect_package(self.pkg, os.path.basename(self.pkg), "juyou")
        self.assertEqual(info.shop_key, "juyou")
        self.assertEqual(info.title, "商品标题")
        self.assertEqual(info.brand, "桔柚")
        self.assertEqual(info.model, "高功率-5")
        self.assertEqual(len(info.skus), 1)
        self.assertEqual(info.skus[0].name, "桔柚高功率-5（12）")
        self.assertEqual(info.skus[0].merchant_code, "dyc-080")
        self.assertEqual(len(info.main_images), 1)
        self.assertEqual(len(info.detail_images), 1)
        self.assertEqual(len(info.sku_images), 1)

    def test_shop_mismatch_raises(self):
        with self.assertRaises(ValidationError):
            inspect_package(self.pkg, "错误店铺", "juyou")

    def test_missing_sku_dir_raises(self):
        shutil.rmtree(os.path.join(self.pkg, "sku图"))
        with self.assertRaises(ValidationError):
            inspect_package(self.pkg, os.path.basename(self.pkg), "juyou")

    def test_non_square_main_raises(self):
        with open(os.path.join(self.pkg, "主图", "主图_2.png"), "wb") as f:
            f.write(make_png(2, 1))
        with self.assertRaises(ValidationError):
            inspect_package(self.pkg, os.path.basename(self.pkg), "juyou")

    def test_prepare_package_from_zip(self):
        zip_path = os.path.join(self.tmp, "桔柚-测试上架.zip")
        old_sync = validation.AUTO_LISTING_SYNC_DIR
        validation.AUTO_LISTING_SYNC_DIR = os.path.join(self.tmp, "sync")
        try:
            with zipfile.ZipFile(zip_path, "w") as zf:
                for root, _dirs, files in os.walk(self.pkg):
                    for name in files:
                        full = os.path.join(root, name)
                        rel = os.path.relpath(full, self.tmp)
                        zf.write(full, rel)
            info = prepare_package(zip_path, "juyou")
            self.assertTrue(os.path.isfile(os.path.join(info.working_dir, "sku.xlsx")))
            self.assertEqual(len(info.skus), 1)
        finally:
            validation.AUTO_LISTING_SYNC_DIR = old_sync


if __name__ == "__main__":
    unittest.main()

