# 需求 & Bug 修改记录

> 最后更新：2026-07-24

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

- [x] **21.** 镜头重组按钮失效修复（`_build_precompose_plans` 方法定义行丢失）
  - 根因：`video_montage_page.py` 中 `_build_precompose_plans` 方法体代码存在，但缺少 `def` 声明行，导致 Python 解析异常
  - 按钮点击触发 `AttributeError` 后被 PySide6 信号槽静默吞掉，无任何报错提示
  - 修复：在对应位置插入完整方法声明 `def _build_precompose_plans(self, clips, target_clip_count, batch_count, randomness, duration_limit_sec):`
  - **文件**：`studio/gui/video_montage_page.py`

- [x] **22.** AI 文案生成 / AI 改写按钮失效修复（Worker 构造参数 NameError）
  - 根因：`GenScriptWorker` 和 `BatchAITextRewriteWorker` 构造时传入未定义的 `api_url`、`api_key` 变量 → `NameError`
  - 这两个 Worker 内部实际通过 `llm_chat()` 走服务端代理，不依赖构造时传入的 API 凭证
  - 修复：统一改为传空字符串 `""`, `""`
  - **文件**：`studio/gui/video_montage_page.py`

- [x] **23.** `BatchAITextRewriteWorker.run()` 内部引用未定义变量修复
  - 根因：`run()` 方法中使用 `requests.post(url, json=payload, headers=headers, ...)` 但 `url`、`headers` 未定义
  - 已导入 `llm_chat` 却未使用，实际请求走了错误的代码路径
  - 修复：替换为 `llm_chat(system_prompt, input_text, model=self.model, timeout=20)` 统一走服务端代理
  - **文件**：`studio/gui/montage/workers/script_workers.py`

- [x] **24.** 声音样本「生成参考文案」时服务端卡死掉线修复（FastAPI 事件循环被同步调用阻塞）
  - 现象：声音样本页点击「根据音频生成/更新参考文案」后，服务端卡死、客户端健康检查灯变红（掉线），但右上角 CPU/内存显示正常
  - 根因：真凶不在声音样本功能本身（音频转写走客户端本地 whisperx 子进程，唯一服务端交互是加标点的 `/llm/chat/completions`，已放行且异步），而是客户端每 10s 轮询的 `/ollama/status`：
    - 该端点**不在** `client_limit_middleware` 放行列表，每次请求都触发 `_load_cache()` → `get_machine_id()` → 同步 `subprocess.run(dmidecode, timeout=5)`，阻塞整个 asyncio 事件循环最多 5s
    - 端点内 `_ollama_alive()` 使用同步 `httpx.get(timeout=3)`，再阻塞最多 3s
    - 事件循环被卡期间所有请求排队，而客户端健康检查超时仅 2~3s，等不到响应即判定离线 → 状态灯 🔴
    - 右上角 CPU/内存来自 `/health`（在放行列表、不阻塞），故资源显示正常但状态灯掉线
  - 修复：
    - `get_machine_id()` 增加模块级缓存 `_MACHINE_ID_CACHE`（机器码运行期恒定，dmidecode 只执行一次）
    - `/ollama/status` 加入 `client_limit_middleware` 放行列表
    - `_ollama_alive()` 改为 async（`httpx.AsyncClient`），全部 9 处调用点补 `await`；`start_ollama` 等待循环 `time.sleep(1)` → `await asyncio.sleep(1)`
  - **文件**：`server/api/license.py`、`server/server.py`、`server/api/ollama.py`（服务端代码，需同步部署到远程 Linux 服务端并重启生效）

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

- [x] **20.** 智能分割支持主要产品提示词
  - 步骤 1 新增「主要产品提示词」输入框（选填，限 100 字）+ 清空按钮
  - 提示词非空时：确认框提示、分割完成后自动触发镜头分析
  - `ServerClipAnalysisWorker` 提交 `/material/score_clip` 时携带 `product_prompt` 字段，服务端 AI 围绕该产品精确评分与描述
  - 提示词为空时保持原有行为（向后兼容；服务端未升级时忽略该字段不报错）
  - **文件**：`studio/gui/montage/step1_split_view.py`、`studio/gui/video_montage_page.py`、`studio/gui/montage/workers/split_workers.py`

- [x] **21.** 修复步骤3配音列表混入目录残留视频（5 条预合成变 29 条）
  - 根因：进入步骤3只传入目录，`_do_scan_voice_video_dir` 退化为 `os.listdir` 整目录扫描，把残留的历史分割镜头片段一并混入配音表
  - 修复：`_on_enter_step_3` 把已确认合成的预合成视频作为明确文件列表传入；扫描逻辑支持跨目录选中文件并去重/存在性过滤
  - 兼容：手动改目录时清除旧文件级选择恢复目录扫描；手动选文件场景行为不变
  - **文件**：`studio/gui/video_montage_page.py`

- [x] **22.** 客户端轻量化：剩余模型调用服务端化（P1+P2）
  - 新增 `utils/montage_client.py`：`describe_shots()` 走 `/material/score_clip` 批量生成镜头描述（修复 ServerDescribeWorker 导入缺失模块）
  - 新增 `utils/matting_client.py`：抠图改为上传服务端 `POST /material/matting`，`RembgWorker` 不再本地加载 rembg/U2Net（抠图页与封面制作共用）
  - storyboard 相似度检索/自动绑定素材改调服务端 `/material/search`（移除 `search_by_text` 死代码，消除 NameError）
  - 修复 `BatchGenerateDescriptionsWorker` 引用未定义 `url` 的 NameError，LLM 调用简化为 `llm_chat_messages`
  - 待服务端落地 `/material/matting` 后联调；二期可移除 `apps/rembg`、`apps/vsr` 本地依赖
  - **文件**：`studio/utils/montage_client.py`、`studio/utils/matting_client.py`、`studio/gui/image_matting_page.py`、`studio/gui/storyboard_page.py`、`studio/gui/montage/workers/desc_workers.py`

- [x] **23.** 修复试听配音不能暂停
  - 根因：`_play_audio` 播放中再点只会 `stop()` 后重新播放，未处理 PausedState；且 Windows 下 QUrl 正斜杠路径与 abspath 反斜杠比较永远不相等，"同一音频"判断失效
  - 修复：改为三态切换——播放中→暂停、已暂停→继续、切换其它音频→停止并重新播放；路径比较前统一 `normpath`
  - 同步修复 `voice_clone_page.py` 中相同逻辑
  - **文件**：`studio/gui/video_montage_page.py`、`studio/gui/voice_clone_page.py`

- [x] **24.** 分镜头定点预览（无需从头播完整个视频）
  - 新增 `_preview_shot`：优先用 ffplay `-autoexit -ss 起点 -t 时长` 从镜头起始时间点直接预览，播完自动关闭；解析文件名时间戳，无时间戳时用表格缓存的 time_str；找不到 ffplay 回退系统默认播放器
  - 双击表格行预览改走 `_preview_shot`；表格头部新增「▶ 预览选中镜头」按钮（`_preview_selected_shot`/`_preview_shot_by_row`）
  - `platform_utils.py` 新增 `find_ffplay()`（同目录/PATH/工程根目录三级查找）
  - **文件**：`studio/utils/platform_utils.py`、`studio/gui/video_montage_page.py`、`studio/gui/montage/step1_split_view.py`

- [x] **25.** 修复重启后新建任务仍出现历史生成的视频
  - 根因：重启后会话内存（预合成方案/配音记录）清空，但步骤3 `_on_enter_step_3` 与步骤4 `_populate_default_mix_videos` 存在整目录扫描回退，把 outputs 里上次生成的旧视频自动扫进列表
  - 修复：新增 `_voice_scan_allow_dir_fallback` 开关——会话内无已合成视频时禁止配音表目录扫描回退；`_populate_default_mix_videos` 移除 outputs 目录扫描回退，只列本次会话生成的已配音视频（旧视频可「添加视频」手动选择）
  - 兼容：手动选择文件/修改目录时恢复目录扫描语义
  - **文件**：`studio/gui/video_montage_page.py`

- [x] **26.** VSR 去字幕切换服务端（客户端轻量化 P3-E）
  - 新增 `utils/vsr_client.py`：`vsr_remove_remote()` 封装上传 `/vsr/remove` → 轮询 `/tasks/unified/{id}` → 下载 `/vsr/download/{filename}` 并落盘本地（原名_no_sub.mp4）
  - 两个去字幕页面新增「使用服务端处理」开关且默认勾选：老页远程 Worker 改用 vsr_client（结果直接落盘，不再只显示下载链接）；v14 页新增服务端分支（多选区转 sub_areas，sttn→sttn_auto 映射）
  - 本地模式保留作回退；连通性已验证（/vsr/remove 路由就绪）；待实际视频端到端验证后可移除 apps/vsr-* 目录
  - **文件**：`studio/utils/vsr_client.py`、`studio/gui/subtitle_removal_page.py`、`studio/gui/subtitle_removal_page_v14.py`

---

## 待实现

- [ ] **27.** 生成脚本后关联素材
  - 当前生成的 `.txt` 口播文案与素材的关联是隐式的（同名、同目录）
  - 需要为脚本建立与源镜头/素材的显式关联（如在产品资料库中关联脚本）
  - 支持从脚本反查使用了哪些分割镜头，从分割镜头反查属于哪个脚本
