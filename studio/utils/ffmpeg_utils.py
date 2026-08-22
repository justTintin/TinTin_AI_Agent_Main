"""ffmpeg/ffprobe 命令封装。

GUI 层不直接调用 subprocess.run 执行 ffmpeg，
统一走本模块的封装函数。
"""
import os
import subprocess

from utils.logger_utils import log

# ── 供 GUI 层使用的 re-exports（避免 GUI 直接 import subprocess） ──
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CompletedProcess = subprocess.CompletedProcess
TimeoutExpired = subprocess.TimeoutExpired
PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT
DEVNULL = subprocess.DEVNULL


def find_ffmpeg() -> str:
    """查找 ffmpeg 可执行文件路径。"""
    from utils.platform_utils import find_ffmpeg as _find
    return _find()


def find_ffprobe() -> str:
    """查找 ffprobe 可执行文件路径。"""
    from utils.platform_utils import find_ffprobe as _find
    return _find()


def _no_window_flags() -> int:
    """Windows 下避免弹出控制台窗口的 creationflags。"""
    return 0x08000000 if os.name == "nt" else 0


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """运行 ffmpeg/ffprobe 子进程。

    默认：stdin=DEVNULL（防止 ffmpeg 在 QThread 中假死）、
    creationflags=无窗口（Windows）。
    """
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if "creationflags" not in kwargs and os.name == "nt":
        kwargs["creationflags"] = _no_window_flags()
    return subprocess.run(cmd, **kwargs)


def extract_frame(video: str, timestamp: float, output: str,
                  scale: str | None = None, quality: int = 4) -> bool:
    """从视频提取单帧截图。

    Args:
        video: 输入视频路径
        timestamp: 截图时间点（秒）
        output: 输出图片路径
        scale: 缩放滤镜（如 "512:-2"），None 为不缩放
        quality: JPEG 质量（2-31，越小越好）
    Returns: 成功 True
    """
    ff = find_ffmpeg()
    if not ff:
        return False
    cmd = [ff, "-y", "-ss", str(timestamp), "-i", video, "-vframes", "1"]
    if scale:
        cmd += ["-vf", f"scale={scale}"]
    cmd += ["-q:v", str(quality), output]
    run(cmd, capture_output=True)
    return os.path.isfile(output)


def cut_video(input_path: str, start: float, end: float, output: str,
              codec: str = "libx264", pix_fmt: str = "yuv420p",
              audio_codec: str = "aac") -> bool:
    """按起止时间裁剪视频。

    Args:
        input_path: 输入视频路径
        start: 开始时间（秒）
        end: 结束时间（秒）
        output: 输出视频路径
        codec: 视频编码器
        pix_fmt: 像素格式
        audio_codec: 音频编码器
    Returns: 成且输出文件非空 True
    """
    ff = find_ffmpeg()
    if not ff:
        return False
    cmd = [ff, "-y", "-ss", str(start), "-to", str(end), "-i", input_path,
           "-c:v", codec, "-pix_fmt", pix_fmt, "-c:a", audio_codec, output]
    run(cmd, capture_output=True)
    return os.path.isfile(output) and os.path.getsize(output) > 0


def change_audio_speed(input_path: str, speed: float, output_path: str) -> bool:
    """改变音频播放速度（atempo 滤镜）。

    Args:
        input_path: 输入音频路径
        speed: 速度倍率（0.5-2.0，超出范围需链式 atempo）
        output_path: 输出音频路径
    Returns: 成功 True
    """
    ff = find_ffmpeg()
    if not ff:
        return False
    cmd = [ff, "-y", "-i", input_path, "-filter:a", f"atempo={speed}", output_path]
    run(cmd, capture_output=True)
    return os.path.isfile(output_path) and os.path.getsize(output_path) > 0


def probe_duration(video: str) -> float:
    """获取视频时长（秒）。"""
    fp = find_ffprobe()
    if not fp:
        return 0.0
    cmd = [fp, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", video]
    try:
        r = run(cmd, capture_output=True, text=True, encoding="utf-8",
                errors="ignore")
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"[ffmpeg_utils] probe_duration 失败: {e}")
        return 0.0


def get_video_resolution(video: str) -> tuple[int, int]:
    """获取视频分辨率 (width, height)。

    通过 ffmpeg -i 的 stderr 输出解析分辨率信息，
    失败时返回默认值 (1280, 720)。
    """
    import re

    ff = find_ffmpeg()
    if not ff:
        return 1280, 720
    try:
        r = run([ff, "-i", video], capture_output=True, text=True,
                encoding="utf-8", errors="ignore")
        out = r.stderr or ""
        match = re.search(r",\s*(\d{2,5})x(\d{2,5})\b", out)
        if match:
            return int(match.group(1)), int(match.group(2))
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"[ffmpeg_utils] get_video_resolution 失败: {e}")
    return 1280, 720


def get_video_fps(video: str) -> float:
    """获取视频帧率 (fps)。

    通过 ffmpeg -i 的 stderr 输出解析 fps，
    失败时返回默认值 30.0。
    """
    import re

    ff = find_ffmpeg()
    if not ff:
        return 30.0
    try:
        r = run([ff, "-i", video], capture_output=True, text=True,
                encoding="utf-8", errors="ignore")
        out = r.stderr or ""
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*fps\b", out)
        if match:
            return float(match.group(1))
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"[ffmpeg_utils] get_video_fps 失败: {e}")
    return 30.0


def popen(cmd: list, **kwargs) -> subprocess.Popen:
    """启动 ffmpeg/ffprobe 子进程（Popen 模式，用于流式读取输出）。

    默认：stdin=DEVNULL、creationflags=无窗口（Windows）。
    """
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if "creationflags" not in kwargs and os.name == "nt":
        kwargs["creationflags"] = _no_window_flags()
    return subprocess.Popen(cmd, **kwargs)
