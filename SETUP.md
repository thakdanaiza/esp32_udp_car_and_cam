# Setup & Run Guide

## Prerequisites

- Python 3.10+
- Moza Racing wheel connected via USB
- ESP32 car powered on and connected to the same WiFi network as your PC
- (Optional) ESP32-CAM for camera feed

## 1. Virtual environment

```bash
cd esp32_udp_car_and_cam
python3 -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

This installs: `opencv-python`, `numpy`, `pandas`, `plotly`, `dash`, and `hidapi`.

## 3. Configuration

Edit these values before running:

| File | Variable | Line | Description |
|------|----------|------|-------------|
| `py_udp.py` | `ESP32_IP` | 16 | IP address of the car ESP32 (check Serial Monitor or router) |
| `dashboard/constants.py` | `CAM_IP` | 24 | IP address of the ESP32-CAM (only if using camera) |

## 4. Running

### Step 1 — Start the controller

In your first terminal (venv activated):

```bash
python py_udp.py
```

This connects to the Moza wheel via HID, sends control packets to the ESP32 on UDP:5005, receives telemetry on UDP:5006, and relays it to the dashboard on UDP:5007.

### Step 2 — Start the dashboard (live mode)

In a second terminal (same venv):

```bash
python dashboard.py --live
```

Opens at **http://localhost:8050**.

### CSV playback mode (no hardware needed)

```bash
python dashboard.py                    # auto-find latest log_*.csv
python dashboard.py log_file.csv       # specific CSV file
```

To record CSV logs, use `py_udp_record.py` instead of `py_udp.py`.

## 5. Network architecture

```
Moza Wheel (USB/HID) --> py_udp.py --> UDP:5005 --> ESP32 Car
                                    <-- UDP:5006 <-- (telemetry)
                         py_udp.py --> UDP:5007 --> dashboard.py --live
```
