"""
wdt_cli.py
旺店通ERP CLI工具 - Python调用Java执行API
"""

import subprocess
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


# ERP配置
ERP_CONFIG = {
    'baseurl': 'https://api.wangdian.cn/openapi2/',
    'appkey': 'wdt112233-jd',
    'appsecret': '7f432fcbcf8bd325ee23bc7453169d92',
    'sid': 'wdt112233',
}

# Java程序路径
JAVA_BIN = r"C:\Java\jdk-21\bin\java.exe"
JAVA_CP = r"C:\Users\tintin\WorkBuddy\Claw\wdt-erp;C:\Users\tintin\WorkBuddy\Claw\wdt-erp\fastjson-1.2.83.jar"
JAVA_CLASS = "com.workbuddy.erp.WdtClient"


def run_java(params: Dict[str, str]) -> str:
    """通过Java程序执行API调用，返回原始JSON字符串"""
    cmd = [JAVA_BIN, "-cp", JAVA_CP, JAVA_CLASS]

    for key, value in params.items():
        cmd.extend([f"--{key}", value])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60
        )

        # 尝试用GBK解码
        try:
            stdout = result.stdout.decode('gbk', errors='replace')
        except:
            stdout = result.stdout.decode('utf-8', errors='replace')

        # 从输出中提取JSON（=== 响应 === 后面的内容）
        parts = stdout.split('=== 响应 ===')
        if len(parts) > 1:
            json_part = parts[1]
            idx = json_part.find('{')
            if idx >= 0:
                json_str = json_part[idx:]

                # 找到匹配的结尾
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

    except Exception as e:
        print(f"[ERROR] 执行失败: {e}")

    return None


def search_combinations(start_time: str = None, end_time: str = None,
                       page_no: int = 1, page_size: int = 100) -> Dict[str, Any]:
    """查询组合装商品"""
    params = {
        'page_no': str(page_no),
        'page_size': str(page_size),
    }

    if start_time:
        params['start_time'] = start_time
    if end_time:
        params['end_time'] = end_time

    json_str = run_java(params)
    if json_str:
        return json.loads(json_str)

    return {"code": -1, "message": "API调用失败", "suites": []}


def find_max_dyc_no(suites: List[Dict]) -> Optional[str]:
    """查找最大的dyc-编号"""
    max_no = 0
    for item in suites:
        suite_no = item.get('suite_no', '')
        if suite_no.startswith('dyc-'):
            try:
                num = int(suite_no.split('-')[1])
                max_no = max(max_no, num)
            except (ValueError, IndexError):
                pass
    return f"dyc-{max_no:03d}" if max_no > 0 else None


def print_suites(suites: List[Dict], title: str = "组合装列表"):
    """打印组合装表格"""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print('=' * 80)

    if not suites:
        print("  (无数据)")
        return

    print(f"{'序号':<5} {'编号':<15} {'名称':<40}")
    print('-' * 80)

    for i, item in enumerate(suites[:50], 1):
        no = item.get('suite_no', '')[:15]
        name = item.get('suite_name', '')[:40]
        print(f"{i:<5} {no:<15} {name:<40}")

    if len(suites) > 50:
        print(f"... (共 {len(suites)} 条)")

    print('=' * 80)


def main():
    """主函数"""
    print("=" * 60)
    print("  旺店通ERP API 查询工具")
    print("=" * 60)

    # 计算时间范围
    now = datetime.now()
    end_time = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    start_time = (now - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")

    print(f"\n[INFO] 查询组合装...")
    print(f"[INFO] 时间范围: {start_time} ~ {end_time}")

    response = search_combinations(start_time, end_time)

    code = response.get('code')
    message = response.get('message', 'ok')
    suites = response.get('suites', [])

    print(f"\n{'=' * 60}")
    print(f"  查询结果")
    print('=' * 60)
    print(f"  code: {code}")
    print(f"  message: {message}")
    print(f"  组合装数量: {len(suites)}")

    if suites:
        print_suites(suites, "ERP组合装列表")

        # 统计
        dyc_count = sum(1 for s in suites if s.get('suite_no', '').startswith('dyc-'))
        pt_count = sum(1 for s in suites if s.get('suite_no', '').startswith('pt'))
        other_count = len(suites) - dyc_count - pt_count

        print(f"\n[统计]")
        print(f"  dyc系列: {dyc_count}个")
        print(f"  pt系列: {pt_count}个")
        print(f"  其他: {other_count}个")

        # 最大dyc编号
        max_dyc = find_max_dyc_no(suites)
        print(f"  最大dyc编号: {max_dyc if max_dyc else '无'}")

        # 建议
        print(f"\n[建议]")
        if dyc_count == 0:
            print(f"  ERP中没有dyc系列组合装")
            print(f"  可以从 dyc-001 开始分配编号")
        else:
            # 找到下一个可用编号
            max_num = 0
            for s in suites:
                no = s.get('suite_no', '')
                if no.startswith('dyc-'):
                    try:
                        num = int(no.split('-')[1])
                        max_num = max(max_num, num)
                    except:
                        pass
            print(f"  下一个可用编号: dyc-{max_num + 1:03d}")
    else:
        print("\n[提示] 没有找到组合装数据")

    print()


if __name__ == "__main__":
    main()
