"""智能混剪的媒体处理工具函数与全局副作用。

本模块集中放置原 video_montage_page.py 的顶层工具函数（ffprobe/ffmpeg 时长探测、
SRT 解析、关键帧抽取、时间戳格式化等），以及 Windows 下屏蔽子进程黑框的
subprocess.Popen monkey-patch。

设计：
- 工具函数无 Qt 依赖，可被 Worker 线程和主页面安全复用。
- _patched_Popen 必须在任何 subprocess.Popen 调用前执行；导入本模块即触发，
  保证 Worker 子模块（同样 import 本模块）也能享受到无黑框效果。
"""
import hashlib
import os
import re
import subprocess


# Prevent black command prompt windows from popping up on Windows when running CLI tasks
class _patched_Popen(subprocess.Popen):  # noqa: N801
    def __init__(self, *args, **kwargs):
        if 'creationflags' not in kwargs:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs['creationflags'] |= subprocess.CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)
subprocess.Popen = _patched_Popen  # type: ignore[misc]


# Step1 原始素材支持的视频扩展名（点击选择与拖拽展开共用同一套过滤）
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v")

# 单次导入素材数量上限：防止误选整个媒体库/磁盘根目录时把上万个文件塞进列表卡死 UI
MAX_SOURCE_VIDEOS = 500

# 遍历素材文件夹时跳过的子目录名：混剪流程自身产出的派生目录，
# 避免把上一次生成的镜头片段/配音/成片当成原始素材再喂回流程。
_DERIVED_DIR_NAMES = {"splits", "output", "outputs", "final", "dubbed", "bgm", "temp", "montage_cache"}

# 景别分类关键词（大小写不敏感子串匹配）。与 docs/服务端景别分类与镜头编排需求.md
# 保持一致；如需新增景别/关键词，两侧同步修改。
# 注意：不用 "enter"/"in" 这类易误伤的短词（如 center 会误中 enter）。
SHOT_TYPE_KEYWORDS = {
    "entrance": ("入场", "进场", "开场", "entrance"),
    "exit": ("出场", "离场", "退场", "收尾", "exit"),
    "medium": ("中景", "medium shot", "medium_shot"),
    "closeup": ("特写", "closeup", "close-up", "close_up"),
}

# 景别键 → 中文名（UI 展示与文档用）
SHOT_TYPE_LABELS = {"entrance": "入场", "exit": "出场", "medium": "中景", "closeup": "特写"}

# 景别键 → 列表项前景色（素材列表里一眼区分景别；未标注保持默认色）
SHOT_TYPE_COLORS = {
    "entrance": "#2ecc71",   # 绿：入场
    "exit": "#e67e22",       # 橙：出场
    "medium": "#3498db",     # 蓝：中景
    "closeup": "#9b59b6",    # 紫：特写
}


def _natural_key(path):
    """目录 + 文件名自然序排序键：文件名里的数字按数值比较（shot_2 排在 shot_10 前）。"""
    parts = re.split(r"(\d+)", os.path.basename(path).lower())
    return (os.path.dirname(path).lower(),
            tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts))


def collect_video_files(root, exts=VIDEO_EXTS, limit=MAX_SOURCE_VIDEOS):
    """递归收集 root 及其所有子文件夹内的视频文件（Step1「选择素材文件夹」用）。

    - 跳过隐藏/系统目录（名字以 . 或 $ 开头）与混剪派生目录（splits/outputs/…），
      避免把已分割出的镜头片段当成原始素材再次导入；
    - 结果按「目录 + 文件名自然序」排序，达到 limit 即停止遍历（安全上限）。

    root 不存在或不是目录时返回空列表（空路径直接返回空，不能回退到当前工作目录）；
    返回的均为绝对路径。
    """
    root_abs = os.path.abspath(root) if root else ""
    if not root_abs or not os.path.isdir(root_abs):
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith((".", "$")) and d.lower() not in _DERIVED_DIR_NAMES]
        for fn in filenames:
            if fn.lower().endswith(tuple(exts)):
                found.append(os.path.abspath(os.path.join(dirpath, fn)))
                if len(found) >= limit:
                    return sorted(found, key=_natural_key)
    return sorted(found, key=_natural_key)


def safe_source_name(video_path, max_len=40):
    """视频文件 → 统一的短源名（splits 目录名 / 片段文件名 / srt 名共用）。

    目的：避免超长视频名（如即梦分镜描述名）导致 Windows 路径超 260 字符
    （makedirs/写片段时报 WinError 3/206）。规则：
    - 保留中文与全角字符（它们本身合法），仅防御性替换半角非法字符与控制字符
    - 折叠连续空白
    - 超过 max_len 时截断并附加 MD5 短哈希保唯一（不同长名截断后不冲突）
    全链路（目录名/片段名/读取）都经此函数，保证一致、不丢镜头。
    """
    base = os.path.splitext(os.path.basename(video_path or ""))[0]
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "video"
    if len(cleaned) > max_len:
        digest = hashlib.md5((base or "").encode("utf-8", errors="ignore")).hexdigest()[:8]  # noqa: E501
        cleaned = cleaned[:max_len] + "_" + digest
    return cleaned


def find_ffmpeg():
    from utils.platform_utils import find_ffmpeg as _ff
    return _ff()


def classify_shot_type(path):
    """按「文件夹/文件命名」识别素材景别（入场/出场/中景/特写）。

    用途：镜头重组编排（入场放头部、出场放尾部，中景/特写混排中间）
    与出入场镜头加速。识别到的景别随合成提交传给服务端
    （见 docs/服务端景别分类与镜头编排需求.md）。

    规则：
    - 关键词为大小写不敏感的子串匹配（见 SHOT_TYPE_KEYWORDS）；
    - 优先匹配文件名（去扩展名），其次父目录由深到浅逐级匹配，命中即返回；
    - 均未命中返回 ""（未标注，编排时当中间镜头处理）。
    """
    if not path:
        return ""  # 空路径直接返回，不能回退到 abspath("")=CWD 误判当前目录名
    full = os.path.abspath(path)
    if full == os.sep:
        return ""
    # 匹配顺序：文件名 → 父目录由深到浅（离文件越近越具体）
    segs = [os.path.splitext(os.path.basename(full))[0]]
    dirs = [d for d in os.path.dirname(full).split(os.sep) if d]
    segs.extend(reversed(dirs))
    for seg in segs:
        low = seg.lower()
        for st, kws in SHOT_TYPE_KEYWORDS.items():
            if any(kw in low for kw in kws):
                return st
    return ""


def apply_shot_layout_order(seq, shot_types):
    """按景别编排镜头顺序：入场放头部、出场放尾部，其余（含未标注）居中混排。

    - 各分组内保持原相对顺序（稳定排序，不额外洗牌，中景/特写天然交错）；
    - 没有任何入场/出场标注时原样返回（不影响无景别素材的既有行为）。

    shot_types: {片段路径: 景别键}，缺失或 "" 一律归入中间段。
    """
    clips = list(seq or [])
    if not clips:
        return clips
    heads = [c for c in clips if shot_types.get(c) == "entrance"]
    tails = [c for c in clips if shot_types.get(c) == "exit"]
    if not heads and not tails:
        return clips
    middle = [c for c in clips
              if shot_types.get(c) not in ("entrance", "exit")]
    return heads + middle + tails


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
    except (OSError, subprocess.SubprocessError):
        pass
    return 0.0


def parse_srt(srt_text):
    import re
    pattern = r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:[^\n]+\n*)+)"  # noqa: E501
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
        except Exception:  # SRT 时间戳解析可能失败
            pass
    return segments


def extract_keyframes(video_path, num_frames=3):
    import base64
    import os

    import cv2

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
    except Exception:  # 外部库调用（cv2 感知哈希计算）
        return None


def compute_clip_quality(clip_path):
    # 延迟导入（与 get_media_duration 一致），避免模块级依赖
    from utils.platform_utils import find_ffprobe, run_subprocess
    """评估镜头质量分数（0~100）。基于清晰度、对比度、是否有音频。
    失败返回 -1。
    """
    import cv2
    import numpy as np
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
        except Exception:  # cv2 操作 + subprocess 调用
            pass

        return min(100, round(sharpness_score + contrast_score + audio_score))
    except Exception:  # 外部库调用（cv2 质量评估）
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
