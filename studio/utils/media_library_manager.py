# -*- coding: utf-8 -*-
"""
素材管理（媒体库）数据层。

采用「挂载目录索引」模式：只登记外部目录的路径（本地磁盘 / 网络磁盘 UNC），
原地引用、不复制导入。每个挂载目录按 产品 / 项目 分组并可打标签。
浏览时按需扫描目录，列出图片 / 视频 / 音频文件。
（即梦等生成的素材未来也可作为挂载目录纳入。）

存储：JSON 文件（config.paths.MEDIA_LIBRARY_FILE），沿用项目「Manager 类 + JSON」模式。
"""
import os
import json
import time

from config.paths import MEDIA_LIBRARY_FILE
from utils.logger_utils import log

# 分组类型
KINDS = ["产品", "项目", "其他"]

# 媒体类型 → 扩展名
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma"}


def media_type(path):
    """返回 'image' / 'video' / 'audio' / None。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def scan_directory(path, type_filter=None, recursive=True, limit=100000):
    """
    扫描目录下的媒体文件（原地引用，不复制）。
    用 os.scandir 遍历：DirEntry.stat() 复用 scandir 缓存，避免逐文件 getsize 系统调用，
    在数万文件时显著更快。limit 为软上限，防止超大目录（如几十万文件）拖垮。
    type_filter: None=全部，或 'image'/'video'/'audio'。
    返回 [{name, path, type, ext, size}]，按类型+名称排序。
    """
    results = []
    if not path or not os.path.isdir(path):
        return results
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                stack.append(entry.path)
                            continue
                        mt = media_type(entry.name)
                        if not mt or (type_filter and mt != type_filter):
                            continue
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                        results.append({
                            "name": entry.name,
                            "path": entry.path,
                            "type": mt,
                            "ext": os.path.splitext(entry.name)[1].lower(),
                            "size": size,
                        })
                        if len(results) >= limit:
                            results.sort(key=lambda x: (x["type"], x["name"].lower()))
                            return results
                    except OSError:
                        continue
        except OSError:
            continue
    results.sort(key=lambda x: (x["type"], x["name"].lower()))
    return results


class MediaLibraryManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or MEDIA_LIBRARY_FILE
        self.mounts = []
        self.load()

    # ---------- 持久化 ----------
    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.mounts = json.load(f)
            except Exception as e:
                log.error(f"加载媒体库失败: {e}")
                self.mounts = []
        else:
            self.mounts = []
        return self.mounts

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.mounts, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"保存媒体库失败: {e}")

    # ---------- 工具 ----------
    @staticmethod
    def _norm_path(p):
        return os.path.normpath(str(p or "").strip())

    @staticmethod
    def parse_tags(text):
        """把 '标签1, 标签2 标签3' 解析为去重列表。"""
        import re
        return [t for t in dict.fromkeys(re.split(r"[,，\s]+", str(text or "").strip())) if t]

    # ---------- 增删改查 ----------
    def add_mount(self, path, name="", kind="", group="", tags=None):
        path = self._norm_path(path)
        if not path:
            return False, "目录路径不能为空", None
        if any(self._norm_path(m["path"]) == path for m in self.mounts):
            return False, "该目录已添加。", None
        mount = {
            "id": os.urandom(8).hex(),
            "path": path,
            "name": (name or os.path.basename(path) or path).strip(),
            "kind": (kind or "").strip(),
            "group": (group or "").strip(),
            "tags": list(tags or []),
            "created_at": int(time.time()),
        }
        self.mounts.append(mount)
        self.save()
        return True, "已添加目录。", mount

    def update_mount(self, mount_id, name=None, kind=None, group=None, tags=None):
        m = self.get(mount_id)
        if not m:
            return False, "未找到该目录。", None
        if name is not None:
            m["name"] = name.strip()
        if kind is not None:
            m["kind"] = kind.strip()
        if group is not None:
            m["group"] = group.strip()
        if tags is not None:
            m["tags"] = list(dict.fromkeys(tags))  # 去重，保留顺序
        self.save()
        return True, "已保存。", m

    def remove_mount(self, mount_id):
        before = len(self.mounts)
        self.mounts = [m for m in self.mounts if m.get("id") != mount_id]
        if len(self.mounts) != before:
            self.save()
            return True
        return False

    def get(self, mount_id):
        return next((m for m in self.mounts if m.get("id") == mount_id), None)

    def all_mounts(self):
        return list(self.mounts)

    def grouped(self):
        """返回 {kind: {group: [mount...]}}，供 UI 树状展示。"""
        tree = {}
        for m in self.mounts:
            kind = m.get("kind", "").strip() or "未分类"
            group = m.get("group", "").strip() or "默认分组"
            tree.setdefault(kind, {}).setdefault(group, []).append(m)
        return tree

    def all_tags(self):
        tags = set()
        for m in self.mounts:
            tags.update(m.get("tags", []))
        return sorted(tags)
