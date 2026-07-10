# -*- coding: utf-8 -*-
import os
import traceback

from PySide6.QtCore import Signal, QThread
from utils.logger_utils import log


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

    def run(self):
        try:
            self._run_remote()
        except Exception:
            self.busy.emit(False)
            log.exception("WhisperX 转写失败")
            self.error.emit(traceback.format_exc())

    def _run_remote(self):
        """远程 ASR 模式：上传音频到远程服务，拿回 segments，本地格式化为 SRT。"""
        from utils import asr_client
        asr_url = asr_client.read_asr_url()
        if not asr_url:
            raise RuntimeError(
                "未配置 ASR 服务地址。"
                "请在系统设置 → Whisper 填写远程 API 地址。"
            )

        self.stage.emit("正在提取音频并上传到远程 ASR 服务...")
        self.progress.emit(10)
        self.busy.emit(True)

        language = self.language if self.language and self.language != "auto" else ""
        segments = asr_client.transcribe_remote(
            video_path=self.video_path,
            asr_url=asr_url,
            language=language,
            task_type=self.task_type or "transcribe",
            diarize=bool(self.multi_mode),
        )

        self.stage.emit("正在生成字幕...")
        self.progress.emit(85)

        srt_content = asr_client.segments_to_srt(segments)

        # 写 SRT 文件到 output_path（保持与 local 模式一致的输出契约）
        if self.output_path:
            srt_path = self.output_path
            if not srt_path.endswith(".srt"):
                base = srt_path.rsplit(".", 1)[0] if "." in os.path.basename(srt_path) else srt_path
                srt_path = base + ".srt"
            os.makedirs(os.path.dirname(srt_path), exist_ok=True)
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
        else:
            srt_path = ""

        self.stage.emit("语音转写字幕完成")
        self.progress.emit(100)
        self.busy.emit(False)
        self.finished.emit(srt_content, srt_path)
