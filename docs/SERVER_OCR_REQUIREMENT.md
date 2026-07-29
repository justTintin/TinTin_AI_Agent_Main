# 服务端 OCR 接口说明（客户端对接）

> 状态：**已对接完成**（2026-07-29）。
> 客户端 OCR 已从本地 PaddleOCR 迁移至服务端 `POST /material/ocr`，服务端返回带坐标。

## 接口

`POST /material/ocr`

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `file` | body (multipart) | binary | 图片字节（与 material_id/file_hash 三选一） |
| `material_id` | query | int | 素材库内素材 ID |
| `file_hash` | query | string | 文件哈希 |

## 响应（OCRResponse / OCRLine）

服务端已为 `/material/ocr` 声明 `OCRResponse`+`OCRLine` 响应模型，OpenAPI 的 200 响应完整列出字段：

```json
{
  "filename": "xxx.jpg",
  "text": "整图所有文字拼接",
  "lines": [
    {
      "text": "某行文字",
      "confidence": 0.99,
      "box": [184, 61, 611, 140],
      "box_rel": [0.23, 0.0762, 0.7638, 0.175]
    }
  ],
  "total": 12
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| text | string | 该行文字 |
| confidence | number | 置信度 |
| box | int[4] \| null | 像素坐标 `[x1,y1,x2,y2]`（左上+右下），相对原图 |
| box_rel | float[4] \| null | 归一化坐标（0-1） |

## 客户端如何使用

### 整图识别
直接上传图片 → 服务端返回带 box 的 lines。

### 区域/选区识别（客户端裁剪）
服务端**请求参数不含 box**（只做整图 OCR）。客户端需要区域识别时：
- **客户端先按 box 裁剪图片**（`ocr_image_crop`）→ 上传裁剪图 → 服务端对裁剪图整图 OCR。
- 适用于：图片文件夹选区测试、视频帧框选识别。

### 关键词空间定位（用响应 box）
客户端 `extract_value_for_key(key, lines)` 用每行的 `box=[x1,y1,x2,y2]` 做"关键词所在块右边/下方最近块"的空间定位（如"型号: MX-3" → 取出 "MX-3"）。
- 解析顺序：优先 `box`（服务端格式 `[x1,y1,x2,y2]`），回退 `poly`（旧格式 `[[x,y],...]`）。
- 无坐标时降级为"同块去掉关键词后的剩余文本"。

## 客户端用法清单

| 场景 | 客户端动作 | 服务端接口 |
|------|-----------|-----------|
| 图片文件夹批量 OCR | 逐张读本地文件 → 上传 | `POST /material/ocr` (file) |
| 选区测试识别 | 客户端按 box 裁剪 → 上传裁剪图 | `POST /material/ocr` (file) |
| 视频帧 OCR | cv2 抽帧 → 按 box 裁剪 → 逐帧上传 | `POST /material/ocr` (file) |

## 连通性检测
客户端用 `GET /material/status`（HTTP 200）判断 OCR 服务端在线。
