/*
  CAM_STREAM_DEBUG
  JPEG streaming over USB Serial — no WiFi needed.
  Use this to verify the camera works and monitor memory/fps before going wireless.

  Baud rate : 921600
  Resolution: QVGA (320x240) — fits Serial bandwidth (~92 KB/s)

  Protocol (same as JST_CAM_STREAM so the same PC viewer works on a serial port):
    PC → ESP32 : 1 byte = JPEG quality (1-63)  — starts the stream
    ESP32 → PC : [4-byte big-endian length] + [JPEG bytes]  (repeating)

  Debug lines are plain text prefixed with '#' — PC viewer should skip them.
  Board: AI Thinker ESP32-CAM
*/

#include "esp_camera.h"
#include "esp_heap_caps.h"

// ===== Camera pins (AI Thinker ESP32-CAM) =====
#define CAM_PIN_PWDN    32
#define CAM_PIN_RESET   -1
#define CAM_PIN_XCLK     0
#define CAM_PIN_SIOD    26
#define CAM_PIN_SIOC    27
#define CAM_PIN_D7      35
#define CAM_PIN_D6      34
#define CAM_PIN_D5      39
#define CAM_PIN_D4      36
#define CAM_PIN_D3      21
#define CAM_PIN_D2      19
#define CAM_PIN_D1      18
#define CAM_PIN_D0       5
#define CAM_PIN_VSYNC   25
#define CAM_PIN_HREF    23
#define CAM_PIN_PCLK    22

// Minimum free heap before skipping a frame (bytes)
#define HEAP_MIN_GUARD   15000

bool    streaming    = false;
uint8_t jpegQuality  = 12;

uint32_t frameCount   = 0;
uint32_t frameDropped = 0;
uint32_t lastStatTime = 0;

// ─────────────────────────────────────────────
void dbg(const char* fmt, ...) {
  // Prefixed with '#' so the PC viewer can strip it
  Serial.print("# ");
  char buf[128];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  Serial.println(buf);
}

// ─────────────────────────────────────────────
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

  // QVGA is safe even without PSRAM and fits USB Serial bandwidth
  config.frame_size    = FRAMESIZE_QVGA;  // 320x240
  config.jpeg_quality  = jpegQuality;
  config.fb_count      = psramFound() ? 2 : 1;
  config.grab_mode     = psramFound() ? CAMERA_GRAB_LATEST : CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    dbg("Camera init FAILED: 0x%x", err);
    return false;
  }

  dbg("Camera OK  QVGA 320x240  PSRAM:%s  fb_count:%d",
      psramFound() ? "yes" : "NO", config.fb_count);
  return true;
}

// ─────────────────────────────────────────────
void applyQuality(uint8_t q) {
  q = constrain(q, 1, 63);
  if (q == jpegQuality) return;
  jpegQuality = q;
  sensor_t* s = esp_camera_sensor_get();
  if (!s) { dbg("Sensor not available"); return; }
  s->set_quality(s, jpegQuality);
  dbg("Quality -> %d", jpegQuality);
}

// ─────────────────────────────────────────────
// Send one JPEG frame over Serial in chunks
bool sendFrame(camera_fb_t* fb) {
  uint32_t len = fb->len;

  // 4-byte big-endian length header
  uint8_t header[4] = {
    (uint8_t)(len >> 24),
    (uint8_t)(len >> 16),
    (uint8_t)(len >>  8),
    (uint8_t)(len      )
  };
  Serial.write(header, 4);

  // Send JPEG in chunks — avoids blocking Serial TX buffer
  const size_t CHUNK = 512;
  size_t sent = 0;
  while (sent < len) {
    size_t chunk = min((size_t)CHUNK, (size_t)(len - sent));
    size_t written = Serial.write(fb->buf + sent, chunk);
    if (written == 0) return false;
    sent += written;
  }
  return true;
}

// ─────────────────────────────────────────────
void setup() {
  Serial.begin(921600);
  delay(200);
  dbg("=== CAM_STREAM_DEBUG boot ===");
  dbg("Free heap at boot: %u bytes", heap_caps_get_free_size(MALLOC_CAP_DEFAULT));

  if (!initCamera()) {
    dbg("Camera failed — halting.");
    while (1) delay(1000);
  }

  dbg("Send any quality byte (1-63) over Serial to start stream.");
}

// ─────────────────────────────────────────────
void loop() {
  // Read quality byte from PC → start/update stream
  if (Serial.available() > 0) {
    uint8_t q = Serial.read();
    applyQuality(q);
    if (!streaming) {
      streaming = true;
      frameCount = frameDropped = 0;
      lastStatTime = millis();
      dbg("Stream START  quality=%d", jpegQuality);
    }
  }

  if (!streaming) return;

  // Low-heap guard — skip frame and warn rather than crash
  uint32_t freeHeap = heap_caps_get_free_size(MALLOC_CAP_DEFAULT);
  if (freeHeap < HEAP_MIN_GUARD) {
    dbg("LOW HEAP %u bytes — skipping frame", freeHeap);
    frameDropped++;
    delay(100);
    return;
  }

  // Capture
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    dbg("Frame capture failed  heap=%u", freeHeap);
    frameDropped++;
    delay(20);
    return;
  }

  uint32_t frameBytes = fb->len;
  bool ok = sendFrame(fb);
  esp_camera_fb_return(fb);      // Always return before anything else

  if (!ok) {
    dbg("Serial write failed");
    return;
  }

  frameCount++;

  // Stats every 3 seconds
  uint32_t now = millis();
  if (now - lastStatTime >= 3000) {
    float elapsed = (now - lastStatTime) / 1000.0f;
    dbg("FPS:%.1f  last_frame:%u B  dropped:%u  free_heap:%u B  quality:%d",
        frameCount / elapsed,
        frameBytes,
        frameDropped,
        heap_caps_get_free_size(MALLOC_CAP_DEFAULT),
        jpegQuality);
    frameCount   = 0;
    frameDropped = 0;
    lastStatTime = now;
  }
}
