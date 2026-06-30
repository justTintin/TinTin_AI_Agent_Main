"""
wdt_client.py
旺店通ERP API Python客户端
完全使用 Python 原生实现，去除了原本的 Java 依赖，保证跨平台和跨电脑运行。
"""

import hashlib
import time
import urllib.parse
import urllib.request
import json
from typing import Dict, Any, Optional

class WdtClient:
    """旺店通ERP OpenAPI v2 客户端"""

    def __init__(self, base_url: str, appkey: str, appsecret: str, sid: str):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.appkey = appkey
        self.appsecret = appsecret
        self.sid = sid

    def _sign_request(self, params: Dict[str, Any]) -> str:
        keys = sorted(params.keys())
        query = []
        for key in keys:
            if key == "sign":
                continue
            val = str(params[key])
            k_len = len(key)
            # 注意：这里模拟 Java 的 String.length()，对于 BMP 字符，等同于 Python 的 len()
            v_len = len(val)
            query.append(f"{k_len:02d}-{key}:{v_len:04d}-{val}")
            
        query_str = ";".join(query) + self.appsecret
        
        md5 = hashlib.md5()
        md5.update(query_str.encode('utf-8'))
        return md5.hexdigest()

    def call_api(self, api_method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        调用API

        Args:
            api_method: API方法名 (例如 'suites_query')
            params: 业务参数

        Returns:
            API响应字典
        """
        if params is None:
            params = {}

        req_params = {}
        for k, v in params.items():
            req_params[k] = str(v)
            
        req_params["appkey"] = self.appkey
        req_params["sid"] = self.sid
        req_params["timestamp"] = str(int(time.time()))
        req_params["format"] = "json"
        req_params["v"] = "1.0"
        
        req_params["sign"] = self._sign_request(req_params)

        url = self.base_url + api_method + ".php"
        data = urllib.parse.urlencode(req_params).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_text = resp.read().decode('utf-8')
                return json.loads(resp_text)
        except urllib.error.URLError as e:
            return {"code": -1, "message": f"网络请求失败: {e}"}
        except Exception as e:
            return {"code": -1, "message": str(e)}

    def search_combinations(self, page_no: int = 1, page_size: int = 100,
                           start_time: Optional[str] = None,
                           end_time: Optional[str] = None) -> Dict[str, Any]:
        """
        查询组合装商品

        Args:
            page_no: 页码
            page_size: 每页条数
            start_time: 开始时间，格式 yyyy-MM-dd HH:mm:ss
            end_time: 结束时间，格式 yyyy-MM-dd HH:mm:ss

        Returns:
            包含组合装列表的响应
        """
        params = {
            'page_no': str(page_no),
            'page_size': str(page_size)
        }

        if start_time:
            params['start_time'] = start_time
        if end_time:
            params['end_time'] = end_time

        return self.call_api('suites_query', params)
