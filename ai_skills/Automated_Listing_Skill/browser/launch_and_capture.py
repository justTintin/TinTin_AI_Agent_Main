import subprocess
import time
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / 'config'))
from skill_config import CHROME_EXE_PATH, CHROME_USER_DATA, CHROME_DEBUG_PORT, RESULT_DIR, ensure_dirs
ensure_dirs()

def main():
    if not CHROME_EXE_PATH or not os.path.isfile(CHROME_EXE_PATH):
        print("未找到 Chrome 可执行文件路径。请设置环境变量 ALS_CHROME_EXE_PATH 或 CHROME_EXE_PATH 指向 chrome.exe")
        sys.exit(2)

    # 1. 关闭所有 Chrome
    print("正在关闭 Chrome...")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    time.sleep(2)
    
    # 2. 用调试模式启动 Chrome（使用默认用户配置）
    print("正在用调试模式启动 Chrome...")
    subprocess.Popen([
        CHROME_EXE_PATH,
        f"--user-data-dir={CHROME_USER_DATA}",
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        "--no-first-run",
        "--no-default-browser-check"
    ])
    time.sleep(5)
    
    # 3. 连接 Chrome 并截图
    print("正在连接 Chrome...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CHROME_DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        
        # 如果当前不是抖店页面，跳转到抖店
        if "jinritemai" not in page.url:
            print("正在访问抖店后台...")
            page.goto("https://fxg.jinritemai.com/ffa/mshop/homepage/index")
            time.sleep(5)
        
        print(f"当前页面: {page.title()}")
        print(f"当前URL: {page.url}")
        
        # 截图
        shot = os.path.join(RESULT_DIR, "douyin_current.png")
        page.screenshot(path=shot, full_page=True)
        print(f"截图已保存: {shot}")
        
        # 获取页面结构信息
        html = page.content()
        
        # 查找菜单项
        menu_items = page.locator('text=/商品|订单|数据|营销|服务|资产|店铺/').all()
        print(f"\n找到 {len(menu_items)} 个菜单项:")
        for i, item in enumerate(menu_items[:10]):
            text = item.text_content() or ""
            if text.strip():
                print(f"  {i+1}. {text.strip()}")
        
        browser.close()
    
    print("\n完成！请查看截图了解当前页面状态。")

if __name__ == "__main__":
    main()
