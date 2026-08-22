"""统一的接口错误格式化：所有调服务端接口失败的错误，必须显示
「接口 URL + 请求参数 + 状态码 + 服务端响应」，不猜测原因。

核心组件：
  · mask_value / mask_params：把请求参数里的敏感字段（api_key/token/base64音频等）
    脱敏，避免泄露密钥或把超大 base64 灌进错误信息。
  · ApiError：结构化异常，携带 url/method/params/status_code/response_text/cause，
    __str__ 输出标准格式，供 GUI 弹窗直接显示。

设计目标：用户看到错误信息后，能立刻知道「调的是哪个接口、带了什么参数、
服务端返回了什么」，而不是看到笼统的"请检查服务端连接/可能显存不足"这类猜测。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# 敏感字段名（小写匹配）——这些字段的值在错误信息里一律显示为 ***
_SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "api-key",
    "token", "access_token", "refresh_token", "bearer",
    "secret", "app_secret", "appsecret", "appkey", "sid",
    "password", "passwd", "cookie", "cookies",
    "access_key", "secret_key", "x-machine-id",
}

# base64 媒体字段——显示为 [base64 N字]，不展开
_BASE64_FIELDS = {"prompt_audio", "audio", "image", "image_b64", "image_base64"}

# 单个值在错误信息里的最大字符数（超长截断）
_MAX_VALUE_LEN = 200


def _looks_like_base64(value: str) -> bool:
    """粗略判断字符串是否是 base64 媒体（超长 + 含 base64 特有字符 +/= 或 data: 前缀）。

    避免把普通长文本（如一篇长文案）误判为 base64：要求超长且含 +/= 这类
    base64 编码才特有的字符，或以 data:image/data:audio 开头。
    """
    if not isinstance(value, str):
        return False
    # data: URI（图片/音频内嵌）
    if value.startswith("data:image") or value.startswith("data:audio"):
        return True
    if len(value) < 500:  # 提高门槛，普通文案很难到 500 字
        return False
    # 含 base64 特有的 + / = 字符（普通中文/英文文案极少连续出现这些）
    return ("+" in value[:500] or "/" in value[:500] or value.rstrip().endswith("="))


def mask_value(key: str, value: Any) -> str:
    """把单个参数值转成脱敏后的可显示字符串。"""
    key_lower = (key or "").lower()

    # 1) 敏感字段 → ***
    if key_lower in _SENSITIVE_KEYS:
        return "***"

    # 2) 已知 base64 媒体字段 / 看起来像 base64 的长字符串
    if key_lower in _BASE64_FIELDS:
        n = len(value) if isinstance(value, (str, bytes)) else 0
        return f"[base64 {n}字]"
    if isinstance(value, str) and _looks_like_base64(value):
        return f"[base64 {len(value)}字]"

    # 3) bytes → 看长度
    if isinstance(value, (bytes, bytearray)):
        return f"[bytes {len(value)}]"

    # 4) dict / list → 递归脱敏（用于 messages 这种嵌套结构）
    if isinstance(value, Mapping):
        inner = ", ".join(f"{k}={mask_value(k, v)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, (list, tuple)):
        # messages 列表：显示前 2 项 + 总数
        if len(value) > 2:
            sample = ", ".join(mask_value(key, v) for v in value[:2])
            return f"[{sample}, ... 共{len(value)}项]"
        return "[" + ", ".join(mask_value(key, v) for v in value) + "]"

    # 5) 普通字符串：长文本截断
    s = str(value)
    if len(s) > _MAX_VALUE_LEN:
        return f"{s[:_MAX_VALUE_LEN]}...({len(s)}字)"
    return s


def mask_params(params: Mapping[str, Any] | None) -> str:
    """把参数 dict 序列化成单行脱敏字符串，用于错误信息展示。

    例: {"text": "你好", "prompt_audio": "base64...", "speaker": "default"}
        → "text=你好, prompt_audio=[base64 124300字], speaker=default"
    """
    if not params:
        return "(无)"
    items = []
    for k, v in params.items():
        items.append(f"{k}={mask_value(k, v)}")
    return ", ".join(items)


def _truncate(text: str | None, limit: int = 500) -> str:
    """截断响应文本，保留有用信息又不过长。"""
    if not text:
        return "(无)"
    s = str(text).strip()
    if len(s) > limit:
        return s[:limit] + f"...(共{len(s)}字)"
    return s


# ── 按服务类型的响应解析器（归一化）─────────────────────────────────────
# 不同接口的服务端错误响应结构不同，这里各自解析提取可读错误消息。

def _try_json(text: str):
    """尝试把响应文本解析成 JSON；失败返回 None。"""
    if not text:
        return None
    import json
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _extract_llm_error(d) -> str:
    """LLM 错误结构多样：{"error":{"message":...}} / {"error":"..."} / {"detail":...}。"""
    if not isinstance(d, dict):
        return ""
    err = d.get("error")
    if isinstance(err, dict):
        # OpenAI 风格: {"error":{"message":"...", "type":"...", "code":"..."}}
        parts = [str(err.get(k, "")) for k in ("message", "type", "code") if err.get(k)]
        return " | ".join(parts) if parts else str(err)[:200]
    if isinstance(err, str) and err:
        return err
    return d.get("detail") or d.get("message") or ""


def _extract_comfyui_error(d) -> str:
    """ComfyUI 错误：{"error":{"node_type":...,"exception_type":...,"node_id":...}}。"""
    if not isinstance(d, dict):
        return ""
    err = d.get("error")
    if isinstance(err, dict):
        parts = [str(err.get(k, "")) for k in
                 ("exception_type", "node_type", "node_id", "message") if err.get(k)]
        return " | ".join(parts) if parts else str(err)[:200]
    if isinstance(err, str) and err:
        return err
    node_errors = d.get("node_errors")
    if node_errors:
        return f"节点错误: {_truncate(str(node_errors), 200)}"
    return d.get("detail") or d.get("message") or ""


def _extract_task_error(d) -> str:
    """task_id 轮询模式（score_clip/beatmap/vsr）：{"status":"failed","error_msg":...}。"""
    if not isinstance(d, dict):
        return ""
    for k in ("error_msg", "error", "message", "detail"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# 各服务对应的解析器（key=service 名，与 http_client 的 service 参数一致）
_PARSERS = {
    "voxcpm":  lambda d: (d.get("detail") or d.get("error") or d.get("message") or "") if isinstance(d, dict) else "",  # noqa: E501
    "whisper": lambda d: (d.get("error") or d.get("detail") or d.get("message") or "") if isinstance(d, dict) else "",  # noqa: E501
    "llm":     _extract_llm_error,
    "comfyui": _extract_comfyui_error,
    "ocr":     lambda d: (d.get("detail") or d.get("error") or d.get("message") or "") if isinstance(d, dict) else "",  # noqa: E501
    "score_clip": _extract_task_error,
    "beatmap": _extract_task_error,
    "vsr":     _extract_task_error,
    "montage": _extract_task_error,
}


def normalize_response(service: str | None, response_text: str | None) -> str:
    """按服务类型解析服务端响应，提取可读错误消息。

    不同接口返回结构不同（detail/error/message/嵌套/task轮询），这里归一化成纯文本。
    解析失败回退到原始响应文本（兜底），保证用户总能看到服务端返回了什么。
    """
    if not response_text:
        return ""
    text = str(response_text).strip()
    data = _try_json(text)

    # 优先用该服务的专属解析器
    parser = _PARSERS.get((service or "").lower()) if service else None
    if parser and data is not None:
        try:
            msg = parser(data)
            if msg and str(msg).strip():
                return str(msg).strip()
        except Exception:  # 外部回调（专属解析器）
            pass  # 解析失败走兜底

    # 通用 JSON 解析（没匹配到专属解析器，或专属解析器返回空）
    if data is not None and isinstance(data, dict):
        for k in ("detail", "error", "message", "error_msg"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                inner = v.get("message") or v.get("type")
                if inner:
                    return str(inner)

    # 兜底：原始文本
    return _truncate(text)


class ApiError(RuntimeError):
    """统一的接口调用异常：携带接口 URL、方法、脱敏参数、状态码、服务端响应。

    所有调服务端接口失败的地方应抛 ApiError（而非 RuntimeError），让用户看到
    「调的哪个接口 + 带了什么参数 + 服务端返回什么」，而不是笼统的猜测。

    用法:
        raise ApiError(url, method="POST", params=payload,
                       status_code=resp.status_code, response_text=resp.text)
        raise ApiError(url, method="POST", params=kwargs, cause=e)  # 网络层错误
    """

    def __init__(self, url: str, *, method: str = "POST",
                 params: Mapping[str, Any] | None = None,
                 status_code: int | None = None,
                 response_text: str | None = None,
                 cause: BaseException | None = None,
                 note: str | None = None,
                 service: str | None = None):
        self.url = url or "(未知接口)"
        self.method = (method or "POST").upper()
        self.params_str = mask_params(params)
        self.status_code = status_code
        self.response_text = response_text
        self.cause = cause
        self.note = note  # 可选的额外说明（如"重试3次后仍失败"），不含猜测
        self.service = service  # 接口服务类型，用于归一化解析服务端响应
        # 归一化后的可读错误消息（从 response_text 按服务类型解析提取）
        self.normalized_error = normalize_response(service, response_text) if response_text else ""  # noqa: E501
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        lines = ["调用接口失败", f"接口: {self.method} {self.url}"]
        lines.append(f"参数: {self.params_str}")
        if self.status_code is not None:
            lines.append(f"状态: HTTP {self.status_code}")
        if self.normalized_error:
            # 归一化后的可读错误（从 detail/error/message 等字段提取）
            lines.append(f"错误: {_truncate(self.normalized_error)}")
        elif self.response_text:
            # 归一化失败，回退到原始响应
            lines.append(f"响应: {_truncate(self.response_text)}")
        if self.cause is not None and not self.normalized_error and not self.response_text:  # noqa: E501
            # 网络层错误（连不上/超时/熔断），没有 HTTP 状态码和响应体
            cause_msg = type(self.cause).__name__
            cause_text = str(self.cause).strip()
            if cause_text:
                cause_msg = f"{cause_msg}: {cause_text}"
            lines.append(f"错误: {cause_msg}")
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.args[0] if self.args else "调用接口失败"
