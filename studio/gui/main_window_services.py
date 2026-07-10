# -*- coding: utf-8 -*-
"""MainWindow 的本地服务管理 mixin（VoxCPM / Ollama），从 gui_main 拆出；self 不变、行为一致。"""

import subprocess
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT, CONFIG_INI_FILE
)
import threading
import uuid
import configparser
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
from gui.subtitle_removal_page import SubtitleRemovalPage
from gui.live_clip_page import LiveClipPage
from gui.voice_clone_page import VoiceClonePage
from gui.voice_samples_page import VoiceSamplesPage
from gui.video_ocr_page import VideoOcrPage
from gui.image_folder_ocr_page import ImageFolderOcrPage
from utils.logger_utils import log, get_last_logs
from utils.account_manager import AccountManager
from core.creator_browser_controller import CreatorBrowserController
from utils.thread_worker import TaskWorker as Worker
from gui.threads import SystemMonitorThread, ComfyWSThread
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QDialog, QListWidget, 
                                 QListWidgetItem, QGridLayout, QFileDialog, 
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont


class ServicesMixin:
    def browse_voxcpm_model_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择 VoxCPM 模型目录", self.edit_voxcpm_model_path.text().strip())
        if dir_path:
            dir_path = os.path.abspath(dir_path)
            self.edit_voxcpm_model_path.setText(dir_path)

    def load_voxcpm_config(self):
        config = configparser.ConfigParser()
        model_path = ""
        port = 7861
        try:
            if os.path.exists(CONFIG_INI_FILE):
                config.read(CONFIG_INI_FILE, encoding='utf-8')
                if config.has_section('VoxCPM'):
                    model_path = config.get('VoxCPM', 'ModelPath', fallback="")
                    port = config.getint('VoxCPM', 'Port', fallback=7861)
        except Exception as e:
            log.error(f"加载 VoxCPM 配置失败: {e}")
        
        if not model_path or not os.path.exists(model_path):
            from config.paths import VOXCPM2_DIR
            default_path = os.path.join(VOXCPM2_DIR, "models", "openbmb__VoxCPM2")
            if os.path.isdir(default_path):
                model_path = os.path.abspath(default_path)
        
        self.edit_voxcpm_model_path.setText(model_path)
        self.spin_voxcpm_port.setValue(port)

        # Load voice clone params from ai_config
        if hasattr(self, 'ai_config'):
            self.vox_api_url_input.setText(self.ai_config.get("vox_api_url", "http://127.0.0.1:7861/v1/tts"))
            mode = self.ai_config.get("vox_mode", "api")
            idx = self.vox_mode_combo.findData(mode)
            if idx >= 0:
                self.vox_mode_combo.setCurrentIndex(idx)
            self.vox_timesteps_spin.setValue(self.ai_config.get("vox_timesteps", 20))
            self.vox_cfg_spin.setValue(self.ai_config.get("vox_cfg", 2.0))
            # VoxCPM 来源模式初始化（触发 _on_vox_source_changed 设置控件可见性）
            vox_source = self.ai_config.get("vox_source", "remote")
            sidx = self.vox_source_combo.findData(vox_source)
            if sidx >= 0:
                self.vox_source_combo.setCurrentIndex(sidx)
            else:
                self.vox_source_combo.setCurrentIndex(1)  # 默认 remote
            self._on_vox_source_changed(self.vox_source_combo.currentIndex())

    def _save_voxcpm_config_silent(self):
        config = configparser.ConfigParser()
        try:
            if os.path.exists(CONFIG_INI_FILE):
                config.read(CONFIG_INI_FILE, encoding='utf-8')
            if not config.has_section('VoxCPM'):
                config.add_section('VoxCPM')
            config.set('VoxCPM', 'ModelPath', self.edit_voxcpm_model_path.text().strip())
            config.set('VoxCPM', 'Port', str(self.spin_voxcpm_port.value()))
            with open(CONFIG_INI_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            # Also save voice clone params to ai_config
            if hasattr(self, 'ai_config'):
                port = self.spin_voxcpm_port.value()
                url = self.vox_api_url_input.text().strip()
                # Auto-fix: if the port in URL doesn't match spinbox, regenerate URL
                if url and f":{port}/" not in url and "/v1/tts" in url:
                    url = f"http://127.0.0.1:{port}/v1/tts"
                    self.vox_api_url_input.setText(url)
                self.ai_config["vox_api_url"] = url
                self.ai_config["vox_source"] = self.vox_source_combo.currentData()
                self.ai_config["vox_mode"] = self.vox_mode_combo.currentData()
                self.ai_config["vox_timesteps"] = self.vox_timesteps_spin.value()
                self.ai_config["vox_cfg"] = self.vox_cfg_spin.value()
                try:
                    import json, os
                    os.makedirs(os.path.dirname(self.ai_config_file), exist_ok=True)
                    with open(self.ai_config_file, 'w', encoding='utf-8') as f:
                        json.dump(self.ai_config, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    log.error(f"保存声音克隆参数到 ai_config 失败: {e}")
            return True
        except Exception as e:
            log.error(f"静默保存 VoxCPM 配置失败: {e}")
            return False

    def save_voxcpm_config(self):
        if self._save_voxcpm_config_silent():
            QMessageBox.information(self, "提示", "VoxCPM 配置参数保存成功！")
            self.refresh_llm_page_status()
        else:
            QMessageBox.critical(self, "错误", "保存 VoxCPM 配置失败，请检查文件权限。")

    def _on_vox_source_changed(self, index):
        """VoxCPM 来源模式切换：local 显示本地进程管理控件，remote 隐藏只留 API 地址。"""
        is_local = (self.vox_source_combo.currentData() == "local")
        # 本地专属控件：仅 local 模式可见
        for attr in ("vox_mode_combo", "edit_voxcpm_model_path", "_browse_vox_btn",
                     "spin_voxcpm_port", "btn_toggle_voxcpm"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(is_local)
        # 推理步数/CFG 在两种模式下都有意义，保留可见
        # API 地址 placeholder 提示
        if is_local:
            self.vox_api_url_input.setPlaceholderText("http://127.0.0.1:7861/v1/tts")
        else:
            self.vox_api_url_input.setPlaceholderText("http://远程服务器IP:7861/v1/tts")
            # remote 模式确保走 API（cli 是本地专属）
            api_idx = self.vox_mode_combo.findData("api")
            if api_idx >= 0:
                self.vox_mode_combo.setCurrentIndex(api_idx)

    def toggle_voxcpm_service(self):
        is_active = False
        if self.voxcpm_process and self.voxcpm_process.poll() is None:
            is_active = True
        else:
            port = self.spin_voxcpm_port.value()
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                s.close()
                is_active = True
            except Exception:
                pass
                
        if is_active:
            self.stop_voxcpm_service()
        else:
            self.start_voxcpm_service()

    def start_voxcpm_service(self):
        log.info("[VoxCPM] 启动流程开始")
        if self.voxcpm_process and self.voxcpm_process.poll() is None:
            log.info("[VoxCPM] 已有运行中进程")
            QMessageBox.information(self, "提示", "VoxCPM 服务已经在后台运行中。")
            return

        self._save_voxcpm_config_silent()
        log.info("[VoxCPM] 配置已保存")
        
        port = self.spin_voxcpm_port.value()
        log.info(f"[VoxCPM] 目标端口: {port}")
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.15)
            s.connect(("127.0.0.1", port))
            s.close()
            log.info(f"[VoxCPM] 端口 {port} 已被占用")
            QMessageBox.warning(self, "端口冲突", f"端口 {port} 已被占用，可能服务已启动，或者有其他程序占用了该端口。")
            self.refresh_llm_page_status()
            return
        except Exception:
            log.info(f"[VoxCPM] 端口 {port} 空闲")

        from gui.env_config_page import get_voxcpm_python
        python_exe = get_voxcpm_python()
        log.info(f"[VoxCPM] Python: {python_exe}")

        # Check GPU memory
        try:
            import torch
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory
                used  = torch.cuda.memory_allocated(0)
                free  = total - used
                free_gb = free / (1024**3)
                log.info(f"[VoxCPM] GPU空闲显存: {free_gb:.1f} GB")
                if free_gb < 4.0:
                    from utils.ollama_manager import OllamaManager, read_ollama_mode
                    # 仅本地内置 Ollama 才会占显存；远程模式无需询问
                    if read_ollama_mode() == "local":
                        ollama_running = OllamaManager.get().is_running()
                        log.info(f"[VoxCPM] Ollama运行中: {ollama_running}")
                        if ollama_running:
                            reply = QMessageBox.question(
                                self, "显存不足",
                                f"当前 GPU 空闲显存仅 {free_gb:.1f} GB，VoxCPM 启动可能失败。\n\n"
                                "是否停止 Ollama 释放显存后再启动 VoxCPM？",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                            )
                            if reply == QMessageBox.Yes:
                                OllamaManager.get().stop()
                                log.info("[VoxCPM] 已停止 Ollama")
                            else:
                                log.info("[VoxCPM] 用户选择不停止 Ollama")
        except Exception as e:
            log.warning(f"[VoxCPM] 显存检测失败: {e}")
        
        checkpoint = self.edit_voxcpm_model_path.text().strip()
        if not checkpoint:
            checkpoint = "openbmb/VoxCPM2"
        elif checkpoint and not checkpoint.startswith("openbmb/"):
            checkpoint = os.path.abspath(checkpoint)
            log.info(f"[VoxCPM] 模型路径为空，使用默认: {checkpoint}")
        else:
            log.info(f"[VoxCPM] 模型路径: {checkpoint}")
             
        listen_addr = f"127.0.0.1:{port}"
        api_server_script = os.path.abspath(os.path.join(WORKSPACE_ROOT, "studio", "voxcpm_api_server.py"))
        log.info(f"[VoxCPM] API脚本: {api_server_script}")
        
        cmd = [
            python_exe,
            api_server_script,
            "--listen", listen_addr,
            "--checkpoint-path", checkpoint
        ]
        log.info(f"[VoxCPM] 命令: {' '.join(cmd)}")
        
        try:
            log_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "logs"))
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "voxcpm_api.log")
            log.info(f"[VoxCPM] 日志文件: {log_path}")
            self.voxcpm_log_file = open(log_path, "a", encoding="utf-8")
            
            self.voxcpm_process = subprocess.Popen(
                cmd,
                stdout=self.voxcpm_log_file,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            log.info(f"[VoxCPM] 子进程 PID: {self.voxcpm_process.pid}")

            self.voxcpm_status_timer.start(1000)
            self.llm_vox_status_val.setText(f"<font color='#f1c40f'><b>⏳ 正在启动 (端口: {port})...</b></font>")
            self.btn_toggle_voxcpm.setText("⏳ 正在启动 VoxCPM...")
            self.btn_toggle_voxcpm.setEnabled(False)
            log.info("[VoxCPM] 启动流程完成，等待服务就绪")

            # Delayed check
            QTimer.singleShot(2000, lambda: self._check_voxcpm_crash(log_path))
        except Exception as e:
            log.error(f"大模型页面启动 VoxCPM 失败: {e}")
            QMessageBox.critical(self, "启动失败", f"启动 VoxCPM 服务失败：\n{e}")

    def stop_voxcpm_service(self, show_prompt=True):
        if self.voxcpm_process:
            proc = self.voxcpm_process
            self.voxcpm_process = None
            if proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                    
            if self.voxcpm_log_file:
                try:
                    self.voxcpm_log_file.close()
                except Exception:
                    pass
                self.voxcpm_log_file = None
            log.info("VoxCPM API server stopped from LLM config page")
        else:
            if show_prompt:
                QMessageBox.information(
                    self,
                    "提示",
                    "当前检测到的 VoxCPM API 服务是由外部独立启动的进程（或在声音克隆页启动），无法在此处关闭。您可以前往声音克隆页或外部任务管理器中关闭。"
                )
                
        if self.voxcpm_status_timer.isActive():
            self.voxcpm_status_timer.stop()
            
        self.btn_toggle_voxcpm.setText("▶️ 启动 VoxCPM 服务")
        self.btn_toggle_voxcpm.setEnabled(True)
        self.refresh_llm_page_status()

    def _check_voxcpm_crash(self, log_path):
        """启动后延迟检查进程是否秒退"""
        if not self.voxcpm_process:
            return
        ret = self.voxcpm_process.poll()
        if ret is None:
            return  # still running, server is loading
        # Process died
        self.voxcpm_process = None
        try:
            if self.voxcpm_log_file: self.voxcpm_log_file.close()
        except Exception: pass
        self.voxcpm_log_file = None
        err_detail = ""
        try:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                    lines = lf.readlines()
                    err_detail = "".join(lines[-8:]).strip() or f"退出码: {ret}"
        except Exception:
            err_detail = f"退出码: {ret}"
        self.btn_toggle_voxcpm.setText("▶️ 启动 VoxCPM 服务")
        self.btn_toggle_voxcpm.setEnabled(True)
        self.llm_vox_status_val.setText(f"<font color='#dc2626'>❌ 启动失败</font>")
        QMessageBox.critical(self, "启动失败", f"VoxCPM 服务启动后立即退出。\n\n{err_detail}")

    def _check_voxcpm_process_status(self):
        running = False
        if self.voxcpm_process:
            ret = self.voxcpm_process.poll()
            if ret is not None:
                self.voxcpm_process = None
                if self.voxcpm_log_file:
                    try:
                        self.voxcpm_log_file.close()
                    except Exception:
                        pass
                    self.voxcpm_log_file = None
                self.btn_toggle_voxcpm.setText("▶️ 启动 VoxCPM 服务")
                self.btn_toggle_voxcpm.setEnabled(True)
                if self.voxcpm_status_timer.isActive():
                    self.voxcpm_status_timer.stop()
                log.info(f"VoxCPM process terminated with exit code {ret}")
            else:
                running = True
                
        port = self.spin_voxcpm_port.value()
        import socket
        port_open = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect(("127.0.0.1", port))
            s.close()
            port_open = True
        except Exception:
            pass

        if port_open:
            self.llm_vox_status_val.setText(f"<font color='#16a34a'><b>✅ 正在运行 (监听端口: {port})</b></font>")
            self.btn_toggle_voxcpm.setText("⏹️ 关闭 VoxCPM 服务")
            self.btn_toggle_voxcpm.setEnabled(True)
        else:
            if running:
                self.llm_vox_status_val.setText(f"<font color='#f97316'><b>⏳ 正在启动 (端口: {port})...</b></font>")
                self.btn_toggle_voxcpm.setText("⏳ 正在启动 VoxCPM...")
                self.btn_toggle_voxcpm.setEnabled(False)
            else:
                self.llm_vox_status_val.setText(f"<font color='#7f8c8d'><b>已关闭 (端口 {port} 空闲)</b></font>")
                self.btn_toggle_voxcpm.setText("▶️ 启动 VoxCPM 服务")
                self.btn_toggle_voxcpm.setEnabled(True)

    def _on_ollama_mode_changed(self, index):
        """Ollama 来源模式切换：local 显示进程管理控件，remote 隐藏它们只保留连接检测。"""
        is_local = (self.ollama_mode_combo.currentData() == "local")
        # 进程管理 & 本地专属控件：仅 local 模式可见
        for attr in ("btn_ollama_start", "btn_ollama_stop",
                     "lbl_runners_warn", "btn_fix_runners", "runners_bar",
                     "ollama_pull_input", "btn_ollama_pull",
                     "ollama_pull_bar", "ollama_progress_lbl"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(is_local)
        # 视觉模型地址输入框 placeholder 提示
        if is_local:
            self.llm_vision_api_url_input.setPlaceholderText("http://127.0.0.1:11434")
        else:
            self.llm_vision_api_url_input.setPlaceholderText("http://远程服务器IP:11434")
        # remote 模式下 local 专属控件若有残留状态，先清掉 runners 警告
        if not is_local:
            self.lbl_runners_warn.setVisible(False)
            self.btn_fix_runners.setVisible(False)
        # 切换后立即刷新一次状态（remote 检测连通性，local 检测进程）
        self._ollama_refresh_status()

    def _ollama_refresh_status(self):
        from utils.ollama_manager import OllamaManager, OLLAMA_BIN, read_ollama_mode
        mgr = OllamaManager.get()
        is_remote = (read_ollama_mode() == "remote")

        # ── 远程模式：跳过本地二进制/runners 检查，直接检测远程连通性 ──
        if is_remote:
            self.lbl_runners_warn.setVisible(False)
            self.btn_fix_runners.setVisible(False)
            if mgr.is_running():
                models = mgr.list_local_models()
                self.ollama_status_lbl.setText("● 已连接（远程）")
                self._set_ollama_status_state("green")
                self.ollama_models_lbl.setText(
                    "远程模型: " + ("、".join(models) if models else "（无）")
                )
                cur = self.llm_vision_model_input.currentText().strip()
                self.llm_vision_model_input.blockSignals(True)
                self.llm_vision_model_input.clear()
                for m in models:
                    self.llm_vision_model_input.addItem(m)
                if cur:
                    self.llm_vision_model_input.setCurrentText(cur)
                self.llm_vision_model_input.blockSignals(False)
            else:
                self.ollama_status_lbl.setText("● 远程连接失败")
                self._set_ollama_status_state("red")
                self.ollama_models_lbl.setText("请检查远程地址及网络")
            return

        # ── 本地模式：原有逻辑 ──
        if not mgr.is_binary_present():
            self.ollama_status_lbl.setText("● ollama.exe 未找到")
            self._set_ollama_status_state("red")
            self.ollama_models_lbl.setText(f"请将 ollama.exe 放到：{OLLAMA_BIN}")
            self.lbl_runners_warn.setVisible(False)
            self.btn_fix_runners.setVisible(False)
            return

        # 检测推理运行库（llama-server.exe）
        runners_ok = mgr.runners_ok()
        self.lbl_runners_warn.setVisible(not runners_ok)
        self.btn_fix_runners.setVisible(not runners_ok)

        if mgr.is_running():
            models = mgr.list_local_models()
            status = "● 运行中" if runners_ok else "● 运行中（推理不可用）"
            state = "green" if runners_ok else "yellow"
            self.ollama_status_lbl.setText(status)
            self._set_ollama_status_state(state)
            self.ollama_models_lbl.setText(
                "已下载模型: " + ("、".join(models) if models else "（无）")
            )
            # 把已下载模型填入「当前视觉模型」下拉框
            cur = self.llm_vision_model_input.currentText().strip()
            self.llm_vision_model_input.blockSignals(True)
            self.llm_vision_model_input.clear()
            for m in models:
                self.llm_vision_model_input.addItem(m)
            if cur:
                self.llm_vision_model_input.setCurrentText(cur)
            self.llm_vision_model_input.blockSignals(False)
        else:
            self.ollama_status_lbl.setText("● 未运行")
            self._set_ollama_status_state("gray")
            self.ollama_models_lbl.setText("已下载模型: (需启动后查看)")

    def _ollama_start(self):
        from utils.ollama_manager import OllamaManager

        class _Worker(QThread):
            done = Signal(bool, str)
            def run(self):
                ok, msg = OllamaManager.get().start()
                self.done.emit(ok, msg)

        self.btn_ollama_start.setEnabled(False)
        self.ollama_status_lbl.setText("● 启动中...")
        self._set_ollama_status_state("yellow")
        self._ollama_start_worker = _Worker()
        self._ollama_start_worker.done.connect(self._ollama_start_done)
        self._ollama_start_worker.start()

    def _ollama_start_done(self, ok: bool, msg: str):
        self.btn_ollama_start.setEnabled(True)
        if ok:
            self._ollama_refresh_status()
            if not self.llm_vision_api_url_input.text().strip():
                self.llm_vision_api_url_input.setText("http://127.0.0.1:11434")
            # 启动成功后，后台预热（把视觉模型加载进显存），避免测试连接时冷加载读超时
            self._ollama_warmup()
        else:
            self.ollama_status_lbl.setText(f"● 启动失败: {msg}")
            self._set_ollama_status_state("red")

    def _ollama_warmup(self):
        """启动成功后后台预热视觉模型；预热期间状态显示「模型加载中」。"""
        from utils.ollama_manager import OllamaManager
        mgr = OllamaManager.get()

        model = mgr.get_configured_model()
        if not model:
            # 未配置模型，无东西可预热，保持正常状态
            return

        # 进入预热：状态置为「加载中」
        self.ollama_status_lbl.setText("● 运行中（模型加载中…）")
        self._set_ollama_status_state("yellow")

        def _run():
            try:
                ok, wmsg = mgr.warmup_model(model)
                if ok:
                    log.info(f"视觉模型预热完成: {wmsg}")
                else:
                    log.warning(f"视觉模型预热未成功（不影响启动结果）: {wmsg}")
            except Exception as e:
                log.warning(f"视觉模型预热异常（不影响启动结果）: {e}")
            # 无论成败，刷新状态恢复为正常显示（运行中 / 未运行）
            QTimer.singleShot(0, self._ollama_refresh_status)

        # 持有线程引用避免被 GC
        self._ollama_warmup_thread = threading.Thread(target=_run, daemon=True)
        self._ollama_warmup_thread.start()

    def _ollama_stop(self):
        from utils.ollama_manager import OllamaManager
        OllamaManager.get().stop()
        self._ollama_refresh_status()

    def _set_ollama_status_state(self, state):
        self.ollama_status_lbl.setProperty("state", state)
        self.ollama_status_lbl.style().unpolish(self.ollama_status_lbl)
        self.ollama_status_lbl.style().polish(self.ollama_status_lbl)

    def _ollama_fix_runners(self):
        """下载 Ollama 完整包，解压 lib/（llama-server.exe）到 bin/。"""
        from utils.ollama_manager import OllamaManager
        mgr = OllamaManager.get()

        class _FixWorker(QThread):
            progress_sig = Signal(int, int, str)
            done = Signal(bool, str)
            def __init__(self, mgr):
                super().__init__()
                self.mgr = mgr
            def run(self):
                ok, msg = self.mgr.download_runners(
                    progress_cb=lambda d, t, lbl: self.progress_sig.emit(d, t, lbl)
                )
                self.done.emit(ok, msg)

        class _RestartWorker(QThread):
            done = Signal(bool, str)
            def __init__(self, mgr):
                super().__init__()
                self.mgr = mgr
            def run(self):
                self.mgr.stop()
                ok, msg = self.mgr.start()
                self.done.emit(ok, msg)

        def _on_progress(downloaded, total, label):
            self.runners_lbl.setText(label)
            if total > 0:
                self.runners_bar.setRange(0, 100)
                self.runners_bar.setValue(int(downloaded * 100 / total))
            else:
                self.runners_bar.setRange(0, 0)

        def _on_restart_done(ok, msg):
            self.runners_bar.setRange(0, 100)
            self.runners_bar.setVisible(False)
            self.btn_ollama_start.setEnabled(True)
            self.btn_ollama_stop.setEnabled(True)
            self._ollama_refresh_status()

        def _on_done(ok, msg):
            self.btn_fix_runners.setEnabled(True)
            self.runners_bar.setRange(0, 100)
            self.runners_bar.setVisible(False)
            if ok:
                self.runners_lbl.setText(f"✅ {msg}  正在重启 Ollama…")
                self.runners_lbl.setVisible(True)
                self.btn_ollama_start.setEnabled(False)
                self.btn_ollama_stop.setEnabled(False)
                self.runners_bar.setRange(0, 0)
                self.runners_bar.setVisible(True)
                self._restart_worker = _RestartWorker(mgr)
                self._restart_worker.done.connect(_on_restart_done)
                self._restart_worker.start()
            else:
                self.runners_lbl.setVisible(False)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "修复失败", msg)

        self.btn_fix_runners.setEnabled(False)
        self.runners_bar.setRange(0, 0)
        self.runners_bar.setVisible(True)
        self.runners_lbl.setText("准备下载…")
        self.runners_lbl.setVisible(True)

        self._fix_worker = _FixWorker(mgr)
        self._fix_worker.progress_sig.connect(_on_progress)
        self._fix_worker.done.connect(_on_done)
        self._fix_worker.start()

    def _ollama_pull(self):
        from utils.ollama_manager import OllamaManager
        model = self.ollama_pull_input.currentData() or ""
        if not model:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先从下拉框选择要下载的模型。")
            return
        mgr = OllamaManager.get()

        class _PullWorker(QThread):
            progress_sig = Signal(str, int)
            done = Signal(bool, str)
            def __init__(self, mgr, model):
                super().__init__()
                self._mgr = mgr
                self._model = model
            def run(self):
                def _cb(status, pct):
                    self.progress_sig.emit(status, pct if pct is not None else -1)
                ok, msg = self._mgr.pull_model(self._model, progress_cb=_cb)
                self.done.emit(ok, msg)

        self.btn_ollama_pull.setEnabled(False)
        self.ollama_pull_bar.setValue(0)
        self.ollama_pull_bar.show()
        self.ollama_progress_lbl.setText(f"⬇ 正在下载 {model}...")

        def _on_progress(status: str, pct: int):
            self.ollama_progress_lbl.setText(status)
            if pct >= 0:
                self.ollama_pull_bar.setValue(pct)
            else:
                self.ollama_pull_bar.setRange(0, 0)

        self._pull_worker = _PullWorker(mgr, model)
        self._pull_worker.progress_sig.connect(_on_progress)
        self._pull_worker.done.connect(self._ollama_pull_done)
        self._pull_worker.start()

    def _ollama_pull_done(self, ok: bool, msg: str):
        self.btn_ollama_pull.setEnabled(True)
        self.ollama_pull_bar.setRange(0, 100)
        self.ollama_pull_bar.hide()
        if ok:
            self.ollama_progress_lbl.setText(f"✅ {msg}")
            model = self.ollama_pull_input.currentData() or ""
            if model and not self.llm_vision_model_input.currentText().strip():
                self.llm_vision_model_input.setCurrentText(model)
            self._ollama_refresh_status()
        else:
            self.ollama_progress_lbl.setText(f"❌ 下载失败: {msg}")
