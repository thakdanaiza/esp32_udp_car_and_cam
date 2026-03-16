#!/usr/bin/env python3
"""JST Racing Telemetry Dashboard — browser-based viewer for log CSV files or live UDP telemetry."""

import sys
import glob
import os
import time
import struct
import socket
import threading
import base64
from collections import deque

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, html, dcc, Output, Input, State

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UDP_TELE_PORT = 5006       # direct from ESP32
UDP_RELAY_PORT = 5007      # relayed from py_udp.py
TELE_FMT = '<ffffffffi'
TELE_SIZE = struct.calcsize(TELE_FMT)  # 36
RELAY_FMT = '<ffffffffihh'             # telemetry + throttle_us + steer_deg
RELAY_SIZE = struct.calcsize(RELAY_FMT) # 40
LIVE_WINDOW_SECONDS = 60
LIVE_UPDATE_MS = 200  # 5 Hz dashboard refresh
SHOW_GFORCE = True

# Camera (chunked UDP from ESP32-CAM)
CAM_IP = "192.168.1.17"
CAM_CMD_PORT = 8080
CAM_STREAM_PORT = 8081
CAM_QUALITY = 48
CAM_QUALITY_RESEND = 1.0
SHOW_CAMERA = True

# Color palette
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

FONT = dict(family="JetBrains Mono, monospace", color=TEXT, size=11)
LAYOUT_COMMON = dict(template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=PLOT_BG, font=FONT)

# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------
live_mode = "--live" in sys.argv

# ---------------------------------------------------------------------------
# Telemetry buffer (live mode)
# ---------------------------------------------------------------------------

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
            self._buf.append(entry)
            # Trim old data outside window
            cutoff = t - self.window_s
            while self._buf and self._buf[0]["time_s"] < cutoff:
                self._buf.popleft()

    def snapshot(self):
        with self._lock:
            if not self._buf:
                return pd.DataFrame()
            return pd.DataFrame(list(self._buf))


class CameraBuffer:
    """Thread-safe chunked-UDP JPEG reassembler (same protocol as cam_viewer.py)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest_jpeg = None
        self.quality = CAM_QUALITY
        # reassembly state
        self._cur_frame_id = -1
        self._cur_total = 0
        self._cur_chunks = {}

    def feed(self, data):
        """Feed a raw UDP packet; reassemble and store completed JPEG."""
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
            jpeg = b''.join(self._cur_chunks[i] for i in range(self._cur_total)
                            if i in self._cur_chunks)
            with self._lock:
                self._latest_jpeg = jpeg
            self._cur_chunks = {}

    def get_latest(self):
        with self._lock:
            return self._latest_jpeg


def udp_receiver(buf):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    port = UDP_RELAY_PORT if live_mode else UDP_TELE_PORT
    sock.bind(("", port))
    sock.settimeout(1.0)
    recv_count = 0
    last_log = time.time()
    while True:
        try:
            data, addr = sock.recvfrom(256)
            if len(data) == RELAY_SIZE:
                buf.append(struct.unpack(RELAY_FMT, data))
                recv_count += 1
            elif len(data) == TELE_SIZE:
                buf.append(struct.unpack(TELE_FMT, data))
                recv_count += 1
            else:
                print(f"[DASH RECV] unexpected packet size={len(data)} from {addr}", file=sys.stderr)
            now = time.time()
            if now - last_log >= 5.0:
                print(f"[DASH] received {recv_count} telemetry packets so far", file=sys.stderr)
                last_log = now
        except socket.timeout:
            pass
        except Exception as e:
            print(f"[DASH RECV ERR] {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CSV loading (csv mode)
# ---------------------------------------------------------------------------
df = None
filename = None

if not live_mode:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        csv_path = args[0]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = sorted(glob.glob(os.path.join(script_dir, "log_*.csv")))
        if not candidates:
            print("Usage: python dashboard.py [path/to/log.csv]")
            print("       python dashboard.py --live")
            print("No log_*.csv found in script directory.")
            sys.exit(1)
        csv_path = candidates[-1]

    print(f"Loading {csv_path} ...")
    df = pd.read_csv(csv_path)
    filename = os.path.basename(csv_path)

    # Insert NaN rows at time gaps > 0.5s to break plotly lines
    t = df["time_s"].values
    dt = np.diff(t)
    gap_idx = np.where(dt > 0.5)[0]
    if len(gap_idx) > 0:
        gap_rows = []
        for i in gap_idx:
            row = {col: np.nan for col in df.columns}
            row["time_s"] = (df["time_s"].iloc[i] + df["time_s"].iloc[i + 1]) / 2
            gap_rows.append(row)
        df = pd.concat([df, pd.DataFrame(gap_rows)], ignore_index=True)
        df = df.sort_values("time_s").reset_index(drop=True)

    # G-force columns are added later when building the layout

# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def _add_gforce_cols(dataframe):
    """Add gravity-corrected G-force columns."""
    ax_mean = dataframe["ax"].mean()
    ay_mean = dataframe["ay"].mean()
    az_mean = dataframe["az"].mean()
    dataframe["ax_corr"] = dataframe["ax"] - ax_mean
    dataframe["ay_corr"] = dataframe["ay"] - ay_mean
    dataframe["az_corr"] = dataframe["az"] - az_mean
    dataframe["g_lateral"] = dataframe["ax_corr"] / 9.81
    dataframe["g_longitudinal"] = dataframe["ay_corr"] / 9.81
    dataframe["g_resultant"] = np.sqrt(
        dataframe["ax_corr"]**2 + dataframe["ay_corr"]**2 + dataframe["az_corr"]**2
    ) / 9.81
    return dataframe


def build_timeseries_fig(dataframe, has_control_cols=True):
    """Build the main time-series subplot figure."""
    t = dataframe["time_s"].values

    if has_control_cols:
        row_titles = [
            "Throttle (µs)", "Steering (deg)",
            "Accelerometer (m/s²)", "Gyroscope (rad/s)",
            "Wheel ω (deg/s)", "Turn Counts",
        ]
        n_rows = 6
        row_heights = [1, 1, 1.5, 1.5, 1, 1]
    else:
        row_titles = [
            "Accelerometer (m/s²)", "Gyroscope (rad/s)",
            "Wheel ω (deg/s)", "Turn Counts",
        ]
        n_rows = 4
        row_heights = [1.5, 1.5, 1, 1]

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=row_titles,
    )

    r = 1  # current row counter

    if has_control_cols:
        # Throttle
        fig.add_trace(go.Scatter(
            x=t, y=dataframe["throttle_us"], mode="lines", name="Throttle",
            fill="tozeroy", fillcolor="rgba(255,68,68,0.15)",
            line=dict(color=RED, width=1.5),
        ), row=r, col=1)
        fig.add_hline(y=1500, line_dash="dot", line_color=TEXT_DIM, opacity=0.5, row=r, col=1)
        r += 1

        # Steering
        fig.add_trace(go.Scatter(
            x=t, y=dataframe["steer_deg"], mode="lines", name="Steering",
            line=dict(color=CYAN, width=1.5),
        ), row=r, col=1)
        for ref_y in [75, 100, 125]:
            fig.add_hline(y=ref_y, line_dash="dot", line_color=TEXT_DIM, opacity=0.3, row=r, col=1)
        r += 1

    # Accelerometer
    for col_name, color, label in [("ax", RED, "ax"), ("ay", GREEN, "ay"), ("az", BLUE, "az")]:
        fig.add_trace(go.Scatter(
            x=t, y=dataframe[col_name], mode="lines", name=label,
            line=dict(color=color, width=1),
        ), row=r, col=1)
    r += 1

    # Gyroscope
    for col_name, color, label in [("gx", RED, "gx"), ("gy", GREEN, "gy"), ("gz", BLUE, "gz")]:
        fig.add_trace(go.Scatter(
            x=t, y=dataframe[col_name], mode="lines", name=label,
            line=dict(color=color, width=1),
        ), row=r, col=1)
    r += 1

    # Omega
    fig.add_trace(go.Scatter(
        x=t, y=dataframe["omega_deg_s"], mode="lines", name="ω",
        line=dict(color=GOLD, width=1.5),
    ), row=r, col=1)
    r += 1

    # Turn counts
    fig.add_trace(go.Scatter(
        x=t, y=dataframe["turn_counts"], mode="markers", name="Turns",
        marker=dict(color=MAGENTA, size=3),
    ), row=r, col=1)

    fig.update_layout(
        **LAYOUT_COMMON,
        height=900 if not has_control_cols else 1100,
        margin=dict(l=60, r=20, t=30, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(size=10)),
        hovermode="x unified",
        uirevision="constant",
    )
    fig.update_xaxes(
        gridcolor=GRID, zeroline=False, showgrid=True,
        title_text="Time (s)", row=n_rows, col=1,
    )
    for i in range(1, n_rows + 1):
        fig.update_yaxes(gridcolor=GRID, zeroline=False, showgrid=True, row=i, col=1)

    for ann in fig.layout.annotations:
        ann.update(font=dict(size=11, color=TEXT_DIM), xanchor="left", x=0.01)

    return fig


def build_gforce_fig(dataframe):
    """Build the G-force scatter figure."""
    dataframe = _add_gforce_cols(dataframe.copy())
    valid = dataframe.dropna(subset=["g_lateral", "g_longitudinal"])

    theta = np.linspace(0, 2 * np.pi, 100)
    gfig = go.Figure()
    for r in [0.05, 0.1, 0.15]:
        gfig.add_trace(go.Scatter(
            x=r * np.cos(theta), y=r * np.sin(theta),
            mode="lines", line=dict(color=BORDER, width=1, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

    if not valid.empty:
        gfig.add_trace(go.Scatter(
            x=valid["g_lateral"], y=valid["g_longitudinal"],
            mode="markers",
            marker=dict(
                size=5, color=valid["time_s"], colorscale="Hot",
                colorbar=dict(title="Time (s)", thickness=12, len=0.8),
                opacity=0.8,
            ),
            name="G-Force",
            hovertemplate="Lat: %{x:.3f}G<br>Long: %{y:.3f}G<extra></extra>",
        ))
        max_g_range = max(0.2, valid["g_lateral"].abs().max(), valid["g_longitudinal"].abs().max()) * 1.2
    else:
        max_g_range = 0.2

    gfig.update_layout(
        **LAYOUT_COMMON,
        height=450,
        margin=dict(l=50, r=20, t=30, b=50),
        xaxis=dict(title="Lateral G", gridcolor=GRID, range=[-max_g_range, max_g_range],
                   scaleanchor="y", scaleratio=1, zeroline=True, zerolinecolor=BORDER),
        yaxis=dict(title="Longitudinal G", gridcolor=GRID, range=[-max_g_range, max_g_range],
                   zeroline=True, zerolinecolor=BORDER),
        showlegend=False,
        uirevision="constant",
    )
    return gfig


def build_steering_wheel_fig(steer_deg=100):
    """Build a steering wheel visualization. steer_deg: 75 (left) - 100 (center) - 125 (right)."""
    # Map servo 75-125 → visual rotation ±90°
    rotation_deg = (steer_deg - 100) / 25 * 90
    angle_rad = np.radians(-rotation_deg)  # negative so clockwise = right

    fig = go.Figure()

    # Outer rim
    theta = np.linspace(0, 2 * np.pi, 120)
    rim_r = 1.0
    fig.add_trace(go.Scatter(
        x=rim_r * np.cos(theta), y=rim_r * np.sin(theta),
        mode="lines", line=dict(color=CYAN, width=4),
        showlegend=False, hoverinfo="skip",
    ))

    # Three spokes at 120° apart, rotated
    spoke_len = 0.75
    for base_angle in [np.pi / 2, np.pi / 2 + 2 * np.pi / 3, np.pi / 2 + 4 * np.pi / 3]:
        a = base_angle + angle_rad
        fig.add_trace(go.Scatter(
            x=[0, spoke_len * np.cos(a)], y=[0, spoke_len * np.sin(a)],
            mode="lines", line=dict(color=TEXT, width=3),
            showlegend=False, hoverinfo="skip",
        ))

    # Center hub
    hub_theta = np.linspace(0, 2 * np.pi, 60)
    hub_r = 0.18
    fig.add_trace(go.Scatter(
        x=hub_r * np.cos(hub_theta), y=hub_r * np.sin(hub_theta),
        mode="lines", fill="toself", fillcolor=CARD_BG,
        line=dict(color=TEXT, width=2),
        showlegend=False, hoverinfo="skip",
    ))

    # Top marker (fixed reference)
    fig.add_trace(go.Scatter(
        x=[0], y=[1.2],
        mode="markers", marker=dict(symbol="triangle-down", size=14, color=RED),
        showlegend=False, hoverinfo="skip",
    ))

    # Direction label
    if rotation_deg < -2:
        direction = "LEFT"
        dir_color = CYAN
    elif rotation_deg > 2:
        direction = "RIGHT"
        dir_color = ORANGE
    else:
        direction = "CENTER"
        dir_color = GREEN

    fig.update_layout(
        **LAYOUT_COMMON,
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-1.5, 1.5], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-1.5, 1.5]),
        showlegend=False,
        annotations=[
            dict(text=f"{steer_deg}°", x=0, y=0, showarrow=False,
                 font=dict(size=16, color=TEXT, family="JetBrains Mono, monospace")),
            dict(text=direction, x=0, y=-1.35, showarrow=False,
                 font=dict(size=13, color=dir_color, family="JetBrains Mono, monospace",
                           weight="bold")),
        ],
        uirevision="constant",
    )
    return fig


def empty_figure(height, message="Waiting for telemetry..."):
    fig = go.Figure()
    fig.update_layout(
        **LAYOUT_COMMON, height=height,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=message, showarrow=False,
                          font=dict(size=20, color=TEXT_DIM),
                          x=0.5, y=0.5, xref="paper", yref="paper")],
    )
    return fig

# ---------------------------------------------------------------------------
# Dash app + styles
# ---------------------------------------------------------------------------
app = Dash(__name__)
app.title = "JST Racing Telemetry"

@app.server.before_request
def _fix_dash4_input_batching():
    """Dash 4 client-side bug: batches inputs across co-firing callbacks.
    Rebuild body to contain exactly the items the target callback expects."""
    import flask as _fl
    if _fl.request.path != '/_dash-update-component' or _fl.request.method != 'POST':
        return
    body = _fl.request.get_json(silent=True)
    if not body:
        return
    cb = app.callback_map.get(body.get('output', ''))
    if not cb:
        return
    # Single lookup from ALL sent items (client may put states in inputs or vice versa)
    all_sent = {}
    for i in body.get('inputs', []):
        all_sent[(i['id'], i['property'])] = i
    for s in body.get('state', []):
        all_sent[(s['id'], s['property'])] = s
    # Rebuild in callback-definition order; pad missing items so length always matches indices
    body['inputs'] = [
        all_sent.get((d['id'], d['property']),
                     {'id': d['id'], 'property': d['property'], 'value': None})
        for d in cb['inputs']
    ]
    body['state'] = [
        all_sent.get((d['id'], d['property']),
                     {'id': d['id'], 'property': d['property'], 'value': None})
        for d in cb['state']
    ]

card_style = {
    "backgroundColor": CARD_BG,
    "border": f"1px solid {BORDER}",
    "borderRadius": "10px",
    "padding": "18px 24px",
    "flex": "1",
    "margin": "0 8px",
    "textAlign": "center",
}
kpi_value_style = {"fontSize": "28px", "fontWeight": "700", "margin": "0",
                   "fontFamily": "JetBrains Mono, monospace"}
kpi_label_style = {"fontSize": "11px", "color": TEXT_DIM, "margin": "6px 0 0 0",
                   "textTransform": "uppercase", "letterSpacing": "1px"}


def kpi_card(value, label, color):
    return html.Div([
        html.P(value, style={**kpi_value_style, "color": color}),
        html.P(label, style=kpi_label_style),
    ], style=card_style)


page_style = {
    "backgroundColor": BG,
    "minHeight": "100vh",
    "fontFamily": "JetBrains Mono, monospace",
    "color": TEXT,
}

gforce_label_style = {
    "textAlign": "center", "color": TEXT_DIM, "fontSize": "11px",
    "letterSpacing": "2px", "margin": "10px 0 0 0",
    "fontFamily": "JetBrains Mono, monospace",
}

# ---------------------------------------------------------------------------
# Layout — CSV mode (static)
# ---------------------------------------------------------------------------
if not live_mode:
    df = _add_gforce_cols(df)
    t = df["time_s"].values
    duration_s = df["time_s"].max() - df["time_s"].min()
    max_rpm = df["omega_deg_s"].abs().max() / 360 * 60
    total_ticks = df["turn_counts"].abs().sum()
    peak_g = df["g_resultant"].max()
    n_samples = len(df)

    has_ctrl = "throttle_us" in df.columns and "steer_deg" in df.columns
    ts_fig = build_timeseries_fig(df, has_control_cols=has_ctrl)
    gf_fig = build_gforce_fig(df) if SHOW_GFORCE else None

    app.layout = html.Div([
        html.Div([
            html.H1("JST Racing Telemetry", style={
                "margin": "0", "fontSize": "22px", "fontWeight": "700", "color": TEXT,
                "fontFamily": "JetBrains Mono, monospace",
            }),
            html.P(f"{filename}  ·  {duration_s:.1f}s  ·  {n_samples} samples", style={
                "margin": "4px 0 0 0", "fontSize": "12px", "color": TEXT_DIM,
                "fontFamily": "JetBrains Mono, monospace",
            }),
        ], style={"padding": "20px 28px 10px 28px"}),

        html.Div([
            kpi_card(f"{max_rpm:.0f}", "Max Wheel RPM", RED),
            kpi_card(f"{total_ticks:,}", "Encoder Ticks", CYAN),
            kpi_card(f"{duration_s:.1f}s", "Run Duration", GOLD),
            kpi_card(f"{peak_g:.2f} G", "Peak G-Force", TEXT),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "0px"}),

        html.Div([
            html.Div([
                dcc.Graph(figure=ts_fig, config={"displayModeBar": True, "scrollZoom": True}),
            ], style={"flex": "3"}),
        ] + ([html.Div([
                html.P("G-FORCE MAP", style=gforce_label_style),
                dcc.Graph(figure=gf_fig, config={"displayModeBar": False}),
            ], style={"flex": "1", "minWidth": "320px"}),
        ] if SHOW_GFORCE else []), style={"display": "flex", "padding": "0 20px", "gap": "8px"}),
    ], style=page_style)

# ---------------------------------------------------------------------------
# Layout — Live mode (dynamic callbacks)
# ---------------------------------------------------------------------------
else:
    tele_buffer = TelemetryBuffer(window_s=LIVE_WINDOW_SECONDS)
    threading.Thread(target=udp_receiver, args=(tele_buffer,), daemon=True).start()
    print(f"LIVE MODE — Listening for telemetry on UDP port {UDP_RELAY_PORT} (relayed from py_udp.py)")

    # Camera threads
    cam_buffer = None
    if SHOW_CAMERA:
        cam_buffer = CameraBuffer()

        def _cam_receiver():
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

        def _cam_quality_sender():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            while True:
                q = max(1, min(63, cam_buffer.quality))
                sock.sendto(bytes([q]), (CAM_IP, CAM_CMD_PORT))
                time.sleep(CAM_QUALITY_RESEND)

        threading.Thread(target=_cam_receiver, daemon=True).start()
        threading.Thread(target=_cam_quality_sender, daemon=True).start()
        print(f"CAMERA — Streaming from {CAM_IP} cmd:{CAM_CMD_PORT} stream:{CAM_STREAM_PORT}")

    app.layout = html.Div([
        # Header with LIVE badge
        html.Div([
            html.H1("JST Racing Telemetry", style={
                "margin": "0", "fontSize": "22px", "fontWeight": "700", "color": TEXT,
                "fontFamily": "JetBrains Mono, monospace",
            }),
            html.Span("LIVE", style={
                "backgroundColor": RED, "color": "white", "padding": "2px 10px",
                "borderRadius": "4px", "fontSize": "12px", "marginLeft": "12px",
                "fontWeight": "700", "fontFamily": "JetBrains Mono, monospace",
            }),
            html.Div([
                html.Span("Window:", style={
                    "fontSize": "11px", "color": TEXT_DIM, "marginRight": "10px",
                    "fontFamily": "JetBrains Mono, monospace",
                }),
                dcc.RadioItems(
                    id="window-selector",
                    options=[
                        {"label": "10s", "value": 10},
                        {"label": "30s", "value": 30},
                        {"label": "1m", "value": 60},
                        {"label": "2m", "value": 120},
                        {"label": "5m", "value": 300},
                        {"label": "10m", "value": 600},
                    ],
                    value=60,
                    inline=True,
                    inputStyle={"display": "none"},
                    labelStyle={
                        "display": "inline-block",
                        "padding": "4px 10px",
                        "margin": "0 3px",
                        "borderRadius": "4px",
                        "fontSize": "11px",
                        "color": TEXT_DIM,
                        "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "cursor": "pointer",
                        "fontFamily": "JetBrains Mono, monospace",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "marginLeft": "auto"}),
        ], style={"padding": "20px 28px 10px 28px", "display": "flex", "alignItems": "center"}),

        # KPI cards (updated by callback)
        html.Div(id="kpi-container", children=[
            kpi_card("--", "Max Wheel RPM", TEXT_DIM),
            kpi_card("--", "Samples", TEXT_DIM),
            kpi_card("--", "Window", TEXT_DIM),
            kpi_card("--", "Peak G-Force", TEXT_DIM),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "0px"}),

        # Graphs
        html.Div([
            html.Div([
                dcc.Graph(id="timeseries-graph", figure=empty_figure(1100),
                          config={"displayModeBar": True, "scrollZoom": True}),
            ], style={"flex": "3"}),
            html.Div(
                ([
                    html.P("CAMERA", style=gforce_label_style),
                    html.Img(id="camera-feed", style={
                        "width": "100%", "borderRadius": "8px",
                        "border": f"1px solid {BORDER}", "display": "block",
                    }),
                    dcc.Slider(
                        id="cam-quality-slider", min=1, max=63, value=CAM_QUALITY, step=1,
                        marks={1: "1 (best)", 32: "32", 63: "63 (fast)"},
                        tooltip={"placement": "bottom"},
                    ),
                ] if SHOW_CAMERA else []) + [
                    html.P("STEERING", style=gforce_label_style),
                    dcc.Graph(id="steering-wheel", figure=build_steering_wheel_fig(100),
                              config={"displayModeBar": False, "staticPlot": True}),
                ] + ([
                    html.P("G-FORCE MAP", style=gforce_label_style),
                    dcc.Graph(id="gforce-graph", figure=empty_figure(450),
                              config={"displayModeBar": False}),
                ] if SHOW_GFORCE else []),
                style={"flex": "1", "minWidth": "320px"},
            ),
        ], style={"display": "flex", "padding": "0 20px", "gap": "8px"}),

        dcc.Interval(id="live-interval", interval=LIVE_UPDATE_MS, n_intervals=0),
    ], style=page_style)

    # -- Callbacks ----

    @app.callback(
        Output("timeseries-graph", "figure"),
        Input("live-interval", "n_intervals"),
        State("window-selector", "value"),
    )
    def update_timeseries(_n, window_s):
        tele_buffer.window_s = window_s
        snap = tele_buffer.snapshot()
        if snap.empty:
            return empty_figure(900)
        has_ctrl = "throttle_us" in snap.columns and "steer_deg" in snap.columns
        return build_timeseries_fig(snap, has_control_cols=has_ctrl)

    if SHOW_GFORCE:
        @app.callback(
            Output("gforce-graph", "figure"),
            Input("live-interval", "n_intervals"),
        )
        def update_gforce(_n):
            snap = tele_buffer.snapshot()
            if snap.empty:
                return empty_figure(450)
            return build_gforce_fig(snap)

    @app.callback(
        Output("steering-wheel", "figure"),
        Input("live-interval", "n_intervals"),
    )
    def update_steering(_n):
        snap = tele_buffer.snapshot()
        if snap.empty or "steer_deg" not in snap.columns:
            return build_steering_wheel_fig(100)
        return build_steering_wheel_fig(int(snap["steer_deg"].iloc[-1]))

    @app.callback(
        Output("kpi-container", "children"),
        Input("live-interval", "n_intervals"),
    )
    def update_kpis(_n):
        snap = tele_buffer.snapshot()
        if snap.empty:
            return [
                kpi_card("--", "Max Wheel RPM", TEXT_DIM),
                kpi_card("--", "Samples", TEXT_DIM),
                kpi_card("--", "Window", TEXT_DIM),
                kpi_card("--", "Peak G-Force", TEXT_DIM),
            ]
        duration = snap["time_s"].max() - snap["time_s"].min()
        max_rpm = snap["omega_deg_s"].abs().max() / 360 * 60
        snap = _add_gforce_cols(snap)
        peak_g = snap["g_resultant"].max()
        return [
            kpi_card(f"{max_rpm:.0f}", "Max Wheel RPM", RED),
            kpi_card(f"{len(snap)}", "Samples", CYAN),
            kpi_card(f"{duration:.1f}s", "Window", GOLD),
            kpi_card(f"{peak_g:.2f} G", "Peak G-Force", TEXT),
        ]

    if SHOW_CAMERA:
        @app.callback(
            Output("camera-feed", "src"),
            Input("live-interval", "n_intervals"),
            State("cam-quality-slider", "value"),
            prevent_initial_call=True,
        )
        def update_camera(_n, quality):
            if quality is not None:
                cam_buffer.quality = max(1, min(63, quality))
            jpeg = cam_buffer.get_latest()
            if jpeg is None:
                return ""
            return f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}"

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Dashboard ready → http://localhost:8050")
    app.run(debug=False, port=8050)
