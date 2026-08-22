"""共用测试工具：路径设置、样本路径、服务端地址解析。"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # tests/
PROJECT_ROOT = os.path.dirname(TESTS_DIR)                                  # 工程根
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
SAMPLES_DIR = os.path.join(TESTS_DIR, "samples")
SAMPLE_VIDEO = os.path.join(SAMPLES_DIR, "video", "sample_gradient_2s.avi")
SAMPLE_IMAGE = os.path.join(SAMPLES_DIR, "image", "sample_gradient_640x480.png")
SAMPLE_AUDIO = os.path.join(SAMPLES_DIR, "audio", "test_tone_1s.wav")


def ensure_studio_on_path():
    """把 studio/ 加入 sys.path，使 `config`/`utils`/`core` 包可导入（与应用运行方式一致）。"""
    if STUDIO_DIR not in sys.path:
        sys.path.insert(0, STUDIO_DIR)
    return STUDIO_DIR


def find_tool(name):
    import shutil
    p = shutil.which(name)
    if p:
        return p
    # 工程根目录的 ffplay/ffprobe 等
    cand = os.path.join(PROJECT_ROOT, name)
    if os.path.isfile(cand):
        return cand
    return None


def read_config_json(rel_path, default=None):
    """安全读取 studio 下 JSON 配置（UTF-8）。"""
    import json
    p = os.path.join(STUDIO_DIR, rel_path)
    if default is None:
        default = {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def server_base_url():
    """从 ai_config.json 读取服务端地址（compute_server_url），失败返回 None。"""
    cfg = read_config_json(os.path.join("config", "ai_config.json"))
    url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
    return url or None


def ollama_base_url():
    """从 ai_config.json 推断 Ollama 地址；默认 192.168.111.28:11435。"""
    cfg = read_config_json(os.path.join("config", "ai_config.json"))
    url = (cfg.get("ollama_api_url") or "").strip().rstrip("/")
    return url or "http://192.168.111.28:11435"
