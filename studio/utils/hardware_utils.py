# -*- coding: utf-8 -*-
"""
hardware_utils — 获取系统硬件信息并自动调整 AI 分析的并行配置。
"""
import os
import platform
import json
import logging
from config.paths import AI_CONFIG_FILE, CONFIG_DIR

log = logging.getLogger(__name__)

# CLIP 配置文件路径
_CLIP_CFG_FILE = os.path.join(CONFIG_DIR, "material_index_config.json")

def get_system_hardware_info() -> dict:
    """
    检测系统硬件配置和版本信息。
    """
    info = {
        "os": f"{platform.system()} {platform.release()} (Build {platform.version()})",
        "cpu_name": platform.processor() or "未知 CPU",
        "cpu_cores": "未知核心",
        "ram": 0.0,
        "gpu_name": "无",
        "gpu_vram": 0.0,
    }
    
    # 获取 CPU 核心数与线程数，获取 CPU 型号
    try:
        import psutil
        info["cpu_cores"] = f"{psutil.cpu_count(logical=False)}核 / {psutil.cpu_count(logical=True)}线程"
    except Exception:
        pass

    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            if cpu_name:
                info["cpu_name"] = cpu_name
    except Exception:
        pass

    # 获取运行内存 (RAM)
    try:
        import psutil
        info["ram"] = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    except Exception:
        pass

    # 获取 GPU 和显存大小 (优先 PyTorch，次优 pynvml)
    try:
        import torch
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_vram"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 2)
        else:
            raise ImportError()
    except Exception:
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            info["gpu_name"] = name
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            info["gpu_vram"] = round(mem_info.total / (1024 ** 3), 2)
        except Exception:
            pass
            
    return info

def auto_adjust_concurrency_configs(force: bool = False) -> dict:
    """
    根据硬件配置自动调整并保存并发与批处理设置。
    如果 force 为 False，仅在配置文件中缺少相应键时才写入。
    """
    hw = get_system_hardware_info()
    vram = hw["gpu_vram"]
    
    # 自适应参数推荐
    if vram >= 15.5:  # 大于等于 16GB 显存 (如 RTX 4090 / 3090)
        ollama_parallel = 4
        vision_concurrency = 4
        clip_batch_size = 16
        level = "高性能模式 (推荐 4 并发，16 批次，适合 >=16GB 显存)"
    elif vram >= 7.5:  # 大于等于 8GB 显存 (如 RTX 4060 / 3070)
        ollama_parallel = 2
        vision_concurrency = 2
        clip_batch_size = 8
        level = "平衡模式 (推荐 2 并发，8 批次，适合 8GB~16GB 显存)"
    else:  # 低于 8GB 显存或无 GPU
        ollama_parallel = 1
        vision_concurrency = 1
        clip_batch_size = 4
        level = "低能耗/单线程安全模式 (推荐 1 并发，4 批次，适合无 GPU 或低显存)"

    # 1. 写入 AI Config (ai_config.json)
    ai_cfg = {}
    if os.path.exists(AI_CONFIG_FILE):
        try:
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                ai_cfg = json.load(f)
        except Exception:
            pass
    
    ai_updated = False
    if force or "ollama_num_parallel" not in ai_cfg:
        ai_cfg["ollama_num_parallel"] = ollama_parallel
        ai_updated = True
    if force or "vision_concurrency" not in ai_cfg:
        ai_cfg["vision_concurrency"] = vision_concurrency
        ai_updated = True
        
    if ai_updated:
        try:
            os.makedirs(os.path.dirname(AI_CONFIG_FILE), exist_ok=True)
            with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(ai_cfg, f, indent=4, ensure_ascii=False)
            log.info(f"已根据硬件自动更新 ai_config: ollama_num_parallel={ai_cfg['ollama_num_parallel']}, vision_concurrency={ai_cfg['vision_concurrency']}")
        except Exception as e:
            log.error(f"保存 ai_config.json 自动优化失败: {e}")

    # 2. 写入 CLIP Config (material_index_config.json)
    clip_cfg = {}
    if os.path.exists(_CLIP_CFG_FILE):
        try:
            with open(_CLIP_CFG_FILE, "r", encoding="utf-8") as f:
                clip_cfg = json.load(f)
        except Exception:
            pass
            
    clip_updated = False
    if force or "batch_size" not in clip_cfg:
        clip_cfg["batch_size"] = clip_batch_size
        clip_updated = True
        
    if clip_updated:
        try:
            os.makedirs(os.path.dirname(_CLIP_CFG_FILE), exist_ok=True)
            with open(_CLIP_CFG_FILE, "w", encoding="utf-8") as f:
                json.dump(clip_cfg, f, indent=2, ensure_ascii=False)
            log.info(f"已根据硬件自动更新 material_index_config: batch_size={clip_cfg['batch_size']}")
        except Exception as e:
            log.error(f"保存 material_index_config.json 自动优化失败: {e}")
        
    return {
        "level": level,
        "ollama_num_parallel": ai_cfg.get("ollama_num_parallel", ollama_parallel),
        "vision_concurrency": ai_cfg.get("vision_concurrency", vision_concurrency),
        "clip_batch_size": clip_cfg.get("batch_size", clip_batch_size)
    }
