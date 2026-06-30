# -*- coding: utf-8 -*-
"""
「我的知识库」数据层。

存放用户自有的创作知识，当前用于承载「品牌调性 / 话术风格」，在文案创作时作为
风格指引叠加进 LLM prompt。与「产品资料」(knowledge_base_manager) 是两套独立库。

存储：JSON 文件（config.paths.MY_KNOWLEDGE_FILE），沿用项目「Manager 类 + JSON」模式。
"""
import os
import json
import time

from config.paths import MY_KNOWLEDGE_FILE, KNOWLEDGE_MATERIALS_DIR
from utils.logger_utils import log

# 风格参考样本类型：从素材浏览器同步的关注/收藏视频文章（标题+文案文本为主，关联源/媒体）
REFERENCE_TYPE = "风格参考样本"
# 风格化类型：从参考样本提炼的写作风格画像（HOW to write，不是 WHAT）
STYLIZATION_TYPE = "风格化"

# 风格化维度：第一维度是账号，其余按内容类型/产品品类/行业垂类
STYLE_DIMS = {
    "account":      "账号风格",   # 特定账号/创作者的写作风格
    "content_type": "内容类型",   # 科技类/科普类/剧情类/玩梗类/硬核类
    "product_cat":  "产品品类",   # 笔电/鼠标类/键盘类/外设类/台机类/苹果类/AI类
    "industry":     "行业垂类",   # 科技类/财经类/电商行业类
}
CONTENT_TYPE_OPTIONS = ["科技类", "科普类", "剧情类", "玩梗类", "硬核类"]
PRODUCT_CAT_OPTIONS  = ["笔电", "鼠标类", "键盘类", "外设类", "台机类", "苹果类", "AI类"]
INDUSTRY_OPTIONS     = ["科技类", "财经类", "电商行业类"]

# 条目类型（场景）。可扩展，风格化排在最前供文案页默认勾选。
ENTRY_TYPES = [STYLIZATION_TYPE, "品牌调性", "话术风格", "人设口吻", "选题方向", "禁用词/红线", REFERENCE_TYPE, "其他"]


class MyKnowledgeManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or MY_KNOWLEDGE_FILE
        self.items = []
        self.load()

    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8-sig") as f:
                    self.items = json.load(f)
            except Exception as e:
                log.error(f"加载我的知识库失败: {e}")
                self.items = []
        else:
            self.items = []
        return self.items

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"保存我的知识库失败: {e}")

    def all_items(self):
        return list(self.items)

    def get(self, item_id):
        return next((it for it in self.items if it.get("id") == item_id), None)

    def add_item(self, name, entry_type="", content=""):
        name = (name or "").strip()
        if not name:
            return False, "名称不能为空", None
        if not (content or "").strip():
            return False, "内容不能为空", None
        item = {
            "id": os.urandom(8).hex(),
            "name": name,
            "type": (entry_type or "").strip(),
            "content": content.strip(),
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        self.items.append(item)
        self.save()
        return True, "已添加。", item

    def update_item(self, item_id, name, entry_type, content):
        target = self.get(item_id)
        if not target:
            return False, "未找到该条目。", None
        if not (name or "").strip():
            return False, "名称不能为空", None
        if not (content or "").strip():
            return False, "内容不能为空", None
        target.update({
            "name": name.strip(),
            "type": (entry_type or "").strip(),
            "content": content.strip(),
            "updated_at": int(time.time()),
        })
        self.save()
        return True, "已保存。", target

    def remove_item(self, item_id):
        before = len(self.items)
        self.items = [it for it in self.items if it.get("id") != item_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def import_browser_samples(self, manifest_path=None, items_path=None):
        """
        同步记录素材：合并 kb_sync.json（已下载，含文案/媒体路径）与 kb_items.json
        （浏览器全量收藏记录，包含未下载条目）后导入「风格参考样本」。
        kb_sync.json 数据优先（更丰富）；kb_items.json 补充其余未下载收藏。
        """
        sync_path = manifest_path or os.path.join(KNOWLEDGE_MATERIALS_DIR, "kb_sync.json")
        raw_path = items_path or os.path.join(KNOWLEDGE_MATERIALS_DIR, "kb_items.json")

        # 合并两个来源：url → entry，kb_sync 优先（数据更丰富）
        all_entries = {}
        if os.path.exists(sync_path):
            try:
                with open(sync_path, "r", encoding="utf-8-sig") as f:
                    for e in json.load(f):
                        url = (e.get("url") or "").strip()
                        all_entries[url or f"_s{len(all_entries)}"] = e
            except Exception:
                pass
        if os.path.exists(raw_path):
            try:
                with open(raw_path, "r", encoding="utf-8-sig") as f:
                    for e in json.load(f):
                        url = (e.get("url") or "").strip()
                        if url and url not in all_entries:
                            all_entries[url] = e
            except Exception:
                pass

        if not all_entries:
            return 0, 0, (
                "未找到可导入的数据。\n"
                "请先在素材浏览器「收藏记录」标签中收集内容，或下载后再同步。"
            )

        existing_urls = {
            (it.get("source") or {}).get("url")
            for it in self.items if (it.get("source") or {}).get("url")
        }
        added = skipped = 0
        for e in all_entries.values():
            url = (e.get("url") or "").strip()
            if url and url in existing_urls:
                skipped += 1
                continue
            title = (e.get("title") or "").strip()
            caption = (e.get("caption") or "").strip()
            platform_name = (e.get("platformName") or e.get("platform") or "").strip()
            creator = (e.get("creatorName") or "").strip()
            content_parts = [p for p in (title, caption) if p]
            content = "\n\n".join(content_parts) or "(无文本)"
            name = f"[{platform_name}][{creator}] {title[:30]}".strip()
            item = {
                "id": os.urandom(8).hex(),
                "name": name or "风格样本",
                "type": REFERENCE_TYPE,
                "content": content,
                "source": {
                    "platform": e.get("platform", ""),
                    "platformName": platform_name,
                    "creator": creator,
                    "url": url,
                    "media_path": e.get("mediaPath", ""),
                    "date": e.get("date", ""),
                    "heat": e.get("heat", ""),
                    "media_type": e.get("type", ""),
                    "is_collected": bool(e.get("isCollected", False)),
                    "is_liked": bool(e.get("isLiked", False)),
                },
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
            self.items.append(item)
            if url:
                existing_urls.add(url)
            added += 1
        if added:
            self.save()
        return added, skipped, f"导入完成：新增 {added} 条，跳过 {skipped} 条（已存在）。"

    def import_kb_items(self, items_path=None):
        """
        导入收藏记录：从浏览器全量收藏记录（kb_items.json）导入「风格参考样本」。
        无需下载，仅导入标题等基础文本信息，适合快速建立风格参考。
        """
        fpath = items_path or os.path.join(KNOWLEDGE_MATERIALS_DIR, "kb_items.json")
        if not os.path.exists(fpath):
            return 0, 0, (
                f"未找到收藏记录：{fpath}\n"
                "请先在素材浏览器「收藏记录」标签中收集内容，收藏记录会自动同步到此路径。"
            )
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                entries = json.load(f)
        except Exception as e:
            return 0, 0, f"读取收藏记录失败：{e}"
        if not isinstance(entries, list):
            return 0, 0, "收藏记录格式异常（应为数组）。"

        existing_urls = {
            (it.get("source") or {}).get("url")
            for it in self.items if (it.get("source") or {}).get("url")
        }
        added = skipped = 0
        for e in entries:
            url = (e.get("url") or "").strip()
            if url and url in existing_urls:
                skipped += 1
                continue
            title = (e.get("title") or "").strip()
            caption = (e.get("caption") or "").strip()
            platform_name = (e.get("platformName") or e.get("platform") or "").strip()
            creator = (e.get("creatorName") or "").strip()
            content_parts = [p for p in (title, caption) if p]
            content = "\n\n".join(content_parts) or "(无文本)"
            name = f"[{platform_name}][{creator}] {title[:30]}".strip()
            item = {
                "id": os.urandom(8).hex(),
                "name": name or "收藏记录",
                "type": REFERENCE_TYPE,
                "content": content,
                "source": {
                    "platform": e.get("platform", ""),
                    "platformName": platform_name,
                    "creator": creator,
                    "url": url,
                    "media_path": "",
                    "date": e.get("date", ""),
                    "heat": e.get("heat", ""),
                    "media_type": e.get("type", ""),
                    "is_collected": bool(e.get("isCollected", False)),
                    "is_liked": bool(e.get("isLiked", False)),
                },
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
            self.items.append(item)
            if url:
                existing_urls.add(url)
            added += 1
        if added:
            self.save()
        return added, skipped, f"导入完成：新增 {added} 条，跳过 {skipped} 条（已存在）。"

    # ──────────── 评分操作 ────────────

    @staticmethod
    def initial_score(sample_count: int) -> float:
        """根据样本量计算风格化初始评分 (5.0–7.0)，样本越多越可信。"""
        return round(min(5.0 + (sample_count or 0) / 10.0, 7.0), 1)

    def like_item(self, item_id: str) -> bool:
        item = self.get(item_id)
        if not item:
            return False
        item["like_count"] = item.get("like_count", 0) + 1
        item["score"] = min(round(item.get("score", 5.0) + 0.5, 1), 10.0)
        item["updated_at"] = int(time.time())
        self.save()
        return True

    def dislike_item(self, item_id: str) -> bool:
        item = self.get(item_id)
        if not item:
            return False
        item["dislike_count"] = item.get("dislike_count", 0) + 1
        item["score"] = max(round(item.get("score", 5.0) - 0.3, 1), 0.0)
        item["updated_at"] = int(time.time())
        self.save()
        return True

    def recommend_stylizations(self, dim: str = None, dim_value: str = None) -> list:
        """按评分降序返回所有风格化；若指定维度/取值则匹配的排最前。"""
        items = [it for it in self.items if it.get("type") == STYLIZATION_TYPE]
        def _sort_key(it):
            match = (it.get("dim") == dim and it.get("dim_value") == dim_value) if dim else False
            return (0 if match else 1, -(it.get("score") or 5.0))
        items.sort(key=_sort_key)
        return items

    # ──────────── Prompt 格式化 ────────────

    def to_prompt_text(self, item_ids):
        """把选中的若干条目拼成可注入 prompt 的文本。
        风格化条目用「风格指引」格式（HOW to write），其余条目用「知识背景」格式。
        一般用途方法，区分风格化与知识背景。调文案请用 to_style_guidance_text()。"""
        ids = set(item_ids or [])
        style_chunks = []
        knowledge_chunks = []
        for it in self.items:
            if it.get("id") not in ids:
                continue
            t = it.get("type", "").strip()
            name = it.get("name", "").strip()
            content = it.get("content", "")
            if t == STYLIZATION_TYPE:
                dim_label = STYLE_DIMS.get(it.get("dim", ""), "风格")
                dim_val = it.get("dim_value", "")
                head = f"【风格指引·{dim_label}：{dim_val}】"
                style_chunks.append(f"{head}\n{content}")
            else:
                head = f"【{t}】{name}" if t else name
                knowledge_chunks.append(f"{head}：\n{content}".strip())
        return "\n\n".join(style_chunks + knowledge_chunks)

    def to_style_guidance_text(self, item_ids):
        """把选中条目全部格式化为「风格指引」，专用于调文案场景。
        无论原始类型（风格化/品牌调性/话术风格/禁用词），
        都统一呈现为写法风格指引（HOW to write），让 LLM 聚焦改写方式而非内容。"""
        ids = set(item_ids or [])
        chunks = []
        for it in self.items:
            if it.get("id") not in ids:
                continue
            t = it.get("type", "").strip()
            name = it.get("name", "").strip()
            content = it.get("content", "")
            if t == STYLIZATION_TYPE:
                dim_label = STYLE_DIMS.get(it.get("dim", ""), "风格")
                dim_val = it.get("dim_value", "")
                head = f"【风格指引·{dim_label}：{dim_val}】"
            else:
                # 品牌调性/话术风格/禁用词等，也统一转为风格指引格式
                label = t if t else "风格"
                head = f"【风格指引·{label}：{name}】"
            chunks.append(f"{head}\n{content}")
        return "\n\n".join(chunks)
