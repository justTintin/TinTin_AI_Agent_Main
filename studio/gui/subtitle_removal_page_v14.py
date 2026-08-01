# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import traceback
import time
import math
import av
from PIL import Image, ImageDraw

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QSlider, QSplitter, QWidget, QTextEdit, QSizePolicy, QListWidget)
from PySide6.QtCore import Signal, QThread, Qt, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon, QCursor, QPainter, QPen, QBrush, QColor, QPolygonF
from utils.logger_utils import log
from config.paths import TMP_DIR


# ═══════════════════════════════════════════════════════════════
# 四边形选区辅助函数（选区统一用四点四边形表示：[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]，视频原始帧像素）
# ═══════════════════════════════════════════════════════════════

def _quad_aabb(quad):
    """四点四边形 → 轴对齐外接框 (x, y, w, h)。本地 CLI 只支持矩形，用 AABB 退化。"""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return [x0, y0, x1 - x0, y1 - y0]


def _rect_to_quad(x, y, w, h):
    """矩形 [x,y,w,h] → 顺时针四点四边形（左上→右上→右下→左下）。"""
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _quad_to_relative_polygon(quad, fw, fh):
    """四点像素 → 相对坐标四点 [[x_rel,y_rel],...]（服务端 polygon 格式）。"""
    return [[round(p[0] / fw, 4), round(p[1] / fh, 4)] for p in quad]


class _ProgressFileReader:
    """包装文件对象，读取时回调上传进度。"""
    def __init__(self, f, total, cb):
        self._f = f
        self._total = total
        self._cb = cb
        self._read = 0

    def read(self, size=-1):
        data = self._f.read(size)
        self._read += len(data)
        if self._cb:
            self._cb(self._read, self._total)
        return data

    def __getattr__(self, name):
        return getattr(self._f, name)


class RemoteVSRWorkerV14(QThread):
    """服务端去字幕 worker：上传视频 + 全部选区 sub_areas → 轮询任务 → 下载结果。"""

    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, video_path, sub_areas, inpaint_mode, output_path, purpose="subtitle", watermark_text=""):
        """
        :param sub_areas: 服务端 sub_areas JSON 字符串。空串=""智能识别（服务端自动检测）；
                          标注选区为四边形相对坐标 [[[x_rel,y_rel]×4], ...]
        :param inpaint_mode: 服务端算法名 sttn_det/sttn_auto/lama/propainter（具体模型由服务端匹配）
        :param output_path: 结果下载后的本地保存路径
        :param purpose: 用途 "subtitle"(去字幕) / "watermark"(去水印)
        :param watermark_text: 要去除的水印文字内容（供服务端精准定位水印，空=按选区/自动识别）
        """
        super().__init__()
        self.video_path = video_path
        self.sub_areas = sub_areas
        self.inpaint_mode = inpaint_mode
        self.output_path = output_path
        self.purpose = purpose
        self.watermark_text = watermark_text
        self.is_aborted = False
        self._task_id = ""
        self._base_url = ""

    def stop(self):
        self.is_aborted = True
        # 尽力取消服务端任务
        if self._task_id and self._base_url:
            import threading
            def _cancel():
                try:
                    from utils.http_client import http_delete
                    http_delete(f"{self._base_url}/tasks/{self._task_id}", timeout=5)
                except Exception:
                    pass
            threading.Thread(target=_cancel, daemon=True).start()

    def run(self):
        import json as _json
        import time as _time
        import requests
        from utils.http_client import http_get, http_post

        try:
            from config.paths import AI_CONFIG_FILE
            base_url = ""
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    base_url = (_json.load(f).get("compute_server_url") or "").strip().rstrip("/")
            if not base_url:
                self.finished.emit(False, "未配置服务端地址，请先在「系统设置 → 模型配置」中设置 compute_server_url。")
                return
            self._base_url = base_url

            is_smart = not self.sub_areas
            self.status_updated.emit("准备上传视频到服务端...")
            self.progress_updated.emit(0)
            self.log_received.emit(f"[INFO] 连接服务端: {base_url}")
            desc = "智能去除（服务端自动检测）" if is_smart else f"选区去除 {self.sub_areas[:60]}"
            self.log_received.emit(f"[INFO] 提交服务端去字幕: {base_url}/vsr/remove  mode={self.inpaint_mode}  {desc}")

            # 上传进度 0-10%（真实字节追踪）
            file_size = os.path.getsize(self.video_path)
            _upload_pct = [0]
            def _on_upload(read, total):
                pct = min(10, int(read * 10 / max(total, 1)))
                if pct != _upload_pct[0]:
                    _upload_pct[0] = pct
                    self.progress_updated.emit(pct)

            with open(self.video_path, "rb") as raw_f:
                tracked_f = _ProgressFileReader(raw_f, file_size, _on_upload)
                files = {"file": (os.path.basename(self.video_path), tracked_f, "video/mp4")}
                data = {
                    "inpaint_mode": self.inpaint_mode,
                    "sub_areas": self.sub_areas,
                    "purpose": self.purpose,
                    "watermark_text": self.watermark_text,
                }
                r = http_post(f"{base_url}/vsr/remove", files=files, data=data, timeout=1800)
            if r.status_code != 200:
                self.finished.emit(False, f"服务端返回 {r.status_code}: {r.text[:300]}")
                return
            result = r.json()
            task_id = result.get("task_id", "")
            if not task_id:
                self.finished.emit(False, f"服务端未返回任务 ID: {str(result)[:300]}")
                return
            self._task_id = task_id
            self.log_received.emit(f"[INFO] task_id={task_id}，开始轮询任务状态...")
            self.status_updated.emit("服务端处理中...")
            self.progress_updated.emit(10)

            poll_url = f"{base_url}/tasks/unified/{task_id}"
            poll_start = _time.time()
            deadline = _time.time() + 3600  # 长视频去字幕耗时久，最多等待 60 分钟
            _last_heartbeat = 0
            while _time.time() < deadline:
                if self.is_aborted:
                    self.finished.emit(False, "用户终止运行。")
                    return
                _time.sleep(3)
                try:
                    pr = http_get(poll_url, timeout=15)
                except Exception:
                    continue
                if pr.status_code != 200:
                    continue
                pdata = pr.json()
                status = str(pdata.get("status") or "").lower()
                # 服务端回报进度 → 映射到 10~95（下载阶段用 95-100）
                try:
                    prog = pdata.get("progress")
                    if prog is not None:
                        pct = float(prog)
                        if pct <= 1.0:
                            pct *= 100
                        mapped = max(10, min(95, int(10 + pct * 0.85)))
                        self.progress_updated.emit(mapped)
                        self.log_received.emit(f"[进度] 服务端 {pct:.0f}% → 客户端 {mapped}%")
                    else:
                        # 服务端没返回进度时，每 10 秒打印一次心跳日志，避免界面像卡住
                        elapsed = int(_time.time() - poll_start)
                        if elapsed - _last_heartbeat >= 10:
                            _last_heartbeat = elapsed
                            self.log_received.emit(f"[等待] 服务端处理中，已等待 {elapsed} 秒...")
                except Exception:
                    pass
                if status in ("completed", "done", "success"):
                    # 优先用服务端返回的 download_url，其次从 filename 拼装
                    dl_url = pdata.get("download_url") or pdata.get("result", {}).get("download_url") or ""
                    if dl_url:
                        if dl_url.startswith("/"):
                            dl_url = base_url + dl_url
                        elif not dl_url.startswith("http"):
                            dl_url = f"{base_url}/{dl_url}"
                        self._download(dl_url)
                    else:
                        filename = (pdata.get("filename") or pdata.get("output")
                                    or pdata.get("result", {}).get("filename") or "")
                        if not filename:
                            filename = f"{task_id}.mp4"
                        self._download(f"{base_url}/vsr/download/{filename}")
                    return
                if status in ("failed", "error"):
                    err = pdata.get("error") or pdata.get("message") or "未知错误"
                    self.finished.emit(False, f"去字幕任务失败(task_id={task_id}): {err}")
                    return
            self.finished.emit(False, f"去字幕任务超时(3600s), task_id={task_id}")
        except Exception as e:
            self.finished.emit(False, f"服务端去字幕异常: {e}")

    def _download(self, dl_url):
        from utils.http_client import http_get
        self.status_updated.emit("正在下载处理结果...")
        self.progress_updated.emit(95)
        self.log_received.emit(f"[INFO] 下载结果: {dl_url}")
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with http_get(dl_url, stream=True, timeout=600) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(self.output_path, "wb") as f:
                for chunk in r.iter_content(1024 * 512):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            mapped = 95 + int(downloaded * 5 / total)
                            self.progress_updated.emit(min(99, mapped))
        self.progress_updated.emit(100)
        self.finished.emit(True, self.output_path)


class InteractivePreviewLabelV14(QLabel):
    boundsChanged = Signal(int)  # index — 选区四点变化，页面读 self.boxes[idx]
    selectionChanged = Signal(int)  # active_index
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #0b1220; border-radius: 8px; border: 1px solid #2e2e32;")
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self.boxes = []  # 每个元素是四点四边形 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]（视频原始帧像素，顺时针）
        self.active_box_index = -1

        self.frame_w = 0
        self.frame_h = 0

        self.target_w = 0
        self.target_h = 0
        self.px_offset_x = 0
        self.px_offset_y = 0

        self.drag_mode = None      # None | 'move' | 'vertex-N' (N=0..3) | 'rotate' | 'draw'
        self.drag_start_pos = None
        self.drag_start_quad = None  # 拖动起始时的四点副本（帧坐标）
        self.draw_start = None       # 新画矩形起始点（widget 坐标）
        self.rotate_center = None    # 旋转中心（帧坐标）
        self.rotate_start_angle = 0.0  # 按下旋转把手时的起始角度
        self._rotate_cursor_cache = None

    def sizeHint(self):
        return QSize(400, 300)

    def set_boxes(self, boxes, active_index):
        self.boxes = boxes
        self.active_box_index = active_index

    def _widget_to_frame(self, pos):
        """widget 像素坐标 → 视频原始帧像素坐标。"""
        if self.target_w <= 0 or self.target_h <= 0:
            return None
        fx = (pos.x() - self.px_offset_x) * self.frame_w / self.target_w
        fy = (pos.y() - self.px_offset_y) * self.frame_h / self.target_h
        return (int(fx), int(fy))

    def _point_in_quad(self, px, py, quad):
        """点是否在四边形内（射线法）。"""
        n = len(quad)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = quad[i]
            xj, yj = quad[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def _rotation_vertex_index(self):
        """返回视觉'右下角'的顶点下标（x+y 最大的角），用作旋转把手。"""
        if self.active_box_index < 0 or not self.boxes:
            return -1
        quad = self.boxes[self.active_box_index]
        if not quad:
            return -1
        best = 0
        best_sum = quad[0][0] + quad[0][1]
        for i in range(1, len(quad)):
            s = quad[i][0] + quad[i][1]
            if s > best_sum:
                best, best_sum = i, s
        return best

    def _rotate_cursor(self):
        """旋转把手光标（懒加载缓存）。"""
        if self._rotate_cursor_cache is None:
            self._rotate_cursor_cache = self._make_rotate_cursor()
        return self._rotate_cursor_cache

    @staticmethod
    def _make_rotate_cursor():
        """绘制顺时针旋转箭头光标（透明底、白色箭头）。"""
        from PySide6.QtCore import QRectF, QPointF
        pm = QPixmap(28, 28)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#ffffff"), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        # 从 12 点方向顺时针画 300° 圆弧，留 60° 缺口放箭头
        p.drawArc(QRectF(5, 5, 18, 18), 90 * 16, -300 * 16)
        cx = cy = 14.0
        r = 9.0
        end_deg = math.radians(150)
        ex = cx + r * math.cos(end_deg)
        ey = cy + r * math.sin(end_deg)
        tx = math.sin(end_deg)
        ty = -math.cos(end_deg)
        tip = QPointF(ex + tx * 5.0, ey + ty * 5.0)
        base = QPointF(ex - tx * 3.0, ey - ty * 3.0)
        side1 = QPointF(ex - ty * 4.0, ey + tx * 4.0)
        side2 = QPointF(ex + ty * 4.0, ey - tx * 4.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawPolygon(QPolygonF([tip, side1, base, side2]))
        p.end()
        return QCursor(pm)

    def get_handle_under_mouse(self, pos):
        """返回 (handle, idx)。handle: 'vertex-N'（N=0..3，仅激活框）/ 'move'（任意框内）/ None。"""
        if self.frame_w <= 0 or self.frame_h <= 0 or self.target_w <= 0 or self.target_h <= 0 or not self.boxes:
            return None, -1

        mx, my = pos.x(), pos.y()
        w_ratio = self.target_w / self.frame_w
        h_ratio = self.target_h / self.frame_h
        threshold = 10  # widget 像素

        # 激活框优先
        box_indices = list(range(len(self.boxes)))
        if 0 <= self.active_box_index < len(self.boxes):
            box_indices.remove(self.active_box_index)
            box_indices.insert(0, self.active_box_index)

        for idx in box_indices:
            quad = self.boxes[idx]
            is_active = (idx == self.active_box_index)
            # 激活框：先检测 4 个顶点手柄
            if is_active:
                for vi, (vx, vy) in enumerate(quad):
                    rx = self.px_offset_x + vx * w_ratio
                    ry = self.px_offset_y + vy * h_ratio
                    if abs(mx - rx) < threshold and abs(my - ry) < threshold:
                        return f'vertex-{vi}', idx
            # 所有框：检测四边形内部（射线法，帧坐标）
            fpt = self._widget_to_frame(pos)
            if fpt and self._point_in_quad(fpt[0], fpt[1], quad):
                return 'move', idx
        return None, -1

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle, idx = self.get_handle_under_mouse(event.pos())
        if handle is not None:
            if idx != self.active_box_index:
                self.active_box_index = idx
                self.selectionChanged.emit(idx)
            self.drag_mode = handle
            self.drag_start_pos = event.pos()
            self.drag_start_quad = [list(p) for p in self.boxes[idx]]
            # 右下角顶点 = 旋转把手：按下进入整体旋转模式
            if (handle.startswith('vertex-')
                    and int(handle.split('-')[1]) == self._rotation_vertex_index()):
                self.drag_mode = 'rotate'
                self.rotate_center = (
                    sum(p[0] for p in self.drag_start_quad) / 4.0,
                    sum(p[1] for p in self.drag_start_quad) / 4.0,
                )
                cx, cy = self.rotate_center
                fx = (event.pos().x() - self.px_offset_x) * self.frame_w / self.target_w
                fy = (event.pos().y() - self.px_offset_y) * self.frame_h / self.target_h
                self.rotate_start_angle = math.atan2(fy - cy, fx - cx)

    def mouseMoveEvent(self, event):
        # 旋转/顶点/整体移动拖动
        if self.drag_mode is not None and self.drag_start_pos is not None and self.active_box_index >= 0:
            sq = self.drag_start_quad  # 起始四点

            if self.drag_mode == 'rotate':
                fx = (event.pos().x() - self.px_offset_x) * self.frame_w / self.target_w
                fy = (event.pos().y() - self.px_offset_y) * self.frame_h / self.target_h
                cx, cy = self.rotate_center
                delta = math.atan2(fy - cy, fx - cx) - self.rotate_start_angle
                cos_d, sin_d = math.cos(delta), math.sin(delta)
                new_quad = []
                for px, py in sq:
                    ox, oy = px - cx, py - cy
                    new_quad.append([cx + ox * cos_d - oy * sin_d,
                                     cy + ox * sin_d + oy * cos_d])
                # 旋转后整体平移，尽量把外接框留在画面内：
                # 放得下 → 整体贴边；放不下（旋转后比画面还大）→ 上/左缘贴边，不把框推出屏幕
                aabb = _quad_aabb(new_quad)
                tx = 0
                if aabb[2] <= self.frame_w:
                    if aabb[0] < 0:
                        tx = -aabb[0]
                    elif aabb[0] + aabb[2] > self.frame_w:
                        tx = self.frame_w - aabb[0] - aabb[2]
                else:
                    tx = -aabb[0] if aabb[0] < 0 else 0
                ty = 0
                if aabb[3] <= self.frame_h:
                    if aabb[1] < 0:
                        ty = -aabb[1]
                    elif aabb[1] + aabb[3] > self.frame_h:
                        ty = self.frame_h - aabb[1] - aabb[3]
                else:
                    ty = -aabb[1] if aabb[1] < 0 else 0
                self.boxes[self.active_box_index] = [[p[0] + tx, p[1] + ty] for p in new_quad]
            else:
                cur = self._widget_to_frame(event.pos())
                start = self._widget_to_frame(self.drag_start_pos)
                if not cur or not start:
                    return
                dx = cur[0] - start[0]
                dy = cur[1] - start[1]

                if self.drag_mode == 'move':
                # 整体平移：clamp 使 AABB 不出帧
                    aabb = _quad_aabb(sq)
                    nx = max(-aabb[0], min(dx, self.frame_w - aabb[0] - aabb[2]))
                    ny = max(-aabb[1], min(dy, self.frame_h - aabb[1] - aabb[3]))
                    self.boxes[self.active_box_index] = [[p[0] + nx, p[1] + ny] for p in sq]
                elif self.drag_mode.startswith('vertex-'):
                    vi = int(self.drag_mode.split('-')[1])
                    new_quad = [list(p) for p in sq]
                    new_quad[vi] = [max(0, min(self.frame_w, cur[0])),
                                    max(0, min(self.frame_h, cur[1]))]
                    self.boxes[self.active_box_index] = new_quad

            self.boundsChanged.emit(self.active_box_index)
        else:
            # 光标提示
            handle, _ = self.get_handle_under_mouse(event.pos())
            if handle and handle.startswith('vertex-'):
                vi = int(handle.split('-')[1])
                if vi == self._rotation_vertex_index():
                    self.setCursor(self._rotate_cursor())
                else:
                    quad = self.boxes[self.active_box_index]
                    cx = sum(p[0] for p in quad) / 4.0
                    cy = sum(p[1] for p in quad) / 4.0
                    vx, vy = quad[vi]
                    self.setCursor(
                        Qt.SizeFDiagCursor if (vx - cx) * (vy - cy) >= 0
                        else Qt.SizeBDiagCursor)
            elif handle == 'move':
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_mode = None
            self.drag_start_pos = None
            self.drag_start_quad = None
            self.rotate_center = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


from gui.base_page import BasePage


class SubtitleRemovalPageV14(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.timer = None
        self.original_frame = None
        self.frame_width = 1280
        self.frame_height = 720
        self.preview_img_path = ""
        self.boxes = [] # List of [x, y, w, h] boxes
        self.active_box_index = -1

    def setup(self):
        tmp_dir = TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        self.preview_img_path = os.path.join(tmp_dir, "vsr_preview.jpg")

        # Page main layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(16)

        # Title
        heading = QLabel("视频去字幕")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 2px; }")
        main_layout.addWidget(splitter, 1)

        # --- Left Panel: File Selection & Preview ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)

        # Select file card (top part of left side)
        select_card = QFrame()
        select_card.setObjectName("card")
        select_layout = QVBoxLayout(select_card)
        select_layout.setContentsMargins(16, 16, 16, 16)
        select_layout.setSpacing(10)

        inp_row = QHBoxLayout()
        inp_row.addWidget(QLabel("输入视频/图片:"))
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText("选择视频 (.mp4/.avi) 或图片 ...")
        self.video_path_input.textChanged.connect(self._on_video_path_changed)
        inp_row.addWidget(self.video_path_input)
        btn_sel = QPushButton("选择文件")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_video)
        inp_row.addWidget(btn_sel)
        select_layout.addLayout(inp_row)
        left_layout.addWidget(select_card, 0)

        # Video Preview card (bottom part of left side)
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        p_layout = QVBoxLayout(preview_card)
        p_layout.setContentsMargins(16, 16, 16, 16)
        p_layout.setSpacing(10)

        p_title = QLabel("🖼️ 实时预览画面 (多选区: 绿框为当前选中，蓝框为其他选区):")
        p_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        p_layout.addWidget(p_title)

        self.preview_label = InteractivePreviewLabelV14()
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.boundsChanged.connect(self._on_label_bounds_changed)
        self.preview_label.selectionChanged.connect(self._on_label_selection_changed)
        self.preview_label.resized.connect(self.update_preview)
        p_layout.addWidget(self.preview_label, 1)

        # Video progress slider for scrubbing / previewing frames
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        
        button_style = """
            QPushButton {
                background-color: #1a1a24;
                color: #a1a1aa;
                border: 1px solid #2e2e38;
                border-radius: 4px;
                font-size: 11px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: #2e2e38;
                color: #ffffff;
                border-color: #3b82f6;
            }
            QPushButton:disabled {
                background-color: #13131a;
                color: #4b5563;
                border-color: #1f2937;
            }
        """

        self.btn_prev_frame = QPushButton("◀")
        self.btn_prev_frame.setFixedWidth(30)
        self.btn_prev_frame.setStyleSheet(button_style)
        self.btn_prev_frame.clicked.connect(self._step_prev_frame)
        seek_row.addWidget(self.btn_prev_frame)
        
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #27272a;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #3b82f6;
                width: 20px;
                height: 20px;
                margin: -8px 0;
                border-radius: 10px;
            }
            QSlider::handle:horizontal:hover {
                background: #3b82f6;
                border: 2px solid #ffffff;
                width: 22px;
                height: 22px;
                margin: -9px 0;
                border-radius: 11px;
            }
        """)
        seek_row.addWidget(self.seek_slider)
        
        self.btn_next_frame = QPushButton("▶")
        self.btn_next_frame.setFixedWidth(30)
        self.btn_next_frame.setStyleSheet(button_style)
        self.btn_next_frame.clicked.connect(self._step_next_frame)
        seek_row.addWidget(self.btn_next_frame)
        
        self.lbl_seek_time = QLabel("00:00 / 00:00")
        self.lbl_seek_time.setFixedWidth(90)
        self.lbl_seek_time.setAlignment(Qt.AlignCenter)
        self.lbl_seek_time.setStyleSheet("""
            QLabel {
                font-family: 'Courier New', monospace;
                font-weight: bold;
                color: #3b82f6;
                background-color: #16161e;
                border: 1px solid #2e2e38;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }
        """)
        seek_row.addWidget(self.lbl_seek_time)

        p_layout.addLayout(seek_row)
        left_layout.addWidget(preview_card, 1)

        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        splitter.addWidget(left_widget)

        # --- Right Panel: Control Area & Processing Log ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_widget.setMinimumWidth(380)

        # Control card (top part of right side)
        controls_card = QFrame()
        controls_card.setObjectName("card")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(0, 20, 0, 20)
        controls_layout.setSpacing(14)

        # ── 用途 + 模式 两个维度（2×2=4 组合，算法由服务端匹配）──
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(QLabel("用途:"))
        self.purpose_combo = QComboBox()
        self.purpose_combo.addItem("📝 去字幕", "subtitle")
        self.purpose_combo.addItem("🏷️ 去水印", "watermark")
        self.purpose_combo.setToolTip("去字幕：擦除视频中的字幕文字。\n去水印：擦除台标/LOGO 等水印。可填写水印文字帮助服务端精准定位要去除的水印。")
        mode_row.addWidget(self.purpose_combo)
        mode_row.addSpacing(12)
        mode_row.addWidget(QLabel("模式:"))
        self.mode_switch = QComboBox()
        self.mode_switch.addItem("✏️ 标注选区（手画四边形选区）", "select")
        self.mode_switch.addItem("🤖 智能识别（自动检测，无需画框）", "smart")
        self.mode_switch.currentIndexChanged.connect(self._on_mode_switched)
        mode_row.addWidget(self.mode_switch, 1)
        controls_layout.addLayout(mode_row)

        # 去水印时才显示的水印文字输入（帮助服务端精准定位要去除的水印）
        watermark_row = QHBoxLayout()
        watermark_row.setSpacing(8)
        self.watermark_lbl = QLabel("水印文字:")
        watermark_row.addWidget(self.watermark_lbl)
        self.watermark_input = QLineEdit()
        self.watermark_input.setPlaceholderText("要去除的水印文字内容（留空=按选区/自动识别去除）")
        watermark_row.addWidget(self.watermark_input)
        self.watermark_container = QWidget()
        wl = QHBoxLayout(self.watermark_container)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addLayout(watermark_row)
        self.watermark_container.setVisible(False)  # 默认去字幕，隐藏
        controls_layout.addWidget(self.watermark_container)
        self.purpose_combo.currentIndexChanged.connect(self._on_purpose_changed)

        # Combined Subtitle Area Manager & Editor (Visual Design Optimized)
        box_manage_group = QFrame()
        self.box_manage_group = box_manage_group
        box_manage_group.setObjectName("box_manage_group")
        box_manage_group.setStyleSheet("#box_manage_group { background-color: #26262a; border-top: 1px solid #2e2e32; border-bottom: 1px solid #2e2e32; border-radius: 0px; }")
        box_manage_layout = QVBoxLayout(box_manage_group)
        box_manage_layout.setContentsMargins(24, 16, 24, 16)
        box_manage_layout.setSpacing(14)

        # Header: Title (uses standard style)
        box_manage_title = QLabel("📦 字幕选区管理:")
        box_manage_title.setStyleSheet("font-weight: bold; color: #ffffff;")
        box_manage_layout.addWidget(box_manage_title)

        # List Widget
        self.box_list_widget = QListWidget()
        self.box_list_widget.setMaximumHeight(95)
        self.box_list_widget.currentRowChanged.connect(self._on_box_list_row_changed)
        self.box_list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1e1e24;
                border: 1px solid #2e2e32;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #28282c;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: white;
            }
        """)
        box_manage_layout.addWidget(self.box_list_widget)

        # Action Buttons
        btn_box_layout = QHBoxLayout()
        btn_box_layout.setSpacing(10)

        self.btn_add_box = QPushButton("➕ 添加选区")
        self.btn_add_box.setObjectName("secondary_button")
        self.btn_add_box.clicked.connect(self._add_box)
        btn_box_layout.addWidget(self.btn_add_box)

        self.btn_delete_box = QPushButton("➖ 删除选区")
        self.btn_delete_box.setObjectName("secondary_button")
        self.btn_delete_box.clicked.connect(self._delete_box)
        btn_box_layout.addWidget(self.btn_delete_box)

        box_manage_layout.addLayout(btn_box_layout)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("background-color: #2e2e32; max-height: 1px;")
        box_manage_layout.addWidget(sep)

        # Coordinate sliders（包在容器里，智能去除模式下整体隐藏）
        self.sliders_container = QWidget()
        sliders_layout = QVBoxLayout(self.sliders_container)
        sliders_layout.setContentsMargins(0, 0, 0, 0)
        sliders_layout.setSpacing(14)

        def create_slider_row(label_text, slider, val_lbl):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(100)
            row.addWidget(lbl)
            slider.setRange(0, 100)
            row.addWidget(slider)
            val_lbl.setStyleSheet("font-weight: bold; min-width: 30px;")
            row.addWidget(val_lbl)
            return row

        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.valueChanged.connect(self.update_preview)
        self.x_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始横坐标 X:", self.x_slider, self.x_val_lbl))

        self.w_slider = QSlider(Qt.Horizontal)
        self.w_slider.valueChanged.connect(self.update_preview)
        self.w_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("字幕选区宽 W:", self.w_slider, self.w_val_lbl))

        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.valueChanged.connect(self.update_preview)
        self.y_val_lbl = QLabel("0")
        sliders_layout.addLayout(create_slider_row("起始纵坐标 Y:", self.y_slider, self.y_val_lbl))

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.valueChanged.connect(self.update_preview)
        self.h_val_lbl = QLabel("1")
        sliders_layout.addLayout(create_slider_row("字幕选区高 H:", self.h_slider, self.h_val_lbl))

        box_manage_layout.addWidget(self.sliders_container)
        self.sliders_container.setVisible(False)  # 四边形直接在预览上拖角点编辑，不再需要坐标滑块
        controls_layout.addWidget(box_manage_group)

        # Options & action buttons (bottom of control card)
        bottom_container = QWidget()
        bottom_container_layout = QVBoxLayout(bottom_container)
        bottom_container_layout.setContentsMargins(24, 0, 24, 0)
        bottom_container_layout.setSpacing(14)

        # 视频去字幕统一走服务端处理，不再暴露本地算法/编码/帧数等设置

        bottom_container_layout.addStretch(1)

        # Status & progress
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("muted_text")
        bottom_container_layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #2e2e38;
                border-radius: 6px;
                background-color: #15151e;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: QLinearGradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 5px;
            }
        """)
        bottom_container_layout.addWidget(self.progress_bar)

        # Run buttons
        btn_action_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始去除字幕")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self.start_removal)
        btn_action_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹️ 停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_removal)
        btn_action_layout.addWidget(self.btn_stop)
        bottom_container_layout.addLayout(btn_action_layout)

        controls_layout.addWidget(bottom_container, 1)
        right_layout.addWidget(controls_card, 0)

        # Processing Log (bottom part of right side)
        log_card = QFrame()
        log_card.setObjectName("card")
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout(log_card)
        log_card.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(6)

        log_layout.addWidget(QLabel("📝 处理日志:"))
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_viewer")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_card, 1)  # ← log_card 加入右侧布局（修复：原来缺失此行）
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

    def _select_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择输入视频或图片",
            "",
            "Media Files (*.mp4 *.avi *.mov *.mkv *.png *.jpg *.jpeg);;All Files (*)"
        )
        if path:
            self.video_path_input.setText(path)

    def _on_video_path_changed(self, path):
        path = path.strip()
        if not path or not os.path.exists(path):
            self.original_frame = None
            self.preview_label.clear()
            self.preview_label.setText("请选择有效的媒体文件")
            return

        try:
            # Check if it is image or video
            ext = os.path.splitext(path)[1].lower()
            is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]
            if is_pic:
                img = Image.open(path)
                self.original_frame = img
                self.frame_width, self.frame_height = img.size
                
                self.seek_slider.setEnabled(False)
                self.seek_slider.setValue(0)
                self.lbl_seek_time.setText("图片无进度")
                self.btn_prev_frame.setEnabled(False)
                self.btn_next_frame.setEnabled(False)
            else:
                container = av.open(path)
                video_stream = next(s for s in container.streams if s.type == 'video')
                self.frame_width = video_stream.width
                self.frame_height = video_stream.height
                
                # Read first frame
                for frame in container.decode(video_stream):
                    self.original_frame = frame.to_image()
                    break
                
                total_sec = container.duration / 1000000.0 if container.duration else 0.0
                self.lbl_seek_time.setText(f"00:00 / {self._format_time(total_sec)}")
                container.close()
                
                self.seek_slider.setEnabled(True)
                self.seek_slider.setValue(0)
                self.btn_prev_frame.setEnabled(True)
                self.btn_next_frame.setEnabled(True)
                
            # Block sliders signals during bounds setup
            self.x_slider.blockSignals(True)
            self.w_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            self.h_slider.blockSignals(True)

            self.x_slider.setRange(0, self.frame_width)
            self.w_slider.setRange(1, self.frame_width)
            self.y_slider.setRange(0, self.frame_height)
            self.h_slider.setRange(1, self.frame_height)

            self.preview_label.frame_w = self.frame_width
            self.preview_label.frame_h = self.frame_height

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            # Initialize first default box（四点四边形，默认为字幕带矩形）
            self.boxes = [
                _rect_to_quad(
                    int(self.frame_width * 0.05),
                    int(self.frame_height * 0.78),
                    int(self.frame_width * 0.90),
                    int(self.frame_height * 0.21),
                )
            ]
            self.active_box_index = 0
            self._update_box_list_widget()
            
            # Force layout activation & events processing to quickly determine correct preview size
            if self.parent_widget.layout():
                self.parent_widget.layout().activate()
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            self.update_preview()
            
            # Schedule a short deferred update as well
            QTimer.singleShot(50, self.update_preview)
        except Exception as e:
            log.error(f"Failed to load video preview: {e}")
            self.original_frame = None
            self.preview_label.setText(f"预览加载失败: {e}")

    def _is_smart_mode(self):
        """智能识别模式：不画框，服务端自动检测。"""
        return getattr(self, "mode_switch", None) is not None and self.mode_switch.currentData() == "smart"

    def _is_select_mode(self):
        """标注选区模式：用户画四边形选区。"""
        return not self._is_smart_mode()

    def _get_purpose(self):
        """用途：subtitle(去字幕) / watermark(去水印)。"""
        return self.purpose_combo.currentData() if hasattr(self, "purpose_combo") else "subtitle"

    def _on_purpose_changed(self, _idx):
        """用途切换：去水印时显示水印文字输入。"""
        is_watermark = self._get_purpose() == "watermark"
        self.watermark_container.setVisible(is_watermark)

    def _on_mode_switched(self, _idx):
        """切换智能/标注模式：显隐选区管理区，两种模式都强制走服务端。"""
        is_select = self._is_select_mode()
        # 选区管理区只在标注模式显示；坐标滑块已废弃
        box_group = getattr(self, "box_manage_group", None)
        if box_group is not None:
            box_group.setVisible(is_select)
        # 服务端处理固定开启，不暴露本地选项
        self.update_preview()

    def _update_box_list_widget(self):
        self.box_list_widget.blockSignals(True)
        self.box_list_widget.clear()
        for idx, quad in enumerate(self.boxes):
            x, y, w, h = _quad_aabb(quad)
            self.box_list_widget.addItem(f"选区 {idx+1}: X={x}, Y={y}, W={w}, H={h}")
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            self.box_list_widget.setCurrentRow(self.active_box_index)
        self.box_list_widget.blockSignals(False)
        self._sync_sliders_to_active_box()

    def _sync_sliders_to_active_box(self):
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            x, y, w, h = _quad_aabb(self.boxes[self.active_box_index])
            
            self.x_slider.blockSignals(True)
            self.w_slider.blockSignals(True)
            self.y_slider.blockSignals(True)
            self.h_slider.blockSignals(True)

            self.x_slider.setValue(x)
            self.w_slider.setValue(w)
            self.y_slider.setValue(y)
            self.h_slider.setValue(h)

            self.x_val_lbl.setText(str(x))
            self.w_val_lbl.setText(str(w))
            self.y_val_lbl.setText(str(y))
            self.h_val_lbl.setText(str(h))

            self.x_slider.blockSignals(False)
            self.w_slider.blockSignals(False)
            self.y_slider.blockSignals(False)
            self.h_slider.blockSignals(False)

            self.btn_delete_box.setEnabled(len(self.boxes) > 1)
        else:
            self.btn_delete_box.setEnabled(False)

    def _on_box_list_row_changed(self, row):
        if row >= 0 and row < len(self.boxes):
            self.active_box_index = row
            self._sync_sliders_to_active_box()
            self.update_preview()

    def _add_box(self):
        if not self.video_path_input.text().strip() or self.original_frame is None:
            return

        x = int(self.frame_width * 0.05)
        y = int(self.frame_height * 0.78)
        w = int(self.frame_width * 0.90)
        h = int(self.frame_height * 0.21)
        if self.boxes:
            lx, ly, lw, lh = _quad_aabb(self.boxes[-1])
            x = lx
            w = lw
            y = max(0, ly - 40)  # 上移避免完全重叠
            h = lh
        self.boxes.append(_rect_to_quad(x, y, w, h))
        self.active_box_index = len(self.boxes) - 1
        self._update_box_list_widget()
        self.update_preview()

    def _delete_box(self):
        if len(self.boxes) <= 1:
            return
        if self.active_box_index >= 0 and self.active_box_index < len(self.boxes):
            self.boxes.pop(self.active_box_index)
            self.active_box_index = min(self.active_box_index, len(self.boxes) - 1)
            self._update_box_list_widget()
            self.update_preview()

    def update_preview(self):
        # 本地模式处理中禁止更新预览；服务端模式上传后允许拖动预览
        if self.worker and self.worker.isRunning():
            if not isinstance(self.worker, RemoteVSRWorkerV14):
                return

        # 四边形直接在预览上拖角点编辑，无需从滑块同步

        # Pass boxes to interactive label
        self.preview_label.set_boxes(self.boxes, self.active_box_index)

        if self.original_frame is not None:
            # Fit to widget layout keeping aspect ratio
            display_w = self.preview_label.width()
            display_h = self.preview_label.height()
            if display_w < 100 or display_h < 100:
                display_w, display_h = 720, 405

            w_img, h_img = self.original_frame.size
            ratio = min(display_w / w_img, display_h / h_img)
            target_w = int(w_img * ratio)
            target_h = int(h_img * ratio)
            if target_w < 1: target_w = 1
            if target_h < 1: target_h = 1

            self.preview_label.target_w = target_w
            self.preview_label.target_h = target_h
            self.preview_label.px_offset_x = (display_w - target_w) // 2
            self.preview_label.px_offset_y = (display_h - target_h) // 2

            # PIL resize
            resized_img = self.original_frame.resize((target_w, target_h), Image.Resampling.LANCZOS)

            # 绘制四边形选区（智能去除模式下不画）
            draw = ImageDraw.Draw(resized_img)
            if self._is_select_mode():
                for idx, quad in enumerate(self.boxes):
                    # 帧坐标 → 显示坐标
                    pts = [(int(p[0] * target_w / w_img), int(p[1] * target_h / h_img)) for p in quad]
                    is_active = (idx == self.active_box_index)
                    outline = "#00ff00" if is_active else "#00ffff"
                    width = 3 if is_active else 2
                    draw.polygon(pts, outline=outline, width=width)
                    # 激活框：3 个角为拉伸方块手柄，右下角为旋转圆环把手
                    if is_active:
                        hs = 5  # 手柄半边长
                        rot_i = self.preview_label._rotation_vertex_index()
                        for vi, (hx, hy) in enumerate(pts):
                            if vi == rot_i:
                                # 旋转把手：黄色圆环 + 斜向箭头
                                draw.ellipse([hx - 7, hy - 7, hx + 7, hy + 7],
                                             outline="#ffd400", width=2)
                                ax0, ay0 = hx + 3, hy - 8
                                ax1, ay1 = hx + 10, hy - 14
                                draw.line([ax0, ay0, ax1, ay1], fill="#ffd400", width=2)
                                draw.polygon(
                                    [(ax1, ay1 - 4), (ax1 + 4, ay1), (ax1 - 2, ay1 + 2)],
                                    fill="#ffd400")
                            else:
                                draw.rectangle([hx - hs, hy - hs, hx + hs, hy + hs],
                                               fill="#00ff00", outline="#ffffff")

            # Convert to QImage
            rgb_img = resized_img.convert("RGB")
            data = rgb_img.tobytes("raw", "RGB")
            qImg = QImage(data, target_w, target_h, target_w * 3, QImage.Format_RGB888)
            self.preview_label.setPixmap(QPixmap.fromImage(qImg))

    def _on_label_bounds_changed(self, idx):
        """label 上顶点拖动/整体移动后，同步滑块到激活四边形的 AABB。"""
        self.active_box_index = idx
        quad = self.boxes[idx]
        x, y, w, h = _quad_aabb(quad)
        self.x_slider.blockSignals(True)
        self.w_slider.blockSignals(True)
        self.y_slider.blockSignals(True)
        self.h_slider.blockSignals(True)
        self.x_slider.setValue(x)
        self.w_slider.setValue(w)
        self.y_slider.setValue(y)
        self.h_slider.setValue(h)
        self.x_val_lbl.setText(str(x))
        self.w_val_lbl.setText(str(w))
        self.y_val_lbl.setText(str(y))
        self.h_val_lbl.setText(str(h))
        self.x_slider.blockSignals(False)
        self.w_slider.blockSignals(False)
        self.y_slider.blockSignals(False)
        self.h_slider.blockSignals(False)
        # Update list item text quietly
        self.box_list_widget.blockSignals(True)
        item = self.box_list_widget.item(idx)
        if item:
            item.setText(f"选区 {idx+1}: X={x}, Y={y}, W={w}, H={h}")
        self.box_list_widget.setCurrentRow(idx)
        self.box_list_widget.blockSignals(False)
        self.update_preview()

    def _on_label_selection_changed(self, idx):
        self.active_box_index = idx
        self.box_list_widget.blockSignals(True)
        self.box_list_widget.setCurrentRow(idx)
        self.box_list_widget.blockSignals(False)
        self._sync_sliders_to_active_box()

    def start_removal(self):
        video_path = self.video_path_input.text().strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.warning(self.parent_widget, "参数错误", "请先选择有效的输入视频或图片！")
            return

        # 选区去除模式必须至少有一个选区；智能去除模式不需要
        is_smart = self._is_smart_mode()
        if not is_smart and not self.boxes:
            QMessageBox.warning(self.parent_widget, "参数错误", "请先设置至少一个擦除选区！")
            return

        # 视频去字幕统一走服务端处理
        self._start_remote_removal(video_path)

    def _lock_controls(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.video_path_input.setEnabled(False)
        self.x_slider.setEnabled(False)
        self.w_slider.setEnabled(False)
        self.y_slider.setEnabled(False)
        self.h_slider.setEnabled(False)
        self.btn_add_box.setEnabled(False)
        self.btn_delete_box.setEnabled(False)
        self.box_list_widget.setEnabled(False)
        self.purpose_combo.setEnabled(False)
        self.mode_switch.setEnabled(False)
        self.seek_slider.setEnabled(False)
        self.btn_prev_frame.setEnabled(False)
        self.btn_next_frame.setEnabled(False)

    def _start_remote_removal(self, video_path):
        """服务端模式：上传视频到 /vsr/remove。

        算法由服务端匹配，客户端只传 purpose(subtitle/watermark) + sub_areas。
        去字幕=精准检测(sttn_det)，去水印=整框重绘(sttn_auto)。
        """
        purpose = self._get_purpose()
        # 去水印→sttn_auto(整框重绘)，去字幕→sttn_det(精准检测)；具体模型服务端匹配
        inpaint_mode = "sttn_auto" if purpose == "watermark" else "sttn_det"

        # 智能识别模式：空 sub_areas，服务端自动检测；标注选区模式：四边形相对坐标
        if self._is_smart_mode():
            sub_areas = ""
        else:
            # 每个四边形 → 相对坐标四点；整体格式 [[ [四点] ], ...]
            polys = [_quad_to_relative_polygon(q, self.frame_width, self.frame_height) for q in self.boxes]
            sub_areas = _json.dumps(polys)

        # 去水印时附带水印文字（帮助服务端精准定位要去除的水印）
        watermark_text = ""
        if purpose == "watermark" and hasattr(self, "watermark_input"):
            watermark_text = self.watermark_input.text().strip()

        base_dir = os.path.dirname(video_path)
        vd_name = os.path.splitext(os.path.basename(video_path))[0]
        ext = os.path.splitext(video_path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".bmp"]:
            output_path = os.path.join(base_dir, "no_sub", f"{vd_name}{ext}")
        else:
            output_path = os.path.join(base_dir, f"{vd_name}_no_sub.mp4")

        self._lock_controls()
        # 服务端模式：视频上传后预览拖动放开（不影响处理）
        self.seek_slider.setEnabled(True)
        self.btn_prev_frame.setEnabled(True)
        self.btn_next_frame.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_view.clear()

        self.worker = RemoteVSRWorkerV14(
            video_path=video_path,
            sub_areas=sub_areas,
            inpaint_mode=inpaint_mode,
            output_path=output_path,
            purpose=purpose,
            watermark_text=watermark_text,
        )
        self.worker.progress_updated.connect(self.on_worker_progress)
        self.worker.status_updated.connect(self.on_worker_status)
        self.worker.log_received.connect(self.on_worker_log)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def stop_removal(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_lbl.setText("状态: 正在终止中，请稍候...")
            self.log_view.append("\n[WARN] 已发出停止指令，等待引擎退出...") 
            # 不在这里调用 cleanup_ui()，等 worker 的 finished 信号触发 on_worker_finished 统一处理

    def on_worker_progress(self, val):
        self.progress_bar.setValue(val)

    def on_worker_status(self, text):
        self.status_lbl.setText(f"状态: {text}")

    def on_worker_log(self, text):
        self.log_view.append(text)

    def on_worker_finished(self, success, out_path):
        self.cleanup_ui()
        if success:
            self.status_lbl.setText("状态: 字幕擦除完毕！")
            
            msg_box = QMessageBox(self.parent_widget)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setWindowTitle("去字幕成功")
            msg_box.setText(f"字幕擦除并画面重绘成功！\n新生成的媒体文件已保存至：\n\n{out_path}")
            
            open_btn = msg_box.addButton("打开文件夹", QMessageBox.ActionRole)
            ok_btn = msg_box.addButton("确定", QMessageBox.AcceptRole)
            
            msg_box.exec()
            
            if msg_box.clickedButton() == open_btn:
                try:
                    import subprocess
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(out_path)}"')
                except Exception as e:
                    log.error(f"Failed to open output directory: {e}")

            # Restore original video preview with selection boxes overlaid
            self.update_preview()
        else:
            if self.worker and self.worker.is_aborted:
                self.status_lbl.setText("状态: 已被用户终止。")
                self.update_preview()
                return

            self.status_lbl.setText(f"状态: 出错。")
            QMessageBox.critical(
                self.parent_widget,
                "处理失败",
                f"去字幕执行过程中发生错误：\n\n{out_path}"
            )
            # Restore original preview on failure as well
            self.update_preview()

    def poll_preview_image(self):
        if os.path.exists(self.preview_img_path):
            try:
                pix = QPixmap()
                with open(self.preview_img_path, "rb") as f:
                    data = f.read()
                pix.loadFromData(data)
                if not pix.isNull():
                    self.preview_label.setPixmap(pix.scaled(
                        self.preview_label.size(), 
                        Qt.KeepAspectRatio, 
                        Qt.SmoothTransformation
                    ))
            except Exception:
                pass

    def cleanup_ui(self):
        if self.timer:
            self.timer.stop()
            self.timer = None
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.video_path_input.setEnabled(True)
        self.x_slider.setEnabled(True)
        self.w_slider.setEnabled(True)
        self.y_slider.setEnabled(True)
        self.h_slider.setEnabled(True)
        self.btn_add_box.setEnabled(True)
        self.btn_delete_box.setEnabled(len(self.boxes) > 1)
        self.box_list_widget.setEnabled(True)
        self.purpose_combo.setEnabled(True)
        self.mode_switch.setEnabled(True)
        self.progress_bar.setValue(0)

        # Restore seek controls based on if it's a video
        video_path = self.video_path_input.text().strip()
        ext = os.path.splitext(video_path)[1].lower() if video_path else ""
        is_pic = ext in [".jpg", ".jpeg", ".png", ".bmp"]
        self.seek_slider.setEnabled(not is_pic and bool(video_path))
        self.btn_prev_frame.setEnabled(not is_pic and bool(video_path))
        self.btn_next_frame.setEnabled(not is_pic and bool(video_path))

    def _seek_to_ratio(self, ratio):
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
            
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".bmp"]:
            return
            
        try:
            container = av.open(path)
            video_stream = next(s for s in container.streams if s.type == 'video')
            
            duration = video_stream.duration
            if duration is None or duration <= 0:
                duration_sec = container.duration / 1000000.0
                target_sec = ratio * duration_sec
                target_ts = int(target_sec / float(video_stream.time_base))
            else:
                target_ts = int(ratio * duration)
                
            container.seek(target_ts, stream=video_stream)
            
            frame_found = False
            for frame in container.decode(video_stream):
                self.original_frame = frame.to_image()
                frame_found = True
                break
                
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            
            if frame_found:
                self.update_preview()
                curr_sec = ratio * total_sec
                self.lbl_seek_time.setText(f"{self._format_time(curr_sec)} / {self._format_time(total_sec)}")
                
        except Exception as e:
            log.error(f"Seek failed: {e}")

    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _on_seek_moved(self, value):
        ratio = value / 1000.0
        self._seek_to_ratio(ratio)

    def _on_seek_released(self):
        ratio = self.seek_slider.value() / 1000.0
        self._seek_to_ratio(ratio)

    def _step_prev_frame(self):
        val = self.seek_slider.value()
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            container = av.open(path)
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            if total_sec > 0:
                ratio_step = 1.0 / total_sec
                new_ratio = max(0.0, (val / 1000.0) - ratio_step)
                self.seek_slider.setValue(int(new_ratio * 1000))
                self._seek_to_ratio(new_ratio)
        except Exception:
            pass

    def _step_next_frame(self):
        val = self.seek_slider.value()
        path = self.video_path_input.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            container = av.open(path)
            total_sec = container.duration / 1000000.0 if container.duration else 0.0
            container.close()
            if total_sec > 0:
                ratio_step = 1.0 / total_sec
                new_ratio = min(1.0, (val / 1000.0) + ratio_step)
                self.seek_slider.setValue(int(new_ratio * 1000))
                self._seek_to_ratio(new_ratio)
        except Exception:
            pass
