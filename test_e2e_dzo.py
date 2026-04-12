import requests
import json
import time

API_KEY = "test-api-key"
BASE_URL = "http://localhost:8000"


def process_file(filename, agent="auto"):
    with open(f"real_docs/{filename}", "r", encoding="utf-8") as f:
        text = f.read()

    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    payload = {"text": text, "filename": filename, "subject": f"Test {filename}", "force": True}

    resp = requests.post(f"{BASE_URL}/api/v1/process/{agent}", json=payload, headers=headers)
    print(f"Requesting {filename} ({agent}): status={resp.status_code}")
    if resp.status_code != 200:
        print(resp.text)
        return None

    job_id = resp.json().get("job", {}).get("job_id")
    if not job_id:
        job_id = resp.json().get("job_id")

    for _ in range(60):
        res = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}", headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data["status"] in ("done", "error"):
                return data
        time.sleep(2)
    return None


data1 = process_file("dzo_example.txt", "dzo")
if data1:
    print("DZO output", data1.get("result", {}).get("decision"))
else:
    print("DZO processing failed")
