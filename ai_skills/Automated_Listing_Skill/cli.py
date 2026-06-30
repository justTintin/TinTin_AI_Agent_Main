# -*- coding: utf-8 -*-
"""
Automated_Listing_Skill CLI Orchestrator
核心调度器：处理输入校验、任务生命周期管理与 WorkBuddy 状态同步
"""

import os
import sys
import json
import shutil
import argparse
import re
import zipfile
import struct
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

CURRENT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(CURRENT_DIR))
sys.path.insert(0, str(CURRENT_DIR / "config"))
try:
    from skill_config import DOUYIN_STORES, ensure_dirs, CHROME_DEBUG_PORT, CHROME_USER_DATA
    ensure_dirs()
except ImportError:
    DOUYIN_STORES = {}
    CHROME_DEBUG_PORT = 9222
    CHROME_USER_DATA = str(CURRENT_DIR / "chrome_user_data")

try:
    from browser.chrome_manager import ensure_debug_chrome, is_cdp_ready
except ImportError:
    ensure_debug_chrome = None
    is_cdp_ready = None


def default_sync_root() -> str:
    home = str(Path.home())
    docs = os.path.join(home, "Documents")
    if os.path.isdir(docs):
        return os.path.join(docs, "WorkBuddy", "上架数据")
    return os.path.join(home, "WorkBuddy", "上架数据")


def _read_skill_version(skill_md_path: str) -> Optional[str]:
    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def _write_skill_version(skill_md_path: str, new_version: str) -> None:
    with open(skill_md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("version:"):
            lines[i] = f"version: {new_version}\n"
            updated = True
            break
    if not updated:
        raise RuntimeError("SKILL.md 缺少 version 字段")
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _parse_version(version: str) -> Optional[Tuple[int, int, int, str]]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.(\d{12})", version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def _bump_version(version: str) -> str:
    parsed = _parse_version(version)
    now_ts = datetime.now().strftime("%Y%m%d%H%M")
    if not parsed:
        return f"1.0.0.{now_ts}"
    major, minor, patch, _ = parsed
    return f"{major}.{minor}.{patch + 1}.{now_ts}"


def _iter_version_files(skill_root: str) -> List[str]:
    allow_ext = {".py", ".cmd"}
    deny_dirs = {"chrome_user_data", "__pycache__"}
    out: List[str] = []
    for root, dirs, files in os.walk(skill_root):
        dirs[:] = [d for d in dirs if d not in deny_dirs]
        for name in files:
            p = os.path.join(root, name)
            if os.path.basename(p).lower() == "skill.md":
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in allow_ext:
                out.append(p)
    out.sort()
    return out


def _fingerprint(skill_root: str) -> str:
    h = hashlib.sha256()
    for p in _iter_version_files(skill_root):
        rel = os.path.relpath(p, skill_root).replace("\\", "/")
        h.update(rel.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        with open(p, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def bump_version_if_needed(skill_root: str) -> Optional[str]:
    skill_md = os.path.join(skill_root, "SKILL.md")
    current = _read_skill_version(skill_md)
    if not current:
        return None

    state_path = os.path.join(skill_root, ".version_state.json")
    fp = _fingerprint(skill_root)

    prior_fp = None
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
            prior_fp = state.get("fingerprint")
    except Exception:
        prior_fp = None

    if prior_fp is None:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"fingerprint": fp, "version": current}, f, ensure_ascii=False, indent=2)
        return None

    if prior_fp == fp:
        return None

    new_version = _bump_version(current)
    _write_skill_version(skill_md, new_version)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": fp, "version": new_version}, f, ensure_ascii=False, indent=2)
    return new_version

def normalize_name(name: str) -> str:
    """归一化名称：去除特殊字符、空格，转小写"""
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', name).lower()

def fuzzy_match_store(candidate_name: str, shop_key: str) -> Tuple[bool, Dict[str, Any]]:
    """
    模糊匹配店铺名称
    candidate_name: 上传的文件夹/文件名
    shop_key: 用户选择的店铺 key (juyou, 555_battery)
    """
    store_info = DOUYIN_STORES.get(shop_key)
    if not store_info:
        return False, {"error": f"未知的店铺 Key: {shop_key}"}

    shop_real_name = store_info.get("name", "")
    aliases = store_info.get("aliases", [])
    
    cand = normalize_name(candidate_name)
    
    if normalize_name(shop_real_name) in cand or cand in normalize_name(shop_real_name):
        return True, {"matched": shop_real_name}
    
    for alias in aliases:
        norm_alias = normalize_name(alias)
        if norm_alias in cand or cand in norm_alias:
            return True, {"matched": alias}
            
    return False, {
        "expected": shop_real_name,
        "aliases": aliases,
        "got": candidate_name
    }

def emit_progress(stage: int, status: str, message: str, **kwargs):
    """向 stdout 吐出 unbuffered JSON Line"""
    data = {
        "type": "progress",
        "stage": stage,
        "status": status,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    data.update(kwargs)
    print(json.dumps(data, ensure_ascii=False))
    sys.stdout.flush()

def emit_result(success: bool, message: str, **kwargs):
    """输出最终结果 JSON"""
    data = {
        "type": "result",
        "success": success,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    data.update(kwargs)
    print(json.dumps(data, ensure_ascii=False))
    sys.stdout.flush()

def _get_image_size(file_path: str) -> Tuple[Optional[int], Optional[int]]:
    """无需 Pillow 库，通过二进制读取获取 PNG/JPG 尺寸"""
    try:
        with open(file_path, 'rb') as f:
            data = f.read(24)
            if data[:8] == b'\x89PNG\r\n\x1a\n':
                w, h = struct.unpack('>LL', data[16:24])
                return int(w), int(h)
            elif data[:2] == b'\xff\xd8':
                f.seek(0)
                size = 2
                ftype = 0
                while not 0xc0 <= ftype <= 0xcf or ftype in [0xc4, 0xc8, 0xcc]:
                    f.seek(size, 1)
                    byte = f.read(2)
                    while byte[0] != 0xff:
                        byte = f.read(1)
                    ftype = byte[1]
                    size = struct.unpack('>H', f.read(2))[0] - 2
                f.seek(1, 1)
                h, w = struct.unpack('>HH', f.read(4))
                return int(w), int(h)
    except Exception:
        pass
    return None, None

def stage_0_validate(input_path: str, shop_key: str, run_id: str, sync_root: str) -> str:
    """
    阶段 0：输入验证
    返回处理后的解压目录路径
    """
    emit_progress(0, "running", f"开始校验输入数据: {os.path.basename(input_path)}")
    
    if not os.path.exists(input_path):
        raise Exception(f"输入路径不存在: {input_path}")

    candidate_name = os.path.basename(input_path)
    is_match, match_info = fuzzy_match_store(candidate_name, shop_key)
    
    if not is_match:
        store_info = DOUYIN_STORES.get(shop_key, {})
        valid_names = [store_info.get("name", "")] + store_info.get("aliases", [])
        valid_names_str = " 或 ".join([f"'{n}'" for n in valid_names if n])
        
        error_msg = (
            f"❌ 店铺匹配失败！\n"
            f"上传的文件名 '{candidate_name}' 未包含目标店铺标识。\n"
            f"请将文件重命名，使其包含 {valid_names_str} 中的任意关键词后再试。"
        )
        emit_progress(0, "error", error_msg, shop_verified=False)
        emit_result(False, "输入校验未通过", error_type="SHOP_MISMATCH", shop_verified=False)
        sys.exit(1)

    emit_progress(0, "success", f"店铺匹配成功: {match_info['matched']}", shop_verified=True)
    
    sync_root = (sync_root or "").strip() or default_sync_root()
    os.makedirs(sync_root, exist_ok=True)

    batch_root = os.path.join(sync_root, os.path.splitext(candidate_name)[0])
    staged_root = os.path.join(batch_root, "_runs", run_id, "input")
    os.makedirs(staged_root, exist_ok=True)

    working_dir = staged_root
    if os.path.isdir(input_path):
        emit_progress(0, "running", f"正在复制数据目录到: {staged_root}", run_id=run_id, staged_path=staged_root, sync_root=sync_root)
        shutil.copytree(input_path, staged_root, dirs_exist_ok=True)
    elif input_path.lower().endswith(".zip"):
        emit_progress(0, "running", f"正在解压数据包到: {staged_root}", run_id=run_id, staged_path=staged_root, sync_root=sync_root)
        with zipfile.ZipFile(input_path, 'r') as zip_ref:
            zip_ref.extractall(staged_root)
        for root, _dirs, files in os.walk(staged_root):
            if "sku.xlsx" in files:
                working_dir = root
                break
    else:
        raise Exception("输入必须为文件夹或 .zip 压缩包")

    emit_progress(0, "running", f"工作目录定位完成: {working_dir}", run_id=run_id, staged_path=staged_root, sync_root=sync_root)

    required_dirs = ["主图", "详情页", "sku图"]
    for d in required_dirs:
        dir_path = os.path.join(working_dir, d)
        if not os.path.isdir(dir_path):
            error_msg = f"❌ 目录结构错误：缺少必要目录 '{d}'"
            emit_progress(0, "error", error_msg)
            emit_result(False, error_msg)
            sys.exit(1)
            
    main_img_dir = os.path.join(working_dir, "主图")
    for img_file in os.listdir(main_img_dir):
        if img_file.lower().endswith(('.png', '.jpg', '.jpeg')):
            w, h = _get_image_size(os.path.join(main_img_dir, img_file))
            if w and h and w != h:
                error_msg = f"❌ 主图比例错误：文件 '{img_file}' 尺寸为 {w}x{h}，主图必须为 1:1 比例。"
                emit_progress(0, "error", error_msg)
                emit_result(False, error_msg)
                sys.exit(1)

    emit_progress(0, "success", "数据包结构与图片比例校验通过")
    return working_dir

def _run_stage(cmd: List[str], stage_num: int, stage_name: str, env: dict) -> int:
    """
    运行子进程并实时转发输出。
    返回子进程退出码：0 为成功，非 0 为失败。
    """
    emit_progress(stage_num, "running", f"正在执行阶段 {stage_num} ({stage_name})...")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                print(f"[stage{stage_num}] {line}", flush=True)
        proc.wait()
        return proc.returncode
    except Exception as e:
        emit_progress(stage_num, "error", f"阶段 {stage_num} 启动失败: {e}")
        return -1


def stage_1_erp(run_env: dict) -> bool:
    """阶段 1：调用 erp_cli.py 拉取 ERP 组合装数据"""
    erp_cli = str(CURRENT_DIR / "erp" / "src" / "erp_cli.py")
    cmd = [sys.executable, "-X", "utf8", erp_cli, "list", "--days", "29"]
    rc = _run_stage(cmd, 1, "ERP 数据拉取", run_env)
    if rc == 0:
        emit_progress(1, "success", "ERP 数据拉取完成")
        return True
    else:
        emit_progress(1, "error", f"ERP 数据拉取失败，退出码: {rc}")
        return False


def stage_2_sku(working_dir: str, run_env: dict) -> bool:
    """阶段 2：调用 gen_sku_no.py 处理商家编码"""
    gen_sku = str(CURRENT_DIR / "erp" / "gen_sku_no.py")
    cmd = [sys.executable, "-X", "utf8", gen_sku, working_dir]
    rc = _run_stage(cmd, 2, "SKU 商家编码处理", run_env)
    if rc == 0:
        emit_progress(2, "success", "SKU 商家编码处理完成")
        return True
    else:
        emit_progress(2, "error", f"SKU 商家编码处理失败，退出码: {rc}")
        return False


def stage_3_browser(working_dir: str, shop_key: str, run_id: str, run_env: dict) -> bool:
    """阶段 3：执行浏览器自动上架"""
    
    # 将 run_id 相关的专属结果目录注入环境变量
    result_dir = str(CURRENT_DIR / "data" / "results" / run_id)
    os.makedirs(result_dir, exist_ok=True)
    run_env["ALS_RESULT_DIR"] = result_dir

    # 1. 自动启动浏览器并检查端口
    emit_progress(3, "running", f"正在检查并启动浏览器 (端口 {CHROME_DEBUG_PORT})...")
    is_first_launch = False
    try:
        if ensure_debug_chrome:
            if not is_cdp_ready(CHROME_DEBUG_PORT):
                is_first_launch = True
            ensure_debug_chrome(CHROME_DEBUG_PORT, CHROME_USER_DATA)
            emit_progress(3, "success", f"浏览器调试模式已就绪 (端口 {CHROME_DEBUG_PORT})")
        else:
            emit_progress(3, "warn", "无法导入 chrome_manager，跳过自动启动")
    except Exception as e:
        emit_progress(3, "error", f"浏览器启动失败: {e}")
        return False

    # 2. 只有在首次启动浏览器时，才提示用户确认登录状态
    if is_first_launch:
        shop_info = DOUYIN_STORES.get(shop_key, {})
        shop_name = shop_info.get("name", shop_key)
        
        confirm_msg = (
            f"✅ 浏览器已经正常启动！\n"
            f"👉 已经打开抖店页面，请使用手机扫码登录（{shop_name}）。\n"
            "登录成功后，请在对话框中回复“继续”或直接点击确认，以执行自动化上架流程。"
        )
        emit_progress(3, "running", confirm_msg, need_confirm=True)
    else:
        emit_progress(3, "running", "检测到浏览器已启动，跳过登录确认，直接执行自动化流程。")
    
    # 实际运行自动化脚本
    batch_pub = str(CURRENT_DIR / "browser" / "batch_publish.py")
    cmd = [
        sys.executable, "-X", "utf8", batch_pub,
        "--working-dir", working_dir,
        "--shop", shop_key,
    ]
    rc = _run_stage(cmd, 3, "浏览器自动上架", run_env)
    if rc == 0:
        emit_progress(3, "success", "浏览器自动上架完成")
        return True
    else:
        emit_progress(3, "error", f"浏览器自动上架失败，退出码: {rc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Automated Listing Skill Pipeline")
    subparsers = parser.add_subparsers(dest="command")
    
    pipe_parser = subparsers.add_parser("pipeline")
    pipe_parser.add_argument("--input", required=True, help="输入文件或文件夹路径")
    pipe_parser.add_argument("--shop", required=True, help="目标店铺 Key")
    pipe_parser.add_argument("--sync-root", default="", help="同步输出根目录（可选）")
    pipe_parser.add_argument(
        "--stop-after", type=int, default=4,
        help="在第几步之后停止：0=仅校验, 1=校验+ERP, 2=+SKU编码, 3/4=全流程"
    )
    
    args = parser.parse_args()
    
    if args.command == "pipeline":
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        sync_root = (args.sync_root or "").strip() or default_sync_root()

        # 将运行参数注入环境变量，子进程可通过环境变量读取
        run_env = os.environ.copy()
        run_env["ALS_RUN_ID"] = run_id
        run_env["ALS_SYNC_ROOT"] = sync_root

        # 同时调用 os.environ 为本进程汉化（如柙本进程直接调用子模块）
        os.environ["ALS_RUN_ID"] = run_id
        os.environ["ALS_SYNC_ROOT"] = sync_root
        
        try:
            bumped = bump_version_if_needed(str(CURRENT_DIR))
            if bumped:
                emit_progress(0, "running", f"版本号已自动更新: {bumped}")

            # 阶段 0：输入校验
            final_path = stage_0_validate(args.input, args.shop, run_id, sync_root)
            
            if args.stop_after == 0:
                emit_result(True, "阶段 0 校验完成", stop_reason="stop_after=0",
                            run_id=run_id, working_dir=final_path, sync_root=sync_root)
                return

            # 阶段 1： ERP 数据拉取
            emit_progress(1, "pending", "准备执行阶段 1 (ERP 拉取)...")
            if not stage_1_erp(run_env):
                emit_result(False, "ERP 数据拉取失败，流程中止",
                            error_type="STAGE1_FAILED", run_id=run_id)
                sys.exit(1)

            if args.stop_after == 1:
                emit_result(True, "阶段 1 完成（ERP 拉取）", stop_reason="stop_after=1",
                            run_id=run_id, working_dir=final_path, sync_root=sync_root)
                return

            # 阶段 2： SKU 商家编码处理
            emit_progress(2, "pending", "准备执行阶段 2 (SKU 编码处理)...")
            if not stage_2_sku(final_path, run_env):
                emit_result(False, "SKU 商家编码处理失败，流程中止",
                            error_type="STAGE2_FAILED", run_id=run_id)
                sys.exit(1)

            if args.stop_after == 2:
                emit_result(True, "阶段 2 完成（SKU 编码）", stop_reason="stop_after=2",
                            run_id=run_id, working_dir=final_path, sync_root=sync_root)
                return

            # 阶段 3： 浏览器自动上架
            emit_progress(3, "pending", "准备执行阶段 3 (浏览器上架)...")
            if not stage_3_browser(final_path, args.shop, run_id, run_env):
                emit_result(False, "浏览器自动上架失败",
                            error_type="STAGE3_FAILED", run_id=run_id)
                sys.exit(1)

            emit_result(True, "全流程执行完毕",
                        run_id=run_id, working_dir=final_path, sync_root=sync_root)
            
        except Exception as e:
            emit_result(False, f"运行出错: {str(e)}")
            sys.exit(1)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
