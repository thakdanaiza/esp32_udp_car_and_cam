#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP32Servo.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_AS5600.h>
#include <Wire.h>

// ===== WiFi =====
const char* WIFI_SSID = "301/3_2.4G";
const char* WIFI_PASS = "357m19smith";

// ===== UDP Ports =====
const uint16_t UDP_CTRL_PORT = 5005;   // Receive control from PC
const uint16_t UDP_TELE_PORT = 5006;   // Send telemetry to PC

// ===== Pins =====
static const int drvPin = 25;
static const int strPin = 26;

#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22

// ===== IIR filter =====
#define IIR_ALPHA_W 0.3f

// ===== Objects =====
WiFiUDP      udp;
Servo        drv;
Servo        str;
Adafruit_MPU6050 mpu;
Adafruit_AS5600  as5600;

// ===== AS5600 state =====
bool     as5600_ok     = false;
uint16_t last_raw      = 0;
int32_t  turn_counts   = 0;
uint32_t last_angle_ms = 0;
float    omega_deg_s   = 0.0f;

// ===== Packets =====
#pragma pack(push, 1)
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
#pragma pack(pop)

ControlPacket   rx;
TelemetryPacket telePkt;

IPAddress pcIP;
bool      pcKnown  = false;

uint32_t lastTx    = 0;
uint32_t lastPrint = 0;
const uint32_t TX_INTERVAL    = 20;
const uint32_t PRINT_INTERVAL = 100;

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

  uint32_t now  = millis();
  uint16_t raw  = as5600.getRawAngle();
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

  // WiFi connect
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi connected. IP: %s\n", WiFi.localIP().toString().c_str());

  udp.begin(UDP_CTRL_PORT);
  Serial.printf("UDP listening on port %d\n", UDP_CTRL_PORT);
  Serial.println("CAR ready");
}

// ===== Loop =====
void loop() {
  // ---------- Receive control from PC ----------
  int pktSize = udp.parsePacket();
  if (pktSize == sizeof(ControlPacket)) {
    udp.read((uint8_t*)&rx, sizeof(rx));
    pcIP    = udp.remoteIP();
    pcKnown = true;

    drv.writeMicroseconds(rx.throttle);
    str.write(rx.steering);
  }

  // ---------- Read sensors ----------
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);
  updateAS5600();

  // ---------- Build telemetry ----------
  telePkt.ax          = a.acceleration.x;
  telePkt.ay          = a.acceleration.y;
  telePkt.az          = a.acceleration.z;
  telePkt.gx          = g.gyro.x;
  telePkt.gy          = g.gyro.y;
  telePkt.gz          = g.gyro.z;
  telePkt.angle_deg   = (float)last_raw * (360.0f / 4096.0f);
  telePkt.omega_deg_s = omega_deg_s;
  telePkt.turn_counts = turn_counts;

  // ---------- Send telemetry every 50ms ----------
  if (pcKnown && millis() - lastTx >= TX_INTERVAL) {
    lastTx = millis();
    udp.beginPacket(pcIP, UDP_TELE_PORT);
    udp.write((uint8_t*)&telePkt, sizeof(telePkt));
    udp.endPacket();
  }

  // ---------- Debug serial ----------
  if (millis() - lastPrint >= PRINT_INTERVAL) {
    lastPrint = millis();
    Serial.printf(
      "CTRL T:%d S:%d | IMU A[%.2f %.2f %.2f] G[%.2f %.2f %.2f] | ENC deg=%.1f w=%.1fdeg/s turns=%ld | PC:%s\n",
      rx.throttle, rx.steering,
      telePkt.ax, telePkt.ay, telePkt.az,
      telePkt.gx, telePkt.gy, telePkt.gz,
      telePkt.angle_deg, telePkt.omega_deg_s, (long)telePkt.turn_counts,
      pcKnown ? pcIP.toString().c_str() : "waiting..."
    );
  }
}
