# -*- coding: utf-8 -*-
"""
数据备份 / 还原 / 迁移。

基于 data_registry：导出一个带时间戳的 zip（可选含密钥 / 含产出），
还原时先自动安全备份当前数据再覆盖；并支持素材挂载根路径批量重定位（换机器迁移用）。
"""
import os
import io
import json
import time
import zipfile

from config.paths import PROJECT_ROOT, BACKUP_DIR, MEDIA_LIBRARY_FILE
from utils.data_registry import DATA_ITEMS, OUTPUTS_ITEM, selected_items, rel_path
from utils.logger_utils import log


def _add_path_to_zip(zf, item, progress=None):
    p = item["path"]
    if not os.path.exists(p):
        return 0
    n = 0
    if item["kind"] == "file":
        zf.write(p, rel_path(p)); n = 1
    else:
        for root, _d, files in os.walk(p):
            for f in files:
                full = os.path.join(root, f)
                try:
                    zf.write(full, rel_path(full)); n += 1
                except OSError:
                    pass
    if progress:
        progress(f"已打包：{item['label']}（{n} 个文件）")
    return n


def backup(out_zip=None, include_secrets=True, include_outputs=False, progress=None):
    """导出备份 zip，返回 zip 路径。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out_zip = out_zip or os.path.join(BACKUP_DIR, time.strftime("backup_%Y%m%d_%H%M%S.zip"))
    items = selected_items(include_secrets, include_outputs)
    manifest = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "include_secrets": include_secrets,
        "include_outputs": include_outputs,
        "items": [it["key"] for it in items],
        "schema": 1,
    }
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        total = 0
        for it in items:
            total += _add_path_to_zip(zf, it, progress)
    if progress:
        progress(f"备份完成：{out_zip}")
    log.info(f"数据备份完成: {out_zip}")
    return out_zip


def read_manifest(zip_path):
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if "backup_manifest.json" in zf.namelist():
                return json.loads(zf.read("backup_manifest.json").decode("utf-8"))
    except Exception:
        pass
    return None


# 还原只允许覆盖这些已知数据位置（防止 zip 被篡改后写到别处）
_ALLOWED_PREFIXES = ("config/", "data/", "accounts/", "assets/voice_samples/", "outputs/")
_ALLOWED_FILES = ("config.ini",)


def _is_allowed(rel):
    rel = rel.replace("\\", "/")
    if ".." in rel.split("/"):
        return False
    return rel in _ALLOWED_FILES or rel.startswith(_ALLOWED_PREFIXES)


def restore(zip_path, progress=None):
    """从备份 zip 还原（先自动安全备份当前数据，再覆盖）。返回 (恢复文件数, 安全备份路径)。"""
    if not os.path.isfile(zip_path):
        raise RuntimeError("备份文件不存在。")
    # 1) 先安全备份当前（含密钥，不含 outputs），避免误覆盖无法回退
    safe = os.path.join(BACKUP_DIR, time.strftime("auto_before_restore_%Y%m%d_%H%M%S.zip"))
    if progress:
        progress("还原前先安全备份当前数据…")
    backup(safe, include_secrets=True, include_outputs=False)
    # 2) 解压覆盖（仅限白名单路径）
    restored = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            rel = info.filename
            if rel == "backup_manifest.json" or info.is_dir():
                continue
            if not _is_allowed(rel):
                log.warning(f"还原跳过非法路径: {rel}")
                continue
            dest = os.path.join(PROJECT_ROOT, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
            restored += 1
    if progress:
        progress(f"还原完成：恢复 {restored} 个文件（当前数据已安全备份到 {safe}）")
    log.info(f"数据还原完成: {zip_path} -> {restored} 文件; 安全备份: {safe}")
    return restored, safe


def relocate_media_root(old_prefix, new_prefix):
    """素材挂载根路径批量重定位（换机器/换盘符迁移后用）。返回改动条数。"""
    old_prefix = (old_prefix or "").strip()
    new_prefix = (new_prefix or "").strip()
    if not old_prefix or not new_prefix:
        raise RuntimeError("旧/新根路径都不能为空。")
    if not os.path.isfile(MEDIA_LIBRARY_FILE):
        return 0
    with open(MEDIA_LIBRARY_FILE, "r", encoding="utf-8") as f:
        mounts = json.load(f)
    changed = 0
    on = os.path.normpath(old_prefix)
    for m in mounts:
        p = os.path.normpath(m.get("path", ""))
        if p == on or p.startswith(on + os.sep):
            m["path"] = os.path.normpath(new_prefix + p[len(on):])
            changed += 1
    if changed:
        with open(MEDIA_LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump(mounts, f, ensure_ascii=False, indent=4)
    log.info(f"素材根路径重定位: {old_prefix} -> {new_prefix}, 改动 {changed} 条")
    return changed
