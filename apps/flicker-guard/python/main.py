"""Team 11 · flicker-guard · Linux side of the UNO Q.

Two Edge Impulse models, both on the board and offline:
  * FLICKER (stimulus), here on Linux: every STEP_S seconds the last features.WINDOW Modulino Light
    readings are preprocessed (features.py) and classified by our flicker model (project 1170128),
    served by the motion_detection brick's runner container (app.yaml). Alert = P(flicker) >= ALERT_P
    in 2 of the last 3 windows.
  * MOVEMENT (response), on the MCU: the sketch runs the "Wearable Movement Monitoring (More
    Classes)" model (project 1170305) on the Modulino Movement at 4 Hz and sends its class scores
    every 2.5 s ("m" messages).

After a flicker exposure a WATCH window of WATCH_S seconds opens. During the exposure and the
watch window, seizure-like movement (P(Seizure) >= SEIZURE_P_WATCH in SEIZURE_N_WATCH classifications
in a row, i.e. 5 s) starts a COUNTDOWN_S countdown to the carer alarm; it is cancelled if the
movement settles. Outside the window a stricter rule applies (SEIZURE_P_ALWAYS x SEIZURE_N_ALWAYS,
10 s), or none at all with MOVEMENT_ONLY_AFTER_STIMULUS = True.

The current state is shown on the UNO Q's LED matrix (static icons, sketch.ino): eye = monitoring,
warning triangle = flicker exposure, eye + time bar = watch window, digits = countdown, SOS = carer
alarm. A self-test shows every icon once when the board starts sending.

Saved in data/recordings/: flicker.<time>.csv (light, training data), movement.<time>.csv (4 Hz
movement samples) and events.<time>.csv (exposures, watch windows, alarms: spec F8).
"""

import math
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

# Flicker model
STEP_S = 0.5                 # classify this often (windows overlap)
ALERT_P = 0.8
FLICKER_LABEL = "flicker"

# Movement model, after the stimulus (spec F6, N3)
SEIZURE_LABEL = "Seizure"
WATCH_S = 300                # watch window after a flicker exposure ends
SEIZURE_P_WATCH, SEIZURE_N_WATCH = 0.6, 2     # during exposure / watch: 2 x 2.5 s = 5 s
SEIZURE_P_ALWAYS, SEIZURE_N_ALWAYS = 0.8, 4   # otherwise: 4 x 2.5 s = 10 s
MOVEMENT_ONLY_AFTER_STIMULUS = False          # True: ignore seizure-like movement without a prior exposure
COUNTDOWN_S = 15             # wearer's chance to recover before the carer alarm
SETTLED_P, SETTLED_N = 0.3, 2  # movement counts as settled after 2 classifications below 0.3

LED_SELFTEST = True          # show every matrix icon once at start-up (1.5 s each)
LED_NAMES = {0: "monitoring (eye)", 1: "flicker warning (triangle)", 2: "watch window (eye + time bar)",
             3: "seizure countdown (digits)", 4: "carer alarm (SOS)"}
LED_SELFTEST_SEQ = [(0, 0), (1, 0), (2, 13), (2, 4), (3, 15), (3, 7), (4, 0), (0, 0)]

lock = threading.Lock()
readings = deque(maxlen=600)          # (t_ms, r, g, b, gain_code)
counts = {"n": 0, "bad": 0, "imu": 0}
files = {}
history = deque(maxlen=3)             # last P(flicker) values
seizure_hist = deque(maxlen=8)        # last P(Seizure) values
moves = deque()                       # movement classifications waiting for the main loop
state = {"alert": False, "last_change_i": -10**9, "total": 0,
         "exposure_start": None, "watch_until": 0.0, "seizure": None, "countdown_until": 0.0}


def rec_file(name, header):
    if name not in files:
        try:
            REC_DIR.mkdir(parents=True, exist_ok=True)
            f = open(REC_DIR / f"{name}.{STAMP}.csv", "w")
            f.write(header + "\n")
            files[name] = f
        except OSError as e:
            print(f"[warn] can't save {name}: {e}", flush=True)
            files[name] = None
    return files[name]


def log_event(kind, detail=""):
    f = rec_file("events", "time,event,detail")
    if f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{kind},{detail}\n")
        f.flush()


# ---- Messages from the sketch (short: they run on the Bridge thread) ---------------------------

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
        f = rec_file("flicker", "t_ms,red,green,blue,gain_x")
        if f:
            f.writelines(f"{t},{r},{g},{b},{ft.GAIN_X[gc]}\n" for t, r, g, b, gc in rows)


def on_imu(batch):
    rows = [tok for tok in str(batch).split(";") if tok.count(",") == 6]
    with lock:
        counts["imu"] += len(rows)
        f = rec_file("movement", "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ")   # same columns as MovementSensor.txt
        if f:
            f.writelines(r + "\n" for r in rows)


def on_m(scores, dsp_us, nn_us):
    probs = {}
    for part in str(scores).split(","):
        label, _, v = part.partition(":")
        try:
            probs[label] = float(v)
        except ValueError:
            pass
    with lock:
        moves.append((probs, int(dsp_us), int(nn_us)))


Bridge.provide("info", on_info)
Bridge.provide("s", on_s)
Bridge.provide("imu", on_imu)
Bridge.provide("m", on_m)


# ---- Flicker model (runner container from the motion_detection brick) ------------------------

model = None
model_note = "no model"
try:
    from arduino.app_bricks.motion_detection import MotionDetection

    md = MotionDetection(confidence=0.0)   # used only as a client for its runner: infer_from_features()
    info = md._model_info
    labels = list(getattr(info, "labels", []))
    if FLICKER_LABEL not in labels:
        model_note = (f"the runner has '{getattr(info, 'name', '?')}' (labels {labels}), not a flicker model: "
                      "recording only, rule baseline as the stimulus. Deploy one with tools/ei (README there).")
    elif info.input_features_count != ft.WINDOW * len(ft.AXES):
        model_note = (f"model expects {info.input_features_count} features but features.py makes "
                      f"{ft.WINDOW * len(ft.AXES)}: retrain or fix WINDOW")
    else:
        model = md
        model_note = (f"flicker model '{getattr(info, 'name', '?')}' (project {getattr(info, 'project_id', '?')}), "
                      f"labels {labels}, {info.frequency} Hz, window {ft.WINDOW} readings")
except Exception as e:  # noqa: BLE001
    model_note = f"Edge Impulse runner not available ({e}): recording only, rule baseline as the stimulus"


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


def set_flicker_alert(alert, how):
    """Stimulus on/off: an exposure starts, or ends and opens the watch window."""
    if alert == state["alert"]:
        return
    state["alert"] = alert
    if alert:
        state["exposure_start"] = time.monotonic()
        print(f"[alert] fast flickering light detected ({how}): cover one eye and look away", flush=True)
        log_event("exposure_start", how)
    else:
        dur = time.monotonic() - (state["exposure_start"] or time.monotonic())
        state["watch_until"] = time.monotonic() + WATCH_S
        print(f"[watch] flicker gone after {dur:.0f} s: watching for seizure-like movement for "
              f"{WATCH_S // 60} min (sensitivity raised)", flush=True)
        log_event("exposure_end", f"{dur:.0f} s")


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
        print("[warn] the flicker model returned no classification", flush=True)
        return
    p = probs.get(FLICKER_LABEL, 0.0)
    history.append(p)
    alert = sum(x >= ALERT_P for x in history) >= 2
    bar = "█" * int(round(p * 10)) + "·" * (10 - int(round(p * 10)))
    print(f"[ei] flicker {p:.2f} {bar} → {'⚠ FLICKER' if alert else 'ok'} ({ms:.0f} ms)", flush=True)
    set_flicker_alert(alert, f"model, P={p:.2f}")


# ---- Movement model scores → watch window logic ----------------------------------------------------

def sensitive():
    return state["alert"] or time.monotonic() < state["watch_until"]


def phase_text():
    if state["alert"]:
        return "exposure"
    left = state["watch_until"] - time.monotonic()
    return f"watch {int(left // 60)}:{int(left % 60):02d} left" if left > 0 else "monitoring"


def on_movement(probs, dsp_us, nn_us):
    p = probs.get(SEIZURE_LABEL, 0.0)
    seizure_hist.append(p)
    top = max(probs, key=probs.get) if probs else "?"
    sens = sensitive()
    thr, n = (SEIZURE_P_WATCH, SEIZURE_N_WATCH) if sens else (SEIZURE_P_ALWAYS, SEIZURE_N_ALWAYS)
    armed = sens or not MOVEMENT_ONLY_AFTER_STIMULUS
    recent = list(seizure_hist)[-n:]
    hit = armed and len(recent) == n and all(x >= thr for x in recent)
    others = " · ".join(f"{k} {v:.2f}" for k, v in
                        sorted(((k, v) for k, v in probs.items() if k != SEIZURE_LABEL), key=lambda kv: -kv[1])[:3])
    print(f"[move] Seizure {p:.2f} (top: {top}) · {others} · {phase_text()} "
          f"(model {dsp_us / 1000 + nn_us / 1000:.1f} ms on the MCU)", flush=True)

    settled = len(seizure_hist) >= SETTLED_N and all(x < SETTLED_P for x in list(seizure_hist)[-SETTLED_N:])
    if state["seizure"] is None and hit:
        state["seizure"] = "suspected"
        state["countdown_until"] = time.monotonic() + COUNTDOWN_S
        ctx = "after a flicker exposure" if sens else "without a recent exposure"
        print(f"[alert] seizure-like movement {ctx}: carer alarm in {COUNTDOWN_S} s unless it stops", flush=True)
        log_event("seizure_suspected", ctx)
    elif state["seizure"] is not None and settled:
        print(f"[watch] movement settled: {'alarm cancelled' if state['seizure'] == 'suspected' else 'alarm cleared'}",
              flush=True)
        log_event("seizure_cancelled" if state["seizure"] == "suspected" else "alarm_cleared")
        state["seizure"] = None


def countdown_tick():
    if state["seizure"] == "suspected":
        left = state["countdown_until"] - time.monotonic()
        if left <= 0:
            state["seizure"] = "alarm"
            print("[alert] CARER ALARM: seizure-like movement continued" +
                  (" after a flicker exposure" if sensitive() else ""), flush=True)
            log_event("carer_alarm", phase_text())
        elif int(left) % 5 == 0:
            print(f"[alert] carer alarm in {left:.0f} s", flush=True)


# ---- LED matrix (sketch: show(state, value)) -------------------------------------------------------

led = {"sent": None, "ok": None, "retry_at": 0.0, "last_state": None, "selftest_t0": None}


def led_target(now):
    if state["seizure"] == "alarm":
        return 4, 0
    if state["seizure"] == "suspected":
        return 3, max(0, math.ceil(state["countdown_until"] - now))
    if state["alert"]:
        return 1, 0
    left = state["watch_until"] - now
    if left > 0:
        return 2, math.ceil(13 * left / WATCH_S)
    return 0, 0


def led_show(target, now):
    try:
        Bridge.call("show", int(target[0]), int(target[1]), timeout=2)
    except Exception as e:  # noqa: BLE001
        if led["ok"] is not False:
            print(f"[warn] LED matrix: call to the MCU failed ({e}); retrying every 10 s", flush=True)
        led["ok"] = False
        led["retry_at"] = now + 10
        if LED_SELFTEST and led["selftest_t0"] is not False:
            led["selftest_t0"] = None   # e.g. the old sketch is still running: redo the self-test later
        return False
    if led["ok"] is not True:
        print("[led] LED matrix connected (Python → MCU calls work)", flush=True)
    led["ok"] = True
    led["sent"] = target
    return True


def led_tick(now):
    if led["ok"] is False and now < led["retry_at"]:
        return
    if LED_SELFTEST and led["selftest_t0"] is not False:
        if led["selftest_t0"] is None:
            with lock:
                started = state["total"] > 0          # the sketch is up and sending
            if not started:
                return
            led["selftest_t0"] = now
            print("[led] self-test: each icon for 1.5 s", flush=True)
        i = int((now - led["selftest_t0"]) / 1.5)
        if i < len(LED_SELFTEST_SEQ):
            tgt = LED_SELFTEST_SEQ[i]
            if tgt != led["sent"] and led_show(tgt, now):
                print(f"[led] self-test {i + 1}/{len(LED_SELFTEST_SEQ)}: {LED_NAMES[tgt[0]]}", flush=True)
            return
        led["selftest_t0"] = False
        print("[led] self-test done", flush=True)
    tgt = led_target(now)
    if tgt != led["sent"] and led_show(tgt, now) and tgt[0] != led["last_state"]:
        led["last_state"] = tgt[0]
        print(f"[led] {LED_NAMES[tgt[0]]}", flush=True)


# ---- Rule-based flicker baseline, once a second (also the stimulus when there's no model) ---------

SPARK = "▁▂▃▄▅▆▇█"
rule_hist = deque(maxlen=3)


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


def status_line(n, n_imu):
    with lock:
        rows = list(readings)[-ft.WINDOW:]
    if len(rows) < 16:
        print(f"[stat] light {n}/s (waiting for readings) · movement {n_imu}/s", flush=True)
        return
    t = np.array([r[0] for r in rows]) / 1000
    gain = np.array([ft.GAIN_X[r[4]] for r in rows], float)
    g = np.array([r[2] for r in rows], float) / gain
    hi = np.percentile(g, 98)
    sw = (hi - np.percentile(g, 2)) / hi if hi > 0 else 0.0
    f, prom = dominant(t, g)
    freq = f"~{f:.1f}Hz" if prom >= 6 and sw >= 0.05 else "steady"
    rule = prom >= 6 and sw >= 0.10 and f >= 3
    print(f"[stat] {n:3d}/s x{ft.GAIN_X[rows[-1][4]]:<2d} G {rows[-1][2]:6d} {spark(g)} swing {sw * 100:3.0f}% "
          f"{freq:8s} rule: {'flicker' if rule else '–'} · movement {n_imu}/s · {phase_text()}", flush=True)
    if model is None:
        rule_hist.append(rule)
        set_flicker_alert(sum(rule_hist) >= 2, "rule baseline")


_next_ei = time.monotonic() + 1.0
_next_stat = time.monotonic() + 1.0
_next_led = time.monotonic() + 1.0
_last_countdown = 0


def loop():
    global _next_ei, _next_stat, _next_led, _last_countdown
    now = time.monotonic()
    if now >= _next_led:
        _next_led = now + 0.25
        led_tick(now)
    if model is not None and now >= _next_ei:
        _next_ei = now + STEP_S
        try:
            ei_step()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] flicker inference failed: {e}", flush=True)
    while True:
        with lock:
            item = moves.popleft() if moves else None
        if item is None:
            break
        on_movement(*item)
    if int(now) != _last_countdown:
        _last_countdown = int(now)
        countdown_tick()
    if now >= _next_stat:
        _next_stat += 1.0
        with lock:
            n, counts["n"] = counts["n"], 0
            n_imu, counts["imu"] = counts["imu"], 0
            bad, counts["bad"] = counts["bad"], 0
            for f in files.values():
                if f:
                    f.flush()
        status_line(n, n_imu)
        if bad:
            print(f"[warn] {bad} malformed readings", flush=True)
    time.sleep(0.02)


print(f"[boot] flicker-guard · {model_note}", flush=True)
print(f"[boot] movement model on the MCU · seizure watch {WATCH_S // 60} min after a flicker exposure "
      f"(P≥{SEIZURE_P_WATCH} x{SEIZURE_N_WATCH}); otherwise "
      + ("off" if MOVEMENT_ONLY_AFTER_STIMULUS else f"P≥{SEIZURE_P_ALWAYS} x{SEIZURE_N_ALWAYS}"), flush=True)
print(f"[rec] data/recordings/{{flicker,movement,events}}.{STAMP}.csv", flush=True)
App.run(user_loop=loop)
