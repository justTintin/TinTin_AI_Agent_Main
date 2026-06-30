# -*- coding: utf-8 -*-
"""
素材检索三向映射表（NAS ↔ RustFS ↔ 向量）数据层。

每条记录以视频哈希（video_id）为纽带，关联：
  - nas_smb_path   : 剪辑师访问源文件的 SMB 路径
  - s3_bucket / s3_frame_prefix : AI 前端看抽帧图片的 RustFS 路径
  - ai_tags        : 视觉模型推断的语义标签
  - audio_script   : Whisper 转写的台词文本
  - vector_id      : 向量数据库中的特征 ID（预留）

存储：JSON 文件（VIDEO_INDEX_FILE），遵循项目 Manager + JSON 模式。
"""
import os
import json
import time
import hashlib

from config.paths import VIDEO_INDEX_FILE
from utils.logger_utils import log

# 哈希采样参数（对超大文件采用首尾采样，兼顾速度与唯一性）
_HEAD_BYTES = 2 * 1024 * 1024   # 前 2 MB
_TAIL_BYTES = 1 * 1024 * 1024   # 后 1 MB


def compute_video_hash(file_path: str) -> str:
    """
    计算视频文件的内容指纹（截断 SHA-256，16 hex 字符）。
    对大文件只采样首部 2MB + 尾部 1MB + 文件大小，速度快且足够唯一。
    """
    h = hashlib.sha256()
    try:
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            # 前 2 MB
            h.update(f.read(_HEAD_BYTES))
            # 后 1 MB（若文件够大）
            if size > _HEAD_BYTES + _TAIL_BYTES:
                f.seek(-_TAIL_BYTES, 2)
                h.update(f.read(_TAIL_BYTES))
        # 文件大小也加入，防止内容相同但大小不同的冲突
        h.update(size.to_bytes(8, "little"))
    except Exception as e:
        log.error(f"计算视频哈希失败 {file_path}: {e}")
        return ""
    return h.hexdigest()[:16]


class VideoIndexManager:
    """NAS/RustFS/向量三向映射表的增删改查。"""

    def __init__(self, file_path=None):
        self.file_path = file_path or VIDEO_INDEX_FILE
        self._entries: list[dict] = []
        self.load()

    # ── 持久化 ──────────────────────────────────────────────────
    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 支持直接是列表（旧格式）或带 version 的字典
                self._entries = data if isinstance(data, list) else data.get("entries", [])
            except Exception as e:
                log.error(f"加载视频索引失败: {e}")
                self._entries = []
        else:
            self._entries = []
        return self._entries

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": self._entries},
                          f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.error(f"保存视频索引失败: {e}")

    # ── 增删改查 ─────────────────────────────────────────────────
    def get_by_id(self, video_id: str) -> dict | None:
        return next((e for e in self._entries if e.get("video_id") == video_id), None)

    def get_by_path(self, nas_path: str) -> dict | None:
        nas_norm = os.path.normcase(nas_path)
        return next(
            (e for e in self._entries
             if os.path.normcase(e.get("nas_smb_path", "")) == nas_norm),
            None
        )

    def upsert(self, entry: dict) -> dict:
        """按 video_id 插入或覆盖更新一条记录，并持久化。"""
        vid = entry.get("video_id", "")
        if not vid:
            raise ValueError("entry 必须包含 video_id")
        existing = self.get_by_id(vid)
        if existing:
            existing.update(entry)
            existing["indexed_at"] = int(time.time())
            self.save()
            return existing
        entry.setdefault("indexed_at", int(time.time()))
        entry.setdefault("created_at", int(time.time()))
        self._entries.append(entry)
        self.save()
        return entry

    def delete(self, video_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("video_id") != video_id]
        if len(self._entries) != before:
            self.save()
            return True
        return False

    def all_entries(self) -> list[dict]:
        return list(self._entries)

    # ── 文本检索 ─────────────────────────────────────────────────
    def search(self, keyword: str, field_filter: str = "all") -> list[dict]:
        """
        在 ai_tags + audio_script + nas_smb_path 中进行关键词检索。
        field_filter: 'all' | 'tags' | 'script' | 'path'
        """
        kw = keyword.strip().lower()
        if not kw:
            return list(self._entries)
        results = []
        for e in self._entries:
            hit = False
            if field_filter in ("all", "tags"):
                tags_str = " ".join(e.get("ai_tags", [])).lower()
                if kw in tags_str:
                    hit = True
            if not hit and field_filter in ("all", "script"):
                script = e.get("audio_script", "").lower()
                if kw in script:
                    hit = True
            if not hit and field_filter in ("all", "path"):
                path = e.get("nas_smb_path", "").lower()
                if kw in path:
                    hit = True
            if hit:
                results.append(e)
        return results

    # ── 统计 ─────────────────────────────────────────────────────
    def stats(self) -> dict:
        total = len(self._entries)
        with_tags = sum(1 for e in self._entries if e.get("ai_tags"))
        with_script = sum(1 for e in self._entries if e.get("audio_script"))
        with_frames = sum(1 for e in self._entries if e.get("frame_count", 0) > 0)
        return {
            "total": total,
            "with_tags": with_tags,
            "with_script": with_script,
            "with_frames": with_frames,
        }
