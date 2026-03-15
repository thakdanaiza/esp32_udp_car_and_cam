#include <WiFi.h>
#include <esp_now.h>
#include <ESP32Servo.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Wire.h>

static const int drvPin = 25;
static const int strPin = 26;

Servo drv;
Servo str;
Adafruit_MPU6050 mpu;

typedef struct {
  int16_t throttle;
  int16_t steering;
} ControlPacket;

typedef struct {
  float ax, ay, az;
  float gx, gy, gz;
} ImuPacket;

ControlPacket rx;
ImuPacket imuPkt;

uint8_t broadcastAddr[] = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};

uint32_t lastTx   = 0;
uint32_t lastPrint = 0;
const uint32_t TX_INTERVAL    = 50;
const uint32_t PRINT_INTERVAL = 100;

void onReceive(const esp_now_recv_info_t *info,
               const uint8_t *data,
               int len) {
  if (len == sizeof(ControlPacket)) {
    memcpy(&rx, data, sizeof(rx));

    // Drive the car
    drv.writeMicroseconds(rx.throttle);
    str.write(rx.steering);
  }
}

void setup() {
  Serial.begin(115200);

  drv.attach(drvPin, 1000, 2000);
  str.attach(strPin);
  drv.writeMicroseconds(1500);
  str.write(100);

  delay(3000); // arm ESC

  Wire.begin();
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found");
    while (1);
  }

  WiFi.mode(WIFI_STA);
  esp_now_init();
  esp_now_register_recv_cb(onReceive);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcastAddr, 6);
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  Serial.println("CAR ready");
}

void loop() {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  imuPkt.ax = a.acceleration.x;
  imuPkt.ay = a.acceleration.y;
  imuPkt.az = a.acceleration.z;
  imuPkt.gx = g.gyro.x;
  imuPkt.gy = g.gyro.y;
  imuPkt.gz = g.gyro.z;

  // ===== Send IMU back =====
  if (millis() - lastTx >= TX_INTERVAL) {
    lastTx = millis();
    esp_now_send(broadcastAddr,
                 (uint8_t*)&imuPkt,
                 sizeof(imuPkt));
  }

  // ===== PRINT DEBUG =====
  if (millis() - lastPrint >= PRINT_INTERVAL) {
    lastPrint = millis();

    Serial.printf(
      "CTRL  T:%d  S:%d | IMU A[%.2f %.2f %.2f] G[%.2f %.2f %.2f]\n",
      rx.throttle, rx.steering,
      imuPkt.ax, imuPkt.ay, imuPkt.az,
      imuPkt.gx, imuPkt.gy, imuPkt.gz
    );
  }
}
