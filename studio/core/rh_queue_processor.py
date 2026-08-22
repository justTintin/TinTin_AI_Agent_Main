"""core/rh_queue_processor.py — RunningHub 任务队列统计与构建。

从 main_window_aigen.py 下沉的纯逻辑函数。
"""
from typing import Any


def compute_queue_stats(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """计算 RunningHub 任务队列的统计指标。

    Args:
        tasks: 任务列表，每个任务需包含 state, submit_count, downloaded 字段

    Returns:
        统计字典：total, submitted, downloaded, done, failed, running, pending, pct
    """
    total = len(tasks)
    submitted = sum(
        1 for t in tasks
        if t.get("submit_count", 0) > 0 or t.get("state") != "pending"
    )
    downloaded = sum(1 for t in tasks if t.get("downloaded"))
    done = sum(1 for t in tasks if t.get("state") == "done")
    failed = sum(1 for t in tasks if t.get("state") == "failed")
    running = sum(1 for t in tasks if t.get("state") == "submitted")
    pending = sum(1 for t in tasks if t.get("state") == "pending")
    pct = int((downloaded + failed) / total * 100) if total else 0
    return {
        "total": total,
        "submitted": submitted,
        "downloaded": downloaded,
        "done": done,
        "failed": failed,
        "running": running,
        "pending": pending,
        "pct": pct,
    }


def build_pending_task(
    idx: int,
    wf_id: str,
    img_file: str,
    vid_file: str | None,
    audio_files: list[str] | None,
    image_nodes: list[str],
    video_nodes: list[str],
    audio_nodes: list[str],
    duration_nodes: list[str],
    duration_value: float,
    instance_type: str | None,
) -> dict[str, Any]:
    """构建单个待处理 RunningHub 任务。

    Args:
        idx: 任务索引
        wf_id: 工作流 ID
        img_file: 图片文件路径
        vid_file: 视频文件路径（视频任务）
        audio_files: 音频文件列表（音频任务，取第一个）
        image_nodes: 图片节点列表
        video_nodes: 视频节点列表
        audio_nodes: 音频节点列表
        duration_nodes: 时长节点列表
        duration_value: 时长值
        instance_type: 实例类型

    Returns:
        任务字典
    """
    aud_file = audio_files[0] if audio_files else None
    return {
        "idx": idx,
        "wf_id": wf_id,
        "img_file": img_file,
        "vid_file": vid_file,
        "aud_file": aud_file,
        "image_nodes": image_nodes,
        "video_nodes": video_nodes,
        "audio_nodes": audio_nodes,
        "duration_nodes": duration_nodes,
        "duration_value": duration_value,
        "instance_type": instance_type or "default",
        "state": "pending",
        "task_id": None,
        "error": None,
        "retry_count": 0,
        "next_attempt_at": 0,
        "submit_count": 0,
        "downloaded": False,
    }
