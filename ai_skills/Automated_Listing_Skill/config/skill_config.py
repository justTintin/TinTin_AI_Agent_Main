# -*- coding: utf-8 -*-
"""
抖店自动上架技能 - 配置文件
所有外部数据路径统一管理，方便修改
"""

import os
import shutil

# ============================================================
# 基础路径配置
# ============================================================

# 技能根目录（向上两级到SKILL_ROOT）
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(SKILL_ROOT, "data")

# 日志目录
LOGS_DIR = os.path.join(SKILL_ROOT, "logs")

# Chrome用户数据目录（浏览器自动化用）
CHROME_USER_DATA = os.path.join(SKILL_ROOT, "chrome_user_data")

# Chrome可执行文件路径
def _detect_chrome_exe_path() -> str:
    env_path = (os.environ.get("ALS_CHROME_EXE_PATH") or os.environ.get("CHROME_EXE_PATH") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    for cmd in ("chrome", "chrome.exe"):
        found = shutil.which(cmd)
        if found and os.path.isfile(found):
            return found

    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    program_files_x86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    local_app_data = os.environ.get("LocalAppData") or os.path.join(os.path.expanduser("~"), "AppData", "Local")

    candidates = [
        os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    return ""


CHROME_EXE_PATH = _detect_chrome_exe_path()


def get_chrome_exe() -> str:
    """
    返回 Chrome 可执行文件路径。
    优先级：环境变量 ALS_CHROME_EXE_PATH / CHROME_EXE_PATH > PATH > 常见安装目录。
    若未找到则抛出 FileNotFoundError。
    """
    path = _detect_chrome_exe_path()
    if not path:
        raise FileNotFoundError(
            "未找到 chrome.exe。"
            "请安装 Chrome，或通过环境变量 ALS_CHROME_EXE_PATH 指定路径。"
        )
    return path

# ============================================================
# 抖店上架数据路径（从抖店导出的xls文件）
# ============================================================

def _default_sync_root() -> str:
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    if os.path.isdir(docs):
        return os.path.join(docs, "WorkBuddy", "上架数据")
    return os.path.join(home, "WorkBuddy", "上架数据")


LISTING_DATA_DIR = (os.environ.get("ALS_SYNC_ROOT") or "").strip() or _default_sync_root()

# 默认上架数据xls文件名
LISTING_XLS_NAME = "sku.xlsx"

# 获取上架数据完整路径
def get_listing_xls_path(subdir=None):
    """获取上架数据xls文件路径"""
    if subdir:
        return os.path.join(LISTING_DATA_DIR, subdir, LISTING_XLS_NAME)
    return os.path.join(LISTING_DATA_DIR, LISTING_XLS_NAME)

# ============================================================
# ERP数据配置
# ============================================================

# ERP数据缓存目录
ERP_CACHE_DIR = os.path.join(DATA_DIR, "erp_cache")

# ERP数据文件
ERP_SUITES_DATA = os.path.join(ERP_CACHE_DIR, "erp_suites_data.json")
ERP_SUITES_LIST = os.path.join(ERP_CACHE_DIR, "erp_suites_list.txt")

# 商家编码处理结果
SKU_NEW_CODES_JSON = os.path.join(LISTING_DATA_DIR, "sku_new_codes.json")

# ============================================================
# 浏览器自动化配置
# ============================================================

# Chrome远程调试端口
CHROME_DEBUG_PORT = 9222



# 多店铺配置：指定不同店铺的具体后台首页地址
DOUYIN_STORES = {
    "juyou": {
        "name": "桔柚数码外设严选",
        "aliases": ["桔柚", "juyou"],
        "homepage_url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index?btm_ppre=a2427.b21452.c0.d0&btm_pre=a2427.b76571.c4158.d20759_i0&btm_show_id=a0a434d5-9b52-4316-832f-ef3caf135f06"
    },
    "555_battery": {
        "name": "555井韵电池店铺",
        "aliases": ["555", "井韵"],
        "homepage_url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index?btm_ppre=a2427.b76571.c902327.d871297&btm_pre=a2427.b76571.c4158.d20759_i0&btm_show_id=5ffcc8f5-50e2-4009-b5fe-9bf06a2060ff"
    }
}

# 浏览器等待超时（秒）
BROWSER_TIMEOUT = 30

# ============================================================
# 输出结果目录
# ============================================================

# 发布结果保存目录
RESULT_DIR = os.environ.get("ALS_RESULT_DIR", os.path.join(SKILL_ROOT, "data", "results"))

# 确保必要的目录存在
def ensure_dirs():
    """确保所有必要目录存在"""
    dirs = [DATA_DIR, LOGS_DIR, ERP_CACHE_DIR, RESULT_DIR, LISTING_DATA_DIR, CHROME_USER_DATA]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
