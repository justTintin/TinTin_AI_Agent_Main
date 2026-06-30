# 关于本项目

**AI 电商智能体 (TinTin AI Agent)** — 面向电商内容创作的全栈 AI 桌面工作站。

## 支持的平台

- **Linux** (Pop!_OS / Ubuntu 24.04+) — Wayland + X11
- **Windows** 10 / 11

## 主要入口

| 平台 | 启动方式 |
|------|----------|
| Linux | `./run.sh` 或 `make run` |
| Windows | `run_gui_integrated.bat` |

## 核心能力

- **抖音生态**：视频解析下载、热点发现、直播切片
- **视频创作**：智能混剪、声音克隆 (VoxCPM)、AI 重命名、字幕去除 (VSR+OCR)、LUT 调色
- **AI 图像**：ComfyUI / RunningHub / 即梦多后端生成、AI 抠图、封面制作
- **素材管理**：CLIP 向量检索、产品库、知识库 RAG

## 运行时文件

统一放在 `.runtime/` 下，不在根目录产生临时文件：
- `.runtime/logs/app.log`
- `.runtime/tmp/`
- `outputs/` — 导出产物
- `data/` — 持久化数据

## 技术架构

- **GUI**：PySide6 (Qt 6) + 暗色主题
- **AI 推理**：VoxCPM2 / Whisper / CLIP / PaddleOCR / rembg / ComfyUI
- **视频处理**：ffmpeg + VSR
- **构建**：PyInstaller (Linux 二进制 / Windows .exe)

更多详情见 [README.md](README.md)。
