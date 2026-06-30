# -*- coding: utf-8 -*-

STYLE_SHEET = """
* {
    font-family: "Microsoft YaHei", "微软雅黑", "Microsoft YaHei UI", sans-serif;
}

QToolTip {
    background-color: #2c2c2e;
    color: #ffffff;
    border: 1px solid #3b82f6;
    border-radius: 4px;
    padding: 4px;
    font-size: 12px;
}

QMainWindow {
    background-color: #1a1a1c;
}

#content_area {
    background-color: #1a1a1c;
}

#sidebar {
    background-color: #111112;
    border-right: 1px solid #252528;
    min-width: 260px;
    max-width: 260px;
}

#sidebar_title {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
    padding: 22px 20px 16px 20px;
}

#sidebar_section_header {
    font-size: 13px;
    font-weight: 700;
    color: #e5e7eb;
    background-color: rgba(59, 130, 246, 0.12);
    border-radius: 6px;
    padding: 8px 16px;
    margin: 12px 12px 4px 12px;
}

QLabel {
    color: #e5e7eb;
}

QLabel#sidebar_footer {
    color: #636366;
    padding: 18px 20px;
    font-size: 11px;
}

QPushButton#nav_button {
    text-align: left;
    padding: 10px 14px;
    border: 1px solid transparent;
    background-color: transparent;
    font-size: 14px;
    font-weight: bold;
    color: #d1d5db;
    border-radius: 10px;
    margin: 4px 10px;
}

QPushButton#nav_button:hover {
    background-color: #242426;
    color: #ffffff;
}

QPushButton#nav_button[active="true"] {
    background-color: rgba(59, 130, 246, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.3);
    color: #3b82f6;
    font-weight: bold;
}

#card {
    background-color: #222224;
    border-radius: 12px;
    border: 1px solid #2e2e32;
}

QLabel#heading {
    font-size: 14px;
    font-weight: 700;
    color: #ffffff;
    margin: 0px;
    padding: 0px;
}

QLabel#card_title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#muted_text {
    color: #8e8e93;
    font-size: 11px;
}

QLabel#accent_text {
    color: #3b82f6;
    font-size: 12px;
    font-weight: 700;
}

QLabel#success_text {
    color: #10b981;
    font-weight: 700;
}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QDateEdit,
QTimeEdit,
QDateTimeEdit,
QComboBox {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    color: #ffffff;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QDateEdit:focus,
QTimeEdit:focus,
QDateTimeEdit:focus,
QComboBox:focus {
    border: 1px solid #3b82f6;
}

QComboBox QAbstractItemView {
    background-color: #222224;
    color: #ffffff;
    border: 1px solid #3a3a3c;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item {
    background-color: #222224;
    color: #ffffff;
    padding: 6px 10px;
}

QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background-color: #3b82f6;
    color: #ffffff;
}

/* Target QListView used as QComboBox dropdown on some platforms */
QComboBox QListView {
    background-color: #222224;
    color: #ffffff;
    border: 1px solid #3a3a3c;
}

QComboBox QListView::item {
    background-color: #222224;
    color: #ffffff;
    padding: 6px 10px;
}

QComboBox QListView::item:hover,
QComboBox QListView::item:selected {
    background-color: #3b82f6;
    color: #ffffff;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox::down-arrow {
    width: 0px;
    height: 0px;
}

QPushButton {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 8px 12px;
    color: #ffffff;
}

QPushButton:hover {
    background-color: #3a3a3c;
}

QPushButton:pressed {
    background-color: #48484a;
}

QPushButton:disabled {
    background-color: #1c1c1e;
    color: #48484a;
    border: 1px solid #2c2c2e;
}

QPushButton#primary_button {
    background-color: #3b82f6;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 700;
}

QPushButton#primary_button:hover {
    background-color: #2563eb;
    border: 1px solid #2563eb;
}

QPushButton#secondary_button {
    background-color: #222224;
    border: 1px solid #3a3a3c;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#secondary_button:hover {
    background-color: #2c2c2e;
}

QPushButton#action_button {
    background-color: #10b981;
    border: 1px solid #10b981;
    color: #ffffff;
    font-weight: 700;
}

QPushButton#action_button:hover {
    background-color: #059669;
    border: 1px solid #059669;
}

QPushButton#pill_button {
    background-color: #222224;
    border: 1px solid #3a3a3c;
    color: #ffffff;
    padding: 6px 12px;
    border-radius: 999px;
    font-weight: 600;
}

QPushButton#pill_button:hover {
    background-color: #2c2c2e;
}

QPushButton#pill_button:checked {
    background-color: rgba(59, 130, 246, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.3);
    color: #3b82f6;
    font-weight: 700;
}

QPushButton#floating_action_button {
    background-color: #10b981;
    border: 2px solid #222224;
    color: #ffffff;
    font-weight: 800;
    border-radius: 18px;
    padding: 8px 14px;
    margin: 10px;
}

QPushButton#floating_action_button:hover {
    background-color: #059669;
}

QPushButton#floating_action_button:disabled {
    background-color: #48484a;
    border: 2px solid #3a3a3c;
    color: #8e8e93;
}

QCheckBox {
    color: #ffffff;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

QTableView::item {
    padding: 6px 8px;
    color: #ffffff;
}

#feature_card {
    background-color: #222224;
    border-radius: 14px;
    border: 1px solid #2e2e32;
}

#feature_card:hover {
    border: 1px solid rgba(59, 130, 246, 0.4);
    background-color: #26262a;
}

#feature_title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
}

#feature_desc {
    font-size: 12px;
    color: #8e8e93;
}

QTableWidget,
QTableView,
QListWidget {
    background-color: #222224;
    border: 1px solid #2e2e32;
    border-radius: 10px;
    gridline-color: #2e2e32;
    selection-background-color: rgba(59, 130, 246, 0.2);
    selection-color: #ffffff;
    alternate-background-color: #1c1c1e;
    color: #ffffff;
}

QTableWidget::viewport,
QTableView::viewport,
QListWidget::viewport {
    background-color: #222224;
}

QTableWidget::item,
QTableView::item,
QListWidget::item {
    color: #ffffff;
}

QHeaderView::section {
    background-color: #1c1c1e;
    padding: 10px 10px;
    border: none;
    border-bottom: 1px solid #2e2e32;
    font-weight: 700;
    color: #ffffff;
}

QTableCornerButton::section {
    background-color: #1c1c1e;
    border: none;
    border-bottom: 1px solid #2e2e32;
}

QProgressBar {
    border: 1px solid #2e2e32;
    border-radius: 8px;
    background-color: #1c1c1e;
    text-align: center;
    height: 14px;
    color: #ffffff;
}

QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 8px;
}

QTextEdit#log_viewer {
    background-color: #0b1220;
    color: #e5e7eb;
    border: 1px solid #111827;
    border-radius: 10px;
    padding: 10px;
    font-family: Consolas, Monaco, monospace;
    font-size: 12px;
}

QScrollBar:vertical {
    width: 10px;
    background: transparent;
    margin: 4px 2px 4px 2px;
}

QScrollBar::handle:vertical {
    background: #48484a;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #636366;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    height: 10px;
    background: transparent;
    margin: 2px 4px 2px 4px;
}

QScrollBar::handle:horizontal {
    background: #48484a;
    border-radius: 5px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: #636366;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

QGroupBox {
    border: 1px solid #2e2e32;
    border-radius: 8px;
    margin-top: 1.5ex;
    color: #ffffff;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #ffffff;
}

QTabWidget::pane {
    border: 1px solid #2e2e32;
    background-color: #222224;
}

QTabBar::tab {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    color: #d1d5db;
    padding: 8px 12px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #222224;
    border-bottom-color: #222224;
    color: #ffffff;
    font-weight: bold;
}

QDialog, QMessageBox {
    background-color: #1a1a1c;
    color: #ffffff;
}

QDialog QLabel, QMessageBox QLabel {
    color: #ffffff;
}

QDialog QPushButton, QMessageBox QPushButton {
    background-color: #2c2c2e;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 6px 16px;
    color: #ffffff;
    min-width: 80px;
}

QDialog QPushButton:hover, QMessageBox QPushButton:hover {
    background-color: #3a3a3c;
}

/* Sidebar section cards */
QFrame[section_type="douyin"] {
    background-color: #151517;
    border: 1px solid #202022;
    border-radius: 10px;
}

QFrame[section_type="resource"] {
    background-color: #151517;
    border: 1px solid #202022;
    border-radius: 10px;
}

QFrame[section_type="account"] {
    background-color: #16151a;
    border: 1px solid #231f2b;
    border-radius: 10px;
}

QFrame[section_type="ai"] {
    background-color: #131514;
    border: 1px solid #1c2420;
    border-radius: 10px;
}

QFrame[section_type="system"] {
    background-color: #171513;
    border: 1px solid #251f1c;
    border-radius: 10px;
}

/* Sidebar section header inside cards */
QLabel#section_header {
    font-size: 11px;
    font-weight: 800;
    color: #7c7c82;
    background-color: transparent;
    padding: 6px 14px 2px 14px;
    margin: 0px;
    text-transform: uppercase;
}

/* Navigation buttons spacing inside cards */
QFrame QPushButton#nav_button {
    margin: 2px 4px;
}
"""
