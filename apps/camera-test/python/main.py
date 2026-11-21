"""Team 11 · camera-test · what can the Arduino USB Camera tell us about flashing light?

Setup: the detector-test rig (hardware/detector-test); only the test LED D1 is needed. Point the
camera at D1 from 10-30 cm, or at a white card that D1 lights. Camera on the UNO Q's USB hub.

Test algorithm (runs once when the app starts, then switches to a live readout)
  1. camera    find the USB camera, open it at 320x240 uncompressed (YUYV), ask for 30 fps
  2. controls  try manual exposure (auto exposure smooths flashes and adapts to them); check that
               exposure really changes brightness; turn off auto white balance; turn off the
               anti-flicker filter if v4l2-ctl is available
  3. timing    5 s of frames: real frame rate, jitter, dropped frames
  4. find LED  LED off 2 s, then on 2 s: which of the 8x6 zones see the LED (share of the view)
  5. sweep     LED square wave at 1-30 Hz, 4 s each. In the LED zones: frequency seen vs. drive
               frequency and vs. the alias the frame rate predicts; response; swing
  6. verdict   how far the camera can be trusted (half the frame rate), blind spots, whether
               exposure can be locked, whether it can measure how much of the view is flashing
Then a live readout once a second (fps, share of view flashing, frequency, swing, red) for testing
real sources: the flicker page, a phone strobe, a TV. Restart the app to re-run the test.
"""

import glob
import os
import shutil
import subprocess
import time
import traceback
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from arduino.app_utils import App, Bridge

RES = (320, 240)
FPS_REQ = 30
FOURCC = "YUYV"                    # uncompressed: no JPEG decoding (datasheet: YUY2 320x240 @ 30 fps)
GRID = (8, 6)                      # zones across, down: each frame becomes 48 brightness values
SWEEP_HZ = [1, 2, 3, 5, 8, 10, 12, 14, 18, 20, 25, 29, 30]
STEP_S = 4.0
EXPOSURE_FINAL = 50                # V4L2 exposure_time_absolute, UVC units of 100 µs -> 5 ms
EXPOSURE_CHECK = (200, 20)         # 20 ms vs 2 ms: does manual exposure change brightness?
ZONE_MIN_LEVELS = 10               # a zone "sees" a change if it moves by >= 10 grey levels
LIVE_WINDOW_S = 2.0

REC_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"
STAMP = time.strftime("%Y%m%d-%H%M%S")
LUMA = np.array([0.114, 0.587, 0.299], dtype=np.float32)   # OpenCV frames are BGR

CAP = None
FPS_EST = float(FPS_REQ)


def say(msg=""):
    print(f"[test] {msg}", flush=True)


# ---- test LED (sketch) ---------------------------------------------------------------------------

def led(period_us=0, on_us=0):
    Bridge.call("led", int(period_us), int(on_us), timeout=5)


def led_square(f_hz):
    period = round(1e6 / f_hz)
    led(period, period // 2)


# ---- camera ----------------------------------------------------------------------------------------

def find_camera():
    links = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))   # USB cameras have stable links
    if links:
        return links[0]
    for i in range(10):
        path = f"/dev/video{i}"
        if not os.path.exists(path):
            continue
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        ok = cap.isOpened() and cap.read()[0]
        cap.release()
        if ok:
            return path
    return None


def fourcc_str(v):
    v = int(v)
    return "".join(chr((v >> 8 * i) & 0xFF) for i in range(4))


def open_camera(path):
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RES[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RES[1])
    cap.set(cv2.CAP_PROP_FPS, FPS_REQ)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    return cap


def flush(cap, n):
    for _ in range(n):
        cap.read()


def grab(cap, seconds):
    """Frames for `seconds`, each reduced to a GRID of grey levels and red shares.

    Returns (timestamps in s, zones[N, rows, cols], red[N, rows, cols]). Uses the driver's frame
    timestamps when they are usable, otherwise the time each frame arrived.
    """
    t_dev, t_arr, zones, red = [], [], [], []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ok, frame = cap.read()
        if not ok or frame is None or frame.ndim != 3:
            continue
        t_arr.append(time.monotonic())
        t_dev.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        small = cv2.resize(frame, GRID, interpolation=cv2.INTER_AREA).astype(np.float32)
        zones.append(small @ LUMA)
        red.append(small[:, :, 2] / (small.sum(axis=2) + 1e-6))
    t = np.array(t_dev)
    if len(t) < 3 or not np.all(np.diff(t) > 0):
        t = np.array(t_arr)
    return t, np.array(zones), np.array(red)


def setup_controls(cap, path):
    """Try to lock a short exposure and switch off automatic corrections. Returns a dict."""
    out = {"manual": False, "works": False, "levels": {}, "ctrls": None}
    led(0, 1)                                         # LED steady on: a bright reference
    flush(cap, 10)
    for v in (1, 0.25):                               # V4L2 "manual"; some OpenCV builds use 0.25
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, v)
        if abs(cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) - v) < 0.01:
            out["manual"] = True
            break
    if out["manual"]:
        for e in EXPOSURE_CHECK:
            cap.set(cv2.CAP_PROP_EXPOSURE, e)
            flush(cap, 8)
            _, z, _ = grab(cap, 0.5)
            out["levels"][e] = float(z.mean()) if len(z) else 0.0
        long_e, short_e = EXPOSURE_CHECK
        out["works"] = out["levels"][long_e] > 1.5 * max(out["levels"][short_e], 1.0)
        cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_FINAL)
    cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    v4l2 = shutil.which("v4l2-ctl")
    if v4l2:
        try:
            subprocess.run([v4l2, "-d", path, "-c", "power_line_frequency=0"], capture_output=True, timeout=5)
            listing = subprocess.run([v4l2, "-d", path, "--list-ctrls"], capture_output=True, text=True,
                                     timeout=5).stdout
            out["ctrls"] = [line.strip() for line in listing.splitlines()
                            if any(k in line for k in ("exposure", "power_line", "white_balance", "gain"))]
        except (OSError, subprocess.SubprocessError):
            pass
    led(0, 0)
    flush(cap, 10)
    return out


# ---- analysis ----------------------------------------------------------------------------------------

def frame_timing(t):
    dt = np.diff(t)
    med = float(np.median(dt))
    return 1.0 / med, float(np.std(dt) * 1000), int(np.sum(dt > 1.5 * med))


def uniform(t, x):
    fs = 1.0 / float(np.median(np.diff(t)))
    tu = np.arange(t[0], t[-1], 1.0 / fs)
    return np.interp(tu, t, x), fs


def dominant(x, fs, fmin=0.3):
    y = np.asarray(x, dtype=float) - float(np.mean(x))
    nfft = 1 << (len(y) * 8 - 1).bit_length()
    spec = np.abs(np.fft.rfft(y, nfft))
    freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
    band = (freqs >= fmin) & (freqs <= fs / 2)
    i = int(np.argmax(spec[band]))
    return float(freqs[band][i]), float(2 * spec[band][i] / len(y))


def alias(f, fs):
    r = f % fs
    return min(r, fs - r)


def swing(x):
    lo, hi = np.percentile(x, [2, 98])
    return float(100.0 * (hi - lo) / hi) if hi > 0 else 0.0


def save_csv(name, header, rows):
    try:
        REC_DIR.mkdir(parents=True, exist_ok=True)
        with open(REC_DIR / f"camtest.{STAMP}.{name}.csv", "w") as f:
            f.write(header + "\n")
            f.writelines(",".join(str(v) for v in row) + "\n" for row in rows)
    except OSError as e:
        say(f"  ! could not save {name}: {e}")


# ---- the test ------------------------------------------------------------------------------------------

def run():
    global CAP, FPS_EST
    time.sleep(3)  # give the sketch time to start
    say("─" * 72)
    say("Camera test · Arduino USB Camera · LED test rig on D3")
    say("Setup: camera 10-30 cm from the test LED D1 (or a white card it lights), LED in view.")
    say("─" * 72)

    say("1/6 camera …")
    path = find_camera()
    if path is None:
        say("VERDICT camera: FAIL: no USB camera found")
        say("  → Plug the camera into the UNO Q's USB-C hub (a powered hub is best), then restart the app.")
        say("  → On the board shell, `ls /dev/v4l/by-id/` should list it.")
        return
    CAP = cap = open_camera(path)
    say(f"  {path}")
    say(f"  {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
        f"{fourcc_str(cap.get(cv2.CAP_PROP_FOURCC))}, driver reports {cap.get(cv2.CAP_PROP_FPS):.0f} fps")

    say("2/6 exposure and automatic corrections …")
    ctl = setup_controls(cap, path)
    if ctl["manual"]:
        lv = ctl["levels"]
        say(f"  manual exposure accepted; brightness at 20 ms vs 2 ms: {lv[EXPOSURE_CHECK[0]]:.0f} vs "
            f"{lv[EXPOSURE_CHECK[1]]:.0f} → {'works' if ctl['works'] else 'NO EFFECT'}; "
            f"now {EXPOSURE_FINAL / 10:.0f} ms")
    else:
        say("  manual exposure NOT accepted: auto exposure stays on (smooths and adapts to flashes)")
    if ctl["ctrls"] is not None:
        say("  v4l2-ctl: anti-flicker off; controls:")
        for line in ctl["ctrls"]:
            say(f"    {line}")
    else:
        say("  v4l2-ctl not available here; to inspect controls, on the board shell run:")
        say(f"    v4l2-ctl -d {path} --list-ctrls   (package v4l-utils)")

    say("3/6 frame timing (5 s) …")
    t_tim, _, _ = grab(cap, 5.0)
    if len(t_tim) < 10:
        say("VERDICT camera: FAIL: almost no frames received")
        return
    FPS_EST, jitter, drops = frame_timing(t_tim)
    say(f"  {FPS_EST:.1f} fps, jitter {jitter:.1f} ms, {drops} dropped of {len(t_tim)}")

    say("4/6 finding the LED …")
    led(0, 0)
    flush(cap, 10)
    _, z_off, _ = grab(cap, 2.0)
    led(0, 1)
    flush(cap, 10)
    _, z_on, r_on = grab(cap, 2.0)
    led(0, 0)
    diff = np.median(z_on, axis=0) - np.median(z_off, axis=0)
    noise = z_off.std(axis=0)
    mask = diff >= np.maximum(ZONE_MIN_LEVELS, 5 * noise)
    n_led = int(mask.sum())
    area = n_led / mask.size
    say(f"  LED seen in {n_led}/{mask.size} zones ({100 * area:.0f}% of the view):")
    for row in mask:
        say("    " + " ".join("#" if m else "·" for m in row))
    if n_led == 0:
        say("VERDICT camera: FAIL: the camera doesn't see the test LED")
        say("  → Aim at D1 (10-30 cm), remove the tube, or point it at a white card lit by D1.")
        say("  → If exposure didn't lock, auto exposure may have hidden the LED: check step 2.")
        return
    contrast = float(diff[mask].mean())
    say(f"  contrast {contrast:.0f} grey levels; red share of LED zones {100 * float(r_on[:, mask].mean()):.0f}%")

    say(f"5/6 flicker sweep {SWEEP_HZ[0]}-{SWEEP_HZ[-1]} Hz, {STEP_S:.0f} s each …")
    rows = []
    for f in SWEEP_HZ:
        led_square(f)
        flush(cap, 5)
        t, z, _ = grab(cap, STEP_S)
        x = z[:, mask].mean(axis=1)
        save_csv(f"sweep_{f}hz", "timestamp,led_zones_grey", zip(np.round(t - t[0], 4), np.round(x, 2)))
        xu, fs = uniform(t, x)
        seen, amp = dominant(xu, fs)
        expect = alias(f, fs)
        resp = amp / (2 * contrast / np.pi)
        sw = swing(xu)
        if f < fs / 2 - 0.5:
            status = "correct" if abs(seen - f) <= 0.5 else "WRONG"
        elif expect < 0.5:
            status = "invisible (blind spot)" if sw < 10 else f"seen as ~{seen:.1f} Hz near a blind spot"
        else:
            status = (f"looks like {expect:.1f} Hz (alias, as predicted)" if abs(seen - expect) <= 0.5
                      else "aliased, not as predicted")
        rows.append((f, seen, expect, resp, sw, status))
    led(0, 0)
    save_csv("results", "f_drive_hz,f_seen_hz,f_alias_expected_hz,response_pct,swing_pct,status",
             [(f, f"{s:.2f}", f"{e:.2f}", f"{100 * r:.1f}", f"{w:.1f}", st) for f, s, e, r, w, st in rows])

    say("6/6 results")
    say("  drive    seen    response  swing   status")
    for f, seen, expect, resp, sw, status in rows:
        say(f"  {f:4.0f} Hz {seen:5.1f} Hz  {100 * resp:5.0f} %  {sw:4.0f} %   {status}")

    reliable = [f for f, seen, _, resp, _, st in rows if st == "correct" and resp >= 0.3]
    limit = max(reliable) if reliable else 0
    missed = [f for f, *_, sw, st in rows if sw < 10]
    say("─" * 72)
    say(f"Frequency: correct up to {limit} Hz (half the frame rate is {FPS_EST / 2:.1f} Hz). Faster flicker "
        f"shows up at the wrong frequency.")
    say(f"Flicker missed entirely at: {', '.join(f'{f} Hz' for f in missed) if missed else 'none of the tested rates'}")
    if FPS_EST >= 25 and limit >= 10 and ctl["works"]:
        verdict = "PASS"
        summary = ("usable as a context sensor (how much of the view is flashing, colour); "
                   "use the fast detector for frequency")
    elif FPS_EST >= 15 and limit >= 5:
        verdict = "PARTIAL"
        summary = "sees flashing, but " + ("exposure can't be locked" if not ctl["works"] else "frequency range is small")
    else:
        verdict = "FAIL"
        summary = "frame rate or response too low to be useful"
    say(f"VERDICT camera: {verdict}: {summary}")
    if not ctl["works"]:
        say("  → Without a fixed short exposure, the camera averages and adapts to flashes. Check the "
            "exposure controls with v4l2-ctl on the board shell.")
    if drops > len(t_tim) * 0.05:
        say("  → Many dropped frames: use a powered USB hub and keep the resolution at 320x240.")
    say(f"Raw signals + results: {REC_DIR}/camtest.{STAMP}.* · copy with: UNOQ_APP=camera-test tools/unoq pull")
    say("Live readout starts now. Point the camera at a flicker source.")


# ---- live readout -------------------------------------------------------------------------------------------

_buf = deque()


def live_step():
    t, z, r = grab(CAP, 1.0)
    for i in range(len(t)):
        _buf.append((t[i], z[i], r[i]))
    while _buf and _buf[-1][0] - _buf[0][0] > LIVE_WINDOW_S:
        _buf.popleft()
    if len(_buf) < 10:
        print("[cam] waiting for frames …", flush=True)
        return
    T = np.array([b[0] for b in _buf])
    Z = np.array([b[1] for b in _buf])
    R = np.array([b[2] for b in _buf])
    fps = 1.0 / float(np.median(np.diff(T)))
    lo, hi = np.percentile(Z, [2, 98], axis=0)
    flashing = ((hi - lo) >= ZONE_MIN_LEVELS) & ((hi - lo) / np.maximum(hi, 1) >= 0.10)
    n = int(flashing.sum())
    if n == 0:
        print(f"[cam] {fps:4.1f} fps │ no flashing", flush=True)
        return
    xu, fs = uniform(T, Z[:, flashing].mean(axis=1))
    f, _ = dominant(xu, fs)
    print(f"[cam] {fps:4.1f} fps │ flashing {100 * n / flashing.size:3.0f}% of view ({n}/{flashing.size} zones) │ "
          f"~{f:4.1f} Hz (reliable ≤ {fps / 2:.0f} Hz) │ swing {swing(xu):3.0f}% │ "
          f"red {100 * float(R[:, flashing].mean()):3.0f}%", flush=True)


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
            try:
                led(0, 0)
            except Exception:
                pass
        return
    if CAP is None:
        time.sleep(1)
        return
    live_step()


App.run(user_loop=loop)
