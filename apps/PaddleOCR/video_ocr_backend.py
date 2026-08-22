# -*- coding: utf-8 -*-
import os
import sys

# Prevent Windows DLL conflicts by mocking unused PyTorch modules before any other imports
from types import ModuleType
class DummySpec:
    def __init__(self, name):
        self.name = name
        self.loader = None
        self.origin = None
        self.submodule_search_locations = None
        self.has_location = False

class DummyMeta(type):
    def __getattr__(cls, name):
        return DummyClass

class DummyClass(metaclass=DummyMeta):
    def __init__(self, *args, **kwargs):
        pass
    def __getattr__(self, name):
        return DummyClass
    def __call__(self, *args, **kwargs):
        return self

class MockModule(object):
    def __init__(self, name):
        self.__name__ = name
        self.__path__ = []
        self.__spec__ = DummySpec(name)
        self.__version__ = "2.5.1"
        
    def __getattr__(self, name):
        if name == "is_available":
            return lambda: False
        return DummyClass

# Mock main packages
sys.modules["torch"] = MockModule("torch")
sys.modules["torchvision"] = MockModule("torchvision")
sys.modules["torchaudio"] = MockModule("torchaudio")

# Mock common submodules
mock_submods = [
    "torch.nn", "torch.nn.functional", "torch.utils", "torch.utils.data", 
    "torch.cuda", "torch.distributed", "torch.multiprocessing", 
    "torch.autograd", "torch.serialization", "torch.jit", 
    "torch.backends", "torch.backends.cudnn"
]
for name in mock_submods:
    sys.modules[name] = MockModule(name)

# Link submodules dynamically to torch
for sub in mock_submods:
    parts = sub.split(".")
    curr = sys.modules["torch"]
    for i, part in enumerate(parts[1:]):
        sub_path = "torch." + ".".join(parts[1:i+2])
        if not hasattr(curr, part):
            setattr(curr, part, sys.modules[sub_path])
        curr = getattr(curr, part)

import argparse
import cv2
import csv
import re
import shutil
import numpy as np

# Force PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK to True to avoid network delay
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

# Resolve absolute path to apps/PaddleOCR dynamically
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Force PADDLE_PDX_CACHE_HOME to local paddle-models directory inside apps/PaddleOCR
os.environ["PADDLE_PDX_CACHE_HOME"] = os.path.abspath(os.path.join(script_dir, "paddle-models"))

def integrate_local_models():
    user_paddlex_dir = os.path.join(os.path.expanduser("~"), ".paddlex", "official_models")
    local_paddlex_dir = os.path.join(script_dir, "paddle-models", "official_models")
    
    if os.path.exists(user_paddlex_dir) and not os.path.exists(local_paddlex_dir):
        print(f"[INFO] 正在将缓存的模型文件集成到本工程目录: {local_paddlex_dir} ...", flush=True)
        try:
            os.makedirs(local_paddlex_dir, exist_ok=True)
            for item in os.listdir(user_paddlex_dir):
                s_path = os.path.join(user_paddlex_dir, item)
                d_path = os.path.join(local_paddlex_dir, item)
                if os.path.isdir(s_path):
                    shutil.copytree(s_path, d_path)
                else:
                    shutil.copy2(s_path, d_path)
            print("[INFO] 本地模型文件集成成功！", flush=True)
        except Exception as e:
            print(f"[WARNING] 集成模型文件失败: {e}", flush=True)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--ymin", type=int, default=0)
    parser.add_argument("--ymax", type=int, default=0)
    parser.add_argument("--xmin", type=int, default=0)
    parser.add_argument("--xmax", type=int, default=0)
    parser.add_argument("--sample_interval", type=int, default=5, help="Process every N frames")
    parser.add_argument("--output", required=True, help="Output csv file path")
    parser.add_argument("--filter_mode", default="all", choices=["all", "numeric"], help="Filter mode")
    parser.add_argument("--preview_path", default="", help="Optional preview image output path")
    return parser.parse_args()

def extract_numbers(text):
    pattern = r"[-+]?\d*\.\d+|\d+"
    matches = re.findall(pattern, text)
    return " ".join(matches)

def format_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def main():
    integrate_local_models()
    args = parse_args()
    
    video_path = args.video
    if not os.path.exists(video_path):
        print(f"[ERROR] Video file not found: {video_path}", flush=True)
        sys.exit(-1)
        
    print(f"[STARTING] Video: {video_path}, Bounding Box: ({args.xmin}, {args.ymin}) -> ({args.xmax}, {args.ymax})", flush=True)
    
    try:
        if sys.platform == "win32":
            import ctypes
            python_dir = os.path.dirname(sys.executable)
            site_packages = os.path.join(python_dir, "Lib", "site-packages")
            nvidia_dir = os.path.join(site_packages, "nvidia")
            if os.path.exists(nvidia_dir):
                for sub in os.listdir(nvidia_dir):
                    bin_dir = os.path.join(nvidia_dir, sub, "bin")
                    if os.path.exists(bin_dir):
                        os.add_dll_directory(bin_dir)
                
                dlls = [
                    os.path.join(nvidia_dir, "cuda_runtime", "bin", "cudart64_12.dll"),
                    os.path.join(nvidia_dir, "cublas", "bin", "cublasLt64_12.dll"),
                    os.path.join(nvidia_dir, "cublas", "bin", "cublas64_12.dll"),
                    os.path.join(nvidia_dir, "cudnn", "bin", "cudnn64_9.dll"),
                    os.path.join(nvidia_dir, "cudnn", "bin", "cudnn_adv64_9.dll"),
                    os.path.join(nvidia_dir, "cudnn", "bin", "cudnn_ops64_9.dll"),
                    os.path.join(nvidia_dir, "cudnn", "bin", "cudnn_cnn64_9.dll"),
                ]
                for d in dlls:
                    if os.path.exists(d):
                        try:
                            ctypes.windll.kernel32.LoadLibraryExW(d, None, 0x00000008)
                        except Exception:
                            pass

        import paddle
        import paddleocr
        from paddleocr import PaddleOCR
        use_gpu = paddle.device.is_compiled_with_cuda()
        print(f"[INFO] Paddle compiled with CUDA: {use_gpu}", flush=True)
        device = "gpu" if use_gpu else "cpu"
        ocr = PaddleOCR(device=device)
        print("[INFO] PaddleOCR initialized successfully from local environment.", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Failed to initialize PaddleOCR: {e}", flush=True)
        sys.exit(-1)
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERROR] Failed to open video: {video_path}", flush=True)
        sys.exit(-1)
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0
    print(f"[INFO] Total frames: {total_frames}, FPS: {fps}", flush=True)
    
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    
    results = []
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        
        if (frame_idx - 1) % args.sample_interval == 0:
            timestamp_sec = (frame_idx - 1) / fps
            time_str = format_time(timestamp_sec)
            
            img_h, img_w = frame.shape[:2]
            ymin = max(0, min(args.ymin, img_h))
            ymax = max(0, min(args.ymax, img_h))
            xmin = max(0, min(args.xmin, img_w))
            xmax = max(0, min(args.xmax, img_w))
            
            if ymax > ymin and xmax > xmin:
                roi = frame[ymin:ymax, xmin:xmax]
            else:
                roi = frame
                
            if args.preview_path:
                try:
                    cv2.imwrite(args.preview_path, roi)
                except Exception:
                    pass
                    
            try:
                ocr_res = list(ocr.predict(input=roi))
                
                texts = []
                scores = []
                for res in ocr_res:
                    if 'rec_texts' in res:
                        if isinstance(res['rec_texts'], list):
                            texts.extend(res['rec_texts'])
                            scores.extend(res['rec_scores'])
                        else:
                            texts.append(res['rec_texts'])
                            scores.append(res['rec_scores'])
                            
                recognized_text = " ".join(texts)
                avg_score = np.mean(scores) if scores else 0.0
                
                extracted = recognized_text
                if args.filter_mode == "numeric":
                    extracted = extract_numbers(recognized_text)
                    
                if recognized_text.strip():
                    print(f"[OCR] Frame: {frame_idx} | Time: {time_str} | Text: {recognized_text} | Extracted: {extracted}", flush=True)
                    results.append({
                        "frame": frame_idx,
                        "time": time_str,
                        "raw_text": recognized_text,
                        "extracted_value": extracted,
                        "confidence": f"{avg_score:.4f}"
                    })
            except Exception as e:
                print(f"[WARNING] OCR failed at frame {frame_idx}: {e}", flush=True)
                
        if total_frames > 0:
            progress_percent = int((frame_idx / total_frames) * 100)
            progress_percent = min(99, progress_percent)
            print(f"[PROGRESS] {progress_percent}", flush=True)
            
    cap.release()
    
    try:
        with open(args.output, 'w', newline='', encoding='utf-8-sig') as csvfile:
            fieldnames = ["帧号", "时间戳", "原始识别文本", "提取数值(温度/数字)", "置信度"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "帧号": r["frame"],
                    "时间戳": r["time"],
                    "原始识别文本": r["raw_text"],
                    "提取数值(温度/数字)": r["extracted_value"],
                    "置信度": r["confidence"]
                })
        print(f"[PROGRESS] 100", flush=True)
        print(f"[SUCCESS] OCR scanning completed. Results saved to: {args.output}", flush=True)
    except Exception as e:
        print(f"[ERROR] Failed to save CSV file: {e}", flush=True)
        sys.exit(-1)

if __name__ == "__main__":
    main()
