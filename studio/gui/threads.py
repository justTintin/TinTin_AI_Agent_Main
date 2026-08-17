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
        """客户端心跳：GET /health?machine_id=&capabilities=（技能匹配路由用）。

        - machine_id：本机归属（任务派发按在线客户端）
        - capabilities：已装技能 id 列表（逗号分隔）——下载/技能任务优先派给
          有该技能的在线客户端（online_client_with，回退任意在线）
        /health 返回 {status, hostname, os, python, gpu:{...}}——服务端整体
        健康与服务端资源（GPU 显存/利用率），供资源监控栏展示。
        """
        import os
        import json
        from urllib.parse import quote
        from utils.http_client import http_get

        consecutive_failures = 0
        while self.running:
            status = {"server_ok": False, "health": None}
            try:
                if os.path.isfile(self.config_file_path):
                    with open(self.config_file_path, encoding="utf-8") as f:
                        cfg = json.load(f)
                    server_url = (cfg.get("compute_server_url") or cfg.get("llm_vision_api_url", "")).strip()
                    if server_url:
                        # 心跳带 machine_id + capabilities（已装技能）
                        mid = ""
                        try:
                            from utils.license import get_machine_id
                            mid = get_machine_id() or ""
                        except Exception:
                            pass
                        caps = ""
                        try:
                            from utils.skill_manager import list_skills
                            caps = ",".join(
                                str(s.get("id") or "") for s in list_skills()
                                if s.get("id"))
                        except Exception:
                            pass
                        params = []
                        if mid:
                            params.append(f"machine_id={quote(mid)}")
                        if caps:
                            params.append(f"capabilities={quote(caps)}")
                        url = f"{server_url.rstrip(chr(47))}/health"
                        if params:
                            url += "?" + "&".join(params)
                        # 服务端心跳：单次请求、不重试不打日志（避免不可达时刷屏）；200=服务端可达
                        res = http_get(url, timeout=2, quiet=True)
                        if res.status_code == 200:
                            status["server_ok"] = True
                            try:
                                status["health"] = res.json()
                            except Exception:
                                pass
            except Exception:
                pass

            self.status_updated.emit(status)

            # 指数退避：服务端不可达时拉长间隔，恢复后回到基础 10s，封顶 60s
            if status.get("server_ok"):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
            delay = 10 if consecutive_failures == 0 else min(
                10 * (2 ** (consecutive_failures - 1)), 60)
            for _ in range(int(delay * 2)):
                if not self.running:
                    return
                time.sleep(0.5)


