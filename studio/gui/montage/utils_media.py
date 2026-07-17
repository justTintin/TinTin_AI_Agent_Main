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
        from utils.platform_utils import find_ffprobe, create_no_window_flag
        creationflags = create_no_window_flag()
        ffprobe_exe = find_ffprobe()
        if not os.path.isfile(ffprobe_exe):
            ffprobe_exe = find_ffmpeg().replace("ffmpeg", "ffprobe")
        if not os.path.isfile(ffprobe_exe):
            return 0.0
        cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", filepath]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=10)
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
