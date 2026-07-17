# 需求 & Bug 修改记录

> 最后更新：2026-07-17

---

## 我的知识库

- [x] **1.** 我的知识库页面 - 知识背景功能按钮 删除
- [x] **2.** 我的知识库页面 - 参考素材 下载状态 更新
- [x] **3.** 素材浏览器 本地下载地址 移除项目，可指定项目文件内目录只存地址
- [x] **4.** 飞书的按钮 隐藏（功能代码保留）
- [x] **5.** 素材检索页面 关键词搜索和品牌的混合查询检查 —— 已确认：关键词+品牌是同一接口 `/material/search` 的混合查询

---

## 系统配置

- [x] **6.** 模型配置页面 API 地址做成统一配置
  - 页面顶部添加统一服务端地址输入框 (`compute_server_url`)
  - PaddleOCR 使用本地模型，移除 API 地址输入框
  - 所有 Tab 的保存按钮 (LLM/Ollama/Whisper/CLIP) 均保存统一地址 + 各接口地址
  - 顶部「保存全部」按钮保存全部配置 (含 VoxCPM 参数)
  - 统一地址修改后联动更新 Whisper/CLIP（始终使用统一地址）
  - VoxCPM 的 API 地址保留手动维护（需手动加 `/voxcpm/tts` 后缀）
  - 6 个模型 Tab 合并为单个滚动页面
  - 模型专属 API 地址输入框置灰只读：`llm_api_url_input`、`llm_vision_api_url_input`、`vox_api_url_input`、`whisper_api_url_input`、`clip_api_url_input`
  - **文件**：`studio/gui/main_window_pages.py`、`studio/gui/main_window_aiconfig.py`

- [x] **8.** LLM 大语言模型 API 地址根据提供商自动切换
  - 提供商下拉框：DeepSeek / OpenAI / Ollama / 阿里云 DashScope / 智谱 GLM / Moonshot(Kimi) / 自定义
  - 选择预设提供商时 API 地址自动填充并置灰只读
  - 选择「自定义」时 API 地址恢复可编辑
  - API Key 输入框从 UI 隐藏（保留隐藏属性避免崩溃）
  - **文件**：`studio/gui/main_window_pages.py`、`studio/gui/main_window_aiconfig.py`

- [x] **9.** 模型配置页各模块按钮区域统一
  - VoxCPM「保存」按钮样式修正
  - VoxCPM 状态标签移至按钮下方独立行
  - Whisper / CLIP 按钮对齐统一
  - **文件**：`studio/gui/main_window_pages.py`

---

## Bug 修复

- [x] **7.** 任务队列页面点击后卡顿崩溃修复
  - 根因：`_sync_server_tasks_async` 在 Worker 子线程中直接操作 Qt 控件
  - 修复：拆分为 `_fetch_server_tasks_data()`（纯数据）+ `_apply_server_tasks_data()`（GUI 更新）
  - Worker 对象存为 `self._sync_worker` 防止 GC 回收
  - 「同步服务端」按钮改用 `_sync_server_tasks_async`
  - **文件**：`studio/gui/main_window_pages.py`

- [x] **11.** LLM 调用 URL 修复：`/llm/chat` → `/llm/chat/completions`
  - 根因：服务端实际端点为 `/llm/chat/completions`，客户端打 `/llm/chat` 返回 404
  - 导致所有 LLM 调用无响应且服务端无日志
  - **文件**：`studio/utils/llm_proxy.py`

- [x] **12.** 视觉 LLM 全部迁移到服务端代理
  - 6 个文件的视觉模型调用从直连 `/v1/chat/completions` → `llm_chat_messages()` 走代理
  - `cover_maker_page` / `hook_score_page` / `marketing_detect_page` / `video_ai_rename_page` / `video_indexer`
  - `LocalVisionDescWorker`：Ollama raw API → `llm_chat_messages()`
  - `main_window_aiconfig` 视觉连接测试改为走代理
  - **文件**：`studio/gui/cover_maker_page.py`、`hook_score_page.py`、`marketing_detect_page.py`、`video_ai_rename_page.py`、`main_window_aiconfig.py`、`video_montage_page.py`、`studio/utils/video_indexer.py`

- [x] **13.** 过时 `api_url`/`api_key` 校验清理 + NameError 修复
  - `product_library_page._on_mine()`：引用未定义的 `url`/`key` → NameError
  - `video_montage_page._batch_gen_copy_by_scene` / `_gen_copy_for_assembled`：同上
  - `_run_batch_vision_descriptions` / `_trigger_vision_on_dir`：阻塞 + 崩溃
  - 修复：统一改为只检查 `model`，`api_url`/`api_key` 传空串
  - **文件**：`product_library_page.py`、`video_montage_page.py`、`my_knowledge_page.py`、`product_script_page.py`、`storyboard_page.py`

- [x] **14.** 镜头重组预览播放卡死修复
  - 根因：`_on_preview_media_status_changed` 在 `EndOfMedia` 信号回调里直接调 `setSource()`
  - 修复：`QTimer.singleShot(50)` 延迟到下一事件循环，新增 `InvalidMedia` 跳过处理
  - **文件**：`studio/gui/video_montage_page.py`

---

## 智能混剪

- [x] **10.** 智能混剪「按文案智能匹配」模式功能改造
  - 「合成视频生成文案」按钮仅在「随机洗牌」模式显示
  - 新增「🤖 AI 生成文案」按钮：根据勾选的镜头素材描述 + 产品背景 + 时长限制生成口播文案
  - 「镜头重组」按钮移至脚本工具栏右侧
  - 时长限制控件两种模式下均可见
  - 新增 `GenScriptWorker` + 回调方法
  - **文件**：`studio/gui/montage/step2_concat_view.py`、`studio/gui/video_montage_page.py`

- [x] **15.** 分割镜头综合评分系统
  - `_score_clip()`：5 维度 0~10 分（清晰度 / 干净度 / 抖动 / 主体突出 / 曝光）
  - 步骤 1 表格 + 步骤 2 表格 + 预合成详情均显示评分（🟢≥8 / 🟡≥6 / 🔴<6）
  - 评分 ≥7 分默认自动勾选，缓存复用避免重复计算
  - **文件**：`studio/gui/video_montage_page.py`、`studio/gui/montage/step1_split_view.py`

- [x] **16.** 镜头去重择优
  - `_compute_clip_hash()`：帧哈希 64-bit + 汉明距离
  - `_compute_clip_quality()`：清晰度 + 对比度 + 音频综合质量分
  - `_build_precompose_plans`：相似镜头（距离 < 8）→ 高质量替换 / 低质量跳过
  - **文件**：`studio/gui/video_montage_page.py`

- [x] **17.** LUT 色彩还原配置
  - 系统设置新增「资源配置」分区（独立于系统工具）
  - 视频配置 tab：添加/删除 LUT 映射（名称 → 文件路径），存 `video_config.json`
  - 镜头重组界面新增 LUT 还原下拉框（默认"无"）
  - `_concat_with_transition` 拼接时应用 `lut3d` 滤镜
  - 新增 `video_config.example.json` 模板
  - **文件**：`studio/config/paths.py`、`studio/gui/main_window_pages.py`、`studio/gui/video_montage_page.py`、`studio/gui/montage/step2_concat_view.py`

- [x] **18.** 预合成列表文案显示优化
  - 文案状态从图标 (📄) 改为文字预览 (📝 前 30 字)
  - 双击预合成列表项弹窗显示完整文案
  - **文件**：`studio/gui/video_montage_page.py`、`studio/gui/montage/step2_concat_view.py`

- [x] **19.** 灰片 / Log 视频检测工具
  - `detect_log_video()`：ffprobe 色彩元数据 + 帧对比度分析
  - `probe_color_metadata()`：读取 `color_transfer` / `pix_fmt` / `color_space`
  - **文件**：`studio/utils/video_indexer.py`

---

## 待实现

- [ ] **20.** 生成脚本后关联素材
  - 当前生成的 `.txt` 口播文案与素材的关联是隐式的（同名、同目录）
  - 需要为脚本建立与源镜头/素材的显式关联（如在产品资料库中关联脚本）
  - 支持从脚本反查使用了哪些分割镜头，从分割镜头反查属于哪个脚本
