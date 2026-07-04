# DingDaGuai E-commerce Agent Matrix (GUI / Web)

This project is for learning and internal use only.

The repository currently contains:
- **GUI Desktop App (recommended, Windows)**: PySide6-based app (Douyin parsing & download queue, downloader manager, AI tools).
- **Web Backend (optional / legacy)**: Flask-based pages and APIs (requires `config.ini` and database setup).

## 1. GUI Desktop App (Windows)

### 1.1 Launch (updated)

Run:
- `run_gui_integrated.bat`

Or:

```powershell
.\python_embeded\python.exe gui_main.py
```

### 1.2 First-time setup

Install Playwright browser binaries:

```powershell
.\python_embeded\python.exe -m playwright install chromium
```

AI config (local, do not commit):
- Example: `config/ai_config.example.json`
- Actual config: `config/ai_config.json`

```powershell
copy .\config\ai_config.example.json .\config\ai_config.json
```

Logs & temp:
- `.runtime/logs/app.log`
- `.runtime/tmp/`

## 2. Web Backend (optional / legacy)

Use a separate virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_server.py test
```

Default URL:
- http://127.0.0.1:5050/video_list
