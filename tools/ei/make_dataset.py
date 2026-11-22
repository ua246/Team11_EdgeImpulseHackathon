#!/usr/bin/env python3
"""Team 11 · cut a flashguard recording made with tools/flicker.html → "Collect" into labelled
windows for Edge Impulse.

    UNOQ_APP=flashguard tools/unoq pull
    python3 tools/ei/make_dataset.py recordings/flashguard/flicker.<time>.csv
        → recordings/flashguard/dataset.<time>.json  (then tools/ei/ei.py upload <that file>)
    python3 tools/ei/make_dataset.py --check <csv>   exit 0 once the recording holds a complete session

Each window is features.WINDOW readings (~1.77 s), preprocessed exactly as on the board
(apps/flashguard/python/features.py), taken every STRIDE readings inside each labelled segment
(the edges are trimmed). Whole segments are held out for testing (every 5th segment of the schedule,
and the last 20% of the room-light minute), so overlapping windows never sit on both sides.
"""

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "apps" / "flashguard" / "python"))
import collect_schedule as cs  # noqa: E402
import features as ft  # noqa: E402

STRIDE = 18                      # readings between window starts (~0.5 s)
TRIM = {"default": (0.7, 0.3), "room": (3.0, 1.0)}   # seconds dropped at the start / end of a segment
SATURATED = 65000
MIN_FLICKER_SWING = 0.03         # flicker windows whose total brightness moves less than this are dropped:
                                 # too faint to count as flicker (room light can swamp a dim screen)


def load(path):
    rows = np.genfromtxt(path, delimiter=",", skip_header=1, invalid_raise=False)
    if rows.ndim != 2 or rows.shape[1] < 5:
        return None
    rows = rows[~np.isnan(rows).any(axis=1)]
    return rows[:, 0] / 1000.0, rows[:, 1:4], rows[:, 4]


def _lin(h):
    return (np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float) / 255) ** 2.2   # screen gamma


def expected_brightness(tl, step=0.1):
    """What the screen should look like to the sensor (sum of linear R, G, B), every `step` seconds
    from the start of the timeline; NaN where unknown (room light). Fast flicker counts as its mean."""
    t_start = tl[0]["t0"]
    total = tl[-1]["t0"] + tl[-1]["d"] - t_start
    tt = np.arange(0, total, step) + t_start
    out = np.full(len(tt), np.nan)
    for e in tl:
        m = (tt >= e["t0"]) & (tt < e["t0"] + e["d"])
        rel = tt[m] - e["t0"]
        on, off = _lin(e.get("on", "#ffffff")).sum(), _lin(e.get("off", "#000000")).sum()
        k = e["k"]
        if k == "white":
            out[m] = 3.0
        elif k == "black":
            out[m] = 0.0
        elif k == "flicker":
            out[m] = (on + off) / 2
        elif k == "blink":
            out[m] = np.where((rel * e["r"]) % 1 < 0.5, on, off)
        elif k == "steady":
            out[m] = on
        elif k == "fade":
            f = 0.5 - 0.5 * np.cos(2 * np.pi * e["r"] * rel)
            out[m] = off + (on - off) * f
        elif k == "steps":
            idx = np.searchsorted(np.array(e["times"]), rel, side="right") - 1
            out[m] = np.array([_lin(c).sum() for c in e["levels"]])[np.clip(idx, 0, None)]
    return tt, out


def find_sync(t, x, step=0.1):
    """Time of the sync edge (end of the white block), found by sliding the whole schedule's expected
    brightness along the measured brightness and taking the best correlation. Works when room light
    swamps the screen or contrast is low. Returns (time, correlation) or (None, best correlation)."""
    tl = cs.timeline()
    rel, exp = expected_brightness(tl, step)
    grid = np.arange(t[0], t[-1], step)
    meas = np.interp(grid, t, x)
    n = len(exp)
    if len(grid) < n:
        return None, 0.0
    valid = ~np.isnan(exp)
    e = exp[valid] - exp[valid].mean()
    e /= np.linalg.norm(e)
    best, best_i = -1.0, 0
    for i in range(0, len(grid) - n + 1):
        m = meas[i:i + n][valid]
        m = m - m.mean()
        nm = np.linalg.norm(m)
        if nm == 0:
            continue
        c = float(m @ e / nm)
        if c > best:
            best, best_i = c, i
    if best < 0.5:
        return None, best
    # rel[0] is the timeline start (sync black) relative to the sync edge; refine the edge locally
    edge = grid[best_i] - rel[0]
    win = (t > edge - 1.5) & (t < edge + 1.0)
    if win.sum() > 10:
        hi = np.median(x[(t > edge - 2.5) & (t < edge - 0.5)])
        lo = np.median(x[(t > edge + 0.5) & (t < edge + 1.5)])
        mid = (hi + lo) / 2
        tw, xw = t[win], x[win]
        cross = np.where((xw[:-1] >= mid) & (xw[1:] < mid))[0]
        if len(cross):
            j = cross[np.argmin(np.abs(tw[cross] - edge))]
            frac = (xw[j] - mid) / (xw[j] - xw[j + 1])
            edge = float(tw[j] + frac * (tw[j + 1] - tw[j]))
    return edge, best


def windows(t, rgb, gain, ts):
    tl = cs.timeline()
    out, skipped = [], {"gain change": 0, "gap": 0, "saturated": 0, "too faint (flicker)": 0}
    for e in tl:
        if e["label"] not in ("flicker", "no_flicker"):
            continue
        a_trim, b_trim = TRIM.get(e["k"], TRIM["default"])
        a, b = ts + e["t0"] + a_trim, ts + e["t0"] + e["d"] - b_trim
        idx = np.where((t >= a) & (t <= b))[0]
        seg = e.get("n", "room")
        for k, s in enumerate(range(0, len(idx) - ft.WINDOW + 1, STRIDE)):
            w = idx[s:s + ft.WINDOW]
            if np.ptp(gain[w]) > 0:
                skipped["gain change"] += 1
                continue
            if t[w[-1]] - t[w[0]] > ft.WINDOW * ft.INTERVAL_MS / 1000 * 1.3:
                skipped["gap"] += 1
                continue
            if rgb[w].max() >= SATURATED:
                skipped["saturated"] += 1
                continue
            if e["label"] == "flicker":
                b = (rgb[w] / gain[w][:, None]).sum(axis=1)
                hi = np.percentile(b, 98)
                if hi <= 0 or (hi - np.percentile(b, 2)) / hi < MIN_FLICKER_SWING:
                    skipped["too faint (flicker)"] += 1
                    continue
            if e["k"] == "room":
                test = t[w[0]] >= a + 0.8 * (b - a)
            else:
                test = e["n"] % 5 == 0
            out.append({"name": f"{e['label']}.s{seg}.w{k:02d}", "label": e["label"], "segment": seg,
                        "kind": e["k"], "category": "testing" if test else "training",
                        "values": ft.preprocess(rgb[w], gain[w]).round(5).tolist()})
    return out, skipped


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) != 1:
        sys.exit(__doc__)
    path = Path(args[0])
    data = load(path)
    if data is None or len(data[0]) < 100:
        print("not enough readings yet")
        return 1
    t, rgb, gain = data
    ts, corr = find_sync(t, (rgb / gain[:, None]).sum(axis=1))
    end = cs.timeline()[-1]
    if ts is None:
        print(f"no Collect session found (best match with the schedule: correlation {corr:.2f})")
        return 1
    complete = t[-1] >= ts + end["t0"]
    if check:
        print(f"sync at {ts:.2f} s (match {corr:.2f}); session {'complete' if complete else 'running'}")
        return 0 if complete else 1
    samples, skipped = windows(t, rgb, gain, ts)
    out = path.with_name(path.name.replace("flicker.", "dataset.").replace(".csv", ".json"))
    out.write_text(json.dumps({"interval_ms": ft.INTERVAL_MS, "axes": list(ft.AXES), "window": ft.WINDOW,
                               "source": path.name, "samples": samples}))
    print(f"sync at {ts:.2f} s in {path.name} (match with the schedule: {corr:.2f})"
          + ("" if complete else "  [warn] session incomplete"))
    for cat in ("training", "testing"):
        c = {lab: sum(1 for s in samples if s["category"] == cat and s["label"] == lab) for lab in ("flicker", "no_flicker")}
        print(f"  {cat:8s}: {c['flicker']:4d} flicker, {c['no_flicker']:4d} no_flicker windows")
    if any(skipped.values()):
        print("  skipped: " + ", ".join(f"{v} {k}" for k, v in skipped.items() if v))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
