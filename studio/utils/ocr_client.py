# -*- coding: utf-8 -*-
"""OCR 服务端客户端 — POST /material/ocr"""
import os
import requests
from utils.logger_utils import log


def _server_url():
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return "http://192.168.111.18:8000"


def ocr_image(file_path: str, server_url: str = "") -> str:
    """上传图片到服务端 OCR，返回识别文本。"""
    url = (server_url or _server_url()).rstrip("/")
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{url}/material/ocr",
                files={"file": (os.path.basename(file_path), f, "image/png")},
                timeout=60,
            )
        if resp.status_code != 200:
            log.error(f"[OCR] 服务端返回 {resp.status_code}: {resp.text[:200]}")
            raise RuntimeError(f"OCR 服务端返回 {resp.status_code}")
        data = resp.json()
        return data.get("text", data.get("result", ""))
    except requests.exceptions.ConnectionError as e:
        log.error(f"[OCR] 服务端连接失败: {e}")
        raise RuntimeError(f"无法连接 OCR 服务端 ({url})，请检查服务是否启动")
    except requests.exceptions.Timeout:
        log.error(f"[OCR] 服务端请求超时: {url}")
        raise RuntimeError(f"OCR 服务端 ({url}) 响应超时，可能正在加载模型")
