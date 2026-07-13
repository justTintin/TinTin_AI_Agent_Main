# -*- coding: utf-8 -*-
"""
视频索引流水线（NAS 视频 → 哈希 → 抽帧 → 上传 RustFS → AI 标签 → Whisper 转写）。

VideoIndexWorker 是一个 BaseWorker，对单个视频文件走完整流水线，
最终把三向映射记录写入 VideoIndexManager。

各阶段均可单独跳过（已有数据时）或独立触发（如仅补充转写）。
"""
import os
import re
import json
import time
import base64
import tempfile

from utils.base_worker import BaseWorker
from utils.logger_utils import log
from PySide6.QtCore import Signal


# ─── 抽帧（复用 video_ai_rename_page 的 cv2 方案）──────────────────────────

def extract_frames_to_files(video_path: str, num_frames: int = 8,
                             out_dir: str = None) -> list[str]:
    """
    从视频抽取 num_frames 帧，保存为 JPG 文件，返回文件路径列表。
    均匀采样 10%–90% 区间，首帧（0%）强制包含。
    """
    try:
        import cv2
    except ImportError:
        log.error("cv2 未安装，无法抽帧")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return []

    remaining = max(num_frames - 1, 0)
    ratios = [0.0]
    if remaining > 0:
        ratios += [0.10 + 0.80 * i / (remaining + 1) for i in range(1, remaining + 1)]

    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="vidx_frames_")

    saved = []
    for idx, r in enumerate(ratios):
        fi = int(total * r)
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ret, frame = cap.read()
        if not ret:
            continue
        fh, fw = frame.shape[:2]
        max_side = 720
        if max(fh, fw) > max_side:
            scale = max_side / max(fh, fw)
            frame = cv2.resize(frame, (int(fw * scale), int(fh * scale)))
        out_path = os.path.join(out_dir, f"frame_{idx + 1:04d}.jpg")
        cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        saved.append(out_path)

    cap.release()
    return saved


def frame_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ─── 视觉 LLM：提取 AI 标签（语义标签列表，区别于重命名页的品牌/型号）─────────

def call_vision_for_tags(frames_b64: list[str], api_url: str,
                         api_key: str, model: str) -> list[str]:
    """
    把多帧 base64 图片一次发给视觉模型，提取画面语义标签列表。
    返回 ["键盘", "机械轴", "俯拍", "客制化"] 格式。
    """
    if not frames_b64:
        return []
    try:
        import requests as req
        system_prompt = (
            "你是专业的消费电子/产品视频标注专家。\n"
            "给你若干视频关键帧，请归纳画面中出现的所有语义标签。\n"
            "标签应覆盖：产品品类、品牌、型号关键词、拍摄角度、场景、颜色、特效等。\n"
            "只返回 JSON 数组，不要任何其他内容，例如：\n"
            "[\"键盘\", \"机械轴\", \"客制化\", \"俯拍\", \"白色\", \"特写\"]"
        )
        content = [{"type": "text", "text": "请分析以下视频关键帧，返回语义标签数组："}]
        for i, b64 in enumerate(frames_b64[:6]):   # 最多 6 帧，防止 token 超限
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        url = f"{api_url.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "num_ctx": 32768,  # Ollama: override default 4096 context for vision models
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }
        resp = req.post(url, json=payload, headers=headers, timeout=90)
        if resp.status_code != 200:
            log.error(f"视觉 LLM 返回 {resp.status_code}: {resp.text[:200]}")
            return []
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # 清除 markdown 代码块
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            raw = m.group(0)
        tags = json.loads(raw)
        return [str(t).strip() for t in tags if str(t).strip()]
    except Exception as e:
        log.error(f"视觉 LLM 标签提取失败: {e}")
        return []


# ─── Whisper 转写（纯远程 ASR 服务）──

def transcribe_audio(video_path: str, models_dir: str,
                     model_name: str = "large-v3") -> str:
    """
    调用远程 ASR 服务对视频音轨转写，返回纯文本台词。

    远程模式下走 asr_client 远程服务，不加载本地模型。
    models_dir / model_name 参数仅为兼容调用方签名保留，本模式下不再使用。
    """
    try:
        from utils.asr_client import read_asr_url, transcribe_remote, segments_to_plain
        asr_url = read_asr_url()
        if not asr_url:
            log.warning("未配置远程 ASR 服务地址，跳过转写")
            return ""
        segments = transcribe_remote(video_path, asr_url, language="zh")
        return segments_to_plain(segments)
    except Exception as e:
        log.warning(f"远程 ASR 转写失败（跳过）: {e}")
        return ""


# ─── 主流水线 Worker ──────────────────────────────────────────────────────────

class VideoIndexWorker(BaseWorker):
    """
    对单个视频文件走完整索引流水线：
      hash → 抽帧 → 上传 RustFS → AI 标签 → Whisper 转写 → 写入映射表

    stage_log(str)  : 阶段日志（显示在 UI 进度框）
    finished(dict)  : 完成后发出完整的映射记录
    """
    stage_log = Signal(str)
    finished  = Signal(dict)

    def __init__(self, video_path: str, *,
                 num_frames: int = 8,
                 run_whisper: bool = False,
                 whisper_model: str = "small",
                 skip_if_indexed: bool = True):
        super().__init__()
        self.video_path = video_path
        self.num_frames = num_frames
        self.run_whisper = run_whisper
        self.whisper_model = whisper_model
        self.skip_if_indexed = skip_if_indexed

    def _log(self, msg: str):
        log.info(msg)
        self.stage_log.emit(msg)

    def do_work(self):
        from config.paths import AI_CONFIG_FILE, WHISPER_MODELS_DIR
        from utils.rustfs_manager import _build_client, _ensure_bucket, get_rustfs_config

        vpath = self.video_path
        # mgr = VideoIndexManager()  # removed with material mgmt

        # ── 1. 哈希 ──────────────────────────────────────────────
        self._log(f"[1/5] 计算哈希：{os.path.basename(vpath)}")
        video_id = compute_video_hash(vpath)
        if not video_id:
            raise RuntimeError("哈希计算失败，文件可能不可读")

        if self.skip_if_indexed:
            existing = mgr.get_by_id(video_id)
            if existing and existing.get("frame_count", 0) > 0:
                self._log(f"  已索引（{video_id}），跳过")
                self.finished.emit(existing)
                return

        # ── 2. 读取视频元信息 ──────────────────────────────────────
        self._log("[2/5] 读取视频元信息")
        duration, resolution = 0.0, ""
        try:
            import cv2
            cap = cv2.VideoCapture(vpath)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 1
                fc = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                duration = round(fc / fps, 2)
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                resolution = f"{w}x{h}" if w and h else ""
            cap.release()
        except Exception as e:
            self._log(f"  元信息读取失败（跳过）: {e}")

        # ── 3. 抽帧 + 上传 RustFS ──────────────────────────────────
        self._log(f"[3/5] 抽取 {self.num_frames} 帧并上传 RustFS")
        tmp_dir = tempfile.mkdtemp(prefix=f"vidx_{video_id}_")
        frame_paths = extract_frames_to_files(vpath, self.num_frames, tmp_dir)
        self._log(f"  抽出 {len(frame_paths)} 帧")

        cfg = get_rustfs_config()
        bucket = cfg["bucket"]
        remote_prefix = f"{video_id}/"
        frame_count = 0

        try:
            client, _ = _build_client()
            _ensure_bucket(client, bucket)
            for fp in frame_paths:
                obj_key = remote_prefix + os.path.basename(fp)
                client.upload_file(fp, bucket, obj_key)
                frame_count += 1
                self._log(f"  ✓ 上传 {os.path.basename(fp)}")
        except Exception as e:
            self._log(f"  ⚠ RustFS 上传失败（继续建索引）: {e}")

        # ── 4. AI 标签（视觉 LLM）────────────────────────────────
        self._log("[4/5] 视觉模型提取语义标签")
        ai_tags: list[str] = []
        try:
            ai_cfg = {}
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                ai_cfg = json.load(f)
            api_url = ai_cfg.get("llm_vision_api_url", "")
            api_key = ai_cfg.get("llm_vision_api_key") or ai_cfg.get("llm_api_key", "")
            model = ai_cfg.get("llm_vision_model", "")
            if api_url and model and frame_paths:
                frames_b64 = [frame_to_b64(p) for p in frame_paths[:6]]
                ai_tags = call_vision_for_tags(frames_b64, api_url, api_key, model)
                self._log(f"  标签: {ai_tags}")
            else:
                self._log("  视觉 API 未配置，跳过标签提取")
        except Exception as e:
            self._log(f"  标签提取失败（跳过）: {e}")

        # ── 5. Whisper 转写（可选）────────────────────────────────
        audio_script = ""
        if self.run_whisper:
            self._log("[5/5] Whisper 音频转写")
            audio_script = transcribe_audio(vpath, WHISPER_MODELS_DIR, self.whisper_model)
            self._log(f"  转写完成，{len(audio_script)} 字")
        else:
            self._log("[5/5] 跳过 Whisper 转写（可后续单独触发）")

        # ── 清理临时帧文件 ────────────────────────────────────────
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

        # ── 写入映射表 ────────────────────────────────────────────
        entry = {
            "video_id":        video_id,
            "nas_smb_path":    vpath,
            "s3_bucket":       bucket,
            "s3_frame_prefix": remote_prefix,
            "frame_count":     frame_count,
            "ai_tags":         ai_tags,
            "audio_script":    audio_script,
            "vector_id":       "",          # 预留，接入向量库时填充
            "duration":        duration,
            "resolution":      resolution,
            "file_size":       os.path.getsize(vpath) if os.path.exists(vpath) else 0,
        }
        saved = mgr.upsert(entry)
        self._log(f"✅ 索引完成 video_id={video_id}")
        self.finished.emit(saved)


class WhisperFillWorker(BaseWorker):
    """仅对已索引但无转写的条目补充 Whisper 转写，不重新抽帧。"""
    stage_log = Signal(str)
    finished  = Signal(dict)

    def __init__(self, video_id: str, video_path: str, whisper_model: str = "small"):
        super().__init__()
        self.video_id = video_id
        self.video_path = video_path
        self.whisper_model = whisper_model

    def do_work(self):
        from config.paths import WHISPER_MODELS_DIR
        # mgr = VideoIndexManager()  # removed with material mgmt
        entry = mgr.get_by_id(self.video_id)
        if not entry:
            raise RuntimeError(f"未找到 video_id={self.video_id}")
        self.stage_log.emit(f"Whisper 转写：{os.path.basename(self.video_path)}")
        script = transcribe_audio(self.video_path, WHISPER_MODELS_DIR, self.whisper_model)
        entry["audio_script"] = script
        mgr.upsert(entry)
        self.stage_log.emit(f"转写完成，{len(script)} 字")
        self.finished.emit(entry)
