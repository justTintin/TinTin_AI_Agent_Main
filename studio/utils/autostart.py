"""Windows 开机自启管理（HKCU\\...\\CurrentVersion\\Run 注册表键）。

源码模式：写 "pythonw.exe" "studio/gui_main.py"（脚本目录自动入 sys.path，无需额外环境）。
打包模式：直接写 exe 路径。
"""
import contextlib
import os
import sys
import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "LuosidingAgent"


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        alt = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        if os.path.isfile(alt):
            python_exe = alt
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui_main.py")  # noqa: E501
    return f'"{python_exe}" "{entry}"'


def is_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY)
        try:
            val, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(val)
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """写入/删除 Run 键。返回是否成功。"""
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY)
        try:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _autostart_command())  # noqa: E501
            else:
                with contextlib.suppress(OSError):
                    winreg.DeleteValue(key, _VALUE_NAME)
        finally:
            winreg.CloseKey(key)
        return True
    except OSError:
        return False
