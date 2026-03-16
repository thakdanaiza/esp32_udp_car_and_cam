# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESP32-based RC car platform with two communication modes:
- **Mode A (UDP Direct)**: PC talks directly to car ESP32 over WiFi UDP — recommended mode
- **Mode B (ESP-NOW)**: PC → Ground Station ESP32 → Car ESP32 (two-ESP32 setup, legacy)
- **Camera**: Separate ESP32-CAM streams 720p JPEG over TCP

## Architecture

### Firmware (Arduino `.ino` sketches)
- `JST_RC_DEV_CAR_UDP/` — Main car firmware. Receives 4-byte `ControlPacket` (throttle µs + steering deg) on UDP:5005, sends 36-byte `TelemetryPacket` (IMU + encoder) on UDP:5006 at 20 Hz.
- `JST_RC_DEV_CAR_IMU/` and `JST_RC_DEV_CAR_IMU_ENC/` — ESP-NOW car variants (IMU only vs IMU+encoder).
- `JST_RC_GROUND_STATION_IMU/` — Ground station for ESP-NOW mode. Reads serial `<steering,throttle>` commands, broadcasts via ESP-NOW.
- `JST_CAM_STREAM/` — Lean TCP camera streamer. Waits for 1-byte quality command from PC, then streams `[4-byte big-endian length][JPEG data]` frames.
- `UDP_TEST/` — Simple UDP echo/heartbeat for connectivity testing.
- `AS5600_lean/`, `AS5600_fulltest/` — Standalone AS5600 magnetic encoder tests.

### Python scripts (PC side)
- `py_udp.py` — Main controller: reads Moza Racing wheel via HID, sends control packets, receives telemetry. Requires `ESP32_IP` to be set.
- `py_udp_record.py` — Same as above but logs time-series to `log_YYYYMMDD_HHMMSS.csv`.
- `cam_viewer.py` — OpenCV viewer for ESP32-CAM TCP stream with quality trackbar.
- `py_udp_simple.py` — Minimal telemetry receiver (no HID device needed).
- `udp_test.py` — UDP connectivity test companion for `UDP_TEST/`.

### Packet structs (must stay in sync between firmware and Python)
```
ControlPacket  (4 bytes): int16 throttle_us, int16 steering_deg
TelemetryPacket (36 bytes): 8×float (ax,ay,az,gx,gy,gz,angle_deg,omega_deg_s) + int32 turn_counts
```
Python format strings: `CTRL_FMT = '<hh'`, `TELE_FMT = '<ffffffffi'`

## Build & Upload

All firmware uses Arduino IDE or `arduino-cli` with the ESP32 board package.

```bash
# Install ESP32 board package, then compile+upload a sketch:
arduino-cli compile --fqbn esp32:esp32:esp32 JST_RC_DEV_CAR_UDP/
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 JST_RC_DEV_CAR_UDP/

# For ESP32-CAM (AI Thinker):
arduino-cli compile --fqbn esp32:esp32:esp32cam JST_CAM_STREAM/
arduino-cli upload  --fqbn esp32:esp32:esp32cam -p /dev/ttyUSB0 JST_CAM_STREAM/
```

### Required Arduino libraries
`ESP32Servo`, `Adafruit MPU6050`, `Adafruit Unified Sensor`, `Adafruit AS5600`

### Python dependencies
```bash
pip install hidapi pyserial numpy opencv-python
```

## Key Configuration Points

Each sketch and Python script has hardcoded WiFi/IP settings that must be edited before use:
- Firmware: `WIFI_SSID`, `WIFI_PASS` at the top of each `.ino`
- Python: `ESP32_IP` at the top of each `.py`

## Hardware Pin Map (Car ESP32)
- Servo (steering): GPIO 26
- ESC (drive): GPIO 25
- I2C: SDA=21, SCL=22 (MPU6050 @ 0x68, AS5600 @ 0x36)

## ESP32-CAM_MJPEG2SD

Vendored third-party project (has its own LICENSE and README). Full-featured camera app with SD recording, motion detection, MQTT, FTP, etc. Not part of the core JST RC car system.
