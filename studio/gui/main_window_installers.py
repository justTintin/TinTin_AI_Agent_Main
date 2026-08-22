# type: ignore
"""MainWindow 的安装器 mixin（Playwright / PaddleOCR 修复），从 gui_main 拆出。"""

import os
import sys
import zipfile

from config.paths import BUNDLED_PW_BROWSERS_ZIP, PW_BROWSERS_DIR
from PySide6.QtWidgets import QMessageBox
from utils.ffmpeg_utils import run


class InstallersMixin:
    def is_playwright_chromium_present(self):
        if not os.path.isdir(PW_BROWSERS_DIR):
            return False
        return any("chrome.exe" in files for _root, _dirs, files in os.walk(PW_BROWSERS_DIR))

    def ensure_playwright_chromium_ready(self):
        self._pw_ready = self.is_playwright_chromium_present()
        if self._pw_ready:
            return
        if not self._pw_install_running:
            self.install_playwright_chromium()

    def install_playwright_chromium(self):
        if self._pw_install_running:
            return
        self._pw_install_running = True
        if hasattr(self, "cg_install_btn"):
            self.cg_install_btn.setEnabled(False)
        if hasattr(self, "cg_status_label"):
            self.cg_status_label.setText("正在安装 Chromium 内核（首次可能较慢）...")

        def run_install():
            try:
                if os.path.exists(BUNDLED_PW_BROWSERS_ZIP):
                    os.makedirs(PW_BROWSERS_DIR, exist_ok=True)
                    with zipfile.ZipFile(BUNDLED_PW_BROWSERS_ZIP, "r") as zf:
                        zf.extractall(PW_BROWSERS_DIR)
                    return {"code": 0, "out": "unzipped"}
            except Exception as e:  # 文件解压涉及 I/O 多类异常
                return {"code": 2, "out": f"unzip_failed: {e}"}

            env = os.environ.copy()
            env["PLAYWRIGHT_BROWSERS_PATH"] = PW_BROWSERS_DIR
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            p = run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="ignore")  # noqa: E501
            return {"code": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}

        def on_done(res):
            code = res.get("code")
            out = res.get("out", "")
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if code == 0:
                self._pw_ready = True
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装完成")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText("")
            else:
                if hasattr(self, "cg_status_label"):
                    self.cg_status_label.setText("Chromium 内核安装失败")
                if hasattr(self, "cg_error_label"):
                    self.cg_error_label.setText(out[-800:])

        def on_err(err):
            self._pw_install_running = False
            if hasattr(self, "cg_install_btn"):
                self.cg_install_btn.setEnabled(True)
            if hasattr(self, "cg_error_label"):
                self.cg_error_label.setText(err)
            if hasattr(self, "cg_status_label"):
                self.cg_status_label.setText("Chromium 内核安装失败")

        self.start_worker(run_install, on_finished=on_done, on_error=on_err)

    def start_paddle_repair(self):
        """OCR 已为服务端模式，无需本地部署。此方法仅作兼容保留。"""
        QMessageBox.information(self, "无需部署", "OCR 已切换为服务端模式（/material/ocr），无需本地 PaddleOCR 环境。")  # noqa: E501
