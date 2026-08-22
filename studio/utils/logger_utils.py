# -*- coding: utf-8 -*-
import sys
import os
from loguru import logger

from config.paths import LOG_DIR

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
    
    # 添加文件处理器
    logger.add(log_file, 
               rotation="10 MB", 
               retention="1 week", 
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
