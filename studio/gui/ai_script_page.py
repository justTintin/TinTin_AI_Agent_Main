# -*- coding: utf-8 -*-
import os
import sys
import json
import configparser
import traceback
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
                               QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFrame,
                               QSplitter, QWidget, QScrollArea, QProgressBar, QComboBox)
from PySide6.QtCore import Signal, QThread, Qt
from PySide6.QtGui import QColor
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.my_knowledge_manager import MyKnowledgeManager
from config.paths import CONFIG_INI_FILE

class FeishuSyncWorker(BaseWorker):
    finished = Signal(list)

    def __init__(self, app_id, app_secret, app_token, table_id, topic_field, script_field):
        super().__init__()
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.table_id = table_id
        self.topic_field = topic_field
        self.script_field = script_field

    def run(self):
        try:
            import requests
            from utils.http_client import http_get, http_post
            token_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
            payload = {"app_id": self.app_id, "app_secret": self.app_secret}
            res = http_post(token_url, json=payload, timeout=10)
            if res.status_code != 200:
                raise RuntimeError(f"获取飞书 token 失败: HTTP {res.status_code} - {res.text}")
            token_data = res.json()
            if token_data.get("code") != 0:
                raise RuntimeError(f"获取飞书 token 失败: {token_data.get('msg')}")
            access_token = token_data.get("app_access_token")

            records_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {"page_size": 100}
            res = http_get(records_url, headers=headers, params=params, timeout=15)
            if res.status_code != 200:
                raise RuntimeError(f"获取多维表格记录失败: HTTP {res.status_code} - {res.text}")
            
            data = res.json()
            if data.get("code") != 0:
                raise RuntimeError(f"获取记录失败: {data.get('msg')}")
                
            items = data.get("data", {}).get("items", [])
            parsed_records = []
            for item in items:
                record_id = item.get("record_id")
                fields = item.get("fields", {})
                
                # Debug: log available field names on first record
                if not parsed_records:
                    log.info(f"飞书表格可用字段: {list(fields.keys())}")
                    log.info(f"正在查找的题字段: '{self.topic_field}', 脚本字段: '{self.script_field}'")
                
                topic_val = fields.get(self.topic_field, "")
                if isinstance(topic_val, list):
                    topic_text = "".join([str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in topic_val])
                else:
                    topic_text = str(topic_val) if topic_val else ""
                
                script_val = fields.get(self.script_field, "")
                if isinstance(script_val, list):
                    script_text = "".join([str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in script_val])
                else:
                    script_text = str(script_val)
                    
                status_text = str(fields.get("状态", "未开始"))
                
                parsed_records.append({
                    "id": record_id,
                    "topic": topic_text.strip(),
                    "status": status_text.strip(),
                    "script": script_text.strip()
                })
            self.finished.emit(parsed_records)
        except Exception as e:
            self.error.emit(str(e))

class WebSearchWorker(BaseWorker):
    """联网素材搜索：优先走服务端 POST /material/stock_search（Pexels/Pixabay 免版权，
    支持中文），服务端不可达时才回退客户端直连 DuckDuckGo（国内网络常超时）。"""
    finished = Signal(str)

    def __init__(self, query, kind="video"):
        super().__init__()
        self.query = query
        self.kind = kind

    def run(self):
        try:
            text = self._search_via_server()
            if text:
                self.finished.emit(text)
                return
        except _ServerUnavailable as e:
            log.warning(f"[联网搜索] 服务端 stock_search 不可用（{e}），回退 DuckDuckGo 直连")
        except RuntimeError as e:
            # 服务端可达但明确报错（如未配置 API key 的 503）：直接提示，不回退
            self.error.emit(str(e))
            return
        try:
            self.finished.emit(self._search_duckduckgo())
        except Exception as e:
            self.error.emit(str(e))

    # ── 服务端在线素材搜索（/guide「在线素材搜索 Stock Material」）──
    def _search_via_server(self):
        from utils.http_client import http_post
        base = self._server_url()
        if not base:
            raise _ServerUnavailable("未配置服务端地址")
        res = http_post(f"{base}/material/stock_search",
                        json={"query": self.query.strip(), "kind": self.kind,
                              "page": 1, "per": 10},
                        timeout=20)
        if res.status_code == 503:
            raise RuntimeError(
                "服务端在线素材搜索未启用（HTTP 503）：需服务端 config.yaml 配置 "
                "stock.pexels_api_key / stock.pixabay_api_key 后重试。")
        if res.status_code != 200:
            raise _ServerUnavailable(f"HTTP {res.status_code}")
        items = (res.json() or {}).get("items") or []
        if not items:
            return "未找到相关在线素材，可换关键词重试。"
        provider = (res.json() or {}).get("provider", "")
        lines = [f"以下在线素材免版权可商用（来源：{provider or 'Pexels/Pixabay'}）：", ""]
        for it in items:
            meta = []
            if it.get("duration_sec"):
                meta.append(f"{it['duration_sec']}s")
            if it.get("width") and it.get("height"):
                meta.append(f"{it['width']}x{it['height']}")
            if it.get("author"):
                meta.append(f"作者: {it['author']}")
            lines.append(f"【{it.get('type', '')}】 {' | '.join(meta)}")
            if it.get("thumb"):
                lines.append(f"预览: {it['thumb']}")
            if it.get("url"):
                lines.append(f"直链: {it['url']}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _server_url():
        try:
            from config.paths import AI_CONFIG_FILE
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
                if url:
                    return url
        except Exception:
            pass
        return ""

    # ── 回退：客户端直连 DuckDuckGo（国内网络可能不通）──
    def _search_duckduckgo(self):
        from utils.http_client import http_get
        from lxml import html
        import urllib.parse

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        q = self.query.strip()
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
        res = http_get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            raise RuntimeError(f"搜索请求失败，HTTP 状态码: {res.status_code}")

        tree = html.fromstring(res.text)
        results = []
        bodies = tree.xpath('//div[@class="result__body"]')
        for b in bodies[:5]:
            title_elem = b.xpath('.//a[@class="result__url"]')
            snippet_elem = b.xpath('.//a[@class="result__snippet"]')
            if title_elem and snippet_elem:
                title = title_elem[0].text_content().strip()
                snippet = snippet_elem[0].text_content().strip()
                results.append(f"【标题】: {title}\n【摘要】: {snippet}\n")

        if not results:
            return "未找到相关联网资料，您可以手动输入参考背景。"
        return "\n---\n".join(results)


class _ServerUnavailable(Exception):
    """服务端不可达/无此接口 → 允许回退直连；区别于服务端明确报错（不回退）。"""

class LLMWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, api_url, api_key, model, system_prompt, user_prompt):
        super().__init__()
        self.model = model
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt

    def run(self):
        try:
            from utils.llm_proxy import llm_chat
            content = llm_chat(
                self.system_prompt, self.user_prompt,
                model=self.model, temperature=0.7, timeout=60
            )
            self.finished.emit(content)
        except Exception as e:
            self.error.emit(str(e))

class FeishuUploadWorker(BaseWorker):
    finished = Signal(str)

    def __init__(self, app_id, app_secret, mode, app_token, table_id, record_id, script_field, script_text, folder_token=None, topic_name=None):
        super().__init__()
        self.app_id = app_id
        self.app_secret = app_secret
        self.mode = mode
        self.app_token = app_token
        self.table_id = table_id
        self.record_id = record_id
        self.script_field = script_field
        self.script_text = script_text
        self.folder_token = folder_token
        self.topic_name = topic_name or "新建脚本"

    def run(self):
        try:
            import requests
            from utils.http_client import http_get, http_post, http_put
            token_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
            payload = {"app_id": self.app_id, "app_secret": self.app_secret}
            res = http_post(token_url, json=payload, timeout=10)
            if res.status_code != 200:
                raise RuntimeError(f"获取飞书 token 失败: HTTP {res.status_code} - {res.text}")
            token_data = res.json()
            if token_data.get("code") != 0:
                raise RuntimeError(f"获取飞书 token 失败: {token_data.get('msg')}")
            access_token = token_data.get("app_access_token")
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            if self.mode == 'bitable':
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/{self.record_id}"
                payload = {
                    "fields": {
                        self.script_field: self.script_text
                    }
                }
                res = http_put(url, headers=headers, json=payload, timeout=15)
                if res.status_code != 200:
                    raise RuntimeError(f"同步多维表格失败: HTTP {res.status_code} - {res.text}")
                data = res.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"同步多维表格失败: {data.get('msg')}")
                self.finished.emit("同步成功！已更新飞书多维表格对应单元格。")
            else:
                create_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
                doc_payload = {
                    "title": f"{self.topic_name}_分镜脚本"
                }
                if self.folder_token:
                    doc_payload["folder_token"] = self.folder_token
                res = http_post(create_url, headers=headers, json=doc_payload, timeout=15)
                if res.status_code != 200:
                    raise RuntimeError(f"创建文档失败: HTTP {res.status_code} - {res.text}")
                create_data = res.json()
                if create_data.get("code") != 0:
                    raise RuntimeError(f"创建文档失败: {create_data.get('msg')}")
                
                doc_info = create_data.get("data", {}).get("document", {})
                document_id = doc_info.get("document_id")
                
                blocks_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
                
                children_blocks = []
                children_blocks.append({
                    "block_type": 1,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": f"选题: {self.topic_name}\n"
                                }
                            }
                        ]
                    }
                })
                
                lines = self.script_text.split("\n")
                for line in lines:
                    if line.strip():
                        children_blocks.append({
                            "block_type": 1,
                            "text": {
                                "elements": [
                                    {
                                        "text_run": {
                                            "content": line
                                        }
                                    }
                                ]
                            }
                        })
                
                for i in range(0, len(children_blocks), 100):
                    batch = children_blocks[i:i+100]
                    res = http_post(blocks_url, headers=headers, json={"children": batch}, timeout=15)
                
                doc_url = f"https://open.feishu.cn/docx/{document_id}"
                self.finished.emit(f"生成飞书云文档成功！\n文档链接: {doc_url}")
        except Exception as e:
            self.error.emit(str(e))

from utils.my_knowledge_manager import STYLIZATION_TYPE

from gui.base_page import BasePage
from gui.searchable_combo import SearchableComboBox

class AIScriptPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self.my_kb = MyKnowledgeManager()
        self._selected_stylization = None
        self.records_list = []
        self.selected_record = None

    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        heading = QLabel("✍️ AI 文案创作")
        heading.setObjectName("heading")
        layout.addWidget(heading, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #2e2e32; width: 4px; }")

        # ── 左侧 ──
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(150)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)

        # 卡片 1：飞书选题同步
        card_topics = QFrame()
        card_topics.setObjectName("card")
        topics_layout = QVBoxLayout(card_topics)
        topics_layout.setContentsMargins(20, 16, 20, 16)
        topics_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("📋 飞书选题"))
        title_row.addStretch()
        self.btn_sync_topics = QPushButton("🔧 同步飞书选题")
        self.btn_sync_topics.setObjectName("secondary_button")
        self.btn_sync_topics.clicked.connect(self._sync_feishu_topics)
        self.btn_sync_topics.hide()
        title_row.addWidget(self.btn_sync_topics)
        topics_layout.addLayout(title_row)

        self.table_topics = QTableWidget()
        self.table_topics.setColumnCount(3)
        self.table_topics.setHorizontalHeaderLabels(["选题名称", "状态", "ID"])
        self.table_topics.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_topics.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_topics.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_topics.setSelectionMode(QTableWidget.SingleSelection)
        self.table_topics.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_topics.itemSelectionChanged.connect(self._on_topic_selected)
        self.table_topics.setMinimumWidth(100)
        topics_layout.addWidget(self.table_topics, 1)
        left_layout.addWidget(card_topics, 1)

        # 卡片 2：选题输入
        card_topic = QFrame()
        card_topic.setObjectName("card")
        topic_layout = QVBoxLayout(card_topic)
        topic_layout.setContentsMargins(20, 16, 20, 16)
        topic_layout.setSpacing(10)
        topic_layout.addWidget(QLabel("📋 选题标题"))
        self.edit_topic_title = QLineEdit()
        self.edit_topic_title.setPlaceholderText("输入视频选题标题，用于生成AI文案...")
        self.edit_topic_title.textChanged.connect(self._on_topic_text_changed)
        topic_layout.addWidget(self.edit_topic_title)
        left_layout.addWidget(card_topic, 0)

        # 卡片 2：选题背景笔记（可选，手动填写；联网查素材在分镜页操作）
        card_ref = QFrame()
        card_ref.setObjectName("card")
        ref_layout = QVBoxLayout(card_ref)
        ref_layout.setContentsMargins(20, 16, 20, 16)
        ref_layout.setSpacing(10)
        ref_layout.addWidget(QLabel("📝 选题背景 / 参考笔记（可选）"))
        self.edit_references = QTextEdit()
        self.edit_references.setPlaceholderText(
            "可在此手动填写选题的背景知识、数据来源或参考要点，供大模型写文案时参考。\n"
            "（联网查找素材请在「分镜脚本创作」页操作）"
        )
        self.edit_references.setMinimumWidth(100)
        self.edit_references.setMaximumHeight(100)
        ref_layout.addWidget(self.edit_references, 1)
        left_layout.addWidget(card_ref, 0)

        # 卡片 3：风格化（可选）
        card_style = QFrame()
        card_style.setObjectName("card")
        sl = QVBoxLayout(card_style)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(10)

        style_hdr = QHBoxLayout()
        style_hdr.addWidget(QLabel("🎨 风格化（可选）"))
        btn_refresh_style = QPushButton("🔄")
        btn_refresh_style.setObjectName("secondary_button")
        btn_refresh_style.setFixedWidth(36)
        btn_refresh_style.setToolTip("重新加载知识库风格化列表")
        btn_refresh_style.clicked.connect(self._reload_stylizations)
        style_hdr.addWidget(btn_refresh_style)
        sl.addLayout(style_hdr)

        self.combo_stylization = SearchableComboBox(placeholder="输入风格名称搜索…")
        self.combo_stylization.currentIndexChanged.connect(self._on_stylization_selected)
        sl.addWidget(self.combo_stylization)

        self.text_style_portrait = QTextEdit()
        self.text_style_portrait.setReadOnly(True)
        self.text_style_portrait.setPlaceholderText("← 选择风格化后，风格画像显示在这里")
        self.text_style_portrait.setMinimumHeight(200)
        sl.addWidget(self.text_style_portrait, 1)

        left_layout.addWidget(card_style, 2)

        left_scroll.setWidget(left_container)
        splitter.addWidget(left_scroll)

        # ── 右侧 ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(14)
        right_panel.setMinimumWidth(150)

        card_draft = QFrame()
        card_draft.setObjectName("card")
        draft_layout = QVBoxLayout(card_draft)
        draft_layout.setContentsMargins(20, 16, 20, 16)
        draft_layout.setSpacing(10)

        draft_title_row = QHBoxLayout()
        draft_title_row.addWidget(QLabel("📝 爆款视频文案草稿（支持修改）"))
        draft_title_row.addStretch()
        self.btn_check_extreme = QPushButton("🚫 极限词检测")
        self.btn_check_extreme.setObjectName("secondary_button")
        self.btn_check_extreme.clicked.connect(self._check_extreme_words)
        draft_title_row.addWidget(self.btn_check_extreme)
        self.btn_gen_draft = QPushButton("✨ 生成 AI 文案")
        self.btn_gen_draft.setObjectName("primary_button")
        self.btn_gen_draft.setEnabled(False)
        self.btn_gen_draft.clicked.connect(self._generate_copywriting)
        draft_title_row.addWidget(self.btn_gen_draft)
        draft_layout.addLayout(draft_title_row)

        draft_layout.addWidget(QLabel("附加提示词（可选）"))
        self.edit_extra_prompt = QTextEdit()
        self.edit_extra_prompt.setPlaceholderText(
            "可输入额外要求，例如：时长约60秒 / 强调互动引导 / 适合年轻女性 / 避免夸大词…")
        self.edit_extra_prompt.setFixedHeight(68)
        self.edit_extra_prompt.setMinimumWidth(100)
        draft_layout.addWidget(self.edit_extra_prompt)

        self.edit_copywriting = QTextEdit()
        self.edit_copywriting.setPlaceholderText(
            "生成的文案将显示在这里；可直接编辑修改，修改后内容将传入分镜脚本创作。")
        self.edit_copywriting.setMinimumWidth(100)
        draft_layout.addWidget(self.edit_copywriting, 1)

        self.btn_go_storyboard = QPushButton("➡️ 前往分镜脚本创作")
        self.btn_go_storyboard.setObjectName("primary_button")
        self.btn_go_storyboard.setFixedHeight(45)
        self.btn_go_storyboard.setEnabled(False)
        self.btn_go_storyboard.clicked.connect(self._go_to_storyboard)
        draft_layout.addWidget(self.btn_go_storyboard)

        right_layout.addWidget(card_draft, 1)
        splitter.addWidget(right_panel)
        layout.addWidget(splitter, 1)

        status_row = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("muted_text")
        status_row.addWidget(self.lbl_status)
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setRange(0, 0)
        self.pbar.setMaximumWidth(200)
        status_row.addWidget(self.pbar)
        layout.addLayout(status_row)

        self.reload_sources()

    def _on_topic_text_changed(self):
        has_text = bool(self.edit_topic_title.text().strip())
        self.btn_gen_draft.setEnabled(has_text or self.selected_record is not None)
        self.btn_go_storyboard.setEnabled(has_text or self.selected_record is not None)

    # ── 风格化 ──

    def _reload_stylizations(self):
        if not hasattr(self, "combo_stylization"):
            return
        self.my_kb.load()
        self.combo_stylization.blockSignals(True)
        self.combo_stylization.clear()
        self.combo_stylization.addItem("— 不使用风格化（纯话题驱动）", None)
        stylizations = sorted(
            [it for it in self.my_kb.all_items() if it.get("type") == STYLIZATION_TYPE],
            key=lambda x: -(x.get("score") or 5.0)
        )
        for it in stylizations:
            score = it.get("score", 5.0)
            cnt = it.get("source_count", 0)
            label = f"{it.get('name','')}  ⭐{score:.1f} ({cnt}条)"
            self.combo_stylization.addItem(label, it.get("id"))
        self.combo_stylization.blockSignals(False)
        self._on_stylization_selected()

    def _on_stylization_selected(self):
        if not hasattr(self, "combo_stylization"):
            return
        sid = self.combo_stylization.currentData()
        if not sid:
            self._selected_stylization = None
            if hasattr(self, "text_style_portrait"):
                self.text_style_portrait.clear()
                self.text_style_portrait.setPlaceholderText("← 选择风格化后，风格画像显示在这里")
            return
        item = self.my_kb.get(sid)
        self._selected_stylization = item
        if hasattr(self, "text_style_portrait") and item:
            self.text_style_portrait.setPlainText(item.get("content", ""))

    def _generate_copywriting(self):
        topic = self.edit_topic_title.text().strip()
        if not topic:
            if self.selected_record:
                topic = self.selected_record.get("topic", "")
            if not topic:
                QMessageBox.warning(self.parent_widget, "选题为空", "请先输入视频选题标题或从飞书同步选题。")
                return

        ai = getattr(self.main_window, "ai_config", {}) or {}
        llm_api_url = ai.get("llm_api_url", "")
        llm_api_key = ai.get("llm_api_key", "")
        llm_model   = ai.get("llm_model", "deepseek-chat")

        if not llm_model:
            QMessageBox.warning(self.parent_widget, "大模型未配置",
                                "请先在「AI 设置」配置 LLM 模型名称。")
            return

        background   = self.edit_references.toPlainText().strip()
        extra_prompt = self.edit_extra_prompt.toPlainText().strip()

        style_text = ""
        if self._selected_stylization:
            style_text = (self._selected_stylization.get("content") or "").strip()

        system_prompt = (
            "你是资深的爆款短视频文案主创，擅长结合热点话题创作富有张力、口语化、吸睛的短视频文案。"
        )
        if style_text:
            system_prompt += (
                "\n\n同时须严格按照「风格指引」决定文案的**写作风格（HOW）**，"
                "话题内容（WHAT）不可改变。"
            )

        user_parts = [f"【选题】\n{topic}"]
        if background:
            user_parts.append(f"【背景参考】\n{background}")
        if style_text:
            user_parts.append(f"【风格指引】\n{style_text[:1000]}")

        reqs = [
            "请创作一篇 300-500 字的短视频文案。要求：",
            "① 开头黄金 3 秒吸睛；中间干货支撑；结尾互动/金句升华。",
            "② 语言极口语化，适合直接口播。",
        ]
        if style_text:
            reqs.append("③ 严格遵守「风格指引」的钩子/口吻/节奏/句式风格。")
        reqs.append("只输出文案正文，不要前言或总结说明。")
        if extra_prompt:
            reqs.append(f"\n【附加要求】\n{extra_prompt}")
        user_parts.append("\n".join(reqs))

        user_prompt = "\n\n".join(user_parts)

        self.btn_gen_draft.setEnabled(False)
        self.lbl_status.setText("AI 正在创作视频文案，请稍候…")
        self.pbar.setVisible(True)

        self.llm_worker = LLMWorker(llm_api_url, llm_api_key, llm_model, system_prompt, user_prompt)

        def on_done(content):
            self.btn_gen_draft.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText("文案生成完成。")
            self.edit_copywriting.setText(content.strip())
            self.btn_go_storyboard.setEnabled(True)

        def on_err(err_msg):
            self.btn_gen_draft.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText("文案生成失败。")
            QMessageBox.critical(self.parent_widget, "大模型异常", f"AI 生成文案失败：\n{err_msg}")

        self.llm_worker.finished.connect(on_done)
        self.llm_worker.error.connect(on_err)
        self.llm_worker.start()

    def reload_sources(self):
        self._reload_stylizations()

    def _go_to_storyboard(self):
        copy_text = self.edit_copywriting.toPlainText().strip()
        if not copy_text:
            QMessageBox.warning(self.parent_widget, "文案为空", "请先生成或填写文案，然后再进行分镜脚本设计。")
            return
        
        # Pass copywriting text and Feishu record info to Storyboard Page
        if hasattr(self.main_window, "storyboard_tool") and self.main_window.storyboard_tool:
            style_id = self._selected_stylization.get("id") if self._selected_stylization else None
            self.main_window.storyboard_tool.set_copywriting(
                copy_text,
                feishu_record=self.selected_record,
                stylization_id=style_id,
            )
        
        # Switch to storyboard page (index 38)
        self.main_window.switch_page(37)

    def _check_extreme_words(self):
        text = self.edit_copywriting.toPlainText()
        if not text.strip():
            QMessageBox.information(self.parent_widget, "极限词检测", "文案内容为空，无需检测。")
            return

        # 清除之前的高亮
        cursor = self.edit_copywriting.textCursor()
        cursor.select(cursor.Document)
        fmt_reset = cursor.charFormat()
        fmt_reset.setBackground(Qt.transparent)
        cursor.setCharFormat(fmt_reset)
        cursor.clearSelection()

        from utils.extreme_words import check_extreme_words
        matches = check_extreme_words(text)

        if not matches:
            QMessageBox.information(self.parent_widget, "极限词检测", "恭喜，未检测到任何平台极限词，文案安全！")
            return

        unique_words = set()
        for match in matches:
            word = match["word"]
            unique_words.add(word)
            start = match["start"]
            end = match["end"]

            cursor.setPosition(start)
            cursor.setPosition(end, cursor.KeepAnchor)
            fmt = cursor.charFormat()
            fmt.setBackground(QColor("#fca5a5"))  # 淡红色警告背景
            cursor.setCharFormat(fmt)

        cursor.clearSelection()
        self.edit_copywriting.setTextCursor(cursor)

        word_list_str = "、".join(sorted(unique_words))
        QMessageBox.warning(
            self.parent_widget,
            "极限词提醒",
            f"检测到 {len(matches)} 处平台广告极限词，已在文本中红底高亮显示！\n\n涉及词汇：{word_list_str}"
        )

    # ──────────────────── 飞书同步 ──────────────────────────────────
    def _get_feishu_config(self):
        """从 CONFIG_INI_FILE 读取飞书配置。"""
        config = configparser.ConfigParser()
        appid = ""
        appsecret = ""
        apptoken = ""
        tableid = ""
        topicfield = "选题"
        scriptfield = "脚本"
        foldertoken = ""
        try:
            config.read(CONFIG_INI_FILE, encoding="utf-8")
            if config.has_section('Feishu'):
                appid = config.get('Feishu', 'AppId', fallback="")
                appsecret = config.get('Feishu', 'AppSecret', fallback="")
                apptoken = config.get('Feishu', 'AppToken', fallback="")
                tableid = config.get('Feishu', 'TableId', fallback="")
                topicfield = config.get('Feishu', 'TopicField', fallback="选题")
                scriptfield = config.get('Feishu', 'ScriptField', fallback="脚本")
                foldertoken = config.get('Feishu', 'FolderToken', fallback="")
        except Exception:
            pass
        return appid, appsecret, apptoken, tableid, topicfield, scriptfield, foldertoken

    def _sync_feishu_topics(self):
        """从飞书多维表格同步选题列表。"""
        appid, appsecret, apptoken, tableid, topicfield, scriptfield, foldertoken = self._get_feishu_config()
        if not appid or not appsecret or not apptoken or not tableid:
            QMessageBox.warning(self.parent_widget, "配置未完成",
                                "请先在「环境配置」页配置好飞书 AppID/Secret/AppToken/TableID。")
            return
        self.btn_sync_topics.setEnabled(False)
        self.lbl_status.setText("正在连接飞书并获取选题数据...")
        self.pbar.setVisible(True)
        self.sync_worker = FeishuSyncWorker(appid, appsecret, apptoken, tableid, topicfield, scriptfield)

        def on_done(records):
            self.btn_sync_topics.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText(f"同步成功，获取到 {len(records)} 个选题")
            self.records_list = records

            self.table_topics.setRowCount(0)
            for idx, r in enumerate(records):
                self.table_topics.insertRow(idx)
                self.table_topics.setItem(idx, 0, QTableWidgetItem(r["topic"]))
                self.table_topics.setItem(idx, 1, QTableWidgetItem(r["status"]))
                self.table_topics.setItem(idx, 2, QTableWidgetItem(r["id"]))

        def on_err(err_msg):
            self.btn_sync_topics.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText("同步失败")
            QMessageBox.critical(self.parent_widget, "飞书同步失败", err_msg)

        self.sync_worker.finished.connect(on_done)
        self.sync_worker.error.connect(on_err)
        self.sync_worker.start()

    def _on_topic_selected(self):
        """当在飞书选题表格中选择一行时触发。"""
        selected_ranges = self.table_topics.selectedRanges()
        if not selected_ranges:
            self.selected_record = None
            return
        row = selected_ranges[0].topRow()
        if row < 0 or row >= len(self.records_list):
            return
        self.selected_record = self.records_list[row]
        self.btn_gen_draft.setEnabled(True)
        self.btn_go_storyboard.setEnabled(True)
        if self.selected_record["topic"]:
            self.edit_topic_title.setText(self.selected_record["topic"])
