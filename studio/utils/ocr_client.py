# -*- coding: utf-8 -*-
"""OCR 客户端：通过服务端 POST /material/ocr 识别图片文字。

替代本地 PaddleOCR subprocess 调用。服务端接口契约：
    POST {compute_server_url}/material/ocr
    入参：file（multipart 图片字节）/ material_id（query）/ file_hash（query）
    返回：{"filename": str, "text": str, "lines": [{"text","confidence"[,"poly"]}], "total": int}

    lines[].poly（可选，PaddleOCR dt_polys）：[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    —— 服务端返回 poly 时，extract_value_for_key 可做空间定位（关键词右/下方取值）；
       未返回时降级为纯文本匹配。
"""
import os
import re

from utils.logger_utils import log


def _get_server_url():
    """读取 OCR 服务端地址。

    优先级：ai_config.ocr_api_url（独立配置）> ai_config.compute_server_url（统一地址）。
    """
    try:
        from config.paths import AI_CONFIG_FILE
        import json
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("ocr_api_url") or cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def ocr_image(image_bytes, filename="image.jpg", material_id=None, file_hash=None, timeout=60):
    """上传图片字节到服务端 OCR，返回 {filename, text, lines, total}。

    失败抛 RuntimeError。lines 元素为 {text, confidence, poly?}。
    """
    from utils.http_client import http_post
    url = f"{_get_server_url()}/material/ocr"
    params = {}
    if material_id:
        params["material_id"] = material_id
    if file_hash:
        params["file_hash"] = file_hash
    files = {"file": (filename, image_bytes, "image/jpeg")}
    resp = http_post(url, files=files, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"服务端 OCR 返回 {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    # 业务错误（HTTP 200 + {"error": ...}）
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"服务端 OCR 失败: {data['error']}")
    # 规范化 lines
    lines = data.get("lines") or []
    norm_lines = []
    for ln in lines:
        if isinstance(ln, dict):
            norm_lines.append({
                "text": ln.get("text", ""),
                "confidence": ln.get("confidence", 0.0),
                # box: 服务端返回 [x1,y1,x2,y2]（左上+右下，像素）；poly: 兼容旧格式 [[x,y],...]
                "box": ln.get("box"),
                "poly": ln.get("poly") or ln.get("dt_polys") or None,
            })
        elif isinstance(ln, str):
            norm_lines.append({"text": ln, "confidence": 0.0, "box": None, "poly": None})
    return {
        "filename": data.get("filename", filename),
        "text": data.get("text", ""),
        "lines": norm_lines,
        "total": data.get("total", len(norm_lines)),
    }


def ocr_image_file(path, timeout=60):
    """读取本地图片文件 → 上传 OCR。"""
    with open(path, "rb") as f:
        data = f.read()
    return ocr_image(data, filename=os.path.basename(path), timeout=timeout)


def ocr_image_crop(path_or_array, box, timeout=60):
    """按 box(ymin,ymax,xmin,xmax) 裁剪图片 → 编码 JPEG → 上传 OCR。

    path_or_array：图片路径或 numpy 数组（BGR）。
    用于"框选选区"测试识别——客户端先裁剪再上传，等价于本地 ROI OCR。
    """
    import numpy as np
    import cv2
    # 载入图片（兼容 unicode 路径）
    if isinstance(path_or_array, str):
        img = cv2.imdecode(np.fromfile(path_or_array, dtype=np.uint8), 1)  # cv2.IMREAD_COLOR
        if img is None:
            raise RuntimeError(f"无法读取图片: {path_or_array}")
    else:
        img = path_or_array

    ymin, ymax, xmin, xmax = box
    img_h, img_w = img.shape[:2]
    ymin = max(0, min(int(ymin), img_h))
    ymax = max(0, min(int(ymax), img_h))
    xmin = max(0, min(int(xmin), img_w))
    xmax = max(0, min(int(xmax), img_w))
    if ymax > ymin and xmax > xmin:
        roi = img[ymin:ymax, xmin:xmax]
    else:
        roi = img

    # 编码为 JPEG 字节
    ok, buf = cv2.imencode(".jpg", roi)
    if not ok:
        raise RuntimeError("ROI 编码 JPEG 失败")
    return ocr_image(buf.tobytes(), filename="crop.jpg", timeout=timeout)


# ── 关键词定位（从 apps/PaddleOCR/image_folder_ocr_backend.py 移植，兼容无坐标）──

def _normalize_text(s):
    s = (s or "").strip().lower().replace(" ", "")
    for ch in [":", "：", "-", "_", ",", ".", ";", "；", "=", " "]:
        s = s.replace(ch, "")
    return s


def _strip_seps(text):
    """去除常见前导分隔符 + 尾部 复制/copy。"""
    text = (text or "").strip()
    while text and text[0] in [":", "：", "-", "_", "=", " ", "\t"]:
        text = text[1:].strip()
    if text.endswith("复制"):
        text = text[:-2].strip()
    if text.endswith("copy"):
        text = text[:-4].strip()
    return text


def extract_value_for_key(key_text, lines):
    """根据关键词从 OCR lines 中定位取值。

    lines: [{"text","confidence","box?","poly?"}]（ocr_image 返回的 lines）。
    返回 (extracted_or_None, raw_block_text)。

    坐标格式（优先级）：
    - box: 服务端返回 [x1,y1,x2,y2]（左上+右下，像素）。← 当前服务端 /material/ocr 返回此格式
    - poly: [[x,y],...] 四边形点集（旧格式兼容）。
    有坐标时启用空间定位（关键词右边/下方最近的块）；无坐标降级纯文本匹配。
    """
    norm_key = _normalize_text(key_text)
    if not norm_key:
        return None, ""

    texts = [ln.get("text", "") for ln in lines]

    # 统一解析每行的 bbox = (xmin, xmax, ymin, ymax)；解析失败为 None
    def to_bbox(ln):
        # 优先 box=[x1,y1,x2,y2]
        b = ln.get("box")
        if isinstance(b, (list, tuple)) and len(b) >= 4:
            x1, y1, x2, y2 = b[0], b[1], b[2], b[3]
            return (min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2))
        # 回退 poly=[[x,y],...]
        poly = ln.get("poly")
        if isinstance(poly, (list, tuple)) and len(poly) >= 2 and isinstance(poly[0], (list, tuple)):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            return (min(xs), max(xs), min(ys), max(ys))
        return None

    bboxes = [to_bbox(ln) for ln in lines]
    has_coords = bool(texts) and all(b is not None for b in bboxes) and len(bboxes) == len(texts)

    # 找到关键词所在块
    key_idx = -1
    for i, t in enumerate(texts):
        if norm_key in _normalize_text(t):
            key_idx = i
            break
    if key_idx == -1:
        return None, ""

    key_block_text = texts[key_idx]

    # 优先：关键词所在块去掉关键词后的剩余
    cleaned = _strip_seps(re.sub(re.escape(key_text), "", key_block_text, flags=re.IGNORECASE))
    if cleaned:
        return cleaned, key_block_text

    # 无坐标 → 无法做空间定位
    if not has_coords:
        return None, key_block_text

    # 有坐标 → 空间定位（右边 / 下方）
    k_xmin, k_xmax, k_ymin, k_ymax = bboxes[key_idx]
    k_cx = (k_xmin + k_xmax) / 2.0
    k_cy = (k_ymin + k_ymax) / 2.0
    k_h = k_ymax - k_ymin
    k_w = k_xmax - k_xmin

    # Step 1: 右边候选（同一行）
    right_cands = []
    for i in range(len(texts)):
        if i == key_idx:
            continue
        xmin, xmax, ymin, ymax = bboxes[i]
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        if (xmin > k_cx) and (abs(cy - k_cy) < k_h * 1.2):
            right_cands.append((i, xmin - k_xmax))
    if right_cands:
        right_cands.sort(key=lambda x: x[1])
        return _strip_seps(texts[right_cands[0][0]]), key_block_text

    # Step 2: 下方候选
    below_cands = []
    for i in range(len(texts)):
        if i == key_idx:
            continue
        xmin, xmax, ymin, ymax = bboxes[i]
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        if (ymin > k_cy) and (abs(cx - k_cx) < k_w * 1.5):
            below_cands.append((i, ymin - k_ymax))
    if below_cands:
        below_cands.sort(key=lambda x: x[1])
        return _strip_seps(texts[below_cands[0][0]]), key_block_text

    return None, key_block_text


def extract_numbers(text):
    """从文本提取数字（温度/数值），与 video backend 一致。"""
    pattern = r"[-+]?\d*\.\d+|\d+"
    return " ".join(re.findall(pattern, text or ""))


def check_server_ocr(timeout=5):
    """轻量探测服务端 OCR 是否可用（调 /material/status）。返回 bool。"""
    try:
        from utils.http_client import http_get
        resp = http_get(f"{_get_server_url()}/material/status", timeout=timeout, quiet=True)
        return resp.status_code == 200
    except Exception as e:
        log.debug(f"[OCR] 服务端连通检测失败: {e}")
        return False
