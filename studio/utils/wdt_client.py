# -*- coding: utf-8 -*-
"""
旺店通 ERP OpenAPI2 客户端（纯 Python，仅依赖标准库）。

签名算法移植自 ai_skills/Automated_Listing_Skill/erp/wdt_client.py，
接口文档：https://open.wangdian.cn/open/apidoc
本模块只实现知识库需要的「库存查询 stock_query」。
"""
import os
import json
import time
import hashlib
import urllib.parse
import urllib.request
import urllib.error

from config.paths import PROJECT_ROOT

# 凭据配置文件（JSON）。默认填旺店通官方沙箱账号，正式使用请替换为生产 appkey/secret/sid。
ERP_CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "erp_config.json")

_DEFAULT_CONFIG = {
    "base_url": "https://api.wangdian.cn/openapi2/",
    "appkey": "wdt112233-jd",
    "appsecret": "7f432fcbcf8bd325ee23bc7453169d92",
    "sid": "wdt112233",
}


def load_erp_config():
    """读取 ERP 凭据配置；不存在则写入沙箱默认值并返回。"""
    try:
        if os.path.exists(ERP_CONFIG_FILE):
            with open(ERP_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return {**_DEFAULT_CONFIG, **(cfg or {})}
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(ERP_CONFIG_FILE), exist_ok=True)
        with open(ERP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(_DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return dict(_DEFAULT_CONFIG)


class WdtClient:
    def __init__(self, base_url=None, appkey=None, appsecret=None, sid=None):
        cfg = load_erp_config()
        self.base_url = (base_url or cfg["base_url"]).rstrip("/") + "/"
        self.appkey = appkey or cfg["appkey"]
        self.appsecret = appsecret or cfg["appsecret"]
        self.sid = sid or cfg["sid"]

    def _sign(self, params):
        parts = []
        for key in sorted(params.keys()):
            if key == "sign":
                continue
            val = str(params[key])
            parts.append(f"{len(key):02d}-{key}:{len(val):04d}-{val}")
        query_str = ";".join(parts) + self.appsecret
        return hashlib.md5(query_str.encode("utf-8")).hexdigest()

    def call_api(self, api_method, params=None):
        req = {k: str(v) for k, v in (params or {}).items()}
        req["appkey"] = self.appkey
        req["sid"] = self.sid
        req["timestamp"] = str(int(time.time()))
        req["format"] = "json"
        req["v"] = "1.0"
        req["sign"] = self._sign(req)

        url = self.base_url + api_method + ".php"
        data = urllib.parse.urlencode(req).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {"code": -1, "message": f"网络请求失败: {e}"}
        except Exception as e:
            return {"code": -1, "message": str(e)}

    def stock_query(self, page_no=0, page_size=100, warehouse_no=None,
                    start_time=None, end_time=None):
        """库存查询（以仓库为维度的 SKU 库存量）。"""
        params = {"page_no": page_no, "page_size": page_size}
        if warehouse_no:
            params["warehouse_no"] = warehouse_no
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self.call_api("stock_query", params)

    def goods_query(self, page_no=0, page_size=100, start_time=None, end_time=None):
        """货品档案查询。注意：start_time/end_time 必填，且时间跨度不能超过约 1 个月。"""
        params = {"page_no": page_no, "page_size": page_size}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self.call_api("goods_query", params)

    def fetch_goods_class_map(self, needed_goods_no=None, months_back=18,
                              window_days=30, page_size=100, progress_cb=None):
        """
        构建 goods_no -> {"category": class_name, "brand": brand_name} 映射，用于补全品类。

        goods_query 按修改时间过滤且单次时间跨度上限约 1 个月，故按 window_days 的时间窗
        从当前向前回溯 months_back 个月逐窗拉取。
        若给定 needed_goods_no（集合），一旦全部命中即提前结束。
        返回 (mapping, error)。
        """
        import datetime as _dt
        needed = set(needed_goods_no) if needed_goods_no else None
        mapping = {}
        end = _dt.datetime.now()
        earliest = end - _dt.timedelta(days=int(months_back * 30))
        cursor = end
        fmt = "%Y-%m-%d %H:%M:%S"
        while cursor > earliest:
            win_start = max(cursor - _dt.timedelta(days=window_days), earliest)
            st, et = win_start.strftime(fmt), cursor.strftime(fmt)
            page_no = 0
            total = None
            collected = 0
            while True:
                resp = self.goods_query(page_no=page_no, page_size=page_size, start_time=st, end_time=et)
                if resp.get("code") != 0:
                    # 时间窗内无数据等业务错误不致命，跳过本窗
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
                if progress_cb:
                    try:
                        progress_cb(len(mapping))
                    except Exception:
                        pass
                if not goods or (total and collected >= total):
                    break
                page_no += 1
            if needed is not None and needed.issubset(mapping.keys()):
                break
            cursor = win_start
        return mapping, None

    def fetch_all_stocks(self, page_size=100, warehouse_no=None, progress_cb=None):
        """
        分页拉取全部库存记录。
        progress_cb(fetched, total) 可选，用于上报进度。
        返回 (records, error)：error 为 None 表示成功。
        """
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
                try:
                    progress_cb(len(records), total)
                except Exception:
                    pass
            if not batch or (total and len(records) >= total):
                break
            page_no += 1
        return records, None


def map_stocks_to_kb(stock_records):
    """
    把 stock_query 返回的原始记录映射并按 spec_no 聚合成知识库条目。
    同一 SKU（spec_no）跨多仓时，库存量求和，仓库名合并。
    返回 KB 字段 dict 列表。
    """
    def to_num(v):
        try:
            return float(str(v).strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    def fmt(n):
        # 去掉无意义的小数（371.0000 -> 371）
        return str(int(n)) if abs(n - int(n)) < 1e-6 else f"{n:.4f}".rstrip("0").rstrip(".")

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
        a["_stock"] += to_num(r.get("stock_num"))
        a["_avail"] += to_num(r.get("avaliable_num"))  # 注意：旺店通字段拼写为 avaliable
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
            "stock_num": fmt(a["_stock"]),
            "available_num": fmt(a["_avail"]),
            "warehouse": "、".join(a["_warehouses"]),
        })
    return out
