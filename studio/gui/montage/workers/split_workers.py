# -*- coding: utf-8 -*-
"""智能混剪 - 分割阶段 Worker：场景检测、挑精华、镜头评分。"""
import os
import subprocess
import traceback
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.api_error import ApiError
from utils.hwaccel import get_video_encode_args
from gui.montage.utils_media import find_ffmpeg, format_seconds_to_srt_timestamp



class PySceneDetectWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    busy = Signal(bool)
    finished = Signal(str, int, list)  # Output directory, number of scenes, list of (start_sec, end_sec)

    def __init__(self, video_path, output_dir, threshold, min_scene_len):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.threshold = threshold
        self.min_scene_len = min_scene_len

    def run(self):
        try:
            self.stage.emit("正在检查 PySceneDetect 环境")
            self.progress.emit(10)
            self.busy.emit(True)

            try:
                from scenedetect import open_video, SceneManager, split_video_ffmpeg
                from scenedetect.detectors import ContentDetector
            except ImportError:
                raise RuntimeError("未检测到 scenedetect 依赖。")

            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path:
                raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或将其加入环境变量 PATH。")

            # Setup ffmpeg environment for scenedetect
            if os.path.isfile(ffmpeg_path):
                ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_path))
                if ffmpeg_dir not in os.environ["PATH"]:
                    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
                try:
                    import scenedetect.output.video
                    scenedetect.output.video._FFMPEG_PATH = ffmpeg_path
                except Exception as e:
                    log.warning(f"无法为 scenedetect 设置 _FFMPEG_PATH: {e}")

            self.stage.emit("正在分析镜头切点...")
            self.progress.emit(30)

            # 打开视频并进行场景检测
            video = open_video(self.video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=self.threshold, min_scene_len=self.min_scene_len))
            scene_manager.detect_scenes(video, show_progress=False)
            scene_list = scene_manager.get_scene_list()

            if not scene_list:
                self.stage.emit("未检测到明显的镜头切点")
                self.progress.emit(100)
                self.finished.emit(self.output_dir, 0, [])
                return

            self.stage.emit(f"检测到 {len(scene_list)} 个镜头，正在分割输出...")
            self.progress.emit(60)

            os.makedirs(self.output_dir, exist_ok=True)
            video_basename = os.path.splitext(os.path.basename(self.video_path))[0]
            output_template = f"{video_basename}_shot_$SCENE_NUMBER.mp4"

            # 调用 PySceneDetect 进行分段视频导出
            split_video_ffmpeg(
                self.video_path,
                scene_list,
                output_dir=self.output_dir,
                output_file_template=output_template,
                show_progress=False
            )

            # 验证输出文件是否生成，防止 ffmpeg 调用失败无输出却显示成功
            created_files = []
            if os.path.exists(self.output_dir):
                created_files = [f for f in os.listdir(self.output_dir) if f.lower().endswith(".mp4")]
            
            if not created_files:
                raise RuntimeError(
                    "未能生成分割后的镜头视频文件。请检查 ffmpeg 是否工作正常。\n"
                    "也可以尝试将 ffmpeg.exe 复制到软件根目录下。"
                )

            scenes_sec = [(s[0].get_seconds(), s[1].get_seconds()) for s in scene_list]
            self.stage.emit("分割导出完成")
            self.progress.emit(100)
            self.finished.emit(self.output_dir, len(scene_list), scenes_sec)

        except Exception:
            self.busy.emit(False)
            log.exception("镜头分割失败")
            self.error.emit(traceback.format_exc())



class ServerSplitWorker(BaseWorker):
    """服务端镜头分割 + 逐镜分析（POST /montage/split，分割+分析合并接口）。

    与 PySceneDetectWorker 同信号契约：
        finished(output_dir, scene_count, [(start_sec, end_sec), ...])
    新增：
        analysis_ready(list)  # [{filename, shot_index, aesthetic_score, shot_analysis, description}, ...]

    素材来源三选一（服务端解析）：
        - video_path：本地视频/图片文件（传 file，视频做分割、图片转静态镜头）
        - material_id：素材库素材 id（传 material_id）
        - clip_url：素材地址（material://{id} / http(s)://... / 本地路径）

    片段由服务端裁好，通过 shots[].download_url 下载到 output_dir（文件名保持
    {源名}_shot_{序号:03d}.mp4，与 _rename_video_splits_with_metadata 期望的 _shot_ 前缀一致）；
    下载失败时若有本地源文件则回退本地 ffmpeg 按 start/end 重裁，否则该镜跳过。
    """

    stage = Signal(str)
    progress = Signal(int)
    busy = Signal(bool)
    finished = Signal(str, int, list)
    analysis_ready = Signal(list)

    def __init__(self, video_path=None, output_dir="", threshold=27, min_scene_len=0.5,
                 server_url=None, material_id="", clip_url="", product_mode=False,
                 image_duration=3.0, analyze=True):
        super().__init__()
        self.video_path = video_path or ""
        self.output_dir = output_dir
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        self.server_url = (server_url or "").strip().rstrip("/")
        self.material_id = (material_id or "").strip()
        self.clip_url = (clip_url or "").strip()
        self.product_mode = product_mode
        self.image_duration = image_duration
        self.analyze = analyze
        self.shot_meta = []  # 逐镜分析结果（finished 之后 analysis_ready emit）

    def _local_cut(self, start, end, out):
        """本地 ffmpeg 按起止时间重裁（download_url 下载失败时的兜底）。"""
        ffmpeg = find_ffmpeg()
        if not ffmpeg or not self.video_path or not os.path.isfile(self.video_path):
            return False
        flags = 0x08000000 if os.name == "nt" else 0
        cmd = [ffmpeg, "-y", "-ss", str(start), "-to", str(end),
               "-i", self.video_path, "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", out]
        r2 = subprocess.run(cmd, capture_output=True, creationflags=flags)
        return os.path.isfile(out) and os.path.getsize(out) > 0

    def run(self):
        try:
            self.stage.emit("正在调用服务端镜头分割（分割+逐镜分析）…")
            self.progress.emit(10)
            self.busy.emit(True)

            if not self.server_url:
                from utils import scheduled_task_client as _stc
                self.server_url = _stc._server_url()
            if not self.server_url:
                raise RuntimeError("未配置 compute_server_url")

            from utils.http_client import http_get, http_post
            os.makedirs(self.output_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(self.video_path))[0] if self.video_path else ""
            data = {
                "threshold": str(self.threshold),
                "min_scene_len": str(self.min_scene_len),
                "analyze": "true" if self.analyze else "false",
                "product_mode": "true" if self.product_mode else "false",
                "image_duration": str(self.image_duration),
            }
            files = None
            if self.material_id:
                data["material_id"] = self.material_id
            elif self.clip_url:
                data["clip_url"] = self.clip_url
            elif self.video_path and os.path.isfile(self.video_path):
                # 按扩展名设置 mime：图片也可作为静态镜头上传
                _ext = os.path.splitext(self.video_path)[1].lower()
                _mime = {".mp4": "video/mp4", ".m4v": "video/m4v", ".mov": "video/quicktime",
                         ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
                         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                         ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}.get(_ext, "video/mp4")
                files = {"file": (os.path.basename(self.video_path), open(self.video_path, "rb"), _mime)}
            else:
                raise RuntimeError("没有可分割的素材（需 file / material_id / clip_url 之一）")

            try:
                r = http_post(f"{self.server_url}/montage/split", files=files, data=data, timeout=600)
            finally:
                if files:
                    try:
                        files["file"][1].close()
                    except Exception:
                        pass
            if r.status_code != 200:
                raise RuntimeError(f"服务端分割返回 {r.status_code}: {r.text[:200]}")

            resp = r.json() or {}
            shots = resp.get("shots") or []
            if not shots:
                self.stage.emit("服务端未检测到镜头切点")
                self.progress.emit(100)
                self.finished.emit(self.output_dir, 0, [])
                self.analysis_ready.emit([])
                return

            self.progress.emit(50)
            self.stage.emit(f"服务端检测到 {len(shots)} 个镜头，正在下载服务端裁好的片段…")
            self.shot_meta = []
            scenes = []
            created = 0
            for sh in shots:
                start = float(sh.get("start_sec") or 0)
                end = float(sh.get("end_sec") or start)
                idx = int(sh.get("shot_index") or (created + 1))
                # 文件名保持 {源名}_shot_{序号:03d}.mp4（优先用服务端返回的 filename）
                fname = sh.get("filename") or f"{base}_shot_{idx:03d}.mp4"
                out = os.path.join(self.output_dir, os.path.basename(fname))
                ok = False
                dl_url = sh.get("download_url") or ""
                if dl_url:
                    try:
                        r = http_get(self.server_url + dl_url, stream=True, timeout=300)
                        r.raise_for_status()
                        with open(out, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        ok = os.path.isfile(out) and os.path.getsize(out) > 0
                        if not ok:
                            log.warning(f"[服务端分割] 下载片段为空: {out}")
                    except Exception as e:
                        log.warning(f"[服务端分割] 下载片段失败({fname}): {e}")
                if not ok:
                    log.warning(f"[服务端分割] 下载失败，回退本地重裁: {fname}")
                    ok = self._local_cut(start, end, out)
                if ok:
                    scenes.append((start, end))
                    created += 1
                    self.shot_meta.append({
                        "filename": os.path.basename(out),
                        "shot_index": idx,
                        "aesthetic_score": sh.get("aesthetic_score"),
                        "shot_analysis": sh.get("shot_analysis"),
                        "description": sh.get("description") or "",
                    })
                else:
                    log.warning(f"[服务端分割] 片段生成失败，跳过: {fname}")
            if not created:
                raise RuntimeError("服务端分割返回镜头但片段获取失败，请检查网络/ffmpeg")

            self.progress.emit(100)
            self.stage.emit("分割导出完成（服务端分割+分析，片段已下载）")
            self.finished.emit(self.output_dir, created, scenes)
            self.analysis_ready.emit(list(self.shot_meta))
        except Exception:
            self.busy.emit(False)
            log.exception("服务端镜头分割失败")
            self.error.emit(traceback.format_exc())


class BestClipWorker(BaseWorker):
    """从整段视频里挑出"比较好的 N 秒"（清晰+适度运动），裁剪成单个片段。

    评分：对画面按约 3fps 抽样，计算锐度(Laplacian 方差)与相邻帧运动量，
    归一化后 score = 0.6*锐度 + 0.4*运动，过暗/过曝帧扣分；
    滑动 N 秒窗口取平均分最高的一段。
    """
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(str, float, float)  # 输出片段路径, 起始秒, 结束秒

    def __init__(self, video_path, output_dir, duration_sec, shot_index=1, clear_dir=False):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.duration_sec = float(duration_sec)
        self.shot_index = int(shot_index)
        self.clear_dir = clear_dir

    def run(self):
        try:
            self.stage.emit("正在分析画面，挑选精华片段...")
            self.progress.emit(10)
            start, end = self._find_best_window()
            self.progress.emit(60)
            out_path = self._cut(start, end)
            self.progress.emit(100)
            self.finished.emit(out_path, start, end)
        except Exception:
            self.error.emit(traceback.format_exc())

    def _find_best_window(self):
        import cv2
        import numpy as np
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError("无法打开视频文件")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if fps <= 0 or fps > 1000:
            fps = 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_dur = total / fps if total > 0 else 0.0

        # 视频比目标时长还短：直接用整段
        if total <= 0 or video_dur <= self.duration_sec:
            cap.release()
            return 0.0, (video_dur if video_dur > 0 else self.duration_sec)

        sample_fps = 3.0
        step = max(1, int(round(fps / sample_fps)))
        times, sharp_l, motion_l, bright_l = [], [], [], []
        prev_gray = None
        i = 0
        while True:
            if not cap.grab():
                break
            if i % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if w > 320:
                    nh = max(1, int(h * 320 / w))
                    frame = cv2.resize(frame, (320, nh))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                bright = float(gray.mean())
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    motion = float(np.mean(cv2.absdiff(gray, prev_gray)))
                else:
                    motion = 0.0
                prev_gray = gray
                times.append(i / fps)
                sharp_l.append(sharp)
                motion_l.append(motion)
                bright_l.append(bright)
            i += 1
        cap.release()

        if not times:
            return 0.0, self.duration_sec

        sharp_a = np.array(sharp_l)
        motion_a = np.array(motion_l)
        bright_a = np.array(bright_l)
        times_a = np.array(times)

        def _norm(a):
            mn, mx = float(a.min()), float(a.max())
            return (a - mn) / (mx - mn) if mx > mn else np.zeros_like(a)

        score = 0.6 * _norm(sharp_a) + 0.4 * _norm(motion_a)
        # 过暗/过曝惩罚
        score = score - np.where((bright_a < 40) | (bright_a > 225), 0.5, 0.0)

        last_start = max(0.0, video_dur - self.duration_sec)
        win_step = 0.5
        best_s, best_score = 0.0, -1e9
        s = 0.0
        while s <= last_start + 1e-6:
            mask = (times_a >= s) & (times_a < s + self.duration_sec)
            if mask.any():
                wscore = float(score[mask].mean())
                if wscore > best_score:
                    best_score = wscore
                    best_s = s
            s += win_step
        return best_s, best_s + self.duration_sec

    def _cut(self, start, end):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("未检测到 ffmpeg，请在软件目录放置 ffmpeg.exe 或加入 PATH。")
        os.makedirs(self.output_dir, exist_ok=True)

        # 精华模式每个视频只产出一段，先清掉该目录里旧的分镜片段，避免混剪混入多余素材
        if self.clear_dir:
            try:
                for f in os.listdir(self.output_dir):
                    if "_shot_" in f and f.lower().endswith((".mp4", ".m4v")):
                        try:
                            os.remove(os.path.join(self.output_dir, f))
                        except Exception:
                            pass
            except Exception:
                pass

        basename = os.path.splitext(os.path.basename(self.video_path))[0]
        s_str = format_seconds_to_srt_timestamp(start).replace(":", "-")
        e_str = format_seconds_to_srt_timestamp(end).replace(":", "-")
        out_name = f"{basename}_shot_{self.shot_index:03d}_{s_str}_{e_str}.mp4"
        out_path = os.path.abspath(os.path.join(self.output_dir, out_name))
        dur = max(0.1, end - start)

        creationflags = 0x08000000
        # format=yuv420p：源素材可能是 10-bit（yuv420p10le/HDR），AMF 等硬件编码器
        # 不支持 10-bit 输入，必须在滤镜链显式转 8-bit。
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", self.video_path,
               "-t", f"{dur:.3f}", "-vf", "format=yuv420p",
               *get_video_encode_args(crf=18, preset="veryfast"),
               "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", creationflags=creationflags, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.exists(out_path):
            tail = (r.stderr or "")[-400:]
            raise RuntimeError(f"ffmpeg 裁剪失败:\n{tail}")
        return out_path





class BeatDetectWorker(BaseWorker):
    """调用服务端 POST /audio/beatmap 检测音乐节拍点。

    异步任务模式（服务端文档: docs/SERVER_API.md §1.3）：
      1. POST /audio/beatmap 上传音频（可携带 count + segment_duration 请求多片段）→ 返回 task_id
      2. GET  /tasks/unified/{task_id} 轮询 → status: pending/running/completed/failed
      3. completed 后从 result 取节拍时间戳列表与片段(clips)列表

    信号: beats_ready(list[float], list[dict]), error(str)
        - beats: 全曲节拍时间戳列表
        - clips: 片段列表 [{"start","end","strength"}, ...]（count>0 时返回）
    """
    beats_ready = Signal(list, list)
    error = Signal(str)

    _POLL_INTERVAL = 2.0
    _POLL_TIMEOUT = 120.0

    def __init__(self, music_path, server_url, count=0, segment_duration=0.0):
        super().__init__()
        self.music_path = music_path
        self.server_url = (server_url or "").strip().rstrip("/")
        self.count = int(count or 0)
        self.segment_duration = float(segment_duration or 0.0)
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def do_work(self):
        from utils.http_client import http_get, http_post
        import time as _time

        fname = os.path.basename(self.music_path)
        fsize = os.path.getsize(self.music_path) if os.path.isfile(self.music_path) else 0
        submit_url = f"{self.server_url}/audio/beatmap"

        # 多片段请求参数（count=片段个数，segment_duration=每段时长秒）
        form_data = {}
        if self.count > 0:
            form_data["count"] = str(self.count)
        if self.segment_duration > 0:
            form_data["segment_duration"] = str(self.segment_duration)

        try:
            # ── 第 1 步：提交音频文件，获取 task_id ──
            log.info(f"[音乐卡点] 提交: {fname} ({fsize/1024/1024:.1f}MB) -> POST {submit_url} "
                     f"count={self.count} segment_duration={self.segment_duration}")
            with open(self.music_path, "rb") as f:
                resp = http_post(submit_url,
                                 files={"file": (fname, f, "audio/mpeg")},
                                 data=form_data,
                                 timeout=60)
            log.info(f"[音乐卡点] 响应: HTTP {resp.status_code}, body={resp.text[:300]}")
            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"提交失败 HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                submit_data = resp.json()
            except Exception:
                raise RuntimeError(f"响应非 JSON: {resp.text[:200]}")

            # 兼容：如果服务端直接返回结果（同步兼容模式）
            task_id = (submit_data.get("task_id") or submit_data.get("id")
                       or submit_data.get("job_id") or "")
            if not task_id:
                beats = self._extract_beats(submit_data)
                if beats:
                    clips = self._extract_clips(submit_data)
                    self.beats_ready.emit(beats, clips)
                    return
                raise RuntimeError(f"未返回 task_id 也无节拍数据: {str(submit_data)[:250]}")

            # ── 第 2 步：轮询 GET /tasks/unified/{task_id} ──
            log.info(f"[音乐卡点] task_id={task_id}，轮询中...")
            poll_url = f"{self.server_url}/tasks/unified/{task_id}"
            deadline = _time.time() + self._POLL_TIMEOUT
            last_status = ""

            while _time.time() < deadline:
                if self._should_stop:
                    raise RuntimeError("用户取消")
                _time.sleep(self._POLL_INTERVAL)
                try:
                    pr = http_get(poll_url, timeout=15)
                except Exception as e:
                    log.warning(f"[音乐卡点] task_id={task_id} 轮询异常: {e}")
                    continue
                if pr.status_code != 200:
                    continue
                try:
                    pdata = pr.json()
                except Exception:
                    continue

                task_obj = pdata.get("data") if isinstance(pdata.get("data"), dict) else pdata
                status = str(task_obj.get("status") or task_obj.get("state") or "").lower()
                if status != last_status:
                    log.info(f"[音乐卡点] task_id={task_id} status={status}")
                    last_status = status

                if status in ("completed", "done", "success", "finished"):
                    result = task_obj.get("result") or task_obj
                    beats = self._extract_beats(result)
                    if not beats:
                        raise RuntimeError(f"任务完成但无节拍: {str(task_obj)[:250]}")
                    clips = self._extract_clips(result)
                    log.info(f"[音乐卡点] 完成: {len(beats)} 个节拍, "
                             f"{beats[0]:.2f}s~{beats[-1]:.2f}s, {len(clips)} 个片段")
                    self.beats_ready.emit(beats, clips)
                    return

                if status in ("failed", "error", "cancelled"):
                    err = (task_obj.get("error_msg") or task_obj.get("error")
                           or task_obj.get("message") or "未知")
                    raise RuntimeError(f"任务失败(task_id={task_id}): {err}")

            raise RuntimeError(f"轮询超时({self._POLL_TIMEOUT:.0f}s), task={task_id}")
        except Exception as e:
            log.error(f"[音乐卡点] task_id={task_id if 'task_id' in dir() else 'N/A'} 失败: {e}")
            self.error.emit(f"[task_id={task_id if 'task_id' in dir() else 'N/A'}] {e}")

    @staticmethod
    def _extract_beats(payload):
        if not isinstance(payload, dict):
            return []
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        beats = (inner.get("beats") or inner.get("beat_times")
                 or inner.get("timestamps") or inner.get("beat_points") or [])
        if isinstance(beats, list) and beats:
            try:
                return sorted(float(b) for b in beats if b is not None)
            except (TypeError, ValueError):
                return []
        result = inner.get("result")
        if isinstance(result, dict):
            beats = (result.get("beats") or result.get("beat_times")
                     or result.get("timestamps") or [])
            if isinstance(beats, list) and beats:
                try:
                    return sorted(float(b) for b in beats if b is not None)
                except (TypeError, ValueError):
                    pass
        return []

    @staticmethod
    def _extract_clips(payload):
        """从服务端 result 中提取片段(clips)列表。

        返回 [{"start": float, "end": float, "strength": float}, ...]，
        按 start 排序。服务端未返回 clips 时返回空列表（回退单片段模式）。
        """
        if not isinstance(payload, dict):
            return []
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        clips = inner.get("clips")
        if not isinstance(clips, list):
            result = inner.get("result")
            if isinstance(result, dict):
                clips = result.get("clips")
        if not isinstance(clips, list) or not clips:
            return []
        out = []
        for c in clips:
            if not isinstance(c, dict):
                continue
            try:
                start = float(c.get("start"))
                end = float(c.get("end"))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            try:
                strength = float(c.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            out.append({"start": start, "end": end, "strength": strength})
        out.sort(key=lambda x: x["start"])
        return out


# ═══════════════════════════════════════════════════════════
# 卡点成片：服务端 /montage/beat 逐段生成 + 轮询 + 下载
# ═══════════════════════════════════════════════════════════

class BeatVideoGenWorker(BaseWorker):
    """调用服务端 POST /montage/beat 一次上传生成多个卡点成片（服务端契约见 /guide §2.9）。

    一次任务：上传整段音乐 + 全部镜头视频（multipart，仅上传一次），
    通过 variant_count 指定生成个数，服务端自动镜头分割→卡点检测→素材指派→
    xfade 转场→混音，一次产出 N 个完整成片变体（各自随机排位/入点/转场）。
      1. POST /montage/beat  → {id, status}
      2. GET  /tasks/unified/{id} 轮询 → result.variants / result.file
      3. GET  /montage/result/{task_id}/{variant_index} 逐个下载变体成片

    信号:
        progress(int, str)      生成进度（百分比, 描述）
        video_ready(int, str)   某个变体视频下载完成（0 基变体索引, 本地路径）
        all_done(list)          全部结束 [{index, ok, path, error}, ...]
    """
    progress = Signal(int, str)
    video_ready = Signal(int, str)
    all_done = Signal(list)

    _POLL_INTERVAL = 3.0
    _POLL_TIMEOUT = 900.0   # 视频编译耗时较长，给足超时

    _MIME = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska", ".webm": "video/webm", ".flv": "video/x-flv",
    }

    def __init__(self, server_url, spec, download_dir):
        super().__init__()
        self.server_url = (server_url or "").strip().rstrip("/")
        self.spec = dict(spec or {})
        self.download_dir = download_dir
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    @classmethod
    def _mime(cls, path):
        return cls._MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")

    def do_work(self):
        from utils.http_client import http_get
        import time as _time

        spec = self.spec
        n_variants = max(1, int(spec.get("variant_count") or 1))
        results = [{"index": i, "ok": False, "path": "", "error": ""} for i in range(n_variants)]

        # ── 第 1 步：提交单个 /montage/beat 任务（音乐+素材仅上传一次）──
        self.progress.emit(5, "正在上传音乐与素材...")
        try:
            videos = self._prepare_videos(spec)
            submit_spec = dict(spec)
            submit_spec["videos"] = videos
            tid = self._submit_one(submit_spec)
        except Exception as e:
            log.error(f"[卡点成片] 提交失败: {e}")
            for r in results:
                # ApiError 已含"调用接口失败 + 接口 + 参数 + 错误"，无需额外前缀
                r["error"] = str(e) if isinstance(e, ApiError) else f"提交失败: {e}"
            self.all_done.emit(results)
            return
        log.info(f"[卡点成片] 已提交 task_id={tid}, variant_count={n_variants}")

        # ── 第 2 步：轮询任务直到完成 ──
        self.progress.emit(20, "服务端生成中...")
        deadline = _time.time() + self._POLL_TIMEOUT
        result = None
        while _time.time() < deadline:
            if self._should_stop:
                raise RuntimeError("用户取消")
            _time.sleep(self._POLL_INTERVAL)
            try:
                pr = http_get(f"{self.server_url}/tasks/unified/{tid}", timeout=15)
            except Exception as e:
                log.warning(f"[卡点成片] task_id={tid} 轮询异常: {e}")
                continue
            if pr.status_code != 200:
                continue
            try:
                pdata = pr.json()
            except Exception:
                continue
            task_obj = pdata.get("data") if isinstance(pdata.get("data"), dict) else pdata
            status = str(task_obj.get("status") or task_obj.get("state") or "").lower()
            if status in ("completed", "done", "success", "finished"):
                result = task_obj.get("result") or task_obj
                break
            elif status in ("failed", "error", "cancelled"):
                err = (task_obj.get("error_msg") or task_obj.get("error")
                       or task_obj.get("message") or "未知")
                for r in results:
                    r["error"] = f"服务端生成失败(task_id={tid}): {err}"
                log.error(f"[卡点成片] task_id={tid} 生成失败: {err}")
                self.all_done.emit(results)
                return

        if result is None:
            for r in results:
                r["error"] = f"生成超时（{self._POLL_TIMEOUT:.0f}s）, task_id={tid}"
            self.all_done.emit(results)
            return

        # ── 第 3 步：逐个下载变体成片 ──
        variants = result.get("variants") or []
        if variants:
            total_v = len(variants)
            for i, v in enumerate(variants):
                if self._should_stop:
                    raise RuntimeError("用户取消")
                file_ref = v.get("file") or f"/montage/result/{tid}/{v.get('variant', i + 1)}"
                try:
                    local = self._download(tid, file_ref, i)
                    results[i]["ok"] = True
                    results[i]["path"] = local
                    log.info(f"[卡点成片] task_id={tid} 变体{i + 1} 下载完成: {local}")
                    self.video_ready.emit(i, local)
                except Exception as e:
                    log.error(f"[卡点成片] task_id={tid} 变体{i + 1} 下载失败: {e}")
                    results[i]["error"] = f"下载失败(task_id={tid}): {e}"
                self.progress.emit(int(50 + (i + 1) / total_v * 50),
                                   f"下载视频 {i + 1}/{total_v}")
        else:
            # variant_count=1 时服务端仅返回 result.file
            file_ref = result.get("file") or f"/montage/result/{tid}"
            try:
                local = self._download(tid, file_ref, 0)
                results[0]["ok"] = True
                results[0]["path"] = local
                log.info(f"[卡点成片] task_id={tid} 成片下载完成: {local}")
                self.video_ready.emit(0, local)
            except Exception as e:
                log.error(f"[卡点成片] task_id={tid} 成片下载失败: {e}")
                results[0]["error"] = f"下载失败(task_id={tid}): {e}"

        self.progress.emit(100, "全部完成")
        self.all_done.emit(results)

    _IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

    def _prepare_videos(self, spec):
        """上传前预处理素材：图片转成静态视频片段（服务端只接受视频）。
        图片片段时长默认 2 秒，可由 spec['image_duration'] 指定（随音乐节拍变化）。"""
        videos = [v for v in (spec.get("videos") or []) if v and os.path.isfile(v)]
        try:
            img_dur = max(0.5, float(spec.get("image_duration") or 2.0))
        except (TypeError, ValueError):
            img_dur = 2.0
        out_dir = os.path.join(self.download_dir, "img_clips")
        prepared = []
        n_img = 0
        for v in videos:
            if os.path.splitext(v)[1].lower() in self._IMAGE_EXTS:
                if n_img == 0:
                    self.progress.emit(8, "正在转换图片素材...")
                clip = self._image_to_clip(v, out_dir, img_dur)
                prepared.append(clip)
                n_img += 1
                log.info(f"[卡点成片] 图片转片段: {os.path.basename(v)} -> {clip} ({img_dur:.1f}s)")
            else:
                prepared.append(v)
        if n_img:
            log.info(f"[卡点成片] 共转换 {n_img} 张图片为 {img_dur:.1f}s 静态片段")
        return prepared

    def _image_to_clip(self, image_path, out_dir, duration):
        """ffmpeg 将单张图片转成带静音音轨的 mp4 静态片段，结果按时长缓存复用。"""
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(out_dir, f"{stem}_img{duration:.1f}s.mp4")
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("未检测到 ffmpeg，无法转换图片素材。")
        dur = max(0.5, float(duration))
        # 尺寸归一到偶数（yuv420p 要求），附带静音音轨便于服务端混音
        cmd = [ffmpeg, "-y", "-loop", "1", "-i", image_path,
               "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
               "-t", f"{dur:.3f}",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-c:a", "aac", "-shortest", "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", creationflags=0x08000000, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.exists(out_path):
            tail = (r.stderr or "")[-300:]
            raise RuntimeError(f"图片转视频失败({os.path.basename(image_path)}):\n{tail}")
        return out_path

    def _submit_one(self, spec):
        """提交单个 /montage/beat 任务，返回 task_id。"""
        from utils.http_client import http_post
        music = spec.get("music") or ""
        videos = spec.get("videos") or []
        if not music or not os.path.isfile(music):
            raise RuntimeError(f"音乐文件不存在: {music}")
        videos = [v for v in videos if v and os.path.isfile(v)]
        if not videos:
            raise RuntimeError("没有可上传的镜头视频")

        # 组装表单参数（仅传非空项）
        data = {}
        for key in ("count", "time_limit", "variant_count", "min_duration", "max_duration",
                    "width", "height", "fps", "crf", "transition", "transition_duration",
                    "aspect_ratio"):
            v = spec.get(key)
            if v is None or v == "":
                continue
            data[key] = str(v)

        opened, files = [], []
        try:
            mf = open(music, "rb"); opened.append(mf)
            files.append(("music", (os.path.basename(music), mf, self._mime(music))))
            for vp in videos:
                vf = open(vp, "rb"); opened.append(vf)
                files.append(("videos", (os.path.basename(vp), vf, self._mime(vp))))
            log.info(f"[卡点成片] 上传: 1 音乐 + {len(videos)} 视频, 参数={data}")
            resp = http_post(f"{self.server_url}/montage/beat",
                             files=files, data=data, timeout=600)
        finally:
            for fh in opened:
                try:
                    fh.close()
                except Exception:
                    pass

        # 提交给 ApiError 的参数：music 文件名 + 镜头数 + 变体数 + 表单参数（脱敏由 ApiError 完成）
        beat_url = f"{self.server_url}/montage/beat"
        error_params = {
            "music": os.path.basename(music),
            "video_count": len(videos),
            "variant_count": spec.get("variant_count", 1),
        }
        error_params.update(data)

        if resp.status_code not in (200, 201, 202):
            raise ApiError(beat_url, method="POST", params=error_params,
                           status_code=resp.status_code, response_text=resp.text, service="montage")
        try:
            body = resp.json()
        except Exception:
            raise ApiError(beat_url, method="POST", params=error_params,
                           response_text=resp.text, service="montage",
                           note="响应非 JSON")
        tid = body.get("id") or body.get("task_id") or body.get("job_id") or ""
        if not tid:
            raise ApiError(beat_url, method="POST", params=error_params,
                           status_code=resp.status_code, response_text=resp.text, service="montage",
                           note="未返回任务 id")
        return tid

    def _download(self, task_id, file_ref, index):
        """下载成片到 download_dir，返回本地路径。"""
        from utils.http_client import http_get
        url = file_ref if str(file_ref).startswith("http") else f"{self.server_url}{file_ref}"
        if not str(file_ref).startswith(("http", "/")):
            url = f"{self.server_url}/montage/result/{task_id}"
        os.makedirs(self.download_dir, exist_ok=True)
        ext = os.path.splitext(str(file_ref).split("?")[0])[1] or ".mp4"
        local = os.path.join(self.download_dir, f"beat_gen_{index + 1}{ext}")
        with http_get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(local, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if not os.path.isfile(local) or os.path.getsize(local) == 0:
            raise RuntimeError("下载文件为空")
        return local
