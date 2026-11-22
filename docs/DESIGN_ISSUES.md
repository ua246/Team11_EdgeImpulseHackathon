# Design issue log

Problems, limits and decisions found while building the device. Add an entry whenever something
changes the design, and update its status rather than deleting it: the history is useful for the
pitch and the Q&A. IDs are never reused; gaps are entries removed with DI-22.

**Status:** Open · Mitigated (worked around, needs a hardware check) · Resolved · Accepted
(known limitation, stated in the pitch) · Rule (constraint everyone must follow)
**Severity:** High (could sink the demo or the core claim) · Medium · Low

| ID | Issue | Area | Severity | Status |
|---|---|---|---|---|
| [DI-01](#di-01-modulino-light-takes-only-about-36-readings-per-second) | Modulino Light takes only about 36 readings/s | Sensing | High | Accepted |
| [DI-02](#di-02-modulino-light-library-blocks-for-50150-ms) | Modulino Light library blocks for 50–150 ms | Firmware | High | Mitigated |
| [DI-03](#di-03-modulino-light-has-a-fixed-i2c-address) | Modulino Light has a fixed I2C address | Hardware | Low | Accepted |
| [DI-04](#di-04-mcu--linux-link-is-only-115200-baud) | MCU ↔ Linux link is only 115200 baud | Firmware | Medium | Mitigated |
| [DI-05](#di-05-pin-voltages) | Pin voltages: 3.3 V logic, A0/A1 not 5 V tolerant | Hardware | High | Rule |
| [DI-08](#di-08-motion-only-detects-convulsive-seizures) | Motion only detects convulsive seizures | Clinical | Medium | Accepted |
| [DI-09](#di-09-no-real-seizure-data) | No real seizure data | ML | High | Accepted |
| [DI-10](#di-10-streams-have-different-sample-rates) | Streams have different sample rates | ML | Low | Resolved |
| [DI-11](#di-11-sensor-placement-pulls-in-two-directions) | Sensor placement pulls in two directions | Hardware | Medium | Open |
| [DI-12](#di-12-demo-safety-flashing-light-in-the-judging-room) | Demo safety: flashing light in the judging room | Demo | High | Rule |
| [DI-13](#di-13-bridge-deadlock-rule) | Bridge deadlock rule | Firmware | Medium | Rule |
| [DI-14](#di-14-eduroam-may-block-ssh-to-the-board) | eduroam may block SSH to the board | Tooling | Low | Mitigated |
| [DI-15](#di-15-tooling-not-yet-run-on-real-hardware) | Tooling not yet run on real hardware | Tooling | Medium | Resolved |
| [DI-18](#di-18-screens-short-flashes-and-viewing-distance) | Screens, short flashes and viewing distance | Sensing | Medium | Open |
| [DI-19](#di-19-our-board-runs-app-lab-07--zephyr-core-052) | Our board runs App Lab 0.7 / Zephyr core 0.52 | Tooling | High | Mitigated |
| [DI-20](#di-20-sketch-upload-to-the-mcu-fails) | Sketch upload to the MCU fails | Firmware | High | Mitigated |
| [DI-22](#di-22-decision-the-modulino-light-is-the-only-light-sensor) | Decision: the Modulino Light is the only light sensor | Sensing | High | Resolved |
| [DI-23](#di-23-running-the-edge-impulse-models-offline-on-the-uno-q) | Running the Edge Impulse models offline on the UNO Q | ML | High | Mitigated |
| [DI-24](#di-24-the-arduino_modulino-library-stops-sketches-starting-on-our-board) | The Arduino_Modulino library stops sketches starting on our board | Firmware | High | Mitigated |
| [DI-25](#di-25-the-sketch-crashes-after-a-power-cycle-since-the-heart-rate-start-up) | The sketch crashes after a power cycle (since the heart-rate start-up) | Firmware | High | Open |

---

## DI-01 Modulino Light takes only about 36 readings per second
**Status:** Accepted (design decision, DI-22; measured on the board) · **Severity:** High · **Logged:** 2026-11-21

**Limit.** The LTR-381RGB on the Modulino Light needs at least 25 ms per reading: the fastest
settings in the Arduino_LTR381RGB library are 16-bit resolution (25 ms integration) and a 25 ms
repeat rate, nominally 40 readings/s. **On our board it measured 36.1–36.3 readings/s** (two runs
of `apps/light-test`): the sensor's own clock runs about 10% slow, so each reading averages about
27.6 ms. Frequencies above half that rate, **about 18 Hz**, fold back to a wrong, lower value
(aliasing). The flicker most likely to trigger seizures is 16–25 Hz (Epilepsy Society).

**What the sensor sees.** Each reading is the *average* light over its window, which also weakens
fast flicker. Predicted for the measured 36.2 readings/s:

| True flicker | Strength after averaging | Seen as | Measured (screen sweep) |
|---|---|---|---|
| 5 Hz | 97% | 5 Hz | 5.0 Hz ✓ |
| 10 Hz | 88% | 10 Hz | **10.0 Hz ✓**, 76% strength |
| 15 Hz | 74% | 15 Hz | 15.0 Hz ✓ |
| 18 Hz | 64% | 18 Hz (at the limit) | screen artefact, see below |
| 20 Hz | 57% | **16 Hz** | 16.3 Hz ✓ (folded as predicted) |
| 25 Hz | 38% | **11 Hz** | screen artefact, see below |
| 30 Hz | 20% | **6 Hz** | 6.3 Hz ✓ (folded as predicted) |
| 35 Hz | 3% | **1 Hz** | – |
| 36 Hz | 0% (invisible) | — | – |
| 100 Hz (UK mains lighting) | 8% | **8.6 Hz** | seen in room light at ~8.6 Hz, 0.1% of the light level |

**Measured (2026-11-21).** `apps/light-test`'s screen sweep: `tools/flicker.html` on the laptop
screen, sensor 2–5 cm away. Report: `recordings/light-test/lighttest.20251210-192133.screen.report.txt`
(the board's clock is unsynced).
- **10 Hz: PASS.** It reads 10.0 Hz, and 9 and 11 Hz are correct too.
- **Correct frequency from 1 to 15 Hz**, all 11 rates exact.
- **20 and 30 Hz fold exactly where predicted.**
- **The strength is a little below prediction:** 76% vs 88% at 10 Hz. Part of this is the screen's
  slow pixel changes; the LED test separates the two.
- **18 and 25 Hz read 6.1 and 5.0 Hz because of the screen.** A 60 Hz screen can't show those rates
  evenly: the frame pattern repeats every 3 periods (18 Hz) or 5 periods (25 Hz), adding a 6 Hz or
  5 Hz component that the sensor reports. Flashing video on 60 Hz screens has the same structure.
- The LED rig run hasn't been done yet (the first attempt had no LED connected).

**So:**
- **The frequency is read correctly up to about 15 Hz;** 15–18 Hz is borderline; above about 18 Hz
  it folds to a wrong, lower frequency.
- **Flicker is still *detected* (yes/no) from 3 Hz to about 30 Hz,** at reduced strength. That's
  enough for a warning, but not for weighting the 16–25 Hz peak band by its true frequency.
- **Ripple from mains-powered lights (100 Hz in the UK) folds to about 8.6 Hz,** inside the
  warning band. It is weak (8% predicted; 0.1% of the light level measured in room light), so
  ignore anything below a minimum brightness swing (the broadcast guidelines only count changes of
  about 10% or more). The reading rate varies a little between sensors, so the exact alias does too.
- **Because each reading integrates over ~27 ms, short strobe flashes are not missed between
  readings.** A 2 ms flash still adds its energy to the reading it falls in (DI-18).

**Possible upgrade (not planned): two Modulino Lights half a period out of step** would give about
72 readings/s and correct frequencies up to about 30 Hz. But both sensors have the same fixed
address, so they need separate I2C buses (DI-03). Their clocks drift apart within about a second,
so one sensor must be restarted periodically to keep the offset. The averaging is unchanged, and
the two units need matching. That's about 2–3 h of work with hardware risk.

**Tests.** `apps/light-test` (README there):
- **LED rig** (`hardware/light-test`): flashes a test LED at 1–35 Hz and in short flashes into the
  sensor.
- **Screen sweep:** `tools/flicker.html` → Sweep, analysed with `screen_sweep.py`.

Both report the frequency seen against the predicted alias, the strength against the averaging
prediction, and the usable band.

---|---|---|
| 5 Hz | 97% | 5 Hz |
| 10 Hz | 90% | 10 Hz |
| 15 Hz | 78% | 15 Hz |
| 18 Hz | 70% | 18 Hz (close to the 20 Hz limit) |
| 20 Hz | 64% | 20 Hz (at the limit) |
| 25 Hz | 47% | **15 Hz** |
| 30 Hz | 30% | **10 Hz** |
| 35 Hz | 14% | **5 Hz** |
| 40 Hz | 0% (invisible) | — |
| 100 Hz (UK mains lighting) | 13% | **20 Hz** |

**So:**
- **The frequency is read correctly up to about 15 Hz;** 15–20 Hz is borderline; above 20 Hz it
  folds to a wrong, lower frequency.
- **Flicker is still *detected* (yes/no) from 3 Hz to about 35 Hz,** at reduced strength. That's
  enough for a warning, but not for weighting the 16–25 Hz peak band by its true frequency.
- **Ripple from mains-powered lights (100 Hz in the UK) can show up as a weak fake 20 Hz signal.**
  Ignore anything below a minimum brightness swing (the broadcast guidelines only count changes of
  about 10% or more).
- **Because each reading integrates over 25 ms, short strobe flashes are not missed between
  readings.** A 2 ms flash still adds its energy to the reading it falls in (DI-18).

**Possible upgrade (not planned): two Modulino Lights half a period (12.5 ms) out of step** would
give 80 readings/s and correct frequencies up to about 35 Hz. But both sensors have the same fixed
address, so they need separate I2C buses (DI-03). Their clocks drift apart within about a second,
so one sensor must be restarted periodically to keep the offset. The 25 ms averaging is unchanged,
and the two units need matching. That's about 2–3 h of work with hardware risk.

**Test.** `apps/light-test` with the rig in `hardware/light-test` flashes a test LED at 1–35 Hz
into the Modulino Light. It reports, per rate, the frequency seen against the alias predicted
above, the response against the 25 ms averaging prediction, and the usable band. Expected:
correct around 10 Hz, folding above 20 Hz.

---

## DI-02 Modulino Light library blocks for 50–150 ms
**Status:** Mitigated (needs a hardware check) · **Severity:** High · **Logged:** 2026-11-21

**Problem.** Each call to `ModulinoLight::update()` (via `LTR381RGBClass::readAllSensors`) switches
the sensor between colour and ambient mode and waits for data with `delay(50)`. Every call blocks
about 50–150 ms, which would stall the IMU sampling and limit light to about 10/s.

**Decision.** The sketches (`flashguard`, `light-test`, and the archived `sensor-stream`) don't call `update()`. They configure the
sensor once (continuous colour mode, 16-bit / 25 ms), check the data-ready bit without waiting, and
read the colour registers directly. The register map was taken from the library source.

**Checked on hardware:** `flashguard`'s `[stat]` line shows ~36 readings/s (DI-01). `flashguard`
sets the gain automatically (register 0x05).

---

## DI-03 Modulino Light has a fixed I2C address
**Status:** Accepted · **Severity:** Low · **Logged:** 2026-11-21

The address is 0x53 and can't be changed, so two Lights can't share one bus. It only matters for
the two-sensor upgrade in DI-01. The workarounds are separate buses (`Wire1` = Qwiic, `Wire` =
header SDA/SCL, `Wire2` = A4/A5 with board package 1.1.0) or a multiplexer hub.

---

## DI-04 MCU ↔ Linux link is only 115200 baud
**Status:** Mitigated · **Severity:** Medium · **Logged:** 2026-11-21

**Problem.** All Bridge traffic between the microcontroller and the Linux side (`Bridge.notify`,
`Monitor`/`Serial` prints) shares a 115200-baud UART (`arduino-router` on `/dev/ttyHS1`), which is
about 11 KB/s in total. Sending one message per sample at high rates would saturate it.

**Decision.** The sketch batches compact integer CSV text every 100 ms, about 2 KB/s for the IMU at
50/s and light at 40/s. The MCU reports its slowest send, and Python prints `[warn]` if it looks bad.

**Rule.** Before adding a stream or raising a rate, estimate its bytes per second. For fast signals,
compute features on the microcontroller and send those instead of raw samples.

---

## DI-05 Pin voltages
**Status:** Rule · **Severity:** High · **Logged:** 2026-11-21

- Header pins use 3.3 V logic. Most digital pins tolerate 5 V, but **A0 and A1 do not**, and no pin
  may exceed 3.3 V while used as an analog input. Power any analog sensor from **3.3 V**.
- Servos, motors and the test LED take 5 V from the board's 5V pin or a power bank, never from a
  logic pin, and share the board's ground.
- Kit LCDs are usually 5 V I2C devices: they need a level shifter before going on a 3.3 V bus.

Source: Arduino UNO Q full pinout (ABX00162).

---

## DI-08 Motion only detects convulsive seizures
**Status:** Accepted (state it in the pitch) · **Severity:** Medium · **Logged:** 2026-11-21

A motion sensor can detect tonic-clonic (convulsive) seizures. Absence seizures and small myoclonic
jerks, which are common in photosensitive epilepsy, need EEG and are out of scope. The response
side of the device targets convulsive seizures only, from motion alone.

---

## DI-09 No real seizure data
**Status:** Accepted (state it in the pitch) · **Severity:** High · **Logged:** 2026-11-21

The motion model has to be trained on *acted* rhythmic shaking. What keeps false alarms down is a
wide set of normal vigorous activities in the training data: clapping, waving, brushing teeth,
jogging, typing, stirring. **Mitigations:**
- A cancel button for the wearer.
- An alarm only after shaking has lasted several seconds.
- Measure false alarms per hour of normal wear, and report it.
- Next step to mention in the pitch: validate on clinical data.

---

## DI-10 Streams have different sample rates
**Status:** Resolved · **Severity:** Low · **Logged:** 2026-11-21

IMU 50/s, light ≤40/s. **Decision:** record one CSV per stream, and give each Edge Impulse model
only the stream it needs (light model: `light`; seizure model: `imu`).

---

## DI-11 Sensor placement pulls in two directions
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

The light sensor must face forward near eye level (cap brim). The motion sensor works best on the
wrist or arm for convulsions. **Proposal:** Modulino Light on the cap; arm sleeve (provided)
holding the UNO Q and the Modulino Movement; one Qwiic cable up to the cap. Check cable lengths and
strain relief.

---

## DI-12 Demo safety: flashing light in the judging room
**Status:** Rule · **Severity:** High · **Logged:** 2026-11-21

Never strobe the open room. The flicker source goes inside a cupped hand or cardboard tube against
the sensor, exposures stay short, and the room gets a warning first. The same applies while
recording data. Ask teammates whether anyone is photosensitive.

---

## DI-13 Bridge deadlock rule
**Status:** Rule · **Severity:** Medium · **Logged:** 2026-11-21

Never call `Monitor.print()` or `Bridge.call()` inside a sketch function registered with
`Bridge.provide()`; it can deadlock. Use `Bridge.provide_safe()` for anything that touches Arduino
APIs. On the Python side, a function registered with `Bridge.provide()` must not call
`Bridge.call()`. Source: Arduino App Lab Bridge docs.

---

## DI-14 eduroam may block SSH to the board
**Status:** Mitigated · **Severity:** Low · **Logged:** 2026-11-21

Campus Wi-Fi often blocks device-to-device traffic. **Decision:** `tools/unoq` uses USB (adb) by
default; SSH is optional (`UNOQ_HOST`).

---

## DI-15 Tooling not yet run on real hardware
**Status:** Resolved (2026-11-22: `flashguard` runs, records to `data/` and is pulled with
`tools/unoq pull`; `sensor-stream` itself never ran and is archived, see DI-24) · **Severity:** Medium · **Logged:** 2026-11-21

The sketches compile for the UNO Q, and the Python sides passed laptop tests with simulated data.
Still to confirm on the board with `sensor-stream`:
- write permissions on the app's `data/` folder (recording);
- that the board's Python can see `data/record.json` at the path the laptop writes it to.

Close this issue after a successful `tools/unoq dev` plus a recording on the real board.

---

## DI-18 Screens, short flashes and viewing distance
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

**Flashes in video content.** A video can change at most once per frame, so its fastest flash is
half the frame rate: 12–15 Hz for 24/25/30 fps content, 25–30 Hz for 50/60 fps (games, sport). The
Modulino Light reads the first group at the right frequency; the second group is still detected
but folds to about 6–16 Hz (DI-01).

**Hidden fast flicker from screens is averaged out.** Screen refresh (60–240 Hz) and backlight /
OLED dimming (PWM, often 200 Hz to several kHz) is not the seizure risk. The 25 ms integration
averages it to a few percent, below the brightness-swing threshold. Mains ripple (100 Hz) leaks
through at about 8%, folded to about 8.6 Hz, and is handled by the same threshold.

**Short strobe flashes are caught.** Because each reading integrates 25 ms of light, a short flash
(a xenon strobe under 1 ms, or an LED strobe of a few ms) can't fall between readings. It shows up
at its energy share of the reading.

**Distance: it's about share of view, not metres.** The sensor measures *all* the light in its
field of view. The flicker signal is the flashing source's share of that light, so it falls with
distance, smaller screens and brighter rooms. That matches the usual advice for people with
photosensitive epilepsy (watch in a well-lit room, sit further back, use smaller screens), so the
reading scales roughly the way the risk does. **To aim it where the wearer looks,** put the
sensor at the end of a short black tube on the cap brim.

**Next step.** Measure the brightness swing with the flicker page on a laptop and a TV at 0.5, 1,
2 and 3 m, in a dim and a lit room, with and without the tube. The `swing NN%` value in
`flashguard`'s `[stat]` line shows it directly. Set the alert threshold from that data.

---

## DI-19 Our board runs App Lab 0.7 / Zephyr core 0.52
**Status:** Mitigated · **Severity:** High · **Logged:** 2026-11-21

Found on the real board (`uno-q`): `arduino-app-cli` 0.7.0, `arduino:zephyr` 0.52.0, Python
container `python-apps-base:0.5.0` (Python 3.13, numpy). The board is offline (no Wi-Fi). The tools
were written against the 0.14 docs. Differences and fixes:
- **No `app ps`, `--verbose` or top-level `monitor`** (it's `app monitor`, which panics with "not
  implemented" in 0.7). `tools/unoq` detects the version and uses full app paths.
- **The bundled Bridge library (0.2.2) needs MsgPack 0.4.2, DebugLog 0.8.4, ArxContainer 0.7.0 and
  ArxTypeTraits 0.3.2.** These aren't on the board and can't be downloaded offline. They were
  copied from the laptop's `~/.arduino15/internal/` to the board's (same folder names) with
  `adb push`. Sketches list them in `sketch.yaml` in the **plain** form `- MsgPack (0.4.2)`, because
  0.7 rejects `- dependency: …`. This only matters when App Lab builds on the board (DI-20).
- **`adb shell` sets `TMPDIR=/data/local/tmp`** (an Android path that doesn't exist here), so
  builds fail. `tools/unoq` exports `TMPDIR=/tmp`.
- **The `arduino` user's password has never been set** ("password must be changed"). `cron` jobs
  are refused, and `sudo` and SSH need it. Set it once: `adb shell` → `passwd`.
- **Option:** connect the board to Wi-Fi and run `arduino-app-cli system update` to get current
  versions. That needs internet and the password.

---

## DI-20 Sketch upload to the MCU fails
**Status:** Mitigated (root cause found) · **Severity:** High · **Logged:** 2026-11-21

**Symptom.** Every sketch upload from App Lab on the board compiles, then fails in OpenOCD:
"clearing lockup after double fault / error waiting for target flash write algorithm / block write
failed … at offset 0x000f0000".

**Root cause:** a version mismatch, not a faulty chip.
- **The chip's bootloader is from board package 1.1.0.** It runs Zephyr v4.4.2 and is
  byte-identical to the 1.1.0 package's bootloader image.
- **The board's App Lab still builds and flashes with package 0.52,** which targets the older Zephyr
  v4.2.0 bootloader, flashes with the wrong halt sequence (`reset` then `halt`, after the bootloader
  has started), and writes sketches to 0x080F0000 instead of 1.1.0's 0x08100000.

**Read-only diagnostic** (`openocd` on the board): SWD works; no lockup; CFSR/HFSR = 0; flash
controller error-free; RDP 0; TrustZone off; no write protection.

**Working route (automatic in `tools/unoq`):**
- Build the sketch **on the laptop** with package 1.1.0 and upload it with the official 1.1.0
  procedure over USB (`tools/unoq flash`).
- Run the Python side as a Python-only App Lab app.
- `tools/unoq` picks this route by itself when the board's package differs from the laptop's.
- Verified with a test sketch: 100 samples/s reached Python over the Bridge.

**Permanent fix:** update the board's software online (`arduino-app-cli system update`, needs the
password and Wi-Fi), so App Lab builds with a package that matches the bootloader.

**Update 2026-11-22: Python → MCU calls work too.** `Bridge.call("show", state, value)` from Python
to a `Bridge.provide_safe` function in the sketch is confirmed (flashguard's LED matrix). One
gotcha: calls fail with "method show not available" until the new sketch is flashed, so start
Python before flashing and retry.

---

## DI-22 Decision: the Modulino Light is the only light sensor
**Status:** Resolved · **Severity:** High · **Logged:** 2026-11-21

**Decision.** The device uses the **Modulino Light** for flicker and colour, and nothing else. We
accept its limits (DI-01): correct frequency around 3–15 Hz, folded but still detected up to about
35 Hz.

Other light sensors were evaluated on the real board and dropped, together with heart-rate
sensing. The seizure-response side uses motion only (DI-08). Their test apps, rig and log entries
(DI-06, DI-07, DI-16, DI-17, DI-21) were removed from the repo. They remain in git history at
commit `65e6c7f`.

**Next step.** Characterise the Modulino Light with `apps/light-test` (rig: `hardware/light-test`)
and use the measured usable band in the pitch and the light model.

---

## DI-23 Running the Edge Impulse models offline on the UNO Q
**Status:** Mitigated (both models run on the board; live end-to-end test pending) · **Severity:** High · **Logged:** 2026-11-21

**Update 2026-11-22.**
- **Flicker model** (project 1170128):
  - trained with `tools/ei/ei.py train` (Admin key);
  - **97.0% on 101 held-out test windows**: flicker 33/36 (3 "uncertain"), no_flicker 65/65, int8
    and float32 alike;
  - deployed as a Linux aarch64 `.eim` through the brick runner; about 30 ms per classification on
    the board.
- **Movement model** ("Wearable Movement Monitoring (More Classes)", teammate project 1170305;
  classes Running, Seizure, Sitting, Standing, Walking, Waving):
  - runs **on the MCU** from its exported Arduino library (vendored in
    `apps/flashguard/libraries/`);
  - builds for core 1.1.0 (191 KB flash, 82 KB RAM; the first build takes about 8 min) and takes
    **13 ms per classification**;
  - input is identical to its training recipe (`MovementSensor.txt`): accX/Y/Z in g and gyrX/Y/Z in
    °/s at 4 Hz, a 10 s window, classified every 2.5 s. 1.01 g at rest, checked.
- **After-stimulus logic** in `apps/flashguard/python/main.py`: a flicker alert opens a 5 min
  watch window; P(Seizure) ≥ 0.6 for 5 s starts a 15 s countdown to the carer alarm.
- **Not yet done:** the live test with real flicker followed by acted shaking; the
  wearer-cancel button; alarm hardware.

**Decision: run the model on the Linux side, through an App Lab brick.**
- The board is offline, so nothing can be downloaded or installed (`edge-impulse-linux` needs
  internet).
- The board already has Arduino's `ei-models-runner:0.5.0` image (Edge Impulse's Linux runner).
  The `arduino:motion_detection` brick starts it with any `.eim` model, chosen through a brick
  variable in `app.yaml`:
  ```yaml
  bricks:
    - arduino:motion_detection:
        variables:
          EI_MOTION_DETECTION_MODEL: /home/arduino/.arduino-bricks/ei-models/flashguard.eim
  ```
- **Verified on the board:**
  - the runner loads a model from that path and serves it over HTTP on port 1337;
  - `MotionDetection(...).infer_from_features(list)` returns
    `{"result": {"classification": {label: 0..1}}}`;
  - the brick's own `_extract_classification()` gives percentage *strings*, so `apps/flashguard`
    parses the raw result instead.
- **Rejected for now: the MCU (Zephyr module).** Edge Impulse calls UNO Q support there
  "experimental"; it needs `west` and debugger flashing.
- Edge Impulse lists a deployment target named **"Arduino UNO Q"** (`arduino-uno-q`), plus
  "Linux (AARCH64)" (`runner-linux-aarch64`).

**Model input** (`apps/flashguard/python/features.py`, shared with the training tools):
- **Window:** 64 readings (about 1.77 s at 36 readings/s).
- **Preprocessing:** divide by the sensor gain, take the log (so brightness and distance become an
  offset), subtract the window mean.
- **Inference:** every 0.5 s on overlapping windows. The brick's own buffer uses non-overlapping
  windows, which would give a slower alert.

**Training data so far:** one ~7 min Collect session from the laptop screen (`tools/ei`).
- **Room light swamped the screen.** Flicker changed the total light by only 5–30%, so 32 windows too
  faint to count were dropped.
- **Uploaded:** 510 windows to project 1170128 (409 training, 101 test, split by segment).

**Problems:**
- **The API key in use has the `ingestion_deployment` role.** It can upload and download models, but
  can't create the impulse or train. Training needs an Admin key, or the Studio UI.
- **One window was uploaded twice** (a test upload; `x-disallow-duplicates` didn't catch it because
  Edge Impulse renames files). It's harmless; delete it with an Admin key.
- **Screen-only training data.** Real LED strobes, room-light changes and other screens should be
  added (Collect in a darker room with the sensor closer, plus real-world negatives).

**Next step:** train, deploy the `.eim`, then measure on the board: accuracy on the flicker page,
false alerts in room light, and time from onset to alert (T4). Plan: `docs/BRIEF.md`.

---

## DI-24 The Arduino_Modulino library stops sketches starting on our board
**Status:** Mitigated · **Severity:** High · **Logged:** 2026-11-22

**Problem.** With `Arduino_Modulino` 0.7.0 (`Modulino.begin(Wire1)` + `ModulinoMovement`), a
sketch built with board package 1.1.0 flashes fine but never sends anything, not even its first
`Bridge.notify` from `setup()`. Bisected on the board:
- the same sketch with the Edge Impulse library removed is still silent;
- the previous sketch without the Modulino library runs (36 readings/s).

The exact cause inside the library wasn't investigated. `sensor-stream` (now in `archive/`) uses
this library too, so it probably has the same problem (DI-15).

**Decision.** Read the Modulinos through their registers on `Wire1`, as already done for the
Modulino Light (DI-02). For the Modulino Movement (LSM6DSOX at 0x6A), the settings and scaling are
copied from `Arduino_LSM6DSOX`, which the Modulino library uses, so the data matches anything
recorded through it:
- CTRL2_G = 0x4C (gyro 104 Hz, 2000 °/s), CTRL1_XL = 0x4A (accel 104 Hz, ±4 g), CTRL7_G = 0x00,
  CTRL8_XL = 0x09;
- acceleration = raw × 4/32768 g, rotation = raw × 2000/32768 °/s.

See `apps/flashguard/sketch/sketch.ino` (`imuBegin`, `imuRead`).

**Next step.** If `sensor-stream` is ever needed again, port it to the same driver. For v0.1,
`flashguard` does the recording.

---

## DI-25 The sketch crashes after a power cycle (since the heart-rate start-up)
**Status:** Open (workaround: flash from the laptop) · **Severity:** High · **Logged:** 2026-11-22

**Problem.** Since the heart-rate and buzzer start-up was added to `apps/flashguard`, the MCU
sketch runs fine when flashed from the laptop, but after a power cycle it crashes on start-up:
- the red LED flashes;
- Python receives 0 readings;
- the Linux side starts normally.

The LED-matrix version before it did come back fine after a power cycle.

**Likely cause (not confirmed):** at power-on, `setup()` now probes three I2C buses (Wire, Wire2,
Wire1) and scans every address while the sensors may still be powering up. The crash happens before
the sketch can report anything.

**Workaround.** Keep the board powered during the demo; after a power cycle run `tools/unoq flash`
(~1 min).

**Fix to try.**
1. Do the heart-rate/buzzer detection a few seconds after boot, in `loop()`.
2. Probe only 0x57 and 0x1E, and drop the full bus scan.
3. Test with a real unplug and replug.

---

## Template

```
## DI-NN Short title
**Status:** Open · **Severity:** … · **Logged:** YYYY-MM-DD

**Problem.** What is wrong or limiting, with evidence (measurement, datasheet, library source).
**Options / Decision.** What we chose and why.
**Next step.** What closes this issue.
```
