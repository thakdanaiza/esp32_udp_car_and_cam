#!/usr/bin/env python3
"""
cam_viewer.py
Receives JPEG stream from ESP32 (JST_CAM_STREAM) over UDP.
Displays with OpenCV + trackbar to adjust quality in real-time.
Press Q to quit.

Protocol:
  PC → ESP32 (UDP port 8080): 1 byte = JPEG quality (1-63), resent every 1s
  ESP32 → PC (UDP port 8081): chunked frames
    Each chunk: [2B LE frame_id][1B chunk_index][1B total_chunks][payload]

Architecture:
  Receiver thread: recvfrom → reassemble chunks → store latest frame → loop
  Main thread:     grab latest frame → decode → overlay → display → loop

Install: pip install opencv-python numpy
"""

import socket
import struct
import threading
import numpy as np
import cv2
import time

# ===== Config =====
ESP32_IP        = "192.168.1.17"
UDP_CMD_PORT    = 8080            # send quality commands to ESP32
UDP_STREAM_PORT = 8081            # receive frames from ESP32
INIT_QUALITY    = 48              # quality at startup (1=best, 63=worst)
QUALITY_RESEND  = 1.0             # resend quality every N seconds

WINDOW = "ESP32-CAM VGA  |  Q=quit"

# ===== Shared state =====
frame_lock   = threading.Lock()
_latest_jpeg = None
_frame_seq   = 0

last_quality = INIT_QUALITY


def on_trackbar(val):
    global last_quality
    last_quality = max(1, min(63, val))


def receiver_thread(recv_sock, stop_event, drop_counter):
    """Background thread: receives UDP chunks, reassembles into JPEG frames."""
    global _latest_jpeg, _frame_seq

    last_frame_id = -1
    # Reassembly state for current frame
    cur_frame_id = -1
    cur_total = 0
    cur_chunks = {}

    while not stop_event.is_set():
        try:
            data, addr = recv_sock.recvfrom(1500)
            if len(data) < 5:  # 4-byte header + at least 1 byte payload
                continue

            frame_id = struct.unpack('<H', data[:2])[0]
            chunk_idx = data[2]
            total_chunks = data[3]
            payload = data[4:]

            # New frame — reset reassembly buffer
            if frame_id != cur_frame_id:
                # Count dropped frames
                if last_frame_id >= 0 and cur_frame_id >= 0:
                    gap = (frame_id - last_frame_id - 1) & 0xFFFF
                    if gap > 0:
                        drop_counter[0] += gap
                last_frame_id = frame_id
                cur_frame_id = frame_id
                cur_total = total_chunks
                cur_chunks = {}

            cur_chunks[chunk_idx] = payload

            # All chunks received — assemble JPEG
            if len(cur_chunks) == cur_total:
                jpeg = b''.join(cur_chunks[i] for i in range(cur_total)
                                if i in cur_chunks)
                with frame_lock:
                    _latest_jpeg = jpeg
                    _frame_seq += 1
                cur_chunks = {}  # done with this frame

        except socket.timeout:
            continue
        except Exception:
            if not stop_event.is_set():
                break


def main():
    global _latest_jpeg, _frame_seq

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 960, 720)
    cv2.createTrackbar("Quality (1=best)", WINDOW, INIT_QUALITY, 63, on_trackbar)

    # UDP sockets
    cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind(("", UDP_STREAM_PORT))
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
    recv_sock.settimeout(1.0)

    drop_counter = [0]  # mutable container for thread access
    stop_event = threading.Event()
    recv_t = threading.Thread(
        target=receiver_thread, args=(recv_sock, stop_event, drop_counter), daemon=True
    )
    recv_t.start()

    fps_count    = 0
    fps_time     = time.time()
    last_fps     = 0.0
    last_seq     = 0
    last_img     = None
    last_send    = 0.0

    print(f"Streaming from {ESP32_IP} — UDP cmd:{UDP_CMD_PORT} stream:{UDP_STREAM_PORT}")

    try:
        while True:
            # Periodic quality resend (covers startup + UDP loss)
            now = time.time()
            if now - last_send >= QUALITY_RESEND:
                q = last_quality
                cmd_sock.sendto(bytes([max(1, min(63, q))]), (ESP32_IP, UDP_CMD_PORT))
                last_send = now

            # Grab latest frame
            with frame_lock:
                jpeg = _latest_jpeg
                seq  = _frame_seq

            if seq != last_seq and jpeg is not None:
                last_seq = seq
                arr = np.frombuffer(jpeg, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    last_img = img
                    fps_count += 1

            if last_img is None:
                key = cv2.waitKey(10) & 0xFF
                if key == ord('q'):
                    break
                continue

            # FPS calc
            if now - fps_time >= 1.0:
                last_fps  = fps_count / (now - fps_time)
                fps_count = 0
                fps_time  = now

            # Overlay
            q = cv2.getTrackbarPos("Quality (1=best)", WINDOW)
            cv2.putText(last_img, f"FPS: {last_fps:.1f}  Q: {q}  drops: {drop_counter[0]}",
                        (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            cv2.imshow(WINDOW, last_img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop_event.set()
        recv_t.join(timeout=2.0)
        cmd_sock.close()
        recv_sock.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
