"""Team 11 · light-test · analyse a screen sweep (laptop).

tools/flicker.html → "Sweep (automatic)" shows: 3 s black, 3 s white (sync), 2 s black, then each
rate in RATES for 6 s with 1.5 s black gaps, then 3 s white and 2 s black. light-test records the
sensor's readings in live mode (data/recordings/lighttest.<time>.live.csv). This script finds the
sync block in that file, cuts out each rate and runs the same analysis as the LED test:

    tools/unoq pull      (UNOQ_APP=light-test)
    python3 apps/light-test/python/screen_sweep.py recordings/light-test/lighttest.<time>.live.csv

--check only reports whether a complete sweep is in the file (exit code 0 = yes).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis as an  # noqa: E402

# Keep in sync with SWEEP in tools/flicker.html.
INTRO_BLACK, SYNC_WHITE, AFTER_SYNC = 3.0, 3.0, 2.0
RATES = [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 15, 18, 20, 25, 30]
STEP_ON, STEP_GAP = 6.0, 1.5
END_WHITE, END_BLACK = 3.0, 2.0
TRIM = 0.25                       # seconds dropped at the end of each window (timing margin)
SWEEP_AFTER_SYNC = AFTER_SYNC + len(RATES) * (STEP_ON + STEP_GAP) + END_WHITE + END_BLACK


def load_segments(path):
    """(t, rgb) pieces of the file; the time base restarts when the sketch starts a new phase."""
    try:
        rows = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    except ValueError:             # a half-written last line while the board is still recording
        rows = np.genfromtxt(path, delimiter=",", skip_header=1, invalid_raise=False)
        rows = rows[~np.isnan(rows).any(1)] if rows.ndim == 2 else np.empty((0, 4))
    if rows.ndim != 2 or rows.shape[0] < 50 or rows.shape[1] < 4:
        return []
    t, rgb = rows[:, 0] / 1000.0, rows[:, 1:4]
    cuts = np.where(np.diff(t) < 0)[0] + 1
    return [(t[a:b], rgb[a:b]) for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(t)]) if b - a > 50]


def find_syncs(t, x):
    """Times of the white → black edge at the end of each sync block: a 2.4-3.6 s bright run
    with at least 2.5 s of dark before it (the end marker has only 1.5 s, after flicker)."""
    lo, hi = np.percentile(x, 2), np.percentile(x, 99.5)
    if hi - lo < 50:
        return []
    mid, dark_thr = lo + 0.5 * (hi - lo), lo + 0.25 * (hi - lo)
    bright = x > mid
    syncs, i, n = [], 0, len(x)
    while i < n:
        if not bright[i]:
            i += 1
            continue
        j = i
        while j < n and bright[j]:
            j += 1
        if j < n and 2.4 <= t[j - 1] - t[i] <= 3.6:
            pre = (t >= t[i] - 2.5) & (t < t[i] - 0.1)
            if pre.sum() > 20 and (x[pre] < dark_thr).mean() > 0.95:
                # interpolate the crossing of the halfway level between the last bright and first dark reading
                a, b = x[j - 1], x[j]
                frac = (a - mid) / (a - b) if a != b else 0.5
                syncs.append(float(t[j - 1] + frac * (t[j] - t[j - 1])))
        i = j
    return syncs


def window(t, rgb, start, length):
    keep = (t >= start) & (t < start + length - TRIM)
    return {"t": list(t[keep] - start), "rgb": [tuple(v) for v in rgb[keep]]}


def build_steps(t, rgb, ts):
    """Steps in the format analysis.report() expects, for the sweep whose sync edge is at ts."""
    steps = {}
    steps[0] = dict(kind="dark", freq=0.0, on_us=0, **window(t, rgb, ts - SYNC_WHITE - INTRO_BLACK, INTRO_BLACK))
    steps[1] = dict(kind="steady", freq=0.0, on_us=0, **window(t, rgb, ts - SYNC_WHITE, SYNC_WHITE))
    for k, f in enumerate(RATES):
        start = ts + AFTER_SYNC + k * (STEP_ON + STEP_GAP)
        steps[2 + k] = dict(kind="square", freq=float(f), on_us=int(5e5 / f), **window(t, rgb, start, STEP_ON))
    end_black = ts + SWEEP_AFTER_SYNC - END_BLACK
    steps[2 + len(RATES)] = dict(kind="dark", freq=0.0, on_us=0, **window(t, rgb, end_black, END_BLACK))
    return {i: s for i, s in steps.items() if len(s["t"]) >= 20}


def sweeps(path):
    out = []
    for t, rgb in load_segments(path):
        x = rgb.max(1)
        for ts in find_syncs(t, x):
            complete = t[-1] >= ts + SWEEP_AFTER_SYNC - END_BLACK + 1.0
            out.append((t, rgb, ts, complete))
    return out


def main(argv):
    check = "--check" in argv
    args = [a for a in argv if a != "--check"]
    if len(args) != 1:
        sys.exit(__doc__)
    path = Path(args[0])
    found = sweeps(path)
    if check:
        done = [s for s in found if s[3]]
        print(f"{len(found)} sweep(s) found, {len(done)} complete")
        return 0 if done else 1
    if not found:
        print("No sweep found: no 3 s white block after ≥ 2.5 s of dark. Was the sensor facing the screen "
              "when the sweep started?")
        return 1
    t, rgb, ts, complete = found[-1]
    if len(found) > 1:
        print(f"({len(found)} sweeps in the file; analysing the last one)")
    steps = build_steps(t, rgb, ts)
    n = 3 + len(RATES)
    notes = ["light source: laptop screen via tools/flicker.html (about 60 frames/s). 8, 9, 11, 18 and 25 Hz",
             "  can't be shown evenly at 60 frames/s (the average rate is exact), and pixel transitions",
             "  soften the edges, so the response is judged only for information, not for the verdicts."]
    if not complete:
        notes.append("[warn] the recording ends before the sweep finished: later rates are missing")
    lines, verdicts = an.report(steps, n, title=f"screen sweep · {path.name}", source="screen",
                                judge_amplitude=False, notes=notes)
    print("\n".join(lines))
    out = path.with_name(path.name.replace(".live.csv", "") + ".screen.report.txt")
    out.write_text("\n".join(lines) + "\n")
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
