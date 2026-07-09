#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
螺丝钉-电商智能体矩阵 · 发布分包打包工具

将工程打包为多个 <10GB 的分卷文件，与启动器 exe 放在同一目录下。
客户首次启动时自动解包。

用法:
    python tools/pack_release.py [--volume-size 10G]

输出:
    螺丝钉-电商智能体矩阵.vol.001
    螺丝钉-电商智能体矩阵.vol.002
    ...
"""

import os, sys, zipfile, hashlib, time, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VOLUME_SIZE = 10 * 1024**3  # 10GB 默认

# 需要排除的目录/文件
EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules", "build", "dist",
    ".mypy_cache", ".pytest_cache", ".hypothesis",
}
EXCLUDE_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
}
EXCLUDE_PATTERNS = {
    ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so",
}
# 客户业务数据（打包时排除，避免将客户数据发给其他人）
EXCLUDE_DATA_PATHS = {
    "studio/data/product_library.json",
    "studio/data/material_index_config.json",
    "studio/config/trial_whitelist.json",
    "studio/config/.activation_cache",
    "studio/config/license.dat",
    "studio/config/license_private.pem",
    "tools/license_private.pem",
}


def should_include(path: Path, rel: str) -> bool:
    """判断文件是否应该打包。"""
    parts = rel.split(os.sep)
    # 排除目录
    if any(p in EXCLUDE_DIRS for p in parts):
        return False
    name = path.name
    if name in EXCLUDE_FILES:
        return False
    if any(name.endswith(s) for s in EXCLUDE_PATTERNS):
        return False
    # 排除 git 内部文件
    if ".git" in parts:
        return False
    # 排除客户业务数据
    if rel in EXCLUDE_DATA_PATHS:
        return False
    return True


def collect_files() -> list[tuple[Path, str]]:
    """收集需要打包的文件。返回 [(abs_path, rel_path)]。"""
    files = []
    total_size = 0
    for root, dirs, filenames in os.walk(PROJECT_ROOT):
        # 跳过排除目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fn in filenames:
            abs_path = Path(root) / fn
            rel_path = abs_path.relative_to(PROJECT_ROOT).as_posix()
            if should_include(abs_path, rel_path):
                files.append((abs_path, rel_path))
                total_size += abs_path.stat().st_size
    return files, total_size


def pack(files: list, total_size: int, output_prefix: str):
    """打包为分卷 zip 文件。"""
    vol_size = VOLUME_SIZE
    vol_index = 1
    current_size = 0
    zip_path = f"{output_prefix}.vol.{vol_index:03d}"
    zf = zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True)

    manifest = []

    for abs_path, rel_path in files:
        file_size = abs_path.stat().st_size

        # 检查是否需要新卷（当前卷超过限制且已有内容）
        if current_size + file_size > vol_size and current_size > 0:
            zf.close()
            _size = os.path.getsize(zip_path)
            print(f"  {zip_path}  ({_size/1024**3:.1f} GB)")
            manifest.append({"vol": vol_index, "size": _size, "file": zip_path})
            vol_index += 1
            zip_path = f"{output_prefix}.vol.{vol_index:03d}"
            zf = zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
            current_size = 0

        zf.write(abs_path, rel_path)
        current_size += file_size

    # 关闭最后一个卷
    if zf.fp:
        zf.close()
        _size = os.path.getsize(zip_path)
        print(f"  {zip_path}  ({_size/1024**3:.1f} GB)")
        manifest.append({"vol": vol_index, "size": _size, "file": zip_path})

    # 写入清单文件
    manifest_path = f"{output_prefix}.manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "app": "螺丝钉-电商智能体矩阵",
            "volumes": vol_index,
            "total_size": total_size,
            "files": manifest,
        }, f, ensure_ascii=False, indent=2)
    print(f"  清单: {manifest_path}")
    print(f"\n共 {vol_index} 卷, 原始大小: {total_size/1024**3:.1f} GB")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="螺丝钉-电商智能体矩阵 发布分包工具")
    parser.add_argument("--volume-size", default="10G", help="每卷大小, 默认 10G")
    args = parser.parse_args()

    global VOLUME_SIZE
    size_str = args.volume_size.upper()
    if size_str.endswith("G"):
        VOLUME_SIZE = float(size_str[:-1]) * 1024**3
    elif size_str.endswith("M"):
        VOLUME_SIZE = float(size_str[:-1]) * 1024**2
    else:
        VOLUME_SIZE = int(size_str)

    print("扫描文件...")
    t0 = time.time()
    files, total_size = collect_files()
    print(f"  共 {len(files)} 个文件, {total_size/1024**3:.1f} GB ({time.time()-t0:.0f}s)")

    output_prefix = str(PROJECT_ROOT / "螺丝钉-电商智能体矩阵")
    print(f"\n打包到 {output_prefix}.vol.xxx ...")
    t0 = time.time()
    pack(files, total_size, output_prefix)
    print(f"打包完成 ({time.time()-t0:.0f}s)")
    print(f"\n提示：将 .vol.* 文件和启动器 exe 放在同一目录下,")
    print(f"      首次运行启动器时自动解包。")


if __name__ == "__main__":
    main()
