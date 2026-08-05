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


# ─── 灰片/Log 检测 ──────────────────────────────────────────────────

# Log 色彩空间的 transfer characteristics
_LOG_TRANSFERS = {
    "arib-std-b67",   # HLG（Sony 部分 S-Log 使用）
    "smpte2084",      # PQ（HDR / 部分 Log）
    "smpte428",       # D-Cinema
    "linear",         # 线性（ACES / 部分 Log）
    "log",            # 通用 Log
    "log100",
    "log100-sqrt10",
    "log316-sqrt10",
}

# 10-bit 像素格式（专业/Log 素材常见）
_10BIT_PIX_FMTS = {
    "yuv420p10le", "yuv422p10le", "yuv444p10le",
    "yuv420p10be", "yuv422p10be", "yuv444p10be",
    "gbrp10le", "gbrp10le",
}


def probe_color_metadata(video_path: str, ffprobe_path: str = "") -> dict:
    """用 ffprobe 提取视频的色彩元数据。

    Returns:
        {"color_transfer": str, "color_primaries": str, "color_space": str,
         "pix_fmt": str, "width": int, "height": int}
        失败返回空 dict。
    """
    import subprocess
    if not ffprobe_path:
        from utils.platform_utils import find_ffprobe
        ffprobe_path = find_ffprobe()
        if not ffprobe_path or not os.path.isfile(ffprobe_path):
            from utils.platform_utils import find_ffmpeg
            ff = find_ffmpeg()
            if ff:
                ffprobe_path = ff.replace("ffmpeg", "ffprobe")
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        return {}

    cmd = [
        ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=color_transfer,color_primaries,color_space,pix_fmt,width,height",
        "-of", "json", video_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           creationflags=0x08000000)
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout)
        streams = data.get("streams", [])
        return streams[0] if streams else {}
    except Exception:
        return {}


# 图片扩展名（用于 probe_media_size 走 PIL 分支）
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def probe_media_size(path):
    """读取单个媒体文件的像素尺寸 (width, height)。

    图片走 PIL.Image.open().size；视频走 ffprobe。
    失败返回 None。二进制路径解析与 probe_color_metadata 一致。
    """
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()

    # ── 图片：PIL ──
    if ext in _IMAGE_EXTS:
        try:
            from PIL import Image
            with Image.open(path) as im:
                w, h = im.size
            if w and h:
                return int(w), int(h)
        except Exception:
            return None
        return None

    # ── 视频：ffprobe（复用 probe_color_metadata 的二进制解析套路）──
    import subprocess
    from utils.platform_utils import find_ffprobe
    ffprobe_path = find_ffprobe()
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        from utils.platform_utils import find_ffmpeg
        ff = find_ffmpeg()
        if ff:
            ffprobe_path = ff.replace("ffmpeg", "ffprobe")
    if not ffprobe_path or not os.path.isfile(ffprobe_path):
        return None
    cmd = [
        ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           creationflags=0x08000000)
        if r.returncode != 0:
            return None
        streams = json.loads(r.stdout).get("streams") or []
        if not streams:
            return None
        w = int(streams[0].get("width") or 0)
        h = int(streams[0].get("height") or 0)
        if w and h:
            return w, h
    except Exception:
        return None
    return None


def classify_aspect(w, h):
    """按像素宽高分类画面比例，返回 "1:1" / "16:9" / "9:16"。

    阈值：16:9≈1.78、9:16≈0.56、1:1=1.0；
    0.08 容差覆盖常见拍摄抖动（4:3=1.33 判为 16:9，符合偏横屏直觉）。
    """
    if not w or not h:
        return "1:1"
    r = w / h
    if abs(r - 1.0) < 0.08:   # 方屏
        return "1:1"
    if r > 1.2:               # 横屏
        return "16:9"
    if r < 0.83:              # 竖屏
        return "9:16"
    return "1:1"              # 近似方形兜底


def detect_log_video(video_path: str, sample_frames: int = 5) -> dict:
    """检测视频是否为 Log/灰片，需要 LUT 还原。

    两路判断：
      1. ffprobe 色彩元数据：transfer 是否为 Log 类 / pix_fmt 是否为 10-bit
      2. 采样帧直方图：对比度是否偏低（灰片特征）

    Returns:
        {
            "is_log": bool,           # 是否为灰片
            "confidence": float,       # 置信度 0.0 ~ 1.0
            "reason": str,            # 判断理由
            "color_metadata": dict,   # ffprobe 原始色彩元数据
            "frame_stats": dict,      # 帧采样统计 {mean_brightness, contrast_std, ...}
        }
    """
    import cv2
    import numpy as np

    result = {
        "is_log": False,
        "confidence": 0.0,
        "reason": "",
        "color_metadata": {},
        "frame_stats": {},
    }

    # ── 1. 色彩元数据 ──
    meta = probe_color_metadata(video_path)
    result["color_metadata"] = meta

    transfer = (meta.get("color_transfer") or "").strip().lower()
    pix_fmt = (meta.get("pix_fmt") or "").strip().lower()
    color_space = (meta.get("color_space") or "").strip().lower()

    meta_score = 0.0
    reasons = []

    if transfer and transfer != "unknown":
        if transfer in _LOG_TRANSFERS:
            meta_score += 0.6
            reasons.append(f"色彩传输函数为 {transfer}（Log/HDR 类）")
        elif transfer == "bt709":
            meta_score -= 0.3  # 标准 Rec.709，很可能不是灰片

    if pix_fmt in _10BIT_PIX_FMTS:
        meta_score += 0.25
        reasons.append(f"10-bit 像素格式 {pix_fmt}（常见于 Log 素材）")

    if color_space and color_space != "bt709" and color_space != "unknown":
        if "bt2020" in color_space or "smpte" in color_space:
            meta_score += 0.15
            reasons.append(f"广色域 {color_space}")

    # ── 2. 采样帧直方图分析 ──
    try:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
        else:
            contrasts = []
            brightnesses = []
            # 在 5%~95% 区间均匀采样
            positions = [int(total_frames * p) for p in
                         [0.05, 0.25, 0.50, 0.75, 0.90][:sample_frames]]
            for pos in positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                if not ret:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                bright = float(np.mean(gray))
                contrast = float(np.std(gray))
                brightnesses.append(bright)
                contrasts.append(contrast)
            cap.release()

            if brightnesses and contrasts:
                avg_brightness = np.mean(brightnesses)
                avg_contrast = np.mean(contrasts)
                result["frame_stats"] = {
                    "mean_brightness": round(avg_brightness, 1),
                    "mean_contrast_std": round(avg_contrast, 1),
                }
                # 灰片特征：对比度偏低（像素集中在中间，标准差小）
                # 正常 Rec.709 视频对比度通常 > 50；灰片往往 < 40
                if avg_contrast < 35:
                    meta_score += 0.4
                    reasons.append(f"帧对比度偏低(std={avg_contrast:.0f})，典型灰片特征")
                elif avg_contrast < 50:
                    meta_score += 0.2
                    reasons.append(f"帧对比度中等(std={avg_contrast:.0f})，可能为灰片")
                else:
                    meta_score -= 0.1  # 高对比度，不像灰片
    except ImportError:
        pass  # cv2 不可用，跳过帧分析
    except Exception:
        pass

    meta_score = max(0.0, min(1.0, meta_score))
    result["confidence"] = round(meta_score, 2)
    result["is_log"] = meta_score >= 0.5
    result["reason"] = "；".join(reasons) if reasons else (
        "未检测到明显 Log 特征" if meta_score < 0.5 else "综合判断可能为灰片"
    )
    return result


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

def call_vision_for_tags(frames_b64: list[str]) -> list[str]:
    """
    把多帧 base64 图片一次发给视觉模型，提取画面语义标签列表。
    返回 ["键盘", "机械轴", "俯拍", "客制化"] 格式。
    """
    if not frames_b64:
        return []
    try:
        from utils.llm_proxy import llm_chat_messages
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
        raw = llm_chat_messages(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": content}],
            model=model, temperature=0.1, max_tokens=300, timeout=90)
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
            if frame_paths:
                frames_b64 = [frame_to_b64(p) for p in frame_paths[:6]]
                ai_tags = call_vision_for_tags(frames_b64)
                self._log(f"  标签: {ai_tags}")
            else:
                self._log("  视觉模型未配置，跳过标签提取")
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
