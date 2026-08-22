"""HTTP 文件下载工具。

GUI 层不直接使用 requests.get 下载文件，
统一走本模块封装函数。
"""
from __future__ import annotations

import os

import requests

from utils.logger_utils import log


def download_file(url: str, save_path: str, *,
                  timeout: int = 120, stream: bool = True) -> bool:
    """下载文件到本地路径。

    Args:
        url: 下载 URL
        save_path: 本地保存路径
        timeout: 超时秒数
        stream: 是否流式下载（大文件推荐 True）
    Returns: 成功 True，失败 False
    """
    try:
        kwargs = {"timeout": timeout}
        if stream:
            kwargs["stream"] = True
        resp = requests.get(url, **kwargs)
        if resp.status_code != 200:
            log.error(f"[http_download] HTTP {resp.status_code}: {url}")
            return False

        with open(save_path, "wb") as f:
            if stream:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            else:
                f.write(resp.content)
        return os.path.isfile(save_path) and os.path.getsize(save_path) > 0
    except (requests.exceptions.RequestException, OSError) as e:
        log.error(f"[http_download] 下载失败 {url}: {e}")
        return False
