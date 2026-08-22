import os
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



def _verify_encoder(ffmpeg_path: str, encoder: str) -> bool:
    """严格验证 GPU 编码器：用 testsrc 生成测试视频 + scale 滤镜 + 输出到临时文件。
    模拟真实编码管线（_transcode_one 使用 scale/pad/fps 滤镜），确保编码器真正可用。
    """
    import tempfile
    tmp_out = None
    try:
        tmp_out = os.path.join(tempfile.gettempdir(), f"_hwaccel_test_{encoder}.mp4")
        cmd = [
            ffmpeg_path, "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc=s=320x240:d=0.2:r=30",
            "-vf", "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2,fps=30",
            "-c:v", encoder,
            "-frames:v", "3",
            "-an",
            tmp_out,
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            log.warning("hwaccel: %s 验证编码失败: %s", encoder, (r.stderr or "")[-200:])
            return False
        # 确认输出文件有效（非空）
        if not os.path.isfile(tmp_out) or os.path.getsize(tmp_out) < 100:
            log.warning("hwaccel: %s 验证输出文件无效", encoder)
            return False
        return True
    except Exception as e:
        log.warning("hwaccel: %s 验证异常: %s", encoder, e)
        return False
    finally:
        if tmp_out and os.path.isfile(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass


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
                # 验证编码器实际可用（编码一帧测试）
                if not _verify_encoder(ffmpeg_path, name):
                    log.warning("hwaccel: %s 在编码器列表中但实际不可用，跳过", name)
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
    return args


def get_hwaccel_decode_args() -> list[str]:
    return _detect()["hwaccel_decode"]
