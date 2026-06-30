#!/usr/bin/env python3
"""
Cross-platform build script for TinTin AI Agent.

Usage:
    python build.py win      Build Windows executable (PyInstaller)
    python build.py linux    Build Linux executable (PyInstaller)
    python build.py run      Run directly (dev mode)
    python build.py clean    Clean build artifacts

Requires: pyinstaller
"""

import os
import sys
import shutil
import subprocess
import argparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
ENTRY = os.path.join(STUDIO_DIR, "gui_main.py")
NAME = "AI电商智能体"
ICON = os.path.join(STUDIO_DIR, "assets", "app_icon.png")


def run_dev():
    """Run the application directly (dev mode)."""
    print("[run] Starting TinTin AI Agent in dev mode...")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.pathsep.join([
        STUDIO_DIR,
        env.get("PYTHONPATH", ""),
    ]))
    subprocess.run([sys.executable, ENTRY], env=env, cwd=PROJECT_ROOT)


def build_win():
    """Build Windows executable using PyInstaller."""
    print("[build] Building Windows executable...")
    _ensure_pyinstaller()

    icon_ico = os.path.join(STUDIO_DIR, "assets", "app_icon.ico")
    icon_args = [f"--icon={icon_ico}"] if os.path.isfile(icon_ico) else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'assets')}{os.pathsep}studio/assets",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'config')}{os.pathsep}studio/config",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'bin', 'win')}{os.pathsep}studio/bin",
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'apps')}{os.pathsep}apps",
        "--collect-all", "PySide6",
        "--hidden-import", "utils.platform_utils",
        "--hidden-import", "utils.service_registry",
        "--hidden-import", "config.paths",
        "--hidden-import", "voxcpm",
        "--hidden-import", "loguru",
        "--clean",
        "--noconfirm",
        *icon_args,
        ENTRY,
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    print(f"[build] Done → {os.path.join(DIST_DIR, NAME + '.exe')}")


def build_linux():
    """Build Linux executable using PyInstaller."""
    print("[build] Building Linux executable...")
    _ensure_pyinstaller()

    icon_args = [f"--icon={ICON}"] if os.path.isfile(ICON) else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'assets')}{os.pathsep}studio/assets",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'config')}{os.pathsep}studio/config",
        "--add-data", f"{os.path.join(STUDIO_DIR, 'bin', 'linux')}{os.pathsep}studio/bin",
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'apps')}{os.pathsep}apps",
        "--collect-all", "PySide6",
        "--hidden-import", "utils.platform_utils",
        "--hidden-import", "utils.service_registry",
        "--hidden-import", "config.paths",
        "--hidden-import", "voxcpm",
        "--hidden-import", "loguru",
        "--clean",
        "--noconfirm",
        *icon_args,
        ENTRY,
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    print(f"[build] Done → {os.path.join(DIST_DIR, NAME)}")


def clean():
    """Remove build artifacts."""
    for d in [BUILD_DIR, DIST_DIR]:
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"[clean] Removed {d}")
    for spec in os.listdir(PROJECT_ROOT):
        if spec.endswith(".spec"):
            os.remove(os.path.join(PROJECT_ROOT, spec))
            print(f"[clean] Removed {spec}")


def _ensure_pyinstaller():
    try:
        import PyInstaller
    except ImportError:
        print("[build] Installing pyinstaller...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TinTin AI Agent Build Tool")
    parser.add_argument("command", choices=["win", "linux", "run", "clean"],
                        help="Action to perform")
    args = parser.parse_args()

    if args.command == "win":
        build_win()
    elif args.command == "linux":
        build_linux()
    elif args.command == "run":
        run_dev()
    elif args.command == "clean":
        clean()
