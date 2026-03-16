"""Shared constants: ports, packet formats, colors, styles."""

import struct

# ---------------------------------------------------------------------------
# Network / packet formats
# ---------------------------------------------------------------------------
UDP_TELE_PORT = 5006       # direct from ESP32
UDP_RELAY_PORT = 5007      # relayed from py_udp.py

TELE_FMT = '<ffffffffi'
TELE_SIZE = struct.calcsize(TELE_FMT)             # 36

RELAY_FMT = '<ffffffffihh'                        # tele + throttle_us + steer_deg
RELAY_SIZE = struct.calcsize(RELAY_FMT)            # 40

RELAY_GEAR_FMT = '<ffffffffihhh'                  # tele + throttle_us + steer_deg + gear
RELAY_GEAR_SIZE = struct.calcsize(RELAY_GEAR_FMT)  # 42

LIVE_WINDOW_SECONDS = 60
LIVE_UPDATE_MS = 200  # 5 Hz dashboard refresh

# Camera (chunked UDP from ESP32-CAM)
CAM_IP = "192.168.1.17"
CAM_CMD_PORT = 8080
CAM_STREAM_PORT = 8081
CAM_QUALITY = 48
CAM_QUALITY_RESEND = 1.0
SHOW_CAMERA = True
SHOW_GFORCE = True

# Hardware
WHEEL_DIAMETER_MM = 65

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"
RED = "#ff4444"
CYAN = "#00d4ff"
GOLD = "#ffd700"
GREEN = "#3fb950"
MAGENTA = "#f778ba"
ORANGE = "#f0883e"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
PLOT_BG = "#0d1117"
GRID = "#21262d"

# ---------------------------------------------------------------------------
# Plotly common settings
# ---------------------------------------------------------------------------
FONT = dict(family="JetBrains Mono, monospace", color=TEXT, size=11)
LAYOUT_COMMON = dict(
    template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=PLOT_BG, font=FONT,
)
