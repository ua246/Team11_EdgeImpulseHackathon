# Models in FlickerGuard v0.1

Both models are pinned here, so v0.1 can be rebuilt exactly as it ran.

## Flicker model (stimulus): `flicker-guard.eim`

| | |
|---|---|
| Edge Impulse project | 1170128 (`loadingwear-project-1`), deployment v1 |
| File | `flicker-guard.eim`: Linux aarch64 (`runner-linux-aarch64`), 13.8 MB, md5 `fdcff01a0dea321718621068b1fb2c2f`. Identical to the copy that ran on the board on 2026-11-22 |
| Runs on | UNO Q Linux side, through the `arduino:motion_detection` brick's runner (`app.yaml`) |
| Input | 64 Modulino Light readings × R, G, B (~1.77 s at ~36/s), preprocessed by `python/features.py`: ÷ gain, log, minus the window mean |
| Impulse | Time series 1767 ms / 36.23 Hz → Spectral Analysis (FFT 64, no filter, log spectrum) → Keras classifier |
| Classes | `flicker` (3–30 Hz square-wave flashing), `no_flicker` (steady light, slow blinks ≤ 2 Hz, fades, level steps, room light) |
| Training data | One 7 min Collect session from a laptop screen (`tools/ei`): 409 training + 101 test windows, split by segment |
| Accuracy | **97.0%** on the 101 held-out test windows (int8 and float32): flicker 33/36 (3 "uncertain"), no_flicker 65/65 |
| Speed | ~30 ms per classification on the board (HTTP call to the runner included) |
| Rebuild | `tools/ei/ei.py train` then `tools/ei/ei.py deploy` (Admin API key), copy the `.eim` here |
| Install | `tools/unoq push` copies it to `/home/arduino/.arduino-bricks/ei-models/` when it differs |

**Known limits:**
- Trained on screen flicker only, in a room bright enough to swamp the screen (DI-23).
- Real strobes, other screens and daylight are untested.
- The Modulino Light reads true frequencies only up to about 15 Hz; faster flicker is folded (DI-01).

## Movement model (response): Arduino library in `../libraries/`

| | |
|---|---|
| Edge Impulse project | 1170305, "Wearable Movement Monitoring (More Classes)" (teammate's), deployment v1 |
| File | `../libraries/Wearable_Movement_Monitoring_More_Classes__inferencing/` (exported Arduino library, EON-compiled int8 model) |
| Runs on | UNO Q MCU (STM32U585), inside `sketch/sketch.ino`. ~13 ms per classification |
| Input | Modulino Movement accX/Y/Z (g) + gyrX/Y/Z (°/s) at 4 Hz, 40 samples (10 s), classified every 2.5 s. Recipe: `movement/MovementSensor.ino` |
| Impulse | Spectral Analysis (FFT 16, log, overlap) on the 6 axes → classifier |
| Classes | Running, **Seizure**, Sitting, Standing, Walking, Waving |
| Accuracy | Not reported to us; trained on acted movements (DI-09) |
| Rebuild | Re-export "Arduino library" from project 1170305 and replace the folder in `../libraries/` |

**Known limit:** the Seizure class comes from acted shaking. Whether acted shaking on our sensor
scores high hasn't been checked live yet.
