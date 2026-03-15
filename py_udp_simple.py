#!/usr/bin/env python3
"""
Simple telemetry receiver from ESP32 (JST_RC_DEV_CAR_UDP).
Just receives TelemetryPacket and prints it.
"""

import socket
import struct

UDP_TELE_PORT = 5006   # port that PC receives telemetry from ESP32 on

# TelemetryPacket: 8x float + 1x int32 = 36 bytes (must match ESP32 struct)
TELE_FMT  = '<ffffffffi'
TELE_SIZE = struct.calcsize(TELE_FMT)  # 36

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", UDP_TELE_PORT))
    print(f"Listening for telemetry on UDP port {UDP_TELE_PORT} ...")
    print(f"Expected packet size: {TELE_SIZE} bytes\n")

    while True:
        data, addr = sock.recvfrom(256)
        if len(data) == TELE_SIZE:
            ax, ay, az, gx, gy, gz, angle, omega, turns = struct.unpack(TELE_FMT, data)
            print(f"[{addr[0]}] "
                  f"A[{ax:6.2f} {ay:6.2f} {az:6.2f}] "
                  f"G[{gx:6.2f} {gy:6.2f} {gz:6.2f}] | "
                  f"deg={angle:6.1f}  w={omega:7.1f}deg/s  turns={turns}")
        else:
            print(f"[{addr[0]}] unexpected size {len(data)} bytes: {data}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
