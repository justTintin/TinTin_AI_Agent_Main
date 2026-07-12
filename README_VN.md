# DingDaGuai E-commerce Agent Matrix (Client-Server)

Dự án dùng cho mục đích học tập và nội bộ.

Hệ thống sử dụng **kiến trúc client-server**:
- **GUI Client (Windows)**: Ứng dụng PySide6 — xử lý giao diện người dùng, tiền xử lý media (ffmpeg) và điều phối các tác vụ AI qua API từ xa.
- **Compute Server (remote)**: Máy chủ AI hợp nhất — cung cấp dịch vụ Whisper (ASR), VoxCPM (TTS), Ollama (vision LLM) và CLIP (vector embedding).
- **ComfyUI Server (remote)**: Tạo hình ảnh AI.
- **DeepSeek API (cloud)**: Tạo văn bản / nội dung quảng cáo.

> **Lưu ý**: Flask web backend cũ đã được loại bỏ. Tất cả AI inference hiện được xử lý qua compute server từ xa.

## 1. GUI Client (Windows)

Chạy:
- `run_gui_integrated.bat`

Hoặc:

```powershell
.\python_embeded\python.exe studio\gui_main.py
```

Cài Playwright browser:

```powershell
.\python_embeded\python.exe -m playwright install chromium
```

Cấu hình AI (local):
- Ví dụ: `studio/config/ai_config.json.example`
- File thật: `studio/config/ai_config.json`

```powershell
copy .\studio\config\ai_config.json.example .\studio\config\ai_config.json
```

Cấu hình **compute server URL** trong `ai_config.json`:
```json
{
  "compute_server_url": "http://<your-server-ip>:8000",
  "comfyui_addr": "http://<your-comfyui-ip>:8188",
  "llm_api_key": "sk-xxx"
}
```

Log & temp:
- `studio/.runtime/logs/app.log`
- `studio/.runtime/tmp/`

## 2. Kiến trúc dịch vụ AI

| Dịch vụ | Vai trò | Giao thức | Trường cấu hình |
|---------|---------|-----------|-----------------|
| **Compute Server** | Whisper ASR + VoxCPM TTS + Ollama Vision + CLIP Embedding | HTTP REST | `compute_server_url` |
| **ComfyUI** | Tạo hình ảnh AI | HTTP | `comfyui_addr` |
| **DeepSeek API** | LLM tạo nội dung | HTTP | `llm_api_url` |

### Xử lý cục bộ (vẫn chạy trên client)
- **VSR** (xóa phụ đề video)
- **rembg** (xóa nền)
- **PaddleOCR** (nhận dạng văn bản)
- **ffmpeg** (trích xuất và xử lý media)
