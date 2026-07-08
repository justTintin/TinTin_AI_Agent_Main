# TinTin AI Agent 部署与配置指南

## 1. 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 64位 或 Ubuntu 24.04+ |
| GPU | NVIDIA GPU，CUDA 12.x，显存 ≥ 8GB（推荐 24GB RTX 4090） |
| Python | 主程序使用内置 `python_embeded`（3.11），各子应用有独立 venv |
| 磁盘空间 | ≥ 100GB（含模型权重） |
| 网络 | 需访问外网下载模型、调用 DeepSeek API |

### 显存与性能模式（自动检测）

| 显存 | Ollama并发 | 视觉并发 | CLIP批大小 | 模式 |
|------|-----------|---------|-----------|------|
| ≥ 16GB | 4 | 4 | 16 | 高性能 |
| 8-16GB | 2 | 2 | 8 | 平衡 |
| < 8GB | 1 | 1 | 4 | 低能耗 |

---

## 2. 目录结构

```
TinTin_AI_Agent_Main/
├── python_embeded/          # 主 Python 3.11 环境
├── studio/                  # 主程序源码
│   ├── gui_main.py          # 启动入口
│   ├── gui/                 # 界面代码
│   ├── utils/               # 工具模块
│   ├── config/              # 配置文件目录
│   ├── config.ini           # VoxCPM 等配置
│   ├── bin/win/             # ollama.exe、dreamina.exe 等
│   ├── assets/              # 图标、字体、声音样本
│   ├── data/                # 运行时数据（自动生成）
│   └── .runtime/            # 日志、临时文件、cookies
├── apps/                    # 子应用与模型（~59GB）
│   ├── voxcpm2/             # 声音克隆
│   ├── vsr-v1.4.0/          # 视频去字幕 v1.4
│   ├── vsr-v1.1.1-*/        # 视频去字幕 v1.1
│   ├── clip-models/         # Chinese-CLIP 模型
│   ├── whisper-models/      # Whisper 语音识别模型
│   ├── PaddleOCR/           # OCR 引擎
│   ├── rembg/               # 抠图
│   ├── comfyui/             # ComfyUI 图像生成
│   └── asset-browser/       # 素材浏览器
├── config.ini               # 全局配置（VoxCPM 模型路径等）
├── ffprobe.exe              # 视频探测工具
└── run_gui_integrated.bat   # Windows 启动脚本
```

---

## 3. 启动方式

### Windows
```bat
studio\run_gui_integrated.bat
```
该脚本自动定位 `python_embeded\pythonw.exe` 并启动 `gui_main.py`。

### Linux
```bash
make install   # 首次：创建 .venv，安装依赖，下载 Chromium
make run       # 启动 GUI
```

---

## 4. 外部工具

### ffmpeg / ffprobe
- `ffprobe.exe` 需放在工程根目录
- `ffmpeg.exe` 搜索顺序：`studio/bin/win/` → 系统 PATH → 工程根目录 → `apps/asset-browser/bin/` → `apps/vsr-v1.4.0/backend/ffmpeg/win_x64/`
- 如缺失，镜头分割、视频合成、去字幕等功能均无法运行

### Ollama
- 内置于 `studio/bin/win/ollama.exe`，含 CUDA 12/13 和 Vulkan runners
- 自动检测 CUDA 版本选择 runner
- 环境变量：`OLLAMA_KEEP_ALIVE=2m`（空闲2分钟自动卸载模型释放显存）
- 需拉取视觉模型：`ollama pull qwen2.5vl:7b`（推荐）

---

## 5. 配置文件

### 5.1 `config.ini`（工程根目录）

```ini
[VoxCPM]
modelpath = apps/voxcpm2/models/openbmb__VoxCPM2
port = 7861
```

> **注意**：代码加载的是**工程根目录**的 `config.ini`，不是 `studio/config.ini`。

### 5.2 `studio/config/ai_config.json`

大模型、图像生成、声音克隆等 AI 服务配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| `llm_api_url` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `llm_api_key` | API 密钥 | `sk-xxx` |
| `llm_model` | 模型名 | `deepseek-v4-flash` |
| `llm_vision_api_url` | 视觉模型(Ollama)地址 | `http://127.0.0.1:11434` |
| `llm_vision_model` | 视觉模型名 | `qwen2.5vl:7b-16k` |
| `comfyui_addr` | ComfyUI 地址 | `http://127.0.0.1:8188` |
| `vox_api_url` | VoxCPM API 地址 | `http://127.0.0.1:7861/v1/tts` |
| `runninghub_api_key` | RunningHub API Key | |
| `rustfs_endpoint` | S3 对象存储地址 | `http://192.168.111.17:9000` |

### 5.3 `studio/config/material_index_config.json`

向量检索数据库与 CLIP 模型配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| `db_host` | PostgreSQL 地址 | `192.168.111.17` |
| `db_port` | 端口 | `15432` |
| `db_name` | 数据库名 | `material_index` |
| `db_user` / `db_password` | 账号密码 | |
| `clip_model_dir` | CLIP 模型路径 | 需改为实际路径 |
| `nas_root` | NAS 素材根路径 | `\\192.168.111.17` |
| `batch_size` | CLIP 编码批大小 | 16（按显存自动调） |

> **注意**：`clip_model_dir` 默认硬编码为 `D:/Project/TinTin_AI_Agent_Main/...`，换到其他盘需修改此路径。

### 5.4 `studio/config/erp_config.json`
旺店通 ERP API 配置（可选）。

### 5.5 `studio/config/theme.json`
```json
{"theme": "dark"}
```
可选值：`dark` / `light` / `system`。

---

## 6. 数据库

### PostgreSQL + pgvector（向量检索）

```sql
CREATE DATABASE material_index;
\c material_index
CREATE EXTENSION vector;
```

依赖安装：`pip install psycopg2-binary pgvector`

### 其他数据库
- **MySQL**：业务数据（pymysql）
- **MongoDB**：爬虫数据（pymongo）
- **RustFS/S3**：素材对象存储（boto3）

---

## 7. 模型权重

| 模型 | 位置 | 用途 |
|------|------|------|
| VoxCPM2 | `apps/voxcpm2/models/openbmb__VoxCPM2/` | 声音克隆 |
| Chinese-CLIP | `apps/clip-models/damo/multi-modal_clip-vit-base-patch16_zh/` | 向量检索 |
| Whisper large-v3 | `apps/whisper-models/faster-whisper-large-v3/` | 语音转文字 |
| U2Net | `apps/rembg/models/u2net.onnx` | 抠图 |
| PaddleOCR | `apps/vsr-v1.4.0/backend/models/` | 字幕检测/去字幕 |
| STTN/LaMa/ProPainter | `apps/vsr-v1.4.0/backend/models/` | 视频修复 |
| Ollama 视觉模型 | `ollama pull qwen2.5vl:7b` | 画面分析 |

---

## 8. 子应用 Python 环境

| 子应用 | Python 路径 | 版本 | 关键依赖 |
|--------|-----------|------|---------|
| 主程序 | `python_embeded/python.exe` | 3.11 | PySide6, torch 2.6+cu124 |
| VoxCPM2 | `apps/voxcpm2/venv/python.exe` | 3.12 | torch 2.8+cu128, librosa |
| 去字幕 v1.4 | `apps/vsr-v1.4.0/Python/python.exe` | 3.12 | paddleocr, onnxruntime |
| 去字幕 v1.1 | `apps/vsr-v1.1.1-*/Python/python.exe` | 3.x | paddle, onnxruntime-gpu |

---

## 9. 已知问题与修复要点

### 9.1 VoxCPM venv 依赖版本锁定

`apps/voxcpm2/venv` 中以下包版本必须严格匹配，否则声音克隆报错：

| 包 | 正确版本 | 错误版本 | 症状 |
|----|---------|---------|------|
| soundfile | **0.12.1** | 0.13.x | `module 'soundfile' has no attribute 'SoundFileRuntimeError'` |
| dill | **≥ 0.3.9** | 0.3.8 | `module 'dill' has no attribute 'extend'` |
| lazy_loader | **0.4** | 0.5 | `module 'lazy_loader' has no attribute 'attach_stub'` |

修复命令：
```bat
apps\voxcpm2\venv\python.exe -m pip install soundfile==0.12.1 "dill>=0.3.9" lazy-loader==0.4
```

### 9.2 numpy DLL 损坏

`numpy.libs/msvcp140-*.dll` 如果是 0 字节，会导致 numpy 加载失败：
```
DLL load failed while importing _multiarray_umath
```
修复：从 `C:\Windows\System32\msvcp140.dll` 复制替换该 0 字节文件。

### 9.3 Windows 中文编码

子进程输出中文时可能因 cp1252 编码崩溃。以下入口已修复（`sys.stdout.reconfigure(encoding="utf-8")`）：
- `studio/voxcpm_api_server.py`
- `apps/vsr-v1.4.0/vsr_run.py`
- `apps/vsr-v1.1.1-*/resources/vsr_run.py`

### 9.4 去字幕 Python 路径

vsr-v1.4.0 和 vsr-v1.1.1 使用 QPT 打包的嵌入式 Python，`python.exe` 直接在 `Python/` 目录下（无 `Scripts/` 子目录）。代码已做回退处理。

### 9.5 License 认证

当前已临时关闭（`gui_main.py:1464`，`_LICENSE_CHECK_DISABLED = True`）。恢复时改为：
```python
_LICENSE_CHECK_DISABLED = _os.environ.get("TINTIN_NO_LICENSE") == "1" or sys.platform == "win32"
```

### 9.6 HuggingFace 镜像

`gui_main.py` 强制设置 `HF_ENDPOINT=https://hf-mirror.com`，国内网络可直接下载模型。

---

## 10. 外部服务依赖

| 服务 | 地址 | 用途 | 必需 |
|------|------|------|------|
| DeepSeek API | `api.deepseek.com` | 文案生成 | 是 |
| Ollama | `127.0.0.1:11434` | 画面分析 | 是 |
| PostgreSQL | `192.168.111.17:15432` | 向量检索 | 是（向量检索功能） |
| ComfyUI | `127.0.0.1:8188` | 图像生成 | 否 |
| RunningHub | `runninghub.cn` | 云端图像生成 | 否 |
| RustFS/S3 | `192.168.111.17:9000` | 素材存储 | 否 |
| 抖音 | `douyin.com` | 视频下载/发布 | 否 |
| 旺店通 | `api.wangdian.cn` | ERP | 否 |

---

## 11. 新电脑部署清单

1. **复制工程** 到目标电脑（任意盘符）
2. **安装 NVIDIA 驱动**，确保 `nvidia-smi` 可用，CUDA ≥ 12.0
3. **放置 ffmpeg.exe** 到工程根目录或 PATH 中
4. **修改 `material_index_config.json`** 中 `clip_model_dir` 为实际路径
5. **修改数据库连接** `material_index_config.json` 中的 host/port/password
6. **填写 `ai_config.json`** 中的 DeepSeek API Key
7. **拉取 Ollama 视觉模型**：`ollama pull qwen2.5vl:7b`
8. **验证 VoxCPM venv** 依赖版本（见 9.1）
9. **运行** `studio\run_gui_integrated.bat`
