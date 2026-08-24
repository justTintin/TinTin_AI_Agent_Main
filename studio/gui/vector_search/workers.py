"""素材检索：所有异步 Worker 类 + 工具函数。"""
import json
import os

import requests.exceptions
from PySide6.QtCore import Signal
from utils import material_client
from utils.base_worker import BaseWorker
from utils.http_client import http_get, http_post


def _get_server_url():
    try:
        import json

        from config.paths import AI_CONFIG_FILE
        if os.path.isfile(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            url = (cfg.get("compute_server_url") or "").strip().rstrip("/")
            if url:
                return url
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def _fmt_ms(ms):
    """毫秒 → m:ss。"""
    total = max(0, int(ms or 0)) // 1000
    return f"{total // 60}:{total % 60:02d}"


class _SearchWorker(BaseWorker):
    """素材检索：有关键词走 /material/search（语义），否则走 /material/list（浏览）。"""
    finished = Signal(list, int)

    def __init__(self, query="", brand="", category="", media_type="", model="", background_type="", source="", limit=50, offset=0):  # noqa: E501
        super().__init__()
        self.query = query
        self.brand = brand
        self.category = category
        self.media_type = media_type
        self.model = model
        self.background_type = background_type
        self.source = source
        self.limit = limit
        self.offset = offset

    def do_work(self):
        try:
            if self.query:
                params = {"query": self.query, "limit": self.limit, "offset": self.offset}  # noqa: E501
                if self.source:
                    params["source"] = self.source
                data = material_client.search(params, timeout=20)
                if data is None:
                    raise RuntimeError("服务端素材检索失败")
                results = data.get("results") or data.get("data") or []
                total = data.get("total") or len(results)
            else:
                params = {"size": self.limit,
                          "page": (self.offset // self.limit) + 1 if self.limit else 1}
                if self.brand:
                    params["brand"] = self.brand
                if self.category:
                    params["category"] = self.category
                if self.media_type:
                    params["media_type"] = self.media_type
                if self.model:
                    params["model"] = self.model
                if self.background_type:
                    params["background_type"] = self.background_type
                if self.source:
                    params["source"] = self.source
                data = material_client.list(params, timeout=20)
                if data is None:
                    raise RuntimeError("服务端素材列表获取失败")
                results = data.get("items") or []
                total = data.get("total") or len(results)
            self.finished.emit(results, int(total))
        except Exception as e:
            self.error.emit(str(e))


class _DistinctLoader(BaseWorker):
    """异步获取字段去重列表（品牌/分类）。"""
    finished = Signal(str, list)  # field, values

    def __init__(self, field):
        super().__init__()
        self.field = field

    def do_work(self):
        try:
            data = material_client.distinct(self.field, timeout=15)
            # 服务端返回 {"values": [...]}，提取 values 数组
            values = data.get("values", []) if isinstance(data, dict) else data or []
            self.finished.emit(self.field, values)
        except Exception:  # 字段去重涉及 HTTP 请求
            self.finished.emit(self.field, [])


class _BrandCountLoader(BaseWorker):
    """批量查询每个品牌在素材库中的素材数量，用于过滤无对应素材的品牌。"""
    finished = Signal(dict)  # {brand: total}

    def __init__(self, brands):
        super().__init__()
        self.brands = list(brands or [])

    def do_work(self):
        from concurrent.futures import ThreadPoolExecutor

        def _count(brand):
            try:
                data = material_client.list({"page": 1, "size": 1, "brand": brand}, timeout=15)  # noqa: E501
                if data is not None:
                    return brand, int((data or {}).get("total") or 0)
            except Exception:  # 品牌数量查询涉及 HTTP 请求
                pass
            return brand, -1

        counts = {}
        try:
            with ThreadPoolExecutor(max_workers=6) as ex:
                for brand, total in ex.map(_count, self.brands):
                    counts[brand] = total
        except Exception:  # 并发执行品牌统计
            counts = dict.fromkeys(self.brands, -1)
        self.finished.emit(counts)


class _NormalizedBrandsLoader(BaseWorker):
    """异步获取归一化品牌列表（/api/product-library/clients/{machine_id}/brands）。

    服务端已对品牌做归一化处理（如 罗技/Logitech -> 罗技(Logitech)），
    素材检索品牌筛选用归一化品牌，替代 /material/distinct 的原始乱值。
    """
    finished = Signal(str, list)  # "brand", values

    def do_work(self):
        try:
            from utils.license import get_machine_id
            mid = get_machine_id() or ""
            if not mid:
                self.error.emit("无法获取机器码（machine_id）")
                return
            url = f"{_get_server_url()}/api/product-library/clients/{mid}/brands"
            resp = http_get(url, timeout=15)
            if resp.status_code == 200:
                values = (resp.json() or {}).get("brands") or []
                self.finished.emit("brand", values)
                return
            self.error.emit(f"品牌接口返回 HTTP {resp.status_code}")
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            self.error.emit(str(e))


class _StatsLoader(BaseWorker):
    """异步获取素材库统计。"""
    finished = Signal(dict)

    def do_work(self):
        try:
            data = material_client.stats(timeout=10)
            self.finished.emit(data or {})
        except Exception:  # 素材统计涉及 HTTP 请求
            self.finished.emit({})


class _ThumbWorker(BaseWorker):
    """单个素材缩略图加载（/material/thumbnail，失败回退 /material/serve）。"""
    finished = Signal(str, bytes)  # material_id, image_bytes

    def __init__(self, material_id):
        super().__init__()
        self.material_id = str(material_id)

    def do_work(self):
        try:
            resp = http_get(material_client.thumbnail_url(self.material_id), timeout=10)
            if resp.status_code != 200 or not resp.content:
                resp = http_get(material_client.serve_url(self.material_id), timeout=10)
            if resp.status_code == 200 and resp.content:
                self.finished.emit(self.material_id, resp.content)
        except requests.exceptions.RequestException:
            pass  # 失败时不 emit finished；BaseWorker.run() 会 emit error，由页面恢复计数


class _FullImageWorker(BaseWorker):
    """原图加载（/material/serve）：预览时用原图，确保清晰度。"""
    finished = Signal(str, bytes)  # material_id, image_bytes

    def __init__(self, material_id):
        super().__init__()
        self.material_id = str(material_id)

    def do_work(self):
        try:
            resp = http_get(material_client.serve_url(self.material_id), timeout=30)
            if resp.status_code == 200 and resp.content:
                self.finished.emit(self.material_id, resp.content)
        except requests.exceptions.RequestException:
            pass


class _PromptWorker(BaseWorker):
    """服务端反推提示词：POST /prompt/image 或 /prompt/video（multipart material_id）。"""
    finished = Signal(str, str, str)  # 正向提示词, 负向提示词, 错误信息

    def __init__(self, material_id, media_type):
        super().__init__()
        self.material_id = str(material_id)
        self.media_type = (media_type or "image").lower()

    def do_work(self):
        endpoint = "video" if self.media_type == "video" else "image"
        url = f"{_get_server_url()}/prompt/{endpoint}"
        try:
            resp = http_post(url, files={"material_id": (None, self.material_id)}, timeout=180)  # noqa: E501
            if resp.status_code != 200:
                self.finished.emit("", "", f"服务端返回 {resp.status_code}")
                return
            data = resp.json() or {}
            prompt = (data.get("prompt") or "").strip()
            neg = (data.get("negative_prompt") or "").strip()
            self.finished.emit(prompt, neg, "")
        except requests.exceptions.RequestException as e:
            self.finished.emit("", "", str(e))


class _PluginListWorker(BaseWorker):
    """异步加载插件列表。"""
    finished = Signal(list)

    def __init__(self, source="plugin", limit=500):
        super().__init__()
        self.source = source
        self.limit = limit

    def do_work(self):
        try:
            from utils import material_client as mc
            data = mc.list_by_source(self.source, {"size": self.limit, "page": 1}, timeout=20)
            if data is None:
                self.finished.emit([])
                return
            items = data.get("items") or data.get("results") or []
            self.finished.emit(items)
        except Exception:
            self.finished.emit([])


class _ImportPluginWorker(BaseWorker):
    """异步执行插件素材导入。"""
    finished = Signal(dict)

    def __init__(self, items):
        super().__init__()
        self.items = list(items)

    def do_work(self):
        from utils import material_client as mc
        results = []
        for item in self.items:
            try:
                pid = str(item.get("id") or item.get("plugin_id") or "")
                url = item.get("url") or item.get("download_url") or ""
                cat = item.get("category") or ""
                tags = item.get("tags") or []
                if not pid and not url:
                    results.append({"item": item, "ok": False, "error": "缺少 id 或 url"})
                    continue
                res = mc.import_plugin(
                    plugin_id=pid or None,
                    url=url or None,
                    category=cat,
                    tags=tags if isinstance(tags, list) else [],
                    timeout=120,
                )
                results.append({"item": item, "ok": bool(res and res.get("ok")),
                                 "material_id": (res or {}).get("material_id", ""),
                                 "error": (res or {}).get("error", "")})
            except Exception as e:
                results.append({"item": item, "ok": False, "error": str(e)})
        self.finished.emit({"results": results, "total": len(self.items),
                             "success": sum(1 for r in results if r.get("ok"))})
