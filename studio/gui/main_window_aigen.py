# -*- coding: utf-8 -*-
"""MainWindow 的 AI 生成/工作流任务 mixin（RunningHub / ComfyUI / 数字人 / 视频工具），从 gui_main 拆出。"""

import subprocess
import time
import json
import sys
import os
from config.paths import (
    PROJECT_ROOT, RUNTIME_DIR, LOG_DIR, TMP_DIR, COOKIES_DIR,
    ACCOUNTS_DIR, PW_BROWSERS_DIR, WORKSPACE_ROOT
)
import threading
import uuid
import configparser
from ui import gui_styles
from gui.transcription_page import TranscriptionToolPage
from gui.env_config_page import EnvRuntimePage, EnvInstallWorker
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
from utils import comfyui_client as comfy
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


class AIGenMixin:
    def start_comfyui_websocket(self):
        # 被动解析后端（不为监听进度而启动本地）；无可用后端则跳过
        addr = comfy.resolve_addr(self.ai_config, auto_start=False)
        if hasattr(self, 'comfy_ws') and self.comfy_ws:
            self.comfy_ws.running = False
            self.comfy_ws.wait()
        if not addr:
            self.comfy_ws = None
            return
        self.comfy_ws = ComfyWSThread(addr)
        self.comfy_ws.progress_received.connect(self.on_ws_progress)
        self.comfy_ws.status_received.connect(self.on_ws_status)
        self.comfy_ws.start()

    def refresh_comfyui_local_status(self):
        """刷新配置卡里的本地 ComfyUI 引擎状态标签。"""
        if not hasattr(self, "comfyui_local_status"):
            return
        local = comfy.ComfyUILocal.get()
        if not local.is_present():
            txt = "本地引擎：⚪ 未安装（apps/comfyui 缺源码）"
        elif local.is_running():
            txt = "本地引擎：✅ 运行中（127.0.0.1:8188）"
        else:
            txt = "本地引擎：🟡 已就位（未运行，提交任务/打开编辑器时自动启动）"
        self.comfyui_local_status.setText(txt)

    def open_comfyui_editor(self):
        """打开 ComfyUI 网页节点编辑器用于调试工作流（客户端走 API，编辑器走网页）。

        优先用已在线的后端（外部优先）；都不在线则后台拉起本地引擎，就绪后自动打开浏览器。
        """
        import webbrowser
        # 1. 已有在线后端 → 直接打开
        addr = comfy.resolve_addr(self.ai_config, auto_start=False)
        if addr and comfy.is_alive(addr):
            webbrowser.open(addr)
            return
        # 2. 无在线后端：本地引擎是否就位？
        if not comfy.ComfyUILocal.get().is_present():
            QMessageBox.warning(
                self, "无法打开",
                "没有可用的外部 ComfyUI，本地引擎也未安装。\n"
                "请在 [AI 设置] 填写外部地址，或获取 ComfyUI 源码到 apps/comfyui。")
            return
        # 3. 后台启动本地，避免阻塞界面；就绪后打开浏览器
        QMessageBox.information(
            self, "正在启动",
            "正在启动本地 ComfyUI 节点编辑器，就绪后会自动打开浏览器，请稍候…")

        def run_task():
            return comfy.resolve_addr(self.ai_config, auto_start=True)

        def on_finished(ready_addr):
            self.refresh_comfyui_local_status()
            if ready_addr:
                webbrowser.open(ready_addr)
            else:
                QMessageBox.critical(
                    self, "启动失败",
                    "本地 ComfyUI 启动超时，请查看日志：\n.runtime/logs/comfyui_local.log")

        self.start_worker(run_task, on_finished)

    def refresh_vt_workflows(self):
        self.vt_workflow_selector.clear()
        workflow_dir = os.path.join(PROJECT_ROOT, "assets", "workflow")
        if os.path.exists(workflow_dir):
            files = [f for f in os.listdir(workflow_dir) if f.endswith(".json")]
            for f in files:
                self.vt_workflow_selector.addItem(f, os.path.join(workflow_dir, f))

    def on_vt_workflow_changed(self, index):
        file_path = self.vt_workflow_selector.currentData()
        if not file_path: return
        
        # Auto load when selected
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.vt_current_workflow_data = json.load(f)
            self.vt_workflow_status.setText(f"✅ 已加载: {os.path.basename(file_path)}")
        except Exception as e:
            self.vt_workflow_status.setText(f"❌ 加载失败: {str(e)}")

    def select_vt_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", "Video Files (*.mp4 *.avi *.mov *.mkv)")
        if path:
            self.vt_video_path_input.setText(path)

    def run_video_tool_task(self):
        if not hasattr(self, 'vt_current_workflow_data') or not self.vt_current_workflow_data:
            QMessageBox.warning(self, "错误", "请先选择并加载工作流。")
            return
            
        video_path = self.vt_video_path_input.text().strip()
        if not video_path:
            QMessageBox.warning(self, "错误", "请先选择视频文件。")
            return

        self.log_area.setText("正在上传视频并提交任务...")
        
        def run_task():
            try:
                # 1. 上传视频（外部不可用时自动拉起本地 ComfyUI）
                log.info(f"Uploading video to ComfyUI: {video_path}")
                upload_name = comfy.upload_file(self.ai_config, video_path, kind="video")
                if not upload_name:
                    return False, "视频上传失败（无可用 ComfyUI 后端或上传出错）"

                # 2. Update workflow JSON with uploaded video name
                # Heuristic: find nodes with 'video' or 'LoadVideo'
                wf_str = json.dumps(self.vt_current_workflow_data)
                modified_wf = json.loads(wf_str)
                found = False
                for node_id, node in modified_wf.items():
                    if node.get("class_type") in ["LoadVideo", "VHS_VideoCombine", "LoadVideoPath"]:
                        if "video" in node.get("inputs", {}):
                            node["inputs"]["video"] = upload_name
                            found = True

                if not found:
                    # Fallback string replace
                    wf_str = wf_str.replace("input_video.mp4", upload_name)
                    modified_wf = json.loads(wf_str)

                # 3. 提交到 ComfyUI（后端已在上一步解析就绪，无需再次启动）
                return comfy.submit_prompt(self.ai_config, modified_wf, auto_start=False)
            except Exception as e:
                return False, str(e)

        def on_finished(result):
            success, info = result
            if success:
                QMessageBox.information(self, "成功", f"任务已提交！ID: {info}")
                self.add_task_to_list(info, status="正在处理")
            else:
                QMessageBox.critical(self, "错误", info)

        self.start_worker(run_task, on_finished)

    def auto_load_default_dh_workflow(self):
        default_wf = os.path.join(PROJECT_ROOT, "assets", "workflow", "数字人-上传图片和声音--20260113-api.json")
        if os.path.exists(default_wf):
            try:
                with open(default_wf, 'r', encoding='utf-8') as f:
                    self.current_workflow_data = json.load(f)
                self.workflow_status.setText(f"✅ 已自动加载: {os.path.basename(default_wf)}")
                if hasattr(self, 'btn_run_local'):
                    self.btn_run_local.setEnabled(True)
            except Exception as e:
                log.error(f"Failed to auto-load DH workflow: {e}")
                self.workflow_status.setText(f"❌ 自动加载失败: {str(e)}")

    def refresh_rh_workflows(self):
        if not self.runninghub:
            self.rh_workflow_info.setText("❌ RunningHub 模块加载失败")
            return
            
        api_key = self.ai_config.get("runninghub_api_key", "").strip()
        if not api_key:
            self.rh_workflow_info.setText("❌ 请先在 [AI 设置] 中配置 API Key")
            return
            
        self.rh_workflow_info.setText("正在获取 AI 应用列表...")
        
        def fetch():
            # First update config in case it changed
            self.runninghub.update_config(
                api_key=self.ai_config.get("runninghub_api_key", ""),
                base_url=self.ai_config.get("runninghub_base_url", "https://www.runninghub.cn")
            )
            return self.runninghub.get_workflow_list()
        
        def on_done(wfs):
            self.rh_workflows = wfs
            self.rh_workflow_selector.clear()
            if not wfs:
                self.rh_workflow_info.setText("❌ 未获取到 AI 应用，请确保已在平台发布应用为 API")
                QMessageBox.warning(self, "获取失败", "未能获取到 AI 应用列表。\n\n可能原因：\n1. API Key 不正确\n2. 您的 AI 应用未发布为 API（请在发布页面确认）\n3. 网络连接问题\n\n详情请查看日志 (.runtime/logs/app.log)")
                return
            
            for wf in wfs:
                # Handle both workflow and app field names
                name = wf.get("workflowName") or wf.get("appName") or wf.get("name") or "未命名"
                wf_id = wf.get("workflowId") or wf.get("appId") or wf.get("id")
                self.rh_workflow_selector.addItem(name, wf_id)
            
            self.rh_workflow_info.setText(f"✅ 已加载 {len(wfs)} 个 AI 应用")
            if self.backend_selector.currentIndex() == 1:
                self.btn_run_workflow.setEnabled(True)
            # Auto-fetch detail for the first one
            if self.rh_workflow_selector.count() > 0:
                self.view_rh_api_detail()

        self.start_worker(fetch, on_done)

    def run_digital_human_task(self):
        if self.backend_selector.currentIndex() == 0:
            self.run_comfyui_task()
        else:
            self.run_runninghub_task()

    def open_rh_web_interface(self):
        url = "https://www.runninghub.cn/ai-detail/2030239520712560642"
        # Try to use current selected app ID if available
        wf_id = self.rh_workflow_selector.currentData()
        if wf_id:
            url = f"https://www.runninghub.cn/ai-detail/{wf_id}"
            
        open_cef_browser(url, "RunningHub AI 应用浏览器")

    def view_rh_api_detail(self):
        if not self.runninghub:
            QMessageBox.warning(self, "未安装依赖", "RunningHub 模块加载失败，请检查日志。")
            return
        wf_id = self.rh_workflow_selector.currentData()
        if not wf_id: 
            self.rh_api_detail_text.setText("请先选择 AI 应用")
            return
        
        self.rh_api_detail_text.setText("正在加载应用接口详情...")
        
        def fetch():
            return self.runninghub.get_workflow_detail(wf_id)
        
        def on_done(detail):
            if not detail:
                self.rh_api_detail_text.setText("❌ 无法获取接口详情")
                QMessageBox.warning(self, "错误", "无法获取 AI 应用接口详情。请检查该应用是否已在平台发布为 API。")
                return
            
            # Format detail for display
            name = detail.get("workflowName") or detail.get("appName") or detail.get("name") or "未命名"
            nodes = detail.get("nodeInfoList") or detail.get("nodes") or []
            
            msg = f"<b>AI 应用:</b> {name}<br>"
            msg += f"<b>ID:</b> {wf_id}<br><br>"
            msg += "<b>API 接口节点:</b><br>"
            
            if not nodes:
                msg += "<i>(未发现可配置的 API 节点，请在 RunningHub 平台设置 API 节点)</i>"
            else:
                for node in nodes:
                    title = node.get("nodeTitle") or node.get("title") or "未知节点"
                    node_id = node.get("nodeId") or node.get("id") or "??"
                    params = node.get("inputParams") or node.get("params") or []
                    param_names = [p.get("paramTitle") or p.get("name") or "??" for p in params]
                    msg += f"• <b>[{node_id}] {title}:</b> {', '.join(param_names)}<br>"
            
            self.rh_api_detail_text.setHtml(msg)
            self.current_rh_workflow_detail = detail

        self.start_worker(fetch, on_done)

    def run_runninghub_task(self):
        if not self.runninghub:
            QMessageBox.warning(self, "未安装依赖", "RunningHub 模块加载失败，请检查日志。")
            return
        wf_id = self.rh_workflow_selector.currentData()
        if not wf_id:
            QMessageBox.warning(self, "错误", "请先选择一个工作流。")
            return
            
        img_file = self.img_path_input.text().strip()
        aud_file = self.aud_path_input.text().strip()
        
        if not img_file or not aud_file:
            QMessageBox.warning(self, "输入限制", "请先选择图片和音频文件。")
            return

        self.log_area.setText(f"正在上传文件并提交 RunningHub 任务...")
        
        def run_task():
            try:
                # 1. Upload files to RunningHub
                log.info(f"Uploading image to RunningHub: {img_file}")
                rh_img_url = self.runninghub.upload_file(img_file)
                if not rh_img_url: return False, "图片上传失败"
                
                log.info(f"Uploading audio to RunningHub: {aud_file}")
                rh_aud_url = self.runninghub.upload_file(aud_file)
                if not rh_aud_url: return False, "音频上传失败"
                
                # 2. Get workflow detail to find input nodes automatically
                detail = self.runninghub.get_workflow_detail(wf_id)
                if not detail: return False, "获取工作流详情失败"
                
                # 3. Build node_info_list
                # We look for nodes that look like LoadImage and LoadAudio
                node_info_list = []
                found_img = False
                found_aud = False
                
                # Check both nodeTitle and inputParams paramTitle
                nodes = detail.get("nodeInfoList") or detail.get("nodes") or []
                for node in nodes:
                    node_id = node.get("nodeId") or node.get("id")
                    title = (node.get("nodeTitle") or node.get("title") or "").lower()
                    params = node.get("inputParams") or node.get("params") or []
                    
                    # Try to find image node
                    if not found_img:
                        is_img_node = "image" in title or "图片" in title or "图生" in title
                        param_to_use = None
                        for p in params:
                            p_title = (p.get("paramTitle") or p.get("name") or "").lower()
                            if "image" in p_title or "图片" in p_title or "url" in p_title:
                                param_to_use = p.get("paramName") or p.get("name")
                                break
                        
                        if is_img_node and param_to_use:
                            node_info_list.append({
                                "nodeId": node_id,
                                "inputParams": [{"paramName": param_to_use, "paramValue": rh_img_url}]
                            })
                            found_img = True
                            continue

                    # Try to find audio node
                    if not found_aud:
                        is_aud_node = "audio" in title or "音频" in title or "voice" in title or "声音" in title
                        param_to_use = None
                        for p in params:
                            p_title = (p.get("paramTitle") or p.get("name") or "").lower()
                            if "audio" in p_title or "音频" in p_title or "url" in p_title or "voice" in p_title:
                                param_to_use = p.get("paramName") or p.get("name")
                                break
                        
                        if is_aud_node and param_to_use:
                            node_info_list.append({
                                "nodeId": node_id,
                                "inputParams": [{"paramName": param_to_use, "paramValue": rh_aud_url}]
                            })
                            found_aud = True
                            continue

                if not found_img or not found_aud:
                    log.warning(f"Heuristic mapping: found_img={found_img}, found_aud={found_aud}")
                    return False, "自动识别 AI 应用的图片或音频输入节点失败。请确保应用中有清晰命名的图片和音频输入节点。"
                
                # 4. Execute
                task_id = self.runninghub.execute_workflow(wf_id, node_info_list)
                if task_id:
                    return True, task_id
                return False, "任务启动失败"
            except Exception as e:
                return False, str(e)

        def on_finished(result):
            success, info = result
            if success:
                QMessageBox.information(self, "成功", f"RunningHub 任务已提交！ID: {info}")
                # Add to local task list if we can track RunningHub tasks too
                self.add_task_to_list(info, status="云端运行中")
            else:
                self.workflow_status.setText("❌ 失败")
                QMessageBox.critical(self, "错误", f"任务启动失败: {info}")

        self.start_worker(run_task, on_finished)

    def upload_to_comfyui(self, server_addr, file_path):
        # 兼容旧签名（server_addr 已忽略）；统一走 comfyui_client，含外部→本地回退
        return comfy.upload_file(self.ai_config, file_path)

    def load_comfyui_workflow(self):
        workflow_path = os.path.join(PROJECT_ROOT, "assets", "workflow", "数字人-上传图片和声音--20260113-api.json")
        if not os.path.exists(workflow_path):
            QMessageBox.warning(self, "未找到文件", f"工作流文件 {workflow_path} 不存在。")
            return
            
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                self.current_workflow_data = json.load(f)
            self.workflow_status.setText("✅ 已加载: 数字人-上传图片和声音")
            self.btn_run_workflow.setEnabled(True)
            log.info(f"Successfully loaded workflow: {workflow_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载工作流失败: {e}")

    def run_comfyui_task(self):
        if not self.current_workflow_data:
            return
            
        img_file = self.img_path_input.text().strip()
        aud_file = self.aud_path_input.text().strip()
        
        if not img_file or not aud_file:
            QMessageBox.warning(self, "输入限制", "请先选择图片和音频文件。")
            return
            
        self.log_area.setText(f"正在上传文件并提交任务...")
        self.workflow_status.setText("⏳ 正在处理...")

        def run_task():
            try:
                # 1. 上传图片（外部不可用时自动拉起本地 ComfyUI）
                log.info(f"Uploading image: {img_file}")
                server_img = comfy.upload_file(self.ai_config, img_file, kind="image")
                if not server_img: return False, "图片上传失败"

                # 2. 上传音频（后端已就绪，无需再次启动）
                log.info(f"Uploading audio: {aud_file}")
                server_aud = comfy.upload_file(self.ai_config, aud_file, kind="audio",
                                               auto_start=False)
                if not server_aud: return False, "音频上传失败"

                # 3. Modify Workflow Nodes
                # Node 284: LoadImage
                if "284" in self.current_workflow_data:
                    self.current_workflow_data["284"]["inputs"]["image"] = server_img
                # Node 311: VHS_LoadAudioUpload
                if "311" in self.current_workflow_data:
                    self.current_workflow_data["311"]["inputs"]["audio"] = server_aud

                # 4. 提交 workflow
                return comfy.submit_prompt(self.ai_config, self.current_workflow_data,
                                           auto_start=False)
            except Exception as e:
                return False, str(e)

        def on_finished(result):
            success, info = result
            if success:
                self.workflow_status.setText("✅ 任务提交成功")
                self.add_task_to_list(info)
                QMessageBox.information(self, "成功", f"任务已提交！ID: {info}")
            else:
                self.workflow_status.setText("❌ 失败")
                QMessageBox.critical(self, "错误", f"任务启动失败: {info}")

        self.worker = Worker(run_task)
        self.worker.finished.connect(on_finished)
        self.worker.start()
