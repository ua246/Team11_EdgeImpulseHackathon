// Team 11 · movement model training recorder (teammate's sketch, kept as the model's input recipe)
//
// This is how the data for the "Wearable Movement Monitoring (More Classes)" Edge Impulse model
// (project 1170305) was recorded: Modulino Movement at 4 Hz, printed over Serial as
// accX,accY,accZ (g) and gyrX,gyrY,gyrZ (deg/s). flashguard's sketch reproduces exactly this input.
// Note: it uses the Arduino_Modulino library, which stops sketches starting on our UNO Q with board
// package 1.1.0 (DI-24); to record more data on the UNO Q, use flashguard's movement.<time>.csv.

#include <Modulino.h>

ModulinoMovement movement;

unsigned long lastSample = 0;
unsigned long sampleCount = 0;
unsigned long startTime = 0;

const unsigned long SAMPLE_INTERVAL = 250000; // 4 Hz

void setup() {
    Serial.begin(115200);

    Modulino.begin();

    if (!movement.begin()) {
        Serial.println("Sensor error");
        while (1);
    }

    delay(1000);

    Serial.println("accX,accY,accZ,gyrX,gyrY,gyrZ");

    startTime = micros();
}

void loop() {
    unsigned long now = micros();

    if (now - lastSample >= SAMPLE_INTERVAL) {
        lastSample = now;

        if (movement.update()) {
            Serial.print(movement.getX(), 4);
            Serial.print(",");
            Serial.print(movement.getY(), 4);
            Serial.print(",");
            Serial.print(movement.getZ(), 4);
            Serial.print(",");
            Serial.print(movement.getRoll(), 3);
            Serial.print(",");
            Serial.print(movement.getPitch(), 3);
            Serial.print(",");
            Serial.println(movement.getYaw(), 3);

            sampleCount++;
        }
    }
}