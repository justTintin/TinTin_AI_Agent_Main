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
    def load_voxcpm_config(self):
        # 纯远程模式：只从 ai_config 读取远程 TTS 配置回填到输入框
        if hasattr(self, 'ai_config'):
            self.vox_api_url_input.setText(self.ai_config.get("vox_api_url", "http://127.0.0.1:7861/v1/tts"))
            self.vox_timesteps_spin.setValue(self.ai_config.get("vox_timesteps", 20))
            self.vox_cfg_spin.setValue(self.ai_config.get("vox_cfg", 2.0))

    def _save_voxcpm_config_silent(self):
        try:
            if hasattr(self, "ai_config"):
                # 关键：先从所有 UI 收集最新值，避免保存时用过期内存值覆盖其它字段
                # （否则会把它Tab的旧地址写回文件，例如 comfyui_addr 被重置为旧值）
                if hasattr(self, "_collect_all_config_from_ui"):
                    self._collect_all_config_from_ui()
                else:
                    self.ai_config["vox_api_url"] = self.vox_api_url_input.text().strip()
                    self.ai_config["vox_source"] = "remote"  # 纯远程
                    self.ai_config["vox_mode"] = "api"       # 纯 API 调用
                    self.ai_config["vox_timesteps"] = self.vox_timesteps_spin.value()
                    self.ai_config["vox_cfg"] = self.vox_cfg_spin.value()
                try:
                    from utils import config_manager as _cm
                    _cm.save_ai_config(self.ai_config)
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

    def _ollama_refresh_status(self):
        from utils.ollama_manager import OllamaManager
        mgr = OllamaManager.get()

        # 纯远程模式：检测远程连通性，连通则列出远程模型
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
            self.ollama_status_lbl.setText("● 连接失败")
            self._set_ollama_status_state("red")
            self.ollama_models_lbl.setText("请检查远程地址及网络")

    def _set_ollama_status_state(self, state):
        self.ollama_status_lbl.setProperty("state", state)
        self.ollama_status_lbl.style().unpolish(self.ollama_status_lbl)
        self.ollama_status_lbl.style().polish(self.ollama_status_lbl)
