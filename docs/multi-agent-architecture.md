# TinTin AI · 多智能体架构设计

## 架构概览

```
                        ┌─────────────────────┐
                        │    🧠 主控智能体      │
                        │   (Orchestrator)     │
                        │  接收用户意图→拆解→   │
                        │  分配→汇总→交付       │
                        └──────┬──────────────┘
               ┌───────────────┼───────────────┐
               │               │               │
        ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
        │ 📹 分析Agent │ │ ✂️ 混剪Agent│ │ ✍️ 文案Agent│
        │ 素材分析     │ │ 镜头分割   │ │ 脚本生成   │
        │ Whisper转写  │ │ 智能匹配   │ │ 飞书同步   │
        │ CLIP向量化   │ │ 拼接装配   │ │ 知识库     │
        │ 视觉识别     │ │ BGM/配音   │ │ 分镜创作   │
        └──────────────┘ └────────────┘ └────────────┘
               │               │               │
        ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
        │ 📊 运营Agent │ │ 🗣️ 数字人  │ │ 🔧 工具Agent│
        │ 数据看板     │ │ 口播合成   │ │ 封面/抠图   │
        │ 多平台发布   │ │ 表情驱动   │ │ OCR/去字幕  │
        │ 热点追踪     │ │ 声音克隆   │ │ 视频修复    │
        └──────────────┘ └────────────┘ └────────────┘
```

## Agent 通信协议

```python
# 主控 → 分析Agent
{
    "task": "analyze_material",
    "payload": {"video_path": "D:/素材/C0097.MP4", "hash": "d0e984397313a206"},
    "priority": 1
}

# 分析Agent → 主控
{
    "task_id": "xxx",
    "status": "done",
    "result": {"scenes": 8, "script": "245字", "brand": "罗技", "clip_vector": [0.12, -0.34, ...]}
}
```

## 优势

| 单体架构 | 多Agent |
|---------|---------|
| 一个进程崩全崩 | Agent独立隔离 |
| 串行等待 | 并行分析+混剪+文案同时跑 |
| 耦合紧，改一处影响全局 | 各自独立迭代 |
| 用户界面等所有结果 | 分析完一批就展示一批 |

## 实现方式

```python
# 主控智能体伪代码
class Orchestrator:
    def handle_user_intent(self, intent: str, files: list):
        if intent == "制作视频":
            # 并行分发
            analysis_task = delegate_task(goal="分析素材", agent="analysis_agent")
            script_task = delegate_task(goal="生成文案", agent="script_agent")
            
            # 等待依赖完成
            analysis_result = await analysis_task
            script_result = await script_task
            
            # 串联下一步
            montage_task = delegate_task(
                goal="智能混剪",
                agent="montage_agent",
                context=f"素材分析:{analysis_result} 文案:{script_result}"
            )
            return await montage_task
```

## Agent 清单

| Agent | 职责 | 依赖 |
|-------|------|------|
| `analysis_agent` | 素材入库、Whisper转写、CLIP向量化、视觉AI识别 | ffmpeg, Ollama, CLIP |
| `montage_agent` | 镜头分割、文案匹配、拼接装配、BGM/配音 | ffmpeg, PySceneDetect, TTS |
| `script_agent` | 脚本生成、飞书同步、知识库、分镜创作 | DeepSeek API |
| `ops_agent` | 数据看板、多平台发布、热点追踪、账号管理 | 平台API |
| `design_agent` | 封面制作、图像抠图、OCR、视频修复、数字人 | OpenCV, PaddleOCR |
| `orchestrator` | 意图理解、任务拆解、并行调度、结果汇总 | 全部 Agent |
