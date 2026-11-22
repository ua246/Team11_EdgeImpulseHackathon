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

- **Sketches are built on the laptop and flashed over USB** (board package 1.1.0; the board's own
  App Lab can't flash, DI-20). `start`, `restart` and `dev` do it automatically. A first build of
  `flicker-guard` takes ~8 min (Edge Impulse SDK); later builds take ~1 min.
- **`UNOQ_NO_SKETCH=1 tools/unoq restart`** restarts only Python and the model runner.
- **`tools/unoq push` also installs a pinned model** (`apps/<app>/models/<app>.eim`) when it changed.
- **Compile errors become clickable entries in the Problems panel.**
- **Every output stream is also saved to `logs/`,** which is useful after a demo.
- **`tools/unoq autostart`** makes the app start at power-up (set for `flicker-guard` on our board).

**Which app and which link:** these are set in `.vscode/settings.json` (`unoq.app`, default
`flicker-guard`; `unoq.host`), or with `UNOQ_APP` / `UNOQ_HOST` in the terminal. To use SSH over
Wi-Fi instead of USB, set the host to `arduino@<board-name>.local`. eduroam often blocks
device-to-device traffic; use USB there.

## Reading the output (flicker-guard)

```
[stat]  36/s x18 G   6774 █▆▂▅█▅▁▅ swing  87% ~10.0Hz  rule: flicker · movement 4/s · monitoring
[ei] flicker 0.97 ██████████ → ⚠ FLICKER (31 ms)
[move] Seizure 0.02 (top: Standing) · Standing 0.97 · ... · watch 4:12 left (model 13.0 ms on the MCU)
[alert] … / [watch] … / [led] …
```

- **`[stat]`, once a second:**
  - light readings per second (~36), sensor gain, green level, a sparkline of the last ~1.8 s;
  - `swing`: how much dimmer the dark phase is than the bright phase. Steady light reads a few
    percent; full flashing 80–100%;
  - `~10.0Hz`: the strongest flicker frequency, shown when it stands out. True up to about 15 Hz,
    folded above (DI-01);
  - `rule`: the rule-based baseline's verdict;
  - movement samples per second (4);
  - the phase: monitoring, exposure, or watch with the time left.
- **`[ei]`, every 0.5 s:** the Edge Impulse flicker model's P(flicker). An alert needs ≥ 0.8 in 2 of
  the last 3 windows.
- **`[move]`, every 2.5 s:** the movement model's classes from the MCU.
- **`[alert]` / `[watch]` / `[led]`:** state changes, also logged to `events.<time>.csv` and shown
  on the LED matrix.
- **Colours:** `[alert]` is red background, `[warn]` yellow, `[rec]` magenta; errors are red.

**If `[stat]` shows `swing 1% steady` while the flicker page runs,** the flicker isn't reaching the
Modulino Light: move it closer to the screen and dim the room.

## Recording data for Edge Impulse

`flicker-guard` records all the time, to `data/recordings/` on the board:

| File | Rate | Columns |
|---|---|---|
| `flicker.<time>.csv` | ~36/s | t_ms, red, green, blue, gain_x |
| `movement.<time>.csv` | 4/s | timestamp, accX/Y/Z (g), gyrX/Y/Z (°/s), same as the movement model's training data |
| `events.<time>.csv` | on change | time, event, detail |

Copy them with `tools/unoq pull` (→ `recordings/flicker-guard/`). Labelled flicker training data
comes from `tools/flicker.html` → **Collect**, then `tools/ei/make_dataset.py`, `ei.py upload`,
`ei.py train`, `ei.py deploy` (see `tools/ei/README.md`). `recordings/` is git-ignored; datasets
live in Edge Impulse.

## Repo layout

See [README.md](../README.md#repo-layout).

## Hardware notes

Checked against Arduino's docs and the library source code. The full list of problems, limits and
decisions is in [DESIGN_ISSUES.md](DESIGN_ISSUES.md).

- **Qwiic connector = `Wire1`**, not `Wire`.
- **Don't use the Arduino_Modulino library with board package 1.1.0:** sketches using it never start
  on our board (DI-24). Read the Modulinos' registers instead; `apps/flicker-guard` has drivers for
  the Light and the Movement.
- **Modulino Light maxes out at 40 Hz:** the sensor needs at least 25 ms per reading. The library's
  `ModulinoLight::update()` also blocks for about 50–150 ms per call, which would stall everything
  else, so the sketches read the sensor's registers directly. Flicker frequency is read correctly
  only up to about 15–20 Hz; faster flicker folds to a lower frequency (DI-01, tested by
  `apps/light-test`).
- **The microcontroller ↔ Linux link is a 115200-baud UART,** about 11 KB/s in total, shared by
  all Bridge traffic. Send batches, keep messages small, and watch for `[warn]` lines.
- **Voltages:** header pins are 3.3 V logic. **A0/A1 are not 5 V tolerant,** and no pin may exceed
  3.3 V while used as an analog input. Power any analog sensor from 3.3 V.
- **`Serial.print()` and `Monitor.print()`** both appear in the MCU monitor (Zephyr core 0.55 and later).
- **Never call `Monitor.print()` or `Bridge.call()` inside a function registered with
  `Bridge.provide()`.** It can deadlock; use `Bridge.provide_safe()` instead.

## Status of this setup

Verified on our board (App Lab 0.7, laptop board package 1.1.0) as of v0.1 (2026-11-22):
- push, laptop flashing, logs and pull;
- Bridge messages both ways;
- the brick runner with a custom model;
- start at power-up.

Known board quirks are in `docs/DESIGN_ISSUES.md` (DI-19, DI-20, DI-24).
