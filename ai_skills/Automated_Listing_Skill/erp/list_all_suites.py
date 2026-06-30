"""
列出ERP中所有组合装商家编码
"""
import subprocess
import json
from datetime import datetime

JAVA_BIN = r"C:\Java\jdk-21\bin\java.exe"
JAVA_CP = r"C:\Users\tintin\WorkBuddy\Claw\wdt-erp;C:\Users\tintin\WorkBuddy\Claw\wdt-erp\fastjson-1.2.83.jar"


def run_java(params):
    cmd = [JAVA_BIN, "-cp", JAVA_CP, "com.workbuddy.erp.WdtClient"]
    for key, value in params.items():
        cmd.extend([f"--{key}", value])

    result = subprocess.run(cmd, capture_output=True, timeout=60)
    try:
        stdout = result.stdout.decode('gbk', errors='replace')
    except:
        stdout = result.stdout.decode('utf-8', errors='replace')

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
    params = {
        'page_no': '1',
        'page_size': '200',  # 尝试获取更多
        'start_time': '2020-01-01 00:00:00',
        'end_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    print("查询ERP全部组合装...")
    json_str = run_java(params)
    if json_str:
        data = json.loads(json_str)
        suites = data.get('suites', [])
        print(f"总条数: {len(suites)}")

        # 提取所有商家编码
        suite_nos = [s.get('suite_no', '') for s in suites]

        # 按字母排序
        suite_nos_sorted = sorted(suite_nos)

        print("\n全部商家编码 (按字母排序):")
        print("-" * 30)
        for i, no in enumerate(suite_nos_sorted, 1):
            print(f"{i:3d}. {no}")

        # 查找dyc系列
        dyc_list = [no for no in suite_nos if no.startswith('dyc-')]
        print(f"\ndyc系列: {dyc_list if dyc_list else '(无)'}")


if __name__ == "__main__":
    main()
