# TinTin 工程命名规则（同步自服务端 NAMING-CONVENTIONS）

> 来源：服务端在线文档中心 `http://192.168.111.28:8000/guide/docs/NAMING-CONVENTIONS.md`
> 同步时间：2026-08-03
> 本规则是**整个工程（服务端 server/ + 客户端 studio/）的唯一命名约定**。新代码必须遵守；既有代码不一致处逐步收敛（见附录B）。
> 核心原则：可读性 > 简短，一致性 > 个人偏好。

## 0. 总则
- **见名知意**：名字必须准确描述内容/用途，禁止缩写语义不明的词。
- **一处一义，一义一名**：同一概念全局只能有一个名字；不同概念禁止重名。
- **分层上下文**：模块内短名、跨模块带领域前缀（见 §3 前缀体系）。
- **中英对照**：用户可见术语中英文并存；内部标识一律英文 snake_case。
- **宁可长，不可歧义**：`material_backfill_brand` 优于 `mbf`。

## 1. 代码标识符命名

| 场景 | 规则 | 示例 |
|---|---|---|
| 函数/方法 | snake_case，动词开头 | `_norm_brand()`、`_build_compose_cmd()`、`submit_beat_task()` |
| 类 | PascalCase | `TimelineSegment`、`ComposeRequest`、`ServerSplitWorker` |
| 模块级常量 | 全大写 + 下划线 | `_BRAND_ALIASES`、`OUTPUT_ROOT`、`_DUP_CACHE_TTL` |
| 模块内私有 | 前缀 `_` | `_analyze_pipeline`、`_norm_model` |
| 局部变量/参数 | 全小写 snake_case | `task_id`、`clip_path` |
| 布尔变量 | `is_` / `has_` / `can_` 前缀 | `is_best_in_group`、`is_image`、`has_audio` |
| 枚举值 | snake_case，小写 | `pending → queued → running → analyzed` |

## 2. 流程术语命名（中文流程 → 英文标识）

规则：`<领域>_<动作>`，领域词用业务中文名对应英文，动作词用统一动词表。

### 2.1 动作词统一表（必须用这些词，不得自创）

| 动作词 | 含义 | 示例 |
|---|---|---|
| split | 镜头分割 | `/montage/split`、`_split_video_to_shots` |
| concat | 镜头拼接 | `montage_concat`、`concat_to_project` |
| compose | 合成命令构建 | `ComposeRequest`、`_build_compose_cmd` |
| beat | 音乐卡点成片 | `montage_beat`、`beat_compose` |
| render | 渲染 | `editor_render`、`render_project`、`render_mg` |
| analyze | 智能分析 | `material_analyze`、`material_batch_analyze` |
| score | 美学评分 | `clip_score`、`material_batch_score`、`score_clip` |
| scan | 扫描入库 | `material_scan` |
| transcribe | 语音转写 | `whisper_transcribe`、`transcribe` |
| encode | 向量编码 | `clip_encode_image`、`clip_encode_text` |
| backfill | 存量数据回填 | `material_backfill_dimensions`、`material_backfill_brand` |

### 2.2 产品形态/流程标识（task_type 与路径核心词）

| 中文术语 | 英文标识 | 说明 |
|---|---|---|
| 一键成片（产品模式） | `product_montage` | 服务端唯一产品成片标识；客户端「产品成片」tab 提交此类型 |
| 分镜脚本成片 | `storyboard_montage` | 客户端「脚本成片」tab |
| 音乐卡点成片 | `montage_beat` | 服务端 `/montage/beat` |
| 智能混剪-镜头分割 | `montage/split` | 同步接口，无独立 task_type |
| 智能混剪-镜头拼接 | `montage_concat` | 成片队列 |
| 剪辑引擎渲染 | `editor_render` | 成片队列 |
| 自动字幕转写 | `transcribe` | 成片队列 |
| 视频去字幕 | `vsr_remove` / `vsr_detect` / `vsr_analyze` | 客户端队列 |
| 素材智能分析 | `material_analyze` | 素材队列 |

> ⚠️ 统一约定：客户端**不再使用 `video_montage` 作为 task_type**（服务端只认 `product_montage`）。

## 3. 前缀体系（三套队列 + API 分组）

| 队列 | 任务 ID 前缀 | 存储 | 格式 |
|---|---|---|---|
| 客户端队列 | `c_` | SQLite tasks.db | `c_` + uuid4[:10] |
| 素材队列 | `m_` | SQLite material_tasks.db | `m_` + uuid4[:10] |
| 成片队列 | （无前缀） | PostgreSQL scheduled_tasks | 整数 SERIAL |

task_type 格式：`<领域>_<动作>` 或 `<产品形态>_<动作>`，snake_case。
API 路由前缀分组：`/material` 素材库、`/tasks` 客户端队列、`/scheduled/tasks` 成片队列、`/montage` 混剪、`/editor` 剪辑、`/vsr /whisper /voxcpm /clip` 模型服务。
> ⚠️ API 前缀统一**不带 /api**（历史遗留 `/api/storyboard/scripts`、`/api/product-library` 逐步迁移）。

## 4. 品牌归一化 / 背景 / 用途规则（客户端已对接）

- 品牌标准名=中文（`罗技`），英文别名表显示 `罗技(Logitech)`；过滤支持 中文/英文/对照格式 三种输入。
- 型号归一化：占位词（型号/无/未知/N/A/-）置空，其余原样保留。
- 背景类型 `background_type` 枚举（全小写）：`white` / `black` / `solid` / `gradient` / **`green_screen`** / **`blue_screen`** / `transparent` / `scene`。
  （注意：绿幕/蓝幕带下划线 `green_screen`/`blue_screen`，不是 greenscreen/bluescreen。）
- 素材用途 `use_case`：`background` / `product` / `scene`；综合分 = 0.5×像素分 + 0.3×语义分 + 0.2×用途适配分。
- 归一化执行点：写入层（AI 分析入库）、读取层（list/search/distinct/schema）、过滤层（brand 参数）；存量经 `POST /material/backfill_brand` 回填。

## 5. 数据库命名（客户端不直接建表，仅联调参考）

表名：单数名词 snake_case，素材族 `material_` 开头；主键 `id`、外键 `<父表单数>_id`；时间字段 `created_at/updated_at/completed_at`；布尔字段小写；索引 `idx_<表>_<列>`。

## 6. 输出产物命名（客户端下载/落盘参考）

- 单一主产物统一 `final.mp4`（成片类）；`output.mp4` 仅编辑器渲染内部。
- 镜头片段一律 `<源名>_shot_<序号3位>.mp4`。
- 下载重命名：`montage_{task_id}.mp4`、`concat_{task_id}.mp4`、`editor_{task_id}.mp4`。

## 7. 中间资产/缓存命名

- 磁盘缓存：`<功能>_<标识>`（`caption_{role}.srt`、`placeholder_{md5_8}.png`）。
- 内存缓存：`_<名称>_cache` + 可选 `_<名称>_TTL`（`_dup_cache` + `_DUP_CACHE_TTL`）。
- 数据文件：`data/<领域>.json`（`templates_registry.json`、`luts.json`、`fonts.json`）。

---

## 附录A：客户端补充约定（规范未定义，客户端已形成惯例）

| 场景 | 约定 | 示例 |
|---|---|---|
| 页面类 | 后缀 `Page` | `VectorSearchPage`、`CompileVideoPage`、`StoryboardPage` |
| 分步视图 | 后缀 `View` | `Step1SplitView`、`Step2ConcatView` |
| 后台任务 | 后缀 `Worker`（继承 BaseWorker） | `ServerSplitWorker`、`TemplatePreviewWorker`、`ScriptListLoader` |
| UI 控件属性 | `<类型缩写>_<名称>`：btn_ / lbl_ / combo_ / spin_ / slider_ / input_ / list_ / chk_ / tbl_ | `btn_play`、`lbl_time`、`combo_script`、`slider_brightness` |
| 信号 | snake_case，名词/事件名 | `finished`、`error`、`stage`、`progress`、`analysis_ready` |
| 槽/回调 | `_on_<事件>`（私有） | `_on_script_changed`、`_on_merged_split_done` |
| 页面内部 worker 引用 | `self.worker` / `self.highlight_worker` 等业务名 | 混剪页 `worker`/`highlight_worker` |
| 混剪任务缓存 | `.runtime/montage_cache/<job_id>/`（manifest.json + splits/ + downloads/） | 方案二落地 |
| 布尔局部变量 | 同样加 `is_` / `has_` / `can_` 前缀 | `is_bg_used`、`is_local` |
| 任务提交 | `stc.create_task(task_type, ...)`，task_type 走 §2.2 表 | `product_montage` / `storyboard_montage` / `montage_concat` |

## 附录B：客户端不一致清单（2026-08-03 检查）

### 已修复
- task_type `video_montage` → `product_montage`（compile_video_page / scheduled_tasks_page 映射 / scheduled_task_client 注释）
- 背景类型 `greenscreen`/`bluescreen` → `green_screen`/`blue_screen`（vector_search_page 背景多选）
- 布尔命名 `_brand_fallback_done` → `_is_brand_fallback_done`、`_use_bg` → `is_bg_used`（vector_search_page）

### 待逐步收敛（历史代码，布尔变量未用 is_/has_/can_ 前缀）

| 文件 | 现名 | 建议 |
|---|---|---|
| gui_main.py | `_running` | `_is_running` |
| gui_main.py | `_pw_ready` / `_pw_install_running` / `_models_ready` | `_is_pw_ready` / `_is_pw_install_running` / `_is_models_ready` |
| gui_main.py | `_tray_quit` / `_tray_hint_shown` | `_is_tray_quit` / `_is_tray_hint_shown` |
| gui/dialogs.py | `_activated` | `_is_activated` |
| gui/live_clip_page.py | `saved` / `selected` / `_stop_requested` | `is_saved` / `is_selected` / `_is_stop_requested` |
| gui/my_knowledge_page.py | `_style_filter_updating` | `_is_style_filter_updating` |
| gui/product_library_page.py | `_should_stop` | `_is_should_stop` |
| gui/subtitle_removal_page_v14.py | `allow_rotation` | `is_rotation_allowed` |
| gui/threads.py | `running` | `is_running` |
| gui/transcription_page.py | `_edit_mode` | `_is_edit_mode` |
| gui/video_ai_rename_page.py | `_abort` | `_is_abort` |

> 以上为历史代码，改动涉及多处引用，按规范「逐步收敛」原则在后续相关改动中顺带重命名，避免一次性大改引入回归。
