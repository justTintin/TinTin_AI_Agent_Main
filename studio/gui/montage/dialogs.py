# -*- coding: utf-8 -*-
"""智能混剪 - 对话框：文本编辑、脚本对比、配音成品、合成成品、产品文案输入、配音行详情。"""
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
                               QListWidget, QListWidgetItem, QDialogButtonBox, QPlainTextEdit, QWidget,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
                               QLineEdit)
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
                border: 1px solid rgba(128, 128, 128, 0.25);
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
        btn_use_original.setObjectName("secondary_button")
        btn_use_original.clicked.connect(self._use_original)
        btn_box.addWidget(btn_use_original)
        
        btn_save = mdi_button("保存修改", "save")
        btn_save.clicked.connect(self.accept)
        btn_box.addWidget(btn_save)
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondary_button")
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



class ClipSelectionDialog(QDialog):
    """步骤2重新选择镜头的对话框，表格样式与步骤1的镜头列表保持一致。"""

    def __init__(self, clips, selected_paths, parent=None, play_callback=None):
        super().__init__(parent)
        self.clips = clips
        self.selected_paths = set(selected_paths)
        self.play_callback = play_callback
        self.setWindowTitle("重新选择镜头")
        self.setMinimumSize(900, 500)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_lbl = QLabel("请勾选要用于镜头重组的镜头片段（双击视频片段可播放预览，双击描述可编辑）：")
        header_lbl.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        layout.addWidget(header_lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["选择", "序号", "视频片段", "时间戳", "画面文案描述", "评分"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(300)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 50)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 200)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 60)

        self._populate_table()
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_select_all = QPushButton("全选")
        btn_select_all.setObjectName("secondary_button")
        btn_select_all.clicked.connect(self._select_all)
        btn_deselect_all = QPushButton("取消全选")
        btn_deselect_all.setObjectName("secondary_button")
        btn_deselect_all.clicked.connect(self._deselect_all)
        btn_row.addWidget(btn_select_all)
        btn_row.addWidget(btn_deselect_all)
        btn_row.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondary_button")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.clips))
        for idx, clip in enumerate(self.clips):
            path = clip.get("path", "")
            filename = clip.get("filename", os.path.basename(path) if path else "")
            time_str = clip.get("time_str", "")
            desc = clip.get("desc", "")
            score = clip.get("score", -1.0)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(chk_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if path in self.selected_paths else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, path)
            self.table.setItem(idx, 0, chk_item)

            idx_item = QTableWidgetItem(str(idx + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(idx, 1, idx_item)

            file_item = QTableWidgetItem(filename)
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            file_item.setData(Qt.UserRole, path)
            file_item.setToolTip(path)
            self.table.setItem(idx, 2, file_item)

            time_item = QTableWidgetItem(time_str)
            time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable)
            time_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(idx, 3, time_item)

            desc_item = QTableWidgetItem(desc)
            desc_item.setToolTip(desc if desc else "双击可编辑描述")
            self.table.setItem(idx, 4, desc_item)

            score_text = f"{score:.1f}" if score >= 0 else "—"
            score_item = QTableWidgetItem(score_text)
            score_item.setFlags(score_item.flags() & ~Qt.ItemIsEditable)
            score_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(idx, 5, score_item)

        self.table.blockSignals(False)

    def _on_cell_changed(self, row, col):
        if col == 0:
            item = self.table.item(row, 0)
            if item:
                path = item.data(Qt.UserRole)
                if item.checkState() == Qt.Checked:
                    self.selected_paths.add(path)
                else:
                    self.selected_paths.discard(path)
        elif col == 4:
            file_item = self.table.item(row, 2)
            desc_item = self.table.item(row, 4)
            if file_item and desc_item and 0 <= row < len(self.clips):
                path = file_item.data(Qt.UserRole)
                if path:
                    self.clips[row]["desc"] = desc_item.text().strip()

    def _on_item_double_clicked(self, item):
        row = item.row()
        col = item.column()
        if col == 4:
            return
        file_item = self.table.item(row, 2)
        if file_item and self.play_callback:
            path = file_item.data(Qt.UserRole)
            if path:
                self.play_callback(path)

    def _select_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item:
                item.setCheckState(Qt.Checked)
                self.selected_paths.add(item.data(Qt.UserRole))
        self.table.blockSignals(False)

    def _deselect_all(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
                self.selected_paths.discard(item.data(Qt.UserRole))
        self.table.blockSignals(False)

    def get_selected_paths(self):
        return list(self.selected_paths)

    def get_clips(self):
        return self.clips



class ArrangeMaterialsDialog(QDialog):
    """整理已选镜头素材：列出当前素材，支持逐个删除、清空全部。

    与 FinalMixedVideosDialog 保持一致的 QListWidget + 行内控件样式。
    调用方通过 get_result_paths() 取得删除/调整后的最终素材路径列表。
    """
    def __init__(self, parent, paths):
        super().__init__(parent)
        self.setWindowTitle("🗂 整理已选镜头素材")
        self.setMinimumSize(560, 380)
        self.resize(640, 480)

        # Theme-consistent dialog（沿用 FinalMixedVideosDialog 风格）
        self.setStyleSheet("""
            QListWidget {
                border: 1px solid #2e2e32;
                border-radius: 8px;
                padding: 5px;
            }
            QPushButton#primary_button {
                font-weight: 700;
            }
            QPushButton#delete_btn {
                color: #e74c3c;
                font-weight: bold;
            }
            QPushButton#delete_btn:hover {
                color: #ff6b6b;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.header_lbl = QLabel()
        self.header_lbl.setStyleSheet("font-size: 14px; color: #2ecc71;")
        layout.addWidget(self.header_lbl)

        tip_lbl = QLabel("提示：点击右侧「删除」可移除单个素材；底部「清空全部」可一键移除。")
        tip_lbl.setStyleSheet("font-size: 12px; color: #9ca3af;")
        tip_lbl.setWordWrap(True)
        layout.addWidget(tip_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        layout.addWidget(self.list_widget)

        self._paths = list(paths) if paths else []
        self._rebuild_list()

        footer_layout = QHBoxLayout()
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet("font-size: 12px; color: #9ca3af;")
        footer_layout.addWidget(self.count_lbl)
        footer_layout.addStretch()

        btn_clear = QPushButton("清空全部")
        btn_clear.setObjectName("secondary_button")
        btn_clear.clicked.connect(self._clear_all)
        footer_layout.addWidget(btn_clear)

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondary_button")
        btn_cancel.clicked.connect(self.reject)
        footer_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("primary_button")
        btn_ok.clicked.connect(self.accept)
        footer_layout.addWidget(btn_ok)

        layout.addLayout(footer_layout)
        self._refresh_counts()

    def _rebuild_list(self):
        """根据 self._paths 重建列表行（带序号 + 文件名 + 删除按钮）。"""
        self.list_widget.clear()
        for idx, path in enumerate(self._paths, start=1):
            item = QListWidgetItem()
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 4, 8, 4)
            item_layout.setSpacing(10)

            idx_lbl = QLabel(f"{idx}.")
            idx_lbl.setStyleSheet("color: #6b7280; font-size: 12px;")
            idx_lbl.setFixedWidth(28)
            item_layout.addWidget(idx_lbl)

            name_lbl = QLabel(os.path.basename(path))
            name_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            name_lbl.setToolTip(path)
            item_layout.addWidget(name_lbl, 1)

            btn_del = QPushButton("删除")
            btn_del.setObjectName("delete_btn")
            # 默认参数绑定循环变量，避免闭包指向最后一项
            btn_del.clicked.connect(lambda checked=False, p=path: self._delete_one(p))
            item_layout.addWidget(btn_del)

            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

    def _delete_one(self, path):
        """删除指定路径的素材（如有重复仅删首个匹配）。"""
        try:
            self._paths.remove(path)
        except ValueError:
            pass
        self._rebuild_list()
        self._refresh_counts()

    def _clear_all(self):
        if not self._paths:
            return
        self._paths = []
        self._rebuild_list()
        self._refresh_counts()

    def _refresh_counts(self):
        n = len(self._paths)
        self.header_lbl.setText(f"✨ 当前已选 <b>{n}</b> 个素材，可在下方删除或调整")
        self.count_lbl.setText(f"剩余 {n} 个素材")

    def get_result_paths(self):
        """返回删除/调整后的最终素材路径列表（按当前顺序）。"""
        return list(self._paths)

