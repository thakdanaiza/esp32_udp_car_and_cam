# Swarm Robotics — JST RC Car Platform

ESP32-based RC car platform with IMU + encoder telemetry, real-time camera streaming, and PC control via WiFi (UDP/TCP).

---

## Repository Structure

```
swarm-robotics/
│
├── JST_RC_DEV_CAR_UDP/          # ESP32 car firmware (WiFi UDP)
├── JST_RC_DEV_CAR_IMU_ENC/      # ESP32 car firmware (ESP-NOW, IMU + encoder)
├── JST_RC_DEV_CAR_IMU/          # ESP32 car firmware (ESP-NOW, IMU only)
├── JST_RC_GROUND_STATION_IMU/   # ESP32 ground station firmware (ESP-NOW)
│
├── JST_CAM_STREAM/              # ESP32-CAM lean TCP streaming firmware
│
├── AS5600_lean/                 # AS5600 magnetic encoder standalone test
├── AS5600_fulltest/             # AS5600 full feature test
│
├── UDP_TEST/                    # UDP communication test (ESP32 + Python)
│
├── py_udp.py                    # Main RC controller (Moza wheel + UDP)
├── py_udp_record.py             # RC controller with CSV time-series logging
├── py_udp_simple.py             # Minimal telemetry receiver (no HID)
├── cam_viewer.py                # 720p camera viewer with quality control
├── udp_test.py                  # UDP connectivity test
│
├── py.py                        # Legacy: Moza HID + Serial (ESP-NOW mode)
├── imu.py                       # IMU data reader / plotter
├── imu_FF.py                    # IMU feed-forward helper
└── moza_port.py                 # Moza wheel port scanner utility
```

---

## System Overview

### Mode A — UDP Direct (recommended)

PC communicates directly with the car ESP32 over WiFi UDP. No ground station required.

```
┌─────────────────┐   UDP:5005 (control)   ┌───────────────────┐
│  PC (py_udp.py) │ ─────────────────────► │  ESP32 Car        │
│  Moza wheel HID │ ◄───────────────────── │  JST_RC_DEV_CAR   │
└─────────────────┘   UDP:5006 (telemetry) │  _UDP             │
                                            └───────────────────┘
```

**Telemetry sent back (20 Hz):**
- IMU: ax, ay, az, gx, gy, gz (MPU6050)
- Encoder: angle (deg), angular velocity (deg/s), turn count (AS5600)

### Mode B — ESP-NOW (two-ESP32 setup)

```
┌──────────────┐   Serial (COM)   ┌──────────────────┐   ESP-NOW   ┌───────────┐
│  PC (py.py)  │ ───────────────► │  Ground Station  │ ──────────► │  Car      │
│  Moza wheel  │ ◄─────────────── │  ESP32           │ ◄────────── │  ESP32    │
└──────────────┘                  └──────────────────┘             └───────────┘
```

### Camera Stream

```
┌──────────────────┐   TCP:8080 (JPEG frames)   ┌───────────────┐
│  cam_viewer.py   │ ◄─────────────────────────  │  ESP32-CAM    │
│  OpenCV display  │ ──────────────────────────► │  JST_CAM      │
└──────────────────┘   quality byte (1-63)       │  _STREAM      │
                                                  └───────────────┘
```

---

## Hardware

| Component | Purpose |
|---|---|
| ESP32 (car) | Main controller, WiFi, servo/ESC |
| MPU6050 | 6-axis IMU (I2C 0x68) |
| AS5600 | Magnetic rotary encoder (I2C 0x36) |
| ESP32-CAM (AI Thinker) | 720p JPEG camera |
| Servo (pin 26) | Steering |
| ESC (pin 25) | Drive motor |
| Moza Racing wheel | PC input device (HID) |

**ESP32 Car — I2C pins:** SDA=21, SCL=22

---

## Packet Formats

### ControlPacket (PC → Car, 4 bytes)
```c
struct ControlPacket {
    int16_t throttle;   // ESC microseconds (1500=neutral, 1750=full)
    int16_t steering;   // Servo degrees (75-125)
};
```

### TelemetryPacket (Car → PC, 36 bytes)
```c
struct TelemetryPacket {
    float   ax, ay, az;       // acceleration m/s²
    float   gx, gy, gz;       // gyroscope rad/s
    float   angle_deg;        // encoder absolute angle 0-360°
    float   omega_deg_s;      // angular velocity deg/s (IIR filtered)
    int32_t turn_counts;      // absolute accumulated position
};
```

### Camera Protocol (TCP)
```
PC → ESP32 : 1 byte  = JPEG quality (1=best/large, 63=worst/small/fast)
ESP32 → PC : 4 bytes = frame size (big-endian uint32)
             N bytes = JPEG data
             (repeating)
```

---

## Quick Start

### 1. ESP32 Car (UDP mode)

1. Open `JST_RC_DEV_CAR_UDP/JST_RC_DEV_CAR_UDP.ino`
2. Set `WIFI_SSID` and `WIFI_PASS`
3. Upload → note the IP printed on Serial Monitor

### 2. Python controller

```bash
pip install hidapi pyserial numpy opencv-python
```

Edit `ESP32_IP` in `py_udp.py`, then:

```bash
python py_udp.py
```

### 3. Camera stream

1. Open `JST_CAM_STREAM/JST_CAM_STREAM.ino`
2. Set `WIFI_SSID` and `WIFI_PASS` → upload
3. Edit `ESP32_IP` in `cam_viewer.py`

```bash
python cam_viewer.py
```

Use the **Quality trackbar** to trade off sharpness vs. FPS (1=sharpest, 63=fastest).

### 4. UDP connectivity test

```bash
# Edit ESP32_IP in UDP_TEST/UDP_TEST.ino → upload
python udp_test.py
```

### 5. Record a session

```bash
python py_udp_record.py
# Saves log_YYYYMMDD_HHMMSS.csv with control + telemetry time-series
```

---

## CSV Log Format

```
time_s, throttle_us, steer_deg, ax, ay, az, gx, gy, gz, angle_deg, omega_deg_s, turn_counts
0.050,  1500,        100,       0.12, -0.05, 9.81, 0.01, 0.00, 0.02, 45.2, 0.0, 512
...
```

---

## Dependencies

### Arduino libraries
- `ESP32Servo`
- `Adafruit MPU6050`
- `Adafruit Unified Sensor`
- `Adafruit AS5600`
- `esp_camera` (built-in with ESP32 board package)

### Python packages
```
hidapi
pyserial
numpy
opencv-python
```

---

## Expected Performance

| Mode | Board | Resolution | FPS |
|---|---|---|---|
| Camera stream | ESP32 (OV2640) | 720p | ~8-12 |
| Camera stream | ESP32-S3 | 720p | ~15-20 |
| Telemetry | ESP32 | — | 20 Hz |
| Control | PC → ESP32 | — | 20 Hz |

Adjust `jpeg_quality` in `JST_CAM_STREAM.ino` or the trackbar in `cam_viewer.py` to tune FPS vs. image quality.
