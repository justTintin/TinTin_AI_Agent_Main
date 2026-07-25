# ComfyUI 工作流即 API — 集成文档

> 本文档定义 ComfyUI 工作流从调试到发布的完整生命周期，以及客户端如何发现和调用已发布的工作流应用。客户端开发者可据此文档独立完成对接。

## 1. 工作流生命周期

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  ① 画布调试  │ ──→ │  ② 发布应用  │ ──→ │  ③ 客户端调用 │
│             │     │             │     │             │
│ 通过 IP 访问 │     │ 导出蓝图 JSON │     │ 发现 → 填参  │
│ ComfyUI Web │     │ + 定义 schema │     │ → 执行 → 结果│
│ Canvas 调试  │     │ 注册到 registry│    │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

### ① 画布调试

开发者通过浏览器访问 ComfyUI Web UI（`http://<comfyui_ip>:8188`），在节点画布上：
- 搭建工作流（选择节点、连线、配置参数）
- 测试运行，调整参数直到效果满意
- 确认工作流可正常运行

### ② 发布为应用

调试完成后，将工作流发布为一个"应用"：

1. **导出蓝图** — 从 ComfyUI 导出 API 格式的 JSON（包含节点 ID、class_type、inputs）
2. **定义 Schema** — 声明该应用的输入参数和输出结果
3. **注册** — 将蓝图 + schema 写入注册表（`registry.yaml`）

发布后的应用具有：唯一 ID、名称、分类、输入参数定义、输出定义、以及参数到节点的映射关系。

### ③ 客户端调用

客户端通过 API 发现已发布的应用，根据 schema 构建调用参数，提交执行，轮询获取结果。

---

## 2. 系统架构

```
┌───────────────────────────────────────────────────────┐
│                 ComfyUI 实例 (远程)                     │
│                                                        │
│  原生 API:                                             │
│    GET  /models              → 模型类型列表             │
│    GET  /models/{folder}     → 指定类型模型文件列表      │
│    GET  /object_info         → 所有节点定义              │
│    GET  /system_stats        → 系统信息(版本/GPU/显存)   │
│    GET  /queue               → 任务队列状态              │
│    POST /prompt              → 提交工作流执行            │
│    GET  /history/{prompt_id} → 查询执行结果              │
│    POST /upload/image        → 上传图片/文件             │
│    GET  /view                → 获取生成的图片/视频        │
│    POST /interrupt           → 中断当前任务              │
│    POST /free                → 释放显存                  │
└──────────────────────┬────────────────────────────────┘
                       │ HTTP (直连, 地址: comfyui_addr)
                       ▼
┌───────────────────────────────────────────────────────┐
│              应用注册层 (Workflow Registry)              │
│                                                        │
│  registry.yaml — 所有已发布应用的注册表                  │
│                                                        │
│  API 端点:                                             │
│    GET  /apps              → 应用列表(摘要)             │
│    GET  /apps/{id}         → 应用详情(完整 schema)      │
│    POST /apps/{id}/run     → 执行应用(传入参数)         │
│    GET  /apps/{id}/status/{prompt_id} → 执行状态/结果   │
│                                                        │
│  同时代理 ComfyUI 基础能力:                             │
│    GET  /models              → 模型列表(透传 ComfyUI)   │
│    GET  /system_stats        → 系统信息(透传 ComfyUI)   │
└──────────────────────┬────────────────────────────────┘
                       │
                       ▼
┌───────────────────────────────────────────────────────┐
│                      客户端                             │
│                                                        │
│  Studio (Qt 桌面端) — 直连，无 CORS 限制               │
│  Dashboard (Web 前端) — 直连需 CORS 或经 Server 代理    │
│                                                        │
│  调用流程:                                              │
│  1. GET /apps → 拿到可用应用列表                        │
│  2. GET /apps/{id} → 拿到输入 schema                   │
│  3. 根据 schema 构建 UI / 自动填参                      │
│  4. 如有文件输入 → POST /upload/image 上传              │
│  5. POST /apps/{id}/run → 提交执行，拿到 prompt_id      │
│  6. GET /apps/{id}/status/{prompt_id} → 轮询直到完成    │
│  7. 从结果中获取生成的图片/视频 URL                      │
└───────────────────────────────────────────────────────┘
```

---

## 3. 应用注册表 (registry.yaml)

文件位置：`comfy/blueprints/registry.yaml`（或应用注册层可配置的路径）

### 格式定义

```yaml
apps:
  - id: string              # 唯一标识，如 "text-to-image-flux"
    name: string            # 显示名称，如 "文生图 (Flux)"
    description: string     # 简短描述
    category: string        # 分类: text-to-image | image-edit | video | audio | utility
    version: string         # 版本号，如 "1.0"
    blueprint: string       # 蓝图 JSON 文件名（相对于 blueprints 目录）

    inputs:                 # 输入参数列表
      - key: string         # 参数名（客户端用此 key 传值）
        type: string        # 类型: string | int | float | bool | file | enum
        required: bool      # 是否必填
        default: any        # 默认值（可选）
        label: string       # 显示标签
        description: string # 参数说明（可选）
        accept: string      # type=file 时: image | audio | video（可选）
        options: list       # type=enum 时的可选值（可选）
        min: number         # type=int/float 时的最小值（可选）
        max: number         # type=int/float 时的最大值（可选）

    outputs:                # 输出结果列表
      - key: string         # 输出标识
        type: string        # 类型: image | video | audio | text | json
        label: string       # 显示标签

    node_map:               # 参数到蓝图节点的映射
      <input_key>:          # 对应 inputs 中的 key
        node: string        # 蓝图中的节点 ID
        field: string       # 该节点的输入字段名
```

### 示例

```yaml
apps:
  - id: digital-human
    name: 数字人
    description: 上传人物图片和语音，生成数字人说视频
    category: video
    version: "1.0"
    blueprint: digital-human-api.json

    inputs:
      - key: image
        type: file
        accept: image
        required: true
        label: 人物图片
      - key: audio
        type: file
        accept: audio
        required: true
        label: 语音文件
      - key: resolution
        type: enum
        required: false
        default: "720p"
        options: ["480p", "720p", "1080p"]
        label: 分辨率

    outputs:
      - key: video
        type: video
        label: 生成视频

    node_map:
      image: {node: "284", field: "image"}
      audio: {node: "311", field: "audio"}
      resolution: {node: "285", field: "resolution"}

  - id: text-to-image-flux
    name: 文生图 (Flux)
    description: 使用 Flux 模型从文字描述生成图片
    category: text-to-image
    version: "1.0"
    blueprint: text-to-image-flux.json

    inputs:
      - key: prompt
        type: string
        required: true
        label: 提示词
      - key: width
        type: int
        default: 1024
        min: 512
        max: 2048
        label: 宽度
      - key: height
        type: int
        default: 1024
        min: 512
        max: 2048
        label: 高度
      - key: steps
        type: int
        default: 20
        min: 1
        max: 50
        label: 采样步数
      - key: seed
        type: int
        default: -1
        label: 随机种子 (-1 为随机)

    outputs:
      - key: image
        type: image
        label: 生成图片

    node_map:
      prompt: {node: "57", field: "text"}
      width: {node: "58", field: "width"}
      height: {node: "58", field: "height"}
      steps: {node: "59", field: "steps"}
      seed: {node: "60", field: "seed"}
```

---

## 4. API 接口定义

### 4.1 应用发现

#### `GET /apps` — 获取已发布应用列表

**响应:**
```json
{
  "apps": [
    {
      "id": "text-to-image-flux",
      "name": "文生图 (Flux)",
      "description": "使用 Flux 模型从文字描述生成图片",
      "category": "text-to-image",
      "version": "1.0",
      "input_count": 5,
      "output_count": 1
    },
    {
      "id": "digital-human",
      "name": "数字人",
      "description": "上传人物图片和语音，生成数字人说视频",
      "category": "video",
      "version": "1.0",
      "input_count": 3,
      "output_count": 1
    }
  ],
  "categories": ["text-to-image", "video"]
}
```

#### `GET /apps/{id}` — 获取应用详情

**响应:**
```json
{
  "id": "digital-human",
  "name": "数字人",
  "description": "上传人物图片和语音，生成数字人说视频",
  "category": "video",
  "version": "1.0",
  "inputs": [
    {"key": "image", "type": "file", "accept": "image", "required": true, "label": "人物图片"},
    {"key": "audio", "type": "file", "accept": "audio", "required": true, "label": "语音文件"},
    {"key": "resolution", "type": "enum", "required": false, "default": "720p", "options": ["480p", "720p", "1080p"], "label": "分辨率"}
  ],
  "outputs": [
    {"key": "video", "type": "video", "label": "生成视频"}
  ]
}
```

### 4.2 应用执行

#### `POST /apps/{id}/run` — 执行应用

**请求体:**
```json
{
  "params": {
    "image": "uploaded_filename.png",
    "audio": "uploaded_filename.wav",
    "resolution": "720p"
  }
}
```

> 文件类型参数需先通过 `POST /upload/image` 上传，拿到文件名后传入。

**响应:**
```json
{
  "prompt_id": "xxxx-xxxx-xxxx",
  "status": "queued"
}
```

#### `GET /apps/{id}/status/{prompt_id}` — 查询执行状态

**响应（执行中）:**
```json
{
  "prompt_id": "xxxx-xxxx-xxxx",
  "status": "running",
  "progress": 45
}
```

**响应（完成）:**
```json
{
  "prompt_id": "xxxx-xxxx-xxxx",
  "status": "completed",
  "outputs": {
    "video": {
      "filename": "output_001.mp4",
      "type": "video",
      "url": "/view?filename=output_001.mp4&type=output"
    }
  }
}
```

**响应（失败）:**
```json
{
  "prompt_id": "xxxx-xxxx-xxxx",
  "status": "failed",
  "error": "CUDA out of memory"
}
```

### 4.3 ComfyUI 基础能力（透传）

#### `GET /models` — 模型列表

透传 ComfyUI 的 `/models` + `/models/{folder}`，返回:
```json
{
  "checkpoints": ["flux1-dev.safetensors", "sd_xl_base_1.0.safetensors"],
  "loras": ["detail_enhancer.safetensors"],
  "vae": ["ae.safetensors"],
  "controlnet": ["control_v11p_sd15_canny.pth"]
}
```

#### `GET /system_stats` — 系统信息

透传 ComfyUI 的 `/system_stats`，返回版本、GPU、显存等信息。

### 4.4 文件操作（透传）

#### `POST /upload/image` — 上传文件

multipart/form-data，字段名 `image`。返回 `{"name": "uploaded_filename.png"}`。

#### `GET /view?filename=xxx&type=output` — 获取生成结果

返回图片/视频二进制数据。

---

## 5. 客户端调用流程（完整示例）

以"数字人"应用为例：

```python
# 1. 发现可用应用
apps = GET http://<addr>/apps
# → [{"id": "digital-human", "name": "数字人", ...}, ...]

# 2. 获取应用详情和 schema
detail = GET http://<addr>/apps/digital-human
# → inputs: [image(file), audio(file), resolution(enum)]

# 3. 上传文件
img_result = POST http://<addr>/upload/image  (multipart: image=人物.png)
# → {"name": "人物_abc123.png"}

audio_result = POST http://<addr>/upload/image  (multipart: audio=语音.wav)
# → {"name": "语音_def456.wav"}

# 4. 执行应用
run_result = POST http://<addr>/apps/digital-human/run
  body: {"params": {"image": "人物_abc123.png", "audio": "语音_def456.wav", "resolution": "720p"}}
# → {"prompt_id": "xxx-yyy-zzz", "status": "queued"}

# 5. 轮询状态
while True:
    status = GET http://<addr>/apps/digital-human/status/xxx-yyy-zzz
    if status.status == "completed":
        break
    if status.status == "failed":
        raise Error(status.error)
    sleep(2)

# 6. 获取结果
video_url = status.outputs.video.url
# → "/view?filename=output_001.mp4&type=output"
video_data = GET http://<addr>/view?filename=output_001.mp4&type=output
```

---

## 6. 客户端开发指南

### 6.1 comfyui_client.py 需要实现的函数

```python
class ComfyUIClient:
    def __init__(self, addr: str):
        """addr: ComfyUI 或应用注册层的地址"""
        self.addr = addr.rstrip("/")

    # ── 应用发现 ──

    def list_apps(self) -> list[dict]:
        """获取已发布应用列表"""
        # GET /apps

    def get_app(self, app_id: str) -> dict:
        """获取应用详情（含完整 input/output schema）"""
        # GET /apps/{app_id}

    # ── 应用执行 ──

    def upload_file(self, file_path: str) -> str:
        """上传文件到 ComfyUI，返回服务端文件名"""
        # POST /upload/image

    def run_app(self, app_id: str, params: dict) -> str:
        """执行应用，返回 prompt_id"""
        # POST /apps/{app_id}/run

    def get_status(self, app_id: str, prompt_id: str) -> dict:
        """查询执行状态"""
        # GET /apps/{app_id}/status/{prompt_id}

    def wait_for_result(self, app_id: str, prompt_id: str, interval=2, timeout=600) -> dict:
        """轮询等待执行完成，返回最终结果"""

    def download_output(self, filename: str, file_type="output") -> bytes:
        """下载生成的文件"""
        # GET /view?filename=xxx&type=output

    # ── ComfyUI 基础信息 ──

    def get_models(self) -> dict:
        """获取所有模型类型及文件列表"""
        # GET /models

    def get_system_stats(self) -> dict:
        """获取系统信息（版本、GPU、显存）"""
        # GET /system_stats

    def is_alive(self) -> bool:
        """检查 ComfyUI 是否在线"""
        # GET /system_stats, 200 = alive
```

### 6.2 UI 构建指南

根据 `get_app()` 返回的 schema 动态构建 UI：

| input type | UI 组件 |
|---|---|
| `string` | 文本输入框 |
| `int` / `float` | 数字输入框（有 min/max 时用滑块） |
| `bool` | 开关/复选框 |
| `file` (accept=image) | 图片选择器/拖放区 |
| `file` (accept=audio) | 音频选择器/录音按钮 |
| `file` (accept=video) | 视频选择器 |
| `enum` | 下拉选择框 |

根据 output type 展示结果：

| output type | 展示方式 |
|---|---|
| `image` | 图片预览 |
| `video` | 视频播放器 |
| `audio` | 音频播放器 |
| `text` | 文本显示 |

### 6.3 错误处理

- ComfyUI 不在线 → 提示用户检查地址或服务状态
- 文件上传失败 → 检查文件大小和格式
- 执行失败 → 显示 error 信息（通常是显存不足或节点错误）
- 超时 → 长时间轮询无结果，提示用户检查 ComfyUI 队列

---

## 7. 部署选择

应用注册层可部署为以下任一形式：

| 方式 | 优点 | 缺点 |
|---|---|---|
| **ComfyUI 自定义节点** | 与 ComfyUI 同进程，无跨服务调用 | 需要修改 ComfyUI 环境 |
| **独立微服务** | 独立部署，不侵入 ComfyUI | 多一个服务要管理 |
| **客户端 Server 模块** | 复用现有 Server 基础设施 | Server 需要能访问 registry.yaml |

无论哪种部署方式，API 接口定义（第 4 节）保持不变，客户端代码无需修改。

---

## 8. 发布工作流的操作流程

1. 在 ComfyUI Web Canvas 上调试好工作流
2. 导出 API 格式 JSON（ComfyUI → Developer API 菜单 → Save API Format）
3. 将 JSON 文件放入 `comfy/blueprints/` 目录
4. 在 `registry.yaml` 中添加条目：定义 id、name、inputs、outputs、node_map
5. 应用注册层自动加载新条目（或手动触发 reload）
6. 客户端通过 `GET /apps` 即可发现新应用
