# -*- coding: utf-8 -*-
"""LLM 服务端压力测试脚本。

用法:
    python tests/stress_llm.py                          # 默认 10并发×50请求
    python tests/stress_llm.py -c 20 -n 200 -m qwen2.5vl:7b-16k  # 自定义参数
    python tests/stress_llm.py --vision                  # 多模态压力测试
"""
import os
import sys
import time
import json
import base64
import threading
import argparse
import requests

SERVER = "http://192.168.111.19:8000"

# ── 结果收集 ──
errors = []
times = []
lock = threading.Lock()


def make_text_request(i: int, model: str = "deepseek-v4-flash", timeout: int = 120):
    """纯文本请求。"""
    t0 = time.time()
    try:
        r = requests.post(
            f"{SERVER}/llm/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": f"压力测试第 {i} 次请求"}],
                "max_tokens": 30,
            },
            timeout=timeout,
        )
        elapsed = time.time() - t0
        with lock:
            times.append(elapsed)
            if r.status_code != 200:
                errors.append(f"req #{i}: HTTP {r.status_code} {r.text[:100]}")
            elif not r.json().get("choices"):
                errors.append(f"req #{i}: empty response")
        return True
    except Exception as e:
        with lock:
            errors.append(f"req #{i}: {type(e).__name__}: {e}")
        return False


def make_vision_request(i: int, model: str = "qwen2.5vl:7b-16k", timeout: int = 120):
    """多模态请求（带一张小图片 base64）。"""
    # 生成一张 1×1 白色 JPEG 的 base64（极小，用于压力测试）
    tiny_jpg_b64 = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQE"
        "AAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AKwA="
    )
    t0 = time.time()
    try:
        r = requests.post(
            f"{SERVER}/llm/chat/completions",
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"压力测试第 {i} 次"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{tiny_jpg_b64}"}},
                    ],
                }],
                "max_tokens": 20,
            },
            timeout=timeout,
        )
        elapsed = time.time() - t0
        with lock:
            times.append(elapsed)
            if r.status_code != 200:
                errors.append(f"req #{i}: HTTP {r.status_code} {r.text[:100]}")
        return True
    except Exception as e:
        with lock:
            errors.append(f"req #{i}: {type(e).__name__}: {e}")
        return False


def worker(start: int, count: int, model: str, vision: bool, timeout: int):
    """工作线程。"""
    fn = make_vision_request if vision else make_text_request
    for i in range(start, start + count):
        fn(i, model=model, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description="LLM 压力测试")
    parser.add_argument("-c", "--concurrent", type=int, default=10, help="并发数")
    parser.add_argument("-n", "--requests", type=int, default=50, help="总请求数")
    parser.add_argument("-m", "--model", type=str, default="deepseek-v4-flash", help="模型名")
    parser.add_argument("-t", "--timeout", type=int, default=120, help="单个请求超时秒数")
    parser.add_argument("--vision", action="store_true", help="多模态压力测试")
    parser.add_argument("--server", type=str, default=SERVER, help="服务端地址")
    args = parser.parse_args()

    global SERVER
    SERVER = args.server

    print(f"=== LLM 压力测试 ===")
    print(f"服务端: {SERVER}")
    print(f"并发数: {args.concurrent}")
    print(f"总请求: {args.requests}")
    print(f"模型:   {args.model}")
    print(f"模式:   {'多模态' if args.vision else '纯文本'}")
    print()

    # 先检查连通性
    try:
        r = requests.get(f"{SERVER}/health", timeout=5)
        if r.status_code != 200:
            print(f"❌ 服务端不可达: HTTP {r.status_code}")
            return 1
        print("✅ 服务端连通")
    except Exception as e:
        print(f"❌ 服务端不可达: {e}")
        return 1

    per_thread = args.requests // args.concurrent
    remainder = args.requests % args.concurrent

    threads = []
    start = 0
    t0_total = time.time()

    for i in range(args.concurrent):
        count = per_thread + (1 if i < remainder else 0)
        if count <= 0:
            continue
        t = threading.Thread(
            target=worker,
            args=(start, count, args.model, args.vision, args.timeout),
        )
        threads.append(t)
        t.start()
        start += count

    for t in threads:
        t.join()

    total_elapsed = time.time() - t0_total

    # ── 统计 ──
    print(f"\n=== 结果 ===")
    print(f"总耗时:    {total_elapsed:.1f}s")
    print(f"成功:      {len(times)}/{args.requests}")
    print(f"失败:      {len(errors)}/{args.requests}")

    if times:
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        p99 = times[int(len(times) * 0.99)]
        print(f"P50 延迟:  {p50:.2f}s")
        print(f"P95 延迟:  {p95:.2f}s")
        print(f"P99 延迟:  {p99:.2f}s")
        print(f"QPS:       {len(times) / total_elapsed:.1f}")

    if errors:
        print(f"\n错误明细 (前 10):")
        for e in errors[:10]:
            print(f"  - {e}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
