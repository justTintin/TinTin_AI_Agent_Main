"""JSON 通用工具：深拷贝、UI 编辑器输入输出双向转换。

GUI 层不直接使用 json.loads(json.dumps(x)) 或手写 try/loads 容错，
统一走本模块封装函数。
"""
from __future__ import annotations

import copy
import json


def deep_copy(obj):
    """对象深拷贝（替代 json.loads(json.dumps(x)) 模式）。

    比 JSON 序列化方式更快，且支持非 JSON 类型的 Python 对象。
    对于纯 JSON 工作流数据与 json.loads(dumps(x)) 行为等价。
    """
    return copy.deepcopy(obj)


def to_editor_text(obj, indent: int = 2) -> str:
    """Python 对象 → JSON 显示文本（QPlainTextEdit 可编辑友好）。"""
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def from_editor_text(text, default=None):
    """JSON 文本 → Python 对象。

    失败不抛异常，返回 default。自动忽略前后空白字符。
    """
    if text is None:
        return default
    s = text.strip()
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


def compact_text(obj):
    """对象 → 紧凑 JSON 文本（无缩进、无换行，单行输出）。

    与 to_editor_text（indent=2 美化多行）区分：本函数用于需要单行紧凑展示的场景。
    中文不转义（ensure_ascii=False）。
    """
    return json.dumps(obj, ensure_ascii=False)


def parse_json_default(value):
    """模板参数默认值 → 展示文本（替代 GUI 层重复的 _parse_json_default）。

    - None → ""
    - dict/list → to_editor_text(value)（美化多行展示）
    - str → 原样返回（无论是否合法 JSON）
    - 其他类型 → str(value)
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return to_editor_text(value)
    if isinstance(value, str):
        return value
    return str(value)
