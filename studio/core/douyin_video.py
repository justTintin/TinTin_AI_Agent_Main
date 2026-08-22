import traceback

from loguru import logger

from .browser_fetcher import PlaywrightFetcher
from .douyin_parser import parse_video_detail_json


def get_douyin_origin_video(aweme_id):
    """
    Main entrypoint: Fetches Douyin video detail using browser interception and parses it.  # noqa: E501
    """
    try:
        # Initialize fetcher
        fetcher = PlaywrightFetcher(headless=True)
        # Intercept JSON from API
        json_data = fetcher.get_video_json(aweme_id=aweme_id)

        if json_data:
            # Parse JSON into unified dictionary
            result = parse_video_detail_json(aweme_id=aweme_id, json_res=json_data)
            return result
        else:
            logger.error(f"aweme_id: {aweme_id} 无法通过浏览器拦截获取到视频JSON数据")
            return False

    except Exception:  # 外部API调用（Playwright 浏览器拦截获取抖音视频）
        logger.error(f'aweme_id: {aweme_id} 获取异常: {traceback.format_exc()}')
        return False

if __name__ == '__main__':
    # Test fetch
    print(get_douyin_origin_video(aweme_id='7350291791045790991'))
