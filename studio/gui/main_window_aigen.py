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
from utils import comfyui_client as comfy
from gui.dialogs import LoginDialog, StartupSplash, CloseSplash, open_cef_browser, EditAccountDialog
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QLabel, QStackedWidget, 
                                 QFrame, QSizePolicy, QLineEdit, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QMessageBox, QCheckBox,
                                 QScrollArea, QTextEdit, QTextBrowser, QDialog, QListWidget,
                                 QListWidgetItem, QGridLayout, QFileDialog,
                                 QProgressBar, QComboBox, QInputDialog, QSplitter,
                                 QAbstractItemView, QButtonGroup, QGroupBox, QListView,
                                 QSpinBox, QFormLayout, QDialogButtonBox)
from PySide6.QtGui import QIcon, QFont, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QFont


from utils.file_dialog_utils import pick_file
WORKFLOW_TYPES = ("文生图", "图生图", "图生视频", "数字人", "其他")

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
        path, _ = pick_file(self, "选择视频", "", "Video Files (*.mp4 *.avi *.mov *.mkv)")
        if path:
            self.vt_video_path_input.setText(path)

    def run_video_tool_task(self):
        if not hasattr(self, 'vt_current_workflow_data') or not self.vt_current_workflow_data:
            QMessageBox.warning(self.parent_widget, "错误", "请先选择并加载工作流。")
            return

        video_path = self.vt_video_path_input.text().strip()
        if not video_path:
            QMessageBox.warning(self.parent_widget, "错误", "请先选择视频文件。")
            return

        self.workflow_status.setText("⏳ 正在上传视频并提交任务...")

        def run_task():
            try:
                client = comfy.get_client(self.ai_config)

                # 1. 上传视频
                log.info(f"Uploading video to ComfyUI: {video_path}")
                upload_name = client.upload_file(video_path, accept="video")
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

                # 3. 提交（视频工具无对应 /apps 应用，走原始 workflow 提交）
                prompt_id = client.submit_raw_prompt(modified_wf)
                return True, prompt_id
            except Exception as e:
                return False, str(e)

        def on_finished(result):
            success, info = result
            if success:
                QMessageBox.information(self.parent_widget, "成功", f"任务已提交！ID: {info}")
                self.add_task_to_list(info, status="正在处理")
            else:
                QMessageBox.critical(self.parent_widget, "错误", info)

        self.start_worker(run_task, on_finished)

    def auto_load_default_dh_workflow(self):
        default_wf = os.path.join(PROJECT_ROOT, "assets", "workflow", "数字人-上传图片和声音--20260113-api.json")
        if os.path.exists(default_wf):
            try:
                with open(default_wf, 'r', encoding='utf-8') as f:
                    self.current_workflow_data = json.load(f)
                self.workflow_status.setText(f"✅ 已自动加载: {os.path.basename(default_wf)}")
                if hasattr(self, 'btn_run_workflow'):
                    self.btn_run_workflow.setEnabled(True)
            except Exception as e:
                log.error(f"Failed to auto-load DH workflow: {e}")
                self.workflow_status.setText(f"❌ 自动加载失败: {str(e)}")



    def run_digital_human_task(self):
        if self.backend_selector.currentIndex() == 0:
            self.run_comfyui_dh_task()
        else:
            self.run_runninghub_task()

    def open_rh_web_interface(self):
        wf_id = self.rh_workflow_id_input.text().strip()
        url = f"https://www.runninghub.cn/call-api/api-detail/{wf_id}?apiType=5" if wf_id else "https://www.runninghub.cn"
        open_cef_browser(url, "RunningHub 工作流 API")

    def view_rh_api_detail(self):
        """获取 RunningHub 工作流 JSON，在节点列表中展示所有图片/音频输入节点。"""
        if not self.runninghub:
            self.rh_workflow_info.setText("RunningHub 模块未初始化，无法获取节点")
            return
        wf_id = self.rh_workflow_id_input.text().strip()
        if not wf_id:
            self.rh_workflow_info.setText("❌ 请先填写 RunningHub 工作流 ID")
            self._reset_rh_node_list()
            return

        self.rh_workflow_info.setText("⏳ 正在获取工作流节点...")
        self._reset_rh_node_list()

        def fetch():
            # 优先走服务端工作流 JSON 接口，失败回退直连 RunningHub
            from utils import digital_human_client as dhc
            wf = dhc.get_workflow_json(wf_id)
            if wf is not None:
                return wf
            return self.runninghub.get_workflow_json(wf_id)

        def on_done(wf):
            if not wf or not isinstance(wf, dict):
                err = "❌ 无法获取工作流 JSON。可能原因：1) 工作流 ID 不正确；2) 未发布为 API；3) API Key 无权限；4) 网络连接问题。"
                self.rh_workflow_info.setText(err)
                return

            self.current_rh_workflow_json = wf
            self.rh_image_nodes = []
            self.rh_audio_nodes = []
            for node_id, node in wf.items():
                if not isinstance(node, dict):
                    continue
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                for field_name, val in inputs.items():
                    # 只把真实文件输入节点（非连线）当作可映射输入，
                    # 连线节点的 image/audio 是列表引用，不能直接填文件 URL
                    if field_name in ("image", "audio") and not isinstance(val, list):
                        if field_name == "image":
                            self.rh_image_nodes.append((node_id, class_type, field_name))
                        else:
                            self.rh_audio_nodes.append((node_id, class_type, field_name))

            # 填充节点列表，默认全部勾选
            self.rh_node_list.clear()
            for node_id, class_type, field_name in self.rh_image_nodes + self.rh_audio_nodes:
                display = f"[{node_id}] {class_type} ({field_name})"
                item = QListWidgetItem(display)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, {"node_id": node_id, "class_type": class_type, "field_name": field_name})
                self.rh_node_list.addItem(item)

            self._refresh_rh_input_panel()
            summary = f"图片节点 {len(self.rh_image_nodes)} 个，音频节点 {len(self.rh_audio_nodes)} 个；默认全部勾选。"
            self.rh_workflow_info.setText(f"✅ 已获取 {len(self.rh_image_nodes) + len(self.rh_audio_nodes)} 个输入节点，{summary}")
            if self.backend_selector.currentIndex() == 1:
                self.btn_run_workflow.setEnabled(self.rh_audio_list.rowCount() > 0)

        self.start_worker(fetch, on_done)

    def _reset_rh_node_list(self):
        """清空节点列表并重置输入面板。"""
        self.rh_image_nodes = []
        self.rh_audio_nodes = []
        if hasattr(self, "rh_node_list"):
            self.rh_node_list.clear()
        self._refresh_rh_input_panel()

    def _on_rh_node_checked(self, item):
        """节点复选框变化时刷新输入面板。"""
        self._refresh_rh_input_panel()

    def _refresh_rh_input_panel(self):
        """根据勾选的节点类型显示/隐藏对应的输入组件。"""
        has_img = False
        has_aud = False
        for i in range(self.rh_node_list.count()):
            item = self.rh_node_list.item(i)
            if item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole) or {}
                if data.get("field_name") == "image":
                    has_img = True
                elif data.get("field_name") == "audio":
                    has_aud = True
        if hasattr(self, "rh_img_input_group"):
            self.rh_img_input_group.setVisible(has_img)
        if hasattr(self, "rh_audio_input_group"):
            self.rh_audio_input_group.setVisible(has_aud)

    def run_runninghub_task(self):
        """RunningHub 数字人：按队列提交批量任务（1 张图片 + N 个音频）。"""
        if not self.runninghub:
            self.rh_workflow_info.setText("RunningHub 模块未初始化，无法提交任务")
            return
        wf_id = self.rh_workflow_id_input.text().strip()
        if not wf_id:
            self.rh_workflow_info.setText("请先选择 RunningHub 数字人工作流")
            return

        checked_image_nodes, checked_audio_nodes = self._get_checked_rh_nodes()
        if not checked_image_nodes or not checked_audio_nodes:
            self.rh_workflow_info.setText("请先在节点列表中勾选至少 1 个图片节点和 1 个音频节点")
            return

        img_file = self.rh_img_path_input.text().strip()
        if not img_file:
            self.rh_workflow_info.setText("请选择人物图片")
            return

        audio_files = []
        for _row in range(self.rh_audio_list.rowCount()):
            _item = self.rh_audio_list.item(_row, 0)
            if _item and _item.data(Qt.UserRole):
                audio_files.append(_item.data(Qt.UserRole))
        if not audio_files:
            self.rh_workflow_info.setText("请至少添加一个驱动音频")
            return

        # 只提交新添加的音频：已成功处理过的文件不重复提交
        processed = getattr(self, "_rh_processed_audios", None) or set()
        new_files = [f for f in audio_files if f not in processed]
        if not new_files:
            self.rh_workflow_info.setText("当前音频都已处理过，请先添加新的驱动音频")
            return
        audio_files = new_files

        # 构建待处理队列
        self.rh_queue_paused = False
        wf_cfg = self._rh_find_workflow_config(wf_id) or {}
        self.rh_pending_tasks = []
        for idx, aud_file in enumerate(audio_files):
            self.rh_pending_tasks.append({
                "idx": idx,
                "wf_id": wf_id,
                "img_file": img_file,
                "aud_file": aud_file,
                "image_nodes": checked_image_nodes,
                "audio_nodes": checked_audio_nodes,
                "instance_type": wf_cfg.get("instanceType") or "default",
                "state": "pending",  # pending | paused | submitted | done | failed
                "task_id": None,
                "error": None,
                "retry_count": 0,
                "next_attempt_at": 0,
                "submit_count": 0,
                "downloaded": False,
            })

        self.rh_submitted_tasks = {}
        self.log_area.setText(f"已加入 {len(audio_files)} 个音频到 RunningHub 任务队列，开始执行...")
        self.btn_run_workflow.setEnabled(False)
        self._start_rh_poll_timer()
        self._update_rh_queue_stats()
        self._process_rh_queue()

    def add_single_rh_task(self, img_file, aud_file):
        """表单方式添加单个 RunningHub 数字人任务并开始执行。"""
        if not self.runninghub:
            QMessageBox.warning(self, "未初始化", "RunningHub 模块未初始化")
            return
        wf_id = self.rh_workflow_id_input.text().strip()
        if not wf_id:
            QMessageBox.warning(self, "未配置工作流", "请先在平台接入中配置数字人工作流")
            return
        if not os.path.isfile(img_file) or not os.path.isfile(aud_file):
            QMessageBox.warning(self, "文件不存在", "请选择存在的图片和音频文件")
            return
        processed = getattr(self, "_rh_processed_audios", None) or set()
        if aud_file in processed:
            QMessageBox.warning(self, "已处理", "该音频已处理过，请勿重复提交")
            return
        image_nodes, audio_nodes = self._get_checked_rh_nodes()
        if not image_nodes or not audio_nodes:
            image_nodes = [("180", "LoadImage", "image")]
            audio_nodes = [("6", "LoadAudio", "audio")]
        wf_cfg = self._rh_find_workflow_config(wf_id) or {}
        self.rh_queue_paused = False
        self.rh_pending_tasks = [{
            "idx": 0,
            "wf_id": wf_id,
            "img_file": img_file,
            "aud_file": aud_file,
            "image_nodes": image_nodes,
            "audio_nodes": audio_nodes,
            "instance_type": wf_cfg.get("instanceType") or "default",
            "state": "pending",
            "task_id": None,
            "error": None,
            "retry_count": 0,
            "next_attempt_at": 0,
            "submit_count": 0,
            "downloaded": False,
        }]
        self.rh_submitted_tasks = {}
        self.log_area.setText("已添加 1 个任务到 RunningHub 队列，开始执行...")
        self.btn_run_workflow.setEnabled(False)
        self._start_rh_poll_timer()
        self._update_rh_queue_stats()
        self._process_rh_queue()

    def _get_checked_rh_nodes(self):
        """从节点列表中返回当前勾选的 (image_nodes, audio_nodes)。"""
        image_nodes = []
        audio_nodes = []
        for i in range(self.rh_node_list.count()):
            item = self.rh_node_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            data = item.data(Qt.UserRole) or {}
            node_id = data.get("node_id")
            field_name = data.get("field_name")
            class_type = data.get("class_type")
            if not node_id or not field_name:
                continue
            if field_name == "image":
                image_nodes.append((node_id, class_type, field_name))
            elif field_name == "audio":
                audio_nodes.append((node_id, class_type, field_name))
        return image_nodes, audio_nodes

    def upload_to_comfyui(self, server_addr, file_path):
        # 兼容旧签名（server_addr 已忽略）；统一走 ComfyUIClient
        client = comfy.get_client(self.ai_config)
        return client.upload_file(file_path)

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
        """执行当前选中的 AI 应用：收集动态表单参数 → 上传文件类输入 → run_app。"""
        app_detail = getattr(self, '_ai_current_app', None)
        if not app_detail or not app_detail.get('id'):
            QMessageBox.warning(self.parent_widget, "未选择应用", "请先在左侧列表选择一个 AI 应用。")
            return

        app_id = app_detail['id']
        app_name = app_detail.get('name', app_id)

        # 校验必填项
        params, file_inputs = self._collect_ai_app_params()
        for inp in app_detail.get('inputs', []):
            if inp.get('required'):
                val = params.get(inp.get('key'))
                if val in (None, "", []):
                    QMessageBox.warning(self.parent_widget, "参数缺失", f"请填写必填项：{inp.get('label', inp.get('key'))}")
                    return

        self.workflow_status.setText(f"⏳ 正在执行「{app_name}」...")
        self.btn_run_workflow.setEnabled(False)

        def run_task():
            try:
                client = comfy.get_client(self.ai_config)

                # 1. 上传文件类输入，把本地路径替换为服务端文件名
                for key, path, accept in file_inputs:
                    if not path:
                        continue
                    log.info(f"[AI应用] 上传 {key}: {path}")
                    server_name = client.upload_file(path, accept=accept or 'image')
                    params[key] = server_name

                # 2. 执行应用
                prompt_id = client.run_app(app_id, params)
                return True, prompt_id
            except Exception as e:
                return False, str(e)

        def on_finished(result):
            self.btn_run_workflow.setEnabled(True)
            success, info = result
            if success:
                self.workflow_status.setText(f"✅ 「{app_name}」任务已提交")
                self.add_task_to_list(info)
                QMessageBox.information(self.parent_widget, "成功", f"任务已提交！\n应用：{app_name}\nID: {info}")
            else:
                self.workflow_status.setText("❌ 失败")
                QMessageBox.critical(self.parent_widget, "错误", f"任务启动失败: {info}")

        self.worker = Worker(run_task)
        self.worker.finished.connect(on_finished)
        self.worker.start()

    def _on_dh_backend_changed(self, index):
        """数字人 Tab：切换后端时显示/隐藏对应区域并启用/禁用提交按钮。"""
        if index == 0:  # ComfyUI
            self.comfy_section.show()
            self.rh_section.hide()
            self.btn_run_workflow.setText("提交生成任务")
            self.btn_run_workflow.setEnabled(bool(self.current_workflow_data))
        else:  # RunningHub
            self.comfy_section.hide()
            self.rh_section.show()
            self.btn_run_workflow.setText("开始批量任务")
            self._refresh_rh_input_panel()
            self._rh_refresh_dh_workflow_selector()
            wf_id = self.rh_workflow_id_input.text().strip()
            if wf_id and hasattr(self, "rh_node_list") and self.rh_node_list.count() == 0:
                QTimer.singleShot(300, self.view_rh_api_detail)
            self.btn_run_workflow.setEnabled(bool(wf_id) and self._rh_has_new_audios())

    def _rh_has_new_audios(self):
        """列表中是否存在未处理过的驱动音频（只认新增的，已处理过的不重复提交）。"""
        processed = getattr(self, "_rh_processed_audios", None) or set()
        for row in range(self.rh_audio_list.rowCount()):
            item = self.rh_audio_list.item(row, 0)
            if item and item.data(Qt.UserRole) and item.data(Qt.UserRole) not in processed:
                return True
        return False

    def _test_runninghub_config(self):
        """在 AI 设置页测试 RunningHub API Key 是否可用。"""
        if not self.runninghub:
            self.rh_config_status.setText("❌ RunningHub 模块未初始化")
            return
        api_key = self.runninghub_api_key_input.text().strip()
        base_url = self.runninghub_base_url_input.text().strip().rstrip("/") or "https://www.runninghub.cn"
        if not api_key:
            self.rh_config_status.setText("❌ 请先填写 API Key")
            return
        self.rh_config_status.setText("⏳ 正在测试...")
        def run():
            self.runninghub.update_config(api_key=api_key, base_url=base_url)
            return self.runninghub.test_connection()
        def on_done(info):
            if info:
                self.rh_config_status.setText(f"✅ 连接成功 (类型: {info.get('apiType', '-')}, 余额: {info.get('remainCoins', '-')})")
            else:
                self.rh_config_status.setText("❌ 连接失败，请检查 API Key 和基础地址")
        self.start_worker(run, on_done)

    def _test_runninghub_comfy_protocol(self):
        """测试 RunningHub 在线工作流的 ComfyUI 协议接口可用性。"""
        from utils.runninghub_comfy_client import RunningHubComfyClient
        base_url = self.runninghub_base_url_input.text().strip().rstrip("/") or "https://www.runninghub.cn"
        comfy_auth = self.runninghub_comfy_auth_input.text().strip()
        identify = self.runninghub_comfy_identify_input.text().strip()
        access_token = self.runninghub_access_token_input.text().strip()
        if not comfy_auth or not identify:
            self.rh_comfy_status.setText("❌ 请先填写 Rh-Comfy-Auth 和 Rh-Identify（登录 RunningHub 后在浏览器 localStorage 中查看）")
            return
        client = RunningHubComfyClient(base_url=base_url, comfy_auth=comfy_auth, identify=identify, access_token=access_token)
        self.rh_comfy_status.setText("⏳ 正在检测 RunningHub ComfyUI 协议接口...")

        def run():
            ok = client.is_alive()
            info = client.get_object_info() if ok else None
            required = ["LoadImage", "LoadAudio", "WanVideoModelLoader", "MultiTalkModelLoader"]
            missing = [k for k in required if not (info or {}).get(k)] if isinstance(info, dict) else []
            return ok, bool(info), missing

        def on_done(result):
            ok, has_info, missing = result
            if ok and has_info:
                if missing:
                    self.rh_comfy_status.setText(f"✅ 协议可用，但缺少节点: {', '.join(missing)}")
                else:
                    self.rh_comfy_status.setText("✅ ComfyUI 协议可用，所需节点齐全")
            elif ok:
                self.rh_comfy_status.setText("✅ /system_stats 可用，但 /object_info 未返回节点")
            else:
                self.rh_comfy_status.setText("❌ ComfyUI 协议不可用，请检查会话凭证")

        self.start_worker(run, on_done)

    def run_comfyui_dh_task(self):
        """数字人 ComfyUI 本地/外部后端：上传图片+音频，patch 工作流并提交。"""
        if not self.current_workflow_data:
            QMessageBox.warning(self, "未加载工作流", "请先加载数字人工作流。")
            return
        img_file = self.img_path_input.text().strip()
        aud_file = self.aud_path_input.text().strip()
        if not img_file or not aud_file:
            QMessageBox.warning(self, "输入缺失", "请选择人物图片和驱动语音。")
            return

        self.workflow_status.setText("⏳ 正在上传文件并提交 ComfyUI 任务...")
        self.btn_run_workflow.setEnabled(False)

        def run_task():
            try:
                client = comfy.get_client(self.ai_config)
                img_name = client.upload_file(img_file, accept="image")
                aud_name = client.upload_file(aud_file, accept="audio")
                wf = json.loads(json.dumps(self.current_workflow_data))
                for node_id, node in wf.items():
                    if not isinstance(node, dict):
                        continue
                    class_type = node.get("class_type", "")
                    inputs = node.get("inputs", {})
                    if class_type == "LoadImage" and "image" in inputs:
                        inputs["image"] = img_name
                    elif class_type == "VHS_LoadAudioUpload" and "audio" in inputs:
                        inputs["audio"] = aud_name
                prompt_id = client.submit_raw_prompt(wf)
                return True, prompt_id
            except Exception as e:
                log.exception("ComfyUI digital human task failed")
                return False, str(e)

        def on_finished(result):
            self.btn_run_workflow.setEnabled(True)
            success, info = result
            if success:
                self.workflow_status.setText(f"✅ 任务已提交: {info}")
                self.add_task_to_list(info, status="正在运行")
                QMessageBox.information(self, "成功", f"ComfyUI 任务已提交！ID: {info}")
            else:
                self.workflow_status.setText("❌ 失败")
                QMessageBox.critical(self, "错误", f"任务启动失败: {info}")

        self.start_worker(run_task, on_finished)


    # ------------------------------------------------------------------
    # RunningHub 批量队列 / 轮询 / 导出
    # ------------------------------------------------------------------
    def _start_rh_poll_timer(self):
        """启动 RunningHub 任务状态轮询。"""
        if not hasattr(self, "rh_poll_timer") or self.rh_poll_timer is None:
            self.rh_poll_timer = QTimer(self)
            self.rh_poll_timer.timeout.connect(self._poll_rh_tasks)
        if not self.rh_poll_timer.isActive():
            self.rh_poll_timer.start(3000)

    def _rh_queue_stats(self):
        """计算 RunningHub 任务队列的总数、已提交、成功下载等统计。"""
        tasks = getattr(self, "rh_pending_tasks", None) or []
        total = len(tasks)
        submitted = sum(1 for t in tasks if t.get("submit_count", 0) > 0 or t.get("state") != "pending")
        downloaded = sum(1 for t in tasks if t.get("downloaded"))
        done = sum(1 for t in tasks if t.get("state") == "done")
        failed = sum(1 for t in tasks if t.get("state") == "failed")
        running = sum(1 for t in tasks if t.get("state") == "submitted")
        pending = sum(1 for t in tasks if t.get("state") == "pending")
        pct = int((downloaded + failed) / total * 100) if total else 0
        return {
            "total": total,
            "submitted": submitted,
            "downloaded": downloaded,
            "done": done,
            "failed": failed,
            "running": running,
            "pending": pending,
            "pct": pct,
        }

    def _update_rh_queue_stats(self):
        """刷新数字人页面的任务队列统计。"""
        if not hasattr(self, "rh_queue_stats_label"):
            return
        s = self._rh_queue_stats()
        self.rh_queue_stats_label.setText(
            f"任务队列: 共 {s['total']} | 已提交 {s['submitted']}/{s['total']} | "
            f"成功下载 {s['downloaded']} | 失败 {s['failed']} | "
            f"运行中 {s['running']} | 待处理 {s['pending']} | 进度 {s['pct']}%"
        )

    def _process_rh_queue(self):
        """顺序处理待提交的 RunningHub 任务。"""
        if self.rh_queue_paused:
            self.log_area.append("任务队列已暂停。")
            return

        # RunningHub 同时只能跑一个任务，已有在跑任务时等待
        if self.rh_submitted_tasks:
            return

        # 找到下一个未提交的 pending 任务
        task = None
        for t in self.rh_pending_tasks:
            if t["state"] == "pending":
                task = t
                break
        if task is None:
            # 没有 pending 任务，检查是否全部结束
            all_done = all(t["state"] in ("done", "failed") for t in self.rh_pending_tasks)
            if all_done and not self.rh_submitted_tasks:
                self.log_area.append("所有任务已完成。")
                self.btn_run_workflow.setEnabled(
                    bool(self.rh_workflow_id_input.text().strip()) and self._rh_has_new_audios())
            return

        now = time.time()
        wait_until = task.get("next_attempt_at") or 0
        if wait_until > now:
            wait_sec = int(wait_until - now) + 1
            self.log_area.append(f"[{task['idx']+1}] RunningHub 资源不足，{wait_sec} 秒后自动重试")
            if not self.rh_queue_paused:
                QTimer.singleShot(wait_sec * 1000, self._process_rh_queue)
            return

        task["state"] = "submitted"
        wf_id = task["wf_id"]
        img_file = task["img_file"]
        aud_file = task["aud_file"]
        idx = task["idx"]

        self._set_rh_audio_row_state(aud_file, "running")
        self.log_area.append(f"[{idx+1}/{len(self.rh_pending_tasks)}] 正在上传并提交: {os.path.basename(aud_file)}")

        def run_task():
            try:
                use_protocol = False
                if (self.ai_config or {}).get("runninghub_comfy_auth") and getattr(self, "current_rh_workflow_json", None):
                    use_protocol = True
                if use_protocol:
                    from utils.runninghub_comfy_client import get_runninghub_comfy_client
                    client = get_runninghub_comfy_client(self.ai_config)
                    img_name = client.upload_file(img_file)
                    aud_name = client.upload_file(aud_file)
                    wf = json.loads(json.dumps(self.current_rh_workflow_json))
                    for node_id, node in wf.items():
                        if not isinstance(node, dict):
                            continue
                        class_type = node.get("class_type", "")
                        inputs = node.get("inputs", {})
                        if class_type == "LoadImage" and "image" in inputs:
                            inputs["image"] = img_name
                        elif class_type == "LoadAudio" and "audio" in inputs:
                            inputs["audio"] = aud_name
                    prompt_id = client.submit_prompt(wf)
                    meta = {"img_url": img_name, "aud_url": aud_name, "aud_file": aud_file, "img_file": img_file, "protocol": True}
                    return True, prompt_id, meta

                # 优先走服务端统一接口（服务端已配置 RunningHub，客户端免 API Key）；
                # 服务端地址未配置或提交失败时静默回退直连 RunningHub
                from utils import digital_human_client as dhc
                task_id, dh_err = dhc.submit_digital_human(
                    img_file, aud_file, wf_id,
                    instance_type=task.get("instance_type") or "default")
                if task_id:
                    meta = {"aud_file": aud_file, "img_file": img_file, "server": True}
                    return True, task_id, meta
                if dh_err:
                    log.warning("数字人服务端提交失败，回退直连 RunningHub: %s", dh_err)

                img_url = self.runninghub.upload_file(img_file)
                if not img_url:
                    return False, "图片上传失败", None
                aud_url = self.runninghub.upload_file(aud_file)
                if not aud_url:
                    return False, "音频上传失败", None

                node_info_list = []
                for node_id, _class_type, field_name in task.get("image_nodes", []):
                    node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": img_url})
                for node_id, _class_type, field_name in task.get("audio_nodes", []):
                    node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": aud_url})

                meta = {"img_url": img_url, "aud_url": aud_url, "aud_file": aud_file, "img_file": img_file}
                instance_type = task.get("instance_type") or "default"
                use_personal_queue = bool((self.ai_config or {}).get("runninghub_use_personal_queue", True))
                result = self.runninghub.run_workflow(
                    wf_id, node_info_list,
                    instance_type=instance_type,
                    use_personal_queue=use_personal_queue,
                )
                if result.get("success"):
                    return True, result.get("task_id"), meta

                # 错误码 435 = 未找到独占实例，官方建议 48G 显存工作流传 instanceType=plus
                if result.get("error_code") == "435" and instance_type != "plus":
                    log.warning("RunningHub 435, retry with plus instance for %s", wf_id)
                    retry = self.runninghub.run_workflow(
                        wf_id, node_info_list,
                        instance_type="plus",
                        use_personal_queue=use_personal_queue,
                    )
                    if retry.get("success"):
                        task["instance_type"] = "plus"
                        meta["retried_plus"] = True
                        return True, retry.get("task_id"), meta
                    result = retry

                err_code = str(result.get("error_code") or "")
                err_msg = str(result.get("error_message") or "")
                if err_code and err_msg:
                    err = f"[{err_code}] {err_msg}"
                else:
                    err = (err_code + " " + err_msg).strip() or "任务启动失败"
                return False, err, None
            except Exception as e:
                log.exception("RunningHub queue task failed")
                return False, str(e), None

        def on_finished(result):
            success, info, meta = result
            if success:
                task["task_id"] = info
                task["state"] = "submitted"
                task["submit_count"] = task.get("submit_count", 0) + 1
                self.rh_submitted_tasks[info] = {
                    "task": task,
                    "meta": meta,
                    "status": "SUBMITTED",
                    "results": None,
                    "paused": False,
                    "protocol": bool(meta and meta.get("protocol")),
                }
                self.add_task_to_list(
                    info,
                    status="⏳ 排队中",
                    task_type="RunningHub",
                    source="云端",
                    extra={"wf_id": wf_id, "aud_file": aud_file, "img_file": img_file, "rh_meta": True}
                )
                self._start_rh_poll_timer()
                self.log_area.append(f"[{idx+1}] 已提交: {info}")
                self._update_rh_queue_stats()
                if meta and meta.get("retried_plus"):
                    self.log_area.append(f"[{idx+1}] 首次提交返回 435（未找到独占实例），已自动改用 plus 实例重试成功")
            else:
                is_415 = "[415]" in info or "可用资源不足" in info or "capacity reached" in info.lower()
                if is_415 and task.get("retry_count", 0) < 10:
                    task["retry_count"] = task.get("retry_count", 0) + 1
                    task["state"] = "pending"
                    task["next_attempt_at"] = time.time() + 30
                    self._set_rh_audio_row_state(aud_file, "pending")
                    self.log_area.append(f"[{idx+1}] 提交失败（415 资源不足），30 秒后自动重试第 {task['retry_count']} 次")
                    self._update_rh_queue_stats()
                    if not self.rh_queue_paused:
                        QTimer.singleShot(30000, self._process_rh_queue)
                    else:
                        self.btn_run_workflow.setEnabled(True)
                    return
                task["state"] = "failed"
                task["error"] = info
                self._set_rh_audio_row_state(aud_file, "failed")
                self.log_area.append(f"[{idx+1}] 提交失败: {info}")
                self._update_rh_queue_stats()

            # 提交成功后在 RunningHub 任务完成时才继续下一个
            if not success:
                # 提交失败没有占用 RunningHub 额度，直接继续下一个
                if not self.rh_queue_paused:
                    QTimer.singleShot(500, self._process_rh_queue)
                else:
                    self.btn_run_workflow.setEnabled(True)

        self.start_worker(run_task, on_finished)

    def _poll_rh_tasks(self):
        """轮询所有已提交的 RunningHub 任务状态。"""
        if not self.rh_submitted_tasks:
            # 没有运行中任务，停止轮询
            if hasattr(self, "rh_poll_timer") and self.rh_poll_timer.isActive():
                self.rh_poll_timer.stop()
            return

        for task_id, record in list(self.rh_submitted_tasks.items()):
            if record.get("paused"):
                continue
            self._query_single_rh_task(task_id)

    def _query_single_rh_task(self, task_id):
        """查询单个 RunningHub 任务状态并更新 UI。"""
        def run_task():
            # 优先走服务端状态接口（服务端透传 RunningHub 响应），失败回退直连
            from utils import digital_human_client as dhc
            data = dhc.get_task_status(task_id)
            if data is not None:
                return data
            return self.runninghub.get_task_status(task_id)

        def on_done(resp):
            if not resp or not isinstance(resp, dict):
                return
            code = resp.get("code")
            data = resp.get("data") or resp
            status = data.get("status") or data.get("errorMessage") or "UNKNOWN"
            error_msg = data.get("errorMessage") or ""
            results = data.get("results") or []

            record = self.rh_submitted_tasks.get(task_id)
            if not record:
                return
            if record.get("protocol"):
                self._query_single_comfy_task(task_id)
                return

            task = record["task"]
            record["status"] = status
            record["results"] = results

            # 更新任务表状态
            self._update_rh_task_status(task_id, status, results)

            if status == "SUCCESS":
                task["state"] = "done"
                self.rh_submitted_tasks.pop(task_id, None)
                self._set_rh_audio_row_state(task.get("aud_file") or "", "done")
                processed = getattr(self, "_rh_processed_audios", None)
                if processed is not None:
                    processed.add(task.get("aud_file") or "")
                self.log_area.append(f"任务完成: {task_id}，结果 {len(results)} 个")
                self._update_rh_queue_stats()
                self._auto_download_rh_results(task_id, results, record.get("meta") or {})
            elif status == "FAILED":
                task["state"] = "failed"
                task["error"] = error_msg
                self.rh_submitted_tasks.pop(task_id, None)
                self._set_rh_audio_row_state(task.get("aud_file") or "", "failed")
                self.log_area.append(f"任务失败: {task_id} {error_msg}")
                self._update_rh_queue_stats()

            if status in ("SUCCESS", "FAILED") and not self.rh_queue_paused:
                self.log_area.append("任务结束，等待 30 秒让 RunningHub 独占实例释放后提交下一个任务")
                QTimer.singleShot(30000, self._process_rh_queue)

            # 检查是否全部完成
            if not self.rh_submitted_tasks and all(t["state"] in ("done", "failed") for t in self.rh_pending_tasks):
                if hasattr(self, "rh_poll_timer") and self.rh_poll_timer.isActive():
                    self.rh_poll_timer.stop()
                self.btn_run_workflow.setEnabled(
                    bool(self.rh_workflow_id_input.text().strip()) and self._rh_has_new_audios())
                self.log_area.append("批量任务队列已全部结束。")

        self.start_worker(run_task, on_done)

    def _query_single_comfy_task(self, task_id):
        """查询 RunningHub 在线工作流（ComfyUI 协议）的历史状态。"""
        from utils.runninghub_comfy_client import get_runninghub_comfy_client

        def run_task():
            client = get_runninghub_comfy_client(self.ai_config)
            entry = client.get_history(task_id)
            if not entry:
                return None, None, None
            status = (entry.get("status") or "").lower()
            results = client.history_outputs(entry)
            err = ""
            if isinstance(entry.get("error"), dict):
                err = str(entry.get("error", {}).get("message") or entry.get("error", {}).get("exception_message") or "")
            elif entry.get("exception_message"):
                err = str(entry.get("exception_message"))
            elif entry.get("error"):
                err = str(entry.get("error"))
            return status, results, err

        def on_done(result):
            status, results, err = result
            if status is None:
                return
            record = self.rh_submitted_tasks.get(task_id)
            if not record:
                return
            task = record["task"]
            record["status"] = status
            record["results"] = results

            if status in ("success", "completed"):
                task["state"] = "done"
                self.rh_submitted_tasks.pop(task_id, None)
                self._set_rh_audio_row_state(task.get("aud_file") or "", "done")
                processed = getattr(self, "_rh_processed_audios", None)
                if processed is not None:
                    processed.add(task.get("aud_file") or "")
                self.log_area.append(f"任务完成: {task_id}，结果 {len(results)} 个")
                self._update_rh_queue_stats()
                self._auto_download_rh_results(task_id, results, record.get("meta") or {})
            elif status in ("error", "failed"):
                task["state"] = "failed"
                task["error"] = err or "工作流运行失败"
                self.rh_submitted_tasks.pop(task_id, None)
                self._set_rh_audio_row_state(task.get("aud_file") or "", "failed")
                self.log_area.append(f"任务失败: {task_id} {task['error']}")
                self._update_rh_queue_stats()
            else:
                return

            self._update_rh_task_status(task_id, "SUCCESS" if status in ("success", "completed") else "FAILED", results)
            if not self.rh_queue_paused:
                self.log_area.append("任务结束，等待 30 秒后提交下一个任务")
                QTimer.singleShot(30000, self._process_rh_queue)
            if not self.rh_submitted_tasks and all(t["state"] in ("done", "failed") for t in self.rh_pending_tasks):
                if hasattr(self, "rh_poll_timer") and self.rh_poll_timer.isActive():
                    self.rh_poll_timer.stop()
                self.btn_run_workflow.setEnabled(
                    bool(self.rh_workflow_id_input.text().strip()) and self._rh_has_new_audios())
                self.log_area.append("批量任务队列已全部结束。")

        self.start_worker(run_task, on_done)

    def _update_rh_task_status(self, task_id, status, results):
        """根据 task_id 找到任务表行并更新状态、进度与结果。"""
        for row in range(self.task_table.rowCount()):
            item = self.task_table.item(row, 0)
            if not item:
                continue
            t = item.data(0x0100) or {}
            if item.text() == task_id[:12] or t.get("id") == task_id or t.get("task_id") == task_id:
                status_text = status
                if status == "QUEUED":
                    status_text = "⏳ 排队中"
                elif status == "RUNNING":
                    status_text = "⏳ 运行中"
                elif status == "SUCCESS":
                    status_text = "✅ 完成"
                elif status == "FAILED":
                    status_text = "❌ 失败"
                elif status == "PAUSED":
                    status_text = "⏸ 已暂停"
                self.task_table.item(row, 3).setText(status_text)
                p_bar = self.task_table.cellWidget(row, 4)
                if p_bar and isinstance(p_bar, QProgressBar):
                    p_bar.setValue(100 if status in ("SUCCESS", "FAILED") else 50)
                # 更新详情数据
                t = item.data(0x0100) or {}
                t["status"] = status_text
                t["results"] = results
                t["result"] = results
                item.setData(0x0100, t)
                # 完成/失败时启用下载按钮，并禁用暂停/恢复
                registry = self._task_registry.get(task_id)
                if registry:
                    if status in ("SUCCESS", "FAILED"):
                        btn = registry.get("download_btn")
                        if btn:
                            btn.setEnabled(True)
                        for key in ("pause_btn", "resume_btn"):
                            btn = registry.get(key)
                            if btn:
                                btn.setEnabled(False)
                break

    def _auto_download_rh_results(self, task_id, results, meta=None):
        """任务成功后自动把 RunningHub 结果下载到本地目录。

        命名规范：以音频文件名为基础，单个结果为
        《音频名》.扩展名；多个结果为 《音频名》_序号.扩展名；
        同名文件存在时追加 task_id 避免覆盖。
        """
        if not results:
            self.log_area.append(f"任务 {task_id} 完成，但没有可下载的结果。")
            return
        from utils import config_manager as cm
        from datetime import datetime
        base_dir = cm.get_setting("local_config", "cache_dir", "") or os.path.join(PROJECT_ROOT, "outputs", "runninghub")
        save_dir = os.path.join(base_dir, datetime.now().strftime("%Y%m%d"))
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            log.error(f"创建 RunningHub 下载目录失败: {e}")
            self.log_area.append(f"自动下载失败，无法创建目录: {save_dir} ({e})")
            return
        aud_name = ""
        if meta and meta.get("aud_file"):
            aud_name = os.path.splitext(os.path.basename(meta["aud_file"]))[0]
        self.log_area.append(f"任务完成，开始自动下载到: {save_dir}")
        if aud_name:
            self.log_area.append(f"下载命名规范: {aud_name}.扩展名（多个结果时为 {aud_name}_序号.扩展名）")

        def run_task():
            import requests
            downloaded_paths = []
            failed = 0
            for idx, res in enumerate(results, start=1):
                if not isinstance(res, dict):
                    continue
                url = res.get("url")
                # 服务端透传的结果可能是相对路径，拼统一计算节点地址
                if url and isinstance(url, str) and url.startswith("/"):
                    from utils import digital_human_client as dhc
                    base = dhc._get_server_url()
                    if base:
                        url = base + url
                text_val = res.get("text")
                filename = res.get("filename") or ""
                protocol = bool(meta and meta.get("protocol"))
                if not url and not text_val and not filename:
                    continue
                ext = res.get("outputType", "bin")
                if aud_name:
                    base_name = aud_name if len(results) == 1 else f"{aud_name}_{idx}"
                else:
                    base_name = f"{task_id}_{idx}"
                name = f"{base_name}.{ext}"
                path = os.path.join(save_dir, name)
                if os.path.exists(path):
                    name = f"{base_name}_{task_id}.{ext}"
                    path = os.path.join(save_dir, name)
                try:
                    if filename and protocol:
                        from utils.runninghub_comfy_client import get_runninghub_comfy_client
                        client = get_runninghub_comfy_client(self.ai_config)
                        data = client.download_output(filename, res.get("subfolder") or "", res.get("type") or "output")
                        with open(path, "wb") as f:
                            f.write(data)
                        downloaded_paths.append(path)
                    elif url:
                        r = requests.get(url, timeout=120)
                        if r.status_code == 200:
                            with open(path, "wb") as f:
                                f.write(r.content)
                            downloaded_paths.append(path)
                        else:
                            failed += 1
                            log.error(f"自动下载失败 HTTP {r.status_code}: {url}")
                    else:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(str(text_val))
                        downloaded_paths.append(path)
                except Exception as e:
                    failed += 1
                    log.error(f"自动下载失败 {url or text_val}: {e}")
            return downloaded_paths, failed, save_dir

        def on_finished(result):
            downloaded_paths, failed, save_dir = result
            for path in downloaded_paths:
                self.log_area.append(f"已下载: {path}")
            if downloaded_paths:
                for t in getattr(self, "rh_pending_tasks", []):
                    if t.get("task_id") == task_id or t.get("aud_file") == (meta or {}).get("aud_file"):
                        t["downloaded"] = True
                        break
                self._update_rh_queue_stats()
            if failed:
                self.log_area.append(f"自动下载完成：成功 {len(downloaded_paths)} 个，失败 {failed} 个，目录: {save_dir}")
            else:
                self.log_area.append(f"自动下载完成：成功 {len(downloaded_paths)} 个，目录: {save_dir}")

        self.start_worker(run_task, on_finished)


    def _set_rh_action_buttons(self, task_id, paused=False):
        """切换 RunningHub 任务行的暂停/恢复按钮状态。"""
        registry = getattr(self, "_task_registry", {}).get(task_id)
        if not registry:
            return
        pause_btn = registry.get("pause_btn")
        resume_btn = registry.get("resume_btn")
        if pause_btn:
            pause_btn.setEnabled(not paused)
        if resume_btn:
            resume_btn.setEnabled(paused)

    def cancel_rh_task(self, task_id):
        """取消/移除 RunningHub 任务：从队列和任务表中移除。"""
        # 从待处理队列中移除
        if hasattr(self, "rh_pending_tasks"):
            self.rh_pending_tasks = [t for t in self.rh_pending_tasks if t.get("task_id") != task_id and t.get("aud_file") != task_id]
        # 从已提交记录中移除
        if hasattr(self, "rh_submitted_tasks"):
            self.rh_submitted_tasks.pop(task_id, None)
        # 从任务表中移除
        for row in range(self.task_table.rowCount() - 1, -1, -1):
            item = self.task_table.item(row, 0)
            if not item:
                continue
            t = item.data(0x0100) or {}
            if t.get("task_id") == task_id or item.text() == task_id[:12]:
                self.task_table.removeRow(row)
                self._task_registry.pop(task_id, None)
                break
        self.log_area.append(f"已取消: {task_id}")

    def pause_rh_task(self, task_id):
        """暂停某个 RunningHub 任务（或队列）。"""
        record = self.rh_submitted_tasks.get(task_id)
        if record:
            record["paused"] = True
            self._update_rh_task_status(task_id, "PAUSED", record.get("results"))
        else:
            for t in self.rh_pending_tasks:
                if t.get("task_id") == task_id or t.get("aud_file") == task_id:
                    t["state"] = "paused"
                    break
        self._set_rh_action_buttons(task_id, paused=True)
        self.log_area.append(f"已暂停: {task_id}")

    def resume_rh_task(self, task_id):
        """恢复某个 RunningHub 任务（或队列）。"""
        record = self.rh_submitted_tasks.get(task_id)
        if record:
            record["paused"] = False
            self._query_single_rh_task(task_id)
        else:
            for t in self.rh_pending_tasks:
                if t.get("task_id") == task_id or t.get("aud_file") == task_id:
                    t["state"] = "pending"
                    break
        self.rh_queue_paused = False
        self._start_rh_poll_timer()
        self._process_rh_queue()
        self._set_rh_action_buttons(task_id, paused=False)
        self.log_area.append(f"已恢复: {task_id}")

    def export_all_rh_results(self):
        """导出所有已完成的 RunningHub 任务结果到本地目录。"""
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out_dir:
            return

        from datetime import datetime
        import requests

        exported = 0
        failed = 0
        for row in range(self.task_table.rowCount()):
            item = self.task_table.item(row, 0)
            if not item:
                continue
            t = item.data(0x0100) or {}
            if not t.get("rh_meta"):
                continue
            status_text = self.task_table.item(row, 3).text() if self.task_table.item(row, 3) else ""
            if "完成" not in status_text:
                continue
            results = t.get("results") or []
            for res_idx, res in enumerate(results, start=1):
                url = res.get("url") if isinstance(res, dict) else None
                if not url:
                    continue
                ext = res.get("outputType", "bin")
                aud_file = t.get("aud_file") or ""
                aud_name = os.path.splitext(os.path.basename(aud_file))[0] if aud_file else ""
                if aud_name:
                    base_name = aud_name if len(results) == 1 else f"{aud_name}_{res_idx}"
                else:
                    base_name = f"{t.get('task_id', item.text())}_{datetime.now().strftime('%H%M%S')}"
                name = f"{base_name}.{ext}"
                path = os.path.join(out_dir, name)
                if os.path.exists(path):
                    name = f"{base_name}_{t.get('task_id', item.text())}.{ext}"
                    path = os.path.join(out_dir, name)
                try:
                    r = requests.get(url, timeout=60)
                    if r.status_code == 200:
                        with open(path, "wb") as f:
                            f.write(r.content)
                        exported += 1
                        self.log_area.append(f"已导出: {path}")
                    else:
                        failed += 1
                except Exception as e:
                    log.error(f"导出结果失败 {url}: {e}")
                    failed += 1

        QMessageBox.information(self, "导出完成", f"成功导出 {exported} 个文件，失败 {failed} 个。\n目录: {out_dir}")

    # ------------------------------------------------------------------
    # RunningHub 平台接入：工作流列表管理
    # ------------------------------------------------------------------


    def _rh_migrate_workflow_items(self, items):
        """兼容旧配置：把纯字符串或缺少 type 的字典统一成 {id, name, type}。"""
        result = []
        if not isinstance(items, list):
            return result
        for item in items:
            if isinstance(item, str):
                item = {"id": item, "name": item, "type": "其他", "instanceType": "default"}
            elif isinstance(item, dict):
                if not item.get("id"):
                    continue
                if not item.get("type"):
                    item["type"] = "其他"
                if not item.get("name"):
                    item["name"] = item["id"]
                if not item.get("instanceType"):
                    item["instanceType"] = "default"
            else:
                continue
            result.append(item)
        return result


    def _rh_find_workflow_config(self, wf_id):
        """按工作流 ID 查找本地配置（含实例类型等），未找到返回 None。"""
        from utils import config_manager as cm
        items = cm.get_setting("ai_config", "runninghub_workflows", [])
        for item in self._rh_migrate_workflow_items(items):
            if item.get("id") == wf_id:
                return item
        return None

    def _rh_set_workflow_table(self, items):
        """把工作流列表填充到平台接入页的 QTableWidget。"""
        self.rh_workflow_table.setRowCount(0)
        for item in items:
            self._rh_add_workflow_row(item)

    def _rh_add_workflow_row(self, data):
        """在表格末尾添加一行工作流。"""
        row = self.rh_workflow_table.rowCount()
        self.rh_workflow_table.insertRow(row)
        name_item = QTableWidgetItem(data.get("name", ""))
        type_item = QTableWidgetItem(data.get("type", "其他"))
        id_item = QTableWidgetItem(data.get("id", ""))
        instance_item = QTableWidgetItem(data.get("instanceType") or "default")
        for it in (name_item, type_item, id_item, instance_item):
            it.setData(Qt.UserRole, data)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        self.rh_workflow_table.setItem(row, 0, name_item)
        self.rh_workflow_table.setItem(row, 1, type_item)
        self.rh_workflow_table.setItem(row, 2, id_item)
        self.rh_workflow_table.setItem(row, 3, instance_item)

    def _rh_update_workflow_row(self, row, data):
        """更新表格中指定行的工作流数据。"""
        name_item = QTableWidgetItem(data.get("name", ""))
        type_item = QTableWidgetItem(data.get("type", "其他"))
        id_item = QTableWidgetItem(data.get("id", ""))
        instance_item = QTableWidgetItem(data.get("instanceType") or "default")
        for it in (name_item, type_item, id_item, instance_item):
            it.setData(Qt.UserRole, data)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        self.rh_workflow_table.setItem(row, 0, name_item)
        self.rh_workflow_table.setItem(row, 1, type_item)
        self.rh_workflow_table.setItem(row, 2, id_item)
        self.rh_workflow_table.setItem(row, 3, instance_item)

    def _rh_load_workflow_list(self):
        """从 ai_config 加载保存的 RunningHub 工作流列表。"""
        from utils import config_manager as cm
        items = cm.get_setting("ai_config", "runninghub_workflows", [])
        items = self._rh_migrate_workflow_items(items)
        self._rh_set_workflow_table(items)
        self._rh_maybe_refresh_dh_selector()

    def _rh_save_workflow_list(self):
        """把当前 RunningHub 工作流列表保存到 ai_config。"""
        from utils import config_manager as cm
        items = []
        for row in range(self.rh_workflow_table.rowCount()):
            item = self.rh_workflow_table.item(row, 0)
            data = item.data(Qt.UserRole) if item else {}
            if isinstance(data, dict) and data.get("id"):
                items.append(data)
        cm.set_setting("ai_config", "runninghub_workflows", items)

    def _rh_selected_workflow(self):
        """返回平台接入页当前选中的工作流数据字典，未选中返回 None。"""
        row = self.rh_workflow_table.currentRow()
        if row < 0:
            return None
        item = self.rh_workflow_table.item(row, 0)
        if not item:
            return None
        data = item.data(Qt.UserRole) or {}
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return data

    def _rh_workflow_dialog(self, title, data=None):
        """添加/编辑工作流的统一对话框，返回 {id, name, type, instanceType} 或 None。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_input = QLineEdit()
        type_combo = QComboBox()
        type_combo.addItems(WORKFLOW_TYPES)
        id_input = QLineEdit()
        instance_combo = QComboBox()
        instance_combo.addItems(["default", "plus"])
        instance_combo.setToolTip("default=24G显存，plus=48G显存；部分工作流必须使用 plus")
        if data:
            name_input.setText(data.get("name", ""))
            idx = type_combo.findText(data.get("type", "其他"))
            if idx < 0:
                idx = type_combo.findText("其他")
            type_combo.setCurrentIndex(idx)
            id_input.setText(data.get("id", ""))
            iidx = instance_combo.findText(data.get("instanceType") or "default")
            if iidx >= 0:
                instance_combo.setCurrentIndex(iidx)
        else:
            type_combo.setCurrentIndex(type_combo.findText("其他"))
        form.addRow("名称:", name_input)
        form.addRow("类型:", type_combo)
        form.addRow("工作流 ID:", id_input)
        form.addRow("实例类型:", instance_combo)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return None
        name = name_input.text().strip()
        wf_id = id_input.text().strip()
        wf_type = type_combo.currentText()
        instance_type = instance_combo.currentText()
        if not wf_id:
            QMessageBox.warning(self, "输入错误", "工作流 ID 不能为空")
            return None
        return {"id": wf_id, "name": name or wf_id, "type": wf_type, "instanceType": instance_type}

    def _rh_refresh_workflow_list(self):
        """拉取 RunningHub 工作流列表并合并到本地表格。

        优先走服务端订阅列表接口（无需 API Key）；服务端不可用时回退直连 RunningHub API。
        """
        if not self.runninghub:
            self.rh_workflow_list_status.setText("RunningHub 模块未初始化")
            return
        self.rh_workflow_list_status.setText("正在获取工作流列表...")

        def run_task():
            from utils import digital_human_client as dhc
            items = dhc.get_workflows()
            if items is not None:
                return items, True
            api_key = self.runninghub_api_key_input.text().strip()
            if not api_key:
                return None, False
            base_url = self.runninghub_base_url_input.text().strip().rstrip("/") or "https://www.runninghub.cn"
            self.runninghub.update_config(api_key=api_key, base_url=base_url)
            return self.runninghub.get_workflow_list(), False

        def on_done(result):
            items, from_server = result
            if items is None:
                self.rh_workflow_list_status.setText(
                    "无法从服务端或 API 读取工作流列表。RunningHub 未公开列表接口，请手动添加工作流 ID。")
                return
            if not items:
                self.rh_workflow_list_status.setText("接口返回成功，但当前没有工作流。")
                return
            existing_ids = set()
            for row in range(self.rh_workflow_table.rowCount()):
                data = self.rh_workflow_table.item(row, 0).data(Qt.UserRole) or {}
                existing_ids.add(data.get("id"))
            added = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                wf_id = item.get("id") or item.get("workflowId") or item.get("webappId")
                name = item.get("name") or item.get("title") or wf_id
                if wf_id and wf_id not in existing_ids:
                    # 服务端订阅条目用 instance_type（下划线），统一成 instanceType
                    self._rh_add_workflow_row({
                        "id": wf_id,
                        "name": name,
                        "type": item.get("type") or "其他",
                        "instanceType": item.get("instance_type") or item.get("instanceType") or "default",
                    })
                    existing_ids.add(wf_id)
                    added += 1
            self._rh_save_workflow_list()
            self._rh_maybe_refresh_dh_selector()
            src = "服务端订阅列表" if from_server else "RunningHub API"
            self.rh_workflow_list_status.setText(f"已从{src}刷新，新增 {added} 个工作流")

        self.start_worker(run_task, on_done)

    def _rh_show_add_workflow_dialog(self):
        """弹出对话框添加工作流，添加后自动选中并显示节点。"""
        data = self._rh_workflow_dialog("添加工作流")
        if not data:
            return
        for row in range(self.rh_workflow_table.rowCount()):
            existing = self.rh_workflow_table.item(row, 0).data(Qt.UserRole) or {}
            if existing.get("id") == data["id"]:
                self.rh_workflow_list_status.setText("该工作流 ID 已存在")
                return
        self._rh_add_workflow_row(data)
        self._rh_save_workflow_list()
        self.rh_workflow_table.setCurrentCell(self.rh_workflow_table.rowCount() - 1, 0)
        self._rh_view_workflow_nodes()
        self._rh_maybe_refresh_dh_selector()

    def _rh_show_edit_workflow_dialog(self):
        """编辑当前选中工作流的名称、类型、ID。"""
        row = self.rh_workflow_table.currentRow()
        if row < 0:
            self.rh_workflow_list_status.setText("请先选择一个工作流")
            return
        old = self.rh_workflow_table.item(row, 0).data(Qt.UserRole) or {}
        data = self._rh_workflow_dialog("编辑工作流", old)
        if not data:
            return
        if data["id"] != old.get("id"):
            for r in range(self.rh_workflow_table.rowCount()):
                if r == row:
                    continue
                existing = self.rh_workflow_table.item(r, 0).data(Qt.UserRole) or {}
                if existing.get("id") == data["id"]:
                    self.rh_workflow_list_status.setText("该工作流 ID 已存在")
                    return
        self._rh_update_workflow_row(row, data)
        self._rh_save_workflow_list()
        self._rh_view_workflow_nodes()
        self._rh_maybe_refresh_dh_selector()

    def _rh_on_workflow_selection_changed(self):
        """平台接入工作流列表：切换选中项时自动显示节点详情。"""
        QTimer.singleShot(100, self._rh_view_workflow_nodes)

    def _rh_view_workflow_nodes(self):
        """在平台接入 Tab 内联显示选中工作流的所有节点、输入、输出信息。"""
        data = self._rh_selected_workflow()
        if not data:
            self.rh_workflow_list_status.setText("请先选择一个工作流")
            if hasattr(self, "rh_workflow_node_display"):
                self.rh_workflow_node_display.setText("选择上方工作流后，节点信息会显示在这里。")
            return
        wf_id = data.get("id")
        if not wf_id:
            return
        if hasattr(self, "rh_workflow_node_display"):
            self.rh_workflow_node_display.setText("正在获取节点...")
        self.rh_workflow_list_status.setText("正在获取 " + wf_id + " 的节点...")

        def run_task():
            # 优先走服务端工作流 JSON 接口，失败回退直连 RunningHub
            from utils import digital_human_client as dhc
            wf = dhc.get_workflow_json(wf_id)
            if wf is not None:
                return wf
            return self.runninghub.get_workflow_json(wf_id)

        def on_done(wf):
            if not wf or not isinstance(wf, dict):
                msg = "无法获取工作流 JSON，请检查工作流 ID 和 API Key"
                self.rh_workflow_list_status.setText(msg)
                if hasattr(self, "rh_workflow_node_display"):
                    self.rh_workflow_node_display.setText(msg)
                return

            references = {}
            for src_id, src_node in wf.items():
                if not isinstance(src_node, dict):
                    continue
                inputs = src_node.get("inputs", {})
                for field_name, val in inputs.items():
                    if isinstance(val, list) and len(val) >= 2 and isinstance(val[0], str):
                        target_id = val[0]
                        references.setdefault(target_id, []).append((src_id, src_node.get("class_type", ""), field_name))

            sections = ["<b>工作流 ID:</b> " + wf_id + "<br><br>"]
            sections.append("<b>输入节点（需要映射的节点）：</b>")
            input_nodes = []
            other_nodes = []
            for node_id, node in wf.items():
                if not isinstance(node, dict):
                    continue
                class_type = node.get("class_type", "")
                meta = node.get("_meta", {})
                title = meta.get("title") or class_type
                inputs = node.get("inputs", {})

                input_lines = []
                for field_name, val in inputs.items():
                    if isinstance(val, list) and len(val) >= 2:
                        input_lines.append("  • " + field_name + ": 连接自节点 [" + val[0] + "]")
                    elif val is None or val == "":
                        input_lines.append("  • " + field_name + ": （未设置）")
                    else:
                        input_lines.append("  • " + field_name + ": " + str(val))

                ref_lines = []
                for ref_id, ref_class, ref_field in references.get(node_id, []):
                    ref_lines.append("  • 被节点 [" + ref_id + "] " + ref_class + " 的 " + ref_field + " 引用")
                if not ref_lines:
                    ref_lines.append("  • 输出：暂无下游连接")

                node_html = "<br><b>节点 [" + node_id + "] " + title + "</b>（" + class_type + "）"
                if input_lines:
                    node_html += "<br><u>输入：</u><br>" + "<br>".join(input_lines)
                if ref_lines:
                    node_html += "<br><u>输出：</u><br>" + "<br>".join(ref_lines)

                has_media_input = any(f in inputs for f in ("image", "audio"))
                if has_media_input:
                    input_nodes.append(node_html)
                else:
                    other_nodes.append(node_html)

            if input_nodes:
                sections.append("<br>".join(input_nodes))
            else:
                sections.append("<i>未发现图片/音频输入节点</i>")

            sections.append("<br><br><b>其他节点：</b>")
            if other_nodes:
                sections.append("<br>".join(other_nodes[:20]))
                if len(other_nodes) > 20:
                    sections.append("<br><i>...还有 " + str(len(other_nodes) - 20) + " 个节点未显示</i>")
            else:
                sections.append("<i>无</i>")

            html = "".join(sections)
            self.rh_workflow_list_status.setText("已获取 " + str(len(input_nodes)) + " 个输入节点，共 " + str(len(other_nodes)) + " 个其他节点")
            if hasattr(self, "rh_workflow_node_display"):
                self.rh_workflow_node_display.setText(html)

        self.start_worker(run_task, on_done)

    def _rh_remove_workflow(self):
        """从列表中删除选中的工作流。"""
        row = self.rh_workflow_table.currentRow()
        if row < 0:
            self.rh_workflow_list_status.setText("请先选择一个工作流")
            return
        self.rh_workflow_table.removeRow(row)
        self._rh_save_workflow_list()
        self.rh_workflow_list_status.setText("已删除")
        self._rh_maybe_refresh_dh_selector()

    def _rh_maybe_refresh_dh_selector(self):
        """平台接入工作流变更后，同步刷新数字人 Tab 的类型过滤下拉列表。"""
        if hasattr(self, "rh_workflow_selector") and hasattr(self, "rh_workflow_id_input"):
            self._rh_refresh_dh_workflow_selector()

    def _rh_refresh_dh_workflow_selector(self):
        """数字人 Tab：只显示类型为「数字人」的工作流下拉列表。"""
        from utils import config_manager as cm
        items = cm.get_setting("ai_config", "runninghub_workflows", [])
        items = self._rh_migrate_workflow_items(items)
        digital = [it for it in items if it.get("type") == "数字人"]
        current_id = self.rh_workflow_id_input.text().strip()
        self.rh_workflow_selector.blockSignals(True)
        self.rh_workflow_selector.clear()
        for it in digital:
            name = it.get("name") or it.get("id")
            self.rh_workflow_selector.addItem(name, it.get("id"))
        idx = self.rh_workflow_selector.findData(current_id)
        if idx < 0 and self.rh_workflow_selector.count() > 0:
            idx = 0
        self.rh_workflow_selector.setCurrentIndex(idx)
        self.rh_workflow_selector.blockSignals(False)
        self._on_rh_dh_workflow_changed(idx)
        # 本地还没有数字人工作流时，尝试从服务端订阅列表自动补全（失败静默）
        if not digital:
            self._rh_fetch_server_workflows_async()

    def _rh_fetch_server_workflows_async(self):
        """后台拉取服务端订阅的工作流列表并合并到本地（供数字人 Tab 下拉使用）。"""
        if getattr(self, "_rh_server_fetching", False):
            return
        self._rh_server_fetching = True

        def run_task():
            from utils import digital_human_client as dhc
            return dhc.get_workflows()

        def on_done(items):
            self._rh_server_fetching = False
            if not items:
                return
            existing_ids = set()
            for row in range(self.rh_workflow_table.rowCount()):
                item = self.rh_workflow_table.item(row, 0)
                if item:
                    data = item.data(Qt.UserRole) or {}
                    existing_ids.add(data.get("id"))
            added = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                wf_id = it.get("id") or it.get("workflowId")
                if wf_id and wf_id not in existing_ids:
                    self._rh_add_workflow_row({
                        "id": wf_id,
                        "name": it.get("name") or wf_id,
                        "type": it.get("type") or "其他",
                        "instanceType": it.get("instance_type") or it.get("instanceType") or "default",
                    })
                    existing_ids.add(wf_id)
                    added += 1
            if added:
                self._rh_save_workflow_list()
                self._rh_refresh_dh_workflow_selector()

        self.start_worker(run_task, on_done)

    def _on_rh_dh_workflow_changed(self, index):
        """数字人 Tab：下拉列表切换时同步隐藏 ID 输入框并自动获取节点。"""
        wf_id = self.rh_workflow_selector.itemData(index) if index >= 0 else None
        self.rh_workflow_id_input.setText(wf_id or "")
        if wf_id:
            self.rh_workflow_info.setText("已选择工作流: " + wf_id + "，正在获取节点...")
            self._reset_rh_node_list()
            QTimer.singleShot(200, self.view_rh_api_detail)
        else:
            self.rh_workflow_info.setText("请在平台接入中配置类型为「数字人」的工作流")
            self._reset_rh_node_list()
