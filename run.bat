@echo off
setlocal
title Unified AI Gateway - Control Center
color 0B
cd /d "%~dp0"

if not "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0api_cli.ps1" %*
    exit /b %ERRORLEVEL%
)

echo ==========================================================================
echo               UNIFIED AI GATEWAY (KILO + AINATIVE)
echo                     One-Click Auto-Launcher
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
    echo [ERROR] Python is not installed or not in your system PATH!
    echo.
    echo Please download and install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: Make sure to check "Add python.exe to PATH" during setup.
    echo ==========================================================================
    pause
    exit /b 1
)

%PY_CMD% -c "import fastapi, uvicorn, requests, undetected_chromedriver, selenium, httpx" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] First-time setup: Missing Python packages detected.
    echo [*] Installing dependencies from requirements.txt...
    echo.
    %PY_CMD% -m pip install -r "%~dp0requirements.txt"
    if %ERRORLEVEL% NEQ 0 (
        echo [WARN] Pip install finished with warnings. Proceeding...
    ) else (
        echo [OK] Python dependencies verified.
    )
    echo.
)

node --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    cmd /c npm list -g localtunnel --depth=0 >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [*] Ensuring localtunnel is installed globally...
        cmd /c npm install -g localtunnel >nul 2>&1
        echo [OK] LocalTunnel ready.
        echo.
    )
)

if not exist "%~dp0config.json" (
    echo { "kilo_cap": 175, "ainative_cap": 100, "port": 8008 } > "%~dp0config.json"
)

set "BIN_DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%" 2>nul
echo @echo off > "%BIN_DIR%\api.bat"
echo powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0api_cli.ps1" %%* >> "%BIN_DIR%\api.bat"

cls
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0api_cli.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Gateway CLI exited with code %ERRORLEVEL%.
    pause
)