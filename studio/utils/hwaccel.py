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


def _test_encoder(ffmpeg_path: str, encoder: str) -> bool:
    """用 2 帧测试编码器是否真正可用（驱动/GPU 就绪）。
    注意：AMF 等硬件编码器有最小分辨率要求，不能用太小的尺寸。"""
    try:
        r = subprocess.run(
            [ffmpeg_path, "-y", "-f", "lavfi", "-i",
             "testsrc=duration=0.2:size=640x480:rate=25",
             "-c:v", encoder, "-frames:v", "2",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def _detect():
    result = {"encoder": "libx264", "hwaccel_decode": []}
    try:
        ffmpeg_path = find_ffmpeg()
        r = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = r.stdout + r.stderr
        for name in ("h264_nvenc", "h264_amf", "h264_qsv"):
            if name in out:
                # 编码器在列表中 ≠ 驱动可用，需实际测试 1 帧
                if not _test_encoder(ffmpeg_path, name):
                    log.warning("hwaccel: %s 在编码器列表中但实际测试失败（驱动不可用），跳过", name)
                    continue
                result["encoder"] = name
                if name == "h264_nvenc":
                    result["hwaccel_decode"] = ["-hwaccel", "cuda"]
                elif name == "h264_qsv":
                    result["hwaccel_decode"] = ["-hwaccel", "qsv"]
                log.info("hwaccel: 检测到 %s 并验证通过，使用 %s", name, name)
                return result
        log.info("hwaccel: 未检测到可用 GPU 编码器，回退 libx264")
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
    # 硬件编码器（AMF/NVENC/QSV）普遍不支持 10-bit 输入（如 yuv420p10le/HDR 素材），
    # AMF 会直接报 "10-bit input video is not supported by AMF H264 encoder" 拒绝编码。
    # 统一强制 8-bit yuv420p 输出；对 libx264 无副作用（其默认即 yuv420p）。
    args += ["-pix_fmt", "yuv420p"]
    return args


def get_hwaccel_decode_args() -> list[str]:
    return _detect()["hwaccel_decode"]
