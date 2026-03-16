#!/usr/bin/env python3
"""
cam_viewer.py
Receives JPEG stream from ESP32 (JST_CAM_STREAM) over TCP.
Displays with OpenCV + trackbar to adjust quality in real-time.
Press Q to quit.

Protocol:
  PC → ESP32 : 1 byte = JPEG quality (1-63)
  ESP32 → PC : [4-byte big-endian length] + [JPEG bytes]

Install: pip install opencv-python numpy
"""

import socket
import struct
import threading
import numpy as np
import cv2
import time

# ===== Config =====
ESP32_IP        = "192.168.1.17"  # <-- Enter the IP address of the ESP32
TCP_PORT        = 8080
INIT_QUALITY    = 48              # quality at startup (1=best, 63=worst)
RECONNECT_DELAY = 2.0

WINDOW = "ESP32-CAM 720p  |  Q=quit"

# ===== Shared state =====
sock_lock    = threading.Lock()
_sock        = None        # global socket ref for sending quality

last_quality = INIT_QUALITY
sent_quality = -1          # Prevent resending if value has not changed


def send_quality(q: int):
    """Send quality byte to ESP32 (thread-safe)"""
    global sent_quality
    q = max(1, min(63, q))
    if q == sent_quality:
        return
    with sock_lock:
        if _sock:
            try:
                _sock.sendall(bytes([q]))
                sent_quality = q
            except Exception:
                pass


def on_trackbar(val):
    """Callback when trackbar changes"""
    global last_quality
    last_quality = val
    send_quality(val)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            raise ConnectionError("Timeout waiting for data")

        if not chunk:
            raise ConnectionError("Connection closed")

        buf.extend(chunk)
    return bytes(buf)


def stream_loop(sock):
    global _sock
    fps_count = 0
    fps_time  = time.time()
    last_fps  = 0.0

    # Send first quality byte → trigger ESP32 to start stream
    sock.sendall(bytes([last_quality]))
    print(f"Sent START  quality={last_quality}")

    while True:
        # Read header
        print("Waiting frame...")
        header = recv_exact(sock, 4)
        print("Header received")
        size   = struct.unpack('>I', header)[0]

        if size == 0 or size > 300_000:
            raise ValueError(f"Invalid frame size: {size}")

        # Read JPEG
        jpeg = recv_exact(sock, size)

        # Decode
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if len(jpeg) < 1000:
            continue
        if img is None:
            continue

        # FPS
        fps_count += 1
        now = time.time()
        if now - fps_time >= 1.0:
            last_fps  = fps_count / (now - fps_time)
            fps_count = 0
            fps_time  = now

        # Overlay
        q = cv2.getTrackbarPos("Quality (1=best)", WINDOW)
        cv2.putText(img, f"FPS: {last_fps:.1f}   Q: {q}",
                    (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 2)

        cv2.imshow(WINDOW, img)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return False

    return True


def main():
    global _sock, sent_quality

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 1280, 760)

    # Trackbar: 1 (sharpest / large file) → 63 (blurry / small file / high FPS)
    cv2.createTrackbar("Quality (1=best)", WINDOW, INIT_QUALITY, 63, on_trackbar)

    print(f"Connecting to {ESP32_IP}:{TCP_PORT} ...")

    while True:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((ESP32_IP, TCP_PORT))
            s.settimeout(None)
            print(f"Connected  {ESP32_IP}:{TCP_PORT}")

            with sock_lock:
                _sock = s
            sent_quality = -1   # reset so it sends again

            keep = stream_loop(s)

            with sock_lock:
                _sock = None
            s.close()

            if not keep:
                break

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            with sock_lock:
                _sock = None
            print(f"Error: {e}  — reconnecting in {RECONNECT_DELAY}s ...")
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            time.sleep(RECONNECT_DELAY)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
