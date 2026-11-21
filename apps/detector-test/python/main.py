"""Team 11 · detector-test · can the heart beat module measure flicker?

Runs once when the app starts (restart the app to run it again). Wiring:
hardware/detector-test/detector-test.kicad_sch. The test LED D1 must face the module's
detector inside a light-tight tube, and the module's own LED must be covered.

Test algorithm
  1. dark     LED off, 1 s           -> baseline level and noise of each channel
  2. steady   LED on, 1 s            -> response size, polarity, saturation
  3. step     off 0.5 s / on 1 s / off 0.5 s
                                     -> 10-90 % rise and fall time, bandwidth ~ 0.35 / rise time,
                                        and whether the module has a built-in heartbeat filter
                                        (output falls back to baseline under steady light)
  4. sweep    50 % square wave at 1-60 Hz, 2 s each
                                     -> frequency found at 1000 samples/s and at 200/s (what the
                                        sensor-stream app uses), response vs. a perfect detector,
                                        brightness swing
  5. pulses   10 Hz flashes of 1 ms and 5 ms
                                     -> how many short flashes are caught at 1000/s and at 200/s
  6. verdict  per channel:
                PASS     frequency right and response >= 50 % up to at least 30 Hz,
                         and frequency right at 200/s from 3 to 30 Hz
                PARTIAL  usable up to at least 10 Hz
                FAIL     anything less, or no response
Results: printed as [test] lines and saved to data/recordings/ (pull with tools/unoq pull).
"""

import math
import time
import traceback
from pathlib import Path

from arduino.app_utils import App, Bridge

try:
    import numpy as np  # optional: makes the analysis faster
except ImportError:
    np = None

RATE = 1000                         # samples per second during captures
FULL_SCALE = 4095                   # 12-bit (analogReadResolution(12) in the sketch)
CHANNELS = {                        # sketch channel index -> name. Index 0 is A1, the optional
    1: "A2 raw",                    # phototransistor (Q2/R4): add  0: "A1 phototransistor"  if fitted.
    2: "A3 filtered",
}
SWEEP_HZ = [1, 2, 3, 5, 8, 10, 12, 15, 18, 20, 25, 30, 40, 50, 60]
STREAM_DECIMATE = 5                 # 1000/s -> 200/s, like sensor-stream
CHUNK = 300                         # samples per chunk() call

REC_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"
STAMP = time.strftime("%Y%m%d-%H%M%S")


def say(msg=""):
    print(f"[test] {msg}", flush=True)


# ---- talking to the sketch ------------------------------------------------------------------

def capture(step, duration_ms, period_us, on_start_us, on_len_us):
    """Run one capture on the MCU and fetch the samples. Returns ({channel: samples}, actual rate)."""
    res = Bridge.call("capture", duration_ms, period_us, on_start_us, on_len_us, RATE,
                      timeout=duration_ms / 1000 + 10)
    n, elapsed_us, late = (int(v) for v in str(res).split(","))
    fs = n / (elapsed_us / 1e6) if elapsed_us else RATE
    if late > n * 0.01 or abs(fs - RATE) > RATE * 0.02:
        say(f"  ! timing: {late} of {n} samples late, actual rate {fs:.1f}/s (analysis uses the actual rate)")
    data = {}
    for ch in CHANNELS:
        vals = []
        for start in range(0, n, CHUNK):
            s = str(Bridge.call("chunk", ch, start, min(CHUNK, n - start), timeout=10))
            vals.extend(int(s[i:i + 3], 16) for i in range(0, len(s) - 2, 3))
        if len(vals) != n:
            raise RuntimeError(f"channel {ch}: got {len(vals)} of {n} samples")
        data[ch] = vals
    save_raw(step, data, fs)
    return data, fs


def save_raw(step, data, fs):
    try:
        REC_DIR.mkdir(parents=True, exist_ok=True)
        chans = list(data)
        with open(REC_DIR / f"dettest.{STAMP}.{step}.csv", "w") as f:
            f.write("timestamp," + ",".join(CHANNELS[c].split()[0] for c in chans) + "\n")
            for i in range(len(data[chans[0]])):
                f.write(f"{i * 1000 / fs:.2f}," + ",".join(str(data[c][i]) for c in chans) + "\n")
    except OSError as e:
        say(f"  ! could not save raw data: {e}")


def square(f_hz, duty=0.5):
    period = round(1e6 / f_hz)
    return period, 0, round(period * duty)


# ---- analysis -----------------------------------------------------------------------------------

def mean(x):
    return sum(x) / len(x)


def median(x):
    s = sorted(x)
    return s[len(s) // 2]


def std(x):
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / len(x))


def percentile(x, p):
    s = sorted(x)
    return s[int(p / 100 * (len(s) - 1))]


def amplitude_at(x, fs, f):
    """Amplitude of the sine component at f (Goertzel), over a whole number of cycles."""
    n = int(int(len(x) * f / fs) * fs / f)
    if n >= fs / f:
        x = x[:n]
    m = mean(x)
    w = 2 * math.pi * f / fs
    c = 2 * math.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = (v - m) + c * s1 - s2, s1
    p = s1 * s1 + s2 * s2 - c * s1 * s2
    return 2 * math.sqrt(max(p, 0.0)) / len(x)


def dominant(x, fs, fmin, fmax):
    """Strongest frequency in [fmin, fmax] and its amplitude."""
    fmax = min(fmax, fs / 2 - 0.5)
    if np is not None:
        y = np.asarray(x, dtype=float)
        y -= y.mean()
        nfft = 1 << (len(y) * 8 - 1).bit_length()
        spec = np.abs(np.fft.rfft(y, nfft))
        freqs = np.fft.rfftfreq(nfft, 1 / fs)
        band = (freqs >= fmin) & (freqs <= fmax)
        i = int(np.argmax(spec[band]))
        return float(freqs[band][i]), float(2 * spec[band][i] / len(y))
    best_f, best_a = fmin, -1.0
    f = fmin
    while f <= fmax:
        a = amplitude_at(x, fs, f)
        if a > best_a:
            best_f, best_a = f, a
        f += 0.5
    f = best_f - 0.5
    while f <= best_f + 0.5:
        a = amplitude_at(x, fs, f)
        if a > best_a:
            best_f, best_a = f, a
        f += 0.05
    return best_f, best_a


def swing(x):
    lo, hi = percentile(x, 2), percentile(x, 98)
    return 100.0 * (hi - lo) / hi if hi > 0 else 0.0


def first_cross(norm, start, level, rising, stop):
    for i in range(start, min(stop, len(norm))):
        if (norm[i] >= level) if rising else (norm[i] <= level):
            return i
    return None


# ---- the test ------------------------------------------------------------------------------------

def run():
    time.sleep(3)  # give the sketch time to start
    say("─" * 72)
    say(f"Detector test · {RATE} samples/s · channels: {', '.join(CHANNELS.values())}")
    say("Setup: test LED D1 facing the detector in a light-tight tube; module LED covered.")
    say("─" * 72)
    res = {ch: {"sweep": []} for ch in CHANNELS}

    say("1/5 dark and steady light …")
    dark, _ = capture("dark", 1000, 1, 0, 0)
    on, _ = capture("steady", 1000, 1, 0, 1)
    for ch in CHANNELS:
        r = res[ch]
        d, o = dark[ch][len(dark[ch]) // 2:], on[ch][len(on[ch]) // 2:]   # settled second halves
        r["dark"], r["noise"], r["on"] = median(d), std(d), median(o)
        r["contrast"] = r["on"] - r["dark"]
        r["sat"] = r["on"] >= 0.98 * FULL_SCALE or (r["contrast"] < 0 and r["on"] <= 0.02 * FULL_SCALE)
        r["thr"] = max(10 * r["noise"], 0.01 * FULL_SCALE)

    say("2/5 step response …")
    step, fs = capture("step", 2000, 2_000_000, 500_000, 1_000_000)
    for ch in CHANNELS:
        r, x = res[ch], step[ch]
        lo = median(x[int(0.05 * fs):int(0.45 * fs)])
        hi = median(x[int(1.0 * fs):int(1.45 * fs)])
        peak = max(x[int(0.5 * fs):int(1.5 * fs)], key=lambda v: abs(v - lo))
        # A module with a heartbeat filter jumps on the step, then falls back to baseline.
        r["ac_coupled"] = abs(peak - lo) > 3 * max(abs(hi - lo), 1) and abs(peak - lo) >= r["thr"]
        r["base"] = lo
        r["ref"] = (peak - lo) if r["ac_coupled"] else r["contrast"]    # signed full response
        r["responds"] = abs(r["ref"]) >= r["thr"]
        r["rise_ms"] = r["fall_ms"] = None
        if abs(hi - lo) >= r["thr"] and not r["ac_coupled"]:
            norm = [(v - lo) / (hi - lo) for v in x]
            i_on, i_off = int(0.5 * fs), int(1.5 * fs)
            a, b = first_cross(norm, i_on, 0.1, True, i_off), first_cross(norm, i_on, 0.9, True, i_off)
            c, d = first_cross(norm, i_off, 0.9, False, len(norm)), first_cross(norm, i_off, 0.1, False, len(norm))
            if a is not None and b is not None:
                r["rise_ms"] = (b - a) * 1000 / fs
            if c is not None and d is not None:
                r["fall_ms"] = (d - c) * 1000 / fs

    say(f"3/5 frequency sweep {SWEEP_HZ[0]}-{SWEEP_HZ[-1]} Hz …")
    for f in SWEEP_HZ:
        data, fs = capture(f"sweep_{f}hz", 2000, *square(f))
        for ch in CHANNELS:
            r = res[ch]
            x = data[ch][int(0.1 * fs):]          # skip the first 0.1 s
            xs = x[::STREAM_DECIMATE]              # instant readings at 200/s, like sensor-stream
            f1k, _ = dominant(x, fs, 0.5, 100)
            f200, _ = dominant(xs, fs / STREAM_DECIMATE, 0.5, 100)
            ideal = 2 * abs(r["ref"]) / math.pi        # fundamental of a perfect square-wave response
            resp = amplitude_at(x, fs, f) / ideal if ideal > 0 else 0.0
            r["sweep"].append((f, f1k, f200, resp, swing(xs)))

    say("4/5 short flashes …")
    for width_us in (1000, 5000):
        # Flashes start 0.5 ms into each period so they don't line up with the sample clock.
        data, fs = capture(f"pulses_{width_us // 1000}ms", 2000, 100_000, 500, width_us)
        for ch in CHANNELS:
            r = res[ch]
            if not r["responds"]:
                continue
            x, per = data[ch], int(0.1 * fs)
            periods = len(x) // per
            norm = [(v - r["base"]) / r["ref"] for v in x]
            caught_1k = sum(max(norm[k * per:(k + 1) * per]) >= 0.25 for k in range(periods))
            # At 200/s a flash is caught only if a reading happens to land on it: average over
            # the 5 possible reading offsets for the expected catch count.
            caught_200 = mean([sum(max(norm[i] for i in range(k * per + off, (k + 1) * per, STREAM_DECIMATE)) >= 0.25
                                   for k in range(periods)) for off in range(STREAM_DECIMATE)])
            r[f"pulses_{width_us // 1000}ms"] = (caught_1k, caught_200, periods)

    say("5/5 results")
    lines = ["channel,step,f_drive_hz,f_seen_1000,f_seen_200,response_pct,swing_pct"]
    for ch, name in CHANNELS.items():
        report(name, res[ch], lines)
    try:
        REC_DIR.mkdir(parents=True, exist_ok=True)
        (REC_DIR / f"dettest.{STAMP}.results.csv").write_text("\n".join(lines) + "\n")
    except OSError as e:
        say(f"! could not save results: {e}")
    say("─" * 72)
    say(f"Done. Raw captures + results: {REC_DIR}/dettest.{STAMP}.*")
    say("Copy to the laptop: UNOQ_APP=detector-test tools/unoq pull · run again: tools/unoq restart")


def report(name, r, lines):
    say("─" * 72)
    say(f"{name}: dark {r['dark']:.0f} ± {r['noise']:.1f}, LED on {r['on']:.0f}, "
        f"contrast {r['contrast']:+.0f} of {FULL_SCALE}")
    hints = []
    if not r["responds"]:
        verdict, usable = "FAIL", 0
        say(f"VERDICT {name}: FAIL: no clear response to the test LED")
        hints += ["Check wiring: module S → A2, + → 3V3, − → GND.",
                  "Aim D1 straight at the detector, 1-2 cm away, inside the tube.",
                  "Is the module's own LED covered? A lit module LED swamps the test LED.",
                  "An IR-only detector (dark lens) barely sees a white LED: try the optional phototransistor."]
        for h in hints:
            say(f"  → {h}")
        return

    if r["contrast"] < 0:
        hints.append("Inverted output (more light = lower reading). Fine for frequency; flip it in software "
                     "before using the swing readout.")
    if r["sat"]:
        hints.append("Saturated: move D1 further away, add a layer of paper, or raise R3. Then re-run.")
    if r["ac_coupled"]:
        hints.append("Output falls back to baseline under steady light: the module has a built-in heartbeat "
                     "filter. Use a bare phototransistor (Q2/R4) or tap the detector before the amplifier.")

    if r["ac_coupled"]:
        say(f"  step: output jumps by {r['ref']:+.0f}, then falls back to baseline under steady light")
    rise = f"{r['rise_ms']:.1f} ms" if r["rise_ms"] is not None else "n/a"
    fall = f"{r['fall_ms']:.1f} ms" if r["fall_ms"] is not None else "n/a"
    bw = f" → bandwidth ≈ {350 / r['rise_ms']:.0f} Hz" if r["rise_ms"] else ""
    say(f"  step: rise {rise}, fall {fall}{bw}")
    say("  drive   seen@1000/s  seen@200/s  response  swing@200/s")
    usable, ok200 = 0, True
    for f, f1k, f200, resp, sw in r["sweep"]:
        good1k = abs(f1k - f) <= 0.5
        good200 = abs(f200 - f) <= 0.5
        if good1k and resp >= 0.5:
            usable = max(usable, f)
        if 3 <= f <= 30 and not good200:
            ok200 = False
        say(f"  {f:4.0f} Hz  {f1k:6.1f}{'' if good1k else ' ✗'}{'':5}{f200:6.1f}{'' if good200 else ' ✗'}"
            f"{'':4}{100 * resp:5.0f} %   {sw:5.0f} %")
        lines.append(f"{name},sweep,{f},{f1k:.2f},{f200:.2f},{100 * resp:.1f},{sw:.1f}")
    for key in ("pulses_1ms", "pulses_5ms"):
        if key in r:
            c1k, c200, tot = r[key]
            say(f"  10 Hz flashes of {key[7:]}: caught {c1k}/{tot} at 1000/s, ~{c200:.0f}/{tot} at 200/s")
            lines.append(f"{name},{key},10,{c1k},{c200:.1f},,")
            if key == "pulses_1ms" and c200 < tot * 0.8:
                hints.append("Short (1 ms) flashes often fall between 200/s readings: compare A2 and A3 here "
                             "(R1/C1 stretches flashes), or keep the highest of several quick readings per sample.")

    if usable >= 30 and ok200:
        verdict = "PASS"
        summary = f"reads flicker correctly up to {usable} Hz, and at 200/s from 3-30 Hz"
    elif usable >= 10:
        verdict = "PARTIAL"
        summary = f"usable up to {usable} Hz" + ("" if ok200 else "; some 3-30 Hz rates wrong at 200/s")
    else:
        verdict = "FAIL"
        summary = f"usable only up to {usable} Hz" if usable else "no frequency read correctly"
    say(f"VERDICT {name}: {verdict}: {summary}")
    for h in hints:
        say(f"  → {h}")


_started = False


def loop():
    global _started
    if not _started:
        _started = True
        try:
            run()
        except Exception as e:  # keep the app alive so the error stays visible in the logs
            say(f"✗ test aborted: {e!r}")
            traceback.print_exc()
    time.sleep(1)


App.run(user_loop=loop)
