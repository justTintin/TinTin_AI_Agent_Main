# -*- coding: utf-8 -*-
import os
import sys
import gc
import subprocess
import traceback

from PySide6.QtCore import Signal, QThread
from utils.logger_utils import log


def _check_and_warn_vram(min_free_mb: int = 3000):
    """检查 GPU 剩余显存，若不足则输出警告日志。"""
    try:
        import torch
        if not torch.cuda.is_available():
            return
        free_mb = (torch.cuda.get_device_properties(0).total_memory
                   - torch.cuda.memory_allocated(0)) // 1024 // 1024
        if free_mb < min_free_mb:
            log.warning(
                f"[WhisperX] GPU 剩余显存不足 {min_free_mb}MB（当前 {free_mb}MB），"
                "转写任务可能失败或导致系统不稳定！建议停止其他 GPU 任务后再试。"
            )
    except Exception:
        pass


def _release_gpu_cache():
    """安全地释放 GPU 显存缓存，减少碎片化压力。"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()
    except Exception:
        pass

class WhisperXTranscribeWorker(QThread):
    stage = Signal(str)
    progress = Signal(int)
    busy = Signal(bool)
    finished = Signal(str, str)  # 发送 SRT 内容和路径
    error = Signal(str)

    def __init__(self, video_path, audio_path, output_path, model_name, language, task_type, multi_mode, download_root, device_mode):
        super().__init__()
        self.video_path = video_path
        self.audio_path = audio_path
        self.output_path = output_path
        self.model_name = model_name
        self.language = language
        self.task_type = task_type
        self.multi_mode = multi_mode
        self.download_root = download_root
        self.device_mode = device_mode
        self.process = None

    def run(self):
        try:
            # 1. 确保 ffmpeg 可用（复用项目统一的查找逻辑，覆盖 asset-browser/vsr 等内置位置）
            from utils.platform_utils import find_ffmpeg
            ffmpeg_path = find_ffmpeg()
            if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
                raise RuntimeError(
                    "未检测到 ffmpeg，请安装 ffmpeg 或将其加入环境变量 PATH。"
                )

            # 2. 构造 whisperx_runner.py 子进程命令
            runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisperx_runner.py")
            cmd = [
                sys.executable, "-u", runner_path,
                "--video_path", self.video_path,
                "--audio_path", self.audio_path,
                "--output_path", self.output_path,
                "--model_name", self.model_name,
                "--download_root", self.download_root,
                "--device_mode", self.device_mode,
                "--ffmpeg_path", ffmpeg_path,
            ]
            if self.language:
                cmd.extend(["--language", self.language])
            if self.task_type:
                cmd.extend(["--task_type", self.task_type])
            if self.multi_mode:
                cmd.append("--multi_mode")

            log.info(f"[WhisperX Worker] 启动子进程: {' '.join(cmd)}")

            # 2.5 启动前检查 GPU 显存是否充足
            _check_and_warn_vram(min_free_mb=3000)

            # 3. 启动子进程并重定向 stderr 到 stdout 统一解析
            env = os.environ.copy()
            # 自动为国内用户配置 Hugging Face 镜像加速，防止网络连接超时
            env["HF_ENDPOINT"] = "https://hf-mirror.com"
            env["PYTHONIOENCODING"] = "utf-8"
            if ffmpeg_path:
                ffmpeg_dir = os.path.dirname(ffmpeg_path)
                if ffmpeg_dir not in env.get("PATH", ""):
                    env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            finished_srt_path = None
            error_lines = []
            is_error = False

            # 4. 实时读取输出流
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                line_str = line.strip()
                if not line_str:
                    continue

                log.info(f"[WhisperX Subprocess] {line_str}")

                # 解析自定义标记
                if line_str.startswith("[STAGE] "):
                    stage_msg = line_str[len("[STAGE] "):]
                    self.stage.emit(stage_msg)
                elif line_str.startswith("[PROGRESS] "):
                    try:
                        prog_val = int(line_str[len("[PROGRESS] "):])
                        self.progress.emit(prog_val)
                        if 30 < prog_val < 90:
                            self.busy.emit(True)
                        else:
                            self.busy.emit(False)
                    except Exception:
                        pass
                elif line_str.startswith("[FINISHED] "):
                    finished_srt_path = line_str[len("[FINISHED] "):]
                elif line_str.startswith("[ERROR] "):
                    is_error = True
                    error_lines.append(line_str[len("[ERROR] "):])
                else:
                    if "Traceback" in line_str or "Exception" in line_str or "Error" in line_str:
                        is_error = True
                    if is_error:
                        error_lines.append(line_str)

            self.process.wait()

            if self.process.returncode != 0:
                err_msg = "\n".join(error_lines) if error_lines else f"子进程执行失败，退出代码: {self.process.returncode}"
                raise RuntimeError(err_msg)

            if not finished_srt_path:
                base_out_path = self.output_path.rsplit(".", 1)[0]
                finished_srt_path = base_out_path + ".srt"

            if not os.path.exists(finished_srt_path):
                raise FileNotFoundError(f"未找到生成的字幕文件: {finished_srt_path}")

            with open(finished_srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()

            self.stage.emit("语音转写字幕完成")
            self.progress.emit(100)
            self.busy.emit(False)
            self.finished.emit(srt_content, finished_srt_path)

        except Exception:
            self.busy.emit(False)
            log.exception("WhisperX 转写失败")
            self.error.emit(traceback.format_exc())
        finally:
            # 无论成功与否，子进程结束后都释放 GPU 缓存
            _release_gpu_cache()

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                log.info("[WhisperX Worker] 正在终止 WhisperX 子进程...")
                if sys.platform == "win32":
                    # 使用 taskkill /T 确保终止整个进程树（包含 CUDA 子进程）
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        capture_output=True
                    )
                else:
                    self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    log.warning("[WhisperX Worker] 强行杀死 WhisperX 子进程...")
                    self.process.kill()
                except Exception:
                    pass
            finally:
                # 进程终止后释放 GPU 缓存
                _release_gpu_cache()
