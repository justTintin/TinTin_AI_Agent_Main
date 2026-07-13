# -*- coding: utf-8 -*-
"""OCR 服务端客户端 — POST /material/ocr"""
import os
import requests

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
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{url}/material/ocr",
            files={"file": (os.path.basename(file_path), f, "image/png")},
            timeout=60,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"OCR 服务端返回 {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data.get("text", data.get("result", ""))
