#!/usr/bin/env python3
"""Mock telemetry sender — simulates relay-format packets for dashboard testing.

Sends 42-byte relay packets (telemetry + throttle + steer + gear) on port 5007
so the dashboard in --live mode can be tested without hardware.
"""

import math
import struct
import socket
import time

RELAY_PORT = 5007
RELAY_GEAR_FMT = "<ffffffffihhh"  # 36B tele + 2B throttle + 2B steer + 2B gear = 42B
SEND_HZ = 20

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Sending mock relay telemetry to localhost:{RELAY_PORT} at {SEND_HZ} Hz")
print("Press Ctrl+C to stop.\n")

t0 = time.time()
turn_counts = 0

try:
    while True:
        t = time.time() - t0

        # IMU accelerometer (m/s^2) — gravity on az + lateral/longitudinal oscillation
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
        turn_counts = int(t * 2)

        # Control signals — simulate steering sweep and throttle bursts
        throttle_us = int(1500 + 200 * (0.5 + 0.5 * math.sin(0.3 * t)))
        steer_deg = int(100 + 25 * math.sin(0.5 * t))

        # Gear — cycle through 0,1,2,3 every ~10 seconds
        gear_cycle = int(t / 10) % 5
        gear = [0, 1, 2, 3, -1][gear_cycle]

        pkt = struct.pack(
            RELAY_GEAR_FMT,
            ax, ay, az, gx, gy, gz, angle, omega, turn_counts,
            throttle_us, steer_deg, gear,
        )
        sock.sendto(pkt, ("127.0.0.1", RELAY_PORT))

        elapsed = t
        if int(elapsed) % 5 == 0 and abs(elapsed - round(elapsed)) < 0.03:
            print(
                f"  t={elapsed:6.1f}s  ax={ax:+5.2f}  omega={omega:6.1f}  "
                f"thr={throttle_us}  steer={steer_deg}  gear={gear}"
            )

        time.sleep(1.0 / SEND_HZ)

except KeyboardInterrupt:
    print("\nStopped.")
finally:
    sock.close()
