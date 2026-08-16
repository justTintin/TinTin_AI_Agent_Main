# -*- coding: utf-8 -*-
"""MainWindow 的 AI / 大模型配置 mixin（ai_config 读写、连接测试、Ollama 后端切换），从 gui_main 拆出。"""

import subprocess
import time
import json
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT, CONFIG_INI_FILE, DREAMINA_EXE
)
import threading
import uuid
import configparser
from utils.platform_utils import create_no_window_flag
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvConfigPage, EnvInstallWorker
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
from utils import config_manager as cm


class AIConfigMixin:
    def save_llm_config(self):
        # 关键：先从所有 UI 收集最新值，避免保存时用过期内存值覆盖其它字段
        self._collect_all_config_from_ui()
        try:
            cm.save_ai_config(self.ai_config)
            QMessageBox.information(self, "成功", "大模型配置已保存。")
            log.info("LLM configuration saved successfully.")
        except Exception as e:
            log.error(f"保存大模型配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _collect_all_config_from_ui(self):
        """从所有 UI 输入框收集当前值到 self.ai_config（不写文件）。

        关键修复：任何保存按钮在写文件前都必须先调用本方法，
        否则会用过期的内存值覆盖用户在其它 Tab 已修改但未保存的字段。
        所有 getattr 都容忍控件不存在（不同页面加载顺序）。
        """
        # ComfyUI / VoiceClone 直连地址
        comfyui_input = getattr(self, "comfyui_input", None)
        if comfyui_input is not None:
            self.ai_config["comfyui_addr"] = comfyui_input.text().strip()
        voice_clone_input = getattr(self, "voice_clone_input", None)
        if voice_clone_input is not None:
            self.ai_config["voice_clone_addr"] = voice_clone_input.text().strip()
        # LLM 文本模型
        if getattr(self, "llm_provider_combo", None) is not None:
            self.ai_config["llm_provider"] = self.llm_provider_combo.currentData()
        if getattr(self, "llm_api_key_input", None) is not None:
            self.ai_config["llm_api_key"] = self.llm_api_key_input.text().strip()
        if getattr(self, "llm_api_url_input", None) is not None:
            self.ai_config["llm_api_url"] = self.llm_api_url_input.text().strip()
        if getattr(self, "llm_model_input", None) is not None:
            self.ai_config["llm_model"] = self.llm_model_input.text().strip()
        # 视觉模型
        if getattr(self, "llm_vision_api_url_input", None) is not None:
            self.ai_config["llm_vision_api_url"] = self.llm_vision_api_url_input.text().strip()
        # 统一服务端地址
        server_url = getattr(self, "compute_server_input", None)
        if server_url is not None:
            self.ai_config["compute_server_url"] = server_url.text().strip()
        # Whisper / CLIP
        whisper_url = getattr(self, "whisper_api_url_input", None)
        if whisper_url is not None:
            self.ai_config["whisper_api_url"] = whisper_url.text().strip()
        clip_url = getattr(self, "clip_api_url_input", None)
        if clip_url is not None:
            self.ai_config["clip_api_url"] = clip_url.text().strip()
        # OCR（服务端 /material/ocr）
        ocr_url = getattr(self, "ocr_api_url_input", None)
        if ocr_url is not None:
            self.ai_config["ocr_api_url"] = ocr_url.text().strip()
        # VoxCPM
        vox_url = getattr(self, "vox_api_url_input", None)
        if vox_url is not None:
            self.ai_config["vox_api_url"] = vox_url.text().strip()
        vox_timesteps = getattr(self, "vox_timesteps_spin", None)
        if vox_timesteps is not None:
            self.ai_config["vox_timesteps"] = vox_timesteps.value()
        vox_cfg = getattr(self, "vox_cfg_spin", None)
        if vox_cfg is not None:
            self.ai_config["vox_cfg"] = vox_cfg.value()
        self.ai_config["vox_source"] = "remote"
        self.ai_config["vox_mode"] = "api"
        # RunningHub
        rh_key = getattr(self, "runninghub_api_key_input", None)
        if rh_key is not None:
            self.ai_config["runninghub_api_key"] = rh_key.text().strip()
        rh_url = getattr(self, "runninghub_base_url_input", None)
        if rh_url is not None:
            self.ai_config["runninghub_base_url"] = rh_url.text().strip().rstrip("/")
        rh_comfy_auth = getattr(self, "runninghub_comfy_auth_input", None)
        if rh_comfy_auth is not None:
            self.ai_config["runninghub_comfy_auth"] = rh_comfy_auth.text().strip()
        rh_comfy_identify = getattr(self, "runninghub_comfy_identify_input", None)
        if rh_comfy_identify is not None:
            self.ai_config["runninghub_comfy_identify"] = rh_comfy_identify.text().strip()
        rh_access_token = getattr(self, "runninghub_access_token_input", None)
        if rh_access_token is not None:
            self.ai_config["runninghub_access_token"] = rh_access_token.text().strip()
        rh_personal_queue = getattr(self, "runninghub_use_personal_queue_check", None)
        if rh_personal_queue is not None:
            self.ai_config["runninghub_use_personal_queue"] = rh_personal_queue.isChecked()

    def _save_all_ai_config(self):
        """保存所有模型Tab的配置（含VoxCPM和统一服务端地址），由「保存全部」按钮触发。"""
        # 关键：先从所有 UI 收集最新值，避免用过期内存值覆盖
        self._collect_all_config_from_ui()
        try:
            cm.save_ai_config(self.ai_config)
            QMessageBox.information(self, "成功", "所有模型配置已保存。")
            log.info("All AI configuration saved successfully.")
        except Exception as e:
            log.error(f"保存全部AI配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _on_server_url_changed(self, url):
        """统一服务端地址变更时，联动更新各Tab的API地址。
        视觉模型/Whisper/CLIP 直接使用统一地址，VoxCPM 追加后缀。"""
        url = url.strip()
        if not url:
            return
        # 视觉模型（Ollama 远程）— 始终与统一地址同步
        vm = getattr(self, "llm_vision_api_url_input", None)
        if vm:
            vm.setText(url)
        # Whisper — 始终与统一地址同步
        w = getattr(self, "whisper_api_url_input", None)
        if w:
            w.setText(url)
        # CLIP — 始终与统一地址同步
        c = getattr(self, "clip_api_url_input", None)
        if c:
            c.setText(url)
        # PaddleOCR — 始终与统一地址同步（服务端 /material/ocr）
        o = getattr(self, "ocr_api_url_input", None)
        if o:
            o.setText(url)
        # VoxCPM — 追加 /voxcpm/tts 后缀后同步
        v = getattr(self, "vox_api_url_input", None)
        if v:
            v.setText(url + "/voxcpm/tts")

    def refresh_llm_page_status(self):
        if not hasattr(self, "env_config_tool"):
            return
            
        # If we have cached info already, show it immediately first
        if self.env_config_tool.cached_info:
            self._update_llm_page_ui(self.env_config_tool.cached_info)
            
        # Trigger an async refresh to update the cache and UI in background
        self.env_config_tool.refresh_status_async(self._on_llm_env_checked)

        # 刷新内置 Ollama 服务检测
        if hasattr(self, "_ollama_refresh_status"):
            self._ollama_refresh_status()

    def _on_llm_env_checked(self, info):
        self._update_llm_page_ui(info)

    def _update_llm_page_ui(self, info):
        if not info:
            return
        # Update VoxCPM status label
        if info.get("voxcpm_ok", False):
            vox_status = f"<font color='#16a34a'><b>完成： {info.get('voxcpm_status', '')}</b></font>"
        elif info.get("voxcpm_installed", False):
            vox_status = f"<font color='#d97706'><b>注意： {info.get('voxcpm_status', '')}</b></font>"
        else:
            vox_status = f"<font color='#dc2626'><b>失败： {info.get('voxcpm_status', '')}</b></font>"
        self.llm_vox_status_val.setText(vox_status)

        # Update PaddleOCR status labels
        if info.get("paddleocr_ok", False):
            paddle_status = f"<font color='#16a34a'><b>完成： {info.get('paddleocr_status', '')}</b></font>"
        else:
            paddle_status = f"<font color='#dc2626'><b>失败： {info.get('paddleocr_status', '')}</b></font>"
        self.llm_paddle_status_val.setText(paddle_status)
        
        p_models_status = f"<font color='#2563eb'><b>{', '.join(info.get('paddleocr_models', []))}</b></font> (存放目录: {info.get('paddleocr_models_dir', '')})"
        self.llm_paddle_models_val.setText(p_models_status)

    def load_ai_config(self):
        default_config = {
            "comfyui_addr": "http://X.X.X.X:8188",
            "voice_clone_addr": "http://X.X.X.X:7860",
            "llm_provider": "deepseek",
            "llm_api_key": "",
            "llm_api_url": "https://api.deepseek.com",
            "llm_model": "deepseek-v4-flash",
            "llm_vision_api_url": "",
            "compute_server_url": "",
            "whisper_api_url": "",
            "clip_api_url": "",
            "ocr_api_url": "",
            "vox_api_url": "",
            "vox_source": "remote",
            "vox_mode": "api",
            "vox_timesteps": 20,
            "vox_cfg": 2.0,
            "runninghub_api_key": "",
            "runninghub_base_url": "https://www.runninghub.cn",
            "runninghub_comfy_auth": "",
            "runninghub_comfy_identify": "",
            "runninghub_access_token": "",
            "runninghub_use_personal_queue": True
        }
        loaded = cm.load_config("ai_config")
        if loaded:
            self.ai_config = loaded
            for k, v in default_config.items():
                if k not in self.ai_config:
                    self.ai_config[k] = v
            return

        # 旧版工程根目录 ai_config.json（迁移一次后写入统一位置）
        legacy = getattr(self, "ai_config_legacy_file", "") or ""
        if legacy and os.path.exists(legacy):
            try:
                with open(legacy, 'r', encoding='utf-8') as f:
                    self.ai_config = json.load(f)
                for k, v in default_config.items():
                    if k not in self.ai_config:
                        self.ai_config[k] = v
                cm.save_ai_config(self.ai_config)
                return
            except Exception as e:
                log.error(f"加载 AI 配置失败: {e}")
        self.ai_config = default_config

    def save_ai_config(self):
        # 关键：先从所有 UI 收集最新值，避免保存时用过期内存值覆盖其它字段
        self._collect_all_config_from_ui()

        try:
            cm.save_ai_config(self.ai_config)
            QMessageBox.information(self, "成功", "AI 配置已保存。")
            log.info("AI configuration saved successfully.")
        except Exception as e:
            log.error(f"保存 AI 配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def test_ai_connections(self):
        comfyui_addr = self.comfyui_input.text().strip().rstrip("/")
        voice_addr = self.voice_clone_input.text().strip().rstrip("/")
        
        results = []
        try:
            import requests
            from utils.http_client import http_get
            from utils import comfyui_client as comfy
            # Test ComfyUI：外部地址 + 本地引擎双后端
            if comfyui_addr and comfy.is_alive(comfyui_addr):
                results.append("ComfyUI(外部): 完成： 在线")
            elif comfyui_addr:
                results.append("ComfyUI(外部):  无法连接")
            else:
                results.append("ComfyUI(外部):  未配置")
            local = comfy.ComfyUILocal.get()
            if not local.is_present():
                results.append("ComfyUI(本地):  未安装 (apps/comfyui)")
            elif local.is_running():
                results.append("ComfyUI(本地): 完成： 运行中")
            else:
                results.append("ComfyUI(本地):  已就位 (未运行，提交任务时自动启动)")

            # Test Voice Clone
            try:
                res = http_get(voice_addr, timeout=5)
                results.append(f"克隆声音: {'完成： 在线' if res.status_code == 200 else ' 异常 ('+str(res.status_code)+')'}")
            except:
                results.append("克隆声音:  无法连接")
            
            QMessageBox.information(self, "测试结果", "\n".join(results))
        except Exception as e:
            QMessageBox.critical(self, "测试失败", str(e))

    def _on_llm_provider_changed(self, index):
        provider = self.llm_provider_combo.currentData()
        presets = {
            "deepseek":     ("https://api.deepseek.com",                          "deepseek-v4-flash"),
            "openai":       ("https://api.openai.com/v1",                          "gpt-4o"),
            "ollama":       ("http://localhost:11434/v1",                          "qwen2.5:7b"),
            "dashscope":    ("https://dashscope.aliyuncs.com/compatible-mode/v1",  "qwen-plus"),
            "zhipu":        ("https://open.bigmodel.cn/api/paas/v4",               "glm-4-flash"),
            "moonshot":     ("https://api.moonshot.cn/v1",                         "moonshot-v1-8k"),
            "custom":       ("", ""),
        }
        url, model = presets.get(provider, ("", ""))
        if provider == "custom":
            # 自定义模式：API 地址恢复可编辑，清空占位
            self.llm_api_url_input.setReadOnly(False)
            self.llm_api_url_input.setStyleSheet("")
            self.llm_api_url_input.setPlaceholderText("https://your-api-endpoint.com/v1")
            self.llm_model_input.setPlaceholderText("your-model-name")
        else:
            # 预设提供商：地址只读，自动填充
            _ro = "QLineEdit { background-color: #3a3a3a; color: #909090; border: 1px solid #555; }"
            self.llm_api_url_input.setReadOnly(True)
            self.llm_api_url_input.setStyleSheet(_ro)
            if url:
                self.llm_api_url_input.setText(url)
            if model:
                self.llm_model_input.setText(model)

    # ──────────────────── Ollama 管理 ────────────────────

    def _test_llm_connection(self):
        sender = self.sender()
        btn = sender if sender else (self.btn_test_llm if hasattr(self, "btn_test_llm") else None)
        if btn:
            btn.setEnabled(False)
        self.llm_status_lbl.setText("正在测试...")
        self.llm_status_lbl.setStyleSheet("color: #f39c12;")

        model = self.llm_model_input.text().strip() or "deepseek-v4-flash"
        self._llm_test_worker = self._create_proxy_test_worker(model, self.llm_status_lbl, btn)
        self._llm_test_worker.start()

    def _create_proxy_test_worker(self, model, status_lbl, btn):
        class _ProxyTestWorker(QThread):
            done = Signal(bool, str)
            def __init__(self, mdl):
                super().__init__()
                self.mdl = mdl
            def run(self):
                try:
                    from utils.llm_proxy import llm_chat
                    llm_chat("", "Hi", model=self.mdl, timeout=10, max_tokens=5)
                    self.done.emit(True, f"完成： 连接成功 ({self.mdl})")
                except RuntimeError as e:
                    self.done.emit(False, f"失败： {e}")
                except Exception as e:
                    self.done.emit(False, f"失败： 连接失败: {str(e)[:80]}")

        def _on_done(ok, text):
            status_lbl.setText(text)
            status_lbl.setStyleSheet(
                "color: #2ecc71; font-weight: bold;" if ok else "color: #e74c3c;"
            )
            if btn:
                btn.setEnabled(True)

        w = _ProxyTestWorker(model)
        w.done.connect(_on_done)
        return w

    def _test_vision_connection(self):
        """测试视觉模型连接：模型由服务端选择，客户端只测试服务端是否可达。"""
        sender = self.sender()
        if sender:
            sender.setEnabled(False)
        self.vision_status_lbl.setText("正在测试...")
        self.vision_status_lbl.setStyleSheet("color: #f39c12;")

        # 视觉模型由服务端选择，客户端不再指定 model
        class _TestWorker(QThread):
            done = Signal(bool, str, str)

            def run(self):
                from utils.llm_proxy import llm_chat
                try:
                    llm_chat("", "Hi", model=None, max_tokens=5, timeout=120)
                    self.done.emit(True, "完成： 连接成功（视觉模型由服务端选择）", "#2ecc71")
                except RuntimeError as e:
                    err = str(e)[:80]
                    if "Read timed out" in err or "ReadTimeout" in err or "超时" in err:
                        self.done.emit(False, "模型可能正在加载，请稍后重试", "#f39c12")
                    elif "404" in err or "not found" in err.lower():
                        self.done.emit(False, "失败： 服务端接口不存在 (404)", "#e74c3c")
                    elif "未配置服务端" in err:
                        self.done.emit(False, "失败： 未配置服务端地址", "#e74c3c")
                    else:
                        self.done.emit(False, f"失败： 连接失败: {err}", "#e74c3c")
                except Exception as e:
                    self.done.emit(False, f"失败： 连接失败: {str(e)[:80]}", "#e74c3c")

        def _on_done(ok, text, color):
            self.vision_status_lbl.setText(text)
            self.vision_status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            if sender:
                sender.setEnabled(True)

        self._vision_test_worker = _TestWorker()
        self._vision_test_worker.done.connect(_on_done)
        self._vision_test_worker.start()

    def _test_vox_connection(self):
        """测试远程 VoxCPM TTS 服务连接。"""
        sender = self.sender()
        if sender: sender.setEnabled(False)
        self.llm_vox_status_val.setText("正在测试...")
        self.llm_vox_status_val.setStyleSheet("color: #f39c12;")

        api_url = self.vox_api_url_input.text().strip()
        if not api_url:
            self.llm_vox_status_val.setText("注意： 请填写 API 地址")
            self.llm_vox_status_val.setStyleSheet("color: #f39c12;")
            if sender: sender.setEnabled(True)
            return

        def _run():
            import requests
            from utils.http_client import http_get
            try:
                base = api_url.rstrip("/v1/tts").rstrip("/voxcpm/tts").rstrip("/")
                r = http_get(f"{base}/voxcpm/health", timeout=5, quiet=True)
                if r.status_code == 200:
                    self.llm_vox_status_val.setText("完成： 连接成功")
                    self.llm_vox_status_val.setStyleSheet("color: #2ecc71;")
                else:
                    self.llm_vox_status_val.setText(f"失败： HTTP {r.status_code}")
                    self.llm_vox_status_val.setStyleSheet("color: #e74c3c;")
            except Exception as e:
                self.llm_vox_status_val.setText(f"失败： 连接失败: {str(e)[:60]}")
                self.llm_vox_status_val.setStyleSheet("color: #e74c3c;")
            if sender: sender.setEnabled(True)

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _test_whisper_connection(self):
        """测试远程 Whisper ASR 服务连接。"""
        sender = self.sender()
        if sender: sender.setEnabled(False)
        self.whisper_status_lbl.setText("正在测试...")
        self.whisper_status_lbl.setStyleSheet("color: #f39c12;")

        api_url = self.whisper_api_url_input.text().strip()
        if not api_url:
            self.whisper_status_lbl.setText("注意： 请填写 ASR 服务地址")
            self.whisper_status_lbl.setStyleSheet("color: #f39c12;")
            if sender: sender.setEnabled(True)
            return

        def _run():
            import requests
            from utils.http_client import http_get
            try:
                base = api_url.rstrip("/")
                r = http_get(f"{base}/whisper/health", timeout=5, quiet=True)
                if r.status_code == 200:
                    self.whisper_status_lbl.setText("完成： 连接成功")
                    self.whisper_status_lbl.setStyleSheet("color: #2ecc71;")
                else:
                    self.whisper_status_lbl.setText(f"失败： HTTP {r.status_code}")
                    self.whisper_status_lbl.setStyleSheet("color: #e74c3c;")
            except Exception as e:
                self.whisper_status_lbl.setText(f"失败： 连接失败: {str(e)[:60]}")
                self.whisper_status_lbl.setStyleSheet("color: #e74c3c;")
            if sender: sender.setEnabled(True)

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _test_clip_connection(self):
        """测试远程 CLIP embedding 服务连接。"""
        sender = self.sender()
        if sender: sender.setEnabled(False)
        self.clip_status_lbl.setText("正在测试...")
        self.clip_status_lbl.setStyleSheet("color: #f39c12;")

        api_url = self.clip_api_url_input.text().strip()
        if not api_url:
            self.clip_status_lbl.setText("注意： 请填写 CLIP API 地址")
            self.clip_status_lbl.setStyleSheet("color: #f39c12;")
            if sender: sender.setEnabled(True)
            return

        def _run():
            import requests
            from utils.http_client import http_get
            try:
                base = api_url.rstrip("/")
                r = http_get(f"{base}/clip/health", timeout=5, quiet=True)
                if r.status_code == 200:
                    self.clip_status_lbl.setText("完成： 连接成功")
                    self.clip_status_lbl.setStyleSheet("color: #2ecc71;")
                else:
                    self.clip_status_lbl.setText(f"失败： HTTP {r.status_code}")
                    self.clip_status_lbl.setStyleSheet("color: #e74c3c;")
            except Exception as e:
                self.clip_status_lbl.setText(f"失败： 连接失败: {str(e)[:60]}")
                self.clip_status_lbl.setStyleSheet("color: #e74c3c;")
            if sender: sender.setEnabled(True)

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _test_ocr_connection(self):
        """测试远程服务端 OCR 连接（调 /material/status 探测 /material/ocr 可用性）。"""
        sender = self.sender()
        if sender: sender.setEnabled(False)
        self.ocr_status_lbl.setText("正在测试...")
        self.ocr_status_lbl.setStyleSheet("color: #f39c12;")

        api_url = self.ocr_api_url_input.text().strip()
        if not api_url:
            self.ocr_status_lbl.setText("注意： 请填写 OCR 服务地址")
            self.ocr_status_lbl.setStyleSheet("color: #f39c12;")
            if sender: sender.setEnabled(True)
            return

        def _run():
            import requests
            from utils.http_client import http_get
            try:
                base = api_url.rstrip("/")
                # 探测 /material/status（与 check_server_ocr 一致）
                r = http_get(f"{base}/material/status", timeout=5, quiet=True)
                if r.status_code == 200:
                    self.ocr_status_lbl.setText("完成： 连接成功（/material/ocr 可用）")
                    self.ocr_status_lbl.setStyleSheet("color: #2ecc71;")
                else:
                    self.ocr_status_lbl.setText(f"失败： HTTP {r.status_code}")
                    self.ocr_status_lbl.setStyleSheet("color: #e74c3c;")
            except Exception as e:
                self.ocr_status_lbl.setText(f"失败： 连接失败: {str(e)[:60]}")
                self.ocr_status_lbl.setStyleSheet("color: #e74c3c;")
            if sender: sender.setEnabled(True)

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _dreamina_login(self):
        self.dr_status.setText("发起登录…")
        try:
            from utils.dreamina_client import DreaminaClient
            client = DreaminaClient()
            if client.is_installed():
                # Windows: 使用 dreamina CLI 设备码 OAuth
                ok, kv = client.login_headless()
                if not ok:
                    self.dr_status.setText(f"<font color='#dc2626'>失败： {kv}</font>")
                    return
                device_code = kv.get("device_code", "")
                verify_url = kv.get("verification_uri", "")
                self.dr_status.setText(f"<font color='#f59e0b'>请在浏览器打开验证: {verify_url}</font>")
                import webbrowser
                try:
                    if verify_url:
                        webbrowser.open(verify_url)
                except: pass
                # 轮询等待认证
                import threading
                def poll():
                    ok2, msg = client.checklogin(device_code, poll=30)
                    if ok2:
                        self.dr_status.setText("<font color='#16a34a'>完成： 登录成功</font>")
                    else:
                        self.dr_status.setText(f"<font color='#dc2626'>失败： 登录失败: {msg[:100]}</font>")
                threading.Thread(target=poll, daemon=True).start()
            else:
                # Linux: CLI 不可用，打开浏览器
                self.dr_status.setText(
                    "<font color='#f59e0b'>即梦 CLI 未安装（Windows 专属）。建议使用素材浏览器左侧「即梦AI」标签直接访问。</font>")
                import webbrowser
                webbrowser.open("https://jimeng.jianying.com/ai-tool/image/generate")
        except Exception as e:
            self.dr_status.setText(f"<font color='#dc2626'>失败： {e}</font>")

    def _dreamina_check(self):
        self.dr_status.setText("检测中…")
        try:
            from utils.dreamina_client import DreaminaClient
            client = DreaminaClient()
            if not client.is_installed():
                self.dr_status.setText("<font color='#dc2626'>失败： CLI 未安装</font>")
                return
            ok, msg = client.is_logged_in()
            if ok:
                self.dr_status.setText(f"<font color='#16a34a'> 已登录 · 额度: {msg}</font>")
            else:
                self.dr_status.setText("<font color='#f59e0b'> 未登录</font>")
        except Exception as e:
            self.dr_status.setText(f"<font color='#dc2626'>失败： {e}</font>")

    # ── 飞书配置 ──

    def load_feishu_config(self):
        config = cm.load_ini()
        appid = ""; appsecret = ""; apptoken = ""; tableid = ""
        topicfield = "选题"; scriptfield = "脚本"; foldertoken = ""
        try:
            if config.has_section('Feishu'):
                appid = config.get('Feishu', 'AppId', fallback="")
                appsecret = config.get('Feishu', 'AppSecret', fallback="")
                apptoken = config.get('Feishu', 'AppToken', fallback="")
                tableid = config.get('Feishu', 'TableId', fallback="")
                topicfield = config.get('Feishu', 'TopicField', fallback="选题")
                scriptfield = config.get('Feishu', 'ScriptField', fallback="脚本")
                foldertoken = config.get('Feishu', 'FolderToken', fallback="")
        except Exception as e:
            log.error(f"加载飞书配置失败: {e}")
        if hasattr(self, 'edit_feishu_appid'):
            self.edit_feishu_appid.setText(appid)
            self.edit_feishu_appsecret.setText(appsecret)
            self.edit_feishu_apptoken.setText(apptoken)
            self.edit_feishu_tableid.setText(tableid)
            self.edit_feishu_topicfield.setText(topicfield)
            self.edit_feishu_scriptfield.setText(scriptfield)
            self.edit_feishu_foldertoken.setText(foldertoken)

    def save_feishu_config(self):
        config = cm.load_ini()
        try:
            if not config.has_section('Feishu'):
                config.add_section('Feishu')
            config.set('Feishu', 'AppId', self.edit_feishu_appid.text().strip())
            config.set('Feishu', 'AppSecret', self.edit_feishu_appsecret.text().strip())
            config.set('Feishu', 'AppToken', self.edit_feishu_apptoken.text().strip())
            config.set('Feishu', 'TableId', self.edit_feishu_tableid.text().strip())
            config.set('Feishu', 'TopicField', self.edit_feishu_topicfield.text().strip())
            config.set('Feishu', 'ScriptField', self.edit_feishu_scriptfield.text().strip())
            config.set('Feishu', 'FolderToken', self.edit_feishu_foldertoken.text().strip())
            cm.save_ini(config)
            QMessageBox.information(self, "提示", "飞书配置参数保存成功！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存飞书配置失败:\n{e}")
            log.error(f"保存飞书配置失败: {e}")

    def _test_feishu(self):
        self.fs_test_status.setText("测试中…")
        import requests as req
        from utils.http_client import http_post
        app_id = self.edit_feishu_appid.text().strip()
        app_secret = self.edit_feishu_appsecret.text().strip()
        if not app_id or not app_secret:
            self.fs_test_status.setText("<font color='#dc2626'>失败： 请填入 App ID 和 Secret</font>")
            return
        try:
            r = http_post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                          json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
            if r.status_code == 200 and r.json().get("tenant_access_token"):
                self.fs_test_status.setText("<font color='#16a34a'>完成： 连接成功</font>")
            else:
                self.fs_test_status.setText(f"<font color='#dc2626'>失败： HTTP {r.status_code}</font>")
        except Exception as e:
            self.fs_test_status.setText(f"<font color='#dc2626'>失败： {e}</font>")

