# -*- coding: utf-8 -*-
import time
import datetime
from loguru import logger

def parse_video_detail_json(aweme_id, json_res):
    """
    Parses the intercepted Douyin API JSON response into the standard dictionary format.
    """
    if not json_res or 'aweme_detail' not in json_res or not json_res['aweme_detail']:
        logger.error(f"aweme_id: {aweme_id} 无效的 JSON 或缺少 'aweme_detail'")
        return False
        
    res_data = json_res['aweme_detail']
    
    aweme_id_str = str(aweme_id)
    title = res_data.get('desc') or res_data.get('caption') or aweme_id_str
    title = title.replace('\\n', ' ').replace('\n', ' ').replace('\\t', ' ').replace('\t', ' ').replace('\\r', ' ').replace('\r', ' ').replace('\\', '')
    
    temp = {
        "itemId": aweme_id_str,
        "platform": "douyin",
        "itemUrl": f'https://www.douyin.com/video/{aweme_id}',
        "title": title,
        "descDetail": res_data.get('desc', ''),
        "originVideo": None,
        "normalVideo": None,
        "audio": None,
        'imageUrl': res_data.get('video', {}).get('cover', {}).get('url_list', [None])[0],
        'likes': res_data.get('statistics', {}).get('digg_count', 0),
        'collectNum': res_data.get('statistics', {}).get('collect_count', 0),
        'commentNum': res_data.get('statistics', {}).get('comment_count', 0),
        'publishTime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(res_data.get('create_time', time.time()))),
        'crawlTime': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'createTime': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Extract high-quality video URL
    v_info = res_data.get('video', {})
    
    video_url = None

    # Prioritize bit_rate list for highest quality
    bit_rates = v_info.get('bit_rate', [])
    if bit_rates:
        # Sort by bit_rate to get the highest quality
        sorted_bit_rates = sorted(bit_rates, key=lambda x: x.get('bit_rate', 0), reverse=True)
        for br in sorted_bit_rates:
            url_list = br.get('play_addr', {}).get('url_list', [])
            if url_list:
                # Pick the first URL in the list for this bit rate
                video_url = url_list[0]
                break
    
    # Fallback to standard play addresses if bit_rate not found
    if not video_url:
        paths = [
            v_info.get('play_addr_265', {}).get('url_list', []),
            v_info.get('play_addr_h264', {}).get('url_list', []),
            v_info.get('play_addr', {}).get('url_list', []),
        ]
        for url_list in paths:
            if url_list:
                video_url = url_list[0]
                break
            
    if video_url:
        # Ensure HTTPS
        if video_url.startswith('http:'):
            video_url = video_url.replace('http:', 'https:', 1)
            
        temp["originVideo"] = video_url
        temp["normalVideo"] = video_url
        logger.info(f"aweme_id: {aweme_id} 视频详情解析成功 (高清地址)")
        return temp
    else:
        logger.warning(f"aweme_id: {aweme_id} 解析成功但未找到视频地址")
        return temp
