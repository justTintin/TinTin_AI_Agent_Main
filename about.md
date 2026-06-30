# 关于本项目

**AI 电商智能体 (TinTin AI Agent)** v2.1.0 — 面向电商内容创作的全栈 AI 桌面工作站。

## 平台

- **Linux** — Pop!_OS / Ubuntu 24.04+, Wayland + X11
- **Windows** — 10 / 11

## 启动

| 平台 | 命令 |
|------|------|
| Linux | `./run.sh` 或 `make run` |
| Windows | `run_gui_integrated.bat` |

## 系统配置 (v2.1 侧边栏)

| 菜单 | 子模块 |
|------|--------|
| 🖥️ 运行环境 | Python/GPU/CUDA · 硬件优化 · 备份还原 · 终端 |
| 🔌 平台接入 | ComfyUI · RunningHub · 即梦 · 飞书 |
| 🧠 模型配置 | Ollama · VoxCPM · Whisper · CLIP · PaddleOCR · rembg |
| 📊 系统信息 | 硬件 · 日志 · 帮助 |
| 📦 资源配置 | 声音样本 · 素材目录 (NAS/本地) |

## 核心能力

- **抖音生态** — 视频下载、热点发现、直播切片
- **视频创作** — 智能混剪、声音克隆 (VoxCPM)、AI 重命名、字幕去除 (VSR+OCR)、LUT 调色
- **AI 图像** — ComfyUI / RunningHub / 即梦多后端、AI 抠图 (rembg)、封面制作
- **素材管理** — CLIP 向量检索、产品库、知识库 RAG
- **素材浏览器** — Electron 内嵌浏览器，支持多平台嗅探下载

## 技术

- **GUI** — PySide6 (Qt 6) + 暗色主题
- **AI** — VoxCPM2 · WhisperX · CLIP · PaddleOCR · rembg · ComfyUI
- **视频** — ffmpeg + VSR
- **构建** — PyInstaller (Linux 二进制 / Windows .exe)

## 运行时

- `.runtime/logs/` — 日志
- `outputs/` — 导出产物
- `data/` — 持久化数据

详细文档：[README.md](README.md)  |  开发指南：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
