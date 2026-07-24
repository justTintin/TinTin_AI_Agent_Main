import subprocess
import logging
from functools import lru_cache

from utils.platform_utils import find_ffmpeg

log = logging.getLogger(__name__)

_PRESET_MAP = {
    "h264_nvenc": {
        "slow": "p7",
        "medium": "p5",
        "fast": "p3",
        "veryfast": "p2",
        "superfast": "p1",
    },
    "h264_amf": {
        "slow": "quality",
        "medium": "balanced",
        "fast": "speed",
        "veryfast": "speed",
        "superfast": "speed",
    },
    "h264_qsv": {
        "slow": "veryslow",
        "medium": "medium",
        "fast": "veryfast",
        "veryfast": "veryfast",
        "superfast": "veryfast",
    },
    "libx264": {
        "slow": "slow",
        "medium": "medium",
        "fast": "fast",
        "veryfast": "veryfast",
        "superfast": "superfast",
    },
}

_QUALITY_FLAG = {
    "h264_nvenc": "-cq",
    "h264_amf": "-qp_i",
    "h264_qsv": "-global_quality",
    "libx264": "-crf",
}


@lru_cache(maxsize=1)
def _detect():
    result = {"encoder": "libx264", "hwaccel_decode": []}
    try:
        ffmpeg_path = find_ffmpeg()
        r = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, errors="replace", timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout or "") + (r.stderr or "")
        for name in ("h264_nvenc", "h264_amf", "h264_qsv"):
            if name in out:
                result["encoder"] = name
                if name == "h264_nvenc":
                    result["hwaccel_decode"] = ["-hwaccel", "cuda"]
                elif name == "h264_qsv":
                    result["hwaccel_decode"] = ["-hwaccel", "qsv"]
                log.info("hwaccel: 检测到 %s，使用 %s", name, name)
                return result
        log.info("hwaccel: 未检测到 GPU 编码器，回退 libx264")
    except Exception as e:
        log.warning("hwaccel 检测失败，回退 libx264: %s", e)
    return result


def get_encoder() -> str:
    return _detect()["encoder"]


def get_video_encode_args(crf: int = 23, preset: str = "fast") -> list[str]:
    info = _detect()
    enc = info["encoder"]
    pmap = _PRESET_MAP[enc]
    mapped = pmap.get(preset, pmap.get("fast", list(pmap.values())[0]))
    args = ["-c:v", enc, "-preset", mapped]
    qf = _QUALITY_FLAG[enc]
    if enc == "h264_nvenc":
        args += [qf, str(crf), "-rc", "vbr_hq"]
    elif enc == "h264_amf":
        args += [qf, str(crf), "-qp_p", str(crf)]
    else:
        args += [qf, str(crf)]
    return args


def get_hwaccel_decode_args() -> list[str]:
    return _detect()["hwaccel_decode"]
