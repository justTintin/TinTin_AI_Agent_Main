# 螺丝钉-电商智能体矩阵 · 自动更新架构方案

> 版本：v2.0 | 技术栈：Python + PySide6 (Qt 6) + FastAPI + Jenkins + Nginx | 架构：服务端驱动更新

---

## 一、架构总览

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| **服务端驱动** | 客户端不设轮询，由服务端返回版本信息触发更新 |
| **客户端启动时检测** | 客户端启动时一次性向服务端查询版本，无后台定时检查 |
| **手动触发** | 用户可随时点击「检查更新」按钮 |
| **两套更新通道** | 客户端更新包（PyInstaller 打包）+ 服务端自身热更新包 |

### 1.2 整体流程

```
                          Git Push
                             │
                             ▼
                    ┌────────────────────┐
                    │   Jenkins Pipeline  │
                    │  ① 拉取代码         │
                    │  ② 更新版本号       │
                    │  ③ PyInstaller     │
                    │  ④ 打包 ZIP + SHA256│
                    │  ⑤ 生成 version.json│
                    └─────────┬──────────┘
                              │ SCP
                              ▼
                    ┌────────────────────┐
                    │   Nginx 更新服务器    │
                    │  /var/www/updates/  │
                    │  ├── version.json   │
                    │  └── v2.1.2.zip     │
                    └─────────┬──────────┘
                              │ HTTP
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
┌─────────────────────┐             ┌─────────────────────┐
│  服务端计算节点        │             │   客户端桌面应用       │
│  (FastAPI)          │  ◄── API ──  │  (PySide6 GUI)      │
│                     │  (带版本头)   │                      │
│  GET /api/updates/  │  ── 响应 ──► │  ① 启动时请求更新检查  │
│    check            │             │  ② 发现新版本 → 弹窗  │
│                     │             │  ③ 下载 ZIP → 替换   │
│  自身热更新脚本       │             │  ④ updater.bat 重启  │
└─────────────────────┘             └─────────────────────┘
```

### 1.3 更新触发途径

| 触发方式 | 客户端 | 服务端 |
|----------|--------|--------|
| 启动时 | ✅ 一次性检测（非定时） | ❌ 不适用 |
| 手动检查 | ✅ 用户点击按钮 | ✅ SSH 触发 / Jenkins 触发 |
| API 通信中 | ✅ 服务端返回版本头信息，客户端发现有更新可提示 | ✅ 不适用 |
| Jenkins 自动 | ❌ 不适用 | ✅ 自动化流水线触发热更新 |

### 1.4 现有基础

| 模块 | 文件 | 状态 |
|------|------|------|
| 版本号管理 | `studio/version.py` | ✅ 已有（CalVer: 主.次.修订.构建日期） |
| 更新配置 | `studio/config/update.json` | ✅ 已有 |
| 更新检查器 | `studio/utils/update_checker.py` | ✅ 已有骨架 |
| 路径常量 | `studio/config/paths.py` | ✅ 已有 |
| 后台 Worker | `studio/utils/base_worker.py` | ✅ 已有 |

---

## 二、服务端方案（Server Side）

### 2.1 更新检测 API

在现有 FastAPI 计算节点中新增以下端点：

```python
# server/routers/updates.py
"""
服务端更新路由。

客户端 → 服务端：请求版本检测
服务端 → Nginx：拉取更新包
"""
import os
import json
import subprocess
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/updates", tags=["updates"])

# 服务端自身版本号
SERVER_VERSION = "1.2.1"
# 从共享的 version.json 读取发布信息
MANIFEST_PATH = "/var/www/updates/version.json"


class CheckResponse(BaseModel):
    """版本检查响应。"""
    client_available: bool          # 客户端是否有新版本
    client_latest_version: str      # 客户端最新版本号
    client_download_url: str        # 客户端下载地址
    client_file_hash: str           # SHA256
    client_file_size: int           # 大小（字节）
    client_release_notes: str       # 更新说明
    client_force_update: bool       # 是否强制更新
    server_latest_version: str      # 服务端最新版本号
    server_download_url: str        # 服务端更新包
    server_file_hash: str
    server_file_size: int


def _load_manifest() -> dict:
    """读取共享的 version.json。"""
    try:
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "latest_version": "",
            "download_url": "",
            "file_hash": "",
            "file_size": 0,
            "release_notes": "",
            "force_update": False,
            "server_update": {},
        }


@router.get("/check", response_model=CheckResponse)
async def check_update(request: Request):
    """
    版本更新检查。

    客户端启动时或用户手动点击时调用此接口。
    服务端根据客户端上报的版本号判断是否需要更新。
    """
    client_version = request.headers.get("x-client-version", "")
    manifest = _load_manifest()

    # 客户端版本比对
    from packaging.version import Version
    remote_client_ver = manifest.get("latest_version", "")
    client_available = False
    if client_version and remote_client_ver:
        try:
            client_available = Version(remote_client_ver) > Version(client_version)
        except Exception:
            client_available = False

    # 服务端自身版本信息
    server_info = manifest.get("server_update", {})

    return CheckResponse(
        client_available=client_available,
        client_latest_version=remote_client_ver,
        client_download_url=manifest.get("download_url", ""),
        client_file_hash=manifest.get("file_hash", ""),
        client_file_size=manifest.get("file_size", 0),
        client_release_notes=manifest.get("release_notes", ""),
        client_force_update=manifest.get("force_update", False),
        server_latest_version=server_info.get("latest_version", SERVER_VERSION),
        server_download_url=server_info.get("download_url", ""),
        server_file_hash=server_info.get("file_hash", ""),
        server_file_size=server_info.get("file_size", 0),
    )


@router.post("/apply-server-update")
async def apply_server_update():
    """
    触发服务端自身热更新。

    由运维人员或 Jenkins 调用。
    启动后台更新脚本：下载 → 解压 → 替换代码 → 重启 uvicorn。
    """
    try:
        script_path = "/opt/server/scripts/hot_reload.sh"
        if not os.path.isfile(script_path):
            raise HTTPException(500, "热更新脚本不存在")

        subprocess.Popen(
            ["bash", script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"status": "ok", "message": "服务端更新已在后台启动"}
    except Exception as e:
        raise HTTPException(500, str(e))
```

### 2.2 服务端热更新脚本

```bash
#!/bin/bash
# /opt/server/scripts/hot_reload.sh
# 服务端热更新：读取 version.json → 下载 → 解压 → 替换 → 重启

set -e

MANIFEST="/var/www/updates/version.json"
TMP_DIR="/tmp/server_update"
TARGET_DIR="/opt/server"

echo "[$(date)] 服务端更新开始"

# 读取更新信息
SERVER_VER=$(python3 -c "import json; d=json.load(open('$MANIFEST')); su=d.get('server_update',{}); print(su.get('latest_version',''))")
DL_URL=$(python3 -c "import json; d=json.load(open('$MANIFEST')); su=d.get('server_update',{}); print(su.get('download_url',''))")

if [ -z "$SERVER_VER" ]; then
    echo "无服务端更新"
    exit 0
fi

echo "[更新] 服务端版本: $SERVER_VER"
echo "[更新] 下载地址: $DL_URL"

# 下载
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
wget -q "http://localhost$DL_URL" -O "$TMP_DIR/update.zip"

# 解压
cd "$TMP_DIR"
unzip -q update.zip -d extracted

# 替换（排除配置文件）
rsync -av --delete \
    --exclude='config/ai_config.json' \
    --exclude='logs/' \
    --exclude='.env' \
    extracted/ "$TARGET_DIR/"

# 重启服务
systemctl restart compute-server

# 清理
rm -rf "$TMP_DIR"

echo "[$(date)] 服务端更新完成: $SERVER_VER"
```

### 2.3 客户端 API 拦截检测（被动触发）

客户端在进行所有常规 API 请求时，服务端可在响应头中附加版本信息，客户端拦截到后触发更新提示。

在服务端 FastAPI 中通过 middleware 实现：

```python
# server/main.py 或 middleware
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import json


class VersionCheckMiddleware(BaseHTTPMiddleware):
    """
    在每次 API 响应中附加最新客户端版本信息。
    客户端收到后若发现版本不匹配，可提示用户更新。
    """
    MANIFEST_PATH = "/var/www/updates/version.json"

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        try:
            with open(self.MANIFEST_PATH, "r") as f:
                manifest = json.load(f)
            latest = manifest.get("latest_version", "")
            if latest:
                response.headers["X-Latest-Client-Version"] = latest
                response.headers["X-Update-Download-Url"] = manifest.get("download_url", "")
                response.headers["X-Update-Release-Notes"] = manifest.get("release_notes", "")[:200]
                response.headers["X-Force-Update"] = str(manifest.get("force_update", False)).lower()
        except Exception:
            pass

        return response
```

---

## 三、客户端方案（Client Side）

### 3.1 目录结构

```
studio/
├── updater/                          # ★ 新增：自动更新模块
│   ├── __init__.py                   #   模块导出口
│   ├── version_worker.py             #   VersionCheckWorker：向服务端查询版本
│   ├── download_worker.py            #   DownloadWorker：后台下载 + 进度
│   ├── updater_dialog.py             #   更新对话框 UI
│   ├── install.py                    #   安装逻辑（解压、替换、重启）
│   └── updater.bat                   #   引导替换脚本（绕过 exe 占用）
│
├── utils/
│   ├── update_checker.py             #   已有：版本比对等工具函数
│   ├── base_worker.py                #   已有：BaseWorker 基类
│   └── api_client.py                 #   修改：添加更新检测头拦截
│
├── config/
│   ├── update.json                   #   已有：update_url 配置
│   └── paths.py                      #   已有：路径常量
│
├── version.py                        #   已有：版本号
└── gui_main.py                       #   修改：接入启动检测 + 版本头拦截
```

### 3.2 核心代码实现

#### 3.2.1 `updater/__init__.py` — 模块导出口

```python
# -*- coding: utf-8 -*-
"""
自动更新模块。

更新流程（服务端驱动）：
  ① 客户端启动时或用户手动点击，向服务端 /api/updates/check 查询版本
  ② 服务端比对版本号，返回最新版本信息和下载地址
  ③ 客户端弹窗让用户确认 → 下载 ZIP → 验证 SHA256 → 安装 → 重启

所有 Worker 基于 BaseWorker，异步非阻塞，不卡界面。
"""
from updater.version_worker import VersionCheckWorker
from updater.download_worker import DownloadWorker
from updater.updater_dialog import UpdateDialog
from updater.install import install_update
```

#### 3.2.2 `updater/version_worker.py` — 版本查询 Worker

与现有 `RateClipsWorker`、`_SearchWorker` 同一模式：

```python
# -*- coding: utf-8 -*-
"""
版本查询 Worker。

向服务端计算节点查询最新版本信息。
不设定时器，仅在启动时或用户手动点击时调用。
"""
import requests
from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.update_checker import get_local_version, load_update_config
from utils.logger_utils import log


class VersionCheckWorker(BaseWorker):
    """向服务端查询客户端和服务端的最新版本。"""
    finished = Signal(dict)

    def do_work(self):
        local_ver = get_local_version()
        cfg = load_update_config()
        server_url = (cfg.get("update_url") or "").strip().rstrip("/")

        # 若 update_url 未配置，尝试从服务端地址推导
        if not server_url:
            # 从 ai_config.json 读取 compute_server_url 作为备选
            try:
                from config.paths import AI_CONFIG_FILE
                import json as _json
                if os.path.isfile(AI_CONFIG_FILE):
                    with open(AI_CONFIG_FILE, encoding="utf-8") as f:
                        ai_cfg = _json.load(f)
                    server_url = (ai_cfg.get("compute_server_url") or "").strip().rstrip("/")
            except Exception:
                pass

        if not server_url:
            self.finished.emit({
                "available": False,
                "reason": "更新服务器未配置",
                "local_version": local_ver,
                "client_available": False,
                "server_available": False,
            })
            return

        try:
            resp = requests.get(
                f"{server_url}/api/updates/check",
                timeout=10,
                headers={"X-Client-Version": local_ver},
            )
            resp.raise_for_status()
            info = resp.json()

            self.finished.emit({
                "available": info.get("client_available", False),
                "reason": "",
                "local_version": local_ver,
                # 客户端更新信息
                "client_available": info.get("client_available", False),
                "client_latest_version": info.get("client_latest_version", ""),
                "client_download_url": info.get("client_download_url", ""),
                "client_file_hash": info.get("client_file_hash", ""),
                "client_file_size": info.get("client_file_size", 0),
                "client_release_notes": info.get("client_release_notes", ""),
                "client_force_update": info.get("client_force_update", False),
                # 服务端更新信息
                "server_available": False,  # 服务端更新由运维触发
                "server_latest_version": info.get("server_latest_version", ""),
            })

        except requests.ConnectionError:
            self.finished.emit({
                "available": False,
                "reason": "无法连接到服务端",
                "local_version": local_ver,
            })
        except Exception as e:
            log.warning(f"版本查询失败: {e}")
            self.finished.emit({
                "available": False,
                "reason": str(e),
                "local_version": local_ver,
            })
```

#### 3.2.3 `updater/download_worker.py` — 下载 Worker（带进度）

```python
# -*- coding: utf-8 -*-
"""
后台下载更新包 Worker。

支持：流式下载、进度回调、SHA256 校验。
"""
import os
import hashlib
import tempfile
import requests
from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.logger_utils import log


class DownloadWorker(BaseWorker):
    """下载更新包，发射进度信号。"""
    progress = Signal(int, int)    # current, total (bytes)
    finished = Signal(str)         # 下载到本地的 zip 路径
    error = Signal(str)

    def __init__(self, download_url: str, expected_hash: str = "", parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.expected_hash = expected_hash
        self._target_path = ""

    def do_work(self):
        tmp_dir = tempfile.mkdtemp(prefix="tinupdate_")
        zip_name = os.path.basename(self.download_url.split("?")[0]) or "update.zip"
        self._target_path = os.path.join(tmp_dir, zip_name)

        try:
            resp = requests.get(self.download_url, stream=True, timeout=300)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            sha256 = hashlib.sha256()

            with open(self._target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        sha256.update(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(downloaded, total)

            # SHA256 校验
            if self.expected_hash:
                actual_hash = sha256.hexdigest()
                expected = self.expected_hash.replace("sha256:", "").lower()
                if actual_hash != expected:
                    os.remove(self._target_path)
                    raise RuntimeError(
                        f"SHA256 校验失败: 期望={expected}, 实际={actual_hash}"
                    )

            self.finished.emit(self._target_path)

        except Exception as e:
            if os.path.isfile(self._target_path):
                os.remove(self._target_path)
            self.error.emit(str(e))
```

#### 3.2.4 `updater/updater_dialog.py` — 更新对话框

```python
# -*- coding: utf-8 -*-
"""
更新对话框。

场景：
  - 版本检测后有更新 → 显示版本信息 + "立即更新"按钮
  - 下载中 → 进度条
  - 安装完成 → 重启
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextBrowser,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


class UpdateDialog(QDialog):
    """自动更新对话框。"""

    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.download_worker = None
        self._setup_ui()
        self._show_version_info()

    def _setup_ui(self):
        self.setWindowTitle("软件更新")
        self.setFixedSize(520, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.lbl_title)

        self.lbl_version = QLabel()
        layout.addWidget(self.lbl_version)

        self.notes_browser = QTextBrowser()
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setMaximumHeight(180)
        layout.addWidget(self.notes_browser)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("muted_text")
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_skip = QPushButton("稍后再说")
        self.btn_skip.setObjectName("secondary_button")
        self.btn_skip.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_skip)

        self.btn_confirm = QPushButton("立即更新")
        self.btn_confirm.setObjectName("primary_button")
        self.btn_confirm.clicked.connect(self._on_update_clicked)
        btn_row.addWidget(self.btn_confirm)

        layout.addLayout(btn_row)

    def _show_version_info(self):
        info = self.update_info
        self.lbl_title.setText(f"发现新版本 v{info.get('client_latest_version', '')}")
        self.lbl_version.setText(
            f"当前版本: v{info.get('local_version', '')}  →  "
            f"最新版本: v{info.get('client_latest_version', '')}"
        )
        notes = info.get("client_release_notes", "暂无更新说明")
        self.notes_browser.setPlainText(notes)

        if info.get("client_force_update", False):
            self.btn_skip.setVisible(False)
            self.setWindowTitle("强制更新")
            self.lbl_status.setText("此版本为强制更新，请安装最新版本")

    def _on_update_clicked(self):
        """开始下载更新。"""
        self.btn_confirm.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("正在下载更新包...")

        from updater.download_worker import DownloadWorker
        self.download_worker = DownloadWorker(
            download_url=self.update_info["client_download_url"],
            expected_hash=self.update_info.get("client_file_hash", ""),
        )
        self.download_worker.progress.connect(self._on_progress)
        self.download_worker.finished.connect(self._on_downloaded)
        self.download_worker.error.connect(self._on_download_error)
        self.download_worker.start()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        mb = current / 1048576
        total_mb = total / 1048576
        self.lbl_status.setText(f"下载中: {mb:.1f}MB / {total_mb:.1f}MB")

    def _on_downloaded(self, zip_path: str):
        self.lbl_status.setText("正在安装更新...")
        from updater.install import install_update
        if install_update(zip_path):
            self.lbl_status.setText("安装完成，正在重启...")
            import subprocess
            import sys
            from pathlib import Path
            bat = Path(sys.argv[0]).parent / "updater.bat"
            subprocess.Popen([str(bat)], shell=True)
            self.accept()
            QGuiApplication.instance().quit()
        else:
            self.lbl_status.setText("安装失败，请稍后重试")
            self.btn_confirm.setEnabled(True)

    def _on_download_error(self, msg: str):
        self.lbl_status.setText(f"下载失败: {msg}")
        self.btn_confirm.setEnabled(True)
        self.btn_skip.setEnabled(True)
```

#### 3.2.5 `updater/install.py` — 安装逻辑

```python
# -*- coding: utf-8 -*-
"""
更新安装逻辑。

PyInstaller onedir 模式下，exe 被占用无法直接覆盖。
因此通过 updater.bat 引导替换：
  ① 备份旧目录 → ② 解压新包 → ③ 启动主程序 → ④ 后台清理备份
"""
import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path
from config.paths import PROJECT_ROOT
from utils.logger_utils import log

# 替换时排除的用户数据目录（不覆盖）
EXCLUDE_DIRS = ["config", "logs", "data", "outputs", "accounts", "playwright_profile"]
EXCLUDE_FILES = ["config.ini"]


def _should_exclude(rel_path: str) -> bool:
    rel = rel_path.replace("\\", "/")
    for d in EXCLUDE_DIRS:
        if rel.startswith(d + "/") or rel == d:
            return True
    for f in EXCLUDE_FILES:
        if rel == f:
            return True
    return False


def install_update(zip_path: str) -> bool:
    """
    执行更新安装。

    返回 True 表示安装成功，调用方应退出主程序并启动 updater.bat。
    """
    try:
        current_dir = Path(sys.argv[0]).parent if getattr(sys, "frozen", False) else PROJECT_ROOT
        if not getattr(sys, "frozen", False):
            current_dir = PROJECT_ROOT

        bat_path = current_dir / "updater.bat"
        zip_dest = current_dir / "_update_package.zip"
        backup_dir = current_dir.parent / (current_dir.name + ".bak")

        shutil.move(zip_path, str(zip_dest))

        # 生成 bat 脚本
        bat_content = f"""@echo off
chcp 65001 >nul
echo 正在更新，请勿关闭窗口...
timeout /t 2 /nobreak >nul

rem 备份旧目录
echo 备份旧版本...
if exist "{backup_dir}" rmdir /s /q "{backup_dir}"
move "{current_dir}" "{backup_dir}" >nul

rem 解压新包
echo 解压更新包...
mkdir "{current_dir}" >nul
cd /d "{current_dir}"
powershell -Command "Expand-Archive -Path '{zip_dest}' -DestinationPath '{current_dir}' -Force" >nul

rem 恢复用户数据
echo 恢复配置...
xcopy "{backup_dir}\\config" "{current_dir}\\config" /E /I /Y /Q >nul
xcopy "{backup_dir}\\data" "{current_dir}\\data" /E /I /Y /Q >nul
if exist "{backup_dir}\\accounts" xcopy "{backup_dir}\\accounts" "{current_dir}\\accounts" /E /I /Y /Q >nul
if exist "{backup_dir}\\outputs" xcopy "{backup_dir}\\outputs" "{current_dir}\\outputs" /E /I /Y /Q >nul

del "{zip_dest}" >nul

echo 启动新版本...
start "" "{current_dir}\\螺丝钉-电商智能体矩阵.exe"

start /b cmd /c "timeout /t 5 /nobreak >nul & rmdir /s /q "{backup_dir}""
exit
"""
        with open(str(bat_path), "w", encoding="utf-8") as f:
            f.write(bat_content)

        log.info(f"更新包已就绪: {zip_dest}, 引导脚本: {bat_path}")
        return True

    except Exception as e:
        log.error(f"安装更新失败: {e}")
        return False
```

### 3.3 接入 `gui_main.py`

在 MainWindow 中添加**启动时一次性检测**和**手动检测入口**：

```python
# gui_main.py 修改示例

class MainWindow(QMainWindow, ...):
    def __init__(self):
        super().__init__()
        # ... 现有初始化代码 ...

        # 启动3秒后检查一次更新（非定时，仅这一次）
        QTimer.singleShot(3000, self._check_update_once)

    def _check_update_once(self):
        """启动时一次性检查更新。"""
        self._version_worker = VersionCheckWorker()
        self._version_worker.finished.connect(self._on_version_check_result)
        self._version_worker.start()

    def _on_version_check_result(self, result: dict):
        if not result.get("available"):
            return  # 无更新或无法连接，静默忽略
        # 有可用更新，弹窗询问用户
        dialog = UpdateDialog(result, self)
        dialog.exec()

    def _on_menu_check_update(self):
        """菜单/按钮「检查更新」触发 — 用户手动检查。"""
        # 显示状态
        self.lbl_status.setText("正在检查更新...")

        w = VersionCheckWorker()
        w.finished.connect(lambda r: self._on_manual_check_result(r))
        w.start()

    def _on_manual_check_result(self, result: dict):
        if result.get("available"):
            dialog = UpdateDialog(result, self)
            dialog.exec()
        else:
            reason = result.get("reason", "已是最新版本")
            QMessageBox.information(self, "检查更新", reason)

    @staticmethod
    def on_api_response_headers(headers: dict):
        """
        当客户端收到任何服务端 API 响应时，检查版本头。
        可在现有的 HTTP 客户端工具（如 api_client.py）中调用此方法。

        此方法为被动检测，不设定时器。
        """
        latest = headers.get("X-Latest-Client-Version", "")
        if not latest:
            return
        from utils.update_checker import get_local_version, _compare_versions
        if _compare_versions(get_local_version(), latest) == 1:
            # 有新版本，触发更新提示
            # （可通过信号或回调通知主窗口弹窗）
            log.info(f"服务端通知有新版本: {latest}")
```

### 3.4 API 响应头拦截

在现有的 HTTP 客户端工具中（如 `utils/api_client.py` 或各 `*_client.py` 的请求封装），添加对响应头的拦截：

```python
# utils/api_client.py 中
import requests as _requests


def request(method, url, **kwargs):
    """统一 HTTP 请求封装，自动附加版本头并检测更新。"""
    from utils.update_checker import get_local_version

    headers = kwargs.pop("headers", {})
    headers.setdefault("X-Client-Version", get_local_version())

    resp = _requests.request(method, url, headers=headers, **kwargs)

    # 检查响应头中是否有版本更新信息
    _check_response_for_update(resp.headers)

    return resp


def _check_response_for_update(headers: dict):
    """检查服务端是否在响应头中通知了新版本。"""
    latest = headers.get("X-Latest-Client-Version", "")
    if not latest:
        return
    from utils.update_checker import get_local_version, _compare_versions
    if _compare_versions(get_local_version(), latest) == 1:
        # 通过信号/回调通知主窗口
        from PySide6.QtCore import QMetaObject, Qt, Q_ARG
        # ... 触发更新提示逻辑
        pass
```

### 3.5 更新配置

```json
{
  "update_url": "http://X.X.X.X.X.X.X:8000",
  "channel": "stable",
  "check_on_startup": true,
  "last_check": "2026-07-17T19:30:00.000000"
}
```

| 字段 | 说明 |
|------|------|
| `update_url` | 服务端计算节点地址（复用 `compute_server_url`） |
| `check_on_startup` | 启动时是否检查更新（一次性，非定时） |
| `channel` | 更新通道（`stable` / `canary`） |

更新配置中的 `update_url` 默认复用 `compute_server_url`，无需额外配置。客户端启动时向 `{compute_server_url}/api/updates/check` 发一次请求，即完成版本检测。

---

## 四、Nginx 配置与更新包分发

### 4.1 Nginx 配置

```nginx
# /etc/nginx/sites-available/updates.your-server.com

server {
    listen 80;
    server_name updates.your-server.com;

    root /var/www/updates;

    location /version.json {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Access-Control-Allow-Origin "*";
    }

    location /updates/ {
        add_header Cache-Control "public, max-age=3600";
        add_header Accept-Ranges bytes;
        limit_rate 50m;  # 限速 50MB/s
    }

    location /server-updates/ {
        add_header Cache-Control "public, max-age=3600";
        add_header Accept-Ranges bytes;
        limit_rate 50m;
    }
}
```

### 4.2 `version.json` 清单

```json
{
  "latest_version": "2.1.2.20260717",
  "min_version": "2.0.0.20260101",
  "release_notes": "## v2.1.2 更新内容\n\n### ✨ 新增\n- 素材检索显示文件路径\n- 自动更新模块\n\n### 🐛 修复\n- 启动崩溃问题\n\n---\n完整日志: https://git.your-server.com/changelog",
  "download_url": "http://updates.your-server.com/updates/v2.1.2.zip",
  "file_hash": "sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",
  "file_size": 524288000,
  "force_update": false,
  "server_update": {
    "latest_version": "1.2.1.20260717",
    "download_url": "http://updates.your-server.com/server-updates/server-v1.2.1.zip",
    "file_hash": "sha256:def...",
    "file_size": 104857600,
    "release_notes": "服务端性能优化"
  },
  "channels": {
    "stable": { "version": "2.1.1.20260709", "download_url": "..." },
    "canary": { "version": "2.1.2.20260717", "download_url": "..." }
  }
}
```

---

## 五、CI/CD 流水线（Jenkins）

### 5.1 Jenkins Pipeline

```groovy
pipeline {
    agent any

    environment {
        PROJECT_ROOT = "D:\\code\\TinTin_AI_Agent_Client-0713\\TinTin_AI_Agent_Main"
        NGINX_HOST = "updates.your-server.com"
        NGINX_UPDATES_DIR = "/var/www/updates"
    }

    parameters {
        choice(name: 'TARGET', choices: ['client', 'server', 'both'],
               description: '更新目标')
        choice(name: 'CHANNEL', choices: ['stable', 'canary'],
               description: '发布通道')
        string(name: 'RELEASE_NOTES', defaultValue: '', description: '更新说明')
        booleanParam(name: 'FORCE_UPDATE', defaultValue: false,
                     description: '是否强制更新')
    }

    stages {
        stage('拉取代码') {
            steps { checkout scm }
        }

        stage('更新版本号') {
            when { expression { params.TARGET in ['client', 'both'] } }
            steps {
                script {
                    // 自动更新 __base_version__ 的修订号
                    bat '''
                        python -c "
import re
ver_path = 'studio/version.py'
with open(ver_path) as f: content = f.read()
match = re.search(r'__base_version__ = \"(\\d+\\.\\d+\\.)(\\d+)\"', content)
if match:
    prefix = match.group(1)
    rev = int(match.group(2)) + 1
    content = content.replace(match.group(0),
        f'__base_version__ = \"{prefix}{rev}\"')
    with open(ver_path, 'w') as f: f.write(content)
    print(f'版本号已更新: {prefix}{rev}')
"
                    '''
                }
            }
        }

        stage('PyInstaller 打包') {
            when { expression { params.TARGET in ['client', 'both'] } }
            steps {
                bat 'cd %PROJECT_ROOT% && powershell -File run_pyinstaller.ps1'
            }
        }

        stage('生成更新包') {
            steps {
                script {
                    def ver = readFile('studio/version.py').findAll(/__version__ = "(.*?)"/)[0]

                    if (params.TARGET in ['client', 'both']) {
                        bat """
                            cd %PROJECT_ROOT%
                            powershell -Command "Compress-Archive -Path dist/螺丝钉-电商智能体矩阵/* -DestinationPath updates/v${ver}.zip -Force"
                        """
                        def clientHash = sha256("updates/v${ver}.zip")
                        echo "客户端更新包: v${ver}.zip (${clientHash})"
                    }
                }
            }
        }

        stage('生成 version.json') {
            steps {
                script {
                    def ver = readFile('studio/version.py').findAll(/__version__ = "(.*?)"/)[0]
                    // 生成完整的 version.json
                    def manifest = [
                        latest_version: ver,
                        min_version: "2.0.0.20260101",
                        release_notes: params.RELEASE_NOTES ?: "自动构建 ${ver}",
                        download_url: "http://${NGINX_HOST}/updates/v${ver}.zip",
                        file_hash: "sha256:${sha256('updates/v' + ver + '.zip')}",
                        file_size: fileSize("updates/v${ver}.zip"),
                        force_update: params.FORCE_UPDATE,
                        channels: [
                            (params.CHANNEL): [
                                version: ver,
                                download_url: "http://${NGINX_HOST}/updates/v${ver}.zip"
                            ]
                        ],
                        server_update: [
                            latest_version: "",
                            download_url: "",
                            file_hash: "",
                            file_size: 0,
                            release_notes: ""
                        ]
                    ]

                    writeJSON file: 'updates/version.json', json: manifest
                }
            }
        }

        stage('发布到 Nginx') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'nginx-deploy', keyFileVariable: 'KEY')]) {
                    sh """
                        scp -i ${KEY} updates/*.zip root@${NGINX_HOST}:${NGINX_UPDATES_DIR}/updates/
                        scp -i ${KEY} updates/version.json root@${NGINX_HOST}:${NGINX_UPDATES_DIR}/version.json
                    """
                }
            }
        }

        stage('触发服务端热更新') {
            when { expression { params.TARGET in ['server', 'both'] } }
            steps {
                // 调用服务端热更新 API
                sh "curl -X POST http://compute-server:8000/api/updates/apply-server-update"
            }
        }
    }
}
```

---

## 六、蓝绿发布 / 金丝雀发布

### 6.1 实现原理

通过三种方式实现分级发布：

| 方式 | 实现 | 粒度 |
|------|------|------|
| **服务端 API 分流** | `/api/updates/check` 按 IP hash 返回不同版本 | 客户端维度 |
| **Nginx 静态文件分流** | 不同的 `version.json` 指向不同版本 | 全局维度 |
| **更新通道** | 配置 `channel: canary` 的客户端走金丝雀通道 | 配置维度 |

### 6.2 服务端 API 分流实现

```python
# server/routers/updates.py 中
import hashlib


def _select_channel(client_ip: str) -> str:
    """基于客户端 IP 做一致性哈希分流。"""
    hash_val = int(hashlib.md5(client_ip.encode()).hexdigest(), 16) % 100
    if hash_val < 10:    # 10% → canary
        return "canary"
    return "stable"


@router.get("/check")
async def check_update(request: Request):
    client_version = request.headers.get("x-client-version", "")
    client_ip = request.client.host if request.client else ""

    manifest = _load_manifest()
    channel = _select_channel(client_ip)

    # 从对应通道读取版本信息
    channel_info = manifest.get("channels", {}).get(channel, {})
    remote_ver = channel_info.get("version") or manifest.get("latest_version", "")

    # 比对版本...
```

### 6.3 发布流程

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  内测     │ → │  金丝雀   │ → │  全量     │ → │  回滚     │
│  Jenkins  │   │  10%用户  │   │  100%用户 │   │  version  │
│  手动触发  │   │  自动监控  │   │  自动发布  │   │  json回退 │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
```

**回滚操作：** 修改 `version.json` 中的 `latest_version` 即可：

```bash
ssh root@nginx-server
sed -i 's/"latest_version": "2.1.2"/"latest_version": "2.1.1"/' /var/www/updates/version.json
```

客户端下次启动检测时发现本地版本比服务端版本更新，自动忽略，完成回滚。

---

## 七、安全考虑

| 措施 | 说明 |
|------|------|
| **SHA256 校验** | 打包后计算 hash 写入 manifest，下载后校验 |
| **HTTPS** | Nginx 配置 Let's Encrypt 证书，`update_url` 使用 `https://` |
| **用户数据保护** | 替换时排除 `config/`、`data/`、`logs/`、`outputs/`、`accounts/` |
| **回滚安全** | 更新前自动备份旧目录，`updater.bat` 保留 5 秒后清理 |
| **断点续传** | 下载支持 `Range` 头，网络中断可恢复 |

---

## 八、与现有架构的整合路径

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| **1** | 服务端：实现 `GET /api/updates/check` | `server/routers/updates.py` |
| **2** | 服务端：添加 VersionCheckMiddleware | `server/main.py` |
| **3** | 服务端：编写 `hot_reload.sh` 热更新脚本 | `/opt/server/scripts/` |
| **4** | 客户端：实现 `updater/version_worker.py` | 新增 |
| **5** | 客户端：实现 `updater/download_worker.py` | 新增 |
| **6** | 客户端：实现 `updater/updater_dialog.py` | 新增 |
| **7** | 客户端：实现 `updater/install.py` + `updater.bat` | 新增 |
| **8** | 客户端：修改 `gui_main.py` 接入启动检测 | 修改 |
| **9** | 客户端：统一 HTTP 请求封装添加版本头 | 修改 `api_client.py` |
| **10** | 运维：配置 Nginx + Jenkins Pipeline | 运维 |
| **11** | 测试全流程 | 测试 |

### 复用的现有基础设施

| 现有模块 | 用途 |
|----------|------|
| `version.py` | 版本号唯一来源，供客户端上报和服务端比对 |
| `update_checker.py` | `_compare_versions()` 版本比对函数 |
| `base_worker.py` | `VersionCheckWorker` / `DownloadWorker` 继承 |
| `config/update.json` | 客户端配置 `update_url`（默认复用 `compute_server_url`）|
| `config/paths.py` | `UPDATE_CONFIG_FILE` 定位更新配置 |
| `ai_config.json` | 从中读取 `compute_server_url` 作为默认更新地址 |

---

## 九、关键区别总结

| 特性 | 原方案 | 现方案（服务端驱动） |
|------|--------|-------------------|
| **更新触发** | 客户端定时轮询 | 启动时一次性检测 + 用户手动 |
| **后台定时器** | 有（interval timer） | **无** |
| **检测目标** | Nginx 静态 `version.json` | 服务端 `/api/updates/check` |
| **被动检测** | ❌ 不支持 | ✅ 服务端 API 响应头中携带版本信息 |
| **配置便捷性** | 需单独配置 `update_url` | **默认复用** `compute_server_url` |
| **服务端热更新** | 可选 | ✅ FastAPI 端点 + 热更新脚本完整实现 |
