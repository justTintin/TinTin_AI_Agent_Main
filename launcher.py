#!/usr/bin/env python3
"""螺丝钉-电商智能体矩阵 · 启动器/解包器

双模式：
  模式1 — 首次运行：检测到工程文件不存在，从分卷包(.vol.*)中解压
  模式2 — 正常运行：工程文件已存在，直接启动应用

发布流程：
  1. python tools/pack_release.py    → 生成 螺丝钉-电商智能体矩阵.vol.*
  2. python build.py launcher        → 生成 螺丝钉-电商智能体矩阵.exe
  3. 把 .exe + .vol.* 一起发给客户
"""
import os, sys, subprocess, zipfile, glob, re, traceback

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
os.chdir(BASE_DIR)


def _pause(msg="按 Enter 退出..."):
    """等待用户确认。windowed 模式用 MessageBox。"""
    if getattr(sys, 'frozen', False) and not sys.stdin:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "螺丝钉-电商智能体矩阵", 0)
        except Exception:
            pass
    else:
        try:
            input(msg)
        except (EOFError, RuntimeError):
            pass


# ═══════════════════════════════════════════════════════════
# 模式1：首次运行 → 解包
# ═══════════════════════════════════════════════════════════

def needs_extraction() -> bool:
    """检测是否需要首次解包。"""
    return not os.path.isfile(os.path.join(BASE_DIR, "studio", "gui_main.py"))


def find_volumes() -> list[str]:
    """查找分卷文件，按编号排序。"""
    pattern = os.path.join(BASE_DIR, "螺丝钉-电商智能体矩阵.vol.*")
    files = glob.glob(pattern)
    # 排除 manifest.json
    files = [f for f in files if not f.endswith(".manifest.json")]
    files.sort(key=lambda x: int(re.search(r"\.vol\.(\d+)$", x).group(1)))
    return files


def extract_volumes(volumes: list[str]):
    """从分卷 zip 中解压所有文件。"""
    total = len(volumes)
    print(f"首次运行，正在解包 {total} 个分卷...")

    # 第一个分卷是完整的 zip 头，后续分卷需要按顺序合并解压
    # zipfile 不支持直接分卷读取，所以逐个处理
    for i, vol_path in enumerate(volumes):
        vol_name = os.path.basename(vol_path)
        print(f"  [{i+1}/{total}] {vol_name} ...")
        try:
            with zipfile.ZipFile(vol_path, "r", allowZip64=True) as zf:
                zf.extractall(BASE_DIR)
        except zipfile.BadZipFile:
            # 不是独立 zip 的分卷需要合并后解压
            _extract_split_volumes(volumes, i)
            break

    print("解包完成！")


def _extract_split_volumes(volumes: list[str], start_idx: int):
    """处理跨卷 zip（第一个是完整 zip，后续是续卷）。"""
    import io
    # 合并所有分卷到内存
    buffer = io.BytesIO()
    for v in volumes:
        with open(v, "rb") as f:
            buffer.write(f.read())
    buffer.seek(0)
    with zipfile.ZipFile(buffer, "r", allowZip64=True) as zf:
        zf.extractall(BASE_DIR)


def run_extraction():
    """解包流程主入口。"""
    volumes = find_volumes()
    if not volumes:
        print("错误：未找到分卷文件")
        print("请将 螺丝钉-电商智能体矩阵.vol.* 与本程序放在同一目录。")
        _pause()
        sys.exit(1)

    extract_volumes(volumes)
    print("首次解包完成，正在启动...")


# ═══════════════════════════════════════════════════════════
# 模式2：正常运行 → 启动应用
# ═══════════════════════════════════════════════════════════

def find_python() -> str:
    """查找嵌入式 Python。"""
    candidates = [
        os.path.join(BASE_DIR, "python_embeded", "python.exe"),
        os.path.join(BASE_DIR, "python_embeded", "pythonw.exe"),
        os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe"),
        "python",
    ]
    for c in candidates:
        if c == "python":
            return c
        if os.path.isfile(c):
            return c
    return "python"


def launch_app():
    """启动主程序。"""
    python_exe = find_python()
    entry = os.path.join(BASE_DIR, "studio", "gui_main.py")

    if not os.path.isfile(entry):
        print(f"错误：未找到 {entry}")
        print("请确认分卷已正确解包。")
        _pause()
        sys.exit(1)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.path.join(BASE_DIR, "studio"))
    env["TINTIN_NO_LICENSE"] = "1"

    result = subprocess.run([python_exe, entry], env=env, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"程序异常退出，错误码: {result.returncode}")
        _pause()


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    if needs_extraction():
        run_extraction()
    launch_app()


if __name__ == "__main__":
    main()
