#!/usr/bin/env python3
"""
IMU real-time plotter
Reads IMU data from Serial in format:
IMU,ax,ay,az,gx,gy,gz
Plots accel + gyro in real time
"""

import serial
import time
import matplotlib.pyplot as plt
from collections import deque

# ======================
# CONFIG
# ======================
SERIAL_PORT = "COM9"      # <<< Change to match your machine
BAUDRATE = 115200
WINDOW_SIZE = 300         # Number of points shown in the graph
UPDATE_INTERVAL = 0.05    # seconds (20 Hz plot)

# ======================
# SERIAL
# ======================
ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
time.sleep(2)

# ======================
# DATA BUFFERS
# ======================
ax_buf = deque(maxlen=WINDOW_SIZE)
ay_buf = deque(maxlen=WINDOW_SIZE)
az_buf = deque(maxlen=WINDOW_SIZE)

gx_buf = deque(maxlen=WINDOW_SIZE)
gy_buf = deque(maxlen=WINDOW_SIZE)
gz_buf = deque(maxlen=WINDOW_SIZE)

# ======================
# MATPLOTLIB SETUP
# ======================
plt.ion()
fig, axs = plt.subplots(2, 1, figsize=(10, 7))

# Acceleration plot
axs[0].set_title("Acceleration (m/s²)")
axs[0].set_ylabel("m/s²")
axs[0].grid(True)

# Gyro plot
axs[1].set_title("Gyroscope (rad/s)")
axs[1].set_ylabel("rad/s")
axs[1].set_xlabel("samples")
axs[1].grid(True)

last_update = time.time()

print("Listening for IMU data... (Ctrl+C to stop)")

# ======================
# MAIN LOOP
# ======================
try:
    while True:
        line = ser.readline().decode(errors="ignore").strip()
        # print(line)
        if line.startswith("IMU,"):
            parts = line.split(",")
            # print(parts)
            if len(parts) == 7:
                ax, ay, az = map(float, parts[1:4])
                gx, gy, gz = map(float, parts[4:7])

                ax_buf.append(ax)
                ay_buf.append(ay)
                az_buf.append(az)

                gx_buf.append(gx)
                gy_buf.append(gy)
                gz_buf.append(gz)

        now = time.time()
        if now - last_update >= UPDATE_INTERVAL:
            last_update = now

            axs[0].cla()
            axs[1].cla()

            # Accel
            axs[0].plot(ax_buf, label="ax")
            axs[0].plot(ay_buf, label="ay")
            axs[0].plot(az_buf, label="az")
            axs[0].legend()
            axs[0].set_title("Acceleration (m/s²)")
            axs[0].grid(True)

            # Gyro
            axs[1].plot(gx_buf, label="gx")
            axs[1].plot(gy_buf, label="gy")
            axs[1].plot(gz_buf, label="gz")
            axs[1].legend()
            axs[1].set_title("Gyroscope (rad/s)")
            axs[1].grid(True)

            plt.pause(0.001)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    ser.close()
    print("Serial closed")
