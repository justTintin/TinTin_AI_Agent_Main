# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import traceback
import sys
import json
import re
import tempfile
import time
from collections import Counter

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QTextEdit,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                               QWidget, QStackedWidget, QScrollArea, QGridLayout, QSlider, QDialog)
from PySide6.QtCore import Signal, QThread, Qt, QUrl, QTimer
from utils.base_worker import BaseWorker
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QFont, QPixmap, QImage, QDesktopServices
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from utils.gui_icons import mdi_button, mdi_icon
from utils.logger_utils import log
from config.paths import OUTPUTS_DIR, TMP_DIR


HOT_KEYWORDS_CN = [
    "重点", "关键", "核心", "重要", "注意", "记住", "一定要", "必须",
    "首先", "然后", "最后", "总结", "结论", "建议", "推荐",
    "技巧", "方法", "步骤", "教程", "演示", "实战", "案例",
    "干货", "福利", "优惠", "限时", "免费", "独家",
    "数据", "算法", "模型", "AI", "人工智能", "深度学习",
    "赚钱", "流量", "变现", "涨粉", "运营",
]


def _startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def _ffmpeg():
    from utils.platform_utils import find_ffmpeg, binary_name
    p = find_ffmpeg()
    if not p or p == binary_name("ffmpeg"):
        p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError("未检测到 ffmpeg，请安装 ffmpeg 或将其加入环境变量 PATH")
    return p


def extract_audio_streaming(video_path, audio_path):
    """用 ffmpeg 提取音频，yield 进度秒数。"""
    ffmpeg = _ffmpeg()
    cmd = [ffmpeg, "-y", "-threads", "0", "-i", video_path, "-vn",
           "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
           "-progress", "pipe:1", "-nostats", audio_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=0, startupinfo=_startupinfo())
    for line in iter(proc.stdout.readline, b""):
        if line.startswith(b"out_time_ms="):
            try:
                yield int(line.split(b"=")[1]) / 1_000_000
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("音频提取失败")


def extract_frame(video_path, out_image, time_sec=1.0):
    cmd = [_ffmpeg(), "-y", "-ss", str(time_sec), "-i", video_path,
           "-vframes", "1", "-q:v", "2", out_image]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                       startupinfo=_startupinfo())
    if r.returncode != 0 or not os.path.exists(out_image):
        raise RuntimeError(f"提取帧失败:\n{r.stderr}")


def resize_and_pad_with_blur(img, target_size):
    tw, th = target_size
    sw, sh = img.size
    
    # 1. Create blurred background (resize source to stretch over target, then apply strong blur)
    bg = img.resize((tw, th), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=20))
    
    # 2. Resize source preserving aspect ratio to fit inside target_size
    ratio = min(tw / sw, th / sh)
    nw = int(sw * ratio)
    nh = int(sh * ratio)
    fg = img.resize((nw, nh), Image.Resampling.LANCZOS)
    
    # 3. Paste the fg directly in the center of bg
    x = (tw - nw) // 2
    y = (th - nh) // 2
    bg.paste(fg, (x, y))
    return bg


def get_video_resolution(video_path):
    cmd = [_ffmpeg(), "-i", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", startupinfo=_startupinfo())
    out = r.stderr or ""
    match = re.search(r",\s*(\d{2,5})x(\d{2,5})\b", out)
    if match:
        w = int(match.group(1))
        h = int(match.group(2))
        return w, h
    return 1280, 720


def get_video_fps(video_path):
    cmd = [_ffmpeg(), "-i", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", startupinfo=_startupinfo())
    out = r.stderr or ""
    fps = 30.0
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*fps\b", out)
    if match:
        try:
            fps = float(match.group(1))
        except ValueError:
            pass
    if fps <= 0 or fps > 120:
        fps = 30.0
    return fps


def slice_srt(original_srt_path, start_sec, end_sec, out_srt_path):
    if not os.path.exists(original_srt_path):
        return False
    try:
        with open(original_srt_path, "r", encoding="utf-8", errors="ignore") as f:
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
    except Exception as e:
        print(f"Error slicing SRT: {e}")
        return False


def generate_cover_image(frame_path, title, out_path, size=(1280, 720)):
    img = Image.open(frame_path).convert("RGB")
    # Apply aspect ratio blur padding instead of raw resizing to avoid compression
    img = resize_and_pad_with_blur(img, size)
    draw = ImageDraw.Draw(img)

    if size[0] < size[1]: # Vertical
        bar_h = 180
        font_size = 52
        line_width = 4
    else: # Horizontal
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
    ffmpeg = _ffmpeg()
    
    # 1. Detect resolution and fps dynamically
    w, h = get_video_resolution(video_path)
    fps = get_video_fps(video_path)
    
    # 2. Select appropriate cover (use vertical cover if portrait video)
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
        f"[1:v]fps={fps}[v1];"
        f"[v0][v1]concat=n=2:v=1:a=0[v];"
        f"[1:a]adelay={cover_duration*1000}:all=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-shortest",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                       startupinfo=_startupinfo())
    if r.returncode != 0:
        raise RuntimeError(f"封面嵌入失败:\n{r.stderr}")


# ==================== Workers ====================

class AudioExtractWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, video_path, audio_path):
        super().__init__()
        self.video_path = video_path
        self.audio_path = audio_path

    def run(self):
        try:
            self.stage.emit("正在流式提取音频...")
            last = -1
            for sec in extract_audio_streaming(self.video_path, self.audio_path):
                if self.isInterruptionRequested():
                    return
                pct = min(99, int(sec / 10 if sec < 1000 else sec / 60))
                if pct > last:
                    self.progress.emit(pct)
                    last = pct
            if self.isInterruptionRequested():
                return
            self.progress.emit(100)
            self.finished.emit(self.audio_path)
        except Exception:
            self.error.emit(traceback.format_exc())


class HotSpotAnalyzer(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, segments, use_llm=False, llm_url="", llm_key="", llm_model=""):
        super().__init__()
        self.segments = [s for s in segments if hasattr(s, 'start') and hasattr(s, 'text')]
        self.use_llm = use_llm
        self.llm_url = llm_url
        self.llm_key = llm_key
        self.llm_model = llm_model

    def run(self):
        try:
            if self.use_llm and self.llm_url and self.llm_key:
                self._llm_analyze()
            else:
                self._rule_analyze()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _rule_analyze(self):
        self.stage.emit("正在使用内置算法分析热点片段...")
        self.progress.emit(10)
        windows = []
        win, step = 60, 30
        total_dur = self.segments[-1].end if self.segments else 0
        for t0 in range(0, int(total_dur) + 1, step):
            t1 = t0 + win
            wsegs = [s for s in self.segments if s.start < t1 and s.end > t0]
            if not wsegs:
                continue
            text = " ".join(s.text.strip() for s in wsegs)
            words = list(re.findall(r"[\u4e00-\u9fff\w]+", text))
            if len(words) < 10:
                continue
            kw_hits = sum(1 for w in words if w in HOT_KEYWORDS_CN)
            density = len(words) / win
            unique = len(set(words)) / max(1, len(words))
            digits = sum(1 for c in text if c.isdigit())
            score = kw_hits * 3.0 + density * 10.0 + unique * 15.0 + min(digits, 20) * 0.3
            windows.append({"start": t0, "end": t1, "score": score, "text": text, "words": words})
        self.progress.emit(40)
        if not windows:
            self.finished.emit([])
            return
        scores = [w["score"] for w in windows]
        threshold = sum(scores) / len(scores) * 1.3
        peaks = [w for w in windows if w["score"] >= threshold]
        self.progress.emit(60)
        merged = []
        for p in sorted(peaks, key=lambda x: x["start"]):
            if merged and p["start"] - merged[-1]["end"] < 20:
                merged[-1]["end"] = max(merged[-1]["end"], p["end"])
                merged[-1]["score"] = max(merged[-1]["score"], p["score"])
                merged[-1]["text"] += " " + p["text"]
                merged[-1]["words"].extend(p["words"])
            else:
                merged.append(p)
        results = []
        for m in merged:
            dur = m["end"] - m["start"]
            if dur < 15 or dur > 300:
                if dur > 300:
                    m["end"] = m["start"] + 300
                else:
                    continue
            word_freq = Counter(m["words"])
            hot = [w for w in word_freq if w in HOT_KEYWORDS_CN]
            reg = [(w, c) for w, c in word_freq.most_common(20) if len(w) >= 2 and w not in HOT_KEYWORDS_CN]
            top = hot[:3] + [w for w, _ in reg[:5]]
            title = " | ".join(top[:5]) if top else "精彩片段"
            results.append({
                "start": m["start"], "end": m["end"],
                "start_str": f"{int(m['start']//60):02d}:{int(m['start']%60):02d}",
                "end_str": f"{int(m['end']//60):02d}:{int(m['end']%60):02d}",
                "duration": int(dur), "score": round(m["score"], 1),
                "title": title, "preview": m["text"][:120].replace("\n", " "),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        self.progress.emit(100)
        self.finished.emit(results)

    def _llm_analyze(self):
        self.stage.emit("正在使用大模型(DeepSeek/OpenAI)分析热点...")
        self.progress.emit(10)
        import requests
        full = []
        for s in self.segments:
            ts = f"[{int(s.start//60):02d}:{int(s.start%60):02d}]"
            full.append(f"{ts} {s.text.strip()}")
            
        # Group lines to avoid splitting them and add overlapping context (5 lines)
        chunks = []
        current_chunk = []
        current_len = 0
        overlap_lines = []
        for line in full:
            if not current_chunk and overlap_lines:
                current_chunk.extend(overlap_lines)
                current_len = sum(len(l) + 1 for l in overlap_lines)
            current_chunk.append(line)
            current_len += len(line) + 1
            if current_len >= 4000:
                chunks.append("\n".join(current_chunk))
                overlap_lines = current_chunk[-5:] if len(current_chunk) >= 5 else current_chunk[:]
                current_chunk = []
                current_len = 0
        if current_chunk:
            chunks.append("\n".join(current_chunk))
            
        all_results = []
        for ci, chunk in enumerate(chunks):
            self.stage.emit(f"正在使用大模型分析第 {ci+1}/{len(chunks)} 段字幕...")
            self.progress.emit(10 + int(ci / max(1, len(chunks)) * 70))
            prompt = (
                "你是专业的直播视频内容分析师。请仔细阅读以下直播字幕文本，并从中找出最具传播价值和吸引力的热点片段。\n\n"
                "【分析与剪裁规则】：\n"
                "1. **保持话题完整连贯（核心要求）**：如果主播在连续讨论同一个话题或主题，请务必将其归为一个完整的片段，不要将其切碎为多个零碎、不连贯的小片段。片段时长一般控制在30秒到5分钟之间。如果一个话题较长（如3-5分钟），只要逻辑连贯，请输出为一个完整片段。\n"
                "2. **语义停顿**：确保片段的开始时间（start）和结束时间（end）定位在语句的自然停顿处，避免截断一句话。\n"
                "3. **时间戳格式**：必须严格使用待分析文本中对应的 `分:秒`（如 `12:34`）格式。如果分钟数超过60，也请按照 `分钟数:秒` 格式输出（例如 `75:20`），不要转换为 `时:分:秒`。\n"
                "4. **评分打分**：根据内容的精彩程度、信息干货密度 and 传播价值，给每个片段打分（0-10分）。\n"
                "5. **片段标题**：为片段起一个能够高度概括主题、有吸引力且不超过15个字的简短标题。\n\n"
                "【输出格式要求】：\n"
                "请仅返回一个标准的 JSON 数组格式，不要包含任何 Markdown 格式标记（如 ```json）或任何额外的解释性文字。格式示例如下：\n"
                "[{\"start\": \"mm:ss\", \"end\": \"mm:ss\", \"title\": \"片段标题\", \"score\": 8.5}]\n\n"
                "【待分析字幕文本】：\n" + chunk
            )
            try:
                resp = requests.post(
                    f"{self.llm_url.rstrip('/')}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.llm_key}", "Content-Type": "application/json"},
                    json={"model": self.llm_model, "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.3, "max_tokens": 2000}, timeout=120)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    m = re.search(r"\[[\s\S]*\]", content)
                    if m:
                        for item in json.loads(m.group()):
                            sp = item["start"].split(":"); ep = item["end"].split(":")
                            item["start"] = int(sp[0]) * 60 + int(sp[1])
                            item["end"] = int(ep[0]) * 60 + int(ep[1])
                            item["duration"] = item["end"] - item["start"]
                            item["start_str"] = item.get("start_str", item.get("start", ""))
                            item["end_str"] = item.get("end_str", item.get("end", ""))
                            item["preview"] = ""
                            item["score"] = item.get("score", 5.0)
                            all_results.append(item)
            except Exception as e:
                log.warning(f"LLM chunk {ci} error: {e}")
                
        # Post-process: merge overlapping or adjacent LLM hotspots (gap <= 15s)
        merged_results = []
        all_results.sort(key=lambda x: x["start"])
        for item in all_results:
            if not merged_results:
                merged_results.append(item)
            else:
                prev = merged_results[-1]
                if item["start"] <= prev["end"] + 15:
                    new_end = max(prev["end"], item["end"])
                    if new_end - prev["start"] <= 300: # Limit to 5 mins max
                        prev["end"] = new_end
                        prev["duration"] = prev["end"] - prev["start"]
                        prev["score"] = max(prev["score"], item["score"])
                        if item["title"] and item["title"] != prev["title"]:
                            prev["title"] = f"{prev['title']}/{item['title']}"[:25]
                    else:
                        merged_results.append(item)
                else:
                    merged_results.append(item)
                    
        for item in merged_results:
            item["start_str"] = f"{int(item['start']//60):02d}:{int(item['start']%60):02d}"
            item["end_str"] = f"{int(item['end']//60):02d}:{int(item['end']%60):02d}"
            
        merged_results.sort(key=lambda x: x["score"], reverse=True)
        self.progress.emit(100)
        self.finished.emit(merged_results)


class VideoClipWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, video_path, clips, output_dir, srt_path=""):
        super().__init__()
        self.video_path = video_path
        self.clips = clips
        self.output_dir = output_dir
        self.srt_path = srt_path

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            results = []
            total = len(self.clips)
            for i, clip in enumerate(self.clips):
                title = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", clip.get("title", "clip"))[:30]
                out = os.path.join(self.output_dir, f"clip_{i+1:03d}_{title}.mp4")
                self.stage.emit(f"正在剪辑第 {i+1}/{total} 个片段: {title}...")
                
                start_sec = clip["start"]
                end_sec = clip["end"]
                duration = max(0.1, end_sec - start_sec)
                
                # Combine fast seek (before -i) and accurate seek (after -i)
                fast_start = max(0, start_sec - 30)
                remain_start = start_sec - fast_start
                
                # Check for burning subtitles
                burn = clip.get("burn_subtitles", False)
                temp_srt = None
                cwd_dir = None
                vf_args = []
                
                if burn and self.srt_path and os.path.exists(self.srt_path):
                    temp_srt = out.replace(".mp4", "_temp_sub.srt")
                    success = slice_srt(self.srt_path, start_sec, end_sec, temp_srt)
                    if success and os.path.exists(temp_srt) and os.path.getsize(temp_srt) > 0:
                        cwd_dir = os.path.dirname(temp_srt)
                        rel_srt = os.path.basename(temp_srt)
                        vf_args = ["-vf", f"subtitles={rel_srt}"]
                    else:
                        temp_srt = None
                
                abs_video = os.path.abspath(self.video_path)
                abs_out = os.path.abspath(out)
                
                cmd = [_ffmpeg(), "-y",
                       "-ss", f"{fast_start:.3f}",
                       "-i", abs_video,
                       "-ss", f"{remain_start:.3f}",
                       "-t", f"{duration:.3f}"] + vf_args + [
                       "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                       "-c:a", "aac", abs_out]
                       
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="ignore", startupinfo=_startupinfo(), cwd=cwd_dir)
                                   
                if temp_srt and os.path.exists(temp_srt):
                    try:
                        os.remove(temp_srt)
                    except Exception:
                        pass
                        
                if os.path.exists(out) and os.path.getsize(out) > 0:
                    results.append({
                        "path": out,
                        "title": clip.get("title", ""),
                        "index": clip.get("index", i),
                        "start": clip.get("start", 0),
                        "end": clip.get("end", 0),
                        "start_str": clip.get("start_str", ""),
                        "end_str": clip.get("end_str", ""),
                        "duration": clip.get("duration", 0),
                        "score": clip.get("score", 0),
                    })
                self.progress.emit(int((i + 1) / total * 90))
            self.stage.emit(f"剪辑完成: {len(results)}/{total}")
            self.progress.emit(90)
            self.finished.emit(results)
        except Exception:
            self.error.emit(traceback.format_exc())


class CoverGeneratorWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    cover_ready = Signal(int, str)
    finished = Signal(list)

    def __init__(self, clips_info, output_dir):
        super().__init__()
        self.clips_info = clips_info
        self.output_dir = output_dir

    def run(self):
        try:
            covers_dir = os.path.join(self.output_dir, "covers")
            os.makedirs(covers_dir, exist_ok=True)
            results = []
            total = len(self.clips_info)
            for i, ci in enumerate(self.clips_info):
                self.stage.emit(f"正在提取并生成第 {i+1}/{total} 个片段的封面: {ci['title'][:20]}...")
                self.progress.emit(int(i / total * 100))
                frame_path = os.path.join(covers_dir, f"frame_{i+1:03d}.jpg")
                cover_path = os.path.join(covers_dir, f"cover_{i+1:03d}.jpg")
                cover_vertical_path = os.path.join(covers_dir, f"cover_vertical_{i+1:03d}.jpg")
                extract_frame(ci["path"], frame_path, time_sec=1.0)
                generate_cover_image(frame_path, ci["title"], cover_path, size=(1280, 720))
                generate_cover_image(frame_path, ci["title"], cover_vertical_path, size=(720, 1280))
                results.append({
                    "cover_path": cover_path,
                    "cover_vertical_path": cover_vertical_path,
                    "frame_path": frame_path,
                    "video_path": ci["path"],
                    "title": ci["title"],
                    "index": i,
                    "start": ci.get("start", 0),
                    "end": ci.get("end", 0),
                    "start_str": ci.get("start_str", ""),
                    "end_str": ci.get("end_str", ""),
                    "duration": ci.get("duration", 0),
                    "score": ci.get("score", 0),
                })
                self.cover_ready.emit(i, cover_path)
            self.finished.emit(results)
        except Exception:
            self.error.emit(traceback.format_exc())


class FinalExportWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, covers_info, output_dir):
        super().__init__()
        self.covers_info = covers_info
        self.output_dir = output_dir

    def run(self):
        try:
            final_dir = os.path.join(self.output_dir, "final")
            os.makedirs(final_dir, exist_ok=True)
            results = []
            total = len(self.covers_info)
            for i, ci in enumerate(self.covers_info):
                title = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", ci["title"])[:30]
                out = os.path.join(final_dir, f"done_{i+1:03d}_{title}.mp4")
                self.stage.emit(f"正在合并并导出第 {i+1}/{total} 个视频: {ci['title'][:20]}...")
                embed_cover_to_video(ci["cover_path"], ci["video_path"], out)
                results.append(out)
                self.progress.emit(int((i + 1) / total * 100))
            self.finished.emit(results)
        except Exception:
            self.error.emit(traceback.format_exc())


# ==================== Audio Player Widget ====================

class AudioPlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        self.btn_play = mdi_button("播放", "play")
        self.btn_play.setFixedWidth(70)
        self.btn_play.setObjectName("secondary_button")
        self.btn_play.clicked.connect(self.toggle_play)
        layout.addWidget(self.btn_play)
        
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(100)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_time)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #2e2e32;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)
        layout.addWidget(self.slider)
        
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        
        self.audio_path = None
        self.setEnabled(False)
        
    def set_audio_path(self, audio_path):
        if not audio_path or not os.path.exists(audio_path):
            self.setEnabled(False)
            return
        self.audio_path = audio_path
        self.player.setSource(QUrl.fromLocalFile(audio_path))
        self.setEnabled(True)
        self.btn_play.setText("播放")
        self.lbl_time.setText("00:00 / 00:00")
        self.slider.setValue(0)
        
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放")
        else:
            self.player.play()
            self.btn_play.setText("暂停")
            
    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())
        
    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)
        
    def set_position(self, position):
        self.player.setPosition(position)
        
    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000
        
        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60
        
        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60
        
        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")


# ==================== Helper Widgets ====================

# ==================== Helper Widgets ====================

class CoverEditDialog(QDialog):
    def __init__(self, video_path, title, frame_path, cover_path, cover_vertical_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑视频封面")
        self.resize(1100, 650)
        self.setModal(True)
        self.setObjectName("cover_edit_dialog")
       
        self.video_path = video_path
        self.original_title = title
        self.original_frame_path = frame_path
        self.original_cover_path = cover_path
        self.original_cover_vertical_path = cover_vertical_path or cover_path.replace("cover_", "cover_vertical_")
        
        self.temp_dir = tempfile.mkdtemp()
        self.temp_frame_path = os.path.join(self.temp_dir, "temp_frame.jpg")
        self.temp_cover_path = os.path.join(self.temp_dir, "temp_cover.jpg")
        self.temp_cover_vertical_path = os.path.join(self.temp_dir, "temp_cover_vertical.jpg")
        
        if os.path.exists(frame_path):
            shutil.copy(frame_path, self.temp_frame_path)
        if os.path.exists(cover_path):
            shutil.copy(cover_path, self.temp_cover_path)
        if os.path.exists(self.original_cover_vertical_path):
            shutil.copy(self.original_cover_vertical_path, self.temp_cover_vertical_path)
            
        self.current_title = title
        self.saved = False
        
        # Throttled seek variables to support drag frame-by-frame mode
        self.last_seek_time = 0
        self.pending_seek_pos = None
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.timeout.connect(self._do_throttled_seek)
        
        self.init_ui()
        
    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(20)
        
        # COLUMN 1: Video area (1/3 width)
        col1_widget = QWidget()
        col1_layout = QVBoxLayout(col1_widget)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        col1_layout.setSpacing(10)
        
        player_title = QLabel("<b>🎥 视频截取区域 (拖动滑块定帧)</b>")
        player_title.setObjectName("cover_section_title")
        col1_layout.addWidget(player_title)
        
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("cover_video_widget")
        col1_layout.addWidget(self.video_widget, 1)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        # Larger drag handle for precise frame adjustment/scrubbing
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px;
                background: #27272a;
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 3px solid #3b82f6;
                width: 22px;
                height: 22px;
                margin-top: -7px;
                margin-bottom: -7px;
                border-radius: 11px;
            }
            QSlider::handle:horizontal:hover {
                background: #3b82f6;
                border: 3px solid #ffffff;
            }
        """)
        col1_layout.addWidget(self.slider)
        
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(10)
        
        self.btn_play = mdi_button("播放", "play")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        self.btn_play.setFixedWidth(80)
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.btn_play)
        
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(100)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setObjectName("cover_time_label")
        ctrl_layout.addWidget(self.lbl_time)
        
        ctrl_layout.addStretch()
        
        self.btn_capture = mdi_button("选择当前帧为封面", "camera")
        self.btn_capture.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_capture.clicked.connect(self.capture_current_frame)
        ctrl_layout.addWidget(self.btn_capture)
        
        col1_layout.addLayout(ctrl_layout)
        main_layout.addWidget(col1_widget, 1) # Weight 1 (1/3 of layout width)
        
        # COLUMN 2: Horizontal Cover Preview (1/3 width)
        col2_widget = QWidget()
        col2_layout = QVBoxLayout(col2_widget)
        col2_layout.setContentsMargins(0, 0, 0, 0)
        col2_layout.setSpacing(12)
        col2_layout.setAlignment(Qt.AlignTop)
        
        h_cover_title = QLabel("<b>🖼️ 横屏封面预览 (16:9)</b>")
        h_cover_title.setObjectName("cover_section_title")
        col2_layout.addWidget(h_cover_title)
        
        self.lbl_cover_preview_h = QLabel()
        self.lbl_cover_preview_h.setFixedSize(320, 180) # Large horizontal preview
        self.lbl_cover_preview_h.setObjectName("cover_preview_h")
        self.lbl_cover_preview_h.setAlignment(Qt.AlignCenter)
        col2_layout.addWidget(self.lbl_cover_preview_h, 0, Qt.AlignCenter)
        
        if os.path.exists(self.temp_cover_path):
            pix_h = QPixmap(self.temp_cover_path)
            self.lbl_cover_preview_h.setPixmap(pix_h.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_cover_preview_h.setText("暂无横屏封面，请在左侧截图")
            
        col2_layout.addSpacing(10)
        col2_layout.addWidget(QLabel("封面标题 (不超过10个字):"))
        self.title_input = QLineEdit(self.current_title)
        self.title_input.setMaxLength(10)
        self.title_input.setPlaceholderText("请输入标题文案...")
        self.title_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 4px;
                padding: 6px;
                color: #f8fafc;
                font-size: 13px;
            }
        """)
        self.title_input.textChanged.connect(self.on_title_changed)
        col2_layout.addWidget(self.title_input)
        
        main_layout.addWidget(col2_widget, 1) # Weight 1 (1/3 of layout width)
        
        # COLUMN 3: Vertical Cover Preview (1/3 width)
        col3_widget = QWidget()
        col3_layout = QVBoxLayout(col3_widget)
        col3_layout.setContentsMargins(0, 0, 0, 0)
        col3_layout.setSpacing(12)
        col3_layout.setAlignment(Qt.AlignTop)
        
        v_cover_title = QLabel("<b>📱 竖屏封面预览 (9:16)</b>")
        v_cover_title.setObjectName("cover_section_title")
        col3_layout.addWidget(v_cover_title)
        
        self.lbl_cover_preview_v = QLabel()
        self.lbl_cover_preview_v.setFixedSize(180, 320) # Large vertical preview
        self.lbl_cover_preview_v.setObjectName("cover_preview_v")
        self.lbl_cover_preview_v.setAlignment(Qt.AlignCenter)
        col3_layout.addWidget(self.lbl_cover_preview_v, 0, Qt.AlignCenter)
        
        if os.path.exists(self.temp_cover_vertical_path):
            pix_v = QPixmap(self.temp_cover_vertical_path)
            self.lbl_cover_preview_v.setPixmap(pix_v.scaled(180, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_cover_preview_v.setText("暂无竖屏封面，请在左侧截图")
            
        col3_layout.addSpacing(10)
        
        actions_layout = QHBoxLayout()
        self.btn_save = QPushButton("确定保存")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        
        actions_layout.addWidget(self.btn_save)
        actions_layout.addWidget(self.btn_cancel)
        col3_layout.addLayout(actions_layout)
        
        main_layout.addWidget(col3_widget, 1) # Weight 1 (1/3 of layout width)
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderMoved.connect(self.set_position)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        
        self.player.setSource(QUrl.fromLocalFile(self.video_path))
        self.player.play()
        
    def on_slider_pressed(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放")
        
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放")
        else:
            self.player.play()
            self.btn_play.setText("暂停")
            
    def set_position(self, position):
        self.pending_seek_pos = position
        now = time.time()
        if now - self.last_seek_time > 0.05:
            self._do_throttled_seek()
        else:
            if not self.seek_timer.isActive():
                self.seek_timer.start(30)
                
    def _do_throttled_seek(self):
        if self.pending_seek_pos is not None:
            self.player.setPosition(self.pending_seek_pos)
            self.last_seek_time = time.time()
            self.pending_seek_pos = None
            
    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())
        
    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)
        
    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000
        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60
        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60
        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")
        
    def capture_current_frame(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放")
            
        time_sec = self.player.position() / 1000.0
        self.btn_capture.setEnabled(False)
        self.btn_capture.setText("正在截取中...")
        self.btn_capture.repaint()
        
        try:
            extract_frame(self.video_path, self.temp_frame_path, time_sec=time_sec)
            self.regenerate_cover()
        except Exception as e:
            QMessageBox.warning(self, "截图失败", f"无法捕获当前帧:\n{str(e)}")
        finally:
            self.btn_capture.setEnabled(True)
            self.btn_capture.setText("选择当前帧为封面")
            
    def on_title_changed(self, text):
        self.current_title = text.strip()
        self.regenerate_cover()
        
    def regenerate_cover(self):
        if not os.path.exists(self.temp_frame_path):
            return
        try:
            generate_cover_image(self.temp_frame_path, self.current_title, self.temp_cover_path, size=(1280, 720))
            generate_cover_image(self.temp_frame_path, self.current_title, self.temp_cover_vertical_path, size=(720, 1280))
            
            pix_h = QPixmap(self.temp_cover_path)
            self.lbl_cover_preview_h.setPixmap(pix_h.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            
            pix_v = QPixmap(self.temp_cover_vertical_path)
            self.lbl_cover_preview_v.setPixmap(pix_v.scaled(180, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            log.exception("生成临时封面失败")
            
    def save_and_close(self):
        try:
            if not os.path.exists(self.temp_frame_path):
                QMessageBox.warning(self, "提示", "请先截取一帧画面作为封面背景")
                return
            shutil.copy(self.temp_frame_path, self.original_frame_path)
            shutil.copy(self.temp_cover_path, self.original_cover_path)
            shutil.copy(self.temp_cover_vertical_path, self.original_cover_vertical_path)
            self.saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存封面修改:\n{str(e)}")
            
    def closeEvent(self, event):
        self.player.stop()
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)



class ClipListItemWidget(QFrame):
    def __init__(self, clip_info, index, main_page, parent=None):
        super().__init__(parent)
        self.clip_info = clip_info
        self.clip_index = index
        self.main_page = main_page
        self.selected = False
        
        self.setObjectName("clip_list_item")
        self.setFrameShape(QFrame.StyledPanel)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        top_layout = QHBoxLayout()
        self.lbl_title = QLabel(f"<b>{self.clip_info.get('title', '精彩片段')}</b>")
        self.lbl_title.setObjectName("clip_list_item_title")
        self.lbl_title.setWordWrap(True)
        top_layout.addWidget(self.lbl_title, 1)
        
        score = self.clip_info.get('score', 0.0)
        self.lbl_score = QLabel(f"⭐ {score}")
        self.lbl_score.setObjectName("clip_list_item_score")
        top_layout.addWidget(self.lbl_score)
        layout.addLayout(top_layout)
        
        meta_layout = QHBoxLayout()
        meta_text = f"⏱ {self.clip_info.get('start_str', '00:00')} - {self.clip_info.get('end_str', '00:00')} ({self.clip_info.get('duration', 0)}s)"
        self.lbl_meta = QLabel(meta_text)
        self.lbl_meta.setObjectName("clip_list_item_meta")
        meta_layout.addWidget(self.lbl_meta, 1)
        
        from PySide6.QtWidgets import QCheckBox
        self.chk_subtitles = QCheckBox("加字幕")
        self.chk_subtitles.setStyleSheet("""
            QCheckBox {
                color: #94a3b8;
                font-size: 11px;
            }
        """)
        self.chk_subtitles.setChecked(False)
        meta_layout.addWidget(self.chk_subtitles)
        layout.addLayout(meta_layout)
        
        # Intermediate row: Slicing progress and individual slice button
        self.slice_layout = QHBoxLayout()
        self.slice_layout.setSpacing(8)
        
        self.pbar_slice = QProgressBar()
        self.pbar_slice.setRange(0, 100)
        self.pbar_slice.setValue(0)
        self.pbar_slice.setFixedHeight(10)
        self.pbar_slice.setVisible(False)
        self.pbar_slice.setStyleSheet("""
            QProgressBar {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 4px;
                text-align: center;
                color: #ffffff;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 3px;
            }
        """)
        self.slice_layout.addWidget(self.pbar_slice, 1)
        
        self.btn_slice_single = mdi_button("单独切片", "cut")
        self.btn_slice_single.setStyleSheet("""
            QPushButton {
                background-color: #d97706;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b45309;
            }
            QPushButton:disabled {
                background-color: #27272a;
                color: #71717a;
                border: 1px solid #27272a;
            }
        """)
        self.btn_slice_single.setFixedWidth(80)
        self.btn_slice_single.clicked.connect(self.start_individual_slice)
        self.slice_layout.addWidget(self.btn_slice_single)
        
        layout.addLayout(self.slice_layout)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setObjectName("clip_list_separator")
        layout.addWidget(sep)
        
        play_layout = QHBoxLayout()
        play_layout.setSpacing(6)
        
        self.btn_play = mdi_button("播放声音", "play")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
            QPushButton:disabled {
                color: #52525b;
                border-color: #27272a;
            }
        """)
        self.btn_play.setFixedWidth(80)
        self.btn_play.setEnabled(False)
        play_layout.addWidget(self.btn_play)
        
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setObjectName("clip_list_item_time")
        self.lbl_time.setFixedWidth(80)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        play_layout.addWidget(self.lbl_time)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #2e2e32;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #10b981;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 10px;
                height: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
        """)
        play_layout.addWidget(self.slider)
        
        self.btn_edit_cover = mdi_button("编辑封面", "palette")
        self.btn_edit_cover.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:disabled {
                background-color: #27272a;
                color: #52525b;
                border: 1px solid #27272a;
            }
        """)
        self.btn_edit_cover.setFixedWidth(80)
        self.btn_edit_cover.setEnabled(False)
        play_layout.addWidget(self.btn_edit_cover)
        
        layout.addLayout(play_layout)
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_edit_cover.clicked.connect(self.open_cover_editor)
        self.slider.sliderMoved.connect(self.set_position)
        
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        
        self.update_style()

    def mousePressEvent(self, event):
        self.main_page.select_clip_item(self.clip_index)
        super().mousePressEvent(event)
        
    def update_style(self):
        if self.selected:
            self.setStyleSheet("""
                QFrame#clip_list_item {
                    background-color: #1e293b;
                    border: 2px solid #3b82f6;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#clip_list_item {
                    background-color: #18181b;
                    border: 1px solid #2e2e32;
                    border-radius: 8px;
                }
                QFrame#clip_list_item:hover {
                    border: 1px solid #4b5563;
                }
            """)
            
    def set_selected(self, selected):
        self.selected = selected
        self.update_style()
        
    def enable_playback(self, video_path):
        self.clip_info["video_path"] = video_path
        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.btn_play.setEnabled(True)
        self.btn_edit_cover.setEnabled(True)
        self.slider.setEnabled(True)
        
        self.btn_slice_single.setText("已切片")
        self.btn_slice_single.setEnabled(False)
        self.pbar_slice.setVisible(False)
        
    def toggle_play(self):
        if not self.clip_info.get("video_path") or not os.path.exists(self.clip_info["video_path"]):
            return
            
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放声音")
        else:
            self.main_page.pause_all_players_except(self.clip_index)
            self.player.play()
            self.btn_play.setText("暂停")
            
    def pause_audio(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setText("播放声音")
            
    def open_cover_editor(self):
        video_path = self.clip_info.get("video_path")
        if not video_path or not os.path.exists(video_path):
            return
            
        self.pause_audio()
        self.main_page.pause_all_players_except(-1)
        
        cover_path = self.clip_info.get("cover_path", "")
        cover_vertical_path = self.clip_info.get("cover_vertical_path", "")
        if not cover_vertical_path and cover_path:
            cover_vertical_path = cover_path.replace("cover_", "cover_vertical_")
            
        dialog = CoverEditDialog(
            video_path=video_path,
            title=self.clip_info.get("title", ""),
            frame_path=self.clip_info.get("frame_path", ""),
            cover_path=cover_path,
            cover_vertical_path=cover_vertical_path,
            parent=self.main_page.parent_widget
        )
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.clip_info["title"] = dialog.current_title
            self.clip_info["cover_path"] = dialog.original_cover_path
            self.clip_info["cover_vertical_path"] = dialog.original_cover_vertical_path
            self.lbl_title.setText(f"<b>{dialog.current_title}</b>")
            self.main_page.on_clip_info_updated(
                self.clip_index, 
                dialog.current_title, 
                dialog.original_cover_path, 
                dialog.original_cover_vertical_path
            )

    def start_individual_slice(self):
        if not self.main_page.video_path or not os.path.exists(self.main_page.video_path):
            QMessageBox.warning(self.main_page.parent_widget, "错误", f"视频文件不存在，请重新选择视频文件。\n路径: {self.main_page.video_path or '未选择'}")
            return
            
        self.btn_slice_single.setEnabled(False)
        self.btn_slice_single.setText("正在切片...")
        self.pbar_slice.setValue(0)
        self.pbar_slice.setVisible(True)
        
        if not self.main_page.output_dir:
            vname = os.path.splitext(os.path.basename(self.main_page.video_path))[0]
            self.main_page.output_dir = os.path.join(OUTPUTS_DIR, "live_clips", vname)
            os.makedirs(self.main_page.output_dir, exist_ok=True)
            
        clip_data = dict(self.clip_info)
        clip_data["burn_subtitles"] = self.chk_subtitles.isChecked()
        clip_data["index"] = self.clip_index
        self.worker_clip = VideoClipWorker(
            self.main_page.video_path, [clip_data], self.main_page.output_dir,
            srt_path=getattr(self.main_page, "srt_path", "")
        )
        self.worker_clip.progress.connect(self.pbar_slice.setValue)
        self.worker_clip.finished.connect(self.on_individual_clip_done)
        self.worker_clip.error.connect(self.on_individual_slice_error)
        self.worker_clip.start()
        
    def on_individual_slice_error(self, err):
        self.btn_slice_single.setEnabled(True)
        self.btn_slice_single.setText("单独切片")
        self.pbar_slice.setVisible(False)
        QMessageBox.critical(self.main_page.parent_widget, "错误", f"单独切片失败:\n{err}")
        
    def on_individual_clip_done(self, results):
        if not results:
            self.on_individual_slice_error("没有生成切片视频")
            return
            
        video_path = results[0]["path"]
        self.clip_info["video_path"] = video_path
        self.btn_slice_single.setText("生成封面...")
        
        ci = {
            "path": video_path,
            "title": self.clip_info.get("title", ""),
            "index": self.clip_index,
            "start": self.clip_info.get("start", 0),
            "end": self.clip_info.get("end", 0),
            "start_str": self.clip_info.get("start_str", ""),
            "end_str": self.clip_info.get("end_str", ""),
            "duration": self.clip_info.get("duration", 0),
            "score": self.clip_info.get("score", 0),
        }
        
        self.worker_cover = CoverGeneratorWorker([ci], self.main_page.output_dir)
        self.worker_cover.finished.connect(self.on_individual_cover_done)
        self.worker_cover.error.connect(self.on_individual_slice_error)
        self.worker_cover.start()
        
    def on_individual_cover_done(self, covers_info):
        if not covers_info:
            self.on_individual_slice_error("没有生成封面")
            return
            
        ci = covers_info[0]
        self.clip_info["cover_path"] = ci["cover_path"]
        self.clip_info["cover_vertical_path"] = ci.get("cover_vertical_path", "")
        self.clip_info["frame_path"] = ci["frame_path"]
        self.clip_info["video_path"] = ci["video_path"]
        self.clip_info["title"] = ci["title"]
        
        self.enable_playback(ci["video_path"])
        self.main_page.update_covers_info_for_index(self.clip_index, ci)
        
        self.btn_slice_single.setText("已切片")
    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label(position, self.player.duration())
        
    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label(self.player.position(), duration)
        
    def set_position(self, position):
        self.player.setPosition(position)
        
    def update_time_label(self, position, duration):
        pos_sec = position // 1000
        dur_sec = duration // 1000
        pos_min = pos_sec // 60
        pos_sec = pos_sec % 60
        dur_min = dur_sec // 60
        dur_sec = dur_sec % 60
        self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")


# ==================== Page ====================

from gui.base_page import BasePage


class LiveClipPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self._stop_requested = False
        self.hotspots = []
        self.transcript_segments = []
        self.audio_path = ""
        self.clipped_results = []
        self.covers_info = []
        self.output_dir = ""
        self.video_path = ""
        self.srt_path = ""

        self.cover_images = {}
        self.cover_title_inputs = {}
        self.clip_item_widgets = []
        self.selected_clip_idx = -1

    def _get_step_font(self, active=False):
        font = QFont("Microsoft YaHei", 10)
        font.setBold(active)
        return font

    def _update_step_indicator(self, index):
        for i, lbl in enumerate(self.step_labels):
            if i == index:
                lbl.setFont(self._get_step_font(True))
                lbl.setProperty("status", "active")
            elif i < index:
                lbl.setFont(self._get_step_font(False))
                lbl.setProperty("status", "done")
            else:
                lbl.setFont(self._get_step_font(False))
                lbl.setProperty("status", "pending")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _go_to_step(self, index):
        self.pause_all_players_except(-1)
        if hasattr(self, "audio_player"):
            self.audio_player.player.pause()
            self.audio_player.btn_play.setText("播放")

        if index == 0:
            self.progress_bar = self.progress_bar_p0
            self.stage_lbl = self.stage_lbl_p0
        else:
            self.progress_bar = self.progress_bar_p1
            self.stage_lbl = self.stage_lbl_p1
            # Update selected count label for Step 2
            selected_count = sum(1 for i in range(self.hotspot_table.rowCount())
                                 if self.hotspot_table.item(i, 0) and self.hotspot_table.item(i, 0).checkState() == Qt.Checked)
            self.clip_status_lbl.setText(f"已选 {selected_count} 个片段待切片")
            self.btn_clip.setEnabled(selected_count > 0)
            self._init_clip_list()

        self.stacked.setCurrentIndex(index)
        self._update_step_indicator(index)
        self.stage_lbl.setText("就绪")
        self.progress_bar.setVisible(False)

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(16)

        heading = QLabel("\U0001F4E1 直播智能切片")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        # Step bar
        self.step_bar = QFrame()
        self.step_bar.setObjectName("step_bar")
        self.step_bar.setStyleSheet(
            "QFrame#step_bar { background-color: rgba(255,255,255,0.02); "
            "border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 16px; }")
        sl = QHBoxLayout(self.step_bar)
        self.step_labels = []
        for i, text in enumerate(["\U0001F4F9 视频分析与热点发现", "\u2702 切片与封面生成"]):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("export_step_label")
            lbl.setFont(self._get_step_font(i == 0))
            sl.addWidget(lbl)
            self.step_labels.append(lbl)
            layout.addWidget(self.step_bar, 0)
    
            # 初始化第一步为激活状态
            QTimer.singleShot(0, lambda: self._update_step_indicator(0))

        # Stacked widget
        self.stacked = QStackedWidget()
        layout.addWidget(self.stacked, 1)

        self._setup_page_analysis()
        self._setup_page_clip()

        # Set default references
        self.progress_bar = self.progress_bar_p0
        self.stage_lbl = self.stage_lbl_p0

    # ===== Page 0: Analysis =====
    def _setup_page_analysis(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setSpacing(10)
        cl.setContentsMargins(12, 10, 12, 10)

        # Row 1: Video selection in one line
        vr = QHBoxLayout()
        vr.addWidget(QLabel("<b>直播视频:</b>"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("选择直播录像（支持 40GB+，流式处理）...")
        vr.addWidget(self.video_path_input)
        btn = QPushButton("选择视频")
        btn.setObjectName("secondary_button")
        btn.clicked.connect(self._select_video)
        vr.addWidget(btn)
        
        self.video_info_lbl = QLabel("")
        self.video_info_lbl.setObjectName("video_info_label")
        vr.addWidget(self.video_info_lbl)
        cl.addLayout(vr)

        # Row 2: Audio player for seek and playback
        pr = QHBoxLayout()
        pr.addWidget(QLabel("音频预览:"))
        self.audio_player = AudioPlayerWidget()
        pr.addWidget(self.audio_player, 1)
        cl.addLayout(pr)

        # Row 3: Analysis method, transcription engine and Start button in one line
        ar = QHBoxLayout()
        ar.addWidget(QLabel("分析方法:"))
        self.analysis_mode = QComboBox()
        self.analysis_mode.addItem("🤖 AI 大模型 (DeepSeek/OpenAI)", "llm")
        self.analysis_mode.addItem("🧠 内置算法 (无需 API)", "rule")
        ar.addWidget(self.analysis_mode)

        # Transcribe Language Selection
        ar.addWidget(QLabel("转写语言:"))
        self.transcribe_lang = QComboBox()
        self.transcribe_lang.addItem("中文 (简体)", "zh")
        self.transcribe_lang.addItem("自动识别", "auto")
        self.transcribe_lang.addItem("英语", "en")
        self.transcribe_lang.setCurrentIndex(0)  # Default to Chinese
        ar.addWidget(self.transcribe_lang)

        self.chk_reextract = QCheckBox("强制重新提取音频")
        self.chk_reextract.setToolTip("勾选后每次重新用 ffmpeg 提取音频")
        ar.addWidget(self.chk_reextract)

        self.btn_analyze = mdi_button("开始提取并分析", "mic")
        self.btn_analyze.setObjectName("action_button")
        self.btn_analyze.setFixedHeight(30)
        self.btn_analyze.clicked.connect(self._start_analysis_pipeline)
        ar.addWidget(self.btn_analyze, 1)

        self.btn_stop = mdi_button("停止", "stop")
        self.btn_stop.setObjectName("secondary_button")
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_analysis)
        ar.addWidget(self.btn_stop)
        cl.addLayout(ar)

        layout.addWidget(card)

        # Lower section: Left (Subtitles) and Right (Hotspots) layout
        lower_layout = QHBoxLayout()
        lower_layout.setSpacing(12)

        # Left: Subtitle Preview
        sub_card = QFrame()
        sub_card.setObjectName("card")
        sub_vl = QVBoxLayout(sub_card)
        sub_vl.setSpacing(8)
        sub_vl.setContentsMargins(12, 10, 12, 10)
        sub_vl.addWidget(QLabel("<b>📝 字幕预览</b>"))
        
        self.transcript_preview = QTextEdit()
        self.transcript_preview.setReadOnly(True)
        self.transcript_preview.setObjectName("log_viewer")
        self.transcript_preview.setPlaceholderText("转写完成后在此预览字幕...")
        sub_vl.addWidget(self.transcript_preview)

        # Export Subtitles Button
        self.btn_export_sub = mdi_button("导出字幕", "save")
        self.btn_export_sub.setObjectName("secondary_button")
        self.btn_export_sub.setEnabled(False)
        self.btn_export_sub.clicked.connect(self._export_subtitles)
        sub_vl.addWidget(self.btn_export_sub)

        lower_layout.addWidget(sub_card, 1)

        # Right: Hotspot list
        list_card = QFrame()
        list_card.setObjectName("card")
        ll = QVBoxLayout(list_card)
        ll.setSpacing(8)
        ll.setContentsMargins(12, 10, 12, 10)

        lh = QHBoxLayout()
        lh.addWidget(QLabel("<b>\U0001F4CA 发现的热点片段</b>"))
        lh.addStretch()

        # Score filter dropdown
        lh.addWidget(QLabel("评分过滤:"))
        self.score_filter = QComboBox()
        self.score_filter.addItem("显示所有", 0.0)
        self.score_filter.addItem(">= 3.0", 3.0)
        self.score_filter.addItem(">= 5.0", 5.0)
        self.score_filter.addItem(">= 6.0", 6.0)
        self.score_filter.addItem(">= 7.0", 7.0)
        self.score_filter.addItem(">= 8.0", 8.0)
        self.score_filter.addItem(">= 9.0", 9.0)
        self.score_filter.setCurrentIndex(6)  # 默认设置为 >= 9.0
        self.score_filter.currentIndexChanged.connect(self._filter_hotspots)
        lh.addWidget(self.score_filter)

        self.selected_count_lbl = QLabel("已选: 0")
        self.selected_count_lbl.setObjectName("success_text")
        lh.addWidget(self.selected_count_lbl)

        sel_btns = QHBoxLayout()
        ba = QPushButton("全选"); ba.setObjectName("secondary_button"); ba.clicked.connect(self._select_all)
        bd = QPushButton("取消"); bd.setObjectName("secondary_button"); bd.clicked.connect(self._deselect_all)
        sel_btns.addWidget(ba); sel_btns.addWidget(bd); sel_btns.addStretch()
        lh.addLayout(sel_btns)
        ll.addLayout(lh)

        self.hotspot_table = QTableWidget(0, 5)
        self.hotspot_table.setHorizontalHeaderLabels(["选择", "时间段", "时长", "评分", "标题"])
        self.hotspot_table.verticalHeader().setVisible(False)
        self.hotspot_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hotspot_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hotspot_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.hotspot_table.setColumnWidth(0, 50)
        self.hotspot_table.setColumnWidth(1, 110)
        self.hotspot_table.setColumnWidth(2, 60)
        self.hotspot_table.setColumnWidth(3, 50)
        self.hotspot_table.cellClicked.connect(self._on_hotspot_clicked)
        self.hotspot_table.cellChanged.connect(lambda r, c: self._update_count() if c == 0 else None)
        ll.addWidget(self.hotspot_table)

        # Removed hotspot_detail text edit since it is no longer needed

        lower_layout.addWidget(list_card, 1)

        layout.addLayout(lower_layout, 1)

        # Bottom status, progress and navigation row for Page 0
        bot_layout = QHBoxLayout()
        
        self.stage_lbl_p0 = QLabel("就绪 - 请选择直播视频")
        self.stage_lbl_p0.setObjectName("muted_text")
        bot_layout.addWidget(self.stage_lbl_p0)

        self.progress_bar_p0 = QProgressBar()
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p0.setRange(0, 100)
        bot_layout.addWidget(self.progress_bar_p0, 1)

        self.btn_to_step2 = mdi_button("下一步：切片与封面", "right")
        self.btn_to_step2.setObjectName("primary_button")
        self.btn_to_step2.setEnabled(False)
        self.btn_to_step2.clicked.connect(lambda: self._go_to_step(1))
        bot_layout.addWidget(self.btn_to_step2)
        
        layout.addLayout(bot_layout)

        self.stacked.addWidget(page)

    # ===== Page 1: Clip & Cover =====
    def _setup_page_clip(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Unified Card for Step 2
        clip_list_card = QFrame()
        clip_list_card.setObjectName("card")
        ccl = QVBoxLayout(clip_list_card)
        ccl.setSpacing(12)
        ccl.setContentsMargins(16, 16, 16, 16)
        
        # Header controls row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)
        
        title_lbl = QLabel("<b>\u2702 自动切片与封面编辑</b>")
        title_lbl.setObjectName("clip_page_title")
        header_layout.addWidget(title_lbl)
        
        self.clip_status_lbl = QLabel("已选 0 个片段待切片")
        self.clip_status_lbl.setObjectName("clip_status_label")
        header_layout.addWidget(self.clip_status_lbl)
        
        self.btn_clip = mdi_button("开始切片", "cut")
        self.btn_clip.setObjectName("action_button")
        self.btn_clip.setFixedHeight(30)
        self.btn_clip.setFixedWidth(120)
        self.btn_clip.clicked.connect(self._start_clip_pipeline)
        header_layout.addWidget(self.btn_clip)
        
        ccl.addLayout(header_layout)
        
        # Scroll Area for the list of clips
        self.cover_scroll = QScrollArea()
        self.cover_scroll.setWidgetResizable(True)
        self.cover_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cover_scroll.setFrameShape(QScrollArea.NoFrame)
        self.cover_scroll.setStyleSheet("background-color: transparent;")
        
        self.cover_container = QWidget()
        self.cover_container.setStyleSheet("background-color: transparent;")
        self.clips_list_layout = QGridLayout(self.cover_container)
        self.clips_list_layout.setContentsMargins(0, 0, 0, 0)
        self.clips_list_layout.setSpacing(12)
        self.clips_list_layout.setAlignment(Qt.AlignTop)
        
        self.cover_scroll.setWidget(self.cover_container)
        ccl.addWidget(self.cover_scroll, 1)
        
        layout.addWidget(clip_list_card, 1)

        # Export card
        export_card = QFrame()
        export_card.setObjectName("card")
        evl = QVBoxLayout(export_card)
        evl.setSpacing(8)
        evl.addWidget(QLabel("<b>\U0001F4E4 最终导出</b>"))
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_export = mdi_button("确认封面并导出最终视频", "rocket")
        self.btn_export.setObjectName("action_button")
        self.btn_export.setFixedHeight(40)
        self.btn_export.clicked.connect(self._start_final_export)
        self.btn_export.setEnabled(False)
        btn_layout.addWidget(self.btn_export, 1)

        self.btn_open_output = mdi_button("打开输出目录", "folder")
        self.btn_open_output.setObjectName("secondary_button")
        self.btn_open_output.setFixedHeight(40)
        self.btn_open_output.clicked.connect(self._open_output)
        self.btn_open_output.setEnabled(False)
        btn_layout.addWidget(self.btn_open_output, 1)
        
        evl.addLayout(btn_layout)

        self.export_result_lbl = QLabel("")
        self.export_result_lbl.setWordWrap(True)
        self.export_result_lbl.setObjectName("export_result_label")
        evl.addWidget(self.export_result_lbl)
        
        layout.addWidget(export_card)

        # Progress & Status for Page 1
        self.stage_lbl_p1 = QLabel("就绪")
        self.stage_lbl_p1.setObjectName("muted_text")
        layout.addWidget(self.stage_lbl_p1)

        self.progress_bar_p1 = QProgressBar()
        self.progress_bar_p1.setVisible(False)
        self.progress_bar_p1.setRange(0, 100)
        layout.addWidget(self.progress_bar_p1)

        # Nav
        nav = QHBoxLayout()
        nav.addWidget(mdi_button("上一步：视频分析", "left"))
        nav.itemAt(0).widget().setObjectName("secondary_button")
        nav.itemAt(0).widget().clicked.connect(lambda: self._go_to_step(0))
        nav.addStretch()
        layout.addLayout(nav)

        self.stacked.addWidget(page)

        # ===== Actions =====

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择直播视频", "",
                                              "Video (*.mp4 *.flv *.ts *.mov *.avi *.mkv);;All (*)")
        if path:
            self.video_path = path
            self.video_path_input.setText(path)
            gb = os.path.getsize(path) / (1024 ** 3)
            self.video_info_lbl.setText(f"\U0001F4E6 文件: {gb:.1f} GB  |  流式处理，内存安全")
            
            # Auto-check if audio was already extracted previously
            vname = os.path.splitext(os.path.basename(path))[0]
            self.audio_path = os.path.join(TMP_DIR, f"{vname}_audio.wav")
            if os.path.exists(self.audio_path) and os.path.getsize(self.audio_path) > 0:
                self.audio_player.set_audio_path(self.audio_path)
            else:
                self.audio_player.setEnabled(False)
                self.audio_player.lbl_time.setText("等待提取音频...")

    def _start_analysis_pipeline(self):
        self._stop_requested = False
        log.info("[LiveClip] _start_analysis_pipeline")
        video_path = self.video_path_input.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "错误", "请先选择视频文件")
            return
        self.video_path = video_path
        self.btn_export_sub.setEnabled(False)

        os.makedirs(TMP_DIR, exist_ok=True)
        vname = os.path.splitext(os.path.basename(video_path))[0]
        self.audio_path = os.path.join(TMP_DIR, f"{vname}_audio.wav")

        # 音频缓存：存在且未勾选"重新提取"则跳过
        reextract = getattr(self, "chk_reextract", None) and self.chk_reextract.isChecked()
        if os.path.exists(self.audio_path) and os.path.getsize(self.audio_path) > 0 and not reextract:
            self.btn_analyze.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_to_step2.setEnabled(False)
            self.stage_lbl.setText("使用已提取的音频...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.audio_player.set_audio_path(self.audio_path)
            self._do_transcribe(self.audio_path)
            return

        # 勾选了重新提取或首次运行，删除旧文件
        if os.path.exists(self.audio_path):
            try:
                os.remove(self.audio_path)
            except Exception:
                pass

        self.btn_analyze.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_to_step2.setEnabled(False)
        self.stage_lbl.setText("正在读取视频并转换为声音文件...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        self._audio_worker = AudioExtractWorker(video_path, self.audio_path)
        self._audio_worker.stage.connect(self.stage_lbl.setText)
        self._audio_worker.progress.connect(self.progress_bar.setValue)
        self._audio_worker.finished.connect(self._do_transcribe)
        self._audio_worker.error.connect(self._on_err)
        self._audio_worker.start()

        def _do_transcribe(self, audio_path):
            log.info(f"[LiveClip] _do_transcribe audio_path={audio_path}")
            out_dir = os.path.join(OUTPUTS_DIR, "transcription")
            os.makedirs(out_dir, exist_ok=True)
            vname = os.path.splitext(os.path.basename(self.video_path))[0]
            out = os.path.join(out_dir, f"{vname}.srt")
            self.srt_path = out

            self.stage_lbl.setText("正在上传音频到服务端...")
            self.progress_bar.setRange(0, 0)  # 不确定模式
            self.progress_bar.setVisible(True)

            lang_choice = self.transcribe_lang.currentData()
            language = None if lang_choice == "auto" else lang_choice

            from utils.asr_client import transcribe_remote, read_asr_url
            from utils.base_worker import BaseWorker

            class RemoteTranscribeWorker(BaseWorker):
                stage = Signal(str)
                progress = Signal(int)
                finished = Signal(str)
                error = Signal(str)

                def __init__(self, video_path, output_path, language):
                    super().__init__()
                    self.video_path = video_path
                    self.output_path = output_path
                    self.language = language

                def do_work(self):
                    if self.isInterruptionRequested():
                        return
                    try:
                        log.info(f"[RemoteTranscribeWorker] 开始, file={self.video_path}")
                        asr_url = read_asr_url()
                        segments = transcribe_remote(
                            self.video_path, asr_url,
                            language=self.language, task_type="transcribe",
                            progress_cb=lambda m: (self.stage.emit(m), log.info(f"[RemoteTranscribeWorker] {m}")),
                        )
                        if self.isInterruptionRequested():
                            return
                        lines = []
                        lines = []
                        for i, seg in enumerate(segments):
                            start = seg.get("start", 0)
                            end = seg.get("end", 0)
                            text = seg.get("text", "").strip().replace("\n", " ")
                            lines.append(f"{i+1}")
                            lines.append(
                                f"{int(start//3600):02d}:{int(start%3600//60):02d}:{start%60:06.3f} --> "
                                f"{int(end//3600):02d}:{int(end%3600//60):02d}:{end%60:06.3f}"
                            )
                            lines.append(text)
                            lines.append("")
                        srt_text = "\n".join(lines)
                        with open(self.output_path, "w", encoding="utf-8") as f:
                            f.write(srt_text)
                        self.stage.emit("转写完成")
                        self.finished.emit(self.output_path)
                    except Exception as e:
                        self.error.emit(str(e))

            self._tw = RemoteTranscribeWorker(audio_path, out, language)
            self.audio_player.set_audio_path(audio_path)
            self._tw.stage.connect(self.stage_lbl.setText)
            self._tw.finished.connect(self._do_analyze)
            self._tw.error.connect(self._on_err)
            self._tw.start()

    def _stop_analysis(self):
        log.info("[LiveClip] _stop_analysis 用户请求停止")
        self._stop_requested = True
        # 停止音频提取
        if hasattr(self, "_audio_worker") and self._audio_worker and self._audio_worker.isRunning():
            self._audio_worker.requestInterruption()
            self._audio_worker.terminate()
            self._audio_worker.wait(2000)
        # 停止转写（HTTP 阻塞无法优雅中断，强制终止）
        if hasattr(self, "_tw") and self._tw and self._tw.isRunning():
            self._tw.requestInterruption()
            self._tw.terminate()
            self._tw.wait(2000)
        self._reset_ui()
        self.stage_lbl.setText("⏹ 已停止")
        log.info("[LiveClip] _stop_analysis 完成")

    def _do_analyze(self, srt_content, srt_path):
        self._parse_srt(srt_content)
        self._update_transcript_preview_html()
        self.btn_export_sub.setEnabled(True)

        if not self.transcript_segments:
            QMessageBox.warning(self.parent_widget, "提示", "未识别到语音内容")
            self._reset_ui()
            return

        mode = self.analysis_mode.currentData()
        use_llm = (mode == "llm")
        llm_url = llm_key = llm_model = ""
        if use_llm:
            cfg = getattr(self.main_window, "ai_config", {})
            llm_url = cfg.get("llm_api_url", "")
            llm_key = cfg.get("llm_api_key", "")
            llm_model = cfg.get("llm_model", "deepseek-chat")
            if not llm_url or not llm_key:
                QMessageBox.warning(self.parent_widget, "未配置LLM",
                                    "请在 'AI 设置' 中配置大模型 API。\n将使用内置算法。")
                use_llm = False

        if use_llm:
            self.stage_lbl.setText("正在使用大模型（DeepSeek/OpenAI）分析热点...")
        else:
            self.stage_lbl.setText("正在使用内置算法分析热点...")
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)

        self._analyzer = HotSpotAnalyzer(self.transcript_segments,
                                         use_llm=use_llm, llm_url=llm_url, llm_key=llm_key, llm_model=llm_model)
        self._analyzer.stage.connect(self.stage_lbl.setText)
        self._analyzer.progress.connect(self.progress_bar.setValue)
        self._analyzer.finished.connect(self._on_analysis)
        self._analyzer.error.connect(self._on_err)
        self._analyzer.start()

    def _parse_srt(self, srt):
        self.transcript_segments = []
        srt = srt.replace("\r\n", "\n").replace("\r", "\n")
        # Split by double newlines or lines containing only spaces
        blocks = re.split(r'\n\s*\n', srt.strip())
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            if len(lines) < 3:
                continue
            
            timestamp_line = lines[1]
            text = " ".join(lines[2:]).strip()
            if not text:
                continue
            
            match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})", timestamp_line)
            if match:
                sh, sm, ss, sms = match.group(1), match.group(2), match.group(3), match.group(4)
                eh, em, es, ems = match.group(5), match.group(6), match.group(7), match.group(8)
                
                sms_val = float(sms) / (10**len(sms))
                ems_val = float(ems) / (10**len(ems))
                
                start = int(sh) * 3600 + int(sm) * 60 + int(ss) + sms_val
                end = int(eh) * 3600 + int(em) * 60 + int(es) + ems_val
                
                self.transcript_segments.append(type("S", (), {"start": start, "end": end, "text": text})())

    def _on_analysis(self, hotspots):
        self.hotspots = hotspots
        self.btn_analyze.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.stage_lbl.setText(f"发现 {len(hotspots)} 个热点片段")

        self.hotspot_table.setRowCount(len(hotspots))
        for i, hs in enumerate(hotspots):
            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked); self.hotspot_table.setItem(i, 0, chk)
            self.hotspot_table.setItem(i, 1, QTableWidgetItem(f"{hs['start_str']} - {hs['end_str']}"))
            d = hs["duration"]
            ds = f"{d // 60}m{d % 60}s" if d >= 60 else f"{d}s"
            self.hotspot_table.setItem(i, 2, QTableWidgetItem(ds))
            si = QTableWidgetItem(str(hs["score"]))
            if hs["score"] >= 7: si.setForeground(Qt.green)
            elif hs["score"] >= 5: si.setForeground(Qt.yellow)
            self.hotspot_table.setItem(i, 3, si)
            self.hotspot_table.setItem(i, 4, QTableWidgetItem(hs["title"]))

        self.btn_to_step2.setEnabled(len(hotspots) > 0)
        self._filter_hotspots()

    def _on_hotspot_clicked(self, r, c):
        if r < len(self.hotspots):
            hs = self.hotspots[r]
            
            # Scroll left transcript preview to the start of the hotspot
            hs_start = hs["start"]
            best_idx = 1
            min_diff = 999999.0
            for idx, seg in enumerate(self.transcript_segments, 1):
                diff = abs(seg.start - hs_start)
                if diff < min_diff:
                    min_diff = diff
                    best_idx = idx
            
            self.transcript_preview.scrollToAnchor(f"seg_{best_idx}")

    def _update_count(self):
        c = sum(1 for i in range(self.hotspot_table.rowCount())
                if self.hotspot_table.item(i, 0) and self.hotspot_table.item(i, 0).checkState() == Qt.Checked)
        self.selected_count_lbl.setText(f"已选: {c}")

    def _select_all(self):
        for i in range(self.hotspot_table.rowCount()):
            if not self.hotspot_table.isRowHidden(i) and self.hotspot_table.item(i, 0):
                self.hotspot_table.item(i, 0).setCheckState(Qt.Checked)
        self._update_count()

    def _deselect_all(self):
        for i in range(self.hotspot_table.rowCount()):
            if not self.hotspot_table.isRowHidden(i) and self.hotspot_table.item(i, 0):
                self.hotspot_table.item(i, 0).setCheckState(Qt.Unchecked)
        self._update_count()

    def _filter_hotspots(self):
        min_score = self.score_filter.currentData() if hasattr(self, 'score_filter') else 0.0
        for i in range(self.hotspot_table.rowCount()):
            if i < len(self.hotspots):
                score = self.hotspots[i]["score"]
                should_hide = score < min_score
                self.hotspot_table.setRowHidden(i, should_hide)
                
                # Automatically synchronize check state with visibility
                if self.hotspot_table.item(i, 0):
                    if should_hide:
                        self.hotspot_table.item(i, 0).setCheckState(Qt.Unchecked)
                    else:
                        self.hotspot_table.item(i, 0).setCheckState(Qt.Checked)
        self._update_count()
        self._update_transcript_preview_html()

    def _format_timestamp(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms == 1000:
            ms = 0
            s += 1
            if s == 60:
                s = 0
                m += 1
                if m == 60:
                    m = 0
                    h += 1
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _update_transcript_preview_html(self):
        if not self.transcript_segments:
            return
        
        min_score = self.score_filter.currentData() if hasattr(self, 'score_filter') else 0.0
        
        html_lines = [
            "<html><head><style>"
            "p { margin: 0px 0px 10px 0px; line-height: 1.4; font-size: 13px; color: #e2e8f0; }"
            "span.timestamp { color: #94a3b8; font-family: monospace; font-size: 11px; }"
            "</style></head><body style='background-color: #18181b; margin: 10px;'>"
        ]
        
        for idx, seg in enumerate(self.transcript_segments, 1):
            # Check if this segment overlaps with any active hotspot (score >= min_score)
            best_score = -1
            for hs in self.hotspots:
                if hs["score"] >= min_score:
                    if seg.start < hs["end"] and seg.end > hs["start"]:
                        if hs["score"] > best_score:
                            best_score = hs["score"]
            
            # Determine background color based on score
            bg_style = ""
            if best_score >= 10.0:
                bg_style = "background-color: rgba(153, 27, 27, 0.45); padding: 2px 4px; border-radius: 3px;" # Deep red (10分)
            elif best_score >= 9.0:
                bg_style = "background-color: rgba(234, 88, 12, 0.4); padding: 2px 4px; border-radius: 3px;" # Orange red (9分)
            elif best_score >= 8.0:
                bg_style = "background-color: rgba(217, 119, 6, 0.35); padding: 2px 4px; border-radius: 3px;" # Orange yellow (8分)
            elif best_score >= 6.0:
                bg_style = "background-color: rgba(46, 204, 113, 0.25); padding: 2px 4px; border-radius: 3px;" # Soft green
            elif best_score >= 3.0:
                bg_style = "background-color: rgba(52, 152, 219, 0.25); padding: 2px 4px; border-radius: 3px;" # Soft blue
                
            start_str = self._format_timestamp(seg.start)
            end_str = self._format_timestamp(seg.end)
            
            anchor_html = f"<a name='seg_{idx}'></a>"
            
            if bg_style:
                text_html = f"<span style='{bg_style}'>{seg.text}</span>"
            else:
                text_html = f"<span>{seg.text}</span>"
                
            html_lines.append(
                f"<p>{anchor_html}<b>{idx}</b><br>"
                f"<span class='timestamp'>{start_str} --> {end_str}</span><br>"
                f"{text_html}</p>"
            )
            
        html_lines.append("</body></html>")
        self.transcript_preview.setHtml("".join(html_lines))

    def _export_subtitles(self):
        if not getattr(self, "srt_path", "") or not os.path.exists(self.srt_path):
            QMessageBox.warning(self.parent_widget, "提示", "未找到生成的字幕文件。")
            return
            
        vname = os.path.splitext(os.path.basename(self.video_path))[0] if getattr(self, "video_path", "") else "transcript"
        default_dir = os.path.dirname(os.path.abspath(self.video_path)) if getattr(self, "video_path", "") and os.path.exists(self.video_path) else ""
        default_path = os.path.join(default_dir, f"{vname}.srt")
        
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "保存字幕文件",
            default_path,
            "SRT Subtitle Files (*.srt);;All Files (*)"
        )
        if path:
            try:
                shutil.copy(self.srt_path, path)
                QMessageBox.information(self.parent_widget, "导出成功", f"字幕文件已成功保存到：\n{path}")
            except Exception as e:
                QMessageBox.critical(self.parent_widget, "导出失败", f"无法保存文件：\n{e}")

    def _start_clip_pipeline(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self.parent_widget, "错误", f"视频文件不存在，请重新选择视频文件。\n路径: {self.video_path or '未选择'}")
            return

        selected = []
        for widget in getattr(self, "clip_item_widgets", []):
            clip_data = dict(widget.clip_info)
            clip_data["burn_subtitles"] = widget.chk_subtitles.isChecked()
            clip_data["index"] = widget.clip_index
            selected.append(clip_data)
            
        if not selected:
            QMessageBox.warning(self.parent_widget, "未选择", "当前没有可切片的片段")
            return

        vname = os.path.splitext(os.path.basename(self.video_path))[0]
        self.output_dir = os.path.join(OUTPUTS_DIR, "live_clips", vname)
        os.makedirs(self.output_dir, exist_ok=True)

        self.btn_clip.setEnabled(False)
        for widget in getattr(self, "clip_item_widgets", []):
            widget.btn_slice_single.setEnabled(False)
            widget.btn_slice_single.setText("批量切片中")
        self.clip_status_lbl.setText(f"正在切片 {len(selected)} 个片段...")
        self.stage_lbl.setText("切片中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        self._clip_worker = VideoClipWorker(
            self.video_path, selected, self.output_dir, 
            srt_path=getattr(self, "srt_path", "")
        )
        self._clip_worker.stage.connect(self.stage_lbl.setText)
        self._clip_worker.progress.connect(self.progress_bar.setValue)
        self._clip_worker.finished.connect(self._on_clip_done)
        self._clip_worker.error.connect(self._on_err)
        self._clip_worker.start()

    def _on_clip_done(self, results):
        self.clipped_results = results
        self.clip_status_lbl.setText(f"\u2705 切片完成：{len(results)} 个视频")
        self.stage_lbl.setText("正在生成封面...")
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)

        self._cover_worker = CoverGeneratorWorker(results, self.output_dir)
        self._cover_worker.stage.connect(self.stage_lbl.setText)
        self._cover_worker.progress.connect(self.progress_bar.setValue)
        self._cover_worker.cover_ready.connect(self._on_cover_ready)
        self._cover_worker.finished.connect(self._on_covers_done)
        self._cover_worker.error.connect(self._on_err)
        self._cover_worker.start()

    def _init_clip_list(self):
        while self.clips_list_layout.count():
            item = self.clips_list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                
        self.clip_item_widgets = []
        self.selected_clip_idx = -1
        
        selected_hotspots = []
        for i in range(self.hotspot_table.rowCount()):
            it = self.hotspot_table.item(i, 0)
            if it and it.checkState() == Qt.Checked and i < len(self.hotspots):
                hs_copy = dict(self.hotspots[i])
                selected_hotspots.append(hs_copy)
                
        for idx, hs in enumerate(selected_hotspots):
            widget = ClipListItemWidget(hs, idx, self)
            row = idx // 3
            col = idx % 3
            self.clips_list_layout.addWidget(widget, row, col)
            self.clip_item_widgets.append(widget)

    def select_clip_item(self, index):
        if index < 0 or index >= len(self.clip_item_widgets):
            return
        
        self.selected_clip_idx = index
        for i, widget in enumerate(self.clip_item_widgets):
            widget.set_selected(i == index)

    def on_clip_info_updated(self, index, new_title, cover_path, cover_vertical_path=None):
        for ci in self.covers_info:
            if ci["index"] == index:
                ci["title"] = new_title
                ci["cover_path"] = cover_path
                if cover_vertical_path:
                    ci["cover_vertical_path"] = cover_vertical_path
                break

    def pause_all_players_except(self, active_index):
        for widget in getattr(self, "clip_item_widgets", []):
            if widget.clip_index != active_index:
                widget.pause_audio()

    def update_covers_info_for_index(self, index, ci_data):
        if not hasattr(self, "covers_info") or self.covers_info is None:
            self.covers_info = []
            
        found = False
        for i, item in enumerate(self.covers_info):
            if item["index"] == index:
                self.covers_info[i] = ci_data
                found = True
                break
        if not found:
            self.covers_info.append(ci_data)
            
        self.btn_export.setEnabled(len(self.covers_info) > 0)

    def _on_cover_ready(self, idx, cover_path):
        self.cover_images[idx] = cover_path
        if idx < len(self.clip_item_widgets):
            self.clip_item_widgets[idx].clip_info["cover_path"] = cover_path

    def _on_covers_done(self, covers_info):
        self.covers_info = covers_info
        self.btn_clip.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.stage_lbl.setText(f"✅ 封面生成完成：{len(covers_info)} 个")

        for ci in covers_info:
            idx = ci["index"]
            if idx < len(self.clip_item_widgets):
                self.clip_item_widgets[idx].clip_info["cover_path"] = ci["cover_path"]
                self.clip_item_widgets[idx].clip_info["cover_vertical_path"] = ci.get("cover_vertical_path", "")
                self.clip_item_widgets[idx].clip_info["frame_path"] = ci["frame_path"]
                self.clip_item_widgets[idx].clip_info["video_path"] = ci["video_path"]
                self.clip_item_widgets[idx].clip_info["title"] = ci["title"]
                self.clip_item_widgets[idx].enable_playback(ci["video_path"])

        if self.clip_item_widgets:
            self.select_clip_item(0)

    def _start_final_export(self):
        if not self.clip_item_widgets or not self.covers_info:
            return
            
        for widget in self.clip_item_widgets:
            idx = widget.clip_index
            new_title = widget.clip_info["title"].strip()
            for ci in self.covers_info:
                if ci["index"] == idx:
                    ci["title"] = new_title
        self.btn_export.setEnabled(False)
        self.stage_lbl.setText("导出最终视频（嵌入封面首帧）...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        self._export_worker = FinalExportWorker(self.covers_info, self.output_dir)
        self._export_worker.stage.connect(self.stage_lbl.setText)
        self._export_worker.progress.connect(self.progress_bar.setValue)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.error.connect(self._on_err)
        self._export_worker.start()

    def _on_export_done(self, paths):
        self.btn_export.setEnabled(True)
        self.btn_open_output.setEnabled(True)
        self.progress_bar.setVisible(False)
        final_dir = os.path.join(self.output_dir, "final")
        self.export_result_lbl.setText(f"\u2705 导出完成！{len(paths)} 个视频已保存到:\n{final_dir}")
        self.stage_lbl.setText(f"导出完成，共 {len(paths)} 个视频")
        QMessageBox.information(self.parent_widget, "导出完成",
                                f"成功导出 {len(paths)} 个带封面的视频！\n\n{final_dir}")

    def _on_err(self, err):
        self.btn_analyze.setEnabled(True)
        self.btn_clip.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p1.setVisible(False)
        self.stage_lbl.setText("❌ 操作失败")
        
        for widget in getattr(self, "clip_item_widgets", []):
            if not widget.clip_info.get("video_path"):
                widget.btn_slice_single.setEnabled(True)
                widget.btn_slice_single.setText("单独切片")
                
        s = ""
        for line in (err or "").splitlines()[::-1]:
            if line.strip(): s = line.strip(); break
        QMessageBox.critical(self.parent_widget, "错误", f"操作失败:\n{s or err[:500]}")

        def _reset_ui(self):
            self.btn_analyze.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_to_step2.setEnabled(False)
        self.progress_bar_p0.setVisible(False)
        self.progress_bar_p1.setVisible(False)
        self.btn_export_sub.setEnabled(False)

    def _open_output(self):
        if self.output_dir:
            d = os.path.join(self.output_dir, "final")
            if os.path.exists(d):
                QDesktopServices.openUrl(QUrl.fromLocalFile(d))
            elif os.path.exists(self.output_dir):
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))
