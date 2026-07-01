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
    padding: 8px 12px;
    font-size: 13px;
    color: #1d1d1f;
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
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 8px 16px;
    color: #1d1d1f;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f5f5f7;
    border: 1px solid #b0b0b8;
}

QPushButton:pressed { background-color: #e5e5ea; }
QPushButton:disabled {
    background-color: #f5f5f7;
    color: #aeaeb2;
    border: 1px solid #e5e5ea;
}

QPushButton#primary_button {
    background-color: #6366f1;
    border: 1px solid #6366f1;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#primary_button:hover {
    background-color: #4f46e5;
}

QPushButton#secondary_button {
    background-color: #f5f5f7;
    border: 1px solid #d2d2d7;
}

QPushButton#secondary_button:hover {
    background-color: #e8e8ed;
}

QPushButton#action_button {
    background-color: #10b981;
    border: 1px solid #10b981;
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
    background-color: #6366f1;
    border: 2px solid #6366f1;
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

QTableWidget::item { color: #3a3a3f; padding: 6px 10px; }

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
    background-color: #f5f5f7;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 8px 20px;
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
"""
