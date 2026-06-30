# Tintin AI Agent - Ubuntu 迁移部署指南

本指南详述了 Tintin AI Agent 项目的跨平台改造结构和 Ubuntu 下的部署步骤。

## 跨平台架构

代码已全平台适配，同一套源码在 Windows / Linux 上均可运行。

### 平台二进制分层
```
studio/bin/
├── win/          # Windows 可执行文件 (ollama.exe, dreamina.exe, lib/)
├── linux/        # Linux 可执行文件 (ollama, dreamina)
```

代码中通过 `get_bin("ollama")` 自动定位到当前平台对应的二进制目录。

### 核心工具模块
- `studio/config/paths.py` — 路径配置（`get_bin()`, `BIN_PLATFORM_DIR`）
- `studio/utils/platform_utils.py` — 跨平台工具（`find_ffmpeg()`, `find_python()`, `IS_WIN` 等）
- `build.py` — 统一构建脚本（`python build.py win/linux/run/clean`）

---

## 1. 步骤一：部署环境

```bash
chmod +x ubuntu_migration_bundle/setup_env.sh
./ubuntu_migration_bundle/setup_env.sh
source .venv/bin/activate
python3 ubuntu_migration_bundle/import_configs.py
```

## 2. 步骤二：放置 Linux 二进制

```bash
# Ollama Linux 版
# 从 https://github.com/ollama/ollama/releases/latest 下载 ollama-linux-amd64
mv ollama-linux-amd64 studio/bin/linux/ollama
chmod +x studio/bin/linux/ollama

# 即梦 CLI (如有 Linux 版本)
# 放入 studio/bin/linux/dreamina
```

## 3. 步骤三：FFmpeg

`setup_env.sh` 已通过 apt 安装系统级 ffmpeg，代码中 `find_ffmpeg()` 自动查找。

## 4. 步骤四：运行

```bash
# 开发模式
python3 build.py run

# 或有 GUI 环境
source .venv/bin/activate
python3 studio/gui_main.py

# Headless 模式
xvfb-run --server-args="-screen 0 1024x768x24" python3 studio/gui_main.py
```

## 5. 构建打包

```bash
python3 build.py linux    # 打包 Linux 可执行文件
python3 build.py clean    # 清理构建产物
```
