@echo off
echo =======================================
echo Douyin Automated Listing - EXE Builder
echo =======================================

:: Request Administrator privileges to fix symlink creation error during electron-builder extraction
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo.
    echo [Requesting Admin Privileges]
    echo To fix the electron-builder "Cannot create symbolic link" error, this script needs Administrator rights.
    echo Please click "Yes" on the UAC prompt...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    pushd "%CD%"
    CD /D "%~dp0"

echo.
echo [1/3] Installing Node.js dependencies...
call npm install
if %ERRORLEVEL% neq 0 (
    echo.
    echo [Error] Failed to install dependencies. Please check your network or Node.js installation.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/3] Checking electron-builder...
call npm list electron-builder > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing electron-builder...
    call npm install electron-builder --save-dev
)

echo.
echo [3/3] Building EXE file...
echo (First time build may take a while to download Electron binaries. Please wait...)
call npm run build

if %ERRORLEVEL% neq 0 (
    echo.
    echo [Error] Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo =======================================
echo [Success] Build completed!
echo.
echo Your EXE file has been generated in:
echo %~dp0dist
echo =======================================
echo.
pause
