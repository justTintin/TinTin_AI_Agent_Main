import requests
from utils.http_client import http_get, http_post
import json
from utils.logger_utils import log

class RunningHubManager:
    def __init__(self, api_key=None, base_url="https://www.runninghub.cn"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json"
        }

    def update_config(self, api_key, base_url=None):
        self.api_key = api_key
        if base_url:
            self.base_url = base_url.rstrip("/")
        self.headers["Authorization"] = f"Bearer {self.api_key}"

    def get_user_info(self):
        """获取用户信息以验证 API Key"""
        url = f"{self.base_url}/openapi/v1/user/info"
        try:
            log.info(f"Verifying RunningHub API Key via: {url}")
            res = http_get(url, headers=self.headers, timeout=10)
            log.info(f"User Info Response [{res.status_code}]: {res.text[:100]}...")
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            log.error(f"Error getting user info: {e}")
        return None

    def get_workflow_list(self, page=1, size=50):
        """获取工作流/AI 应用列表"""
        urls_to_try = [self.base_url]
        if "www.runninghub.cn" in self.base_url:
            urls_to_try.append("https://api.runninghub.cn")
            
        # Priority on /app/list since user explicitly mentioned AI Apps
        endpoints = [
            ("/openapi/v1/app/list", "POST"),
            ("/openapi/v1/app/page", "GET"),
            ("/openapi/v1/workflow/list", "POST"),
            ("/openapi/v1/workflow/list", "GET"),
            ("/openapi/v1/workflow/page", "GET")
        ]
        
        payload = {"page": page, "size": size}
        
        for base in urls_to_try:
            for path, method in endpoints:
                url = f"{base}{path}"
                try:
                    log.info(f"Trying RunningHub API: {method} {url}")
                    if method == "POST":
                        res = http_post(url, headers=self.headers, json=payload, timeout=10)
                    else:
                        res = http_get(url, headers=self.headers, params=payload, timeout=10)
                    
                    log.info(f"Response from {url} [{res.status_code}]: {res.text[:150]}...")
                    
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == 0:
                            res_data = data.get("data", {})
                            items = []
                            if isinstance(res_data, list):
                                items = res_data
                            elif isinstance(res_data, dict):
                                items = res_data.get("list") or res_data.get("records") or res_data.get("rows") or []
                            
                            if items:
                                # Ensure items have unified naming (App uses 'appName'/'appId')
                                for item in items:
                                    if 'appId' in item and 'workflowId' not in item:
                                        item['workflowId'] = item['appId']
                                    if 'appName' in item and 'workflowName' not in item:
                                        item['workflowName'] = item['appName']
                                        
                                if base != self.base_url:
                                    log.info(f"Switching RunningHub base URL to: {base}")
                                    self.base_url = base
                                log.info(f"Success! Found {len(items)} items via {path}")
                                return items
                except Exception as e:
                    log.error(f"Error with {url}: {e}")
                
        log.error("All RunningHub list endpoints and base URLs failed.")
        return []

    def get_workflow_detail(self, workflow_id):
        """获取工作流/AI 应用详情"""
        endpoints = [
            ("/openapi/v1/app/detail", "POST", {"appId": workflow_id}),
            ("/openapi/v1/app/detail", "GET", {"appId": workflow_id}),
            ("/openapi/v1/workflow/detail", "GET", {"workflowId": workflow_id}),
            ("/openapi/v1/workflow/detail", "POST", {"workflowId": workflow_id})
        ]
        
        for path, method, params in endpoints:
            url = f"{self.base_url}{path}"
            try:
                log.info(f"Trying RunningHub Detail API: {method} {url} with {params}")
                if method == "POST":
                    res = http_post(url, headers=self.headers, json=params, timeout=10)
                else:
                    res = http_get(url, headers=self.headers, params=params, timeout=10)
                
                log.info(f"Detail Response from {url} [{res.status_code}]: {res.text[:150]}...")
                
                if res.status_code == 200:
                    data = res.json()
                    if data.get("code") == 0:
                        detail = data.get("data", {})
                        # Normalize field names for Apps
                        if 'appId' in detail:
                            detail['workflowId'] = detail['appId']
                        if 'appName' in detail:
                            detail['workflowName'] = detail['appName']
                        return detail
            except Exception as e:
                log.error(f"Error with detail {url}: {e}")
        return None

    def execute_workflow(self, workflow_id, node_info_list):
        """执行工作流或 AI 应用"""
        # Try both App and Workflow execution endpoints
        endpoints = [
            ("/openapi/v1/app/execute", {"appId": workflow_id, "nodeInfoList": node_info_list}),
            ("/openapi/v1/task/execute", {"workflowId": workflow_id, "nodeInfoList": node_info_list})
        ]
        
        for path, payload in endpoints:
            url = f"{self.base_url}{path}"
            try:
                log.info(f"Executing RunningHub via: {url}")
                res = http_post(url, headers=self.headers, json=payload, timeout=20)
                log.info(f"Execution Response [{res.status_code}]: {res.text[:150]}...")
                if res.status_code == 200:
                    data = res.json()
                    if data.get("code") == 0:
                        return data.get("data", {}).get("taskId")
            except Exception as e:
                log.error(f"Error executing via {url}: {e}")
        return None

    def get_task_status(self, task_id):
        """查询任务状态"""
        url = f"{self.base_url}/openapi/v1/task/status"
        params = {"taskId": task_id}
        try:
            res = http_get(url, headers=self.headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("code") == 0:
                    return data.get("data", {})
            log.error(f"Failed to get RunningHub task status (task_id={task_id}): {res.text}")
        except Exception as e:
            log.error(f"Error fetching RunningHub task status (task_id={task_id}): {e}")
        return None

    def upload_file(self, file_path):
        """上传文件到 RunningHub 并返回 URL"""
        url = f"{self.base_url}/openapi/v1/asset/upload"
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                # Note: Some APIs might require different field names
                res = http_post(url, headers={"Authorization": self.headers["Authorization"]}, files=files, timeout=60)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("code") == 0:
                        return data.get("data", {}).get("url")
            log.error(f"Failed to upload file to RunningHub: {res.text}")
        except Exception as e:
            log.error(f"Error uploading to RunningHub: {e}")
        return None
