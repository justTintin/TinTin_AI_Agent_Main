# DingDaGuai E-commerce Agent Matrix (GUI / Web)

Dự án dùng cho mục đích học tập và nội bộ.

Kho này hiện có:
- **Ứng dụng GUI (khuyến nghị, Windows)**: PySide6 (phân tích Douyin, hàng đợi tải, quản lý tải, AI tools).
- **Web backend (tuỳ chọn / legacy)**: Flask (cần `config.ini` và DB).

## 1. GUI (Windows)

Chạy:
- `run_gui_integrated.bat`

Hoặc:

```powershell
.\python_embeded\python.exe gui_main.py
```

Cài Playwright browser:

```powershell
.\python_embeded\python.exe -m playwright install chromium
```

Cấu hình AI (local):
- Ví dụ: `config/ai_config.example.json`
- File thật: `config/ai_config.json`

```powershell
copy .\config\ai_config.example.json .\config\ai_config.json
```

Log & temp:
- `.runtime/logs/app.log`
- `.runtime/tmp/`

## 2. Web backend (optional / legacy)

Khuyến nghị dùng venv riêng:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_server.py test
```

URL mặc định:
- http://127.0.0.1:5050/video_list
