"""统一模板服务端客户端（按 OpenAPI /templates/* 实现，tag：模板统一）。

已从旧 `/template/*`（成片模板）切换到统一模板接口：

  GET    /templates                   模板列表（?type=video/motion/cover）
  POST   /templates                   保存/创建模板（同 id 覆盖；内置不可覆盖）
  GET    /templates/{template_id}     查询单个模板完整定义
  PUT    /templates/{template_id}     更新自定义模板（整体替换）
  DELETE /templates/{template_id}     删除自定义模板（内置不可删）
  POST   /templates/validate          校验模板定义（TemplateIn）
  POST   /templates/analyze-video     动效视频 -> 生成统一模板定义
  POST   /templates/preview           动效/封面模板单帧预览（Remotion still）
  POST   /templates/render            统一渲染入口（RenderIn）-> task_id
  POST   /templates/render/beat       音乐卡点成片渲染（multipart）-> task_id
  GET    /templates/render/result/{task_id}   渲染进度/结果
  GET    /templates/render/download/{task_id} 渲染结果下载

历史兼容说明：
  - list_templates 的 category 参数映射到统一 type 过滤：
    ""->全部、"mg"/"motion"->motion、"cover"->cover、"video"->video
  - match_slots 在统一接口中暂无对应端点，仍走旧 /template/match（兼容保留）。
"""
import contextlib
import json
import os

import requests

from utils.http_client import http_delete, http_get, http_post, http_put
from utils.logger_utils import log

_CATEGORY_TO_TYPE = {
    "": "",
    "mg": "motion",
    "motion": "motion",
    "cover": "cover",
    "video": "video",
}


def _server_url():
    """读取 compute_server_url。"""
    try:
        import json as _json

        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as _f:
                cfg = _json.load(_f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def _safe_json(resp):
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        log.warning(f"[Template] JSON parse failed: {e}")
        return {}


def _task_id(data):
    """从统一渲染提交响应中提取任务 ID。"""
    if not isinstance(data, dict):
        return None
    return data.get("task_id") or data.get("id") or None


# ── 模板 CRUD（统一接口 /templates）──────────────────────────────

def list_templates(category="", timeout=10):
    """GET /templates?type=... 返回模板列表。

    category 兼容旧版约定：""=全部、"mg"/"motion"=动效、"cover"=封面、"video"=成片。
    服务端响应：{"templates": [...], "total": N}
    """
    url = _server_url()
    if not url:
        return []
    t = _CATEGORY_TO_TYPE.get((category or "").strip().lower(), category or "")
    params = {"type": t} if t else {}
    try:
        r = http_get(f"{url}/templates", params=params, timeout=timeout)
        if r.status_code == 200:
            data = _safe_json(r)
            if isinstance(data, list):
                return data
            return data.get("templates") or data.get("items") or data.get("data") or []
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] list_templates failed: {e}")
    return []


def get_template(template_id, timeout=10):
    """GET /templates/{template_id}。返回模板定义 dict。"""
    url = _server_url()
    if not url:
        return None
    try:
        r = http_get(f"{url}/templates/{template_id}", timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] get_template failed: {e}")
    return None


def export_template(template_id, timeout=10):
    """GET /templates/{template_id}（旧 /template/export/{id} 的等价查询）。"""
    return get_template(template_id, timeout=timeout)


def validate_template(template: dict, timeout=10):
    """POST /templates/validate。返回校验结果 dict（如 {"ok": true}）。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    try:
        r = http_post(f"{url}/templates/validate", json=template, timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] validate_template failed: {e}")
    return {}


def save_template(template: dict, timeout=15):
    """POST /templates 保存/创建模板（同 id 覆盖更新；内置模板不可覆盖）。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not isinstance(template, dict):
        raise TypeError("template 必须是 dict")
    try:
        r = http_post(f"{url}/templates", json=template, timeout=timeout)
        if r.status_code in (200, 201):
            return _safe_json(r)
        log.warning(f"[Template] save_template HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] save_template failed: {e}")
    return None


def import_template(template: dict, timeout=15):
    """POST /templates 保存自定义模板（旧 /template/import 的等价接口）。"""
    return save_template(template, timeout=timeout)


def update_template(template_id, template: dict, timeout=15):
    """PUT /templates/{template_id} 更新自定义模板（整体替换）。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not isinstance(template, dict):
        raise TypeError("template 必须是 dict")
    try:
        r = http_put(f"{url}/templates/{template_id}", json=template, timeout=timeout)
        if r.status_code in (200, 201):
            return _safe_json(r)
        log.warning(f"[Template] update_template HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] update_template failed: {e}")
    return None


def delete_template(template_id, timeout=10):
    """DELETE /templates/{template_id} 删除自定义模板（内置不可删）。"""
    url = _server_url()
    if not url:
        return None
    try:
        r = http_delete(f"{url}/templates/{template_id}", timeout=timeout)
        if r.status_code in (200, 204):
            return _safe_json(r) if r.status_code == 200 else {}
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] delete_template failed: {e}")
    return None


# ── 统一渲染 / 预览 / 分析 ───────────────────────────────────────

def generate(template_id, topic="", top_k=1, timeout=600):
    """POST /templates/render 统一渲染入口。

    兼容旧版 generate(template_id, topic, top_k) 调用：topic/top_k 放入 params。
    返回 task_id（str），失败返回 None。
    """
    return render(
        template_id,
        params={"topic": topic or "", "top_k": top_k},
        timeout=timeout,
    )


def render(template_id, params=None, ratio="9:16", width=None, height=None,
           scale=1.0, render_type="", timeout=600):
    """POST /templates/render（RenderIn）→ 返回 task_id（str），失败返回 None。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not template_id:
        raise ValueError("template_id 不能为空")
    body = {"template_id": template_id}
    if params:
        body["params"] = params
    if ratio:
        body["ratio"] = ratio
    if width:
        body["width"] = int(width)
    if height:
        body["height"] = int(height)
    if scale is not None:
        body["scale"] = float(scale)
    if render_type:
        body["type"] = render_type
    try:
        r = http_post(f"{url}/templates/render", json=body, timeout=timeout)
        if r.status_code in (200, 201):
            data = _safe_json(r)
            task_id = _task_id(data)
            log.info(f"[Template] render task_id={task_id}, template_id={template_id}")
            return task_id
        log.warning(f"[Template] render HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] render failed: {e}")
    return None


def render_cover_image(template_id, params=None, ratio="9:16", width=None, height=None,
                         scale=1.0, timeout=120):
    """渲染封面（type=cover）：服务端 /templates/render 对 cover 类型直接同步返回 PNG。

    与 render()（motion/video 异步任务）不同，cover 响应是 image/png 字节。
    返回 PNG 字节（bytes）；失败返回 None。
    """
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not template_id:
        raise ValueError("template_id 不能为空")
    body = {"template_id": template_id}
    if params:
        body["params"] = params
    if ratio:
        body["ratio"] = ratio
    if width:
        body["width"] = int(width)
    if height:
        body["height"] = int(height)
    if scale is not None:
        body["scale"] = float(scale)
    try:
        r = http_post(f"{url}/templates/render", json=body, timeout=timeout)
        if r.status_code == 200:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "image" in ctype:
                return r.content
            log.warning(f"[Template] render_cover_image 返回非图片类型: {ctype} {r.text[:120]}")  # noqa: E501
            return None
        log.warning(f"[Template] render_cover_image HTTP {r.status_code}: {r.text[:200]}")  # noqa: E501
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] render_cover_image failed: {e}")
    return None


def render_beat(template_id, music, videos=None, params=None, clip_urls="", timeout=600):  # noqa: E501
    """POST /templates/render/beat（multipart）→ 返回 task_id（str）。

    music: 本地音频文件路径（必填）；videos: 本地素材文件路径列表（可选）；
    params: dict，会序列化为 JSON 字符串覆盖模板默认风格参数
    （threshold/count/time_limit/min_duration/max_duration/transition/aspect 等）。
    """
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not template_id:
        raise ValueError("template_id 不能为空")
    if not music or not os.path.isfile(music):
        raise FileNotFoundError(f"music 文件不存在: {music}")
    data = {
        "template_id": template_id,
        "params": json.dumps(params or {}, ensure_ascii=False),
        "clip_urls": clip_urls or "",
    }
    files = [("music", (os.path.basename(music), open(music, "rb")))]  # noqa: SIM115
    for path in (videos or []):
        if os.path.isfile(path):
            files.append(("videos", (os.path.basename(path), open(path, "rb"))))  # noqa: SIM115
    try:
        r = http_post(f"{url}/templates/render/beat", data=data, files=files, timeout=timeout)  # noqa: E501
        if r.status_code in (200, 201):
            data = _safe_json(r)
            task_id = _task_id(data)
            log.info(f"[Template] render_beat task_id={task_id}, template_id={template_id}")  # noqa: E501
            return task_id
        log.warning(f"[Template] render_beat HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] render_beat failed: {e}")
    finally:
        for _f in files:
            with contextlib.suppress(OSError):
                _f[1][1].close()
    return None


def render_result(task_id, timeout=15):
    """GET /templates/render/result/{task_id}。返回状态 dict：
    {id, status, progress, result{output_url,...}, error}。
    """
    url = _server_url()
    if not url or not task_id:
        return {}
    try:
        r = http_get(f"{url}/templates/render/result/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] render_result failed: {e}")
    return {}


def render_download(task_id, timeout=60):
    """GET /templates/render/download/{task_id}。返回 requests.Response（可流式保存）。"""
    url = _server_url()
    if not url or not task_id:
        return None
    try:
        r = http_get(f"{url}/templates/render/download/{task_id}", timeout=timeout)
        if r.status_code == 200:
            return r
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] render_download failed: {e}")
    return None


def download_render_result(output_url, local_path, timeout=120):
    """下载渲染结果到本地文件。

    output_url 可以是完整 URL 或服务端相对路径（自动拼接 compute_server_url）。
    """
    import os

    from utils.mg_server_client import _ensure_url

    full = _ensure_url(output_url)
    try:
        r = http_get(full, stream=True, timeout=timeout)
        r.raise_for_status()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return local_path
    except (requests.exceptions.RequestException, OSError) as e:
        log.warning(f"[Template] download_render_result failed: {e}")
        return None


def poll_render_status(task_id, timeout=10):
    """轮询渲染任务状态，依次尝试多个端点。

    优先 /templates/render/result/{id}，回退 /tasks/unified/{id}、
    /scheduled/tasks/{id}、/editor/render/{id}。
    返回状态 dict 或 None。
    """
    url = _server_url()
    if not url or not task_id:
        return None
    for endpoint in (
        f"{url}/templates/render/result/{task_id}",
        f"{url}/tasks/unified/{task_id}",
        f"{url}/scheduled/tasks/{task_id}",
        f"{url}/editor/render/{task_id}",
    ):
        try:
            r = http_get(endpoint, timeout=timeout)
            if r.status_code == 200:
                return _safe_json(r)
        except requests.exceptions.RequestException:
            continue
    return None


def analyze_video(file_path=None, material_id=None, timeout=600):
    """POST /templates/analyze-video。上传动效视频 → 返回生成的统一模板定义 dict。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not file_path and not material_id:
        raise ValueError("file_path 与 material_id 至少提供一个")
    data = {}
    files = {}
    if file_path:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"file 不存在: {file_path}")
        files["file"] = (os.path.basename(file_path), open(file_path, "rb"))  # noqa: SIM115
    if material_id:
        data["material_id"] = int(material_id)
    try:
        r = http_post(f"{url}/templates/analyze-video", data=data or None, files=files or None, timeout=timeout)  # noqa: E501
        if r.status_code in (200, 201):
            return _safe_json(r)
        log.warning(f"[Template] analyze_video HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] analyze_video failed: {e}")
    finally:
        for _f in files.values():
            with contextlib.suppress(OSError):
                _f[1].close()
    return None


def preview(template_id, params=None, ratio="9:16", width=None, height=None,
            scale=1.0, render_type="", timeout=120):
    """POST /templates/preview（RenderIn）→ 单帧预览结果 dict。"""
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not template_id:
        raise ValueError("template_id 不能为空")
    body = {"template_id": template_id}
    if params:
        body["params"] = params
    if ratio:
        body["ratio"] = ratio
    if width:
        body["width"] = int(width)
    if height:
        body["height"] = int(height)
    if scale is not None:
        body["scale"] = float(scale)
    if render_type:
        body["type"] = render_type
    try:
        r = http_post(f"{url}/templates/preview", json=body, timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
        log.warning(f"[Template] preview HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] preview failed: {e}")
    return {}


# ── 素材匹配（兼容保留：统一接口暂无对应端点）────────────────────────

def match_slots(tags, top_k=5, timeout=10):
    """POST /template/match（旧成片模板接口，兼容保留）。返回候选素材列表。

    注：统一模板接口（/templates/*）暂无 slot 匹配端点。
    """
    url = _server_url()
    if not url:
        return []
    try:
        r = http_post(f"{url}/template/match", json={"tags": tags, "top_k": top_k}, timeout=timeout)  # noqa: E501
        if r.status_code == 200:
            data = _safe_json(r)
            if isinstance(data, list):
                return data
            return data.get("items") or data.get("data") or []
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] match_slots failed: {e}")
    return []


# ── 模板引擎：智能素材匹配 / 一键成片 / 模板导入 ──────────────────────

def match_materials(slots, material_ids=None, top_k=5, timeout=30):
    """POST /montage/match — 按模板 slot 的 tag 列表智能匹配素材。

    slots: [{slot, tags, type, required}, ...]
    material_ids: 可选，限定在指定素材 ID 集合内匹配
    top_k: 每个 slot 返回候选数量
    返回: {slot: [{material_id, score, ...}, ...], ...}
    """
    url = _server_url()
    if not url:
        return {}
    payload = {"slots": slots, "top_k": top_k}
    if material_ids:
        payload["material_ids"] = list(material_ids)
    try:
        r = http_post(f"{url}/montage/match", json=payload, timeout=timeout)
        if r.status_code == 200:
            return _safe_json(r)
        log.warning(f"[Template] match_materials HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] match_materials failed: {e}")
    return {}


def generate_template(template_id, slot_materials, params=None, ratio="9:16",
                      width=None, height=None, scale=1.0, timeout=600):
    """POST /template/generate — 模板成片一键编译。

    template_id: 模板 ID
    slot_materials: {slot: material_id, ...} 每个 slot 绑定的素材
    params: 模板自定义参数 {topic, bgm_style, ...}
    返回 task_id（str），失败返回 None
    """
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    body = {
        "template_id": template_id,
        "slot_materials": slot_materials,
    }
    if params:
        body["params"] = params
    if ratio:
        body["ratio"] = ratio
    if width:
        body["width"] = int(width)
    if height:
        body["height"] = int(height)
    if scale is not None:
        body["scale"] = float(scale)
    try:
        r = http_post(f"{url}/template/generate", json=body, timeout=timeout)
        if r.status_code in (200, 201):
            data = _safe_json(r)
            task_id = _task_id(data)
            log.info(f"[Template] generate_template task_id={task_id}")
            return task_id
        log.warning(f"[Template] generate_template HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] generate_template failed: {e}")
    return None


def import_template_file(file_path, name="", category="", description="", timeout=60):
    """POST /template/import — 导入剪映(.drt)/PR(.xml) 模板文件。

    file_path: 本地文件路径
    name/category/description: 模板元信息
    返回导入的模板 dict，失败返回 None
    """
    url = _server_url()
    if not url:
        raise RuntimeError("未配置 compute_server_url")
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"模板文件不存在: {file_path}")
    data = {"name": name or os.path.basename(file_path),
            "category": category,
            "description": description}
    files = [("file", (os.path.basename(file_path), open(file_path, "rb")))]  # noqa: SIM115
    try:
        r = http_post(f"{url}/template/import", data=data or None, files=files or None, timeout=timeout)  # noqa: E501
        if r.status_code in (200, 201):
            return _safe_json(r)
        log.warning(f"[Template] import_template_file HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        log.warning(f"[Template] import_template_file failed: {e}")
    finally:
        for _f in files:
            with contextlib.suppress(OSError):
                _f[1][1].close()
    return None


def list_video_templates(category="", timeout=10):
    """GET /templates?type=video — 获取成片模板列表（type=video）。"""
    return list_templates(category="video", timeout=timeout)
