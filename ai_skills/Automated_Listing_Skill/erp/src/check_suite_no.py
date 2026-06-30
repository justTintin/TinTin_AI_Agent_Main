# -*- coding: utf-8 -*-
"""
检查商家编码是否在ERP中存在，如果存在则自动递增
"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, 'config')
import json
import re
import shutil
from datetime import datetime, timedelta
import pandas as pd
from erp_client import WdtClient
from erp_config import (
    ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID,
    DATA_DIR
)

# 尝试导入Excel写入库
try:
    import xlwt
    HAS_XLWT = True
except ImportError:
    HAS_XLWT = False

try:
    import xlsxwriter
    HAS_XLSXWRITER = True
except ImportError:
    HAS_XLSXWRITER = False

def download_all_suites():
    """下载ERP全部组合装数据（2天内，分页）"""
    client = WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)
    
    # 时间范围：2天，结束时间为当前时间前5分钟（ERP最大支持范围）
    now = datetime.now()
    end_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    start_time = (now - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
    
    print(f"[下载ERP数据] 时间范围: {start_time} ~ {end_time}")
    
    all_suites = []
    page_no = 1
    page_size = 100
    
    while True:
        response = client.search_combinations(
            page_no=page_no,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
            suite_no=None  # 不传参数，查询全部
        )
        
        code = response.get('code')
        if code != 0:
            print(f"[错误] code={code}, message={response.get('message')}")
            break
        
        suites = response.get('suites_list', [])
        all_suites.extend(suites)
        
        total_count = response.get('total_count', 0)
        print(f"  第{page_no}页: 获取 {len(suites)} 条, 累计 {len(all_suites)}/{total_count}")
        
        if len(all_suites) >= total_count or len(suites) < page_size:
            break
        
        page_no += 1
    
    # 构建 suite_no -> suite 映射
    suite_map = {s.get('suite_no'): s for s in all_suites if s.get('suite_no')}
    
    print(f"[完成] 共下载 {len(all_suites)} 条组合装, {len(suite_map)} 个唯一商家编码")
    
    return all_suites, suite_map

def find_available_suite_no(original_no, suite_map):
    """
    检查商家编码是否存在，如存在则末尾+1继续查找
    返回第一个不存在的编码
    """
    # 提取前缀和数字部分
    match = re.match(r'^(.+?)(\d+)$', original_no)
    if not match:
        print(f"  [警告] 无法解析编码格式: {original_no}")
        return original_no
    
    prefix = match.group(1)
    num = int(match.group(2))
    current_no = original_no
    
    while current_no in suite_map:
        num += 1
        current_no = f"{prefix}{num:03d}"  # 保持3位数字格式
        print(f"    {original_no} 已存在，尝试 {current_no}...")
    
    if current_no != original_no:
        print(f"  [找到可用编码] {original_no} -> {current_no}")
    else:
        print(f"  [编码可用] {current_no}")
    
    return current_no

def process_sku_file(suite_map):
    """处理sku.xlsx文件，检查并更新商家编码"""
    sku_file = f"{DATA_DIR}\\sku.xlsx"
    print(f"\n[处理文件] {sku_file}")
    
    # 读取Excel
    df = pd.read_excel(sku_file)
    
    print(f"  共 {len(df)} 条记录")
    print(f"  列: {df.columns.tolist()}")
    
    # 检查'商家编码'列
    if '商家编码' not in df.columns:
        print("[错误] 文件中没有'商家编码'列")
        return
    
    changes = []
    
    for idx, row in df.iterrows():
        original_no = str(row['商家编码'])
        
        # 跳过空值
        if pd.isna(row['商家编码']) or original_no.strip() == '':
            continue
        
        # 检查并获取可用编码
        new_no = find_available_suite_no(original_no.strip(), suite_map)
        
        if new_no != original_no:
            changes.append({
                'index': idx,
                'original': original_no,
                'new': new_no,
                'name': row.get('组合装名称', '')
            })
            df.at[idx, '商家编码'] = new_no
    
    # 保存文件 - 改为xlsx格式保存
    xlsx_file = f"{DATA_DIR}\\sku_new.xlsx"
    df.to_excel(xlsx_file, index=False, engine='xlsxwriter')
    print(f"\n新文件已保存到: {xlsx_file}")
    
    print(f"\n[完成] 修改了 {len(changes)} 条记录")
    
    if changes:
        print("\n变更列表:")
        for c in changes:
            print(f"  {c['original']} -> {c['new']} ({c['name']})")
        
        # 同时保存变更记录
        changes_file = f"{DATA_DIR}\\changes.json"
        with open(changes_file, 'w', encoding='utf-8') as f:
            json.dump(changes, f, ensure_ascii=False, indent=2)
        print(f"\n变更记录已保存到: {changes_file}")
    
    print(f"\n新文件已保存到: {xlsx_file}")
    
    return changes

def main():
    print("=" * 60)
    print("  ERP商家编码检查与更新工具")
    print("=" * 60)
    
    # 1. 下载ERP全部数据
    all_suites, suite_map = download_all_suites()
    
    # 显示ERP中的dyc编码
    dyc_codes = [no for no in suite_map.keys() if no.startswith('dyc-')]
    if dyc_codes:
        dyc_codes.sort()
        print(f"\n[ERP中dyc编码] {len(dyc_codes)} 个")
        print(f"  {dyc_codes}")
    
    # 2. 处理sku文件
    changes = process_sku_file(suite_map)
    
    print("\n" + "=" * 60)
    print("  完成!")
    print("=" * 60)

if __name__ == '__main__':
    main()
