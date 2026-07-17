# -*- coding: utf-8 -*-
"""智能混剪 - 分割阶段 Worker：场景检测、挑精华、镜头评分。"""
import os
from PySide6.QtCore import Signal
from utils.base_worker import BaseWorker
from utils.logger_utils import log
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
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", self.video_path,
               "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-movflags", "+faststart", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", creationflags=creationflags)
        if r.returncode != 0 or not os.path.exists(out_path):
            tail = (r.stderr or "")[-400:]
            raise RuntimeError(f"ffmpeg 裁剪失败:\n{tail}")
        return out_path



class ScoreClipsWorker(BaseWorker):
    """后台并行评分分割镜头，完成时通过信号通知主线程刷新表格。

    用线程池并发执行 _score_clip()，比串行循环快数倍。
    _score_clip() 每次调用自建 cv2.VideoCapture、无共享状态，线程安全。
    """
    score_ready = Signal(int, float)  # row_index, score
    all_done = Signal()

    # 评分是 IO(抽帧)+轻 CPU(Laplacian/SSIM) 混合，并发数取 CPU 核心数的一半，
    # 上限 6，避免 OpenCV 后端在高并发下偶发解码错误。
    _MAX_WORKERS = max(2, min(6, (os.cpu_count() or 4) // 2))

    def __init__(self, page_ref, clip_paths):
        super().__init__()
        self.page_ref = page_ref
        self.clip_paths = clip_paths
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not self.clip_paths:
            self.all_done.emit()
            return

        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS,
                                thread_name_prefix="score") as pool:
            # 提交全部任务，记录 future→行号 映射
            future_to_idx = {
                pool.submit(self.page_ref._score_clip, clip_path): idx
                for idx, clip_path in enumerate(self.clip_paths)
            }
            try:
                for fut in as_completed(future_to_idx):
                    if self._should_stop:
                        break
                    idx = future_to_idx[fut]
                    try:
                        score = fut.result()
                    except Exception:
                        score = -1
                    # 信号通过 Qt 队列连接自动排到主线程，安全更新表格
                    self.score_ready.emit(idx, score)
            finally:
                # 中途 stop() 时取消尚未开始的 future，避免无谓计算
                for fut in future_to_idx:
                    if not fut.done():
                        fut.cancel()
        self.all_done.emit()
