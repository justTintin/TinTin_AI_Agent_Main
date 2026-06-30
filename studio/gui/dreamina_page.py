# -*- coding: utf-8 -*-
"""
即梦（Dreamina）生成页。

把 `dreamina` CLI 当普通命令行工具用（详见 utils/dreamina_client.py）：
- 登录：设备码 OAuth。点登录 → 显示授权链接（浏览器打开用抖音确认）→ 后台轮询完成。
- 文生图：提交 text2image → 轮询 query_result 下载图片到 outputs/dreamina/<时间>。
- 生成结果可一键加入「素材管理」。

视频生成（text2video 等）后续按同模式扩展。
"""
import os
import time
import webbrowser
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit,
    QFrame, QWidget, QComboBox, QListWidget, QListWidgetItem, QProgressBar,
)
from PySide6.QtCore import Signal, Qt

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.dreamina_client import DreaminaClient
from utils.media_library_manager import MediaLibraryManager
from config.paths import DREAMINA_OUTPUT_DIR

RATIOS = ["(默认)", "9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2", "21:9"]
MODELS = ["(默认)", "5.0", "4.7", "4.6", "4.5", "4.1", "4.0", "3.1", "3.0"]
RESOLUTIONS = ["(默认)", "1k", "2k", "4k"]


class LoginInitWorker(BaseWorker):
    finished = Signal(dict)

    def do_work(self):
        ok, info = DreaminaClient().login_headless()
        if not ok:
            self.error.emit(info if isinstance(info, str) else "发起登录失败")
            return
        self.finished.emit(info)


class LoginPollWorker(BaseWorker):
    finished = Signal(bool, str)

    def __init__(self, device_code):
        super().__init__()
        self.device_code = device_code

    def do_work(self):
        ok, raw = DreaminaClient().checklogin(self.device_code, poll=60)
        self.finished.emit(ok, raw)


class CreditWorker(BaseWorker):
    finished = Signal(bool, str)

    def do_work(self):
        logged, credit = DreaminaClient().is_logged_in()
        self.finished.emit(logged, credit)


class Text2ImageWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(list, str)   # downloaded files, submit_id

    def __init__(self, prompt, ratio, model, resolution, out_dir):
        super().__init__()
        self.prompt = prompt
        self.ratio = ratio
        self.model = model
        self.resolution = resolution
        self.out_dir = out_dir

    def do_work(self):
        client = DreaminaClient()
        self.phase.emit("正在提交文生图任务…")
        ok, info = client.text2image(self.prompt, ratio=self.ratio,
                                     resolution_type=self.resolution,
                                     model_version=self.model, poll=0)
        submit_id = info.get("submit_id", "")
        if not submit_id:
            self.error.emit("提交失败：\n" + (info.get("raw", "") or "未返回 submit_id"))
            return
        if info.get("gen_status") == "fail":
            self.error.emit("生成失败：" + info.get("fail_reason", info.get("raw", "")))
            return
        self.phase.emit(f"已提交（{submit_id[:12]}…），等待出图…")
        # 轮询 query_result，直到目录里出现下载文件 / 失败 / 超时
        for i in range(40):  # ~40 * 6s ≈ 4 分钟
            info2, files = client.query_result(submit_id, download_dir=self.out_dir)
            if files:
                self.finished.emit(files, submit_id)
                return
            if info2.get("gen_status") == "fail":
                self.error.emit("生成失败：" + info2.get("fail_reason", info2.get("raw", "")))
                return
            self.phase.emit(f"出图中…（{(i + 1) * 6}s）")
            time.sleep(6)
        self.error.emit("等待超时，可稍后在『查询结果』里用 submit_id 重试。")


class DreaminaPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.client = DreaminaClient()
        self.media = MediaLibraryManager()
        self._login_info = None
        self._last_out_dir = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(16)

        heading = QLabel("🎨 即梦生成")
        heading.setObjectName("heading")
        root.addWidget(heading)

        if not self.client.is_installed():
            warn = QLabel("⚠️ 未检测到 dreamina 可执行文件（studio/bin/dreamina.exe）。"
                          "请先放置即梦 CLI 二进制后重启。")
            warn.setObjectName("muted_text"); warn.setWordWrap(True)
            root.addWidget(warn)

        root.addWidget(self._build_login_card())
        root.addWidget(self._build_generate_card(), 1)
        root.addWidget(self._build_result_card(), 1)

        self._refresh_login_state()

    # ---------- 登录卡 ----------
    def _build_login_card(self):
        card = QFrame(); card.setObjectName("card")
        lay = QVBoxLayout(card); lay.setContentsMargins(20, 14, 20, 14); lay.setSpacing(8)

        row = QHBoxLayout()
        self.lbl_login = QLabel("登录状态：检测中…")
        row.addWidget(self.lbl_login, 1)
        self.btn_login = QPushButton("登录即梦")
        self.btn_login.setObjectName("primary_button")
        self.btn_login.clicked.connect(self._start_login)
        row.addWidget(self.btn_login)
        btn_credit = QPushButton("刷新额度"); btn_credit.setObjectName("secondary_button")
        btn_credit.clicked.connect(self._refresh_login_state)
        row.addWidget(btn_credit)
        lay.addLayout(row)

        self.login_hint = QLabel("")
        self.login_hint.setObjectName("muted_text"); self.login_hint.setWordWrap(True)
        self.login_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.login_hint)

        self.btn_open_auth = QPushButton("🌐 在浏览器打开授权页（用抖音扫码/确认）")
        self.btn_open_auth.setObjectName("secondary_button")
        self.btn_open_auth.clicked.connect(self._open_auth_url)
        self.btn_open_auth.setVisible(False)
        lay.addWidget(self.btn_open_auth)
        return card

    def _build_generate_card(self):
        card = QFrame(); card.setObjectName("card")
        lay = QVBoxLayout(card); lay.setContentsMargins(20, 14, 20, 14); lay.setSpacing(10)
        lay.addWidget(QLabel("🖼️ 文生图（text2image，消耗额度）"))

        self.edit_prompt = QTextEdit()
        self.edit_prompt.setPlaceholderText("输入画面提示词（可来自分镜脚本的『画面视觉描述』）…")
        self.edit_prompt.setFixedHeight(80)
        lay.addWidget(self.edit_prompt)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("比例"))
        self.combo_ratio = QComboBox(); self.combo_ratio.addItems(RATIOS); self.combo_ratio.setCurrentText("9:16")
        opt.addWidget(self.combo_ratio)
        opt.addWidget(QLabel("模型"))
        self.combo_model = QComboBox(); self.combo_model.addItems(MODELS)
        opt.addWidget(self.combo_model)
        opt.addWidget(QLabel("清晰度"))
        self.combo_res = QComboBox(); self.combo_res.addItems(RESOLUTIONS)
        opt.addWidget(self.combo_res)
        opt.addStretch()
        self.btn_gen = QPushButton("🎨 生成图片")
        self.btn_gen.setObjectName("primary_button")
        self.btn_gen.clicked.connect(self._generate)
        opt.addWidget(self.btn_gen)
        lay.addLayout(opt)

        srow = QHBoxLayout()
        self.gen_status = QLabel("就绪"); self.gen_status.setObjectName("muted_text")
        srow.addWidget(self.gen_status, 1)
        self.gen_pbar = QProgressBar(); self.gen_pbar.setVisible(False)
        self.gen_pbar.setRange(0, 0); self.gen_pbar.setMaximumWidth(160)
        srow.addWidget(self.gen_pbar)
        lay.addLayout(srow)
        return card

    def _build_result_card(self):
        card = QFrame(); card.setObjectName("card")
        lay = QVBoxLayout(card); lay.setContentsMargins(20, 14, 20, 14); lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("📦 生成结果"))
        top.addStretch()
        self.btn_to_media = QPushButton("📥 加入素材管理"); self.btn_to_media.setObjectName("secondary_button")
        self.btn_to_media.clicked.connect(self._add_to_media); self.btn_to_media.setEnabled(False)
        top.addWidget(self.btn_to_media)
        self.btn_open_dir = QPushButton("打开输出目录"); self.btn_open_dir.setObjectName("secondary_button")
        self.btn_open_dir.clicked.connect(self._open_out_dir); self.btn_open_dir.setEnabled(False)
        top.addWidget(self.btn_open_dir)
        lay.addLayout(top)
        self.result_list = QListWidget()
        lay.addWidget(self.result_list, 1)
        return card

    # ---------- 登录流程 ----------
    def _refresh_login_state(self):
        self.lbl_login.setText("登录状态：检测中…")
        w = self.track_worker(CreditWorker())
        w.finished.connect(self._on_credit)
        w.start()

    def _on_credit(self, logged, credit):
        if logged:
            self.lbl_login.setText(f"✅ 已登录　额度：{credit or '—'}")
            self.btn_login.setText("重新登录")
        else:
            self.lbl_login.setText("❌ 未登录")
            self.btn_login.setText("登录即梦")

    def _start_login(self):
        self.btn_login.setEnabled(False)
        self.login_hint.setText("正在发起设备码登录…")
        w = self.track_worker(LoginInitWorker())
        w.finished.connect(self._on_login_init)
        w.error.connect(self._on_login_err)
        w.start()

    def _on_login_init(self, info):
        self._login_info = info
        self.btn_open_auth.setVisible(True)
        self.login_hint.setText(
            "请在浏览器打开下方授权页，用『抖音』App 扫码并确认授权；确认后本页会自动完成登录。\n"
            f"user_code: {info.get('user_code','')}\n{info.get('verification_uri','')}"
        )
        webbrowser.open(info.get("verification_uri", ""))
        # 后台轮询完成登录
        w = self.track_worker(LoginPollWorker(info.get("device_code", "")))
        w.finished.connect(self._on_login_done)
        w.error.connect(self._on_login_err)
        w.start()

    def _on_login_done(self, ok, raw):
        self.btn_login.setEnabled(True)
        if ok:
            self.btn_open_auth.setVisible(False)
            self.login_hint.setText("✅ 登录成功，本地会话已保存。")
            self._refresh_login_state()
        else:
            self.login_hint.setText("未检测到登录完成。若已在手机确认，请点『刷新额度』；否则重试登录。")

    def _on_login_err(self, err):
        self.btn_login.setEnabled(True)
        self.login_hint.setText(f"登录失败：{err}")

    def _open_auth_url(self):
        if self._login_info:
            webbrowser.open(self._login_info.get("verification_uri", ""))

    # ---------- 生成 ----------
    def _combo_val(self, combo):
        v = combo.currentText()
        return "" if v == "(默认)" else v

    def _generate(self):
        prompt = self.edit_prompt.toPlainText().strip()
        if not prompt:
            self.show_warning("请先输入画面提示词。")
            return
        out_dir = os.path.join(DREAMINA_OUTPUT_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))
        self._last_out_dir = out_dir
        self.btn_gen.setEnabled(False)
        self.gen_pbar.setVisible(True)
        self.result_list.clear()
        self.btn_to_media.setEnabled(False)
        self.btn_open_dir.setEnabled(False)
        w = self.track_worker(Text2ImageWorker(
            prompt, self._combo_val(self.combo_ratio), self._combo_val(self.combo_model),
            self._combo_val(self.combo_res), out_dir))
        w.phase.connect(self.gen_status.setText)
        w.finished.connect(self._on_generated)
        w.error.connect(self._on_gen_err)
        w.start()

    def _on_generated(self, files, submit_id):
        self.btn_gen.setEnabled(True)
        self.gen_pbar.setVisible(False)
        self.gen_status.setText(f"✅ 生成完成，{len(files)} 个文件（submit_id={submit_id[:12]}…）")
        for f in files:
            self.result_list.addItem(QListWidgetItem(f))
        self.btn_to_media.setEnabled(bool(files))
        self.btn_open_dir.setEnabled(bool(files))

    def _on_gen_err(self, err):
        self.btn_gen.setEnabled(True)
        self.gen_pbar.setVisible(False)
        self.gen_status.setText("生成失败。")
        self.show_error(err, "即梦生成失败")

    def _add_to_media(self):
        if not self._last_out_dir or not os.path.isdir(self._last_out_dir):
            return
        ok, msg, _ = self.media.add_mount(self._last_out_dir, kind="项目",
                                          group="即梦生成", tags=["即梦", "AI生成"])
        self.show_info(msg if ok else f"未添加：{msg}")

    def _open_out_dir(self):
        if self._last_out_dir and os.path.isdir(self._last_out_dir) and os.name == "nt":
            os.startfile(self._last_out_dir)  # noqa
