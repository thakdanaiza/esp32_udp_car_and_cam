#include <WiFi.h>
#include <esp_now.h>
#include <ESP32Servo.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_AS5600.h>
#include <Wire.h>

// ===== Pins =====
static const int drvPin = 25;
static const int strPin = 26;

#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22

// ===== IIR filter =====
#define IIR_ALPHA_W 0.3f

// ===== Objects =====
Servo drv;
Servo str;
Adafruit_MPU6050 mpu;
Adafruit_AS5600  as5600;

// ===== AS5600 state =====
bool     as5600_ok    = false;
uint16_t last_raw     = 0;
int32_t  turn_counts  = 0;
uint32_t last_angle_ms = 0;
float    omega_deg_s  = 0.0f;

// ===== Packets =====
typedef struct {
  int16_t throttle;
  int16_t steering;
} ControlPacket;

typedef struct {
  float   ax, ay, az;
  float   gx, gy, gz;
  float   angle_deg;
  float   omega_deg_s;
  int32_t turn_counts;
} TelemetryPacket;

ControlPacket   rx;
TelemetryPacket telePkt;

uint8_t broadcastAddr[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

uint32_t lastTx    = 0;
uint32_t lastPrint = 0;
const uint32_t TX_INTERVAL    = 50;
const uint32_t PRINT_INTERVAL = 100;

// ===== ESP-NOW receive =====
void onReceive(const esp_now_recv_info_t *info,
               const uint8_t *data,
               int len) {
  if (len == sizeof(ControlPacket)) {
    memcpy(&rx, data, sizeof(rx));
    drv.writeMicroseconds(rx.throttle);
    str.write(rx.steering);
  }
}

// ===== AS5600 init =====
static void as5600Init() {
  as5600_ok = as5600.begin();
  if (!as5600_ok) {
    Serial.println("AS5600 not found. Continuing without encoder.");
    return;
  }
  Serial.println("AS5600 found!");
  last_raw      = as5600.getRawAngle();
  turn_counts   = last_raw;
  last_angle_ms = millis();
  omega_deg_s   = 0.0f;
}

// ===== AS5600 update =====
static void updateAS5600() {
  if (!as5600_ok) return;

  uint32_t now = millis();
  uint16_t raw = as5600.getRawAngle();
  int32_t  diff = (int32_t)raw - (int32_t)last_raw;

  if (diff >  2048) diff -= 4096;
  if (diff < -2048) diff += 4096;

  turn_counts += diff;

  uint32_t dt_ms = now - last_angle_ms;
  if (dt_ms > 0) {
    float dt  = (float)dt_ms / 1000.0f;
    float deg = (float)diff * (360.0f / 4096.0f);
    float w   = deg / dt;
    omega_deg_s = IIR_ALPHA_W * w + (1.0f - IIR_ALPHA_W) * omega_deg_s;
  }

  last_raw      = raw;
  last_angle_ms = now;
}

// ===== Setup =====
void setup() {
  Serial.begin(115200);

  drv.attach(drvPin, 1000, 2000);
  str.attach(strPin);
  drv.writeMicroseconds(1500);
  str.write(100);

  delay(3000); // arm ESC

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  if (!mpu.begin()) {
    Serial.println("MPU6050 not found");
    while (1);
  }
  Serial.println("MPU6050 found!");

  as5600Init();

  WiFi.mode(WIFI_STA);
  esp_now_init();
  esp_now_register_recv_cb(onReceive);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcastAddr, 6);
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  Serial.println("CAR ready");
}

// ===== Loop =====
void loop() {
  // Read MPU6050
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  // Update AS5600
  updateAS5600();

  // Build telemetry packet
  telePkt.ax          = a.acceleration.x;
  telePkt.ay          = a.acceleration.y;
  telePkt.az          = a.acceleration.z;
  telePkt.gx          = g.gyro.x;
  telePkt.gy          = g.gyro.y;
  telePkt.gz          = g.gyro.z;
  telePkt.angle_deg   = (float)last_raw * (360.0f / 4096.0f);
  telePkt.omega_deg_s = omega_deg_s;
  telePkt.turn_counts = turn_counts;

  // Send telemetry via ESP-NOW
  if (millis() - lastTx >= TX_INTERVAL) {
    lastTx = millis();
    esp_now_send(broadcastAddr,
                 (uint8_t*)&telePkt,
                 sizeof(telePkt));
  }

  // Debug print
  if (millis() - lastPrint >= PRINT_INTERVAL) {
    lastPrint = millis();
    Serial.printf(
      "CTRL T:%d S:%d | IMU A[%.2f %.2f %.2f] G[%.2f %.2f %.2f] | ENC deg=%.1f w=%.1fdeg/s turns=%ld\n",
      rx.throttle, rx.steering,
      telePkt.ax, telePkt.ay, telePkt.az,
      telePkt.gx, telePkt.gy, telePkt.gz,
      telePkt.angle_deg, telePkt.omega_deg_s, (long)telePkt.turn_counts
    );
  }
}
