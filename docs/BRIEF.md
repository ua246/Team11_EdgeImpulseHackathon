# FlashGuard: status after day 1, plan for day 2

**Team 11** · written Sat 21 Nov 2026, evening · Devpost deadline **Sun 12:00**, judges 13:00.
Full design: [PROJECT_SPEC.md](PROJECT_SPEC.md) · decisions and problems:
[DESIGN_ISSUES.md](DESIGN_ISSUES.md) · board workflow: [UNOQ_DEV.md](UNOQ_DEV.md).

## Update: Sun 22 Nov, morning

**Both Edge Impulse models now run on the UNO Q, offline** (`apps/flashguard`, DI-23):

| | Flicker model (stimulus) | Movement model (response) |
|---|---|---|
| Project | ours, 1170128 | teammate's "Wearable Movement Monitoring (More Classes)", 1170305 |
| Runs on | Linux side, brick runner (`.eim`) | MCU, exported Arduino library |
| Input | Modulino Light R/G/B, 1.77 s window every 0.5 s | Modulino Movement acc + gyro at 4 Hz, 10 s window every 2.5 s |
| Result | **97.0%** on 101 held-out test windows, no false alarms | classes Running / **Seizure** / Sitting / Standing / Walking / Waving |
| Time per classification on the board | ~30 ms | ~13 ms |

**After-stimulus logic:**
1. A flicker alert opens a **5 min watch window**.
2. P(Seizure) ≥ 0.6 for 5 s then starts a **15 s countdown** to the carer alarm, which is cancelled
   if the movement settles.
3. Outside the window the rule is stricter (≥ 0.8 for 10 s).
4. Events are logged to `events.<time>.csv`.

This is tested in simulation, and each model runs on the board. **The live end-to-end test (flicker
page → shake the Movement module) is the next step.**

**Found:** the Arduino_Modulino library stops sketches starting on our board, so both Modulinos are
now read through their registers (DI-24).

**LED matrix:** shows the state with static icons: eye, warning triangle, eye + time bar, countdown,
SOS. This confirmed that **Python → MCU calls (`Bridge.call`) work** on our board.

**Still to do from the list below:** priority 1's live test; priorities 2–5. Wearer cancel and
Vibro/Buzzer output are open.

**Saved as v0.1, the first working model** (git tag `v0.1`, [RELEASE_v0.1.md](RELEASE_v0.1.md)).
The repo is now organised around it:
- `apps/flashguard` is the product, with its models pinned in `models/`;
- `sensor-stream` and the MAX30102 app moved to `archive/`;
- `tools/unoq` and VSCodium default to `flashguard`, and `tools/unoq push` installs the pinned model.

## In one paragraph

A wearable that warns people with photosensitive epilepsy about seizure-provoking flicker, and
alarms a carer if a convulsive seizure follows. The **light side works end to end except for the
trained model**:
- The Modulino Light is characterised on the real board: 10 Hz flicker reads correctly, and the
  frequency is right from 1 to 15 Hz.
- An app streams and records its readings.
- Arduino's Edge Impulse runner runs offline on the board with our app.
- Labelled training data is recorded and uploaded to Edge Impulse.

**Tomorrow's first job is to train the model, put it on the board and test it live.** The seizure
(motion) side hasn't started.

## What exists

### Board and tooling
| Item | What it does | State |
|---|---|---|
| `tools/unoq` | One command for the board over USB: `dev`, `push`, `start`/`restart`, `logs`, `flash`, `pull`, `record`, `doctor` | Works on our board |
| Flashing from the laptop | The board's App Lab (0.7, core 0.52) can't flash sketches (DI-20). `tools/unoq` builds with core 1.1.0 on the laptop and uploads over USB automatically | Works |
| `UNOQ_NO_SKETCH=1 tools/unoq restart` | Restarts Python and the brick containers without re-flashing | Works |
| `tools/pretty.py`, VSCodium tasks | Coloured, timestamped output; Ctrl+Shift+B = push + restart + watch | Works |

### Apps (`apps/`)
| App | Purpose | State |
|---|---|---|
| `flashguard` | **The product.** Streams Modulino Light readings with auto gain, runs the Edge Impulse model every 0.5 s (P(flicker) ≥ 0.8 in 2 of 3 windows → alert), prints a rule-based baseline, records training data | Verified on the board except inference with a real flicker model (none trained yet; a placeholder model sits at the model path) |
| `light-test` | Characterises the Modulino Light: LED-rig sweep (automatic) or screen sweep (`tools/flicker.html` → Sweep, analysed by `screen_sweep.py`), with PASS/PARTIAL/FAIL verdicts | Screen sweep **PASS**; LED rig not built yet |
| `sensor-stream` (now `archive/`) | Streams Modulino Light + Movement; labelled CSV recording for Edge Impulse (`tools/unoq record`) | Compiles; **not yet run on the board** (DI-15). The starting point for the motion model |
| `max30102-heart-rate` (now `archive/`) | A teammate's standalone heart-rate app | Outside the current design (DI-22); kept as is |

### Edge Impulse pipeline (`tools/ei/`, see its README)
| Step | State |
|---|---|
| `tools/flicker.html` → **Collect**: 7 min labelled schedule (flicker 3–30 Hz in several colours and contrasts; steady, slow blinks, fades, steps; 60 s room light) | Done, 1 session |
| `make_dataset.py`: finds the session by correlating with the schedule, cuts 64-reading windows, splits training/test by segment | Done, tested on simulated and real data |
| `ei.py upload`: JSON ingestion to project **1170128** | Done: **409 training + 101 test windows** (148 / 36 flicker) |
| `ei.py train` / `ei.py deploy` | **To do**: needs an **Admin** API key (the current key can only upload and deploy) |

### Hardware
| Item | State |
|---|---|
| `hardware/light-test`: KiCad schematic (UNO Q, Modulino Light on Qwiic, test LED on D3 via 2N3904), electrical rules check 0 errors / 0 warnings, PDF, parts list | Drawn; **not built** |
| Modulino Light on the Qwiic connector | In use |
| Modulino Movement, Vibro, Buzzer, Buttons | Not wired into an app yet |

### Measured facts worth quoting in the pitch
- **The Modulino Light takes about 36 readings/s** (nominally 40), so the frequency limit is
  about 18 Hz (DI-01).
- **Screen sweep:** frequency correct from 1 to 15 Hz; 10 Hz strength 76% (88% predicted); 20 and
  30 Hz fold exactly as predicted. 18 and 25 Hz misread only because a 60 Hz screen can't show
  them evenly.
- **Mains lighting** (100 Hz) folds to about 8.6 Hz at about 0.1% of the light level, far below the
  10% alert swing.
- **The Edge Impulse runner runs fully offline on the UNO Q** with a custom model (DI-23).

## What needs doing tomorrow (in priority order)

**1. Train and deploy the flicker model. MVP, about 1–1.5 h.**
- Get an **Admin** API key (Studio → Dashboard → Keys → Add new, role Admin) and save it to
  `~/.config/flashguard/ei-api-key`.
- Write `ei.py train`, or click through Studio with the settings in `tools/ei/README.md`:
  - time-series window 1767 ms, 36.23 Hz;
  - Spectral Analysis on R/G/B, FFT 64, log on;
  - Keras classifier.

  Check the test accuracy. Delete the one duplicate window.
- Write `ei.py deploy`: build the **"Arduino UNO Q"** (`arduino-uno-q`) or `runner-linux-aarch64`
  target, download the `.eim`, then
  `adb push … /home/arduino/.arduino-bricks/ei-models/flashguard.eim` and
  `UNOQ_APP=flashguard UNOQ_NO_SKETCH=1 tools/unoq restart`.
  - Check that the model's `input_features_count` is 192.
- **Live test:**
  - flicker page at 5, 10 and 15 Hz → alert;
  - steady screen, 1–2 Hz blinks, room light, waving a hand → no alert.
  - Measure the inference time and the time from onset to alert (T4, target ≤ 1 s).

**2. Better training data, if accuracy or the live test is weak. About 45 min.**
- Run **Collect** again with the **sensor 1–2 cm from the screen in a dimmed room**. The first
  session was swamped by room light.
- Add real-world negatives: walking around, lights switching on and off.
- If possible, add a phone-torch strobe app as a different flicker source.
- Re-upload (keep the old data) and retrain.

**3. Wearer alert output. About 45 min.**
- Modulino Vibro (and/or Buzzer) on the Qwiic chain: vibrate on `[alert]`.
- A UNO Q LED-matrix icon (static, nothing that flashes; N7).
- This needs a Python → MCU message (`Bridge.call`), which is **unproven on our board** (DI-20).
  Test it early; the fallback is a sketch that drives the Vibro from a rule on its own data.

**4. Demo and submission. Protect this time: 10:30–12:00.**
- Demo script (spec §11): shielded flicker → vibration; harmless light → nothing.
- A results table: model accuracy against the rule baseline, false alerts, latency.
- A backup video. Devpost text (spec §17), and update the spec's open items.

**5. Stretch: seizure-like motion (model B).**
- (Superseded: the teammate's movement model now runs in flashguard.) Run `sensor-stream` on the board, record acted shaking against normal activities (2 people), and
  train a second model.
- **Open question:** whether two brick runners can run at once. The fallback is a rule on the motion
  energy.
- Only start this if 1–4 are done by about 10:00. Otherwise the pitch is "FlashGuard light-only"
  (spec §15).

**Optional:** build the LED rig and run `apps/light-test` (T1 with a real LED), for a cleaner sensor
characterisation than the screen.

## How to pick up

```sh
adb devices                                         # board on USB; Linux needs ~1 min after power-on
UNOQ_APP=flashguard tools/unoq dev               # flashes the sketch, starts the runner, shows output
python3 -m venv .venv && .venv/bin/pip install numpy requests   # laptop tools
.venv/bin/python tools/ei/ei.py info                # project 1170128: data and impulse summary
```

**Not in git (on purpose):**
- Recordings live in `recordings/` on the laptop that took them. The raw session is
  `flashguard/flicker.20251210-195010.csv`; the board's clock is unsynced, hence the date.
- The training windows are in the Edge Impulse project.
- The API key lives in `~/.config/flashguard/`.

**Board state:**
- `flashguard` is installed, with the placeholder model.
- The `arduino` user's password has never been set (DI-19); it's only needed for sudo/SSH/updates.

## Risks for tomorrow

| Risk | Mitigation |
|---|---|
| Model weak on real light (trained on one screen session in a bright room) | Priority 2 data; the rule baseline is already in the app as a fallback |
| No Admin key / API surprises | Train in the Studio UI (settings in `tools/ei/README.md`); the current key can still deploy |
| `Bridge.call` Python → MCU doesn't work (alert output) | Drive the Vibro from the sketch's own rule; keep the model's verdict on screen |
| Demo flicker in the judging room | Never strobe the open room: tube or cupped hand, warn first (DI-12) |
| Time | Model B is stretch only; stop features at 10:30 |
