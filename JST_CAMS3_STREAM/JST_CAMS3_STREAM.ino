/*
  JST_CAM_STREAM
  Lean 720p JPEG streaming over TCP WiFi.
  No web server, no SD card, no motion detection.

  Protocol:
    PC → ESP32 : 1 byte = JPEG quality (1-63)
                 Send first time to START stream, send again to change quality
    ESP32 → PC : [4-byte big-endian length] + [JPEG bytes]  (repeating)

  Board: AI Thinker ESP32-CAM
*/

#include <WiFi.h>
#include "esp_camera.h"

// ===== WiFi =====
const char* WIFI_SSID = "301/3_2.4G";
const char* WIFI_PASS = "357m19smith";

// ===== TCP =====
const uint16_t TCP_PORT = 8080;

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

WiFiServer server(TCP_PORT);
WiFiClient client;

bool     streaming   = false;  // Start stream after receiving the first quality byte
uint8_t  jpegQuality = 12;     // default quality

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
    // config.frame_size   = FRAMESIZE_HD;   // 1280x720 — needs PSRAM
    // config.fb_count     = 3; // was 2
    // config.grab_mode    = CAMERA_GRAB_LATEST;
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    Serial.println("No PSRAM — falling back to VGA");
    config.frame_size   = FRAMESIZE_VGA;  // 640x480 — safe without PSRAM
    config.fb_count     = 1;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  config.jpeg_quality  = jpegQuality;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  Serial.println("Camera OK (SVGA 800x600)");
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

bool sendFrame(WiFiClient& cli, camera_fb_t* fb) {
  uint32_t len = fb->len;
  uint8_t header[4] = {
    (uint8_t)(len >> 24),
    (uint8_t)(len >> 16),
    (uint8_t)(len >>  8),
    (uint8_t)(len      )
  };
  if (cli.write(header, 4) != 4) return false;

  // Send in TCP-segment-sized chunks to avoid exhausting heap in lwIP buffers
  const size_t CHUNK = 1460;
  size_t sent = 0;
  while (sent < len) {
    size_t chunk = min((size_t)CHUNK, (size_t)(len - sent));
    size_t written = cli.write(fb->buf + sent, chunk);
    if (written == 0) return false;
    sent += written;
  }
  cli.flush();
  return true;
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

  server.begin();
  server.setNoDelay(true);
  Serial.printf("TCP port %d — waiting for cam_viewer...\n", TCP_PORT);
}

void loop() {
  // Accept new client
  if (server.hasClient()) {
    if (client.connected()) client.stop();
    client = server.accept();
    client.setNoDelay(true);
    streaming  = false;   // Always wait for quality byte first
    frameCount = 0;
    lastFpsTime = millis();
    Serial.printf("Client: %s — waiting for quality byte...\n",
                  client.remoteIP().toString().c_str());
  }

  if (!client.connected()) return;

  // Check command from PC (quality byte) — do this before sending each frame
  if (client.available() > 0) {
    uint8_t q = client.read();
    applyQuality(q);
    if (!streaming) {
      streaming = true;
      Serial.printf("Stream START  quality=%d\n", jpegQuality);
    }
  }

  if (!streaming) return;   // Quality byte not yet received → do not send

  // Low-heap guard — skip frame rather than crash
  if (heap_caps_get_free_size(MALLOC_CAP_DEFAULT) < 8000) {
    Serial.printf("[MEM] Low heap: %u bytes — skipping frame\n",
                  heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
    delay(100);
    return;
  }

  // Capture + send
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Frame capture failed");
    delay(10);
    return;
  }

  bool ok = sendFrame(client, fb);
  esp_camera_fb_return(fb);

  if (!ok) {
    Serial.println("Client disconnected.");
    client.stop();
    streaming = false;
    return;
  }

  // FPS log
  frameCount++;
  uint32_t now = millis();
  if (now - lastFpsTime >= 2000) {
    Serial.printf("FPS: %.1f  quality: %d\n",
                  frameCount * 1000.0f / (now - lastFpsTime), jpegQuality);
    frameCount  = 0;
    lastFpsTime = now;
  }
}
