"""Team 11 · max-strobe-test · Linux side.

Records the MAX30102 stream from the sketch (400 samples/s, red LED alternating on/off every 2 s)
to data/recordings/strobe.<time>.csv and prints a status line once a second. The analysis runs
on the laptop: apps/max-strobe-test/analyze.py (see the README there).
"""

import threading
import time
from pathlib import Path

import numpy as np

from arduino.app_utils import App, Bridge

REC_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"
STAMP = time.strftime("%Y%m%d-%H%M%S")

lock = threading.Lock()
csv = None
rows = 0
counts = {"n": 0, "ovf": 0}
recent = {0: [], 1: []}                 # LED off / on -> samples from the last second


def on_info(text):
    print(text, flush=True)


def on_strobe(t0, led, ovf, batch):
    global csv, rows
    vals = [int(v) for v in str(batch).split(";") if v]
    with lock:
        try:
            if csv is None:
                REC_DIR.mkdir(parents=True, exist_ok=True)
                csv = open(REC_DIR / f"strobe.{STAMP}.csv", "w")
                csv.write("row,batch_t0_ms,led,alc_ovf,value\n")
            for i, v in enumerate(vals):
                csv.write(f"{rows},{int(t0)},{int(led)},{int(ovf) if i == 0 else 0},{v}\n")
                rows += 1
            csv.flush()
        except OSError:
            pass
        counts["n"] += len(vals)
        counts["ovf"] += int(ovf)
        recent[int(led)].extend(vals)


Bridge.provide("info", on_info)
Bridge.provide("strobe", on_strobe)


def loop():
    time.sleep(1)
    with lock:
        n, ovf = counts["n"], counts["ovf"]
        counts["n"] = counts["ovf"] = 0
        parts = []
        for led, name in ((1, "LED on"), (0, "LED off")):
            x = np.asarray(recent[led], dtype=float)
            recent[led] = []
            if len(x) > 20:
                parts.append(f"{name}: level {np.median(x):7.0f} swing {np.percentile(x, 98) - np.percentile(x, 2):6.0f}")
        total = rows
    print(f"[strobe] {n:3d}/s · " + " · ".join(parts) + f" · ALC overflow {ovf}/s · rows {total}", flush=True)


print(f"[boot] max-strobe-test recording to {REC_DIR}/strobe.{STAMP}.csv", flush=True)
App.run(user_loop=loop)
