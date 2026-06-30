
import sys
import os
from core import douyin_video
from loguru import logger

aweme_id = "7587164982459125030"
logger.info(f"Testing aweme_id: {aweme_id}")

try:
    print("\n--- Testing API Method (get_douyin_origin_video) ---")
    data_api = douyin_video.get_douyin_origin_video(aweme_id=aweme_id)
    if data_api:
        print("API Method: Success!")
        print(f"Title: {data_api.get('title')}")
        print(f"Video URL: {data_api.get('originVideo')[:100]}...")
    else:
        print("API Method: Failed")
except Exception as e:
    print(f"API Error: {e}")

try:
    print("\n--- Testing HTML Method (get_douyin_video_detail) ---")
    data_html = douyin_video.get_douyin_video_detail(aweme_id=aweme_id)
    if data_html:
        print("HTML Method: Success!")
        print(f"Title: {data_html.get('title')}")
        print(f"Video URL: {bool(data_html.get('originVideo'))}")
    else:
        print("HTML Method: Failed (Likely JS Riddle)")
except Exception as e:
    print(f"HTML Error: {e}")
