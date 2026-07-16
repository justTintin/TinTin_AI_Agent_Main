# -*- coding: utf-8 -*-
"""Ollama 远程客户端（纯远程模式，不再管理本地进程）。

所有推理请求走 llm_vision_api_url 配置的远程 Ollama 服务。
本模块仅保留远程只读 API：连通性检测、模型列表、配置读取。
"""
import os
import requests
from utils.logger_utils import log
from utils.http_client import resilient_get


def _read_ai_config() -> dict:
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _read_ollama_api() -> str:
    """返回远程 Ollama API 基地址。优先读 llm_vision_api_url，否则从 compute_server_url 派生。"""
    cfg = _read_ai_config()
    url = (cfg.get("llm_vision_api_url") or "").strip()
    if not url:
        base = (cfg.get("compute_server_url") or "").strip()
        if base:
            url = base
    if not url:
        return "http://127.0.0.1:11434"
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    return url.rstrip("/")


class OllamaManager:
    """远程 Ollama 只读客户端（保留单例接口兼容现有调用）。"""
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        pass

    def is_running(self) -> bool:
        """检测远程 Ollama 服务是否可达。"""
        url = f"{_read_ollama_api()}/ollama/status"
        try:
            r = resilient_get(url, timeout=5, service="ollama", circuit_breaker=False)
            ok = r.status_code == 200
            log.info(f"[Ollama] GET {url} -> HTTP {r.status_code}")
            return ok
        except Exception as e:
            log.warning(f"[Ollama] GET {url} 失败: {e}")
            return False

    def list_local_models(self) -> list[str]:
        """列出远程 Ollama 已加载的模型。"""
        url = f"{_read_ollama_api()}/ollama/models"
        try:
            r = requests.get(f"{_read_ollama_api()}/ollama/models", timeout=5)
            log.info(f"[Ollama] GET {url} -> HTTP {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                models = data.get("models") or data.get("data") or []
                return [m.get("name", m.get("model", str(m))) for m in models]
        except Exception:
            pass
        return []

    def get_configured_model(self) -> str:
        """从 ai_config.json 读取当前配置的视觉模型名；读不到返回空串。"""
        return str(_read_ai_config().get("llm_vision_model", "") or "").strip()
