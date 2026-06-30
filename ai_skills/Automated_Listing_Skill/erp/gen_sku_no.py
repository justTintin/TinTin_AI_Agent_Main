# -*- coding: utf-8 -*-
"""
递归查找可用商家编码 - 保留xls完整数据

从配置文件读取数据路径
"""
import json
import pandas as pd
from datetime import datetime
import os
import sys

# 添加config目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'config'))
from skill_config import (
    ERP_SUITES_DATA,
    LISTING_DATA_DIR,
    LISTING_XLS_NAME,
    SKU_NEW_CODES_JSON
)

def get_number_format(code):
    """获取编码的数字格式，用于保持位数"""
    if '-' in code:
        prefix, num_str = code.rsplit('-', 1)
        num = int(num_str)
        digits = len(num_str)
        return prefix, digits
    return code, None

def find_next_code(code, existing_codes):
    """递归查找下一个可用编码"""
    prefix, digits = get_number_format(code)
    if digits is None:
        return code

    num = int(code.split('-')[-1])
    new_code = f"{prefix}-{str(num + 1).zfill(digits)}"

    if new_code in existing_codes:
        return find_next_code(new_code, existing_codes)
    return new_code

def main(data_dir=None, xls_name=None):
    print("=" * 60)
    print("商家编码递归递增查找工具")
    print("=" * 60)

    # 使用配置或自定义路径
    data_dir = data_dir or LISTING_DATA_DIR
    xls_file = xls_name or LISTING_XLS_NAME
    xls_path = os.path.join(data_dir, xls_file)
    erp_file = ERP_SUITES_DATA

    # 读取ERP数据
    print(f"\n[1] 读取ERP数据: {erp_file}")
    if not os.path.exists(erp_file):
        print(f"    错误：ERP数据文件不存在！")
        print(f"    请先运行：python src/erp_cli.py list --days 29")
        return None

    with open(erp_file, 'r', encoding='utf-8') as f:
        erp_data = json.load(f)

    suites = erp_data.get('suites', [])
    erp_total = len(suites)
    print(f"    ERP数据总量: {erp_total}")

    # 构建ERP商家编码集合
    erp_codes = {s.get('suite_no', '') for s in suites if s.get('suite_no')}
    print(f"    ERP商家编码数量: {len(erp_codes)}")

    # 读取xls文件
    print(f"\n[2] 读取xlsx文件: {xls_path}")
    if not os.path.exists(xls_path):
        print(f"    错误：xlsx文件不存在！")
        print(f"    请检查路径：{xls_path}")
        return None

    df = pd.read_excel(xls_path)
    total_rows = len(df)
    print(f"    xlsx总行数: {total_rows}")

    # 处理每一行
    results = []
    modified_count = 0

    for idx, row in df.iterrows():
        original_code = str(row['商家编码'])
        new_code = original_code

        # 检查是否在ERP中存在
        if original_code in erp_codes:
            new_code = find_next_code(original_code, erp_codes)
            # 把新编码加入集合，避免同一批次中冲突
            erp_codes.add(new_code)
            modified_count += 1
            status = "已修改"
        else:
            # 不在ERP中，保持原样
            status = "无需修改"

        results.append({
            "序号": idx + 1,
            "原编码": original_code,
            "新编码": new_code,
            "状态": status,
            "完整数据": {col: ("" if pd.isna(val) else val) for col, val in row.items()}
        })

        if status == "已修改":
            print(f"    [{idx+1}] {original_code} -> {new_code}")

    # 汇总
    summary = {
        "处理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "数据源目录": data_dir,
        "xls文件": xls_file,
        "ERP数据总数": erp_total,
        "xls数据行数": total_rows,
        "统计": {
            "已修改": modified_count,
            "无需修改": total_rows - modified_count,
            "总计": total_rows
        },
        "明细": results
    }

    run_id = (os.environ.get("ALS_RUN_ID") or "").strip()
    if not run_id:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_dir = os.path.join(data_dir, "_runs", run_id, "preprocess")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "sku_new_codes.json")

    summary["输出目录"] = output_dir
    summary["输出文件"] = output_file

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[3] 结果已保存: {output_file}")
    print(f"\n{'=' * 60}")
    print(f"处理完成！")
    print(f"  总行数: {total_rows}")
    print(f"  已修改: {modified_count}")
    print(f"  无需修改: {total_rows - modified_count}")
    print(f"{'=' * 60}")

    return summary

if __name__ == "__main__":
    # 支持命令行指定数据目录
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
        main(data_dir=data_dir)
    else:
        main()
