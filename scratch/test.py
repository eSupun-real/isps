import requests

def test():
    # Login as an agent
    r = requests.post("http://127.0.0.1:5050/api/auth/login", json={"username": "agent_mol", "password": "agent1234"})
    if r.status_code != 200:
        print("Login failed:", r.text)
        return
    token = r.json().get("token")
    print("Token obtained.")

    # Try lookup-imo
    r = requests.get("http://127.0.0.1:5050/api/vessels/lookup-imo/9240328", headers={"Authorization": f"Bearer {token}"})
    print("Lookup IMO status:", r.status_code)
    print("Lookup IMO response:", r.text)

    # Try config
    r = requests.get("http://127.0.0.1:5050/api/config", headers={"Authorization": f"Bearer {token}"})
    print("Config status:", r.status_code)
    print("Config response:", r.text)

if __name__ == "__main__":
    test()
