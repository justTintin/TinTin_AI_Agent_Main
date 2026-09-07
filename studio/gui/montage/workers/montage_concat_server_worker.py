"""智能混剪 - 服务端镜头合成 Worker。

按 /guide 2.10 调用 POST /montage/concat（multipart/form-data）：
  - files: 按顺序上传的镜头文件
  - lut: 可选 LUT 文件（.cube）
  - 其他 form 字段: transition / transition_duration / width / height / fps / crf / preset

提交后通过 GET /scheduled/tasks/{id} 轮询，下载成品到本地。
"""
import json
import os
import subprocess
import time
from contextlib import ExitStack

from PySide6.QtCore import Signal
from utils import scheduled_task_client as stc  # type: ignore[attr-defined]
from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.montage_client import concat, download_result

# 服务端报“找不到自己刚接收的镜头文件”的特征串（服务端内部故障，客户端重试无意义）
_SERVER_LOST_UPLOAD_MARKERS = ("素材不存在", "filenotfounderror", "no such file or directory")


def _looks_like_server_lost_upload(error_msg):
    """判断服务端错误是否属于“上传文件落盘后自己找不到”。

    典型形态：`素材不存在: <服务端部署路径>/uploads/montage/concat_xxx/clip_001.mp4`。
    常见于服务端把 multipart 按原始文件名落盘、而合成引擎按 clip_%03d 取文件，
    或上传目录基准与解析基准不是同一个常量（跨部署路径）。
    与镜头内容/客户端参数无关，回退本地合成即可绕过。
    """
    low = (error_msg or "").lower()
    return any(m in low for m in _SERVER_LOST_UPLOAD_MARKERS)


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
    fallback_to_local = Signal(str)  # 服务端不可用时通知客户端回退本地合成（含原因）

    # 轮询间隔（秒）
    _POLL_INTERVAL = 3.0
    # 单文件下载超时（秒）
    _DOWNLOAD_TIMEOUT = 600
    # 新契约结果端点轮询总超时（秒）：含排队时间，给足 60 分钟
    _RESULT_POLL_TIMEOUT = 60 * 60
    # 上传最低网速估算 500KB/s
    _UPLOAD_SPEED_BPS = 500 * 1024

    def __init__(self, local_output_path, clips, options=None, lut_path=None, task_id=None,  # noqa: E501
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
        # 新契约标记（2026-09 服务端改版）：concat 任务不注册 unified 表，只走结果端点。
        # 默认 True——恢复任务（task_id 由 manifest 传入，无提交响应可判别）同样只走结果端点；
        # _submit_concat 会按提交响应里有无 queue_position 覆盖（旧服务端无此字段 → 走 unified）。
        self._new_contract = True

    def do_work(self):
        if not self.task_id:
            if not self.clips and not self.clip_urls:
                raise RuntimeError("没有可合成的镜头（本地 files 或 clip_urls 至少一项）")
            self.task_id = self._submit_concat()
            if self.task_id is None:
                # _submit_concat 返回 None 表示已触发 fallback_to_local 信号，无需继续
                return
        self._poll_and_download()

    def _submit_concat(self):
        """POST /montage/concat：files + 可选 LUT + 合成参数在同一个 multipart 请求里上传。"""
        server = stc._server_url()
        if not server:
            raise RuntimeError("未配置 compute_server_url")

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
                self.stage.emit(f"正在上传镜头 {i + 1}/{len(self.clips)}: {os.path.basename(path)}")  # noqa: E501
                f = stack.enter_context(open(path, "rb"))
                files.append(("files", (os.path.basename(path), f)))
            if self.lut_path:
                self.stage.emit(f"正在上传 LUT: {os.path.basename(self.lut_path)}")
                lut_file = stack.enter_context(open(self.lut_path, "rb"))
                files.append(("lut", (os.path.basename(self.lut_path), lut_file)))
            self.stage.emit("正在提交 montage_concat 合成任务...")
            timeout = max(60, int(total_size / self._UPLOAD_SPEED_BPS) + 30)
            try:
                resp = concat(server, files, data, timeout)
            except Exception as e:
                err_str = str(e)
                # 402 Payment Required：服务端授权/配额问题，通知客户端回退本地合成
                if "402" in err_str:
                    log.warning(f"[montage_concat] 服务端返回 402，回退本地合成: {err_str}")
                    self.fallback_to_local.emit(f"服务端返回 402 (Payment Required)，已自动回退到本地合成")
                    return None
                raise RuntimeError(f"提交 montage_concat 失败: {e}") from e

        task_id = resp.get("id")
        if not task_id:
            raise RuntimeError(f"montage_concat 未返回任务 id: {resp}")
        # 新契约判别：响应含 queue_position（2026-09 服务端改版）。新契约的 concat 任务
        # 不注册 unified 表——unified/{id} 返回 200 必为历史任务撞名（同类型旧任务
        # task_type 也含 montage，仅拦异类型的旧判据挡不住），其 completed 态会被误
        # 消费、下载它的 video_url 必 404 → 误报「成片无效」。新契约只走结果端点轮询。
        self._new_contract = "queue_position" in resp
        # 通知页面把服务端 task_id 记入任务缓存 manifest
        self.task_id_obtained.emit(str(task_id))
        self.progress.emit(30)
        log.info(f"[montage_concat] 已提交任务 id={task_id}, response={resp}")
        return task_id

    def _poll_and_download(self):
        self.stage.emit(f"已提交服务端合成，任务 ID={self.task_id}，正在轮询...")
        deadline = time.monotonic() + self._RESULT_POLL_TIMEOUT
        collision_logged = False
        while not self._stopped:
            # 超时检查对所有路径生效（含旧契约 unified 轮询），
            # 防止服务端任务永远停在 running 时 worker 无限轮询、按钮永久禁用
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"服务端合成超时（>{self._RESULT_POLL_TIMEOUT // 60} 分钟），任务 ID={self.task_id}。"
                    "请稍后重试或回退本地合成。")
            if not self._new_contract:
                task = stc.get_task(self.task_id, timeout=10)
                ttype = str((task or {}).get("task_type") or "")
                if task is not None and ttype and "montage" not in ttype.lower():
                    # unified 命中但 task_type 不符 → ID 撞名（如 editor_render 的历史任务），
                    # 不能拿它的 result.video_url 去下载（会拿到别的任务的产物或 404）。
                    if not collision_logged:
                        log.info(f"[montage_concat] unified/{self.task_id} 是其它类型任务({ttype})，改用 concat 结果端点轮询")  # noqa: E501
                        collision_logged = True
                elif task is not None:
                    # 旧契约：concat 任务注册在 unified 表（task_type 含 montage 或历史响应无 task_type）
                    if self._consume_unified_task(task):
                        return
                    time.sleep(self._POLL_INTERVAL)
                    continue

            # 新契约：GET /montage/concat/result/{id} 兼作状态与结果——
            # 未完成 404，完成 200 直出 mp4。
            if self._poll_result_endpoint():
                return
            self.progress.emit(max(30, min(90, 30 + int(30 * 0.6))))
            time.sleep(self._POLL_INTERVAL)

        raise RuntimeError("用户终止了服务端合成任务")

    def _consume_unified_task(self, task):
        """旧契约处理 unified 任务状态。返回 True 表示已到终态（完成/失败/回退），False 继续轮。"""
        status = task.get("status", "")
        progress = int(task.get("progress", 0) or 0)
        self.progress.emit(max(30, min(90, 30 + int(progress * 0.6))))

        if status == "completed":
            result = task.get("result") or {}
            video_url = result.get("video_url") or result.get("url") or result.get("output_url")  # noqa: E501
            if not video_url:
                raise RuntimeError("服务端合成完成，但结果中未返回 video_url/url/output_url")
            if not self._download(video_url):
                # unified 显示 completed 但成片下载不到（HTTP 非 200）→ 极可能是
                # 历史任务撞名（同类型旧任务恰好同 ID），不能据此报错终止；
                # 改走结果端点继续轮询真正属于本次提交的任务，由总超时兜底。
                log.warning(f"[montage_concat] unified/{self.task_id} 显示 completed 但成片下载失败，"
                            "判定为历史任务撞名，改用 concat 结果端点轮询")
                return False
            self._write_sources_file()
            self.stage.emit(f"完成： 服务端合成完成：{os.path.basename(self.local_output_path)}")  # noqa: E501
            self.progress.emit(100)
            self.concat_finished.emit(self.local_output_path)
            return True

        if status in ("failed", "error"):
            error_msg = task.get("error_msg") or task.get("error") or "未知错误"
            # 服务端找不到自己刚接收的镜头文件 → 服务端内部问题，直接回退本地合成。
            # 仅在所有片段都是本地上传（无 material:// 需服务端解析）时回退，
            # 否则本地合成会缺掉素材库片段，静默产出错片。
            if not self.clip_urls and _looks_like_server_lost_upload(error_msg):
                log.warning(f"[montage_concat] 服务端丢失自身上传文件，回退本地合成: {error_msg[:300]}")  # noqa: E501
                self.fallback_to_local.emit(
                    "服务端合成失败（服务端找不到自己接收的镜头文件，属服务端问题），已自动回退到本地合成")  # noqa: E501
                return True
            raise RuntimeError(f"服务端合成失败：{error_msg}")

        self.stage.emit(f"服务端合成中... {status} ({progress}%)")
        return False

    def _poll_result_endpoint(self):
        """新契约轮询：GET /montage/concat/result/{id}。

        未完成 404（返回 False 继续轮）；完成 200 直出 mp4（落盘、发信号、返回 True）。
        """
        url = f"{stc._server_url()}/montage/concat/result/{self.task_id}"
        saved = download_result(url, self.local_output_path, self._DOWNLOAD_TIMEOUT)
        if not saved:
            return False  # 404=尚未完成；其它异常也继续轮，由总超时兜底
        # 完整性校验，失败自动重下一次；仍失败则报错（不无限轮，防服务端产物本身损坏）
        self._validate_downloaded_file(redownload_url=url)
        self._write_sources_file()
        self.stage.emit(f"完成： 服务端合成完成：{os.path.basename(self.local_output_path)}")  # noqa: E501
        self.progress.emit(100)
        self.concat_finished.emit(self.local_output_path)
        return True

    def _download(self, video_url):
        """下载服务端成片到本地输出路径。

        返回 False 表示未取到文件（HTTP 非 200/网络异常，如任务尚未产出）——
        不得把空文件/404 响应当成已下载的成片去走完整性校验（会误报「文件损坏」）。
        """
        out_dir = os.path.dirname(self.local_output_path)
        os.makedirs(out_dir, exist_ok=True)

        full_url = video_url
        if video_url.startswith("/"):
            full_url = stc._server_url() + video_url

        self.stage.emit("正在下载成片...")
        if not download_result(full_url, self.local_output_path, self._DOWNLOAD_TIMEOUT):  # noqa: E501
            log.warning(f"[montage_concat] 成片下载失败（服务端未返回 200 或网络异常）: {full_url}")
            return False
        # 完整性校验（>1KB 且 ffprobe 可读），失败自动重下一次；
        # 防止截断文件（moov 缺失）溜过大小校验，直到配音/预览步骤才报莫名的 ffmpeg 错。
        self._validate_downloaded_file(redownload_url=full_url)
        return True

    @staticmethod
    def _probe_video_ok(path):
        """ffprobe 能读出时长>0 视为完整（moov 缺失/截断文件会失败）。"""
        try:
            from utils.platform_utils import find_ffprobe, run_subprocess
            ffprobe = find_ffprobe()
            if not ffprobe or not os.path.isfile(ffprobe):
                return True  # 无 ffprobe 时退化为只做大小校验，不阻塞流程
            r = run_subprocess([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", path],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False
            return float((r.stdout or "").strip() or 0) > 0
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            return False

    def _validate_downloaded_file(self, redownload_url=""):
        """成片完整性校验（>1KB 且 ffprobe 可读）；失败时重下 1 次再验，仍失败则报错。

        区分两种失败：从未取到文件（HTTP 非 200/空响应）vs 取到了但损坏——
        二者根因不同（任务未产出/URL 失效 vs 下载中断），报错文案需可区分。
        """
        has_file = False
        for attempt in (1, 2):
            has_file = (os.path.isfile(self.local_output_path)
                        and os.path.getsize(self.local_output_path) >= 1024)
            if has_file and self._probe_video_ok(self.local_output_path):
                return
            log.warning(f"[montage_concat] 成片完整性校验未通过（第 {attempt}/2 次）: "
                        f"{self.local_output_path}")
            if redownload_url and attempt == 1:
                log.warning("[montage_concat] 尝试重新下载成片…")
                download_result(redownload_url, self.local_output_path, self._DOWNLOAD_TIMEOUT)  # noqa: E501
        if not has_file:
            raise RuntimeError(
                "成片下载失败：服务端未返回有效文件（HTTP 非 200 或空响应），"
                "通常为任务尚未完成或结果链接失效。请重新执行合成；"
                "若反复出现请检查网络/服务端。")
        raise RuntimeError(
            "下载后的成片无效：文件不完整或损坏（如 moov 缺失，常见于下载中断或"
            "服务端产物异常）。请重新执行合成；若反复出现请检查网络/服务端。")

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
