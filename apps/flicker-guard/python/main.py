"""Team 11 · flicker-guard · Linux side of the UNO Q.

Is fast flickering light present? An Edge Impulse model answers this on the board, offline:
  * the sketch streams every Modulino Light reading (R, G, B, gain) over the Bridge;
  * every STEP_S seconds the last features.WINDOW readings are preprocessed (features.py) and
    classified by the Edge Impulse model, served by the motion_detection brick's runner container
    (custom .eim model: see app.yaml and tools/ei/README.md);
  * an alert needs P(flicker) >= ALERT_P in 2 of the last 3 windows;
  * a rule-based baseline (brightness swing + strongest frequency) is printed alongside.
Every reading is also saved to data/recordings/flicker.<time>.csv: that's the training data
(tools/flicker.html → "Collect", then tools/ei/make_dataset.py).
"""

import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import features as ft  # noqa: E402
from arduino.app_utils import App, Bridge  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent
REC_DIR = APP_DIR / "data" / "recordings"
STAMP = time.strftime("%Y%m%d-%H%M%S")
STEP_S = 0.5           # classify this often (windows overlap)
ALERT_P = 0.8
FLICKER_LABEL = "flicker"

lock = threading.Lock()
readings = deque(maxlen=600)          # (t_ms, r, g, b, gain_code)
counts = {"n": 0, "bad": 0}
rec = {"f": None}
history = deque(maxlen=3)             # last P(flicker) values
state = {"alert": False, "last_change_i": -10**9, "total": 0}


def rec_file():
    if rec["f"] is None:
        try:
            REC_DIR.mkdir(parents=True, exist_ok=True)
            rec["f"] = open(REC_DIR / f"flicker.{STAMP}.csv", "w")
            rec["f"].write("t_ms,red,green,blue,gain_x\n")
        except OSError as e:
            print(f"[warn] can't save readings: {e}", flush=True)
            rec["f"] = False
    return rec["f"] or None


def on_info(text):
    print(str(text), flush=True)


def on_s(batch):
    rows = []
    for tok in str(batch).split(";"):
        if not tok:
            continue
        try:
            t, r, g, b, gc = (int(v) for v in tok.split(","))
        except ValueError:
            counts["bad"] += 1
            continue
        rows.append((t, r, g, b, min(max(gc, 0), 4)))
    with lock:
        for row in rows:
            if readings and readings[-1][4] != row[4]:
                state["last_change_i"] = state["total"]
            readings.append(row)
            state["total"] += 1
        counts["n"] += len(rows)
        f = rec_file()
        if f:
            f.writelines(f"{t},{r},{g},{b},{ft.GAIN_X[gc]}\n" for t, r, g, b, gc in rows)


Bridge.provide("info", on_info)
Bridge.provide("s", on_s)


# ---- Edge Impulse model (runner container from the motion_detection brick) --------------------

model = None
model_note = "no model"
try:
    from arduino.app_bricks.motion_detection import MotionDetection

    md = MotionDetection(confidence=0.0)   # used only as a client for its runner: infer_from_features()
    info = md._model_info
    labels = list(getattr(info, "labels", []))
    if FLICKER_LABEL not in labels:
        model_note = (f"the runner has '{getattr(info, 'name', '?')}' (labels {labels}), not a flicker model: "
                      "recording only. Deploy one with tools/ei (README there).")
    elif info.input_features_count != ft.WINDOW * len(ft.AXES):
        model_note = (f"model expects {info.input_features_count} features but features.py makes "
                      f"{ft.WINDOW * len(ft.AXES)}: retrain or fix WINDOW")
    else:
        model = md
        model_note = (f"Edge Impulse model '{getattr(info, 'name', '?')}' (project {getattr(info, 'project_id', '?')}), "
                      f"labels {labels}, {info.frequency} Hz, window {ft.WINDOW} readings")
except Exception as e:  # noqa: BLE001
    model_note = f"Edge Impulse runner not available ({e}): recording only"


def classify(window_rows):
    rgb = np.array([w[1:4] for w in window_rows], float)
    gain = np.array([ft.GAIN_X[w[4]] for w in window_rows], float)
    feats = ft.flatten(ft.preprocess(rgb, gain))
    t0 = time.monotonic()
    ret = model.infer_from_features(feats)
    ms = (time.monotonic() - t0) * 1000
    # Runner format (checked on the board): {"result": {"classification": {label: 0..1}}, "timing": {...}}.
    # (The brick's _extract_classification() turns these into percentage strings, so it isn't used.)
    cls = (ret or {}).get("result", {}).get("classification")
    return ({str(k): float(v) for k, v in cls.items()} if isinstance(cls, dict) else None), ms


def ei_step():
    with lock:
        n_total, last_change = state["total"], state["last_change_i"]
        rows = list(readings)[-ft.WINDOW:]
    if len(rows) < ft.WINDOW:
        return
    if n_total - last_change < ft.WINDOW + 2:     # a gain change inside the window: skip it
        return
    span = (rows[-1][0] - rows[0][0]) / 1000
    if span > ft.WINDOW * ft.INTERVAL_MS / 1000 * 1.3:
        return                                    # readings missing (Bridge hiccup)
    probs, ms = classify(rows)
    if probs is None:
        print("[warn] the model returned no classification", flush=True)
        return
    p = probs.get(FLICKER_LABEL, 0.0)
    history.append(p)
    alert = sum(x >= ALERT_P for x in history) >= 2
    others = " · ".join(f"{k} {v:.2f}" for k, v in probs.items() if k != FLICKER_LABEL)
    bar = "█" * int(round(p * 10)) + "·" * (10 - int(round(p * 10)))
    verdict = "⚠ FLICKER" if alert else "ok"
    print(f"[ei] flicker {p:.2f} {bar} {others} → {verdict} ({ms:.0f} ms)", flush=True)
    if alert != state["alert"]:
        state["alert"] = alert
        print("[alert] fast flickering light detected" if alert else "[ei] flicker gone", flush=True)


# ---- Rule-based baseline, once a second --------------------------------------------------------

SPARK = "▁▂▃▄▅▆▇█"


def spark(x, width=16):
    x = list(x)[-width:]
    lo, hi = min(x), max(x)
    if hi - lo < 1e-9:
        return SPARK[0] * len(x)
    return "".join(SPARK[min(7, int((v - lo) / (hi - lo) * 8))] for v in x)


def dominant(t, x):
    if len(t) < 16 or t[-1] <= t[0]:
        return 0.0, 0.0
    x = x - np.polyval(np.polyfit(t - t[0], x, 1), t - t[0])
    u = (t - t[0]) / (t[-1] - t[0])
    w = 0.5 - 0.5 * np.cos(2 * np.pi * u)
    fs = (len(t) - 1) / (t[-1] - t[0])
    freqs = np.arange(0.5, fs / 2, 0.05)
    amp = 2 * np.abs(np.exp(-2j * np.pi * np.outer(freqs, t - t[0])) @ (x * w)) / w.sum()
    k = int(np.argmax(amp))
    return float(freqs[k]), float(amp[k] / max(np.median(amp), 1e-12))


def status_line(n):
    with lock:
        rows = list(readings)[-ft.WINDOW:]
    if len(rows) < 16:
        print(f"[stat] {n}/s (waiting for readings)", flush=True)
        return
    t = np.array([r[0] for r in rows]) / 1000
    gain = np.array([ft.GAIN_X[r[4]] for r in rows], float)
    g = np.array([r[2] for r in rows], float) / gain
    hi = np.percentile(g, 98)
    sw = (hi - np.percentile(g, 2)) / hi if hi > 0 else 0.0
    f, prom = dominant(t, g)
    freq = f"~{f:.1f}Hz" if prom >= 6 and sw >= 0.05 else "steady"
    rule = "flicker" if prom >= 6 and sw >= 0.10 and f >= 3 else "–"
    print(f"[stat] {n:3d}/s x{ft.GAIN_X[rows[-1][4]]:<2d} G {rows[-1][2]:6d} {spark(g)} swing {sw * 100:3.0f}% "
          f"{freq:8s} rule: {rule}", flush=True)


_next_ei = time.monotonic() + 1.0
_next_stat = time.monotonic() + 1.0


def loop():
    global _next_ei, _next_stat
    now = time.monotonic()
    if model is not None and now >= _next_ei:
        _next_ei = now + STEP_S
        try:
            ei_step()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] inference failed: {e}", flush=True)
    if now >= _next_stat:
        _next_stat += 1.0
        with lock:
            n, counts["n"] = counts["n"], 0
            bad, counts["bad"] = counts["bad"], 0
            if rec["f"]:
                rec["f"].flush()
        status_line(n)
        if bad:
            print(f"[warn] {bad} malformed readings", flush=True)
    time.sleep(0.02)


print(f"[boot] flicker-guard · {model_note}", flush=True)
print(f"[rec] readings → data/recordings/flicker.{STAMP}.csv", flush=True)
App.run(user_loop=loop)
