import os
import sys
import json
import urllib.request

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

def get_models():
    port = get_proxy_port()
    url = f"http://localhost:{port}/v1/models"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print("\n=======================================================")
            print("        AVAILABLE MODELS ON YOUR PROXY GATEWAY")
            print("=======================================================")
            for item in data.get("data", []):
                m_id = item.get("id", "")
                provider = item.get("owned_by", "").upper()
                print(f" -> {m_id:<40} (Provider: {provider})")
            print("=======================================================\n")
    except Exception as e:
        print(f"[!] Error fetching from proxy (is proxy running?): {e}")

if __name__ == "__main__":
    get_models()
