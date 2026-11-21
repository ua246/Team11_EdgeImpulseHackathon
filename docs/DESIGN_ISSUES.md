# Design issue log

Problems, limits and decisions found while building the device. Add an entry whenever something
changes the design, and update its status rather than deleting it: the history is useful for the
pitch and the Q&A.

**Status:** Open · Mitigated (worked around, needs a hardware check) · Resolved · Accepted
(known limitation, stated in the pitch) · Rule (constraint everyone must follow)
**Severity:** High (could sink the demo or the core claim) · Medium · Low

| ID | Issue | Area | Severity | Status |
|---|---|---|---|---|
| [DI-01](#di-01-modulino-light-tops-out-at-40-samples-per-second) | Modulino Light tops out at 40 samples/s | Sensing | High | Open |
| [DI-02](#di-02-modulino-light-library-blocks-for-50150-ms) | Modulino Light library blocks for 50–150 ms | Firmware | High | Mitigated |
| [DI-03](#di-03-modulino-light-has-a-fixed-i2c-address) | Modulino Light has a fixed I2C address | Hardware | Low | Accepted |
| [DI-04](#di-04-mcu--linux-link-is-only-115200-baud) | MCU ↔ Linux link is only 115200 baud | Firmware | Medium | Mitigated |
| [DI-05](#di-05-pin-voltages) | Pin voltages: 3.3 V logic, A0/A1 not 5 V tolerant | Hardware | High | Rule |
| [DI-06](#di-06-heart-beat-sensor-has-two-competing-jobs) | Heart beat sensor has two competing jobs | Hardware | Medium | Open |
| [DI-07](#di-07-heart-rate-is-unreliable-during-a-convulsion) | Heart rate is unreliable during a convulsion | Sensing | Medium | Accepted |
| [DI-08](#di-08-motion-only-detects-convulsive-seizures) | Motion only detects convulsive seizures | Clinical | Medium | Accepted |
| [DI-09](#di-09-no-real-seizure-data) | No real seizure data | ML | High | Accepted |
| [DI-10](#di-10-streams-have-different-sample-rates) | Streams have different sample rates | ML | Low | Resolved |
| [DI-11](#di-11-sensor-placement-pulls-in-two-directions) | Sensor placement pulls in two directions | Hardware | Medium | Open |
| [DI-12](#di-12-demo-safety-flashing-light-in-the-judging-room) | Demo safety: flashing light in the judging room | Demo | High | Rule |
| [DI-13](#di-13-bridge-deadlock-rule) | Bridge deadlock rule | Firmware | Medium | Rule |
| [DI-14](#di-14-eduroam-may-block-ssh-to-the-board) | eduroam may block SSH to the board | Tooling | Low | Mitigated |
| [DI-15](#di-15-tooling-not-yet-run-on-real-hardware) | Tooling not yet run on real hardware | Tooling | Medium | Open |
| [DI-16](#di-16-camera-instead-of-the-light-sensor) | Camera instead of the light sensor (Raspberry Pi camera / Pi 5) | Sensing | Medium | Resolved: not usable |
| [DI-17](#di-17-pi-5--camera-module-3-as-a-camera-front-end-for-the-uno-q) | Pi 5 + Camera Module 3 as a camera front-end for the UNO Q | Architecture | Medium | Open |
| [DI-18](#di-18-screens-hidden-fast-flicker-and-viewing-distance) | Screens: hidden fast flicker and viewing distance | Sensing | Medium | Open |

---

## DI-01 Modulino Light tops out at 40 samples per second
**Status:** Open · **Severity:** High · **Logged:** 2026-11-21

**Problem.** The LTR-381RGB on the Modulino Light needs at least 25 ms per reading: the fastest
settings in the Arduino_LTR381RGB library are 16-bit resolution (25 ms integration) and a 25 ms
repeat rate. That gives at most 40 samples/s, so frequencies above 20 Hz fold back to the wrong
value (aliasing). The flicker most likely to trigger seizures is 16–25 Hz (Epilepsy Society).

**What one sensor actually sees.** Each reading is the *average* light over its 25 ms, which also
weakens fast flicker:

| True flicker | Strength after 25 ms averaging | Seen as (1 sensor, 40/s) | Seen as (2 interleaved, 80/s) |
|---|---|---|---|
| 5 Hz | 97% | 5 Hz | 5 Hz |
| 10 Hz | 90% | 10 Hz | 10 Hz |
| 18 Hz | 70% | 18 Hz | 18 Hz |
| 20 Hz | 64% | 20 Hz | 20 Hz |
| 25 Hz | 47% | **15 Hz** | 25 Hz |
| 30 Hz | 30% | **10 Hz** | 30 Hz |
| 35 Hz | 14% | **5 Hz** | 35 Hz |
| 40 Hz | 0% (invisible) | — | — |
| 100 Hz (UK mains lighting) | 13% | **20 Hz** | **20 Hz** |

**So:**
- **One sensor still *detects* flicker from 3 Hz to about 35 Hz;** it just reports the wrong
  frequency above 20 Hz. That's enough for a yes/no warning.
- **It is not enough for the per-patient frequency range or for weighting the 16–25 Hz peak band.**
- **Ripple from mains-powered lights (100 Hz in the UK) can show up as a weak fake 20 Hz signal.**
  Ignore anything below a minimum brightness swing (the broadcast guidelines only count changes
  of about 10% or more).

**Options:**

| Option | Gets you | Cost / risk | Verdict |
|---|---|---|---|
| A. Fast analog light detector (heart beat sensor's detector, phototransistor or photodiode) on an analog pin at 200–1000 samples/s | Correct frequency across 3–60 Hz, no aliasing, no averaging loss | Need a part that responds to visible light; see DI-06 | **Preferred.** Test in hour one. Keep one Modulino Light for colour (red detection only needs 40/s) |
| B. Two Modulino Lights, half a period (12.5 ms) out of step | 80 samples/s merged: correct frequency up to about 35 Hz | Six sub-problems, below; about 2–3 h of work with hardware risk | Fallback if A fails and you have a second Modulino Light |
| C. Camera on the UNO Q (Arduino USB Camera, or Raspberry Pi Camera Module 2 via the UNO Media Carrier), exposure locked | Where and how much of the view is flashing, colour per region | The Arduino USB Camera tops out at **30 fps** (datasheet), so it identifies flicker only up to 15 Hz, worse than the Modulino Light. 105 g, needs the USB hub. See DI-16 | Not for frequency. Optional *context* sensor (how much of the view, red) |
| D. Accept one sensor | Flicker yes/no up to about 35 Hz | Frequencies above 20 Hz are wrong; the mains alias needs a swing threshold | Acceptable minimum for the demo |

**Option B in detail (two sensors, out of sync).** This is time-interleaved sampling, the same
trick fast oscilloscopes use with several slower converters. It works in principle, but:

1. **Same I2C address (DI-03).** Both sensors are fixed at 0x53, so they need separate buses. The
   UNO Q has three: `Wire1` (Qwiic connector), `Wire` (SDA/SCL header pins D20/D21) and `Wire2`
   (A4 = SDA, A5 = SCL). Connect the second Light with a Qwiic-to-jumper cable. The provided
   multi-port hub only helps if it contains a multiplexer chip (address 0x70, which the Modulino
   library supports as `ModulinoHub`); a passive hub just joins the wires.
2. **The clocks drift.** Each sensor runs on its own internal oscillator. Even a 1% difference
   moves the offset 0.25 ms per reading, so a 12.5 ms offset collapses to 0 within about a second,
   and then the pair is no better than one sensor. You need active phase control:
   - Timestamp every reading on the microcontroller.
   - Measure the offset between the two sensors continuously.
   - When the offset drifts, restart sensor B (switch it off and on via the MAIN_CTRL register) at
     the right moment.
   - Each restart costs one reading from B. Whether a restart lands cleanly needs testing.
3. **Averaging is unchanged.** Every reading is still a 25 ms average, so 25 Hz flicker arrives at
   47% strength, 30 Hz at 30%, and 40 Hz not at all. Interleaving fixes the *frequency* reading,
   not the sensitivity.
4. **Mains ripple still aliases.** 100 Hz shows up at 20 Hz with 80 samples/s as well. The brightness
   swing threshold is still needed.
5. **Unit mismatch.** Two sensors never read exactly the same, so the merged stream gets a fake
   zig-zag. That produces a false peak at 40 Hz, plus a mirror image of any real flicker
   (18 Hz real → small 22 Hz ghost). Normalise each sensor by its own running average before
   merging, and mount them side by side at the same angle so they see the same light.
6. **Bus time.** Polling two sensors fast enough to timestamp them needs the I2C buses at 400 kHz
   (the Modulino library sets 100 kHz), or the polling eats the time needed for the IMU and heart
   beat sampling.

**Next step.** Build the rig in `hardware/detector-test` and run `apps/detector-test`. A **PASS** on
A2 or A3 means choose option A and close this issue. The quick manual check still works too: the
flicker page at 5 / 15 / 25 Hz, reading the `~Hz` value in the `[stat]` line of `sensor-stream`.

---

## DI-02 Modulino Light library blocks for 50–150 ms
**Status:** Mitigated (needs a hardware check) · **Severity:** High · **Logged:** 2026-11-21

**Problem.** Each call to `ModulinoLight::update()` (via `LTR381RGBClass::readAllSensors`) switches
the sensor between colour and ambient mode and waits for data with `delay(50)`. Every call blocks
about 50–150 ms, which would stall the IMU and heart beat sampling and limit light to about 10/s.

**Decision.** `apps/sensor-stream/sketch/sketch.ino` doesn't call `update()`. It configures the sensor
once (continuous colour mode, 16-bit / 25 ms, gain ×3), checks the data-ready bit without waiting,
and reads the colour registers directly. The register map was taken from the library source.

**Check on hardware:** the `[stat]` line should show `LIGHT ~40/s`. If readings saturate in bright
light, lower the gain; if dim light reads near 0, raise it (register 0x05).

---

## DI-03 Modulino Light has a fixed I2C address
**Status:** Accepted · **Severity:** Low · **Logged:** 2026-11-21

The address is 0x53 and can't be changed, so two Lights can't share one bus. Only relevant to
DI-01 option B. Workarounds are separate buses (`Wire`, `Wire1`, `Wire2`) or a multiplexer hub.

---

## DI-04 MCU ↔ Linux link is only 115200 baud
**Status:** Mitigated · **Severity:** Medium · **Logged:** 2026-11-21

**Problem.** All Bridge traffic between the microcontroller and the Linux side (`Bridge.notify`,
`Monitor`/`Serial` prints) shares a 115200-baud UART (`arduino-router` on `/dev/ttyHS1`), which is
about 11 KB/s in total. Sending one message per sample at high rates would saturate it.

**Decision.** The sketch batches compact integer CSV text every 100 ms, about 3.3 KB/s for IMU at
50/s, light at 40/s and heart beat at 200/s. The MCU reports missed samples and its slowest send,
and Python prints `[warn]` if either looks bad.

**Rule.** Before adding a stream or raising a rate, estimate its bytes per second. For fast signals,
compute features on the microcontroller and send those instead of raw samples.

---

## DI-05 Pin voltages
**Status:** Rule · **Severity:** High · **Logged:** 2026-11-21

- Header pins use 3.3 V logic. Most digital pins tolerate 5 V, but **A0 and A1 do not**, and no pin
  may exceed 3.3 V while used as an analog input.
- Power analog sensors (the heart beat sensor is on A2) from **3.3 V**.
- Servos and motors take 5 V from the power bank, never from a pin, and share the board's ground.
- Kit LCDs are usually 5 V I2C devices: they need a level shifter before going on a 3.3 V bus.

Source: Arduino UNO Q full pinout (ABX00162).

---

## DI-06 Heart beat sensor has two competing jobs
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

The heart beat sensor is wanted both for **heart rate** (on the finger, earlobe or wrist) and as
the **fast light detector** for DI-01 option A (facing forward, LED covered). One unit can't do both.

**Plan:** you have more than one, so use one for each, each on its own analog pin, and test both
in hour one. The objective test is `apps/detector-test` (rig: `hardware/detector-test`). The UNO Q
flashes a test LED at 1–60 Hz into the module and grades it PASS / PARTIAL / FAIL, with the usable
frequency range and hints. If its detector is IR-only (dark lens), it may barely respond to LED or screen light;
then look for a phototransistor or photodiode instead.

**Gotchas for using it as a flicker detector:**
- **Cover or disconnect the module's own LED,** or its light swamps the room light.
- **Pulse-sensor style modules** (green LED with an amplifier) filter for heartbeats, around
  1–3 Hz, and may smooth out fast flicker. Test before relying on them.
- **Digital heart-rate / SpO2 sensors** (e.g. MAX3010x over I2C) deliberately cancel ambient light,
  so they can't be used as a room-light detector.
- **A light-dependent resistor (LDR) is too slow:** it takes tens of milliseconds to respond.
  Use a phototransistor or photodiode.
- **Mains ripple from room lights is 100 Hz in the UK,** which is exactly the limit of 200 samples/s.
  If mains ripple confuses the reading, sample at 500/s (about 4 KB/s on the Bridge, still within
  DI-04), or add an RC low-pass filter (e.g. 10 kΩ + 220 nF ≈ 70 Hz) in front of the pin.

---

## DI-07 Heart rate is unreliable during a convulsion
**Status:** Accepted · **Severity:** Medium · **Logged:** 2026-11-21

Optical heart-rate sensors are swamped by movement, so readings during rhythmic shaking are
garbage. **Decision:** motion is the primary seizure signal. Heart rate *before and after* the
shaking (a rise against the wearer's baseline) only confirms it.

---

## DI-08 Motion only detects convulsive seizures
**Status:** Accepted (state it in the pitch) · **Severity:** Medium · **Logged:** 2026-11-21

A motion sensor can detect tonic-clonic (convulsive) seizures. Absence seizures and small myoclonic
jerks, which are common in photosensitive epilepsy, need EEG and are out of scope. The response
side of the device targets convulsive seizures only.

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

IMU 50/s, light ≤40/s, heart beat 200/s. **Decision:** record one CSV per stream, and give each
Edge Impulse model only the streams it needs (light model: `light` + `hb`; seizure model:
`imu` + `hb`). Resample only if a model truly needs a merged input.

---

## DI-11 Sensor placement pulls in two directions
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

The light sensor must face forward near eye level (cap brim). The motion sensor works best on the
wrist or arm for convulsions. **Proposal:** cap for light; arm sleeve (provided) holding the UNO Q,
motion sensor and heart beat sensor; one Qwiic cable up to the cap. Check cable lengths and strain
relief.

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
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

The sketch compiles for the UNO Q, and the Python side passed a laptop test with simulated data.
Still untested on the board:
- write permissions on the app's `data/` folder (recording);
- the exact output format of `arduino-app-cli app logs` / `monitor`;
- that the board's Python can see `data/record.json` at the path the laptop writes it to.

Close this issue after the first successful `tools/unoq dev` plus a recording on the real board.

---

## DI-16 Camera instead of the light sensor
**Status:** Resolved: not usable · **Severity:** Medium · **Logged:** 2026-11-21

**Outcome.** The team's camera is a **Raspberry Pi Camera Module 3 (IMX708)**, which the UNO Q
doesn't support. Running it on the Pi 5 breaks the "runs on the UNO Q" rule. The camera route is
only reopened if the organisers can lend a **Camera Module 2 + UNO Media Carrier**, or if a kit USB
camera turns out to have a 60+ fps mode. Fast flicker sensing stays with the analog detector
(DI-01 option A).

**Arduino USB Camera (TPX00246), checked against its datasheet:**
- Sony IMX376 sensor with a rolling shutter. 80° diagonal field of view. USB 2.0, standard UVC.
- 250 mA, or 410 mA with the ring light on. 105 g, 70×40×90 mm.
- **30 fps maximum in every mode:**
  - MJPEG at 320×240 up to 3840×2160;
  - uncompressed YUY2 at 30 fps up to 720×480, falling to 10 fps at 720p and 5 fps at 1080p.

So it identifies flicker frequency only up to **15 Hz**. The 16–25 Hz peak band folds down to
5–14 Hz: still detectable as "flicker" if exposure is short, but at the wrong frequency.

**It works in a custom App Lab app without a Brick:**
`from arduino.app_peripherals.camera import Camera`, then
`Camera("usb:0", resolution=(320, 240), fps=30)`, `.start()`, `.capture()`
(Arduino example `06-camera-basics/01-simple-camera`).

**Unknown:** whether the camera lets you lock exposure. The datasheet only lists automatic
exposure, white balance and gain. Check on the board with `v4l2-ctl -d /dev/video0 --list-ctrls`.
Without a short fixed exposure, auto exposure smooths flashes: a 33 ms exposure cuts 25 Hz flicker
to about 20% strength.

**Verdict:** not a flicker-frequency sensor. It's useful only as a context sensor:
- what share of the view is flashing (to weight large flashes over a small blinking LED);
- whether the flashing is red.

Process 320×240 YUY2 frames into a coarse brightness grid; never store images. Mount it in the
chest holder (too heavy for a cap), and keep its ring light **off**.

**Question.** Could a camera (the team has a Raspberry Pi camera / Pi 5) detect flashing light
instead of the Modulino Light?

**Findings:**
- **Running the detection on a Raspberry Pi 5 is ruled out.** The brief says every project must run
  on the UNO Q, and judges score whether the model runs there. It would also mean wearing a second
  computer that wants a 5 V / 5 A supply.
- **Raspberry Pi cameras on the UNO Q** need the Arduino UNO Media Carrier (a separate board with
  two 22-pin MIPI-CSI connectors).
  - Only Sony IMX219 cameras (Raspberry Pi Camera Module 2) are supported so far. Camera Module 3
    (IMX708), HQ and Global Shutter cameras are not.
  - Module 2 needs a 22-to-15-pin ribbon cable; the cable sold for the Pi 5 is that cable.
  - Set-up: `sudo arduino-linux-config hw enable media-carrier camera0=type1-2lanes`, then reboot.
    Source: Arduino App Lab docs, "MIPI-CSI Camera".
- **Frame rate decides it.** A camera can only identify flicker up to half its frame rate:
  - 30 fps → 15 Hz, which misses the 16–25 Hz peak band;
  - 60 fps → 30 Hz;
  - 90+ fps → 45 Hz and above.

  On a Raspberry Pi the Module 2 is rated up to about 200 fps at 640×480. Which modes the UNO Q's
  camera driver offers is unknown.
- **Required settings:**
  - fixed exposure of 5 ms or less;
  - auto exposure, auto white balance and anti-flicker ("power line frequency") turned off;
  - low resolution.

  Otherwise the camera smooths the flashes out itself.

**What a camera adds:**
- *How much* of the view is flashing. Broadcast guidance treats flashes covering a large share of
  the screen (about a quarter) as the hazard, so a small blinking LED could be ignored.
- *Where* the flashing is, and colour per region (red flashes).
- A pitch point: shrink every frame to a coarse grid of brightness values (e.g. 8×6) immediately
  and never store images. It becomes a privacy-preserving 48-pixel light meter.
- No Bridge bottleneck (DI-04), because the camera connects to the Linux side directly.

**Costs:**
- setup time;
- a custom App Lab app may need extra configuration to reach the camera (the built-in camera Bricks
  have it);
- CPU load at high frame rates;
- bystander privacy;
- power.

**Next step.** A 15-minute test on the board:
1. List the camera's modes with `v4l2-ctl --list-formats-ext` (package `v4l-utils`).
2. Capture a few seconds at the fastest mode with exposure locked, while the flicker page runs at
   25 Hz.
3. Check that the frame-brightness signal shows 25 Hz.

If 60+ fps works, the camera can replace the Modulino Light as the flicker sensor.

---

## DI-17 Pi 5 + Camera Module 3 as a camera front-end for the UNO Q
**Status:** Open (needs the organisers' OK) · **Severity:** Medium · **Logged:** 2026-11-21

**Idea.** The Pi 5 captures and shrinks frames; the UNO Q does all the analysis and runs the Edge
Impulse model.

**Constraints:**
- **Never send full images.** At 120 fps, full Camera Module 3 frames (1536×864) are about
  240 MB/s, far beyond Wi-Fi or USB. Even 30 fps is about 60 MB/s.
- **Send tiny frames instead.** The Pi's image processor can produce a second, low-resolution
  stream for free (picamera2 `lores`). 64×48 YUV420 is 4.6 KB per frame, about 0.55 MB/s at
  120 fps. That's fine over USB or Wi-Fi.
- **Send them to the UNO Q's Linux side,** never through the microcontroller. The Bridge is a
  115200-baud UART (~11 KB/s, DI-04), which can't carry images.
- **Link options:**
  1. **USB cable, Pi → UNO Q:** the Pi runs `adb forward` exactly like the laptop does, then sends
     over a local TCP socket. No Wi-Fi needed.
  2. **Wi-Fi:** the Pi runs a hotspot and the UNO Q joins it. eduroam usually blocks
     device-to-device traffic (DI-14).
- **Camera settings on the Pi:** 1536×864 at 120 fps; fixed exposure of 5 ms or less; auto
  exposure, auto white balance and anti-flicker off. Timestamp every frame on the Pi.

**What it gives:**
- Correct flicker frequency up to 60 Hz.
- How much of the view is flashing, where, and colour per region.

**Against it:**
- **Rules.** "Every project must run on the UNO Q": the model would, but judges may ask why the
  Pi isn't doing the work. Ask the organisers before building.
- **Wearability.** Two computers and two power banks; the Pi 5 draws about 4–7 W.
- **Effort.** About 2–3 h: a Pi capture script, the link, and a receiver in the UNO Q app.
- **Two-device demo.**

**Decision rule.** Go ahead only if (1) the organisers allow it, and (2) the analog fast-detector
test (DI-01 option A) fails, or the team specifically wants the "how much of the view is flashing"
feature.

---

## DI-18 Screens: hidden fast flicker and viewing distance
**Status:** Open · **Severity:** Medium · **Logged:** 2026-11-21

**Flashes in video content are in range.** A video can change at most once per frame, so its
fastest flash is half the frame rate: 12–15 Hz for 24/25/30 fps content, 25–30 Hz for 50/60 fps
(games, sport). All of that is inside the 3–30 Hz band, and well inside what the fast detector
reads correctly at 200 samples/s (up to about 80–100 Hz).

**Hidden fast flicker from screens can fake a flash.** Screen refresh (60–240 Hz) and especially
backlight / OLED brightness dimming (PWM, often 200 Hz to several kHz, deep on dimmed screens) is
not the seizure risk, but it can **alias** into the band. Examples:
- 220 Hz sampled at 200/s looks like 20 Hz;
- 480 Hz sampled at 500/s also looks like 20 Hz.

Sampling faster alone doesn't fix this. **Mitigation:** an RC low-pass filter in front of the
analog pin. One stage of 10 kΩ + 220 nF (about 70 Hz) cuts 480 Hz to about 14%; two stages cut it
to about 2%. Keep the minimum-brightness-swing threshold too. **Test** against a phone or laptop
screen at low brightness, where PWM is strongest.

**Distance: it's about share of view, not metres.** A single detector measures *all* the light in
its field of view. The flicker signal is the flashing source's share of that light, so it falls with
distance, smaller screens and brighter rooms. That matches the usual advice for people with
photosensitive epilepsy (watch in a well-lit room, sit further back, use smaller screens), so the
reading scales roughly the way the risk does.

**To aim it where the wearer looks,** put the detector at the end of a short black tube (a straw
wrapped in tape). That narrows its view, so a screen in front fills more of it and room lights less.

**Very short strobe flashes can fall between readings.** The fast detector takes an *instant*
reading every 5 ms, so a xenon-style flash lasting under 1 ms is usually missed. Phone-torch and
most LED strobes stay on long enough. If it matters:
- the RC filter above stretches short flashes so they get caught; or
- take several quick readings per sample on the MCU and keep the highest.

**Next step.** Measure the brightness swing with the flicker page on a laptop and a TV at 0.5, 1, 2
and 3 m, in a dim and a lit room, with and without the tube. The `swing NN%` value in the `[stat]`
line for `LIGHT` and `HB` shows it directly. Set the alert threshold from that data.

---

## Template

```
## DI-NN Short title
**Status:** Open · **Severity:** … · **Logged:** YYYY-MM-DD

**Problem.** What is wrong or limiting, with evidence (measurement, datasheet, library source).
**Options / Decision.** What we chose and why.
**Next step.** What closes this issue.
```
