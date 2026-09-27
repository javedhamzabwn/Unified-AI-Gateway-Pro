param(
    [switch]$NoTunnel
)

$baseDir = $PSScriptRoot

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# Read port and settings from config.json
$port = 8008
$kiloWorkers = 1
$aiWorkers = 1
$configFile = Join-Path $baseDir "config.json"
if (Test-Path $configFile) {
    try {
        $json = Get-Content $configFile -Raw | ConvertFrom-Json
        if ($json.port) { $port = [int]$json.port }
        if ($json.kilo_workers) { $kiloWorkers = [int]$json.kilo_workers }
        if ($json.ainative_workers) { $aiWorkers = [int]$json.ainative_workers }
    } catch {}
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   STARTING UNIFIED AI GATEWAY (KILO + AINATIVE)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Clean old processes surgically
Write-Host "[1/5] Terminating previous bot & proxy instances..." -ForegroundColor Yellow
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match "^(python|pythonw)\.exe$" -and $_.CommandLine -match "kilo_proxy|kilo_mailtm|ainative_mailtm"
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

# Free configured port if occupied
try {
    Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
} catch {}

# Surgically terminate bot Chrome only
try {
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "bot_profiles|kilo_prof|ainative_prof"
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

# Terminate previous localtunnel processes only (preserve unrelated node apps!)
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(node|cmd)\.exe$") -and ($_.CommandLine -match "localtunnel|kilo-api")
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

# Find Python executable
$pyCmd = "python"
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        $pyCmd = "py -3"
    } else {
        Write-Host "[ERROR] Python is not installed or not in PATH!" -ForegroundColor Red
        return
    }
}

# 2. Launch Kilo Code Bot
Write-Host "[2/5] Starting Kilo Code Key Generator (Background | Workers: $kiloWorkers)..." -ForegroundColor Yellow
$kiloScript = Join-Path $baseDir "kilo_mailtm.py"
Start-Process "python" -ArgumentList "`"$kiloScript`" --workers $kiloWorkers" -WorkingDirectory $baseDir -WindowStyle Hidden

# 3. Launch AINative Studio Bot
Write-Host "[3/5] Starting AINative Studio Key Generator (Background | Workers: $aiWorkers)..." -ForegroundColor Yellow
$aiNativeScript = Join-Path $baseDir "ainative_mailtm.py"
Start-Process "python" -ArgumentList "`"$aiNativeScript`" --workers $aiWorkers" -WorkingDirectory $baseDir -WindowStyle Hidden

# 4. Launch Unified Proxy Server
Write-Host "[4/5] Starting Unified Proxy Gateway on port $port..." -ForegroundColor Yellow
$proxyScript = Join-Path $baseDir "kilo_proxy.py"
Start-Process "python" -ArgumentList "`"$proxyScript`"" -WorkingDirectory $baseDir -WindowStyle Hidden

# 5. Launch LocalTunnel (if node/npx available and not disabled)
$cleanUsername = ($env:USERNAME.ToLower() -replace '[^a-z0-9]', '')
$subdomain = "kilo-api-$cleanUsername"
$tunnelLog = Join-Path $baseDir "tunnel.log"
Remove-Item $tunnelLog -ErrorAction SilentlyContinue

$hasNpx = (Get-Command "npx" -ErrorAction SilentlyContinue) -ne $null
if ($hasNpx -and -not $NoTunnel) {
    Write-Host "[5/5] Starting LocalTunnel public URL..." -ForegroundColor Yellow
    # Note: --yes flag prevents interactive prompt hanging!
    Start-Process cmd -ArgumentList "/c npx --yes localtunnel --port $port --subdomain $subdomain > `"$tunnelLog`" 2>&1" -WorkingDirectory $baseDir -WindowStyle Hidden
} else {
    Write-Host "[5/5] Skipping LocalTunnel (Node.js/npx not found or disabled)." -ForegroundColor DarkGray
}

# Verify Proxy is responding
Write-Host ""
Write-Host "Verifying Gateway connection on port $port..." -ForegroundColor DarkGray
$online = $false
for ($i = 0; $i -lt 8; $i++) {
    Start-Sleep -Milliseconds 400
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 1 -ErrorAction Stop
        if ($resp) { $online = $true; break }
    } catch {
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:$port/v1/models" -TimeoutSec 1 -ErrorAction Stop
            if ($resp) { $online = $true; break }
        } catch {}
    }
}

Write-Host "=======================================================" -ForegroundColor Green
if ($online) {
    Write-Host " [OK] DUAL-PROVIDER API GATEWAY IS ONLINE!" -ForegroundColor Green
} else {
    Write-Host " [WARN] Gateway starting up (check: api details in a moment)" -ForegroundColor Yellow
}
Write-Host " -> Web Dashboard  : http://localhost:$port/dashboard" -ForegroundColor Green
Write-Host " -> Proxy Gateway  : http://localhost:$port/v1/chat/completions" -ForegroundColor Cyan
Write-Host " -> Models URL     : http://localhost:$port/v1/models" -ForegroundColor Cyan
if ($hasNpx -and -not $NoTunnel) {
    Write-Host " -> Public Tunnel  : https://$subdomain.loca.lt" -ForegroundColor Green
}
Write-Host " -> Kilo Bot       : Active ($kiloWorkers parallel browser workers)" -ForegroundColor Cyan
Write-Host " -> AINative Bot   : Active ($aiWorkers parallel browser workers)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Green
