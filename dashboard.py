#!/usr/bin/env python3
"""JST Racing Telemetry Dashboard — browser-based viewer for log CSV files or live UDP telemetry."""

import sys
import glob
import os
import time
import struct
import socket
import threading
from collections import deque

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, html, dcc, Output, Input

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UDP_TELE_PORT = 5006
TELE_FMT = '<ffffffffi'
TELE_SIZE = struct.calcsize(TELE_FMT)  # 36
LIVE_WINDOW_SECONDS = 60
LIVE_UPDATE_MS = 200

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
    def __init__(self, max_entries=1500):
        self._lock = threading.Lock()
        self._buf = deque(maxlen=max_entries)
        self._t0 = None

    def append(self, vals):
        with self._lock:
            now = time.time()
            if self._t0 is None:
                self._t0 = now
            self._buf.append({
                "time_s": round(now - self._t0, 4),
                "ax": vals[0], "ay": vals[1], "az": vals[2],
                "gx": vals[3], "gy": vals[4], "gz": vals[5],
                "angle_deg": vals[6], "omega_deg_s": vals[7], "turn_counts": vals[8],
            })

    def snapshot(self):
        with self._lock:
            if not self._buf:
                return pd.DataFrame()
            return pd.DataFrame(list(self._buf))


def udp_receiver(buf):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", UDP_TELE_PORT))
    sock.settimeout(1.0)
    while True:
        try:
            data, _ = sock.recvfrom(256)
            if len(data) == TELE_SIZE:
                buf.append(struct.unpack(TELE_FMT, data))
        except socket.timeout:
            pass
        except Exception:
            pass


tele_buffer = None

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
    gf_fig = build_gforce_fig(df)

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
            html.Div([
                html.P("G-FORCE MAP", style=gforce_label_style),
                dcc.Graph(figure=gf_fig, config={"displayModeBar": False}),
            ], style={"flex": "1", "minWidth": "320px"}),
        ], style={"display": "flex", "padding": "0 20px", "gap": "8px"}),
    ], style=page_style)

# ---------------------------------------------------------------------------
# Layout — Live mode (dynamic callbacks)
# ---------------------------------------------------------------------------
else:
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
                dcc.Graph(id="timeseries-graph", figure=empty_figure(900),
                          config={"displayModeBar": True, "scrollZoom": True}),
            ], style={"flex": "3"}),
            html.Div([
                html.P("G-FORCE MAP", style=gforce_label_style),
                dcc.Graph(id="gforce-graph", figure=empty_figure(450),
                          config={"displayModeBar": False}),
            ], style={"flex": "1", "minWidth": "320px"}),
        ], style={"display": "flex", "padding": "0 20px", "gap": "8px"}),

        # Interval timer
        dcc.Interval(id="live-interval", interval=LIVE_UPDATE_MS, n_intervals=0),
    ], style=page_style)

    # -- Callbacks ----------------------------------------------------------

    @app.callback(
        Output("timeseries-graph", "figure"),
        Input("live-interval", "n_intervals"),
    )
    def update_timeseries(_n):
        snap = tele_buffer.snapshot()
        if snap.empty:
            return empty_figure(900)
        return build_timeseries_fig(snap, has_control_cols=False)

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

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if live_mode:
        tele_buffer = TelemetryBuffer(max_entries=LIVE_WINDOW_SECONDS * 25)
        t = threading.Thread(target=udp_receiver, args=(tele_buffer,), daemon=True)
        t.start()
        print(f"LIVE MODE — Listening for telemetry on UDP port {UDP_TELE_PORT}")
    print(f"Dashboard ready → http://localhost:8050")
    app.run(debug=False, port=8050)
