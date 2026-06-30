"""
列出ERP中所有组合装商家编码 - 保存到文件
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
        'page_size': '200',
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

        # ===== 保存到文本文件 =====
        txt_path = r"C:\Users\tintin\WorkBuddy\Claw\erp_suites_list.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("ERP组合装列表 (按商家编码字母排序)\n")
            f.write("=" * 50 + "\n")
            f.write(f"总条数: {len(suites)}\n")
            f.write("=" * 50 + "\n\n")
            for i, no in enumerate(suite_nos_sorted, 1):
                f.write(f"{i:3d}. {no}\n")

        # 查找dyc系列
        dyc_list = [no for no in suite_nos if no.startswith('dyc-')]
        print(f"dyc系列: {dyc_list if dyc_list else '(无)'}")
        print(f"\n已保存到: {txt_path}")

        # ===== 保存完整JSON =====
        json_path = r"C:\Users\tintin\WorkBuddy\Claw\erp_suites_full.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"完整JSON已保存到: {json_path}")


if __name__ == "__main__":
    main()
