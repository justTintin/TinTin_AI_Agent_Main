# -*- coding: utf-8 -*-
import os
import re
import html
import traceback
import sys

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame,
                               QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
                               QWidget, QTextEdit, QTextBrowser, QSplitter, QApplication)
from PySide6.QtCore import Signal, Qt, QUrl, QTimer, QObject, QEvent
from PySide6.QtGui import (QDesktopServices, QAction, QColor, QTextCharFormat, QTextCursor,
                           QBrush, QTextFormat)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button, table_action_button
from utils.logger_utils import log
from config.paths import TMP_DIR, OUTPUTS_DIR
from gui.base_page import BasePage


# ── 支持的文件类型 ──
SUPPORTED_EXTS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v",
    ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma",
})


class _SpaceFilter(QObject):
    """全局空格键过滤器：仅当转写页可见且焦点在本页内时，用空格切换 播放/字幕编辑 模式。

    必须是 QObject 子类才能 installEventFilter（参考 terminal_page._HistoryFilter）。
    """
    def __init__(self, page):
        super().__init__(page.parent_widget)  # 与页面控件同生命周期
        self._page = page

    def eventFilter(self, obj, event):
        page = self._page
        if (event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space
                and not event.isAutoRepeat()):
            if not page.parent_widget.isVisible():
                return False
            fw = QApplication.focusWidget()
            if fw is not None and not page.parent_widget.isAncestorOf(fw):
                return False  # 焦点在其他页面，不干预
            # 文本输入框（语言框等）里空格正常输入；字幕编辑框内空格用于退出编辑
            if fw is not None and fw is not page.subtitle_editor \
                    and isinstance(fw, (QLineEdit, QComboBox)):
                return False
            page._toggle_edit_mode()
            return True
        return False


class TranscriptionToolPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.files = []  # [{"path": str, "size": int, "status": str, "srt_text": str, "preview": str}, ...]
        self._edit_mode = False      # 字幕编辑模式（空格切换）
        self._edit_file_row = -1     # 正在编辑的文件行号

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

        btn_process = mdi_button("开始处理", "play")
        btn_process.setObjectName("action_button")
        btn_process.setFixedHeight(34)
        btn_process.clicked.connect(self._start_batch)
        self.btn_process = btn_process
        row1.addWidget(btn_process)

        row1.addStretch()
        ctrl_lay.addLayout(row1)

        layout.addWidget(ctrl_card, 0)

        # ── 主体区域：左（文件列表 + 字幕文本） / 右（视频播放器） ──
        splitter = QSplitter(Qt.Horizontal)

        # 左侧面板：文件列表在上，字幕文本在下
        left_panel = QWidget()
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        # 文件表格（紧凑显示）
        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(["文件名", "大小", "状态", "操作"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.file_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setMaximumHeight(200)
        self.file_table.doubleClicked.connect(self._on_table_double_click)
        self.file_table.itemSelectionChanged.connect(self._on_file_selection_changed)
        self.file_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._on_context_menu)
        left_lay.addWidget(self.file_table)

        # 字幕文本区（显示选中文件的全文字幕，支持字级点击跳转）
        self.subtitle_editor = QTextBrowser()
        self.subtitle_editor.setOpenExternalLinks(False)
        self.subtitle_editor.setOpenLinks(False)  # 只发 anchorClicked，不导航（否则点击字锚点会清空文档）
        self.subtitle_editor.setPlaceholderText("选中已完成转写的文件，此处显示完整字幕；点击字幕跳转到对应位置播放；空格键暂停并编辑字幕（修改自动保存）…")
        self.subtitle_editor.anchorClicked.connect(self._on_word_clicked)
        left_lay.addWidget(self.subtitle_editor, 1)
        self._highlight_word_key = None  # 当前高亮的 word 锚点 key，避免每帧重绘
        self._highlight_seg = None       # 当前高亮的段索引（淡蓝背景）

        splitter.addWidget(left_panel)

        # 右侧面板：视频播放器
        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(0, 0, 0, 0)

        self._video_widget = QVideoWidget()
        self._video_widget.setMinimumSize(320, 240)
        self._video_widget.setStyleSheet("background: #000;")
        right_lay.addWidget(self._video_widget, 1)

        # 播放控件
        play_row = QHBoxLayout()
        self.btn_play_prev = QPushButton("⏮")
        self.btn_play_prev.clicked.connect(self._play_prev_file)
        play_row.addWidget(self.btn_play_prev)
        self.btn_play_toggle = QPushButton("⏸")
        self.btn_play_toggle.clicked.connect(self._toggle_play)
        play_row.addWidget(self.btn_play_toggle)
        self.btn_play_next = QPushButton("⏭")
        self.btn_play_next.clicked.connect(self._play_next_file)
        play_row.addWidget(self.btn_play_next)
        play_row.addStretch()
        self._play_time_label = QLabel("00:00 / 00:00")
        play_row.addWidget(self._play_time_label)
        right_lay.addLayout(play_row)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter, 1)

        # ── 底部状态行：处理阶段 + 进度条 ──
        bottom_row = QHBoxLayout()
        self.stage_label = QLabel("")
        self.stage_label.setObjectName("muted_text")
        bottom_row.addWidget(self.stage_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(200)
        bottom_row.addWidget(self.progress_bar)
        layout.addLayout(bottom_row)

        # ── 播放器 ──
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()  # Qt6 必须显式设置音频输出，否则无声
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.positionChanged.connect(self._update_play_time)

        # 空格键：暂停并进入字幕编辑模式 / 保存并回到播放模式
        self._space_filter = _SpaceFilter(self)
        QApplication.instance().installEventFilter(self._space_filter)

        # 编辑实时保存（防抖：停止输入 600ms 后落盘到视频旁的 .srt）
        self._edit_save_timer = QTimer(self.parent_widget)
        self._edit_save_timer.setSingleShot(True)
        self._edit_save_timer.setInterval(600)
        self._edit_save_timer.timeout.connect(self._on_live_edit)
        self.subtitle_editor.textChanged.connect(self._edit_save_timer.start)

    # ══════════════════════════════════════════
    #  右侧播放控制
    # ══════════════════════════════════════════

    def _on_file_selection_changed(self):
        """选中表格行时，更新左侧字幕文本和右侧视频。"""
        if self._edit_mode:
            self._exit_edit_mode(resume=False)  # 切换文件前先把当前编辑落盘
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self.files):
            return
        f = self.files[row]
        # 更新字幕区：优先用 segments 渲染字级可点击字幕，否则回退纯文本
        self._highlight_word_key = None
        self._highlight_seg = None
        self.subtitle_editor.setExtraSelections([])
        if f.get("segments"):
            self._render_subtitle_html(f["segments"])
        elif f["srt_text"]:
            self.subtitle_editor.setPlainText(
                self._convert_format(f["srt_text"], "srt"))
        else:
            self.subtitle_editor.clear()
        # 播放视频
        self._play_file(f["path"])

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self.btn_play_toggle.setText("▶")
        else:
            self._player.play()
            self.btn_play_toggle.setText("⏸")

    def _play_prev_file(self):
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row() - 1
        if row < 0:
            row = len(self.files) - 1
        self.file_table.selectRow(row)

    def _play_next_file(self):
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row() + 1
        if row >= len(self.files):
            row = 0
        self.file_table.selectRow(row)

    def _update_play_time(self, pos):
        dur = self._player.duration()
        if dur > 0:
            pos_str = f"{pos // 60000:02d}:{(pos % 60000) // 1000:02d}"
            dur_str = f"{dur // 60000:02d}:{(dur % 60000) // 1000:02d}"
            self._play_time_label.setText(f"{pos_str} / {dur_str}")
        # 卡拉OK 式高亮：根据播放位置高亮当前字
        self._highlight_current_word(pos)

    # ══════════════════════════════════════════
    #  字级对齐：渲染 / 点击跳转 / 播放高亮
    # ══════════════════════════════════════════

    @staticmethod
    def _fmt_srt_time(sec: float) -> str:
        """秒 → SRT 时间戳 HH:MM:SS,mmm"""
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _render_subtitle_html(self, segments):
        """把 segments 渲染为 SRT 样式分段（序号/时间戳/正文）+ 可点击锚点。

        时间戳行是句级锚点 href=s{段}（点击跳到段首）；
        有 words 的段正文逐字锚点 href=w{段}_{字}（点击跳到该字）；
        被用户修改过的段（seg["edited"]）正文加下划线标识。
        """
        parts = ['<div style="font-size:14px;color:#d1d5db;line-height:1.8;">']
        for si, seg in enumerate(segments or []):
            start = float(seg.get("start", 0) or 0)
            end = float(seg.get("end", 0) or 0)
            time_line = f"{self._fmt_srt_time(start)} --> {self._fmt_srt_time(end)}"
            # 修改过的段：正文下划线 + 淡蓝文字标识
            edited = bool(seg.get("edited"))
            a_style = ("color:#93c5fd;text-decoration:underline;" if edited
                       else "color:#d1d5db;text-decoration:none;")
            words = seg.get("words") or []
            if words:
                spans = []
                for wi, w in enumerate(words):
                    txt = html.escape(str(w.get("word", "")))
                    href = f"w{si}_{wi}"
                    spans.append(f'<a href="{href}" style="{a_style}">{txt}</a>')
                text_html = "".join(spans)
            else:
                txt = html.escape(str(seg.get("text", "")).strip())
                if not txt:
                    continue
                text_html = f'<a href="s{si}" style="{a_style}">{txt}</a>'
            parts.append(
                f'<p style="margin:10px 0;">'
                f'<a href="s{si}" style="color:#6b7280;text-decoration:none;'
                f'font-family:Consolas,monospace;font-size:12px;">{si + 1}&nbsp;&nbsp;{time_line}</a>'
                f'<br>{text_html}</p>')
        parts.append('</div>')
        self.subtitle_editor.setHtml("\n".join(parts))
        self.subtitle_editor.clearFocus()  # 避免选中高亮干扰

    def _on_word_clicked(self, url):
        """点击字幕中的字/句：跳转视频到该时间戳并播放。"""
        if self._edit_mode:
            return  # 编辑状态下点击是定位光标，不做跳转
        anchor = url.toString() if hasattr(url, "toString") else str(url)
        if not anchor:
            return
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        f = self.files[rows[0].row()]
        segments = f.get("segments") or []
        start = None
        if anchor.startswith("w"):
            # 字级：w{si}_{wi}
            try:
                _, idx = anchor.split("w", 1)
                si_str, wi_str = idx.split("_", 1)
                si, wi = int(si_str), int(wi_str)
                words = segments[si].get("words") or []
                start = float(words[wi].get("start", 0))
            except (ValueError, IndexError, KeyError, TypeError):
                start = None
        elif anchor.startswith("s"):
            # 句子级：s{si}
            try:
                si = int(anchor[1:])
                start = float(segments[si].get("start", 0))
            except (ValueError, IndexError, KeyError, TypeError):
                start = None
        if start is None:
            return
        # 确保播放的是当前文件，再 seek + play（QMediaPlayer 用毫秒）
        self._ensure_playing_file(f["path"])
        self._player.setPosition(int(start * 1000))
        self._player.play()
        self.btn_play_toggle.setText("⏸")
        # 立即高亮被点击的位置（不等下一帧 positionChanged）
        try:
            si = int(anchor.split("_")[0][1:])
        except (ValueError, IndexError):
            si = None
        self._highlight_word_key = anchor if anchor.startswith("w") else None
        self._highlight_seg = si
        self._refresh_highlights()

    def _ensure_playing_file(self, path):
        """确保播放器加载的是指定文件（点击字幕时可能源未切换）。"""
        if not os.path.isfile(path):
            return
        cur = self._player.source()
        want = QUrl.fromLocalFile(path)
        if cur.isEmpty() or cur.toLocalFile() != path:
            self._player.stop()
            self._player.setSource(want)
            self._player.setVideoOutput(self._video_widget)

    def _highlight_current_word(self, pos_ms):
        """根据播放位置高亮：当前段整体淡蓝背景 + 当前字黄色（卡拉OK 跟随）。

        用 ExtraSelections 上色（不改文档内容），且仅在目标变化时刷新。
        """
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        f = self.files[rows[0].row()]
        segments = f.get("segments") or []
        if not segments:
            return
        cur_sec = pos_ms / 1000.0
        # 先定位当前段，再在段内定位当前字
        target_seg = None
        target_key = None
        for si, seg in enumerate(segments):
            ss = float(seg.get("start", 0))
            se = float(seg.get("end", 0))
            if ss <= cur_sec < max(se, ss + 0.01):
                target_seg = si
                for wi, w in enumerate(seg.get("words") or []):
                    ws = float(w.get("start", 0))
                    we = float(w.get("end", 0))
                    if ws <= cur_sec < max(we, ws + 0.01):
                        target_key = f"w{si}_{wi}"
                        break
                break
        # 仅在目标变化时重绘，避免每帧刷新
        if target_seg == self._highlight_seg and target_key == self._highlight_word_key:
            return
        self._highlight_seg = target_seg
        self._highlight_word_key = target_key
        self._refresh_highlights()

    def _find_href_range(self, href):
        """定位指定 anchorHref 在文档中的连续字符区间，返回 (start, end)；未找到返回 (None, None)。"""
        doc = self.subtitle_editor.document()
        n = doc.characterCount()
        run_start = -1
        end_pos = -1
        cur = QTextCursor(doc)
        i = 0
        while i < n:
            cur.setPosition(i)
            if cur.charFormat().anchorHref() == href:
                if run_start < 0:
                    run_start = i
                end_pos = i + 1
            elif run_start >= 0:
                break
            i += 1
        if run_start < 0:
            return None, None
        return run_start, end_pos

    def _refresh_highlights(self):
        """按当前状态刷新高亮：当前段淡蓝背景（底层）+ 当前字黄色（上层）。"""
        sels = []
        doc = self.subtitle_editor.document()
        # 当前段：淡蓝色整段背景（全宽，从本段时间戳行到下一段开始）
        if self._highlight_seg is not None:
            seg_start, _ = self._find_href_range(f"s{self._highlight_seg}")
            next_start, _ = self._find_href_range(f"s{self._highlight_seg + 1}")
            if seg_start is not None:
                seg_end = next_start if next_start is not None else doc.characterCount() - 1
                seg_sel = QTextEdit.ExtraSelection()
                seg_sel.format.setBackground(QBrush(QColor("#d6e9ff")))  # 淡蓝
                seg_sel.format.setForeground(QBrush(QColor("#1a1a1a")))
                seg_sel.format.setProperty(QTextFormat.FullWidthSelection, True)  # 整段全宽背景
                seg_sel.cursor = QTextCursor(doc)
                seg_sel.cursor.setPosition(seg_start)
                seg_sel.cursor.setPosition(seg_end, QTextCursor.KeepAnchor)
                sels.append(seg_sel)
        # 当前字：黄色背景
        if self._highlight_word_key:
            ws, we = self._find_href_range(self._highlight_word_key)
            if ws is not None:
                word_sel = QTextEdit.ExtraSelection()
                word_sel.format.setBackground(QBrush(QColor("#f9c74f")))
                word_sel.format.setForeground(QBrush(QColor("#1a1a1a")))
                word_sel.cursor = QTextCursor(doc)
                word_sel.cursor.setPosition(ws)
                word_sel.cursor.setPosition(we, QTextCursor.KeepAnchor)
                sels.append(word_sel)
        self.subtitle_editor.setExtraSelections(sels)

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
            entry = {"path": p, "size": fsize, "status": "等待处理",
                     "srt_text": "", "preview": "", "segments": []}
            # 闭环：视频旁已有 .srt（此前转写/手动修订过）→ 直接加载，无需重复转写
            sidecar = os.path.splitext(p)[0] + ".srt"
            if os.path.isfile(sidecar):
                try:
                    with open(sidecar, "r", encoding="utf-8") as fp:
                        srt_text = fp.read()
                    segs = self._parse_srt(srt_text)
                    if segs:
                        entry.update(status="✅ 完成", srt_text=srt_text, segments=segs)
                        log.info(f"[转写] 检测到已有字幕，直接加载: {sidecar}")
                except Exception as e:
                    log.error(f"[转写] 读取已有字幕失败 {sidecar}: {e}")
            self.files.append(entry)
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
        self._set_action_buttons(row, f)
        self._apply_row_color(row, f["status"])

    def _refresh_file_row(self, idx):
        f = self.files[idx]
        name = os.path.basename(f["path"])
        self.file_table.item(idx, 0).setText(name)
        size_text = f"{f['size'] / 1048576:.1f} MB" if f['size'] > 0 else ""
        self.file_table.item(idx, 1).setText(size_text)
        self.file_table.item(idx, 2).setText(f["status"])
        self._set_action_buttons(idx, f)
        self._apply_row_color(idx, f["status"])

    def _set_action_buttons(self, row, f):
        # 清除旧的按钮
        old = self.file_table.cellWidget(row, 3)
        if old:
            old.deleteLater()
            self.file_table.removeCellWidget(row, 3)
        # 已完成才显示按钮
        if f["status"] == "✅ 完成" and f["srt_text"]:
            btn = table_action_button("💾", "导出 SRT 字幕")
            btn.clicked.connect(lambda r=row: self._show_save_dialog(r))
            self.file_table.setCellWidget(row, 3, btn)

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
        if 0 <= row < len(self.files) and self.files[row]["status"] == "✅ 完成":
            act_retry = QAction("🔄 重新转写", self.parent_widget)
            act_retry.triggered.connect(lambda r=row: self._retry_transcribe(r))
            menu.addAction(act_retry)
        act = QAction("从列表移除", self.parent_widget)
        act.triggered.connect(lambda r=row: self._remove_file(r))
        menu.addAction(act)
        menu.exec(self.file_table.viewport().mapToGlobal(pos))

    def _retry_transcribe(self, idx):
        """把已完成文件重置为待处理，允许重新生成字幕。"""
        if 0 <= idx < len(self.files):
            f = self.files[idx]
            f["status"] = "等待处理"
            f.pop("orig_segments", None)  # 重新转写后修改标记按新结果重算
            self._refresh_file_row(idx)
            self.stage_label.setText(f"已重置为待处理: {os.path.basename(f['path'])}（点击「开始处理」重新转写）")

    def _on_table_double_click(self, index):
        if not index.isValid():
            return
        row = index.row()
        f = self.files[row]

        # 已完成且有关键结果 → 保存对话框（不管是点哪列）
        if f["status"] == "✅ 完成" and f["srt_text"]:
            self._show_save_dialog(row)
            return

        # 否则播放文件
        self._play_file(f["path"])

    # ══════════════════════════════════════════
    #  字幕编辑模式（空格切换）
    # ══════════════════════════════════════════

    def _toggle_edit_mode(self):
        if self._edit_mode:
            self._exit_edit_mode(resume=True)
        else:
            self._enter_edit_mode()

    def _enter_edit_mode(self):
        rows = self.file_table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self.files):
            return
        f = self.files[row]
        if not f["srt_text"]:
            self.stage_label.setText("该文件还没有字幕，无法编辑")
            return
        self._edit_mode = True
        self._edit_file_row = row
        self._player.pause()
        self.btn_play_toggle.setText("▶")
        # 原地编辑：不替换内容（与播放态同一渲染），格式不跳动、滚动位置不变
        self.subtitle_editor.setExtraSelections([])
        self.subtitle_editor.setReadOnly(False)
        self.subtitle_editor.setFocus()
        self.stage_label.setText("✏️ 字幕编辑中（修改自动保存，再按空格回到播放）")

    def _exit_edit_mode(self, resume=True):
        row = self._edit_file_row
        self._edit_mode = False
        self.subtitle_editor.setReadOnly(True)
        if 0 <= row < len(self.files):
            f = self.files[row]
            self._apply_edits(f, self.subtitle_editor.toPlainText())
            # 仍是当前行则立即重渲染（切走时由选择变更处理），并保持滚动位置
            if self.file_table.currentRow() == row:
                vsb = self.subtitle_editor.verticalScrollBar()
                scroll = vsb.value()
                self._highlight_word_key = None
                self._highlight_seg = None
                self.subtitle_editor.setExtraSelections([])
                if f.get("segments"):
                    self._render_subtitle_html(f["segments"])
                elif f["srt_text"]:
                    self.subtitle_editor.setPlainText(f["srt_text"])
                vsb.setValue(scroll)
        self.stage_label.setText("")
        if resume:
            self._player.play()
            self.btn_play_toggle.setText("⏸")

    # ── 实时保存 / 修改标记 ──

    def _on_live_edit(self):
        """编辑中防抖落盘：解析当前文本 → 更新数据 → 写入视频旁的 .srt。"""
        if not self._edit_mode:
            return
        row = self._edit_file_row
        if not (0 <= row < len(self.files)):
            return
        if self._apply_edits(self.files[row], self.subtitle_editor.toPlainText()):
            import time as _t
            self.stage_label.setText(f"✏️ 编辑中 · 已自动保存 {_t.strftime('%H:%M:%S')}")

    def _apply_edits(self, f, text) -> bool:
        """把编辑后的字幕文本回写到文件记录：更新 segments/srt_text、
        未改动的段保留字级时间戳（words）、被改的段打下划线标记、实时写入视频旁 .srt。"""
        new_segments = self._parse_srt(text)
        if not new_segments:
            return False
        cur = f.get("segments") or []
        # 首次编辑时快照原始转写结果，作为“是否修改”的对比基准
        orig = f.get("orig_segments")
        if orig is None:
            orig = [{"start": float(s.get("start", 0) or 0),
                     "end": float(s.get("end", 0) or 0),
                     "text": str(s.get("text", "")).strip()}
                    for s in cur]
            f["orig_segments"] = orig
        for i, seg in enumerate(new_segments):
            # 与当前段完全一致 → 保留字级时间戳（逐字点击/黄色高亮不丢失）
            if i < len(cur):
                c = cur[i]
                if (seg["text"] == str(c.get("text", "")).strip()
                        and abs(seg["start"] - float(c.get("start", 0) or 0)) <= 0.01
                        and abs(seg["end"] - float(c.get("end", 0) or 0)) <= 0.01):
                    seg["words"] = c.get("words") or []
            # 与原始基准对比 → 是否标记为已修改（下划线）
            if i < len(orig):
                o = orig[i]
                seg["edited"] = (abs(seg["start"] - o["start"]) > 0.01
                                 or abs(seg["end"] - o["end"]) > 0.01
                                 or seg["text"] != o["text"])
            else:
                seg["edited"] = True  # 新增的段
        f["segments"] = new_segments
        f["srt_text"] = self._segments_to_srt(new_segments)
        self._write_sidecar(f)
        return True

    def _write_sidecar(self, f):
        """把字幕实时保存到视频旁的同名 .srt（编辑闭环：下次添加自动加载）。"""
        try:
            path = os.path.splitext(f["path"])[0] + ".srt"
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(f["srt_text"])
        except Exception as e:
            log.error(f"[转写] 实时保存字幕失败: {e}")

    # ── SRT 解析 / 生成 ──

    @staticmethod
    def _parse_srt_time(t: str) -> float:
        """SRT 时间戳 HH:MM:SS,mmm（兼容 . 分隔）→ 秒"""
        t = t.strip().replace(".", ",")
        try:
            hms, ms = t.split(",")
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms[:3]) / 1000.0
        except Exception:
            return 0.0

    _TIME_RE = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")

    @classmethod
    def _parse_srt(cls, text: str) -> list:
        """逐行解析字幕文本 → segments [{"start","end","text","words":[]}]。

        同时兼容两种输入：原始 SRT（序号行+时间轴行+正文）和
        编辑态视图纯文本（时间轴行内嵌序号，如 "1  00:00:01,000 --> ..."）。
        """
        segments = []
        cur = None
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = cls._TIME_RE.search(line)
            if m:
                if cur:
                    segments.append(cur)
                cur = {"start": cls._parse_srt_time(m.group(1)),
                       "end": cls._parse_srt_time(m.group(2)),
                       "text": "", "words": []}
                continue
            if re.fullmatch(r"\d+", line):
                continue  # SRT 序号行
            if cur is not None:
                cur["text"] = (cur["text"] + " " + line).strip()
        if cur:
            segments.append(cur)
        segments = [s for s in segments if s["text"]]
        segments.sort(key=lambda s: s["start"])
        return segments

    @staticmethod
    def _segments_to_srt(segments) -> str:
        lines = []
        for i, seg in enumerate(segments):
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = str(seg.get("text", "")).strip().replace("\n", " ")
            lines.append(f"{i + 1}")
            lines.append(
                f"{int(start // 3600):02d}:{int(start % 3600 // 60):02d}:{start % 60:06.3f} --> "
                f"{int(end // 3600):02d}:{int(end % 3600 // 60):02d}:{end % 60:06.3f}"
            )
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def _play_file(self, path):
        if not os.path.isfile(path):
            QMessageBox.warning(self.parent_widget, "文件不存在", f"文件不存在:\n{path}")
            return
        url = QUrl.fromLocalFile(path)
        self._player.stop()
        self._player.setSource(url)
        self._video_widget.show()
        self._player.setVideoOutput(self._video_widget)
        self._player.play()
        self.btn_play_toggle.setText("⏸")

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
            # 没有待处理文件：若存在已完成文件，询问是否全部重新转写
            done = [i for i, f in enumerate(self.files) if f["status"] == "✅ 完成"]
            if done and self.confirm(f"没有待处理的文件。\n\n是否重新转写已完成的 {len(done)} 个文件？\n（原有字幕将被新结果覆盖）", "重新转写"):
                for i in done:
                    self.files[i]["status"] = "等待处理"
                    self.files[i].pop("orig_segments", None)
                    self._refresh_file_row(i)
                pending = done
            else:
                QMessageBox.warning(self.parent_widget, "无待处理文件",
                                    "没有待处理的文件。\n如需重新生成字幕，请右键文件选择「🔄 重新转写」。")
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
            # 默认展示第一个已完成文件的转写结果
            for i, f in enumerate(self.files):
                if f["status"] == "✅ 完成" and f["srt_text"]:
                    if self.file_table.currentRow() == i:
                        self._on_file_selection_changed()  # 已选中不会发信号，强制刷新显示
                    else:
                        self.file_table.selectRow(i)
                    break
            return

        idx = self._current_pending[self._current_index]
        f = self.files[idx]
        f["status"] = "⏳ 处理中"
        self._refresh_file_row(idx)
        self.stage_label.setText(f"正在处理: {os.path.basename(f['path'])}")
        self.progress_bar.setValue(self._current_index)

        from utils.asr_client import transcribe_remote, read_asr_url

        class BatchWorker(BaseWorker):
            finished = Signal(int, str, list)  # file_list_index, srt_text, segments(含 words)
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
                    # 保留完整 segments（含 word 级时间戳），供字级对齐点击使用
                    self.finished.emit(self.file_idx, srt_text, segments)
                except Exception as e:
                    self.error.emit(self.file_idx, str(e))

        self.worker = BatchWorker(idx, f["path"], language, task_type, diarize)
        self.worker.finished.connect(self._on_file_done)
        self.worker.error.connect(self._on_file_error)
        self.worker.start()

    def _on_file_done(self, file_idx, srt_text, segments):
        f = self.files[file_idx]
        f["status"] = "✅ 完成"
        f["srt_text"] = srt_text
        f["segments"] = segments or []
        f.pop("orig_segments", None)  # 新结果成为修改标记的新基准
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
        self._write_sidecar(f)  # 转写结果同步保存到视频旁 .srt，形成闭环
        # 若完成的正是当前选中行，立即刷新字幕显示（选中态不变化时不会触发信号）
        if self.file_table.currentRow() == file_idx:
            self._on_file_selection_changed()

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
