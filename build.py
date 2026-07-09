#!/usr/bin/env python3
"""
Cross-platform build script for 螺丝钉-电商智能体矩阵.

Usage:
    python build.py win        Build full Windows executable (for distribution)
    python build.py launcher   Build lightweight launcher exe (for development, outputs to project root)
    python build.py linux      Build Linux executable
    python build.py run        Run directly (dev mode)
    python build.py clean      Clean build artifacts

For commercial distribution: python build.py win
For dev double-click launch: python build.py launcher  → then double-click the exe at project root
"""

import os, sys, shutil, subprocess, argparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
ENTRY = os.path.join(STUDIO_DIR, "gui_main.py")
NAME = "螺丝钉-电商智能体矩阵"
ICON = os.path.join(STUDIO_DIR, "assets", "app_icon.png")
# PyInstaller --key 加密密钥：从环境变量 BUILD_KEY 读取
BUILD_KEY = os.environ.get("BUILD_KEY", "d2j9s7k3x5m8q4w6p1r0t2y4u6i8o7a9")


def run_dev():
    """Run the application directly (dev mode)."""
    print("[run] Starting 螺丝钉-电商智能体矩阵 in dev mode...")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.pathsep.join([STUDIO_DIR, env.get("PYTHONPATH", "")]))
    subprocess.run([sys.executable, ENTRY], env=env, cwd=PROJECT_ROOT)


def build_win():
    """Build Windows executable for commercial distribution (self-contained, large)."""
    print("[build] Building Windows executable for distribution...")
    _ensure_pyinstaller()
    icon_ico = os.path.join(STUDIO_DIR, "assets", "app_icon.ico")
    icon_args = [f"--icon={icon_ico}"] if os.path.isfile(icon_ico) else []
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--key", BUILD_KEY,
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
    """Build Linux executable."""
    print("[build] Building Linux executable...")
    _ensure_pyinstaller()
    icon_args = [f"--icon={ICON}"] if os.path.isfile(ICON) else []
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--key", BUILD_KEY,
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


def build_launcher():
    """Build lightweight launcher exe. Output to project root for double-click launch."""
    print("[build] Building launcher executable...")
    _ensure_pyinstaller()
    launcher = os.path.join(PROJECT_ROOT, "launcher.py")
    icon_ico = os.path.join(STUDIO_DIR, "assets", "app_icon.ico")
    icon_args = [f"--icon={icon_ico}"] if os.path.isfile(icon_ico) else []
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
        *icon_args,
        launcher,
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    src = os.path.join(DIST_DIR, NAME + ".exe")
    dst = os.path.join(PROJECT_ROOT, NAME + ".exe")
    shutil.copy2(src, dst)
    print(f"[build] Done → {dst}")


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
    launcher_exe = os.path.join(PROJECT_ROOT, NAME + ".exe")
    if os.path.isfile(launcher_exe):
        os.remove(launcher_exe)
        print(f"[clean] Removed {launcher_exe}")


def _ensure_pyinstaller():
    try:
        import PyInstaller
    except ImportError:
        print("[build] Installing pyinstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="螺丝钉-电商智能体矩阵 Build Tool")
    parser.add_argument("command", choices=["win", "linux", "run", "launcher", "clean"],
                        help="Action to perform")
    args = parser.parse_args()
    if args.command == "win":
        build_win()
    elif args.command == "linux":
        build_linux()
    elif args.command == "launcher":
        build_launcher()
    elif args.command == "run":
        run_dev()
    elif args.command == "clean":
        clean()
