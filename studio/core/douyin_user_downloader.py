# -*- coding: utf-8 -*-
import os
import re
import json
import time
import random
import requests
import datetime
import argparse
from loguru import logger
from urllib.parse import quote, urlparse
from . import douyin_a_bogus
from . import douyin_video

class DouyinUserDownloader:
    def __init__(self, user_url, cookie_file='douyin_cookies.txt', download_path='downloads', cookie_str=None):
        self.user_url = user_url
        self.cookie_file = cookie_file
        self.download_path = download_path
        self.cookies_str = cookie_str if cookie_str else self._load_cookies()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/',
            'Accept': 'application/json, text/plain, */*',
            'Cookie': self.cookies_str
        }
        self.aweme_id = self._extract_aweme_id()
        self.sec_uid = self._extract_sec_uid() if not self.aweme_id else None
        
    def _load_cookies(self):
        try:
            with open(self.cookie_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"无法读取 cookie 文件 {self.cookie_file}: {e}")
            return ""

    def _extract_aweme_id(self):
        """从 URL 中提取单个视频/笔记的 aweme_id，如果无法提取则返回 None。"""
        url = self.user_url
        # 格式: /video/1234567890  or  /note/1234567890
        video_match = re.search(r'(?:video|note)/(\d+)', url)
        if video_match:
            aweme_id = video_match.group(1)
            logger.info(f"从链接中提取到单视频 aweme_id: {aweme_id}")
            return aweme_id
        # 格式: ?modal_id=1234567890  or  &modal_id=1234567890
        modal_match = re.search(r'modal_id=(\d+)', url)
        if modal_match:
            aweme_id = modal_match.group(1)
            logger.info(f"从链接 modal_id 中提取到 aweme_id: {aweme_id}")
            return aweme_id
        return None

    def _extract_sec_uid(self):
        url = self.user_url
        # 先处理短链接或用户主页链接的跳转
        if 'v.douyin.com' in url or '/user/' in url:
            logger.info(f"正在通过链接获取 sec_uid: {url}...")
            try:
                # Follow redirects to get the final Home Page URL which contains sec_uid
                res = requests.get(url, headers=self.headers, allow_redirects=True, timeout=10)
                url = res.url
                logger.info(f"最终重定向到: {url}")
            except Exception as e:
                logger.error(f"解析跳转失败: {e}")
        
        # 优先匹配 sec_user_id (由 MS4w 开头的长 ID)
        match = re.search(r'user/([a-zA-Z0-9_-]+)', url)
        if match:
            sec_uid = match.group(1)
            logger.info(f"提取到 ID: {sec_uid}")
            return sec_uid
        
        # 尝试从查询参数提取
        query = urlparse(url).query
        params = {}
        for qc in query.split('&'):
            if '=' in qc:
                k, v = qc.split('=', 1)
                params[k] = v
        
        if 'sec_user_id' in params:
            sec_uid = params['sec_user_id']
            logger.info(f"从参数中提取到 sec_uid: {sec_uid}")
            return sec_uid
        
        # 如果是单视频链接，则不需要 sec_uid，返回 None
        logger.info(f"未能从链接提取 sec_uid (可能是单视频链接): {url}")
        return None

    def fetch_all_videos(self):
        # 如果是单个视频链接，直接获取该视频详情
        if self.aweme_id and not self.sec_uid:
            return self._fetch_single_video(self.aweme_id)
        
        if not self.sec_uid:
            raise Exception(f"无法从链接中识别出用户主页或单个视频，请检查链接格式: {self.user_url}")
        
        all_videos = []
        max_cursor = 0
        has_more = True
        
        # 提取 webid 和 fp
        fp_match = re.search(r's_v_web_id=([^; ]+)', self.cookies_str)
        fp_val = fp_match.group(1) if fp_match else 'verify_lw66uj9x_y69HTWBr_NOK0_4O0k_As0k_vZiOREH3U5SC'
        
        webid_match = re.search(r'tt_webid=([^; ]+)', self.cookies_str)
        if not webid_match:
            webid_match = re.search(r'webid=([^; ]+)', self.cookies_str)
        webid_val = webid_match.group(1) if webid_match else '7163531063863133732'

        while has_more:
            msToken = douyin_video.generate_random_str()
            url = (
                f"https://www.douyin.com/aweme/v1/web/aweme/post/?"
                f"device_platform=webapp&aid=6383&channel=channel_pc_web"
                f"&sec_user_id={self.sec_uid}&max_cursor={max_cursor}&count=20"
                f"&publish_video_strategy_type=2&pc_client_type=1&version_code=170400&version_name=17.4.0"
                f"&cookie_enabled=true&screen_width=1920&screen_height=1080&browser_language=zh-CN"
                f"&browser_platform=Win32&browser_name=Chrome&browser_version=131.0.0.0"
                f"&browser_online=true&engine_name=Blink&engine_version=131.0.0.0&os_name=Windows"
                f"&os_version=10&cpu_core_num=16&device_memory=8&platform=PC&downlink=10"
                f"&effective_type=4g&round_trip_time=0&webid={webid_val}"
                f"&verifyFp={fp_val}&fp={fp_val}&msToken={msToken}"
            )
            
            query_params = url.split('?')[1]
            ab = douyin_a_bogus.get_ab(target_url=query_params, user_agent=self.headers['user-agent'], cookie_str=self.cookies_str)
            if ab:
                url += f"&a_bogus={ab}"
            
            logger.info(f"正在获取视频列表, cursor: {max_cursor}...")
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                if res.status_code != 200:
                    logger.error(f"请求失败，状态码: {res.status_code}, 响应内容: {res.text[:200]}")
                    if res.status_code == 403:
                        raise Exception("访问被拒绝 (403)，可能是 Cookie 失效或 IP 被封禁")
                    elif res.status_code == 302:
                        raise Exception("检测到重定向到登录页，Cookie 已过期")
                    else:
                        raise Exception(f"HTTP 错误: {res.status_code}")
                
                try:
                    data = res.json()
                except ValueError:
                    logger.error(f"无法解析 JSON。状态码: {res.status_code}")
                    logger.debug(f"响应内容预览: {res.text[:1000]}")
                    if "verify" in res.text or "验证" in res.text:
                        raise Exception("触发了验证码，请在浏览器中手动验证后再重试")
                    if "登录" in res.text or "login" in res.text:
                        raise Exception("检测到已退出登录，请重新登录")
                    raise Exception(f"API 响应内容不是有效的 JSON 格式 (HTTP {res.status_code})")
                
                if data.get('status_code') != 0:
                    status_msg = data.get('status_msg', '未知错误')
                    logger.error(f"API 返回错误: {status_msg}")
                    if "登录" in status_msg or "login" in status_msg.lower():
                        raise Exception("登录已过期或未登录")
                    break
                    
                aweme_list = data.get('aweme_list', [])
                all_videos.extend(aweme_list)
                logger.info(f"本次获取 {len(aweme_list)} 个视频，总计 {len(all_videos)} 个")
                
                has_more = data.get('has_more', 0) == 1
                max_cursor = data.get('max_cursor', 0)
                
                if has_more:
                    time.sleep(random.uniform(1.0, 2.0))
            except Exception as e:
                logger.error(f"请求发生异常: {e}")
                raise e # Re-raise so the GUI worker can catch it
                
        return all_videos

    def _fetch_single_video(self, aweme_id):
        """获取单个视频的信息，并格式化为 aweme_list 格式。"""
        logger.info(f"正在获取单个视频详情, aweme_id: {aweme_id}")
        try:
            detail = douyin_video.get_douyin_origin_video(aweme_id=aweme_id)
            if not detail:
                raise Exception(f"无法获取视频详情 (aweme_id={aweme_id})，接口返回为空")
            
            # get_douyin_origin_video returns a dict. Convert it to the aweme format
            # that the rest of the code (download_videos, display_parsed_videos) expects.
            create_time = 0
            try:
                from datetime import datetime
                dt = datetime.strptime(detail.get('publishTime', ''), '%Y-%m-%d %H:%M:%S')
                create_time = int(dt.timestamp())
            except:
                pass
            
            aweme_item = {
                'aweme_id': aweme_id,
                'desc': detail.get('title') or detail.get('descDetail') or aweme_id,
                'create_time': create_time,
                'author': {'nickname': 'video'},
                # Store video URL directly to avoid re-fetching
                '_direct_video_url': detail.get('originVideo'),
                'video': {
                    'play_addr': {
                        'url_list': [detail.get('originVideo')] if detail.get('originVideo') else []
                    }
                }
            }
            logger.info(f"成功获取单个视频: {aweme_item['desc']}")
            return [aweme_item]
        except Exception as e:
            logger.error(f"获取单个视频失败: {e}")
            raise

    def download_videos(self, aweme_list):
        if not aweme_list:
            logger.warning("没有可下载的视频")
            return
            
        # 获取用户名作为子目录
        nickname = "unknown_user"
        if aweme_list:
            nickname = aweme_list[0].get('author', {}).get('nickname', 'unknown_user')
        
        # 清理文件名中的非法字符
        nickname = re.sub(r'[\\/:*?"<>|]', '_', nickname)
        save_dir = os.path.join(self.download_path, nickname)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        logger.info(f"开始批量下载视频到: {save_dir}")
        
        for idx, item in enumerate(aweme_list):
            aweme_id = item.get('aweme_id')
            desc = item.get('desc', 'no_description')
            safe_desc = re.sub(r'[\\/:*?"<>|]', '_', desc)[:50]
            
            # Match new rule: Account Name + Video Publication Time + Video Title
            ctime = item.get('create_time', 0)
            time_str = time.strftime('%Y%m%d_%H%M%S', time.localtime(ctime)) if ctime else "00000000"
            safe_nickname = re.sub(r'[\\/:*?"<>|]', '_', nickname)
            filename = f"{safe_nickname}_{time_str}_{safe_desc}.mp4"
            filepath = os.path.join(save_dir, filename)
            
            if os.path.exists(filepath):
                logger.info(f"[{idx+1}/{len(aweme_list)}] 视频已存在，跳过: {filename}")
                continue
                
            # 尝试获取无水印地址，复用 douyin_video.py 的逻辑
            try:
                # 如果已有预先获取的视频地址（单视频模式），直接使用
                video_url = item.get('_direct_video_url')
                
                if not video_url:
                    # 批量模式：重新获取无水印地址
                    detail = douyin_video.get_douyin_origin_video(aweme_id=aweme_id)
                    video_url = detail.get('originVideo') if detail else None
                
                if not video_url:
                    # 最终备选：使用 aweme_list 中的地址
                    play_addr = item.get('video', {}).get('play_addr', {})
                    url_list = play_addr.get('url_list', [])
                    if url_list:
                        video_url = url_list[0]
                
                if video_url:
                    logger.info(f"[{idx+1}/{len(aweme_list)}] 正在下载: {filename}")
                    self._download_file(video_url, filepath)
                else:
                    logger.warning(f"[{idx+1}/{len(aweme_list)}] 无法找到视频地址: {aweme_id}")
            except Exception as e:
                logger.error(f"[{idx+1}/{len(aweme_list)}] 下载视频 {aweme_id} 失败: {e}")

    def _download_file(self, url, filepath):
        # 转换 https 为 http (保持原有项目的某种兼容性尝试，虽然现代环境一般不需要)
        # url = url.replace('https://', 'http://')
        try:
            res = requests.get(url, headers=self.headers, stream=True, timeout=30)
            if res.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
        except Exception as e:
            logger.error(f"文件下载失败: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='抖音用户主页所有视频批量下载器')
    parser.add_argument('--url', type=str, required=True, help='用户主页链接 (支持短链接)')
    parser.add_argument('--path', type=str, default='downloads', help='下载保存路径')
    args = parser.parse_args()
    
    downloader = DouyinUserDownloader(user_url=args.url, download_path=args.path)
    videos = downloader.fetch_all_videos()
    downloader.download_videos(videos)

if __name__ == '__main__':
    main()
