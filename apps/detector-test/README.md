# Detector Test

Answers one question: **can the heart beat module's light detector measure flicker?** It also
tells you which input to use (A2 raw, or A3 after the R1/C1 filter).

The UNO Q flashes a white test LED into the detector at known rates and records what the detector
reports, 1000 times a second. It then grades the result: **PASS / PARTIAL / FAIL**, with hints.

## Wiring

Schematic: [`hardware/detector-test`](../../hardware/detector-test/) (KiCad project + PDF).

- **Module:** S → A2 (raw) and → R1 100k → A3, with C1 22n from A3 to GND. + → **3V3** (not 5V). − → GND.
- **Test LED:** D3 → R2 1k → base of Q1 (2N3904); 5V → R3 100 Ω → D1 white LED → Q1 collector; Q1
  emitter → GND.
- **Setup:** D1 faces the detector 1–2 cm away inside a short black tube (light-tight). The
  module's own LED is covered with black tape.

> **Safety:** the LED flashes at 1–60 Hz. Keep it inside the tube, and keep anyone photosensitive away.

## Run it

```sh
UNOQ_APP=detector-test tools/unoq dev       # push, start, show the output
```

In VSCodium you can instead set `"unoq.app": "detector-test"` in `.vscode/settings.json`, then
press Ctrl+Shift+B.

- **Timing:** the test starts 3 s after the app does and takes about 1–2 minutes.
- **Run it again:** `UNOQ_APP=detector-test tools/unoq restart`.
- **Save the files:** `UNOQ_APP=detector-test tools/unoq pull` copies the raw captures and results
  to `recordings/detector-test/`.

## The test algorithm

| Step | LED pattern | Measures | Why |
|---|---|---|---|
| 1 dark | off, 1 s | baseline level, noise | detection threshold = 10 × noise (min. 1% of range) |
| 2 steady | on, 1 s | response size, polarity, saturation | is the LED seen at all; does brighter read higher or lower |
| 3 step | off 0.5 s → on 1 s → off 0.5 s | 10–90 % rise and fall time → bandwidth ≈ 0.35 / rise time; does the output fall back under steady light | a module with a heartbeat filter jumps on the step, then returns to baseline |
| 4 sweep | 50 % square wave at 1, 2, 3, 5, 8, 10, 12, 15, 18, 20, 25, 30, 40, 50, 60 Hz, 2 s each | frequency found at 1000/s **and** at 200/s (instant readings, exactly like `sensor-stream`); response vs. a perfect detector; brightness swing | the real question: is each frequency read correctly, and how much of the signal survives |
| 5 pulses | 10 Hz flashes lasting 1 ms, then 5 ms | flashes caught at 1000/s and (averaged over reading offsets) at 200/s | short strobe flashes can fall between readings (DI-18) |
| 6 verdict | – | per channel | see below |

**How the numbers are worked out:**
- **Frequency found:** the strongest peak in the spectrum between 0.5 and 100 Hz.
- **Response:** the strength of the flicker at the drive frequency, compared with what a perfect
  detector would show for the step-2 contrast (2 × contrast / π, the fundamental of a square wave).
- **Correct:** a frequency counts as read correctly when it's within ±0.5 Hz of the drive frequency.

## Verdicts

| Verdict | Rule | What to do |
|---|---|---|
| **PASS** | Frequency correct with response ≥ 50% up to at least 30 Hz, *and* every rate from 3–30 Hz correct at 200/s | Use this channel as the flicker sensor (DI-01 option A). Choose A2 or A3 using the short-flash line |
| **PARTIAL** | Usable up to at least 10 Hz | Probably a built-in heartbeat filter; read the hints. Try the bare phototransistor (Q2/R4 → A1) |
| **FAIL** | Usable below 10 Hz, or no clear response | Follow the hints: wiring, aim, covered LED, IR-only detector |

**Possible hints:**
- **inverted output:** fine for frequency; flip the signal before using the swing readout.
- **saturated:** move the LED back, or raise R3.
- **heartbeat filter detected:** the module needs a bare phototransistor instead.
- **short flashes missed at 200/s:** compare A2 and A3, or keep the highest of several quick
  readings per sample.

To test the optional phototransistor too, fit Q2/R4 and add `0: "A1 phototransistor"` to
`CHANNELS` at the top of `python/main.py`.

## Example output (simulated fast detector)

```
[test] A2 raw: dark 300 ± 3.0, LED on 2800, contrast +2500 of 4095
[test]   step: rise 1.0 ms, fall 1.0 ms → bandwidth ≈ 350 Hz
[test]   drive   seen@1000/s  seen@200/s  response  swing@200/s
[test]     25 Hz    25.0       25.0      100 %      89 %
[test]     60 Hz    60.0       60.0       99 %      89 %
[test]   10 Hz flashes of 1ms: caught 20/20 at 1000/s, ~4/20 at 200/s
[test] VERDICT A2 raw: PASS: reads flicker correctly up to 60 Hz, and at 200/s from 3-30 Hz
```

## Status

- **Sketch:** compiles for the UNO Q.
- **Grading:** dry-run on a laptop against four simulated detectors:

  | Simulated detector | Verdict |
  |---|---|
  | Fast | PASS |
  | With a heartbeat filter (0.7–5 Hz) | PARTIAL, plus the filter hint |
  | IR-only | FAIL, plus the wiring/IR hints |
  | Inverted output | PASS, plus the inverted hint |

- **Not yet run on the real board.**
