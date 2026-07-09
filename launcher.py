#!/usr/bin/env python3
"""螺丝钉-电商智能体矩阵 · 启动器

用法（开发）:
  python build.py launcher → 生成启动器 exe 到工程根目录,双击启动

用法（发布）:
  python build.py win → 生成独立完整 exe 到 dist/,可直接分发
"""
import os, sys, subprocess

# 确定工程根目录（启动器 exe 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
os.chdir(BASE_DIR)

# 查找嵌入式 Python
python_exe = os.path.join(BASE_DIR, "python_embeded", "python.exe")
if not os.path.isfile(python_exe):
    python_exe = os.path.join(BASE_DIR, "python_embeded", "pythonw.exe")
if not os.path.isfile(python_exe):
    python_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
if not os.path.isfile(python_exe):
    python_exe = "python"  # 系统 PATH

entry = os.path.join(BASE_DIR, "studio", "gui_main.py")
if not os.path.isfile(entry):
    print(f"错误: 未找到 {entry}")
    print(f"请将启动器放在工程根目录运行")
    input("按 Enter 退出...")
    sys.exit(1)

# 设置环境变量
env = os.environ.copy()
env.setdefault("PYTHONPATH", os.path.join(BASE_DIR, "studio"))
env["TINTIN_NO_LICENSE"] = "1"  # 开发模式跳过激活检查

# 启动
result = subprocess.run([python_exe, entry], env=env, cwd=BASE_DIR)
if result.returncode != 0:
    print(f"程序异常退出，错误码: {result.returncode}")
    input("按 Enter 退出...")
