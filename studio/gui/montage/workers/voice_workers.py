# -*- coding: utf-8 -*-
"""智能混剪 - 配音阶段 Worker：声音克隆（TTS）。"""
import os
import time
import base64
import subprocess
import traceback
import requests
from utils.http_client import http_get, http_post
from utils.voxcpm_client import repair_wav_bytes
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.api_error import ApiError
from gui.montage.utils_media import find_ffmpeg, get_media_duration



class VoiceCloneWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    row_progress = Signal(int, int) # row_idx, value (0-100)
    finished = Signal(dict)  # Outputs a dict mapping: video_path -> voice_wav_path

    def __init__(self, tasks, voice_ref_audio, voice_ref_text, voice_mode, voice_api_url, voice_cli_checkpoint, temp_dir, task_type="video",
                 inference_timesteps=10, cfg_value=2.0, speed_min=0.9, speed_max=1.2):
        super().__init__()
        self.tasks = tasks  # list of tuples: (row_idx, text, video_path, output_wav_path)
        self.voice_ref_audio = voice_ref_audio
        self.voice_ref_text = voice_ref_text
        self.voice_mode = voice_mode
        self.voice_api_url = voice_api_url
        self.voice_cli_checkpoint = voice_cli_checkpoint
        self.temp_dir = temp_dir
        self.task_type = task_type
        self.inference_timesteps = inference_timesteps
        self.cfg_value = cfg_value
        self.speed_min = speed_min  # 变速下限：音频过长时最多拉慢到此倍速，超出不调整
        self.speed_max = speed_max  # 变速上限：音频过短时最多加速到此倍速，超出不调整
        self.failures = []  # [(row_idx, video_path, error_msg)] 单条失败记录（不中断整批）

    def _health_url(self):
        """由 TTS 接口地址推导出 /health 健康检查地址。"""
        try:
            u = self.voice_api_url
            for suffix in ("/v1/tts", "/tts"):
                if u.endswith(suffix):
                    return u[: -len(suffix)] + "/health"
            # 兜底：取 scheme://host:port + /health
            from urllib.parse import urlparse
            p = urlparse(u)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}/health"
        except Exception:
            pass
        return None

    def _wait_for_server_recovery(self, max_wait=20.0):
        """连接中断后，轮询 /health 等待服务恢复；返回是否恢复。"""
        health = self._health_url()
        if not health:
            time.sleep(min(3.0, max_wait))
            return False
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                r = http_get(health, timeout=3, quiet=True)
                if r.status_code == 200 and r.json().get("loaded"):
                    return True
            except Exception:
                pass
            time.sleep(2.0)
        return False

    @staticmethod
    def _preprocess_tts_text(text: str) -> str:
        """预处理发往 TTS 的文本：阿拉伯数字转中文、大写英文缩写拆为逐字母。

        解决的问题：
        - "8000 DPI" → VoxCPM 可能读成"八零零零"或跳过 → 预处理为"八千 D P I"
        - "LIGHTSPEED" 等品牌词被跳过 → 拆为"L I G H T S P E E D"逐字播报
        - "Type-C" → "Type C"（去连字符，避免停顿异常）
        """
        import re

        CN_DIGITS = "零一二三四五六七八九"

        def int_to_cn(n: int) -> str:
            if n == 0:
                return "零"
            units = [
                (100_000_000, "亿"), (10_000, "万"),
                (1_000, "千"), (100, "百"), (10, "十"), (1, ""),
            ]
            result = ""
            need_zero = False
            for val, name in units:
                d = n // val
                n %= val
                if d:
                    if need_zero:
                        result += "零"
                        need_zero = False
                    if not (val == 10 and d == 1 and not result):
                        result += CN_DIGITS[d]
                    result += name
                elif result:
                    need_zero = True
            return result

        # 1. 整数 → 中文（先处理小数 x.y → 中文x点中文y，再处理整数）
        def replace_decimal(m):
            try:
                int_part = int_to_cn(int(m.group(1)))
                frac_part = int_to_cn(int(m.group(2)))
                return f"{int_part}点{frac_part}"
            except Exception:
                return m.group(0)

        def replace_int(m):
            try:
                return int_to_cn(int(m.group(0)))
            except Exception:
                return m.group(0)

        text = re.sub(r'\b(\d+)\.(\d+)\b', replace_decimal, text)
        text = re.sub(r'\b\d+\b', replace_int, text)

        # 2. 全大写英文缩写（2字母以上）→ 字母间加空格，便于逐字播报
        _keep_units = {"Hz", "MHz", "GHz", "kHz"}
        def space_caps(m):
            w = m.group(0)
            return w if w in _keep_units else " ".join(list(w))
        text = re.sub(r'\b[A-Z]{2,}\b', space_caps, text)

        # 3. 英文连字符 → 空格（Type-C → Type C）
        text = re.sub(r'([A-Za-z])-([A-Za-z])', r'\1 \2', text)

        return text

    def _post_tts(self, text, ref_audio_b64, row_idx, label=""):
        """向服务端 VoxCPM API 发起一次合成请求，带重试，返回 wav 字节；失败抛异常。

        服务端接口：POST /voxcpm/tts
          {"text": "...", "prompt_audio": "base64...", "speaker": "default"}
        """
        payload = {
            "text": self._preprocess_tts_text(text),
            "prompt_audio": ref_audio_b64 or None,
            "speaker": "default",
        }
        max_attempts = 3
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                res = http_post(self.voice_api_url, json=payload, timeout=180)
                if res.status_code == 503:
                    # 503：服务端繁忙/资源不足，不猜测具体原因，只显示服务端响应
                    raise ApiError(self.voice_api_url, method="POST", params=payload,
                                   status_code=503, response_text=res.text, service="voxcpm")
                if res.status_code != 200:
                    raise ApiError(self.voice_api_url, method="POST", params=payload,
                                   status_code=res.status_code, response_text=res.text, service="voxcpm")
                return res.content
            except requests.exceptions.RequestException as e:
                # 连接被重置/超时：服务可能崩溃，等待恢复后重试
                last_err = e
                if attempt < max_attempts:
                    self.stage.emit(
                        f"第 {row_idx + 1} 个声音{label}连接中断，等待服务恢复后重试 "
                        f"({attempt}/{max_attempts - 1})...")
                    if not self._wait_for_server_recovery(max_wait=20.0):
                        time.sleep(2.0)
                    continue
                raise ApiError(self.voice_api_url, method="POST", params=payload,
                               cause=e, note=f"连接失败（已重试 {max_attempts} 次）", service="voxcpm")
            except ApiError as e:
                last_err = e
                # 仅对 503（服务端繁忙）重试，其它确定性错误直接抛出
                if e.status_code == 503 and attempt < max_attempts:
                    self.stage.emit(
                        f"第 {row_idx + 1} 个声音{label}服务端繁忙(503)，稍后重试 "
                        f"({attempt}/{max_attempts - 1})...")
                    self._wait_for_server_recovery(max_wait=15.0)
                    time.sleep(2.0)
                    continue
                raise
        raise ApiError(self.voice_api_url, method="POST", params=payload,
                       cause=last_err, note="合成失败", service="voxcpm")

    @staticmethod
    def _split_sentences(text):
        """将（可能多行的）文案切分为可朗读的短句，过滤掉只含标点/符号的片段。"""
        import re
        segs = []
        for line in (text or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            for part in re.split(r"(?<=[。！？!?；;…])", line):
                part = part.strip()
                if part:
                    segs.append(part)
        # 仅保留含有中文/字母/数字（可朗读内容）的片段
        return [s for s in segs if re.search(r"[一-鿿A-Za-z0-9]", s)]

    @staticmethod
    def _concat_wav_bytes(wav_list, gap_sec=0.15):
        """把多段 wav 字节按顺序拼接为一段（句间插入少量静音），返回 wav 字节。"""
        import io
        import wave
        if not wav_list:
            raise RuntimeError("没有可拼接的音频片段")
        out_io = io.BytesIO()
        writer = None
        params = None
        try:
            for i, wb in enumerate(wav_list):
                with wave.open(io.BytesIO(wb), "rb") as w:
                    p = w.getparams()
                    frames = w.readframes(w.getnframes())
                if writer is None:
                    params = p
                    writer = wave.open(out_io, "wb")
                    writer.setparams(p)
                writer.writeframes(frames)
                if gap_sec > 0 and i < len(wav_list) - 1:
                    nsil = int(gap_sec * params.framerate)
                    writer.writeframes(b"\x00" * (nsil * params.sampwidth * params.nchannels))
        finally:
            if writer is not None:
                writer.close()
        return out_io.getvalue()

    @staticmethod
    def _wav_bytes_duration(wav_bytes) -> float:
        """读取一段 wav 字节的时长（秒）。"""
        import io
        import wave
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            fr = w.getframerate() or 1
            return w.getnframes() / float(fr)

    @staticmethod
    def _write_timing_sidecar(wav_path, timing):
        """把句级时间轴写到 wav 同名 .timing.json（供字幕精确对轴）。"""
        import json as _json
        try:
            with open(wav_path + ".timing.json", "w", encoding="utf-8") as f:
                _json.dump(timing, f, ensure_ascii=False, indent=1)
        except Exception:
            log.warning(f"写入句级时间轴失败: {wav_path}.timing.json")

    @staticmethod
    def _scale_timing_sidecar(wav_path, factor):
        """音频整体变速后，按 factor 缩放句级时间轴（new = old * factor）。"""
        import json as _json
        p = wav_path + ".timing.json"
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                timing = _json.load(f)
            for t in timing:
                t["start"] = round(float(t.get("start", 0)) * factor, 3)
                t["end"] = round(float(t.get("end", 0)) * factor, 3)
            with open(p, "w", encoding="utf-8") as f:
                _json.dump(timing, f, ensure_ascii=False, indent=1)
        except Exception:
            log.warning(f"缩放句级时间轴失败: {p}")

    def _synthesize_item(self, text, ref_audio_b64, out_wav_path, row_idx):
        """合成一条文案为 wav 文件。

        多句文案 → 逐句合成并记录每句真实时长（写入 .timing.json，供字幕精确对轴），
        再拼接为整段；逐句失败或单句文案 → 整体合成（时间轴退化为整段一条）。
        """
        gap = 0.15
        segs = self._split_sentences(text)

        # 逐句合成：拿到每句真实起止时间，字幕不再靠字数估算
        if len(segs) >= 2:
            try:
                wavs = []
                timing = []
                cursor = 0.0
                for si, seg in enumerate(segs):
                    self.stage.emit(f"第 {row_idx + 1} 个声音逐句合成 {si + 1}/{len(segs)}...")
                    wb = repair_wav_bytes(self._post_tts(seg, ref_audio_b64, row_idx, label="逐句"))
                    dur = self._wav_bytes_duration(wb)
                    timing.append({"text": seg, "start": round(cursor, 3), "end": round(cursor + dur, 3)})
                    cursor += dur + gap
                    wavs.append(wb)
                    time.sleep(0.2)
                combined = self._concat_wav_bytes(wavs, gap_sec=gap)
                with open(out_wav_path, "wb") as f:
                    f.write(combined)
                self._write_timing_sidecar(out_wav_path, timing)
                return
            except Exception:
                self.stage.emit(f"第 {row_idx + 1} 个声音逐句合成失败，回退整体合成...")

        # 整体合成（单句文案 / 逐句失败回退）
        merged_text = text.strip()
        if "\n" in merged_text:
            lines = [l.strip() for l in merged_text.split("\n") if l.strip()]
            merged_text = "。".join(lines) + "。"
        content = repair_wav_bytes(self._post_tts(merged_text, ref_audio_b64, row_idx))
        with open(out_wav_path, "wb") as f:
            f.write(content)
        try:
            total_dur = self._wav_bytes_duration(content)
            if len(segs) <= 1:
                timing = [{"text": merged_text, "start": 0.0, "end": round(total_dur, 3)}]
            else:
                # 回退场景：整段音频内按字数比例分配句时间（比无时间轴强）
                char_counts = [max(1, len(s)) for s in segs]
                total_chars = sum(char_counts)
                timing = []
                cursor = 0.0
                for s, c in zip(segs, char_counts):
                    d = total_dur * c / total_chars
                    timing.append({"text": s, "start": round(cursor, 3), "end": round(cursor + d, 3)})
                    cursor += d
            self._write_timing_sidecar(out_wav_path, timing)
        except Exception:
            pass

    def run(self):
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            voices_dir = os.path.join(self.temp_dir, "voices")
            os.makedirs(voices_dir, exist_ok=True)
            
            results = {}
            total = len(self.tasks)
            
            ref_audio_b64 = None
            if self.voice_ref_audio and os.path.exists(self.voice_ref_audio):
                with open(self.voice_ref_audio, "rb") as f:
                    ref_audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            for index, (row_idx, text, video_path, out_wav_path) in enumerate(self.tasks):
                if not text.strip():
                    continue
                
                if self.task_type == "voice":
                    self.stage.emit(f"正在克隆第 {row_idx + 1} 个声音片段 ({index + 1}/{total})...")
                else:
                    self.stage.emit(f"正在合成第 {row_idx + 1} 个视频的克隆人声 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                self.row_progress.emit(row_idx, 15)
                
                os.makedirs(os.path.dirname(out_wav_path), exist_ok=True)

                try:
                    self.row_progress.emit(row_idx, 50)

                    self._synthesize_item(text, ref_audio_b64, out_wav_path, row_idx)

                    self.row_progress.emit(row_idx, 90)

                    # Adjust audio speed to match video duration.
                    # Clamped to [speed_min, speed_max] to prevent extreme atempo distortion.
                    # If the required ratio falls outside this range, audio is left as-is and
                    # the final step (step 4) handles the remaining mismatch.
                    if os.path.exists(video_path) and video_path.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")):
                        vid_dur = get_media_duration(video_path)
                        aud_dur = get_media_duration(out_wav_path)
                        if vid_dur > 0 and aud_dur > 0 and abs(vid_dur - aud_dur) / vid_dur > 0.02:
                            speed_ratio = aud_dur / vid_dur
                            # Clamp to allowed range — beyond this the distortion is unacceptable
                            clamped = max(self.speed_min, min(self.speed_max, speed_ratio))
                            if abs(clamped - 1.0) > 0.005:
                                temp_wav = out_wav_path + ".tmp.wav"
                                ffmpeg_exe = find_ffmpeg()
                                creationflags = 0x08000000
                                speed_cmd = [
                                    ffmpeg_exe, "-y", "-i", out_wav_path,
                                    "-filter:a", f"atempo={clamped:.4f}",
                                    temp_wav
                                ]
                                sr = subprocess.run(speed_cmd, capture_output=True, creationflags=creationflags)
                                if sr.returncode == 0 and os.path.exists(temp_wav):
                                    os.replace(temp_wav, out_wav_path)
                                    # 音频变速后，句级时间轴同步缩放（atempo=X → 时长×1/X）
                                    self._scale_timing_sidecar(out_wav_path, 1.0 / clamped)

                    results[video_path] = out_wav_path
                    self.row_progress.emit(row_idx, 100)
                except Exception as e:
                    # 单条失败不再中断整批：记录失败、跳过，继续合成其余视频。
                    self.row_progress.emit(row_idx, 0)
                    log.exception(f"第 {row_idx + 1} 个声音克隆失败")
                    self.failures.append((row_idx, video_path, str(e)))
                    self.stage.emit(f"⚠ 第 {row_idx + 1} 个声音克隆失败，已跳过继续...")

                # Brief pause between tasks to let server reset GPU state
                time.sleep(0.3)

            self.progress.emit(100)

            if self.failures and not results:
                # 全部失败：逐条显示接口URL+参数+服务端错误（不猜测原因）
                detail = "\n\n".join(
                    f"· 第 {r + 1} 个：\n{m}" for r, _v, m in self.failures[:8])
                more = "" if len(self.failures) <= 8 else f"\n\n…… 等共 {len(self.failures)} 个失败"
                self.error.emit(
                    f"全部声音克隆均失败（共 {len(self.failures)} 个）。"
                    f"下方为每个失败请求的接口与错误详情：\n\n"
                    f"{detail}{more}")
                return

            if self.failures:
                self.stage.emit(
                    f"声音克隆完成：成功 {len(results)} 个，失败 {len(self.failures)} 个（已跳过）")
            else:
                self.stage.emit("声音克隆合成成功")
            self.finished.emit(results)

        except Exception:
            log.exception("声音克隆失败")
            self.error.emit(traceback.format_exc())
