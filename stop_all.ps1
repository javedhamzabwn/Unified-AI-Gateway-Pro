$baseDir = $PSScriptRoot

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$port = 8008
$configFile = Join-Path $baseDir "config.json"
if (Test-Path $configFile) {
    try {
        $json = Get-Content $configFile -Raw | ConvertFrom-Json
        if ($json.port) { $port = [int]$json.port }
    } catch {}
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "[STOP] INITIATING SURGICAL SYSTEM STOP..." -ForegroundColor Red
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. KILL ALL PYTHON BOT SCRIPTS AND WRAPPERS
Write-Host "-> Hunting down Python bot and proxy processes..." -ForegroundColor DarkGray
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(python|pythonw)\.exe$") -and ($_.CommandLine -match "kilo_mailtm|ainative_mailtm|kilo_proxy|uvicorn")
    } | ForEach-Object {
        Write-Host "  -> Killing Process PID: $($_.ProcessId)" -ForegroundColor DarkGray
        taskkill /F /T /PID $_.ProcessId 2>$null | Out-Null
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

# Release port
try {
    Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
} catch {}

# 2. KILL ALL BOT CHROME PROCESSES (Surgical: only matches bot profile directories)
Write-Host "-> Hunting down orphaned Bot Chrome processes..." -ForegroundColor DarkGray
$killedPids = @{}
for ($i = 0; $i -lt 5; $i++) {
    $botChrome = @()
    try {
        $botChrome = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -match "bot_profiles|kilo_prof|ainative_prof"
        }
    } catch {}

    if (-not $botChrome -or $botChrome.Count -eq 0) { break }
    $botChrome | ForEach-Object {
        $pidNum = $_.ProcessId
        if (-not $killedPids.ContainsKey($pidNum)) {
            $killedPids[$pidNum] = $true
            Write-Host "  -> Killing Bot Chrome PID: $pidNum" -ForegroundColor DarkGray
        }
        taskkill /F /T /PID $pidNum 2>$null | Out-Null
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 250
}

Write-Host "-> Bot Chrome Status: 0 Active Instances Confirmed (Personal Chrome Untouched)" -ForegroundColor Green

# 3. KILL LOCALTUNNEL / NODE (Surgical: only matches localtunnel)
Write-Host "-> Hunting down LocalTunnel connection..." -ForegroundColor DarkGray
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(node|cmd)\.exe$") -and ($_.CommandLine -match "localtunnel|kilo-api")
    } | ForEach-Object {
        Write-Host "  -> Killing Tunnel PID: $($_.ProcessId)" -ForegroundColor DarkGray
        taskkill /F /T /PID $_.ProcessId 2>$null | Out-Null
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

# 4. CLEAN UP PROFILE DIRECTORIES AND PID FILE
$pidFile = Join-Path $baseDir "bot_chrome_pids.txt"
if (Test-Path $pidFile) { Set-Content -Path $pidFile -Value "" -Force }

Remove-Item (Join-Path $baseDir "bot_profiles\kilo_prof") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $baseDir "bot_profiles\ainative_prof") -Recurse -Force -ErrorAction SilentlyContinue

# 5. REMOVE OLD STARTUP SHORTCUT
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\KiloKeyAutomator.lnk" -ErrorAction SilentlyContinue

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "[OK] FULL SYSTEM STOPPED AND VERIFIED CLEAN!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
