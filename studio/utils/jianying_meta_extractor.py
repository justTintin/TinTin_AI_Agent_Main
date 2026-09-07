"""剪映本地草稿「花字/文字效果/音效」元数据侦察提取器。

背景：剪映官方无素材 API；项目采用「手写剪映草稿 JSON」路线（jianying_exporter.py），
其转场资源 ID 即来自剪映内置元数据（pyJianYingDraft）。花字模板/音效走同一思路：
从本机剪映草稿（draft_content.json）中提取效果素材的 id/name，供花字模板包引用。

设计说明：
- 剪映各版本草稿里花字/音效的字段名不固定（花字可能出现在 texts/text_templates/
  text_effects 等键，音效在 audios 且 category_name 含「音效」），因此本提取器是
  **侦察式**的：全量扫描 materials 下各数组，按防御规则分类候选，并输出「键名×条目
  数」清单——即使字段名与预期不符，也能从真实数据反推结构，再迭代精化规则。
- 草稿可能被新版剪映加密（非 JSON）→ 解析失败直接跳过并计数，不报错。
- 纯 Python 无 Qt 依赖，可单测；扫描只读，不修改任何剪映数据。
"""
import glob
import json
import os

from utils.logger_utils import log

# materials 下与文本效果/花字相关的候选键（防御式枚举，命中几个算几个）
_TEXT_EFFECT_KEYS = ("text_effects", "text_templates", "texts")
# 动画键（花字出现时机相关的入场/出场/循环动画）
_ANIMATION_KEYS = ("material_animations",)
# 音频键（音效在 audios 里，靠 category_name 区分音效/BGM/配乐）
_AUDIO_KEYS = ("audios",)

_SFX_CATEGORY_MARKS = ("音效", "sfx", "sound effect")


class JianyingMetaExtractor:
    """从本机剪映草稿目录侦察花字/文字效果/音效元数据。"""

    def __init__(self, draft_root: str = ""):
        self.draft_root = draft_root or self.get_default_draft_root()

    @staticmethod
    def get_default_draft_root() -> str:
        """Windows 默认剪映专业版草稿根目录（与 JianyingExporter 保持一致）。"""
        appdata = os.environ.get("LOCALAPPDATA")
        if not appdata:
            appdata = os.path.expandvars(r"%USERPROFILE%\AppData\Local")
        return os.path.normpath(
            os.path.join(appdata, "JianyingPro", "User Data", "Projects", "com.lveditor.draft"))  # noqa: E501

    def list_drafts(self) -> list[dict]:
        """枚举草稿：[{name, folder, json_path}]；无目录/无草稿返回 []。"""
        root = self.draft_root
        if not root or not os.path.isdir(root):
            return []
        drafts = []
        for json_path in sorted(glob.glob(os.path.join(root, "*", "draft_content.json"))):  # noqa: E501
            folder = os.path.dirname(json_path)
            drafts.append({
                "name": os.path.basename(folder),
                "folder": folder,
                "json_path": json_path,
            })
        return drafts

    # ---------- 对外主入口 ----------
    def extract_fancy_usage(self, draft_dir: str) -> dict:
        """从草稿目录的 key_value.json 提取「素材使用记录」（新版剪映加密草稿的明文旁路）。

        新版剪映（6.0+）的 draft_content.json 加密，但同目录 key_value.json 保存了每个
        添加到草稿的线上素材的使用记录（明文 JSON）：materialId=素材ID（即花字
        effect_id）、materialName=素材名、materialThirdcategory=花字面板左侧分类、
        materialSubcategory=text_special_effect（花字）/text_template（文字模板）。
        提取流程：在剪映里把想要的花字逐个添加到任意草稿并保存 → 本方法即可提取。

        返回 {
          "draft_dir": str,
          "fancy": [...],          # 花字（text_special_effect），按 material_id 去重
          "text_templates": [...], # 文字模板（text_template）
          "other": [...],          # 其它 text 类素材
        }
        """
        path = os.path.join(draft_dir, "key_value.json")
        result = {"draft_dir": draft_dir, "fancy": [], "text_templates": [], "other": []}
        try:
            import json as _json
            with open(path, encoding="utf-8") as f:
                kv = _json.load(f)
        except (OSError, ValueError):
            log.warning(f"[花字提取] key_value.json 不可读/不存在：{path}")
            return result

        seen = set()
        for _seg_id, rec in kv.items():
            if not isinstance(rec, dict) or rec.get("materialCategory") != "text":
                continue
            material_id = str(rec.get("materialId") or "")
            if not material_id or material_id in seen:
                continue
            seen.add(material_id)
            entry = {
                "material_id": material_id,
                "name": str(rec.get("materialName") or ""),
                "subcategory": str(rec.get("materialSubcategory") or ""),
                "category": str(rec.get("materialThirdcategory") or ""),
                "category_id": str(rec.get("materialThirdcategoryId") or ""),
                "is_vip": str(rec.get("is_vip") or ""),
                "segment_id": str(rec.get("segmentId") or _seg_id or ""),
            }
            sub = entry["subcategory"]
            if sub == "text_special_effect":
                result["fancy"].append(entry)
            elif sub == "text_template":
                result["text_templates"].append(entry)
            else:
                result["other"].append(entry)

        log.info(
            f"[花字提取] {draft_dir}：花字 {len(result['fancy'])}、"
            f"文字模板 {len(result['text_templates'])}、其它 {len(result['other'])}")
        return result

    def extract_all(self) -> dict:
        """扫描全部草稿，汇总提取结果。

        返回 {
          "draft_root": str,
          "drafts_scanned": int, "drafts_parsed": int, "drafts_skipped": int,
          "key_stats": {key: count, ...},          # 各草稿 materials 键出现统计
          "text_effect_candidates": [...],          # 花字/文字效果候选
          "animation_candidates": [...],            # 文字动画候选（出现时机用）
          "sound_effect_candidates": [...],         # 音效候选
        }
        """
        result = {
            "draft_root": self.draft_root,
            "drafts_scanned": 0, "drafts_parsed": 0, "drafts_skipped": 0,
            "key_stats": {},
            "text_effect_candidates": [],
            "animation_candidates": [],
            "sound_effect_candidates": [],
        }
        for draft in self.list_drafts():
            result["drafts_scanned"] += 1
            data = self._load_draft_json(draft["json_path"])
            if data is None:
                result["drafts_skipped"] += 1
                continue
            result["drafts_parsed"] += 1
            self._extract_one(draft, data, result)
        log.info(
            f"[剪映侦察] 扫描 {result['drafts_scanned']} 份草稿：解析 {result['drafts_parsed']}、"
            f"跳过 {result['drafts_skipped']}（加密/损坏）；"
            f"花字候选 {len(result['text_effect_candidates'])}、"
            f"动画候选 {len(result['animation_candidates'])}、"
            f"音效候选 {len(result['sound_effect_candidates'])}")
        return result

    # ---------- 内部实现 ----------
    @staticmethod
    def _load_draft_json(json_path: str) -> dict | None:
        """读取并解析草稿 JSON；加密/损坏/过大异常返回 None。"""
        try:
            if os.path.getsize(json_path) > 64 * 1024 * 1024:
                return None
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None  # 新版剪映加密草稿不是合法 JSON，静默跳过

    def _extract_one(self, draft: dict, data: dict, result: dict) -> None:
        materials = data.get("materials")
        if not isinstance(materials, dict):
            return
        src = {"draft": draft["name"], "folder": draft["folder"]}

        for key, items in materials.items():
            if isinstance(items, list):
                result["key_stats"][key] = result["key_stats"].get(key, 0) + len(items)  # noqa: E501

        # 1) 花字/文字效果候选：专用键全收 + texts 里自带 effects 字段的条目
        for key in _TEXT_EFFECT_KEYS:
            for item in materials.get(key) or []:
                if not isinstance(item, dict):
                    continue
                cand = self._common_fields(item, key, **src)
                if key == "texts":
                    # 普通文本素材：仅当带效果字段（花字/气泡应用后出现）才收
                    if not (item.get("effects") or item.get("text_templates")
                            or item.get("type") not in (None, "text")):
                        continue
                    cand["content"] = str(item.get("content") or "")[:60]
                result["text_effect_candidates"].append(cand)

        # 2) 文字动画候选（入场/出场/循环 → 花字出现时机）
        for key in _ANIMATION_KEYS:
            for item in materials.get(key) or []:
                if isinstance(item, dict):
                    result["animation_candidates"].append(self._common_fields(item, key, **src))  # noqa: E501

        # 3) 音效候选：audios 里 category_name 含「音效」
        for key in _AUDIO_KEYS:
            for item in materials.get(key) or []:
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category_name") or "")
                if any(mark in category.lower() or mark in category for mark in _SFX_CATEGORY_MARKS):  # noqa: E501
                    cand = self._common_fields(item, key, **src)
                    cand["category_name"] = category
                    cand["duration_us"] = item.get("duration")
                    result["sound_effect_candidates"].append(cand)

    @staticmethod
    def _common_fields(item: dict, key: str, **src) -> dict:
        """抽取跨版本通用字段：id/name/effect_id/resource_id/type。"""
        cand = dict(src)
        cand["material_key"] = key
        for field in ("id", "name", "effect_id", "resource_id", "type", "category_name"):  # noqa: E501
            if item.get(field) is not None:
                cand[field] = item.get(field)
        return {k: v for k, v in cand.items() if v not in (None, "")}
