"""Submit a small weather request to a locally running OpenEPW REST server."""

import json
from pathlib import Path

import httpx

if __name__ == "__main__":
    request = json.loads(Path(__file__).with_name("request.json").read_text())
    with httpx.Client(base_url="http://127.0.0.1:8000") as client:
        response = client.post("/v1/weather/plan", json=request)
        response.raise_for_status()
        job = client.post(
            "/v1/weather/jobs",
            json={"plan": response.json(), "idempotency_key": "example-rest-2024"},
        )
        job.raise_for_status()
        print(json.dumps(job.json(), indent=2))
