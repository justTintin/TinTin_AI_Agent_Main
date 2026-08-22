"""yt-dlp 工具封装。

GUI 层不直接调用 subprocess.run([ytdlp, "-U"], ...)，
统一走本模块封装函数。
"""
from __future__ import annotations

import subprocess

from utils.logger_utils import log


def update_ytdlp(ytdlp_path: str, *, timeout: int = 300) -> tuple[bool, str]:
    """运行 yt-dlp -U 自更新。

    Args:
        ytdlp_path: yt-dlp 可执行文件路径
        timeout: 超时秒数（默认 300）
    Returns:
        (成功 True/失败 False, 最后一条输出或错误信息)
    """
    try:
        r = subprocess.run(
            [ytdlp_path, "-U"],
            capture_output=True, text=True,
            timeout=timeout,
            encoding="utf-8", errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        msg = out.splitlines()[-1] if out else "完成"
        if r.returncode != 0:
            log.warning(f"[ytdlp_utils] 更新失败 rc={r.returncode}: {msg}")
            return False, msg
        return True, msg
    except Exception as e:
        log.error(f"[ytdlp_utils] 更新异常: {e}")
        return False, str(e)
