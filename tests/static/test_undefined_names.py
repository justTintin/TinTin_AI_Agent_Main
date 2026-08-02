# -*- coding: utf-8 -*-
"""未定义名静态回归检查（防 `_json` 类局部别名泄漏 / 漏导入导致的 NameError）。

背景（2026-08-02）：
  - subtitle_removal_page_v14 在页面方法里用 `_json.dumps`，但 `_json` 只在
    worker 的 run() 内局部导入 → 点「开始去除字幕」直接 NameError、界面无反应。
  - 同类漏导入还抓到：compile_video_page 的 VideoTemplateLoadWorker、
    montage/dialogs.py 的 mdi_button/subprocess、desc_workers 的 url、
    utils_media 的 run_subprocess、nas_client 的 ShareAccess/CreateDisposition 等，
    均已修复。

检查：
  1. 全 studio：`_json.`/`_time.` 局部别名泄漏（模块级或所在函数内未定义却使用）。
  2. 全 studio：函数内使用了但从未定义/导入的名字（AST 作用域链解析，
     支持闭包/元组解包/推导式/嵌套 def）。
  已知遗留（未被任何页面引用、重构后遗留的死代码，记录原因以便后续清理）：
    - utils/video_indexer.py  VideoIndexWorker/WhisperFillWorker（素材管理迁移服务端后遗留）
    - utils/rustfs_manager.py sync_directory_to_rustfs（引用已删除的 scan_directory 辅助函数）
"""
import ast
import builtins
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

STUDIO_DIR = testutil.STUDIO_DIR
SKIP_DIRS = {".runtime", "__pycache__", "backups", ".idea"}

# 模块级可用的内置 dunder 等
_BUILTINS = set(dir(builtins)) | {"self", "cls", "__file__", "__name__", "__doc__"}

# config.paths 等跨文件约定名（历史代码直接使用，此处视为已定义）
_KNOWN_GLOBALS = {
    "TMP_DIR", "PROJECT_ROOT", "WORKSPACE_ROOT", "CONFIG_DIR", "RUNTIME_DIR",
    "LOG_DIR", "COOKIES_DIR", "ACCOUNTS_DIR", "PW_BROWSERS_DIR",
    "FINAL_OUTPUT_DIR", "KNOWLEDGE_MEDIA_DIR", "COVER_OUTPUT_DIR", "MG_OUTPUT_DIR",
    "AI_CONFIG_FILE", "DATA_DIR", "BACKUP_DIR", "TMP", "TEMP", "TMPDIR", "TEMPLATES",
    "OUTPUTS_DIR",
}

# 已知遗留死代码（未被引用），记录原因避免误报；新代码不得新增
KNOWN_BROKEN = {
    "utils/video_indexer.py": "VideoIndexWorker/WhisperFillWorker 在素材管理迁移服务端后遗留（compute_video_hash/mgr 未定义），未被任何页面引用",
    "utils/rustfs_manager.py": "sync_directory_to_rustfs 引用已删除的 scan_directory 辅助函数，函数本身未被引用",
}


def _all_py_files():
    out = []
    for root, dirs, files in os.walk(STUDIO_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return out


def _add_targets(targets, names):
    for t in targets or []:
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            _add_targets(t.elts, names)
        elif isinstance(t, ast.Starred) and isinstance(t.value, ast.Name):
            names.add(t.value.id)


def _stmt_defs(body, names):
    """收集语句块内的局部定义（含 if/for/try 等子块；嵌套 def/class 只收名字）。"""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            _add_targets(node.targets, names)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            _add_targets([node.target], names)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _add_targets([node.target], names)
        elif isinstance(node, ast.With):
            for wi in node.items:
                if wi.optional_vars:
                    _add_targets([wi.optional_vars], names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):
                if child.name:
                    names.add(child.name)
                _stmt_defs(child.body, names)
            elif isinstance(child, ast.stmt):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(child.name)  # 嵌套在 if/try 等块内的 def/class，绑定到所在作用域
                else:
                    _stmt_defs([child], names)


def _extra_defs(tree, names):
    """lambda 参数 + 推导式目标（视为已定义，避免误报）。"""
    for c in ast.walk(tree):
        if isinstance(c, ast.Lambda):
            for a in list(c.args.args) + list(c.args.kwonlyargs) + list(c.args.posonlyargs):
                names.add(a.arg)
        elif isinstance(c, ast.comprehension):
            _add_targets([c.target], names)


def _module_names(tree):
    names = set(_BUILTINS) | set(_KNOWN_GLOBALS)

    def scan(stmts):
        for node in stmts:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                _add_targets(node.targets, names)
            elif isinstance(node, ast.AnnAssign):
                _add_targets([node.target], names)
            elif isinstance(node, ast.stmt):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.stmt) and not isinstance(child,
                                                                      (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        scan([child])

    scan(tree.body)
    return names


def _undefined_names(path):
    """返回 [(函数名, 未定义名, 行号), ...]（跳过 KNOWN_BROKEN 文件）。"""
    rel = os.path.relpath(path, STUDIO_DIR).replace("\\", "/")
    if rel in KNOWN_BROKEN:
        return []
    with io.open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mod = _module_names(tree)
    issues = []

    def visit_function(node, enclosing):
        defined = set(enclosing)
        for a in list(node.args.args) + list(node.args.kwonlyargs) + list(node.args.posonlyargs):
            defined.add(a.arg)
        if node.args.vararg:
            defined.add(node.args.vararg.arg)
        if node.args.kwarg:
            defined.add(node.args.kwarg.arg)
        _stmt_defs(node.body, defined)
        _extra_defs(node, defined)
        used = set()

        def _collect(n):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                used.add(n.id)
            for child in ast.iter_child_nodes(n):
                _collect(child)

        for st in node.body:
            _collect(st)
        for n in sorted(used - defined):
            issues.append((node.name, n, node.lineno))
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_function(sub, defined)
            elif isinstance(sub, ast.ClassDef):
                for m in sub.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        visit_function(m, defined)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function(node, mod)
        elif isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_function(m, mod)
    return issues


def _alias_leaks(path):
    """_json./_time. 别名在模块级或所在函数内均未定义 → 泄漏。返回 [(函数名, 别名, 行号)]。"""
    with io.open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mod = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                mod.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                mod.add(a.asname or a.name)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defined = set(mod)
        for a in list(node.args.args) + list(node.args.kwonlyargs):
            defined.add(a.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    defined.add(a.asname or a.name.split(".")[0])
            elif isinstance(sub, ast.ImportFrom):
                for a in sub.names:
                    defined.add(a.asname or a.name)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                    and sub.value.id in ("_json", "_time") and sub.value.id not in defined:
                out.append((node.name, sub.value.id, sub.lineno))
    return out


class TestUndefinedNames(unittest.TestCase):
    def test_no_undefined_names(self):
        bad = []
        for path in _all_py_files():
            try:
                for fn, name, ln in _undefined_names(path):
                    bad.append("%s:%d %s(): 未定义名 %s" % (
                        os.path.relpath(path, STUDIO_DIR), ln, fn, name))
            except SyntaxError as e:
                bad.append("%s: 语法错误 %s" % (os.path.relpath(path, STUDIO_DIR), e))
        if bad:
            self.fail("发现未定义名（可能 NameError）：\n  " + "\n  ".join(bad[:50]))

    def test_no_json_time_alias_leak(self):
        bad = []
        for path in _all_py_files():
            try:
                for fn, alias, ln in _alias_leaks(path):
                    bad.append("%s:%d %s(): 使用 %s. 但作用域内未定义" % (
                        os.path.relpath(path, STUDIO_DIR), ln, fn, alias))
            except SyntaxError:
                continue
        if bad:
            self.fail("发现局部别名泄漏（如 _json.）：\n  " + "\n  ".join(bad[:50]))


if __name__ == "__main__":
    unittest.main()