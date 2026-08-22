"""OCR 后台 Worker（走服务端 POST /material/ocr）。

替代各 OCR 页面里的 subprocess 本地 PaddleOCR 调用。
信号签名与原 worker 完全一致，页面层 connect 无需改动：
    progress_updated(int) / status_updated(str) / log_received(str) / finished(bool, str)  # noqa: E501
"""
import csv
import os

from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.logger_utils import log
from utils.ocr_client import (
    extract_numbers,
    extract_value_for_key,
    ocr_image_crop,
    ocr_image_file,
)


class ImageFolderOcrWorker(BaseWorker):
    """图片文件夹批量 OCR：逐张调服务端 → 关键词定位 → 写 csv/txt。"""
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str)  # success, output_path_or_error

    def __init__(self, folder_path, key_text, output_path):
        super().__init__()
        self.folder_path = folder_path
        self.key_text = key_text
        self.output_path = output_path
        self.is_aborted = False

    def stop(self):
        self.is_aborted = True

    def run(self):
        self.status_updated.emit("正在连接 OCR 服务端...")
        self.log_received.emit("[INFO] 开始图片文件夹批量 OCR 识别任务（服务端模式）")
        self.log_received.emit(f"[INFO] 文件夹路径: {self.folder_path}")
        self.log_received.emit(f"[INFO] 定位关键词: {self.key_text}")

        try:
            valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff")
            images = []
            for fname in os.listdir(self.folder_path):
                if fname.lower().endswith(valid_exts):
                    images.append(os.path.join(self.folder_path, fname))

            if not images:
                self.finished.emit(False, f"文件夹内无有效图片: {self.folder_path}")
                return

            self.log_received.emit(f"[STARTING] 批量 OCR: 共 {len(images)} 张图片")
            results = []

            for idx, img_path in enumerate(images):
                if self.is_aborted:
                    self.finished.emit(False, "用户终止运行。")
                    return

                basename = os.path.basename(img_path)
                self.status_updated.emit(f"正在识别: {basename}")
                try:
                    ret = ocr_image_file(img_path)
                    lines = ret.get("lines", [])
                    extracted, raw_block = extract_value_for_key(self.key_text, lines)

                    if extracted is not None:
                        self.log_received.emit(
                            f"[OCR] Image: {basename} | Extracted: {extracted} | Text Block: {raw_block}")  # noqa: E501
                    else:
                        self.log_received.emit(f"[OCR] Image: {basename} | [未定位到关键词 '{self.key_text}']")  # noqa: E501

                    results.append({
                        "image": basename,
                        "path": img_path,
                        "extracted": extracted or "",
                        "raw": raw_block or "",
                    })
                except Exception as e:  # ocr_image_file 外部 API 调用
                    self.log_received.emit(f"[WARNING] OCR 失败 {basename}: {e}")
                    results.append({
                        "image": basename,
                        "path": img_path,
                        "extracted": f"Error: {e}",
                        "raw": "",
                    })

                progress = min(99, int(((idx + 1) / len(images)) * 100))
                self.progress_updated.emit(progress)

            # 写输出文件
            saved_path = self._write_output(results)
            self.progress_updated.emit(100)
            self.log_received.emit(f"[SUCCESS] Results saved to: {saved_path}")
            self.finished.emit(True, saved_path)

        except Exception as e:  # 顶层异常：混合文件 I/O + 外部 OCR API 调用
            log.error(f"[OCR] 图片文件夹批量任务异常: {e}")
            self.finished.emit(False, f"执行 OCR 时发生异常: {str(e)}")

    def _write_output(self, results):
        """写 csv/txt（逻辑移植自 image_folder_ocr_backend.py）。"""
        output_path = self.output_path
        save_path = output_path
        base, ext = os.path.splitext(output_path)
        count = 1
        while True:
            try:
                with open(save_path, "a") as _f:
                    pass
                break
            except (OSError, PermissionError):
                save_path = f"{base}_{count}{ext}"
                count += 1
                if count > 100:
                    break

        os.makedirs(os.path.dirname(os.path.abspath(save_path)) or ".", exist_ok=True)

        if save_path.lower().endswith(".csv"):
            with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["图片名称", f"提取值 ({self.key_text})", "包含关键词文本块", "文件完整路径"])  # noqa: E501
                for r in results:
                    writer.writerow([r["image"], r["extracted"], r["raw"], r["path"]])
        else:
            with open(save_path, "w", encoding="utf-8") as f:
                for r in results:
                    val = r["extracted"] if r["extracted"] else "(未匹配到)"
                    f.write(f"{r['image']}: {val}\n")
        return save_path


class ImageOcrTestWorker(BaseWorker):
    """单图选区测试 OCR：客户端按 box 裁剪 → 上传服务端。"""
    finished = Signal(bool, str)  # success, text_or_error

    def __init__(self, image_path, box):
        super().__init__()
        self.image_path = image_path
        self.box = box  # [ymin, ymax, xmin, xmax]

    def run(self):
        try:
            ret = ocr_image_crop(self.image_path, self.box)
            texts = [ln.get("text", "") for ln in ret.get("lines", [])]
            recognized = " ".join(t for t in texts if t)
            self.finished.emit(True, recognized if recognized else "(无识别文本)")
        except Exception as e:  # ocr_image_crop 外部 API 调用
            log.error(f"[OCR] 选区测试失败: {e}")
            self.finished.emit(False, str(e))


class VideoOcrWorker(BaseWorker):
    """视频帧框选 OCR：cv2 抽帧 → 裁剪 box → 逐帧上传服务端 → 写 csv。"""
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_received = Signal(str)
    finished = Signal(bool, str)  # success, output_path_or_error

    def __init__(self, video_path, box, sample_interval, filter_mode, output_path, preview_path):  # noqa: E501
        """
        :param box: [ymin, ymax, xmin, xmax]
        """
        super().__init__()
        self.video_path = video_path
        self.box = box
        self.sample_interval = max(1, int(sample_interval))
        self.filter_mode = filter_mode  # "all" | "numeric"
        self.output_path = output_path
        self.preview_path = preview_path
        self.is_aborted = False

    def stop(self):
        self.is_aborted = True

    def run(self):
        import cv2
        ymin, ymax, xmin, xmax = self.box

        self.status_updated.emit("正在连接 OCR 服务端...")
        self.log_received.emit("[INFO] 开始视频 OCR 识别任务（服务端模式）")
        self.log_received.emit(f"[INFO] 视频文件: {self.video_path}")
        self.log_received.emit(f"[INFO] 框选选区: YMin={ymin}, YMax={ymax}, XMin={xmin}, XMax={xmax}")  # noqa: E501

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            self.finished.emit(False, f"无法打开视频: {self.video_path}")
            return

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.log_received.emit(f"[INFO] Total frames: {total_frames}, FPS: {fps:.1f}")

        results = []
        frame_idx = 0
        try:
            while True:
                if self.is_aborted:
                    self.finished.emit(False, "用户终止运行。")
                    return

                ret, frame = cap.read()
                if not ret:
                    break
                frame_idx += 1

                if (frame_idx - 1) % self.sample_interval != 0:
                    if total_frames > 0:
                        prog = min(99, int((frame_idx / total_frames) * 100))
                        self.progress_updated.emit(prog)
                    continue

                timestamp_sec = (frame_idx - 1) / fps
                time_str = self._format_time(timestamp_sec)
                self.status_updated.emit(f"识别中: 帧 {frame_idx} @ {time_str}")

                # 首帧裁剪区存为预览图（与原 backend 一致）
                if frame_idx == 1 and self.preview_path:
                    try:
                        img_h, img_w = frame.shape[:2]
                        _y0 = max(0, min(int(ymin), img_h))
                        _y1 = max(0, min(int(ymax), img_h))
                        _x0 = max(0, min(int(xmin), img_w))
                        _x1 = max(0, min(int(xmax), img_w))
                        roi = frame[_y0:_y1, _x0:_x1] if (_y1 > _y0 and _x1 > _x0) else frame  # noqa: E501
                        cv2.imwrite(self.preview_path, roi)
                    except OSError:
                        pass

                try:
                    ret_ocr = ocr_image_crop(frame, self.box)
                    texts = [ln.get("text", "") for ln in ret_ocr.get("lines", [])]
                    recognized = " ".join(t for t in texts if t)
                    extracted = recognized
                    if self.filter_mode == "numeric":
                        extracted = extract_numbers(recognized)

                    if recognized.strip():
                        self.log_received.emit(
                            f"[OCR] Frame: {frame_idx} | Time: {time_str} | Text: {recognized} | Extracted: {extracted}")  # noqa: E501
                        results.append({
                            "frame": frame_idx,
                            "time": time_str,
                            "raw_text": recognized,
                            "extracted_value": extracted,
                            "confidence": f"{ret_ocr.get('total', 0)}",
                        })
                except Exception as e:  # ocr_image_crop 外部 API 调用
                    self.log_received.emit(f"[WARNING] OCR 失败 帧 {frame_idx}: {e}")

                if total_frames > 0:
                    prog = min(99, int((frame_idx / total_frames) * 100))
                    self.progress_updated.emit(prog)

            # 写 csv
            saved_path = self._write_csv(results)
            self.progress_updated.emit(100)
            self.log_received.emit(f"[SUCCESS] Results saved to: {saved_path}")
            self.finished.emit(True, saved_path)

        except Exception as e:  # 顶层异常：混合 cv2 帧读取 + 外部 OCR API 调用
            log.error(f"[OCR] 视频任务异常: {e}")
            self.finished.emit(False, f"执行 OCR 时发生异常: {str(e)}")
        finally:
            cap.release()

    def _format_time(self, sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _write_csv(self, results):
        save_path = self.output_path
        os.makedirs(os.path.dirname(os.path.abspath(save_path)) or ".", exist_ok=True)
        with open(save_path, "w", newline="", encoding="utf-8-sig") as csvfile:
            fieldnames = ["帧号", "时间戳", "原始识别文本", "提取数值(温度/数字)", "置信度"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "帧号": r["frame"],
                    "时间戳": r["time"],
                    "原始识别文本": r["raw_text"],
                    "提取数值(温度/数字)": r["extracted_value"],
                    "置信度": r["confidence"],
                })
        return save_path
