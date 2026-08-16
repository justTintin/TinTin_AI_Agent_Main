# -*- coding: utf-8 -*-
"""爆款仿制（Viral Clone）：链接/素材 ID → 拆解结构 → 复刻脚本。

- 拆解/复刻走服务端 /viral/clone/analyze + /viral/clone/plan（flow 一条调用优先）
- 视频下载一律由客户端素材浏览器完成（不走服务端）：填链接 → 点
  「在素材浏览器中下载」→ 下载入库后填素材 ID
- 生成（三替换）/组装（剪辑）为占位按钮：服务端 E-3.0 节点引擎就绪后开放

ViralClonePage：可复用 QWidget 组件（工作台对话框 / 一键成片 Tab 均使用）；
ViralCloneDialog：对话框包装（工作台「爆款仿制」卡片入口）。
"""
import json

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextBrowser, QGroupBox, QGridLayout, QMessageBox, QApplication, QWidget,
)
from utils.gui_icons import mdi_button
from utils.logger_utils import log
from utils import viral_clone_client as vcc
from gui.searchable_combo import SearchableComboBox


class CloneWorker(QThread):
    """后台执行 run_clone（拆解 + 复刻规划），进度经 signal 回传 UI 线程。"""
    progress = Signal(str)
    result = Signal(object)

    def __init__(self, video_ref, product_info, parent=None):
        super().__init__(parent)
        self.video_ref = video_ref
        self.product_info = product_info

    def run(self):
        try:
            res = vcc.run_clone(self.video_ref, self.product_info,
                                on_log=self.progress.emit)
        except Exception as e:
            log.exception(f"[仿爆款] 后台执行异常: {e}")
            res = {"ok": False, "error": f"客户端异常：{e}"}
        self.result.emit(res)


class _ProductLoader(QThread):
    """后台加载产品库条目（服务端 /grouped 优先，失败返回空）。"""
    loaded = Signal(object)

    def run(self):
        mgr = None
        items = []
        try:
            from utils.product_library_manager import ProductLibraryManager
            mgr = ProductLibraryManager()
            items = list(mgr.all_items())[:300]
        except Exception as e:
            log.warning(f"[仿爆款] 产品库加载失败: {e}")
        self.loaded.emit((mgr, items))


class ViralClonePage(QWidget):
    """爆款仿制页面组件：来源 + 产品 → 拆解 → 复刻脚本（生成/组装占位）。

    可嵌入任意容器（一键成片 Tab / 对话框）。show_close=True 时底部显示关闭按钮
    （对话框模式），作为页面嵌入时不显示。
    """

    def __init__(self, parent_widget=None, main_window=None, show_close=False):
        super().__init__(parent_widget)
        self.main_window = main_window
        self.show_close = show_close
        self._result = None
        self._product_mgr = None
        self._worker = None
        self._loader = None
        self.build()

    # ── UI ────────────────────────────────────────────────────────────
    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("爆款仿制（Viral Clone）")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)
        sub = QLabel("给一条爆款视频链接或素材 ID → 自动拆解结构（镜头/文案/节奏）→ 生成复刻脚本（保留结构、替换本店产品）。")
        sub.setStyleSheet("color:#8b93a3; font-size:12px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # 爆款视频来源
        src_box = QGroupBox("① 爆款视频来源（链接 / 素材 ID 二选一）")
        src_lay = QGridLayout(src_box)
        src_lay.setSpacing(8)
        self.edit_link = QLineEdit()
        self.edit_link.setPlaceholderText("抖音 / B站 / YouTube / 快手 等链接")
        src_lay.addWidget(QLabel("链接："), 0, 0)
        link_row = QHBoxLayout()
        link_row.setSpacing(6)
        link_row.addWidget(self.edit_link, 1)
        self.btn_download = mdi_button("在素材浏览器中下载", "download")
        self.btn_download.setToolTip("打开客户端素材浏览器下载该视频；下载入库后填素材 ID 继续（下载不走服务端）")
        self.btn_download.clicked.connect(self._on_download)
        link_row.addWidget(self.btn_download)
        src_lay.addLayout(link_row, 0, 1)
        self.edit_material = QLineEdit()
        self.edit_material.setPlaceholderText("素材库 ID（数字；素材浏览器里可查）")
        src_lay.addWidget(QLabel("素材 ID："), 1, 0)
        src_lay.addWidget(self.edit_material, 1, 1)
        hint = QLabel("提示：视频下载一律由客户端素材浏览器完成（不走服务端）。链接填好后点「在素材浏览器中下载」，下载入库后填素材 ID；服务端 output 区路径可直接填。")
        hint.setStyleSheet("color:#6b7280; font-size:11px;")
        hint.setWordWrap(True)
        src_lay.addWidget(hint, 2, 0, 1, 2)
        root.addWidget(src_box)

        # 本店产品
        prod_box = QGroupBox("② 本店产品（替换爆款中的产品）")
        prod_lay = QGridLayout(prod_box)
        prod_lay.setSpacing(8)
        self.combo_product = SearchableComboBox(placeholder="搜索选择本店产品…")
        prod_lay.addWidget(QLabel("产品："), 0, 0)
        prod_lay.addWidget(self.combo_product, 0, 1)
        self.edit_product = QLineEdit()
        self.edit_product.setPlaceholderText("或手动输入产品描述（品牌/型号/核心卖点）…")
        prod_lay.addWidget(QLabel("自定义："), 1, 0)
        prod_lay.addWidget(self.edit_product, 1, 1)
        root.addWidget(prod_box)

        # 操作
        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.btn_run = mdi_button("拆解并复刻", "fire")
        self.btn_run.setObjectName("primary_button")
        self.btn_run.setFixedHeight(34)
        self.btn_run.clicked.connect(self._on_run)
        ops.addWidget(self.btn_run)
        self.btn_generate = mdi_button("生成素材（占位）", "creation")
        self.btn_generate.setToolTip("三替换素材生成：服务端 E-3.0 节点引擎就绪后开放")
        self.btn_generate.clicked.connect(self._on_generate)
        ops.addWidget(self.btn_generate)
        self.btn_montage = mdi_button("组装成片（占位）", "film")
        self.btn_montage.setToolTip("复刻素材组装：服务端 E-3.0 节点引擎就绪后开放")
        self.btn_montage.clicked.connect(self._on_montage)
        ops.addWidget(self.btn_montage)
        self.btn_copy = mdi_button("复制复刻脚本", "content-copy")
        self.btn_copy.setToolTip("把当前复刻脚本 JSON 复制到剪贴板")
        self.btn_copy.clicked.connect(self._on_copy)
        ops.addWidget(self.btn_copy)
        ops.addStretch(1)
        root.addLayout(ops)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#8b93a3; font-size:12px;")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.output = QTextBrowser()
        self.output.setOpenExternalLinks(True)
        self.output.setStyleSheet(
            "QTextBrowser { background:#12141d; border:1px solid #2c3344;"
            " border-radius:8px; padding:10px; font-family:Consolas,monospace; font-size:12px; }"
        )
        root.addWidget(self.output, 1)

        if self.show_close:
            self.btn_close = mdi_button("关闭", "close")
            self.btn_close.clicked.connect(self._on_close)
            root.addWidget(self.btn_close, 0, Qt.AlignRight)

        self._load_products()

    def _on_close(self):
        """对话框模式下关闭（页面嵌入模式无关闭按钮）。"""
        dlg = self.window()
        if isinstance(dlg, QDialog):
            dlg.reject()

    def _load_products(self):
        self._loader = _ProductLoader(self)
        self._loader.loaded.connect(self._on_products_loaded)
        self._loader.start()

    def _on_products_loaded(self, payload):
        mgr, items = payload
        self._product_mgr = mgr
        self.combo_product.setItems([
            (f"{it.get('brand','')} / {it.get('model') or it.get('name') or it.get('title','')}".strip(" /"),
             it)
            for it in items if it.get("brand") or it.get("model") or it.get("name") or it.get("title")
        ])
        if items:
            self.lbl_status.setText(f"就绪（产品库已加载 {len(items)} 条）")
        else:
            self.lbl_status.setText("就绪（产品库为空，可使用自定义产品描述）")

    # ── 下载（客户端素材浏览器，不走服务端）─────────────────────────
    def _on_download(self):
        url = self.edit_link.text().strip()
        ok, msg, dl_dir = vcc.open_in_asset_browser(url or None, topic="爆款仿制")
        self.lbl_status.setText(msg)
        self.output.append(f"\n{msg}")
        if ok and dl_dir:
            self.output.append(f"下载目录：{dl_dir}")
        if ok:
            self.output.append("下载完成后在素材浏览器/素材库中入库，回到本页填素材 ID 继续")

    # ── 输入组装 ──────────────────────────────────────────────────────
    def _video_ref(self):
        link = self.edit_link.text().strip()
        mid = self.edit_material.text().strip()
        if mid:
            return mid
        return link

    def _product_info(self):
        item = self.combo_product.currentData()
        if item is not None and self._product_mgr is not None:
            try:
                return self._product_mgr.to_prompt_text(item)
            except Exception:
                pass
        custom = self.edit_product.text().strip()
        if custom:
            return custom
        return ""

    def _set_running(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_generate.setEnabled(not running)
        self.btn_montage.setEnabled(not running)

    # ── 动作 ──────────────────────────────────────────────────────────
    def _on_run(self):
        ref = self._video_ref()
        if not ref:
            QMessageBox.warning(self, "缺少输入", "请填写爆款视频链接或素材 ID")
            return
        if not self._product_info():
            QMessageBox.warning(self, "缺少产品", "请选择本店产品或填写自定义产品描述")
            return
        self._set_running(True)
        self.lbl_status.setText("正在拆解爆款…（链接需先下载入库，可能较久）")
        self.output.clear()
        self._result = None
        self._worker = CloneWorker(ref, self._product_info(), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_result)
        self._worker.start()

    def _on_progress(self, msg):
        self.lbl_status.setText(msg)
        self.output.append(f"{msg}")

    def _on_result(self, res):
        self._set_running(False)
        self._result = res
        if not res.get("ok"):
            if res.get("need_download"):
                msg = (res.get("error") or "请先在客户端素材浏览器中下载视频") + "；点「在素材浏览器中下载」完成下载入库后，填素材 ID 重试"
                self.lbl_status.setText(msg)
                self.output.append(f"\n{msg}")
            elif res.get("need_login") or res.get("captcha"):
                self.lbl_status.setText(res.get("error") or "抖音风控，请先完成登录/验证")
                self.output.append(f"\n{res.get('error') or '抖音风控'}")
            else:
                self.lbl_status.setText(f"{res.get('error') or '执行失败'}")
                self.output.append(f"\n{res.get('error') or '执行失败'}")
            return
        self.lbl_status.setText("拆解 + 复刻脚本完成（生成/组装待服务端 E-3.0 开放）")
        self._render_result(res)

    def _render_result(self, res):
        parts = []
        parts.append("══ 爆款结构（structure）══")
        parts.append(json.dumps(res.get("structure") or {}, ensure_ascii=False, indent=2))
        parts.append("")
        parts.append("══ 复刻脚本（script）══")
        parts.append(json.dumps(res.get("script") or {}, ensure_ascii=False, indent=2))
        self.output.setPlainText("\n".join(parts))

    def _on_generate(self):
        if not self._result or not self._result.get("script"):
            QMessageBox.information(self, "占位", "请先执行「拆解并复刻」拿到复刻脚本")
            return
        res = vcc.generate(self._result["script"])
        self.lbl_status.setText(f"生成素材：{res['reason']}")
        self.output.append(f"\n生成素材（占位）：{res['reason']}")

    def _on_montage(self):
        if not self._result:
            QMessageBox.information(self, "占位", "请先执行「拆解并复刻」")
            return
        res = vcc.montage({"script": self._result.get("script")})
        self.lbl_status.setText(f"组装成片：{res['reason']}")
        self.output.append(f"\n组装成片（占位）：{res['reason']}")

    def _on_copy(self):
        if not self._result or not self._result.get("script"):
            QMessageBox.information(self, "复制", "暂无可复制的复刻脚本")
            return
        QApplication.clipboard().setText(
            json.dumps(self._result["script"], ensure_ascii=False, indent=2))
        self.lbl_status.setText("复刻脚本已复制到剪贴板")


class ViralCloneDialog(QDialog):
    """爆款仿制对话框（工作台「爆款仿制」卡片入口），内部复用 ViralClonePage。"""

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("爆款仿制（Viral Clone）")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.page = ViralClonePage(self, main_window=main_window, show_close=True)
        lay.addWidget(self.page)
