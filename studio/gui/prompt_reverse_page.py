# -*- coding: utf-8 -*-
"""提示词反推工具页（媒体工具 → 提示词反推）。

两个子页面：
  - 图片反推提示词：拖入/上传图片 → POST /prompt/image → 结构化提示词
  - 视频反推提示词：上传视频 → 时间轴框选(≤30s) → POST /prompt/video（start_sec/end_sec 时间窗）→ 结构化提示词

专用接口（非通用 /llm/chat/completions）：
  POST /prompt/image  multipart: file | material_id → Florence-2 PromptGen + qwen2.5vl
  POST /prompt/video  multipart: file + start_sec/end_sec → 风格/运镜/光线/转场
"""
import os
import json
import glob
import shutil
import subprocess
import tempfile

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QImage, QMouseEvent, QPaintEvent
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QProgressBar, QWidget,
)

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.file_dialog_utils import pick_file
from utils.http_client import http_get, http_post
from utils.logger_utils import log


# ── 工具函数 ──

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff")
VID_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".wmv")


def _get_server_url():
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _probe_duration(path):
    try:
        from utils.video_compiler import _probe_duration as _pd
        return _pd(path)
    except Exception:
        return 0.0


def _find_ffmpeg():
    try:
        from utils.platform_utils import find_ffmpeg
        return find_ffmpeg()
    except Exception:
        return ""


def _extract_frames(video, duration, count=16):
    """从视频中均匀抽取 count 张缩略帧（jpg），返回路径列表；失败返回 []。"""
    ff = _find_ffmpeg()
    if not ff or duration <= 0 or count <= 1:
        return []
    out_dir = os.path.join(tempfile.gettempdir(), "prompt_reverse_frames")
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "frame_*.jpg")):
        try:
            os.remove(old)
        except OSError:
            pass
    pattern = os.path.join(out_dir, "frame_%02d.jpg")
    step = duration / count
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        subprocess.run(
            [ff, "-y", "-i", video, "-vf", f"scale=320:-2,fps=1/{step:.4f}",
             "-frames:v", str(count), "-q:v", "2", pattern],
            capture_output=True, creationflags=flags, timeout=60)
    except Exception:
        return []
    return sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))


def _fmt_sec(s):
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def _format_result(data):
    """将服务端 JSON 响应格式化为可读文本。"""
    parts = []
    desc = data.get("description")
    if desc:
        parts.append(f"【描述】\n{desc}")
    prompt = data.get("prompt")
    if prompt:
        parts.append(f"【正向提示词 Prompt】\n{prompt}")
    neg = data.get("negative_prompt")
    if neg:
        parts.append(f"【反向提示词 Negative Prompt】\n{neg}")
    tags = data.get("style_tags")
    if tags:
        parts.append(f"【风格标签】{', '.join(tags)}")
    ratio = data.get("aspect_ratio")
    if ratio:
        parts.append(f"【画面比例】{ratio}")
    engine = data.get("engine_used") or data.get("model_used")
    if engine:
        parts.append(f"【引擎】{engine}")
    return "\n\n".join(parts) if parts else json.dumps(data, ensure_ascii=False, indent=2)


from gui.common_widgets import DropZone as _DropZone

class _FrameExtractWorker(BaseWorker):
    """后台抽取视频帧缩略图，供时间轴帧预览使用。"""
    finished = Signal(str, list)  # (video_path, frame_paths)

    def __init__(self, video, duration):
        super().__init__()
        self.video = video
        self.duration = duration

    def do_work(self):
        self.finished.emit(self.video, _extract_frames(self.video, self.duration))


# ── 视频波形时间轴 ──

class _VideoTimeline(QWidget):
    """波形风格视频时间轴，支持拖选区间（上限 30 秒）。"""
    range_changed = Signal()
    MAX_WINDOW = 30.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._sel_start = 0.0
        self._sel_end = 0.0
        self._waveform = []
        self._frames = []  # 视频帧缩略图（QImage），非空时优先绘制帧预览
        self._drag = None
        self.setMinimumHeight(90)
        self.setMaximumHeight(90)
        self.setMouseTracking(True)

    def set_video(self, path, duration):
        self._duration = max(0.1, duration)
        win = min(self.MAX_WINDOW, self._duration)
        self._sel_start = 0.0
        self._sel_end = win
        self._frames = []
        self._gen_waveform(path)
        self.update()

    def set_frames(self, paths):
        """设置视频帧缩略图（后台抽帧完成后调用）；空列表时保持波形回退。"""
        self._frames = []
        for p in paths:
            img = QImage(p)
            if not img.isNull():
                self._frames.append(img)
        self.update()

    def _gen_waveform(self, path):
        """从视频提取音量包络作为伪波形；失败时用随机条。"""
        import random
        bars = 120
        try:
            ff = _find_ffmpeg()
            if ff:
                tmp = tempfile.mktemp(suffix=".dat")
                flags = 0x08000000 if os.name == "nt" else 0
                subprocess.run(
                    [ff, "-i", path, "-vn", "-ac", "1",
                     "-filter:a", "aresample=120", "-map", "0:a",
                     "-f", "data", "-codec:a", "pcm_s16le", tmp],
                    capture_output=True, creationflags=flags, timeout=15)
                if os.path.isfile(tmp):
                    with open(tmp, "rb") as f:
                        raw = f.read()
                    os.remove(tmp)
                    n = len(raw) // 2
                    import struct
                    vals = struct.unpack(f"<{n}h", raw[:n * 2]) if n else ()
                    if vals:
                        chunk = max(1, len(vals) // bars)
                        for i in range(bars):
                            seg = vals[i * chunk:(i + 1) * chunk]
                            amp = max(abs(v) for v in seg) / 32768.0 if seg else 0
                            self._waveform.append(min(1.0, amp * 1.8))
                        if len(self._waveform) >= bars // 2:
                            return
        except Exception:
            pass
        self._waveform = [random.uniform(0.12, 0.85) for _ in range(bars)]

    def get_range(self):
        return self._sel_start, self._sel_end

    def _x_to_time(self, x):
        w = self.width() - 20
        if w <= 0:
            return 0.0
        return max(0, min(self._duration, (x - 10) / w * self._duration))

    def _time_to_x(self, t):
        w = self.width() - 20
        return 10 + (t / max(0.1, self._duration)) * w

    def _handle_at(self, x):
        lx = self._time_to_x(self._sel_start)
        rx = self._time_to_x(self._sel_end)
        if abs(x - lx) < 8:
            return "left"
        if abs(x - rx) < 8:
            return "right"
        if lx < x < rx:
            return "move"
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton or self._duration <= 0:
            return
        x = event.position().x()
        h = self._handle_at(x)
        if h:
            self._drag = h
        else:
            t = self._x_to_time(x)
            win = min(self._sel_end - self._sel_start, self.MAX_WINDOW)
            self._sel_start = max(0, min(t, self._duration - win))
            self._sel_end = self._sel_start + win
            self._drag = "move"
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag is None or self._duration <= 0:
            return
        x = event.position().x()
        t = self._x_to_time(x)
        if self._drag == "left":
            new_start = max(0, min(t, self._sel_end - 1.0))
            if self._sel_end - new_start <= self.MAX_WINDOW:
                self._sel_start = new_start
        elif self._drag == "right":
            new_end = max(t, self._sel_start + 1.0)
            new_end = min(self._duration, new_end)
            if new_end - self._sel_start <= self.MAX_WINDOW:
                self._sel_end = new_end
        elif self._drag == "move":
            win = self._sel_end - self._sel_start
            new_start = max(0, min(t - win / 2, self._duration - win))
            self._sel_start = new_start
            self._sel_end = new_start + win
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag = None
        self.range_changed.emit()

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#16161e"))
        if not self._waveform and not self._frames:
            return
        if self._frames:
            self._paint_frames(p)
            return
        inner_x, inner_w = 10, self.width() - 20
        mid_y = self.height() / 2
        max_bar_h = self.height() / 2 - 8
        bar_w = inner_w / len(self._waveform)
        sx = self._time_to_x(self._sel_start)
        ex = self._time_to_x(self._sel_end)
        for i, amp in enumerate(self._waveform):
            bx = inner_x + i * bar_w
            bh = max(2, amp * max_bar_h)
            in_sel = sx <= bx + bar_w / 2 <= ex
            color = QColor("#2ecc71") if in_sel else QColor("#3a3a48")
            p.fillRect(QRectF(bx, mid_y - bh, max(1, bar_w - 1), bh * 2), color)
        p.setPen(QPen(QColor("#2ecc71"), 2))
        p.drawLine(int(sx), 0, int(sx), self.height())
        p.drawLine(int(ex), 0, int(ex), self.height())
        p.setBrush(QColor("#2ecc71"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(sx) - 5, self.height() // 2 - 5, 10, 10)
        p.drawEllipse(int(ex) - 5, self.height() // 2 - 5, 10, 10)
        p.setPen(QColor("#8b90a3"))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(int(sx) + 3, 14, _fmt_sec(self._sel_start))
        p.drawText(int(ex) + 3, 14, _fmt_sec(self._sel_end))
        p.drawText(10, self.height() - 4, "0:00")
        p.drawText(self.width() - 36, self.height() - 4, _fmt_sec(self._duration))

    def _paint_frames(self, p):
        """以视频帧缩略图平铺时间轴：选区内绿色高亮，选区外压暗。"""
        inner_x, inner_w = 10, self.width() - 20
        n = len(self._frames)
        fw = inner_w / n
        fh = self.height() - 34
        y = 17
        for i, img in enumerate(self._frames):
            t0 = i * self._duration / n
            t1 = (i + 1) * self._duration / n
            in_sel = t1 > self._sel_start and t0 < self._sel_end
            rect = QRectF(inner_x + i * fw, y, fw, fh)
            p.fillRect(rect, QColor("#101018"))
            scaled = img.scaled(int(fw), int(fh), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ox = rect.x() + (rect.width() - scaled.width()) / 2
            oy = rect.y() + (rect.height() - scaled.height()) / 2
            p.drawImage(QRectF(ox, oy, scaled.width(), scaled.height()), scaled)
            if in_sel:
                p.fillRect(rect, QColor(46, 204, 113, 36))
            else:
                p.fillRect(rect, QColor(0, 0, 0, 150))
        # 选区边界线 + 拖动手柄 + 时间标注（与波形版一致）
        sx = self._time_to_x(self._sel_start)
        ex = self._time_to_x(self._sel_end)
        p.setPen(QPen(QColor("#2ecc71"), 2))
        p.drawLine(int(sx), 0, int(sx), self.height())
        p.drawLine(int(ex), 0, int(ex), self.height())
        p.setBrush(QColor("#2ecc71"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(sx) - 5, self.height() // 2 - 5, 10, 10)
        p.drawEllipse(int(ex) - 5, self.height() // 2 - 5, 10, 10)
        p.setPen(QColor("#8b90a3"))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        p.drawText(int(sx) + 3, 14, _fmt_sec(self._sel_start))
        p.drawText(int(ex) + 3, 14, _fmt_sec(self._sel_end))
        p.drawText(10, self.height() - 4, "0:00")
        p.drawText(self.width() - 36, self.height() - 4, _fmt_sec(self._duration))


# ── 图片反推 worker（POST /prompt/image multipart）──

class _ImagePromptWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址，请在系统设置中填写统一计算节点地址。")
            return
        try:
            self.phase.emit("正在上传图片并分析…")
            log.info(f"[图片反推] 请求 {base}/prompt/image file={os.path.basename(self.image_path)}")
            with open(self.image_path, "rb") as f:
                resp = http_post(
                    f"{base}/prompt/image",
                    files={"file": (os.path.basename(self.image_path), f)},
                    timeout=180)
            if resp.status_code != 200:
                raise RuntimeError(f"服务端返回 {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            self.finished.emit(_format_result(data))
        except Exception as e:
            log.error(f"[图片反推] 失败: {type(e).__name__}: {e}")
            self.error.emit(str(e))


# ── 视频反推 worker（POST /prompt/video multipart + start_sec/end_sec 时间窗）──

class _VideoPromptWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, video_path, start, end):
        super().__init__()
        self.video = video_path
        self.start = start
        self.end = end

    def do_work(self):
        base = _get_server_url()
        if not base:
            self.error.emit("未配置服务端地址，请在系统设置中填写统一计算节点地址。")
            return
        try:
            self.phase.emit("正在上传视频并分析…")
            # 服务端 /prompt/video 支持 start_sec/end_sec 时间窗，直接传参，无需本地裁切
            # 视觉模型推理耗时较长（30s 窗口实测约 2 分钟），timeout 取 600s 留足余量
            log.info(f"[视频反推] 请求 {base}/prompt/video file={os.path.basename(self.video)} "
                     f"start_sec={self.start:.2f} end_sec={self.end:.2f}")
            with open(self.video, "rb") as f:
                resp = http_post(
                    f"{base}/prompt/video",
                    files={"file": (os.path.basename(self.video), f)},
                    data={"start_sec": f"{self.start:.2f}",
                          "end_sec": f"{self.end:.2f}"},
                    timeout=600)
            if resp.status_code != 200:
                raise RuntimeError(f"服务端返回 {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            self.finished.emit(_format_result(data))
        except Exception as e:
            log.error(f"[视频反推] 失败: {type(e).__name__}: {e}")
            self.error.emit(str(e))


# ── 图片反推提示词页面 ──

class ImagePromptReversePage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._image_path = ""
        self._worker = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(12)

        title = QLabel(" 图片反推提示词")
        title.setObjectName("heading")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(14)

        left = QVBoxLayout()
        self.drop = _DropZone(IMG_EXTS, self.parent_widget)
        self.drop.file_dropped.connect(self._on_image_selected)
        left.addWidget(self.drop)
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(140)
        self.lbl_preview.setStyleSheet(
            "background: #16161e; border-radius: 8px; color: #6b7280;")
        self.lbl_preview.setText("图片预览")
        left.addWidget(self.lbl_preview)
        top.addLayout(left, 1)

        right = QVBoxLayout()
        btn_row = QHBoxLayout()
        self.btn_run = QPushButton(" 反推提示词")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        btn_row.addWidget(self.btn_run)
        self.btn_copy = QPushButton(" 复制")
        self.btn_copy.setObjectName("secondary_button")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_result)
        btn_row.addWidget(self.btn_copy)
        right.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        right.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("muted_text")
        right.addWidget(self.lbl_status)

        self.result = QTextEdit()
        self.result.setPlaceholderText("反推结果将显示在这里…")
        self.result.setReadOnly(True)
        right.addWidget(self.result, 1)
        top.addLayout(right, 2)
        root.addLayout(top, 1)

    def _on_image_selected(self, paths):
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        self._image_path = path
        pm = QPixmap(path)
        if not pm.isNull():
            scaled = pm.scaled(400, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled)
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"已选择: {os.path.basename(path)}")

    def _run(self):
        if not self._image_path or not os.path.isfile(self._image_path):
            return
        self.btn_run.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.result.clear()
        self.lbl_status.setText("处理中…")
        self._worker = self.track_worker(_ImagePromptWorker(self._image_path))
        self._worker.phase.connect(self._on_phase)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_phase(self, msg):
        self.lbl_status.setText(msg)

    def _on_done(self, text):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.result.setPlainText(text)
        self.lbl_status.setText(" 完成")

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"失败： {msg}")

    def _copy_result(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.result.toPlainText())


# ── 视频反推提示词页面 ──

class VideoPromptReversePage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._video_path = ""
        self._duration = 0.0
        self._worker = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(12)

        title = QLabel(" 视频反推提示词")
        title.setObjectName("heading")
        root.addWidget(title)

        self.drop = _DropZone(VID_EXTS, self.parent_widget)
        self.drop.file_dropped.connect(self._on_video_selected)
        self.drop.setMaximumHeight(80)
        root.addWidget(self.drop)

        tl_label = QLabel("拖动把手选择片段（最长 30 秒）")
        tl_label.setObjectName("muted_text")
        root.addWidget(tl_label)
        self.timeline = _VideoTimeline(self.parent_widget)
        root.addWidget(self.timeline)

        self.lbl_range = QLabel("未选择视频")
        self.lbl_range.setObjectName("muted_text")
        root.addWidget(self.lbl_range)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton(" 反推提示词")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        btn_row.addWidget(self.btn_run)
        self.btn_copy = QPushButton(" 复制")
        self.btn_copy.setObjectName("secondary_button")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_result)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        btn_row.addWidget(self.progress)
        root.addLayout(btn_row)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("muted_text")
        root.addWidget(self.lbl_status)

        self.result = QTextEdit()
        self.result.setPlaceholderText("反推结果将显示在这里…")
        self.result.setReadOnly(True)
        root.addWidget(self.result, 1)

        self.timeline.range_changed.connect(self._update_range_label)

    def _on_video_selected(self, paths):
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        self._video_path = path
        self._duration = _probe_duration(path)
        if self._duration <= 0:
            self.lbl_status.setText("注意： 无法读取视频时长")
            return
        self.timeline.set_video(path, self._duration)
        self.btn_run.setEnabled(True)
        self._update_range_label()
        self.lbl_status.setText(
            f"已选择: {os.path.basename(path)} ({_fmt_sec(self._duration)})")
        # 后台抽帧供时间轴帧预览（失败时回退显示波形）
        self._frame_worker = self.track_worker(_FrameExtractWorker(path, self._duration))
        self._frame_worker.finished.connect(self._on_frames_ready)
        self._frame_worker.start()

    def _on_frames_ready(self, video, paths):
        """抽帧完成：仅当仍是当前视频时应用帧预览，避免旧任务覆盖新视频。"""
        if video == self._video_path:
            self.timeline.set_frames(paths)

    def _update_range_label(self):
        s, e = self.timeline.get_range()
        self.lbl_range.setText(
            f"选中区间: {_fmt_sec(s)} – {_fmt_sec(e)}（{e - s:.1f} 秒）")

    def _run(self):
        if not self._video_path or not os.path.isfile(self._video_path):
            return
        s, e = self.timeline.get_range()
        self.btn_run.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.result.clear()
        self.lbl_status.setText("处理中…")
        self._worker = self.track_worker(
            _VideoPromptWorker(self._video_path, s, e))
        self._worker.phase.connect(self._on_phase)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_phase(self, msg):
        self.lbl_status.setText(msg)

    def _on_done(self, text):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.result.setPlainText(text)
        self.lbl_status.setText(" 完成")

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.lbl_status.setText(f"失败： {msg}")

    def _copy_result(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.result.toPlainText())
