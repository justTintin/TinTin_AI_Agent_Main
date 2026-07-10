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


class AIConfigMixin:
    def save_llm_config(self):
        self.ai_config["llm_provider"] = self.llm_provider_combo.currentData()
        self.ai_config["llm_api_key"] = self.llm_api_key_input.text().strip()
        self.ai_config["llm_api_url"] = self.llm_api_url_input.text().strip()
        self.ai_config["llm_model"] = self.llm_model_input.text().strip()
        vision_url = self.llm_vision_api_url_input.text().strip()
        vision_model = self.llm_vision_model_input.currentText().strip()
        if vision_model and not vision_url:
            vision_url = "http://127.0.0.1:11434"
            self.llm_vision_api_url_input.setText(vision_url)
        self.ai_config["llm_vision_api_url"] = vision_url
        self.ai_config["llm_vision_model"] = vision_model
        try:
            os.makedirs(os.path.dirname(self.ai_config_file), exist_ok=True)
            with open(self.ai_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.ai_config, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "大模型配置已保存。")
            log.info("LLM configuration saved successfully.")
        except Exception as e:
            log.error(f"保存大模型配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

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
        # Update Whisper status labels
        if info.get("whisper_ok", False):
            whisper_status = f"<font color='#16a34a'><b>✅ 已就绪</b></font> ({info.get('whisper_version', '')})"
        else:
            whisper_status = "<font color='#dc2626'><b>❌ 未就绪</b></font> (缺少 whisperx 依赖)"
        self.llm_whisper_status_val.setText(whisper_status)
        
        if info.get("dll_ok", False):
            dll_status = f"<font color='#16a34a'><b>✅ 已就绪</b></font> ({info.get('dll_status', '')})"
        else:
            dll_status = f"<font color='#d97706'><b>⚠️ {info.get('dll_status', '')}</b></font>"
        self.llm_dll_status_val.setText(dll_status)
        
        models_status = f"<font color='#2563eb'><b>{', '.join(info.get('found_models', []))}</b></font> (存放目录: {info.get('models_dir', '')})"
        self.llm_models_status_val.setText(models_status)
        
        # Update VoxCPM status label
        if info.get("voxcpm_ok", False):
            vox_status = f"<font color='#16a34a'><b>✅ {info.get('voxcpm_status', '')}</b></font>"
        elif info.get("voxcpm_installed", False):
            vox_status = f"<font color='#d97706'><b>⚠️ {info.get('voxcpm_status', '')}</b></font>"
        else:
            vox_status = f"<font color='#dc2626'><b>❌ {info.get('voxcpm_status', '')}</b></font>"
        self.llm_vox_status_val.setText(vox_status)

        # Update PaddleOCR status labels
        if info.get("paddleocr_ok", False):
            paddle_status = f"<font color='#16a34a'><b>✅ {info.get('paddleocr_status', '')}</b></font>"
        else:
            paddle_status = f"<font color='#dc2626'><b>❌ {info.get('paddleocr_status', '')}</b></font>"
        self.llm_paddle_status_val.setText(paddle_status)
        
        p_models_status = f"<font color='#2563eb'><b>{', '.join(info.get('paddleocr_models', []))}</b></font> (存放目录: {info.get('paddleocr_models_dir', '')})"
        self.llm_paddle_models_val.setText(p_models_status)

    def load_ai_config(self):
        default_config = {
            "comfyui_addr": "http://192.168.111.36:8188",
            "voice_clone_addr": "http://192.168.111.36:7860",
            "runninghub_api_key": "",
            "runninghub_base_url": "https://www.runninghub.cn",
            "llm_provider": "deepseek",
            "llm_api_key": "",
            "llm_api_url": "https://api.deepseek.com",
            "llm_model": "deepseek-v4-flash",
            "llm_vision_api_url": "http://127.0.0.1:11434",
            "llm_vision_model": "",
            "vox_api_url": "http://127.0.0.1:7861/v1/tts",
            "vox_mode": "api",
            "vox_timesteps": 20,
            "vox_cfg": 2.0
        }
        config_path = self.ai_config_file if os.path.exists(self.ai_config_file) else None
        if not config_path and hasattr(self, "ai_config_legacy_file") and os.path.exists(self.ai_config_legacy_file):
            config_path = self.ai_config_legacy_file

        if config_path:
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.ai_config = json.load(f)
                for k, v in default_config.items():
                    if k not in self.ai_config:
                        self.ai_config[k] = v
                if config_path != self.ai_config_file:
                    try:
                        os.makedirs(os.path.dirname(self.ai_config_file), exist_ok=True)
                        with open(self.ai_config_file, 'w', encoding='utf-8') as wf:
                            json.dump(self.ai_config, wf, indent=4, ensure_ascii=False)
                    except Exception as e:
                        log.error(f"迁移 AI 配置失败: {e}")
                return
            except Exception as e:
                log.error(f"加载 AI 配置失败: {e}")
        self.ai_config = default_config

    def save_ai_config(self):
        self.ai_config["comfyui_addr"] = self.comfyui_input.text().strip()
        self.ai_config["voice_clone_addr"] = self.voice_clone_input.text().strip()
        self.ai_config["runninghub_api_key"] = self.rh_api_key_input.text().strip()
        self.ai_config["runninghub_base_url"] = self.rh_base_url_input.text().strip()
        
        # Update runninghub manager instance
        self.runninghub.update_config(
            self.ai_config["runninghub_api_key"],
            self.ai_config["runninghub_base_url"]
        )
        
        try:
            os.makedirs(os.path.dirname(self.ai_config_file), exist_ok=True)
            with open(self.ai_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.ai_config, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "成功", "AI 配置已保存。")
            log.info("AI configuration saved successfully.")
        except Exception as e:
            log.error(f"保存 AI 配置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def test_ai_connections(self):
        comfyui_addr = self.comfyui_input.text().strip().rstrip("/")
        voice_addr = self.voice_clone_input.text().strip().rstrip("/")
        rh_api_key = self.rh_api_key_input.text().strip()
        rh_base_url = self.rh_base_url_input.text().strip().rstrip("/")
        
        results = []
        try:
            import requests
            from utils import comfyui_client as comfy
            # Test ComfyUI：外部地址 + 本地引擎双后端
            if comfyui_addr and comfy.is_alive(comfyui_addr):
                results.append("ComfyUI(外部): ✅ 在线")
            elif comfyui_addr:
                results.append("ComfyUI(外部): ❌ 无法连接")
            else:
                results.append("ComfyUI(外部): ⚪ 未配置")
            local = comfy.ComfyUILocal.get()
            if not local.is_present():
                results.append("ComfyUI(本地): ⚪ 未安装 (apps/comfyui)")
            elif local.is_running():
                results.append("ComfyUI(本地): ✅ 运行中")
            else:
                results.append("ComfyUI(本地): 🟡 已就位 (未运行，提交任务时自动启动)")

            # Test Voice Clone
            try:
                res = requests.get(voice_addr, timeout=5)
                results.append(f"克隆声音: {'✅ 在线' if res.status_code == 200 else '❌ 异常 ('+str(res.status_code)+')'}")
            except:
                results.append("克隆声音: ❌ 无法连接")
            
            # Test RunningHub
            if rh_api_key:
                try:
                    url = f"{rh_base_url}/openapi/v1/workflow/list"
                    headers = {"Authorization": f"Bearer {rh_api_key}"}
                    res = requests.get(url, headers=headers, params={"page": 1, "size": 1}, timeout=5)
                    if res.status_code == 200 and res.json().get("code") == 0:
                        results.append("RunningHub: ✅ 认证成功")
                    else:
                        msg = res.json().get("msg", "认证失败")
                        results.append(f"RunningHub: ❌ {msg} (HTTP {res.status_code})")
                except Exception as e:
                    results.append(f"RunningHub: ❌ 连接失败 ({str(e)})")
            else:
                results.append("RunningHub: ⚠️ 未配置 API Key")
            
            QMessageBox.information(self, "测试结果", "\n".join(results))
        except Exception as e:
            QMessageBox.critical(self, "测试失败", str(e))

    def _on_llm_provider_changed(self, index):
        provider = self.llm_provider_combo.currentData()
        presets = {
            "deepseek": ("https://api.deepseek.com", "deepseek-v4-flash"),
            "openai": ("https://api.openai.com", "gpt-3.5-turbo"),
            "custom": ("", ""),
        }
        url, model = presets.get(provider, ("", ""))
        if url:
            self.llm_api_url_input.setText(url)
        if model:
            self.llm_model_input.setText(model)
        if provider == "custom":
            self.llm_api_url_input.setPlaceholderText("https://your-api-endpoint.com")
            self.llm_model_input.setPlaceholderText("your-model-name")

    # ──────────────────── Ollama 管理 ────────────────────

    def _test_llm_connection(self):
        sender = self.sender()
        btn = sender if sender else (self.btn_test_llm if hasattr(self, "btn_test_llm") else None)
        if btn:
            btn.setEnabled(False)
        self.llm_status_lbl.setText("正在测试...")
        self.llm_status_lbl.setStyleSheet("color: #f39c12;")
        try:
            import requests
            api_url = self.llm_api_url_input.text().strip()
            api_key = self.llm_api_key_input.text().strip()
            model = self.llm_model_input.text().strip()
            if not api_key or not api_url:
                self.llm_status_lbl.setText("⚠️ 请填写 API Key 和接口地址")
                self.llm_status_lbl.setStyleSheet("color: #f39c12;")
                if btn:
                    btn.setEnabled(True)
                return
            url = f"{api_url.rstrip('/')}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                self.llm_status_lbl.setText(f"✅ 连接成功 ({model})")
                self.llm_status_lbl.setStyleSheet("color: #2ecc71; font-weight: bold;")
            elif res.status_code == 401:
                self.llm_status_lbl.setText(f"❌ API Key 无效，请检查")
                self.llm_status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")
            elif res.status_code == 404:
                self.llm_status_lbl.setText(f"❌ 接口地址或模型名错误 (404)")
                self.llm_status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")
            else:
                msg = res.json().get("error", {}).get("message", res.text[:60])
                self.llm_status_lbl.setText(f"❌ HTTP {res.status_code}: {msg}")
                self.llm_status_lbl.setStyleSheet("color: #e74c3c;")
        except Exception as e:
            err = str(e)[:80]
            self.llm_status_lbl.setText(f"❌ 连接失败: {err}")
            self.llm_status_lbl.setStyleSheet("color: #e74c3c;")
        if btn:
            btn.setEnabled(True)

    def _test_vision_connection(self):
        sender = self.sender()
        if sender:
            sender.setEnabled(False)
        self.vision_status_lbl.setText("正在测试...")
        self.vision_status_lbl.setStyleSheet("color: #f39c12;")
        try:
            import requests
            api_url = self.llm_vision_api_url_input.text().strip()
            api_key = self.llm_api_key_input.text().strip()
            model = self.llm_vision_model_input.currentText().strip()
            if not api_url:
                self.vision_status_lbl.setText("⚠️ 请填写接口地址")
                self.vision_status_lbl.setStyleSheet("color: #f39c12;")
                if sender:
                    sender.setEnabled(True)
                return
            url = f"{api_url.rstrip('/')}/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {"model": model or "qwen2.5vl:7b", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                self.vision_status_lbl.setText(f"✅ 连接成功 ({model})")
                self.vision_status_lbl.setStyleSheet("color: #2ecc71; font-weight: bold;")
            elif res.status_code == 401:
                self.vision_status_lbl.setText(f"❌ 认证失败，请检查 API Key")
                self.vision_status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")
            elif res.status_code == 404:
                self.vision_status_lbl.setText(f"❌ 接口地址或模型名错误 (404)")
                self.vision_status_lbl.setStyleSheet("color: #e74c3c; font-weight: bold;")
            else:
                msg = res.json().get("error", {}).get("message", res.text[:60])
                self.vision_status_lbl.setText(f"❌ HTTP {res.status_code}: {msg}")
                self.vision_status_lbl.setStyleSheet("color: #e74c3c;")
        except Exception as e:
            err = str(e)[:80]
            self.vision_status_lbl.setText(f"❌ 连接失败: {err}")
            self.vision_status_lbl.setStyleSheet("color: #e74c3c;")
        if sender:
            sender.setEnabled(True)

    def on_backend_changed(self, index):
        is_rh = (index == 1)
        # ComfyUI section now includes image/audio inputs
        self.comfy_section.setVisible(not is_rh)
        self.rh_section.setVisible(is_rh)
        
        # Update run button visibility and text
        if not is_rh:
            self.btn_run_local.setEnabled(self.current_workflow_data is not None)

    def load_feishu_config(self):
        config = configparser.ConfigParser()
        appid = ""; appsecret = ""; apptoken = ""; tableid = ""
        topicfield = "选题"; scriptfield = "脚本"; foldertoken = ""
        try:
            if os.path.exists(CONFIG_INI_FILE):
                config.read(CONFIG_INI_FILE, encoding='utf-8')
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
        config = configparser.ConfigParser()
        try:
            if os.path.exists(CONFIG_INI_FILE):
                config.read(CONFIG_INI_FILE, encoding='utf-8')
            if not config.has_section('Feishu'):
                config.add_section('Feishu')
            config.set('Feishu', 'AppId', self.edit_feishu_appid.text().strip())
            config.set('Feishu', 'AppSecret', self.edit_feishu_appsecret.text().strip())
            config.set('Feishu', 'AppToken', self.edit_feishu_apptoken.text().strip())
            config.set('Feishu', 'TableId', self.edit_feishu_tableid.text().strip())
            config.set('Feishu', 'TopicField', self.edit_feishu_topicfield.text().strip())
            config.set('Feishu', 'ScriptField', self.edit_feishu_scriptfield.text().strip())
            config.set('Feishu', 'FolderToken', self.edit_feishu_foldertoken.text().strip())
            with open(CONFIG_INI_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            QMessageBox.information(self, "提示", "飞书配置参数保存成功！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存飞书配置失败:\n{e}")
            log.error(f"保存飞书配置失败: {e}")

    def _test_feishu(self):
        self.fs_test_status.setText("⏳ 测试中…")
        import requests as req
        app_id = self.edit_feishu_appid.text().strip()
        app_secret = self.edit_feishu_appsecret.text().strip()
        if not app_id or not app_secret:
            self.fs_test_status.setText("<font color='#dc2626'>❌ 请填入 App ID 和 Secret</font>")
            return
        try:
            r = req.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
            if r.status_code == 200 and r.json().get("tenant_access_token"):
                self.fs_test_status.setText("<font color='#16a34a'>✅ 连接成功</font>")
            else:
                self.fs_test_status.setText(f"<font color='#dc2626'>❌ HTTP {r.status_code}</font>")
        except Exception as e:
            self.fs_test_status.setText(f"<font color='#dc2626'>❌ {e}</font>")

    def _dreamina_login(self):
        self.dr_status.setText("⏳ 发起登录…")
        try:
            from utils.dreamina_client import DreaminaClient
            client = DreaminaClient()
            if client.is_installed():
                # Windows: 使用 dreamina CLI 设备码 OAuth
                ok, kv = client.login_headless()
                if not ok:
                    self.dr_status.setText(f"<font color='#dc2626'>❌ {kv}</font>")
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
                        self.dr_status.setText("<font color='#16a34a'>✅ 登录成功</font>")
                    else:
                        self.dr_status.setText(f"<font color='#dc2626'>❌ 登录失败: {msg[:100]}</font>")
                threading.Thread(target=poll, daemon=True).start()
            else:
                # Linux: CLI 不可用，打开浏览器
                self.dr_status.setText(
                    "<font color='#f59e0b'>⏳ 即梦 CLI 未安装（Windows 专属）。建议使用素材浏览器左侧「即梦AI」标签直接访问。</font>")
                import webbrowser
                webbrowser.open("https://jimeng.jianying.com/ai-tool/image/generate")
        except Exception as e:
            self.dr_status.setText(f"<font color='#dc2626'>❌ {e}</font>")

    def _dreamina_check(self):
        self.dr_status.setText("⏳ 检测中…")
        try:
            from utils.dreamina_client import DreaminaClient
            client = DreaminaClient()
            if not client.is_installed():
                self.dr_status.setText("<font color='#dc2626'>❌ CLI 未安装</font>")
                return
            ok, msg = client.is_logged_in()
            if ok:
                self.dr_status.setText(f"<font color='#16a34a'>✅ 已登录 · 额度: {msg}</font>")
            else:
                self.dr_status.setText("<font color='#f59e0b'>⚠ 未登录</font>")
        except Exception as e:
            self.dr_status.setText(f"<font color='#dc2626'>❌ {e}</font>")

    # ── 旺店通 ERP 配置 ──

    def _save_erp_platform_cfg(self):
        from config.paths import CONFIG_DIR
        cfg_path = os.path.join(CONFIG_DIR, "erp_config.json")
        try:
            cfg = {
                "base_url": self.erp_url_input.text().strip(),
                "appkey": self.erp_appkey_input.text().strip(),
                "appsecret": self.erp_appsecret_input.text().strip(),
                "sid": self.erp_sid_input.text().strip(),
            }
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_erp_status.setText("✅ 配置已保存")
            self.lbl_erp_status.setStyleSheet("color: #4ade80;")
        except Exception as e:
            self.lbl_erp_status.setText(f"❌ 保存失败: {e}")
            self.lbl_erp_status.setStyleSheet("color: #f87171;")

    def load_erp_platform_cfg(self):
        from config.paths import CONFIG_DIR
        cfg_path = os.path.join(CONFIG_DIR, "erp_config.json")
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                self.erp_url_input.setText(cfg.get("base_url", ""))
                self.erp_appkey_input.setText(cfg.get("appkey", ""))
                self.erp_appsecret_input.setText(cfg.get("appsecret", ""))
                self.erp_sid_input.setText(cfg.get("sid", ""))
        except Exception as e:
            print(f"加载 ERP 配置失败: {e}")

    # ── 数据库配置 ──

    def _save_matdb_platform_cfg(self):
        from config.paths import CONFIG_DIR
        cfg_path = os.path.join(CONFIG_DIR, "material_index_config.json")
        try:
            import json as _json
            cfg = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = _json.load(f)
            cfg["db_host"] = self.matdb_host_input.text().strip()
            cfg["db_port"] = int(self.matdb_port_input.text().strip() or 0)
            cfg["db_name"] = self.matdb_name_input.text().strip()
            cfg["db_user"] = self.matdb_user_input.text().strip()
            cfg["db_password"] = self.matdb_pass_input.text().strip()
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_db_status.setText("✅ 配置已保存")
            self.lbl_db_status.setStyleSheet("color: #4ade80;")
        except Exception as e:
            self.lbl_db_status.setText(f"❌ 保存失败: {e}")
            self.lbl_db_status.setStyleSheet("color: #f87171;")

    def load_matdb_platform_cfg(self):
        from config.paths import CONFIG_DIR
        cfg_path = os.path.join(CONFIG_DIR, "material_index_config.json")
        try:
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                self.matdb_host_input.setText(cfg.get("db_host", "192.168.111.17"))
                self.matdb_port_input.setText(str(cfg.get("db_port", 15432)))
                self.matdb_name_input.setText(cfg.get("db_name", "material_index"))
                self.matdb_user_input.setText(cfg.get("db_user", "postgres"))
                self.matdb_pass_input.setText(cfg.get("db_password", ""))
        except Exception as e:
            print(f"加载数据库配置失败: {e}")

    def _test_matdb_platform(self):
        import psycopg2
        try:
            self.lbl_db_status.setText("⏳ 测试中...")
            self.lbl_db_status.setStyleSheet("color: #facc15;")
            host = self.matdb_host_input.text().strip()
            port = int(self.matdb_port_input.text().strip() or 15432)
            dbname = self.matdb_name_input.text().strip()
            user = self.matdb_user_input.text().strip()
            password = self.matdb_pass_input.text().strip()
            conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password, connect_timeout=5)
            conn.close()
            self.lbl_db_status.setText("✅ 连接成功")
            self.lbl_db_status.setStyleSheet("color: #4ade80;")
        except Exception as e:
            self.lbl_db_status.setText(f"❌ 连接失败: {e}")
            self.lbl_db_status.setStyleSheet("color: #f87171;")
