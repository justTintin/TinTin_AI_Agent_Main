# -*- coding: utf-8 -*-
"""服务注册管理中心 — 统一管理所有后台服务的生命周期（启动/停止/状态/依赖）"""
import threading
from typing import Callable, Optional
from utils.logger_utils import log


class ServiceRegistry:
    """轻量级服务注册管理中心。

    使用方式:
        sr = ServiceRegistry()
        sr.register("ollama", start_fn=start_ollama, stop_fn=stop_ollama,
                     depends_on=["gpu"])
        sr.register("gpu", start_fn=lambda: log.info("GPU ready"))
        sr.start_all()         # 按依赖顺序启动
        sr.stop_all()          # 按逆序关闭
        sr.status()            # -> {"ollama": "running", ...}
    """

    def __init__(self):
        self._services: dict[str, dict] = {}  # name -> {start, stop, status_fn, depends_on, thread}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        start_fn: Optional[Callable[[], bool]] = None,
        stop_fn: Optional[Callable[[], None]] = None,
        status_fn: Optional[Callable[[], str]] = None,
        depends_on: Optional[list[str]] = None,
        auto_start: bool = False,
    ) -> "ServiceRegistry":
        with self._lock:
            self._services[name] = {
                "start_fn": start_fn,
                "stop_fn": stop_fn,
                "status_fn": status_fn,
                "depends_on": depends_on or [],
                "auto_start": auto_start,
                "state": "stopped",  # stopped / starting / running / error
                "thread": None,
            }
        return self

    def start(self, name: str) -> bool:
        svc = self._services.get(name)
        if not svc or not svc["start_fn"]:
            log.warning(f"[ServiceRegistry] 服务 '{name}' 未注册或无启动函数")
            return False

        for dep in svc["depends_on"]:
            dep_svc = self._services.get(dep)
            if dep_svc and dep_svc["state"] != "running":
                log.info(f"[ServiceRegistry] 先启动依赖 '{dep}' -> '{name}'")
                if not self.start(dep):
                    log.error(f"[ServiceRegistry] 依赖 '{dep}' 启动失败，跳过 '{name}'")
                    return False

        if svc["state"] == "running":
            return True

        svc["state"] = "starting"
        try:
            ok = svc["start_fn"]()
            svc["state"] = "running" if ok else "error"
            if ok:
                log.info(f"[ServiceRegistry] '{name}' 启动成功")
            else:
                log.error(f"[ServiceRegistry] '{name}' 启动失败")
            return ok
        except Exception as e:
            svc["state"] = "error"
            log.error(f"[ServiceRegistry] '{name}' 启动异常: {e}")
            return False

    def start_async(self, name: str):
        svc = self._services.get(name)
        if not svc:
            return
        t = threading.Thread(target=lambda: self.start(name), daemon=True)
        svc["thread"] = t
        t.start()

    def start_all(self, async_mode: bool = False):
        started = []
        try:
            ordered = self._topological_order()
            for name in ordered:
                svc = self._services[name]
                if not svc.get("auto_start"):
                    continue
                if async_mode:
                    self.start_async(name)
                else:
                    self.start(name)
        except Exception as e:
            log.error(f"[ServiceRegistry] start_all 异常: {e}")

    def stop(self, name: str):
        svc = self._services.get(name)
        if not svc:
            return
        if svc["state"] in ("stopped", "error"):
            svc["state"] = "stopped"
            return

        try:
            if svc["stop_fn"]:
                svc["stop_fn"]()
        except Exception as e:
            log.warning(f"[ServiceRegistry] '{name}' 停止异常: {e}")
        finally:
            svc["state"] = "stopped"
            svc["thread"] = None

    def stop_all(self):
        ordered = self._topological_order()
        for name in reversed(ordered):
            self.stop(name)

    def status(self) -> dict[str, str]:
        result = {}
        for name, svc in self._services.items():
            state = svc["state"]
            if svc["status_fn"]:
                try:
                    state = svc["status_fn"]()
                except Exception:
                    pass
            result[name] = state
        return result

    def is_running(self, name: str) -> bool:
        svc = self._services.get(name)
        return svc["state"] == "running" if svc else False

    def _topological_order(self) -> list[str]:
        """按依赖拓扑排序返回服务名列表"""
        visited = set()
        order = []

        def visit(n):
            if n in visited:
                return
            visited.add(n)
            svc = self._services.get(n)
            if svc:
                for dep in svc.get("depends_on", []):
                    if dep in self._services:
                        visit(dep)
            order.append(n)

        for name in self._services:
            visit(name)
        return order
