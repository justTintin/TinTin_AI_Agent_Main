# -*- coding: utf-8 -*-
import json
import time
import requests
import uuid
from PySide6.QtCore import QThread, Signal
from utils.logger_utils import log
from config.paths import CONFIG_INI_FILE

try:
    import websocket
except ImportError:
    websocket = None


class SystemMonitorThread(QThread):
    stats_updated = Signal(dict)
    
    def __init__(self, get_addr_func):
        super().__init__()
        self.get_addr_func = get_addr_func
        self.running = True
    
    def run(self):
        while self.running:
            try:
                addr = self.get_addr_func().rstrip("/")
                if not addr:
                    raise Exception("No address")
                
                # ComfyUI system_stats endpoint
                res = requests.get(f"{addr}/system_stats", timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    cpu = data.get('system', {}).get('cpu_utilization', 0)
                    
                    gpu_info = "--"
                    devices = data.get('devices', [])
                    for d in devices:
                        if d.get('type') == 'cuda':
                            used = (d.get('vram_total', 0) - d.get('vram_free', 0)) // 1024 // 1024
                            total = d.get('vram_total', 0) // 1024 // 1024
                            gpu_info = f"{used}MB / {total}MB"
                            break
                    
                    self.stats_updated.emit({
                        "cpu": f"{cpu:.1f}",
                        "ram": "--",
                        "gpu": gpu_info
                    })
                else:
                    self.stats_updated.emit({"cpu": "Error", "ram": "--", "gpu": "Error"})
            except Exception:
                self.stats_updated.emit({"cpu": "Offline", "ram": "--", "gpu": "Offline"})
            time.sleep(3)


class ComfyWSThread(QThread):
    progress_received = Signal(str, int)  # prompt_id, percentage
    status_received = Signal(str, str)    # prompt_id, status_text
    
    def __init__(self, server_addr):
        super().__init__()
        self.server_addr = server_addr.replace("http://", "ws://") + "/ws?clientId=" + str(uuid.uuid4())
        self.running = True

    def run(self):
        if not websocket:
            log.error("websocket-client library is not installed. ComfyUI progress monitoring will not work.")
            return
            
        while self.running:
            try:
                ws = websocket.create_connection(self.server_addr)
                while self.running:
                    out = ws.recv()
                    data = json.loads(out)
                    if data['type'] == 'progress':
                        value = data['data']['value']
                        max_val = data['data']['max']
                        prompt_id = data['data']['prompt_id']
                        percent = int((value / max_val) * 100)
                        self.progress_received.emit(prompt_id, percent)
                    elif data['type'] == 'executing':
                        prompt_id = data['data']['prompt_id']
                        node = data['data']['node']
                        if node is None:
                            self.status_received.emit(prompt_id, "已完成")
                        else:
                            self.status_received.emit(prompt_id, f"正在执行节点: {node}")
                ws.close()
            except Exception as e:
                log.error(f"WebSocket error connecting to ComfyUI ({self.server_addr}): {e}")
                time.sleep(5)


class AIStatusCheckThread(QThread):
    status_updated = Signal(dict)

    def __init__(self, config_file_path):
        super().__init__()
        self.config_file_path = config_file_path
        self.running = True

    def run(self):
        import os
        import json
        import requests as req

        while self.running:
            status = {
                "ollama_ok": False,
                "vision_ok": False,
                "whisper_ok": False,
                "clip_ok": False,
                "clone_ok": False,
            }
            try:
                # 1. 检测大模型 (Ollama/Vision)
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = json.load(f)
                    api_url = cfg.get("llm_vision_api_url", "").strip()
                    api_key = (cfg.get("llm_vision_api_key") or cfg.get("llm_api_key", "")).strip()
                    model   = cfg.get("llm_vision_model", "").strip()
                    
                    if api_url:
                        try:
                            res = req.get(
                                f"{api_url.rstrip('/')}/v1/models",
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=2,
                            )
                            if res.status_code == 200:
                                status["ollama_ok"] = True
                                if model:
                                    try:
                                        models_data = res.json().get("data", [])
                                        model_names = [m.get("id") for m in models_data]
                                        matched = False
                                        for m_name in model_names:
                                            if m_name == model or m_name == model + ":latest" or model == m_name.split(":")[0] or model.startswith(m_name) or m_name.startswith(model):
                                                matched = True
                                                break
                                        is_cloud = any(x in api_url for x in ("api.deepseek.com", "aliyuncs.com", "openai.com", "openrouter.ai"))
                                        if matched or is_cloud:
                                            status["vision_ok"] = True
                                    except Exception:
                                        status["vision_ok"] = True
                        except Exception:
                            pass
            except Exception:
                pass

            # 2. 检测远程声音克隆 API (VoxCPM) 连通性
            try:
                import json as _json
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = _json.load(f)
                    vox_url = cfg.get("vox_api_url", "").strip()
                    if vox_url:
                        base = vox_url.rstrip("/voxcpm/tts").rstrip("/")
                        r = req.get(f"{base}/voxcpm/health", timeout=3)
                        if r.status_code == 200:
                            status["clone_ok"] = True
            except Exception:
                pass

            # 3. 检测远程 Whisper ASR 服务连通性
            try:
                import json as _json
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = _json.load(f)
                    whisper_url = cfg.get("whisper_api_url", "").strip()
                    if whisper_url:
                        base = whisper_url.rstrip("/")
                        r = req.get(f"{base}/whisper/health", timeout=3)
                        if r.status_code == 200:
                            status["whisper_ok"] = True
            except Exception:
                pass

            # 4. 检测远程 CLIP embedding 服务连通性
            try:
                import json as _json
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = _json.load(f)
                    clip_url = cfg.get("clip_api_url", "").strip()
                    if clip_url:
                        base = clip_url.rstrip("/")
                        r = req.get(f"{base}/clip/health", timeout=3)
                        if r.status_code == 200:
                            status["clip_ok"] = True
            except Exception:
                pass

            self.status_updated.emit(status)
            
            # Sleep 10 seconds, but check self.running frequently
            for _ in range(20):
                if not self.running:
                    break
                time.sleep(0.5)
