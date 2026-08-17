#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缁熶竴娴嬭瘯鍏ュ彛 + 鍦烘櫙瑕嗙洊搴︽姤鍛娿€?

鐢ㄦ硶锛堟帹鑽愮敤搴旂敤鍚屾 python_embeded 杩愯锛?
    python tests/run_all.py                 # 绂荤嚎锛氬崟鍏?+ 闈欐€?+ 鏍锋湰
    python tests/run_all.py --online        # 鍔犱笂鍦ㄧ嚎闆嗘垚娴嬭瘯锛堟湇鍔＄/Ollama锛?
    python tests/run_all.py --category unit # 鍙窇鏌愮被

杈撳嚭:
    鎺у埗鍙版眹鎬?+ tests/report/coverage_report.md锛堝姛鑳矫楁祴璇曡鐩栫煩闃碉級
"""
import argparse
import datetime
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS_DIR, "lib"))

# 鍔熻兘 鈫?娴嬭瘯绫诲悕锛堢敤浜庤鐩栧害鎶ュ憡锛?
FEATURES = [
    ("閰嶇疆璇诲啓 (config_manager)", ["TestConfigManager"]),
    ("鍝佺墝褰掍竴鍖?(brand_normalizer)", ["TestBrandNormalizer"]),
    ("鏋侀檺璇嶆娴?(extreme_words)", ["TestExtremeWords"]),
    ("璺緞涓庣洰褰曠粨鏋?(config.paths)", ["TestPaths"]),
    ("纭欢缂栫爜鍙傛暟 (hwaccel)", ["TestHwaccelArgs"]),
    ("闀滃ご鍒嗘瀽缂撳瓨 (shot_analysis_cache)", ["TestShotAnalysisCache"]),
    ("鎶栭煶瑙嗛瑙ｆ瀽 (douyin_parser)", ["TestDouyinParser"]),
    ("鏁版嵁澶囦唤 (backup_manager)", ["TestBackupManager"]),
    ("鏈湴鎶€鑳藉畨瑁?(skill_manager)", ["TestSkillManager"]),
    ("鑷姩涓婃灦鏁版嵁鍖呮牎楠?(auto_listing)", ["TestAutoListingValidation"]),
    ("璇硶/瀵煎叆鍋ュ悍 (鍏ㄩ儴 studio)", ["TestSyntaxImports"]),
    ("UI 闈欐€佸洖褰?(灏辩华/甯冨眬/鍒嗛暅JSON)", ["TestUIRegression"]),
    ("鏈畾涔夊悕闈欐€佹鏌?(AST, 鍏?studio)", ["TestUndefinedNames"]),
    ("鏍锋湰鏁版嵁鏈夋晥鎬?, ["TestSampleFiles"]),
    ("涓€閿垚鐗囩绾?(video_compiler)", ["TestVideoCompilerPure", "TestCompileVideoSmoke"]),
    ("鏅鸿兘娣峰壀鏈嶅姟绔嫾鎺?Worker锛堢绾?mock锛?, ["TestMontageConcatWorker"]),
    ("浠跨垎娆惧鎴风锛坴iral_clone_client锛岀绾?mock锛?, ["TestViralCloneAnalyze", "TestViralClonePlan", "TestViralCloneFlow", "TestViralCloneSource", "TestViralCloneAssetBrowser", "TestViralCloneRun", "TestViralClonePlaceholders"]),
    ("客户端任务下发闭环（client_task_worker，离线 mock）", ["TestPickup", "TestReport", "TestExecute"]),
    ("鏅鸿兘娣峰壀闀滃ご鍒嗗壊锛堝湪绾?/montage/split锛?, ["TestMontageSplitOnline"]),
    ("Ollama 鍥剧墖璇嗗埆锛堝湪绾匡級", ["TestOllamaImageRecognition"]),
    ("Ollama 瑙嗛鍒嗘瀽锛堝湪绾匡級", ["TestOllamaVideo"]),
    ("鏈嶅姟绔繛閫氭€э紙鍦ㄧ嚎锛?, ["TestServerConnectivity"]),
]

# 鏈夎鍒掍絾灏氭湭鑷姩鍖栫殑鍦烘櫙锛堟潵鑷?docs/TEST_PLAN.md锛?
MANUAL_FEATURES = [
    "鏅鸿兘娣峰壀瀹屾暣娴佺▼锛堢湡瀹炲闀滃ご鎷兼帴鍥炲綊锛岄渶澶ф牱鏈?鏈嶅姟绔紝鑷姩鍖栦粎瑕嗙洊 worker 涓?/montage/split 鍐掔儫锛?,
    "鍘诲瓧骞?鍘绘按鍗颁笌 OCR 鏈嶅姟绔祦绋嬶紙渚濊禆鏈嶅姟绔彲鐢級",
    "绱犳潗妫€绱?浜у搧搴撴湇鍔＄鎺ュ彛鍏ㄩ噺锛?material/*锛?,
    "涓€閿垚鐗?鑴氭湰鎴愮墖绔埌绔?,
    "LLM 鍘嬪姏娴嬭瘯 10骞跺彂脳50锛坱ests/stress_llm.py 鎵嬪伐鎵ц锛?,
    "璧勬簮鍗犵敤/闀挎椂杩愯娉勬紡妫€鏌?,
    "UI 鍝嶅簲鏃堕棿/鍗￠】",
]


class CollectResult(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def _class_of(test_id):
    parts = test_id.split(".")
    return parts[-2] if len(parts) >= 2 else "?"


def _status(total, passed, failed, skipped, errors):
    if failed or errors:
        return "澶辫触"
    if passed == total and total > 0:
        return "閫氳繃"
    if skipped == total:
        return "璺宠繃"
    return "閮ㄥ垎"


def main():
    ap = argparse.ArgumentParser(description="宸ョ▼缁熶竴娴嬭瘯鍏ュ彛")
    ap.add_argument("--online", action="store_true", help="鍖呭惈鍦ㄧ嚎闆嗘垚娴嬭瘯")
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
            mod_name = "%s.%s" % (d, f[:-3])
            spec = importlib.util.spec_from_file_location(mod_name, os.path.join(dir_path, f))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            suite.addTests(loader.loadTestsFromModule(mod))

    print("=" * 78)
    print("TinTin_AI_Agent_Main 娴嬭瘯濂椾欢 | %s | 绫诲埆: %s%s" % (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.category, " (+鍦ㄧ嚎)" if args.online else ""))
    print("=" * 78)
    runner = unittest.TextTestRunner(resultclass=CollectResult, verbosity=1)
    result = runner.run(suite)

    # ---- 瑕嗙洊搴︽姤鍛?----
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

    covered = sum(1 for _, _, _, _, _, st in rows if st in ("閫氳繃", "閮ㄥ垎"))
    report_path = os.path.join(TESTS_DIR, "report", "coverage_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 娴嬭瘯鍦烘櫙瑕嗙洊搴︽姤鍛奬n\n")
        f.write("- 鐢熸垚鏃堕棿锛?s\n" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        f.write("- 杩愯鏂瑰紡锛?s\n\n" % ("--online锛堝惈鍦ㄧ嚎闆嗘垚锛? if args.online else "绂荤嚎锛堝崟鍏?闈欐€?鏍锋湰锛?))
        f.write("## 鑷姩鍖栬鐩栫煩闃礬n\n")
        f.write("| 鍦烘櫙 | 鐢ㄤ緥鏁?| 閫氳繃 | 澶辫触 | 璺宠繃 | 鐘舵€?|\n|---|---|---|---|---|---|\n")
        for feature, total, passed, failed, skipped, st in rows:
            f.write("| %s | %d | %d | %d | %d | %s |\n" % (feature, total, passed, failed, skipped, st))
        f.write("\n- 宸茶嚜鍔ㄥ寲瑕嗙洊鍦烘櫙锛?d / %d\n" % (covered, len(rows)))
        f.write("\n## 灏氭湭鑷姩鍖栫殑鍦烘櫙锛堟潵鑷?docs/TEST_PLAN.md锛岄渶鎵嬪伐/鍚庣画琛ワ級\n\n")
        for mf in MANUAL_FEATURES:
            f.write("- %s\n" % mf)
        f.write("\n## 姹囨€籠n\n")
        f.write("- 鎬荤敤渚嬶細%d | 閫氳繃锛?d | 澶辫触锛?d | 閿欒锛?d | 璺宠繃锛?d\n" % (
            result.testsRun, len(result.passed), len(result.failures), len(result.errors), len(result.skipped)))

    print("\n" + "=" * 78)
    print("瑕嗙洊搴︽姤鍛婂凡鐢熸垚: %s" % report_path)
    print("%-42s %6s %6s %6s %6s %6s" % ("鍦烘櫙", "鐢ㄤ緥", "閫氳繃", "澶辫触", "璺宠繃", "鐘舵€?))
    print("-" * 78)
    for feature, total, passed, failed, skipped, st in rows:
        print("%-42s %6d %6d %6d %6d %6s" % (feature[:42], total, passed, failed, skipped, st))
    print("-" * 78)
    print("鎬荤敤渚? %d | 閫氳繃: %d | 澶辫触: %d | 閿欒: %d | 璺宠繃: %d" % (
        result.testsRun, len(result.passed), len(result.failures), len(result.errors), len(result.skipped)))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

