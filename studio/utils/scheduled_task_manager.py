# -*- coding: utf-8 -*-
"""
定时任务数据层：保存「一键成片」等动作的定时调度配置。

存储：data/scheduled_tasks.json（Manager + JSON 模式，与 VideoPredictionManager 同构）。

调度模式（schedule.mode）：
    once     指定日期时间执行一次（schedule.date + schedule.time）
    daily    每天指定时刻（schedule.time）
    weekly   每周指定星期几的指定时刻（schedule.weekdays + schedule.time）
    interval 每隔 N 小时（schedule.interval_hours）

调度判断（is_due）由本模块的 is_due(task, now) 实现，供 ScheduledTaskThread 调用。
应用必须保持运行，调度才会生效（应用内置调度，非系统级 cron）。
"""
import os
import json
import time
import datetime as _dt

from config.paths import SCHEDULED_TASKS_FILE
from utils.logger_utils import log

# 动作类型（当前只支持一键成片，预留扩展）
ACTIONS = ["compile_video"]

# 调度模式
SCHEDULE_MODES = ["daily", "once", "weekly", "interval"]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class ScheduledTaskManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or SCHEDULED_TASKS_FILE
        self.items = []
        self.load()

    # ── 持久化 ────────────────────────────────────────────────────────────
    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
            except Exception as e:
                log.error(f"加载定时任务库失败: {e}")
                self.items = []
        else:
            self.items = []
        return self.items

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, indent=2, ensure_ascii=False)

    # ── CRUD ──────────────────────────────────────────────────────────────
    def all_items(self):
        return list(self.items)

    def get(self, item_id):
        return next((it for it in self.items if it.get("id") == item_id), None)

    def add_item(self, name, action, params, schedule):
        """新增一条定时任务，返回其 id。
        params: dict（一键成片参数）
        schedule: dict（调度配置）
        """
        now = int(time.time())
        item = {
            "id": os.urandom(8).hex(),
            "name": (name or "").strip() or "未命名任务",
            "action": action,
            "params": params or {},
            "schedule": self._normalize_schedule(schedule or {}),
            "status": "idle",
            "last_run": 0,
            "last_result": "",
            "next_run": 0,
            "created_at": now,
        }
        item["next_run"] = compute_next_run(item, now)
        self.items.insert(0, item)
        self.save()
        return item["id"]

    def update_item(self, item_id, patch):
        """局部更新一条任务（patch 为字段→值的 dict）。"""
        target = self.get(item_id)
        if not target:
            return False
        # 若改了 schedule 相关字段，重新归一化并重算 next_run
        if "schedule" in patch:
            patch["schedule"] = self._normalize_schedule(patch["schedule"])
        target.update(patch)
        target["next_run"] = compute_next_run(target, int(time.time()))
        self.save()
        return True

    def remove_item(self, item_id):
        before = len(self.items)
        self.items = [it for it in self.items if it.get("id") != item_id]
        if len(self.items) < before:
            self.save()
            return True
        return False

    @staticmethod
    def _normalize_schedule(s):
        """补全 schedule 字段的默认值。"""
        return {
            "mode": s.get("mode", "daily") if s.get("mode") in SCHEDULE_MODES else "daily",
            "time": s.get("time", "09:00"),                # HH:MM
            "date": s.get("date", ""),                      # YYYY-MM-DD（once 用）
            "weekdays": s.get("weekdays", [0, 1, 2, 3, 4]),  # 0=周一…6=周日（weekly 用）
            "interval_hours": max(1, int(s.get("interval_hours", 24) or 24)),  # interval 用
            "enabled": bool(s.get("enabled", True)),
        }


# ════════════════════════════════════════════════════════════════════════════
#  调度判断
# ════════════════════════════════════════════════════════════════════════════
def _parse_hhmm(s):
    """'14:30' -> (14, 30)；失败返回 None。"""
    try:
        h, m = s.split(":")
        return int(h), int(m)
    except Exception:
        return None


def _today_str():
    return _dt.datetime.now().strftime("%Y-%m-%d")


def _date_time_ts(date_str, time_str):
    """把 'YYYY-MM-DD' + 'HH:MM' 转成本地时间戳。"""
    try:
        dt = _dt.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return dt.timestamp()
    except Exception:
        return 0.0


def is_due(task, now):
    """判断任务在 now 时刻是否该触发。已执行过（last_run 标记）的不会重复触发。
    返回 bool。调用方在触发后应立即把 status 置 running / last_run 置 now。"""
    sch = task.get("schedule", {}) or {}
    if not sch.get("enabled", True):
        return False
    mode = sch.get("mode", "daily")
    last_run = float(task.get("last_run", 0) or 0)
    hhmm = _parse_hhmm(sch.get("time", "09:00"))
    today = _today_str()

    if mode == "once":
        target_ts = _date_time_ts(sch.get("date", ""), sch.get("time", "09:00"))
        if target_ts <= 0:
            return False
        # 到点且从未在该时刻后执行过
        return now >= target_ts and last_run < target_ts

    if mode == "daily":
        if not hhmm:
            return False
        # 今天该时刻的时间戳
        target_ts = _date_time_ts(today, sch.get("time", "09:00"))
        return now >= target_ts and last_run < target_ts

    if mode == "weekly":
        if not hhmm:
            return False
        # Python weekday(): 周一=0…周日=6，与 weekdays 约定一致
        wd = _dt.datetime.now().weekday()
        if wd not in (sch.get("weekdays") or []):
            return False
        target_ts = _date_time_ts(today, sch.get("time", "09:00"))
        return now >= target_ts and last_run < target_ts

    if mode == "interval":
        interval_h = max(1, int(sch.get("interval_hours", 24) or 24))
        interval_s = interval_h * 3600
        # 基准时间：上次执行时间；若从未执行，用创建时间
        base = last_run if last_run > 0 else float(task.get("created_at", 0) or 0)
        if base <= 0:
            base = now
        return (now - base) >= interval_s

    return False


def compute_next_run(task, now):
    """粗略估算下次执行时间戳（供 UI 显示）。无法估算返回 0。"""
    sch = task.get("schedule", {}) or {}
    if not sch.get("enabled", True):
        return 0
    mode = sch.get("mode", "daily")
    today = _today_str()
    last_run = float(task.get("last_run", 0) or 0)

    try:
        if mode == "once":
            ts = _date_time_ts(sch.get("date", ""), sch.get("time", "09:00"))
            return ts if ts > now else 0
        if mode == "daily":
            ts = _date_time_ts(today, sch.get("time", "09:00"))
            return ts if ts > now else _date_time_ts(
                (_dt.datetime.now() + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
                sch.get("time", "09:00"))
        if mode == "weekly":
            # 找接下来最近的一个目标 weekday
            wds = sorted(set(sch.get("weekdays") or []))
            if not wds:
                return 0
            cur_wd = _dt.datetime.now().weekday()
            for offset in range(8):
                cand_wd = (cur_wd + offset) % 7
                if cand_wd in wds:
                    cand_date = (_dt.datetime.now() + _dt.timedelta(days=offset)).strftime("%Y-%m-%d")
                    ts = _date_time_ts(cand_date, sch.get("time", "09:00"))
                    if ts > now:
                        return ts
            return 0
        if mode == "interval":
            interval_s = max(1, int(sch.get("interval_hours", 24) or 24)) * 3600
            base = last_run if last_run > 0 else float(task.get("created_at", 0) or now)
            return base + interval_s
    except Exception:
        pass
    return 0


def format_next_run(ts):
    """把时间戳格式化成可读字符串（供 UI）。"""
    if not ts or ts <= 0:
        return "—"
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return "—"


def format_last_run(ts):
    if not ts or ts <= 0:
        return "未执行"
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return "—"
