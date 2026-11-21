// Team 11 · max-strobe-test · MCU side
//
// Can the MAX30102/MAX30105 heart-rate sensor detect strobe / flicker light?
// The chip cancels ambient light by design (each sample = LED-on minus LED-off), so this test
// measures how much flicker still leaks through, and whether its "ambient light overflow" flag
// (ALC_OVF) trips on bright flashes.
//   - single-LED (HR) mode, 400 samples/s, 18-bit: flicker up to 200 Hz is visible in principle
//   - the red LED alternates ON (7 mA) / OFF every 2 s, so both cases are recorded under the
//     same flicker
//   - ALC_OVF events are counted per batch
// Messages to Python:
//   notify("info", text)
//   notify("strobe", t0_ms, led_on, alc_ovf_count, "v;v;v;...")   one LED state per batch
// Searches Wire2 (A4/A5), Wire1 (Qwiic) and Wire (header). Needs board package 1.1.0
// (tools/unoq flash builds with it).

#include <Arduino_RouterBridge.h>
#include <Wire.h>

const uint8_t ADDR = 0x57;
const uint32_t SWITCH_MS = 2000;       // LED on/off period
const uint32_t FLUSH_MS = 100;

TwoWire* bus = nullptr;
const char* busName = "";
uint8_t partId = 0;
bool ledOn = true;
uint32_t lastSwitch = 0, lastFlush = 0, batchT0 = 0;
uint16_t ovf = 0;
String batch;

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

bool probe(TwoWire& w, const char* name) {
  w.begin();
  w.setClock(400000);                    // 400 kHz: plenty of headroom for 400 samples/s
  bus = &w;
  busName = name;
  uint8_t id = 0;
  if (!rd(0xFF, &id, 1)) return false;
  partId = id;
  return true;
}

void setLed(bool on) {
  wr(0x0C, on ? 0x24 : 0x00);            // red LED pulse amplitude: ~7 mA or off
  ledOn = on;
}

void flush() {
  if (batch.length()) {
    Bridge.notify("strobe", (int)batchT0, (int)ledOn, (int)ovf, batch);
    batch = "";
    ovf = 0;
  }
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  batch.reserve(1024);
  delay(1500);
  if (!(probe(Wire2, "Wire2 (A4/A5)") || probe(Wire1, "Wire1 (Qwiic)") || probe(Wire, "Wire (header SDA/SCL)"))
      || partId != 0x15) {
    info("[mcu] no MAX30102/MAX30105 (part ID 0x15) found on Wire2, Wire1 or Wire");
    partId = 0;
    return;
  }
  wr(0x09, 0x40);                        // reset
  delay(20);
  wr(0x02, 0x20);                        // interrupt enable 1: ALC_OVF (so the status flag is set)
  wr(0x08, 0x10);                        // FIFO: no averaging, rollover
  wr(0x0A, 0x2F);                        // ADC range 4096 nA (01), 400 samples/s (011), 411 us pulses (11, 18-bit)
  wr(0x0D, 0x00);                        // IR LED off (unused in HR mode)
  setLed(true);
  wr(0x09, 0x02);                        // HR mode: red LED only
  wr(0x04, 0); wr(0x05, 0); wr(0x06, 0); // clear FIFO pointers
  info("[mcu] strobe test: MAX30102/MAX30105 on " + String(busName) +
       ", 400 samples/s, red LED alternating on/off every 2 s");
  lastSwitch = lastFlush = millis();
}

void loop() {
  if (partId != 0x15) {
    delay(100);
    return;
  }
  uint8_t st = 0;
  if (rd(0x00, &st, 1) && (st & 0x20)) ovf++;   // interrupt status 1, clear-on-read
  uint8_t p[3];
  if (rd(0x04, p, 3)) {                         // write pointer, overflow counter, read pointer
    int n = (p[0] - p[2]) & 0x1F;
    while (n > 0) {
      int k = n > 10 ? 10 : n;
      uint8_t d[30];
      if (!rd(0x07, d, k * 3)) break;
      for (int i = 0; i < k; i++) {
        uint32_t v = ((uint32_t)d[i * 3] << 16 | (uint32_t)d[i * 3 + 1] << 8 | d[i * 3 + 2]) & 0x3FFFF;
        if (batch.length() == 0) batchT0 = millis();
        batch += String(v);
        batch += ';';
      }
      n -= k;
    }
  }
  uint32_t now = millis();
  if (now - lastSwitch >= SWITCH_MS) {          // send what was measured in the old state first
    flush();
    lastSwitch = now;
    setLed(!ledOn);
  }
  if (now - lastFlush >= FLUSH_MS) {
    lastFlush = now;
    flush();
  }
}
