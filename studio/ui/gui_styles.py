# -*- coding: utf-8 -*-
"""
暗色主题 QSS · 螺丝钉-电商智能体矩阵 v3.0
设计语言：Aurora Dark — 深空层次 · 品牌渐变 · 精致细节
主色：#6366f1 (Indigo) → #8b5cf6 (Violet)
背景：#0b0c10（近黑微蓝），卡片分层 #151722 / #1a1d2a
"""
import os

from config.paths import BUNDLE_ICONS_DIR

_CHECK_ICON = os.path.join(BUNDLE_ICONS_DIR, "check.svg")
_CHECK_ICON_URL = _CHECK_ICON.replace(os.sep, '/')

_ARROW_DOWN_ICON = os.path.join(BUNDLE_ICONS_DIR, "arrow_down.svg")
_ARROW_DOWN_ICON_URL = _ARROW_DOWN_ICON.replace(os.sep, '/')

STYLE_SHEET = """
/* ═══════════════════════════════════════════════════════════════
   基础元素
   ═══════════════════════════════════════════════════════════════ */

* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", "Segoe UI", sans-serif;
    outline: none;
}

QMainWindow, QWidget {
    background-color: #0b0c10;
}

QToolTip {
    background-color: #1c1f2b;
    color: #e8eaf2;
    border: 1px solid #30364a;
    border-radius: 8px;
    padding: 7px 11px;
    font-size: 12px;
}

QLabel {
    color: #c3c6d2;
    background: transparent;
}

QStatusBar {
    background-color: #0d0e14;
    color: #8b90a3;
    border-top: 1px solid #1d2029;
}

QMenuBar {
    background-color: #0f1016;
    color: #b9bdcb;
}

QMenuBar::item {
    padding: 5px 12px;
    border-radius: 6px;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #1c1f2b;
    color: #ffffff;
}

QMenu {
    background-color: #171a25;
    color: #d6d9e4;
    border: 1px solid #2b3040;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px;
    background: transparent;
}

QMenu::item:selected {
    background-color: rgba(99, 102, 241, 0.22);
    color: #e6e7ff;
}

QMenu::separator {
    height: 1px;
    background: #2b3040;
    margin: 6px 8px;
}

/* ═══════════════════════════════════════════════════════════════
   侧边栏
   ═══════════════════════════════════════════════════════════════ */

#sidebar {
    background-color: #0f1016;
    border-right: 1px solid #1e212b;
    min-width: 264px;
    max-width: 264px;
}

#sidebar_title {
    font-size: 21px;
    font-weight: 700;
    color: #f1f2f8;
    padding: 24px 22px 14px 22px;
    letter-spacing: 0.5px;
}

#sidebar QLabel#section_header,
#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #5f6475;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    padding: 6px 14px 2px 14px;
}

#sidebar_footer {
    color: #4c5060;
    padding: 14px 20px;
    font-size: 11px;
    letter-spacing: 0.5px;
}

/* 侧边栏分区卡片：悬浮在深色底上的低层表面 */
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
    color: #9ca1b1;
    border-radius: 8px;
    margin: 2px 8px;
}

QPushButton#nav_button:hover {
    background-color: #171a24;
    color: #e4e6ef;
}

QPushButton#nav_button:pressed {
    background-color: #1c1f2c;
}

QPushButton#nav_button[active="true"] {
    border-left: 3px solid #818cf8;
    background-color: rgba(99, 102, 241, 0.16);
    color: #c9ccff;
    font-weight: 600;
    padding-left: 11px;
}

/* ═══════════════════════════════════════════════════════════════
   内容区 / 页面文字
   ═══════════════════════════════════════════════════════════════ */

#content_area {
    background-color: #0b0c10;
}

#section_label {
    font-size: 13px;
    font-weight: 700;
    color: #d6d9e4;
    letter-spacing: 0.3px;
}

#page_subtitle {
    color: #9ca1b1;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: 700;
    color: #e6e8f0;
    margin-top: 4px;
}

#heading {
    font-size: 16px;
    font-weight: 700;
    color: #f0f1f7;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #f0f1f7;
}

#muted_text {
    color: #73788c;
    font-size: 12px;
}

#accent_text {
    color: #a5a8ff;
    font-size: 12px;
    font-weight: 600;
}

#success_text {
    color: #34d399;
    font-weight: 600;
}

/* ═══════════════════════════════════════════════════════════════
   卡片
   ═══════════════════════════════════════════════════════════════ */

#card {
    background-color: #151722;
    border: 1px solid #252938;
    border-radius: 12px;
}

#feature_card {
    background-color: #151722;
    border: 1px solid #252938;
    border-radius: 14px;
}

#feature_card:hover {
    border: 1px solid rgba(99, 102, 241, 0.45);
    background-color: #181b28;
}

#feature_title {
    font-size: 15px;
    font-weight: 700;
    color: #f0f1f7;
}

#feature_desc {
    font-size: 12px;
    color: #7d8296;
    line-height: 1.6;
}

#model_status_card {
    background-color: #1a1d2a;
    border: 1px solid #2e3347;
    border-radius: 10px;
}

#model_info_label {
    font-size: 13px;
    font-weight: 700;
    color: #e6e8f0;
}

#model_status_label {
    font-weight: 700;
    color: #a7abba;
}

#model_status_label[state="green"] { color: #34d399; }
#model_status_label[state="red"] { color: #f87171; }
#model_status_label[state="yellow"] { color: #fbbf24; }

#dim_score_card {
    background-color: #151722;
    border: 1px solid #252938;
    border-radius: 12px;
}

#preview_panel {
    background-color: #11131b;
    border: 1px solid #222633;
    border-radius: 10px;
}

#thumbnail_placeholder {
    border: 1px dashed #343a4d;
    border-radius: 8px;
    color: #6b7084;
    background-color: #10121a;
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
    background-color: #171a25;
    border: 1px solid #2b3040;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    color: #e2e4ec;
    selection-background-color: rgba(99, 102, 241, 0.35);
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
    border: 1px solid #3a4058;
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
    background-color: #1a1d2a;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #10121a;
    color: #525768;
    border: 1px solid #1d2029;
}

QLineEdit {
    placeholder-text-color: #5c6172;
}

QTextEdit,
QPlainTextEdit {
    placeholder-text-color: #5c6172;
}

/* ═══════════════════════════════════════════════════════════════
   下拉框
   ═══════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #171a25;
    border: 1px solid #2b3040;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    color: #e2e4ec;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #6366f1;
}

QComboBox:hover {
    border: 1px solid #3a4058;
}

QComboBox:on {
    border: 1px solid #6366f1;
    background-color: #1a1d2a;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: url("__ARROW_DOWN_ICON_URL__");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1a1d2a;
    color: #e2e4ec;
    border: 1px solid #33384d;
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
    background-color: #262b3d;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #6366f1;
    color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════
   按钮
   ═══════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #232736;
    border: 1px solid #2f3449;
    border-radius: 8px;
    padding: 7px 14px;
    color: #d9dce7;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #2a2f42;
    border: 1px solid #3a4058;
    color: #f0f1f7;
}

QPushButton:pressed {
    background-color: #323850;
}

QPushButton:disabled {
    background-color: #171a25;
    border: 1px solid #222633;
    color: #5a5f70;
}

QPushButton#primary_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #7c5cf6);
    border: 1px solid rgba(139, 118, 255, 0.35);
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
    background-color: #262a38;
    border: 1px solid #2b3040;
    color: #6a6f85;
}

QPushButton#secondary_button {
    background-color: transparent;
    border: 1px solid #33384d;
    color: #c8cbd8;
    font-weight: 500;
}

QPushButton#secondary_button:hover {
    background-color: #1e2230;
    border: 1px solid #454c68;
    color: #f0f1f7;
}

QPushButton#secondary_button[pressed="true"] {
    background-color: #262b3d;
}

QPushButton#action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
    border: 1px solid rgba(52, 211, 153, 0.3);
    color: #ffffff;
    font-weight: 600;
}

QPushButton#action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #14c98a, stop:1 #06a876);
    color: #ffffff;
}

QPushButton#action_button:disabled {
    background-color: #262a38;
    border: 1px solid #2b3040;
    color: #6a6f85;
}

QPushButton#pill_button {
    background-color: transparent;
    border: 1px solid #33384d;
    color: #c8cbd8;
    padding: 6px 16px;
    border-radius: 18px;
    font-weight: 500;
}

QPushButton#pill_button:hover {
    background-color: #1e2230;
    border: 1px solid #454c68;
    color: #f0f1f7;
}

QPushButton#pill_button:checked {
    background-color: rgba(99, 102, 241, 0.2);
    border: 1px solid rgba(129, 140, 248, 0.55);
    color: #c9ccff;
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
    background-color: #262a38;
    color: #6a6f85;
}

QPushButton#secondary_button[danger="true"] {
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.35);
    font-weight: 600;
}

QPushButton#secondary_button[danger="true"]:hover {
    background-color: rgba(248, 113, 113, 0.12);
    color: #fca5a5;
    border-color: rgba(248, 113, 113, 0.5);
}

QPushButton#delete_btn,
QPushButton#close_btn {
    color: #f87171;
}

QPushButton#delete_btn:hover,
QPushButton#close_btn:hover {
    background-color: rgba(248, 113, 113, 0.12);
    color: #fca5a5;
}

/* ═══════════════════════════════════════════════════════════════
   复选框 / 单选按钮
   ═══════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {
    color: #c3c6d2;
    spacing: 8px;
    background: transparent;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3a4058;
    border-radius: 5px;
    background-color: #171a25;
}

QCheckBox::indicator:hover {
    border: 2px solid #818cf8;
}

QCheckBox::indicator:checked {
    background-color: rgba(99, 102, 241, 0.32);
    border: 2px solid #818cf8;
    image: url("__CHECK_ICON_URL__");
}

QCheckBox::indicator:disabled {
    border: 2px solid #262b3d;
    background-color: #12141d;
}

QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #3a4058;
    border-radius: 9px;
    background-color: #171a25;
}

QRadioButton::indicator:hover {
    border: 2px solid #818cf8;
}

QRadioButton::indicator:checked {
    background-color: #6366f1;
    border: 2px solid #818cf8;
}

/* ═══════════════════════════════════════════════════════════════
   表格 / 列表
   ═══════════════════════════════════════════════════════════════ */

QTableWidget,
QTableView,
QListWidget {
    background-color: #12141d;
    border: 1px solid #252938;
    border-radius: 12px;
    gridline-color: #1c202c;
    selection-background-color: rgba(99, 102, 241, 0.26);
    selection-color: #eef0f8;
    alternate-background-color: #141720;
    color: #c3c6d2;
    outline: none;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #c3c6d2;
    padding: 6px 10px;
    min-height: 30px;
    border: none;
}

QTableWidget::item:hover,
QTableView::item:hover {
    background-color: rgba(255, 255, 255, 0.035);
}

QTableWidget::item:selected,
QTableView::item:selected,
QListWidget::item:selected {
    background-color: rgba(99, 102, 241, 0.26);
    color: #eef0f8;
}

QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 0.045);
    border-radius: 6px;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #3a4058;
    border-radius: 4px;
    background-color: #171a25;
}

QTableView::indicator:checked {
    background-color: rgba(99, 102, 241, 0.32);
    border: 2px solid #818cf8;
    image: url("__CHECK_ICON_URL__");
}

QHeaderView::section {
    background-color: #0e1018;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #232736;
    border-right: 1px solid #1c202c;
    font-weight: 700;
    font-size: 12px;
    color: #7d8296;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTableCornerButton::section {
    background-color: #0e1018;
    border: none;
    border-bottom: 2px solid #232736;
}

#side_list {
    background-color: #12141d;
    border: 1px solid #252938;
    border-radius: 10px;
}

/* ═══════════════════════════════════════════════════════════════
   进度条
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #1d2130;
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
    background-color: #0c0e16;
    color: #a8adbd;
    border: 1px solid #1d2130;
    border-radius: 10px;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    line-height: 1.6;
}

QTextEdit#log_box {
    background-color: #121527;
    color: #c3cde3;
    font-size: 12px;
    border-radius: 8px;
    border: 1px solid #2b3040;
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
    background: #2d3345;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #3d4560;
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
    background: #2d3345;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #3d4560;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════
   分组框 / Tab
   ═══════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #252938;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 16px;
    color: #c3c6d2;
    font-weight: 600;
    background-color: rgba(255, 255, 255, 0.008);
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #8f94a8;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTabWidget::pane {
    border: 1px solid #252938;
    background-color: #14161f;
    border-radius: 0 0 12px 12px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8f94a8;
    padding: 10px 20px;
    margin-right: 4px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: rgba(99, 102, 241, 0.1);
    color: #c9ccff;
    font-weight: 700;
    border-bottom: 2px solid #818cf8;
}

QTabBar::tab:hover:!selected {
    color: #e6e8f0;
    background-color: rgba(255, 255, 255, 0.04);
}

/* ═══════════════════════════════════════════════════════════════
   对话框 / 消息框
   ═══════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #14161f;
    color: #e6e8f0;
}

QMessageBox {
    background-color: #14161f;
    color: #e6e8f0;
}

QDialog QLabel,
QMessageBox QLabel {
    color: #d6d9e4;
}

QDialog QPushButton,
QMessageBox QPushButton {
    background-color: #232736;
    border: 1px solid #2f3449;
    border-radius: 8px;
    padding: 7px 18px;
    color: #d9dce7;
    min-width: 84px;
    font-weight: 500;
}

QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #2a2f42;
    color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════
   滑块
   ═══════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    height: 5px;
    background: #1d2130;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: #818cf8;
    border: 2px solid #151722;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #a5a8ff;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════════════
   分割线 / 分隔条
   ═══════════════════════════════════════════════════════════════ */

#separator {
    color: #232736;
    background-color: #232736;
}

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #232736;
}

QSplitter::handle {
    background-color: #1e212b;
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
    background-color: rgba(17, 19, 28, 0.88);
    border: 1px solid rgba(255, 255, 255, 0.1);
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
    color: #8f94a8;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#status_overlay QLabel#ov_icon {
    font-size: 13px;
}

#status_overlay QLabel#ov_name {
    color: #8f94a8;
    font-weight: 500;
}

#status_overlay QLabel#ov_value {
    color: #e6e8f0;
    font-weight: 700;
}

#status_overlay QLabel#ov_value[level="ok"] {
    color: #34d399;
}

#status_overlay QLabel#ov_value[level="warn"] {
    color: #fbbf24;
}

#status_overlay QLabel#ov_value[level="bad"] {
    color: #f87171;
}

#status_overlay QLabel#ov_value[level="idle"] {
    color: #6b7080;
}

#status_overlay QLabel#ov_service {
    color: #98a0b2;
    font-weight: 500;
}

#status_overlay QLabel#ov_service[state="ok"] {
    color: #34d399;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="bad"] {
    color: #f87171;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="unknown"] {
    color: #6b7080;
}

#status_separator {
    background-color: rgba(255, 255, 255, 0.16);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   状态标签
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: 700;
}

#login_status_label[state="green"] { color: #34d399; }
#login_status_label[state="red"] { color: #f87171; }
#login_status_label[state="yellow"] { color: #fbbf24; }

#llm_status_label {
    font-weight: 700;
}

#llm_status_label[state="green"] { color: #34d399; }
#llm_status_label[state="red"] { color: #f87171; }
#llm_status_label[state="yellow"] { color: #fbbf24; }

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #34d399; }
#ollama_status_lbl[state="red"] { color: #f87171; }
#ollama_status_lbl[state="yellow"] { color: #fbbf24; }
#ollama_status_lbl[state="gray"] { color: #9ca3af; }

/* ═══════════════════════════════════════════════════════════════
   素材管理 / NAS
   ═══════════════════════════════════════════════════════════════ */

#step_bar {
    background-color: #151722;
    border: 1px solid #252938;
    border-radius: 10px;
}

#step_label {
    color: #7d8296;
    padding: 4px 0;
    font-size: 13px;
}

#step_label[status="active"] {
    color: #60a5fa;
    font-weight: 700;
    background-color: rgba(96, 165, 250, 0.12);
    border-radius: 6px;
    padding: 4px 8px;
}

#step_label[status="done"] {
    color: #34d399;
    background-color: rgba(52, 211, 153, 0.1);
    border-radius: 6px;
    padding: 4px 8px;
}

#step_label[status="pending"] {
    color: #7d8296;
}

#nas_root_label {
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
}

#stats_analyze, #stats_ingest {
    font-size: 13px;
    color: #ffffff;
}

#btn_refresh_stats {
    background-color: #232736;
    border: 1px solid #2f3449;
    border-radius: 6px;
    color: #e6e8f0;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_refresh_stats:hover {
    background-color: #2a2f42;
    color: #ffffff;
}

#btn_align {
    background-color: #1e3a5f;
    border: 1px solid #2b4a7a;
    border-radius: 6px;
    color: #93c5fd;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_align:hover {
    background-color: #1e40af;
    color: #ffffff;
}

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog {
    background-color: #12141d;
    color: #f8fafc;
}

#cover_section_title {
    font-size: 13px;
    color: #94a3b8;
}

#cover_video_widget {
    background-color: #000000;
    border-radius: 8px;
    border: 1px solid #2b3040;
}

#cover_time_label {
    color: #94a3b8;
}

#cover_preview_h,
#cover_preview_v {
    background-color: #0c0e16;
    border-radius: 8px;
    border: 1px solid #2b3040;
}

#clip_list_item_title {
    font-size: 13px;
    color: #f8fafc;
}

#clip_list_item_score {
    color: #fbbf24;
    font-weight: 700;
}

#clip_list_item_meta {
    color: #94a3b8;
    font-size: 11px;
}

#clip_list_separator {
    background-color: #2e3347;
    max-height: 1px;
}

#clip_list_item_time {
    color: #94a3b8;
    font-size: 11px;
}

#export_step_label {
    padding: 6px 12px;
}

#export_step_label[status="active"] {
    color: #60a5fa;
    font-weight: 700;
    background-color: rgba(96, 165, 250, 0.12);
    border-radius: 6px;
}

#export_step_label[status="done"] {
    color: #34d399;
    background-color: rgba(52, 211, 153, 0.1);
    border-radius: 6px;
}

#export_step_label[status="pending"] {
    color: #7d8296;
}

#clip_page_title {
    font-size: 14px;
    color: #f8fafc;
}

#clip_status_label {
    color: #94a3b8;
}

#export_result_label {
    color: #34d399;
    font-weight: 700;
}

#video_info_label {
    color: #60a5fa;
}

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px;
    font-weight: 700;
    border: 1px solid #252938;
    border-radius: 10px;
    margin-top: 12px;
    background-color: rgba(255, 255, 255, 0.008);
}

#model_groupbox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

#ollama_models_lbl {
    color: #8f94a8;
    font-size: 11px;
}

#ollama_runners_warn {
    color: #f87171;
    font-size: 12px;
}

#ollama_progress_lbl {
    color: #fbbf24;
    font-size: 11px;
}

#model_groupbox[section="llm"]::title     { color: #60a5fa; }
#model_groupbox[section="vox"]::title     { color: #a78bfa; }
#model_groupbox[section="whisper"]::title { color: #34d399; }
#model_groupbox[section="ocr"]::title     { color: #fbbf24; }

#comfyui_local_status {
    color: #8f94a8;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   AI 重命名 / 视频播放器 对话框
   ═══════════════════════════════════════════════════════════════ */

#aiRenameTable {
    background-color: #12141d;
    border: 1px solid #252938;
    border-radius: 10px;
}

#aiRenameLogPanel,
#aiRenameLogTitle {
    background-color: #0c0e16;
    border: 1px solid #1d2130;
    border-radius: 8px;
}

#aiRenameModelInfo {
    color: #8f94a8;
    font-size: 12px;
}

#aiRenameDesc {
    color: #a7abba;
    font-size: 12px;
}

#videoPlayerDialog {
    background-color: #12141d;
}

#videoPlayerLeft,
#videoPlayerRight {
    background-color: #151722;
    border: 1px solid #252938;
    border-radius: 10px;
}

#videoPlayerInfoLabel,
#videoPlayerFileLabel {
    color: #e6e8f0;
    font-size: 13px;
    font-weight: 600;
}

#videoPlayerFrameStatus,
#videoPlayerTime,
#videoPlayerHint {
    color: #8f94a8;
    font-size: 12px;
}

#videoPlayerDivider {
    background-color: #2b3040;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   其他
   ═══════════════════════════════════════════════════════════════ */

#batchReplaceDialog {
    background-color: #14161f;
}

#terminalPrompt {
    color: #34d399;
    font-family: 'Consolas', monospace;
}

#themeSplitter::handle {
    background-color: #1e212b;
}

#themeSeparator {
    background-color: #232736;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   启动/关闭闪屏 · 激活对话框
   ═══════════════════════════════════════════════════════════════ */

QWidget#startup_splash {
    background: transparent;
}

QFrame#splash_card {
    background-color: #151722;
    border: 1px solid #2b3040;
    border-radius: 14px;
}

QFrame#splash_card QLabel {
    color: #d6d9e4;
    background: transparent;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#splash_title {
    font-size: 18px;
    color: #f0f1f7;
}

QLabel#splash_status {
    font-size: 13px;
    color: #a5a8ff;
}

QDialog#close_splash {
    background-color: #151722;
    border: 1px solid #2b3040;
    border-radius: 14px;
}

QDialog#close_splash QLabel {
    color: #d6d9e4;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#close_splash_title {
    font-size: 15px;
    color: #f0f1f7;
}

QLabel#close_splash_status {
    font-size: 12px;
    color: #8f94a8;
}

QLabel#activation_title {
    font-size: 20px;
    font-weight: 700;
    color: #f0f1f7;
}

QLabel#activation_machine_id {
    color: #a5a8ff;
    font-family: monospace;
    font-size: 12px;
    background-color: #171a25;
    border: 1px solid #2b3040;
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
    background-color: #151722;
    border: 1px solid #2b3040;
    border-radius: 12px;
}

QLabel#about_app_title {
    font-size: 18px;
    font-weight: 700;
    color: #f0f1f7;
}

QLabel#about_dev_info {
    font-size: 13px;
    color: #a7abba;
}

QLabel#about_contact {
    font-size: 13px;
    color: #d6d9e4;
}

QLabel#about_license_title {
    font-size: 13px;
    font-weight: 700;
    color: #34d399;
}

QLabel#about_version_title {
    font-size: 13px;
    font-weight: 700;
    color: #60a5fa;
}

QLineEdit#about_machine_id {
    color: #60a5fa;
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
    color: #c3c6d2;
}

/* ═══════════════════════════════════════════════════════════════
   节拍视图（智能混剪）专用
   ═══════════════════════════════════════════════════════════════ */

#segment_card {
    background-color: #151722;
    border: 1px solid #2b3040;
    border-radius: 10px;
}

QScrollArea#beat_cards_scroll {
    border: 1px solid #252938;
    border-radius: 10px;
    background: #12141d;
}

QLabel#beat_time_label {
    background-color: #1d2130;
    color: #fbbf24;
    font-family: Consolas, monospace;
    font-size: 9pt;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
}

QLabel#beat_clips_info {
    color: #34d399;
    font-weight: 700;
}

QLabel#beat_preview_title {
    color: #fbbf24;
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
    color: #9ca3af;
    border-radius: 4px;
}

QPushButton#table_action_button:hover {
    color: #ffffff;
    background: rgba(255, 255, 255, 0.1);
}

QLabel#dev_icon {
    font-size: 48px;
}

QLabel#dev_title {
    font-size: 20px;
    font-weight: 700;
    color: #a7abba;
}

QLabel#dev_subtitle {
    font-size: 14px;
    color: #73788c;
}
""".replace("__CHECK_ICON_URL__", _CHECK_ICON_URL).replace("__ARROW_DOWN_ICON_URL__", _ARROW_DOWN_ICON_URL)
