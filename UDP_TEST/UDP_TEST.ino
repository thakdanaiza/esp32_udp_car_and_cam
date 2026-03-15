#include <WiFi.h>
#include <WiFiUdp.h>

const char* WIFI_SSID = "301/3_2.4G";
const char* WIFI_PASS = "357m19smith";

const uint16_t UDP_RECV_PORT = 5005;  // Receive from PC
const uint16_t UDP_SEND_PORT = 5006;  // Send back to PC

WiFiUDP udp;
IPAddress pcIP;
bool pcKnown = false;

uint32_t counter = 0;
uint32_t lastSend = 0;

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());

  udp.begin(UDP_RECV_PORT);
  Serial.printf("Listening on UDP port %d\n", UDP_RECV_PORT);
}

void loop() {
  // ---------- Receive packet from PC ----------
  int size = udp.parsePacket();
  if (size > 0) {
    char buf[64] = {};
    udp.read(buf, sizeof(buf) - 1);

    pcIP    = udp.remoteIP();
    pcKnown = true;

    Serial.printf("[RX] from %s  \"%s\"\n", pcIP.toString().c_str(), buf);

    // Echo back immediately
    udp.beginPacket(pcIP, UDP_SEND_PORT);
    udp.printf("ECHO: %s", buf);
    udp.endPacket();
  }

  // ---------- Send heartbeat every 1s ----------
  if (pcKnown && millis() - lastSend >= 1000) {
    lastSend = millis();
    char msg[32];
    snprintf(msg, sizeof(msg), "HB:%lu", counter++);

    udp.beginPacket(pcIP, UDP_SEND_PORT);
    udp.write((uint8_t*)msg, strlen(msg));
    udp.endPacket();

    Serial.printf("[TX] heartbeat \"%s\" → %s:%d\n", msg, pcIP.toString().c_str(), UDP_SEND_PORT);
  }
}
