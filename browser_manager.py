"""
Browser Manager & Driver Factory for Unified AI Gateway.
Supports:
 - Automatic Chrome / Edge detection across Windows registries & paths
 - Undetected ChromeDriver (Stealth bypass)
 - Standard Selenium with anti-detect flags (Universal fallback)
 - Remote CDP connection (Port 9222 for Chrome extensions / browser-use / existing browser)
 - Headless and Visible (Headed / Live) modes
"""

import os
import sys
import time
import socket
import random
import shutil
import subprocess
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def get_free_port():
    """Finds a free TCP port for isolated Chrome debugging."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
    except Exception:
        return random.randint(28000, 48000)

def get_config():
    """Reads settings from config.json with defaults."""
    cfg = {
        "kilo_cap": 175,
        "ainative_cap": 100,
        "port": 8008,
        "headless": True,
        "browser_engine": "auto",
        "cdp_port": 9222,
        "kilo_workers": 1,
        "ainative_workers": 1
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception:
            pass
    return cfg

def find_browser_executable():
    """Locates Chrome or Edge executable on Windows."""
    # 1. Check registry
    try:
        import winreg
        for subkey in [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey)
                path, _ = winreg.QueryValue(key, None)
                if path and os.path.isfile(path):
                    return path
            except Exception:
                pass
    except Exception:
        pass

    # 2. Check standard Chrome filesystem paths
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidates = [
        os.path.join(program_files, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(program_files_x86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(program_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(program_files, r"Microsoft\Edge\Application\msedge.exe"),
    ]

    for c in candidates:
        if os.path.isfile(c):
            return c

    return None

def create_browser(profile_dir=None, headless=None, engine=None, remote_port=None):
    """
    Creates and returns a configured browser instance.
    Returns: (driver, browser_pid)
    """
    cfg = get_config()
    if headless is None:
        headless = cfg.get("headless", True)
    if engine is None:
        engine = cfg.get("browser_engine", "auto")

    debug_port = get_free_port()
    browser_bin = find_browser_executable()

    # --- MODE 1: REMOTE CDP CONNECTION (For Extension / Browser-Use / Debugger) ---
    if engine == "cdp" or remote_port:
        cdp_p = remote_port or cfg.get("cdp_port", 9222)
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            opts = Options()
            opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{cdp_p}")
            driver = webdriver.Chrome(options=opts)
            return driver, None
        except Exception as e:
            print(f"[BROWSER] CDP connection to port {cdp_p} failed: {e}. Falling back to standard browser...")

    # --- MODE 2: UNDETECTED CHROMEDRIVER (Primary Stealth Engine) ---
    if engine in ["auto", "uc"]:
        try:
            import undetected_chromedriver as uc
            try:
                _orig_uc_del = getattr(uc.Chrome, "__del__", None)
                if _orig_uc_del:
                    def _safe_uc_del(self):
                        try:
                            _orig_uc_del(self)
                        except Exception:
                            pass
                    uc.Chrome.__del__ = _safe_uc_del
            except Exception:
                pass

            opts = uc.ChromeOptions()
            if profile_dir:
                os.makedirs(profile_dir, exist_ok=True)
                opts.add_argument(f"--user-data-dir={profile_dir}")
            opts.add_argument(f"--remote-debugging-port={debug_port}")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-notifications")
            opts.add_argument("--disable-popup-blocking")
            opts.add_argument("--password-store=basic")

            if browser_bin:
                opts.binary_location = browser_bin

            if headless:
                opts.add_argument("--headless=new")
                opts.add_argument("--window-position=-32000,-32000")
                opts.add_argument("--window-size=1280,720")
            else:
                opts.add_argument("--window-size=1200,900")
                opts.add_argument("--window-position=50,50")

            # Initialize uc.Chrome
            try:
                driver = uc.Chrome(options=opts, use_subprocess=True)
            except Exception:
                driver = uc.Chrome(options=opts)

            pid = getattr(driver, "browser_pid", None)
            return driver, pid

        except Exception as e:
            print(f"[BROWSER] Undetected-Chromedriver init failed ({e}). Falling back to Standard Selenium...")

    # --- MODE 3: STANDARD SELENIUM WITH ANTI-DETECT FLAGS (Universal Fallback) ---
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        if profile_dir:
            os.makedirs(profile_dir, exist_ok=True)
            opts.add_argument(f"--user-data-dir={profile_dir}")
        opts.add_argument(f"--remote-debugging-port={debug_port}")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option('useAutomationExtension', False)

        if browser_bin:
            opts.binary_location = browser_bin

        if headless:
            opts.add_argument("--headless=new")
            opts.add_argument("--window-position=-32000,-32000")
            opts.add_argument("--window-size=1280,720")
        else:
            opts.add_argument("--window-size=1200,900")
            opts.add_argument("--window-position=50,50")

        driver = webdriver.Chrome(options=opts)
        # Patch navigator.webdriver via CDP
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
            )
        except Exception:
            pass

        return driver, None

    except Exception as e:
        raise RuntimeError(f"All browser initialization attempts failed! Error: {e}")

def safe_close_browser(driver):
    """Safely closes driver avoiding WinError 6 / deallocator warnings."""
    if not driver:
        return
    try:
        if hasattr(driver, "__del__"):
            try:
                driver.__del__ = lambda: None
            except Exception:
                pass
        driver.quit()
    except Exception:
        pass

def launch_cdp_chrome(port=9222, profile_dir=None):
    """
    Launches an independent Chrome browser with remote debugging on specified port.
    Ideal for:
      - CSI extension connection
      - Browser-Use integration
      - Visual debugging and manual verification
    """
    browser_bin = find_browser_executable()
    if not browser_bin:
        raise RuntimeError("No Chrome or Edge installation found on system!")

    if not profile_dir:
        profile_dir = os.path.join(BASE_DIR, "bot_profiles", "cdp_shared_prof")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        browser_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1200,900",
        "--window-position=50,50"
    ]
    proc = subprocess.Popen(cmd)
    return proc.pid

def update_config(updates):
    """Updates config.json with key-value pairs."""
    cfg = get_config()
    cfg.update(updates)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        print(f"[CONFIG] Failed to write config: {e}")
        return False

def kill_bot_chrome(profile_keyword="bot_profiles"):
    """Surgically kills only bot Chrome instances matching the profile keyword."""
    try:
        ps_cmd = (
            f"Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.CommandLine -match '{profile_keyword}' }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    import argparse
    parser = argparse.ArgumentParser(description="Unified AI Gateway - Browser Manager")
    parser.add_argument("--test", action="store_true", help="Test browser initialization")
    parser.add_argument("--status", action="store_true", help="Show browser environment and config")
    parser.add_argument("--launch-cdp", type=int, nargs="?", const=9222, help="Launch Chrome on CDP port (default: 9222)")
    parser.add_argument("--set-headless", choices=["true", "false"], help="Set headless mode in config")
    parser.add_argument("--set-engine", choices=["auto", "uc", "selenium", "cdp"], help="Set engine in config")
    parser.add_argument("--set-cdp-port", type=int, help="Set default CDP port in config")
    parser.add_argument("--set-kilo-workers", type=int, help="Set Kilo parallel browser workers count (1-5)")
    parser.add_argument("--set-ainative-workers", type=int, help="Set AINative parallel browser workers count (1-5)")

    parser.add_argument("--visible", action="store_true", help="Run test with visible window")

    args = parser.parse_args()

    if args.status:
        cfg = get_config()
        bin_path = find_browser_executable()
        print("=== BROWSER SUBSYSTEM STATUS ===")
        print(f"Browser Executable : {bin_path or 'NOT FOUND'}")
        print(f"Engine Setting     : {cfg.get('browser_engine', 'auto')}")
        print(f"Headless Mode      : {cfg.get('headless', True)}")
        print(f"CDP Remote Port    : {cfg.get('cdp_port', 9222)}")
        print(f"Kilo Workers       : {cfg.get('kilo_workers', 1)}")
        print(f"AINative Workers   : {cfg.get('ainative_workers', 1)}")
        print("================================")
        sys.exit(0)

    if args.set_kilo_workers:
        update_config({"kilo_workers": max(1, min(5, args.set_kilo_workers))})
        print(f"[OK] Kilo workers set to: {args.set_kilo_workers}")
        sys.exit(0)

    if args.set_ainative_workers:
        update_config({"ainative_workers": max(1, min(5, args.set_ainative_workers))})
        print(f"[OK] AINative workers set to: {args.set_ainative_workers}")
        sys.exit(0)

    if args.set_headless:
        val = (args.set_headless == "true")
        update_config({"headless": val})
        print(f"[OK] Headless mode set to: {val}")
        sys.exit(0)

    if args.set_engine:
        update_config({"browser_engine": args.set_engine})
        print(f"[OK] Browser engine set to: {args.set_engine}")
        sys.exit(0)

    if args.set_cdp_port:
        update_config({"cdp_port": args.set_cdp_port})
        print(f"[OK] CDP port set to: {args.set_cdp_port}")
        sys.exit(0)

    if args.launch_cdp:
        port = args.launch_cdp
        print(f"[LAUNCH] Starting Chrome in Remote Debugging CDP Mode on port {port}...")
        try:
            pid = launch_cdp_chrome(port=port)
            print(f"[OK] Chrome running on port {port} (PID: {pid}).")
            print(f"     You can now connect CSI extensions or browser-use to http://127.0.0.1:{port}")
        except Exception as e:
            print(f"[ERROR] Failed to launch Chrome CDP: {e}")
        sys.exit(0)

    if args.test:
        cfg = get_config()
        is_headless = not args.visible if args.visible else cfg.get("headless", True)
        engine_name = cfg.get("browser_engine", "auto")
        mode_desc = "Visible (On-Screen)" if not is_headless else "Headless (Background)"

        print(f"[*] Initializing browser ({engine_name} | {mode_desc})...")
        t0 = time.time()
        drv = None
        try:
            drv, pid = create_browser(headless=is_headless, engine=engine_name)
            
            # 1. Fetch live web page for Pakistan Time & Date
            target_url = "https://timeapi.io/api/time/current/zone?timeZone=Asia/Karachi"
            print(f"[*] Navigating to live endpoint: {target_url} ...")
            drv.get(target_url)

            # 2. Extract DOM content from the real page
            body_text = drv.find_element("tag name", "body").text.strip()
            pak_date = "N/A"
            pak_time = "N/A"
            pak_day = "N/A"
            try:
                data = json.loads(body_text)
                pak_date = data.get("date", "N/A")
                pak_time = f"{data.get('time', 'N/A')}:{data.get('seconds', '00'):02d} PKT"
                pak_day = data.get("dayOfWeek", "")
            except Exception:
                pak_time = body_text[:60]

            # 3. Evaluate live JavaScript inside Chrome V8 engine
            js_eval = drv.execute_script("""
                return {
                    rendered_time: new Intl.DateTimeFormat('en-US', {
                        timeZone: 'Asia/Karachi',
                        dateStyle: 'full',
                        timeStyle: 'long'
                    }).format(new Date()),
                    user_agent: navigator.userAgent
                };
            """)

            latency = time.time() - t0
            safe_close_browser(drv)

            print("\n=======================================================")
            print("        REAL-TIME BROWSER VERIFICATION & DIAGNOSTIC")
            print("=======================================================")
            print(f" -> Browser Status    : VERIFIED & ACTIVE (PID: {pid or 'Attached'})")
            print(f" -> Engine & Mode     : {engine_name.upper()} ({mode_desc})")
            print(f" -> Live Web Source   : {target_url}")
            print(f" -> Pakistan Date     : {pak_date} ({pak_day})")
            print(f" -> Pakistan Time     : {pak_time}")
            print(f" -> Browser JS Engine : {js_eval.get('rendered_time')}")
            print(f" -> Render Latency    : {latency:.2f} seconds")
            print("=======================================================")
            print(" [SUCCESS] Browser is 100% genuine, rendering DOM/JS, and pulling live data!\n")
        except Exception as e:
            if drv:
                safe_close_browser(drv)
            print(f"[FAILED] Browser test error: {e}")
            sys.exit(1)
        sys.exit(0)

    parser.print_help()
