# -*- coding: utf-8 -*-
"""backup_manager：数据备份 zip 生成。"""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil
testutil.ensure_studio_on_path()

from utils import backup_manager as bm


class TestBackupManager(unittest.TestCase):
    def test_backup_creates_valid_zip_with_manifest(self):
        with tempfile.TemporaryDirectory(prefix="bak_test_") as tmp:
            out = os.path.join(tmp, "backup.zip")
            result = bm.backup(out_zip=out)
            self.assertEqual(result, out)
            self.assertTrue(os.path.isfile(out))
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIn("backup_manifest.json", names)
                manifest = zf.read("backup_manifest.json").decode("utf-8")
                self.assertIn("created", manifest)
                self.assertIn("items", manifest)

    def test_backup_excludes_outputs_by_default(self):
        with tempfile.TemporaryDirectory(prefix="bak_test_") as tmp:
            out = os.path.join(tmp, "backup.zip")
            bm.backup(out_zip=out, include_outputs=False)
            with zipfile.ZipFile(out) as zf:
                self.assertNotIn("outputs/", "\n".join(zf.namelist()))


if __name__ == "__main__":
    unittest.main()