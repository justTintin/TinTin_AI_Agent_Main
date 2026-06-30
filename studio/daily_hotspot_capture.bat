@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Daily scheduled hotspot capture: launch asset-browser in hotspot mode, auto-quit when done.
..\python_embeded\python.exe -c "import sys; sys.path.insert(0,'.'); from utils import asset_browser_client as a; ok,msg=a.launch_hotspot_capture(auto_quit=True); print(ok, msg)"
