# -*- coding: utf-8 -*-
"""
扁平化暗色主题 · TinTin AI Agent v2.1
设计语言：Flat Design Modern — 微阴影 · 大圆角 · 低对比边框 · 流畅过渡
"""

STYLE_SHEET = """
* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", sans-serif;
}

/* ═══════════════════════════════════════════════════════════════
   基础元素
   ═══════════════════════════════════════════════════════════════ */

QMainWindow {
    background-color: #0f0f11;
}

QToolTip {
    background-color: #1e1e22;
    color: #e4e4e7;
    border: 1px solid #2a2a30;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

QLabel {
    color: #c8c8d0;
}

/* ═══════════════════════════════════════════════════════════════
   侧边栏
   ═══════════════════════════════════════════════════════════════ */

#sidebar {
    background-color: #0a0a0d;
    border-right: 1px solid #1a1a22;
    min-width: 260px;
    max-width: 260px;
}

#sidebar_title {
    font-size: 20px;
    font-weight: 700;
    color: #f0f0f5;
    padding: 22px 20px 16px 20px;
    letter-spacing: 0.5px;
}

#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #7c7c8a;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 16px 4px 16px;
    margin: 8px 12px 0px 12px;
}

#sidebar_footer {
    color: #4a4a55;
    padding: 18px 20px;
    font-size: 11px;
}

QPushButton#nav_button {
    text-align: left;
    padding: 9px 14px;
    border: none;
    background-color: transparent;
    font-size: 13px;
    font-weight: 500;
    color: #9a9aa8;
    border-radius: 8px;
    margin: 2px 10px;
}

QPushButton#nav_button:hover {
    background-color: #16161d;
    color: #e4e4e7;
}

QPushButton#nav_button[active="true"] {
    background-color: rgba(99, 102, 241, 0.12);
    color: #818cf8;
    font-weight: 600;
}

/* ═══════════════════════════════════════════════════════════════
   卡片
   ═══════════════════════════════════════════════════════════════ */

#card {
    background-color: #141418;
    border-radius: 10px;
    border: 1px solid #1e1e26;
}

#feature_card {
    background-color: #141418;
    border-radius: 12px;
    border: 1px solid #1e1e26;
}

#feature_card:hover {
    border: 1px solid rgba(99, 102, 241, 0.25);
    background-color: #18181e;
}

/* ═══════════════════════════════════════════════════════════════
   文字样式
   ═══════════════════════════════════════════════════════════════ */

#heading {
    font-size: 15px;
    font-weight: 700;
    color: #f0f0f5;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #f0f0f5;
}

#muted_text {
    color: #6b6b7a;
    font-size: 12px;
}

#accent_text {
    color: #818cf8;
    font-size: 12px;
    font-weight: 600;
}

#success_text {
    color: #34d399;
    font-weight: 600;
}

#feature_title {
    font-size: 15px;
    font-weight: 700;
    color: #f0f0f5;
}

#feature_desc {
    font-size: 12px;
    color: #6b6b7a;
    line-height: 1.5;
}

/* ═══════════════════════════════════════════════════════════════
   输入控件
   ═══════════════════════════════════════════════════════════════ */

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QDateEdit,
QTimeEdit,
QDateTimeEdit {
    background-color: #1a1a22;
    border: 1px solid #252530;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #e4e4e7;
    selection-background-color: rgba(99, 102, 241, 0.3);
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QDateEdit:focus,
QTimeEdit:focus,
QDateTimeEdit:focus {
    border: 1px solid #6366f1;
    background-color: #1c1c26;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #111116;
    color: #4a4a55;
    border: 1px solid #1a1a22;
}

/* ═══════════════════════════════════════════════════════════════
   下拉框
   ═══════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #1a1a22;
    border: 1px solid #252530;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #e4e4e7;
}

QComboBox:focus {
    border: 1px solid #6366f1;
}

QComboBox:hover {
    border: 1px solid #353545;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1a1a22;
    color: #e4e4e7;
    border: 1px solid #252530;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #6366f1;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 8px 12px;
    border-radius: 4px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #252530;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════
   按钮
   ═══════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #1e1e26;
    border: 1px solid #2a2a35;
    border-radius: 8px;
    padding: 8px 16px;
    color: #c8c8d0;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #252530;
    border: 1px solid #353545;
}

QPushButton:pressed {
    background-color: #2a2a38;
}

QPushButton:disabled {
    background-color: #111116;
    color: #4a4a55;
    border: 1px solid #1a1a22;
}

QPushButton#primary_button {
    background-color: #6366f1;
    border: 1px solid #6366f1;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background-color: #4f46e5;
    border: 1px solid #4f46e5;
}

QPushButton#primary_button:pressed {
    background-color: #4338ca;
}

QPushButton#primary_button:disabled {
    background-color: #312e81;
    border: 1px solid #312e81;
    color: #6366aa;
}

QPushButton#secondary_button {
    background-color: #1a1a22;
    border: 1px solid #252530;
    color: #c8c8d0;
    font-weight: 500;
}

QPushButton#secondary_button:hover {
    background-color: #1e1e28;
    border: 1px solid #353545;
}

QPushButton#action_button {
    background-color: #10b981;
    border: 1px solid #10b981;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#action_button:hover {
    background-color: #059669;
}

QPushButton#pill_button {
    background-color: #1a1a22;
    border: 1px solid #252530;
    color: #c8c8d0;
    padding: 6px 14px;
    border-radius: 16px;
    font-weight: 500;
}

QPushButton#pill_button:hover {
    background-color: #1e1e28;
    border: 1px solid #353545;
}

QPushButton#pill_button:checked {
    background-color: rgba(99, 102, 241, 0.15);
    border: 1px solid rgba(99, 102, 241, 0.3);
    color: #818cf8;
    font-weight: 600;
}

QPushButton#floating_action_button {
    background-color: #10b981;
    border: 2px solid #141418;
    color: #ffffff;
    font-weight: 700;
    border-radius: 20px;
    padding: 8px 16px;
    margin: 10px;
}

QPushButton#floating_action_button:hover {
    background-color: #059669;
}

QPushButton#floating_action_button:disabled {
    background-color: #2a2a35;
    border: 2px solid #1e1e26;
    color: #6b6b7a;
}

/* ═══════════════════════════════════════════════════════════════
   复选框
   ═══════════════════════════════════════════════════════════════ */

QCheckBox {
    color: #c8c8d0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #353545;
    border-radius: 4px;
    background-color: #1a1a22;
}

QCheckBox::indicator:hover {
    border: 2px solid #6366f1;
}

QCheckBox::indicator:checked {
    background-color: #6366f1;
    border: 2px solid #6366f1;
    image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='white' d='M13.78 4.22a.75.75 0 0 1 0 1.06l-7.5 7.5a.75.75 0 0 1-1.06 0L2.22 9.78a.75.75 0 0 1 1.06-1.06L5.5 11.44l6.72-6.72a.75.75 0 0 1 1.06 0z'/%3E%3C/svg%3E");
}

/* ═══════════════════════════════════════════════════════════════
   表格
   ═══════════════════════════════════════════════════════════════ */

QTableWidget,
QTableView,
QListWidget {
    background-color: #141418;
    border: 1px solid #1e1e26;
    border-radius: 10px;
    gridline-color: #1a1a24;
    selection-background-color: rgba(99, 102, 241, 0.2);
    selection-color: #e4e4e7;
    alternate-background-color: #111118;
    color: #c8c8d0;
    outline: none;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #c8c8d0;
    padding: 6px 10px;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #353545;
    border-radius: 4px;
    background-color: #1a1a22;
}

QTableView::indicator:checked {
    background-color: #6366f1;
    border: 2px solid #6366f1;
    image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='white' d='M13.78 4.22a.75.75 0 0 1 0 1.06l-7.5 7.5a.75.75 0 0 1-1.06 0L2.22 9.78a.75.75 0 0 1 1.06-1.06L5.5 11.44l6.72-6.72a.75.75 0 0 1 1.06 0z'/%3E%3C/svg%3E");
}

QHeaderView::section {
    background-color: #0f0f14;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #1e1e26;
    font-weight: 700;
    font-size: 12px;
    color: #7c7c8a;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QTableCornerButton::section {
    background-color: #0f0f14;
    border: none;
    border-bottom: 2px solid #1e1e26;
}

/* ═══════════════════════════════════════════════════════════════
   进度条
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #1a1a22;
    text-align: center;
    height: 8px;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 6px;
}

/* ═══════════════════════════════════════════════════════════════
   日志查看器
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_viewer {
    background-color: #0a0a10;
    color: #a0a0b0;
    border: 1px solid #14141c;
    border-radius: 8px;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    line-height: 1.6;
}

/* ═══════════════════════════════════════════════════════════════
   缩略图占位 / 素材缩略图
   ═══════════════════════════════════════════════════════════════ */

#thumbnail_placeholder {
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    color: #6b6b7a;
}

/* ═══════════════════════════════════════════════════════════════
   页面副标题 / 提示文字
   ═══════════════════════════════════════════════════════════════ */

#page_subtitle {
    color: #aaaaaa;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: bold;
    color: #e5e7eb;
    margin-top: 4px;
}

/* ═══════════════════════════════════════════════════════════════
   模型状态卡片（hook_score / marketing_detect）
   ═══════════════════════════════════════════════════════════════ */

#model_status_card {
    background-color: #1a1a26;
    border: 1px solid #3a3a4a;
    border-radius: 8px;
}

#model_info_label {
    font-size: 13px;
    font-weight: bold;
    color: #e0e0e0;
}

#model_status_label {
    font-weight: bold;
    color: #a0aec0;
}

#model_status_label[state="green"] { color: #2ecc71; }
#model_status_label[state="red"] { color: #e74c3c; }
#model_status_label[state="yellow"] { color: #f1c40f; }

/* ═══════════════════════════════════════════════════════════════
   日志输出框（全页）
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_box {
    background-color: #1a1a2e;
    color: #c8d6e5;
    font-size: 12px;
    border-radius: 6px;
    border: 1px solid #252530;
}

/* ═══════════════════════════════════════════════════════════════
   登录状态标签
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: bold;
}

#login_status_label[state="green"] { color: #2ecc71; }
#login_status_label[state="red"] { color: #e74c3c; }
#login_status_label[state="yellow"] { color: #f39c12; }

/* ═══════════════════════════════════════════════════════════════
   LLM 状态标签
   ═══════════════════════════════════════════════════════════════ */

#llm_status_label {
    font-weight: bold;
}

#llm_status_label[state="green"] { color: #2ecc71; }
#llm_status_label[state="red"] { color: #e74c3c; }
#llm_status_label[state="yellow"] { color: #f39c12; }

/* ═══════════════════════════════════════════════════════════════
   Ollama 状态标签
   ═══════════════════════════════════════════════════════════════ */

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #34d399; }
#ollama_status_lbl[state="red"] { color: #f87171; }
#ollama_status_lbl[state="yellow"] { color: #fbbf24; }
#ollama_status_lbl[state="gray"] { color: #9ca3af; }

/* ═══════════════════════════════════════════════════════════════
   滚动条
   ═══════════════════════════════════════════════════════════════ */

QScrollBar:vertical {
    width: 8px;
    background: transparent;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background: #2a2a35;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #3a3a48;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    height: 8px;
    background: transparent;
    margin: 2px 4px;
}

QScrollBar::handle:horizontal {
    background: #2a2a35;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #3a3a48;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════
   分组框
   ═══════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #1e1e26;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 16px;
    color: #c8c8d0;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #9a9aa8;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ═══════════════════════════════════════════════════════════════
   Tab 标签页
   ═══════════════════════════════════════════════════════════════ */

QTabWidget::pane {
    border: 1px solid #1e1e26;
    background-color: #141418;
    border-radius: 0 0 10px 10px;
}

QTabBar::tab {
    background-color: #1a1a22;
    border: 1px solid #252530;
    border-bottom: none;
    color: #7c7c8a;
    padding: 10px 20px;
    margin-right: 2px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #141418;
    color: #818cf8;
    font-weight: 700;
    border-bottom: 2px solid #6366f1;
}

QTabBar::tab:hover:!selected {
    color: #a0a0b0;
    background-color: #1e1e28;
}

/* ═══════════════════════════════════════════════════════════════
   对话框
   ═══════════════════════════════════════════════════════════════ */

QDialog,
QMessageBox {
    background-color: #141418;
    color: #c8c8d0;
}

QDialog QLabel,
QMessageBox QLabel {
    color: #c8c8d0;
}

QDialog QPushButton,
QMessageBox QPushButton {
    background-color: #1e1e26;
    border: 1px solid #2a2a35;
    border-radius: 8px;
    padding: 8px 20px;
    color: #c8c8d0;
    min-width: 80px;
    font-weight: 500;
}

QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #252530;
}

/* ═══════════════════════════════════════════════════════════════
   滑块
   ═══════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    height: 6px;
    background: #1a1a22;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: #6366f1;
    border: 2px solid #141418;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background: #818cf8;
}

QSlider::sub-page:horizontal {
    background: #6366f1;
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════════════
  分割线
   ═══════════════════════════════════════════════════════════════ */

#separator {
    color: #1e1e26;
    background-color: #1e1e26;
}

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #1e1e26;
}

/* ═══════════════════════════════════════════════════════════════
   对话框
   ═══════════════════════════════════════════════════════════════ */

QDialog, QMessageBox { background-color: #1a1a1c; color: #e4e4e7; }
QDialog QLabel, QMessageBox QLabel { color: #e4e4e7; }

QDialog QPushButton, QMessageBox QPushButton {
    background-color: #2c2c2e;
    border: 1px solid #3a3a40;
    border-radius: 8px;
    padding: 8px 20px;
    color: #e4e4e7;
    min-width: 80px;
}

QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background-color: #3a3a40;
}

/* ═══════════════════════════════════════════════════════════════
   状态栏
   ═══════════════════════════════════════════════════════════════ */

#status_overlay {
    background-color: rgba(15, 23, 42, 0.75);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
}
#status_overlay QLabel {
    background: transparent;
    border: none;
    color: #94a3b8;
    font-family: 'Consolas', 'Segoe UI', monospace;
    font-size: 11px;
    font-weight: bold;
}
#status_separator {
    background-color: rgba(255, 255, 255, 0.15);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   素材管理
   ═══════════════════════════════════════════════════════════════ */

#step_label {
    color: #7f8c8d; padding: 4px 0; font-size: 13px;
}
#step_label[active="true"] {
    color: #3498db; font-weight: bold;
    background-color: rgba(52, 152, 219, 0.1); border-radius: 4px;
}
#nas_root_label { font-size: 13px; font-weight: bold; color: #ffffff; }
#stats_analyze, #stats_ingest { font-size: 13px; color: #ffffff; }
#btn_refresh_stats {
    background-color: #27272a; border: 1px solid #3f3f46; border-radius: 4px;
    color: #e4e4e7; padding: 3px 8px; font-size: 11px; font-weight: bold;
}
#btn_refresh_stats:hover { background-color: #3f3f46; border-color: #52525b; color: #ffffff; }
#btn_align {
    background-color: #1e3a5f; border: 1px solid #3b82f6; border-radius: 4px;
    color: #93c5fd; padding: 3px 8px; font-size: 11px; font-weight: bold;
}
#btn_align:hover { background-color: #1e40af; border-color: #60a5fa; color: #ffffff; }
#secondary_button[danger="true"] { color: #ef4444; font-weight: bold; }

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog { background-color: #121214; color: #f8fafc; }

#cover_section_title { font-size: 13px; color: #94a3b8; }

#cover_video_widget { background-color: #000000; border-radius: 6px; border: 1px solid #27272a; }

#cover_time_label { color: #94a3b8; }

#cover_preview_h,
#cover_preview_v { background-color: #0c0a09; border-radius: 6px; border: 1px solid #27272a; }

#clip_list_item_title { font-size: 13px; color: #f8fafc; }

#clip_list_item_score { color: #eab308; font-weight: bold; }

#clip_list_item_meta { color: #94a3b8; font-size: 11px; }

#clip_list_separator { background-color: #2e2e32; max-height: 1px; }

#clip_list_item_time { color: #94a3b8; font-size: 11px; }

#export_step_label { padding: 6px 12px; }
#export_step_label[status="active"] { color: #3498db; font-weight: bold; background-color: rgba(52,152,219,0.1); border-radius: 4px; }
#export_step_label[status="done"] { color: #2ecc71; background-color: rgba(46,204,113,0.08); border-radius: 4px; }
#export_step_label[status="pending"] { color: #7f8c8d; }

#clip_page_title { font-size: 14px; color: #f8fafc; }

#clip_status_label { color: #94a3b8; }

#export_result_label { color: #10b981; font-weight: bold; }

#video_info_label { color: #3b82f6; }

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px; font-weight: bold;
    border: 1px solid #2e2e32; border-radius: 8px; margin-top: 12px;
}
#model_groupbox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 8px;
}
#ollama_status_lbl { color: #9ca3af; font-size: 12px; }
#ollama_models_lbl { color: #6b7280; font-size: 11px; }
#ollama_runners_warn { color: #f87171; font-size: 12px; }
#ollama_progress_lbl { color: #fbbf24; font-size: 11px; }
"""
