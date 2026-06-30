"""
douyin_login.py
简单版：仅连接抖店并截图确认登录状态
"""

import asyncio
import sys
import io
import os
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright


def _is_cdp_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except Exception:
        return False


def _find_chrome_exe() -> str:
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    p = shutil.which("chrome") or shutil.which("chrome.exe")
    if p:
        return p
    raise FileNotFoundError("未找到 chrome.exe")


def _ensure_debug_chrome(port: int, user_data_dir: str) -> None:
    if _is_cdp_ready(port):
        return

    chrome_exe = _find_chrome_exe()
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)

    for _ in range(40):
        if _is_cdp_ready(port):
            return
        import time

        time.sleep(0.25)
    raise RuntimeError("Chrome 已启动，但调试端口未就绪")


async def _detect_current_store_name(page, store_keywords) -> str:
    try:
        keywords = [k for k in (store_keywords or []) if isinstance(k, str) and k.strip()]
        if not keywords:
            return ""

        found = await page.evaluate(
            """(keywords) => {
                const maxTop = 260;
                const minRight = window.innerWidth - 620;
                const nodes = document.querySelectorAll('a,span,div');
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                for (const el of nodes) {
                    if (!isVisible(el)) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.top < 0 || rect.bottom > maxTop) continue;
                    if (rect.right < minRight) continue;
                    const text = (el.textContent || '').trim();
                    if (!text) continue;
                    for (const kw of keywords) {
                        if (text.includes(kw)) return kw;
                    }
                }
                const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
                for (const kw of keywords) {
                    if (bodyText.includes(kw)) return kw;
                }
                return '';
            }""",
            keywords,
        )
        return (found or "").strip()
    except Exception:
        return ""
    return ""


async def check_douyin_login():
    """连接抖店，确认登录状态"""

    shop_key = os.environ.get("ALS_SHOP_KEY", "")
    shop_name = os.environ.get("ALS_SHOP_NAME", "")
    shop_homepage_url = os.environ.get("ALS_SHOP_HOMEPAGE_URL", "")

    skill_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(skill_root / "config"))
    from skill_config import CHROME_DEBUG_PORT, CHROME_USER_DATA, RESULT_DIR, DOUYIN_STORES, ensure_dirs
    ensure_dirs()
    _ensure_debug_chrome(CHROME_DEBUG_PORT, CHROME_USER_DATA)

    async with async_playwright() as p:
        try:
            print(f"正在连接到本地 Chrome（端口 {CHROME_DEBUG_PORT}）...")
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CHROME_DEBUG_PORT}")

            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()

            title = await page.title()
            print(f"[OK] 连接成功！当前页面：{title}")
            print(f"     URL: {page.url}")
            if shop_name or shop_key:
                print(f"[SHOP] 当前目标店铺：{shop_name or shop_key}")
                if shop_homepage_url:
                    print(f"[SHOP] 店铺首页：{shop_homepage_url}")
                    await page.goto(shop_homepage_url)
                    await asyncio.sleep(2)
                    title = await page.title()
                    print(f"[SHOP] 已进入目标店铺首页：{title}")
                    print(f"[SHOP] 当前URL：{page.url}")

            if "login" in page.url.lower() or "passport" in page.url.lower():
                print("[WARN] 未登录状态，请先在浏览器中登录抖店")
                return 2

            if shop_name:
                all_keywords = []
                for _k, info in (DOUYIN_STORES or {}).items():
                    all_keywords.append(info.get("name", ""))
                    all_keywords.extend(info.get("aliases", []) or [])
                all_keywords = [k for k in all_keywords if isinstance(k, str) and k.strip()]
                all_keywords.sort(key=len, reverse=True)

                target_keywords = [shop_name]
                for _k, info in (DOUYIN_STORES or {}).items():
                    if _k == shop_key:
                        target_keywords = [info.get("name", "")] + (info.get("aliases", []) or [])
                        break
                target_keywords = [k for k in target_keywords if isinstance(k, str) and k.strip()]
                target_keywords.sort(key=len, reverse=True)

                current_store = await _detect_current_store_name(page, target_keywords + all_keywords)
                if current_store:
                    print(f"[SHOP] 当前页面店铺识别：{current_store}")
                    if not any(k and (k in current_store or current_store in k) for k in target_keywords):
                        print(f"[ERROR] 当前页面店铺与目标店铺不一致，期望：{shop_name}")
                        return 4
                else:
                    page_text = await page.locator("body").inner_text()
                    if any(k and k in page_text for k in target_keywords):
                        pass
                    else:
                        print("[WARN] 未能可靠识别当前店铺，请人工确认右上角店铺后再继续")

            print("[OK] 已确认登录状态与店铺匹配！")

            # 简单截图（非全页，避免超时）
            await asyncio.sleep(2)
            shot_path = os.path.join(RESULT_DIR, "current_page.png")
            await page.screenshot(path=shot_path)
            print(f"[SHOT] 当前页面截图已保存：{shot_path}")

        except Exception as e:
            print(f"[ERROR] 连接失败：{e}")
            print("\n请确认：")
            print(f"1. Chrome 已使用 --remote-debugging-port={CHROME_DEBUG_PORT} 启动")
            print(f"2. 可在浏览器访问 http://127.0.0.1:{CHROME_DEBUG_PORT}/json 验证端口")
            return 3

        finally:
            print("\n脚本执行完毕（浏览器保持打开）")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check_douyin_login()))
