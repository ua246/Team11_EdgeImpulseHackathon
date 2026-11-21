# Modulino Light test rig (KiCad)

The test setup for [`apps/light-test`](../../apps/light-test/). Open `light-test.kicad_pro` in
KiCad 10, or read `light-test.pdf`.

The sketch flashes a white LED (D1) on D3 at known rates into the Modulino Light (M1), which sits on
the UNO Q's Qwiic connector. The only "connection" between them is the light path, drawn dashed.
KiCad's electrical rules check passes with 0 errors and 0 warnings. `team11.kicad_sym` holds the
custom symbols for the UNO Q and the Modulino Light.

## Parts

| Ref | Part | Value | Notes |
|---|---|---|---|
| J1 | Arduino UNO Q | – | Powered and flashed over USB-C from the laptop |
| M1 | Modulino Light | ABX00111 | LTR-381RGB, I2C address 0x53. On the Qwiic connector (bus `Wire1`) |
| – | Qwiic cable | JST-SH 4-pin | Comes with the Modulino. A Modulino Movement may stay on the chain |
| D1 | LED | white, 5 mm | Test light. White matches real-world light sources |
| R3 | Resistor | 220 Ω | LED current about 9 mA from 5V. Use 100 Ω (about 20 mA) if the test says the LED is too dim |
| Q1 | NPN transistor | 2N3904 | Any small NPN works (BC547, 2N2222); **check the pinout** (BC547 is C-B-E) |
| R2 | Resistor | 1 kΩ | Base resistor, driven from D3 (about 2.6 mA) |
| – | Black tube or box | – | E.g. a toilet-roll tube wrapped in black tape, or a small box. Holds D1 facing the sensor, light-tight |
| – | Paper | – | *Optional.* Between D1 and the sensor if the test reports saturation |

| UNO Q pin | Net | Use |
|---|---|---|
| Qwiic | QW_GND, QW_3V3, SDA1, SCL1 | Modulino Light |
| D3 | LED_DRV | test LED drive |
| 5V | – | LED power |
| GND | – | ground |

## Build

1. Plug the Modulino Light into the UNO Q's Qwiic connector.
2. On a breadboard: 5V → R3 → D1 anode; D1 cathode → Q1 collector; Q1 emitter → GND;
   D3 → R2 → Q1 base.
3. Point D1 at the sensor (the small clear chip on the Modulino), 1–3 cm away. Enclose both so no
   room light gets in.
4. Run `UNOQ_APP=light-test tools/unoq dev`.

**Without a transistor:** use a red LED with 150 Ω straight from D3 to GND (about 9 mA from the
3.3 V pin). A white LED barely lights from 3.3 V. The sketch's automatic gain and channel choice
cope with red light.

**On the wearable:** the Modulino Light faces forward on the cap brim, ideally at the end of a
short black tube so it sees where the wearer looks (DI-18).
