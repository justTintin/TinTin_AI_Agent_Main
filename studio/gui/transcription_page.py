import os
import traceback
import sys

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame)
from PySide6.QtCore import Signal, QThread, QUrl
from utils.base_worker import BaseWorker
from PySide6.QtGui import QDesktopServices
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from config.paths import TMP_DIR, OUTPUTS_DIR


def setup_nvidia_dll_path():
    """
    在 Windows 平台且使用嵌入式 Python 时，CTranslate2 (faster-whisper) 加速需要 cuda/cudnn 的 DLL。
    如果用户通过 pip 安装了 nvidia-cublas-cu12 和 nvidia-cudnn-cu12，
    我们将这些包的 bin 目录动态加入系统 PATH 和 DLL 搜索目录。
    """
    import site
    packages_dirs = []

    # 尝试系统 site-packages
    try:
        packages_dirs.extend(site.getsitepackages())
    except Exception:
        pass

    # 尝试用户 site-packages
    try:
        packages_dirs.append(site.getusersitepackages())
    except Exception:
        pass

    # 尝试相对于 python.exe 的 site-packages (特别适用于嵌入式 Python 环境)
    try:
        base_dir = os.path.dirname(sys.executable)
        packages_dirs.append(os.path.join(base_dir, "Lib", "site-packages"))
        packages_dirs.append(os.path.join(base_dir, "lib", "site-packages"))
    except Exception:
        pass

    added = False
    for p in packages_dirs:
        if not p or not os.path.isdir(p):
            continue
        nvidia_base = os.path.join(p, "nvidia")
        if os.path.isdir(nvidia_base):
            for sub in ["cublas", "cudnn"]:
                bin_path = os.path.join(nvidia_base, sub, "bin")
                if os.path.isdir(bin_path):
                    if bin_path not in os.environ["PATH"]:
                        os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(bin_path)
                            added = True
                        except Exception:
                            pass
    if added:
        log.info("已自动加载 nvidia CUDA/cuDNN DLL 路径")


def format_srt_timestamp(seconds):
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


def format_vtt_timestamp(seconds):
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
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_txt_timestamp(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{m:02d}:{s:02d}.{ms:03d}"

# WhisperTranscribeWorker is deprecated. We use WhisperXTranscribeWorker from apps.whisperx.whisperx_worker instead.


from gui.base_page import BasePage


class TranscriptionToolPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.last_output_path = ""
        self.transcription_results = {}

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)

        heading = QLabel("🎙️ 视频生成字幕文件（WhisperX）")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(14)

        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("视频文件:"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("选择视频文件 (.mp4/.mov/.avi/.mkv 等) ...")
        inp_row.addWidget(self.video_path_input)
        btn_sel = QPushButton("选择视频")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_video)
        inp_row.addWidget(btn_sel)
        card_layout.addLayout(inp_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("音频语言（留空自动检测）:"))
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("如 zh、en、空则自动检测")
        self.lang_input.setMaximumWidth(200)
        lang_row.addWidget(self.lang_input)
        lang_row.addStretch()
        card_layout.addLayout(lang_row)

        task_row = QHBoxLayout()
        task_row.addWidget(QLabel("任务类型:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(["转写（原语言）", "翻译为英文"])
        task_row.addWidget(self.task_combo)
        card_layout.addLayout(task_row)

        self.multi_speaker_check = QCheckBox("👥 多人模式（启用说话人分离）")
        card_layout.addWidget(self.multi_speaker_check)

        self.stage_label = QLabel("就绪")
        self.stage_label.setObjectName("muted_text")
        card_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        btn_run = mdi_button("开始生成字幕", "video")
        btn_run.setObjectName("action_button")
        btn_run.setFixedHeight(46)
        btn_run.clicked.connect(self._start_transcription)
        self.btn_run = btn_run
        card_layout.addWidget(btn_run)

        layout.addWidget(card, 0)

        result_card = QFrame()
        result_card.setObjectName("card")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(24, 20, 24, 20)

        res_header = QHBoxLayout()
        res_header.addWidget(QLabel("转写字幕结果:"))
        res_header.addStretch()

        # 字幕预览格式切换选择框
        res_header.addWidget(QLabel("字幕格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItem("SRT 字幕文件 (*.srt)", "srt")
        self.format_combo.addItem("WebVTT 字幕文件 (*.vtt)", "vtt")
        self.format_combo.addItem("TXT 带有时间戳文本 (*.txt)", "txt")
        self.format_combo.addItem("TXT 纯文本（无时间戳） (*.txt)", "plain")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        res_header.addWidget(self.format_combo)
        res_header.addSpacing(10)

        btn_save = mdi_button("保存结果", "save")
        btn_save.setObjectName("secondary_button")
        btn_save.clicked.connect(self._save_result)
        self.btn_save = btn_save
        self.btn_save.setEnabled(False)
        res_header.addWidget(btn_save)
        result_layout.addLayout(res_header)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("转写出的字幕将在此处显示 ...")
        result_layout.addWidget(self.result_text)

        layout.addWidget(result_card, 1)
        self._refresh_dep_status()

    def _refresh_dep_status(self):
        self.btn_run.setEnabled(True)

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择视频文件",
            "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;All Files (*)",
        )
        if path:
            self.video_path_input.setText(path)

    def _start_transcription(self):
        if self.worker and self.worker.isRunning():
            return

        video_path = self.video_path_input.text().strip()
        if not video_path:
            QMessageBox.warning(self.parent_widget, "请选择文件", "请先选择一个视频文件。")
            return
        if not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"文件不存在：\n{video_path}")
            return

        language = self.lang_input.text().strip() or None
        task_type = "translate" if "翻译" in self.task_combo.currentText() else "transcribe"
        diarize = self.multi_speaker_check.isChecked()

        out_dir = os.path.join(OUTPUTS_DIR, "transcription")
        os.makedirs(out_dir, exist_ok=True)
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        output_path = os.path.join(out_dir, f"{video_basename}.srt")

        self.btn_run.setEnabled(False)
        self.stage_label.setText("正在连接远程服务...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定模式
        self.result_text.clear()
        self.last_output_path = ""
        self.transcription_results = {}

        from utils.asr_client import transcribe_remote, segments_to_plain

        class RemoteTranscribeWorker(BaseWorker):
            stage = Signal(str)
            progress = Signal(int)
            finished = Signal(str, str)  # srt_text, output_path
            error = Signal(str)

            def __init__(self, video_path, output_path, language, task_type, diarize):
                super().__init__()
                self.video_path = video_path
                self.output_path = output_path
                self.language = language
                self.task_type = task_type
                self.diarize = diarize

            def do_work(self):
                try:
                    self.stage.emit("正在提取音频...")
                    from utils.asr_client import _extract_audio
                    audio_path = _extract_audio(self.video_path)
                    self.stage.emit("正在发送到远程 Whisper 服务...")
                    segments, _info = transcribe_remote(
                        audio_path, language=self.language, task_type=self.task_type,
                        diarize=self.diarize,
                    )
                    # 生成 SRT
                    srt_lines = []
                    for i, seg in enumerate(segments):
                        start = seg.get("start", 0)
                        end = seg.get("end", 0)
                        text = seg.get("text", "").strip().replace("\n", " ")
                        srt_lines.append(f"{i+1}")
                        srt_lines.append(
                            f"{int(start//3600):02d}:{int(start%3600//60):02d}:{start%60:06.3f} --> "
                            f"{int(end//3600):02d}:{int(end%3600//60):02d}:{end%60:06.3f}"
                        )
                        srt_lines.append(text)
                        srt_lines.append("")
                    srt_text = "\n".join(srt_lines)
                    with open(self.output_path, "w", encoding="utf-8") as f:
                        f.write(srt_text)
                    self.stage.emit("转写完成")
                    self.finished.emit(srt_text, self.output_path)
                except Exception as e:
                    self.error.emit(str(e))

        self.worker = RemoteTranscribeWorker(video_path, output_path, language, task_type, diarize)
        self.worker.stage.connect(self._on_stage)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _deps_ok(self):
        return True

    def _on_stage(self, text):
        self.stage_label.setText(text)

    def _on_progress(self, value):
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 100:
            self.progress_bar.setValue(int(value))

    def _on_busy(self, is_busy):
        if is_busy:
            self.progress_bar.setRange(0, 0)
        else:
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)

    def _on_finished(self, srt_text, output_path):
        self.last_output_path = output_path
        self.transcription_results = {
            "srt": srt_text,
            "vtt": "",
            "txt": "",
            "plain": ""
        }
        
        # 自动加载同目录生成的其他格式内容
        base_path = output_path.rsplit(".", 1)[0]
        vtt_path = base_path + ".vtt"
        txt_path = base_path + ".txt"
        plain_path = base_path + "_plain.txt"
        
        if os.path.exists(vtt_path):
            try:
                with open(vtt_path, "r", encoding="utf-8") as f:
                    self.transcription_results["vtt"] = f.read()
            except Exception:
                pass
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    self.transcription_results["txt"] = f.read()
            except Exception:
                pass
        if os.path.exists(plain_path):
            try:
                with open(plain_path, "r", encoding="utf-8") as f:
                    self.transcription_results["plain"] = f.read()
            except Exception:
                pass

        self.btn_run.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.stage_label.setText(f"✅ 完成：{output_path}")
        self._on_format_changed()

    def _on_format_changed(self):
        if not hasattr(self, "transcription_results") or not self.transcription_results:
            return
        fmt = self.format_combo.currentData()
        self.result_text.setPlainText(self.transcription_results.get(fmt, ""))

    def _on_error(self, err):
        self.btn_run.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 失败（详情请查看 .runtime/logs/app.log）")
        summary = ""
        try:
            for line in (err or "").splitlines()[::-1]:
                if line.strip():
                    summary = line.strip()
                    break
        except Exception:
            summary = ""
        msg = "转写失败，详情已写入日志：.runtime/logs/app.log"
        if summary:
            msg = msg + f"\n\n错误摘要：{summary}"
        QMessageBox.critical(self.parent_widget, "转写失败", msg)

    def _save_result(self):
        text = self.result_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self.parent_widget, "无内容", "转写结果为空，无法保存。")
            return
        
        fmt = self.format_combo.currentData()
        ext = "txt" if fmt in ("txt", "plain") else fmt
        video_path = self.video_path_input.text().strip()
        video_basename = os.path.splitext(os.path.basename(video_path))[0] if video_path else "whisper_transcript"
        
        # If a valid video path is specified, default to saving in its parent directory
        if video_path and os.path.exists(video_path):
            default_dir = os.path.dirname(os.path.abspath(video_path))
            if fmt == "plain":
                default_path = os.path.join(default_dir, f"{video_basename}_plain.txt")
            else:
                default_path = os.path.join(default_dir, f"{video_basename}.{ext}")
        else:
            # Fallback to standard Documents folder if possible
            documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
            if os.path.exists(documents_dir):
                if fmt == "plain":
                    default_path = os.path.join(documents_dir, f"{video_basename}_plain.txt")
                else:
                    default_path = os.path.join(documents_dir, f"{video_basename}.{ext}")
            else:
                if fmt == "plain":
                    default_path = f"{video_basename}_plain.txt"
                else:
                    default_path = f"{video_basename}.{ext}"
                
        filter_str = f"{ext.upper()} Files (*.{ext});;All Files (*)"
        
        path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "保存转写结果",
            default_path,
            filter_str,
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                QMessageBox.information(self.parent_widget, "已保存", f"结果已保存到：\n{path}")
            except Exception as e:
                QMessageBox.critical(self.parent_widget, "保存失败", str(e))
