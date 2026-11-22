#include <Wire.h>
#include <MAX30105.h>


MAX30105 sensor;
constexpr uint8_t address = 0x57;
constexpr uint32_t minIR = 5000;
constexpr uint32_t maxIR = 260000;
constexpr uint16_t sampleRate = 100;
constexpr uint8_t intervalCount = 5;
constexpr int riseBpm = 15;  // Adjustable demo threshold above personal baseline.

bool ready = false;
uint16_t contactSamples = 0;
uint32_t sampleNumber = 0;
uint32_t lastBeat = 0;
uint32_t lastSampleMs = 0;
uint32_t ir = 0;
uint16_t intervals[intervalCount] = {};
uint8_t filled = 0;
uint8_t slot = 0;
int restingBpm = 0;
bool baselineRequested = false;
float smoothIR = 0;
float dcIR = 0;
float envelope = 0;
bool aboveThreshold = false;

void clearIntervals() {
  filled = 0;
  slot = 0;
  lastBeat = 0;
}

int estimateBpm(bool requireSteady) {
  if (!filled || sampleNumber - lastBeat > 180) return 0;
  if (requireSteady && filled < intervalCount) return 0;
  uint16_t sorted[intervalCount];
  for (uint8_t i = 0; i < filled; ++i) {
    uint8_t j = i;
    while (j > 0 && sorted[j - 1] > intervals[i]) {
      sorted[j] = sorted[j - 1];
      --j;
    }
    sorted[j] = intervals[i];
  }
  const int median = (sorted[(filled - 1) / 2] + sorted[filled / 2]) / 2;
  for (uint8_t i = 0; i < filled; ++i) {
    if (requireSteady && abs(int(sorted[i]) - median) * 5 > median) return 0;
  }
  return (60 * sampleRate + median / 2) / median;
}

void readSample(uint32_t value) {
  ir = value;
  ++sampleNumber;

  if (value < minIR || value >= maxIR) {
    contactSamples = 0;
    aboveThreshold = false;
    clearIntervals();
    return;
  }
  if (!contactSamples) {
    smoothIR = dcIR = value;
    envelope = 0;
    aboveThreshold = false;
  }
  smoothIR += 0.20f * (value - smoothIR);
  dcIR += 0.025f * (smoothIR - dcIR);
  const float pulse = smoothIR - dcIR;
  const float magnitude = pulse < 0 ? -pulse : pulse;
  envelope *= 0.995f;
  if (magnitude > envelope) envelope = magnitude;
  const float threshold = envelope * 0.35f > 10 ? envelope * 0.35f : 10;
  const bool beat = !aboveThreshold && pulse > threshold;
  if (beat) aboveThreshold = true;
  if (pulse < 0) aboveThreshold = false;

  if (contactSamples < 2 * sampleRate) {
    ++contactSamples;
    return;
  }
  if (lastBeat && sampleNumber - lastBeat > 180) clearIntervals();
  if (!beat) return;

  if (lastBeat) {
    const uint32_t gap = sampleNumber - lastBeat;
    if (gap < 30) return;
    intervals[slot] = gap;
    slot = (slot + 1) % intervalCount;
    if (filled < intervalCount) ++filled;
  }
  lastBeat = sampleNumber;
}

void setup() {
  Serial.begin(115200);
}

void loop() {
  if (!ready) {
    // UNO Q dedicated SDA/SCL header (D20/D21). A4/A5 uses Wire2.
    const bool found = sensor.begin(Wire, I2C_SPEED_STANDARD, address) ||
                       sensor.begin(Wire2, I2C_SPEED_STANDARD, address);
    if (!found) {
      Serial.println("MAX30102 not detected at 0x57. Check SDA/SCL, power and GND.");
      delay(2000);
      return;
    }
    // IR channel at 100 samples/s with no FIFO averaging.
    sensor.setup(0x24, 1, 2, sampleRate, 411, 4096);
    sensor.setPulseAmplitudeRed(0);
    ready = true;
    Serial.println("MAX30102 detected. Send r to save a resting BPM or c to clear it.");
  }

  if (sensor.check()) {
    const uint32_t now = millis();
    // The library's sample buffer is small. Reacquire after a polling stall.
    if (now - lastSampleMs > 250) {
      clearIntervals();
      contactSamples = 0;
    }
    lastSampleMs = now;
    while (sensor.available()) {
      readSample(sensor.getFIFOIR());
      sensor.nextSample();
    }
  }

  const bool streaming = millis() - lastSampleMs <= 250;
  const int bpm = streaming ? estimateBpm(true) : 0;
  while (Serial.available()) {
    const int command = Serial.read();
    if (command == 'r') {
      baselineRequested = true;
      if (!streaming || !estimateBpm(false)) {
        Serial.println("Baseline requested. Hold your finger still while beats are detected.");
      }
    } else if (command == 'c') {
      baselineRequested = false;
      restingBpm = 0;
      Serial.println("Resting baseline cleared.");
    }
  }

  if (baselineRequested && streaming) {
    const int baseline = estimateBpm(false);
    if (baseline) {
      restingBpm = baseline;
      baselineRequested = false;
      Serial.print("Resting baseline saved: ");
      Serial.print(restingBpm);
      Serial.println(bpm ? " BPM" : " BPM (provisional)");
    }
  }

  static uint32_t lastReport = 0;
  if (millis() - lastReport < 1000) {
    delay(1);
    return;
  }
  lastReport = millis();
  Serial.print("IR: ");
  Serial.print(ir);
  if (!streaming) Serial.println(" | No fresh samples");
  else if (ir < minIR) Serial.println(" | Place fingertip on sensor");
  else if (ir >= maxIR) Serial.println(" | Signal saturated, reposition finger");
  else if (!bpm) Serial.println(" | Hold still for a steady pulse");
  else {
    Serial.print(" | BPM: ");
    Serial.print(bpm);
    if (restingBpm) {
      Serial.print(" | Rest: ");
      Serial.print(restingBpm);
      Serial.print(" | Change: ");
      Serial.print(bpm - restingBpm);
      Serial.println(bpm >= restingBpm + riseBpm ? " | ELEVATED" : " | BELOW DEMO THRESHOLD");
    } else {
      Serial.println(" | Send r to save resting baseline");
    }
  }
}
