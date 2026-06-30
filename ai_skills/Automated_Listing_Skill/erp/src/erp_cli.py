"""
erp_cli.py
旺店通ERP CLI工具
命令行查询ERP组合装数据
"""

import sys
import shutil
import os
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 添加父目录到路径（用于导入src模块）
ERP_DIR = Path(__file__).parent.parent  # erp/src -> erp
sys.path.insert(0, str(ERP_DIR))

# 添加config到路径（用于导入配置）
SKILL_ROOT = ERP_DIR.parent  # erp -> skill_root
sys.path.insert(0, str(SKILL_ROOT / 'config'))

from src.erp_client import WdtClient
from src.erp_utils import parse_suites, filter_by_prefix, print_suites_table, print_statistics, get_next_dyc_no
from erp_config import ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID
from skill_config import DATA_DIR, ERP_CACHE_DIR


def create_client() -> WdtClient:
    """创建ERP客户端"""
    return WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)


def cmd_list(args):
    """列出所有组合装（支持分页查询）"""
    client = create_client()

    print("=" * 60)
    print("  查询ERP全部组合装（分页）")
    print("=" * 60)

    # 计算时间范围
    days = args.days
    now = datetime.now()
    end_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    start_time = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[INFO] 查询天数: {days} 天")
    print(f"[INFO] 时间范围: {start_time} ~ {end_time}")

    # 分页获取全部数据
    all_suites = []
    page_no = 1
    page_size = args.page_size if args.page_size else 100

    while True:
        print(f"\n[请求] 第 {page_no} 页，每页 {page_size} 条...")
        
        response = client.search_combinations(
            page_no=page_no,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time
        )

        code = response.get('code')
        if code != 0:
            print(f"[ERROR] API错误: {response.get('message')}")
            break

        # 解析数据
        suites = parse_suites(response)
        
        if not suites:
            print(f"[完成] 第 {page_no} 页无数据，停止请求")
            break

        all_suites.extend(suites)
        print(f"[获取] 第 {page_no} 页获取 {len(suites)} 条，累计 {len(all_suites)} 条")

        # 如果返回数据少于page_size，说明已经是最后一页
        if len(suites) < page_size:
            print(f"[完成] 数据不足一页，已获取全部数据")
            break

        page_no += 1

    print(f"\n[结果] 共获取 {len(all_suites)} 条组合装")

    if args.prefix:
        filtered_suites = filter_by_prefix(all_suites, args.prefix)
        print(f"[过滤] 只显示 {args.prefix}* 系列，共 {len(filtered_suites)} 条")
        display_suites = filtered_suites
    else:
        display_suites = all_suites

    if display_suites:
        print_suites_table(display_suites, f"{args.prefix or ''}组合装列表".strip())
        print_statistics(display_suites)

    # 如果之前有旧文件，直接重命名为备份（不考虑 total_count，只要有就备份）
    json_file = Path(ERP_CACHE_DIR) / 'erp_suites_data.json'
    if json_file.exists():
        backup_file = Path(ERP_CACHE_DIR) / 'erp_suites_data_backup.json'
        try:
            shutil.copy2(json_file, backup_file)
            print(f"\n[备份] 旧数据已备份到 {backup_file}")
        except Exception as e:
            print(f"[WARN] 备份旧数据失败: {e}")

    # 只有获取到数据才保存
    if len(all_suites) > 0:
        # 保存到配置的数据目录
        os.makedirs(ERP_CACHE_DIR, exist_ok=True)

        # 保存完整JSON
        save_data = {
            "query_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "time_range": {
                "start": start_time,
                "end": end_time
            },
            "days": days,
            "total_count": len(all_suites),
            "page_count": page_no,
            "page_size": page_size,
            "suites": all_suites
        }
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        # 保存列表
        list_file = Path(ERP_CACHE_DIR) / 'erp_suites_list.txt'
        with open(list_file, 'w', encoding='utf-8') as f:
            f.write(f"ERP组合装列表（{days}天数据）\n")
            f.write("=" * 50 + "\n")
            f.write(f"查询时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"时间范围: {start_time} ~ {end_time}\n")
            f.write(f"总条数: {len(all_suites)}\n")
            f.write(f"分页数: {page_no}\n")
            f.write("=" * 50 + "\n\n")
            for i, s in enumerate(all_suites, 1):
                f.write(f"{i:4d}. {s.get('suite_no', ''):<15} {s.get('suite_name', '')}\n")

        print(f"\n[已保存]")
        print(f"  JSON: {json_file}")
        print(f"  列表: {list_file}")
    else:
        print("\n[跳过] 未获取到数据，不覆盖已有文件")


def cmd_query(args):
    """按商家编码查询"""
    client = create_client()

    print("=" * 60)
    print(f"  按商家编码查询: {args.no}")
    print("=" * 60)

    # 计算时间范围（30天）
    now = datetime.now()
    end_time = now.strftime("%Y-%m-%d %H:%M:%S")
    start_time = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")

    print(f"\n[INFO] 时间范围: {start_time} ~ {end_time}")

    # 直接传入suite_no进行查询
    response = client.search_combinations(
        page_no=1,
        page_size=100,
        start_time=start_time,
        end_time=end_time,
        suite_no=args.no
    )

    code = response.get('code')
    message = response.get('message', 'ok')
    suites = parse_suites(response)

    print(f"\n[结果] code={code}, message={message}")
    print(f"[数据] 共 {len(suites)} 条组合装")

    # 本地过滤（双重保险）
    target = None
    for s in suites:
        if s.get('suite_no') == args.no:
            target = s
            break

    if target:
        print(f"\n[找到]")
        print(f"  商家编码: {target.get('suite_no')}")
        print(f"  组合装名称: {target.get('suite_name')}")
        print(f"  其他字段:")
        for k, v in target.items():
            if k not in ('suite_no', 'suite_name'):
                print(f"    {k}: {v}")
    else:
        print(f"\n[未找到] ERP中没有 {args.no} 这个组合装")

        # 列出相近的
        prefix = args.no.split('-')[0] + '-'
        similar = filter_by_prefix(suites, prefix)
        if similar:
            print(f"\n[相近编号]")
            for s in similar[:10]:
                print(f"  - {s.get('suite_no')}: {s.get('suite_name')}")


def cmd_stats(args):
    """显示统计信息"""
    client = create_client()

    print("=" * 60)
    print("  ERP组合装统计")
    print("=" * 60)

    response = client.search_combinations(page_size=100)
    suites = parse_suites(response)

    print(f"\n[基本信息]")
    print(f"  组合装总数: {len(suites)}")

    if suites:
        print_statistics(suites)


def main():
    parser = argparse.ArgumentParser(description='旺店通ERP CLI工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # list 命令
    list_parser = subparsers.add_parser('list', help='列出所有组合装（分页请求）')
    list_parser.add_argument('--prefix', '-p', help='按前缀过滤，如 dyc-, pt')
    list_parser.add_argument('--save', '-s', action='store_true', help='保存到文件')
    list_parser.add_argument('--page-size', type=int, default=100, help='每页条数（最大100）')
    list_parser.add_argument('--days', '-d', type=int, default=29, help='查询天数（默认29天）')
    list_parser.set_defaults(func=cmd_list)

    # query 命令
    query_parser = subparsers.add_parser('query', help='按商家编码查询')
    query_parser.add_argument('--no', '-n', required=True, help='商家编码，如 dyc-080')
    query_parser.set_defaults(func=cmd_query)

    # stats 命令
    stats_parser = subparsers.add_parser('stats', help='显示统计信息')
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
