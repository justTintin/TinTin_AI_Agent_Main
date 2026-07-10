# -*- coding: utf-8 -*-
"""Ollama 远程客户端（纯远程模式，不再管理本地进程）。

所有推理请求走 llm_vision_api_url 配置的远程 Ollama 服务。
本模块仅保留远程只读 API：连通性检测、模型列表、配置读取。
"""
import os
import requests
from utils.logger_utils import log


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
    """返回远程 Ollama API 基地址（从 llm_vision_api_url 读取）。"""
    url = (_read_ai_config().get("llm_vision_api_url") or "").strip()
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
        try:
            r = requests.get(f"{_read_ollama_api()}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_local_models(self) -> list[str]:
        """列出远程 Ollama 已加载的模型。"""
        try:
            r = requests.get(f"{_read_ollama_api()}/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def get_configured_model(self) -> str:
        """从 ai_config.json 读取当前配置的视觉模型名；读不到返回空串。"""
        return str(_read_ai_config().get("llm_vision_model", "") or "").strip()
