@echo off
setlocal
color 0B
title Unified AI Gateway - Installer
cd /d "%~dp0"

echo ==========================================================================
echo          UNIFIED AI GATEWAY (KILO + AINATIVE) - INSTALLER
echo ==========================================================================
echo.

set "PY_CMD="
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY_CMD=python"
) else (
    py -3 --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    color 0C
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo ==========================================================================
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PY_CMD% --version') do echo [1/4] Found %%v

echo.
echo [2/4] Checking Node.js and LocalTunnel...
node --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%v in ('node --version') do echo       Found Node.js %%v
    echo       Ensuring localtunnel is installed globally...
    cmd /c npm install -g localtunnel >nul 2>&1
    echo       LocalTunnel installed and ready.
) else (
    echo       [NOTICE] Node.js is not installed.
    echo       Public tunnel requires Node.js. Local gateway on port 8008 will still work.
)

echo.
echo [3/4] Installing required Python packages...
%PY_CMD% -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Some packages may have failed. Continuing...
)

echo.
echo [4/4] Configuring environment and global 'api' command...
if not exist "%~dp0config.json" (
    echo { "kilo_cap": 175, "ainative_cap": 100, "port": 8008 } > "%~dp0config.json"
)

set "BIN_DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%" 2>nul
echo @echo off > "%BIN_DIR%\api.bat"
echo powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0api_cli.ps1" %%* >> "%BIN_DIR%\api.bat"

echo.
echo ==========================================================================
echo  SUCCESS! The Unified AI Gateway is fully installed and ready to run.
echo ==========================================================================
echo.
echo  You can run the gateway anytime by:
echo    - Double-clicking 'run.bat' in this folder
echo    - Typing 'api' in ANY command prompt or PowerShell window
echo.
echo ==========================================================================
set /p "LAUNCH_NOW=Launch Gateway Control Center now? (Y/n): "
if /i "%LAUNCH_NOW%"=="n" (
    echo Exiting setup.
    exit /b 0
)

call "%~dp0run.bat"