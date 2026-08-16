# -*- coding: utf-8 -*-
"""智能混剪 - 拼接/合成阶段 Worker：标准化转码拼接、配音烧字幕、最终混音。"""
import os
import random
import shutil
import subprocess
import traceback
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.hwaccel import get_video_encode_args
from gui.montage.utils_media import find_ffmpeg, get_media_duration


def _run_proc(cmd, **kwargs):
    """运行子进程；默认关闭 stdin，避免 ffmpeg/ffprobe 在 GUI 后台线程中因等待 stdin 输入而假死。

    ffmpeg 默认会尝试读取 stdin 以响应 'q' 等交互命令。在 PySide6 QThread 里，子进程继承的
    stdin 往往不是真实终端；一旦 ffmpeg 阻塞在 stdin 读取上，就会出现 CPU/GPU 占用为 0 的
    "假死"现象。显式传入 DEVNULL 可彻底避免该问题。
    """
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(cmd, **kwargs)



class _TranscodeSkip(Exception):
    """标准化转码单个镜头时，因文件损坏/不可读/转码失败而需跳过。
    携带的提示文案会原样 emit 到 stage 信号，供 UI 展示。"""



class VideoConcatWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Emits list of generated files absolute paths

    def __init__(self, selected_clips, output_dir, layout_mode, recombine_mode, target_clip_count, batch_count, split_descriptions=None, randomness="medium", selected_descriptions_list=None, transition="fade", beat_times=None, music_path="", music_range=None, lut_path=""):
        super().__init__()
        self.selected_clips = selected_clips
        self.output_dir = output_dir
        self.layout_mode = layout_mode
        self.recombine_mode = recombine_mode
        self.target_clip_count = target_clip_count
        self.batch_count = batch_count
        self.split_descriptions = split_descriptions or {}
        self.randomness = randomness
        self.selected_descriptions_list = selected_descriptions_list
        self.transition = transition or "fade"
        # 音乐卡点模式参数：beat_times=相对裁剪后音频的节拍点，music_range=[起始,结束]绝对时间
        self.beat_times = list(beat_times or [])
        self.music_path = music_path or ""
        self.music_range = list(music_range or [])
        self.lut_path = (lut_path or "").strip()

    def _probe_resolution(self, clip):
        """用 ffprobe 读取视频显示分辨率（已考虑旋转），失败返回 None。"""
        import re as _re
        try:
            from utils.platform_utils import find_ffprobe
            ffprobe = find_ffprobe()
            if not os.path.isfile(ffprobe):
                ff = find_ffmpeg()
                ffprobe = ff.replace("ffmpeg", "ffprobe")
            cf = subprocess.CREATE_NO_WINDOW
            cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
                   "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", clip]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=cf, timeout=15)
            m = _re.search(r"(\d+)x(\d+)", (r.stdout or "").strip())
            if m:
                w, h = int(m.group(1)), int(m.group(2))
                if w > 0 and h > 0:
                    return w, h
        except Exception as e:
            log.warning(f"探测原视频分辨率失败: {e}")
        return None

    def _transcode_one(self, i, clip, ffmpeg_path, ffprobe_path, temp_dir, width, height):
        """标准化转码单个镜头到 temp_dir/norm_{i:04d}.mp4。

        纯函数式：只读入参，输出独立文件，无实例状态写入，线程安全。
        文件损坏/探测失败/转码失败时抛 _TranscodeSkip（携带提示文案），由调用方决定跳过。
        成功返回 norm_out 绝对路径。
        """
        clip_abspath = os.path.abspath(clip)
        name = os.path.basename(clip)
        # 1) 完整性快检
        if not os.path.isfile(clip_abspath) or os.path.getsize(clip_abspath) < 1024:
            raise _TranscodeSkip(f"注意： 跳过损坏/过小文件: {name}")
        probe_cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", clip_abspath]
        try:
            probe_r = _run_proc(probe_cmd, capture_output=True, text=True, timeout=15,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            if probe_r.returncode != 0 or not probe_r.stdout.strip():
                raise _TranscodeSkip(f"注意： 跳过无法读取的文件: {name}")
        except _TranscodeSkip:
            raise
        except Exception:
            raise _TranscodeSkip(f"注意： 跳过探测失败的文件: {name}")

        # 2) 转码：缩放/填充黑边/统一 30fps，强制软编 libx264 superfast crf23
        # 标准化转码阶段必须强制软编，避免 GPU 编码器驱动/并发会话在后台线程中
        # 出现 0% 占用假死；xfade/LUT 阶段已强制软编，此处保持一致。
        norm_out = os.path.join(temp_dir, f"norm_{i:04d}.mp4")
        # format=yuv420p：源素材可能是 10-bit（yuv420p10le/HDR），AMF 等硬件编码器
        # 不支持 10-bit 输入，必须在滤镜链显式转 8-bit，否则转码全部失败。
        vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p"

        clip_dur = 0.0
        try:
            if probe_r.returncode == 0 and probe_r.stdout.strip():
                clip_dur = float(probe_r.stdout.strip())
        except Exception:
            pass
        encode_timeout = max(60, int(clip_dur * 10)) if clip_dur > 0 else 300

        cmd = [
            ffmpeg_path, "-y", "-i", clip_abspath,
            "-vf", vf_filter,
            *get_video_encode_args(crf=23, preset="superfast", force_software=True),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            norm_out
        ]
        try:
            r = _run_proc(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=encode_timeout)
        except subprocess.TimeoutExpired:
            log.warning(f"标准化转码单镜头超时({encode_timeout}s): {name}")
            raise _TranscodeSkip(f"注意： 转码超时，跳过: {name}")
        if r.returncode != 0:
            log.warning(f"标准化转码单镜头失败，跳过: {clip}\n{r.stderr[-300:]}")
            raise _TranscodeSkip(f"注意： 转码失败，跳过: {name}")
        return norm_out

    # ffmpeg xfade 转场类型映射
    _XFADE_MAP = {
        "fade": "fade",
        "dissolve": "dissolve",
        "slideleft": "slideleft",
        "slideright": "slideright",
        "slideup": "slideup",
        "slidedown": "slidedown",
        "zoomin": "zoomin",
        "zoomout": "zoomout",
    }
    # 单个 xfade filter_complex 中最多同时解码的镜头数。超过此值时拆分为多个
    # chunk 分别做 xfade，再用无损 concat 合并，避免镜头过多导致 filter graph
    # 过大、初始化缓慢甚至 ffmpeg 假死。
    _XFADE_CHUNK_SIZE = 12

    def _simple_concat(self, ffmpeg_path, clips, out_file, temp_dir, batch_idx):
        """无损 concat（无转场）。单镜头直接复制；多镜头走 concat demuxer。
        若启用 LUT，使用 filter_complex 给每个镜头做 lut3d 后 concat（需重编码）。
        """
        if not clips:
            return subprocess.CompletedProcess(args=[], returncode=1, stderr="no clips")

        lut_path = self.lut_path
        if lut_path and not os.path.isfile(lut_path):
            lut_path = ""

        if len(clips) == 1:
            if lut_path:
                lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
                vf = f"lut3d='{lut_esc}',format=yuv420p"
                self.stage.emit(f"单个镜头 LUT 还原（软件编码）...")
                cmd = [ffmpeg_path, "-y", "-i", clips[0], "-vf", vf,
                       *get_video_encode_args(crf=23, preset="superfast", force_software=True),
                       "-c:a", "aac", "-ar", "44100", "-ac", "2",
                       "-movflags", "+faststart", out_file]
            else:
                cmd = [ffmpeg_path, "-y", "-i", clips[0], "-c", "copy", out_file]
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)

        # 多镜头 + LUT：需要在 filter_complex 里逐个应用 lut3d 后 concat
        if lut_path:
            lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
            n = len(clips)
            video_parts = [f"[{i}:v]lut3d='{lut_esc}',format=yuv420p[v{i}];" for i in range(n)]
            concat_labels = "".join(f"[v{i}]" for i in range(n))
            audio_labels = "".join(f"[{i}:a]" for i in range(n))
            filter_complex = (
                "".join(video_parts) +
                f"{concat_labels}concat=n={n}:v=1:a=0[vout];" +
                f"{audio_labels}concat=n={n}:v=0:a=1[aout]"
            )
            cmd = [ffmpeg_path, "-y"] + [arg for i, clip in enumerate(clips) for arg in ("-i", clip)] + [
                "-filter_complex", filter_complex,
                "-map", "[vout]", "-map", "[aout]",
                *get_video_encode_args(crf=23, preset="superfast", force_software=True),
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                out_file
            ]
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)

        concat_txt = os.path.join(temp_dir, f"concat_simple_{batch_idx}_{os.getpid()}.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for c in clips:
                safe_path = c.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_file]
        return _run_proc(cmd, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def _run_xfade(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path):
        """对少量镜头直接构建 xfade 滤镜链拼接。超过 _XFADE_CHUNK_SIZE 的镜头应走
        _run_xfade_chunked 分块处理。
        """
        xfade_type = self._XFADE_MAP.get(self.transition, "fade")
        transition_dur = 0.5

        self.stage.emit(f"正在合成转场视频 ({len(clips)} 个镜头){'，LUT 已启用' if lut_path else ''}...")

        durations = []
        for clip in clips:
            dur = 0.0
            try:
                cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", clip]
                pr = _run_proc(cmd, capture_output=True, text=True, timeout=10,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
                if pr.returncode == 0 and pr.stdout.strip():
                    dur = float(pr.stdout.strip())
            except Exception:
                pass
            if dur <= 0:
                dur = 5.0
            durations.append(dur)

        n = len(clips)
        filter_parts = []
        inputs = []
        for clip in clips:
            inputs += ["-i", clip]

        if lut_path:
            lut_esc = lut_path.replace("\\", "/").replace(":", "\\:")
            for i in range(n):
                filter_parts.append(f"[{i}:v]lut3d='{lut_esc}',format=yuv420p[lut{i}];")

        if lut_path:
            prev_label = "lut0"
        else:
            prev_label = "0:v"
        accumulated = durations[0]
        for i in range(1, n):
            offset = max(0, accumulated - transition_dur)
            out_label = f"v{i:02d}"
            src_label = f"lut{i}" if lut_path else f"{i}:v"
            filter_parts.append(
                f"[{prev_label}][{src_label}]xfade=transition={xfade_type}:duration={transition_dur}:offset={offset:.3f}[{out_label}]"
            )
            prev_label = out_label
            accumulated = offset + transition_dur + (durations[i] - transition_dur)

        audio_filter_parts = []
        for i in range(n):
            audio_filter_parts.append(f"[{i}:a]")
        audio_filter_parts.append(f"concat=n={n}:v=0:a=1[aout]")
        audio_filter = "".join(audio_filter_parts)

        final_vlabel = prev_label
        filter_complex = ";".join(filter_parts) + ";" + audio_filter

        total_dur = sum(durations)
        timeout = max(120, int(total_dur * 3) + n * 20)

        cmd = [ffmpeg_path, "-y"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{final_vlabel}]",
            "-map", "[aout]",
            *get_video_encode_args(crf=23, preset="superfast", force_software=True),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out_file
        ]
        try:
            return _run_proc(cmd, capture_output=True, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning(f"xfade 拼接 {len(clips)} 个镜头超时({timeout}s)，输出文件未生成，准备降级")
            return subprocess.CompletedProcess(args=cmd, returncode=1,
                                               stderr=f"xfade timeout after {timeout}s")

    def _run_xfade_chunked(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path):
        """镜头数过多时拆块处理，每块内部做 xfade，最后无损 concat 合并各块。"""
        chunk_size = self._XFADE_CHUNK_SIZE
        chunks = [clips[i:i + chunk_size] for i in range(0, len(clips), chunk_size)]
        chunk_files = []
        for idx, chunk in enumerate(chunks):
            self.stage.emit(f"转场拼接分块 {idx + 1}/{len(chunks)} ({len(chunk)} 个镜头)...")
            chunk_out = os.path.join(temp_dir, f"chunk_{batch_idx}_{idx}_{os.getpid()}.mp4")
            r = self._run_xfade(ffmpeg_path, ffprobe_path, chunk, chunk_out, temp_dir,
                                f"{batch_idx}_{idx}", lut_path)
            if r.returncode != 0 or not os.path.isfile(chunk_out):
                log.warning(f"分块 {idx + 1} xfade 失败，该块改用无损 concat: {r.stderr[-200:]}")
                r2 = self._simple_concat(ffmpeg_path, chunk, chunk_out, temp_dir,
                                         f"{batch_idx}_{idx}_fallback")
                if r2.returncode != 0 or not os.path.isfile(chunk_out):
                    return subprocess.CompletedProcess(args=[], returncode=1,
                        stderr=f"chunk {idx} fallback concat failed: {r2.stderr}")
            chunk_files.append(chunk_out)

        return self._simple_concat(ffmpeg_path, chunk_files, out_file, temp_dir,
                                    f"chunked_{batch_idx}")

    def _concat_with_transition(self, ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx):
        """用 ffmpeg xfade 滤镜拼接镜头，实现转场动画。可选 LUT 色彩还原。

        注意：xfade 是复杂 CPU 滤镜，其输出像素格式/帧时序与硬件编码器（AMF/NVENC/QSV）
        配合时容易出现卡顿/假死。因此本阶段统一强制使用 libx264 软编，确保稳定性。
        当 LUT 启用时，也在 lut3d 后显式转 yuv420p，避免 10-bit/HDR 素材格式不兼容。
        为避免镜头数过多时 filter graph 过大导致初始化/编码假死，超过阈值会自动分块；
        若用户选择"无转场"或 xfade 超时/失败，自动降级为无损 concat。
        """
        if not clips:
            return subprocess.CompletedProcess(args=[], returncode=1, stderr="no clips")

        # 读取 LUT 配置
        lut_path = self.lut_path
        if lut_path and not os.path.isfile(lut_path):
            log.warning(f"[LUT] 文件不存在，跳过: {lut_path}")
            lut_path = ""
        if lut_path:
            log.info(f"[LUT] 应用色彩还原: {os.path.basename(lut_path)}")

        # 无转场 / 单镜头：直接走无损 concat
        if self.transition == "none" or len(clips) <= 1:
            return self._simple_concat(ffmpeg_path, clips, out_file, temp_dir, batch_idx)

        # 镜头数在阈值内：直接 xfade；超过阈值：分块 xfade
        if len(clips) <= self._XFADE_CHUNK_SIZE:
            return self._run_xfade(ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path)
        return self._run_xfade_chunked(ffmpeg_path, ffprobe_path, clips, out_file, temp_dir, batch_idx, lut_path)

    def _compose_beat_video(self, ffmpeg_path, norm_clips, out_file, temp_dir):
        """音乐卡点合成：每个镜头裁剪到对应节拍区间时长，硬切拼接（保证卡点精准），
        再叠加裁剪后的音乐片段（替换原声）。

        beat_times: 相对裁剪后音频的节拍点（第一个为 0），相邻节拍形成一个镜头槽位。
        music_range: [起始秒, 结束秒] 绝对时间，从原音乐裁剪出对应片段。
        """
        beats = self.beat_times
        n_slots = max(0, len(beats) - 1)
        if n_slots <= 0 or not norm_clips:
            raise RuntimeError("卡点合成失败：节拍点或镜头为空")

        # 镜头数与槽位数对齐（不足循环填充，多余截断）
        seq = []
        for i in range(n_slots):
            seq.append(norm_clips[i % len(norm_clips)])

        # 1) 每个镜头裁剪到节拍区间时长（硬切，不加转场以保证卡点精准）
        cut_paths = []
        total_dur = 0.0
        for i in range(n_slots):
            dur = max(0.1, beats[i + 1] - beats[i])
            src = seq[i]
            cut = os.path.join(temp_dir, f"beatcut_{i:04d}.mp4")
            cmd = [ffmpeg_path, "-y", "-i", src,
                   "-t", f"{dur:.3f}",
                   "-an",  # 去除原声，后续统一叠加音乐
                   *get_video_encode_args(crf=20, preset="veryfast"),
                   "-pix_fmt", "yuv420p",
                   cut]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0 or not os.path.isfile(cut):
                log.warning(f"卡点裁剪镜头失败: {r.stderr[-200:]}")
                raise RuntimeError(f"卡点裁剪第 {i+1} 个镜头失败")
            cut_paths.append(cut)
            total_dur += dur

        # 2) concat 拼接（硬切）
        concat_txt = os.path.join(temp_dir, "beat_concat.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for c in cut_paths:
                f.write(f"file '{c.replace(chr(92), '/')}'\n")
        noaudio = os.path.join(temp_dir, "beat_noaudio.mp4")
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
               "-c", "copy", noaudio]
        r = _run_proc(cmd, capture_output=True, text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(noaudio):
            raise RuntimeError(f"卡点拼接失败：{(r.stderr or '')[-200:]}")

        # 3) 叠加裁剪后的音乐片段（替换原声）
        if self.music_path and os.path.isfile(self.music_path):
            m_start = float(self.music_range[0]) if len(self.music_range) >= 1 else 0.0
            m_end = float(self.music_range[1]) if len(self.music_range) >= 2 else 0.0
            m_dur = max(0.1, m_end - m_start) if m_end > m_start else total_dur
            cmd = [ffmpeg_path, "-y",
                   "-i", noaudio,
                   "-ss", f"{m_start:.3f}", "-t", f"{m_dur:.3f}", "-i", self.music_path,
                   "-map", "0:v:0", "-map", "1:a:0",
                   "-c:v", "copy", "-c:a", "aac", "-shortest",
                   out_file]
            r = _run_proc(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0 or not os.path.isfile(out_file):
                log.warning(f"卡点叠加音乐失败，输出无音乐版本: {(r.stderr or '')[-200:]}")
                shutil.copyfile(noaudio, out_file)
        else:
            shutil.copyfile(noaudio, out_file)
        return out_file

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            from utils.platform_utils import find_ffprobe
            ffprobe_path = find_ffprobe()
            if not os.path.isfile(ffprobe_path):
                ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

            if not self.selected_clips:
                raise RuntimeError("未选择任何镜头素材。")

            self.stage.emit("准备标准化转码工作...")
            self.progress.emit(5)

            # Establish temp working dir inside output_dir
            temp_dir = os.path.join(self.output_dir, ".temp_concat")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)

            if self.layout_mode == "vertical":
                width, height = 1080, 1920
            elif self.layout_mode == "horizontal":
                width, height = 1920, 1080
            else:  # "source": 与原视频一致，取第一个素材的分辨率
                res = self._probe_resolution(self.selected_clips[0])
                if res:
                    width, height = res
                    width -= width % 2      # 保证为偶数，libx264 要求
                    height -= height % 2
                    self.stage.emit(f"输出画幅与原视频一致：{width}x{height}")
                else:
                    width, height = 1080, 1920  # 探测失败回退竖屏

            # Step 1: Transcode all selected candidate clips once to temporary folder
            # 并行转码：每个镜头输出独立文件 (norm_{i:04d}.mp4)，互不冲突；
            # 完成后按 i 排序重组，保证拼接顺序与串行版完全一致。
            normalized_list = []
            norm_to_desc = {}
            skipped_clips = []
            total_clips = len(self.selected_clips)
            # 转码是 ffmpeg 子进程密集型，并发数取 CPU 核心数，上限 8
            # （ffmpeg libx264 自身已多线程，过多并发反而争抢 CPU/磁盘）
            max_workers = max(2, min(8, os.cpu_count() or 4))
            transcode_args = (ffmpeg_path, ffprobe_path, temp_dir, width, height)
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers,
                                    thread_name_prefix="norm") as pool:
                future_to_meta = {
                    pool.submit(self._transcode_one, i, clip, *transcode_args): (i, clip)
                    for i, clip in enumerate(self.selected_clips)
                }
                done_count = 0
                for fut in as_completed(future_to_meta):
                    i, clip = future_to_meta[fut]
                    try:
                        norm_out = fut.result()
                    except _TranscodeSkip as e:
                        skipped_clips.append(clip)
                        self.stage.emit(str(e))
                        norm_out = None
                    except Exception as e:
                        # 未预期错误也按跳过处理，避免整个合成失败
                        log.warning(f"标准化转码异常，跳过: {clip}\n{e}", exc_info=True)
                        skipped_clips.append(clip)
                        self.stage.emit(f"注意： 转码失败，跳过: {os.path.basename(clip)}")
                        norm_out = None

                    if norm_out:
                        normalized_list.append((i, norm_out))
                        if self.selected_descriptions_list is not None and i < len(self.selected_descriptions_list):
                            norm_to_desc[norm_out] = self.selected_descriptions_list[i]
                        else:
                            norm_to_desc[norm_out] = self.split_descriptions.get(os.path.abspath(clip), "")

                    done_count += 1
                    self.stage.emit(f"标准化转码进度 {done_count}/{total_clips}")
                    prog = 10 + int(done_count / total_clips * 70)
                    self.progress.emit(prog)

            # 按原始下标 i 排序，恢复与串行版一致的拼接顺序
            normalized_list.sort(key=lambda t: t[0])
            normalized_list = [p for _, p in normalized_list]

            if not normalized_list:
                raise RuntimeError("所有镜头文件均损坏或转码失败，无法合成视频。请重新进行镜头分割。")
            if skipped_clips:
                self.stage.emit(f"注意： 共跳过 {len(skipped_clips)} 个损坏文件，继续合成剩余 {len(normalized_list)} 个镜头")

            # ── 音乐卡点模式：按节拍裁剪镜头 + 叠加音乐片段，生成单个卡点视频 ──
            if self.recombine_mode == "beat" and self.beat_times:
                self.stage.emit(" 正在按音乐节拍合成卡点视频...")
                out_file = os.path.join(
                    self.output_dir, f"montage_beat_{random.randint(1000, 9999)}.mp4")
                self._compose_beat_video(ffmpeg_path, normalized_list, out_file, temp_dir)
                # 保存源镜头列表
                try:
                    sources_file = os.path.splitext(out_file)[0] + "_sources.txt"
                    with open(sources_file, "w", encoding="utf-8") as sf:
                        for src in self.selected_clips:
                            sf.write(src + "\n")
                except Exception as e:
                    log.warning(f"保存卡点视频源镜头列表失败: {e}")
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
                self.stage.emit(" 音乐卡点视频合成完成！")
                self.progress.emit(100)
                self.finished.emit([out_file])
                return

            # Step 2: Batch generate fast concatenations
            generated_paths = []
            for batch_idx in range(self.batch_count):
                self.stage.emit(f"无损拼接第 {batch_idx+1}/{self.batch_count} 个视频...")
                
                batch_clips = list(normalized_list)
                if self.recombine_mode == "random":
                    if self.randomness == "high":
                        random.shuffle(batch_clips)
                    elif self.randomness == "medium":
                        # Group consecutive clips with same description
                        groups = []
                        current_group = []
                        current_desc = None
                        for n_clip in batch_clips:
                            desc = norm_to_desc.get(n_clip, "").strip()
                            if not current_group:
                                current_group.append(n_clip)
                                current_desc = desc
                            else:
                                if desc == current_desc and desc != "":
                                    current_group.append(n_clip)
                                else:
                                    groups.append(current_group)
                                    current_group = [n_clip]
                                    current_desc = desc
                        if current_group:
                            groups.append(current_group)
                        
                        # Shuffle the groups
                        random.shuffle(groups)
                        # Flatten
                        batch_clips = [c for group in groups for c in group]
                    elif self.randomness == "low":
                        # Low randomness = no shuffling, keep sequential order
                        pass
                
                if len(batch_clips) > self.target_clip_count:
                    batch_clips = batch_clips[:self.target_clip_count]
                elif len(batch_clips) < self.target_clip_count:
                    extra_needed = self.target_clip_count - len(batch_clips)
                    for _ in range(extra_needed):
                        batch_clips.append(random.choice(normalized_list))
                
                out_file = os.path.join(self.output_dir, f"montage_concat_{random.randint(1000, 9999)}_{batch_idx+1}.mp4")

                # 使用 xfade 滤镜实现转场动画（非 copy 模式，需要重新编码）
                r = self._concat_with_transition(ffmpeg_path, ffprobe_path, batch_clips, out_file, temp_dir, batch_idx)
                if r.returncode != 0:
                    # 转场拼接失败，回退到无损 concat
                    log.warning(f"转场拼接失败，回退到普通拼接: {r.stderr[-200:]}")
                    concat_txt = os.path.join(temp_dir, f"concat_{batch_idx}.txt")
                    with open(concat_txt, "w", encoding="utf-8") as f:
                        for n_clip in batch_clips:
                            safe_path = n_clip.replace("\\", "/")
                            f.write(f"file '{safe_path}'\n")
                    cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", out_file]
                    r = _run_proc(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    if r.returncode != 0:
                        raise RuntimeError(f"拼接第 {batch_idx+1} 个视频失败：\n{r.stderr}")
                
                # 注：不再在合成视频时把画面描述拼接写入 .txt。
                # 该 .txt 是「口播文案」专属文件，只有用户点「生成口播文案」按钮由 AI 生成后才填充。
                # 画面描述已保存在内存 split_descriptions/split_clips_cache + _sources.txt 中，
                # 生成口播文案时由 _get_video_scene_descriptions 正常读取，不受影响。

                # Save the list of original source clips that make up this generated video
                sources_file = os.path.splitext(out_file)[0] + "_sources.txt"
                try:
                    original_sources = []
                    for n_clip in batch_clips:
                        filename = os.path.basename(n_clip)
                        if filename.startswith("norm_") and filename.endswith(".mp4"):
                            try:
                                idx = int(filename.split("_")[1].split(".")[0])
                                if 0 <= idx < len(self.selected_clips):
                                    original_sources.append(self.selected_clips[idx])
                            except Exception:
                                pass
                    with open(sources_file, "w", encoding="utf-8") as sf:
                        for src in original_sources:
                            sf.write(src + "\n")
                except Exception as e:
                    log.warning(f"保存视频源镜头列表失败: {e}")

                generated_paths.append(out_file)
                self.progress.emit(80 + int((batch_idx + 1) / self.batch_count * 20))

            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

            self.stage.emit(f"批量拼接完成，共生成 {self.batch_count} 个视频！")
            self.progress.emit(100)
            self.finished.emit(generated_paths)

        except Exception:
            log.exception("批量拼接合并失败")
            self.error.emit(traceback.format_exc())



class FinalMixWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # Returns a list of final video paths

    def __init__(self, tasks, bgm_path, bgm_volume):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, output_path)
        self.bgm_path = bgm_path
        self.bgm_volume = bgm_volume

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            creationflags = subprocess.CREATE_NO_WINDOW
            has_bgm = bool(self.bgm_path and os.path.exists(self.bgm_path))
            bgm_vol = self.bgm_volume / 100.0
            
            results = []
            total = len(self.tasks)
            
            for index, (video_path, output_path) in enumerate(self.tasks):
                self.stage.emit(f"正在进行最终合成配乐 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                if has_bgm:
                    # Check if the input video has an audio stream
                    has_audio = False
                    try:
                        ffprobe_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "csv=p=0", video_path
                        ]
                        p_probe = _run_proc(ffprobe_cmd, capture_output=True, text=True, creationflags=creationflags)
                        if "audio" in p_probe.stdout:
                            has_audio = True
                    except Exception:
                        has_audio = True

                    # BGM 淡入淡出：开头 1s 淡入，结尾 2s 淡出（按视频时长定位）
                    vid_dur = get_media_duration(video_path)
                    fade_out_start = max(0.0, vid_dur - 2.0)
                    bgm_fades = f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start:.3f}:d=2.0" if vid_dur > 0 else "afade=t=in:st=0:d=1.0"

                    if has_audio:
                        # 人声闪避（sidechain ducking）：BGM 在人声出现时自动压低，
                        # 人声停顿时回升；最终 loudnorm 统一响度（EBU R128 -16 LUFS）。
                        filter_complex = (
                            f"[0:a]asplit=2[vo][sc];"
                            f"[1:a]volume={bgm_vol},{bgm_fades}[bg];"
                            f"[bg][sc]sidechaincompress=threshold=0.05:ratio=8:attack=50:release=400[duck];"
                            f"[vo][duck]amix=inputs=2:duration=first:normalize=0,"
                            f"loudnorm=I=-16:TP=-1.5:LRA=11[a]"
                        )
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", filter_complex,
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                    else:
                        cmd = [
                            ffmpeg_path, "-y", "-i", video_path,
                            "-stream_loop", "-1", "-i", self.bgm_path,
                            "-filter_complex", f"[1:a]volume={bgm_vol},{bgm_fades},loudnorm=I=-16:TP=-1.5:LRA=11[bgm]",
                            "-map", "0:v", "-map", "[bgm]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            output_path
                        ]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-c", "copy",
                        output_path
                    ]
                
                r = _run_proc(cmd, capture_output=True, text=True, creationflags=creationflags)
                if r.returncode != 0:
                    raise RuntimeError(f"最后合成视频失败：\n{r.stderr}")
                    
                results.append(output_path)
                
            self.stage.emit("所有视频及配乐最终合成完成！")
            self.progress.emit(100)
            self.finished.emit(results)
            
        except Exception:
            log.exception("最终合成失败")
            self.error.emit(traceback.format_exc())



class VideoDubbingWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(dict)  # Outputs a dict mapping: original_video_path -> dubbed_video_path

    def __init__(self, tasks, add_subtitles=True, length_modes=None,
                 fancy_text=False, fancy_style="gold", fancy_words=None):
        super().__init__()
        self.tasks = tasks  # list of tuples: (video_path, voice_wav_path, output_video_path, text)
        self.add_subtitles = add_subtitles
        self.length_modes = length_modes or {}  # video_path -> "video" or "audio"
        self.fancy_text = fancy_text
        self.fancy_style = fancy_style
        self.fancy_words = fancy_words or []  # list of strings to overlay

    @staticmethod
    def _load_timing_sidecar(voice_wav_path):
        """读取逐句 TTS 生成的句级时间轴（.timing.json）；无效则返回 None。"""
        import json as _json
        p = (voice_wav_path or "") + ".timing.json"
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                timing = _json.load(f)
            if (isinstance(timing, list) and timing
                    and all(isinstance(t, dict) and t.get("text") for t in timing)):
                return timing
        except Exception:
            pass
        return None

    def run(self):
        try:
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            results = {}
            total = len(self.tasks)
            
            for index, (video_path, voice_wav_path, output_video_path, text) in enumerate(self.tasks):
                self.stage.emit(f"正在进行视频原声替换配音 ({index + 1}/{total})...")
                self.progress.emit(int(index / total * 100))
                
                os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

                length_mode = self.length_modes.get(video_path, "video")
                video_dur = get_media_duration(video_path)
                audio_dur = get_media_duration(voice_wav_path)
                use_audio_length = (length_mode == "audio" and audio_dur > video_dur > 0)
                extra_dur = audio_dur - video_dur if use_audio_length else 0.0
                display_dur = audio_dur if use_audio_length else video_dur

                # Build video filter chain
                video_filters = []
                video_label = "0:v"
                audio_label = "1:a:0"
                need_audio_speed = (not use_audio_length and audio_dur > video_dur > 0)

                if use_audio_length:
                    # Extend video with last frame clone to match audio length
                    video_filters.append(f"[{video_label}]tpad=stop_mode=clone:stop_duration={extra_dur:.3f}[v_padded]")
                    video_label = "v_padded"

                if self.add_subtitles and text:
                    # Resolve Microsoft YaHei font path on Windows
                    font_path = "C\\:/Windows/Fonts/msyh.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
                        font_path = "msyh"

                    # 优先使用逐句 TTS 的真实句级时间轴（字幕与语音精确同步）
                    timing = self._load_timing_sidecar(voice_wav_path)
                    if timing:
                        raw_lines = [str(t["text"]).strip() for t in timing]
                        line_starts = [float(t.get("start", 0)) for t in timing]
                        line_ends = [float(t.get("end", 0)) for t in timing]
                        # 本步骤内音频被 atempo 加速对齐视频时 → 时间轴按同比例缩放
                        if need_audio_speed and audio_dur > 0:
                            f_scale = video_dur / audio_dur
                            line_starts = [s * f_scale for s in line_starts]
                            line_ends = [e * f_scale for e in line_ends]
                        if display_dur > 0:
                            line_ends = [min(e, display_dur) for e in line_ends]
                    else:
                        # 回退：无时间轴时按字数比例估算（旧行为）
                        raw_lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                        if not raw_lines:
                            raw_lines = [text.strip()]
                        char_counts = [max(1, len(line)) for line in raw_lines]
                        total_chars = sum(char_counts)
                        cum_t = 0.0
                        line_starts, line_ends = [], []
                        for c in char_counts:
                            t0 = cum_t
                            t1 = cum_t + (display_dur * c / total_chars if display_dur > 0 else 5.0)
                            line_starts.append(t0)
                            line_ends.append(t1)
                            cum_t = t1

                    # Build drawtext filters
                    drawtexts = []
                    for i, line_text in enumerate(raw_lines):
                        start_t = line_starts[i]
                        end_t = line_ends[i]
                        escaped = line_text.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')
                        dt = (
                            f"drawtext=fontfile='{font_path}':"
                            f"text='{escaped}':"
                            f"fontsize=h*0.025:fontcolor=white:"
                            f"box=1:boxcolor=black@0.5:boxborderw=6:"
                            f"x=(w-text_w)/2:y=h-text_h-h*0.06:"
                            f"enable='between(t,{start_t:.3f},{end_t:.3f})'"
                        )
                        drawtexts.append(dt)
                    video_filters.append(f"[{video_label}]{','.join(drawtexts)}[v]")
                    video_label = "v"

                # 花字叠加（关键信息加重提醒，大号彩色描边特效文字）
                if self.fancy_text and self.fancy_words and display_dur > 0:
                    font_path = "C\\:/Windows/Fonts/msyhbd.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
                        font_path = "C\\:/Windows/Fonts/msyh.ttc"
                    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
                        font_path = "msyh"

                    # 花字样式预设：fontcolor + borderw + bordercolor + shadow
                    fancy_styles = {
                        "gold":          "fontcolor=0xF0C040:borderw=4:bordercolor=0x6B3000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "red":           "fontcolor=0xFF4040:borderw=4:bordercolor=0x800000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "blue":          "fontcolor=0x40A0FF:borderw=4:bordercolor=0x003080:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "purple":        "fontcolor=0xC060FF:borderw=4:bordercolor=0x300060:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                        "neon_green":    "fontcolor=0x40FF80:borderw=3:bordercolor=0x004020:shadowx=3:shadowy=3:shadowcolor=0x00FF80@0.5",
                        "white_outline": "fontcolor=white:borderw=5:bordercolor=black:shadowx=2:shadowy=2:shadowcolor=0x000000@0.6",
                        "yellow_red":    "fontcolor=0xFFFF00:borderw=5:bordercolor=0xCC0000:shadowx=2:shadowy=2:shadowcolor=0x000000@0.8",
                    }
                    style_str = fancy_styles.get(self.fancy_style, fancy_styles["gold"])

                    fancy_drawtexts = []
                    # 每个花字在整个视频时长内均匀分布轮换显示
                    n_words = len(self.fancy_words)
                    if n_words > 0:
                        seg_dur = display_dur / n_words
                        for wi, word in enumerate(self.fancy_words):
                            word = word.strip()
                            if not word:
                                continue
                            ft_start = wi * seg_dur
                            ft_end = min((wi + 1) * seg_dur, display_dur)
                            escaped = word.replace('\\', '\\\\').replace("'", "'\\\\''").replace(':', '\\:').replace(',', '\\,')
                            # 花字：大号字体，居中偏上，带描边和阴影
                            dt = (
                                f"drawtext=fontfile='{font_path}':"
                                f"text='{escaped}':"
                                f"fontsize=h*0.08:{style_str}:"
                                f"x=(w-text_w)/2:y=h*0.3:"
                                f"enable='between(t,{ft_start:.3f},{ft_end:.3f})'"
                            )
                            fancy_drawtexts.append(dt)
                    if fancy_drawtexts:
                        video_filters.append(f"[{video_label}]{','.join(fancy_drawtexts)}[vf]")
                        video_label = "vf"

                if need_audio_speed:
                    # Speed up audio to match video duration using atempo chain
                    ratio = audio_dur / video_dur
                    atempo_parts = []
                    remaining = ratio
                    while remaining > 2.0:
                        atempo_parts.append("atempo=2.0")
                        remaining /= 2.0
                    if remaining < 0.5:
                        atempo_parts.append(f"atempo=0.5")
                        remaining /= 0.5
                    if abs(remaining - 1.0) > 0.001:
                        atempo_parts.append(f"atempo={remaining:.4f}")
                    if atempo_parts:
                        if video_filters:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")
                            audio_label = "a"
                        else:
                            video_filters.append(f"[{audio_label}]{','.join(atempo_parts)}[a]")
                            audio_label = "a"
                            # Need a dummy video pass-through so filter_complex can map both
                            video_filters.insert(0, f"[{video_label}]null[v]")
                            video_label = "v"

                if video_filters:
                    filter_complex = ";".join(video_filters)
                    audio_map = f"[{audio_label}]" if audio_label == "a" else audio_label
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                        "-filter_complex", filter_complex,
                        "-map", f"[{video_label}]", "-map", audio_map,
                        *get_video_encode_args(crf=23, preset="superfast"), "-c:a", "aac",
                    ]
                    # "以声音为准"时严格裁剪输出到音频时长：
                    #   audio > video → tpad 已把视频延长到 audio_dur，-t 再确认一次（无害）
                    #   audio < video → tpad 未触发，必须靠 -t 裁掉多余的视频
                    if length_mode == "audio" and audio_dur > 0:
                        cmd += ["-t", f"{audio_dur:.3f}"]
                else:
                    cmd = [
                        ffmpeg_path, "-y", "-i", video_path,
                        "-i", voice_wav_path,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                    ]
                cmd.append(output_video_path)
                
                r = _run_proc(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode != 0:
                    err = r.stderr or r.stdout or "(无输出)"
                    raise RuntimeError(f"视频原声替换配音失败：\n{err}\n命令: {' '.join(cmd)}")
                    
                results[video_path] = output_video_path
                
            self.stage.emit("所有视频替换配音完成！")
            self.progress.emit(100)
            self.finished.emit(results)
            
        except Exception:
            log.exception("视频替换配音失败")
            self.error.emit(traceback.format_exc())
