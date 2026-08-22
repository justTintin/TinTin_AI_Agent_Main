# -*- coding: utf-8 -*-
"""批量 LUT 调色转换页面

选定一个视频文件夹和一个 LUT 文件（.cube / .3dl / .lut），
对文件夹内所有视频批量应用 LUT 后导出为标准 H.264 MP4。
可通过强度滑块在原始画面和完整 LUT 效果之间做混合。
"""

import os
import sys
import subprocess
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QDoubleSpinBox,
    QCheckBox, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from utils.base_worker import BaseWorker

from utils.logger_utils import log
from utils.hwaccel import get_video_encode_args


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _find_ffmpeg():
    """查找 ffmpeg 可执行文件（使用平台感知的统一查找）。"""
    from utils.platform_utils import find_ffmpeg as _ff
    return _ff()


def _escape_lut_path(path):
    """将 LUT 文件路径转义为 FFmpeg filter 可接受的格式（Windows 冒号需转义）。"""
    p = path.replace("\\", "/")
    # Windows 盘符冒号：C:/... → C\:/...
    if len(p) > 1 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".mts", ".ts")


# ─── Worker ──────────────────────────────────────────────────────────────────

class VideoLutWorker(BaseWorker):
    stage    = Signal(str)
    progress = Signal(int)          # 0-100
    log_line = Signal(str)          # 追加到日志框
    finished = Signal(int, int)     # (成功数, 失败数)
    error    = Signal(str)

    def __init__(self, video_files, lut_path, output_dir, intensity=1.0):
        super().__init__()
        self.video_files = video_files
        self.lut_path    = lut_path
        self.output_dir  = output_dir
        self.intensity   = intensity   # 0.0 = 原始, 1.0 = 完整 LUT

    def run(self):
        try:
            ffmpeg = _find_ffmpeg()
            os.makedirs(self.output_dir, exist_ok=True)

            total   = len(self.video_files)
            success = 0
            fail    = 0
            lut_esc = _escape_lut_path(self.lut_path)

            for idx, src in enumerate(self.video_files):
                basename = os.path.basename(src)
                stem     = os.path.splitext(basename)[0]
                dst      = os.path.join(self.output_dir, stem + "_lut.mp4")

                self.stage.emit(f"正在转换 ({idx + 1}/{total})：{basename}")
                self.progress.emit(int(idx / total * 100))

                try:
                    use_full_lut = abs(self.intensity - 1.0) < 0.005

                    if use_full_lut:
                        # 完整 LUT，简单 -vf
                        cmd = [
                            ffmpeg, "-y", "-i", src,
                            "-vf", f"lut3d='{lut_esc}'",
                            *get_video_encode_args(crf=18, preset="superfast"),
                            "-c:a", "copy",
                            dst,
                        ]
                    else:
                        # 混合：原始画面 × (1-intensity) + LUT画面 × intensity
                        blend_expr = f"A*{1.0 - self.intensity:.4f}+B*{self.intensity:.4f}"
                        fc = (
                            f"[0:v]split[orig][forlut];"
                            f"[forlut]lut3d='{lut_esc}'[lutted];"
                            f"[orig][lutted]blend=all_expr='{blend_expr}'[out]"
                        )
                        cmd = [
                            ffmpeg, "-y", "-i", src,
                            "-filter_complex", fc,
                            "-map", "[out]", "-map", "0:a?",
                            *get_video_encode_args(crf=18, preset="superfast"),
                            "-c:a", "copy",
                            dst,
                        ]

                    creationflags = 0x08000000
                    r = subprocess.run(
                        cmd, capture_output=True, text=True,
                        creationflags=creationflags)

                    if r.returncode == 0:
                        success += 1
                        self.log_line.emit(f"✅ {basename} → {os.path.basename(dst)}")
                    else:
                        fail += 1
                        err_snippet = (r.stderr or r.stdout or "")[-300:]
                        self.log_line.emit(f"❌ {basename} 失败：{err_snippet}")
                        log.warning(f"LUT转换失败 {basename}: {r.stderr}")

                except Exception as e:
                    fail += 1
                    self.log_line.emit(f"❌ {basename} 异常：{e}")
                    log.exception(f"LUT转换异常 {basename}")

            self.progress.emit(100)
            self.stage.emit(
                f"批量 LUT 转换完成：成功 {success} 个，失败 {fail} 个")
            self.finished.emit(success, fail)

        except Exception:
            self.error.emit(traceback.format_exc())


# ─── Page ────────────────────────────────────────────────────────────────────

from gui.base_page import BasePage


class VideoLutPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._worker       = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── 标题 ────────────────────────────────────────────────────────────
        title = QLabel("🎨 批量 LUT 调色转换")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ecf0f1;")
        lay.addWidget(title)

        hint = QLabel(
            "选择视频文件夹和 LUT 文件，批量为所有视频应用 LUT 调色并导出为标准 H.264 MP4。\n"
            "支持 .cube / .3dl / .lut 格式的 LUT 文件。")
        hint.setStyleSheet("color: #aaa; font-size: 13px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ── 输入文件夹 ───────────────────────────────────────────────────────
        lay.addWidget(self._section("📁 视频输入文件夹"))
        row_in = QHBoxLayout()
        self.input_dir_edit = QLineEdit()
        self.input_dir_edit.setPlaceholderText("选择包含视频文件的文件夹…")
        self.input_dir_edit.textChanged.connect(self._on_input_changed)
        row_in.addWidget(self.input_dir_edit)
        btn_browse_in = QPushButton("选择文件夹")
        btn_browse_in.setFixedWidth(90)
        btn_browse_in.clicked.connect(self._browse_input)
        row_in.addWidget(btn_browse_in)
        lay.addLayout(row_in)

        self.lbl_found = QLabel("未扫描到视频文件")
        self.lbl_found.setStyleSheet("color: #aaa; font-size: 12px;")
        lay.addWidget(self.lbl_found)

        # ── LUT 文件 ────────────────────────────────────────────────────────
        lay.addWidget(self._section("🎨 LUT 文件"))
        row_lut = QHBoxLayout()
        self.lut_edit = QLineEdit()
        self.lut_edit.setPlaceholderText("选择 .cube / .3dl / .lut 文件…")
        row_lut.addWidget(self.lut_edit)
        btn_browse_lut = QPushButton("选择文件")
        btn_browse_lut.setFixedWidth(90)
        btn_browse_lut.clicked.connect(self._browse_lut)
        row_lut.addWidget(btn_browse_lut)
        lay.addLayout(row_lut)

        # ── 输出文件夹 ───────────────────────────────────────────────────────
        lay.addWidget(self._section("💾 输出文件夹"))
        row_out = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("默认：输入文件夹下的 lut_output 子目录")
        row_out.addWidget(self.output_dir_edit)
        btn_browse_out = QPushButton("选择文件夹")
        btn_browse_out.setFixedWidth(90)
        btn_browse_out.clicked.connect(self._browse_output)
        row_out.addWidget(btn_browse_out)
        lay.addLayout(row_out)

        # ── LUT 强度 ────────────────────────────────────────────────────────
        row_intensity = QHBoxLayout()
        row_intensity.addWidget(QLabel("LUT 强度:"))
        self.intensity_spin = QDoubleSpinBox()
        self.intensity_spin.setRange(0.0, 1.0)
        self.intensity_spin.setValue(1.0)
        self.intensity_spin.setSingleStep(0.05)
        self.intensity_spin.setDecimals(2)
        self.intensity_spin.setFixedWidth(70)
        self.intensity_spin.setToolTip(
            "1.0 = 完全应用 LUT\n0.0 = 完全不应用（原始画面）\n中间值为两者混合")
        row_intensity.addWidget(self.intensity_spin)
        row_intensity.addWidget(QLabel("（1.0 = 完整效果，0.5 = 半强度混合）"))
        row_intensity.addStretch()
        lay.addLayout(row_intensity)

        # ── 子文件夹选项 ──────────────────────────────────────────────────
        self.chk_recursive = QCheckBox("同时处理子文件夹中的视频")
        self.chk_recursive.setChecked(False)
        self.chk_recursive.setStyleSheet("color: #e5e7eb;")
        lay.addWidget(self.chk_recursive)

        # ── 开始按钮 ────────────────────────────────────────────────────────
        row_btn = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始批量 LUT 转换")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self._start)
        row_btn.addWidget(self.btn_start)
        self.btn_open_out = QPushButton("📂 打开输出目录")
        self.btn_open_out.setFixedHeight(40)
        self.btn_open_out.setEnabled(False)
        self.btn_open_out.clicked.connect(self._open_output)
        row_btn.addWidget(self.btn_open_out)
        lay.addLayout(row_btn)

        # ── 进度 ────────────────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        lay.addWidget(self.progress_bar)

        self.stage_label = QLabel("")
        self.stage_label.setStyleSheet("color: #aaa; font-size: 12px;")
        lay.addWidget(self.stage_label)

        # ── 日志 ────────────────────────────────────────────────────────────
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(220)
        self.log_box.setStyleSheet(
            "background: #1a1a2e; color: #c8d6e5; font-size: 12px; border-radius: 6px;")
        lay.addWidget(self.log_box)

        lay.addStretch()

    # ── 辅助 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _section(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #e5e7eb; margin-top: 4px;")
        return lbl

    def _browse_input(self):
        d = QFileDialog.getExistingDirectory(
            self.parent_widget, "选择视频输入文件夹",
            self.input_dir_edit.text() or "")
        if d:
            self.input_dir_edit.setText(d)

    def _browse_lut(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择 LUT 文件", "",
            "LUT 文件 (*.cube *.3dl *.lut *.m3d *.dat);;所有文件 (*.*)")
        if path:
            self.lut_edit.setText(path)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(
            self.parent_widget, "选择输出文件夹",
            self.output_dir_edit.text() or "")
        if d:
            self.output_dir_edit.setText(d)

    def _on_input_changed(self, text):
        """扫描输入文件夹，实时显示找到的视频数量，并自动填写输出路径。"""
        text = text.strip()
        if not text or not os.path.isdir(text):
            self.lbl_found.setText("未扫描到视频文件")
            return
        files = self._collect_videos(text)
        self.lbl_found.setText(f"找到 {len(files)} 个视频文件")
        if not self.output_dir_edit.text().strip():
            self.output_dir_edit.setText(os.path.join(text, "lut_output"))

    def _collect_videos(self, folder):
        recursive = self.chk_recursive.isChecked()
        result = []
        if recursive:
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(VIDEO_EXTS):
                        result.append(os.path.join(root, f))
        else:
            try:
                for f in os.listdir(folder):
                    if f.lower().endswith(VIDEO_EXTS):
                        result.append(os.path.join(folder, f))
            except Exception:
                pass
        result.sort()
        return result

    def _open_output(self):
        out = self.output_dir_edit.text().strip()
        if out and os.path.isdir(out):
            os.startfile(out)

    # ── 开始转换 ─────────────────────────────────────────────────────────────

    def _start(self):
        if self._worker and self._worker.isRunning():
            return

        in_dir  = self.input_dir_edit.text().strip()
        lut     = self.lut_edit.text().strip()
        out_dir = self.output_dir_edit.text().strip()

        if not in_dir or not os.path.isdir(in_dir):
            self._log("❗ 请先选择有效的视频输入文件夹")
            return
        if not lut or not os.path.isfile(lut):
            self._log("❗ 请先选择有效的 LUT 文件")
            return

        videos = self._collect_videos(in_dir)
        if not videos:
            self._log("❗ 输入文件夹中未找到视频文件")
            return

        if not out_dir:
            out_dir = os.path.join(in_dir, "lut_output")
            self.output_dir_edit.setText(out_dir)

        intensity = self.intensity_spin.value()

        self.log_box.clear()
        self._log(f"LUT 文件：{os.path.basename(lut)}")
        self._log(f"强度：{intensity:.2f}   视频数：{len(videos)}   输出：{out_dir}")
        self._log("─" * 50)

        self.btn_start.setEnabled(False)
        self.btn_open_out.setEnabled(False)
        self.progress_bar.setValue(0)

        self._worker = VideoLutWorker(videos, lut, out_dir, intensity)
        self._worker.stage.connect(self._on_stage)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.log_line.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stage(self, msg):
        self.stage_label.setText(msg)

    def _on_finished(self, success, fail):
        self.btn_start.setEnabled(True)
        self.btn_open_out.setEnabled(True)
        self._log("─" * 50)
        self._log(f"✅ 完成！成功 {success} 个，失败 {fail} 个")
        self.stage_label.setText(f"完成：成功 {success} 个，失败 {fail} 个")

    def _on_error(self, msg):
        self.btn_start.setEnabled(True)
        self._log(f"❌ 发生严重错误：\n{msg}")
        self.stage_label.setText("发生错误，请查看日志")

    def _log(self, text):
        self.log_box.append(text)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())
