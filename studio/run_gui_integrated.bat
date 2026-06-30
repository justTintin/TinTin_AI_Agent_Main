@echo off
setlocal
cd /d "%~dp0"

set "APP_DIR=%~dp0"
if not exist "%APP_DIR%gui_main.py" set "APP_DIR=%~dp0studio\"

set "PYTHON_EXE=%~dp0python_embeded\pythonw.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0..\python_embeded\pythonw.exe"

set "RUNTIME_DIR=%APP_DIR%.runtime"
set "TMP_DIR=%RUNTIME_DIR%\tmp"
set "LOG_DIR=%RUNTIME_DIR%\logs"

if not exist "%TMP_DIR%" mkdir "%TMP_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "TMP=%TMP_DIR%"
set "TEMP=%TMP_DIR%"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Internal Python environment not found at %PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%APP_DIR%gui_main.py" (
    echo [ERROR] gui_main.py not found at %APP_DIR%gui_main.py
    pause
    exit /b 1
)

echo [INFO] Using internal Python: %PYTHON_EXE%

start "" "%PYTHON_EXE%" "%APP_DIR%gui_main.py"

endlocal
