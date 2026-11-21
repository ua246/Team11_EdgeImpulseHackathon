// Team 11 · flicker-guard · MCU side
//
// Streams every Modulino Light reading (R, G, B and the gain it was taken at) to Python, which
// records it for training and runs the Edge Impulse model on it (python/main.py).
//   notify("info", text)
//   notify("s", "t,r,g,b,gc;t,r,g,b,gc;...")   t = millis(), gc = gain code (0-4 = x1, x3, x6, x9, x18)
// About 36 readings/s (DI-01). The sensor's registers are used directly, because the Modulino
// library's update() blocks for 50-150 ms (DI-02).
//
// Automatic gain: drop one step at once if any channel goes above 85% of full scale; raise one
// step after 3 s with every channel below 8%. Python divides by the gain, so a change only shows
// up as one or two mixed readings, which it skips.

#include <Arduino_RouterBridge.h>
#include <Wire.h>

const uint32_t FLUSH_MS = 100;
const uint32_t POLL_US = 1000;
const uint32_t RAISE_AFTER_MS = 3000;
const uint32_t FULL_SCALE = 65535;     // 16-bit resolution

const uint8_t LTR_ADDR = 0x53, LTR_MAIN_CTRL = 0x00, LTR_MEAS_RATE = 0x04, LTR_GAIN = 0x05,
              LTR_PART_ID = 0x06, LTR_STATUS = 0x07, LTR_DATA_GREEN = 0x0D;
const uint8_t GAIN_X[] = {1, 3, 6, 9, 18};

uint8_t gainCode = 4;
bool lightOk = false;
String batch;
uint32_t lastFlushMs = 0, lastPollUs = 0, lastRetryMs = 0, dimSinceMs = 0;

bool ltrWrite(uint8_t reg, uint8_t val) {
  Wire1.beginTransmission(LTR_ADDR);
  Wire1.write(reg);
  Wire1.write(val);
  return Wire1.endTransmission() == 0;
}

bool ltrRead(uint8_t reg, uint8_t* buf, size_t len) {
  Wire1.beginTransmission(LTR_ADDR);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(LTR_ADDR, len) != len) return false;
  for (size_t i = 0; i < len; i++) buf[i] = Wire1.read();
  return true;
}

bool lightBegin() {
  uint8_t id = 0, status = 0;
  if (!ltrRead(LTR_PART_ID, &id, 1) || (id & 0xF0) != 0xC0) return false;
  ltrRead(LTR_STATUS, &status, 1);
  ltrWrite(LTR_MAIN_CTRL, 0x00);
  ltrWrite(LTR_GAIN, gainCode);
  ltrWrite(LTR_MEAS_RATE, (0x04 << 4) | 0x00);   // 16-bit (25 ms nominal), fastest repeat
  return ltrWrite(LTR_MAIN_CTRL, 0x06);          // colour mode, continuous
}

bool lightPoll(uint32_t& r, uint32_t& g, uint32_t& b, bool& lost) {
  uint8_t status = 0;
  if (!ltrRead(LTR_STATUS, &status, 1)) { lost = true; return false; }
  if (status & 0x20) { lightBegin(); return false; }
  if (!(status & 0x08)) return false;
  uint8_t d[9];
  if (!ltrRead(LTR_DATA_GREEN, d, sizeof(d))) { lost = true; return false; }
  g = ((uint32_t)d[0] | (uint32_t)d[1] << 8 | (uint32_t)d[2] << 16) & 0xFFFFF;
  r = ((uint32_t)d[3] | (uint32_t)d[4] << 8 | (uint32_t)d[5] << 16) & 0xFFFFF;
  b = ((uint32_t)d[6] | (uint32_t)d[7] << 8 | (uint32_t)d[8] << 16) & 0xFFFFF;
  return true;
}

void setGain(uint8_t code) {
  gainCode = code;
  ltrWrite(LTR_GAIN, gainCode);   // takes effect from the next reading
}

void info(const String& s) {
  Bridge.notify("info", s);
  Monitor.println(s);
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  Wire1.begin();
  Wire1.setClock(400000);
  batch.reserve(1024);
  lightOk = lightBegin();
  info(String("[mcu] flicker-guard booted. Modulino Light: ") + (lightOk ? "OK" : "MISSING (Qwiic cable?)"));
}

void loop() {
  uint32_t nowMs = millis(), nowUs = micros();
  if (!lightOk) {
    if (nowMs - lastRetryMs >= 1000) {
      lastRetryMs = nowMs;
      if ((lightOk = lightBegin())) info("[mcu] Modulino Light connected");
    }
    return;
  }

  if (nowUs - lastPollUs >= POLL_US) {
    lastPollUs = nowUs;
    uint32_t r, g, b;
    bool lost = false;
    if (lightPoll(r, g, b, lost)) {
      batch += nowMs; batch += ','; batch += r; batch += ','; batch += g; batch += ',';
      batch += b; batch += ','; batch += gainCode; batch += ';';
      uint32_t peak = max(r, max(g, b));
      if (peak > FULL_SCALE * 85 / 100 && gainCode > 0) {
        setGain(gainCode - 1);
        dimSinceMs = nowMs;
      } else if (peak < FULL_SCALE * 8 / 100 && gainCode < 4) {
        if (!dimSinceMs) dimSinceMs = nowMs;
        if (nowMs - dimSinceMs >= RAISE_AFTER_MS) {
          setGain(gainCode + 1);
          dimSinceMs = nowMs;
        }
      } else {
        dimSinceMs = 0;
      }
    } else if (lost) {
      lightOk = false;
      info("[mcu] Modulino Light stopped answering (Qwiic cable?)");
      return;
    }
  }

  if (batch.length() && nowMs - lastFlushMs >= FLUSH_MS) {
    lastFlushMs = nowMs;
    Bridge.notify("s", batch);
    batch = "";
  }
}
