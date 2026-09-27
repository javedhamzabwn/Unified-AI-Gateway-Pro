param(
    [Parameter(Mandatory=$false, Position=0)]
    [string]$Command,
    
    [Parameter(Mandatory=$false, Position=1)]
    [string]$Arg1,

    [Parameter(Mandatory=$false, Position=2)]
    [string]$Arg2
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$baseDir = $PSScriptRoot

function Get-UserInput([string]$prompt = "") {
    try {
        $val = Read-Host $prompt
        if ($null -eq $val) { return "0" }
        return ([string]$val).Trim()
    } catch {
        return "0"
    }
}

function Get-KeyCount([string]$filePath) {
    if (Test-Path $filePath) {
        return (Get-Content $filePath | Where-Object { $_.Trim() -ne "" } | Measure-Object).Count
    }
    return 0
}

function Get-GatewayConfig {
    $configFile = Join-Path $baseDir "config.json"
    $kiloCap = 175
    $aiNativeCap = 100
    $kiloWorkers = 1
    $aiWorkers = 1
    $port = 8008
    $headless = $true
    $engine = "auto"
    $cdpPort = 9222
    if (Test-Path $configFile) {
        try {
            $json = Get-Content $configFile -Raw | ConvertFrom-Json
            if ($null -ne $json.kilo_cap) { $kiloCap = [int]$json.kilo_cap }
            if ($null -ne $json.ainative_cap) { $aiNativeCap = [int]$json.ainative_cap }
            if ($null -ne $json.kilo_workers) { $kiloWorkers = [int]$json.kilo_workers }
            if ($null -ne $json.ainative_workers) { $aiWorkers = [int]$json.ainative_workers }
            if ($null -ne $json.port) { $port = [int]$json.port }
            if ($null -ne $json.headless) { $headless = [bool]$json.headless }
            if ($null -ne $json.browser_engine) { $engine = [string]$json.browser_engine }
            if ($null -ne $json.cdp_port) { $cdpPort = [int]$json.cdp_port }
        } catch {}
    }
    return @{
        KiloCap = $kiloCap
        AINativeCap = $aiNativeCap
        KiloWorkers = $kiloWorkers
        AINativeWorkers = $aiWorkers
        Port = $port
        Headless = $headless
        Engine = $engine
        CdpPort = $cdpPort
    }
}

function Set-GatewayConfigValue([string]$key, $val) {
    $configFile = Join-Path $baseDir "config.json"
    $configHash = @{}
    if (Test-Path $configFile) {
        try {
            $parsed = Get-Content $configFile -Raw | ConvertFrom-Json
            foreach ($prop in $parsed.psobject.properties) {
                $configHash[$prop.Name] = $prop.Value
            }
        } catch {}
    }
    $configHash[$key] = $val
    $configHash | ConvertTo-Json -Depth 5 | Set-Content $configFile -Force
}

function Get-PublicTunnelUrl {
    $tunnelLog = Join-Path $baseDir "tunnel.log"
    if (Test-Path $tunnelLog) {
        try {
            $content = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
            if ($content -match 'your url is:\s*(https://[^\s]+)') {
                return $matches[1].TrimEnd('/')
            }
        } catch {}
    }
    $cleanUsername = ($env:USERNAME.ToLower() -replace '[^a-z0-9]', '')
    return "https://kilo-api-$cleanUsername.loca.lt"
}

function Test-GatewayOnline {
    $cfg = Get-GatewayConfig
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$($cfg.Port)/v1/models" -TimeoutSec 1 -ErrorAction Stop
        if ($resp) { return $true }
    } catch {
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:$($cfg.Port)/v1/models" -TimeoutSec 1 -ErrorAction Stop
            if ($resp) { return $true }
        } catch {}
    }
    return $false
}

function Show-Details {
    $kiloCount = Get-KeyCount (Join-Path $baseDir "kilo_keys.txt")
    $aiNativeCount = Get-KeyCount (Join-Path $baseDir "ainative_keys.txt")
    $cfg = Get-GatewayConfig
    $tunnelUrl = Get-PublicTunnelUrl
    $isOnline = Test-GatewayOnline
    $modeStr = if ($cfg.Headless) { "Headless (Background Stealth)" } else { "Visible (Watch on Screen)" }

    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host "       LIVE SYSTEM STATUS AND KEY INVENTORY" -ForegroundColor Green
    Write-Host "=======================================================" -ForegroundColor Green
    if ($isOnline) {
        Write-Host " -> Gateway Status     : ONLINE (Port $($cfg.Port))" -ForegroundColor Green
    } else {
        Write-Host " -> Gateway Status     : OFFLINE (Run option 1 to start)" -ForegroundColor Yellow
    }
    Write-Host " -> Kilo Code Keys     : $kiloCount (Target Cap: $($cfg.KiloCap) | Workers: $($cfg.KiloWorkers))" -ForegroundColor Cyan
    Write-Host " -> AINative Keys      : $aiNativeCount (Target Cap: $($cfg.AINativeCap) | Workers: $($cfg.AINativeWorkers))" -ForegroundColor Cyan
    Write-Host " -> Browser Mode       : $modeStr" -ForegroundColor Cyan
    Write-Host " -> Browser Engine     : $($cfg.Engine) (CDP Port: $($cfg.CdpPort))" -ForegroundColor Cyan
    Write-Host " -> Local Proxy URL    : http://localhost:$($cfg.Port)/v1/chat/completions" -ForegroundColor Cyan
    Write-Host " -> Local Models URL   : http://localhost:$($cfg.Port)/v1/models" -ForegroundColor Cyan
    Write-Host " -> Public Tunnel URL  : $tunnelUrl/v1/chat/completions" -ForegroundColor Green
    Write-Host " -> Web Dashboard URL  : http://localhost:$($cfg.Port)/dashboard" -ForegroundColor Green
    Write-Host "=======================================================" -ForegroundColor Green
}

function Open-WebDashboard {
    $cfg = Get-GatewayConfig
    $url = "http://localhost:$($cfg.Port)/dashboard"
    Write-Host "`nOpening Web Dashboard: $url" -ForegroundColor Green
    try {
        Start-Process $url
    } catch {
        Write-Host "Please open in browser: $url" -ForegroundColor Yellow
    }
}

function View-LogFile([string]$logFile, [string]$title) {
    if (-not (Test-Path $logFile)) {
        Write-Host "`n[WARN] Log file '$logFile' does not exist yet. The service may not have run." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        return
    }
    Write-Host "`n=======================================================" -ForegroundColor Cyan
    Write-Host " STREAMING LOG: $title (Press Ctrl+C to return to menu)" -ForegroundColor Cyan
    Write-Host "=======================================================" -ForegroundColor Cyan
    try {
        Get-Content $logFile -Wait -Tail 30
    } catch [System.Management.Automation.PipelineStoppedException] {
        # Graceful exit on Ctrl+C
    } catch {
        # Other exceptions
    }
    Write-Host "`nReturned from log stream." -ForegroundColor DarkGray
    Start-Sleep -Seconds 1
}

function Show-LogsMenu {
    while ($true) {
        Write-Host "`n-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "                LIVE ACTIVITY LOGS" -ForegroundColor Cyan
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "  [1] Kilo Code Bot Log        (kilo.log)"
        Write-Host "  [2] AINative Studio Bot Log  (ainative.log)"
        Write-Host "  [3] Unified Proxy Server Log (proxy.log)"
        Write-Host "  [4] LocalTunnel Network Log  (tunnel.log)"
        Write-Host "  [B] Back to Main Menu"
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        $choice = (Get-UserInput "Select log to view (1-4, B)").ToUpper()

        switch ($choice) {
            "1" { View-LogFile (Join-Path $baseDir "kilo.log") "Kilo Code Bot" }
            "2" { View-LogFile (Join-Path $baseDir "ainative.log") "AINative Studio Bot" }
            "3" { View-LogFile (Join-Path $baseDir "proxy.log") "Unified Proxy Server" }
            "4" { View-LogFile (Join-Path $baseDir "tunnel.log") "LocalTunnel Network" }
            "B" { return }
            default { Write-Host "Invalid choice." -ForegroundColor Red; Start-Sleep -Milliseconds 600 }
        }
    }
}

function Show-TestMenu {
    while ($true) {
        Write-Host "`n-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "               TEST GATEWAY & MODELS" -ForegroundColor Cyan
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        $cfg = Get-GatewayConfig
        Write-Host "  [1] Test Local Proxy Chat (http://localhost:$($cfg.Port))"
        Write-Host "  [2] Test Public LocalTunnel Chat (loca.lt)"
        Write-Host "  [3] List All Available Models Across Providers"
        Write-Host "  [4] Custom Prompt Test"
        Write-Host "  [B] Back to Main Menu"
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        $choice = (Get-UserInput "Select test option (1-4, B)").ToUpper()

        switch ($choice) {
            "1" {
                Write-Host ""
                python (Join-Path $baseDir "test_proxy.py") "local"
                Read-Host "Press Enter to continue..."
            }
            "2" {
                Write-Host ""
                python (Join-Path $baseDir "test_proxy.py") "public"
                Read-Host "Press Enter to continue..."
            }
            "3" {
                Write-Host ""
                python (Join-Path $baseDir "list_models.py")
                Read-Host "Press Enter to continue..."
            }
            "4" {
                $target = Get-UserInput "Target (1=local, 2=public) [default: 1]"
                $targetStr = if ($target -eq "2") { "public" } else { "local" }
                $m = Get-UserInput "Model ID [default: kilo-auto/free]"
                if (-not $m) { $m = "kilo-auto/free" }
                $p = Get-UserInput "Prompt [default: 'Hello world']"
                if (-not $p) { $p = "Hello world" }
                Write-Host ""
                python (Join-Path $baseDir "test_proxy.py") $targetStr $m $p
                Read-Host "Press Enter to continue..."
            }
            "B" { return }
            default { Write-Host "Invalid choice." -ForegroundColor Red; Start-Sleep -Milliseconds 600 }
        }
    }
}

function Show-CapMenu {
    $configFile = Join-Path $baseDir "config.json"
    $cfg = Get-GatewayConfig

    Write-Host "`n-------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "       CONFIGURE KEY LIMITS & GATEWAY PORT" -ForegroundColor Cyan
    Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "Current Limits -> Kilo: $($cfg.KiloCap) (Workers: $($cfg.KiloWorkers)) | AINative: $($cfg.AINativeCap) (Workers: $($cfg.AINativeWorkers)) | Port: $($cfg.Port)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [1] Set Kilo Code Target Cap"
    Write-Host "  [2] Set AINative Studio Target Cap"
    Write-Host "  [3] Set Both to the Same Cap"
    Write-Host "  [4] Set to Hibernate (Cap = 0)"
    Write-Host "  [5] Change Gateway Proxy Port (Default: 8008)"
    Write-Host "  [6] Set Parallel Browser Workers (1-5 Concurrent Browsers)"
    Write-Host "  [B] Back to Main Menu"
    Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
    $choice = (Get-UserInput "Select option (1-6, B)").ToUpper()

    if ($choice -eq "B") { return }

    if ($choice -eq "6") {
        Write-Host "`nConfigure Parallel Workers (Concurrent Browsers):"
        Write-Host "  Current -> Kilo: $($cfg.KiloWorkers) | AINative: $($cfg.AINativeWorkers)" -ForegroundColor Yellow
        $kw = Get-UserInput "Enter number of concurrent Kilo browser workers (1-5) [current: $($cfg.KiloWorkers)]"
        if ([int]::TryParse($kw, [ref]$null)) {
            $kwNum = [Math]::Max(1, [Math]::Min(5, [int]$kw))
            Set-GatewayConfigValue "kilo_workers" $kwNum
            Write-Host "[OK] Kilo concurrent browser workers set to: $kwNum" -ForegroundColor Green
        }
        $aw = Get-UserInput "Enter number of concurrent AINative browser workers (1-5) [current: $($cfg.AINativeWorkers)]"
        if ([int]::TryParse($aw, [ref]$null)) {
            $awNum = [Math]::Max(1, [Math]::Min(5, [int]$aw))
            Set-GatewayConfigValue "ainative_workers" $awNum
            Write-Host "[OK] AINative concurrent browser workers set to: $awNum" -ForegroundColor Green
        }
        Write-Host "[INFO] If background bots are running, restart them to apply new worker concurrency." -ForegroundColor Yellow
        Start-Sleep -Seconds 1
        return
    }

    if ($choice -eq "5") {
        $pInput = Get-UserInput "Enter new Gateway port number [default: 8008]"
        if ([int]::TryParse($pInput, [ref]$null)) {
            Set-GatewayConfigValue "port" ([int]$pInput)
            Write-Host "[OK] Gateway proxy port updated to: $pInput" -ForegroundColor Green
            Write-Host "[INFO] If gateway is currently running, restart it to bind to the new port." -ForegroundColor Yellow
        } else {
            Write-Host "Invalid port number." -ForegroundColor Red
        }
        Start-Sleep -Seconds 1
        return
    }

    $newCap = 0
    if ($choice -in @("1", "2", "3")) {
        $inputVal = Get-UserInput "Enter new numeric cap (e.g. 150, or 0 to hibernate)"
        if (-not [int]::TryParse($inputVal, [ref]$null)) {
            Write-Host "Invalid whole number." -ForegroundColor Red
            Start-Sleep -Seconds 1
            return
        }
        $newCap = [int]$inputVal
    } elseif ($choice -eq "4") {
        $newCap = 0
    } else {
        Write-Host "Invalid choice." -ForegroundColor Red
        Start-Sleep -Milliseconds 600
        return
    }

    if ($choice -eq "1" -or $choice -eq "3" -or $choice -eq "4") {
        Set-GatewayConfigValue "kilo_cap" $newCap
        Write-Host "[OK] Kilo Code cap set to $newCap" -ForegroundColor Green
    }
    if ($choice -eq "2" -or $choice -eq "3" -or $choice -eq "4") {
        Set-GatewayConfigValue "ainative_cap" $newCap
        Write-Host "[OK] AINative Studio cap set to $newCap" -ForegroundColor Green
    }

    Start-Sleep -Seconds 1
}

function Show-BrowserMenu {
    while ($true) {
        $cfg = Get-GatewayConfig
        $modeStr = if ($cfg.Headless) { "Headless (Background Stealth)" } else { "Visible (Watch on Screen)" }
        Write-Host "`n-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "       BROWSER ENGINE & EXECUTION MODE SETTINGS" -ForegroundColor Cyan
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "  Current Mode   : $modeStr" -ForegroundColor Yellow
        Write-Host "  Current Engine : $($cfg.Engine) (auto / uc / selenium / cdp)" -ForegroundColor Yellow
        Write-Host "  CDP Debug Port : $($cfg.CdpPort)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  [1] Toggle Headless vs Visible Browser Mode"
        Write-Host "  [2] Select Browser Engine (Auto Stealth / UC / Selenium / Remote CDP)"
        Write-Host "  [3] Set Remote CDP Debugging Port"
        Write-Host "  [4] Launch Chrome in Remote CDP Mode (For CSI / Browser-Use / Manual Login)"
        Write-Host "  [5] Test Browser Subsystem (Real-Time Pakistan Clock & DOM/JS Verification)"
        Write-Host "  [B] Back to Main Menu"
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        $choice = (Get-UserInput "Select browser setting (1-5, B)").ToUpper()

        switch ($choice) {
            "1" {
                $newHeadless = -not $cfg.Headless
                Set-GatewayConfigValue "headless" $newHeadless
                $status = if ($newHeadless) { "Headless (Hidden / Background)" } else { "Visible (Watch on Screen)" }
                Write-Host "[OK] Browser mode set to: $status" -ForegroundColor Green
                Start-Sleep -Seconds 1
            }
            "2" {
                Write-Host "`nSelect Engine:"
                Write-Host "  [1] Auto (Stealth UC with automated Selenium CDP fallback) [Default]"
                Write-Host "  [2] Undetected-Chromedriver (UC only)"
                Write-Host "  [3] Standard Selenium CDP (Universal fallback)"
                Write-Host "  [4] Remote CDP (Connects to existing Chrome / CSI / Browser-Use)"
                $engChoice = Get-UserInput "Choice (1-4)"
                $selected = switch ($engChoice) {
                    "1" { "auto" }
                    "2" { "uc" }
                    "3" { "selenium" }
                    "4" { "cdp" }
                    default { "auto" }
                }
                Set-GatewayConfigValue "browser_engine" $selected
                Write-Host "[OK] Browser engine set to: $selected" -ForegroundColor Green
                Start-Sleep -Seconds 1
            }
            "3" {
                $p = Get-UserInput "Enter remote CDP debugging port [current: $($cfg.CdpPort)]"
                if ([int]::TryParse($p, [ref]$null)) {
                    Set-GatewayConfigValue "cdp_port" ([int]$p)
                    Write-Host "[OK] CDP port updated to: $p" -ForegroundColor Green
                } else {
                    Write-Host "Invalid port number." -ForegroundColor Red
                }
                Start-Sleep -Seconds 1
            }
            "4" {
                Write-Host "`nLaunching independent Chrome on CDP port $($cfg.CdpPort)..." -ForegroundColor Cyan
                python (Join-Path $baseDir "browser_manager.py") --launch-cdp $cfg.CdpPort
                Read-Host "Press Enter to continue..."
            }
            "5" {
                $visChoice = Get-UserInput "Diagnostic Mode: (1=Headless Background, 2=Visible Watch On Screen) [default: 1]"
                Write-Host "`nRunning real-time browser diagnostic test..." -ForegroundColor Cyan
                if ($visChoice -eq "2") {
                    python (Join-Path $baseDir "browser_manager.py") --test --visible
                } else {
                    python (Join-Path $baseDir "browser_manager.py") --test
                }
                Read-Host "Press Enter to continue..."
            }
            "B" { return }
            default { Write-Host "Invalid choice." -ForegroundColor Red; Start-Sleep -Milliseconds 600 }
        }
    }
}

function Show-LiveHarvestMenu {
    while ($true) {
        $kiloCount = Get-KeyCount (Join-Path $baseDir "kilo_keys.txt")
        $aiNativeCount = Get-KeyCount (Join-Path $baseDir "ainative_keys.txt")
        $cfg = Get-GatewayConfig

        Write-Host "`n-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "      LIVE BROWSER KEY HARVESTER (ON-SCREEN WATCH)" -ForegroundColor Cyan
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "  Stock: Kilo: $kiloCount / $($cfg.KiloCap)  |  AINative: $aiNativeCount / $($cfg.AINativeCap)" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  [1] Harvest 1 Kilo Code Key Live (Visible Chrome On-Screen)"
        Write-Host "  [2] Harvest 1 AINative Studio Key Live (Visible Chrome On-Screen)"
        Write-Host "  [3] Run Kilo Code Harvester (Visible Continuous Watch)"
        Write-Host "  [4] Run AINative Studio Harvester (Visible Continuous Watch)"
        Write-Host "  [5] Run Unified Proxy Server in Foreground (Watch Live API Traffic)"
        Write-Host "  [B] Back to Main Menu"
        Write-Host "-------------------------------------------------------" -ForegroundColor Cyan
        $choice = (Get-UserInput "Select option (1-5, B)").ToUpper()

        switch ($choice) {
            "1" {
                Write-Host "`nLaunching Kilo Code Harvester (Visible, Single Key)..." -ForegroundColor Yellow
                python (Join-Path $baseDir "kilo_mailtm.py") --visible --once
                Read-Host "Press Enter to continue..."
            }
            "2" {
                Write-Host "`nLaunching AINative Studio Harvester (Visible, Single Key)..." -ForegroundColor Yellow
                python (Join-Path $baseDir "ainative_mailtm.py") --visible --once
                Read-Host "Press Enter to continue..."
            }
            "3" {
                Write-Host "`nLaunching Kilo Code Harvester Loop (Visible, Ctrl+C to stop)..." -ForegroundColor Yellow
                python (Join-Path $baseDir "kilo_mailtm.py") --visible
                Read-Host "Press Enter to continue..."
            }
            "4" {
                Write-Host "`nLaunching AINative Harvester Loop (Visible, Ctrl+C to stop)..." -ForegroundColor Yellow
                python (Join-Path $baseDir "ainative_mailtm.py") --visible
                Read-Host "Press Enter to continue..."
            }
            "5" {
                Write-Host "`nLaunching Unified Proxy Server on port $($cfg.Port) (Ctrl+C to stop)..." -ForegroundColor Yellow
                python (Join-Path $baseDir "kilo_proxy.py")
                Read-Host "Server ended. Press Enter to continue..."
            }
            "B" { return }
            default { Write-Host "Invalid choice." -ForegroundColor Red; Start-Sleep -Milliseconds 600 }
        }
    }
}

function Show-InteractiveMenu {
    while ($true) {
        $isOnline = Test-GatewayOnline
        $kiloCount = Get-KeyCount (Join-Path $baseDir "kilo_keys.txt")
        $aiNativeCount = Get-KeyCount (Join-Path $baseDir "ainative_keys.txt")
        $cfg = Get-GatewayConfig
        $tunnelUrl = Get-PublicTunnelUrl
        $modeStr = if ($cfg.Headless) { "Headless" } else { "Visible" }

        Write-Host ""
        Write-Host "==========================================================================" -ForegroundColor Cyan
        Write-Host "                  UNIFIED AI GATEWAY - CONTROL CENTER" -ForegroundColor Cyan
        Write-Host "                     (Kilo Code + AINative Studio)" -ForegroundColor DarkCyan
        Write-Host "==========================================================================" -ForegroundColor Cyan
        if ($isOnline) {
            Write-Host "  -> Gateway : " -NoNewline; Write-Host "ONLINE" -ForegroundColor Green -NoNewline; Write-Host " (http://localhost:$($cfg.Port))"
        } else {
            Write-Host "  -> Gateway : " -NoNewline; Write-Host "OFFLINE" -ForegroundColor Yellow -NoNewline; Write-Host " (Press 1 to start)"
        }
        Write-Host "  -> Keys    : Kilo: $kiloCount (Cap: $($cfg.KiloCap))  |  AINative: $aiNativeCount (Cap: $($cfg.AINativeCap))" -ForegroundColor Cyan
        Write-Host "  -> Browser : Engine: $($cfg.Engine) | Mode: $modeStr | CDP Port: $($cfg.CdpPort)" -ForegroundColor DarkGray
        Write-Host "  -> Tunnel  : $tunnelUrl" -ForegroundColor DarkGray
        Write-Host "==========================================================================" -ForegroundColor Cyan
        Write-Host "  [W]  Open Web Dashboard (Manage via Browser: http://localhost:$($cfg.Port)/dashboard)" -ForegroundColor Green
        Write-Host "  [1]  Start All Gateway & Bots (Runs in Background)"
        Write-Host "  [2]  Stop All (Clean Shutdown of Bots, Browsers & Proxy)"
        Write-Host "  [3]  Live Status & Key Stock (Detailed Info & Endpoints)"
        Write-Host "  [4]  Live Activity Logs (Sub-Menu: Kilo / AINative / Proxy / Tunnel)"
        Write-Host "  [5]  Test Gateway & AI Models (Sub-Menu: Local / Public / Models / Prompt)"
        Write-Host "  [6]  Configure Key Caps & Port (Limits & Gateway Port)"
        Write-Host "  [7]  Browser Engine & Stealth Settings (CSI / CDP / Headless / Visible)"
        Write-Host "  [8]  Live Browser Key Harvester (Watch Live On-Screen / Fetch 1 Key)"
        Write-Host "  [9]  Fix / Restore Personal Chrome (Unblock & Clean Stale Locks)"
        Write-Host "  [10] Reinstall / Update Dependencies (First-Time Setup / Fix Tools)"
        Write-Host "  [0]  Exit"
        Write-Host "==========================================================================" -ForegroundColor Cyan
        $mainChoice = (Get-UserInput "Select an option (0-10, W)").ToUpper()
        if ($mainChoice -eq "") { continue }

        switch ($mainChoice) {
            "W" {
                Open-WebDashboard
                Start-Sleep -Seconds 1
            }
            "11" {
                Open-WebDashboard
                Start-Sleep -Seconds 1
            }
            "1" {
                Write-Host ""
                & (Join-Path $baseDir "start_all.ps1")
                Start-Sleep -Seconds 2
            }
            "2" {
                Write-Host ""
                & (Join-Path $baseDir "stop_all.ps1")
                Start-Sleep -Seconds 2
            }
            "3" {
                Write-Host ""
                Show-Details
                Read-Host "Press Enter to continue..."
            }
            "4" {
                Show-LogsMenu
            }
            "5" {
                Show-TestMenu
            }
            "6" {
                Show-CapMenu
            }
            "7" {
                Show-BrowserMenu
            }
            "8" {
                Show-LiveHarvestMenu
            }
            "9" {
                Write-Host ""
                & (Join-Path $baseDir "restore_personal_chrome.ps1")
                Start-Sleep -Seconds 2
            }
            "10" {
                Write-Host ""
                & (Join-Path $baseDir "install.ps1")
                Read-Host "Press Enter to continue..."
            }
            "0" {
                Write-Host "`nExiting Unified AI Gateway Control Center. Goodbye!`n" -ForegroundColor Green
                return
            }
            default {
                Write-Host "Invalid option. Please enter a number 0 to 10." -ForegroundColor Red
                Start-Sleep -Milliseconds 800
            }
        }
    }
}

# --- COMMAND ROUTING (CLI vs INTERACTIVE) ---
if (-not $Command -or $Command -in @("menu", "interactive", "ui", "gui")) {
    Show-InteractiveMenu
    exit
}

switch ($Command.ToLower()) {
    "web" {
        Open-WebDashboard
    }
    "dashboard" {
        Open-WebDashboard
    }
    "start" {
        & (Join-Path $baseDir "start_all.ps1")
    }
    "stop" {
        & (Join-Path $baseDir "stop_all.ps1")
    }
    "restore" {
        & (Join-Path $baseDir "restore_personal_chrome.ps1")
    }
    "install" {
        & (Join-Path $baseDir "install.ps1")
    }
    "browser" {
        Show-BrowserMenu
    }
    "harvest" {
        if ($Arg1 -eq "kilo") {
            python (Join-Path $baseDir "kilo_mailtm.py") --visible --once
        } elseif ($Arg1 -eq "ainative") {
            python (Join-Path $baseDir "ainative_mailtm.py") --visible --once
        } else {
            Show-LiveHarvestMenu
        }
    }
    "cdp" {
        $cfg = Get-GatewayConfig
        python (Join-Path $baseDir "browser_manager.py") --launch-cdp $cfg.CdpPort
    }
    "logs" {
        & (Join-Path $baseDir "api_cli.ps1") -Command "log" -Arg1 $Arg1
    }
    "log" {
        if (-not $Arg1) {
            Show-LogsMenu
        } else {
            switch ($Arg1) {
                "1" { View-LogFile (Join-Path $baseDir "kilo.log") "Kilo Code Bot" }
                "2" { View-LogFile (Join-Path $baseDir "ainative.log") "AINative Studio Bot" }
                "3" { View-LogFile (Join-Path $baseDir "proxy.log") "Unified Proxy Server" }
                "4" { View-LogFile (Join-Path $baseDir "tunnel.log") "LocalTunnel Network" }
                default { Write-Host "Invalid log choice (1=kilo, 2=ainative, 3=proxy, 4=tunnel)." -ForegroundColor Red }
            }
        }
    }
    "test" {
        Show-TestMenu
    }
    "hi" {
        python (Join-Path $baseDir "test_proxy.py") "local"
    }
    "public" {
        if ($Arg1 -eq "hi") {
            python (Join-Path $baseDir "test_proxy.py") "public"
        } else {
            Write-Host "Usage: api public hi" -ForegroundColor Yellow
        }
    }
    "details" {
        Show-Details
    }
    "status" {
        Show-Details
    }
    "cap" {
        Show-CapMenu
    }
    "models" {
        python (Join-Path $baseDir "list_models.py")
    }
    "port" {
        if ($Arg1 -and [int]::TryParse($Arg1, [ref]$null)) {
            Set-GatewayConfigValue "port" ([int]$Arg1)
            Write-Host "[OK] Gateway proxy port set to $Arg1" -ForegroundColor Green
        } else {
            Write-Host "Usage: api port <port_number>" -ForegroundColor Yellow
        }
    }
    "run" {
        if ($Arg1 -eq "ainative") {
            python (Join-Path $baseDir "ainative_mailtm.py") --visible
        } elseif ($Arg1 -eq "kilo") {
            python (Join-Path $baseDir "kilo_mailtm.py") --visible
        } elseif ($Arg1 -eq "proxy") {
            python (Join-Path $baseDir "kilo_proxy.py")
        } else {
            Show-LiveHarvestMenu
        }
    }
    "workers" {
        if ($Arg1 -eq "kilo" -and $Arg2 -and [int]::TryParse($Arg2, [ref]$null)) {
            $num = [Math]::Max(1, [Math]::Min(5, [int]$Arg2))
            Set-GatewayConfigValue "kilo_workers" $num
            Write-Host "[OK] Kilo concurrent browser workers set to $num" -ForegroundColor Green
        } elseif ($Arg1 -eq "ainative" -and $Arg2 -and [int]::TryParse($Arg2, [ref]$null)) {
            $num = [Math]::Max(1, [Math]::Min(5, [int]$Arg2))
            Set-GatewayConfigValue "ainative_workers" $num
            Write-Host "[OK] AINative concurrent browser workers set to $num" -ForegroundColor Green
        } else {
            $cfg = Get-GatewayConfig
            Write-Host "Current Parallel Workers -> Kilo: $($cfg.KiloWorkers) | AINative: $($cfg.AINativeWorkers)" -ForegroundColor Yellow
            Write-Host "Usage: api workers kilo <1-5>  OR  api workers ainative <1-5>" -ForegroundColor Cyan
        }
    }
    default {
        Write-Host "Unknown command '$Command'." -ForegroundColor Red
        Write-Host "Available CLI Commands:" -ForegroundColor Cyan
        Write-Host "  api            - Interactive control center menu"
        Write-Host "  api web        - Open localhost web dashboard in browser"
        Write-Host "  api start      - Start background bots & proxy"
        Write-Host "  api stop       - Clean stop all bots and proxies"
        Write-Host "  api details    - Show live status, key stock & endpoints"
        Write-Host "  api workers    - Set parallel browser workers (1-5)"
        Write-Host "  api browser    - Browser engine, stealth & CDP configuration"
        Write-Host "  api harvest    - Live browser key harvester (watch on-screen)"
        Write-Host "  api cdp        - Launch Chrome with remote debugging on port 9222"
        Write-Host "  api log [1-4]  - View live logs"
        Write-Host "  api models     - List available AI models"
        Write-Host "  api hi         - Test local proxy"
        Write-Host "  api public hi  - Test public tunnel"
        Write-Host "  api cap        - Configure key generation caps"
        Write-Host "  api port <num> - Set Gateway HTTP port"
        Write-Host "  api restore    - Fix/restore personal Chrome"
        Write-Host "  api install    - Setup/check dependencies"
    }
}

