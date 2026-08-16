# -*- coding: utf-8 -*-
"""
扩展插件页面（page 44）

管理「螺丝钉素材采集」浏览器扩展：
- 检测本机已安装的 Chromium 系浏览器（Chrome / Edge / 360 / QQ 等）
- 一键把扩展安装（加载）到所选浏览器：复制扩展文件到稳定目录后
  以 --load-extension 方式启动浏览器，并打开扩展管理页
- 控制本地桥接服务（extension_bridge）：启停 / 端口 / 保存目录 / 服务端扫描
- 查看最近采集记录
"""
import os
import shutil
import subprocess
import winreg

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.base_page import BasePage
from config.paths import EXTENSION_DIR
from utils.extension_bridge import DEFAULT_PORT
from utils.logger_utils import log
from utils.extension_bridge import DEFAULT_PORT, get_bridge

# 扩展模块目录（apps/browser-extension/）—— 源码即浏览器加载点，无需复制副本
from utils.file_dialog_utils import pick_directory
from utils.gui_icons import mdi_button
EXT_DIR = EXTENSION_DIR


# ── 浏览器检测 ────────────────────────────────────────────────────────────────

def _reg_app_path(exe_name: str) -> str:
    """从注册表 App Paths 读取浏览器可执行文件路径。"""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(
                root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}")
            path, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)
            if path and os.path.isfile(path):
                return path
        except OSError:
            continue
    return ""


def _first_existing(candidates) -> str:
    for p in candidates:
        p = os.path.expandvars(p)
        if os.path.isfile(p):
            return p
    return ""


def detect_browsers() -> list:
    """返回 [{name, exe}]，exe 为空表示未安装。"""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    la = os.environ.get("LOCALAPPDATA", "")
    defs = [
        ("Google Chrome", "chrome.exe", [
            rf"{pf}\Google\Chrome\Application\chrome.exe",
            rf"{pfx}\Google\Chrome\Application\chrome.exe",
            rf"{la}\Google\Chrome\Application\chrome.exe",
        ]),
        ("Microsoft Edge", "msedge.exe", [
            rf"{pfx}\Microsoft\Edge\Application\msedge.exe",
            rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        ]),
        ("360极速浏览器", "360chrome.exe", [
            rf"{la}\360Chrome\Chrome\Application\360chrome.exe",
            rf"{pf}\360\360Chrome\Chrome\Application\360chrome.exe",
            rf"{pfx}\360\360Chrome\Chrome\Application\360chrome.exe",
        ]),
        ("360安全浏览器", "360se.exe", [
            rf"{pf}\360\360se6\Application\360se.exe",
            rf"{pfx}\360\360se6\Application\360se.exe",
        ]),
        ("QQ浏览器", "QQBrowser.exe", [
            rf"{pf}\Tencent\QQBrowser\QQBrowser.exe",
            rf"{pfx}\Tencent\QQBrowser\QQBrowser.exe",
            rf"{la}\Tencent\QQBrowser\QQBrowser.exe",
        ]),
        ("搜狗高速浏览器", "SogouExplorer.exe", [
            rf"{pf}\SogouExplorer\SogouExplorer.exe",
            rf"{pfx}\SogouExplorer\SogouExplorer.exe",
        ]),
    ]
    result = []
    for name, exe_name, fallbacks in defs:
        exe = _reg_app_path(exe_name) or _first_existing(fallbacks)
        result.append({"name": name, "exe": exe})
    return result


def ensure_extension_installed() -> str:
    """校验扩展目录就绪并返回其路径（apps/browser-extension/，浏览器直接加载）。

    源码目录即加载点，无需复制副本（Chrome 开发者模式加载未打包扩展只读不写）。
    旧的 apps/extension 副本若存在则清理，避免双目录混淆。
    """
    if not os.path.isdir(EXT_DIR) or not os.path.isfile(os.path.join(EXT_DIR, "manifest.json")):
        raise FileNotFoundError(f"扩展目录不存在或缺少 manifest.json: {EXT_DIR}")
    # 清理历史遗留的复制副本（apps/extension），统一用 browser-extension 作为加载点
    legacy_copy = os.path.join(os.path.dirname(EXT_DIR), "extension")
    if os.path.isdir(legacy_copy) and os.path.normcase(legacy_copy) != os.path.normcase(EXT_DIR):
        try:
            shutil.rmtree(legacy_copy, ignore_errors=True)
        except Exception:
            pass
    return EXT_DIR


class ExtensionPage(BasePage):
    def setup(self):
        self.bridge = get_bridge()
        self._browsers = []

        outer = QVBoxLayout(self.parent_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs)

        download_tab = QWidget()
        dl_lay = QVBoxLayout(download_tab)
        dl_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        dl_lay.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel(" 扩展插件")
        title.setObjectName("heading")
        hdr.addWidget(title)
        desc = QLabel("浏览器素材采集扩展（仿 Billfish 采集插件）")
        desc.setObjectName("muted_text")
        desc.setWordWrap(True)
        desc.setMaximumWidth(1400)  # 一行显示，右侧留白避让资源监控
        hdr.addWidget(desc)
        hdr.addStretch()
        root.addLayout(hdr)

        root.addWidget(self._build_browser_card())
        root.addWidget(self._build_bridge_card())
        root.addWidget(self._build_records_card(), 1)
        self.tabs.addTab(download_tab, "⬇ 下载插件")

        self.bridge.record_added.connect(lambda _rec: self._refresh_records())
        self.bridge.log_message.connect(lambda _msg: self._refresh_bridge_status())

        from gui.auto_listing_tab import AutoListingTab
        self.auto_listing_tab = AutoListingTab(self)
        self.tabs.addTab(self.auto_listing_tab, " 自动上架")

        self._refresh_browsers()
        self._refresh_bridge_status()
        self._refresh_records()

    # ── 浏览器安装卡片 ──
    def _build_browser_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lay.addWidget(self._card_title("① 选择浏览器并安装扩展"))

        row = QHBoxLayout()
        self.browser_list = QListWidget()
        self.browser_list.setMaximumHeight(120)
        self.browser_list.setSelectionMode(QAbstractItemView.SingleSelection)
        row.addWidget(self.browser_list, 1)

        btns = QVBoxLayout()
        self.btn_install = QPushButton("安装到所选浏览器")
        self.btn_install.setObjectName("primary_button")
        self.btn_install.clicked.connect(self._install_to_browser)
        btns.addWidget(self.btn_install)
        self.btn_refresh_browsers = QPushButton("重新检测")
        self.btn_refresh_browsers.setObjectName("secondary_button")
        self.btn_refresh_browsers.clicked.connect(self._refresh_browsers)
        btns.addWidget(self.btn_refresh_browsers)
        self.btn_open_ext_dir = QPushButton("打开扩展目录")
        self.btn_open_ext_dir.setObjectName("secondary_button")
        self.btn_open_ext_dir.clicked.connect(self._open_ext_dir)
        btns.addWidget(self.btn_open_ext_dir)
        self.btn_copy_path = QPushButton("复制扩展路径")
        self.btn_copy_path.setObjectName("secondary_button")
        self.btn_copy_path.clicked.connect(self._copy_ext_path)
        btns.addWidget(self.btn_copy_path)
        btns.addStretch()
        row.addLayout(btns)
        lay.addLayout(row)

        tip = QLabel(
            "说明：新版 Chrome / Edge 已禁止启用非商店来源的 .crx 扩展（旁加载已失效）。\n"
            "点击「安装到所选浏览器」会打开扩展管理页并复制扩展路径，按提示开启「开发者模式」→"
            "「加载已解压的扩展程序」即可——只需装一次，重启浏览器后仍然有效。"
        )
        tip.setObjectName("muted_text")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    # ── 桥接服务卡片 ──
    def _build_bridge_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(self._card_title("② 采集桥接服务（接收扩展发来的素材）"))
        head.addStretch()
        self.bridge_status = QLabel("● 未启动")
        self.bridge_status.setObjectName("muted_text")
        head.addWidget(self.bridge_status)
        self.bridge_port_note = QLabel()
        self.bridge_port_note.setObjectName("muted_text")
        self.bridge_port_note.setStyleSheet("color: #f59e0b; font-size: 12px;")
        head.addWidget(self.bridge_port_note)
        lay.addLayout(head)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("监听端口:"))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(int(self.bridge.config.get("port") or DEFAULT_PORT))
        row1.addWidget(self.spin_port)
        row1.addWidget(QLabel("保存目录:"))
        self.edit_save_dir = QLineEdit(self.bridge.config.get("save_dir") or "")
        row1.addWidget(self.edit_save_dir, 1)
        btn_browse = mdi_button("浏览…", "folder")
        btn_browse.setObjectName("secondary_button")
        btn_browse.clicked.connect(self._browse_save_dir)
        row1.addWidget(btn_browse)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_auto_start = QCheckBox("启动客户端时自动开启桥接服务")
        self.chk_auto_start.setChecked(bool(self.bridge.config.get("auto_start", True)))
        row2.addWidget(self.chk_auto_start)
        row2.addWidget(QLabel("服务端扫描目录(可空):"))
        self.edit_scan_dir = QLineEdit(self.bridge.config.get("server_scan_dir") or "")
        self.edit_scan_dir.setPlaceholderText("服务端可见的 NAS 路径，采集后触发 /material/scan 入库")
        row2.addWidget(self.edit_scan_dir, 1)
        lay.addLayout(row2)

        row2b = QHBoxLayout()
        row2b.addWidget(QLabel("NAS 同步目录:"))
        self.edit_nas_dir = QLineEdit(self.bridge.config.get("nas_sync_dir") or "")
        self.edit_nas_dir.setPlaceholderText("本地映射网盘目录（如 Z:\\materials\\collect），下载成功后同步到此")
        row2b.addWidget(self.edit_nas_dir, 1)
        btn_browse_nas = mdi_button("浏览…", "folder")
        btn_browse_nas.setObjectName("secondary_button")
        btn_browse_nas.clicked.connect(self._browse_nas_dir)
        row2b.addWidget(btn_browse_nas)
        lay.addLayout(row2b)

        row2c = QHBoxLayout()
        row2c.addWidget(QLabel("下载引擎 Cookies:"))
        self.combo_cookies = QComboBox()
        for text, data in [("不使用", ""), ("Chrome", "chrome"), ("Edge", "edge"), ("Firefox", "firefox")]:
            self.combo_cookies.addItem(text, data)
        cur_cookies = (self.bridge.config.get("cookies_browser") or "").lower()
        idx = self.combo_cookies.findData(cur_cookies)
        self.combo_cookies.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_cookies.setToolTip(
            "YouTube 等站点有防机器人校验，yt-dlp 需要读取浏览器登录态 cookies 才能下载。\n"
            "选择读取哪个浏览器的 cookies（需在该浏览器登录过 YouTube/Google）。"
        )
        row2c.addWidget(self.combo_cookies)
        self.btn_update_engine = QPushButton("⬆ 更新下载引擎 (yt-dlp)")
        self.btn_update_engine.setObjectName("secondary_button")
        self.btn_update_engine.clicked.connect(self._update_engine)
        row2c.addWidget(self.btn_update_engine)
        row2c.addStretch()
        lay.addLayout(row2c)

        row2e = QHBoxLayout()
        row2e.addWidget(QLabel("代理地址:"))
        self.edit_proxy = QLineEdit(self.bridge.config.get("proxy") or "")
        self.edit_proxy.setPlaceholderText("127.0.0.1:7890（留空=不走代理；socks5端口请写 socks5://host:port）")
        self.edit_proxy.setToolTip(
            "仅 YouTube 下载使用代理，其他站点直连。填写你代理软件的本地端口，\n"
            "以运行环境方式注入：yt-dlp/ffmpeg 全链路统一走代理。\n\n"
            "填写规则：\n"
            "• 直接写 127.0.0.1:端口 → 默认按 http 代理（推荐，兼容 Clash 混合端口/v2rayN http端口）\n"
            "• 代理只开了 socks5 端口 → 显式写 socks5://127.0.0.1:端口\n"
            "• 已带 http:// 或 socks5:// 前缀则按你写的\n"
            "• B站/抖音等国内站点留空即可"
        )
        row2e.addWidget(self.edit_proxy, 1)
        lay.addLayout(row2e)

        row2d = QHBoxLayout()
        self.chk_auto_subtitle = QCheckBox(" 视频下载后自动生成字幕（调用服务端 Whisper，与视频同目录保存 .srt 并同步 NAS）")
        self.chk_auto_subtitle.setChecked(bool(self.bridge.config.get("auto_subtitle", False)))
        row2d.addWidget(self.chk_auto_subtitle)
        row2d.addStretch()
        lay.addLayout(row2d)

        row3 = QHBoxLayout()
        self.btn_bridge_toggle = QPushButton("启动服务")
        self.btn_bridge_toggle.setObjectName("primary_button")
        self.btn_bridge_toggle.clicked.connect(self._toggle_bridge)
        row3.addWidget(self.btn_bridge_toggle)
        btn_save_cfg = QPushButton("保存配置")
        btn_save_cfg.setObjectName("secondary_button")
        btn_save_cfg.clicked.connect(self._save_bridge_config)
        row3.addWidget(btn_save_cfg)
        btn_open_save = QPushButton("打开采集目录")
        btn_open_save.setObjectName("secondary_button")
        btn_open_save.clicked.connect(self._open_save_dir)
        row3.addWidget(btn_open_save)
        row3.addStretch()
        lay.addLayout(row3)
        return card

    # ── 采集记录卡片 ──
    def _build_records_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(self._card_title("③ 最近采集记录"))
        head.addStretch()
        btn_clear_done = QPushButton("清空已完成")
        btn_clear_done.setObjectName("secondary_button")
        btn_clear_done.setToolTip("删除已下载成功（含已同步 NAS）的记录，保留失败记录")
        btn_clear_done.clicked.connect(self._clear_done_records)
        head.addWidget(btn_clear_done)
        btn_clear_all = QPushButton(" 清空全部")
        btn_clear_all.setObjectName("secondary_button")
        btn_clear_all.setToolTip("删除所有记录（成功和失败），服务器重启后记录会重现")
        btn_clear_all.clicked.connect(self._clear_all_records)
        head.addWidget(btn_clear_all)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("secondary_button")
        btn_refresh.clicked.connect(self._refresh_records)
        head.addWidget(btn_refresh)
        lay.addLayout(head)

        self.records_table = QTableWidget(0, 5)
        self.records_table.setHorizontalHeaderLabels(["时间", "类型", "文件名", "状态", "来源页面"])
        self.records_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.records_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.records_table.verticalHeader().setVisible(False)
        self.records_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.records_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.records_table, 1)
        return card

    def _card_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("card_title")
        return lbl

    # ── 浏览器相关动作 ──
    def _refresh_browsers(self):
        self._browsers = detect_browsers()
        self.browser_list.clear()
        first_installed = -1
        for i, b in enumerate(self._browsers):
            installed = bool(b["exe"])
            item = QListWidgetItem(f"{'完成：' if installed else '移除'} {b['name']}  {b['exe'] or '（未安装）'}")
            item.setData(Qt.UserRole, i)
            if not installed:
                item.setFlags(Qt.NoItemFlags)
            elif first_installed < 0:
                first_installed = i
            self.browser_list.addItem(item)
        if first_installed >= 0:
            self.browser_list.setCurrentRow(first_installed)

    def _install_to_browser(self):
        row = self.browser_list.currentRow()
        if row < 0:
            self.show_warning("请先选择一个浏览器。")
            return
        browser = self._browsers[self.browser_list.item(row).data(Qt.UserRole)]
        if not browser["exe"]:
            self.show_warning(f"未检测到 {browser['name']}，请选择其他浏览器。")
            return
        try:
            ext_dir = ensure_extension_installed()
        except Exception as e:
            self.show_error(f"准备扩展文件失败：{e}")
            return
        # 打开浏览器扩展管理页（不带 --load-extension：浏览器已运行时该参数会被忽略，
        # 且临时加载每次启动都要重装，反而误导）
        try:
            subprocess.Popen(
                [browser["exe"], "chrome://extensions/"],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as e:
            self.show_error(f"启动浏览器失败：{e}")
            return
        QGuiApplication.clipboard().setText(ext_dir)
        log.info(f"[扩展插件] 已打开 {browser['name']} 扩展管理页，扩展目录: {ext_dir}")
        self.show_info(
            f"已在 {browser['name']} 打开扩展管理页，扩展目录已复制到剪贴板。\n\n"
            "请按以下三步完成安装（只需装一次，重启浏览器后仍在）：\n"
            "1. 在扩展管理页右上角打开「开发者模式」\n"
            "2. 点击「加载已解压的扩展程序」\n"
            f"3. 粘贴路径 {ext_dir} 并确认\n\n"
            "注意： 重要：每次客户端更新扩展后，需要在扩展管理页找到「螺丝钉下载器」，"
            "点击其卡片上的「 刷新」按钮重新加载，否则浏览器仍运行旧版本。\n\n"
            "说明：新版 Chrome/Edge 已禁止启用任何非商店来源的 .crx 扩展，"
            "开发者模式加载是目前唯一的本地持久安装方式（启动时顶部会有一条开发者模式提示，属正常现象）。")

    def _open_ext_dir(self):
        try:
            ext_dir = ensure_extension_installed()
            os.startfile(ext_dir)
        except Exception as e:
            self.show_error(f"打开扩展目录失败：{e}")

    def _copy_ext_path(self):
        QGuiApplication.clipboard().setText(EXT_DIR)
        self.show_info(f"扩展路径已复制：\n{EXT_DIR}")

    # ── 桥接服务动作 ──
    def _validate_sync_pair(self) -> bool:
        """服务端扫描目录与 NAS 同步目录必须成对配置。"""
        scan = self.edit_scan_dir.text().strip()
        nas = self.edit_nas_dir.text().strip()
        if scan and not nas:
            self.show_warning("已配置「服务端扫描目录」，必须同时选择「NAS 同步目录」"
                              "（本地映射网盘，与服务端扫描目录对应），采集的素材才会同步入库。")
            return False
        if nas and not scan:
            self.show_warning("已配置「NAS 同步目录」，建议同时填写「服务端扫描目录」，"
                              "否则素材只同步到 NAS，不会触发服务端入库扫描。")
        return True

    def _save_bridge_config(self):
        if not self._validate_sync_pair():
            return
        restart_needed = (
            int(self.bridge.config.get("port") or DEFAULT_PORT) != self.spin_port.value()
            and self.bridge.is_running
        )
        self.bridge.update_config(
            port=self.spin_port.value(),
            save_dir=self.edit_save_dir.text().strip(),
            auto_start=self.chk_auto_start.isChecked(),
            server_scan_dir=self.edit_scan_dir.text().strip(),
            nas_sync_dir=self.edit_nas_dir.text().strip(),
            cookies_browser=self.combo_cookies.currentData(),
            auto_subtitle=self.chk_auto_subtitle.isChecked(),
            proxy=self.edit_proxy.text().strip(),
        )
        if restart_needed:
            self.bridge.stop()
            self.bridge.start()
        self._refresh_bridge_status()
        self.show_info("桥接配置已保存。")

    def _toggle_bridge(self):
        if self.bridge.is_running:
            self.bridge.stop()
        else:
            self._save_bridge_config_silent()
            ok, msg = self.bridge.start()
            if not ok:
                self.show_error(msg)
        self._refresh_bridge_status()

    def _save_bridge_config_silent(self):
        self.bridge.update_config(
            port=self.spin_port.value(),
            save_dir=self.edit_save_dir.text().strip(),
            auto_start=self.chk_auto_start.isChecked(),
            server_scan_dir=self.edit_scan_dir.text().strip(),
            nas_sync_dir=self.edit_nas_dir.text().strip(),
            cookies_browser=self.combo_cookies.currentData(),
            auto_subtitle=self.chk_auto_subtitle.isChecked(),
            proxy=self.edit_proxy.text().strip(),
        )

    def _update_engine(self):
        """后台更新 yt-dlp（YouTube 解析规则频繁变化，需保持最新）。"""
        from utils.base_worker import BaseWorker
        from utils.extension_bridge import _find_ytdlp
        ytdlp = _find_ytdlp()
        if not ytdlp:
            self.show_warning("未找到 yt-dlp（apps/asset-browser/bin/yt-dlp.exe）。")
            return
        self.btn_update_engine.setEnabled(False)
        self.btn_update_engine.setText("更新中…")

        class _UpdateWorker(BaseWorker):
            finished = Signal(str)

            def do_work(self):
                r = subprocess.run([ytdlp, "-U"], capture_output=True, text=True,
                                   timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                self.finished.emit(out.splitlines()[-1] if out else "完成")

        def _done(msg):
            self.btn_update_engine.setEnabled(True)
            self.btn_update_engine.setText("⬆ 更新下载引擎 (yt-dlp)")
            log.info(f"[扩展插件] yt-dlp 更新: {msg}")
            self.show_info(f"下载引擎更新结果：\n{msg}")

        def _err(msg):
            self.btn_update_engine.setEnabled(True)
            self.btn_update_engine.setText("⬆ 更新下载引擎 (yt-dlp)")
            self.show_error(f"更新失败：{msg}")

        w = self.track_worker(_UpdateWorker())
        w.finished.connect(_done)
        w.error.connect(_err)
        w.start()

    def _browse_nas_dir(self):
        d = pick_directory(self.parent_widget, "选择 NAS 同步目录（本地映射网盘）",
                                             self.edit_nas_dir.text() or DATA_DIR)
        if d:
            self.edit_nas_dir.setText(d)

    def _browse_save_dir(self):
        d = pick_directory(self.parent_widget, "选择采集保存目录",
                                             self.edit_save_dir.text() or DATA_DIR)
        if d:
            self.edit_save_dir.setText(d)

    def _open_save_dir(self):
        d = self.edit_save_dir.text().strip()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            self.show_error(f"打开目录失败：{e}")

    def _refresh_bridge_status(self):
        running = self.bridge.is_running
        port = self.bridge.port
        self.bridge_status.setText(
            f"● 运行中 127.0.0.1:{port}（已采集 {self.bridge.collected_count} 个）"
            if running else "● 未启动")
        self.bridge_status.setStyleSheet("color: #2ecc71;" if running else "color: #999;")
        self.btn_bridge_toggle.setText("停止服务" if running else "启动服务")

        port_note = None
        if running:
            config_port = self.bridge.config.get("port")
            try:
                cfg_port = int(config_port) if config_port else DEFAULT_PORT
                if cfg_port != port:
                    port_note = f"注意： 配置端口({cfg_port}) 与运行端口({port})不一致，请在桥接配置中更新配置到运行端口({port})以免连接失败"
            except Exception:
                pass

        self.bridge_port_note.setText(port_note or "")

    # ── 记录 ──
    def _clear_done_records(self):
        n = self.bridge.clear_done_records()
        self._refresh_records()
        self.show_info(f"已清除 {n} 条已完成记录（失败记录保留）。")

    def _clear_all_records(self):
        n = self.bridge.clear_all_records()
        self._refresh_records()
        self.show_info(f"已清除 {n} 条全部记录。")

    def _refresh_records(self):
        records = list(reversed(self.bridge.records))[:100]
        self.records_table.setRowCount(len(records))
        for r, rec in enumerate(records):
            if rec.get("status") == "ok":
                status = " 成功" + (" ⇢NAS" if rec.get("synced") else "")
            else:
                status = f"失败： {rec.get('error', '')[:40]}"
            for c, val in enumerate([
                rec.get("time", ""), rec.get("media_type", ""),
                rec.get("filename") or rec.get("url", "")[-60:], status,
                rec.get("page_title") or rec.get("page_url", ""),
            ]):
                self.records_table.setItem(r, c, QTableWidgetItem(str(val)))
        self._refresh_bridge_status()

    # ── 页面激活时刷新 ──
    def refresh(self):
        self._refresh_bridge_status()
        self._refresh_records()
        if hasattr(self, "auto_listing_tab"):
            self.auto_listing_tab.refresh()
