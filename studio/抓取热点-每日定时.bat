@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM 每日定时热点采集：启动素材浏览器(热点模式)，采完自动关闭。
REM 用 Windows 任务计划程序每天调用本脚本即可。
..\python_embeded\python.exe -c "import sys; sys.path.insert(0,'.'); from utils import asset_browser_client as a; ok,msg=a.launch_hotspot_capture(auto_quit=True); print(ok, msg)"
