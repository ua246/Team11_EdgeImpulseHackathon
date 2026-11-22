#include <Arduino_RouterBridge.h>
#include <MAX30105.h>
#include <Wire.h>

MAX30105 sensor;
constexpr unsigned long reportIntervalMs = 100;
unsigned long lastReport = 0;
uint32_t sampleIndex = 0;
String batch;

void setup() {
  Bridge.begin();
  Wire1.begin();
  batch.reserve(128);
}

void loop() {
  static bool ready = false;
  if (!ready) {
    if (!sensor.begin(Wire1, I2C_SPEED_STANDARD)) {
      Bridge.notify("pulse_status", "MAX30102 missing on Qwiic (0x57). Check wiring.");
      delay(2000);
      return;
    }
    // Two LEDs, no FIFO averaging, 100 samples/s, 18-bit resolution.
    sensor.setup(0x24, 1, 2, 100, 411, 4096);
    sensor.setPulseAmplitudeRed(0);
    ready = true;
  }

  sensor.check();
  while (sensor.available()) {
    if (batch.length() == 0) batch = String(sampleIndex);
    batch += ',';
    batch += String(sensor.getFIFOIR());
    sensor.nextSample();
    ++sampleIndex;

    if (batch.length() >= 100) {
      Bridge.notify("pulse_samples", batch);
      batch = "";
    }
  }

  if (millis() - lastReport >= reportIntervalMs) {
    lastReport = millis();
    if (batch.length()) {
      Bridge.notify("pulse_samples", batch);
      batch = "";
    }
  }
  delay(2);
}
