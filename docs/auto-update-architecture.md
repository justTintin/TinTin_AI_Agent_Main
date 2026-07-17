# 螺丝钉-电商智能体矩阵 · 自动更新架构方案

> 版本：v1.0 | 技术栈：Python + PySide6 (Qt 6) + Jenkins + Nginx | 架构：客户端-服务端统一更新

---

## 一、架构总览

### 1.1 整体流程

```
  Git Push (tag / branch)
       │
       ▼
┌─────────────────────────────────────────────────────┐
│                   Jenkins Pipeline                    │
│  ① 拉取代码 → ② 更新 version.py → ③ PyInstaller 打包 │
│  ④ 生成 version.json manifest → ⑤ 上传到 Nginx 服务器  │
└──────────────────────┬──────────────────────────────┘
                       │ SCP / RSYNC
                       ▼
┌─────────────────────────────────────────────────────┐
│                    Nginx 更新服务器                     │
│  /var/www/updates/                                   │
│  ├── version.json         ← 版本清单（蓝绿开关）        │
│  ├── updates/             ← 更新包目录                  │
│  │   ├── v2.1.1.zip                                     │
│  │   └── v2.1.2.zip                                     │
│  ├── stable/              ← 稳定版包                    │
│  ├── canary/              ← 金丝雀版包                   │
│  └── archive/             ← 历史版本归档                 │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP GET (定时/手动)
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐   ┌──────────────────┐
│  客户端桌面应用     │   │  服务端计算节点     │
│  (PySide6 GUI)   │   │  (FastAPI)       │
│  定时/手动检查更新  │   │  提供 /update/* API│
│  下载ZIP → 替换   │   │  可复用更新通道    │
│  重启应用         │   │  热更新/重启服务   │
└──────────────────┘   └──────────────────┘
```

### 1.2 现有基础

本项目已具备以下基础模块，本方案在此之上做完整实现：

| 模块 | 文件 | 状态 |
|------|------|------|
| 版本号管理 | `studio/version.py` | ✅ 已有（CalVer: 主.次.修订.构建日期） |
| 更新配置 | `studio/config/update.json` | ✅ 已有（update_url / channel / check_on_startup） |
| 更新检查器 | `studio/utils/update_checker.py` | ✅ 已有骨架（版本比对、配置读写，TODO待实现） |
| 配置路径 | `studio/config/paths.py` | ✅ 已有（UPDATE_CONFIG_FILE 常量） |
| 后台工作器 | `studio/utils/base_worker.py` | ✅ 已有（BaseWorker QThread 基类） |

---

## 二、客户端方案（Client Side）

### 2.1 目录结构

```
studio/
├── updater/                          # ★ 新增：自动更新模块
│   ├── __init__.py                   #   导出版本检查/下载/安装接口
│   ├── check_worker.py               #   CheckUpdateWorker：后台检查更新
│   ├── download_worker.py            #   DownloadWorker：后台下载 + 进度
│   ├── updater_dialog.py             #   更新对话框 UI
│   ├── install.py                    #   安装逻辑（解压、替换、重启）
│   └── updater.bat                   #   引导替换脚本（绕过 exe 占用）
│
├── utils/
│   ├── update_checker.py             #   已有：同步检查更新（将被 check_worker 调用）
│   └── base_worker.py                #   已有：BaseWorker QThread 基类
│
├── config/
│   ├── update.json                   #   已有：更新配置
│   └── paths.py                      #   已有：路径常量
│
├── version.py                        #   已有：版本号
└── gui_main.py                       #   修改：接入更新入口
```

### 2.2 新增模块实现

#### 2.2.1 `updater/__init__.py` — 模块导出口

```python
# -*- coding: utf-8 -*-
"""
自动更新模块。

提供完整的更新流程：检查 → 下载 → 安装 → 重启。
所有 Worker 基于 BaseWorker，异步非阻塞，不卡界面。
"""
from updater.check_worker import CheckUpdateWorker
from updater.download_worker import DownloadWorker
from updater.updater_dialog import UpdateDialog
from updater.install import install_update, get_updater_bat_path
```

#### 2.2.2 `updater/check_worker.py` — 版本检查 Worker

对应项目已有的 `BaseWorker` 模式，与 `RateClipsWorker`、`_SearchWorker` 等实现一致：

```python
# -*- coding: utf-8 -*-
"""
后台检查更新 Worker。

向 Nginx 服务器请求 version.json，比对本地版本号。
"""
import json
import requests
from PySide6.QtCore import Signal

from utils.base_worker import BaseWorker
from utils.update_checker import load_update_config, get_local_version, _compare_versions
from utils.logger_utils import log


class CheckUpdateWorker(BaseWorker):
    """异步检查更新，不阻塞 GUI。"""
    finished = Signal(dict)  # {available, latest_version, download_url, file_hash, file_size, release_notes, force_update}

    def __init__(self, parent=None):
        super().__init__(parent)

    def do_work(self):
        cfg = load_update_config()
        update_url = (cfg.get("update_url") or "").strip()
        local_ver = get_local_version()

        if not update_url:
            self.finished.emit({
                "available": False,
                "reason": "更新服务器未配置",
                "local_version": local_ver,
            })
            return

        try:
            # 请求 version.json（Nginx 静态文件或服务端 API）
            resp = requests.get(
                f"{update_url.rstrip('/')}/updates/version.json",
                timeout=10,
                headers={"X-Client-Version": local_ver},
            )
            resp.raise_for_status()
            info = resp.json()

            remote_ver = info.get("latest_version", "")
            if not remote_ver:
                self.finished.emit({"available": False, "reason": "服务器返回版本号为空"})
                return

            available = _compare_versions(local_ver, remote_ver) == 1

            self.finished.emit({
                "available": available,
                "reason": "" if available else "已是最新版本",
                "local_version": local_ver,
                "latest_version": remote_ver,
                "download_url": info.get("download_url", ""),
                "file_hash": info.get("file_hash", ""),
                "file_size": info.get("file_size", 0),
                "release_notes": info.get("release_notes", ""),
                "force_update": info.get("force_update", False),
            })

        except requests.ConnectionError:
            self.finished.emit({"available": False, "reason": "无法连接到更新服务器"})
        except Exception as e:
            log.warning(f"检查更新失败: {e}")
            self.finished.emit({"available": False, "reason": str(e)})
```

#### 2.2.3 `updater/download_worker.py` — 下载 Worker（带进度）

```python
# -*- coding: utf-8 -*-
"""
后台下载更新包 Worker。

支持：断点续传（Range）、下载进度回调、SHA256 校验。
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
        # 下载到临时目录
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

#### 2.2.4 `updater/install.py` — 安装逻辑

```python
# -*- coding: utf-8 -*-
"""
更新安装逻辑。

PyInstaller onedir 模式下，exe 和大量 dll 被占用无法直接覆盖，
因此通过 updater.bat 引导替换：
  ① 备份旧目录 → ② 解压新包 → ③ 启动主程序 → ④ 后台清理备份
"""
import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path
from config.paths import PROJECT_ROOT, RUNTIME_DIR
from utils.logger_utils import log

# 替换时排除的用户数据目录（不覆盖）
EXCLUDE_DIRS = [
    "config",
    "logs",
    "data",
    "outputs",
    "accounts",
    "playwright_profile",
]
EXCLUDE_FILES = [
    "config.ini",
]


def _should_exclude(rel_path: str) -> bool:
    """判断路径是否属于应排除的用户数据。"""
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
    返回 False 表示安装失败。
    """
    try:
        # 当前运行目录（dist/螺丝钉-电商智能体矩阵/）
        current_dir = Path(sys.argv[0]).parent if getattr(sys, "frozen", False) else PROJECT_ROOT
        # 若为开发模式，使用 PROJECT_ROOT
        if not getattr(sys, "frozen", False):
            current_dir = PROJECT_ROOT

        # 生成 updater.bat
        bat_path = current_dir / "updater.bat"
        zip_dest = current_dir / "_update_package.zip"
        backup_dir = current_dir.parent / (current_dir.name + ".bak")

        # 移动 zip 到目标目录
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

rem 恢复用户数据（从备份复制）
echo 恢复配置...
xcopy "{backup_dir}\\config" "{current_dir}\\config" /E /I /Y /Q >nul
xcopy "{backup_dir}\\data" "{current_dir}\\data" /E /I /Y /Q >nul
if exist "{backup_dir}\\accounts" xcopy "{backup_dir}\\accounts" "{current_dir}\\accounts" /E /I /Y /Q >nul
if exist "{backup_dir}\\outputs" xcopy "{backup_dir}\\outputs" "{current_dir}\\outputs" /E /I /Y /Q >nul

rem 删除更新包
del "{zip_dest}" >nul

rem 启动主程序
echo 启动新版本...
start "" "{current_dir}\\螺丝钉-电商智能体矩阵.exe"

rem 后台清理备份
start /b cmd /c "timeout /t 5 /nobreak >nul & rmdir /s /q "{backup_dir}""
exit
"""
        with open(str(bat_path), "w", encoding="utf-8") as f:
            f.write(bat_content)

        log.info(f"更新包已就绪: {zip_dest}")
        log.info(f"引导脚本已生成: {bat_path}")
        return True

    except Exception as e:
        log.error(f"安装更新失败: {e}")
        return False
```

#### 2.2.5 `updater/updater_dialog.py` — 更新对话框

```python
# -*- coding: utf-8 -*-
"""
更新对话框。

三种场景：
  - 有新版本 → 显示版本信息 + "立即更新"按钮
  - 下载中 → 进度条 + 速度显示
  - 安装中 → 提示用户等待
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextBrowser,
)
from PySide6.QtCore import Qt, QTimer
from updater.install import install_update


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

        # 标题
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.lbl_title)

        # 版本信息
        self.lbl_version = QLabel()
        layout.addWidget(self.lbl_version)

        # 更新说明
        self.notes_browser = QTextBrowser()
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setMaximumHeight(180)
        layout.addWidget(self.notes_browser)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 状态提示
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("muted_text")
        layout.addWidget(self.lbl_status)

        # 按钮行
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
        self.lbl_title.setText(f"发现新版本 v{info.get('latest_version', '')}")
        self.lbl_version.setText(
            f"当前版本: v{info.get('local_version', '')}  →  "
            f"最新版本: v{info.get('latest_version', '')}"
        )
        notes = info.get("release_notes", "暂无更新说明")
        self.notes_browser.setPlainText(notes)

        if info.get("force_update", False):
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

        # 启动下载 Worker
        from updater.download_worker import DownloadWorker
        self.download_worker = DownloadWorker(
            download_url=self.update_info["download_url"],
            expected_hash=self.update_info.get("file_hash", ""),
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
        # 执行安装（生成 updater.bat）
        if install_update(zip_path):
            self.lbl_status.setText("安装完成，正在重启...")
            # 启动 updater.bat，然后退出主程序
            import subprocess
            import sys
            from pathlib import Path
            bat = Path(sys.argv[0]).parent / "updater.bat"
            subprocess.Popen([str(bat)], shell=True)
            # 退出主程序
            self.accept()
            QApplication.quit()
        else:
            self.lbl_status.setText("安装失败，请稍后重试")
            self.btn_confirm.setEnabled(True)

    def _on_download_error(self, msg: str):
        self.lbl_status.setText(f"下载失败: {msg}")
        self.btn_confirm.setEnabled(True)
        self.btn_skip.setEnabled(True)
```

### 2.3 修改 `gui_main.py` 接入点

在 MainWindow 启动流程中添加以下逻辑：

```python
# gui_main.py 修改示例

class MainWindow(QMainWindow, ...):
    def __init__(self):
        super().__init__()
        # ... 现有初始化代码 ...

        # 延迟启动更新检查（等待主窗口展示后再检查）
        QTimer.singleShot(3000, self._delayed_update_check)

    def _delayed_update_check(self):
        """启动3秒后检查更新，不干扰启动体验。"""
        cfg = load_update_config()
        if not cfg.get("check_on_startup", False):
            return

        self._check_update_worker = CheckUpdateWorker()
        self._check_update_worker.finished.connect(self._on_update_check_result)
        self._check_update_worker.start()

    def _on_update_check_result(self, result: dict):
        if result.get("available"):
            dialog = UpdateDialog(result, self)
            dialog.exec()

    def _on_menu_check_update(self):
        """菜单/按钮「检查更新」触发。"""
        self.lbl_status.setText("正在检查更新...")
        w = CheckUpdateWorker()
        w.finished.connect(lambda r: self._on_update_check_result(r))
        w.start()
```

在菜单或设置页面添加「检查更新」按钮：

```python
# 侧边栏或设置页面
self.btn_check_update = QPushButton("检查更新")
self.btn_check_update.setObjectName("secondary_button")
self.btn_check_update.clicked.connect(self.main_window._on_menu_check_update)
```

### 2.4 更新配置 (`config/update.json`)

```json
{
  "update_url": "http://update.your-server.com",
  "channel": "stable",
  "check_on_startup": true,
  "last_check": "2026-07-17T19:30:00.000000"
}
```

| 字段 | 说明 |
|------|------|
| `update_url` | 更新服务器地址（Nginx 或服务端 API） |
| `channel` | 更新通道：`stable` / `canary` / `beta` |
| `check_on_startup` | 启动时自动检查 |
| `last_check` | 上次检查时间 |

---

## 三、服务端方案（Server Side）

### 3.1 Nginx 静态文件分发（推荐）

#### 3.1.1 目录结构

```
/var/www/updates/                        # Nginx root
├── version.json                         # ★ 版本清单（客户端/服务端共用）
├── updates/                             # 更新包存放
│   ├── v2.1.0.zip
│   ├── v2.1.1.zip
│   └── v2.1.2.zip
├── server-updates/                      # 服务端更新包
│   ├── server-v1.2.0.zip
│   └── server-v1.2.1.zip
├── stable/                              # 稳定版（软链接指向）
│   └── latest.zip -> ../updates/v2.1.1.zip
├── canary/                              # 金丝雀版
│   └── latest.zip -> ../updates/v2.1.2.zip
└── archive/                             # 归档
    ├── v2.0.9.zip
    └── v2.1.0.zip
```

#### 3.1.2 `version.json` 清单格式

```json
{
  "latest_version": "2.1.2.20260717",
  "min_version": "2.0.0.20260101",
  "release_notes": "## v2.1.2 更新内容\n\n### ✨ 新增\n- 自动更新模块\n- 素材检索显示文件路径\n\n### 🐛 修复\n- 启动崩溃问题\n- 任务队列卡顿\n\n### ⚡ 优化\n- AI 评分性能提升\n\n---\n完整变更日志: https://git.your-server.com/changelog",
  "download_url": "/updates/v2.1.2.zip",
  "file_hash": "sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",
  "file_size": 524288000,
  "force_update": false,
  "server_update": {
    "latest_version": "1.2.1.20260717",
    "download_url": "/server-updates/server-v1.2.1.zip",
    "file_hash": "sha256:...",
    "file_size": 104857600,
    "release_notes": "服务端更新内容..."
  },
  "channels": {
    "stable": {
      "version": "2.1.1.20260709",
      "download_url": "/updates/v2.1.1.zip"
    },
    "canary": {
      "version": "2.1.2.20260717",
      "download_url": "/updates/v2.1.2.zip"
    }
  }
}
```

#### 3.1.3 Nginx 配置

```nginx
# /etc/nginx/sites-available/updates.your-server.com

server {
    listen 80;
    server_name updates.your-server.com;

    root /var/www/updates;
    index version.json;

    # 对 version.json 禁用缓存，客户端每次拿最新清单
    location /version.json {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Access-Control-Allow-Origin "*";
    }

    # 更新包下载（支持大文件断点续传）
    location /updates/ {
        add_header Cache-Control "public, max-age=3600";
        add_header Access-Control-Allow-Origin "*";

        # 断点续传支持
        add_header Accept-Ranges bytes;

        # 限速 50MB/s，防止占满带宽
        limit_rate 50m;
    }

    location /server-updates/ {
        # 同更新包配置
        add_header Cache-Control "public, max-age=3600";
        add_header Accept-Ranges bytes;
        limit_rate 50m;
    }

    # 金丝雀发布：按 IP 范围分流
    # 10% 的客户端返回 canary 通道版本
    location = /version.json {
        content_by_lua_block {
            local client_ip = ngx.var.remote_addr
            local hash = 0
            for i = 1, #client_ip do
                hash = hash + string.byte(client_ip, i)
            end
            local rand = hash % 100

            -- 默认用 stable
            local channel = "stable"
            if rand < 10 then  -- 10% 的流量进 canary
                channel = "canary"
            end

            -- 读取 version.json，替换 download_url 指向
            local file = io.open("/var/www/updates/version.json", "r")
            if file then
                local content = file:read("*all")
                file:close()
                ngx.say(content)
            else
                ngx.status = 404
                ngx.say("{}")
            end
        }
    }

    # 服务端热更新 API 代理
    location /api/updates/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 客户端更新通道选择 API
    location /api/channel {
        add_header Content-Type application/json;
        return 200 '{"channel": "stable", "update_url": "http://updates.your-server.com"}';
    }
}
```

### 3.2 服务端 FastAPI 更新接口

在现有服务端（`compute_server`）中新增更新相关 API，使服务端自身也能热更新。

#### 3.2.1 API 接口定义

```python
# server/updates/router.py
"""
服务端更新路由。

提供：
  - GET  /api/updates/version     ← 服务端版本检查
  - POST /api/updates/apply       ← 触发服务端热更新
  - GET  /api/updates/status      ← 当前更新状态
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import sys
import json
import subprocess
from datetime import datetime

router = APIRouter(prefix="/api/updates", tags=["updates"])

SERVER_VERSION = "1.2.1"  # 服务端自身版本号
UPDATE_CONFIG_PATH = "/var/www/updates/version.json"


class UpdateStatus(BaseModel):
    current_version: str
    latest_version: str = ""
    update_available: bool = False
    last_check: str = ""
    is_updating: bool = False


@router.get("/version")
async def check_server_update():
    """检查服务端是否有更新。"""
    try:
        with open(UPDATE_CONFIG_PATH, "r") as f:
            manifest = json.load(f)

        server_info = manifest.get("server_update", {})
        latest = server_info.get("latest_version", "")

        return {
            "current_version": SERVER_VERSION,
            "latest_version": latest,
            "update_available": latest > SERVER_VERSION,
            "download_url": server_info.get("download_url", ""),
            "file_hash": server_info.get("file_hash", ""),
            "file_size": server_info.get("file_size", 0),
            "release_notes": server_info.get("release_notes", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply")
async def apply_server_update():
    """应用服务端热更新。

    流程：下载 → 解压到临时目录 → 执行更新脚本 → 重启服务进程。
    """
    # 此接口应由运维人员或 Jenkins 触发，而非客户端直接调用
    try:
        # 使用 subprocess 启动后台更新脚本
        subprocess.Popen(
            ["bash", "/opt/server/scripts/hot_reload.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"status": "ok", "message": "更新已在后台启动"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_update_status():
    """获取当前服务端更新状态。"""
    return UpdateStatus(
        current_version=SERVER_VERSION,
        last_check=datetime.now().isoformat(),
    )
```

#### 3.2.2 服务端热更新脚本 (`hot_reload.sh`)

```bash
#!/bin/bash
# /opt/server/scripts/hot_reload.sh
# 服务端热更新：下载 → 解压 → 替换代码 → 重启 uvicorn

set -e

MANIFEST="/var/www/updates/version.json"
TMP_DIR="/tmp/server_update"
TARGET_DIR="/opt/server"

# 读取 manifest
LATEST_VER=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['server_update']['latest_version'])")
DL_URL=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['server_update']['download_url'])")

echo "[更新] 发现新版本: $LATEST_VER"

# 下载
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
wget -q "http://localhost$DL_URL" -O "$TMP_DIR/update.zip"

# 解压
cd "$TMP_DIR"
unzip -q update.zip -d extracted

# 替换代码（排除配置文件）
rsync -av --delete \
    --exclude='config/*' \
    --exclude='logs/*' \
    --exclude='.env' \
    extracted/ "$TARGET_DIR/"

# 重启服务
systemctl restart compute-server

# 清理
rm -rf "$TMP_DIR"

echo "[更新] 完成: $LATEST_VER"
```

### 3.3 服务端更新通道选择 API

客户端启动时首先请求此接口确定使用哪个更新通道：

```python
@router.get("/api/channel")
async def get_update_channel(client_version: str = "", client_ip: str = ""):
    """
    更新通道分配。

    按 IP 或 client_id 做权重分配：
      - 默认 90% → stable（稳定版）
      - 10% → canary（金丝雀版）
    可通过运维后台手动调整白名单 IP 到 canary。
    """
    import hashlib

    # 基于 IP 做一致性哈希分配
    hash_val = int(hashlib.md5(client_ip.encode()).hexdigest(), 16) % 100

    channel = "canary" if hash_val < 10 else "stable"

    return {
        "channel": channel,
        "update_url": "http://updates.your-server.com",
        "check_interval": 3600,  # 建议检查间隔（秒）
    }
```

---

## 四、CI/CD 流水线（Jenkins）

### 4.1 Jenkinsfile

```groovy
pipeline {
    agent any

    environment {
        PROJECT_ROOT = "D:\\code\\TinTin_AI_Agent_Client-0713\\TinTin_AI_Agent_Main"
        NGINX_HOST = "update.your-server.com"
        NGINX_UPDATES_DIR = "/var/www/updates"
    }

    parameters {
        choice(name: 'CHANNEL', choices: ['stable', 'canary', 'beta'], description: '发布通道')
        string(name: 'RELEASE_NOTES', defaultValue: '', description: '更新说明（支持 Markdown）')
        booleanParam(name: 'FORCE_UPDATE', defaultValue: false, description: '是否强制更新')
    }

    stages {
        stage('拉取代码') {
            steps {
                checkout scm
            }
        }

        stage('更新版本号') {
            steps {
                bat '''
                    cd %PROJECT_ROOT%
                    python -c "
import datetime
now = datetime.datetime.now()
base = open('studio/version.py').read().split('__base_version__ = \"')[1].split('\"')[0]
# 若参数指定版本则用参数，否则保持现有 base_version
print(f'当前版本: {base}.{now.strftime(\\\"%Y%m%d\\\")}')
"
                '''
            }
        }

        stage('运行测试') {
            steps {
                bat 'cd %PROJECT_ROOT% && python -m pytest studio/tests/ --junitxml=report.xml'
            }
        }

        stage('PyInstaller 打包') {
            steps {
                bat 'cd %PROJECT_ROOT% && powershell -File run_pyinstaller.ps1'
            }
        }

        stage('生成更新包') {
            steps {
                script {
                    def version = readFile('studio/version.py').findAll(/__version__ = "(.*?)"/)[0]
                    def buildDir = "dist/螺丝钉-电商智能体矩阵"

                    bat """
                        cd %PROJECT_ROOT%

                        REM 压缩打包产物
                        powershell -Command "Compress-Archive -Path ${buildDir}/* -DestinationPath updates/${version}.zip -Force"

                        REM 计算 SHA256
                        for /f %%i in ('certutil -hashfile updates/${version}.zip SHA256 ^| findstr /v "CertUtil"') do set HASH=%%i
                        echo SHA256: %HASH%
                    """
                }
            }
        }

        stage('生成 version.json') {
            steps {
                script {
                    def version = readFile('studio/version.py').findAll(/__version__ = "(.*?)"/)[0]
                    def fileSize = fileExists("updates/${version}.zip") ? filesize("updates/${version}.zip") : 0
                    def notes = params.RELEASE_NOTES ?: "自动构建版本 ${version}"
                    def force = params.FORCE_UPDATE ? 'true' : 'false'
                    
                    def manifest = """
{
  "latest_version": "${version}",
  "min_version": "2.0.0.20260101",
  "release_notes": ${toJSON(notes)},
  "download_url": "/updates/${version}.zip",
  "file_size": ${fileSize},
  "force_update": ${force},
  "channels": {
    "${params.CHANNEL}": {
      "version": "${version}",
      "download_url": "/updates/${version}.zip"
    }
  }
}
"""
                    writeFile file: 'updates/version.json', text: manifest
                }
            }
        }

        stage('发布到 Nginx') {
            steps {
                withCredentials([sshUserPrivateKey(credentialsId: 'nginx-deploy', keyFileVariable: 'KEY')]) {
                    script {
                        // 将更新包和 manifest 推送到 Nginx 服务器
                        sh """
                            scp -i ${KEY} updates/*.zip root@${NGINX_HOST}:${NGINX_UPDATES_DIR}/updates/
                            scp -i ${KEY} updates/version.json root@${NGINX_HOST}:${NGINX_UPDATES_DIR}/version.json
                        """
                    }
                }
            }
        }

        stage('通知') {
            steps {
                // 发送企业微信/钉钉通知
                echo "构建完成: ${version} → ${params.CHANNEL} 通道"
            }
        }
    }

    post {
        failure {
            // 构建失败通知
            echo "构建失败，请检查 Jenkins 日志"
        }
    }
}
```

### 4.2 `pack_release.py` — 本地打包脚本（新增）

与 Jenkins 流程对应，开发者也可在本地运行：

```python
# -*- coding: utf-8 -*-
"""
发布打包脚本。

用法：
  python pack_release.py                    # 打包 stable 通道
  python pack_release.py --channel canary  # 打包金丝雀通道
  python pack_release.py --deploy           # 打包 + 上传到 Nginx
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STUDIO_DIR = os.path.join(PROJECT_ROOT, "studio")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "updates")


def get_version() -> str:
    """从 version.py 读取完整版本号。"""
    sys.path.insert(0, STUDIO_DIR)
    from version import __version__
    return __version__


def build_pyinstaller():
    """执行 PyInstaller 打包。"""
    print("[1/5] 执行 PyInstaller 打包...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "build_app.spec"],
        cwd=PROJECT_ROOT,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"打包失败:\n{result.stderr}")
        sys.exit(1)
    print("打包成功")


def create_zip(version: str) -> str:
    """压缩 dist 目录为 ZIP。"""
    print(f"[2/5] 创建更新包 v{version}...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    zip_path = os.path.join(OUTPUT_DIR, f"v{version}.zip")

    app_dir = os.path.join(DIST_DIR, "螺丝钉-电商智能体矩阵")
    if not os.path.isdir(app_dir):
        print(f"错误: 未找到 dist 目录: {app_dir}")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(app_dir):
            for f in files:
                file_path = os.path.join(root, f)
                arcname = os.path.relpath(file_path, app_dir)
                zf.write(file_path, arcname)

    print(f"ZIP 已创建: {zip_path} ({os.path.getsize(zip_path) / 1048576:.1f}MB)")
    return zip_path


def generate_manifest(zip_path: str, version: str, channel: str = "stable",
                      force: bool = False, notes: str = ""):
    """生成 version.json。"""
    print("[3/5] 生成 version.json...")

    sha256 = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)

    manifest = {
        "latest_version": version,
        "min_version": "2.0.0.20260101",
        "release_notes": notes or f"自动构建版本 {version}",
        "download_url": f"/updates/v{version}.zip",
        "file_hash": f"sha256:{sha256.hexdigest()}",
        "file_size": os.path.getsize(zip_path),
        "force_update": force,
        "channels": {
            channel: {
                "version": version,
                "download_url": f"/updates/v{version}.zip",
            }
        },
        "server_update": {
            "latest_version": "",
            "download_url": "",
            "file_hash": "",
            "file_size": 0,
            "release_notes": "",
        },
    }

    manifest_path = os.path.join(OUTPUT_DIR, "version.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Manifest 已生成: {manifest_path}")
    return manifest


def deploy_to_nginx(host: str = "update.your-server.com"):
    """上传更新包和 manifest 到 Nginx 服务器。"""
    print(f"[4/5] 上传到 {host}...")
    result = subprocess.run([
        "scp",
        "-r",
        f"{OUTPUT_DIR}/.",
        f"root@{host}:/var/www/updates/",
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"上传失败:\n{result.stderr}")
        sys.exit(1)
    print("上传成功")


def update_version(base_version: str = None):
    """更新 version.py 中的版本号（可选）。"""
    print("[0/5] 更新版本号...")
    ver_path = os.path.join(STUDIO_DIR, "version.py")
    now = datetime.now().strftime("%Y%m%d")
    if base_version:
        new_ver = f'__base_version__ = "{base_version}"'
    else:
        # 读取当前 base_version，构建日期更新为今天
        with open(ver_path, "r", encoding="utf-8") as f:
            content = f.read()
        import re
        match = re.search(r'__base_version__ = "([^"]+)"', content)
        if not match:
            print("无法读取 __base_version__")
            sys.exit(1)
        new_ver = f'__base_version__ = "{match.group(1)}"'

    # 更新构建日期行
    lines = []
    with open(ver_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("__base_version__"):
                lines.append(f'{new_ver}\n')
            elif line.startswith("__build_date__"):
                lines.append(f'__build_date__ = "{now}"\n')
            else:
                lines.append(line)
    with open(ver_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"版本号已更新: base={new_ver}, build={now}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="发布打包工具")
    parser.add_argument("--channel", default="stable", choices=["stable", "canary", "beta"])
    parser.add_argument("--deploy", action="store_true", help="打包后上传到 Nginx")
    parser.add_argument("--force", action="store_true", help="强制更新")
    parser.add_argument("--notes", default="", help="更新说明")
    parser.add_argument("--version", help="指定版本号（如 2.1.2）")
    args = parser.parse_args()

    if args.version:
        update_version(args.version)

    version = get_version()
    print(f"目标版本: {version} (通道: {args.channel})")

    build_pyinstaller()
    zip_path = create_zip(version)
    generate_manifest(zip_path, version, args.channel, args.force, args.notes)

    if args.deploy:
        deploy_to_nginx()

    print(f"[5/5] 发布完成! 版本 {version} → {args.channel}")
```

---

## 五、蓝绿发布 / 金丝雀发布策略

### 5.1 实现原理

通过 `version.json` 作为 **流量开关**，控制不同客户端拿到的版本号。

```
┌────────────────────────────────────────────┐
│              version.json                    │
│                                              │
│  channels: {                                 │
│    "stable": { version: "2.1.1" },  ← 90%    │
│    "canary": { version: "2.1.2" },  ← 10%    │
│    "beta":   { version: "2.2.0" }   ← 测试组 │
│  }                                           │
└────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│  通道选择 API      │
│  GET /api/channel │
│                   │
│  IP hash → 10% → canary │
│  IP hash → 90% → stable │
└──────────────────┘
```

### 5.2 发布流程

| 阶段 | 操作 | 影响范围 |
|------|------|---------|
| **内测** | Jenkins 构建 canary 包 → 手动更新 Nginx | 内部开发机 |
| **金丝雀** | Nginx 设置 10% 流量到 canary version.json | 10% 外部用户 |
| **全量** | 将 stable 通道的 version 指向新版本 | 所有用户 |
| **回滚** | 将 stable 通道的 version 指回旧版本 | 所有用户回到旧版 |

### 5.3 回滚操作

回滚只需修改 `version.json` 中的版本号，无需重新打包：

```bash
# 回滚到 v2.1.1
ssh root@nginx-server
sed -i 's/"latest_version": "2.1.2"/"latest_version": "2.1.1"/' /var/www/updates/version.json
# 确保 stable 通道也指向旧版
sed -i 's/"version": "2.1.2"/"version": "2.1.1"/' /var/www/updates/version.json
```

5 分钟后所有客户端 `check_interval` 到期，拿到旧版本号，发现本地版本更新，自动忽略。

如果遇到严重问题需要立即阻止更新：

```nginx
# Nginx 返回空 manifest，客户端检测到无更新
location = /version.json {
    return 200 '{"latest_version": "", "min_version": ""}';
}
```

---

## 六、安全考虑

### 6.1 更新包完整性校验

- Jenkins 在打包后计算 ZIP 的 SHA256，写入 `version.json`
- 客户端下载完成后校验 SHA256，不匹配则丢弃
- 防止传输损坏或中间人篡改

### 6.2 HTTPS

- Nginx 应配置 HTTPS（Let's Encrypt 免费证书）
- `update_url` 配置为 `https://` 开头
- 防止中间人攻击，确保客户端下载的是官方包

### 6.3 用户数据保护

- 更新替换时 **排除** `config/`、`data/`、`logs/`、`outputs/`、`accounts/` 目录
- `updater.bat` 在解压后执行 `xcopy` 从备份目录恢复用户数据
- 更新前后 `config/update.json` 保留，确保更新配置不丢失

### 6.4 回滚安全

- 更新前自动备份旧版本目录（`xxx.bak`）
- `updater.bat` 保留备份 5 秒后后台清理
- 若新版本启动失败，用户可以手动从 `.bak` 目录恢复

---

## 七、与现有架构的整合路径

### 实施步骤

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| **1** | 实现 `updater/check_worker.py`（异步版本检查） | 新增 |
| **2** | 实现 `updater/download_worker.py`（带进度下载） | 新增 |
| **3** | 实现 `updater/updater_dialog.py`（更新 UI） | 新增 |
| **4** | 实现 `updater/install.py`（安装 + updater.bat） | 新增 |
| **5** | 实现 `pack_release.py`（本地打包 + 上传） | 新增 |
| **6** | 修改 `gui_main.py` 接入更新入口 | 修改 |
| **7** | 配置 Nginx 服务器 | 运维 |
| **8** | 编写 Jenkins Pipeline | 运维 |
| **9** | 配置服务端更新 API | 修改服务端 |
| **10** | 测试全流程：打包 → 发布 → 更新 → 回滚 | 测试 |

### 复用的现有基础设施

```
现有模块                    新增模块
─────────                  ──────────
version.py          →      pack_release.py 读取版本号
update_checker.py   →      check_worker.py 调用其版本比对函数
base_worker.py      →      CheckUpdateWorker / DownloadWorker 继承
config/update.json  →      客户端配置 update_url
config/paths.py     →      定位更新配置文件
```

---

## 八、常见问题

### Q: 打包产物非常大（1-2GB），全量下载太慢怎么办？

**方案 A：按文件增量更新**

在 Jenkins 构建时生成 `manifest-{version}.json`，记录每个文件的 SHA256：

```json
{
  "version": "2.1.2.20260717",
  "files": [
    {"path": "studio/gui/vector_search_page.py", "hash": "abc...", "size": 8123},
    {"path": "PySide6/QtCore.pyd", "hash": "def...", "size": 5242880}
  ]
}
```

客户端比对本地文件 hash，只下载变化的文件。**但实现较复杂**，建议第一版先用全量包 + `limit_rate` 限速。

**方案 B：分块下载 + 断点续传**

`DownloadWorker` 已支持 `stream=True` 和 `Range` 断点续传。建议配合 CDN 加速。

### Q: 开发模式（非 PyInstaller 打包）如何更新？

开发模式下不走 `updater.bat`，改为 `git pull`：

```python
# updater/install.py 中判断
if not getattr(sys, "frozen", False):
    # 开发模式：直接 git pull
    subprocess.run(["git", "pull"], cwd=PROJECT_ROOT)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements_gui.txt"])
else:
    # 打包模式：updater.bat 替换
    ...bat流程...
```

### Q: 服务端热更新如何保证不中断服务？

Nginx 作为反向代理，用 `upstream` 做无感重启：

```nginx
upstream compute_server {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;  # 热更新时启动新实例
}
```

更新流程：
```
① 启动新实例（8002 端口加载新代码）
② 更新 Nginx upstream 权重，逐步切流量到 8002
③ 确认 8002 正常 → 关闭 8001 旧实例
④ 更新完成
```
