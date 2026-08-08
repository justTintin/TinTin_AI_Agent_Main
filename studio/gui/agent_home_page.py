# -*- coding: utf-8 -*-
"""运营工作台首页：高频任务卡片 + 一句话需求（LLM 意图路由）+ AI 对话面板。

一句话需求 → utils.agent_router.route_text()：
  1. 优先 LLM 意图识别（服务端 /llm/chat/completions）；
  2. 超时/失败回退本地关键词匹配；
  3. 返回 (页面 index, tab index) 或标记「多智能体组合任务」。

AI 对话（参考 Cherry Studio 对话体验，服务端暂不支持流式 → 整段返回）：
  - 智能体对话：POST /agent/chat，服务端智能体循环执行，可调用注册能力；
  - 通用对话：POST /llm/chat/completions，DeepSeek 代理多轮问答；
  模型下拉来自 GET /llm/models，上下文自动截断防超长。
"""
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QLineEdit, QFrame, QGridLayout, QWidget,
                               QMessageBox, QTabWidget, QComboBox, QTextEdit,
                               QTextBrowser, QScrollArea)
from utils.gui_icons import mdi_icon, mdi_button
from utils.logger_utils import log

# (示例文案, 直达目标页 index)
_ASK_CHIPS = [("带货 15 秒竖屏", 33), ("直播切片", 18), ("声音克隆", 20), ("封面制作", 32)]

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


class _IntentThread(QThread):
    """后台执行一句话意图路由（LLM + 关键词兜底），不阻塞 UI。"""
    done = Signal(object)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text

    def run(self):
        try:
            from utils.agent_router import route_text
            self.done.emit(route_text(self._text))
        except Exception as e:
            log.warning(f"意图路由失败: {e}")
            self.done.emit(None)


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


class _ChatPanel(QWidget):
    """AI 对话面板：模式/模型切换 + 多轮气泡 + 输入发送（参考 Cherry Studio 对话体验）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []       # OpenAI 风格消息（不含 system）
        self._mode = "agent"     # agent=智能体对话 / llm=通用对话
        self._model = ""
        self._worker = None
        self._model_loader = None
        self._pending = None     # 等待回复的占位气泡
        self._setup_ui()
        self._load_models()

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

        self.append_bubble(
            "assistant",
            "你好，我是 TinTin 智能体助手 🤖\n\n"
            "可以问我电商短视频运营的问题，也可以直接说需求，我会拆解并帮你执行。")

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


class AgentHomePage:
    """运营工作台首页（高频任务卡片 + 一句话需求 + AI 对话面板）。"""

    def __init__(self, parent_widget, main_window):
        self.parent_widget = parent_widget
        self.main_window = main_window
        self._intent_thread = None
        self._ask_go_btn = None
        self.setup()

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(14)

        heading = QLabel("✨ 螺丝钉智能体工作台")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading)
        sub = QLabel("说一句话，或点一个任务卡片——剩下的交给智能体。")
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

        # 一句话需求
        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText("例如：帮我把这段文案做成带货视频；或：生成一个数字人视频")
        self.ask_input.setFixedHeight(40)
        self.ask_input.returnPressed.connect(self._on_ask_go)
        ask_row.addWidget(self.ask_input, 1)
        btn_go = mdi_button("开始", "rocket")
        btn_go.setObjectName("primary_button")
        btn_go.setFixedHeight(40)
        btn_go.clicked.connect(self._on_ask_go)
        self._ask_go_btn = btn_go
        ask_row.addWidget(btn_go)
        layout.addLayout(ask_row)

        # 示例 chips（点击直达对应功能）
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for text, target in _ASK_CHIPS:
            c = QPushButton(text)
            c.setFixedHeight(28)
            c.setCursor(Qt.PointingHandCursor)
            c.setStyleSheet(
                "QPushButton { background:#1d212b; border:1px solid #262b36; "
                "border-radius:14px; color:#8b93a3; padding:2px 12px; font-size:12px; } "
                "QPushButton:hover { border-color:#60a5fa; color:#60a5fa; }")
            c.clicked.connect(lambda checked=False, t=target: self._goto(t))
            chips.addWidget(c)
        chips.addStretch()
        layout.addLayout(chips)

        # AI 对话面板（占剩余空间）
        self._chat_panel = _ChatPanel()
        layout.addWidget(self._chat_panel, 1)

    # ── 一句话需求路由 ─────────────────────────────────────
    def _on_ask_go(self):
        text = self.ask_input.text().strip()
        if not text:
            return
        self._ask_text = text  # 供多智能体编排提交使用
        if self._intent_thread and self._intent_thread.isRunning():
            return
        self._intent_thread = _IntentThread(text)
        self._intent_thread.done.connect(self._on_intent_ready)
        self._intent_thread.start()
        if self._ask_go_btn is not None:
            self._ask_go_btn.setEnabled(False)
            self._ask_go_btn.setText("⏳ 识别中...")

    def _on_intent_ready(self, result):
        if self._ask_go_btn is not None:
            self._ask_go_btn.setEnabled(True)
            self._ask_go_btn.setText("开始")
        if not result:
            return
        if result.get("multi_agent"):
            self._submit_orchestration(
                getattr(self, "_ask_text", "") or "",
                fallback_page=result.get("page", 33))
            return
        self._goto(result.get("page", 33), result.get("tab"))

    # ── 多智能体编排：LLM 拆 plan → 提交服务端 ───────────────────────────
    def _submit_orchestration(self, text, fallback_page=33):
        """多智能体需求：拆解 plan → POST /agent/tasks(mode=execute) → 跳定时任务页查看。

        拆解失败/服务端不可用时兑底：提示并带用户去最相关的功能入口。
        """
        if not text:
            return
        from utils.thread_worker import TaskWorker as Worker
        self._ask_go_btn_set_busy(True, "⏳ 拆解编排中...")

        def _do():
            from utils.agent_router import build_plan
            from utils import agent_client as ac
            plan = build_plan(text)
            if not plan:
                return None, None
            t = ac.create_task(goal=plan.get("goal"), plan=plan, mode="execute")
            return plan, t

        def _ok(result):
            self._ask_go_btn_set_busy(False, "开始")
            plan, t = result
            if not plan:
                QMessageBox.information(
                    self.parent_widget, "云端智能体",
                    "这条需求需要组合多个能力，但拆解失败（服务端 LLM 或注册表不可用），\n"
                    "先带你去最相关的功能入口。")
                self._goto(fallback_page)
                return
            if not t:
                QMessageBox.warning(
                    self.parent_widget, "提交失败",
                    "编排任务提交服务端失败，请确认服务端在线后重试。")
                return
            log.info(f"[工作台] 编排任务已提交 task_id={t.get('id')}")
            mw = self.main_window
            if mw is not None and hasattr(mw, "switch_page"):
                mw.switch_page(47)  # 定时任务页：服务端任务 Tab 可查看/确认编排任务
            QMessageBox.information(
                self.parent_widget, "已提交",
                "任务已拆解并提交服务端，按注册的智能体自动分解执行。\n"
                f"task_id: {t.get('id')}（可在「定时任务 → 最近编排任务」查看进度与人工确认）")

        def _err(e):
            self._ask_go_btn_set_busy(False, "开始")
            QMessageBox.warning(self.parent_widget, "云端智能体异常", f"云端智能体异常：{e}")

        w = Worker(_do)
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._intent_thread = w  # 持有引用：QThread 被 GC 回收会触发 Qt fatal 崩溃
        w.start()

    def _ask_go_btn_set_busy(self, busy, text):
        """开始按钮忙碌态切换。"""
        if self._ask_go_btn is not None:
            self._ask_go_btn.setEnabled(not busy)
            self._ask_go_btn.setText(text)

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
