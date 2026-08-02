# -*- coding: utf-8 -*-
"""
Remotion（编程式 MG 动画）渲染客户端。

工程在 studio/remotion/（package.json + src 模板）。本模块用 Node/npm/npx 调用 Remotion：
- install()：在工程目录跑 npm install（首次需要，依赖较重，含无头 Chrome）。
- render(comp_id, props, out_path)：npx remotion render src/index.ts <comp> <out> --props=<json>。
模板元数据 TEMPLATES 同时驱动 GUI 表单。

 注意：业务已迁移到服务端渲染（见 utils/mg_server_client.py 与 gui.mg_render_worker）。
 本模块仅作为离线 fallback 保留，新代码不再要求客户端安装 Node/Chrome。
"""
import os
import json
import shutil
import subprocess
import tempfile

from config.paths import REMOTION_DIR
from utils.platform_utils import create_no_window_flag

# MG 模板（id 对应 remotion/src/Root.tsx 的 Composition id）+ 参数（驱动表单）。
TEMPLATES = [
    {"id": "TitleReveal", "name": "动态标题", "params": [
        {"key": "title", "label": "标题", "type": "text", "default": "主标题"},
        {"key": "subtitle", "label": "副标题", "type": "text", "default": "副标题"},
        {"key": "color", "label": "文字色", "type": "color", "default": "#FFFFFF"},
        {"key": "bg", "label": "背景色", "type": "color", "default": "#101418"},
    ]},
    {"id": "KineticSubtitle", "name": "逐字弹出字幕", "params": [
        {"key": "text", "label": "文案", "type": "text", "default": "逐字弹出的字幕文案"},
        {"key": "color", "label": "文字色", "type": "color", "default": "#FFFFFF"},
        {"key": "bg", "label": "背景色", "type": "color", "default": "#101418"},
    ]},
    {"id": "NumberCounter", "name": "数字增长动画", "params": [
        {"key": "label", "label": "标签", "type": "text", "default": "累计销量"},
        {"key": "from", "label": "起始数", "type": "number", "default": 0},
        {"key": "to", "label": "目标数", "type": "number", "default": 9999},
        {"key": "suffix", "label": "后缀", "type": "text", "default": "+"},
        {"key": "color", "label": "数字色", "type": "color", "default": "#FFD54A"},
        {"key": "bg", "label": "背景色", "type": "color", "default": "#101418"},
    ]},
    {"id": "LowerThird", "name": "下三分之一字幕条", "params": [
        {"key": "title", "label": "主标题", "type": "text", "default": "产品名称"},
        {"key": "subtitle", "label": "副标题", "type": "text", "default": "一句话卖点"},
        {"key": "color", "label": "文字色", "type": "color", "default": "#FFFFFF"},
        {"key": "accent", "label": "强调色", "type": "color", "default": "#FF3366"},
    ]},
]


def _which(name):
    return shutil.which(name) or shutil.which(name + ".cmd")


def node_ok():
    return _which("node") is not None and _which("npm") is not None


def is_installed():
    return os.path.isdir(os.path.join(REMOTION_DIR, "node_modules", "remotion"))


def _run(args, cwd, timeout, on_line=None):
    flags = create_no_window_flag()
    p = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=flags)
    out = []
    for line in p.stdout:
        out.append(line)
        if on_line:
            on_line(line.rstrip())
    p.wait(timeout=timeout)
    return p.returncode, "".join(out)


def install(on_line=None):
    if not node_ok():
        raise RuntimeError("未检测到 Node/npm，请先安装 Node.js。")
    npm = _which("npm")
    code, out = _run([npm, "install"], cwd=REMOTION_DIR, timeout=1800, on_line=on_line)
    if code != 0 or not is_installed():
        raise RuntimeError("npm install 失败：\n" + out[-500:])
    return True


def render(comp_id, props, out_path, on_line=None, timeout=1200):
    if not node_ok():
        raise RuntimeError("未检测到 Node/npm，请先安装 Node.js。")
    if not is_installed():
        raise RuntimeError("Remotion 依赖未安装。请先在 MG 动画页点『安装依赖』。")
    npx = _which("npx")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # props 写临时文件，避免命令行 JSON 转义问题
    pf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(props or {}, pf, ensure_ascii=False)
    pf.close()
    try:
        args = [npx, "remotion", "render", "src/index.ts", comp_id,
                os.path.abspath(out_path), f"--props={pf.name}", "--log=error"]
        code, out = _run(args, cwd=REMOTION_DIR, timeout=timeout, on_line=on_line)
        if code != 0 or not os.path.isfile(out_path):
            raise RuntimeError("Remotion 渲染失败：\n" + out[-600:])
        return out_path
    finally:
        try:
            os.remove(pf.name)
        except OSError:
            pass
