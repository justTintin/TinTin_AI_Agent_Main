# -*- coding: utf-8 -*-
"""
产品资料数据层。

把鼠标 / 键盘等外设按「品类 → 品牌 → 型号」统一归类，作为后续 AI 文案创作的
基础数据。基础数据从旺店通 ERP 仓库（库存接口 stock_query）同步而来，
仅保留基础 + 库存字段（暂不含营销字段）。

存储：JSON 文件（config.paths.PRODUCT_LIBRARY_FILE），沿用本项目
account_manager 的「Manager 类 + JSON」持久化模式，不引入数据库。
"""
import os
import json
import time

from config.paths import PRODUCT_LIBRARY_FILE
from utils.logger_utils import log

# 每个型号条目的字段（基础 + 库存）。FIELDS 同时驱动 GUI 表单与仓库同步映射。
# key = 内部字段名，label = 中文显示名，multiline = 是否多行文本。
FIELDS = [
    ("category", "品类", False),         # 鼠标 / 键盘 ...（仓库库存接口无此字段，手动归类）
    ("brand", "品牌", False),            # ← stock_query.brand_name
    ("model", "型号/货品名称", False),    # ← stock_query.goods_name
    ("goods_no", "商家编码", False),      # ← stock_query.goods_no
    ("spec_no", "规格编码", False),       # ← stock_query.spec_no（SKU 唯一键）
    ("spec_name", "规格名称", False),     # ← stock_query.spec_name
    ("barcode", "条形码", False),         # ← stock_query.barcode
    ("stock_num", "库存量", False),       # ← Σ stock_query.stock_num
    ("available_num", "可用库存", False), # ← Σ stock_query.avaliable_num
    ("warehouse", "仓库", False),         # ← stock_query.warehouse_name（多仓汇总）
    ("notes", "备注", True),              # 手动
    ("features", "性能参数", True),        # AI挖掘/手动
    ("selling_points", "核心卖点", True),   # AI挖掘/手动
]

# 必填字段（手动新增时）
REQUIRED_FIELDS = ("brand", "model")

# 由仓库同步覆盖的字段。其余字段保留用户手工编辑、再同步不清掉：
#   category（品类，手工/自动归类）、notes（备注）、model（商品名称/型号，允许手工改名）。
# 注意：本项目只从仓库读取，绝不回写仓库——这些本地编辑不会同步给 ERP。
WAREHOUSE_FIELDS = (
    "brand", "goods_no", "spec_no", "spec_name",
    "barcode", "stock_num", "available_num", "warehouse",
)


class ProductLibraryManager:
    def __init__(self, file_path=None):
        self.file_path = file_path or PRODUCT_LIBRARY_FILE
        self.items = []
        self.load()

    # ---------- 持久化 ----------
    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
            except Exception as e:
                log.error(f"加载产品资料失败: {e}")
                self.items = []
        else:
            self.items = []
        return self.items

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"保存产品资料失败: {e}")

    # ---------- 工具 ----------
    @staticmethod
    def _normalize(data):
        """把任意 dict 规整成只含已知字段的条目（缺失字段补空字符串）。"""
        return {key: str(data.get(key, "") or "").strip() for key, _label, _ml in FIELDS}

    @staticmethod
    def _norm(s):
        return str(s or "").strip().lower()

    # ---------- 增删改查（手动） ----------
    def add_item(self, data):
        """手动新增型号。返回 (ok, msg, item)。"""
        item = self._normalize(data)
        missing = [lbl for k, lbl, _ in FIELDS if k in REQUIRED_FIELDS and not item[k]]
        if missing:
            return False, f"必填项不能为空：{'、'.join(missing)}", None
        if self._find_existing(item):
            return False, "已存在相同 规格编码 或 品牌+型号 的条目，请改用编辑。", None
        item["id"] = os.urandom(8).hex()
        item["created_at"] = item["updated_at"] = int(time.time())
        self.items.append(item)
        self.save()
        return True, "已添加。", item

    def update_item(self, item_id, data):
        target = self.get(item_id)
        if not target:
            return False, "未找到该条目。", None
        new = self._normalize(data)
        missing = [lbl for k, lbl, _ in FIELDS if k in REQUIRED_FIELDS and not new[k]]
        if missing:
            return False, f"必填项不能为空：{'、'.join(missing)}", None
        dup = self._find_existing(new)
        if dup and dup["id"] != item_id:
            return False, "已存在相同 规格编码 或 品牌+型号 的其它条目。", None
        target.update(new)
        target["updated_at"] = int(time.time())
        self.save()
        return True, "已保存。", target

    def remove_item(self, item_id):
        before = len(self.items)
        self.items = [it for it in self.items if it.get("id") != item_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def get(self, item_id):
        return next((it for it in self.items if it.get("id") == item_id), None)

    def _find_existing(self, item):
        """按 规格编码（优先）或 品牌+型号 定位已有条目。"""
        spec = self._norm(item.get("spec_no"))
        if spec:
            hit = next((it for it in self.items if self._norm(it.get("spec_no")) == spec), None)
            if hit:
                return hit
        bm = (self._norm(item.get("brand")), self._norm(item.get("model")))
        return next(
            (it for it in self.items
             if (self._norm(it.get("brand")), self._norm(it.get("model"))) == bm
             and not self._norm(it.get("spec_no"))),
            None,
        )

    # ---------- 仓库同步 ----------
    def upsert_stocks(self, mapped_items):
        """
        批量 upsert 仓库同步来的条目（已映射成 KB 字段的 dict 列表）。
        以 spec_no 为唯一键：已存在则只刷新 WAREHOUSE_FIELDS（保留手工填的 category/notes），
        不存在则新增。返回 (added, updated)。
        """
        added = updated = 0
        now = int(time.time())
        for raw in mapped_items:
            data = self._normalize(raw)
            existing = self._find_existing(data)
            if existing:
                for k in WAREHOUSE_FIELDS:
                    existing[k] = data.get(k, existing.get(k, ""))
                existing["updated_at"] = now
                updated += 1
            else:
                data["id"] = os.urandom(8).hex()
                data["created_at"] = data["updated_at"] = now
                self.items.append(data)
                added += 1
        self.save()
        return added, updated

    def apply_categories(self, goods_map, fill_brand_if_empty=True):
        """
        用 goods_no -> {"category", "brand"} 映射补全品类（仅填空的 category，不覆盖手工值）。
        返回更新条数。
        """
        now = int(time.time())
        updated = 0
        for it in self.items:
            no = self._norm(it.get("goods_no"))
            if not no:
                continue
            info = goods_map.get(it.get("goods_no", "").strip()) or goods_map.get(no)
            if not info:
                continue
            changed = False
            if not it.get("category", "").strip() and info.get("category"):
                it["category"] = info["category"]
                changed = True
            if fill_brand_if_empty and not it.get("brand", "").strip() and info.get("brand"):
                it["brand"] = info["brand"]
                changed = True
            if changed:
                it["updated_at"] = now
                updated += 1
        if updated:
            self.save()
        return updated

    # ---------- 检索 / 归类（供文案创作调用） ----------
    def all_items(self):
        return list(self.items)

    def categories(self):
        return sorted({it.get("category", "").strip() for it in self.items if it.get("category", "").strip()})

    def brands(self, category=None):
        return sorted({
            it.get("brand", "").strip()
            for it in self.items
            if it.get("brand", "").strip() and (category is None or it.get("category", "").strip() == category)
        })

    def search(self, keyword):
        kw = self._norm(keyword)
        if not kw:
            return self.all_items()
        out = []
        for it in self.items:
            blob = " ".join(str(it.get(k, "")) for k, _, _ in FIELDS).lower()
            if kw in blob:
                out.append(it)
        return out

    def grouped(self):
        """返回 {品类: {品牌: [条目...]}}，供 UI 树状展示。"""
        tree = {}
        for it in self.items:
            cat = it.get("category", "").strip() or "未归类"
            brand = it.get("brand", "").strip() or "未知品牌"
            tree.setdefault(cat, {}).setdefault(brand, []).append(it)
        return tree

    def to_prompt_text(self, item):
        """把一个型号条目格式化成可注入 LLM prompt 的产品资料文本。"""
        if not item:
            return ""
        lines = []
        for key, label, _ml in FIELDS:
            val = str(item.get(key, "")).strip()
            if val:
                lines.append(f"{label}：{val}")
        return "\n".join(lines)
