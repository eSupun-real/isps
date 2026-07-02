import os
import urllib.request
import json

def test_anthropic():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("Testing Anthropic key:", api_key[:15] + "...")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    body = json.dumps({
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello"}]
    }).encode()
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print("Anthropic Success:", data["content"][0]["text"])
    except Exception as e:
        print("Anthropic Failed:", e)

def test_openai():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    print("Testing OpenAI key:", api_key[:15] + "...")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    body = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello"}]
    }).encode()
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print("OpenAI Success:", data["choices"][0]["message"]["content"])
    except Exception as e:
        print("OpenAI Failed:", e)

if __name__ == "__main__":
    # Load env manually
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    test_anthropic()
    test_openai()
