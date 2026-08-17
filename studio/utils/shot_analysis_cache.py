# -*- coding: utf-8 -*-
"""镜头分析结果缓存：把「生成镜头分析」（服务端 /material/score_clip）返回的
评分 / 景别 / 产品 / 型号 / 描述 / 其他维度持久化到视频工作目录的 sidecar JSON，
避免重新打开应用或对同一视频重新分割后只剩"画面描述"、其他字段全部丢失。

存储：{video_workspace_dir}/{video_basename}_shots.json（跟随源视频走，删视频即清缓存）。

Key 策略（内容寻址，跨重分割稳定命中）：
    "{shot_filename}|{size}|{mtime}|{md5_首尾各256KB}"
  - 文件名 + 大小 + mtime 作快速预筛（绝大多数变化能拦住，免读文件）
  - 首尾各读 256KB 算 md5 作内容指纹：同一视频重新分割生成的相同内容片段
    即使序号变化（分割阈值微调导致错位）也能命中；不同内容不会误命中
  - 不读全文件，平衡准确性与速度（镜头片段通常 < 几十 MB）

设计参考：utils/video_prediction_manager.py 的 Manager + JSON 模式。
"""
import os
import json
import time
import hashlib

from utils.logger_utils import log

# 指纹采样：首尾各读这么多字节算 md5（256KB 够区分不同镜头，又不会拖慢）
_FINGERPRINT_BYTES = 256 * 1024


def _clip_key(clip_path):
    """生成镜头文件的内容寻址 key。文件不存在/不可读时回退到纯路径。

    只用「大小 + 内容指纹」作 key，刻意不纳入文件名和 mtime —— 因为重新分割时
    文件会被删重建（mtime 变），阈值微调还会让镜头序号错位（文件名变）。
    只要片段内容相同就能命中，这正是「跨重分割复用」的关键。
    """
    try:
        if not os.path.isfile(clip_path):
            return clip_path
        size = os.path.getsize(clip_path)
        # 小文件直接全量算；大文件采样首尾
        h = hashlib.md5()
        with open(clip_path, "rb") as f:
            if size <= _FINGERPRINT_BYTES * 2:
                h.update(f.read())
            else:
                h.update(f.read(_FINGERPRINT_BYTES))
                f.seek(-_FINGERPRINT_BYTES, os.SEEK_END)
                h.update(f.read(_FINGERPRINT_BYTES))
        return f"{size}|{h.hexdigest()}"
    except Exception as e:
        log.warning(f"生成镜头缓存 key 失败({clip_path}): {e}")
        return clip_path


class ShotAnalysisCache:
    """单个源视频的镜头分析 sidecar 缓存。"""

    def __init__(self, workspace_dir, video_basename):
        # 路径与 _save_split_srt 的 srt 同目录：{video_dir}/{video_basename}/
        self.file_path = os.path.join(workspace_dir or "", f"{video_basename}_shots.json")
        self._items = {}  # key -> {score, desc, shot_type, product, model, extra, updated_at}
        self.load()

    def load(self):
        """从磁盘加载缓存；文件不存在或损坏时返回空 dict。"""
        self._items = {}
        if not self.file_path or not os.path.exists(self.file_path):
            return self._items
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容 list / dict 两种历史格式
            if isinstance(data, dict):
                self._items = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except Exception as e:
            log.warning(f"加载镜头分析缓存失败({self.file_path}): {e}")
            self._items = {}
        return self._items

    def save(self):
        """落盘。失败只告警不抛，避免影响主流程。"""
        if not self.file_path:
            return
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f"保存镜头分析缓存失败({self.file_path}): {e}")

    def get(self, clip_path):
        """按镜头文件查缓存，命中返回 dict，未命中返回 None。"""
        return self._items.get(_clip_key(clip_path))

    def upsert(self, clip_path, data):
        """写入/更新一条镜头分析结果并立即落盘。

        data = {score, desc, shot_type, product, model, extra, ...}
        """
        if not data:
            return
        entry = dict(data)  # 浅拷贝，避免持有调用方的可变引用
        entry["updated_at"] = int(time.time())
        self._items[_clip_key(clip_path)] = entry
        self.save()
