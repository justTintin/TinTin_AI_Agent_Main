import json
import os
import time
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from utils.logger_utils import log

_webview_started = False

def open_cef_browser(url, title="RunningHub AI 应用浏览器"):
    global _webview_started
    try:
        import webview
        if not _webview_started:
            webview.create_window(title, url, width=1100, height=800)
            webview.start(gui='cef', threaded=True)
            _webview_started = True
        else:
            log.warning("CEF browser already started, falling back to system browser")
            webbrowser.open(url)
    except Exception as e:  # 外部API调用（CEF 浏览器启动）
        log.error(f"Failed to open CEF browser: {e}")
        webbrowser.open(url)


class LoginDialog(QDialog):
    login_successful = Signal(dict) # Returns account info

    def __init__(self, playwright_profile_path, browsers_path, parent=None):
        super().__init__(parent)
        self.playwright_profile_path = playwright_profile_path
        self.browsers_path = browsers_path
        self.profile_id = "staging_new_account"

        self.setWindowTitle("添加抖音账户分身")
        self.resize(500, 300)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(15)

        # Instructions
        self.info_label = QLabel(
            " 已经为您在外部打开了一个独立的 Chromium 浏览器 (CEF) 窗口。\n\n"
            "1. 请在弹出的浏览器窗口中扫码或短信登录您的抖音账号。\n"
            "2. 登录成功后，返回此界面，点击下方的「完成并同步账户」按钮。\n\n"
            "提示：如果浏览器窗口被关闭，可以点击下方按钮重新打开。"
        )
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        self.layout.addWidget(self.info_label)

        # Buttons
        btn_layout = QHBoxLayout()

        self.btn_reopen = QPushButton(" 重新打开浏览器")
        self.btn_reopen.clicked.connect(self.start_login_browser)
        btn_layout.addWidget(self.btn_reopen)

        self.btn_save = QPushButton(" 完成并同步账户")
        self.btn_save.setObjectName("primary_button")
        self.btn_save.clicked.connect(self.save_and_sync)
        btn_layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton(" 取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.layout.addLayout(btn_layout)

        self.controller = None
        self.start_login_browser()

    def start_login_browser(self):
        if self.controller and self.controller.is_running():
            self.controller.goto("https://www.douyin.com")
            return

        user_data_dir = os.path.join(self.playwright_profile_path, "accounts", self.profile_id)  # noqa: E501
        os.makedirs(user_data_dir, exist_ok=True)

        from core.creator_browser_controller import CreatorBrowserController
        self.controller = CreatorBrowserController(
            user_data_dir=user_data_dir,
            browsers_path=self.browsers_path,
            headless=False
        )
        self.controller.start()
        QTimer.singleShot(500, lambda: self.controller.goto("https://www.douyin.com"))

    def save_and_sync(self):
        if not self.controller or not self.controller.is_running():
            QMessageBox.warning(self, "错误", "登录浏览器未运行或已关闭，请重新打开。")
            return

        js_code = """
        (function() {
            var info = { nick: "", uid: "" };
            try {
                var data = window._ROUTER_DATA || window._SSR_DATA ||
                JSON.parse(
                    document.getElementById('RENDER_DATA')?.innerText || '{}'
                );
                // Heuristic search for nick/uid
                function findInfo(obj) {
                    if (!obj || typeof obj !== 'object') return;
                    if (obj.nickname && !info.nick) info.nick = obj.nickname;
                    if (obj.sec_uid && !info.uid) info.uid = obj.sec_uid;
                    for (var k in obj) {
                        if (typeof obj[k] === 'object') findInfo(obj[k]);
                    }
                }
                findInfo(data);
            } catch(e) {}
            if (!info.nick) info.nick = document.title.split('的')[0];
            return JSON.stringify(info);
        })()
        """
        result = self.controller.evaluate(js_code)
        if not result:
            QMessageBox.warning(self, "同步失败", "未能从页面获取登录状态。请确认您在浏览器中已经成功登录抖音。")
            return

        try:
            data = json.loads(result)
            nickname = data.get('nick')
            uid = data.get('uid')

            # Fallback if page Router data is not fully loaded
            if not uid:
                cookies = self.controller.get_cookies()
                if not cookies or not any("douyin.com" in c.get("domain", "") for c in cookies):  # noqa: E501
                    QMessageBox.warning(self, "同步失败", "未能检测到有效的登录 Cookie，请先在浏览器中登录。")
                    return
                uid = f"id_{self.profile_id}_{int(time.time())}"

            if not nickname or nickname.startswith("未命名_"):
                nickname = "新账户"

            acc_info = {
                "uid": uid,
                "nickname": nickname,
                "profile_id": self.profile_id,
                "cookie": ""
            }
            self.controller.stop()
            self.login_successful.emit(acc_info)
            self.accept()
        except Exception as e:  # 外部API调用（登录结果解析）
            log.error(f"Error parsing login result: {e}")
            self.accept()

    def closeEvent(self, event):  # noqa: N802
        if self.controller:
            self.controller.stop()
        super().closeEvent(event)


class StartupSplash(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 260)

        # Center on screen
        qr = self.frameGeometry()
        cp = QApplication.primaryScreen().geometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

        layout = QVBoxLayout(self)
        self.card = QFrame()
        self.card.setObjectName("splash_card")
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(30, 35, 30, 35)
        self.card_layout.setSpacing(16)

        title_lbl = QLabel(" <b>螺丝钉-电商智能体矩阵</b>")
        title_lbl.setObjectName("splash_title")
        title_lbl.setAlignment(Qt.AlignCenter)
        self.card_layout.addWidget(title_lbl)

        self.status_lbl = QLabel("正在启动程序，准备系统核心中...")
        self.status_lbl.setObjectName("splash_status")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.card_layout.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(10)
        self.progress.setTextVisible(False)
        self.card_layout.addWidget(self.progress)

        layout.addWidget(self.card)


class CloseSplash(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)  # noqa: E501
        self.setObjectName("close_splash")
        self.setFixedSize(450, 180)

        if parent:
            qr = self.frameGeometry()
            cp = parent.geometry().center()
            qr.moveCenter(cp)
            self.move(qr.topLeft())
        else:
            qr = self.frameGeometry()
            cp = QApplication.primaryScreen().geometry().center()
            qr.moveCenter(cp)
            self.move(qr.topLeft())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 30, 20, 30)
        layout.setSpacing(16)

        title = QLabel(" <b>正在安全关闭系统，请稍候...</b>")
        title.setObjectName("close_splash_title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.status_lbl = QLabel("正在释放浏览器内核、清理后台服务与未完成任务...")
        self.status_lbl.setObjectName("close_splash_status")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)


class EditAccountDialog(QDialog):
    def __init__(self, nickname, douyin_id, remark, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑账户资料")
        self.resize(400, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # Nickname field
        row1 = QHBoxLayout()
        lbl_nickname = QLabel("账户名称:")
        lbl_nickname.setFixedWidth(80)
        from PySide6.QtWidgets import QLineEdit
        self.edit_nickname = QLineEdit()
        self.edit_nickname.setText(nickname)
        row1.addWidget(lbl_nickname)
        row1.addWidget(self.edit_nickname)
        layout.addLayout(row1)

        # Douyin ID field
        row2 = QHBoxLayout()
        lbl_douyin_id = QLabel("抖音号:")
        lbl_douyin_id.setFixedWidth(80)
        self.edit_douyin_id = QLineEdit()
        self.edit_douyin_id.setText(douyin_id)
        self.edit_douyin_id.setPlaceholderText("请输入抖音号")
        row2.addWidget(lbl_douyin_id)
        row2.addWidget(self.edit_douyin_id)
        layout.addLayout(row2)

        # Remark field
        row3 = QHBoxLayout()
        lbl_remark = QLabel("备注信息:")
        lbl_remark.setFixedWidth(80)
        self.edit_remark = QLineEdit()
        self.edit_remark.setText(remark)
        self.edit_remark.setPlaceholderText("可输入该账号的备注用途")
        row3.addWidget(lbl_remark)
        row3.addWidget(self.edit_remark)
        layout.addLayout(row3)

        layout.addSpacing(10)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("primary_button")
        self.btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def get_data(self):
        return {
            "nickname": self.edit_nickname.text().strip(),
            "douyin_id": self.edit_douyin_id.text().strip(),
            "remark": self.edit_remark.text().strip()
        }


class ActivationDialog(QDialog):
    """激活码输入对话框 —— 用户手动输入激活码（签发的License JSON）"""

    def __init__(self, machine_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("激活 - 电商智能体矩阵")
        self.setFixedSize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        # 标题区域
        title = QLabel(" 软件激活")
        title.setObjectName("activation_title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel("该设备尚未激活，请输入开发人员提供的激活码。")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 13px; color: #9e9ea6;")
        layout.addWidget(desc)

        # 机器码显示（可选中复制 + 一键复制按钮）
        mid_row = QHBoxLayout()
        mid_row.addWidget(QLabel("机器码:"))
        self.mid_lbl = QLabel(machine_id)
        self.mid_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.mid_lbl.setCursor(Qt.IBeamCursor)
        self.mid_lbl.setObjectName("activation_machine_id")
        self.mid_lbl.setToolTip("可拖动选中后 Ctrl+C 复制，或点右侧按钮")
        mid_row.addWidget(self.mid_lbl, 1)
        btn_copy_mid = QPushButton(" 复制")
        btn_copy_mid.setObjectName("secondary_button")
        btn_copy_mid.setCursor(Qt.PointingHandCursor)
        btn_copy_mid.setToolTip("复制机器码到剪贴板")
        btn_copy_mid.clicked.connect(lambda: self._copy_to_clipboard(machine_id, btn_copy_mid))  # noqa: E501
        mid_row.addWidget(btn_copy_mid)
        layout.addLayout(mid_row)

        # 激活码输入
        layout.addWidget(QLabel("激活码:"))
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText(
            "请将开发人员提供的激活码（JSON）粘贴到这里..."
        )
        self.code_edit.setMinimumHeight(80)
        self.code_edit.setObjectName("activation_code_edit")
        layout.addWidget(self.code_edit)

        # 状态提示
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_activate = QPushButton("完成： 激活")
        btn_activate.setObjectName("primary_button")
        btn_activate.clicked.connect(self._do_activate)
        btn_row.addWidget(btn_activate)
        btn_exit = QPushButton("退出")
        btn_exit.setObjectName("secondary_button")
        btn_exit.clicked.connect(self.reject)
        btn_row.addWidget(btn_exit)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._activated = False

    def _copy_to_clipboard(self, text: str, btn: QPushButton):
        """复制文本到剪贴板，并在按钮上短暂提示「已复制」。"""
        QApplication.clipboard().setText(text)
        orig = btn.text()
        btn.setText(" 已复制")
        btn.setEnabled(False)
        QTimer.singleShot(1200, lambda: (btn.setText(orig), btn.setEnabled(True)))

    def _do_activate(self):
        from utils.license import save_activation_cache, verify_activation_code
        code = self.code_edit.toPlainText().strip()
        if not code:
            self.status_label.setText("注意： 请输入激活码")
            self.status_label.setStyleSheet("color: #f87171; font-size: 13px;")
            return
        info = verify_activation_code(code)
        if info is None:
            self.status_label.setText("失败： 激活码无效，请检查后重试")
            self.status_label.setStyleSheet("color: #f87171; font-size: 13px;")
            return
        # 激活成功
        save_activation_cache(info)
        self._activated = True
        self.accept()

    def is_activated(self) -> bool:
        return self._activated
