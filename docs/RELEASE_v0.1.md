# FlashGuard v0.1: first working model

**Tag `v0.1`** · Sun 22 Nov 2026 · Team 11, CUES × Edge Impulse × Cambridge MedTech hackathon

(v0.1 was tagged under the working name *FlickerGuard*: the tag message and the files at that tag use
the old name and the app folder `apps/flicker-guard`. The project was renamed **FlashGuard** later
the same day.)

The first version where the whole chain runs on the Arduino UNO Q, offline:
**flicker detection (Edge Impulse) → watch window → seizure-like movement (Edge Impulse) → carer
alarm**, with the state shown on the board's LED matrix.

## What works

| Part | Where | Status |
|---|---|---|
| Flicker model | Linux side, brick runner, `apps/flashguard/models/flashguard.eim` | 97.0% on 101 held-out test windows, no false alarms; ~30 ms per check on the board |
| Movement model (teammate's, project 1170305) | MCU, Arduino library in `apps/flashguard/libraries/` | Runs every 2.5 s, ~13 ms; input checked (1.01 g at rest) |
| After-stimulus logic | `apps/flashguard/python/main.py` | Flicker alert → 5 min watch window → P(Seizure) ≥ 0.6 for 5 s → 15 s countdown → carer alarm; tested in simulation |
| LED matrix | `apps/flashguard/sketch/sketch.ino` | Static icons: eye, warning triangle, eye + time bar, countdown, SOS. Self-test passes on the board |
| Logging | `data/recordings/` on the board | Light, movement and events (exposure, alarm) as CSV |
| Starts at power-up | App Lab default app | FlashGuard comes up by itself about 2 min after power-on, no laptop needed |
| Sensor characterisation | `apps/light-test`, `hardware/light-test` | Screen sweep PASS: 10 Hz read correctly, correct band 1–15 Hz, sensor takes ~36 readings/s |
| Training pipeline | `tools/flicker.html` (Collect), `tools/ei/` | Record → label → upload → train → deploy, scripted |

**Board facts this version relies on** (all in `docs/DESIGN_ISSUES.md`):
- Sketches are built and flashed from the laptop with board package 1.1.0 (DI-20).
- The Modulinos are read through their registers, not the Arduino_Modulino library (DI-24).
- Python ↔ MCU calls work in both directions (DI-20 update).

## Run it

```sh
tools/unoq doctor                 # board on USB
tools/unoq dev                    # push + flash + watch (flashguard is the default app)
tools/unoq push                   # also installs the pinned flicker model when it changed
tools/unoq autostart              # start FlashGuard at power-up (already set on our board)
```

Live test:
1. `tools/flicker.html` at 10 Hz, 2–5 cm in front of the **Modulino Light**, in a dim room → warning
   triangle.
2. Esc → eye + time bar.
3. Shake the **Modulino Movement** for 10–20 s → countdown → SOS.

## Known limits / not yet done

- **Live end-to-end test not completed.** The first attempt was in bright daylight, and the board
  rebooted when it was moved.
- **Flicker model trained on one screen session only** (bright room, laptop screen). Needs more data:
  dim room, real strobes, other screens.
- **The Seizure class comes from acted movements**; not checked live on our sensor.
- **No wearer cancel button and no vibration/buzzer output yet** (LED matrix only).
- **Frequencies above ~15 Hz are folded** by the light sensor (DI-01). Detection still works up to
  ~30 Hz.

## Repo at this version

See the layout in [`README.md`](../README.md). `archive/` holds apps that are not part of v0.1:
- `sensor-stream`, replaced by FlashGuard's own recording, and affected by DI-24;
- the MAX30102 heart-rate experiment (DI-22).
