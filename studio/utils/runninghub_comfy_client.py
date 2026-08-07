# -*- coding: utf-8 -*-
"""RunningHub online workflow client using the standard ComfyUI protocol.

RunningHub hosts standard ComfyUI instances.  Instead of the public openapi
(which is meant for external integrators), this client talks to the same
ComfyUI endpoints that the RunningHub editor uses:

    POST /upload/image
    POST /prompt
    GET  /history/{prompt_id}
    GET  /view?filename=...

The RunningHub editor authenticates these calls with session values stored in
browser localStorage: Rh-Comfy-Auth, Rh-Identify and Rh-Accesstoken.
"""

import os
import time
import urllib.parse

import requests

from utils.logger_utils import log


class RunningHubComfyClient:
    """Client-side wrapper that runs an online RunningHub workflow like a local ComfyUI."""

    def __init__(self, base_url="https://www.runninghub.cn",
                 comfy_auth="", identify="", access_token="",
                 timeout=120):
        self.base_url = (base_url or "https://www.runninghub.cn").rstrip("/")
        self.comfy_auth = comfy_auth or ""
        self.identify = identify or ""
        self.access_token = access_token or ""
        self.timeout = timeout

    def update_auth(self, comfy_auth="", identify="", access_token=""):
        self.comfy_auth = comfy_auth or self.comfy_auth
        self.identify = identify or self.identify
        self.access_token = access_token or self.access_token

    def _auth_query(self):
        params = {}
        if self.comfy_auth:
            params["Rh-Comfy-Auth"] = self.comfy_auth
        if self.identify:
            params["Rh-Identify"] = self.identify
        return params

    def _headers(self):
        headers = {}
        if self.comfy_auth:
            headers["Rh-Comfy-Auth"] = self.comfy_auth
        if self.identify:
            headers["Rh-Identify"] = self.identify
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def is_alive(self, timeout=8):
        try:
            resp = requests.get(
                f"{self.base_url}/system_stats",
                headers=self._headers(),
                params=self._auth_query(),
                timeout=timeout,
            )
            return resp.status_code == 200
        except Exception as e:
            log.warning(f"RunningHub ComfyUI protocol check failed: {e}")
            return False

    def get_object_info(self):
        try:
            resp = requests.get(
                f"{self.base_url}/object_info",
                headers=self._headers(),
                params=self._auth_query(),
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            log.error(f"object_info HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"object_info error: {e}")
        return None

    def upload_file(self, file_path):
        """Upload a local file to the RunningHub ComfyUI input dir, return server filename."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(file_path)
        url = f"{self.base_url}/upload/image"
        with open(file_path, "rb") as f:
            files = {"image": (os.path.basename(file_path), f)}
            data = {"type": "input", "overwrite": "true", "subfolder": ""}
            resp = requests.post(
                url,
                files=files,
                data=data,
                headers=self._headers(),
                params=self._auth_query(),
                timeout=self.timeout,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"upload failed HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        name = data.get("name") or data.get("subfolder") or ""
        if not name:
            raise RuntimeError(f"upload response missing name: {resp.text[:200]}")
        log.info(f"[RunningHub ComfyUI] uploaded {os.path.basename(file_path)} -> {name}")
        return name

    def submit_prompt(self, workflow_json):
        """Submit a standard ComfyUI prompt, return prompt_id."""
        url = f"{self.base_url}/prompt"
        resp = requests.post(
            url,
            json={"prompt": workflow_json},
            headers=self._headers(),
            params=self._auth_query(),
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"submit prompt failed HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        prompt_id = data.get("prompt_id") or data.get("taskId") or ""
        if not prompt_id:
            raise RuntimeError(f"submit response missing prompt_id: {resp.text[:300]}")
        return prompt_id

    def get_history(self, prompt_id):
        """Return the ComfyUI history entry for a prompt_id, or None."""
        try:
            resp = requests.get(
                f"{self.base_url}/history/{prompt_id}",
                headers=self._headers(),
                params=self._auth_query(),
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data.get(prompt_id)
            log.error(f"history HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"history error: {e}")
        return None

    def wait_history(self, prompt_id, timeout=3600, interval=3.0):
        """Poll ComfyUI history until the prompt finishes. Return entry or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            entry = self.get_history(prompt_id)
            if entry:
                status = (entry.get("status") or "").lower()
                if status in ("success", "error", "completed", "failed"):
                    return entry
            time.sleep(interval)
        return None

    @staticmethod
    def history_outputs(entry):
        """Convert a ComfyUI history entry to RunningHub-like result rows."""
        outputs = []
        if not entry or not isinstance(entry, dict):
            return outputs
        node_outputs = entry.get("outputs") or {}
        for node_id, out in node_outputs.items():
            if not isinstance(out, dict):
                continue
            images = out.get("images") or []
            for img in images:
                outputs.append({
                    "nodeId": str(node_id),
                    "url": "",
                    "outputType": (img.get("type") or "png"),
                    "filename": img.get("filename", ""),
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                    "text": None,
                })
            for text_key in ("text", "string"):
                if out.get(text_key):
                    outputs.append({
                        "nodeId": str(node_id),
                        "url": "",
                        "outputType": "txt",
                        "filename": "",
                        "subfolder": "",
                        "type": "output",
                        "text": str(out.get(text_key)),
                    })
        return outputs

    def output_url(self, filename, subfolder="", file_type="output"):
        query = {
            "filename": filename,
            "type": file_type,
            "subfolder": subfolder,
        }
        query.update(self._auth_query())
        return f"{self.base_url}/view?{urllib.parse.urlencode(query)}"

    def download_output(self, filename, subfolder="", file_type="output"):
        url = self.output_url(filename, subfolder, file_type)
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"download failed HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.content


def get_runninghub_comfy_client(ai_config=None):
    """Build a RunningHubComfyClient from ai_config settings."""
    cfg = ai_config or {}
    return RunningHubComfyClient(
        base_url=cfg.get("runninghub_base_url", "https://www.runninghub.cn"),
        comfy_auth=cfg.get("runninghub_comfy_auth", ""),
        identify=cfg.get("runninghub_comfy_identify", ""),
        access_token=cfg.get("runninghub_access_token", ""),
    )
