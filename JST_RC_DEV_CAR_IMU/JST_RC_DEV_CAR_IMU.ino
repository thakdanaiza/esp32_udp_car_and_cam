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

uint8_t broadcastAddr[] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };

uint32_t lastTx = 0;
uint32_t lastPrint = 0;
const uint32_t TX_INTERVAL = 50;
const uint32_t PRINT_INTERVAL = 100;

int16_t initial_spd = 1500;
int16_t initial_str = 100;
int cur_spd = 0;


///////////test
float pedal_prev = 0;
float diff_pedal;
float k_acc_cmd = 0.1;  //after test move to class dynaic engine
float accel_cmd = 0.0;
float vel_cmd = 0.0;

int16_t mapByteSteer(int v) {
  // v: 0..255  →  -1000..+1000
  v = constrain(v, 0, 255);
  return map(v, 0, 255, 75, 125);
}

int16_t mapByteThrot(int v) {
  v = constrain(v, 0, 255);
  return map(v, 0, 255, 0, 255);
}

int16_t mapByteReverse(int v) {
  v = constrain(v, 0, 255);
  return map(v, 0, 255, 0, 255);
}

void onReceive(const esp_now_recv_info_t *info,
               const uint8_t *data,
               int len) {
  if (len == sizeof(ControlPacket)) {
    memcpy(&rx, data, sizeof(rx));

    //cal

    diff_pedal = (float)rx.throttle - pedal_prev;
    pedal_prev = (float)rx.throttle;

    if (pedal_prev > 0) {
      if(diff_pedal >0){
        accel_cmd += diff_pedal * k_acc_cmd; 
      }else if(diff_pedal < 0){
        accel_cmd += diff_pedal * k_acc_cmd*2.0;  
      }else{
        //accel = prev
        accel_cmd = 1.0*accel_cmd;
      }
           
    } else {
      if (vel_cmd <= 0.0) {
        accel_cmd = 0.0;
      } else {
        accel_cmd -= k_acc_cmd * 10.0;
        //accel_cmd =0.0;
      }
    }
      
    float vel_limit = 100.0*(pedal_prev/255.0);
    if (vel_cmd > vel_limit) {
      vel_cmd = vel_limit;
      accel_cmd =0.0;
    } else if (vel_cmd < 0.0) {
      vel_cmd = 0.0;
    }
    vel_cmd = vel_cmd + (accel_cmd * 0.05);

    // Drive the car
    cur_spd = map(vel_cmd, 0, 100, 1500, 2200);
    drv.writeMicroseconds(cur_spd);

    str.write(mapByteSteer(rx.steering));
  }
}

void setup() {
  Serial.begin(921600);

  drv.attach(drvPin, 1000, 2000);
  str.attach(strPin);
  drv.writeMicroseconds(initial_spd);
  cur_spd = initial_spd;
  str.write(initial_str);

  delay(3000);  // arm ESC

  Wire.begin();
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found");
    while (1)
      ;
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
                 (uint8_t *)&imuPkt,
                 sizeof(imuPkt));
  }

  // ===== PRINT DEBUG =====
  if (millis() - lastPrint >= PRINT_INTERVAL) {
    lastPrint = millis();

    // Serial.printf(
    //   "CTRL  T:%d  S:%d | IMU A[%.2f %.2f %.2f] G[%.2f %.2f %.2f]\n",
    //   rx.throttle, rx.steering,
    //   imuPkt.ax, imuPkt.ay, imuPkt.az,
    //   imuPkt.gx, imuPkt.gy, imuPkt.gz
    // );

    Serial.printf(
      "CTRL  T:%d  S:%d ",
      rx.throttle, rx.steering);
    Serial.printf(
      "CTRL  Pedal_prev:%.2f  d_pedal:%.2f  accel_cmd:%.2f  vel_cmd:%.2f cur_spd:%d\n",
      pedal_prev, diff_pedal, accel_cmd, vel_cmd, cur_spd);
  }
}
