"""
按商家编码精确查询ERP组合装
"""
import subprocess
import json
from datetime import datetime

JAVA_BIN = r"C:\Java\jdk-21\bin\java.exe"
JAVA_CP = r"C:\Users\tintin\WorkBuddy\Claw\wdt-erp;C:\Users\tintin\WorkBuddy\Claw\wdt-erp\fastjson-1.2.83.jar"

# 要查询的商家编码
SUITE_NO = "dyc-080"


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
    print(f"按商家编码查询: {SUITE_NO}")
    print("=" * 50)

    # 测试1: 不带时间
    print("\n[测试1] 不带时间参数:")
    params1 = {
        'page_no': '1',
        'page_size': '100',
    }
    json_str1 = run_java(params1)
    if json_str1:
        data1 = json.loads(json_str1)
        print(f"code: {data1.get('code')}, message: {data1.get('message')}")
        suites1 = data1.get('suites', [])
        print(f"返回条数: {len(suites1)}")
        # 查找dyc-080
        for s in suites1:
            if s.get('suite_no') == SUITE_NO:
                print(f"✅ 找到 {SUITE_NO}:")
                print(f"   {json.dumps(s, ensure_ascii=False, indent=2)}")
                return

        print(f"❌ 未找到 {SUITE_NO}")

    # 测试2: 尝试用 suite_no 参数
    print("\n[测试2] 添加 suite_no 参数:")
    params2 = {
        'page_no': '1',
        'page_size': '100',
        'suite_no': SUITE_NO,
    }
    json_str2 = run_java(params2)
    if json_str2:
        data2 = json.loads(json_str2)
        print(f"code: {data2.get('code')}, message: {data2.get('message')}")
        suites2 = data2.get('suites', [])
        print(f"返回条数: {len(suites2)}")
        if suites2:
            print(f"✅ 找到: {json.dumps(suites2[0], ensure_ascii=False)}")

    # 测试3: 尝试用 suite_no_list 参数
    print("\n[测试3] 添加 suite_no_list 参数:")
    params3 = {
        'page_no': '1',
        'page_size': '100',
        'suite_no_list': SUITE_NO,
    }
    json_str3 = run_java(params3)
    if json_str3:
        data3 = json.loads(json_str3)
        print(f"code: {data3.get('code')}, message: {data3.get('message')}")
        suites3 = data3.get('suites', [])
        print(f"返回条数: {len(suites3)}")
        if suites3:
            print(f"✅ 找到: {json.dumps(suites3[0], ensure_ascii=False)}")

    # 测试4: 尝试用 goods_no_list 参数
    print("\n[测试4] 添加 goods_no_list 参数:")
    params4 = {
        'page_no': '1',
        'page_size': '100',
        'goods_no_list': SUITE_NO,
    }
    json_str4 = run_java(params4)
    if json_str4:
        data4 = json.loads(json_str4)
        print(f"code: {data4.get('code')}, message: {data4.get('message')}")
        suites4 = data4.get('suites', [])
        print(f"返回条数: {len(suites4)}")
        if suites4:
            print(f"✅ 找到: {json.dumps(suites4[0], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
