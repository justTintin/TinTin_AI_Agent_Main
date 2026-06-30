# -*- coding: utf-8 -*-
import json
from loguru import logger
from playwright.sync_api import sync_playwright

class PlaywrightFetcher:
    def __init__(self, headless=True):
        self.headless = headless

    def get_video_json(self, aweme_id, timeout=15000):
        """
        Uses Playwright to intercept the detailed API response for a Douyin video.
        """
        target_url = f"https://www.douyin.com/video/{aweme_id}"
        video_data = None

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless, 
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            page = context.new_page()

            def handle_response(response):
                nonlocal video_data
                if "aweme/v1/web/aweme/detail/" in response.url and response.status == 200:
                    try:
                        json_body = response.json()
                        if "aweme_detail" in json_body:
                            logger.info(f"aweme_id: {aweme_id} 成功拦截到 API 响应")
                            video_data = json_body
                    except Exception as e:
                        logger.error(f"解析 API 响应失败: {e}")

            page.on("response", handle_response)

            try:
                logger.info(f"aweme_id: {aweme_id} 浏览器发起请求 {target_url} ...")
                page.goto(target_url, wait_until="commit", timeout=timeout)
                
                with page.expect_response(
                    lambda response: "aweme/v1/web/aweme/detail/" in response.url and "aweme_id=" in response.url, 
                    timeout=timeout
                ) as response_info:
                    pass
                
                page.wait_for_timeout(500)
            except Exception as e:
                logger.error(f"aweme_id: {aweme_id} 等待详情 API 网络响应超时或异常: {e}")
            finally:
                browser.close()

        return video_data
