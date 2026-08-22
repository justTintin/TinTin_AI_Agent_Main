# -*- coding: utf-8 -*-
import os
import sys
import argparse
import cv2
import csv
import re
import shutil
import numpy as np

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
    # Batch OCR arguments
    parser.add_argument("--folder", default="", help="Input image folder path")
    parser.add_argument("--key", default="", help="Anchor/Key text to search for")
    parser.add_argument("--output", default="", help="Output csv or txt file path")
    
    # Test OCR mode arguments
    parser.add_argument("--test_mode", action="store_true", help="Run OCR in test mode on a single image")
    parser.add_argument("--image", default="", help="Path to single image for testing")
    parser.add_argument("--ymin", type=int, default=0)
    parser.add_argument("--ymax", type=int, default=0)
    parser.add_argument("--xmin", type=int, default=0)
    parser.add_argument("--xmax", type=int, default=0)
    
    return parser.parse_args()

def normalize_text(s):
    s = s.strip().lower()
    # remove spaces
    s = s.replace(" ", "")
    # remove common punctuation and separators
    for char in [":", "：", "-", "_", ",", ".", ";", "；", "=", " "]:
        s = s.replace(char, "")
    return s

def extract_value_for_key(key_text, texts, polys):
    norm_key = normalize_text(key_text)
    if not norm_key:
        return None, ""

    key_idx = -1
    for i, t in enumerate(texts):
        if norm_key in normalize_text(t):
            key_idx = i
            break

    if key_idx == -1:
        return None, ""

    key_block_text = texts[key_idx]
    
    # Try to clean the key string from the text block using case-insensitive regex
    cleaned_block_text = re.sub(re.escape(key_text), "", key_block_text, flags=re.IGNORECASE)
    cleaned_block_text = cleaned_block_text.strip()
    while cleaned_block_text and cleaned_block_text[0] in [":", "：", "-", "_", "=", " ", "\t"]:
        cleaned_block_text = cleaned_block_text[1:].strip()

    # Strip trailing "复制" if present
    if cleaned_block_text.endswith("复制"):
        cleaned_block_text = cleaned_block_text[:-2].strip()
    if cleaned_block_text.endswith("copy"):
        cleaned_block_text = cleaned_block_text[:-4].strip()

    # If the remaining block text contains value, we use it
    if cleaned_block_text:
        return cleaned_block_text, key_block_text

    # Otherwise, look for blocks using two-step selection
    key_poly = polys[key_idx]
    k_xmin = min(p[0] for p in key_poly)
    k_xmax = max(p[0] for p in key_poly)
    k_ymin = min(p[1] for p in key_poly)
    k_ymax = max(p[1] for p in key_poly)
    k_cx = (k_xmin + k_xmax) / 2.0
    k_cy = (k_ymin + k_ymax) / 2.0
    k_h = k_ymax - k_ymin
    k_w = k_xmax - k_xmin

    # Step 1: Look for candidates to the right (same line)
    right_candidates = []
    for i, t in enumerate(texts):
        if i == key_idx:
            continue
        poly = polys[i]
        xmin = min(p[0] for p in poly)
        xmax = max(p[0] for p in poly)
        ymin = min(p[1] for p in poly)
        ymax = max(p[1] for p in poly)
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        
        # B is to the right of K: B's xmin > K's center x, and vertical center overlap is high
        if (xmin > k_cx) and (abs(cy - k_cy) < k_h * 1.2):
            dist = xmin - k_xmax
            right_candidates.append((i, dist))
            
    if right_candidates:
        right_candidates.sort(key=lambda x: x[1])
        best_idx = right_candidates[0][0]
        best_text = texts[best_idx].strip()
        
        # Strip common leading separators
        while best_text and best_text[0] in [":", "：", "-", "_", "=", " ", "\t"]:
            best_text = best_text[1:].strip()
        if best_text.endswith("复制"):
            best_text = best_text[:-2].strip()
        if best_text.endswith("copy"):
            best_text = best_text[:-4].strip()
        return best_text, key_block_text

    # Step 2: If no candidate to the right, look for candidates below
    below_candidates = []
    for i, t in enumerate(texts):
        if i == key_idx:
            continue
        poly = polys[i]
        xmin = min(p[0] for p in poly)
        xmax = max(p[0] for p in poly)
        ymin = min(p[1] for p in poly)
        ymax = max(p[1] for p in poly)
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        
        # B is below K: B's ymin > K's center y, and horizontal center overlap is high
        if (ymin > k_cy) and (abs(cx - k_cx) < k_w * 1.5):
            dist = ymin - k_ymax
            below_candidates.append((i, dist))
            
    if below_candidates:
        below_candidates.sort(key=lambda x: x[1])
        best_idx = below_candidates[0][0]
        best_text = texts[best_idx].strip()
        
        # Strip common leading separators
        while best_text and best_text[0] in [":", "：", "-", "_", "=", " ", "\t"]:
            best_text = best_text[1:].strip()
        if best_text.endswith("复制"):
            best_text = best_text[:-2].strip()
        if best_text.endswith("copy"):
            best_text = best_text[:-4].strip()
        return best_text, key_block_text

    return None, key_block_text

def main():
    integrate_local_models()
    args = parse_args()
    
    # Initialize PaddleOCR with Windows DLL Loading logic
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
        from paddleocr import PaddleOCR
        use_gpu = paddle.device.is_compiled_with_cuda()
        print(f"[INFO] Paddle compiled with CUDA: {use_gpu}", flush=True)
        device = "gpu" if use_gpu else "cpu"
        ocr = PaddleOCR(device=device)
        print("[INFO] PaddleOCR 初始化成功。", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] 初始化 PaddleOCR 失败: {e}", flush=True)
        sys.exit(-1)

    if args.test_mode:
        # TEST MODE: crop selection area on a single image and run OCR
        if not args.image or not os.path.exists(args.image):
            print(f"[ERROR] Test image path not found: {args.image}", flush=True)
            sys.exit(-1)
            
        print(f"[STARTING] Test Image: {args.image}, BBox: ({args.xmin}, {args.ymin}) -> ({args.xmax}, {args.ymax})", flush=True)
        
        try:
            # Read image using OpenCV with unicode support
            img = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                print(f"[ERROR] Failed to load image: {args.image}", flush=True)
                sys.exit(-1)
                
            img_h, img_w = img.shape[:2]
            ymin = max(0, min(args.ymin, img_h))
            ymax = max(0, min(args.ymax, img_h))
            xmin = max(0, min(args.xmin, img_w))
            xmax = max(0, min(args.xmax, img_w))
            
            if ymax > ymin and xmax > xmin:
                roi = img[ymin:ymax, xmin:xmax]
            else:
                roi = img
                
            res = list(ocr.predict(input=roi))
            texts = []
            if res:
                rec_texts = res[0].get("rec_texts", [])
                if isinstance(rec_texts, list):
                    texts.extend(rec_texts)
                elif rec_texts:
                    texts.append(rec_texts)
                    
            recognized_text = " ".join(texts)
            print(f"[TEST_RESULT] Text: {recognized_text}", flush=True)
            print("[PROGRESS] 100", flush=True)
            print("[SUCCESS] Test OCR completed.", flush=True)
        except Exception as e:
            print(f"[ERROR] Test OCR failed: {e}", flush=True)
            sys.exit(-1)
            
    else:
        # BATCH MODE: process a folder of images
        folder_path = args.folder
        if not folder_path or not os.path.exists(folder_path):
            print(f"[ERROR] Folder path not found: {folder_path}", flush=True)
            sys.exit(-1)
            
        output_path = args.output
        if not output_path:
            print("[ERROR] Output file path not specified.", flush=True)
            sys.exit(-1)
            
        key_text = args.key
        if not key_text:
            print("[ERROR] Key text/Anchor text not specified.", flush=True)
            sys.exit(-1)
            
        # Find all images
        valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff")
        images = []
        for file in os.listdir(folder_path):
            if file.lower().endswith(valid_exts):
                images.append(os.path.join(folder_path, file))
                
        if not images:
            print(f"[ERROR] No valid images found in folder: {folder_path}", flush=True)
            sys.exit(-1)
            
        print(f"[STARTING] Batch OCR: Folder={folder_path}, Count={len(images)}, Key='{key_text}'", flush=True)
        
        results = []
        for idx, img_path in enumerate(images):
            basename = os.path.basename(img_path)
            try:
                # Load image with unicode support
                img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    print(f"[WARNING] Failed to load image, skipping: {img_path}", flush=True)
                    continue
                    
                res = list(ocr.predict(input=img))
                if res:
                    texts = res[0].get("rec_texts", [])
                    polys = res[0].get("dt_polys", [])
                    
                    extracted_val, raw_block = extract_value_for_key(key_text, texts, polys)
                    
                    if extracted_val is not None:
                        print(f"[OCR] Image: {basename} | Extracted: {extracted_val} | Text Block: {raw_block}", flush=True)
                        results.append({
                            "image": basename,
                            "path": img_path,
                            "extracted": extracted_val,
                            "raw": raw_block
                        })
                    else:
                        print(f"[OCR] Image: {basename} | [未定位到关键词 '{key_text}']", flush=True)
                        results.append({
                            "image": basename,
                            "path": img_path,
                            "extracted": "",
                            "raw": ""
                        })
                else:
                    print(f"[OCR] Image: {basename} | [未识别到文本]", flush=True)
                    results.append({
                        "image": basename,
                        "path": img_path,
                        "extracted": "",
                        "raw": ""
                    })
            except Exception as e:
                print(f"[WARNING] OCR failed for image {basename}: {e}", flush=True)
                results.append({
                    "image": basename,
                    "path": img_path,
                    "extracted": f"Error: {e}",
                    "raw": ""
                })
                
            progress = int(((idx + 1) / len(images)) * 100)
            progress = min(99, progress)
            print(f"[PROGRESS] {progress}", flush=True)
            
        # Write output
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            
            # Check if output_path is locked; if so, try appending _1, _2...
            save_path = output_path
            count = 1
            base, ext = os.path.splitext(output_path)
            while True:
                try:
                    # Test if we can open it for writing
                    with open(save_path, "a") as f:
                        pass
                    break
                except (IOError, PermissionError):
                    save_path = f"{base}_{count}{ext}"
                    count += 1
                    if count > 100:
                        break

            if save_path != output_path:
                print(f"[WARNING] 目标文件已被占用打开，已自动另存为: {save_path}", flush=True)

            is_csv = save_path.lower().endswith(".csv")
            if is_csv:
                with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["图片名称", f"提取值 ({key_text})", "包含关键词文本块", "文件完整路径"])
                    for r in results:
                        writer.writerow([r["image"], r["extracted"], r["raw"], r["path"]])
            else:
                # Text format
                with open(save_path, "w", encoding="utf-8") as f:
                    for r in results:
                        val = r["extracted"] if r["extracted"] else "(未匹配到)"
                        f.write(f"{r['image']}: {val}\n")
                        
            print("[PROGRESS] 100", flush=True)
            print(f"[SUCCESS] OCR scanning completed. Results saved to: {save_path}", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to save output file: {e}", flush=True)
            sys.exit(-1)

if __name__ == "__main__":
    main()
