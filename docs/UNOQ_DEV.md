# UNO Q development setup (VSCodium)

Edit code on the laptop, push it to the Arduino UNO Q, and watch the Python and microcontroller
output side by side, all from VSCodium or one terminal command (`tools/unoq`).

## One-time setup

1. **Install adb** (talks to the board over USB-C):
   - Arch / CachyOS: `sudo pacman -S android-tools`
   - Debian / Ubuntu: `sudo apt install adb`
   - macOS: `brew install android-platform-tools`
2. **Linux USB permission:** a udev rule for Arduino's vendor ID `2341`, as in
   [Arduino's Linux setup guide](https://docs.arduino.cc/software/app-lab/setup/linux/).
3. **Board first-run:** set the board up once with Arduino App Lab (name, password, Wi-Fi).
   USB/adb works without this step; SSH needs it.
4. **Open the repo in VSCodium** (`codium .`) and accept the recommended extensions.
5. **Optional, for fast compile checks and C++ autocomplete:** install the UNO Q core once
   (`arduino-cli core install arduino:zephyr`, about 400 MB), then run the task
   **UNO Q: compile check (laptop)**. `tools/unoq` also finds the `arduino-cli` bundled with
   the Arduino IDE.
6. Plug in the board, wait up to a minute after power-on, then run `tools/unoq doctor`.

## Everyday loop

| Do | VSCodium | Terminal |
|---|---|---|
| Push, restart, watch output | **Ctrl+Shift+B** | `tools/unoq dev` |
| Python output only | Task: UNO Q: Python logs | `tools/unoq logs` |
| Sketch output (`Serial` / `Monitor`) | Task: UNO Q: MCU monitor | `tools/unoq monitor` |
| Check the sketch compiles (no board needed) | Task: UNO Q: compile check (laptop) | `tools/unoq compile` |
| Shell on the board | Task: UNO Q: shell | `tools/unoq shell` |

Run tasks with **Ctrl+Shift+P → Tasks: Run Task**.

- **Restarting compiles the sketch on the board,** which takes about a minute. The first start of
  an app also downloads containers.
- **Compile errors become clickable entries in the Problems panel.**
- **Every output stream is also saved to `logs/`,** which is useful after a demo.

**Which app and which link:** these are set in `.vscode/settings.json` (`unoq.app`, `unoq.host`),
or with `UNOQ_APP` / `UNOQ_HOST` in the terminal. To use SSH over Wi-Fi instead of USB, set the
host to `arduino@<board-name>.local`. eduroam often blocks device-to-device traffic; use USB there.

## Reading the output

```
15:13:18.192 PY  [stat] IMU 50/s |a| 1.00g ▇▂▄▇▇▃▅▆ │ LIGHT 40/s G 1500 red 29% ██▁▁██▁▁ swing 87% ~18.0Hz │ HB 200/s 900 ▄▄▁▁██▁▁ swing 83% ~25.0Hz
```

- **Rates (`/s`):** samples actually received per second. They should be about 50 / 40 / 200.
  "no data" means a sensor is missing; check the Qwiic cable.
- **Values:** `|a|` is total acceleration (about 1.00 g at rest). `G` is the light sensor's green
  channel (roughly brightness). `red` is the red share of the light. HB is the raw ADC value.
- **Sparkline:** the last 2 seconds of each signal.
- **`~18.0Hz`:** the strongest frequency, shown only when it clearly stands out.
  - Light covers 1–20 Hz.
  - The heart beat sensor channel covers 0.5–60 Hz, so a pulse shows as about 1–2 Hz. If its light
    detector sees flicker, that flicker frequency shows here instead.
- **`swing 83%`:** how much dimmer the dark phase is than the bright phase over the last 2 s.
  - Steady light reads a few percent.
  - Full on/off flashing reads 80–100%.
  - Mains ripple and distant screens read low, so use this to set the alert threshold.
  - `SAT` means the bright phase hit the top of the sensor's range: move or shade the sensor.
  - It's only meaningful when 0 means dark. A heart beat module with a built-in amplifier may
    centre its output mid-range instead.
- **Colours:**
  - `[warn]` (yellow) means samples were missed or the Bridge is slow.
  - `[rec]` (magenta) is recording status.
  - Errors are red.

## Recording data for Edge Impulse

1. Start the app (Ctrl+Shift+B).
2. Start a recording with the task **UNO Q: record…** or with `tools/unoq record <label> <seconds>`,
   e.g. `tools/unoq record flicker_18hz 30`. Stop early with `tools/unoq record stop`.
3. Copy the files to the laptop with `tools/unoq pull`. They land in `recordings/<app>/` as
   `<label>.<time>.<stream>.csv`, one file per stream:

   | Stream | Rate | Columns |
   |---|---|---|
   | `imu` | 50 Hz | timestamp (ms), accX/Y/Z (m/s²), gyrX/Y/Z (°/s) |
   | `light` | ≤40 Hz | timestamp (ms), red, green, blue (raw counts) |
   | `hb` | 200 Hz | timestamp (ms), hb (raw ADC) |

4. In Edge Impulse Studio go to **Data acquisition → Upload data**. The CSV Wizard uses the
   `timestamp` column, and the label is the part of the file name before the first dot.

The streams have different rates, so give each model its own streams (e.g. light model: `light` +
`hb`; seizure model: `imu` + `hb`), or resample before merging. `recordings/` is git-ignored;
share datasets through Edge Impulse.

## Repo layout

```
apps/sensor-stream/        App Lab app: comms test + data recorder (copy it to start a new app)
  app.yaml                 app manifest
  python/main.py           Linux side: receives data, prints status, records CSVs
  sketch/sketch.ino        MCU side: reads sensors, sends batches over the Bridge
  sketch/sketch.yaml       sketch libraries (Arduino_Modulino 0.7.0, as in Arduino's own examples)
apps/detector-test/        automated test: is the heart beat module fast enough for flicker? (PASS/PARTIAL/FAIL)
hardware/detector-test/    KiCad schematic + PDF + parts list for the detector test rig
tools/unoq                 command-line helper (adb or SSH)
tools/pretty.py            timestamps, colours and log files for board output
tools/stubs/               editor-only stubs for arduino.app_utils
.vscode/                   tasks, settings, recommended extensions
```

## Hardware notes

Checked against Arduino's docs and the library source code. The full list of problems, limits and
decisions is in [DESIGN_ISSUES.md](DESIGN_ISSUES.md).

- **Qwiic connector = `Wire1`**, not `Wire`. Call `Modulino.begin(Wire1)`.
- **Modulino Light maxes out at 40 Hz:** the sensor needs at least 25 ms per reading. The library's
  `ModulinoLight::update()` also blocks for about 50–150 ms per call, which would stall everything
  else, so `sketch.ino` reads the sensor's registers directly. Flicker above 20 Hz needs a faster
  sensor (see the heart beat sensor idea in the project brief).
- **The microcontroller ↔ Linux link is a 115200-baud UART,** about 11 KB/s in total, shared by
  all Bridge traffic. Send batches, keep messages small, and watch for `[warn]` lines.
- **Voltages:** header pins are 3.3 V logic. **A0/A1 are not 5 V tolerant,** and no pin may exceed
  3.3 V while used as an analog input. Power the heart beat sensor from 3.3 V. It is read on **A2**.
- **`Serial.print()` and `Monitor.print()`** both appear in the MCU monitor (Zephyr core 0.55 and later).
- **Never call `Monitor.print()` or `Bridge.call()` inside a function registered with
  `Bridge.provide()`.** It can deadlock; use `Bridge.provide_safe()` instead.

## Status of this setup

The sketch compiles for the UNO Q, and the Python side was dry-run on a laptop with simulated
sensor data (rates, frequency detection and recording all worked). **It has not yet run on a
real board,** so expect small fixes on the first run. Likely spots: file permissions on
`data/`, and the exact log format of `arduino-app-cli`.
