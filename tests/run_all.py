#!/usr/bin/env python3
"""统一测试入口 + 场景覆盖报告。

用法：项目根目录同款 python_embeded 运行：
    python tests/run_all.py                 # 离线：单元+ 静态+ 脚本
    python tests/run_all.py --online        # 加上在线集成测试（服务端/Ollama）
    python tests/run_all.py --category unit # 只跑某类

输出：
    控制台汇总 + tests/report/coverage_report.md（功能覆盖矩阵）
"""
import argparse
import datetime
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS_DIR, "lib"))

FEATURES = [
    ("配置读写 (config_manager)", ["TestConfigManager"]),
    ("品牌归一化 (brand_normalizer)", ["TestBrandNormalizer"]),
    ("极限词检查 (extreme_words)", ["TestExtremeWords"]),
    ("路径与目录结构 (config.paths)", ["TestPaths"]),
    ("硬件编码参数 (hwaccel)", ["TestHwaccelArgs"]),
    ("镜头分析缓存 (shot_analysis_cache)", ["TestShotAnalysisCache"]),
    ("抖音视频解析 (douyin_parser)", ["TestDouyinParser"]),
    ("数据备份 (backup_manager)", ["TestBackupManager"]),
    ("本地技能管理 (skill_manager)", ["TestSkillManager"]),
    ("自动上架数据包校验 (auto_listing)", ["TestAutoListingValidation"]),
    ("语法/导入检查 (全部 studio)", ["TestSyntaxImports"]),
    ("UI 静态回归 (布局/分镜JSON)", ["TestUIRegression"]),
    ("未定义名静态检查 (AST, 全 studio)", ["TestUndefinedNames"]),
    ("样品数据有效性", ["TestSampleFiles"]),
    ("一键成片 (video_compiler)", ["TestVideoCompilerPure", "TestCompileVideoSmoke"]),
    ("智能混剪拼接 Worker (离线 mock)", ["TestMontageConcatWorker"]),
    ("爆款克隆客户端 (离线 mock)", ["TestViralCloneAnalyze", "TestViralClonePlan", "TestViralCloneFlow", "TestViralCloneSource", "TestViralCloneAssetBrowser", "TestViralCloneRun", "TestViralClonePlaceholders"]),
    ("客户端任务下发闭环（client_task_worker，离线 mock）", ["TestPickup", "TestReport", "TestExecute"]),
    ("智能混剪镜头分裂 (在线 montage/split)", ["TestMontageSplitOnline"]),
    ("Ollama 图片识别 (在线)", ["TestOllamaImageRecognition"]),
    ("Ollama 视频分析 (在线)", ["TestOllamaVideo"]),
    ("服务端连通性 (在线)", ["TestServerConnectivity"]),
]

MANUAL_FEATURES = [
    "智能混剪完整流程（真实多镜头拼接回归，需大样本服务端，自动化仅覆盖 worker 及 montage/split 烟雾）",
    "去重字/去水印与 OCR 服务端切换（依赖服务端可用性）",
    "素材检索/产品库服务端接口全量 (material/*)",
    "一键成片桌面成片给到端到端",
    "LLM 压力测试 10并发×50（tests/stress_llm.py 手工执行）",
    "资源占用/长时间运行泄漏检查",
    "UI 响应时间/加载",
]


class CollectResult(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.passed = []

    def addSuccess(self, test):  # noqa: N802
        super().addSuccess(test)
        self.passed.append(test.id())


def _class_of(test_id):
    parts = test_id.split(".")
    return parts[-2] if len(parts) >= 2 else "?"  # noqa: PLR2004


def _status(total, passed, failed, skipped, errors):
    if failed or errors:
        return "失败"
    if passed == total and total > 0:
        return "通过"
    if skipped == total:
        return "跳过"
    return "部分"


def main():
    ap = argparse.ArgumentParser(description="工程统一测试入口")
    ap.add_argument("--online", action="store_true", help="包含在线集成测试")
    ap.add_argument("--category", choices=["unit", "static", "integration", "all"], default="all")
    args = ap.parse_args()

    os.environ["RUN_ONLINE"] = "1" if args.online else "0"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    import importlib.util
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    dirs = ["unit", "static"]
    if args.category in ("integration", "all"):
        dirs.append("integration")
    for d in dirs:
        dir_path = os.path.join(TESTS_DIR, d)
        for f in sorted(os.listdir(dir_path)):
            if not (f.startswith("test_") and f.endswith(".py")):
                continue
            mod_name = f"{d}.{f[:-3]}"
            spec = importlib.util.spec_from_file_location(mod_name, os.path.join(dir_path, f))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            suite.addTests(loader.loadTestsFromModule(mod))

    print("=" * 78)
    print(f"TinTin_AI_Agent_Main 测试套件 | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 类别: {args.category}{' (+在线)' if args.online else ''}")
    print("=" * 78)
    runner = unittest.TextTestRunner(resultclass=CollectResult, verbosity=1)
    result = runner.run(suite)

    rows = []
    for feature, classes in FEATURES:
        ids = [t for t in result.passed + [t[0].id() for t in result.failures + result.errors] +
               [t[0].id() for t in result.skipped] if _class_of(t) in classes]
        cls = set(classes)
        total = sum(1 for t in ids if _class_of(t) in cls)
        passed = sum(1 for t in result.passed if _class_of(t) in cls)
        failed = sum(1 for t in [t[0].id() for t in result.failures] if _class_of(t) in cls)
        errors = sum(1 for t in [t[0].id() for t in result.errors] if _class_of(t) in cls)
        skipped = sum(1 for t in [t[0].id() for t in result.skipped] if _class_of(t) in cls)
        if total == 0:
            total = 0
        rows.append((feature, total, passed, failed, skipped, _status(total, passed, failed, skipped, errors)))

    covered = sum(1 for _, _, _, _, _, st in rows if st in ("通过", "部分"))
    report_path = os.path.join(TESTS_DIR, "report", "coverage_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 测试场景覆盖报告\n\n")
        f.write(f"- 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- 运行方式：{'--online（含在线集成）' if args.online else '离线（仅单元/静态/脚本）'}\n\n")
        f.write("## 自动化覆盖矩阵\n\n")
        f.write("| 场景 | 用例数 | 通过 | 失败 | 跳过 | 状态 |\n|---|---|---|---|---|---|\n")
        for feature, total, passed, failed, skipped, st in rows:
            f.write(f"| {feature} | {total} | {passed} | {failed} | {skipped} | {st} |\n")
        f.write(f"\n- 已自动化覆盖场景：{covered} / {len(rows)}\n")
        f.write("\n## 尚未自动化的场景（来自 docs/TEST_PLAN.md，需手工/后续补充）\n\n")
        for mf in MANUAL_FEATURES:
            f.write(f"- {mf}\n")
        f.write("\n## 汇总\n\n")
        f.write(f"- 总用例：{result.testsRun} | 通过：{len(result.passed)} | 失败：{len(result.failures)} | 错误：{len(result.errors)} | 跳过：{len(result.skipped)}\n")

    print("\n" + "=" * 78)
    print(f"覆盖报告已生成: {report_path}")
    print("%-42s %6s %6s %6s %6s %6s" % ("场景", "用例", "通过", "失败", "跳过", "状态"))  # noqa: UP031
    print("-" * 78)
    for feature, total, passed, failed, skipped, st in rows:
        print("%-42s %6d %6d %6d %6d %6s" % (feature[:42], total, passed, failed, skipped, st))  # noqa: UP031
    print("-" * 78)
    print(f"总用例: {result.testsRun} | 通过: {len(result.passed)} | 失败: {len(result.failures)} | 错误: {len(result.errors)} | 跳过: {len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
