# -*- coding: utf-8 -*-
"""
产品资料数据层（服务端存储，通过机器码隔离）。

- 所有数据持久化到服务端，客户端不再写本地 JSON。
- 每台客户端通过机器码（MAC+主机名+CPU 哈希）作为唯一标识。
- 服务端按机器码隔离每台客户端的产品资料数据。
- 读操作优先使用服务端响应；服务端不可达时降级到本地缓存。
- 写操作全部走 HTTP，成功后刷新缓存。

保留的常量：FIELDS, REQUIRED_FIELDS, WAREHOUSE_FIELDS（驱动 GUI 表单与字段归一化）。
"""
import os
import json
import time

from utils.logger_utils import log

# ── 字段常量（驱动 GUI 表单与字段归一化） ──────────────────────────────────
FIELDS = [
    ("category", "品类", False),
    ("brand", "品牌", False),
    ("model", "型号/货品名称", False),
    ("goods_no", "商家编码", False),
    ("spec_no", "规格编码", False),
    ("spec_name", "规格名称", False),
    ("barcode", "条形码", False),
    ("stock_num", "库存量", False),
    ("available_num", "可用库存", False),
    ("warehouse", "仓库", False),
    ("notes", "备注", True),
    ("features", "性能参数", True),
    ("selling_points", "核心卖点", True),
]

REQUIRED_FIELDS = ("brand", "model")

WAREHOUSE_FIELDS = (
    "brand", "goods_no", "spec_no", "spec_name",
    "barcode", "stock_num", "available_num", "warehouse",
)


# ── 配置工具 ────────────────────────────────────────────────────────────────

def _get_server_url() -> str:
    """读取 ai_config.json 中的统一服务端地址。"""
    try:
        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return ""


def _get_machine_id() -> str:
    """获取机器唯一标识（复用 license 模块的机器码算法）。"""
    try:
        from utils.license import get_machine_id
        return get_machine_id()
    except Exception:
        # 降级：用 socket 名哈希
        import hashlib, socket
        return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]


# ── 数据层 ──────────────────────────────────────────────────────────────────

class ProductLibraryManager:
    """产品资料 HTTP 客户端。

    所有数据由服务端存储，客户端通过机器码标识身份。
    读操作：优先服务端，降级到本地缓存。
    写操作：全部走 HTTP，成功后刷新缓存。
    """

    def __init__(self, machine_id=None, file_path=None):
        # file_path 参数为兼容保留，不再使用
        self.machine_id = machine_id or _get_machine_id()
        self.items: list[dict] = []
        self._cache_time: float = 0
        self.load()

    # ── HTTP 底层 ──────────────────────────────────────────────────────────

    def _base(self) -> str:
        return f"{_get_server_url().rstrip('/')}/api/product-library/clients/{self.machine_id}"

    def _headers(self) -> dict:
        return {"X-Machine-ID": self.machine_id, "Content-Type": "application/json"}

    def _http_get(self, path: str, params=None, timeout=10):
        from utils.http_client import http_get
        url = f"{self._base()}{path}"
        try:
            r = http_get(url, headers=self._headers(), params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            log.warning(f"[ProductLib] GET {url} → HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            log.error(f"[ProductLib] GET {url} 失败: {e}")
        return None

    def _http_post(self, path: str, json_data=None, timeout=15):
        from utils.http_client import http_post
        url = f"{self._base()}{path}"
        try:
            r = http_post(url, headers=self._headers(), json=json_data, timeout=timeout)
            if r.status_code in (200, 201):
                return r.json()
            log.error(f"[ProductLib] POST {url} → HTTP {r.status_code}: {r.text[:200]}")
            # 把服务端错误消息返回给调用方
            try:
                err = r.json()
                return {"ok": False, "message": err.get("message") or err.get("detail") or f"HTTP {r.status_code}"}
            except Exception:
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as e:
            log.error(f"[ProductLib] POST {url} 失败: {e}")
            return {"ok": False, "message": f"网络异常: {e}"}

    def _http_put(self, path: str, json_data: dict, timeout=10):
        from utils.http_client import http_put
        url = f"{self._base()}{path}"
        try:
            r = http_put(url, headers=self._headers(), json=json_data, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            log.error(f"[ProductLib] PUT {url} → HTTP {r.status_code}: {r.text[:200]}")
            try:
                err = r.json()
                return {"ok": False, "message": err.get("message") or err.get("detail") or f"HTTP {r.status_code}"}
            except Exception:
                return {"ok": False, "message": f"HTTP {r.status_code}"}
        except Exception as e:
            log.error(f"[ProductLib] PUT {url} 失败: {e}")
            return {"ok": False, "message": f"网络异常: {e}"}

    def _http_delete(self, path: str, timeout=10) -> bool:
        from utils.http_client import http_delete
        url = f"{self._base()}{path}"
        try:
            r = http_delete(url, headers=self._headers(), timeout=timeout)
            if r.status_code == 200:
                return True
            log.warning(f"[ProductLib] DELETE {url} → HTTP {r.status_code}")
        except Exception as e:
            log.error(f"[ProductLib] DELETE {url} 失败: {e}")
        return False

    # ── 持久化 ─────────────────────────────────────────────────────────────

    def load(self):
        """从服务端拉取全量数据到本地缓存。

        服务端 /items 固定只返回前 50 条（limit/offset 参数被忽略），
        而 /grouped 返回全部产品（含 features/selling_points），
        因此用 /grouped 作为全量缓存源，保证树里每个产品都能命中本地缓存。
        """
        data = self._http_get("/grouped", timeout=15)
        if data is not None:
            tree = data.get("tree") if isinstance(data, dict) else None
            if isinstance(tree, dict):
                items = []
                for _cat, brands in tree.items():
                    for _brand, lst in brands.items():
                        items.extend(lst)
                self.items = items
                self._cache_time = time.time()
                return self.items
            self.items = []
            self._cache_time = time.time()
            return self.items
        # 兜底：仍尝试 /items（可能只有前 50 条）
        data = self._http_get("/items", timeout=15)
        if data is not None:
            if isinstance(data, list):
                self.items = data
            elif isinstance(data, dict) and isinstance(data.get("items"), list):
                self.items = data["items"]
            else:
                self.items = []
            self._cache_time = time.time()
        else:
            log.warning("[ProductLib] 服务端不可达，本地缓存为空或保留旧缓存")
            if self._cache_time == 0:
                self.items = []
        return self.items

    # ── 工具 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(data):
        """把任意 dict 规整成只含已知字段的条目（缺失字段补空字符串）。"""
        return {key: str(data.get(key, "") or "").strip() for key, _label, _ml in FIELDS}

    @staticmethod
    def _norm(s):
        return str(s or "").strip().lower()

    # ── 增删改（HTTP） ────────────────────────────────────────────────────

    def add_item(self, data):
        """新增型号。返回 (ok, msg, item)。"""
        item = self._normalize(data)
        missing = [lbl for k, lbl, _ in FIELDS if k in REQUIRED_FIELDS and not item[k]]
        if missing:
            return False, f"必填项不能为空：{'、'.join(missing)}", None
        result = self._http_post("/items", json_data=item)
        if result and result.get("ok"):
            new_item = result.get("item", item)
            self.items.append(new_item)
            return True, result.get("message", "已添加。"), new_item
        return False, result.get("message", "添加失败（服务端错误）。") if result else "服务端不可达。", None

    def update_item(self, item_id, data):
        """修改已有条目。返回 (ok, msg, item)。"""
        new = self._normalize(data)
        missing = [lbl for k, lbl, _ in FIELDS if k in REQUIRED_FIELDS and not new[k]]
        if missing:
            return False, f"必填项不能为空：{'、'.join(missing)}", None
        result = self._http_put(f"/items/{item_id}", json_data=new)
        if result and result.get("ok"):
            target = self.get(item_id)
            if target:
                target.update(new)
                target["updated_at"] = result.get("updated_at", int(time.time()))
            return True, result.get("message", "已保存。"), target
        return False, result.get("message", "保存失败（服务端错误）。") if result else "服务端不可达。", None

    def remove_item(self, item_id):
        """删除条目。返回 True/False。"""
        ok = self._http_delete(f"/items/{item_id}")
        if ok:
            self.items = [it for it in self.items if it.get("id") != item_id]
        return ok

    def get(self, item_id):
        """按 id 查找。"""
        return next((it for it in self.items if it.get("id") == item_id), None)

    # ── 仓库同步（HTTP） ──────────────────────────────────────────────────

    def upsert_stocks(self, mapped_items):
        """批量 upsert 仓库同步来的条目（服务端执行）。返回 (added, updated)。"""
        if not mapped_items:
            return 0, 0
        result = self._http_post("/upsert", json_data={"items": mapped_items}, timeout=60)
        if result and result.get("ok"):
            added = int(result.get("added", 0))
            updated = int(result.get("updated", 0))
            self.load()  # 刷新缓存
            return added, updated
        return 0, 0

    def apply_categories(self, goods_map, fill_brand_if_empty=True):
        """批量补全品类（服务端执行）。返回更新条数。"""
        if not goods_map:
            return 0
        result = self._http_post(
            "/apply-categories",
            json_data={"goods_map": goods_map, "fill_brand_if_empty": fill_brand_if_empty},
            timeout=30,
        )
        if result and result.get("ok"):
            updated = int(result.get("updated", 0))
            self.load()  # 刷新缓存
            return updated
        return 0

    # ── 检索 / 归类 ──────────────────────────────────────────────────────

    def all_items(self):
        """返回所有条目（优先服务端全量 /grouped，降级缓存）。"""
        return list(self.load())

    def categories(self):
        """品类列表。"""
        result = self._http_get("/categories", timeout=5)
        if result and isinstance(result.get("categories"), list):
            return result["categories"]
        # 本地降级
        return sorted({it.get("category", "").strip() for it in self.items if it.get("category", "").strip()})

    def brands(self, category=None):
        """品牌列表。"""
        params = {"category": category or ""}
        result = self._http_get("/brands", params=params, timeout=5)
        if result and isinstance(result.get("brands"), list):
            return result["brands"]
        # 本地降级
        return sorted({
            it.get("brand", "").strip()
            for it in self.items
            if it.get("brand", "").strip() and (category is None or it.get("category", "").strip() == category)
        })

    def search(self, keyword):
        """关键词搜索（优先服务端）。"""
        result = self._http_get("/search", params={"q": keyword}, timeout=8)
        if result and isinstance(result.get("items"), list):
            return result["items"]
        # 本地降级
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
        """返回 {品类: {品牌: [条目...]}} 树状结构（优先服务端）。"""
        result = self._http_get("/grouped", timeout=8)
        if result and isinstance(result.get("tree"), dict):
            return result["tree"]
        # 本地降级
        tree = {}
        for it in self.items:
            cat = it.get("category", "").strip() or "未归类"
            brand = it.get("brand", "").strip() or "未知品牌"
            tree.setdefault(cat, {}).setdefault(brand, []).append(it)
        return tree

    def to_prompt_text(self, item):
        """本地格式化（纯字符串拼接，无需服务端）。"""
        if not item:
            return ""
        lines = []
        for key, label, _ml in FIELDS:
            val = str(item.get(key, "")).strip()
            if val:
                lines.append(f"{label}：{val}")
        return "\n".join(lines)
