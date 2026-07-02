import os
import urllib.request
import json
from pathlib import Path

# Load env manually
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

api_key = os.environ.get("OPENROUTER_API_KEY", "")
print("Testing OpenRouter key:", api_key[:15] + "...")
url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}
body = json.dumps({
    "model": "google/gemini-2.5-flash",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Hello"}]
}).encode()

try:
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print("OpenRouter Success:", data["choices"][0]["message"]["content"])
except Exception as e:
    print("OpenRouter Failed:", e)
