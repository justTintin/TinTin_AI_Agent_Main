"""「自动上架」Tab：导入数据包、管理 Chrome 调试会话、执行抖店自动上架。"""
import os

from gui.elided_label import ElidedLabel
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.auto_listing import config as al_config
from utils.auto_listing.chrome_manager import is_cdp_ready
from utils.auto_listing.engine import AutoListingEngine
from utils.auto_listing.validation import prepare_package
from utils.base_worker import BaseWorker
from utils.file_dialog_utils import pick_directory
from utils.gui_icons import mdi_button


class ValidateWorker(BaseWorker):
    finished = Signal(dict)

    def __init__(self, input_path, shop_key, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.shop_key = shop_key

    def do_work(self):
        info = prepare_package(self.input_path, self.shop_key)
        self.finished.emit({
            "title": info.title,
            "shop_name": info.shop_name,
            "sku_count": len(info.skus),
            "main_images": len(info.main_images),
            "detail_images": len(info.detail_images),
            "sku_images": len(info.sku_images),
            "warnings": info.warnings,
            "info": info,
        })


class AutoListingWorker(BaseWorker):
    progress = Signal(str, str)
    finished = Signal(dict)

    def __init__(self, input_path, shop_key, config, publish_after_save,
                 prepared_info=None, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.shop_key = shop_key
        self.config = config
        self.publish_after_save = publish_after_save
        self.prepared_info = prepared_info

    def do_work(self):
        engine = AutoListingEngine(
            progress=lambda stage, msg: self.progress.emit(stage, msg),
            should_stop=lambda: self.isInterruptionRequested(),
        )
        result = engine.run(
            self.input_path,
            self.shop_key,
            config=self.config,
            publish_after_save=self.publish_after_save,
            prepared_info=self.prepared_info,
        )
        self.finished.emit(result)


class AutoListingTab(QWidget):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page
        self._cfg = al_config.load_config()
        self._prepared_info = None
        self._worker = None
        self._validate_worker = None
        self._build_ui()
        self._load_config_to_ui()

    # ─────────────────────────── UI ───────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        root.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel(" 自动上架")
        title.setObjectName("heading")
        hdr.addWidget(title)
        desc = ElidedLabel("抖店商品自动上架：导入数据包 → 复用已登录 Chrome → 自动填写并保存草稿", max_lines=1)
        desc.setObjectName("muted_text")
        hdr.addWidget(desc)
        hdr.addStretch()
        lay.addLayout(hdr)

        lay.addWidget(self._build_config_card())
        lay.addWidget(self._build_package_card())
        lay.addWidget(self._build_execution_card(), 1)

    def _card_title(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("card_title")
        return lbl

    def _build_config_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(self._card_title("① 浏览器与店铺"))

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("目标店铺:"))
        self.shop_combo = QComboBox()
        for key, info in al_config.DOUYIN_STORES.items():
            self.shop_combo.addItem(f"{info['name']}（{key}）", key)
        row1.addWidget(self.shop_combo)
        row1.addSpacing(12)
        row1.addWidget(QLabel("Chrome:"))
        self.chrome_edit = QLineEdit()
        self.chrome_edit.setPlaceholderText("chrome.exe 路径，留空自动检测")
        row1.addWidget(self.chrome_edit, 1)
        btn_chrome = mdi_button("浏览", "folder")
        btn_chrome.setObjectName("secondary_button")
        btn_chrome.clicked.connect(self._browse_chrome)
        row1.addWidget(btn_chrome)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("调试端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        row2.addWidget(self.port_spin)
        row2.addSpacing(12)
        row2.addWidget(QLabel("用户目录:"))
        self.user_data_edit = QLineEdit()
        row2.addWidget(self.user_data_edit, 1)
        btn_data = mdi_button("浏览", "folder")
        btn_data.setObjectName("secondary_button")
        btn_data.clicked.connect(self._browse_user_data)
        row2.addWidget(btn_data)
        self.cdp_status = QLabel("● 未检测")
        self.cdp_status.setObjectName("muted_text")
        row2.addWidget(self.cdp_status)
        lay.addLayout(row2)

        btns = QHBoxLayout()
        btn_check = mdi_button("检测端口", "search")
        btn_check.setObjectName("secondary_button")
        btn_check.clicked.connect(self._check_cdp)
        btns.addWidget(btn_check)
        btn_save = mdi_button("保存配置", "save")
        btn_save.setObjectName("primary_button")
        btn_save.clicked.connect(self._save_config_ui)
        btns.addWidget(btn_save)
        btn_open_result = mdi_button("打开结果目录", "folder")
        btn_open_result.setObjectName("secondary_button")
        btn_open_result.clicked.connect(self._open_result_dir)
        btns.addWidget(btn_open_result)
        btns.addStretch()
        lay.addLayout(btns)
        return card

    def _build_package_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(self._card_title("② 上架数据包"))

        row = QHBoxLayout()
        row.addWidget(QLabel("数据包:"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择包含 sku.xlsx、主图、详情页、sku图 的目录或 .zip")
        row.addWidget(self.input_edit, 1)
        btn_dir = mdi_button("目录", "folder")
        btn_dir.setObjectName("secondary_button")
        btn_dir.clicked.connect(self._browse_package_dir)
        row.addWidget(btn_dir)
        btn_zip = mdi_button("ZIP", "file")
        btn_zip.setObjectName("secondary_button")
        btn_zip.clicked.connect(self._browse_package_zip)
        row.addWidget(btn_zip)
        btn_validate = mdi_button("校验", "check")
        btn_validate.setObjectName("primary_button")
        btn_validate.clicked.connect(self._validate_package)
        row.addWidget(btn_validate)
        lay.addLayout(row)

        self.package_summary = QLabel("尚未校验数据包")
        self.package_summary.setObjectName("muted_text")
        self.package_summary.setWordWrap(True)
        lay.addWidget(self.package_summary)
        return card

    def _build_execution_card(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(self._card_title("③ 执行"))

        ctl = QHBoxLayout()
        self.chk_publish = QCheckBox("保存草稿后尝试直接上架（默认只保存草稿）")
        ctl.addWidget(self.chk_publish)
        ctl.addStretch()
        self.btn_start = mdi_button("开始自动上架", "rocket")
        self.btn_start.setObjectName("primary_button")
        self.btn_start.clicked.connect(self._start)
        ctl.addWidget(self.btn_start)
        self.btn_stop = mdi_button("停止", "stop")
        self.btn_stop.setObjectName("secondary_button")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        ctl.addWidget(self.btn_stop)
        lay.addLayout(ctl)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("运行日志会显示在这里")
        lay.addWidget(self.log_view, 1)
        return card

    # ─────────────────────────── 配置 ───────────────────────────
    def _collect_cfg(self):
        return {
            "chrome_exe": self.chrome_edit.text().strip() or al_config.detect_chrome_exe(),  # noqa: E501
            "debug_port": self.port_spin.value(),
            "user_data_dir": self.user_data_edit.text().strip() or al_config.AUTO_LISTING_CHROME_USER_DATA,  # noqa: E501
            "result_dir": al_config.AUTO_LISTING_RESULTS_DIR,
            "sync_dir": al_config.AUTO_LISTING_SYNC_DIR,
            "shop_key": self.shop_combo.currentData(),
            "publish_after_save": self.chk_publish.isChecked(),
        }

    def _load_config_to_ui(self):
        self.shop_combo.setCurrentIndex(max(0, self.shop_combo.findData(self._cfg.get("shop_key"))))  # noqa: E501
        self.chrome_edit.setText(self._cfg.get("chrome_exe") or "")
        self.port_spin.setValue(int(self._cfg.get("debug_port") or 9222))
        self.user_data_edit.setText(self._cfg.get("user_data_dir") or "")
        self.chk_publish.setChecked(bool(self._cfg.get("publish_after_save")))
        self._check_cdp()

    def _save_config_ui(self):
        self._cfg = al_config.save_config(self._collect_cfg())
        self._page.show_info("自动上架配置已保存。")

    def _browse_chrome(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Chrome", "", "Chrome (*.exe)")
        if path:
            self.chrome_edit.setText(path)

    def _browse_user_data(self):
        d = pick_directory(self, "选择 Chrome 用户数据目录", self.user_data_edit.text())
        if d:
            self.user_data_edit.setText(d)

    def _open_result_dir(self):
        d = self._collect_cfg().get("result_dir") or al_config.AUTO_LISTING_RESULTS_DIR
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _check_cdp(self):
        try:
            ready = is_cdp_ready(self.port_spin.value(), timeout=0.3)
        except Exception:  # 外部API调用（CDP 端口探测）
            ready = False
        self.cdp_status.setText("● 已就绪" if ready else "● 未启动")
        self.cdp_status.setStyleSheet("color: #2ecc71;" if ready else "color: #999;")

    def _browse_package_dir(self):
        d = pick_directory(self, "选择上架数据包目录")
        if d:
            self.input_edit.setText(d)
            self._prepared_info = None

    def _browse_package_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择上架数据包 ZIP", "", "ZIP (*.zip)")
        if path:
            self.input_edit.setText(path)
            self._prepared_info = None

    # ─────────────────────────── 执行 ───────────────────────────
    def _validate_package(self):
        path = self.input_edit.text().strip()
        shop_key = self.shop_combo.currentData()
        if not path:
            self._page.show_warning("请先选择上架数据包。")
            return
        self._prepared_info = None
        self.package_summary.setText("正在校验…")
        w = ValidateWorker(path, shop_key)
        self._validate_worker = self._page.track_worker(w)
        w.finished.connect(self._on_validated)
        w.error.connect(self._on_validate_error)
        w.start()

    def _on_validated(self, data):
        self._prepared_info = data.get("info")
        warns = "；".join(data.get("warnings") or []) or "无"
        self.package_summary.setText(
            f"完成： 店铺：{data['shop_name']} | 标题：{data['title'] or '（未命名）'} | "
            f"SKU：{data['sku_count']} | 主图：{data['main_images']} | "
            f"详情：{data['detail_images']} | SKU图：{data['sku_images']}\n警告：{warns}")
        self.log_view.append(f"[校验] 数据包校验通过：{data['title'] or '（未命名商品）'}，{data['sku_count']} 个SKU")  # noqa: E501

    def _on_validate_error(self, msg):
        self.package_summary.setText(f"失败： 校验失败：{msg}")
        self.log_view.append(f"[校验] 失败：{msg}")

    def _start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        path = self.input_edit.text().strip()
        shop_key = self.shop_combo.currentData()
        if not path:
            self._page.show_warning("请先选择上架数据包。")
            return
        if self._prepared_info is None:
            self._page.show_warning("请先点击「校验」，校验通过后再开始。")
            return
        cfg = self._collect_cfg()
        al_config.save_config(cfg)
        self.log_view.clear()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        w = AutoListingWorker(
            path, shop_key, cfg, self.chk_publish.isChecked(),
            prepared_info=self._prepared_info,
        )
        self._worker = self._page.track_worker(w)
        w.progress.connect(self._on_progress)
        w.finished.connect(self._on_finished)
        w.error.connect(self._on_error)
        w.start()
        self._check_cdp()

    def _stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self.log_view.append("[停止] 已请求停止，当前步骤完成后退出…")
            self.btn_stop.setEnabled(False)

    def _on_progress(self, stage, msg):
        self.log_view.append(f"[{stage}] {msg}")
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())  # noqa: E501

    def _on_finished(self, result):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._worker = None
        msg = f"任务完成：草稿保存={'成功' if result.get('saved') else '未确认'}；结果目录：{result.get('result_dir')}"  # noqa: E501
        self.log_view.append(f"[完成] {msg}")
        self._page.show_info(msg)
        self._check_cdp()

    def _on_error(self, msg):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._worker = None
        self.log_view.append(f"[错误] {msg}")
        self._page.show_error(msg)

    def refresh(self):
        self._check_cdp()
