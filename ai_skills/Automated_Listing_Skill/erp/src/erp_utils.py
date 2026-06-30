"""
erp_utils.py
旺店通ERP 工具函数
"""

from typing import Dict, Any, List, Optional


def parse_suites(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    解析组合装查询响应

    Args:
        response: API响应字典

    Returns:
        组合装列表
    """
    if response.get('code') != 0:
        return []

    return response.get('suites', [])


def find_max_dyc_no(suites: List[Dict[str, Any]], field: str = 'suite_no') -> Optional[str]:
    """
    查找最大的dyc-编号

    Args:
        suites: 组合装列表
        field: 字段名，默认suite_no

    Returns:
        最大的dyc编号，如 "dyc-100"，如果没有则返回None
    """
    max_no = 0
    for item in suites:
        goods_no = item.get(field, '')
        if goods_no and goods_no.startswith('dyc-'):
            try:
                num = int(goods_no.split('-')[1])
                max_no = max(max_no, num)
            except (ValueError, IndexError):
                pass
    return f"dyc-{max_no:03d}" if max_no > 0 else None


def get_next_dyc_no(suites: List[Dict[str, Any]], field: str = 'suite_no') -> str:
    """
    获取下一个可用的dyc编号

    Args:
        suites: 组合装列表
        field: 字段名

    Returns:
        下一个可用的编号，如 "dyc-101"
    """
    max_no = find_max_dyc_no(suites, field)
    if max_no:
        num = int(max_no.split('-')[1])
        return f"dyc-{num + 1:03d}"
    return "dyc-001"


def filter_by_prefix(suites: List[Dict[str, Any]], prefix: str, field: str = 'suite_no') -> List[Dict[str, Any]]:
    """
    按前缀过滤组合装

    Args:
        suites: 组合装列表
        prefix: 前缀，如 "dyc-" 或 "pt"
        field: 字段名

    Returns:
        过滤后的列表
    """
    return [s for s in suites if s.get(field, '').startswith(prefix)]


def print_suites_table(suites: List[Dict[str, Any]], title: str = "组合装列表", max_rows: int = 50):
    """
    打印组合装表格

    Args:
        suites: 组合装列表
        title: 表格标题
        max_rows: 最大显示行数
    """
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print('=' * 80)

    if not suites:
        print("  (无数据)")
        return

    print(f"{'序号':<5} {'商家编码':<15} {'组合装名称':<40}")
    print('-' * 80)

    for i, item in enumerate(suites[:max_rows], 1):
        no = item.get('suite_no', '')[:15]
        name = item.get('suite_name', '')[:40]
        print(f"{i:<5} {no:<15} {name:<40}")

    if len(suites) > max_rows:
        print(f"... (共 {len(suites)} 条)")

    print('=' * 80)


def print_statistics(suites: List[Dict[str, Any]]):
    """
    打印组合装统计信息

    Args:
        suites: 组合装列表
    """
    total = len(suites)

    # 分类统计
    dyc_list = [s for s in suites if s.get('suite_no', '').startswith('dyc-')]
    pt_list = [s for s in suites if s.get('suite_no', '').startswith('pt')]
    other_list = [s for s in suites if not s.get('suite_no', '').startswith('dyc-') and not s.get('suite_no', '').startswith('pt')]

    print(f"\n[统计信息]")
    print(f"  总数: {total}")
    print(f"  dyc系列: {len(dyc_list)}")
    print(f"  pt系列: {len(pt_list)}")
    print(f"  其他: {len(other_list)}")

    # 最大编号建议
    max_dyc = find_max_dyc_no(suites)
    if max_dyc:
        print(f"  最大dyc编号: {max_dyc}")
        print(f"  下一个可用: {get_next_dyc_no(suites)}")
    else:
        print(f"  下一个可用: dyc-001")
