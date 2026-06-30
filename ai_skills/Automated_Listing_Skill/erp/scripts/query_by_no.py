"""
scripts/query_by_no.py
按商家编码查询组合装
"""

import sys
import argparse
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.erp_client import WdtClient
from src.erp_utils import filter_by_prefix
from config.erp_config import ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID


def main():
    parser = argparse.ArgumentParser(description='按商家编码查询组合装')
    parser.add_argument('--no', '-n', required=True, help='商家编码，如 dyc-080')
    args = parser.parse_args()

    client = WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)

    print("=" * 60)
    print(f"  查询商家编码: {args.no}")
    print("=" * 60)

    # 查询全部
    response = client.search_combinations(page_no=1, page_size=200)
    suites = response.get('suites', [])

    # 本地过滤
    target = None
    for s in suites:
        if s.get('suite_no') == args.no:
            target = s
            break

    if target:
        print(f"\n[找到]")
        print(f"  商家编码: {target.get('suite_no')}")
        print(f"  组合装名称: {target.get('suite_name')}")
        print(f"\n  完整数据:")
        for k, v in target.items():
            print(f"    {k}: {v}")
    else:
        print(f"\n[未找到] ERP中没有 {args.no} 这个组合装")

        # 列出相近的
        prefix = args.no.split('-')[0] + '-'
        similar = filter_by_prefix(suites, prefix)
        if similar:
            print(f"\n[相近编号 - {prefix}* 系列]")
            for s in similar:
                print(f"  - {s.get('suite_no')}: {s.get('suite_name')}")
        else:
            print(f"\n[提示] ERP中没有任何 {prefix}* 系列组合装")


if __name__ == "__main__":
    main()
