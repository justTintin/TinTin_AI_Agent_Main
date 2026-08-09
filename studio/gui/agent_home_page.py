# -*- coding: utf-8 -*-
"""运营工作台首页：高频任务卡片 + AI 对话面板（服务端智能体注册表 → 智能体列表供对话唤起）。

AI 对话（参考 Cherry Studio 对话体验，服务端暂不支持流式 → 整段返回）：
  - 智能体对话：POST /agent/chat，服务端智能体循环执行，可调用注册能力；
  - 通用对话：POST /llm/chat/completions，DeepSeek 代理多轮问答；
  模型下拉来自 GET /llm/models，上下文自动截断防超长。

智能体列表：把服务端 /agent/registry 注册的智能体能力（带唤醒提示词）放在
对话框下方；点击后把唤醒词插入输入框。选择的产品/素材/脚本/附件同样以文本
形式插入输入框，用户编辑完成后点「发送」才提交给智能体（所见即所得）。
"""
import os
import re

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize, QPoint, QEvent
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFrame, QGridLayout, QWidget, QCheckBox,
                               QTabWidget, QComboBox, QTextEdit, QApplication,
                               QTextBrowser, QScrollArea, QDialog, QFileDialog,
                               QListWidget, QListWidgetItem, QMessageBox)
from gui.searchable_combo import SearchableComboBox
from utils.gui_icons import mdi_icon, mdi_button
from utils.logger_utils import log

# (标题, 图标, 描述, 目标页 index, 强调色)
_TASK_CARDS = [
    ("一键成片", "rocket", "选产品或贴文案，自动配素材配音生成成片", 33, "#3b82f6"),
    ("智能混剪", "cut", "多镜头素材自动拼接成片，支持转场配音", 14, "#8b5cf6"),
    ("声音克隆", "mic", "粘贴文案、选音色，克隆整段语音", 20, "#d946ef"),
    ("直播切片", "video", "从直播回放自动切出精彩片段配字幕", 18, "#f97316"),
    ("封面制作", "camera", "输入标题卖点，自动生成视频封面", 32, "#06b6d4"),
    ("视频去字幕", "closed-caption", "AI 擦除视频字幕/水印，服务端智能识别选区", 17, "#10b981"),
    ("视频评价", "film", "预测成片数据表现，给出优化建议", 34, "#f59e0b"),
    ("成片任务", "folder", "查看所有成片/混剪任务进度", 42, "#64748b"),
]

# 通用对话模式的首条系统提示词（智能体模式由服务端内置助手提示词接管）
_SYSTEM_PROMPT = (
    "你是「螺丝钉电商智能体」的运营助手，帮助用户完成电商短视频的内容创作、素材管理、"
    "视频处理等任务。回答简洁实用，需要执行具体任务时给出可操作的步骤建议。"
)

# 素材类型显示标签（服务端 media_type → 中文）
_MEDIA_TYPE_LABEL = {"image": "图片", "video": "视频", "audio": "音频", "document": "文档"}

# 对话回复中的成片视频资产识别（供气泡挂播放/下载按钮）
_URL_RE = re.compile(r"https?://[^\s)\]}>，。；、]+")
_REL_URL_RE = re.compile(r"/editor/render/(\d+)/result[^\s]*")
_VIDEO_URL_HINTS = (".mp4", "/render", "/result", "/video", "/output", "/download")


class _TaskCard(QPushButton):
    """任务卡片：顶部强调色条 + 渐变图标块 + 标题 + 描述，可点击。"""

    def __init__(self, title, icon, desc, accent="#3b82f6", parent=None):
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        self.setStyleSheet(
            f"QPushButton {{"
            f" background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"   stop:0 #1b1f2d, stop:1 #161924);"
            f" border:1px solid #2c3344; border-top:3px solid {accent};"
            f" border-radius:12px; text-align:left; }}"
            f" QPushButton:hover {{"
            f"  border:1px solid {accent}; border-top:3px solid {accent};"
            f"  background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"    stop:0 #202536, stop:1 #1a1e2c); }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(9)
        ico = QLabel()
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"  stop:0 {accent}, stop:1 #334155); border-radius:10px;")
        ico.setPixmap(mdi_icon(icon, "#ffffff").pixmap(22, 22))
        head.addWidget(ico)
        t = QLabel(title)
        t.setStyleSheet("background:transparent; border:none; font-size:15px; font-weight:700; color:#f0f1f7;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("background:transparent; border:none; color:#9aa3b2; font-size:12px; line-height:1.5;")
        lay.addWidget(d)


# ── AI 对话 ─────────────────────────────────────────────────────────────

class _ChatInput(QTextEdit):
    """对话输入框：回车发送，Shift+回车换行；输入 / 弹出智能体快捷菜单。

    复制粘贴由 QTextEdit 原生支持（Ctrl+C/V/X、右键菜单、拖放文本）；
    粘贴统一转纯文本，丢弃图片/HTML 格式，保证发送给智能体的内容干净。
    """
    sendRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slash_popup = None
        self.setAcceptRichText(False)
        self.textChanged.connect(self._on_text_changed)

    def insertFromMimeData(self, source):
        """粘贴/拖入只保留纯文本：图片、HTML 等格式一律丢弃。"""
        if source is not None and source.hasText():
            self.insertPlainText(source.text())

    def set_slash_popup(self, popup):
        """注入斜杠快捷菜单（_SlashPopup），由面板层创建。"""
        self._slash_popup = popup

    def _on_text_changed(self):
        """光标前以 /开头且是智能体名前缀时弹出候选，否则关闭。

        只认智能体名匹配：智能体插入文本（如 negative/style_tags）或 URL 里的
        斜杠不会触发菜单，否则菜单（模态浮层）反复弹出抢焦点导致无法发送。
        """
        popup = self._slash_popup
        if popup is None:
            return
        if not popup.agents:
            popup.hide()
            return
        cur = self.textCursor()
        seg = cur.block().text()[:cur.positionInBlock()]
        m = re.search(r"/([^\s/]*)$", seg)
        if m and popup.is_agent_prefix(m.group(1)):
            popup.show_for(m.group(1))
        elif popup.isVisible():
            popup.hide()

    def keyPressEvent(self, event):
        popup = self._slash_popup
        if popup is not None and popup.isVisible():
            if event.key() == Qt.Key_Down:
                popup.next_row()
                event.accept()
                return
            if event.key() == Qt.Key_Up:
                popup.prev_row()
                event.accept()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                popup.confirm()
                event.accept()
                return
            if event.key() == Qt.Key_Escape:
                popup.hide()
                event.accept()
                return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.sendRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _SlashPopup(QListWidget):
    """斜杠快捷菜单：输入 / 时列出智能体候选，上下键选择、回车或点击插入唤醒词。

    参考 Cherry Studio 的命令菜单交互。键盘焦点保持在输入框（本控件 NoFocus），
    通过输入框的 keyPressEvent 转发方向键 / 回车 / ESC；Esc 或点击外部自动关闭。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 非模态不激活浮层：Qt.Popup 是应用级模态，显示时主窗口无法聚焦/发送；
        # 改 Tool + WA_ShowWithoutActivating 后菜单显示不影响输入框焦点，点击外部由 eventFilter 关闭。
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(420)
        self.setMaximumHeight(280)
        self.setStyleSheet(
            "QListWidget { background:#1d212b; border:1px solid #2c3344;"
            " border-radius:8px; color:#e2e6ef; font-size:13px; }"
            " QListWidget::item { padding:7px 10px; }"
            " QListWidget::item:selected { background:#2f6fed; color:#ffffff; }")
        self._agents = []
        self._match = []
        self._input = None
        self._last_kw = None   # 最近一次过滤关键字（未变化时不重建列表）
        self.itemClicked.connect(self._on_item_clicked)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def is_agent_prefix(self, kw):
        """斜杠关键字是否可作为智能体名唤起（空关键字=显示全部候选）。"""
        kw = (kw or "").strip().lower()
        if not kw:
            return True
        return any(kw in (a.get("name") or "").lower() for a in self._agents)

    def eventFilter(self, obj, ev):
        """点击菜单外部任意位置 → 关闭菜单（事件继续传递，不吞点击）。"""
        if self.isVisible() and ev.type() == QEvent.MouseButtonPress:
            pos = (ev.globalPosition().toPoint()
                   if hasattr(ev, "globalPosition") else ev.globalPos())
            if not self.geometry().contains(pos):
                self.hide()
        return super().eventFilter(obj, ev)

    @property
    def agents(self):
        return self._agents

    def set_agents(self, agents):
        self._agents = agents or []

    def set_input(self, w):
        self._input = w

    def show_for(self, kw):
        """按关键字过滤智能体并弹出菜单（定位在输入框上方）。

        菜单已显示时只刷新列表内容，不重复 show()/raise_()：
        本菜单是不激活浮层（WA_ShowWithoutActivating），显示时输入框焦点不受影响；
        点击外部由 eventFilter 关闭。
        """
        k = (kw or "").strip().lower()
        if self.isVisible() and k == self._last_kw:
            return   # 菜单已显示且过滤词未变：无需重建
        self._last_kw = k
        was_visible = self.isVisible()
        self.clear()
        self._match = []
        for a in self._agents:
            name = a.get("name") or a.get("id") or ""
            desc = a.get("desc") or ""
            if k and k not in name.lower() and k not in desc.lower():
                continue
            self._match.append(a)
            item = QListWidgetItem(f"🤖 {name}")
            item.setToolTip(desc)
            self.addItem(item)
        if not self._match:
            it = QListWidgetItem("（无匹配智能体）")
            it.setFlags(Qt.NoItemFlags)
            self.addItem(it)
        else:
            self.setCurrentRow(0)
        if self._input is not None:
            self.adjustSize()
            h = min(self.sizeHint().height(), self.maximumHeight())
            self.setFixedHeight(h)
            pos = self._input.mapToGlobal(QPoint(0, 0)) - QPoint(0, h + 8)
            self.move(pos)
        if not was_visible:
            self.show()
            self.raise_()

    def next_row(self):
        if self._match and self.currentRow() < len(self._match) - 1:
            self.setCurrentRow(self.currentRow() + 1)

    def prev_row(self):
        if self._match and self.currentRow() > 0:
            self.setCurrentRow(self.currentRow() - 1)

    def confirm(self):
        row = self.currentRow()
        if self._match and 0 <= row < len(self._match):
            self._insert_agent(self._match[row])

    def _on_item_clicked(self, item):
        row = self.row(item)
        if self._match and 0 <= row < len(self._match):
            self._insert_agent(self._match[row])

    def _insert_agent(self, agent):
        """把输入框中的 /关键字 替换为智能体唤醒词，光标移到末尾。"""
        self.hide()
        w = self._input
        if w is None:
            return
        cur = w.textCursor()
        block = cur.block().text()
        pos = cur.positionInBlock()
        seg = block[:pos]
        i = seg.rfind("/")
        if i >= 0 and all(c != " " for c in seg[i + 1:]):
            cur.setPosition(cur.block().position() + i)
            cur.setPosition(cur.block().position() + pos, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        name = agent.get("name") or agent.get("id") or "该智能体"
        desc = (agent.get("desc") or "").strip()
        prefix = f"请【{name}】智能体执行：{desc}" if desc else f"请【{name}】智能体执行"
        cur.insertText(prefix)
        w.setTextCursor(cur)
        w.setFocus()
        QTimer.singleShot(0, w.setFocus)   # 兜底：菜单刚关闭时确保焦点回输入框


class _MdBrowser(QTextBrowser):
    """只读 Markdown 气泡浏览器：随内容自适应高度，宽度不超上限。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenExternalLinks(True)
        self.setMaximumWidth(720)
        self.setMinimumWidth(200)
        self.document().contentsChanged.connect(self._adjust_height)

    def setMarkdown(self, text):
        """渲染 markdown 后把链接前景色改为亮蓝。

        Qt 解析器把链接颜色写死为调色板 Link 色（#0000ff），QSS / 默认样式表 /
        widget 调色板均无法覆盖；与用户气泡蓝底同色无法区分，故手动重着色。
        """
        super().setMarkdown(text)
        self._recolor_links()

    def _recolor_links(self):
        doc = self.document()
        blk = doc.begin()
        while blk.isValid():
            it = blk.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isAnchor() and fmt.foreground().color().name() == "#0000ff":
                    cur = QTextCursor(doc)
                    cur.setPosition(frag.position())
                    cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                    f = QTextCharFormat()
                    f.setForeground(QColor("#8ec2ff"))
                    cur.mergeCharFormat(f)   # 只合并前景色，保留下划线等其它格式
                it += 1
            blk = blk.next()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
        self._adjust_height()

    def _adjust_height(self):
        self.setFixedHeight(max(int(self.document().size().height()) + 12, 30))

    def sizeHint(self):
        doc = self.document()
        w = max(int(doc.idealWidth()) + 36, 200)
        w = min(w, 720)
        return QSize(w, max(int(doc.size().height()) + 12, 30))


class _ChatBubble(QWidget):
    """对话气泡：头像 + Markdown 内容；用户右对齐蓝底，助手左对齐深灰底。

    智能体回复若含成片视频资产，可在内容下方挂「播放/下载」按钮（set_asset_actions）。
    """

    def __init__(self, role, text, parent=None):
        super().__init__(parent)
        is_user = role == "user"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        avatar = QLabel("🙂" if is_user else "🤖")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#1d212b; border-radius:17px; font-size:18px;")
        avatar.setToolTip("我" if is_user else "智能体")

        self._browser = _MdBrowser()
        if is_user:
            # 深蓝灰底（原亮蓝 #2f6fed 与蓝色链接同色无法区分，改为深色后链接亮蓝可读）
            self._browser.setStyleSheet(
                "QTextBrowser { background:#24405f; color:#ffffff;"
                " border-radius:10px; padding:8px 12px; }")
        else:
            self._browser.setStyleSheet(
                "QTextBrowser { background:#232838; color:#e2e6ef;"
                " border-radius:10px; padding:8px 12px; }")

        # 内容列：markdown 正文 + 资产操作行（有视频资产时才显示）
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        col.addWidget(self._browser)
        self._asset_box = QWidget()
        self._asset_box.setVisible(False)
        al = QHBoxLayout(self._asset_box)
        al.setContentsMargins(2, 0, 2, 0)
        al.setSpacing(6)
        col.addWidget(self._asset_box)
        self._asset_url = ""
        self._asset_tid = ""

        self.set_text(text)

        if is_user:
            lay.addStretch()
            lay.addLayout(col)
            lay.addWidget(avatar)
        else:
            lay.addWidget(avatar)
            lay.addLayout(col)
            lay.addStretch()

    def set_text(self, text):
        self._browser.setMarkdown(text or "")

    # ── 成片资产操作（播放/下载）──────────────────────────────────────
    def set_asset_actions(self, url, title="", tid=""):
        """在气泡下方挂成片资产的播放/下载按钮（面板检测到视频地址后调用）。"""
        self._asset_url = url
        self._asset_tid = tid
        for i in reversed(range(self._asset_box.layout().count())):
            w = self._asset_box.layout().itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        style = ("QPushButton { background:#232838; border:1px solid #2f6fed;"
                 " border-radius:12px; color:#5b8ef0; padding:2px 14px; font-size:12px; }"
                 " QPushButton:hover { background:#2f6fed; color:#ffffff; }")
        btn_play = QPushButton("▶ 播放成片")
        btn_play.setStyleSheet(style)
        btn_play.setToolTip(title or "播放对话生成的成片视频")
        btn_play.clicked.connect(self._play_asset)
        self._asset_box.layout().addWidget(btn_play)
        btn_dl = QPushButton("⬇ 下载成片")
        btn_dl.setStyleSheet(style)
        btn_dl.setToolTip("把成片保存到本地文件")
        btn_dl.clicked.connect(self._download_asset)
        self._asset_box.layout().addWidget(btn_dl)
        self._asset_box.layout().addStretch()
        self._asset_box.setVisible(True)

    def _play_asset(self):
        if not self._asset_url:
            return
        from gui.scheduled_tasks_page import _VideoPlayerDialog
        dlg = _VideoPlayerDialog(self._asset_url, f"任务 #{self._asset_tid}", self)
        self._player_dialog = dlg   # 持有引用防 QThread/播放器 GC
        dlg.exec()

    def _download_asset(self):
        if not self._asset_url:
            return
        from gui.scheduled_tasks_page import _download_to_file
        from utils.thread_worker import TaskWorker as Worker
        default = f"render_{self._asset_tid}.mp4" if self._asset_tid else "render_video.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存成片",
            os.path.join(os.path.expanduser("~"), "Desktop", default),
            "视频文件 (*.mp4 *.mov *.webm);;所有文件 (*.*)")
        if not path:
            return
        url = self._asset_url
        worker = Worker(lambda: _download_to_file(url, path))
        worker.finished.connect(
            lambda p: QMessageBox.information(self, "下载完成", f"✅ 成片已保存：\n{p}"))
        worker.error.connect(
            lambda e: QMessageBox.warning(self, "下载失败", f"下载成片失败：{e}"))
        self._dl_worker = worker   # 持有引用防 QThread GC
        worker.start()


class _ChatWorker(QThread):
    """后台对话请求：智能体模式走 /agent/chat，通用模式走 /llm/chat/completions。

    message：本轮增强消息（唤醒词 + 用户输入 + 附件/产品上下文）；
    history：对话历史（用户输入原文，不含增强部分）。
    plan_mode：开启后智能体对话以 mode=plan 提交（先拆解为编排任务自动执行，
    回复返回任务 ID，可在「编排任务」页跟踪）。
    """
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, mode, history, model, message=None, plan_mode=False, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._history = history
        self._model = model
        self._message = message
        self._plan_mode = plan_mode

    def run(self):
        try:
            if self._mode == "agent":
                from utils.agent_client import agent_chat
                msgs = list(self._history or [])
                message = self._message or (msgs[-1]["content"] if msgs else "")
                reply = agent_chat(message, history=msgs[:-1] or None,
                                   model=self._model or None, max_rounds=3,
                                   mode="plan" if self._plan_mode else None)
            else:
                from utils.llm_proxy import llm_chat_messages
                msgs = [dict(m) for m in (self._history or [])]
                if not msgs:
                    msgs.append({"role": "system", "content": _SYSTEM_PROMPT})
                if self._message is not None and msgs and msgs[-1]["role"] == "user":
                    msgs[-1] = {"role": "user", "content": self._message}
                reply = llm_chat_messages(msgs, model=self._model,
                                          temperature=0.4, timeout=180)
            if not reply:
                raise RuntimeError("服务端未返回内容，请稍后重试")
            self.done.emit(reply)
        except Exception as e:
            log.warning(f"[工作台对话] 请求失败: {e}")
            self.failed.emit(str(e))


class _ModelLoader(QThread):
    """后台加载服务端可用模型列表（GET /llm/models）。"""
    done = Signal(list)

    def run(self):
        try:
            from utils.llm_proxy import list_llm_models
            self.done.emit(list_llm_models(timeout=8))
        except Exception as e:
            log.warning(f"[工作台对话] 加载模型列表失败: {e}")
            self.done.emit([])


class _AgentLoader(QThread):
    """后台加载服务端智能体注册表（GET /agent/registry），过滤基础设施类 → 智能体列表。"""
    done = Signal(list)

    def run(self):
        try:
            from utils.agent_client import get_registry
            data = get_registry(include_external=False, timeout=8) or {}
            agents = []
            for c in (data.get("capabilities") or []):
                tags = c.get("tags") or []
                if any(t in ("infra", "external") for t in tags):
                    continue  # 注册表/任务登记/任务树等基础设施不当作对话智能体
                agents.append({
                    "id": c.get("id") or "",
                    "name": c.get("name") or c.get("id") or "",
                    "desc": c.get("description") or "",
                })
            self.done.emit(agents)
        except Exception as e:
            log.warning(f"[工作台对话] 加载智能体列表失败: {e}")
            self.done.emit([])


class _AgentBar(QWidget):
    """智能体快捷条：每行 10 个按钮，默认只显示第一行，多余折叠；点「展开」显示全部。"""
    agentClicked = Signal(dict)
    _COLS = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agents = []
        self._expanded = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("🤖 智能体")
        lbl.setStyleSheet("color:#8b93a3; font-size:12px; font-weight:600;")
        lbl.setAlignment(Qt.AlignTop)
        row.addWidget(lbl)
        content = QWidget()
        self._grid = QGridLayout(content)
        self._grid.setContentsMargins(0, 2, 0, 0)
        self._grid.setSpacing(6)
        row.addWidget(content, 1)
        self.setFixedHeight(36)

    def set_agents(self, agents):
        self._agents = agents or []
        self._expanded = False
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        n = len(self._agents)
        if n == 0:
            self.setFixedHeight(36)
            return
        for i, a in enumerate(self._agents):
            btn = QPushButton(a.get("name") or a.get("id") or "?")
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            desc = a.get("desc") or ""
            btn.setToolTip(f"{desc}\n点击把唤醒词插入输入框，补充需求后点发送")
            btn.setStyleSheet(
                "QPushButton { background:#1d212b; border:1px solid #262b36; "
                "border-radius:13px; color:#c9d1de; padding:0 12px; font-size:12px; } "
                "QPushButton:hover { border-color:#34d399; color:#34d399; }")
            btn.clicked.connect(lambda checked=False, ag=a: self.agentClicked.emit(ag))
            r, c = divmod(i, self._COLS)
            self._grid.addWidget(btn, r, c, Qt.AlignLeft)
        # 展开/收起按钮：固定第一行第 11 列，总数超过一行才显示
        self.btn_toggle = QPushButton("▾ 展开")
        self.btn_toggle.setFixedHeight(26)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.setStyleSheet(
            "QPushButton { background:transparent; border:1px dashed #3a4152; "
            "border-radius:13px; color:#8b93a3; padding:0 10px; font-size:12px; } "
            "QPushButton:hover { border-color:#34d399; color:#34d399; }")
        self.btn_toggle.clicked.connect(self._toggle_expand)
        self._grid.addWidget(self.btn_toggle, 0, self._COLS, Qt.AlignLeft)
        self._grid.setColumnStretch(self._COLS + 1, 1)
        self._apply_state()

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._apply_state()

    def _apply_state(self):
        n = len(self._agents)
        if n <= self._COLS:
            self.btn_toggle.setVisible(False)
            self.setFixedHeight(36)
            return
        extra = n - self._COLS
        self.btn_toggle.setText(
            "▴ 收起" if self._expanded else f"▾ 展开 {extra} 个")
        for i, a in enumerate(self._agents):
            it = self._grid.itemAt(i)
            if it is not None and it.widget() is not None:
                it.widget().setVisible(self._expanded or i < self._COLS)
        rows = (n + self._COLS - 1) // self._COLS if self._expanded else 1
        self.setFixedHeight(36 if rows == 1 else 26 * rows + 6 * (rows - 1) + 4)


class _ProductPickerDialog(QDialog):
    """可搜索产品选择弹窗：后台加载产品库（/grouped），Completer 实时过滤。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择产品")
        self.setModal(True)
        self.resize(480, 200)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(QLabel("搜索并选择产品（品类/品牌/型号）："))
        self.combo = SearchableComboBox(placeholder="输入品牌/型号/品类搜索…")
        self.combo.setMinimumHeight(34)
        v.addWidget(self.combo)
        tip = QLabel("产品数据来自服务端产品资料库；为空时可先在「产品资料」页同步。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b93a3; font-size:12px;")
        v.addWidget(tip)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("确定")
        ok.setObjectName("primary_button")
        ok.setFixedSize(84, 32)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondary_button")
        cancel.setFixedSize(84, 32)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        v.addLayout(btns)
        self._mgr = None
        self._loader = None
        self._load()

    def _load(self):
        from utils.product_library_manager import ProductLibraryManager
        from utils.thread_worker import TaskWorker as Worker
        self._mgr = ProductLibraryManager()
        self.combo.addItem("加载产品中…", "")
        self._loader = Worker(self._mgr.grouped)
        self._loader.finished.connect(self._on_loaded)
        self._loader.error.connect(lambda msg: self._on_loaded(None))
        self._loader.start()

    def _on_loaded(self, grouped):
        grouped = grouped or {}
        self.combo.blockSignals(True)
        self.combo.clear()
        if not grouped:
            self.combo.addItem("（产品库为空，请先在「产品资料」页同步）", "")
        else:
            for cat, brands in grouped.items():
                for brand, items in brands.items():
                    for it in items:
                        model = it.get("model", "").strip() or it.get("goods_no", "")
                        label = f"[{cat}] {brand} / {model}"
                        self.combo.addItem(label, it.get("id", ""))
        self.combo.blockSignals(False)

    def selected_item(self):
        """返回当前选中产品条目（dict），未选择返回 {}。"""
        if self._mgr is None:
            return {}
        item_id = self.combo.currentData() or ""
        return self._mgr.get(item_id) or {}


class _MaterialPickerDialog(QDialog):
    """可搜索素材选择弹窗：后台加载服务端素材库（GET /material/list），Completer 实时过滤。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择素材")
        self.setModal(True)
        self.resize(520, 200)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(QLabel("搜索并选择素材（文件名/品牌/型号）："))
        self.combo = SearchableComboBox(placeholder="输入文件名/品牌/型号搜索…")
        self.combo.setMinimumHeight(34)
        v.addWidget(self.combo)
        tip = QLabel("素材来自服务端素材库；为空时可先在「素材检索」页确认服务端素材是否已入库。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b93a3; font-size:12px;")
        v.addWidget(tip)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("确定")
        ok.setObjectName("primary_button")
        ok.setFixedSize(84, 32)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondary_button")
        cancel.setFixedSize(84, 32)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        v.addLayout(btns)
        self._items = []
        self._loader = None
        self._load()

    def _load(self):
        from utils.http_client import http_get
        from utils.thread_worker import TaskWorker as Worker
        from utils import config_manager as _cm
        base = (_cm.get_setting("ai_config", "compute_server_url") or "").strip().rstrip("/")

        def _fetch():
            if not base:
                return []
            resp = http_get(f"{base}/material/list",
                            params={"size": 500, "page": 1}, timeout=20)
            if resp.status_code != 200:
                raise RuntimeError(f"服务器返回 {resp.status_code}")
            return (resp.json() or {}).get("items") or []

        self.combo.addItem("加载素材中…", "")
        self._loader = Worker(_fetch)
        self._loader.finished.connect(self._on_loaded)
        self._loader.error.connect(lambda msg: self._on_loaded(None))
        self._loader.start()

    def _on_loaded(self, items):
        self._items = items or []
        self.combo.blockSignals(True)
        self.combo.clear()
        if not self._items:
            self.combo.addItem("（素材库为空或服务端不可达，请先同步素材）", "")
        else:
            for it in self._items:
                mid = str(it.get("id") or it.get("material_id") or "")
                if not mid:
                    continue
                name = it.get("filename") or mid
                brand = (it.get("brand") or "").strip()
                model = (it.get("model") or it.get("product") or "").strip()
                mtype = _MEDIA_TYPE_LABEL.get((it.get("media_type") or "").lower(), "素材")
                suffix = f"（{brand} / {model}）" if (brand or model) else ""
                self.combo.addItem(f"[{mtype}] {name}{suffix}", mid)
        self.combo.blockSignals(False)

    def selected_item(self):
        """返回当前选中素材条目（dict），未选择返回 {}。"""
        mid = self.combo.currentData() or ""
        for it in self._items:
            if str(it.get("id") or it.get("material_id") or "") == mid:
                return it
        return {}


class _ScriptPickerDialog(QDialog):
    """可搜索分镜脚本选择弹窗：后台加载服务端脚本列表（/api/storyboard/scripts），Completer 实时过滤。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择分镜脚本")
        self.setModal(True)
        self.resize(560, 200)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(QLabel("搜索并选择分镜脚本（主题/镜头数）："))
        self.combo = SearchableComboBox(placeholder="输入主题搜索脚本…")
        self.combo.setMinimumHeight(34)
        v.addWidget(self.combo)
        tip = QLabel("脚本来自服务端分镜脚本库；为空时可先在「分镜脚本创作」页保存脚本。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b93a3; font-size:12px;")
        v.addWidget(tip)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("确定")
        ok.setObjectName("primary_button")
        ok.setFixedSize(84, 32)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondary_button")
        cancel.setFixedSize(84, 32)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        v.addLayout(btns)
        self._items = []
        self._loader = None
        self._load()

    def _load(self):
        from utils.storyboard_client import list_scripts
        from utils.thread_worker import TaskWorker as Worker
        self.combo.addItem("加载脚本中…", "")
        self._loader = Worker(lambda: list_scripts(page=1, page_size=100))
        self._loader.finished.connect(self._on_loaded)
        self._loader.error.connect(lambda msg: self._on_loaded(None))
        self._loader.start()

    def _on_loaded(self, items):
        self._items = items or []
        self.combo.blockSignals(True)
        self.combo.clear()
        if not self._items:
            self.combo.addItem("（暂无分镜脚本或服务端不可达）", "")
        else:
            for it in self._items:
                sid = it.get("id")
                if not sid:
                    continue
                label = f"[{it.get('topic', '')}] {it.get('shot_count', 0)}镜"
                if it.get("saved_at"):
                    label += f" · {it['saved_at']}"
                self.combo.addItem(label, str(sid))
        self.combo.blockSignals(False)

    def selected_item(self):
        """返回当前选中脚本条目（dict），未选择返回 {}。"""
        sid = str(self.combo.currentData() or "")
        for it in self._items:
            if str(it.get("id") or "") == sid:
                return it
        return {}


class _ChatPanel(QWidget):
    """AI 对话面板：模式/模型切换 + 多轮气泡 + 输入发送 + 智能体快捷条。

    附件/产品/素材/脚本选择后显示在输入框上方的「上下文」区（不插入输入框），
    不删除则每次发送都作为背景信息携带；点胶囊 ✕ 移除。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []       # OpenAI 风格消息（用户输入原文）
        self._mode = "agent"     # agent=智能体对话 / llm=通用对话
        self._model = ""
        self._worker = None
        self._model_loader = None
        self._agent_loader = None
        self._pending = None     # 等待回复的占位气泡
        self._agents = []        # 服务端智能体列表缓存（斜杠菜单与快捷条共用）
        self._busy_timer = None  # 发送后 120s 超时自动恢复输入（防 worker 卡住）
        # 对话上下文（选择区显示，不删除则每次发送都携带）
        self._ctx_attachments = []   # [{"name", "path"}]
        self._ctx_product = None     # dict 或 None（产品单选覆盖）
        self._ctx_materials = []     # [dict]（按 material_id 去重）
        self._ctx_scripts = []       # [dict]（按 id 去重）
        self._setup_ui()
        self._load_models()
        self._load_agents()

    def _setup_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("💬 AI 对话")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        top.addWidget(title)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("🤖 智能体对话", "agent")
        self.mode_combo.addItem("💬 通用对话", "llm")
        self.mode_combo.setToolTip(
            "智能体对话：服务端智能体循环执行，可调用已注册能力；\n"
            "通用对话：纯大模型多轮问答（DeepSeek 代理）。")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self.mode_combo)
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("对话模型（来自服务端 /llm/models）")
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        top.addWidget(self.model_combo)
        top.addStretch()
        btn_clear = mdi_button("清空对话", "broom")
        btn_clear.setObjectName("secondary_button")
        btn_clear.setFixedHeight(30)
        btn_clear.clicked.connect(self.clear_chat)
        top.addWidget(btn_clear)
        v.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._msg_lay = QVBoxLayout(self._content)
        self._msg_lay.setContentsMargins(4, 2, 4, 2)
        self._msg_lay.setSpacing(10)
        self._msg_lay.addStretch()
        self._scroll.setWidget(self._content)
        v.addWidget(self._scroll, 1)

        # 工具行：选择的产品/素材/脚本/附件加入对话上下文（显示在输入框上方，不删除持续携带）
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        self.btn_attach = QPushButton("📎 附件")
        self.btn_attach.setObjectName("secondary_button")
        self.btn_attach.setFixedHeight(30)
        self.btn_attach.setCursor(Qt.PointingHandCursor)
        self.btn_attach.setToolTip("选择本地文件加入对话上下文（不删除则每次对话都携带）")
        self.btn_attach.clicked.connect(self._pick_attachments)
        tool_row.addWidget(self.btn_attach)
        self.btn_product = QPushButton("📦 产品")
        self.btn_product.setObjectName("secondary_button")
        self.btn_product.setFixedHeight(30)
        self.btn_product.setCursor(Qt.PointingHandCursor)
        self.btn_product.setToolTip("从产品资料库选择产品加入对话上下文（不删除则每次对话都携带）")
        self.btn_product.clicked.connect(self._pick_product)
        tool_row.addWidget(self.btn_product)
        self.btn_material = QPushButton("📁 素材")
        self.btn_material.setObjectName("secondary_button")
        self.btn_material.setFixedHeight(30)
        self.btn_material.setCursor(Qt.PointingHandCursor)
        self.btn_material.setToolTip("从服务端素材库选择素材加入对话上下文（不删除则每次对话都携带）")
        self.btn_material.clicked.connect(self._pick_material)
        tool_row.addWidget(self.btn_material)
        self.btn_script = QPushButton("📜 脚本")
        self.btn_script.setObjectName("secondary_button")
        self.btn_script.setFixedHeight(30)
        self.btn_script.setCursor(Qt.PointingHandCursor)
        self.btn_script.setToolTip("从服务端分镜脚本库选择脚本加入对话上下文（不删除则每次对话都携带）")
        self.btn_script.clicked.connect(self._pick_script)
        tool_row.addWidget(self.btn_script)
        self.chk_plan = QCheckBox("🧭 转编排任务")
        self.chk_plan.setCursor(Qt.PointingHandCursor)
        self.chk_plan.setToolTip("开启后：智能体对话以编排任务方式提交（mode=plan），"
                                 "服务端先拆解为 plan 再自动执行，回复返回任务 ID")
        tool_row.addWidget(self.chk_plan)
        tool_row.addStretch()
        v.addLayout(tool_row)

        # 对话上下文条：选择项显示区（不随发送清空，点击胶囊 ✕ 移除）
        ctx_row = QHBoxLayout()
        ctx_row.setSpacing(8)
        ctx_label = QLabel("📌 上下文")
        ctx_label.setStyleSheet("color:#8b93a3; font-size:12px; font-weight:600;")
        ctx_row.addWidget(ctx_label)
        self._ctx_scroll = QScrollArea()
        self._ctx_scroll.setWidgetResizable(True)
        self._ctx_scroll.setFrameShape(QFrame.NoFrame)
        self._ctx_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._ctx_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ctx_scroll.setFixedHeight(32)
        ctx_content = QWidget()
        self._ctx_lay = QHBoxLayout(ctx_content)
        self._ctx_lay.setContentsMargins(0, 0, 0, 0)
        self._ctx_lay.setSpacing(6)
        self._ctx_lay.addStretch()
        self._ctx_scroll.setWidget(ctx_content)
        ctx_row.addWidget(self._ctx_scroll, 1)
        self._ctx_row_widget = QWidget()
        self._ctx_row_widget.setLayout(ctx_row)
        self._ctx_row_widget.setVisible(False)
        v.addWidget(self._ctx_row_widget)

        in_row = QHBoxLayout()
        in_row.setSpacing(8)
        self.input_edit = _ChatInput()
        self.input_edit.setFixedHeight(64)
        self.input_edit.setPlaceholderText("输入消息，回车发送（Shift+回车换行）；输入 / 快速唤起智能体…")
        self.input_edit.sendRequested.connect(self._on_send)
        # 斜杠快捷菜单（/ 唤起智能体，参考 Cherry Studio 命令菜单；父级挂面板便于跟随主窗口）
        self._slash_popup = _SlashPopup(self)
        self._slash_popup.set_input(self.input_edit)
        self.input_edit.set_slash_popup(self._slash_popup)
        in_row.addWidget(self.input_edit, 1)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary_button")
        self.send_btn.setFixedSize(84, 40)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send)
        in_row.addWidget(self.send_btn)
        v.addLayout(in_row)

        # 智能体快捷条（对话框下方：服务端智能体 → 点击经对话唤起执行）
        self._agent_bar = _AgentBar()
        self._agent_bar.agentClicked.connect(self._on_agent_clicked)
        v.addWidget(self._agent_bar)

        self.append_bubble(
            "assistant",
            "你好，我是 TinTin 智能体助手 🤖\n\n"
            "可以问我电商短视频运营的问题，也可以直接说需求，我会拆解并帮你执行；\n"
            "选择 📎附件 / 📦产品 / 📁素材 / 📜脚本会加入对话上下文（显示在输入框上方，"
            "不删除则每次对话都携带），点「发送」交给智能体执行；输入 / 可快速唤起智能体；\n"
            "勾选 🧭转编排任务 后，对话会先转为编排任务提交服务端自动执行（回复返回任务 ID）。")

    # ── 消息渲染 ─────────────────────────────────────────
    def append_bubble(self, role, text):
        """追加气泡到消息区底部，返回气泡对象（供占位更新）。"""
        bubble = _ChatBubble(role, text)
        self._msg_lay.insertWidget(self._msg_lay.count() - 1, bubble)
        QTimer.singleShot(0, self._scroll_to_bottom)
        return bubble

    def clear_chat(self):
        while self._msg_lay.count() > 1:
            item = self._msg_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._history.clear()
        self._ctx_attachments = []
        self._ctx_product = None
        self._ctx_materials = []
        self._ctx_scripts = []
        self._rebuild_ctx_bar()
        self.append_bubble("assistant", "对话已清空，有什么想聊的？")

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 发送/回复 ─────────────────────────────────────────
    def _on_send(self):
        if self._worker is not None and self._worker.isRunning():
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self.append_bubble("user", text)
        # 发送内容 = 用户输入 + 当前对话上下文（选择项不删除则持续携带）
        ctx = self._build_context_text()
        message = f"{text}\n\n{ctx}" if ctx else text
        self._history.append({"role": "user", "content": text})
        self._trim_history()
        self._set_busy(True)
        if self._busy_timer is not None:
            self._busy_timer.stop()
        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._on_busy_timeout)
        self._busy_timer.start(120000)
        self._pending = self.append_bubble("assistant", "⏳ 思考中…")
        self._worker = _ChatWorker(self._mode, self._history, self._model,
                                   message=message,
                                   plan_mode=self.chk_plan.isChecked())
        self._worker.done.connect(self._on_reply_ok)
        self._worker.failed.connect(self._on_reply_failed)
        self._worker.start()

    def _product_summary(self, item):
        """产品上下文文本：品牌/型号/品类/货号 + 性能 + 卖点。"""
        lines = []
        for key, label in (("brand", "品牌"), ("model", "型号"),
                           ("category", "品类"), ("goods_no", "货号")):
            val = str(item.get(key) or "").strip()
            if val:
                lines.append(f"{label}:{val}")
        feat = str(item.get("features") or "").strip()
        sell = str(item.get("selling_points") or "").strip()
        if feat:
            lines.append(f"性能:{feat[:300]}")
        if sell:
            lines.append(f"卖点:{sell[:300]}")
        return "\n".join(lines)

    @staticmethod
    def _material_summary(item):
        """素材上下文文本：ID/文件名/类型/品牌型号/路径。"""
        mid = str(item.get("id") or item.get("material_id") or "")
        name = item.get("filename") or mid or "未命名"
        mtype = _MEDIA_TYPE_LABEL.get((item.get("media_type") or "").lower(), "素材")
        lines = [f"素材ID:{mid}", f"文件名:{name}", f"类型:{mtype}"]
        for key, label in (("brand", "品牌"), ("model", "型号"), ("category", "分类")):
            val = str(item.get(key) or "").strip()
            if val:
                lines.append(f"{label}:{val}")
        path = str(item.get("path") or "").strip()
        if path:
            lines.append(f"路径:{path}")
        return "\n".join(lines)

    @staticmethod
    def _script_summary(item):
        """分镜脚本上下文文本：ID/主题/镜头数/画幅/保存时间。"""
        lines = [f"脚本ID:{item.get('id') or ''}"]
        topic = str(item.get("topic") or "").strip()
        if topic:
            lines.append(f"主题:{topic}")
        lines.append(f"镜头数:{item.get('shot_count') or 0}")
        ratio = str(item.get("ratio") or "").strip()
        if ratio:
            lines.append(f"画幅:{ratio}")
        saved = str(item.get("saved_at") or "").strip()
        if saved:
            lines.append(f"保存时间:{saved}")
        return "\n".join(lines)

    def _on_reply_ok(self, reply):
        if self._busy_timer is not None:
            self._busy_timer.stop()
            self._busy_timer = None
        self._set_busy(False)
        self._history.append({"role": "assistant", "content": reply})
        self._trim_history()
        if self._pending is not None:
            self._pending.set_text(reply)
            bubble = self._pending
            self._pending = None
        else:
            bubble = self.append_bubble("assistant", reply)
        # 回复含成片视频资产 → 气泡挂播放/下载按钮
        url, tid = self._detect_video_asset(reply)
        if url:
            bubble.set_asset_actions(url, title=f"任务 #{tid}", tid=tid)

    def _detect_video_asset(self, text):
        """从智能体回复中提取成片视频地址（供气泡挂播放/下载按钮）。

        识别顺序：① 文本中带视频特征的绝对 URL；② /editor/render/{id}/result 相对路径；
        ③ 「任务ID：#N」+ 成片语境 → 服务端 render 结果端点兜底。
        返回 (url, task_id)，无则 ("", "")。
        """
        text = text or ""
        # ① 绝对 URL（含视频特征）
        for m in _URL_RE.finditer(text):
            u = m.group(0).rstrip(".,;:!?")
            if any(k in u.lower() for k in _VIDEO_URL_HINTS):
                return u, ""
        # ② 相对路径
        m = _REL_URL_RE.search(text)
        if m:
            base = self._server_base()
            if base:
                return base + m.group(0), m.group(1)
        # ③ 任务 ID 兜底（仅当消息含成片/渲染语境，避免误判普通编号）
        if re.search(r"(成片|渲染|一键成片|render)", text, re.I):
            m = re.search(r"(?:任务\s*ID|task\s*id)\s*[:：]?\s*#?(\d+)", text, re.I)
            if m:
                base = self._server_base()
                if base:
                    return f"{base}/editor/render/{m.group(1)}/result", m.group(1)
        return "", ""

    @staticmethod
    def _server_base():
        """读取 compute_server_url（与成片任务页一致）。"""
        from utils import scheduled_task_client as stc
        try:
            return stc._server_url()
        except Exception:
            return ""

    def _on_reply_failed(self, err):
        if self._busy_timer is not None:
            self._busy_timer.stop()
            self._busy_timer = None
        self._set_busy(False)
        if self._pending is not None:
            self._pending.set_text(f"⚠️ 出错了：{err}")
            self._pending = None

    def _on_busy_timeout(self):
        """请求超过 120 秒未返回：自动恢复输入，避免服务端无响应时界面卡死。"""
        self._busy_timer = None
        if self._worker is not None and self._worker.isRunning():
            self._set_busy(False)
            if self._pending is not None:
                self._pending.set_text(
                    "⏳ 请求超过 120 秒未返回，已恢复输入；回复稍后到达会直接显示。")

    def _set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("思考中…" if busy else "发送")
        self.input_edit.setEnabled(not busy)

    def _trim_history(self):
        """上下文截断：保留最近 12 条且总字符不超过 8000。"""
        while (len(self._history) > 12
               or sum(len(m.get("content") or "") for m in self._history) > 8000):
            self._history.pop(0)

    # ── 模式 / 模型 ─────────────────────────────────────────
    def _on_mode_changed(self, idx):
        self._mode = self.mode_combo.itemData(idx) or "agent"
        self._history.clear()
        # 切换对话模式视为新会话：清空对话上下文
        self._ctx_attachments = []
        self._ctx_product = None
        self._ctx_materials = []
        self._ctx_scripts = []
        self._rebuild_ctx_bar()
        mode_name = "智能体对话" if self._mode == "agent" else "通用对话"
        self.append_bubble("assistant", f"已切换到【{mode_name}】。")

    def _load_models(self):
        self.model_combo.addItem("加载模型中…", "")
        self._model_loader = _ModelLoader()
        self._model_loader.done.connect(self._on_models_loaded)
        self._model_loader.start()

    def _on_models_loaded(self, models):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        default = ""
        try:
            from utils.llm_proxy import _get_default_model
            default = _get_default_model()
        except Exception:
            pass
        for m in models:
            mid = m.get("id") or ""
            name = m.get("name") or mid
            provider = m.get("provider_name") or m.get("provider") or ""
            self.model_combo.addItem(f"{name}（{provider}）" if provider else name, mid)
        if self.model_combo.count() == 0:
            self.model_combo.addItem("默认模型", default)
        idx = self.model_combo.findData(default)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)
        self._model = self.model_combo.currentData() or ""

    def _on_model_changed(self, idx):
        self._model = self.model_combo.itemData(idx) or ""

    # ── 智能体快捷唤起 ─────────────────────────────────────
    def _load_agents(self):
        self._agent_loader = _AgentLoader()
        self._agent_loader.done.connect(self._on_agents_loaded)
        self._agent_loader.start()

    def _on_agents_loaded(self, agents):
        self._agents = agents
        self._agent_bar.set_agents(agents)
        self._slash_popup.set_agents(agents)

    def _on_agent_clicked(self, agent):
        """点击智能体：切到智能体对话，把唤醒词插入输入框开头（已存在则替换旧智能体）。"""
        if self._mode != "agent":
            idx = self.mode_combo.findData("agent")
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        name = agent.get("name") or agent.get("id") or "该智能体"
        desc = (agent.get("desc") or "").strip()
        prefix = f"请【{name}】智能体执行：{desc}" if desc else f"请【{name}】智能体执行"
        old = self.input_edit.toPlainText()
        first_line = old.split("\n", 1)[0]
        if first_line.startswith("请【") and "智能体执行：" in first_line:
            old = old.split("\n", 1)[1].lstrip("\n") if "\n" in old else ""
        self.input_edit.setPlainText((prefix + "\n\n" + old) if old else prefix)
        self.input_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.input_edit.setFocus()

    # ── 对话上下文（选择区显示，不随发送清空）────────────────────────
    def _make_chip(self, label, key):
        """上下文胶囊：显示选择项，点击移除。"""
        chip = QPushButton(f"{label}  ✕")
        chip.setFixedHeight(24)
        chip.setCursor(Qt.PointingHandCursor)
        chip.setToolTip("点击移除该上下文项（不删除则每次对话都携带）")
        chip.setStyleSheet(
            "QPushButton { background:#1d212b; border:1px solid #2c3344; border-radius:12px;"
            " color:#c9d1de; padding:0 10px; font-size:12px; }"
            " QPushButton:hover { border-color:#e74c3c; color:#e74c3c; }")
        chip.clicked.connect(lambda: self._remove_ctx(key))
        return chip

    def _rebuild_ctx_bar(self):
        """按当前上下文状态重建胶囊行（保留末尾 stretch）。"""
        while self._ctx_lay.count() > 1:
            item = self._ctx_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        idx = 0

        def add(label, key):
            nonlocal idx
            self._ctx_lay.insertWidget(idx, self._make_chip(label, key))
            idx += 1

        if self._ctx_product:
            add(f"📦 {self._ctx_product.get('brand', '')} / {self._ctx_product.get('model', '')}",
                ("product",))
        for i, m in enumerate(self._ctx_materials):
            mid = str(m.get("id") or m.get("material_id") or "")
            name = m.get("filename") or mid or "未命名"
            mtype = _MEDIA_TYPE_LABEL.get((m.get("media_type") or "").lower(), "素材")
            add(f"📁 [{mtype}] {name}", ("material", i))
        for i, s in enumerate(self._ctx_scripts):
            add(f"📜 [{s.get('topic', '')}] {s.get('shot_count', 0)}镜", ("script", i))
        for i, a in enumerate(self._ctx_attachments):
            add(f"📎 {a['name']}", ("attachment", i))
        self._ctx_row_widget.setVisible(self._ctx_lay.count() > 1)

    def _remove_ctx(self, key):
        """移除一个上下文项（kind, index）。"""
        kind = key[0]
        if kind == "product":
            self._ctx_product = None
        elif kind == "material":
            i = key[1]
            if 0 <= i < len(self._ctx_materials):
                self._ctx_materials.pop(i)
        elif kind == "script":
            i = key[1]
            if 0 <= i < len(self._ctx_scripts):
                self._ctx_scripts.pop(i)
        elif kind == "attachment":
            i = key[1]
            if 0 <= i < len(self._ctx_attachments):
                self._ctx_attachments.pop(i)
        self._rebuild_ctx_bar()

    def _build_context_text(self):
        """当前选择上下文文本：每次发送都会拼接到消息里。"""
        parts = []
        if self._ctx_product:
            parts.append("【产品】\n" + self._product_summary(self._ctx_product))
        for m in self._ctx_materials:
            parts.append("【素材】\n" + self._material_summary(m))
        for s in self._ctx_scripts:
            parts.append("【脚本】\n" + self._script_summary(s))
        if self._ctx_attachments:
            lines = [f"- {a['name']}（{a['path']}）" for a in self._ctx_attachments]
            parts.append("【附件】\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def _pick_attachments(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择对话附件", "", "所有文件 (*.*)")
        if not files:
            return
        for p in files:
            if not any(a["path"] == p for a in self._ctx_attachments):
                self._ctx_attachments.append({"name": os.path.basename(p), "path": p})
        self._rebuild_ctx_bar()

    def _pick_product(self):
        dlg = _ProductPickerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            item = dlg.selected_item()
            if item:
                self._ctx_product = item   # 产品单选：重复选择直接覆盖
                self._rebuild_ctx_bar()

    def _pick_material(self):
        dlg = _MaterialPickerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            item = dlg.selected_item()
            if item:
                mid = str(item.get("id") or item.get("material_id") or "")
                if mid and not any(
                        str(m.get("id") or m.get("material_id") or "") == mid
                        for m in self._ctx_materials):
                    self._ctx_materials.append(item)
                self._rebuild_ctx_bar()

    def _pick_script(self):
        dlg = _ScriptPickerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            item = dlg.selected_item()
            if item:
                sid = str(item.get("id") or "")
                if sid and not any(str(s.get("id") or "") == sid for s in self._ctx_scripts):
                    self._ctx_scripts.append(item)
                self._rebuild_ctx_bar()


class AgentHomePage:
    """运营工作台首页（高频任务卡片 + AI 对话面板）。"""

    def __init__(self, parent_widget, main_window):
        self.parent_widget = parent_widget
        self.main_window = main_window
        self.setup()

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(14)

        heading = QLabel("✨ 螺丝钉智能体工作台")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading)
        sub = QLabel("输入需求或点一个任务卡片——剩下的交给智能体。")
        sub.setStyleSheet("color:#8b93a3; font-size:13px;")
        layout.addWidget(sub)

        # 高频任务卡片（紧贴标题下方）
        card_title = QLabel("高频任务")
        card_title.setStyleSheet("font-size:15px; font-weight:700;")
        layout.addWidget(card_title)
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (title, icon, desc, idx, accent) in enumerate(_TASK_CARDS):
            card = _TaskCard(title, icon, desc, accent)
            card.clicked.connect(lambda checked=False, i=idx: self._goto(i))
            grid.addWidget(card, i // 4, i % 4)
        layout.addLayout(grid)

        # AI 对话面板（占剩余空间）
        self._chat_panel = _ChatPanel()
        layout.addWidget(self._chat_panel, 1)

    def _goto(self, page, tab=None):
        """跳转到指定页面，若目标页有 Tab 则自动切到对应 Tab。"""
        self.main_window.switch_page(page)
        if tab is not None:
            QTimer.singleShot(0, lambda: self._activate_tab(page, tab))

    def _activate_tab(self, page, tab):
        try:
            w = self.main_window.content_stack.widget(page)
            if w is None:
                return
            tabs = w.findChild(QTabWidget)
            if tabs is not None and 0 <= tab < tabs.count():
                tabs.setCurrentIndex(tab)
        except Exception as e:
            log.warning(f"激活页面 Tab 失败: {e}")
