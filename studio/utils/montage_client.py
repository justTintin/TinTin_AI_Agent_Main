"""混剪服务端 API 客户端。

封装 /montage/* 接口调用，GUI Worker 不直接拼 URL。
"""
import json
import os

import requests

from utils.http_client import http_get, http_post
from utils.logger_utils import log


def split(server_url: str, files: dict, data: dict | None = None,
          timeout: int | tuple = 590) -> dict:
    """POST /montage/split — 服务端镜头分割+分析。

    files: {"file": (filename, file_obj, mime_type)}
    data: form 字段
    """
    url = f"{server_url}/montage/split"
    try:
        r = http_post(url, data=data, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] split 失败: {e}")
        raise


def concat(server_url: str, files: list, data: dict | None = None,
           timeout: int = 120) -> dict:
    """POST /montage/concat — 多段视频拼接（multipart）。

    files: [("files", (filename, file_obj)), ...]
    data: form 字段
    """
    url = f"{server_url}/montage/concat"
    try:
        r = http_post(url, data=data, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] concat 失败: {e}")
        raise


def beat(server_url: str, files: list, data: dict | None = None,
         timeout: int = 120) -> dict:
    """POST /montage/beat — 卡点成片生成（multipart）。

    files: [("files", (filename, file_obj)), ...]
    data: form 字段
    """
    url = f"{server_url}/montage/beat"
    try:
        r = http_post(url, data=data, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] beat 失败: {e}")
        raise


def result_url(server_url: str, task_id: str, variant: int | None = None) -> str:
    """构造 /montage/result/{task_id}[/{variant}] 下载 URL。"""
    if not server_url:
        return ""
    url = f"{server_url}/montage/result/{task_id}"
    if variant is not None:
        url = f"{url}/{variant}"
    return url


def download_result(url: str, path: str, timeout: int = 300) -> str | None:
    """流式下载混剪结果文件。返回保存路径或 None。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with http_get(url, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                log.warning(f"[montage] download → HTTP {r.status_code}")
                return None
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return path
    except (OSError, requests.exceptions.RequestException) as e:
        log.error(f"[montage] download 失败: {e}")
        return None


def poll_unified(server_url: str, task_id: str, timeout: int = 15) -> dict | None:
    """GET /tasks/unified/{task_id} — 轮询统一任务状态。"""
    url = f"{server_url}/tasks/unified/{task_id}"
    try:
        r = http_get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[montage] poll_unified → HTTP {r.status_code}")
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] poll_unified 失败: {e}")
    return None
