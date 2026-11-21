# Flicker Guard

Is fast flickering light (3–30 Hz) present? An **Edge Impulse model running on the UNO Q** answers
this from the Modulino Light, fully offline.

```sh
UNOQ_APP=flicker-guard tools/unoq dev     # first start: flashes the sketch from the laptop (DI-20)
UNOQ_APP=flicker-guard UNOQ_NO_SKETCH=1 tools/unoq restart   # restart Python + model runner only
```

## How it works

- **Sketch:** streams every reading (R, G, B, gain) to Python, about 36 per second. It sets the gain
  automatically: one step down at once above 85% of full scale, one step up after 3 s below 8%.
- **Model runner:** the `arduino:motion_detection` brick (`app.yaml`) starts Arduino's
  `ei-models-runner` container, which is already on the board. It serves our own `.eim` model from
  `/home/arduino/.arduino-bricks/ei-models/flicker-guard.eim` over HTTP. An inference call was
  checked on the board (with a placeholder model); the response is
  `{"result": {"classification": {label: 0..1}}, ...}`. Inference time is still to be measured.
- **Python** (`python/main.py`):
  - every 0.5 s, takes the last 64 readings (about 1.77 s);
  - preprocesses them with `features.py`: divide by the gain, take the log, subtract the window mean;
  - asks the model for P(flicker);
  - raises an alert when P ≥ 0.8 in 2 of the last 3 windows;
  - also prints a rule-based baseline (brightness swing + strongest frequency) once a second.
- **Recording:** every reading also goes to `data/recordings/flicker.<time>.csv`. That's the training
  data (see [tools/ei](../../tools/ei/README.md)).

The same preprocessing (`features.py`) is used for training and on the board. **If you change
`WINDOW` or the preprocessing, re-upload the data and retrain.**

## Output

```
[stat]  36/s x18 G    517 ▁█▁█▁█▁█ swing  87% ~10.0Hz  rule: flicker
[ei] flicker 0.97 ██████████ no_flicker 0.03 → ⚠ FLICKER (4 ms)
[alert] fast flickering light detected
```

Until our model is deployed, the runner holds a placeholder: a copy of the bundled up/down-wave
motion model. In that state the app says "not a flicker model: recording only" and just records.

## Status (2026-11-21)

- Streaming, auto-gain, recording and the runner path are verified on the board.
- The training data is recorded and uploaded to Edge Impulse (510 windows).
- Model training and deployment are still to do; see [docs/BRIEF.md](../../docs/BRIEF.md).
