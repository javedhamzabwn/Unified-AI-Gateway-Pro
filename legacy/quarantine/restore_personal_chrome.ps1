$baseDir = $PSScriptRoot

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "[RESTORE] UNBLOCKING AND LAUNCHING PERSONAL CHROME..." -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Terminate all bot scripts
try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -match "^(python|pythonw|cmd)\.exe$") -and ($_.CommandLine -match "kilo_mailtm|ainative_mailtm")
    } | ForEach-Object {
        Write-Host "  -> Terminating Bot PID: $($_.ProcessId)" -ForegroundColor DarkGray
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

# 2. Terminate bot Chrome processes
try {
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "bot_profiles|kilo_prof|ainative_prof"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

# 3. Terminate any lingering background Chrome if requested
Write-Host "-> Checking for locked background Chrome processes..." -ForegroundColor Cyan
taskkill /F /IM chrome.exe 2>$null | Out-Null
Start-Sleep -Milliseconds 500

# 4. Remove stale profile lock if present
$lockFile = "$env:LOCALAPPDATA\Google\Chrome\User Data\SingletonLock"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

# 5. Launch personal Chrome fresh on screen
Write-Host "-> Launching your personal Google Chrome now..." -ForegroundColor Green
Start-Process "chrome.exe" -ErrorAction SilentlyContinue

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "[OK] PERSONAL CHROME LAUNCHED!" -ForegroundColor Green
Write-Host "Your Chrome is now open. Click 'Restore' to reload your tabs." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
