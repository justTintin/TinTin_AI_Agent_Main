# -*- coding: utf-8 -*-
"""
浅色主题 QSS · 螺丝钉-电商智能体矩阵 v3.0
设计系统：Luosiding Design Library
背景：--background #fff；主色：--primary #4f46e5；强调：--accent #8b5cf6
"""
import os as _os

from config.paths import BUNDLE_ICONS_DIR

_CHECK_LIGHT_ICON = _os.path.join(BUNDLE_ICONS_DIR, "check_light.svg")
_CHECK_LIGHT_URL = _CHECK_LIGHT_ICON.replace(_os.sep, '/')

_ARROW_DOWN_LIGHT_ICON = _os.path.join(BUNDLE_ICONS_DIR, "arrow_down_light.svg")
_ARROW_DOWN_LIGHT_URL = _ARROW_DOWN_LIGHT_ICON.replace(_os.sep, '/')

LIGHT_STYLE_SHEET = """
/* ═══════════════════════════════════════════════════════════════
   基础元素 / Base
   tokens: --background #fff, --foreground #151722
   ═══════════════════════════════════════════════════════════════ */

* {
    font-family: "Microsoft YaHei", "微软雅黑", "Noto Sans SC", "Segoe UI", sans-serif;
    outline: none;
}

QMainWindow, QWidget {
    background-color: #ffffff /* --background */;
}

QToolTip {
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
    border: 1px solid #9ca1b1 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 11px;
    font-size: 12px;
}

QLabel {
    color: #5f6475 /* --muted-foreground */;
    background: transparent;
}

QStatusBar {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #5f6475 /* --muted-foreground */;
    border-top: 1px solid #c3c6d2 /* --surface-container */;
}

QMenuBar {
    background-color: #ffffff /* --surface */;
    color: #5f6475 /* --muted-foreground */;
}

QMenuBar::item {
    padding: 5px 12px;
    border-radius: 6px /* --radius-sm */;
    background: transparent;
}

QMenuBar::item:selected {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #151722 /* --foreground */;
}

QMenu {
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
    border: 1px solid #c3c6d2 /* --surface-container */;
    border-radius: 10px /* --radius-lg */;
    padding: 6px;
}

QMenu::item {
    padding: 7px 26px 7px 12px;
    border-radius: 6px /* --radius-sm */;
    background: transparent;
}

QMenu::item:selected {
    background-color: rgba(99, 102, 241, 0.08) /* --interactive-hover */;
    color: #4f46e5 /* --primary */;
}

QMenu::separator {
    height: 1px;
    background: #c3c6d2 /* --surface-container */;
    margin: 6px 8px;
}

/* ═══════════════════════════════════════════════════════════════
   侧边栏 / Sidebar
   token: --color-sidebar --surface-container-low #f0f1f7
   ═══════════════════════════════════════════════════════════════ */

#sidebar {
    background-color: #f0f1f7 /* --surface-container-low */;
    border-right: 1px solid #c3c6d2 /* --surface-container */;
    min-width: 264px;
    max-width: 264px;
}

#sidebar_title {
    font-size: 21px;
    font-weight: 700;
    color: #151722 /* --foreground */;
    padding: 24px 22px 14px 22px;
    letter-spacing: 0.5px;
}

#sidebar QLabel#section_header,
#sidebar_section_header {
    font-size: 11px;
    font-weight: 700;
    color: #73788c /* --luosiding-slate-300 */;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    padding: 6px 14px 2px 14px;
}

#sidebar_footer {
    color: #9ca1b1 /* --luosiding-slate-200 */;
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
    background-color: #f0f1f7 /* --surface-container-low */;
    border-right: 1px solid #c3c6d2 /* --surface-container */;
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
    color: #5f6475 /* --muted-foreground */;
    border-radius: 8px /* --radius-md */;
    margin: 2px 8px;
}

QPushButton#nav_button:hover {
    background-color: rgba(99, 102, 241, 0.08) /* --interactive-hover */;
    color: #151722 /* --foreground */;
}

QPushButton#nav_button:pressed {
    background-color: rgba(99, 102, 241, 0.16) /* --interactive-press */;
}

QPushButton#nav_button[active="true"] {
    border-left: 3px solid #4f46e5 /* --primary */;
    background-color: rgba(99, 102, 241, 0.08);
    color: #4f46e5 /* --primary */;
    font-weight: 600;
    padding-left: 11px;
}

/* ═══════════════════════════════════════════════════════════════
   内容区 / 页面文字
   ═══════════════════════════════════════════════════════════════ */

#content_area {
    background-color: #ffffff /* --background */;
}

#section_label {
    font-size: 13px;
    font-weight: 700;
    color: #151722 /* --foreground */;
    letter-spacing: 0.3px;
}

#page_subtitle {
    color: #5f6475 /* --muted-foreground */;
    font-size: 13px;
}

#page_section_label {
    font-size: 13px;
    font-weight: 700;
    color: #151722 /* --foreground */;
    margin-top: 4px;
}

#heading {
    font-size: 16px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

#muted_text {
    color: #5f6475 /* --muted-foreground */;
    font-size: 12px;
}

#accent_text {
    color: #4f46e5 /* --primary */;
    font-size: 12px;
    font-weight: 600;
}

#success_text {
    color: #10b981 /* --color-success */;
    font-weight: 600;
}

/* ═══════════════════════════════════════════════════════════════
   卡片 / Card
   token: --color-card --surface #fff, --border #9ca1b1, --radius-xl 12px
   ═══════════════════════════════════════════════════════════════ */

#card {
    background-color: #ffffff /* --surface --color-card */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

#search_sidebar {
    background-color: #ffffff /* --surface --color-card */;
    border: 1px solid #c3c6d2 /* --border */;
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
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 6px /* --radius-sm */;
    color: #5f6475 /* --muted-foreground */;
    padding: 0;
    margin: 0;
}

#dreamina_file_list::item:selected {
    background-color: rgba(99, 102, 241, 0.16);
    border: 1px solid #6366f1 /* --primary */;
    color: #151722 /* --foreground */;
}

#dreamina_file_list::item:hover {
    background-color: #f0f1f7 /* --surface-container-high */;
}

#feature_card {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

#feature_card:hover {
    border: 1px solid #4f46e5 /* --primary */;
    background-color: #f0f1f7 /* --surface-dim */;
}

#feature_title {
    font-size: 15px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

#feature_desc {
    font-size: 12px;
    color: #5f6475 /* --muted-foreground */;
    line-height: 1.6;
}

#model_status_card {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#model_info_label {
    font-size: 13px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

#model_status_label {
    font-weight: 700;
    color: #5f6475 /* --muted-foreground */;
}

#model_status_label[state="green"] { color: #10b981 /* --color-success */; }
#model_status_label[state="red"] { color: #ef4444 /* --color-error */; }
#model_status_label[state="yellow"] { color: #f59e0b /* --color-warning */; }

#dim_score_card {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

#preview_panel {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#thumbnail_placeholder {
    border: 1px dashed #9ca1b1 /* --border */;
    border-radius: 8px /* --radius-md */;
    color: #73788c /* --luosiding-slate-300 */;
    background-color: #ffffff /* --background */;
}

/* ═══════════════════════════════════════════════════════════════
   输入控件 / Input
   tokens: --surface #fff, --border #9ca1b1, --radius-md 8px
   ═══════════════════════════════════════════════════════════════ */

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QDateEdit,
QTimeEdit,
QDateTimeEdit {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 8px 12px;
    font-size: 13px;
    color: #151722 /* --foreground */;
    selection-background-color: rgba(99, 102, 241, 0.25);
    selection-color: #ffffff /* --primary-foreground */;
}

QLineEdit:hover,
QTextEdit:hover,
QPlainTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QDateEdit:hover,
QTimeEdit:hover,
QDateTimeEdit:hover {
    border: 1px solid #9ca1b1 /* --surface-container-high */;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QDateEdit:focus,
QTimeEdit:focus,
QDateTimeEdit:focus {
    border: 1px solid #6366f1 /* --ring */;
    background-color: #f0f1f7 /* --surface-dim */;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #9ca1b1 /* --luosiding-slate-200 */;
    border: 1px solid #c3c6d2 /* --border */;
}

QLineEdit {
    placeholder-text-color: #9ca1b1 /* --luosiding-slate-200 */;
}

QTextEdit,
QPlainTextEdit {
    placeholder-text-color: #9ca1b1 /* --luosiding-slate-200 */;
}

/* ═══════════════════════════════════════════════════════════════
   下拉框 / ComboBox
   ═══════════════════════════════════════════════════════════════ */

QComboBox {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 6px 12px;
    font-size: 13px;
    color: #151722 /* --foreground */;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #6366f1 /* --ring */;
}

QComboBox:hover {
    border: 1px solid #9ca1b1 /* --surface-container-high */;
}

QComboBox:on {
    border: 1px solid #6366f1 /* --ring */;
    background-color: #f0f1f7 /* --surface-dim */;
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
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 4px;
    selection-background-color: #4f46e5 /* --primary */;
    selection-color: #ffffff /* --primary-foreground */;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 8px 12px;
    border-radius: 6px /* --radius-sm */;
    min-height: 20px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #f0f1f7 /* --surface-dim */;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #4f46e5 /* --primary */;
    color: #ffffff /* --primary-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   按钮 / Button
   tokens: .btn.primary #4f46e5, .secondary #c3c6d2, .ghost transparent
   ═══════════════════════════════════════════════════════════════ */

QPushButton {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 14px;
    color: #151722 /* --foreground */;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #9ca1b1 /* --surface-container-high */;
    color: #151722 /* --foreground */;
}

QPushButton:pressed {
    background-color: #c3c6d2 /* --surface-container */;
}

QPushButton:disabled {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

QPushButton#primary_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border: 1px solid rgba(79, 70, 229, 0.5);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1 /* --luosiding-indigo-400 */, stop:1 #a78bfa /* --luosiding-violet-400 */);
    color: #ffffff /* --primary-foreground */;
}

QPushButton#primary_button:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4338ca /* --luosiding-indigo-600 */, stop:1 #7c3aed /* --luosiding-violet-600 */);
}

QPushButton#primary_button:disabled {
    background-color: #c3c6d2 /* --surface-container */;
    border: 1px solid #9ca1b1 /* --surface-container-high */;
    color: #73788c /* --luosiding-slate-300 */;
}

QPushButton#secondary_button {
    background-color: transparent;
    border: 1px solid #c3c6d2 /* --border */;
    color: #5f6475 /* --muted-foreground */;
    font-weight: 500;
}

QPushButton#secondary_button:hover {
    background-color: rgba(99, 102, 241, 0.08) /* --interactive-hover */;
    border: 1px solid #9ca1b1 /* --surface-container-high */;
    color: #151722 /* --foreground */;
}

QPushButton#secondary_button[pressed="true"] {
    background-color: #f0f1f7 /* --surface-dim */;
}

QPushButton#action_button {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981 /* --luosiding-success-500 */, stop:1 #059669 /* --luosiding-success-600 */);
    border: 1px solid rgba(5, 150, 105, 0.5);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#action_button:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34d399 /* --luosiding-success-400 */, stop:1 #10b981 /* --luosiding-success-500 */);
    color: #ffffff /* --primary-foreground */;
}

QPushButton#action_button:disabled {
    background-color: #c3c6d2 /* --surface-container */;
    border: 1px solid #9ca1b1 /* --surface-container-high */;
    color: #73788c /* --luosiding-slate-300 */;
}

QPushButton#pill_button {
    background-color: transparent;
    border: 1px solid #c3c6d2 /* --border */;
    color: #5f6475 /* --muted-foreground */;
    padding: 6px 16px;
    border-radius: 18px;
    font-weight: 500;
}

QPushButton#pill_button:hover {
    background-color: rgba(99, 102, 241, 0.08) /* --interactive-hover */;
    border: 1px solid #9ca1b1 /* --surface-container-high */;
    color: #151722 /* --foreground */;
}

QPushButton#pill_button:checked {
    background-color: rgba(99, 102, 241, 0.12);
    border: 1px solid rgba(79, 70, 229, 0.4);
    color: #4f46e5 /* --primary */;
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
    background-color: #c3c6d2 /* --surface-container */;
    color: #73788c /* --luosiding-slate-300 */;
}

QPushButton#secondary_button[danger="true"] {
    color: #ef4444 /* --color-error */;
    border-color: rgba(239, 68, 68, 0.4);
    font-weight: 600;
}

QPushButton#secondary_button[danger="true"]:hover {
    background-color: rgba(239, 68, 68, 0.08);
    color: #dc2626 /* --luosiding-error-600 */;
    border-color: rgba(239, 68, 68, 0.55);
}

QPushButton#danger_button {
    background-color: #ef4444 /* --color-error */;
    border: 1px solid rgba(239, 68, 68, 0.5);
    color: #ffffff /* --primary-foreground */;
    font-weight: 600;
}

QPushButton#danger_button:hover {
    background-color: #f87171 /* --luosiding-error-400 */;
}

QPushButton#delete_btn,
QPushButton#close_btn {
    color: #ef4444 /* --color-error */;
}

QPushButton#delete_btn:hover,
QPushButton#close_btn:hover {
    background-color: rgba(239, 68, 68, 0.08);
    color: #dc2626 /* --luosiding-error-600 */;
}

/* ═══════════════════════════════════════════════════════════════
   复选框 / 单选按钮
   ═══════════════════════════════════════════════════════════════ */

QCheckBox, QRadioButton {
    color: #5f6475 /* --muted-foreground */;
    spacing: 8px;
    background: transparent;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #c3c6d2 /* --border */;
    border-radius: 5px;
    background-color: #ffffff /* --surface */;
}

QCheckBox::indicator:hover {
    border: 2px solid #4f46e5 /* --primary */;
}

QCheckBox::indicator:checked {
    background-color: rgba(99, 102, 241, 0.22);
    border: 2px solid #4f46e5 /* --primary */;
    image: url("__CHECK_LIGHT_URL__");
}

QCheckBox::indicator:disabled {
    border: 2px solid #c3c6d2 /* --border */;
    background-color: #f0f1f7 /* --surface-dim */;
}

QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 2px solid #c3c6d2 /* --border */;
    border-radius: 9px;
    background-color: #ffffff /* --surface */;
}

QRadioButton::indicator:hover {
    border: 2px solid #4f46e5 /* --primary */;
}

QRadioButton::indicator:checked {
    background-color: #4f46e5 /* --primary */;
    border: 2px solid #4f46e5 /* --primary */;
}

/* ═══════════════════════════════════════════════════════════════
   表格 / 列表 / Table & List
   ═══════════════════════════════════════════════════════════════ */

QTableWidget,
QTableView,
QListWidget {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 12px /* --radius-xl */;
    gridline-color: #f0f1f7 /* --surface-dim */;
    selection-background-color: rgba(99, 102, 241, 0.18);
    selection-color: #151722 /* --foreground */;
    alternate-background-color: #f0f1f7 /* --surface-dim */;
    color: #5f6475 /* --muted-foreground */;
    outline: none;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #5f6475 /* --muted-foreground */;
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
    color: #151722 /* --foreground */;
}

QListWidget::item:hover {
    background-color: rgba(0, 0, 0, 0.03);
    border-radius: 6px /* --radius-sm */;
}

QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #c3c6d2 /* --border */;
    border-radius: 4px;
    background-color: #ffffff /* --surface */;
}

QTableView::indicator:checked {
    background-color: rgba(99, 102, 241, 0.22);
    border: 2px solid #4f46e5 /* --primary */;
    image: url("__CHECK_LIGHT_URL__");
}

QHeaderView::section {
    background-color: #f0f1f7 /* --surface-dim */;
    padding: 10px 12px;
    border: none;
    border-bottom: 2px solid #c3c6d2 /* --border */;
    border-right: 1px solid #f0f1f7 /* --surface-dim */;
    font-weight: 700;
    font-size: 12px;
    color: #73788c /* --luosiding-slate-300 */;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTableCornerButton::section {
    background-color: #f0f1f7 /* --surface-dim */;
    border: none;
    border-bottom: 2px solid #c3c6d2 /* --border */;
}

#side_list {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

/* ═══════════════════════════════════════════════════════════════
   进度条 / ProgressBar
   ═══════════════════════════════════════════════════════════════ */

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #c3c6d2 /* --surface-container */;
    text-align: center;
    height: 6px;
    color: transparent;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border-radius: 4px;
}

/* ═══════════════════════════════════════════════════════════════
   日志查看器 / 日志输出框
   ═══════════════════════════════════════════════════════════════ */

QTextEdit#log_viewer {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #5f6475 /* --muted-foreground */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
    font-size: 12px;
    line-height: 1.6;
}

QTextEdit#log_box {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #151722 /* --foreground */;
    font-size: 12px;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #c3c6d2 /* --border */;
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
    background: #c3c6d2 /* --surface-container */;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #9ca1b1 /* --surface-container-high */;
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
    background: #c3c6d2 /* --surface-container */;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #9ca1b1 /* --surface-container-high */;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ═══════════════════════════════════════════════════════════════
   分组框 / Tab
   ═══════════════════════════════════════════════════════════════ */

QGroupBox {
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
    margin-top: 12px;
    padding-top: 16px;
    color: #5f6475 /* --muted-foreground */;
    font-weight: 600;
    background-color: rgba(255, 255, 255, 0.5);
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

QTabWidget::pane {
    border: 1px solid #c3c6d2 /* --border */;
    background-color: #ffffff /* --surface */;
    border-radius: 0 0 12px 12px;
}

QTabBar::tab {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #73788c /* --luosiding-slate-300 */;
    padding: 10px 20px;
    margin-right: 4px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: rgba(99, 102, 241, 0.08);
    color: #4f46e5 /* --primary */;
    font-weight: 700;
    border-bottom: 2px solid #4f46e5 /* --primary */;
}

QTabBar::tab:hover:!selected {
    color: #151722 /* --foreground */;
    background-color: #f0f1f7 /* --surface-dim */;
}

/* ═══════════════════════════════════════════════════════════════
   对话框 / 消息框
   ═══════════════════════════════════════════════════════════════ */

QDialog {
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
}

QMessageBox {
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
}

QDialog QLabel,
QMessageBox QLabel {
    color: #151722 /* --foreground */;
}

QDialog QPushButton,
QMessageBox QPushButton {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
    padding: 7px 18px;
    color: #151722 /* --foreground */;
    min-width: 84px;
    font-weight: 500;
}

QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #151722 /* --foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   滑块 / Slider
   ═══════════════════════════════════════════════════════════════ */

QSlider::groove:horizontal {
    height: 5px;
    background: #c3c6d2 /* --surface-container */;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: #4f46e5 /* --primary */;
    border: 2px solid #ffffff /* --surface */;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #6366f1 /* --luosiding-indigo-400 */;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5 /* --primary */, stop:1 #8b5cf6 /* --accent */);
    border-radius: 3px;
}

/* ═══════════════════════════════════════════════════════════════
   分割线 / 分隔条
   ═══════════════════════════════════════════════════════════════ */

#separator {
    color: #c3c6d2 /* --surface-container */;
    background-color: #c3c6d2 /* --surface-container */;
}

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #c3c6d2 /* --surface-container */;
}

QSplitter::handle {
    background-color: #c3c6d2 /* --surface-container */;
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
    background-color: rgba(255, 255, 255, 0.94);
    border: 1px solid rgba(0, 0, 0, 0.09);
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
    color: #5f6475 /* --muted-foreground */;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#status_overlay QLabel#ov_icon {
    font-size: 13px;
}

#status_overlay QLabel#ov_name {
    color: #73788c /* --luosiding-slate-300 */;
    font-weight: 500;
}

#status_overlay QLabel#ov_value {
    color: #151722 /* --foreground */;
    font-weight: 700;
}

#status_overlay QLabel#ov_value[level="ok"] {
    color: #10b981 /* --color-success */;
}

#status_overlay QLabel#ov_value[level="warn"] {
    color: #f59e0b /* --color-warning */;
}

#status_overlay QLabel#ov_value[level="bad"] {
    color: #ef4444 /* --color-error */;
}

#status_overlay QLabel#ov_value[level="idle"] {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#status_overlay QLabel#ov_service {
    color: #5f6475 /* --muted-foreground */;
    font-weight: 500;
}

#status_overlay QLabel#ov_service[state="ok"] {
    color: #10b981 /* --color-success */;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="bad"] {
    color: #ef4444 /* --color-error */;
    font-weight: 600;
}

#status_overlay QLabel#ov_service[state="unknown"] {
    color: #9ca1b1 /* --luosiding-slate-200 */;
}

#status_separator {
    background-color: rgba(0, 0, 0, 0.12);
    border: none;
}

/* ═══════════════════════════════════════════════════════════════
   状态标签 / Status Labels
   ═══════════════════════════════════════════════════════════════ */

#login_status_label {
    font-size: 16px;
    font-weight: 700;
}

#login_status_label[state="green"] { color: #10b981 /* --color-success */; }
#login_status_label[state="red"] { color: #ef4444 /* --color-error */; }
#login_status_label[state="yellow"] { color: #f59e0b /* --color-warning */; }

#llm_status_label {
    font-weight: 700;
}

#llm_status_label[state="green"] { color: #10b981 /* --color-success */; }
#llm_status_label[state="red"] { color: #ef4444 /* --color-error */; }
#llm_status_label[state="yellow"] { color: #f59e0b /* --color-warning */; }

#ollama_status_lbl {
    font-size: 12px;
}

#ollama_status_lbl[state="green"] { color: #10b981 /* --color-success */; }
#ollama_status_lbl[state="red"] { color: #ef4444 /* --color-error */; }
#ollama_status_lbl[state="yellow"] { color: #f59e0b /* --color-warning */; }
#ollama_status_lbl[state="gray"] { color: #73788c /* --luosiding-slate-300 */; }

/* ═══════════════════════════════════════════════════════════════
   素材管理 / NAS
   ═══════════════════════════════════════════════════════════════ */

#step_bar {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#step_label {
    color: #73788c /* --luosiding-slate-300 */;
    padding: 4px 0;
    font-size: 13px;
}

#step_label[status="active"] {
    color: #3b82f6 /* --color-info */;
    font-weight: 700;
    background-color: rgba(59, 130, 246, 0.1);
    border-radius: 6px /* --radius-sm */;
    padding: 4px 8px;
}

#step_label[status="done"] {
    color: #10b981 /* --color-success */;
    background-color: rgba(16, 185, 129, 0.08);
    border-radius: 6px /* --radius-sm */;
    padding: 4px 8px;
}

#step_label[status="pending"] {
    color: #73788c /* --luosiding-slate-300 */;
}

#nas_root_label {
    font-size: 13px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

#stats_analyze, #stats_ingest {
    font-size: 13px;
    color: #151722 /* --foreground */;
}

#btn_refresh_stats {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 6px /* --radius-sm */;
    color: #151722 /* --foreground */;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_refresh_stats:hover {
    background-color: #c3c6d2 /* --surface-container */;
    color: #151722 /* --foreground */;
}

#btn_align {
    background-color: #dbeafe /* --luosiding-info-100 */;
    border: 1px solid #bfdbfe /* --luosiding-info-200 */;
    border-radius: 6px /* --radius-sm */;
    color: #1e40af /* --luosiding-info-800 */;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

#btn_align:hover {
    background-color: #bfdbfe /* --luosiding-info-200 */;
    color: #1e3a8a /* --luosiding-info-900 */;
}

/* ═══════════════════════════════════════════════════════════════
   live_clip_page 专用样式
   ═══════════════════════════════════════════════════════════════ */

#cover_edit_dialog {
    background-color: #ffffff /* --surface */;
    color: #151722 /* --foreground */;
}

#cover_section_title {
    font-size: 13px;
    color: #73788c /* --luosiding-slate-300 */;
}

#cover_video_widget {
    background-color: #000000;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #c3c6d2 /* --border */;
}

#cover_time_label {
    color: #73788c /* --luosiding-slate-300 */;
}

#cover_preview_h,
#cover_preview_v {
    background-color: #f0f1f7 /* --surface-dim */;
    border-radius: 8px /* --radius-md */;
    border: 1px solid #c3c6d2 /* --border */;
}

#clip_list_item_title {
    font-size: 13px;
    color: #151722 /* --foreground */;
}

#clip_list_item_score {
    color: #f59e0b /* --color-warning */;
    font-weight: 700;
}

#clip_list_item_meta {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 11px;
}

#clip_list_separator {
    background-color: #c3c6d2 /* --border */;
    max-height: 1px;
}

#clip_list_item_time {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 11px;
}

#export_step_label {
    padding: 6px 12px;
}

#export_step_label[status="active"] {
    color: #3b82f6 /* --color-info */;
    font-weight: 700;
    background-color: rgba(59, 130, 246, 0.1);
    border-radius: 6px /* --radius-sm */;
}

#export_step_label[status="done"] {
    color: #10b981 /* --color-success */;
    background-color: rgba(16, 185, 129, 0.08);
    border-radius: 6px /* --radius-sm */;
}

#export_step_label[status="pending"] {
    color: #73788c /* --luosiding-slate-300 */;
}

#clip_page_title {
    font-size: 14px;
    color: #151722 /* --foreground */;
}

#clip_status_label {
    color: #73788c /* --luosiding-slate-300 */;
}

#export_result_label {
    color: #10b981 /* --color-success */;
    font-weight: 700;
}

#video_info_label {
    color: #3b82f6 /* --color-info */;
}

/* ═══════════════════════════════════════════════════════════════
   模型配置 Ollama
   ═══════════════════════════════════════════════════════════════ */

#model_groupbox {
    font-size: 13px;
    font-weight: 700;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
    margin-top: 12px;
    background-color: rgba(255, 255, 255, 0.5);
}

#model_groupbox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
}

#ollama_models_lbl {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 11px;
}

#ollama_runners_warn {
    color: #ef4444 /* --color-error */;
    font-size: 12px;
}

#ollama_progress_lbl {
    color: #f59e0b /* --color-warning */;
    font-size: 11px;
}

#model_groupbox[section="llm"]::title     { color: #3b82f6 /* --color-info */; }
#model_groupbox[section="vox"]::title     { color: #7c3aed /* --luosiding-violet-600 */; }
#model_groupbox[section="whisper"]::title { color: #10b981 /* --color-success */; }
#model_groupbox[section="ocr"]::title     { color: #f59e0b /* --color-warning */; }

#comfyui_local_status {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 12px;
}

/* ═══════════════════════════════════════════════════════════════
   AI 重命名 / 视频播放器 对话框
   ═══════════════════════════════════════════════════════════════ */

#aiRenameTable {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#aiRenameLogPanel,
#aiRenameLogTitle {
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 8px /* --radius-md */;
}

#aiRenameModelInfo {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 12px;
}

#aiRenameDesc {
    color: #5f6475 /* --muted-foreground */;
    font-size: 12px;
}

#videoPlayerDialog {
    background-color: #ffffff /* --surface */;
}

#videoPlayerLeft,
#videoPlayerRight {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

#videoPlayerInfoLabel,
#videoPlayerFileLabel {
    color: #151722 /* --foreground */;
    font-size: 13px;
    font-weight: 600;
}

#videoPlayerFrameStatus,
#videoPlayerTime,
#videoPlayerHint {
    color: #73788c /* --luosiding-slate-300 */;
    font-size: 12px;
}

#videoPlayerDivider {
    background-color: #c3c6d2 /* --border */;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   其他 / Misc
   ═══════════════════════════════════════════════════════════════ */

#batchReplaceDialog {
    background-color: #ffffff /* --surface */;
}

#terminalPrompt {
    color: #10b981 /* --color-success */;
    font-family: 'Consolas', monospace;
}

#themeSplitter::handle {
    background-color: #c3c6d2 /* --surface-container */;
}

#themeSeparator {
    background-color: #c3c6d2 /* --surface-container */;
    max-height: 1px;
}

/* ═══════════════════════════════════════════════════════════════
   启动/关闭闪屏 · 激活对话框 / Splash & Activation
   ═══════════════════════════════════════════════════════════════ */

QWidget#startup_splash {
    background: transparent;
}

QFrame#splash_card {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

QFrame#splash_card QLabel {
    color: #151722 /* --foreground */;
    background: transparent;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#splash_title {
    font-size: 18px;
    color: #151722 /* --foreground */;
}

QLabel#splash_status {
    font-size: 13px;
    color: #4f46e5 /* --primary */;
}

QDialog#close_splash {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 14px /* --radius-2xl */;
}

QDialog#close_splash QLabel {
    color: #151722 /* --foreground */;
    font-family: "Microsoft YaHei", "微软雅黑";
}

QLabel#close_splash_title {
    font-size: 15px;
    color: #151722 /* --foreground */;
}

QLabel#close_splash_status {
    font-size: 12px;
    color: #73788c /* --luosiding-slate-300 */;
}

QLabel#activation_title {
    font-size: 20px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

QLabel#activation_machine_id {
    color: #4f46e5 /* --primary */;
    font-family: monospace;
    font-size: 12px;
    background-color: #f0f1f7 /* --surface-dim */;
    border: 1px solid #c3c6d2 /* --border */;
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
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 12px /* --radius-xl */;
}

QLabel#about_app_title {
    font-size: 18px;
    font-weight: 700;
    color: #151722 /* --foreground */;
}

QLabel#about_dev_info {
    font-size: 13px;
    color: #5f6475 /* --muted-foreground */;
}

QLabel#about_contact {
    font-size: 13px;
    color: #151722 /* --foreground */;
}

QLabel#about_license_title {
    font-size: 13px;
    font-weight: 700;
    color: #10b981 /* --color-success */;
}

QLabel#about_version_title {
    font-size: 13px;
    font-weight: 700;
    color: #3b82f6 /* --color-info */;
}

QLineEdit#about_machine_id {
    color: #3b82f6 /* --color-info */;
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
    color: #5f6475 /* --muted-foreground */;
}

/* ═══════════════════════════════════════════════════════════════
   节拍视图（智能混剪）专用 / Beat View
   ═══════════════════════════════════════════════════════════════ */

#segment_card {
    background-color: #ffffff /* --surface */;
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
}

QScrollArea#beat_cards_scroll {
    border: 1px solid #c3c6d2 /* --border */;
    border-radius: 10px /* --radius-lg */;
    background: #f0f1f7 /* --surface-dim */;
}

QLabel#beat_time_label {
    background-color: #f0f1f7 /* --surface-dim */;
    color: #f59e0b /* --color-warning */;
    font-family: Consolas, monospace;
    font-size: 9pt;
    font-weight: 700;
    border-radius: 3px;
    padding: 2px 6px;
}

QLabel#beat_clips_info {
    color: #10b981 /* --color-success */;
    font-weight: 700;
}

QLabel#beat_preview_title {
    color: #f59e0b /* --color-warning */;
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
    color: #73788c /* --luosiding-slate-300 */;
    border-radius: 4px;
}

QPushButton#table_action_button:hover {
    color: #151722 /* --foreground */;
    background: rgba(0, 0, 0, 0.07);
}

QLabel#dev_icon {
    font-size: 48px;
}

QLabel#dev_title {
    font-size: 20px;
    font-weight: 700;
    color: #5f6475 /* --muted-foreground */;
}

QLabel#dev_subtitle {
    font-size: 14px;
    color: #9ca1b1 /* --luosiding-slate-200 */;
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
QLabel.badge.success { background-color: #10b981 /* --color-success */; color: #ffffff; }
QLabel#badge.warning,
QLabel.badge.warning { background-color: #f59e0b /* --color-warning */; color: #151722; }
QLabel#badge.error,
QLabel.badge.error { background-color: #ef4444 /* --color-error */; color: #ffffff; }
QLabel#badge.info,
QLabel.badge.info { background-color: #3b82f6 /* --color-info */; color: #ffffff; }
QLabel#badge.platform,
QLabel.badge.platform { background-color: #f0f1f7 /* --surface-dim */; color: #151722; border-radius: 8px; }
QLabel#badge.tag,
QLabel.badge.tag { background-color: #c3c6d2 /* --surface-container */; color: #151722; border-radius: 8px; }

/* ═══════════════════════════════════════════════════════════════
   Tab 按钮 / Tab Button
   ═══════════════════════════════════════════════════════════════ */

QPushButton#tab_button {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #73788c /* --luosiding-slate-300 */;
    padding: 10px 20px;
    border-radius: 8px 8px 0 0;
    font-weight: 500;
}

QPushButton#tab_button:hover {
    background-color: rgba(99, 102, 241, 0.08) /* --interactive-hover */;
    color: #151722 /* --foreground */;
}

QPushButton#tab_button:checked,
QPushButton#tab_button[active="true"] {
    background-color: rgba(99, 102, 241, 0.08);
    color: #4f46e5 /* --primary */;
    font-weight: 700;
    border-bottom: 2px solid #4f46e5 /* --primary */;
}
""".replace("__CHECK_LIGHT_URL__", _CHECK_LIGHT_URL).replace("__ARROW_DOWN_LIGHT_URL__", _ARROW_DOWN_LIGHT_URL)
