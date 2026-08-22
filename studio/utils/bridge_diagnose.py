"""桥接服务连接诊断脚本。

用法：在【客户端正在运行 + 插件显示"未连接客户端"】的状态下，双击运行：
    python_embeded/python.exe utils/bridge_diagnose.py

输出每一项的真相，帮助定位"客户端显示运行中但插件连不上"的根因。
"""
import os
import socket
import sys
import urllib.request

# 候选端口（与扩展 background.js discoverBridge 一致）
DEFAULT_PORT = 51233
CANDIDATE_PORTS = [DEFAULT_PORT, 49337, 54321, 51000]


def _read_config_port():
    """读取客户端配置里设的端口。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        studio = os.path.dirname(here)
        cfg = os.path.join(studio, "data", "extension_bridge.json")
        if os.path.isfile(cfg):
            import json
            with open(cfg, encoding="utf-8") as f:
                return int(json.load(f).get("port") or DEFAULT_PORT), cfg
    except (OSError, json.JSONDecodeError) as e:
        return None, f"读取配置失败: {e}"
    return None, cfg + "（不存在，用默认端口）"


def _port_listening(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _ping(port):
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=2)
        return r.status, r.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # urllib HTTP 请求
        return None, str(e)[:120]


def main():
    print("=" * 60)
    print("  桥接服务连接诊断")
    print("=" * 60)

    cfg_port, cfg_info = _read_config_port()
    print(f"\n[1] 客户端配置端口: {cfg_port or DEFAULT_PORT}")
    print(f"    配置来源: {cfg_info}")

    print("\n[2] 逐端口探测（监听 + /ping）:")
    listened = []
    for p in sorted(set([cfg_port or DEFAULT_PORT] + CANDIDATE_PORTS)):
        listening = _port_listening(p)
        if listening:
            listened.append(p)
        code, body = _ping(p) if listening else (None, "端口未监听")
        flag = "完成：" if (listening and code == 200) else ("注意：" if listening else "失败：")
        print(f"    {flag} 端口 {p}: 监听={'是' if listening else '否'} "
              f"/ping={'HTTP '+str(code) if code else '失败'}")
        if code == 200:
            print(f"        响应: {body}")

    print("\n[3] 结论:")
    if not listened:
        print("    失败： 没有任何候选端口在监听 → 客户端桥接服务实际未启动成功。")
        print("       可能原因：端口被占用、start() 抛异常但状态显示错误、")
        print("       或 auto_start 关闭且未手动点'启动服务'。")
        print("       建议：在客户端'扩展采集'页点'启动服务'，看是否报错。")
    elif cfg_port and cfg_port not in listened:
        print(f"    注意： 配置端口 {cfg_port} 未监听，但其它端口在监听: {listened}")
        print("       → 客户端可能因端口冲突换了端口，但插件还连旧端口。")
        print(f"       建议：把插件端口改为 {listened[0]}，或在客户端把端口改回 {cfg_port} 重启。")
    elif cfg_port in listened:
        p = cfg_port
        code, _ = _ping(p)
        if code == 200:
            print(f"    完成： 端口 {p} 正常监听且 /ping 返回 200。")
            print("       服务端没问题 → 问题在浏览器扩展侧：")
            print("       - 确认插件 host_permissions 含 <all_urls>（已含）")
            print("       - Chrome 地址栏访问 chrome://extensions → 点插件'详细信息'")
            print("         → 确认已勾选'允许访问文件网址'及站点权限")
            print("       - 点插件弹窗'保存'按钮，确认 host/port 是 127.0.0.1 /", p)
            print("       - 浏览器 F12 → 扩展 service worker 控制台看 fetch 报错")
            print("       - 杀毒/防火墙是否拦了浏览器对 127.0.0.1 的访问")
        else:
            print(f"    注意： 端口 {p} 在监听但 /ping 异常 (HTTP {code}) → 服务异常。")
    input("\n按回车关闭...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 诊断脚本顶层兜底
        print(f"\n诊断脚本异常: {e}")
        input("按回车关闭...")
        sys.exit(1)
