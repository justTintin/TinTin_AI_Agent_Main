import json

from utils.http_client import http_get, http_post
from utils.logger_utils import log


class RunningHubManager:
    """RunningHub API 客户端。

    同时支持：
    - AI 应用：/task/openapi/ai-app/run（暂未使用）
    - ComfyUI 工作流：/openapi/v2/run/workflow/{id}
    """

    def __init__(self, api_key=None, base_url="https://www.runninghub.cn"):
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def update_config(self, api_key, base_url=None):
        self.api_key = api_key or ""
        if base_url:
            self.base_url = base_url.rstrip("/")
        self.headers["Authorization"] = f"Bearer {self.api_key}"

    def _auth_header(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def test_connection(self):
        """测试 API Key：查询账户状态。"""
        url = f"{self.base_url}/uc/openapi/accountStatus"
        try:
            log.info(f"Testing RunningHub API Key via: {url}")
            resp = http_post(url, headers=self._auth_header(), json={"apikey": self.api_key}, timeout=10)  # noqa: E501
            log.info(f"Account status response [{resp.status_code}]: {resp.text[:150]}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data")
        except Exception as e:
            log.error(f"Error testing RunningHub connection: {e}")
        return None

    def upload_file(self, file_path):
        """上传本地文件，返回 public download_url（用于工作流 nodeInfoList）。"""
        url = f"{self.base_url}/openapi/v2/media/upload/binary"
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                resp = http_post(url, headers=self._auth_header(), files=files, timeout=60)  # noqa: E501
            log.info(f"Upload response [{resp.status_code}]: {resp.text[:200]}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("download_url") or data.get("data", {}).get("fileName")  # noqa: E501
            log.error(f"Failed to upload file to RunningHub: {resp.text}")
        except Exception as e:
            log.error(f"Error uploading to RunningHub: {e}")
        return None

    def get_workflow_json(self, workflow_id):
        """获取 ComfyUI 工作流 JSON（用于识别输入节点）。

        端点：POST /api/openapi/getJsonApiFormat
        """
        url = f"{self.base_url}/api/openapi/getJsonApiFormat"
        payload = {"apiKey": self.api_key, "workflowId": workflow_id}
        try:
            log.info(f"Fetching workflow JSON: {url} workflowId={workflow_id}")
            resp = http_post(url, headers=self._auth_header(), json=payload, timeout=10)
            log.info(f"Workflow JSON response [{resp.status_code}]: {resp.text[:200]}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    prompt_str = data.get("data", {}).get("prompt", "")
                    if isinstance(prompt_str, str) and prompt_str:
                        return json.loads(prompt_str)
                    return prompt_str
        except Exception as e:
            log.error(f"Error fetching workflow JSON: {e}")
        return None

    def run_workflow(self, workflow_id, node_info_list, add_metadata=True, instance_type="default",  # noqa: E501
                    use_personal_queue=False, retain_seconds=None, webhook_url=None):
        """提交 ComfyUI 工作流任务。

        端点：POST /openapi/v2/run/workflow/{workflow_id}
        返回 {"success": bool, "task_id": str, "error_code": str, "error_message": str, "raw": dict}。"""  # noqa: E501
        url = f"{self.base_url}/openapi/v2/run/workflow/{workflow_id}"
        payload = {
            "addMetadata": add_metadata,
            "nodeInfoList": node_info_list,
            "instanceType": instance_type or "default",
            "usePersonalQueue": bool(use_personal_queue),
        }
        if retain_seconds:
            payload["retainSeconds"] = int(retain_seconds)
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        try:
            log.info(f"Running workflow: {url} payload={json.dumps(payload, ensure_ascii=False)[:500]}")  # noqa: E501
            resp = http_post(url, headers=self._auth_header(), json=payload, timeout=30)
            log.info(f"Run workflow response [{resp.status_code}]: {resp.text[:500]}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    task_id = data.get("taskId") or ""
                    error_code = str(data.get("errorCode") or "")
                    error_message = data.get("errorMessage") or ""
                    if task_id:
                        return {"success": True, "task_id": task_id, "error_code": "", "error_message": "", "raw": data}  # noqa: E501
                    return {
                        "success": False,
                        "task_id": None,
                        "error_code": error_code or str(data.get("code") or ""),
                        "error_message": error_message or resp.text[:300],
                        "raw": data,
                    }
            return {
                "success": False,
                "task_id": None,
                "error_code": str(resp.status_code),
                "error_message": f"HTTP {resp.status_code}: {resp.text[:300]}",
                "raw": None,
            }
        except Exception as e:
            log.error(f"Error running workflow: {e}")
            return {"success": False, "task_id": None, "error_code": "", "error_message": str(e), "raw": None}  # noqa: E501

    def get_task_status(self, task_id):
        """查询任务结果 V2。"""
        url = f"{self.base_url}/openapi/v2/query"
        try:
            resp = http_post(url, headers=self._auth_header(), json={"taskId": task_id}, timeout=10)  # noqa: E501
            if resp.status_code == 200:
                return resp.json()
            log.error(f"Failed to get task status (task_id={task_id}): {resp.text}")
        except Exception as e:
            log.error(f"Error fetching task status: {e}")
        return None

    # ---- 工作流列表（RunningHub 未公开文档，按常见端点探测） ----
    def get_workflow_list(self, page=1, size=50):
        """尝试读取当前 API Key 下的工作流/应用列表。优先 POST /api/openapi/getWorkflowList，失败回退 GET。"""
        endpoints = [
            ("POST", f"{self.base_url}/api/openapi/getWorkflowList", {"apiKey": self.api_key, "page": page, "size": size}),  # noqa: E501
            ("GET", f"{self.base_url}/api/openapi/getWorkflowList", {"apiKey": self.api_key, "page": page, "size": size}),  # noqa: E501
        ]
        for method, url, payload in endpoints:
            try:
                log.info(f"Trying list workflows: {method} {url}")
                if method == "POST":
                    resp = http_post(url, headers=self._auth_header(), json=payload, timeout=10)  # noqa: E501
                else:
                    resp = http_get(url, headers=self._auth_header(), params=payload, timeout=10)  # noqa: E501
                log.info(f"List workflows response [{resp.status_code}]: {resp.text[:200]}")  # noqa: E501
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        items = data.get("data", {})
                        if isinstance(items, dict):
                            items = items.get("list") or items.get("records") or items.get("items") or []  # noqa: E501
                        if isinstance(items, list):
                            return items
            except Exception as e:
                log.error(f"Error listing workflows via {method} {url}: {e}")
        return None

    def get_workflow_detail(self, workflow_id):
        url = f"{self.base_url}/api/webapp/apiCallDemo"
        params = {"apiKey": self.api_key, "webappId": workflow_id}
        try:
            resp = http_get(url, headers=self._auth_header(), params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data")
        except Exception as e:
            log.error(f"Error fetching app detail: {e}")
        return None

    def execute_workflow(self, workflow_id, node_info_list):
        url = f"{self.base_url}/task/openapi/ai-app/run"
        payload = {
            "apiKey": self.api_key,
            "webappId": workflow_id,
            "nodeInfoList": node_info_list
        }
        try:
            resp = http_post(url, headers=self._auth_header(), json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("taskId")
        except Exception as e:
            log.error(f"Error executing AI app: {e}")
        return None
