import os
import sys

IS_WIN = sys.platform == "win32"

# Project root (studio/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Workspace root (TinTin_AI_Agent/)
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)

# Central runtime dir (studio/.runtime/)
RUNTIME_DIR = os.path.join(PROJECT_ROOT, ".runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
COOKIES_DIR = os.path.join(RUNTIME_DIR, "cookies")
ACCOUNTS_DIR = os.path.join(PROJECT_ROOT, "accounts")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
AI_CONFIG_FILE = os.path.join(CONFIG_DIR, "ai_config.json")
ERP_CONFIG_FILE = os.path.join(CONFIG_DIR, "erp_config.json")
CONFIG_INI_FILE = os.path.join(PROJECT_ROOT, "config.ini")
VOICE_SAMPLES_DIR = os.path.join(PROJECT_ROOT, "assets", "voice_samples")
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
PRODUCT_LIBRARY_FILE = os.path.join(DATA_DIR, "product_library.json")
MY_KNOWLEDGE_FILE = os.path.join(DATA_DIR, "my_knowledge.json")
MEDIA_LIBRARY_FILE = os.path.join(DATA_DIR, "media_library.json")
TAG_LIBRARY_FILE = os.path.join(DATA_DIR, "tag_library.json")
PYTHON_EMBEDED_DIR = os.path.join(WORKSPACE_ROOT, "python_embeded")

# apps/ paths
APPS_DIR = os.path.join(WORKSPACE_ROOT, "apps")
PW_BROWSERS_DIR = os.path.join(APPS_DIR, "pw-browsers")
WHISPER_MODELS_DIR = os.path.join(APPS_DIR, "whisper-models")
VSR_DIR = os.path.join(APPS_DIR, "vsr-v1.1.1-windows-nvidia-cuda")
VSR_V14_DIR = os.path.join(APPS_DIR, "vsr-v1.4.0")
PADDLEOCR_VENV_DIR = os.path.join(APPS_DIR, "vsr-v1.4.0", "Python")
PADDLEOCR_PYTHON = os.path.join(PADDLEOCR_VENV_DIR, "python.exe" if IS_WIN else "bin/python")
if not os.path.isfile(PADDLEOCR_PYTHON):
    from utils.platform_utils import find_python
    PADDLEOCR_PYTHON = find_python()
PADDLEOCR_SCRIPT = os.path.join(APPS_DIR, "PaddleOCR", "video_ocr_backend.py")
IMAGE_FOLDER_OCR_SCRIPT = os.path.join(APPS_DIR, "PaddleOCR", "image_folder_ocr_backend.py")
REMBG_DIR = os.path.join(APPS_DIR, "rembg")
BUNDLED_PW_BROWSERS_ZIP = os.path.join(PROJECT_ROOT, "assets", "playwright", "pw-browsers-win.zip")
CREATOR_CONTENT_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
DREAMINA_OUTPUT_DIR = os.path.join(OUTPUTS_DIR, "dreamina")
COVER_OUTPUT_DIR = os.path.join(OUTPUTS_DIR, "covers")
FINAL_OUTPUT_DIR = os.path.join(OUTPUTS_DIR, "final")
MG_OUTPUT_DIR = os.path.join(OUTPUTS_DIR, "mg")
REMOTION_DIR = os.path.join(PROJECT_ROOT, "remotion")
VOXCPM2_DIR = os.path.join(APPS_DIR, "voxcpm2")
QWEN_IMAGE_LAYERED_DIR = os.path.join(APPS_DIR, "Qwen-Image-Layered")
COMFYUI_DIR = os.path.join(APPS_DIR, "comfyui")
ASSET_BROWSER_DIR = os.path.join(APPS_DIR, "asset-browser")
MATERIALS_DIR = os.path.join(OUTPUTS_DIR, "materials")
KNOWLEDGE_MATERIALS_DIR = os.path.join(MATERIALS_DIR, "knowledge")
HOTSPOTS_MATERIALS_DIR = os.path.join(MATERIALS_DIR, "hotspots")
HOTSPOTS_FILE = os.path.join(DATA_DIR, "hotspots.json")
VIDEO_PREDICTIONS_FILE = os.path.join(DATA_DIR, "video_predictions.json")
VIDEO_INDEX_FILE = os.path.join(DATA_DIR, "video_index.json")

# Platform-specific binary directories
BIN_DIR = os.path.join(PROJECT_ROOT, "bin")
PLATFORM_DIR = "win" if IS_WIN else ("linux" if sys.platform == "linux" else "darwin")
BIN_PLATFORM_DIR = os.path.join(BIN_DIR, PLATFORM_DIR)

# Built-in binaries (resolved at import time via get_bin)
DREAMINA_EXE = None
OLLAMA_BIN = None


def get_bin(name):
    """Return full path to a platform-specific binary in bin/<platform>/<name>.
    On Windows, auto-appends .exe.
    """
    bin_dir = BIN_PLATFORM_DIR
    if IS_WIN:
        candidates = [
            os.path.join(bin_dir, f"{name}.exe"),
            os.path.join(bin_dir, name),
        ]
    else:
        candidates = [
            os.path.join(bin_dir, name),
            os.path.join(bin_dir, f"{name}.exe"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    import shutil
    found = shutil.which(name if not IS_WIN else f"{name}.exe")
    if found:
        return found
    return os.path.join(bin_dir, f"{name}.exe" if IS_WIN else name)


def init_bin_paths():
    global DREAMINA_EXE, OLLAMA_BIN
    DREAMINA_EXE = get_bin("dreamina")
    OLLAMA_BIN = get_bin("ollama")


init_bin_paths()

# Legacy compat aliases (prefer get_bin() for new code)
DREAMINA_EXE_LEGACY = DREAMINA_EXE

# knowledge_dir mapping override
_kb_dir_cfg = os.path.join(DATA_DIR, "knowledge_dir.json")
if os.path.exists(_kb_dir_cfg):
    try:
        import json as _j
        with open(_kb_dir_cfg, encoding="utf-8") as _kf:
            _kd = _j.load(_kf)
        _custom = (_kd.get("materials_dir") or "").strip()
        if _custom and os.path.isdir(_custom):
            KNOWLEDGE_MATERIALS_DIR = _custom
    except Exception:
        pass

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)
os.makedirs(COOKIES_DIR, exist_ok=True)
os.makedirs(ACCOUNTS_DIR, exist_ok=True)
os.makedirs(WHISPER_MODELS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

_old_product_file = os.path.join(DATA_DIR, "knowledge_base.json")
if os.path.exists(_old_product_file) and not os.path.exists(PRODUCT_LIBRARY_FILE):
    try:
        os.rename(_old_product_file, PRODUCT_LIBRARY_FILE)
    except OSError:
        pass
