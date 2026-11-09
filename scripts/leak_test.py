from __future__ import annotations

import argparse
import time

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--model", default="faster-whisper-tiny")
    parser.add_argument("--variant", default="faster-whisper-tiny:int8")
    parser.add_argument("--cycles", type=int, default=20)
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base, timeout=120)
    status = client.get("/api/resources/status").json()
    for item in status.get("loaded", []):
        client.post(f"/api/models/{item['model_id']}/unload")
    time.sleep(2)
    baseline = client.get("/api/resources/status").json()["memory"]["gpu_used_gb"]
    print("baseline GPU used:", baseline, "GB")
    samples: list[float] = []
    for index in range(args.cycles):
        response = client.post(f"/api/models/{args.model}/load", json={"variant_id": args.variant, "force": True})
        if response.status_code != 200:
            print("load failed", response.status_code, response.text)
            return 1
        time.sleep(1)
        used_loaded = client.get("/api/resources/status").json()["memory"]["gpu_used_gb"]
        client.post(f"/api/models/{args.model}/unload")
        time.sleep(1.5)
        used_after = client.get("/api/resources/status").json()["memory"]["gpu_used_gb"]
        samples.append(used_after)
        print(f"{index + 1:02d}/{args.cycles}: loaded={used_loaded:.3f} GB after={used_after:.3f} GB")
    final = samples[-1]
    drift = final - baseline
    print(f"final drift: {drift:+.3f} GB (threshold +0.20 GB)")
    return 0 if drift <= 0.2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
