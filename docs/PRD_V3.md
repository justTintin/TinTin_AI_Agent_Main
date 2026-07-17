# PRD V3 — 后期需求规划

> 版本：v3.0 草案 | 日期：2026-07-17 | 状态：规划中

---

## 一、希区柯克镜头 & 特效镜头

### 1.1 目标

智能混剪增加电影级运镜效果，提升视频质感和专业度。

### 1.2 特效镜头类型

| 类型 | 效果 | 适用场景 |
|------|------|---------|
| 希区柯克变焦 (Dolly Zoom) | 主体不变，背景拉近/拉远 | 悬念、强调、转场 |
| 推拉镜头 (Push/Pull) | 画面徐徐推进或拉远 | 开场、产品展示 |
| 摇晃镜头 (Shake) | 画面震动 | 冲击感、动作场景 |
| 慢动作 (Slow Motion) | 逐帧插值降速 | 细节展示、情绪渲染 |
| 快速缩放 (Speed Ramp) | 变速 + 缩放组合 | 卡点、节奏变化 |
| 旋转过渡 (Spin) | 画面旋转切入 | 快节奏转场 |
| 镜像/翻转 (Flip) | 水平/垂直翻转过渡 | 对比、创意转场 |

### 1.3 技术方案

```
ffmpeg 滤镜链：
  zoompan  →  推拉/希区柯克
  minterpolate  →  慢动作
  rotate + zoompan  →  旋转缩放
  setpts/atempo  →  变速
```

### 1.4 智能匹配

根据画面内容自动推荐特效：
- 产品特写 → 慢动作 + 推近
- 人物出场 → 希区柯克
- 快节奏 BGM → 快速缩放
- 文字/字幕出现 → 弹入动画

---

## 二、剪映 (PR) 驱动 & 审美判断

### 2.1 目标

将 AI 生成的粗剪 XML/JSON 导出，驱动剪映进行精细化剪辑。剪辑时做审美判断。

### 2.2 导出格式

- 剪映支持通过 DRT (Draft) 文件导入工程
- 已有 `utils/jianying_exporter.py` 基础，需扩展
- 导出内容：时间轴、转场、滤镜、字幕、音频

### 2.3 审美判断模块

| 维度 | 判断标准 | 技术 |
|------|---------|------|
| 构图 | 三分法、主体居中比例 | `_score_clip()` 已有的主体突出分 |
| 色彩 | 色调统一性、饱和度 | cv2 色彩直方图分析 |
| 节奏 | BPM 与镜头切换卡点 | ffmpeg 提取 BPM，镜头时长对齐 |
| 连贯性 | 相邻镜头的色彩/亮度跳变 | 帧间差异检测 |
| 安全区 | 字幕/标题是否在安全区内 | OCR + 位置分析 |

### 2.4 剪映驱动流程

```
混剪粗剪 → 导出 DRT JSON
  → 剪映打开工程
  → AI 逐镜头审阅：
      构图建议、色彩调整建议、转场建议
  → 用户确认/修改
  → 导出成品
```

### 2.5 接口

| API | 描述 |
|-----|------|
| `POST /montage/export/jianying` | 导出剪映工程文件 |
| `POST /evaluate/aesthetics` | LLM 审美评价（构图/色彩/节奏） |
| `POST /evaluate/rhythm` | BPM 卡点对齐分析 |

---

## 三、一键成片模板 + 素材匹配

### 3.1 目标

提供预置视频模板，AI 根据模板结构从素材库中自动匹配素材。

### 3.2 模板结构

```json
{
  "name": "电商带货-30s",
  "duration": 30,
  "template": [
    {"type": "intro", "duration": 3, "tag": ["logo", "品牌"]},
    {"type": "hook", "duration": 5, "tag": ["产品特写", "痛点展示"]},
    {"type": "feature", "duration": 3, "tag": ["功能介绍", "卖点"]},
    {"type": "feature", "duration": 3, "tag": ["功能介绍", "卖点"]},
    {"type": "feature", "duration": 3, "tag": ["功能介绍", "卖点"]},
    {"type": "testimonial", "duration": 5, "tag": ["使用场景", "真人出镜"]},
    {"type": "cta", "duration": 5, "tag": ["价格", "促销"]},
    {"type": "outro", "duration": 3, "tag": ["logo", "结尾"]}
  ],
  "bgm": "upbeat_electronic",
  "transitions": "fade"
}
```

### 3.3 素材匹配

```
选择模板 → 解析所需 tag → CLIP 向量检索素材库
  → 每个 slot 匹配 top 5 候选
  → 评分 + 去重 → 自动填充
  → 用户可手动替换
```

### 3.4 预设模板

| 模板 | 时长 | 适用 |
|------|------|------|
| 电商带货-15s | 15s | 短视频信息流 |
| 电商带货-30s | 30s | 短视频信息流 |
| 电商带货-60s | 60s | 直播切片混剪 |
| 产品评测-60s | 60s | B 站/小红书 |
| 品牌故事-90s | 90s | 品牌宣传 |
| 活动促销-15s | 15s | 大促快节奏 |

### 3.5 接口

| API | 描述 |
|-----|------|
| `GET /montage/templates` | 获取模板列表 |
| `POST /montage/match` | 根据模板匹配素材 |
| `POST /montage/compile` | 一键编译成片 |

---

## 四、MG 动画整合

### 4.1 目标

将现有 MG 动画能力（Remotion）整合为一键成片流程。

### 4.2 当前状态

- `gui/mg_animation_page.py` — 已开发但暂时隐藏
- `utils/remotion_client.py` — Remotion 渲染客户端
- Remotion 工程位于 `studio/remotion/`

### 4.3 整合方案

```
输入文案/数据 → AI 生成 MG 脚本 (JSON)
  → 填充 Remotion 模板
  → 服务端 npx remotion render
  → 输出 MP4
  → 合并到主视频（混剪 + MG 动画片头/片尾/转场）
```

### 4.4 接口

| API | 描述 |
|-----|------|
| `POST /mg/generate` | 提交 MG 脚本生成渲染任务 |
| `GET /mg/status/{task_id}` | 查询渲染进度 |

---

## 五、垂类剪辑模板

### 5.1 电影解说

**模板结构**：
```
片头 (3s) → 开场悬念 (5s) → 剧情概述 (15s) 
→ 名场面 1 (10s) → 分析点评 (8s) → 名场面 2 (10s) 
→ 总结升华 (5s) → 片尾引导关注 (3s)
```

**AI 能力**：
- 自动识别电影名场面（高潮+转折）
- LLM 生成解说文案（悬念钩子 + 剧情 + 点评）
- TTS 配音（解说风格声音样本）
- 画面匹配解说文案时间轴

### 5.2 知识科普

**模板结构**：
```
问题引入 (5s) → 概念解释 (10s) → 案例演示 (10s) 
→ 数据支撑 (5s) → 实用技巧 (8s) → 总结 + 引导 (5s)
```

**AI 能力**：
- LLM 根据选题生成科普脚本
- 素材库中匹配知识类画面（产品/图表/示意图）
- 自动生成字幕 + 标注
- 字幕高亮关键词

### 5.3 通用模板引擎

所有垂类模板统一用 JSON 描述结构，引擎可扩展：

```json
{
  "category": "movie_review",
  "name": "电影解说-3min",
  "duration": 180,
  "segments": [...],
  "voice_profile": "解说_男声",
  "bgm_profile": "悬疑_紧张"
}
```

### 5.4 接口

| API | 描述 |
|-----|------|
| `POST /template/generate` | 根据模板类型 + 素材生成成片 |
| `GET /template/list` | 获取所有模板 |
| `POST /template/validate` | 校验用户自定义模板 |

---

## 六、优先级 & 依赖

| 优先级 | 功能 | 依赖 | 预估 |
|--------|------|------|------|
| P0 | 一键成片模板 + 素材匹配 | CLIP 向量检索已有 | 2 周 |
| P1 | 剪映导出增强 + 审美判断 | jianying_exporter 基础已有 | 3 周 |
| P1 | 电影解说模板 | LLM + TTS + 素材匹配 | 2 周 |
| P2 | 希区柯克 & 特效镜头 | ffmpeg 滤镜 | 1 周 |
| P2 | 知识科普模板 | 同上 | 1 周 |
| P2 | MG 动画整合 | Remotion 已有 | 1 周 |

---

## 七、接口汇总（服务端新增）

```
POST  /template/generate        一键成片
POST  /template/list            模板列表
POST  /montage/export/jianying  导出剪映工程
POST  /evaluate/aesthetics      审美评价
POST  /evaluate/rhythm          节奏/卡点分析
POST  /mg/generate              MG动画渲染
POST  /montage/match            素材匹配
POST  /montage/compile          编译成片
```
