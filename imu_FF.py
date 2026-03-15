#!/usr/bin/env python3
import serial, time, math
import matplotlib.pyplot as plt
from collections import deque
import numpy as np

# ================= CONFIG =================
SERIAL_PORT = "COM9"
BAUDRATE = 115200

WINDOW = 400
PLOT_DT = 0.05

ALPHA_GYR = 0.2
ALPHA_YAW = 0.7

WHEELBASE = 0.26
VELOCITY = 1.0

BIAS_SAMPLES = 200   # ~2s @100Hz

# ================= SERIAL =================
ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
time.sleep(2)

# ================= STATE =================
state = "CALIBRATING"

bias_buf = []
gz_bias = 0.0

yaw = 0.0
x = y = 0.0
gz_f = 0.0

last_imu_t = time.time()
last_plot_t = time.time()
last_status_t = time.time()

# ================= BUFFERS =================
gz_raw_buf = deque(maxlen=WINDOW)
gz_f_buf   = deque(maxlen=WINDOW)
yaw_buf    = deque(maxlen=WINDOW)
x_buf      = deque(maxlen=WINDOW)
y_buf      = deque(maxlen=WINDOW)

# ================= PLOT =================
plt.ion()
fig, axs = plt.subplots(2, 2, figsize=(11, 9))

print("Starting IMU pipeline")
print("Hold vehicle STILL for gyro bias calibration")

# ================= LOOP =================
try:
    while True:
        line = ser.readline().decode(errors="ignore").strip()

        if line.startswith("IMU,"):
            parts = line.split(",")
            if len(parts) < 8:
                continue

            ax, ay, az = map(float, parts[1:4])
            gx, gy, gz = map(float, parts[4:7])
            steer_deg = float(parts[7])

            now = time.time()
            dt = now - last_imu_t
            last_imu_t = now

            # ---------- CALIBRATION ----------
            if state == "CALIBRATING":
                bias_buf.append(gz)
                gz_raw_buf.append(gz)

                if len(bias_buf) >= BIAS_SAMPLES:
                    gz_bias = np.mean(bias_buf)
                    state = "RUNNING"
                    print(f"Calibration done | gyro bias = {gz_bias:.6f} rad/s")
                else:
                    if now - last_status_t > 0.5:
                        last_status_t = now
                        print(f"Calibrating... {len(bias_buf)}/{BIAS_SAMPLES}")
                continue

            # ---------- RUNNING ----------
            gz -= gz_bias
            gz_f = ALPHA_GYR * gz + (1 - ALPHA_GYR) * gz_f

            steer_rad = math.radians(steer_deg)
            yaw_rate_steer = VELOCITY / WHEELBASE * math.tan(steer_rad)

            yaw_dot = ALPHA_YAW * gz_f + (1 - ALPHA_YAW) * yaw_rate_steer
            yaw += yaw_dot * dt

            x += VELOCITY * math.cos(yaw) * dt
            y += VELOCITY * math.sin(yaw) * dt

            # buffers
            gz_raw_buf.append(gz)
            gz_f_buf.append(gz_f)
            yaw_buf.append(yaw)
            x_buf.append(x)
            y_buf.append(y)

        # ---------- PLOT ----------
        if time.time() - last_plot_t >= PLOT_DT:
            last_plot_t = time.time()

            axs[0,0].cla()
            axs[0,1].cla()
            axs[1,0].cla()

            axs[0,0].plot(gz_raw_buf, label="gz raw")
            axs[0,0].plot(gz_f_buf, label="gz filtered")
            axs[0,0].set_title("Gyro Z")
            axs[0,0].legend()
            axs[0,0].grid(True)

            axs[0,1].plot(yaw_buf)
            axs[0,1].set_title("Yaw (rad)")
            axs[0,1].grid(True)

            axs[1,0].plot(x_buf, y_buf, "-o", markersize=2)
            axs[1,0].set_title("2D Trajectory")
            axs[1,0].axis("equal")
            axs[1,0].grid(True)

            plt.pause(0.001)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    ser.close()
    print("Serial closed")
