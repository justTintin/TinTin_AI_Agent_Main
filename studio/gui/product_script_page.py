# -*- coding: utf-8 -*-
"""
「产品文案创作」页（与「飞书选题文案」分开，互不干扰）。

流程：
  选产品 → 查看性能参数 & 核心卖点（已保存在产品资料）
         → 可选：选择一个风格化条目（来自「我的知识库」）
         → 填写附加提示词（可选）
         → 一键生成文案

风格化调整：可在生成后单独调用风格 skill 对文案进行写法改写。
"""
import os

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFrame, QWidget,
    QComboBox, QSplitter, QMessageBox, QCheckBox,
    QProgressBar, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from utils.product_library_manager import ProductLibraryManager
from gui.searchable_combo import SearchableComboBox
from utils.my_knowledge_manager import MyKnowledgeManager, STYLIZATION_TYPE
from gui.ai_script_page import LLMWorker
from gui.base_page import BasePage


class ProductScriptPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.kb = ProductLibraryManager()
        self.my_kb = MyKnowledgeManager()
        self.worker = None
        self._product_text = ""
        self._selected_stylization = None   # currently chosen stylization dict

    # ──────────────────────── UI ────────────────────────
    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        hdr = QHBoxLayout()
        heading = QLabel("🛒 产品文案创作")
        heading.setObjectName("heading")
        hdr.addWidget(heading)
        desc = QLabel("基于产品资料与风格化画像，一键生成产品文案与分镜脚本")
        desc.setObjectName("muted_text")
        desc.setWordWrap(True)
        desc.setMaximumWidth(1400)  # 一行显示，右侧留白避让资源监控
        hdr.addWidget(desc)
        hdr.addStretch()
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Horizontal)
        left_panel = self._build_left()
        left_panel.setMinimumWidth(150)
        right_panel = self._build_right()
        right_panel.setMinimumWidth(150)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([420, 600])
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

    def _build_left(self):
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 10, 0)
        col.setSpacing(14)

        # ── 卡片 1：产品检索 ──
        card_src = QFrame()
        card_src.setObjectName("card")
        src = QVBoxLayout(card_src)
        src.setContentsMargins(20, 16, 20, 16)
        src.setSpacing(10)

        search_row = QHBoxLayout()
        lbl_search = QLabel("📦 产品选择")
        lbl_search.setObjectName("card_title")
        search_row.addWidget(lbl_search)
        self.combo_product = SearchableComboBox(placeholder="输入品牌/型号搜索产品…")
        self.combo_product.currentIndexChanged.connect(self._on_product_selected)
        self.combo_product.setMinimumWidth(100)
        search_row.addWidget(self.combo_product, 1)
        btn_reload = QPushButton("🔄 重置")
        btn_reload.setObjectName("secondary_button")
        btn_reload.setToolTip("重新载入产品资料与我的知识库")
        btn_reload.clicked.connect(self.reload_sources)
        search_row.addWidget(btn_reload)
        src.addLayout(search_row)
        col.addWidget(card_src)

        # ── 卡片 2：产品已保存资料 ──
        card_detail = QFrame()
        card_detail.setObjectName("card")
        detail = QVBoxLayout(card_detail)
        detail.setContentsMargins(20, 16, 20, 16)
        detail.setSpacing(10)

        title_detail = QLabel("📋 产品已保存资料 (性能参数与核心卖点)")
        title_detail.setObjectName("card_title")
        title_detail.setWordWrap(True)
        detail.addWidget(title_detail)

        detail.addWidget(QLabel("性能参数"))
        self.edit_features = QTextEdit()
        self.edit_features.setPlaceholderText("选择产品后自动显示；支持临时编辑…")
        self.edit_features.setMinimumHeight(80)
        self.edit_features.setMinimumWidth(100)
        detail.addWidget(self.edit_features)

        detail.addWidget(QLabel("核心卖点"))
        self.edit_selling_points = QTextEdit()
        self.edit_selling_points.setPlaceholderText("选择产品后自动显示；支持临时编辑…")
        self.edit_selling_points.setMinimumHeight(80)
        self.edit_selling_points.setMinimumWidth(100)
        detail.addWidget(self.edit_selling_points)
        col.addWidget(card_detail)

        # ── 卡片 3：风格化（可选） ──
        card_style = QFrame()
        card_style.setObjectName("card")
        sl = QVBoxLayout(card_style)
        sl.setContentsMargins(20, 16, 20, 16)
        sl.setSpacing(10)

        style_hdr = QHBoxLayout()
        style_title = QLabel("🎨 风格化（可选）")
        style_title.setObjectName("card_title")
        style_hdr.addWidget(style_title)
        sl.addLayout(style_hdr)

        style_row = QHBoxLayout()
        self.combo_stylization = SearchableComboBox(placeholder="输入风格名称搜索…")
        self.combo_stylization.currentIndexChanged.connect(self._on_stylization_selected)
        style_row.addWidget(self.combo_stylization, 1)
        btn_refresh_style = QPushButton("🔄 重置")
        btn_refresh_style.setObjectName("secondary_button")
        btn_refresh_style.setToolTip("重新加载知识库风格化列表")
        btn_refresh_style.clicked.connect(self._reload_stylizations)
        style_row.addWidget(btn_refresh_style)
        sl.addLayout(style_row)

        self.text_style_portrait = QTextEdit()
        self.text_style_portrait.setReadOnly(True)
        self.text_style_portrait.setPlaceholderText("← 从上方选择一个风格化条目，风格画像将显示在这里")
        self.text_style_portrait.setMinimumHeight(100)
        self.text_style_portrait.setMinimumWidth(100)
        sl.addWidget(self.text_style_portrait, 1)

        col.addWidget(card_style)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        return scroll

    def _build_right(self):
        panel = QWidget()
        col = QVBoxLayout(panel)
        col.setContentsMargins(10, 0, 0, 0)
        col.setSpacing(14)

        card_copy = QFrame()
        card_copy.setObjectName("card")
        cp = QVBoxLayout(card_copy)
        cp.setContentsMargins(20, 16, 20, 16)
        cp.setSpacing(10)

        # 生成设置：平台 / 语气 / 结构 / 话题标签 / 违禁词（放在生成文案按钮前面）
        gen_settings = QGridLayout()
        gen_settings.setHorizontalSpacing(10)
        gen_settings.setVerticalSpacing(8)
        gen_settings.addWidget(QLabel("平台"), 0, 0)
        self.combo_platform = QComboBox()
        self.combo_platform.addItems(["通用", "抖音", "快手", "小红书"])
        gen_settings.addWidget(self.combo_platform, 0, 1)
        gen_settings.addWidget(QLabel("语气"), 0, 2)
        self.combo_tone = QComboBox()
        self.combo_tone.addItems(["热情种草", "专业测评", "幽默搞笑", "悬念钩子", "温情故事", "酷飒高级"])
        gen_settings.addWidget(self.combo_tone, 0, 3)
        gen_settings.addWidget(QLabel("结构"), 1, 0)
        self.combo_structure = QComboBox()
        self.combo_structure.addItems(["黄金3秒开场", "痛点切入", "故事化", "清单式", "对比式", "倒叙悬念"])
        gen_settings.addWidget(self.combo_structure, 1, 1)
        gen_settings.addWidget(QLabel("话题标签"), 1, 2)
        self.combo_tags = QComboBox()
        self.combo_tags.addItems(["不生成", "5 个", "10 个"])
        gen_settings.addWidget(self.combo_tags, 1, 3)
        self.check_avoid_banned = QCheckBox("规避平台违禁词 / 极限词")
        self.check_avoid_banned.setChecked(True)
        gen_settings.addWidget(self.check_avoid_banned, 2, 0, 1, 4)
        cp.addLayout(gen_settings)

        cp_row = QHBoxLayout()
        cp_row.addWidget(QLabel("📝 视频文案（可编辑）"))
        cp_row.addStretch()
        self.btn_check_extreme = QPushButton("🚫 极限词检测")
        self.btn_check_extreme.setObjectName("secondary_button")
        self.btn_check_extreme.clicked.connect(self._check_extreme_words)
        cp_row.addWidget(self.btn_check_extreme)
        self.btn_gen_copy = QPushButton("✨ 生成文案")
        self.btn_gen_copy.setObjectName("primary_button")
        self.btn_gen_copy.clicked.connect(self._generate_copywriting)
        cp_row.addWidget(self.btn_gen_copy)
        cp.addLayout(cp_row)

        # 附加提示词（可选）
        cp.addWidget(QLabel("附加提示词（可选）"))
        self.edit_extra_prompt = QTextEdit()
        self.edit_extra_prompt.setPlaceholderText(
            "可输入额外要求，例如：时长约60秒 / 针对年轻女性 / 偏硬核测评风格 / 避免夸大词…")
        self.edit_extra_prompt.setFixedHeight(68)
        self.edit_extra_prompt.setMinimumWidth(100)
        cp.addWidget(self.edit_extra_prompt)

        self.edit_copy = QTextEdit()
        self.edit_copy.setPlaceholderText(
            "根据产品卖点（和可选风格化）生成的文案显示在这里；生成后可直接编辑。")
        self.edit_copy.setMinimumHeight(300)
        self.edit_copy.setMinimumWidth(100)
        cp.addWidget(self.edit_copy, 1)

        self.btn_go_storyboard = QPushButton("➡️ 前往分镜脚本设计")
        self.btn_go_storyboard.setObjectName("primary_button")
        self.btn_go_storyboard.setFixedHeight(45)
        self.btn_go_storyboard.clicked.connect(self._go_to_storyboard)
        cp.addWidget(self.btn_go_storyboard)

        col.addWidget(card_copy, 1)
        return panel

    # ──────────────────────── 页面跳转 ────────────────────────
    def _go_to_storyboard(self):
        copy_text = self.edit_copy.toPlainText().strip()
        if not copy_text:
            QMessageBox.warning(self.parent_widget, "文案为空", "请先生成或填写文案，然后再进行分镜脚本设计。")
            return
        # 携带当前产品上下文（品牌/型号/产品类型），供分镜页素材检索使用
        prod = {}
        item_id = self.combo_product.currentData()
        if item_id:
            prod = self.kb.get(item_id) or {}
        if hasattr(self.main_window, "storyboard_tool") and self.main_window.storyboard_tool:
            style_id = self._selected_stylization.get("id") if self._selected_stylization else None
            self.main_window.storyboard_tool.set_copywriting(
                copy_text, stylization_id=style_id, product=prod)
        self.main_window.switch_page(37)

    # ──────────────────────── 数据载入 ────────────────────────
    def reload_sources(self):
        self.kb.load()
        self.my_kb.load()
        self._populate_products("")
        self._reload_stylizations()

    def _reload_stylizations(self):
        """重新载入知识库中的风格化条目到 combo_stylization。"""
        if not hasattr(self, "combo_stylization"):
            return
        self.my_kb.load()
        self.combo_stylization.blockSignals(True)
        self.combo_stylization.clear()
        self.combo_stylization.addItem("— 不使用风格化（纯产品驱动）", None)
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
                self.text_style_portrait.setPlaceholderText(
                    "← 从上方选择一个风格化条目，风格画像将显示在这里")
            return
        item = self.my_kb.get(sid)
        self._selected_stylization = item
        if hasattr(self, "text_style_portrait") and item:
            self.text_style_portrait.setPlainText(item.get("content", ""))

    def _populate_products(self, keyword=""):
        items = self.kb.search(keyword) if keyword else self.kb.all_items()
        items = sorted(items, key=lambda x: (x.get("category", ""), x.get("brand", ""), x.get("model", "")))
        self.combo_product.blockSignals(True)
        self.combo_product.clear()
        self.combo_product.addItem("--- 请选择产品 ---", None)
        for it in items:
            label = f"{it.get('brand','')} - {it.get('model','')}".strip(" -") or it.get("goods_no", "")
            cat = it.get("category", "").strip()
            if cat:
                label = f"[{cat}] {label}"
            self.combo_product.addItem(label, it.get("id"))
        if not items:
            hint = "（无匹配产品）" if keyword else "（产品资料为空，请先在「产品资料」页同步）"
            self.combo_product.addItem(hint, None)
        self.combo_product.blockSignals(False)
        self.combo_product.setCurrentIndex(0)
        self._on_product_selected()

    def _on_product_selected(self):
        pid = self.combo_product.currentData()
        if not pid:
            self.edit_features.clear()
            self.edit_selling_points.clear()
            return
        record = self.kb.get(pid)
        if record:
            self.edit_features.setPlainText(record.get("features", ""))
            self.edit_selling_points.setPlainText(record.get("selling_points", ""))
        else:
            self.edit_features.clear()
            self.edit_selling_points.clear()

    # ──────────────────────── LLM 通用 ────────────────────────
    def _ai_cfg(self):
        ai = getattr(self.main_window, "ai_config", {}) or {}
        model = ai.get("llm_model", "deepseek-v4-flash")
        if not model:
            QMessageBox.warning(self.parent_widget, "大模型未配置",
                                "请先在「AI 设置 / 大模型配置」中选择模型名称。")
            return None
        return "", "", model

    def _run_llm(self, system_prompt, user_prompt, on_done, busy_btn, busy_text):
        cfg = self._ai_cfg()
        if not cfg:
            return
        url, key, model = cfg
        busy_btn.setEnabled(False)
        self.lbl_status.setText(busy_text)
        self.pbar.setVisible(True)
        self.worker = LLMWorker(url, key, model, system_prompt, user_prompt)

        def _done(content):
            busy_btn.setEnabled(True)
            self.pbar.setVisible(False)
            on_done(content.strip())

        def _err(msg):
            busy_btn.setEnabled(True)
            self.pbar.setVisible(False)
            self.lbl_status.setText("生成失败。")
            QMessageBox.critical(self.parent_widget, "大模型异常", f"请求失败：\n{msg}")

        self.worker.finished.connect(_done)
        self.worker.error.connect(_err)
        self.worker.start()

    # ──────────────────────── 生成文案 ────────────────────────
    def _generate_copywriting(self):
        pid = self.combo_product.currentData()
        if not pid:
            QMessageBox.information(self.parent_widget, "请选择产品", "请先在检索框搜索并选择一个产品。")
            return

        features      = self.edit_features.toPlainText().strip()
        selling_points = self.edit_selling_points.toPlainText().strip()
        if not (features or selling_points):
            QMessageBox.warning(self.parent_widget, "产品资料为空",
                                "请先在「产品资料」页为该产品填写性能参数或核心卖点。")
            return

        extra_prompt = self.edit_extra_prompt.toPlainText().strip()

        # 风格化（可选）
        style_text = ""
        if self._selected_stylization:
            style_text = (self._selected_stylization.get("content") or "").strip()

        # 产品基础信息
        record = self.kb.get(pid)
        basic = []
        if record:
            for k, lbl in [("category","品类"),("brand","品牌"),("model","型号"),
                            ("goods_no","商家编码"),("spec_name","规格")]:
                v = str(record.get(k, "")).strip()
                if v:
                    basic.append(f"{lbl}：{v}")
        self._product_text = (
            f"{'  '.join(basic)}\n\n"
            f"【性能参数】\n{features if features else '（未录入）'}\n\n"
            f"【核心卖点】\n{selling_points if selling_points else '（未录入）'}"
        )

        # System prompt
        system_prompt = (
            "你是资深的爆款短视频带货文案主创，擅长把产品卖点写成口语化、吸睛、适合念白的短视频文案。"
        )
        if style_text:
            system_prompt += (
                "\n\n同时，你须严格按照「风格指引」决定文案的**写作风格（HOW）**，"
                "但产品名称、核心卖点与数据（WHAT）不可改变。"
            )

        # User prompt
        user_parts = [f"【产品资料】\n{self._product_text}"]
        if style_text:
            user_parts.append(f"【风格指引】\n{style_text[:1000]}")

        # 生成设置映射：平台 / 语气 / 结构 / 话题标签 / 违禁词
        platform_text = {
            "通用": "通用（不指定平台）",
            "抖音": "抖音：口语化、节奏快、黄金3秒抓人、适合口播，可带轻量互动引导",
            "快手": "快手：接地气、老铁口吻、真实感强、简单直接",
            "小红书": "小红书：种草笔记体、真诚分享、分段清晰、可带适量 emoji",
        }.get(self.combo_platform.currentText(), "通用（不指定平台）")
        tone_text = {
            "热情种草": "热情种草：兴奋、真诚、强烈推荐感",
            "专业测评": "专业测评：客观、数据化、权威感",
            "幽默搞笑": "幽默搞笑：轻松、有梗、口语化",
            "悬念钩子": "悬念钩子：先抛疑问/反差，再揭晓卖点",
            "温情故事": "温情故事：从生活场景切入，强调情感共鸣",
            "酷飒高级": "酷飒高级：简洁、利落、高级感",
        }.get(self.combo_tone.currentText(), "热情种草")
        structure_text = {
            "黄金3秒开场": "黄金3秒开场：开头抓人，中间卖点支撑，结尾引导下单/互动",
            "痛点切入": "痛点切入：先讲用户痛点，再给产品方案，最后行动引导",
            "故事化": "故事化：用场景/故事带入，自然引出产品卖点",
            "清单式": "清单式：分点列出卖点/优势，清晰易读",
            "对比式": "对比式：与同类产品或旧方案对比，突出优势",
            "倒叙悬念": "倒叙悬念：先给结果/反差，再回溯原因",
        }.get(self.combo_structure.currentText(), "黄金3秒开场")
        tag_count = {"不生成": 0, "5 个": 5, "10 个": 10}.get(self.combo_tags.currentText(), 0)

        reqs = [
            "请根据以上信息，创作一篇 200-400 字的带货短视频文案。要求：",
            "① 开头黄金 3 秒抓人；中间用卖点支撑；结尾引导下单/互动。",
            "② 极口语化，适合直接口播。",
        ]
        if style_text:
            reqs.append("③ 严格遵守「风格指引」中定义的钩子/口吻/节奏/句式/收尾风格。")
        reqs.append(f"平台要求：{platform_text}。")
        reqs.append(f"语气要求：{tone_text}。")
        reqs.append(f"结构要求：{structure_text}。")
        if tag_count:
            reqs.append(f"文末另起一行生成 {tag_count} 个话题标签（# 开头，贴合所选平台与产品）。")
        if self.check_avoid_banned.isChecked():
            reqs.append("违禁词要求：全程规避平台广告极限词/违禁词（绝对化用语、虚假宣传、夸大功效、无法验证的承诺等），必要时用中性表达替代。")
        reqs.append("只输出文案正文，不要任何前言或总结说明。")
        if extra_prompt:
            reqs.append(f"\n【附加要求】\n{extra_prompt}")
        user_parts.append("\n".join(reqs))

        user_prompt = "\n\n".join(user_parts)

        def on_done(content):
            self.edit_copy.setPlainText(content)
            self.lbl_status.setText("文案已生成，可直接前往分镜脚本设计。")

        self._run_llm(system_prompt, user_prompt, on_done, self.btn_gen_copy, "AI 正在创作文案…")

    def _check_extreme_words(self):
        text = self.edit_copy.toPlainText()
        if not text.strip():
            QMessageBox.information(self.parent_widget, "极限词检测", "文案内容为空，无需检测。")
            return

        # 清除之前的高亮
        cursor = self.edit_copy.textCursor()
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
        self.edit_copy.setTextCursor(cursor)

        word_list_str = "、".join(sorted(unique_words))
        QMessageBox.warning(
            self.parent_widget,
            "极限词提醒",
            f"检测到 {len(matches)} 处平台广告极限词，已在文本中红底高亮显示！\n\n涉及词汇：{word_list_str}"
        )

