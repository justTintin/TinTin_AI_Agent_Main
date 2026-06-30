import json
import random
import time
import os
import traceback

import requests
from flask import Flask, render_template, request, url_for, redirect
from pymongo import MongoClient
import sys
from core.login import Login
import re
import configparser
import math
import pymysql
from flask_limiter import Limiter


app = Flask(__name__)
# 限流
limiter = Limiter(app, default_limits=["200 per day", "50 per hour"])
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
api_config = config['Web_API']
path_config = config['Path']
mysql_config = config['MySQL']
db_type = config.get('Database', 'Type', fallback='mongodb').lower()

def get_mysql_conn():
    return pymysql.connect(
        host=mysql_config['Host'],
        port=int(mysql_config['Port']),
        user=mysql_config['User'],
        password=mysql_config['Password'],
        database=mysql_config['Database'],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

print(f"System Args: {sys.argv}")
print(f"Active Database Type: {db_type}")

# 初始化 MongoDB (即便 Type=mysql 也可以初始化，备查或兼容)
try:
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        client = MongoClient(host=path_config['Mongo_host_local'], port=int(path_config['Mongo_port']), username=path_config['Mongo_username'], password=path_config['Mongo_password'], authSource='admin', authMechanism='SCRAM-SHA-256')
    elif path_config.get('Mongo_username', None) and path_config.get('Mongo_password', None):
        client = MongoClient(host=path_config['Mongo_host_server'], port=int(path_config['Mongo_port']), username=path_config['Mongo_username'], password=path_config['Mongo_password'], authSource='admin', authMechanism='SCRAM-SHA-256')
    else:
        client = MongoClient(host=path_config['Mongo_host_server'], port=int(path_config['Mongo_port']))
    collection = client['handling_vedio']['vedios']
except Exception as e:
    print(f"MongoDB 连接初始化失败: {e}")
    collection = None

video_path = path_config['Video_path']
error_path = path_config['Error_path']
if os.path.exists(error_path):
    pass
else:
    print(f'error_path 目录不存在, 开始创建...')
    os.mkdir(error_path)

LOGIN = None
PREDATA = None
USEFUL_NUM = None


@app.route('/')
def root():
    return redirect(url_for('video_list'))


@app.route('/video_list')
def video_list():
    global USEFUL_NUM
    kill_orphan_chrome()
    info = {'status': 0, 'video_list': [], 'has_more': False, 'message': None, 'page': 1, 'page_index': []}
    page_size = 50
    temp = request.args.get('page', 1)
    page = int(temp) if re.search(r'\d', str(temp)) else 1
    info['page'] = page
    offset = (page - 1) * page_size

    if db_type == 'mongodb' and collection is not None:
        useful_num = int(collection.count_documents({'video_update_time': {'$gt': time.time() - 5 * 60 * 60}}))
        if useful_num > 0:
            page_num = int(math.ceil(useful_num/page_size))
            info['page_index'] = [i for i in range(1, page_num+1)]
            info['has_more'] = (offset + page_size) < useful_num
            videos = collection.find({'video_update_time': {'$gt': time.time() - 5 * 60 * 60}}).limit(page_size).skip(offset)
            for video in videos:
                if '_id' in video: del video['_id']
                # 统一字段处理
                video['video_title'] = video.get('video_title', '').strip().replace('\n', '')[:40]
                video['has_handling'] = '已搬运' if video.get('has_handling') is True else '未搬运'
                info['video_list'].append(video)
            info['message'] = '获取视频列表成功 (MongoDB)!'
        else:
            info['status'] = -1
            info['message'] = '暂无可用的 MongoDB 视频'
            
    elif db_type == 'mysql':
        try:
            conn = get_mysql_conn()
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as total FROM videos")
                useful_num = cursor.fetchone()['total']
                if useful_num > 0:
                    page_num = int(math.ceil(useful_num / page_size))
                    info['page_index'] = [i for i in range(1, page_num + 1)]
                    cursor.execute("SELECT * FROM videos ORDER BY video_update_time DESC LIMIT %s OFFSET %s", (page_size, offset))
                    videos = cursor.fetchall()
                    for video in videos:
                        video['video_title'] = video.get('video_title', '').strip().replace('\n', '')[:40]
                        video['has_handling'] = '已搬运' if video.get('has_handling') is True else '未搬运'
                        info['video_list'].append(video)
                    info['has_more'] = (offset + page_size) < useful_num
                    info['message'] = '获取视频列表成功 (MySQL)!'
                else:
                    info['status'] = -1
                    info['message'] = '暂无可用的 MySQL 视频'
            conn.close()
        except Exception as e:
            info['status'] = -500
            info['message'] = f'MySQL 数据库连接失败: {str(e)}'
    
    return render_template('video_list.html', data=info)


@app.route('/advanced_list')
def advanced_list():
    page = request.args.get('page', 1, type=int)
    page_size = 50
    offset = (page - 1) * page_size
    
    info = {'status': 0, 'video_list': [], 'has_more': False, 'message': '获取高级视频列表成功!', 'page': page, 'page_index': []}
    
    try:
        conn = get_mysql_conn()
        with conn.cursor() as cursor:
            # 获取总数
            cursor.execute("SELECT COUNT(*) as total FROM videos WHERE video_datafrom = '抖音_高级'")
            total = cursor.fetchone()['total']
            
            if total > 0:
                page_num = int(math.ceil(total / page_size))
                info['page_index'] = [i for i in range(1, page_num + 1)]
                
                # 获取列表
                sql = """
                SELECT * FROM videos 
                WHERE video_datafrom = '抖音_高级' 
                ORDER BY publish_time DESC 
                LIMIT %s OFFSET %s
                """
                cursor.execute(sql, (page_size, offset))
                videos = cursor.fetchall()
                
                for video in videos:
                    # 转换格式以匹配前端模板
                    video['has_handling'] = '未搬运' # MySQL 暂未同步搬运状态
                    video['video_title'] = video['video_title'].strip().replace('\n', '')
                    if len(video['video_title']) > 40:
                        video['video_title'] = video['video_title'][:40]
                    info['video_list'].append(video)
                
                info['has_more'] = (offset + page_size) < total
            else:
                info['status'] = -1
                info['message'] = '暂无高级筛选视频'
        conn.close()
    except Exception as e:
        info['status'] = -500
        info['message'] = f'数据库连接失败: {str(e)}'
        traceback.print_exc()

    return render_template('advanced_list.html', data=info)


@app.route('/video', methods=['GET'])
def index():
    video_id = request.args.get('video_id')
    if video_id:
        return_data = None
        # 优先从当前启用的数据库查找
        if db_type == 'mysql':
            try:
                conn = get_mysql_conn()
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM videos WHERE video_id = %s", (video_id,))
                    return_data = cursor.fetchone()
                conn.close()
            except: pass
        
        if not return_data and collection is not None:
            return_data = collection.find_one({'video_id': video_id})
            if return_data and '_id' in return_data: del return_data['_id']

        if return_data:
            video_url = return_data.get('video_url')
            print('video_url: ', video_url)
            return render_template('home.html', data=json.dumps(return_data, default=str), origin_video_url=video_url)
        else:
            return 'no data '
    else:
        return 'video_id is wrong !!!'


@app.route('/jump', methods=['POST'])
def jump():
    video_id = request.form.get('video_id')
    temp = collection.find_one({'video_id': video_id})
    if temp:
        del temp['_id']
        return render_template('home.html', data=json.dumps(temp))
    else:
        return render_template('home.html', data=json.dumps({}))


@app.route('/pre_handling', methods=['POST'])
def pre_handling_video():
    print('pre_args: ', request.form)
    global PREDATA
    PREDATA = dict(request.form)
    return 'True'


@app.route('/handling', methods=['GET', 'POST'])
def handling_video():
    print('url: ', request.url)
    print('handling form: ', request.form)
    data = PREDATA
    if data:
        video_datafrom = data['video_datafrom']
        login = Login()
        global LOGIN
        LOGIN = login
        if video_datafrom == "抖音" or video_datafrom == 'douyin':
            # login.tiktok_login()
            return render_template('handling.html', data=json.dumps(data), dict=data, video_id=data['video_id'], login_pic_url='None')
        else:
            login_pic_url = login.douyin_login()
            if login_pic_url:
                pass
            else:
                login_pic_url = ''

            return render_template('handling.html', data=json.dumps(data), dict=data, video_id=data['video_id'], login_pic_url=login_pic_url)
    else:
        return redirect(url_for('video_list'))


@app.route('/download_video', methods=['POST'])
def download_video():
    path = path_config['video_path']
    video_url = request.form.get('video_url')
    video_id = request.form.get('video_id')
    video_name = video_id + '.mp4'
    file_path = path + video_name
    if os.path.exists(file_path):
        print(f'下载: {video_id} 无需下载')
        return video_name
    else:
        # video_url = video_url
        video_url = video_url.replace('https://', 'http://')
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36'}
        for i in range(3):
            try:
                if 'tiktok' in video_url or 'youtube' in video_url or 'google' in video_url:
                    resp = requests.get(url=video_url, headers=headers)
                else:
                    resp = requests.get(url=video_url, headers=headers)
                if resp.status_code < 300:
                    with open(file_path, 'wb')as f:
                        f.write(resp.content)
                    print(f'下载: {video_id} 成功! ')
                    return video_name
                else:
                    continue
            except:
                print(f'下载: {video_id} 失败: {traceback.format_exc()}')
        return '下载失败!'


@app.route('/refresh_login_pic', methods=['POST'])
def refresh_login_pic():
    kill_orphan_chrome()
    douyin_login = Login()
    global LOGIN
    LOGIN = douyin_login
    login_pic_url = douyin_login.douyin_login()
    if login_pic_url:
        pass
    else:
        login_pic_url = '刷新失败'
    print(f'刷新登录二维码: {login_pic_url}')
    return login_pic_url


@app.route('/publish', methods=['POST'])
def publish():
    return '演示服务器屏蔽发布功能! 请下载项目自行测试'
    global LOGIN
    path = path_config['video_path']
    video_id = request.form.get('video_id')
    video_datafrom = request.form.get('video_datafrom')
    account = request.form.get('account')
    password = request.form.get('password')
    title = request.form.get('title', ' ')
    publish_platform = request.form.get('publish_platform')
    video_name = video_id + '.mp4'
    print(f'title: {title} account: {account} password: {password} publish: {publish_platform}')
    video_url = request.form.get('video_url')
    video_url = video_url.replace('https://', 'http://')
    file_path = path+video_name
    print(f'video_path: {video_path} video_url: {video_url}')
    for i in range(3):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36'}
        try:
            print(f'第{i+1}次下载视频')
            if 'tiktok' in video_url or 'youtube' in video_url or 'google' in video_url:
                resp = requests.get(url=video_url, headers=headers, stream=True)
            else:
                resp = requests.get(url=video_url, headers=headers, stream=True)
            if resp.status_code < 300:
                with open(file_path, 'wb')as f:
                    f.write(resp.content)
                print(f'下载视频完成')
                break
            else:
                print(f'下载视频异常, 开始重试...')
                continue
        except Exception as e:
            print(f'下载视频异常: {e}')
            continue
    if os.path.exists(file_path):
        print(f'开始发布视频')
        try:
            if publish_platform == 'tiktok':
                if account is not None and password is not None and account != '' and password != '':
                    login = Login()
                    LOGIN = login
                    result = login.tiktok_login(account=account, password=password)
                else:
                    result = '账号或密码为空'
            elif publish_platform == 'youtube':
                if account is not None and password is not None and account != '' and password != '':
                    login = Login()
                    LOGIN = login
                    result = login.youtube_login(account=account, password=password)
                else:
                    result = '账号或密码为空'
            else:
                result = LOGIN.douyin_upload(video_path=file_path, title=title)
        except Exception as e:
            print(f'发布视频, 页面异常: {e}')
            result = '页面异常'
            if LOGIN:
                if LOGIN.broswer:
                    LOGIN.broswer.save_screenshot(error_path+'error'+str(int(time.time()))+'.png')
                    LOGIN.broswer.quit()
        if result is True:
            # 同时尝试更新两个数据库，取决于哪个存在该 ID
            if collection is not None:
                collection.update_one({'video_id': video_id}, {'$set': {'has_handling': True}})
            try:
                conn = get_mysql_conn()
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE videos SET has_handling = 1 WHERE video_id = %s", (video_id,))
                conn.commit()
                conn.close()
            except:
                pass
            message = 'success'
        else:
            message = result
    else:
        message = '网络环境异常, 请点击下载视频后重试!'
    # else:
    #     message = '找不到可用的chrome, 请返回刷新!'
    if LOGIN:
        if LOGIN.broswer:
            LOGIN.broswer.quit()
    return message


@app.route('/hcaptcha', methods=['POST'])
def hcaptcha():
    code = request.form.get('code')
    video_id = request.form.get('video_id')
    if re.search(r'\D', code):
        print(f'请输入正确的验证码: {code}')
        return 'error code'
    else:
        if LOGIN:
            result = LOGIN.hcaptcha(code=code)
            if result is True:
                collection.update_one({'video_id': video_id}, {'$set': {'has_handling': True}})
                message = 'success'
            else:
                message = '验证失败'
        else:
            message = '验证, 无可用的chrome'
        return message


def kill_orphan_chrome():
    for i in range(2):
        if len(sys.argv) >1 and sys.argv[1] == 'test':
            break
        else:
            try:
                if os.popen('ps -f --ppid 1 | grep chromedriver').read():
                    os.system("ps -f --ppid 1 | grep chromedriver | awk '{print $2}' | xargs kill -9")
            except:
                pass
            try:
                if os.popen('ps -f --ppid 1 | grep chrome').read():
                    os.system("ps -f --ppid 1 | grep chrome | awk '{print $2}' | xargs kill -9")
            except:
                pass
        time.sleep(random.uniform(0.3, 0.5))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        app.run(host=api_config['Host'], port=int(api_config['Port']), debug=True)
    else:
        app.run(host=api_config['Host'], port=int(api_config['Port']), threaded=True)

