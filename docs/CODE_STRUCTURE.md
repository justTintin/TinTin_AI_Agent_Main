# 螺丝钉-电商智能体矩阵 · 代码结构说明

> 版本：v2.1.1 | 技术栈：Python + PySide6 (Qt 6) | 架构：客户端-服务端分离

---

## 一、项目概览

**螺丝钉-电商智能体矩阵** 是一套面向电商内容创作的全栈 AI 桌面工作站，将 AI 视觉分析、语音合成、自然语言理解与视频处理等能力通过客户端-服务端架构有机整合，帮助内容团队高效产出电商视频和素材。

### 设计原则

- **客户端**（本机 Windows）：PySide6 桌面应用，只做 UI 渲染和轻量预处理（ffmpeg 提取音频、VSR 去字幕等），以及 AI 任务的调度编排
- **服务端**（远程计算节点）：统一部署 AI 推理服务 — Whisper（语音转写）、VoxCPM（声音克隆）、Ollama（视觉分析）、Chinese-CLIP（向量嵌入）
- **独立服务节点**：ComfyUI（AI 图像生成）
- **云端服务**：DeepSeek API（文案生成）

---

## 二、项目目录结构

```
TinTin_AI_Agent_Main/                      # 项目根目录
│
├── studio/                                # ★ 核心主应用（Python + PySide6）
│   ├── gui_main.py                        #   应用入口，MainWindow 主窗口
│   ├── version.py                         #   版本号（CalVer 语义混合）
│   │
│   ├── gui/                               #   功能页面（40+ 页面）
│   │   ├── main_window_sidebar.py         #     侧边栏导航（Section + 按钮）
│   │   ├── main_window_pages.py           #     页面初始化（setup_pages）
│   │   ├── main_window_aiconfig.py        #     AI 配置页面
│   │   ├── main_window_aigen.py           #     AI 生成相关
│   │   ├── main_window_services.py        #     服务管理
│   │   ├── main_window_accounts.py        #     账号管理
│   │   ├── main_window_installers.py      #     安装器/环境检测
│   │   ├── threads.py                     #     后台线程（监控/WS/AI状态）
│   │   ├── dialogs.py                     #     对话框（登录/激活/启动画面）
│   │   ├── base_page.py                   #     页面基类
│   │   ├── montage/                       #     智能混剪子模块
│   │   │   ├── base_step_view.py          #       步骤视图基类
│   │   │   ├── step1_split_view.py        #       步骤1：镜头分割
│   │   │   ├── step2_concat_view.py       #       步骤2：排列拼接
│   │   │   ├── step3_voice_view.py        #       步骤3：配音字幕
│   │   │   └── step4_final_view.py        #       步骤4：合成导出
│   │   │
│   │   ├── transcription_page.py          #     视频转文字（Whisper）
│   │   ├── video_montage_page.py          #     智能混剪主页面
│   │   ├── live_clip_page.py              #     直播切片
│   │   ├── voice_clone_page.py            #     声音克隆
│   │   ├── voice_samples_page.py          #     声音样本管理
│   │   ├── subtitle_removal_page.py       #     视频去字幕（旧版VSR）
│   │   ├── subtitle_removal_page_v14.py   #     视频去字幕（V14新版）
│   │   ├── video_ocr_page.py              #     视频框选 OCR
│   │   ├── image_folder_ocr_page.py       #     图片文件夹 OCR
│   │   ├── image_matting_page.py          #     图像抠图（rembg）
│   │   ├── image_layered_page.py          #     图像智能分层
│   │   ├── hook_score_page.py             #     视频预测评价（钩子评分）
│   │   ├── marketing_detect_page.py       #     营销视频检测
│   │   ├── video_ai_rename_page.py        #     视频智能重命名
│   │   ├── video_lut_page.py              #     批量 LUT 调色
│   │   ├── env_config_page.py             #     运行环境配置
│   │   ├── ai_script_page.py              #     AI 脚本/文案创作
│   │   ├── storyboard_page.py             #     分镜脚本创作
│   │   ├── dreamina_page.py               #     即梦 AI 图像生成
│   │   ├── dreamina_assets_page.py        #     即梦素材管理
│   │   ├── cover_maker_page.py            #     封面制作
│   │   ├── compile_video_page.py          #     一键成片（ComfyUI）
│   │   ├── mg_animation_page.py           #     MG 动画（Remotion）
│   │   ├── vector_search_page.py          #     向量检索
│   │   ├── my_knowledge_page.py           #     我的知识库
│   │   ├── product_library_page.py        #     产品资料库
│   │   ├── product_script_page.py         #     产品文案创作
│   │   ├── backup_page.py                 #     数据备份/还原
│   │   └── terminal_page.py               #     内嵌 Python 终端
│   │
│   ├── utils/                             #   工具库/客户端（30+ 模块）
│   │   ├── logger_utils.py                #     日志工具
│   │   ├── gui_icons.py                   #     GUI 图标工具
│   │   ├── theme_manager.py               #     主题管理（暗色/亮色）
│   │   ├── hardware_utils.py              #     硬件信息检测
│   │   ├── platform_utils.py              #     平台工具
│   │   ├── thread_worker.py               #     线程工作器
│   │   ├── account_manager.py             #     账号管理器
│   │   ├── license.py                     #     授权/激活校验
│   │   ├── service_registry.py            #     服务注册表
│   │   ├── data_registry.py               #     数据注册表
│   │   │
│   │   ├── asr_client.py                  #    远程 Whisper 语音转写客户端
│   │   ├── voxcpm_client.py               #    远程 VoxCPM 声音克隆客户端
│   │   ├── comfyui_client.py              #    远程 ComfyUI 图像生成客户端
│   │   ├── ollama_manager.py              #    远程 Ollama 视觉模型管理
│   │   ├── dreamina_client.py             #    即梦 API 客户端
│   │   ├── ocr_client.py                  #    本地 OCR 客户端
│   │   ├── video_indexer.py               #    视频索引/分析
│   │   ├── video_compiler.py              #    视频编译/合成
│   │   ├── video_prediction_manager.py    #    视频预测管理
│   │   ├── asset_browser_client.py        #    素材浏览器客户端
│   │   ├── nas_client.py                  #    NAS 网络存储客户端
│   │   ├── rustfs_manager.py              #    RustFS/S3 对象存储管理
│   │   ├── jianying_exporter.py           #    剪映导出工具
│   │   │
│   │   ├── product_library_manager.py     #    产品资料库管理器
│   │   ├── my_knowledge_manager.py        #    知识库管理器
│   │   ├── knowledge_distiller.py         #    知识蒸馏/分析
│   │   ├── hotspot_manager.py             #    热点管理器
│   │   ├── brand_normalizer.py            #    品牌名称规范化
│   │   ├── extreme_words.py               #    极限词检测
│   │   ├── runninghub_manager.py          #    RunningHub 管理器
│   │   ├── remotion_client.py             #    Remotion 动画客户端
│   │   ├── update_checker.py              #    版本更新检查
│   │   ├── backup_manager.py              #    备份管理器
│   │   ├── base_worker.py                 #    工作器基类
│   │   └── wdt_client.py                  #    WebDriver 工具客户端
│   │
│   ├── core/                              #   本地核心引擎
│   │   ├── creator_browser_controller.py  #     创作者浏览器控制器（Playwright）
│   │   ├── browser_fetcher.py             #     浏览器抓取工具
│   │   ├── douyin_parser.py               #     抖音页面解析器
│   │   ├── douyin_a_bogus.py              #     抖音 A-Bogus 签名算法
│   │   ├── douyin_user_downloader.py      #     抖音用户视频下载
│   │   └── douyin_video.py                #     抖音视频模型
│   │
│   ├── config/                            #   配置文件
│   │   ├── paths.py                       #     全局路径 & 二进制定位（核心）
│   │   ├── ai_config.json                 #     AI 服务配置（远程地址/Key）
│   │   ├── ai_config.json.example         #     AI 配置模板
│   │   ├── ai_config.example.json         #     早期模板（已废弃）
│   │   ├── material_index_config.json     #     素材索引配置
│   │   ├── erp_config.json.example        #     ERP 配置模板
│   │   ├── license.dat                    #     授权数据文件
│   │   ├── license_private.pem            #     License 私钥
│   │   ├── license_public.pem             #     License 公钥
│   │   ├── .activation_cache              #     激活缓存
│   │   ├── theme.json                     #     主题配置
│   │   └── update.json                    #     更新配置
│   │
│   ├── ui/                                #   UI 样式
│   │   ├── gui_styles.py                  #     暗色主题 QSS
│   │   └── gui_styles_light.py            #     亮色主题 QSS
│   │
│   ├── data/                              #   持久化数据（JSON）
│   │   ├── product_library.json           #     产品资料库
│   │   ├── my_knowledge.json              #     个人知识库
│   │   ├── media_library.json             #     媒体库索引
│   │   ├── hotspots.json                  #     热点数据
│   │   ├── video_predictions.json         #     视频预测数据
│   │   ├── brand_dictionary.json          #     品牌词典
│   │   ├── knowledge_dir.json             #     知识库目录映射
│   │   └── material_index_config.json     #     素材索引配置
│   │
│   ├── accounts/                          #   账号数据
│   │   ├── accounts.json                  #     账号信息
│   │   └── sessions/                      #     浏览器会话
│   │
│   ├── assets/                            #   静态资源
│   │   ├── app_icon.png / .ico            #     应用图标
│   │   ├── icons/                         #     SVG/PNG 图标集
│   │   ├── voice_samples/                 #     声音样本（六六、冲哥、老怀）
│   │   │   └── metadata.json              #       样本元数据
│   │   ├── playwright/                    #     内置 Playwright Chromium
│   │   ├── workflow/                      #     ComfyUI 工作流文件
│   │   ├── wheels/                        #     内置 Python wheels
│   │   ├── douyin_a_bogus.js              #     抖音 a_bogus 算法 JS
│   │   ├── douyin_x-bogus.js              #     抖音 x_bogus 算法 JS
│   │   └── stealth.min.js                 #     Playwright 反检测脚本
│   │
│   ├── outputs/                           #   导出产物目录
│   │   ├── dreamina/                      #     即梦生成输出
│   │   ├── covers/                        #     封面输出
│   │   ├── final/                         #     最终合成输出
│   │   ├── mg/                            #     MG 动画输出
│   │   └── materials/                     #     素材输出
│   │
│   ├── remotion/                          #   Remotion 动画工程
│   ├── static/                            #   Web 静态文件
│   ├── bin/win/                           #   内置二进制工具
│   │   ├── dreamina.exe                   #     即梦 CLI
│   │   ├── ffmpeg.exe                     #     ffmpeg
│   │   ├── ffprobe.exe                    #     ffprobe
│   │   └── ollama.exe                     #     Ollama CLI
│   │
│   ├── .runtime/                          #   运行时目录
│   │   ├── logs/                          #     运行日志
│   │   ├── tmp/                           #     临时文件
│   │   └── cookies/                       #     Cookie 存储
│   │
│   ├── requirements.txt                   #   后端依赖（爬虫/DB/Flask）
│   ├── requirements_gui.txt               #   GUI 主程序依赖
│   └── requirements_dev.txt               #   开发工具依赖
│
├── apps/                                  # 本地第三方工具（不入库，~59 GB）
│   ├── PaddleOCR/                         #   OCR 引擎（本地处理）
│   ├── comfyui/                           #   ComfyUI 图像生成
│   ├── vsr-v1.1.1-windows-nvidia-cuda/   #   VSR 视频超分（旧版）
│   ├── vsr-v1.4.0/                        #   VSR 视频超分（新版）
│   ├── rembg/                             #   AI 抠图
│   ├── clip-models-hf/                    #   CLIP 向量模型
│   ├── asset-browser/                     #   Electron 素材浏览器
│   ├── pw-browsers/                       #   Playwright 浏览器内核
│   ├── voxcpm2/                           #   VoxCPM 声音克隆模型
│   ├── modelscope/                        #   ModelScope 模型
│   └── Qwen-Image-Layered/               #   通义千问图像分层
│
├── ai_skills/                             # AI 技能
│   ├── Automated_Listing_Skill/           #   自动化上架技能
│   └── Automate_List_Chrome/              #   Chrome 自动化上架
│
├── python_embeded/                        # 内嵌 Python 运行时
│
├── docs/                                  # 文档
│   ├── PRD.md                             #   产品需求文档
│   ├── SETUP.md                           #   安装部署指南
│   ├── DEVELOPMENT.md                     #   开发指南
│   ├── REPO_CLEANUP.md                    #   仓库清理说明
│   ├── icon-spec.md                       #   图标规范
│   ├── multi-agent-architecture.md        #   多智能体架构
│   └── ui-prototype.html                  #   UI 原型
│
├── build.py                               # 开发模式启动脚本
├── export_configs.py                      # 配置导出工具
├── help.md                                # 使用说明书
├── config.ini.example                     # 服务配置模板
├── package.json                           # jsdom 依赖（用于 JS 运行时）
├── .gitignore                             # Git 忽略规则
└── README.md                              # 项目 README
```

---

## 三、核心代码模块详解

### 3.1 应用入口 — `gui_main.py`

该文件是应用的**主入口**，负责：

- **环境初始化**（第 1-105 行）：
  - 配置 CUDA/cuDNN DLL 路径（Windows 内嵌 Python）
  - 设置 Hugging Face 国内镜像 `hf-mirror.com`
  - 设置 Windows 任务栏图标 AppUserModelID
  - 禁止 CLI 弹出黑窗口（重写 `subprocess.Popen`）
  - 处理 `pythonw.exe` 下 stdout/stderr 为 None 的崩溃问题
  - 添加项目路径到 `sys.path`
  - 迁移 `pw-browsers` 目录到统一位置
  - 设置 `PLAYWRIGHT_BROWSERS_PATH` 环境变量

- **`MainWindow` 类**（第 361 行起）：主窗口，通过多重继承组合多个 Mixin：
  ```python
  class MainWindow(QMainWindow, PageSetupMixin, ServicesMixin, AccountsMixin, 
                         AIGenMixin, SidebarMixin, InstallersMixin, AIConfigMixin):
  ```
  - 使用 `QStackedWidget` 管理 40+ 个功能页面
  - 包含 `SystemStatusOverlay` 状态栏（实时显示 CPU/RAM/GPU/服务状态）
  - 后台启动 `_StatsCollector` 采集远程服务器 `/health` 状态
  - 后台启动 `AIStatusCheckThread` 检测 AI 服务连通性
  - 页面切换时触发对应页面的数据刷新逻辑

### 3.2 GUI 页面层 — `studio/gui/`

每个功能页面是一个独立模块，通过 `main_window_pages.py` 中的 `setup_*_page()` 方法注册到 `QStackedWidget`。页面索引从 0 到 43。

| 页面索引 | 功能名称 | 模块文件 | 说明 |
|---------|---------|---------|------|
| 1 | 热点追踪 | — | 原热点追踪页，已移除 |
| 3 | 数字人 | — | 下版本计划 |
| 6 | 系统日志 | — | 内嵌日志查看器 |
| 7 | AI 设置 | `main_window_aiconfig.py` | LLM/视觉/语音/克隆/向量模型配置 |
| 8 | 账号管理 | `main_window_accounts.py` | 抖音账号管理 |
| 9 | 任务列表 | — | 后台任务查看 |
| 12 | 视频转文字 | `transcription_page.py` | Whisper 语音识别 |
| 13 | 运行环境 | `env_config_page.py` | 系统状态/依赖修复/终端 |
| 14 | 视频去字幕 | `subtitle_removal_page.py` | VSR 旧版 |
| 15 | **智能混剪** | `video_montage_page.py` (38万字节) | 核心功能，含 4 步骤子视图 |
| 16 | 图像抠图 | `image_matting_page.py` | rembg 批处理 |
| 17 | 智能分层 | `image_layered_page.py` | AI 图像分解 |
| 18 | 视频去字幕 V14 | `subtitle_removal_page_v14.py` | VSR v14 新版 |
| 19 | **直播切片** | `live_clip_page.py` (10万+字节) | 直播录制+精华提取 |
| 20 | AI 脚本 | `ai_script_page.py` | AI 文案创作 |
| 21 | 声音克隆 | `voice_clone_page.py` | VoxCPM TTS |
| 22 | 声音样本 | `voice_samples_page.py` | 样本管理 |
| 23 | 大模型配置 | — | LLM 设置页 |
| 24 | 视频框选 OCR | `video_ocr_page.py` | 视频区域文字提取 |
| 25 | 图片文件夹 OCR | `image_folder_ocr_page.py` | 批量图片 OCR |
| 26 | 视频重命名 | `video_ai_rename_page.py` | AI 视觉模型命名 |
| 27 | LUT 调色 | `video_lut_page.py` | 批量色彩预设 |
| 28 | 产品资料 | `product_library_page.py` | 产品库管理 |
| 29 | 我的知识库 | `my_knowledge_page.py` | 个人 RAG 知识库 |
| 30 | 产品文案创作 | `product_script_page.py` | 电商文案生成 |
| 32 | **即梦生成** | `dreamina_page.py` | AI 图像生成 |
| 33 | 封面制作 | `cover_maker_page.py` | 批量封面生成 |
| 34 | 一键成片 | `compile_video_page.py` | ComfyUI 端到端 |
| 35 | 视频预测评价 | `hook_score_page.py` | 钩子评分 |
| 36 | MG 动画 | `mg_animation_page.py` | Remotion 图形动画 |
| 37 | 数据备份 | `backup_page.py` | 配置+数据打包 |
| 38 | 分镜脚本 | `storyboard_page.py` | AI 分镜生成 |
| 39 | 向量检索 | `vector_search_page.py` | CLIP 语义搜索 |
| 40 | 内嵌终端 | `terminal_page.py` | Python 终端 |
| 41 | 营销检测 | `marketing_detect_page.py` | 违禁内容检测 |
| 42 | 即梦素材 | `dreamina_assets_page.py` | 即梦生成素材管理 |

### 3.3 工具/客户端层 — `studio/utils/`

| 模块 | 职责 | 技术 |
|------|------|------|
| `asr_client.py` | 远程 Whisper 语音转写客户端 | HTTP REST → 服务端 `/whisper/transcribe` |
| `voxcpm_client.py` | 远程 VoxCPM 声音克隆客户端 | HTTP → 服务端 `/voxcpm/tts` |
| `comfyui_client.py` | 远程 ComfyUI 客户端 | HTTP + WebSocket → `host:8188` |
| `ollama_manager.py` | 远程 Ollama 视觉模型管理 | HTTP → 服务端 `/vllm/chat` |
| `dreamina_client.py` | 即梦 API 客户端 | 子进程调用 `dreamina.exe` |
| `ocr_client.py` | 本地 OCR 调用 | 子进程调用 PaddleOCR |
| `video_indexer.py` | 视频分析/索引 | OpenCV + 远程 CLIP + 视觉模型 |
| `video_compiler.py` | 视频合成 | ffmpeg 调用 |
| `video_prediction_manager.py` | 视频预测评价 | 远程视觉模型分析 |
| `asset_browser_client.py` | Electron 素材浏览器通信 | WebSocket |
| `nas_client.py` | NAS 网络存储客户端 | SMB 协议 |
| `rustfs_manager.py` | RustFS/S3 对象存储 | S3 API |
| `jianying_exporter.py` | 剪映导出工具 | 剪映 DRT 解析 |
| `product_library_manager.py` | 产品资料库 CRUD | JSON 文件持久化 |
| `my_knowledge_manager.py` | 知识库管理 | JSON 文件 |
| `knowledge_distiller.py` | AI 知识蒸馏分析 | 远程 LLM + 视觉模型 |
| `hotspot_manager.py` | 热点追踪 | 抖音 API + Playwright |
| `runninghub_manager.py` | RunningHub API | HTTP |
| `remotion_client.py` | Remotion 渲染 | 子进程调用 npm |
| `license.py` | License 签发/校验 | RSA 签名 |
| `backup_manager.py` | 数据备份/还原 | zip 打包 |
| `update_checker.py` | 版本更新检查 | GitHub Release / 自有服务器 |
| `brand_normalizer.py` | 品牌名称规范化 | 品牌词典匹配 |
| `extreme_words.py` | 极限词检测 | 正则词库 |
| `theme_manager.py` | 主题管理 | JSON 持久化 |
| `hardware_utils.py` | 硬件信息检测 | psutil + nvidia-smi |
| `platform_utils.py` | 平台工具函数 | Python 路径查找等 |
| `service_registry.py` | 服务注册表 | 服务地址管理 |
| `data_registry.py` | 数据注册表 | 数据文件路径管理 |
| `gui_icons.py` | GUI 图标工具 | SVG/MDI 图标渲染 |
| `logger_utils.py` | 日志工具 | loguru 封装 |

### 3.4 核心引擎层 — `studio/core/`

| 模块 | 职责 |
|------|------|
| `creator_browser_controller.py` | 创作者浏览器控制器，基于 Playwright 控制抖音创作者平台 |
| `browser_fetcher.py` | 浏览器数据抓取工具 |
| `douyin_parser.py` | 抖音页面 HTML/JSON 解析 |
| `douyin_a_bogus.py` | 抖音 A-Bogus 签名算法（调用 JS 引擎 `pyexecjs`） |
| `douyin_user_downloader.py` | 抖音用户主页视频批量下载 |
| `douyin_video.py` | 抖音视频数据模型 |

### 3.5 配置层 — `studio/config/`

**`paths.py`** — 全局路径管理中心（164 行），定义：

- **运行模式感知**：支持源码模式（开发）和 frozen 模式（PyInstaller 打包）
- **三个根目录**：
  - `_BUNDLE_DIR`：只读资源根（frozen 时 = `_MEIPASS`）
  - `PROJECT_ROOT`：studio/ 根（可写数据根）
  - `WORKSPACE_ROOT`：工程根（apps/python_embeded）
- **关键路径常量**（约 50 个）：RUNTIME_DIR/LOG_DIR/TMP_DIR/OUTPUTS_DIR/DATA_DIR/CONFIG_DIR 等
- **二进制工具定位**：`get_bin()` 函数自动查找 `bin/win/` 下的 exe
- **`init_bin_paths()`**：初始化 `DREAMINA_EXE`、`OLLAMA_BIN`

**配置文件清单**：
- `ai_config.json` — AI 服务端地址、API Key、模型名称等
- `material_index_config.json` — 素材索引配置
- `theme.json` — 暗色/亮色主题
- `update.json` — 在线更新配置

---

## 四、架构设计要点

### 4.1 多重继承 Mixin 模式

`MainWindow` 通过多重继承组合 7 个 Mixin 类，每个 Mixin 负责一组相关功能：

```
MainWindow
├── PageSetupMixin      — 页面初始化（40+ 页面创建）
├── ServicesMixin       — 服务管理（Playwright/浏览器）
├── AccountsMixin       — 抖音账号管理
├── AIGenMixin          — AI 生成功能
├── SidebarMixin        — 侧边栏导航
├── InstallersMixin     — 环境安装/检测
└── AIConfigMixin       — AI 配置管理
```

### 4.2 客户端-服务端分离

```
[客户端]                          [服务端]
  gui_main.py                        compute_server (FastAPI)
    ↓                                    ├── /whisper/transcribe
  asr_client.py ── HTTP ──→              ├── /voxcpm/tts
  voxcpm_client.py ── HTTP ──→           ├── /vllm/chat
  ollama_manager.py ── HTTP ──→          ├── /clip/embed
  comfyui_client.py ── HTTP+WS ──→      └── /material/*
  dreamina_client.py ── 子进程 ──→   [本地] dreamina.exe
  ocr_client.py ── 子进程 ──→       [本地] PaddleOCR
```

### 4.3 智能混剪 4 步骤流程

`video_montage_page.py`（38 万字节，最大页面）通过分步视图实现：

```
Step 1: 镜头分割          Step 2: 精华筛选          Step 3: 配音字幕          Step 4: 合成导出
┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│ 添加素材      │  →   │ 勾选精华片段  │  →   │ 输入口播文案  │  →   │ 设置参数      │
│ 分析镜头      │       │ 调整顺序      │       │ 选择声音样本  │       │ 合成视频      │
│ 场景切分      │       │ 预览片段      │       │ 自动生成字幕  │       │ 输出文件      │
└──────────────┘       └──────────────┘       └──────────────┘       └──────────────┘
```

各步骤视图位于 `gui/montage/` 目录：
- `step1_split_view.py` — 镜头分割与素材导入
- `step2_concat_view.py` — 片段排列与预览
- `step3_voice_view.py` — 配音与字幕生成
- `step4_final_view.py` — 合成参数与导出

### 4.4 后台服务监控体系

```
SystemStatusOverlay (状态栏)
  └── _StatsCollector (QThread)
        └── 每 3 秒轮询 远程服务器 /health 接口
              ├── CPU 使用率
              ├── RAM 使用率
              └── GPU 显存/利用率

AIStatusCheckThread (QThread)
  └── 定期检测各 AI 服务连通性
        ├── Ollama: 🟢/🔴
        ├── 视觉模型: 🟢/🔴
        ├── Whisper: 🟢/🔴
        ├── CLIP: 🟢/🔴
        └── VoxCPM: 🟢/🔴

SystemMonitorThread (QThread)
  └── 本地 ComfyUI 进程监控
```

### 4.5 授权与激活体系

- 启动时检测激活状态（`license.py`）
- 白名单：`config/trial_whitelist.json` 免激活
- 开发跳过：环境变量 `TINTIN_NO_LICENSE=1`
- RSA 签名签发（`license_private.pem` / `license_public.pem`）
- 激活缓存：`config/.activation_cache`

---

## 五、数据流与依赖关系

### 5.1 主要数据文件

| 文件 | 格式 | 用途 | 关联页面 |
|------|------|------|---------|
| `data/product_library.json` | JSON | 产品资料存储（54 万字节） | 产品资料/产品文案创作 |
| `data/my_knowledge.json` | JSON | 个人知识库（90 万字节） | 我的知识库 |
| `data/media_library.json` | JSON | 媒体素材库索引 | 素材管理/向量检索 |
| `data/hotspots.json` | JSON | 热点数据 | 热点追踪 |
| `data/video_predictions.json` | JSON | 视频预测评价数据 | 视频预测评价 |
| `data/brand_dictionary.json` | JSON | 品牌名称词典 | 品牌规范化 |
| `accounts/accounts.json` | JSON | 抖音账号信息 | 账号管理 |
| `config/ai_config.json` | JSON | AI 服务地址/密钥 | 系统设置 |

### 5.2 关键依赖关系

```
gui_main.py (MainWindow)
  ├── gui/main_window_sidebar.py    → 侧边栏
  ├── gui/main_window_pages.py      → 页面注册
  ├── config/paths.py               → 路径常量
  ├── utils/logger_utils.py         → 日志
  ├── utils/account_manager.py      → 账号管理
  ├── utils/gui_icons.py            → 图标
  ├── core/creator_browser_controller.py → 浏览器控制
  ├── gui/threads.py                → 后台线程
  └── gui/dialogs.py                → 对话框

每个功能页面 →
  ├── utils/xxx_client.py           → 远程服务调用
  └── utils/xxx_manager.py          → 本地数据管理
```

---

## 六、app 目录说明

`apps/` 目录下的第三方工具（约 59 GB）**不纳入版本控制**，通过 `.gitignore` 排除：

| 工具 | 版本 | 用途 | 调用方式 |
|------|------|------|---------|
| PaddleOCR | — | OCR 文字识别 | `PaddleOCR_SCRIPT` 子进程调用 |
| VSR v1.1.1 | v1.1.1 | 视频超分/去字幕（旧版） | 子进程调用 |
| VSR v1.4.0 | v1.4.0 | 视频超分/去字幕（新版） | 子进程调用 |
| rembg | — | AI 抠图 | Python 直接导入 |
| comfyui | — | AI 图像生成 | HTTP + WebSocket |
| asset-browser | Electron | 素材浏览器 | 子进程启动 |
| pw-browsers | Chromium | Playwright 浏览器内核 | Playwright 调用 |
| clip-models-hf | OFA-Sys/chinese-clip | CLIP 向量模型（Fallback） | transformers |
| voxcpm2 | VoxCPM2 | 声音克隆模型 | 远程服务端模式 |
| modelscope | — | ModelScope 模型 | Python 导入 |

---

## 七、技术栈全景

| 层 | 技术 |
|----|------|
| **客户端 GUI** | PySide6 (Qt 6.6.3) |
| **服务端 AI 推理** | FastAPI · Whisper · VoxCPM2 · Ollama (vLLM) · Chinese-CLIP |
| **图像生成** | ComfyUI（独立服务节点）|
| **文案生成** | DeepSeek API（云端）/ 自定义 LLM API |
| **Web 引擎** | QtWebEngine / Playwright / Selenium |
| **本地处理** | ffmpeg · VSR · rembg · PaddleOCR · OpenCV |
| **数据存储** | JSON 文件（本地）· PostgreSQL+pgvector · MySQL · MongoDB · RustFS/S3 |
| **构建** | PyInstaller · Makefile |
| **素材浏览器** | Electron |
| **动画** | Remotion (Node.js) |
| **签名算法** | pyexecjs（执行抖音加密 JS）|

---

## 八、功能状态总表

### ✅ 当前可用功能

| 分类 | 功能 | 核心文件 |
|------|------|---------|
| 方案脚本 | 我的知识库 | `my_knowledge_page.py`, `my_knowledge_manager.py` |
| 方案脚本 | 产品资料库 | `product_library_page.py`, `product_library_manager.py` |
| 方案脚本 | 产品文案创作 | `product_script_page.py` |
| 方案脚本 | 分镜脚本创作 | `storyboard_page.py` |
| 媒体库 | 即梦 AI 生成 | `dreamina_page.py`, `dreamina_client.py` |
| 媒体库 | 素材管理 | `video_indexer.py` |
| 媒体库 | 素材浏览器 | Electron app + `asset_browser_client.py` |
| 媒体库 | 向量检索 | `vector_search_page.py` |
| 媒体库 | 任务队列 | — |
| 成片制作 | 智能混剪 | `video_montage_page.py`, `gui/montage/` |
| 成片制作 | 直播切片 | `live_clip_page.py` |
| 图形处理 | 图像抠图 | `image_matting_page.py` |
| 图形处理 | 图片框选 OCR | `image_folder_ocr_page.py` |
| 视频处理 | 视频转文字 | `transcription_page.py`, `asr_client.py` |
| 视频处理 | 声音克隆 | `voice_clone_page.py`, `voxcpm_client.py` |
| 视频处理 | 视频去字幕 | `subtitle_removal_page.py` / `subtitle_removal_page_v14.py` |
| 视频处理 | 视频框选 OCR | `video_ocr_page.py` |
| 视频处理 | 视频预测评价 | `hook_score_page.py`, `video_prediction_manager.py` |
| 视频处理 | 营销视频检测 | `marketing_detect_page.py` |
| 系统设置 | 所有配置页面 | `main_window_aiconfig.py`, `env_config_page.py` |

### 🔒 已开发但暂时隐藏

| 功能 | 文件 | 说明 |
|------|------|------|
| 即梦素材 | `dreamina_assets_page.py` | 即梦生成素材管理 |
| MG 动画 | `mg_animation_page.py` | Remotion 动态图形 |
| 智能分层 | `image_layered_page.py` | AI 图像分层 |
| 视频修复 | `subtitle_removal_page_v14.py` | VSR 超分修复 |
| 视频重命名 | `video_ai_rename_page.py` | 视觉模型智能命名 |
| 批量 LUT | `video_lut_page.py` | LUT 色彩预设 |
| 封面制作 | `cover_maker_page.py` | 批量电商封面生成 |
| 一键成片 | `compile_video_page.py` | ComfyUI 工作流 |

### 📅 下版本计划

| 功能 | 说明 |
|------|------|
| 数字人 | 数字人形象生成 |
| 飞书选题 | 从飞书表格同步选题 |

---

## 九、运行与构建

### 开发模式
```powershell
python build.py run
# 或直接
python studio/gui_main.py
```

### 依赖管理
- `studio/requirements_gui.txt` — GUI 主程序依赖（PySide6 / 图像视频处理等）
- `studio/requirements.txt` — 爬虫/数据库/Flask 等后端依赖
- `studio/requirements_dev.txt` — 开发工具（PyInstaller / Playwright）

### 发布构建
打包/构建/加固逻辑在独立发布工程 `TinTin_Release_Builder` 中。
