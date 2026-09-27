import time
import requests
import re
import string
import random
import os
import sys
import ctypes
import tempfile
import shutil
import uuid
import json
import socket
import threading
import subprocess

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import browser_manager

# Lazy StealthPopen: Only activated in headless mode so visible mode renders properly
_orig_popen = subprocess.Popen
_stealth_applied = False

class StealthPopen(_orig_popen):
    def __init__(self, *args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        
        if "chrome" in cmd_str.lower():
            startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE: Window is hidden from birth
            kwargs["startupinfo"] = startupinfo
            
            flags = kwargs.get("creationflags", 0)
            flags |= 0x08000000  # CREATE_NO_WINDOW: Zero console/window flash
            kwargs["creationflags"] = flags
            
        super().__init__(*args, **kwargs)

def enable_stealth_popen():
    global _stealth_applied
    if not _stealth_applied:
        try:
            uc.dprocess.Popen = StealthPopen
        except Exception:
            pass
        subprocess.Popen = StealthPopen
        _stealth_applied = True


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(BASE_DIR, "kilo_keys.txt")
LOG_PATH = os.path.join(BASE_DIR, "kilo.log")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROFILES_DIR = os.path.join(BASE_DIR, "bot_profiles")
DEDICATED_PROFILE = os.path.join(PROFILES_DIR, "kilo_prof")
PID_FILE = os.path.join(BASE_DIR, "bot_chrome_pids.txt")

os.makedirs(PROFILES_DIR, exist_ok=True)

def get_free_port():
    """Finds a random free TCP port to guarantee 100% isolation from personal Chrome."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
    except:
        return random.randint(25000, 45000)

_last_config_mtime = 0
_last_config_val = 168
def get_target_cap():
    global _last_config_mtime, _last_config_val
    if os.path.exists(CONFIG_PATH):
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime != _last_config_mtime:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _last_config_val = data.get("kilo_cap", 168)
                _last_config_mtime = mtime
            return _last_config_val
        except:
            pass
    return _last_config_val

def prune_log_file():
    try:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            runs = content.split("🔄 Stock:")
            if len(runs) > 3:
                new_content = "🔄 Stock:" + "🔄 Stock:".join(runs[-3:])
                with open(LOG_PATH, "w", encoding="utf-8") as f:
                    f.write(new_content)
    except:
        pass

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
            f.flush()
        if "Stock:" in msg or "Hibernation" in msg:
            prune_log_file()
    except:
        pass

def save_bot_pid(pid):
    """Saves the bot Chrome PID to a tracking file so stop_all can kill ONLY bot Chrome."""
    try:
        with open(PID_FILE, "a", encoding="utf-8") as f:
            f.write(str(pid) + "\n")
    except:
        pass

def remove_bot_pid(pid):
    """Removes a bot Chrome PID from the tracking file."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                pids = [line.strip() for line in f if line.strip() and line.strip() != str(pid)]
            with open(PID_FILE, "w") as f:
                f.write("\n".join(pids) + "\n" if pids else "")
    except:
        pass
_key_file_lock = threading.Lock()

def kill_bot_chrome_by_pid(pid, profile_path=None):
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except: pass

    if profile_path:
        try:
            prof_name = os.path.basename(profile_path)
            ps_cmd = f"Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | Where-Object {{ $_.CommandLine -match '{prof_name}' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass
    remove_bot_pid(pid)

def verify_no_running_bot_chrome(profile_keyword="kilo_prof"):
    """
    Verifies that exactly 0 Chrome processes for this bot profile exist.
    Surgically scoped to profile_keyword so parallel workers don't kill each other!
    """
    ps_cmd = f"""
    $botChrome = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {{ $_.CommandLine -match '{profile_keyword}' }}
    if ($botChrome) {{
        $botChrome | ForEach-Object {{
            try {{ taskkill /F /T /PID $_.ProcessId 2>$null | Out-Null }} catch {{}}
            try {{ Stop-Process -Id $_.ProcessId -Force 2>$null | Out-Null }} catch {{}}
        }}
        Start-Sleep -Milliseconds 250
    }}
    $rem = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {{ $_.CommandLine -match '{profile_keyword}' }}
    if ($rem) {{ exit 1 }} else {{ exit 0 }}
    """
    for _ in range(3):
        res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return True
        time.sleep(0.3)
    return True

def close_extra_tabs(driver):
    """Kills any useless background tabs to strictly save RAM."""
    try:
        handles = driver.window_handles
        if len(handles) > 1:
            main_handle = handles[-1]
            for h in handles:
                if h != main_handle:
                    driver.switch_to.window(h)
                    driver.close()
            driver.switch_to.window(main_handle)
    except:
        pass

def generate_random_string(length=10):
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for _ in range(length))

def check_internet():
    try:
        requests.get("https://1.1.1.1", timeout=3)
        return True
    except:
        return False

def wait_for_internet():
    if not check_internet():
        log("⚠️ Internet connection lost! Waiting...")
        while not check_internet():
            time.sleep(5)
        log("✅ Internet connection restored!")

_last_keys_mtime = 0
_last_keys_count = 0
def get_current_key_count():
    global _last_keys_mtime, _last_keys_count
    if not os.path.exists(SAVE_PATH):
        return 0
    try:
        mtime = os.path.getmtime(SAVE_PATH)
        if mtime != _last_keys_mtime:
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                _last_keys_count = len(lines)
            _last_keys_mtime = mtime
        return _last_keys_count
    except Exception as e:
        return _last_keys_count

class MailTM:
    def __init__(self):
        self.base_url = "https://api.mail.tm"
        self.domain = self._get_domain()
        self.address = f"{generate_random_string()}@{self.domain}"
        self.password = "SuperSecretPassword123!"
        self.token = None
        self._create_account()
        self._get_token()

    def _get_domain(self):
        res = requests.get(f"{self.base_url}/domains", timeout=10)
        return res.json()['hydra:member'][0]['domain']

    def _create_account(self):
        data = {"address": self.address, "password": self.password}
        requests.post(f"{self.base_url}/accounts", json=data, timeout=10)

    def _get_token(self):
        data = {"address": self.address, "password": self.password}
        for _ in range(4):
            try:
                res = requests.post(f"{self.base_url}/token", json=data, timeout=10)
                if res.status_code == 200:
                    d = res.json()
                    if 'token' in d and d['token']:
                        self.token = d['token']
                        return
            except Exception:
                pass
            time.sleep(1.5)
        res = requests.post(f"{self.base_url}/token", json=data, timeout=10)
        self.token = res.json().get('token', '')

    def get_magic_link(self):
        log("📡 Waiting for email...")
        headers = {"Authorization": f"Bearer {self.token}"}
        for _ in range(30):
            time.sleep(2)
            try:
                res = requests.get(f"{self.base_url}/messages", headers=headers, timeout=5)
                messages = res.json().get('hydra:member', [])
                if messages:
                    msg_id = messages[0]['id']
                    msg_res = requests.get(f"{self.base_url}/messages/{msg_id}", headers=headers, timeout=5)
                    
                    body = msg_res.json().get('html', '') or msg_res.json().get('text', '')
                    if isinstance(body, list):
                        body = " ".join(body)
                    body = str(body)
                    
                    match = re.search(r'https://email\.app\.kilocode\.ai/c/[^\s\"\'\>\\]+', body)
                    if not match:
                        match = re.search(r'https://[^\s\"\'\>\\]*(?:kilo|kilocode)[^\s\"\'\>\\]*/c/[^\s\"\'\>\\]+', body)
                    if match:
                        return match.group(0)
            except:
                pass
        return None

def clean_old_bot_profiles():
    """Safely cleans up old temporary bot profile directories."""
    try:
        if os.path.exists(PROFILES_DIR):
            for item in os.listdir(PROFILES_DIR):
                item_path = os.path.join(PROFILES_DIR, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
    except:
        pass
def log_w(worker_id, msg):
    prefix = f"[W{worker_id}] " if worker_id is not None else ""
    log(f"{prefix}{msg}")

def run_worker(worker_id=0, visible=False, run_once=False, engine=None, cdp_port=None):
    prof_keyword = f"kilo_prof_w{worker_id}"
    worker_profile_dir = os.path.join(PROFILES_DIR, prof_keyword)

    while True:
        wait_for_internet()
        target_cap = get_target_cap()

        current_count = get_current_key_count()
        if not run_once and current_count >= target_cap:
            log(f"⏸️ Target of {target_cap} keys reached ({current_count}/{target_cap}). Entering zero-CPU hibernation mode...")
            last_logged_cap = target_cap
            while True:
                time.sleep(1.5)
                new_count = get_current_key_count()
                new_cap = get_target_cap()
                if new_cap != last_logged_cap:
                    last_logged_cap = new_cap
                    target_cap = new_cap
                    if new_count >= new_cap:
                        log(f"⚙️ Target cap updated to {new_cap}. Target already met ({new_count}/{new_cap}). Still hibernating...")
                    else:
                        log(f"⚡ Target cap raised to {new_cap}! Stock is {new_count}/{new_cap}. Waking up instantly...")
                        break
                elif new_count < new_cap:
                    log(f"⚡ Stock dropped to {new_count}/{new_cap}! Waking up instantly...")
                    target_cap = new_cap
                    break
            continue

        log_w(worker_id, f"🔄 Stock: {current_count}/{target_cap}. Starting new run...")
        verify_no_running_bot_chrome(prof_keyword)
        log_w(worker_id, f"🛡️ Verified 0 Chrome instances for worker {worker_id}. Starting browser...")
        log_w(worker_id, "✉️ Creating email...")

        driver = None
        temp_profile_dir = None
        browser_pid = None
        stop_stealth_thread = None
        try:
            mail_account = MailTM()
            email = mail_account.address
            log_w(worker_id, f"✅ Email created: {email}")

            temp_profile_dir = worker_profile_dir
            if os.path.exists(temp_profile_dir):
                try: shutil.rmtree(temp_profile_dir, ignore_errors=True)
                except Exception: pass
            os.makedirs(temp_profile_dir, exist_ok=True)

            log_w(worker_id, "🌐 Launching browser via Browser Manager...")
            actual_cdp_port = (cdp_port + worker_id) if cdp_port else None
            driver, browser_pid = browser_manager.create_browser(
                profile_dir=temp_profile_dir,
                headless=(not visible),
                engine=engine,
                remote_port=actual_cdp_port
            )

            if browser_pid:
                save_bot_pid(browser_pid)

            if not visible:
                stop_stealth_thread = threading.Event()
                def stealth_worker():
                    user32 = ctypes.windll.user32
                    GWL_EXSTYLE = -20
                    WS_EX_TOOLWINDOW = 0x00000080
                    WS_EX_APPWINDOW = 0x00040000
                    SW_HIDE = 0
                    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                    def enum_fn(hwnd, lparam):
                        try:
                            if not browser_pid: return True
                            pid = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            if pid.value != browser_pid: return True
                            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                            if not (ex & WS_EX_TOOLWINDOW):
                                ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
                            user32.ShowWindow(hwnd, SW_HIDE)
                        except Exception: pass
                        return True
                    
                    cb = WNDENUMPROC(enum_fn)
                    while not stop_stealth_thread.is_set():
                        try:
                            if browser_pid:
                                user32.EnumWindows(cb, 0)
                        except Exception: pass
                        time.sleep(0.02)

                stealth_thread = threading.Thread(target=stealth_worker, daemon=True)
                stealth_thread.start()

            driver.get("https://app.kilo.ai/users/sign_in")
            close_extra_tabs(driver)
            log("✅ Website opened")
            
            try:
                email_input = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "sign-in-email")))
            except:
                log("⚠️ Cloudflare detected! Waiting...")
                try:
                    email_input = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "sign-in-email")))
                    log("✅ Cloudflare passed")
                except:
                    log("❌ Cloudflare timeout. Nuking browser data and retrying...")
                    if browser_pid:
                        kill_bot_chrome_by_pid(browser_pid, temp_profile_dir)
                    try: driver.quit()
                    except: pass
                    shutil.rmtree(temp_profile_dir, ignore_errors=True)
                    continue

            log("✍️ Pasting email...")
            email_input.clear()
            
            driver.execute_script("""
                var input = arguments[0];
                var value = arguments[1];
                var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                nativeSetter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            """, email_input, email)

            time.sleep(1)

            log("📩 Submitting sign-in form...")
            # Click Continue button directly (more reliable than form.requestSubmit)
            submitted = driver.execute_script("""
                var buttons = Array.from(document.querySelectorAll('button'));
                var btn = buttons.find(b => (b.innerText && b.innerText.trim().toLowerCase().includes('continue')) || b.type === 'submit');
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            """)
            if not submitted:
                try:
                    form = driver.find_element(By.TAG_NAME, "form")
                    driver.execute_script("arguments[0].requestSubmit();", form)
                except:
                    pass

            log("✅ Form submitted")

            log_w(worker_id, "📩 Requesting magic link...")
            magic_btn = None
            for _ in range(25):
                try:
                    magic_btn = driver.execute_script("""
                        var buttons = Array.from(document.querySelectorAll('button, a'));
                        return buttons.find(b => b.innerText && b.innerText.toLowerCase().includes('magic link'));
                    """)
                    if magic_btn:
                        break
                except:
                    pass
                time.sleep(0.5)

            if not magic_btn:
                # Check if security verification / challenge is present on screen
                page_src = ""
                try: page_src = driver.page_source.lower()
                except: pass
                if any(x in page_src for x in ["security verification", "complete this verification", "turnstile", "cf-turnstile"]):
                    log_w(worker_id, "⚠️ Security verification required on page. Switch to Visible mode (api browser / web dashboard) to complete verification.")
                    time.sleep(4)
                
                try:
                    magic_btn = WebDriverWait(driver, 8).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Email me a magic link') or contains(., 'magic link')]"))
                    )
                except Exception:
                    raise RuntimeError("Magic link button not ready (verification challenge or form delay)")

            time.sleep(0.5)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", magic_btn)
            log_w(worker_id, "✅ Email sent")
            
            link = mail_account.get_magic_link()
            if not link:
                log("❌ Magic link timeout. Nuking browser data and retrying...")
                if browser_pid:
                    kill_bot_chrome_by_pid(browser_pid, temp_profile_dir)
                try: driver.quit()
                except: pass
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
                continue
                
            log("🔗 Link extracted from email")
            log("🌐 Opening link...")
            driver.get(link)
            close_extra_tabs(driver)
            log("✅ Link opened")
            
            api_key = ""
            start_time = time.time()
            while time.time() - start_time < 20:
                try:
                    elem = driver.find_element(By.ID, "api-key")
                    val = elem.get_attribute("value") or elem.text
                    if val and len(val.strip()) > 40:
                        api_key = val.strip()
                        break
                except:
                    pass

                if not api_key:
                    try:
                        for input_el in driver.find_elements(By.TAG_NAME, "input"):
                            val = input_el.get_attribute("value") or ""
                            if val.startswith("eyJ") and len(val) > 40:
                                api_key = val.strip()
                                break
                    except:
                        pass
                
                time.sleep(1)

            if api_key:
                log_w(worker_id, "🔑 API key found!")
                with _key_file_lock:
                    with open(SAVE_PATH, "a", encoding="utf-8") as f:
                        f.write(api_key + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                
                new_count = get_current_key_count()
                log_w(worker_id, f"💾 API key saved! Total keys in file: {new_count}/{target_cap}")
            else:
                log_w(worker_id, "❌ Could not extract API key within 20s. Nuking browser data and retrying...")
            
            if stop_stealth_thread:
                stop_stealth_thread.set()
            log_w(worker_id, "🧹 Nuking browser data entirely...\n")
            if browser_pid:
                kill_bot_chrome_by_pid(browser_pid, temp_profile_dir)
            browser_manager.safe_close_browser(driver)
            shutil.rmtree(temp_profile_dir, ignore_errors=True)
            verify_no_running_bot_chrome(prof_keyword)
            log_w(worker_id, f"🛡️ Verified 0 Chrome instances for worker {worker_id} before next loop.")

            if api_key and run_once:
                log_w(worker_id, "🏁 Finished single-key harvest (--once). Exiting successfully.")
                return

            time.sleep(2)
            
        except Exception as e:
            if stop_stealth_thread:
                stop_stealth_thread.set()
            err_msg = str(e).strip()
            if "Stacktrace:" in err_msg:
                err_msg = err_msg.split("Stacktrace:")[0].strip()
            if not err_msg or err_msg == "Message:" or err_msg.startswith("Message:"):
                err_msg = f"{type(e).__name__} (Element interaction timed out or verification challenge active)"
            log_w(worker_id, f"❌ Error encountered: {err_msg[:120]}... Nuking browser data and retrying...")
            if browser_pid:
                kill_bot_chrome_by_pid(browser_pid, temp_profile_dir)
            browser_manager.safe_close_browser(driver)
            if temp_profile_dir and os.path.exists(temp_profile_dir):
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
            verify_no_running_bot_chrome(prof_keyword)

            if run_once:
                log_w(worker_id, "❌ Harvest attempt failed in single-run mode (--once).")
                return
                
            if "HTTPSConnectionPool" in err_msg or "Max retries" in err_msg or "NameResolutionError" in err_msg:
                log_w(worker_id, "⚠️ Mail.tm connection blocked/down! Cooling down for 60 seconds...")
                time.sleep(60)
            else:
                time.sleep(3)

def run(visible=False, run_once=False, engine=None, cdp_port=None, workers=None):
    if not visible:
        enable_stealth_popen()

    cfg = browser_manager.get_config()
    target_cap = get_target_cap()
    mode_str = "Live Visible" if visible else "Headless Background"
    
    num_workers = int(workers or cfg.get("kilo_workers", 1))
    if run_once:
        num_workers = 1

    log(f"🚀 Smart Kilo Automator Started ({mode_str} | Cap: {target_cap} | Parallel Workers: {num_workers})")
    log(f"📁 Saving to: {SAVE_PATH}\n")
    
    clean_old_bot_profiles()
    try:
        open(PID_FILE, "w").close()
    except Exception:
        pass

    if num_workers <= 1:
        run_worker(worker_id=0, visible=visible, run_once=run_once, engine=engine, cdp_port=cdp_port)
    else:
        threads = []
        for i in range(num_workers):
            t = threading.Thread(
                target=run_worker,
                kwargs={
                    "worker_id": i,
                    "visible": visible,
                    "run_once": run_once,
                    "engine": engine,
                    "cdp_port": cdp_port
                },
                daemon=True
            )
            threads.append(t)
            t.start()
            time.sleep(3.5)

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            log("🛑 Process interrupted. Stopping worker threads...")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kilo Code Key Harvester")
    parser.add_argument("--visible", "--live", "--headed", action="store_true", help="Watch browser live on screen")
    parser.add_argument("--headless", action="store_true", help="Force headless background mode")
    parser.add_argument("--once", action="store_true", help="Harvest exactly 1 key and exit")
    parser.add_argument("--engine", choices=["auto", "uc", "selenium", "cdp"], default=None, help="Browser engine")
    parser.add_argument("--cdp-port", type=int, default=None, help="Remote CDP port")
    parser.add_argument("--workers", type=int, default=None, help="Number of concurrent parallel browser workers (1-5)")
    args = parser.parse_args()

    cfg = browser_manager.get_config()
    is_vis = args.visible
    if not is_vis and not args.headless:
        is_vis = not cfg.get("headless", True)

    eng = args.engine or cfg.get("browser_engine", "auto")
    port = args.cdp_port or cfg.get("cdp_port", 9222)
    workers_count = args.workers or cfg.get("kilo_workers", 1)

    run(visible=is_vis, run_once=args.once, engine=eng, cdp_port=port, workers=workers_count)

