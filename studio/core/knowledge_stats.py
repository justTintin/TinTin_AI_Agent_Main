"""core/knowledge_stats.py — 知识库统计与阈值判断。

从 my_knowledge_page.py 下沉的纯逻辑函数。
"""
import json
import os
import time
from typing import Any


def compute_knowledge_stats(
    items: list[dict[str, Any]],
    stylization_type: str,
    reference_type: str,
) -> dict[str, Any]:
    """计算知识库统计数据。

    Args:
        items: 知识库条目列表
        stylization_type: 风格化条目类型标识
        reference_type: 参考素材条目类型标识

    Returns:
        统计字典包含:
        - stylizations: 风格化条目数
        - samples: 参考素材条目数
        - downloaded_kb: 已下载媒体的参考素材数
        - last_ts: 最近更新时间戳
        - days_ago: 距上次提炼的天数
    """
    stylizations = [it for it in items if it.get("type") == stylization_type]
    samples = [it for it in items if it.get("type") == reference_type]

    if stylizations:
        last_ts = max(it.get("updated_at", 0) for it in stylizations)
        days_ago = int((time.time() - last_ts) / 86400)
    else:
        last_ts = 0
        days_ago = 9999

    downloaded_kb = sum(
        1 for it in samples
        if os.path.exists((it.get("source") or {}).get("media_path", "") or "")
    )

    return {
        "stylizations": len(stylizations),
        "samples": len(samples),
        "downloaded_kb": downloaded_kb,
        "last_ts": last_ts,
        "days_ago": days_ago,
    }


def determine_warning_level(
    stylizations_count: int,
    unimported: int,
    days_ago: int,
) -> tuple[str, str]:
    """根据统计数据确定警告级别与颜色。

    规则:
    - 红色(danger): 无风格化 / 未导入 > 30 / 超过 14 天未提炼
    - 橙色(warning): 有未导入 / 超过 7 天未提炼
    - 绿色(normal): 数据同步且新鲜

    Args:
        stylizations_count: 风格化条目数
        unimported: 未导入数量
        days_ago: 距上次提炼天数

    Returns:
        (color_hex, level_name)
    """
    if not stylizations_count or unimported > 30 or days_ago > 14:
        return "#F44336", "danger"
    elif unimported > 0 or days_ago > 7:
        return "#FF9800", "warning"
    else:
        return "#4CAF50", "normal"


def read_browser_counts(
    materials_dir: str,
    media_dir: str,
) -> tuple[int, int]:
    """读取浏览器收藏记录与已下载素材数量。

    优先从 materials_dir 读取，回退到 media_dir。

    Args:
        materials_dir: 素材目录
        media_dir: 媒体目录

    Returns:
        (browser_items_count, browser_sync_count)
    """
    browser_items = 0
    browser_sync = 0

    items_path = os.path.join(materials_dir, "kb_items.json")
    if not os.path.exists(items_path):
        items_path = os.path.join(media_dir, "kb_items.json")

    sync_path = os.path.join(materials_dir, "kb_sync.json")
    if not os.path.exists(sync_path):
        sync_path = os.path.join(media_dir, "kb_sync.json")

    if os.path.exists(items_path):
        try:
            with open(items_path, encoding="utf-8-sig") as f:
                data = json.load(f)
                if isinstance(data, list):
                    browser_items = len(data)
        except (OSError, json.JSONDecodeError):
            pass

    if os.path.exists(sync_path):
        try:
            with open(sync_path, encoding="utf-8-sig") as f:
                data = json.load(f)
                if isinstance(data, list):
                    browser_sync = len(data)
        except (OSError, json.JSONDecodeError):
            pass

    return browser_items, browser_sync
