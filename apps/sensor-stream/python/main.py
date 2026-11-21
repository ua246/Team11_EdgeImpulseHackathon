"""Team 11 · sensor-stream · Linux side of the UNO Q.

Receives sensor batches from sketch/sketch.ino over the Bridge and:
  * prints one status line per second: sample rates, latest values, a sparkline of the
    last 2 s, and the dominant frequency of the light and heart beat signals
    (this is the hour-one check: does the sensor see 5 / 15 / 25 Hz flicker correctly?)
  * records labelled CSV files for Edge Impulse when asked:
        tools/unoq record <label> <seconds>      (from the laptop)
    which writes data/record.json; files land in data/recordings/<label>.<time>.<stream>.csv
"""

import json
import math
import threading
import time
from collections import deque
from pathlib import Path

from arduino.app_utils import App, Bridge

# Nominal rates: keep in sync with the constants at the top of sketch/sketch.ino.
IMU_HZ = 50
LIGHT_HZ = 40  # LTR-381RGB hardware maximum (one reading per 25 ms)
HB_HZ = 200
WINDOW_S = 2.0
G = 9.80665
LIGHT_FULL_SCALE = 65535  # 16-bit light sensor counts
HB_FULL_SCALE = 1023      # 10-bit analogRead (UNO Q core default)

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONTROL_FILE = DATA_DIR / "record.json"
REC_DIR = DATA_DIR / "recordings"

HEADERS = {
    "imu": "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ",  # ms, m/s^2, deg/s
    "light": "timestamp,red,green,blue",               # ms, raw counts
    "hb": "timestamp,hb",                              # ms, raw ADC
}

lock = threading.Lock()
imu_win = deque(maxlen=int(IMU_HZ * WINDOW_S))      # |a| in g
light_win = deque(maxlen=int(LIGHT_HZ * WINDOW_S))  # green channel (closest to brightness)
red_win = deque(maxlen=int(LIGHT_HZ * WINDOW_S))    # red share of r+g+b
hb_win = deque(maxlen=int(HB_HZ * WINDOW_S))
counts = {"imu": 0, "light": 0, "hb": 0, "bad": 0}
latest = {}
mcu = {}


class Recorder:
    """Writes incoming rows to one CSV per stream while a recording is active."""

    def __init__(self):
        self.label = None
        self.until = 0.0
        self.stamp = ""
        self.files = {}
        self.rows = {}

    def start(self, label, seconds):
        self.stop()
        try:
            REC_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[rec] ✗ cannot create {REC_DIR}: {e}", flush=True)
            return
        self.label, self.until = label, time.monotonic() + seconds
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.files, self.rows = {}, {}
        print(f"[rec] ● recording '{label}' for {seconds:g}s", flush=True)

    def write(self, stream, rows):
        if self.label is None or not rows:
            return
        f = self.files.get(stream)
        if f is None:
            f = open(REC_DIR / f"{self.label}.{self.stamp}.{stream}.csv", "w")
            f.write(HEADERS[stream] + "\n")
            self.files[stream], self.rows[stream] = f, 0
        f.write("\n".join(rows) + "\n")
        self.rows[stream] += len(rows)

    def tick(self):
        if self.label is not None and time.monotonic() >= self.until:
            self.stop()

    def remaining(self):
        return max(0.0, self.until - time.monotonic())

    def stop(self):
        if self.label is None:
            return
        for f in self.files.values():
            f.close()
        summary = ", ".join(f"{k} {v} rows" for k, v in self.rows.items()) or "NO DATA RECEIVED"
        print(f"[rec] ■ saved '{self.label}': {summary} → {REC_DIR}", flush=True)
        self.label, self.files = None, {}


recorder = Recorder()


# ---- Bridge handlers (called by the sketch via Bridge.notify) ----------------------------

def on_imu(batch: str):
    rows = []
    with lock:
        for line in batch.splitlines():
            try:
                t, ax, ay, az, gx, gy, gz = (int(v) for v in line.split(","))
            except ValueError:
                counts["bad"] += 1
                continue
            counts["imu"] += 1
            imu_win.append(math.sqrt(ax * ax + ay * ay + az * az) / 1000.0)
            latest["imu"] = (ax, ay, az, gx, gy, gz)
            if recorder.label:
                rows.append(f"{t},{ax * G / 1000:.4f},{ay * G / 1000:.4f},{az * G / 1000:.4f},"
                            f"{gx / 10:.1f},{gy / 10:.1f},{gz / 10:.1f}")
        recorder.write("imu", rows)


def on_light(batch: str):
    rows = []
    with lock:
        for line in batch.splitlines():
            try:
                t, r, g, b = (int(v) for v in line.split(","))
            except ValueError:
                counts["bad"] += 1
                continue
            counts["light"] += 1
            light_win.append(g)
            red_win.append(r / (r + g + b) if r + g + b else 0.0)
            latest["light"] = (r, g, b)
            if recorder.label:
                rows.append(f"{t},{r},{g},{b}")
        recorder.write("light", rows)


def on_hb(t0: int, batch: str):
    rows = []
    with lock:
        for tok in batch.split():
            try:
                rel, val = (int(v) for v in tok.split(":"))
            except ValueError:
                counts["bad"] += 1
                continue
            counts["hb"] += 1
            hb_win.append(val)
            latest["hb"] = val
            if recorder.label:
                rows.append(f"{t0 + rel},{val}")
        recorder.write("hb", rows)


def on_mcu(imu_ok, light_ok, n_imu, n_light, n_hb, hb_missed, max_flush_us):
    with lock:
        for name, now_ok in (("IMU", imu_ok), ("Light sensor", light_ok)):
            was = mcu.get(name)
            if was is not None and bool(was) != bool(now_ok):
                print(f"[mcu] {name}: {'connected' if now_ok else 'LOST'}", flush=True)
            mcu[name] = now_ok
        mcu["report"] = (n_imu, n_light, n_hb, hb_missed, max_flush_us)


Bridge.provide("imu", on_imu)
Bridge.provide("light", on_light)
Bridge.provide("hb", on_hb)
Bridge.provide("mcu", on_mcu)


# ---- Status line --------------------------------------------------------------------------

SPARK = "▁▂▃▄▅▆▇█"


def spark(values, width=16):
    vals = list(values)
    if len(vals) < width:
        return "·" * width
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return SPARK[0] * width
    step = len(vals) / width
    pts = [vals[int(i * step)] for i in range(width)]
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in pts)


def dominant_freq(values, fs, fmin, fmax, step=0.5):
    """Strongest frequency in [fmin, fmax] and the share of signal energy in it (0..1)."""
    x = list(values)
    n = len(x)
    if n < fs:  # need at least 1 s of data
        return None, 0.0
    mean = sum(x) / n
    x = [v - mean for v in x]
    energy = sum(v * v for v in x)
    if energy < 1e-9:
        return None, 0.0
    best_f, best_p = None, 0.0
    f = fmin
    while f <= fmax + 1e-9:
        w = 2 * math.pi * f / fs
        re = sum(v * math.cos(w * i) for i, v in enumerate(x))
        im = sum(v * math.sin(w * i) for i, v in enumerate(x))
        p = re * re + im * im
        if p > best_p:
            best_f, best_p = f, p
        f += step
    return best_f, min(1.0, 2 * best_p / (n * energy))


def swing_text(values, full_scale):
    """Brightness swing over the window: how much dimmer the dark phase is than the bright phase, in %.

    Uses the 2nd and 98th percentiles, so a single noisy reading doesn't count, but a strobe still
    registers if at least ~2% of readings catch a flash. Only meaningful when the reading is
    proportional to light (0 = dark). Appends SAT when the bright phase hits the top of the range.
    """
    v = sorted(values)
    if len(v) < 20:
        return "swing   —"
    lo, hi = v[int(0.02 * (len(v) - 1))], v[int(0.98 * (len(v) - 1))]
    if hi <= 0:
        return "swing   —"
    sat = " SAT" if hi >= 0.99 * full_scale else ""
    return f"swing {100.0 * (hi - lo) / hi:3.0f}%{sat}"


def freq_text(values, fs, fmin, fmax):
    f, share = dominant_freq(values, fs, fmin, fmax)
    if f is None or share < 0.3:
        return "  —    "
    return f"~{f:4.1f}Hz"


_last_status = time.monotonic()


def print_status():
    global _last_status
    now = time.monotonic()
    dt, _last_status = now - _last_status, now
    with lock:
        c = dict(counts)
        for k in counts:
            counts[k] = 0
        imu, light, red, hb = list(imu_win), list(light_win), list(red_win), list(hb_win)
        lat, rep = dict(latest), mcu.get("report")
        rec = (recorder.label, recorder.remaining()) if recorder.label else None

    parts = []
    if c["imu"]:
        parts.append(f"IMU {c['imu'] / dt:4.0f}/s |a| {imu[-1]:4.2f}g {spark(imu)}")
    else:
        parts.append("IMU  no data (Qwiic cable?)")
    if c["light"]:
        r, g, b = lat["light"]
        parts.append(f"LIGHT {c['light'] / dt:3.0f}/s G {g:6d} red {red[-1]:4.0%} {spark(light)} "
                     f"{swing_text(light, LIGHT_FULL_SCALE)} {freq_text(light, LIGHT_HZ, 1.0, LIGHT_HZ / 2)}")
    else:
        parts.append("LIGHT no data (Qwiic cable?)")
    if c["hb"]:
        parts.append(f"HB {c['hb'] / dt:4.0f}/s {lat['hb']:5d} {spark(hb)} "
                     f"{swing_text(hb, HB_FULL_SCALE)} {freq_text(hb, HB_HZ, 0.5, 60.0)}")
    else:
        parts.append("HB    no data")
    if rec:
        parts.append(f"● REC {rec[0]} {rec[1]:.0f}s")
    print("[stat] " + " │ ".join(parts), flush=True)

    if c["bad"]:
        print(f"[warn] {c['bad']} malformed samples in the last second", flush=True)
    if rep and (rep[3] or rep[4] > 20000):
        print(f"[warn] MCU: {rep[3]} heart beat samples missed, slowest Bridge send {rep[4] / 1000:.1f} ms",
              flush=True)


# ---- Record requests from the laptop (data/record.json) ----------------------------------

def _mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


_ctrl_mtime = _mtime(CONTROL_FILE)  # ignore a request left over from before this start


def check_control():
    global _ctrl_mtime
    m = _mtime(CONTROL_FILE)
    if m is None or m == _ctrl_mtime:
        return
    _ctrl_mtime = m
    try:
        req = json.loads(CONTROL_FILE.read_text())
        label, seconds = str(req["label"]), float(req.get("seconds", 10))
    except (OSError, ValueError, KeyError) as e:
        print(f"[rec] ✗ could not read {CONTROL_FILE.name}: {e}", flush=True)
        return
    with lock:
        if label == "stop":
            recorder.stop()
        else:
            recorder.start(label, seconds)


_next_status = time.monotonic() + 1.0


def loop():
    global _next_status
    check_control()
    with lock:
        recorder.tick()
    if time.monotonic() >= _next_status:
        _next_status += 1.0
        print_status()
    time.sleep(0.05)


print(f"[boot] sensor-stream started · IMU {IMU_HZ} Hz, light ≤{LIGHT_HZ} Hz, heart beat {HB_HZ} Hz "
      f"· recordings → {REC_DIR}", flush=True)
App.run(user_loop=loop)
