# 螺丝钉-电商智能体矩阵

> 面向电商内容创作的全栈 AI 桌面工作站
>
> 智能混剪 · 直播切片 · 声音克隆 · 素材检索 · AI 图像生成

**跨平台**：Windows 10+ / Linux (Pop!_OS, Ubuntu 24.04+)  |  **GUI**：PySide6 (Qt 6)  |  **版本**：v2.1.1

---

## 架构

```
project-root/
├── studio/                    主应用 (Python)
│   ├── gui_main.py            入口，侧边栏 + QStackedWidget 页面切换
│   ├── gui/                   页面层 (40+ 功能页面)
│   ├── core/                  抖音解析 / 下载引擎
│   ├── utils/                 管理器 & 外部服务客户端
│   ├── config/paths.py        全局路径 & 跨平台二进制定位
│   └── ui/gui_styles.py       暗色主题 QSS
├── apps/                      第三方工具 & 模型 (~59 GB，不入库)
│   ├── voxcpm2/               声音克隆 (VoxCPM2)
│   ├── vsr-v1.4.0/            视频超分辨率
│   ├── whisper-models/        语音转文字 (WhisperX)
│   ├── PaddleOCR/             光学字符识别
│   ├── rembg/                 AI 抠图
│   ├── comfyui/               AI 图像生成 (ComfyUI)
│   ├── clip-models/           CLIP 向量模型 (Chinese-CLIP)
│   └── asset-browser/         Electron 素材浏览器
├── docs/                      文档
├── build.py                   跨平台 PyInstaller 构建
├── Makefile                   开发辅助
├── run.sh                     Linux 启动脚本
└── config.ini                 飞书 & VoxCPM 配置
```

> ⚠️ **`apps/` 与敏感文件不入库**：约 59 GB 的模型/工具二进制、Cookie、License 白名单、用户主题偏好等均通过 `.gitignore` 排除。开发者克隆后需自行下载模型或从分发包获取（见 [docs/SETUP.md](docs/SETUP.md)）。

---

## 快速开始

### Linux

```bash
make install          # 创建 venv + 安装依赖 + Playwright Chromium
./run.sh              # 启动 GUI
```

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
- **ComfyUI**：本地服务启停、地址配置、连接测试
- **RunningHub**：API Key 配置、用户信息验证
- **即梦**：二进制路径显示
- **飞书**：App ID/Secret/Token/Table 配置，保存到 `config.ini`

### 🧠 模型配置
- **Ollama**：启停、模型列表、下载/删除、CUDA runner 自动匹配
- **VoxCPM**：TTS 服务启停、端口配置
- **Whisper**：模型加载测试 (base/large-v3)
- **CLIP**：Chinese-CLIP 下载 (ModelScope)、加载预热、批大小配置
- **PaddleOCR**：Python 环境检测、导入测试
- **rembg**：抠图模型可用性检测

### 📊 系统信息
- 硬件信息：OS / CPU / RAM / GPU / VRAM
- 系统日志：最近 100 行实时查看
- 帮助文档：快速开始 / 环境要求 / 功能概览 / FAQ

### 📦 资源配置
- 声音样本管理
- 素材目录：支持多目录，NAS 入库，平台自动适配 (Linux: `/mnt/nas/Photos`)

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
  "llm_vision_api_url": "http://127.0.0.1:11434",
  "llm_vision_model": "qwen2.5vl:7b-16k",
  "ollama_num_parallel": 4,
  "vision_concurrency": 4,
  "comfyui_addr": "http://127.0.0.1:8188",
  "runninghub_api_key": "",
  "runninghub_base_url": "https://www.runninghub.cn",
  "voice_clone_addr": "http://127.0.0.1:7860",
  "vox_api_url": "http://127.0.0.1:7861/v1/tts",
  "vox_mode": "api",
  "vox_timesteps": 20,
  "vox_cfg": 2.0,
  "rustfs_endpoint": "http://192.168.111.17:9000",
  "rustfs_access_key": "xxx",
  "rustfs_secret_key": "xxx",
  "rustfs_bucket": "photos"
}
```

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
| GUI | PySide6 (Qt 6) |
| Web 引擎 | QtWebEngine / Playwright |
| AI 推理 | VoxCPM2 · WhisperX · CLIP · rembg · PaddleOCR · ComfyUI |
| 视频 | ffmpeg · VSR |
| 数据 | MySQL · PostgreSQL+pgvector · MongoDB |
| 构建 | PyInstaller · Makefile |
| 素材浏览器 | Electron |

---

> ⚠️ 仅供学习交流，请勿用于违反平台规则或法律的用途。
