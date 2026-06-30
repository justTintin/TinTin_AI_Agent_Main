"""
用商家编码查询ERP组合装
"""
import subprocess
import json
import re
from datetime import datetime

# Java程序路径
JAVA_BIN = r"C:\Java\jdk-21\bin\java.exe"
JAVA_CP = r"C:\Users\tintin\WorkBuddy\Claw\wdt-erp;C:\Users\tintin\WorkBuddy\Claw\wdt-erp\fastjson-1.2.83.jar"
JAVA_CLASS = "com.workbuddy.erp.WdtClient"

# 要查询的商家编码
SUITE_NO = "dyc-080"


def run_java(params):
    """通过Java程序执行API调用"""
    cmd = [JAVA_BIN, "-cp", JAVA_CP, JAVA_CLASS]
    for key, value in params.items():
        cmd.extend([f"--{key}", value])

    result = subprocess.run(cmd, capture_output=True, timeout=60)

    try:
        stdout = result.stdout.decode('gbk', errors='replace')
    except:
        stdout = result.stdout.decode('utf-8', errors='replace')

    # 从=== 响应 ===后提取JSON
    parts = stdout.split('=== 响应 ===')
    if len(parts) > 1:
        json_part = parts[1]
        idx = json_part.find('{')
        if idx >= 0:
            json_str = json_part[idx:]
            bracket_count = 0
            end_idx = len(json_str)
            for i, c in enumerate(json_str):
                if c == '{':
                    bracket_count += 1
                elif c == '}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_idx = i + 1
                        break
            return json_str[:end_idx]
    return None


def main():
    print(f"查询ERP组合装: {SUITE_NO}")
    print("=" * 50)

    # 查询参数 - 使用 goods_combine_search 接口
    params = {
        'page_no': '1',
        'page_size': '100',
        'start_time': '2020-01-01 00:00:00',  # 查询全部历史数据
        'end_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    json_str = run_java(params)
    if json_str:
        data = json.loads(json_str)
        print(f"code: {data.get('code')}")
        print(f"message: {data.get('message')}")

        suites = data.get('suites', [])
        print(f"总组合装数: {len(suites)}")

        # 查找 dyc-080
        found = None
        for s in suites:
            if s.get('suite_no') == SUITE_NO:
                found = s
                break

        if found:
            print(f"\n✅ 找到 {SUITE_NO}:")
            print(f"  组合装名称: {found.get('suite_name')}")
            print(f"  组合装简称: {found.get('short_name')}")
            print(f"  条码: {found.get('barcode')}")
            print(f"  零售价: {found.get('retail_price')}")
            print(f"  批发价: {found.get('wholesale_price')}")
            print(f"  会员价: {found.get('member_price')}")
            print(f"  品牌: {found.get('brand_no')}")
            print(f"  分类: {found.get('category_no')}")
            print(f"  备注: {found.get('remark')}")
        else:
            print(f"\n❌ 未找到 {SUITE_NO}")

            # 列出所有 dyc- 系列
            dyc_list = [s for s in suites if 'dyc' in str(s.get('suite_no', '')).lower()]
            if dyc_list:
                print(f"\n但找到 {len(dyc_list)} 个包含 'dyc' 的组合装:")
                for s in dyc_list[:10]:
                    print(f"  {s.get('suite_no')}: {s.get('suite_name')}")
            else:
                print("\nERP中没有 dyc 系列的组合装")


if __name__ == "__main__":
    main()
