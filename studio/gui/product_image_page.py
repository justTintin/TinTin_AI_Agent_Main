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
from datetime import datetime

from config.paths import OUTPUTS_DIR
from gui.base_page import BasePage
from gui.searchable_combo import SearchableComboBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.base_worker import BaseWorker
from utils.file_dialog_utils import pick_file
from utils.gui_icons import mdi_button
from utils.logger_utils import log

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
    """后台获取服务端可用工作流列表，按 output_type 过滤图片类。"""
    finished = Signal(list)

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url

    def do_work(self):
        from utils import workflow_client as wfc
        data = wfc.list_workflows(scope="client")
        workflows = (data or {}).get("workflows") or []
        out = []
        for w in workflows:
            if not isinstance(w, dict):
                continue
            item = wfc.normalize_server_workflow(w)
            if not item:
                continue
            if item.get("output_type") == "image":
                out.append(item)
        self.finished.emit(out)


class UploadAndRunWorker(BaseWorker):
    """上传产品图 → 提交工作流 → 轮询结果 → 下载生成图（新版 workflow_client）。"""
    phase = Signal(str)
    progress = Signal(int)
    finished = Signal(list)  # 本地下载的结果文件路径列表

    def __init__(self, server_url, image_path, workflow_id, prompt_text, output_dir):
        super().__init__()
        self.server_url = server_url
        self.image_path = image_path
        self.workflow_id = workflow_id
        self.prompt_text = prompt_text
        self.output_dir = output_dir

    def do_work(self):
        from utils import workflow_client as wfc

        # 1. 准备提交参数
        self.phase.emit("正在提交生成任务…")
        self.progress.emit(10)

        files = {"image": self.image_path}
        values = {"prompt": self.prompt_text}

        # 2. 提交任务
        resp = wfc.run_workflow(
            self.workflow_id,
            files=files,
            values=values,
            timeout=300,
        )
        if not resp or not resp.get("ok"):
            self.error.emit(f"提交失败：{resp.get('error', '未知错误') if resp else '无响应'}")
            return

        task_id = resp.get("task_id")
        if not task_id:
            self.error.emit("提交失败：未返回 task_id")
            return
        log.info(f"[生成图片] 任务已提交 task_id={task_id}")

        # 3. 轮询任务状态
        self.phase.emit("生成中，请稍候…")
        self.progress.emit(30)
        output_urls = []
        for i in range(60):  # 最多等 5 分钟
            time.sleep(5)
            status = wfc.task_status(task_id, timeout=15)
            if not status:
                self.progress.emit(30 + min(i, 25))
                continue
            state = status.get("state", "")
            if state == "error":
                self.error.emit(f"生成失败：{status.get('error', '未知错误')}")
                return
            if state == "completed":
                outputs = status.get("outputs", {})
                output_urls = outputs.get("urls", []) or outputs.get("files", [])
                if not output_urls:
                    # 尝试从 data 中获取
                    data = status.get("data", {})
                    if isinstance(data, dict):
                        output_urls = data.get("urls", []) or data.get("files", [])
                break
            self.progress.emit(30 + min(i + 1, 25))

        if not output_urls:
            self.error.emit("生成超时（5分钟），请稍后查看任务状态。")
            return

        # 4. 下载结果图
        self.phase.emit(f"正在下载 {len(output_urls)} 张结果图…")
        self.progress.emit(80)
        os.makedirs(self.output_dir, exist_ok=True)
        downloaded = []
        for idx, url in enumerate(output_urls):
            try:
                import requests as req
                r = req.get(url, timeout=30)
                if r.status_code == 200:
                    ext = ".png"
                    cd = r.headers.get("Content-Type", "")
                    if "jpeg" in cd or "jpg" in cd:
                        ext = ".jpg"
                    elif "webp" in cd:
                        ext = ".webp"
                    local_path = os.path.join(self.output_dir, f"result_{idx}{ext}")
                    with open(local_path, "wb") as f:
                        f.write(r.content)
                    downloaded.append(local_path)
                else:
                    log.warning(f"[生成图片] 下载 {url} 失败: HTTP {r.status_code}")
            except Exception as e:
                log.warning(f"[生成图片] 下载 {url} 失败: {e}")

        self.progress.emit(100)
        self.phase.emit(f"完成！共 {len(downloaded)} 张图片")
        self.finished.emit(downloaded)


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

        lay.addWidget(QLabel(" 产品选择"))

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
            "QLabel { border: 1px dashed #555; border-radius: 8px; background: rgba(255,255,255,0.03); }")  # noqa: E501
        self.lbl_product_img.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.lbl_product_img)

        # 图片操作按钮
        img_row = QHBoxLayout()
        btn_upload = mdi_button("选择图片", "folder")
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

        lay.addWidget(QLabel(" 生成配置"))

        # 工作流选择
        wf_row = QHBoxLayout()
        wf_row.addWidget(QLabel("工作流:"))
        self.combo_workflow = SearchableComboBox(placeholder="输入工作流名称搜索…")
        self.combo_workflow.currentIndexChanged.connect(self._on_workflow_selected)
        wf_row.addWidget(self.combo_workflow, 1)
        btn_reload_wf = mdi_button("刷新工作流", "refresh")
        btn_reload_wf.setFixedWidth(100)
        btn_reload_wf.setToolTip("刷新工作流列表")
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
        self.btn_generate = QPushButton(" 开始生图")
        self.btn_generate.setObjectName("primary_button")
        self.btn_generate.setMinimumHeight(38)
        self.btn_generate.clicked.connect(self._start_generate)
        gen_row.addWidget(self.btn_generate)
        self.btn_open_output = QPushButton(" 打开输出目录")
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
        self.lbl_status = QLabel("")
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
        self._load_products()
        self._load_workflows()

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
            self.combo_workflow.addItem("（暂无图片生成工作流）")
            return
        for wf in workflows:
            name = wf.get("name", "") if isinstance(wf, dict) else str(wf)
            wf_type = wf.get("type", "") if isinstance(wf, dict) else ""
            display = f"{name} [{wf_type}]" if wf_type and wf_type not in ("其他", "") else name
            self.combo_workflow.addItem(display, wf)

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
        path, _ = pick_file(
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
            self.show_warning("没有可用的图片生成工作流")
            return

        wf_item = self._workflows[wf_idx]
        if not isinstance(wf_item, dict):
            self.show_warning("工作流数据格式错误")
            return

        workflow_id = wf_item.get("id", "")
        if not workflow_id:
            self.show_warning("工作流 ID 为空")
            return

        # 禁用按钮
        self.btn_generate.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("正在提交生成任务…")

        # 输出目录
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(PRODUCT_IMAGE_OUTPUT_DIR, ts)

        # 启动 Worker
        w = UploadAndRunWorker(
            self._server_url, self._selected_image,
            workflow_id, prompt_text, output_dir)
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
        self.lbl_status.setText(f"完成： 生成完成，共 {len(files)} 张图片")
        self._show_results(files)

    def _on_generate_error(self, err):
        self.btn_generate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText("失败： 生成失败")
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
        os.startfile(path)

    def _open_output_dir(self):
        os.makedirs(PRODUCT_IMAGE_OUTPUT_DIR, exist_ok=True)
        os.startfile(PRODUCT_IMAGE_OUTPUT_DIR)
