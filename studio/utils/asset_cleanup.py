"""资产清理：应用启动时清理中间产物，释放 NAS/本地空间。

设计原则：
  · 零风险优先：第一层只删纯垃圾（.temp_concat 残留、游离 norm_*.mp4、临时目录过期文件）
  · 缓存按年龄：第二层按修改时间清理过期缓存（splits/voices 等），可重建故安全
  · 最终产物不动：任何用户成品（montage_concat_*/dubbed_*/final/封面图...）绝不删
  · 安全防护：路径穿越检查 + 严格文件名/前缀匹配 + 逐项异常隔离 + 只扫固定目录

纯函数式，不依赖 Qt，可在任意线程调用（启动时建议后台线程，避免阻塞 UI）。
"""
import contextlib
import os
import shutil
import time
from typing import Any

from config.paths import OUTPUTS_DIR, TMP_DIR

from utils.logger_utils import log

# 最终产物前缀——这些是用户成品，清理时一律跳过（白名单保护）
_FINAL_PREFIXES = (
    "montage_concat_", "montage_beat_", "dubbed_", "final_",
    "mg_", "cover_", "dreamina_", "product_",
)

# 最终产物后缀（含 _no_sub 这种语义后缀）
_FINAL_SUFFIXES = ("_no_sub.mp4",)


def _is_within(path, root):
    """安全检查：path 必须严格位于 root 之下，防止路径穿越（如 ../ 逃逸）。"""
    try:
        rp = os.path.realpath(os.path.abspath(path))
        rr = os.path.realpath(os.path.abspath(root))
        return os.path.commonpath([rp, rr]) == rr
    except (ValueError, OSError):
        return False


def _is_final_product(name):
    """判断文件名是否属于最终产物（用户成品），是则跳过不删。"""
    for p in _FINAL_PREFIXES:
        if name.startswith(p):
            return True
    return any(name.endswith(s) for s in _FINAL_SUFFIXES)


def _file_age_days(path):
    """返回文件距上次修改的天数；失败返回 None。"""
    try:
        mtime = os.path.getmtime(path)
        return max(0.0, (time.time() - mtime) / 86400.0)
    except OSError:
        return None


def _safe_remove(path, stats):
    """安全删除单个文件，累计统计。失败只告警不抛。"""
    try:
        size = os.path.getsize(path)
        os.remove(path)
        stats["deleted"] += 1
        stats["bytes"] += size
    except OSError as e:
        stats["errors"].append(f"{os.path.basename(path)}: {e}")


def _safe_rmtree(path, stats):
    """安全删除整个目录，累计统计。失败只告警不抛。"""
    try:
        size = 0
        for root_d, _, files in os.walk(path):
            for f in files:
                with contextlib.suppress(OSError):
                    size += os.path.getsize(os.path.join(root_d, f))
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            stats["deleted"] += 1
            stats["bytes"] += size
    except OSError as e:
        stats["errors"].append(f"rmtree {os.path.basename(path)}: {e}")


# ── 第一层：零风险纯垃圾 ────────────────────────────────────────────────

def _cleanup_tmp_dir(tmp_dir, max_age_days, stats):
    """清理固定临时目录（.runtime/tmp）下超过 max_age_days 天的文件。

    这里是 ASR 抽音频、直播切片临时帧、封面帧等临时文件的堆积地，
    实测会累积数 GB，且本就是临时文件，删除零风险。
    """
    if not os.path.isdir(tmp_dir):
        return
    try:
        for name in os.listdir(tmp_dir):
            full = os.path.join(tmp_dir, name)
            if not _is_within(full, tmp_dir):
                continue
            age = _file_age_days(full)
            if age is None or age < max_age_days:
                continue  # 未过期，保留
            if os.path.isdir(full):
                _safe_rmtree(full, stats)
                log.info(f"[启动清理] 删除临时目录 {name} (age={age:.1f}d)")
            else:
                _safe_remove(full, stats)
                log.info(f"[启动清理] 删除临时文件 {name} (age={age:.1f}d)")
    except OSError as e:
        stats["errors"].append(f"scan tmp_dir: {e}")


def _cleanup_temp_concat_and_norm(root_dir, stats):
    """清理 root_dir（含子目录）下的 .temp_concat/ 目录和游离的 norm_*.mp4。

    .temp_concat 是标准化转码临时目录，正常流程合成结束已 rmtree，残留必为异常中断；
    norm_*.mp4 是其中的标准化中间文件，本应随目录删除，游离的是泄漏。
    """
    if not os.path.isdir(root_dir):
        return
    for root_d, dirs, files in os.walk(root_dir):
        # 删除 .temp_concat 子目录
        for d in list(dirs):
            if d == ".temp_concat":
                full = os.path.join(root_d, d)
                if _is_within(full, root_dir):
                    _safe_rmtree(full, stats)
                    log.info(f"[启动清理] 删除残留 .temp_concat: {full}")
                    dirs.remove(d)  # 不再下钻
        # 删除游离 norm_*.mp4（仅限中间文件命名，绝不在 _FINAL_PREFIXES 内）
        for f in files:
            if f.startswith("norm_") and f.lower().endswith(".mp4"):
                full = os.path.join(root_d, f)
                if _is_within(full, root_dir):
                    _safe_remove(full, stats)
                    log.info(f"[启动清理] 删除游离中间文件 {f}")


# ── 第二层：缓存型中间产物（按年龄删）────────────────────────────────────

def _cleanup_aged_cache(root_dir, max_age_days, stats):
    """清理 root_dir 下超期的缓存型中间产物：splits/、voices/、_shots.json。

    这些可重建（重新分割/重新分析/重新配音），超期清理避免 NAS 堆积。
    """
    if not os.path.isdir(root_dir):
        return

    # 1) 遍历子目录，找名为 splits/ 或 voices/ 的目录
    for root_d, dirs, _files in os.walk(root_dir):
        for d in list(dirs):
            if d not in ("splits", "voices"):
                continue
            sub = os.path.join(root_d, d)
            if not _is_within(sub, root_dir):
                continue
            _cleanup_aged_subdir(sub, d, max_age_days, stats)
            # splits/voices 清空后保留空目录（下次流程会用），不删目录本身

    # 2) 清理超期的 _shots.json（镜头分析缓存，跟随源视频但本次保守只扫 root_dir 树）
    for root_d, _dirs, files in os.walk(root_dir):
        for f in files:
            if not f.endswith("_shots.json"):
                continue
            full = os.path.join(root_d, f)
            if not _is_within(full, root_dir):
                continue
            age = _file_age_days(full)
            if age is None or age < max_age_days:
                continue
            _safe_remove(full, stats)
            log.info(f"[启动清理] 删除过期镜头分析缓存 {f} (age={age:.1f}d)")


def _cleanup_aged_subdir(sub_dir, dir_name, max_age_days, stats):
    """清理 splits/ 或 voices/ 目录下超期的文件。"""
    try:
        for name in os.listdir(sub_dir):
            full = os.path.join(sub_dir, name)
            if not _is_within(full, sub_dir):
                continue
            # 最终产物保护：哪怕在 splits/voices 里也跳过用户成品
            if _is_final_product(name):
                continue
            age = _file_age_days(full)
            if age is None or age < max_age_days:
                continue
            if dir_name == "splits":
                # 只删分镜片段命名（shot_*），其它命名不动
                if not (name.startswith("shot_") and name.lower().endswith((".mp4", ".m4v"))):  # noqa: E501
                    continue
            elif dir_name == "voices":  # noqa: SIM102
                # 只删 voice_*.wav 和 *.timing.json
                if not (name.lower().endswith(".wav") or name.endswith(".timing.json")):
                    continue
            _safe_remove(full, stats)
            log.info(f"[启动清理] 删除过期缓存 {dir_name}/{name} (age={age:.1f}d)")
    except OSError as e:
        stats["errors"].append(f"scan {dir_name}: {e}")


# ── 入口 ────────────────────────────────────────────────────────────────

def cleanup_on_startup(max_age_days=7, tmp_max_age_days=1):
    """应用启动时清理中间产物。

    返回 dict: {"deleted": int, "bytes": int, "errors": list[str]}
    max_age_days: 缓存型中间产物（splits/voices/_shots.json）的保留天数
    tmp_max_age_days: 临时目录文件的保留天数（默认 1 天，过期即清）
    """
    stats: dict[str, Any] = {"deleted": 0, "bytes": 0, "errors": []}
    log.info(f"[启动清理] 开始（tmp>{tmp_max_age_days}d, cache>{max_age_days}d）")

    try:
        # 第一层：零风险纯垃圾
        _cleanup_tmp_dir(TMP_DIR, tmp_max_age_days, stats)
        _cleanup_temp_concat_and_norm(OUTPUTS_DIR, stats)
        # 第二层：缓存型按年龄
        _cleanup_aged_cache(OUTPUTS_DIR, max_age_days, stats)
    except Exception as e:  # 启动清理整体异常
        stats["errors"].append(f"cleanup_on_startup: {e}")
        log.exception(f"[启动清理] 发生未预期异常: {e}")

    freed_mb = stats["bytes"] // 1024 // 1024
    log.info(f"[启动清理] 完成: 删除 {stats['deleted']} 项, 释放 {freed_mb}MB, 错误 {len(stats['errors'])} 项")  # noqa: E501
    return stats
