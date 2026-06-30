import time
import os
import configparser
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from loguru import logger

class DouyinCookieRefresher:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini', encoding='utf-8')
        self.path_config = self.config['Path']
        
        self.chrome_version = int(self.path_config.get('chrome_version', 86))
        self.cookie_file = 'douyin_cookies.txt'
        
    def refresh(self):
        logger.info("正在启动浏览器以获取抖音 Cookie...")
        
        # 尝试杀掉残留进程
        try:
            os.system("taskkill /f /im chrome.exe")
            os.system("taskkill /f /im chromedriver.exe")
        except:
            pass

        options = uc.ChromeOptions()
        # 使用固定的用户数据目录以尝试保持登录状态
        user_data_dir = os.path.join(os.getcwd(), 'chrome_debug_session')
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
            
        options.add_argument(f'--user-data-dir={user_data_dir}')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        driver = None
        try:
            logger.info(f"正在尝试启动 Chrome (版本设定: {self.chrome_version})...")
            driver = uc.Chrome(options=options, version_main=self.chrome_version)
        except Exception as e:
            logger.warning(f"指定版本启动失败: {e}，尝试自动检测版本启动...")
            try:
                driver = uc.Chrome(options=options)
            except Exception as e2:
                logger.error(f"浏览器启动完全失败: {e2}")
                return

        try:
            # 先打开抖音
            driver.get('https://www.douyin.com/')
            time.sleep(5)
            
            # 额外打开搜索页以确保采集到搜索相关的 Cookie
            logger.info("正在模拟搜索行为以采集搜索专有 Cookie...")
            driver.get('https://www.douyin.com/search/%E7%A7%91%E6%8A%80?type=video')
            time.sleep(5)
            
            # 检查是否已经登录
            cookies = driver.get_cookies()
            is_logged_in = any(c['name'] == 'LOGIN_STATUS' and c['value'] == '1' for c in cookies) or \
                           "user/self" in driver.page_source
            
            if is_logged_in:
                logger.success("检测到已有登录会话！")
            else:
                logger.info("未检测到登录状态，正在尝试调出登录窗口...")
                # 尝试点击登录按钮以弹出二维码
                try:
                    # 抖音首页的登录按钮多种多样，尝试几个常见的
                    login_selectors = [
                        '//button[contains(text(), "登录")]',
                        '//div[contains(text(), "登录")]',
                        '//div[contains(@class, "login")]'
                    ]
                    for selector in login_selectors:
                        btns = driver.find_elements(By.XPATH, selector)
                        if btns:
                            btns[0].click()
                            time.sleep(2)
                            break
                except:
                    pass
                
                # 截图查看当前状态（用于诊断二维码是否出现）
                qr_path = "douyin_login_status.png"
                driver.save_screenshot(qr_path)
                logger.info(f"当前页面状态已保存至: {qr_path} (请确认是否有二维码)")
                
                print("\n" + "!"*60)
                print("如果上述截图中没有二维码，请在浏览器中手动操作使其显示。")
                print("完成登录后（看到头像），请回到此处按 [回车键] 提取数据。")
                print("!"*60 + "\n")
                
                input(">>> 请在浏览器中完成登录后，按 [回车键] 继续 >>>")

            # 提取最终 Cookie
            final_cookies = driver.get_cookies()
            if not final_cookies:
                logger.error("未能获取到任何 Cookie。")
            else:
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in final_cookies])
                with open(self.cookie_file, 'w', encoding='utf-8') as f:
                    f.write(cookie_str)
                logger.success(f"Cookie 已提取并保存至 {self.cookie_file}")
            
            driver.quit()
            
        except Exception as e:
            import traceback
            logger.error(f"出错: {e}")
            traceback.print_exc()
            input("按回车退出...")

if __name__ == '__main__':
    refresher = DouyinCookieRefresher()
    refresher.refresh()
