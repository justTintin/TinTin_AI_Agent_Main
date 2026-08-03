# -*- coding: utf-8 -*-
"""
数据备份 / 还原 / 迁移页。

基于 utils/data_registry 的统一登记表：
- 一键备份成 zip（可选含密钥 / 含产出）
- 从 zip 还原（还原前自动安全备份当前数据）
- 素材挂载根路径批量重定位（换机器迁移用）
"""
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
    QCheckBox, QFileDialog, QProgressBar, QTextEdit,
)
from PySide6.QtCore import Signal

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils import backup_manager as bm
from utils.data_registry import summarize
from config.paths import BACKUP_DIR


from utils.file_dialog_utils import pick_file
from utils.gui_icons import mdi_button
def _fmt(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{int(n)}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


class BackupWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, include_secrets, include_outputs):
        super().__init__()
        self.include_secrets = include_secrets; self.include_outputs = include_outputs

    def do_work(self):
        out = bm.backup(include_secrets=self.include_secrets,
                        include_outputs=self.include_outputs, progress=self.phase.emit)
        self.finished.emit(out)


class RestoreWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(int, str)

    def __init__(self, zip_path):
        super().__init__()
        self.zip_path = zip_path

    def do_work(self):
        n, safe = bm.restore(self.zip_path, progress=self.phase.emit)
        self.finished.emit(n, safe)


class BackupPage(BasePage):
    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(14)

        hdr = QHBoxLayout()
        heading = QLabel("💾 数据备份 / 还原 / 迁移")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        sub = QLabel("配置(密钥) + 业务数据(产品资料/我的知识库/素材索引/账号/声音样本) 一键备份还原；素材外部目录支持迁移重定位。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        sub.setMaximumWidth(920)  # 限宽换行，右侧留白避让资源监控
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        # 数据盘点
        inv = QFrame(); inv.setObjectName("card")
        il = QVBoxLayout(inv); il.setContentsMargins(20, 14, 20, 14)
        il.addWidget(QLabel("📋 当前数据盘点"))
        self.inv_text = QTextEdit(); self.inv_text.setReadOnly(True); self.inv_text.setFixedHeight(170)
        il.addWidget(self.inv_text)
        root.addWidget(inv)

        # 备份
        bk = QFrame(); bk.setObjectName("card")
        bl = QVBoxLayout(bk); bl.setContentsMargins(20, 14, 20, 14); bl.setSpacing(8)
        bl.addWidget(QLabel("📦 备份"))
        opt = QHBoxLayout()
        self.chk_secrets = QCheckBox("包含密钥/登录态(换自己机器勾选；给别人请取消)"); self.chk_secrets.setChecked(True)
        opt.addWidget(self.chk_secrets)
        self.chk_outputs = QCheckBox("包含生成产出outputs(较大)"); self.chk_outputs.setChecked(False)
        opt.addWidget(self.chk_outputs); opt.addStretch()
        bl.addLayout(opt)
        brow = QHBoxLayout()
        self.btn_backup = QPushButton("📦 立即备份"); self.btn_backup.setObjectName("primary_button")
        self.btn_backup.clicked.connect(self._backup)
        brow.addWidget(self.btn_backup)
        btn_dir = QPushButton("打开备份目录"); btn_dir.setObjectName("secondary_button")
        btn_dir.clicked.connect(self._open_backup_dir)
        brow.addWidget(btn_dir); brow.addStretch()
        bl.addLayout(brow)
        root.addWidget(bk)

        # 还原
        rs = QFrame(); rs.setObjectName("card")
        rl = QVBoxLayout(rs); rl.setContentsMargins(20, 14, 20, 14); rl.setSpacing(8)
        rl.addWidget(QLabel("♻️ 还原（会先自动安全备份当前数据，再用所选 zip 覆盖）"))
        rr = QHBoxLayout()
        self.in_zip = QLineEdit(); self.in_zip.setPlaceholderText("选择备份 zip…")
        rr.addWidget(self.in_zip, 1)
        btn_br = mdi_button("浏览…", "folder"); btn_br.setObjectName("secondary_button"); btn_br.clicked.connect(self._browse_zip)
        rr.addWidget(btn_br)
        self.btn_restore = QPushButton("♻️ 还原"); self.btn_restore.setObjectName("secondary_button")
        self.btn_restore.clicked.connect(self._restore)
        rr.addWidget(self.btn_restore)
        rl.addLayout(rr)
        root.addWidget(rs)

        # 素材路径重定位
        rc = QFrame(); rc.setObjectName("card")
        cl = QVBoxLayout(rc); cl.setContentsMargins(20, 14, 20, 14); cl.setSpacing(8)
        cl.addWidget(QLabel("📁 素材根路径重定位（迁移到新机器/换盘符后，把挂载目录旧前缀换成新前缀）"))
        cr = QHBoxLayout()
        self.in_old = QLineEdit(); self.in_old.setPlaceholderText(r"旧前缀，如 D:\素材")
        cr.addWidget(self.in_old, 1)
        cr.addWidget(QLabel("→"))
        self.in_new = QLineEdit(); self.in_new.setPlaceholderText(r"新前缀，如 E:\我的素材")
        cr.addWidget(self.in_new, 1)
        btn_rl = QPushButton("重定位"); btn_rl.setObjectName("secondary_button"); btn_rl.clicked.connect(self._relocate)
        cr.addWidget(btn_rl)
        cl.addLayout(cr)
        root.addWidget(rc)

        srow = QHBoxLayout()
        self.status = QLabel(""); self.status.setObjectName("muted_text")
        srow.addWidget(self.status, 1)
        self.pbar = QProgressBar(); self.pbar.setVisible(False); self.pbar.setRange(0, 0); self.pbar.setMaximumWidth(160)
        srow.addWidget(self.pbar)
        root.addLayout(srow)
        root.addStretch()

        self._refresh_inventory()

    def _refresh_inventory(self):
        lines = []
        for it in summarize():
            mark = "🔑" if it["sensitive"] else "  "
            ok = "✅" if it["exists"] else "—"
            lines.append(f"{ok} {mark} [{it['category']:8}] {it['label']}： {_fmt(it['size'])}")
        self.inv_text.setPlainText("\n".join(lines))

    # ---------- 备份 ----------
    def _backup(self):
        self.btn_backup.setEnabled(False); self.pbar.setVisible(True)
        w = BackupWorker(self.chk_secrets.isChecked(), self.chk_outputs.isChecked())
        w.phase.connect(self.status.setText)
        w.finished.connect(self._backup_done)
        w.error.connect(lambda e: (self.btn_backup.setEnabled(True), self.pbar.setVisible(False),
                                   self.show_error(str(e), "备份失败")))
        self.track_worker(w); w.start()

    def _backup_done(self, path):
        self.btn_backup.setEnabled(True); self.pbar.setVisible(False)
        self.status.setText(f"✅ 已备份：{path}")
        self.show_info(f"备份完成：\n{path}")

    def _open_backup_dir(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.name == "nt":
            os.startfile(BACKUP_DIR)  # noqa

    # ---------- 还原 ----------
    def _browse_zip(self):
        f, _ = pick_file(self.parent_widget, "选择备份 zip", BACKUP_DIR, "备份 (*.zip)")
        if f:
            self.in_zip.setText(f)

    def _restore(self):
        z = self.in_zip.text().strip()
        if not z or not os.path.isfile(z):
            self.show_warning("请先选择有效的备份 zip。")
            return
        mani = bm.read_manifest(z)
        info = f"备份时间：{mani.get('created')}\n含密钥：{mani.get('include_secrets')}\n项目：{mani.get('items')}" if mani else "（无 manifest，可能非本工具备份）"
        if not self.confirm(f"将用此备份覆盖当前数据：\n{z}\n\n{info}\n\n还原前会自动安全备份当前数据。确定继续？", "确认还原"):
            return
        self.btn_restore.setEnabled(False); self.pbar.setVisible(True)
        w = RestoreWorker(z)
        w.phase.connect(self.status.setText)
        w.finished.connect(self._restore_done)
        w.error.connect(lambda e: (self.btn_restore.setEnabled(True), self.pbar.setVisible(False),
                                   self.show_error(str(e), "还原失败")))
        self.track_worker(w); w.start()

    def _restore_done(self, n, safe):
        self.btn_restore.setEnabled(True); self.pbar.setVisible(False)
        self._refresh_inventory()
        self.status.setText(f"✅ 已还原 {n} 个文件")
        self.show_info(f"还原完成，恢复 {n} 个文件。\n当前数据已安全备份到：\n{safe}\n\n建议重启软件以加载新数据。")

    # ---------- 素材重定位 ----------
    def _relocate(self):
        try:
            n = bm.relocate_media_root(self.in_old.text(), self.in_new.text())
        except Exception as e:
            self.show_error(str(e), "重定位失败")
            return
        self._refresh_inventory()
        self.show_info(f"已重定位 {n} 个挂载目录的根路径。" + ("\n建议到素材管理刷新查看。" if n else "\n（没有匹配旧前缀的目录）"))
