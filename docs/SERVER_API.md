# 服务端接口文档（客户端对接用）

> 服务端地址：`http://192.168.111.28:8000`（2026-08-02 实测，原 .19 已迁移）
> OpenAPI 规范：`http://192.168.111.28:8000/openapi.json`
> 框架：FastAPI (Python)，实测共 241 个路径
> 最后同步：2026-08-03

⚠️ **重要原则**：客户端不得自行定义接口路径和协议，必须严格对照本文档（即服务端 OpenAPI 实际暴露的端点）。

---

## 一、智能混剪相关接口

> 2026-08-02 服务端已上线「分割+分析合并」改造：`POST /montage/split` 一个接口完成镜头分割 + 逐镜美学评分 + 景别/产品识别 + 画面描述，并返回服务端裁好的片段下载地址；客户端不再需要本地重裁，也无需单独调 `/material/score_clip`。
> 完整改造方案见《CLIENT-STEP1-MIGRATION.md》。

### 1.1 镜头分割+分析合并 `POST /montage/split`

上传视频/图片 或 素材库素材 → 服务端镜头分割 → 裁出片段 → 逐镜分析（评分/景别/产品/描述）→ 返回片段与数据。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | 二选一 | — | 客户端上传的视频/图片（multipart；视频做分割，图片转静态镜头） |
| material_id | string | 二选一 | "" | 素材库素材 id（服务端解析后分割） |
| clip_url | string | 二选一 | "" | 素材地址：`material://{id}` / `http(s)://...` / 本地路径 |
| threshold | number | ❌ | 27 | 场景检测敏感度 (1-100, 越小越敏感) |
| min_scene_len | number | ❌ | 0.5 | 最小镜头长度（秒） |
| dedup | boolean | ❌ | true | 重复镜头检测 |
| dedup_threshold | number | ❌ | 0.95 | 重复判定相似度阈值（0~1） |
| product_mode | boolean | ❌ | false | 美学评分是否用电商模式 |
| analyze | boolean | ❌ | true | 是否逐镜分析（美学评分+景别/产品识别） |
| image_duration | number | ❌ | 3.0 | 图片转静态镜头时长（秒） |

**响应**：

```json
{
  "task_id": "abc123",
  "filename": "video.mp4",
  "total_shots": 5,
  "shots": [{
    "shot_index": 1,
    "filename": "video_shot_001.mp4",
    "start_sec": 0.0, "end_sec": 3.2, "duration_sec": 3.2,
    "is_image": false,
    "download_url": "/montage/split/clip/abc123/video_shot_001.mp4",
    "aesthetic_score": {"total": 7.8, "clarity": 8.1, "texture": 7.5, "aesthetics": 8.0, "composition": 7.6, "color_quality": 8.2, "figure_quality": 5.0, "subject_prominence": 8.3, "engine": "quality_scorer"},
    "shot_analysis": {"shot_type": "特写", "visual_type": "产品", "segment": "前段", "scene_primary": "黑色无线鼠标侧视图", "scene_secondary": "白色桌面自然光", "brand": "罗技", "product": "鼠标", "model": null, "confidence": 0.93},
    "description": "黑色无线鼠标侧视图 白色桌面自然光",
    "duplicate_group": 1, "duplicate_similarity": 0.969, "is_best_in_group": true, "aesthetic_total": 6.3
  }],
  "dedup": {"enabled": true, "threshold": 0.95, "total_shots": 5, "file_duplicates": 0, "aesthetic_duplicates": 1},
  "analysis": {"enabled": true, "analyzed": 5, "total": 5}
}
```

> - `shots[].download_url` 为相对路径，客户端拼 `server_url + download_url` 流式下载片段；文件名保持 `{源视频名}_shot_{序号:03d}.mp4`。
> - 评分取 `aesthetic_score.total`（与旧 `/material/score_clip` 同一 quality_scorer 引擎）；`shot_analysis` 与旧 `analyze_shot=true` 结构一致；`description` = `scene_primary + scene_secondary`。
> - 素材库图片已整图分析过（ai_status=analyzed）时，可免分割直接复用素材库 `scene_desc_*`/`quality_score`/`shot_type`，不调本接口。

---

### 1.2 分割片段下载 `GET /montage/split/clip/{task_id}/{filename}`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| task_id | path | string | `/montage/split` 返回的任务 id |
| filename | path | string | shots[].filename（如 `video_shot_001.mp4`） |

返回 `video/mp4` 流（支持 Range）。

---

### 1.3 镜头拼接 `POST /montage/concat`

上传已排序镜头文件 + 合成参数 → 立即创建拼接任务 → 返回 task_id。支持本地文件与素材地址混合。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| files | binary[] | 与 clip_urls 合计 ≥2 | — | 本地镜头上传（可多传） |
| clip_urls | string | ❌ | "" | 素材地址 JSON 数组字符串：`["material://123","/abs/b.mp4","http://x/a.mp4"]`（素材检索地址/本地路径/网络地址，与 files 可混合） |
| lut | binary | ❌ | — | 3D LUT 文件（.cube） |
| transition | string | ❌ | fade | fade/dissolve/wipeleft/wiperight/slideup/slidedown/radial/random/none |
| transition_duration | number | ❌ | 0.3 | 转场时长（秒） |
| width / height | int | ❌ | 1080 / 1920 | 输出分辨率 |
| fps | int | ❌ | 30 | 帧率 |
| crf | int | ❌ | 20 | 编码质量 |
| preset | string | ❌ | medium | 编码预设 |
| image_duration | number | ❌ | 3.0 | 图片素材转静态镜头时长（秒） |

**响应**：`{"id": 185, "status": "queued", "queue_position": 1, "clip_count": 2}`

轮询 `GET /tasks/unified/{id}`（或 `GET /scheduled/tasks/{id}`）→ `completed` 后取 `result`：

```json
{
  "clip_count": 2,
  "duration": 3.73,
  "output_url": "/editor/render/185/result",
  "output_path": "/home/.../server/output/montage/concat_185/final.mp4",
  "size_mb": 0.0,
  "warnings": []
}
```

下载成片：拼 `server_url + result.output_url`（或 `GET /montage/concat/result/{task_id}`）。

> ⚠️ 实测注意：提交内容完全相同的多个片段时任务可能 failed（progress 45、result 空）；应避免重复内容镜头。

---

### 1.4 拼接成片下载 `GET /montage/concat/result/{task_id}`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| task_id | path | string | `/montage/concat` 返回的任务 id |

返回成片文件流。

---

### 1.5 镜头评分/分析 `POST /material/score_clip`（兼容保留，新代码改用 split.analyze）

客户端上传视频镜头 → 入成片任务队列 → 抽帧打分。返回成片任务 ID，客户端轮询 `GET /scheduled/tasks/{task_id}` 查看结果。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | ✅ | — | 视频镜头片段（multipart/form-data） |
| product_mode | boolean | ❌ | false | 产品模式（产品/普通） |
| analyze_shot | boolean | ❌ | false | 是否做镜头画面分析 |
| frame_at | number | ❌ | 0.5 | 抽帧时间点（秒） |

**响应**（提交成功）：`{"task_id": "...", "status": "pending"}` → 轮询 `GET /tasks/unified/{task_id}`。

**任务完成后的 result 字段**：

```json
{
  "filename": "镜头片段.mp4",
  "aesthetic_score": {
    "total": 7.1,
    "engine": "laion+opencv",
    "clarity": 7.7, "texture": 4.5, "aesthetics": 5.0, "composition": 7.5,
    "color_quality": 10.0, "figure_quality": 5.0, "subject_prominence": 10.0
  }
}
```

> ℹ️ 评分在 `result.aesthetic_score.total`，不是 `result.score`。
> ℹ️ **新代码不再调用本接口**：`POST /montage/split` 的 `analyze=true` 已内嵌同等分析（同一引擎/结构）。

---

### 1.6 音乐卡点 `POST /audio/beatmap`

上传音乐文件，入后台任务队列，返回任务 ID，客户端轮询 `GET /tasks/{id}` 取结果。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | binary | ✅ | — | 音频文件（mp3/wav/m4a 等，multipart/form-data） |
| count | int | ❌ | 0 | 要返回的卡点片段个数（>0 时服务端从音乐中挑选 N 个片段，每段生成一个视频） |
| segment_duration | float | ❌ | 0.0 | 每个片段的时长（秒），与 count 配合使用 |

**响应**（提交成功）：`{"task_id": "...", "status": "pending"}` → 轮询 `GET /tasks/unified/{task_id}`。

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
> - `clips`：当 `count>0` 时返回的卡点片段列表，每个片段 `{start, end, strength}` 对应一个视频。

---

### 1.7 卡点成片 `POST /montage/beat`

一次上传音乐+全部素材，用 `variant_count` 一次生成多个卡点视频变体。

**Body** (multipart/form-data)：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| music | binary | ✅ | 整段音乐文件（仅上传一次） |
| videos | binary[] | 与 clip_urls 至少传一个 | 原始视频文件（可多传，服务端先做镜头分割） |
| clip_urls | string | ❌ | 已分割素材地址 JSON 数组（本地路径/可下载 URL），与 videos 合并入素材池 |
| variant_count | int | ❌ | 一次生成的完整成片变体数（1~5，上限 5） |
| time_limit | number | ❌ | 每个成片时长上限（秒，0=完整有效区间） |
| aspect_ratio | string | ❌ | 画面比例 `"16:9"`/`"9:16"`/`"1:1"` |
| width / height | int | ❌ | 输出分辨率 |
| transition | string | ❌ | 转场：fade/dissolve/wipeleft/wiperight/slideup/slidedown/radial/random/none |
| transition_duration | number | ❌ | 转场时长（秒） |
| min_duration / max_duration | number | ❌ | 单镜头最短/最长时长 |
| count / threshold / min_scene_len / fps / crf | - | ❌ | 其它编码/分割参数 |

**响应**：`{"task_id": "..."}` → 轮询 `GET /tasks/unified/{task_id}` → 完成后取结果。

### 1.8 卡点成片结果 `GET /montage/result/{task_id}` / `GET /montage/result/{task_id}/{variant_index}`

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

> 注：语义搜索不支持 brand 等过滤参数（传了服务端返回 400，其余参数被忽略）；品牌/型号/分类筛选请在浏览模式（`/material/list`）使用。

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
| `/material/list` | GET | 分页列表，支持 search/media_type/brand/category/model/background_type/score_range/file_hash/tag/favorite/ai_status/share_name/cursor/search_mode/dup 等筛选；**brand 传归一化名、model 模糊匹配、background_type 按背景类型（白底=white）** |
| `/material/schema` | GET | 可搜索字段字典（含去重值） |
| `/material/distinct` | GET | 字段去重值（原始值，品牌请用归一化接口） |
| `/material/backfill_brand` | POST | **品牌/型号归一化回填**（罗技/Logitech/罗技科技 → 罗技），后台任务；body.limit 最多处理条数（0/缺省=全部），进度轮询 GET /material/tasks/{task_id} |
| `/material/backfill_background` | POST | **背景类型回填**（白/黑/纯色/渐变/绿幕/蓝幕/透明/场景），后台任务；body.limit 最多处理条数（0/缺省=全部缺 background_type 的素材），进度轮询 GET /material/tasks/{task_id} |
| `/material/duplicates` | GET | 素材库重复检测：文件重复(hash) + 美学重复(embedding 余弦相似度，threshold 默认0.95，limit 默认100) |
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

> **品牌归一化说明（2026-08-03 实测）**：
> - 服务端已对品牌做归一化（如 罗技/Logitech/罗技科技 → 罗技），归一化品牌列表来自 `GET /api/product-library/clients/{machine_id}/brands`（产品库章节）。
> - 素材筛选品牌时传归一化名：实测 `/material/list?brand=罗技(Logitech)` 返回 93 条，且返回素材 brand 已是归一化值。
> - 旧数据可通过 `POST /material/backfill_brand` 回填归一化。
> - **注意**：`/material/search`（语义搜索）不接受 brand 参数（传了返回 400），品牌/型号筛选仅在浏览模式（/material/list）生效。

> **背景类型过滤（2026-08-03 服务端已上线）**：
> - `/material/list` 新增 `background_type` 参数，取值（distinct）：`gradient`/`scene`/`transparent`/`white`；**白底图过滤传 `background_type=white`**（实测返回标记为 white 的素材）。
> - 客户端素材检索“白底图”选项已接入该参数；旧数据可通过 `POST /material/backfill_background` 回填。

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
| sub_areas | string | "" | 字幕区域 JSON，三种格式见下 |

**`sub_areas` 三种格式**（均为**相对坐标** 0~1，非像素）：
- **空字符串 `""`**：智能去除，服务端自动检测字幕位置（对应客户端"智能去除"模式）
- **矩形** `[[ymin_rel, ymax_rel, xmin_rel, xmax_rel]]`，例：`[[0.88, 0.99, 0.15, 0.85]]`
- **多边形（不规则四边形，用于斜水印）** `[[[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]]]`，四点相对坐标，例：`[[[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]]]`

> 客户端 `subtitle_removal_page_v14.py` 现用四边形格式提交（支持斜水印）；本地 CLI 模式仍用矩形像素（四边形退化为其 AABB 外接框）。

**异步**：返回 `{"task_id","status":"pending","message"}` → 轮询 `GET /vsr/result/{task_id}`（status: pending→running→completed）→ `GET /vsr/download/{filename}` 下载

### `POST /vsr/detect` — 自动检测字幕框
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| file | binary | — | 视频文件 |
| interval | number | 1.0 | 采样间隔（秒） |

异步返回 task_id，轮询 `GET /vsr/result/{task_id}`，完成后 `result.boxes[]` 结构：
```json
{
  "video": {"width":640,"height":360,"fps":25.0,"frame_count":50,"duration":2.0},
  "sampled_frames": 2, "frames_with_text": 2,
  "boxes": [{
    "xmin":226,"xmax":411,"ymin":327,"ymax":355,        // 像素坐标
    "xmin_rel":0.3531,"xmax_rel":0.6422,"ymin_rel":0.9083,"ymax_rel":0.9861,  // 相对坐标
    "polygon":[[0.3531,0.9083],[0.6422,0.9083],[0.6422,0.9861],[0.3531,0.9861]]  // 四点相对坐标
  }]
}
```

| 端点 | Method | 说明 |
|------|--------|------|
| `/vsr/remove` | POST | 去字幕（支持空/矩形/多边形 sub_areas） |
| `/vsr/detect` | POST | 自动检测字幕区域（返回 boxes+polygon） |
| `/vsr/analyze` | POST | 视频分析（file, interval, sub_areas） |
| `/vsr/result/{task_id}` | GET | 查询任务结果（status/progress/log/result） |
| `/vsr/download/{filename}` | GET | 下载结果视频 |
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


## 十四、模板接口（统一模板 /templates/* + 相关模板组）

> ℹ️ 客户端应优先使用**统一模板接口**（OpenAPI tag：模板统一，`/templates/*`）。
> 旧 `/template/*`（成片模板）与 `/mg/templates`（MG 动画）仍保留兼容，但新代码应走统一接口。

### 14.1 统一模板 CRUD（模板统一）

| 端点 | Method | 说明 |
|------|--------|------|
| `/templates` | GET | 模板列表，`?type=` 过滤 `video/motion/cover/beat`；**封面模板与动效模板已分离**（2026-08-02 实测 25 个：motion 16 + cover 5 + video 2 + beat 2），含完整 params schema + effects |
| `/templates` | POST | 保存/创建模板（同 id 覆盖更新；内置模板不可覆盖） |
| `/templates/{template_id}` | GET | 查询单个模板完整定义 |
| `/templates/{template_id}` | PUT | 更新自定义模板（整体替换） |
| `/templates/{template_id}` | DELETE | 删除自定义模板（内置不可删） |
| `/templates/validate` | POST | 校验模板定义（`TemplateIn`）→ `{"ok": true}` |

### 14.2 统一模板渲染 / 预览 / 分析

| 端点 | Method | 说明 |
|------|--------|------|
| `/templates/analyze-video` | POST | 上传动效视频 → 分析画面 → 生成统一模板定义（multipart：`file` / `material_id`） |
| `/templates/preview` | POST | 动效/封面模板单帧预览（Remotion still），body 同 `RenderIn` |
| `/templates/render` | POST | **统一渲染入口**：按模板 type 分发到 Remotion / 剪辑引擎，body 为 `RenderIn`。motion/video 返回 JSON 任务 ID（轮询 result/download）；**cover 直接同步返回 PNG**（客户端用 render_cover_image） |
| `/templates/render/beat` | POST | 音乐卡点成片渲染（multipart：`template_id`+`music` 必填，`videos[]`/`clip_urls`，`params` 为 JSON 字符串） |
| `/templates/render/result/{task_id}` | GET | 统一渲染进度/结果查询（恒返回 JSON 状态） |
| `/templates/render/download/{task_id}` | GET | 渲染结果下载（动效 mp4 / 成片 mp4） |

**`GET /templates/render/result/{task_id}` 响应**（2026-08-02 实测）：

```json
{
  "id": "c_xxxx",
  "status": "pending | running | completed | failed",
  "progress": 0,
  "result": {
    "output_url": "/templates/render/download/c_xxxx",
    "output_path": "...",
    "template": "mg_intro",
    "type": "motion"
  },
  "error": null
}
```

### 14.3 请求 Schema

**`TemplateIn`**（POST/PUT `/templates`、`/templates/validate`）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | `^[a-zA-Z0-9_\-]+$`，2~64 字符 |
| name | string | ✅ | 1~80 字符 |
| category | string | ❌ | 默认 `custom` |
| type | string | ❌ | `video/motion/cover`，默认 `motion`（实测含 `beat`） |
| canvas | object | ❌ | 如 `{"width":1080,"height":1920,"fps":30}` |
| duration | number | ❌ | 0.5~120，默认 4.0 |
| params | array | ❌ | `ParamDef[]` |
| effects | object | ❌ | 视频效果定义（含 `{{参数}}` 占位符） |

**`ParamDef`**：`name`（必填）、`type`（默认 string）、`default`、`label`、`required`、`options[]`。

**`RenderIn`**（`/templates/render`、`/templates/preview`）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| template_id | string | ✅ | 模板 id |
| params | object | ❌ | 模板参数（按 params schema），如 `{"topic":"...","bgm":"..."}` |
| type | string | ❌ | 渲染模式，可选覆盖模板默认（`video/motion/cover`） |
| ratio | string | ❌ | 画面比例，默认 `9:16` |
| width / height | int | ❌ | 输出分辨率 |
| scale | number | ❌ | 0.2~1.0，默认 1.0 |

**`/templates/render/beat` multipart 字段**：`template_id`（必填）、`params`（JSON 字符串，默认 `"{}"`，覆盖模板默认风格参数 threshold/count/time_limit/min_duration/max_duration/transition/aspect 等）、`music`（必填）、`videos[]`、`clip_urls`。

### 14.4 相关模板组（并存）

| 组 | 端点 | 说明 |
|----|------|------|
| 成片模板（旧） | `/template/list` `/template/validate` `/template/import` `/template/export/{id}` `/template/generate` `/template/match` | 旧版成片模板（category 过滤），兼容保留；`/template/list?category=cover` 实测 total=0（封面模板只走统一接口） |
| MG 动画 | `/mg/templates` 及 `/mg/templates/{template_id}` | MG 动画模板 CRUD（内置不可删） |
| 花字模板 | `/textfx/templates` 及 `/textfx/templates/{template_id}` | 花字模板（zip 上传） |
| LLM 模板 | `/llm/templates` | 内置 LLM 提供商模板 |
### 14.5 封面模板（type=cover）与动效模板（type=motion）分离（2026-08-02 实测）

服务端已把**封面模板**与**动效模板**在统一模板库中按 `type` 分开：

| type | 含义 | 数量 | 模板 |
|------|------|------|------|
| `cover` | 封面模板：静态画面 + 参数驱动 | 5 | `cover_promo` 促销封面、`cover_title` 大字标题、`cover_quote` 金句、`cover_gradient` 渐变、`cover_clean` 极简（均 builtin） |
| `motion` | 动效模板：视频动效 | 16 | `mg_scene`/`mg_intro`/`mg_outro`/`mg_countdown`/`mg_quote`/`mg_benchmark`/`rve_*` 等（均 builtin） |
| `video` | 一键成片 | 2 | `ecom_15s`、`brand_30s`（params: topic/bgm） |
| `beat` | 音乐卡点 | 2 | `beat_fast`、`beat_smooth` |

封面模板参数（type=cover，2026-08-02 实测）：

- `cover_promo`：title / subtitle / badge / color / bg / fontSize
- `cover_title`：title / subtitle / color / bg / fontSize
- `cover_quote`：title / text / author / color / bg / fontSize
- `cover_gradient`：title / subtitle / color / bg / bg2 / fontSize
- `cover_clean`：title / subtitle / color / bg / fontSize

> 客户端获取封面模板用 `GET /templates?type=cover`（统一接口，返回 5 个内置封面模板）；
> 旧 `/template/list?category=cover` 实测 `total=0`（不含封面模板，仅兼容保留）。

---
## 附录：客户端常见错误对照

| 客户端错误写法 | 正确接口 | 说明 |
|---|---|---|
| `POST /material/beat_detect` | `POST /audio/beatmap` | 音乐卡点接口在 audio 模块，非 material |
| 轮询 `GET /material/beat_detect/{task_id}` | `GET /tasks/{task_id}` | 通用任务轮询路径 |
| 轮询 `GET /material/score_clip/{task_id}` | `GET /tasks/unified/{task_id}` | 统一任务查询接口 |
| VSR 参数 `ymin/ymax/xmin/xmax` 分开传 | `sub_areas` JSON 字符串 | 三种格式：空(智能)/矩形/多边形，均为相对坐标（见 §七） |
| VSR 跳过轮询直接拼 download URL | 先轮询 `GET /vsr/result/{task_id}` | 等完成后再取文件名下载 |
| 客户端 `GET /template/list?category=cover` | `GET /templates?type=cover` | 统一模板接口按 type 过滤；封面模板已上线（5 个 type=cover），旧接口 total=0 |
| 客户端 `POST /template/generate` | `POST /templates/render` | 统一渲染入口，body 为 RenderIn（template_id + params） |
| 客户端 `POST /template/import` | `POST /templates` | 统一保存/创建模板（同 id 覆盖） |
| 客户端 `POST /template/validate` | `POST /templates/validate` | 统一模板校验 |
| 客户端 `GET /template/export/{id}` | `GET /templates/{id}` | 统一模板详情查询 |
| 客户端轮询模板渲染任务 | `GET /templates/render/result/{task_id}` | 统一渲染进度/结果；下载用 `GET /templates/render/download/{task_id}` |
