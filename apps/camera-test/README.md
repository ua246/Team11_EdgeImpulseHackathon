# Camera Test

Finds out what the **Arduino USB Camera** can tell us about flashing light on the UNO Q:
- its real frame rate;
- whether exposure can be locked;
- how far it reads flicker frequency correctly;
- where its blind spots are;
- whether it can measure **how much of the view** is flashing, and in what colour.

After the test it switches to a **live readout** for real sources.

Expected result from the datasheet: the camera tops out at **30 fps**, so it can only read flicker
up to about **15 Hz** correctly. Faster flicker shows up at a wrong, lower frequency, and flicker
near 30 Hz can vanish. The test measures this on your actual hardware. It also decides whether the
camera is worth using as a *context* sensor next to the fast light detector (DI-16).

## Setup

- **Camera:** plugged into the UNO Q's USB-C hub. A powered hub is best; the camera draws 250 mA.
  Keep its ring light **off**.
- **Test LED:** the test LED D1 from the [detector test rig](../../hardware/detector-test/)
  (D3 → R2 → Q1 → D1). Point the camera at D1 from 10–30 cm with the tube removed, or at a white
  card that D1 lights.

> **Safety:** the LED flashes at 1–30 Hz. Keep it shielded from people nearby, and keep anyone
> photosensitive away.

## Run it

```sh
UNOQ_APP=camera-test tools/unoq dev       # push, start, show the output
```

- **Timing:** the test takes about 1.5 minutes, then the live readout starts.
- **Run it again:** `UNOQ_APP=camera-test tools/unoq restart`.
- **Save the files:** `UNOQ_APP=camera-test tools/unoq pull` copies the raw signals and results to
  `recordings/camera-test/`.

## The test algorithm

| Step | What happens | Reports |
|---|---|---|
| 1 camera | Finds the USB camera (`/dev/v4l/by-id/*-video-index0`) and opens it with OpenCV at 320×240 uncompressed YUYV, asking for 30 fps | Device, format, the frame rate the driver claims |
| 2 controls | Test LED on. Tries manual exposure, compares brightness at 20 ms vs 2 ms, then sets **5 ms**. Turns off auto white balance. If `v4l2-ctl` exists, turns off the anti-flicker filter and lists the controls | Whether exposure can be locked |
| 3 timing | 5 s of frames, using the driver's frame timestamps when available | Real fps, jitter, dropped frames |
| 4 find LED | LED off 2 s, then on 2 s. Each frame is shrunk to an **8×6 grid** of brightness values. Zones that brighten by ≥ 10 grey levels (and 5× noise) see the LED | Zone map, share of view, contrast, red share |
| 5 sweep | LED square wave at 1, 2, 3, 5, 8, 10, 12, 14, 18, 20, 25, 29, 30 Hz, 4 s each. The LED zones' brightness is resampled evenly and the strongest frequency picked | Frequency seen, the **false frequency predicted** from the frame rate, response vs. a perfect sensor, swing, status |
| 6 verdict | – | Frequency limit, blind spots, PASS / PARTIAL / FAIL |

**Status column:**
- `correct`: below half the frame rate and read within ±0.5 Hz.
- `looks like X Hz (alias, as predicted)`: above half the frame rate. The camera reports the wrong
  frequency X, exactly as the frame rate predicts.
- `invisible (blind spot)`: near a multiple of the frame rate, the flicker almost disappears.

**Verdicts:**

| Verdict | Rule | Meaning |
|---|---|---|
| **PASS** | ≥ 25 fps, frequency correct up to ≥ 10 Hz, exposure lockable | Usable as a *context* sensor: how much of the view is flashing, and colour. Frequency comes from the fast detector |
| **PARTIAL** | ≥ 15 fps and correct up to ≥ 5 Hz | Sees flashing, but exposure can't be locked (it smooths and adapts to flashes) or the range is small |
| **FAIL** | Otherwise, or no camera, or LED not seen | Follow the hints |

## Live readout

After the test, once a second (the test LED is off now):

```
[cam] 30.0 fps │ flashing  25% of view (12/48 zones) │ ~ 7.0 Hz (reliable ≤ 15 Hz) │ swing  60% │ red  49%
```

- **Flashing zones:** over the last 2 s, a zone counts as flashing if it swings by ≥ 10 grey levels
  and ≥ 10%.
- **Frequency, swing, red:** worked out over the flashing zones only.

Use this for the flicker page on a laptop or TV, a phone strobe, or room lights. Images are never
stored; each frame is reduced to 48 numbers straight away.

The live readout also runs if step 4 fails because there's no LED rig: camera only, real sources.

## Status

- **Sketch:** compiles for the UNO Q.
- **Python side:** dry-run on a laptop with a simulated 29.97 fps camera that blurs over its
  exposure time:

  | Simulated case | Result |
  |---|---|
  | Exposure locked | 1–14 Hz correct; 18/20/25/29 Hz showed up as 12/10/5/1 Hz, exactly as predicted; 30 Hz flagged near a blind spot; **PASS** |
  | Exposure can't be locked | Response fell from 85% (10 Hz) to 17% (25 Hz); 29–30 Hz missed entirely; **PARTIAL** with the exposure hint |
  | Live readout | A red 7 Hz source covering a quarter of the view read as 25% / 7 Hz / red 49% |

- **Not yet run on the real board and camera.**
