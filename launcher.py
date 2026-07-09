#!/usr/bin/env python3
"""螺丝钉-电商智能体矩阵 · 启动器"""
import os, sys, subprocess, ctypes

# 当前目录设为工程根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# 查找 python 可执行文件
python_exe = os.path.join(BASE_DIR, "python_embeded", "python.exe")
if not os.path.isfile(python_exe):
    python_exe = os.path.join(BASE_DIR, "studio", "python_embeded", "python.exe")
if not os.path.isfile(python_exe):
    python_exe = sys.executable  # fallback

entry = os.path.join(BASE_DIR, "studio", "gui_main.py")
if not os.path.isfile(entry):
    entry = os.path.join(BASE_DIR, "gui_main.py")

# 设置环境变量
env = os.environ.copy()
env.setdefault("PYTHONPATH", BASE_DIR)
env["TINTIN_NO_LICENSE"] = "1"  # 开发模式跳过激活

# 显示控制台窗口(debug)或隐藏(release)
show_console = "-console" in sys.argv
if not show_console:
    try:
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

subprocess.run([python_exe, entry], env=env, cwd=BASE_DIR)
