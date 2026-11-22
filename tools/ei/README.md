# Edge Impulse pipeline (flicker model)

From a labelled recording to a model on the board. Needs Python with `numpy` and `requests` on the
laptop.

| Step | Command | Status |
|---|---|---|
| 1. Schedule | `python3 tools/ei/collect_schedule.py` → `tools/collect-schedule.js` | done |
| 2. Record | run `apps/flashguard`; open `tools/flicker.html` → **Collect (training data)**, ~7 min | done (1 session) |
| 3. Pull | `UNOQ_APP=flashguard tools/unoq pull` → `recordings/flashguard/flicker.<time>.csv` | done |
| 4. Label | `python3 tools/ei/make_dataset.py <csv>` → `dataset.<time>.json` | done |
| 5. Upload | `python3 tools/ei/ei.py upload <dataset.json>` | done (509 windows) |
| 6. Train | `python3 tools/ei/ei.py train [cycles]` (Admin key): impulse, spectral features, Keras, test-set evaluation | done: **97.0%** on 101 test windows (flicker 33/36, 3 uncertain; no_flicker 65/65) |
| 7. Deploy | `python3 tools/ei/ei.py deploy` → `build/flashguard.eim`, then `adb push build/flashguard.eim /home/arduino/.arduino-bricks/ei-models/` and `UNOQ_APP=flashguard UNOQ_NO_SKETCH=1 tools/unoq restart` | done, running on the board (~30 ms per classification) |

**API keys:** read from `$EI_API_KEY`, else `~/.config/flashguard/ei-admin-key` (Admin: needed to
train), else `~/.config/flashguard/ei-api-key` (`ingestion_deployment`: upload and deploy only).
Never commit them. Project: 1170128.

## The Collect schedule (`collect_schedule.py`)

- **Start:** a sync block (3 s black, 3 s white, 2 s black).
- **48 shuffled 7 s segments:**
  - 24 **flicker**: 3–30 Hz square waves in white, red, blue and green, and at lower contrasts
    (white/grey, grey/black, dark grey/black);
  - 24 **no_flicker**: steady colours, slow blinks at 0.5–2 Hz, slow fades, irregular level steps.
- **End:** 60 s of room light (the user points the sensor around the room), labelled
  **no_flicker**.

## Labelling (`make_dataset.py`)

- **Finding the session:** it slides the schedule's expected screen brightness along the recording
  and takes the best correlation. This works even when room light swamps the screen (match 0.84 on
  the first real session).
- **Windows:** 64 readings each, cut every 18 readings inside each segment. The segment edges are
  trimmed (3 s at the start of the room minute).
- **Skipped windows:** a gain change, a gap, saturation, or flicker windows with less than 3%
  brightness swing (too faint to count).
- **Test split by segment:** every 5th segment, plus the last 20% of the room minute. Overlapping
  windows are never split between training and test.
- **Tested** on a simulated session (60 Hz screen, pixel lag, 36 readings/s) and the real one.

## Training settings (what `ei.py train` sets up)

| Setting | Value |
|---|---|
| Time series input | window **1767 ms** (64 readings at 27.6 ms: 1766.4 ms rounds down to 63), window increase 1767 ms, frequency 36.23 Hz, zero-pad on |
| Processing | **Spectral Analysis** on red, green, blue. FFT length 64, no filter (the window mean is already removed), take log of spectrum on |
| Learning | **Classification** (Keras), small dense network, default settings first |
| Check | `input_features_count` in the downloaded model must be 192 (= 64 × 3); `main.py` refuses a mismatch |

Deployment target: **"Arduino UNO Q"** (`arduino-uno-q`) or **"Linux (AARCH64)"**
(`runner-linux-aarch64`). Both are listed for this project.
