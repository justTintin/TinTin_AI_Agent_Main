# DingDaGuai E-commerce Agent Matrix (Client-Server)

This project is for learning and internal use only.

The system uses a **client-server architecture**:
- **GUI Client (Windows)**: PySide6 desktop app — handles UI, media preprocessing (ffmpeg), and orchestrates AI tasks via remote APIs.
- **Compute Server (remote)**: Unified AI inference server — provides Whisper (ASR), VoxCPM (TTS), Ollama (vision LLM), and CLIP (vector embedding) services.
- **ComfyUI Server (remote)**: AI image generation.
- **DeepSeek API (cloud)**: Text generation / copywriting.

> **Note**: The old Flask web backend has been removed. All AI inference now goes through the remote compute server.

## 1. GUI Client (Windows)

### 1.1 Launch

Run:
- `run_gui_integrated.bat`

Or:

```powershell
.\python_embeded\python.exe studio\gui_main.py
```

### 1.2 First-time setup

Install Playwright browser binaries:

```powershell
.\python_embeded\python.exe -m playwright install chromium
```

AI config (local, do not commit):
- Example: `studio/config/ai_config.json.example`
- Actual config: `studio/config/ai_config.json`

```powershell
copy .\studio\config\ai_config.json.example .\studio\config\ai_config.json
```

Configure the **compute server URL** in `ai_config.json`:
```json
{
  "compute_server_url": "http://<your-server-ip>:8000",
  "comfyui_addr": "http://<your-comfyui-ip>:8188",
  "llm_api_key": "sk-xxx"
}
```

Logs & temp:
- `studio/.runtime/logs/app.log`
- `studio/.runtime/tmp/`

## 2. AI Services Architecture

| Service | Role | Protocol | Config Field |
|---------|------|----------|--------------|
| **Compute Server** | Whisper ASR + VoxCPM TTS + Ollama Vision + CLIP Embedding | HTTP REST | `compute_server_url` |
| **ComfyUI** | AI Image Generation | HTTP | `comfyui_addr` |
| **DeepSeek API** | LLM Copywriting | HTTP | `llm_api_url` |

### Local Processing (still runs on client)
- **VSR** (video subtitle removal)
- **rembg** (background removal)
- **PaddleOCR** (text recognition)
- **ffmpeg** (media extraction and processing)
