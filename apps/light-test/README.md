# Light Test

How well does the **Modulino Light** read flicker? The UNO Q flashes a test LED at known rates into
the sensor and compares what the sensor sees with the model in
[DI-01](../../docs/DESIGN_ISSUES.md#di-01-modulino-light-tops-out-at-40-samples-per-second):
- **about 40 readings/s:** frequencies above 20 Hz fold to a wrong, lower frequency;
- **each reading averages 25 ms of light:** fast flicker gets weaker by |sinc(f·25 ms)|, about 90% left
  at 10 Hz and 47% at 25 Hz.

Expected result: **10 Hz reads correctly**, frequencies are right up to about 15–18 Hz, 20 Hz is the
limit, and 25 / 30 / 35 Hz show up as about 15 / 10 / 5 Hz.

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
sensor's real reading rate, not the nominal 40/s.

## Reading the result

```
[step] 10 Hz square    seen  10.0 Hz (expected 10.0) · response  90% (predicted  90%) · swing 100% · ✓ correct frequency
[step] 25 Hz square    seen  14.6 Hz (expected 14.6) · response  46% (predicted  46%) · swing  58% · folds to 14.6 Hz (as predicted)
  VERDICT 10 Hz flicker: PASS (reads 10.0 Hz, response 90% vs 90% predicted; 9 and 11 Hz also correct)
  VERDICT correct-frequency band: PASS (1–18 Hz; expected about 1–15 Hz)
```

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

The analysis was checked on simulated runs: a sensor that follows the model exactly, one with dead
time between readings, Python joining late, and a sensor that smooths over 100 ms (all verdicts
FAIL, as they should). **It hasn't run on the real rig yet.**
