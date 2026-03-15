#!/usr/bin/env python3
"""
Moza Racing HID + UDP controller with time-series recording.
Logs both control commands and telemetry to CSV.

CSV columns:
  time_s, throttle_us, steer_deg,
  ax, ay, az, gx, gy, gz,
  angle_deg, omega_deg_s, turn_counts
"""

import hid
import time
import sys
import struct
import socket
import threading
import csv
import os
from datetime import datetime

# ===== UDP Config =====
ESP32_IP      = "192.168.1.31"
UDP_CTRL_PORT = 5005
UDP_TELE_PORT = 5006

# ===== Packet format =====
CTRL_FMT  = '<hh'
TELE_FMT  = '<ffffffffi'
CTRL_SIZE = struct.calcsize(CTRL_FMT)   # 4
TELE_SIZE = struct.calcsize(TELE_FMT)   # 36

# ===== Moza =====
MOZA_VENDOR_IDS = [0x346E]
steering_min    = 16777217
steering_max    = 33554177
BAR_WIDTH       = 50

# ===== Shared state =====
tele_lock = threading.Lock()
tele_data = {
    "ax": 0.0, "ay": 0.0, "az": 0.0,
    "gx": 0.0, "gy": 0.0, "gz": 0.0,
    "angle": 0.0, "omega": 0.0, "turns": 0,
    "updated": False
}

ctrl_lock = threading.Lock()
ctrl_data = {"throttle_us": 1500, "steer_deg": 100}

record_lock = threading.Lock()
record_rows = []   # list of dicts, flushed to CSV periodically

t0 = time.time()   # start time reference


# ===== Telemetry receive thread =====
def tele_recv_thread(sock):
    while True:
        try:
            data, _ = sock.recvfrom(256)
            if len(data) == TELE_SIZE:
                vals = struct.unpack(TELE_FMT, data)
                ts   = time.time() - t0
                with tele_lock:
                    tele_data.update({
                        "ax": vals[0], "ay": vals[1], "az": vals[2],
                        "gx": vals[3], "gy": vals[4], "gz": vals[5],
                        "angle": vals[6], "omega": vals[7], "turns": vals[8],
                        "updated": True
                    })
                # record row on every telemetry packet received
                with ctrl_lock:
                    thr = ctrl_data["throttle_us"]
                    steer = ctrl_data["steer_deg"]
                with record_lock:
                    record_rows.append({
                        "time_s":       round(ts, 4),
                        "throttle_us":  thr,
                        "steer_deg":    steer,
                        "ax":  round(vals[0], 4),
                        "ay":  round(vals[1], 4),
                        "az":  round(vals[2], 4),
                        "gx":  round(vals[3], 4),
                        "gy":  round(vals[4], 4),
                        "gz":  round(vals[5], 4),
                        "angle_deg":    round(vals[6], 2),
                        "omega_deg_s":  round(vals[7], 2),
                        "turn_counts":  vals[8],
                    })
        except socket.timeout:
            pass
        except Exception:
            pass


# ===== CSV flush thread =====
def csv_flush_thread(filepath):
    """Flush record_rows to CSV every 1 second."""
    fieldnames = [
        "time_s", "throttle_us", "steer_deg",
        "ax", "ay", "az", "gx", "gy", "gz",
        "angle_deg", "omega_deg_s", "turn_counts"
    ]
    # Write header
    with open(filepath, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=fieldnames).writeheader()

    while True:
        time.sleep(1.0)
        with record_lock:
            rows = record_rows.copy()
            record_rows.clear()
        if rows:
            with open(filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerows(rows)


# ===== Display helpers =====
def draw_steering_bar(value, min_val, max_val):
    if max_val == min_val:
        normalized = 0.5
    else:
        normalized = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    center = BAR_WIDTH // 2
    pos    = int(normalized * BAR_WIDTH)
    bar    = [' '] * BAR_WIDTH
    bar[center] = '|'
    if pos < center:
        for i in range(pos, center): bar[i] = '█'
    elif pos > center:
        for i in range(center + 1, min(pos + 1, BAR_WIDTH)): bar[i] = '█'
    pct = (normalized - 0.5) * 200
    direction = "LEFT " if pct < -1 else "RIGHT" if pct > 1 else "CENT "
    return f"[{''.join(bar)}] {pct:+6.1f}% {direction}"


def draw_pedal_bar(value, max_val=65535, label=""):
    pct    = min(100, (value / max_val) * 100) if max_val else 0
    filled = int((pct / 100) * BAR_WIDTH)
    bar    = '█' * filled + '░' * (BAR_WIDTH - filled)
    return f"{label:10} [{bar}] {pct:5.1f}%"


# ===== HID read loop =====
def read_device(device_info, ctrl_sock, csv_path):
    device = hid.device()
    device.open_path(device_info['path'])
    device.set_nonblocking(True)

    print(f"HID: {device_info.get('product_string','')}")
    print(f"UDP: {ESP32_IP}:{UDP_CTRL_PORT}")
    print(f"CSV: {csv_path}")
    print("Press Ctrl+C to stop.\n")
    print("\n" * 17)

    last_ctrl_send = 0
    steering_out   = 127
    throttle_out   = 0

    try:
        while True:
            data = device.read(64)
            now_ms = time.time() * 1000

            if data:
                if len(data) >= 4:
                    steering = (data[3] << 24) | (data[2] << 16) | (data[1] << 8) | data[0]
                else:
                    steering = 0

                if len(data) >= 13:
                    throttle = struct.unpack('<h', bytes([data[5],  data[6]]))[0]  + 32768
                    brake    = struct.unpack('<h', bytes([data[11], data[12]]))[0] + 32768
                else:
                    throttle = brake = 0

                s_range = steering_max - steering_min
                steering_out = int(max(0.0, min(1.0, (steering - steering_min) / s_range)) * 255) if s_range else 127
                throttle_out = int((throttle / 65535) * 255)

                # Redraw display (17 lines)
                sys.stdout.write('\033[17F')

                with tele_lock:
                    t = dict(tele_data)

                elapsed = round(time.time() - t0, 1)
                with record_lock:
                    nrows = len(record_rows)

                steer_servo = int(steering_out / 255 * (125 - 75) + 75)
                thr_us      = int(throttle_out / 255 * (1750 - 1500) + 1500)

                print("┌" + "─" * 78 + "┐")
                print(f"│  STEERING  {draw_steering_bar(steering, steering_min, steering_max):64} │")
                print(f"│  {draw_pedal_bar(throttle, 65535, 'THROTTLE'):74} │")
                print(f"│  {draw_pedal_bar(brake,    65535, 'BRAKE'):74} │")
                print("│" + " " * 78 + "│")
                print(f"│  CTRL TX → steer={steer_servo:3d}deg  throttle={thr_us:4d}us                                  │")
                print("│" + " " * 78 + "│")
                print(f"│  IMU  ax={t['ax']:6.2f}  ay={t['ay']:6.2f}  az={t['az']:6.2f}                                    │")
                print(f"│       gx={t['gx']:6.2f}  gy={t['gy']:6.2f}  gz={t['gz']:6.2f}                                    │")
                print(f"│  ENC  deg={t['angle']:6.1f}  omega={t['omega']:7.1f} deg/s  turns={t['turns']:6d}                   │")
                print("│" + " " * 78 + "│")
                print(f"│  REC  elapsed={elapsed:7.1f}s   buffered={nrows:4d} rows   → {os.path.basename(csv_path):30} │")
                print("└" + "─" * 78 + "┘")

            # Send ControlPacket every 50ms
            if (now_ms - last_ctrl_send) >= 50:
                steer_servo = int(steering_out / 255 * (125 - 75) + 75)
                thr_us      = int(throttle_out / 255 * (1750 - 1500) + 1500)
                with ctrl_lock:
                    ctrl_data["throttle_us"] = thr_us
                    ctrl_data["steer_deg"]   = steer_servo
                pkt = struct.pack(CTRL_FMT, thr_us, steer_servo)
                try:
                    ctrl_sock.sendto(pkt, (ESP32_IP, UDP_CTRL_PORT))
                except Exception:
                    pass
                last_ctrl_send = now_ms

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        device.close()
        # Final flush
        with record_lock:
            rows = record_rows.copy()
            record_rows.clear()
        if rows:
            fieldnames = [
                "time_s", "throttle_us", "steer_deg",
                "ax", "ay", "az", "gx", "gy", "gz",
                "angle_deg", "omega_deg_s", "turn_counts"
            ]
            with open(csv_path, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)
        print(f"CSV saved: {csv_path}")


def main():
    # Generate filename based on timestamp
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"log_{ts}.csv")

    print("=== RC Car UDP Recorder ===")
    print(f"ESP32: {ESP32_IP}  CTRL:{UDP_CTRL_PORT}  TELE:{UDP_TELE_PORT}")

    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    tele_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tele_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tele_sock.bind(("", UDP_TELE_PORT))
    tele_sock.settimeout(1.0)

    threading.Thread(target=tele_recv_thread, args=(tele_sock,),  daemon=True).start()
    threading.Thread(target=csv_flush_thread, args=(csv_path,),   daemon=True).start()

    devices = hid.enumerate()
    moza    = [d for d in devices
               if d['vendor_id'] in MOZA_VENDOR_IDS
               or 'moza' in str(d.get('product_string', '')).lower()]

    if not devices:
        print("No HID devices found.")
        sys.exit(1)

    if moza:
        read_device(moza[0], ctrl_sock, csv_path)
    else:
        print("No Moza device found. Available:")
        for i, d in enumerate(devices):
            print(f"  [{i}] 0x{d['vendor_id']:04X}:{d['product_id']:04X}  {d.get('product_string','')}")
        try:
            idx = int(input("Select: ").strip())
            read_device(devices[idx], ctrl_sock, csv_path)
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Bye.")

    ctrl_sock.close()
    tele_sock.close()


if __name__ == "__main__":
    main()
