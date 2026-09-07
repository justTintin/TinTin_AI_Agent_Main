"""混剪服务端 API 客户端。

封装 /montage/* 接口调用，GUI Worker 不直接拼 URL。
"""
import contextlib
import json
import os

import requests

from utils.http_client import http_delete, http_get, http_post
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


def list_fonts(server_url: str, timeout: int = 15) -> list:
    """GET /config/fonts — 拉取服务端字体库列表。

    响应形如 {"fonts": [{"id","family","filename","stored_as","file_path",
    "source_path","size","installed"}], "total": N}，返回 fonts 列表；
    失败或未配置地址返回 []（调用方按「无字体可选」降级，不阻断流程）。
    """
    if not server_url:
        return []
    url = f"{server_url}/config/fonts"
    try:
        r = http_get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        if isinstance(data, list):  # 兼容直接返回数组的形态
            return data
        fonts = data.get("fonts")
        return fonts if isinstance(fonts, list) else []
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] list_fonts 失败: {e}")
        return []


def scan_fonts(server_url: str, directory: str, timeout: int = 60) -> dict:
    """POST /config/fonts/scan — 让服务端扫描指定目录并导入字体。返回响应 dict。"""
    url = f"{server_url}/config/fonts/scan"
    try:
        r = http_post(url, data={"directory": directory}, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] scan_fonts 失败: {e}")
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


# ── 花字模板库（docs/服务端花字烧制需求.md 3.3，二阶段可选接口）──────────────

def list_fancy_templates(server_url: str, timeout: int = 15) -> list:
    """GET /fancy/templates — 拉取服务端花字模板库列表。

    未部署（404/405）或失败返回 []，调用方无法区分「空库」与「未部署」，
    需要区分时看 upload 的报错。
    """
    if not server_url:
        return []
    url = f"{server_url}/fancy/templates"
    try:
        r = http_get(url, timeout=timeout)
        if r.status_code in (404, 405):
            log.info("[montage] /fancy/templates 未部署（服务端未实现 3.3）")
            return []
        r.raise_for_status()
        data = r.json() or {}
        # 服务端返回 {"items": [...]}（与 /scheduled/tasks 风格一致）；兼容 templates 键与裸数组
        tpls = (data.get("templates") or data.get("items")) if isinstance(data, dict) else data
        return tpls if isinstance(tpls, list) else []
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.error(f"[montage] list_fancy_templates 失败: {e}")
        return []


def upload_fancy_templates(server_url: str, templates: list, sound_paths: dict | None = None,
                           timeout: int = 120) -> dict:
    """POST /fancy/templates — 批量导入花字模板（multipart）。

    templates: 模板 dict 列表（不带 _path）；
    sound_paths: {template_id: 本地音效绝对路径}，可选——有音效的模板随包上传，
                 文件名带 template_id 前缀（服务端按 sound_map 关联回模板）。
    返回响应 dict；服务端未部署该接口时抛 RuntimeError（消息含 404）。
    """
    if not server_url:
        raise RuntimeError("未配置服务端地址")
    url = f"{server_url}/fancy/templates"
    data = {"templates": json.dumps(templates, ensure_ascii=False)}
    sound_paths = sound_paths or {}
    if sound_paths:
        data["sound_map"] = json.dumps(
            {tid: os.path.basename(p) for tid, p in sound_paths.items()},
            ensure_ascii=False)
    handles = []
    try:
        files = []
        for tid, p in sound_paths.items():
            if os.path.isfile(p):
                f = open(p, "rb")
                handles.append(f)
                files.append(("sound_files", (f"{tid}__{os.path.basename(p)}", f)))
        r = http_post(url, data=data, files=files or None, timeout=timeout)
    finally:
        for f in handles:
            with contextlib.suppress(Exception):
                f.close()
    if r.status_code == 405:
        raise RuntimeError(
            "服务端 /fancy/templates 仅实现了查询（GET），未实现上传（POST）。"
            "需服务端按 docs/服务端花字烧制需求.md 3.3 补充 POST 后才能同步。")
    if r.status_code in (404, 405):
        raise RuntimeError(
            "服务端未部署花字模板库接口（/fancy/templates，HTTP 404）。"
            "需服务端按 docs/服务端花字烧制需求.md 3.3 实现后才能同步。")
    r.raise_for_status()
    return r.json() or {}


def delete_fancy_template(server_url: str, template_id: str, timeout: int = 15) -> dict:
    """DELETE /fancy/templates/{template_id} — 下架服务端花字模板。返回响应 dict。"""
    if not server_url:
        raise RuntimeError("未配置服务端地址")
    url = f"{server_url}/fancy/templates/{template_id}"
    r = http_delete(url, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}
