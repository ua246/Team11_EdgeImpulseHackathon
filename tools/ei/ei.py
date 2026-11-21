#!/usr/bin/env python3
"""Team 11 · drive the FlickerGuard Edge Impulse project from the laptop (needs `requests`).

    python3 tools/ei/ei.py info                        project, data and impulse summary
    python3 tools/ei/ei.py upload <dataset.json>       labelled windows from make_dataset.py
    python3 tools/ei/ei.py train                       TODO (needs an Admin key): impulse, features, training
    python3 tools/ei/ei.py deploy                      TODO: build the "Arduino UNO Q" / Linux aarch64 .eim

The API key is read from $EI_API_KEY or ~/.config/flickerguard/ei-api-key (keep it out of git).
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

STUDIO = "https://studio.edgeimpulse.com/v1/api"
INGEST = "https://ingestion.edgeimpulse.com/api"
REPO = Path(__file__).resolve().parent.parent.parent
MODEL_OUT = REPO / "build" / "flicker-guard.eim"


def api_key():
    key = os.environ.get("EI_API_KEY")
    if not key:
        f = Path.home() / ".config" / "flickerguard" / "ei-api-key"
        if not f.exists():
            sys.exit("No API key: set EI_API_KEY or save it to ~/.config/flickerguard/ei-api-key")
        key = f.read_text().strip()
    return key


KEY = None
H = {}


def setup():
    global KEY, H
    KEY = api_key()
    H = {"x-api-key": KEY}


def get(path, **kw):
    r = requests.get(f"{STUDIO}/{path}", headers=H, timeout=60, **kw)
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get("success") is False:
        raise RuntimeError(f"GET {path}: {j.get('error')}")
    return j


def post(path, body=None, **kw):
    r = requests.post(f"{STUDIO}/{path}", headers=H, json=body if body is not None else {}, timeout=120, **kw)
    r.raise_for_status()
    j = r.json()
    if isinstance(j, dict) and j.get("success") is False:
        raise RuntimeError(f"POST {path}: {j.get('error')}")
    return j


def project_id():
    return get("projects")["projects"][0]["id"]


# ---- info -----------------------------------------------------------------------------------------

def cmd_info():
    pid = project_id()
    j = get(str(pid))
    p = j["project"]
    print(f"project {pid} · {p['name']} (owner {p.get('owner')})")
    for cat, summ in (j.get("dataSummaryPerCategory") or {}).items():
        print(f"  {cat:9s} {summ.get('dataCount', 0):4d} samples, labels {summ.get('labels')}")
    print(f"  impulse: {'yes' if (j.get('impulse') or {}).get('created') else 'none yet'}")


# ---- upload -------------------------------------------------------------------------------------------

def acquisition_json(sample, interval_ms, axes):
    return {
        "protected": {"ver": "v1", "alg": "none", "iat": int(time.time())},
        "signature": "0" * 64,
        "payload": {
            "device_name": "uno-q-flicker-guard",
            "device_type": "ARDUINO_UNO_Q",
            "interval_ms": interval_ms,
            "sensors": [{"name": a, "units": "N/A"} for a in axes],
            "values": sample["values"],
        },
    }


def upload_one(sample, interval_ms, axes):
    body = acquisition_json(sample, interval_ms, axes)
    headers = dict(H, **{"x-file-name": sample["name"] + ".json", "x-label": sample["label"],
                         "Content-Type": "application/json", "x-disallow-duplicates": "1"})
    for attempt in range(4):
        try:
            r = requests.post(f"{INGEST}/{sample['category']}/data", headers=headers, data=json.dumps(body), timeout=60)
            if r.status_code == 200:
                return True, ""
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** attempt)
                continue
            return False, f"{r.status_code} {r.text[:200]}"
        except requests.RequestException as e:
            time.sleep(2 ** attempt)
            err = str(e)
    return False, err


def cmd_upload(path, limit=None):
    d = json.loads(Path(path).read_text())
    samples = d["samples"][:limit] if limit else d["samples"]
    ok = fail = 0
    errors = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for good, err in ex.map(lambda s: upload_one(s, d["interval_ms"], d["axes"]), samples):
            if good:
                ok += 1
            else:
                fail += 1
                errors.append(err)
            if (ok + fail) % 100 == 0:
                print(f"  {ok + fail}/{len(samples)} uploaded", flush=True)
    print(f"uploaded {ok}/{len(samples)}" + (f", {fail} failed (first: {errors[0]})" if fail else ""))
    return 0 if not fail else 1


def main(argv):
    if not argv:
        sys.exit(__doc__)
    setup()
    cmd = argv[0]
    if cmd == "info":
        cmd_info()
    elif cmd == "upload":
        limit = int(argv[2]) if len(argv) > 2 else None
        return cmd_upload(argv[1], limit)
    elif cmd in ("train", "deploy"):
        print(f"'{cmd}' isn't written yet. Training needs an Admin API key (the current key's role is "
              "ingestion_deployment); see docs/BRIEF.md for the plan and the settings to use.")
        return 2
    else:
        sys.exit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
