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


class ScheduledTaskThread(QThread):
    """定时任务调度线程：每 30 秒扫描一次 scheduled_tasks.json，发现到期任务就发信号。
    应用必须保持运行，调度才生效（应用内置调度，非系统 cron）。
    到期触发后，立即把任务 status 置 running、last_run 置 now，避免重复触发；
    执行结果（done/failed）由执行方（compile_video_page）回调更新。"""
    task_due = Signal(str)   # 发任务 id，由 MainWindow 接收并跳转执行

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        while self.running:
            try:
                from utils.scheduled_task_manager import ScheduledTaskManager, is_due
                mgr = ScheduledTaskManager()
                now = time.time()
                has_running = False
                for t in mgr.all_items():
                    sch = t.get("schedule", {}) or {}
                    if not sch.get("enabled", True):
                        continue
                    if t.get("status") == "running":
                        has_running = True
                        continue
                    if is_due(t, now):
                        # 标记 running + 记录本次触发时间，避免循环内重复触发
                        mgr.update_item(t["id"], {"status": "running", "last_run": int(now)})
                        log.info(f"[定时任务] 触发: {t.get('name')} ({t['id']})")
                        self.task_due.emit(t["id"])
                        break  # 一次只触发一个（前台执行占用界面，串行处理）
            except Exception as e:
                log.warning(f"[定时任务] 调度扫描异常: {e}")
            # 每 30 秒扫一次；用短循环支持快速响应 stop
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(1)


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
        from utils.http_client import resilient_get, resilient_post

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
                    model   = cfg.get("llm_vision_model", "").strip()

                    if server_url:
                        try:
                            res = resilient_get(
                                f"{server_url.rstrip('/')}/ollama/status",
                                timeout=2, service="ollama", circuit_breaker=False,
                            )
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
                        r = resilient_get(f"{base}/voxcpm/health", timeout=3, service="voxcpm", circuit_breaker=False)
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
                        r = resilient_get(f"{base}/whisper/health", timeout=3, service="whisper", circuit_breaker=False)
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
                        r = resilient_get(f"{base}/clip/health", timeout=3, service="clip", circuit_breaker=False)
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
