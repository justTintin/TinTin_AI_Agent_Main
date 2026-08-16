# -*- coding: utf-8 -*-
"""仿爆款（Viral Clone）客户端：封装服务端 /viral/clone/* 接口族。

服务端契约（权威：/agent/registry 中 viral_clone_analyze / viral_clone_plan）：
- POST /viral/clone/analyze   拆解爆款（同步）
    {video_path: string?, material_id: int?} → {structure: object}
- POST /viral/clone/plan      复刻规划（同步，依赖 analyze）
    {structure: object, product_info: string} → {script: object}
- POST /viral/clone/flow      全链一条调用（下载→拆解→复刻；客户端仅传 material_id/video_path）
    {material_id: int?/video_path: string?, product_info: string} → {ok, structure, script}
    抖音未登录/风控 → {need_login: true} / {captcha: true}（先扫码/滑块）

下载原则（2026-08-16 定）：客户端发起的下载一律由客户端素材浏览器（apps/asset-browser，
Electron）完成，**不走服务端下载**（服务端仅做拆解/复刻）。素材浏览器下载→素材库入库后，
拿到 material_id 再进拆解。外部链接输入时客户端只负责"打开素材浏览器引导下载"。

生成（三替换）/组装（剪辑）/对比评价尚未在服务端注册为 viral 能力（卡 E-3.0），
客户端 generate()/montage()/review() 先占位返回 ok=False + 明确提示。
"""
from utils.http_client import http_post
from utils.logger_utils import log
from utils.scheduled_task_client import _server_url

# 服务端 output 上传/下载区的路径标记（analyze 的 video_path 仅接受该区域内的相对路径）
_SERVER_OUTPUT_MARKERS = ("/output/", "output\\", "output/")

# 链接 → 素材浏览器平台推断（handoff platform 字段）
_URL_PLATFORM_RULES = (
    (("douyin.com", "iesdouyin.com", "v.douyin.com"), "douyin"),
    (("bilibili.com", "b23.tv"), "bilibili"),
    (("xiaohongshu.com", "xhslink.com"), "xiaohongshu"),
    (("tiktok.com",), "tiktok"),
    (("youtube.com", "youtu.be"), "youtube"),
)


def _is_server_path(p: str) -> bool:
    """判断是否为服务端 output 上传/下载区内的路径（analyze 可直接接收）。"""
    return any(m in p for m in _SERVER_OUTPUT_MARKERS)


def _guess_platform(url: str) -> str:
    """按域名粗略推断平台（素材浏览器 handoff 用），未知返回 douyin。"""
    low = (url or "").lower()
    for domains, platform in _URL_PLATFORM_RULES:
        if any(d in low for d in domains):
            return platform
    return "douyin"


# ── 同步 API（供 Worker 调用，全部带超时）──────────────────────────────────

def analyze(video_path=None, material_id=None, timeout=600):
    """POST /viral/clone/analyze → 拆解爆款，返回结构 dict（失败返回 None）。

    二选一：
      - material_id: 素材库已有素材（客户端素材浏览器下载入库后获得）
      - video_path:  服务端 output 上传/下载区内的路径
    """
    body = {}
    if material_id is not None:
        body["material_id"] = int(material_id)
    if video_path:
        body["video_path"] = video_path
    if not body:
        log.warning("[仿爆款] analyze 需要 video_path 或 material_id 至少一个")
        return None
    try:
        r = http_post(f"{_server_url()}/viral/clone/analyze", json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[仿爆款] analyze HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"[仿爆款] analyze 失败: {e}")
    return None


def plan(structure, product_info, timeout=180):
    """POST /viral/clone/plan → 复刻规划，返回复刻脚本 dict（失败返回 None）。"""
    if not isinstance(structure, dict):
        log.warning("[仿爆款] plan 需要拆解结构（dict）")
        return None
    body = {"structure": structure, "product_info": product_info or ""}
    try:
        r = http_post(f"{_server_url()}/viral/clone/plan", json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning(f"[仿爆款] plan HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"[仿爆款] plan 失败: {e}")
    return None


def flow(material_id=None, video_path=None, product_info="", timeout=900):
    """POST /viral/clone/flow → 全链一条调用（拆解 + 复刻规划）。

    客户端**只传 material_id / video_path**（下载一律由客户端素材浏览器完成，
    不传 url，避免触发服务端下载）。
    返回 {ok, structure?, script?, need_login?, captcha?, error?}：
      - ok=True   → structure/script 就绪
      - need_login → 抖音未登录，需先扫码登录
      - captcha    → 抖音触发滑块验证
    """
    body = {"product_info": product_info or ""}
    if material_id is not None:
        body["material_id"] = int(material_id)
    elif video_path:
        body["video_path"] = video_path
    else:
        return {"ok": False, "error": "flow 需要 material_id 或 video_path"}
    try:
        r = http_post(f"{_server_url()}/viral/clone/flow", json=body, timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "error": f"flow HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json() if isinstance(r.json(), dict) else {}
        if data.get("need_login"):
            return {"ok": False, "need_login": True,
                    "error": "抖音未登录：请在素材浏览器中打开抖音扫码登录后重试"}
        if data.get("captcha"):
            return {"ok": False, "captcha": True,
                    "error": "抖音触发滑块验证：请在素材浏览器中完成验证后重试"}
        if not data.get("ok"):
            return {"ok": False, "error": data.get("error") or "flow 未返回成功"}
        return {"ok": True, "structure": data.get("structure"),
                "script": data.get("script")}
    except Exception as e:
        log.warning(f"[仿爆款] flow 失败: {e}")
        return {"ok": False, "error": f"flow 调用失败：{e}"}


# ── 客户端素材浏览器下载（下载一律走素材浏览器，不走服务端）────────────────

def open_in_asset_browser(url=None, topic="爆款仿制"):
    """打开客户端素材浏览器引导下载爆款视频。

    - url 提供时：按域名推断平台，握手后打开对应平台搜索页，下载目录指向
      「爆款仿制」专属目录（素材浏览器下载产物 → 素材库入库 → 拿 material_id）
    - url 为空：普通浏览模式
    返回 (ok, msg, download_dir?)。
    """
    try:
        from utils import asset_browser_client as ab
        if url and str(url).strip():
            platform = _guess_platform(str(url))
            return ab.launch_for_topic(topic, keyword=str(url).strip(),
                                       platform=platform)
        return ab.launch() + ("",)
    except Exception as e:
        log.warning(f"[仿爆款] 打开素材浏览器失败: {e}")
        return False, f"打开素材浏览器失败：{e}", ""


# ── 视频来源归一化 ─────────────────────────────────────────────────────────

def normalize_source(video_ref):
    """把用户输入（素材 ID / 服务端路径 / 本地文件 / 链接）归一化为 analyze 入参。

    返回 {ok, analyze_kwargs: dict, note: str, need_download?: bool}。
    链接/本地文件 → ok=False + need_download=True：请先用客户端素材浏览器下载入库，
    再填素材 ID（**下载不走服务端**）。
    """
    if video_ref is None or video_ref == "":
        return {"ok": False, "analyze_kwargs": {}, "note": "未提供爆款视频"}
    # 素材 ID（数字）
    if isinstance(video_ref, int) or str(video_ref).strip().isdigit():
        return {"ok": True, "analyze_kwargs": {"material_id": int(video_ref)},
                "note": f"素材库 id={int(video_ref)}"}
    s = str(video_ref).strip()
    # 服务端 output 路径
    if _is_server_path(s):
        return {"ok": True, "analyze_kwargs": {"video_path": s},
                "note": "服务端 output 路径"}
    # 外部链接：客户端素材浏览器下载，不走服务端
    if s.lower().startswith(("http://", "https://")):
        return {"ok": False, "need_download": True, "analyze_kwargs": {},
                "note": "请在客户端素材浏览器中下载该视频并入库，然后填素材 ID 继续"}
    # 本地文件路径（客户端文件）
    if ":" in s[:2] or s.startswith(("/", "\\")):
        return {"ok": False, "need_download": True, "analyze_kwargs": {},
                "note": "本地文件请先经素材浏览器上传/入库，再填素材 ID"}
    # 兜底：视为素材 ID 文本
    return {"ok": True, "analyze_kwargs": {"material_id": s},
            "note": f"素材 id={s}"}


# ── 端到端：拆解 + 复刻规划 ────────────────────────────────────────────────

def run_clone(video_ref, product_info="", on_log=None, timeout=900):
    """完整执行「拆解 → 复刻规划」（优先 flow 一条调用，失败回退 analyze+plan）。

    视频必须先经客户端素材浏览器下载入库（material_id）或位于服务端 output 区。
    返回 {ok, structure?, script?, error?, need_download?, need_login?, captcha?}。
    """
    def _emit(msg):
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass
        log.info(f"[仿爆款] {msg}")

    norm = normalize_source(video_ref)
    if not norm.get("ok"):
        if norm.get("need_download"):
            return {"ok": False, "need_download": True,
                    "error": norm.get("note", "请先在客户端素材浏览器中下载视频")}
        return {"ok": False, "error": norm.get("note", "爆款视频来源无效")}
    kwargs = norm["analyze_kwargs"]
    _emit(f"爆款来源：{norm['note']}")

    # 优先 flow（一条调用）
    res = flow(product_info=product_info, timeout=timeout, **kwargs)
    if res.get("ok"):
        _emit("拆解 + 复刻规划完成（flow）")
        return {"ok": True, "structure": res["structure"], "script": res["script"],
                "note": norm["note"]}
    if res.get("need_login") or res.get("captcha"):
        return {"ok": False, "need_login": res.get("need_login"),
                "captcha": res.get("captcha"), "error": res.get("error")}

    # flow 失败（如旧服务端未实现）→ 回退 analyze + plan
    _emit(f"flow 不可用（{res.get('error', '未知')}），回退分步调用")
    structure = analyze(timeout=timeout, **kwargs)
    if not structure:
        return {"ok": False, "error": "爆款拆解失败（analyze 未返回结构），请检查视频来源或服务端日志"}
    meta = structure.get("meta") or {}
    _emit(f"拆解完成：时长 {meta.get('duration', '?')}s，镜头 {meta.get('shot_count', '?')} 个")
    script = plan(structure, product_info, timeout=180)
    if not script:
        return {"ok": False, "error": "复刻规划失败（plan 未返回脚本）", "structure": structure}
    return {"ok": True, "structure": structure, "script": script, "note": norm["note"]}


# ── 占位：生成 / 组装 / 对比（服务端 E-3.0 未就绪）────────────────────────

_E30_NOT_READY = ("服务端 E-3.0 节点工作流引擎未就绪：三替换生成/组装/对比评价尚未开放，"
                  "当前仿爆款可用到「拆解 + 复刻脚本」阶段")


def generate(script, **kwargs):
    """占位：三替换素材生成（物品/人物/声色替换，RunningHub + VoxCPM2）。

    服务端 E-3.0 就绪后开放；当前恒返回 ok=False 并提示。
    """
    log.warning(f"[仿爆款] generate 占位：{_E30_NOT_READY}")
    return {"ok": False, "reason": _E30_NOT_READY, "script": script}


def montage(materials, **kwargs):
    """占位：复刻素材组装成片（剪辑引擎，同节奏同转场）。

    服务端 E-3.0 就绪后开放；当前恒返回 ok=False 并提示。
    """
    log.warning(f"[仿爆款] montage 占位：{_E30_NOT_READY}")
    return {"ok": False, "reason": _E30_NOT_READY, "materials": materials}


def review(clone_video_ref, source_structure=None, **kwargs):
    """占位：复刻成片 vs 爆款的分维度对比报告（评审链路）。

    服务端 E-3.0 就绪后开放；当前恒返回 ok=False 并提示。
    """
    log.warning(f"[仿爆款] review 占位：{_E30_NOT_READY}")
    return {"ok": False, "reason": _E30_NOT_READY, "video_ref": clone_video_ref}
