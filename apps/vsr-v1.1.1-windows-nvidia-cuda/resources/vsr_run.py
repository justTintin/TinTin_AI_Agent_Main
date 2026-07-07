import os
import sys

# 强制 stdout/stderr 使用 UTF-8 编码，避免 Windows cp1252 无法输出中文
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import time
import cv2
import threading

# Add resources and backend to system path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

import backend.main
import config

def poll_progress(sr, preview_path):
    last_prog = -1
    while not sr.isFinished:
        prog = int(sr.progress_total)
        if prog != last_prog:
            print(f"[PROGRESS] {prog}", flush=True)
            last_prog = prog
        if sr.preview_frame is not None:
            try:
                # Save preview frame for GUI display
                cv2.imwrite(preview_path, sr.preview_frame)
            except Exception:
                pass
        time.sleep(0.2)
    print("[PROGRESS] 100", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--ymin", type=int, default=0)
    parser.add_argument("--ymax", type=int, default=0)
    parser.add_argument("--xmin", type=int, default=0)
    parser.add_argument("--xmax", type=int, default=0)
    parser.add_argument("--mode", default="sttn")
    parser.add_argument("--skip_detect", action="store_true")
    parser.add_argument("--lama_fast", action="store_true")
    parser.add_argument("--h264", action="store_true")
    parser.add_argument("--preview_path", default="")
    args = parser.parse_args()

    # Override config variables
    config.MODE = config.InpaintMode(args.mode)
    config.STTN_SKIP_DETECTION = args.skip_detect
    config.LAMA_SUPER_FAST = args.lama_fast
    config.USE_H264 = args.h264

    sub_area = (args.ymin, args.ymax, args.xmin, args.xmax)
    # If all coordinate bounds are 0, process full screen or automatic detection
    if args.ymin == 0 and args.ymax == 0 and args.xmin == 0 and args.xmax == 0:
        sub_area = None

    print(f"[STARTING] Video: {args.video}, Mode: {args.mode}, Area: {sub_area}", flush=True)

    sr = backend.main.SubtitleRemover(args.video, sub_area, gui_mode=True)
    
    if args.preview_path:
        t = threading.Thread(target=poll_progress, args=(sr, args.preview_path), daemon=True)
        t.start()
        
    sr.run()
    print("[SUCCESS] Subtitle removal completed successfully.", flush=True)

if __name__ == "__main__":
    main()
