# -*- coding: utf-8 -*-
"""工作台「一句话需求」路由：LLM 意图识别 + 关键词兜底。

一句话 → (页面 index, tab index|None, 是否多智能体任务)。
LLM 不可用/超时/解析失败时回退本地关键词匹配，保证路由始终可用。
"""
import re

# 意图名 -> (页面 index, tab index | None)
INTENT_MAP = {
    "一键成片": (33, None),
    "智能混剪": (14, None),
    "声音克隆": (20, None),
    "直播切片": (18, None),
    "封面制作": (32, None),
    "营销检测": (40, None),
    "视频评价": (34, None),
    "成片任务": (42, None),
    "素材生成": (31, 0),
    "产品生图": (31, 1),
    "数字人": (31, 2),
    "MG动画": (31, 3),
    "素材检索": (38, None),
    "音频素材": (44, None),
    "媒体工具": (45, None),
    "任务队列": (9, None),
    "视频去字幕": (17, None),
    "语音转写": (12, None),
}

# 关键词 -> (页面 index, tab index | None)；顺序匹配，靠前优先
KEYWORD_RULES = [
    (("数字人", "人像", "口播"), (31, 2)),
    (("即梦", "文生图", "图生图", "生成图片", "生图", "素材生成"), (31, 0)),
    (("产品图", "产品生图"), (31, 1)),
    (("mg动画", "MG动画", "动画"), (31, 3)),
    (("直播", "切片"), (18, None)),
    (("声音", "克隆", "配音", "音色"), (20, None)),
    (("封面",), (32, None)),
    (("营销",), (40, None)),
    (("评价", "预测", "数据表现"), (34, None)),
    (("混剪", "拼接", "镜头"), (14, None)),
    (("任务", "进度", "队列"), (42, None)),
    (("素材", "检索", "搜索素材"), (38, None)),
    (("音频素材",), (44, None)),
    (("媒体工具",), (45, None)),
    (("去字幕",), (17, None)),
    (("转写", "字幕"), (12, None)),
    (("成片", "带货", "文案成片"), (33, None)),
]

_SYSTEM_PROMPT = (
    "你是客户端智能体路由。用户输入一句话需求，判断应交给哪个功能页，"
    "只输出严格 JSON：{\"intent\": \"功能名\", \"multi_agent\": bool}。\n"
    "功能名只能是：" + "、".join(sorted(INTENT_MAP.keys())) + "。\n"
    "若需求需要组合多个能力（如“数字人口播带货视频”需数字人+配音+成片+封面），"
    "multi_agent 置 true，intent 填其中最相关的一个功能名。"
)


def route_text(text, use_llm=True):
    """一句话需求 -> dict(page, tab, intent, multi_agent)。

    page: 目标页面 index；tab: 目标 tab 序号或 None；multi_agent: 是否需要组合多能力。
    """
    text = (text or "").strip()
    if not text:
        return {"page": 33, "tab": None, "intent": "一键成片", "multi_agent": False}
    if use_llm:
        result = _llm_route(text)
        if result is not None:
            return result
    return _keyword_route(text)


def _llm_route(text):
    try:
        from utils.llm_proxy import llm_chat_json
        data = llm_chat_json(_SYSTEM_PROMPT, text, temperature=0.0, timeout=15)
        if not isinstance(data, dict):
            return None
        intent = str(data.get("intent") or "").strip()
        multi = bool(data.get("multi_agent", False))
        if intent in INTENT_MAP:
            page, tab = INTENT_MAP[intent]
            return {"page": page, "tab": tab, "intent": intent, "multi_agent": multi}
    except Exception:
        pass
    return None


def _keyword_route(text):
    low = text.lower()
    for keys, target in KEYWORD_RULES:
        for k in keys:
            if k.lower() in low:
                page, tab = target
                return {"page": page, "tab": tab, "intent": keys[0], "multi_agent": False}
    return {"page": 33, "tab": None, "intent": "一键成片", "multi_agent": False}