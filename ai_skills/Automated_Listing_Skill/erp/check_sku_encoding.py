"""
check_sku_encoding.py
检查sku.xlsx中的商家编码是否在ERP数据中存在
"""

import json
import pandas as pd
from pathlib import Path

# 路径配置
SKU_FILE = r"Y:\自动上架workbuddy\上架数据\2026040914-上架数据\sku.xlsx"
ERP_DATA_FILE = r"C:\Users\tintin\WorkBuddy\Claw\erp_suites_data.json"
ERP_BACKUP_FILE = r"C:\Users\tintin\WorkBuddy\Claw\erp\output\suites_full.json"
OUTPUT_DIR = r"C:\Users\tintin\WorkBuddy\Claw"

def main():
    print("=" * 60)
    print("  检查SKU商家编码是否在ERP中存在")
    print("=" * 60)

    # 1. 读取ERP数据（优先主文件，否则用备份）
    print("\n[1] 读取ERP数据...")
    
    # 尝试读取主文件
    erp_data = None
    try:
        with open(ERP_DATA_FILE, 'r', encoding='utf-8') as f:
            erp_data = json.load(f)
        if erp_data.get('total_count', 0) > 0:
            print(f"    使用主数据文件: {ERP_DATA_FILE}")
    except:
        pass
    
    # 如果主文件为空，使用备份
    if erp_data is None or erp_data.get('total_count', 0) == 0:
        try:
            with open(ERP_BACKUP_FILE, 'r', encoding='utf-8') as f:
                erp_data = json.load(f)
            print(f"    使用备份数据文件: {ERP_BACKUP_FILE}")
        except:
            print(f"    错误: 无法读取ERP数据文件")
            return
    
    # 提取ERP中的所有商家编码
    erp_suite_nos = set()
    for suite in erp_data.get('suites', []):
        suite_no = suite.get('suite_no', '').strip()
        if suite_no:
            erp_suite_nos.add(suite_no)
    
    total = erp_data.get('total_count', 0) or len(erp_data.get('suites', []))
    print(f"    ERP数据共 {total} 条")
    print(f"    商家编码总数: {len(erp_suite_nos)}")

    # 2. 读取sku.xlsx
    print("\n[2] 读取sku.xlsx...")
    sku_df = pd.read_excel(SKU_FILE, engine='openpyxl')
    print(f"    共 {len(sku_df)} 行")
    print(f"    列名: {list(sku_df.columns)}")

    # 查找商家编码列
    suite_no_col = None
    for col in sku_df.columns:
        col_lower = str(col).lower()
        if '商家编码' in str(col) or 'suite_no' in col_lower or '编号' in str(col):
            suite_no_col = col
            break
    
    if suite_no_col is None:
        # 尝试使用第1列或第2列
        if len(sku_df.columns) >= 2:
            suite_no_col = sku_df.columns[1]
        else:
            suite_no_col = sku_df.columns[0]
    
    print(f"    商家编码列: {suite_no_col}")

    # 提取sku中的商家编码
    sku_codes = []
    for code in sku_df[suite_no_col].dropna():
        code_str = str(code).strip()
        if code_str and code_str != 'nan':
            sku_codes.append(code_str)

    print(f"    SKU商家编码数量: {len(sku_codes)}")

    # 3. 检查是否存在
    print("\n[3] 检查编码存在性...")
    
    results = []
    existing = []
    not_existing = []

    for code in sku_codes:
        exists = code in erp_suite_nos
        status = "✅ 存在" if exists else "❌ 不存在"
        results.append({
            "商家编码": code,
            "状态": status,
            "是否在ERP": exists
        })
        if exists:
            existing.append(code)
        else:
            not_existing.append(code)

    # 4. 统计
    print(f"\n[结果统计]")
    print(f"  ✅ 在ERP中存在: {len(existing)} 个")
    print(f"  ❌ 不在ERP中: {len(not_existing)} 个")

    if not_existing:
        print(f"\n[不存在编码列表]")
        for code in not_existing[:20]:  # 只显示前20个
            print(f"    - {code}")
        if len(not_existing) > 20:
            print(f"    ... 还有 {len(not_existing) - 20} 个")

    # 5. 保存结果
    print("\n[4] 保存结果...")
    
    # 保存完整结果JSON
    result_json_file = Path(OUTPUT_DIR) / 'sku_encoding_check.json'
    with open(result_json_file, 'w', encoding='utf-8') as f:
        json.dump({
            "check_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sku_file": SKU_FILE,
            "erp_file": ERP_DATA_FILE,
            "total_sku_codes": len(sku_codes),
            "existing_count": len(existing),
            "not_existing_count": len(not_existing),
            "existing_codes": existing,
            "not_existing_codes": not_existing,
            "details": results
        }, f, ensure_ascii=False, indent=2)
    print(f"    JSON: {result_json_file}")

    # 保存简洁的结果TXT
    result_txt_file = Path(OUTPUT_DIR) / 'sku_encoding_check.txt'
    with open(result_txt_file, 'w', encoding='utf-8') as f:
        f.write("SKU商家编码检查结果\n")
        f.write("=" * 50 + "\n")
        f.write(f"检查时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"SKU文件: {SKU_FILE}\n")
        f.write(f"ERP数据: {ERP_DATA_FILE}\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"✅ 在ERP中存在: {len(existing)} 个\n")
        f.write(f"❌ 不在ERP中: {len(not_existing)} 个\n\n")
        
        if existing:
            f.write("存在编码:\n")
            for code in existing:
                f.write(f"  {code}\n")
            f.write("\n")
        
        if not_existing:
            f.write("不存在编码:\n")
            for code in not_existing:
                f.write(f"  {code}\n")
    print(f"    TXT: {result_txt_file}")

    print("\n[完成]")

if __name__ == "__main__":
    main()
