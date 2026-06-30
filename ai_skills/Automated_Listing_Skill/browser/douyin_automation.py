from playwright.sync_api import sync_playwright
import os
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / 'config'))
from skill_config import CHROME_USER_DATA, RESULT_DIR, ensure_dirs
ensure_dirs()

USER_DATA_DIR = CHROME_USER_DATA

def run_automation():
    with sync_playwright() as p:
        # 使用固定的用户数据目录启动浏览器
        # 这样 cookies、localStorage、登录状态都会保存
        context = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        print("浏览器已启动，使用固定的用户数据目录")
        print(f"用户数据保存在: {USER_DATA_DIR}")
        
        # 访问抖店后台
        print("正在访问抖店后台...")
        page.goto("https://fxg.jinritemai.com/ffa/mshop/homepage/index", timeout=60000)
        page.wait_for_load_state("load", timeout=60000)
        time.sleep(3)
        
        print(f"当前页面标题: {page.title()}")
        print(f"当前URL: {page.url}")
        
        # 检查是否需要登录
        page_content = page.content()
        if "登录" in page_content or "login" in page_content.lower():
            print("\n[!] 需要登录，请在浏览器窗口中完成登录")
            print("登录完成后，按 Enter 键继续...")
            input()
        else:
            print("[✓] 已检测到登录状态")
        
        # 查找并点击商品管理
        print("\n正在查找商品管理...")
        
        selectors = [
            'text=商品管理',
            'text=商品',
            'a:has-text("商品")',
            '[data-testid="product"]',
            'a[href*="product"]',
            'a[href*="goods"]'
        ]
        
        found = False
        for selector in selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0:
                    print(f"找到商品管理入口: {selector}")
                    elements.first.click()
                    page.wait_for_load_state("load", timeout=60000)
                    time.sleep(3)
                    found = True
                    break
            except Exception as e:
                continue
        
        if found:
            print("[✓] 已进入商品管理页面")
            shot = os.path.join(RESULT_DIR, "douyin_products.png")
            page.screenshot(path=shot, full_page=True)
            print(f"截图已保存: {shot}")
        else:
            print("[!] 未找到商品管理入口")
        
        print("\n操作完成，浏览器保持打开状态")
        print("关闭浏览器窗口即可退出")
        
        # 保持浏览器打开，等待用户手动关闭
        while True:
            time.sleep(1)

if __name__ == "__main__":
    run_automation()
