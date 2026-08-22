"""本地定时任务管理：基于 Windows 任务计划程序（schtasks）注册/查询/删除客户端内置任务。

背景：客户端定时任务此前靠手工 bat + 任务计划程序配置（抓取热点-每日定时.bat）。
现由本模块统一接管：注册/注销/状态查询全部走 schtasks 命令，任务定义持久化在
studio/data/local_scheduled_tasks.json，「定时任务」对话框直接调用。

任务类型：
- hotspot：本地定时任务（不依赖服务端智能体，当前为每日热点采集，调用
  asset_browser_client.launch_hotspot_capture(auto_quit=True)）
- agent：云端智能体（到点读取任务描述 → LLM 拆解 plan → 提交服务端 /agent/tasks 执行；
  服务端 Orchestrator 按注册的智能体能力自动分解执行）

注意：任务命令内联 Python 代码并注入 studio 绝对路径（sys.path.insert），
不依赖任务计划程序的「起始于」目录，因此无需 bat 包装脚本。
"""
import json
import os
import re
import subprocess
from datetime import datetime

from config.paths import DATA_DIR, PROJECT_ROOT, PYTHON_EMBEDED_DIR

from utils.logger_utils import log

TASK_PREFIX = "TinTinAI_"
TASKS_FILE = os.path.join(DATA_DIR, "local_scheduled_tasks.json")

# 任务类型 → 执行代码模板（{root} 注入 studio 绝对路径；{task_name} 注入任务名）
_EXEC_CODE = {
    "hotspot": (
        "import sys;sys.path.insert(0,{root!r});"
        "from utils import asset_browser_client as a;"
        "a.launch_hotspot_capture(auto_quit=True)"
    ),
    # 到点后：从本地任务清单读取本任务（注册时已 LLM 拆解的 plan 优先；
    # 旧任务无 plan 时回退按 goal 重新拆解）→ 提交服务端编排执行
    # 注意：单行内联代码不能用 if 复合语句（Python 不允许分号后跟复合语句），用 and 短路
    "agent": (
        "import sys,json,os;sys.path.insert(0,{root!r});"
        "from config.paths import DATA_DIR;"
        "from utils.agent_router import build_plan;"
        "from utils import agent_client as ac;"
        "tasks=json.load(open(os.path.join(DATA_DIR,'local_scheduled_tasks.json'),encoding='utf-8'));"  # noqa: E501
        "me=next((t for t in tasks if t.get('task_name')=={task_name!r}),{{}});"
        "plan=me.get('plan') or (build_plan(me.get('goal') or '') if (me.get('goal') or '').strip() else None);"  # noqa: E501
        "plan and ac.create_task(goal=plan.get('goal'),plan=plan,mode='execute')"
    ),
}

_WEEKDAY_ABBR = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# schtasks 上次结果：0x0=成功；0x41303（十进制 267011）= 任务从未运行
_HAS_NOT_RUN_VALUES = ("267011", "0x41303", "41303")


def _schtasks(*args):
    """执行 schtasks 命令，返回 (returncode, 输出文本)。失败返回 (-1, 错误信息)。"""
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True,
                           text=True, encoding="gbk", errors="replace", timeout=20)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"[本地定时] schtasks 执行失败: {e}")
        return -1, str(e)


def _load():
    """读取本地任务清单（json）。"""
    try:
        if os.path.isfile(TASKS_FILE):
            with open(TASKS_FILE, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"[本地定时] 读取任务清单失败: {e}")
    return []


def _save(tasks):
    """持久化本地任务清单。"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        log.warning(f"[本地定时] 保存任务清单失败: {e}")
        return False


def _parse_query_info(out):
    """解析 schtasks /query /v LIST 输出 → 关键字段 dict（中英文键兼容）。"""
    info = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key or not val:
            continue
        if key in ("下次运行时间", "上次运行时间", "上次结果", "状态",
                   "Next Run Time", "Last Run Time", "Last Result", "Status"):
            info[key] = val
    return info


def _result_text(val):
    """上次结果（0/0x0=成功，0x41303=从未运行）→ 可读文本。"""
    if not val:
        return "—"
    v = val.strip("()")
    if v in ("0", "0x0"):
        return "成功"
    if v in _HAS_NOT_RUN_VALUES:
        return "尚未运行"
    return val


def _schedule_text(schedule):
    """调度配置 → 展示文本。schedule: {mode, time, weekdays}。"""
    schedule = schedule or {}
    mode = schedule.get("mode", "daily")
    time_str = schedule.get("time", "")
    if mode == "weekly":
        days = schedule.get("weekdays") or []
        day_text = "、".join("一二三四五六日"[d] + "" for d in days if 0 <= d <= 6)
        if day_text:
            day_text = f"周{day_text}"
        return f"每周 {day_text} {time_str}" if day_text else f"每周 {time_str}"
    return f"每天 {time_str}"


def create_task(name, task_type="hotspot", schedule=None, goal=None, plan=None):
    """注册一个本地定时任务。

    schedule: {"mode": "daily"|"weekly", "time": "HH:MM", "weekdays": [0-6]}
    goal: 云端智能体类型（agent）的任务描述。
    plan: 云端智能体类型注册时 LLM 拆解出的执行步骤（dict），随任务保存，到点直接提交服务端。
    返回 (True, 任务名) 或 (False, 错误信息)。
    """
    schedule = schedule or {}
    mode = schedule.get("mode", "daily")
    if mode not in ("daily", "weekly"):
        return False, f"不支持的调度方式: {mode}"
    if task_type not in _EXEC_CODE:
        return False, f"不支持的本地任务类型: {task_type}"
    if task_type == "agent" and not (goal or "").strip():
        return False, "云端智能体任务需要任务描述（goal）"
    time_str = schedule.get("time") or "09:00"
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return False, f"时间格式应为 HH:MM：{time_str}"

    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "", name or "").strip()
    if not safe:
        return False, "任务名称不能为空"
    task_name = f"{TASK_PREFIX}{safe}"
    if any(t.get("task_name") == task_name for t in _load()):
        return False, f"同名任务已存在：{task_name}"

    python_exe = os.path.join(PYTHON_EMBEDED_DIR, "python.exe")
    if not os.path.isfile(python_exe):
        return False, f"未找到 python.exe：{python_exe}"
    code = _EXEC_CODE[task_type].format(root=PROJECT_ROOT, task_name=task_name)
    tr = f'"{python_exe}" -c "{code}"'

    args = ["/create", "/f", "/tn", task_name, "/tr", tr,
            "/sc", "DAILY" if mode == "daily" else "WEEKLY", "/st", time_str]
    if mode == "weekly":
        days = [d for d in (schedule.get("weekdays") or []) if 0 <= d <= 6]
        if not days:
            return False, "每周模式至少选择一个星期"
        args += ["/d", ",".join(_WEEKDAY_ABBR[d] for d in sorted(set(days)))]
    code_, out = _schtasks(*args)
    if code_ != 0:
        return False, out.strip() or f"schtasks 创建失败（退出码 {code_}）"

    tasks = _load()
    tasks.append({
        "task_name": task_name,
        "name": safe,
        "type": task_type,
        "schedule": {"mode": mode, "time": time_str,
                     "weekdays": schedule.get("weekdays", []) if mode == "weekly" else []},  # noqa: E501
        "goal": (goal or "").strip() if task_type == "agent" else "",
        "plan": plan if task_type == "agent" else None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save(tasks)
    log.info(f"[本地定时] 已注册任务 {task_name}（{mode} {time_str}）")
    return True, task_name


def list_tasks():
    """返回本地任务清单，并合并 schtasks 实时状态（下次/上次运行、上次结果）。"""
    tasks = _load()
    for t in tasks:
        code_, out = _schtasks("/query", "/tn", t.get("task_name", ""), "/fo", "LIST", "/v")  # noqa: E501
        if code_ == 0:
            info = _parse_query_info(out)
            t["registered"] = True
            t["next_run"] = info.get("下次运行时间") or info.get("Next Run Time") or ""
            t["last_run"] = info.get("上次运行时间") or info.get("Last Run Time") or ""
            t["last_result"] = info.get("上次结果") or info.get("Last Result") or ""
        else:
            t["registered"] = False
            t["next_run"] = t["last_run"] = t["last_result"] = ""
    return tasks


def delete_task(name):
    """注销本地定时任务（schtasks /delete + 清理清单）。name 为任务名或 task_name。"""
    tasks = _load()
    t = next((x for x in tasks
              if x.get("task_name") == name or x.get("name") == name), None)
    if t is None:
        return False, "任务不在本地清单中"
    code_, out = _schtasks("/delete", "/f", "/tn", t["task_name"])
    if code_ != 0:
        return False, out.strip() or f"schtasks 删除失败（退出码 {code_}）"
    _save([x for x in tasks if x is not t])
    log.info(f"[本地定时] 已注销任务 {t['task_name']}")
    return True, t["task_name"]


def run_now(task_name):
    """立即运行已注册的本地任务（schtasks /run）。"""
    code_, out = _schtasks("/run", "/tn", task_name)
    if code_ == 0:
        return True, "已触发执行"
    return False, out.strip() or "触发失败"
