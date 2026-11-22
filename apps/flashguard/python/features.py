"""Team 11 · flashguard · model input, shared by the board (main.py) and the laptop tools (tools/ei).

The Edge Impulse model sees one window of WINDOW Modulino Light readings (R, G, B). The same
preprocessing must be used for training and on the device, so it lives here only:
  1. divide by the sensor gain (readings at different gains become comparable),
  2. take the log, so brightness and distance become an offset and flicker becomes a relative change,
  3. subtract the window mean, so only the change within the window is left.
"""

import numpy as np

WINDOW = 64             # readings per window: about 1.77 s at the sensor's ~36 readings/s
INTERVAL_MS = 27.6      # measured reading interval (DI-01); the model is told this frequency
AXES = ("red", "green", "blue")
GAIN_X = (1, 3, 6, 9, 18)  # LTR-381RGB gain codes 0-4
FLOOR = 0.5             # added before the log (about 10 counts at gain x18) so darkness isn't noise-dominated


def preprocess(rgb, gain_x):
    """rgb: (WINDOW, 3) raw counts; gain_x: gain factor per reading (scalar or (WINDOW,)).
    Returns (WINDOW, 3) float32 features."""
    v = np.asarray(rgb, float) / np.asarray(gain_x, float).reshape(-1, 1)
    v = np.log(v + FLOOR)
    v -= v.mean(axis=0)
    return v.astype(np.float32)


def flatten(window):
    """Interleaved [r0, g0, b0, r1, g1, b1, ...], the layout Edge Impulse expects for time series."""
    return np.asarray(window, np.float32).reshape(-1).tolist()
