import os
import sys
import time
import traceback
import requests
import re
import html
import string
import random
import ctypes
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(BASE_DIR, "ainative_keys.txt")
LOG_PATH = os.path.join(BASE_DIR, "ainative.log")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROFILES_DIR = os.path.join(BASE_DIR, "bot_profiles")
DEDICATED_PROFILE = os.path.join(PROFILES_DIR, "ainative_prof")
PID_FILE = os.path.join(BASE_DIR, "bot_chrome_pids.txt")

os.makedirs(PROFILES_DIR, exist_ok=True)

def _boot_log(msg):
    t = time.strftime('%H:%M:%S')
    formatted = f"[{t}] [AINative] {msg}"
    print(formatted)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as _f:
            _f.write(formatted + "\n")
            _f.flush()
    except Exception:
        pass

sys.excepthook = lambda t, v, tb: _boot_log(f"💥 CRASH: {''.join(traceback.format_exception(t, v, tb))}")

_orig_popen = subprocess.Popen
_stealth_applied = False

class StealthPopen(_orig_popen):
    def __init__(self, *args, **kwargs):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = startupinfo
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
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


def get_free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]
    except: return random.randint(35000, 55000)

def generate_random_string(length=10):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

_last_config_mtime = 0
_last_config_val = 71
def get_target_cap():
    global _last_config_mtime, _last_config_val
    if os.path.exists(CONFIG_PATH):
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if mtime != _last_config_mtime:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _last_config_val = int(data.get("ainative_cap", 71))
                _last_config_mtime = mtime
            return _last_config_val
        except: pass
    return _last_config_val

_last_keys_mtime = 0
_last_keys_count = 0
def get_current_key_count():
    global _last_keys_mtime, _last_keys_count
    if not os.path.exists(SAVE_PATH): return 0
    try:
        mtime = os.path.getmtime(SAVE_PATH)
        if mtime != _last_keys_mtime:
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                _last_keys_count = len(lines)
            _last_keys_mtime = mtime
        return _last_keys_count
    except: return _last_keys_count

class MailTM:
    def __init__(self):
        self.base_url = "https://api.mail.tm"
        self.domain = self._get_domain()
        self.address = f"api{generate_random_string()}@{self.domain}"
        self.password = "TestPassword123!"
        self._create_account()
        self.token = self._get_token()

    def _get_domain(self):
        res = requests.get(f"{self.base_url}/domains", timeout=8)
        return res.json()['hydra:member'][0]['domain']

    def _create_account(self):
        requests.post(f"{self.base_url}/accounts", json={"address": self.address, "password": self.password}, timeout=8)

    def _get_token(self):
        for _ in range(4):
            try:
                res = requests.post(f"{self.base_url}/token", json={"address": self.address, "password": self.password}, timeout=8)
                if res.status_code == 200:
                    data = res.json()
                    if 'token' in data and data['token']:
                        return data['token']
            except Exception:
                pass
            time.sleep(1.5)
        res = requests.post(f"{self.base_url}/token", json={"address": self.address, "password": self.password}, timeout=8)
        return res.json().get('token', '')

    def get_verification_token_and_link(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        for _ in range(25):
            time.sleep(2)
            try:
                res = requests.get(f"{self.base_url}/messages", headers=headers, timeout=5).json()
                if msgs := res.get('hydra:member', []):
                    body = requests.get(f"{self.base_url}/messages/{msgs[0]['id']}", headers=headers, timeout=5).json()
                    raw_html = body.get('html', '') or body.get('text', '')
                    if isinstance(raw_html, list): raw_html = " ".join(raw_html)
                    unescaped = html.unescape(str(raw_html))
                    tok = None
                    tok_match = re.search(r'verify-email\?token=([a-zA-Z0-9_\-\.]+)', unescaped)
                    if tok_match:
                        tok = tok_match.group(1)
                    elif (t2 := re.search(r'token=([a-zA-Z0-9_\-\.]+)', unescaped)):
                        tok = t2.group(1)
                    link = None
                    link_match = re.search(r'https?://(?:[a-zA-Z0-9\-]+\.)?ainative\.studio/[^\s"\'<>\\]+', unescaped)
                    if link_match:
                        link = link_match.group(0)
                    if tok or link:
                        return tok, link
            except Exception:
                pass
        return None, None

_key_file_lock = threading.Lock()

def clean_worker_profile(prof_dir):
    if os.path.exists(prof_dir):
        try: shutil.rmtree(prof_dir, ignore_errors=True)
        except: pass

def kill_worker_chrome(prof_keyword):
    browser_manager.kill_bot_chrome(prof_keyword)

def log_w(worker_id, msg):
    prefix = f"[W{worker_id}] " if worker_id is not None else ""
    _boot_log(f"{prefix}{msg}")

def run_worker(worker_id=0, visible=False, run_once=False, engine=None, cdp_port=None):
    prof_keyword = f"ainative_prof_w{worker_id}"
    prof_dir = os.path.join(PROFILES_DIR, prof_keyword)
    clean_worker_profile(prof_dir)

    while True:
        target_cap = get_target_cap()
        current_count = get_current_key_count()
        if not run_once and current_count >= target_cap:
            log_w(worker_id, f"⏸️ Target of {target_cap} reached. Hibernating...")
            time.sleep(3)
            continue
            
        log_w(worker_id, f"🔄 Stock: {current_count}/{target_cap}. Starting API run...")
        kill_worker_chrome(prof_keyword)
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        try:
            # 1. API: Create Email & Register
            mail = MailTM()
            log_w(worker_id, f"✅ Fast API Email: {mail.address}")
            
            reg_res = session.post("https://api.ainative.studio/api/v1/auth/register", json={
                "email": mail.address,
                "password": mail.password,
                "name": "Kilo Automation"
            }, timeout=10)
            
            if reg_res.status_code not in (200, 201):
                log_w(worker_id, f"⚠️ API Registration failed: {reg_res.text}")
                continue
                
            # 2. API: Fetch Email & Verify
            log_w(worker_id, "📡 Waiting for backend verification token...")
            vtoken, link = mail.get_verification_token_and_link()
            if not vtoken and not link:
                log_w(worker_id, "❌ Verification timeout. Retrying...")
                continue
                
            if vtoken:
                v_res = session.post("https://api.ainative.studio/api/v1/auth/verify-email", json={"token": vtoken}, timeout=10)
                if v_res.status_code != 200:
                    try: session.get(f"https://api.ainative.studio/api/v1/auth/verify-email?token={vtoken}", timeout=10)
                    except: pass
            if link:
                try: session.get(link, timeout=10)
                except: pass
            log_w(worker_id, "✅ Verified instantly via API!")
            
            # 3. API: Login
            log_res = session.post("https://api.ainative.studio/api/v1/auth/login", json={
                "email": mail.address,
                "password": mail.password
            }, timeout=10)
            
            if log_res.status_code not in (200, 201):
                log_w(worker_id, f"⚠️ API Login failed ({log_res.status_code}): {log_res.text[:80]}. Retrying...")
                continue

            access_token = log_res.json().get("access_token", "")
            log_w(worker_id, "🚀 Logged in via API. Generating API key...")
            
            # 4. Instant Direct API Key Generation (Zero browser RAM needed!)
            api_key = ""
            try:
                key_res = session.post(
                    "https://api.ainative.studio/api/v1/api-keys",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"name": "GatewayKey"},
                    timeout=10
                )
                if key_res.status_code in (200, 201):
                    api_key = key_res.json().get("api_key", "")
            except Exception:
                pass

            # Fallback to Browser Extraction only if API creation didn't return key
            if not api_key:
                clean_worker_profile(prof_dir)
                os.makedirs(prof_dir, exist_ok=True)
                actual_cdp_port = (cdp_port + worker_id) if cdp_port else None
                driver, browser_pid = browser_manager.create_browser(
                    profile_dir=prof_dir,
                    headless=(not visible),
                    engine=engine,
                    remote_port=actual_cdp_port
                )
                
                driver.get("https://ainative.studio") # Initial load to set domain cookies
                for cookie in session.cookies:
                    driver.add_cookie({"name": cookie.name, "value": cookie.value, "domain": ".ainative.studio"})
                
                driver.get("https://ainative.studio/dashboard/api-keys")
                time.sleep(2)
                
                driver.execute_script("""
                    var buttons = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
                    var btn = buttons.find(b => (b.innerText || '').toLowerCase().includes('create api'));
                    if (btn) btn.click();
                """)
                time.sleep(1)
                driver.execute_script("""
                    var inputs = Array.from(document.querySelectorAll('input'));
                    var target = inputs.find(i => i.placeholder && i.placeholder.includes('API Key')) || inputs[0];
                    if (target) {
                        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                        nativeSetter.call(target, "GatewayKey");
                        target.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    var modal_btns = Array.from(document.querySelectorAll('button'));
                    var gen = modal_btns.find(b => (b.innerText || '').toLowerCase().includes('create'));
                    if (gen) gen.click();
                """)
                time.sleep(2)
                
                for _ in range(5):
                    page_html = driver.page_source
                    matches = re.findall(r'sk_[a-zA-Z0-9_\-]{20,}', page_html)
                    if matches and len(matches[0]) >= 28:
                        api_key = matches[0]
                        break
                    time.sleep(0.5)

                browser_manager.safe_close_browser(driver)
                kill_worker_chrome(prof_keyword)

            if api_key:
                log_w(worker_id, f"🔑 API key found: {api_key[:15]}...")
                with _key_file_lock:
                    with open(SAVE_PATH, "a", encoding="utf-8") as f:
                        f.write(api_key + "\n")
                log_w(worker_id, "💾 Saved! Next run starting...\n")
                if run_once:
                    log_w(worker_id, "🏁 Finished single-key harvest (--once). Exiting successfully.")
                    return
            else:
                log_w(worker_id, "❌ Could not extract API key. Retrying...\n")
                if run_once:
                    log_w(worker_id, "❌ Harvest attempt failed in single-run mode (--once).")
                    return

        except Exception as e:
            log_w(worker_id, f"❌ Error: {str(e)[:100]}... Retrying.")
            kill_worker_chrome(prof_keyword)
            if run_once:
                log_w(worker_id, "❌ Harvest attempt failed in single-run mode (--once).")
                return
            time.sleep(2)

def run(visible=False, run_once=False, engine=None, cdp_port=None, workers=None):
    if not visible:
        enable_stealth_popen()

    cfg = browser_manager.get_config()
    target_cap = get_target_cap()
    mode_str = "Live Visible" if visible else "Headless Background"
    
    num_workers = int(workers or cfg.get("ainative_workers", 1))
    if run_once:
        num_workers = 1

    _boot_log(f"🚀 AINative Hybrid API-Bot Started ({mode_str} | Cap: {target_cap} | Parallel Workers: {num_workers})")

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
            _boot_log("🛑 Process interrupted. Stopping worker threads...")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AINative Studio Key Harvester")
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
    workers_count = args.workers or cfg.get("ainative_workers", 1)

    try:
        run(visible=is_vis, run_once=args.once, engine=eng, cdp_port=port, workers=workers_count)
    except Exception as e:
        _boot_log(f"💥 CRASH: {traceback.format_exc()}")

