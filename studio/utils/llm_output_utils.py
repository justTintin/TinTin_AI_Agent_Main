"""LLM 输出解析 + JSON 清洗工具。

大模型（LLM/ASR/VL）输出通常包含 Markdown 代码块、中文描述、甚至嵌入在长文本中的 JSON。
GUI 层不直接写 regex+json.loads 组合逻辑，统一走本模块。
"""
from __future__ import annotations

import json
import re

from utils.logger_utils import log

_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.IGNORECASE | re.DOTALL)


def _match_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    """在 text 中查找第一对平衡的 open_ch/close_ch（支持嵌套），返回子串（含括号）。"""
    n = len(text)
    i = text.find(open_ch)
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, n):
        c = text[j]
        if in_str:
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def extract_first_object(text: str):
    """提取 text 中首个平衡的 {...} 对象并解析，失败返回 None。"""
    if not text:
        return None
    s = _match_balanced(text, "{", "}")
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        log.debug(f"[llm_output_utils] extract_first_object 解析失败: {e}")
        return None


def extract_first_array(text: str):
    """提取 text 中首个平衡的 [...] 数组并解析，失败返回 None。"""
    if not text:
        return None
    s = _match_balanced(text, "[", "]")
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        log.debug(f"[llm_output_utils] extract_first_array 解析失败: {e}")
        return None


def _try_loads(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def extract_json_block(text: str):
    """从 LLM 输出中提取 JSON。优先级：

    1. 整段 text 直接 json.loads（纯 JSON 响应）
    2. 剥离 ```...``` Markdown 代码块（支持 ```json 或 裸 ```），剥离后 json.loads
    3. 代码块/全文 regex 抓第一对 {}
    4. 代码块/全文 regex 抓第一对 []

    全部失败返回 None。
    """
    if not text:
        return None
    stripped = text.strip()

    # 1. 直接是纯 JSON
    obj = _try_loads(stripped)
    if obj is not None:
        return obj

    # 2. Markdown 代码块
    m = _CODE_BLOCK_RE.search(text)
    if m:
        inside = m.group(1).strip()
        obj = _try_loads(inside)
        if obj is not None:
            return obj
        # 整个 code block 不是纯 JSON，尝试在内部抓 object/array：谁在前面用谁
        i_obj = inside.find("{")
        i_arr = inside.find("[")
        if i_obj >= 0 and (i_arr < 0 or i_obj <= i_arr):
            obj = extract_first_object(inside)
            if obj is not None:
                return obj
        if i_arr >= 0:
            obj = extract_first_array(inside)
            if obj is not None:
                return obj

    # 3. 在原 text 中直接找 {...} 或 [...]：谁在前面用谁（平衡括号匹配）
    obj_idx = text.find("{")
    arr_idx = text.find("[")
    if obj_idx >= 0 and (arr_idx < 0 or obj_idx <= arr_idx):
        obj = extract_first_object(text)
        if obj is not None:
            return obj
    if arr_idx >= 0:
        return extract_first_array(text)
    return None


def safe_json_parse(text: str):
    """直接 json.loads，失败回退到 extract_json_block，再失败返回 None。"""
    if not text:
        return None
    obj = _try_loads(text.strip())
    if obj is not None:
        return obj
    return extract_json_block(text)
