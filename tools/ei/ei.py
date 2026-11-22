#!/usr/bin/env python3
"""Team 11 · drive the FlickerGuard Edge Impulse project from the laptop (needs `requests`).

    python3 tools/ei/ei.py info                        project, data and impulse summary
    python3 tools/ei/ei.py upload <dataset.json>       labelled windows from make_dataset.py
    python3 tools/ei/ei.py train [cycles]              impulse + spectral features + Keras training + test accuracy
    python3 tools/ei/ei.py deploy                      build the Linux aarch64 .eim → build/flicker-guard.eim

The API key is read from $EI_API_KEY, else ~/.config/flickerguard/ei-admin-key (Admin role: needed to
train), else ~/.config/flickerguard/ei-api-key (ingestion/deployment only). Keep keys out of git.
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
    if key:
        return key
    for name in ("ei-admin-key", "ei-api-key"):
        f = Path.home() / ".config" / "flickerguard" / name
        if f.exists():
            return f.read_text().strip()
    sys.exit("No API key: set EI_API_KEY or save it to ~/.config/flickerguard/ei-admin-key")


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


# ---- train ------------------------------------------------------------------------------------------

# Must match apps/flicker-guard/python/features.py: 64 readings at 27.6 ms. 1766.4 ms would round down
# to 63 readings, so the window is 1767 ms.
IMPULSE = {
    "inputBlocks": [{"id": 1, "type": "time-series", "name": "Time series", "title": "Time series data",
                     "windowSizeMs": 1767, "windowIncreaseMs": 1767, "frequencyHz": 1000 / 27.6, "padZeros": True}],
    "dspBlocks": [{"id": 2, "type": "spectral-analysis", "name": "Spectral features", "title": "Spectral Analysis",
                   "axes": ["red", "green", "blue"], "input": 1, "implementationVersion": 4}],
    "learnBlocks": [{"id": 3, "type": "keras", "name": "Classifier", "title": "Classification", "dsp": [2]}],
}
DSP_CONFIG = {"fft-length": "64", "filter-type": "none", "do-log": "true", "do-fft-overlap": "false",
              "scale-axes": "1", "input-decimation-ratio": "1"}


def wait_job(pid, job_id, what, timeout=1800):
    t0, last = time.time(), ""
    while time.time() - t0 < timeout:
        job = get(f"{pid}/jobs/{job_id}/status")["job"]
        if job.get("finished"):
            if not job.get("finishedSuccessful"):
                log = requests.get(f"{STUDIO}/{pid}/jobs/{job_id}/stdout", headers=H, timeout=60).text
                raise RuntimeError(f"{what} failed:\n{log[-1500:]}")
            print(f"  {what}: done in {time.time() - t0:.0f} s", flush=True)
            return job
        msg = f"  {what}: running ({time.time() - t0:.0f} s)"
        if msg[:-5] != last:
            last = msg[:-5]
        time.sleep(5)
    raise RuntimeError(f"{what}: timed out")


def cmd_train(cycles=60):
    pid = project_id()
    imp = get(f"{pid}/impulse").get("impulse") or {}
    if not imp.get("inputBlocks"):
        post(f"{pid}/impulse", IMPULSE)
        print("impulse created")
    post(f"{pid}/dsp/2", {"config": DSP_CONFIG})
    print("spectral analysis configured:", DSP_CONFIG)
    j = post(f"{pid}/jobs/generate-features", {"dspId": 2})
    wait_job(pid, j["id"], "generate features")
    j = post(f"{pid}/jobs/train/keras/3", {"trainingCycles": int(cycles), "learningRate": 0.005})
    wait_job(pid, j["id"], "train")
    j = post(f"{pid}/jobs/evaluate", {})
    wait_job(pid, j["id"], "test-set evaluation")
    ev = get(f"{pid}/deployment/evaluate")
    for res in ev.get("result", []):
        print(f"test set, {res.get('modelType')} model: accuracy {res['accuracy']['raw']:.1f}% "
              f"({res['totalCorrectWindowCount']['raw']}/{res['totalWindowCount']} windows)")
        for true, row in res.get("confusionMatrix", {}).items():
            print(f"  {true:12s} → " + ", ".join(f"{k} {v['raw']}" for k, v in row.items()))
    return 0


def cmd_deploy(fmt="runner-linux-aarch64"):
    pid = project_id()
    j = post(f"{pid}/jobs/build-ondevice-model?type={fmt}", {"engine": "tflite"})
    wait_job(pid, j["id"], f"build {fmt}")
    r = requests.get(f"{STUDIO}/{pid}/deployment/download", headers=H, params={"type": fmt}, timeout=300)
    r.raise_for_status()
    MODEL_OUT.parent.mkdir(exist_ok=True)
    out = MODEL_OUT if fmt == "runner-linux-aarch64" else MODEL_OUT.with_name(f"flicker-guard.{fmt}.eim")
    out.write_bytes(r.content)
    out.chmod(0o755)
    print(f"downloaded {out} ({len(r.content) / 1e6:.1f} MB)")
    return 0


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
    elif cmd == "train":
        return cmd_train(*argv[1:2])
    elif cmd == "deploy":
        return cmd_deploy(*argv[1:2])
    else:
        sys.exit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
