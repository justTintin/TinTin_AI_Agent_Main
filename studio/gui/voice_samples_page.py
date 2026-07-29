# -*- coding: utf-8 -*-
import os
import sys
import shutil
import json
import uuid
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
                               QFileDialog, QProgressBar, QMessageBox, QFrame, QTableWidget,
                               QTableWidgetItem, QHeaderView, QWidget, QInputDialog, QDialog)
from PySide6.QtCore import Signal, QThread, Qt, QUrl
from utils.base_worker import BaseWorker
from PySide6.QtGui import QColor
from utils.logger_utils import log
from config.paths import PROJECT_ROOT

VOICE_SAMPLES_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "assets", "voice_samples"))
METADATA_PATH = os.path.join(VOICE_SAMPLES_DIR, "metadata.json")

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

def load_voice_samples():
    os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
    if not os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
        return []
    try:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            samples = json.load(f)
        # Always resolve path from filename relative to VOICE_SAMPLES_DIR
        # so the project can be moved without breaking sample references.
        for s in samples:
            if s.get("filename"):
                s["path"] = os.path.join(VOICE_SAMPLES_DIR, s["filename"])
        return samples
    except Exception as e:
        log.error(f"加载声音样本元数据失败: {e}")
        return []

def save_voice_samples(samples):
    os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
    try:
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(samples, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log.error(f"保存声音样本元数据失败: {e}")

from gui.base_page import BasePage


class VoiceSamplesPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self._media_player = None
        self._audio_output = None
        self.transcribe_workers = {}

    def setup(self):
        # Main layout
        main_layout = QVBoxLayout(self.parent_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)

        # Title
        heading = QLabel("🎭 声音样本库管理")
        heading.setObjectName("heading")
        main_layout.addWidget(heading, 0)

        # 1. Form Card for adding voice samples
        form_card = QFrame()
        form_card.setObjectName("card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(20, 20, 20, 20)

        form_title = QLabel("添加参考声音样本")
        form_title.setObjectName("card_title")
        form_layout.addWidget(form_title)

        # File path selection row
        row_file = QHBoxLayout()
        row_file.addWidget(QLabel("选择音频文件:"))
        self.file_path_input = QLineEdit()
        self.file_path_input.setReadOnly(True)
        self.file_path_input.setPlaceholderText("点击右侧按钮选择 wav/mp3/m4a 声音文件...")
        row_file.addWidget(self.file_path_input)
        
        btn_browse = QPushButton("浏览文件")
        btn_browse.setObjectName("secondary_button")
        btn_browse.clicked.connect(self._browse_audio_file)
        row_file.addWidget(btn_browse)
        form_layout.addLayout(row_file)

        # Sample display name row
        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("样本显示名称:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：磁性男播音、温柔女声等...")
        row_name.addWidget(self.name_input)
        form_layout.addLayout(row_name)

        # Reference text description row
        row_text = QHBoxLayout()
        row_text.addWidget(QLabel("参考文案(可选):"))
        self.ref_text_input = QTextEdit()
        self.ref_text_input.setPlaceholderText("选填。填入参考音频对应的说话文字，克隆时会自动填充参考文案框...")
        self.ref_text_input.setFixedHeight(50)
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
                border: 1px solid #3b82f6;
                background-color: rgba(255, 255, 255, 0.08);
            }
        """)
        row_text.addWidget(self.ref_text_input)
        form_layout.addLayout(row_text)

        # Form action buttons row
        row_form_actions = QHBoxLayout()
        self.btn_add_sample = QPushButton("➕ 添加声音样本")
        self.btn_add_sample.setObjectName("primary_button")
        self.btn_add_sample.clicked.connect(self._add_voice_sample)
        row_form_actions.addWidget(self.btn_add_sample)
        row_form_actions.addStretch()
        form_layout.addLayout(row_form_actions)

        main_layout.addWidget(form_card, 0)

        # 2. Table Card for listing existing samples
        table_card = QFrame()
        table_card.setObjectName("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setSpacing(12)
        table_layout.setContentsMargins(20, 20, 20, 20)

        table_header_row = QHBoxLayout()
        table_title = QLabel("已保存的声音样本库")
        table_title.setObjectName("card_title")
        table_header_row.addWidget(table_title)
        table_header_row.addStretch()
        table_layout.addLayout(table_header_row)

        # Table
        self.samples_table = QTableWidget()
        self.samples_table.setColumnCount(5)
        self.samples_table.setHorizontalHeaderLabels(["序号", "样本名称", "参考文案", "文件名", "操作"])
        self.samples_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.samples_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.samples_table.setColumnWidth(1, 150)
        self.samples_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.samples_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.samples_table.setColumnWidth(3, 180)
        self.samples_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.samples_table.setColumnWidth(4, 160)
        self.samples_table.verticalHeader().setDefaultSectionSize(38)
        self.samples_table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        table_layout.addWidget(self.samples_table, 1)

        main_layout.addWidget(table_card, 1)

        # Bottom status
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("muted_text")
        main_layout.addWidget(self.status_label, 0)



        # Load initial data
        self._load_table_data()

    def _browse_audio_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "选择音频样本",
            "",
            "Audio Files (*.wav *.mp3 *.m4a);;All Files (*)"
        )
        if path:
            self.file_path_input.setText(path)
            # Pre-fill name input if it is empty
            if not self.name_input.text().strip():
                filename = os.path.basename(path)
                self.name_input.setText(os.path.splitext(filename)[0])

    def _add_voice_sample(self):
        filepath = self.file_path_input.text().strip()
        name = self.name_input.text().strip()
        ref_text = self.ref_text_input.toPlainText().strip()

        if not filepath or not os.path.exists(filepath):
            QMessageBox.warning(self.parent_widget, "提示", "请选择有效的参考音频文件。")
            return
        if not name:
            QMessageBox.warning(self.parent_widget, "提示", "请输入样本名称。")
            return

        self.btn_add_sample.setEnabled(False)
        self.status_label.setText("正在添加样本...")

        try:
            # Copy file to assets, preserving the original filename
            os.makedirs(VOICE_SAMPLES_DIR, exist_ok=True)
            orig_filename = os.path.basename(filepath)
            base, ext = os.path.splitext(orig_filename)
            filename = orig_filename
            counter = 1
            while os.path.exists(os.path.join(VOICE_SAMPLES_DIR, filename)):
                filename = f"{base}_{counter}{ext}"
                counter += 1
            dest_path = os.path.join(VOICE_SAMPLES_DIR, filename)
            shutil.copy2(filepath, dest_path)

            # Save metadata
            samples = load_voice_samples()
            samples.append({
                "id": str(uuid.uuid4())[:8],
                "name": name,
                "filename": filename,
                "ref_text": ref_text
            })
            save_voice_samples(samples)

            # Reset form
            self.file_path_input.clear()
            self.name_input.clear()
            self.ref_text_input.clear()

            self._load_table_data()
            self.status_label.setText("✅ 成功添加声音样本库！")
            QMessageBox.information(self.parent_widget, "成功", f"人声样本 '{name}' 已成功导入样本库！")
        except Exception as e:
            log.error(f"添加人声样本失败: {e}")
            self.status_label.setText("❌ 添加失败")
            QMessageBox.critical(self.parent_widget, "错误", f"添加失败: {e}")
        finally:
            self.btn_add_sample.setEnabled(True)

    def _load_table_data(self):
        self.samples_table.setRowCount(0)
        samples = load_voice_samples()
        
        # Sort by name
        samples.sort(key=lambda x: x.get("name", "").lower())
        
        self.samples_table.setRowCount(len(samples))
        for i, s in enumerate(samples):
            # 0: Index
            item_idx = QTableWidgetItem(str(i + 1))
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.samples_table.setItem(i, 0, item_idx)

            # 1: Name
            item_name = QTableWidgetItem(s.get("name", ""))
            item_name.setFlags(item_name.flags() & ~Qt.ItemIsEditable)
            self.samples_table.setItem(i, 1, item_name)

            # 2: Ref text
            item_text = QTableWidgetItem(s.get("ref_text", ""))
            item_text.setFlags(item_text.flags() & ~Qt.ItemIsEditable)
            item_text.setData(Qt.UserRole, s.get("id"))
            self.samples_table.setItem(i, 2, item_text)

            # 3: Filename
            item_file = QTableWidgetItem(s.get("filename", ""))
            item_file.setFlags(item_file.flags() & ~Qt.ItemIsEditable)
            self.samples_table.setItem(i, 3, item_file)

            # 4: Action row with Play, Rename, Delete
            widget = QWidget()
            h_layout = QHBoxLayout(widget)
            h_layout.setContentsMargins(4, 2, 4, 2)
            h_layout.setSpacing(4)

            sample_id = s.get("id")
            path = s.get("path")

            btn_play = QPushButton("🔊")
            btn_play.setToolTip("播放")
            btn_play.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_play.setFixedWidth(28)
            btn_play.clicked.connect(lambda checked=False, p=path: self._play_sample(p))
            h_layout.addWidget(btn_play)

            # Transcribe/generate text button (always visible)
            btn_asr = QPushButton("📝")
            btn_asr.setToolTip("根据音频生成/更新参考文案")
            btn_asr.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_asr.setFixedWidth(28)
            btn_asr.clicked.connect(lambda checked=False, p=path, sid=sample_id: self._generate_ref_text(p, sid))
            h_layout.addWidget(btn_asr)

            btn_rename = QPushButton("✏️")
            btn_rename.setToolTip("重命名")
            btn_rename.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_rename.setFixedWidth(28)
            btn_rename.clicked.connect(lambda checked=False, idx=i, sid=sample_id: self._rename_sample(idx, sid))
            h_layout.addWidget(btn_rename)

            btn_delete = QPushButton("🗑️")
            btn_delete.setToolTip("删除")
            btn_delete.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_delete.setFixedWidth(28)
            btn_delete.clicked.connect(lambda checked=False, idx=i, sid=sample_id: self._delete_sample(idx, sid))
            h_layout.addWidget(btn_delete)

            self.samples_table.setCellWidget(i, 4, widget)

    def _play_sample(self, wav_path):
        if not wav_path or not os.path.exists(wav_path):
            QMessageBox.warning(self.parent_widget, "错误", "音频文件不存在，无法播放。")
            return
        try:
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
            log.error(f"播放样本音频失败: {e}")

    def _rename_sample(self, row_idx, sample_id):
        samples = load_voice_samples()
        target = None
        for s in samples:
            if s.get("id") == sample_id:
                target = s
                break
        if not target:
            return
            
        new_name, ok = QInputDialog.getText(
            self.parent_widget,
            "重命名样本",
            "请输入新的样本名称:",
            QLineEdit.Normal,
            target.get("name", "")
        )
        if ok and new_name.strip():
            target["name"] = new_name.strip()
            save_voice_samples(samples)
            self._load_table_data()

    def _delete_sample(self, row_idx, sample_id):
        reply = QMessageBox.question(
            self.parent_widget,
            "确认删除",
            "确定要删除该声音样本吗？对应的本地音频文件也将被删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            samples = load_voice_samples()
            new_samples = []
            for s in samples:
                if s.get("id") == sample_id:
                    filepath = s.get("path", "")
                    if filepath and os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as e:
                            log.warning(f"删除物理文件失败: {e}")
                else:
                    new_samples.append(s)
            save_voice_samples(new_samples)
            self._load_table_data()

    def _generate_ref_text(self, wav_path, sample_id):
        if sample_id in self.transcribe_workers:
            QMessageBox.warning(self.parent_widget, "提示", "该样本正在识别中，请稍候...")
            return

        if not wav_path or not os.path.exists(wav_path):
            QMessageBox.warning(self.parent_widget, "错误", "音频文件不存在，无法生成文案。")
            return

        # Find row in table and update background to green + status text
        target_row = -1
        for row in range(self.samples_table.rowCount()):
            item = self.samples_table.item(row, 2)
            if item and item.data(Qt.UserRole) == sample_id:
                target_row = row
                break

        if target_row != -1:
            item = self.samples_table.item(target_row, 2)
            if item:
                item.setText("⏳ 正在生成文案...")
                item.setBackground(QColor(46, 204, 113, 80))  # Soft green

        self.status_label.setText(f"正在识别样本音频文本 (ID: {sample_id})...")

        # 远程 ASR worker：transcribe_remote → segments → segments_to_plain
        class RemoteAsrSampleWorker(BaseWorker):
            finished = Signal(list)
            error = Signal(str)

            def __init__(self, audio_path):
                super().__init__()
                self.audio_path = audio_path

            def do_work(self):
                try:
                    from utils.asr_client import transcribe_remote, read_asr_url
                    segments = transcribe_remote(
                        self.audio_path, read_asr_url(),
                        language="", task_type="transcribe",
                    )
                    self.finished.emit(segments)
                except Exception as e:
                    self.error.emit(str(e))

        worker = RemoteAsrSampleWorker(wav_path)
        self.transcribe_workers[sample_id] = worker

        def on_finished(segments):
            self.status_label.setText("✅ 识别参考音频文本完成")
            from utils.asr_client import segments_to_plain
            plain_text = segments_to_plain(segments)

            # 识别结果为空（音频无人声 / 服务端未返回内容）：给出提示，不静默保存空文案
            if not plain_text.strip():
                self.status_label.setText("⚠️ 未识别到文字")
                if sample_id in self.transcribe_workers:
                    del self.transcribe_workers[sample_id]
                self._load_table_data()
                QMessageBox.warning(
                    self.parent_widget, "未识别到文字",
                    "音频转写完成，但未识别出任何文字内容。\n\n"
                    "可能原因：音频中没有人声 / 音质过差 / 服务端 Whisper 模型异常。"
                )
                return

            def save_text(text_val):
                samples = load_voice_samples()
                for s in samples:
                    if s.get("id") == sample_id:
                        s["ref_text"] = text_val
                        break
                save_voice_samples(samples)

                if sample_id in self.transcribe_workers:
                    del self.transcribe_workers[sample_id]

                self._load_table_data()

            llm_model = self.main_window.ai_config.get("llm_model", "deepseek-chat")

            if llm_model and plain_text.strip():
                self.status_label.setText("⏳ 正在使用 AI 模型自动优化断句与标点...")
                self.punc_worker = PunctuationLLMWorker(llm_model, plain_text)

                def on_punc_done(punctuated_text):
                    save_text(punctuated_text)

                def on_punc_err(err):
                    log.warning(f"AI 添加标点失败: {err}，使用原始识别文本。")
                    save_text(plain_text)

                self.punc_worker.finished.connect(on_punc_done)
                self.punc_worker.error.connect(on_punc_err)
                self.punc_worker.start()
            else:
                save_text(plain_text)

        def on_error(err):
            self.status_label.setText("❌ 识别文本失败")
            if sample_id in self.transcribe_workers:
                del self.transcribe_workers[sample_id]
            self._load_table_data()
            QMessageBox.critical(self.parent_widget, "识别文本失败", f"无法从音频中提取文本：\n{err}")

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.start()

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

    def _on_table_cell_double_clicked(self, row, col):
        if col == 2:  # Reference script column
            item = self.samples_table.item(row, col)
            if not item:
                return
            sample_id = item.data(Qt.UserRole)
            if not sample_id:
                return
            
            samples = load_voice_samples()
            target = None
            for s in samples:
                if s.get("id") == sample_id:
                    target = s
                    break
            if not target:
                return
            
            from gui.video_montage_page import TextEditDialog
            
            dialog = TextEditDialog(f"编辑参考文案 - {target.get('name')}", target.get("ref_text", ""), self.parent_widget)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text().strip()
                target["ref_text"] = new_text
                save_voice_samples(samples)
                self._load_table_data()
