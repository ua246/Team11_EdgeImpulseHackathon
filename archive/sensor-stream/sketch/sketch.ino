// Team 11 · sensor-stream · MCU side (STM32 on the UNO Q)
//
// Reads two sensors and streams them to Python (python/main.py) over the Bridge:
//   - Modulino Movement (LSM6DSOX IMU) on the Qwiic connector  -> "imu"   batches
//   - Modulino Light (LTR-381RGB) on the Qwiic connector        -> "light" batches
// Once a second it also sends a self-report ("mcu") so Python can show health and timing.
//
// Wiring: both Modulinos on the Qwiic connector (bus Wire1, not Wire), daisy-chained.
//
// Messages are compact CSV text, batched every FLUSH_PERIOD_MS, because the MCU<->Linux
// link is a 115200-baud UART (~11 KB/s in total). Keep the total well under that.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <Wire.h>

// ---- Configuration (keep the rates in sync with python/main.py) -----------------------
const uint32_t IMU_PERIOD_MS   = 20;     // 50 Hz
const uint32_t FLUSH_PERIOD_MS = 100;    // one Bridge message per stream every 100 ms
const uint32_t REPORT_MS       = 1000;   // MCU self-report period
const uint32_t RETRY_MS        = 3000;   // retry a missing sensor this often (hot-plug)

// ---- Modulino Light, read directly ----------------------------------------------------
// The library's ModulinoLight::update() switches modes and polls with delay(50), so each
// call blocks ~50-150 ms. That would stall the IMU sampling. Instead we put
// the LTR-381RGB in continuous colour mode once and read a new sample whenever the
// data-ready bit is set. Hardware maximum: one reading per 25 ms (40 Hz).
// Register map from Arduino_LTR381RGB (src/LTR381RGB.cpp).
const uint8_t LTR_ADDR       = 0x53;
const uint8_t LTR_MAIN_CTRL  = 0x00;
const uint8_t LTR_MEAS_RATE  = 0x04;
const uint8_t LTR_GAIN       = 0x05;
const uint8_t LTR_PART_ID    = 0x06;
const uint8_t LTR_STATUS     = 0x07;
const uint8_t LTR_DATA_GREEN = 0x0D;  // then RED (0x10), BLUE (0x13); 3 bytes each, LSB first

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
  ltrRead(LTR_STATUS, &status, 1);            // clears the power-on flag
  ltrWrite(LTR_GAIN, 0x01);                   // gain x3: bright flicker saturates less (0x04 = x18 for dim rooms)
  ltrWrite(LTR_MEAS_RATE, (0x04 << 4) | 0x00); // 16-bit resolution (25 ms) and 25 ms repeat rate
  return ltrWrite(LTR_MAIN_CTRL, 0x06);       // enable, colour (RGB) mode, continuous
}

// Non-blocking. Returns true when a fresh sample was read into r, g, b.
bool lightPoll(uint32_t& r, uint32_t& g, uint32_t& b, bool& lost) {
  uint8_t status = 0;
  if (!ltrRead(LTR_STATUS, &status, 1)) { lost = true; return false; }
  if (status & 0x20) { lightBegin(); return false; }  // sensor reset itself: reconfigure
  if (!(status & 0x08)) return false;                 // no new data yet
  uint8_t d[9];
  if (!ltrRead(LTR_DATA_GREEN, d, sizeof(d))) { lost = true; return false; }
  g = ((uint32_t)d[0] | (uint32_t)d[1] << 8 | (uint32_t)d[2] << 16) & 0xFFFFF;
  r = ((uint32_t)d[3] | (uint32_t)d[4] << 8 | (uint32_t)d[5] << 16) & 0xFFFFF;
  b = ((uint32_t)d[6] | (uint32_t)d[7] << 8 | (uint32_t)d[8] << 16) & 0xFFFFF;
  return true;
}

// ---- State ------------------------------------------------------------------------------
ModulinoMovement movement;
bool imuOk = false, lightOk = false;

String imuBuf, lightBuf;
uint32_t lastImuMs = 0, lastFlushMs = 0, lastReportMs = 0, lastRetryMs = 0;
uint32_t nImu = 0, nLight = 0, maxFlushUs = 0;

void setup() {
  Bridge.begin();
  Monitor.begin();
  Modulino.begin(Wire1);              // Qwiic connector = Wire1 on the UNO Q

  imuBuf.reserve(1024);
  lightBuf.reserve(512);

  imuOk = movement.begin();
  lightOk = lightBegin();

  Monitor.print("[mcu] sensor-stream booted. IMU: ");
  Monitor.print(imuOk ? "OK" : "MISSING");
  Monitor.print("  Light: ");
  Monitor.println(lightOk ? "OK" : "MISSING");

  lastImuMs = lastFlushMs = lastReportMs = lastRetryMs = millis();
}

void loop() {
  uint32_t nowMs = millis();

  // IMU: acceleration in milli-g, rotation in 0.1 deg/s (integers keep messages short).
  if (imuOk && nowMs - lastImuMs >= IMU_PERIOD_MS) {
    lastImuMs = nowMs;
    if (movement.update()) {
      imuBuf += nowMs;                                   imuBuf += ',';
      imuBuf += (long)lroundf(movement.getX() * 1000);   imuBuf += ',';
      imuBuf += (long)lroundf(movement.getY() * 1000);   imuBuf += ',';
      imuBuf += (long)lroundf(movement.getZ() * 1000);   imuBuf += ',';
      imuBuf += (long)lroundf(movement.getRoll() * 10);  imuBuf += ',';  // gyro x
      imuBuf += (long)lroundf(movement.getPitch() * 10); imuBuf += ',';  // gyro y
      imuBuf += (long)lroundf(movement.getYaw() * 10);   imuBuf += '\n'; // gyro z
      nImu++;
    }
  }

  // Light: whenever the sensor has a new reading (max 40 Hz).
  if (lightOk) {
    uint32_t r, g, b;
    bool lost = false;
    if (lightPoll(r, g, b, lost)) {
      lightBuf += nowMs; lightBuf += ',';
      lightBuf += r;     lightBuf += ',';
      lightBuf += g;     lightBuf += ',';
      lightBuf += b;     lightBuf += '\n';
      nLight++;
    } else if (lost) {
      lightOk = false;
      Monitor.println("[mcu] Light sensor stopped answering (Qwiic cable?)");
    }
  }

  // Send batches.
  if (nowMs - lastFlushMs >= FLUSH_PERIOD_MS) {
    lastFlushMs = nowMs;
    uint32_t t = micros();
    if (imuBuf.length())   { Bridge.notify("imu", imuBuf);         imuBuf = ""; }
    if (lightBuf.length()) { Bridge.notify("light", lightBuf);     lightBuf = ""; }
    uint32_t took = micros() - t;
    if (took > maxFlushUs) maxFlushUs = took;
  }

  // Self-report: sample counts since the last report and the worst flush time.
  if (nowMs - lastReportMs >= REPORT_MS) {
    lastReportMs = nowMs;
    Bridge.notify("mcu", (int)imuOk, (int)lightOk, nImu, nLight, maxFlushUs);
    nImu = nLight = maxFlushUs = 0;
  }

  // Hot-plug: retry missing sensors.
  if ((!imuOk || !lightOk) && nowMs - lastRetryMs >= RETRY_MS) {
    lastRetryMs = nowMs;
    if (!imuOk && (imuOk = movement.begin())) Monitor.println("[mcu] IMU connected");
    if (!lightOk && (lightOk = lightBegin())) Monitor.println("[mcu] Light sensor connected");
  }
}
