#!/usr/bin/env python3
"""开发模式启动器 — 直接运行 gui_main.py（无解包逻辑）"""
import os
import sys
import subprocess

# Windowed 模式下用 MessageBox 显示错误
def _show_error(msg):
    if getattr(sys, 'frozen', False) and not sys.stdin:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "启动错误", 0)
        except Exception:
            pass
    else:
        try:
            print(msg)
            input("按 Enter 退出...")
        except (EOFError, RuntimeError):
            pass

# 定位项目根目录
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，EXE 就在项目根目录
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.chdir(BASE_DIR)

entry = os.path.join(BASE_DIR, "studio", "gui_main.py")
if not os.path.isfile(entry):
    _show_error(f"错误：未找到 {entry}")
    sys.exit(1)

env = os.environ.copy()
env.setdefault("PYTHONPATH", os.path.join(BASE_DIR, "studio"))

# PyInstaller 打包后直接用当前解释器运行
python_exe = sys.executable
subprocess.run([python_exe, entry], env=env, cwd=BASE_DIR)
