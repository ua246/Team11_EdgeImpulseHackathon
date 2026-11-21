"""Team 11 · light-test · analysis.

Used by main.py on the board, and on the laptop to re-analyse a saved run:
    python3 apps/light-test/python/analysis.py recordings/light-test/lighttest.<time>.csv

The model being tested (DI-01): the Modulino Light averages the light over one reading period
(nominally 25 ms; 40 readings/s, measured about 36/s on our board). So a square wave at f Hz should show up
  * at f itself while f is below half the reading rate (about 18 Hz), and at |f - k·fs| above it;
  * with a fundamental of |sinc(f·T)| (T = 1/fs, measured) of its full strength (2/π of the on-off step).
Short flashes are summed into the reading they fall in, so none should be missed.
"""

import math
import sys
from pathlib import Path

import numpy as np

SETTLE_S = 0.5           # skip the start of each step (the first reading may straddle the change)
FULL_SCALE = 65535       # 16-bit readings
PROMINENCE_MIN = 6.0     # spectral peak / median of the spectrum: "a clear frequency"
SWING_MIN = 0.10         # minimum brightness change that counts as flicker (broadcast guidelines)
CHANNELS = ("red", "green", "blue")
FS_NOMINAL = 40.0


# ---- Model ------------------------------------------------------------------------------------

def alias(f, fs):
    """Frequency that f appears at when sampled fs times a second."""
    f = math.fmod(f, fs)
    return min(f, fs - f)


def box_response(f, T):
    """Strength left after averaging over T seconds (|sinc|)."""
    x = f * T
    return 1.0 if x == 0 else abs(math.sin(math.pi * x) / (math.pi * x))


# ---- Signal helpers ---------------------------------------------------------------------------

def dft(t, x, freqs):
    """Amplitude spectrum from the real timestamps (robust to jitter and missed readings).
    Linear trend removed, Hann window; a sine of amplitude A reads as about A at its frequency."""
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    if len(t) < 8 or t[-1] <= t[0]:
        return np.zeros(len(freqs))
    x = x - np.polyval(np.polyfit(t - t[0], x, 1), t - t[0])
    u = (t - t[0]) / (t[-1] - t[0])
    w = 0.5 - 0.5 * np.cos(2 * np.pi * u)
    e = np.exp(-2j * np.pi * np.outer(freqs, t - t[0]))
    return 2 * np.abs(e @ (x * w)) / w.sum()


def dominant(t, x, fs, f_min=0.5):
    """(frequency, amplitude, prominence) of the strongest component between f_min and fs/2."""
    freqs = np.arange(f_min, fs / 2, 0.02)
    amp = dft(t, x, freqs)
    if not len(amp) or not amp.any():
        return 0.0, 0.0, 0.0
    k = int(np.argmax(amp))
    return float(freqs[k]), float(amp[k]), float(amp[k] / max(np.median(amp), 1e-9))


def amplitude_near(t, x, f, width=0.3):
    if f < 0.3:
        return 0.0
    freqs = np.arange(max(0.2, f - width), f + width + 1e-9, 0.01)
    return float(dft(t, x, freqs).max())


def swing(x):
    return float(np.percentile(x, 98) - np.percentile(x, 2))


# ---- Steps ------------------------------------------------------------------------------------

def settled(step):
    """(t, rgb) of the step without its first SETTLE_S seconds."""
    t = np.asarray(step["t"], float)
    rgb = np.asarray(step["rgb"], float).reshape(-1, 3)
    keep = t >= SETTLE_S
    return t[keep], rgb[keep]


def step_rate(step):
    t = np.asarray(step["t"], float)
    if len(t) < 10 or t[-1] <= t[0]:
        return None
    return (len(t) - 1) / (t[-1] - t[0])


def describe(step):
    f = step["freq"]
    if step["kind"] == "square":
        return f"{f:g} Hz square"
    if step["kind"] == "flash":
        return f"{step['on_us'] / 1000:g} ms flash, {f:g}/s"
    return step["kind"]


def context(steps):
    """Reading rate, channel and levels from the dark / steady steps (with fallbacks)."""
    rates = [r for r in (step_rate(s) for s in steps.values() if s["t"]) if r]
    fs = float(np.median(rates)) if rates else FS_NOMINAL
    gaps = 0
    for s in steps.values():
        t = np.asarray(s["t"], float)
        if len(t) > 2:
            gaps += int((np.diff(t) > 1.5 / fs).sum())
    ctx = {"fs": fs, "T": 1.0 / fs, "gaps": gaps, "channel": 1, "contrast": None,
           "dark": None, "steady": None, "noise": 1.0, "saturated": False, "levels": {},
           "seen": True, "step_seen": None}

    def first(kind):
        for i in sorted(steps):
            if steps[i]["kind"] == kind and len(settled(steps[i])[0]) >= 10:
                return settled(steps[i])[1]
        return None

    dark, steady = first("dark"), first("steady")
    if dark is not None and steady is not None:
        contrast = steady.mean(0) - dark.mean(0)
        sat = steady.max(0) >= 0.98 * FULL_SCALE
        order = sorted(range(3), key=lambda c: (not sat[c], contrast[c]), reverse=True)
        ch = order[0]
        ctx.update(channel=ch, contrast=float(contrast[ch]), dark=float(dark[:, ch].mean()),
                   steady=float(steady[:, ch].mean()), noise=max(float(dark[:, ch].std()), 1.0),
                   saturated=bool(sat[ch]),
                   levels={CHANNELS[c]: (float(dark[:, c].mean()), float(steady[:, c].mean())) for c in range(3)})
        if contrast[ch] < max(200.0, 20 * ctx["noise"]):   # the light source never reached the sensor
            ctx.update(seen=False, step_seen=float(contrast[ch]), contrast=None)
    else:  # Python joined late: estimate the on-off step from the slow square waves
        slow = [settled(s)[1] for s in steps.values() if s["kind"] == "square" and 0 < s["freq"] <= 8]
        slow = [x for x in slow if len(x) >= 10]
        if slow:
            sw = np.array([[swing(x[:, c]) for c in range(3)] for x in slow]).mean(0)
            ch = int(np.argmax(sw))
            ctx.update(channel=ch, contrast=float(sw[ch]))
    return ctx


def analyse_square(step, ctx):
    t, rgb = settled(step)
    x = rgb[:, ctx["channel"]]
    fs, T, f = ctx["fs"], ctx["T"], step["freq"]
    seen, _, prom = dominant(t, x, fs)
    expect = alias(f, fs)
    region = "below" if f < 0.47 * fs else ("edge" if f <= 0.53 * fs else "above")
    tol = lambda ref: max(0.25, 0.03 * ref)
    clear = prom >= PROMINENCE_MIN
    C = ctx["contrast"]
    sw = swing(x) / C if C else None
    detected = clear and (sw is None or sw >= SWING_MIN)
    response = amplitude_near(t, x, expect) / (2 * C / math.pi) if C else None
    predicted = box_response(f, T)
    correct = region == "below" and clear and abs(seen - f) <= tol(f)
    folds = clear and abs(seen - expect) <= tol(expect)
    if region == "edge":
        model_ok = True   # at half the reading rate the result depends on phase: no prediction
    else:
        amp_ok = (response is None or not ctx.get("judge_amplitude", True)
                  or abs(response - predicted) <= max(0.15, 0.25 * predicted))
        model_ok = folds and amp_ok
    if region == "edge":
        result = f"at the limit: reads {seen:.1f} Hz" if clear else "at the limit: no clear frequency"
    elif correct:
        result = "✓ correct frequency"
    elif folds and region != "below":
        result = f"folds to {seen:.1f} Hz (as predicted)"
    elif detected:
        result = "flicker seen, wrong frequency"
    else:
        result = "✗ not detected"
    return {"f": f, "seen": seen, "expect": expect, "prominence": prom, "swing": sw, "response": response,
            "predicted": predicted, "correct": correct, "folds": folds, "detected": detected,
            "model_ok": model_ok, "region": region, "result": result, "n": len(t)}


def analyse_flash(step, ctx):
    t, rgb = settled(step)
    x = rgb[:, ctx["channel"]]
    T, P, on = ctx["T"], 1.0 / step["freq"], step["on_us"] / 1e6
    base = float(np.median(x))
    noise = max(ctx["noise"], 1.4826 * float(np.median(np.abs(x - base))))  # most readings hold no flash
    C = ctx["contrast"]
    expected = C * on / T if C else None
    thr = base + max(0.35 * expected if expected else 0.0, 6 * noise)
    above = x > thr
    events, energies, i = 0, [], 0
    while i < len(x):
        if above[i]:
            j = i
            while j < len(x) and above[j]:
                j += 1
            events += 1
            energies.append(float((x[i:j] - base).sum()))
            i = j
        else:
            i += 1
    # flashes start at k·P after the step start; reading at time t covers [t - T, t]
    if len(t):
        k0, k1 = math.ceil((t[0] - T) / P), math.floor((t[-1] - on) / P)
        sent = max(0, k1 - k0 + 1)
    else:
        sent = 0
    caught = min(events, sent)
    energy = (float(np.median(energies)) / expected) if (energies and expected) else None
    return {"sent": sent, "caught": caught, "extra": max(0, events - sent), "energy": energy,
            "expected_bump": expected, "base": base}


# ---- Report -----------------------------------------------------------------------------------

def report(steps, n_steps, rng=None, ends=None, title="light-test", source="LED", judge_amplitude=True, notes=()):
    """Full report. Returns (lines, verdicts) where each verdict is (name, PASS|PARTIAL|FAIL, detail).
    source names the light source in messages; judge_amplitude=False judges folding by frequency only
    (for sources with soft edges, such as a screen)."""
    ends = ends or {}
    ctx = context(steps)
    ctx["judge_amplitude"] = judge_amplitude
    ch = CHANNELS[ctx["channel"]]
    L = [f"Modulino Light flicker test · {title}", ""]
    L.append("Setup")
    if rng:
        L.append(f"  sensor gain x{rng['gain_x']} (auto): LED on {rng['on']} counts, dark {rng['dark']} "
                 f"(brightest channel; full scale {FULL_SCALE})" + ("  SATURATED" if rng["saturated"] else ""))
    L.append(f"  reading rate {ctx['fs']:.2f}/s (nominal 40) → averaging window T ≈ {ctx['T'] * 1000:.1f} ms; "
             f"half the rate = {ctx['fs'] / 2:.1f} Hz" + (f"; {ctx['gaps']} missed readings" if ctx["gaps"] else ""))
    if ctx["levels"]:
        lv = ", ".join(f"{c} {d:.0f}→{s:.0f}" for c, (d, s) in ctx["levels"].items())
        L.append(f"  dark→{source} on: {lv}; analysed channel: {ch} (largest step, noise {ctx['noise']:.1f} counts)")
    elif ctx["contrast"]:
        L.append(f"  dark/steady steps missing: on-off step estimated from the slow square waves ({ch})")
    L += [f"  {n}" for n in notes]
    warnings = []
    if not ctx["seen"]:
        warnings.append(f"the sensor didn't see the {source} (on − off = {ctx['step_seen']:.0f} counts): "
                        + ("check the wiring (D3 → R2 → Q1, LED polarity) and that D1 faces the sensor"
                           if source == "LED" else "hold the sensor facing the screen"))
    elif ctx["contrast"] is not None and ctx["contrast"] < 1000:
        warnings.append(f"the {source} barely reaches the sensor (on-off step < 1000 counts)")
    if ctx["saturated"]:
        warnings.append(f"the steady {source} saturates the sensor: add paper in front of the sensor, or move it away")
    missing = [i for i in range(n_steps) if i not in steps]
    if missing:
        warnings.append(f"{len(missing)} of {n_steps} steps missed (Python started late): restart the app for a full run")
    darks = [i for i in sorted(steps) if steps[i]["kind"] == "dark" and len(settled(steps[i])[0])]
    if len(darks) >= 2 and ctx["contrast"]:
        d0 = settled(steps[darks[0]])[1][:, ctx["channel"]].mean()
        d1 = settled(steps[darks[-1]])[1][:, ctx["channel"]].mean()
        if abs(d1 - d0) > 0.05 * ctx["contrast"]:
            warnings.append(f"dark level drifted {d0:.0f} → {d1:.0f}: room light leaking into the tube?")
    for w in warnings:
        L.append(f"  [warn] {w}")

    sq = [(i, analyse_square(steps[i], ctx)) for i in sorted(steps) if steps[i]["kind"] == "square"
          and len(settled(steps[i])[0]) >= 16]
    L += ["", "Square waves (50% duty)",
          "   true    seen   expected  response  predicted  swing  edge-late  result"]
    for i, r in sq:
        late = ends.get(i, {}).get("late_us")
        late_s = f"{late / 1000:5.1f} ms" if late is not None else "     – "
        resp = f"{r['response']:6.2f}" if r["response"] is not None else "     –"
        sw = f"{r['swing'] * 100:4.0f}%" if r["swing"] is not None else "   –"
        exp = f"{r['expect']:5.1f}" + ("*" if r["region"] == "above" else (" ~" if r["region"] == "edge" else "  "))
        seen = f"{r['seen']:6.1f}" if r["prominence"] >= PROMINENCE_MIN else "     –"
        L.append(f"  {r['f']:5.1f}  {seen}   {exp}   {resp}     {r['predicted']:6.2f}   {sw}   {late_s}  {r['result']}")
    L.append("  * folded (above half the reading rate)   ~ at half the reading rate: phase-dependent, no prediction")
    L.append("  response = fundamental ÷ (2/π × on-off step); predicted = |sinc(f·T)|")

    fl = [(i, analyse_flash(steps[i], ctx)) for i in sorted(steps) if steps[i]["kind"] == "flash"
          and len(settled(steps[i])[0]) >= 16]
    if fl:
        L += ["", "Short flashes"]
        for i, r in fl:
            e = f", energy captured {r['energy'] * 100:.0f}% of predicted" if r["energy"] is not None else ""
            x = f", {r['extra']} extra events" if r["extra"] else ""
            L.append(f"  {describe(steps[i]):18s} caught {r['caught']}/{r['sent']}{e}{x}")

    # ---- verdicts
    verdicts = []
    by_f = {r["f"]: r for _, r in sq}
    if 10.0 in by_f:
        r10 = by_f[10.0]
        neighbours = [by_f[f]["correct"] for f in (9.0, 11.0) if f in by_f]
        detail = f"reads {r10['seen']:.1f} Hz" + (
            f", response {r10['response'] * 100:.0f}% vs {r10['predicted'] * 100:.0f}% predicted" if r10["response"] else "")
        if r10["correct"] and all(neighbours):
            verdicts.append(("10 Hz flicker", "PASS", detail + "; 9 and 11 Hz also correct"))
        elif r10["correct"]:
            verdicts.append(("10 Hz flicker", "PARTIAL", detail + "; a neighbouring rate was wrong"))
        else:
            verdicts.append(("10 Hz flicker", "FAIL", detail))
    # Band: the unbroken run of correct rates around 10 Hz (or the longest run if 10 Hz failed).
    below = sorted((r["f"], r["correct"]) for _, r in sq if r["region"] == "below")
    runs, cur = [], []
    for f, ok in below:
        if ok:
            cur.append(f)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    run = next((r for r in runs if 10.0 in r), max(runs, key=len) if runs else [])
    band_hi = run[-1] if run else None
    if below:
        band = f"{run[0]:g}–{run[-1]:g} Hz" if run else "none"
        if run and run[0] <= 3 and run[-1] >= 15:
            st = "PASS"
        elif 10.0 in run:
            st = "PARTIAL"
        else:
            st = "FAIL"
        verdicts.append(("correct-frequency band", st, f"{band}; expected about 1–15 Hz"))
    above = [r for _, r in sq if r["region"] == "above"]
    if above:
        ok = sum(r["model_ok"] for r in above)
        det = sum(r["detected"] for r in above)
        st = "PASS" if ok == len(above) else ("PARTIAL" if ok >= len(above) / 2 else "FAIL")
        verdicts.append(("above 20 Hz (folding model)", st,
                         f"detected {det}/{len(above)}, fold as predicted {ok}/{len(above)}"))
    if fl:
        worst = min(r["caught"] / r["sent"] if r["sent"] else 0 for _, r in fl)
        st = "PASS" if worst >= 0.9 else ("PARTIAL" if worst >= 0.5 else "FAIL")
        verdicts.append(("short flashes", st, ", ".join(f"{describe(steps[i])}: {r['caught']}/{r['sent']}" for i, r in fl)))
    main = [v for v in verdicts if v[0] in ("10 Hz flicker", "correct-frequency band")]
    if main:
        if all(v[1] == "PASS" for v in main):
            overall = "PASS"
        elif main[0][1] in ("PASS", "PARTIAL"):
            overall = "PARTIAL"
        else:
            overall = "FAIL"
        top = band_hi if band_hi else 0
        verdicts.append(("Modulino Light as the flicker sensor", overall,
                         f"frequency reliable up to {top:g} Hz, flicker detected up to "
                         f"{max([r['f'] for _, r in sq if r['detected']] or [0]):g} Hz"))
    if not ctx["seen"]:   # nothing to judge the sensor on
        verdicts = [("test setup", "FAIL", f"the sensor never saw the {source}; the Modulino Light was not tested")]
    L += ["", "Verdicts"] + [f"  VERDICT {n}: {s} ({d})" for n, s, d in verdicts]
    return L, verdicts


# ---- CSV (written by main.py) ------------------------------------------------------------------

CSV_HEADER = "run,step,kind,freq_hz,on_us,t_ms,red,green,blue"


def load_csv(path):
    steps = {}
    for line in Path(path).read_text().splitlines()[1:]:
        p = line.split(",")
        if len(p) != 9:
            continue
        idx = int(p[1])
        s = steps.setdefault(idx, {"kind": p[2], "freq": float(p[3]), "on_us": int(p[4]), "t": [], "rgb": []})
        s["t"].append(float(p[5]) / 1000)
        s["rgb"].append((int(p[6]), int(p[7]), int(p[8])))
    return steps


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: analysis.py <lighttest.*.csv>")
    st = load_csv(sys.argv[1])
    lines, _ = report(st, max(st) + 1 if st else 0, title=Path(sys.argv[1]).name)
    print("\n".join(lines))
