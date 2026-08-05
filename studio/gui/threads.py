# -*- coding: utf-8 -*-
import json
import time
import requests
from utils.http_client import http_get
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
        consecutive_failures = 0
        while self.running:
            ok = False
            try:
                addr = self.get_addr_func().rstrip("/")
                if not addr:
                    raise Exception("No address")
                
                # ComfyUI system_stats endpoint
                res = http_get(f"{addr}/system_stats", timeout=3, quiet=True)
                if res.status_code == 200:
                    ok = True
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
            # 指数退避：连续失败时 3s→6s→12s→…封顶 60s；成功后复位
            consecutive_failures = 0 if ok else consecutive_failures + 1
            delay = 3 if consecutive_failures == 0 else min(
                3 * (2 ** (consecutive_failures - 1)), 60)
            end = time.time() + delay
            while self.running and time.time() < end:
                time.sleep(0.25)


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
        from utils.http_client import http_get

        consecutive_failures = 0
        while self.running:
            status = {
                "ollama_ok": False,
                "vision_ok": False,
                "whisper_ok": False,
                "clip_ok": False,
                "clone_ok": False,
            }
            try:
                # 1. 检测大模型 — 走服务端代理（不再直连带 API Key）
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = json.load(f)
                    server_url = (cfg.get("compute_server_url") or cfg.get("llm_vision_api_url", "")).strip()

                    if server_url:
                        # 健康探活：单次请求、不重试不打日志（避免服务不可达时刷屏）
                        try:
                            res = http_get(f"{server_url.rstrip('/')}/ollama/status", timeout=2, quiet=True)
                            if res.status_code == 200:
                                status["ollama_ok"] = True
                                status["vision_ok"] = True  # 服务端代理管理视觉模型
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
                        r = http_get(f"{base}/voxcpm/health", timeout=2, quiet=True)
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
                        r = http_get(f"{base}/whisper/health", timeout=2, quiet=True)
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
                        r = http_get(f"{base}/clip/health", timeout=2, quiet=True)
                        if r.status_code == 200:
                            status["clip_ok"] = True
            except Exception:
                pass

            self.status_updated.emit(status)

            # 指数退避：全部服务探测失败（如服务端不可达）时拉长间隔，避免刷日志；
            # 任一服务恢复后回到基础 10s 间隔。封顶 60s。
            if any(status.values()):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
            delay = 10 if consecutive_failures == 0 else min(
                10 * (2 ** (consecutive_failures - 1)), 60)
            for _ in range(int(delay * 2)):
                if not self.running:
                    return
                time.sleep(0.5)
