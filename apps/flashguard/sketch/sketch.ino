// Team 11 · flashguard · MCU side
//
// 1. Streams every Modulino Light reading (R, G, B and the gain it was taken at) to Python, which
//    records it and runs the Edge Impulse *flicker* model on it (python/main.py, Linux side).
// 2. Runs the Edge Impulse *movement* model here on the MCU (Arduino library in ../libraries,
//    "Wearable Movement Monitoring (More Classes)", project 1170305): Modulino Movement at 4 Hz,
//    exactly as it was recorded for training (accX/Y/Z in g, gyrX/Y/Z in deg/s), 10 s window,
//    classified every 2.5 s. Python uses it to watch for seizure-like movement after a flicker alert.
//   notify("info", text)
//   notify("s", "t,r,g,b,gc;t,r,g,b,gc;...")   t = millis(), gc = gain code (0-4 = x1, x3, x6, x9, x18)
//   notify("imu", "t,ax,ay,az,gx,gy,gz;...")   4 Hz movement samples (recorded by Python)
//   notify("m", "Running:0.012,Seizure:0.950,...", dsp_us, nn_us)   one movement classification
// 3. Shows the alert state on the UNO Q's LED matrix. Python calls show(state, value) (Bridge.call);
//    static icons only, changing at most once a second (nothing on the device flashes: spec N7).
//    0 monitoring · 1 flicker exposure · 2 watch window (value = time-left bar, 0-13 columns)
//    3 seizure suspected (value = seconds to the alarm) · 4 carer alarm · 5 heart rate elevated
// 4. Heart rate from a MAX30102 (the teammate's beat detector from apps/FlickerGuard_IDE_Pulse,
//    ported to register access): infrared at 100 samples/s, BPM = median of 5 beat intervals.
//    Searched on Wire (header SDA/SCL, D20/D21), Wire2 (A4/A5) and Wire1 (Qwiic).
//   notify("hr", bpm_steady, bpm_any, ir, quality)   once a second
//      quality: 0 no fingertip · 1 saturated · 2 settling / not steady · 3 steady (bpm_steady valid)
// 5. Modulino Buzzer (I2C 0x1E, on any bus): Python calls buzz(freq_hz, ms) (Bridge.call).
// About 36 readings/s (DI-01). The sensor's registers are used directly, because the Modulino
// library's update() blocks for 50-150 ms (DI-02).
//
// Automatic gain: drop one step at once if any channel goes above 85% of full scale; raise one
// step after 3 s with every channel below 8%. Python divides by the gain, so a change only shows
// up as one or two mixed readings, which it skips.

#include <Arduino_RouterBridge.h>
#include <Wire.h>
#include <Wearable_Movement_Monitoring_More_Classes__inferencing.h>

const uint32_t FLUSH_MS = 100;
const uint32_t POLL_US = 1000;
const uint32_t RAISE_AFTER_MS = 3000;
const uint32_t FULL_SCALE = 65535;     // 16-bit resolution

const uint8_t LTR_ADDR = 0x53, LTR_MAIN_CTRL = 0x00, LTR_MEAS_RATE = 0x04, LTR_GAIN = 0x05,
              LTR_PART_ID = 0x06, LTR_STATUS = 0x07, LTR_DATA_GREEN = 0x0D;
const uint8_t GAIN_X[] = {1, 3, 6, 9, 18};

// ---- LED matrix (8 x 13). Functions exported by the UNO Q core (same as Arduino_LED_Matrix uses);
// declared here so the sketch needs no extra library. 3-bit grayscale: 0 off ... 7 full. -------------
extern "C" {
void matrixBegin(void);
void matrixSetGrayscaleBits(uint8_t bits);
void matrixGrayscaleWrite(const uint8_t *buf);
}
const int MX_W = 13, MX_H = 8;
uint8_t mx[MX_W * MX_H];

const char* const ICON_MONITOR[MX_H] = {   // calm eye, dim
  ".............", "....+++++....", "..++.....++..", ".+....+....+.",
  "+....+++....+", ".+....+....+.", "..++.....++..", "....+++++...."};
const char* const ICON_EXPOSURE[MX_H] = {  // warning triangle with "!"
  "......#......", ".....#.#.....", "....#.#.#....", "....#.#.#....",
  "...#..#..#...", "...#.....#...", "..#...#...#..", ".###########."};
const char* const ICON_WATCH[MX_H] = {     // open eye; row 7 = time left in the watch window
  "....#####....", "..##.....##..", ".#....#....#.", "#....###....#",
  ".#....#....#.", "..##.....##..", "....#####....", "............."};
const char* const ICON_HEART[MX_H] = {     // heart: heart rate elevated
  ".............", "...##...##...", "..####.####..", "..#########..",
  "...#######...", "....#####....", ".....###.....", "......#......"};
const char* const ICON_ALARM[MX_H] = {     // SOS
  "#############", ".............", ".###.###.###.", ".#...#.#.#...",
  ".###.#.#.###.", "...#.#.#...#.", ".###.###.###.", "#############"};
const uint8_t DIGITS[10][7] = {            // 5 x 7 font, one byte per row, bit 4 = left column
  {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}, {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E},
  {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}, {0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E},
  {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}, {0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E},
  {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}, {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08},
  {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}, {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}};

void mxArt(const char* const art[MX_H]) {
  for (int r = 0; r < MX_H; r++)
    for (int c = 0; c < MX_W; c++)
      mx[r * MX_W + c] = art[r][c] == '#' ? 7 : (art[r][c] == '+' ? 2 : 0);
}

void mxDigit(int d, int x0) {
  for (int r = 0; r < 7; r++)
    for (int c = 0; c < 5; c++)
      if (DIGITS[d][r] & (0x10 >> c)) mx[r * MX_W + x0 + c] = 7;
}

int shownState = -1, shownValue = -1;

// Called by Python through Bridge.call("show", state, value). provide_safe: runs in loop context.
int showStatus(int state, int value) {
  if (state == shownState && value == shownValue) return 1;
  shownState = state;
  shownValue = value;
  switch (state) {
    case 1: mxArt(ICON_EXPOSURE); break;
    case 2:
      mxArt(ICON_WATCH);
      for (int c = 0; c < MX_W && c < value; c++) mx[7 * MX_W + c] = 2;
      break;
    case 3:
      memset(mx, 0, sizeof(mx));
      value = constrain(value, 0, 99);
      if (value >= 10) { mxDigit(value / 10, 1); mxDigit(value % 10, 7); }
      else mxDigit(value, 4);
      break;
    case 4: mxArt(ICON_ALARM); break;
    case 5: mxArt(ICON_HEART); break;
    default: mxArt(ICON_MONITOR); break;
  }
  matrixGrayscaleWrite(mx);
  return 1;
}

// ---- Movement model (Edge Impulse Arduino library) -----------------------------------------------
const uint32_t MOVE_PERIOD_US = EI_CLASSIFIER_INTERVAL_MS * 1000UL;   // 250 ms = 4 Hz, as in training
const int MOVE_AXES = EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME;             // 6
const int MOVE_WINDOW = EI_CLASSIFIER_RAW_SAMPLE_COUNT;                // 40 samples = 10 s
const int MOVE_EVERY = MOVE_WINDOW / EI_CLASSIFIER_SLICES_PER_MODEL_WINDOW;   // classify every 10 samples
// Modulino Movement = LSM6DSOX at 0x6A, read through its registers. (The Arduino_Modulino library
// stops the sketch from starting on our board, see DI-24.) Same settings and scaling as
// Arduino_LSM6DSOX, which the Modulino library uses, so the data matches the training data.
const uint8_t IMU_ADDR = 0x6A;
bool moveOk = false;
float moveRing[MOVE_WINDOW * MOVE_AXES];
float moveWin[EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE];
uint32_t moveCount = 0, moveSince = 0, lastMoveUs = 0, lastMoveRetryMs = 0;
String imuBatch;

uint8_t gainCode = 4;
bool lightOk = false;
String batch;
uint32_t lastFlushMs = 0, lastPollUs = 0, lastRetryMs = 0, dimSinceMs = 0;

bool i2cWrite(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire1.beginTransmission(addr);
  Wire1.write(reg);
  Wire1.write(val);
  return Wire1.endTransmission() == 0;
}

bool i2cRead(uint8_t addr, uint8_t reg, uint8_t* buf, size_t len) {
  Wire1.beginTransmission(addr);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(addr, len) != len) return false;
  for (size_t i = 0; i < len; i++) buf[i] = Wire1.read();
  return true;
}

bool imuBegin() {
  uint8_t id = 0;
  if (!i2cRead(IMU_ADDR, 0x0F, &id, 1) || !(id == 0x6C || id == 0x69)) return false;   // WHO_AM_I
  i2cWrite(IMU_ADDR, 0x11, 0x4C);   // CTRL2_G: gyro 104 Hz, 2000 dps
  i2cWrite(IMU_ADDR, 0x10, 0x4A);   // CTRL1_XL: accel 104 Hz, +-4 g
  i2cWrite(IMU_ADDR, 0x16, 0x00);   // CTRL7_G
  return i2cWrite(IMU_ADDR, 0x17, 0x09);   // CTRL8_XL
}

// accX/Y/Z in g, gyrX/Y/Z in deg/s (ModulinoMovement getX/Y/Z and getRoll/Pitch/Yaw).
bool imuRead(float v[6]) {
  uint8_t d[12];
  if (!i2cRead(IMU_ADDR, 0x22, d, sizeof(d))) return false;   // OUTX_L_G .. OUTZ_H_XL
  for (int i = 0; i < 3; i++) {
    int16_t g = (int16_t)(d[2 * i] | d[2 * i + 1] << 8);
    int16_t a = (int16_t)(d[6 + 2 * i] | d[6 + 2 * i + 1] << 8);
    v[i] = a * 4.0f / 32768.0f;
    v[3 + i] = g * 2000.0f / 32768.0f;
  }
  return true;
}

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

// ---- Heart rate: MAX30102 at 0x57 -------------------------------------------------------------------
const uint8_t HR_ADDR = 0x57;
const uint32_t HR_MIN_IR = 5000, HR_MAX_IR = 260000;   // fingertip present / saturated (teammate's limits)
const uint16_t HR_RATE = 100;                          // samples/s
const uint8_t HR_INTERVALS = 5;
TwoWire* hrBus = nullptr;
const char* hrBusName = "";
bool hrOk = false;
uint32_t hrLastPollMs = 0, hrLastRetryMs = 0, hrLastReportMs = 0, hrLastSampleMs = 0, hrIr = 0;

bool busWrite(TwoWire& w, uint8_t addr, const uint8_t* buf, size_t len) {
  w.beginTransmission(addr);
  w.write(buf, len);
  return w.endTransmission() == 0;
}

bool busRead(TwoWire& w, uint8_t addr, uint8_t reg, uint8_t* buf, size_t len) {
  w.beginTransmission(addr);
  w.write(reg);
  if (w.endTransmission(false) != 0) return false;
  if (w.requestFrom(addr, len) != len) return false;
  for (size_t i = 0; i < len; i++) buf[i] = w.read();
  return true;
}

bool hrWrite(uint8_t reg, uint8_t val) {
  uint8_t b[2] = {reg, val};
  return busWrite(*hrBus, HR_ADDR, b, 2);
}

bool busHas(TwoWire& w, uint8_t addr) {
  w.beginTransmission(addr);
  return w.endTransmission() == 0;
}

String scanBus(TwoWire& w) {
  String s;
  for (uint8_t a = 0x08; a < 0x78; a++)
    if (busHas(w, a)) { s += " 0x"; s += String(a, HEX); }
  return s.length() ? s : String(" none");
}

// --- the teammate's beat detector (FlickerGuard_IDE_Pulse.ino), unchanged apart from names ---
uint16_t contactSamples = 0;
uint32_t sampleNumber = 0, lastBeat = 0;
uint16_t intervals[HR_INTERVALS] = {};
uint8_t filled = 0, slot = 0;
float smoothIR = 0, dcIR = 0, envelope = 0;
bool aboveThreshold = false;

void clearIntervals() {
  filled = 0;
  slot = 0;
  lastBeat = 0;
}

int estimateBpm(bool requireSteady) {
  if (!filled || sampleNumber - lastBeat > 180) return 0;
  if (requireSteady && filled < HR_INTERVALS) return 0;
  uint16_t sorted[HR_INTERVALS];
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
  return (60 * HR_RATE + median / 2) / median;
}

void readSample(uint32_t value) {
  hrIr = value;
  ++sampleNumber;
  if (value < HR_MIN_IR || value >= HR_MAX_IR) {
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
  if (contactSamples < 2 * HR_RATE) {
    ++contactSamples;
    return;
  }
  if (lastBeat && sampleNumber - lastBeat > 180) clearIntervals();
  if (!beat) return;
  if (lastBeat) {
    const uint32_t gap = sampleNumber - lastBeat;
    if (gap < 30) return;
    intervals[slot] = gap;
    slot = (slot + 1) % HR_INTERVALS;
    if (filled < HR_INTERVALS) ++filled;
  }
  lastBeat = sampleNumber;
}
// --- end of the teammate's detector ---

bool hrConfigure() {
  uint8_t id = 0;
  if (!busRead(*hrBus, HR_ADDR, 0xFF, &id, 1) || id != 0x15) return false;   // MAX30102 part ID
  hrWrite(0x09, 0x40);              // reset
  delay(10);
  hrWrite(0x08, 0x10);              // FIFO: no averaging, rollover on
  hrWrite(0x0A, 0x27);              // ADC 4096 nA, 100 samples/s, 411 us (18-bit): as the teammate's setup()
  hrWrite(0x0C, 0x00);              // red LED off
  hrWrite(0x0D, 0x24);              // IR LED ~7 mA
  hrWrite(0x09, 0x03);              // SpO2 mode (red + IR slots; only IR is used)
  hrWrite(0x04, 0); hrWrite(0x05, 0); hrWrite(0x06, 0);   // clear FIFO pointers
  contactSamples = 0;
  clearIntervals();
  return true;
}

bool hrBegin() {
  struct { TwoWire* w; const char* name; } buses[] = {
    {&Wire, "Wire (header SDA/SCL)"}, {&Wire2, "Wire2 (A4/A5)"}, {&Wire1, "Wire1 (Qwiic)"}};
  for (auto& b : buses) {
    if (b.w != &Wire1) { b.w->begin(); b.w->setClock(400000); }
    if (!busHas(*b.w, HR_ADDR)) continue;
    hrBus = b.w;
    hrBusName = b.name;
    if (hrConfigure()) return true;
  }
  hrBus = nullptr;
  return false;
}

void hrPoll() {
  uint8_t p[3];
  if (!busRead(*hrBus, HR_ADDR, 0x04, p, 3)) { hrOk = false; info("[mcu] heart rate sensor stopped answering"); return; }
  if (p[1]) { contactSamples = 0; clearIntervals(); }   // FIFO overflowed: samples were lost, restart
  int n = (p[0] - p[2]) & 0x1F;
  while (n > 0) {
    int k = n > 5 ? 5 : n;
    uint8_t d[30];
    if (!busRead(*hrBus, HR_ADDR, 0x07, d, k * 6)) return;
    for (int i = 0; i < k; i++)
      readSample(((uint32_t)d[i * 6 + 3] << 16 | (uint32_t)d[i * 6 + 4] << 8 | d[i * 6 + 5]) & 0x3FFFF);
    n -= k;
  }
  hrLastSampleMs = millis();
}

void hrReport() {
  int quality;
  if (hrIr < HR_MIN_IR) quality = 0;
  else if (hrIr >= HR_MAX_IR) quality = 1;
  else quality = estimateBpm(true) ? 3 : 2;
  Bridge.notify("hr", estimateBpm(true), estimateBpm(false), (int)hrIr, quality);
}

// ---- Modulino Buzzer: 0x1E (the library's 0x3C / 2), command = freq_hz (uint32 LE) + ms (uint32 LE) ----
const uint8_t BUZZER_ADDR = 0x1E;
TwoWire* buzzBus = nullptr;

int buzz(int freq, int ms) {
  if (!buzzBus) return 0;
  uint8_t b[8];
  uint32_t f = freq, l = ms;
  memcpy(&b[0], &f, 4);
  memcpy(&b[4], &l, 4);
  return busWrite(*buzzBus, BUZZER_ADDR, b, 8) ? 1 : 0;
}

void info(const String& s) {
  Bridge.notify("info", s);
  Monitor.println(s);
}

void sampleMovement(uint32_t nowMs) {
  float v[MOVE_AXES];
  if (!imuRead(v)) {
    moveOk = false;
    info("[mcu] Modulino Movement stopped answering (Qwiic cable?)");
    return;
  }
  memcpy(&moveRing[(moveCount % MOVE_WINDOW) * MOVE_AXES], v, sizeof(v));
  moveCount++;
  moveSince++;
  imuBatch += nowMs;
  for (int i = 0; i < MOVE_AXES; i++) { imuBatch += ','; imuBatch += String(v[i], i < 3 ? 4 : 2); }
  imuBatch += ';';
}

void classifyMovement() {
  // Oldest sample first, as Edge Impulse expects.
  for (int i = 0; i < MOVE_WINDOW; i++) {
    uint32_t src = (moveCount + i) % MOVE_WINDOW;
    memcpy(&moveWin[i * MOVE_AXES], &moveRing[src * MOVE_AXES], MOVE_AXES * sizeof(float));
  }
  signal_t signal;
  if (numpy::signal_from_buffer(moveWin, EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE, &signal) != 0) return;
  ei_impulse_result_t result = {0};
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    info(String("[mcu] movement model error ") + (int)err);
    return;
  }
  String s;
  for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    if (i) s += ',';
    s += result.classification[i].label;
    s += ':';
    s += String(result.classification[i].value, 3);
  }
  Bridge.notify("m", s, (int)(result.timing.dsp_us), (int)(result.timing.classification_us));
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  matrixBegin();
  matrixSetGrayscaleBits(3);
  showStatus(0, 0);
  Bridge.provide_safe("show", showStatus);
  Wire1.begin();               // Qwiic connector = Wire1 on the UNO Q
  Wire1.setClock(400000);
  batch.reserve(1024);
  imuBatch.reserve(512);
  lightOk = lightBegin();
  moveOk = imuBegin();
  lastMoveUs = micros();
  hrOk = hrBegin();
  if (busHas(Wire1, BUZZER_ADDR)) buzzBus = &Wire1;
  else if (busHas(Wire, BUZZER_ADDR)) buzzBus = &Wire;
  else if (busHas(Wire2, BUZZER_ADDR)) buzzBus = &Wire2;
  Bridge.provide_safe("buzz", buzz);
  info(String("[mcu] I2C scan: Wire1 (Qwiic):") + scanBus(Wire1) + " · Wire (D20/D21):" + scanBus(Wire) +
       " · Wire2 (A4/A5):" + scanBus(Wire2));
  info(String("[mcu] heart rate sensor (MAX30102): ") + (hrOk ? String("OK on ") + hrBusName : String("MISSING")) +
       ", buzzer (Modulino Buzzer 0x1E): " + (buzzBus ? "OK" : "MISSING"));
  info(String("[mcu] flashguard booted. Modulino Light: ") + (lightOk ? "OK" : "MISSING (Qwiic cable?)") +
       ", Modulino Movement: " + (moveOk ? "OK" : "MISSING") + ". Movement model: " + EI_CLASSIFIER_PROJECT_NAME +
       " (" + EI_CLASSIFIER_LABEL_COUNT + " classes, " + EI_CLASSIFIER_FREQUENCY + " Hz, " +
       (EI_CLASSIFIER_RAW_SAMPLE_COUNT / EI_CLASSIFIER_FREQUENCY) + " s window)");
}

void loop() {
  uint32_t nowMs = millis(), nowUs = micros();

  // Heart rate: drain the sensor's FIFO every 10 ms (it samples at 100/s on its own clock).
  if (hrOk) {
    if (nowMs - hrLastPollMs >= 10) { hrLastPollMs = nowMs; hrPoll(); }
    if (nowMs - hrLastReportMs >= 1000) { hrLastReportMs = nowMs; hrReport(); }
  } else if (nowMs - hrLastRetryMs >= 3000) {
    hrLastRetryMs = nowMs;
    if ((hrOk = hrBegin())) info(String("[mcu] heart rate sensor connected on ") + hrBusName);
  }

  // Movement: 4 Hz sampling, classification every MOVE_EVERY samples once the window is full.
  if (moveOk) {
    if (nowUs - lastMoveUs >= MOVE_PERIOD_US) {
      lastMoveUs = (nowUs - lastMoveUs >= 3 * MOVE_PERIOD_US) ? nowUs : lastMoveUs + MOVE_PERIOD_US;
      sampleMovement(nowMs);
    }
    if (moveCount >= (uint32_t)MOVE_WINDOW && moveSince >= (uint32_t)MOVE_EVERY) {
      moveSince = 0;
      classifyMovement();
    }
  } else if (nowMs - lastMoveRetryMs >= 3000) {
    lastMoveRetryMs = nowMs;
    if ((moveOk = imuBegin())) { lastMoveUs = micros(); info("[mcu] Modulino Movement connected"); }
  }

  if (!lightOk) {
    if (nowMs - lastRetryMs >= 1000) {
      lastRetryMs = nowMs;
      if ((lightOk = lightBegin())) info("[mcu] Modulino Light connected");
    }
  } else if (nowUs - lastPollUs >= POLL_US) {
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
    }
  }

  if (nowMs - lastFlushMs >= FLUSH_MS) {
    lastFlushMs = nowMs;
    if (batch.length()) { Bridge.notify("s", batch); batch = ""; }
    if (imuBatch.length()) { Bridge.notify("imu", imuBatch); imuBatch = ""; }
  }
}
