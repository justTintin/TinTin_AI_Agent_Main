"""模板参数构造器：从 GUI 层下沉的参数收集、摘要提取、请求构建逻辑。

从 compile_video_page.py 和 mg_animation_page.py 中统一下沉的业务计算逻辑。
"""
import os
from collections.abc import Callable
from typing import Any

from utils.json_utils import from_editor_text


def collect_script_params(
    script: dict[str, Any],
    count: int = 1,
    ratio: str = "9:16",
    platform: str = "",
    autocheck: bool = False,
) -> dict[str, Any]:
    """收集脚本成片的提交参数（适配服务端 storyboard_montage 执行器契约）。

    服务端契约：
      params = {shots:[{index,shot_type,duration,visual,audio}], voice_settings:{speaker}}  # noqa: E501
    注意：文案字段服务端叫 `audio`（不是 storyboard 的 narration）。

    Args:
        script: 脚本文档（包含 shots 列表等）
        count: 变体数量
        ratio: 画面比例
        platform: 发布平台
        autocheck: 是否自动检查

    Returns:
        服务端 storyboard_montage 执行器的参数字典
    """
    s = script or {}
    raw_shots = s.get("shots", [])
    server_shots = []
    for sh in raw_shots:
        server_shots.append({
            "index": sh.get("index", 0),
            "shot_type": sh.get("shot_type", ""),
            "duration": sh.get("duration", 3),
            "visual": sh.get("visual", ""),
            "audio": sh.get("audio", "") or sh.get("narration", ""),
            "material_path": sh.get("material_path", ""),
            "material_type": sh.get("material_type", ""),
            "sfx": sh.get("sfx", ""),
        })
    return {
        "shots": server_shots,
        "voice_settings": {"speaker": "default"},
        "count": count,
        "script_name": s.get("name", "") or s.get("id", ""),
        "script_path": s.get("path", ""),
        "topic": s.get("topic", ""),
        "ratio": ratio,
        "total_duration": s.get("total_duration", 0),
        "shot_count": s.get("shot_count", 0),
        "predict_platform": platform,
        "autocheck": autocheck,
    }


def extract_script_summary(
    template: dict[str, Any],
    material_name_fn: Callable[[Any], str] | None = None,
) -> dict[str, Any] | None:
    """从模板的 storyboard/script 字段中提取素材/口播/音频/音效清单。

    Args:
        template: 模板字典
        material_name_fn: 素材名称提取函数（默认取 basename）

    Returns:
        摘要字典，包含 shot_count, total_duration, ratio, materials, narrations, audio_files, sfx_files  # noqa: E501
        如果无法提取则返回 None
    """
    if material_name_fn is None:
        def material_name_fn(m):
            return os.path.basename(str(m)) if m else ""

    script = None
    for key in ("storyboard", "script", "storyboard_script",
                "storyboard_text", "storyboard_json", "template_script",
                "montage_script"):
        v = template.get(key)
        if v:
            script = v
            break
    if not script and isinstance(template.get("shots"), list):
        script = template
    if not script:
        return None
    if isinstance(script, str):
        script = from_editor_text(script)
    if isinstance(script, dict):
        shots = script.get("shots") or []
    elif isinstance(script, list):
        shots = script
    else:
        return None
    if not isinstance(shots, list):
        return None

    total_duration = 0.0
    materials = []
    narrations = []
    audio_files = []
    sfx_files = []

    for sh in shots:
        if not isinstance(sh, dict):
            continue
        total_duration += float(
            sh.get("duration") or sh.get("duration_seconds") or 0
        )
        # 素材
        for k in ("materials", "material_path", "visual", "image",
                  "video", "media", "source", "clip", "file",
                  "scene", "shot", "description"):
            mv = sh.get(k)
            if not mv:
                continue
            if isinstance(mv, list):
                for m in mv:
                    materials.append(material_name_fn(m))
            else:
                materials.append(material_name_fn(mv))
        # 口播
        for k in ("audio", "narration", "subtitle", "text",
                  "voiceover", "copy", "caption", "script"):
            nv = sh.get(k)
            if nv and isinstance(nv, str):
                narrations.append(nv.strip())
                break
        # 配音
        for k in ("audio", "voice", "audio_file", "bgm",
                  "sound", "music", "voiceover"):
            av = sh.get(k)
            if av and isinstance(av, str) and (av.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))
                    or "://" in av or os.path.splitext(av)[1]):
                audio_files.append(os.path.basename(av))
                break
        # 音效
        for k in ("sfx", "sound_effect", "effect", "sound"):
            sv = sh.get(k)
            if sv:
                if isinstance(sv, list):
                    for s in sv:
                        sfx_files.append(material_name_fn(s))
                else:
                    sfx_files.append(material_name_fn(sv))

    return {
        "shot_count": len(shots),
        "total_duration": total_duration,
        "ratio": script.get("ratio") if isinstance(script, dict) else "",
        "materials": materials,
        "narrations": narrations,
        "audio_files": audio_files,
        "sfx_files": sfx_files,
    }


def _template_backend(template: dict[str, Any]) -> str:
    """获取模板渲染时使用的后端 template id。"""
    if template.get("is_builtin") or template.get("builtin"):
        return template.get("id", "")
    return template.get("backend") or template.get("id", "")


def build_mg_request(
    template: dict[str, Any],
    values: dict[str, Any],
    common: dict[str, Any],
    scenes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构建 MG 动画请求参数。

    Args:
        template: 模板字典（需包含 id/is_builtin 或 backend 字段）
        values: 表单值（用户输入）
        common: 通用参数（ratio, scale, color, bg, font_size, duration）
        scenes: 场景列表（可选）

    Returns:
        MG 请求字典
    """
    if not template:
        raise ValueError("请先选择模板")
    backend = _template_backend(template)

    req: dict[str, Any] = {"template": backend}
    # 添加通用参数
    for k, v in common.items():
        if v is not None:
            req[k] = v

    # 合并，用户输入值优先
    for k, v in values.items():
        if v is not None and v != "":
            req[k] = v

    # scenes
    if scenes:
        req["scenes"] = scenes

    return req
