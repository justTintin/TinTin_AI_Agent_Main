"""花字模板包（fancy template）加载器。

模板包 JSON schema（与 docs/花字模板样式与音效方案调研.md 一致）：
{
  "template_id": "gold_pop",
  "name": "鎏金弹出",
  "style": "fontcolor=...:borderw=4:...",   // drawtext 样式串（本地直出通道）
  "jy_effect_id": "7296357486490144036",    // 剪映草稿通道的花字效果 id（可空）
  "jy_intro_anim": "复古打字机",             // 剪映入场动画名（可空）
  "sound": {"file": "sfx/pop_01.wav", "gain_db": -6},  // 出现音效（可空；
                                                        // file 相对 assets/fancy/）
  "timing": "uniform"                        // uniform=按总时长轮换 | per_line=按字幕行
}

模板来源两处：
1. 内置：studio/assets/fancy/templates/*.json（随包分发）；
2. 用户自建/剪映提取：同目录下任意新增 JSON（侦察报告转模板即可）。
"""
import glob
import json
import os

from utils.logger_utils import log

ASSETS_FANCY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # studio/
    "assets", "fancy")
TEMPLATE_DIR = os.path.join(ASSETS_FANCY_DIR, "templates")

__CACHE: list | None = None


def list_fancy_templates(force_reload: bool = False) -> list[dict]:
    """列出全部花字模板 dict；解析失败的文件跳过并记日志。结果缓存。"""
    global __CACHE
    if __CACHE is not None and not force_reload:
        return __CACHE
    templates = []
    for path in sorted(glob.glob(os.path.join(TEMPLATE_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("template_id") and data.get("name"):
                data["_path"] = path
                templates.append(data)
            else:
                log.warning(f"[花字模板] 缺 template_id/name，跳过: {path}")
        except (OSError, ValueError) as e:
            log.warning(f"[花字模板] 解析失败，跳过: {path} ({e})")
    __CACHE = templates
    return templates


def serialize_for_task(template) -> str:
    """把花字模板 dict 序列化为任务字段 fancy_template 的 JSON 串；无效返回 ""。

    供服务端任务提交用（docs/服务端花字烧制需求.md 2.4/3.1）：去掉加载器注入的
    _path，保留 template_id/name/style/jy_effect_id/jy_intro_anim/sound/timing
    等全部业务字段。服务端未支持时该字段被忽略，不影响现有流程。
    """
    if not isinstance(template, dict) or not template.get("template_id"):
        return ""
    data = {k: v for k, v in template.items() if k != "_path"}
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def get_fancy_sound_path(template: dict) -> str:
    """模板音效文件的绝对路径；未配置/文件不存在返回空串。"""
    sound = (template or {}).get("sound") or {}
    rel = str(sound.get("file") or "").strip()
    if not rel:
        return ""
    path = rel if os.path.isabs(rel) else os.path.join(ASSETS_FANCY_DIR, rel)
    return path if os.path.isfile(path) else ""


def get_fancy_sound_gain_db(template: dict) -> float:
    """模板音效增益（dB），缺省 -6（避免音效盖过人声）。"""
    try:
        return float(((template or {}).get("sound") or {}).get("gain_db", -6.0))
    except (TypeError, ValueError):
        return -6.0


# ── 本地入场动画（drawtext 可实现）───────────────────────────────────────
# 剪映动画（jy_intro_anim）→ 本地通用动画映射：drawtext 只支持 alpha/x/y 的
# t 表达式，按语义归为 4 类；未识别/空 → fade（淡入，最安全）。
#   fade: 淡入        rise: 淡入+上浮      slide: 淡入+水平滑入     pop: 淡入+衰减弹跳
_FANCY_ANIM_KEYWORDS = (
    ("滑", "slide"),       # 向左滑动 / 向右滑动
    ("弹", "pop"),         # 波浪弹入
    ("跳", "pop"),         # 跳动 / 轻微跳动
    ("晃", "pop"),         # 晃动
    ("摆", "pop"),         # 摇摆
    ("放大", "fade"),      # 放大（缩放无法用 drawtext 表达，退化为淡入）
    ("吸入", "fade"),
    ("折叠", "fade"),
    ("打字机", "fade"),
)
_VALID_ANIMS = {"fade", "rise", "slide", "pop", "none"}


def get_fancy_anim(template: dict) -> str:
    """模板本地入场动画类型：anim 字段显式优先，否则按 jy_intro_anim 语义映射。

    返回 fade/rise/slide/pop/none 之一；无效值回退 fade。
    服务端烧制如需对齐，按同名规则实现（docs/服务端花字烧制需求.md 2.4）。
    """
    t = template or {}
    anim = str(t.get("anim") or "").strip().lower()
    if anim in _VALID_ANIMS:
        return anim
    jy = str(t.get("jy_intro_anim") or "").strip()
    if not jy:
        return "fade"
    for kw, anim in _FANCY_ANIM_KEYWORDS:
        if kw in jy:
            return anim
    return "fade"


# ── 模板预览图（下拉框图标 + 预览标签）──────────────────────────────────
PREVIEW_DIR = os.path.join(ASSETS_FANCY_DIR, "previews")
PREVIEW_TEXT = "199元超值"   # 预览样本字（含数字，检验数字+描边观感）


def template_preview_path(template_id: str) -> str:
    """模板预览图缓存路径（不保证存在）。"""
    return os.path.join(PREVIEW_DIR, f"{template_id}.png")


def ensure_template_preview(template: dict, ffmpeg_path: str, font_path: str) -> str:
    """生成（或复用缓存）模板预览图，返回 PNG 绝对路径；失败返回 ""。

    黑底 240x56，按模板 style 的 drawtext 串渲染样本字——预览与烧制同一
    样式串，所见即所得。重复调用直接命中缓存；ffmpeg 失败静默返回空。
    """
    tid = str((template or {}).get("template_id") or "").strip()
    if not tid or not ffmpeg_path:
        return ""
    out = template_preview_path(tid)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    style = str(template.get("style") or "").strip()
    if not style:
        return ""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    font_esc = str(font_path).replace("\\", "/").replace(":", "\\:")
    # drawtext 居中 + 稍大字号，充分展示描边/阴影观感
    vf = (f"drawtext=fontfile='{font_esc}':text='{PREVIEW_TEXT}':"
          f"fontsize=26:x=(w-text_w)/2:y=(h-text_h)/2:{style}")
    cmd = [ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=240x56:d=1",
           "-frames:v", "1", "-vf", vf, out]
    try:
        import subprocess
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
            return out
        log.warning(f"[花字模板] 预览图生成失败 {tid}: {(r.stderr or '')[:200]}")
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"[花字模板] 预览图生成异常 {tid}: {e}")
    return ""
