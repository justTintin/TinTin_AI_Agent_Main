# -*- coding: utf-8 -*-
"""
视频AI智能重命名页面
选择文件夹 → 扫描视频 → 抽帧分析 → AI识别产品信息 → 按规则重命名
命名规则: 品牌_品类_型号_视频日期_视频分辨率_横竖屏
"""
import os
import re
import json
import base64
import datetime
import traceback

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QProgressBar, QMessageBox, QWidget, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QSpinBox, QDialog, QDialogButtonBox, QScrollArea, QSizePolicy,
    QComboBox, QSlider
)
from PySide6.QtCore import Signal, QThread, Qt, QUrl, QTimer
from utils.base_worker import BaseWorker
from PySide6.QtGui import QColor, QFont
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from utils.logger_utils import log

# ─────────────────────────────────────────────
#  常量 / 知识库
# ─────────────────────────────────────────────
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv',
                    '.webm', '.m4v', '.ts', '.mts', '.rmvb', '.3gp'}

KNOWN_BRANDS = [
    "logitech", "罗技", "razer", "雷蛇", "corsair", "海盗船",
    "steelseries", "赛睿", "hyperx", "cherry", "樱桃", "filco",
    "leopold", "iqunix", "nuphy", "keychron", "ducky", "varmilo", "阿米洛",
    "apple", "苹果", "samsung", "三星", "xiaomi", "小米",
    "huawei", "华为", "lenovo", "联想", "asus", "华硕",
    "msi", "微星", "zowie", "rog", "benq", "coolermaster",
    "glorious", "endgame", "pulsar", "xtrfy", "fnatic", "alienware",
    "anker", "安克", "hp", "惠普", "dell", "戴尔", "roccat",
]

KNOWN_CATEGORIES = {
    "鼠标": ["mouse", "鼠标"],
    "键盘": ["keyboard", "键盘", "kbd"],
    "手机": ["phone", "手机", "mobile", "smartphone", "iphone"],
    "耳机": ["headset", "earphone", "headphone", "耳机", "earbuds", "airpods"],
    "显示器": ["monitor", "display", "显示器"],
    "鼠标垫": ["mousepad", "pad", "鼠标垫", "deskmat"],
    "键鼠套装": ["combo", "kit", "套装"],
}


# ─────────────────────────────────────────────
#  模块级辅助函数
# ─────────────────────────────────────────────
def _parse_existing_filename(filename: str) -> dict:
    """
    从已有文件名中提取命名规则字段，返回 dict。
    key 可能包含: brand, category, resolution, orientation, date
    """
    result = {}
    name_no_ext = os.path.splitext(filename)[0]
    lower = name_no_ext.lower()

    # 分辨率: 1920x1080 / 3840×2160 / 1080p
    res_match = re.search(r'(\d{3,4})[xX×](\d{3,4})', name_no_ext)
    if res_match:
        w, h = int(res_match.group(1)), int(res_match.group(2))
        result['resolution'] = f"{w}x{h}"
        result['orientation'] = '横屏' if w >= h else '竖屏'

    # 横竖屏关键词
    if '横屏' in name_no_ext or 'landscape' in lower:
        result['orientation'] = '横屏'
    elif '竖屏' in name_no_ext or 'portrait' in lower:
        result['orientation'] = '竖屏'

    # 日期: YYYYMMDD / YYYY-MM-DD / YYYY_MM_DD
    date_match = re.search(r'(20\d{2})[_\-]?(\d{2})[_\-]?(\d{2})', name_no_ext)
    if date_match:
        result['date'] = f"{date_match.group(1)}{date_match.group(2)}{date_match.group(3)}"

    # 品牌
    for brand in KNOWN_BRANDS:
        if brand.lower() in lower:
            result['brand'] = brand
            break

    # 品类
    for cat, keywords in KNOWN_CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in lower:
                result['category'] = cat
                break
        if 'category' in result:
            break

    return result


def _get_video_meta(video_path: str) -> dict:
    """使用 cv2 读取视频分辨率和横竖屏。"""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {}
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if w > 0 and h > 0:
            return {
                'resolution': f"{w}x{h}",
                'orientation': '横屏' if w >= h else '竖屏'
            }
    except Exception as e:
        log.warning(f"cv2 read video meta failed: {e}")
    return {}


def _extract_keyframes_b64(video_path: str, num_frames: int = 4) -> list:
    """抽取关键帧，返回 base64 编码的 JPEG 列表。
    跳过视频头尾 10%（片头/片尾），在 10%-90% 范围内均匀采样，
    确保抽到产品整体外观展示帧。
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return []

        # 第 0 帧（封面帧）可能直接标注了产品型号，必须优先采样
        # 剩余帧在 10%-90% 范围内均匀分布，覆盖产品展示段
        remaining = max(num_frames - 1, 0)
        ratios = [0.0]  # 始终包含第一帧
        if remaining > 0:
            start_ratio = 0.10
            end_ratio   = 0.90
            ratios += [
                start_ratio + (end_ratio - start_ratio) * i / (remaining + 1)
                for i in range(1, remaining + 1)
            ]

        keyframes_b64 = []
        for r in ratios:
            frame_idx = int(total_frames * r)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                fh, fw = frame.shape[:2]
                max_size = 800  # 提高分辨率以便识别产品型号细节
                if fh > max_size or fw > max_size:
                    if fh > fw:
                        nh, nw = max_size, int(fw * max_size / fh)
                    else:
                        nh, nw = int(fh * max_size / fw), max_size
                    frame = cv2.resize(frame, (nw, nh))
                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if ok:
                    keyframes_b64.append(base64.b64encode(buf).decode('utf-8'))
        cap.release()
        return keyframes_b64
    except Exception as e:
        log.warning(f"Extract keyframes failed for {video_path}: {e}")
        return []


def _extract_path_info(full_path: str, folder_root: str) -> dict:
    """从完整路径提取品牌/品类/型号。先查选中文件夹名及上级目录，再查子目录。"""
    result = {'brand': 'unknown', 'category': 'unknown', 'model': 'unknown'}
    try:
        # 1. 从选中文件夹的绝对路径向上提取（文件夹名最可靠）
        path_text = ""
        if folder_root:
            abs_root = os.path.abspath(folder_root).replace("\\", "/")
            dirs_above = [d for d in abs_root.split("/") if d]
            # 取选中文件夹名 + 上级目录名
            path_text = " ".join(dirs_above[-3:])  # 最后3层

        # 2. 也检查子目录路径作为补充
        if full_path:
            rel = os.path.relpath(full_path, folder_root) if folder_root else ""
            sub_parts = [p.strip() for p in rel.replace("\\", "/").split("/") if p.strip()][:-1]
            if sub_parts:
                path_text += " " + " ".join(sub_parts)

        path_text = path_text.strip()
        if not path_text:
            return result

        # 品牌匹配
        for brand in KNOWN_BRANDS:
            if brand.lower() in path_text.lower():
                result['brand'] = brand
                break

        # 品类匹配
        for cat_name, keywords in KNOWN_CATEGORIES.items():
            for kw in keywords:
                if kw.lower() in path_text.lower():
                    result['category'] = cat_name
                    break
            if result['category'] != 'unknown':
                break

        # 型号提取：字母+数字组合 (M304, G502, MX3, RX7800XT 等)
        model_match = re.search(r'\b([A-Z]{1,4}[\s_-]?\d{2,5}[A-Za-z]?)\b', path_text)
        if model_match:
            result['model'] = model_match.group(1).replace(" ", "").replace("_", "")
    except Exception:
        pass
    return result


def _build_new_filename(ai_info: dict, meta: dict, parsed: dict,
                        original_path: str, path_info: dict = None) -> str:
    """
    格式: 品牌_品类_型号_日期_分辨率_横竖屏.ext
    品牌/品类/型号全部来自视觉AI结果。
    """
    ext = os.path.splitext(original_path)[1]

    try:
        mtime = os.path.getmtime(original_path)
        fs_date = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
    except Exception:
        fs_date = "unknown"

    def clean(v):
        v = str(v or "").strip()
        return v if v and v.lower() not in ("unknown", "none", "") else "unknown"

    brand      = clean(ai_info.get('brand'))
    category   = clean(ai_info.get('category'))
    model      = clean(ai_info.get('model'))
    date_val   = parsed.get("date") or fs_date
    resolution = meta.get("resolution")  or parsed.get("resolution")  or "unknown"
    orientation= meta.get("orientation") or parsed.get("orientation") or "unknown"

    parts = [brand, category, model, date_val, resolution, orientation]
    base = "_".join(parts)
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', base)
    base = base.strip("_. ")
    return base + ext


def _ensure_unique_path(new_path: str) -> str:
    """如果新路径已存在，则在文件名后追加 _2, _3, ..."""
    if not os.path.exists(new_path):
        return new_path
    base, ext = os.path.splitext(new_path)
    counter = 2
    while True:
        candidate = f"{base}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


# ─────────────────────────────────────────────
#  多帧结果聚合（投票 + 权重）
# ─────────────────────────────────────────────
def _aggregate_frame_results(results: list) -> tuple:
    """
    对多帧独立识别结果进行多数投票聚合。
    每个字段（brand/category/model）选出频率最高的非-unknown 值，
    并计算置信度（该值出现帧数 / 总帧数）。
    若全部为 unknown 则保留 unknown，置信度 0。
    返回 (ai_info_dict, conf_dict)。
    """
    from collections import Counter
    total = len(results)

    def top_value(counter: Counter):
        without_unk = {k: v for k, v in counter.items() if k.lower() != 'unknown'}
        if without_unk:
            best = max(without_unk, key=without_unk.get)
            return best, without_unk[best] / total
        return 'unknown', 0.0

    brand_cnt    = Counter(r.get('brand',    'unknown') for r in results)
    category_cnt = Counter(r.get('category', 'unknown') for r in results)
    model_cnt    = Counter(r.get('model',    'unknown') for r in results)

    brand,    b_conf = top_value(brand_cnt)
    category, c_conf = top_value(category_cnt)
    model,    m_conf = top_value(model_cnt)

    return (
        {'brand': brand, 'category': category, 'model': model},
        {
            'brand_conf':    b_conf,
            'category_conf': c_conf,
            'model_conf':    m_conf,
            'frame_count':   total,
            'brand_votes':    dict(brand_cnt),
            'category_votes': dict(category_cnt),
            'model_votes':    dict(model_cnt),
        },
    )


# ─────────────────────────────────────────────
#  后台分析线程
# ─────────────────────────────────────────────
class VideoAnalyzeWorker(BaseWorker):
    """逐个分析文件夹中的视频，发射分析结果信号。"""
    video_analyzed = Signal(int, dict)    # (row_index, result_dict)
    progress       = Signal(int, int, str) # (current, total, msg)
    log_sig        = Signal(str)           # real-time log line for global panel
    log_row_sig    = Signal(int, str)      # (row_idx, line) — per-video log
    finished       = Signal()
    error          = Signal(str)

    def __init__(self, video_files: list, api_url: str,
                 api_key: str, model: str, num_frames: int = 4,
                 folder_path: str = "", vision_model: str = "",
                 vision_api_url: str = ""):
        super().__init__()
        self.video_files     = video_files
        self.api_url         = (api_url or "").rstrip("/")
        self.api_key         = api_key or ""
        self.model           = model or ""
        self.vision_model    = (vision_model or "").strip()
        # 视觉 API 地址：未填则回退到文本模型地址（兼容云端视觉模型）
        self.vision_api_url  = (vision_api_url or api_url or "").rstrip("/")
        self.num_frames      = num_frames
        self._folder_path    = folder_path or ""
        self._abort          = False

    def abort(self):
        self._abort = True

    def _emit_log(self, line: str):
        """同时向全局日志面板和当前行缓存发送日志。"""
        self.log_sig.emit(line)
        self.log_row_sig.emit(self._cur_row, line)

    def run(self):
        total = len(self.video_files)
        self._cur_row = -1
        self.log_sig.emit(f"开始分析，共 {total} 个视频  |  视觉模型: {self.vision_model or '无'}")

        for idx, fpath in enumerate(self.video_files):
            if self._abort:
                self.log_sig.emit("── 已停止 ──")
                break
            self._cur_row = idx
            fname = os.path.basename(fpath)
            self.progress.emit(idx + 1, total, f"分析中 ({idx+1}/{total}): {fname}")
            self.log_sig.emit(f"── [{idx+1}/{total}] {fname}")
            self.log_row_sig.emit(idx, f"文件: {fname}")
            try:
                result = self._analyze_one(fpath)
                self.video_analyzed.emit(idx, result)
            except Exception as e:
                log.warning(f"Analyze video failed [{fname}]: {e}")
                self._emit_log(f"  ✗ 未捕获异常: {type(e).__name__}: {e}")
                result = self._fallback_result(fpath, str(e))
                self.video_analyzed.emit(idx, result)

        self.log_sig.emit("── 全部分析完成 ──")
        self.finished.emit()

    def _analyze_one(self, fpath: str) -> dict:
        fname = os.path.basename(fpath)

        # 1. 解析原文件名中已有信息
        parsed = _parse_existing_filename(fname)

        # 2. 视频元数据（分辨率/方向）
        meta = _get_video_meta(fpath)

        # 3. 文件日期
        try:
            mtime = os.path.getmtime(fpath)
            fs_date = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
        except Exception:
            fs_date = parsed.get("date", "unknown")
        if fs_date and fs_date != "unknown":
            parsed["date"] = fs_date

        # 4. 视觉分析 — 逐帧独立调用，投票聚合
        ai_info   = {'brand': 'unknown', 'category': 'unknown', 'model': 'unknown'}
        conf_info = {'brand_conf': 0.0, 'category_conf': 0.0, 'model_conf': 0.0,
                     'frame_count': 0, 'brand_votes': {}, 'category_votes': {}, 'model_votes': {}}
        self._emit_log(
            f"  视觉API: {self.vision_api_url or '(未配置)'}  "
            f"视觉模型: {self.vision_model or '(未选择)'}"
        )

        if self.vision_model and self.vision_api_url:
            import requests as req
            vision_ok = False
            try:
                self._emit_log(f"  抽帧中… num_frames={self.num_frames}")
                kfs = _extract_keyframes_b64(fpath, self.num_frames)
                log.info(f"[{fname}] 抽帧完成 frames={len(kfs)}")
                if kfs:
                    self._emit_log(f"  抽帧完成: {len(kfs)} 帧，开始逐帧分析…")
                    frame_results = []
                    for i, kf in enumerate(kfs):
                        if self._abort:
                            break
                        try:
                            r = self._call_vision_llm_single(i + 1, len(kfs), kf, req)
                            frame_results.append(r)
                            self._emit_log(
                                f"  帧{i+1:02d}/{len(kfs)}: "
                                f"品牌={r['brand']}  品类={r['category']}  型号={r['model']}"
                            )
                        except Exception as e:
                            self._emit_log(f"  帧{i+1:02d} ✗ {type(e).__name__}: {e}")
                    if frame_results:
                        ai_info, conf_info = _aggregate_frame_results(frame_results)
                        vision_ok = any(v.lower() != 'unknown' for v in ai_info.values())
                        log.info(f"[{fname}] 聚合结果: {ai_info} 置信度: {conf_info}")
                        self._emit_log(
                            f"  聚合({conf_info['frame_count']}帧): "
                            f"品牌={ai_info['brand']}({conf_info['brand_conf']:.0%})  "
                            f"品类={ai_info['category']}({conf_info['category_conf']:.0%})  "
                            f"型号={ai_info['model']}({conf_info['model_conf']:.0%})"
                        )
                        # 输出详细投票分布
                        for field, votes in [
                            ('品牌', conf_info['brand_votes']),
                            ('品类', conf_info['category_votes']),
                            ('型号', conf_info['model_votes']),
                        ]:
                            detail = '  '.join(f"{k}×{v}" for k, v in
                                               sorted(votes.items(), key=lambda x: -x[1]))
                            self._emit_log(f"    {field}分布: {detail}")
                    else:
                        self._emit_log("  ✗ 所有帧分析均失败")
                else:
                    log.warning(f"[{fname}] 抽帧返回空列表")
                    self._emit_log("  ✗ 抽帧返回空列表，跳过视觉分析")
            except Exception as e:
                log.warning(f"[{fname}] 视觉分析异常: {type(e).__name__}: {e}")
                self._emit_log(f"  ✗ 视觉分析异常: {type(e).__name__}: {e}")

            if not vision_ok:
                self._emit_log("  视觉未识别，结果为 unknown")
        else:
            self._emit_log("  ✗ 未配置视觉模型或API地址，跳过分析")

        # 5. 生成新文件名
        new_name = _build_new_filename(ai_info, meta, parsed, fpath)

        resolution  = meta.get('resolution')  or parsed.get('resolution')  or 'unknown'
        orientation = meta.get('orientation') or parsed.get('orientation') or 'unknown'

        ai_ok = any(v.lower() != 'unknown' for v in ai_info.values())
        status_text = '已分析 ✓' if ai_ok else '未识别 ⚠'
        self._emit_log(
            f"  ✔ 最终: 品牌={ai_info.get('brand','?')}  品类={ai_info.get('category','?')}  "
            f"型号={ai_info.get('model','?')}  → {new_name}"
        )

        return {
            'original_path': fpath,
            'original_name': fname,
            'new_name':      new_name,
            'brand':         ai_info.get('brand',    'unknown'),
            'category':      ai_info.get('category', 'unknown'),
            'model_name':    ai_info.get('model',    'unknown'),
            'resolution':    resolution,
            'orientation':   orientation,
            'date':          parsed.get('date', fs_date),
            'status':        status_text,
            'error':         False,
            'brand_conf':    conf_info.get('brand_conf',    0.0),
            'category_conf': conf_info.get('category_conf', 0.0),
            'model_conf':    conf_info.get('model_conf',    0.0),
            'frame_count':   conf_info.get('frame_count',   0),
        }

    def _fallback_result(self, fpath: str, err_msg: str) -> dict:
        fname  = os.path.basename(fpath)
        parsed = _parse_existing_filename(fname)
        meta   = _get_video_meta(fpath)
        try:
            mtime  = os.path.getmtime(fpath)
            date_s = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
        except Exception:
            date_s = parsed.get("date", "unknown")
        parsed["date"] = date_s
        new_name = _build_new_filename({'brand':'unknown','category':'unknown','model':'unknown'},
                                       meta, parsed, fpath)
        return {
            'original_path': fpath,
            'original_name': fname,
            'new_name':      new_name,
            'brand':         'unknown',
            'category':      'unknown',
            'model_name':    'unknown',
            'resolution':    meta.get('resolution', 'unknown'),
            'orientation':   meta.get('orientation','unknown'),
            'date':          date_s,
            'status':        f'⚠ 失败: {err_msg[:50]}',
            'error':         True,
            'brand_conf':    0.0,
            'category_conf': 0.0,
            'model_conf':    0.0,
            'frame_count':   0,
        }

    def _call_vision_llm_single(self, frame_num: int, total: int,
                                kf_b64: str, req) -> dict:
        """调用视觉模型分析单帧，返回 {'brand':..., 'category':..., 'model':...}。"""
        system_prompt = (
            "你是专业的消费电子产品视觉识别专家。\n"
            "这是视频中的一帧截图。通过产品外观特征（形状/轮廓/设计语言/LOGO/文字标识等）\n"
            "推断品牌、品类和型号。\n"
            "只返回 JSON，不要任何其他内容：\n"
            "{\n"
            "  \"brand\": \"品牌名（Logitech/Razer/Apple/小米等；无法识别填 unknown）\",\n"
            "  \"category\": \"品类（鼠标/键盘/手机/耳机/显示器等；无法识别填 unknown）\",\n"
            "  \"model\": \"最可能的型号（G502/MX Master 3/iPhone 15 Pro等；无法判断填 unknown）\"\n"
            "}"
        )
        url = f"{self.vision_api_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text",
                     "text": f"这是视频第 {frame_num}/{total} 帧，请识别画面中的产品品牌、品类和型号："},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{kf_b64}"}},
                ]},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        }
        self._emit_log(f"    → 帧{frame_num}  POST {self.vision_api_url}")
        res = req.post(url, json=payload, headers=headers, timeout=60)
        self._emit_log(f"    ← HTTP {res.status_code}")
        if res.status_code != 200:
            self._emit_log(f"    ✗ 错误: {res.text[:150]}")
            raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
        raw = res.json()["choices"][0]["message"]["content"].strip()
        self._emit_log(f"    原始: {raw[:100]}")
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE).strip()
        m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if m:
            raw = m.group(0)
        data = json.loads(raw)

        def clean(v):
            v = str(v or "").strip()
            return v if v and v.lower() not in ("none", "") else "unknown"

        return {
            'brand':    clean(data.get('brand')),
            'category': clean(data.get('category')),
            'model':    clean(data.get('model')),
        }



# ─────────────────────────────────────────────
#  单帧分析线程
# ─────────────────────────────────────────────
class FrameAnalysisThread(BaseWorker):
    """抽取视频指定位置的单帧并调用视觉模型分析。"""
    result_ready = Signal(dict)   # {'brand':..., 'category':..., 'model':...} or {'error':...}
    log_ready    = Signal(str)

    def __init__(self, fpath: str, pos_ms: int,
                 vision_model: str, vision_api_url: str, api_key: str):
        super().__init__()
        self.fpath          = fpath
        self.pos_ms         = pos_ms
        self.vision_model   = vision_model
        self.vision_api_url = (vision_api_url or "").rstrip("/")
        self.api_key        = api_key or ""

    def run(self):
        import cv2
        import requests as req
        try:
            self.log_ready.emit("抽帧中…")
            cap = cv2.VideoCapture(self.fpath)
            cap.set(cv2.CAP_PROP_POS_MSEC, self.pos_ms)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                self.result_ready.emit({'error': '无法读取该位置的帧'})
                return
            fh, fw = frame.shape[:2]
            max_size = 800
            if fh > max_size or fw > max_size:
                if fh > fw:
                    nh, nw = max_size, int(fw * max_size / fh)
                else:
                    nh, nw = int(fh * max_size / fw), max_size
                frame = cv2.resize(frame, (nw, nh))
            ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                self.result_ready.emit({'error': '帧编码失败'})
                return
            kf_b64 = base64.b64encode(buf).decode('utf-8')
            self.log_ready.emit("发送至视觉模型…")
            result = self._call_vision(kf_b64, req)
            self.result_ready.emit(result)
        except Exception as e:
            self.result_ready.emit({'error': f'{type(e).__name__}: {e}'})

    def _call_vision(self, kf_b64: str, req) -> dict:
        system_prompt = (
            "你是专业的消费电子产品视觉识别专家。通过产品外观特征识别品牌、品类和型号。"
            "只返回 JSON，格式：{\"brand\":\"...\",\"category\":\"...\",\"model\":\"...\"}"
            "无法识别时对应字段填 unknown。"
        )
        url = f"{self.vision_api_url}/v1/chat/completions"
        payload = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "请识别这一帧中的产品品牌、品类和型号："},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{kf_b64}"}}
                ]},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        res = req.post(url, json=payload, headers=headers, timeout=60)
        if res.status_code != 200:
            raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
        raw = res.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE).strip()
        m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if m:
            raw = m.group(0)
        data = json.loads(raw)
        def clean(v):
            v = str(v or "").strip()
            return v if v and v.lower() not in ("none", "") else "unknown"
        return {
            'brand':    clean(data.get('brand')),
            'category': clean(data.get('category')),
            'model':    clean(data.get('model')),
        }


# ─────────────────────────────────────────────
#  批量查找替换对话框
# ─────────────────────────────────────────────
class BatchFindReplaceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔄 批量查找替换（新文件名）")
        self.setMinimumWidth(420)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: #e5e7eb; }
            QLabel  { color: #9ca3af; font-size: 13px; }
            QLineEdit {
                background-color: #2c2c2e;
                border: 1px solid #3a3a3c;
                border-radius: 5px;
                padding: 5px 8px;
                color: #ffffff;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3b82f6;
                color: white; border: none;
                padding: 7px 18px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton#cancel_btn {
                background-color: transparent;
                color: #d1d5db;
                border: 1px solid #4b5563;
            }
            QPushButton#cancel_btn:hover { background-color: rgba(255,255,255,0.06); }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("在所有已生成的新文件名中批量查找并替换："))

        row_find = QHBoxLayout()
        row_find.addWidget(QLabel("查找："))
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("输入要查找的文字...")
        row_find.addWidget(self.find_input, 1)
        layout.addLayout(row_find)

        row_replace = QHBoxLayout()
        row_replace.addWidget(QLabel("替换为："))
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("输入替换后的文字（留空则删除）")
        row_replace.addWidget(self.replace_input, 1)
        layout.addLayout(row_replace)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("✅ 应用替换")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("cancel_btn")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def get_values(self):
        return self.find_input.text(), self.replace_input.text()


# ─────────────────────────────────────────────
#  视频播放 + 单帧分析对话框
# ─────────────────────────────────────────────
class VideoPlayerDialog(QDialog):
    """
    双击视频行弹出的播放器窗口。
    左：QMediaPlayer 播放 + 时间轴拖拽
    右：分析当前帧 / 编辑字段 / 应用重命名
    """

    def __init__(self, fpath: str, row_idx: int,
                 vision_model: str, vision_api_url: str, api_key: str,
                 page_ref, parent=None):
        super().__init__(parent)
        self.fpath           = fpath
        self.row_idx         = row_idx
        self.vision_model    = vision_model
        self.vision_api_url  = vision_api_url
        self.api_key         = api_key
        self.page_ref        = page_ref
        self._duration       = 0
        self._slider_dragging = False
        self._analysis_thread = None
        self._pending_rename  = None

        self._setup_ui()
        self._setup_player()

    # ── UI ──────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle(f"视频预览 — {os.path.basename(self.fpath)}")
        self.resize(1040, 640)
        self.setObjectName("videoPlayerDialog")

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # ── Left: video ──────────────────────────
        left_w = QWidget()
        left_w.setStyleSheet("background: #000;")
        left_v = QVBoxLayout(left_w)
        left_v.setContentsMargins(0, 0, 0, 8)
        left_v.setSpacing(6)

        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_v.addWidget(self.video_widget, 1)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        left_v.addWidget(self.slider)

        ctrl_h = QHBoxLayout()
        ctrl_h.setContentsMargins(12, 0, 12, 0)
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(90)
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl_h.addWidget(self.btn_play)
        ctrl_h.addStretch()
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setStyleSheet("color: #9ca3af; font-size: 12px; font-family: monospace;")
        ctrl_h.addWidget(self.lbl_time)
        left_v.addLayout(ctrl_h)

        main_h.addWidget(left_w, 1)

        # Vertical divider
        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet("QFrame { color: #2d2d2d; }")
        div.setFixedWidth(1)
        main_h.addWidget(div)

        # ── Right: analysis panel ────────────────
        right_w = QWidget()
        right_w.setFixedWidth(270)
        right_w.setStyleSheet("background-color: #1c1c1e;")
        right_v = QVBoxLayout(right_w)
        right_v.setContentsMargins(14, 14, 14, 14)
        right_v.setSpacing(8)

        hint = QLabel("拖动时间轴选帧，暂停后\n点击按钮识别当前产品：")
        hint.setStyleSheet("color: #6b7280; font-size: 12px;")
        right_v.addWidget(hint)

        can_analyze = bool(self.vision_model and self.vision_api_url)
        self.btn_analyze_frame = QPushButton("🔍 分析这一帧")
        self.btn_analyze_frame.setEnabled(can_analyze)
        if not can_analyze:
            self.btn_analyze_frame.setToolTip("请先在设置中配置视觉模型和 API 地址")
        self.btn_analyze_frame.clicked.connect(self._analyze_current_frame)
        right_v.addWidget(self.btn_analyze_frame)

        self.lbl_frame_status = QLabel("")
        self.lbl_frame_status.setStyleSheet("color: #fbbf24; font-size: 11px;")
        self.lbl_frame_status.setWordWrap(True)
        right_v.addWidget(self.lbl_frame_status)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { color: #2d2d2d; }")
        right_v.addWidget(sep)

        for label_text, attr_name in [
            ("品牌:", "edit_brand"),
            ("品类:", "edit_category"),
            ("型号:", "edit_model"),
        ]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #9ca3af; font-size: 12px;")
            right_v.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText("unknown")
            setattr(self, attr_name, edit)
            right_v.addWidget(edit)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("QFrame { color: #2d2d2d; }")
        right_v.addWidget(sep2)

        lbl_fn = QLabel("新文件名:")
        lbl_fn.setStyleSheet("color: #9ca3af; font-size: 12px;")
        right_v.addWidget(lbl_fn)
        self.edit_filename = QLineEdit()
        self.edit_filename.setPlaceholderText("分析后自动填写，可编辑")
        right_v.addWidget(self.edit_filename)

        # Auto-rebuild filename when fields change
        self.edit_brand.textChanged.connect(self._rebuild_filename)
        self.edit_category.textChanged.connect(self._rebuild_filename)
        self.edit_model.textChanged.connect(self._rebuild_filename)

        right_v.addStretch()

        self.btn_apply_rename = QPushButton("✅ 确认重命名")
        self.btn_apply_rename.setEnabled(False)
        self.btn_apply_rename.clicked.connect(self._apply_rename)
        right_v.addWidget(self.btn_apply_rename)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("close_btn")
        btn_close.clicked.connect(self.reject)
        right_v.addWidget(btn_close)

        main_h.addWidget(right_w)

    # ── Player ──────────────────────────────────
    def _setup_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)

        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(self.fpath)))
        self.player.play()  # auto-start so first frame is visible

    def closeEvent(self, event):
        self.player.stop()
        if self._analysis_thread and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(2000)
        super().closeEvent(event)

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ 暂停")
        else:
            self.btn_play.setText("▶ 播放")

    def _on_duration_changed(self, duration: int):
        self._duration = duration
        self._update_time_label(self.player.position())

    def _on_position_changed(self, pos_ms: int):
        if not self._slider_dragging and self._duration > 0:
            self.slider.setValue(int(pos_ms * 1000 / self._duration))
        self._update_time_label(pos_ms)

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        if self._duration > 0:
            self.player.setPosition(int(self.slider.value() * self._duration / 1000))

    def _on_slider_moved(self, value: int):
        if self._duration > 0:
            self._update_time_label(int(value * self._duration / 1000))

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = ms // 1000
        m, s = divmod(s, 60)
        return f"{m}:{s:02d}"

    def _update_time_label(self, pos_ms: int):
        self.lbl_time.setText(f"{self._fmt_ms(pos_ms)} / {self._fmt_ms(self._duration)}")

    # ── Frame analysis ───────────────────────────
    def _analyze_current_frame(self):
        self.player.pause()
        pos_ms = self.player.position()
        self.btn_analyze_frame.setEnabled(False)
        self.lbl_frame_status.setText("抽帧中…")

        self._analysis_thread = FrameAnalysisThread(
            self.fpath, pos_ms, self.vision_model, self.vision_api_url, self.api_key
        )
        self._analysis_thread.result_ready.connect(self._on_frame_analyzed)
        self._analysis_thread.log_ready.connect(self.lbl_frame_status.setText)
        self._analysis_thread.start()

    def _on_frame_analyzed(self, result: dict):
        self.btn_analyze_frame.setEnabled(True)
        if 'error' in result:
            self.lbl_frame_status.setText(f"✗ {result['error']}")
            return
        self.lbl_frame_status.setText("✓ 分析完成")
        self.edit_brand.setText(result.get('brand', 'unknown'))
        self.edit_category.setText(result.get('category', 'unknown'))
        self.edit_model.setText(result.get('model', 'unknown'))
        self._rebuild_filename()
        self.btn_apply_rename.setEnabled(True)

    def _rebuild_filename(self):
        brand    = self.edit_brand.text().strip() or "unknown"
        category = self.edit_category.text().strip() or "unknown"
        model    = self.edit_model.text().strip() or "unknown"
        ai_info  = {'brand': brand, 'category': category, 'model': model}
        meta     = _get_video_meta(self.fpath)
        fname    = os.path.basename(self.fpath)
        parsed   = _parse_existing_filename(fname)
        try:
            mtime = os.path.getmtime(self.fpath)
            parsed["date"] = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
        except Exception:
            pass
        self.edit_filename.setText(_build_new_filename(ai_info, meta, parsed, self.fpath))
        self.btn_apply_rename.setEnabled(True)

    # ── Rename ───────────────────────────────────
    def _apply_rename(self):
        new_name = self.edit_filename.text().strip()
        if not new_name:
            QMessageBox.warning(self, "文件名为空", "请输入新文件名。")
            return
        folder   = os.path.dirname(self.fpath)
        new_path = _ensure_unique_path(os.path.join(folder, new_name))
        actual_name = os.path.basename(new_path)
        ai_info = {
            'brand':    self.edit_brand.text().strip() or 'unknown',
            'category': self.edit_category.text().strip() or 'unknown',
            'model':    self.edit_model.text().strip() or 'unknown',
        }
        self.player.stop()
        self._pending_rename = (new_path, actual_name, ai_info)
        # Brief delay so the media player releases the file handle on Windows
        QTimer.singleShot(400, self._do_pending_rename)

    def _do_pending_rename(self):
        if not self._pending_rename:
            return
        new_path, actual_name, ai_info = self._pending_rename
        self._pending_rename = None
        try:
            os.rename(self.fpath, new_path)
        except Exception as e:
            QMessageBox.warning(self, "重命名失败", str(e))
            return
        self.page_ref._apply_rename_from_dialog(self.row_idx, actual_name, ai_info)
        self.fpath = new_path
        self.setWindowTitle(f"视频预览 — {actual_name}")
        self.lbl_frame_status.setText(f"✅ 已重命名: {actual_name}")
        self.btn_apply_rename.setEnabled(False)


# ─────────────────────────────────────────────
#  主页面类
# ─────────────────────────────────────────────
from gui.base_page import BasePage


class VideoAiRenamePage(BasePage):
    """视频AI智能重命名页面。"""

    HISTORY_FILENAME = "_rename_history.json"

    def __init__(self, parent_widget, main_win):
        super().__init__(parent_widget, main_win)
        self.main_win      = main_win  # 兼容旧引用
        self.worker        = None
        self.video_files   = []   # list of absolute paths
        self._folder_path  = ""
        self._results      = {}   # row_idx -> result dict
        self._row_logs     = {}   # row_idx -> [log lines]
        self._renamed_count = 0

    # ──────────────────────── UI 构建 ────────────────────────
    def setup(self):
        layout = QVBoxLayout(self.parent_widget)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(10)

        # 标题
        heading = QLabel("🏷️ 视频AI智能重命名")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        desc = QLabel(
            "选择文件夹 → AI 分析视频内容 → 预览新文件名 → 手动调整 → 批量重命名\n"
            "命名规则：品牌_品类_型号_视频日期_视频分辨率_横竖屏"
        )
        desc.setStyleSheet("color: #9ca3af; font-size: 12px; line-height: 1.5;")
        layout.addWidget(desc)

        # ── 文件夹选择行 ──
        row_folder = QHBoxLayout()
        row_folder.setSpacing(8)
        lbl_folder = QLabel("📁 视频文件夹:")
        lbl_folder.setFixedWidth(90)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("选择包含视频文件的文件夹...")
        self.folder_input.setReadOnly(True)
        btn_sel = QPushButton("选择文件夹")
        btn_sel.setObjectName("secondary_button")
        btn_sel.clicked.connect(self._select_folder)
        row_folder.addWidget(lbl_folder)
        row_folder.addWidget(self.folder_input, 1)
        row_folder.addWidget(btn_sel)
        layout.addLayout(row_folder)

        # ── 模型配置行 ──
        row_config = QHBoxLayout()
        row_config.setSpacing(8)

        # 文本模型（只读标签）
        self.lbl_model_info = QLabel("")
        self.lbl_model_info.setStyleSheet("color: #60a5fa; font-size: 12px;")
        row_config.addWidget(self.lbl_model_info)

        # 视觉模型选择下拉框（纯选择，不可手动输入）
        row_config.addWidget(QLabel("视觉:"))
        self.combo_vision_model = QComboBox()
        self.combo_vision_model.setMinimumWidth(180)
        self.combo_vision_model.setToolTip("选择已下载的 Ollama 视觉模型，留空则仅用文本分析")
        self.combo_vision_model.currentIndexChanged.connect(self._on_vision_model_changed)
        row_config.addWidget(self.combo_vision_model)

        # 刷新按钮：重新读配置并刷新 Ollama 模型列表
        btn_reload_cfg = QPushButton("↺")
        btn_reload_cfg.setFixedWidth(28)
        btn_reload_cfg.setToolTip("刷新配置和 Ollama 已下载模型列表")
        btn_reload_cfg.setObjectName("secondary_button")
        btn_reload_cfg.clicked.connect(self._load_llm_config)
        row_config.addWidget(btn_reload_cfg)
        row_config.addStretch()
        row_config.addWidget(QLabel("抽帧数:"))
        self.spin_frames = QSpinBox()
        self.spin_frames.setRange(1, 16)
        self.spin_frames.setValue(10)
        self.spin_frames.setToolTip("每个视频抽取多少帧（每帧独立调用视觉模型，结果投票聚合）")
        self.spin_frames.setFixedWidth(60)
        row_config.addWidget(self.spin_frames)
        layout.addLayout(row_config)

        # 从主窗口加载 LLM 配置
        self._load_llm_config()

        # ── 操作按钮行 ──
        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        self.btn_analyze = QPushButton("🔍 分析并预览")
        self.btn_analyze.setObjectName("primary_button")
        self.btn_analyze.setToolTip("分析视频内容，预览重命名结果（不修改文件）")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self._start_analyze)
        row_actions.addWidget(self.btn_analyze)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setObjectName("secondary_button")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_analyze)
        row_actions.addWidget(self.btn_stop)

        self.btn_rename = QPushButton("✅ 执行重命名")
        self.btn_rename.setObjectName("action_button")
        self.btn_rename.setToolTip("将勾选的视频按预览的新文件名重命名")
        self.btn_rename.setEnabled(False)
        self.btn_rename.clicked.connect(self._do_rename)
        row_actions.addWidget(self.btn_rename)

        self.btn_undo = QPushButton("↩️ 撤销上次重命名")
        self.btn_undo.setObjectName("secondary_button")
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._undo_rename)
        row_actions.addWidget(self.btn_undo)

        row_actions.addStretch(1)

        self.btn_batch_replace = QPushButton("🔄 批量查找替换")
        self.btn_batch_replace.setObjectName("secondary_button")
        self.btn_batch_replace.setToolTip("在新文件名列中批量查找并替换文字")
        self.btn_batch_replace.setEnabled(False)
        self.btn_batch_replace.clicked.connect(self._batch_find_replace)
        row_actions.addWidget(self.btn_batch_replace)

        btn_check_all = QPushButton("☑ 全选")
        btn_check_all.setObjectName("secondary_button")
        btn_check_all.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_check_all.clicked.connect(lambda: self._set_all_checked(True))
        row_actions.addWidget(btn_check_all)

        btn_uncheck = QPushButton("☐ 全不选")
        btn_uncheck.setObjectName("secondary_button")
        btn_uncheck.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_uncheck.clicked.connect(lambda: self._set_all_checked(False))
        row_actions.addWidget(btn_uncheck)

        layout.addLayout(row_actions)

        # ── 批量设置字段 ──
        row_batch_fix = QHBoxLayout()
        row_batch_fix.setSpacing(8)
        row_batch_fix.addWidget(QLabel("🔧 批量设置:"))
        self.combo_batch_field = QComboBox()
        self.combo_batch_field.addItems(["品牌(AI)", "品类(AI)", "型号(AI)"])
        self.combo_batch_field.setFixedWidth(80)
        self.combo_batch_field.setEnabled(False)
        row_batch_fix.addWidget(self.combo_batch_field)
        self.input_batch_value = QLineEdit()
        self.input_batch_value.setPlaceholderText("输入要统一设置的值（如: 罗技）")
        self.input_batch_value.setEnabled(False)
        row_batch_fix.addWidget(self.input_batch_value, 1)
        self.btn_batch_set = QPushButton("应用")
        self.btn_batch_set.setObjectName("secondary_button")
        self.btn_batch_set.setToolTip("将输入的值批量设置到所选字段")
        self.btn_batch_set.setEnabled(False)
        self.btn_batch_set.clicked.connect(self._batch_set_field)
        row_batch_fix.addWidget(self.btn_batch_set)
        row_batch_fix.addStretch(2)
        layout.addLayout(row_batch_fix)

        # ── 文件列表表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "☑", "#", "原文件名", "新文件名（双击编辑）",
            "分辨率/方向", "日期", "状态", "分析结果", "重分析", "播放"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed);       self.table.setColumnWidth(0, 32)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed);       self.table.setColumnWidth(1, 40)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive); self.table.setColumnWidth(2, 160)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive); self.table.setColumnWidth(4, 110)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive); self.table.setColumnWidth(5, 80)
        hdr.setSectionResizeMode(6, QHeaderView.Interactive); self.table.setColumnWidth(6, 80)
        hdr.setSectionResizeMode(7, QHeaderView.Stretch)
        hdr.setSectionResizeMode(8, QHeaderView.Fixed);       self.table.setColumnWidth(8, 50)
        hdr.setSectionResizeMode(9, QHeaderView.Fixed);       self.table.setColumnWidth(9, 45)

        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        # 双击第 3 列（新文件名）→ 内联编辑；播放按钮（第 9 列）打开播放器
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setMinimumHeight(300)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #232323;
                gridline-color: #2d2d2d;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #9ca3af;
                padding: 5px;
                border: none;
                border-right: 1px solid #3a3a3c;
                font-size: 12px;
                font-weight: bold;
            }
            QTableWidget QLineEdit {
                background-color: #1e293b;
                color: #f0f9ff;
                font-size: 13px;
                border: 1px solid #3b82f6;
                padding: 2px 6px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
        """)
        layout.addWidget(self.table, 1)

        # ── 进度条 + 状态标签 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("请选择文件夹，然后点击「分析并预览」")
        self.status_lbl.setStyleSheet("color: #9ca3af; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        # ── 实时日志面板 ──
        log_header_row = QHBoxLayout()
        lbl_log_title = QLabel("📋 实时日志")
        lbl_log_title.setStyleSheet("color: #6b7280; font-size: 11px;")
        log_header_row.addWidget(lbl_log_title)
        log_header_row.addStretch()
        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.setObjectName("secondary_button")
        btn_clear_log.setFixedWidth(64)
        btn_clear_log.setFixedHeight(20)
        btn_clear_log.setStyleSheet("font-size: 11px; padding: 1px 4px;")
        btn_clear_log.clicked.connect(lambda: self.log_panel.clear())
        log_header_row.addWidget(btn_clear_log)
        layout.addLayout(log_header_row)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFixedHeight(140)
        self.log_panel.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d0d;
                color: #c8c8c8;
                border: 1px solid #2d2d2d;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_panel)

    # ──────────────────────── 配置加载 ────────────────────────
    def _load_llm_config(self):
        """从主窗口 ai_config 加载 LLM 配置，并刷新 Ollama 模型列表。"""
        self._api_url         = ""
        self._api_key         = ""
        self._model           = ""
        self._vision_api_url  = ""
        self._vision_model    = ""
        try:
            cfg = self.main_win.ai_config
            self._api_url        = cfg.get("llm_api_url",       "").strip()
            self._api_key        = cfg.get("llm_api_key",       "").strip()
            self._model          = cfg.get("llm_model",          "").strip()
            self._vision_api_url = cfg.get("llm_vision_api_url","").strip()
            self._vision_model   = cfg.get("llm_vision_model",  "").strip()
            self.lbl_model_info.setText(f"🤖 文本: {self._model}" if self._model else "⚠ 未配置文本模型")
            self.lbl_model_info.setStyleSheet(
                "color: #60a5fa; font-size: 12px;" if self._model else "color: #f87171; font-size: 12px;"
            )
        except Exception:
            self.lbl_model_info.setText("⚠ 无法读取 AI 配置")
            self.lbl_model_info.setStyleSheet("color: #f87171; font-size: 12px;")

        # 刷新视觉模型下拉框：尝试从 Ollama 获取已下载列表
        cur = self._vision_model
        self.combo_vision_model.blockSignals(True)
        self.combo_vision_model.clear()
        self.combo_vision_model.addItem("无（仅文本分析）", userData="")
        try:
            from utils.ollama_manager import OllamaManager
            mgr = OllamaManager.get()
            if mgr.is_running():
                for m in mgr.list_local_models():
                    self.combo_vision_model.addItem(m, userData=m)
        except Exception:
            pass
        # 如果配置里有视觉模型但 Ollama 没列出，手动加一条
        if cur:
            idx = self.combo_vision_model.findData(cur)
            if idx < 0:
                self.combo_vision_model.addItem(cur, userData=cur)
                idx = self.combo_vision_model.count() - 1
            self.combo_vision_model.setCurrentIndex(idx)
        else:
            self.combo_vision_model.setCurrentIndex(0)
        self.combo_vision_model.blockSignals(False)
        self._vision_model = cur

    def _on_vision_model_changed(self, index: int):
        """用户切换视觉模型时，用 userData 更新 self._vision_model（避免显示文字污染）。"""
        self._vision_model = self.combo_vision_model.currentData() or ""

    # ──────────────────────── 文件夹选择 ────────────────────────
    def _select_folder(self):
        path = QFileDialog.getExistingDirectory(
            self.parent_widget, "选择包含视频文件的文件夹", ""
        )
        if not path:
            return
        self._folder_path = path
        self.folder_input.setText(path)
        self._scan_folder(path)

    def load_folder(self, path):
        """供其它页面（如素材管理）跳转时直接载入目录。"""
        if not path or not os.path.isdir(path):
            return
        self._folder_path = path
        self.folder_input.setText(path)
        self._scan_folder(path)

    def _scan_folder(self, folder: str):
        files = []
        try:
            for fname in sorted(os.listdir(folder)):
                ext = os.path.splitext(fname)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    files.append(os.path.join(folder, fname))
        except Exception as e:
            QMessageBox.warning(self.parent_widget, "扫描失败", str(e))
            return

        if not files:
            QMessageBox.information(
                self.parent_widget, "未发现视频",
                f"在选定文件夹中未找到视频文件。\n支持格式：{', '.join(VIDEO_EXTENSIONS)}"
            )
            return

        self.video_files = files
        self._results  = {}
        self._row_logs = {}
        self._populate_table_empty(files)
        self.btn_analyze.setEnabled(True)
        self.btn_rename.setEnabled(False)
        self.btn_batch_replace.setEnabled(False)
        self.combo_batch_field.setEnabled(False)
        self.input_batch_value.setEnabled(False)
        self.btn_batch_set.setEnabled(False)
        self.status_lbl.setText(f"已发现 {len(files)} 个视频文件，点击「分析并预览」开始分析")
        # 检查撤销历史
        self._check_undo_available()

    def _populate_table_empty(self, files: list):
        """用文件列表填充表格（初始化行，新名称先占位）。"""
        self.table.setRowCount(0)
        self.table.setRowCount(len(files))
        for row, fpath in enumerate(files):
            fname = os.path.basename(fpath)
            parsed = _parse_existing_filename(fname)
            meta   = _get_video_meta(fpath)
            try:
                mtime  = os.path.getmtime(fpath)
                date_s = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d")
            except Exception:
                date_s = parsed.get("date", "unknown")
            parsed["date"] = date_s

            # 生成初始文件名（仅基于原文件名解析 + 路径 + 元数据，无 AI）
            folder_root = os.path.abspath(self._folder_path) if self._folder_path else ""
            path_info = _extract_path_info(fpath, folder_root)
            init_new = _build_new_filename(
                {'brand':'unknown','category':'unknown','model':'unknown'},
                meta, parsed, fpath, path_info
            )

            # Col 0: checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, chk_item)

            # Col 1: #
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            num_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, num_item)

            # Col 2: 原文件名（只读）
            orig_item = QTableWidgetItem(fname)
            orig_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            orig_item.setToolTip(fpath)
            orig_item.setForeground(QColor("#9ca3af"))
            self.table.setItem(row, 2, orig_item)

            # Col 3: 新文件名（可编辑）
            new_item = QTableWidgetItem(init_new)
            new_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            new_item.setForeground(QColor("#f3f4f6"))
            self.table.setItem(row, 3, new_item)

            # Col 4: 分辨率/方向
            res_str = meta.get('resolution', parsed.get('resolution', '-'))
            ori_str = meta.get('orientation', parsed.get('orientation', ''))
            res_item = QTableWidgetItem(f"{res_str}  {ori_str}")
            res_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            res_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, res_item)

            # Col 5: 日期
            date_item = QTableWidgetItem(date_s)
            date_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            date_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, date_item)

            # Col 6: 状态
            status_item = QTableWidgetItem("待分析")
            status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor("#9ca3af"))
            self.table.setItem(row, 6, status_item)

            # Col 7: 分析结果
            ai_result_item = QTableWidgetItem("-")
            ai_result_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ai_result_item.setForeground(QColor("#9ca3af"))
            self.table.setItem(row, 7, ai_result_item)

            # Col 8: 重分析按钮
            btn_reanalyze = QPushButton("🔄")
            btn_reanalyze.setToolTip("单独重新分析该视频")
            btn_reanalyze.setStyleSheet("padding: 0px; font-size: 11px;")
            btn_reanalyze.setFixedWidth(30)
            btn_reanalyze.setFixedHeight(24)
            btn_reanalyze.setEnabled(False)
            btn_reanalyze.clicked.connect(lambda checked=False, r=row, fp=fpath: self._reanalyze_single(r, fp))
            self.table.setCellWidget(row, 8, btn_reanalyze)

            # Col 9: 播放按钮（随时可用，打开 VideoPlayerDialog）
            btn_play_row = QPushButton("▶")
            btn_play_row.setToolTip("播放视频，拖拽到任意帧后可分析命名")
            btn_play_row.setStyleSheet(
                "padding: 0px; font-size: 12px;"
                "background-color: #1d4ed8; color: #fff; border-radius: 3px;"
            )
            btn_play_row.setFixedWidth(30)
            btn_play_row.setFixedHeight(24)
            btn_play_row.clicked.connect(lambda checked=False, r=row: self._open_video_player(r))
            self.table.setCellWidget(row, 9, btn_play_row)

        self.table.resizeRowsToContents()

    # ──────────────────────── 分析 ────────────────────────
    def _start_analyze(self):
        if not self.video_files:
            return

        api_url      = self._api_url
        api_key      = self._api_key
        model        = self._model
        vision_model = self._vision_model
        num_frames   = self.spin_frames.value()

        if not api_url or not model:
            reply = QMessageBox.question(
                self.parent_widget, "未配置 AI",
                "未配置 AI 接口地址或模型名称。\n"
                "将仅根据原文件名和视频元数据（分辨率/日期）生成新文件名，\n"
                "品牌/品类/型号 将填写为 unknown。\n\n确认继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.btn_analyze.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_rename.setEnabled(False)
        self.btn_batch_replace.setEnabled(False)
        self.combo_batch_field.setEnabled(False)
        self.input_batch_value.setEnabled(False)
        self.btn_batch_set.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.video_files))
        self.progress_bar.setValue(0)
        self._results  = {}
        self._row_logs = {}

        # 重置状态列
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 6)
            if item:
                item.setText("分析中...")
                item.setForeground(QColor("#fbbf24"))

        self.worker = VideoAnalyzeWorker(
            self.video_files, api_url, api_key, model, num_frames,
            folder_path=self._folder_path, vision_model=vision_model,
            vision_api_url=self._vision_api_url
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.video_analyzed.connect(self._on_video_analyzed)
        self.worker.finished.connect(self._on_analyze_finished)
        self.worker.log_sig.connect(self._append_log)
        self.worker.log_row_sig.connect(self._on_row_log)
        self.worker.start()

    def _stop_analyze(self):
        if self.worker and self.worker.isRunning():
            self.worker.abort()

    def _reanalyze_single(self, row_idx: int, fpath: str):
        """单独重新分析一个视频。"""
        if not self._api_url or not self._model:
            QMessageBox.warning(self.parent_widget, "未配置 AI", "请先在设置中配置 AI 模型。")
            return

        status_item = self.table.item(row_idx, 6)
        if status_item:
            status_item.setText("分析中...")
            status_item.setForeground(QColor("#fbbf24"))

        btn = self.table.cellWidget(row_idx, 8)
        if btn:
            btn.setEnabled(False)

        class ReAnalyzeThread(BaseWorker):
            result_ready = Signal(int, dict)
            def __init__(self, fpath, worker_instance):
                super().__init__()
                self.fpath = fpath
                self.worker = worker_instance
            def run(self):
                try:
                    result = self.worker._analyze_one(self.fpath)
                    self.result_ready.emit(-1, result)
                except Exception as e:
                    self.result_ready.emit(-1, {'status': f'⚠ {str(e)[:50]}', 'error': True,
                        'brand':'unknown','category':'unknown','model':'unknown',
                        'new_name':'','resolution':'','orientation':'','date':'','model_name':'unknown'})

        temp_worker = VideoAnalyzeWorker([fpath], self._api_url, self._api_key, self._model,
                                         self.spin_frames.value(), folder_path=self._folder_path,
                                         vision_model=self._vision_model,
                                         vision_api_url=self._vision_api_url)
        temp_worker.log_sig.connect(self._append_log)
        temp_worker.log_row_sig.connect(
            lambda ridx, line, ri=row_idx: self._on_row_log(ri, line)
        )
        self._single_thread = ReAnalyzeThread(fpath, temp_worker)
        self._single_thread.result_ready.connect(lambda idx, res: self._on_video_analyzed(row_idx, res))
        self._single_thread.start()

    def _on_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setValue(current)
        self.status_lbl.setText(msg)

    def _on_video_analyzed(self, row_idx: int, result: dict):
        self._results[row_idx] = result
        new_name = result['new_name']

        # 更新新文件名列
        new_item = self.table.item(row_idx, 3)
        if new_item:
            new_item.setText(new_name)
            if result['error']:
                new_item.setForeground(QColor("#f87171"))
            else:
                new_item.setForeground(QColor("#34d399"))

        # 更新状态列
        status_item = self.table.item(row_idx, 6)
        if status_item:
            status_item.setText(result['status'])
            if result['error']:
                status_item.setForeground(QColor("#f87171"))
            else:
                status_item.setForeground(QColor("#34d399"))

        # 更新分析结果列（显示投票置信度）
        ai_result_item = self.table.item(row_idx, 7)
        if ai_result_item:
            brand  = result.get('brand',     'unknown')
            cat    = result.get('category',  'unknown')
            model  = result.get('model_name','unknown')
            bc     = result.get('brand_conf',    0.0)
            cc     = result.get('category_conf', 0.0)
            mc     = result.get('model_conf',    0.0)
            n      = result.get('frame_count',   0)
            if n > 0:
                ai_result_item.setText(
                    f"品牌:{brand}({bc:.0%})  品类:{cat}({cc:.0%})  型号:{model}({mc:.0%})  [{n}帧]"
                )
            else:
                ai_result_item.setText(f"品牌:{brand}  品类:{cat}  型号:{model}")
            ai_result_item.setForeground(QColor("#9ca3af"))

        # 启用重分析按钮
        btn = self.table.cellWidget(row_idx, 8)
        if btn:
            btn.setEnabled(True)

    def _on_analyze_finished(self):
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_rename.setEnabled(True)
        self.btn_batch_replace.setEnabled(True)
        self.combo_batch_field.setEnabled(True)
        self.input_batch_value.setEnabled(True)
        self.btn_batch_set.setEnabled(True)
        self.progress_bar.setVisible(False)

        # 残留的"分析中..."说明该行根本没收到结果（线程中途异常/被中止），
        # 不能伪装成"已分析 ✓"，标记为未完成。
        incomplete = 0
        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, 6)
            if status_item and status_item.text() == "分析中...":
                status_item.setText("未完成 ⚠")
                status_item.setForeground(QColor("#f87171"))
                incomplete += 1

        # 根据真实结果统计成功/失败
        total = len(self.video_files)
        ok = sum(1 for r in self._results.values() if not r.get('error'))
        failed = sum(1 for r in self._results.values() if r.get('error'))

        if incomplete or failed:
            self.status_lbl.setText(
                f"⚠ 分析结束：成功 {ok} 个，失败 {failed} 个，未完成 {incomplete} 个（共 {total}）。"
                "失败/未完成的行可点「🔄」单独重分析；详情见日志。"
            )
        else:
            self.status_lbl.setText(
                f"✅ 分析完成！共 {total} 个视频，成功 {ok} 个。"
                "可直接双击「新文件名」列进行编辑，或点击「批量查找替换」，"
                "确认后点击「执行重命名」。"
            )

    # ──────────────────────── 日志面板 ────────────────────────
    def _append_log(self, text: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_panel.append(f"[{ts}] {text}")
        sb = self.log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_row_log(self, row_idx: int, line: str):
        if row_idx < 0:
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._row_logs.setdefault(row_idx, []).append(f"[{ts}] {line}")

    def _open_video_player(self, row: int):
        """播放按钮 → 打开视频播放器（可拖拽选帧、分析、重命名）。"""
        if row >= len(self.video_files):
            return
        fpath = self.video_files[row]
        if not os.path.isfile(fpath):
            QMessageBox.warning(self.parent_widget, "文件不存在",
                                f"找不到文件：\n{fpath}\n（可能已被重命名或删除）")
            return
        dlg = VideoPlayerDialog(
            fpath          = fpath,
            row_idx        = row,
            vision_model   = self._vision_model,
            vision_api_url = self._vision_api_url,
            api_key        = self._api_key,
            page_ref       = self,
            parent         = self.parent_widget,
        )
        dlg.exec()

    def _apply_rename_from_dialog(self, row_idx: int, actual_name: str, ai_info: dict):
        """VideoPlayerDialog 确认重命名后同步更新表格和内部状态。"""
        # 更新表格显示
        orig_item = self.table.item(row_idx, 2)
        new_item  = self.table.item(row_idx, 3)
        if orig_item:
            orig_item.setText(actual_name)
        if new_item:
            new_item.setText(actual_name)
            new_item.setForeground(QColor("#34d399"))
        status_item = self.table.item(row_idx, 6)
        if status_item:
            status_item.setText("已重命名 ✓")
            status_item.setForeground(QColor("#34d399"))
        ai_result_item = self.table.item(row_idx, 7)
        if ai_result_item:
            brand = ai_info.get('brand', 'unknown')
            cat   = ai_info.get('category', 'unknown')
            model = ai_info.get('model', 'unknown')
            ai_result_item.setText(f"品牌:{brand} 品类:{cat} 型号:{model}")

        # 更新内存中的路径和结果
        if row_idx < len(self.video_files):
            folder = os.path.dirname(self.video_files[row_idx])
            self.video_files[row_idx] = os.path.join(folder, actual_name)
        if row_idx in self._results:
            self._results[row_idx].update({
                'original_path': self.video_files[row_idx],
                'original_name': actual_name,
                'new_name':      actual_name,
                'brand':         ai_info.get('brand', 'unknown'),
                'category':      ai_info.get('category', 'unknown'),
                'model_name':    ai_info.get('model', 'unknown'),
                'status':        '已重命名 ✓',
            })

    # ──────────────────────── 批量设置字段 ────────────────────────
    def _batch_set_field(self):
        field_map = {"品牌(AI)": 3, "品类(AI)": 4, "型号(AI)": 5}
        field = self.combo_batch_field.currentText()
        value = self.input_batch_value.text().strip()
        if not value:
            QMessageBox.warning(self.parent_widget, "输入为空", "请输入要设置的值。")
            return

        pos = field_map[field]
        count = 0
        for row in range(self.table.rowCount()):
            new_name_item = self.table.item(row, 3)
            if not new_name_item:
                continue
            current = new_name_item.text()
            ext = os.path.splitext(current)[1] if "." in current else ""
            base = os.path.splitext(current)[0]
            parts = base.split("_")
            while len(parts) < 6:
                parts.append("unknown")
            parts[pos] = value
            new_base = "_".join(parts)
            new_name = new_base + ext
            if new_name != current:
                new_name_item.setText(new_name)
                count += 1

        self.status_lbl.setText(f"✅ 已批量设置 {field} = {value}，共更新 {count} 个文件")

    # ──────────────────────── 批量查找替换 ────────────────────────
    def _batch_find_replace(self):
        dlg = BatchFindReplaceDialog(self.parent_widget)
        if dlg.exec() != QDialog.Accepted:
            return
        find_text, replace_text = dlg.get_values()
        if not find_text:
            return

        count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 3)
            if item and find_text in item.text():
                item.setText(item.text().replace(find_text, replace_text))
                count += 1

        self.status_lbl.setText(f"✅ 批量替换完成：共修改了 {count} 行的新文件名。")

    # ──────────────────────── 全选/全不选 ────────────────────────
    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

    # ──────────────────────── 执行重命名 ────────────────────────
    def _do_rename(self):
        if not self._folder_path:
            return

        # 收集勾选的行
        to_rename = []
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            if not chk or chk.checkState() != Qt.Checked:
                continue
            orig_item = self.table.item(row, 2)
            new_item  = self.table.item(row, 3)
            if not orig_item or not new_item:
                continue
            orig_name = orig_item.text()
            new_name  = new_item.text().strip()
            if not new_name or new_name == orig_name:
                continue
            to_rename.append((row, orig_name, new_name))

        if not to_rename:
            QMessageBox.information(
                self.parent_widget, "无需重命名",
                "没有需要重命名的文件（勾选且新文件名与原文件名不同的项）。"
            )
            return

        reply = QMessageBox.question(
            self.parent_widget, "确认重命名",
            f"即将对 {len(to_rename)} 个文件进行重命名，操作可通过「撤销」按钮还原。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        history_entries = []
        success_count = 0
        fail_msgs = []

        for row, orig_name, new_name in to_rename:
            old_path = os.path.join(self._folder_path, orig_name)
            raw_new_path = os.path.join(self._folder_path, new_name)
            new_path = _ensure_unique_path(raw_new_path)

            try:
                os.rename(old_path, new_path)
                history_entries.append({
                    "old": orig_name,
                    "new": os.path.basename(new_path)
                })
                success_count += 1
                # 更新表格
                orig_item = self.table.item(row, 2)
                new_item  = self.table.item(row, 3)
                if orig_item:
                    orig_item.setText(os.path.basename(new_path))
                if new_item:
                    new_item.setText(os.path.basename(new_path))
                    new_item.setForeground(QColor("#34d399"))
                status_item = self.table.item(row, 6)
                if status_item:
                    status_item.setText("已重命名 ✓")
                    status_item.setForeground(QColor("#34d399"))
            except Exception as e:
                fail_msgs.append(f"{orig_name}: {e}")
                status_item = self.table.item(row, 6)
                if status_item:
                    status_item.setText("失败 ✗")
                    status_item.setForeground(QColor("#f87171"))

        # 保存撤销历史
        if history_entries:
            history_path = os.path.join(self._folder_path, self.HISTORY_FILENAME)
            history_data = {
                "timestamp": datetime.datetime.now().isoformat(),
                "renames": history_entries
            }
            try:
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(history_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log.warning(f"Save rename history failed: {e}")

        self.btn_undo.setEnabled(bool(history_entries))
        msg = f"✅ 重命名完成：成功 {success_count} 个。"
        if fail_msgs:
            msg += f"\n⚠ 失败 {len(fail_msgs)} 个：\n" + "\n".join(fail_msgs[:5])
        self.status_lbl.setText(msg)

    # ──────────────────────── 撤销 ────────────────────────
    def _check_undo_available(self):
        if not self._folder_path:
            return
        history_path = os.path.join(self._folder_path, self.HISTORY_FILENAME)
        self.btn_undo.setEnabled(os.path.exists(history_path))

    def _undo_rename(self):
        if not self._folder_path:
            return
        history_path = os.path.join(self._folder_path, self.HISTORY_FILENAME)
        if not os.path.exists(history_path):
            QMessageBox.information(self.parent_widget, "无记录", "找不到撤销历史文件。")
            return

        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self.parent_widget, "读取失败", str(e))
            return

        entries = history_data.get("renames", [])
        if not entries:
            QMessageBox.information(self.parent_widget, "无记录", "历史记录为空。")
            return

        ts = history_data.get("timestamp", "未知时间")
        reply = QMessageBox.question(
            self.parent_widget, "确认撤销",
            f"将撤销 {len(entries)} 个文件的重命名操作（操作时间：{ts}）。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success_count = 0
        fail_msgs = []
        for entry in entries:
            new_name = entry.get("new", "")
            old_name = entry.get("old", "")
            if not new_name or not old_name:
                continue
            new_path = os.path.join(self._folder_path, new_name)
            old_path = os.path.join(self._folder_path, old_name)
            if not os.path.exists(new_path):
                fail_msgs.append(f"{new_name} 不存在，已跳过")
                continue
            try:
                os.rename(new_path, old_path)
                success_count += 1
            except Exception as e:
                fail_msgs.append(f"{new_name} → {old_name}: {e}")

        # 删除历史文件
        try:
            os.remove(history_path)
        except Exception:
            pass

        self.btn_undo.setEnabled(False)
        msg = f"✅ 撤销完成：还原 {success_count} 个文件。"
        if fail_msgs:
            msg += "\n⚠ 部分失败：\n" + "\n".join(fail_msgs[:5])
        self.status_lbl.setText(msg)

        # 重新扫描文件夹刷新列表
        self._scan_folder(self._folder_path)
