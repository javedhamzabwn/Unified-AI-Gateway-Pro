# Unified Kilo & AINative API Gateway

This is an automated API key harvesting system and proxy gateway that multiplexes Kilo Code and AINative Studio AI models into a single, unified endpoint. It comes with an intelligent caching routing proxy, background stealth browsers for auto-key generation, and a local tunneling system for public access.

## 🚀 1-Click Installation

To set up everything on a new PC, all you have to do is run a single command. 

If you are setting this up for the first time, open PowerShell and paste this exact command to auto-download, install, configure the 100 API cap, and start the proxy in the background:

```powershell
cd $HOME\Desktop; git clone https://github.com/javedhamzabwn/Unified-AI-Gateway-Pro.git KiloAPI_New; cd KiloAPI_New; '{ "kilo_cap": 100, "ainative_cap": 100 }' | Set-Content config.json; PowerShell -ExecutionPolicy Bypass -File .\install.ps1; PowerShell -ExecutionPolicy Bypass -File .\api_cli.ps1 start
```

Alternatively, if you already downloaded the folder manually:
1. Double-click **`run.bat`** (or `Install.bat`) to automatically install dependencies and launch the interactive Control Center in one click!

## 🛠️ Usage & Control Center

You can control the entire system either interactively or via CLI:

### 1. Web Dashboard (GUI Control Center)
* Open in any browser: **`http://localhost:8008/dashboard`** (or run `api web`).
* **Live Metrics**: Monitor Kilo Code and AINative key stock, capacity meters, and browser engine status in real-time.
* **Stream Logs**: Real-time log streaming for Kilo, AINative, Proxy, and LocalTunnel.
* **Error Inspector**: Real-time error detection with actionable troubleshooting hints (Cloudflare checks, email lags, rate limits).
* **AI Chat Tester**: Playground to query AI models directly from the browser.
* **1-Click Controls**: Start/Stop services, trigger live visible harvests, launch CDP Chrome, and toggle Headless/Visible browser modes.

### 2. Interactive Terminal Control Center
* Double-click `run.bat` (or type `api` in any terminal without arguments).
* Features sub-menus for live activity logs, endpoint tests, key cap configuration, Chrome recovery, and foreground debugging.

### 3. Quick CLI Commands
* `api` - Launch the interactive terminal Control Center.
* `api web` - Open the localhost Web Dashboard in your default browser.
* `api start` - Boot up the proxy, local tunnel, and background stealth bots.
* `api stop` - Cleanly shut down all bots, browser processes, and proxy servers.
* `api details` - View live status, active keys count, caps, browser engine, and URLs.
* `api workers [kilo|ainative] <1-5>` - Configure concurrent parallel browser workers.
* `api browser` - Configure browser engines (Auto UC / Selenium CDP / Remote CDP), Headless vs Visible mode.
* `api harvest [kilo|ainative]` - Live visible single-key harvester (watch key extraction on-screen).
* `api cdp` - Launch independent Chrome on port 9222 for CSI extension / Browser-Use / manual verification.
* `api log` - Stream live activity logs of the stealth bots, proxy, and tunnel.
* `api models` - List all the AI models currently available across the providers.
* `api cap` - Set maximum key generation caps or change Gateway HTTP port.
* `api hi` - Test the local proxy completion endpoint.
* `api public hi` - Test the public tunnel completion endpoint.
* `api restore` - Fix locked/blocked personal Chrome browser.
* `api install` - Run environment and dependency verification.

## 🌐 Browser Subsystem & Remote CDP (CSI / Browser-Use)
The new `browser_manager.py` subsystem provides:
- **Headless Mode**: Zero-footprint background runs without interrupting user desktop work.
- **Visible Mode**: On-screen browser execution to inspect navigation and Cloudflare verification live.
- **Automated Fallback**: Switches from Undetected-Chromedriver to Standard Selenium CDP with anti-detect script injection automatically if needed.
- **Remote CDP Connection (Port 9222)**: Connect to existing Chrome sessions or external tools like Browser-Use or CSI extensions.

## 🧠 Intelligent Routing Cache
The built-in proxy server (`kilo_proxy.py`) automatically routes your requests to the correct provider (Kilo Code or AINative Studio) depending on the model. If a model works on one provider but fails on another, the proxy **memorizes** this and instantly routes all future requests directly to the correct provider to save time and bandwidth.

## ⚠️ Requirements
* Windows OS (PowerShell 5.1 or PowerShell 7+)
* Chrome or Edge Browser (auto-detected via registry or Program Files)
* Python 3.10+
* Node.js (for the LocalTunnel public URL)

