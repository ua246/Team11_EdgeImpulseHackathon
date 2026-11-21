# Flicker detector test rig (KiCad)

A test rig for using the heart beat module as a fast light detector. Open `detector-test.kicad_pro`
in KiCad 10, or read `detector-test.pdf`. The rig is used by
[`apps/detector-test`](../../apps/detector-test/), which also explains the test.

The project includes `team11.kicad_sym`, the custom UNO Q header and heart beat module symbols.
KiCad's electrical rules check passes with 0 errors and 0 warnings.

## Parts

| Ref | Part | Value | Notes |
|---|---|---|---|
| M1 | Heart beat module | – | Power from **3V3**. Cover its LED with black tape |
| R1 | Resistor | 100 kΩ | With C1: low-pass filter at about 72 Hz, feeding A3 |
| C1 | Capacitor | 22 nF | Ceramic |
| D1 | LED | white, 5 mm | Test light. White matches real-world light sources |
| R3 | Resistor | 100 Ω | Sets the LED current to about 20 mA from 5V |
| Q1 | NPN transistor | 2N3904 | Any small NPN works (BC547, 2N2222); **check the pinout** (BC547 is C-B-E) |
| R2 | Resistor | 1 kΩ | Base resistor, driven from D3 |
| Q2 | NPN phototransistor | – | *Optional, not fitted.* Fallback detector on A1 |
| R4 | Resistor | 10 kΩ | *Optional, not fitted.* Load for Q2 |
| – | Black tube, 3–5 cm | – | Drinking straw wrapped in black tape. Holds D1 facing the detector, light-tight |

| UNO Q pin | Net | Use |
|---|---|---|
| A1 | PT_OUT | optional phototransistor |
| A2 | DET_RAW | module output, unfiltered |
| A3 | DET_FILT | module output after R1/C1 |
| D3 | LED_DRV | test LED drive |
| 3V3 | – | module power |
| 5V | – | LED power |
| GND | – | ground |

**Without a transistor:** use a red LED with 150 Ω straight from D3 to GND (about 9 mA). Its
colour is less realistic, and IR-only detectors respond to it more than to white light.

**On the wearable:** keep R1/C1 and read A3 if the test says so. Replace the tube-and-LED setup with
a short black tube in front of the detector, pointing where the wearer looks (DI-18).
