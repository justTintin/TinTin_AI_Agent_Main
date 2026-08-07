# TinTin AI Agent 部署与配置指南

## 1. 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 64位 |
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
	├── studio/                  # 客户端主程序源码
	│   ├── gui_main.py          # 启动入口
	│   ├── gui/                 # 界面代码
	│   ├── utils/               # 工具模块（含远程服务客户端）
	│   │   ├── asr_client.py    # 远程 Whisper 语音转写客户端
	│   │   ├── voxcpm_client.py # 远程 VoxCPM 声音克隆客户端
	│   │   ├── comfyui_client.py# 远程 ComfyUI 图像生成客户端
	│   │   ├── ollama_manager.py# Ollama 管理器（支持远程模式）
	│   │   └── material_clip_indexer.py # 远程 CLIP 向量检索客户端
	│   ├── config/              # 配置文件目录
	│   ├── config.ini           # VoxCPM 等配置（保留项）
	│   ├── bin/win/             # dreamina.exe 等
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

> ⚠️ **含凭据的配置文件不入库**：下列 JSON/ini 含 API Key、数据库密码等敏感信息，已从 git 移除（本地保留）。仓库内提供对应的 `.example` 模板（值用 `xxx` 占位），新部署时复制为正式文件并填入真实值。

### 5.1 `config.ini`（工程根目录）

飞书集成与 VoxCPM 声音克隆配置：

```ini
[Feishu]
appid = cli_xxx               ; 飞书应用 App ID
appsecret = xxx               ; 飞书应用 App Secret
apptoken = xxx                ; 飞书表格 App Token
tableid = tblxxx              ; 选题表格 Table ID
topicfield = 文案标题          ; 选题标题列字段名
scriptfield = 脚本             ; 脚本内容列字段名
foldertoken =                 ; 文件夹 Token（可空）

[VoxCPM]
modelpath = apps/voxcpm2/models/openbmb__VoxCPM2
port = 7861
```

> **注意**：代码加载的是**工程根目录**的 `config.ini`，不是 `studio/config.ini`（后者为冗余备份）。模板见 `config.ini.example`。

### 5.2 `studio/config/ai_config.json`

大模型、计算节点、图像生成、声音克隆、对象存储等 AI 服务配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| `llm_provider` | LLM 提供商 | `deepseek` |
| `llm_api_url` | LLM API 地址 | `https://api.deepseek.com` |
| `llm_api_key` | LLM API 密钥 | `sk-xxx` |
| `llm_model` | 文本模型名 | `deepseek-v4-flash` |
| `compute_server_url` | **统一计算节点地址**（ASR/VoxCPM/Ollama/CLIP 共用） | `http://X.X.X.X.X.X.X:8000` |
| `whisper_api_url` | 语音转写地址（不填则从 `compute_server_url` 派生） | `http://X.X.X.X.X.X.X:8000` |
| `llm_vision_api_url` | 视觉分析（Ollama）地址（不填则从 `compute_server_url` 派生） | `http://X.X.X.X.X.X.X:8000` |
| `llm_vision_model` | 视觉模型名 | `qwen2.5vl:7b-16k` |
| `vox_api_url` | VoxCPM TTS API 地址（不填则从 `compute_server_url` 派生） | `http://X.X.X.X.X.X.X:8000/voxcpm/tts` |
| `clip_api_url` | 向量嵌入服务地址（不填则从 `compute_server_url` 派生） | `http://X.X.X.X.X.X.X:8000` |
| `material_api_url` | 素材管理服务地址（不填则从 `compute_server_url` 派生） | `http://X.X.X.X.X.X.X:8000` |
| `comfyui_addr` | ComfyUI 图像生成地址（独立服务节点） | `http://X.X.X.X.X.X.X:8188` |
| `runninghub_api_key` | RunningHub API Key | |
| `runninghub_base_url` | RunningHub 基址 | `https://www.runninghub.cn` |
| `vox_mode` | VoxCPM 模式 | `api` |
| `vox_timesteps` | VoxCPM 时间步数 | `20` |
| `vox_cfg` | VoxCPM CFG 强度 | `2.0` |
| `rustfs_endpoint` | RustFS/S3 对象存储地址 | `http://X.X.X.X.X.X.X:9000` |
| `rustfs_access_key` | S3 Access Key | `xxx` |
| `rustfs_secret_key` | S3 Secret Key | `xxx` |
| `rustfs_bucket` | S3 Bucket 名 | `photos` |

> **架构说明**：AI 推理任务统一通过 `compute_server_url` 指向的远程计算节点执行。客户端（本机）只负责 UI 交互和媒体预处理（ffmpeg 提取音频等）。各服务地址可单独覆盖，不填时自动从 `compute_server_url` 派生。
> 
> 模板见 `studio/config/ai_config.json.example`。

### 5.3 `studio/config/material_index_config.json`

向量检索数据库、CLIP 模型、NAS 素材索引配置：

| 字段 | 说明 | 示例 |
|------|------|------|
| `db_host` / `db_port` | PostgreSQL 地址 / 端口 | `X` / `15432` |
| `db_name` | 数据库名 | `material_index` |
| `db_user` / `db_password` | 数据库账号 / 密码 | `xxx` |
| `clip_model` | CLIP 模型规格 | `ViT-B-16`（可选 `ViT-L-14` / `ViT-H-14`） |
| `clip_model_dir` | CLIP 模型目录 | 需改为实际路径 |
| `device` | 推理设备 | `auto`（自动选 cuda/cpu） |
| `batch_size` | CLIP 编码批大小（按显存自动调） | `16` |
| `fps` | 抽帧采样率 | `1` |
| `tag_depth_product` | 产品标签目录层级（0=第一级） | `0` |
| `tag_depth_brand` | 品牌标签目录层级 | `1` |
| `tag_depth_model` | 型号标签目录层级 | `2` |
| `tag_depth_category` | 类别标签层级（-1=不取） | `-1` |
| `save_thumbs` | 是否生成缩略图 | `false` |
| `thumb_dir` | 缩略图目录（`save_thumbs=true` 时生效） | |
| `nas_root` | NAS 素材根路径 | `\\X` |
| `nas_user` / `nas_password` | NAS 账号 / 密码 | `xxx` |
| `index_directories` | 索引目录映射（local_path ↔ nas_folder） | 列表 |
| `ffmpeg_path` | ffmpeg 路径（null=自动查找） | `null` |

> **注意**：`clip_model_dir` 默认硬编码为 `D:/Project/TinTin_AI_Agent_Main/...`，换到其他盘需修改此路径。模板见 `studio/config/material_index_config.json.example`。

### 5.4 `studio/config/erp_config.json`

旺店通 ERP OpenAPI2 配置（可选，仅知识库库存查询用到）：

| 字段 | 说明 | 示例 |
|------|------|------|
| `base_url` | API 基址 | `https://api.wangdian.cn/openapi2/` |
| `appkey` | 应用 AppKey | `wdt112233-jd`（沙箱示例） |
| `appsecret` | 应用 Secret | `xxx` |
| `sid` | 商家 SID | `wdt112233` |

> 默认填旺店通官方沙箱账号，正式使用请替换为生产凭据。模板见 `studio/config/erp_config.json.example`。

### 5.5 `studio/config/theme.json`

```json
{"theme": "dark"}
```

可选值：`dark` / `light` / `system`。该文件由程序在用户切换主题时自动生成（`utils/theme_manager.py`），**不入库**。首次运行时默认 `dark`。

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

默认**开启**：未激活设备启动会弹出激活对话框，需输入开发人员签发的激活码（JSON）。
- 激活对话框显示 16 位机器码，支持鼠标选中复制或点「📋 复制」按钮
- 开发跳过：设环境变量 `TINTIN_NO_LICENSE=1`（`gui_main.py:1465`，`_LICENSE_CHECK_DISABLED = _os.environ.get("TINTIN_NO_LICENSE") == "1"`）
- 签发工具：`tools/license_tool.py`
- 白名单 `studio/config/trial_whitelist.json` 中的机器码可免激活直接试用（该文件已从 git 移除，仅本地保留）

### 9.6 HuggingFace 镜像

`gui_main.py` 强制设置 `HF_ENDPOINT=https://hf-mirror.com`，国内网络可直接下载模型。

---

## 10. 外部服务依赖

| 服务 | 地址 | 用途 | 必需 |
|------|------|------|------|
| **统一计算节点** | `http://<server>:8000` | ASR 转写 + VoxCPM TTS + Ollama 视觉 + CLIP 向量 | **是** |
| DeepSeek API | `api.deepseek.com` | 文案生成 | **是** |
| ComfyUI | `http://<server>:8188` | 图像生成 | 否 |
| PostgreSQL | `X.X.X.X:15432` | 向量检索 | 是（向量检索功能） |
| RunningHub | `runninghub.cn` | 云端图像生成 | 否 |
| RustFS/S3 | `X.X.X.X:9000` | 素材存储 | 否 |
| 抖音 | `douyin.com` | 直播切片录制 / 素材嗅探 | 否 |
| 旺店通 | `api.wangdian.cn` | ERP | 否 |

---

## 11. 新电脑部署清单

1. **复制工程** 到目标电脑（任意盘符）
2. **安装 NVIDIA 驱动**，确保 `nvidia-smi` 可用，CUDA ≥ 12.0
3. **放置 ffmpeg.exe** 到工程根目录或 PATH 中
4. **配置远程计算节点**：确认服务端已部署并获取计算节点 URL（`compute_server_url`），填入 `ai_config.json`
5. **修改 `material_index_config.json`** 中 `clip_model_dir` 为实际路径
6. **修改数据库连接** `material_index_config.json` 中的 host/port/password
7. **填写 `ai_config.json`** 中的 DeepSeek API Key
8. **运行** `studio\run_gui_integrated.bat`
9. **配置统一计算节点**：在 GUI 中进入「系统设置 → 平台接入 → 统一计算节点」，填写服务端地址并测试连接
