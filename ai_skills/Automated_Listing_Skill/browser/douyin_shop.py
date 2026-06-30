"""
douyin_shop.py
抖店商品管理自动化脚本
使用 Playwright connect_over_cdp 接管已有 Chrome 浏览器（9222 端口）
不新建浏览器，直接使用已登录的会话
"""

import asyncio
import os
import sys
import io
from pathlib import Path

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 加载技能配置，获取统一的结果输出目录
SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR, ensure_dirs
ensure_dirs()

from playwright.async_api import async_playwright


async def manage_douyin_products():
    """接管已有 Chrome 浏览器，操作抖店商品管理"""

    async with async_playwright() as p:
        try:
            # [关键] 连接已有 Chrome，不 launch 新浏览器
            print("正在连接到本地 Chrome（端口 9222）...")
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")

            # 获取已有的页面，不新建 context
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()

            title = await page.title()
            print(f"[OK] 连接成功！当前页面：{title}")
            print(f"     URL: {page.url}")

            # 检查登录状态
            if "login" in page.url.lower() or "passport" in page.url.lower():
                print("[WARN] 未登录状态，请先在浏览器中登录抖店")
                return

            print("[OK] 已确认登录状态，准备进入商品管理...")

            # 通过点击左侧导航栏的"商品"菜单进入商品管理
            print("正在点击左侧导航栏的'商品'菜单...")
            try:
                # 先找到左侧导航栏中的"商品"菜单（使用更精确的选择器）
                # 尝试通过菜单项的 data-menu-id 或特定 class 定位
                product_menu = await page.query_selector('div.nav-menu_leftBar__2a2z5 span:has-text("商品")')
                if not product_menu:
                    # 备选：通过父元素查找包含"商品"文本的元素
                    product_menu = await page.query_selector('div[class*="nav"] span:has-text("商品")')
                
                if product_menu:
                    # 使用 force 参数点击，忽略遮挡
                    await product_menu.click(force=True)
                    print("[OK] 已点击'商品'菜单")
                    await asyncio.sleep(2)
                else:
                    print("[WARN] 未找到'商品'菜单，尝试 JavaScript 点击")
                    # 使用 JavaScript 点击
                    await page.evaluate('''() => {
                        const items = document.querySelectorAll('span, div');
                        for (const item of items) {
                            if (item.textContent.trim() === '商品') {
                                item.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    await asyncio.sleep(2)
                
                # 等待子菜单出现，然后点击"商品管理"
                await asyncio.sleep(1)
                product_mgmt = await page.query_selector('text=商品管理')
                if product_mgmt:
                    await product_mgmt.click(force=True)
                    print("[OK] 已点击'商品管理'子菜单")
                    await asyncio.sleep(3)
                else:
                    # 使用 JavaScript 查找并点击
                    clicked = await page.evaluate('''() => {
                        const items = document.querySelectorAll('span, div, a');
                        for (const item of items) {
                            if (item.textContent.trim() === '商品管理') {
                                item.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    if clicked:
                        print("[OK] 已通过 JavaScript 点击'商品管理'")
                    await asyncio.sleep(3)
                    
            except Exception as e:
                print(f"[WARN] 点击导航菜单时出现问题：{e}")
                # 备用方案：直接跳转URL
                target_url = "https://fxg.jinritemai.com/ffa/mshop/homepage/index#/home/product/list"
                print(f"[INFO] 尝试直接跳转：{target_url}")
                await page.goto(target_url)
                await asyncio.sleep(3)

            # 处理可能出现的弹窗
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)

            title2 = await page.title()
            print(f"[PAGE] 当前页面标题：{title2}")
            print(f"[PAGE] 当前页面URL：{page.url}")

            # 截图保存
            screenshot_path = os.path.join(RESULT_DIR, "product_page.png")
            await page.screenshot(path=screenshot_path, full_page=False)
            print(f"[SHOT] 截图已保存：{screenshot_path}")

            # 等待页面加载完成后再截一张
            await asyncio.sleep(2)
            screenshot_path2 = os.path.join(RESULT_DIR, "product_page2.png")
            await page.screenshot(path=screenshot_path2, full_page=True)
            print(f"[SHOT] 完整页面截图已保存：{screenshot_path2}")

            # 查找商品列表中的内容
            try:
                # 尝试多种选择器来定位商品列表
                selectors = [
                    '[class*="product"]',
                    '[class*="item"]',
                    'table tr',
                    '.product-list-item',
                    '[data-testid*="product"]'
                ]
                for selector in selectors:
                    items = await page.query_selector_all(selector)
                    if items:
                        print(f"[INFO] 使用选择器 '{selector}' 找到 {len(items)} 个元素")
            except Exception as e:
                print(f"[INFO] 查询商品列表元素时出现问题：{e}")

            # 点击"创建商品"按钮进入商品创建界面
            print("\n[INFO] 正在尝试进入商品创建页面...")
            try:
                # 等待页面加载
                await asyncio.sleep(2)
                
                # 记录当前页面句柄
                original_pages = len(context.pages)
                print(f"[INFO] 当前标签页数量：{original_pages}")
                
                # 方式1：通过按钮文本查找
                create_btn = await page.query_selector('button:has-text("创建商品")')
                if create_btn:
                    await create_btn.click()
                    print("[OK] 已点击'创建商品'按钮（通过按钮文本）")
                else:
                    # 方式2：通过 JavaScript 查找包含"创建商品"的元素
                    clicked = await page.evaluate('''() => {
                        const elements = document.querySelectorAll('button, a, div, span');
                        for (const el of elements) {
                            if (el.textContent.trim() === '创建商品' || 
                                el.textContent.trim().includes('创建商品')) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    if clicked:
                        print("[OK] 已通过 JavaScript 点击'创建商品'")
                    else:
                        print("[WARN] 未找到'创建商品'按钮，尝试直接跳转URL")
                
                # 等待一下，检查是否有新窗口打开
                await asyncio.sleep(3)
                new_pages = len(context.pages)
                print(f"[INFO] 点击后标签页数量：{new_pages}")
                
                # 如果有新窗口，切换到新窗口
                if new_pages > original_pages:
                    new_page = context.pages[-1]
                    await new_page.bring_to_front()
                    print(f"[OK] 检测到新窗口，已切换到新标签页")
                    page = new_page  # 使用新页面进行后续操作
                else:
                    print("[INFO] 没有检测到新窗口，检查当前页面是否变化")
                
                # 截图保存
                await asyncio.sleep(2)
                create_shot = os.path.join(RESULT_DIR, "product_create.png")
                await page.screenshot(path=create_shot, full_page=True)
                print(f"[SHOT] 商品创建页面截图已保存：{create_shot}")
                
                # 获取页面信息
                create_title = await page.title()
                print(f"[PAGE] 页面标题：{create_title}")
                print(f"[PAGE] 页面URL：{page.url}")
                
                # 如果仍在列表页，尝试直接跳转创建商品URL
                if 'list' in page.url:
                    print("[INFO] 仍在列表页，尝试直接跳转创建商品URL...")
                    # 抖店创建商品的可能URL
                    create_urls = [
                        "https://fxg.jinritemai.com/ffa/g/create",
                        "https://fxg.jinritemai.com/ffa/mshop/homepage/index#/home/product/create",
                        "https://fxg.jinritemai.com/ffa/g/publish"
                    ]
                    for url in create_urls:
                        try:
                            await page.goto(url)
                            await asyncio.sleep(3)
                            if 'create' in page.url or 'publish' in page.url:
                                print(f"[OK] 成功跳转到创建页面：{page.url}")
                                create_shot2 = os.path.join(RESULT_DIR, "product_create.png")
                                await page.screenshot(path=create_shot2, full_page=True)
                                print(f"[SHOT] 已更新创建页面截图：{create_shot2}")
                                break
                        except Exception as e:
                            print(f"[INFO] 尝试 {url} 失败：{e}")
                
            except Exception as e:
                print(f"[ERROR] 进入商品创建页面时出现问题：{e}")

            print(f"\n[DONE] 操作完成！截图已保存至 {RESULT_DIR}，请查看 product_page.png / product_page2.png / product_create.png")

        except Exception as e:
            print(f"[ERROR] 连接失败：{e}")
            print("\n请确认：")
            print("1. Chrome 已使用 --remote-debugging-port=9222 启动")
            print("2. 可在浏览器访问 http://127.0.0.1:9222/json 验证端口")

        finally:
            print("\n脚本执行完毕（浏览器保持打开）")


if __name__ == "__main__":
    asyncio.run(manage_douyin_products())
