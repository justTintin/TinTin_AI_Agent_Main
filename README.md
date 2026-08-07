# 螺丝钉-电商智能体矩阵

> 面向电商内容创作的全栈 AI 桌面工作站
>
> 智能混剪 · 直播切片 · 声音克隆 · 素材检索 · AI 图像生成

**Windows 专用**：Windows 10+ 64位  |  **客户端 GUI**：PySide6 (Qt 6)  |  **版本**：v2.1.1

---

## 项目定位

本仓库为 **Windows 桌面客户端**。用户通过 PySide6 图形界面完成内容创作 workflow；重度 AI 推理与媒体合成任务按功能配置委托到远程服务端或本地工具执行。

客户端只负责：

- 用户界面渲染与交互
- 本地素材浏览、管理与轻量预处理
- 向配置的远程服务端发起任务请求并轮询结果
- 调用已集成的本地工具（ffmpeg、rembg 等）及浏览器扩展桥接服务
- 调用 RunningHub 云端 ComfyUI 工作流（数字人对口型等）：上传图片/音频 → 提交工作流 → 轮询状态 → 自动下载结果
- 浏览器扩展「螺丝钉素材采集」的本地桥接（`utils/extension_bridge.py`），随客户端自动启动

> 远程服务地址统一在 `studio/config/ai_config.json` 中配置，具体服务端实现由独立部署的 `compute_server` / `comfyui_server` 等提供；数字人也可走 RunningHub 云端工作流 API。本仓库不维护服务端代码。

---

## 分发包体积与本地依赖

当前工作区（含内嵌 Python 与本地工具）参考体积：

| 目录 | 说明 | 参考体积 |
|------|------|---------|
| `apps/` | 本地第三方工具 | 约 13.6 GB（实测 13.59 GB） |
| `python_embeded/` | 内嵌 Python 运行时 | 约 9.3 GB（实测 9.26 GB） |
| `studio/` | 客户端源码与资源 | 约 2.7 GB（实测 2.68 GB） |

> `apps/` 与敏感文件不入库，实际体积随模型/工具下载情况变化。部署时从分发包获取或按 `docs/SETUP.md` 自行准备。

`apps/` 当前目录：

| 目录 | 用途 |
|------|------|
| `vsr-v1.4.0/` | 视频去字幕 / 视频修复旧版本地包（当前可见功能已切换服务端） |
| `asset-browser/` | Electron 素材浏览器 |
| `pw-browsers/` | Playwright 内嵌 Chromium |
| `rembg/` | AI 图像抠图 |
| `modelscope/` | 即梦/模型scope 相关工具 |
| `browser-extension/` | 「螺丝钉素材采集」浏览器扩展源码 |
| `whisper-models/` | 本地 Whisper 模型占位 |
| `clip-models-hf/` | 本地 CLIP 模型占位 |

> 视频去字幕、OCR 等功能的本地 PaddleOCR 模型已移除，当前可见版本统一走服务端。

---

## 快速开始

### 生产环境（分发包）

双击运行根目录：

```
螺丝钉-电商智能体矩阵.exe
```

该启动器会调用内嵌 Python 环境 `python_embeded\pythonw.exe` 启动 GUI，并随客户端自动启动浏览器扩展桥接服务。

### 开发环境

```powershell
# 方式一：开发启动脚本
python build.py run

# 方式二：使用内嵌环境启动
studio\run_gui_integrated.bat
```

> `build.py` 仅保留开发模式；打包/加固/发布逻辑已迁移到独立发布工程 `TinTin_Release_Builder`。

---

## 侧边栏导航

> 侧边栏顺序已按当前 `studio/gui/main_window_sidebar.py` 重新扫描。

### 当前可用（按显示顺序）

```
🌐 素材浏览器（顶部独立按钮，直接打开 Electron 应用）

📚 方案脚本
  ├── 📚 我的知识库
  ├── 📦 产品资料
  ├── 🛒 产品文案创作
  └── 📝 分镜脚本创作

🗄️ 媒体库
  ├── 🎨 素材生成
  ├── 🔍 素材检索
  └── 📋 任务队列

✂️ 成片制作
  ├── 🕒 成片任务
  ├── 🚀 一键成片
  ├── ✂️ 智能混剪
  └── 📡 直播切片

🖼️ 图形处理
  ├── 👤 图像抠图
  └── 👁️ 图片框选 OCR

🎬 视频处理
  ├── 💬 视频转文字
  ├── 🎙️ 声音克隆
  ├── 🎞️ 视频去字幕
  └── 🔎 视频框选 OCR

📈 视频运营
  ├── 📈 视频评价预测
  └── 📢 视频营销检测

⚙️ 系统设置
  ├── ⚙️ 模型配置
  ├── 🔌 平台接入
  ├── 📦 资源配置
  ├── 🖥️ 运行环境
  ├── 🧩 扩展插件
  └── ❓ 帮助
```

> 素材浏览器为独立 Electron 应用，从侧边栏顶部直接唤起；「扩展插件」管理浏览器扩展安装与本地桥接服务。

### 已隐藏（代码仍在，菜单未开放）

| 功能 | 说明 | 对应文件/索引 |
|------|------|--------------|
| 数字人 | 数字人对口型（已接入 RunningHub 云端工作流）；菜单入口未开放，可在侧边栏启用 | `setup_digital_human_page` / index 3 |
| 即梦素材 | 即梦生成素材管理 | `dreamina_assets_page.py` / index 43 |
| MG 动画 | Remotion 动态图形 | `mg_animation_page.py` / index 36 |
| 智能分层 | AI 图像分层 | `image_layered_page.py` / index 17 |
| 视频修复 | VSR 超分/去噪/补帧 v14 | `subtitle_removal_page_v14.py` / index 11 |
| 视频智能重命名 | 视觉模型智能命名 | `video_ai_rename_page.py` / index 26 |
| 封面制作 | 批量电商封面生成 | `cover_maker_page.py` / index 33 |
| 账户平台 | 抖音账户管理（整段 Section 注释） | `main_window_accounts.py` / index 8 |
| 本地视频去字幕（旧版） | 基于本地 VSR 的旧版页面 | `subtitle_removal_page.py` / index 14 |

### 已移除（代码/文件已删除）

| 功能 | 说明 |
|------|------|
| 批量 LUT 调色 | 本地 LUT 调色功能已删除 |
| 热点追踪 | 页面已彻底移除，功能并入素材浏览器；`studio/gui/hotspot_page.py` 已删除 |
| AI 技能模块 | `ai_skills/` 目录已删除（无代码依赖） |
| 旧版爬虫 | `legacy_crawler/` 目录已删除，被 `studio/core/` 取代 |

> 菜单显隐以 `studio/gui/main_window_sidebar.py` 注释为准；页面索引以 `studio/gui_main.py` 的 `setup_pages` 顺序为准。

---

## 功能模块

### 成片制作

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 智能混剪 | 可用 | 镜头分割、精华提取、镜头重组在客户端编排；最终视频合成默认委托远程服务端（可切换本地），合成参数与分割片段上传至服务端 |
| 直播切片 | 可用 | 直播录制管理、自动分段、精华提取界面 |
| 一键成片 | 可用 | 模板选择、素材匹配、合成请求界面 |
| 成片任务 | 可用 | 合成/生成任务队列展示界面 |

### 媒体库

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 素材生成 | 可用 | 调用即梦/ComfyUI 等生成图像并管理入库 |
| 素材检索 | 可用 | 向量/关键词检索界面，请求远程 CLIP 服务 |
| 任务队列 | 可用 | 展示服务端定时任务/生成队列状态 |

### 视频处理

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 视频转文字 | 可用 | 上传/选择视频 → 请求远程 Whisper 服务 → 展示时间戳文本 |
| 声音克隆 | 可用 | 样本管理、TTS 请求远程 VoxCPM 服务 |
| 视频去字幕 | 可用 | 上传视频+选区 → 服务端 `/vsr/remove` 处理 → 下载结果 |
| 视频框选 OCR | 可用 | 框选区域 → 裁剪后上传 → 服务端 `/material/ocr` 识别 |
| 视频修复 | 隐藏 | 本地 VSR 处理（v14） |
| 视频智能重命名 | 隐藏 | 抽帧 → 请求远程视觉模型 → 智能命名 |
| 批量 LUT 调色 | 已移除 | 本地 LUT 调色功能已删除 |
| 本地视频去字幕（旧版） | 隐藏 | 旧版本地 VSR 页面 |

### 图形处理

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 图像抠图 | 可用 | 本地 rembg 批量去背景 |
| 图片框选 OCR | 可用 | 框选区域 → 裁剪后上传 → 服务端 `/material/ocr` 识别 |
| 智能分层 | 隐藏 | AI 图像分层分解 |
| 封面制作 | 隐藏 | 批量电商封面生成 |

### 方案脚本

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 我的知识库 | 可用 | 个人知识库 (RAG) 界面 |
| 产品资料 | 可用 | 产品资料库管理 + Excel 导入导出 |
| 产品文案创作 | 可用 | 产品资料 → 调用云端 LLM API 生成文案 |
| 分镜脚本创作 | 可用 | 分析画面 → 调用 LLM 生成分镜脚本；含「飞书选题同步」卡片 |

### 视频运营

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 视频评价预测 | 可用 | 钩子评分界面 |
| 视频营销检测 | 可用 | 识别营销/违禁内容界面 |

### 扩展与采集

| 功能 | 状态 | 客户端实现 |
|------|:----:|------|
| 浏览器扩展管理 | 可用 | 检测/安装 Chrome/Edge/360 等浏览器扩展；控制本地桥接服务启停与端口 |
| 素材浏览器 | 可用 | Electron 应用，嗅探网页视频/音频资源 |

---


## RunningHub 数字人工作流

数字人页面支持两种后端：

| 后端 | 说明 |
|------|------|
| ComfyUI（本地/局域网） | 本地或私有 GPU 上的 ComfyUI，上传图片/音频后 patch 工作流并提交 |
| RunningHub（云端工作流 API） | 走 RunningHub 官方工作流接口 `POST /openapi/v2/run/workflow/{workflowId}` |

### RunningHub 配置要点

- 在“平台接入 → RunningHub”配置 `runninghub_api_key` 与 `runninghub_base_url`。
- 工作流 ID 使用 API 详情页地址 `call-api/api-detail/{workflowId}?apiType=5` 中的那个 ID，不是编辑器 `/workflow/{id}` 页面的 ID（当两者一致时可同时使用）。
- 实例类型：48G 显存工作流必须配 `instanceType=plus`。
- 企业级-独占 Key 建议开启“个人独占队列”（`usePersonalQueue=true`），任务才会分配到你租用的独占机器。
- 节点映射：只映射真实文件输入节点 `LoadImage [180]`、`LoadAudio [6]`；连线节点不提交。

### 客户端队列与下载

- 队列由客户端管理，同时只提交一个任务；415 资源不足时 30 秒后自动重试，任务完成后等待 30 秒再提交下一个。
- 页面实时显示队列统计：总数、已提交、成功下载、失败、进度。
- 结果自动下载，命名规则：以音频文件名为基础，单个结果为 `音频名.mp4`，多个结果为 `音频名_序号.mp4`。

> 可选：若要直接按 ComfyUI 协议提交（`POST /prompt`），需填写浏览器登录态 `Rh-Comfy-Auth` / `Rh-Identify` / `Rh-Accesstoken`；默认不填，使用官方工作流 API 即可。


## 系统配置

> v2.1.0 将原「环境配置」拆分为 5 个独立菜单，合并/迁移了冗余菜单：AI 设置→平台接入、大模型配置→模型配置、系统日志/帮助/备份还原/Python 终端→运行环境/资源配置等。

### 运行环境
- Python 版本/路径、GPU 型号/显存、CUDA/PyTorch 状态实时检测
- 根据显存自动优化并发参数
- 一键修复：重装 CUDA 版 PyTorch + WhisperX 依赖
- 数据备份/还原：配置 + 业务数据一键打包 zip
- 内嵌 Python 终端
- 系统日志 / 帮助文档 / 硬件信息

### 平台接入
- 统一计算节点：远程服务端地址配置、连通性测试
- ComfyUI：远程地址配置、连接测试
- RunningHub：API Key 配置、工作流管理（名称/类型/ID/实例类型）、个人独占队列选项、可选 ComfyUI 协议会话凭证、连接测试
- 即梦 / 飞书：二进制路径与 App ID/Secret 配置

### 模型配置
- 大语言模型：API 地址 / Key / 模型名
- 视觉模型：远程 Ollama 列表、下载/删除
- 语音转写：远程 Whisper 连通性测试
- 声音克隆：远程 VoxCPM 连通性测试
- 向量模型：远程 CLIP 连通性测试
- OCR 文本识别：服务端 `/material/ocr` 连通性测试（本地 PaddleOCR 模型已移除）
- rembg：本地抠图模型可用性检测

### 资源配置
- 声音样本管理
- 素材目录：支持多目录，NAS 入库

### 扩展插件
- 检测本机 Chromium 系浏览器（Chrome / Edge / 360 / QQ 等）
- 一键安装/加载「螺丝钉素材采集」扩展
- 控制本地桥接服务（`utils/extension_bridge.py`）：端口、保存目录、服务端扫描、启停
- 查看最近采集记录

---

## 配置

> 凭据与敏感文件不入库。仓库提供 `.example` 模板，部署时复制为正式文件并填入真实值。

### AI 配置 (`studio/config/ai_config.json`)

关键字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `compute_server_url` | 统一计算节点地址（ASR / VoxCPM / Ollama / CLIP / OCR / 去字幕 / 智能混剪合成） | `http://<server>:8000` |
| `whisper_api_url` | 语音转写服务地址（不填则从 `compute_server_url` 派生） | `http://<server>:8000` |
| `llm_vision_api_url` | 视觉分析地址（不填则从 `compute_server_url` 派生） | `http://<server>:8000` |
| `vox_api_url` | 声音克隆 TTS 地址（不填则从 `compute_server_url` 派生） | `http://<server>:8000/voxcpm/tts` |
| `clip_api_url` | 向量嵌入服务地址（不填则从 `compute_server_url` 派生） | `http://<server>:8000` |
| `material_api_url` | 素材管理 / OCR 服务地址（不填则从 `compute_server_url` 派生） | `http://<server>:8000` |
| `comfyui_addr` | ComfyUI 图像生成地址（独立服务节点） | `http://<server>:8188` |
| `llm_api_url` | 文案生成 LLM API（云端） | `https://api.deepseek.com` |
| `runninghub_api_key` | RunningHub 工作流 API Key | `rh_xxx` |
| `runninghub_base_url` | RunningHub 基础地址 | `https://www.runninghub.cn` |
| `runninghub_use_personal_queue` | 企业级-独占 Key 是否使用个人独占队列 | `true` |
| `runninghub_workflows` | 已配置的 RunningHub 工作流列表（id/name/type/instanceType） | `[]` |
| `runninghub_comfy_auth` | 可选：ComfyUI 协议会话凭证 Rh-Comfy-Auth | 空 |
| `runninghub_comfy_identify` | 可选：Rh-Identify | 空 |
| `runninghub_access_token` | 可选：Rh-Accesstoken | 空 |

> 服务端接口路径以运行时服务端 `/guide` 或 OpenAPI 文档为准，客户端按文档对接。

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

- **客户端免激活**：当前版本服务端采用激活机制，客户端启动时直接放行（_access_granted = True），不再弹出本地激活对话框。
- 历史 License 验证模块（studio/utils/license.py）仍保留在仓库中，仅作验证逻辑参考；签发工具在独立工程 TinTin_License_Signer 中维护，不随客户端分发。
- 旧的本地激活码、机器码、试用白名单等入口已废弃，不再使用。

### 运行时目录

| 目录 | 说明 |
|------|------|
| `.runtime/logs/` | 运行日志 |
| `.runtime/tmp/` | 临时文件 |
| `outputs/` | 导出产物 |
| `data/` | 持久化 JSON |
| `data/extension_bridge.json` | 扩展桥接配置 |

---

## 开发

```bash
python build.py run    # 开发模式运行（打包逻辑已迁移到 TinTin_Release_Builder）
make install-dev       # 完整开发环境（若使用 Makefile）
make check             # 全部 .py 语法校验
make clean             # 清理构建产物
```

### 依赖文件

- `studio/requirements_gui.txt` — GUI 主程序依赖
- `studio/requirements.txt` — 爬虫/数据库/Flask 依赖
- `studio/requirements_dev.txt` — 开发工具
- 运行前需准备 Python 环境（`python_embeded/` 或系统 Python）并安装上述依赖；`python_embeded/` 不入库。

详细指南见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 客户端 GUI | PySide6 (Qt 6) |
| 内嵌 Python | `python_embeded/` 独立 Python 环境 |
| 图像生成 | 即梦 / ComfyUI（远程） |
| 数字人对口型 | RunningHub 云端 ComfyUI 工作流 API（可选 ComfyUI 协议） |
| 文案生成 | DeepSeek API（云端） |
| 本地媒体处理 | ffmpeg · rembg |
| OCR / 去字幕 | 服务端 `/material/ocr` / `/vsr/remove` |
| Web 引擎 | QtWebEngine / Playwright |
| 浏览器扩展桥接 | `utils/extension_bridge.py`（本地 HTTP 服务） |
| 构建 | PyInstaller · Makefile / TinTin_Release_Builder |
| 素材浏览器 | Electron |

---

> 设计原则：客户端聚焦 UI、本地轻量处理与浏览器扩展桥接；重度 AI 推理、媒体合成、OCR、去字幕统一委托到可配置的远程服务端，避免依赖客户端机器性能。

> 仅供学习交流，请勿用于违反平台规则或法律的用途。
