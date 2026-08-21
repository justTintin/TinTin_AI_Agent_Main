# -*- coding: utf-8 -*-
"""OCR 服务端客户端 — 客户端不再内置 PaddleOCR，识别统一交由算力服务端执行。

对应服务端接口（见 docs/服务端OCR接口扩展需求-交付服务端团队.md）：
  · POST /ocr/image          单图 OCR（可选 ROI 裁剪，同步返回 text）
  · POST /ocr/video          视频逐帧 OCR（异步任务 → 下载 CSV）
  · POST /ocr/batch          图片文件夹批量 OCR（异步任务 → 下载 CSV/txt）
  · GET  /ocr/download/{fn}  下载结果文件

地址来源：ai_config.json 的 compute_server_url。
"""
import os
import time
import zipfile

import requests

from utils.logger_utils import log

_POLL_INTERVAL = 3.0        # 轮询间隔（秒）
_POLL_TIMEOUT = 1800.0      # 最长等待（OCR 批量/视频较慢，给足 30 分钟）


def _server_url(server_url: str = "") -> str:
    """获取算力服务端地址（参数优先，否则走统一解析）。"""
    from utils.server_resolver import get_server_url
    return get_server_url(explicit=server_url)


def _poll_and_download(base: str, task_id: str, out_path: str,
                       timeout: float, progress_cb=None) -> str:
    """轮询任务直到完成，然后下载结果文件到 out_path，返回 out_path。"""
    def _stage(text):
        log.info(f"[OCR远程] {text}")
        if progress_cb:
            try:
                progress_cb(text)
            except Exception:
                pass

    _stage(f"服务端处理中（task={task_id}）...")
    poll_url = f"{base}/tasks/unified/{task_id}"
    deadline = time.time() + timeout
    filename = ""
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            pr = requests.get(poll_url, timeout=15)
        except Exception:
            continue
        if pr.status_code != 200:
            continue
        try:
            pdata = pr.json()
        except Exception:
            continue
        task_obj = pdata.get("data") if isinstance(pdata.get("data"), dict) else pdata
        status = str(task_obj.get("status") or task_obj.get("state") or "").lower()
        if status in ("completed", "done", "success", "finished"):
            result = task_obj.get("result") if isinstance(task_obj.get("result"), dict) else {}
            params = task_obj.get("params") if isinstance(task_obj.get("params"), dict) else {}
            filename = (task_obj.get("filename") or task_obj.get("output")
                        or result.get("filename") or result.get("output")
                        or params.get("output") or "")
            break
        if status in ("failed", "error", "cancelled"):
            err = (task_obj.get("error_msg") or task_obj.get("error")
                   or task_obj.get("message") or "未知错误")
            err = str(err)[:600]
            logs = task_obj.get("log") or []
            tail = "\n".join(str(l) for l in logs[-5:]) if isinstance(logs, list) else ""
            suffix = f"\n\n服务端日志:\n{tail}" if tail else ""
            raise RuntimeError(f"OCR 任务失败: {err}{suffix}")
    else:
        raise RuntimeError(f"OCR 任务超时({timeout:.0f}s)，task_id={task_id}")

    if not filename:
        raise RuntimeError("服务端未返回 OCR 结果文件名")

    # 下载结果文件
    _stage("正在下载 OCR 结果文件...")
    dl_url = f"{base}/ocr/download/{filename}"
    try:
        dr = requests.get(dl_url, timeout=300, stream=True)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"下载结果失败: {e}")
    if dr.status_code != 200:
        raise RuntimeError(f"下载结果失败 HTTP {dr.status_code}: {dl_url}")

    tmp_path = out_path + ".part"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(tmp_path, "wb") as f:
            for chunk in dr.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        os.replace(tmp_path, out_path)
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise RuntimeError(f"保存 OCR 结果失败: {e}")

    _stage(f"完成: {out_path}")
    return out_path


def ocr_image_roi(image_path: str, box=None, server_url: str = "") -> str:
    """单图 OCR（可选 ROI 裁剪），同步返回识别文本。

    Args:
        image_path: 图片路径
        box: (ymin, ymax, xmin, xmax)，None 或全 0 表示整图
        server_url: 服务端地址（留空读 ai_config.json）

    Returns:
        识别文本字符串
    """
    base = _server_url(server_url)
    data = {}
    if box:
        ymin, ymax, xmin, xmax = [int(v) for v in box]
        if not (ymin == 0 and ymax == 0 and xmin == 0 and xmax == 0):
            data.update({"ymin": ymin, "ymax": ymax, "xmin": xmin, "xmax": xmax})

    mime = "image/png"
    ext = os.path.splitext(image_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif ext == ".bmp":
        mime = "image/bmp"
    elif ext == ".webp":
        mime = "image/webp"

    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{base}/ocr/image",
                files={"file": (os.path.basename(image_path), f, mime)},
                data=data,
                timeout=120,
            )
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"无法连接 OCR 服务端 ({base})，请检查服务是否启动") from e
    except requests.exceptions.Timeout:
        raise RuntimeError(f"OCR 服务端 ({base}) 响应超时，可能正在加载模型")

    if resp.status_code != 200:
        raise RuntimeError(f"OCR 服务端返回 {resp.status_code}: {resp.text[:200]}")
    try:
        payload = resp.json()
    except Exception:
        raise RuntimeError(f"OCR 响应非 JSON: {resp.text[:200]}")
    return payload.get("text", payload.get("result", "")) or ""


def video_ocr_remote(video_path: str, box=None, sample_interval: int = 5,
                     filter_mode: str = "all", out_path: str = "",
                     server_url: str = "", timeout: float = _POLL_TIMEOUT,
                     progress_cb=None) -> str:
    """视频逐帧 OCR（服务端执行），下载 CSV 结果到本地。

    Args:
        video_path: 输入视频路径
        box: (ymin, ymax, xmin, xmax)，None 或全 0 表示整帧
        sample_interval: 每 N 帧取 1 帧
        filter_mode: all / numeric
        out_path: CSV 保存路径（留空则「原目录/原名_ocr.csv」）
        server_url / timeout / progress_cb: 同上

    Returns:
        本地 CSV 文件路径
    """
    base = _server_url(server_url)

    if not out_path:
        stem, _ = os.path.splitext(video_path)
        out_path = f"{stem}_ocr.csv"

    def _stage(text):
        log.info(f"[OCR远程] {text}")
        if progress_cb:
            try:
                progress_cb(text)
            except Exception:
                pass

    data = {
        "sample_interval": int(sample_interval or 5),
        "filter_mode": filter_mode or "all",
    }
    if box:
        ymin, ymax, xmin, xmax = [int(v) for v in box]
        data.update({"ymin": ymin, "ymax": ymax, "xmin": xmin, "xmax": xmax})

    _stage("正在上传视频到服务端 OCR...")
    try:
        with open(video_path, "rb") as f:
            resp = requests.post(
                f"{base}/ocr/video",
                files={"file": (os.path.basename(video_path), f, "video/mp4")},
                data=data,
                timeout=600,
            )
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"无法连接 OCR 服务端 ({base})，请检查服务是否启动") from e

    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"服务端返回 {resp.status_code}: {resp.text[:200]}")
    try:
        submit_data = resp.json()
    except Exception:
        raise RuntimeError(f"提交响应非 JSON: {resp.text[:200]}")

    task_id = (submit_data.get("task_id") or submit_data.get("id")
               or submit_data.get("job_id") or "")
    if not task_id:
        raise RuntimeError(f"服务端未返回任务 ID: {str(submit_data)[:200]}")

    return _poll_and_download(base, task_id, out_path, timeout, progress_cb)


def image_folder_ocr_remote(folder_path: str, key_text: str, out_path: str = "",
                            output_format: str = "csv", server_url: str = "",
                            timeout: float = _POLL_TIMEOUT, progress_cb=None) -> str:
    """图片文件夹批量 OCR（客户端打包 zip 上传，服务端识别并提取关键词值）。

    Args:
        folder_path: 图片文件夹路径
        key_text: 定位关键词（锚点文本）
        out_path: 结果保存路径（留空则「文件夹同级/batch_ocr.csv|.txt」）
        output_format: csv / txt
        server_url / timeout / progress_cb: 同上

    Returns:
        本地结果文件路径
    """
    base = _server_url(server_url)
    fmt = (output_format or "csv").lower()
    if fmt not in ("csv", "txt"):
        fmt = "csv"

    if not out_path:
        parent = os.path.dirname(os.path.abspath(folder_path))
        out_path = os.path.join(parent, f"batch_ocr.{fmt}")

    def _stage(text):
        log.info(f"[OCR远程] {text}")
        if progress_cb:
            try:
                progress_cb(text)
            except Exception:
                pass

    valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff")
    images = []
    for name in os.listdir(folder_path):
        if name.lower().endswith(valid_exts):
            images.append(os.path.join(folder_path, name))
    if not images:
        raise RuntimeError(f"文件夹中没有可识别的图片: {folder_path}")

    # 打包为 zip（临时文件）
    _stage(f"正在打包 {len(images)} 张图片...")
    import tempfile
    tmp_zip = os.path.join(tempfile.gettempdir(), f"tin_ocr_{int(time.time())}.zip")
    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_STORED) as zf:
            for p in images:
                zf.write(p, arcname=os.path.basename(p))
    except Exception as e:
        raise RuntimeError(f"打包图片失败: {e}")

    try:
        _stage("正在上传图片压缩包到服务端 OCR...")
        try:
            with open(tmp_zip, "rb") as f:
                resp = requests.post(
                    f"{base}/ocr/batch",
                    files={"file": ("images.zip", f, "application/zip")},
                    data={"key": key_text, "output_format": fmt},
                    timeout=600,
                )
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"无法连接 OCR 服务端 ({base})，请检查服务是否启动") from e

        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(f"服务端返回 {resp.status_code}: {resp.text[:200]}")
        try:
            submit_data = resp.json()
        except Exception:
            raise RuntimeError(f"提交响应非 JSON: {resp.text[:200]}")

        task_id = (submit_data.get("task_id") or submit_data.get("id")
                   or submit_data.get("job_id") or "")
        if not task_id:
            raise RuntimeError(f"服务端未返回任务 ID: {str(submit_data)[:200]}")

        return _poll_and_download(base, task_id, out_path, timeout, progress_cb)
    finally:
        try:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
        except Exception:
            pass
