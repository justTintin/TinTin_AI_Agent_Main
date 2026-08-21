# -*- coding: utf-8 -*-
"""服务端抠图客户端 — POST /material/matting

客户端不再本地加载 rembg/U2Net 模型，统一将图片上传算力服务端抠图，
服务端返回透明背景 PNG 二进制，客户端保存即可。
"""
import os

import requests

from utils.logger_utils import log


def _server_url(server_url: str = "") -> str:
    """获取算力服务端地址（参数优先，否则走统一解析）。"""
    from utils.server_resolver import get_server_url
    return get_server_url(explicit=server_url)


def matting_image(file_path: str, model: str = "u2net", out_path: str = "",
                  server_url: str = "") -> str:
    """上传图片到服务端抠图，保存返回的透明 PNG，返回输出路径。

    Args:
        file_path: 待抠图图片路径（png/jpg 等）
        model: 服务端抠图模型名（u2net / u2netp / u2net_human_seg / isnet-general-use）
        out_path: 输出 PNG 路径（留空则与源文件同目录生成 xxx_matting.png）
        server_url: 服务端地址（留空读 ai_config.json 的 compute_server_url）

    Returns:
        抠图结果 PNG 的本地路径

    Raises:
        RuntimeError: 服务端不可达 / 接口未部署 / 返回异常
    """
    if not file_path or not os.path.isfile(file_path):
        raise RuntimeError(f"图片不存在: {file_path}")

    base = _server_url(server_url)
    url = f"{base}/material/matting"

    if not out_path:
        out_path = os.path.splitext(file_path)[0] + "_matting.png"

    log.info(f"[抠图] 上传服务端抠图: {os.path.basename(file_path)} model={model} -> {url}")
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                files={"file": (os.path.basename(file_path), f)},
                data={"model": model or "u2net"},
                timeout=120,
            )
    except requests.exceptions.ConnectionError as e:
        log.error(f"[抠图] 服务端连接失败: {e}")
        raise RuntimeError(f"无法连接算力服务端 ({base})，请检查服务是否启动")
    except requests.exceptions.Timeout:
        raise RuntimeError(f"抠图请求超时: {url}（服务端可能正在加载模型，请稍后重试）")

    if resp.status_code == 404:
        raise RuntimeError("服务端抠图接口 /material/matting 未部署，请联系管理员升级服务端")
    if resp.status_code != 200:
        raise RuntimeError(f"抠图服务端返回 HTTP {resp.status_code}: {resp.text[:200]}")

    # 正常应返回 PNG 二进制；若返回 JSON 则视为错误信息
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            data = resp.json()
            err = data.get("error") or data.get("detail") or str(data)[:200]
        except Exception:
            err = resp.text[:200]
        raise RuntimeError(f"抠图失败: {err}")

    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        raise RuntimeError(f"保存抠图结果失败: {e}")

    log.info(f"[抠图] 完成: {out_path} ({len(resp.content)/1024:.0f}KB)")
    return out_path
