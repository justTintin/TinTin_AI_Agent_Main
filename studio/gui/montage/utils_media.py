# -*- coding: utf-8 -*-
"""智能混剪的媒体处理工具函数与全局副作用。

本模块集中放置原 video_montage_page.py 的顶层工具函数（ffprobe/ffmpeg 时长探测、
SRT 解析、关键帧抽取、时间戳格式化等），以及 Windows 下屏蔽子进程黑框的
subprocess.Popen monkey-patch。

设计：
- 工具函数无 Qt 依赖，可被 Worker 线程和主页面安全复用。
- _patched_Popen 必须在任何 subprocess.Popen 调用前执行；导入本模块即触发，
  保证 Worker 子模块（同样 import 本模块）也能享受到无黑框效果。
"""
import os
import subprocess

# Prevent black command prompt windows from popping up on Windows when running CLI tasks
class _patched_Popen(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        if 'creationflags' not in kwargs:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs['creationflags'] |= subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
subprocess.Popen = _patched_Popen


def find_ffmpeg():
    from utils.platform_utils import find_ffmpeg as _ff
    return _ff()


def get_media_duration(filepath):
    try:
        from utils.platform_utils import find_ffprobe, run_subprocess
        ffprobe_exe = find_ffprobe()
        if not os.path.isfile(ffprobe_exe):
            ffprobe_exe = find_ffmpeg().replace("ffmpeg", "ffprobe")
        if not os.path.isfile(ffprobe_exe):
            return 0.0
        cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", filepath]
        r = run_subprocess(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0.0


def parse_srt(srt_text):
    import re
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:[^\n]+\n*)+)"
    matches = re.findall(pattern, srt_text)
    segments = []

    def srt_time_to_seconds(t_str):
        parts = t_str.replace(",", ".").split(":")
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

    for m in matches:
        try:
            start_sec = srt_time_to_seconds(m[1])
            end_sec = srt_time_to_seconds(m[2])
            text = m[3].strip()
            segments.append((start_sec, end_sec, text))
        except Exception:
            pass
    return segments


def extract_keyframes(video_path, num_frames=3):
    import cv2
    import base64
    import os

    if not video_path or not os.path.exists(video_path):
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    keyframes_b64 = []
    # Extract frames at 20%, 50%, 80% marks
    ratios = [0.2, 0.5, 0.8]
    for r in ratios:
        frame_idx = int(total_frames * r)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            # Resize frame to save bandwidth/tokens (max size 384px)
            h, w = frame.shape[:2]
            max_size = 384
            if h > max_size or w > max_size:
                if h > w:
                    new_h, new_w = max_size, int(w * max_size / h)
                else:
                    new_h, new_w = int(h * max_size / w), max_size
                frame = cv2.resize(frame, (new_w, new_h))

            # Encode as JPG
            ret_jpg, buffer = cv2.imencode('.jpg', frame)
            if ret_jpg:
                b64_str = base64.b64encode(buffer).decode('utf-8')
                keyframes_b64.append(b64_str)
    cap.release()
    return keyframes_b64


def compute_clip_hash(clip_path):
    """提取视频中间帧，计算 64 位平均哈希用于相似度比较。
    返回 64 位整数的哈希值，失败返回 None。两帧汉明距离 < 8 视为高度相似。
    """
    import cv2
    import numpy as np
    try:
        cap = cv2.VideoCapture(clip_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return None
        # 取中间帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
        avg = resized.mean()
        bits = (resized > avg).flatten()
        # 64-bit integer
        h = 0
        for b in bits:
            h = (h << 1) | int(b)
        return h
    except Exception:
        return None


def compute_clip_quality(clip_path):
    # 延迟导入（与 get_media_duration 一致），避免模块级依赖
    from utils.platform_utils import find_ffprobe, run_subprocess
    """评估镜头质量分数（0~100）。基于清晰度、对比度、是否有音频。
    失败返回 -1。
    """
    import cv2
    import numpy as np
    import subprocess
    try:
        cap = cv2.VideoCapture(clip_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return -1
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 3)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return -1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 清晰度：Laplacian 方差（越高越清晰）
        lap = cv2.Laplacian(gray, cv2.CV_64F).var()
        # 映射到 0-50 分（正常清晰视频 ~100-500，模糊 < 50）
        sharpness_score = min(50, max(0, lap / 10))

        # 对比度：灰度标准差（太低=灰片，太高=过曝）
        contrast = float(np.std(gray))
        contrast_score = min(30, max(0, (contrast - 20) * 1.5))

        # 音频：有音频 +20 分
        audio_score = 0
        try:
            from utils.platform_utils import find_ffprobe
            ffprobe = find_ffprobe()
            if not ffprobe:
                from utils.platform_utils import find_ffmpeg
                ff = find_ffmpeg()
                if ff:
                    ffprobe = ff.replace("ffmpeg", "ffprobe")
            if ffprobe:
                r = run_subprocess(
                    [ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", clip_path],
                    capture_output=True, text=True, timeout=10)
                if "audio" in (r.stdout or ""):
                    audio_score = 20
        except Exception:
            pass

        return min(100, round(sharpness_score + contrast_score + audio_score))
    except Exception:
        return -1


def format_seconds_to_srt_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds >= 1000:
        milliseconds -= 1000
        secs += 1
        if secs >= 60:
            secs -= 60
            minutes += 1
            if minutes >= 60:
                minutes -= 60
                hours += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def parse_srt_to_descriptions(srt_content):
    import re
    content = srt_content.replace("\r\n", "\n").strip()
    blocks = re.split(r'\n\s*\n', content)
    texts = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) >= 3:
            time_idx = -1
            for idx, line_str in enumerate(lines):
                if "-->" in line_str:
                    time_idx = idx
                    break
            if time_idx != -1 and time_idx + 1 < len(lines):
                text = " ".join(lines[time_idx + 1:])
                texts.append(text)
    return texts
