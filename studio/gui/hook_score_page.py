# -*- coding: utf-8 -*-
"""
📈 视频评价预测页（由「开头黄金3秒评分」升级而来）。

选择投放平台 → 上传视频 → 抽取覆盖全片的关键帧 → 用视觉大模型按该平台的推荐逻辑
预测这条视频的表现（综合分 + 预测量级 + 多维度评分 + 建议）。
发布后可回填「真实播放量 + 平台评价」，这些「预测 vs 实际」对照会反哺下次预测（在 prompt 里校准）。

依赖：视觉模型（大模型配置里的 llm_vision_*）、自带 ffmpeg。
数据层见 utils/video_prediction_manager.py。
"""
import os
import json
import base64
import shutil
import subprocess
import glob
import math

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
    QFileDialog, QProgressBar, QTextEdit, QScrollArea, QWidget, QGridLayout,
    QComboBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
)
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QPolygonF
from PySide6.QtCore import Signal, Qt, QPointF, QRectF

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.video_compiler import _find, _probe_duration
from utils.video_prediction_manager import (
    VideoPredictionManager, PLATFORMS, DIMENSIONS, PLAY_LEVELS)
from config.paths import TMP_DIR

DIM_COLORS = {
    "吸睛力": "#e74c3c", "画面冲击": "#3498db", "悬念信息": "#f1c40f",
    "节奏": "#9b59b6", "完播预测": "#2ecc71", "平台适配": "#e67e22",
}


def _sample_times(dur):
    """前3秒密集（开头仍重要）+ 覆盖前 20 秒，预测视频表现。"""
    span = min(20.0, dur or 20.0)
    opening = [0.5, 1.5, 2.5]
    rest = []
    if span > 3.2:
        n = 9
        for i in range(n):
            rest.append(round(3.0 + (span - 3.0) * (i + 0.5) / n, 1))
    times = [t for t in (opening + rest) if not dur or t < dur]
    return times or [0.5]


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


class DimScoreCard(QFrame):
    def __init__(self, title, color_hex, parent=None):
        super().__init__(parent)
        self.setObjectName("dim_score_card")
        self.setStyleSheet(f"""
            QFrame {{ border: 2px solid {color_hex}; border-radius: 12px; background-color: #1a1a2a; }}
            QLabel {{ border: none; background-color: transparent; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-size: 12px; color: #a0aec0; font-weight: bold;")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_title)
        self.lbl_score = QLabel("—")
        self.lbl_score.setStyleSheet(f"font-size: 30px; font-weight: bold; color: {color_hex};")
        self.lbl_score.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_score)

    def set_score(self, score):
        self.lbl_score.setText(str(score))


class RadarChartWidget(QWidget):
    """支持任意维度数的雷达图。"""
    def __init__(self, dims=None, parent=None):
        super().__init__(parent)
        self.dims = dims or list(DIMENSIONS)
        self.scores = {d: 0 for d in self.dims}
        # 缩小到约 1/3，避免占用过多空间
        self.setMinimumSize(170, 170)
        self.setMaximumSize(170, 170)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_scores(self, scores):
        self.scores = scores or {}
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r_max = min(w, h) / 2.0 - 30.0
        dims = self.dims
        n = len(dims)
        if n < 3:
            return
        for step in (0.25, 0.5, 0.75, 1.0):
            p.setPen(QPen(QColor("#3a3a4a"), 1, Qt.DashLine))
            poly = QPolygonF()
            for i in range(n):
                a = -math.pi / 2.0 + i * (2.0 * math.pi / n)
                poly.append(QPointF(cx + r_max * step * math.cos(a), cy + r_max * step * math.sin(a)))
            p.drawPolygon(poly)
        p.setPen(QPen(QColor("#4a4a5a"), 1))
        for i in range(n):
            a = -math.pi / 2.0 + i * (2.0 * math.pi / n)
            p.drawLine(QPointF(cx, cy), QPointF(cx + r_max * math.cos(a), cy + r_max * math.sin(a)))
        poly = QPolygonF()
        for i, d in enumerate(dims):
            v = max(0, min(100, self.scores.get(d, 0) or 0))
            a = -math.pi / 2.0 + i * (2.0 * math.pi / n)
            r = r_max * (v / 100.0)
            poly.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        p.setPen(QPen(QColor("#2ecc71"), 2))
        p.setBrush(QBrush(QColor(46, 204, 113, 60)))
        p.drawPolygon(poly)
        p.setFont(QFont("Microsoft YaHei", 7, QFont.Bold))
        for i, d in enumerate(dims):
            v = self.scores.get(d, 0)
            a = -math.pi / 2.0 + i * (2.0 * math.pi / n)
            xl = cx + (r_max + 13.0) * math.cos(a)
            yl = cy + (r_max + 13.0) * math.sin(a)
            p.setPen(QPen(QColor(DIM_COLORS.get(d, "#ffffff"))))
            p.drawText(QRectF(xl - 34.0, yl - 15.0, 68.0, 30.0), Qt.AlignCenter, f"{d}\n{v}")


class HookScoreWorker(BaseWorker):
    phase = Signal(str)
    frames = Signal(list)
    finished = Signal(dict)

    def __init__(self, video, ai_config, platform=None, calibration=""):
        super().__init__()
        self.video = video
        self.cfg = ai_config or {}
        self.platform = platform or "抖音"
        self.calibration = calibration or ""

    def do_work(self):
        import requests
        api_url = self.cfg.get("llm_vision_api_url"); model = self.cfg.get("llm_vision_model")
        api_key = self.cfg.get("llm_vision_api_key") or self.cfg.get("llm_api_key", "")
        if not (api_url and model):
            raise RuntimeError("需要『视觉模型』。请到『大模型配置』填写视觉模型地址与名称。")

        dur = _probe_duration(self.video) or 10.0
        times = _sample_times(dur)
        frames_dir = os.path.join(TMP_DIR, "hook_frames")
        shutil.rmtree(frames_dir, ignore_errors=True)
        os.makedirs(frames_dir, exist_ok=True)
        frames = []
        ffmpeg = _find("ffmpeg.exe")
        flags = 0x08000000 if os.name == "nt" else 0
        for i, t in enumerate(times):
            self.phase.emit(f"抽帧 {i + 1}/{len(times)}（{t}s）…")
            out = os.path.join(frames_dir, f"f{i:02d}_{t}s.jpg")
            subprocess.run([ffmpeg, "-y", "-ss", str(t), "-i", self.video,
                            "-vframes", "1", "-vf", "scale=512:-2", "-q:v", "4", out],
                           capture_output=True, creationflags=flags)
            if os.path.isfile(out):
                frames.append(out)
        if not frames:
            raise RuntimeError("无法从视频抽帧，请确认视频文件有效。")
        self.frames.emit(frames)

        self.phase.emit(f"视觉模型正在按「{self.platform}」预测视频表现…")
        title = os.path.splitext(os.path.basename(self.video))[0]
        calib = (self.calibration + "\n") if self.calibration else ""
        sys_prompt = (
            f"你是短视频运营与投放专家，熟悉各平台推荐机制。下面按时间顺序给出一条【完整视频】"
            f"的若干关键帧（前3秒密集，其余覆盖全片）。目标投放平台：{self.platform}。"
            f"请站在「{self.platform}」的推荐逻辑与用户偏好上，预测这条视频的表现，并多维度打分。\n"
            + calib +
            "严格只输出 JSON：\n"
            '{"total":0-100,"play_level":"爆款|优质|普通|偏弱","golden3s":true/false,'
            '"dims":{"吸睛力":0-100,"画面冲击":0-100,"悬念信息":0-100,"节奏":0-100,'
            '"完播预测":0-100,"平台适配":0-100},'
            '"comment":"一句话总评","suggestions":["建议1","建议2","建议3"]}\n'
            "total=综合预测分；play_level=预测表现量级；完播预测=预计完播表现；"
            "平台适配=与该平台调性/算法的契合度。")
        content = [{"type": "text",
                    "text": f"目标平台：{self.platform}；视频标题：{title}。以下为该视频的关键帧（按时间先后）："}]
        for fr in frames:
            with open(fr, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        payload = {"model": model, "temperature": 0.4,
                   "num_ctx": 32768,  # Ollama: override default 4096 context for vision models
                   "messages": [{"role": "system", "content": sys_prompt},
                                {"role": "user", "content": content}]}
        try:
            res = requests.post(f"{api_url.rstrip('/')}/v1/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {api_key}",
                                         "Content-Type": "application/json"}, timeout=180)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"无法连接视觉模型（{api_url}）：{e}\n请检查『大模型配置』里的视觉模型地址。")
        if res.status_code != 200:
            raise RuntimeError(f"视觉模型请求失败 HTTP {res.status_code}：\n{res.text[:400]}")
        try:
            data = res.json()
        except ValueError:
            raise RuntimeError(f"视觉模型返回的不是 JSON：\n{res.text[:400]}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"视觉模型未返回内容（可能该模型不支持图片输入）：\n{str(data)[:400]}")
        text = (choices[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            raise RuntimeError("视觉模型返回空内容（请确认所选模型支持图片/视觉输入）。")
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
                raise RuntimeError("视觉模型没有按要求输出 JSON，原始返回：\n" + text[:500])
            result = json.loads(m.group())
        self.finished.emit(result)


class HookScorePage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.video = ""
        self.worker = None
        self.manager = VideoPredictionManager()
        self._last_pred = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(12)

        heading = QLabel("📈 视频评价预测")
        heading.setObjectName("heading")
        root.addWidget(heading)
        sub = QLabel("选投放平台 → 上传视频 → 视觉模型按该平台推荐逻辑预测表现（综合分 + 预测量级 + 多维评分）。"
                     "发布后回填真实播放量与平台评价，模型会据此自我校准。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        warning_lbl = QLabel("⚠️ 说明：此为根据大模型预测，实验功能，不一定完全准确。")
        warning_lbl.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        root.addWidget(warning_lbl)

        # 视觉模型状态
        self.model_status_card = QFrame(); self.model_status_card.setObjectName("card")
        self.model_status_card.setStyleSheet("background-color:#1a1a26; border:1px solid #3a3a4a; border-radius:8px;")
        m = QHBoxLayout(self.model_status_card); m.setContentsMargins(16, 10, 16, 10)
        self.lbl_model_info = QLabel("视频大模型：正在加载配置...")
        self.lbl_model_info.setStyleSheet("font-size:13px; font-weight:bold; color:#e0e0e0;")
        m.addWidget(self.lbl_model_info)
        self.lbl_model_status = QLabel("🔴 未检测"); self.lbl_model_status.setStyleSheet("font-weight:bold; color:#a0aec0;")
        m.addWidget(self.lbl_model_status); m.addStretch()
        self.btn_test_model = QPushButton("测试连接"); self.btn_test_model.setObjectName("secondary_button")
        self.btn_test_model.setFixedHeight(30); self.btn_test_model.clicked.connect(self._test_vision_model)
        m.addWidget(self.btn_test_model)
        root.addWidget(self.model_status_card)

        # 输入条：平台 + 视频 + 操作
        bar = QFrame(); bar.setObjectName("card")
        h = QHBoxLayout(bar); h.setContentsMargins(20, 12, 20, 12)
        h.addWidget(QLabel("投放平台"))
        self.cmb_platform = QComboBox(); self.cmb_platform.addItems(PLATFORMS); self.cmb_platform.setFixedWidth(110)
        h.addWidget(self.cmb_platform)
        self.in_video = QLineEdit(); self.in_video.setPlaceholderText("选择要预测的视频…")
        h.addWidget(self.in_video, 1)
        b = QPushButton("浏览…"); b.setObjectName("secondary_button"); b.clicked.connect(self._browse)
        h.addWidget(b)
        self.btn_run = QPushButton("📈 开始预测"); self.btn_run.setObjectName("primary_button")
        self.btn_run.clicked.connect(self._run); h.addWidget(self.btn_run)
        self.pbar = QProgressBar(); self.pbar.setVisible(False); self.pbar.setRange(0, 0); self.pbar.setMaximumWidth(120)
        h.addWidget(self.pbar)
        root.addWidget(bar)

        # 抽帧预览
        self.frames_scroll = QScrollArea(); self.frames_scroll.setWidgetResizable(True)
        self.frames_scroll.setFixedHeight(124); self.frames_scroll.setFrameShape(QScrollArea.NoFrame)
        self.frames_host = QWidget(); self.frames_box = QHBoxLayout(self.frames_host)
        self.frames_box.setContentsMargins(4, 4, 4, 4); self.frames_box.setSpacing(6)
        self.frames_scroll.setWidget(self.frames_host); self.frames_scroll.setVisible(False)
        root.addWidget(self.frames_scroll)

        # 结果区
        self.result_card = QFrame(); self.result_card.setObjectName("card")
        rc = QVBoxLayout(self.result_card); rc.setContentsMargins(24, 20, 24, 20); rc.setSpacing(10)
        top = QHBoxLayout()
        self.lbl_total = QLabel("—"); self.lbl_total.setStyleSheet("font-size:46px; font-weight:bold;")
        top.addWidget(self.lbl_total)
        tv = QVBoxLayout()
        self.lbl_total_cap = QLabel("综合预测分"); self.lbl_total_cap.setObjectName("muted_text"); tv.addWidget(self.lbl_total_cap)
        self.lbl_level = QLabel(""); self.lbl_level.setStyleSheet("font-size:18px; font-weight:bold;"); tv.addWidget(self.lbl_level)
        self.lbl_golden = QLabel(""); tv.addWidget(self.lbl_golden)
        top.addLayout(tv); top.addStretch()
        rc.addLayout(top)

        dims_section = QWidget(); dims_layout = QHBoxLayout(dims_section)
        dims_layout.setContentsMargins(0, 10, 0, 10); dims_layout.setSpacing(20)
        grid = QGridLayout(); grid.setSpacing(10)
        self.dim_cards = {}
        for i, d in enumerate(DIMENSIONS):
            card = DimScoreCard(d, DIM_COLORS.get(d, "#888"))
            self.dim_cards[d] = card
            grid.addWidget(card, i // 3, i % 3)
        dims_layout.addLayout(grid, 1)
        self.radar_chart = RadarChartWidget(DIMENSIONS)
        dims_layout.addWidget(self.radar_chart, 0, Qt.AlignVCenter)
        rc.addWidget(dims_section)

        rc.addWidget(QLabel("总评"))
        self.lbl_comment = QLabel(""); self.lbl_comment.setWordWrap(True); rc.addWidget(self.lbl_comment)
        rc.addWidget(QLabel("改进建议"))
        self.txt_sugg = QTextEdit(); self.txt_sugg.setReadOnly(True); self.txt_sugg.setFixedHeight(110); rc.addWidget(self.txt_sugg)
        self.result_card.setVisible(False)
        root.addWidget(self.result_card)

        # 反馈数据（发布后回填，紧跟在预测结果下方；用于校准下次预测）
        self.feedback_card = QFrame(); self.feedback_card.setObjectName("card")
        fc = QVBoxLayout(self.feedback_card); fc.setContentsMargins(24, 14, 24, 14); fc.setSpacing(8)
        fc.addWidget(QLabel("📊 反馈数据（发布后回填，模型据此校准下次预测）"))
        frow = QHBoxLayout()
        frow.addWidget(QLabel("真实播放量"))
        self.fb_play = QLineEdit(); self.fb_play.setPlaceholderText("如 12.5万 / 8000"); frow.addWidget(self.fb_play, 1)
        frow.addWidget(QLabel("平台评价/标签"))
        self.fb_eval = QLineEdit(); self.fb_eval.setPlaceholderText("如：被推荐 / 限流 / 上热门 / 完播率低"); frow.addWidget(self.fb_eval, 2)
        self.btn_save_fb = QPushButton("保存反馈"); self.btn_save_fb.setObjectName("primary_button")
        self.btn_save_fb.clicked.connect(self._save_feedback); frow.addWidget(self.btn_save_fb)
        fc.addLayout(frow)
        self.fb_status = QLabel(""); self.fb_status.setObjectName("muted_text"); fc.addWidget(self.fb_status)
        self.feedback_card.setVisible(False)
        root.addWidget(self.feedback_card)

        self.status = QLabel("就绪"); self.status.setObjectName("muted_text"); root.addWidget(self.status)
        root.addStretch()
        self.update_vision_model_display()

    # ---------- 视觉模型 ----------
    def update_vision_model_display(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        url = ai.get("llm_vision_api_url", ""); model = ai.get("llm_vision_model", "")
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
        url = ai.get("llm_vision_api_url", ""); key = ai.get("llm_vision_api_key") or ai.get("llm_api_key", "")
        model = ai.get("llm_vision_model", "")
        if not url or not model:
            return
        self.btn_test_model.setEnabled(False)
        self.lbl_model_status.setText("🟡 正在测试..."); self.lbl_model_status.setStyleSheet("font-weight:bold; color:#f1c40f;")
        self.test_worker = VisionModelTestWorker(url, key, model)

        def on_finished(success, message):
            self.btn_test_model.setEnabled(True)
            self.lbl_model_status.setText(message)
            self.lbl_model_status.setStyleSheet(f"font-weight:bold; color:{'#2ecc71' if success else '#e74c3c'};")
        self.test_worker.finished.connect(on_finished); self.test_worker.start()

    # ---------- 预测 ----------
    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择视频", "",
                                           "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.flv)")
        if f:
            self.in_video.setText(f)

    def _run(self):
        video = self.in_video.text().strip()
        if not video or not os.path.isfile(video):
            self.show_warning("请先选择有效的视频文件。")
            return
        platform = self.cmb_platform.currentText()
        calib = self.manager.calibration_text(platform=platform)
        self.btn_run.setEnabled(False); self.pbar.setVisible(True); self.status.setText("预测中…")
        self.worker = HookScoreWorker(video, self.ai_config, platform=platform, calibration=calib)
        self.worker.phase.connect(self.status.setText)
        self.worker.frames.connect(self._show_frames)
        self.worker.finished.connect(self._done)
        self.worker.error.connect(self._err)
        self.track_worker(self.worker); self.worker.start()

    def _show_frames(self, paths):
        while self.frames_box.count():
            it = self.frames_box.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        for p in paths:
            lbl = QLabel(); pm = QPixmap(p)
            if not pm.isNull():
                lbl.setPixmap(pm.scaledToHeight(104, Qt.SmoothTransformation))
            lbl.setToolTip(os.path.basename(p)); self.frames_box.addWidget(lbl)
        self.frames_box.addStretch(); self.frames_scroll.setVisible(True)

    def show_result(self, video, data):
        """供「一键成片」自检后跳转复用。"""
        self.in_video.setText(video or "")
        fs = sorted(glob.glob(os.path.join(TMP_DIR, "hook_frames", "*.jpg")))
        if fs:
            self._show_frames(fs)
        if data:
            self._render(data)
        self.status.setText("（来自一键成片的自检结果，可重新预测）")

    def _done(self, data):
        self.btn_run.setEnabled(True); self.pbar.setVisible(False); self.status.setText("预测完成。")
        self._render(data)
        # 持久化预测，记下 id 供下方「反馈数据」回填 + 校准
        self._last_pred_id = None
        try:
            self._last_pred_id = self.manager.add_prediction(
                self.in_video.text().strip(), self.cmb_platform.currentText(), data)
        except Exception:
            pass
        self.fb_play.clear(); self.fb_eval.clear(); self.fb_status.setText("")
        self.feedback_card.setVisible(bool(self._last_pred_id))

    def _render(self, data):
        total = data.get("total", "—")
        self.lbl_total.setText(str(total))
        color = "#2ecc71" if isinstance(total, (int, float)) and total >= 80 else \
                "#f1c40f" if isinstance(total, (int, float)) and total >= 60 else "#e74c3c"
        self.lbl_total.setStyleSheet(f"font-size:46px; font-weight:bold; color:{color};")
        level = data.get("play_level", "")
        lv_color = {"爆款": "#2ecc71", "优质": "#3498db", "普通": "#f1c40f", "偏弱": "#e74c3c"}.get(level, "#a0aec0")
        self.lbl_level.setText(f"预测表现：{level}" if level else "")
        self.lbl_level.setStyleSheet(f"font-size:18px; font-weight:bold; color:{lv_color};")
        g = data.get("golden3s")
        self.lbl_golden.setText("✅ 前3秒合格" if g else "⚠️ 前3秒待加强")
        dims = data.get("dims", {}) or {}
        for d, card in self.dim_cards.items():
            card.set_score(dims.get(d, "—"))
        self.radar_chart.set_scores(dims)
        self.lbl_comment.setText(str(data.get("comment", "")))
        sugg = data.get("suggestions", []) or []
        self.txt_sugg.setPlainText("\n".join(f"• {s}" for s in sugg) if isinstance(sugg, list) else str(sugg))
        self.result_card.setVisible(True)

    def _err(self, e):
        self.btn_run.setEnabled(True); self.pbar.setVisible(False); self.status.setText("预测失败。")
        self.show_error(str(e), "视频预测失败")

    # ---------- 反馈数据（内联，紧跟预测结果下方）----------
    def _save_feedback(self):
        pid = getattr(self, "_last_pred_id", None)
        if not pid:
            self.fb_status.setText("请先做一次「开始预测」。")
            return
        play = self.fb_play.text().strip()
        if not play:
            self.fb_status.setText("请填写真实播放量。")
            return
        ok = self.manager.set_feedback(pid, play, self.fb_eval.text())
        self.fb_status.setText("✅ 已保存，将用于该平台下次预测校准。" if ok else "保存失败。")
