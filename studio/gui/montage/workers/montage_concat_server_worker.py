# -*- coding: utf-8 -*-
"""智能混剪 - 服务端镜头合成 Worker。

按 /guide 2.10 调用 POST /montage/concat（multipart/form-data）：
  - files: 按顺序上传的镜头文件
  - lut: 可选 LUT 文件（.cube）
  - 其他 form 字段: transition / transition_duration / width / height / fps / crf / preset

提交后通过 GET /scheduled/tasks/{id} 轮询，下载成品到本地。
"""
import os
import time
import json
from contextlib import ExitStack
import requests
from utils.http_client import http_get, http_post
from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils import scheduled_task_client as stc


class MontageConcatServerWorker(BaseWorker):
    """服务端 montage_concat 合成 Worker。

    信号：
        stage(str):      当前阶段文案
        progress(int):   0-100 进度
        concat_finished(str):   本地输出文件绝对路径
        error(str):      失败原因
    """
    stage = Signal(str)
    progress = Signal(int)
    concat_finished = Signal(str)
    task_id_obtained = Signal(str)

    # 轮询间隔（秒）
    _POLL_INTERVAL = 3.0
    # 单文件下载超时（秒）
    _DOWNLOAD_TIMEOUT = 600
    # 上传最低网速估算 500KB/s
    _UPLOAD_SPEED_BPS = 500 * 1024

    def __init__(self, local_output_path, clips, options=None, lut_path=None, task_id=None,
                 source_clips=None, clip_urls=None):
        super().__init__()
        self.local_output_path = local_output_path
        self.clips = list(clips or [])
        self.options = dict(options or {})
        self.lut_path = (lut_path or "").strip()
        self.task_id = task_id
        self.source_clips = list(source_clips or [])
        # 素材检索地址等（material://{id} / http / 本地路径），随 clip_urls 传给服务端，可混合 files
        self.clip_urls = list(clip_urls or [])
        self._stopped = False

    def do_work(self):
        if not self.task_id:
            if not self.clips and not self.clip_urls:
                raise RuntimeError("没有可合成的镜头（本地 files 或 clip_urls 至少一项）")
            self.task_id = self._submit_concat()
        self._poll_and_download()

    def _submit_concat(self):
        """POST /montage/concat：files + 可选 LUT + 合成参数在同一个 multipart 请求里上传。"""
        server = stc._server_url()
        if not server:
            raise RuntimeError("未配置 compute_server_url")
        url = f"{server}/montage/concat"

        total_size = 0
        for path in self.clips:
            if not os.path.isfile(path):
                raise RuntimeError(f"镜头文件不存在: {path}")
            total_size += os.path.getsize(path)

        if self.lut_path:
            if not os.path.isfile(self.lut_path):
                raise RuntimeError(f"LUT 文件不存在: {self.lut_path}")
            total_size += os.path.getsize(self.lut_path)

        # form 字段全部用字符串（服务端从 multipart 里读取）
        data = {k: str(v) for k, v in self.options.items()}
        if self.clip_urls:
            data["clip_urls"] = json.dumps(self.clip_urls, ensure_ascii=False)
            self.stage.emit(f"素材地址 clip_urls: {len(self.clip_urls)} 个")

        with ExitStack() as stack:
            files = []
            for i, path in enumerate(self.clips):
                self.stage.emit(f"正在上传镜头 {i + 1}/{len(self.clips)}: {os.path.basename(path)}")
                f = stack.enter_context(open(path, "rb"))
                files.append(("files", (os.path.basename(path), f)))
            if self.lut_path:
                self.stage.emit(f"正在上传 LUT: {os.path.basename(self.lut_path)}")
                lut_file = stack.enter_context(open(self.lut_path, "rb"))
                files.append(("lut", (os.path.basename(self.lut_path), lut_file)))
            self.stage.emit("正在提交 montage_concat 合成任务...")
            timeout = max(60, int(total_size / self._UPLOAD_SPEED_BPS) + 30)
            try:
                r = http_post(url, data=data, files=files, timeout=timeout)
                r.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"提交 montage_concat 失败: {e}")

        try:
            resp = r.json()
        except Exception as e:
            raise RuntimeError(f"montage_concat 返回解析失败: {e}")

        task_id = resp.get("id")
        if not task_id:
            raise RuntimeError(f"montage_concat 未返回任务 id: {resp}")
        # 通知页面把服务端 task_id 记入任务缓存 manifest
        self.task_id_obtained.emit(str(task_id))
        self.progress.emit(30)
        log.info(f"[montage_concat] 已提交任务 id={task_id}, response={resp}")
        return task_id

    def _poll_and_download(self):
        self.stage.emit(f"已提交服务端合成，任务 ID={self.task_id}，正在轮询...")
        while not self._stopped:
            task = stc.get_task(self.task_id, timeout=10)
            if not task:
                time.sleep(self._POLL_INTERVAL)
                continue

            status = task.get("status", "")
            progress = int(task.get("progress", 0) or 0)
            self.progress.emit(max(30, min(90, 30 + int(progress * 0.6))))

            if status == "completed":
                result = task.get("result") or {}
                video_url = result.get("video_url") or result.get("url") or result.get("output_url")
                if not video_url:
                    raise RuntimeError("服务端合成完成，但结果中未返回 video_url/url/output_url")
                self._download(video_url)
                self._write_sources_file()
                self.stage.emit(f"✅ 服务端合成完成：{os.path.basename(self.local_output_path)}")
                self.progress.emit(100)
                self.concat_finished.emit(self.local_output_path)
                return

            if status in ("failed", "error"):
                error_msg = task.get("error_msg") or task.get("error") or "未知错误"
                raise RuntimeError(f"服务端合成失败：{error_msg}")

            self.stage.emit(f"服务端合成中... {status} ({progress}%)")
            time.sleep(self._POLL_INTERVAL)

        raise RuntimeError("用户终止了服务端合成任务")

    def _download(self, video_url):
        """下载服务端成片到本地输出路径。"""
        out_dir = os.path.dirname(self.local_output_path)
        os.makedirs(out_dir, exist_ok=True)

        full_url = video_url
        if video_url.startswith("/"):
            full_url = stc._server_url() + video_url

        self.stage.emit("正在下载成片...")
        r = http_get(full_url, stream=True, timeout=self._DOWNLOAD_TIMEOUT)
        r.raise_for_status()

        with open(self.local_output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        if not os.path.isfile(self.local_output_path) or os.path.getsize(self.local_output_path) < 1024:
            raise RuntimeError("下载后的成片文件无效或过小")

    def _write_sources_file(self):
        """写入 _sources.txt，保持与本地 VideoConcatWorker 输出一致。"""
        if not self.source_clips:
            return
        sources_file = os.path.splitext(self.local_output_path)[0] + "_sources.txt"
        try:
            with open(sources_file, "w", encoding="utf-8") as sf:
                for src in self.source_clips:
                    sf.write(src + "\n")
        except Exception as e:
            log.warning(f"保存服务端合成源镜头列表失败: {e}")

    def stop(self):
        self._stopped = True
