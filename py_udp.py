#!/usr/bin/env python3
"""
Moza Racing HID reader + UDP controller for ESP32 RC Car.
Sends ControlPacket (throttle/steering) to ESP32 via UDP.
Receives TelemetryPacket (IMU + encoder) from ESP32 via UDP.
"""

import hid
import time
import sys
import struct
import socket
import threading

# ===== UDP Config =====
ESP32_IP        = "192.168.1.12"   # <-- Enter the IP of the ESP32 (check Serial Monitor or from the connected WiFi router)
UDP_CTRL_PORT   = 5005             # port that ESP32 receives control on
UDP_TELE_PORT   = 5006             # port that PC receives telemetry on
DASHBOARD_PORT  = 5007             # relay telemetry to dashboard on localhost

# ===== Packet format (must match ESP32 structs, packed) =====
# ControlPacket:   int16 throttle, int16 steering  → 4 bytes
# TelemetryPacket: 8x float + 1x int32            → 36 bytes
CTRL_FMT = '<hh'
TELE_FMT = '<ffffffffi'
CTRL_SIZE = struct.calcsize(CTRL_FMT)   # 4
TELE_SIZE = struct.calcsize(TELE_FMT)   # 36

# ===== Display =====
BAR_WIDTH         = 50
STEERING_BAR_WIDTH = 50

# ===== Moza =====
MOZA_VENDOR_IDS = [0x346E]
steering_min    = 16777217
steering_max    = 33554177

# ===== Relay packet format (telemetry + control) =====
RELAY_FMT = '<ffffffffihh'   # telemetry (36 bytes) + throttle_us, steer_deg (4 bytes) = 40 bytes

# ===== Telemetry state (shared with receive thread) =====
tele_lock = threading.Lock()
tele_data = {
    "ax": 0.0, "ay": 0.0, "az": 0.0,
    "gx": 0.0, "gy": 0.0, "gz": 0.0,
    "angle": 0.0, "omega": 0.0, "turns": 0
}

# ===== Control state (shared with relay) =====
ctrl_lock = threading.Lock()
ctrl_state = {"throttle_us": 1500, "steer_deg": 100}


def tele_recv_thread(sock, relay_sock):
    """Background thread: receive TelemetryPacket from ESP32 and relay to dashboard."""
    while True:
        try:
            data, _ = sock.recvfrom(256)
            if len(data) == TELE_SIZE:
                vals = struct.unpack(TELE_FMT, data)
                with tele_lock:
                    tele_data["ax"]    = vals[0]
                    tele_data["ay"]    = vals[1]
                    tele_data["az"]    = vals[2]
                    tele_data["gx"]    = vals[3]
                    tele_data["gy"]    = vals[4]
                    tele_data["gz"]    = vals[5]
                    tele_data["angle"] = vals[6]
                    tele_data["omega"] = vals[7]
                    tele_data["turns"] = vals[8]
                try:
                    with ctrl_lock:
                        thr   = ctrl_state["throttle_us"]
                        steer = ctrl_state["steer_deg"]
                    relay_pkt = data + struct.pack('<hh', thr, steer)
                    relay_sock.sendto(relay_pkt, ("127.0.0.1", DASHBOARD_PORT))
                except Exception:
                    pass
        except Exception:
            pass


def draw_steering_bar(value, min_val, max_val):
    if max_val == min_val:
        normalized = 0.5
    else:
        normalized = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    center_pos = STEERING_BAR_WIDTH // 2
    pos  = int(normalized * STEERING_BAR_WIDTH)
    bar  = [' '] * STEERING_BAR_WIDTH
    bar[center_pos] = '|'
    if pos < center_pos:
        for i in range(pos, center_pos):
            bar[i] = '█'
    elif pos > center_pos:
        for i in range(center_pos + 1, min(pos + 1, STEERING_BAR_WIDTH)):
            bar[i] = '█'
    percentage = (normalized - 0.5) * 200
    direction  = "LEFT " if percentage < -1 else "RIGHT" if percentage > 1 else "CENTER"
    return f"[{''.join(bar)}] {percentage:+6.1f}% {direction}"


def draw_pedal_bar(value, max_val=65535, label=""):
    percentage = min(100, (value / max_val) * 100) if max_val else 0
    filled = int((percentage / 100) * BAR_WIDTH)
    bar = '█' * filled + '░' * (BAR_WIDTH - filled)
    return f"{label:10} [{bar}] {percentage:5.1f}%"


def list_hid_devices():
    devices      = hid.enumerate()
    moza_devices = [d for d in devices
                    if d['vendor_id'] in MOZA_VENDOR_IDS
                    or 'moza' in str(d.get('product_string', '')).lower()]
    return devices, moza_devices


def read_device(device_info, ctrl_sock):
    vid     = device_info['vendor_id']
    pid     = device_info['product_id']
    product = device_info.get('product_string', 'Unknown')
    print(f"\nConnecting to: {product} (VID: 0x{vid:04X}, PID: 0x{pid:04X})")

    device = hid.device()
    device.open_path(device_info['path'])
    device.set_nonblocking(True)

    print(f"HID connected. Sending control to {ESP32_IP}:{UDP_CTRL_PORT}")
    print(f"Receiving telemetry on port {UDP_TELE_PORT}")
    print("Press Ctrl+C to stop.\n")
    print("\n" * 16)

    last_serial_send = 0
    steering_out     = 127
    throttle_out     = 0
    gear = 0
    left_flag, right_flag, N_flag, R_flag = 0, 0, 0, 0

    try:
        while True:
            data = device.read(64)
            current_ms = time.time() * 1000

            if data:
                # Parse steering (32-bit LE)
                if len(data) >= 4:
                    steering = (data[3] << 24) | (data[2] << 16) | (data[1] << 8) | data[0]
                else:
                    steering = 0

                # Parse throttle/brake (signed 16-bit)
                if len(data) >= 13:
                    throttle_s = struct.unpack('<h', bytes([data[5],  data[6]]))[0]
                    brake_s    = struct.unpack('<h', bytes([data[11], data[12]]))[0]
                    throttle   = throttle_s + 32768
                    brake      = brake_s    + 32768
                else:
                    throttle = brake = 0

                # Parse gearing buttons (1-bit)
                if len(data) >= 21:
                    paddle_left  = (data[19] >> 0) & 1
                    paddle_right = (data[19] >> 1) & 1
                    N_button     = (data[19] >> 6) & 1
                    R_button     = (data[21] >> 6) & 1
                    
                    

                # Normalize to 0-255
                s_range = steering_max - steering_min
                steering_out = int(max(0.0, min(1.0, (steering - steering_min) / s_range)) * 255) if s_range else 127
                throttle_out = int((throttle / 65535) * 255)
                brake_out    = int((brake / 65535) * 255)

                # gear functioning
                if gear == 0: throttle_out = 0
                if paddle_left and not left_flag:
                    left_flag = 1
                    if gear > 0:
                        gear -= 1
                if not paddle_left and left_flag:
                    left_flag = 0

                if paddle_right and not right_flag:
                    right_flag = 1
                    if gear < 3:
                        if R_flag:
                            R_flag = 0
                            gear = 0
                        gear += 1
                if not paddle_right and right_flag:
                    right_flag = 0

                if N_button and not N_flag:
                    gear = 0

                if R_button and gear == 0:
                    R_flag = 1
                    gear = -1

                # Redraw display (16 lines)
                sys.stdout.write('\033[16F')

                raw_disp = " ".join(f"{i}:{data[i]:3d}" for i in range(min(12, len(data))))

                with tele_lock:
                    t = dict(tele_data)

                print("┌" + "─" * 85 + "┐")
                print(f"│  STEERING  {draw_steering_bar(steering, steering_min, steering_max):64}      │")
                print(f"│  Raw: {steering:12d}                                                                  │")
                print("│" + " " * 85 + "│")
                print(f"│  {draw_pedal_bar(throttle, 65535, 'THROTTLE'):74}         │")
                print(f"│  {draw_pedal_bar(brake,    65535, 'BRAKE'):74}         │")
                print("│" + " " * 85 + "│")
                print(f"│  UDP TX → {ESP32_IP}:{UDP_CTRL_PORT} <gear = [{gear}]> <str={steering_out},thr={throttle_out},brk={brake_out},pL={paddle_left},pR={paddle_right},N={N_button},R={R_button}>    │")
                print("│" + " " * 85 + "│")
                print(f"│  IMU  A [{t['ax']:6.2f} {t['ay']:6.2f} {t['az']:6.2f}]"
                      f"  G [{t['gx']:6.2f} {t['gy']:6.2f} {t['gz']:6.2f}]                            │")
                print(f"│  ENC  deg={t['angle']:6.1f}  omega={t['omega']:7.1f} deg/s  turns={t['turns']:6d}                                 │")
                # print("│" + " " * 85 + "│")
                # print(f"│  Raw bytes: {raw_disp:64} │")
                print("└" + "─" * 85 + "┘")

            # Send ControlPacket every 50ms
            if (current_ms - last_serial_send) >= 50:
                # map 0-255 steering → servo degrees (75-125)
                steer_servo = int(steering_out / 255 * (125 - 75) + 75)
                # map 0-255 throttle → ESC microseconds (1500-1750)
                match gear:
                    case 1:
                        thr_us = int(throttle_out / 255 * (1650 - 1500) + 1500)
                    case 2:
                        thr_us = int(throttle_out / 255 * (1750 - 1500) + 1500)
                    case 3:
                        thr_us = int(throttle_out / 255 * (1850 - 1500) + 1500)
                    case -1:
                        thr_us = int(1500 - (throttle_out / 255 * (1500 - 1250)))
                    case 0:
                        thr_us = 1500
                pkt = struct.pack(CTRL_FMT, thr_us, steer_servo)
                with ctrl_lock:
                    ctrl_state["throttle_us"] = thr_us
                    ctrl_state["steer_deg"] = steer_servo
                try:
                    ctrl_sock.sendto(pkt, (ESP32_IP, UDP_CTRL_PORT))
                except Exception:
                    pass
                last_serial_send = current_ms

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    finally:
        device.close()
        print("HID device closed.")


def main():
    print("\nMoza Racing + ESP32 UDP Controller")
    print("=" * 70)
    print(f"ESP32 IP : {ESP32_IP}")
    print(f"CTRL port: {UDP_CTRL_PORT}  (TX to ESP32)")
    print(f"TELE port: {UDP_TELE_PORT}  (RX from ESP32)")
    print("=" * 70)

    # UDP socket for sending control
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctrl_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # UDP socket for receiving telemetry
    tele_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tele_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tele_sock.bind(("", UDP_TELE_PORT))
    tele_sock.settimeout(1.0)

    # Relay socket for forwarding telemetry to dashboard
    relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Start receive thread
    t = threading.Thread(target=tele_recv_thread, args=(tele_sock, relay_sock), daemon=True)
    t.start()

    # Find Moza HID
    all_devices, moza_devices = list_hid_devices()
    if not all_devices:
        print("No HID devices found!")
        sys.exit(1)

    if moza_devices:
        print(f"Found Moza device: {moza_devices[0].get('product_string','')}")
        read_device(moza_devices[0], ctrl_sock)
    else:
        print("No Moza device found. Available HID devices:")
        for i, d in enumerate(all_devices):
            print(f"  [{i}] 0x{d['vendor_id']:04X}:{d['product_id']:04X}  {d.get('product_string','')}")
        try:
            idx = int(input("Select device number: ").strip())
            read_device(all_devices[idx], ctrl_sock)
        except (ValueError, IndexError, KeyboardInterrupt):
            print("Bye.")

    ctrl_sock.close()
    tele_sock.close()


if __name__ == "__main__":
    main()
