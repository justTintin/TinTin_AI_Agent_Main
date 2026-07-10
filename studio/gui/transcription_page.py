import os
import shutil
import subprocess
import traceback
import sys

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame)
from PySide6.QtCore import Signal, QThread, QUrl
from utils.base_worker import BaseWorker
from PySide6.QtGui import QDesktopServices
from utils.gui_icons import mdi_button, mdi_icon
from utils.logger_utils import log
from config.paths import RUNTIME_DIR, TMP_DIR, OUTPUTS_DIR, WHISPER_MODELS_DIR, APPS_DIR, BUNDLE_ASSETS_DIR

WHISPER_MODELS = {
    "small": {"name": "small", "params": "244M", "description": "中等速度，较高准确率"},
    "medium": {"name": "medium", "params": "769M", "description": "较慢，高准确率（需较大显存）"},
    "large-v3": {"name": "large-v3", "params": "1550M", "description": "最慢，最高准确率（最新大模型，推荐）"},
    "large": {"name": "large", "params": "1550M", "description": "最慢，原版大模型（需大显存）"},
}


def migrate_whisper_models():
    """
    自动将旧的 .runtime/whisper-models 目录下的模型迁移到 apps/whisper-models 目录下。
    """
    try:
        old_dir = os.path.join(RUNTIME_DIR, "whisper-models")
        new_dir = WHISPER_MODELS_DIR

        if os.path.isdir(old_dir) and any(os.listdir(old_dir)):
            log.info(f"检测到旧的 Whisper 模型放置在: {old_dir}，正在自动迁移到新目录: {new_dir}")
            os.makedirs(new_dir, exist_ok=True)
            for item in os.listdir(old_dir):
                src = os.path.join(old_dir, item)
                dst = os.path.join(new_dir, item)
                if os.path.exists(dst):
                    log.info(f"迁移目标路径已存在，跳过: {dst}")
                    continue
                try:
                    shutil.move(src, dst)
                    log.info(f"成功迁移文件/目录: {src} -> {dst}")
                except Exception as e:
                    log.error(f"迁移失败 {src} -> {dst}: {e}")
            
            # 检查旧目录是否为空，为空则删除
            try:
                if not os.listdir(old_dir):
                    os.rmdir(old_dir)
                    log.info(f"旧的空目录已清理: {old_dir}")
            except Exception:
                pass
    except Exception as e:
        log.error(f"迁移 Whisper 模型时发生错误: {e}")

# 执行迁移
migrate_whisper_models()


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

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Whisper 模型:"))
        self.model_combo = QComboBox()
        for key, info in WHISPER_MODELS.items():
            self.model_combo.addItem(f"{info['name']} ({info['params']}) — {info['description']}", key)
        self.model_combo.setCurrentIndex(self.model_combo.findData("large-v3"))
        model_row.addWidget(self.model_combo)
        
        btn_open_model_dir = mdi_button("打开模型目录", "folder")
        btn_open_model_dir.setObjectName("secondary_button")
        btn_open_model_dir.clicked.connect(self._open_model_directory)
        model_row.addWidget(btn_open_model_dir)

        card_layout.addLayout(model_row)

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

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("运行设备:"))
        self.device_combo = QComboBox()
        # 默认优先 CUDA GPU，放在第一项
        self.device_combo.addItems(["CUDA (推荐，使用GPU)", "自动（优先CUDA）", "CPU"])
        self.device_combo.setCurrentIndex(0)
        device_row.addWidget(self.device_combo)
        device_row.addStretch()
        card_layout.addLayout(device_row)

        self.multi_check = QCheckBox("👥 多人模式（启用说话人分离）")
        card_layout.addWidget(self.multi_check)

        self.stage_label = QLabel("就绪")
        self.stage_label.setObjectName("muted_text")
        card_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        install_row = QHBoxLayout()
        install_row.addStretch()
        self.btn_install_deps = QPushButton("安装转写依赖")
        self.btn_install_deps.setObjectName("secondary_button")
        self.btn_install_deps.clicked.connect(self._install_deps)
        install_row.addWidget(self.btn_install_deps)
        card_layout.addLayout(install_row)

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
        if not self._deps_ok():
            self.stage_label.setText("缺少依赖（请先点击“安装转写依赖”）")
            return

        video_path = self.video_path_input.text().strip()
        if not video_path:
            QMessageBox.warning(self.parent_widget, "请选择文件", "请先选择一个视频文件。")
            return
        if not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"文件不存在：\n{video_path}")
            return

        model_name = self.model_combo.currentData()
        language = self.lang_input.text().strip() or None
        task_type = "translate" if "翻译" in self.task_combo.currentText() else "transcribe"
        multi_mode = self.multi_check.isChecked()
        device_text = self.device_combo.currentText()
        
        if "CUDA" in device_text and "自动" not in device_text:
            device_mode = "cuda"
        elif "CPU" in device_text:
            device_mode = "cpu"
        else:
            device_mode = "auto"

        tmp_dir = TMP_DIR
        out_dir = os.path.join(OUTPUTS_DIR, "transcription")
        os.makedirs(out_dir, exist_ok=True)

        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        audio_path = os.path.join(tmp_dir, f"{video_basename}_audio.wav")
        # 默认保存为同名 .srt 字幕文件
        output_path = os.path.join(out_dir, f"{video_basename}.srt")

        # 检查模型是否已经在本地存在
        model_dir_name = f"models--Systran--faster-whisper-{model_name}"
        whisper_models_dir = WHISPER_MODELS_DIR
        model_path = os.path.join(whisper_models_dir, model_dir_name)
        simple_model_path = os.path.join(whisper_models_dir, model_name)
        simple_model_path_alt = os.path.join(whisper_models_dir, f"faster-whisper-{model_name}")
        root_model_bin = os.path.join(whisper_models_dir, "model.bin")
        root_config_json = os.path.join(whisper_models_dir, "config.json")
        
        model_exists = False
        if os.path.isdir(model_path) and any(os.listdir(model_path)):
            model_exists = True
        elif os.path.isdir(simple_model_path) and os.path.isfile(os.path.join(simple_model_path, "model.bin")):
            model_exists = True
        elif os.path.isdir(simple_model_path_alt) and os.path.isfile(os.path.join(simple_model_path_alt, "model.bin")):
            model_exists = True
        elif os.path.isfile(root_model_bin) and os.path.isfile(root_config_json):
            model_exists = True
            
        if not model_exists:
            reply = QMessageBox.question(
                self.parent_widget,
                "提示模型下载",
                f"本地未检测到 {model_name} 模型。\n\n"
                "程序将会自动为您从镜像网络下载该模型（约需几分钟）。\n"
                "您也可以选择‘否’并手动将模型放置到模型目录下。\n\n"
                "是否确认开始自动下载模型并转写视频？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.No:
                return

        self.btn_run.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.stage_label.setText("准备中")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.result_text.clear()
        self.last_output_path = ""
        self.transcription_results = {}

        from apps.whisperx.whisperx_worker import WhisperXTranscribeWorker
        self.worker = WhisperXTranscribeWorker(
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_path,
            model_name=model_name,
            language=language,
            task_type=task_type,
            multi_mode=multi_mode,
            download_root=whisper_models_dir,
            device_mode=device_mode,
        )
        self.worker.stage.connect(self._on_stage)
        self.worker.progress.connect(self._on_progress)
        self.worker.busy.connect(self._on_busy)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _deps_ok(self):
        # 纯远程 ASR 模式：转写由远程服务完成，不再依赖本地 torch / whisperx。
        return True

    def _refresh_dep_status(self):
        ok = self._deps_ok()
        self.btn_install_deps.setVisible(False)  # 远程模式无需本地依赖安装
        self.btn_run.setEnabled(ok)

    def _install_deps(self):
        if hasattr(self, "_install_worker") and self._install_worker and self._install_worker.isRunning():
            return

        class PipInstallWorker(BaseWorker):
            stage = Signal(str)
            busy = Signal(bool)
            finished = Signal()

            def run(self):
                try:
                    wheel_dir = os.path.join(BUNDLE_ASSETS_DIR, "wheels")
                    has_wheels = os.path.isdir(wheel_dir) and any(n.lower().endswith(".whl") for n in os.listdir(wheel_dir))
                    has_nvidia = bool(shutil.which("nvidia-smi"))

                    def run_pip(args):
                        cmd = [sys.executable, "-m", "pip"] + args
                        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", creationflags=subprocess.CREATE_NO_WINDOW)
                        if p.returncode != 0:
                            raise RuntimeError((p.stdout or "") + "\n" + (p.stderr or ""))

                    def run_pip_allow_fail(args):
                        cmd = [sys.executable, "-m", "pip"] + args
                        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", creationflags=subprocess.CREATE_NO_WINDOW)

                    self.stage.emit("正在清理旧版本 torch")
                    self.busy.emit(True)
                    run_pip_allow_fail(["uninstall", "-y", "torch", "torchvision", "torchaudio"])

                    self.stage.emit("正在安装依赖包（时间较长，请耐心等待）...")
                    self.busy.emit(True)
                    
                    if has_wheels:
                        run_pip(["install", "--no-index", "--find-links", wheel_dir, "torch", "faster-whisper", "transformers", "pyannote-audio"])
                    else:
                        if has_nvidia:
                            try:
                                self.stage.emit("检测到 NVIDIA，正在安装 CUDA 版 torch 及其 GPU 运行库...")
                                run_pip(["install", "torch", "--index-url", "https://download.pytorch.org/whl/cu118"])
                                run_pip(["install", "faster-whisper", "transformers", "pyannote-audio", "nvidia-cublas-cu12", "nvidia-cudnn-cu12"])
                            except Exception:
                                self.stage.emit("CUDA 版安装失败，回退安装 CPU 版依赖...")
                                run_pip(["install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
                                run_pip(["install", "faster-whisper", "transformers", "pyannote-audio"])
                        else:
                            run_pip(["install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
                            run_pip(["install", "faster-whisper", "transformers", "pyannote-audio"])

                    self.busy.emit(False)
                    self.stage.emit("依赖安装完成")
                    self.finished.emit()
                except Exception:
                    self.busy.emit(False)
                    self.error.emit(traceback.format_exc())

        self.btn_install_deps.setEnabled(False)
        self.stage_label.setText("正在安装依赖 ...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._install_worker = PipInstallWorker()
        self._install_worker.stage.connect(self._on_stage)
        self._install_worker.busy.connect(self._on_busy)

        def on_ok():
            self.btn_install_deps.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self._refresh_dep_status()
            if self._deps_ok():
                self.stage_label.setText("依赖已安装，可开始生成字幕")
            else:
                self.stage_label.setText("依赖安装完成，但检测依然失败（请查看日志）")

        def on_err(err):
            log.exception("安装转写依赖失败")
            self.btn_install_deps.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.stage_label.setText("❌ 安装失败（详情请查看 .runtime/logs/app.log）")
            QMessageBox.critical(self.parent_widget, "安装失败", "安装依赖失败，详情已写入日志：.runtime/logs/app.log")

        self._install_worker.finished.connect(on_ok)
        self._install_worker.error.connect(on_err)
        self._install_worker.start()

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

    def _open_model_directory(self):
        model_dir = WHISPER_MODELS_DIR
        os.makedirs(model_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(model_dir))
