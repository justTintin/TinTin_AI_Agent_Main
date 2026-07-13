# -*- coding: utf-8 -*-
"""
一键成片页。

把 镜头素材目录(图片) + 配音 + 字幕文案 + 封面 用 ffmpeg 自动拼成成品视频（幻灯片式）。
重型剪辑仍走「智能混剪」；本页面向"快速出片"。

逻辑见 utils/video_compiler.py。
"""
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QFrame,
    QComboBox, QDoubleSpinBox, QFileDialog, QProgressBar, QCheckBox,
)
from PySide6.QtCore import Signal

from gui.base_page import BasePage
from utils.base_worker import BaseWorker
from utils.gui_icons import mdi_button, mdi_icon
from utils.logger_utils import log
from utils.video_compiler import compile_video, collect_images, RATIO_SIZES
from utils.voxcpm_client import synthesize_tts
from utils.video_prediction_manager import PLATFORMS, VideoPredictionManager
from config.paths import FINAL_OUTPUT_DIR


class TTSWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, text, ref_wav, out_path):
        super().__init__()
        self.text = text; self.ref_wav = ref_wav; self.out_path = out_path

    def do_work(self):
        self.phase.emit("正在合成配音…")
        synthesize_tts(self.text, self.ref_wav, self.out_path)
        self.finished.emit(self.out_path)


class CompileVideoWorker(BaseWorker):
    phase = Signal(str)
    finished = Signal(str)

    def __init__(self, folder, out_path, audio, cover, subtitle, ratio, per_dur, intro=""):
        super().__init__()
        self.folder = folder; self.out_path = out_path
        self.audio = audio; self.cover = cover; self.subtitle = subtitle
        self.ratio = ratio; self.per_dur = per_dur; self.intro = intro

    def do_work(self):
        images = collect_images(self.folder)
        if not images:
            raise RuntimeError("素材目录里没有图片（支持 jpg/png/webp 等）。")
        compile_video(images, self.out_path, audio=self.audio, cover=self.cover,
                      subtitle_text=self.subtitle, ratio=self.ratio, per_dur=self.per_dur,
                      intro=self.intro, progress=self.phase.emit)
        self.finished.emit(self.out_path)


class CompileVideoPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)
        self.worker = None
        self._last_out = ""
        self._self_check_data = None

    def setup(self):
        root = QVBoxLayout(self.parent_widget)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(14)

        heading = QLabel("🎬 一键成片")
        heading.setObjectName("heading")
        root.addWidget(heading)
        sub = QLabel("镜头素材(图片) + 配音 + 字幕 + 封面 → 自动拼成成品视频。复杂剪辑请用「智能混剪」。")
        sub.setObjectName("muted_text"); sub.setWordWrap(True)
        root.addWidget(sub)

        card = QFrame(); card.setObjectName("card")
        form = QVBoxLayout(card); form.setContentsMargins(20, 16, 20, 16); form.setSpacing(10)

        self.in_folder = self._file_row(form, "镜头素材目录", self._browse_folder, folder=True,
                                        placeholder="选择图片素材目录（如即梦生成的 shots_ 目录）")
        self.in_audio = self._file_row(form, "配音音频(可选)", self._browse_audio,
                                       placeholder="wav/mp3/m4a，留空则无声（按每张时长）")
        # TTS 一键配音（用下方『字幕文案』作为配音文案）
        tts_row = QHBoxLayout()
        tts_row.addWidget(QLabel("　TTS 音色"))
        self.combo_voice = QComboBox()
        tts_row.addWidget(self.combo_voice, 1)
        self.btn_tts = mdi_button("用文案生成配音(TTS)", "audio")
        self.btn_tts.setObjectName("secondary_button")
        self.btn_tts.clicked.connect(self._tts_generate)
        tts_row.addWidget(self.btn_tts)
        form.addLayout(tts_row)

        self.in_intro = self._file_row(form, "开场视频(可选)", self._browse_intro,
                                       placeholder="片头开场视频，如 MG 动态标题；拼在最前面")
        intro_row = QHBoxLayout()
        intro_row.addStretch()
        self.btn_mg_intro = mdi_button("用动态标题生成开场(MG)", "film")
        self.btn_mg_intro.setObjectName("secondary_button")
        self.btn_mg_intro.clicked.connect(self._gen_mg_intro)
        intro_row.addWidget(self.btn_mg_intro)
        form.addLayout(intro_row)

        self.in_cover = self._file_row(form, "封面(可选)", self._browse_cover,
                                       placeholder="片头封面图，显示 2 秒")

        form.addWidget(QLabel("字幕文案 / 配音文案(可选；均分烧录为字幕，也作 TTS 配音文本)"))
        self.in_subtitle = QTextEdit(); self.in_subtitle.setFixedHeight(70)
        self.in_subtitle.setPlaceholderText("粘贴文案；按句子均匀分布为字幕，并可一键 TTS 配音。留空则不加。")
        form.addWidget(self.in_subtitle)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("比例"))
        self.combo_ratio = QComboBox(); self.combo_ratio.addItems(list(RATIO_SIZES.keys()))
        opt.addWidget(self.combo_ratio)
        opt.addWidget(QLabel("每张时长(无配音时)"))
        self.spin_dur = QDoubleSpinBox(); self.spin_dur.setRange(0.5, 30.0); self.spin_dur.setValue(3.0)
        self.spin_dur.setSuffix(" 秒"); opt.addWidget(self.spin_dur)
        self.chk_autocheck = QCheckBox("成片后自动视频预测评价")
        self.chk_autocheck.setChecked(True)
        opt.addWidget(self.chk_autocheck)
        opt.addWidget(QLabel("平台"))
        self.combo_predict_platform = QComboBox(); self.combo_predict_platform.addItems(PLATFORMS)
        self.combo_predict_platform.setFixedWidth(96)
        opt.addWidget(self.combo_predict_platform)
        opt.addStretch()
        self.btn_make = mdi_button("生成成片", "video"); self.btn_make.setObjectName("primary_button")
        self.btn_make.clicked.connect(self._make)
        opt.addWidget(self.btn_make)
        form.addLayout(opt)
        root.addWidget(card)

        score_row = QHBoxLayout()
        self.score_label = QLabel("")
        self.score_label.setObjectName("muted_text"); self.score_label.setWordWrap(True)
        score_row.addWidget(self.score_label, 1)
        self.btn_detail = mdi_button("查看详情/建议", "right"); self.btn_detail.setObjectName("secondary_button")
        self.btn_detail.clicked.connect(self._open_detail); self.btn_detail.setVisible(False)
        score_row.addWidget(self.btn_detail)
        root.addLayout(score_row)

        res = QHBoxLayout()
        self.status = QLabel("就绪"); self.status.setObjectName("muted_text")
        res.addWidget(self.status, 1)
        self.pbar = QProgressBar(); self.pbar.setVisible(False); self.pbar.setRange(0, 0); self.pbar.setMaximumWidth(160)
        res.addWidget(self.pbar)
        self.btn_open = QPushButton("打开成片"); self.btn_open.setObjectName("secondary_button")
        self.btn_open.clicked.connect(self._open); self.btn_open.setEnabled(False)
        res.addWidget(self.btn_open)
        root.addLayout(res)
        root.addStretch()
        self._populate_voices()

    def _populate_voices(self):
        self.combo_voice.clear()
        self.combo_voice.addItem("默认音色（无参考）", "")
        try:
            from gui.voice_samples_page import load_voice_samples
            for s in load_voice_samples():
                name = s.get("name") or s.get("filename") or "样本"
                path = s.get("path", "")
                if path:
                    self.combo_voice.addItem(name, path)
        except Exception as e:
            log.error(f"载入音色样本失败: {e}")

    def _tts_generate(self):
        text = self.in_subtitle.toPlainText().strip()
        if not text:
            self.show_warning("请先在『字幕文案 / 配音文案』里填入要配音的文案。")
            return
        ref = self.combo_voice.currentData() or ""
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("tts_%Y%m%d_%H%M%S.wav"))
        self.btn_tts.setEnabled(False); self.pbar.setVisible(True)
        self.status.setText("准备配音…")
        worker = TTSWorker(text, ref, out)
        worker.phase.connect(self.status.setText)

        def done(path):
            self.btn_tts.setEnabled(True); self.pbar.setVisible(False)
            self.in_audio.setText(path)
            self.status.setText(f"✅ 配音已生成并填入：{os.path.basename(path)}")

        worker.finished.connect(done)
        worker.error.connect(lambda e: (self.btn_tts.setEnabled(True), self.pbar.setVisible(False),
                                        self.show_error(str(e), "TTS 配音失败")))
        self.track_worker(worker); worker.start()

    def _file_row(self, parent, label, on_browse, folder=False, placeholder=""):
        parent.addWidget(QLabel(label))
        row = QHBoxLayout()
        edit = QLineEdit(); edit.setPlaceholderText(placeholder)
        row.addWidget(edit, 1)
        btn = QPushButton("浏览…"); btn.setObjectName("secondary_button")
        btn.clicked.connect(lambda: on_browse(edit))
        row.addWidget(btn)
        parent.addLayout(row)
        return edit

    def _browse_folder(self, edit):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择素材目录")
        if d:
            edit.setText(d)

    def _browse_audio(self, edit):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择配音", "", "音频 (*.wav *.mp3 *.m4a *.aac *.flac)")
        if f:
            edit.setText(f)

    def _browse_cover(self, edit):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if f:
            edit.setText(f)

    def _browse_intro(self, edit):
        f, _ = QFileDialog.getOpenFileName(self.parent_widget, "选择开场视频", "",
                                           "视频 (*.mp4 *.mov *.mkv *.webm)")
        if f:
            edit.setText(f)

    def _gen_mg_intro(self):
        from utils.remotion_client import is_installed
        if not is_installed():
            self.show_warning("Remotion 依赖未安装。请先到「🎞️ MG 动画」页点『安装依赖』。")
            return
        from PySide6.QtWidgets import QInputDialog
        default = (self.in_subtitle.toPlainText().strip().splitlines() or [""])[0][:16]
        title, ok = QInputDialog.getText(self.parent_widget, "动态标题开场", "标题文字：", text=default)
        if not ok or not title.strip():
            return
        from gui.mg_animation_page import MGRenderWorker
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("mgintro_%Y%m%d_%H%M%S.mp4"))
        self.btn_mg_intro.setEnabled(False); self.pbar.setVisible(True)
        self.status.setText("正在渲染动态标题开场(MG)…")
        w = MGRenderWorker("TitleReveal", {"title": title.strip(), "subtitle": "",
                                           "bg": "#101418", "color": "#FFFFFF"}, out)
        w.phase.connect(self.status.setText)

        def done(path):
            self.btn_mg_intro.setEnabled(True); self.pbar.setVisible(False)
            self.in_intro.setText(path)
            self.status.setText(f"✅ 开场动画已生成并填入：{os.path.basename(path)}")
        w.finished.connect(done)
        w.error.connect(lambda e: (self.btn_mg_intro.setEnabled(True), self.pbar.setVisible(False),
                                   self.show_error(str(e), "MG 开场生成失败")))
        self.track_worker(w); w.start()

    def _make(self):
        folder = self.in_folder.text().strip()
        if not folder or not os.path.isdir(folder):
            self.show_warning("请先选择有效的镜头素材目录。")
            return
        out = os.path.join(FINAL_OUTPUT_DIR, datetime.now().strftime("final_%Y%m%d_%H%M%S.mp4"))
        self.btn_make.setEnabled(False); self.pbar.setVisible(True)
        self.btn_open.setEnabled(False)
        self.worker = CompileVideoWorker(
            folder, out, self.in_audio.text().strip(), self.in_cover.text().strip(),
            self.in_subtitle.toPlainText().strip(), self.combo_ratio.currentText(), self.spin_dur.value(),
            intro=self.in_intro.text().strip())
        self.worker.phase.connect(self.status.setText)
        self.worker.finished.connect(self._done)
        self.worker.error.connect(self._err)
        self.track_worker(self.worker); self.worker.start()

    def _done(self, out):
        self._last_out = out
        self.btn_make.setEnabled(True); self.pbar.setVisible(False)
        self.btn_open.setEnabled(True)
        self.status.setText(f"✅ 成片完成：{out}")
        # 自动视频预测评价：按所选平台预测成片表现
        if self.chk_autocheck.isChecked():
            cfg = self.ai_config
            if cfg.get("llm_vision_api_url") and cfg.get("llm_vision_model"):
                from gui.hook_score_page import HookScoreWorker
                platform = self.combo_predict_platform.currentText()
                self._predict_platform = platform
                try:
                    calib = VideoPredictionManager().calibration_text(platform=platform)
                except Exception:
                    calib = ""
                self.score_label.setText(f"⏳ 正在按「{platform}」做视频预测评价…")
                sw = HookScoreWorker(out, cfg, platform=platform, calibration=calib)
                sw.finished.connect(self._on_self_check)
                sw.error.connect(lambda e: self.score_label.setText(f"视频预测失败：{e}"))
                self.track_worker(sw); sw.start()
            else:
                self.score_label.setText("（未配置视觉模型，跳过视频预测评价。）")

    def _on_self_check(self, data):
        self._self_check_data = data
        total = data.get("total", "—")
        level = data.get("play_level", "")
        comment = str(data.get("comment", ""))
        self.score_label.setText(f"📈 视频预测：综合 {total} 分 · 预测{level}　{comment}")
        self.btn_detail.setVisible(True)
        # 纳入预测库（回填真实数据/校准闭环）
        try:
            VideoPredictionManager().add_prediction(
                self._last_out, getattr(self, "_predict_platform", "抖音"), data)
        except Exception:
            pass

    def _open_detail(self):
        tool = getattr(self.main_window, "hook_score_tool", None)
        try:
            self.main_window.switch_page(35)  # 开头黄金3秒评分
            if tool and hasattr(tool, "show_result"):
                tool.show_result(self._last_out, self._self_check_data)
        except Exception as e:
            self.show_error(f"跳转失败：{e}")

    def _err(self, e):
        self.btn_make.setEnabled(True); self.pbar.setVisible(False)
        self.status.setText("成片失败。")
        self.show_error(str(e), "一键成片失败")

    def _open(self):
        if self._last_out and os.path.isfile(self._last_out) and os.name == "nt":
            os.startfile(self._last_out)  # noqa

	