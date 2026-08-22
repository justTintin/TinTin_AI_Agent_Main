#!/usr/bin/env python3
"""
开发模式启动脚本。

注意：打包/构建/加固逻辑已迁移到独立发布工程：
  D:\\Project\\TinTin_Release_Builder\\release.py

本文件只保留开发模式（直接运行应用），不再包含任何发布功能。
"""

import os
import sys
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
ENTRY = os.path.join(STUDIO_DIR, "gui_main.py")


def run_dev():
    """Run the application directly (dev mode)."""
    print("[run] Starting 螺丝钉-电商智能体矩阵 in dev mode...")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.pathsep.join([STUDIO_DIR, env.get("PYTHONPATH", "")]))
    subprocess.run([sys.executable, ENTRY], env=env, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="螺丝钉-电商智能体矩阵 开发启动")
    parser.add_argument("command", nargs="?", default="run", choices=["run"],
                        help="仅支持 run（开发模式）；发布请用 TinTin_Release_Builder")
    args = parser.parse_args()
    if args.command == "run":
        run_dev()
