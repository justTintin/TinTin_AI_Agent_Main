import json
import time
import datetime
import requests
import random
import sys
import re
import configparser
import pymysql
from urllib.parse import quote
from loguru import logger
from pymongo import MongoClient
from . import douyin_a_bogus
import re

# 借用原有的模块
from . import douyin_video

class DouyinAdvancedCrawler:
    def __init__(self):
        logger.info("初始化高级抖音爬虫 (互动价值模型, MySQL版)...")
        self.config = configparser.ConfigParser()
        self.config.read('config.ini', encoding='utf-8')
        
        self.crawlers_config = self.config['Crawlers']
        self.path_config = self.config['Path']
        self.adv_config = self.config['Douyin_Advanced']
        self.mysql_config = self.config['MySQL']
        self.min_comments = self.adv_config.getint('Min_Comments', 100)

        self.db_type = self.config.get('Database', 'Type', fallback='mongodb').lower()

        # MySQL 初始化
        self.conn = None
        try:
            self.conn = pymysql.connect(
                host=self.mysql_config['Host'],
                port=int(self.mysql_config['Port']),
                user=self.mysql_config['User'],
                password=self.mysql_config['Password'],
                database=self.mysql_config['Database'],
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.create_table_if_not_exists()
        except Exception as e:
            logger.error(f"MySQL 初始化失败: {e}")

        # MongoDB 初始化
        self.collection = None
        try:
            if self.path_config.get('Mongo_username') and self.path_config.get('Mongo_password'):
                client = MongoClient(host=self.path_config['Mongo_host_server'], port=int(self.path_config['Mongo_port']), username=self.path_config['Mongo_username'], password=self.path_config['Mongo_password'], authSource='admin', authMechanism='SCRAM-SHA-256')
            else:
                client = MongoClient(host=self.path_config['Mongo_host_server'], port=int(self.path_config['Mongo_port']))
            self.collection = client['handling_vedio']['vedios']
        except Exception as e:
            logger.error(f"MongoDB 初始化失败: {e}")
        
        # 代理设置
        self.proxy = None
        if self.crawlers_config['Proxy_switch'] == 'True':
            if self.crawlers_config['Use_socks5_proxy'] == 'True':
                self.proxy = {"http": self.crawlers_config['Socks5_proxy'], "https": self.crawlers_config['Socks5_proxy']}
            elif self.crawlers_config['Use_simple_proxy'] == 'True':
                self.proxy = {"http": 'http://' + self.crawlers_config['Simple_proxy'], "https": 'https://' + self.crawlers_config['Simple_proxy']}

    def create_table_if_not_exists(self):
        with self.conn.cursor() as cursor:
            sql = """
            CREATE TABLE IF NOT EXISTS videos (
                video_id VARCHAR(64) PRIMARY KEY,
                video_title TEXT,
                video_url TEXT,
                video_pic TEXT,
                video_playtime VARCHAR(32),
                video_watch_num BIGINT,
                video_datafrom VARCHAR(32),
                video_update_time DOUBLE,
                keywords VARCHAR(255),
                engagement_rate DOUBLE,
                fan_to_view_ratio DOUBLE,
                follower_count BIGINT,
                play_count BIGINT,
                digg_count BIGINT,
                comment_count BIGINT,
                collect_count BIGINT,
                share_count BIGINT,
                nickname VARCHAR(128),
                publish_time DATETIME,
                crawl_time DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            cursor.execute(sql)
        self.conn.commit()

    def simple_get(self, url, headers, cookies=None):
        for i in range(5):
            try:
                if self.proxy:
                    res = requests.get(url=url, headers=headers, proxies=self.proxy, cookies=cookies, timeout=10)
                else:
                    res = requests.get(url=url, headers=headers, cookies=cookies, timeout=10)
                if res.status_code < 300:
                    return res.text
                else:
                    logger.warning(f"请求 {url} 异常 {res.status_code}, 重试 {i+1}")
                    time.sleep(1)
            except Exception as e:
                logger.error(f"请求报错: {e}")
                time.sleep(1)
        return None

    def calculate_interaction_value(self, video_data):
        stats = video_data.get('statistics', {})
        play_count = stats.get('play_count', 0)
        digg_count = stats.get('digg_count', 0)
        comment_count = stats.get('comment_count', 0)
        collect_count = stats.get('collect_count', 0)
        share_count = stats.get('share_count', 0)
        
        author = video_data.get('author', {})
        follower_count = author.get('follower_count', 0)
        
        engagement_rate = (digg_count + comment_count + collect_count + share_count) / play_count if play_count > 0 else 0
        fan_to_view_ratio = play_count / follower_count if follower_count > 0 else (play_count if play_count > 0 else 0)

        return {
            "engagement_rate": round(engagement_rate, 4),
            "fan_to_view_ratio": round(fan_to_view_ratio, 2),
            "follower_count": follower_count,
            "play_count": play_count,
            "digg_count": digg_count,
            "comment_count": comment_count,
            "collect_count": collect_count,
            "share_count": share_count,
            "nickname": author.get('nickname', '未知')
        }

    def run_advanced_search(self):
        if not self.adv_config.getboolean('Switch'):
            logger.info("高级筛选开关未开启，退出。")
            return

        topics_str = self.adv_config['Topic']
        # 支持逗号分隔的多个关键词
        keywords = [k.strip() for k in topics_str.split(',') if k.strip()]
        
        max_followers = self.adv_config.getint('Max_Followers')
        days = self.adv_config.getint('Search_Days')
        max_page = self.config.getint('Crawlers', 'Max_page', fallback=3)
        
        logger.info(f"开始高级搜索: 关键词列表={keywords}, 粉丝上限={max_followers}, 时间范围={days}天, 抓取页数={max_page}")
        
        try:
            with open('douyin_cookies.txt', 'r', encoding='utf-8') as f:
                cookies_str = f.read()
        except Exception as e:
            logger.error(f"无法读取 douyin_cookies.txt: {e}")
            return

        # 动态提取 verifyFp (s_v_web_id) 和 webid
        fp_match = re.search(r's_v_web_id=([^; ]+)', cookies_str)
        fp_val = fp_match.group(1) if fp_match else 'verify_lw66uj9x_y69HTWBr_NOK0_4O0k_As0k_vZiOREH3U5SC'
        
        webid_match = re.search(r'tt_webid=([^; ]+)', cookies_str)
        if not webid_match:
            webid_match = re.search(r'webid=([^; ]+)', cookies_str)
        webid_val = webid_match.group(1) if webid_match else '7163531063863133732'

        for keyword in keywords:
            logger.info(f"===== 正在搜索关键词: [{keyword}] =====")
            search_keywords_encoded = quote(keyword)
            # publish_time 参数: 0-不限, 1-一天内, 7-一周内, 180-半年内等
            publish_time_val = days if days in [1, 7, 30, 90, 180] else 0 
            
            # 强制时间过滤：计算 cutoff 时间戳
            now_ts = int(time.time())
            cutoff_ts = now_ts - (days * 24 * 3600)
            logger.info(f"严格时间过滤已开启: 仅抓取 {datetime.datetime.fromtimestamp(cutoff_ts).strftime('%Y-%m-%d')} 之后发布的视频")

            cursor = 0
            for page in range(max_page):
                # 随机生成 msToken
                msToken = douyin_video.generate_random_str()
                # 随机化单次抓取数量
                random_count = random.randint(17, 25)
                logger.info(f"--- 正在抓取 [{keyword}] 第 {page + 1} 页 (offset={cursor}, count={random_count}) ---")

                # 模仿原代码中的长 URL，包含浏览器指纹等参数
                url = (
                    f"https://www.douyin.com/aweme/v1/web/search/item/?"
                    f"device_platform=webapp&aid=6383&channel=channel_pc_web&search_channel=aweme_video_web"
                    f"&sort_type=0&publish_time={publish_time_val}&keyword={search_keywords_encoded}"
                    f"&search_source=switch_tab&query_correct_type=1&is_filter_search=0&from_group_id="
                    f"&offset={cursor}&count={random_count}&pc_client_type=1&version_code=170400&version_name=17.4.0"
                    f"&cookie_enabled=true&screen_width=1920&screen_height=1080&browser_language=zh-CN"
                    f"&browser_platform=Win32&browser_name=Chrome&browser_version=131.0.0.0"
                    f"&browser_online=true&engine_name=Blink&engine_version=131.0.0.0&os_name=Windows"
                    f"&os_version=10&cpu_core_num=16&device_memory=8&platform=PC&downlink=10"
                    f"&effective_type=4g&round_trip_time=0&webid={webid_val}"
                    f"&verifyFp={fp_val}&fp={fp_val}&msToken={msToken}"
                )

                headers = {
                    'authority': 'www.douyin.com',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'referer': f'https://www.douyin.com/search/{search_keywords_encoded}?publish_time=0&sort_type=0&source=switch_tab&type=video',
                    'cookie': cookies_str,
                    'accept': 'application/json, text/plain, */*'
                }
                    
                # 生成 a_bogus 签名
                query_params = url.split('?')[1]
                ab = douyin_a_bogus.get_ab(target_url=query_params, user_agent=headers['user-agent'], cookie_str=cookies_str)
                if ab:
                    url += f"&a_bogus={ab}"
                    logger.debug(f"生成 a_bogus 成功: {ab[:10]}...")
                else:
                    logger.warning("生成 a_bogus 失败，尝试原样发送请求")

                res_text = self.simple_get(url, headers)
                if not res_text:
                    logger.error(f"关键词 [{keyword}] 搜索请求失败，没有返回内容")
                    break

                try:
                    data = json.loads(res_text)
                except Exception as e:
                    logger.error(f"解析 JSON 失败: {e}. 响应内容前100字符: {res_text[:100]}")
                    break

                if data.get('status_code') != 0:
                    logger.error(f"API 返回状态码异常: {data.get('status_code')}, 消息: {data.get('status_msg')}")
                    # 如果返回 0 但是 aweme_list 为空可能是因为触发了 verify_check
                    if "verify_check" in res_text:
                        logger.warning("触发了 verify_check，可能需要更新 Cookie 或等待后重试。")
                    break

                videos = data.get('data', [])
                if not videos:
                    # 获取 nil_info 以判断是否触发验证码 (verify_check)
                    nil_info = data.get('search_nil_info', {})
                    nil_type = nil_info.get('search_nil_type')
                    status_msg = data.get('status_msg', 'No Msg')
                    
                    if nil_type == 'verify_check' or "verify_check" in res_text:
                        logger.error(f"关键词 [{keyword}] 第 {page + 1} 页触发了 verify_check (验证码拦截/Anti-Scraping)！请重新运行 refresh_douyin_cookies.py。")
                    elif nil_type:
                        logger.warning(f"关键词 [{keyword}] 第 {page + 1} 页结果为空, nil_type={nil_type}, msg={status_msg}")
                    else:
                        logger.warning(f"关键词 [{keyword}] 第 {page + 1} 页结果列表为空, status_msg={status_msg}")
                    break
                
                logger.info(f"关键词 [{keyword}] 第 {page + 1} 页成功获取 {len(videos)} 个原始视频")

                for item in videos:
                    video_info = item.get('aweme_info')
                    if not video_info: continue
                    
                    aweme_id = video_info['aweme_id']
                    author = video_info.get('author', {})
                    nickname = author.get('nickname', '未知')
                    
                    # 严格时间校验 (几天内)
                    create_time = video_info.get('create_time', 0)
                    if create_time < cutoff_ts:
                        logger.info(f"丢弃过时视频 {aweme_id}: 发布时间 {datetime.datetime.fromtimestamp(create_time).strftime('%Y-%m-%d')} 超过限定范围")
                        continue

                    metrics = self.calculate_interaction_value(video_info)
                    if metrics['follower_count'] > max_followers:
                        logger.info(f"跳过 UP主 {nickname}: 粉丝数 {metrics['follower_count']} > {max_followers}")
                        continue
                    
                    if metrics['comment_count'] < self.min_comments:
                        logger.info(f"忽略视频 {aweme_id}: 评论数 {metrics['comment_count']} < {self.min_comments}")
                        continue
                    
                    logger.info(f"符合条件: {nickname} - {video_info['desc'][:20]} (互动率: {metrics['engagement_rate']}, 周期: {days}天内)")
                    
                    try:
                        # 抓取详情前增加随机休眠
                        time.sleep(random.uniform(1.0, 3.0))
                        detail = douyin_video.get_douyin_origin_video(aweme_id=aweme_id)
                        if not detail:
                            logger.warning(f"获取视频 {aweme_id} 原始详情失败")
                            continue
                        
                        # 准备保存数据
                        publish_time_str = detail.get('publishTime', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        
                        data_tuple = (
                            aweme_id,
                            detail.get('title', video_info['desc']),
                            detail.get('originVideo'),
                            detail.get('imageUrl'),
                            None, # playtime
                            metrics['play_count'],
                            '抖音_高级',
                            time.time(),
                            keyword,
                            metrics['engagement_rate'],
                            metrics['fan_to_view_ratio'],
                            metrics['follower_count'],
                            metrics['play_count'],
                            metrics['digg_count'],
                            metrics['comment_count'],
                            metrics['collect_count'],
                            metrics['share_count'],
                            nickname,
                            publish_time_str,
                            datetime.datetime.now()
                        )
                        
                        if self.db_type == 'mysql' and self.conn:
                            with self.conn.cursor() as cursor_db:
                                sql = """
                                INSERT INTO videos (
                                    video_id, video_title, video_url, video_pic, video_playtime, 
                                    video_watch_num, video_datafrom, video_update_time, keywords, 
                                    engagement_rate, fan_to_view_ratio, follower_count, play_count, 
                                    digg_count, comment_count, collect_count, share_count, nickname, publish_time, crawl_time
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    video_title=VALUES(video_title), video_url=VALUES(video_url), video_pic=VALUES(video_pic),
                                    video_watch_num=VALUES(video_watch_num), video_update_time=VALUES(video_update_time),
                                    engagement_rate=VALUES(engagement_rate), publish_time=VALUES(publish_time), crawl_time=VALUES(crawl_time)
                                """
                                cursor_db.execute(sql, data_tuple)
                            self.conn.commit()
                            logger.success(f"MySQL 保存成功: {aweme_id}")
                        elif self.collection is not None:
                            mongo_data = {
                                "video_id": aweme_id,
                                "video_title": detail.get('title', video_info['desc']),
                                "video_url": detail.get('originVideo'),
                                "video_pic": detail.get('imageUrl'),
                                "video_watch_num": metrics['play_count'],
                                "video_datafrom": '抖音_高级',
                                "video_update_time": time.time(),
                                "keywords": keyword,
                                "engagement_rate": metrics['engagement_rate'],
                                "follower_count": metrics['follower_count'],
                                "nickname": nickname,
                                "publish_time": publish_time_str
                            }
                            self.collection.update_one({'video_id': aweme_id}, {'$set': mongo_data}, upsert=True)
                            logger.success(f"MongoDB 保存成功: {aweme_id}")
                    except Exception as e:
                        logger.error(f"处理视频 {aweme_id} 失败: {e}")

                # 翻页前的随机休眠
                if page < max_page - 1:
                    sleep_time = random.uniform(3.0, 6.0)
                    logger.info(f"关键词 [{keyword}] 等待 {sleep_time:.2f} 秒后加载下一页...")
                    time.sleep(sleep_time)
                
                # 更新 offset
                cursor = data.get('cursor', cursor + random_count)
                if not data.get('has_more'):
                    logger.info(f"关键词 [{keyword}] 没有更多数据，停止翻页。")
                    break

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

if __name__ == '__main__':
    crawler = DouyinAdvancedCrawler()
    crawler.run_advanced_search()
