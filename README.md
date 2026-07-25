# 螺丝钉-电商智能体矩阵

> 面向电商内容创作的全栈 AI 桌面工作站
>
> 智能混剪 · 直播切片 · 声音克隆 · 素材检索 · AI 图像生成

**Windows 专用**：Windows 10+ 64位  |  **客户端 GUI**：PySide6 (Qt 6)  |  **版本**：v2.1.1

---

## 架构（客户端-服务端分离）

系统采用**客户端-服务端**（Client-Server）架构：客户端负责交互界面与轻量预处理，AI 推理任务统一交由远程服务端处理。

```
┌─────────────────────────────────────────────────────────────────┐
│                    客户端 (本机 Windows)                           │
│                                                                  │
│  studio/                    主应用 (Python + PySide6)              │
│   ├── gui_main.py           入口，侧边栏 + 页面切换                  │
│   ├── gui/                  40+ 功能页面                            │
│   ├── utils/                管理器 & 远程服务客户端                   │
│   │   ├── asr_client.py     → 远程 Whisper 语音转写                  │
│   │   ├── voxcpm_client.py  → 远程 VoxCPM 声音克隆                   │
│   │   ├── comfyui_client.py → 远程 ComfyUI 图像生成                  │
│   │   ├── ollama_manager.py → 远程 Ollama 视觉模型                   │
│   │   └── material_clip_indexer.py → 远程 CLIP 向量检索              │
│   ├── core/                 本地抖音解析 / 下载引擎                   │
│   ├── config/paths.py       全局路径 & 二进制定位                    │
│   └── ui/gui_styles.py      暗色/亮色主题 QSS                       │
│                                                                  │
│  apps/                      本地第三方工具 (~59 GB，不入库)           │
│   ├── vsr-v1.4.0/           视频去字幕 (本地处理)                    │
│   ├── PaddleOCR/            OCR 引擎 (本地处理)                     │
│   ├── rembg/                AI 抠图 (本地处理)                      │
│   ├── clip-models/          CLIP 向量模型 (fallback)                │
│   └── asset-browser/        Electron 素材浏览器                     │
└─────────────────────────────────────────────────────────────────┘
                               │
             HTTP / WebSocket  │  (局域网 / 公网)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    服务端 (远程 Linux/Windows)                     │
│                                                                  │
│  compute_server (统一计算节点)       http://<server>:8000          │
│   ├── /whisper/transcribe     → 语音转写 (Whisper)                │
│   ├── /voxcpm/tts             → 声音克隆 TTS (VoxCPM)             │
│   ├── /vllm/chat              → 视觉分析 (Qwen2.5VL)              │
│   ├── /clip/embed             → 向量嵌入 (Chinese-CLIP)           │
│   └── /material/*             → 素材管理 API                       │
│                                                                  │
│  comfyui_server               http://<server>:8188                │
│   └── AI 图像生成 (ComfyUI)                                       │
│                                                                  │
│  DeepSeek API (云端)          https://api.deepseek.com            │
│   └── 文案生成 (LLM)                                             │
└─────────────────────────────────────────────────────────────────┘
```

> ⚠️ **`apps/` 与敏感文件不入库**：约 59 GB 的模型/工具二进制、Cookie、License 白名单、用户主题偏好等均通过 `.gitignore` 排除。开发者克隆后需自行下载模型或从分发包获取（见 [docs/SETUP.md](docs/SETUP.md)）。

---

## 快速开始

### Windows

```powershell
.\run_gui_integrated.bat
```

---

## 侧边栏导航

### ✅ 当前可用

```
📚 方案脚本
  ├── 📚 我的知识库       📦 产品资料
  └── 🛒 产品文案创作     📝 分镜脚本创作

🗄️ 媒体库
  ├── 🎨 即梦生成         🔍 向量检索
  ├── 🗄️ 素材管理
  └── 🌐 素材浏览器       (外部 Electron 应用)

✂️ 成片制作
  ├── ✂️ 智能混剪         📡 直播切片

🖼️ 图形处理
  ├── 👤 图像抠图         👁️ 图片框选 OCR

🎬 视频处理
  ├── 💬 视频转文字       🎙️ 声音克隆
  ├── 🎞️ 视频去字幕      🔎 视频框选 OCR
  └── 📈 视频预测评价     📢 营销视频检测

⚙️ 系统设置
  ├── ⚙️ 模型配置         🔌 平台接入
  ├── 📦 资源配置         🖥️ 运行环境
  └── ❓ 帮助
```

### 🚧 已隐藏（未在侧边栏显示）

下列功能代码已存在但菜单未开放，按计划状态分组：

| 功能 | 状态 | 说明 |
|------|------|------|
| 🗣️ 数字人 | 📅 下版本计划 | 数字人形象生成 |
| 🚀 一键成片 | 📅 下版本计划 | ComfyUI 工作流端到端成片 |
| 🖼️ 封面制作 | 📅 下版本计划 | 批量电商封面生成 |
| ✍️ 飞书选题 | 📅 下版本计划 | 从飞书表格同步选题 |
| 🧺 即梦素材 | 🔒 暂时隐藏 | 即梦生成素材管理（功能已开发） |
| 🪄 MG 动画 | 🔒 暂时隐藏 | Remotion 动态图形（功能已开发） |
| 🗂️ 智能分层 | 🔒 暂时隐藏 | AI 图像分层（功能已开发） |
| ✨ 视频修复 | 🔒 暂时隐藏 | VSR 超分修复 v14（功能已开发） |
| 🏷️ 视频智能重命名 | 🔒 暂时隐藏 | 视觉模型智能命名（功能已开发） |
| 🌈 批量 LUT 调色 | 🔒 暂时隐藏 | LUT 色彩预设（功能已开发） |
| 📋 任务列表 | 🔒 暂时隐藏 | 后台任务查看（占位） |
| 👥 账户平台 | 🔒 暂时隐藏 | 抖音账户管理（整段 Section 隐藏） |

> 状态图例：📅 下版本计划 = 已排期；🔒 暂时隐藏 = 功能已就绪但暂不开放。具体见 `studio/gui/main_window_sidebar.py` 注释。

---

## 功能模块

> 状态：✅ 可用 · 🔒 暂时隐藏（功能已就绪）· 📅 下版本计划

### 🎬 视频处理

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 智能混剪 | ✅ | 镜头分割 → 精华提取 → 排列 → 配音 → 字幕 → 合成 |
| 直播切片 | ✅ | 直播录制 → 自动分段 → 精华提取 |
| 视频转文字 | ✅ | Whisper 语音识别，输出带时间戳文本 |
| 声音克隆 | ✅ | 上传样音 → VoxCPM 克隆 → 口播 TTS |
| 视频去字幕 | ✅ | VSR 超分 + PaddleOCR 检测 → 擦除硬字幕 |
| 视频框选 OCR | ✅ | 视频内框选区域 → 自动提取文字 |
| 视频预测评价 | ✅ | 钩子评分，预测视频表现 |
| 营销视频检测 | ✅ | 识别视频中的营销/违禁内容 |
| 视频智能重命名 | 🔒 | 抽帧 → 视觉模型分析 → 智能文件名 |
| 视频修复 | 🔒 | VSR 超分/去噪/补帧（v14） |
| 批量 LUT 调色 | 🔒 | LUT 色彩预设批量应用 |
| 数字人 | 📅 | 数字人形象生成 |

### 🖼️ 图形处理

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 图像抠图 | ✅ | rembg 批量去背景，输出透明 PNG |
| 图片框选 OCR | ✅ | 图片内框选区域 → 自动提取文字 |
| 智能分层 | 🔒 | AI 图像分层分解 |
| MG 动画 | 🔒 | Remotion 驱动的动态图形 |
| 封面制作 | 📅 | 批量电商封面生成 |

### 🤖 AI 工具

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 即梦生成 | ✅ | 即梦多比例/多模型 AI 图像生成 |
| 一键成片 | 📅 | ComfyUI 工作流端到端成片 |

### 📚 方案脚本

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 我的知识库 | ✅ | 个人知识库 (RAG) |
| 产品资料 | ✅ | 产品资料库管理 + Excel 导入导出 |
| 产品文案创作 | ✅ | 产品资料 → AI 自动生成电商文案 |
| 分镜脚本创作 | ✅ | AI 分析画面 → 生成分镜脚本 |
| 飞书选题 | 📅 | 从飞书表格同步选题 |

### 📊 素材管理

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 素材管理 | ✅ | 素材入库 / 标签 / NAS 目录索引 / AI 分析 |
| 素材浏览器 | ✅ | 内嵌 Electron 浏览器，自动嗅探视频/音频 |
| 向量检索 | ✅ | CLIP 语义搜索 + 关键词加权匹配 |
| 即梦素材 | 🔒 | 即梦生成素材管理 |
| 任务列表 | 🔒 | 后台任务查看 |

---

## 系统配置详解

### 🖥️ 运行环境
- Python 版本/路径、GPU 型号/显存、CUDA/PyTorch 状态实时检测
- 根据显存自动优化并发参数 (Ollama 并发 / 视觉分析 / CLIP 批大小)
- 一键修复：重装 CUDA 版 PyTorch + WhisperX 依赖
- 数据备份/还原：配置 + 业务数据一键打包 zip
- 内嵌 Python 终端：在应用内执行命令

### 🔌 平台接入
- **统一计算节点**：远程服务端地址配置、连通性测试（集中管理 ASR/VoxCPM/Ollama/CLIP）
- **ComfyUI**：远程地址配置、连接测试
- **RunningHub**：API Key 配置、用户信息验证
- **即梦**：二进制路径显示
- **飞书**：App ID/Secret/Token/Table 配置，保存到 `config.ini`

### 🧠 模型配置
- **大语言模型**（云端）：API 地址 / Key / 模型名配置
- **视觉模型**（服务端）：远程 Ollama 视觉模型列表、下载/删除
- **语音转写**（服务端）：远程 Whisper 服务连通性测试
- **声音克隆**（服务端）：远程 VoxCPM 服务连通性测试
- **向量模型**（服务端）：远程 CLIP 服务连通性测试
- **PaddleOCR**（本地）：Python 环境检测、导入测试
- **rembg**（本地）：抠图模型可用性检测

### 📊 系统信息
- 硬件信息：OS / CPU / RAM / GPU / VRAM
- 系统日志：最近 100 行实时查看
- 帮助文档：快速开始 / 环境要求 / 功能概览 / FAQ

### 📦 资源配置
- 声音样本管理
- 素材目录：支持多目录，NAS 入库，平台自动适配

---

## 配置

> 完整字段说明见 **[docs/SETUP.md](docs/SETUP.md)** 第 5 节。含凭据的配置文件不入库，仓库内提供 `.example` 模板，部署时复制为正式文件并填入真实值。

### AI 配置 (`studio/config/ai_config.json`)

```json
{
  "llm_provider": "deepseek",
  "llm_api_key": "sk-xxx",
  "llm_api_url": "https://api.deepseek.com",
  "llm_model": "deepseek-v4-flash",
  "compute_server_url": "http://192.168.111.18:8000",
  "whisper_api_url": "http://192.168.111.18:8000",
  "llm_vision_api_url": "http://192.168.111.18:8000",
  "vox_api_url": "http://192.168.111.18:8000/voxcpm/tts",
  "clip_api_url": "http://192.168.111.18:8000",
  "material_api_url": "http://192.168.111.18:8000",
  "comfyui_addr": "http://192.168.111.36:8188",
  "runninghub_api_key": "",
  "runninghub_base_url": "https://www.runninghub.cn",
  "rustfs_endpoint": "http://192.168.111.17:9000",
  "rustfs_access_key": "xxx",
  "rustfs_secret_key": "xxx",
  "rustfs_bucket": "photos"
}
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `compute_server_url` | **统一计算节点地址**（ASR / VoxCPM / Ollama / CLIP 共用） | `http://192.168.111.18:8000` |
| `whisper_api_url` | 语音转写服务地址（不填则从 `compute_server_url` 派生） | `http://192.168.111.18:8000` |
| `llm_vision_api_url` | 视觉分析（Ollama）地址（不填则从 `compute_server_url` 派生） | `http://192.168.111.18:8000` |
| `vox_api_url` | 声音克隆 TTS 地址（不填则从 `compute_server_url` 派生） | `http://192.168.111.18:8000/voxcpm/tts` |
| `clip_api_url` | 向量嵌入服务地址（不填则从 `compute_server_url` 派生） | `http://192.168.111.18:8000` |
| `material_api_url` | 素材管理服务地址（不填则从 `compute_server_url` 派生） | `http://192.168.111.18:8000` |
| `comfyui_addr` | ComfyUI 图像生成地址（独立服务节点） | `http://192.168.111.36:8188` |
| `llm_api_url` | 文案生成 LLM API（云端） | `https://api.deepseek.com` |
| `rustfs_endpoint` | RustFS/S3 对象存储地址 | `http://192.168.111.17:9000` |

### 服务配置 (`config.ini`)

```ini
[Feishu]
appid = cli_xxx
appsecret = xxx
apptoken = xxx
tableid = tblxxx
topicfield = 文案标题
scriptfield = 脚本
foldertoken =

[VoxCPM]
modelpath = apps/voxcpm2/models/openbmb__VoxCPM2
port = 7861
```

> **注意**：VoxCPM 目前使用远程服务端模式，本地 `VoxCPM` 配置段为保留项。远程地址统一在 `ai_config.json` 中配置。

### 激活与授权

未激活设备启动时弹出激活对话框，需输入开发人员签发的激活码（JSON）。

- **机器码**：对话框显示 16 位机器码，**支持鼠标选中复制或点「📋 复制」按钮**，发给开发人员签发激活码
- **白名单**：`studio/config/trial_whitelist.json` 中的机器码可免激活直接试用（该文件已从 git 移除，仅本地保留）
- **开发跳过**：设环境变量 `TINTIN_NO_LICENSE=1` 可跳过激活检查（仅开发用）
- 签发工具：`tools/license_tool.py`

### 运行时目录

| 目录 | 说明 |
|------|------|
| `.runtime/logs/` | 运行日志 |
| `.runtime/tmp/` | 临时文件 |
| `outputs/` | 导出产物 |
| `data/` | 持久化 JSON |

---

## 开发

```bash
make install-dev     # 完整开发环境 (含 PyInstaller)
make run             # 开发模式运行
make build           # 打包当前平台
make check           # 全部 .py 语法校验
make clean           # 清理构建产物
```

### 依赖文件

| 文件 | 用途 |
|------|------|
| `studio/requirements_gui.txt` | GUI 主程序依赖（PySide6 / 图像视频 / 授权等，含可选功能注释） |
| `studio/requirements.txt` | 爬虫 / 数据库 / Flask 等后端依赖 |
| `studio/requirements_dev.txt` | 开发工具（PyInstaller / Playwright） |

详细指南见 **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 客户端 GUI | PySide6 (Qt 6) |
| 服务端 (AI 推理) | FastAPI · Whisper · VoxCPM2 · Ollama (vLLM) · Chinese-CLIP |
| 图像生成 | ComfyUI（独立服务节点）|
| 文案生成 | DeepSeek API（云端） |
| Web 引擎 | QtWebEngine / Playwright |
| 本地处理 | ffmpeg · VSR · rembg · PaddleOCR |
| 数据 | PostgreSQL+pgvector · MySQL · MongoDB · RustFS/S3 |
| 构建 | PyInstaller · Makefile |
| 素材浏览器 | Electron |

---

> 💡 **设计原则**：客户端只做 UI 渲染和轻量预处理（ffmpeg 提取音频、本地 VSR 去字幕等），所有 AI 推理任务（语音转写、声音克隆、视觉分析、向量嵌入）统一由远程服务端执行。这种分离让客户端保持轻量，同时支持服务端 GPU 资源共享与横向扩展。

> ⚠️ 仅供学习交流，请勿用于违反平台规则或法律的用途。
