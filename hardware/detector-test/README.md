# Flicker sensor test rig (KiCad)

One sheet with the test setups for both candidate flicker sensors. Open `detector-test.kicad_pro`
in KiCad 10, or read `detector-test.pdf`.
- **Heart beat module as a fast light detector:** used by
  [`apps/detector-test`](../../apps/detector-test/).
- **Arduino USB Camera:** used by [`apps/camera-test`](../../apps/camera-test/).

Both tests share the same test light source (D3 → R2 → Q1 → D1). Each app's README explains its
test.

The project includes `team11.kicad_sym`, with custom symbols for the UNO Q, heart beat module, USB-C
hub, USB camera and power bank. KiCad's electrical rules check passes with 0 errors and 0 warnings.

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
| HUB1 | USB-C hub | multi-port, with PD input | Camera test. The UNO Q's USB-C goes to the hub's host port |
| CAM1 | Arduino USB Camera | TPX00246 | Camera test. On the hub's USB-A port; 250 mA (410 mA with the ring light, which stays **off**) |
| PB1 | Power bank | USB-C PD | Feeds the hub's PD input, which powers the UNO Q and the camera |

| UNO Q pin | Net | Use |
|---|---|---|
| A1 | PT_OUT | optional phototransistor |
| A2 | DET_RAW | module output, unfiltered |
| A3 | DET_FILT | module output after R1/C1 |
| D3 | LED_DRV | test LED drive |
| 3V3 | – | module power |
| 5V | – | LED power |
| GND | – | ground |
| USB-C | USB_HOST | to the USB-C hub (camera test) |

## Camera test setup

1. Plug the UNO Q's USB-C into the hub's host port, the camera into a USB-A port, and the power
   bank into the hub's PD input.
2. Wire the test light source (D3, R2, Q1, R3, D1). M1, R1/C1 and Q2/R4 aren't needed.
3. Take D1 out of its tube. Aim the camera at D1 from 10–30 cm, or at a white card that D1 lights.
   This light path is the only "connection" between the camera and the LED.
4. Run `UNOQ_APP=camera-test tools/unoq dev`.

**Without a transistor:** use a red LED with 150 Ω straight from D3 to GND (about 9 mA). Its
colour is less realistic, and IR-only detectors respond to it more than to white light.

**On the wearable:** keep R1/C1 and read A3 if the test says so. Replace the tube-and-LED setup with
a short black tube in front of the detector, pointing where the wearer looks (DI-18).
