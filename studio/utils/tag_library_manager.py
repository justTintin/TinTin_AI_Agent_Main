# -*- coding: utf-8 -*-
"""
素材标签库管理器。

标签库定义了品牌/产品类型/分类的规范名称和别名。
当素材目录以选题命名（如"千问AI眼镜"）挂入素材管理时，
自动匹配标签库并为挂载目录打上规范标签；
素材管理页面可随时触发"刷新标签"，对所有挂载目录重新应用。

数据文件：studio/data/tag_library.json
"""
import os
import re
import json
import time
import uuid

from config.paths import TAG_LIBRARY_FILE
from utils.logger_utils import log

_DEFAULT_DATA = {
    "version": 1,
    "tags": [
        {
            "id": "ai_glasses_qwen",
            "name": "千问AI眼镜",
            "aliases": ["千问眼镜", "Qwen眼镜", "Qwen AI", "通义眼镜"],
            "brand": "阿里/通义千问",
            "type": "AI眼镜",
            "category": "智能硬件",
            "color": "#3B82F6",
            "created_at": 0,
        }
    ],
    "types": ["AI眼镜", "手机", "耳机", "平板", "智能手表",
              "键盘", "鼠标", "音箱", "摄像头", "路由器"],
    "categories": ["智能硬件", "消费电子", "外设", "办公", "游戏", "影音"],
}


class TagLibraryManager:
    def __init__(self):
        self._data = None

    # ── 持久化 ─────────────────────────────────────────────────────────────
    def _load(self):
        if os.path.exists(TAG_LIBRARY_FILE):
            try:
                with open(TAG_LIBRARY_FILE, encoding="utf-8") as f:
                    self._data = json.load(f)
                return
            except Exception as e:
                log.warning(f"TagLibraryManager: 读取失败，重置。{e}")
        import copy
        self._data = copy.deepcopy(_DEFAULT_DATA)
        self._save()

    def _save(self):
        try:
            with open(TAG_LIBRARY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"TagLibraryManager: 写入失败。{e}")

    @property
    def data(self):
        if self._data is None:
            self._load()
        return self._data

    # ── 只读访问 ────────────────────────────────────────────────────────────
    @property
    def tags(self):
        return self.data.get("tags", [])

    @property
    def types(self):
        return self.data.get("types", [])

    @property
    def categories(self):
        return self.data.get("categories", [])

    def get_tag(self, tag_id):
        return next((t for t in self.tags if t["id"] == tag_id), None)

    # ── 匹配逻辑 ────────────────────────────────────────────────────────────
    def match_topic(self, topic: str) -> list[str]:
        """
        给定选题/目录名，返回匹配到的规范标签列表。
        同时返回 name（规范名）、type（类型）、category（分类）。
        顺序：name 优先，去重。
        """
        if not topic:
            return []
        topic_lower = topic.lower()
        result = []
        seen = set()

        def _add(v):
            if v and v not in seen:
                seen.add(v)
                result.append(v)

        for entry in self.tags:
            # 检查 name + aliases 是否出现在 topic 中（不区分大小写）
            candidates = [entry.get("name", "")] + entry.get("aliases", [])
            if any(c.lower() in topic_lower or topic_lower in c.lower()
                   for c in candidates if c):
                _add(entry.get("name"))
                _add(entry.get("type"))
                _add(entry.get("category"))
                _add(entry.get("brand"))

        return [t for t in result if t]

    # ── 批量自动打标 ────────────────────────────────────────────────────────
    def auto_tag_mounts(self, media_manager) -> int:
        """
        遍历 media_manager 所有挂载，用目录名匹配标签库，自动补充标签。
        只追加缺失的规范标签，不覆盖用户手动设置的标签。
        返回更新了标签的挂载数量。
        """
        updated = 0
        for mount in media_manager.mounts:
            dir_name = os.path.basename(mount.get("path", "").rstrip("/\\"))
            matched = self.match_topic(dir_name)
            if not matched:
                continue
            existing = set(mount.get("tags", []))
            new_tags = [t for t in matched if t not in existing]
            if new_tags:
                media_manager.update_mount(
                    mount["id"],
                    tags=sorted(existing | set(new_tags)),
                )
                updated += 1
        if updated:
            log.info(f"TagLibraryManager: 自动标签更新了 {updated} 个挂载目录")
        return updated

    # ── 增删改 ──────────────────────────────────────────────────────────────
    def add_tag(self, name, brand="", tag_type="", category="",
                aliases=None, color="") -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name.strip(),
            "aliases": [a.strip() for a in (aliases or []) if a.strip()],
            "brand": brand.strip(),
            "type": tag_type.strip(),
            "category": category.strip(),
            "color": color or "#6B7280",
            "created_at": int(time.time()),
        }
        self.data.setdefault("tags", []).append(entry)
        self._save()
        return entry

    def update_tag(self, tag_id, **kwargs):
        t = self.get_tag(tag_id)
        if not t:
            return False
        for k, v in kwargs.items():
            if k in t:
                t[k] = v
        self._save()
        return True

    def delete_tag(self, tag_id) -> bool:
        before = len(self.data["tags"])
        self.data["tags"] = [t for t in self.data["tags"] if t["id"] != tag_id]
        if len(self.data["tags"]) < before:
            self._save()
            return True
        return False

    def add_type(self, type_name: str):
        t = type_name.strip()
        if t and t not in self.data.get("types", []):
            self.data.setdefault("types", []).append(t)
            self._save()

    def add_category(self, cat: str):
        c = cat.strip()
        if c and c not in self.data.get("categories", []):
            self.data.setdefault("categories", []).append(c)
            self._save()
