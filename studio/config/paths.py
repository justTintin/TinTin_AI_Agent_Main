import os
import sys

IS_WIN = True  # 工程仅支持 Windows

# ── 运行模式感知 ────────────────────────────────────────────────────────────
# 两种运行模式：
#   · 源码模式（开发）：从 studio/ 目录直接跑 .py，__file__ 指向真实磁盘路径。
#   · frozen 模式（发布）：PyInstaller 打包成 exe，代码在只读的 _MEIPASS 临时目录，
#     而可写数据/外部子系统必须在 exe 旁边的部署目录。
#
# 三个根目录：
#   _BUNDLE_DIR   只读资源根（打包进 exe 的 assets/内置bin/图标等）。frozen 时 = _MEIPASS。
#   PROJECT_ROOT  studio/ 根，可写数据大多派生自此。frozen 时 = 部署根/studio（可写）。
#   WORKSPACE_ROOT 工程根，apps/python_embeded 派生自此。frozen 时 = 部署根（exe 旁）。
#
# 设计权衡：绝大多数派生路径（config/data/logs/accounts/outputs）是【可写数据】，
# 所以 frozen 时 PROJECT_ROOT 指向可写部署目录，而非只读 _MEIPASS。
# 只读资源（assets、内置 bin、brand_dictionary）改用 BUNDLE_* 常量显式指向 _BUNDLE_DIR。
if getattr(sys, "frozen", False):
    # frozen 模式：exe 所在目录是部署根，所有可写数据/外部子系统都在这里
    WORKSPACE_ROOT = os.path.dirname(sys.executable)              # = exe 旁（可写）
    PROJECT_ROOT = os.path.join(WORKSPACE_ROOT, "studio")         # 可写数据根
    _BUNDLE_DIR = getattr(sys, "_MEIPASS", WORKSPACE_ROOT)        # 只读资源根
    _BUNDLE_STUDIO_DIR = os.path.join(_BUNDLE_DIR, "studio")      # 打包进去的 studio/ 资源
else:
    # 源码模式：保持原有行为
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # studio/
    WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)                               # 工程根
    _BUNDLE_DIR = PROJECT_ROOT                                                   # 资源也在 studio/
    _BUNDLE_STUDIO_DIR = PROJECT_ROOT

# Central runtime dir (studio/.runtime/)
RUNTIME_DIR = os.path.join(PROJECT_ROOT, ".runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
TMP_DIR = os.path.join(RUNTIME_DIR, "tmp")
COOKIES_DIR = os.path.join(RUNTIME_DIR, "cookies")
ACCOUNTS_DIR = os.path.join(PROJECT_ROOT, "accounts")

# ── 输出总目录（可在「系统设置 → 本地配置」中自定义）────────────────────
_DEFAULT_OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
_LOCAL_CFG_FILE = os.path.join(PROJECT_ROOT, "config", "local_config.json")

def _resolve_outputs_dir():
    """优先读取 local_config.json 中用户配置的 output_dir，否则回退默认值。"""
    try:
        if os.path.isfile(_LOCAL_CFG_FILE):
            import json as _json
            with open(_LOCAL_CFG_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            d = (data.get("output_dir") or data.get("cache_dir") or "").strip()
            if d:
                os.makedirs(d, exist_ok=True)
                return d
    except Exception:
        pass
    return _DEFAULT_OUTPUTS_DIR

OUTPUTS_DIR = _resolve_outputs_dir()
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
AI_CONFIG_FILE = os.path.join(CONFIG_DIR, "ai_config.json")
VIDEO_CONFIG_FILE = os.path.join(CONFIG_DIR, "video_config.json")
ERP_CONFIG_FILE = os.path.join(CONFIG_DIR, "erp_config.json")
UPDATE_CONFIG_FILE = os.path.join(CONFIG_DIR, "update.json")
CONFIG_INI_FILE = os.path.join(PROJECT_ROOT, "config.ini")
VOICE_SAMPLES_DIR = os.path.join(PROJECT_ROOT, "assets", "voice_samples")
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backups")
PRODUCT_LIBRARY_FILE = os.path.join(DATA_DIR, "product_library.json")
MY_KNOWLEDGE_FILE = os.path.join(DATA_DIR, "my_knowledge.json")
MEDIA_LIBRARY_FILE = os.path.join(DATA_DIR, "media_library.json")
TAG_LIBRARY_FILE = os.path.join(DATA_DIR, "tag_library.json")
PYTHON_EMBEDED_DIR = os.path.join(WORKSPACE_ROOT, "python_embeded")

# 只读资源（打包进 exe，frozen 时在 _BUNDLE_STUDIO_DIR；源码模式与 PROJECT_ROOT 相同）
BUNDLE_ASSETS_DIR = os.path.join(_BUNDLE_STUDIO_DIR, "assets")
BUNDLE_DATA_DIR = os.path.join(_BUNDLE_STUDIO_DIR, "data")
BRAND_DICTIONARY_FILE = os.path.join(BUNDLE_DATA_DIR, "brand_dictionary.json")
BUNDLE_ICONS_DIR = os.path.join(BUNDLE_ASSETS_DIR, "icons")
VOICE_SAMPLES_BUNDLE_DIR = os.path.join(BUNDLE_ASSETS_DIR, "voice_samples")

# apps/ paths（外部子系统，frozen 时在部署根/apps）
APPS_DIR = os.path.join(WORKSPACE_ROOT, "apps")
PW_BROWSERS_DIR = os.path.join(APPS_DIR, "pw-browsers")
WHISPER_MODELS_DIR = os.path.join(APPS_DIR, "whisper-models")
# 注：vsr-v1.1.1（旧版去字幕，已废弃删除）现统一指向 v1.4.0。
# VSR_DIR 仅为兼容旧代码（subtitle_removal_page 孤儿页）保留别名。
VSR_V14_DIR = os.path.join(APPS_DIR, "vsr-v1.4.0")
VSR_DIR = VSR_V14_DIR
# OCR 已迁移至服务端 POST /material/ocr，不再使用本地 PaddleOCR 环境/脚本。
# 原 PADDLEOCR_VENV_DIR/PADDLEOCR_PYTHON/PADDLEOCR_SCRIPT/IMAGE_FOLDER_OCR_SCRIPT 已移除。
REMBG_DIR = os.path.join(APPS_DIR, "rembg")
# 只读资源：assets 下的内置浏览器包（frozen 时在 _BUNDLE_DIR）
BUNDLED_PW_BROWSERS_ZIP = os.path.join(_BUNDLE_STUDIO_DIR, "assets", "playwright", "pw-browsers-win.zip")
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
# 浏览器扩展源码模块（随 apps/ 一起打包分发；运行时复制到 EXT_INSTALL_DIR 供浏览器加载）
EXTENSION_SRC_DIR = os.path.join(APPS_DIR, "browser-extension")
MATERIALS_DIR = os.path.join(OUTPUTS_DIR, "materials")
# JSON 元数据目录（固定项目内部，kb_items.json / kb_sync.json 存放于此）
KNOWLEDGE_MATERIALS_DIR = os.path.join(MATERIALS_DIR, "knowledge")
# 媒体文件存储目录（用户可配置，视频/图片等下载至此）
# 默认与 JSON 目录相同；可通过 data/knowledge_dir.json 的 media_dir 覆盖
KNOWLEDGE_MEDIA_DIR = os.path.join(MATERIALS_DIR, "knowledge")

# 素材目录平台默认值
MATERIALS_PLATFORM_DEFAULTS = [os.path.join(MATERIALS_DIR, "knowledge")]
HOTSPOTS_MATERIALS_DIR = os.path.join(MATERIALS_DIR, "hotspots")
HOTSPOTS_FILE = os.path.join(DATA_DIR, "hotspots.json")
VIDEO_PREDICTIONS_FILE = os.path.join(DATA_DIR, "video_predictions.json")
VIDEO_INDEX_FILE = os.path.join(DATA_DIR, "video_index.json")

# Platform-specific binary directories（内置 bin 是只读资源，frozen 时在 _BUNDLE_DIR）
BIN_DIR = os.path.join(_BUNDLE_STUDIO_DIR, "bin")
PLATFORM_DIR = "win"
BIN_PLATFORM_DIR = os.path.join(BIN_DIR, PLATFORM_DIR)

# Built-in binaries (resolved at import time via get_bin)
DREAMINA_EXE = None
OLLAMA_BIN = None


def get_bin(name):
    """Return full path to a platform-specific binary in bin/win/<name>.
    On Windows, auto-appends .exe.
    """
    bin_dir = BIN_PLATFORM_DIR
    candidates = [
        os.path.join(bin_dir, f"{name}.exe"),
        os.path.join(bin_dir, name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    import shutil
    found = shutil.which(f"{name}.exe")
    if found:
        return found
    return os.path.join(bin_dir, f"{name}.exe")


def init_bin_paths():
    global DREAMINA_EXE, OLLAMA_BIN
    DREAMINA_EXE = get_bin("dreamina")
    OLLAMA_BIN = get_bin("ollama")


init_bin_paths()

# Legacy compat aliases (prefer get_bin() for new code)
DREAMINA_EXE_LEGACY = DREAMINA_EXE

# knowledge_dir mapping override：仅覆盖媒体文件目录，JSON 元数据始终留在项目内
_kb_dir_cfg = os.path.join(DATA_DIR, "knowledge_dir.json")
if os.path.exists(_kb_dir_cfg):
    try:
        import json as _j
        with open(_kb_dir_cfg, encoding="utf-8") as _kf:
            _kd = _j.load(_kf)
        # 兼容旧字段名 materials_dir 和新字段名 media_dir
        _custom = (_kd.get("media_dir") or _kd.get("materials_dir") or "").strip()
        if _custom and os.path.isdir(_custom):
            KNOWLEDGE_MEDIA_DIR = _custom
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
