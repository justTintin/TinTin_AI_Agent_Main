"""
品牌归一化工具 — 加载 brand_dictionary.json，提供 canonical_name() 函数。
AI 识别出的品牌经此归一化后，合并大小写/中英文/拼写变体。
"""
import json

from config.paths import BRAND_DICTIONARY_FILE

_dict_path = BRAND_DICTIONARY_FILE
_alias_to_canonical: dict[str, str] = {}
_loaded = False


def _load() -> None:
    global _loaded, _alias_to_canonical
    if _loaded:
        return
    try:
        with open(_dict_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _loaded = True
        return
    brands = data.get("brands", {})
    for key, entry in brands.items():
        canonical = entry.get("canonical", key)
        # Key itself maps to canonical
        _alias_to_canonical[key.lower()] = canonical
        # All aliases also map to canonical
        for alias in entry.get("aliases", []):
            _alias_to_canonical[alias.lower()] = canonical
    _loaded = True


def canonical_name(raw_brand: str | None) -> str | None:
    """Return the canonical brand name for a raw AI-recognized brand string."""
    if not raw_brand or not raw_brand.strip():
        return raw_brand
    _load()
    key = raw_brand.strip().lower()
    return _alias_to_canonical.get(key, raw_brand.strip())


def reload_dictionary() -> None:
    """Force re-load the brand dictionary (for hot-reload after edits)."""
    global _loaded, _alias_to_canonical
    _loaded = False
    _alias_to_canonical = {}
    _load()
