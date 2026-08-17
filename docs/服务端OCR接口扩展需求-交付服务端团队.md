# 服务端 OCR 接口扩展需求（客户端轻量化改造配套）

> 版本：v1.0 | 交付对象：服务端团队 | 关联：客户端 PaddleOCR 服务端化改造
>
> 背景：客户端正在把本地 PaddleOCR（`apps/PaddleOCR`，约 9.5GB）迁到服务端执行，以实现客户端轻量化。现有 `POST /material/ocr` 仅支持**单张图片**识别，无法覆盖客户端的两个 OCR 功能页。需服务端新增以下端点。
>
> 参考现有实现：服务端已有 `POST /vsr/remove`（异步任务队列 + 下载）模式，本需求的异步端点请沿用同一模式。

---

## 一、需求总览

客户端有两个 OCR 功能页，对应三类能力，需服务端覆盖：

| 客户端功能页 | 能力 | 建议端点 | 模式 |
|-------------|------|---------|------|
| 视频 OCR（框选扫描） | 视频逐帧 OCR + ROI 框选 + 数字过滤 + 导出 CSV | `POST /ocr/video` | 异步任务 |
| 图片文件夹批量 OCR | 整目录图片 OCR + 关键词定位提取 + 导出 CSV/txt | `POST /ocr/batch` | 异步任务 |
| 选区 OCR 测试（批量页内） | 单图 ROI 裁剪 OCR，返回文本 | `POST /ocr/image` | 同步 |

现有 `POST /material/ocr`（单图、整图、返回 text）可保留；`/ocr/image` 是其**带 ROI 裁剪**的增强版。

---

## 二、接口定义

### 2.1 视频 OCR `POST /ocr/video`（异步任务）

上传视频，服务端逐帧抽样 OCR，返回 CSV 结果文件。

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|:----:|------|------|
| file | body(multipart) | binary | ✅ | — | 视频文件（mp4/avi 等） |
| ymin | form | int | ❌ | 0 | 框选区域上边界（像素） |
| ymax | form | int | ❌ | 0 | 框选区域下边界 |
| xmin | form | int | ❌ | 0 | 框选区域左边界 |
| xmax | form | int | ❌ | 0 | 框选区域右边界 |
| sample_interval | form | int | ❌ | 5 | 每 N 帧取 1 帧做 OCR |
| filter_mode | form | string | ❌ | `all` | `all`=保留全部文本；`numeric`=仅提取数字 |

> 框选坐标约定与 VSR 一致：`(ymin, ymax, xmin, xmax)`；四个都为 0 时表示整帧识别。

**响应（提交成功）**：
```json
{ "task_id": "xxxx-xxxx", "status": "pending" }
```

**轮询**：`GET /tasks/unified/{task_id}`

**任务完成后 result 字段**：
```json
{ "filename": "video_ocr_xxxx.csv" }
```

**下载结果**：`GET /ocr/download/{filename}` → `Content-Type: text/csv`，CSV 二进制。

**CSV 格式约定**（UTF-8 BOM，`utf-8-sig`，表头固定）：

| 列 | 说明 |
|----|------|
| 帧号 | 原始帧序号（1-based） |
| 时间戳 | `HH:MM:SS.mmm` |
| 原始识别文本 | 该帧 ROI 内识别到的完整文本 |
| 提取数值(温度/数字) | `filter_mode=numeric` 时提取的数字串；`all` 时等于原始文本 |
| 置信度 | 识别置信度均值（0~1，4 位小数） |

**服务端处理逻辑**（对齐客户端原 `apps/PaddleOCR/video_ocr_backend.py`）：
1. 打开视频，读取总帧数与 FPS
2. 每 `sample_interval` 帧：按 `(ymin,ymax,xmin,xmax)` 裁剪 ROI（越界则裁剪到画面内；区域无效则用整帧）
3. 对 ROI 做 OCR，拼接 `rec_texts`，计算 `rec_scores` 均值
4. `filter_mode=numeric` 时用正则 `[-+]?\d*\.\d+|\d+` 提取数字
5. 仅有文本的帧写入结果；进度可写入任务 log 供客户端展示

---

### 2.2 图片文件夹批量 OCR `POST /ocr/batch`（异步任务）

上传**图片压缩包（zip）**，服务端解压后逐张 OCR，按关键词定位并提取值，返回 CSV/txt。

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|:----:|------|------|
| file | body(multipart) | binary | ✅ | — | zip 压缩包（内含 jpg/jpeg/png/bmp/webp/tiff） |
| key | form | string | ✅ | — | 定位关键词（锚点文本），用于提取其右侧/下方的值 |
| output_format | form | string | ❌ | `csv` | `csv` 或 `txt` |

**响应（提交成功）**：
```json
{ "task_id": "xxxx-xxxx", "status": "pending" }
```

**轮询**：`GET /tasks/unified/{task_id}`

**任务完成后 result 字段**：
```json
{ "filename": "batch_ocr_xxxx.csv" }
```

**下载结果**：`GET /ocr/download/{filename}` → CSV/txt 二进制。

**CSV 格式约定**（UTF-8 BOM，表头固定）：

| 列 | 说明 |
|----|------|
| 图片名称 | 图片文件名 |
| 提取值 ({key}) | 依据关键词定位到的值（未定位到为空） |
| 包含关键词文本块 | 含关键词的原始文本块 |
| 文件完整路径 | 原客户端侧完整路径（服务端可回传 zip 内相对路径） |

**txt 格式**：每行 `图片名称: 提取值`。

**关键词定位提取逻辑**（对齐客户端原 `image_folder_ocr_backend.py` 的 `extract_value_for_key`，服务端需完整复刻）：
1. 对每张图整图 OCR，得到 `rec_texts` 与 `dt_polys`
2. 归一化（去空格/标点/小写）后查找包含 `key` 的文本块
3. 先从该块内剔除 key 本身，若剩余非空即为提取值
4. 否则按空间位置找相邻块：**优先右侧同行**（块中心 y 接近且 xmin > key 中心 x），其次**下方同列**（ymin > key 中心 y 且中心 x 接近）
5. 对候选值去除前导分隔符（`:`、`：`、`-`、`=` 等）与尾随「复制/copy」

---

### 2.3 单图选区 OCR `POST /ocr/image`（同步）

单张图片 OCR，可选 ROI 裁剪，同步返回识别文本。用于批量页的「测试识别选区」按钮。

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|:----:|------|------|
| file | body(multipart) | binary | ✅ | — | 图片（png/jpg 等） |
| ymin/ymax/xmin/xmax | form | int | ❌ | 0 | 可选 ROI；全 0 表示整图 |

**响应**：
```json
{ "text": "识别到的完整文本" }
```

> 说明：现有 `POST /material/ocr` 不带裁剪；本端点 = 其增强版。若服务端倾向收敛，也可直接为 `/material/ocr` 增加这 4 个可选裁剪参数，客户端改用同一端点即可（二选一，需与客户端约定一致）。

---

## 三、通用约定

### 3.1 任务队列与状态

- 异步端点（`/ocr/video`、`/ocr/batch`）沿用服务端现有任务队列与统一查询 `GET /tasks/unified/{task_id}`
- 状态枚举沿用现有：`pending / running / completed / failed`
- 失败时 `error_msg` 给出可读原因

### 3.2 文件上传与大小

- 视频 OCR：单个视频，建议限制 ≤ 2GB（或按服务端 nginx `client_max_body_size`）
- 批量 OCR：zip 压缩包，建议限制 ≤ 1GB、解压后图片数 ≤ 5000 张；超出时返回明确错误

### 3.3 结果文件清理

- 下载端点 `GET /ocr/download/{filename}` 返回后建议保留一定时长（如 1 小时）再清理，避免客户端下载失败无法重试

### 3.4 模型与并发

- 服务端复用现有 PaddleOCR 推理环境；OCR 模型权重放服务端统一目录，**不随客户端分发**
- 并发用信号量限流，避免多任务同时加载模型占满显存

---

## 四、客户端已完成的配套改造（供联调参考）

客户端侧（本次已改）：
- `studio/utils/ocr_client.py` 新增 `video_ocr_remote()` / `image_folder_ocr_remote()` / `ocr_image_roi()`，按本文档调用服务端
- `studio/gui/video_ocr_page.py`、`studio/gui/image_folder_ocr_page.py` 改为走服务端（不再调用本地 PaddleOCR）
- 客户端批量 OCR 会先在本地把所选文件夹打包为 zip 再上传
- `compute_server_url`（`ai_config.json`）作为 OCR 服务地址来源

联调时请确保上述端点路径、参数名、响应字段与本文档一致；如有出入，以服务端 OpenAPI（`/openapi.json`）为准并同步客户端。
