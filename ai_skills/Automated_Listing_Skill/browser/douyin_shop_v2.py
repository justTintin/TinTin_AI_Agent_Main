"""
抖店商品管理 - 接管已登录的 Chrome
使用 connect_over_cdp 连接到端口 9222 的 Chrome 实例
"""

import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / 'config'))
from skill_config import CHROME_DEBUG_PORT, RESULT_DIR, ensure_dirs
ensure_dirs()

async def manage_douyin_shop():
    async with async_playwright() as p:
        # 【关键点 1】强制连接已有端口，绝不 launch 新浏览器
        try:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CHROME_DEBUG_PORT}")
            
            # 【关键点 2】直接获取已有的上下文和页面
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            
            print(f"✓ 成功接管浏览器")
            print(f"  当前页面标题: {await page.title()}")
            print(f"  当前URL: {page.url}")
            
            # 检查登录状态
            if "login" in page.url.lower():
                print("⚠ 警告：页面显示未登录，请先登录抖店")
                return
            
            # 导航到商品管理页面
            print("\n[1] 导航到商品管理...")
            if "product" not in page.url:
                await page.goto("https://fxg.jinritemai.com/ffa/mshop/product/list")
                await asyncio.sleep(3)
            
            # 关闭可能的弹窗
            print("[2] 关闭弹窗...")
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            
            # 截图验证
            print("[3] 截图保存...")
            shot = os.path.join(RESULT_DIR, "douyin_products.png")
            await page.screenshot(path=shot, full_page=True)
            print(f"  ✓ 截图已保存: {shot}")
            
            # 查找商品管理相关元素
            print("\n[4] 分析页面结构...")
            
            # 尝试查找商品列表
            product_rows = await page.locator('.product-item, .goods-item, tr[data-row-key]').count()
            print(f"  找到 {product_rows} 个商品行")
            
            # 查找发布商品按钮
            publish_btn = page.locator('button:has-text("发布商品"), a:has-text("发布商品")')
            if await publish_btn.count() > 0:
                print("  ✓ 发现'发布商品'按钮")
            
            print("\n✓ 操作完成！")
            
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            print(f"  请确认 Chrome 已用 --remote-debugging-port={CHROME_DEBUG_PORT} 启动")

if __name__ == "__main__":
    asyncio.run(manage_douyin_shop())
