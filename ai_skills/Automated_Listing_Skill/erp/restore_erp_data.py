"""
restore_erp_data.py
将旧的suites_full.json转换为新格式并恢复完整数据
"""

import json
from pathlib import Path
from datetime import datetime

# 源文件（旧格式，只有100条）
SOURCE_FILE = r"C:\Users\tintin\WorkBuddy\Claw\erp\output\suites_full.json"
# 目标文件
TARGET_FILE = r"C:\Users\tintin\WorkBuddy\Claw\erp_suites_data.json"

def main():
    print("恢复ERP数据...")

    # 读取旧格式数据
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        old_data = json.load(f)

    # 提取suites
    suites = old_data.get('suites', [])

    # 创建新格式数据
    new_data = {
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_range": {
            "start": "2026-03-11 00:00:00",
            "end": "2026-04-09 23:59:59"
        },
        "days": 29,
        "total_count": len(suites),
        "page_count": 1,
        "page_size": 100,
        "suites": suites
    }

    # 保存
    with open(TARGET_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print(f"已恢复 {len(suites)} 条数据到 {TARGET_FILE}")

if __name__ == "__main__":
    main()
