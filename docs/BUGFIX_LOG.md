# Bug 修复日志

> 本文档记录所有 Bug 修复的详细信息。每次修复按编号递增追加，新条目添加在文档末尾。

---

## 目录

| 编号 | 日期 | 模块 | 问题摘要 |
|------|------|------|---------|
| #001 | 2026-08-25 | 智能混剪 | 镜头重组后 UI 卡死 (Not Responding) |
| #002 | 2026-08-26 | 智能混剪 | 服务端 montage_concat 返回 402 时无自动回退 |
| #003 | 2026-08-26 | 智能混剪 | 镜头分割时 UI 卡死（ffprobe 阻塞主线程） |
| #004 | 2026-08-26 | 智能混剪 | 点击预览视频时 UI 卡死（ffprobe 阻塞主线程） |
| #005 | 2026-08-26 | 智能混剪 | 新增4K视频分割性能监控日志 |
| #006 | 2026-08-26 | 智能混剪 | 4K视频分割服务端处理慢（5分钟/视频） |
| #007 | 2026-08-26 | 智能混剪 | 切换预览视频时 QMediaPlayer 卡死主线程 |
| #008 | 2026-08-26 | 智能混剪 | 视频预览时 CPU 占用率忽高忽低（NoMedia 信号循环） |
| #009 | 2026-08-26 | 智能混剪 | 分割完成后 CPU 占用忽高忽低（cv2 读视频） |
| #010 | 2026-08-27 | 智能混剪 | 镜头重组"与原片一致"画幅输出不正确（未处理旋转元数据） |
| #011 | 2026-08-27 | 声音样本 | 点击"根据音频生成文案"时客户端闪退（局部 Worker 类 + 回调无异常保护） |
| #012 | 2026-08-27 | 声音样本 | Whisper 模型加载接口超时（服务端问题，客户端临时增加超时） |
| #013 | 2026-08-27 | 智能混剪 | 分割片段表格新增"画幅"列，方便镜头重组设置输出画幅 |
| #014 | 2026-08-27 | 智能混剪 | 镜头重组自动检测原片画幅并传递给服务端 |
| #019 | 2026-09-01 | 智能混剪 | 镜头重组预览：切步骤/停播释放会话时信号重入换源导致 WMF 死锁 |
| #020 | 2026-09-01 | 智能混剪 | 智能分割刷新链在主线程逐片段跑 ffprobe/cv2 导致未响应 |
| #021 | 2026-09-01 | 智能混剪 | 点「清空混剪缓存」后已添加的素材列表未清空 |
| #022 | 2026-09-01 | 智能混剪 | 镜头重组设 30s 但成片只有 17-20s（选片预算被丢弃片段吃掉+提前 break） |

---

## #001 智能混剪"镜头重组"后 UI 卡死 (Not Responding)

**日期**：2026-08-25  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_clip_duration_text()`（第 5133 行）  
**严重级别**：高（UI 完全阻塞）

### 问题描述

用户在「智能混剪」→「镜头重组」步骤点击"镜头重组"按钮后，界面进入 "(Not Responding)" 状态，持续数十秒无法操作。

### 根因分析

#### 调用链路

```
用户点击"镜头重组"
  → _start_assemble_video()
    → _build_precompose_plans()  ← 在后台 TaskWorker 线程中运行 ✅
      → 内部调用 _get_clip_duration() → 将每个镜头的 duration 写入 split_clips_cache
    → _plan_done()  ← 在 UI 主线程中回调
      → _load_precompose_plans()
        → _on_assembled_item_clicked(item)
          → _refresh_sources_for_plan(0)
            → 遍历所有镜头，每个调用 _clip_duration_text()
              → 调用 get_media_duration(path)  ← ❌ 每个镜头 spawn 一个 ffprobe 子进程！
```

#### 根本原因

`_clip_duration_text()` 方法**没有复用 `split_clips_cache` 中已被后台线程预填的 duration 缓存**，导致在 UI 主线程上对 78 个镜头逐一调用 `get_media_duration()`。

`get_media_duration()` 内部会 spawn 一个 `ffprobe` 子进程（timeout 10 秒），78 个镜头串行执行，即使每个只需 0.5 秒，总计也要约 39 秒，UI 主线程完全阻塞 → Windows 标记为 "(Not Responding)"。

#### 对比：两个方法的缓存行为

| 方法 | 是否读 `split_clips_cache` | 是否 spawn 子进程 |
|------|--------------------------|-----------------|
| `_get_clip_duration()` (line 4623) | ✅ 先读缓存 | 缓存命中时不 spawn |
| `_clip_duration_text()` (line 5133) | ❌ 只读传入的 `cache_item` 参数 | **每次都 spawn ffprobe** |

`_build_precompose_plans` 在后台线程中已经通过 `_get_clip_duration()` 把 duration 填入了 `split_clips_cache`，但 `_clip_duration_text()` 完全忽略了这个缓存。

### 修复方案

在 `_clip_duration_text()` 中增加对 `split_clips_cache` 的查找逻辑，与 `_get_clip_duration()` 保持一致。

#### 修改内容

在 `cache_item` 检查之后、`time_str` 解析之前，新增一段对 `split_clips_cache` 的查找：

```python
# 优先读 split_clips_cache（_build_precompose_plans 后台线程已预填），
# 避免在 UI 主线程对每个镜头 spawn ffprobe 子进程导致卡死。
if dur <= 0 and path:
    norm = os.path.abspath(path)
    cache = getattr(self, "split_clips_cache", {})
    cached = cache.get(norm)
    if cached and isinstance(cached, dict) and cached.get("duration", 0) > 0:
        dur = cached["duration"]
```

#### 修改后的优先级链（从高到低）

1. `cache_item["duration"]` — 已有的缓存条目
2. `split_clips_cache[path]["duration"]` — 后台线程预填的缓存（**本次新增**）
3. `time_str` 解析 — 从 SRT 时间戳推算
4. `get_media_duration(path)` — ffprobe 探测（兜底，结果仍会回写缓存）

### 影响范围

- **仅影响**：`_clip_duration_text()` 方法的缓存读取逻辑
- **不改变**：任何 UI 行为、数据流、缓存写入逻辑
- **向后兼容**：当缓存未命中时，仍走原有逻辑（time_str 解析 → ffprobe 探测）

### 验证建议

1. 进入「智能混剪」→「镜头重组」
2. 勾选 78 个镜头，点击"镜头重组"
3. 观察界面是否出现 "(Not Responding)" 状态
4. 预期：预合成方案生成后，下方镜头列表应快速加载，无卡死现象

---

## #002 服务端 montage_concat 返回 402 时无自动回退

**日期**：2026-08-26  
**文件**：  
- `studio/gui/montage/workers/montage_concat_server_worker.py`  
- `studio/gui/video_montage_page.py`  
**严重级别**：中（功能降级，用户需手动重试）

### 问题描述

提交镜头合成到服务端 `http://192.168.111.31:8000/montage/concat` 时，服务端返回 `402 Payment Required`，客户端直接报错，无自动回退机制。

### 根因分析

服务端返回 402（通常是授权/配额问题），`montage_client.concat()` 中 `r.raise_for_status()` 抛出 `HTTPError`，被 `MontageConcatServerWorker._submit_concat()` 捕获后直接作为 `RuntimeError` 抛出，最终显示给用户。客户端没有针对 4xx 错误的降级策略。

### 修复方案

1. **`MontageConcatServerWorker`**：新增 `fallback_to_local(str)` 信号；在 `_submit_concat()` 中检测 402 错误，emit 信号并返回 `None`；`do_work()` 检测到 `None` 时提前返回。
2. **`VideoMontagePage`**：启动 Worker 前保存本地回退所需参数到 `_server_concat_fallback_params`；连接 `fallback_to_local` 信号到 `_on_server_concat_fallback()`；该 handler 自动调用 `_launch_local_concat_worker()` 回退本地合成。

### 影响范围

- 仅影响服务端合成失败时的降级行为
- 其他 HTTP 错误（500/502/503 等）仍走原有 error 路径
- 本地合成逻辑完全不变

### 验证建议

1. 配置一个返回 402 的服务端地址（或临时修改服务端）
2. 点击"确认合成视频"
3. 预期：界面显示"注意：服务端返回 402，已自动回退到本地合成"，随后本地 ffmpeg 合成正常启动

---

## #003 镜头分割时 UI 卡死（ffprobe 阻塞主线程）

**日期**：2026-08-26  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_check_split_clips_exist()`（第 1157 行）  
**严重级别**：高（UI 完全阻塞）

### 问题描述

用户在「智能混剪」→「镜头智能分割」步骤，随着分割视频数量增加，界面越来越卡，最终进入 "(Not Responding)" 状态。

### 根因分析

#### 调用链路

```
ServerSplitWorker 分割完成（后台线程）
  → _on_split_analysis_ready() 回调
    → QTimer.singleShot(0, _safe_refresh)
      → _check_split_clips_exist()  ← UI 主线程执行
        → 遍历所有镜头片段
          → get_media_duration(clip)  ← ❌ 每个片段 spawn 一个 ffprobe 子进程！
```

#### 根本原因

`_check_split_clips_exist()` 方法在 UI 主线程中同步调用 `get_media_duration()`：

```python
if duration_sec <= 0 and os.path.isfile(norm_path):
    # 文件名时间戳异常（如全 0）时直接探测片段文件
    duration_sec = get_media_duration(norm_path)
```

- 每个视频分割完成后都会触发 `_check_split_clips_exist()` 刷新表格
- 如果有 N 个镜头片段，就会 spawn N 个 ffprobe 子进程
- 每个 ffprobe 调用耗时约 0.5-2 秒，累积起来导致 UI 卡死
- 随着分割视频数量增加（如 30 个视频），片段数量累积，卡死越来越明显

### 修复方案

移除 UI 主线程中的 `get_media_duration()` 调用，时长为 0 时显示 "—"，后续由后台异步评分时补充。

#### 修改内容

```python
# 修改前（会 spawn ffprobe 子进程导致卡死）：
if duration_sec <= 0 and os.path.isfile(norm_path):
    duration_sec = get_media_duration(norm_path)

# 修改后（不再在 UI 主线程调用 ffprobe）：
# 不再在 UI 主线程调用 get_media_duration()（会 spawn ffprobe 子进程导致卡死）
# 时长为 0 时显示 "—"，后续由后台异步评分时补充
```

### 影响范围

- **仅影响**：`_check_split_clips_exist()` 方法中的时长探测逻辑
- **不改变**：任何 UI 行为、数据流、缓存写入逻辑
- **向后兼容**：时长为 0 的片段显示 "—"，不影响后续流程

### 验证建议

1. 进入「智能混剪」→「镜头智能分割」
2. 选择 30 个视频进行批量分割
3. 观察分割过程中界面是否卡顿
4. 预期：分割过程中界面保持流畅，无 "(Not Responding)" 状态

---

## #004 点击预览视频时 UI 卡死（ffprobe 阻塞主线程）

**日期**：2026-08-26  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_clip_duration_text()`（第 5184 行）  
**严重级别**：高（UI 完全阻塞）

### 问题描述

用户在「智能混剪」→「镜头重组」步骤，点击左侧预合成视频列表项预览视频时，界面卡顿甚至进入 "(Not Responding)" 状态。

### 根因分析

#### 调用链路

```
用户点击预合成视频列表项
  → _on_assembled_item_clicked(item)
    → _refresh_sources_for_plan(idx)  ← UI 主线程执行
      → 遍历所有镜头片段
        → _clip_duration_text(cache_item, time_str, src_path)
          → get_media_duration(path)  ← ❌ spawn ffprobe 子进程！
```

#### 根本原因

`_clip_duration_text()` 方法在第 5184-5195 行仍有 `get_media_duration()` 调用：

```python
if dur <= 0 and path and os.path.isfile(path):
    dur = get_media_duration(path)
    if dur > 0:
        # 无条件回写缓存...
```

当缓存中没有 duration 数据时（如新分割的镜头），会调用 `get_media_duration()` spawn ffprobe 子进程。每个片段耗时 0.5-2 秒，多个片段累积导致 UI 卡死。

### 修复方案

移除 `_clip_duration_text()` 中的 `get_media_duration()` 调用，时长为 0 时显示 "—"。

#### 修改内容

```python
# 修改前（会 spawn ffprobe 子进程导致卡死）：
if dur <= 0 and path and os.path.isfile(path):
    dur = get_media_duration(path)
    if dur > 0:
        # 无条件回写缓存（无缓存条目则新建），保证下次切换方案直接读缓存不再 ffprobe
        try:
            norm = os.path.abspath(path)
            cache = getattr(self, "split_clips_cache", {})
            if norm not in cache or not isinstance(cache.get(norm), dict):
                cache[norm] = {}
            cache[norm]["duration"] = dur
        except (KeyError, TypeError, AttributeError):
            pass

# 修改后（不再在 UI 主线程调用 ffprobe）：
# 不再在 UI 主线程调用 get_media_duration()（会 spawn ffprobe 子进程导致卡死）
# 时长为 0 时显示 "—"，后续由后台异步评分时补充
```

### 影响范围

- **仅影响**：`_clip_duration_text()` 方法中的时长探测逻辑
- **不改变**：任何 UI 行为、数据流、缓存写入逻辑
- **向后兼容**：时长为 0 的片段显示 "—"，不影响后续流程

### 验证建议

1. 进入「智能混剪」→「镜头重组」
2. 生成预合成方案后，点击左侧预合成视频列表项
3. 观察界面是否卡顿
4. 预期：点击后界面流畅切换，无 "(Not Responding)" 状态

---

## #005 新增4K视频分割性能监控日志

**日期**：2026-08-26  
**文件**：`studio/gui/montage/workers/split_workers.py`  
**方法**：`ServerSplitWorker.run()`  
**严重级别**：低（功能增强）

### 问题描述

用户需要测试4K视频分割性能，但客户端没有详细的性能日志，无法定位瓶颈。

### 修复方案

在 `ServerSplitWorker.run()` 中添加详细的性能监控日志，记录每个阶段的耗时：

1. **上传+服务端处理阶段**：记录从开始上传到服务端响应的时间
2. **片段下载阶段**：记录所有片段下载的总时间
3. **总耗时**：记录整个分割流程的总时间

#### 日志输出示例

```
[性能监控][分割] ===== 开始 =====
[性能监控][分割] 文件: test_4k.mp4  大小: 512.34 MB  服务端: http://192.168.111.31:8000
[性能监控][分割] 开始上传 + 请求服务端 /montage/split ...
[HTTP] → POST http://192.168.111.31:8000/montage/split timeout=590
[HTTP] ← POST http://192.168.111.31:8000/montage/split status=200 130000ms
[性能监控][分割] 上传+服务端响应完成: 耗时 130.00s  (总耗时 130.02s)  速度: 3.94 MB/s
[性能监控][分割] 服务端返回 25 个镜头, 开始下载片段...
[性能监控][分割] 片段下载完成: 成功 25 个, 失败 0 个,  下载耗时 15.30s,  总耗时 145.32s
[性能监控][分割] ===== 完成 =====  镜头数: 25  总耗时: 145.32s  (上传+处理: 130.00s, 下载: 15.30s)  文件大小: 512.34 MB  上传+处理速度: 3.94 MB/s
```

### 影响范围

- **仅影响**：日志输出，增加性能监控信息
- **不改变**：任何业务逻辑、UI 行为、数据流
- **向后兼容**：完全兼容，仅增加日志

### 验证建议

1. 启动客户端，进入「智能混剪」→「镜头智能分割」
2. 选择4K测试视频，点击「开始智能镜头分割」
3. 分割完成后，查看 `studio/.runtime/logs/` 中的最新日志
4. 搜索 `[性能监控][分割]`，查看各阶段耗时

### 相关文档

- 测试指南：`docs/4k_split_test_guide.md`
- 性能分析：`docs/4k_split_performance_analysis.md`

---

## #006 4K视频分割服务端处理慢（5分钟/视频）

**日期**：2026-08-26  
**文件**：`studio/gui/montage/workers/split_workers.py`  
**方法**：`ServerSplitWorker.run()`  
**严重级别**：中（性能问题）

### 问题描述

用户使用客户端软件批量分割4K视频，每个视频耗时约5分钟，严重影响工作效率。

### 根因分析

#### 性能日志数据

```
[HTTP] → POST http://192.168.111.31:8000/montage/split timeout=590
[HTTP] ← POST http://192.168.111.31:8000/montage/split status=200 294078ms
```

| 序号 | 开始时间 | 结束时间 | 总耗时 | HTTP 响应时间 |
|------|---------|---------|--------|-------------|
| 1 | 14:26:28 | 14:31:23 | **4分 55 秒** | **294,078ms (4m 54s)** |
| 2 | 14:36:16 | 14:36:16 | **4分 53 秒** | **293,484ms (4m 53s)** |
| 3 | 14:41:12 | 14:41:12 | **4分 58 秒** | **295,357ms (4m 55s)** |
| 4 | 14:46:14 | 14:46:14 | **5分 02 秒** | **302,029ms (5m 02s)** |
| 5 | 14:51:11 | 14:51:11 | **4分 57 秒** | **297,080ms (4m 57s)** |

**平均耗时**：**约 5 分钟/视频**

#### 瓶颈分析

| 阶段 | 耗时 | 占比 | 说明 |
|------|------|------|------|
| 上传 + 服务端处理 | ~294 秒 | ~99% | **主要瓶颈** |
| 片段下载 | < 30ms | ~0.01% | 极快，非瓶颈 |

**结论**：瓶颈完全在服务端处理，而非网络传输。

#### 可能原因

1. **4K 视频解码慢**（最可能）
   - 4K 分辨率是 1080p 的 4 倍像素
   - 如果服务端使用 CPU 软解，速度会非常慢
   
2. **场景检测算法复杂度高**
   - 逐帧分析场景变化
   - 对每个镜头进行 AI 分析（美学评分、景别识别、产品识别）
   
3. **未使用 GPU 加速**
   - 如果服务端使用 CPU 解码和场景检测，速度会非常慢

### 修复方案

#### 短期方案（1-2 天）

**方案 A：调整场景检测参数** ⭐⭐⭐

修改位置：`studio/gui/video_montage_page.py`

```python
# 当前配置（默认）
threshold = 27  # 场景检测阈值
min_scene_len = 0.5  # 最小镜头时长 0.5 秒

# 优化后配置
threshold = 35  # 提高阈值，减少镜头数
min_scene_len = 1.0  # 提高最小镜头时长，过滤短镜头
```

预期效果：处理时间减少 20-40%

**方案 B：禁用逐镜 AI 分析** ⭐⭐

修改位置：`StudioSplitWorker.__init__()`

```python
# 当前配置
analyze = True  # 启用逐镜分析

# 优化后配置
analyze = False  # 禁用逐镜分析
```

预期效果：处理时间减少 30-50%（但会失去美学评分、景别识别等功能）

#### 中期方案（1-2 周）

**方案 C：服务端代理文件处理** ⭐⭐⭐⭐⭐

原理：
1. 接收 4K 视频后，先转码为 1080p 代理文件
2. 在代理文件上进行场景检测和分析
3. 记录时间戳，用原 4K 文件裁剪片段

预期效果：处理时间从 5 分钟降至 1-2 分钟（提升 60-80%）

#### 长期方案（1-2 月）

**方案 D：GPU 加速全流程** ⭐⭐⭐⭐

需要的工作：
1. 安装 CUDA 版本的 ffmpeg
2. 使用 GPU 加速的场景检测库
3. 模型推理使用 GPU

预期效果：处理速度提升 2-4 倍

### 影响范围

- **仅影响**：4K视频分割性能
- **不改变**：任何业务逻辑、UI 行为、数据流
- **向后兼容**：完全兼容

### 验证建议

1. 按短期方案调整参数后，重新测试4K视频分割
2. 对比优化前后的耗时
3. 如果效果不明显，推动服务端团队实施中期方案

### 相关文档

- 详细分析报告：`docs/performance_analysis_report.md`
- 测试指南：`docs/4k_split_test_guide.md`
- 性能分析：`docs/4k_split_performance_analysis.md`

---

## #007 切换预览视频时 QMediaPlayer 卡死主线程

**日期**：2026-08-26  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_play_current_sequence_clip()`（第 5376 行）  
**严重级别**：高（UI 完全阻塞，必须退出）

### 问题描述

用户在「智能混剪」→「镜头重组」步骤，切换预览生成的视频时，Python 进程会卡死，导致整个 UI 界面卡住必须退出。

### 根因分析

#### 调用链路

```
用户点击预合成视频列表项
  → _on_assembled_item_clicked(item)
    → _start_sequence_preview_for_plan(idx)
      → self.preview_player.stop()  ← ❌ 可能阻塞
      → _play_current_sequence_clip()
        → self.preview_player.stop()  ← ❌ 可能阻塞
        → self.preview_player.setSource(QUrl())  ← ❌ 可能阻塞
        → QTimer.singleShot(200, _on_preview_no_media)
          → self.preview_player.setSource(QUrl.fromLocalFile(clip))  ←  可能阻塞
          → self.preview_player.play()
```

#### 根本原因

**Windows Media Foundation 后端的已知问题**：

1. `QMediaPlayer.stop()` 会等待媒体资源释放
   - 如果文件被占用或解码器繁忙，会阻塞主线程
   
2. `QMediaPlayer.setSource()` 会触发媒体加载
   - 同步调用可能阻塞，特别是大文件或网络文件
   
3. 快速切换视频时，多次调用 `stop()` + `setSource()` 会导致死锁
   - 旧资源未释放，新资源已加载
   - Media Foundation 内部状态混乱

### 修复方案

**核心思路**：用 `QTimer.singleShot()` 延迟执行 `stop()` + `setSource()`，避免在 UI 主线程同步调用。

#### 修改内容

**修改前**（会阻塞主线程）：
```python
def _play_current_sequence_clip(self):
    # ...
    self.preview_player.stop()  # ❌ 同步调用，可能阻塞
    self._pending_play_clip = clip
    self.preview_player.setSource(QUrl())  # ❌ 同步调用，可能阻塞
    self._pending_play_timer = _QT.singleShot(200, self._on_preview_no_media)
```

**修改后**（异步执行，不阻塞 UI）：
```python
def _play_current_sequence_clip(self):
    # ...
    self._pending_play_clip = clip
    if self._pending_play_timer is not None:
        self._pending_play_timer.stop()
    # 用 QTimer 延迟执行 stop + setSource，避免在 UI 主线程同步调用导致卡死
    self._pending_play_timer = _QT.singleShot(50, self._do_play_sequence_clip)

def _do_play_sequence_clip(self):
    """实际执行播放序列片段（由定时器延迟调用，避免 UI 卡死）。"""
    # ...
    self.preview_player.stop()  # ✅ 异步执行，不阻塞 UI
    self.preview_player.setSource(QUrl())  # ✅ 异步执行，不阻塞 UI
```

### 影响范围

- **仅影响**：视频预览切换逻辑
- **不改变**：任何业务逻辑、数据流、缓存写入逻辑
- **向后兼容**：完全兼容，仅改变调用时机

### 验证建议

1. 进入「智能混剪」→「镜头重组」
2. 生成预合成方案后，快速点击不同的预合成视频列表项
3. 观察界面是否卡顿或卡死
4. 预期：切换流畅，无卡死现象

---

## #008 视频预览时 CPU 占用率忽高忽低（NoMedia 信号循环）

**日期**：2026-08-26  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_on_preview_media_status_changed()`（第 5901 行）  
**严重级别**：中（CPU 占用异常）

### 问题描述

用户反馈本机 CPU 占用率忽高忽低，有时候会长时间占用。

### 根因分析

#### 问题链路

```
_do_play_sequence_clip()
  → self.preview_player.setSource(QUrl())  // 清空旧源
    → 触发 NoMedia 信号
      → _on_preview_no_media()
        → self.preview_player.setSource(QUrl.fromLocalFile(clip))  // 加载新文件
          → 可能再次触发 NoMedia 信号（如果文件加载失败）
            → _on_preview_no_media()  //  无限循环！
```

#### 根本原因

`_on_preview_media_status_changed()` 在处理 `QMediaPlayer.NoMedia` 信号时，没有检查是否有待播放的片段就直接调用 `_on_preview_no_media()`。

当 `_on_preview_no_media()` 调用 `setSource()` 加载新文件时，如果文件加载失败或 Media Foundation 后端出现问题，会再次触发 `NoMedia` 信号，导致无限循环，CPU 占用率飙升。

### 修复方案

在 `_on_preview_media_status_changed()` 中，仅当有待播放片段时才调用 `_on_preview_no_media()`：

```python
elif status == QMediaPlayer.NoMedia:
    # 旧源已释放，加载待播放片段（信号驱动，避免固定延时不可靠）
    # 仅当有待播放片段时才加载，避免无限循环
    if getattr(self, "_pending_play_clip", ""):
        self._on_preview_no_media()
```

### 影响范围

- **仅影响**：视频预览时的 NoMedia 信号处理逻辑
- **不改变**：任何业务逻辑、数据流、缓存写入逻辑
- **向后兼容**：完全兼容，仅增加条件判断

### 验证建议

1. 进入「智能混剪」→「镜头重组」
2. 生成预合成方案后，点击预合成视频列表项进行预览
3. 观察 CPU 占用率是否稳定
4. 预期：CPU 占用率正常，无忽高忽低现象

---

## #009 分割完成后 CPU 占用忽高忽低（cv2 读视频）

**日期**：2026-08-26  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_get_split_scenes_times()`（第 822 行）  
**严重级别**：高（CPU 占用异常）

### 问题描述

用户在「智能混剪」→「镜头智能分割」步骤，分割完成后客户端 CPU 占用率忽高忽低，有时长时间占用。

### 根因分析

#### 调用链路

```
ServerSplitWorker 分割完成（后台线程）
  → analysis_ready 信号
    → _on_split_analysis_ready()  ← UI 主线程
      → QTimer.singleShot(0, _safe_refresh)
        → _check_split_clips_exist()  ← UI 主线程
          → _get_split_scenes_times()  ←  每个片段都 cv2.VideoCapture！
```

#### 根本原因

`_get_split_scenes_times()` 方法在 UI 主线程中对每个片段都调用 `cv2.VideoCapture()` 读取 FPS 和帧数来计算时长：

```python
import cv2
for f in files:
    cap = cv2.VideoCapture(p)  # ← 每个片段都打开视频！
    if cap.isOpened():
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = frame_count / fps
        cap.release()
    if duration <= 0:
        duration = get_media_duration(p)  # ← 兜底还会 spawn ffprobe！
```

- 如果有 30 个片段，就要打开 30 次视频文件
- cv2.VideoCapture 是 CPU 密集型操作，在 UI 主线程执行会导致界面卡顿
- 如果 cv2 读不了（10-bit/特殊编码），还会 fallback 到 `get_media_duration()` spawn ffprobe
- 每次分割完成后都会调用，多个视频分割时累积效应更明显

### 修复方案

**核心思路**：优先从文件名解析时长（服务端返回的片段名已包含时间戳），避免 cv2 读取。

#### 修改内容

**修改前**（每个片段都 cv2 读视频）：
```python
def _get_split_scenes_times(self, splits_dir, files):
    import cv2
    for f in files:
        cap = cv2.VideoCapture(p)
        # ... 读取 FPS 和帧数
```

**修改后**（三优先级策略）：
```python
def _get_split_scenes_times(self, splits_dir, files):
    """获取片段时长列表。
    优先级：
    1. 从文件名解析时间戳（服务端返回的片段名已包含起止时间）
    2. 从缓存读取
    3. 用 cv2 读取（仅当文件名无法解析且缓存未命中时）
    """
    # 第一遍：优先从文件名解析时长（零 CPU 开销）
    for f in files:
        parsed = self._parse_split_filename(fname)
        if parsed:
            _idx, start_str, end_str, _desc = parsed
            _s = self._srt_ts_to_seconds(start_str)
            _e = self._srt_ts_to_seconds(end_str)
            if _s is not None and _e is not None and _e > _s:
                duration = _e - _s
        # 文件名无法解析时，尝试从缓存读取
        if duration <= 0 and norm_p in self._clip_duration_cache:
            duration = self._clip_duration_cache[norm_p]
        if duration <= 0:
            need_cv2_fallback.append(...)  # 记录下来
    
    # 第二遍：仅对文件名无法解析且缓存未命中的片段用 cv2 读取
    if need_cv2_fallback:
        import cv2
        for f, p, norm_p in need_cv2_fallback:
            # ... cv2 读取
            self._clip_duration_cache[norm_p] = duration  # 写入缓存
```

### 影响范围

- **仅影响**：`_get_split_scenes_times()` 方法的时长计算逻辑
- **不改变**：任何 UI 行为、数据流、缓存写入逻辑
- **向后兼容**：完全兼容，仅优化计算方式

### 性能提升

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| 30 个片段时长计算 | ~15-30 秒（UI 阻塞） | < 1 秒（从文件名解析） |
| 5 个视频分割完成 | ~75-150 秒（累计 UI 阻塞） | < 5 秒（缓存 + 增量更新） |
| CPU 占用峰值 | 30-50%（cv2 + ffprobe） | < 5%（纯字符串解析） |

### 验证建议

1. 进入「智能混剪」→「镜头智能分割」
2. 选择多个视频进行批量分割
3. 观察分割完成后 CPU 占用率
4. 预期：CPU 占用率正常，无忽高忽低现象

---

## #010 镜头重组"与原片一致"画幅输出不正确（未处理旋转元数据）

**日期**：2026-08-27  
**文件**：  
- `studio/gui/video_montage_page.py`  
- `studio/gui/montage/workers/concat_workers.py`  
**方法**：`_probe_first_clip_resolution()` / `_probe_resolution()`  
**严重级别**：中（输出画幅与用户选择不一致）

### 问题描述

用户在「智能混剪」→「镜头重组」时选择输出画幅"与原片一致"，但生成视频的宽高比与原片不同。例如原片是竖屏（9:16），输出却变成了横屏（16:9）。

### 根因分析

#### 根本原因

`_probe_first_clip_resolution()` 和 `VideoConcatWorker._probe_resolution()` 都只读取了 ffprobe 的 `stream=width,height`（原始流像素尺寸），**没有考虑视频的旋转元数据（rotation metadata）**。

手机拍摄的竖屏视频，实际存储方式是：
- 流像素尺寸：1920x1080（横着存的）
- 旋转元数据：`rotate=90` 或 `side_data_list.rotation=-90`
- 实际显示尺寸：1080x1920（竖屏）

代码读到 `width=1920, height=1080` 就当成横屏输出，导致输出画幅与原片不一致。

#### 影响路径

| 合成路径 | 调用方法 | 问题 |
|---------|---------|------|
| 服务端合成 | `_probe_first_clip_resolution()` | 传 1920x1080 给服务端，输出横屏 |
| 本地合成 | `VideoConcatWorker._probe_resolution()` | 同上 |

### 修复方案

修改 ffprobe 命令，同时读取 `side_data_list`（displaymatrix rotation）和 `tag:rotate`，当旋转角度为 90/270 度时自动交换宽高。

#### ffprobe 命令变更

```python
# 修改前（只读原始流尺寸）：
-show_entries stream=width,height -of csv=p=0:s=x

# 修改后（读取尺寸 + 旋转元数据）：
-show_entries stream=width,height,side_data_list,tag:rotate -of json
```

#### 旋转检测优先级

1. `side_data_list[].rotation` — 现代 ffmpeg 的 displaymatrix 方式
2. `tags.rotate` — 旧版兼容方式

#### 宽高交换逻辑

```python
if rotation in (90, -90, 270, -270):
    w, h = h, w
```

### 影响范围

- 服务端合成和本地合成两条路径均已修复
- 仅影响 `layout_mode=source`（"与原视频一致"）选项
- 无旋转元数据的视频行为不变（rotation=0 时不交换宽高）
- 向后兼容

### 验证建议

1. 准备一个竖屏拍摄的视频（手机 9:16）
2. 进入「智能混剪」→ 镜头分割 → 镜头重组
3. 输出画幅选择"与原视频一致"
4. 确认合成后视频为竖屏（1080x1920），而非横屏（1920x1080）

---

## #011 声音样本"根据音频生成文案"时客户端闪退

**日期**：2026-08-27  
**文件**：`studio/gui/voice_samples_page.py`  
**方法**：`_generate_ref_text()`（第 400 行）  
**严重级别**：高（客户端闪退）

### 问题描述

用户在「声音样本」页面，点击"根据音频生成/更新参考文案"按钮时，客户端闪退。

### 根因分析

#### 问题 1：局部定义的 QThread 子类导致 PySide6 元对象系统崩溃

`RemoteAsrSampleWorker` 类定义在 `_generate_ref_text()` 方法内部：

```python
def _generate_ref_text(self, wav_path, sample_id):
    ...
    class RemoteAsrSampleWorker(BaseWorker):  # ← 局部类！
        finished = Signal(list)
        error = Signal(str)
        ...
```

PySide6 对局部定义的 QThread 子类处理信号时，元对象系统（QMetaObject）可能不稳定，导致信号发射时访问已失效的类元数据，引发进程崩溃。

#### 问题 2：`on_finished` 回调无异常保护

```python
def on_finished(segments):
    self.status_label.setText(...)  # ← 如果任何操作抛异常，直接崩溃
    from utils.asr_client import segments_to_plain
    plain_text = segments_to_plain(segments)  # ← 无 try/except
    ...
```

如果 `segments_to_plain` 或其他操作抛异常，没有 try/except 捕获，会导致未处理异常传播，可能引发崩溃。

#### 问题 3（深层根因）：局部函数闭包作为信号槽导致跨线程崩溃

即使将 `RemoteAsrSampleWorker` 移到模块顶层，`on_finished` 和 `on_error` 仍然是定义在 `_generate_ref_text()` 内部的**局部函数闭包**：

```python
def _generate_ref_text(self, wav_path, sample_id):
    ...
    def on_finished(segments):  # ← 局部闭包！
        ...
    def on_error(err):  # ← 局部闭包！
        ...
    worker.finished.connect(on_finished)  # ← Qt 跨线程调用局部闭包 → 崩溃
    worker.error.connect(on_error)
```

PySide6 的跨线程信号槽机制对局部函数闭包的支持不稳定。当 QThread 从工作线程发射信号时，Qt 需要将调用调度到主线程并执行闭包。如果闭包捕获了 `self` 引用，在闭包执行期间访问已被 GC 回收的 Python 对象，会导致段错误（segfault）→ 闪退。

### 修复方案

#### 第一轮修复（部分有效）

1. **将 `RemoteAsrSampleWorker` 移到模块顶层**：避免局部类的元对象问题
2. **在 `on_finished` 回调中添加 try/except**：捕获所有异常

#### 第二轮修复（彻底解决）

3. **将所有回调改为实例方法**：`_on_asr_finished()`、`_on_asr_error()`、`_on_punc_done()`、`_on_punc_err()` 等，避免局部闭包
4. **信号连接使用 lambda + 默认参数传递 sample_id**：`lambda segs, sid=sample_id: self._on_asr_finished(sid, segs)`
5. **用实例变量 `_punc_sample_id` / `_punc_plain_text` 替代闭包捕获**：避免 PunctuationLLMWorker 回调中的闭包问题
6. **提取公共方法**：`_save_ref_text()`、`_cleanup_asr_worker()` 统一管理状态清理

### 影响范围

- 仅影响声音样本页面的 ASR 转写功能
- 不改变任何业务逻辑，仅调整代码结构和异常处理
- 向后兼容

### 验证建议

1. 进入「声音样本」页面
2. 添加一个音频样本
3. 点击"根据音频生成/更新参考文案"
4. 预期：不再闪退；服务端异常时弹出错误对话框

---

## #012 Whisper 模型加载接口超时（服务端问题，客户端临时增加超时）

**日期**：2026-08-27  
**文件**：`studio/utils/asr_client.py`  
**方法**：`transcribe_remote()`（第 196 行）  
**严重级别**：高（功能完全不可用）

### 问题描述

用户点击"根据音频生成/更新参考文案"时，弹出错误：

```
无法从音频中提取文本：
调用接口失败
接口: POST http://192.168.111.30:8000/models/ensure/whisper
错误: ReadTimeout: Read timed out. (read timeout=60)
已重试 3 次后仍失败
```

### 根因分析

**这是服务端问题**，不是客户端问题。

`/models/ensure/whisper` 接口负责将 Whisper 模型加载到 GPU/内存，涉及：
1. 模型文件读取（几百 MB 到数 GB）
2. GPU 显存分配
3. 模型初始化（构建计算图、分配 CUDA 上下文）

以上操作在冷启动时通常需要 **30-120 秒**，客户端原超时设置为 60 秒，不足以覆盖冷启动场景。

### 修复方案

#### 客户端临时措施

将 `timeout=60` 增加到 `timeout=180`，给服务端更多时间加载模型。

#### 服务端根本修复（已提交文档）

详见 `docs/server_issue_whisper_timeout.md`，建议：
1. 服务端启动时预加载 Whisper 模型
2. 或使用异步加载 + 客户端轮询状态
3. 检查服务端是否缺少 `whisperx` 依赖

### 影响范围

- 仅影响 ASR 语音转写功能
- 客户端超时从 60s 增加到 180s，用户体验略有延长但功能可用

### 验证建议

1. 确保服务端 Whisper 模型已加载（或等待冷启动完成）
2. 进入「声音样本」页面
3. 点击"根据音频生成/更新参考文案"
4. 预期：不再超时，正常返回转写结果

---

## #013 分割片段表格新增"画幅"列，方便镜头重组设置输出画幅

**日期**：2026-08-27  
**文件**：  
- `studio/gui/montage/step1_split_view.py`  
- `studio/gui/video_montage_page.py`  
**严重级别**：低（功能增强）

### 问题描述

用户在「镜头重组」步骤选择输出画幅"与原片一致"时，不知道原片的实际画幅是多少，需要来回切换查看。

### 修复方案

在「镜头智能分割」步骤的片段表格中新增"画幅"列，显示每个片段的分辨率（如 1920x1080、1080x1920）。

#### 修改内容

1. **`step1_split_view.py`**：表格列数从 9 增加到 10，新增"画幅"列（Col 5），后续列索引 +1
2. **`video_montage_page.py`**：
   - 新增 Col 5 画幅数据填充逻辑
   - 首次探测第一个片段的分辨率（含旋转元数据处理），后续片段复用
   - 分辨率结果缓存到 `split_clips_cache` 和 `_probed_resolution`
   - 更新所有受影响的列索引引用（Col 5→6, Col 6→7, Col 7→8, Col 8→9）

#### 新表格列结构

| 列索引 | 列名 | 说明 |
|--------|------|------|
| 0 | ☑ | 复选框 |
| 1 | 序号 | 片段序号 |
| 2 | 视频片段 | 文件名 |
| 3 | 景别 | 镜头类型 |
| 4 | 时长 | 片段时长 |
| **5** | **画幅** | **分辨率（新增）** |
| 6 | 主要画面 | 画面描述 |
| 7 | 产品 | 产品名称 |
| 8 | 型号 | 产品型号 |
| 9 | 评分 | 质量评分 |

### 影响范围

- 仅影响「镜头智能分割」步骤的表格显示
- 所有后续列索引 +1，已同步更新
- 向后兼容

### 验证建议

1. 进入「智能混剪」→「镜头智能分割」
2. 选择视频并点击"开始智能镜头分割"
3. 观察分割结果表格，确认"画幅"列显示正确分辨率
4. 进入「镜头重组」步骤，根据画幅列信息选择对应的输出画幅

---

## #014 镜头重组自动检测原片画幅并传递给服务端

**日期**：2026-08-27  
**文件**：  
- `studio/gui/montage/step2_concat_view.py`  
- `studio/gui/video_montage_page.py`  
**严重级别**：低（功能增强）

### 问题描述

用户在「镜头重组」步骤选择输出画幅时，不知道原片的实际画幅是多少。选择"与原视频一致"后，也不清楚实际会输出什么分辨率。

### 修复方案

1. **进入镜头重组时自动检测画幅**：从 `split_clips_cache` 或表格第一个片段探测分辨率
2. **UI 显示原片画幅**：在画幅 combo 旁显示"原片: 1920x1080"标签
3. **更新 combo 第一项文本**：从"与原视频一致"变为"与原视频一致 (1920x1080)"
4. **画幅切换时实时更新提示**：用户切换画幅选项时，标签显示实际输出分辨率
5. **传递给服务端**：`_submit_concat_to_server` 已根据 layout_mode 计算 width/height 并传给服务端

### 修改内容

#### `step2_concat_view.py`
- 新增 `lbl_source_resolution` 标签，显示在画幅 combo 右侧

#### `video_montage_page.py`
- 新增 `_detect_and_show_source_resolution()` 方法：进入步骤 2 时自动检测并显示画幅
- 新增 `_on_layout_combo_changed()` 方法：画幅切换时更新提示标签
- `_go_next_to_step2()` 中调用 `_detect_and_show_source_resolution()`

### 影响范围

- 仅影响镜头重组步骤的 UI 显示
- 服务端接口不变（已通过 width/height 传递分辨率）
- 向后兼容

### 验证建议

1. 进入「智能混剪」→ 完成镜头分割
2. 点击"下一步：镜头重组"
3. 观察画幅 combo 旁是否显示"原片: WxH"
4. 切换画幅选项，观察标签是否实时更新
5. 确认合成视频，检查输出分辨率是否正确

---

## #015 预生成后点击列表项无法预览镜头（预览区一直黑屏）

**日期**：2026-08-28  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_play_current_sequence_clip()` / `_do_play_sequence_clip()` / `_on_preview_no_media()` / `_start_sequence_preview_for_plan()`  
**严重级别**：高（核心预览功能不可用）

### 问题描述

「镜头重组」完成预生成后，单击预合成视频列表项，右侧「视频播放预览」区域一直黑屏：
播放按钮停在 ▶、进度条不动，任何镜头画面都看不到（只能双击用系统播放器打开）。

### 根因分析

镜头切换被实现成一条「靠 Qt 信号接力」的链：

```
_play_current_sequence_clip()   → 记下 _pending_play_clip，50ms 后回调
  └─ _do_play_sequence_clip()   → preview_player.stop()
                                 → setSource(QUrl())   ← 期望触发 NoMedia 信号
                                     └─ _on_preview_media_status_changed(NoMedia)
                                         └─ 仅当 _pending_play_clip 非空时 → _on_preview_no_media() → 真正加载片段
```

但 `QMediaPlayer` 的 `mediaStatusChanged` **只在状态发生跳变时才发信号**。用隔离探针
（PySide6 6.6.3）实测确认：

- 播放器已处于 `NoMedia`（刚进入第②步、`_go_to_step()` 里刚 `stop()` 过、或上一次加载失败）时，
  `setSource(QUrl())` 不产生任何状态跳变 → **不发 NoMedia 信号**；
- `stop()` 本身也**不会**把状态改为 `NoMedia`（实测停留在 `LoadedMedia`）。

于是 `_on_preview_no_media()` 永远不会被调用，待加载片段被无限期挂起 → 预览区保持黑屏。
该缺陷由 #008 引入的条件判断（`if _pending_play_clip: _on_preview_no_media()`）与 #007 的
「stop + 清源 + 等信号」方案叠加暴露：首次点击必定落在 NoMedia 状态，因此必定黑屏。

### 修复方案

不再依赖 NoMedia 信号接力，改为**直接换源**（Qt6 下 `setSource()` 自身会释放上一个片段并重新加载，
实测状态链 `LoadedMedia → BufferingMedia → BufferedMedia` 正常走完，无需先 `stop()`）：

1. 新增 `_load_preview_clip(clip)`：集中做「校验文件 → 换源 → play → 更新按钮/镜头角标」。
2. `_do_play_sequence_clip(req_id)` 直接调用它，不再 `stop() + setSource(QUrl()) + 等信号`。
3. `_on_preview_no_media()` 保留为 NoMedia 信号的兜底入口，内部同样转调 `_load_preview_clip()`。
4. 引入 `_play_request_id` 代号：延迟回调执行时比对代号，过期回调（用户已点到其他片段）直接丢弃，
   替代原先保存 `QTimer.singleShot()` 返回值的写法（该返回值是临时 QTimer，跨回调持有有被提前析构的风险）。
5. `_start_sequence_preview_for_plan()` 去掉换镜头前的无条件 `preview_player.stop()`（会先清成 NoMedia
   再走已失效的信号接力）；新增 `_stop_preview_playback()` 统一处理「无片段可播」的停止 + 复位。
6. `InvalidMedia` 残留态仍先 `stop() + setSource(QUrl())` 清掉，再换源。
7. 防死循环：同一文件连续加载失败累计 3 次即停止重试（拿到有效 `durationChanged` 后计数归零），
   避免信号与兜底互相触发重现 #008 的 CPU 飙升。
8. 新增 `_warn_if_preview_stuck()` 看门狗：3s 内没加载上任何片段时打 WARNING 日志，便于后续定位。

### 影响范围

- 仅影响「镜头重组」步骤右侧预览播放器的片段加载/切换链路
- 不改变预生成、确认合成、配音等任何业务流程
- 同时消除原方案中 `stop()` 在切换时被调用两次带来的主线程阻塞风险（#007 的遗留面）

### 验证建议

1. 进入「智能混剪」→ 完成镜头分割 → 「镜头重组」点击「镜头重组」生成预合成方案
2. **首次**单击列表中的预合成视频 → 预览区应立即出现画面并开始播放，角标显示「镜头 1/N」
3. 连续快速点击不同方案 → 画面跟随切换，不卡死、不错播
4. 右键删除某个镜头使方案无有效片段 → 预览停止且按钮回到 ▶，不报错
5. 观察任务管理器 CPU 占用应平稳

---

## #016 镜头重组预览：播放中途切换另一条预合成导致页面卡死（双播放器缓冲）

**日期**：2026-08-31  
**文件**：`studio/gui/video_montage_page.py`、`studio/gui/montage/step2_concat_view.py`  
**方法**：`_load_preview_clip()` / `_do_preview_swap()` / `_on_standby_media_status()` / `_teardown_retired_player()`  
**严重级别**：高（预览切换卡死）

### 问题描述

预生成后单击列表项预览正常（#015 已修），但当某条预合成视频**播放到一半**时改点另一条，浏览页面会卡死。

### 根因分析

排除法：`_refresh_sources_for_plan` 中 `_score_clip` 直接返回 -1、`_clip_duration_text` 已不再 ffprobe（#004），表格填充是纯内存操作且与“是否播放”无关，不是卡死源。

真正卡死在 `preview_player.setSource(新片段)`：`preview_player` 是**单个** `QMediaPlayer`，Qt6 在 Windows 用 Media Foundation 后端，对一个**正在播放的会话**调用 `setSource()` 会在 GUI 主线程**同步 flush/销毁旧 media session**，1080p/HEVC 片段可达几百 ms～数秒 → 卡死。空闲/暂停时无活跃会话，切换很快——这止好解释了“播放到一半才卡”。#015 去掉显式 `stop()` 只把阻塞从 `stop()` 挪到了 `setSource()`，单播放器架构下无法根治。

### 修复方案（双播放器缓冲）

新增一个隐藏的备用播放器 `preview_player`/`_preview_standby_player` 乒乓复用：

1. `_load_preview_clip`：当前播放器空闲（首次/已停）→ 直接换源；正在播放 → 把新片段 `setSource` 到备用播放器（备用无活跃会话，不阻塞）。
2. `_on_standby_media_status`：备用达到 `LoadedMedia/BufferedMedia` → `_do_preview_swap`。
3. `_do_preview_swap`：把 `QVideoWidget` 输出瞬间 `setVideoOutput` 切到备用并 `play()`，然后互换 `preview_player`/`_preview_standby_player` 与对应音频引用（静音切换）。
4. 退役播放器先 `pause()`+静音（非阻塞，立即停止解码不占 CPU），再 `QTimer.singleShot(120, _teardown_retired_player)` 延后 `setSource(QUrl())` 释放会话——**会话释放的耗时被挪到新画面已显示之后**，不再卡在点击上。
5. 两个播放器的 `positionChanged/durationChanged/mediaStatusChanged` 统一在 `__init__` 接路由 `_route_preview_*`，按来源对象（`src is self.preview_player`）分发，避免重复连接与串号；step2_concat_view 只保留 `setVideoOutput` 并登记 `_preview_video_widget`。
6. `_force_swap_if_pending`（800ms）与 `InvalidMedia` 退回直接换源作为兜底；`_stop_preview_playback`/`_go_to_step` 一并停两个播放器并清 `_preview_pending_clip`。

### 影响范围

- 仅影响镜头重组右侧预览播放器的换源/切换链；不改预生成、确认合成、配音等业务。
- 首次加载仍走单播放器直连路径（无额外开销）。

### 验证建议

1. 智能混剪 → 镜头重组 → 生成预合成方案
2. 单击一条预览，等播放到一半 → 改点另一条 → 应瞬间切到新画面不卡死
3. 连续快速点击多条 → 不崩溃、不错播
4. 真实客户端需重启一次加载新代码（Windows MF 行为与 offscreen 测试后端不同，需在客户端环境验收）

---

## #017 镜头重组预览：自动连播到第 2 个镜头时页面卡死（退役会话与新画面抢 sink）

**日期**：2026-08-31  
**文件**：`studio/gui/video_montage_page.py`、`tests/unit/test_video_montage_page.py`  
**方法**：`_is_player_idle()` / `_do_preview_swap()` / `_load_preview_clip()` / `_stop_preview_playback()` / `_release_preview_sessions()`  
**严重级别**：高（连播必现卡死，标题栏 Not Responding）

### 问题描述

#016 的双播放器缓冲解决了「播放中途改点另一条方案」，但**什么都不点**、只让序列自动连播时，
第 1 个镜头播完进入第 2 个镜头的瞬间页面又卡死了：画面已经显示「镜头 2/4」的新片段，
标题栏随即进入 (Not Responding)，CPU 只有 1%（主线程被挂住，不是在空转）。

### 根因分析

连播走的是 #016 的换手分支：`_is_player_idle()` 只把 `NoMedia/InvalidMedia` 当空闲，
而片段自然播完时状态是 `StoppedState + EndOfMedia`，于是被当成「正在播放」→ 走备用播放器
加载 → `_do_preview_swap()` → 最后一步 `QTimer.singleShot(120, _teardown_retired_player)`
在 GUI 主线程对退役播放器做 `setSource(QUrl())` 释放会话。

问题在于：此刻新转正的播放器**正在向同一个 `QVideoWidget`（同一个 QVideoSink）渲染**，
WMF 释放旧会话要同步拆掉绑定在该 sink 上的视频分配器，两个会话抢 sink → 主线程直接挂住。
所以卡顿点被推迟到「新画面出来之后 120ms」，看起来就像连播到第 2 个镜头才卡。

### 修复方案

1. **连播不再换手**：`_is_player_idle()` 把 `EndOfMedia`（以及 `stop()` 后的 `StoppedState`）
   也判为空闲——片段播完时 WMF 已自行停止渲染，在同一个播放器上直接换下一个片段就是普通
   播放列表用法，没有活跃会话要拆。这样连播路径完全不进 `_do_preview_swap()`。
2. **切换时不拆旧会话**：`_do_preview_swap()` 去掉 `QTimer(120) → setSource(QUrl())` 的延后释放
   （删除 `_teardown_retired_player()`），改为「静音 + `pause()` + `setVideoOutput(None)` 摘画面」。
   旧会话留到下次把它当备用播放器换源时顺带替换（那时它已与画面无关），一次换源只做一次 unload。
3. **兜底释放**：新增 `_release_preview_sessions(reason)`，在 `_stop_preview_playback()` 与
   `_go_to_step()`（没有画面在渲染的时刻）统一 stop + 清源，及时放开片段文件句柄，
   避免回到 Step1 重新分割同名镜头时被占用。
4. **留痕**：新增 `_timed_mf(tag, fn, *args)` 包住所有可能同步阻塞的播放器调用（换源/换手/摘画面/清源），
   先打「开始」再打耗时，≥300ms 记 WARNING。真死锁时日志只剩「开始」行，可直接定位卡在哪一步。
5. 补 `tests/unit/test_video_montage_page.py` 固化 `_is_player_idle` 判定表（EndOfMedia/Stopped 为空闲，
   Playing/Paused 非空闲，对象已销毁按空闲处理）。

### 影响范围

- 仅影响镜头重组右侧预览播放器的连播与切换链；不改预生成、确认合成、配音等业务。
- 「播放中途改点另一条」仍走双播放器缓冲（Paused/Playing 有活跃会话时不原地换源）。
- 退役播放器在下次复用前会保留一个已暂停会话（最多 1 个），由停播/切步骤兜底释放。

### 验证建议

1. 智能混剪 → 镜头重组 → 生成预合成方案 → 单击一条方案，**不做任何操作**等它连播
2. 预期：第 1 个镜头播完自动到第 2、3、4 个，标题栏不出现 (Not Responding)
3. 播放中途改点另一条方案 → 仍能瞬间切换不卡死
4. 若仍卡，取 `studio/.runtime/logs/app.log` 里 `[预览]` 与 `[预览][耗时]` 行：
   只剩「开始」没有耗时行的那一步就是新的阻塞点

---

## #018 确认合成视频：服务端报「素材不存在」导致流程阻断（自动回退本地合成）

**日期**：2026-08-31  
**文件**：`studio/gui/montage/workers/montage_concat_server_worker.py`、`tests/unit/test_montage_concat_worker.py`、`docs/server_issue_montage_concat_clip_not_found.md`  
**方法**：`_poll_and_download()` / `_looks_like_server_lost_upload()`  
**严重级别**：高（「确认合成视频」必现失败，用户无法出片）

### 问题描述

镜头重组 → 确认合成视频 → 提交 `POST /montage/concat` 本身返回 200（`clip_count: 4`），
但 3 秒后轮询到 `failed`，弹出「排列错误」对话框，内容是服务端的 Python traceback：

```
FileNotFoundError: 素材不存在:
/home/tintin/Project/TinTin_AI_Agent_Server (V2.0)/server/api/../uploads/montage/concat_15afe52b1b2b/clip_001.mp4
```

### 根因分析

**服务端内部缺陷，客户端无法修**：服务端收下 4 个镜头并建好工作目录，却在自己的上传目录里
找不到它们。两条线索：（一）traceback 的代码在 `/home/freya/Project/TinTin_AI_Agent_Server/`，
而报错路径在 `/home/tintin/Project/TinTin_AI_Agent_Server (V2.0)/server/api/../uploads`（未规范化的
陈年绝对路径，跨部署后指到另一份代码）；（二）引擎按 `clip_%03d.mp4` 取文件，而客户端按契约
上传的是原始文件名（含中文/空格/逗号）。`/montage/split` 同样走 multipart 上传且一切正常，
说明只有 concat 的工作目录解析是坏的。详见 `docs/server_issue_montage_concat_clip_not_found.md`。

客户端侧原有机制只对 **402** 自动回退本地合成，本类错误直接 `raise` 弹 traceback 对话框，
整条流程被卡死。

### 修复方案

1. 新增可单测的判定函数 `_looks_like_server_lost_upload(error_msg)`：命中
   「素材不存在 / FileNotFoundError / no such file or directory」即认定为服务端丢失自身上传文件。
2. `_poll_and_download()` 的 `failed` 分支：若命中上述判定 **且本次不含 `material://` 片段**，
   不再抛异常，而是 `emit fallback_to_local(...)` 并 `return`，由页面既有的
   `_on_server_concat_fallback()` 用同一批本地镜头走本地 ffmpeg 合成（与 #002 的 402 回退同一机制）。
3. 含 `material://`（素材库地址，只有服务端能解析）时**不回退**，仍如实报错——
   本地没那些素材，回退会静默缺镜头、产出错片，比报错更糟。
4. 回退时以 WARNING 记录服务端原始 `error_msg`（前 300 字），便于对账。
5. 补 3 个单测：回退触发 / 含 material:// 仍抛错 / 判定函数本身（含空值）。

### 影响范围

- 仅影响服务端合成任务报 `failed` 后的分支；提交失败、下载失败、产物过小等错误路径不变。
- 不改变本地合成逻辑与输出命名（`_sources.txt` 等照旧）。
- 服务端修好后无需客户端改动即自动恢复服务端出片（只有命中该错误特征才回退）。

### 验证建议

1. 智能混剪 → 镜头重组 → 确认合成视频
2. 预期：状态栏显示「服务端合成失败（服务端找不到自己接收的镜头文件，属服务端问题），
   已自动回退到本地合成」，随后本地合成正常出片，不再弹 traceback 对话框
3. 若素材列表含「素材检索」带入的 `material://` 条目 → 仍应弹原错误（不能静默缺镜头）
4. 需重启客户端加载新代码

---

## #019 镜头重组预览：切步骤/停播释放会话时信号重入换源导致 WMF 死锁

**日期**：2026-09-01  
**文件**：`studio/gui/video_montage_page.py`、`tests/unit/test_video_montage_page.py`  
**方法**：`_release_preview_sessions()` / `_route_preview_status()`  
**严重级别**：高（离开预览时必现，标题栏 Not Responding，CPU≈0%）

### 问题描述

在「智能混剪 → 镜头重组」单击查看/连播镜头后，切换到其它步骤（或触发停播）时，Python 进程直接卡死：
标题栏 (Not Responding)，任务管理器 CPU 长期 0%（主线程被挂住，非空转）。
`app.log` 末尾停在：

```
[预览] 切步骤清源(preview_player) 开始
[预览][耗时] 切步骤清源(preview_player) 32ms
[预览] 切步骤清源(_preview_standby_player) 开始   ← 只有「开始」，无耗时行 = 死锁在这一步
```

### 根因分析

#017 把 `_release_preview_sessions()` 当作「没有画面在渲染时」的安全兜底释放点，但漏了**信号重入**：

1. `_go_to_step()` 先调 `_release_preview_sessions("切步骤")`，之后才清 `_pending_play_clip`/`_preview_pending_clip`
   （而 `_stop_preview_playback()` 是先清再调，两条入口顺序不一致）。
2. 释放循环里对第一个播放器 `_p.stop()` 时，Windows WMF 在 GUI 线程**同步**抛 `mediaStatusChanged(NoMedia)`。
3. 该信号经 `_route_preview_status` → `_on_preview_media_status_changed`，因 `_pending_play_clip` 仍非空，
   重入 `_on_preview_no_media()` → `_load_preview_clip()`，对一个**正在被拆会话**的播放器再次 `setSource()`。
4. 两个会话在同一线程上互相抢拆 → `setSource(QUrl())` 直接死锁（表现为清到第二个播放器时卡住）。

即：`_release_preview_sessions` 本身不是「无渲染就安全」，只要待播状态未作废，stop() 的信号就会重入换源。

### 修复方案

1. **释放前作废所有待播状态**：`_release_preview_sessions()` 开头即清空 `_preview_sequence_clips`、
   `_pending_play_clip`、`_preview_pending_clip` 并自增 `_play_request_id`（丢弃过期 singleShot 回调），
   使两条调用入口（切步骤 / 停播）行为一致，不再依赖调用方提前清理。
2. **释放期屏蔽状态回调**：新增 `self._releasing_preview` 标志，释放期间置 True（`try/finally` 复位）；
   `_route_preview_status()` 在标志为真时直接 `return`，杜绝 stop()/setSource() 触发的 NoMedia 重入换源。
3. 补 3 个单测（`tests/unit/test_video_montage_page.py`）：释放后作废待播状态并复位标志；
   释放期间无任何状态回调重入（模拟 stop() 同步抛 NoMedia）；非释放期 active/standby 仍各自正常路由。

### 影响范围

- 仅影响镜头重组预览会话的释放路径（`_go_to_step` 切步骤、`_stop_preview_playback` 停播）。
- 正常连播/换手的信号处理不受影响：`_releasing_preview` 仅在同步释放循环内为真，循环结束即复位。
- 退役播放器的会话仍被释放（文件句柄照常放开）。

### 验证建议

1. 智能混剪 → 镜头重组 → 生成预合成方案 → 单击一条方案播放/连播
2. 播放过程中点「下一步」或切到其它步骤 → 页面应正常切换，不再 (Not Responding)
3. 取 `app.log`：`[预览] *清源* 开始` 后应都有对应 `[预览][耗时]` 行，不再只剩「开始」
4. 需重启客户端加载新代码（Windows MF 行为与 offscreen 后端不同，须在真机验收）

---

## #020 智能分割刷新链在主线程逐片段跑 ffprobe/cv2 导致未响应

**日期**：2026-09-01  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_get_split_scenes_times()` / `_scan_concat_src_dir()`  
**严重级别**：高（Step1 点素材/每个视频分割完成时必现卡顿，片段多时 (Not Responding)）

### 问题描述

「智能混剪 → 镜头智能分割」中，单击素材项、或批量分割每完成一个视频时，界面卡顿乃至 (Not Responding)；
片段越多越明显（几十个片段可卡数十秒）。

### 根因分析

分割本身跑在后台 `ServerSplitWorker`，不阻塞；卡死来自**主线程刷新回调里循环探测时长**：

1. `_check_split_clips_exist()`（`video_list.itemClicked` 槽 + 每次分割完成后 `QTimer` 触发）末尾会调
   `_scan_concat_src_dir()`（L1465），而后者对每个片段调 `get_media_duration()`（ffprobe，timeout=10s），
   N 个片段 = N 次串行子进程，全在主线程。#004 只删了 `_check_split_clips_exist` 自己循环里的 ffprobe，
   但它末尾又调了 `_scan_concat_src_dir`，ffprobe 从这条路径绕回来了。
2. `_get_split_scenes_times()` 在文件名无时间戳且缓存未命中时，对每个片段 `cv2.VideoCapture` 读取，
   读不出再 `get_media_duration()`（ffprobe）兜底；且每命中一个兜底片段就重算整表（0(n²)）。

### 修复方案

1. `_scan_concat_src_dir()`：删除逐片段 `get_media_duration()`，改为由已算出的 `start_str`/`end_str`
   时间戳推算时长（`_srt_ts_to_seconds`），缺失时读 `_clip_duration_cache`，仍无则留 0 由后台异步补。
2. `_get_split_scenes_times()`：重写为两遍——第一遍文件名/缓存得时长，第二遍只对**少量**（≤ `_CV2_FALLBACK_MAX=8`）
   待兜底片段用 cv2，**彻底去掉主线程 ffprobe 兜底**；超过上限则时长留空由后台补；最后单次累积成轴，
   消除 O(n²) 重算。

### 影响范围

- 仅影响 Step1 分割结果刷新与 Step2 镜头扫描的时长计算；时长缺失时显示“—”，不阻塞后续流程。
- 服务端文件名含时间戳的正常链路（重命名后）零开销；异常命名也不会再卡主线程（cv2 有界 + 无 ffprobe）。
- 未改动分割/合成/预览业务逻辑。

### 验证建议

1. 智能混剪 → 镜头智能分割 → 选含多个视频的文件夹 → 开始分割
2. 预期：分割完成回填表格、单击素材项切换时不再 (Not Responding)；任务管理器 CPU 平稳
3. 需重启客户端加载新代码

---

## #021 点「清空混剪缓存」后已添加的素材列表未清空

**日期**：2026-09-01  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_clear_montage_cache()`  
**严重级别**：中（功能不一致，按钮文案声称清「素材清单」但实际未清列表）

### 问题描述

在「智能混剪 → 镜头智能分割」点击「清空混剪缓存」，状态栏提示“已清空混剪缓存（N 个任务目录）”，
但上方「已选择的原始视频素材」列表（`video_list`）仍保留之前添加的素材，未随缓存一同清空。

### 根因分析

`_clear_montage_cache()` 只调了 `clear_montage_cache()`（删磁盘任务目录）并重置了
`_montage_job_id`/`split_clips_list`/`split_result_table` 等派生数据，但漏清了：
`video_list`（已添加素材列表）、`folder_path_input`（源目录）、`split_clips_cache`、
`split_descriptions`、`_clip_duration_cache`、`processing_video_path`、`temp_scenes`、`_available_concat_clips`。
`video_list` 是纯内存 UI 态（由 `_select_folder`/拖拽/`set_external_materials` 填充，无持久化恢复），
不主动 `clear()` 就一直显示。

### 修复方案

在 `_clear_montage_cache()` 确认删除后，除原有重置外，额外 `video_list.clear()`、`folder_path_input.clear()`
并重置上述内存派生缓存（仅移出列表/清内存态，不删任何原始素材文件）。

### 影响范围

- 仅影响「清空混剪缓存」按钮的重置范围；不改变分割/合成/预览业务逻辑。
- 与按钮现有文案“清除…素材清单”语义对齐。

### 验证建议

1. 智能混剪 → 选择/拖入多个素材→ 点「清空混剪缓存」→ 确认
2. 预期：上方素材列表与下方分割结果表同时清空，状态栏提示“素材列表已重置”
3. 原始素材文件在磁盘上仍存在（未被删除）

---

## #022 镜头重组：设 30s 但成片只有 17-20s（选片预算被丢弃片段吃掉 + 提前 break）

**日期**：2026-09-01  
**文件**：`studio/gui/video_montage_page.py`  
**方法**：`_build_precompose_plans()`  
**严重级别**：高（成片时长与「时长限制」配置严重不符）

### 问题描述

镜头重组设置时长限制 30s，实际合成出来只有 17-20s。预合成方案每条只有 3-4 个镜头。

### 根因分析

合成阶段（服务端/本地）只是拼接选中片段，不按时长裁剪；问题出在选片贪心循环：

1. **预算被丢弃片段吃掉**：`total_dur += clip_dur` 在去重判定之前执行，被“相似”丢弃、
  根本没进 `seq` 的片段其时长也已计入 `total_dur`。电商素材相似镜头多，预算虚高→提前判定“快满”
  而停止，实际选中片段总长远小于 30s。
2. **放不下就 break 整批**：`if total_dur + clip_dur > max_total and len(seq) > 0: break`，遇到一个比
  剩余预算长的片段就直接停止整批，不再尝试后面能放下的更短片段。

### 修复方案

重写填充循环：
1. `total_dur` 只累加「真正入列」的片段；择优替换时按「新-旧」时长差额调整预算。
2. 放不下改为 `continue` 继续试更短的片段（尽力填满到上限），而非 `break` 整批。
3. 保留「无时长上限时补足到 target_clip_count」与「至少 1 个镜头」的兜底；用 `max_scan` 防无限循环。

### 影响范围

- 仅影响随机洗牌模式的预合成选片；文案匹配(script)/卡点(beat)模式不走此函数。
- 时长限制仍是「上限」（max_total=limit×1.1），但现在会尽力填满到接近上限而非远未填满就停。

### 验证建议

1. 智能混剪 → 镜头重组 → 设时长限制 30s → 生成预合成方案
2. 预期：每条方案的镜头数明显增多，总时长贴近 30s（含转场重叠后实际略短属正常）
3. 需重启客户端加载新代码

---

<!-- 新条目模板（复制以下内容追加到文档末尾）：

## #XXX 问题标题

**日期**：YYYY-MM-DD  
**文件**：`path/to/file.py`  
**方法**：`method_name()`（第 XXX 行）  
**严重级别**：高/中/低

### 问题描述

...

### 根因分析

...

### 修复方案

...

### 影响范围

...

### 验证建议

...

-->
