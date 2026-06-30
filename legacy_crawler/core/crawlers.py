import json
import time
import datetime
import requests
import random
import sys
from pymongo import MongoClient
import re
import threadpool
from urllib.parse import quote
import configparser
import os
import undetected_chromedriver as uc
from . import douyin_a_bogus
from . import douyin_video

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
crawlers_config = config['Crawlers']
path_config = config['Path']
# 请求时最大线程数
MAX_THREAD = int(crawlers_config['Max_thread'])
# tiktok douyin 关键字搜索视频结果分页,最多为3
MAX_PAGE = int(crawlers_config['Max_page'])


class Crawlers(object):
    def __init__(self):
        print(f'初始化爬虫...')
        self.tiktok_headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36'}
        self.tiktok_api_headers = {
            'user-agent': 'com.ss.android.ugc.trill/2613 (Linux; U; Android 10; en_US; Pixel 4; Build/QQ3A.200805.001; Cronet/58.0.2991.0)'}
        self.db_type = config.get('Database', 'Type', fallback='mongodb').lower()
        self.mysql_config = config['MySQL']
        
        # 初始化 MongoDB
        try:
            if len(sys.argv) > 1 and sys.argv[1] == 'test':
                client = MongoClient(host=path_config['Mongo_host_local'], port=int(path_config['Mongo_port']),
                                     username=path_config['Mongo_username'], password=path_config['Mongo_password'],
                                     authSource='admin', authMechanism='SCRAM-SHA-256')
            elif path_config.get('Mongo_username', None) and path_config.get('Mongo_password', None):
                client = MongoClient(host=path_config['Mongo_host_server'], port=int(path_config['Mongo_port']),
                                     username=path_config['Mongo_username'], password=path_config['Mongo_password'],
                                     authSource='admin', authMechanism='SCRAM-SHA-256')
            else:
                client = MongoClient(host=path_config['Mongo_host_server'], port=int(path_config['Mongo_port']))
            self.db = client['handling_vedio']
            self.collection = self.db['vedios']
        except Exception as e:
            print(f"MongoDB 初始化失败: {e}")
            self.collection = None

        # 初始化 MySQL 数据库（如果启用）
        self.mysql_conn = None
        if self.db_type == 'mysql':
            try:
                import pymysql
                self.mysql_conn = pymysql.connect(
                    host=self.mysql_config['Host'],
                    port=int(self.mysql_config['Port']),
                    user=self.mysql_config['User'],
                    password=self.mysql_config['Password'],
                    database=self.mysql_config['Database'],
                    charset='utf8mb4',
                    cursorclass=pymysql.cursors.DictCursor
                )
                self.create_mysql_table_if_not_exists()
            except Exception as e:
                print(f"MySQL 初始化失败: {e}")
        self.info = {'video_id': None, 'video_title': None, 'video_url': None, 'audio_url': None,
                     'update_timestamp': None}
        self.youtube_results = []
        self.tiktok_results = []
        self.douyin_results = []
        self.toutiao_results = []
        self.arg = sys.argv[1]
        if crawlers_config['Proxy_switch'] == 'False':
            self.proxy = None
        elif crawlers_config['Use_socks5_proxy'] == 'True':
            self.proxy = {"http": crawlers_config['Socks5_proxy'], "https": crawlers_config['Socks5_proxy']}
        elif crawlers_config['Use_simple_proxy'] == 'True':
            self.proxy = {"http": 'http://' + crawlers_config['Socks5_proxy'],
                          "https": 'https://' + crawlers_config['Socks5_proxy']}
        else:
            self.proxy = None

    def create_mysql_table_if_not_exists(self):
        if not self.mysql_conn: return
        with self.mysql_conn.cursor() as cursor:
            sql = """
            CREATE TABLE IF NOT EXISTS videos (
                video_id VARCHAR(64) PRIMARY KEY,
                video_title TEXT,
                video_url TEXT,
                video_pic TEXT,
                video_playtime VARCHAR(32),
                video_watch_num VARCHAR(64),
                video_datafrom VARCHAR(32),
                video_update_time DOUBLE,
                keywords VARCHAR(255),
                has_handling BOOLEAN DEFAULT FALSE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
            cursor.execute(sql)
        self.mysql_conn.commit()

    def save_to_db(self, video):
        video_id = video['video_id']
        if self.db_type == 'mysql' and self.mysql_conn:
            try:
                with self.mysql_conn.cursor() as cursor:
                    sql = """
                    INSERT INTO videos (video_id, video_title, video_url, video_pic, video_playtime, video_watch_num, video_datafrom, video_update_time, keywords)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        video_title=VALUES(video_title), video_url=VALUES(video_url), video_pic=VALUES(video_pic),
                        video_watch_num=VALUES(video_watch_num), video_update_time=VALUES(video_update_time)
                    """
                    cursor.execute(sql, (
                        video_id, video.get('video_title'), video.get('video_url'), video.get('video_pic'),
                        video.get('video_playtime'), str(video.get('video_watch_num')), video.get('video_datafrom'),
                        video.get('video_update_time'), video.get('keywords')
                    ))
                self.mysql_conn.commit()
                print(f'MySQL 写入/更新成功: {video_id}')
            except Exception as e:
                print(f'MySQL 写入异常: {e}')
        elif self.collection is not None:
            try:
                if self.collection.find_one({'video_id': video_id}):
                    self.collection.update_one({'video_id': video_id}, {'$set': video})
                    print(f'MongoDB 更新成功: {video_id}')
                else:
                    self.collection.insert_one(video)
                    print(f'MongoDB 写入成功: {video_id}')
            except Exception as e:
                print(f'MongoDB 写入失败: {e}')
        else:
            print(f'无法保存视频 {video_id}: 没有任何数据库连接可用')

    def check_exists(self, video_id):
        if self.db_type == 'mysql' and self.mysql_conn:
            with self.mysql_conn.cursor() as cursor:
                cursor.execute("SELECT video_id, video_update_time FROM videos WHERE video_id = %s", (video_id,))
                return cursor.fetchone()
        elif self.collection is not None:
            return self.collection.find_one({'video_id': video_id})
        return None

    def update_tiktok_cookies(self):
        print('chrome 正在启动', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        opt = uc.ChromeOptions()
        opt.add_argument('--no-first-run')
        opt.add_argument('--no-service-autorun')
        opt.add_argument('--password-store=basic')
        opt.add_argument('--lang=en-US')
        opt.add_argument('--mute-audio')
        opt.add_argument('--disable-gpu')
        opt.add_argument('--headless')
        _browser = uc.Chrome(options=opt, version_main=int(path_config['chrome_version']))
        print('chrome 启动成功', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        _browser.implicitly_wait(10)
        _browser.get('https://www.tiktok.com/foryou?is_copy_url=1&is_from_webapp=v1')
        time.sleep(random.uniform(2, 3))
        cookies = _browser.get_cookies()
        cookies = {cookie['name']: cookie['value'] for cookie in cookies}
        if len(cookies) > 0:
            try:
                _browser.quit()
                with open('tiktok_cookies.json', 'w') as f:
                    f.write(json.dumps(cookies))
            except:
                pass
            return cookies
        else:
            try:
                _browser.quit()
            except:
                pass
            return None

    def tiktok_crawler(self, search_keywords):
        self.tiktok_results = []
        # 先关键词搜索视频
        video_list = []
        # 旧版废弃
        # for i in range(MAX_PAGE):
        #     try:
        #         temp, has_more = self.tiktok_search_video(search_keywords, offset=12 * i)
        #     except:
        #         continue
        #     if has_more == 1:
        #         for one in temp:
        #             video_list.append(one)
        #     else:
        #         for one in temp:
        #             video_list.append(one)
        #         break

        # 新版
        video_list.extend(self.tiktok_search_video_remote(search_keywords))
        # new_video_list = []
        # for video in video_list:
        #     video_id = video['video_id']
        #     if self.collection.find_one({'video_id': video_id}) is None or (time.time() - self.collection.find_one({'video_id': video_id})['video_update_time'] > 30 * 60):
        #         new_video_list.append(video)
        #     else:
        #         continue
        print(f'tiktok需要更新视频数量: {len(video_list)}')
        if video_list:
            # 旧版废弃
            # params = [(None, {'video_id': video['video_id']}) for video in new_video_list]
            # pool = threadpool.ThreadPool(MAX_THREAD)
            # tasks = threadpool.makeRequests(self.tiktok_video_info, params, self.save_result_tiktok)
            # [pool.putRequest(req) for req in tasks]
            # pool.wait()
            # for video in new_video_list:
            #     for task in tasks:
            #         if video['video_id'] == task.kwds['video_id']:
            #             for result in self.tiktok_results:
            #                 if result['request_id'] == task.requestID:
            #                     video['video_url'] = result['results']
            #                 else:
            #                     continue
            #         else:
            #             continue
            for video in video_list:
                if 'video_url' in video.keys():
                    if video['video_url'] is not None and video['video_url'] != '':
                        self.save_to_db(video)
                    else:
                        print(f'tiktok video_url is None... skip saving')
                        continue
                else:
                    print(f'tiktok video_url is not in keys... skip saving')
                    continue
        else:
            print(f' 采集tiktok视频出现异常, keywords:{search_keywords}')

    def youtube_crawler(self, search_keywords):
        self.youtube_results = []
        video_list = []
        try:
            video_list = self.youtube_search_video(search_keywords)
        except Exception as e:
            print(f"youtube_search_video 失败: {e}")
            video_list = []
        new_video_list = []
        print(f"开始循环，video_list 长度: {len(video_list)}")
        for i, video in enumerate(video_list):
            print(f"循环第{i + 1}次，视频ID: {video.get('video_id', '未知')}")
            video_id = video['video_id']
            # 检查数据库连接
            try:
                record = self.collection.find_one({'video_id': video_id})
                print(f"record查询成功: {record is not None}")
            except Exception as db_error:
                print(f"⚠️ 数据库查询异常: {db_error}")
                # 这里可以决定是继续还是跳出
                continue
            print(f'record:{record}')
            record = self.check_exists(video_id)
            if record:
                # 兼容两种数据库的返回
                update_time = record.get('video_update_time') if isinstance(record, dict) else record[1]
                time_diff = time.time() - update_time
                should_update = time_diff > 30 * 60
                print(f'应该更新：{should_update}')
            else:
                should_update = True
                print("无记录")
            if should_update:
                new_video_list.append(video)
            else:
                continue
        print(f'youtube需要更新视频数量: {len(new_video_list)}')
        # print(new_video_list)
        if new_video_list is not None:
            params = [(None, {'video_id': video['video_id']}) for video in new_video_list]
            pool = threadpool.ThreadPool(MAX_THREAD)
            tasks = threadpool.makeRequests(self.youtube_video_info, params, self.save_result)
            [pool.putRequest(req) for req in tasks]
            pool.wait()
            for video in new_video_list:
                for task in tasks:
                    if video['video_id'] == task.kwds['video_id']:
                        for result in self.youtube_results:
                            if result['request_id'] == task.requestID:
                                video['video_url'] = result['results']['video_url']
                                video['audio_url'] = result['results']['audio_url']
                            else:
                                continue
                    else:
                        continue

            for video in new_video_list:
                if 'video_url' in video.keys() and video['video_url']:
                    self.save_to_db(video)
                else:
                    continue
        else:
            print(f' 采集youtube视频出现异常, keywords:{search_keywords}')

    def douyin_crawler(self, search_keywords):
        self.douyin_results = []
        video_list = []
        for i in range(MAX_PAGE):
            try:
                temp, has_more = self.douyin_search_video(search_keywords, offset=12 * i)
            except:
                continue
            if has_more == 1:
                for one in temp:
                    video_list.append(one)
            else:
                for one in temp:
                    video_list.append(one)
                break
        new_video_list = []
        for video in video_list:
            video_id = video['video_id']
            if self.collection.find_one({'video_id': video_id}) is None or (
                    time.time() - self.collection.find_one({'video_id': video_id})['video_update_time'] > 30 * 60):
                new_video_list.append(video)
            else:
                continue
        print(f'douyin 需要更新视频数量: {len(new_video_list)}')
        if new_video_list:
            for video in new_video_list:
                if 'video_url' in video.keys() and video['video_url']:
                    self.save_to_db(video)
                else:
                    print(f'douyin video_url is None... skip saving')
                    continue
        else:
            print(f'douyin 没有 需要更新视频, keywords:{search_keywords}')

    def toutiao_crawler(self, search_keywords):
        self.toutiao_results = []
        print(f'开启toutiao爬虫... keywords: {search_keywords}')
        if search_keywords in ["热点", "热梗"]:
            self.toutiao_hot_crawler()
        else:
            self.toutiao_search_video(search_keywords)

    def toutiao_hot_crawler(self):
        print("正在抓取今日头条热榜...")
        url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.toutiao.com/',
            'Accept': 'application/json, text/plain, */*'
        }
        res_text = self.simple_get(url, headers=headers)
        if res_text:
            try:
                data = json.loads(res_text)
                items = data.get('data', [])
                for item in items:
                    video_id = str(item.get('ClusterId', ''))
                    title = item.get('Title', '')
                    url = item.get('Url', '')
                    pic = item.get('Image', {}).get('url', '')
                    
                    # 过滤科技数码类 (如果需要)
                    # categories = item.get('InterestCategory', [])
                    # if 'technology' in categories or 'digital' in categories:
                    #     pass
                    
                    video = {
                        'keywords': '热点',
                        'video_id': video_id,
                        'video_title': title,
                        'video_url': url,
                        'video_pic': pic,
                        'video_playtime': None,
                        'video_watch_num': item.get('HotValue', 0),
                        'video_datafrom': 'toutiao',
                        'video_update_time': time.time()
                    }
                    self.save_to_db(video)
            except Exception as e:
                print(f"解析头条热榜失败: {e}")

    def toutiao_search_video(self, search_keywords):
        print(f"正在搜索头条视频: {search_keywords}")
        # 使用 UC 浏览器
        opt = uc.ChromeOptions()
        opt.add_argument('--headless')
        opt.add_argument('--no-sandbox')
        opt.add_argument('--disable-dev-shm-usage')
        
        try:
            driver = uc.Chrome(options=opt)
            search_url = f"https://so.toutiao.com/search?keyword={quote(search_keywords)}&pd=video"
            driver.get(search_url)
            time.sleep(5) # 等待加载
            
            # 尝试通过执行 JS 获取数据
            # 常见的 Toutiao 数据注入对象
            data = driver.execute_script("return window._SSR_DATA || window.initialData || (window.T && window.T.flowData)")
            
            if not data:
                # 备选方案: 这里的 DOM 结构可能会变，但先尝试一个通用的
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                # 寻找所有的 a 标签
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    # 处理相对链接
                    if href.startswith('/'):
                        href = 'https://so.toutiao.com' + href
                    
                    if '/search/jump?' in href or 'toutiao.com/video/' in href or 'toutiao.com/article/' in href:
                        # 尝试获取标题
                        title = link.get_text(strip=True)
                        if not title:
                            # 尝试找内部的 h1, h2, h3 或 div
                            title_elem = link.find(['h1', 'h2', 'h3', 'div'])
                            if title_elem: title = title_elem.get_text(strip=True)
                        
                        if len(title) < 5: continue
                        
                        # 提取 ID (如果是 jump 链接，尝试从参数中找，或者使用 hash)
                        video_id = ""
                        if 'video/' in href:
                             m = re.search(r'video/(\d+)', href)
                             if m: video_id = m.group(1)
                        if not video_id:
                             # 使用 URL 的 hash 作为 ID
                             import hashlib
                             video_id = hashlib.md5(href.encode()).hexdigest()
                        
                        video = {
                            'keywords': search_keywords,
                            'video_id': video_id,
                            'video_title': title,
                            'video_url': href,
                            'video_pic': None,
                            'video_playtime': None,
                            'video_watch_num': 0,
                            'video_datafrom': 'toutiao',
                            'video_update_time': time.time()
                        }
                        self.save_to_db(video)
            else:
                # 如果获取到了 JSON 数据，则进行解析 (根据实际结构)
                # print("获取到 SSR 数据")
                # 这里需要根据 data 的实际结构进一步解析，由于结构复杂，暂时打印
                pass
                
            driver.quit()
        except Exception as e:
            print(f"头条搜索爬虫异常: {e}")
            try: driver.quit()
            except: pass

    def save_result(self, request, result):
        self.youtube_results.append({'request_id': request.requestID, 'results': result})

    def save_result_tiktok(self, request, result):
        self.tiktok_results.append({'request_id': request.requestID, 'results': result})

    def tiktok_search_video(self, search_keywords, offset=0):
        cookiestr = "tt_csrf_token=poZiJA2w-g7ubYxO-IPYptHs43-fevP82K6c; tt_chain_token=LV3vyP9xkzu1olcUYxoMPA==; csrf_session_id=3c385bce12441f6a9adcb2b02b5e5dae; passport_csrf_token=13925ec1d3411be9048f73be0f660a95; passport_csrf_token_default=13925ec1d3411be9048f73be0f660a95; s_v_web_id=verify_lojksyop_PltyvHfO_6w5N_4DwS_AewM_sS6alf5MtDVD; multi_sids=7169356242610357254%3Af0585c4b10a9490c77eb0c414da470d4; cmpl_token=AgQQAPO8F-RO0rNARSMFN90__yRRexJef4A3YNODxQ; passport_auth_status=8dba23d8f1a6f74eb79aafed4c6e10fa%2C; passport_auth_status_ss=8dba23d8f1a6f74eb79aafed4c6e10fa%2C; sid_guard=f0585c4b10a9490c77eb0c414da470d4%7C1699110824%7C15552000%7CThu%2C+02-May-2024+15%3A13%3A44+GMT; uid_tt=afcd0f90ff8631face19e3f8a187453648b65e7c99ecafec77e51b179432c6a4; uid_tt_ss=afcd0f90ff8631face19e3f8a187453648b65e7c99ecafec77e51b179432c6a4; sid_tt=f0585c4b10a9490c77eb0c414da470d4; sessionid=f0585c4b10a9490c77eb0c414da470d4; sessionid_ss=f0585c4b10a9490c77eb0c414da470d4; sid_ucp_v1=1.0.0-KGMyNGM5ZmQ1NjE5MjE5MTM1MDI4MDVkZmMzNGQyNDA2YzQyOGFiY2MKHwiGiJToyPCqv2MQqL-ZqgYYswsgDDCDlvubBjgIQBIQAxoGbWFsaXZhIiBmMDU4NWM0YjEwYTk0OTBjNzdlYjBjNDE0ZGE0NzBkNA; ssid_ucp_v1=1.0.0-KGMyNGM5ZmQ1NjE5MjE5MTM1MDI4MDVkZmMzNGQyNDA2YzQyOGFiY2MKHwiGiJToyPCqv2MQqL-ZqgYYswsgDDCDlvubBjgIQBIQAxoGbWFsaXZhIiBmMDU4NWM0YjEwYTk0OTBjNzdlYjBjNDE0ZGE0NzBkNA; store-idc=alisg; store-country-code=sg; store-country-code-src=uid; tt-target-idc=alisg; tt-target-idc-sign=aL8uKtxviSyE5Urayg680oYvSQPlHCptrUNu0A50vNQtWjxDn4k0qL-IzEX_F4uVsDIH11h4Ld7xteVoPEN7X7j5TpZp2AeEw_xdP6-J6kGm74x_TW9Ij_I3lY3AFJZ0MXNRy_cIwqzy_AB1AfqtHlGTJ5cBi2x7vLVYGH-cRklp2purLxVRb7ofeJHQpvLhORGDpzCBdxuMjKpCDB992PzCMUCmyyibEyxIFy_TUZXquRhmcIkfRoVAbq5TwsdA6W2QpAyaN8ZS1MOkSpBqXMO8U6nF89XZnB49yiC_4YEC7x09_LUw_Uj9-idt6McglSyxzzEMNzShHjALyWNhEh-Y0sAsghC-R1yvn6Wl0-99AjqtiGl47AaKBeshO0J2hC_ojih5sqQUKgjSA2VZDatSRSHkNp535QMMUwVj_WTX7uSxwZpVPYkcxdz82kiC5Y0ayiA0YBDh8l0wpwNzo9jei5k53k5ojd3RsRkT6oYD2eFoUiDmcDH_CKf_-YVN; ttwid=1%7CPslqeUeyVJmPPQ_m2XdO-inB7WkSqW2h4e4P_ZxGZeE%7C1700471632%7C1f004ba9a4192e255a3ae80910ca98fc48f925429cd67d5b589b4eacbb8caa6a; msToken=nUPQqImtDM_NQKZgj14YiSn9x7sxb4MXPRmXJMP_0TK0jJvblzEEiTafq9tZclma4bfTjqX13vgK-TtsF1v1yP-Gm9kOpenFhlDPiC-1kyhH85JV8iPiKKIpPkUyn2D820hIe0LXf_mstVI=; odin_tt=7fa11e3dd2ce551f6d7a6aad704d6109f70424f6a6bf1c944e4d98b28535f26140e2f6f9eb8e4b5a1e719f71f52036e62ce8ddf8f49376ef581420643b8b0cb3595e9d0213e4ac88f9c1aa7a8569eb5e"
        keywords = search_keywords
        search_keywords = quote(search_keywords, safe='')
        print('search_keywords: ', search_keywords)
        url = f'https://www.tiktok.com/api/search/general/full/?aid=1988&app_language=zh-Hans&app_name=tiktok_web&browser_language=zh-CN&browser_name=Mozilla&browser_online=true&browser_platform=MacIntel&browser_version=5.0%20%28Macintosh%3B%20Intel%20Mac%20OS%20X%2010_15_7%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F118.0.0.0%20Safari%2F537.36&channel=tiktok_web&cookie_enabled=true&device_id=7291677034442016263&device_platform=web_pc&device_type=web_h264&focus_state=false&from_page=search&history_len=2&is_fullscreen=false&is_page_visible=true&keyword={search_keywords}&offset={offset}&os=mac&priority_region=&referer=&region=SG&screen_height=900&screen_width=1440&search_id=20231019143145139F4D25AFEB59234776&tz_name=Asia%2FShanghai&web_search_code=%7B%22tiktok%22%3A%7B%22client_params_x%22%3A%7B%22search_engine%22%3A%7B%22ies_mt_user_live_video_card_use_libra%22%3A1%2C%22mt_search_general_user_live_card%22%3A1%7D%7D%2C%22search_server%22%3A%7B%7D%7D%7D&webcast_language=zh-Hans'
        headers = {
            'authority': 'www.tiktok.com',
            'referer': 'https://www.tiktok.com/search?q=beautiful%20woman&t=1670318209758',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
            'cookie': cookiestr
        }
        res = self.simple_get(url=url, headers=headers)
        if res is None or res == '':
            print(f'直接请求失败, 开始curl请求...')
            curl_code = f"curl 'https://www.tiktok.com/api/search/general/full/?aid=1988&app_language=zh-Hans&app_name=tiktok_web&browser_language=zh-CN&browser_name=Mozilla&browser_online=true&browser_platform=MacIntel&browser_version=5.0%20%28Macintosh%3B%20Intel%20Mac%20OS%20X%2010_15_7%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F118.0.0.0%20Safari%2F537.36&channel=tiktok_web&cookie_enabled=true&device_id=7291677034442016263&device_platform=web_pc&device_type=web_h264&focus_state=false&from_page=search&history_len=2&is_fullscreen=false&is_page_visible=true&keyword={search_keywords}&offset={offset}&os=mac&priority_region=&referer=&region=SG&screen_height=900&screen_width=1440&search_id=20231019143145139F4D25AFEB59234776&tz_name=Asia%2FShanghai&web_search_code=%7B%22tiktok%22%3A%7B%22client_params_x%22%3A%7B%22search_engine%22%3A%7B%22ies_mt_user_live_video_card_use_libra%22%3A1%2C%22mt_search_general_user_live_card%22%3A1%7D%7D%2C%22search_server%22%3A%7B%7D%7D%7D&webcast_language=zh-Hans' \
                    -H 'cookie: {cookiestr}' \
                    -H 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36' \
                    --compressed"
            res_curl = os.popen(curl_code).read()
            try:
                json.loads(res_curl)
                res = res_curl
            except:
                res = None
        has_more = 0
        if res is not None:
            print(f'res: {res}')
            results = []
            target = json.loads(res)
            if target['status_code'] < 300:
                if 'has_more' in target.keys():
                    if target['has_more'] == 1:
                        has_more = 1
                if 'data' not in target.keys():
                    return results, False
                videos = target['data']
                for video in videos:
                    if 'item' in video.keys():
                        video = video['item']
                    else:
                        continue
                    temp = {'keywords': keywords, 'video_id': video['id'], 'video_pic': video['video']['cover'],
                            'video_title': video['desc']
                            }
                    if re.search(r'(.+?)#', video['desc']):
                        temp['video_title'] = re.search(r'(.+?)#', video['desc']).group(1)
                    elif re.search(r'(.+?)@', video['desc']):
                        temp['video_title'] = re.search(r'(.+?)@', video['desc']).group(1)
                    else:
                        pass
                    temp['video_playtime'] = None
                    temp['video_watch_num'] = video['stats']['playCount']
                    temp['video_h5_url'] = video['video']['playAddr']
                    temp['video_datafrom'] = 'tiktok'
                    temp['video_update_time'] = time.time()
                    temp['audio_url'] = None
                    print(temp)
                    results.append(temp)
                return results, has_more
            else:
                raise Exception(f'tiktok: 更新: {search_keywords} 失败!!! 接口返回异常')
        else:
            raise Exception(f'tiktok: 更新: {search_keywords} 失败!!! 请检查接口')

    def tiktok_search_video_remote(self, search_keywords, pages=3):
        print('search_keywords: ', search_keywords)
        url = f'http://185.212.58.40:7758/tiktok_search'
        headers = {
            "Content-Type": "application/json",
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
            'cookie': "token=dongdonglongbbb@gmail.com"
        }
        data = {"keyword": search_keywords, "sort": 0, "platform": "tiktok", "pages": pages}
        res = self.simple_post(url=url, headers=headers, data_json=json.dumps(data))
        if res is not None:
            print(f'res: {res}')
            results = []
            target = json.loads(res)
            for video in target['data']:
                temp = {'keywords': search_keywords, 'video_id': video['video_id'], 'video_pic': video['cover'],
                        'video_title': video['description']
                        }
                if re.search(r'(.+?)#', video['description']):
                    temp['video_title'] = re.search(r'(.+?)#', video['description']).group(1)
                elif re.search(r'(.+?)@', video['description']):
                    temp['video_title'] = re.search(r'(.+?)@', video['description']).group(1)
                else:
                    pass
                temp['video_playtime'] = None
                temp['video_watch_num'] = video['play_count']
                temp['video_h5_url'] = video['download_no_watermark_addr']
                temp['video_url'] = video['download_no_watermark_addr']
                temp['video_datafrom'] = 'tiktok'
                temp['video_update_time'] = time.time()
                temp['audio_url'] = None
                print(temp)
                results.append(temp)
            return results
        else:
            raise Exception(f'tiktok: 更新: {search_keywords} 失败!!! 请检查接口')

    def tiktok_video_info(self, video_id):
        openudid = ''.join(random.sample('0123456789abcdef', 16))
        uuid = ''.join(random.sample('01234567890123456', 16))
        req_ticket = str(int(time.time() * 1000))
        ts = int(time.time())
        url = f'https://api-h2.tiktokv.com/aweme/v1/feed/?aweme_id={video_id}&version_name=37.0.4&version_code=370004&build_number=37.0.4&manifest_version_code=2023700040&update_version_code=2023700040&openudid={openudid}&uuid={uuid}&_rticket={req_ticket}&ts={ts}&device_brand=Redmi&device_type=Redmi%20K30%20Pro%20Zoom%20Edition&device_platform=android&resolution=1080*1920&dpi=420&os_version=10&os_api=29&carrier_region=US&sys_region=US%C2%AEion=US&app_name=trill&app_language=en&language=en&timezone_name=America/New_York&timezone_offset=-14400&channel=googleplay&ac=wifi&mcc_mnc=310260&is_my_cn=0&aid=1180&ssmix=a&as=a1qwert123&cp=cbfhckdckkde1'
        headers = self.tiktok_api_headers
        res = self.simple_get(url, headers)
        # input('test:::')
        if res is not None:
            data = json.loads(res)
            video_info = data['aweme_list'][0]
            video_url = None
            if 'play_addr' in video_info['video'].keys():
                if len(video_info['video']['play_addr']['url_list']) > 0:
                    video_url = video_info['video']['play_addr']['url_list'][0]
                else:
                    pass
            elif 'play_addr_265' in video_info['video'].keys():
                video_url = video_info['video']['play_addr_265']['url_list'][0]

            elif 'play_addr_h264' in video_info['video'].keys():
                video_url = video_info['video']['play_addr_264']['url_list'][0]
            else:
                pass
            print(f'tiktok video_url: {video_url}')
            return video_url
        else:
            print(f'tiktok 获取 {video_id} 详情失败!!!')
            return None

    def youtube_search_video(self, search_keywords):
        url = 'https://www.youtube.com/youtubei/v1/search?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8&prettyPrint=false'
        headers = {
            'cookie': 'HSID=AktAVU9oMHDHxfM0v; SSID=AkbYFPo2H60u9Jk9u; APISID=2kKwtuXoWzZ9bW0f/AM72Ibg2XB5kgHuz4; SAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; __Secure-1PAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; __Secure-3PAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; LOGIN_INFO=AFmmF2swRgIhAKKuCnL5P8p8NyfaSzyvdfeaGhE8H-umi4u8HGw-EeutAiEAz_F7bBnQG6kJYSzqufcw3K-FYEhUoqxf5h9wPKo3qzI:QUQ3MjNmekhuWERYd3plWlROVTFRRWg3NWVFdW92ZTJ5bjhXcTM5dnd1eUJTYmVUb0hYMEtTdkFBSXVSdDk3RFpKdmJZbnZ4ZDhMU1NxVHFwNmRQckRrbjl2cV9BUUx5czljdlBTMDFqeWxJZm9tUWFyWGI5bUJib05SU3NJdHdMZ3c2N1JFWHVDdXRHcWo4RkhNVFFaZU5adXdPeVU2dllB; SID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F2KFb1Ii7vZXYyDVpR01CwNAACgYKASASARISFQHGX2Mi0lqEYLLMZAP7CykZLrOWxRoVAUF8yKrWsZy7-0TRrzFbyRHvcUnj0076; __Secure-1PSID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F2l_hEcQuXh-tqU7iEp7KfKgACgYKAUESARISFQHGX2MiRikWldSLEJ8T7qun1Eik_hoVAUF8yKpsNQDv_1RXm03TRikTvXyC0076; __Secure-3PSID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F25jG5fEvviVn9RGU1jeTeIAACgYKAe8SARISFQHGX2Mi7C75OevAmnLfkur0QVyGfxoVAUF8yKrA2fjn5ze1dnBPvWLYC-W00076; PREF=tz=America.Los_Angeles&f5=30000&f7=100&f3=8&f4=4000000; __Secure-1PSIDTS=sidts-CjQBflaCdcU1-58WJ3VjS2nk3QfR8hIb3xhbxO33ZXW3wD6W5O4ZfAUQG96jWArdH6I5LWeYEAA; __Secure-3PSIDTS=sidts-CjQBflaCdcU1-58WJ3VjS2nk3QfR8hIb3xhbxO33ZXW3wD6W5O4ZfAUQG96jWArdH6I5LWeYEAA; SIDCC=AKEyXzU9wLOFBpGXZDkNvzNTn3lIX8qfq6_x7xprjbktSsOFI7vuYuQVvp6dwLYxO5-0pU6xbX4; __Secure-1PSIDCC=AKEyXzVKPeW7WSbe0Da7L1P5xvWK8RIqbxQeSPkFUO_-ne4Lyw4rPIW2tF73fNbQ19joeTuKj_u_; __Secure-3PSIDCC=AKEyXzVbu-gjucRR6MqRRQQlrjhsyvosw-2atrC_oV3e-qM9HfGTrVEftmca5iuOpawjZc8hnqGU; VISITOR_INFO1_LIVE=RQ-WbwGHy58; VISITOR_PRIVACY_METADATA=CgJWThIEGgAgYQ%3D%3D; YSC=7xyHjCHoT8I; __Secure-YNID=14.YT=k94-n5m-pRB3njixA3gVg53fIILT_uWOeCOGwf5_Kazh12AE3O8O51PGQjafZMp1t4YCGzJ_iORknKF61InUhSXLtlmbUvK5_GlM7WEIWhgCh4TDL-7_IZj6v9zcR2cxucc6_2TBYZnT5cO9BpvHXymKaW1BhqcgLE8lvG4jD1jaIj9B6O5LBZi7LV5XlZUOl7eP3VsnvJdi9KTEML8QtuhOF5yP6PehluFpZ2l8jkkvH2ldrybGfjLWAE9nN4vBuaCk9LKUB3ONS62HS5xLsAo0enHWtLUr9r2fZP0tsWQQ2wdYc0ZNuZapHPhKliSWsta_fgyrK_QlW4yeJW8glA; __Secure-ROLLOUT_TOKEN=CKCS7LLAro_WNRD_msWU9dWJAxj6ioSr392RAw%3D%3D',
            'authority': 'www.youtube.com',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'x-goog-visitor-id': 'CgtSUS1XYndHSHk1OCjhqL_KBjIKCgJWThIEGgAgYWLfAgrcAjE0LllUPWs5NC1uNW0tcFJCM25qaXhBM2dWZzUzZklJTFRfdVdPZUNPR3dmNV9LYXpoMTJBRTNPOE81MVBHUWphZlpNcDF0NFlDR3pKX2lPUmtuS0Y2MUluVWhTWEx0bG1iVXZLNV9HbE03V0VJV2hnQ2g0VERMLTdfSVpqNnY5emNSMmN4dWNjNl8yVEJZWm5UNWNPOUJwdkhYeW1LYVcxQmhxY2dMRThsdkc0akQxamFJajlCNk81TEJaaTdMVjVYbFpVT2w3ZVAzVnNudkpkaTlLVEVNTDhRdHVoT0Y1eVA2UGVobHVGcFoybDhqa2t2SDJsZHJ5YkdmakxXQUU5bk40dkJ1YUNrOUxLVUIzT05TNjJIUzV4THNBbzBlbkhXdExVcjlyMmZaUDB0c1dRUTJ3ZFljMFpOdVphcEhQaEtsaVNXc3RhX2ZneXJLX1FsVzR5ZUpXOGdsQQ%3D%3D'
        }
        country = random.choice(['US', 'SG', 'JP'])
        ip = random.choice(['172.53.173.232', '172.105.229.161', '182.125.229.161', '192.53.173.232'])
        data = {"context": {
            "client": {"hl": "en-US", "gl": f"{country}", "remoteHost": f"{ip}", "deviceMake": "", "deviceModel": "",
                       "visitorData": "CgtSUS1XYndHSHk1OCjhqL_KBjIKCgJWThIEGgAgYWLfAgrcAjE0LllUPWs5NC1uNW0tcFJCM25qaXhBM2dWZzUzZklJTFRfdVdPZUNPR3dmNV9LYXpoMTJBRTNPOE81MVBHUWphZlpNcDF0NFlDR3pKX2lPUmtuS0Y2MUluVWhTWEx0bG1iVXZLNV9HbE03V0VJV2hnQ2g0VERMLTdfSVpqNnY5emNSMmN4dWNjNl8yVEJZWm5UNWNPOUJwdkhYeW1LYVcxQmhxY2dMRThsdkc0akQxamFJajlCNk81TEJaaTdMVjVYbFpVT2w3ZVAzVnNudkpkaTlLVEVNTDhRdHVoT0Y1eVA2UGVobHVGcFoybDhqa2t2SDJsZHJ5YkdmakxXQUU5bk40dkJ1YUNrOUxLVUIzT05TNjJIUzV4THNBbzBlbkhXdExVcjlyMmZaUDB0c1dRUTJ3ZFljMFpOdVphcEhQaEtsaVNXc3RhX2ZneXJLX1FsVzR5ZUpXOGdsQQ%3D%3D",
                       "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36,gzip(gfe)",
                       "clientName": "WEB", "clientVersion": "2.20221103.04.00", "osName": "Windows",
                       "osVersion": "10.0",
                       "originalUrl": f"https://www.youtube.com/results?search_query={search_keywords}",
                       "platform": "DESKTOP", "clientFormFactor": "UNKNOWN_FORM_FACTOR", "configInfo": {
                    "appInstallData": "CLT1kZsGENSDrgUQm8quBRCZxq4FEJ_QrgUQsoj-EhCpp64FELjUrgUQt9yuBRCHkf4SEOK5rgUQuIuuBRCR-PwSENi-rQU%3D"},
                       "userInterfaceTheme": "USER_INTERFACE_THEME_DARK", "timeZone": "Asia/Shanghai",
                       "browserName": "Chrome", "browserVersion": "143.0.0.0",
                       "acceptHeader": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                       "deviceExperimentId": "ChxOekUyTVRrNE5ESXlNamd5TWpBeU16WTNOdz09ELT1kZsG",
                       "screenWidthPoints": 1272, "screenHeightPoints": 1297, "screenPixelDensity": 1,
                       "screenDensityFloat": 1, "utcOffsetMinutes": 480, "memoryTotalKbytes": "8000000",
                       "mainAppWebInfo": {"graftUrl": "/results?search_query=funny+video",
                                          "pwaInstallabilityStatus": "PWA_INSTALLABILITY_STATUS_UNKNOWN",
                                          "webDisplayMode": "WEB_DISPLAY_MODE_BROWSER",
                                          "isWebNativeShareAvailable": True}}, "user": {"lockedSafetyMode": False},
            "request": {"useSsl": True, "internalExperimentFlags": [], "consistencyTokenJars": []},
            "clickTracking": {"clickTrackingParams": "CA0Q7VAiEwi588CKv5P7AhXQ_TgGHUB3BNI="}, "adSignalsInfo": {
                "params": [{"key": "dt", "value": "1667529402961"}, {"key": "flash", "value": "0"},
                           {"key": "frm", "value": "0"}, {"key": "u_tz", "value": "480"},
                           {"key": "u_his", "value": "2"}, {"key": "u_h", "value": "1440"},
                           {"key": "u_w", "value": "2560"}, {"key": "u_ah", "value": "1400"},
                           {"key": "u_aw", "value": "2560"}, {"key": "u_cd", "value": "24"},
                           {"key": "bc", "value": "31"}, {"key": "bih", "value": "1297"},
                           {"key": "biw", "value": "1256"},
                           {"key": "brdim", "value": "0,0,0,0,2560,0,2560,1400,1272,1297"},
                           {"key": "vis", "value": "1"}, {"key": "wgl", "value": "true"},
                           {"key": "ca_type", "value": "image"}]}}, "query": f"{search_keywords}",
            "webSearchboxStatsUrl": "/search?oq=funny&gs_l=youtube.12.0.0i512i433k1j0i512i433i131k1l4j0i512i433k1j0i512i3k1j0i512k1j0i512i433k1l2j0i512k1l4.9687.10621.0.16257.7.7.0.0.0.0.331.650.3-2.4.0....0...1ac.1j4.64.youtube..3.2.650.0..0i433i131k1.325.fYjIXqBJKd4"}

        res = self.simple_post(url=url, headers=headers, data_json=json.dumps(data))
        if res is not None:
            target = json.loads(res)
            try:
                all_video = \
                    target['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer'][
                        'contents'][0]['itemSectionRenderer']['contents']
                target_video = filter(lambda x: 'videoRenderer' in x.keys(), all_video)
                target_video = [one['videoRenderer'] for one in target_video]
                video_list = []
                for video in target_video:
                    video_id = video['videoId']
                    video_datafrom = 'youtube'
                    video_update_time = time.time()
                    video_h5_url = f'https://www.youtube.com/watch?v={video_id}'
                    if len(video['thumbnail']['thumbnails']) > 0:
                        video_pic = video['thumbnail']['thumbnails'][-1]['url']
                    else:
                        video_pic = None
                    if len(video['title']['runs']) > 0:
                        video_title = video['title']['runs'][0]['text']
                        if re.search(r'(.+?)#', video_title):
                            video_title = re.search(r'(.+?)#', video_title).group(1)
                        elif re.search(r'(.+?)@', video_title):
                            video_title = re.search(r'(.+?)@', video_title).group(1)
                        else:
                            pass
                    else:
                        video_title = None
                    if 'lengthText' in video.keys():
                        if 'simpleText' in video['lengthText'].keys():
                            video_playtime = video['lengthText']['simpleText']
                        else:
                            video_playtime = None
                    else:
                        video_playtime = None
                    if 'viewCountText' in video.keys():
                        if 'simpleText' in video['viewCountText'].keys():
                            video_watch_num = video['viewCountText']['simpleText']
                        else:
                            video_watch_num = None
                    else:
                        video_watch_num = None
                    temp = {'keywords': search_keywords, 'video_id': video_id, 'video_pic': video_pic,
                            'video_title': video_title, 'video_playtime': video_playtime,
                            'video_watch_num': video_watch_num, 'video_h5_url': video_h5_url,
                            'video_datafrom': video_datafrom, 'video_update_time': video_update_time}
                    print(temp)
                    video_list.append(temp)
                return video_list
            except Exception as e:
                print(f'{url} 响应内容异常: {e}')
                return None

        else:
            raise Exception(f'youtube: 更新: {search_keywords} 失败!!! 请检查接口')

    def youtube_video_info(self, video_id):
        headers = {
            'cookie': 'HSID=AktAVU9oMHDHxfM0v; SSID=AkbYFPo2H60u9Jk9u; APISID=2kKwtuXoWzZ9bW0f/AM72Ibg2XB5kgHuz4; SAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; __Secure-1PAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; __Secure-3PAPISID=ZvROX7YeSiayAFgc/ARJx7YkjiqcLXZCef; VISITOR_INFO1_LIVE=RQ-WbwGHy58; VISITOR_PRIVACY_METADATA=CgJWThIEGgAgYQ%3D%3D; YSC=7xyHjCHoT8I; LOGIN_INFO=AFmmF2swRgIhAKKuCnL5P8p8NyfaSzyvdfeaGhE8H-umi4u8HGw-EeutAiEAz_F7bBnQG6kJYSzqufcw3K-FYEhUoqxf5h9wPKo3qzI:QUQ3MjNmekhuWERYd3plWlROVTFRRWg3NWVFdW92ZTJ5bjhXcTM5dnd1eUJTYmVUb0hYMEtTdkFBSXVSdDk3RFpKdmJZbnZ4ZDhMU1NxVHFwNmRQckRrbjl2cV9BUUx5czljdlBTMDFqeWxJZm9tUWFyWGI5bUJib05SU3NJdHdMZ3c2N1JFWHVDdXRHcWo4RkhNVFFaZU5adXdPeVU2dllB; SID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F2KFb1Ii7vZXYyDVpR01CwNAACgYKASASARISFQHGX2Mi0lqEYLLMZAP7CykZLrOWxRoVAUF8yKrWsZy7-0TRrzFbyRHvcUnj0076; __Secure-1PSID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F2l_hEcQuXh-tqU7iEp7KfKgACgYKAUESARISFQHGX2MiRikWldSLEJ8T7qun1Eik_hoVAUF8yKpsNQDv_1RXm03TRikTvXyC0076; __Secure-3PSID=g.a0004AjwixzVcrGYoC2LJ5a9u_X1ujjdr-Lpl2JMfhM75i1-_-F25jG5fEvviVn9RGU1jeTeIAACgYKAe8SARISFQHGX2Mi7C75OevAmnLfkur0QVyGfxoVAUF8yKrA2fjn5ze1dnBPvWLYC-W00076; __Secure-YNID=14.YT=k94-n5m-pRB3njixA3gVg53fIILT_uWOeCOGwf5_Kazh12AE3O8O51PGQjafZMp1t4YCGzJ_iORknKF61InUhSXLtlmbUvK5_GlM7WEIWhgCh4TDL-7_IZj6v9zcR2cxucc6_2TBYZnT5cO9BpvHXymKaW1BhqcgLE8lvG4jD1jaIj9B6O5LBZi7LV5XlZUOl7eP3VsnvJdi9KTEML8QtuhOF5yP6PehluFpZ2l8jkkvH2ldrybGfjLWAE9nN4vBuaCk9LKUB3ONS62HS5xLsAo0enHWtLUr9r2fZP0tsWQQ2wdYc0ZNuZapHPhKliSWsta_fgyrK_QlW4yeJW8glA; __Secure-ROLLOUT_TOKEN=CKCS7LLAro_WNRD_msWU9dWJAxj6ioSr392RAw%3D%3D; PREF=tz=America.Los_Angeles&f5=30000&f7=100&f3=8&f4=4000000; __Secure-1PSIDTS=sidts-CjQBflaCdVs3PtGQMVNNYFQxinpRO3gTLQ6fiuOpWXu7CgP99G_shH22dE45Ui9kUOjfW43yEAA; __Secure-3PSIDTS=sidts-CjQBflaCdVs3PtGQMVNNYFQxinpRO3gTLQ6fiuOpWXu7CgP99G_shH22dE45Ui9kUOjfW43yEAA; SIDCC=AKEyXzUa5D5ZoZU3k77Ksa-UwPGE53KZdbMhZpRf3Ym4EyppTh_g7u-wLklhVQMPGO7rCd0Z98Q; __Secure-1PSIDCC=AKEyXzW-KvQFkZwjXaEA-j0l_Xice9yXAVQY6MS-2OPut0GoLLAEKvYNNFfgGoBRoKZWOPajEKTT; __Secure-3PSIDCC=AKEyXzU2SjcHwiNnpYqg72bDy_E6nM1s6R61yzfMwWAojD0KQB0CuQLk-Qfv6FuKKoaZd5sWV8jJ',
            'referer': 'https://www.youtube.com/results?search_query=jk%E7%BE%8E%E5%A5%B3',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36'
        }
        url = f'https://www.youtube.com/watch?v={video_id}'
        print(f"获取视频详情: {url}")
        try:
            response = self.simple_get(url, headers=headers)
            if response is None:
                print(f"❌ 请求失败: {url}")
                return None, None
            # 改进的正则表达式，避免截断
            pattern = r'var ytInitialPlayerResponse\s*=\s*({.*?});\s*var'
            match = re.search(pattern, response, re.DOTALL)

            if not match:
                print(f"❌ 无法提取JSON数据: {video_id}")
                return None, None
            json_str = match.group(1)
            json_data = json.loads(json_str)
            # 1. 检查可播放状态
            playability_status = json_data.get('playabilityStatus', {})
            status = playability_status.get('status', 'UNKNOWN')
            if status != 'OK':
                reason = playability_status.get('reason', '未知原因')
                print(f"❌ 视频 {video_id} 不可播放: {status} - {reason}")

                # 记录详细的错误信息
                if 'errorScreen' in playability_status:
                    error_screen = playability_status.get('errorScreen', {})
                    if 'playerErrorMessageRenderer' in error_screen:
                        error_msg = error_screen['playerErrorMessageRenderer'].get('reason', {}).get('simpleText', '')
                        print(f"   错误详情: {error_msg}")

                return None, None
            # 2. 检查streamingData是否存在
            if 'streamingData' not in json_data:
                print(f"❌ 视频 {video_id} 缺少 streamingData 字段")
                print(f"   可用的字段: {list(json_data.keys())}")
                return None, None
            streaming_data = json_data['streamingData']
            # 3. 检查adaptiveFormats是否存在
            if 'adaptiveFormats' not in streaming_data:
                print(f"❌ 视频 {video_id} 缺少 adaptiveFormats")
                print(f"   streamingData 中的字段: {list(streaming_data.keys())}")
                return None, None

            adaptive_formats = streaming_data['adaptiveFormats']

            if not adaptive_formats:
                print(f"⚠️ 视频 {video_id} 的 adaptiveFormats 为空")
                return None, None
            # 提取视频和音频URL
            video_url = None
            audio_url = None
            video_formats = []
            audio_formats = []
            for fmt in adaptive_formats:
                # 判断是视频还是音频
                mime_type = fmt.get('mimeType', '').lower()
                if 'video/' in mime_type:
                    video_formats.append(fmt)
                elif 'audio/' in mime_type:
                    audio_formats.append(fmt)

            # 选择最高质量的视频（优先1080p）
            video_formats.sort(key=lambda x: (
                x.get('height', 0),
                x.get('width', 0),
                x.get('bitrate', 0)
            ), reverse=True)
            if video_formats:
                # 先找1080p
                for fmt in video_formats:
                    if fmt.get('height') >= 1080:
                        video_url = streaming_data['serverAbrStreamingUrl']
                        print(f"✅ 找到1080p视频: {fmt.get('height')}x{fmt.get('width')}")
                        break

                # 如果没有1080p，使用最高质量
                if not video_url and video_formats:
                    video_url = streaming_data['serverAbrStreamingUrl']
                    print(f"✅ 使用最高质量视频: {video_formats[0].get('height')}x{video_formats[0].get('width')}")
            # 选择最高质量的音频
            audio_formats.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
            if audio_formats:
                # todo 这里需要判断音频所在
                audio_url = streaming_data['serverAbrStreamingUrl']
            print(f"✅ 找到音频: {audio_formats[0].get('bitrate', 0)} bps")

            if video_url and audio_url:
                print(f"✅ 成功获取视频 {video_id} 的链接")
                return video_url, audio_url
            else:
                print(
                    f"⚠️ 未找到完整资源: 视频URL={'是' if video_url else '否'}, 音频URL={'是' if audio_url else '否'}")
            return video_url, audio_url
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            return None, None
        except Exception as e:
            print(f"❌ 处理视频 {video_id} 时出错: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def douyin_search_video(self, search_keywords, offset=0):
        keywords = search_keywords
        search_keywords = quote(search_keywords)
        print(search_keywords)
        try:
            # 读取抖音cookies
            with open('douyin_cookies.txt', 'r', encoding='utf-8') as file:
                cookies = file.read()
        except:
            raise Exception(f'请复制抖音cookies到 douyin_cookies.txt!!!')

        # 动态提取 verifyFp (s_v_web_id)
        import re
        fp_match = re.search(r's_v_web_id=([^; ]+)', cookies)
        fp_val = fp_match.group(1) if fp_match else 'verify_lw66uj9x_y69HTWBr_NOK0_4O0k_As0k_vZiOREH3U5SC'

        url = (
            f'https://www.douyin.com/aweme/v1/web/search/item/?'
            f'device_platform=webapp&aid=6383&channel=channel_pc_web&search_channel=aweme_video_web'
            f'&sort_type=0&publish_time=0&keyword={search_keywords}&search_source=switch_tab'
            f'&query_correct_type=1&is_filter_search=0&from_group_id=&offset={offset}&count=20'
            f'&pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true'
            f'&screen_width=1920&screen_height=1080&browser_language=zh-CN&browser_platform=Win32'
            f'&browser_name=Chrome&browser_version=145.0.0.0&browser_online=true&engine_name=Blink'
            f'&engine_version=145.0.0.0&os_name=Windows&os_version=10&cpu_core_num=16&device_memory=8'
            f'&platform=PC&downlink=10&effective_type=4g&round_trip_time=0&webid=7163531063863133732'
            f'&verifyFp={fp_val}&fp={fp_val}'
        )

        headers = {
            'authority': 'www.douyin.com',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            'referer': 'https://www.douyin.com/search/%E7%83%AD%E9%97%A8?publish_time=0&sort_type=0&source=switch_tab&type=video',
            'cookie': cookies
        }
        
        # 生成 a_bogus 签名
        query_params = url.split('?')[1]
        ab = douyin_a_bogus.get_ab(target_url=query_params, user_agent=headers['user-agent'], cookie_str=cookies)
        if ab:
            url += f"&a_bogus={ab}"
            print(f"生成 a_bogus 成功: {ab[:10]}...")
        else:
            print("生成 a_bogus 失败")

        res = self.simple_get(url=url, headers=headers)
        has_more = 0
        if res is not None:
            results = []
            target = json.loads(res)
            if target['status_code'] < 300:
                if 'has_more' in target.keys():
                    if target['has_more'] == 1:
                        has_more = 1
                if 'data' not in target.keys():
                    return results, False

                videos = target['data']
                for video in videos:
                    video = video['aweme_info']
                    temp = {'keywords': keywords, 'video_id': video['aweme_id'],
                            'video_pic': video['video']['cover']['url_list'][0], 'video_title': video['desc']}
                    if re.search(r'(.+?)#', video['desc']):
                        temp['video_title'] = re.search(r'(.+?)#', video['desc']).group(1)
                    elif re.search(r'(.+?)@', video['desc']):
                        temp['video_title'] = re.search(r'(.+?)@', video['desc']).group(1)
                    else:
                        pass
                    temp['video_h5_url'] = video['video']['play_addr']['url_list'][-1]
                    try:
                        # 提取抖音无水印视频
                        temp['video_h5_url'] = douyin_video.get_douyin_origin_video(aweme_id=video['aweme_id'])[
                            'originVideo']
                    except:
                        continue
                    temp['video_playtime'] = None
                    temp['video_watch_num'] = video['statistics']['digg_count']
                    temp['video_datafrom'] = '抖音'
                    temp['video_update_time'] = time.time()
                    temp['audio_url'] = None
                    temp['video_url'] = temp['video_h5_url']
                    print(temp)
                    results.append(temp)
                return results, has_more
            else:
                raise Exception(f'tiktok: 更新: {search_keywords} 失败!!! 接口返回异常')
        else:
            raise Exception(f'tiktok: 更新: {search_keywords} 失败!!! 请检查接口')

    def simple_post(self, url, data_json, headers):
        for i in range(5):
            try:
                if self.proxy:
                    res = requests.post(url=url, headers=headers, data=data_json, proxies=self.proxy)
                else:
                    res = requests.post(url=url, headers=headers, data=data_json)
                if res.status_code < 300:
                    print(f'请求 {url} 成功! {res.status_code}')
                    return res.text
                else:
                    print(f'请求 {url} 响应异常 状态码为: {res.status_code}, 开始重试, 重试次数:{i + 1}')
                    time.sleep(random.uniform(0.5, 1))
                    continue
            except:
                print(f'请求 {url} 发生错误, 开始重试, 重试次数:{i + 1}')
                time.sleep(random.uniform(0.5, 1))
                continue
        raise Exception(f'接口: {url} 异常, 终止任务!')

    def simple_get(self, url, headers, cookies=None):
        for i in range(5):
            try:
                if self.proxy:
                    if cookies:
                        res = requests.get(url=url, headers=headers, cookies=cookies)
                    else:
                        res = requests.post(url=url, headers=headers, proxies=self.proxy)
                else:
                    if cookies:
                        res = requests.get(url=url, headers=headers, cookies=cookies)
                    else:
                        res = requests.get(url=url, headers=headers)
                if res.status_code < 300:
                    print(f'请求 {url} 成功! {res.status_code}')
                    return res.text
                else:
                    print(f'请求 {url} 响应异常 状态码为: {res.status_code} {res.text}, 开始重试, 重试次数:{i + 1}')
                    time.sleep(random.uniform(0.5, 1))
                    continue
            except Exception as e:
                print(f'请求 {url} 发生错误, 开始重试, 重试次数:{i + 1} error: {e}')
                time.sleep(random.uniform(0.5, 1))
                continue
        raise Exception(f'接口: {url} 异常, 终止任务!')


if __name__ == '__main__':
    crawler = Crawlers()
    # crawler.update_tiktok_cookies()
    # for i in range(10):
    # crawler.youtube_search_video('funny video')
    #     time.sleep(1)

    # crawler.youtube_video_info('cZ81NTPz3Fs')
    # for i in range(3):
    # crawler.youtube_crawler('funny video')
    #     time.sleep(3)
    # crawler.tiktok_search_video('beautiful girls', offset=0)
    # crawler.tiktok_search_video_remote('beautiful girls')
    # crawler.tiktok_video_info('7462168953985486098')
    crawler.tiktok_crawler('love')
    # crawler.youtube_crawler('funny')

    # crawler.douyin_search_video('今日热点')
    # crawler.douyin_crawler('小姐姐短视频')
