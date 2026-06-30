import re

with open('java_output.txt', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# 查找 === 响应 === 后面的内容
parts = content.split('=== 响应 ===')
if len(parts) > 1:
    json_part = parts[1]
    # 找第一个 {
    idx = json_part.find('{')
    if idx >= 0:
        json_str = json_part[idx:]
        # 找匹配的结尾 }
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
        json_str = json_str[:end_idx]
        print(f"JSON长度: {len(json_str)}")
        print(f"JSON开头: {json_str[:200]}")

        import json
        data = json.loads(json_str)
        print(f"\nKeys: {list(data.keys())}")
        print(f"code: {data.get('code')}")
        print(f"message: {data.get('message')}")
        print(f"suites数量: {len(data.get('suites', []))}")

        # 统计dyc编号
        suites = data.get('suites', [])
        dyc_nos = [s.get('suite_no', '') for s in suites if s.get('suite_no', '').startswith('dyc-')]
        pt_nos = [s.get('suite_no', '') for s in suites if s.get('suite_no', '').startswith('pt')]

        print(f"\ndyc系列: {len(dyc_nos)}个")
        print(f"pt系列: {len(pt_nos)}个")

        if dyc_nos:
            print(f"dyc系列列表: {dyc_nos[:10]}")
        else:
            print("没有dyc系列组合装")
