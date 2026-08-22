"""process_utils 单元测试。

验证：
- 常量 re-export 可导入且为 int（Windows 下为正值，非 Windows 下为 0）
- popen 不强制无窗口 / 不设 stdin 默认值（保留调用方控制权）
"""
import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil  # noqa: E402

testutil.ensure_studio_on_path()

from utils import process_utils  # noqa: E402
from utils.process_utils import (  # noqa: E402
    CREATE_NEW_CONSOLE,
    CREATE_NEW_PROCESS_GROUP,
    CREATE_NO_WINDOW,
    DETACHED_PROCESS,
    popen,
)


class TestProcessUtilsConstants(unittest.TestCase):
    """常量 re-export 正确性。"""

    def test_constants_are_int(self):
        for name, val in [
            ("CREATE_NEW_CONSOLE", CREATE_NEW_CONSOLE),
            ("DETACHED_PROCESS", DETACHED_PROCESS),
            ("CREATE_NEW_PROCESS_GROUP", CREATE_NEW_PROCESS_GROUP),
            ("CREATE_NO_WINDOW", CREATE_NO_WINDOW),
        ]:
            with self.subTest(name=name):
                self.assertIsInstance(val, int, f"{name} 应为 int")

    def test_constants_match_subprocess(self):
        # 非平台相关断言：process_utils 的常量应等于 subprocess 的同名常量
        import subprocess

        self.assertEqual(CREATE_NEW_CONSOLE, getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        self.assertEqual(DETACHED_PROCESS, getattr(subprocess, "DETACHED_PROCESS", 0))
        self.assertEqual(CREATE_NEW_PROCESS_GROUP, getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.assertEqual(CREATE_NO_WINDOW, getattr(subprocess, "CREATE_NO_WINDOW", 0))


class TestProcessUtilsPopen(unittest.TestCase):
    """popen 不强制无窗口 / 不设 stdin 默认值，保留调用方控制权。"""

    @mock.patch.object(process_utils.subprocess, "Popen")
    def test_popen_does_not_force_no_window(self, mock_popen):
        """popen 不应自动注入 CREATE_NO_WINDOW（与 ffmpeg_utils.popen 区分）。"""
        popen(["cmd"], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        _args, kwargs = mock_popen.call_args
        # 调用方显式传入的 creationflags 应被原样保留
        self.assertEqual(kwargs.get("creationflags"), DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        # 不应自动注入 CREATE_NO_WINDOW
        flags = kwargs.get("creationflags", 0)
        self.assertEqual(flags & CREATE_NO_WINDOW, 0)

    @mock.patch.object(process_utils.subprocess, "Popen")
    def test_popen_does_not_set_default_stdin(self, mock_popen):
        """popen 不应设 stdin 默认值（保留调用方控制权）。"""
        popen(["cmd"])
        _args, kwargs = mock_popen.call_args
        self.assertNotIn("stdin", kwargs, "popen 不应自动注入 stdin")

    @mock.patch.object(process_utils.subprocess, "Popen")
    def test_popen_passes_through_kwargs(self, mock_popen):
        """popen 透传调用方的所有 kwargs。"""
        sentinel = object()
        popen(["cmd"], stdout=sentinel, env={"X": "1"})
        _args, kwargs = mock_popen.call_args
        self.assertIs(kwargs["stdout"], sentinel)
        self.assertEqual(kwargs["env"], {"X": "1"})

    def test_popen_signature_takes_cmd_positional(self):
        """popen 签名：cmd 位置参数 + **kwargs。"""
        sig = inspect.signature(popen)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["cmd", "kwargs"])


if __name__ == "__main__":
    unittest.main()
