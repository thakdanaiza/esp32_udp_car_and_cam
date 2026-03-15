#include <WiFi.h>
#include <esp_now.h>

typedef struct {
  int16_t throttle;   // -1000 .. +1000
  int16_t steering;   // -1000 .. +1000
  int16_t brake;      // -1000 .. +1000
  bool N_but;
  bool R_but;
} ControlPacket;


typedef struct {
  float   ax, ay, az;
  float   gx, gy, gz;
  float   angle_deg;
  float   omega_deg_s;
  int32_t turn_counts;
} TelemetryPacket;

ControlPacket    pkt;
TelemetryPacket  teleRx;

// broadcast
uint8_t broadcastAddr[] = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};

// timing
const uint32_t TX_INTERVAL_MS = 50;
uint32_t lastTxTime = 0;

uint32_t lastTx = 0;

int16_t mapByteSteer(int v) {
  // v: 0..255  →  -1000..+1000
  v = constrain(v, 0, 255);
  return map(v, 0, 255, 75, 125);
}

int16_t mapByteThrot(int v) {
  v = constrain(v, 0, 255);
  return map(v, 0, 255, 1500, 1750);
}

void onReceive(const esp_now_recv_info_t *info,
               const uint8_t *data,
               int len) {
  if (len == sizeof(TelemetryPacket)) {
    memcpy(&teleRx, data, sizeof(teleRx));

    Serial.printf(
      "TELE,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.2f,%.2f,%ld\n",
      teleRx.ax, teleRx.ay, teleRx.az,
      teleRx.gx, teleRx.gy, teleRx.gz,
      teleRx.angle_deg, teleRx.omega_deg_s, (long)teleRx.turn_counts
    );
  }
}

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    while (1);
  }

  esp_now_register_recv_cb(onReceive);
  
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcastAddr, 6);
  peer.channel = 0;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  Serial.println("JOY ready. Send <steering,throttle>");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("<") && cmd.endsWith(">")) {
      cmd = cmd.substring(1, cmd.length() - 1);

      int commaIdx = cmd.indexOf(',');
      if (commaIdx > 0) {
        int steeringRaw = cmd.substring(0, commaIdx).toInt();
        int throttleRaw = cmd.substring(commaIdx + 1).toInt();

        pkt.steering = mapByteSteer(steeringRaw);
        pkt.throttle = mapByteThrot(throttleRaw);

        // esp_now_send(
        //   broadcastAddr,
        //   (uint8_t*)&pkt,
        //   sizeof(pkt)
        // );
      }
    }
  }
  /* ---------- 2) Send ESP-NOW every 50 ms ---------- */
  if (millis() - lastTxTime >= TX_INTERVAL_MS) {
    lastTxTime = millis();

    esp_now_send(
      broadcastAddr,
      (uint8_t*)&pkt,
      sizeof(pkt)
    );

    // Serial.printf(
    //   "TX steer:%d thr:%d\n",
    //   pkt.steering,
    //   pkt.throttle
    // );
  }

}
