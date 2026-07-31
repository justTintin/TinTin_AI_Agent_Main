# -*- coding: utf-8 -*-
"""
产品生图页面。

通过服务端 ComfyUI 代理，实现「产品图 + 场景描述 → AI 生成背景/融图」能力。
- 左侧：产品选择（复用产品库）+ 产品图上传/预览
- 右侧：工作流选择 + 场景描述 + 生成 + 结果预览/下载

服务端接口（代理模式）：
  GET  /comfyui/workflows          列出可用工作流
  GET  /comfyui/workflow?path=xx   获取工作流 JSON
  POST /comfyui/upload/image       上传产品图
  POST /comfyui/run                提交工作流执行
  GET  /comfyui/history            执行历史（轮询结果）
  GET  /comfyui/view?filename=xx   获取生成图片
"""
import os
import time
import json
import shutil
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QFrame, QWidget, QComboBox, QProgressBar, QFileDialog, QSplitter,
    QScrollArea, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QPixmap

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from config.paths import OUTPUTS_DIR
from gui.searchable_combo import SearchableComboBox

PRODUCT_IMAGE_OUTPUT_DIR = os.path.join(OUTPUTS_DIR, "product_images")


# ── Workers ──────────────────────────────────────────────────────────────────

class LoadProductsWorker(BaseWorker):
    """后台加载产品库列表。"""
    finished = Signal(list)

    def do_work(self):
        from utils.product_library_manager import ProductLibraryManager
        mgr = ProductLibraryManager()
        items = mgr.items or []
        self.finished.emit(items)


class LoadWorkflowsWorker(BaseWorker):
    """后台获取服务端可用工作流列表。"""
    finished = Signal(list)

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url

    def do_work(self):
        from utils.http_client import http_get
        url = f"{self.server_url}/comfyui/workflows"
        r = http_get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        workflows = data.get("workflows", [])
        self.finished.emit(workflows)


class ServerCheckWorker(BaseWorker):
    """后台检测服务端 ComfyUI 状态，避免阻塞界面。"""
    finished = Signal(str)  # 状态文本

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url

    def do_work(self):
        from utils.http_client import http_get
        try:
            r = http_get(f"{self.server_url}/comfyui/status", timeout=5, quiet=True)
            if r.status_code == 200:
                data = r.json()
                if data.get("online"):
                    ver = data.get("version", "?")
                    self.finished.emit(f"✅ ComfyUI 在线 (v{ver})")
                    return
            self.finished.emit("❌ ComfyUI 离线")
        except Exception:
            self.finished.emit("❌ 服务端不可达")


class UploadAndRunWorker(BaseWorker):
    """上传产品图 → 提交工作流 → 轮询结果 → 下载生成图。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # 本地下载的结果文件路径列表

    def __init__(self, server_url, image_path, workflow_json, prompt_text, output_dir):
        super().__init__()
        self.server_url = server_url
        self.image_path = image_path
        self.workflow_json = workflow_json
        self.prompt_text = prompt_text
        self.output_dir = output_dir

    def do_work(self):
        from utils.http_client import http_get, http_post

        # 1. 上传产品图
        self.phase.emit("正在上传产品图…")
        self.progress.emit(10)
        upload_url = f"{self.server_url}/comfyui/upload/image"
        with open(self.image_path, "rb") as f:
            resp = http_post(upload_url, files={"image": f},
                             params={"overwrite": "true"}, timeout=60)
        resp.raise_for_status()
        uploaded_name = resp.json().get("name", os.path.basename(self.image_path))
        log.info(f"[产品生图] 上传成功: {uploaded_name}")

        # 2. 注入参数到工作流
        self.phase.emit("正在提交生成任务…")
        self.progress.emit(25)
        workflow = self._inject_params(self.workflow_json, uploaded_name)

        # 3. 提交执行
        run_url = f"{self.server_url}/comfyui/run"
        payload = {"prompt": workflow, "client_id": "tintin-studio"}
        resp = http_post(run_url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        prompt_id = result.get("prompt_id") or result.get("id") or ""
        if not prompt_id:
            self.error.emit(f"提交失败：服务端未返回 prompt_id\n{json.dumps(result, ensure_ascii=False)[:300]}")
            return
        log.info(f"[产品生图] 任务已提交 prompt_id={prompt_id}")

        # 4. 轮询 history 等待完成
        self.phase.emit("生成中，等待 ComfyUI 出图…")
        self.progress.emit(40)
        history_url = f"{self.server_url}/comfyui/history"
        output_files = []
        for i in range(60):  # 最多等 5 分钟
            time.sleep(5)
            try:
                hr = http_get(history_url, timeout=10)
                if hr.status_code != 200:
                    continue
                hist = hr.json()
                task_hist = hist.get(prompt_id)
                if not task_hist:
                    self.progress.emit(40 + min(i, 20))
                    continue
                status = task_hist.get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    self.error.emit(f"ComfyUI 执行出错：{json.dumps(msgs, ensure_ascii=False)[:500]}")
                    return
                outputs = task_hist.get("outputs", {})
                if outputs:
                    # 收集所有输出图片
                    for node_id, node_out in outputs.items():
                        for img in node_out.get("images", []):
                            output_files.append(img)
                    if output_files:
                        break
            except Exception as e:
                log.warning(f"[产品生图] 轮询异常: {e}")
            self.progress.emit(40 + min(i + 1, 20))

        if not output_files:
            self.error.emit("生成超时（5分钟），请稍后在 ComfyUI 历史中查看。")
            return

        # 5. 下载结果图
        self.phase.emit(f"正在下载 {len(output_files)} 张结果图…")
        self.progress.emit(80)
        os.makedirs(self.output_dir, exist_ok=True)
        downloaded = []
        for idx, img_info in enumerate(output_files):
            fname = img_info.get("filename", f"result_{idx}.png")
            subfolder = img_info.get("subfolder", "")
            img_type = img_info.get("type", "output")
            view_url = (f"{self.server_url}/comfyui/view"
                        f"?filename={fname}&type={img_type}&subfolder={subfolder}")
            try:
                ir = http_get(view_url, timeout=30)
                if ir.status_code == 200:
                    local_path = os.path.join(self.output_dir, fname)
                    with open(local_path, "wb") as f:
                        f.write(ir.content)
                    downloaded.append(local_path)
            except Exception as e:
                log.warning(f"[产品生图] 下载 {fname} 失败: {e}")

        self.progress.emit(100)
        self.phase.emit(f"完成！共 {len(downloaded)} 张图片")
        self.finished.emit(downloaded)

    def _inject_params(self, workflow, uploaded_image_name):
        """将产品图和 prompt 注入工作流节点。

        策略：遍历节点，找到 LoadImage 类型节点替换图片名；
        找到 CLIPTextEncode / 文本相关节点注入 prompt。
        """
        if not isinstance(workflow, dict):
            return workflow
        wf = json.loads(json.dumps(workflow))  # deep copy
        prompt_injected = False
        for node_id, node in wf.items():
            if not isinstance(node, dict):
                continue
            class_type = node.get("class_type", "")
            inputs = node.get("inputs", {})
            # 替换 LoadImage 节点的图片
            if "LoadImage" in class_type or "load_image" in class_type.lower():
                if "image" in inputs:
                    inputs["image"] = uploaded_image_name
            # 注入 prompt 到第一个文本编码节点
            if not prompt_injected and self.prompt_text:
                if "CLIPTextEncode" in class_type or "text" in class_type.lower():
                    if "text" in inputs:
                        inputs["text"] = self.prompt_text
                        prompt_injected = True
        return wf


# ── Page ─────────────────────────────────────────────────────────────────────

class ProductImagePage(BasePage):
    """产品生图页面：产品图 + 场景描述 → ComfyUI 生成。"""

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._products = []
        self._workflows = []
        self._workflow_cache = {}  # path -> workflow json
        self._selected_image = ""
        self._result_files = []

    @property
    def _server_url(self):
        """获取服务端地址（跟随 compute_server_url，未配置返回空串）。"""
        url = (self.ai_config.get("compute_server_url") or "").strip().rstrip("/")
        return url

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # 标题行
        title_row = QHBoxLayout()
        heading = QLabel("🖼️ 产品生图")
        heading.setObjectName("heading")
        title_row.addWidget(heading)
        title_row.addStretch()
        root.addLayout(title_row)

        # 服务端状态/刷新独立一行（标题行不放其它控件，避免被资源监控遮挡）
        status_row = QHBoxLayout()
        self.lbl_server_status = QLabel("检测服务端…")
        self.lbl_server_status.setObjectName("muted_text")
        status_row.addWidget(self.lbl_server_status)
        status_row.addStretch()
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setObjectName("secondary_button")
        btn_refresh.clicked.connect(self._refresh_all)
        status_row.addWidget(btn_refresh)
        root.addLayout(status_row)

        # 主体：左右分栏
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        # 底部状态
        self._build_status_bar(root)

        # 初始加载
        self._refresh_all()

    # ── 左侧面板：产品选择 + 图片 ──────────────────────────────────────────

    def _build_left_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(QLabel("📦 产品选择"))

        # 产品下拉
        self.combo_product = SearchableComboBox(placeholder="输入品牌/型号搜索产品…")
        self.combo_product.currentIndexChanged.connect(self._on_product_selected)
        lay.addWidget(self.combo_product)

        # 产品图预览
        lay.addWidget(QLabel("产品图（白底图）："))
        self.lbl_product_img = QLabel("未选择图片")
        self.lbl_product_img.setAlignment(Qt.AlignCenter)
        self.lbl_product_img.setMinimumSize(200, 200)
        self.lbl_product_img.setMaximumSize(300, 300)
        self.lbl_product_img.setStyleSheet(
            "QLabel { border: 1px dashed #555; border-radius: 8px; background: rgba(255,255,255,0.03); }")
        self.lbl_product_img.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.lbl_product_img)

        # 图片操作按钮
        img_row = QHBoxLayout()
        btn_upload = QPushButton("📁 选择图片")
        btn_upload.setObjectName("primary_button")
        btn_upload.clicked.connect(self._select_image)
        img_row.addWidget(btn_upload)
        btn_clear = QPushButton("清除")
        btn_clear.setObjectName("secondary_button")
        btn_clear.clicked.connect(self._clear_image)
        img_row.addWidget(btn_clear)
        lay.addLayout(img_row)

        self.lbl_image_path = QLabel("")
        self.lbl_image_path.setObjectName("muted_text")
        self.lbl_image_path.setWordWrap(True)
        lay.addWidget(self.lbl_image_path)

        lay.addStretch()
        return panel

    # ── 右侧面板：工作流 + 生成 ────────────────────────────────────────────

    def _build_right_panel(self):
        panel = QFrame()
        panel.setObjectName("card")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        lay.addWidget(QLabel("🎨 生成配置"))

        # 工作流选择
        wf_row = QHBoxLayout()
        wf_row.addWidget(QLabel("工作流:"))
        self.combo_workflow = SearchableComboBox(placeholder="输入工作流名称搜索…")
        self.combo_workflow.currentIndexChanged.connect(self._on_workflow_selected)
        wf_row.addWidget(self.combo_workflow, 1)
        btn_reload_wf = QPushButton("🔄")
        btn_reload_wf.setFixedWidth(36)
        btn_reload_wf.clicked.connect(self._load_workflows)
        wf_row.addWidget(btn_reload_wf)
        lay.addLayout(wf_row)

        # 场景描述 / Prompt
        lay.addWidget(QLabel("场景描述（Prompt）："))
        self.edit_prompt = QTextEdit()
        self.edit_prompt.setPlaceholderText(
            "描述想要的产品背景/场景，例如：\n"
            "「产品放在大理石桌面上，背景是模糊的现代客厅，暖色灯光，高级感」\n\n"
            "选择产品后会自动填入产品信息，可在此基础上修改。")
        self.edit_prompt.setFixedHeight(100)
        lay.addWidget(self.edit_prompt)

        # 生成按钮
        gen_row = QHBoxLayout()
        self.btn_generate = QPushButton("🚀 开始生图")
        self.btn_generate.setObjectName("primary_button")
        self.btn_generate.setMinimumHeight(38)
        self.btn_generate.clicked.connect(self._start_generate)
        gen_row.addWidget(self.btn_generate)
        self.btn_open_output = QPushButton("📂 打开输出目录")
        self.btn_open_output.setObjectName("secondary_button")
        self.btn_open_output.clicked.connect(self._open_output_dir)
        gen_row.addWidget(self.btn_open_output)
        lay.addLayout(gen_row)

        # 结果预览区
        lay.addWidget(QLabel("生成结果："))
        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setMinimumHeight(180)
        self.result_container = QWidget()
        self.result_layout = QGridLayout(self.result_container)
        self.result_layout.setSpacing(8)
        self.result_scroll.setWidget(self.result_container)
        lay.addWidget(self.result_scroll, 1)

        return panel

    # ── 状态栏 ─────────────────────────────────────────────────────────────

    def _build_status_bar(self, root):
        row = QHBoxLayout()
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("muted_text")
        row.addWidget(self.lbl_status, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setMaximumWidth(200)
        row.addWidget(self.progress_bar)
        root.addLayout(row)

    # ── 数据加载 ───────────────────────────────────────────────────────────

    def _refresh_all(self):
        self._check_server()
        self._load_products()
        self._load_workflows()

    def _check_server(self):
        """检测服务端 ComfyUI 状态（后台线程，不阻塞界面）。"""
        self.lbl_server_status.setText("检测服务端…")
        w = self.track_worker(ServerCheckWorker(self._server_url))
        w.finished.connect(self.lbl_server_status.setText)
        w.start()

    def _load_products(self):
        self.combo_product.clear()
        self.combo_product.addItem("加载中…")
        w = LoadProductsWorker()
        self.track_worker(w)
        w.finished.connect(self._on_products_loaded)
        w.error.connect(lambda e: self.lbl_status.setText(f"加载产品库失败: {e}"))
        w.start()

    def _on_products_loaded(self, items):
        self._products = items
        self.combo_product.clear()
        if not items:
            self.combo_product.addItem("（产品库为空，请先在产品资料页同步）")
            return
        for item in items:
            brand = item.get("brand", "")
            model = item.get("model", "")
            label = f"{brand} {model}".strip() or item.get("id", "?")
            self.combo_product.addItem(label, item.get("id"))

    def _load_workflows(self):
        self.combo_workflow.clear()
        self.combo_workflow.addItem("加载中…")
        w = LoadWorkflowsWorker(self._server_url)
        self.track_worker(w)
        w.finished.connect(self._on_workflows_loaded)
        w.error.connect(lambda e: self._on_workflows_error(e))
        w.start()

    def _on_workflows_loaded(self, workflows):
        self._workflows = workflows
        self.combo_workflow.clear()
        if not workflows:
            self.combo_workflow.addItem("（暂无工作流，请在服务端 comfy/workflows/ 放置 .json）")
            return
        for wf in workflows:
            name = wf if isinstance(wf, str) else wf.get("name", str(wf))
            self.combo_workflow.addItem(name)

    def _on_workflows_error(self, err):
        self.combo_workflow.clear()
        self.combo_workflow.addItem(f"加载失败: {err}")

    # ── 交互事件 ───────────────────────────────────────────────────────────

    def _on_product_selected(self, idx):
        if idx < 0 or idx >= len(self._products):
            return
        item = self._products[idx]
        # 自动填入产品信息作为 prompt 基础
        brand = item.get("brand", "")
        model = item.get("model", "")
        category = item.get("category", "")
        selling = item.get("selling_points", "")
        prompt_parts = []
        if category:
            prompt_parts.append(f"品类：{category}")
        if brand:
            prompt_parts.append(f"品牌：{brand}")
        if model:
            prompt_parts.append(f"产品：{model}")
        if selling:
            prompt_parts.append(f"卖点：{selling}")
        if prompt_parts:
            base_prompt = "，".join(prompt_parts)
            self.edit_prompt.setPlainText(
                f"{base_prompt}\n场景：产品放在简约桌面上，背景虚化，柔和光线，电商主图风格")

    def _on_workflow_selected(self, idx):
        pass  # 工作流内容在提交时按需加载

    def _select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择产品图片",
            "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._selected_image = path
            self.lbl_image_path.setText(path)
            self._show_image_preview(path)

    def _clear_image(self):
        self._selected_image = ""
        self.lbl_image_path.setText("")
        self.lbl_product_img.setText("未选择图片")
        self.lbl_product_img.setPixmap(QPixmap())

    def _show_image_preview(self, path):
        pm = QPixmap(path)
        if pm.isNull():
            self.lbl_product_img.setText("无法加载图片")
            return
        scaled = pm.scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_product_img.setPixmap(scaled)

    # ── 生成 ───────────────────────────────────────────────────────────────

    def _start_generate(self):
        # 校验
        if not self._selected_image:
            self.show_warning("请先选择一张产品图片")
            return
        if not os.path.isfile(self._selected_image):
            self.show_warning(f"图片文件不存在：{self._selected_image}")
            return

        prompt_text = self.edit_prompt.toPlainText().strip()
        if not prompt_text:
            self.show_warning("请输入场景描述（Prompt）")
            return

        # 获取工作流
        wf_idx = self.combo_workflow.currentIndex()
        if not self._workflows or wf_idx < 0 or wf_idx >= len(self._workflows):
            self.show_warning("没有可用的工作流，请先在服务端 comfy/workflows/ 目录放置工作流 JSON 文件")
            return

        wf_item = self._workflows[wf_idx]
        wf_path = wf_item if isinstance(wf_item, str) else wf_item.get("path", "")

        # 禁用按钮
        self.btn_generate.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("正在获取工作流…")

        # 先获取工作流 JSON，再启动生成 Worker
        self._fetch_workflow_and_run(wf_path, prompt_text)

    def _fetch_workflow_and_run(self, wf_path, prompt_text):
        """获取工作流 JSON 后启动生成。"""
        from utils.http_client import http_get
        try:
            url = f"{self._server_url}/comfyui/workflow"
            r = http_get(url, params={"path": wf_path}, timeout=10)
            r.raise_for_status()
            workflow_json = r.json()
        except Exception as e:
            self.btn_generate.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.show_error(f"获取工作流失败：{e}")
            return

        # 输出目录
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(PRODUCT_IMAGE_OUTPUT_DIR, ts)

        # 启动 Worker
        w = UploadAndRunWorker(
            self._server_url, self._selected_image,
            workflow_json, prompt_text, output_dir)
        self.track_worker(w)
        w.phase.connect(self.lbl_status.setText)
        w.progress.connect(self.progress_bar.setValue)
        w.finished.connect(self._on_generate_done)
        w.error.connect(self._on_generate_error)
        w.start()

    def _on_generate_done(self, files):
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._result_files = files
        self.lbl_status.setText(f"✅ 生成完成，共 {len(files)} 张图片")
        self._show_results(files)

    def _on_generate_error(self, err):
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"❌ 生成失败")
        self.show_error(f"产品生图失败：\n{err}")

    def _show_results(self, files):
        """在结果区显示生成的图片缩略图。"""
        # 清空旧结果
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, fpath in enumerate(files):
            pm = QPixmap(fpath)
            if pm.isNull():
                continue
            lbl = QLabel()
            scaled = pm.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(scaled)
            lbl.setToolTip(fpath)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda e, p=fpath: self._open_file(p)
            self.result_layout.addWidget(lbl, idx // 3, idx % 3)

    def _open_file(self, path):
        """用系统默认程序打开文件。"""
        import subprocess
        os.startfile(path)

    def _open_output_dir(self):
        os.makedirs(PRODUCT_IMAGE_OUTPUT_DIR, exist_ok=True)
        os.startfile(PRODUCT_IMAGE_OUTPUT_DIR)
