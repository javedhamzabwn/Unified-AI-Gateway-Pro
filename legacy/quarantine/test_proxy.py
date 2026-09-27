import os
import sys
import json
import re
import urllib.request
import urllib.error

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def get_proxy_port():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return int(json.load(f).get("port", 8008))
        except:
            pass
    return 8008

def get_public_proxy_url():
    tunnel_log = os.path.join(BASE_DIR, "tunnel.log")
    if os.path.exists(tunnel_log):
        try:
            with open(tunnel_log, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                m = re.search(r'your url is:\s*(https://[^\s]+)', content, re.IGNORECASE)
                if m:
                    return f"{m.group(1).rstrip('/')}/v1/chat/completions"
        except:
            pass
    username = os.environ.get("USERNAME", "user").lower()
    clean_username = re.sub(r'[^a-z0-9]', '', username)
    return f"https://kilo-api-{clean_username}.loca.lt/v1/chat/completions"

def test_say_hi(target="local", model_name="kilo-auto/free", prompt="Hi! Please reply with a short friendly greeting in one sentence."):
    port = get_proxy_port()
    if target == "public":
        url = get_public_proxy_url()
        target_name = f"Public LocalTunnel ({url})"
    else:
        url = f"http://localhost:{port}/v1/chat/completions"
        target_name = f"Local Gateway (http://localhost:{port})"
    
    print(f"[*] Sending request to [{model_name}] via {target_name}...")
    
    headers = {
        "Authorization": "Bearer dummy-key",
        "Content-Type": "application/json",
        "Bypass-Tunnel-Reminder": "true"  # Bypasses localtunnel warning page
    }
    
    body = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            model_used = data.get("model", model_name)
            choices = data.get("choices", [])
            reply = choices[0]["message"]["content"] if choices else str(data)
            
            print("\n=======================================================")
            print("[OK] PROXY TEST SUCCESSFUL!")
            print(f" -> Target Endpoint : {target_name}")
            print(f" -> Model Used      : {model_used}")
            print(f" -> AI Reply        : {reply.strip()}")
            print("=======================================================\n")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode('utf-8', errors='ignore')
        except:
            pass
        print(f"\n[!] HTTP Error {e.code} through {target_name}: {e.reason}")
        if err_body:
            print(f" -> Response: {err_body}")
        if "0 keys" in err_body or "Failed to serve model" in err_body:
            print("💡 Tip: No harvested API keys yet in kilo_keys.txt or ainative_keys.txt.")
            print("   Allow background bots a few minutes to farm keys, or run option 7 to run a bot in foreground.")
    except urllib.error.URLError as e:
        print(f"\n[!] Connection Error through {target_name}: {e}")
        if target == "local":
            print(f"💡 Tip: The local proxy server is not running on port {port}. Start it with option 1.")
        else:
            print("💡 Tip: The public tunnel may still be connecting, or localtunnel service is busy.")
    except Exception as e:
        print(f"\n[!] Error through {target_name}: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "local"
    model = sys.argv[2] if len(sys.argv) > 2 else "kilo-auto/free"
    prompt = sys.argv[3] if len(sys.argv) > 3 else "Hi! Please reply with a short friendly greeting in one sentence."
    test_say_hi(target, model, prompt)
