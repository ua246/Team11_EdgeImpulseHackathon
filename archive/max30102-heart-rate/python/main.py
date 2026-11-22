from collections import deque
from statistics import median
from threading import Lock
from time import monotonic, sleep

from arduino.app_utils import Bridge

RATE = 100
WINDOW = 800
MIN_IR = 5000
samples = deque(maxlen=WINDOW)
lock = Lock()
next_index = None
last_update = None
sensor_status = "Waiting for sensor data"


def receive(batch: str):
    global next_index, last_update
    index, *values = map(int, batch.split(","))
    with lock:
        if index != next_index:
            samples.clear()
        samples.extend(values)
        next_index = index + len(values)
        last_update = monotonic()


def status(message: str):
    global sensor_status
    with lock:
        sensor_status = message


def estimate(values):
    level = median(values[-RATE:])
    if level < MIN_IR:
        return "Place a fingertip gently over the sensor"
    if max(values[-RATE:]) >= 260000:
        return "Signal saturated. Reposition your finger"
    if len(values) < WINDOW:
        return "Collecting pulse signal. Hold still"

    # Smooth the optical signal, then remove slow drift with a local baseline.
    prefix = [0]
    for sample in values:
        prefix.append(prefix[-1] + sample)
    signal = [
        (prefix[i + 3] - prefix[i - 2]) / 5
        - (prefix[i + 36] - prefix[i - 35]) / 71
        for i in range(35, len(values) - 35)
    ]
    ranked = sorted(signal)
    spread = ranked[int(0.9 * len(ranked))] - ranked[int(0.1 * len(ranked))]
    if spread < 12:
        return "Weak pulse signal. Reposition your finger"

    # Require spaced peaks and consistent intervals before reporting BPM.
    peaks = []
    threshold = median(signal) + 0.25 * spread
    for i in range(1, len(signal) - 1):
        if signal[i] <= threshold or not (signal[i - 1] < signal[i] >= signal[i + 1]):
            continue
        if not peaks or i - peaks[-1] >= 30:
            peaks.append(i)
        elif signal[i] > signal[peaks[-1]]:
            peaks[-1] = i

    intervals = [b - a for a, b in zip(peaks, peaks[1:])]
    if len(intervals) < 3:
        return "Looking for a steady pulse. Hold still"
    period = median(intervals)
    matching = sum(abs(gap - period) <= 0.2 * period for gap in intervals)
    if not 30 <= period <= 150 or matching < max(3, 0.75 * len(intervals)):
        return "Pulse signal unstable. Hold still"
    return f"{60 * RATE / period:.0f} BPM  |  IR level {level:.0f}"


Bridge.provide("pulse_samples", receive)
Bridge.provide("pulse_status", status)
print("MAX30102 Heart Rate", flush=True)
while True:
    with lock:
        snapshot = list(samples)
        age = monotonic() - last_update if last_update is not None else float("inf")
        message = sensor_status
    print(estimate(snapshot) if snapshot and age < 2 else message, flush=True)
    sleep(1)
