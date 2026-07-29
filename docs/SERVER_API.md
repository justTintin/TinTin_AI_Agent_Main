# 服务端接口文档（客户端对接用）

> 服务端地址：`http://192.168.111.28:8000`（2026-07-29 实测，原 .19 已迁移）
> OpenAPI 规范：`http://192.168.111.28:8000/openapi.json`
> 框架：FastAPI (Python)，实测共 153 个路径
> 最后同步：2026-07-29

⚠️ **重要原则**：客户端不得自行定义接口路径和协议，必须严格对照本文档（即服务端 OpenAPI 实际暴露的端点）。

---

## 一、智能混剪相关接口

### 1.1 镜头分割 `POST /montage/split`

上传视频，检测镜头分割，返回每个镜头的起止时间及分割后的片段文件。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | ✅ | — | 视频文件（multipart/form-data） |
| threshold | number | ❌ | 27 | 场景检测敏感度 (1-100, 越小越敏感) |
| min_scene_len | number | ❌ | 0.5 | 最小镜头长度（秒） |

**请求示例**：
```
POST /montage/split
Content-Type: multipart/form-data

file: <video.mp4>
threshold: 27
min_scene_len: 0.5
```

---

### 1.2 镜头评分/分析 `POST /material/score_clip`

客户端上传视频镜头 → 入成片任务队列 → 抽帧打分。
返回成片任务 ID，客户端轮询 `GET /scheduled/tasks/{task_id}` 查看结果。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | ✅ | — | 视频镜头片段（multipart/form-data） |
| product_mode | boolean | ❌ | false | 产品模式（产品/普通） |
| analyze_shot | boolean | ❌ | false | 是否做镜头画面分析 |
| frame_at | number | ❌ | 0.5 | 抽帧时间点（秒） |

**请求示例**：
```
POST /material/score_clip
Content-Type: multipart/form-data

file: <clip_001.mp4>
product_mode: false
analyze_shot: true
frame_at: 0.5
```

**响应**（提交成功）：
```json
{
  "task_id": "xxxx-xxxx-xxxx",
  "status": "pending"
}
```

**轮询结果**：`GET /tasks/unified/{task_id}`（统一接口，见下方「任务队列」章节）

**任务完成后的 result 字段**：
```json
{
  "filename": "镜头片段.mp4",
  "aesthetic_score": {
    "total": 7.1,
    "engine": "laion+opencv",
    "clarity": 7.7,
    "texture": 4.5,
    "aesthetics": 5.0,
    "composition": 7.5,
    "color_quality": 10.0,
    "figure_quality": 5.0,
    "subject_prominence": 10.0
  }
}
```

> ℹ️ 评分在 `result.aesthetic_score.total`，不是 `result.score`。各维度分数在 `aesthetic_score` 子字段中。

---

### 1.3 音乐卡点 `POST /audio/beatmap`

上传音乐文件，入后台任务队列，返回任务 ID，客户端轮询 `GET /tasks/{id}` 取结果。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | ✅ | — | 音频文件（mp3/wav/m4a 等，multipart/form-data） |
| count | int | ❌ | 0 | 要返回的卡点片段个数（>0 时服务端从音乐中挑选 N 个片段，每段生成一个视频） |
| segment_duration | float | ❌ | 0.0 | 每个片段的时长（秒），与 count 配合使用 |

**请求示例**：
```
POST /audio/beatmap
Content-Type: multipart/form-data

file: <music.mp3>
count: 3
segment_duration: 30
```

**响应**（提交成功）：
```json
{
  "task_id": "xxxx-xxxx-xxxx",
  "status": "pending"
}
```

**轮询结果**：`GET /tasks/unified/{task_id}`（统一接口，见下方「任务队列」章节）

**任务完成后的 result 字段**：
```json
{
  "beats": [0.52, 1.04, 1.56, 2.08, ...],
  "bpm": 120.0,
  "duration": 180.5,
  "clips": [
    {"start": 0.0,  "end": 30.0, "strength": 0.85},
    {"start": 30.0, "end": 60.0, "strength": 0.78},
    {"start": 60.0, "end": 90.0, "strength": 0.72}
  ],
  "clip_count": 3,
  "segment_duration": 30.0
}
```

> - `beats`：全曲节拍时间戳（绝对时间）。客户端应兼容 `beats` / `beat_times` / `timestamps` / `beat_points` 等字段名。
> - `clips`：当 `count>0` 时返回的卡点片段列表，每个片段 `{start, end, strength}` 对应一个视频；
>   客户端将落在每个片段区间内的 `beats` 作为该视频的卡点槽位，并用 `[start, end]` 裁剪对应音乐片段。

---

### 1.4 卡点成片 `POST /montage/beat`

一次上传音乐+全部素材，用 `variant_count` 一次生成多个卡点视频变体。

**Body** (multipart/form-data)：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| music | binary | ✅ | 整段音乐文件（仅上传一次） |
| videos | binary[] | ✅ | 全部镜头素材（图片/视频，多次上传同名字段） |
| variant_count | int | ❌ | 一次生成的完整成片变体数（上限 5） |
| time_limit | number | ❌ | 每个成片时长上限（秒，0=完整有效区间） |
| aspect_ratio | string | ❌ | 画面比例 `"16:9"`/`"9:16"`/`"1:1"` |
| width / height | int | ❌ | 输出分辨率 |
| transition | string | ❌ | 转场：fade/dissolve/wipeleft/wiperight/slideup/slidedown/radial/random/none |
| transition_duration | number | ❌ | 转场时长（秒） |
| min_duration / max_duration | number | ❌ | 单镜头最短/最长时长 |
| count / threshold / min_scene_len / fps / crf | - | ❌ | 其它编码/分割参数 |

**响应**：`{"task_id": "..."}` → 轮询 `GET /tasks/unified/{task_id}` → 完成后取结果。

### 1.5 卡点成片结果 `GET /montage/result/{task_id}` / `GET /montage/result/{task_id}/{variant_index}`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| task_id | path | string | 任务 ID |
| variant_index | path | int | 变体序号（取特定变体时） |

返回成片文件信息/流。

---

## 二、任务队列（通用轮询）

> ℹ️ 服务端已统一 task_id 查询接口：**推荐客户端统一使用 `GET /tasks/unified/{task_id}`** 跨队列查询所有类型任务。
>
> 原有 5 个分散接口仍可用，但新代码应优先使用统一接口：
>
> | 接口 | 队列 | 状态 |
> |------|------|------|
> | `GET /tasks/unified/{task_id}` | **统一查询** | ✅ 推荐 |
> | `GET /tasks/{task_id}` | 后台任务队列 | 兼容保留 |
> | `GET /scheduled/tasks/{task_id}` | 成片/定时任务队列 | 兼容保留 |
> | `GET /material/tasks/{task_id}` | 素材任务队列 | 兼容保留 |
> | `GET /vsr/result/{task_id}` | VSR 任务队列 | 兼容保留 |

### 2.1 查询任务状态 `GET /tasks/{task_id}`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| task_id | path | string | 任务 ID |

**响应**：
```json
{
  "task_id": "xxxx",
  "status": "pending | running | completed | failed",
  "result": { ... },
  "error": "错误信息（失败时）"
}
```

### 2.2 任务列表 `GET /tasks`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 50 | 返回条数 |
| model | string | "" | 按模型筛选 |
| status | string | "" | 按状态筛选 |
| type | string | "" | 按类型筛选 |
| type_prefix | string | "" | 按类型前缀筛选 |

### 2.3 取消任务 `DELETE /tasks/{task_id}`

### 2.4 统一任务查询 `GET /tasks/unified/{task_id}`

跨队列统一查询（后台队列 + 素材队列 + 成片队列），不确定任务在哪个队列时用这个。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| task_id | path | string | 任务 ID |

### 2.5 队列控制

| 端点 | 说明 |
|------|------|
| `GET /tasks/queue/state` | 队列状态 |
| `POST /tasks/queue/pause` | 暂停调度 |
| `POST /tasks/queue/resume` | 恢复调度 |
| `POST /tasks/batch_cancel` | 批量取消 |
| `POST /tasks/batch_delete` | 批量删除 |

---

## 三、素材管理

### 3.1 向量语义搜索 `POST /material/search`

CLIP 编码查询文本 → pgvector cosine 相似度。

**Body** (JSON)：
```json
{
  "query": "红色无线鼠标",
  "limit": 20
}
```

### 3.2 AI 分析 `POST /material/analyze`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| material_id | query | int | 从 DB 读文件（与 file 二选一） |
| file_hash | query | string | 按哈希定位 |
| background | query | bool | true 时提交后台任务返回 task_id |
| file | body | binary | 直接上传文件 |

### 3.3 画面质量评分 `POST /material/score`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| material_id | query | int | 素材 ID |
| file_hash | query | string | 文件哈希 |
| product_mode | query | bool | 产品模式 |

### 3.4 OCR 识别 `POST /material/ocr`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| material_id | query | int | 素材 ID（可选） |
| file_hash | query | string | 文件哈希（可选） |
| file | body (multipart) | binary | 上传图片字节 |

**返回**（`OCRResponse`，已声明响应模型）：
```json
{
  "filename": "xxx.jpg",
  "text": "整图所有文字拼接",
  "lines": [
    {"text": "...", "confidence": 0.99, "box": [184,61,611,140], "box_rel": [0.23,0.076,0.764,0.175]}
  ],
  "total": 12
}
```

`lines[]` 字段：
| 字段 | 类型 | 说明 |
|------|------|------|
| text | string | 该行识别文字 |
| confidence | number | 置信度 0-1 |
| box | int[4] \| null | 像素坐标 `[x1,y1,x2,y2]`（左上+右下），相对原图 |
| box_rel | float[4] \| null | 归一化坐标 `[x1,y1,x2,y2]`（0-1） |

> - **请求不支持 box 裁剪**：仅 `file`/`material_id`/`file_hash` 三个入参，整图识别。
> - **响应带坐标**：每行返回 `box`（像素）+ `box_rel`（归一化）。客户端 `extract_value_for_key` 用 box 做"关键词右/下方取值"的空间定位。
> - 选区/视频帧识别由**客户端先按 box 裁剪、再上传裁剪图**（`ocr_image_crop`）。

### 3.5 素材任务队列

| 端点 | Method | 说明 |
|------|--------|------|
| `/material/tasks` | GET | 素材任务列表 |
| `/material/tasks/{task_id}` | GET | 查询素材任务状态 |
| `/material/tasks/{task_id}` | DELETE | 取消素材任务 |
| `/material/tasks/queue/state` | GET | 素材队列状态 |
| `/material/tasks/queue/pause` | POST | 暂停素材队列 |
| `/material/tasks/queue/resume` | POST | 恢复素材队列 |
| `/material/tasks/batch_cancel` | POST | 批量取消 |
| `/material/tasks/batch_delete` | POST | 批量删除 |

### 3.6 其他素材接口

| 端点 | Method | 说明 |
|------|--------|------|
| `/material/list` | GET | 分页列表（支持 search/media_type/brand/category 等筛选） |
| `/material/schema` | GET | 可搜索字段字典 |
| `/material/distinct` | GET | 字段去重值 |
| `/material/stats` | GET | 统计信息 |
| `/material/status` | GET | 服务状态 |
| `/material/config` | GET/PUT | 数据库配置 |
| `/material/cron` | GET/PUT | 定时扫描任务配置 |
| `/material/dirs` | GET | 浏览 NAS 目录 |
| `/material/scan` | POST | 扫描 NAS 目录入库 |
| `/material/serve` | GET | 文件流式播放（支持 Range） |
| `/material/thumbnail` | GET | 单素材缩略图 |
| `/material/batch_thumbnail` | POST | 批量生成缩略图 |
| `/material/delete` | POST | 删除素材记录 |
| `/material/favorite` | POST | 收藏/取消收藏 |
| `/material/batch_score` | POST | 批量评分 |
| `/material/batch_analyze` | POST | 批量 AI 分析 |
| `/material/enqueue_analysis` | POST | 按条件批量加入分析队列 |
| `/material/backfill_dimensions` | POST | 回填宽高/时长维度 |
| `/material/cleanup_recycle` | POST | 清空回收站 |
| `/material/test_db` | POST | 测试数据库连接 |
| `/material/test_local` | POST | 测试本地存储 |
| `/material/logs` | GET | 单素材分析日志 |
| `/material/logs_list` | GET | 分析日志分页列表 |

### 3.7 相似素材 / 标签（新增）

| 端点 | Method | 说明 |
|------|--------|------|
| `/material/similar` | GET | 以图搜图 / 相似素材（CLIP 向量） |
| `/material/tags` | GET | 标签列表 |
| `/material/tags/add` | POST | 给素材加标签 |
| `/material/tags/remove` | POST | 移除素材标签 |

> 标签体系可用于素材检索的多维筛选（对标 Eagle/Billfish）。客户端 `vector_search_page` 待接入。

---

## 四、Whisper 语音转写

### `POST /whisper/transcribe`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| file | binary | — | 音频文件 |
| language | string | "zh" | 语言 |
| fmt | string | "srt" | 输出格式（`json` 时返回含 word 级时间戳的 segments） |
| task_id | string | "" | 关联任务 ID |

> `fmt=json` 时返回 `segments[].words[] = [{word, start, end}]`，可用于字级对齐。

| 端点 | Method | 说明 |
|------|--------|------|
| `/whisper/health` | GET | Whisper 服务健康检查 |
| `/v1/audio/transcriptions` | POST | OpenAI 兼容转写（等价 /whisper/transcribe） |

---

## 五、LLM 大模型

### `POST /llm/chat/completions`

统一 LLM 多模态接口，根据 model 自动路由到对应提供商。

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role": "user", "content": "你好"}],
  "max_tokens": 4096,
  "temperature": 0.7,
  "stream": false
}
```

### 其他 LLM 接口

| 端点 | Method | 说明 |
|------|--------|------|
| `/llm/models` | GET | 模型列表 |
| `/llm/providers` | GET | 提供商配置 |
| `/llm/providers/{key}` | GET/PUT/DELETE | 单个提供商管理 |
| `/llm/providers/{key}/toggle` | POST | 启用/禁用 |
| `/llm/templates` | GET | 内置模板 |
| `/llm/stats` | GET | Token 用量统计 |
| `/llm/records` | GET | 调用记录 |
| `/v1/models` | GET | 模型列表（OpenAI 兼容） |
| `/v1/chat/completions` | POST | 对话（OpenAI 兼容，等价 /llm/chat/completions） |
| `/llm/stats` | GET | Token 用量统计 |
| `/llm/records` | GET | 调用记录 |

---

## 六、声音克隆 VoxCPM

### `POST /voxcpm/tts`

```json
{
  "text": "要合成的文本",
  "prompt_audio": "base64或URL（参考音频）",
  "speaker": "default",
  "task_id": ""
}
```

| 端点 | 说明 |
|------|------|
| `POST /voxcpm/load` | 加载模型到显存 |
| `POST /voxcpm/unload` | 卸载模型 |
| `GET /voxcpm/health` | 健康检查 |

---

## 七、VSR 去字幕

### `POST /vsr/remove`

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| file | binary | — | 视频文件 |
| inpaint_mode | string | "sttn_det" | 算法：sttn_det/sttn_auto/lama/propainter |
| sub_areas | string | "" | 字幕区域 JSON `[[ymin,ymax,xmin,xmax]]` |

**异步**：返回 task_id → `GET /tasks/unified/{task_id}` 查询（统一接口） → `GET /vsr/download/{filename}` 下载

| 端点 | Method | 说明 |
|------|--------|------|
| `/vsr/detect` | POST | 自动检测字幕区域（返回 boxes） |
| `/vsr/health` | GET | VSR 服务健康检查 |

---

## 八、ComfyUI 图像/视频生成

| 端点 | Method | 说明 |
|------|--------|------|
| `/comfyui/run` | POST | 提交工作流 |
| `/comfyui/status` | GET | 运行状态 |
| `/comfyui/queue` | GET | 任务队列 |
| `/comfyui/history` | GET | 执行历史 |
| `/comfyui/view` | GET | 获取生成文件 |
| `/comfyui/models` | GET | 模型列表 |
| `/comfyui/workflows` | GET | 工作流列表 |
| `/comfyui/manage` | POST | 启动/停止/重启 |
| `/comfyui/config` | GET/PUT | 地址配置 |

---

## 九、Ollama 本地模型

| 端点 | Method | 说明 |
|------|--------|------|
| `/ollama/chat` | POST | 对话 |
| `/ollama/models` | GET | 模型列表 |
| `/ollama/status` | GET | 状态 |
| `/ollama/start` | POST | 启动 |
| `/ollama/stop` | POST | 停止 |
| `/ollama/load` | POST | 预热加载 |
| `/ollama/unload` | POST | 卸载 |
| `/ollama/pull` | POST | 下载模型 |

---

## 十、CLIP 向量

| 端点 | Method | 说明 |
|------|--------|------|
| `/clip/encode_image` | POST | 图片编码为向量 |
| `/clip/encode_text` | POST | 文本编码为向量 |
| `/clip/health` | GET | 健康检查 |

---

## 十一、模型调度

| 端点 | Method | 说明 |
|------|--------|------|
| `/models/status` | GET | 所有模型状态 |
| `/models/ensure/{service_key}` | POST | 确保模型已加载 |
| `/models/unload/{service_key}` | POST | 卸载模型 |
| `/models/scan_upgrade` | POST | 扫描升级 |
| `/models/upgrade` | POST | 执行升级 |

---

## 十二、定时任务

| 端点 | Method | 说明 |
|------|--------|------|
| `/scheduled/tasks` | GET/POST | 列表/创建 |
| `/scheduled/tasks/{task_id}` | GET/PUT/DELETE | 查询/更新/删除 |
| `/scheduled/tasks/batch_delete` | POST | 批量删除 |
| `/scheduled/tasks/queue` | GET | 队列状态 |
| `/scheduled/tasks/evolution/stats` | GET | 进化统计 |
| `/scheduled/tasks/evolution/feedback` | POST | 用户评分反馈 |

---

## 十二(补)、产品生图 / 应用执行 / NAS / OpenAI兼容（新增模块）

### 产品生图（对应客户端 ProductImagePage）
| 端点 | Method | 说明 |
|------|--------|------|
| `/product-image/generate` | POST | 单张产品图生成（产品图+场景描述→ComfyUI） |
| `/product-image/batch` | POST | 批量产品图生成 |
| `/product-image/status/{task_id}` | GET | 查询生成进度 |
| `/product-image/result/{task_id}` | GET | 下载生成结果（首张） |
| `/product-image/result/{task_id}/{filename}` | GET | 下载指定结果文件 |
| `/product-image/workflows` | GET | 可用场景工作流列表 |

### 已发布应用执行
| 端点 | Method | 说明 |
|------|--------|------|
| `/apps` | GET | 已发布应用列表 |
| `/apps/reload` | POST | 重新加载注册表 |
| `/apps/{app_id}` | GET | 应用详情 |
| `/apps/{app_id}/run` | POST | 执行应用 |
| `/apps/{app_id}/status/{prompt_id}` | GET | 查询执行状态 |

### NAS 存储
| 端点 | Method | 说明 |
|------|--------|------|
| `/nas/test` | POST | 测试 NAS 连接 |
| `/nas/scan` | POST | 扫描 NAS |

### OpenAI 兼容接口（/v1）
| 端点 | Method | 说明 |
|------|--------|------|
| `/v1/chat/completions` | POST | 对话（OpenAI 格式） |
| `/v1/audio/speech` | POST | TTS 语音合成（OpenAI 格式，等价 /voxcpm/tts） |
| `/v1/audio/transcriptions` | POST | 语音转写（OpenAI 格式，等价 /whisper/transcribe） |
| `/v1/embeddings` | POST | 文本向量（OpenAI 格式，等价 /clip/encode_text） |

### 模型模式切换（新增）
| 端点 | Method | 说明 |
|------|--------|------|
| `/models/mode` | GET/PUT | 获取/设置模型调度模式 |
| `/ollama/source` | GET/POST | Ollama 数据源（本地/远程） |
| `/ollama/switch-gpu` | POST | 切换 Ollama GPU |

### ComfyUI 补充（新增）
| 端点 | Method | 说明 |
|------|--------|------|
| `/comfyui/workflow` | GET | 读取指定工作流内容 |
| `/comfyui/upload/image` | POST | 上传图片（img2img） |
| `/comfyui/object_info` | GET | 节点信息 |
| `/comfyui/interrupt` | POST | 中断当前任务 |
| `/comfyui/free` | POST | 释放显存 |

### 产品库 ERP（/api/product-library）
| 端点 | Method | 说明 |
|------|--------|------|
| `/api/product-library/init` | POST | 初始化 |
| `/api/product-library/stats` | GET | 库统计 |
| `/api/product-library/erp-config` | GET/PUT | ERP 配置 |
| `/api/product-library/client/erp-config` | GET | 客户端取 ERP 配置 |
| `/api/product-library/client/erp-test` | POST | 客户端 ERP 测试 |
| `/api/product-library/clients/{machine_id}/items` | GET/POST | 产品列表/创建 |
| `/api/product-library/clients/{machine_id}/items/{item_id}` | GET/PUT/DELETE | 产品 CRUD |
| `/api/product-library/clients/{machine_id}/search` | GET | 产品搜索 |
| `/api/product-library/clients/{machine_id}/brands` | GET | 品牌列表 |
| `/api/product-library/clients/{machine_id}/categories` | GET | 分类列表 |
| `/api/product-library/clients/{machine_id}/grouped` | GET | 分组视图 |
| `/api/product-library/clients/{machine_id}/upsert` | POST | 批量 upsert |
| `/api/product-library/clients/{machine_id}/apply-categories` | POST | 应用分类 |
| `/api/product-library/clients/{machine_id}/sync` | POST | 触发同步 |
| `/api/product-library/clients/{machine_id}/sync/status` | GET | 同步状态 |
| `/api/product-library/clients/{machine_id}/mine` | POST | 触发挖掘 |
| `/api/product-library/clients/{machine_id}/mine/status` | GET | 挖掘状态 |
| `/api/product-library/clients/{machine_id}/items/{item_id}/prompt` | GET | 产品文案 prompt |

---

## 十三、系统

| 端点 | Method | 说明 |
|------|--------|------|
| `/` | GET | Dashboard |
| `/health` | GET | 全局健康检查 |
| `/system/license` | GET | 激活状态 |
| `/system/activate` | POST | 提交激活码 |
| `/system/license/machine-id` | GET | 机器码 |
| `/system/restart` | POST | 重启服务 |
| `/metrics/history` | GET | 硬件指标（最近10分钟） |
| `/api/logs` | GET | 服务端日志 |
| `/guide` | GET | API 引导页（HTML） |

---

## 附录：客户端常见错误对照

| 客户端错误写法 | 正确接口 | 说明 |
|---|---|---|
| `POST /material/beat_detect` | `POST /audio/beatmap` | 音乐卡点接口在 audio 模块，非 material |
| 轮询 `GET /material/beat_detect/{task_id}` | `GET /tasks/{task_id}` | 通用任务轮询路径 |
| 轮询 `GET /material/score_clip/{task_id}` | `GET /tasks/unified/{task_id}` | 统一任务查询接口 |
| VSR 参数 `ymin/ymax/xmin/xmax` 分开传 | `sub_areas` JSON 字符串 | 格式: `[[ymin,ymax,xmin,xmax]]` |
| VSR 跳过轮询直接拼 download URL | 先轮询 `GET /tasks/unified/{task_id}` | 等完成后再取文件名下载 |
