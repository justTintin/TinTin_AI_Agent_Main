# -*- coding: utf-8 -*-
"""
素材入库流水线（Chinese-CLIP 版）

NAS 瑙嗛/鍥剧墖 鈫 ffmpeg 鎶藉抚 鈫 Chinese-CLIP 512 缁村悜閲 鈫 PostgreSQL + pgvector

琛ㄧ粨鏋勶紙鍦ㄥ師 schema.sql 鍩虹涓婏紝materials 澧炲姞 file_hash 鍒椾綔涓哄敮涓閿锛:
  materials  鈥 姣忎釜婧愭枃浠朵竴琛岋紙file_hash UNIQUE锛宲ath 鍙闅忔枃浠剁Щ鍔ㄦ洿鏂帮級
  frames     鈥 姣忓抚涓琛岋紙embedding 512 缁达紝鏍囩惧瓧娈 brand/product/model/category锛

用法:
  from utils.material_clip_indexer import MaterialClipIndexer, search_by_text

  # 入库
  idx = MaterialClipIndexer(nas_root=r"\\192.168.111.17\素材")
  idx.index_directory(r"\\192.168.111.17\绱犳潗\榧犳爣閿鐩")

  # 妫绱
  results = search_by_text("罗技无线鼠标 白色", top_k=10)

鍛戒护琛:
  python -m utils.material_clip_indexer index "Z:\\绱犳潗\\榧犳爣閿鐩" --nas-root "Z:\\绱犳潗"
  python -m utils.material_clip_indexer search "罗技鼠标"

依赖:
  pip install psycopg2-binary pgvector transformers torch pillow
"""
from __future__ import annotations

import os
import re
import json
import time
import hashlib
import subprocess
import tempfile
import shutil
import logging
import threading
from pathlib import Path
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

import sys as _sys

_DRIVE_UNC_CACHE = {}


def to_relative_path(local_path: str, nas_root: str) -> str:
    """
    Convert a local filesystem path to a relative NAS path.
    Windows: resolves drive letters to UNC paths via mpr.dll.
    Linux:   strips nas_root prefix from local_path, or returns the full path.
    """
    if not local_path:
        return ""

    local_path = local_path.replace("\\", "/")
    unc_path = local_path

    if _sys.platform == "win32" and len(local_path) >= 2 and local_path[1] == ":":
        drive = local_path[:2].upper()
        if drive in _DRIVE_UNC_CACHE:
            unc_path = _DRIVE_UNC_CACHE[drive] + local_path[2:]
        else:
            try:
                mpr = ctypes.WinDLL("mpr.dll")
                buffer = ctypes.create_unicode_buffer(512)
                length = ctypes.c_ulong(512)
                res = mpr.WNetGetConnectionW(drive, buffer, ctypes.byref(length))
                if res == 0:
                    _DRIVE_UNC_CACHE[drive] = buffer.value
                    unc_path = buffer.value + local_path[2:]
            except Exception:
                pass

    unc_norm = unc_path.replace("\\", "/")
    nas_norm = nas_root.replace("\\", "/").rstrip("/")
    if nas_norm and unc_norm.lower().startswith(nas_norm.lower()):
        return unc_path[len(nas_norm):].replace("\\", "/").lstrip("/")
    # Linux: also strip /mnt/nas prefix
    if unc_norm.lower().startswith("/mnt/nas/"):
        return unc_norm[len("/mnt/nas/"):].lstrip("/")
    return unc_path.replace("\\", "/").lstrip("/")


def to_local_path(rel_path: str, nas_root: str) -> str:
    """
    Convert a relative NAS path back to a local filesystem path.
    Windows: resolves UNC paths to drive letters via mpr.dll.
    Linux:   replaces UNC/SMB prefix with local mount point.
    """
    if not rel_path:
        return ""

    rel_path = rel_path.replace("\\", "/")

    # Handle Windows drive letters / UNC paths on Linux
    if _sys.platform != "win32" and (rel_path.startswith("//") or (len(rel_path) >= 2 and rel_path[1] == ":")):
        # Strip known NAS host prefixes → /mnt/nas
        for prefix in ["//192.168.111.17", "//192.168.111.17/"]:
            if rel_path.lower().startswith(prefix.lower()):
                rel_path = "/mnt/nas/" + rel_path[len(prefix):].lstrip("/")
                break
        return os.path.abspath(rel_path)

    if (len(rel_path) >= 2 and rel_path[1] == ":"):
        return os.path.normpath(rel_path)

    unc_path = os.path.normpath(os.path.join(nas_root, rel_path.lstrip("/\\")))

    # Linux: convert UNC host prefix to /mnt/nas mount path
    if _sys.platform != "win32":
        unc_norm = unc_path.replace("\\", "/")
        for prefix in ["//192.168.111.17/", "//192.168.111.17"]:
            if unc_norm.startswith(prefix):
                unc_path = "/mnt/nas/" + unc_norm[len(prefix):].lstrip("/")
                break

    if _sys.platform == "win32":
        try:
            mpr = ctypes.WinDLL("mpr.dll")
            for drive_letter in [f"{chr(c)}:" for c in range(ord("A"), ord("Z") + 1)]:
                buffer = ctypes.create_unicode_buffer(512)
                length = ctypes.c_ulong(512)
                res = mpr.WNetGetConnectionW(drive_letter, buffer, ctypes.byref(length))
                if res == 0:
                    unc_drive = os.path.normpath(buffer.value)
                    if unc_path.lower().startswith(unc_drive.lower()):
                        return os.path.normpath(drive_letter + unc_path[len(unc_drive):])
        except Exception:
            pass

    return unc_path

# 鈹鈹 鍏ㄥ眬缂栫爜鍣ㄥ崟渚嬶紙閬垮厤姣忔℃悳绱㈤噸澶嶅姞杞芥ā鍨嬶級鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
_ENCODER_LOCK = threading.Lock()
_GLOBAL_ENCODER: Optional["_ClipEncoder"] = None


def get_encoder(cfg: Optional[dict] = None) -> "_ClipEncoder":
    """鑾峰彇鍏ㄥ眬 CLIP 缂栫爜鍣ㄥ崟渚嬶紙鎳掑姞杞斤紝绾跨▼瀹夊叏锛夈"""
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        if _GLOBAL_ENCODER is None:
            if cfg is None:
                cfg = _load_config()
            _GLOBAL_ENCODER = _ClipEncoder(
                cfg["clip_model"], cfg.get("clip_model_dir"),
                cfg.get("device", "auto"), cfg.get("batch_size", 8),
            )
    return _GLOBAL_ENCODER


def reset_encoder():
    """閲嶇疆鍏ㄥ眬缂栫爜鍣锛堟洿鎹㈡ā鍨嬭矾寰勫悗璋冪敤锛夈"""
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        _GLOBAL_ENCODER = None


def preload_encoder(cfg: Optional[dict] = None):
    """
    棰勫姞杞 CLIP 妯″瀷鍒板唴瀛橈紙鍦ㄥ悗鍙扮嚎绋嬭皟鐢锛岄伩鍏嶉樆濉 UI锛夈
    鍔犺浇鎴愬姛/澶辫触鍧囦笉鎶涘紓甯革紱璋冪敤 get_encoder_status() 鏌ヨ㈢粨鏋溿
    """
    try:
        enc = get_encoder(cfg)
        enc._load()
    except Exception as e:
        log.warning(f"CLIP 妯″瀷棰勫姞杞藉け璐: {e}")


def get_encoder_status() -> dict:
    """
    杩斿洖褰撳墠缂栫爜鍣ㄧ姸鎬佸瓧鍏:
      loaded  bool      鏄鍚﹀凡鎴愬姛鍔犺浇
      status  str       浜虹被鍙璇荤姸鎬佹弿杩
      backend str|None  "transformers" | "modelscope" | None
      error   str|None  澶辫触鍘熷洜锛堜粎 loaded=False 涓旀浘灏濊瘯杩囨椂鏈夊硷級
    """
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        enc = _GLOBAL_ENCODER
    if enc is None:
        return {"loaded": False, "status": "鏈鍒濆嬪寲", "backend": None, "error": None}
    if enc._backend is not None:
        return {
            "loaded":  True,
            "status":  f"宸插氨缁 ({enc._backend})",
            "backend": enc._backend,
            "error":   None,
        }
    if enc._load_error:
        return {
            "loaded":  False,
            "status":  "加载失败",
            "backend": None,
            "error":   enc._load_error,
        }
    return {"loaded": False, "status": "鏈鍔犺浇", "backend": None, "error": None}

# 鈹鈹 榛樿ら厤缃锛堝彲琚 config/material_index_config.json 瑕嗙洊锛夆攢鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
_DEFAULT_CFG = {
    "db_host":     "192.168.111.17",
    "db_port":     15432,
    "db_name":     "material_index",
    "db_user":     "postgres",
    "db_password": "postgres",

    # 鐩褰曞眰绾ф爣绛撅紙鐩稿 nas_root锛0 = 绗涓绾у瓙鐩褰曪級
    # 示例: \\NAS\素材\鼠标\罗技\G502\video.mp4
    #   depth 0 鈫 product="榧犳爣"  depth 1 鈫 brand="缃楁妧"  depth 2 鈫 model="G502"
    "tag_depth_product":  0,
    "tag_depth_brand":    1,
    "tag_depth_model":    2,
    "tag_depth_category": -1,   # -1 = 涓嶄粠璺寰勫彇 category

    # 鎶藉抚鐜囷紙姣忕掑抚鏁帮級
    "fps": 1,

    # Chinese-CLIP 妯″瀷锛圚uggingFace model ID锛屾垨 ViT-B-16 / ViT-L-14 / ViT-H-14 绠绉帮級
    "clip_model": "ViT-B-16",
    "clip_model_dir": None,     # None 鈫 鐢 HuggingFace 榛樿ょ紦瀛樼洰褰

    # 鎺ㄧ悊璁惧: "cuda" | "cpu" | "auto"
    "device": "auto",

    # 姣忔壒閫佸叆 CLIP 鐨勫浘鐗囨暟锛堟樉瀛樹笉瓒虫椂璋冨皬锛
    "batch_size": 8,

    # ffmpeg 鍙鎵ц屾枃浠惰矾寰勶紙None 鈫 浠 PATH 鎵撅級
    "ffmpeg_path": None,

    # 鏄鍚︿繚瀛樺抚缂╃暐鍥撅紙淇濆瓨鍒 thumb_dir锛屽惁鍒 thumb_path 瀛 NULL锛
    "save_thumbs": False,
    "thumb_dir": None,          # None 鈫 鐢ㄧ郴缁熶复鏃剁洰褰曚笅鐨勫浐瀹氬瓙鐩褰
}

_CFG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "material_index_config.json"
)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# 鍙拌瘝鍏抽敭璇嶅簱锛堣嗚堿I鏈璇嗗埆鏃剁殑鏂囧瓧鍏滃簳锛
_KNOWN_BRANDS = [
    "logitech", "缃楁妧", "razer", "闆疯泧", "corsair", "娴风洍鑸",
    "steelseries", "璧涚澘", "hyperx", "cherry", "妯辨", "roccat",
    "apple", "苹果", "samsung", "三星", "xiaomi", "小米",
    "huawei", "鍗庝负", "asus", "鍗庣", "msi", "寰鏄",
    "anker", "安克", "hp", "惠普", "dell", "戴尔",
]

_KNOWN_CATEGORIES = {
    "鼠标":   ["mouse", "鼠标"],
    "閿鐩":   ["keyboard", "閿鐩", "kbd", "鏈烘拌酱"],
    "手机":   ["phone", "手机", "mobile", "iphone", "安卓"],
    "耳机":   ["headset", "earphone", "耳机", "earbuds", "airpods"],
    "鏄剧ず鍣": ["monitor", "display", "鏄剧ず鍣"],
    "榧犳爣鍨": ["mousepad", "榧犳爣鍨", "desk mat"],
    "闊崇":   ["speaker", "闊崇", "鍠囧彮"],
}


# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
# 工具函数
# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

def _compute_hash(file_path: str) -> str:
    """
    蹇閫 SHA-256 鍐呭规寚绾癸紙棣 2MB + 灏 1MB + 鏂囦欢澶у皬锛夛紝杩斿洖 16 瀛楃 hex銆
    瀵瑰ぇ鏂囦欢閲囨牱鑰岄潪鍏ㄩ噺璇伙紝鍏奸【閫熷害涓庡敮涓鎬с
    """
    h = hashlib.sha256()
    try:
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            h.update(f.read(2 * 1024 * 1024))
            if size > 3 * 1024 * 1024:
                f.seek(-1024 * 1024, 2)
                h.update(f.read(1024 * 1024))
        h.update(size.to_bytes(8, "little"))
    except Exception as e:
        log.error(f"哈希计算失败 {file_path}: {e}")
        return ""
    return h.hexdigest()[:16]


def _load_config() -> dict:
    cfg = dict(_DEFAULT_CFG)
    if os.path.exists(_CFG_FILE):
        try:
            with open(_CFG_FILE, encoding="utf-8") as f:
                overrides = json.load(f)
            cfg.update({k: v for k, v in overrides.items() if not k.startswith("_")})
        except Exception as e:
            log.warning(f"鍔犺浇閰嶇疆鏂囦欢澶辫触锛屼娇鐢ㄩ粯璁ゅ: {e}")
    return cfg


def _get_video_meta(file_path: str, ffmpeg_path: Optional[str]) -> tuple[float, int, int]:
    """鐢 ffprobe 鑾峰彇 (鏃堕暱绉, 瀹, 楂)锛屽け璐ヨ繑鍥 (0, 0, 0)銆"""
    ffprobe = (ffmpeg_path or "ffmpeg").replace("ffmpeg", "ffprobe")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", file_path],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream.get("width", 0))
                h = int(stream.get("height", 0))
                dur_str = stream.get("duration") or data.get("format", {}).get("duration", "0")
                try:
                    dur = float(dur_str)
                except (ValueError, TypeError):
                    dur = 0.0
                return dur, w, h
    except Exception:
        pass
    return 0.0, 0, 0


def _get_image_meta(file_path: str) -> tuple[int, int]:
    """鑾峰彇鍥剧墖 (瀹, 楂)锛屽け璐ヨ繑鍥 (0, 0)銆"""
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            return img.width, img.height
    except Exception:
        return 0, 0


def _extract_frames_ffmpeg(
    file_path: str, out_dir: str, fps: float, ffmpeg_path: Optional[str]
) -> list[tuple[int, float, str]]:
    """
    鎸 fps 鎶藉抚鍒 out_dir锛岃繑鍥 [(frame_idx, timestamp_s, img_path), ...]銆
    缂╂斁鍒板藉害鏈澶 720px锛堜繚鎸佹瘮渚嬶級銆
    """
    ffmpeg_exe = ffmpeg_path or "ffmpeg"
    pattern = os.path.join(out_dir, "frame_%06d.jpg")
    cmd = [
        ffmpeg_exe, "-i", file_path,
        "-vf", f"fps={fps},scale='min(720,iw)':-2",
        "-q:v", "3", "-y", pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800, check=True)
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg 抽帧失败: {e.stderr.decode(errors='replace')[:300]}")
        return []
    except FileNotFoundError:
        log.error("ffmpeg 鏈鎵惧埌锛岃峰畨瑁 ffmpeg 鎴栧湪閰嶇疆涓鎸囧畾璺寰")
        return []

    result = []
    for fname in sorted(os.listdir(out_dir)):
        if not fname.endswith(".jpg"):
            continue
        try:
            idx = int(fname.replace("frame_", "").replace(".jpg", ""))
        except ValueError:
            continue
        ts = (idx - 1) / fps
        result.append((idx, round(ts, 3), os.path.join(out_dir, fname)))
    return result


def _parse_path_tags(
    file_path: str, nas_root: str,
    depth_product: int, depth_brand: int, depth_model: int, depth_category: int
) -> dict[str, str]:
    """
    浠庢枃浠惰矾寰勭殑鐩褰曞眰绾цВ鏋愭爣绛撅紝杩斿洖 {brand, product, model, category}銆
    depth=-1 琛ㄧず涓嶅彇璇ュ瓧娈点
    """
    try:
        rel = Path(file_path).relative_to(Path(nas_root))
        parts = list(rel.parts[:-1])
    except (ValueError, TypeError):
        parts = list(Path(file_path).parts[:-1])

    def _get(depth: int) -> Optional[str]:
        if depth < 0 or depth >= len(parts):
            return None
        return parts[depth].strip("銆愩慬]銆屻").strip() or None

    return {
        "brand":    _get(depth_brand),
        "product":  _get(depth_product),
        "model":    _get(depth_model),
        "category": _get(depth_category),
    }


def _call_vision_for_product(
    img_paths: list[str], api_url: str, api_key: str, model: str,
    max_frames: int = 6,
    log_cb=None,
    ocr_text: str = "",
    concurrency: int = 4,
) -> dict:
    """
    对已抽取的帧文件调用视觉 LLM 识别品牌/品类/型号/主要画面描述/次要画面描述，多帧投票取最高频非-unknown 值。
    """
    if not (api_url and model and img_paths):
        return {}

    try:
        import base64 as _b64
        import requests as _req
    except ImportError:
        return {}

    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(img_paths)
    step = max(1, total // max_frames)
    sampled = img_paths[::step][:max_frames]

    system_prompt = (
        "你是专业的消费电子产品视觉识别专家。\n"
        "通过产品外观特征（形状/轮廓/设计语言/LOGO/文字标识）推断品牌、品类和型号，并用中文对画面内容进行核心视觉描述。\n"
        "只返回 JSON，不要任何其他内容，格式如下：\n"
        "{\n"
        "  \"brand\": \"品牌名，无法识别填 unknown\",\n"
        "  \"category\": \"品类（鼠标/键盘/耳机/显示器等），无法识别填 unknown\",\n"
        "  \"model\": \"型号，无法识别填 unknown\",\n"
        "  \"scene_desc_primary\": \"主要画面描述（中文，15字以内，描述画面中的最核心的主体、动作或特写内容，例如：白色鼠标放置在黑布上）\",\n"
        "  \"scene_desc_secondary\": \"次要画面描述（中文，20字以内，描述背景环境、光源、或辅助道具，例如：黑色背景，左侧有微弱暖光）\"\n"
        "}\n"
    )
    url = f"{api_url.rstrip('/')}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    brand_cnt: Counter = Counter()
    cat_cnt:   Counter = Counter()
    model_cnt: Counter = Counter()
    primary_list = []
    secondary_list = []

    def _clean(v) -> str:
        v = str(v or "").strip()
        return v if v and v.lower() not in ("unknown", "none", "") else "unknown"

    def _clean_desc(v) -> str:
        v = str(v or "").strip()
        if v.lower() in ("unknown", "none", "", "null", "未识别", "无法识别"):
            return ""
        return v

    def _query_frame(i, img_path):
        try:
            from PIL import Image
            import io
            with Image.open(img_path) as img:
                img.thumbnail((768, 768))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                img_bytes = buf.getvalue()
            b64 = _b64.b64encode(img_bytes).decode()
            user_text = f"这是视频第 {i+1}/{len(sampled)} 帧，识别产品 brand/category/model 及画面描述："
            if ocr_text:
                user_text += f"\n提示：该图片包含以下 OCR 识别到的文字内容（可用于辅助识别产品品牌、型号或做画面内容描述参考）:\n{ocr_text}"
            payload = {
                "model": model,
                "num_ctx": 32768,  # Ollama: override default 4096 context
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ]},
                ],
                "temperature": 0.1,
                "max_tokens": 150,
            }
            res = _req.post(url, json=payload, headers=headers, timeout=60)
            if res.status_code != 200:
                msg = f"视觉AI帧{i+1} HTTP {res.status_code}: {res.text[:200]}"
                if log_cb:
                    log_cb(f"     ⚠ {msg}")
                return None
            raw = res.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\s*```$",           "", raw, flags=re.MULTILINE).strip()
            m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
            return json.loads(raw)
        except Exception as e:
            msg = f"视觉AI帧{i+1}失败: {e}"
            if log_cb:
                log_cb(f"     ⚠ {msg}")
            return None

    results = [None] * len(sampled)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_query_frame, i, img_path): i for i, img_path in enumerate(sampled)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                data = future.result()
                if data:
                    results[i] = data
            except Exception as e:
                if log_cb:
                    log_cb(f"     ⚠ 视觉AI第 {i+1} 帧并发请求异常: {e}")

    for i, data in enumerate(results):
        if not data:
            continue
        try:
            brand_cnt[_clean(data.get("brand",    "unknown"))] += 1
            cat_cnt  [_clean(data.get("category", "unknown"))] += 1
            model_cnt[_clean(data.get("model",    "unknown"))] += 1
            
            p_desc = data.get("scene_desc_primary") or data.get("scene_description_primary", "")
            s_desc = data.get("scene_desc_secondary") or data.get("scene_description_secondary", "")
            p_desc = _clean_desc(p_desc)
            s_desc = _clean_desc(s_desc)
            if p_desc:
                primary_list.append(p_desc)
            if s_desc:
                secondary_list.append(s_desc)
        except Exception as e:
            if log_cb:
                log_cb(f"     ⚠ 视觉AI第 {i+1} 帧数据解析失败: {e}")

    def _top(cnt: Counter) -> Optional[str]:
        without_unk = {k: v for k, v in cnt.items() if k.lower() != "unknown"}
        return max(without_unk, key=without_unk.get) if without_unk else None

    result: dict = {}
    b = _top(brand_cnt)
    c = _top(cat_cnt)
    m_val = _top(model_cnt)
    if b:     result["brand"]   = b
    if c:     result["product"] = c
    if m_val: result["model"]   = m_val

    # Deduplicate descriptions while preserving order
    unique_p = []
    for p in primary_list:
        if p not in unique_p:
            unique_p.append(p)
    unique_s = []
    for s in secondary_list:
        if s not in unique_s:
            unique_s.append(s)

    result["scene_desc_primary"] = "；".join(unique_p) if unique_p else None
    result["scene_desc_secondary"] = "；".join(unique_s) if unique_s else None

    n = len(sampled)
    if n > 0 and (b or m_val):
        hits = (brand_cnt.get(b, 0) if b else 0) + (model_cnt.get(m_val, 0) if m_val else 0)
        slots = n * ((1 if b else 0) + (1 if m_val else 0))
        result["ai_confidence"] = round(hits / slots, 2) if slots else 0.0

    return result

def _extract_from_script(text: str) -> tuple:
    """
    浠 Whisper 鍙拌瘝鏂囨湰涓鐢ㄥ叧閿璇嶅尮閰嶆彁鍙栧搧鐗/鍝佺被/鍨嬪彿銆
    瑙嗚堿I鏈璇嗗埆鏃朵綔涓鸿ˉ鍏呭厹搴曪紝杩斿洖 (brand, product, model)锛屾湭璇嗗埆涓 None銆
    """
    if not text:
        return None, None, None
    lower = text.lower()
    brand   = next((b for b in _KNOWN_BRANDS if b.lower() in lower), None)
    product = None
    for cat, keywords in _KNOWN_CATEGORIES.items():
        if any(kw.lower() in lower for kw in keywords):
            product = cat
            break
    # 鍨嬪彿锛氬ぇ鍐欏瓧姣+鏁板瓧缁勫悎锛屽 G502 / MX3 / MH751
    m = re.search(r'\b([A-Z]{1,4}\s?\d{2,5}[A-Za-z0-9]?)\b', text)
    model = m.group(1).replace(" ", "") if m else None
    return brand, product, model


# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
# Chinese-CLIP 鎺ㄧ悊锛堟噿鍔犺浇锛屼娇鐢 transformers.ChineseCLIPModel锛
# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

# 绠绉 鈫 HuggingFace model ID
_HF_MODEL_MAP = {
    "ViT-B-16": "OFA-Sys/chinese-clip-vit-base-patch16",
    "ViT-L-14": "OFA-Sys/chinese-clip-vit-large-patch14",
    "ViT-H-14": "OFA-Sys/chinese-clip-vit-huge-patch14",
}

# 绠绉 鈫 ModelScope model ID锛堝浗鍐呭彲鐩存帴涓嬭浇锛
_MS_MODEL_MAP = {
    "ViT-B-16": ("damo/multi-modal_clip-vit-base-patch16_zh", "v1.0.1"),
    "ViT-L-14": ("damo/multi-modal_clip-vit-large-patch14_zh", "v1.0.0"),
    "ViT-H-14": ("damo/multi-modal_clip-vit-huge-patch14_zh", "v1.0.0"),
}

# ViT-B-16=512, ViT-L-14=768, ViT-H-14=1024
_EMBED_DIM_MAP = {
    "ViT-B-16": 512,
    "ViT-L-14": 768,
    "ViT-H-14": 1024,
}


class _ClipEncoder:
    """
    Chinese-CLIP 鎺ㄧ悊灏佽咃紝鏀鎸佷袱濂楀悗绔锛
    - transformers锛氭湰鍦 HuggingFace 鏍煎紡鐩褰 / hf-mirror.com 涓嬭浇
    - modelscope锛氶氳繃 ModelScope pipeline锛堝浗鍐呭彲闈狅紝鑷鍔ㄤ笅杞斤級
    """
    def __init__(self, model_name: str, model_dir: Optional[str], device: str, batch_size: int):
        self.model_name = model_name
        self.model_dir = model_dir
        self.batch_size = batch_size
        self._torch = None
        self._device = None
        self._requested_device = device
        self._load_error: Optional[str] = None   # fail-fast
        self._hf_id = _HF_MODEL_MAP.get(model_name, model_name)
        self._ms_id, self._ms_rev = _MS_MODEL_MAP.get(model_name, ("", ""))
        self._embed_dim = _EMBED_DIM_MAP.get(model_name, 512)

        # 鍚庣鍖哄垎锛歵ransformers锛圚F 鏍煎紡锛夋垨 modelscope pipeline
        self._backend: Optional[str] = None   # "transformers" | "modelscope"
        self._hf_model = None
        self._hf_processor = None
        self._ms_pipeline = None
        self._ms_missing: bool = False  # modelscope 鏈瀹夎呮椂鏍囪

    # 鈹鈹 鍔犺浇锛堟噿鍔犺浇 + fail-fast锛夆攢鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

    def _load(self):
        if self._backend is not None:
            return
        if self._load_error:
            raise RuntimeError(self._load_error)

        try:
            import torch
        except ImportError as e:
            self._load_error = f"缺少 torch: {e}"
            raise RuntimeError(self._load_error) from e

        self._torch = torch
        device = ("cuda" if torch.cuda.is_available() else "cpu") \
            if self._requested_device == "auto" else self._requested_device
        self._device = device

        local_is_ms_format = (
            self.model_dir
            and os.path.isdir(self.model_dir)
            and os.path.isfile(os.path.join(self.model_dir, "configuration.json"))
            and not os.path.isfile(os.path.join(self.model_dir, "config.json"))
        )

        # 鈶 鏈鍦 HuggingFace 鏍煎紡鐩褰曪紙鏈蹇锛屼笉闇瑕佺綉缁滐級
        if self.model_dir and os.path.isdir(self.model_dir) and not local_is_ms_format:
            if self._try_load_hf(self.model_dir, device):
                return

        # 鈶 ModelScope 鏍煎紡锛堟湰鍦板凡涓嬭浇 鎴 鍦ㄧ嚎涓嬭浇锛夆斺 modelscope 鏄鍞涓鍚庣
        if local_is_ms_format or self._ms_id:
            if self._try_load_modelscope(device):
                return
            # modelscope 鏈瀹夎 鈫 鐩存帴缁欏嚭娓呮櫚鎻愮ず锛屼笉灏濊瘯鍏朵粬閫斿緞
            if self._ms_missing:
                self._load_error = (
                    "鈿狅笍 妯″瀷涓 ModelScope 鏍煎紡锛岄渶瑕 modelscope 鍖呫俓n\n"
                    "璇峰湪銆岀幆澧冮厤缃銆嶁啋銆屽悜閲忓簱銆嶇偣銆岎煍 鍔犺浇/棰勭儹妯″瀷銆嶏紝\n"
                    "绋嬪簭浼氳嚜鍔ㄤ粠鏈鍦板畨瑁 modelscope 骞跺姞杞芥ā鍨嬨"
                )
                raise RuntimeError(self._load_error)

        # 鈶 妯″瀷鐩褰曚笉瀛樺湪 / 鏈涓嬭浇
        if self.model_dir and not os.path.isdir(self.model_dir):
            self._load_error = (
                f"模型目录不存在: {self.model_dir}\n\n"
                "请在「环境配置」→「向量库」点「⬇ 一键下载模型」。"
            )
            raise RuntimeError(self._load_error)

        self._load_error = (
            "⚠️ 无法加载 Chinese-CLIP 模型。\n\n"
            "璇峰湪銆岀幆澧冮厤缃銆嶁啋銆屽悜閲忓簱銆嶇偣銆屸瑖 涓閿涓嬭浇妯″瀷銆嶄笅杞芥ā鍨嬶紝\n"
            "鍐嶇偣銆岎煍 鍔犺浇/棰勭儹妯″瀷銆嶅姞杞姐"
        )
        raise RuntimeError(self._load_error)

    def model_id_or_path(self, hf_kw: dict) -> str:
        return self.model_dir if (self.model_dir and not hf_kw) else self._hf_id

    def _try_load_hf(self, model_path: str, device: str, **kw) -> bool:
        try:
            from transformers import ChineseCLIPModel, ChineseCLIPProcessor
            log.info(f"尝试 transformers 加载: {model_path}")
            m = ChineseCLIPModel.from_pretrained(model_path, **kw).to(device).eval()
            p = ChineseCLIPProcessor.from_pretrained(model_path, **kw)
            self._hf_model = m
            self._hf_processor = p
            self._backend = "transformers"
            log.info("Chinese-CLIP (transformers) 加载完成")
            return True
        except ValueError as e:
            # transformers 鏂扮増鏈瀵 torch.load 鐨 CVE-2025-32434 瀹夊叏妫鏌ワ細
            # 鏈鍦板彲淇℃ā鍨嬫枃浠讹紝缁曡繃璇ラ檺鍒舵墜鍔ㄥ姞杞芥潈閲嶃
            if "CVE-2025-32434" in str(e) or "torch.load" in str(e):
                try:
                    import torch
                    from transformers import ChineseCLIPModel, ChineseCLIPProcessor
                    from transformers import AutoConfig
                    import os as _os
                    log.info(f"缁曡繃 transformers torch 鐗堟湰妫鏌ワ紝鎵嬪姩鍔犺浇鏈鍦版潈閲: {model_path}")
                    cfg = AutoConfig.from_pretrained(model_path, local_files_only=True)
                    m = ChineseCLIPModel(cfg)
                    # 找到 .bin 文件
                    bin_files = [f for f in _os.listdir(model_path)
                                 if f.endswith(".bin") or f.endswith(".pt")]
                    if not bin_files:
                        raise FileNotFoundError(f"鏈鎵惧埌 .bin 妯″瀷鏂囦欢: {model_path}")
                    state_raw = torch.load(
                        _os.path.join(model_path, bin_files[0]),
                        map_location="cpu", weights_only=False,
                    )
                    # 瑙ｅ寘宓屽
                    if isinstance(state_raw, dict) and "state_dict" in state_raw:
                        sd = state_raw["state_dict"]
                    elif isinstance(state_raw, dict) and "model" in state_raw:
                        sd = state_raw["model"]
                    else:
                        sd = state_raw
                    # 濡傛灉 key 鍖呭惈 'module.' 鍓嶇紑锛圖DP 璁缁冿級锛屽幓鎺
                    if all(k.startswith("module.") for k in list(sd.keys())[:5]):
                        sd = {k[len("module."):]: v for k, v in sd.items()}
                    missing, unexpected = m.load_state_dict(sd, strict=False)
                    log.info(f"手动加载: missing={len(missing)} unexpected={len(unexpected)}")
                    m = m.to(device).eval()
                    p = ChineseCLIPProcessor.from_pretrained(model_path, local_files_only=True)
                    self._hf_model = m
                    self._hf_processor = p
                    self._backend = "transformers"
                    log.info("Chinese-CLIP (手动加载权重) 加载完成")
                    return True
                except Exception as e2:
                    log.warning(f"transformers 手动加载权重失败 ({model_path}): {e2}")
                    return False
            log.warning(f"transformers 加载失败 ({model_path}): {e}")
            return False
        except Exception as e:
            log.warning(f"transformers 加载失败 ({model_path}): {e}")
            return False

    def _try_load_modelscope(self, device: str) -> bool:
        """
        鐩存帴鍔犺浇 ModelScope 鏍煎紡鐨 Chinese-CLIP 妯″瀷锛
        涓嶉氳繃 pipeline API锛堥伩鍏嶆媺璧 OFA/fairseq 渚濊禆棰楅棶棰橈級銆
        """
        local_dir = self.model_dir

        # 鈹鈹 妫鏌 modelscope 鍖呮槸鍚﹀畨瑁 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
        try:
            import modelscope  # noqa: F401
        except ImportError:
            log.warning("modelscope 鏈瀹夎咃紝璺宠繃 ModelScope 鍚庣銆傝疯繍琛: pip install modelscope")
            self._ms_missing = True
            return False

        # 鈹鈹 灏濊瘯鏂瑰紡 1锛氱洿鎺ョ敤 transformers 鍔犺浇 ModelScope 鏈鍦扮洰褰曪紙鍐呭圭浉鍚岋級 鈹鈹鈹鈹鈹鈹鈹鈹鈹
        if local_dir and os.path.isdir(local_dir):
            try:
                from transformers import ChineseCLIPModel, ChineseCLIPProcessor
                log.info(f"灏濊瘯鐢 transformers 鐩存帴鍔犺浇 ModelScope 鐩褰: {local_dir}")
                m = ChineseCLIPModel.from_pretrained(local_dir, local_files_only=True)
                m = m.to(device).eval()
                p = ChineseCLIPProcessor.from_pretrained(local_dir, local_files_only=True)
                self._hf_model = m
                self._hf_processor = p
                self._backend = "transformers"   # 澶嶇敤 transformers 缂栫爜璺寰
                log.info("Chinese-CLIP 閫氳繃 transformers 鐩村姞 ModelScope 鐩褰曞畬鎴")
                return True
            except Exception as e:
                log.info(f"transformers 鐩磋 ModelScope 鐩褰曞け璐 ({e})锛屽皾璇 modelscope pipeline鈥")

        # 鈹鈹 灏濊瘯鏂瑰紡 2锛 鐢 modelscope pipeline 锛堥渶瑕佸畬鏁翠緷璧栵級 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
        try:
            from modelscope.pipelines import pipeline as ms_pipeline
            from modelscope.utils.constant import Tasks
        except ImportError as ie:
            log.warning(f"modelscope.pipelines 导入失败: {ie}")
            return False

        try:
            if local_dir and os.path.isdir(local_dir) and os.path.isfile(
                os.path.join(local_dir, "configuration.json")
            ):
                log.info(f"姝ｅ湪浠庢湰鍦扮洰褰曞姞杞 ModelScope 妯″瀷: {local_dir}")
                model_src = local_dir
                kw: dict = {}
            else:
                log.info(f"姝ｅ湪閫氳繃 ModelScope 涓嬭浇 {self._ms_id} (revision={self._ms_rev})鈥")
                model_src = self._ms_id
                kw = {"model_revision": self._ms_rev}

            pl = ms_pipeline(
                Tasks.multi_modal_embedding,
                model=model_src,
                device="gpu" if "cuda" in device else "cpu",
                **kw,
            )
            self._ms_pipeline = pl
            self._backend = "modelscope"
            log.info("Chinese-CLIP (ModelScope pipeline) 加载完成")
            return True
        except Exception as e:
            log.warning(f"ModelScope pipeline 加载失败: {e}")
            return False

    # 鈹鈹 缂栫爜鎺ュ彛 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

    def encode_images(self, img_paths: list[str]) -> list[list[float]]:
        self._load()
        zero = [0.0] * self._embed_dim
        all_embs: list[list[float]] = []

        if self._backend == "modelscope":
            from PIL import Image
            for p in img_paths:
                try:
                    img = Image.open(p).convert("RGB")
                    out = self._ms_pipeline({"img": img})
                    emb = out["img_embedding"]  # numpy (1, dim)
                    import numpy as np
                    e = emb[0].astype("float32")
                    n = float(np.linalg.norm(e))
                    all_embs.append((e / n if n > 0 else e).tolist())
                except Exception as ex:
                    log.warning(f"图片编码失败 {p}: {ex}")
                    all_embs.append(list(zero))
            return all_embs

        # transformers 鍚庣
        from PIL import Image
        torch = self._torch
        for i in range(0, len(img_paths), self.batch_size):
            batch = img_paths[i: i + self.batch_size]
            pil_imgs, valid_idx = [], []
            for j, p in enumerate(batch):
                try:
                    pil_imgs.append(Image.open(p).convert("RGB"))
                    valid_idx.append(j)
                except Exception as ex:
                    log.warning(f"图片读取失败 {p}: {ex}")
            result = [list(zero) for _ in batch]
            if pil_imgs:
                inputs = self._hf_processor(images=pil_imgs, return_tensors="pt")
                inputs = {k: v.to(self._device) for k, v in inputs.items()}
                with torch.no_grad():
                    emb = self._hf_model.get_image_features(**inputs)
                    if hasattr(emb, "pooler_output"):
                        emb = emb.pooler_output
                    emb = emb / emb.norm(p=2, dim=-1, keepdim=True)
                    emb_np = emb.cpu().float().numpy()
                for k, vi in enumerate(valid_idx):
                    result[vi] = emb_np[k].tolist()
            all_embs.extend(result)
        return all_embs

    def encode_text(self, texts: list[str]) -> list[list[float]]:
        self._load()

        if self._backend == "modelscope":
            import numpy as np
            all_embs = []
            for t in texts:
                try:
                    out = self._ms_pipeline({"text": t})
                    emb = out["text_embedding"][0].astype("float32")
                    n = float(np.linalg.norm(emb))
                    all_embs.append((emb / n if n > 0 else emb).tolist())
                except Exception as ex:
                    log.warning(f"文本编码失败 '{t}': {ex}")
                    all_embs.append([0.0] * self._embed_dim)
            return all_embs

        # transformers 鍚庣
        torch = self._torch
        inputs = self._hf_processor(
            text=texts, return_tensors="pt", padding=True, truncation=True
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            emb = self._hf_model.get_text_features(**inputs)
            if hasattr(emb, "pooler_output"):
                emb = emb.pooler_output
            emb = emb / emb.norm(p=2, dim=-1, keepdim=True)
        return emb.cpu().float().numpy().tolist()


# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
# 鏁版嵁搴撳眰锛堜弗鏍煎瑰簲鐪熷疄 schema锛
# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

class _MaterialDB:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._conn = None
        self._schema_ensured = False

    def _connect(self):
        if self._conn is not None:
            try:
                self._conn.cursor().execute("SELECT 1")
                return
            except Exception:
                self._conn = None
                self._schema_ensured = False
        try:
            import psycopg2
            from pgvector.psycopg2 import register_vector
        except ImportError as e:
            raise RuntimeError(
                f"缺少依赖: {e}\n请安装: pip install psycopg2-binary pgvector"
            ) from e
        c = self._cfg
        self._conn = psycopg2.connect(
            host=c["db_host"], port=c["db_port"],
            dbname=c["db_name"], user=c["db_user"], password=c["db_password"],
            connect_timeout=10,
        )
        # register_vector 闇瑕佸湪浜嬪姟澶栬皟鐢锛屽繀椤诲厛鎵撳紑 autocommit
        self._conn.autocommit = True
        register_vector(self._conn)
        self._conn.autocommit = False
        if not self._schema_ensured:
            self._ensure_schema()
            self._schema_ensured = True

    def _ensure_schema(self):
        """鍚戞棫鏁版嵁搴撴坊鍔 AI 鍒嗘瀽缁撴灉鍒楋紙骞傜瓑锛屼娇鐢 IF NOT EXISTS锛夈"""
        try:
            with self._conn.cursor() as cur:
                for col, coltype in [
                    ("brand",         "TEXT"),
                    ("product",       "TEXT"),
                    ("model",         "TEXT"),
                    ("category",      "TEXT"),
                    ("ai_status",     "TEXT DEFAULT 'pending'"),
                    ("audio_script",  "TEXT"),
                    ("ai_confidence", "REAL"),
                    ("scene_desc_primary", "TEXT"),
                    ("scene_desc_secondary", "TEXT"),
                ]:
                    cur.execute(
                        f"ALTER TABLE materials ADD COLUMN IF NOT EXISTS {col} {coltype}"
                    )
                # 迁移老数据：把反斜杠统一替换为正斜杠，以确保 Windows 和 Linux 兼容及路径前缀匹配生效
                cur.execute(
                    "UPDATE materials SET path = REPLACE(path, %s, %s) WHERE path LIKE %s",
                    ("\\", "/", "%\\\\%")
                )
                # 把老盘符路径也迁移成相对路径以保持统一
                cur.execute(
                    "UPDATE materials SET path = REPLACE(path, %s, %s) WHERE path LIKE %s",
                    ("R:/", "鼠标键盘/", "R:/%")
                )
                cur.execute(
                    "UPDATE materials SET path = REPLACE(path, %s, %s) WHERE path LIKE %s",
                    ("T:/", "公共素材/", "T:/%")
                )
                cur.execute(
                    "UPDATE materials SET path = REPLACE(path, %s, %s) WHERE path LIKE %s",
                    ("W:/", "鼠标键盘/", "W:/%")
                )
            self._conn.commit()
        except Exception as e:
            log.warning(f"schema 迁移跳过: {e}")
            try:
                self._conn.rollback()
            except Exception:
                pass

    def update_material_ai(self, material_id: int, *,
                            brand=None, product=None, model=None, category=None,
                            audio_script=None, ai_status: str = "analyzed",
                            ai_confidence=None, scene_desc_primary=None,
                            scene_desc_secondary=None) -> None:
        """鏇存柊绱犳潗鐨 AI 鍒嗘瀽缁撴灉锛堝搧鐗/鍨嬪彿/鍙拌瘝/鐘舵/缃淇″害/鐢婚潰鎻忚堪锛夈"""
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE materials
                   SET brand=%s, product=%s, model=%s, category=%s,
                       audio_script=%s, ai_status=%s, ai_confidence=%s,
                       scene_desc_primary=%s, scene_desc_secondary=%s
                 WHERE id=%s
            """, (brand, product, model, category, audio_script, ai_status, ai_confidence,
                  scene_desc_primary, scene_desc_secondary, material_id))
        self._conn.commit()

    def search_by_tags(self, brand: str = None, model: str = None,
                       category: str = None, ai_status: str = None,
                       limit: int = 10000, hash_prefix: str = "") -> list:
        """鎸夊搧鐗/鍨嬪彿/绫诲埆鏍囩炬ā绯婃煡璇㈢礌鏉愶紝浠讳綍瀛楁电暀绌哄垯涓嶇瓫閫夎ュ瓧娈点"""
        self._connect()
        conds: list = []
        params: list = []
        if brand:
            conds.append("brand ILIKE %s")
            params.append(f"%{brand}%")
        if model:
            conds.append("(model ILIKE %s OR product ILIKE %s)")
            params.extend([f"%{model}%", f"%{model}%"])
        if category:
            conds.append("(category ILIKE %s OR product ILIKE %s)")
            params.extend([f"%{category}%", f"%{category}%"])
        if ai_status:
            conds.append("COALESCE(ai_status,'pending') = %s")
            params.append(ai_status)
        if hash_prefix:
            conds.append("file_hash ILIKE %s")
            params.append(hash_prefix.strip() + "%")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, path, filename, media_type, duration_s,
                       brand, product, model, category,
                       COALESCE(ai_status,'pending') AS ai_status,
                       ai_confidence, file_hash, scene_desc_primary, scene_desc_secondary
                FROM materials
                {where}
                ORDER BY id DESC
                LIMIT %s
            """, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        self._conn.commit()
        return rows

    def upsert_material(self, file_hash: str, path: str, media_type: str, filename: str,
                        duration_s: Optional[float], width: int, height: int,
                        file_size: Optional[int] = None, mtime: Optional[float] = None) -> int:
        """
        鎸 file_hash 鎻掑叆鎴栨洿鏂 materials锛岃繑鍥 id銆
        鏂囦欢绉诲姩鏃 path 浼氳鏇存柊锛屽叾浠栧厓鏁版嵁涔防殢涔嬪埛鏂般
        """
        path = to_relative_path(path, self._cfg.get("nas_root", ""))
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute("""
                INSERT INTO materials
                    (file_hash, path, media_type, filename, duration_s, width, height, file_size, mtime)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_hash) DO UPDATE SET
                    path       = EXCLUDED.path,
                    media_type = EXCLUDED.media_type,
                    filename   = EXCLUDED.filename,
                    duration_s = EXCLUDED.duration_s,
                    width      = EXCLUDED.width,
                    height     = EXCLUDED.height,
                    file_size  = COALESCE(EXCLUDED.file_size, materials.file_size),
                    mtime      = COALESCE(EXCLUDED.mtime, materials.mtime)
                RETURNING id
            """, (file_hash, path, media_type, filename, duration_s, width, height, file_size, mtime))
            material_id = cur.fetchone()[0]
        self._conn.commit()
        return material_id

    def delete_material_by_path(self, path: str) -> None:
        """从数据库中完全删除指定路径的素材及其对应的所有视频帧记录。"""
        path = to_relative_path(path, self._cfg.get("nas_root", ""))
        self._connect()
        with self._conn.cursor() as cur:
            # 级联删除 frames 记录
            cur.execute("DELETE FROM frames WHERE material_id IN (SELECT id FROM materials WHERE path = %s)", (path,))
            cur.execute("DELETE FROM materials WHERE path = %s", (path,))
        self._conn.commit()

    def list_materials(self, path_prefix: str = "", limit: int = 10000,
                       offset: int = 0, ai_status: Optional[str] = None,
                       hash_prefix: str = "", media_type: Optional[str] = None,
                       brand: str = "", scene_desc: str = "",
                       conf_filter: str = "", product: str = "") -> list:
        self._connect()
        conds = []
        params = []
        if path_prefix:
            normalized_prefix = to_relative_path(path_prefix, self._cfg.get("nas_root", ""))
            conds.append("path LIKE %s")
            params.append(normalized_prefix + "%")
        if ai_status:
            conds.append("COALESCE(ai_status,'pending') = %s")
            params.append(ai_status)
        if hash_prefix:
            h_val = hash_prefix.strip()
            if h_val in ("—", "null", "无", "empty", "NULL"):
                conds.append("(file_hash IS NULL OR file_hash = '' OR file_hash = '—')")
            else:
                conds.append("file_hash ILIKE %s")
                params.append(h_val + "%")
        if media_type:
            conds.append("media_type = %s")
            params.append(media_type)
        if brand:
            brand_val = brand.strip()
            if brand_val in ("—", "null", "无", "empty", "NULL"):
                conds.append("(brand IS NULL OR brand = '' OR brand = '—')")
            else:
                conds.append("brand ILIKE %s")
                params.append(f"%{brand_val}%")
        if product:
            prod_val = product.strip()
            if prod_val in ("—", "null", "无", "empty", "NULL"):
                conds.append("(product IS NULL OR product = '' OR product = '—')")
            else:
                conds.append("product ILIKE %s")
                params.append(f"%{prod_val}%")
        if scene_desc:
            desc_val = scene_desc.strip()
            if desc_val in ("—", "null", "无", "empty", "NULL"):
                conds.append("(scene_desc_primary IS NULL OR scene_desc_primary = '' OR scene_desc_primary = '—' OR scene_desc_secondary IS NULL OR scene_desc_secondary = '' OR scene_desc_secondary = '—')")
            else:
                conds.append("(scene_desc_primary ILIKE %s OR scene_desc_secondary ILIKE %s)")
                params.extend([f"%{desc_val}%", f"%{desc_val}%"])
        if conf_filter == "high":
            conds.append("ai_confidence >= 0.7")
        elif conf_filter == "medium":
            conds.append("ai_confidence >= 0.4 AND ai_confidence < 0.7")
        elif conf_filter == "low":
            conds.append("(ai_confidence < 0.4 OR ai_confidence IS NULL)")
        
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params += [limit, offset]
        with self._conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, path, filename, media_type, duration_s,
                       brand, product, model, category,
                       COALESCE(ai_status,'pending') AS ai_status,
                       ai_confidence, file_hash, file_size,
                       scene_desc_primary, scene_desc_secondary
                FROM materials
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
            """, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        self._conn.commit()
        return rows

    def get_stats(self) -> dict:
        """返回 {total, pending, analyzed, failed}"""
        self._connect()
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM materials")
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT COALESCE(ai_status,'pending'), COUNT(*) "
                    "FROM materials GROUP BY 1"
                )
                by_status = {row[0]: row[1] for row in cur.fetchall()}
            self._conn.commit()
            return {
                "total":    total,
                "pending":  by_status.get("pending", 0),
                "analyzed": by_status.get("analyzed", 0),
                "failed":   by_status.get("failed", 0),
            }
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
            return {"total": 0, "pending": 0, "analyzed": 0, "failed": 0}

    def get_pending_materials(self, path_prefix: str = "", limit: int = 10000) -> list:
        """杩斿洖 ai_status='pending'锛堟垨涓 NULL锛夌殑绱犳潗 [{id, path}, ...]銆"""
        self._connect()
        with self._conn.cursor() as cur:
            if path_prefix:
                normalized_prefix = to_relative_path(path_prefix, self._cfg.get("nas_root", ""))
                cur.execute(
                    "SELECT id, path FROM materials "
                    "WHERE COALESCE(ai_status,'pending')='pending' AND path LIKE %s "
                    "ORDER BY id LIMIT %s",
                    (normalized_prefix + "%", limit),
                )
            else:
                cur.execute(
                    "SELECT id, path FROM materials "
                    "WHERE COALESCE(ai_status,'pending')='pending' "
                    "ORDER BY id LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        self._conn.commit()
        return [{"id": row[0], "path": row[1]} for row in rows]

    def get_material_by_hash(self, file_hash: str) -> Optional[dict]:
        """鎸夊唴瀹瑰搱甯屾煡鎵撅紝杩斿洖 {id, path} 鎴 None銆"""
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, path FROM materials WHERE file_hash = %s", (file_hash,)
            )
            row = cur.fetchone()
        self._conn.commit()
        return {"id": row[0], "path": row[1]} if row else None

    def replace_frames(self, material_id: int, frames: list[dict]):
        """鍒犻櫎鏃у抚锛屾壒閲忓啓鍏ユ柊甯с"""
        import numpy as np
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM frames WHERE material_id = %s", (material_id,))
            if frames:
                cur.executemany("""
                    INSERT INTO frames
                        (material_id, ts_s, brand, product, model, category,
                         confidence, embedding, thumb_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [
                    (
                        material_id,
                        f["ts_s"],
                        f.get("brand"),
                        f.get("product"),
                        f.get("model"),
                        f.get("category"),
                        f.get("confidence", 1.0),
                        np.array(f["embedding"], dtype="float32"),
                        f.get("thumb_path"),
                    )
                    for f in frames
                ])
        self._conn.commit()

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
def _sanitize_filename(name: str) -> str:
    # 移除非法字符
    invalid_chars = '<>:"/\\|?*\n\r\t'
    for c in invalid_chars:
        name = name.replace(c, "")
    # 限制长度并去除首尾空格
    name = name.strip()[:100]
    return name


def _run_image_ocr(img_path: str) -> str:
    try:
        import sys
        import subprocess
        from config.paths import PADDLEOCR_PYTHON, IMAGE_FOLDER_OCR_SCRIPT
    except ImportError:
        log.warning("config.paths import failed in OCR runner.")
        return ""
        
    if not (os.path.exists(PADDLEOCR_PYTHON) and os.path.exists(IMAGE_FOLDER_OCR_SCRIPT)):
        log.warning(f"PaddleOCR path not found: {PADDLEOCR_PYTHON} or {IMAGE_FOLDER_OCR_SCRIPT}")
        return ""
        
    cmd = [PADDLEOCR_PYTHON, IMAGE_FOLDER_OCR_SCRIPT, "--test_mode", "--image", img_path]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
            startupinfo=startupinfo,
            cwd=os.path.dirname(IMAGE_FOLDER_OCR_SCRIPT),
            timeout=30
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("[TEST_RESULT] Text:"):
                    return line.replace("[TEST_RESULT] Text:", "").strip()
    except Exception as e:
        log.warning(f"OCR execution failed for {img_path}: {e}")
    return ""


# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹
# 主入库器
# 鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹鈹

class MaterialClipIndexer:
    """
    主入库类。

    progress_cb: Callable[[str], None]  # 进度日志回调（GUI 集成时传入）
    """

    def __init__(self, nas_root: str = "", progress_cb: Optional[Callable] = None):
        self.cfg = _load_config()
        self.nas_root = nas_root or self.cfg.get("nas_root", "")
        self._cb = progress_cb or (lambda msg: log.info(msg))
        self._db = _MaterialDB(self.cfg)
        self._encoder = _ClipEncoder(
            model_name=self.cfg["clip_model"],
            model_dir=self.cfg.get("clip_model_dir"),
            device=self.cfg["device"],
            batch_size=self.cfg["batch_size"],
        )

    def to_local_path(self, path: str) -> str:
        return to_local_path(path, self.nas_root)

    def to_relative_path(self, path: str) -> str:
        return to_relative_path(path, self.nas_root)

    def _log(self, msg: str):
        self._cb(msg)

    def _call_vision_ai_tags(self, img_paths: list[str], max_frames: int = 6, ocr_text: str = "") -> dict:
        """读取 AI 配置，调用视觉 LLM 识别品牌/品类/型号。未配置或失败时返回 {}。"""
        api_url = api_key = model = ""
        concurrency = 4
        try:
            from config.paths import AI_CONFIG_FILE
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                ai_cfg = json.load(f)
            api_url = ai_cfg.get("llm_vision_api_url", "").strip()
            api_key = (ai_cfg.get("llm_vision_api_key") or ai_cfg.get("llm_api_key", "")).strip()
            model   = ai_cfg.get("llm_vision_model", "").strip()
            concurrency = int(ai_cfg.get("vision_concurrency", 4))
        except Exception:
            pass
            
        if not api_url or not model:
            return {}
            
        return _call_vision_for_product(img_paths, api_url, api_key, model, max_frames,
                                        log_cb=self._log, ocr_text=ocr_text, concurrency=concurrency)

    # ── 单文件入库 ──

    def index_file(self, file_path: str, *, force: bool = False) -> bool:
        """
        对单个文件完整走一遍入库流水线。
        force=True 时强制重新抽帧入库（即使 path 已存在）。
        """
        file_path = file_path.replace('\\', '/')
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        is_video = ext in VIDEO_EXTS
        is_image = ext in IMAGE_EXTS
        if not (is_video or is_image):
            self._log(f"  跳过（不支持的类型 {ext}）")
            return False

        # 1. 哈希 -> 重复检查（哈希不变说明内容相同，即使路径变了也不重复入库）
        self._log(f"  ① 计算哈希")
        file_hash = _compute_hash(file_path)
        if not file_hash:
            self._log(f"  ✗ 哈希计算失败，跳过")
            return False

        if not force:
            existing = self._db.get_material_by_hash(file_hash)
            if existing is not None:
                existing_rel = self.to_relative_path(existing["path"])
                file_rel = self.to_relative_path(file_path)
                if existing_rel != file_rel:
                    existing_local = self.to_local_path(existing["path"])
                    if os.path.exists(existing_local):
                        self._log(f"  → 原路径已存在且有效 ({existing_rel})，当前为副本，跳过重新抽帧")
                    else:
                        # 路径变了，更新 path 但不重新抽帧
                        self._db.upsert_material(
                            file_hash, file_path,
                            "video" if is_video else "image",
                            fname, None, 0, 0,
                        )
                        self._log(f"  → 路径已从 {existing_rel} 迁移更新至 {file_rel}，跳过重新抽帧")
                else:
                    self._log(f"  → 已索引（material_id={existing['id']}），跳过")
                return False

        # 2. 元信息
        media_type = "video" if is_video else "image"
        duration_s: Optional[float] = None
        width = height = 0

        if is_video:
            self._log(f"  ② 读取视频元信息")
            dur, width, height = _get_video_meta(file_path, self.cfg.get("ffmpeg_path"))
            duration_s = dur if dur > 0 else None
        else:
            self._log(f"  ② 读取图片元信息")
            width, height = _get_image_meta(file_path)

        # 3. 路径标签
        tags = _parse_path_tags(
            file_path, self.nas_root,
            depth_product=self.cfg["tag_depth_product"],
            depth_brand=self.cfg["tag_depth_brand"],
            depth_model=self.cfg["tag_depth_model"],
            depth_category=self.cfg["tag_depth_category"],
        )
        self._log(
            f"  ③ 路径标签: brand={tags['brand']!r} product={tags['product']!r} "
            f"model={tags['model']!r}"
        )

        # 4. 抽帧 + CLIP 推理
        frame_records: list[dict] = []
        tmp_dir = tempfile.mkdtemp(prefix="clip_idx_")
        save_thumbs = self.cfg.get("save_thumbs", False)
        thumb_base = self.cfg.get("thumb_dir") or os.path.join(tmp_dir, "thumbs")

        try:
            if is_image:
                self._log(f"  ④ 图片编码")
                embs = self._encoder.encode_images([file_path])

                ai_info = self._call_vision_ai_tags([file_path])
                if ai_info:
                    tags.update(ai_info)
                    self._log(
                        f"     AI识别: brand={tags.get('brand')!r} "
                        f"product={tags.get('product')!r} model={tags.get('model')!r}"
                    )

                thumb_path = None
                if save_thumbs:
                    thumb_path = self._make_thumb(file_path, thumb_base, 0)
                frame_records.append({
                    "ts_s": 0.0,
                    "embedding": embs[0],
                    "thumb_path": thumb_path,
                    **tags,
                    "confidence": 1.0,
                })

            else:  # video
                fps = self.cfg["fps"]
                self._log(f"  ③ ffmpeg 抽帧（{fps}fps）")
                frame_infos = _extract_frames_ffmpeg(
                    file_path, tmp_dir, fps, self.cfg.get("ffmpeg_path")
                )
                if not frame_infos:
                    self._log("  ✗ 抽帧失败，跳过")
                    return False

                img_paths = [fi[2] for fi in frame_infos]

                # 视觉 AI 识别品牌/品类/型号，复用已抽的帧，覆盖路径标签
                self._log(f"     抽出 {len(frame_infos)} 帧，视觉AI识别中…")
                ai_info = self._call_vision_ai_tags(img_paths)
                if ai_info:
                    tags.update(ai_info)
                    self._log(
                        f"     AI识别: brand={tags.get('brand')!r} "
                        f"product={tags.get('product')!r} model={tags.get('model')!r}"
                    )
                else:
                    self._log(f"     视觉AI未配置或识别失败，沿用路径标签")

                self._log(f"     CLIP 推理中…")
                embs = self._encoder.encode_images(img_paths)

                for (fidx, ts, img_path), emb in zip(frame_infos, embs):
                    thumb_path = None
                    if save_thumbs:
                        thumb_path = self._make_thumb(img_path, thumb_base, fidx)
                    frame_records.append({
                        "ts_s": ts,
                        "embedding": emb,
                        "thumb_path": thumb_path,
                        **tags,
                        "confidence": 1.0,
                    })

        finally:
            if not save_thumbs:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            else:
                # 仅清理抽帧原始图（缩略图已移到 thumb_base）
                for _, _, fp in (frame_infos if is_video else []):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass

        # 5. 写入数据库
        self._log(f"  ⑤ 写入数据库（{len(frame_records)} 帧）")
        try:
            material_id = self._db.upsert_material(
                file_hash=file_hash, path=file_path,
                media_type=media_type, filename=fname,
                duration_s=duration_s, width=width, height=height,
            )
            self._db.replace_frames(material_id, frame_records)
            self._log(f"  ✓ 完成 material_id={material_id}")
            return True
        except Exception as e:
            log.error(f"写入数据库失败 {fname}: {e}", exc_info=True)
            self._log(f"  ✗ 写库失败: {e}")
            return False

    def _make_thumb(self, src_img: str, thumb_dir: str, idx: int) -> Optional[str]:
        """生成缩略图（最长边 256px），返回缩略图路径。"""
        try:
            from PIL import Image
            os.makedirs(thumb_dir, exist_ok=True)
            dst = os.path.join(thumb_dir, f"thumb_{idx:06d}.jpg")
            with Image.open(src_img) as img:
                img.thumbnail((256, 256))
                img.save(dst, "JPEG", quality=75)
            return dst
        except Exception as e:
            log.warning(f"生成缩略图失败: {e}")
            return None

    # ── Phase 1: 元信息快速入库（无 AI，无 CLIP） ──

    def index_file_meta(self, file_path: str, *, force: bool = False) -> bool:
        """
        Phase 1：仅记录文件 hash / 路径 / 类型 / 大小 / 分辨率，ai_status='pending'。
        速度极快，无需 CLIP 模型或视觉 API。
        """
        file_path = file_path.replace('\\', '/')
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        is_video = ext in VIDEO_EXTS
        is_image = ext in IMAGE_EXTS
        if not (is_video or is_image):
            return False

        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            mtime = stat.st_mtime
        except Exception:
            file_size = None
            mtime = None

        self._log(f"  ① 计算哈希")
        file_hash = _compute_hash(file_path)
        if not file_hash:
            self._log(f"  ✗ 哈希失败，跳过")
            return False

        if not force:
            existing = self._db.get_material_by_hash(file_hash)
            if existing is not None:
                existing_rel = self.to_relative_path(existing["path"])
                file_rel = self.to_relative_path(file_path)
                if existing_rel != file_rel:
                    existing_local = self.to_local_path(existing["path"])
                    if os.path.exists(existing_local):
                        self._log(f"  → 原路径已存在且有效 ({existing_rel})，当前为副本，跳过")
                    else:
                        self._db.upsert_material(
                            file_hash, file_path,
                            "video" if is_video else "image",
                            fname, None, 0, 0,
                            file_size=file_size, mtime=mtime
                        )
                        self._log(f"  → 路径已从 {existing_rel} 迁移更新至 {file_rel}")
                else:
                    self._log(f"  → 已入库，跳过")
                return False

        media_type = "video" if is_video else "image"
        duration_s, width, height = None, 0, 0
        if is_video:
            self._log(f"  ② 读取视频元信息")
            dur, w, h = _get_video_meta(file_path, self.cfg.get("ffmpeg_path"))
            duration_s = dur or None
            width, height = w, h
        else:
            self._log(f"  ② 读取图片尺寸")
            width, height = _get_image_meta(file_path)

        try:
            material_id = self._db.upsert_material(
                file_hash=file_hash, path=file_path,
                media_type=media_type, filename=fname,
                duration_s=duration_s, width=width, height=height,
                file_size=file_size, mtime=mtime
            )
            self._db.update_material_ai(
                material_id,
                brand=None, product=None, model=None,
                category=None, audio_script=None,
                ai_status="pending",
            )
            self._log(f"  ✓ 已入库 id={material_id}")
            return True
        except Exception as e:
            self._log(f"  ✗ 写库失败: {e}")
            return False

    def index_directory_meta(self, directory: str, *, force: bool = False, file_progress_cb: Optional[Callable[[int, int], None]] = None) -> tuple:
        """Phase 1 批量：遍历目录，仅入库文件元信息（不做任何 AI 分析）。"""
        self._log("正在并行扫描目录结构并统计媒体文件...")
        
        supported_exts = VIDEO_EXTS | IMAGE_EXTS
        all_disk_files = []
        last_reported_count = 0
        
        def scan_single_dir(dpath):
            local_files = []
            subdirs = []
            try:
                for entry in os.scandir(dpath):
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in supported_exts:
                            try:
                                st = entry.stat()
                                local_files.append((os.path.normpath(entry.path), st.st_size, st.st_mtime))
                            except Exception:
                                local_files.append((os.path.normpath(entry.path), 0, 0.0))
                    elif entry.is_dir():
                        subdirs.append(entry.path)
            except Exception:
                pass
            return local_files, subdirs

        # 并发扫描目录树，16 线程避让网络共享目录延迟
        futures = []
        with ThreadPoolExecutor(max_workers=16) as executor:
            pending_dirs = [directory]
            while pending_dirs or futures:
                for d in pending_dirs:
                    futures.append(executor.submit(scan_single_dir, d))
                pending_dirs = []
                
                completed = [fut for fut in futures if fut.done()]
                if completed:
                    for fut in completed:
                        local_files, subdirs = fut.result()
                        all_disk_files.extend(local_files)
                        pending_dirs.extend(subdirs)
                        futures.remove(fut)
                    
                    current_count = len(all_disk_files)
                    if file_progress_cb and current_count - last_reported_count >= 100:
                        file_progress_cb(-1, current_count)
                        last_reported_count = current_count
                else:
                    time.sleep(0.01)

        total = len(all_disk_files)
        if file_progress_cb:
            file_progress_cb(-1, total)
        self._log(f"发现 {total} 个符合格式要求的媒体文件。")

        # 加载数据库中已有的状态数据：{ rel_path: (size, mtime, file_hash) }
        db_state = {}
        if not force:
            try:
                self._db._connect()
                with self._db._conn.cursor() as cur:
                    dir_rel = self.to_relative_path(directory).replace('\\', '/').strip('/')
                    if dir_rel:
                        cur.execute(
                            "SELECT path, file_size, mtime, file_hash FROM materials WHERE path = %s OR path LIKE %s",
                            (dir_rel, dir_rel + "/%")
                        )
                    else:
                        cur.execute("SELECT path, file_size, mtime, file_hash FROM materials")
                    rows = cur.fetchall()
                    for r in rows:
                        if r[0]:
                            db_state[r[0].replace('\\', '/').strip('/')] = (r[1], r[2], r[3])
                self._db._conn.commit()
                self._log(f"已加载数据库中已存的 {len(db_state)} 条路径索引。")
            except Exception as e:
                self._log(f"加载已有记录失败，降级为无缓存模式: {e}")

        # 比对与分类
        new_files = []      # 磁盘新出现的文件
        modified_files = [] # 磁盘上发生修改的文件
        deleted_paths = set(db_state.keys()) # 磁盘已删除/移动的相对路径
        
        ok_count = skip_count = fail_count = 0
        
        for fp, size, mtime in all_disk_files:
            rel_path = self.to_relative_path(fp).replace('\\', '/').strip('/')
            if rel_path in db_state:
                db_size, db_mtime, db_hash = db_state[rel_path]
                size_match = (db_size == size) if (db_size is not None) else True
                mtime_match = (abs(db_mtime - mtime) < 1.0) if (db_mtime is not None) else True
                
                if size_match and mtime_match:
                    skip_count += 1
                else:
                    modified_files.append((fp, size, mtime))
                
                if rel_path in deleted_paths:
                    deleted_paths.remove(rel_path)
            else:
                new_files.append((fp, size, mtime))

        # 重命名/移动启发式优化
        deleted_meta_map = {}
        for del_rel in list(deleted_paths):
            sz, mt, h = db_state[del_rel]
            if sz is not None and mt is not None:
                deleted_meta_map[(sz, mt)] = (del_rel, h)
        
        final_new_files = []
        for fp, size, mtime in new_files:
            match_key = (size, mtime)
            if match_key in deleted_meta_map:
                old_rel, h = deleted_meta_map[match_key]
                try:
                    self._db.upsert_material(
                        file_hash=h, path=fp,
                        media_type="video" if os.path.splitext(fp)[1].lower() in VIDEO_EXTS else "image",
                        filename=os.path.basename(fp),
                        duration_s=None, width=0, height=0,
                        file_size=size, mtime=mtime
                    )
                    if old_rel in deleted_paths:
                        deleted_paths.remove(old_rel)
                    skip_count += 1
                    self._log(f"检测到文件移动/重命名: {old_rel} ➔ {self.to_relative_path(fp)}")
                except Exception:
                    final_new_files.append((fp, size, mtime))
            else:
                final_new_files.append((fp, size, mtime))
                
        # 对变化部分进行真正的 Hash 计算与元信息分析
        work_todo = final_new_files + modified_files
        todo_total = len(work_todo)
        
        self._log(f"元数据比对完成：已跳过未变文件 {skip_count} 个，需入库/更新 {todo_total} 个文件，待清理失效文件 {len(deleted_paths)} 个。")
        
        for idx, (fp, size, mtime) in enumerate(work_todo):
            if file_progress_cb:
                file_progress_cb(idx + 1, todo_total)
            
            self._log(f"\n[{idx+1}/{todo_total}] {os.path.basename(fp)}")
            try:
                if self.index_file_meta(fp, force=force):
                    ok_count += 1
                else:
                    skip_count += 1
            except Exception as e:
                self._log(f"  ✗ 异常: {e}")
                fail_count += 1

        # 执行清理：从数据库中删除物理磁盘上不存在且未被更新移走的失效路径文件
        # (在此处执行可以完美保留重命名/移动文件的 AI 分析数据)
        deleted_count = 0
        for del_rel in deleted_paths:
            try:
                del_local = self.to_local_path(del_rel)
                self._db.delete_material_by_path(del_local)
                deleted_count += 1
                self._log(f"清理失效的库中文件记录: {del_rel}")
            except Exception as e:
                self._log(f"清理失效记录失败 {del_rel}: {e}")
                
        self._log(f"\n━━━ 元信息差分同步完成 ━━━  新增/更新:{ok_count}  跳过:{skip_count}  失败:{fail_count}  清理失效:{deleted_count}")
        return ok_count, skip_count, fail_count

    def analyze_material(self, material_id: int, file_path: str) -> bool:
        """
        Phase 2：对单个已入库素材执行 AI 分析。
        流程：抽帧 → 视觉 LLM（品牌/型号）→ Whisper（台词补充）→ CLIP 向量（可选）
        结果写回 materials 并更新 frames，失败时标记 ai_status='failed'。
        """
        file_path = self.to_local_path(file_path)
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        is_video = ext in VIDEO_EXTS
        is_image = ext in IMAGE_EXTS

        # 计算并记录文件哈希与基本信息
        file_hash = _compute_hash(file_path) or "unknown"
        self._log(f"\n========================================================")
        self._log(f"📄 [AI 分析] 文件: {fname}")
        self._log(f"🔑 哈希值 (Hash): {file_hash}")
        self._log(f"--------------------------------------------------------")

        # 1. OCR text extraction for images (No automatic renaming during AI analysis)
        ocr_text = ""
        new_file_path = file_path
        new_fname = fname

        if is_image:
            self._log("  ① 运行图片 OCR 识别")
            try:
                ocr_text = _run_image_ocr(file_path)
            except Exception as e:
                self._log(f"     ⚠ OCR 运行异常: {e}")
                ocr_text = ""

            if ocr_text:
                self._log(f"     OCR 识别到文字: '{ocr_text}'")

        tmp_dir = tempfile.mkdtemp(prefix="clip_ai_")
        try:
            # ── 抽帧 ──────────────────────────────────────────────────────────
            if is_video:
                fps = self.cfg["fps"]
                self._log(f"  ③ 抽帧（{fps}fps）")
                frame_infos = _extract_frames_ffmpeg(
                    new_file_path, tmp_dir, fps, self.cfg.get("ffmpeg_path")
                )
                img_paths = [fi[2] for fi in frame_infos] if frame_infos else []
            else:
                frame_infos = [(0, 0.0, new_file_path)]
                img_paths = [new_file_path]

            # ── 视觉 LLM：品牌 / 品类 / 型号 / 画面描述 ───────────────────────
            brand = product = model = None
            scene_desc_primary = scene_desc_secondary = None
            ai_confidence = None
            if img_paths:
                self._log(f"  ④ 视觉AI识别（{len(img_paths)} 帧）")
                ai_info = self._call_vision_ai_tags(img_paths, ocr_text=ocr_text)
                if ai_info:
                    brand              = ai_info.get("brand")
                    product            = ai_info.get("product")
                    model              = ai_info.get("model")
                    scene_desc_primary = ai_info.get("scene_desc_primary")
                    scene_desc_secondary = ai_info.get("scene_desc_secondary")
                    ai_confidence      = ai_info.get("ai_confidence")
                    self._log(
                        f"     AI: brand={brand!r} product={product!r} model={model!r} "
                        f"confidence={ai_confidence}"
                    )
                else:
                    self._log(f"     视觉AI未配置或识别失败")

            # ── Whisper 台词转写（视频，可选）────────────────────────────────
            audio_script = ""
            if is_video:
                self._log(f"  ⑤ Whisper 台词转写")
                try:
                    from config.paths import WHISPER_MODELS_DIR
                    from utils.video_indexer import transcribe_audio
                    audio_script = transcribe_audio(new_file_path, WHISPER_MODELS_DIR)
                    self._log(f"     转写 {len(audio_script)} 字")
                    # 视觉未识别时从台词关键词补充
                    if not (brand and model) and audio_script:
                        s_brand, s_product, s_model = _extract_from_script(audio_script)
                        brand   = brand   or s_brand
                        product = product or s_product
                        model   = model   or s_model
                        if s_brand or s_model:
                            self._log(
                                f"     台词补充: brand={brand!r} model={model!r}"
                            )
                            if ai_confidence is None:
                                ai_confidence = 0.4  # 台词关键词识别，置信度较低
                except Exception as e:
                    self._log(f"     转写失败（跳过）: {e}")

            # ── CLIP 向量编码（可选，失败不中断主流程）───────────────────────
            frame_records: list[dict] = []
            try:
                if img_paths:
                    self._log(f"  ⑥ CLIP 向量编码")
                    step = max(1, len(img_paths) // 8)
                    sample_paths = img_paths[::step][:8]
                    sample_infos = frame_infos[::step][:8]
                    embs = self._encoder.encode_images(sample_paths)
                    tags_row = {
                        "brand": brand, "product": product,
                        "model": model, "category": None,
                    }
                    for (fidx, ts, _), emb in zip(sample_infos, embs):
                        frame_records.append({
                            "ts_s": ts, "embedding": emb,
                            "thumb_path": None, **tags_row, "confidence": 1.0,
                        })
                    self._log(f"     写入 {len(frame_records)} 帧向量")
            except Exception as e:
                self._log(
                    f"  ⚠ CLIP 编码失败（跳过向量，品牌/型号仍保存）: {e}"
                )

            # ── 写库 ─────────────────────────────────────────────────────────
            status = "analyzed"
            if not scene_desc_primary or not str(scene_desc_primary).strip() or str(scene_desc_primary).strip() == "—":
                self._log("  ✗ 视觉 AI 识别未生成主要画面描述，判定为分析失败")
                status = "failed"

            self._db.update_material_ai(
                material_id,
                brand=brand, product=product, model=model,
                category=None, audio_script=audio_script,
                ai_status=status,
                ai_confidence=ai_confidence,
                scene_desc_primary=scene_desc_primary,
                scene_desc_secondary=scene_desc_secondary,
            )
            if frame_records:
                self._db.replace_frames(material_id, frame_records)
            
            if status == "failed":
                self._log(f"  ❌ AI 分析失败")
                self._log(f"========================================================\n")
                return False

            self._log(f"  ✅ AI 分析完成")
            self._log(f"========================================================\n")
            return True

        except Exception as e:
            log.error(f"AI分析失败 {new_fname}: {e}", exc_info=True)
            self._log(f"  ✗ AI 分析失败: {e}")
            try:
                self._db.update_material_ai(
                    material_id,
                    brand=None, product=None, model=None, category=None,
                    audio_script=None, ai_status="failed",
                    ai_confidence=None, scene_desc_primary=None, scene_desc_secondary=None,
                )
            except Exception:
                pass
            self._log(f"========================================================\n")
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def analyze_directory(self, directory: str, *, limit: int = 10000) -> tuple:
        """对目录下所有 pending 状态的素材进行 AI 分析。"""
        self._log(f"\n━━━ 开始批量 AI 分析 ━━━  目录: {directory}")
        pending = self.get_pending_materials(directory, limit=limit)
        total = len(pending)
        if total == 0:
            self._log("没有待分析 of 素材。")
            return 0, 0

        self._log(f"待分析 {total} 个素材，开始 AI 分析…")
        ok_count = fail_count = 0
        for i, mat in enumerate(pending):
            fp = self.to_local_path(mat["path"])
            self._log(f"\n[{i+1}/{total}] {os.path.basename(fp)}")
            if not os.path.isfile(fp):
                self._log(f"  ✗ 文件不可访问，标记失败")
                try:
                    self._db.update_material_ai(
                        mat["id"],
                        brand=None, product=None, model=None, category=None,
                        audio_script=None, ai_status="failed",
                        ai_confidence=None, scene_desc_primary=None, scene_desc_secondary=None,
                    )
                except Exception:
                    pass
                fail_count += 1
                continue

            try:
                if self.analyze_material(mat["id"], fp):
                    ok_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                self._log(f"  ✗ 异常: {e}")
                fail_count += 1

        self._log(
            f"\n━━━ AI批量分析完成 ━━━  成功:{ok_count}  失败:{fail_count}"
        )
        return ok_count, fail_count

    def ocr_rename_material(self, material_id: int, file_path: str) -> tuple[bool, str]:
        """
        对单个图片素材进行 OCR 识别，并重命名该物理文件，同步更新数据库。
        返回 (success, new_path)
        """
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        if ext not in IMAGE_EXTS:
            return False, file_path

        self._log(f"  ① 运行图片 OCR 识别: {fname}")
        try:
            ocr_text = _run_image_ocr(file_path)
        except Exception as e:
            self._log(f"     ⚠ OCR 运行异常: {e}")
            return False, file_path

        if not ocr_text:
            self._log("     OCR 未识别到任何文字，跳过重命名")
            return False, file_path

        self._log(f"     OCR 识别到文字: '{ocr_text}'")
        sanitized = _sanitize_filename(ocr_text)
        if not sanitized:
            self._log("     清洗后的文字为空（均为非法字符），跳过重命名")
            return False, file_path

        dir_name = os.path.dirname(file_path)
        candidate_name = f"{sanitized}{ext}"
        candidate_path = os.path.join(dir_name, candidate_name)
        counter = 1
        # Resolve conflicts with suffix _1, _2...
        while os.path.exists(candidate_path) and candidate_path.lower() != file_path.lower():
            candidate_name = f"{sanitized}_{counter}{ext}"
            candidate_path = os.path.join(dir_name, candidate_name)
            counter += 1

        if candidate_path.lower() == file_path.lower():
            self._log("     文件名无变化，无需重命名")
            return True, file_path

        self._log(f"  ② 正在将文件重命名为: {candidate_name}")
        try:
            os.rename(file_path, candidate_path)
            
            # Sync database immediately
            self._db._connect()
            with self._db._conn.cursor() as cur:
                cur.execute(
                    "UPDATE materials SET path=%s, filename=%s WHERE id=%s",
                    (candidate_path.replace('\\', '/'), candidate_name, material_id)
                )
            self._db._conn.commit()
            self._log("     已同步更新数据库路径与文件名")
            return True, candidate_path
        except Exception as e:
            self._log(f"  ✗ 重命名文件失败: {e}")
            return False, file_path

    def ocr_rename_directory(self, directory: str) -> tuple[int, int]:
        """对目录下所有的图片执行 OCR 智能重命名。"""
        self._log(f"\n━━━ 开始批量 OCR 智能重命名 ━━━  目录: {directory}")
        
        # Query all materials in this directory (we can load materials under this path prefix)
        self._db._connect()
        conds = ["path LIKE %s"]
        normalized_dir = self.to_relative_path(directory)
        params = [normalized_dir + "%"]
        where = "WHERE " + " AND ".join(conds)
        
        with self._db._conn.cursor() as cur:
            cur.execute(f"SELECT id, path FROM materials {where} ORDER BY id DESC", params)
            rows = cur.fetchall()
            
        total = len(rows)
        if total == 0:
            self._log("该目录下没有任何已入库素材。")
            return 0, 0
            
        ok_count = fail_count = 0
        for i, row in enumerate(rows):
            mat_id, fp = row[0], self.to_local_path(row[1])
            fname = os.path.basename(fp)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMAGE_EXTS:
                # Skip non-images
                continue
                
            self._log(f"\n[{i+1}/{total}] {fname}")
            if not os.path.isfile(fp):
                self._log("  ✗ 文件不可访问，跳过")
                fail_count += 1
                continue
                
            success, _ = self.ocr_rename_material(mat_id, fp)
            if success:
                ok_count += 1
            else:
                fail_count += 1
                
        self._log(f"\n━━━ 智能重命名完成 ━━━  成功:{ok_count}  失败:{fail_count}")
        return ok_count, fail_count

    def get_stats(self) -> dict:
        return self._db.get_stats()

    def list_materials(self, path_prefix: str = "", limit: int = 10000,
                       offset: int = 0, ai_status: Optional[str] = None,
                       hash_prefix: str = "", media_type: Optional[str] = None,
                       brand: str = "", scene_desc: str = "",
                       conf_filter: str = "", product: str = "") -> list:
        return self._db.list_materials(
            path_prefix, limit, offset, ai_status, hash_prefix, media_type,
            brand=brand, scene_desc=scene_desc, conf_filter=conf_filter, product=product
        )

    def search_by_tags(self, brand: str = None, model: str = None,
                       category: str = None, ai_status: str = None,
                       limit: int = 10000, hash_prefix: str = "") -> list:
        return self._db.search_by_tags(brand, model, category, ai_status, limit, hash_prefix)

    def index_directory(
        self, directory: str, *, force: bool = False,
        nas_root: Optional[str] = None
    ) -> tuple:
        if nas_root is not None:
            self.nas_root = nas_root
        self._log(f"\n━━━ 开始批量入库 ━━━  目录: {directory}")
        
        # We need to collect files recursively
        files = []
        for root, _, fs in os.walk(directory):
            for f in fs:
                ext = os.path.splitext(f)[1].lower()
                if ext in VIDEO_EXTS or ext in IMAGE_EXTS:
                    files.append(os.path.join(root, f))
        
        total = len(files)
        if total == 0:
            self._log("未找到支持的音视频/图片素材。")
            return 0, 0, 0

        self._log(f"找到 {total} 个素材，开始元信息快速入库…")
        ok_count = skip_count = fail_count = 0
        for i, fp in enumerate(files):
            self._log(f"\n[{i+1}/{total}] {os.path.basename(fp)}")
            try:
                if self.index_file_meta(fp, force=force):
                    ok_count += 1
                else:
                    skip_count += 1
            except Exception as e:
                self._log(f"  ✗ 异常: {e}")
                fail_count += 1

        self._log(
            f"\n━━━ 元信息入库完成 ━━━  新增:{ok_count}  跳过:{skip_count}  失败:{fail_count}"
        )
        return ok_count, skip_count, fail_count

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __getattr__(self, name):
        if name in ("_connect", "_conn"):
            return getattr(self._db, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


# ──────────────────────────────────────────────────────────────────────────────
# 相似度检索（返回 frames 级别，连接 materials 取路径）
# ──────────────────────────────────────────────────────────────────────────────

def search_by_text(
    query: str, top_k: int = 20,
    filter_brand: Optional[str] = None,
    filter_category: Optional[str] = None,
    filter_hash: Optional[str] = None,
    cfg: Optional[dict] = None,
    comprehensive: bool = True,
) -> list[dict]:
    """
    用文字描述向量检索，返回最相似的 top_k 帧记录（含来源文件路径）。
    可附加 brand / category / file_hash 筛选。
    comprehensive=True 时综合匹配文件名、画面描述、品牌、型号，并按置信度加权。
    返回字段: material_id, path, filename, ts_s, brand, product, model, category, score, file_hash, scene_desc_primary, scene_desc_secondary
    """
    if cfg is None:
        cfg = _load_config()
    import numpy as np
    encoder = get_encoder(cfg)
    embs = encoder.encode_text([query])
    if not embs:
        return []
    query_vec = np.array(embs[0], dtype="float32")

    db = _MaterialDB(cfg)
    try:
        db._connect()
        conditions = ["f.embedding IS NOT NULL"]
        params: list = []

        # 综合文本匹配模式
        text_score_parts = []
        if comprehensive and query:
            like_q = f"%{query}%"
            # 关键词拆分为单个词，每个词分别匹配
            keywords = [k.strip() for k in query.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if k.strip()]
            if not keywords:
                keywords = [query]

            for kw in keywords:
                kw_like = f"%{kw}%"
                # 文件名、画面描述、品牌、型号、品类 都做 ILIKE 匹配
                text_score_parts.append(
                    f"(CASE WHEN m.filename ILIKE %s THEN 1.0 ELSE 0 END +"
                    f" CASE WHEN m.scene_desc_primary ILIKE %s THEN 0.8 ELSE 0 END +"
                    f" CASE WHEN m.scene_desc_secondary ILIKE %s THEN 0.6 ELSE 0 END +"
                    f" CASE WHEN f.brand ILIKE %s THEN 0.9 ELSE 0 END +"
                    f" CASE WHEN f.model ILIKE %s THEN 0.9 ELSE 0 END +"
                    f" CASE WHEN f.category ILIKE %s THEN 0.7 ELSE 0 END +"
                    f" CASE WHEN f.product ILIKE %s THEN 0.7 ELSE 0 END)"
                )
                params.extend([kw_like] * 7)

        if filter_brand:
            conditions.append("f.brand = %s")
            params.append(filter_brand)
        if filter_category:
            conditions.append("f.category = %s")
            params.append(filter_category)
        if filter_hash:
            conditions.append("m.file_hash ILIKE %s")
            params.append(filter_hash.strip() + "%")
        where = " AND ".join(conditions)

        # 组合分数: 向量相似度 60% + 文本匹配 30% + 置信度 10%
        if text_score_parts:
            text_sum = " + ".join(text_score_parts)
            score_sql = f"""
                (0.6 * (1 - (f.embedding <=> %s)) +
                 0.3 * ({text_sum}) / GREATEST(1, {len(keywords)} * 3.0) +
                 0.1 * COALESCE(m.ai_confidence, 0.5))
                AS score
            """
        else:
            score_sql = "1 - (f.embedding <=> %s) AS score"

        sql = f"""
            SELECT m.id, m.path, m.filename, f.ts_s,
                   f.brand, f.product, f.model, f.category,
                   {score_sql},
                   m.file_hash, m.scene_desc_primary, m.scene_desc_secondary,
                   COALESCE(m.ai_confidence, 0.5) AS confidence,
                   COALESCE(m.media_type, '') AS media_type
            FROM frames f
            JOIN materials m ON m.id = f.material_id
            WHERE {where}
            ORDER BY score DESC
            LIMIT %s
        """
        params = [query_vec] + params + [query_vec, top_k]
        with db._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [
            {
                "material_id": r[0], "path": r[1], "filename": r[2],
                "ts_s": r[3], "brand": r[4], "product": r[5],
                "model": r[6], "category": r[7], "score": float(r[8]),
                "file_hash": r[9], "scene_desc_primary": r[10], "scene_desc_secondary": r[11],
                "confidence": float(r[12]) if r[12] is not None else 0.5,
                "media_type": r[13] or "",
            }
            for r in rows
        ]
    finally:
        db.close()


def search_by_image(
    image_path: str, top_k: int = 20, cfg: Optional[dict] = None
) -> list[dict]:
    """以图搜视频帧，返回同 search_by_text 的结构。"""
    if cfg is None:
        cfg = _load_config()
    import numpy as np
    encoder = _ClipEncoder(cfg["clip_model"], cfg.get("clip_model_dir"), cfg["device"], 1)
    embs = encoder.encode_images([image_path])
    if not embs:
        return []
    query_vec = np.array(embs[0], dtype="float32")

    db = _MaterialDB(cfg)
    try:
        db._connect()
        with db._conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.path, m.filename, f.ts_s,
                       f.brand, f.product, f.model, f.category,
                       1 - (f.embedding <=> %s) AS score,
                       m.file_hash, m.scene_desc_primary, m.scene_desc_secondary
                FROM frames f
                JOIN materials m ON m.id = f.material_id
                WHERE f.embedding IS NOT NULL
                ORDER BY f.embedding <=> %s
                LIMIT %s
            """, (query_vec, query_vec, top_k))
            rows = cur.fetchall()
        return [
            {
                "material_id": r[0], "path": r[1], "filename": r[2],
                "ts_s": r[3], "brand": r[4], "product": r[5],
                "model": r[6], "category": r[7], "score": float(r[8]),
                "file_hash": r[9], "scene_desc_primary": r[10], "scene_desc_secondary": r[11],
            }
            for r in rows
        ]
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="素材 CLIP 入库工具")
    sub = parser.add_subparsers(dest="cmd")

    p_idx = sub.add_parser("index", help="批量入库指定目录")
    p_idx.add_argument("directory", help="要入库的目录路径")
    p_idx.add_argument("--nas-root", default="", help="NAS 根目录（用于路径标签解析）")
    p_idx.add_argument("--force", action="store_true", help="强制重新入库已存在的路径")
    p_idx.add_argument("--fps", type=float, help="覆盖配置的抽帧帧率")

    p_srch = sub.add_parser("search", help="文字检索")
    p_srch.add_argument("query", help="搜索描述词")
    p_srch.add_argument("--top-k", type=int, default=10)
    p_srch.add_argument("--brand", default=None)

    args = parser.parse_args()

    if args.cmd == "index":
        cfg = _load_config()
        if args.fps:
            cfg["fps"] = args.fps

        def _print(msg):
            print(msg)

        with MaterialClipIndexer(nas_root=args.nas_root, progress_cb=_print) as indexer:
            indexer.cfg = cfg
            ok, skip, fail = indexer.index_directory(args.directory, force=args.force)
        print(f"\n成功:{ok}  跳过:{skip}  失败:{fail}")

    elif args.cmd == "search":
        results = search_by_text(args.query, top_k=args.top_k, filter_brand=args.brand)
        for r in results:
            ts = f"@{r['ts_s']:.1f}s" if r["ts_s"] else ""
            print(f"[{r['score']:.3f}] {r['filename']}{ts}  {r['brand']} {r['model']}")
            print(f"         {r['path']}")

    else:
        parser.print_help()
