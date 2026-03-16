"""Thread-safe telemetry and camera buffers."""

import struct
import threading
import time
from collections import deque

import pandas as pd

from .constants import CAM_QUALITY


class TelemetryBuffer:
    def __init__(self, window_s=60):
        self._lock = threading.Lock()
        self._buf = deque()
        self._t0 = None
        self.window_s = window_s

    def append(self, vals):
        with self._lock:
            now = time.time()
            if self._t0 is None:
                self._t0 = now
            t = round(now - self._t0, 4)
            entry = {
                "time_s": t,
                "ax": vals[0], "ay": vals[1], "az": vals[2],
                "gx": vals[3], "gy": vals[4], "gz": vals[5],
                "angle_deg": vals[6], "omega_deg_s": vals[7], "turn_counts": vals[8],
            }
            if len(vals) >= 11:
                entry["throttle_us"] = vals[9]
                entry["steer_deg"] = vals[10]
            if len(vals) >= 12:
                entry["gear"] = vals[11]
            self._buf.append(entry)
            cutoff = t - self.window_s
            while self._buf and self._buf[0]["time_s"] < cutoff:
                self._buf.popleft()

    def snapshot(self):
        with self._lock:
            if not self._buf:
                return pd.DataFrame()
            return pd.DataFrame(list(self._buf))


class CameraBuffer:
    """Thread-safe chunked-UDP JPEG reassembler."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest_jpeg = None
        self.quality = CAM_QUALITY
        self._cur_frame_id = -1
        self._cur_total = 0
        self._cur_chunks = {}

    def feed(self, data):
        if len(data) < 5:
            return
        frame_id = struct.unpack('<H', data[:2])[0]
        chunk_idx = data[2]
        total_chunks = data[3]
        payload = data[4:]

        if frame_id != self._cur_frame_id:
            self._cur_frame_id = frame_id
            self._cur_total = total_chunks
            self._cur_chunks = {}

        self._cur_chunks[chunk_idx] = payload

        if len(self._cur_chunks) == self._cur_total:
            jpeg = b''.join(
                self._cur_chunks[i] for i in range(self._cur_total)
                if i in self._cur_chunks
            )
            with self._lock:
                self._latest_jpeg = jpeg
            self._cur_chunks = {}

    def get_latest(self):
        with self._lock:
            return self._latest_jpeg
