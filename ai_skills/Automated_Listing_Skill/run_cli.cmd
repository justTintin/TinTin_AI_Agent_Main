@echo off
setlocal enabledelayedexpansion

chcp 65001 > nul

set "SKILL_ROOT=%~dp0"
cd /d "%SKILL_ROOT%"

python -u cli.py %*

if %ERRORLEVEL% neq 0 (
    exit /b %ERRORLEVEL%
)
