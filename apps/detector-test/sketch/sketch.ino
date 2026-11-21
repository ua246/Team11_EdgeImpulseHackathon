// Team 11 · detector-test · MCU side
//
// Test rig: hardware/detector-test/detector-test.kicad_sch
//   D3 -> R2 -> Q1 drives the white test LED D1, which shines into the heart beat module.
//   A2 = module output (raw), A3 = module output after the R1/C1 low-pass, A1 = optional phototransistor.
//
// The test plan lives in python/main.py. This sketch only offers two Bridge functions:
//   capture(duration_ms, period_us, on_start_us, on_len_us, rate_hz) -> "n,elapsed_us,late"
//       Drives the LED in a repeating pattern while sampling A1, A2, A3 at rate_hz into RAM.
//       The LED is on whenever (t mod period_us) is in [on_start_us, on_start_us + on_len_us).
//       No Bridge traffic happens during a capture, so the timing is not disturbed.
//   chunk(channel, start, count) -> hex string, 3 hex digits per sample (12-bit values)

#include <Arduino_RouterBridge.h>

const int LED_PIN = D3;
const int CH_PINS[] = {A1, A2, A3};   // 0 = optional phototransistor, 1 = raw module, 2 = filtered module
const int N_CH = 3;
const int MAX_SAMPLES = 2500;         // 2.5 s at 1000 samples/s

uint16_t buf[N_CH][MAX_SAMPLES];
int nSamples = 0;

String capture(long duration_ms, long period_us, long on_start_us, long on_len_us, long rate_hz) {
  if (rate_hz < 1) rate_hz = 1;
  if (period_us < 1) period_us = 1;
  long n = duration_ms * rate_hz / 1000;
  if (n > MAX_SAMPLES) n = MAX_SAMPLES;
  if (n < 1) n = 1;
  const uint32_t interval = 1000000UL / (uint32_t)rate_hz;

  bool ledOn = false;
  digitalWrite(LED_PIN, LOW);
  long late = 0;
  const uint32_t t0 = micros();
  uint32_t next = t0;
  long i = 0;
  while (i < n) {
    const uint32_t now = micros();
    const uint32_t phase = (now - t0) % (uint32_t)period_us;
    const bool on = on_len_us > 0 && phase >= (uint32_t)on_start_us && phase < (uint32_t)(on_start_us + on_len_us);
    if (on != ledOn) {
      digitalWrite(LED_PIN, on ? HIGH : LOW);
      ledOn = on;
    }
    if ((int32_t)(now - next) >= 0) {
      if (now - next > 200) late++;
      for (int c = 0; c < N_CH; c++) buf[c][i] = analogRead(CH_PINS[c]);
      i++;
      next += interval;
    }
  }
  const uint32_t elapsed = micros() - t0;
  digitalWrite(LED_PIN, LOW);
  nSamples = n;
  return String(n) + "," + String(elapsed) + "," + String(late);
}

String chunk(int ch, int start, int count) {
  static const char HEX_DIGITS[] = "0123456789ABCDEF";
  String s;
  if (ch < 0 || ch >= N_CH || start < 0 || start >= nSamples) return s;
  int end = start + count;
  if (end > nSamples) end = nSamples;
  s.reserve((end - start) * 3);
  for (int i = start; i < end; i++) {
    const uint16_t v = buf[ch][i] & 0xFFF;
    s += HEX_DIGITS[v >> 8];
    s += HEX_DIGITS[(v >> 4) & 0xF];
    s += HEX_DIGITS[v & 0xF];
  }
  return s;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  analogReadResolution(12);
  Bridge.begin();
  Monitor.begin();
  Bridge.provide_safe("capture", capture);
  Bridge.provide_safe("chunk", chunk);
  Monitor.println("[mcu] detector-test ready: LED on D3, sampling A1/A2/A3");
}

void loop() {
  // Nothing: Python drives the test through capture() and chunk().
}
