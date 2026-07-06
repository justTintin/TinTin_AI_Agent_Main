"""
炫白主题 QSS · 扁平化浅色风格
"""
LIGHT_STYLE_SHEET = """
* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", sans-serif;
}

QMainWindow {
    background-color: #f5f5f7;
}

QToolTip {
    background-color: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}

QLabel {
    color: #3a3a3f;
}

#sidebar {
    background-color: #ebebed;
    border-right: 1px solid #dcdce0;
    min-width: 260px;
    max-width: 260px;
}

#sidebar_title {
    font-size: 20px;
    font-weight: 700;
    color: #1d1d1f;
    padding: 22px 20px 16px 20px;
}

#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #86868b;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 16px 4px 16px;
    margin: 8px 12px 0px 12px;
}

#sidebar_footer {
    color: #aeaeb2;
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
    color: #6e6e73;
    border-radius: 8px;
    margin: 2px 10px;
}

QPushButton#nav_button:hover {
    background-color: #dedee3;
    color: #1d1d1f;
}

QPushButton#nav_button[active="true"] {
    background-color: rgba(99, 102, 241, 0.12);
    color: #4f46e5;
    font-weight: 600;
}

#card {
    background-color: #ffffff;
    border-radius: 10px;
    border: 1px solid #e5e5ea;
}

#feature_card {
    background-color: #ffffff;
    border-radius: 12px;
    border: 1px solid #e5e5ea;
}

#feature_card:hover {
    border: 1px solid rgba(99, 102, 241, 0.3);
    background-color: #fafafe;
}

#heading {
    font-size: 15px;
    font-weight: 700;
    color: #1d1d1f;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #1d1d1f;
}

#muted_text {
    color: #86868b;
    font-size: 12px;
}

#accent_text {
    color: #4f46e5;
    font-size: 12px;
    font-weight: 600;
}

#success_text {
    color: #059669;
    font-weight: 600;
}

QLineEdit, QTextEdit, QPlainTextEdit,
QSpinBox, QDoubleSpinBox,
QDateEdit, QTimeEdit, QDateTimeEdit {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1d1d1f;
    selection-background-color: rgba(99, 102, 241, 0.2);
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #6366f1;
}

QComboBox {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    color: #1d1d1f;
    min-width: 80px;
}

QComboBox:focus { border: 1px solid #6366f1; }
QComboBox:hover { border: 1px solid #b0b0b8; }

QComboBox::drop-down { border: none; width: 28px; }

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
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
    background-color: #f0f0f5;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

QPushButton {
    background-color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    color: #1d1d1f;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f5f5f7;
}

QPushButton:pressed { background-color: #e5e5ea; }
QPushButton:disabled {
    background-color: #f5f5f7;
    color: #aeaeb2;
}

QPushButton#primary_button {
    background-color: #6366f1;
    border: none;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background-color: #4f46e5;
}

QPushButton#secondary_button {
    background-color: #e8e8ed;
    border: none;
}

QPushButton#secondary_button:hover {
    background-color: #dcdce0;
}

QPushButton#action_button {
    background-color: #10b981;
    border: none;
    color: #ffffff;
}

QPushButton#action_button:hover {
    background-color: #059669;
}

QCheckBox { color: #3a3a3f; spacing: 8px; }

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #c7c7cc;
    border-radius: 4px;
    background-color: #ffffff;
}

QCheckBox::indicator:hover { border: 2px solid #6366f1; }
QCheckBox::indicator:checked {
    background-color: rgba(99, 102, 241, 0.12);
    border: 2px solid #6366f1;
    image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='%236366f1' d='M13.78 4.22a.75.75 0 0 1 0 1.06l-7.5 7.5a.75.75 0 0 1-1.06 0L2.22 9.78a.75.75 0 0 1 1.06-1.06L5.5 11.44l6.72-6.72a.75.75 0 0 1 1.06 0z'/%3E%3C/svg%3E");
}

QTableWidget, QTableView, QListWidget {
    background-color: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    gridline-color: #f0f0f5;
    selection-background-color: rgba(99, 102, 241, 0.15);
    selection-color: #1d1d1f;
    alternate-background-color: #fafafa;
    color: #1d1d1f;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #3a3a3f;
    padding: 5px 8px;
    min-height: 28px;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #c7c7cc;
    border-radius: 4px;
    background-color: #ffffff;
}

QTableView::indicator:checked {
    background-color: rgba(99, 102, 241, 0.12);
    border: 2px solid #6366f1;
    image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='%236366f1' d='M13.78 4.22a.75.75 0 0 1 0 1.06l-7.5 7.5a.75.75 0 0 1-1.06 0L2.22 9.78a.75.75 0 0 1 1.06-1.06L5.5 11.44l6.72-6.72a.75.75 0 0 1 1.06 0z'/%3E%3C/svg%3E");
}

QHeaderView::section {
    background-color: #f5f5f7;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #e5e5ea;
    font-weight: 700;
    font-size: 12px;
    color: #86868b;
    text-transform: uppercase;
}

QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #e5e5ea;
    height: 8px;
}

QProgressBar::chunk {
    background-color: #6366f1;
    border-radius: 6px;
}

QTextEdit#log_viewer {
    background-color: #fafafa;
    color: #3a3a3f;
    border: 1px solid #e5e5ea;
    border-radius: 8px;
    padding: 12px;
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   缩略图占位 / 素材缩略图
   ═══════════════════════════════════════════════════════════════ */

#thumbnail_placeholder {
    border: 1px solid #d2d2d7;
    border-radius: 4px;
    color: #86868b;
}

/* ═══════════════════════════════════════════════════════════════
   页面副标题 / 提示文字
   ═══════════════════════════════════════════════════════════════ */

#page_subtitle {
    color: #86868b;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: bold;
    color: #3a3a3f;
    margin-top: 4px;
}

/* ═══════════════════════════════════════════════════════════════
   模型状态卡片（hook_score / marketing_detect）
   ═══════════════════════════════════════════════════════════════ */

#model_status_card {
    background-color: #f0f0f5;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
}

#model_info_label {
    font-size: 13px;
    font-weight: bold;
    color: #1d1d1f;
}

#model_status_label {
    font-weight: bold;
    color: #86868b;
}

#model_status_label[state="green"] { color: #059669; }
#model_status_label[state="red"] { color: #dc2626; }
#model_status_label[state="yellow"] { color: #d97706; }

/* ═══════════════════════════════════════════════════════════════
   日志输出框（全页）
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_box {
    background-color: #f5f5f7;
    color: #3a3a3f;
    font-size: 12px;
    border-radius: 6px;
    border: 1px solid #e5e5ea;
}

/* ═══════════════════════════════════════════════════════════════
   登录状态标签 (light)
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: bold;
}

#login_status_label[state="green"] { color: #059669; }
#login_status_label[state="red"] { color: #dc2626; }
#login_status_label[state="yellow"] { color: #d97706; }

/* ═══════════════════════════════════════════════════════════════
   LLM 状态标签 (light)
   ═══════════════════════════════════════════════════════════════ */

#llm_status_label {
    font-weight: bold;
}

#llm_status_label[state="green"] { color: #059669; }
#llm_status_label[state="red"] { color: #dc2626; }
#llm_status_label[state="yellow"] { color: #d97706; }

/* ═══════════════════════════════════════════════════════════════
   Ollama 状态标签 (light)
   ═══════════════════════════════════════════════════════════════ */

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #059669; }
#ollama_status_lbl[state="red"] { color: #dc2626; }
#ollama_status_lbl[state="yellow"] { color: #d97706; }
#ollama_status_lbl[state="gray"] { color: #86868b; }

QScrollBar:vertical { width: 8px; background: transparent; margin: 4px 2px; }
QScrollBar::handle:vertical {
    background: #c7c7cc;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #aeaeb2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal {
    background: #c7c7cc;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #aeaeb2; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

QGroupBox {
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 16px;
    color: #3a3a3f;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #86868b;
    font-size: 12px;
}

QTabWidget::pane {
    border: 1px solid #e5e5ea;
    background-color: #ffffff;
    border-radius: 0 0 10px 10px;
}

QTabBar::tab {
    background-color: #f5f5f7;
    border: 1px solid #e5e5ea;
    border-bottom: none;
    color: #86868b;
    padding: 10px 20px;
    margin-right: 2px;
    border-radius: 8px 8px 0 0;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #4f46e5;
    font-weight: 700;
    border-bottom: 2px solid #6366f1;
}

QTabBar::tab:hover:!selected {
    color: #3a3a3f;
    background-color: #ebebed;
}

QDialog, QMessageBox { background-color: #ffffff; color: #1d1d1f; }
QDialog QLabel, QMessageBox QLabel { color: #1d1d1f; }

QDialog QPushButton, QMessageBox QPushButton {
    background-color: #e8e8ed;
    border: none;
    border-radius: 8px;
    padding: 6px 16px;
    color: #1d1d1f;
    min-width: 80px;
}

QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background-color: #e5e5ea;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #e5e5ea;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: #6366f1;
    border: 2px solid #ffffff;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background: #6366f1;
    border-radius: 3px;
}

QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #e5e5ea; }

/* ═══════════════════════════════════════════════════════════════
   状态栏
   ═══════════════════════════════════════════════════════════════ */

#status_overlay {
    background-color: rgba(240, 240, 245, 0.9);
    border: 1px solid rgba(0, 0, 0, 0.1);
    border-radius: 6px;
}
#status_overlay QLabel {
    background: transparent;
    border: none;
    color: #6b7280;
    font-family: 'Consolas', 'Segoe UI', monospace;
    font-size: 11px;
    font-weight: bold;
}
#status_separator {
    background-color: rgba(0, 0, 0, 0.1);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   素材管理
   ═══════════════════════════════════════════════════════════════ */

#step_label {
    color: #86868b; padding: 4px 0; font-size: 13px;
}
#step_label[active="true"] {
    color: #2563eb; font-weight: bold;
    background-color: rgba(37, 99, 235, 0.1); border-radius: 4px;
}
#nas_root_label { font-size: 13px; font-weight: bold; color: #1d1d1f; }
#stats_analyze, #stats_ingest { font-size: 13px; color: #1d1d1f; }
#btn_refresh_stats {
    background-color: #f0f0f5; border: none; border-radius: 4px;
    color: #3a3a3f; padding: 3px 8px; font-size: 11px; font-weight: bold;
}
#btn_refresh_stats:hover { background-color: #e8e8ed; }
#btn_align {
    background-color: #dbeafe; border: none; border-radius: 4px;
    color: #1e40af; padding: 3px 8px; font-size: 11px; font-weight: bold;
}
#btn_align:hover { background-color: #bfdbfe; }
#secondary_button[danger="true"] { color: #dc2626; font-weight: bold; }

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog { background-color: #ffffff; color: #1d1d1f; }

#cover_section_title { font-size: 13px; color: #6b7280; }

#cover_video_widget { background-color: #000000; border-radius: 6px; border: 1px solid #d2d2d7; }

#cover_time_label { color: #6b7280; }

#cover_preview_h,
#cover_preview_v { background-color: #f0f0f5; border-radius: 6px; border: 1px solid #d2d2d7; }

#clip_list_item_title { font-size: 13px; color: #1d1d1f; }

#clip_list_item_score { color: #eab308; font-weight: bold; }

#clip_list_item_meta { color: #6b7280; font-size: 11px; }

#clip_list_separator { background-color: #e5e5ea; max-height: 1px; }

#clip_list_item_time { color: #6b7280; font-size: 11px; }

#export_step_label { padding: 6px 12px; }
#export_step_label[status="active"] { color: #2563eb; font-weight: bold; background-color: rgba(37,99,235,0.1); border-radius: 4px; }
#export_step_label[status="done"] { color: #059669; background-color: rgba(5,150,105,0.08); border-radius: 4px; }
#export_step_label[status="pending"] { color: #86868b; }

#clip_page_title { font-size: 14px; color: #1d1d1f; }

#clip_status_label { color: #6b7280; }

#export_result_label { color: #10b981; font-weight: bold; }

#video_info_label { color: #3b82f6; }

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px; font-weight: bold;
    border: 1px solid #e5e5ea; border-radius: 8px; margin-top: 12px;
}
#model_groupbox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 8px;
}
#ollama_status_lbl { color: #86868b; font-size: 12px; }
#ollama_models_lbl { color: #6b7280; font-size: 11px; }
#ollama_runners_warn { color: #dc2626; font-size: 12px; }
#ollama_progress_lbl { color: #d97706; font-size: 11px; }

#model_groupbox[section="llm"]::title     { color: #2563eb; }
#model_groupbox[section="vox"]::title     { color: #7c3aed; }
#model_groupbox[section="whisper"]::title { color: #059669; }
#model_groupbox[section="ocr"]::title     { color: #d97706; }

#comfyui_local_status { color: #86868b; font-size: 12px; }
"""
