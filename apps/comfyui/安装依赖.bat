@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=..\..\python_embeded\python.exe
echo 使用工程内置 python_embeded 安装 ComfyUI 依赖...
echo （torch / torchvision 已随工程预装，pip 会自动跳过）
"%PY%" -m pip install -r requirements.txt
echo.
echo 依赖安装完成。可双击「启动-本地ComfyUI.bat」测试，或直接在 studio 里提交任务自动启动。
pause
