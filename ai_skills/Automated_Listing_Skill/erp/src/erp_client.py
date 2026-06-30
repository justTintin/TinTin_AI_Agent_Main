"""
erp_client.py
旺店通ERP OpenAPI v2 Python客户端
通过调用Java程序执行API请求
"""

import subprocess
import json
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / 'config'))
from skill_config import ERP_JAVA_EXE, ERP_JAVA_CLASSPATH, ERP_JAVA_MAIN_CLASS, ensure_dirs
ensure_dirs()


class WdtClient:
    """旺店通ERP OpenAPI v2 客户端"""

    def __init__(self, base_url: str, appkey: str, appsecret: str, sid: str):
        """
        初始化客户端

        Args:
            base_url: API基础URL
            appkey: 应用Key
            appsecret: 应用密钥
            sid: 系统ID
        """
        self.base_url = base_url
        self.appkey = appkey
        self.appsecret = appsecret
        self.sid = sid

        self.java_exe = ERP_JAVA_EXE
        self.java_classpath = ERP_JAVA_CLASSPATH
        self.java_main_class = ERP_JAVA_MAIN_CLASS

    def call_api(self, api_method: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        调用API（通过Java程序）

        Args:
            api_method: API方法名
            params: 业务参数

        Returns:
            API响应字典
        """
        if params is None:
            params = {}

        # 构建命令行参数
        cmd = [
            self.java_exe,
            "-cp", self.java_classpath,
            self.java_main_class,
            api_method
        ]

        # 添加参数
        for key, value in params.items():
            cmd.extend([f"--{key}", str(value)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60
            )

            # Java程序输出是GBK编码
            try:
                stdout = result.stdout.decode('gbk', errors='replace')
            except:
                stdout = result.stdout.decode('utf-8', errors='replace')

            if stdout:
                # 解析输出中的JSON（从 "=== 响应 ===" 后面提取）
                if '=== 响应 ===' in stdout:
                    json_str = stdout.split('=== 响应 ===')[1]
                    json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
                else:
                    json_match = re.search(r'\{.*\}', stdout, re.DOTALL)

                if json_match:
                    return json.loads(json_match.group())

            return {"code": -1, "message": "API调用失败"}

        except subprocess.TimeoutExpired:
            return {"code": -1, "message": "API调用超时"}
        except Exception as e:
            return {"code": -1, "message": str(e)}

    def search_combinations(self, page_no: int = 1, page_size: int = 100,
                           start_time: Optional[str] = None,
                           end_time: Optional[str] = None,
                           suite_no: Optional[str] = None) -> Dict[str, Any]:
        """
        查询组合装商品

        Args:
            page_no: 页码
            page_size: 每页条数
            start_time: 开始时间，格式 yyyy-MM-dd HH:mm:ss
            end_time: 结束时间，格式 yyyy-MM-dd HH:mm:ss
            suite_no: 组合装商家编码（可选，用于精确查询）

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
        if suite_no:
            params['suite_no'] = suite_no

        response = self.call_api('suites_query', params)
        
        # ERP返回的是 suites 字段，不是 suites_list
        # 标准化响应格式
        if 'suites' in response and 'suites_list' not in response:
            response['suites_list'] = response.get('suites', [])
        
        return response

    def get_all_combinations(self, page_size: int = 200) -> List[Dict[str, Any]]:
        """
        获取全部组合装（自动处理分页）

        Args:
            page_size: 每页条数，默认200

        Returns:
            全部组合装列表
        """
        all_suites = []
        page_no = 1

        while True:
            response = self.search_combinations(page_no=page_no, page_size=page_size)

            if response.get('code') != 0:
                print(f"[ERROR] API错误: {response.get('message')}")
                break

            suites = response.get('suites', [])
            if not suites:
                break

            all_suites.extend(suites)

            if len(suites) < page_size:
                break

            page_no += 1

        return all_suites
