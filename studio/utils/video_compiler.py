import contextlib
import json
import logging
import os
import shutil
import tempfile

from config.paths import PROJECT_ROOT, WORKSPACE_ROOT

from utils.hwaccel import get_video_encode_args
from utils.platform_utils import find_ffmpeg, find_ffprobe, run_subprocess

RATIO_SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _find(name):
    for c in (os.path.join(WORKSPACE_ROOT, name), os.path.join(PROJECT_ROOT, name), name):  # noqa: E501
        if os.path.isfile(c):
            return c
    return shutil.which(name) or name


def _run(args, cwd=None):
    r = run_subprocess(args, capture_output=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-400:] or "ffmpeg 失败")  # noqa: E501


def _probe_duration(path):
    try:
        ffprobe = find_ffprobe()
        r = run_subprocess([ffprobe, "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", path],
                           capture_output=True)
        return float((r.stdout or b"").decode().strip() or 0)
    except (ValueError, OSError):
        return 0.0


def _tc(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_text(text, n):
    import re
    parts = [p.strip() for p in re.split(r"[。！？\.!?\n]+", text or "") if p.strip()]
    if not parts:
        return [""] * n
    if len(parts) >= n:
        out, per = [], max(1, len(parts) // n)
        for i in range(n):
            seg = parts[i * per:(i + 1) * per] if i < n - 1 else parts[i * per:]
            out.append("，".join(seg))
        return out
    return parts + [""] * (n - len(parts))


def _write_srt(srt_path, text, n, per_dur):
    segs = _split_text(text, n)
    lines = []
    for i, seg in enumerate(segs):
        if not seg:
            continue
        start, end = i * per_dur, (i + 1) * per_dur
        lines.append(f"{i + 1}\n{_tc(start)} --> {_tc(end)}\n{seg}\n")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def collect_images(folder):
    out = []
    if folder and os.path.isdir(folder):
        for root, _d, files in os.walk(folder):
            for fn in sorted(files):
                if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
                    out.append(os.path.join(root, fn))
    return out


def compile_video(images, out_path, audio="", cover="", subtitle_text="",
                  ratio="9:16", per_dur=3.0, fps=30, intro="", progress=None):
    def _p(msg):
        if progress:
            with contextlib.suppress(Exception):
                progress(msg)

    if not images:
        raise RuntimeError("没有可用的图片素材。")
    ffmpeg = find_ffmpeg()
    W, H = RATIO_SIZES.get(ratio, (720, 1280))  # noqa: N806
    n = len(images)
    dur = float(per_dur)
    if audio and os.path.isfile(audio):
        ad = _probe_duration(audio)
        if ad > 0:
            dur = max(0.8, ad / n)

    tmp = tempfile.mkdtemp(prefix="compile_")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p")
    try:
        _p(f"拼接 {n} 张素材…")
        listf = os.path.join(tmp, "list.txt")
        with open(listf, "w", encoding="utf-8") as f:
            for img in images:
                f.write(f"file '{os.path.abspath(img)}'\nduration {dur}\n")
            f.write(f"file '{os.path.abspath(images[-1])}'\n")
        slideshow = os.path.join(tmp, "slideshow.mp4")
        _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", listf,
              "-vf", vf, *get_video_encode_args(crf=23, preset="veryfast"), slideshow])
        cur = slideshow

        if subtitle_text and subtitle_text.strip():
            _p("烧录字幕…")
            _write_srt(os.path.join(tmp, "subs.srt"), subtitle_text, n, dur)
            sub_out = os.path.join(tmp, "sub.mp4")
            style = "FontSize=18,Outline=2,Alignment=2,MarginV=60"
            _run([ffmpeg, "-y", "-i", "slideshow.mp4",
                  "-vf", f"subtitles=subs.srt:force_style='{style}'",
                  *get_video_encode_args(crf=23, preset="veryfast"), "sub.mp4"], cwd=tmp)  # noqa: E501
            cur = sub_out

        pre = []
        if intro and os.path.isfile(intro):
            _p("加开场动画…")
            iv = os.path.join(tmp, "intro.mp4")
            _run([ffmpeg, "-y", "-i", intro, "-vf", vf, "-an",
                  *get_video_encode_args(crf=23, preset="veryfast"), iv])
            pre.append(iv)
        if cover and os.path.isfile(cover):
            _p("加封面片头…")
            cov = os.path.join(tmp, "cover.mp4")
            _run([ffmpeg, "-y", "-loop", "1", "-t", "2", "-i", cover,
                  "-vf", vf, *get_video_encode_args(crf=23, preset="veryfast"), cov])
            pre.append(cov)
        if pre:
            inputs = []
            for clip in pre + [cur]:
                inputs += ["-i", clip]
            n = len(pre) + 1
            streams = "".join(f"[{i}:v]" for i in range(n))
            cat = os.path.join(tmp, "cat.mp4")
            _run([ffmpeg, "-y"] + inputs +
                 ["-filter_complex", f"{streams}concat=n={n}:v=1:a=0[v]", "-map", "[v]",
                  *get_video_encode_args(crf=23, preset="veryfast"), cat])
            cur = cat

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if audio and os.path.isfile(audio):
            _p("混入配音…")
            _run([ffmpeg, "-y", "-i", cur, "-i", audio, "-c:v", "copy",
                  "-c:a", "aac", "-shortest", out_path])
        else:
            _run([ffmpeg, "-y", "-i", cur, "-c", "copy", out_path])
        _p("完成")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split_groups(images, n):
    """把 images 尽量均分成 n 组；不足 n 时循环填充。"""
    if not images:
        return [[] for _ in range(n)]
    if len(images) >= n:
        k, m = divmod(len(images), n)
        groups = []
        start = 0
        for i in range(n):
            size = k + (1 if i < m else 0)
            groups.append(images[start:start + size])
            start += size
        return groups
    else:
        return [[images[i % len(images)]] for i in range(n)]


def scan_storyboard_scripts(base_dir):
    """扫描所有分镜 JSON 脚本。返回 [{name, path, topic, ratio, total_duration, shot_count, shots}]。"""  # noqa: E501
    logger = logging.getLogger(__name__)
    results: list[dict] = []
    try:
        if not base_dir or not os.path.isdir(base_dir):
            return results
        for topic_dir in sorted(os.listdir(base_dir)):
            sb_dir = os.path.join(base_dir, topic_dir, "storyboard")
            if not os.path.isdir(sb_dir):
                continue
            for fn in sorted(os.listdir(sb_dir)):
                if not fn.lower().endswith(".json"):
                    continue
                fp = os.path.join(sb_dir, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):  # noqa: E501
                        continue
                    results.append({
                        "name": os.path.splitext(fn)[0],
                        "path": fp,
                        "topic": data.get("topic", topic_dir),
                        "ratio": data.get("ratio", "9:16"),
                        "total_duration": data.get("total_duration", 0),
                        "shot_count": data.get("shot_count", len(data.get("shots", []))),  # noqa: E501
                        "shots": data.get("shots", []),
                        "saved_at": data.get("saved_at", 0),
                    })
                except (OSError, json.JSONDecodeError) as e:
                    logger.warning("读取脚本失败 %s: %s", fp, e)
    except OSError as e:
        logger.warning("扫描脚本失败: %s", e)
    return results
