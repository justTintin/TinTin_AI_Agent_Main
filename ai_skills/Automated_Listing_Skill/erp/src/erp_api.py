"""
erp_api.py
旺店通ERP HTTP API服务
启动后可通过HTTP请求访问ERP数据
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.erp_client import WdtClient
from src.erp_utils import parse_suites, filter_by_prefix
from config.erp_config import ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID

app = Flask(__name__)

# 创建ERP客户端
client = WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)


@app.route('/api/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'service': 'erp-api'})


@app.route('/api/suites', methods=['GET'])
def list_suites():
    """
    列出组合装列表

    Query参数:
        - prefix: 按前缀过滤 (如 dyc-, pt-)
        - page_size: 每页条数 (默认100)
    """
    try:
        prefix = request.args.get('prefix')
        page_size = int(request.args.get('page_size', 100))

        # 时间范围：最近2天
        now = datetime.now()
        end_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        start_time = (now - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")

        response = client.search_combinations(
            page_no=1,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time
        )

        suites = parse_suites(response)

        # 过滤
        if prefix:
            suites = filter_by_prefix(suites, prefix)

        return jsonify({
            'code': 0,
            'message': 'ok',
            'count': len(suites),
            'data': suites
        })

    except Exception as e:
        return jsonify({'code': -1, 'message': str(e)})


@app.route('/api/suites/query', methods=['GET'])
def query_suite():
    """
    按商家编码查询组合装

    Query参数:
        - suite_no: 商家编码 (可选，如 dyc-080)
    """
    try:
        suite_no = request.args.get('suite_no')

        # 时间范围：29天，结束时间为当前时间前3分钟
        now = datetime.now()
        end_time = (now - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
        start_time = (now - timedelta(days=29)).strftime("%Y-%m-%d 00:00:00")

        # 查询全部（ERP不支持suite_no过滤，需要本地过滤）
        response = client.search_combinations(
            page_no=1,
            page_size=100,
            start_time=start_time,
            end_time=end_time
        )

        # 如果指定了suite_no，在本地过滤
        if suite_no:
            suites = response.get('suites_list', [])
            filtered = [s for s in suites if s.get('suite_no') == suite_no]
            response['suites_list'] = filtered
            response['total_count'] = len(filtered)

        return jsonify(response)

        suites = parse_suites(response)

        # 精确匹配
        target = None
        for s in suites:
            if s.get('suite_no') == suite_no:
                target = s
                break

        return jsonify({
            'code': 0,
            'message': 'ok',
            'found': target is not None,
            'data': target
        })

    except Exception as e:
        return jsonify({'code': -1, 'message': str(e)})


@app.route('/api/suites/stats', methods=['GET'])
def stats():
    """获取统计信息"""
    try:
        response = client.search_combinations(
            page_no=1,
            page_size=100,
            start_time=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00"),
            end_time=(datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        )

        suites = parse_suites(response)

        # 统计
        prefixes = {}
        for s in suites:
            suite_no = s.get('suite_no', '')
            prefix = suite_no.split('-')[0] if '-' in suite_no else 'other'
            prefixes[prefix] = prefixes.get(prefix, 0) + 1

        return jsonify({
            'code': 0,
            'message': 'ok',
            'total': len(suites),
            'by_prefix': prefixes
        })

    except Exception as e:
        return jsonify({'code': -1, 'message': str(e)})


if __name__ == '__main__':
    print("=" * 60)
    print("  旺店通ERP API服务")
    print("=" * 60)
    print()
    print("  地址: http://127.0.0.1:5000")
    print()
    print("  接口:")
    print("    GET /api/health          - 健康检查")
    print("    GET /api/suites           - 列出组合装")
    print("    GET /api/suites/query     - 按编码查询")
    print("    GET /api/suites/stats     - 统计信息")
    print()
    print("  示例:")
    print("    http://127.0.0.1:5000/api/suites?prefix=dyc")
    print("    http://127.0.0.1:5000/api/suites/query?no=dyc-080")
    print()
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False)
