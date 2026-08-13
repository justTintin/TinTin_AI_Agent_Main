# -*- coding: utf-8 -*-
"""技能安装/管理弹窗。

支持从含 SKILL.md 的文件夹或 zip 包安装本地技能；安装后由工作台
把技能合并进智能体快捷条与斜杠菜单，使用时按智能体同一方式唤起。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QMessageBox,
)

from utils.logger_utils import log
from utils.thread_worker import TaskWorker


class SkillManagerDialog(QDialog):
    skillsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技能管理")
        self.setModal(True)
        self.resize(560, 420)
        self._worker = None
        self._skills = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(QLabel(
            "本地技能：安装后与智能体一样出现在工作台快捷条和斜杠菜单；"
            "支持单个 .md、含 SKILL.md 的文件夹或 ZIP 包。"))

        self.list_skills = QListWidget()
        self.list_skills.setAlternatingRowColors(True)
        v.addWidget(self.list_skills, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_dir = QPushButton("📁 从文件夹安装")
        btn_dir.setCursor(Qt.PointingHandCursor)
        btn_dir.clicked.connect(self._install_dir)
        row.addWidget(btn_dir)
        btn_md = QPushButton("📄 从 .md 安装")
        btn_md.setCursor(Qt.PointingHandCursor)
        btn_md.clicked.connect(self._install_md)
        row.addWidget(btn_md)
        btn_zip = QPushButton("🗜️ 从 ZIP 安装")
        btn_zip.setCursor(Qt.PointingHandCursor)
        btn_zip.clicked.connect(self._install_zip)
        row.addWidget(btn_zip)
        btn_remove = QPushButton("卸载选中")
        btn_remove.setCursor(Qt.PointingHandCursor)
        btn_remove.clicked.connect(self._uninstall_selected)
        row.addWidget(btn_remove)
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
        from utils import skill_manager as sm
        return sm.list_skills()

    def _on_loaded(self, entries):
        self._skills = entries or []
        self.list_skills.clear()
        for s in self._skills:
            name = s.get("name") or s.get("id") or "未命名技能"
            desc = s.get("description") or ""
            version = s.get("version") or ""
            label = f"{name}  v{version}" if version else name
            item = QListWidgetItem(f"🧩 {label}")
            item.setToolTip(desc)
            item.setData(Qt.UserRole, s.get("id") or "")
            self.list_skills.addItem(item)
        if not self._skills:
            self.list_skills.addItem("（暂无已安装技能）")

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
        return sm.install_skill(src, overwrite=True)

    def _on_installed(self, entry):
        name = (entry or {}).get("name") or "技能"
        QMessageBox.information(self, "安装完成", f"✅ 已安装技能：{name}")
        self._reload()
        self.skillsChanged.emit()

    def _on_install_error(self, err):
        QMessageBox.warning(self, "安装失败", f"技能安装失败：\n{err}")

    def _uninstall_selected(self):
        item = self.list_skills.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个技能。")
            return
        skill_id = item.data(Qt.UserRole) or ""
        name = item.text().replace("🧩 ", "")
        if not skill_id:
            return
        if QMessageBox.question(
                self, "确认卸载", f"确定卸载技能「{name}」吗？") != QMessageBox.Yes:
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
