# 一键成片 / 成片任务 审查清单

> 审查日期：2026-07-17（2026-07-18 多次纠正：素材评分结论 + 定时执行结论 + 脚本成片执行器）
> 审查范围：客户端 `utils/video_compiler.py` + `gui/compile_video_page.py` + 服务端 `/scheduled/tasks` 实测
> 当前状态：**客户端已全面转为 thin client（提交服务端执行）；脚本成片待服务端加执行器**。
>
> 关键结论：
> - 客户端「产品成片」「脚本成片」都已改为提交服务端 `/scheduled/tasks` 执行
> - 服务端 `video_montage`（产品成片）执行器**已实现**，会真实编译视频
> - 服务端 `script_montage`（脚本成片）执行器**未实现**，提交后一直 pending（详见文末）
> - 素材评分/向量检索在服务端已设计但数据未就绪（`quality_score` 列缺、pgvector 未启用）
> - 决策：**脚本成片等服务端加执行器**；客户端代码已就绪，无需再改

---

## 结论速览

当前流程要达到「抖音/小红书风格的电商带货短视频」（竖屏、快节奏、卖点突出、有字幕有配音有 BGM），**至少需修复下面 5 个 🔴 致命问题**。修完后可产出「能看」的基础成片；要达到「高质量」还需补 🟡 中等问题（转场、关键词高亮、封面差异化、语音对齐字幕）。

| 级别 | 数量 | 含义 |
|---|---|---|
| 🔴 致命 | 5 | 成片不可用 / 质量极差，必须修 |
| 🟡 中等 | 7 | 影响质量但勉强能用，建议修 |
| 🟢 轻微 | 6 | 优化项，不急 |

---

## 🔴 致命问题（必须修，否则成片不可用）

### S1. N 片分组「循环填充」逻辑错误，素材不足时每个视频只剩 1 张图

**位置**：`gui/compile_video_page.py:197-200`（`_split_groups` 的 else 分支）

```python
else:
    # 不足：循环填充到 n 组
    return [images[i % len(images):i % len(images) + 1] if not images[i % len(images):]
            else [images[i % len(images)]] for i in range(n)] if images else [[] for _ in range(n)]
```

**根因**：当 `len(images) < n`（如 3 张图、count=5），切片 `images[i%3 : i%3+1]` 永远只取 1 张，结果是 5 个视频每个只有 1 张图。一个 1 张图的"视频"等于一张静态图配 per_dur 秒。

**影响**：用户素材少时批量出片完全不可用。电商带货恰恰经常素材有限。

**修复方案**：改为「先把 images 循环扩展到足够长，再均分」：
```python
else:
    # 不足：循环扩展到每组至少 min_per_group 张，再均分
    min_per_group = 4
    need = n * min_per_group
    extended = (images * ((need // len(images)) + 1))[:need] if images else []
    if not extended:
        return [[] for _ in range(n)]
    k, m = divmod(len(extended), n)
    groups, start = [], 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        groups.append(extended[start:start + size]); start += size
    return groups
```
注意：循环扩展会让同一图重复出现——电商视频忌讳重复，可接受度视场景而定；或改为「素材不足时降低 count 并提示用户」。

---

### S2. 默认每张时长 3.0 秒，节奏严重过慢

**位置**：
- `utils/video_compiler.py:82`：`per_dur=3.0`（函数默认值）
- `gui/compile_video_page.py:333`：`self.spin_dur.setValue(3.0)`（UI 默认）
- `gui/compile_video_page.py:665`：`apply_params_and_run` 的回退默认 `per_dur=3.0`

**根因**：抖音/小红书电商短视频镜头切换普遍在 0.5–1.5 秒/张，3 秒/张等于放 PPT。

**影响**：默认出片节奏拖沓，第一印象差，留存率断崖下跌；定时任务默认就是慢节奏。

**修复方案**：
- `video_compiler.py:82` 默认改 `per_dur=1.2`
- `compile_video_page.py:333` 默认改 `setValue(1.2)`
- `compile_video_page.py:665` 回退默认改 `1.2`
- UI 上「每张时长」旁加提示「电商推荐 0.8–1.5 秒」

---

### S3. 字幕字号 FontSize=18，在 1080×1920 上几乎看不见

**位置**：`utils/video_compiler.py:120`
```python
style = "FontSize=18,Outline=2,Alignment=2,MarginV=60"
```

**根因**：1080 宽度下 FontSize=18 折合手机屏约 12–14px，移动环境根本看不清。

**影响**：卖点完全传达不到观众，等于没字幕。

**修复方案**：改为大字、加粗、加粗描边：
```python
style = "FontSize=52,Bold=1,Outline=3,Shadow=1,Alignment=2,MarginV=80,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
```
- 进一步可支持「关键词高亮」（卖点词变黄/红），需要把字幕按词分段着色（ASS 格式而非 SRT）。

---

### S4. 图片缩放用 pad 填黑边，横图竖屏观感极差

**位置**：`utils/video_compiler.py:102-103`
```python
vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
      f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p")
```

**根因**：`force_original_aspect_ratio=decrease` + `pad=black` 会按比例缩小后留**黑边**。电商主图多为方图/横图，竖屏视频会变成中间一条带 + 上下大黑边。

**影响**：大面积黑边直接判废，极度不专业。

**修复方案**（三选一，推荐第 1）：
1. **铺满裁切**（推荐，最简单）：`scale=...:force_original_aspect_ratio=increase,crop=W:H`，居中裁掉多余部分。
2. **模糊背景填充**（最美观）：原图居中 + 放大模糊的同图作背景铺满。
   ```
   split[a][b];[b]scale=W:H,boxblur=20:5[bg];[a]scale=W:H:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2
   ```
3. **加 UI 选项**：让用户选「裁切填充 / 模糊背景 / 黑边」三种模式。

---

### S5. 无配音时完全静音，无 BGM 支持

**位置**：`utils/video_compiler.py:152-157`，全文件无 `amix`/BGM 相关代码（已确认）

```python
if audio and os.path.isfile(audio):
    _run([ffmpeg, "-y", "-i", cur, "-i", audio, "-c:v", "copy", "-c:a", "aac", "-shortest", out_path])
else:
    _run([ffmpeg, "-y", "-i", cur, "-c", "copy", out_path])   # ← 无任何音频流
```

**根因**：电商带货视频即使没配音也必须有 BGM 营造节奏感，纯静音在抖音会被秒划走。代码完全无 BGM 输入参数。

**影响**：默认体验下视频无任何声音，平台分发权重低。

**修复方案**：
- `compile_video` 增加 `bgm=""` 参数
- UI「可选设置」加「背景音乐(可选)」浏览框
- 混音逻辑：有配音 + BGM 时用 `amix` 混合（配音音量大、BGM 小）；仅 BGM 时直接叠加；无音频流时把 BGM 作为唯一音轨
- ffmpeg 参考：`-i video -i bgm -filter_complex "[1:a]volume=0.3[bg];[bg]amix=inputs=1" -shortest`

---

## 🟡 中等问题（建议修）

### M1. 字幕按图片数均分，与文案句数/语音节奏脱节

**位置**：`utils/video_compiler.py:45-56`（`_split_text`）、`:59-68`（`_write_srt`）、`:118`（`n = len(images)`）

**根因**：`_write_srt(srt_path, text, n, per_dur)` 里 n 是图片数。文案 3 句、图片 8 张时，3 句塞前 3 段、后 5 段空字幕；文案 12 句、图片 8 张时整除取段会丢余数句。字幕时间轴 `start=i*per_dur` 按图片时长切，**完全不和 TTS 音频对齐**。

**影响**：字幕与语音/画面三者错位，专业感差。

**修复方案**：
- 有配音时：改用 forced alignment（按句切分音频时长，或用 whisper 类工具拿到时间戳）
- 无配音时：按句数（而非图片数）均分总时长，每句一条字幕

---

### M2. 有配音时 `-shortest` 会截断视频或音频

**位置**：`utils/video_compiler.py:154-155`

**根因**：`-shortest` 取较短流结束。虽前面按 `ad/n` 对齐了图片时长，但文案短/音频短/图片多时会互相截断。

**影响**：偶发末尾画面/声音突断。

**修复方案**：明确策略——音频为主时 `-shortest` OK；否则给视频补静音垫或循环 BGM 填满。

---

### M3. 图片之间硬切，无任何转场

**位置**：`utils/video_compiler.py:106-113`（concat demuxer），全文件无 `xfade`/`fade`

**根因**：concat demuxer 直接拼接，镜头间硬切。per_dur=3s 尚可，改成 0.8s 快节奏后硬切会很廉价。

**影响**：快节奏场景下观感粗糙。

**修复方案**：slideshow 阶段每张图前后加 0.15s `fade=in/out`，或用 `xfade` 转场（dissolve/fade）。

---

### M4. collect_images 不做最低分辨率/损坏校验，子目录顺序不可控

**位置**：`utils/video_compiler.py:71-78`

**根因**：
- 仅按扩展名过滤，损坏图/极小图（64×64 缩略图）会被收录
- `sorted(files)` 只排单目录内文件名；`os.walk` 跨子目录时 `_d`（line 74）没排序，子目录顺序不可控

**影响**：镜头顺序混乱、画面质量参差。

**修复方案**：
- 加最小宽高校验（ffprobe 读 stream 或 PIL 读 size，过滤 < 400×400 的）
- `_d.sort()` 排序子目录
- 提供手动排序接口（拖拽顺序或文件名前缀约定）

---

### M5. intro/cover 时长不透明、不可调

**位置**：`utils/video_compiler.py:136`（cover 固定 `-t 2`）、`:130`（intro 按原视频时长）

**根因**：封面固定 2 秒，快节奏视频里显得过长（电商开屏封面一般 0.5–1s）。用户不知道总时长会变多少。

**影响**：总时长不可预期，开篇拖沓。

**修复方案**：cover 时长做成参数（默认 1.0s）；UI 显示「预计总时长 = intro + cover + N×per_dur」。

---

### M6. N 片之间共用同一份 intro/cover/audio/subtitle，无法差异化

**位置**：`gui/compile_video_page.py:179-182`（`_compile_one` 用 `self.xxx`，循环里只换 group）

**根因**：批量出 5 个视频，5 个的开场/封面/配音/字幕完全一样。

**影响**：多片价值有限，矩阵号场景下平台可能判搬运。

**修复方案**：支持文案/封面列表（按 index 取）；至少 subtitle 按 group 切片。

---

### M7. SRT 序号在空段时跳跃

**位置**：`utils/video_compiler.py:62-66`

**根因**：序号用 `i+1`（数组下标），但空段 `continue` 跳过，导致序号不连续（如 1,2,5,7）。

**影响**：部分严格解析器/平台报警告。

**修复方案**：另维护一个 `seq` 计数器自增。

---

## 🟢 轻微问题（优化项）

### L1. ratio 下拉默认值依赖 dict 顺序（隐式契约）
**位置**：`gui/compile_video_page.py:338-339`
**建议**：显式 `setCurrentText("9:16")`，UI 标注「竖屏（抖音/小红书推荐）」。

### L2. CRF=23 + preset=veryfast，多次 re-encode 有代际损失
**位置**：`utils/video_compiler.py:113,123,131,137,148`
**建议**：slideshow + sub 烧录合并到一次 filter_complex；或 sub 阶段用软字幕。

### L3. concat 列表最后一行重复写末尾图（正确，无需修）
**位置**：`utils/video_compiler.py:108-110`（ffmpeg concat demuxer 正确用法）

### L4. 默认平台预测只对第一个成片做
**位置**：`gui/compile_video_page.py:778-789`
**建议**：多片时对每个成片都预测（或让用户选）。

### L5. TTS 文案与字幕文案共用同一个输入框
**位置**：`gui/compile_video_page.py:303-306`
**建议**：电商场景字幕宜精简、配音宜展开，应分开设两个输入框。

### L6. 远程素材匹配取 `commonpath` 可能过宽
**位置**：`gui/compile_video_page.py:107-112`
**建议**：commonpath 可能涵盖大量无关产品图，`collect_images` 会全收进来。可改为「取出现次数最多的目录」或「限定单产品子目录」。

---

## 关于「素材评分/相似度匹配」（已纠正：服务端有，但数据未就绪）

> ⚠ 本节为 2026-07-18 纠正版。此前版本误判为「无数据源」，实测服务端后纠正。

实测服务端（`http://192.168.111.30:8000`，基于 `/openapi.json` + 真实请求）发现：**评分/向量检索能力在服务端已实现，但当前部署实例的数据未就绪**。

### 服务端已实现的能力（设计完成）

| 端点 | 能力 | 设计状态 |
|---|---|---|
| `/material/search` | **CLIP 向量语义检索**（768维 pgvector cosine 相似度，结果含 `score` 降序） | ✅ 设计完成 |
| `/material/score` POST | **7 维画面质量评分**（质感/美感/构图/清晰度/主体突出/人物色彩/人物形象） | ✅ 设计完成 |
| `/material/batch_score` POST | 批量评分 | ✅ 设计完成 |
| `/material/analyze` POST | AI 场景描述分析（产 `scene_desc_primary`） | ✅ 设计完成 |
| `/material/schema` GET | 动态字段字典（客户端无需硬编码字段名） | ✅ 已生效 |

**关键认知纠正**：向量检索**本来就是服务端做的**（CLIP 编码 + pgvector），客户端只调 `/material/search`。`storyboard_page.py` 里的 `search_by_text` 是已废弃的客户端旧代码残留（死代码），不是"客户端在搞向量检索"。

### 当前部署实例的缺口（数据未就绪，非能力缺失）

| 现象 | 原因 | 实测证据 |
|---|---|---|
| `/material/search` 返回无 `score` 字段 | `vector_search.available: false`（pgvector 未启用） | schema 接口明确返回 available:false |
| `/material/score` GET 报错 | 数据库表缺 `quality_score` 列（迁移未跑） | `column "quality_score" does not exist` |
| `ai_confidence: null` | 素材未跑批量评分 | search 返回的 ai_confidence 全为 null |
| search 返回无 `path` 字段 | 服务端只暴露 id/filename/share_name/file_hash，不暴露本地路径 | 返回字段列表确认 |

### 客户端 `MaterialMatchWorker` 当前问题（待服务端就绪后修）

- **隐藏 bug**：不传 `query` 时服务端返回 400（query 必填），当前代码 brand/category 都有时就不传 query，会直接失败
- **过滤参数错配**：客户端传 `category`/`model`，但服务端返回字段无 `category`（只有 `product`），且这些过滤当前未实现（只 `brand` 生效）
- **path 取不到**：服务端不返回 path，当前 `r.get("path")` 永远空 → "无可用 path 字段"
- **未消费 score**：即便向量检索启用返回 score，客户端也没排序

### 服务端就绪后客户端改造点（待办）

服务端完成以下三项后，客户端改造即可生效：
1. 数据库迁移加 `quality_score` 列
2. 对素材跑一次 `/material/batch_score`
3. 启用 pgvector（`vector_search.available: true`）

客户端 `MaterialMatchWorker` 改造（届时做）：
- 传 `query`（产品 `selling_points` 卖点文本，必填）+ `brand` 过滤
- 消费返回的 `score` 降序排序，取 top N
- （可选）调 `/material/score` 补画面质量分，与相似度综合排序
- path 兜底：`share_name` + NAS 盘符映射（U:/V:/W:/X: 已挂载 `\\192.168.111.17`），或走 `/material/serve` 流式

---

## 服务端真实能力实测（2026-07-18 更新）

> ⚠ 本节为最新实测结论，覆盖了早期"定时任务不会执行"的错误判断。

### 定时任务 `/scheduled/tasks` —— CRUD 可用 + 部分类型有执行器

实测确认：**服务端定时任务会真实执行**（早期判断"仅存储不执行"是错的，源于测错了 task_type）。不同 task_type 的执行器覆盖情况：

| task_type | 实测状态（提交后 3-20 秒） | 执行器 |
|---|---|---|
| `video_montage`（产品成片） | `pending` → `running`(progress=30) → completed/failed | ✅ **有执行器**，会真实编译视频 |
| `script_montage`（脚本成片） | `pending` → 20 秒仍 `pending/progress=0` | ❌ **无执行器**，任务永不执行 |
| `compile_video`（早期误测） | 一直 pending | ❌ 无效 task_type |

- CRUD（增删改查）：✅ 全部可用
- 任务参数：服务端接受客户端任意扩展参数（16+ 字段全保留存储，无 422）
- `video_montage` 执行器会产出成片（`result.video_url`），但偶发 `error_msg:"视频编译失败"`（服务端实现质量问题）

### 服务端待就绪清单（已按实测更新）

| # | 待办 | 状态 | 阻塞的能力 |
|---|---|---|---|
| 1 | `script_montage` 执行器 | ❌ **未实现** | **脚本成片**（客户端已就绪，提交后一直 pending） |
| 2 | 数据库 `quality_score` 列迁移 | ❌ 未实现 | `/material/score` 评分（GET 报 column does not exist） |
| 3 | pgvector 启用（`vector_search.available`） | ❌ false | `/material/search` 向量相似度 score |
| 4 | 素材批量评分（`/material/batch_score`） | ❌ 未跑 | 评分数据落库（`ai_confidence` 全 null） |
| 5 | `video_montage` 成片质量 | ⚠️ 会执行但偶发失败 | 产品成片稳定性 |

### `script_montage` 执行器接口契约（给服务端开发对接用）

客户端脚本成片 tab 提交任务时，`POST /scheduled/tasks` 的 body：
```json
{
  "task_type": "script_montage",
  "title": "{topic}-{script_name}-脚本成片",
  "params": {
    "script_name": "脚本名",
    "script_path": "客户端 json 路径（服务端可能无法访问，仅供参考）",
    "topic": "脚本主题",
    "ratio": "9:16",
    "total_duration": 15,
    "shot_count": 3,
    "shots": [
      {
        "index": 1,
        "shot_type": "特写",
        "duration": 5,
        "sfx": "渐入",
        "visual": "画面描述",
        "narration": "旁白文案",
        "material_type": "local",
        "material_path": "素材绝对路径（服务端按此取素材）",
        "material_hash": "去重hash"
      }
    ],
    "predict_platform": "抖音",
    "autocheck": true
  },
  "schedule": null
}
```

**服务端执行器期望行为**（客户端假设）：
1. 按 `shots` 顺序，每镜头用 `material_path` 取素材文件（服务端 NAS 直连）
2. 按 `narration` 配文案（字幕/配音）、按 `duration` 控每镜时长
3. 按 `ratio` 输出对应画幅，拼接成片
4. 完成后 `result: {"video_url": "/output/xxx.mp4"}`，客户端凭此打开结果
5. 进度通过 `status`（pending→running→completed/failed）+ `progress`（0-100）反馈

**关键差异**（与 `video_montage` 的区别）：
- `video_montage`：服务端自主做素材匹配（客户端只传 products），全托管
- `script_montage`：客户端已指定每镜头的素材路径 + 文案 + 时长，服务端只负责按这张"镜头表"执行 ffmpeg，**不需要再做素材匹配**

客户端代码已就绪（`compile_video_page.py` 的 `_submit_script`），服务端实现 `script_montage` 执行器后自动生效，无需客户端再改。


---

## 最小可行修复路径（达到「能看」的电商视频）

按优先级，依次修复下面 5 个即可产出基础可用成片：

1. **S1**（N 片分组逻辑）——避免素材少时出单图废片
2. **S4**（图片填充改 crop）——消除黑边
3. **S3**（字幕字号 52+加粗）——卖点可见
4. **S5**（加 BGM 参数）——有节奏感
5. **S2**（默认节奏 1.2s）——快节奏

全部集中在 `utils/video_compiler.py` 和 `gui/compile_video_page.py` 两个文件，改动可控。

修完后要达到「高质量」（转场、关键词高亮、封面差异化、语音对齐字幕），再补 M1/M3/M6。

---

## 定时任务流程的额外注意点

定时任务复用上述同一套 `compile_video` 管线，因此上述所有质量问题在定时自动出片时同样存在，且因为是无人值守自动执行，**默认配置的影响被放大**。建议：
- 定时任务保存参数时，校验关键参数（per_dur 不应 > 2.0、必须填 BGM 或配音），不达标提示用户。
- 「添加为定时任务」弹窗里显示预计成片效果摘要（节奏、时长、是否有 BGM），让用户知道默认会出什么样的视频。
