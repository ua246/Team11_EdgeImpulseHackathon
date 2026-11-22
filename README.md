# FlashGuard (Team 11)

A wearable for people with photosensitive epilepsy, built on the Arduino UNO Q with two Edge Impulse
models running on the board, offline:
- it **warns** the wearer about seizure-provoking flickering light;
- if seizure-like movement follows, it **counts down to a carer alarm**.

The state shows on the board's LED matrix.

**Current version: [v0.1, the first working model](docs/RELEASE_v0.1.md)** · design:
[PROJECT_SPEC](docs/PROJECT_SPEC.md) · status and plan: [BRIEF](docs/BRIEF.md) · decisions and problems:
[DESIGN_ISSUES](docs/DESIGN_ISSUES.md)

## Quick start

1. Install adb (`sudo pacman -S android-tools` / `sudo apt install adb`), plug in the UNO Q, and run
   `tools/unoq doctor`.
2. Open this folder in VSCodium and accept the recommended extensions.
3. Press **Ctrl+Shift+B**, or run `tools/unoq dev`. This builds the sketch on the laptop, flashes it,
   starts `apps/flashguard`, and shows the output.
   - The first build takes ~8 min (Edge Impulse SDK); later builds take ~1 min.
4. Live test: open `tools/flicker.html`, show 10 Hz to the Modulino Light (dim room, 2–5 cm), then
   shake the Modulino Movement. See [apps/flashguard](apps/flashguard/README.md).

Full board workflow: [docs/UNOQ_DEV.md](docs/UNOQ_DEV.md).

## Repo layout

```
apps/
  flashguard/           THE PRODUCT (App Lab app)
    python/             Linux side: flicker model, after-stimulus logic, LED control, logging
    sketch/             MCU side: sensors, movement model, LED matrix
    models/             pinned models + model cards (flicker .eim, movement recipe)
    libraries/          movement model (Edge Impulse Arduino library)
  light-test/           sensor characterisation test (LED rig or screen sweep)
tools/
  unoq                  board CLI: dev, push (+ model), flash, logs, pull, autostart, doctor
  ei/                   Edge Impulse pipeline: Collect schedule, labelling, upload, train, deploy
  flicker.html          flicker test page: manual rates, Sweep (light-test), Collect (training data)
  pretty.py, stubs/     output formatting; editor stubs for the board's Python modules
hardware/light-test/    KiCad test rig (UNO Q + Modulino Light + test LED)
docs/                   spec, release notes, brief, design issue log, board guide
archive/                apps not part of v0.1 (kept for reference)
```

The training recordings (`recordings/`) and build output (`build/`) are git-ignored. The training
data lives in Edge Impulse project 1170128.
