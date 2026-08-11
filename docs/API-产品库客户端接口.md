# 产品资料库 — 客户端接口文档

> 基础路径：`http://<SERVER_IP>:8000/api/product-library`  
> 所有接口均无需鉴权（已在服务端中间件白名单中放行 `/api/product-library/` 前缀）  
> 响应格式：JSON（UTF-8）

---

## 一、客户端专用接口（`/client/` 前缀）

### 1.1 获取 ERP 配置

客户端从服务端统一获取旺店通 ERP 凭据，无需本地维护 `erp_config.json`。

```
GET /api/product-library/client/erp-config
```

**请求参数：** 无

**响应示例：**

```json
{
  "ok": true,
  "configured": true,
  "erp": {
    "base_url": "https://api.wangdian.cn/openapi2/",
    "appkey": "wdt112233-jd",
    "appsecret": "7f432fcbcf8bd325ee23bc7453169d92",
    "sid": "wdt112233"
  }
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 请求是否成功 |
| `configured` | bool | 服务端是否已配置 ERP（appkey 非空） |
| `erp.base_url` | string | 旺店通 OpenAPI2 基地址 |
| `erp.appkey` | string | 应用 Key |
| `erp.appsecret` | string | 应用密钥（完整明文） |
| `erp.sid` | string | 商家编号 |

**客户端用法：** 用返回的 4 个字段初始化本地 `WdtClient`，即可直接调用旺店通 API。

---

### 1.2 测试 ERP 连接

验证服务端当前 ERP 凭据是否有效（实际调用旺店通 `stock_query` 接口）。

```
POST /api/product-library/client/erp-test
```

**请求参数：** 无（使用服务端已保存的配置）

**响应示例（成功）：**

```json
{
  "ok": true,
  "message": "连接成功，库存记录总数: 1526"
}
```

**响应示例（失败）：**

```json
{
  "ok": false,
  "message": "appkey不存在",
  "code": 1001
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | ERP 是否连通 |
| `message` | string | 人类可读的结果描述 |
| `code` | int | 旺店通错误码（仅失败时返回） |

---

### 1.3 批量拉取产品数据

支持**增量同步**（按 `updated_since` 时间戳过滤）和分页。

```
GET /api/product-library/client/products
```

**Query 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `updated_since` | int | `0` | Unix 时间戳。只返回 `updated_at > 此值` 的条目。传 `0` 表示全量拉取 |
| `category` | string | `""` | 品类筛选（精确匹配），空字符串不筛选 |
| `brand` | string | `""` | 品牌筛选（精确匹配），空字符串不筛选 |
| `page` | int | `1` | 页码（从 1 开始） |
| `page_size` | int | `200` | 每页条数（1~1000） |

**请求示例：**

```
GET /api/product-library/client/products?updated_since=1752000000&page_size=500
```

**响应示例：**

```json
{
  "ok": true,
  "items": [
    {
      "id": "a1b2c3d4e5f60718",
      "category": "鼠标",
      "brand": "罗技",
      "model": "G PRO X SUPERLIGHT 2",
      "goods_no": "LG-GPXSL2",
      "spec_no": "LG-GPXSL2-BK",
      "spec_name": "黑色",
      "barcode": "6970986123456",
      "stock_num": "128",
      "available_num": "115",
      "warehouse": "主仓、华东仓",
      "notes": "",
      "features": "- 重量：60g\n- 传感器：HERO 2\n- DPI：100-32000",
      "selling_points": "- 超轻 60g 设计\n- HERO 2 旗舰传感器\n- 95 小时续航",
      "created_at": 1751900000,
      "updated_at": 1752050000
    }
  ],
  "total": 356,
  "page": 1,
  "page_size": 500,
  "server_time": 1752100000
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 请求是否成功 |
| `items` | array | 产品条目列表（结构见下方「产品条目字段」） |
| `total` | int | 满足条件的总条数（用于分页计算） |
| `page` | int | 当前页码 |
| `page_size` | int | 每页条数 |
| `server_time` | int | 服务端当前 Unix 时间戳（客户端下次增量同步用此值） |

**增量同步建议流程：**

```python
# 客户端本地记录上次同步时间
last_sync = load_local("last_sync_time", 0)

# 拉取增量
resp = requests.get(f"{SERVER}/api/product-library/client/products",
                    params={"updated_since": last_sync, "page_size": 1000})
data = resp.json()

# 更新本地数据
for item in data["items"]:
    upsert_local_product(item)

# 保存同步时间（用 server_time 而非本地时间，避免时钟偏差）
save_local("last_sync_time", data["server_time"])
```

---

### 1.4 获取单个产品详情

返回单条产品完整信息，附带 `prompt_text`（可直接注入 LLM prompt）。

```
GET /api/product-library/client/product/{item_id}
```

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `item_id` | string | 产品 ID（16 位十六进制） |

**响应示例：**

```json
{
  "ok": true,
  "item": {
    "id": "a1b2c3d4e5f60718",
    "category": "鼠标",
    "brand": "罗技",
    "model": "G PRO X SUPERLIGHT 2",
    "goods_no": "LG-GPXSL2",
    "spec_no": "LG-GPXSL2-BK",
    "spec_name": "黑色",
    "barcode": "6970986123456",
    "stock_num": "128",
    "available_num": "115",
    "warehouse": "主仓、华东仓",
    "notes": "",
    "features": "- 重量：60g\n- 传感器：HERO 2",
    "selling_points": "- 超轻 60g 设计\n- HERO 2 旗舰传感器",
    "created_at": 1751900000,
    "updated_at": 1752050000,
    "prompt_text": "品类：鼠标\n品牌：罗技\n型号/货品名称：G PRO X SUPERLIGHT 2\n商家编码：LG-GPXSL2\n规格编码：LG-GPXSL2-BK\n规格名称：黑色\n条形码：6970986123456\n库存量：128\n可用库存：115\n仓库：主仓、华东仓\n性能参数：- 重量：60g\n- 传感器：HERO 2\n核心卖点：- 超轻 60g 设计\n- HERO 2 旗舰传感器"
  }
}
```

**错误响应（404）：**

```json
{
  "detail": "条目不存在"
}
```

---

## 二、产品条目字段说明

所有产品接口返回的 `item` 对象结构统一：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `id` | string | 唯一标识（16位 hex） | 系统生成 |
| `category` | string | 品类（鼠标/键盘等） | 货品档案/手动 |
| `brand` | string | 品牌 | ERP 同步 |
| `model` | string | 型号/货品名称 | ERP 同步 |
| `goods_no` | string | 商家编码 | ERP 同步 |
| `spec_no` | string | 规格编码（SKU 唯一键） | ERP 同步 |
| `spec_name` | string | 规格名称（颜色/版本等） | ERP 同步 |
| `barcode` | string | 条形码 | ERP 同步 |
| `stock_num` | string | 库存量（多仓汇总） | ERP 同步 |
| `available_num` | string | 可用库存 | ERP 同步 |
| `warehouse` | string | 仓库名（多仓用「、」分隔） | ERP 同步 |
| `notes` | string | 备注 | 手动编辑 |
| `features` | string | 性能参数（Markdown） | AI 挖掘/手动 |
| `selling_points` | string | 核心卖点（Markdown） | AI 挖掘/手动 |
| `created_at` | int | 创建时间（Unix 时间戳） | 系统 |
| `updated_at` | int | 最后更新时间（Unix 时间戳） | 系统 |

---

## 三、其他可用接口（客户端也可调用）

以下接口虽非 `/client/` 前缀，但客户端同样可以调用：

### 3.1 触发 ERP 同步

```
POST /api/product-library/sync
```

触发服务端从旺店通仓库全量同步库存数据到数据库。同一时间只允许一个同步任务。

**响应：**
```json
{"ok": true, "message": "同步已启动"}
```

**冲突响应（409）：**
```json
{"detail": "同步正在进行中，请等待完成"}
```

---

### 3.2 查询同步进度

```
GET /api/product-library/sync/status
```

**响应示例：**
```json
{
  "running": true,
  "phase": "正在获取品类... 已识别 42 个货品",
  "fetched": 800,
  "total": 1526,
  "added": 120,
  "updated": 680,
  "error": "",
  "started_at": 1752100000,
  "finished_at": 0
}
```

| 字段 | 说明 |
|------|------|
| `running` | 是否正在运行 |
| `phase` | 当前阶段描述 |
| `fetched` / `total` | 已拉取 / 总记录数 |
| `added` / `updated` | 新增 / 更新条数 |
| `error` | 错误信息（空字符串=无错误） |
| `started_at` / `finished_at` | 开始/结束时间戳 |

---

### 3.3 关键词搜索

```
GET /api/product-library/search?q=罗技&limit=50
```

在品牌、型号、规格编码、商家编码、条形码、备注中模糊搜索。

---

### 3.4 品类列表

```
GET /api/product-library/categories
```

**响应：**
```json
{"categories": ["鼠标", "键盘", "耳机", "摄像头"]}
```

---

### 3.5 品牌列表

```
GET /api/product-library/brands?category=鼠标
```

**响应：**
```json
{"brands": ["罗技", "雷蛇", "卓威", "赛睿"]}
```

---

### 3.6 产品库统计

```
GET /api/product-library/stats
```

**响应：**
```json
{"total": 356, "with_features": 210, "with_category": 340}
```

---

## 四、客户端集成示例（Python）

```python
"""产品库客户端 SDK 最小示例"""
import requests
import json
import os

SERVER = "http://192.168.111.17:8000"
LOCAL_CACHE = "product_cache.json"


class ProductLibraryClient:
    """服务端产品资料库客户端"""

    def __init__(self, server_url: str):
        self.base = server_url.rstrip("/") + "/api/product-library"

    # ─── ERP 配置 ─────────────────────────────
    def get_erp_config(self) -> dict:
        """获取 ERP 凭据（用于本地初始化 WdtClient）"""
        r = requests.get(f"{self.base}/client/erp-config", timeout=10)
        data = r.json()
        return data.get("erp", {})

    def test_erp_connection(self) -> dict:
        """测试服务端 ERP 连接"""
        r = requests.post(f"{self.base}/client/erp-test", timeout=30)
        return r.json()

    # ─── 产品数据 ─────────────────────────────
    def sync_products(self, updated_since: int = 0) -> list:
        """增量拉取所有产品（自动翻页）"""
        all_items = []
        page = 1
        while True:
            r = requests.get(f"{self.base}/client/products", params={
                "updated_since": updated_since,
                "page": page,
                "page_size": 500,
            }, timeout=30)
            data = r.json()
            all_items.extend(data.get("items", []))
            if len(all_items) >= data.get("total", 0):
                break
            page += 1
        return all_items

    def get_product(self, item_id: str) -> dict:
        """获取单个产品详情（含 prompt_text）"""
        r = requests.get(f"{self.base}/client/product/{item_id}", timeout=10)
        if r.status_code == 404:
            return None
        return r.json().get("item")

    def search(self, keyword: str, limit: int = 50) -> list:
        """关键词搜索"""
        r = requests.get(f"{self.base}/search", params={"q": keyword, "limit": limit}, timeout=10)
        return r.json().get("items", [])

    def get_categories(self) -> list:
        r = requests.get(f"{self.base}/categories", timeout=10)
        return r.json().get("categories", [])

    def get_brands(self, category: str = "") -> list:
        r = requests.get(f"{self.base}/brands", params={"category": category}, timeout=10)
        return r.json().get("brands", [])

    # ─── 同步控制 ─────────────────────────────
    def trigger_sync(self) -> dict:
        """触发服务端 ERP 全量同步"""
        r = requests.post(f"{self.base}/sync", timeout=10)
        return r.json()

    def sync_status(self) -> dict:
        """查询同步进度"""
        r = requests.get(f"{self.base}/sync/status", timeout=10)
        return r.json()


# ─── 使用示例 ─────────────────────────────────────
if __name__ == "__main__":
    client = ProductLibraryClient(SERVER)

    # 1. 获取 ERP 配置
    erp = client.get_erp_config()
    print(f"ERP 配置: appkey={erp['appkey']}, sid={erp['sid']}")

    # 2. 测试连接
    result = client.test_erp_connection()
    print(f"连接测试: {result['message']}")

    # 3. 增量同步产品
    last_time = 0  # 首次全量
    products = client.sync_products(updated_since=last_time)
    print(f"拉取到 {len(products)} 个产品")

    # 4. 搜索
    results = client.search("罗技")
    for p in results[:5]:
        print(f"  {p['brand']} {p['model']} | 库存: {p['stock_num']}")
```

---

## 五、错误处理

| HTTP 状态码 | 含义 | 处理建议 |
|-------------|------|----------|
| 200 | 成功 | 正常处理 |
| 404 | 资源不存在 | 检查 item_id 是否正确 |
| 409 | 冲突（同步进行中） | 等待后重试 |
| 422 | 参数校验失败 | 检查请求参数 |
| 500 | 服务端内部错误 | 记录日志，联系管理员 |

**超时建议：**
- 配置/搜索类接口：10s
- 产品批量拉取：30s
- ERP 连接测试：60s（需等待旺店通响应）
