/*
  JST_CAM_STREAM
  Lean VGA JPEG streaming over chunked UDP WiFi.
  No web server, no SD card, no motion detection.

  Protocol:
    PC → ESP32 (UDP port 8080): 1 byte = JPEG quality (1-63)
    ESP32 → PC (UDP port 8081): chunked frames
      Each chunk: [2B LE frame_id][1B chunk_index][1B total_chunks][payload]
      Max payload per chunk ~1400 bytes to fit in one WiFi MTU.

  Board: ESP32-S3 CAM
*/

#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_camera.h"

// ===== WiFi =====
const char* WIFI_SSID = "301/3_2.4G";
const char* WIFI_PASS = "357m19smith";

// ===== UDP =====
const uint16_t UDP_CMD_PORT    = 8080;   // receive quality commands
const uint16_t UDP_STREAM_PORT = 8081;   // send frames to PC

WiFiUDP udp;
IPAddress pcIP;
bool pcKnown = false;

// ===== Camera pins (ESP32-S3 CAM Board) =====
#define CAM_PIN_PWDN    -1
#define CAM_PIN_RESET   -1
#define CAM_PIN_XCLK    15

#define CAM_PIN_SIOD    4
#define CAM_PIN_SIOC    5

#define CAM_PIN_D0      11
#define CAM_PIN_D1      9
#define CAM_PIN_D2      8
#define CAM_PIN_D3      10
#define CAM_PIN_D4      12
#define CAM_PIN_D5      18
#define CAM_PIN_D6      17
#define CAM_PIN_D7      16

#define CAM_PIN_VSYNC   6
#define CAM_PIN_HREF    7
#define CAM_PIN_PCLK    13

bool     streaming   = false;
uint8_t  jpegQuality = 12;

uint16_t frameId     = 0;
const uint32_t FRAME_INTERVAL = 40;  // ~25 FPS cap
uint32_t lastFrameMs = 0;

uint32_t frameCount  = 0;
uint32_t lastFpsTime = 0;

bool initCamera() {
  camera_config_t config;
  config.ledc_channel  = LEDC_CHANNEL_0;
  config.ledc_timer    = LEDC_TIMER_0;
  config.pin_d0        = CAM_PIN_D0;
  config.pin_d1        = CAM_PIN_D1;
  config.pin_d2        = CAM_PIN_D2;
  config.pin_d3        = CAM_PIN_D3;
  config.pin_d4        = CAM_PIN_D4;
  config.pin_d5        = CAM_PIN_D5;
  config.pin_d6        = CAM_PIN_D6;
  config.pin_d7        = CAM_PIN_D7;
  config.pin_xclk      = CAM_PIN_XCLK;
  config.pin_pclk      = CAM_PIN_PCLK;
  config.pin_vsync     = CAM_PIN_VSYNC;
  config.pin_href      = CAM_PIN_HREF;
  config.pin_sccb_sda  = CAM_PIN_SIOD;
  config.pin_sccb_scl  = CAM_PIN_SIOC;
  config.pin_pwdn      = CAM_PIN_PWDN;
  config.pin_reset     = CAM_PIN_RESET;

  config.xclk_freq_hz  = 20000000;
  config.pixel_format  = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = FRAMESIZE_VGA;   // 640x480
    config.jpeg_quality = jpegQuality;
    config.fb_count     = 3;
    config.grab_mode    = CAMERA_GRAB_LATEST;
  } else {
    Serial.println("No PSRAM — falling back to VGA single buffer");
    config.frame_size   = FRAMESIZE_VGA;
    config.jpeg_quality = jpegQuality;
    config.fb_count     = 1;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  Serial.println("Camera OK (VGA 640x480)");
  return true;
}

void applyQuality(uint8_t q) {
  q = constrain(q, 1, 63);
  if (q == jpegQuality) return;
  jpegQuality = q;
  sensor_t* s = esp_camera_sensor_get();

  if (!s) { Serial.println("Sensor not available"); return; }
  s->set_quality(s, jpegQuality);
  Serial.printf("Quality → %d\n", jpegQuality);
}

const size_t MAX_CHUNK_PAYLOAD = 1400;  // fits in one WiFi MTU

void sendFrameUDP(camera_fb_t* fb) {
  uint8_t totalChunks = (fb->len + MAX_CHUNK_PAYLOAD - 1) / MAX_CHUNK_PAYLOAD;
  if (totalChunks > 255) totalChunks = 255;  // safety clamp

  for (uint8_t i = 0; i < totalChunks; i++) {
    size_t offset = (size_t)i * MAX_CHUNK_PAYLOAD;
    size_t len = fb->len - offset;
    if (len > MAX_CHUNK_PAYLOAD) len = MAX_CHUNK_PAYLOAD;

    udp.beginPacket(pcIP, UDP_STREAM_PORT);
    uint8_t hdr[4] = {
      (uint8_t)(frameId & 0xFF), (uint8_t)(frameId >> 8),
      i, totalChunks
    };
    udp.write(hdr, 4);
    udp.write(fb->buf + offset, len);
    udp.endPacket();
  }
  frameId++;
}

void setup() {
  Serial.begin(115200);

  if (!initCamera()) {
    Serial.println("Camera failed — halting.");
    while (1) delay(1000);
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK. IP: %s\n", WiFi.localIP().toString().c_str());

  udp.begin(UDP_CMD_PORT);
  Serial.printf("UDP cmd port %d — waiting for quality byte...\n", UDP_CMD_PORT);
}

void loop() {
  // Check for quality command from PC
  int pktSize = udp.parsePacket();
  if (pktSize == 1) {
    uint8_t q;
    udp.read(&q, 1);
    pcIP = udp.remoteIP();
    pcKnown = true;
    applyQuality(q);
    if (!streaming) {
      streaming = true;
      frameCount  = 0;
      lastFpsTime = millis();
      Serial.printf("Stream START  quality=%d  PC=%s\n",
                    jpegQuality, pcIP.toString().c_str());
    }
  }

  if (!pcKnown || !streaming) return;

  // FPS cap
  if (millis() - lastFrameMs < FRAME_INTERVAL) return;
  lastFrameMs = millis();

  // Low-heap guard
  if (heap_caps_get_free_size(MALLOC_CAP_DEFAULT) < 8000) {
    Serial.printf("[MEM] Low heap: %u bytes — skipping frame\n",
                  heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
    delay(10);
    return;
  }

  // Capture + send
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Frame capture failed");
    delay(10);
    return;
  }

  sendFrameUDP(fb);
  esp_camera_fb_return(fb);

  // FPS log
  frameCount++;
  uint32_t now = millis();
  if (now - lastFpsTime >= 2000) {
    Serial.printf("FPS: %.1f  quality: %d  frame_id: %u\n",
                  frameCount * 1000.0f / (now - lastFpsTime), jpegQuality, frameId);
    frameCount  = 0;
    lastFpsTime = now;
  }
}
