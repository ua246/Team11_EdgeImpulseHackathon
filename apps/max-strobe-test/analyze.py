#!/usr/bin/env python3
"""Analyse a max-strobe-test recording (runs on the laptop; needs numpy).

    python3 apps/max-strobe-test/analyze.py recordings/max-strobe-test/strobe.<time>.csv steps.json

steps.json lists the test steps by CSV row range, for example:
    [{"label": "baseline", "hz": 0, "start": 1200, "end": 5200},
     {"label": "5 Hz white", "hz": 5, "start": 6400, "end": 10400}, ...]

For every step and LED state (the sensor's own LED on / off), it reports:
  level and swing      median value and 2-98 % spread
  strongest            the strongest frequency between 2 and 100 Hz
  at flicker           amplitude at the step's flicker frequency (±0.6 Hz)
  SNR                  that amplitude divided by the baseline's amplitude at the same frequency
  ALC overflow         how often the chip's ambient-light-overflow flag tripped
A flicker rate counts as DETECTED when SNR >= 5 and the strongest frequency is within 1 Hz of it.
"""
import json
import sys

import numpy as np

FS = 400.0          # samples per second (set in the sketch)
SKIP = 40           # samples dropped after each LED switch (0.1 s settling)
NFFT = 4096


def load(path):
    data = np.genfromtxt(path, delimiter=",", names=True)
    return data["led"].astype(int), data["alc_ovf"].astype(int), data["value"].astype(float)


def segments(led, lo, hi):
    """Contiguous same-LED-state runs inside rows [lo, hi), minus the settling samples."""
    out, start = [], lo
    for i in range(lo + 1, hi + 1):
        if i == hi or led[i] != led[start]:
            if i - start - SKIP >= 200:
                out.append((start + SKIP, i, int(led[start])))
            start = i
    return out


def spectrum(x):
    y = x - np.polyval(np.polyfit(np.arange(len(x)), x, 1), np.arange(len(x)))   # remove level + drift
    w = np.hanning(len(y))
    return np.abs(np.fft.rfft(y * w, NFFT)) * 2 / w.sum()                         # amplitude spectrum


FREQS = np.fft.rfftfreq(NFFT, 1 / FS)


def amp_at(spec, f):
    return float(spec[np.abs(FREQS - f) <= 0.6].max())


def analyse(path, steps):
    led, ovf, val = load(path)
    results = {}
    for st in steps:
        for state in (1, 0):
            segs = [s for s in segments(led, st["start"], st["end"]) if s[2] == state]
            if not segs:
                continue
            spec = np.mean([spectrum(val[a:b]) for a, b, _ in segs], axis=0)
            x = np.concatenate([val[a:b] for a, b, _ in segs])
            band = (FREQS >= 2) & (FREQS <= 100)
            results[(st["label"], state)] = {
                "hz": st["hz"], "spec": spec, "level": float(np.median(x)),
                "swing": float(np.percentile(x, 98) - np.percentile(x, 2)),
                "strongest": float(FREQS[band][np.argmax(spec[band])]),
                "ovf": int(sum(ovf[a:b].sum() for a, b, _ in segs)), "seconds": len(x) / FS,
            }
    base = {state: results.get((steps[0]["label"], state)) for state in (1, 0)}
    print(f"{'step':<14} {'LED':<4} {'level':>8} {'swing':>7} {'strongest':>10} {'at flicker':>11} {'SNR':>7} "
          f"{'ALC ovf':>8}  result")
    detected = {1: [], 0: []}
    for st in steps:
        for state in (1, 0):
            r = results.get((st["label"], state))
            if r is None:
                continue
            f = st["hz"]
            if f > 0 and base[state] is not None:
                a = amp_at(r["spec"], f)
                snr = a / max(amp_at(base[state]["spec"], f), 1e-9)
                hit = snr >= 5 and abs(r["strongest"] - f) <= 1
                if hit:
                    detected[state].append(f)
                res, at, snr_s = ("DETECTED" if hit else "not seen"), f"{a:11.1f}", f"{snr:7.1f}"
            else:
                res, at, snr_s = "(reference)", f"{'—':>11}", f"{'—':>7}"
            print(f"{st['label']:<14} {'on' if state else 'off':<4} {r['level']:8.0f} {r['swing']:7.0f} "
                  f"{r['strongest']:8.1f}Hz {at} {snr_s} {r['ovf']:8d}  {res}")
    flicker_steps = [s for s in steps if s["hz"] > 0]
    for state in (1, 0):
        print(f"LED {'on ' if state else 'off'}: flicker detected in {len(detected[state])}/{len(flicker_steps)} steps"
              + (f" ({', '.join(f'{f:g} Hz' for f in detected[state])})" if detected[state] else ""))
    return detected


if __name__ == "__main__":
    analyse(sys.argv[1], json.load(open(sys.argv[2])))
