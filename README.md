# 丁大怪-电商智能体矩阵

> 面向电商内容创作的全栈 AI 桌面工作站
>
> 视频下载 · 智能混剪 · 声音克隆 · 素材检索 · AI 图像生成

**跨平台**：Windows 10+ / Linux (Pop!_OS, Ubuntu 24.04+)  |  **GUI**：PySide6 (Qt 6)  |  **版本**：v2.1.0

---

## 架构

```
project-root/
├── studio/                    主应用 (Python)
│   ├── gui_main.py            入口，侧边栏 + QStackedWidget 页面切换
│   ├── gui/                   页面层 (20+ 功能页面)
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

```
📥 抖音助手
  ├── 🎬 视频下载         🔍 关键词搜索
  └── 🔥 热点发现

📺 直播工具
  └── 📡 直播切片

✂️ 成片制作
  ├── 🚀 一键成片         ✂️ 智能混剪
  └── 🎞️ 视频修复

🖼️ 图形处理
  ├── 👤 AI 抠图          🧩 图像分层
  ├── 🖼️ 封面制作         🪄 MG 动画
  └── 👁️ 视频框选 OCR     👁️ 图片框选 OCR

📚 方案脚本
  ├── 📚 知识库           📦 产品资料
  ├── 🛒 产品文案         📝 分镜脚本
  └── ✍️ 飞书选题

🗄️ 媒体库
  ├── 🎨 即梦生成         🔍 向量检索
  ├── 🗄️ 素材管理         🌐 素材浏览器
  └── 📋 任务列表

🎙️ 音频处理
  ├── 📝 语音转文字       🎙️ 声音克隆
  └── 🎞️ 视频 LUT         ✨ 视频 AI 重命名

⚙️ 系统配置 (v2.1 重组)
  ├── 🖥️ 运行环境         Python · GPU · 硬件优化 · 备份还原 · 终端
  ├── 🔌 平台接入         ComfyUI · RunningHub · 即梦 · 飞书
  ├── 🧠 模型配置         Ollama · VoxCPM · Whisper · CLIP · PaddleOCR · rembg
  ├── 📊 系统信息         硬件 · 日志 · 帮助
  └── 📦 资源配置         声音样本 · 素材目录 (NAS/本地)
```

---

## 功能模块

### 🎬 视频创作

| 功能 | 说明 |
|------|------|
| **智能混剪** | 镜头分割 → 精华提取 → 排列 → 配音 → 字幕 → 合成 |
| **声音克隆** | 上传样音 → VoxCPM 克隆 → 口播 TTS |
| **AI 重命名** | 抽帧 → 视觉模型分析 → 智能文件名 |
| **字幕去除** | VSR 超分 + PaddleOCR 检测 → 擦除硬字幕 |
| **视频 LUT** | LUT 色彩预设批量应用 |
| **一键成片** | ComfyUI 工作流驱动的端到端视频处理 |

### 📥 抖音工具

| 功能 | 说明 |
|------|------|
| **视频下载** | 链接解析 → 批量下载队列 (暂停/重试) |
| **热点发现** | Playwright 外部浏览器自动采集热点 |
| **直播切片** | 直播录制 → 自动分段 → 精华提取 |

### 🤖 AI 工具

| 功能 | 说明 |
|------|------|
| **AI 图像** | ComfyUI / RunningHub / 即梦 多后端生成 |
| **AI 抠图** | rembg 批量去背景 |
| **封面制作** | 批量电商封面生成 |
| **MG 动画** | Remotion 驱动的动态图形 |

### 📊 素材管理

| 功能 | 说明 |
|------|------|
| **向量检索** | CLIP 语义搜索 + 关键词加权匹配 |
| **素材管理** | 素材入库 / 标签 / NAS 目录索引 |
| **知识库** | 产品资料 + 个人知识库 (RAG) |

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

### AI 配置 (`studio/config/ai_config.json`)

```json
{
  "llm_provider": "deepseek",
  "llm_api_key": "sk-xxx",
  "llm_api_url": "https://api.deepseek.com",
  "llm_model": "deepseek-v4-flash",
  "comfyui_addr": "http://127.0.0.1:8188",
  "runninghub_key": "",
  "runninghub_url": "https://www.runninghub.cn"
}
```

### 服务配置 (`config.ini`)

```ini
[Feishu]
appid = cli_xxx
appsecret = xxx
apptoken = xxx
tableid = tblxxx

[VoxCPM]
Port = 7861
ModelPath = apps/voxcpm2/models/openbmb__VoxCPM2
```

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
