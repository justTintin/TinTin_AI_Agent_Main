"""
scripts/list_suites.py
列出ERP中所有组合装
"""

import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.erp_client import WdtClient
from src.erp_utils import filter_by_prefix, print_suites_table, print_statistics
from config.erp_config import ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID


def main():
    client = WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)

    print("=" * 60)
    print("  查询ERP全部组合装")
    print("=" * 60)

    # 查询全部（不限制时间）
    response = client.search_combinations(page_no=1, page_size=200)
    suites = response.get('suites', [])

    print(f"\n[结果] 共 {len(suites)} 条组合装")

    if suites:
        print_suites_table(suites, "ERP组合装列表")
        print_statistics(suites)

        # 按类型分别显示
        dyc_suites = filter_by_prefix(suites, 'dyc-')
        pt_suites = filter_by_prefix(suites, 'pt')

        if dyc_suites:
            print_suites_table(dyc_suites, "dyc系列组合装")
        if pt_suites:
            print_suites_table(pt_suites[:20], "pt系列组合装 (前20个)")


if __name__ == "__main__":
    main()
