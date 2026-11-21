// Team 11 · light-test · MCU side
//
// How well does the Modulino Light (LTR-381RGB) read flicker? The sketch flashes a test LED on D3
// (rig: hardware/light-test) at known rates into the sensor and streams every sensor reading to
// Python (python/main.py), which analyses each step and prints the verdict.
//
// It runs by itself, so it only needs MCU -> Python messages:
//   1. waits START_DELAY_MS (LED off) so the Python side is listening,
//   2. picks the sensor gain: the highest gain where the steady LED stays below 45% of full scale,
//   3. runs the steps in STEPS[] (dark, steady, square waves 1-35 Hz, short flashes, dark),
//   4. then keeps streaming with the LED off ("live" mode) for manual checks with tools/flicker.html.
// Python can ask for a new run with Bridge.call("run") (best effort); otherwise restart the app.
//
// Messages to Python:
//   notify("info",  text)
//   notify("range", run, gain_code, gain_x, on_level, dark_level, saturated)
//   notify("step",  run, idx, n_steps, kind, freq_x10, on_us, dur_ms)    at the start of each step
//   notify("s",     run, idx, "t,r,g,b;t,r,g,b;...")    t = 0.1 ms since step start; idx -1 = live
//   notify("end",   run, idx, n_samples, max_late_us, max_send_us)
//   notify("done",  run, n_steps)
//
// The sensor is read through its registers (not the Modulino library, whose update() blocks for
// 50-150 ms): 16-bit resolution, 25 ms integration, 25 ms repeat = at most 40 readings/s.

#include <Arduino_RouterBridge.h>
#include <Wire.h>

// ---- Configuration ------------------------------------------------------------------------------
const int      LED_PIN        = 3;      // D3 -> R2 -> Q1 base; HIGH = LED on
const uint32_t START_DELAY_MS = 6000;   // after boot, before the first run
const uint32_t FLUSH_MS       = 100;    // send a batch at most this often...
const uint32_t FLUSH_MAX_MS   = 600;    // ...and at least this often
const uint32_t POLL_US        = 1000;   // sensor data-ready poll interval

struct Step {
  const char* kind;     // "dark", "steady", "square" (50% duty), "flash" (short pulse per period)
  uint16_t freqX10;     // flicker frequency x10 (Hz)
  uint32_t onUs;        // flash length (flash steps only)
  uint16_t durMs;       // step length; Python skips the first 0.5 s
};

const Step STEPS[] = {
  {"dark",   0,   0,    3000},
  {"steady", 0,   0,    3000},
  {"square", 10,  0,    6500},   //  1 Hz
  {"square", 20,  0,    6500},   //  2 Hz
  {"square", 30,  0,    6500},
  {"square", 50,  0,    6500},
  {"square", 60,  0,    6500},
  {"square", 80,  0,    6500},
  {"square", 90,  0,    6500},
  {"square", 100, 0,    6500},   // 10 Hz: the case the device is built around
  {"square", 110, 0,    6500},
  {"square", 120, 0,    6500},
  {"square", 140, 0,    6500},
  {"square", 150, 0,    6500},
  {"square", 160, 0,    6500},
  {"square", 180, 0,    6500},
  {"square", 200, 0,    6500},   // 20 Hz: half the reading rate (the limit)
  {"square", 220, 0,    6500},
  {"square", 250, 0,    6500},
  {"square", 300, 0,    6500},
  {"square", 350, 0,    6500},
  {"flash",  30,  5000, 6500},   // 5 ms flash, 3 per second
  {"flash",  30,  1000, 6500},   // 1 ms flash, 3 per second
  {"dark",   0,   0,    3000},
};
const int N_STEPS = sizeof(STEPS) / sizeof(STEPS[0]);

// ---- LTR-381RGB registers (from Arduino_LTR381RGB, src/LTR381RGB.cpp) --------------------------
const uint8_t LTR_ADDR       = 0x53;
const uint8_t LTR_MAIN_CTRL  = 0x00;
const uint8_t LTR_MEAS_RATE  = 0x04;
const uint8_t LTR_GAIN       = 0x05;   // 0 = x1, 1 = x3, 2 = x6, 3 = x9, 4 = x18
const uint8_t LTR_PART_ID    = 0x06;
const uint8_t LTR_STATUS     = 0x07;
const uint8_t LTR_DATA_GREEN = 0x0D;   // then RED (0x10), BLUE (0x13); 3 bytes each, LSB first
const uint8_t GAIN_X[]       = {1, 3, 6, 9, 18};
const uint32_t FULL_SCALE    = 65535;  // 16-bit resolution

uint8_t gainCode = 1;

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
  ltrRead(LTR_STATUS, &status, 1);              // clears the power-on flag
  ltrWrite(LTR_MAIN_CTRL, 0x00);                // standby while configuring
  ltrWrite(LTR_GAIN, gainCode);
  ltrWrite(LTR_MEAS_RATE, (0x04 << 4) | 0x00);  // 16-bit (25 ms integration), 25 ms repeat
  return ltrWrite(LTR_MAIN_CTRL, 0x06);         // enable, colour (RGB) mode, continuous
}

// Non-blocking. True when a fresh reading was read into r, g, b.
bool lightPoll(uint32_t& r, uint32_t& g, uint32_t& b, bool& lost) {
  uint8_t status = 0;
  if (!ltrRead(LTR_STATUS, &status, 1)) { lost = true; return false; }
  if (status & 0x20) { lightBegin(); return false; }   // sensor reset itself: reconfigure
  if (!(status & 0x08)) return false;                  // no new data yet
  uint8_t d[9];
  if (!ltrRead(LTR_DATA_GREEN, d, sizeof(d))) { lost = true; return false; }
  g = ((uint32_t)d[0] | (uint32_t)d[1] << 8 | (uint32_t)d[2] << 16) & 0xFFFFF;
  r = ((uint32_t)d[3] | (uint32_t)d[4] << 8 | (uint32_t)d[5] << 16) & 0xFFFFF;
  b = ((uint32_t)d[6] | (uint32_t)d[7] << 8 | (uint32_t)d[8] << 16) & 0xFFFFF;
  return true;
}

// Blocking (setup / auto-range only): wait for the next reading.
bool lightWait(uint32_t& r, uint32_t& g, uint32_t& b, uint32_t timeoutMs = 200) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    bool lost = false;
    if (lightPoll(r, g, b, lost)) return true;
    if (lost) return false;
    delay(1);
  }
  return false;
}

// Brightest channel, averaged over n readings after dropping two (they may straddle a change).
uint32_t levelNow(int n) {
  uint32_t r, g, b, sum = 0;
  int got = 0;
  for (int i = 0; i < n + 2; i++) {
    if (!lightWait(r, g, b)) continue;
    if (i < 2) continue;
    sum += max(r, max(g, b));
    got++;
  }
  return got ? sum / got : 0;
}

// ---- State -------------------------------------------------------------------------------------
enum Phase { WAITING, RUNNING, LIVE };
Phase phase = WAITING;
bool lightOk = false;
volatile bool runRequested = false;
uint32_t runId = 0, bootMs = 0;

int stepIdx = -1;
uint32_t stepStartUs = 0, periodUs = 0, onUs = 0;
uint32_t lastCycle = 0xFFFFFFFF;  // period index of the last flash
bool ledOn = false, ledEdge = false;
uint32_t maxLateUs = 0, maxSendUs = 0, nSamples = 0;

String batch;
uint32_t lastFlushMs = 0, lastPollUs = 0, lastRetryMs = 0;

void info(const String& s) {
  Bridge.notify("info", s);
  Monitor.println(s);
}

void led(bool on) {
  digitalWrite(LED_PIN, on ? HIGH : LOW);
  ledOn = on;
}

void flush(int idx) {
  if (!batch.length()) return;
  uint32_t t = micros();
  Bridge.notify("s", (int)runId, idx, batch);
  uint32_t took = micros() - t;
  if (took > maxSendUs) maxSendUs = took;
  batch = "";
  lastFlushMs = millis();
}

// Python asks for a new run (best effort; only a flag here, see the Bridge deadlock rule DI-13).
bool requestRun() {
  runRequested = true;
  return true;
}

// ---- Auto-range: highest gain where the steady LED stays below 45% of full scale ---------------
void autoRange() {
  led(true);
  uint32_t onLevel = 0;
  bool saturated = false;
  for (int code = 4; code >= 0; code--) {
    gainCode = code;
    lightBegin();
    onLevel = levelNow(3);
    if (onLevel < FULL_SCALE * 45 / 100) break;
    if (code == 0) saturated = onLevel > FULL_SCALE * 90 / 100;
  }
  led(false);
  uint32_t darkLevel = levelNow(3);
  Bridge.notify("range", (int)runId, (int)gainCode, (int)GAIN_X[gainCode], (int)onLevel, (int)darkLevel,
                (int)saturated);
  String s = "[mcu] gain x" + String(GAIN_X[gainCode]) + ": LED on " + String(onLevel) + ", dark " +
             String(darkLevel) + " counts (full scale " + String(FULL_SCALE) + ")";
  if (saturated) s += "  SATURATED even at x1: add paper between the LED and the sensor, or move it away";
  else if (onLevel < darkLevel + 1000) s += "  LED barely reaches the sensor: check D1 faces the window";
  info(s);
}

// ---- Steps -------------------------------------------------------------------------------------
void startStep(int idx) {
  flush(stepIdx);
  stepIdx = idx;
  const Step& st = STEPS[idx];
  periodUs = st.freqX10 ? 10000000UL / st.freqX10 : 0;
  onUs = !strcmp(st.kind, "square") ? periodUs / 2 : st.onUs;
  lastCycle = 0xFFFFFFFF;
  maxLateUs = maxSendUs = nSamples = 0;
  Bridge.notify("step", (int)runId, idx, N_STEPS, String(st.kind), (int)st.freqX10, (int)onUs, (int)st.durMs);
  stepStartUs = micros();
  led(!strcmp(st.kind, "steady"));
  lastFlushMs = millis();
}

void endStep() {
  flush(stepIdx);
  Bridge.notify("end", (int)runId, stepIdx, (int)nSamples, (int)maxLateUs, (int)maxSendUs);
}

void startRun() {
  runId = millis();
  led(false);
  info("[mcu] run " + String(runId) + ": " + String(N_STEPS) + " steps, about " +
       String(totalSeconds()) + " s");
  autoRange();
  phase = RUNNING;
  startStep(0);
}

uint32_t totalSeconds() {
  uint32_t ms = 0;
  for (int i = 0; i < N_STEPS; i++) ms += STEPS[i].durMs;
  return ms / 1000;
}

// LED pattern from absolute time since the step started: a late loop only delays an edge, it
// never shifts the following ones. Lateness of every edge is tracked.
void driveLed(uint32_t nowUs) {
  const Step& st = STEPS[stepIdx];
  uint32_t el = nowUs - stepStartUs;
  if (!strcmp(st.kind, "square")) {
    uint32_t ph = el % periodUs;
    bool want = ph < onUs;
    if (want != ledOn) {
      led(want);
      ledEdge = true;
      uint32_t late = want ? ph : ph - onUs;
      if (late > maxLateUs) maxLateUs = late;
    }
  } else if (!strcmp(st.kind, "flash")) {
    uint32_t cycle = el / periodUs;
    if (cycle != lastCycle) {
      lastCycle = cycle;
      uint32_t late = el % periodUs;
      if (late > maxLateUs) maxLateUs = late;
      led(true);
      delayMicroseconds(onUs);  // short and exact; blocks at most 5 ms
      led(false);
      ledEdge = true;
    }
  }
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  pinMode(LED_PIN, OUTPUT);
  led(false);
  Wire1.begin();               // Qwiic connector = Wire1 on the UNO Q
  Wire1.setClock(400000);      // short I2C transfers keep the LED timing tight
  batch.reserve(1024);
  Bridge.provide_safe("run", requestRun);

  lightOk = lightBegin();
  bootMs = millis();
  info(String("[mcu] light-test booted. Modulino Light: ") + (lightOk ? "OK (0x53 on Wire1)" : "MISSING (Qwiic cable?)") +
       ". First run in " + String(START_DELAY_MS / 1000) + " s.");
}

void loop() {
  uint32_t nowUs = micros(), nowMs = millis();

  if (!lightOk) {
    led(false);
    if (nowMs - lastRetryMs >= 1000) {
      lastRetryMs = nowMs;
      if ((lightOk = lightBegin())) info("[mcu] Modulino Light connected");
    }
    return;
  }

  if (runRequested || (phase == WAITING && nowMs - bootMs >= START_DELAY_MS)) {
    runRequested = false;
    if (phase == RUNNING) endStep();
    startRun();
    return;
  }

  if (phase == RUNNING) {
    driveLed(nowUs);
    if (nowUs - stepStartUs >= (uint32_t)STEPS[stepIdx].durMs * 1000UL) {
      endStep();
      if (stepIdx + 1 < N_STEPS) {
        startStep(stepIdx + 1);
      } else {
        led(false);
        phase = LIVE;
        stepIdx = -1;
        stepStartUs = micros();
        Bridge.notify("done", (int)runId, N_STEPS);
        info("[mcu] run finished; LED off, streaming live readings");
      }
      return;
    }
  }

  // Sensor readings (also in WAITING and LIVE, so Python sees data at once).
  if (nowUs - lastPollUs >= POLL_US) {
    lastPollUs = nowUs;
    uint32_t r, g, b;
    bool lost = false;
    if (lightPoll(r, g, b, lost)) {
      uint32_t t = (micros() - stepStartUs) / 100;
      batch += t; batch += ','; batch += r; batch += ','; batch += g; batch += ','; batch += b; batch += ';';
      nSamples++;
    } else if (lost) {
      lightOk = false;
      info("[mcu] Modulino Light stopped answering (Qwiic cable?)");
      return;
    }
  }

  // Send right after an LED edge, when the next edge is furthest away; otherwise on a timer.
  uint32_t since = nowMs - lastFlushMs;
  bool idle = phase != RUNNING || !strcmp(STEPS[stepIdx].kind, "dark") || !strcmp(STEPS[stepIdx].kind, "steady");
  if (batch.length() && ((since >= FLUSH_MS && (ledEdge || idle)) || since >= FLUSH_MAX_MS)) {
    flush(phase == RUNNING ? stepIdx : -1);
  }
  ledEdge = false;
}
