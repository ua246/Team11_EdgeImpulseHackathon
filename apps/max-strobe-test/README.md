# MAX30102 Strobe Test

Can the MAX30102/MAX30105 heart-rate sensor detect strobe or flicker light?

The chip cancels ambient light by design: every sample is LED-on minus LED-off, a fraction of a
millisecond apart. This test measures how much flicker still gets through, and whether the chip's
**ambient-light overflow** flag (ALC_OVF) trips.

- **Sketch:** single-LED (HR) mode at **400 samples/s**, so flicker up to 200 Hz is visible in
  principle. The red LED alternates **on and off every 2 s**, so both cases are recorded under the
  same flicker. ALC_OVF events are counted. The sketch looks for the sensor on `Wire2` (A4/A5),
  `Wire1` (Qwiic) and `Wire`.
- **Python:** records every sample to `data/recordings/strobe.<time>.csv` and prints a status line
  once a second.
- **Analysis (laptop):** `analyze.py <csv> <steps.json>`. For each step and LED state it compares
  the amplitude at the flicker frequency with a no-flicker baseline: **SNR ≥ 5** plus the strongest
  frequency within 1 Hz of the flicker counts as detected. It was checked on synthetic data: a leak
  of 1.6× the noise is detected; no leak gives 0 of 5.

## Run

```sh
UNOQ_APP=max-strobe-test tools/unoq dev     # needs board package 1.1.0 on the laptop (flash from laptop, DI-20)
```

1. Hold the sensor's window 1–3 cm from the screen running `tools/flicker.html`.
2. Record a baseline with no flashing, then 5 / 10 / 18 / 25 Hz white and 10 Hz red, about 10 s
   each. Note the CSV row range of each step in `steps.json`.

## Result (2026-11-21)

`recordings/max-strobe-test/strobe.20251210-182451.*`, laptop screen:
- **Flicker detected in 0 of 5 steps, with the LED on and with it off.** SNR 0.5–2.2.
- **Signal level was unchanged** by the flashing (LED on ≈600, LED off ≈40).
- **ALC overflow: 0 events.**

The ambient-light cancellation removes screen flicker completely, so **this sensor is not a flicker
detector**. Use a bare phototransistor or photodiode for that (DI-01 option A, Q2/R4 in the test
rig). Untested: whether a bright real strobe at close range trips the overflow flag. Even if it did,
that only says "very bright light", not the flash rate.
