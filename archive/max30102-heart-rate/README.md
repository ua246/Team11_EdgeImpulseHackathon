# MAX30102 Heart Rate

A standalone Arduino App Lab prototype for live fingertip pulse estimation. The UNO Q microcontroller samples the IR signal over I²C and sends it to Python for beat detection. Read BPM in the App Lab Console under **Python**.

| UNO Q Qwiic | MAX30102 breakout |
| --- | --- |
| 3.3 V | VIN |
| GND | GND |
| SDA | SDA |
| SCL | SCL |

Use a Qwiic breakout cable and wire with power disconnected. Verify your breakout supports a 3.3 V supply on VIN. Use the pins marked VIN, SDA, SCL and GND. Leave all other sensor pins disconnected. The sketch uses the Qwiic connector's Wire1 bus.

ZIP the contents of this app folder with app.yaml at the ZIP root. In **Apps**, choose **+ → Import or install App** and select the ZIP. Press **Run**, open the **Python** console, then hold a fingertip gently over the optical window for about 8–10 seconds.

If the sensor is missing, check its four connections, especially SDA and SCL. If the app reports a weak or unstable pulse, hold still and try changing finger position or pressure. If contact consistently produces IR below 5000, adjust MIN_IR in python/main.py based on your breakout's signal.

Motion can invalidate the BPM estimate. This app is intended for hackathon bench use.
