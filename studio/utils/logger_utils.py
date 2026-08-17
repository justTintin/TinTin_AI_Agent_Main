# -*- coding: utf-8 -*-
import sys
import os
import glob
import time
import re
from loguru import logger

from config.paths import LOG_DIR

# 日志轮转参数（不用 loguru 内置 rotation/retention：
# 内置轮转通过 os.rename 实现，文件被其他进程（多开客户端/残留进程）
# 打开时抛 PermissionError，导致后续所有日志静默丢失）
_MAX_BYTES = 10 * 1024 * 1024      # 单文件上限 10MB
_RETENTION_DAYS = 30               # 归档日志保留天数（按文件名日期清理）


def _session_stamp():
    """当前启动时刻戳（归档文件名用）：2026-08-17_11-15-30"""
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def _archive_name(log_dir, stamp):
    """归档文件名：app-{启动时刻}.log（日期即索引，按日期查看/清理）。"""
    return os.path.join(log_dir, f"app-{stamp}.log")


def _split_session_log(log_dir):
    """启动切分：把上次会话的 app.log 归档为 app-{启动时刻}.log，再新建 app.log。

    - 每个归档文件 = 一次完整运行，文件名日期即那次启动时间；
    - 归档失败（文件被其他进程占用等）只告警跳过，绝不阻断本次启动写日志。
    """
    app_log = os.path.join(log_dir, "app.log")
    if not os.path.exists(app_log):
        return
    try:
        target = _archive_name(log_dir, _session_stamp())
        # 目标已存在（同秒启动两次等极端情况）时加 pid 后缀避免覆盖
        if os.path.exists(target):
            target = _archive_name(log_dir, f"{_session_stamp()}_{os.getpid()}")
        os.rename(app_log, target)
    except OSError as e:
        # 被其他进程占用：跳过切分，继续追加写 app.log，保证日志不丢
        sys.stderr.write(f"[logger] 启动日志归档失败，继续写 app.log: {e}\n")


def _archive_mtime(log_file):
    """从归档文件名解析日期（app-YYYY-MM-DD_...），失败返回 None。"""
    m = re.search(r"app-(\d{4})-(\d{2})-(\d{2})_", os.path.basename(log_file))
    if not m:
        return None
    try:
        return time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            0, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return None


def _cleanup_old_logs(log_dir):
    """按文件名日期删除超龄归档日志（app-YYYY-MM-DD_*.log）。"""
    now = time.time()
    for p in glob.glob(os.path.join(log_dir, "app-*.log")):
        mtime = _archive_mtime(p)
        if mtime is None:
            continue
        if now - mtime > _RETENTION_DAYS * 86400:
            try:
                os.remove(p)
            except OSError:
                pass


def _try_rotate(message, file):
    """自定义轮转（loguru 签名：rotation(message, file)）：达到大小上限时
    重命名为带时间戳文件。

    文件被其他进程打开导致 rename 失败时返回 False（日志继续追加原文件，
    文件暂超大小上限），绝不阻断日志写入；返回 False 可阻止后续尝试。
    """
    log_file = file.name
    try:
        if os.path.getsize(log_file) < _MAX_BYTES:
            return False
    except OSError:
        return False
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    target = os.path.join(os.path.dirname(log_file), f"app.{ts}_{os.getpid()}.log")
    try:
        os.rename(log_file, target)
        _cleanup_old_logs(os.path.dirname(log_file))
        return True
    except OSError:
        # 被其他进程占用：跳过轮转，继续追加写，保证日志不丢
        return False


def setup_logger():
    """配置日志系统，同时输出到控制台、文件，并保留在内存中供 GUI 读取"""
    # 确保 sys.stdout 和 sys.stderr 在遇到无法编码的字符（如 Emoji）时不会抛出 UnicodeEncodeError 崩溃
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except Exception:
                pass

    os.makedirs(LOG_DIR, exist_ok=True)
    # 启动切分：上次会话的 app.log 归档为 app-{启动时刻}.log
    _split_session_log(LOG_DIR)
    log_file = os.path.join(LOG_DIR, "app.log")

    # 清除默认处理器
    logger.remove()

    # 添加控制台处理器
    logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

    # 添加文件处理器（轮转/retention 自实现，避免多进程占用时轮转失败丢日志）
    logger.add(log_file,
               rotation=_try_rotate,
               encoding="utf-8",
               backtrace=True,
               diagnose=True,
               format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}")

    return logger

# 初始化全局 logger
log = setup_logger()


def list_log_files():
    """列出 logs/ 下所有可查看的日志文件（含当前 app.log 与归档），
    按修改时间倒序返回 [(文件名, 完整路径), ...]。"""
    files = []
    app_log = os.path.join(LOG_DIR, "app.log")
    if os.path.exists(app_log):
        files.append(("app.log", app_log))
    for p in sorted(glob.glob(os.path.join(LOG_DIR, "app-*.log")),
                    key=os.path.getmtime, reverse=True):
        files.append((os.path.basename(p), p))
    # 10MB 大小轮转产物（app.时间戳_pid.log）也列出，兼容查看
    seen = {fp for _, fp in files}
    for p in sorted(glob.glob(os.path.join(LOG_DIR, "app.*.log")),
                    key=os.path.getmtime, reverse=True):
        if p not in seen:
            files.append((os.path.basename(p), p))
    return files


def log_file_label(filename):
    """历史日志下拉框的展示标签：文件名 -> 友好日期描述。"""
    if filename == "app.log":
        return "本次会话"
    m = re.search(r"app-(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", filename)
    if m:
        y, mo, d, h, mi, s = (int(g) for g in m.groups())
        return f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d} 启动"
    # 兼容大小轮转产物 app.时间戳_pid.log
    m2 = re.search(r"app\.(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", filename)
    if m2:
        y, mo, d, h, mi, s = (int(g) for g in m2.groups())
        return f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d} (轮转)"
    return filename


def get_last_logs(limit=100, path=None):
    """读取日志文件末尾若干行。

    path 为 None 时读当前会话 app.log；传入归档文件路径时读历史日志。
    """
    log_file = path or os.path.join(LOG_DIR, "app.log")
    if not os.path.exists(log_file):
        return ""
    try:
        file_size = os.path.getsize(log_file)
        # Read the last 64KB block of the file
        read_size = min(file_size, 65536)
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(file_size - read_size)
            content = f.read()
            lines = content.splitlines()
            # 只读尾部块且未读到文件头时，第一行可能是半行，丢弃
            if read_size < file_size and lines:
                lines = lines[1:]
            return "\n".join(lines[-limit:])
    except Exception as e:
        return f"读取日志失败: {e}"
