# -*- coding: utf-8 -*-
"""
excel_reader.py
sku.xlsx 唯一读取入口（ExcelReader）及文件/图片辅助工具。
包含：
  - ExcelReader 类（一次性加载 sheet1/sheet2，多次复用）
  - 向后兼容的薄包装函数（_read_title_from_sheet2 等）
  - _collect_main_images / _find_sku_image
  - _structure_all_excel_data / _sync_merchant_code_to_excel
  - 路径解析工具：_resolve_working_dir / _find_latest_batch_dir
"""

import os
import re
import sys
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import LISTING_DATA_DIR

def _resolve_working_dir(input_dir: str) -> str:
    if not input_dir:
        return ""
    if not os.path.isdir(input_dir):
        return ""

    direct_xlsx = os.path.join(input_dir, "sku.xlsx")
    if os.path.isfile(direct_xlsx):
        return input_dir

    for root, _dirs, files in os.walk(input_dir):
        if "sku.xlsx" in files:
            return root
    return input_dir


def _find_latest_batch_dir(shop_keywords) -> str:
    base = (LISTING_DATA_DIR or "").strip()
    if not base or not os.path.isdir(base):
        return ""

    keywords = [k for k in (shop_keywords or []) if isinstance(k, str) and k.strip()]
    keywords.sort(key=len, reverse=True)

    candidates = []
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if not os.path.isdir(p):
            continue
        if keywords and not any(k in name for k in keywords):
            continue
        try:
            mtime = os.path.getmtime(p)
        except Exception:
            mtime = 0
        candidates.append((mtime, p))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1] if candidates else ""


def _collect_main_images(working_dir: str):
    if not working_dir or not os.path.isdir(working_dir):
        return []

    main_dir = os.path.join(working_dir, "主图")
    if not os.path.isdir(main_dir):
        for root, dirs, _files in os.walk(working_dir):
            if "主图" in dirs:
                main_dir = os.path.join(root, "主图")
                break

    if not os.path.isdir(main_dir):
        return []

    def parse_index(filename: str):
        base = os.path.splitext(os.path.basename(filename))[0]
        m = re.search(r"(?:主图[_-]?)?(\\d+)", base)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return 10**9
        return 10**9

    allow_ext = {".png", ".jpg", ".jpeg", ".webp"}
    files = []
    for name in os.listdir(main_dir):
        ext = os.path.splitext(name)[1].lower()
        if ext not in allow_ext:
            continue
        files.append(os.path.join(main_dir, name))

    files.sort(key=lambda p: (parse_index(p), os.path.basename(p).lower()))
    return files


# ---------------------------------------------------------------------------
# ExcelReader: sku.xlsx 的唯一读取入口，一次加载、多次复用
# 解决原来 5 个函数各自打开 sku.xlsx 的浪费
# ---------------------------------------------------------------------------

class ExcelReader:
    """
    封装 sku.xlsx 的所有读取操作。
    构造时一次性加载 sheet1（SKU 表）和 sheet2（属性表），
    后续所有读取操作均在内存中完成，不再重复盘面 IO。
    """

    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.xls_path = ""
        self.sheet1 = None  # pd.DataFrame
        self.sheet2 = None  # pd.DataFrame
        self._load_error = ""

        if not working_dir or not os.path.isdir(working_dir):
            self._load_error = f"工作目录不存在: {working_dir}"
            return

        xls_path = os.path.join(working_dir, "sku.xlsx")
        if not os.path.isfile(xls_path):
            self._load_error = f"未找到 sku.xlsx: {working_dir}"
            return
        self.xls_path = xls_path

        try:
            import pandas as pd
            self.sheet1 = pd.read_excel(xls_path, sheet_name=0)
            self.sheet2 = pd.read_excel(xls_path, sheet_name=1)
        except Exception as e:
            self._load_error = f"读取 sku.xlsx 失败: {e}"
            print(f"[WARN] ExcelReader: {self._load_error}")

    def ok(self) -> bool:
        """Excel 是否成功加载"""
        return self.sheet1 is not None

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def get_title(self) -> str:
        """sheet2 第二列的列名为商品标题"""
        if self.sheet2 is None:
            return ""
        try:
            cols = list(self.sheet2.columns)
            if len(cols) < 2:
                return ""
            title = str(cols[1]).strip()
            if not title or title.lower().startswith("unnamed:"):
                return ""
            return title
        except Exception:
            return ""

    def get_brand(self) -> str:
        """sheet1 中「品牌」列的第一个非空展示名"""
        if self.sheet1 is None:
            return ""
        try:
            if "品牌" not in self.sheet1.columns:
                return ""
            val = self.sheet1["品牌"].dropna().values
            if len(val) == 0:
                return ""
            v = str(val[0]).strip()
            return v if v else ""
        except Exception:
            return ""

    def get_sheet2_value(self, key: str) -> str:
        """sheet2 中按 key（第一列）查找对应的 value（第二列）"""
        if self.sheet2 is None or not key:
            return ""
        try:
            cols = list(self.sheet2.columns)
            if len(cols) < 2:
                return ""
            kcol, vcol = cols[0], cols[1]
            mask = self.sheet2[kcol].astype(str).str.strip() == str(key).strip()
            if not mask.any():
                return ""
            raw = self.sheet2.loc[mask, vcol].iloc[0]
            if raw is None:
                return ""
            v = str(raw).strip()
            return "" if not v or v.lower() == "nan" else v
        except Exception:
            return ""

    def get_sku_image_names(self) -> list:
        """sheet1 中所有 SKU 图片名（去重、保持顺序）"""
        if self.sheet1 is None:
            return []
        try:
            col_name = self._resolve_sku_col()
            if not col_name:
                return []
            out, seen = [], set()
            for raw in self.sheet1[col_name].tolist():
                if raw is None:
                    continue
                v = " ".join(str(raw).strip().split())
                if not v or v.lower() == "nan" or v in seen:
                    continue
                seen.add(v)
                out.append(v)
            return out
        except Exception:
            return []

    def get_sku_to_merchant_code_mapping(self) -> dict:
        """sheet1 中 SKU图片名 -> 商家编码的映射，若 Excel 中没有则回落到 sku_new_codes.json"""
        if self.sheet1 is None:
            return self._read_from_sku_new_codes_json()
        try:
            import pandas as pd
            sku_col = self._resolve_sku_col()
            if not sku_col:
                return self._read_from_sku_new_codes_json()

            code_col = ""
            for candidate in ("修改后的商品编码", "同步后的商家编码"):
                if candidate in self.sheet1.columns:
                    code_col = candidate
                    break
            if not code_col:
                code_like = next((c for c in self.sheet1.columns if isinstance(c, str) and "编码" in c), "")
                code_col = code_like or (self.sheet1.columns[-1] if len(self.sheet1.columns) > 0 else "")
            if not code_col:
                return self._read_from_sku_new_codes_json()

            mapping = {}
            for _, row in self.sheet1.iterrows():
                sku = row.get(sku_col)
                code = row.get(code_col)
                if pd.isna(sku) or pd.isna(code):
                    continue
                sku_str = " ".join(str(sku).strip().split())
                code_str = str(code).strip()
                if sku_str and sku_str.lower() != "nan" and code_str and code_str.lower() != "nan":
                    mapping[sku_str] = code_str

            return mapping if mapping else self._read_from_sku_new_codes_json()
        except Exception:
            return self._read_from_sku_new_codes_json()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _resolve_sku_col(self) -> str:
        """Resolve the actual column name for SKU image names in sheet1."""
        if self.sheet1 is None:
            return ""
        if "ску图片名" in self.sheet1.columns:
            return "ску图片名"
        if "sku图片名" in self.sheet1.columns:
            return "sku图片名"
        sku_like = next(
            (c for c in self.sheet1.columns if isinstance(c, str) and "sku" in c.lower()),
            "",
        )
        if sku_like:
            return sku_like
        if "组合装名称" in self.sheet1.columns:
            return "组合装名称"
        return ""

    def _read_from_sku_new_codes_json(self) -> dict:
        """Fallback: 从 _runs 目录下找最新的 sku_new_codes.json"""
        import json as _json
        run_best, run_best_mtime = "", -1.0
        candidates = [os.path.join(self.working_dir, "sku_new_codes.json")]
        runs_dir = os.path.join(self.working_dir, "_runs")
        if os.path.isdir(runs_dir):
            for root, _dirs, files in os.walk(runs_dir):
                if "sku_new_codes.json" in files:
                    p = os.path.join(root, "sku_new_codes.json")
                    try:
                        mtime = os.path.getmtime(p)
                    except Exception:
                        mtime = 0
                    if mtime > run_best_mtime:
                        run_best_mtime, run_best = mtime, p
        if run_best:
            candidates.insert(0, run_best)
        for p in candidates:
            if not os.path.isfile(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                if not isinstance(data, dict):
                    continue
                details = data.get("明细")
                if not isinstance(details, list):
                    continue
                out = {}
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    new_code = str(item.get("新编码") or "").strip()
                    full = item.get("完整数据") or {}
                    if not isinstance(full, dict):
                        full = {}
                    sku_name = str(full.get("sku图片名") or full.get("组合装名称") or "").strip()
                    if not sku_name:
                        sku_name = next(
                            (str(full.get(k) or "").strip() for k in full if isinstance(k, str) and "sku" in k.lower()),
                            "",
                        )
                    sku_name = " ".join(sku_name.split())
                    if sku_name and new_code:
                        out[sku_name] = new_code
                if out:
                    return out
            except Exception:
                continue
        return {}


# ---------------------------------------------------------------------------
# 向后兼容包装函数（保持原有调用点无需修改）
# 内部均通过 ExcelReader 实例操作，不再直接打开文件
# ---------------------------------------------------------------------------

def _get_excel_reader(working_dir: str) -> "ExcelReader":
    """Convenience factory: always returns an ExcelReader (may be in error state)."""
    return ExcelReader(working_dir)


def _read_title_from_sheet2(working_dir: str) -> str:
    return ExcelReader(working_dir).get_title()


def _read_brand_from_sku(working_dir: str) -> str:
    return ExcelReader(working_dir).get_brand()


def _read_sheet2_value(working_dir: str, key: str) -> str:
    return ExcelReader(working_dir).get_sheet2_value(key)


def _read_sku_image_names_from_sheet1(working_dir: str) -> list:
    return ExcelReader(working_dir).get_sku_image_names()


def _read_sku_to_merchant_code_mapping(working_dir: str) -> dict:
    return ExcelReader(working_dir).get_sku_to_merchant_code_mapping()


def _structure_all_excel_data(working_dir: str):
    """将工作表1和2的数据结构化并保存为 JSON"""
    if not working_dir or not os.path.isdir(working_dir):
        return
    xls_path = ""
    for name in ("sku.xlsx",):
        p = os.path.join(working_dir, name)
        if os.path.isfile(p):
            xls_path = p
            break
    if not xls_path:
        print(f"[WARN] 结构化读取中止：未找到 sku.xlsx 文件: {working_dir}")
        return
    
    try:
        import pandas as pd
        import json
        
        sheet1 = pd.read_excel(xls_path, sheet_name=0).fillna("").to_dict(orient="records")
        sheet2 = pd.read_excel(xls_path, sheet_name=1).fillna("").to_dict(orient="records")
        
        out_json = os.path.join(working_dir, "structured_data.json")
        out_data = {}
        
        if os.path.exists(out_json):
            try:
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        out_data = data
            except Exception as e:
                print(f"[WARN] 读取已有 structured_data.json 失败，将重新创建: {e}")

        out_data["sheet1"] = sheet1
        out_data["sheet2"] = sheet2
        
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已将工作表1和2的数据补充结构化保存至: {out_json}")
    except Exception as e:
        print(f"[WARN] 结构化 Excel 数据失败: {e}")

def _sync_merchant_code_to_excel(working_dir: str, code_mapping: dict):
    """如果有商家编码有修改，同步到 sku.xlsx 的最后一列"""
    if not working_dir or not os.path.isdir(working_dir) or not code_mapping:
        return
    
    xls_path = ""
    for name in ("sku.xlsx",):
        p = os.path.join(working_dir, name)
        if os.path.isfile(p):
            xls_path = p
            break
    if not xls_path:
        print(f"[WARN] 商家编码回写中止：未找到 sku.xlsx 文件: {working_dir}")
        return
        
    try:
        import pandas as pd
        xls = pd.ExcelFile(xls_path)
        sheets = {sheet_name: xls.parse(sheet_name) for sheet_name in xls.sheet_names}
        
        if not sheets:
            return
            
        sheet1_name = xls.sheet_names[0]
        df = sheets[sheet1_name]
        
        sku_col = "sku图片名"
        if sku_col not in df.columns:
            if "组合装名称" in df.columns:
                sku_col = "组合装名称"
            else:
                return
        
        sync_col_name = "同步后的商家编码"
        if sync_col_name not in df.columns:
            df[sync_col_name] = ""
            
        modified = False
        for idx, row in df.iterrows():
            sku = str(row.get(sku_col, "")).strip()
            sku = " ".join(sku.split())
            if sku in code_mapping:
                new_code = str(code_mapping[sku]).strip()
                old_code = str(df.at[idx, sync_col_name]).strip()
                # 即使原列不存在（即 NaN），也会处理为 ''，可以进行对比
                if new_code and new_code != old_code:
                    df.at[idx, sync_col_name] = new_code
                    modified = True
                    
        if modified:
            out_path = os.path.join(working_dir, "sku.xlsx")
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                for sheet_name, sheet_df in sheets.items():
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"[OK] 已将修改后的商家编码同步到 {out_path} 的工作表 '{sheet1_name}' 最后一列")
            
    except Exception as e:
        print(f"[WARN] 同步商家编码到 Excel 失败: {e}")



def _find_sku_image(working_dir: str, sku_name: str) -> str:
    if not working_dir or not sku_name:
        return ""
    sku_dir = os.path.join(working_dir, "sku图")
    if not os.path.isdir(sku_dir):
        for root, dirs, _files in os.walk(working_dir):
            if "sku图" in dirs:
                sku_dir = os.path.join(root, "sku图")
                break
    if not os.path.isdir(sku_dir):
        return ""

    sku_name_clean = str(sku_name).strip()
    allow_ext = {".png", ".jpg", ".jpeg", ".webp"}
    for name in os.listdir(sku_dir):
        base, ext = os.path.splitext(name)
        if ext.lower() not in allow_ext:
            continue
        if base.strip() == sku_name_clean:
            return os.path.join(sku_dir, name)
    
    for name in os.listdir(sku_dir):
        base, ext = os.path.splitext(name)
        if ext.lower() not in allow_ext:
            continue
        if sku_name_clean in base or base in sku_name_clean:
            return os.path.join(sku_dir, name)
    return ""
