#include <Wire.h>
#include <Adafruit_AS5600.h>

#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22

#define IIR_ALPHA_W 0.3f

Adafruit_AS5600 as5600;

bool as5600_ok = false;

uint16_t last_raw = 0;
int32_t turn_counts = 0;
uint32_t last_angle_ms = 0;

float omega_deg_s = 0.0f;

void handleSerial(){}

static void as5600Init()
{
    if (PIN_I2C_SDA >= 0 && PIN_I2C_SCL >= 0)
        Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    else
        Wire.begin();

    as5600_ok = as5600.begin();

    if (!as5600_ok)
    {
        Serial.println("AS5600 not found (check I2C wiring/address). Continuing without encoder.");
        return;
    }

    Serial.println("AS5600 found!");

    last_raw = as5600.getRawAngle();
    turn_counts = last_raw;
    last_angle_ms = millis();
    omega_deg_s = 0.0f;
}

static void updateAS5600()
{
    if (!as5600_ok) return;

    uint32_t now = millis();

    uint16_t raw = as5600.getRawAngle();
    int32_t diff = (int32_t)raw - (int32_t)last_raw;

    if (diff > 2048) diff -= 4096;
    if (diff < -2048) diff += 4096;

    turn_counts += diff;

    uint32_t dt_ms = now - last_angle_ms;

    if (dt_ms > 0)
    {
        float dt = (float)dt_ms / 1000.0f;
        float deg = (float)diff * (360.0f / 4096.0f);

        float w = deg / dt;

        omega_deg_s = IIR_ALPHA_W * w + (1.0f - IIR_ALPHA_W) * omega_deg_s;
    }

    last_raw = raw;
    last_angle_ms = now;
}

void setup()
{
    Serial.begin(115200);
    delay(200);

    as5600Init();

    Serial.println("Ready.");
}

void loop()
{
    handleSerial();

    updateAS5600();

    static uint32_t lastPrint = 0;

    if (millis() - lastPrint >= 50)
    {
        lastPrint = millis();

        if (as5600_ok)
        {
            uint16_t raw = last_raw;
            float angle_deg = (float)raw * (360.0f / 4096.0f);

            bool mag = as5600.isMagnetDetected();
            bool mh = as5600.isAGCminGainOverflow();
            bool ml = as5600.isAGCmaxGainOverflow();

            uint8_t agc = as5600.getAGC();
            uint16_t magnitude = as5600.getMagnitude();

            Serial.printf(
                "AS5600 raw=%u deg=%.1f w=%.1fdeg/s Magnet=%s MH=%d ML=%d AGC=%u Mag=%u\n",
                raw, angle_deg, omega_deg_s,
                mag ? "YES" : "NO",
                (int)mh, (int)ml,
                (unsigned)agc, (unsigned)magnitude
            );
        }
    }

    delay(5);