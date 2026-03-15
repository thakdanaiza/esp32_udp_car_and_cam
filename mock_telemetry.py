#!/usr/bin/env python3
"""Mock telemetry sender — simulates ESP32 TelemetryPacket for dashboard testing."""

import math
import struct
import socket
import time

UDP_PORT = 5006
TELE_FMT = "<ffffffffi"  # 8 floats + 1 int32 = 36 bytes
SEND_HZ = 20

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Sending mock telemetry to localhost:{UDP_PORT} at {SEND_HZ} Hz")
print("Press Ctrl+C to stop.\n")

t0 = time.time()
turn_counts = 0

try:
    while True:
        t = time.time() - t0

        # IMU accelerometer (m/s²) — gravity on az + lateral/longitudinal oscillation
        ax = 1.5 * math.sin(0.7 * t) + 0.3 * math.sin(3.1 * t)
        ay = 1.0 * math.sin(0.5 * t + 1.0) + 0.2 * math.cos(2.3 * t)
        az = 9.81 + 0.4 * math.sin(1.2 * t)

        # IMU gyroscope (rad/s)
        gx = 0.3 * math.sin(0.8 * t)
        gy = 0.2 * math.cos(1.1 * t)
        gz = 1.5 * math.sin(0.4 * t) + 0.5 * math.sin(2.0 * t)

        # Encoder — wheel angle and angular velocity
        omega = 360 * (0.5 + 0.5 * math.sin(0.3 * t))  # 0-360 deg/s
        angle = (omega * t) % 360
        turn_counts = int(t * 2)  # ~2 turns per second

        pkt = struct.pack(TELE_FMT, ax, ay, az, gx, gy, gz, angle, omega, turn_counts)
        sock.sendto(pkt, ("127.0.0.1", UDP_PORT))

        elapsed = t
        if int(elapsed) % 5 == 0 and abs(elapsed - round(elapsed)) < 0.03:
            print(f"  t={elapsed:6.1f}s  ax={ax:+5.2f}  omega={omega:6.1f}  turns={turn_counts}")

        time.sleep(1.0 / SEND_HZ)

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    sock.close()
