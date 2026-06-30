@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=..\..\python_embeded\python.exe
echo 正在用工程内置 python_embeded 启动本地 ComfyUI (127.0.0.1:8188)...
REM 经 _run_local.py 引导（embedded python 的 ._pth 不会把本目录加入 sys.path）
"%PY%" _run_local.py --listen 127.0.0.1 --port 8188 --disable-auto-launch
pause
