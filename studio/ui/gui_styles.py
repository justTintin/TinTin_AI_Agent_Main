# -*- coding: utf-8 -*-
"""
暗色主题 QSS · 螺丝钉-电商智能体矩阵 v3.0
设计系统：Luosiding Design Library
背景：--luosiding-slate-950 #0b0c10；主色：--luosiding-indigo-400 #6366f1；强调：--luosiding-violet-500 #8b5cf6
"""
import os

from config.paths import BUNDLE_ICONS_DIR

_CHECK_ICON = os.path.join(BUNDLE_ICONS_DIR, "check.svg")
_CHECK_ICON_URL = _CHECK_ICON.replace(os.sep, '/')

_ARROW_DOWN_ICON = os.path.join(BUNDLE_ICONS_DIR, "arrow_down.svg")
_ARROW_DOWN_ICON_URL = _ARROW_DOWN_ICON.replace(os.sep, '/')

STYLE_SHEET = """
/* ═══════════════════════════════════════════════════════════════
   基础元素 / Base
   tokens: --background #0b0c10, --foreground #f0f1f7
   ═══════════════════════════════════════════════════════════════ */

* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", "Segoe UI", sans-serif;
    outline: none;
}

QMainWindow, QWidget {
    background-color: #0b0c10 /* --luosiding-slate-950 --background */;
}

QToolTip {
    background-color: #1e212b /* --luosiding-slate-800 --surface-container */;
    color: #f0f1f7 /* --luosiding-slate-50 */;
    border: 1px solid #2b3040 /* --luosiding-slate-700 --border */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 11px;
    font-size: 12px;
}

QLabel {
    color: #c3c6d2 /* --luosiding-slate-100 --muted-foreground */;
    background: transparent;
}

QStatusBar {
    background-color: #0b0c10 /* --background */;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    border-top: 1px solid #2b3040 /* --border */;
}

QMenuBar {
    background-color: #151722 /* --luosiding-slate-900 --surface */;
    color: #c3c6d2 /* --muted-foreground */;
}

QMenuBar::item {
    padding: 5px 12px;
    border-radius: 6px /* --radius-sm */;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #1e212b /* --surface-container */;
    color: #ffffff /* --luosiding-slate-0 --primary-foreground */;
}

QMenu {
    background-color: #151722 /* --surface */;
    color: #f0f1f7 /* --foreground */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
    padding: 6px;
}

QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px /* --radius-sm */;
    background: transparent;
}

QMenu::item:selected {
    background-color: rgba(99, 102, 241, 0.18) /* --interactive-hover */;
    color: #c7d2fe /* --luosiding-indigo-100 */;
}

QMenu::separator {
    height: 1px;
    background: #2b3040 /* --border */;
    margin: 6px 8px;
}

/* ═══════════════════════════════════════════════════════════════
   侧边栏 / Sidebar
   token: --color-sidebar --surface-container-low #151722
   ═══════════════════════════════════════════════════════════════ */

#sidebar {
    background-color: #151722 /* --surface-container-low */;
    border-right: 1px solid #1e212b /* --luosiding-slate-800 */;
    min-width: 264px;
    max-width: 264px;
}

#sidebar_title {
    font-size: 21px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
    padding: 24px 22px 14px 22px;
    letter-spacing: 0.5px;
}

#sidebar QLabel#section_header,
#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #5f6475 /* --luosiding-slate-400 */;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    padding: 6px 14px 2px 14px;
}

#sidebar_footer {
    color: #4c5060 /* --luosiding-slate-500 */;
    padding: 14px 20px;
    font-size: 11px;
    letter-spacing: 0.5px;
}

#sidebar QFrame[section_type="ai"],
#sidebar QFrame[section_type="system"] {
    background-color: transparent;
    border: none;
}

/* 系统设置二级菜单侧边栏 */
#settings_menu_panel {
    background-color: #151722 /* --surface-container-low */;
    border-right: 1px solid #1e212b /* --luosiding-slate-800 */;
    min-width: 200px;
    max-width: 200px;
}

#settings_stack {
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
    color: #9ca1b1 /* --luosiding-slate-200 */;
    border-radius: 8px /* --radius-md */;
    margin: 2px 8px;
}

QPushButton#nav_button:hover {
    background-color: rgba(99, 102, 241, 0.12) /* --interactive-hover */;
    color: #f0f1f7 /* --foreground */;
}

QPushButton#nav_button:pressed {
    background-color: rgba(99, 102, 241, 0.24) /* --interactive-press */;
}

QPushButton#nav_button[active="true"] {
    border-left: 3px solid #6366f1 /* --luosiding-indigo-400 --primary */;
    background-color: rgba(99, 102, 241, 0.16);
    color: #c7d2fe /* --luosiding-indigo-100 */;
    font-weight: 600;
    padding-left: 11px;
}

/* ═══════════════════════════════════════════════════════════════
   内容区 / 页面文字
   ═══════════════════════════════════════════════════════════════ */

#content_area {
    background-color: #0b0c10 /* --background */;
}

#section_label {
    font-size: 13px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
    letter-spacing: 0.3px;
}

#page_subtitle {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
    margin-top: 4px;
}

#heading {
    font-size: 16px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

#muted_text {
    color: #73788c /* --luosiding-slate-300 --muted-foreground */;
    font-size: 12px;
}

#accent_text {
    color: #a5b4fc /* --luosiding-indigo-200 */;
    font-size: 12px;
    font-weight: 600;
}

#success_text {
    color: #34d399 /* --luosiding-success-400 --color-success */;
    font-weight: 600;
}

/* ═══════════════════════════════════════════════════════════════
   卡片 / Card
   token: --color-card --surface #151722, --border #2b3040, --radius-xl 12px
   ═══════════════════════════════════════════════════════════════ */

#card {
    background-color: #151722 /* --surface --color-card */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

#search_sidebar {
    background-color: #151722 /* --surface --color-card */;
    border: 1px solid #2b3040 /* --border */;
    border-right: none;
    border-top-left-radius: 12px /* --radius-xl */;
    border-bottom-left-radius: 12px /* --radius-xl */;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
}

/* 即梦素材网格：与素材库页保持一致的紧凑网格 */
#dreamina_file_list {
    background-color: transparent;
    border: none;
    padding: 0;
    margin: 0;
}

#dreamina_file_list::item {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 6px /* --radius-sm */;
    color: #c3c6d2 /* --muted-foreground */;
    padding: 0;
    margin: 0;
}

#dreamina_file_list::item:selected {
    background-color: rgba(99, 102, 241, 0.26);
    border: 1px solid #6366f1 /* --primary */;
    color: #f0f1f7 /* --foreground */;
}

#dreamina_file_list::item:hover {
    background-color: #1c1f2b /* --surface-container-high */;
}

#feature_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

#feature_card:hover {
    border: 1px solid #6366f1 /* --primary */;
    background-color: #1e212b /* --surface-container */;
}

#feature_title {
    font-size: 15px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

#feature_desc {
    font-size: 12px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    line-height: 1.6;
}

#model_status_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#model_info_label {
    font-size: 13px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

#model_status_label {
    font-weight: 700;
    color: #c3c6d2 /* --luosiding-slate-100 */;
}

#model_status_label[state="green"] { color: #34d399 /* --color-success */; }
#model_status_label[state="red"] { color: #f87171 /* --color-error */; }
#model_status_label[state="yellow"] { color: #fbbf24 /* --color-warning */; }

#dim_score_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

#preview_panel {
    background-color: #0b0c10 /* --background */;
    border: 1px solid #1e212b /* --surface-container */;
    border-radius: 10px /* --radius-lg */;
}

#thumbnail_placeholder {
    border: 1px dashed #3a3e4b /* --luosiding-slate-600 --surface-container-highest */;
    border-radius: 8px /* --radius-md */;
    color: #5f6475 /* --luosiding-slate-400 */;
    background-color: #0b0c10 /* --background */;
}

/* ═══════════════════════════════════════════════════════════════
   输入控件 / Input
   tokens: --surface #151722, --border #2b3040, --radius-md 8px
   ═══════════════════════════════════════════════════════════════ */

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QDateEdit,
QTimeEdit,
QDateTimeEdit {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 8px 12px;
    font-size: 13px;
    color: #f0f1f7 /* --foreground */;
    selection-background-color: rgba(99, 102, 241, 0.35);
    selection-color: #ffffff /* --luosiding-slate-0 */;
}

QLineEdit:hover,
QTextEdit:hover,
QPlainTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QDateEdit:hover,
QTimeEdit:hover,
QDateTimeEdit:hover {
    border: 1px solid #3a3e4b /* --surface-container-highest */;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QDateEdit:focus,
QTimeEdit:focus,
QDateTimeEdit:focus {
    border: 1px solid #6366f1 /* --primary */;
    background-color: #1e212b /* --surface-container */;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #0b0c10 /* --background */;
    color: #4c5060 /* --luosiding-slate-500 */;
    border: 1px solid #1e212b /* --surface-container */;
}

QLineEdit {
    placeholder-text-color: #5f6475 /* --luosiding-slate-400 */;
}

QTextEdit,
QPlainTextEdit {
    placeholder-text-color: #5f6475 /* --luosiding-slate-400 */;
}

/* ═══════════════════════════════════════════════════════════════
   下拉框 / ComboBox
   ═══════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 6px 12px;
    font-size: 13px;
    color: #f0f1f7 /* --foreground */;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #6366f1 /* --primary */;
}

QComboBox:hover {
    border: 1px solid #3a3e4b /* --surface-container-highest */;
}

QComboBox:on {
    border: 1px solid #6366f1 /* --primary */;
    background-color: #1e212b /* --surface-container */;
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
    background-color: #1e212b /* --surface-container */;
    color: #f0f1f7 /* --foreground */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 4px;
    selection-background-color: #6366f1 /* --primary */;
    selection-color: #ffffff /* --primary-foreground */;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 8px 12px;
    border-radius: 6px /* --radius-sm */;
    min-height: 20px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #2b3040 /* --surface-container-high */;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #6366f1 /* --primary */;
    color: #ffffff /* --primary-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   按钮 / Button
   tokens: .btn.primary #6366f1, .secondary #2b3040, .ghost transparent
   ═══════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #2b3040 /* --luosiding-slate-700 */;
    border: 1px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 14px;
    color: #f0f1f7 /* --foreground */;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #3a3e4b /* --surface-container-highest */;
    border: 1px solid #4c5060 /* --luosiding-slate-500 */;
    color: #ffffff /* --primary-foreground */;
}

QPushButton:pressed {
    background-color: #4c5060 /* --luosiding-slate-500 */;
}

QPushButton:disabled {
    background-color: #151722 /* --surface */;
    border: 1px solid #1e212b /* --surface-container */;
    color: #5f6475 /* --luosiding-slate-400 */;
}

QPushButton#primary_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border: 1px solid rgba(139, 118, 255, 0.35);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #818cf8 /* --luosiding-indigo-300 */, stop:1 #a78bfa /* --luosiding-violet-400 */);
    color: #ffffff /* --primary-foreground */;
}

QPushButton#primary_button:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5 /* --luosiding-indigo-500 */, stop:1 #7c3aed /* --luosiding-violet-600 */);
}

QPushButton#primary_button:disabled {
    background-color: #1e212b /* --surface-container */;
    border: 1px solid #2b3040 /* --border */;
    color: #5f6475 /* --luosiding-slate-400 */;
}

QPushButton#secondary_button {
    background-color: transparent;
    border: 1px solid #2b3040 /* --border */;
    color: #c3c6d2 /* --luosiding-slate-100 */;
    font-weight: 500;
}

QPushButton#secondary_button:hover {
    background-color: rgba(99, 102, 241, 0.12) /* --interactive-hover */;
    border: 1px solid #3a3e4b /* --surface-container-highest */;
    color: #f0f1f7 /* --foreground */;
}

QPushButton#secondary_button[pressed="true"] {
    background-color: #2b3040 /* --surface-container-high */;
}

QPushButton#action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981 /* --luosiding-success-500 */, stop:1 #059669 /* --luosiding-success-600 */);
    border: 1px solid rgba(52, 211, 153, 0.3);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399 /* --luosiding-success-400 */, stop:1 #10b981 /* --luosiding-success-500 */);
    color: #ffffff /* --primary-foreground */;
}

QPushButton#action_button:disabled {
    background-color: #1e212b /* --surface-container */;
    border: 1px solid #2b3040 /* --border */;
    color: #5f6475 /* --luosiding-slate-400 */;
}

QPushButton#pill_button {
    background-color: transparent;
    border: 1px solid #2b3040 /* --border */;
    color: #c3c6d2 /* --luosiding-slate-100 */;
    padding: 6px 16px;
    border-radius: 18px;
    font-weight: 500;
}

QPushButton#pill_button:hover {
    background-color: rgba(99, 102, 241, 0.12) /* --interactive-hover */;
    border: 1px solid #3a3e4b /* --surface-container-highest */;
    color: #f0f1f7 /* --foreground */;
}

QPushButton#pill_button:checked {
    background-color: rgba(99, 102, 241, 0.2);
    border: 1px solid rgba(129, 140, 248, 0.55);
    color: #c7d2fe /* --luosiding-indigo-100 */;
    font-weight: 600;
}

QPushButton#floating_action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981 /* --luosiding-success-500 */, stop:1 #059669 /* --luosiding-success-600 */);
    border: none;
    color: #ffffff /* --primary-foreground */;
    font-weight: 700;
    border-radius: 22px;
    padding: 9px 18px;
    margin: 10px;
}

QPushButton#floating_action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399 /* --luosiding-success-400 */, stop:1 #10b981 /* --luosiding-success-500 */);
}

QPushButton#floating_action_button:disabled {
    background-color: #1e212b /* --surface-container */;
    color: #5f6475 /* --luosiding-slate-400 */;
}

QPushButton#secondary_button[danger="true"] {
    color: #f87171 /* --color-error */;
    border-color: rgba(248, 113, 113, 0.35);
    font-weight: 600;
}

QPushButton#secondary_button[danger="true"]:hover {
    background-color: rgba(248, 113, 113, 0.12);
    color: #fca5a5 /* --luosiding-error-300 */;
    border-color: rgba(248, 113, 113, 0.5);
}

QPushButton#danger_button {
    background-color: #ef4444 /* --luosiding-error-500 */;
    border: 1px solid rgba(248, 113, 113, 0.5);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#danger_button:hover {
    background-color: #f87171 /* --color-error */;
}

QPushButton#delete_btn,
QPushButton#close_btn {
    color: #f87171 /* --color-error */;
}

QPushButton#delete_btn:hover,
QPushButton#close_btn:hover {
    background-color: rgba(248, 113, 113, 0.12);
    color: #fca5a5 /* --luosiding-error-300 */;
}

/* ═══════════════════════════════════════════════════════════════
   复选框 / 单选按钮
   ═══════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {
    color: #c3c6d2 /* --muted-foreground */;
    spacing: 8px;
    background: transparent;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 5px;
    background-color: #151722 /* --surface */;
}

QCheckBox::indicator:hover {
    border: 2px solid #818cf8 /* --luosiding-indigo-300 */;
}

QCheckBox::indicator:checked {
    background-color: rgba(99, 102, 241, 0.32);
    border: 2px solid #818cf8 /* --luosiding-indigo-300 */;
    image: url("__CHECK_ICON_URL__");
}

QCheckBox::indicator:disabled {
    border: 2px solid #2b3040 /* --surface-container-high */;
    background-color: #0b0c10 /* --background */;
}

QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 9px;
    background-color: #151722 /* --surface */;
}

QRadioButton::indicator:hover {
    border: 2px solid #818cf8 /* --luosiding-indigo-300 */;
}

QRadioButton::indicator:checked {
    background-color: #6366f1 /* --primary */;
    border: 2px solid #818cf8 /* --luosiding-indigo-300 */;
}

/* ═══════════════════════════════════════════════════════════════
   表格 / 列表 / Table & List
   ═══════════════════════════════════════════════════════════════ */

QTableWidget,
QTableView,
QListWidget {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 12px /* --radius-xl */;
    gridline-color: #1e212b /* --surface-container */;
    selection-background-color: rgba(99, 102, 241, 0.26);
    selection-color: #f0f1f7 /* --foreground */;
    alternate-background-color: #0b0c10 /* --background */;
    color: #c3c6d2 /* --muted-foreground */;
    outline: none;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #c3c6d2 /* --muted-foreground */;
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
    color: #f0f1f7 /* --foreground */;
}

QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 0.045);
    border-radius: 6px /* --radius-sm */;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 4px;
    background-color: #151722 /* --surface */;
}

QTableView::indicator:checked {
    background-color: rgba(99, 102, 241, 0.32);
    border: 2px solid #818cf8 /* --luosiding-indigo-300 */;
    image: url("__CHECK_ICON_URL__");
}

QHeaderView::section {
    background-color: #0b0c10 /* --background */;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #2b3040 /* --border */;
    border-right: 1px solid #1e212b /* --surface-container */;
    font-weight: 700;
    font-size: 12px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTableCornerButton::section {
    background-color: #0b0c10 /* --background */;
    border: none;
    border-bottom: 2px solid #2b3040 /* --border */;
}

#side_list {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

/* ═══════════════════════════════════════════════════════════════
   进度条 / ProgressBar
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #1e212b /* --surface-container */;
    text-align: center;
    height: 6px;
    color: transparent;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border-radius: 4px;
}

/* ═══════════════════════════════════════════════════════════════
   日志查看器 / 日志输出框
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_viewer {
    background-color: #0b0c10 /* --background */;
    color: #c3c6d2 /* --muted-foreground */;
    border: 1px solid #1e212b /* --surface-container */;
    border-radius: 10px /* --radius-lg */;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    line-height: 1.6;
}

QTextEdit#log_box {
    background-color: #151722 /* --surface */;
    color: #c3c6d2 /* --muted-foreground */;
    font-size: 12px;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #2b3040 /* --border */;
    font-family: "Consolas", "JetBrains Mono", monospace;
}

/* ═══════════════════════════════════════════════════════════════
   滚动条 / ScrollBar
   ═══════════════════════════════════════════════════════════════ */

QScrollBar:vertical {
    width: 9px;
    background: transparent;
    margin: 4px 2px;
}

QScrollBar::handle:vertical {
    background: #2b3040 /* --surface-container-high */;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #3a3e4b /* --surface-container-highest */;
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
    background: #2b3040 /* --surface-container-high */;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #3a3e4b /* --surface-container-highest */;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════
   分组框 / Tab
   ═══════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
    margin-top: 12px;
    padding-top: 16px;
    color: #c3c6d2 /* --muted-foreground */;
    font-weight: 600;
    background-color: rgba(255, 255, 255, 0.008);
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTabWidget::pane {
    border: 1px solid #2b3040 /* --border */;
    background-color: #151722 /* --surface */;
    border-radius: 0 0 12px 12px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    padding: 10px 20px;
    margin-right: 4px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: rgba(99, 102, 241, 0.1);
    color: #c7d2fe /* --luosiding-indigo-100 */;
    font-weight: 700;
    border-bottom: 2px solid #818cf8 /* --luosiding-indigo-300 */;
}

QTabBar::tab:hover:!selected {
    color: #f0f1f7 /* --foreground */;
    background-color: rgba(255, 255, 255, 0.04);
}

/* ═══════════════════════════════════════════════════════════════
   对话框 / 消息框
   ═══════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #151722 /* --surface */;
    color: #f0f1f7 /* --foreground */;
}

QMessageBox {
    background-color: #151722 /* --surface */;
    color: #f0f1f7 /* --foreground */;
}

QDialog QLabel,
QMessageBox QLabel {
    color: #f0f1f7 /* --foreground */;
}

QDialog QPushButton,
QMessageBox QPushButton {
    background-color: #2b3040 /* --surface-container-high */;
    border: 1px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 18px;
    color: #f0f1f7 /* --foreground */;
    min-width: 84px;
    font-weight: 500;
}

QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #3a3e4b /* --surface-container-highest */;
    color: #ffffff /* --primary-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   滑块 / Slider
   ═══════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    height: 5px;
    background: #1e212b /* --surface-container */;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: #818cf8 /* --luosiding-indigo-300 */;
    border: 2px solid #151722 /* --surface */;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #a5b4fc /* --luosiding-indigo-200 */;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════════════
   分割线 / 分隔条
   ═══════════════════════════════════════════════════════════════ */

#separator {
    color: #2b3040 /* --surface-container-high */;
    background-color: #2b3040 /* --surface-container-high */;
}

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #2b3040 /* --surface-container-high */;
}

QSplitter::handle {
    background-color: #1e212b /* --surface-container */;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ═══════════════════════════════════════════════════════════════
   状态栏浮层 / Status Overlay
   ═══════════════════════════════════════════════════════════════ */

#status_overlay {
    background-color: rgba(17, 19, 28, 0.88);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 10px /* --radius-lg */;
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
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#status_overlay QLabel#ov_icon {
    font-size: 13px;
}

#status_overlay QLabel#ov_name {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-weight: 500;
}

#status_overlay QLabel#ov_value {
    color: #f0f1f7 /* --foreground */;
    font-weight: 700;
}

#status_overlay QLabel#ov_value[level="ok"] {
    color: #34d399 /* --color-success */;
}

#status_overlay QLabel#ov_value[level="warn"] {
    color: #fbbf24 /* --color-warning */;
}

#status_overlay QLabel#ov_value[level="bad"] {
    color: #f87171 /* --color-error */;
}

#status_overlay QLabel#ov_value[level="idle"] {
    color: #5f6475 /* --luosiding-slate-400 */;
}

#status_overlay QLabel#ov_service {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-weight: 500;
}

#status_overlay QLabel#ov_service[state="ok"] {
    color: #34d399 /* --color-success */;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="bad"] {
    color: #f87171 /* --color-error */;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="unknown"] {
    color: #5f6475 /* --luosiding-slate-400 */;
}

#status_separator {
    background-color: rgba(255, 255, 255, 0.16);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   状态标签 / Status Labels
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: 700;
}

#login_status_label[state="green"] { color: #34d399 /* --color-success */; }
#login_status_label[state="red"] { color: #f87171 /* --color-error */; }
#login_status_label[state="yellow"] { color: #fbbf24 /* --color-warning */; }

#llm_status_label {
    font-weight: 700;
}

#llm_status_label[state="green"] { color: #34d399 /* --color-success */; }
#llm_status_label[state="red"] { color: #f87171 /* --color-error */; }
#llm_status_label[state="yellow"] { color: #fbbf24 /* --color-warning */; }

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #34d399 /* --color-success */; }
#ollama_status_lbl[state="red"] { color: #f87171 /* --color-error */; }
#ollama_status_lbl[state="yellow"] { color: #fbbf24 /* --color-warning */; }
#ollama_status_lbl[state="gray"] { color: #9ca1b1 /* --luosiding-slate-200 */; }

/* ═══════════════════════════════════════════════════════════════
   素材管理 / NAS
   ═══════════════════════════════════════════════════════════════ */

#step_bar {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#step_label {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    padding: 4px 0;
    font-size: 13px;
}

#step_label[status="active"] {
    color: #60a5fa /* --color-info */;
    font-weight: 700;
    background-color: rgba(96, 165, 250, 0.12);
    border-radius: 6px /* --radius-sm */;
    padding: 4px 8px;
}

#step_label[status="done"] {
    color: #34d399 /* --color-success */;
    background-color: rgba(52, 211, 153, 0.1);
    border-radius: 6px /* --radius-sm */;
    padding: 4px 8px;
}

#step_label[status="pending"] {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#nas_root_label {
    font-size: 13px;
    font-weight: 700;
    color: #ffffff /* --primary-foreground */;
}

#stats_analyze, #stats_ingest {
    font-size: 13px;
    color: #ffffff /* --primary-foreground */;
}

#btn_refresh_stats {
    background-color: #2b3040 /* --surface-container-high */;
    border: 1px solid #3a3e4b /* --surface-container-highest */;
    border-radius: 6px /* --radius-sm */;
    color: #f0f1f7 /* --foreground */;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_refresh_stats:hover {
    background-color: #3a3e4b /* --surface-container-highest */;
    color: #ffffff /* --primary-foreground */;
}

#btn_align {
    background-color: #1e3a8a /* --luosiding-info-900 */;
    border: 1px solid #1e40af /* --luosiding-info-800 */;
    border-radius: 6px /* --radius-sm */;
    color: #93c5fd /* --luosiding-info-300 */;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_align:hover {
    background-color: #1e40af /* --luosiding-info-800 */;
    color: #ffffff /* --primary-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog {
    background-color: #151722 /* --surface */;
    color: #f0f1f7 /* --foreground */;
}

#cover_section_title {
    font-size: 13px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#cover_video_widget {
    background-color: #000000;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #2b3040 /* --border */;
}

#cover_time_label {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#cover_preview_h,
#cover_preview_v {
    background-color: #0b0c10 /* --background */;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #2b3040 /* --border */;
}

#clip_list_item_title {
    font-size: 13px;
    color: #f0f1f7 /* --foreground */;
}

#clip_list_item_score {
    color: #fbbf24 /* --color-warning */;
    font-weight: 700;
}

#clip_list_item_meta {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 11px;
}

#clip_list_separator {
    background-color: #2b3040 /* --border */;
    max-height: 1px;
}

#clip_list_item_time {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 11px;
}

#export_step_label {
    padding: 6px 12px;
}

#export_step_label[status="active"] {
    color: #60a5fa /* --color-info */;
    font-weight: 700;
    background-color: rgba(96, 165, 250, 0.12);
    border-radius: 6px /* --radius-sm */;
}

#export_step_label[status="done"] {
    color: #34d399 /* --color-success */;
    background-color: rgba(52, 211, 153, 0.1);
    border-radius: 6px /* --radius-sm */;
}

#export_step_label[status="pending"] {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#clip_page_title {
    font-size: 14px;
    color: #f0f1f7 /* --foreground */;
}

#clip_status_label {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#export_result_label {
    color: #34d399 /* --color-success */;
    font-weight: 700;
}

#video_info_label {
    color: #60a5fa /* --color-info */;
}

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px;
    font-weight: 700;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
    margin-top: 12px;
    background-color: rgba(255, 255, 255, 0.008);
}

#model_groupbox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

#ollama_models_lbl {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 11px;
}

#ollama_runners_warn {
    color: #f87171 /* --color-error */;
    font-size: 12px;
}

#ollama_progress_lbl {
    color: #fbbf24 /* --color-warning */;
    font-size: 11px;
}

#model_groupbox[section="llm"]::title     { color: #60a5fa /* --color-info */; }
#model_groupbox[section="vox"]::title     { color: #a78bfa /* --luosiding-violet-400 */; }
#model_groupbox[section="whisper"]::title { color: #34d399 /* --color-success */; }
#model_groupbox[section="ocr"]::title     { color: #fbbf24 /* --color-warning */; }

#comfyui_local_status {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   AI 重命名 / 视频播放器 对话框
   ═══════════════════════════════════════════════════════════════ */

#aiRenameTable {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#aiRenameLogPanel,
#aiRenameLogTitle {
    background-color: #0b0c10 /* --background */;
    border: 1px solid #1e212b /* --surface-container */;
    border-radius: 8px /* --radius-md */;
}

#aiRenameModelInfo {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 12px;
}

#aiRenameDesc {
    color: #c3c6d2 /* --muted-foreground */;
    font-size: 12px;
}

#videoPlayerDialog {
    background-color: #151722 /* --surface */;
}

#videoPlayerLeft,
#videoPlayerRight {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#videoPlayerInfoLabel,
#videoPlayerFileLabel {
    color: #f0f1f7 /* --foreground */;
    font-size: 13px;
    font-weight: 600;
}

#videoPlayerFrameStatus,
#videoPlayerTime,
#videoPlayerHint {
    color: #9ca1b1 /* --luosiding-slate-200 */;
    font-size: 12px;
}

#videoPlayerDivider {
    background-color: #2b3040 /* --border */;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   其他 / Misc
   ═══════════════════════════════════════════════════════════════ */

#batchReplaceDialog {
    background-color: #151722 /* --surface */;
}

#terminalPrompt {
    color: #34d399 /* --color-success */;
    font-family: 'Consolas', monospace;
}

#themeSplitter::handle {
    background-color: #1e212b /* --surface-container */;
}

#themeSeparator {
    background-color: #2b3040 /* --surface-container-high */;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   启动/关闭闪屏 · 激活对话框 / Splash & Activation
   ═══════════════════════════════════════════════════════════════ */

QWidget#startup_splash {
    background: transparent;
}

QFrame#splash_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

QFrame#splash_card QLabel {
    color: #f0f1f7 /* --foreground */;
    background: transparent;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#splash_title {
    font-size: 18px;
    color: #f0f1f7 /* --foreground */;
}

QLabel#splash_status {
    font-size: 13px;
    color: #a5b4fc /* --luosiding-indigo-200 */;
}

QDialog#close_splash {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

QDialog#close_splash QLabel {
    color: #f0f1f7 /* --foreground */;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#close_splash_title {
    font-size: 15px;
    color: #f0f1f7 /* --foreground */;
}

QLabel#close_splash_status {
    font-size: 12px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

QLabel#activation_title {
    font-size: 20px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

QLabel#activation_machine_id {
    color: #a5b4fc /* --luosiding-indigo-200 */;
    font-family: monospace;
    font-size: 12px;
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 6px /* --radius-sm */;
    padding: 6px 10px;
}

QPlainTextEdit#activation_code_edit {
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   帮助页卡片（关于）/ About
   ═══════════════════════════════════════════════════════════════ */

#brand_card,
#license_card,
#version_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

QLabel#about_app_title {
    font-size: 18px;
    font-weight: 700;
    color: #f0f1f7 /* --foreground */;
}

QLabel#about_dev_info {
    font-size: 13px;
    color: #c3c6d2 /* --muted-foreground */;
}

QLabel#about_contact {
    font-size: 13px;
    color: #f0f1f7 /* --foreground */;
}

QLabel#about_license_title {
    font-size: 13px;
    font-weight: 700;
    color: #34d399 /* --color-success */;
}

QLabel#about_version_title {
    font-size: 13px;
    font-weight: 700;
    color: #60a5fa /* --color-info */;
}

QLineEdit#about_machine_id {
    color: #60a5fa /* --color-info */;
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
    color: #c3c6d2 /* --muted-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   节拍视图（智能混剪）专用 / Beat View
   ═══════════════════════════════════════════════════════════════ */

#segment_card {
    background-color: #151722 /* --surface */;
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

QScrollArea#beat_cards_scroll {
    border: 1px solid #2b3040 /* --border */;
    border-radius: 10px /* --radius-lg */;
    background: #0b0c10 /* --background */;
}

QLabel#beat_time_label {
    background-color: #1e212b /* --surface-container */;
    color: #fbbf24 /* --color-warning */;
    font-family: Consolas, monospace;
    font-size: 9pt;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
}

QLabel#beat_clips_info {
    color: #34d399 /* --color-success */;
    font-weight: 700;
}

QLabel#beat_preview_title {
    color: #fbbf24 /* --color-warning */;
    font-weight: 700;
}

/* ═══════════════════════════════════════════════════════════════
   表格操作按钮 / 开发中占位 / Table Action & Dev Placeholder
   ═══════════════════════════════════════════════════════════════ */

QPushButton#table_action_button {
    border: none;
    background: transparent;
    padding: 1px 5px;
    font-size: 13px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    border-radius: 4px;
}

QPushButton#table_action_button:hover {
    color: #ffffff /* --primary-foreground */;
    background: rgba(255, 255, 255, 0.1);
}

QLabel#dev_icon {
    font-size: 48px;
}

QLabel#dev_title {
    font-size: 20px;
    font-weight: 700;
    color: #c3c6d2 /* --muted-foreground */;
}

QLabel#dev_subtitle {
    font-size: 14px;
    color: #73788c /* --luosiding-slate-300 */;
}

/* ═══════════════════════════════════════════════════════════════
   Badge / 标签徽章
   ═══════════════════════════════════════════════════════════════ */

QLabel#badge,
QLabel.badge {
    padding: 2px 8px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#badge.success,
QLabel.badge.success { background-color: #34d399 /* --color-success */; color: #ffffff; }
QLabel#badge.warning,
QLabel.badge.warning { background-color: #fbbf24 /* --color-warning */; color: #151722; }
QLabel#badge.error,
QLabel.badge.error { background-color: #f87171 /* --color-error */; color: #ffffff; }
QLabel#badge.info,
QLabel.badge.info { background-color: #60a5fa /* --color-info */; color: #ffffff; }
QLabel#badge.platform,
QLabel.badge.platform { background-color: #1e212b /* --surface-container */; color: #f0f1f7; border-radius: 8px; }
QLabel#badge.tag,
QLabel.badge.tag { background-color: #2b3040 /* --surface-container-high */; color: #c3c6d2; border-radius: 8px; }

/* ═══════════════════════════════════════════════════════════════
   Tab 按钮 / Tab Button
   ═══════════════════════════════════════════════════════════════ */

QPushButton#tab_button {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    padding: 10px 20px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QPushButton#tab_button:hover {
    background-color: rgba(99, 102, 241, 0.12) /* --interactive-hover */;
    color: #f0f1f7 /* --foreground */;
}

QPushButton#tab_button:checked,
QPushButton#tab_button[active="true"] {
    background-color: rgba(99, 102, 241, 0.1);
    color: #c7d2fe /* --luosiding-indigo-100 */;
    font-weight: 700;
    border-bottom: 2px solid #818cf8 /* --luosiding-indigo-300 */;
}
""".replace("__CHECK_ICON_URL__", _CHECK_ICON_URL).replace("__ARROW_DOWN_ICON_URL__", _ARROW_DOWN_ICON_URL)
