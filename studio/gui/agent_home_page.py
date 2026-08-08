# -*- coding: utf-8 -*-
"""运营工作台首页：高频任务卡片 + AI 对话面板（服务端智能体总结为 Skill 供对话调用）。

AI 对话（参考 Cherry Studio 对话体验，服务端暂不支持流式 → 整段返回）：
  - 智能体对话：POST /agent/chat，服务端智能体循环执行，可调用注册能力；
  - 通用对话：POST /llm/chat/completions，DeepSeek 代理多轮问答；
  模型下拉来自 GET /llm/models，上下文自动截断防超长。

Skill 区：把服务端 /agent/registry 提供的智能体能力总结为常用技能按钮，
放在对话框下方，点击后自动切到智能体对话并发送唤醒消息，由对话执行该技能。
"""
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QFrame, QGridLayout, QWidget,
                               QTabWidget, QComboBox, QTextEdit,
                               QTextBrowser, QScrollArea)
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
    """对话输入框：回车发送，Shift+回车换行。"""
    sendRequested = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.sendRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _MdBrowser(QTextBrowser):
    """只读 Markdown 气泡浏览器：随内容自适应高度，宽度不超上限。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenExternalLinks(True)
        self.setMaximumWidth(720)
        self.setMinimumWidth(200)
        self.document().contentsChanged.connect(self._adjust_height)

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
    """对话气泡：头像 + Markdown 内容；用户右对齐蓝底，助手左对齐深灰底。"""

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
            self._browser.setStyleSheet(
                "QTextBrowser { background:#2f6fed; color:#ffffff;"
                " border-radius:10px; padding:8px 12px; }")
        else:
            self._browser.setStyleSheet(
                "QTextBrowser { background:#232838; color:#e2e6ef;"
                " border-radius:10px; padding:8px 12px; }")
        self.set_text(text)

        if is_user:
            lay.addStretch()
            lay.addWidget(self._browser)
            lay.addWidget(avatar)
        else:
            lay.addWidget(avatar)
            lay.addWidget(self._browser)
            lay.addStretch()

    def set_text(self, text):
        self._browser.setMarkdown(text or "")


class _ChatWorker(QThread):
    """后台对话请求：智能体模式走 /agent/chat，通用模式走 /llm/chat/completions。"""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, mode, history, model, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._history = history
        self._model = model

    def run(self):
        try:
            if self._mode == "agent":
                from utils.agent_client import agent_chat
                msgs = list(self._history or [])
                message = msgs[-1]["content"] if msgs else ""
                reply = agent_chat(message, history=msgs[:-1] or None,
                                   model=self._model or None, max_rounds=3)
            else:
                from utils.llm_proxy import llm_chat_messages
                msgs = list(self._history or [])
                if not msgs:
                    msgs.append({"role": "system", "content": _SYSTEM_PROMPT})
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


class _SkillLoader(QThread):
    """后台加载服务端智能体能力（GET /agent/registry），过滤基础设施类 → 技能列表。"""
    done = Signal(list)

    def run(self):
        try:
            from utils.agent_client import get_registry
            data = get_registry(include_external=False, timeout=8) or {}
            skills = []
            for c in (data.get("capabilities") or []):
                tags = c.get("tags") or []
                if any(t in ("infra", "external") for t in tags):
                    continue  # 注册表/任务登记/任务树等基础设施不当作对话技能
                skills.append({
                    "id": c.get("id") or "",
                    "name": c.get("name") or c.get("id") or "",
                    "desc": c.get("description") or "",
                })
            self.done.emit(skills)
        except Exception as e:
            log.warning(f"[工作台对话] 加载技能列表失败: {e}")
            self.done.emit([])


class _SkillBar(QWidget):
    """技能快捷条：横向滚动的 Skill 按钮（悬停显示唤醒提示词，点击经对话调用）。"""
    skillClicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("🛠️ 技能")
        lbl.setStyleSheet("color:#8b93a3; font-size:12px; font-weight:600;")
        row.addWidget(lbl)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(34)
        content = QWidget()
        self._lay = QHBoxLayout(content)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        self._lay.addStretch()
        self._scroll.setWidget(content)
        row.addWidget(self._scroll, 1)

    def set_skills(self, skills):
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for s in skills:
            btn = QPushButton(s.get("name") or s.get("id") or "?")
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            desc = s.get("desc") or ""
            btn.setToolTip(f"{desc}\n点击后通过对话调用该技能")
            btn.setStyleSheet(
                "QPushButton { background:#1d212b; border:1px solid #262b36; "
                "border-radius:13px; color:#c9d1de; padding:0 12px; font-size:12px; } "
                "QPushButton:hover { border-color:#34d399; color:#34d399; }")
            btn.clicked.connect(lambda checked=False, sk=s: self.skillClicked.emit(sk))
            self._lay.insertWidget(self._lay.count() - 1, btn)


class _ChatPanel(QWidget):
    """AI 对话面板：模式/模型切换 + 多轮气泡 + 输入发送 + 技能快捷条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []       # OpenAI 风格消息（不含 system）
        self._mode = "agent"     # agent=智能体对话 / llm=通用对话
        self._model = ""
        self._worker = None
        self._model_loader = None
        self._skill_loader = None
        self._pending = None     # 等待回复的占位气泡
        self._setup_ui()
        self._load_models()
        self._load_skills()

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

        in_row = QHBoxLayout()
        in_row.setSpacing(8)
        self.input_edit = _ChatInput()
        self.input_edit.setFixedHeight(64)
        self.input_edit.setPlaceholderText("输入消息，回车发送（Shift+回车换行）…")
        self.input_edit.sendRequested.connect(self._on_send)
        in_row.addWidget(self.input_edit, 1)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary_button")
        self.send_btn.setFixedSize(84, 40)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send)
        in_row.addWidget(self.send_btn)
        v.addLayout(in_row)

        # 技能快捷条（对话框下方：服务端智能体能力 → 点击经对话实现）
        self._skill_bar = _SkillBar()
        self._skill_bar.skillClicked.connect(self._on_skill_clicked)
        v.addWidget(self._skill_bar)

        self.append_bubble(
            "assistant",
            "你好，我是 TinTin 智能体助手 🤖\n\n"
            "可以问我电商短视频运营的问题，也可以直接说需求，我会拆解并帮你执行；\n"
            "下方技能栏是服务端智能体提供的能力，点击即可通过对话调用。")

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
        self._history.append({"role": "user", "content": text})
        self._trim_history()
        self._set_busy(True)
        self._pending = self.append_bubble("assistant", "⏳ 思考中…")
        self._worker = _ChatWorker(self._mode, self._history, self._model)
        self._worker.done.connect(self._on_reply_ok)
        self._worker.failed.connect(self._on_reply_failed)
        self._worker.start()

    def _on_reply_ok(self, reply):
        self._set_busy(False)
        self._history.append({"role": "assistant", "content": reply})
        self._trim_history()
        if self._pending is not None:
            self._pending.set_text(reply)
            self._pending = None

    def _on_reply_failed(self, err):
        self._set_busy(False)
        if self._pending is not None:
            self._pending.set_text(f"⚠️ 出错了：{err}")
            self._pending = None

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

    # ── 技能快捷调用 ─────────────────────────────────────────
    def _load_skills(self):
        self._skill_loader = _SkillLoader()
        self._skill_loader.done.connect(self._on_skills_loaded)
        self._skill_loader.start()

    def _on_skills_loaded(self, skills):
        self._skill_bar.set_skills(skills)

    def _on_skill_clicked(self, skill):
        """点击技能：切到智能体对话模式，发送技能唤醒消息，由对话执行。"""
        if self._mode != "agent":
            idx = self.mode_combo.findData("agent")
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        name = skill.get("name") or skill.get("id") or "该技能"
        desc = (skill.get("desc") or "").strip()
        text = f"请调用【{name}】技能执行：{desc}" if desc else f"请调用【{name}】技能执行"
        self.input_edit.setPlainText(text)
        self._on_send()


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
