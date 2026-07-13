# -*- coding: utf-8 -*-
import os
import traceback
import sys

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame,
                               QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
                               QWidget)
from PySide6.QtCore import Signal, Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QAction
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from config.paths import TMP_DIR, OUTPUTS_DIR
from gui.base_page import BasePage


# ── 支持的文件类型 ──
SUPPORTED_EXTS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v",
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma",
})


class TranscriptionToolPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.files = []  # [{"path": str, "size": int, "status": str, "srt_text": str, "preview": str}, ...]

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(12)

        heading = QLabel("🎙️ 音频/视频转文字")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        # ── 顶部控制区 ──
        ctrl_card = QFrame()
        ctrl_card.setObjectName("card")
        ctrl_lay = QVBoxLayout(ctrl_card)
        ctrl_lay.setContentsMargins(24, 20, 24, 20)
        ctrl_lay.setSpacing(12)

        # 第一行：添加文件 + 配置
        row1 = QHBoxLayout()
        btn_add = mdi_button("添加文件", "plus")
        btn_add.setObjectName("secondary_button")
        btn_add.clicked.connect(self._add_files)
        row1.addWidget(btn_add)

        row1.addWidget(QLabel("  语言:"))
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("zh/en/空则自动")
        self.lang_input.setMaximumWidth(120)
        row1.addWidget(self.lang_input)

        row1.addWidget(QLabel("任务:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(["转写（原语言）", "翻译为英文"])
        self.task_combo.setMaximumWidth(140)
        row1.addWidget(self.task_combo)

        self.multi_speaker_check = QCheckBox("👥 多人模式")
        row1.addWidget(self.multi_speaker_check)
        row1.addStretch()
        ctrl_lay.addLayout(row1)

        layout.addWidget(ctrl_card, 0)

        # ── 文件列表 ──
        list_card = QFrame()
        list_card.setObjectName("card")
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(24, 20, 24, 20)

        list_lay.addWidget(QLabel("文件列表（双击预览列查看全文保存，或点操作列💾按钮）："))

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "文件大小", "状态", "结果预览", "操作"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.file_table.setColumnWidth(0, 350)
        self.file_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.doubleClicked.connect(self._on_table_double_click)
        self.file_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._on_context_menu)
        list_lay.addWidget(self.file_table, 1)

        self.stage_label = QLabel("就绪")
        self.stage_label.setObjectName("muted_text")
        list_lay.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        list_lay.addWidget(self.progress_bar)

        btn_process = mdi_button("开始处理", "play")
        btn_process.setObjectName("action_button")
        btn_process.setFixedHeight(40)
        btn_process.clicked.connect(self._start_batch)
        self.btn_process = btn_process
        list_lay.addWidget(btn_process)

        layout.addWidget(list_card, 1)

        # ── 播放器（隐藏） ──
        self._player = QMediaPlayer()
        self._video_widget = QVideoWidget()
        self._video_widget.setWindowTitle("播放")
        self._video_widget.resize(640, 480)

    # ══════════════════════════════════════════
    #  文件管理
    # ══════════════════════════════════════════

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget, "选择文件", "",
            "Media Files (*.mp4 *.mov *.avi *.mkv *.mp3 *.wav *.m4a *.flac *.aac *.ogg);;All Files (*)"
        )
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue
            # 去重
            if any(f["path"] == p for f in self.files):
                continue
            try:
                fsize = os.path.getsize(p)
            except Exception:
                fsize = 0
            self.files.append({"path": p, "size": fsize, "status": "等待处理", "srt_text": "", "preview": ""})
            self._insert_file_row(len(self.files) - 1)

    def _insert_file_row(self, idx):
        row = self.file_table.rowCount()
        self.file_table.insertRow(row)
        f = self.files[idx]
        name = os.path.basename(f["path"])
        self.file_table.setItem(row, 0, QTableWidgetItem(name))
        size_text = f"{f['size'] / 1048576:.1f} MB" if f['size'] > 0 else ""
        self.file_table.setItem(row, 1, QTableWidgetItem(size_text))
        self.file_table.setItem(row, 2, QTableWidgetItem(f["status"]))
        self.file_table.setItem(row, 3, QTableWidgetItem(f["preview"]))
        self._set_save_button(row, f)
        self._apply_row_color(row, f["status"])

    def _refresh_file_row(self, idx):
        f = self.files[idx]
        name = os.path.basename(f["path"])
        self.file_table.item(idx, 0).setText(name)
        size_text = f"{f['size'] / 1048576:.1f} MB" if f['size'] > 0 else ""
        self.file_table.item(idx, 1).setText(size_text)
        self.file_table.item(idx, 2).setText(f["status"])
        self.file_table.item(idx, 3).setText(f["preview"])
        self._set_save_button(idx, f)
        self._apply_row_color(idx, f["status"])

    def _set_save_button(self, row, f):
        # 清除旧的按钮
        old = self.file_table.cellWidget(row, 4)
        if old:
            old.deleteLater()
            self.file_table.removeCellWidget(row, 4)
        # 已完成才显示保存按钮
        if f["status"] == "✅ 完成" and f["srt_text"]:
            btn = QPushButton("💾 保存")
            btn.setObjectName("secondary_button")
            btn.setStyleSheet("padding: 2px 8px; font-size: 12px;")
            btn.clicked.connect(lambda r=row: self._show_save_dialog(r))
            self.file_table.setCellWidget(row, 4, btn)

    def _apply_row_color(self, row, status):
        from PySide6.QtGui import QColor
        colors = {
            "等待处理": QColor(60, 60, 70),
            "⏳ 处理中": QColor(80, 70, 30),
            "✅ 完成":   QColor(30, 70, 40),
            "❌ 失败":   QColor(70, 35, 35),
        }
        bg = colors.get(status)
        if bg:
            for c in range(self.file_table.columnCount()):
                item = self.file_table.item(row, c)
                if item:
                    item.setBackground(bg)

    def _remove_file(self, idx):
        if 0 <= idx < len(self.files):
            self.files.pop(idx)
            self.file_table.removeRow(idx)

    def _on_context_menu(self, pos):
        idx = self.file_table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        menu = self.file_table.createStandardContextMenu()
        menu.addSeparator()
        act = QAction("从列表移除", self.parent_widget)
        act.triggered.connect(lambda r=row: self._remove_file(r))
        menu.addAction(act)
        menu.exec(self.file_table.viewport().mapToGlobal(pos))

    def _on_table_double_click(self, index):
        if not index.isValid():
            return
        row = index.row()
        col = index.column()
        f = self.files[row]

        # 已完成且在结果列(2-3) → 保存对话框
        if f["status"] == "✅ 完成" and f["srt_text"] and col >= 2:
            self._show_save_dialog(row)
            return

        # 否则播放文件
        self._play_file(f["path"])

    def _play_file(self, path):
        if not os.path.isfile(path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"文件不存在:\n{path}")
            return
        url = QUrl.fromLocalFile(path)
        self._player.setSource(url)
        self._video_widget.show()
        self._player.setVideoOutput(self._video_widget)
        self._player.play()

    # ══════════════════════════════════════════
    #  保存对话框
    # ══════════════════════════════════════════

    def _show_save_dialog(self, row):
        f = self.files[row]
        base = os.path.splitext(f["path"])[0]
        basename = os.path.basename(base)

        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("保存字幕")
        dlg.resize(640, 480)
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel(f"文件：{os.path.basename(f['path'])}"))

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("字幕格式:"))
        fmt_combo = QComboBox()
        fmt_combo.addItem("SRT 字幕文件 (*.srt)", "srt")
        fmt_combo.addItem("WebVTT 字幕文件 (*.vtt)", "vtt")
        fmt_combo.addItem("TXT 带有时间戳 (*.txt)", "txt")
        fmt_combo.addItem("TXT 纯文本 (*.txt)", "plain")
        fmt_row.addWidget(fmt_combo)
        fmt_row.addStretch()
        lay.addLayout(fmt_row)

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlaceholderText("选择格式后预览...")
        lay.addWidget(preview, 1)

        def _update_preview():
            text = self._convert_format(f["srt_text"], fmt_combo.currentData())
            preview.setPlainText(text)

        fmt_combo.currentIndexChanged.connect(_update_preview)
        _update_preview()

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        lay.addWidget(btn_box)

        if dlg.exec() != QDialog.Accepted:
            return

        fmt = fmt_combo.currentData()
        ext = "txt" if fmt in ("txt", "plain") else fmt
        full_text = self._convert_format(f["srt_text"], fmt)

        default_path = f"{base}.{ext}"
        save_path, _ = QFileDialog.getSaveFileName(
            dlg, "保存字幕", default_path,
            f"{ext.upper()} Files (*.{ext});;All Files (*)"
        )
        if save_path:
            try:
                with open(save_path, "w", encoding="utf-8") as fp:
                    fp.write(full_text)
                QMessageBox.information(dlg, "已保存", f"字幕已保存:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(dlg, "保存失败", str(e))

    @staticmethod
    def _convert_format(srt_text: str, fmt: str) -> str:
        """将 SRT 格式文本转换为指定格式。"""
        if fmt == "srt":
            return srt_text
        lines = []
        for seg in srt_text.split("\n\n"):
            seg = seg.strip()
            if not seg:
                continue
            parts = seg.split("\n")
            if len(parts) >= 3:
                idx = parts[0]
                time_line = parts[1]
                text = parts[2]
                if fmt == "vtt":
                    lines.append(idx)
                    lines.append(time_line.replace(",", "."))
                    lines.append(text)
                    lines.append("")
                elif fmt == "txt":
                    lines.append(f"[{time_line.split('-->')[0].strip()}] {text}")
                elif fmt == "plain":
                    lines.append(text)
        if fmt == "vtt":
            return "WEBVTT\n\n" + "\n".join(lines)
        return "\n".join(lines)

    # ══════════════════════════════════════════
    #  批量处理
    # ══════════════════════════════════════════

    def _start_batch(self):
        if self.worker and self.worker.isRunning():
            return

        pending = [i for i, f in enumerate(self.files) if f["status"] == "等待处理" or f["status"] == "❌ 失败"]
        if not pending:
            QMessageBox.warning(self.parent_widget, "无待处理文件", "没有待处理的文件。请先添加文件。")
            return

        language = self.lang_input.text().strip() or None
        task_type = "translate" if "翻译" in self.task_combo.currentText() else "transcribe"
        diarize = self.multi_speaker_check.isChecked()

        self.btn_process.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(pending))
        self.progress_bar.setValue(0)
        self._current_pending = pending
        self._current_index = 0

        self._process_next(language, task_type, diarize)

    def _process_next(self, language, task_type, diarize):
        if self._current_index >= len(self._current_pending):
            self.btn_process.setEnabled(True)
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.stage_label.setText("✅ 全部处理完成")
            return

        idx = self._current_pending[self._current_index]
        f = self.files[idx]
        f["status"] = "⏳ 处理中"
        self._refresh_file_row(idx)
        self.stage_label.setText(f"正在处理: {os.path.basename(f['path'])}")
        self.progress_bar.setValue(self._current_index)

        from utils.asr_client import transcribe_remote, read_asr_url

        class BatchWorker(BaseWorker):
            finished = Signal(int, str)  # file_list_index, srt_text
            error = Signal(int, str)

            def __init__(self, file_idx, path, language, task_type, diarize):
                super().__init__()
                self.file_idx = file_idx
                self.path = path
                self.language = language
                self.task_type = task_type
                self.diarize = diarize

            def do_work(self):
                try:
                    asr_url = read_asr_url()
                    segments = transcribe_remote(
                        self.path, asr_url,
                        language=self.language, task_type=self.task_type,
                        diarize=self.diarize,
                    )
                    # 生成 SRT
                    lines = []
                    for i, seg in enumerate(segments):
                        start = seg.get("start", 0)
                        end = seg.get("end", 0)
                        text = seg.get("text", "").strip().replace("\n", " ")
                        lines.append(f"{i+1}")
                        lines.append(
                            f"{int(start//3600):02d}:{int(start%3600//60):02d}:{start%60:06.3f} --> "
                            f"{int(end//3600):02d}:{int(end%3600//60):02d}:{end%60:06.3f}"
                        )
                        lines.append(text)
                        lines.append("")
                    srt_text = "\n".join(lines)
                    self.finished.emit(self.file_idx, srt_text)
                except Exception as e:
                    self.error.emit(self.file_idx, str(e))

        self.worker = BatchWorker(idx, f["path"], language, task_type, diarize)
        self.worker.finished.connect(self._on_file_done)
        self.worker.error.connect(self._on_file_error)
        self.worker.start()

    def _on_file_done(self, file_idx, srt_text):
        f = self.files[file_idx]
        f["status"] = "✅ 完成"
        f["srt_text"] = srt_text
        # 预览：取第一段文字的前 50 字
        preview = ""
        for seg in srt_text.split("\n\n"):
            seg = seg.strip()
            if seg:
                parts = seg.split("\n")
                if len(parts) >= 3:
                    preview = parts[2][:50]
                    break
        f["preview"] = preview
        self._refresh_file_row(file_idx)

        self._current_index += 1
        language = self.lang_input.text().strip() or None
        task_type = "translate" if "翻译" in self.task_combo.currentText() else "transcribe"
        diarize = self.multi_speaker_check.isChecked()
        self._process_next(language, task_type, diarize)

    def _on_file_error(self, file_idx, err):
        f = self.files[file_idx]
        f["status"] = "❌ 失败"
        f["preview"] = ""
        self._refresh_file_row(file_idx)

        summary = ""
        for line in (err or "").splitlines()[::-1]:
            if line.strip():
                summary = line.strip()
                break
        msg = f"❌ 处理失败: {os.path.basename(f['path'])}"
        if summary:
            msg += f"\n错误摘要：{summary}"
        QMessageBox.critical(self.parent_widget, "处理失败", msg)

        self._current_index += 1
        language = self.lang_input.text().strip() or None
        task_type = "translate" if "翻译" in self.task_combo.currentText() else "transcribe"
        diarize = self.multi_speaker_check.isChecked()
        self._process_next(language, task_type, diarize)
