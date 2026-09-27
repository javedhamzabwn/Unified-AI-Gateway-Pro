import os
import json
import random
import requests
import re
import sys
import subprocess
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse
import logging

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import browser_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KILO_KEY_FILE = os.path.join(BASE_DIR, "kilo_keys.txt")
AINATIVE_KEY_FILE = os.path.join(BASE_DIR, "ainative_keys.txt")
LOG_PATH = os.path.join(BASE_DIR, "proxy.log")
DASHBOARD_FILE = os.path.join(BASE_DIR, "dashboard.html")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

KILO_URL = "https://api.kilo.ai/api/gateway/chat/completions"
AINATIVE_URL = "https://api.ainative.studio/v1/chat/completions"

app = FastAPI(title="Unified Kilo & AINative Proxy Gateway")

def log(msg):
    print(f"[PROXY] {msg}")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[PROXY] {msg}\n")
    except Exception:
        pass

def get_keys(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def delete_key(filepath, key_to_delete):
    keys = get_keys(filepath)
    keys = [k for k in keys if k != key_to_delete]
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(keys) + ("\n" if keys else ""))
    except Exception:
        pass

def check_running_processes():
    res = {"kilo": False, "ainative": False, "proxy": True, "tunnel": False}
    try:
        cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_Process | Select-Object -ExpandProperty CommandLine"'
        output = subprocess.check_output(cmd, shell=True, text=True, timeout=2, creationflags=0x08000000)
        out_lower = output.lower()
        res["kilo"] = "kilo_mailtm" in out_lower
        res["ainative"] = "ainative_mailtm" in out_lower
        res["tunnel"] = "localtunnel" in out_lower
    except Exception:
        pass
    return res

def get_tunnel_url():
    tunnel_log = os.path.join(BASE_DIR, "tunnel.log")
    if os.path.exists(tunnel_log):
        try:
            with open(tunnel_log, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r'your url is:\s*(https://[^\s]+)', content)
            if match:
                return match.group(1).rstrip('/')
        except Exception:
            pass
    clean_username = re.sub(r'[^a-z0-9]', '', os.environ.get("USERNAME", "user").lower())
    return f"https://kilo-api-{clean_username}.loca.lt"

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    if os.path.exists(DASHBOARD_FILE):
        with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>Dashboard file not found.</h2>", status_code=404)

@app.get("/api/status")
async def get_status():
    cfg = browser_manager.get_config()
    kilo_keys = get_keys(KILO_KEY_FILE)
    ainative_keys = get_keys(AINATIVE_KEY_FILE)
    return JSONResponse({
        "status": "online",
        "port": cfg.get("port", 8008),
        "kilo_count": len(kilo_keys),
        "kilo_cap": cfg.get("kilo_cap", 175),
        "kilo_workers": cfg.get("kilo_workers", 1),
        "ainative_count": len(ainative_keys),
        "ainative_cap": cfg.get("ainative_cap", 100),
        "ainative_workers": cfg.get("ainative_workers", 1),
        "browser_engine": cfg.get("browser_engine", "auto"),
        "headless": cfg.get("headless", True),
        "cdp_port": cfg.get("cdp_port", 9222),
        "tunnel_url": get_tunnel_url(),
        "processes": check_running_processes()
    })

@app.get("/api/logs/{service}")
async def get_logs(service: str):
    file_map = {
        "kilo": os.path.join(BASE_DIR, "kilo.log"),
        "ainative": os.path.join(BASE_DIR, "ainative.log"),
        "proxy": os.path.join(BASE_DIR, "proxy.log"),
        "tunnel": os.path.join(BASE_DIR, "tunnel.log")
    }
    log_file = file_map.get(service.lower())
    if not log_file or not os.path.exists(log_file):
        return JSONResponse({"service": service, "lines": []})
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip() for line in f.readlines() if line.strip()]
            return JSONResponse({"service": service, "lines": lines[-100:]})
    except Exception as e:
        return JSONResponse({"service": service, "lines": [f"Error reading log: {e}"]})

@app.get("/api/errors")
async def get_errors():
    error_list = []
    log_files = [
        ("kilo", os.path.join(BASE_DIR, "kilo.log")),
        ("ainative", os.path.join(BASE_DIR, "ainative.log")),
        ("proxy", os.path.join(BASE_DIR, "proxy.log")),
        ("tunnel", os.path.join(BASE_DIR, "tunnel.log"))
    ]
    for service, path in log_files:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            for line in lines[-50:]:
                if any(k in line.lower() for k in ["❌", "error", "fail", "timeout", "blocked", "cloudflare", "crash", "denied"]):
                    hint = "Check service logs or network connection."
                    clean_msg = line
                    if "Message:" in clean_msg:
                        clean_msg = re.sub(r'Message:\s*', 'Timeout/Interaction error: ', clean_msg)
                        
                    if "cloudflare" in line.lower() or "security verification" in line.lower():
                        hint = "Security verification on website. Launch Visible mode from dashboard to complete verification."
                    elif "magic link" in line.lower() or "timeout" in line.lower() or "mail.tm" in line.lower():
                        hint = "Temporary email service connection lagged or timed out. Script retries automatically."
                    elif "invalid/exhausted" in line.lower():
                        hint = "API key expired or depleted and was safely purged from key inventory."
                    
                    time_match = re.search(r'\[([0-9:]+)\]', line)
                    ts = time_match.group(1) if time_match else ""
                    error_list.append({
                        "service": service,
                        "timestamp": ts,
                        "message": clean_msg,
                        "hint": hint,
                        "tag": "Warning" if ("cloudflare" in line.lower() or "timeout" in line.lower() or "security" in line.lower()) else "Error"
                    })
        except Exception:
            pass
    return JSONResponse({"errors": error_list[-25:]})

@app.post("/api/action")
async def perform_action(req: Request):
    data = await req.json()
    action = data.get("action", "")
    
    if action == "start":
        ps_cmd = os.path.join(BASE_DIR, "start_all.ps1")
        subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_cmd], creationflags=0x08000000)
        return JSONResponse({"status": "ok", "message": "Gateway and background bots starting..."})
        
    elif action == "stop":
        ps_cmd = os.path.join(BASE_DIR, "stop_all.ps1")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Start-Sleep -Milliseconds 600; & '{ps_cmd}'"], creationflags=0x08000000)
        return JSONResponse({"status": "ok", "message": "System stop initiated. Shutting down all bots and proxy..."})
        
    elif action == "harvest_kilo":
        script = os.path.join(BASE_DIR, "kilo_mailtm.py")
        subprocess.Popen(["python", script, "--visible", "--once"], creationflags=0x08000000)
        return JSONResponse({"status": "ok", "message": "Single Kilo Code live harvest launched on-screen."})
        
    elif action == "harvest_ainative":
        script = os.path.join(BASE_DIR, "ainative_mailtm.py")
        subprocess.Popen(["python", script, "--visible", "--once"], creationflags=0x08000000)
        return JSONResponse({"status": "ok", "message": "Single AINative Studio live harvest launched on-screen."})
        
    elif action == "cdp_launch":
        cfg = browser_manager.get_config()
        port = cfg.get("cdp_port", 9222)
        try:
            pid = browser_manager.launch_cdp_chrome(port=port)
            return JSONResponse({"status": "ok", "message": f"Chrome running on CDP port {port} (PID: {pid}). Ready for CSI / Browser-Use."})
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
            
    elif action == "set_browser":
        headless_val = data.get("headless")
        engine_val = data.get("browser_engine")
        updates = {}
        if headless_val is not None:
            updates["headless"] = bool(headless_val)
        if engine_val:
            updates["browser_engine"] = str(engine_val)
        browser_manager.update_config(updates)
        return JSONResponse({"status": "ok", "message": "Browser settings updated."})
        
    elif action == "save_config":
        updates = {}
        for key in ["kilo_cap", "ainative_cap", "kilo_workers", "ainative_workers", "browser_engine", "cdp_port", "port"]:
            if key in data and data[key] is not None:
                updates[key] = data[key]
        browser_manager.update_config(updates)
        return JSONResponse({"status": "ok", "message": "Configuration saved."})
        
    return JSONResponse({"status": "error", "message": f"Unknown action: {action}"}, status_code=400)

def get_target_providers(model_id):
    model_lower = model_id.lower()
    if any(m in model_lower for m in ["gpt", "claude", "gemini", "deepseek-chat", "deepseek-coder"]):
        return ["ainative"]
    if "kilo" in model_lower:
        return ["kilo"]
    return ["kilo", "ainative"]

@app.get("/v1/models")
async def list_models():
    return JSONResponse(status_code=200, content={
        "object": "list",
        "data": [
            {"id": "kilo-auto/free", "object": "model", "owned_by": "kilo"},
            {"id": "deepseek/deepseek-r1:free", "object": "model", "owned_by": "kilo"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "object": "model", "owned_by": "kilo"},
            {"id": "gpt-4o", "object": "model", "owned_by": "ainative"},
            {"id": "gpt-4o-mini", "object": "model", "owned_by": "ainative"},
            {"id": "claude-3-5-sonnet-20241022", "object": "model", "owned_by": "ainative"},
            {"id": "gemini-1.5-pro", "object": "model", "owned_by": "ainative"},
            {"id": "gemini-1.5-flash", "object": "model", "owned_by": "ainative"}
        ]
    })

routing_cache = {}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
    if not path.endswith("chat/completions"):
        return JSONResponse(status_code=200, content={
            "status": "Gateway Online",
            "kilo_keys": len(get_keys(KILO_KEY_FILE)),
            "ainative_keys": len(get_keys(AINATIVE_KEY_FILE))
        })
        
    try:
        body = await request.json()
    except:
        body = {}
        
    model_id = body.get("model", "kilo-auto/free")
    
    # Use learned routing cache if available
    if model_id in routing_cache:
        providers = [routing_cache[model_id]]
        log(f"⚡ Received request for '{model_id}' -> Using MEMORIZED provider: {providers}")
    else:
        providers = get_target_providers(model_id)
        log(f"Received request for model '{model_id}' -> Initial routing order: {providers}")
    
    for provider in providers:
        key_file = KILO_KEY_FILE if provider == "kilo" else AINATIVE_KEY_FILE
        target_url = KILO_URL if provider == "kilo" else AINATIVE_URL
        
        # Try up to 3 keys per provider
        for attempt in range(3):
            keys = get_keys(key_file)
            if not keys:
                log(f"⚠️ {provider.upper()} has 0 keys left. Trying next provider...")
                break
                
            api_key = random.choice(keys)
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            try:
                log(f"🚀 Forwarding to {provider.upper()} with key ({api_key[:10]}...)")
                response = requests.post(target_url, json=body, headers=headers, timeout=60)
                
                # Success
                if response.status_code == 200:
                    log(f"✅ {provider.upper()} returned 200 OK!")
                    
                    # Save successful routing to memory if we had multiple choices
                    if model_id not in routing_cache and len(providers) > 1:
                        routing_cache[model_id] = provider
                        log(f"🧠 Learned routing: '{model_id}' works on {provider.upper()}. Saved to memory!")
                        
                    return JSONResponse(status_code=200, content=response.json())
                    
                # Quota / Expired key
                if response.status_code in [401, 402, 429]:
                    log(f"💀 {provider.upper()} Key invalid/exhausted! Deleting ({api_key[:10]}...)...")
                    delete_key(key_file, api_key)
                    continue
                    
                # Unsupported model on this provider or other 4xx/5xx
                log(f"⚠️ {provider.upper()} HTTP {response.status_code}: {response.text[:100]}")
                break
                
            except Exception as e:
                log(f"❌ {provider.upper()} Connection error: {str(e)[:50]}")
                break
                
    # If we get here, both providers failed or cached provider broke
    # We should clear the cache so it retries normally next time
    if model_id in routing_cache:
        log(f"🧹 Clearing memory for '{model_id}' as the cached provider failed.")
        del routing_cache[model_id]
        
    return JSONResponse(status_code=500, content={"error": f"Failed to serve model '{model_id}' across providers: {providers}"})

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def get_proxy_port():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return int(json.load(f).get("port", 8008))
        except:
            pass
    return 8008

if __name__ == "__main__":
    import uvicorn
    port = get_proxy_port()
    uvicorn.run(app, host="0.0.0.0", port=port)
