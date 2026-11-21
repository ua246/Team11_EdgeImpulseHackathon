// Team 11 · hr-test · MCU side
//
// Finds the heart beat sensor and streams it to Python at 100 samples/s:
//   - MAX30102 / MAX30105 (part ID 0x15) or MAX30100 (part ID 0x11) at I2C address 0x57,
//     searched on Wire1 (Qwiic), Wire (header SDA/SCL pins) and Wire2 (A4/A5). Wire2 needs the
//     1.1.0 board package (tools/unoq flash builds with it).
//     Channels: red, ir (raw ADC counts).
//   - If no I2C sensor is found: analog pins A0-A3 (for an analog pulse module).
// Messages to Python:
//   notify("info", text)                  setup report (one line per message)
//   notify("ppg", t0_ms, "v v;v v;...")   a batch of samples, one ';'-separated group per sample
// No libraries beyond the Bridge: the sensor registers are driven directly.

#include <Arduino_RouterBridge.h>
#include <Wire.h>

const uint8_t ADDR = 0x57;
const uint32_t PERIOD_US = 10000;      // 100 samples/s
const uint32_t FLUSH_MS = 100;

TwoWire* bus = nullptr;
const char* busName = "";
uint8_t partId = 0;                    // 0x15 = MAX30102/MAX30105, 0x11 = MAX30100, 0 = analog mode
String batch;
uint32_t batchT0 = 0, lastFlush = 0, lastSample = 0, nSamples = 0;

bool wr(uint8_t reg, uint8_t val) {
  bus->beginTransmission(ADDR);
  bus->write(reg);
  bus->write(val);
  return bus->endTransmission() == 0;
}

bool rd(uint8_t reg, uint8_t* buf, size_t len) {
  bus->beginTransmission(ADDR);
  bus->write(reg);
  if (bus->endTransmission(false) != 0) return false;
  if (bus->requestFrom(ADDR, len) != len) return false;
  for (size_t i = 0; i < len; i++) buf[i] = bus->read();
  return true;
}

void info(const String& s) {
  Bridge.notify("info", s);
  Monitor.println(s);
}

// Report every address that answers on a bus, so wiring and pull-up problems are visible.
void scan(TwoWire& w, const char* name) {
  w.begin();
  w.setClock(100000);
  String found;
  for (uint8_t a = 0x08; a < 0x78; a++) {
    w.beginTransmission(a);
    if (w.endTransmission() == 0) {      // 0 = a device acknowledged this address
      found += " 0x";
      found += String(a, HEX);
    }
  }
  info("[mcu] I2C scan " + String(name) + ":" + (found.length() ? found : String(" nothing answers")));
}

bool probe(TwoWire& w, const char* name) {
  w.begin();
  w.setClock(100000);
  bus = &w;
  busName = name;
  uint8_t id = 0;
  if (!rd(0xFF, &id, 1)) return false;   // part ID register (same address on both chips)
  partId = id;
  return true;
}

void setupMax30102() {
  wr(0x09, 0x40);                        // reset
  delay(20);
  wr(0x08, 0x10);                        // FIFO: no averaging, rollover on
  wr(0x0A, 0x27);                        // ADC range 4096 nA, 100 samples/s, 411 us pulses (18-bit)
  wr(0x0C, 0x24);                        // red LED ~7 mA
  wr(0x0D, 0x24);                        // IR LED ~7 mA
  wr(0x09, 0x03);                        // SpO2 mode: red + IR
  wr(0x04, 0); wr(0x05, 0); wr(0x06, 0); // clear FIFO pointers
}

void setupMax30100() {
  wr(0x06, 0x40);                        // reset
  delay(20);
  wr(0x07, 0x47);                        // high-res, 100 samples/s, 1600 us pulses (16-bit)
  wr(0x09, 0x44);                        // red and IR LED ~14 mA
  wr(0x06, 0x03);                        // SpO2 mode
  wr(0x02, 0); wr(0x03, 0); wr(0x04, 0); // clear FIFO pointers
}

void addSample(const String& values) {
  if (batch.length() == 0) batchT0 = millis();
  batch += values;
  batch += ';';
  nSamples++;
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  batch.reserve(512);
  delay(1500);                           // let the Bridge settle before the first messages

  scan(Wire1, "Wire1 (Qwiic)");
  scan(Wire, "Wire (header SDA/SCL)");
  scan(Wire2, "Wire2 (A4/A5)");
  if (probe(Wire1, "Wire1 (Qwiic)") || probe(Wire, "Wire (header SDA/SCL)") || probe(Wire2, "Wire2 (A4/A5)")) {
    if (partId == 0x15) {
      setupMax30102();
      info("[mcu] found MAX30102/MAX30105 (part ID 0x15) on " + String(busName) + ", channels: red ir");
    } else if (partId == 0x11) {
      setupMax30100();
      info("[mcu] found MAX30100 (part ID 0x11) on " + String(busName) + ", channels: red ir");
    } else {
      info("[mcu] device at 0x57 on " + String(busName) + " has unknown part ID 0x" + String(partId, HEX));
      partId = 0;
    }
  } else {
    info("[mcu] no I2C device at 0x57 on Wire1 (Qwiic), Wire (header SDA/SCL) or Wire2 (A4/A5)");
  }
  if (partId == 0) {
    analogReadResolution(12);
    info("[mcu] analog mode: streaming A0 A1 A2 A3 (12-bit)");
  }
  lastSample = micros();
  lastFlush = millis();
}

void readFifo30102() {
  uint8_t p[3];
  if (!rd(0x04, p, 3)) return;            // write pointer, overflow, read pointer
  int n = (p[0] - p[2]) & 0x1F;
  while (n > 0) {
    int k = n > 5 ? 5 : n;
    uint8_t d[30];
    if (!rd(0x07, d, k * 6)) return;
    for (int i = 0; i < k; i++) {
      uint32_t red = ((uint32_t)d[i * 6] << 16 | (uint32_t)d[i * 6 + 1] << 8 | d[i * 6 + 2]) & 0x3FFFF;
      uint32_t ir = ((uint32_t)d[i * 6 + 3] << 16 | (uint32_t)d[i * 6 + 4] << 8 | d[i * 6 + 5]) & 0x3FFFF;
      addSample(String(red) + " " + String(ir));
    }
    n -= k;
  }
}

void readFifo30100() {
  uint8_t p[3];
  if (!rd(0x02, p, 3)) return;            // write pointer, overflow, read pointer
  int n = (p[0] - p[2]) & 0x0F;
  while (n > 0) {
    int k = n > 5 ? 5 : n;
    uint8_t d[20];
    if (!rd(0x05, d, k * 4)) return;
    for (int i = 0; i < k; i++) {
      uint16_t ir = (uint16_t)d[i * 4] << 8 | d[i * 4 + 1];
      uint16_t red = (uint16_t)d[i * 4 + 2] << 8 | d[i * 4 + 3];
      addSample(String(red) + " " + String(ir));
    }
    n -= k;
  }
}

void loop() {
  if (partId == 0x15) {
    readFifo30102();                     // the sensor keeps its own 100/s clock; drain its FIFO
  } else if (partId == 0x11) {
    readFifo30100();
  } else if (micros() - lastSample >= PERIOD_US) {
    lastSample += PERIOD_US;
    addSample(String(analogRead(A0)) + " " + String(analogRead(A1)) + " " +
              String(analogRead(A2)) + " " + String(analogRead(A3)));
  }
  if (millis() - lastFlush >= FLUSH_MS) {
    lastFlush = millis();
    if (batch.length()) {
      Bridge.notify("ppg", (int)batchT0, batch);
      batch = "";
    }
  }
}
