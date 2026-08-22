"""llama-server / Ollama 健康检查：一眼识别模型卡死。

典型卡死特征：
    - 进程 CPU 持续很高（接近单核 100%）
    - 但对 health / generate 请求无响应或超时
本模块只做轻量级采样 + HTTP 探测，不依赖 Qt。
"""
import time
from typing import Any

import psutil
import requests

LLAMA_PROCESS_NAMES = ("llama-server.exe", "llama-server", "ollama.exe", "ollama")


def find_llama_process():
    """查找本地 llama-server / Ollama 进程。"""
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in LLAMA_PROCESS_NAMES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def sample_cpu_percent(pid: int, duration: float = 3.0) -> float | None:
    """对指定 pid 采样 CPU 占用率（%）。"""
    try:
        proc = psutil.Process(pid)
        # 第一次调用返回 0.0，需要间隔采样
        proc.cpu_percent(interval=None)
        time.sleep(duration)
        return proc.cpu_percent(interval=None)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def probe_server(url: str, timeout: float = 5.0) -> dict:
    """探测服务端点，返回 {ok, status_code, elapsed_ms, error}。"""
    result: dict[str, Any] = {"ok": False, "status_code": None, "elapsed_ms": None, "error": None}  # noqa: E501
    try:
        start = time.time()
        r = requests.get(url, timeout=timeout)
        result["elapsed_ms"] = int((time.time() - start) * 1000)
        result["status_code"] = r.status_code
        result["ok"] = r.status_code == 200
    except requests.Timeout:
        result["error"] = "timeout"
    except requests.exceptions.RequestException as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def check_health(base_url: str = "http://192.168.111.28:11435",
                 cpu_threshold: float = 90.0,
                 sample_seconds: float = 3.0,
                 probe_timeout: float = 5.0) -> dict:
    """综合检查：进程 CPU + 接口响应。

    返回 dict：
        - healthy: bool
        - reason: 人类可读结论
        - process: {pid, name, cpu_percent} 或 None
        - probe: probe_server 结果
    """
    result = {
        "healthy": True,
        "reason": "",
        "process": None,
        "probe": None,
    }

    # 1) 找进程
    proc = find_llama_process()
    if proc is None:
        result["healthy"] = False
        result["reason"] = "未找到 llama-server / Ollama 进程"
        return result

    pid = proc.info["pid"]
    name = proc.info["name"]
    cpu = sample_cpu_percent(pid, duration=sample_seconds)
    result["process"] = {"pid": pid, "name": name, "cpu_percent": cpu}

    # 2) 探测接口
    probe_url = base_url.rstrip("/") + "/api/tags"  # Ollama 标准端点
    probe = probe_server(probe_url, timeout=probe_timeout)
    result["probe"] = probe

    if probe["ok"]:
        result["healthy"] = True
        result["reason"] = f"进程正常，接口响应 {probe['elapsed_ms']}ms"
        return result

    # 接口不通
    if cpu is not None and cpu >= cpu_threshold:
        result["healthy"] = False
        result["reason"] = (
            f"模型疑似卡死：CPU {cpu:.1f}%（持续 {sample_seconds}s），"
            f"接口 {probe_url} 无响应 ({probe['error']})"
        )
    else:
        result["healthy"] = False
        result["reason"] = (
            f"接口无响应 ({probe['error']})，但 CPU {cpu if cpu is not None else 'N/A'}% "
            f"未超过阈值 {cpu_threshold}%——可能是网络/服务端其他问题"
        )
    return result


if __name__ == "__main__":
    # 简单 CLI：python -m studio.utils.llama_health
    import json
    res = check_health()
    print(json.dumps(res, ensure_ascii=False, indent=2))
