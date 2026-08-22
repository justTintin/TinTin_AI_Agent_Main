"""tests/unit/test_rustfs_manager.py"""
import os
import sys
import unittest
import tempfile
import json
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()

from utils import rustfs_manager as rfm
from utils.rustfs_manager import (
    _load_ai_config,
    _save_ai_config,
    get_rustfs_config,
    save_rustfs_config,
    _scan_media_files,
    list_objects,
    download_object,
    generate_presigned_url,
    upload_file,
    sync_directory_to_rustfs,
)
from unittest.mock import patch, MagicMock


def _patch_build_client(client=None, bucket="test-bucket"):
    if client is None:
        client = MagicMock()
    return patch.object(rfm, "_build_client", return_value=(client, bucket))


class TestLoadAiConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rustfs_test_")
        self.config_path = os.path.join(self.tmpdir, "ai_config.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_empty_dict_when_file_missing(self):
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", self.config_path):
            result = _load_ai_config()
        self.assertEqual(result, {})

    def test_returns_parsed_json_when_file_exists(self):
        data = {"rustfs_endpoint": "http://10.0.0.1:9000", "rustfs_bucket": "test"}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", self.config_path):
            result = _load_ai_config()
        self.assertEqual(result, data)

    def test_returns_empty_dict_on_invalid_json(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", self.config_path):
            result = _load_ai_config()
        self.assertEqual(result, {})

    def test_returns_empty_dict_on_oserror(self):
        bad_path = os.path.join(self.tmpdir, "no_such_dir", "config.json")
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", bad_path):
            result = _load_ai_config()
        self.assertEqual(result, {})


class TestSaveAiConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rustfs_test_")
        self.config_path = os.path.join(self.tmpdir, "ai_config.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_true_on_successful_save(self):
        data = {"rustfs_endpoint": "http://127.0.0.1:9000"}
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", self.config_path):
            result = _save_ai_config(data)
        self.assertTrue(result)
        with open(self.config_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), data)

    def test_returns_false_on_oserror(self):
        bad_path = os.path.join(self.tmpdir, "no_such_dir", "config.json")
        with patch("utils.rustfs_manager.AI_CONFIG_FILE", bad_path):
            result = _save_ai_config({"key": "val"})
        self.assertFalse(result)


class TestGetRustfsConfig(unittest.TestCase):
    def test_returns_defaults_when_config_empty(self):
        with patch("utils.rustfs_manager._load_ai_config", return_value={}):
            cfg = get_rustfs_config()
        self.assertEqual(cfg["endpoint"], "http://X.X.X.X:9000")
        self.assertEqual(cfg["access_key"], "rustfsadmin")
        self.assertEqual(cfg["secret_key"], "rustfssecret")
        self.assertEqual(cfg["bucket"], "materials")

    def test_returns_configured_values(self):
        fake_cfg = {
            "rustfs_endpoint": "http://10.0.0.5:9000",
            "rustfs_access_key": "mykey",
            "rustfs_secret_key": "mysecret",
            "rustfs_bucket": "mybucket",
        }
        with patch("utils.rustfs_manager._load_ai_config", return_value=fake_cfg):
            cfg = get_rustfs_config()
        self.assertEqual(cfg["endpoint"], "http://10.0.0.5:9000")
        self.assertEqual(cfg["access_key"], "mykey")
        self.assertEqual(cfg["secret_key"], "mysecret")
        self.assertEqual(cfg["bucket"], "mybucket")


class TestSaveRustfsConfig(unittest.TestCase):
    def test_calls_save_with_correct_fields(self):
        loaded = {"other_key": "keep"}
        saved = {}

        def fake_save(data):
            saved.update(data)
            return True

        with patch("utils.rustfs_manager._load_ai_config", return_value=loaded):
            with patch("utils.rustfs_manager._save_ai_config", side_effect=fake_save):
                result = save_rustfs_config("http://ep", "ak", "sk", "bk")

        self.assertTrue(result)
        self.assertEqual(saved["rustfs_endpoint"], "http://ep")
        self.assertEqual(saved["rustfs_access_key"], "ak")
        self.assertEqual(saved["rustfs_secret_key"], "sk")
        self.assertEqual(saved["rustfs_bucket"], "bk")
        self.assertEqual(saved["other_key"], "keep")

    def test_strips_whitespace_from_inputs(self):
        saved = {}

        def fake_save(data):
            saved.update(data)
            return True

        with patch("utils.rustfs_manager._load_ai_config", return_value={}):
            with patch("utils.rustfs_manager._save_ai_config", side_effect=fake_save):
                save_rustfs_config("  http://ep  ", " ak ", " sk ", " bk ")

        self.assertEqual(saved["rustfs_endpoint"], "http://ep")
        self.assertEqual(saved["rustfs_access_key"], "ak")
        self.assertEqual(saved["rustfs_secret_key"], "sk")
        self.assertEqual(saved["rustfs_bucket"], "bk")


class TestScanMediaFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rustfs_scan_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, *parts):
        fp = os.path.join(self.tmpdir, *parts)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as f:
            f.write("x")
        return fp

    def test_returns_only_media_files(self):
        self._touch("a.jpg")
        self._touch("b.png")
        self._touch("c.txt")
        self._touch("d.mp4")
        self._touch("e.mp3")
        self._touch("f.pdf")
        result = _scan_media_files(self.tmpdir, recursive=False)
        names = {f["name"] for f in result}
        self.assertEqual(names, {"a.jpg", "b.png", "d.mp4", "e.mp3"})

    def test_recursive_walks_subdirectories(self):
        self._touch("top.jpg")
        self._touch("sub1", "mid.png")
        self._touch("sub1", "sub2", "deep.mp4")
        self._touch("sub1", "notes.txt")
        result = _scan_media_files(self.tmpdir, recursive=True)
        names = {f["name"] for f in result}
        self.assertEqual(names, {"top.jpg", "mid.png", "deep.mp4"})

    def test_non_recursive_lists_top_level_only(self):
        self._touch("top.jpg")
        self._touch("sub", "nested.png")
        result = _scan_media_files(self.tmpdir, recursive=False)
        names = {f["name"] for f in result}
        self.assertEqual(names, {"top.jpg"})

    def test_returns_empty_list_for_empty_directory(self):
        result = _scan_media_files(self.tmpdir)
        self.assertEqual(result, [])

    def test_case_insensitive_extensions(self):
        self._touch("a.JPEG")
        self._touch("b.MP4")
        result = _scan_media_files(self.tmpdir, recursive=False)
        names = {f["name"] for f in result}
        self.assertEqual(names, {"a.JPEG", "b.MP4"})


class TestListObjects(unittest.TestCase):
    def test_returns_parsed_object_list_on_success(self):
        client = MagicMock()
        paginator = MagicMock()
        page1 = {
            "Contents": [
                {"Key": "dir/a.jpg", "Size": 1024, "LastModified": "2025-01-01T00:00:00Z"},
                {"Key": "dir/b.png", "Size": 2048, "LastModified": "2025-01-02T00:00:00Z"},
            ]
        }
        page2 = {"Contents": []}
        paginator.paginate.return_value = [page1, page2]
        client.get_paginator.return_value = paginator

        with _patch_build_client(client, "mybucket"):
            ok, objs = list_objects(prefix="dir/")

        self.assertTrue(ok)
        self.assertEqual(len(objs), 2)
        self.assertEqual(objs[0]["name"], "dir/a.jpg")
        self.assertEqual(objs[0]["size"], 1024)
        self.assertEqual(objs[0]["ext"], ".jpg")
        self.assertEqual(objs[1]["ext"], ".png")

    def test_returns_error_tuple_on_client_error(self):
        from botocore.exceptions import ClientError
        client = MagicMock()
        client.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "ListObjects",
        )
        with _patch_build_client(client):
            ok, msg = list_objects()
        self.assertFalse(ok)
        self.assertIn("AccessDenied", msg)

    def test_returns_error_tuple_on_general_exception(self):
        client = MagicMock()
        client.get_paginator.side_effect = RuntimeError("boom")
        with _patch_build_client(client):
            ok, msg = list_objects()
        self.assertFalse(ok)
        self.assertIn("boom", msg)

    def test_handles_prefix_filtering(self):
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        client.get_paginator.return_value = paginator

        with _patch_build_client(client):
            ok, objs = list_objects(prefix="images/", max_keys=100)

        self.assertTrue(ok)
        call_kwargs = paginator.paginate.call_args.kwargs
        self.assertEqual(call_kwargs["Prefix"], "images/")
        self.assertEqual(call_kwargs["Bucket"], "test-bucket")


class TestDownloadObject(unittest.TestCase):
    def test_downloads_to_specified_local_path(self):
        client = MagicMock()
        with _patch_build_client(client):
            ok, path = download_object("mykey", local_path="/tmp/out.bin")
        self.assertTrue(ok)
        self.assertEqual(path, "/tmp/out.bin")
        client.download_file.assert_called_once_with("test-bucket", "mykey", "/tmp/out.bin")

    def test_creates_temp_file_when_local_path_is_none(self):
        client = MagicMock()
        with _patch_build_client(client):
            ok, path = download_object("folder/image.jpg")
        self.assertTrue(ok)
        self.assertTrue(path.endswith(".jpg"))
        self.assertTrue(os.path.basename(path).startswith("rustfs_"))
        client.download_file.assert_called_once_with("test-bucket", "folder/image.jpg", path)
        os.unlink(path)

    def test_returns_error_on_exception(self):
        client = MagicMock()
        client.download_file.side_effect = RuntimeError("network fail")
        with _patch_build_client(client):
            ok, msg = download_object("badkey", local_path="/tmp/x.bin")
        self.assertFalse(ok)
        self.assertIn("network fail", msg)


class TestGeneratePresignedUrl(unittest.TestCase):
    def test_returns_url_on_success(self):
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://signed-url.example.com"
        with _patch_build_client(client):
            ok, url = generate_presigned_url("mykey", expires_in=7200)
        self.assertTrue(ok)
        self.assertEqual(url, "https://signed-url.example.com")
        client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "mykey"},
            ExpiresIn=7200,
        )

    def test_returns_error_on_exception(self):
        client = MagicMock()
        client.generate_presigned_url.side_effect = RuntimeError("denied")
        with _patch_build_client(client):
            ok, msg = generate_presigned_url("mykey")
        self.assertFalse(ok)
        self.assertIn("denied", msg)


class TestUploadFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rustfs_upload_")
        self.sample_file = os.path.join(self.tmpdir, "test.txt")
        with open(self.sample_file, "w") as f:
            f.write("hello")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_uploads_with_progress_callback(self):
        client = MagicMock()
        callback = MagicMock()
        with _patch_build_client(client):
            ok, msg = upload_file(self.sample_file, "remote/key",
                                  progress_callback=callback)
        self.assertTrue(ok)
        client.upload_file.assert_called_once_with(
            self.sample_file, "test-bucket", "remote/key",
            Callback=callback,
        )

    def test_uploads_without_callback(self):
        client = MagicMock()
        with _patch_build_client(client):
            ok, msg = upload_file(self.sample_file, "remote/key")
        self.assertTrue(ok)
        client.upload_file.assert_called_once_with(
            self.sample_file, "test-bucket", "remote/key",
        )

    def test_returns_error_on_exception(self):
        client = MagicMock()
        client.upload_file.side_effect = RuntimeError("upload failed")
        with _patch_build_client(client):
            ok, msg = upload_file(self.sample_file, "remote/key")
        self.assertFalse(ok)
        self.assertIn("upload failed", msg)


class TestSyncDirectoryToRustfs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rustfs_sync_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_files(self, structure):
        for rel in structure:
            fp = os.path.join(self.tmpdir, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w") as f:
                f.write("x")

    def test_syncs_media_files_only(self):
        self._make_files(["a.jpg", "b.png", "c.txt", "sub/d.mp4", "sub/e.pdf"])
        client = MagicMock()
        with _patch_build_client(client):
            ok, msg, synced, failed = sync_directory_to_rustfs(
                self.tmpdir, remote_prefix="assets"
            )
        self.assertTrue(ok)
        self.assertEqual(synced, 3)
        self.assertEqual(failed, 0)
        uploaded_keys = [
            call[0][2] for call in client.upload_file.call_args_list
        ]
        self.assertIn("assets/a.jpg", uploaded_keys)
        self.assertIn("assets/b.png", uploaded_keys)
        self.assertIn("assets/sub/d.mp4", uploaded_keys)

    def test_syncs_all_files(self):
        self._make_files(["a.jpg", "b.txt", "sub/c.pdf"])
        client = MagicMock()
        with _patch_build_client(client):
            ok, msg, synced, failed = sync_directory_to_rustfs(
                self.tmpdir, all_files=True
            )
        self.assertTrue(ok)
        self.assertEqual(synced, 3)
        self.assertEqual(failed, 0)

    def test_returns_error_for_nonexistent_directory(self):
        ok, msg, synced, failed = sync_directory_to_rustfs(
            "/nonexistent/path"
        )
        self.assertFalse(ok)
        self.assertIn("目录不存在", msg)
        self.assertEqual(synced, 0)
        self.assertEqual(failed, 0)

    def test_reports_progress_via_callback(self):
        self._make_files(["a.jpg", "b.png", "c.mp3"])
        client = MagicMock()
        progress = MagicMock()
        with _patch_build_client(client):
            ok, msg, synced, failed = sync_directory_to_rustfs(
                self.tmpdir, progress_callback=progress
            )
        self.assertTrue(ok)
        self.assertTrue(progress.called)
        last_call = progress.call_args_list[-1]
        self.assertEqual(last_call[0][0], 3)
        self.assertEqual(last_call[0][1], 3)

    def test_handles_upload_failures(self):
        self._make_files(["a.jpg", "b.png", "c.mp3"])
        client = MagicMock()

        def upload_side_effect(path, bucket, key):
            if "b.png" in key:
                raise RuntimeError("upload rejected")

        client.upload_file.side_effect = upload_side_effect
        with _patch_build_client(client):
            ok, msg, synced, failed = sync_directory_to_rustfs(
                self.tmpdir
            )
        self.assertFalse(ok)
        self.assertEqual(synced, 2)
        self.assertEqual(failed, 1)
        self.assertIn("b.png", msg)


if __name__ == "__main__":
    unittest.main()