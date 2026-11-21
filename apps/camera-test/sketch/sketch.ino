// Team 11 · camera-test · MCU side
//
// Drives the test LED D1 (D3 -> R2 -> Q1, see hardware/detector-test) in a repeating pattern that
// Python sets with Bridge.call("led", period_us, on_us):
//   period_us = 0, on_us = 0   -> off
//   period_us = 0, on_us > 0   -> steady on
//   otherwise                  -> on for on_us at the start of every period_us
//                                 (a square wave when on_us = period_us / 2)
// The pattern runs in loop(), so it keeps going while Python records video. Edges can be up to
// about 1 ms late (the Bridge sleeps 1 ms between loop() runs); the average frequency is exact.

#include <Arduino_RouterBridge.h>

const int LED_PIN = D3;

uint32_t periodUs = 0, onUs = 0, t0 = 0;
bool ledOn = false;

int led(long period_us, long on_us) {
  periodUs = period_us > 0 ? (uint32_t)period_us : 0;
  onUs = on_us > 0 ? (uint32_t)on_us : 0;
  t0 = micros();
  return 1;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  Bridge.begin();
  Monitor.begin();
  Bridge.provide_safe("led", led);
  Monitor.println("[mcu] camera-test ready: test LED on D3");
}

void loop() {
  bool on;
  if (periodUs == 0) {
    on = onUs > 0;
  } else {
    on = ((micros() - t0) % periodUs) < onUs;
  }
  if (on != ledOn) {
    digitalWrite(LED_PIN, on ? HIGH : LOW);
    ledOn = on;
  }
}
