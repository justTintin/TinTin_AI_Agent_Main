# 智能混剪镜头合成服务端化方案

> 目标：把“智能混剪”第 2 步的镜头合成（xfade/concat 阶段）从客户端迁移到服务端，彻底规避客户端 GPU 驱动/并发/10-bit 转码等问题。  
> 适用：服务端对接人员按本方案实现执行器；客户端按本方案改造 `video_montage_page.py` + `concat_workers.py`。

---

## 1. 背景与问题

- 7/20 引入 `hwaccel.py` 后，客户端合成会按机器自动选择 `h264_nvenc/h264_amf/h264_qsv`。
- 客户端 `ThreadPoolExecutor` 并发转码多个镜头，GPU 编码器并发会话/驱动交互下出现 **0% 占用假死**。
- 10-bit 素材需要客户端先 `format=yuv420p` 降级为 8-bit，再交给 GPU 编码器，仍可能触发假死。
- 不同客户端机器编码能力差异大，无法保证稳定。

**结论**：合成逻辑上移到服务端，客户端只做编排 + 上传/引用 + 轮询结果。

---

## 2. 整体架构

```
客户端（video_montage_page）
    │
    ├─ 镜头分割（已服务端化：POST /montage/split）
    ├─ 镜头评分/分析（已服务端化：POST /material/score_clip）
    │
    ▼
[ 第 2 步：镜头合成 ]  ← 本次要迁移
    │
    ├─ 方式 A：共享存储路径 → 直接提交路径列表
    ├─ 方式 B：无共享存储 → 先 POST /material/stage 上传，再提交 staged 路径
    │
    ▼
POST /scheduled/tasks  (task_type = montage_concat)
    │
    ▼
服务端执行器
    ├─ 读取/下载 clips
    ├─ 标准化转码（服务端固定 libx264 或可控 GPU）
    ├─ xfade / concat 拼接
    ├─ 输出成片到服务端 outputs
    │
    ▼
客户端轮询 GET /scheduled/tasks/{task_id}
    │
    ▼
结果下载到本地 outputs/montage
```

---

## 3. 服务端接口设计

### 3.1 文件暂存（可选）

如果客户端镜头文件对服务端不可见，先调用：

```http
POST /material/stage
Content-Type: multipart/form-data

files: <clip_001.mp4>
files: <clip_002.mp4>
files: <clip_003.mp4>
```

**响应**：

```json
{
  "paths": [
    "/staged/montage/clip_001.mp4",
    "/staged/montage/clip_002.mp4",
    "/staged/montage/clip_003.mp4"
  ]
}
```

> 如果客户端与服务端已共享存储（如 NAS / 同一路径挂载），可跳过此步骤，直接提交原始路径。

---

### 3.2 提交合成任务

复用现有定时任务接口：

```http
POST /scheduled/tasks
Content-Type: application/json
```

**请求体**：

```json
{
  "task_type": "montage_concat",
  "title": "智能混剪合成 - 产品A - 预合成 #1",
  "params": {
    "clips": [
      "/staged/montage/clip_001.mp4",
      "/staged/montage/clip_002.mp4",
      "/staged/montage/clip_003.mp4"
    ],
    "options": {
      "transition": "fade",
      "transition_duration": 0.5,
      "layout_mode": "vertical",
      "width": 1080,
      "height": 1920,
      "fps": 30,
      "crf": 23,
      "preset": "superfast",
      "lut_path": "",
      "audio_fade": true
    },
    "output": {
      "output_dir": "/outputs/montage",
      "filename": "montage_concat_001.mp4"
    }
  },
  "schedule": null
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `clips` | list[str] | ✅ | 已排序的镜头文件路径，按此顺序合成 |
| `options.transition` | string | ❌ | 转场类型：`fade`/`dissolve`/`slideleft`/`slideright`/`slideup`/`slidedown`/`zoomin`/`zoomout`/`none` |
| `options.transition_duration` | float | ❌ | 转场时长，默认 0.5 |
| `options.layout_mode` | string | ❌ | `vertical`/`horizontal`/`source` |
| `options.width`/`height` | int | ❌ | `layout_mode=source` 时服务端按第一个 clip 探测；否则用此处 |
| `options.fps` | int | ❌ | 默认 30 |
| `options.crf` | int | ❌ | 默认 23 |
| `options.preset` | string | ❌ | 默认 `superfast` |
| `options.lut_path` | string | ❌ | 服务端可访问的 LUT 文件路径 |
| `options.audio_fade` | bool | ❌ | 是否做音频淡入淡出 |
| `output.output_dir` | string | ✅ | 服务端输出目录 |
| `output.filename` | string | ✅ | 输出文件名 |

**响应**：

```json
{
  "id": "uuid-xxx-xxx",
  "status": "pending"
}
```

---

### 3.3 轮询任务状态

复用统一接口：

```http
GET /scheduled/tasks/{task_id}
```

**响应示例**：

```json
{
  "id": "uuid-xxx-xxx",
  "task_type": "montage_concat",
  "status": "running",
  "progress": 45,
  "error_msg": "",
  "result": null
}
```

**完成时**：

```json
{
  "id": "uuid-xxx-xxx",
  "task_type": "montage_concat",
  "status": "completed",
  "progress": 100,
  "error_msg": "",
  "result": {
    "output_path": "/outputs/montage/montage_concat_001.mp4",
    "output_url": "/material/serve?path=/outputs/montage/montage_concat_001.mp4",
    "duration": 25.5,
    "sources": [
      "/staged/montage/clip_001.mp4",
      "/staged/montage/clip_002.mp4",
      "/staged/montage/clip_003.mp4"
    ]
  }
}
```

**失败时**：

```json
{
  "status": "failed",
  "error_msg": "镜头 /staged/montage/clip_002.mp4 读取失败",
  "result": null
}
```

---

## 4. 服务端执行器职责

新增执行器 `montage_concat`，建议逻辑：

1. **读取 clips**  
   - 如果路径不可读，返回失败。
   - 如果是 staged 文件，确保生命周期足够（至少保留到任务完成 + 客户端下载）。

2. **标准化转码**  
   - 每个 clip 统一分辨率、fps、pix_fmt。
   - **默认强制软编 `libx264`**，避免 GPU 假死。如果后续需要 GPU 加速，再做成可配置开关。
   - 10-bit 素材在 filter 中 `format=yuv420p` 转换。

3. **xfade / concat**  
   - 按 `options.transition` 和 `clips` 顺序拼接。
   - 镜头数 > 12 时建议分块 xfade（参考客户端已实现的 `_run_xfade_chunked`）。
   - transition=`none` 时走 `-c copy` 或简单 concat。

4. **输出**  
   - 写入 `output.output_dir/output.filename`。
   - 返回 `output_path` 和 `output_url`。

5. **进度上报**  
   - 任务 `progress` 字段建议：
     - 0-40：标准化转码
     - 40-80：xfade/concat 拼接
     - 80-100：输出与收尾

---

## 5. 客户端改造

### 5.1 新增 Worker

新建 `studio/gui/montage/workers/montage_concat_server_worker.py`：

```python
class MontageConcatServerWorker(BaseWorker):
    stage = Signal(str)
    progress = Signal(int)
    finished = Signal(str)  # 本地输出路径

    def __init__(self, task_id, local_output_path):
        ...

    def do_work(self):
        # 轮询 GET /scheduled/tasks/{task_id}
        # 每 2-3 秒轮询一次
        # progress 透传服务端 progress
        # 完成后下载 result.output_url 到 local_output_path
        # 本地保存同名的 _sources.txt
```

### 5.2 改造 `video_montage_page.py`

在 `_launch_concat_worker` 中增加分支：

```python
USE_SERVER_CONCAT = True  # 后续可放配置项

if USE_SERVER_CONCAT:
    self._submit_concat_to_server(clips, out_montage_dir, ...)
else:
    # 保留本地 VideoConcatWorker 作为离线 fallback
    self._launch_local_concat_worker(...)
```

服务端提交流程：

1. 收集 clips（已经是本地分割文件路径）。
2. 如果服务端不能直接访问这些路径，先 `POST /material/stage` 上传。
3. 调用 `scheduled_task_client.create_task("montage_concat", title, params)` 获取 `task_id`。
4. 启动 `MontageConcatServerWorker` 轮询并下载结果。
5. 下载完成后写入本地 `out_montage_dir`，触发 `_on_concat_finished` 后续流程。

### 5.3 保留本地 fallback

- 服务端不可用时（无连接、执行器未部署），自动回退到本地 `VideoConcatWorker`。
- 本地版本保持强制软编 + 超时，作为兜底。

---

## 6. 文件路径处理策略

| 场景 | 处理方式 |
|------|----------|
| 客户端与服务端共享 NAS/挂载 | 直接提交原始绝对路径，服务端读取 |
| 客户端本地路径，服务端无法访问 | 先 `POST /material/stage` 上传，再提交 staged 路径 |
| 服务端执行完后 | 客户端通过 `result.output_url` 下载到本地 |

建议服务端实现时同时支持：
- 绝对路径读取（共享存储模式）
- staged 路径读取（上传模式）

---

## 7. 迁移步骤

1. **服务端** 实现 `montage_concat` 执行器 + 文件读取/下载路径。
2. **客户端** 新增 `MontageConcatServerWorker`。
3. **客户端** 在 `video_montage_page.py` 添加服务端分支开关。
4. 联调：
   - 10 镜头常规转场
   - 无转场模式
   - LUT 模式
   - 卡点模式（复用 `beat_times`/`music_path` 参数）
5. 稳定后，把 `USE_SERVER_CONCAT` 默认设为 `True`，本地版作为 fallback 保留。

---

## 8. 待确认问题

1. 客户端 `outputs/montage/splits` 是否与服务端共享存储？还是必须走 `/material/stage` 上传？
2. 服务端是否已有文件下载接口（如 `/material/serve`）可直接复用？
3. 服务端合成输出目录是否和客户端期望的 `out_montage_dir` 一致？是否需要路径映射？
4. 是否希望一次任务提交多个预合成计划（batch），还是逐个提交？（本方案按逐个提交设计，更简单）

---

## 9. 临时止血（当前已提交）

在服务端化完成前，客户端已做：
- `_transcode_one` 强制 `libx264` 软编 + 单镜头超时。
- xfade 分块 + 超时 + 无转场兜底。

可先用此版本缓解卡死，再按计划迁移到服务端。
