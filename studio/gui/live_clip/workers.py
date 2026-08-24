import contextlib
import os
import re
import traceback
from collections import Counter
from typing import Any

from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.ffmpeg_utils import (
    DEVNULL,
    PIPE,
    extract_frame as ffmpeg_extract_frame,
    find_ffmpeg,
    popen as ffmpeg_popen,
    run as ffmpeg_run,
)
from utils.hwaccel import get_video_encode_args
from utils.llm_output_utils import extract_json_block
from utils.logger_utils import log

from .utils import HOT_KEYWORDS_CN, embed_cover_to_video, generate_cover_image, slice_srt


class AudioExtractWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, video_path, audio_path):
        super().__init__()
        self.video_path = video_path
        self.audio_path = audio_path
        self._ffmpeg_proc = None

    def run(self):
        try:
            self.stage.emit("正在流式提取音频...")
            log.info(f"[AudioExtractWorker] 开始提取音频: {self.video_path}")
            last = -1
            count = 0
            for sec in self._extract():
                if self.isInterruptionRequested():
                    return
                count += 1
                pct = min(99, int(sec / 10 if sec < 1000 else sec / 60))
                if pct > last:
                    self.progress.emit(pct)
                    last = pct
            if self.isInterruptionRequested():
                return
            log.info(f"[AudioExtractWorker] 提取完成, 进度更新{count}次")
            self.progress.emit(100)
            self.finished.emit(self.audio_path)
        except Exception:
            log.exception("[AudioExtractWorker] 提取异常")
            self.error.emit(traceback.format_exc())

    def _extract(self):
        ffmpeg = find_ffmpeg()
        cmd = [ffmpeg, "-y", "-threads", "0", "-i", self.video_path, "-vn",
               "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
               "-progress", "pipe:1", "-nostats", self.audio_path]
        log.info(f"[AudioExtractWorker] ffmpeg: {' '.join(cmd)}")
        self._ffmpeg_proc = ffmpeg_popen(cmd, stdout=PIPE, stderr=DEVNULL,
                                              bufsize=0)
        assert self._ffmpeg_proc.stdout is not None
        for line in iter(self._ffmpeg_proc.stdout.readline, b""):
            if self.isInterruptionRequested():
                self._ffmpeg_proc.kill()
                return
            if line.startswith(b"out_time_ms="):
                with contextlib.suppress(ValueError):
                    yield int(line.split(b"=")[1]) / 1_000_000
        self._ffmpeg_proc.wait()
        if self._ffmpeg_proc.returncode != 0:
            raise RuntimeError("音频提取失败")

    def kill_ffmpeg(self):
        try:
            if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
                self._ffmpeg_proc.kill()
                self.finished.emit(self.audio_path)
        except Exception:
            self.error.emit(traceback.format_exc())


class HotSpotAnalyzer(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, segments, use_llm=False, llm_model=""):
        super().__init__()
        self.segments = [s for s in segments if hasattr(s, 'start') and hasattr(s, 'text')]
        self.use_llm = use_llm
        self.llm_model = llm_model

    def run(self):
        try:
            if self.use_llm and self.llm_model:
                self._llm_analyze()
            else:
                self._rule_analyze()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _rule_analyze(self):
        self.stage.emit("正在使用内置算法分析热点片段...")
        self.progress.emit(10)
        windows: list[dict[str, Any]] = []
        win, step = 60, 30
        total_dur = self.segments[-1].end if self.segments else 0
        for t0 in range(0, int(total_dur) + 1, step):
            t1 = t0 + win
            wsegs = [s for s in self.segments if s.start < t1 and s.end > t0]
            if not wsegs:
                continue
            text = " ".join(s.text.strip() for s in wsegs)
            words: list[str] = list(re.findall(r"[\u4e00-\u9fff\w]+", text))
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
        peaks: list[dict[str, Any]] = [w for w in windows if w["score"] >= threshold]
        self.progress.emit(60)
        merged: list[dict[str, Any]] = []
        for p in sorted(peaks, key=lambda x: x["start"]):
            if merged and p["start"] - merged[-1]["end"] < 20:
                merged[-1]["end"] = max(merged[-1]["end"], p["end"])
                merged[-1]["score"] = max(merged[-1]["score"], p["score"])
                merged[-1]["text"] += " " + p["text"]
                merged[-1]["words"].extend(p["words"])
            else:
                merged.append(p)
        results: list[dict[str, Any]] = []
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
        from utils.llm_proxy import llm_chat_messages
        full: list[str] = []
        for s in self.segments:
            ts = f"[{int(s.start//60):02d}:{int(s.start%60):02d}]"
            full.append(f"{ts} {s.text.strip()}")

        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0
        overlap_lines: list[str] = []
        for line in full:
            if not current_chunk and overlap_lines:
                current_chunk.extend(overlap_lines)
                current_len = sum(len(line) + 1 for line in overlap_lines)
            current_chunk.append(line)
            current_len += len(line) + 1
            if current_len >= 4000:
                chunks.append("\n".join(current_chunk))
                overlap_lines = current_chunk[-5:] if len(current_chunk) >= 5 else current_chunk[:]
                current_chunk = []
                current_len = 0
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        all_results: list[dict[str, Any]] = []
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
                content = llm_chat_messages(
                    [{"role": "user", "content": prompt}],
                    model=self.llm_model, temperature=0.3, timeout=120, max_tokens=2000
                )
                parsed = extract_json_block(content)
                if isinstance(parsed, list):
                    for item in parsed:
                        sp = item["start"].split(":")
                        ep = item["end"].split(":")
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

        merged_results: list[dict[str, Any]] = []
        all_results.sort(key=lambda x: x["start"])
        for item in all_results:
            if not merged_results:
                merged_results.append(item)
            else:
                prev = merged_results[-1]
                if item["start"] <= prev["end"] + 15:
                    new_end = max(prev["end"], item["end"])
                    if new_end - prev["start"] <= 300:
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

                fast_start = max(0, start_sec - 30)
                remain_start = start_sec - fast_start

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
                        vf_args = ["-vf", f"subtitles={rel_srt},format=yuv420p"]
                    else:
                        temp_srt = None
                else:
                    vf_args = ["-vf", "format=yuv420p"]

                abs_video = os.path.abspath(self.video_path)
                abs_out = os.path.abspath(out)

                cmd = [find_ffmpeg(), "-y",
                       "-ss", f"{fast_start:.3f}",
                       "-i", abs_video,
                       "-ss", f"{remain_start:.3f}",
                       "-t", f"{duration:.3f}"] + vf_args + [
                       *get_video_encode_args(crf=23, preset="fast"),
                       "-c:a", "aac", abs_out]

                r = ffmpeg_run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="ignore", cwd=cwd_dir)

                if temp_srt and os.path.exists(temp_srt):
                    with contextlib.suppress(OSError):
                        os.remove(temp_srt)

                if r.returncode != 0 and "-c:v" in cmd:
                    enc_idx = cmd.index("-c:v")
                    enc_name = cmd[enc_idx + 1] if enc_idx + 1 < len(cmd) else ""
                    if enc_name != "libx264":
                        log.warning(f"[切片] GPU编码器 {enc_name} 失败，回退 libx264 重试: {title}")
                        fallback_cmd = list(cmd)
                        clean = [fallback_cmd[0]]
                        skip_next = False
                        for _ci, arg in enumerate(fallback_cmd[1:], 1):
                            if skip_next:
                                skip_next = False
                                continue
                            if arg in ("-preset", "-cq", "-qp_i", "-qp_p", "-global_quality", "-rc"):
                                skip_next = True
                                continue
                            if arg in ("vbr_hq", "speed", "quality", "balanced"):
                                continue
                            clean.append(arg)
                        try:
                            vi = clean.index("-c:v")
                            clean[vi + 1] = "libx264"
                            clean.insert(vi + 2, "-preset")
                            clean.insert(vi + 3, "fast")
                            clean.insert(vi + 4, "-crf")
                            clean.insert(vi + 5, "23")
                        except (ValueError, IndexError):
                            pass
                        r = ffmpeg_run(clean, capture_output=True, text=True, encoding="utf-8",
                                           errors="ignore", cwd=cwd_dir)

                if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
                    stderr_tail = (r.stderr or "")[-300:]
                    log.error(f"[切片] 第{i+1}/{total}个片段失败: {title}\n  cmd={cmd}\n  stderr={stderr_tail}")

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
                if not ffmpeg_extract_frame(ci["path"], 1.0, frame_path, quality=2):
                    raise RuntimeError(f"提取帧失败: {ci['path']}")
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


class _RemoteWorker(BaseWorker):
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
            from utils.asr_client import read_asr_url, transcribe_remote

            log.info(f"[_RemoteWorker] 开始 file={self.video_path}")

            def _progress_cb(m: str) -> None:
                self.stage.emit(m)
                log.info(f"[_RemoteWorker] {m}")

            segs = transcribe_remote(self.video_path, read_asr_url(),
                                     language=self.language,
                                     progress_cb=_progress_cb)
            if self.isInterruptionRequested():
                return
            lines = []
            for i, s in enumerate(segs):
                t = s.get("text", "").strip().replace("\n", " ")
                lines.append(f"{i+1}")
                lines.append(f"{int(s.get('start',0)//3600):02d}:{int(s.get('start',0)%3600//60):02d}:{s.get('start',0)%60:06.3f} --> {int(s.get('end',0)//3600):02d}:{int(s.get('end',0)%3600//60):02d}:{s.get('end',0)%60:06.3f}")
                lines.append(t)
                lines.append("")
            with open(self.output_path, "w", encoding="utf-8") as fp:
                fp.write("\n".join(lines))
            self.stage.emit("转写完成")
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))