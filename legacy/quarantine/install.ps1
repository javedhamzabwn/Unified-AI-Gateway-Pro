param(
    [switch]$Force
)

$baseDir = $PSScriptRoot

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "    UNIFIED API GATEWAY SETUP (KILO + AINATIVE)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$binDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$batPath = Join-Path $binDir "api.bat"

# 1. Stop any running background bots safely before installing
Write-Host "[1/4] Stopping any existing gateway processes..." -ForegroundColor Yellow
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(python|pythonw)\.exe$") -and ($_.CommandLine -match "kilo_proxy|kilo_mailtm|ainative_mailtm")
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

# 2. Check Python
Write-Host ""
Write-Host "[2/4] Checking Python environment..." -ForegroundColor Yellow
$py = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $py) {
    $py = Get-Command "py" -ErrorAction SilentlyContinue
}
if (-not $py) {
    Write-Host "[ERROR] Python is not installed or not in PATH!" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Be sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    return
}
$pyVer = & python --version 2>&1
Write-Host "  -> Found Python: $pyVer" -ForegroundColor Green

# Install Requirements
$reqPath = Join-Path $baseDir "requirements.txt"
if (Test-Path $reqPath) {
    Write-Host "  -> Installing Python dependencies from requirements.txt..." -ForegroundColor DarkGray
    python -m pip install -r "$reqPath"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Pip encountered an issue. Gateway may still run if packages were pre-installed." -ForegroundColor Yellow
    } else {
        Write-Host "  -> Python dependencies ready!" -ForegroundColor Green
    }
}

# 3. Check Node.js and LocalTunnel
Write-Host ""
Write-Host "[3/4] Checking Node.js & LocalTunnel..." -ForegroundColor Yellow
$nodeCmd = Get-Command "node" -ErrorAction SilentlyContinue
$npmCmd = Get-Command "npm" -ErrorAction SilentlyContinue
if ($nodeCmd -and $npmCmd) {
    $nodeVer = & node --version 2>&1
    Write-Host "  -> Found Node.js: $nodeVer" -ForegroundColor Green
    Write-Host "  -> Ensuring localtunnel is installed globally..." -ForegroundColor DarkGray
    cmd /c npm install -g localtunnel 2>$null | Out-Null
    Write-Host "  -> LocalTunnel ready!" -ForegroundColor Green
} else {
    Write-Host "  -> [NOTICE] Node.js is not installed." -ForegroundColor Yellow
    Write-Host "     Public tunnel requires Node.js (https://nodejs.org/)." -ForegroundColor DarkGray
    Write-Host "     The local gateway (http://localhost:8000) will still function fully." -ForegroundColor DarkGray
}

# Ensure config.json exists
$configPath = Join-Path $baseDir "config.json"
if (-not (Test-Path $configPath)) {
    @{ kilo_cap = 175; ainative_cap = 100 } | ConvertTo-Json | Set-Content -Path $configPath -Force
    Write-Host "  -> Initialized default config.json" -ForegroundColor DarkGray
}

# 4. Setup Global CLI Command 'api'
Write-Host ""
Write-Host "[4/4] Configuring global 'api' command..." -ForegroundColor Yellow
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir -Force | Out-Null }

$cliPath = Join-Path $baseDir "api_cli.ps1"
$batContent = "@echo off`r`npowershell -ExecutionPolicy Bypass -File `"$cliPath`" %*"
Set-Content -Path $batPath -Value $batContent -Force
Write-Host "  -> Global 'api' command registered in $batPath" -ForegroundColor Green

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host " SUCCESS! The system is fully installed & configured." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "You can now run:" -ForegroundColor White
Write-Host "  api            - Open the interactive terminal control center" -ForegroundColor Cyan
Write-Host "  api start      - Start Kilo + AINative bots & proxy" -ForegroundColor Cyan
Write-Host "  api stop       - Stop everything cleanly" -ForegroundColor Cyan
Write-Host "  api details    - View live status, keys and endpoints" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Green
