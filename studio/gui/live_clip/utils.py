import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from utils.ffmpeg_utils import (
    find_ffmpeg,
    get_video_fps,
    get_video_resolution,
    run as ffmpeg_run,
)
from utils.gui_icons import mdi_icon, std_icon
from utils.hwaccel import get_video_encode_args

HOT_KEYWORDS_CN = [
    "重点", "关键", "核心", "重要", "注意", "记住", "一定要", "必须",
    "首先", "然后", "最后", "总结", "结论", "建议", "推荐",
    "技巧", "方法", "步骤", "教程", "演示", "实战", "案例",
    "干货", "福利", "优惠", "限时", "免费", "独家",
    "数据", "算法", "模型", "AI", "人工智能", "深度学习",
    "赚钱", "流量", "变现", "涨粉", "运营",
]


def _set_button_icon(btn, name):
    icon = std_icon(name)
    if icon.isNull():
        icon = mdi_icon(name)
    btn.setIcon(icon)


def resize_and_pad_with_blur(img, target_size):
    tw, th = target_size
    sw, sh = img.size

    bg = img.resize((tw, th), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=20))

    ratio = min(tw / sw, th / sh)
    nw = int(sw * ratio)
    nh = int(sh * ratio)
    fg = img.resize((nw, nh), Image.Resampling.LANCZOS)

    x = (tw - nw) // 2
    y = (th - nh) // 2
    bg.paste(fg, (x, y))
    return bg


def slice_srt(original_srt_path, start_sec, end_sec, out_srt_path):
    if not os.path.exists(original_srt_path):
        return False
    try:
        with open(original_srt_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        blocks = re.split(r'\n\s*\n', content.strip())
        new_blocks = []
        idx = 1
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            ts_line = lines[1]
            text = "\n".join(lines[2:])
            match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})", ts_line)
            if match:
                sh, sm, ss, sms = map(int, match.groups()[:4])
                eh, em, es, ems = map(int, match.groups()[4:])

                t_start = sh * 3600 + sm * 60 + ss + sms / 1000.0
                t_end = eh * 3600 + em * 60 + es + ems / 1000.0

                if t_end > start_sec and t_start < end_sec:
                    new_start = max(0.0, t_start - start_sec)
                    new_end = min(end_sec - start_sec, t_end - start_sec)

                    if new_end > new_start:
                        def format_ts(t):
                            h = int(t // 3600)
                            m = int((t % 3600) // 60)
                            s = int(t % 60)
                            ms = int(round((t - int(t)) * 1000))
                            if ms >= 1000:
                                s += 1
                                ms -= 1000
                            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

                        new_ts_line = f"{format_ts(new_start)} --> {format_ts(new_end)}"
                        new_blocks.append(f"{idx}\n{new_ts_line}\n{text}")
                        idx += 1

        with open(out_srt_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(new_blocks) + "\n")
        return True
    except OSError as e:
        print(f"Error slicing SRT: {e}")
        return False


def generate_cover_image(frame_path, title, out_path, size=(1280, 720)):
    img = Image.open(frame_path).convert("RGB")
    img = resize_and_pad_with_blur(img, size)
    draw = ImageDraw.Draw(img)

    if size[0] < size[1]:
        bar_h = 180
        font_size = 52
        line_width = 4
    else:
        bar_h = 130
        font_size = 56
        line_width = 4

    overlay = Image.new("RGBA", (size[0], bar_h), (0, 0, 0, 180))
    img.paste(overlay, (0, size[1] - bar_h), overlay)

    draw.rectangle([0, size[1] - bar_h, size[0], size[1] - bar_h + line_width], fill=(59, 130, 246))

    font = None
    for fn in ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
               "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
        if os.path.exists(fn):
            try:
                font = ImageFont.truetype(fn, font_size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), title, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size[0] - tw) // 2
    ty = size[1] - bar_h + (bar_h - th) // 2

    draw.text((tx + 2, ty + 2), title, font=font, fill=(0, 0, 0, 100))
    draw.text((tx, ty), title, font=font, fill=(255, 255, 255))

    img.save(out_path, quality=95)


def embed_cover_to_video(cover_path, video_path, out_path, cover_duration=2):
    ffmpeg = find_ffmpeg()

    w, h = get_video_resolution(video_path)
    fps = get_video_fps(video_path)

    selected_cover = cover_path
    if w < h:
        vertical_path = cover_path.replace("cover_", "cover_vertical_")
        if os.path.exists(vertical_path):
            selected_cover = vertical_path

    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-i", selected_cover,
        "-i", video_path,
        "-filter_complex",
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
        f"trim=duration={cover_duration},fps={fps},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v0];"
        f"[1:v]fps={fps},format=yuv420p[v1];"
        f"[v0][v1]concat=n=2:v=1:a=0[v];"
        f"[1:a]adelay={cover_duration*1000}:all=1[a]",
        "-map", "[v]", "-map", "[a]",
        *get_video_encode_args(crf=23, preset="fast"),
        "-c:a", "aac", "-shortest",
        out_path,
    ]
    r = ffmpeg_run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"封面嵌入失败:\n{r.stderr}")