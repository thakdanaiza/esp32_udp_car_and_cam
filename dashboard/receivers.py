"""UDP receiver threads for telemetry and camera."""

import socket
import struct
import sys
import threading
import time

from .constants import (
    UDP_RELAY_PORT,
    TELE_FMT, TELE_SIZE,
    RELAY_FMT, RELAY_SIZE,
    RELAY_GEAR_FMT, RELAY_GEAR_SIZE,
    CAM_IP, CAM_CMD_PORT, CAM_STREAM_PORT,
)


def start_telemetry_receiver(buf, port=None):
    """Start a daemon thread that receives telemetry UDP packets into *buf*."""
    if port is None:
        port = UDP_RELAY_PORT

    def _recv():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.settimeout(1.0)
        recv_count = 0
        last_log = time.time()
        while True:
            try:
                data, addr = sock.recvfrom(256)
                if len(data) == RELAY_GEAR_SIZE:
                    buf.append(struct.unpack(RELAY_GEAR_FMT, data))
                    recv_count += 1
                elif len(data) == RELAY_SIZE:
                    buf.append(struct.unpack(RELAY_FMT, data))
                    recv_count += 1
                elif len(data) == TELE_SIZE:
                    buf.append(struct.unpack(TELE_FMT, data))
                    recv_count += 1
                else:
                    print(
                        f"[DASH RECV] unexpected size={len(data)} from {addr}",
                        file=sys.stderr,
                    )
                now = time.time()
                if now - last_log >= 5.0:
                    print(
                        f"[DASH] received {recv_count} telemetry packets so far",
                        file=sys.stderr,
                    )
                    last_log = now
            except socket.timeout:
                pass
            except Exception as e:
                print(f"[DASH RECV ERR] {e}", file=sys.stderr)

    t = threading.Thread(target=_recv, daemon=True)
    t.start()
    return t


def start_camera_receiver(cam_buffer):
    """Start daemon threads for camera stream reception and quality command sending."""

    def _cam_recv():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        sock.bind(("", CAM_STREAM_PORT))
        sock.settimeout(1.0)
        while True:
            try:
                data, _ = sock.recvfrom(1500)
                cam_buffer.feed(data)
            except socket.timeout:
                pass
            except Exception as e:
                print(f"[CAM RECV ERR] {e}", file=sys.stderr)

    def _cam_quality():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while True:
            q = max(1, min(63, cam_buffer.quality))
            sock.sendto(bytes([q]), (CAM_IP, CAM_CMD_PORT))
            time.sleep(1.0)

    threading.Thread(target=_cam_recv, daemon=True).start()
    threading.Thread(target=_cam_quality, daemon=True).start()
    print(f"CAMERA — Streaming from {CAM_IP} cmd:{CAM_CMD_PORT} stream:{CAM_STREAM_PORT}")
