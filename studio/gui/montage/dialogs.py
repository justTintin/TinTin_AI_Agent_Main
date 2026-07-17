# -*- coding: utf-8 -*-
"""智能混剪 - 对话框：文本编辑、脚本对比、配音成品、合成成品、产品文案输入、配音行详情。"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
                               QListWidget, QListWidgetItem, QDialogButtonBox, QPlainTextEdit, QWidget)
from PySide6.QtCore import Qt
from gui.montage.widgets import ReadOnlyDoubleClickLineEdit



class TextEditDialog(QDialog):
    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(450, 250)
        self.resize(500, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Theme-consistent dialog: only style widget-specific elements
        self.setStyleSheet("""
            QTextEdit {
                border: 1px solid rgba(128,128,128,0.15);
                border-radius: 4px;
                font-size: 13px;
                padding: 6px;
            }
            QTextEdit:focus {
                border: 1px solid #2ecc71;
            }
        """)

        lbl = QLabel("配音文案编辑:")
        layout.addWidget(lbl)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        layout.addWidget(self.text_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2ecc71;
                    color: white;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #27ae60;
                }
            """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_text(self):
        return self.text_edit.toPlainText().strip()



class ScriptCompareDialog(QDialog):
    def __init__(self, original_text, current_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚖️ 配音文案对比")
        self.setMinimumSize(700, 400)
        self.resize(800, 480)
        
        # Theme-consistent dialog style
        self.setStyleSheet("""
            QPlainTextEdit {
                border: 1px solid #374151;
                border-radius: 6px;
                font-size: 13px;
                line-height: 1.4;
                padding: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        title_lbl = QLabel("📖 左右对比：左侧为原视频文案，右侧为AI修改/当前配音文案")
        title_lbl.setStyleSheet("font-size: 14px; color: #60a5fa; font-weight: bold;")
        layout.addWidget(title_lbl)
        
        # Splitter or side-by-side layout
        h_layout = QHBoxLayout()
        h_layout.setSpacing(12)
        
        # Left: Original
        left_widget = QWidget()
        left_vbox = QVBoxLayout(left_widget)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(6)
        left_vbox.addWidget(QLabel("📝 原始文案 (原视频内容):"))
        self.original_edit = QPlainTextEdit()
        self.original_edit.setPlainText(original_text)
        self.original_edit.setReadOnly(True)
        left_vbox.addWidget(self.original_edit)
        h_layout.addWidget(left_widget)
        
        # Right: Current/Modified
        right_widget = QWidget()
        right_vbox = QVBoxLayout(right_widget)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(6)
        right_vbox.addWidget(QLabel("✨ AI修改后 / 当前文案:"))
        self.current_edit = QPlainTextEdit()
        self.current_edit.setPlainText(current_text)
        right_vbox.addWidget(self.current_edit)
        h_layout.addWidget(right_widget)
        
        layout.addLayout(h_layout)
        
        # Bottom buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        
        btn_use_original = mdi_button("还原为原始文案", "backward")
        btn_use_original.setStyleSheet("""
            QPushButton {
                background-color: #4b5563;
            }
            QPushButton:hover {
                background-color: #374151;
            }
        """)
        btn_use_original.clicked.connect(self._use_original)
        btn_box.addWidget(btn_use_original)
        
        btn_save = mdi_button("保存修改", "save")
        btn_save.clicked.connect(self.accept)
        btn_box.addWidget(btn_save)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #d1d5db;
                border: 1px solid #4b5563;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        
        layout.addLayout(btn_box)
        
    def _use_original(self):
        self.current_edit.setPlainText(self.original_edit.toPlainText())
        
    def get_text(self):
        return self.current_edit.toPlainText().strip()



class DubbedVideosDialog(QDialog):
    def __init__(self, parent, results):
        super().__init__(parent)
        self.setWindowTitle("🎉 配音替换完成")
        self.setMinimumSize(600, 400)
        self.resize(650, 450)
        
        # Theme-consistent dialog (no custom QDialog/QPushButton base style)
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid #2e2e32;
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton#primary_button {
                font-weight: 700;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header_lbl = QLabel("✨ <b>所有视频配音替换完毕！已成功为您生成以下配音文件：</b>")
        header_lbl.setStyleSheet("font-size: 14px; color: #2ecc71;")
        layout.addWidget(header_lbl)

        if results:
            first_path = list(results.values())[0]
            out_dir = os.path.dirname(first_path)
            dir_lbl = QLabel(f"📂 <b>保存目录：</b> <font color='#3498db'>{out_dir}</font>")
            dir_lbl.setWordWrap(True)
            dir_lbl.setStyleSheet("font-size: 12px;")
            layout.addWidget(dir_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        for orig_path, dubbed_path in results.items():
            item = QListWidgetItem()
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 4, 8, 4)
            item_layout.setSpacing(10)

            name_lbl = QLabel(os.path.basename(dubbed_path))
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            name_lbl.setToolTip(f"原视频: {orig_path}\n配音视频: {dubbed_path}")
            item_layout.addWidget(name_lbl, 1)

            btn_play = mdi_button("播放视频", "play")
            btn_play.clicked.connect(lambda checked=False, path=dubbed_path: self._play_video(path))
            item_layout.addWidget(btn_play)

            btn_locate = mdi_button("打开所在目录", "folder")
            btn_locate.clicked.connect(lambda checked=False, path=dubbed_path: self._locate_video(path))
            item_layout.addWidget(btn_locate)

            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        btn_open_all = mdi_button("打开整体输出文件夹", "folder")
        if results:
            btn_open_all.clicked.connect(lambda checked=False, path=out_dir: self._open_dir(path))
        footer_layout.addWidget(btn_open_all)

        btn_ok = QPushButton("确认并返回")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        footer_layout.addWidget(btn_ok)

        layout.addLayout(footer_layout)

    def _play_video(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _locate_video(self, path):
        dir_p = os.path.dirname(path)
        self._open_dir(dir_p)

    def _open_dir(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "打开失败", f"无法打开该目录:\n{e}")



class FinalMixedVideosDialog(QDialog):
    def __init__(self, parent, paths):
        super().__init__(parent)
        self.setWindowTitle("🎉 最终合成视频列表")
        self.setMinimumSize(600, 400)
        self.resize(650, 450)
        
        # Theme-consistent dialog (no custom QDialog/QPushButton base style)
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid #2e2e32;
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton#primary_button {
                font-weight: 700;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header_lbl = QLabel("✨ <b>批量音视频及配乐合成完毕！已成功为您生成以下视频文件：</b>")
        header_lbl.setStyleSheet("font-size: 14px; color: #2ecc71;")
        layout.addWidget(header_lbl)

        if paths:
            out_dir = os.path.dirname(paths[0])
            dir_lbl = QLabel(f"📂 <b>保存目录：</b> <font color='#3498db'>{out_dir}</font>")
            dir_lbl.setWordWrap(True)
            dir_lbl.setStyleSheet("font-size: 12px;")
            layout.addWidget(dir_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        for path in paths:
            item = QListWidgetItem()
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 4, 8, 4)
            item_layout.setSpacing(10)

            name_lbl = QLabel(os.path.basename(path))
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            name_lbl.setToolTip(f"输出视频: {path}")
            item_layout.addWidget(name_lbl, 1)

            btn_play = mdi_button("播放视频", "play")
            btn_play.clicked.connect(lambda checked=False, p=path: self._play_video(p))
            item_layout.addWidget(btn_play)

            btn_locate = mdi_button("打开所在目录", "folder")
            btn_locate.clicked.connect(lambda checked=False, p=path: self._locate_video(p))
            item_layout.addWidget(btn_locate)

            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        btn_open_all = mdi_button("打开整体输出文件夹", "folder")
        if paths:
            btn_open_all.clicked.connect(lambda checked=False, p=out_dir: self._open_dir(p))
        footer_layout.addWidget(btn_open_all)

        btn_ok = QPushButton("确认并返回")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        footer_layout.addWidget(btn_ok)

        layout.addLayout(footer_layout)

    def _play_video(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "播放失败", f"无法播放该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _locate_video(self, path):
        if os.path.exists(path):
            try:
                subprocess.Popen(f'explorer /select,"{path}"')
            except Exception as e:
                QMessageBox.warning(self, "定位失败", f"无法定位该视频:\n{e}")
        else:
            QMessageBox.warning(self, "文件不存在", "视频文件未找到，请确认是否已被删除或移动。")

    def _open_dir(self, path):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "打开失败", f"无法打开该目录:\n{e}")



class ProductCopyInputDialog(QDialog):
    """输入品牌/产品/型号/补充卖点，用于生成口播文案。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✍ 生成口播文案")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel("输入产品信息，由大模型生成该组合视频的口播文案："))

        def _row(lbl_text, placeholder):
            r = QHBoxLayout()
            l = QLabel(lbl_text)
            l.setFixedWidth(64)
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            r.addWidget(l)
            r.addWidget(e, 1)
            layout.addLayout(r)
            return e

        self.brand_in = _row("品牌：", "如 罗技 / Logitech")
        self.product_in = _row("产品：", "如 鼠标 / 键盘 / 无线耳机")
        self.model_in = _row("型号：", "如 G502 / MX Master 3S")

        layout.addWidget(QLabel("补充卖点（可选）："))
        self.extra_in = QTextEdit()
        self.extra_in.setPlaceholderText("如 8K回报率、轻量化、长续航……（可留空）")
        self.extra_in.setFixedHeight(60)
        layout.addWidget(self.extra_in)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("生成")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def get_values(self):
        return (self.brand_in.text().strip(), self.product_in.text().strip(),
                self.model_in.text().strip(), self.extra_in.toPlainText().strip())



class VoiceRowDetailWidget(QWidget):
    def __init__(self, basename, filepath, original_text, edit, wav_path=None,
                 status_widget=None, action_widgets=None, video_duration_sec=0.0,
                 voice_duration_sec=0.0, play_original_btn=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        
        # Line 1: video filename + play original + status + action buttons
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        
        lbl_video = QLabel(f"🎥 视频: {basename}")
        lbl_video.setObjectName("card_title")
        lbl_video.setToolTip(filepath)
        top_layout.addWidget(lbl_video)

        if play_original_btn:
            top_layout.addWidget(play_original_btn)

        top_layout.addStretch()

        if status_widget:
            top_layout.addWidget(status_widget, 0)
        if action_widgets:
            for w in action_widgets:
                top_layout.addWidget(w, 0)
        
        layout.addLayout(top_layout)
        
        # Line 2: Original script + video duration
        row_original = QHBoxLayout()
        row_original.setContentsMargins(0, 0, 0, 0)
        lbl_orig_tag = QLabel("📝 原文: ")
        lbl_orig_tag.setObjectName("muted_text")
        lbl_orig_tag.setFixedWidth(48)
        orig_val = ReadOnlyDoubleClickLineEdit(original_text if original_text else "(无)")
        row_original.addWidget(lbl_orig_tag)
        row_original.addWidget(orig_val, 1)
        if video_duration_sec > 0:
            vid_dur_str = f"{int(video_duration_sec // 60)}:{int(video_duration_sec % 60):02d}"
            lbl_vid_dur = QLabel(f"⏱ {vid_dur_str}")
            lbl_vid_dur.setStyleSheet("color: #f1c40f; font-size: 11px; font-weight: bold;")
            lbl_vid_dur.setFixedWidth(60)
            row_original.addWidget(lbl_vid_dur)
        layout.addLayout(row_original)
        
        # Line 3: AI-modified script + voice duration
        row_edit = QHBoxLayout()
        row_edit.setContentsMargins(0, 0, 0, 0)
        lbl_edit_tag = QLabel("✨ 修改后: ")
        lbl_edit_tag.setObjectName("accent_text")
        row_edit.addWidget(lbl_edit_tag)
        row_edit.addWidget(edit, 1)
        voice_dur_str = ""
        if voice_duration_sec > 0:
            voice_dur_str = f"{int(voice_duration_sec // 60)}:{int(voice_duration_sec % 60):02d}"
            voice_dur_style = "color: #2ecc71; font-size: 11px; font-weight: bold;"
        else:
            voice_dur_str = "--:--"
            voice_dur_style = "color: #7f8c8d; font-size: 11px;"
        self.lbl_voice_duration = QLabel(f"⏱ {voice_dur_str}")
        self.lbl_voice_duration.setStyleSheet(voice_dur_style)
        self.lbl_voice_duration.setFixedWidth(60)
        row_edit.addWidget(self.lbl_voice_duration)
        layout.addLayout(row_edit)
