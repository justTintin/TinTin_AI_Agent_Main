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

import os, sys, shutil, subprocess, argparse, urllib.request, zipfile, stat

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
ENTRY = os.path.join(STUDIO_DIR, "gui_main.py")
NAME = "螺丝钉-电商智能体矩阵"
UPX_DIR = os.path.join(PROJECT_ROOT, "build", "upx")
UPX_BIN = os.path.join(UPX_DIR, "upx.exe") if sys.platform == "win32" else os.path.join(UPX_DIR, "upx")
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
    upx_args = _ensure_upx()
    icon_ico = os.path.join(STUDIO_DIR, "assets", "app_icon.ico")
    icon_args = [f"--icon={icon_ico}"] if os.path.isfile(icon_ico) else []
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--key", BUILD_KEY,
        "--strip",
        *upx_args,
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
    upx_args = _ensure_upx()
    icon_args = [f"--icon={ICON}"] if os.path.isfile(ICON) else []
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--key", BUILD_KEY,
        "--strip",
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
        *upx_args,
        *icon_args,
        ENTRY,
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    print(f"[build] Done → {os.path.join(DIST_DIR, NAME)}")


def build_launcher():
    """Build lightweight launcher with built-in first-run extractor.
    Output to project root. Pack volumes first with: python tools/pack_release.py"""
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
        "--strip",
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


def _ensure_upx():
    """下载 UPX 压缩工具（用于加固 exe）。"""
    if os.path.isfile(UPX_BIN):
        return [UPX_BIN]
    print("[build] 正在下载 UPX（用于压缩加固 exe）...")
    os.makedirs(UPX_DIR, exist_ok=True)
    if sys.platform == "win32":
        url = "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-win64.zip"
        zip_path = os.path.join(UPX_DIR, "upx.zip")
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(UPX_DIR)
            # 找到 upx.exe
            for root, dirs, files in os.walk(UPX_DIR):
                for fn in files:
                    if fn == "upx.exe":
                        exe_path = os.path.join(root, fn)
                        shutil.move(exe_path, UPX_BIN)
                        break
            os.remove(zip_path)
            # 清理解压目录
            for item in os.listdir(UPX_DIR):
                item_path = os.path.join(UPX_DIR, item)
                if item != "upx.exe" and os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            if os.path.isfile(UPX_BIN):
                os.chmod(UPX_BIN, os.stat(UPX_BIN).st_mode | stat.S_IEXEC)
                print(f"[build] UPX 就绪: {UPX_BIN}")
                return [UPX_BIN]
        except Exception as e:
            print(f"[build] UPX 下载失败: {e}（不影响构建，只是缺少压缩加固）")
    else:
        # Linux: 尝试使用系统包管理器安装
        for c in ["upx", "upx-ucl"]:
            if shutil.which(c):
                return [shutil.which(c)]
        print("[build] UPX 未安装（apt install upx-ucl 或 brew install upx）")
    return []


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
