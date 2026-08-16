# -*- coding: utf-8 -*-
"""技能安装/管理弹窗。

表格列表：复选框 | 技能名称 | 是否内置 | 是否已上传。
右键技能行：卸载 / 上传到服务端（技能管理在服务端）；
内置技能（客户端功能）不允许卸载；「已上传」对比服务端 GET /skills 清单。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QPushButton, QFileDialog, QMessageBox,
)

from utils.logger_utils import log
from utils.thread_worker import TaskWorker


class SkillManagerDialog(QDialog):
    skillsChanged = Signal()

    _COL_CHECK = 0
    _COL_NAME = 1
    _COL_BUILTIN = 2
    _COL_UPLOADED = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技能管理")
        self.setModal(True)
        self.resize(640, 440)
        self._worker = None
        self._skills = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(QLabel(
            "技能：安装后与智能体一样出现在工作台快捷条和斜杠菜单；"
            "支持单个 .md、含 SKILL.md 的文件夹或 ZIP 包；"
            "右键技能行可卸载或上传到服务端（技能管理在服务端）；"
            "内置技能（如爆款视频下载）属客户端功能，不允许卸载。"))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["", "技能", "内置", "已上传"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self._COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self._COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(self._COL_BUILTIN, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self._COL_UPLOADED, QHeaderView.ResizeToContents)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_dir = QPushButton(" 从文件夹安装")
        btn_dir.setCursor(Qt.PointingHandCursor)
        btn_dir.clicked.connect(self._install_dir)
        row.addWidget(btn_dir)
        btn_md = QPushButton(" 从 .md 安装")
        btn_md.setCursor(Qt.PointingHandCursor)
        btn_md.clicked.connect(self._install_md)
        row.addWidget(btn_md)
        btn_zip = QPushButton(" 从 ZIP 安装")
        btn_zip.setCursor(Qt.PointingHandCursor)
        btn_zip.clicked.connect(self._install_zip)
        row.addWidget(btn_zip)
        row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setObjectName("secondary_button")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        v.addLayout(row)

        self._reload()

    def _reload(self):
        self._worker = TaskWorker(self._load_skills)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(lambda e: log.warning(f"[技能管理] 加载失败: {e}"))
        self._worker.start()

    def _load_skills(self):
        """返回 (本地技能列表, 服务端已登记 id 集合)。"""
        from utils import skill_manager as sm
        entries = sm.list_skills()
        uploaded = set()
        try:
            for s in (sm.server_skills(timeout=6) or []):
                sid = s.get("skill_id") or s.get("id") or ""
                if sid:
                    uploaded.add(sid)
        except Exception as e:
            log.warning(f"[技能管理] 服务端技能清单获取失败: {e}")
        return entries, uploaded

    def _on_loaded(self, payload):
        entries, uploaded = payload
        self._skills = entries or []
        uploaded = uploaded or set()
        self.table.setRowCount(0)
        for s in self._skills:
            sid = s.get("id") or ""
            name = s.get("name") or sid or "未命名技能"
            version = s.get("version") or ""
            label = f"{name}  v{version}" if version else name
            from utils import skill_manager as sm
            is_b = sm.is_builtin(sid)
            is_up = sid in uploaded

            row = self.table.rowCount()
            self.table.insertRow(row)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, sid)
            self.table.setItem(row, self._COL_CHECK, chk)

            name_item = QTableWidgetItem(" " + label)
            name_item.setData(Qt.UserRole, sid)
            name_item.setToolTip(s.get("description") or "")
            self.table.setItem(row, self._COL_NAME, name_item)

            b_item = QTableWidgetItem("是" if is_b else "否")
            b_item.setTextAlignment(Qt.AlignCenter)
            if is_b:
                b_item.setToolTip("内置技能（客户端功能），不允许卸载")
            self.table.setItem(row, self._COL_BUILTIN, b_item)

            u_item = QTableWidgetItem("是" if is_up else "否")
            u_item.setTextAlignment(Qt.AlignCenter)
            if not is_up:
                u_item.setToolTip("未上传：右键本行选择「上传到服务端」登记")
            self.table.setItem(row, self._COL_UPLOADED, u_item)

        if not self._skills:
            self.table.setRowCount(1)
            empty = QTableWidgetItem("（暂无已安装技能）")
            empty.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(0, self._COL_NAME, empty)

    # ── 右键菜单：卸载 / 上传 ─────────────────────────────────────────
    def _row_at(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return -1
        row = idx.row()
        if row < 0 or row >= self.table.rowCount():
            return -1
        return row

    def _row_skill_id(self, row):
        item = self.table.item(row, self._COL_NAME)
        if item is None:
            return ""
        return item.data(Qt.UserRole) or ""

    def _on_context_menu(self, pos):
        row = self._row_at(pos)
        if row < 0:
            return
        skill_id = self._row_skill_id(row)
        if not skill_id:
            return
        name_item = self.table.item(row, self._COL_NAME)
        name = (name_item.text() or "").replace(" ", "")
        self.table.selectRow(row)
        menu = QMenu(self)
        act_uninstall = menu.addAction("卸载技能")
        act_upload = menu.addAction("上传到服务端")
        chosen = menu.exec_(self.table.mapToGlobal(pos))
        if chosen == act_uninstall:
            self._uninstall_one(skill_id, name)
        elif chosen == act_upload:
            self._upload_one(skill_id)

    def _uninstall_one(self, skill_id, name):
        """卸载单个技能（右键触发）；内置技能拒绝。"""
        from utils import skill_manager as sm
        if sm.is_builtin(skill_id):
            QMessageBox.warning(self, "内置技能",
                                f"技能「{name}」是内置技能（客户端功能），不允许卸载。")
            return
        if QMessageBox.question(self, "确认卸载",
                                f"确定卸载技能「{name}」吗？") != QMessageBox.Yes:
            return
        self._worker = TaskWorker(self._run_remove, skill_id)
        self._worker.finished.connect(self._on_removed)
        self._worker.error.connect(lambda e: QMessageBox.warning(self, "卸载失败", str(e)))
        self._worker.start()

    @staticmethod
    def _run_remove(skill_id):
        from utils import skill_manager as sm
        return sm.remove_skill(skill_id)

    def _on_removed(self, ok):
        if ok:
            self._reload()
            self.skillsChanged.emit()

    # ── 上传到服务端（右键触发）───────────────────────────────────────
    def _upload_one(self, skill_id):
        self._worker = TaskWorker(self._run_upload, [skill_id])
        self._worker.finished.connect(self._on_uploaded)
        self._worker.error.connect(lambda e: QMessageBox.warning(self, "上传失败", str(e)))
        self._worker.start()

    @staticmethod
    def _run_upload(skill_ids):
        from utils import skill_manager as sm
        entries = {s.get("id"): s for s in sm.list_skills()}
        results = []
        for sid in (skill_ids or []):
            entry = entries.get(sid)
            if not entry:
                results.append((sid, False, "本地未找到该技能"))
                continue
            ok = sm.register_skill(entry)
            results.append((sid, ok, "" if ok else "登记失败（服务端不可达或拒绝）"))
        return results

    def _on_uploaded(self, results):
        if not results:
            return
        ok_n = sum(1 for _sid, ok, _err in results if ok)
        fail = [(sid, err) for sid, ok, err in results if not ok]
        msg = f"已登记 {ok_n}/{len(results)} 个技能到服务端。"
        if fail:
            msg += "\n失败：" + "、".join(f"{sid}({err})" for sid, err in fail[:5])
        QMessageBox.information(self, "上传到服务端", msg)
        self._reload()
        self.skillsChanged.emit()

    # ── 安装 ──────────────────────────────────────────────────────────
    def _install_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择技能文件夹（需包含 SKILL.md）")
        if path:
            self._install(path)

    def _install_md(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择技能 .md 文件", "",
            "Markdown 技能 (*.md *.markdown);;所有文件 (*.*)")
        if path:
            self._install(path)

    def _install_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择技能 ZIP 包", "", "ZIP 文件 (*.zip);;所有文件 (*.*)")
        if path:
            self._install(path)

    def _install(self, src):
        self._worker = TaskWorker(self._run_install, src)
        self._worker.finished.connect(self._on_installed)
        self._worker.error.connect(self._on_install_error)
        self._worker.start()

    @staticmethod
    def _run_install(src):
        from utils import skill_manager as sm
        entry = sm.install_skill(src, overwrite=True)
        # 技能管理在服务端：安装后登记（GET /skills 统一返回）
        sm.register_skill(entry)
        return entry

    def _on_installed(self, entry):
        name = (entry or {}).get("name") or "技能"
        QMessageBox.information(self, "安装完成", f" 已安装技能：{name}")
        self._reload()
        self.skillsChanged.emit()

    def _on_install_error(self, err):
        QMessageBox.warning(self, "安装失败", f"技能安装失败：\n{err}")
