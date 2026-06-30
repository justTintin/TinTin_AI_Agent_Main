# -*- coding: utf-8 -*-
"""
本地 ComfyUI 启动引导脚本（供工程内置 python_embeded 使用）。

为什么需要它：python_embeded 的 python311._pth 锁定了 sys.path，既不包含脚本
所在目录、也忽略 PYTHONPATH，导致直接 `python.exe main.py` 无法 import 本目录
下的 comfy 包。这里手动把本目录补进 sys.path，再以 __main__ 方式运行 main.py。

用法：
    python_embeded\\python.exe _run_local.py [--listen 127.0.0.1 --port 8188 ...]
不带参数时使用默认：监听 127.0.0.1:8188，禁用自动打开浏览器。
"""
import os
import sys
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "main.py")

# 关键：把 ComfyUI 目录加入模块搜索路径
sys.path.insert(0, HERE)

# 无显式参数时给一组本地默认值
if len(sys.argv) == 1:
    sys.argv += ["--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch"]
sys.argv[0] = MAIN

runpy.run_path(MAIN, run_name="__main__")
