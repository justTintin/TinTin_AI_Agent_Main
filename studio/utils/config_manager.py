"""
统一配置读写入口（config_manager）。

所有配置文件统一通过本模块读写，页面/工具不再直接操作文件路径：
- JSON 配置：ai_config / local_config / video_config / update / theme /
             material_index / erp
- INI 配置：根目录 config.ini（飞书 / VoxCPM 等）

用法：
    from utils import config_manager as cm
    cfg = cm.get_ai_config()
    cm.save_ai_config(cfg)
    cm.set_setting("local_config", "media_dir", path)
    parser = cm.load_ini()
    cm.save_ini(parser)
"""
import configparser
import json
import os

from config.paths import (
    AI_CONFIG_FILE,
    CONFIG_DIR,
    CONFIG_INI_FILE,
    DATA_DIR,
    ERP_CONFIG_FILE,
    UPDATE_CONFIG_FILE,
    VIDEO_CONFIG_FILE,
)

# JSON 配置文件注册表：逻辑名 → 实际路径（新增配置文件时在这里登记）
_JSON_FILES = {
    "ai_config": AI_CONFIG_FILE,
    "local_config": os.path.join(CONFIG_DIR, "local_config.json"),
    "video_config": VIDEO_CONFIG_FILE,
    "erp_config": ERP_CONFIG_FILE,
    "update": UPDATE_CONFIG_FILE,
    "theme": os.path.join(CONFIG_DIR, "theme.json"),
    "material_index": os.path.join(CONFIG_DIR, "material_index_config.json"),
    "knowledge_dir": os.path.join(DATA_DIR, "knowledge_dir.json"),
}


def _path_of(name):
    p = _JSON_FILES.get(name)
    if not p:
        raise ValueError(f"未知配置项: {name}（可用: {', '.join(_JSON_FILES)}）")
    return p


def load_config(name, default=None):
    """读取 JSON 配置文件；不存在或损坏时返回 default（默认 {}）。"""
    if default is None:
        default = {}
    try:
        p = _path_of(name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return default


def save_config(name, data):
    """写回 JSON 配置文件（原子写：临时文件 + os.replace）。"""
    try:
        p = _path_of(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def get_setting(name, key, default=None):
    """读取单个配置键。"""
    return load_config(name).get(key, default)


def set_setting(name, key, value):
    """更新单个配置键并写回；成功返回 True。"""
    cfg = load_config(name)
    cfg[key] = value
    return save_config(name, cfg)


def clear_config(name):
    """删除整个配置文件（用于恢复默认）；成功返回 True。"""
    try:
        p = _path_of(name)
        if os.path.exists(p):
            os.remove(p)
        return True
    except OSError:
        return False


def get_ai_config():
    """读取 AI 服务配置（ai_config.json）。"""
    return load_config("ai_config")


def save_ai_config(cfg):
    """写回 AI 服务配置。"""
    return save_config("ai_config", cfg)


def load_ini():
    """读取根目录 config.ini（不存在时返回空 parser）。"""
    parser = configparser.ConfigParser()
    try:
        if os.path.isfile(CONFIG_INI_FILE):
            parser.read(CONFIG_INI_FILE, encoding="utf-8")
    except OSError:
        pass
    return parser


def save_ini(parser):
    """写回根目录 config.ini；成功返回 True。"""
    try:
        with open(CONFIG_INI_FILE, "w", encoding="utf-8") as f:
            parser.write(f)
        return True
    except OSError:
        return False
