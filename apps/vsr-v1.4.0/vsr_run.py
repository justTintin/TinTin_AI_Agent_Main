import os
import sys

# 强制 stdout/stderr 使用 UTF-8 编码，避免 Windows cp1252 无法输出中文
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import cv2
import multiprocessing
import traceback

# Add backend to system path so backend imports find config and tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

import backend.main
from backend.config import config, tr
from backend.tools.constant import InpaintMode
from backend.tools.common_tools import is_video_or_image

def main():
    # Force multiprocessing start method
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--ymin", type=int, default=0)
    parser.add_argument("--ymax", type=int, default=0)
    parser.add_argument("--xmin", type=int, default=0)
    parser.add_argument("--xmax", type=int, default=0)
    parser.add_argument("--mode", default="sttn")
    parser.add_argument("--skip_detect", action="store_true")
    parser.add_argument("--lama_fast", action="store_true") # Compatibility placeholder
    parser.add_argument("--h264", action="store_true")      # Compatibility placeholder
    parser.add_argument("--preview_path", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--max_load_num", type=int, default=0,
                        help="Override STTN max frames per batch (0=use config default). "
                             "Lower values reduce GPU memory usage for high-resolution videos.")
    args = parser.parse_args()

    # Determine inpaint mode based on skip_detect and mode args
    mode_str = args.mode.lower()
    if mode_str == "sttn":
        if args.skip_detect:
            config.inpaintMode.value = InpaintMode.STTN_AUTO
        else:
            config.inpaintMode.value = InpaintMode.STTN_DET
    elif mode_str == "lama":
        config.inpaintMode.value = InpaintMode.LAMA
    elif mode_str == "propainter":
        config.inpaintMode.value = InpaintMode.PROPAINTER
    elif mode_str == "opencv":
        config.inpaintMode.value = InpaintMode.OPENCV
    else:
        config.inpaintMode.value = InpaintMode.STTN_AUTO

    video_path = args.video
    if not is_video_or_image(video_path):
        print(f"Error: {video_path} is not supported or corrupted.", flush=True)
        sys.exit(-1)

    # Override STTN batch size if specified (helps with high-resolution / large memory videos)
    if args.max_load_num > 0:
        config.sttnMaxLoadNum.value = args.max_load_num
        print(f"[INFO] STTN max load num overridden to: {args.max_load_num}", flush=True)

    sr = backend.main.SubtitleRemover(video_path, gui_mode=True)

    # Set custom output path if provided
    if args.output:
        sr.video_out_path = os.path.abspath(args.output)

    # Map area bounds
    if not (args.ymin == 0 and args.ymax == 0 and args.xmin == 0 and args.xmax == 0):
        sr.sub_areas = [(args.ymin, args.ymax, args.xmin, args.xmax)]
    else:
        sr.sub_areas = []

    print(f"[STARTING] Video: {args.video}, Mode: {config.inpaintMode.value}, Area: {sr.sub_areas}", flush=True)

    # Monkeypatch update_preview_with_comp to write preview images
    preview_path = args.preview_path
    if preview_path:
        def custom_update_preview(self, frame_ori, frame_comp):
            try:
                preview_frame = cv2.hconcat([frame_ori, frame_comp])
                cv2.imwrite(preview_path, preview_frame)
            except Exception:
                pass
        # Bind method to Class so all instances get it
        backend.main.SubtitleRemover.update_preview_with_comp = custom_update_preview

    # Add progress listener
    def progress_listener(progress_total, isFinished):
        print(f"[PROGRESS] {int(progress_total)}", flush=True)

    sr.add_progress_listener(progress_listener)

    # 顶层兜底：backend/main.py 内层 try 只覆盖了 inpaint 调用本身，
    # 模型加载、run() 前半段、merge_audio_to_video 等处的异常会绕过它，
    # 导致子进程被异常终止、前端只拿到一个无信息的退出码（常表现为 -1）。
    # 这里统一捕获并强制 flush，保证前端能从日志里看到真实异常（如 CUDA OOM）。
    try:
        sr.run()
    except Exception:
        print("[ERROR] Subtitle removal crashed with an uncaught exception:", flush=True)
        traceback.print_exc()
        # 强制刷新，避免崩溃前缓冲区里的 traceback 丢失
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        # 退出码 2：明确表示“后端捕获到 Python 异常”，区别于 -1（原生崩溃）与 1（逻辑未完成）
        sys.exit(2)

    if sr.isFinished:
        print("[PROGRESS] 100", flush=True)
        print("[SUCCESS] Subtitle removal completed successfully.", flush=True)
    else:
        print("[ERROR] Subtitle removal did not finish successfully.", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
