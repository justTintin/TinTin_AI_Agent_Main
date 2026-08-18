"""Step 1 镜头分割控制器

把原本堆在 VideoMontagePage 里的第1步业务逻辑抽出来，
让 Step1SplitView 持有控制器，VideoMontagePage 只保留共享状态和导航。
当前版本为了保持改动可控，控制器仍通过 main_page 访问UI控件和部分共享方法，
后续阶段再进一步解耦。
"""
import contextlib
import os

from gui.montage.workers.split_workers import BestClipWorker, ServerSplitWorker
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox
from utils.logger_utils import log


class Step1SplitController(QObject):
    """第1步：智能镜头分割的完整业务控制。"""

    def __init__(self, view, main_page):
        super().__init__(view)
        self.view = view
        self.main_page = main_page

        # 多视频分割队列状态
        self._merged_queue = []
        self._merged_total = 0
        self._merged_done = 0
        self._merged_split_ok = 0
        self._merged_hl_ok = 0
        self._merged_fail = 0
        self._merged_fail_msgs = []
        self._merged_per_video_splits = []
        self._merged_hl_duration = 3.0
        self._merged_cur_item = None
        self._merged_cur_video = ""
        self._merged_cur_splits_dir = ""

        # worker 引用
        self.worker = None
        self.highlight_worker = None
        self._retired_workers = []

    # ------------------------------------------------------------------
    # 工具：访问 main_page 上的 UI 控件（后续应改为由 view 提供）
    # ------------------------------------------------------------------
    def _stage(self, text):
        if hasattr(self.main_page, "stage_label") and self.main_page.stage_label:
            self.main_page.stage_label.setText(text)

    def _progress(self, value):
        if hasattr(self.main_page, "progress_bar") and self.main_page.progress_bar:
            self.main_page.progress_bar.setValue(value)

    def _progress_range(self, min_v, max_v):
        if hasattr(self.main_page, "progress_bar") and self.main_page.progress_bar:
            self.main_page.progress_bar.setRange(min_v, max_v)

    def _progress_visible(self, visible):
        if hasattr(self.main_page, "progress_bar") and self.main_page.progress_bar:
            self.main_page.progress_bar.setVisible(visible)

    def _set_split_buttons_enabled(self, enabled):
        if hasattr(self.main_page, "btn_split") and self.main_page.btn_split:
            self.main_page.btn_split.setEnabled(enabled)
        if hasattr(self.main_page, "btn_transcribe_raw") and self.main_page.btn_transcribe_raw:
            self.main_page.btn_transcribe_raw.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 公共方法：启动分割
    # ------------------------------------------------------------------
    def start_split(self):
        """合并后的智能镜头分割入口。"""
        if (self.worker and self.worker.isRunning()) or \
           (self.highlight_worker and self.highlight_worker.isRunning()):
            QMessageBox.warning(self.main_page.parent_widget, "正在处理中",
                                "上一次分割/挑精华还在运行中，请等待完成或停止后重试。")
            return

        image_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")

        def _is_img_path(p):
            return os.path.splitext(p or "")[1].lower() in image_exts

        items = []
        video_list = self.main_page.video_list
        for i in range(video_list.count()):
            it = video_list.item(i)
            if it is None:
                continue
            t = it.text().strip()
            if not t:
                continue
            if self.main_page._is_local_file_item(it):
                items.append({"kind": "local", "path": t, "display": os.path.basename(t)})
            elif t.startswith("material://"):
                mid = t[len("material://"):].split(" ")[0].strip()
                if mid:
                    items.append({"kind": "server", "material_id": mid,
                                  "clip_url": f"material://{mid}", "display": t})
        if not items:
            QMessageBox.warning(self.main_page.parent_widget, "无素材",
                                "素材列表中没有可处理的素材。\n"
                                "请从本地上传视频/图片，或从素材库选择素材。")
            return

        dur = self.main_page.spin_highlight_sec.value()
        local_n = sum(1 for x in items if x["kind"] == "local")
        server_n = sum(1 for x in items if x["kind"] == "server")

        local_paths = [x["path"] for x in items if x["kind"] == "local"]
        shared_root = self.main_page.folder_path_input.text().strip()
        if local_paths and (not shared_root or not os.path.isdir(shared_root)):
            try:
                shared_root = os.path.commonpath([os.path.dirname(p) for p in local_paths])
            except Exception:
                shared_root = os.path.dirname(local_paths[0])
            self.main_page.folder_path_input.setText(shared_root)

        self.main_page._ensure_montage_job()
        sp_root = self.main_page._montage_splits_root()
        per_video_splits = []
        for x in items:
            if x["kind"] == "local":
                per_video_splits.append(self.main_page._montage_per_video_splits_dir(x["path"]))
            else:
                per_video_splits.append(os.path.join(sp_root, f"mat_{x['material_id']}"))

        if len(set(per_video_splits)) == 1:
            out_summary = per_video_splits[0]
        else:
            out_summary = f"{len(per_video_splits)} 个素材各自工作目录\n(例: {per_video_splits[0]})"

        local_img = sum(1 for x in items if x["kind"] == "local" and _is_img_path(x["path"]))
        local_vid = max(0, local_n - local_img)
        confirm_msg = (f"将对列表中的 {len(items)} 个素材进行处理\n"
                       f"- 本地视频 {local_vid} 个：服务端镜头分割 + 逐镜分析\n"
                       f"- 本地图片 {local_img} 个：转静态镜头 + 分析\n"
                       f"- 素材库素材 {server_n} 个：按服务端按素材地址分割/转静态镜头 + 分析\n"
                       f"- 无法分割的长视频将自动提取约 {dur:.0f} 秒的精华片段。\n"
                       f"- 分割/分析完成后所有镜头将填入下方镜头列表。\n")
        confirm_msg += (f"\n分割片段输出目录（任务级缓存，不影响原始素材）：\n{out_summary}\n"
                        f"注意：若共享根目录下有旧的分割片段会被清除。\n\n确认开始？")
        reply = QMessageBox.question(
            self.main_page.parent_widget, "智能镜头分割",
            confirm_msg,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 清空已存在的分镜片段
        try:
            for sp_dir in set(per_video_splits):
                os.makedirs(sp_dir, exist_ok=True)
                for f in os.listdir(sp_dir):
                    if "_shot_" in f and f.lower().endswith((".mp4", ".m4v")):
                        with contextlib.suppress(Exception):
                            os.remove(os.path.join(sp_dir, f))
        except Exception as e:
            QMessageBox.warning(self.main_page.parent_widget, "无法准备目录", f"创建/清空 splits 目录失败：\n{e}")
            return

        self._merged_queue = list(items)
        self._merged_total = len(items)
        self._merged_done = 0
        self._merged_split_ok = 0
        self._merged_hl_ok = 0
        self._merged_fail = 0
        self._merged_fail_msgs = []
        self._merged_per_video_splits = per_video_splits
        self._merged_hl_duration = dur

        self._set_split_buttons_enabled(False)
        self._progress_visible(True)
        self._progress_range(0, 100)
        self._progress(0)

        self._process_next_merged_video()

    def _process_next_merged_video(self):
        if not self._merged_queue:
            self._on_merged_all_finished()
            return

        item = self._merged_queue.pop(0)
        self._merged_cur_item = item
        self._merged_cur_video = item.get("path") or item.get("display") or ""
        idx = self._merged_done + 1
        fname = item.get("display") or os.path.basename(item.get("path") or "")

        cur_splits_dir = self._merged_per_video_splits[self._merged_done]
        self._merged_cur_splits_dir = cur_splits_dir

        if item["kind"] == "local" and not os.path.exists(item.get("path", "")):
            self._merged_fail += 1
            self._merged_fail_msgs.append(f"{fname}: 文件不存在")
            self._merged_done += 1
            self._process_next_merged_video()
            return

        self._stage(f"智能镜头分割 ({idx}/{self._merged_total})：{fname}")
        self._progress(int(self._merged_done * 100 / max(1, self._merged_total)))

        self._start_merged_split(item, cur_splits_dir,
                                self.main_page.threshold_spin.value(),
                                float(self.main_page.min_len_spin.value()))

    def _retire_worker(self, w):
        """保留 QThread 引用直到线程结束，避免对象被 GC 时线程仍在运行导致崩溃。

        说明：ServerSplitWorker 现在先 emit analysis_ready 再 emit finished，
        因此 analysis_ready 的槽会在 finished 之前处理，缓存会先写入再启动下一个视频。
        保留 pool 是为了防止跨线程信号在对象释放前仍需要存活引用，统一在
        _on_merged_all_finished 里清理。
        """
        if w is None:
            return
        if w not in self._retired_workers:
            self._retired_workers.append(w)

    def _start_merged_split(self, item, cur_splits_dir, threshold, min_scene_len):
        """镜头分割：服务端 /montage/split（分割+分析合并），失败时本地视频自动挑精华。"""
        is_local = item["kind"] == "local"
        video_path = item.get("path") if is_local else ""
        self._retire_worker(self.worker)
        self.worker = ServerSplitWorker(
            video_path=video_path or None,
            output_dir=cur_splits_dir,
            threshold=threshold,
            min_scene_len=min_scene_len,
            material_id=item.get("material_id", "") if not is_local else "",
            clip_url=item.get("clip_url", "") if not is_local else "",
        )
        self.worker.stage.connect(self._stage)
        self.worker.finished.connect(self._on_merged_split_done)
        self.worker.analysis_ready.connect(
            lambda meta, _d=cur_splits_dir, _v=video_path: self._on_split_analysis_ready(meta, _d, _v))
        self.worker.error.connect(self._on_merged_split_error)
        self.worker.start()

    def _on_split_analysis_ready(self, shot_meta, splits_dir, video_path):
        """服务端分割返回的逐镜分析结果写入 sidecar 缓存。

        评分/desc/景别/产品/型号等从服务端返回，直接写缓存，
        下次 _check_split_clips_exist 扫描时回填。
        """
        if not shot_meta or not splits_dir:
            return
        try:
            from gui.montage.utils_media import safe_source_name as _safe_vbase
            from utils.shot_analysis_cache import ShotAnalysisCache
            first_fname = ""
            for _m in shot_meta:
                if _m.get("filename"):
                    first_fname = _m["filename"]
                    break
            if video_path:
                vbase = _safe_vbase(video_path)
            elif first_fname and "_shot_" in first_fname:
                vbase = first_fname.split("_shot_")[0]
            else:
                vbase = ""
            workspace = os.path.dirname(splits_dir)
            if not workspace:
                return
            cache = ShotAnalysisCache(workspace, vbase)
            for meta in shot_meta:
                fname = meta.get("filename") or ""
                idx = meta.get("shot_index")
                path = ""
                if idx is not None and os.path.isdir(splits_dir):
                    import re as _re
                    _pat = _re.compile(rf"_shot_{idx:03d}" + r"(?:[^\s]*)?\.(mp4|m4v)$")
                    cand = [f for f in os.listdir(splits_dir)
                            if _pat.search(f)]
                    if cand:
                        path = os.path.join(splits_dir, sorted(cand)[0])
                if not path or not os.path.isfile(path):
                    path = os.path.join(splits_dir, fname)
                if not os.path.isfile(path):
                    log.warning(f"[分割分析] 找不到镜头片段: {fname}")
                    continue
                as_ = meta.get("aesthetic_score") or {}
                sa = meta.get("shot_analysis") or {}
                if not isinstance(as_, dict):
                    as_ = {}
                if not isinstance(sa, dict):
                    sa = {}
                cache.upsert(path, {
                    "score": as_.get("total"),
                    "desc": meta.get("description") or sa.get("scene_primary") or "",
                    "shot_type": sa.get("shot_type") or "",
                    "product": sa.get("product") or "",
                    "model": sa.get("model") or "",
                    "extra": {"aesthetic_score": as_, "shot_analysis": sa},
                })
                if meta.get("description"):
                    self.main_page.split_descriptions[os.path.abspath(path)] = meta["description"]
                if path in self.main_page.split_clips_cache:
                    self.main_page.split_clips_cache[path]["score"] = as_.get("total")
                    self.main_page.split_clips_cache[path]["shot_type"] = sa.get("shot_type") or ""
                    self.main_page.split_clips_cache[path]["product"] = sa.get("product") or ""
                    self.main_page.split_clips_cache[path]["model"] = sa.get("model") or ""
                    if meta.get("description"):
                        self.main_page.split_clips_cache[path]["desc"] = meta["description"]
            log.info(f"[分割分析] 已写入 {len(shot_meta)} 条分析缓存 -> {splits_dir}")
            from PySide6.QtCore import QTimer
            def _safe_refresh():
                try:
                    import shiboken6 as _sb
                    if _sb.isValid(self.main_page) and hasattr(self.main_page, "split_result_table"):
                        self.main_page._check_split_clips_exist()
                except Exception:
                    pass
            QTimer.singleShot(0, _safe_refresh)
        except Exception as e:
            log.warning(f"写入分割分析缓存失败: {e}")

    def _on_merged_split_done(self, out_dir, count, scenes):
        item = self._merged_cur_item or {}
        is_local = item.get("kind") == "local"
        video_path = item.get("path") or ""
        fname = item.get("display") or os.path.basename(video_path) or ""
        if count > 0:
            self._merged_split_ok += 1
            log.info(f"[合并分割] {fname} 分割出 {count} 个镜头")
            if is_local and video_path and os.path.isfile(video_path):
                self.main_page._rename_video_splits_with_metadata(self._merged_cur_splits_dir, video_path, scenes)
            self._merged_done += 1
            self._process_next_merged_video()
        else:
            if is_local:
                log.info(f"[合并分割] {fname} 未检测到镜头切点，改为挑精华")
                self._run_merged_highlight(video_path)
            else:
                log.info(f"[合并分割] 素材库视频 {fname} 未检测到镜头切点，跳过")
                self._merged_fail += 1
                self._merged_fail_msgs.append(f"{fname}: 服务端未检测到镜头切点")
                self._merged_done += 1
                self._process_next_merged_video()

    def _on_merged_split_error(self, err):
        item = self._merged_cur_item or {}
        is_local = item.get("kind") == "local"
        video_path = item.get("path") or ""
        fname = item.get("display") or os.path.basename(video_path) or ""
        if not is_local:
            log.warning(f"[合并分割] 素材库视频 {fname} 分割失败，跳过: {err}")
            self._merged_fail += 1
            self._merged_fail_msgs.append(f"{fname}: 服务端分割失败")
            self._merged_done += 1
            self._process_next_merged_video()
            return
        log.warning(f"[合并分割] {fname} 镜头分割失败，改为挑精华: {err}")
        self._run_merged_highlight(video_path)

    def _run_merged_highlight(self, video_path):
        fname = os.path.basename(video_path)
        idx = self._merged_done + 1
        self._stage(f"无法分割，提取精华 ({idx}/{self._merged_total})：{fname}")
        self.highlight_worker = BestClipWorker(
            video_path=video_path,
            output_dir=self._merged_cur_splits_dir,
            duration_sec=self._merged_hl_duration,
            shot_index=1,
            clear_dir=False,
        )
        self.highlight_worker.finished.connect(self._on_merged_highlight_done)
        self.highlight_worker.error.connect(self._on_merged_highlight_error)
        self.highlight_worker.start()

    def _on_merged_highlight_done(self, out_path, start, end):
        self._merged_hl_ok += 1
        log.info(f"[合并分割] 精华片段生成完成：{out_path} [{start:.2f}-{end:.2f}]")
        self._merged_done += 1
        self._process_next_merged_video()

    def _on_merged_highlight_error(self, err):
        video_path = self._merged_cur_video
        fname = os.path.basename(video_path) if video_path else ""
        last_line = (err or "").strip().splitlines()[-1] if err else "未知错误"
        self._merged_fail += 1
        self._merged_fail_msgs.append(f"{fname}: {last_line[:100]}")
        log.error(f"[合并分割] {fname} 精华提取也失败：{err}")
        self._merged_done += 1
        self._process_next_merged_video()

    def _on_merged_all_finished(self):
        self._set_split_buttons_enabled(True)
        self.main_page.processing_video_path = ""
        self.main_page.video_list.setCurrentItem(None)
        if hasattr(self.main_page, "temp_scenes"):
            self.main_page.temp_scenes = []
        self.main_page._last_merged_splits_dirs = list(set(self._merged_per_video_splits))
        self.main_page._sync_manifest_local_clips()

        msg = (f"处理完成：分割 {self._merged_split_ok} 个，挑精华 {self._merged_hl_ok} 个，"
               f"失败 {self._merged_fail} 个，共 {self._merged_total} 个素材。")
        detail = msg
        if self._merged_fail_msgs:
            detail += "\n\n失败详情：\n" + "\n".join(self._merged_fail_msgs[:8])

        self._stage("完成： " + msg)
        self._progress_range(0, 0)
        self.main_page._pending_dialog = ("智能镜头分割完成", detail)
        self.main_page._check_split_clips_exist()
        self._retired_workers = []
