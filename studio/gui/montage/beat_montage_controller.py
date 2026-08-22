# -*- coding: utf-8 -*-
"""卡点成片控制器（一键成片 → 卡点成片 tab）。

自包含业务逻辑：选音乐 + 多选镜头素材 → 检测卡点（/audio/beatmap 返回片段用于波形显示）
→ 一次上传音乐+全部素材，用 variant_count 提交服务端 POST /montage/beat 一次生成多个成片
→ 轮询并逐个下载变体成片 → 片段卡片播放对应变体视频（右侧 QVideoWidget 预览）→ 导出并打开目录。

本类充当 StepBeatView 的 "main_page" 角色：StepBeatView 会把界面控件挂载到本类实例上，
并把按钮/卡片信号连接到本类的 _beat_* 方法（与旧版挂载到 VideoMontagePage 的模式一致）。
"""
import os
import shutil
import tempfile

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QMessageBox

from utils.logger_utils import log
from gui.montage.workers.split_workers import BeatDetectWorker, BeatVideoGenWorker


class BeatMontageController(QObject):
    """卡点成片业务控制器（自包含，不依赖智能混剪页面）。"""

    def __init__(self, parent_widget, main_window):
        super().__init__()
        self.parent_widget = parent_widget
        self.main_window = main_window

        # ── 节拍/片段数据 ──
        self._beat_data_full = []          # 全曲节拍（绝对时间）
        self._beat_data = []               # 跨片段拼接的全局节拍
        self._beat_clips = []              # 服务端返回的片段列表
        self._beat_segments = []           # 片段结构 [{start,end,beats,slot_start,label}]
        self._beat_full_duration = 0.0     # 全曲时长(秒)
        self._beat_music_range = (0.0, 0.0)
        self._beat_clip_assignments = []   # 保留以兼容 StepBeatView（服务端自动指派，不再使用）
        self._beat_video_files = []        # 各片段已下载成片路径 [None]*N

        # ── 镜头素材（多选视频文件，与智能混剪一致）──
        self._beat_clips_list = []

        # ── Worker 引用 ──
        self._beat_worker = None
        self._beat_gen_worker = None

        # 下载/裁剪工作目录
        self._beat_work_dir = os.path.join(tempfile.gettempdir(), "beat_gen_videos")

    # ═══════════════════════════════════════════════════════════
    #  基础 helper
    # ═══════════════════════════════════════════════════════════

    def _get_compute_server_url(self):
        """读取算力服务端地址（与智能混剪一致：ai_config.compute_server_url）。"""
        try:
            cfg = getattr(self.main_window, "ai_config", {}) or {}
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
        except Exception:
            pass
        try:
            from config.paths import AI_CONFIG_FILE
            import json as _json
            if os.path.isfile(AI_CONFIG_FILE):
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = _json.load(f)
                return (cfg.get("compute_server_url") or "").strip().rstrip("/")
        except Exception:
            pass
        return ""

    def _beat_refresh_clips_info(self):
        """刷新已选镜头素材数量标签，返回当前素材列表。"""
        if hasattr(self, "beat_clips_info_lbl"):
            self.beat_clips_info_lbl.setText(f"镜头素材: {len(self._beat_clips_list)} 个")
        return self._beat_clips_list

    def _get_segment_card(self, index):
        """按片段索引取对应的波形卡片（非全曲卡）。"""
        view = getattr(self, "step_beat", None)
        if not view:
            return None
        for c in getattr(view, "segment_cards", []):
            if not getattr(c, "is_full_track", False) and getattr(c, "index", -1) == index:
                return c
        return None

    # ═══════════════════════════════════════════════════════════
    #  文件选择
    # ═══════════════════════════════════════════════════════════

    def _beat_browse_music(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent_widget, "选择卡点音乐",
            "", "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All Files (*)")
        if not path:
            return
        self.beat_music_path.setText(path)
        self.btn_beat_detect.setEnabled(True)
        self.beat_status_lbl.setText(f"已选择: {os.path.basename(path)}")
        if hasattr(self, "step_beat"):
            self.step_beat.load_music(path)

    def _beat_select_materials(self):
        """选择一个或多个视频素材（与智能混剪一致，去重追加）。"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self.parent_widget, "选择视频素材", "",
            "视频文件 (*.mp4 *.mov *.avi *.mkv *.flv *.webm *.m4v);;所有文件 (*.*)")
        if not file_paths:
            return
        existing = set(os.path.abspath(p) for p in self._beat_clips_list)
        added = 0
        for p in file_paths:
            ap = os.path.abspath(p)
            if ap in existing:
                continue
            existing.add(ap)
            self._beat_clips_list.append(ap)
            added += 1
        self._beat_refresh_clips_info()
        n = len(self._beat_clips_list)
        if n:
            names = ", ".join(os.path.basename(p) for p in self._beat_clips_list[:3])
            self.beat_materials_input.setText(f"{names}{' ...' if n > 3 else ''}")
        else:
            self.beat_materials_input.setText("")
        self.beat_status_lbl.setText(f"已选择 {n} 个镜头素材（本次新增 {added} 个）")

    def _beat_browse_out_dir(self):
        d = QFileDialog.getExistingDirectory(self.parent_widget, "选择视频导出目录", "")
        if not d:
            return
        self.beat_out_dir_input.setText(d)

    # ═══════════════════════════════════════════════════════════
    #  检测卡点（/audio/beatmap）+ 触发服务端逐段生成
    # ═══════════════════════════════════════════════════════════

    def _beat_start_detect(self):
        music_path = self.beat_music_path.text().strip()
        if not music_path or not os.path.isfile(music_path):
            QMessageBox.warning(self.parent_widget, "未选择音乐", "请先选择音乐文件。")
            return
        clips = self._beat_refresh_clips_info()
        if not clips:
            QMessageBox.warning(self.parent_widget, "未选择镜头",
                                "请先选择镜头素材（视频文件）。")
            return
        server_url = self._get_compute_server_url()
        if not server_url:
            QMessageBox.warning(self.parent_widget, "未配置服务端",
                                "卡点成片需要服务端接口。\n"
                                "请先在「环境配置」中配置算力服务端地址。")
            return

        self.btn_beat_detect.setEnabled(False)
        self.btn_beat_confirm.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.beat_status_lbl.setText("🎵 正在上传音乐并检测卡点...")

        # 视频个数(count) 与 每段时长(segment_duration)
        count = 0
        if hasattr(self, "beat_video_count_spin"):
            try:
                count = max(0, int(self.beat_video_count_spin.value()))
            except (TypeError, ValueError):
                count = 0
        segment_duration = 0.0
        if hasattr(self, "beat_duration_combo"):
            try:
                segment_duration = float(self.beat_duration_combo.currentData() or 0)
            except (TypeError, ValueError):
                segment_duration = 0.0

        log.info(f"[卡点成片] 检测开始: {music_path}, 服务端: {server_url}, "
                 f"count={count}, segment_duration={segment_duration}, 镜头={len(clips)}")

        self._beat_worker = BeatDetectWorker(
            music_path, server_url, count=count, segment_duration=segment_duration)
        self._beat_worker.beats_ready.connect(self._beat_on_beats_ready)
        self._beat_worker.error.connect(self._beat_on_detect_error)
        self._beat_worker.start()

    def _beat_on_beats_ready(self, beats, clips):
        self.btn_beat_detect.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)

        if not beats or len(beats) < 2:
            self.beat_status_lbl.setText("❌ 节拍点不足，无法卡点")
            QMessageBox.warning(self.parent_widget, "节拍不足",
                                "服务端返回的节拍点少于 2 个，无法进行卡点成片。")
            return

        music_path = self.beat_music_path.text().strip()
        duration = beats[-1] + 1.0
        try:
            from gui.montage.utils_media import get_media_duration
            real_dur = get_media_duration(music_path)
            if real_dur and real_dur > 0:
                duration = real_dur
        except Exception:
            pass

        self._beat_data_full = list(beats)
        self._beat_full_duration = duration
        self._beat_clips = list(clips or [])

        if self._beat_clips:
            # 多片段模式：构建波形卡片并触发服务端逐段生成视频
            self._beat_build_segments()
            log.info(f"[卡点成片] 检测完成: 全曲 {len(beats)} 拍, {len(self._beat_clips)} 个片段")
            self._beat_submit_generation()
        else:
            self._beat_build_single_card()
            log.info(f"[卡点成片] 检测完成: 全曲 {len(beats)} 拍（单片段，仅音乐预览）")

    def _beat_build_segments(self):
        """根据服务端 clips 构建多片段数据结构与波形卡片。"""
        beats = sorted(getattr(self, "_beat_data_full", []))
        clips = getattr(self, "_beat_clips", [])
        duration = getattr(self, "_beat_full_duration", 0.0)
        if not clips:
            return

        segments = []
        global_beats = []
        for ci, c in enumerate(clips):
            s = float(c.get("start", 0.0))
            e = float(c.get("end", 0.0))
            seg_beats = [b for b in beats if s - 1e-6 <= b <= e + 1e-6]
            if not seg_beats:
                seg_beats = [s, e]
            else:
                if seg_beats[0] > s + 1e-6:
                    seg_beats = [s] + seg_beats
                if seg_beats[-1] < e - 1e-6:
                    seg_beats = seg_beats + [e]
            slot_start = max(0, len(global_beats) - 1) if global_beats else 0
            segments.append({
                "start": s, "end": e,
                "beats": seg_beats,
                "slot_start": slot_start,
                "label": f"片段{ci + 1} ({s:.1f}~{e:.1f}s)",
            })
            global_beats.extend(seg_beats if not global_beats else seg_beats[1:])

        self._beat_segments = segments
        self._beat_data = global_beats
        n_slots = max(0, len(global_beats) - 1)
        self._beat_clip_assignments = [None] * n_slots
        self._beat_video_files = [None] * len(segments)

        if hasattr(self, "step_beat"):
            peaks = getattr(self.step_beat, "_full_peaks", [])
            self.step_beat.build_segment_cards(segments, peaks, duration, full_beats=beats)

        self.btn_beat_confirm.setEnabled(False)
        self.beat_status_lbl.setText(
            f"✅ 检测到 {len(segments)} 个卡点片段，正在提交服务端生成 {len(segments)} 个视频...")

    def _beat_build_single_card(self):
        """单片段模式：用全曲节拍构建一张整体预览卡片（仅音乐试听）。"""
        beats = sorted(getattr(self, "_beat_data_full", []))
        duration = getattr(self, "_beat_full_duration", 0.0)
        if len(beats) < 2:
            self.btn_beat_confirm.setEnabled(False)
            self.beat_status_lbl.setText("⚠️ 节拍不足 2 个，无法卡点")
            return
        seg_end = duration if duration > 0 else beats[-1] + 1.0
        segments = [{"start": 0.0, "end": seg_end, "beats": beats, "slot_start": 0,
                     "label": "全曲"}]
        self._beat_segments = segments
        self._beat_data = beats
        self._beat_music_range = (0.0, seg_end)
        self._beat_clip_assignments = [None] * (len(beats) - 1)
        self._beat_video_files = []
        if hasattr(self, "step_beat"):
            peaks = getattr(self.step_beat, "_full_peaks", [])
            self.step_beat.build_segment_cards(segments, peaks, duration)
        self.btn_beat_confirm.setEnabled(False)
        self.beat_status_lbl.setText(f"✅ 全曲 {len(beats)} 拍（单片段，仅音乐预览）")

    def _beat_on_detect_error(self, err):
        self.btn_beat_detect.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.beat_status_lbl.setText("❌ 卡点检测失败")
        QMessageBox.critical(self.parent_widget, "卡点检测失败",
                             f"服务端节拍检测失败：\n{err}\n\n"
                             f"可能原因：\n"
                             f"· 服务端 /audio/beatmap 接口未部署\n"
                             f"· 服务端地址配置错误\n"
                             f"· 音乐文件格式不支持")

    # ═══════════════════════════════════════════════════════════
    #  服务端一次上传生成多视频（/montage/beat + variant_count）
    # ═══════════════════════════════════════════════════════════

    def _beat_submit_generation(self):
        """一次上传音乐+全部素材，用 variant_count 提交 /montage/beat 一次生成多个成片。"""
        segments = getattr(self, "_beat_segments", [])
        music_path = self.beat_music_path.text().strip()
        clips = self._beat_clips_list
        server_url = self._get_compute_server_url()
        if not segments or not clips or not server_url:
            return

        transition = "fade"
        if hasattr(self, "beat_transition_combo"):
            transition = self.beat_transition_combo.currentData() or "fade"

        n_variants = len(segments)  # 与波形卡片数一致：第 i 个卡片播放第 i 个变体
        # 成片时长：取「时长」下拉值（0 表示完整有效区间）
        time_limit = 0.0
        if hasattr(self, "beat_duration_combo"):
            try:
                time_limit = float(self.beat_duration_combo.currentData() or 0)
            except (TypeError, ValueError):
                time_limit = 0.0

        spec = {
            "music": music_path,            # 整段音乐，仅上传一次
            "videos": clips,                # 全部素材，仅上传一次
            "variant_count": n_variants,    # 一次生成 N 个完整成片变体
            "time_limit": round(time_limit, 2) if time_limit > 0 else 0,
            "transition": transition,
            "min_duration": 0.8,
            "max_duration": 3.0,
        }

        self._beat_video_files = [None] * n_variants
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.beat_status_lbl.setText(f"🎬 正在上传素材并生成 {n_variants} 个卡点视频...")
        log.info(f"[卡点成片] 提交 1 个 /montage/beat 任务, variant_count={n_variants}, "
                 f"转场={transition}, time_limit={time_limit}")

        self._beat_gen_worker = BeatVideoGenWorker(server_url, spec, self._beat_work_dir)
        self._beat_gen_worker.progress.connect(self._beat_on_gen_progress)
        self._beat_gen_worker.video_ready.connect(self._beat_on_video_ready)
        self._beat_gen_worker.all_done.connect(self._beat_on_gen_done)
        self._beat_gen_worker.error.connect(self._beat_on_gen_error)
        self._beat_gen_worker.start()

    def _beat_on_gen_progress(self, pct, msg):
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(int(pct))
        if msg and hasattr(self, "beat_status_lbl"):
            self.beat_status_lbl.setText(f"🎬 {msg}")

    def _beat_on_video_ready(self, variant_index, local_path):
        """某个变体视频下载完成：挂到对应卡片并准备播放。"""
        # variant_index 为 0 基变体序号，与波形卡片索引一一对应
        if variant_index < len(self._beat_video_files):
            self._beat_video_files[variant_index] = local_path
        card = self._get_segment_card(variant_index)
        if card:
            card.set_video(local_path)
            if hasattr(self, "beat_preview_video"):
                card.set_video_output(self.beat_preview_video)
        log.info(f"[卡点成片] 变体{variant_index + 1} 视频就绪: {local_path}")

    def _beat_on_gen_done(self, results):
        ok = sum(1 for r in results if r.get("ok"))
        if hasattr(self, "progress_bar"):
            self.progress_bar.setVisible(False)
        self.btn_beat_detect.setEnabled(True)
        if ok > 0:
            self.btn_beat_confirm.setEnabled(True)
            self.beat_status_lbl.setText(
                f"✅ 已生成 {ok}/{len(results)} 个卡点视频，播放片段即可预览，点击「导出视频」保存")
        else:
            self.beat_status_lbl.setText("❌ 卡点视频生成失败，请检查服务端")

    def _beat_on_gen_error(self, err):
        if hasattr(self, "progress_bar"):
            self.progress_bar.setVisible(False)
        self.btn_beat_detect.setEnabled(True)
        self.beat_status_lbl.setText("❌ 卡点视频生成失败")
        log.error(f"[卡点成片] 生成失败: {err}")

    # ═══════════════════════════════════════════════════════════
    #  播放协调（视频输出路由到共享预览）
    # ═══════════════════════════════════════════════════════════

    def _beat_on_card_play_started(self, card):
        """某卡片开始播放：更新预览标题，并把视频输出路由到共享 QVideoWidget。"""
        if getattr(card, "_in_video_mode", False) and hasattr(self, "beat_preview_video"):
            card.set_video_output(self.beat_preview_video)
        if not hasattr(self, "beat_preview_title"):
            return
        if getattr(card, "is_full_track", False):
            self.beat_preview_title.setText("▶ 预览：整体卡点（全曲）")
        elif getattr(card, "_in_video_mode", False):
            self.beat_preview_title.setText(f"▶ 预览：片段 {card.index + 1}（卡点视频）")
        else:
            self.beat_preview_title.setText(f"▶ 预览：片段 {card.index + 1}（仅音乐）")

    def _beat_on_card_position(self, card, abs_sec):
        """播放进度回调：视频即预览，无需额外处理（卡片自行更新游标/时间）。"""
        pass

    # ═══════════════════════════════════════════════════════════
    #  导出视频并打开目录
    # ═══════════════════════════════════════════════════════════

    def _beat_export_videos(self):
        videos = [v for v in getattr(self, "_beat_video_files", []) if v and os.path.isfile(v)]
        if not videos:
            QMessageBox.warning(self.parent_widget, "无可导出视频",
                                "尚未生成任何卡点视频，请先点击「检测卡点」生成。")
            return

        out_dir = self.beat_out_dir_input.text().strip() if hasattr(self, "beat_out_dir_input") else ""
        if not out_dir:
            out_dir = QFileDialog.getExistingDirectory(self.parent_widget, "选择视频导出目录")
            if not out_dir:
                return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self.parent_widget, "目录错误", f"无法创建导出目录：{e}")
            return

        copied = []
        for v in videos:
            dst = os.path.join(out_dir, os.path.basename(v))
            try:
                shutil.copy2(v, dst)
                copied.append(dst)
            except Exception as e:
                log.warning(f"[卡点成片] 导出复制失败 {v}: {e}")

        if copied:
            self.beat_status_lbl.setText(f"✅ 已导出 {len(copied)} 个视频到 {out_dir}")
            QMessageBox.information(self.parent_widget, "导出完成",
                                    f"已导出 {len(copied)} 个卡点视频到：\n{out_dir}")
            try:
                os.startfile(out_dir)  # noqa
            except Exception:
                pass
        else:
            QMessageBox.warning(self.parent_widget, "导出失败", "没有视频复制成功，请查看日志。")
