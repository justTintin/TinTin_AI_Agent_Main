"""热点片段分析算法：基于规则的直播视频热点检测。

从 live_clip_page.py 的 HotSpotAnalyzer._rule_analyze 方法下沉。
"""
import re
from collections import Counter
from typing import Any, cast

HOT_KEYWORDS_CN = [
    "重点", "关键", "核心", "重要", "注意", "记住", "一定要", "必须",
    "首先", "然后", "最后", "总结", "结论", "建议", "推荐",
    "技巧", "方法", "步骤", "教程", "演示", "实战", "案例",
    "干货", "福利", "优惠", "限时", "免费", "独家",
    "数据", "算法", "模型", "AI", "人工智能", "深度学习",
    "赚钱", "流量", "变现", "涨粉", "运营",
]


def rule_analyze(segments: list[Any]) -> list[dict[str, Any]]:
    """基于规则的热点片段分析。

    使用滑动窗口、关键词密度、唯一性、数字特征等指标对每个时间窗口打分，
    筛选高分窗口后合并相邻片段，生成热点片段列表。

    Args:
        segments: 字幕片段列表，每个元素需有 start, end, text 属性

    Returns:
        热点片段列表，每个元素包含:
        - start, end: 起止时间（秒）
        - start_str, end_str: 格式化时间字符串（mm:ss）
        - duration: 时长（秒）
        - score: 热度评分
        - title: 片段标题
        - preview: 预览文本
    """
    windows: list[dict[str, Any]] = []
    win, step = 60, 30
    total_dur = segments[-1].end if segments else 0
    for t0 in range(0, int(total_dur) + 1, step):
        t1 = t0 + win
        wsegs = [s for s in segments if s.start < t1 and s.end > t0]
        if not wsegs:
            continue
        text = " ".join(s.text.strip() for s in wsegs)
        words = list(re.findall(r"[\u4e00-\u9fff\w]+", text))
        if len(words) < 10:
            continue
        kw_hits = sum(1 for w in words if w in HOT_KEYWORDS_CN)
        density = len(words) / win
        unique = len(set(words)) / max(1, len(words))
        digits = sum(1 for c in text if c.isdigit())
        score = kw_hits * 3.0 + density * 10.0 + unique * 15.0 + min(digits, 20) * 0.3
        windows.append({"start": t0, "end": t1, "score": score, "text": text, "words": words})  # noqa: E501

    if not windows:
        return []

    scores = [w["score"] for w in windows]
    threshold = sum(scores) / len(scores) * 1.3
    peaks: list[dict[str, Any]] = [w for w in windows if w["score"] >= threshold]

    merged: list[dict[str, Any]] = []
    for p in sorted(peaks, key=lambda x: cast(float, x["start"])):
        p_start = cast(float, p["start"])
        p_end = cast(float, p["end"])
        p_score = cast(float, p["score"])
        if merged and p_start - cast(float, merged[-1]["end"]) < 20:
            merged[-1]["end"] = max(cast(float, merged[-1]["end"]), p_end)
            merged[-1]["score"] = max(cast(float, merged[-1]["score"]), p_score)
            merged[-1]["text"] = cast(str, merged[-1]["text"]) + " " + cast(str, p["text"])
            cast(list, merged[-1]["words"]).extend(cast(list, p["words"]))
        else:
            merged.append(p)

    results: list[dict[str, Any]] = []
    for m in merged:
        start = cast(float, m["start"])
        end = cast(float, m["end"])
        dur = end - start
        if dur < 15 or dur > 300:
            if dur > 300:
                m["end"] = start + 300
                dur = cast(float, m["end"]) - start
            else:
                continue
        word_freq = Counter(cast(list, m["words"]))
        hot = [w for w in word_freq if w in HOT_KEYWORDS_CN]
        reg = [(w, c) for w, c in word_freq.most_common(20) if len(w) >= 2 and w not in HOT_KEYWORDS_CN]  # noqa: E501
        top = hot[:3] + [w for w, _ in reg[:5]]
        title = " | ".join(top[:5]) if top else "精彩片段"
        score = cast(float, m["score"])
        text = cast(str, m["text"])
        results.append({
            "start": start,
            "end": end,
            "start_str": f"{int(start // 60):02d}:{int(start % 60):02d}",
            "end_str": f"{int(end // 60):02d}:{int(end % 60):02d}",
            "duration": int(dur),
            "score": round(score, 1),
            "title": title,
            "preview": text[:120].replace("\n", " "),
        })
    results.sort(key=lambda x: cast(float, x["score"]), reverse=True)
    return results
