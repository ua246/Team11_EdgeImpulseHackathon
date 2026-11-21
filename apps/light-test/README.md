# Light Test

How well does the **Modulino Light** read flicker? Flicker at known rates is shown to the sensor,
either from a test LED driven by the UNO Q or from the laptop screen, and what the sensor sees is
compared with the model in
[DI-01](../../docs/DESIGN_ISSUES.md#di-01-modulino-light-takes-only-about-36-readings-per-second):
- **about 36 readings/s (measured; nominally 40):** frequencies above about 18 Hz fold to a wrong,
  lower frequency;
- **each reading averages one reading period of light (~27.6 ms):** fast flicker gets weaker by
  |sinc(f·T)|, with about 88% left at 10 Hz and 38% at 25 Hz.

Expected (and measured with the screen): **10 Hz reads correctly**, frequencies are right from 1 to
15 Hz, about 18 Hz is the limit, and 20 / 25 / 30 Hz show up as about 16 / 11 / 6 Hz.

## Results (2026-11-21)

| Run | Result |
|---|---|
| LED rig | Not run yet. The first attempt had no LED connected; the report now says "test setup: FAIL" for that case |
| Screen sweep | **PASS:** 10 Hz reads 10.0 Hz (9 and 11 Hz too); correct band 1–15 Hz; 20 and 30 Hz fold to 16.3 and 6.3 Hz as predicted. 18 and 25 Hz read 6 and 5 Hz: screen artefacts, because a 60 Hz screen can't show them evenly (DI-01) |

Measured reading rate 36.1–36.3/s. Strength at 10 Hz was 76% against 88% predicted, partly due to
the screen's pixel transitions. Report: `recordings/light-test/lighttest.20251210-192133.screen.report.txt`
(git-ignored; the board's clock is unsynced).

## Setup

Build the rig in [`hardware/light-test`](../../hardware/light-test/):
- the Modulino Light on the Qwiic connector;
- a white LED on D3 through an NPN transistor, facing the sensor's window from 1–3 cm away;
- both inside a black tube or box.

The LED flashes at seizure-provoking rates, so keep it covered (DI-12).

```sh
UNOQ_APP=light-test tools/unoq dev      # flashes the sketch from the laptop (board package 1.1.0, DI-20)
```

The sketch runs the whole sweep by itself, starting 6 s after it boots, and takes about 2.5 min.
It only sends MCU → Python messages, which is the direction proven on our board. Python prints a
line per step, then the report.

## Screen test (no LED needed)

After the LED sweep the app stays in live mode and saves every reading to
`data/recordings/lighttest.<time>.live.csv`. The laptop screen can then be the light source:

1. Start the app (`UNOQ_APP=light-test tools/unoq dev`), or, if it's already running, restart only
   the Python side: `UNOQ_APP=light-test UNOQ_NO_SKETCH=1 tools/unoq restart`.
2. Open `tools/flicker.html`, set the screen to full brightness, hold the Modulino Light 2–5 cm from
   the middle of the screen facing it, and click **Sweep (automatic)**. It takes about 2 min:
   - 3 s black, a 3 s white sync block and 2 s black;
   - then 1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 15, 18, 20, 25 and 30 Hz, 6 s each with 1.5 s black gaps.
3. Run `UNOQ_APP=light-test tools/unoq pull`, then
   `python3 apps/light-test/python/screen_sweep.py recordings/light-test/lighttest.<time>.live.csv`.

The script finds the sync block, cuts out each rate and runs the same analysis and verdicts. A
screen's edges are soft and some rates can't be shown evenly at 60 frames/s (8, 9, 11, 18, 25 Hz).
So the response is shown for information only, and folding is judged by frequency alone. There are
no short-flash steps, because one frame (16.7 ms) is the shortest flash a screen can show.
`screen_sweep.py --check <file>` exits 0 once a complete sweep is in the file.

## What the sketch does

1. **Picks the sensor gain:** the highest gain where the steady LED stays below 45% of full scale.
2. **Dark (3 s) and steady LED (3 s):** gives the on-off step and the noise.
3. **Square waves, 6.5 s each:** 1, 2, 3, 5, 6, 8, 9, **10**, 11, 12, 14, 15, 16, 18, 20, 22, 25, 30
   and 35 Hz.
4. **Short flashes, 3 per second:** 5 ms and 1 ms. Since every reading integrates 25 ms of light, none
   should be missed (DI-18).
5. **Dark again:** checks for light leaking into the tube.
6. **Live mode:** LED off, readings keep streaming. Python prints `[live]` lines with the swing and
   frequency, for manual checks with `tools/flicker.html`.

LED edges are timed from absolute time. A slow Bridge send can only delay one edge, never shift
the rate. Batches are sent right after an edge, and the worst lateness per step is reported (a
`[warn]` appears above 2 ms). Every reading carries its MCU timestamp, so the analysis uses the
sensor's real reading rate, not the nominal 40/s (it measured about 36/s).

## Reading the result

```
[step] 10 Hz square    seen  10.0 Hz (expected 10.0) · response  76% (predicted  88%) · swing  94% · ✓ correct frequency
[step] 20 Hz square    seen  16.3 Hz (expected 16.3) · response  27% (predicted  57%) · swing  34% · folds to 16.3 Hz (as predicted)
  VERDICT 10 Hz flicker: PASS (reads 10.0 Hz, response 76% vs 88% predicted; 9 and 11 Hz also correct)
  VERDICT correct-frequency band: PASS (1–15 Hz; expected about 1–15 Hz)
```
(From the screen sweep on our board.)

- **seen / expected:** the strongest frequency in the readings, and where the model says it should
  be (the true rate, or its alias above half the reading rate, marked `*`).
- **response / predicted:** the strength of the fundamental compared with an ideal on-off square
  wave (2/π of the on-off step), against |sinc(f·T)|.
- **swing:** the brightness range compared with the on-off step. Below 10% doesn't count as flicker.

**Verdicts:**

| Verdict | PASS | PARTIAL | FAIL |
|---|---|---|---|
| **10 Hz flicker** | 9, 10 and 11 Hz all correct | only 10 Hz correct | 10 Hz wrong |
| **Correct-frequency band** | unbroken from ≤3 Hz to ≥15 Hz | includes 10 Hz | doesn't include 10 Hz |
| **Above 20 Hz** | every step folds where predicted | at least half do | fewer |
| **Short flashes** | ≥90% of flashes caught | ≥50% | fewer |

The overall verdict is PASS when the first two pass. Rates at exactly half the reading rate (`~`,
20 Hz) depend on the phase and are reported but not judged.

The report and every reading are saved on the board in `data/recordings/` as
`lighttest.<time>.report.txt` and `lighttest.<time>.csv`. Copy them with `tools/unoq pull` (they
land in `recordings/light-test/`), then re-analyse on the laptop (needs numpy):

```sh
python3 apps/light-test/python/analysis.py recordings/light-test/lighttest.<time>.csv
```

## Troubleshooting

- **`SATURATED` / "steady LED saturates":** put a sheet of paper between the LED and the sensor, or
  move the LED away.
- **"LED barely reaches the sensor":** D1 isn't facing the window, or Q1's pins are swapped.
- **"N steps missed":** Python started after the sweep had begun. It asks the sketch for a new run;
  if that fails (Python → MCU calls are unproven on our board), run `tools/unoq restart`.
- **"dark level drifted":** room light is getting into the tube.
- **No data:** when flashing from the laptop, the sketch starts about 20 s after Python. Otherwise
  check the Qwiic cable and run `tools/unoq flash`.

## Tested

- **Simulated LED runs:** a sensor that follows the model exactly, one with dead time between
  readings, Python joining late, and a sensor that smooths over 100 ms (all verdicts FAIL, as they
  should).
- **Simulated screen sweep:** 60 frames/s, frame jitter and slow pixels.
- **On the board:** the full pipeline (sketch, Bridge, analysis, saved report) and the screen sweep
  above. The LED rig run is still to do.
