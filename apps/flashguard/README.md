# FlashGuard

FlashGuard's on-board system: **two Edge Impulse models on the UNO Q, fully offline.**

| Model | Runs on | Input | Output |
|---|---|---|---|
| **Flicker** (stimulus), our project 1170128 | Linux side (QRB2210), via the `arduino:motion_detection` brick's runner container | Modulino Light R/G/B, 64 readings (~1.77 s), every 0.5 s | `flicker` / `no_flicker`. **97.0% on 101 held-out test windows**, no false alarms |
| **Movement** (response), "Wearable Movement Monitoring (More Classes)", project 1170305 | MCU (STM32U585), exported Arduino library in `libraries/` | Modulino Movement accX/Y/Z (g) + gyrX/Y/Z (°/s) at 4 Hz, 40 samples (10 s), every 2.5 s | Running, **Seizure**, Sitting, Standing, Walking, Waving |

```sh
tools/unoq dev        # flashguard is the default app: builds + flashes the sketch from the laptop (DI-20),
                      # starts Python + model runner, shows the output. First build ~8 min (Edge Impulse SDK)
tools/unoq push       # copies the Python side and installs models/flashguard.eim when it changed
UNOQ_NO_SKETCH=1 tools/unoq restart    # restart Python + model runner only (needed after a model change)
tools/unoq autostart  # start at power-up, no laptop needed (set on our board)
```

Models, their provenance and accuracy: [models/README.md](models/README.md). This is
**v0.1, the first working model** ([release note](../../docs/RELEASE_v0.1.md)).

## Wiring

Modulino Light and Modulino Movement daisy-chained on the UNO Q's Qwiic connector (`Wire1`). The
light sensor faces forward (cap brim); the movement sensor goes on the wrist or arm. The sketch
reconnects either one if it's plugged in later.

Both Modulinos are read through their registers, not the Arduino_Modulino library, which stops
sketches starting on our board (DI-24). The movement data matches the library's (g and °/s);
checked: 1.01 g at rest.

## Behaviour (after the stimulus)

```
MONITOR ──flicker alert──▶ EXPOSURE ──flicker gone──▶ WATCH (5 min, sensitivity raised)
   │                          │                           │
   │      seizure-like movement: P(Seizure) ≥ 0.6 in 2 classifications in a row (5 s)
   │                          └─────────────┬─────────────┘
   │                                        ▼
   │  outside the watch window: P ≥ 0.8 in 4 in a row (10 s), or off if MOVEMENT_ONLY_AFTER_STIMULUS
   │                                        ▼
   └◀── movement settles (2 × P < 0.3) ── SEIZURE SUSPECTED: 15 s countdown ──▶ CARER ALARM
```

- **Flicker alert:** P(flicker) ≥ 0.8 in 2 of the last 3 windows. Without a flicker model, the rule
  baseline (brightness swing ≥ 10% at ≥ 3 Hz) is the stimulus instead.
- **Settings:** the constants at the top of `python/main.py`: `WATCH_S`, `SEIZURE_P_WATCH`,
  `SEIZURE_N_WATCH`, `SEIZURE_P_ALWAYS`, `SEIZURE_N_ALWAYS`, `COUNTDOWN_S`,
  `MOVEMENT_ONLY_AFTER_STIMULUS`.
- **Not yet:** the wearer can't cancel the countdown (no button yet). The alarm shows on the LED
  matrix only; there's no Vibro/Buzzer output yet. See `docs/BRIEF.md`.

## LED matrix

The UNO Q's 8 × 13 matrix shows the state, updated by Python with `Bridge.call("show", state, value)`.
All icons are static and change at most once a second, so nothing on the device flashes (spec N7).

| State | Icon |
|---|---|
| Monitoring | dim eye |
| Flicker exposure | warning triangle with "!" |
| Watch window | bright eye, plus a bottom bar for the time left (13 columns = 5 min) |
| Seizure suspected | countdown digits to the carer alarm |
| Carer alarm | SOS |

A self-test shows each icon for 1.5 s when the board starts sending (`LED_SELFTEST` in `main.py`).
The matrix functions come from the UNO Q core (`matrixBegin`, `matrixGrayscaleWrite`), so no extra
library is needed.

## Output

```
[ei] flicker 0.97 ██████████ → ⚠ FLICKER (31 ms)
[alert] fast flickering light detected (model, P=0.97): cover one eye and look away
[watch] flicker gone after 12 s: watching for seizure-like movement for 5 min (sensitivity raised)
[move] Seizure 0.85 (top: Seizure) · Waving 0.08 · Running 0.04 · Walking 0.02 · watch 4:53 left (model 12.9 ms on the MCU)
[alert] seizure-like movement after a flicker exposure: carer alarm in 15 s unless it stops
[alert] CARER ALARM: seizure-like movement continued after a flicker exposure
```

## Files written on the board (`data/recordings/`)

| File | What it holds |
|---|---|
| `flicker.<time>.csv` | Every light reading. Training data for the flicker model (`tools/ei`) |
| `movement.<time>.csv` | 4 Hz movement samples, with the same columns as the teammate's `MovementSensor` data |
| `events.<time>.csv` | Exposure start/end, seizure suspected/cancelled, carer alarm (spec F8) |

## How it works

- **Sketch:**
  - streams light readings (R, G, B, gain) at ~36/s with automatic gain;
  - samples the Modulino Movement every 250 ms;
  - runs `run_classifier()` on the latest 10 s every 2.5 s (about 13 ms on the MCU, measured);
  - sends the class scores with the model's time on the MCU.
  - Builds with board package 1.1.0: 191 KB flash, 82 KB RAM. The first build compiles the Edge
    Impulse SDK, about 8 min.
- **Python:**
  - asks the runner to classify each light window: the `.eim` model at
    `/home/arduino/.arduino-bricks/ei-models/flashguard.eim`, about 30 ms per call measured on the
    board;
  - runs the state machine above;
  - logs events.
- **Preprocessing of the light window** (`features.py`): divide by the gain, take the log, subtract
  the window mean. It's shared with the training tools. **If you change it, retrain.**
- **Movement model input:** accX/Y/Z and gyrX/Y/Z at 4 Hz, the exact recipe of the teammate's
  `MovementSensor` sketch it was trained on. **Changing the rate or the units breaks it.**
