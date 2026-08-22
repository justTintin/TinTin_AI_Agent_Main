"""一键启动验证：编译 studio 全部 .py → 离屏导入 gui_main → 单元测试。

用法(仓库根目录):
    python_embeded\\python.exe scripts\\verify_startup.py

任何一步失败都以非零退出码结束并打印原因。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIO = os.path.join(ROOT, "studio")
TESTS = os.path.join(ROOT, "tests", "unit")
PY = sys.executable


def run(args, cwd=None):
    r = subprocess.run([PY] + args, cwd=cwd)
    if r.returncode != 0:
        sys.exit(r.returncode)


# ---- [1/3] 全量语法编译 ----
print("== [1/3] 编译 studio 全部 .py ==")
import py_compile  # noqa: E402

bad = []
for dp, _dirs, files in os.walk(STUDIO):
    for f in files:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        try:
            py_compile.compile(p, doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append(str(exc))
if bad:
    print("编译失败:")
    for line in bad:
        print("  " + line)
    sys.exit(1)
print("OK")

# ---- [2/3] 离屏导入 gui_main(启动链路) ----
print("== [2/3] 离屏导入 gui_main ==")
code = (
    "import sys, os; "
    f"sys.path.insert(0, r'{STUDIO}'); "
    "os.environ['QT_QPA_PLATFORM']='offscreen'; "
    "os.environ['PYTHONDONTWRITEBYTECODE']='1'; "
    "import gui_main; print('IMPORT OK'); os._exit(0)"
)
run(["-c", code])
print("OK")

# ---- [3/3] 单元测试 ----
print("== [3/3] 单元测试 ==")
run(["-m", "unittest", "discover", "-s", TESTS])
print("ALL OK")
