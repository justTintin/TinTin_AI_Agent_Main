# 客户端智能混剪 Step1 对接文档 — 镜头分割+分析合并接口改造

> 来源：服务端在线文档中心 `http://192.168.111.28:8000/guide/docs/CLIENT-STEP1-MIGRATION.md`
> 同步时间：2026-08-02（服务端 /guide + openapi.json 实测核对）
> 状态：服务端接口已上线并验证通过；本文为客户端（本仓库）需落地的改造参考。
> 客户端当前对齐情况：见文末《附录：客户端对齐核查（2026-08-02）》。

---

## 0. 服务端接口现状（已上线，验证通过）

```
POST /montage/split
Content-Type: multipart/form-data
file:            @video.mp4 或 @image.png     ← 客户端上传（视频做分割，图片转静态镜头）
material_id:     123                          ← 素材库素材 id（二选一，服务端解析后分割）
clip_url:        material://123 或 http(s)://...   ← 素材地址（二选一）
threshold:       27         ← 可选，切点敏感度
min_scene_len:   0.5        ← 可选，最小镜头时长(秒)
dedup:           true       ← 可选，重复镜头检测
dedup_threshold: 0.95       ← 可选
product_mode:    false      ← 可选，电商评分模式
analyze:         true       ← 可选，逐镜分析(评分+景别/产品)，默认 true
image_duration:  3.0        ← 可选，图片转静态镜头时长(秒)

GET /montage/split/clip/{task_id}/{filename}   ← 下载镜头片段
```

响应（每镜字段）：

```json
{
  "task_id": "abc123",
  "total_shots": 5,
  "shots": [{
    "shot_index": 1,
    "filename": "video_shot_001.mp4",
    "start_sec": 0.0, "end_sec": 3.2, "duration_sec": 3.2,
    "is_image": false,
    "download_url": "/montage/split/clip/abc123/video_shot_001.mp4",
    "aesthetic_score": {"total": 7.8, "clarity": 8.1, "texture": 7.5, "aesthetics": 8.0,
                        "composition": 7.6, "color_quality": 8.2, "figure_quality": 5.0,
                        "subject_prominence": 8.3, "engine": "quality_scorer"},
    "shot_analysis": {"shot_type": "特写", "visual_type": "产品", "segment": "前段",
                      "scene_primary": "黑色无线鼠标侧视图", "scene_secondary": "白色桌面自然光",
                      "brand": "罗技", "product": "鼠标", "model": null, "confidence": 0.93},
    "description": "黑色无线鼠标侧视图 白色桌面自然光",
    "duplicate_group": 1, "duplicate_similarity": 0.969,
    "is_best_in_group": true, "aesthetic_total": 6.3
  }],
  "dedup": {"enabled": true, "threshold": 0.95, "total_shots": 5,
            "file_duplicates": 0, "aesthetic_duplicates": 1},
  "analysis": {"enabled": true, "analyzed": 5, "total": 5}
}
```

字段一致性（服务端承诺）：
- 评分 `aesthetic_score.total` 与旧 `ServerClipAnalysisWorker` 解析的 `aesthetic_score.total` 同一 `quality_scorer` 引擎
- `shot_analysis` 与旧 `/material/score_clip` 的 `analyze_shot=true` 返回结构一致
- `description` = `scene_primary + scene_secondary` 拼接，可直接当画面描述

## 1. 需要改的客户端文件

| 文件 | 改动 |
|---|---|
| `gui/montage/workers/split_workers.py` | `ServerSplitWorker`：下载服务端片段替代本地重裁 |
| `gui/video_montage_page.py` | `_on_merged_split_done` 附近：消费分析字段写缓存 |
| `gui/montage/workers/desc_workers.py` | `LocalVisionDescWorker` / `BatchGenerateDescriptionsWorker`：改读 `description`，不再走 LLM |
| `gui/montage/workers/split_workers.py` | 删除死代码 `ServerClipAnalysisWorker` |
| `utils/shot_analysis_cache.py` | `upsert` 调用点补充新字段（extra） |

## 2. ServerSplitWorker 改造

现状：`POST /montage/split` 后本地 ffmpeg 按 `start_sec/end_sec` 重裁，丢弃 `download_url` / `aesthetic_score` / `shot_analysis` / `description`。

改法：
1. 请求 `data` 加 `"analyze": "true"`（默认即 true，显式更明确）。
2. 响应 `shots` 每镜带 `download_url`，**下载到本地 `output_dir`**，文件名保持 `{base}_shot_{idx:03d}.mp4`（与 `_rename_video_splits_with_metadata` 的 `_shot_` 前缀一致）；`download_url` 为相对路径，需拼 `server_url + download_url`。
3. 下载用流式 `http_get(url, stream=True)`，单镜可能几十 MB。
4. 某镜下载失败 → 保留旧逻辑本地重裁兜底。
5. `finished` 信号签名不变：`finished(output_dir, count, scenes)`，`scenes=[(start,end),...]`。
6. 每镜分析结果暂存 worker 实例属性（如 `self.shot_meta`），建议新增信号 `analysis_ready = Signal(list)`，`finished` 之后 emit `[{filename, aesthetic_score, shot_analysis, description}, ...]`。

## 3. 控制器消费分析结果

`_on_merged_split_done` 回调收到 `analysis_ready` 的 shot_meta 后，按 `filename` 写入 sidecar 缓存：

```python
from utils.shot_analysis_cache import ShotAnalysisCache
cache = ShotAnalysisCache(video_workspace_dir, video_basename)
for meta in shot_meta:
    path = os.path.join(cur_splits_dir, meta["filename"])
    as_ = meta.get("aesthetic_score") or {}
    sa = meta.get("shot_analysis") or {}
    cache.upsert(path, {
        "score": as_.get("total"),
        "desc": meta.get("description") or sa.get("scene_primary") or "",
        "shot_type": sa.get("shot_type"),
        "product": sa.get("product"),
        "model": sa.get("model"),
        "extra": {"aesthetic_score": as_, "shot_analysis": sa},
    })
```

写缓存后再 `_check_split_clips_exist()` 刷新表格。`_score_clip` 与 `_pending_score_rows` 消费逻辑可移除；`ServerClipAnalysisWorker` 及 `_on_analysis_item_ready/_on_analysis_all_done/_on_analysis_error` 已无实例化点，删除。

## 4. 画面描述改造（两选一）

- **A（推荐）**：`/montage/split` 已返回 `description`，`_check_split_clips_exist` 的 desc 列读缓存即可；删除/停用 `LocalVisionDescWorker` 触发（`_on_highlights_all_finished` 的 `_trigger_vision_on_dir`）。
- **B（保留 LLM 描述可选）**：仅当 `description` 为空时兜底走 LLM，`_trigger_vision_on_dir` 改为只对无 description 的片段执行。

## 5. 素材来源处理规则（关键）

| 素材来源 | 分割 | 分析 | 处理方式 |
|---|---|---|---|
| 客户端上传视频 | ✅ | ✅ 逐镜 | `ServerSplitWorker` 传 `file`，服务端分割+逐镜分析 |
| 客户端上传图片 | ❌（转静态镜头） | ✅ | 传 `file`，返回 `is_image:true`，时长=image_duration |
| 素材库图片 | ❌ | ❌ 免分析 | 素材库已分析（`ai_status=analyzed`），直接用 `scene_desc_*`/`quality_score`/`shot_type`，**不调** `/montage/split` |
| 素材库视频（本地/NAS 可访问） | ✅ | ✅ 逐镜 | 素材库整段一帧分析、无逐镜数据 → 需重新分割+逐镜分析；传 `file` 或 `material_id` |
| 素材库视频（仅 material://） | ✅ | ✅ 逐镜 | 传 `material_id` 或 `clip_url`，服务端解析后分割 |

客户端需改的点（素材检索 → 智能混剪）：
1. `gui/vector_search_page.py` `_build_selected_materials` 补带 `ai_status`/`scene_desc_*`/`quality_score`/`shot_type` 字段，用于素材库图片免分析复用。
2. `video_montage_page.py` `set_external_materials`：图片一律转 `material://` 进 concat 的旧逻辑需调整；本地/NAS 视频走 `/montage/split`；仅 `material://` 素材若要分割传 `material_id` 给 `/montage/split`。
3. `ServerSplitWorker` 增加可选 `material_id`/`clip_url` 参数：有本地文件传 `file`，只有素材库地址传 `material_id`。

## 6. 不改的部分

- **Step2 镜头重组**：`POST /montage/concat` 已服务端化闭环（`montage_concat_server_worker.py`），不用改。
- **Step3 配音**：`POST /voxcpm/tts` 已服务端化，不用改。
- **Step4 特效包装**：本地 ffmpeg + 剪映导出，按设计保留。
- **评分过滤**：`step1_score_filter_combo`（默认 ≥6 分）直接消费 `aesthetic_score.total`，字段名未变。

## 7. 验证清单

- [ ] 视频分割：返回片段可下载且可播放，时长与 `start_sec/end_sec` 一致
- [ ] 图片分割：返回 `is_image:true` 单镜，时长=image_duration
- [ ] 素材库图片：不调分割接口，直接复用素材库 `scene_desc_*`/`quality_score`/`shot_type`
- [ ] 素材库视频：传 `material_id` 能正常分割+逐镜分析
- [ ] 评分列：新片段显示 `aesthetic_score.total`（不再"—"）
- [ ] 描述列：显示 `description`，不再走 LLM（或仅空值兜底）
- [ ] 景别/产品/型号列：显示 `shot_analysis` 对应字段
- [ ] 重新打开应用 / 重新分割：sidecar 缓存命中，字段不丢
- [ ] 断网回退：`download_url` 下载失败 → 本地重裁兜底，流程不中断

---

## 附录：客户端对齐核查（2026-08-02）

> 依据：本地代码 + 服务端在线实测（openapi.json / /guide / CLIENT-STEP1-MIGRATION.md，任务 184/185 轮询验证）。
> 更新：客户端已于 2026-08-03 按本方案完成改造落地（下表 1-5/8 均已对齐）。

| # | 改造点 | 服务端要求 | 客户端现状 | 状态 |
|---|---|---|---|---|
| 1 | `ServerSplitWorker` 下载片段 | 用 `download_url` 下载替代本地 ffmpeg 重裁，失败才本地兜底 | 已改为下载服务端片段，本地兜底；新增 `analysis_ready` 信号，支持 `material_id`/`clip_url` | ✅ 已对齐 |
| 2 | 分析字段消费 | `_on_merged_split_done` 把 `aesthetic_score/shot_analysis/description` 写 sidecar 缓存 | 已通过 `_on_split_analysis_ready` 写 sidecar 缓存，评分/景别/产品/型号列回填 | ✅ 已对齐 |
| 3 | 死代码清理 | 删 `ServerClipAnalysisWorker`（split_workers.py:345-572）与 `_on_analysis_*` | 已删除 | ✅ 已对齐 |
| 4 | 画面描述 | 方案B：优先读 `description`，仅空值兜底 LLM | 已改为仅对无描述片段兜底走服务端 LLM 视觉接口 | ✅ 已对齐（方案B） |
| 5 | 素材来源 | `set_external_materials` 区分：素材库图片免分析复用 / 素材库视频传 `material_id` 分割；`ServerSplitWorker` 支持 `material_id`/`clip_url` | 已实现：`vector_search_page` 带分析字段；`_start_split` 支持素材库视频（material_id）分割；图片免分割直用于拼接 | ✅ 已对齐 |
| 6 | Step2 concat | 已服务端化，不改 | `MontageConcatServerWorker` files+clip_urls 混合、`/tasks/unified` 轮询、`result.output_url` 下载（实测 `output_url=/editor/render/{id}/result` 可下载） | ✅ 对齐 |
| 7 | 方案二缓存 | 派生片段下载进 `.runtime/montage_cache/<job_id>/splits/<视频名>/` | 已落地（上一提交）；改造点1接入后下载目标即缓存 splits | ✅ 对齐（待接入） |
| 8 | 评分过滤 | `step1_score_filter_combo` 消费 `aesthetic_score.total` | 分析接入后评分列已回填，过滤生效 | ✅ 已对齐 |

### 在线实测证据（2026-08-02）

- `POST /montage/split`（file 上传）返回 `{task_id, total_shots, analysis:{enabled,analyzed,total}, shots:[{shot_index, filename, start_sec, end_sec, duration_sec, is_image, download_url, aesthetic_score{total,...}, shot_analysis{shot_type,visual_type,segment,scene_primary,scene_secondary,brand,product,model,confidence}, description}]}`；`GET /montage/split/clip/{task_id}/{filename}` 可下载（200, video/mp4）。
- `POST /montage/split` 传 `clip_url=material://764578`（素材库素材）可直接分割，返回同结构 shots（服务端解析素材库）。
- `POST /montage/concat` 返回 `{id, status, queue_position, clip_count}`；轮询 `GET /tasks/unified/{id}` → `completed` 后 `result` = `{clip_count, duration, output_path, output_url(/editor/render/{id}/result), size_mb, warnings}`；用 `output_url` 可下载成片（任务 185 完成）。
- 注意事项：两次提交内容完全相同的片段时 concat 曾 failed（progress 45，result 空）；换不同内容片段后成功——重复内容片段会导致服务端拼接失败，客户端应避免提交完全相同的镜头。

