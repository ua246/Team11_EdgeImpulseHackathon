"""Team 11 · light-test · Linux side of the UNO Q.

Listens to the sketch's automatic sweep (sketch/sketch.ino: a test LED flashing into the Modulino
Light at known rates), prints one line per finished step, then the report and VERDICT lines, and
saves:
    data/recordings/lighttest.<time>.report.txt    the report
    data/recordings/lighttest.<time>.csv           every reading (re-analyse with analysis.py)
    data/recordings/lighttest.<time>.live.csv      readings outside the sweep (screen test: screen_sweep.py)
Copy them to the laptop with `tools/unoq pull` (→ recordings/light-test/).
After the sweep it prints a live readout once a second, for manual checks with tools/flicker.html, and
saves those readings so tools/flicker.html → "Sweep" can be analysed on the laptop.
The analysis itself is in analysis.py.
"""

import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import analysis as an  # noqa: E402
from arduino.app_utils import App, Bridge  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent
REC_DIR = APP_DIR / "data" / "recordings"
LIVE_S = 3.0
LATE_WARN_US = 2000

lock = threading.Lock()
runs = {}                                  # run id -> state, see get_run()
events = deque()                           # ("end", run, idx) / ("done", run) for the main loop
live = deque(maxlen=int(40 * LIVE_S))      # (t_s, r, g, b) while no step is running
counts = {"live": 0, "orphan": 0, "bad": 0}
LIVE_STAMP = time.strftime("%Y%m%d-%H%M%S")
live_file = {"f": None}
state = {"running": False, "last_msg": time.monotonic(), "channel": 1, "rerun_asked": False,
         "warned_at": 0.0, "started": time.monotonic()}


def get_run(run):
    r = runs.get(run)
    if r is None:
        r = {"steps": {}, "n": 0, "range": None, "ends": {}, "csv": None, "reported": False,
             "stamp": time.strftime("%Y%m%d-%H%M%S")}
        runs[run] = r
    return r


def live_csv():
    if live_file["f"] is None:
        try:
            REC_DIR.mkdir(parents=True, exist_ok=True)
            live_file["f"] = open(REC_DIR / f"lighttest.{LIVE_STAMP}.live.csv", "w")
            live_file["f"].write("t_ms,red,green,blue\n")
        except OSError as e:
            print(f"[warn] can't save live readings: {e}", flush=True)
            live_file["f"] = False
    return live_file["f"] or None


def csv_of(r):
    if r["csv"] is None:
        try:
            REC_DIR.mkdir(parents=True, exist_ok=True)
            r["csv"] = open(REC_DIR / f"lighttest.{r['stamp']}.csv", "w")
            r["csv"].write(an.CSV_HEADER + "\n")
        except OSError as e:
            print(f"[warn] can't save readings: {e}", flush=True)
            r["csv"] = False
    return r["csv"] or None


# ---- Messages from the sketch (keep these short: they run on the Bridge thread) ----------------

def on_info(text):
    print(str(text), flush=True)


def on_range(run, code, gain_x, on, dark, saturated):
    with lock:
        get_run(run)["range"] = {"gain_x": int(gain_x), "on": int(on), "dark": int(dark),
                                 "saturated": bool(saturated)}
        state["last_msg"] = time.monotonic()


def on_step(run, idx, n, kind, f10, on_us, dur_ms):
    st = {"kind": str(kind), "freq": f10 / 10, "on_us": int(on_us), "dur_ms": int(dur_ms), "t": [], "rgb": []}
    with lock:
        r = get_run(run)
        r["n"] = int(n)
        r["steps"][int(idx)] = st
        state["running"] = True
        state["last_msg"] = time.monotonic()
    print(f"[test] → step {idx + 1}/{n}: {an.describe(st)} ({dur_ms / 1000:g} s)", flush=True)


def on_s(run, idx, batch):
    rows = []
    for tok in str(batch).split(";"):
        if not tok:
            continue
        try:
            t, r_, g, b = (int(v) for v in tok.split(","))
        except ValueError:
            counts["bad"] += 1
            continue
        rows.append((t / 10000.0, r_, g, b))      # 0.1 ms units -> s
    with lock:
        state["last_msg"] = time.monotonic()
        if idx < 0:
            live.extend(rows)
            counts["live"] += len(rows)
            f = live_csv()
            if f:
                f.writelines(f"{t * 1000:.1f},{a},{g},{b}\n" for t, a, g, b in rows)
            return
        r = runs.get(run)
        st = r["steps"].get(idx) if r else None
        if st is None:                            # joined in the middle of this step
            counts["orphan"] += len(rows)
            return
        for t, a, g, b in rows:
            st["t"].append(t)
            st["rgb"].append((a, g, b))
        f = csv_of(r)
        if f:
            f.writelines(f"{run},{idx},{st['kind']},{st['freq']:g},{st['on_us']},{t * 1000:.1f},{a},{g},{b}\n"
                         for t, a, g, b in rows)


def on_end(run, idx, n, late_us, send_us):
    with lock:
        r = runs.get(run)
        if r is not None:
            r["ends"][int(idx)] = {"n": int(n), "late_us": int(late_us), "send_us": int(send_us)}
        events.append(("end", run, int(idx)))


def on_done(run, n):
    with lock:
        state["running"] = False
        events.append(("done", run))


Bridge.provide("info", on_info)
Bridge.provide("range", on_range)
Bridge.provide("step", on_step)
Bridge.provide("s", on_s)
Bridge.provide("end", on_end)
Bridge.provide("done", on_done)


# ---- Per-step lines, report, live readout -----------------------------------------------------

def pct(v):
    return f"{v * 100:3.0f}%" if v is not None else "  –"


def step_line(run, idx):
    with lock:
        r = runs.get(run)
        if r is None or idx not in r["steps"]:
            return
        steps = {i: dict(s, t=list(s["t"]), rgb=list(s["rgb"])) for i, s in r["steps"].items()}
        end = r["ends"].get(idx, {})
    st = steps[idx]
    ctx = an.context(steps)
    state["channel"] = ctx["channel"]
    t, rgb = an.settled(st)
    if len(t) < 16:
        print(f"[warn] {an.describe(st)}: only {len(t)} readings (sensor or Bridge problem?)", flush=True)
        return
    if st["kind"] == "square":
        a = an.analyse_square(st, ctx)
        seen = f"{a['seen']:5.1f} Hz" if a["prominence"] >= an.PROMINENCE_MIN else "    – Hz"
        print(f"[step] {an.describe(st):15s} seen {seen} (expected {a['expect']:4.1f}) · "
              f"response {pct(a['response'])} (predicted {pct(a['predicted'])}) · swing {pct(a['swing'])} · "
              f"{a['result']}", flush=True)
    elif st["kind"] == "flash":
        a = an.analyse_flash(st, ctx)
        e = f", energy {pct(a['energy'])} of predicted" if a["energy"] is not None else ""
        mark = "✓" if a["sent"] and a["caught"] >= 0.9 * a["sent"] else "✗"
        print(f"[step] {an.describe(st):15s} caught {a['caught']}/{a['sent']}{e} {mark}", flush=True)
    else:
        m, s = rgb.mean(0), rgb.std(0)
        print(f"[step] {st['kind']:15s} R/G/B {m[0]:.0f} / {m[1]:.0f} / {m[2]:.0f} counts "
              f"(noise {s[0]:.1f} / {s[1]:.1f} / {s[2]:.1f}) · {len(t) / max(t[-1] - t[0], 1e-6):.1f} readings/s",
              flush=True)
        if st["kind"] == "steady" and rgb.max() >= 0.98 * an.FULL_SCALE:
            print("[warn] the steady LED saturates the sensor: add paper between LED and sensor, or move it away",
                  flush=True)
    if end.get("late_us", 0) > LATE_WARN_US:
        print(f"[warn] LED edges up to {end['late_us'] / 1000:.1f} ms late in this step "
              f"(slowest Bridge send {end['send_us'] / 1000:.1f} ms)", flush=True)


def finish(run):
    with lock:
        r = runs.get(run)
        if r is None or r["reported"]:
            return
        r["reported"] = True
        steps = {i: dict(s, t=list(s["t"]), rgb=list(s["rgb"])) for i, s in r["steps"].items()}
        n, rng, ends, stamp, f = r["n"], r["range"], dict(r["ends"]), r["stamp"], r["csv"]
    lines, _ = an.report(steps, n, rng, ends, title=f"run {run} · {stamp}")
    print("", flush=True)
    for line in lines:
        print(line, flush=True)
    path = REC_DIR / f"lighttest.{stamp}.report.txt"
    try:
        REC_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        if f:
            f.close()
        print(f"[rec] saved data/recordings/lighttest.{stamp}.report.txt and .csv · "
              f"copy to the laptop with: tools/unoq pull", flush=True)
    except OSError as e:
        print(f"[warn] can't save the report: {e}", flush=True)
    if len(steps) < n and not state["rerun_asked"]:
        state["rerun_asked"] = True
        try:
            Bridge.call("run", timeout=5)
            print("[test] some steps were missed: asked the sketch for a new full run", flush=True)
        except Exception as e:  # noqa: BLE001 (MCU calls are unverified on our board: DI-20)
            print(f"[warn] {n - len(steps)} steps were missed and the sketch didn't take a rerun request ({e}). "
                  "Run `tools/unoq restart` for a full run.", flush=True)
    print("[test] live readout follows (LED off). Point the sensor at tools/flicker.html for manual checks: "
          "true rates read correctly up to about 15 Hz; faster flicker shows lower (20 → 16 Hz, 25 → 11 Hz, 30 → 6 Hz).",
          flush=True)


SPARK = "▁▂▃▄▅▆▇█"


def spark(x, width=16):
    x = list(x)[-width:]
    lo, hi = min(x), max(x)
    if hi - lo < 1:
        return SPARK[0] * len(x)
    return "".join(SPARK[min(7, int((v - lo) / (hi - lo) * 8))] for v in x)


def live_line():
    with lock:
        data = list(live)
        n, counts["live"] = counts["live"], 0
    if len(data) < 16:
        if n == 0:
            return
        print(f"[live] {n}/s (collecting)", flush=True)
        return
    t = np.array([d[0] for d in data])
    back = np.where(np.diff(t) < 0)[0]            # the time base restarts with each phase
    if len(back):
        data, t = data[back[-1] + 1:], t[back[-1] + 1:]
    if len(t) < 16 or t[-1] <= t[0]:
        return
    ch = state["channel"]
    x = np.array([d[1 + ch] for d in data], float)
    fs = (len(t) - 1) / (t[-1] - t[0])
    f, _, prom = an.dominant(t, x, fs)
    hi = np.percentile(x, 98)
    sw = (hi - np.percentile(x, 2)) / hi if hi > 0 else 0.0
    freq = f"~{f:.1f}Hz" if prom >= an.PROMINENCE_MIN and sw >= 0.05 else "steady"
    print(f"[live] {n:3d}/s {an.CHANNELS[ch][0].upper()} {x[-1]:6.0f} {spark(x)} swing {sw * 100:3.0f}% {freq}",
          flush=True)


_next = time.monotonic() + 1.0


def loop():
    global _next
    while True:
        with lock:
            ev = events.popleft() if events else None
        if ev is None:
            break
        if ev[0] == "end":
            step_line(ev[1], ev[2])
        else:
            finish(ev[1])
    now = time.monotonic()
    if now >= _next:
        _next += 1.0
        if not state["running"]:
            live_line()
        with lock:
            if live_file["f"]:
                live_file["f"].flush()
        quiet = now - state["last_msg"]
        if quiet > 12 and now - state["warned_at"] > 30:
            state["warned_at"] = now
            print(f"[warn] no data from the sketch for {quiet:.0f} s. When flashing from the laptop the sketch "
                  "starts ~20 s after Python; otherwise check the Qwiic cable and `tools/unoq flash`.", flush=True)
        if counts["bad"]:
            print(f"[warn] {counts['bad']} malformed readings", flush=True)
            counts["bad"] = 0
    time.sleep(0.05)


print("[boot] light-test started · the sketch runs the sweep by itself 6 s after it boots "
      "(~2.5 min); results print as each step ends", flush=True)
print(f"[rec] live readings → data/recordings/lighttest.{LIVE_STAMP}.live.csv "
      "(screen test: tools/flicker.html → Sweep, then screen_sweep.py)", flush=True)
App.run(user_loop=loop)
