"""Team 11 · hr-test · does the heart beat sensor give a usable pulse?

The sketch finds the sensor (MAX3010x over I2C, or an analog module on A0-A3) and streams it at
100 samples/s. This side runs a short protocol, then a live readout once a second:
  1. sensor     which sensor, which bus, which channels (from the sketch); sample rate
  2. baseline   5 s with NO finger on the sensor
  3. finger     waits up to 90 s for a fingertip (keep still, light steady pressure)
  4. measure    20 s: signal level, pulse strength (perfusion index), heart rate from the
                spectrum AND from counting beats (they must agree), SpO2 estimate (uncalibrated)
  5. verdict    PASS / PARTIAL / FAIL with hints
Raw samples are saved to data/recordings/hrtest.<time>.csv, the report to ...report.txt.
"""

import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from arduino.app_utils import App, Bridge

FS = 100.0                          # samples per second (set in the sketch)
WINDOW_S = 8.0                      # analysis window for heart rate
BASELINE_S = 5.0
FINGER_TIMEOUT_S = 180.0
MEASURE_S = 20.0
HR_MIN, HR_MAX = 40, 180            # plausible heart rates (bpm)

REC_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"
STAMP = time.strftime("%Y%m%d-%H%M%S")

lock = threading.Lock()
channels = []                       # e.g. ["red", "ir"] or ["A0", "A1", "A2", "A3"]
full_scale = 4095
buf = {}                            # channel -> deque of recent samples
count = 0                           # samples received since the last status line
total = 0
raw_file = None
_report = None
sensor_epoch = 0                    # bumped each time the sketch reports its sensor (i.e. after every flash)


# ---- output -------------------------------------------------------------------------------------

def keep(line):
    global _report
    try:
        if _report is None:
            REC_DIR.mkdir(parents=True, exist_ok=True)
            _report = open(REC_DIR / f"hrtest.{STAMP}.report.txt", "a")
        _report.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        _report.flush()
    except OSError:
        pass


def say(msg=""):
    print(f"[test] {msg}", flush=True)
    keep(f"[test] {msg}")


def live(msg):
    print(f"[hr] {msg}", flush=True)
    keep(f"[hr] {msg}")


# ---- data from the sketch ------------------------------------------------------------------------

def set_channels(names):
    global channels, full_scale
    channels = names
    full_scale = 262143 if names == ["red", "ir"] else 4095   # MAX30102 18-bit; analog 12-bit
    for c in names:
        buf[c] = deque(maxlen=int(FS * 30))


def on_info(text):
    global sensor_epoch
    say(f"  {text}")
    with lock:
        if "channels: red ir" in text:
            set_channels(["red", "ir"])
            if "MAX30100" in text:
                globals()["full_scale"] = 65535
            sensor_epoch += 1
        elif "analog mode" in text:
            set_channels(["A0", "A1", "A2", "A3"])
            sensor_epoch += 1


def on_ppg(t0, batch):
    global count, total, raw_file
    rows = [s.split() for s in str(batch).split(";") if s.strip()]
    with lock:
        if not channels and rows:      # missed the info message: infer from the sample width
            set_channels(["red", "ir"] if len(rows[0]) == 2 else [f"A{i}" for i in range(len(rows[0]))])
        for i, r in enumerate(rows):
            if len(r) != len(channels):
                continue
            vals = [int(v) for v in r]
            for c, v in zip(channels, vals):
                buf[c].append(v)
            count += 1
            total += 1
            try:
                if raw_file is None:
                    REC_DIR.mkdir(parents=True, exist_ok=True)
                    raw_file = open(REC_DIR / f"hrtest.{STAMP}.csv", "w")
                    raw_file.write("timestamp," + ",".join(channels) + "\n")
                raw_file.write(f"{int(t0) + i * 10}," + ",".join(map(str, vals)) + "\n")
            except OSError:
                pass


Bridge.provide("info", on_info)
Bridge.provide("ppg", on_ppg)


# ---- analysis ------------------------------------------------------------------------------------

def recent(c, seconds):
    with lock:
        x = list(buf.get(c, ()))
    return np.asarray(x[-int(seconds * FS):], dtype=float)


def moving_avg(x, n):
    if len(x) < n or n < 2:
        return x
    k = np.ones(n) / n
    return np.convolve(x, k, mode="same")


def pulse(x):
    """Heart rate analysis of one channel. Returns a dict, or None if too little data."""
    if len(x) < FS * 4:
        return None
    dc = float(np.median(x))
    y = x - moving_avg(x, int(FS * 1.5))              # remove the slow DC drift
    y = moving_avg(y, 5)[int(FS):-int(FS)]            # light smoothing; drop the filter edges
    y = y - y.mean()
    if len(y) < FS * 2:
        return None
    ac = float(np.percentile(y, 95) - np.percentile(y, 5))
    nfft = 1 << (len(y) * 8 - 1).bit_length()
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y)), nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, 1 / FS)
    band = (freqs >= HR_MIN / 60) & (freqs <= HR_MAX / 60)
    wide = (freqs >= 0.5) & (freqs <= 5.0)
    i = int(np.argmax(spec[band]))
    f = float(freqs[band][i])
    peak = spec[band][i]
    near = band & (np.abs(freqs - f) <= 0.15)
    quality = float(spec[near].sum() / max(spec[wide].sum(), 1e-12))
    # count beats: local maxima in the top 30 % of the swing, at least 0.33 s apart
    thr = np.percentile(y, 5) + 0.7 * ac
    beats, last = 0, -FS
    for k in range(1, len(y) - 1):
        if y[k] > thr and y[k] >= y[k - 1] and y[k] > y[k + 1] and k - last >= FS * 0.33:
            beats, last = beats + 1, k
    bpm_peaks = beats / (len(y) / FS) * 60
    return {"dc": dc, "ac": ac, "pi": 100 * ac / dc if dc > 0 else 0.0, "bpm": 60 * f,
            "bpm_peaks": bpm_peaks, "quality": quality}


def hr_channel():
    """The channel to judge heart rate on: IR for the MAX sensors, else the best analog pin."""
    if channels == ["red", "ir"]:
        return "ir"
    best, best_q = channels[0], -1.0
    for c in channels:
        p = pulse(recent(c, WINDOW_S))
        if p and p["quality"] > best_q:
            best, best_q = c, p["quality"]
    return best


def plausible(p):
    # A real pulse is 0.05-10 % of the signal level; bigger "pulses" are noise on a near-zero level.
    return (p is not None and HR_MIN <= p["bpm"] <= HR_MAX and p["quality"] >= 0.3
            and abs(p["bpm"] - p["bpm_peaks"]) <= 12 and 0.05 <= p["pi"] <= 10)


def finger_on(baseline):
    if channels == ["red", "ir"]:
        # A finger shifts the IR level clearly (up from open air, or away from a nearby surface's
        # reflection), or shows a real pulse. Don't require "3x baseline": a sensor facing
        # something already reads high with no finger.
        ir = recent("ir", 1.0)
        if len(ir) == 0:
            return False
        base, level = baseline.get("ir", 0), float(np.median(ir))
        # A fingertip reflects most of the LED light: open air reads ~1 % of range, a finger 5-60 %.
        return level >= 0.05 * full_scale and abs(level - base) > max(0.10 * base, 0.02 * full_scale)
    for c in channels:
        p = pulse(recent(c, WINDOW_S))
        if plausible(p) and p["ac"] >= 20:     # >= 20 counts of 4095: a real pulse, not a floating pin
            return True
    return False


def spo2_estimate():
    if channels != ["red", "ir"]:
        return None
    r, i = pulse(recent("red", WINDOW_S)), pulse(recent("ir", WINDOW_S))
    if not r or not i or i["ac"] <= 0 or r["dc"] <= 0 or i["dc"] <= 0:
        return None
    ratio = (r["ac"] / r["dc"]) / (i["ac"] / i["dc"])
    return 110 - 25 * ratio            # common textbook approximation, NOT calibrated


# ---- protocol ------------------------------------------------------------------------------------

def run():
    say("─" * 72)
    say("Heart rate test · heart beat sensor on the UNO Q")
    say("─" * 72)
    say("1/5 waiting for the sketch to report its sensor …")
    t = time.monotonic()
    while sensor_epoch == 0 and time.monotonic() - t < 45:
        time.sleep(0.2)
    if sensor_epoch == 0:
        say("  no sensor report (the sketch was already running): using the sample format instead")
    _state["epoch"] = sensor_epoch
    t = time.monotonic()
    while total < FS and time.monotonic() - t < 60:
        time.sleep(0.2)
    if total < FS:
        say("VERDICT sensor: FAIL: no samples from the sketch")
        say("  → Is the sketch loaded? (it runs from RAM: load it again after any reset)")
        return False
    global count
    with lock:
        count = 0
    time.sleep(3)
    rate = count / 3
    say(f"  channels: {' '.join(channels)} · {rate:.0f} samples/s (expected {FS:.0f})")

    say(f"2/5 baseline: keep your finger OFF the sensor ({BASELINE_S:.0f} s) …")
    time.sleep(BASELINE_S)
    baseline = {c: float(np.median(recent(c, BASELINE_S))) for c in channels}
    say("  levels with no finger: " + ", ".join(f"{c} {v:.0f}" for c, v in baseline.items()))

    say(f"3/5 place a fingertip on the sensor and keep still (waiting up to {FINGER_TIMEOUT_S:.0f} s) …")
    t = time.monotonic()
    while not finger_on(baseline) and time.monotonic() - t < FINGER_TIMEOUT_S:
        time.sleep(1)
    if not finger_on(baseline):
        say("VERDICT sensor: FAIL: no finger / no pulse detected")
        say("  → MAX3010x: the IR level should jump when a finger covers it. Check the LEDs light up (red glow).")
        say("  → Analog module: power from 3V3, signal to A0-A3, LED facing the fingertip.")
        return True
    say(f"  finger detected after {time.monotonic() - t:.0f} s; settling 3 s")
    time.sleep(3)

    say(f"4/5 measuring {MEASURE_S:.0f} s: keep still …")
    ch = hr_channel()
    results, t = [], time.monotonic()
    while time.monotonic() - t < MEASURE_S:
        time.sleep(1)
        p = pulse(recent(ch, WINDOW_S))
        if p:
            results.append(p)
            live_line(ch, p)

    say("5/5 results")
    good = [p for p in results if plausible(p)]
    dc = np.median([p["dc"] for p in results]) if results else 0
    pi = np.median([p["pi"] for p in results]) if results else 0
    say(f"  channel {ch}: level {dc:.0f} of {full_scale} ({100 * dc / full_scale:.0f}%), "
        f"perfusion index {pi:.2f}%")
    if good:
        bpm = np.array([p["bpm"] for p in good])
        say(f"  heart rate {np.median(bpm):.0f} bpm (range {bpm.min():.0f}-{bpm.max():.0f}); "
            f"{len(good)}/{len(results)} seconds plausible (spectrum and beat count agree)")
    s = spo2_estimate()
    if s is not None:
        say(f"  SpO2 estimate {s:.0f}% (textbook formula, NOT calibrated: for comparison only)")
    hints = []
    if dc >= 0.95 * full_scale:
        hints.append("Signal near the top of the range: press more lightly or lower the LED current.")
    if 0 < pi < 0.2:
        hints.append("Weak pulse: warm the finger, cover the whole sensor window, don't press hard.")
    if good and len(good) >= 0.7 * len(results) and np.ptp([p["bpm"] for p in good]) <= 15:
        verdict, summary = "PASS", f"steady pulse at {np.median([p['bpm'] for p in good]):.0f} bpm"
    elif good:
        verdict, summary = "PARTIAL", "pulse found but not steady (movement, pressure or a weak signal)"
        hints.append("Rest the hand on the table and keep the finger still; then restart the app.")
    else:
        verdict, summary = "FAIL", "finger detected but no clear pulse"
        hints.append("Try another finger, lighter pressure, or shade the sensor from room light.")
    say(f"VERDICT sensor: {verdict}: {summary}")
    for h in hints:
        say(f"  → {h}")
    say(f"Raw samples: {REC_DIR}/hrtest.{STAMP}.csv · copy with: UNOQ_APP=hr-test tools/unoq pull")
    say("Live readout follows (once a second).")
    return True


def live_line(ch, p):
    ok = "ok" if plausible(p) else "--"
    s = spo2_estimate()
    live(f"{ch} level {p['dc']:7.0f} │ PI {p['pi']:5.2f}% │ HR {p['bpm']:5.1f} bpm (beats {p['bpm_peaks']:5.1f}) │ "
         f"quality {p['quality']:.2f} {ok}" + (f" │ SpO2~{s:.0f}%" if s is not None else ""))


_state = {"started": False, "live": False, "epoch": 0}


def loop():
    if _state["started"] and sensor_epoch != _state["epoch"]:
        say("The sketch reported a new sensor: running the test again.")
        _state["started"] = False
    if not _state["started"]:
        _state["started"] = True
        try:
            _state["live"] = run()
        except Exception as e:  # keep the app alive so the error stays visible in the logs
            say(f"✗ test aborted: {e!r}")
        return
    time.sleep(1)
    if _state["live"] and channels:
        ch = hr_channel()
        p = pulse(recent(ch, WINDOW_S))
        if p:
            live_line(ch, p)


App.run(user_loop=loop)
