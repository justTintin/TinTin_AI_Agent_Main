# -*- coding: utf-8 -*-
"""
LLM 代理客户端 — 文本 LLM 调用统一走服务端代理。

客户端不再直接持有 API Key 调用 DeepSeek/OpenAI，
而是通过服务端 /llm/chat/completions 接口转发：
  客户端 → 服务端（携带 model 名称）→ DeepSeek/OpenAI → 服务端 → 客户端

服务端负责：
  - 持有真实 API Key（客户端不存储）
  - 根据 model 名称路由到对应供应商
  - 请求统计、用量追踪
  - 统一限流/重试

用法:
    from utils.llm_proxy import llm_chat
    reply = llm_chat(system="你是文案专家", user="写一段产品介绍", model="deepseek-v4-flash")
"""
import os
import json

from utils.logger_utils import log
from utils.http_client import resilient_post


def _read_config() -> dict:
    """读取 ai_config.json。"""
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _get_server_url() -> str:
    """获取服务端统一地址。"""
    cfg = _read_config()
    return (cfg.get("compute_server_url") or "").strip().rstrip("/")


def _get_default_model() -> str:
    """获取默认文本模型名。"""
    cfg = _read_config()
    return cfg.get("llm_model") or "deepseek-v4-flash"


def llm_chat(
    system: str,
    user: str,
    *,
    model: str = "",
    temperature: float = 0.4,
    timeout: int = 120,
    max_tokens: int = 0,
) -> str:
    """通过服务端代理调用文本 LLM。

    Args:
        system: 系统提示词
        user: 用户消息
        model: 模型名（留空用 ai_config 中的 llm_model）
        temperature: 温度
        timeout: 超时秒数
        max_tokens: 最大 token 数（0=不限制）

    Returns:
        LLM 回复文本

    Raises:
        RuntimeError: 服务端不可达或返回错误
    """
    base = _get_server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址。")

    if not model:
        model = _get_default_model()

    url = f"{base}/llm/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens

    log.info(f"[LLM代理] POST {url} model={model}")
    resp = resilient_post(url, json=payload, timeout=timeout, service="llm")
    if resp.status_code != 200:
        err = resp.text[:300] if resp.text else ""
        log.error(f"[LLM代理] HTTP {resp.status_code}: {err}")
        raise RuntimeError(f"LLM 服务端返回 HTTP {resp.status_code}: {err}")

    data = resp.json()
    # 兼容 OpenAI 格式和自定义格式
    content = (
        data.get("choices", [{}])[0].get("message", {}).get("content", "")
        or data.get("content", "")
        or data.get("result", "")
    )
    log.info(f"[LLM代理] 返回 {len(content)} 字符")
    return content


def llm_chat_messages(
    messages: list,
    *,
    model: str = "",
    temperature: float = 0.4,
    timeout: int = 120,
    max_tokens: int = 0,
) -> str:
    """通过服务端代理调用 LLM（支持多模态 messages 格式）。

    Args:
        messages: OpenAI 格式的消息列表，例如：
            [{"role": "system", "content": "..."},
             {"role": "user", "content": "..."}]
            支持多模态 content（text + image_url 列表）
        model: 模型名（留空用 ai_config 中的 llm_model）
        temperature: 温度
        timeout: 超时秒数
        max_tokens: 最大 token 数（0=不限制）

    Returns:
        LLM 回复文本

    Raises:
        RuntimeError: 服务端不可达或返回错误
    """
    base = _get_server_url()
    if not base:
        raise RuntimeError("未配置服务端地址，请在系统设置中填写统一计算节点地址。")

    if not model:
        model = _get_default_model()

    url = f"{base}/llm/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens

    log.info(f"[LLM代理] POST {url} model={model} 消息数={len(messages)}")
    resp = resilient_post(url, json=payload, timeout=timeout, service="llm")
    if resp.status_code != 200:
        err = resp.text[:300] if resp.text else ""
        log.error(f"[LLM代理] HTTP {resp.status_code}: {err}")
        raise RuntimeError(f"LLM 服务端返回 HTTP {resp.status_code}: {err}")

    data = resp.json()
    content = (
        data.get("choices", [{}])[0].get("message", {}).get("content", "")
        or data.get("content", "")
        or data.get("result", "")
    )
    log.info(f"[LLM代理] 返回 {len(content)} 字符")
    return content


def llm_chat_json(
    system: str,
    user: str,
    *,
    model: str = "",
    temperature: float = 0.2,
    timeout: int = 120,
) -> dict | list | None:
    """调用 LLM 并解析 JSON 结果。容忍 ```json 包裹和前后多余文字。"""
    import re
    text = llm_chat(system, user, model=model, temperature=temperature, timeout=timeout)
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return None
