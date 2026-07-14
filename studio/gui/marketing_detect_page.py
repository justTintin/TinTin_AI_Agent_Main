# -*- coding: utf-8 -*-
"""
📢 视频营销检测页。

通过对视频进行关键帧提取，使用配置的视觉大模型对关键帧内容进行综合研判，
判断该视频是否为营销/广告视频，并分析推广的品类、提取营销特征线索，提供相关的改进建议。
"""
import os
import json
import base64
import shutil
import subprocess
import glob

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
    QFileDialog, QProgressBar, QTextEdit, QScrollArea, QWidget, QGridLayout,
)
from PySide6.QtGui import QPixmap, QColor, QFont
from PySide6.QtCore import Signal, Qt

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.video_compiler import _find, _probe_duration
from config.paths import TMP_DIR


def _sample_times(dur):
    """根据视频时长均匀抽取 6-10 个关键帧，以覆盖视频全片"""
    if dur <= 0:
        return [0.5]
    n = min(10, max(5, int(dur / 3.0)))
    times = []
    if dur <= 2.0:
        return [dur / 2.0]
    for i in range(n):
        times.append(round(dur * (i + 0.5) / n, 1))
    return times


class VisionModelTestWorker(BaseWorker):
    finished = Signal(bool, str)

    def __init__(self, api_url, api_key, model):
        super().__init__()
        self.api_url, self.api_key, self.model = api_url, api_key, model

    def do_work(self):
        import requests
        url = f"{self.api_url.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=8)
            self.finished.emit(res.status_code == 200,
                               "🟢 连接成功" if res.status_code == 200 else f"❌ 失败 (HTTP {res.status_code})")
        except Exception:
            self.finished.emit(False, "❌ 无法连接")


class MarketingDetectWorker(BaseWorker):
    phase = Signal(str)
    frames = Signal(list)
    finished = Signal(dict)

    def __init__(self, video, ai_config):
        super().__init__()
        self.video = video
        self.cfg = ai_config or {}

    def do_work(self):
        import requests
        api_url = self.cfg.get("llm_vision_api_url")
        model = self.cfg.get("llm_vision_model")
        api_key = self.cfg.get("llm_vision_api_key") or self.cfg.get("llm_api_key", "")
        if not (api_url and model):
            raise RuntimeError("需要『视觉模型』。请至『系统配置 / 大模型配置』填写视觉模型相关配置。")

        # 1. 探测时长并抽帧
        self.phase.emit("正在解析视频时长…")
        dur = _probe_duration(self.video) or 10.0
        times = _sample_times(dur)
        
        frames_dir = os.path.join(TMP_DIR, "marketing_frames")
        shutil.rmtree(frames_dir, ignore_errors=True)
        os.makedirs(frames_dir, exist_ok=True)
        
        frames = []
        ffmpeg = _find("ffmpeg.exe")
        flags = 0x08000000 if os.name == "nt" else 0
        
        for i, t in enumerate(times):
            self.phase.emit(f"正在提取关键帧 {i + 1}/{len(times)}（{t}s）…")
            out = os.path.join(frames_dir, f"f{i:02d}_{t}s.jpg")
            subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", self.video,
                            "-vframes", "1", "-vf", "scale=512:-2", "-q:v", "4", out],
                           capture_output=True, creationflags=flags)
            if os.path.isfile(out):
                frames.append(out)
                
        if not frames:
            raise RuntimeError("视频关键帧提取失败，请检查视频文件是否损坏。")
            
        self.frames.emit(frames)

        # 2. 调用视觉大模型进行研判
        self.phase.emit("视觉大模型正在研判视频属性中…")
        title = os.path.splitext(os.path.basename(self.video))[0]
        
        sys_prompt = (
            "你是专业的视频分析和营销内容审查专家。请仔细查看以下按时间顺序排列的视频关键帧（包含视频画面和字幕文字等信息）。\n"
            "你的任务是判断这个视频是否属于【营销/广告宣传/带货/商业推广/引流】类视频。\n"
            "请严格只输出符合以下格式的 JSON，不要包含任何 Markdown 标记或多余字符，确保能够被 json.loads() 解析：\n"
            "{\n"
            '  "is_marketing": true 或 false,\n'
            '  "confidence": 0 到 100 之间的置信度数值,\n'
            '  "category": "直销带货"、"品牌广告"、"软广植入"、"知识付费/教育推广"、"非营销/纯内容"、"其他（请注明）" 之一,\n'
            '  "product_or_brand": "推广的产品/品牌名称，如果没有则为空字符串",\n'
            '  "clues": ["证据1", "证据2", ...（列出视觉画面或文字中体现营销意图的线索）],\n'
            '  "analysis": "对视频营销特征的简明分析说明（不超过150字）",\n'
            '  "suggestions": ["优化或改进建议1", "优化或改进建议2", ...（如何提高营销吸引力、或若非营销视频如何保持内容纯粹性、商业合规等）]\n'
            "}"
        )
        
        content = [{"type": "text", "text": f"视频名称：{title}。以下为按时间先后抽取的关键帧："}]
        for fr in frames:
            with open(fr, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            
        payload = {
            "model": model,
            "temperature": 0.3,
            "num_ctx": 32768,  # Ollama: override default 4096 context for vision models
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": content}
            ]
        }
        
        try:
            res = requests.post(
                f"{api_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                timeout=180
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"无法连接视觉大模型接口（{api_url}）：{e}\n请检查“大模型配置”中的配置信息。")
            
        if res.status_code != 200:
            raise RuntimeError(f"视觉大模型请求失败 (HTTP {res.status_code})：\n{res.text[:400]}")
            
        try:
            data = res.json()
        except ValueError:
            raise RuntimeError(f"视觉大模型返回的数据不是 JSON 格式：\n{res.text[:400]}")
            
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"大模型响应中没有返回文本结果，请确认模型是否支持图片输入。详情：\n{str(data)[:400]}")
            
        text = (choices[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            raise RuntimeError("大模型返回空响应。")
            
        body = text
        if body.startswith("```"):
            body = body.strip("`")
            if body.lower().startswith("json"):
                body = body[4:]
            body = body.strip()
            
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            import re
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                raise RuntimeError("大模型没有输出有效的 JSON 对象，原始返回为：\n" + text[:500])
            result = json.loads(m.group())
            
        self.finished.emit(result)


class MarketingDetectPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.video = ""
        self.worker = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(12)

        # 1. 标题与说明
        heading = QLabel("📢 视频营销检测")
        heading.setObjectName("heading")
        root.addWidget(heading)
        
        sub = QLabel("提取视频关键帧 → 通过视觉大模型多维分析视频内容、字幕、场景，研判是否为广告推广/带货引流视频。")
        sub.setObjectName("muted_text")
        sub.setWordWrap(True)
        root.addWidget(sub)

        warning_lbl = QLabel("⚠️ 说明：此为根据大模型预测，实验功能，不一定完全准确。")
        warning_lbl.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        root.addWidget(warning_lbl)

        # 2. 视觉模型状态卡片
        self.model_status_card = QFrame()
        self.model_status_card.setObjectName("card")
        self.model_status_card.setStyleSheet("background-color:#1a1a26; border:1px solid #3a3a4a; border-radius:8px;")
        m_layout = QHBoxLayout(self.model_status_card)
        m_layout.setContentsMargins(16, 10, 16, 10)
        
        self.lbl_model_info = QLabel("视频大模型：正在加载配置...")
        self.lbl_model_info.setStyleSheet("font-size:13px; font-weight:bold; color:#e0e0e0;")
        m_layout.addWidget(self.lbl_model_info)
        
        self.lbl_model_status = QLabel("🔴 未检测")
        self.lbl_model_status.setStyleSheet("font-weight:bold; color:#a0aec0;")
        m_layout.addWidget(self.lbl_model_status)
        m_layout.addStretch()
        
        self.btn_test_model = QPushButton("测试连接")
        self.btn_test_model.setObjectName("secondary_button")
        self.btn_test_model.setFixedHeight(30)
        self.btn_test_model.clicked.connect(self._test_vision_model)
        m_layout.addWidget(self.btn_test_model)
        root.addWidget(self.model_status_card)

        # 3. 输入栏：选择视频与运行
        bar = QFrame()
        bar.setObjectName("card")
        h_layout = QHBoxLayout(bar)
        h_layout.setContentsMargins(20, 12, 20, 12)
        
        h_layout.addWidget(QLabel("选择视频："))
        self.in_video = QLineEdit()
        self.in_video.setPlaceholderText("请选择或拖入视频文件路径…")
        h_layout.addWidget(self.in_video, 1)
        
        btn_browse = QPushButton("浏览…")
        btn_browse.setObjectName("secondary_button")
        btn_browse.clicked.connect(self._browse)
        h_layout.addWidget(btn_browse)
        
        self.btn_run = QPushButton("📢 开始检测")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.clicked.connect(self._run)
        h_layout.addWidget(self.btn_run)
        
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setRange(0, 0)
        self.pbar.setMaximumWidth(120)
        h_layout.addWidget(self.pbar)
        root.addWidget(bar)

        # 4. 关键帧提取预览区
        self.frames_scroll = QScrollArea()
        self.frames_scroll.setWidgetResizable(True)
        self.frames_scroll.setFixedHeight(124)
        self.frames_scroll.setFrameShape(QScrollArea.NoFrame)
        self.frames_host = QWidget()
        self.frames_box = QHBoxLayout(self.frames_host)
        self.frames_box.setContentsMargins(4, 4, 4, 4)
        self.frames_box.setSpacing(6)
        self.frames_scroll.setWidget(self.frames_host)
        self.frames_scroll.setVisible(False)
        root.addWidget(self.frames_scroll)

        # 5. 检测结果展示卡片
        self.result_card = QFrame()
        self.result_card.setObjectName("card")
        rc_layout = QVBoxLayout(self.result_card)
        rc_layout.setContentsMargins(24, 20, 24, 20)
        rc_layout.setSpacing(12)

        # 顶部结论
        top_layout = QHBoxLayout()
        self.lbl_verdict = QLabel("—")
        self.lbl_verdict.setStyleSheet("font-size:24px; font-weight:bold;")
        top_layout.addWidget(self.lbl_verdict)
        
        self.lbl_confidence = QLabel("")
        self.lbl_confidence.setStyleSheet("font-size:16px; font-weight:bold; color:#a0aec0;")
        top_layout.addWidget(self.lbl_confidence)
        top_layout.addStretch()
        rc_layout.addLayout(top_layout)

        # 属性网格
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(QLabel("📂 推广分类："), 0, 0)
        self.lbl_category = QLabel("—")
        self.lbl_category.setStyleSheet("font-weight:bold; color:#ffffff;")
        grid.addWidget(self.lbl_category, 0, 1)

        grid.addWidget(QLabel("🏷️ 涉及品牌/商品："), 0, 2)
        self.lbl_product = QLabel("—")
        self.lbl_product.setStyleSheet("font-weight:bold; color:#ffffff;")
        grid.addWidget(self.lbl_product, 0, 3)
        rc_layout.addLayout(grid)

        # 营销线索
        rc_layout.addWidget(QLabel("🔍 提取到的营销线索："))
        self.txt_clues = QTextEdit()
        self.txt_clues.setReadOnly(True)
        self.txt_clues.setFixedHeight(70)
        rc_layout.addWidget(self.txt_clues)

        # 详细研判分析
        rc_layout.addWidget(QLabel("📝 详细研判分析："))
        self.txt_analysis = QTextEdit()
        self.txt_analysis.setReadOnly(True)
        self.txt_analysis.setFixedHeight(90)
        rc_layout.addWidget(self.txt_analysis)

        # 优化/合规建议
        rc_layout.addWidget(QLabel("💡 优化与改进建议："))
        self.txt_suggestions = QTextEdit()
        self.txt_suggestions.setReadOnly(True)
        self.txt_suggestions.setFixedHeight(90)
        rc_layout.addWidget(self.txt_suggestions)

        self.result_card.setVisible(False)
        root.addWidget(self.result_card)

        # 底部状态栏
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("muted_text")
        root.addWidget(self.lbl_status)
        root.addStretch()

        self.update_vision_model_display()

    def update_vision_model_display(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        url = ai.get("llm_vision_api_url", "")
        model = ai.get("llm_vision_model", "")
        if url and model:
            self.lbl_model_info.setText(f"视频大模型：{model} ({url})")
            self.lbl_model_status.setText("🟢 已配置")
            self.lbl_model_status.setStyleSheet("font-weight:bold; color:#2ecc71;")
            self.btn_test_model.setEnabled(True)
        else:
            self.lbl_model_info.setText("视频大模型：未配置（请先在“AI设置 / 大模型配置”中填写视觉模型）")
            self.lbl_model_status.setText("🔴 未配置")
            self.lbl_model_status.setStyleSheet("font-weight:bold; color:#e74c3c;")
            self.btn_test_model.setEnabled(False)

    def _test_vision_model(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        url = ai.get("llm_vision_api_url", "")
        key = ai.get("llm_vision_api_key") or ai.get("llm_api_key", "")
        model = ai.get("llm_vision_model", "")
        if not url or not model:
            return
        self.btn_test_model.setEnabled(False)
        self.lbl_model_status.setText("🟡 正在测试...")
        self.lbl_model_status.setStyleSheet("font-weight:bold; color:#f1c40f;")
        
        self.test_worker = VisionModelTestWorker(url, key, model)

        def on_finished(success, message):
            self.btn_test_model.setEnabled(True)
            self.lbl_model_status.setText(message)
            self.lbl_model_status.setStyleSheet(f"font-weight:bold; color:{'#2ecc71' if success else '#e74c3c'};")
            
        self.test_worker.finished.connect(on_finished)
        self.test_worker.start()

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择视频", "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.flv)"
        )
        if f:
            self.in_video.setText(f)

    def _run(self):
        video = self.in_video.text().strip()
        if not video or not os.path.isfile(video):
            self.show_warning("请选择有效的视频文件。")
            return
            
        self.btn_run.setEnabled(False)
        self.pbar.setVisible(True)
        self.lbl_status.setText("检测中…")
        
        self.worker = MarketingDetectWorker(video, self.ai_config)
        self.worker.phase.connect(self.lbl_status.setText)
        self.worker.frames.connect(self._show_frames)
        self.worker.finished.connect(self._done)
        self.worker.error.connect(self._err)
        
        self.track_worker(self.worker)
        self.worker.start()

    def _show_frames(self, paths):
        while self.frames_box.count():
            it = self.frames_box.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        for p in paths:
            lbl = QLabel()
            pm = QPixmap(p)
            if not pm.isNull():
                lbl.setPixmap(pm.scaledToHeight(104, Qt.SmoothTransformation))
            lbl.setToolTip(os.path.basename(p))
            self.frames_box.addWidget(lbl)
        self.frames_box.addStretch()
        self.frames_scroll.setVisible(True)

    def _done(self, data):
        self.btn_run.setEnabled(True)
        self.pbar.setVisible(False)
        self.lbl_status.setText("检测完成。")
        self._render(data)

    def _render(self, data):
        is_m = data.get("is_marketing", False)
        conf = data.get("confidence", 0)
        
        if is_m:
            self.lbl_verdict.setText("⚠️ 检测结论：营销/商业推广视频")
            self.lbl_verdict.setStyleSheet("font-size:20px; font-weight:bold; color:#e74c3c;")
        else:
            self.lbl_verdict.setText("✅ 检测结论：原创内容/非营销视频")
            self.lbl_verdict.setStyleSheet("font-size:20px; font-weight:bold; color:#2ecc71;")
            
        self.lbl_confidence.setText(f"（置信度: {conf}%）")
        self.lbl_category.setText(str(data.get("category", "—")))
        
        prod = data.get("product_or_brand")
        self.lbl_product.setText(str(prod) if prod else "无")
        
        clues = data.get("clues", [])
        self.txt_clues.setPlainText(
            "\n".join(f"• {c}" for c in clues) if isinstance(clues, list) else str(clues)
        )
        
        self.txt_analysis.setPlainText(str(data.get("analysis", "")))
        
        sugg = data.get("suggestions", [])
        self.txt_suggestions.setPlainText(
            "\n".join(f"• {s}" for s in sugg) if isinstance(sugg, list) else str(sugg)
        )
        
        self.result_card.setVisible(True)

    def _err(self, e):
        self.btn_run.setEnabled(True)
        self.pbar.setVisible(False)
        self.lbl_status.setText("检测失败。")
        self.show_error(str(e), "视频营销检测失败")
