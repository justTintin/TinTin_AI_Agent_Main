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
  results, total = search_by_text("罗技无线鼠标 白色", top_k=10)

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
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.paths import CONFIG_DIR

log = logging.getLogger(__name__)


_DRIVE_UNC_CACHE = {}


def to_relative_path(local_path: str, nas_root: str) -> str:
    """
    Convert a local filesystem path to a relative NAS path.
    Windows: resolves drive letters to UNC paths via mpr.dll.
    """
    if not local_path:
        return ""

    local_path = local_path.replace("\\", "/")
    unc_path = local_path

    if len(local_path) >= 2 and local_path[1] == ":":
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
    return unc_path.replace("\\", "/").lstrip("/")


def to_local_path(rel_path: str, nas_root: str = "") -> str:
    """
    将数据库里的路径解析为本地可访问的完整路径。
    统一逻辑：盘符路径直接返回，相对路径从配置读 nas_root 拼接。
    """
    if not rel_path:
        return ""

    rel_path = rel_path.replace("\\", "/")

    # 盘符路径（如 O:/xxx）直接返回——本机已映射，可直接访问
    if len(rel_path) >= 2 and rel_path[1] == ":":
        return os.path.normpath(rel_path)

    # 相对路径：从配置读 nas_root（不依赖传入的变量）
    if not nas_root:
        try:
            cfg = _load_config()
            nas_root = cfg.get("nas_root", "")
        except Exception:
            pass

    unc_path = os.path.normpath(os.path.join(nas_root, rel_path.lstrip("/\\")))

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
    """获取全局 CLIP 编码器单例（远程 HTTP 模式，线程安全）。"""
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        if _GLOBAL_ENCODER is None:
            api_url = _read_clip_api_url()
            _GLOBAL_ENCODER = _ClipEncoder(api_url)
    return _GLOBAL_ENCODER


def reset_encoder():
    """重置全局编码器（远程模式下为空操作，保留以兼容旧调用方）。"""
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        _GLOBAL_ENCODER = None


def preload_encoder(cfg: Optional[dict] = None):
    """
    预热 CLIP 编码器（远程 HTTP 模式下无需本地加载，此函数为空操作，保留以兼容旧调用方）。
    """
    # 远程模式下，实例化即就绪，无需预加载模型。
    get_encoder(cfg)


def get_encoder_status() -> dict:
    """
    返回当前编码器状态字典（远程 HTTP 模式）:
      loaded  bool      是否就绪（远程模式下实例化即视为就绪）
      status  str       人类可读状态描述
      backend str|None  固定为 "remote"
      error   str|None  失败原因（远程地址未配置时给出提示）
    """
    global _GLOBAL_ENCODER
    with _ENCODER_LOCK:
        enc = _GLOBAL_ENCODER
    if enc is None:
        api_url = _read_clip_api_url()
        if not api_url:
            return {
                "loaded": False,
                "status": "未配置 CLIP API 地址",
                "backend": None,
                "error": "请先在「AI 模型配置」中填写 CLIP API 地址。",
            }
        return {"loaded": True, "status": "已就绪 (remote)", "backend": "remote", "error": None}
    if not enc.clip_api_url:
        return {
            "loaded": False,
            "status": "未配置 CLIP API 地址",
            "backend": None,
            "error": "请先在「AI 模型配置」中填写 CLIP API 地址。",
        }
    return {"loaded": True, "status": "已就绪 (remote)", "backend": "remote", "error": None}

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

    # 自适应抽帧：根据视频时长/文件大小动态调整抽帧率，控制总帧数在合理区间
    "adaptive_max_frames": 12,          # 视频分析时总帧数上限
    "adaptive_min_frames": 6,           # 短 clip 或小文件时的最少帧数
    "adaptive_size_threshold_mb": 200,  # 超过此大小进一步降帧

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

_CFG_FILE = os.path.join(CONFIG_DIR, "material_index_config.json")

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# 鍙拌瘝鍏抽敭璇嶅簱锛堣嗚堿I鏈璇嗗埆鏃剁殑鏂囧瓧鍏滃簳锛
_KNOWN_BRANDS = [
    "logitech", "缃楁妧", "razer", "闆疯泧", "corsair", "娴风洍鑸",
    "steelseries", "璧涚澘", "hyperx", "cherry", "妯辨", "roccat",
    "apple", "苹果", "samsung", "三星", "xiaomi", "小米",
    "huawei", "鍗庝负", "asus", "鍗庣", "msi", "寰鏄",
    "anker", "安克", "hp", "惠普", "dell", "戴尔",
    "gpw", "g pro wireless", "gpx", "g pro x superlight",
]

_KNOWN_CATEGORIES = {
    "鼠标":   ["mouse", "鼠标", "dpi", "cpi", "灵敏度", "回报率", "polling rate", "双击", "左键", "右键"],
    "閿鐩":   ["keyboard", "閿鐩", "kbd", "鏈烘拌酱"],
    "手机":   ["phone", "手机", "mobile", "iphone", "安卓"],
    "耳机":   ["headset", "earphone", "耳机", "earbuds", "airpods"],
    "鏄剧ず鍣": ["monitor", "display", "鏄剧ず鍣"],
    "榧犳爣鍨": ["mousepad", "榧犳爣鍨", "desk mat"],
    "闊崇":   ["speaker", "闊崇", "鍠囧彮"],
}


def _is_hidden_name(name: str) -> bool:
    if not name:
        return False
    lower = name.lower()
    if name.startswith("."):
        return True
    if lower in {"#recycle", "$recycle.bin", "system volume information", "thumbs.db", "desktop.ini"}:
        return True
    return False


def _has_hidden_or_system_attr(path: str) -> bool:
    if os.name != "nt":
        return False
    try:
        st = os.stat(path, follow_symlinks=False)
        attrs = getattr(st, "st_file_attributes", 0)
        hidden = 0x2
        system = 0x4
        return bool(attrs & (hidden | system))
    except Exception:
        return False


def _should_skip_path(path: str) -> bool:
    name = os.path.basename(path.rstrip("/\\"))
    if _is_hidden_name(name) or _has_hidden_or_system_attr(path):
        return True
    lower = name.lower()
    if lower == "splits":
        return True
    norm = path.replace("\\", "/").rstrip("/")
    if "/splits/" in norm + "/":
        return True
    return False


# 回收站路径匹配模式：#recycle（Synology）、$recycle.bin（Windows）
# 作为参数值传入 SQL（不内联），避免 #recycle/% 中的 % 被 psycopg2 误判为占位符
_RECYCLE_PATH_PATTERNS = (
    "#recycle/%",      "%/#recycle/%",
    "$recycle.bin/%",  "%/$recycle.bin/%",
)


def _recycle_exclude_cond(table_alias: str = "") -> tuple:
    """构建 WHERE 片段，排除回收站路径（#recycle / $recycle.bin）。
    返回 (sql_fragment, params)：sql_fragment 含 %s 占位符，需与 params 配对传入。
    table_alias: JOIN 场景下 materials 表的别名（如 'm'），留空则不带别名前缀。
    """
    col = f"{table_alias}.path" if table_alias else "path"
    clauses = [f"{col} NOT LIKE %s" for _ in _RECYCLE_PATH_PATTERNS]
    return " AND ".join(clauses), list(_RECYCLE_PATH_PATTERNS)


_SCRIPT_BRAND_PATTERNS = [
    ("罗技", ["logitech", "logi", "罗技", "gpw", "g pro wireless", "g pro x superlight", "gpx"]),
    ("雷蛇", ["razer", "雷蛇"]),
]


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


def _read_clip_api_url() -> str:
    """从 ai_config.json 读取 clip embedding 地址。优先 clip_api_url，否则从 compute_server_url 派生。"""
    ai_cfg_path = os.path.join(CONFIG_DIR, "ai_config.json")
    try:
        if os.path.isfile(ai_cfg_path):
            with open(ai_cfg_path, encoding="utf-8") as f:
                ac = json.load(f)
            url = (ac.get("clip_api_url") or "").strip()
            if not url:
                url = (ac.get("compute_server_url") or "").strip()
            return url
    except Exception as e:
        log.warning(f"读取 ai_config.json 中 clip_api_url 失败: {e}")
    return ""


def _read_material_server_url() -> str:
    """从 ai_config.json 读取素材服务地址。优先 material_api_url，否则从 compute_server_url 派生。"""
    ai_cfg_path = os.path.join(CONFIG_DIR, "ai_config.json")
    try:
        if os.path.isfile(ai_cfg_path):
            with open(ai_cfg_path, encoding="utf-8") as f:
                ac = json.load(f)
            url = (ac.get("material_api_url") or "").strip()
            if not url:
                url = (ac.get("compute_server_url") or "").strip()
            return url
    except Exception as e:
        log.warning(f"读取 ai_config.json 中 material_api_url 失败: {e}")
    return ""


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


class _ClipEncoder:
    """
    CLIP 编码封装（远程 HTTP embedding 服务模式）。

    不再本地加载 Chinese-CLIP 模型，而是通过 HTTP 调用远程 embedding 服务：
      - 文本编码：POST {clip_api_url}/v1/embeddings  body {"input": [...], "model": "clip", "input_type": "text"}
      - 图片编码：POST {clip_api_url}/v1/embeddings  body {"input": [base64...], "model": "clip", "input_type": "image"}
    响应为 OpenAI 格式：{"data": [{"embedding": [...]}, ...]}
    """

    def __init__(self, clip_api_url: Optional[str] = None, batch_size: int = 8):
        self.clip_api_url = (clip_api_url or "").strip()
        self.batch_size = max(1, int(batch_size))

    def _ensure_url(self):
        if not self.clip_api_url:
            raise RuntimeError(
                "未配置 CLIP API 地址，请在「AI 模型配置」中填写 clip_api_url。"
            )

    def _post_embeddings(self, inputs: list[str], input_type: str) -> list[list[float]]:
        """调用远程 /v1/embeddings，返回归一化后的向量列表。"""
        import requests
        self._ensure_url()
        url = f"{self.clip_api_url.rstrip('/')}/v1/embeddings"
        payload = {
            "input": inputs,
            "model": "clip",
            "input_type": input_type,
        }
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json().get("data") or []
        import math
        embs: list[list[float]] = []
        for item in data:
            vec = item.get("embedding") or []
            n = math.sqrt(sum(x * x for x in vec))
            embs.append([x / n for x in vec] if n > 0 else list(vec))
        return embs

    def encode_images(self, img_paths: list[str]) -> list[list[float]]:
        """读取图片 -> base64 -> 远程编码 -> 返回向量列表（与本地实现签名一致）。"""
        import base64
        result: list[list[float]] = []
        for i in range(0, len(img_paths), self.batch_size):
            batch = img_paths[i: i + self.batch_size]
            b64_list: list[str] = []
            valid_idx: list[int] = []
            for j, p in enumerate(batch):
                try:
                    with open(p, "rb") as f:
                        raw = f.read()
                    b64 = base64.b64encode(raw).decode("ascii")
                    b64_list.append(b64)
                    valid_idx.append(j)
                except Exception as ex:
                    log.warning(f"图片读取失败 {p}: {ex}")
            batch_result: list[list[float]] = [[] for _ in batch]
            if b64_list:
                try:
                    embs = self._post_embeddings(b64_list, input_type="image")
                    dim = len(embs[0]) if embs else 0
                    for k, vi in enumerate(valid_idx):
                        if k < len(embs) and embs[k]:
                            batch_result[vi] = embs[k]
                        else:
                            batch_result[vi] = [0.0] * dim
                except Exception as ex:
                    log.warning(f"远程图片编码失败: {ex}")
                    raise  # 抛出异常，让外层 except 清空 frame_records
            # 补全空向量（维度未知时用 0 长度占位，下游 SQL 插入会跳过）
            result.extend(batch_result)
        return result

    def encode_text(self, texts: list[str]) -> list[list[float]]:
        """远程文本编码 -> 返回向量列表（与本地实现签名一致）。"""
        embs = self._post_embeddings(list(texts), input_type="text")
        dim = len(embs[0]) if embs else 0
        if dim == 0:
            raise RuntimeError("远程文本编码返回空向量")
        result: list[list[float]] = []
        for k in range(len(texts)):
            if k < len(embs) and embs[k]:
                result.append(embs[k])
            else:
                result.append([0.0] * dim)
        return result


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

        # 优先从服务端动态拉取 PG 配置；不可达时回退本地文件
        db_cfg = self._cfg.copy()
        try:
            import requests as _req
            server_url = _read_material_server_url()
            if server_url:
                r = _req.get(f"{server_url.rstrip('/')}/material/config", timeout=3)
                if r.status_code == 200:
                    server_cfg = r.json()
                    s_host = server_cfg.get("host", "")
                    # 服务端返回 localhost 时不可用，跳过（回退本地配置）
                    if s_host and s_host not in ("localhost", "127.0.0.1", "::1"):
                        db_cfg["db_host"] = s_host
                        db_cfg["db_port"] = server_cfg.get("port", db_cfg.get("db_port"))
                        db_cfg["db_name"] = server_cfg.get("database", db_cfg.get("db_name"))
                        db_cfg["db_user"] = server_cfg.get("user", db_cfg.get("db_user"))
                        db_cfg["db_password"] = server_cfg.get("password", db_cfg.get("db_password"))
        except Exception:
            pass  # 回退本地配置

        self._conn = psycopg2.connect(
            host=db_cfg["db_host"], port=db_cfg["db_port"],
            dbname=db_cfg["db_name"], user=db_cfg["db_user"], password=db_cfg["db_password"],
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
                    ("duration_s",    "REAL"),
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

    def get_material_by_id(self, material_id: int) -> dict:
        """按 ID 查询单条素材记录，返回字段字典。"""
        self._connect()
        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, path, file_hash, file_size, mtime, brand, product, model, "
                "category, ai_status, ai_confidence, audio_script, "
                "scene_desc_primary, scene_desc_secondary, "
                "COALESCE(share_name, split_part(path, '/', 1)) AS shared_folder "
                "FROM materials WHERE id = %s",
                (material_id,)
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return {
                    "id": row[0], "path": row[1], "file_hash": row[2],
                    "file_size": row[3], "mtime": row[4], "brand": row[5],
                    "product": row[6], "model": row[7], "category": row[8],
                    "ai_status": row[9], "ai_confidence": row[10],
                    "audio_script": row[11], "scene_desc_primary": row[12],
                    "scene_desc_secondary": row[13], "shared_folder": row[14],
                }
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
        return {}

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

    def update_material_file_meta(self, material_id: int, *,
                                  file_hash: Optional[str] = None,
                                  file_size: Optional[int] = None,
                                  mtime: Optional[float] = None) -> None:
        """按 material_id 回填文件元信息，避免历史数据缺失 file_size/mtime。"""
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute("""
                UPDATE materials
                   SET file_hash = COALESCE(%s, file_hash),
                       file_size = COALESCE(%s, file_size),
                       mtime     = COALESCE(%s, mtime)
                 WHERE id=%s
            """, (file_hash, file_size, mtime, material_id))
        self._conn.commit()

    def search_by_tags(self, brand: str = None, model: str = None,
                       category: str = None, ai_status: str = None,
                       limit: int = 10000, hash_prefix: str = "",
                       offset: int = 0) -> tuple:
        """按品牌/型号/类别标签模糊查询素材，任何字段留空则不筛选该字段。
        返回 (rows, total)，total 为符合条件的总记录数（不受 limit/offset 影响）。"""
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
        ex_cond, ex_params = _recycle_exclude_cond()
        conds.append(ex_cond)
        params.extend(ex_params)
        where = "WHERE " + " AND ".join(conds)
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM materials {where}", params)
            total = cur.fetchone()[0]
            cur.execute(f"""
                SELECT id, path, filename, media_type, duration_s,
                       brand, product, model, category,
                       COALESCE(ai_status,'pending') AS ai_status,
                       ai_confidence, file_hash, scene_desc_primary, scene_desc_secondary,
                       COALESCE(share_name, split_part(path, '/', 1)) AS shared_folder
                FROM materials
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        self._conn.commit()
        return rows, total

    def search_by_keyword(self, keyword: str, limit: int = 100,
                          file_type: str = "", brand: str = "",
                          model: str = "", category: str = "",
                          ai_status: str = "", offset: int = 0) -> tuple:
        """关键词模糊搜索：对文件名/画面描述/品牌/型号/路径做 ILIKE 匹配。
        返回 (rows, total)。"""
        self._connect()
        conds: list = []
        params: list = []
        kw_like = f"%{keyword}%"
        conds.append("""(
            filename ILIKE %s OR
            scene_desc_primary ILIKE %s OR
            scene_desc_secondary ILIKE %s OR
            brand ILIKE %s OR
            model ILIKE %s OR
            product ILIKE %s OR
            category ILIKE %s OR
            path ILIKE %s)""")
        params.extend([kw_like] * 8)
        if file_type:
            conds.append("media_type = %s")
            params.append(file_type)
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
        ex_cond, ex_params = _recycle_exclude_cond()
        conds.append(ex_cond)
        params.extend(ex_params)
        where = "WHERE " + " AND ".join(conds)
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM materials {where}", params)
            total = cur.fetchone()[0]
            cur.execute(f"""
                SELECT id, path, filename, media_type, duration_s,
                       brand, product, model, category,
                       COALESCE(ai_status,'pending') AS ai_status,
                       ai_confidence, file_hash, scene_desc_primary, scene_desc_secondary,
                       COALESCE(share_name, split_part(path, '/', 1)) AS shared_folder
                FROM materials
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        self._conn.commit()
        return rows, total

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

    def delete_material_by_id(self, material_id: int) -> None:
        """从数据库中完全删除指定 id 的素材及其对应的所有视频帧记录。"""
        self._connect()
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM frames WHERE material_id = %s", (material_id,))
            cur.execute("DELETE FROM materials WHERE id = %s", (material_id,))
        self._conn.commit()

    def list_materials(self, path_prefix: str = "", limit: int = 10000,
                       offset: int = 0, ai_status: Optional[str] = None,
                       hash_prefix: str = "", media_type: Optional[str] = None,
                       brand: str = "", scene_desc: str = "",
                       conf_filter: str = "", product: str = "") -> tuple:
        """返回 (rows, total)，total 为符合条件的总记录数。"""
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
        ex_cond, ex_params = _recycle_exclude_cond()
        conds.append(ex_cond)
        params.extend(ex_params)

        where = "WHERE " + " AND ".join(conds)
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM materials {where}", params)
            total = cur.fetchone()[0]
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
            """, params + [limit, offset])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        self._conn.commit()
        return rows, total

    def get_stats(self) -> dict:
        """返回 {total, pending, analyzed, failed}"""
        self._connect()
        try:
            ex_cond, ex_params = _recycle_exclude_cond()
            with self._conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM materials WHERE {ex_cond}", ex_params)
                total = cur.fetchone()[0]
                cur.execute(
                    "SELECT COALESCE(ai_status,'pending'), COUNT(*) "
                    f"FROM materials WHERE {ex_cond} GROUP BY 1",
                    ex_params
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
        # Auto-resolve ffmpeg path if not explicitly configured
        if not self.cfg.get("ffmpeg_path"):
            try:
                from utils.platform_utils import find_ffmpeg
                resolved = find_ffmpeg()
                if resolved and os.path.isfile(resolved):
                    self.cfg["ffmpeg_path"] = resolved
            except Exception:
                pass
        self._db = _MaterialDB(self.cfg)
        self._encoder = _ClipEncoder(
            clip_api_url=_read_clip_api_url(),
            batch_size=self.cfg.get("batch_size", 8),
        )

    def to_local_path(self, path: str) -> str:
        return to_local_path(path, self.nas_root)

    def to_relative_path(self, path: str) -> str:
        return to_relative_path(path, self.nas_root)

    def _log(self, msg: str):
        self._cb(msg)

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
                    try:
                        if _should_skip_path(entry.path):
                            continue
                    except Exception:
                        continue
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
                       conf_filter: str = "", product: str = "") -> tuple:
        return self._db.list_materials(
            path_prefix, limit, offset, ai_status, hash_prefix, media_type,
            brand=brand, scene_desc=scene_desc, conf_filter=conf_filter, product=product
        )

    def search_by_tags(self, brand: str = None, model: str = None,
                       category: str = None, ai_status: str = None,
                       limit: int = 10000, hash_prefix: str = "",
                       offset: int = 0) -> tuple:
        return self._db.search_by_tags(brand, model, category, ai_status, limit, hash_prefix, offset)

    def search_by_keyword(self, keyword: str, limit: int = 100,
                          file_type: str = "", brand: str = "",
                          model: str = "", category: str = "",
                          ai_status: str = "", offset: int = 0) -> tuple:
        return self._db.search_by_keyword(keyword, limit, file_type, brand, model, category, ai_status, offset)

    def delete_material_by_id(self, material_id: int) -> None:
        self._db.delete_material_by_id(material_id)

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
    filter_path_prefix: Optional[str] = None,
    filter_color: Optional[str] = None,
    cfg: Optional[dict] = None,
    comprehensive: bool = True,
    offset: int = 0,
) -> tuple:
    """
    用文字描述向量检索，返回最相似的 top_k 帧记录（含来源文件路径）。
    可附加 brand / category / file_hash / color 筛选。
    颜色维度：materials 表无独立颜色列，filter_color 对画面描述/文件名做 ILIKE 匹配，
    支持逗号/空格分隔多个颜色（任一命中即通过）。
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
            b = filter_brand.strip()
            if b:
                conditions.append("COALESCE(f.brand,'') ILIKE %s")
                params.append(f"%{b}%")
        if filter_category:
            c = filter_category.strip()
            if c:
                conditions.append("(COALESCE(f.category,'') ILIKE %s OR COALESCE(f.product,'') ILIKE %s)")
                params.extend([f"%{c}%", f"%{c}%"])
        if filter_hash:
            conditions.append("m.file_hash ILIKE %s")
            params.append(filter_hash.strip() + "%")
        if filter_path_prefix:
            prefix = to_relative_path(filter_path_prefix, cfg.get("nas_root", ""))
            conditions.append("m.path LIKE %s")
            params.append(prefix.rstrip("/") + "%")
        if filter_color:
            colors = [c.strip() for c in filter_color.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if c.strip()]
            if colors:
                color_ors = []
                for col in colors:
                    like = f"%{col}%"
                    color_ors.append(
                        "(COALESCE(m.scene_desc_primary,'') ILIKE %s OR "
                        " COALESCE(m.scene_desc_secondary,'') ILIKE %s OR "
                        " COALESCE(m.filename,'') ILIKE %s)"
                    )
                    params.extend([like, like, like])
                conditions.append("(" + " OR ".join(color_ors) + ")")
        ex_cond, ex_params = _recycle_exclude_cond("m")
        conditions.append(ex_cond)
        params.extend(ex_params)
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
            LIMIT %s OFFSET %s
        """
        params = [query_vec] + params + [top_k, offset]
        with db._conn.cursor() as cur:
            count_sql = f"""
                SELECT COUNT(*) FROM frames f
                JOIN materials m ON m.id = f.material_id
                WHERE {where}
            """
            cur.execute(count_sql, [query_vec] + params[1:-2] if text_score_parts else params[:-2])
            total = cur.fetchone()[0]
            cur.execute(sql, params)
            rows = cur.fetchall()
        result = [
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
        return result, total
    finally:
        db.close()


def search_by_image(
    image_path: str, top_k: int = 20, cfg: Optional[dict] = None
) -> list[dict]:
    """以图搜视频帧，返回同 search_by_text 的结构。"""
    if cfg is None:
        cfg = _load_config()
    import numpy as np
    encoder = _ClipEncoder(clip_api_url=_read_clip_api_url(), batch_size=1)
    embs = encoder.encode_images([image_path])
    if not embs:
        return []
    query_vec = np.array(embs[0], dtype="float32")

    db = _MaterialDB(cfg)
    try:
        db._connect()
        ex_cond, ex_params = _recycle_exclude_cond("m")
        with db._conn.cursor() as cur:
            cur.execute(f"""
                SELECT m.id, m.path, m.filename, f.ts_s,
                       f.brand, f.product, f.model, f.category,
                       1 - (f.embedding <=> %s) AS score,
                       m.file_hash, m.scene_desc_primary, m.scene_desc_secondary
                FROM frames f
                JOIN materials m ON m.id = f.material_id
                WHERE f.embedding IS NOT NULL AND {ex_cond}
                ORDER BY f.embedding <=> %s
                LIMIT %s
            """, (*ex_params, query_vec, query_vec, top_k))
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

    p_srch = sub.add_parser("search", help="文字检索")
    p_srch.add_argument("query", help="搜索描述词")
    p_srch.add_argument("--top-k", type=int, default=10)
    p_srch.add_argument("--brand", default=None)

    args = parser.parse_args()

    if args.cmd == "search":
        results, _total = search_by_text(args.query, top_k=args.top_k, filter_brand=args.brand)
        for r in results:
            ts = f"@{r['ts_s']:.1f}s" if r["ts_s"] else ""
            print(f"[{r['score']:.3f}] {r['filename']}{ts}  {r['brand']} {r['model']}")
            print(f"         {r['path']}")

    else:
        parser.print_help()
