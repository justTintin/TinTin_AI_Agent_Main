# -*- coding: utf-8 -*-
"""
我的知识库 - 以「风格化」为核心的三区布局：

左上：风格化列表（按账号/内容类型/产品品类/行业垂类分组）
左下：选中风格化的风格画像详情 + 知识背景列表
右侧：此风格化参考的原始素材列表，双击素材弹出详情（含播放/蒸馏内容）

工具栏：同步/导入/提炼 + 知识背景管理入口
"""
import json
import os
import subprocess
import time as _time

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QFrame, QListWidget, QListWidgetItem, QMessageBox, QComboBox,
    QSplitter, QFormLayout, QDialog, QDialogButtonBox, QScrollArea, QWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QDesktopServices

from config.paths import KNOWLEDGE_MATERIALS_DIR
from utils.my_knowledge_manager import (
    MyKnowledgeManager, ENTRY_TYPES, REFERENCE_TYPE, STYLIZATION_TYPE, STYLE_DIMS,
)
from utils import asset_browser_client as abrowser
from utils.base_worker import BaseWorker
from utils import knowledge_distiller

from gui.base_page import BasePage


# ══════════════════════════════════════════════════════
#  Workers
# ══════════════════════════════════════════════════════

class _DistillWorker(BaseWorker):
    finished = Signal(tuple)
    progress = Signal(str)

    def __init__(self, manager, cfg):
        super().__init__()
        self.manager = manager
        self.cfg = cfg

    def do_work(self):
        res = knowledge_distiller.run_distillation(
            self.manager, self.cfg, progress_cb=lambda m: self.progress.emit(m))
        self.finished.emit(res)


class _RegenWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, cfg, dim, dim_value, samples):
        super().__init__()
        self._cfg = cfg
        self._dim = dim
        self._dim_value = dim_value
        self._samples = samples

    def do_work(self):
        content = knowledge_distiller._extract_style(
            self._cfg, self._dim, self._dim_value, self._samples)
        self.finished.emit(content)


# ══════════════════════════════════════════════════════
#  素材详情弹窗（双击素材触发）
# ══════════════════════════════════════════════════════

class SampleDetailDialog(QDialog):
    """原始素材详情：左侧视频播放器（WebEngineView在线播放，支持本地关联播放） | 右侧字幕文本、文案及风格化信息"""

    def __init__(self, sample, stylization=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("素材详情")
        self.resize(1400, 850)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        src = sample.get("source") or {}
        platform   = src.get("platformName") or src.get("platform", "")
        creator    = src.get("creator", "")
        date       = src.get("date", "")
        url        = src.get("url") or src.get("originalUrl") or ""
        media_path = src.get("media_path", "")
        has_media  = bool(media_path and os.path.exists(media_path))
        transcript = (sample.get("transcript") or "").strip()
        if src.get("is_liked"):
            badge = "👍 点赞"
        elif src.get("is_collected"):
            badge = "🔖 收藏"
        else:
            badge = "👤 关注"

        # ── 标题 ──
        title_lbl = QLabel(sample.get("name", "(未命名)"))
        f = QFont(); f.setBold(True); f.setPointSize(12)
        title_lbl.setFont(f)
        title_lbl.setWordWrap(True)
        root.addWidget(title_lbl)

        meta_parts = [p for p in [
            f"平台：{platform}", f"创作者：{creator}",
            f"类型：{badge}", f"日期：{date}",
        ] if p.split("：", 1)[1]]
        meta_lbl = QLabel("  |  ".join(meta_parts))
        meta_lbl.setObjectName("muted_text")
        root.addWidget(meta_lbl)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine); sep0.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep0)

        # ── 主体：左右分割 ──
        splitter = QSplitter(Qt.Horizontal)

        # ── 左侧：网页视频播放器与本地播放 ──
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(8)

        ll.addWidget(QLabel("📺 视频播放（网页在线预览 / 本地关联）："))
        
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            has_webengine = True
        except ImportError:
            has_webengine = False

        self.web_view = None
        if has_webengine and url:
            self.web_view = QWebEngineView()
            
            # Set standard Desktop User-Agent to prevent bots detection / JSON responses
            profile = self.web_view.page().profile()
            profile.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # Optimize Bilibili URL to use the embedded player
            target_url = url
            if "bilibili.com" in url:
                import re
                m = re.search(r'/(BV[a-zA-Z0-9]+)', url)
                if m:
                    bvid = m.group(1)
                    target_url = f"https://player.bilibili.com/player.html?bvid={bvid}&page=1&high_quality=1&danmaku=0"
            
            self.web_view.setUrl(QUrl(target_url))
            self.web_view.setMinimumHeight(480)
            ll.addWidget(self.web_view, 1)
        elif has_webengine and has_media:
            self.web_view = QWebEngineView()
            self.web_view.setUrl(QUrl.fromLocalFile(media_path))
            self.web_view.setMinimumHeight(480)
            ll.addWidget(self.web_view, 1)
        else:
            placeholder = QLabel("📺 暂无在线播放链接")
            placeholder.setObjectName("muted_text")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("border: 1px solid #3a3a3c; border-radius: 8px; background-color: #1c1c1e;")
            placeholder.setMinimumHeight(480)
            ll.addWidget(placeholder, 1)

        # 关联操作栏
        local_row = QHBoxLayout()
        if url:
            btn_open = QPushButton("🌐 在外部浏览器打开链接")
            btn_open.setObjectName("secondary_button")
            _u = url
            btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_u)))
            local_row.addWidget(btn_open)

        if has_media:
            btn_play = QPushButton("▶️ 用本地播放器播放")
            btn_play.setObjectName("primary_button")
            _mp = media_path
            btn_play.clicked.connect(lambda: os.startfile(_mp))
            local_row.addWidget(btn_play)
            
            btn_folder = QPushButton("📁 打开本地文件夹")
            btn_folder.setObjectName("secondary_button")
            btn_folder.clicked.connect(lambda: subprocess.Popen(f'explorer /select,"{_mp}"'))
            local_row.addWidget(btn_folder)
        else:
            lbl_no_local = QLabel("📥 本地媒体：未下载（您可通过上方窗口或外部链接直接在线预览）")
            lbl_no_local.setObjectName("muted_text")
            local_row.addWidget(lbl_no_local)
        
        ll.addLayout(local_row)
        splitter.addWidget(left)

        # ── 右侧：内容文本 + 字幕/转写 + 蒸馏贡献 ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(8)

        rl.addWidget(QLabel("📄 内容文本（标题 / 文案）："))
        content_box = QTextEdit()
        content_box.setReadOnly(True)
        content_box.setPlainText(sample.get("content", ""))
        content_box.setMaximumHeight(150)
        rl.addWidget(content_box)

        rl.addWidget(QLabel("📝 字幕 / 转写文本："))
        transcript_box = QTextEdit()
        transcript_box.setReadOnly(True)
        if transcript:
            transcript_box.setPlainText(transcript)
        else:
            transcript_box.setPlaceholderText(
                "（尚未转写 — 可在「参考素材」面板点「🎬 批量转文字」生成转写文本）")
        rl.addWidget(transcript_box, 1)

        if stylization:
            sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); sep3.setFrameShadow(QFrame.Sunken)
            rl.addWidget(sep3)
            dim_label = STYLE_DIMS.get(stylization.get("dim", ""), "风格")
            dim_val   = stylization.get("dim_value", "")
            rl.addWidget(QLabel(f"蒸馏贡献  →  「{dim_label}：{dim_val}」风格化"))
            
            style_preview = QTextEdit()
            style_preview.setReadOnly(True)
            style_preview.setPlainText(stylization.get("content", "")[:500] + "…")
            style_preview.setFixedHeight(200)
            rl.addWidget(style_preview)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 55)
        splitter.setStretchFactor(1, 45)
        root.addWidget(splitter, 1)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        root.addWidget(box)


# ══════════════════════════════════════════════════════
#  知识背景管理弹窗
# ══════════════════════════════════════════════════════

class KnowledgeBgDialog(QDialog):
    """管理手动知识背景条目（品牌调性/话术风格/禁用词等），不影响风格化。"""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("知识背景管理")
        self.resize(760, 500)
        self.current_id = None
        lay = QHBoxLayout(self)

        # 左：列表
        left = QFrame()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("知识背景条目"))
        self.kb_list = QListWidget()
        self.kb_list.itemClicked.connect(self._on_click)
        ll.addWidget(self.kb_list, 1)
        btn_new = QPushButton("➕ 新建")
        btn_new.clicked.connect(self._new_item)
        ll.addWidget(btn_new)
        lay.addWidget(left, 1)

        # 右：编辑表单
        right = QFrame()
        rl = QVBoxLayout(right)
        form = QFormLayout()
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("如：品牌极简科技调性")
        form.addRow("名称 *", self.inp_name)
        self.inp_type = QComboBox()
        self.inp_type.setEditable(True)
        kb_types = [t for t in ENTRY_TYPES if t not in (STYLIZATION_TYPE, REFERENCE_TYPE)]
        self.inp_type.addItems(kb_types)
        self.inp_type.setCurrentText("")
        form.addRow("类型", self.inp_type)
        rl.addLayout(form)
        rl.addWidget(QLabel("内容 *"))
        self.inp_content = QTextEdit()
        self.inp_content.setPlaceholderText(
            "例如：\n- 语气：专业但不端着，像懂行的朋友安利\n- 禁用：夸大功效词")
        rl.addWidget(self.inp_content, 1)
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setObjectName("primary_button")
        self.btn_save.clicked.connect(self._save)
        btn_row.addWidget(self.btn_save)
        btn_del = QPushButton("🗑️ 删除")
        btn_del.setObjectName("secondary_button")
        btn_del.clicked.connect(self._delete)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        self.status = QLabel("")
        self.status.setObjectName("muted_text")
        btn_row.addWidget(self.status)
        rl.addLayout(btn_row)
        lay.addWidget(right, 2)

        self._refresh()

    def _refresh(self):
        self.kb_list.clear()
        kb_items = [it for it in self.manager.all_items()
                    if it.get("type") not in (STYLIZATION_TYPE, REFERENCE_TYPE)]
        for it in kb_items:
            t = it.get("type", "")
            node = QListWidgetItem(f"[{t}] {it.get('name','')}")
            node.setData(Qt.UserRole, it.get("id"))
            self.kb_list.addItem(node)

    def _on_click(self, item):
        rid = item.data(Qt.UserRole)
        record = self.manager.get(rid)
        if not record:
            return
        self.current_id = rid
        self.inp_name.setText(record.get("name", ""))
        self.inp_type.setCurrentText(record.get("type", ""))
        self.inp_content.setPlainText(record.get("content", ""))
        self.btn_save.setText("💾 保存修改")

    def _new_item(self):
        self.current_id = None
        self.inp_name.clear()
        self.inp_type.setCurrentText("")
        self.inp_content.clear()
        self.btn_save.setText("💾 新建")

    def _save(self):
        name = self.inp_name.text().strip()
        etype = self.inp_type.currentText().strip()
        content = self.inp_content.toPlainText().strip()
        if not name or not content:
            self.status.setText("名称和内容不能为空。")
            return
        if self.current_id:
            ok, msg, _ = self.manager.update_item(self.current_id, name, etype, content)
        else:
            ok, msg, item = self.manager.add_item(name, etype, content)
            if ok:
                self.current_id = item["id"]
        self.status.setText(msg)
        if ok:
            self._refresh()
            self.btn_save.setText("💾 保存修改")

    def _delete(self):
        if not self.current_id:
            return
        reply = QMessageBox.question(self, "确认删除", "确定删除该条目？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if self.manager.remove_item(self.current_id):
            self.current_id = None
            self._new_item()
            self._refresh()


# ══════════════════════════════════════════════════════
#  批量视频转文字 Worker
# ══════════════════════════════════════════════════════

class _BatchTranscribeWorker(BaseWorker):
    progress = Signal(str)
    finished = Signal(int)   # count of newly transcribed samples

    def __init__(self, samples, model_name, manager):
        super().__init__()
        self._samples = samples
        self._model_name = model_name
        self._manager = manager

    def do_work(self):
        from utils import asr_client
        asr_url = asr_client.read_asr_url()
        if not asr_url:
            raise RuntimeError("未配置远程 ASR 服务地址，请在系统设置 → Whisper 填写远程 API 地址。")
        count = 0
        for sample in self._samples:
            src = sample.get("source") or {}
            media_path = src.get("media_path", "")
            if not media_path or not os.path.exists(media_path):
                continue
            if (sample.get("transcript") or "").strip():
                continue
            self.progress.emit(f"转写中：{os.path.basename(media_path)}…")
            try:
                segments = asr_client.transcribe_remote(media_path, asr_url, language="zh")
                sample["transcript"] = asr_client.segments_to_plain(segments)
                count += 1
            except Exception as e:
                self.progress.emit(f"⚠️ 跳过 {os.path.basename(media_path)}: {e}")
        if count:
            self._manager.save()
        self.finished.emit(count)


# ══════════════════════════════════════════════════════
#  主页面
# ══════════════════════════════════════════════════════

class MyKnowledgePage(BasePage):

    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.manager = MyKnowledgeManager()
        self.current_stylization = None   # 当前选中的风格化条目 dict
        self._style_filter_dim = None     # None = 全部

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(16)

        heading = QLabel("📚 我的知识库")
        heading.setObjectName("heading")
        root.addWidget(heading)

        subtitle = QLabel(
            "收藏/点赞 → 提炼「风格化」（写法画像）→ 用于脚本风格调整  |  "
            "知识背景：品牌调性/禁用词等手动维护"
        )
        subtitle.setObjectName("muted_text")
        root.addWidget(subtitle)

        # ── 工具栏 ──
        bar = QHBoxLayout()
        btn_sync = QPushButton("🌐 同步关注内容")
        btn_sync.setObjectName("secondary_button")
        btn_sync.setToolTip("打开素材浏览器，同步关注的创作者内容")
        btn_sync.clicked.connect(self._open_browser_sync)
        bar.addWidget(btn_sync)

        btn_import_raw = QPushButton("📋 导入收藏记录")
        btn_import_raw.setObjectName("secondary_button")
        btn_import_raw.setToolTip("从浏览器收藏/点赞记录导入原始素材（无需下载）")
        btn_import_raw.clicked.connect(self._import_kb_items)
        bar.addWidget(btn_import_raw)

        btn_import = QPushButton("🔄 同步记录素材")
        btn_import.setObjectName("secondary_button")
        btn_import.setToolTip("合并导入已下载素材 + 浏览器收藏记录")
        btn_import.clicked.connect(self._import_samples)
        bar.addWidget(btn_import)

        self.btn_distill = QPushButton("✨ 提炼风格化")
        self.btn_distill.setObjectName("primary_button")
        self.btn_distill.setToolTip(
            "把收藏/点赞样本按四个维度（账号/内容类型/产品品类/行业垂类）\n"
            "提炼为「风格化」写法画像（钩子/口吻/节奏/句式/收尾/禁忌）"
        )
        self.btn_distill.clicked.connect(self._distill)
        bar.addWidget(self.btn_distill)

        btn_kb = QPushButton("📚 知识背景")
        btn_kb.setObjectName("secondary_button")
        btn_kb.setToolTip("管理手动维护的知识背景条目（品牌调性/话术风格/禁用词等）")
        btn_kb.clicked.connect(self._open_kb_dialog)
        bar.addWidget(btn_kb)

        self.distill_status = QLabel("")
        self.distill_status.setObjectName("muted_text")
        bar.addWidget(self.distill_status)

        bar.addStretch(1)

        root.addLayout(bar)

        # ── 提炼状态信息栏 ──
        root.addWidget(self._build_status_bar())

        # ── 主体：左右分割 ──
        h_split = QSplitter(Qt.Horizontal)
        h_split.addWidget(self._build_left())
        h_split.addWidget(self._build_right())
        h_split.setStretchFactor(0, 2)
        h_split.setStretchFactor(1, 3)
        root.addWidget(h_split, 1)

        self.refresh_stylization_list()
        self._refresh_stats()

    # ══════════════ 提炼状态信息栏 ══════════════

    def _build_status_bar(self):
        """提炼状态栏：显示上次提炼信息 + 浏览器数据量，颜色示警需要重新提炼。"""
        bar = QFrame()
        bar.setObjectName("card")
        bar.setMaximumHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(20)

        # 上次提炼
        self.stat_last = QLabel("上次提炼：—")
        self.stat_last.setObjectName("muted_text")
        lay.addWidget(self.stat_last)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep1)

        # 知识库（已导入/已下载）
        self.stat_kb = QLabel("知识库：—")
        self.stat_kb.setObjectName("muted_text")
        lay.addWidget(self.stat_kb)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep2)

        # 浏览器数据（收藏记录 / 已下载素材 / 未导入差量）
        self.stat_browser = QLabel("浏览器：—")
        lay.addWidget(self.stat_browser)

        lay.addStretch()

        btn_refresh_stat = QPushButton("🔄 刷新数据统计")
        btn_refresh_stat.setObjectName("secondary_button")
        btn_refresh_stat.setFixedHeight(28)
        btn_refresh_stat.setToolTip("重新读取浏览器数据文件，更新未处理数量统计")
        btn_refresh_stat.clicked.connect(self._refresh_stats)
        lay.addWidget(btn_refresh_stat)

        return bar

    def _refresh_stats(self):
        """读取知识库 + 浏览器文件，计算数量差异，设置示警颜色。"""
        all_items = self.manager.all_items()
        stylizations = [it for it in all_items if it.get("type") == STYLIZATION_TYPE]
        samples      = [it for it in all_items if it.get("type") == REFERENCE_TYPE]

        # ── 上次提炼时间 ──
        if stylizations:
            last_ts  = max(it.get("updated_at", 0) for it in stylizations)
            days_ago = int((_time.time() - last_ts) / 86400)
            if days_ago == 0:
                time_str = "今天"
            elif days_ago == 1:
                time_str = "昨天"
            else:
                time_str = f"{days_ago} 天前"
            self.stat_last.setText(
                f"上次提炼：{time_str}  ·  风格化 {len(stylizations)} 条"
            )
        else:
            days_ago = 9999
            self.stat_last.setText("尚未提炼")

        # ── 知识库统计 ──
        downloaded_kb = sum(
            1 for it in samples
            if os.path.exists((it.get("source") or {}).get("media_path","") or "")
        )
        self.stat_kb.setText(
            f"知识库：{len(samples)} 条样本  ·  {downloaded_kb} 条已下载媒体"
        )

        # ── 浏览器数据文件 ──
        browser_items = 0
        browser_sync  = 0
        kb_items_path = os.path.join(KNOWLEDGE_MATERIALS_DIR, "kb_items.json")
        kb_sync_path  = os.path.join(KNOWLEDGE_MATERIALS_DIR, "kb_sync.json")
        if os.path.exists(kb_items_path):
            try:
                with open(kb_items_path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        browser_items = len(data)
            except Exception:
                pass
        if os.path.exists(kb_sync_path):
            try:
                with open(kb_sync_path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        browser_sync = len(data)
            except Exception:
                pass

        unimported = max(0, browser_items - len(samples))

        self.stat_browser.setText(
            f"浏览器：收藏记录 {browser_items} 条  ·  已下载素材 {browser_sync} 条"
            + (f"  ·  未导入 {unimported} 条" if unimported else "")
        )

        # ── 颜色示警 ──
        # 红色 = 紧急：大量未导入 或 从未提炼
        # 橙色 = 注意：有未导入记录 或 超过 7 天未提炼
        # 绿色 = 正常：数据同步且新鲜
        if not stylizations or unimported > 30 or days_ago > 14:
            color = "#F44336"  # 红色：急需提炼
        elif unimported > 0 or days_ago > 7:
            color = "#FF9800"  # 橙色：建议提炼
        else:
            color = "#4CAF50"  # 绿色：已同步

        self.stat_browser.setStyleSheet(f"color: {color};")
        tooltip = (
            f"浏览器共 {browser_items} 条收藏记录，"
            f"已导入知识库 {len(samples)} 条，"
            f"未导入 {unimported} 条。\n"
            f"距上次提炼 {days_ago if days_ago < 9999 else '∞'} 天。"
        )
        self.stat_browser.setToolTip(tooltip)

    # ══════════════ 左侧面板 ══════════════

    def _build_left(self):
        """左侧 = 上下垂直分割（风格化列表 / 详情+知识背景）+ 操作按钮"""
        outer = QWidget()
        outer.setMinimumWidth(420)
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(8)

        v_split = QSplitter(Qt.Vertical)

        # ── 左上：风格化列表 ──
        top_frame = QFrame()
        top_frame.setObjectName("card")
        tl = QVBoxLayout(top_frame)
        tl.setContentsMargins(12, 12, 12, 12)
        tl.setSpacing(8)

        top_title = QLabel("风格化")
        top_title.setObjectName("card_title")
        tl.addWidget(top_title)

        # 维度过滤标签行
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._style_filter_btns = {}
        _filter_opts = [
            ("全部", None), ("账号风格", "account"), ("内容类型", "content_type"),
            ("产品品类", "product_cat"), ("行业垂类", "industry"),
        ]
        for label, dim in _filter_opts:
            btn = QPushButton(label)
            btn.setObjectName("pill_button")
            btn.setCheckable(True)
            btn.setChecked(dim is None)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _chk, d=dim: self._set_style_filter(d))
            filter_row.addWidget(btn)
            self._style_filter_btns[dim] = btn
        filter_row.addStretch()
        tl.addLayout(filter_row)

        self.style_list = QListWidget()
        self.style_list.itemClicked.connect(self._on_stylization_clicked)
        tl.addWidget(self.style_list, 1)

        v_split.addWidget(top_frame)

        # ── 左下：选中风格化的详情 ──
        bot_frame = QFrame()
        bot_frame.setObjectName("card")
        bl = QVBoxLayout(bot_frame)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.setSpacing(6)

        bot_title = QLabel("风格画像")
        bot_title.setObjectName("card_title")
        bl.addWidget(bot_title)

        # 用 QScrollArea 包住详情内容，内容长时可滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        detail_container = QWidget()
        self.detail_layout = QVBoxLayout(detail_container)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(8)
        self.detail_content = QTextEdit()
        self.detail_content.setReadOnly(True)
        self.detail_content.setPlaceholderText("← 从上方列表选择一个风格化条目")
        self.detail_layout.addWidget(self.detail_content, 1)

        # 知识背景子区
        self.kb_section_label = QLabel("知识背景")
        self.kb_section_label.setObjectName("card_title")
        self.kb_section_label.setVisible(False)
        self.detail_layout.addWidget(self.kb_section_label)

        self.kb_inline_list = QListWidget()
        self.kb_inline_list.setMaximumHeight(100)
        self.kb_inline_list.setVisible(False)
        self.detail_layout.addWidget(self.kb_inline_list)

        scroll.setWidget(detail_container)
        bl.addWidget(scroll, 1)
        v_split.addWidget(bot_frame)

        v_split.setStretchFactor(0, 2)
        v_split.setStretchFactor(1, 3)
        outer_lay.addWidget(v_split, 1)

        # ── 操作按钮行 ──
        btn_row = QHBoxLayout()
        self.btn_use_style = QPushButton("✍️ 用此风格调文案")
        self.btn_use_style.setObjectName("primary_button")
        self.btn_use_style.setEnabled(False)
        self.btn_use_style.clicked.connect(self._adjust_copy)
        btn_row.addWidget(self.btn_use_style)

        self.btn_regen = QPushButton("🔄 重新提炼")
        self.btn_regen.setObjectName("secondary_button")
        self.btn_regen.setEnabled(False)
        self.btn_regen.clicked.connect(self._regen_current)
        btn_row.addWidget(self.btn_regen)

        self.btn_del_style = QPushButton("🗑️ 删除")
        self.btn_del_style.setObjectName("secondary_button")
        self.btn_del_style.setEnabled(False)
        self.btn_del_style.clicked.connect(self._delete_current)
        btn_row.addWidget(self.btn_del_style)

        self.btn_like = QPushButton("👍 加分")
        self.btn_like.setObjectName("secondary_button")
        self.btn_like.setToolTip("此风格效果好，评分 +0.5")
        self.btn_like.setEnabled(False)
        self.btn_like.clicked.connect(self._like_current)
        btn_row.addWidget(self.btn_like)

        self.btn_dislike = QPushButton("👎 差评")
        self.btn_dislike.setObjectName("secondary_button")
        self.btn_dislike.setToolTip("此风格效果差，评分 -0.3")
        self.btn_dislike.setEnabled(False)
        self.btn_dislike.clicked.connect(self._dislike_current)
        btn_row.addWidget(self.btn_dislike)

        btn_row.addStretch()
        self.action_status = QLabel("")
        self.action_status.setObjectName("muted_text")
        btn_row.addWidget(self.action_status)
        outer_lay.addLayout(btn_row)

        return outer

    # ══════════════ 右侧面板 ══════════════

    def _build_right(self):
        """右侧 = 此风格化的参考素材列表，双击素材弹出详情。"""
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        hdr_row = QHBoxLayout()
        self.samples_header = QLabel("参考素材")
        self.samples_header.setObjectName("card_title")
        hdr_row.addWidget(self.samples_header, 1)

        self.btn_transcribe = QPushButton("🎬 批量转文字")
        self.btn_transcribe.setObjectName("secondary_button")
        self.btn_transcribe.setToolTip(
            "对已下载的素材视频运行 Whisper 转写，跳过未下载或已有转写的素材")
        self.btn_transcribe.setEnabled(False)
        self.btn_transcribe.clicked.connect(self._batch_transcribe)
        hdr_row.addWidget(self.btn_transcribe)
        lay.addLayout(hdr_row)

        self.samples_warn_label = QLabel("")
        self.samples_warn_label.setVisible(False)
        self.samples_warn_label.setStyleSheet("color: #FF9800;")
        self.samples_warn_label.setWordWrap(True)
        lay.addWidget(self.samples_warn_label)

        self.samples_hint = QLabel("← 选择一个风格化条目，查看其参考素材")
        self.samples_hint.setObjectName("muted_text")
        self.samples_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.samples_hint)

        self.samples_list = QTreeWidget()
        self.samples_list.setVisible(False)
        self.samples_list.setColumnCount(3)
        self.samples_list.setHeaderLabels(["素材（来源 · 创作者 · 标题）", "下载", "转写"])
        self.samples_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.samples_list.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.samples_list.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.samples_list.setColumnWidth(1, 70)
        self.samples_list.setColumnWidth(2, 70)
        self.samples_list.setRootIsDecorated(False)
        self.samples_list.itemDoubleClicked.connect(self._on_sample_double_clicked)
        lay.addWidget(self.samples_list, 1)

        legend = QLabel("✅=已下载/已转写  ⬜=未下载  📝=已转写  |  双击查看素材详情")
        legend.setObjectName("muted_text")
        legend.setVisible(False)
        self.samples_legend = legend
        lay.addWidget(legend)

        return frame

    # ══════════════ 同步/导入 ══════════════

    def _open_browser_sync(self):
        ok, msg = abrowser.launch_knowledge_sync()
        if not ok:
            self.show_error(msg, "无法打开素材浏览器")
            return
        self.show_info(f"{msg}\n\n在浏览器「收藏记录」里收集内容后，点「同步记录素材」导入。", "已打开")

    def _import_samples(self):
        added, skipped, msg = self.manager.import_browser_samples()
        if added:
            self.refresh_stylization_list()
            self._refresh_stats()
            self.show_info(msg, "导入成功")
        else:
            self.show_warning(msg, "未导入新样本")

    def _import_kb_items(self):
        added, skipped, msg = self.manager.import_kb_items()
        if added:
            self.refresh_stylization_list()
            self._refresh_stats()
            self.show_info(msg, "导入成功")
        else:
            self.show_warning(msg, "未导入新收藏记录")

    # ══════════════ 提炼风格化 ══════════════

    def _distill(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        cfg = {"api_url": ai.get("llm_api_url",""), "api_key": ai.get("llm_api_key",""),
               "model": ai.get("llm_model","deepseek-chat")}
        if not (cfg["api_url"] and cfg["api_key"]):
            self.show_warning("请先在「AI 设置」配置 LLM 的 API 地址与 Key。", "未配置 LLM")
            return
        has_samples = any(it.get("type") == REFERENCE_TYPE for it in self.manager.all_items())
        if not has_samples:
            self.show_warning("还没有原始素材。请先点「导入收藏记录」或「同步记录素材」。", "无可提炼样本")
            return
        self.btn_distill.setEnabled(False)
        self.distill_status.setText("正在打标并提炼风格化…")
        self._distill_worker = _DistillWorker(self.manager, cfg)
        self._distill_worker.progress.connect(lambda m: self.distill_status.setText(m))

        def on_done(res):
            created, updated, msg = res
            self.btn_distill.setEnabled(True)
            self.distill_status.setText("")
            self.refresh_stylization_list()
            self._refresh_stats()
            (self.show_info if (created or updated) else self.show_warning)(msg, "风格化提炼")

        self._distill_worker.finished.connect(on_done)
        self._distill_worker.error.connect(
            lambda e: (self.btn_distill.setEnabled(True),
                       self.distill_status.setText(""),
                       self.show_error(f"提炼失败：{e}")))
        self.track_worker(self._distill_worker)
        self._distill_worker.start()

    def _regen_current(self):
        s = self.current_stylization
        if not s:
            return
        source_urls = set(s.get("source_urls") or [])
        samples = [it for it in self.manager.all_items()
                   if it.get("type") == REFERENCE_TYPE
                   and (it.get("source") or {}).get("url","") in source_urls]
        if not samples:
            self.show_warning("未找到此风格化的源素材，无法重新提炼。", "无源素材")
            return
        ai = getattr(self.main_window, "ai_config", {}) or {}
        cfg = {"api_url": ai.get("llm_api_url",""), "api_key": ai.get("llm_api_key",""),
               "model": ai.get("llm_model","deepseek-chat")}
        if not (cfg["api_url"] and cfg["api_key"]):
            self.show_warning("请先配置 LLM。", "未配置 LLM")
            return
        self.action_status.setText("正在重新提炼…")
        self.btn_regen.setEnabled(False)
        self._regen_worker = _RegenWorker(cfg, s.get("dim",""), s.get("dim_value",""), samples)

        def on_done(content):
            self.btn_regen.setEnabled(True)
            self.action_status.setText("")
            if content:
                import time
                s["content"] = content
                s["updated_at"] = int(time.time())
                self.manager.save()
                self.detail_content.setPlainText(content)
                self.show_info("重新提炼完成。", "完成")
            else:
                self.show_warning("提炼结果为空。", "失败")

        self._regen_worker.finished.connect(on_done)
        self._regen_worker.error.connect(
            lambda e: (setattr(self, 'btn_regen_ok', True),
                       self.btn_regen.setEnabled(True),
                       self.action_status.setText(""),
                       self.show_error(f"失败：{e}")))
        self.track_worker(self._regen_worker)
        self._regen_worker.start()

    def _delete_current(self):
        s = self.current_stylization
        if not s:
            return
        if not self.confirm(f"确定删除风格化「{s.get('name','')}」？", "删除确认"):
            return
        self.manager.remove_item(s.get("id",""))
        self.current_stylization = None
        self._clear_detail()
        self.refresh_stylization_list()

    def _like_current(self):
        s = self.current_stylization
        if not s:
            return
        self.manager.like_item(s.get("id",""))
        self.current_stylization = self.manager.get(s.get("id",""))
        score = self.current_stylization.get("score", 5.0)
        self.action_status.setText(f"👍 已点赞，当前评分 {score:.1f}")
        self.refresh_stylization_list()

    def _dislike_current(self):
        s = self.current_stylization
        if not s:
            return
        self.manager.dislike_item(s.get("id",""))
        self.current_stylization = self.manager.get(s.get("id",""))
        score = self.current_stylization.get("score", 5.0)
        self.action_status.setText(f"👎 已差评，当前评分 {score:.1f}")
        self.refresh_stylization_list()

    # ══════════════ 调文案 ══════════════

    def _adjust_copy(self):
        s = self.current_stylization
        ai = getattr(self.main_window, "ai_config", {}) or {}
        api_url, api_key = ai.get("llm_api_url",""), ai.get("llm_api_key","")
        model = ai.get("llm_model","deepseek-chat")
        if not (api_url and api_key):
            self.show_warning("请先在「AI 设置」配置 LLM 的 API 地址与 Key。", "未配置 LLM")
            return

        # 推荐维度：当前风格化的 dim/dim_value 用于推荐排序
        cur_dim = s.get("dim") if s else None
        cur_dim_val = s.get("dim_value") if s else None

        all_items = self.manager.all_items()
        selectable = [it for it in all_items if it.get("type") not in (REFERENCE_TYPE,)]
        # 风格化按评分降序 + 当前维度/取值优先；非风格化排最后
        def _sel_key(it):
            if it.get("type") == STYLIZATION_TYPE:
                score = it.get("score", 5.0)
                match = (it.get("dim") == cur_dim and it.get("dim_value") == cur_dim_val)
                return (0, 0 if match else 1, -score)
            return (1, 0, 0)
        selectable.sort(key=_sel_key)

        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle("用风格化调整文案")
        dlg.resize(720, 720)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel("① 待调整文案"))
        draft = QTextEdit()
        draft.setPlaceholderText("粘贴要调整的文案…")
        lay.addWidget(draft, 2)

        lay.addWidget(QLabel("② 风格指引（评分高/匹配的排最前，默认勾选当前风格化）"))
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        klist = QListWidget()
        klist.setMaximumHeight(180)
        for it in selectable:
            t = it.get("type", "")
            name = it.get("name", "")
            score = it.get("score")
            score_tag = f" ⭐{score:.1f}" if (t == STYLIZATION_TYPE and score is not None) else ""
            warn_tag = " ⚠️样本少" if (t == STYLIZATION_TYPE and (it.get("source_count") or 0) < 3) else ""
            node = QListWidgetItem(f"[{t}]  {name}{score_tag}{warn_tag}")
            node.setData(Qt.UserRole, it.get("id"))
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
            is_current = s and it.get("id") == s.get("id")
            node.setCheckState(Qt.Checked if is_current else Qt.Unchecked)
            if score is not None and score >= 7.0:
                node.setForeground(QColor("#4CAF50"))
            elif score is not None and score < 5.0:
                node.setForeground(QColor("#FF9800"))
            klist.addItem(node)
        lay.addWidget(klist)

        btn_go = QPushButton("✨ 调整文案")
        btn_go.setObjectName("primary_button")
        lay.addWidget(btn_go)

        lay.addWidget(QLabel("③ 调整结果"))
        out = QTextEdit()
        out.setReadOnly(True)
        lay.addWidget(out, 2)
        status = QLabel("")
        status.setObjectName("muted_text")
        lay.addWidget(status)

        def run():
            d = draft.toPlainText().strip()
            if not d:
                status.setText("请先粘贴文案。")
                return
            ids = [klist.item(i).data(Qt.UserRole) for i in range(klist.count())
                   if klist.item(i).checkState() == Qt.Checked]
            if not ids:
                status.setText("请至少勾选一条风格化/知识。")
                return
            # 全部条目统一转为风格指引格式，让 LLM 只做写法改写
            kb = self.manager.to_style_guidance_text(ids)
            from gui.ai_script_page import LLMWorker
            system = (
                "你是资深短视频/电商文案写法改写助手。\n"
                "下面给你若干条「风格指引」，每条定义了一个写作风格维度——"
                "包括开头钩子、语气口吻、句式节奏、常用句型模板、收尾方式和风格禁忌。\n\n"
                "改写规则（严格遵守）：\n"
                "① 只改写法（HOW）——开头方式、语气、句式结构、节奏、收尾\n"
                "② 不改内容（WHAT）——产品名称、核心卖点、数据、功能描述保持不变\n"
                "③ 禁忌检查——删除风格指引中标注禁止使用的表达方式\n"
                "④ 直接输出改写后的完整文案，不要解释说明、不要列出修改点"
            )
            user = f"【风格指引】\n{kb}\n\n【待改写文案】\n{d}"
            btn_go.setEnabled(False)
            status.setText("正在调整…")
            self._adj_worker = LLMWorker(api_url, api_key, model, system, user)
            self._adj_worker.finished.connect(
                lambda t: (out.setPlainText(t), status.setText("完成"), btn_go.setEnabled(True)))
            self._adj_worker.error.connect(
                lambda e: (status.setText(f"失败：{e}"), btn_go.setEnabled(True)))
            self._adj_worker.start()

        btn_go.clicked.connect(run)
        QDialogButtonBox(QDialogButtonBox.Close, parent=dlg).rejected.connect(dlg.reject)
        lay.addWidget(QDialogButtonBox(QDialogButtonBox.Close, parent=dlg))
        dlg.exec()

    # ══════════════ 知识背景管理 ══════════════

    def _open_kb_dialog(self):
        dlg = KnowledgeBgDialog(self.manager, parent=self.parent_widget)
        dlg.exec()
        # 可能有更新，刷新详情区知识背景
        if self.current_stylization:
            self._fill_kb_inline()

    # ══════════════ 列表刷新 ══════════════

    def refresh_stylization_list(self):
        self.style_list.clear()
        stylizations = [it for it in self.manager.all_items()
                        if it.get("type") == STYLIZATION_TYPE]

        # 应用维度过滤
        if self._style_filter_dim is not None:
            stylizations = [it for it in stylizations if it.get("dim") == self._style_filter_dim]

        if not stylizations:
            msg = ("（暂无风格化条目，请先导入素材并点「✨ 提炼风格化」）"
                   if self._style_filter_dim is None
                   else f"（此维度暂无风格化条目）")
            empty = QListWidgetItem(msg)
            empty.setFlags(Qt.NoItemFlags)
            empty.setForeground(QColor("#888888"))
            self.style_list.addItem(empty)
            return

        # 按维度分组输出
        dim_order = list(STYLE_DIMS.keys())
        by_dim = {}
        for it in stylizations:
            by_dim.setdefault(it.get("dim","other"), []).append(it)

        for dim in dim_order + [k for k in by_dim if k not in dim_order]:
            if dim not in by_dim:
                continue
            dim_label = STYLE_DIMS.get(dim, dim)
            group = by_dim[dim]

            # 维度分组标题
            sec = QListWidgetItem(f"  {dim_label}  ({len(group)})")
            sec.setFlags(Qt.NoItemFlags)
            sec.setForeground(QColor("#888888"))
            f = sec.font()
            f.setBold(True)
            sec.setFont(f)
            self.style_list.addItem(sec)

            # 按评分降序
            group.sort(key=lambda x: -(x.get("score") or 5.0))
            for it in group:
                val = it.get("dim_value","")
                cnt = it.get("source_count", 0)
                score = it.get("score", 5.0)
                # 评分徽章：绿 ≥7 / 黄 5–6.9 / 红 <5
                if score >= 7.0:
                    badge = f"⭐{score:.1f}"
                elif score >= 5.0:
                    badge = f"★{score:.1f}"
                else:
                    badge = f"☆{score:.1f}"
                warn = "  ⚠️" if cnt < 3 else ""
                label = f"    🎨  {val}   [{badge}]  ({cnt} 条){warn}"
                node = QListWidgetItem(label)
                node.setData(Qt.UserRole, it.get("id"))
                # 评分颜色
                if score >= 7.0:
                    node.setForeground(QColor("#4CAF50"))
                elif score < 5.0:
                    node.setForeground(QColor("#FF9800"))
                self.style_list.addItem(node)

    # ══════════════ 选中风格化 ══════════════

    def _on_stylization_clicked(self, item):
        rid = item.data(Qt.UserRole)
        if not rid:
            return
        record = self.manager.get(rid)
        if not record:
            return
        self.current_stylization = record

        # 左下：填充风格画像
        self.detail_content.setPlainText(record.get("content",""))
        self._fill_kb_inline()

        # 操作按钮激活
        self.btn_use_style.setEnabled(True)
        self.btn_regen.setEnabled(True)
        self.btn_del_style.setEnabled(True)
        self.btn_like.setEnabled(True)
        self.btn_dislike.setEnabled(True)
        self.action_status.setText("")

        # 右侧：填充参考素材
        self._fill_samples_panel(record)

    def _fill_kb_inline(self):
        """在左下显示所有知识背景条目（非风格化、非原始样本）。"""
        kb_items = [it for it in self.manager.all_items()
                    if it.get("type") not in (STYLIZATION_TYPE, REFERENCE_TYPE)]
        self.kb_section_label.setVisible(bool(kb_items))
        self.kb_inline_list.setVisible(bool(kb_items))
        self.kb_inline_list.clear()
        for it in kb_items:
            t = it.get("type","")
            node = QListWidgetItem(f"[{t}]  {it.get('name','')}")
            node.setFlags(Qt.NoItemFlags)
            self.kb_inline_list.addItem(node)

    def _fill_samples_panel(self, stylization):
        """右侧：列出此风格化使用的所有参考素材。"""
        dim_label = STYLE_DIMS.get(stylization.get("dim",""), "风格")
        dim_val   = stylization.get("dim_value","")
        source_urls = set(stylization.get("source_urls") or [])

        matched = [it for it in self.manager.all_items()
                   if it.get("type") == REFERENCE_TYPE
                   and (it.get("source") or {}).get("url","") in source_urls]

        n_total   = len(matched)
        n_missing = sum(1 for s in matched
                        if not os.path.exists((s.get("source") or {}).get("media_path","") or ""))
        n_transcribed = sum(1 for s in matched if (s.get("transcript") or "").strip())

        self.samples_header.setText(f"参考素材  —  [{dim_label}]  {dim_val}  （{n_total} 条）")
        self.samples_hint.setVisible(False)
        self.samples_list.setVisible(True)
        self.samples_legend.setVisible(True)
        self.btn_transcribe.setEnabled(True)

        # 未下载/未转写提醒
        warn_parts = []
        if n_missing > 0:
            warn_parts.append(f"⚠️ {n_missing}/{n_total} 条素材尚未下载，批量转文字将跳过")
        if n_transcribed < n_total - n_missing:
            not_yet = n_total - n_missing - n_transcribed
            warn_parts.append(f"📝 {not_yet} 条已下载但未转写")
        if warn_parts:
            self.samples_warn_label.setText("  |  ".join(warn_parts))
            self.samples_warn_label.setVisible(True)
        else:
            self.samples_warn_label.setVisible(False)

        self.samples_list.clear()

        for s in matched:
            src = s.get("source") or {}
            if src.get("is_liked"):
                badge = "👍"
            elif src.get("is_collected"):
                badge = "🔖"
            else:
                badge = "👤"
            platform   = src.get("platformName") or src.get("platform","")
            creator    = src.get("creator","")
            media_path = src.get("media_path","")
            has_media  = bool(media_path and os.path.exists(media_path))
            has_transcript = bool((s.get("transcript") or "").strip())

            title_short = s.get("name","")[:28]
            col0 = f"{badge}  [{platform}]  {creator}  —  {title_short}"
            col1 = "✅" if has_media else "⬜"
            col2 = "📝" if has_transcript else "—"

            node = QTreeWidgetItem([col0, col1, col2])
            node.setData(0, Qt.UserRole, s.get("id"))
            node.setToolTip(0, s.get("name",""))
            node.setTextAlignment(1, Qt.AlignCenter)
            node.setTextAlignment(2, Qt.AlignCenter)
            if has_media:
                node.setForeground(0, QColor("#4CAF50"))
                node.setForeground(1, QColor("#4CAF50"))
            else:
                node.setForeground(1, QColor("#888888"))
            if has_transcript:
                node.setForeground(2, QColor("#2196F3"))
            self.samples_list.addTopLevelItem(node)

    def _clear_detail(self):
        self.detail_content.clear()
        self.kb_section_label.setVisible(False)
        self.kb_inline_list.setVisible(False)
        self.btn_use_style.setEnabled(False)
        self.btn_regen.setEnabled(False)
        self.btn_del_style.setEnabled(False)
        self.btn_like.setEnabled(False)
        self.btn_dislike.setEnabled(False)
        self.btn_transcribe.setEnabled(False)
        self.samples_hint.setVisible(True)
        self.samples_warn_label.setVisible(False)
        self.samples_list.setVisible(False)
        self.samples_legend.setVisible(False)
        self.samples_list.clear()
        self.samples_header.setText("参考素材")

    # ══════════════ 双击素材 ══════════════

    def _on_sample_double_clicked(self, item):
        rid = item.data(0, Qt.UserRole)   # QTreeWidgetItem 需要 (column, role)
        sample = self.manager.get(rid)
        if not sample:
            return
        dlg = SampleDetailDialog(
            sample,
            stylization=self.current_stylization,
            parent=self.parent_widget
        )
        dlg.exec()

    # ══════════════ 风格化过滤 ══════════════

    def _set_style_filter(self, dim):
        self._style_filter_dim = dim
        for d, btn in self._style_filter_btns.items():
            btn.setChecked(d == dim)
        self.refresh_stylization_list()

    # ══════════════ 批量转文字 ══════════════

    def _batch_transcribe(self):
        s = self.current_stylization
        if not s:
            return
        source_urls = set(s.get("source_urls") or [])
        matched = [it for it in self.manager.all_items()
                   if it.get("type") == REFERENCE_TYPE
                   and (it.get("source") or {}).get("url","") in source_urls]
        to_transcribe = [
            it for it in matched
            if os.path.exists((it.get("source") or {}).get("media_path","") or "")
            and not (it.get("transcript") or "").strip()
        ]
        if not to_transcribe:
            already  = sum(1 for it in matched if (it.get("transcript") or "").strip())
            missing  = sum(1 for it in matched
                           if not os.path.exists((it.get("source") or {}).get("media_path","") or ""))
            self.show_info(
                f"无需处理：{already} 条已有转写文本，{missing} 条未下载（已跳过）。",
                "批量转文字"
            )
            return
        ai = getattr(self.main_window, "ai_config", {}) or {}
        model_name = ai.get("whisper_model", "large-v3")
        self.btn_transcribe.setEnabled(False)
        self.samples_header.setText(f"正在转写 0/{len(to_transcribe)} 条…")
        self._transcribe_worker = _BatchTranscribeWorker(to_transcribe, model_name, self.manager)
        self._transcribe_worker.progress.connect(self.samples_header.setText)
        self._transcribe_worker.finished.connect(self._on_transcribe_done)
        self._transcribe_worker.error.connect(
            lambda e: (self.btn_transcribe.setEnabled(True),
                       self.show_error(f"批量转写失败：{e}")))
        self.track_worker(self._transcribe_worker)
        self._transcribe_worker.start()

    def _on_transcribe_done(self, count):
        self.btn_transcribe.setEnabled(True)
        if self.current_stylization:
            self._fill_samples_panel(self.current_stylization)
        self.show_info(f"转写完成：{count} 条素材已生成转写文本。", "批量转文字")

    # ══════════════ 兼容旧调用 ══════════════

    def clear_form(self):
        pass
