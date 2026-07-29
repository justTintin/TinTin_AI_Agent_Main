# -*- coding: utf-8 -*-
"""
统一 HTTP 客户端封装 — 自动重试 + 指数退避 + 按服务名隔离的熔断器。

用法:
    from utils.http_client import resilient_get, resilient_post
    resp = resilient_post(url, json=payload, timeout=600, service="voxcpm")

熔断器按 service 名隔离（whisper/voxcpm/ollama/comfyui）：
  CLOSED → 连续失败 5 次 → OPEN（直接拒绝请求）
  OPEN → 30 秒后 → HALF_OPEN（放一个探测请求）
  HALF_OPEN → 探测成功 → CLOSED / 探测失败 → OPEN

重试：
  最多 3 次，间隔 1s→2s→4s（指数退避）
  只对超时/连接错误重试，HTTP 4xx/5xx 不重试
"""
import time
import requests
from utils.logger_utils import log
from utils.api_error import ApiError

# ── 熔断器 ─────────────────────────────────────────────────

_FAILURE_THRESHOLD = 5      # 连续失败多少次后熔断
_RECOVERY_SECONDS = 30      # 熔断后多少秒进入半开状态

_breakers: dict[str, dict] = {}  # service -> {state, failures, opened_at}


def _get_breaker(service: str) -> dict:
    if service not in _breakers:
        _breakers[service] = {"state": "CLOSED", "failures": 0, "opened_at": 0}
    return _breakers[service]


def _allow_request(service: str) -> bool:
    """检查是否允许发请求。返回 False 表示被熔断。"""
    b = _get_breaker(service)
    if b["state"] == "OPEN":
        if time.time() - b["opened_at"] >= _RECOVERY_SECONDS:
            b["state"] = "HALF_OPEN"
            log.info(f"[熔断器:{service}] OPEN → HALF_OPEN（探测中）")
            return True
        return False
    return True


def _on_success(service: str):
    b = _get_breaker(service)
    if b["state"] != "CLOSED":
        log.info(f"[熔断器:{service}] {b['state']} → CLOSED（恢复）")
    b["state"] = "CLOSED"
    b["failures"] = 0


def _on_failure(service: str):
    b = _get_breaker(service)
    b["failures"] += 1
    if b["failures"] >= _FAILURE_THRESHOLD:
        b["state"] = "OPEN"
        b["opened_at"] = time.time()
        log.warning(f"[熔断器:{service}] CLOSED → OPEN（连续失败 {b['failures']} 次，熔断 30s）")


# ── 重试 + 熔断 封装 ────────────────────────────────────────

_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

_MAX_RETRIES = 3
_BASE_DELAY = 1  # 秒


def resilient_get(url, *, service="default", timeout=10, **kwargs):
    """带重试+熔断的 GET。探活场景传 circuit_breaker=False 跳过熔断。"""
    return _do_request("GET", url, service=service, timeout=timeout, **kwargs)


def resilient_post(url, *, service="default", timeout=30, **kwargs):
    """带重试+熔断的 POST。"""
    return _do_request("POST", url, service=service, timeout=timeout, **kwargs)


def _extract_params(kwargs):
    """从 requests 的 kwargs 里提取有意义的请求参数（供 ApiError 脱敏展示）。

    合并 json/data/files(仅文件名)/headers，让错误信息能看到「带了什么参数」。
    mask_params 会对敏感字段（api_key/Authorization 等）自动脱敏。
    """
    params = {}
    if "json" in kwargs and kwargs["json"]:
        try:
            params.update(kwargs["json"])
        except Exception:
            params["json"] = str(kwargs["json"])[:100]
    if "data" in kwargs and kwargs["data"]:
        d = kwargs["data"]
        if isinstance(d, dict):
            params.update(d)
        else:
            params["data"] = str(d)[:100]
    if "files" in kwargs and kwargs["files"]:
        # files 是 {field: (filename, fileobj, ...)}，只显示文件名
        try:
            files_info = {}
            for field, val in kwargs["files"].items():
                if isinstance(val, (tuple, list)) and val:
                    files_info[field] = val[0]  # filename
                else:
                    files_info[field] = str(val)[:50]
            params["_files"] = files_info
        except Exception:
            params["_files"] = "(文件)"
    if "headers" in kwargs and kwargs["headers"]:
        params["_headers"] = dict(kwargs["headers"])
    return params


def _do_request(method, url, *, service="default", timeout=10,
                circuit_breaker=True, **kwargs):
    params_for_error = _extract_params(kwargs)
    last_err = None
    for attempt in range(_MAX_RETRIES):
        # 熔断检查
        if circuit_breaker and not _allow_request(service):
            raise ApiError(
                url, method=method, params=params_for_error,
                note=f"服务 {service} 已熔断（连续失败 {_FAILURE_THRESHOLD} 次），请稍后重试",
            )

        try:
            if method == "GET":
                resp = requests.get(url, timeout=timeout, **kwargs)
            else:
                resp = requests.post(url, timeout=timeout, **kwargs)

            # HTTP 4xx/5xx 不重试，直接返回（调用方自己处理）
            if circuit_breaker:
                if resp.status_code < 500:
                    _on_success(service)
                # 5xx 视为服务端错误，记录失败但不重试
                elif resp.status_code >= 500:
                    _on_failure(service)

            return resp

        except _RETRYABLE as e:
            last_err = e
            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2 ** attempt)  # 1s → 2s → 4s
                log.warning(f"[HTTP:{service}] {method} {url} 第 {attempt+1} 次失败: {e}，{delay}s 后重试")
                time.sleep(delay)
            else:
                log.error(f"[HTTP:{service}] {method} {url} 重试 {_MAX_RETRIES} 次后仍失败: {e}")
        except Exception as e:
            # 非网络错误，不重试，直接抛出
            raise

    # 重试用完
    if circuit_breaker:
        _on_failure(service)
    raise ApiError(
        url, method=method, params=params_for_error,
        cause=last_err, note=f"已重试 {_MAX_RETRIES} 次后仍失败",
    )
