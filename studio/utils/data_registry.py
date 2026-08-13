# -*- coding: utf-8 -*-
"""
工程数据登记表 —— 所有「值得备份/迁移」的数据在这里统一声明（唯一真相源）。

以前数据散落在 config/ data/ accounts/ assets/，谁要备份都得各自硬编码一遍。
现在统一登记：备份/还原/迁移都遍历 DATA_ITEMS，新增数据只要在此加一行。

字段：
  key       : 稳定标识
  label     : 中文名
  path      : 绝对路径（文件或目录）
  category  : "config"(配置/密钥) | "business"(业务核心数据)
  sensitive : 是否含密钥/登录态（导出时可选排除）
  kind      : "file" | "dir"
"""
import os

from config.paths import (
    PROJECT_ROOT, AI_CONFIG_FILE, ERP_CONFIG_FILE, CONFIG_INI_FILE,
    PRODUCT_LIBRARY_FILE, MY_KNOWLEDGE_FILE, MEDIA_LIBRARY_FILE,
    ACCOUNTS_DIR, VOICE_SAMPLES_DIR, OUTPUTS_DIR,
    VIDEO_CONFIG_FILE, CONFIG_DIR, SKILLS_DIR,
)

DATA_ITEMS = [
    # ---- 配置（含密钥）----
    {"key": "ai_config", "label": "AI/大模型配置", "path": AI_CONFIG_FILE,
     "category": "config", "sensitive": True, "kind": "file"},
    {"key": "video_config", "label": "视频配置(LUT映射)", "path": VIDEO_CONFIG_FILE,
     "category": "config", "sensitive": False, "kind": "file"},
    {"key": "local_config", "label": "本地配置(缓存目录)", "path": os.path.join(CONFIG_DIR, "local_config.json"),
     "category": "config", "sensitive": False, "kind": "file"},
    {"key": "erp_config", "label": "旺店通ERP配置", "path": ERP_CONFIG_FILE,
     "category": "config", "sensitive": True, "kind": "file"},
    {"key": "config_ini", "label": "VoxCPM等设置(config.ini)", "path": CONFIG_INI_FILE,
     "category": "config", "sensitive": True, "kind": "file"},
    # ---- 业务核心数据 ----
    {"key": "product_library", "label": "产品资料", "path": PRODUCT_LIBRARY_FILE,
     "category": "business", "sensitive": False, "kind": "file"},
    {"key": "my_knowledge", "label": "我的知识库", "path": MY_KNOWLEDGE_FILE,
     "category": "business", "sensitive": False, "kind": "file"},
    {"key": "media_library", "label": "素材库索引", "path": MEDIA_LIBRARY_FILE,
     "category": "business", "sensitive": False, "kind": "file"},
    {"key": "accounts", "label": "抖音账号(含登录态)", "path": ACCOUNTS_DIR,
     "category": "business", "sensitive": True, "kind": "dir"},
    {"key": "voice_samples", "label": "声音样本库", "path": VOICE_SAMPLES_DIR,
     "category": "business", "sensitive": False, "kind": "dir"},
    {"key": "skills", "label": "已安装技能", "path": SKILLS_DIR,
     "category": "business", "sensitive": False, "kind": "dir"},
]

# 产出物（大、可再生，默认不进备份，导出时可单独勾选）
OUTPUTS_ITEM = {"key": "outputs", "label": "生成产出(outputs)", "path": OUTPUTS_DIR,
                "category": "outputs", "sensitive": False, "kind": "dir"}


def rel_path(abspath):
    """转成相对 PROJECT_ROOT 的路径（zip 内统一用它，还原时按此放回）。"""
    return os.path.relpath(abspath, PROJECT_ROOT).replace("\\", "/")


def selected_items(include_secrets=True, include_outputs=False):
    """按选项返回要处理的数据项列表。"""
    items = [it for it in DATA_ITEMS if include_secrets or not it["sensitive"]]
    if include_outputs:
        items = items + [OUTPUTS_ITEM]
    return items


def summarize():
    """返回每项的存在性与大小，供 UI 展示。"""
    out = []
    for it in DATA_ITEMS + [OUTPUTS_ITEM]:
        p = it["path"]
        exists = os.path.exists(p)
        size = 0
        if exists:
            if it["kind"] == "file":
                size = os.path.getsize(p)
            else:
                for root, _d, files in os.walk(p):
                    for f in files:
                        try:
                            size += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
        out.append({**it, "exists": exists, "size": size})
    return out
