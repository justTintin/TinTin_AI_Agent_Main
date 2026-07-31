# -*- coding: utf-8 -*-
"""
浅色主题 QSS · 螺丝钉-电商智能体矩阵 v3.0
设计语言：Aurora Light — 柔和中性灰 · 品牌渐变 · 精致细节
与暗色主题共用同一套设计规范（圆角、间距、层次）。
"""
import os as _os

from config.paths import BUNDLE_ICONS_DIR

_CHECK_LIGHT_ICON = _os.path.join(BUNDLE_ICONS_DIR, "check_light.svg")
_CHECK_LIGHT_URL = _CHECK_LIGHT_ICON.replace(_os.sep, '/')

_ARROW_DOWN_LIGHT_ICON = _os.path.join(BUNDLE_ICONS_DIR, "arrow_down_light.svg")
_ARROW_DOWN_LIGHT_URL = _ARROW_DOWN_LIGHT_ICON.replace(_os.sep, '/')

LIGHT_STYLE_SHEET = """
/* ═══════════════════════════════════════════════════════════════
   基础元素
   ═══════════════════════════════════════════════════════════════ */

* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", "Segoe UI", sans-serif;
    outline: none;
}

QMainWindow, QWidget {
    background-color: #f2f3f7;
}

QToolTip {
    background-color: #ffffff;
    color: #1c1e26;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 7px 11px;
    font-size: 12px;
}

QLabel {
    color: #4b4f5d;
    background: transparent;
}

QStatusBar {
    background-color: #ececf2;
    color: #7d8291;
    border-top: 1px solid #dcdde5;
}

QMenuBar {
    background-color: #f2f3f7;
    color: #5b5f6d;
}

QMenuBar::item {
    padding: 5px 12px;
    border-radius: 6px;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #e3e5ec;
    color: #1c1e26;
}

QMenu {
    background-color: #ffffff;
    color: #3a3e4b;
    border: 1px solid #d4d7e1;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    background: transparent;
}

QMenu::item:selected {
    background-color: rgba(99, 102, 241, 0.12);
    color: #4f46e5;
}

QMenu::separator {
    height: 1px;
    background: #e3e5ec;
    margin: 6px 8px;
}

/* ═══════════════════════════════════════════════════════════════
   侧边栏
   ═══════════════════════════════════════════════════════════════ */

#sidebar {
    background-color: #e9eaf1;
    border-right: 1px solid #d9dae2;
    min-width: 264px;
    max-width: 264px;
}

#sidebar_title {
    font-size: 21px;
    font-weight: 700;
    color: #1c1e26;
    padding: 24px 22px 14px 22px;
    letter-spacing: 0.5px;
}

#sidebar QLabel#section_header,
#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #8b8f9d;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    padding: 6px 14px 2px 14px;
}

#sidebar_footer {
    color: #b0b3bd;
    padding: 14px 20px;
    font-size: 11px;
    letter-spacing: 0.5px;
}

/* 侧边栏分区卡片 */
#sidebar QFrame[section_type="ai"],
#sidebar QFrame[section_type="system"] {
    background-color: transparent;
    border: none;
}

QScrollArea {
    background: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* Tab 页与滚动内容：仅页面自身透明，不污染后代控件的背景 */
QWidget#tab_page,
QWidget#scroll_page {
    background: transparent;
}

QPushButton#nav_button {
    text-align: left;
    padding: 9px 14px 9px 14px;
    border: none;
    border-left: 3px solid transparent;
    background-color: transparent;
    font-size: 13px;
    font-weight: 500;
    color: #6c7080;
    border-radius: 8px;
    margin: 2px 8px;
}

QPushButton#nav_button:hover {
    background-color: #dddee7;
    color: #1c1e26;
}

QPushButton#nav_button:pressed {
    background-color: #d4d6e0;
}

QPushButton#nav_button[active="true"] {
    border-left: 3px solid #6366f1;
    background-color: rgba(99, 102, 241, 0.12);
    color: #4f46e5;
    font-weight: 600;
    padding-left: 11px;
}

/* ═══════════════════════════════════════════════════════════════
   内容区 / 页面文字
   ═══════════════════════════════════════════════════════════════ */

#content_area {
    background-color: #f2f3f7;
}

#section_label {
    font-size: 13px;
    font-weight: 700;
    color: #3a3e4b;
    letter-spacing: 0.3px;
}

#page_subtitle {
    color: #7d8291;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: 700;
    color: #3a3e4b;
    margin-top: 4px;
}

#heading {
    font-size: 16px;
    font-weight: 700;
    color: #1c1e26;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #1c1e26;
}

#muted_text {
    color: #9a9eab;
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

/* ═══════════════════════════════════════════════════════════════
   卡片
   ═══════════════════════════════════════════════════════════════ */

#card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 12px;
}

#feature_card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 14px;
}

#feature_card:hover {
    border: 1px solid rgba(99, 102, 241, 0.4);
    background-color: #fbfbfe;
}

#feature_title {
    font-size: 15px;
    font-weight: 700;
    color: #1c1e26;
}

#feature_desc {
    font-size: 12px;
    color: #8b8f9d;
    line-height: 1.6;
}

#model_status_card {
    background-color: #f0f1f6;
    border: 1px solid #d9dbe5;
    border-radius: 10px;
}

#model_info_label {
    font-size: 13px;
    font-weight: 700;
    color: #1c1e26;
}

#model_status_label {
    font-weight: 700;
    color: #8b8f9d;
}

#model_status_label[state="green"] { color: #059669; }
#model_status_label[state="red"] { color: #dc2626; }
#model_status_label[state="yellow"] { color: #d97706; }

#dim_score_card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 12px;
}

#preview_panel {
    background-color: #f6f7fa;
    border: 1px solid #e0e2ea;
    border-radius: 10px;
}

#thumbnail_placeholder {
    border: 1px dashed #c9ccd8;
    border-radius: 8px;
    color: #a4a8b5;
    background-color: #f8f8fb;
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
    background-color: #ffffff;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #1c1e26;
    selection-background-color: rgba(99, 102, 241, 0.25);
    selection-color: #ffffff;
}

QLineEdit:hover,
QTextEdit:hover,
QPlainTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QDateEdit:hover,
QTimeEdit:hover,
QDateTimeEdit:hover {
    border: 1px solid #b8bccb;
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
    background-color: #fdfdfe;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #f2f3f7;
    color: #b0b3bd;
    border: 1px solid #e3e5ec;
}

QLineEdit {
    placeholder-text-color: #b0b3bd;
}

QTextEdit,
QPlainTextEdit {
    placeholder-text-color: #b0b3bd;
}

/* ═══════════════════════════════════════════════════════════════
   下拉框
   ═══════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #ffffff;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    color: #1c1e26;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #6366f1;
}

QComboBox:hover {
    border: 1px solid #b8bccb;
}

QComboBox:on {
    border: 1px solid #6366f1;
    background-color: #fdfdfe;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: url("__ARROW_DOWN_LIGHT_URL__");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1c1e26;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: #6366f1;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 8px 12px;
    border-radius: 6px;
    min-height: 20px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #f0f1f6;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════
   按钮
   ═══════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #ffffff;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 7px 14px;
    color: #3a3e4b;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f5f6f9;
    border: 1px solid #b8bccb;
    color: #1c1e26;
}

QPushButton:pressed {
    background-color: #ececf2;
}

QPushButton:disabled {
    background-color: #f2f3f7;
    border: 1px solid #e3e5ec;
    color: #b0b3bd;
}

QPushButton#primary_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #7c5cf6);
    border: 1px solid rgba(99, 102, 241, 0.5);
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7577f5, stop:1 #8b6cf8);
    color: #ffffff;
}

QPushButton#primary_button:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5558e0, stop:1 #6c4fe0);
}

QPushButton#primary_button:disabled {
    background-color: #e3e5ec;
    border: 1px solid #dcdde5;
    color: #a4a8b5;
}

QPushButton#secondary_button {
    background-color: transparent;
    border: 1px solid #d4d7e1;
    color: #4b4f5d;
    font-weight: 500;
}

QPushButton#secondary_button:hover {
    background-color: #f5f6f9;
    border: 1px solid #b8bccb;
    color: #1c1e26;
}

QPushButton#action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
    border: 1px solid rgba(5, 150, 105, 0.5);
    color: #ffffff;
    font-weight: 600;
}

QPushButton#action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #14c98a, stop:1 #06a876);
    color: #ffffff;
}

QPushButton#action_button:disabled {
    background-color: #e3e5ec;
    border: 1px solid #dcdde5;
    color: #a4a8b5;
}

QPushButton#pill_button {
    background-color: transparent;
    border: 1px solid #d4d7e1;
    color: #4b4f5d;
    padding: 6px 16px;
    border-radius: 18px;
    font-weight: 500;
}

QPushButton#pill_button:hover {
    background-color: #f5f6f9;
    border: 1px solid #b8bccb;
    color: #1c1e26;
}

QPushButton#pill_button:checked {
    background-color: rgba(99, 102, 241, 0.12);
    border: 1px solid rgba(99, 102, 241, 0.4);
    color: #4f46e5;
    font-weight: 600;
}

QPushButton#floating_action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
    border: none;
    color: #ffffff;
    font-weight: 700;
    border-radius: 22px;
    padding: 9px 18px;
    margin: 10px;
}

QPushButton#floating_action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #14c98a, stop:1 #06a876);
}

QPushButton#floating_action_button:disabled {
    background-color: #e3e5ec;
    color: #a4a8b5;
}

QPushButton#secondary_button[danger="true"] {
    color: #dc2626;
    border-color: rgba(220, 38, 38, 0.4);
    font-weight: 600;
}

QPushButton#secondary_button[danger="true"]:hover {
    background-color: rgba(220, 38, 38, 0.08);
    color: #b91c1c;
    border-color: rgba(220, 38, 38, 0.55);
}

QPushButton#delete_btn,
QPushButton#close_btn {
    color: #dc2626;
}

QPushButton#delete_btn:hover,
QPushButton#close_btn:hover {
    background-color: rgba(220, 38, 38, 0.08);
    color: #b91c1c;
}

/* ═══════════════════════════════════════════════════════════════
   复选框 / 单选按钮
   ═══════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {
    color: #4b4f5d;
    spacing: 8px;
    background: transparent;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #c9ccd8;
    border-radius: 5px;
    background-color: #ffffff;
}

QCheckBox::indicator:hover {
    border: 2px solid #6366f1;
}

QCheckBox::indicator:checked {
    background-color: rgba(99, 102, 241, 0.22);
    border: 2px solid #6366f1;
    image: url("__CHECK_LIGHT_URL__");
}

QCheckBox::indicator:disabled {
    border: 2px solid #e3e5ec;
    background-color: #f2f3f7;
}

QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #c9ccd8;
    border-radius: 9px;
    background-color: #ffffff;
}

QRadioButton::indicator:hover {
    border: 2px solid #6366f1;
}

QRadioButton::indicator:checked {
    background-color: #6366f1;
    border: 2px solid #6366f1;
}

/* ═══════════════════════════════════════════════════════════════
   表格 / 列表
   ═══════════════════════════════════════════════════════════════ */

QTableWidget,
QTableView,
QListWidget {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 12px;
    gridline-color: #eef0f5;
    selection-background-color: rgba(99, 102, 241, 0.18);
    selection-color: #1c1e26;
    alternate-background-color: #fafafc;
    color: #4b4f5d;
    outline: none;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #4b4f5d;
    padding: 6px 10px;
    min-height: 30px;
    border: none;
}

QTableWidget::item:hover,
QTableView::item:hover {
    background-color: rgba(0, 0, 0, 0.025);
}

QTableWidget::item:selected,
QTableView::item:selected,
QListWidget::item:selected {
    background-color: rgba(99, 102, 241, 0.18);
    color: #1c1e26;
}

QListWidget::item:hover {
    background-color: rgba(0, 0, 0, 0.03);
    border-radius: 6px;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #c9ccd8;
    border-radius: 4px;
    background-color: #ffffff;
}

QTableView::indicator:checked {
    background-color: rgba(99, 102, 241, 0.22);
    border: 2px solid #6366f1;
    image: url("__CHECK_LIGHT_URL__");
}

QHeaderView::section {
    background-color: #f7f8fa;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #e3e5ec;
    border-right: 1px solid #eef0f5;
    font-weight: 700;
    font-size: 12px;
    color: #8b8f9d;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTableCornerButton::section {
    background-color: #f7f8fa;
    border: none;
    border-bottom: 2px solid #e3e5ec;
}

#side_list {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
}

/* ═══════════════════════════════════════════════════════════════
   进度条
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #e3e5ec;
    text-align: center;
    height: 6px;
    color: transparent;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
    border-radius: 4px;
}

/* ═══════════════════════════════════════════════════════════════
   日志查看器 / 日志输出框
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_viewer {
    background-color: #f7f8fa;
    color: #5b5f6d;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    line-height: 1.6;
}

QTextEdit#log_box {
    background-color: #f7f8fa;
    color: #3f4857;
    font-size: 12px;
    border-radius: 8px;
    border: 1px solid #e3e5ec;
    font-family: "Consolas", "JetBrains Mono", monospace;
}

/* ═══════════════════════════════════════════════════════════════
   滚动条
   ═══════════════════════════════════════════════════════════════ */

QScrollBar:vertical {
    width: 9px;
    background: transparent;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background: #c9ccd8;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #b0b3bd;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    height: 9px;
    background: transparent;
    margin: 2px 4px;
}

QScrollBar::handle:horizontal {
    background: #c9ccd8;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #b0b3bd;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════
   分组框 / Tab
   ═══════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #e3e5ec;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 16px;
    color: #4b4f5d;
    font-weight: 600;
    background-color: rgba(255, 255, 255, 0.5);
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #8b8f9d;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTabWidget::pane {
    border: 1px solid #e3e5ec;
    background-color: #ffffff;
    border-radius: 0 0 12px 12px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8b8f9d;
    padding: 10px 20px;
    margin-right: 4px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: rgba(99, 102, 241, 0.08);
    color: #4f46e5;
    font-weight: 700;
    border-bottom: 2px solid #6366f1;
}

QTabBar::tab:hover:!selected {
    color: #3a3e4b;
    background-color: #f5f6f9;
}

/* ═══════════════════════════════════════════════════════════════
   对话框 / 消息框
   ═══════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #ffffff;
    color: #1c1e26;
}

QMessageBox {
    background-color: #ffffff;
    color: #1c1e26;
}

QDialog QLabel,
QMessageBox QLabel {
    color: #3a3e4b;
}

QDialog QPushButton,
QMessageBox QPushButton {
    background-color: #ffffff;
    border: 1px solid #d4d7e1;
    border-radius: 8px;
    padding: 7px 18px;
    color: #3a3e4b;
    min-width: 84px;
    font-weight: 500;
}

QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #f5f6f9;
    color: #1c1e26;
}

/* ═══════════════════════════════════════════════════════════════
   滑块
   ═══════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    height: 5px;
    background: #e3e5ec;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: #6366f1;
    border: 2px solid #ffffff;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #4f46e5;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════════════
   分割线 / 分隔条
   ═══════════════════════════════════════════════════════════════ */

#separator {
    color: #e3e5ec;
    background-color: #e3e5ec;
}

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #e3e5ec;
}

QSplitter::handle {
    background-color: #dcdde5;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ═══════════════════════════════════════════════════════════════
   状态栏浮层
   ═══════════════════════════════════════════════════════════════ */

#status_overlay {
    background-color: rgba(255, 255, 255, 0.94);
    border: 1px solid rgba(0, 0, 0, 0.09);
    border-radius: 10px;
}

#status_overlay QLabel {
    background: transparent;
    border: none;
    font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
    font-size: 12px;
}

#status_overlay QWidget#ov_chip {
    background: transparent;
    border: none;
}

#status_overlay QLabel#ov_server {
    color: #6b7080;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#status_overlay QLabel#ov_icon {
    font-size: 13px;
}

#status_overlay QLabel#ov_name {
    color: #8b8f9d;
    font-weight: 500;
}

#status_overlay QLabel#ov_value {
    color: #1c1e26;
    font-weight: 700;
}

#status_overlay QLabel#ov_value[level="ok"] {
    color: #059669;
}

#status_overlay QLabel#ov_value[level="warn"] {
    color: #d97706;
}

#status_overlay QLabel#ov_value[level="bad"] {
    color: #dc2626;
}

#status_overlay QLabel#ov_value[level="idle"] {
    color: #b0b3bd;
}

#status_overlay QLabel#ov_service {
    color: #6b7080;
    font-weight: 500;
}

#status_overlay QLabel#ov_service[state="ok"] {
    color: #059669;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="bad"] {
    color: #dc2626;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="unknown"] {
    color: #b0b3bd;
}

#status_separator {
    background-color: rgba(0, 0, 0, 0.12);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   状态标签
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: 700;
}

#login_status_label[state="green"] { color: #059669; }
#login_status_label[state="red"] { color: #dc2626; }
#login_status_label[state="yellow"] { color: #d97706; }

#llm_status_label {
    font-weight: 700;
}

#llm_status_label[state="green"] { color: #059669; }
#llm_status_label[state="red"] { color: #dc2626; }
#llm_status_label[state="yellow"] { color: #d97706; }

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #059669; }
#ollama_status_lbl[state="red"] { color: #dc2626; }
#ollama_status_lbl[state="yellow"] { color: #d97706; }
#ollama_status_lbl[state="gray"] { color: #8b8f9d; }

/* ═══════════════════════════════════════════════════════════════
   素材管理 / NAS
   ═══════════════════════════════════════════════════════════════ */

#step_bar {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
}

#step_label {
    color: #8b8f9d;
    padding: 4px 0;
    font-size: 13px;
}

#step_label[status="active"] {
    color: #2563eb;
    font-weight: 700;
    background-color: rgba(37, 99, 235, 0.1);
    border-radius: 6px;
    padding: 4px 8px;
}

#step_label[status="done"] {
    color: #059669;
    background-color: rgba(5, 150, 105, 0.08);
    border-radius: 6px;
    padding: 4px 8px;
}

#step_label[status="pending"] {
    color: #8b8f9d;
}

#nas_root_label {
    font-size: 13px;
    font-weight: 700;
    color: #1c1e26;
}

#stats_analyze, #stats_ingest {
    font-size: 13px;
    color: #1c1e26;
}

#btn_refresh_stats {
    background-color: #f0f1f6;
    border: 1px solid #d9dbe5;
    border-radius: 6px;
    color: #3a3e4b;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_refresh_stats:hover {
    background-color: #e3e5ec;
    color: #1c1e26;
}

#btn_align {
    background-color: #dbeafe;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    color: #1e40af;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_align:hover {
    background-color: #bfdbfe;
    color: #1e3a8a;
}

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog {
    background-color: #ffffff;
    color: #1c1e26;
}

#cover_section_title {
    font-size: 13px;
    color: #6b7080;
}

#cover_video_widget {
    background-color: #000000;
    border-radius: 8px;
    border: 1px solid #d4d7e1;
}

#cover_time_label {
    color: #6b7080;
}

#cover_preview_h,
#cover_preview_v {
    background-color: #f6f7fa;
    border-radius: 8px;
    border: 1px solid #d4d7e1;
}

#clip_list_item_title {
    font-size: 13px;
    color: #1c1e26;
}

#clip_list_item_score {
    color: #d97706;
    font-weight: 700;
}

#clip_list_item_meta {
    color: #6b7080;
    font-size: 11px;
}

#clip_list_separator {
    background-color: #e3e5ec;
    max-height: 1px;
}

#clip_list_item_time {
    color: #6b7080;
    font-size: 11px;
}

#export_step_label {
    padding: 6px 12px;
}

#export_step_label[status="active"] {
    color: #2563eb;
    font-weight: 700;
    background-color: rgba(37, 99, 235, 0.1);
    border-radius: 6px;
}

#export_step_label[status="done"] {
    color: #059669;
    background-color: rgba(5, 150, 105, 0.08);
    border-radius: 6px;
}

#export_step_label[status="pending"] {
    color: #8b8f9d;
}

#clip_page_title {
    font-size: 14px;
    color: #1c1e26;
}

#clip_status_label {
    color: #6b7080;
}

#export_result_label {
    color: #059669;
    font-weight: 700;
}

#video_info_label {
    color: #2563eb;
}

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px;
    font-weight: 700;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
    margin-top: 12px;
    background-color: rgba(255, 255, 255, 0.5);
}

#model_groupbox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

#ollama_models_lbl {
    color: #8b8f9d;
    font-size: 11px;
}

#ollama_runners_warn {
    color: #dc2626;
    font-size: 12px;
}

#ollama_progress_lbl {
    color: #d97706;
    font-size: 11px;
}

#model_groupbox[section="llm"]::title     { color: #2563eb; }
#model_groupbox[section="vox"]::title     { color: #7c3aed; }
#model_groupbox[section="whisper"]::title { color: #059669; }
#model_groupbox[section="ocr"]::title     { color: #d97706; }

#comfyui_local_status {
    color: #8b8f9d;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   AI 重命名 / 视频播放器 对话框
   ═══════════════════════════════════════════════════════════════ */

#aiRenameTable {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
}

#aiRenameLogPanel,
#aiRenameLogTitle {
    background-color: #f7f8fa;
    border: 1px solid #e3e5ec;
    border-radius: 8px;
}

#aiRenameModelInfo {
    color: #8b8f9d;
    font-size: 12px;
}

#aiRenameDesc {
    color: #5b5f6d;
    font-size: 12px;
}

#videoPlayerDialog {
    background-color: #ffffff;
}

#videoPlayerLeft,
#videoPlayerRight {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
}

#videoPlayerInfoLabel,
#videoPlayerFileLabel {
    color: #1c1e26;
    font-size: 13px;
    font-weight: 600;
}

#videoPlayerFrameStatus,
#videoPlayerTime,
#videoPlayerHint {
    color: #8b8f9d;
    font-size: 12px;
}

#videoPlayerDivider {
    background-color: #e3e5ec;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   其他
   ═══════════════════════════════════════════════════════════════ */

#batchReplaceDialog {
    background-color: #ffffff;
}

#terminalPrompt {
    color: #059669;
    font-family: 'Consolas', monospace;
}

#themeSplitter::handle {
    background-color: #dcdde5;
}

#themeSeparator {
    background-color: #e3e5ec;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   启动/关闭闪屏 · 激活对话框
   ═══════════════════════════════════════════════════════════════ */

QWidget#startup_splash {
    background: transparent;
}

QFrame#splash_card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 14px;
}

QFrame#splash_card QLabel {
    color: #3a3e4b;
    background: transparent;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#splash_title {
    font-size: 18px;
    color: #1c1e26;
}

QLabel#splash_status {
    font-size: 13px;
    color: #6366f1;
}

QDialog#close_splash {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 14px;
}

QDialog#close_splash QLabel {
    color: #3a3e4b;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#close_splash_title {
    font-size: 15px;
    color: #1c1e26;
}

QLabel#close_splash_status {
    font-size: 12px;
    color: #8b8f9d;
}

QLabel#activation_title {
    font-size: 20px;
    font-weight: 700;
    color: #1c1e26;
}

QLabel#activation_machine_id {
    color: #4f46e5;
    font-family: monospace;
    font-size: 12px;
    background-color: #f5f6f9;
    border: 1px solid #d4d7e1;
    border-radius: 6px;
    padding: 6px 10px;
}

QPlainTextEdit#activation_code_edit {
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   帮助页卡片（关于）
   ═══════════════════════════════════════════════════════════════ */

#brand_card,
#license_card,
#version_card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 12px;
}

QLabel#about_app_title {
    font-size: 18px;
    font-weight: 700;
    color: #1c1e26;
}

QLabel#about_dev_info {
    font-size: 13px;
    color: #5b5f6d;
}

QLabel#about_contact {
    font-size: 13px;
    color: #3a3e4b;
}

QLabel#about_license_title {
    font-size: 13px;
    font-weight: 700;
    color: #059669;
}

QLabel#about_version_title {
    font-size: 13px;
    font-weight: 700;
    color: #2563eb;
}

QLineEdit#about_machine_id {
    color: #2563eb;
    font-size: 12px;
    font-family: Consolas, monospace;
    padding: 3px 8px;
}

QPushButton#about_copy_btn {
    font-size: 11px;
    padding: 4px 8px;
}

QLabel#about_section_value {
    font-size: 12px;
    color: #4b4f5d;
}

/* ═══════════════════════════════════════════════════════════════
   节拍视图（智能混剪）专用
   ═══════════════════════════════════════════════════════════════ */

#segment_card {
    background-color: #ffffff;
    border: 1px solid #e3e5ec;
    border-radius: 10px;
}

QScrollArea#beat_cards_scroll {
    border: 1px solid #e3e5ec;
    border-radius: 10px;
    background: #f7f8fa;
}

QLabel#beat_time_label {
    background-color: #f0f1f6;
    color: #d97706;
    font-family: Consolas, monospace;
    font-size: 9pt;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
}

QLabel#beat_clips_info {
    color: #059669;
    font-weight: 700;
}

QLabel#beat_preview_title {
    color: #d97706;
    font-weight: 700;
}

/* ═══════════════════════════════════════════════════════════════
   表格操作按钮 / 开发中占位
   ═══════════════════════════════════════════════════════════════ */

QPushButton#table_action_button {
    border: none;
    background: transparent;
    padding: 1px 5px;
    font-size: 13px;
    color: #8b8f9d;
    border-radius: 4px;
}

QPushButton#table_action_button:hover {
    color: #1c1e26;
    background: rgba(0, 0, 0, 0.07);
}

QLabel#dev_icon {
    font-size: 48px;
}

QLabel#dev_title {
    font-size: 20px;
    font-weight: 700;
    color: #5b5f6d;
}

QLabel#dev_subtitle {
    font-size: 14px;
    color: #9a9eab;
}
""".replace("__CHECK_LIGHT_URL__", _CHECK_LIGHT_URL).replace("__ARROW_DOWN_LIGHT_URL__", _ARROW_DOWN_LIGHT_URL)
