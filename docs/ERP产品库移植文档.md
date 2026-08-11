# ERP 产品库逻辑提取 — 客户端→服务端移植参考

## 一、整体架构与数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                        客户端（PySide6 GUI）                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [产品资料页]  ──点击"从仓库同步"──►  StockSyncWorker (QThread)       │
│       │                                    │                        │
│       │                                    ▼                        │
│       │                            WdtClient (ERP HTTP 客户端)       │
│       │                              ├─ fetch_all_stocks()          │
│       │                              └─ fetch_goods_class_map()     │
│       │                                    │                        │
│       │                                    ▼                        │
│       │                          map_stocks_to_kb() 数据映射         │
│       │                                    │                        │
│       │                                    ▼                        │
│       ◄──────────────────  ProductLibraryManager                    │
│                              ├─ upsert_stocks()                     │
│                              ├─ apply_categories()                  │
│                              └─ save() → JSON 文件                  │
│                                                                     │
│  [产品文案页] ──► ProductLibraryManager.search/get/to_prompt_text    │
│  [一键成片页] ──► ProductLibraryManager (选产品 → 匹配素材 → 成片)    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

数据持久化：studio/data/product_library.json（JSON 数组）
ERP 凭据：  studio/config/erp_config.json
```

---

## 二、ERP 凭据配置

**文件路径**: `studio/config/erp_config.json`

```json
{
    "base_url": "https://api.wangdian.cn/openapi2/",
    "appkey": "wdt112233-jd",
    "appsecret": "7f432fcbcf8bd325ee23bc7453169d92",
    "sid": "wdt112233"
}
```

| 字段 | 说明 |
|------|------|
| base_url | 旺店通 OpenAPI2 网关地址，末尾带 `/` |
| appkey | 应用 key（旺店通开放平台分配） |
| appsecret | 签名密钥 |
| sid | 商家账号标识 |

**加载逻辑** (`wdt_client.py:load_erp_config`):
- 文件存在 → 读取 JSON，与默认值合并
- 文件不存在 → 写入沙箱默认值后返回

---

## 三、ERP HTTP 客户端 — `WdtClient`

**源文件**: `studio/utils/wdt_client.py`  
**依赖**: 纯标准库（`urllib`, `hashlib`, `json`, `time`），无第三方依赖

### 3.1 签名算法 `_sign(params)`

旺店通 OpenAPI2 签名规范：

```python
def _sign(self, params):
    parts = []
    for key in sorted(params.keys()):       # 1. 按 key 字母序排序
        if key == "sign":
            continue                         # 2. 跳过 sign 字段本身
        val = str(params[key])
        # 3. 格式: "key长度-key:value长度-value"
        parts.append(f"{len(key):02d}-{key}:{len(val):04d}-{val}")
    query_str = ";".join(parts) + self.appsecret   # 4. 拼接后追加 appsecret
    return hashlib.md5(query_str.encode("utf-8")).hexdigest()  # 5. MD5
```

**签名示例**:
假设 params = `{"appkey": "abc", "sid": "x", "timestamp": "1700000000", "format": "json", "v": "1.0"}`  
排序后拼接: `06-appkey:0003-abc;06-format:0004-json;03-sid:0001-x;09-timestamp:0010-1700000000;01-v:0003-1.0`  
追加 secret → MD5 → 得到 sign 值

### 3.2 通用 API 调用 `call_api(api_method, params)`

```python
def call_api(self, api_method, params=None):
    req = {k: str(v) for k, v in (params or {}).items()}
    req["appkey"] = self.appkey
    req["sid"] = self.sid
    req["timestamp"] = str(int(time.time()))
    req["format"] = "json"
    req["v"] = "1.0"
    req["sign"] = self._sign(req)

    url = self.base_url + api_method + ".php"    # 例: .../openapi2/stock_query.php
    data = urllib.parse.urlencode(req).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

**请求方式**: POST `application/x-www-form-urlencoded`  
**超时**: 60 秒  
**返回**: JSON dict，成功时 `code=0`

### 3.3 库存查询 `stock_query`

```python
def stock_query(self, page_no=0, page_size=100, warehouse_no=None,
                start_time=None, end_time=None):
    params = {"page_no": page_no, "page_size": page_size}
    if warehouse_no: params["warehouse_no"] = warehouse_no
    if start_time:   params["start_time"] = start_time
    if end_time:     params["end_time"] = end_time
    return self.call_api("stock_query", params)
```

**API 端点**: `POST {base_url}/stock_query.php`  
**响应结构**:
```json
{
    "code": 0,
    "total_count": 1234,
    "stocks": [
        {
            "spec_no": "SKU001",
            "spec_name": "黑色 标准版",
            "goods_no": "GD001",
            "goods_name": "XX 无线鼠标",
            "brand_name": "罗技",
            "barcode": "6901234567890",
            "stock_num": 150,
            "avaliable_num": 120,
            "warehouse_name": "主仓",
            "warehouse_no": "WH01"
        }
    ]
}
```

> ⚠️ 注意：旺店通字段拼写为 `avaliable_num`（非 available），这是 ERP 接口原始拼写。

### 3.4 货品档案查询 `goods_query`

```python
def goods_query(self, page_no=0, page_size=100, start_time=None, end_time=None):
    params = {"page_no": page_no, "page_size": page_size}
    if start_time: params["start_time"] = start_time
    if end_time:   params["end_time"] = end_time
    return self.call_api("goods_query", params)
```

**API 端点**: `POST {base_url}/goods_query.php`  
**限制**: `start_time`/`end_time` 必填，时间跨度 ≤ 约 1 个月  
**响应结构**:
```json
{
    "code": 0,
    "total_count": 500,
    "goods_list": [
        {
            "goods_no": "GD001",
            "goods_name": "XX 无线鼠标",
            "class_name": "鼠标",
            "brand_name": "罗技"
        }
    ]
}
```

### 3.5 全量库存拉取 `fetch_all_stocks`

```python
def fetch_all_stocks(self, page_size=100, warehouse_no=None, progress_cb=None):
    records = []
    page_no = 0
    total = None
    while True:
        resp = self.stock_query(page_no=page_no, page_size=page_size, warehouse_no=warehouse_no)
        if resp.get("code") != 0:
            return records, resp.get("message", "未知错误")
        if total is None:
            total = int(resp.get("total_count", 0) or 0)
        batch = resp.get("stocks", []) or []
        records.extend(batch)
        if progress_cb:
            progress_cb(len(records), total)
        if not batch or (total and len(records) >= total):
            break
        page_no += 1
    return records, None   # (records, error)
```

**逻辑**: 无限分页直到 `len(records) >= total_count` 或返回空批次。

### 3.6 品类映射构建 `fetch_goods_class_map`

```python
def fetch_goods_class_map(self, needed_goods_no=None, months_back=18,
                          window_days=30, page_size=100, progress_cb=None):
    """
    构建 goods_no -> {"category": class_name, "brand": brand_name} 映射。
    
    策略：goods_query 单次时间跨度上限约 1 个月，
    所以从当前时间向前回溯 months_back 个月，每次取 window_days 的窗口逐窗拉取。
    若 needed_goods_no 集合全部命中则提前结束。
    """
    needed = set(needed_goods_no) if needed_goods_no else None
    mapping = {}
    end = datetime.now()
    earliest = end - timedelta(days=int(months_back * 30))
    cursor = end
    fmt = "%Y-%m-%d %H:%M:%S"
    
    while cursor > earliest:
        win_start = max(cursor - timedelta(days=window_days), earliest)
        st, et = win_start.strftime(fmt), cursor.strftime(fmt)
        page_no = 0
        total = None
        collected = 0
        while True:
            resp = self.goods_query(page_no=page_no, page_size=page_size,
                                    start_time=st, end_time=et)
            if resp.get("code") != 0:
                break
            if total is None:
                total = int(resp.get("total_count", 0) or 0)
            goods = resp.get("goods_list", []) or []
            for g in goods:
                no = str(g.get("goods_no", "")).strip()
                if no and no not in mapping:
                    mapping[no] = {
                        "category": str(g.get("class_name", "")).strip(),
                        "brand": str(g.get("brand_name", "")).strip(),
                    }
            collected += len(goods)
            if not goods or (total and collected >= total):
                break
            page_no += 1
        # 提前终止：所有需要的 goods_no 都已找到
        if needed is not None and needed.issubset(mapping.keys()):
            break
        cursor = win_start
    return mapping, None
```

**核心策略**: 时间窗口滑动（30天/窗 × 18个月），逐窗分页拉取，命中即停。

---

## 四、数据映射 — `map_stocks_to_kb`

**功能**: 将 `stock_query` 原始记录按 `spec_no`（SKU）聚合，多仓库存求和。

```python
def map_stocks_to_kb(stock_records):
    """
    输入: stock_query 返回的 stocks 列表（同一 SKU 可能出现在多个仓库）
    输出: 按 spec_no 聚合后的 KB 字段 dict 列表
    """
    agg = {}
    for r in stock_records:
        spec_no = str(r.get("spec_no", "")).strip()
        key = spec_no or f"{r.get('brand_name','')}|{r.get('goods_name','')}"
        if key not in agg:
            agg[key] = {
                "brand": str(r.get("brand_name", "")).strip(),
                "model": str(r.get("goods_name", "")).strip(),
                "goods_no": str(r.get("goods_no", "")).strip(),
                "spec_no": spec_no,
                "spec_name": str(r.get("spec_name", "")).strip(),
                "barcode": str(r.get("barcode", "")).strip(),
                "_stock": 0.0,
                "_avail": 0.0,
                "_warehouses": [],
            }
        a = agg[key]
        a["_stock"] += float(r.get("stock_num") or 0)
        a["_avail"] += float(r.get("avaliable_num") or 0)
        wh = str(r.get("warehouse_name", "")).strip()
        if wh and wh not in a["_warehouses"]:
            a["_warehouses"].append(wh)

    out = []
    for a in agg.values():
        out.append({
            "brand": a["brand"],
            "model": a["model"],
            "goods_no": a["goods_no"],
            "spec_no": a["spec_no"],
            "spec_name": a["spec_name"],
            "barcode": a["barcode"],
            "stock_num": fmt(a["_stock"]),       # 去尾零格式化
            "available_num": fmt(a["_avail"]),
            "warehouse": "、".join(a["_warehouses"]),
        })
    return out
```

**聚合规则**:
- 唯一键: `spec_no`（SKU 编码）；无 spec_no 时回退 `brand_name|goods_name`
- 多仓: `stock_num` 求和，`warehouse_name` 合并（顿号分隔）

---

## 五、数据模型 — `ProductLibraryManager`

**源文件**: `studio/utils/product_library_manager.py`  
**持久化**: `studio/data/product_library.json`（JSON 数组）

### 5.1 字段定义

```python
FIELDS = [
    ("category",      "品类",       False),   # 手动/AI归类（鼠标/键盘...）
    ("brand",         "品牌",       False),   # ← stock_query.brand_name
    ("model",         "型号/货品名称", False),  # ← stock_query.goods_name
    ("goods_no",      "商家编码",    False),   # ← stock_query.goods_no
    ("spec_no",       "规格编码",    False),   # ← stock_query.spec_no（SKU唯一键）
    ("spec_name",     "规格名称",    False),   # ← stock_query.spec_name
    ("barcode",       "条形码",      False),   # ← stock_query.barcode
    ("stock_num",     "库存量",      False),   # ← Σ stock_query.stock_num
    ("available_num", "可用库存",    False),   # ← Σ stock_query.avaliable_num
    ("warehouse",     "仓库",       False),   # ← stock_query.warehouse_name
    ("notes",         "备注",       True),    # 手动
    ("features",      "性能参数",    True),    # AI挖掘/手动
    ("selling_points","核心卖点",    True),    # AI挖掘/手动
]

REQUIRED_FIELDS = ("brand", "model")  # 手动新增时必填

# 仓库同步时只覆盖这些字段，其余保留用户手工编辑
WAREHOUSE_FIELDS = (
    "brand", "goods_no", "spec_no", "spec_name",
    "barcode", "stock_num", "available_num", "warehouse",
)
```

### 5.2 单条数据结构

```json
{
    "id": "a1b2c3d4e5f6g7h8",
    "category": "鼠标",
    "brand": "罗技",
    "model": "G502 HERO",
    "goods_no": "GD001",
    "spec_no": "SKU001",
    "spec_name": "黑色 标准版",
    "barcode": "6901234567890",
    "stock_num": "371",
    "available_num": "320",
    "warehouse": "主仓、分仓",
    "notes": "",
    "features": "- 传感器：HERO 25K\n- DPI：100-25600\n- 按键：11个可编程",
    "selling_points": "- 25600 DPI 电竞级传感器\n- 11 个可编程按键\n- 配重可调系统",
    "created_at": 1700000000,
    "updated_at": 1700003600
}
```

### 5.3 仓库同步 Upsert 逻辑

```python
def upsert_stocks(self, mapped_items):
    """
    批量 upsert：以 spec_no 为唯一键
    - 已存在 → 只刷新 WAREHOUSE_FIELDS（保留 category/notes/features/selling_points）
    - 不存在 → 新增
    """
    added = updated = 0
    now = int(time.time())
    for raw in mapped_items:
        data = self._normalize(raw)
        existing = self._find_existing(data)   # 按 spec_no 或 brand+model 匹配
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
```

### 5.4 品类自动归类

```python
def apply_categories(self, goods_map, fill_brand_if_empty=True):
    """
    用 goods_no -> {"category", "brand"} 映射补全品类。
    只填空的 category，不覆盖手工值。
    """
    for it in self.items:
        no = it.get("goods_no", "").strip()
        info = goods_map.get(no)
        if not info: continue
        if not it.get("category", "").strip() and info.get("category"):
            it["category"] = info["category"]
        if fill_brand_if_empty and not it.get("brand", "").strip() and info.get("brand"):
            it["brand"] = info["brand"]
```

### 5.5 去重匹配规则

```python
def _find_existing(self, item):
    """按 规格编码（优先）或 品牌+型号 定位已有条目"""
    spec = item.get("spec_no", "").strip().lower()
    if spec:
        hit = next((it for it in self.items if it.get("spec_no","").strip().lower() == spec), None)
        if hit: return hit
    bm = (item.get("brand","").strip().lower(), item.get("model","").strip().lower())
    return next(
        (it for it in self.items
         if (it.get("brand","").strip().lower(), it.get("model","").strip().lower()) == bm
         and not it.get("spec_no","").strip()),
        None,
    )
```

---

## 六、同步触发流程（GUI 层）

**源文件**: `studio/gui/product_library_page.py`

### 6.1 StockSyncWorker（后台线程）

```python
class StockSyncWorker(BaseWorker):
    phase = Signal(str)              # 阶段文字
    progress = Signal(int, int)      # fetched, total
    finished = Signal(list, dict)    # mapped KB dicts, goods_no->{category,brand}

    def run(self):
        client = WdtClient()
        # Step 1: 拉取全量库存
        self.phase.emit("正在拉取库存...")
        records, err = client.fetch_all_stocks(
            progress_cb=lambda f, t: self.progress.emit(f, t)
        )
        if err:
            self.error.emit(err)
            return
        # Step 2: 映射为 KB 条目
        mapped = map_stocks_to_kb(records)
        # Step 3: 拉取品类映射
        needed = {m.get("goods_no","").strip() for m in mapped if m.get("goods_no","").strip()}
        self.phase.emit("正在获取品类（货品档案）...")
        goods_map, _ = client.fetch_goods_class_map(
            needed_goods_no=needed,
            progress_cb=lambda n: self.phase.emit(f"正在获取品类... 已识别 {n} 个货品"),
        )
        self.finished.emit(mapped, goods_map)
```

### 6.2 同步完成回调

```python
def _on_sync_done(self, mapped_items, goods_map):
    added, updated = self.manager.upsert_stocks(mapped_items)
    categorized = self.manager.apply_categories(goods_map) if goods_map else 0
    # UI 刷新...
```

---

## 七、AI 挖掘（性能参数 + 核心卖点）

**触发**: 产品资料页「⚡ 一键挖掘」按钮

```python
class BulkMineWorker(BaseWorker):
    def run(self):
        from utils.llm_proxy import llm_chat_messages
        
        system_prompt = (
            '你是一个专业的产品规划与营销专家。根据用户提供的产品基本信息，'
            '整理出该产品的【性能参数】与【核心卖点】。\n'
            '严格以纯 JSON 格式输出：\n'
            '{"features": "性能参数（Markdown 列表/表格）",'
            ' "selling_points": "核心卖点（3-5点，Markdown 列表）"}'
        )
        
        for item in items:
            user_prompt = (
                f'品类：{item.get("category","")}\n品牌：{item.get("brand","")}\n'
                f'型号/货品名称：{item.get("model","")}\n规格名称：{item.get("spec_name","")}\n'
                f'备注：{item.get("notes","")}\n\n请挖掘该产品的【性能参数】与【核心卖点】。'
            )
            content = llm_chat_messages(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": user_prompt}],
                model=self.model, temperature=0.7, timeout=60
            )
            # 解析 JSON → 更新 item["features"], item["selling_points"]
```

---

## 八、下游消费方（移植时需对接）

### 8.1 产品文案创作 (`product_script_page.py`)

```python
# 选产品 → 读取 features/selling_points → 组装 prompt → LLM 生成文案
record = self.kb.get(product_id)
product_text = manager.to_prompt_text(record)  # 格式化为 "标签：值" 多行文本
```

`to_prompt_text` 输出示例:
```
品类：鼠标
品牌：罗技
型号/货品名称：G502 HERO
规格名称：黑色 标准版
性能参数：- 传感器：HERO 25K ...
核心卖点：- 25600 DPI 电竞级传感器 ...
```

### 8.2 一键成片 (`compile_video_page.py`)

```python
self._product_mgr = ProductLibraryManager()
# 选产品 → 获取 features/selling_points → 提交服务端成片任务
```

---

## 九、服务端移植建议

### 需要移植的核心模块

| 模块 | 文件 | 移植内容 |
|------|------|----------|
| ERP 客户端 | `studio/utils/wdt_client.py` | `WdtClient` 全部 + `map_stocks_to_kb` |
| 数据管理 | `studio/utils/product_library_manager.py` | `ProductLibraryManager` 全部 |
| AI 挖掘 | `studio/gui/product_library_page.py` | `BulkMineWorker.run` 中的 prompt 逻辑 |

### 服务端 API 设计建议

```
POST /api/product-library/sync          # 触发 ERP 同步（异步任务）
GET  /api/product-library/sync/status    # 查询同步进度
GET  /api/product-library/items          # 列表（支持搜索/分页）
GET  /api/product-library/items/{id}     # 单条详情
PUT  /api/product-library/items/{id}     # 编辑（category/notes/features/selling_points）
POST /api/product-library/items          # 手动新增
DELETE /api/product-library/items/{id}   # 删除
POST /api/product-library/mine           # 触发 AI 批量挖掘
GET  /api/product-library/categories     # 品类列表
GET  /api/product-library/search?q=xxx   # 关键词搜索
```

### 移植注意事项

1. **签名算法不变** — 旺店通 OpenAPI2 签名是固定的，直接搬 `WdtClient._sign`
2. **`avaliable_num` 拼写** — 旺店通接口原始字段就是 `avaliable`（非 available），不要"修正"
3. **时间窗口策略** — `goods_query` 单次跨度 ≤ 1 个月，必须用滑窗回溯
4. **Upsert 语义** — 同步只覆盖 `WAREHOUSE_FIELDS`，用户手工编辑的 category/notes/features/selling_points 不可被覆盖
5. **去重键** — 优先 `spec_no`，回退 `brand + model`（仅对无 spec_no 的条目）
6. **存储替换** — 客户端用 JSON 文件，服务端建议用 PostgreSQL 表（字段与 FIELDS 一一对应）
7. **凭据安全** — `appsecret` 不应暴露给前端，ERP 调用只在服务端执行
8. **并发安全** — 客户端是单线程同步，服务端需考虑多用户同时触发同步的锁/队列

### 数据库表结构建议

```sql
CREATE TABLE product_library (
    id            VARCHAR(16) PRIMARY KEY,
    category      TEXT DEFAULT '',
    brand         TEXT NOT NULL,
    model         TEXT NOT NULL,
    goods_no      TEXT DEFAULT '',
    spec_no       TEXT DEFAULT '',      -- SKU 唯一键
    spec_name     TEXT DEFAULT '',
    barcode       TEXT DEFAULT '',
    stock_num     TEXT DEFAULT '0',
    available_num TEXT DEFAULT '0',
    warehouse     TEXT DEFAULT '',
    notes         TEXT DEFAULT '',
    features      TEXT DEFAULT '',       -- AI 挖掘
    selling_points TEXT DEFAULT '',      -- AI 挖掘
    created_at    BIGINT,
    updated_at    BIGINT
);

CREATE UNIQUE INDEX idx_spec_no ON product_library(spec_no) WHERE spec_no != '';
CREATE INDEX idx_brand_model ON product_library(brand, model);
CREATE INDEX idx_category ON product_library(category);
```

---

## 十、完整同步时序图

```
用户点击"从仓库同步"
       │
       ▼
StockSyncWorker.run()
       │
       ├──► WdtClient.fetch_all_stocks()
       │         │
       │         ├──► stock_query(page_no=0) → 获取 total_count
       │         ├──► stock_query(page_no=1)
       │         ├──► ...
       │         └──► stock_query(page_no=N) → 全部拉完
       │
       ├──► map_stocks_to_kb(records)  → 按 spec_no 聚合
       │
       ├──► WdtClient.fetch_goods_class_map(needed_goods_no)
       │         │
       │         ├──► goods_query(窗口1: 最近30天) → 分页拉取
       │         ├──► goods_query(窗口2: 30-60天前) → ...
       │         ├──► ...（最多回溯 18 个月）
       │         └──► 全部 needed 命中 → 提前终止
       │
       ▼
ProductLibraryManager.upsert_stocks(mapped)
       │  → 按 spec_no 匹配：存在则更新仓库字段，不存在则新增
       ▼
ProductLibraryManager.apply_categories(goods_map)
       │  → 按 goods_no 补全 category（仅填空值）
       ▼
ProductLibraryManager.save()  → 写入 JSON
       │
       ▼
UI 刷新树状列表
```
