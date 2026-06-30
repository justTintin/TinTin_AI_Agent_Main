# AI 电商智能体 · TinTin AI Agent

> 面向电商内容创作的 AI 桌面工作站 — 视频下载 · 智能混剪 · 声音克隆 · 素材检索 · AI 图像生成

**跨平台**：Windows / Linux  |  **GUI**：PySide6  |  **版本**：v2.1.0

---

## 架构概览

```
TinTin_AI_Agent_Main/
├── studio/                    ← 主应用 (Python)
│   ├── gui_main.py           入口
│   ├── gui/                  20+ 功能页面 (PySide6)
│   ├── core/                 抖音解析 / 下载引擎
│   ├── utils/                管理器 & 外部服务客户端
│   ├── config/paths.py       全局路径
│   └── ui/gui_styles.py      暗色主题样式
├── apps/                     第三方工具 & 模型 (~59 GB)
│   ├── voxcpm2/              声音克隆
│   ├── vsr-v1.4.0/           视频超分 (Video Super-Resolution)
│   ├── whisper-models/       语音转文字
│   ├── PaddleOCR/            光学字符识别
│   ├── rembg/                AI 抠图
│   ├── comfyui/              AI 图像生成工作流
│   ├── clip-models/          CLIP 向量模型
│   └── asset-browser/        Electron 文件浏览器
├── ai_skills/                自动化脚本 (Automated Listing 等)
├── legacy_crawler/           旧版爬虫系统 (归档)
├── docs/                     文档
├── build.py                  跨平台构建脚本
├── Makefile                  开发辅助 (make run / install / build)
├── run.sh                    Linux 启动脚本
└── config.ini                飞书 & VoxCPM 配置
```

---

## 快速开始

### Linux (Pop!_OS / Ubuntu 24.04)

```bash
# 1. 安装依赖
make install          # 创建 .venv + 安装 pip 包 + Playwright Chromium

# 2. 启动
./run.sh              # 或 make run
```

环境要求：
- Python 3.12+
- NVIDIA GPU + CUDA (RTX 4090 推荐)
- QT_WAYLAND_SHELL_INTEGRATION 自动设置

### Windows

```powershell
# 1. 安装依赖
.\python_embeded\python.exe -m pip install -r studio\requirements.txt
.\python_embeded\python.exe -m pip install -r studio\requirements_gui.txt
.\python_embeded\python.exe -m playwright install chromium

# 2. 启动
.\run_gui_integrated.bat
```

---

## 功能模块

### 🎬 视频创作

| 页面 | 功能 |
|------|------|
| **智能混剪** (`video_montage_page`) | 镜头分割 → 精华片段提取 → 排列组合 → 配音 → 字幕 → 合成 |
| **声音克隆** (`voice_clone_page`) | 上传样音 → VoxCPM 克隆 → 口播文案 TTS |
| **AI 视频重命名** (`video_ai_rename_page`) | 抽帧 → 视觉模型分析 → 智能重命名 |
| **字幕去除** (`subtitle_removal_page`) | VSR 超分 + PaddleOCR 检测 → 擦除硬字幕 |
| **视频 LUT** (`video_lut_page`) | LUT 色彩预设批量应用 |
| **AI 脚本生成** (`product_script_page`) | 产品信息 → 大模型生成带货脚本 |

### 📥 抖音工具

| 页面 | 功能 |
|------|------|
| **视频下载** | 链接解析/预览 → 批量下载队列 (暂停/重试) |
| **热点发现** (`hotspot_page`) | 抖音热点数据抓取与展示 |
| **直播切片** (`live_clip_page`) | 直播流录制 → 自动分段 → 精华切片 |

### 🤖 AI 工具

| 页面 | 功能 |
|------|------|
| **AI 图像生成** (`main_window_aigen`) | ComfyUI / RunningHub / 即梦 多后端 |
| **AI 抠图** (`image_matting_page`) | rembg 批量去背景 |
| **图像分层** (`image_layered_page`) | Qwen-Image-Layered 分层处理 |
| **封面制作** (`cover_maker_page`) | 批量生成电商封面图 |
| **MG 动画** (`mg_animation_page`) | Motion Graphics 动画生成 |
| **故事板** (`storyboard_page`) | AI 分镜脚本 |

### 📊 素材管理

| 页面 | 功能 |
|------|------|
| **素材检索** (`material_clip_page`) | CLIP 向量搜索 + 关键词匹配 → 预览/下载 |
| **产品库** (`product_library_page`) | 电商产品资料管理 |
| **知识库** (`my_knowledge_page`) | 个人知识库 (RAG 检索) |

### ⚙️ 系统配置（侧边栏 v2.1 重组）

| 菜单 | Tab 子模块 |
|------|-----------|
| **🖥️ 运行环境** | Python/GPU/CUDA 检测 · 硬件自动优化 · 备份还原 · 终端 |
| **🔌 平台接入** | ComfyUI · RunningHub · 即梦 · 飞书 |
| **🧠 模型配置** | Ollama · VoxCPM · Whisper · CLIP · PaddleOCR · rembg |
| **📊 系统信息** | 硬件信息 · 日志 · 帮助 · 素材目录 |
| **📦 资源配置** | 声音样本 · 素材目录 (NAS/本地) |

---

## 配置

### AI 配置 (`studio/config/ai_config.json`)

```json
{
  "deepseek": { "api_key": "sk-xxx", "base_url": "https://api.deepseek.com" },
  "comfyui": { "host": "127.0.0.1", "port": 8188 },
  "runninghub": { "api_key": "xxx" }
}
```

首次运行可在 GUI 的「🤖 AI 设置」页面填写保存。

### 服务配置 (`config.ini`)

```ini
[Feishu]       # 飞书多维表格 (脚本管理)
[VoxCPM]        # 声音克隆模型路径 & 端口
```

### 运行时目录

| 目录 | 说明 |
|------|------|
| `.runtime/logs/` | 运行日志 |
| `.runtime/tmp/` | 临时文件 |
| `outputs/` | 导出视频 / 截图 |
| `data/` | 持久化 JSON 数据 |
| `accounts/` | 账号 cookie / session |

---

## 开发

详细开发指南见 **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**。

### 环境搭建

```bash
# 完整开发环境
make install-dev     # 含 pyinstaller

# 语法检查
make check           # 编译校验所有 .py 文件
```

### 项目结构约定

- `gui/` — 每个页面一个文件，继承 `BasePage`
- `utils/` — 纯逻辑模块，不依赖 GUI
- `core/` — 抖音平台交互 (Playwright / API)
- `config/paths.py` — 所有路径集中管理，通过 `get_bin()` 实现跨平台二进制定位

### 添加新页面

1. 在 `gui/` 创建 `xxx_page.py`，继承 `BasePage`
2. 在 `main_window_pages.py` 注册页面
3. 在 `main_window_sidebar.py` 添加侧边栏入口

---

## 构建 & 打包

```bash
# 开发模式运行
make run                           # 或 ./run.sh

# 打包为可执行文件
make build-linux                   # Linux 二进制
make build-win                     # Windows .exe
make build                         # 自动检测当前平台

# 清理构建产物
make clean
```

---

## 常见问题

### Playwright 报 "Executable doesn't exist"

```bash
playwright install chromium
# 或指定路径：PLAYWRIGHT_BROWSERS_PATH=apps/pw-browsers playwright install chromium
```

### Wayland 下 Qt 界面异常 (下拉菜单 / 弹窗)

已通过 `run.sh` 设置 `QT_WAYLAND_SHELL_INTEGRATION=xdg-shell` 修复。

### VoxCPM 声音克隆报 500 / connection reset

- **500 + StopIteration**：文本过长，已自动分句合成兜底
- **Connection reset**：服务端 GPU 不足，已内置 3 次重试 + `/health` 检查
- 确保 `apps/voxcpm2/models/openbmb__VoxCPM2` 模型文件完整

### 中文输入法 (Linux Wayland)

`run.sh` 已配置 fcitx5 支持，无需额外设置。

### Ollama 模型路径

模型存储在 `studio/assets/ollama_models/`，可通过 `OLLAMA_MODELS` 环境变量覆盖。

---

## 技术栈

| 层 | 技术 |
|----|------|
| GUI | PySide6 (Qt 6) |
| Web 引擎 | QtWebEngine / Playwright |
| AI 推理 | VoxCPM2 / Whisper / CLIP / rembg / PaddleOCR / ComfyUI |
| 视频处理 | ffmpeg / VSR |
| 数据库 | MySQL (PyMySQL) / MongoDB (PyMongo) |
| 构建 | PyInstaller / Makefile |
| 平台 | Windows 10+ · Linux (Wayland + X11) |

---

> ⚠️ 本项目仅供学习交流，请勿用于违反平台规则或法律的用途。
