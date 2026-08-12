# -*- coding: utf-8 -*-
import os
import sys
import shutil
import subprocess
import json

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QCheckBox, QMessageBox, QFrame, QTableWidget,
                               QTableWidgetItem, QHeaderView, QWidget, QGroupBox, QScrollArea, QListView,
                               QSpinBox, QDialog)
from PySide6.QtCore import Signal, QThread, Qt, QUrl
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button, mdi_icon
from utils.logger_utils import log
from config.paths import PROJECT_ROOT, OUTPUTS_DIR
from gui.voice_samples_page import load_voice_samples
from utils import voxcpm_client

# Import workers and helper dialogs/widgets from video_montage_page to avoid duplicate definitions
from gui.video_montage_page import (
    VoiceCloneWorker,
    DoubleClickLineEdit,
    TextEditDialog,
    find_ffmpeg
)

from utils.file_dialog_utils import pick_directory, pick_file, pick_save_file
class PunctuationLLMWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, model, raw_text):
        super().__init__()
        self.model = model
        self.raw_text = raw_text

    def run(self):
        try:
            from utils.llm_proxy import llm_chat
            system_prompt = "你是一个智能语音识别文本后处理助手。你的任务是给一段没有标点符号的语音识别文本添加合理的标点符号（，。！？：等），并进行合理的断句，使阅读更清晰自然。请绝对不要修改、增加或删除原文本的任何字词（只允许增删标点符号），直接输出加上标点后的纯文本，不要有任何多余的解释或包裹标记。"
            content = llm_chat(system_prompt, self.raw_text, model=self.model, temperature=0.3, timeout=25)
            if content.startswith("```"):
                content = content.replace("```", "").strip()
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))

class SentenceSplitterLLMWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, model, text):
        super().__init__()
        self.model = model
        self.text = text

    def run(self):
        try:
            from utils.llm_proxy import llm_chat
            system_prompt = (
                "你是一个短视频文案拆句专家。请把输入的文本段落拆分成适合逐句进行克隆配音合成的句子列表。\n"
                "规则：\n"
                "1. 第一原则是【句意完整】与【长度合理】。每一行必须是一个语义完整、能独立朗读的句子，长度一般在 10~40 字之间为宜。\n"
                "2. 主要依据句号（。）、感叹号（！）、问号（？）以及换行进行拆分。\n"
                "3. 【严禁拆得过碎】：绝对不要把一个连贯句子的半句、短促词、或仅 5~8 个字的残片单独拆成一行。宁可让某一行偏长一点，也不要为了多分行而把句子拆碎。\n"
                "4. 只有当一个句子【确实过长】（明显超过 50 字、一口气无法顺畅朗读）时，才允许在自然的逗号、分号等停顿处切分；30 字并不是硬性上限，短一点或长一点都没关系，关键看是否通顺完整。\n"
                "5. 输出格式：每行一句话，每行行首不要自己添加行号或序号（不要写 1. 2. 3. 这种）。\n"
                "6. 【绝对忠实原文】：必须严格保持原文的每一个字，绝对不能漏字、改字、删字。特别强调——原文里【本来就有】的编号、序号、序数词（如“（一）”“（二）”“第一条”“其一”等）属于正文内容，必须原样保留在对应句子中，绝不允许删除或简化。\n"
                "7. 只做合理的断句换行，不要对原文做任何总结、改写或润色。"
            )
            content = llm_chat(system_prompt, self.text, model=self.model, temperature=0.2, timeout=120)
            if content.startswith("```"):
                content = content.replace("```", "").strip()
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))


class RemoteAsrWorker(BaseWorker):
    """远程 ASR 转写 worker：调 transcribe_remote 返回含 word 级对齐的 segments。

    替代已删除的 apps.whisperx 本地子进程。服务端 /whisper/transcribe（fmt=json）
    返回 segments[].words[] = [{word, start, end}, ...]，可直接用于精确对齐切音频。
    """
    finished = Signal(list)   # segments: [{"start","end","text","words"?}, ...]
    error = Signal(str)

    def __init__(self, audio_path, language=None):
        super().__init__()
        self.audio_path = audio_path
        self.language = language

    def do_work(self):
        try:
            from utils.asr_client import transcribe_remote, read_asr_url
            asr_url = read_asr_url()
            segments = transcribe_remote(
                self.audio_path, asr_url,
                language=self.language or "",
            )
            self.finished.emit(segments)
        except Exception as e:
            self.error.emit(str(e))

from gui.base_page import BasePage
from gui.searchable_combo import SearchableComboBox


class VoiceClonePage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        
        # State variables
        self.voice_video_paths = []
        self.generated_voice_paths = {}  # maps video_path -> voice_wav_path
        self.dubbed_video_paths = {}     # maps video_path -> dubbed_video_path
        
        self.row_edits = {}
        self.voice_worker = None
        self.dub_worker = None
        self._synthesize_merge = False  # 本次批量克隆是否在生成后合并为整体音频

        self._media_player = None
        self._audio_output = None

    def setup(self):
        # Main layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(30, 24, 30, 24)
        main_layout.setSpacing(16)

        # Title
        heading = QLabel("🎙️ AI 声音克隆")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        # Scroll Area for main content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setObjectName("scroll_page")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)

        # Configuration Card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 20, 20, 20)

        # 1. Reference voice sample selection
        row_ref_audio = QHBoxLayout()
        lbl_ref_sample = QLabel("参考声音样本:")
        lbl_ref_sample.setFixedWidth(140)
        row_ref_audio.addWidget(lbl_ref_sample)
        
        self.ref_audio_combo = SearchableComboBox(placeholder="输入声音名称搜索…")
        self.ref_audio_combo.setView(QListView())
        self.ref_audio_combo.setMinimumWidth(300)
        self.ref_audio_combo.currentIndexChanged.connect(self._on_ref_audio_combo_changed)
        row_ref_audio.addWidget(self.ref_audio_combo)
        
        btn_sel_ref = mdi_button("选择本地人声", "folder")
        btn_sel_ref.setObjectName("secondary_button")
        btn_sel_ref.clicked.connect(self._select_ref_audio)
        row_ref_audio.addWidget(btn_sel_ref)
        
        self.btn_play_ref = mdi_button("", "volume")
        self.btn_play_ref.setToolTip("播放人声样本")
        self.btn_play_ref.setStyleSheet("padding: 0px; font-size: 14px;")
        self.btn_play_ref.setFixedWidth(32)
        self.btn_play_ref.setEnabled(False)
        self.btn_play_ref.clicked.connect(self._play_ref_audio)
        row_ref_audio.addWidget(self.btn_play_ref)
        card_layout.addLayout(row_ref_audio)

        # 4. Ref sample text
        row_ref_text = QHBoxLayout()
        lbl_ref_text = QLabel("参考样本文案 (可选):")
        lbl_ref_text.setFixedWidth(140)
        row_ref_text.addWidget(lbl_ref_text)
        
        self.ref_text_input = QTextEdit()
        self.ref_text_input.setPlaceholderText("可选，填入参考声音样本对应的文字，支持换行...")
        self.ref_text_input.setFixedHeight(100)
        self.ref_text_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                color: #ecf0f1;
                font-size: 13px;
                padding: 4px;
            }
            QTextEdit:focus {
                border: 1px solid #2ecc71;
                background-color: rgba(255, 255, 255, 0.08);
            }
        """)
        row_ref_text.addWidget(self.ref_text_input)

        # Vertical layout for buttons next to the text area
        v_btn_layout = QVBoxLayout()
        v_btn_layout.setSpacing(6)
        v_btn_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_transcribe_ref = mdi_button("识别参考音频文本", "edit")
        self.btn_transcribe_ref.setObjectName("secondary_button")
        self.btn_transcribe_ref.setFixedHeight(100)
        self.btn_transcribe_ref.setEnabled(False)
        self.btn_transcribe_ref.clicked.connect(self._transcribe_ref_audio)
        v_btn_layout.addWidget(self.btn_transcribe_ref)

        row_ref_text.addLayout(v_btn_layout)
        card_layout.addLayout(row_ref_text)

        # 5. Voice Output Directory Row (moved below transcribe)
        row_vid_dir = QHBoxLayout()
        lbl_dir = QLabel("📁 语音输出目录:")
        lbl_dir.setFixedWidth(140)
        row_vid_dir.addWidget(lbl_dir)
        
        self.voice_video_dir_input = QLineEdit()
        self.voice_video_dir_input.setPlaceholderText("选择保存克隆生成语音的目录...")
        default_out_dir = os.path.abspath(os.path.join(OUTPUTS_DIR, "voice_clone"))
        os.makedirs(default_out_dir, exist_ok=True)
        self.voice_video_dir_input.setText(default_out_dir)
        self.voice_video_dir_input.textChanged.connect(self._on_voice_video_dir_changed)
        row_vid_dir.addWidget(self.voice_video_dir_input)
        
        btn_sel_vid_dir = mdi_button("选择输出目录", "folder")
        btn_sel_vid_dir.setObjectName("secondary_button")
        btn_sel_vid_dir.clicked.connect(self._select_voice_video_dir)
        row_vid_dir.addWidget(btn_sel_vid_dir)

        btn_open_dir = mdi_button("打开目录", "folder")
        btn_open_dir.setObjectName("secondary_button")
        btn_open_dir.clicked.connect(self._open_voice_output_dir)
        row_vid_dir.addWidget(btn_open_dir)
        card_layout.addLayout(row_vid_dir)

        # 6. Target clone text (整体文案)
        row_target_text = QHBoxLayout()
        lbl_target_text = QLabel("待克隆整体文案:")
        lbl_target_text.setFixedWidth(140)
        row_target_text.addWidget(lbl_target_text)
        
        self.clone_text_input = QTextEdit()
        self.clone_text_input.setPlaceholderText("填入需要整体克隆的全部视频/音频文案内容，支持换行...")
        self.clone_text_input.setFixedHeight(120)
        self.clone_text_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                color: #ecf0f1;
                font-size: 13px;
                padding: 4px;
            }
            QTextEdit:focus {
                border: 1px solid #2ecc71;
                background-color: rgba(255, 255, 255, 0.08);
            }
        """)
        self.clone_text_input.setContextMenuPolicy(Qt.CustomContextMenu)
        self.clone_text_input.customContextMenuRequested.connect(
            self._show_clone_text_context_menu)
        row_target_text.addWidget(self.clone_text_input)

        v_btn_clone_layout = QVBoxLayout()
        v_btn_clone_layout.setSpacing(6)
        v_btn_clone_layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_clone_whole = mdi_button("整体克隆人声", "voice")
        self.btn_clone_whole.setObjectName("primary_button")
        self.btn_clone_whole.setFixedHeight(40)
        self.btn_clone_whole.clicked.connect(self._clone_whole_audio)
        v_btn_clone_layout.addWidget(self.btn_clone_whole)
        
        self.btn_play_whole = mdi_button("播放克隆声音", "volume")
        self.btn_play_whole.setObjectName("secondary_button")
        self.btn_play_whole.setFixedHeight(40)
        self.btn_play_whole.setEnabled(False)
        self.btn_play_whole.clicked.connect(self._play_whole_audio)
        v_btn_clone_layout.addWidget(self.btn_play_whole)
        
        row_target_text.addLayout(v_btn_clone_layout)
        card_layout.addLayout(row_target_text)

        # 5. Table of files and scripts
        row_table_header = QHBoxLayout()
        row_table_header.addWidget(QLabel("📝 待合成人声音频列表与文案配置:"))
        row_table_header.addStretch()
        
        self.btn_split_text = mdi_button("一键拆分填充", "clipboard")
        self.btn_split_text.setObjectName("secondary_button")
        self.btn_split_text.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        self.btn_split_text.clicked.connect(self._split_and_populate_manually)
        row_table_header.addWidget(self.btn_split_text)

        # 拆分填充策略说明按钮（紧挨一键拆分填充）
        btn_split_help = QPushButton("❓")
        btn_split_help.setFixedSize(24, 24)
        btn_split_help.setStyleSheet("padding: 0px; font-size: 12px;")
        btn_split_help.setToolTip("点击查看“一键拆分填充”的智能合并策略说明")
        btn_split_help.clicked.connect(self._show_split_strategy_help)
        row_table_header.addWidget(btn_split_help)

        btn_add_row = mdi_button("添加行", "plus")
        btn_add_row.setObjectName("secondary_button")
        btn_add_row.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        btn_add_row.clicked.connect(self._add_table_row)
        row_table_header.addWidget(btn_add_row)

        btn_del_row = mdi_button("删除选中行", "trash")
        btn_del_row.setObjectName("secondary_button")
        btn_del_row.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        btn_del_row.clicked.connect(self._delete_selected_row)
        row_table_header.addWidget(btn_del_row)

        btn_clear_table = mdi_button("清空所有行", "broom")
        btn_clear_table.setObjectName("secondary_button")
        btn_clear_table.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        btn_clear_table.clicked.connect(self._clear_table)
        row_table_header.addWidget(btn_clear_table)
        
        card_layout.addLayout(row_table_header)

        self.voice_table = QTableWidget()
        self.voice_table.setColumnCount(5)
        self.voice_table.setHorizontalHeaderLabels(["序号", "生成的音频文件名", "配音文案 (双击输入，回车保存)", "克隆状态", "操作"])
        self.voice_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.voice_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.voice_table.setColumnWidth(1, 150)
        self.voice_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.voice_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.voice_table.setColumnWidth(3, 110)
        self.voice_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.voice_table.setColumnWidth(4, 120)
        self.voice_table.verticalHeader().setDefaultSectionSize(42)
        self.voice_table.verticalHeader().setMinimumSectionSize(35)
        self.voice_table.verticalHeader().setVisible(False)
        self.voice_table.setMinimumHeight(240)
        card_layout.addWidget(self.voice_table, 1)

        # Subtitle option checkbox
        row_subtitle_opt = QHBoxLayout()
        self.chk_add_subtitles = QCheckBox("在配音视频中同时添加/烧录字幕 (字号14px 微软雅黑 白色 50%透明背景)")
        self.chk_add_subtitles.setChecked(True)
        self.chk_add_subtitles.setStyleSheet("color: #e5e7eb; font-size: 13px; font-weight: bold;")
        self.chk_add_subtitles.setVisible(False)
        row_subtitle_opt.addWidget(self.chk_add_subtitles)
        card_layout.addLayout(row_subtitle_opt)

        # 7. Action buttons row
        row_actions = QHBoxLayout()
        self.btn_synthesize_split = mdi_button("分行克隆声音", "voice")
        self.btn_synthesize_split.setObjectName("action_button")
        self.btn_synthesize_split.setFixedHeight(35)
        self.btn_synthesize_split.setToolTip("按表格每一行文案，逐行单独克隆生成各自的声音文件。")
        self.btn_synthesize_split.clicked.connect(lambda: self._run_synthesize(merge=False))
        row_actions.addWidget(self.btn_synthesize_split, 1)

        self.btn_synthesize_merge = mdi_button("合成克隆声音", "voice")
        self.btn_synthesize_merge.setObjectName("primary_button")
        self.btn_synthesize_merge.setFixedHeight(35)
        self.btn_synthesize_merge.setToolTip("逐行克隆后，将所有声音合并为一个整体声音文件（voice_merged.wav）。")
        self.btn_synthesize_merge.clicked.connect(lambda: self._run_synthesize(merge=True))
        row_actions.addWidget(self.btn_synthesize_merge, 1)
        card_layout.addLayout(row_actions)

        # Populate reference voice samples
        self._populate_ref_audio_samples()

        scroll_layout.addWidget(card)
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)

        # Bottom shared status and progress bar
        bottom_status = QFrame()
        bottom_layout = QVBoxLayout(bottom_status)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        self.stage_label = QLabel("")
        self.stage_label.setObjectName("muted_text")
        bottom_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bottom_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(bottom_status, 0)

        # Add a default row on startup
        self._add_table_row()
        self._check_whole_audio_exists()

    def _select_voice_video_dir(self):
        dir_path = pick_directory(self.parent_widget, "选择音频输出目录", "")
        if dir_path:
            self.voice_video_dir_input.setText(dir_path)
            self._check_whole_audio_exists()

    def _open_voice_output_dir(self):
        d = self.voice_video_dir_input.text().strip()
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            QMessageBox.warning(self.parent_widget, "目录无效", "输出目录不存在，请先选择或生成文件。")

    def _show_clone_text_context_menu(self, pos):
        menu = self.clone_text_input.createStandardContextMenu()
        menu.addSeparator()

        act_lower = menu.addAction("转为小写")
        act_title = menu.addAction("首字母大写")
        act_upper = menu.addAction("转为大写")
        act_num_cn = menu.addAction("数字转汉字")

        chosen = menu.exec(self.clone_text_input.mapToGlobal(pos))

        cursor = self.clone_text_input.textCursor()
        sel = cursor.selectedText()
        if not sel:
            return

        if chosen == act_lower:
            cursor.insertText(sel.lower())
        elif chosen == act_title:
            cursor.insertText(sel.title())
        elif chosen == act_upper:
            cursor.insertText(sel.upper())
        elif chosen == act_num_cn:
            cursor.insertText(self._digits_to_cn(sel))

    @staticmethod
    def _digits_to_cn(text: str) -> str:
        import re

        def _int_to_cn(n: int) -> str:
            if n == 0:
                return "零"
            digits = "零一二三四五六七八九"
            units = ["", "十", "百", "千", "万", "十万", "百万", "千万", "亿"]
            result = ""
            s = str(n)
            length = len(s)
            for i, ch in enumerate(s):
                d = int(ch)
                unit = units[length - 1 - i]
                if d == 0:
                    if result and result[-1] != "零":
                        result += "零"
                else:
                    result += digits[d] + unit
            result = result.rstrip("零")
            if result.startswith("一十"):
                result = result[1:]
            return result or "零"

        def replace_num(m):
            num_str = m.group(0)
            if "." in num_str:
                parts = num_str.split(".", 1)
                int_part = _int_to_cn(int(parts[0])) if parts[0] else "零"
                dec_part = "".join(
                    "零一二三四五六七八九"[int(c)] for c in parts[1] if c.isdigit()
                )
                return int_part + "点" + dec_part
            else:
                return _int_to_cn(int(num_str))

        return re.sub(r"\d+(?:\.\d+)?", replace_num, text)

    def _on_voice_video_dir_changed(self):
        self._check_whole_audio_exists()

    def _add_table_row(self):
        row_idx = self.voice_table.rowCount()
        self.voice_table.insertRow(row_idx)
        self._setup_row_widgets(row_idx)
        self._adjust_table_height()

    def _delete_selected_row(self):
        selected_ranges = self.voice_table.selectedRanges()
        if not selected_ranges:
            QMessageBox.warning(self.parent_widget, "提示", "请先在列表中选择要删除的行！")
            return
        
        rows_to_delete = set()
        for r in selected_ranges:
            for i in range(r.topRow(), r.bottomRow() + 1):
                rows_to_delete.add(i)
                
        for i in sorted(rows_to_delete, reverse=True):
            self.voice_table.removeRow(i)
            
        # Re-index remaining rows
        for idx in range(self.voice_table.rowCount()):
            item_idx = self.voice_table.item(idx, 0)
            if item_idx:
                item_idx.setText(str(idx + 1))
            self._update_row_filename(idx)
                
        new_row_edits = {}
        for idx in range(self.voice_table.rowCount()):
            widget = self.voice_table.cellWidget(idx, 2)
            if widget:
                new_row_edits[idx] = widget
        self.row_edits = new_row_edits

        self._adjust_table_height()

    def _clear_table(self):
        self.voice_table.setRowCount(0)
        self.row_edits = {}
        self._adjust_table_height()

    def _setup_row_widgets(self, row_idx):
        # 0: Index
        item_idx = QTableWidgetItem(str(row_idx + 1))
        item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
        item_idx.setTextAlignment(Qt.AlignCenter)
        self.voice_table.setItem(row_idx, 0, item_idx)
        
        # 1: File name
        item_file = QTableWidgetItem("")
        item_file.setFlags(item_file.flags() & ~Qt.ItemIsEditable)
        self.voice_table.setItem(row_idx, 1, item_file)
        
        # 2: Script text
        edit = DoubleClickLineEdit("")
        edit.setPlaceholderText("双击输入文案，留空则不进行克隆")
        style = """
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                color: #ecf0f1;
                padding: 4px 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #2ecc71;
                background-color: rgba(255, 255, 255, 0.08);
            }
        """
        edit.setStyleSheet(style)
        edit.doubleClicked.connect(lambda w=edit: self._on_edit_double_clicked_widget(w))
        edit.textChanged.connect(lambda text, w=edit: self._on_row_text_changed_widget(w, text))
        self.row_edits[row_idx] = edit
        self.voice_table.setCellWidget(row_idx, 2, edit)
        
        # Now update row filename based on text
        self._update_row_filename(row_idx)
        
        # 3: Cloned voice status
        lbl_status = QLabel("未生成")
        lbl_status.setAlignment(Qt.AlignCenter)
        lbl_status.setStyleSheet("color: #95a5a6; font-size: 12px; padding: 4px;")
        self.voice_table.setCellWidget(row_idx, 3, lbl_status)
        
        # 4: Action row
        widget = QWidget()
        h_layout = QHBoxLayout(widget)
        h_layout.setContentsMargins(4, 2, 4, 2)
        h_layout.setSpacing(4)
        
        btn_play = mdi_button("", "volume")
        btn_play.setToolTip("播放克隆的声音")
        btn_play.setStyleSheet("padding: 0px; font-size: 12px;")
        btn_play.setFixedWidth(30)
        btn_play.setEnabled(False)
        btn_play.clicked.connect(lambda checked=False, b=btn_play: self._on_btn_play_clicked_by_btn(b))
        h_layout.addWidget(btn_play)
        
        btn_regen = mdi_button("", "refresh")
        btn_regen.setToolTip("仅重新生成该声音")
        btn_regen.setStyleSheet("padding: 0px; font-size: 12px;")
        btn_regen.setFixedWidth(30)
        btn_regen.clicked.connect(lambda checked=False, b=btn_regen: self._on_btn_regen_clicked_by_btn(b))
        h_layout.addWidget(btn_regen)
        
        btn_export = mdi_button("", "save")
        btn_export.setToolTip("导出该克隆声音")
        btn_export.setStyleSheet("padding: 0px; font-size: 12px;")
        btn_export.setFixedWidth(30)
        btn_export.setEnabled(False)
        btn_export.clicked.connect(lambda checked=False, b=btn_export: self._on_btn_export_clicked_by_btn(b))
        h_layout.addWidget(btn_export)
        
        self.voice_table.setCellWidget(row_idx, 4, widget)

    def _adjust_table_height(self):
        pass

    def _populate_ref_audio_samples(self):
        self.ref_audio_combo.clear()
        

        samples = load_voice_samples()
        
        # Sort by name
        samples.sort(key=lambda x: x.get("name", "").lower())
        
        for s in samples:
            self.ref_audio_combo.addItem(s.get("name"), s.get("path"))
            
        if not samples:
            self.ref_audio_combo.addItem("❌ 未找到预设声音样本", "")
            
        
        # Set default selection and fill its reference text.
        # SearchableComboBox.addItem 会以 blockSignals 选中第 0 项，
        # 因此这里需手动触发一次以填充默认样本的参考文案。
        if self.ref_audio_combo.count() > 0:
            self.ref_audio_combo.setCurrentIndex(0)
            self._on_ref_audio_combo_changed(0)
            
    def _on_ref_audio_combo_changed(self, index):
        data = self.ref_audio_combo.currentData()
        # Enable play and transcribe button if we have a valid path
        path = self.get_ref_audio_path()
        has_valid_path = bool(path and os.path.exists(path))
        self.btn_play_ref.setEnabled(has_valid_path)
        self.btn_transcribe_ref.setEnabled(has_valid_path)
        
        # Auto-fill reference script if it matches one of our saved samples, otherwise clear/refresh it
        self.ref_text_input.clear()
        if path:
            samples = load_voice_samples()
            for s in samples:
                if os.path.abspath(s.get("path", "")) == os.path.abspath(path):
                    ref_text = s.get("ref_text", "").strip()
                    self.ref_text_input.setPlainText(ref_text)
                    break

        # Update existing table row file names
        self._update_table_filenames()
        self._check_whole_audio_exists()

    def _select_ref_audio(self):
        path, _ = pick_file(
            self.parent_widget,
            "选择声音样本",
            "",
            "Audio Files (*.wav *.mp3 *.m4a);;All Files (*)"
        )
        if path:
            self._set_custom_ref_audio(path)

    def _set_custom_ref_audio(self, path):
        path = os.path.abspath(path)
        name = os.path.basename(path)
        
        # Check if it is already in the combo to avoid duplicates
        for idx in range(self.ref_audio_combo.count()):
            if self.ref_audio_combo.itemData(idx) == path:
                self.ref_audio_combo.setCurrentIndex(idx)
                return
        
        # Insert at index 0 and select it
        self.ref_audio_combo.insertItem(0, f"🎵 本地: {name}", path)
        self.ref_audio_combo.setCurrentIndex(0)

    def get_ref_audio_path(self):
        data = self.ref_audio_combo.currentData()
        return data or ""

    def _play_ref_audio(self):
        path = self.get_ref_audio_path()
        if path and os.path.exists(path):
            self._play_audio(path)

    def _transcribe_ref_audio(self):
        ref_audio = self.get_ref_audio_path()
        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未选择声音样本", "请先选择参考声音样本 (wav/mp3)！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在：\n{ref_audio}")
            return

        self.btn_transcribe_ref.setEnabled(False)
        self.btn_transcribe_ref.setText("⏳ 正在识别文本...")
        self.stage_label.setText("正在识别参考音频文本...")

        self.transcribe_worker = RemoteAsrWorker(ref_audio, language=None)

        def on_finished(segments):
            self.btn_transcribe_ref.setEnabled(True)
            self.btn_transcribe_ref.setText("识别参考音频文本")
            self.stage_label.setText("✅ 识别参考音频文本完成")

            from utils.asr_client import segments_to_plain
            plain_text = segments_to_plain(segments)

            llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

            if llm_model and plain_text.strip():
                self.stage_label.setText("⏳ 正在使用 AI 模型自动优化断句与标点...")
                self.punc_worker = PunctuationLLMWorker(llm_model, plain_text)

                def on_punc_done(punctuated_text):
                    self.ref_text_input.setPlainText(punctuated_text)
                    self.stage_label.setText("✅ 识别与标点优化完成")

                def on_punc_err(err):
                    log.warning(f"AI 添加标点失败: {err}，使用原始识别文本。")
                    self.ref_text_input.setPlainText(plain_text)
                    self.stage_label.setText("✅ 识别完成（标点优化失败）")

                self.punc_worker.finished.connect(on_punc_done)
                self.punc_worker.error.connect(on_punc_err)
                self.punc_worker.start()
            else:
                self.ref_text_input.setPlainText(plain_text)

        def on_error(err):
            self.btn_transcribe_ref.setEnabled(True)
            self.btn_transcribe_ref.setText("识别参考音频文本")
            self.stage_label.setText("❌ 识别文本失败")
            QMessageBox.critical(self.parent_widget, "识别文本失败", f"无法从参考音频中提取文本：\n{err}")

        self.transcribe_worker.finished.connect(on_finished)
        self.transcribe_worker.error.connect(on_error)
        self.transcribe_worker.start()

    def _clean_srt_to_text(self, srt_content):
        lines = srt_content.split('\n')
        text_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.isdigit():
                continue
            if '-->' in line:
                continue
            text_lines.append(line)
        return ' '.join(text_lines)

    def _show_split_strategy_help(self):
        """弹窗展示“一键拆分填充”的智能拆分与合并策略说明。"""
        # 动态展示当前样本推算出的单行字数上限，让用户直观理解
        try:
            max_chars = self._estimate_max_chars()
            chars_info = f"\n\n📊 当前样本推算的单行字数上限：约 {max_chars} 字（安全时长 15 秒）。"
        except Exception:
            chars_info = ""

        QMessageBox.information(
            self.parent_widget,
            "一键拆分填充 · 智能策略说明",
            "【功能】把上方“待克隆整体文案”智能拆分成逐行配音文案，自动填入下方列表。\n\n"
            "【拆分流程】\n"
            "1. 优先调用 AI（大模型）进行智能断句，保证每行语义完整、长度合理；\n"
            "   AI 不可用时自动退回本地规则（按句号、问号、感叹号、换行）拆分。\n"
            "2. 若已先生成整体克隆音频（voice_whole.wav），会同时分析音频时间戳，"
            "把整段音频按行切成对应的小音频文件。\n\n"
            "【智能合并策略】（避免每行过短、碎句过多）\n"
            "· 合并长度不是固定的，而是根据【样本声音语速动态推算】：\n"
            "    单行最大字数 ≈ 15秒 × (样本文案字数 ÷ 样本音频时长)\n"
            "· 只要相邻两行合并后不超过该上限，就会自动合并成一行；\n"
            "· 超过上限才断开另起新行。\n"
            "· 拿不到样本时，按中文播音常见语速 4字/秒 兜底（15秒 ≈ 60字）。\n\n"
            "【为什么限制 15 秒】\n"
            "VoxCPM 单次声音克隆生成的音频，安全区为 15~17 秒，不能超过 20 秒。"
            "因此每行文案念出来不能太长，否则克隆会失败或质量下降。\n\n"
            "【防漏字保护】\n"
            "AI 拆分后会校验字数：若输出比原文少（疑似漏字、误删编号等），"
            "会自动退回本地规则拆分，确保“（一）（二）”等原文编号一字不丢。"
            f"{chars_info}"
        )

    def _split_and_populate_manually(self):
        text = self.clone_text_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self.parent_widget, "提示", "请先在“待克隆整体文案”输入内容！")
            return

        whole_filename = self._get_named_filename(text, "whole")
        out_voice_dir = self.voice_video_dir_input.text().strip()
        whole_audio_path = os.path.abspath(os.path.join(out_voice_dir, whole_filename))

        if os.path.exists(whole_audio_path):
            self.btn_split_text.setEnabled(False)
            self.btn_split_text.setText("⏳ 智能识别拆分中...")
            self.stage_label.setText("⏳ 正在调用远程 ASR 分析整段音频时间戳...")

            self.align_worker = RemoteAsrWorker(whole_audio_path, language=None)

            def on_align_finished(segments):
                self.btn_split_text.setEnabled(True)
                self.btn_split_text.setText("一键拆分填充")
                self.stage_label.setText("✅ 音频时间戳分析完成，正在裁切音频并填充列表...")

                llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

                if llm_model:
                    self.stage_label.setText("⏳ 正在使用 AI 模型智能拆分整体文案...")
                    self.split_worker = SentenceSplitterLLMWorker(llm_model, text)

                    def on_split_done(result_text):
                        lines = [line.strip() for line in result_text.split('\n') if line.strip()]
                        # 校验 LLM 是否漏字（如误删编号），漏字则退回本地规则拆分
                        fallback = self._validate_llm_split(text, lines)
                        if fallback is not None:
                            lines = fallback
                        lines = self._merge_short_fragments(lines)
                        self._process_alignment_and_populate(lines, segments, whole_audio_path, out_voice_dir)
                        self.stage_label.setText("✅ 整体克隆语音智能拆分并裁切填充完成！")
                        QMessageBox.information(self.parent_widget, "提示", f"成功通过 AI 智能拆分大句，并裁切整段音频，填充 {len(lines)} 行。")

                    def on_split_err(err):
                        log.warning(f"AI 智能拆分失败: {err}，退回本地分句。")
                        lines = self._split_text_into_sentences(text)
                        lines = self._merge_short_fragments(lines)
                        self._process_alignment_and_populate(lines, segments, whole_audio_path, out_voice_dir)
                        self.stage_label.setText("✅ 整体克隆语音本地拆分并裁切填充完成！")
                        QMessageBox.information(self.parent_widget, "提示", f"AI 拆分失败，已通过本地规则拆分大句，并裁切整段音频，填充 {len(lines)} 行。")

                    self.split_worker.finished.connect(on_split_done)
                    self.split_worker.error.connect(on_split_err)
                    self.split_worker.start()
                else:
                    lines = self._split_text_into_sentences(text)
                    lines = self._merge_short_fragments(lines)
                    self._process_alignment_and_populate(lines, segments, whole_audio_path, out_voice_dir)
                    self.stage_label.setText("✅ 整体克隆语音本地拆分并裁切填充完成！")
                    QMessageBox.information(self.parent_widget, "提示", f"已成功通过本地规则拆分大句，并裁切整段音频，填充 {len(lines)} 行。")

            def on_align_error(err):
                self.btn_split_text.setEnabled(True)
                self.btn_split_text.setText("一键拆分填充")
                self.stage_label.setText("❌ 识别音频时间戳失败")
                QMessageBox.warning(self.parent_widget, "识别失败", f"分析整段音频失败，已退回纯文本拆分模式。\n错误：{err}")
                self._split_and_populate_text_only(text)

            self.align_worker.finished.connect(on_align_finished)
            self.align_worker.error.connect(on_align_error)
            self.align_worker.start()
        else:
            self._split_and_populate_text_only(text)

    def _split_text_into_sentences(self, text):
        if not text:
            return []
        delimiters = ["。", "！", "？", ".", "!", "?", "\n"]
        temp_text = text
        for d in delimiters:
            temp_text = temp_text.replace(d, "\n")

        parts = temp_text.split("\n")
        sentences = []
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)
        return sentences

    @staticmethod
    def _count_chars(s):
        """统计有效字数：中文+字母数字，忽略标点空白。"""
        return sum(1 for c in s if c.isalnum())

    # ── 动态合并参数 ──
    # VoxCPM 单次克隆生成的音频，安全区 15~17 秒，不能超过 20 秒。
    # 因此“每行最长多少字”不应是固定值，而要由样本语速反推：
    #   语速 = 样本文案字数 / 样本音频时长
    #   单行最大字数 = 安全时长上限(15s) × 语速
    _SAFE_DUR_SEC = 15.0   # 单行预估时长上限（保守，远离 20s 红线）
    _FALLBACK_CHARS_PER_SEC = 4.0  # 兜底语速：拿不到样本时按 4 字/秒（中文播音常见语速）

    def _estimate_max_chars(self):
        """根据当前选中的样本，推算“单行配音文案最多多少字”才不超 15 秒。

        优先用 样本音频时长 + 参考文案字数 推算真实语速；
        拿不到（未选样本/未填文案/读时长失败）时退回兜底 4 字/秒。
        """
        try:
            from gui.montage.utils_media import get_media_duration
            ref_audio = self.get_ref_audio_path()
            ref_text = self.ref_text_input.toPlainText().strip()
            if ref_audio and os.path.exists(ref_audio):
                dur = get_media_duration(ref_audio)
                n = self._count_chars(ref_text)
                if dur > 0 and n > 0:
                    chars_per_sec = n / dur
                    max_chars = int(self._SAFE_DUR_SEC * chars_per_sec)
                    # 兜底保护：语速异常时也别太小或太大
                    max_chars = max(10, min(max_chars, 120))
                    log.info(f"[拆分合并] 样本语速 {chars_per_sec:.2f} 字/秒 ({n}字/{dur:.1f}秒)，单行上限 {max_chars} 字")
                    return max_chars
        except Exception as e:
            log.warning(f"[拆分合并] 推算样本语速失败，用兜底 {self._FALLBACK_CHARS_PER_SEC} 字/秒: {e}")
        fallback = int(self._SAFE_DUR_SEC * self._FALLBACK_CHARS_PER_SEC)  # 60 字
        return fallback

    def _merge_short_fragments(self, lines, max_chars=None):
        """按“单行预估时长 ≤ 安全上限”贪心合并相邻短句。

        :param max_chars: 单行最大有效字数（由 _estimate_max_chars 推算）。
                          超过该值不合并；相邻两行合并后未超则合并。
        策略：顺序遍历，若“当前行 + 下一行”合并后字数 ≤ max_chars，就并入当前行；
        否则当前行定稿、下一行开新行。同时仍会处理明显过短的残片（保证不会留极短行）。
        合并仅改变行数与文字，A 路音频对齐会基于合并后的新句子重新匹配 word 序列，不影响切音频。
        """
        if not lines:
            return []
        if max_chars is None:
            max_chars = self._estimate_max_chars()
        # 最小阈值：低于此值视为残片，强制与相邻行合并（避免 5~8 字碎行）
        min_len = max(8, max_chars // 4)

        # 第1遍：贪心向后合并（相邻两行合起来不超 max_chars 就并）
        merged = []
        for s in lines:
            s = s.strip()
            if not s:
                continue
            if merged and self._count_chars(merged[-1]) + self._count_chars(s) <= max_chars:
                merged[-1] = merged[-1] + " " + s
            else:
                merged.append(s)

        # 第2遍：清理仍过短的残片（并入相邻行）
        if len(merged) >= 2:
            cleaned = []
            for s in merged:
                if cleaned and self._count_chars(s) < min_len:
                    # 当前行过短：优先并入前句；若前句已满则并入后句（下一轮处理）
                    if self._count_chars(cleaned[-1]) + self._count_chars(s) <= max_chars:
                        cleaned[-1] = cleaned[-1] + " " + s
                    else:
                        cleaned.append(s)
                else:
                    cleaned.append(s)
            # 末尾过短则并入前句
            if len(cleaned) >= 2 and self._count_chars(cleaned[-1]) < min_len:
                cleaned[-2] = cleaned[-2] + " " + cleaned[-1]
                cleaned.pop()
            merged = cleaned
        return merged

    def _validate_llm_split(self, original_text, llm_lines):
        """校验 LLM 拆分是否忠实原文（没漏字/删字）。

        小模型常会自作主张删除“（一）（二）”这类编号或改写原文。
        用有效字数（中文+字母数字）做容错比对：若 LLM 输出字数明显少于原文（<90%），
        判定为漏字，返回本地规则拆分结果作为兜底；否则返回 None 表示校验通过。
        """
        orig_count = self._count_chars(original_text)
        llm_count = sum(self._count_chars(l) for l in llm_lines)
        # 阈值 99%：严格防漏字。_count_chars 只数中文+字母数字，已排除空格和标点，
        # 所以标点/空白差异不会误判；只要 LLM 输出的实质文字少于原文 99% 即判定漏字，退回本地拆分。
        if orig_count > 0 and llm_count < orig_count * 0.99:
            log.warning(f"AI 拆分疑似漏字（原文 {orig_count} 字，AI 输出 {llm_count} 字），退回本地规则拆分。")
            return self._split_text_into_sentences(original_text)
        return None

    def _populate_sentences_to_table(self, text):
        sentences = self._split_text_into_sentences(text)
        if not sentences:
            return

        sentences = self._merge_short_fragments(sentences)
        self._clear_table()

        for s in sentences:
            row_idx = self.voice_table.rowCount()
            self.voice_table.insertRow(row_idx)
            self._setup_row_widgets(row_idx)
            edit = self.row_edits.get(row_idx)
            if edit:
                edit.setText(s)

        self._adjust_table_height()


    def _play_audio(self, wav_path):
        try:
            if wav_path.lower().endswith(".wav"):
                # Qt 的 QMediaPlayer / QSoundEffect 在部分 Windows 上会把 WAV 尾部截断
                # （例如克隆声音“特”被吞成“ti”）。winsound 走系统原生播放，可完整播完。
                from utils.wav_player import play_wav
                play_wav(wav_path)
                return
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            if not self._media_player:
                self._media_player = QMediaPlayer()
                self._audio_output = QAudioOutput()
                self._media_player.setAudioOutput(self._audio_output)
            if self._media_player.playbackState() == QMediaPlayer.PlayingState:
                self._media_player.stop()
                if self._media_player.source().toLocalFile() == os.path.abspath(wav_path):
                    return
            self._media_player.setSource(QUrl.fromLocalFile(wav_path))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception as e:
            log.error(f"播放音频失败: {e}")



    def _on_edit_double_clicked(self, row_idx):
        edit = self.row_edits.get(row_idx)
        if edit:
            dialog = TextEditDialog(f"编辑第 {row_idx + 1} 行配音文案", edit.text(), self.parent_widget)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                edit.setText(new_text)

    def _on_edit_double_clicked_widget(self, edit):
        row_idx = self._get_widget_row(edit)
        if row_idx != -1:
            dialog = TextEditDialog(f"编辑第 {row_idx + 1} 行配音文案", edit.text(), self.parent_widget)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                edit.setText(new_text)

    def _on_row_text_changed_widget(self, edit, text):
        row_idx = self._get_widget_row(edit)
        if row_idx != -1:
            self._update_row_filename(row_idx)

    def _on_btn_play_clicked_by_btn(self, btn):
        row_idx = self._get_button_row(btn)
        if row_idx != -1:
            self._on_btn_play_clicked_by_row(row_idx)

    def _on_btn_regen_clicked_by_btn(self, btn):
        row_idx = self._get_button_row(btn)
        if row_idx != -1:
            self._on_btn_regen_clicked_by_row(row_idx)

    def _on_btn_export_clicked_by_btn(self, btn):
        row_idx = self._get_button_row(btn)
        if row_idx != -1:
            self._on_btn_export_clicked_by_row(row_idx)

    def _on_row_progress(self, row_idx, value):
        edit = self.row_edits.get(row_idx)
        if edit:
            if value <= 0:
                style = """
                    QLineEdit {
                        background-color: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                    QLineEdit:focus {
                        border: 1px solid #2ecc71;
                        background-color: rgba(255, 255, 255, 0.08);
                    }
                """
            elif value >= 100:
                style = """
                    QLineEdit {
                        background-color: rgba(46, 204, 113, 0.25);
                        border: 1px solid #2ecc71;
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }
                """
            else:
                ratio = value / 100.0
                style = f"""
                    QLineEdit {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(46, 204, 113, 0.35), stop:{ratio} rgba(46, 204, 113, 0.35), stop:{ratio} rgba(255, 255, 255, 0.05), stop:1 rgba(255, 255, 255, 0.05));
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 4px;
                        color: #ecf0f1;
                        padding: 4px 8px;
                        font-size: 13px;
                    }}
                """
            edit.setStyleSheet(style)

    def _on_btn_play_clicked_by_row(self, row_idx):
        wav_path = self.generated_voice_paths.get(row_idx, "")
        if wav_path and os.path.exists(wav_path):
            self._play_audio(wav_path)

    def _on_btn_export_clicked_by_row(self, row_idx):
        wav_path = self.generated_voice_paths.get(row_idx, "")
        if not wav_path or not os.path.exists(wav_path):
            return
        
        save_path, _ = pick_save_file(
            self.parent_widget,
            "导出克隆声音",
            os.path.basename(wav_path),
            "Audio Files (*.wav);;All Files (*)"
        )
        if save_path:
            try:
                shutil.copy2(wav_path, save_path)
                QMessageBox.information(self.parent_widget, "导出成功", f"人声音频成功导出至：\n{save_path}")
            except Exception as e:
                QMessageBox.warning(self.parent_widget, "导出失败", f"无法导出文件: {e}")

    def _on_btn_regen_clicked_by_row(self, row_idx):
        edit = self.row_edits.get(row_idx)
        text = edit.text().strip() if edit else ""
        if not text:
            QMessageBox.warning(self.parent_widget, "配音文案为空", "该行文案为空，无法生成克隆人声。")
            return
        
        self._start_single_synthesize(row_idx, text)

    def _start_single_synthesize(self, row_idx, text):
        if self.voice_worker and self.voice_worker.isRunning():
            QMessageBox.warning(self.parent_widget, "合成中", "当前有克隆人声合成任务正在运行，请等待其完成。")
            return
            
        ref_audio = self.get_ref_audio_path()
        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未选择声音样本", "请先选择参考声音样本！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")
            return

        out_voice_dir = self.voice_video_dir_input.text().strip()
        if not out_voice_dir or not os.path.exists(out_voice_dir):
            QMessageBox.warning(self.parent_widget, "路径无效", "请选择有效的音频输出目录。")
            return

        self.btn_synthesize_split.setEnabled(False)
        self.btn_synthesize_merge.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText(f"正在生成第 {row_idx+1} 行的克隆声音...")

        self._on_row_progress(row_idx, 0)

        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model_path = cfg.get("vox_model_path", "")
        voice_mode = cfg.get("vox_mode", "api")
        api_url = cfg.get("vox_api_url", "") or voxcpm_client.tts_url()
        timesteps = cfg.get("vox_timesteps", 20)
        cfg_val = cfg.get("vox_cfg", 2.0)

        item_file = self.voice_table.item(row_idx, 1)
        filename = item_file.text() if item_file else f"voice_{row_idx + 1}.wav"
        out_wav_path = os.path.abspath(os.path.join(out_voice_dir, filename))
        tasks = [(row_idx, text, f"row_{row_idx}", out_wav_path)]
        
        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.toPlainText().strip(),
            voice_mode=voice_mode,
            voice_api_url=api_url,
            voice_cli_checkpoint=model_path,
            temp_dir=out_voice_dir,
            task_type="voice",
            inference_timesteps=timesteps,
            cfg_value=cfg_val
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.voice_worker.row_progress.connect(self._on_row_progress)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()

    def _run_synthesize(self, merge=False):
        """批量逐行克隆人声。

        :param merge: False=分行克隆（每行单独一个声音文件）；
                      True=合成克隆（逐行生成后再合并为一个整体声音文件 voice_merged.wav）。
        """
        if self.voice_worker and self.voice_worker.isRunning():
            return

        ref_audio = self.get_ref_audio_path()
        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未上传声音样本", "请先上传/选择参考声音样本 (wav/mp3)！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")
            return

        out_voice_dir = self.voice_video_dir_input.text().strip()
        if not out_voice_dir or not os.path.exists(out_voice_dir):
            QMessageBox.warning(self.parent_widget, "路径无效", "请选择音频输出目录。")
            return

        tasks = []
        for i in range(self.voice_table.rowCount()):
            edit = self.row_edits.get(i)
            if edit:
                text = edit.text().strip()
                if text:
                    item_file = self.voice_table.item(i, 1)
                    filename = item_file.text() if item_file else f"voice_{i+1}.wav"
                    out_wav_path = os.path.abspath(os.path.join(out_voice_dir, filename))
                    tasks.append((i, text, f"row_{i}", out_wav_path))

        if not tasks:
            QMessageBox.warning(self.parent_widget, "文案为空", "没有检测到任何配文。请在列表的“配音文案”栏输入内容。")
            return

        for i in range(self.voice_table.rowCount()):
            self._on_row_progress(i, 0)

        self._synthesize_merge = merge
        self.btn_synthesize_split.setEnabled(False)
        self.btn_synthesize_merge.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        mode_hint = "合成克隆（将合并为一个整体音频）" if merge else "分行克隆（每行单独一个音频）"
        self.stage_label.setText(f"⏳ 正在逐行克隆人声 [{mode_hint}]...")

        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model_path = cfg.get("vox_model_path", "")
        voice_mode = cfg.get("vox_mode", "api")
        api_url = cfg.get("vox_api_url", "") or voxcpm_client.tts_url()
        timesteps = cfg.get("vox_timesteps", 20)
        cfg_val = cfg.get("vox_cfg", 2.0)

        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.toPlainText().strip(),
            voice_mode=voice_mode,
            voice_api_url=api_url,
            voice_cli_checkpoint=model_path,
            temp_dir=out_voice_dir,
            task_type="voice",
            inference_timesteps=timesteps,
            cfg_value=cfg_val
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        self.voice_worker.row_progress.connect(self._on_row_progress)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.error.connect(self._on_voice_error)
        self.voice_worker.start()

    def _on_voice_finished(self, results):
        self.btn_synthesize_split.setEnabled(True)
        self.btn_synthesize_merge.setEnabled(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("✅ 克隆人声音频生成完成！")

        for vid, wav in results.items():
            try:
                row_idx = int(vid.split("_")[1])
                self.generated_voice_paths[row_idx] = wav

                lbl_status = self.voice_table.cellWidget(row_idx, 3)
                if isinstance(lbl_status, QLabel):
                    lbl_status.setText(os.path.basename(wav))
                    lbl_status.setStyleSheet("color: #2ecc71; font-size: 12px; padding: 4px;")

                act_widget = self.voice_table.cellWidget(row_idx, 4)
                if act_widget:
                    for btn in act_widget.findChildren(QPushButton):
                        if btn.text() in ("🔊", "💾"):
                            btn.setEnabled(True)
            except Exception as e:
                log.warning(f"更新行 {vid} 状态失败: {e}")

        # 仅当选择“合成克隆声音”时，才把所有分句音频合并为一个整体音频
        merged_msg = ""
        if getattr(self, "_synthesize_merge", False):
            valid_wav_paths = []
            for idx in sorted(self.generated_voice_paths.keys()):
                wav_path = self.generated_voice_paths[idx]
                if wav_path and os.path.exists(wav_path):
                    valid_wav_paths.append(wav_path)

            if len(valid_wav_paths) > 1:
                self.stage_label.setText("⏳ 正在合并所有音频文件...")
                text = self.clone_text_input.toPlainText().strip()
                merged_filename = self._get_named_filename(text, "merged")
                out_voice_dir = self.voice_video_dir_input.text().strip()
                merged_wav_path = os.path.abspath(os.path.join(out_voice_dir, merged_filename))

                if self._merge_wav_files(valid_wav_paths, merged_wav_path):
                    merged_msg = f"\n\n已将所有分句音频合并导出为整体音频：\n{merged_filename}"
                    self.stage_label.setText("✅ 克隆人声音频及合并整体音频生成完成！")
                else:
                    self.stage_label.setText("⚠️ 音频生成完成，但合并失败")
                    merged_msg = "\n\n（合并失败，分句音频已单独生成）"
            else:
                merged_msg = "\n\n（仅有 1 行音频，无需合并）"

        QMessageBox.information(
            self.parent_widget,
            "合成成功",
            f"克隆人声合成完毕，共生成 {len(results)} 个音频文件。{merged_msg}"
        )

    def _on_voice_error(self, err):
        self.btn_synthesize_split.setEnabled(True)
        self.btn_synthesize_merge.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("❌ 合成失败")
        if "ConnectionRefusedError" in err or "Max retries exceeded" in err or "Failed to establish a new connection" in err or "ConnectionError" in err or "连接失败" in err:
            QMessageBox.critical(
                self.parent_widget,
                "服务未启动",
                "❌ 无法连接到 VoxCPM 服务。\n\n请前往「🤖 大模型配置」→「声音克隆配置」页面检查：\n1. VoxCPM 服务是否已启动\n2. API 接口地址是否正确\n3. 模型路径是否正确"
            )
        else:
            from gui.error_dialog import show_error_dialog
            show_error_dialog(self.parent_widget, "人声合成错误", f"处理过程中发生错误：\n{err}")

    def hideEvent(self, event):
        super().hideEvent(event)

    def _get_out_voice_dir(self, dir_path):
        dir_path = os.path.abspath(dir_path)
        path_str = dir_path.replace("\\", "/").rstrip("/")
        
        if path_str.endswith("outputs/voice_clone"):
            return dir_path
        if "/outputs/voice_clone/" in path_str + "/":
            idx = path_str.find("/outputs/voice_clone")
            parent = path_str[:idx]
            return os.path.abspath(os.path.join(parent, "outputs", "voice_clone"))
            
        base_parent = os.path.abspath(os.path.join(dir_path, ".."))
        return os.path.abspath(os.path.join(base_parent, "outputs", "voice_clone"))

    def _get_selected_sample_prefix(self):
        text = self.ref_audio_combo.currentText().strip()
        if text.startswith("🎵 本地: "):
            text = text[len("🎵 本地: "):]
        elif text.startswith("❌ ") or text.startswith("📂 ") or "未找到" in text:
            return ""
        
        # Split by typical separators: '-', '_', ' '
        for sep in ['-', '_', ' ']:
            if sep in text:
                prefix = text.split(sep)[0].strip()
                if prefix:
                    return prefix
        
        name, _ = os.path.splitext(text)
        return name

    @staticmethod
    def _get_first_n_chars(text, n):
        """取文案前 n 个字用于文件名：去除空白/换行与 Windows 非法字符。"""
        if not text:
            return ""
        compact = "".join(text.split())
        for c in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
            compact = compact.replace(c, "")
        compact = compact.strip(" .")
        return compact[:n]

    def _get_named_filename(self, text, kind="whole", idx=None):
        """克隆声音文件名：样本_文案前10字_日期[后缀].wav，避免同名覆盖。

        kind: whole=整体克隆 / merged=合并整体 / row=分句
        """
        from datetime import date
        date_str = date.today().strftime("%Y%m%d")
        sample = self._get_selected_sample_prefix()
        text10 = self._get_first_n_chars(text, 10)
        if not text10:
            text10 = "未命名" if kind != "row" else f"voice{idx or 1}"
        parts = [p for p in (sample, text10, date_str) if p]
        base = "_".join(parts)
        if kind == "merged":
            return f"{base}_merged.wav"
        if kind == "row" and idx:
            return f"{base}_row{idx}.wav"
        return f"{base}.wav"

    def _get_row_filename(self, idx):
        edit = self.row_edits.get(idx)
        text = edit.text().strip() if edit else ""
        return self._get_named_filename(text, "row", idx + 1)

    def _update_row_filename(self, idx):
        item_file = self.voice_table.item(idx, 1)
        if item_file:
            filename = self._get_row_filename(idx)
            stem, _ = os.path.splitext(filename)
            item_file.setText(filename)
            item_file.setData(Qt.UserRole, stem)

    def _update_table_filenames(self):
        for idx in range(self.voice_table.rowCount()):
            self._update_row_filename(idx)

    def _get_widget_row(self, widget):
        for r in range(self.voice_table.rowCount()):
            if self.voice_table.cellWidget(r, 2) == widget:
                return r
        return -1

    def _get_button_row(self, button):
        for r in range(self.voice_table.rowCount()):
            cell_w = self.voice_table.cellWidget(r, 4)
            if cell_w:
                if button in cell_w.findChildren(QPushButton):
                    return r
        return -1

    def _merge_wav_files(self, input_paths, output_path):
        import wave
        if not input_paths:
            return False
        try:
            with wave.open(input_paths[0], 'rb') as first_wav:
                params = first_wav.getparams()
            with wave.open(output_path, 'wb') as out_wav:
                out_wav.setparams(params)
                for path in input_paths:
                    with wave.open(path, 'rb') as wav:
                        out_wav.writeframes(wav.readframes(wav.getnframes()))
            return True
        except Exception as e:
            log.warning(f"使用 wave 模块合并 WAV 失败，尝试 ffmpeg: {e}")
            try:
                ffmpeg_path = find_ffmpeg()
                if not ffmpeg_path:
                    return False
                
                concat_txt = output_path + ".concat.txt"
                with open(concat_txt, "w", encoding="utf-8") as f:
                    for path in input_paths:
                        safe_path = path.replace("\\", "/")
                        f.write(f"file '{safe_path}'\n")
                
                cmd = [
                    ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
                    "-c", "copy", output_path
                ]
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                try:
                    if os.path.exists(concat_txt):
                        os.remove(concat_txt)
                except Exception:
                    pass
                return r.returncode == 0
            except Exception as fe:
                log.error(f"ffmpeg 合并 WAV 失败: {fe}")
                return False

    def _clone_whole_audio(self):
        text = self.clone_text_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self.parent_widget, "提示", "请先输入待克隆整体文案！")
            return
            
        ref_audio = self.get_ref_audio_path()
        if not ref_audio:
            QMessageBox.warning(self.parent_widget, "未选择声音样本", "请先选择参考声音样本！")
            return
        if not os.path.exists(ref_audio):
            QMessageBox.warning(self.parent_widget, "声音样本不存在", f"参考声音样本文件不存在，请重新选择：\n{ref_audio}")
            return

        out_voice_dir = self.voice_video_dir_input.text().strip()
        if not out_voice_dir or not os.path.exists(out_voice_dir):
            QMessageBox.warning(self.parent_widget, "路径无效", "请选择有效的音频输出目录。")
            return

        self.btn_clone_whole.setEnabled(False)
        self.btn_clone_whole.setText("⏳ 正在进行整体克隆...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label.setText("正在进行整体克隆...")

        cfg = getattr(self.main_window, "ai_config", {}) or {}
        model_path = cfg.get("vox_model_path", "")
        voice_mode = cfg.get("vox_mode", "api")
        api_url = cfg.get("vox_api_url", "") or voxcpm_client.tts_url()
        timesteps = cfg.get("vox_timesteps", 20)
        cfg_val = cfg.get("vox_cfg", 2.0)

        whole_filename = self._get_named_filename(text, "whole")
        out_wav_path = os.path.abspath(os.path.join(out_voice_dir, whole_filename))

        tasks = [(-1, text, "whole", out_wav_path)]
        
        self.voice_worker = VoiceCloneWorker(
            tasks=tasks,
            voice_ref_audio=ref_audio,
            voice_ref_text=self.ref_text_input.toPlainText().strip(),
            voice_mode=voice_mode,
            voice_api_url=api_url,
            voice_cli_checkpoint=model_path,
            temp_dir=out_voice_dir,
            task_type="voice",
            inference_timesteps=timesteps,
            cfg_value=cfg_val
        )
        self.voice_worker.stage.connect(lambda t: self.stage_label.setText(t))
        self.voice_worker.progress.connect(lambda v: self.progress_bar.setValue(v))
        
        def on_whole_finished(results):
            self.btn_clone_whole.setEnabled(True)
            self.btn_clone_whole.setText("整体克隆人声")
            self.progress_bar.setValue(100)
            self.stage_label.setText("✅ 整体克隆人声生成成功！可以开始点击一键拆分填充。")
            self._check_whole_audio_exists()
            QMessageBox.information(
                self.parent_widget,
                "生成成功",
                f"整体克隆人声音频生成完毕，已保存至：\n{out_wav_path}"
            )
            
        def on_whole_error(err):
            self.btn_clone_whole.setEnabled(True)
            self.btn_clone_whole.setText("整体克隆人声")
            self.progress_bar.setValue(0)
            self.stage_label.setText("❌ 整体生成失败")
            if "ConnectionRefusedError" in err or "Max retries exceeded" in err or "Failed to establish a new connection" in err or "ConnectionError" in err or "连接失败" in err:
                QMessageBox.critical(
                    self.parent_widget,
                    "服务未启动",
                    "❌ 无法连接到 VoxCPM 服务。\n\n请前往「🤖 大模型配置」→「声音克隆配置」页面检查：\n1. VoxCPM 服务是否已启动\n2. API 接口地址是否正确\n3. 模型路径是否正确"
                )
            else:
                QMessageBox.critical(self.parent_widget, "人声合成错误", f"处理过程中发生错误：\n{err}")
            
        self.voice_worker.finished.connect(on_whole_finished)
        self.voice_worker.error.connect(on_whole_error)
        self.voice_worker.start()

    def _split_and_populate_text_only(self, text):
        llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

        if llm_model:
            self.btn_split_text.setEnabled(False)
            self.btn_split_text.setText("⏳ AI 拆分中...")
            self.stage_label.setText("⏳ 正在使用大模型智能拆分文案...")

            self.split_worker = SentenceSplitterLLMWorker(llm_model, text)

            def on_split_done(result_text):
                self.btn_split_text.setEnabled(True)
                self.btn_split_text.setText("一键拆分填充")
                self.stage_label.setText("✅ AI 智能拆分完成")

                lines = [line.strip() for line in result_text.split('\n') if line.strip()]
                # 校验 LLM 是否漏字（如误删编号），漏字则退回本地规则拆分
                fallback = self._validate_llm_split(text, lines)
                if fallback is not None:
                    lines = fallback
                    self.stage_label.setText("⚠️ AI 拆分疑似漏字，已自动退回本地规则拆分")
                lines = self._merge_short_fragments(lines)
                self._clear_table()
                for s in lines:
                    row_idx = self.voice_table.rowCount()
                    self.voice_table.insertRow(row_idx)
                    self._setup_row_widgets(row_idx)
                    edit = self.row_edits.get(row_idx)
                    if edit:
                        edit.setText(s)
                self._adjust_table_height()
                QMessageBox.information(self.parent_widget, "提示", f"已通过 AI 智能拆分并填入下方列表，共 {self.voice_table.rowCount()} 行。")

            def on_split_err(err):
                log.warning(f"AI 智能拆分失败: {err}，将使用本地分词规则进行拆分。")
                self.btn_split_text.setEnabled(True)
                self.btn_split_text.setText("一键拆分填充")
                self.stage_label.setText("⚠️ AI 智能拆分失败，已自动使用本地规则")
                
                self._populate_sentences_to_table(text)
                QMessageBox.information(self.parent_widget, "提示", f"AI 拆分失败，已自动通过本地规则拆分并填入下方列表，共 {self.voice_table.rowCount()} 行。")

            self.split_worker.finished.connect(on_split_done)
            self.split_worker.error.connect(on_split_err)
            self.split_worker.start()
        else:
            self._populate_sentences_to_table(text)
            QMessageBox.information(self.parent_widget, "提示", f"已成功通过本地标点规则拆分并填入下方列表，共 {self.voice_table.rowCount()} 行。")

    def _process_alignment_and_populate(self, lines, segments, whole_audio_path, out_voice_dir):
        # 优先用 segments 的 word 级时间戳做精确对齐
        alignments = self._get_alignments_from_segments(lines, segments)

        if not alignments:
            # 退回 segment 级线性插值（segments 本身已含 start/end/text）
            if segments:
                alignments = self._align_segments(lines, segments)

        if not alignments:
            # Fallback to text-only population without audios
            self._clear_table()
            for s in lines:
                row_idx = self.voice_table.rowCount()
                self.voice_table.insertRow(row_idx)
                self._setup_row_widgets(row_idx)
                edit = self.row_edits.get(row_idx)
                if edit:
                    edit.setText(s)
            self._adjust_table_height()
            return
            
        self._clear_table()
        for idx, s in enumerate(lines):
            row_idx = self.voice_table.rowCount()
            self.voice_table.insertRow(row_idx)
            self._setup_row_widgets(row_idx)
            
            edit = self.row_edits.get(row_idx)
            if edit:
                edit.setText(s)
                
            start_t, end_t = alignments[idx]
            if start_t != 0.0 or end_t != 0.0:
                filename = self._get_row_filename(row_idx)
                out_wav_path = os.path.abspath(os.path.join(out_voice_dir, filename))
                
                if self._cut_audio(whole_audio_path, start_t, end_t, out_wav_path):
                    self.generated_voice_paths[row_idx] = out_wav_path
                    lbl_status = self.voice_table.cellWidget(row_idx, 3)
                    if isinstance(lbl_status, QLabel):
                        lbl_status.setText(os.path.basename(out_wav_path))
                        lbl_status.setStyleSheet("color: #2ecc71; font-size: 12px; padding: 4px;")
                    act_widget = self.voice_table.cellWidget(row_idx, 4)
                    if act_widget:
                        for btn in act_widget.findChildren(QPushButton):
                            if btn.text() in ("🔊", "💾"):
                                btn.setEnabled(True)
        self._adjust_table_height()

    def _parse_srt(self, srt_content):
        import re
        segments = []
        pattern = re.compile(
            r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:[^\n]+\n*)+)'
        )
        matches = pattern.findall(srt_content)
        for m in matches:
            start_str = m[1]
            end_str = m[2]
            text = m[3].strip()
            
            start_s = self._srt_time_to_seconds(start_str)
            end_s = self._srt_time_to_seconds(end_str)
            
            segments.append({
                'start': start_s,
                'end': end_s,
                'text': text
            })
        return segments

    def _srt_time_to_seconds(self, time_str):
        parts = time_str.replace(',', '.').split(':')
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s

    def _align_segments(self, sentences, srt_segments):
        # Segment-Level Linear Interpolation (SLLI) fallback
        char_times = []
        for seg in srt_segments:
            seg_text = seg.get('text', '')
            seg_clean = "".join(c for c in seg_text if c.isalnum()).lower()
            
            S = seg['start']
            E = seg['end']
            L = len(seg_clean)
            if L > 0:
                D = E - S
                for k in range(L):
                    char_start = S + D * (k / L)
                    char_end = S + D * ((k + 1) / L)
                    char_times.append((char_start, char_end))
                    
        alignment = []
        char_idx = 0
        total_chars = len(char_times)
        
        for s_text in sentences:
            s_clean = "".join(c for c in s_text if c.isalnum()).lower()
            n = len(s_clean)
            if n == 0 or total_chars == 0:
                alignment.append((0.0, 0.0))
                continue
                
            start_char_idx = min(char_idx, total_chars - 1)
            end_char_idx = min(char_idx + n - 1, total_chars - 1)
            
            start_time = char_times[start_char_idx][0]
            end_time = char_times[end_char_idx][1]
            
            # Apply padding
            start_time = max(0.0, start_time - 0.05)
            end_time = end_time + 0.05
            
            if start_time >= end_time:
                alignment.append((0.0, 0.0))
            else:
                alignment.append((start_time, end_time))
            char_idx += n
            
        return alignment

    def _cut_audio(self, input_path, start_time, end_time, output_path):
        from gui.video_montage_page import find_ffmpeg
        import subprocess
        import sys
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            log.error("未找到 ffmpeg，无法裁剪音频")
            return False
            
        cmd = [
            ffmpeg_path, "-y",
            "-ss", f"{start_time:.3f}",
            "-to", f"{end_time:.3f}",
            "-i", input_path,
            "-c", "copy",
            output_path
        ]
        log.info(f"执行裁剪命令: {' '.join(cmd)}")
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if r.returncode != 0:
                log.error(f"裁剪音频失败 (返回码 {r.returncode}):\nSTDOUT: {r.stdout}\nSTDERR: {r.stderr}")
                return False
            return True
        except Exception as e:
            log.exception(f"裁剪进程执行异常: {e}")
            return False

    def _get_alignments_from_json(self, lines, json_path):
        import json
        if not os.path.exists(json_path):
            return None
            
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                result = json.load(f)
        except Exception as e:
            log.warning(f"读取 WhisperX JSON 失败: {e}")
            return None
            
        all_words = []
        for seg in result.get("segments", []):
            for word_info in seg.get("words", []):
                if "start" in word_info and "end" in word_info:
                    all_words.append({
                        'word': word_info['word'].strip(),
                        'start': float(word_info['start']),
                        'end': float(word_info['end'])
                    })
                    
        if not all_words:
            return None
            
        alignments = []
        word_idx = 0
        num_words = len(all_words)
        
        for s_text in lines:
            s_clean = "".join(c for c in s_text if c.isalnum()).lower()
            if not s_clean:
                alignments.append((0.0, 0.0))
                continue
                
            matched_words = []
            accumulated_chars = ""
            
            while word_idx < num_words:
                word_info = all_words[word_idx]
                w_text = word_info['word']
                w_clean = "".join(c for c in w_text if c.isalnum()).lower()
                
                accumulated_chars += w_clean
                matched_words.append(word_info)
                word_idx += 1
                
                if len(accumulated_chars) >= len(s_clean) * 0.85:
                    break
                    
            if matched_words:
                start_time = matched_words[0]['start']
                end_time = matched_words[-1]['end']
                
                # Add tiny padding
                start_time = max(0.0, start_time - 0.05)
                end_time = end_time + 0.05
                
                alignments.append((start_time, end_time))
            else:
                alignments.append((0.0, 0.0))

        return alignments

    def _get_alignments_from_segments(self, lines, segments):
        """基于远程 ASR 返回的 segments（含 word 级时间戳）做句子对齐。

        数据源：segments[i].words[j] = {"word","start","end"}（与旧本地 WhisperX 一致）。
        算法与 _get_alignments_from_json 相同：按字符数贪婪累积到目标句子的 85% 即取首尾 word 时间戳。
        若所有 segment 都无 words 字段，返回 None（调用方退回 SRT 级插值）。
        """
        all_words = []
        for seg in segments or []:
            for word_info in (seg.get("words") or []):
                if "start" in word_info and "end" in word_info:
                    all_words.append({
                        'word': (word_info.get('word') or '').strip(),
                        'start': float(word_info['start']),
                        'end': float(word_info['end'])
                    })

        if not all_words:
            return None

        alignments = []
        word_idx = 0
        num_words = len(all_words)

        for s_text in lines:
            s_clean = "".join(c for c in s_text if c.isalnum()).lower()
            if not s_clean:
                alignments.append((0.0, 0.0))
                continue

            matched_words = []
            accumulated_chars = ""

            while word_idx < num_words:
                word_info = all_words[word_idx]
                w_text = word_info['word']
                w_clean = "".join(c for c in w_text if c.isalnum()).lower()

                accumulated_chars += w_clean
                matched_words.append(word_info)
                word_idx += 1

                if len(accumulated_chars) >= len(s_clean) * 0.85:
                    break

            if matched_words:
                start_time = max(0.0, matched_words[0]['start'] - 0.05)
                end_time = matched_words[-1]['end'] + 0.05
                alignments.append((start_time, end_time))
            else:
                alignments.append((0.0, 0.0))

        return alignments

    def _check_whole_audio_exists(self):
        out_voice_dir = self.voice_video_dir_input.text().strip()
        if not out_voice_dir:
            self.btn_play_whole.setEnabled(False)
            return
        text = self.clone_text_input.toPlainText().strip()
        if not text:
            self.btn_play_whole.setEnabled(False)
            return
        whole_filename = self._get_named_filename(text, "whole")
        whole_audio_path = os.path.abspath(os.path.join(out_voice_dir, whole_filename))
        has_file = os.path.exists(whole_audio_path)
        self.btn_play_whole.setEnabled(has_file)

    def _play_whole_audio(self):
        out_voice_dir = self.voice_video_dir_input.text().strip()
        text = self.clone_text_input.toPlainText().strip()
        whole_filename = self._get_named_filename(text, "whole")
        whole_audio_path = os.path.abspath(os.path.join(out_voice_dir, whole_filename))
        
        if os.path.exists(whole_audio_path):
            self._play_audio(whole_audio_path)
