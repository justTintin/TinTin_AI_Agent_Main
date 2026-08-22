"""智能混剪 - 任务级缓存与素材清单（方案二）。

设计：
    .runtime/montage_cache/<job_id>/
      manifest.json    <- 素材清单（唯一数据源）
      splits/          <- 本地视频派生分割片段（写入缓存，不复制原素材）
      downloads/       <- 服务端素材下载目录（默认不下载，仅本地步骤需要时才下）

manifest.entries 三类：
  - local       本地素材：source_path 字符串引用，绝不拷贝原始文件
  - server      素材检索地址：material_id + material:// 引用（concat 走 clip_urls）
  - local_clip  派生分割片段：clip_path 指向缓存 splits/ 下的文件

纯函数式、不依赖 Qt，可安全地在任意线程调用。
"""
import json
import os
import shutil
import time
import uuid

from config.paths import RUNTIME_DIR

from utils.logger_utils import log

# 缓存根：优先跟随「系统设置 → 本地配置 → 缓存目录」
#   - 配置了 cache_dir：<cache_dir>/montage_cache
#   - 未配置：回退 studio/.runtime/montage_cache（frozen 时 = 部署根/studio/.runtime/montage_cache）
_LOCAL_CFG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # noqa: E501
                                "config", "local_config.json")


def _resolve_cache_root():
    """按 local_config.json 的 cache_dir/output_dir 解析混剪缓存根；未配置回退 RUNTIME_DIR。"""
    try:
        if os.path.isfile(_LOCAL_CFG_FILE):
            import json as _json
            with open(_LOCAL_CFG_FILE, encoding="utf-8") as f:
                data = _json.load(f)
            d = (data.get("cache_dir") or data.get("output_dir") or "").strip()
            if d:
                return os.path.join(d, "montage_cache")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return os.path.join(RUNTIME_DIR, "montage_cache")


_MONTAGE_CACHE_ROOT = _resolve_cache_root()


def montage_cache_root():
    """混剪任务缓存根目录（懒创建）。"""
    try:
        os.makedirs(_MONTAGE_CACHE_ROOT, exist_ok=True)
    except OSError as e:
        log.warning(f"创建混剪缓存根目录失败({_MONTAGE_CACHE_ROOT}): {e}")
    return _MONTAGE_CACHE_ROOT

def new_job_id():
    """生成新任务缓存索引（uuid4 hex）。"""
    return uuid.uuid4().hex


def job_root(job_id):
    """单个混剪任务的缓存根目录。"""
    return os.path.join(montage_cache_root(), str(job_id or ""))


def job_splits_dir(job_id):
    """任务级派生分割片段目录（缓存内）。"""
    return os.path.join(job_root(job_id), "splits")


def job_downloads_dir(job_id):
    """任务级服务端素材下载目录（默认不下载，仅本地步骤需要时才用）。"""
    return os.path.join(job_root(job_id), "downloads")


def manifest_path(job_id):
    """任务素材清单（manifest.json）路径。"""
    return os.path.join(job_root(job_id), "manifest.json")


def load_manifest(job_id):
    """读取素材清单；不存在/损坏返回空 dict。"""
    if not job_id:
        return {}
    p = manifest_path(job_id)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"读取混剪素材清单失败({p}): {e}")
        return {}


def save_manifest(job_id, manifest):
    """落盘素材清单；失败只告警不抛。"""
    if not job_id:
        return False
    try:
        p = manifest_path(job_id)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        log.warning(f"保存混剪素材清单失败({job_id}): {e}")
        return False


def _safe_within(path, root):
    """安全校验：path 必须严格位于 root 之下，防路径穿越。"""
    try:
        rp = os.path.realpath(os.path.abspath(path))
        rr = os.path.realpath(os.path.abspath(root))
        return os.path.commonpath([rp, rr]) == rr
    except (ValueError, OSError):
        return False


def clear_job(job_id):
    """删除单个任务的缓存目录（仅清理派生数据，绝不触碰原素材）。"""
    if not job_id:
        return False
    root = montage_cache_root()
    target = job_root(job_id)
    if not _safe_within(target, root):
        log.warning(f"混剪缓存清理被拦截（越界路径）: {target}")
        return False
    try:
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
            log.info(f"已清理混剪任务缓存: {job_id}")
        return True
    except OSError as e:
        log.warning(f"清理混剪任务缓存失败({job_id}): {e}")
        return False


def clear_montage_cache():
    """清空全部混剪任务缓存（含所有 job 的派生分割片段）。"""
    root = montage_cache_root()
    if not os.path.isdir(root):
        return 0
    removed = 0
    try:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if os.path.isdir(full) and _safe_within(full, root):
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
        log.info(f"已清空混剪缓存，移除 {removed} 个任务目录")
    except OSError as e:
        log.warning(f"清空混剪缓存失败: {e}")
    return removed


def clear_abandoned_jobs(max_age_hours=24):
    """清理超过 max_age_hours 未活动的任务缓存（含 manifest 等）。"""
    root = montage_cache_root()
    if not os.path.isdir(root):
        return 0
    removed = 0
    now = time.time()
    try:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if not (os.path.isdir(full) and _safe_within(full, root)):
                continue
            try:
                age_h = (now - os.path.getmtime(full)) / 3600.0
            except OSError:
                continue
            if age_h >= max_age_hours:
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
    except OSError as e:
        log.warning(f"清理过期混剪任务缓存失败: {e}")
    if removed:
        log.info(f"已清理 {removed} 个过期混剪任务缓存(>{max_age_hours}h)")
    return removed
