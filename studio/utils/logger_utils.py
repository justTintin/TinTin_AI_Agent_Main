# -*- coding: utf-8 -*-
import sys
import os
import glob
import time
from loguru import logger

from config.paths import LOG_DIR

# 日志轮转参数（不用 loguru 内置 rotation/retention：
# 内置轮转通过 os.rename 实现，文件被其他进程（多开客户端/残留进程）
# 打开时抛 PermissionError，导致后续所有日志静默丢失）
_MAX_BYTES = 10 * 1024 * 1024      # 单文件上限 10MB
_RETENTION_SECONDS = 7 * 86400     # 滚动文件保留 1 周


def _cleanup_old_logs(log_dir):
    """删除超龄的滚动日志文件（retention 自实现）。"""
    now = time.time()
    for p in glob.glob(os.path.join(log_dir, "app.*.log")):
        try:
            if now - os.path.getmtime(p) > _RETENTION_SECONDS:
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

def get_last_logs(limit=100):
    """读取最后几行日志文件"""
    log_file = os.path.join(LOG_DIR, "app.log")
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
            # Discard first partial line if we seeked into the middle of a line
            if len(lines) > limit + 1:
                return "\n".join(lines[-limit:])
            else:
                return "\n".join(lines[1:])
    except Exception as e:
        return f"读取日志失败: {e}"
