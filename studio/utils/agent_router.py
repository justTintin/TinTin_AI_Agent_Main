# -*- coding: utf-8 -*-
"""工作台「一句话需求」路由：LLM 意图识别 + 关键词兜底。

一句话 → (页面 index, tab index|None, 是否多智能体任务)。
LLM 不可用/超时/解析失败时回退本地关键词匹配，保证路由始终可用。
"""
import json
import re

from utils.logger_utils import log

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
    "素材检索": (38, 0),
    "即梦素材": (38, 1),
    "音频素材": (44, None),
    "媒体工具": (45, None),
    "任务队列": (42, None),
    "视频去字幕": (17, None),
    "语音转写": (12, None),
    "仿爆款": (46, None),
    "爆款仿制": (46, None),
}

# 关键词 -> (页面 index, tab index | None)；顺序匹配，靠前优先
KEYWORD_RULES = [
    (("即梦素材",), (38, 1)),
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
    (("仿爆款", "爆款仿制", "仿这条", "模仿爆款", "爆款拆解"), (46, None)),
]

# 参数结构特殊的能力示例模板（params_schema 未声明时的兜底提示；
# 字段以实测/服务端契约为准，仅约束 LLM 拆解输出格式）
_PARAM_TEMPLATES = {
    "llm_chat": {"prompt": "要生成/处理的文本内容或问题"},
    "review_check": {"content": "待审查的文案或产物文本"},
    "agent_script_eval": {
        "shots": [{"index": 1, "shot_type": "镜头类型", "visual": "画面描述",
                     "audio": "配音文案", "sfx": "音效", "duration": 3.0}],
        "topic": "分镜主题",
    },
    "material_search": {"query": "检索关键词"},
    "asr_transcribe": {"file_path": "音频文件路径"},
    "tts_voice_clone": {"text": "待合成文本", "voice_sample": "音色样本路径"},
    "task_status_unified": {"task_id": "任务id"},
}


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


def build_plan(text, registry=None, timeout=20):
    """LLM 拆解一句话需求 → 服务端可执行 plan（POST /agent/tasks mode=execute 契约）。

    plan 格式：{goal, steps:[{id, capability, params, depends_on, needs_user_input}]}
    capability 必须是注册表已登记能力（executor=server）；拆解/校验失败返回 None。
    """
    text = (text or "").strip()
    if not text:
        return None
    if registry is None:
        from utils import agent_client as ac
        registry = ac.get_registry(timeout=8)
    caps = (registry or {}).get("capabilities") or []
    server_caps = [c for c in caps if c.get("executor") == "server"]
    if not server_caps:
        log.warning("[智能体编排] 注册表为空，无法拆解 plan")
        return None
    cap_lines = [
        f"- {c.get('id')}: {c.get('name')}｜{str(c.get('description') or '')[:60]}"
        for c in server_caps[:40]
    ]
    tpl_lines = []
    for c in server_caps:
        tpl = _PARAM_TEMPLATES.get(c.get("id"))
        if tpl:
            tpl_lines.append(f"- {c.get('id')}: {json.dumps(tpl, ensure_ascii=False)}")
    prompt = (
        "你是多智能体编排器。把用户的一句话目标拆解为可执行 plan（严格 JSON，无其他文字）。\n"
        "可用能力（capability id）：\n" + "\n".join(cap_lines) + "\n"
        "参数模板（无模板的能力按常见字段 prompt/content/text 给合理值）：\n"
        + "\n".join(tpl_lines) + "\n"
        "plan 格式：{\"goal\": \"目标\", \"steps\": [{\"id\": \"s1\", \"capability\": \"能力id\", "
        "\"params\": {能力输入字段}, \"depends_on\": [], \"needs_user_input\": false}]}\n"
        "规则：\n"
        "1. 只使用上面列出的能力 id，能力不够就拆到最接近的一步，params 严格按参数模板给；\n"
        "2. 有依赖的步骤用 depends_on 引用前置步骤 id；\n"
        "3. 需要用户提供素材/确认的步骤 needs_user_input 置 true；\n"
        "4. 步骤 2-8 个，输出必须是合法 JSON。"
    )
    try:
        from utils.llm_proxy import llm_chat_json
        data = llm_chat_json(prompt, text, temperature=0.0, timeout=timeout)
        if not isinstance(data, dict) or not data.get("steps"):
            return None
        ids = {c.get("id") for c in server_caps}
        for s in data["steps"]:
            if not isinstance(s, dict) or s.get("capability") not in ids:
                log.warning(f"[智能体编排] plan 含未登记能力，拒绝: {s}")
                return None
        return data
    except Exception as e:
        log.warning(f"[智能体编排] plan 拆解失败: {e}")
        return None
