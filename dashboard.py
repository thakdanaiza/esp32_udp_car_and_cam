#!/usr/bin/env python3
"""JST Racing Telemetry Dashboard — interactive browser-based viewer for log CSV files."""

import sys
import glob
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, html, dcc

# ---------------------------------------------------------------------------
# 1. Load CSV
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    csv_path = sys.argv[1]
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = sorted(glob.glob(os.path.join(script_dir, "log_*.csv")))
    if not candidates:
        print("Usage: python dashboard.py [path/to/log.csv]")
        print("No log_*.csv found in script directory.")
        sys.exit(1)
    csv_path = candidates[-1]

print(f"Loading {csv_path} ...")
df = pd.read_csv(csv_path)
filename = os.path.basename(csv_path)

# ---------------------------------------------------------------------------
# 2. Derived metrics
# ---------------------------------------------------------------------------
t = df["time_s"].values

# Insert NaN rows at time gaps > 0.5s to break plotly lines
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
    t = df["time_s"].values

# Gravity correction (subtract mean — fixed-mount IMU tilt)
ax_mean, ay_mean, az_mean = df[["ax", "ay", "az"]].mean()
df["ax_corr"] = df["ax"] - ax_mean
df["ay_corr"] = df["ay"] - ay_mean
df["az_corr"] = df["az"] - az_mean

# G-force (corrected)
df["g_lateral"] = df["ax_corr"] / 9.81
df["g_longitudinal"] = df["ay_corr"] / 9.81
df["g_resultant"] = np.sqrt(df["ax_corr"]**2 + df["ay_corr"]**2 + df["az_corr"]**2) / 9.81

# ---------------------------------------------------------------------------
# 3. KPIs
# ---------------------------------------------------------------------------
duration_s = df["time_s"].max() - df["time_s"].min()
max_rpm = df["omega_deg_s"].abs().max() / 360 * 60
total_ticks = df["turn_counts"].abs().sum()
peak_g = df["g_resultant"].max()
n_samples = len(df)

# ---------------------------------------------------------------------------
# 4. Color palette
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
# 5. Main time-series figure (6 rows, shared x-axis)
# ---------------------------------------------------------------------------
row_titles = [
    "Throttle (µs)", "Steering (deg)",
    "Accelerometer (m/s²)", "Gyroscope (rad/s)",
    "Wheel ω (deg/s)", "Turn Counts",
]

fig = make_subplots(
    rows=6, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=[1, 1, 1.5, 1.5, 1, 1],
    subplot_titles=row_titles,
)

# Row 1: Throttle
fig.add_trace(go.Scatter(
    x=t, y=df["throttle_us"], mode="lines", name="Throttle",
    fill="tozeroy", fillcolor="rgba(255,68,68,0.15)",
    line=dict(color=RED, width=1.5),
), row=1, col=1)
fig.add_hline(y=1500, line_dash="dot", line_color=TEXT_DIM, opacity=0.5, row=1, col=1)

# Row 2: Steering
fig.add_trace(go.Scatter(
    x=t, y=df["steer_deg"], mode="lines", name="Steering",
    line=dict(color=CYAN, width=1.5),
), row=2, col=1)
for ref_y in [75, 100, 125]:
    fig.add_hline(y=ref_y, line_dash="dot", line_color=TEXT_DIM, opacity=0.3, row=2, col=1)

# Row 3: Accelerometer
for col_name, color, label in [("ax", RED, "ax"), ("ay", GREEN, "ay"), ("az", BLUE, "az")]:
    fig.add_trace(go.Scatter(
        x=t, y=df[col_name], mode="lines", name=label,
        line=dict(color=color, width=1),
    ), row=3, col=1)

# Row 4: Gyroscope
for col_name, color, label in [("gx", RED, "gx"), ("gy", GREEN, "gy"), ("gz", BLUE, "gz")]:
    fig.add_trace(go.Scatter(
        x=t, y=df[col_name], mode="lines", name=label,
        line=dict(color=color, width=1),
    ), row=4, col=1)

# Row 5: Omega
fig.add_trace(go.Scatter(
    x=t, y=df["omega_deg_s"], mode="lines", name="ω",
    line=dict(color=GOLD, width=1.5),
), row=5, col=1)

# Row 6: Turn counts
fig.add_trace(go.Scatter(
    x=t, y=df["turn_counts"], mode="markers", name="Turns",
    marker=dict(color=MAGENTA, size=3),
), row=6, col=1)

# Style the whole figure
fig.update_layout(
    height=1100,
    template="plotly_dark",
    paper_bgcolor=BG,
    plot_bgcolor=PLOT_BG,
    font=dict(family="JetBrains Mono, monospace", color=TEXT, size=11),
    margin=dict(l=60, r=20, t=30, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                font=dict(size=10)),
    hovermode="x unified",
)
fig.update_xaxes(
    gridcolor=GRID, zeroline=False, showgrid=True,
    title_text="Time (s)", row=6, col=1,
)
for i in range(1, 7):
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showgrid=True, row=i, col=1)

# Annotation style for subplot titles
for ann in fig.layout.annotations:
    ann.update(font=dict(size=11, color=TEXT_DIM), xanchor="left", x=0.01)

# ---------------------------------------------------------------------------
# 6. G-Force scatter
# ---------------------------------------------------------------------------
# Concentric circles
theta = np.linspace(0, 2 * np.pi, 100)
gforce_fig = go.Figure()
for r in [0.05, 0.1, 0.15]:
    gforce_fig.add_trace(go.Scatter(
        x=r * np.cos(theta), y=r * np.sin(theta),
        mode="lines", line=dict(color=BORDER, width=1, dash="dot"),
        showlegend=False, hoverinfo="skip",
    ))

# Data points colored by time
valid = df.dropna(subset=["g_lateral", "g_longitudinal"])
gforce_fig.add_trace(go.Scatter(
    x=valid["g_lateral"], y=valid["g_longitudinal"],
    mode="markers",
    marker=dict(
        size=5,
        color=valid["time_s"],
        colorscale="Hot",
        colorbar=dict(title="Time (s)", thickness=12, len=0.8),
        opacity=0.8,
    ),
    name="G-Force",
    hovertemplate="Lat: %{x:.3f}G<br>Long: %{y:.3f}G<extra></extra>",
))

max_g_range = max(0.2, valid["g_lateral"].abs().max(), valid["g_longitudinal"].abs().max()) * 1.2
gforce_fig.update_layout(
    template="plotly_dark",
    paper_bgcolor=BG,
    plot_bgcolor=PLOT_BG,
    font=dict(family="JetBrains Mono, monospace", color=TEXT, size=11),
    height=450,
    margin=dict(l=50, r=20, t=30, b=50),
    xaxis=dict(title="Lateral G", gridcolor=GRID, range=[-max_g_range, max_g_range],
               scaleanchor="y", scaleratio=1, zeroline=True, zerolinecolor=BORDER),
    yaxis=dict(title="Longitudinal G", gridcolor=GRID, range=[-max_g_range, max_g_range],
               zeroline=True, zerolinecolor=BORDER),
    showlegend=False,
)

# ---------------------------------------------------------------------------
# 7. Dash layout
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
kpi_value_style = {"fontSize": "28px", "fontWeight": "700", "margin": "0", "fontFamily": "JetBrains Mono, monospace"}
kpi_label_style = {"fontSize": "11px", "color": TEXT_DIM, "margin": "6px 0 0 0", "textTransform": "uppercase",
                   "letterSpacing": "1px"}


def kpi_card(value, label, color):
    return html.Div([
        html.P(value, style={**kpi_value_style, "color": color}),
        html.P(label, style=kpi_label_style),
    ], style=card_style)


app.layout = html.Div([
    # Header
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

    # KPI cards
    html.Div([
        kpi_card(f"{max_rpm:.0f}", "Max Wheel RPM", RED),
        kpi_card(f"{total_ticks:,}", "Encoder Ticks", CYAN),
        kpi_card(f"{duration_s:.1f}s", "Run Duration", GOLD),
        kpi_card(f"{peak_g:.2f} G", "Peak G-Force", TEXT),
    ], style={"display": "flex", "padding": "10px 20px", "gap": "0px"}),

    # Main content: time-series (left) + g-force (right)
    html.Div([
        html.Div([
            dcc.Graph(figure=fig, config={"displayModeBar": True, "scrollZoom": True}),
        ], style={"flex": "3"}),
        html.Div([
            html.P("G-FORCE MAP", style={
                "textAlign": "center", "color": TEXT_DIM, "fontSize": "11px",
                "letterSpacing": "2px", "margin": "10px 0 0 0",
                "fontFamily": "JetBrains Mono, monospace",
            }),
            dcc.Graph(figure=gforce_fig, config={"displayModeBar": False}),
        ], style={"flex": "1", "minWidth": "320px"}),
    ], style={"display": "flex", "padding": "0 20px", "gap": "8px"}),

], style={
    "backgroundColor": BG,
    "minHeight": "100vh",
    "fontFamily": "JetBrains Mono, monospace",
    "color": TEXT,
})

# ---------------------------------------------------------------------------
# 8. Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Dashboard ready → http://localhost:8050")
    app.run(debug=False, port=8050)
