"""Plotly figure builders for both modes."""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .constants import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, PLOT_BG, GRID,
    RED, CYAN, GOLD, GREEN, MAGENTA, ORANGE, BLUE,
    LAYOUT_COMMON,
)
from .metrics import add_gforce_cols


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def empty_figure(height, message="Waiting for telemetry..."):
    fig = go.Figure()
    fig.update_layout(
        **LAYOUT_COMMON,
        height=height,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                showarrow=False,
                font=dict(size=20, color=TEXT_DIM),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )
        ],
    )
    return fig


# ---------------------------------------------------------------------------
# Data Team Mode — time-series
# ---------------------------------------------------------------------------

def build_timeseries_fig(dataframe, has_control_cols=True):
    """Build the main time-series subplot figure."""
    t = dataframe["time_s"].values

    if has_control_cols:
        row_titles = [
            "Throttle (us)", "Steering (deg)",
            "Accelerometer (m/s2)", "Gyroscope (rad/s)",
            "Wheel w (deg/s)", "Turn Counts",
        ]
        n_rows = 6
        row_heights = [1, 1, 1.5, 1.5, 1, 1]
    else:
        row_titles = [
            "Accelerometer (m/s2)", "Gyroscope (rad/s)",
            "Wheel w (deg/s)", "Turn Counts",
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

    r = 1
    if has_control_cols:
        fig.add_trace(go.Scatter(
            x=t, y=dataframe["throttle_us"], mode="lines", name="Throttle",
            fill="tozeroy", fillcolor="rgba(255,68,68,0.15)",
            line=dict(color=RED, width=1.5),
        ), row=r, col=1)
        fig.add_hline(y=1500, line_dash="dot", line_color=TEXT_DIM, opacity=0.5, row=r, col=1)
        r += 1

        fig.add_trace(go.Scatter(
            x=t, y=dataframe["steer_deg"], mode="lines", name="Steering",
            line=dict(color=CYAN, width=1.5),
        ), row=r, col=1)
        for ref_y in [75, 100, 125]:
            fig.add_hline(y=ref_y, line_dash="dot", line_color=TEXT_DIM, opacity=0.3, row=r, col=1)
        r += 1

    for col_name, color, label in [("ax", RED, "ax"), ("ay", GREEN, "ay"), ("az", BLUE, "az")]:
        fig.add_trace(go.Scatter(
            x=t, y=dataframe[col_name], mode="lines", name=label,
            line=dict(color=color, width=1),
        ), row=r, col=1)
    r += 1

    for col_name, color, label in [("gx", RED, "gx"), ("gy", GREEN, "gy"), ("gz", BLUE, "gz")]:
        fig.add_trace(go.Scatter(
            x=t, y=dataframe[col_name], mode="lines", name=label,
            line=dict(color=color, width=1),
        ), row=r, col=1)
    r += 1

    fig.add_trace(go.Scatter(
        x=t, y=dataframe["omega_deg_s"], mode="lines", name="w",
        line=dict(color=GOLD, width=1.5),
    ), row=r, col=1)
    r += 1

    fig.add_trace(go.Scatter(
        x=t, y=dataframe["turn_counts"], mode="markers", name="Turns",
        marker=dict(color=MAGENTA, size=3),
    ), row=r, col=1)

    fig.update_layout(
        **LAYOUT_COMMON,
        height=900 if not has_control_cols else 1100,
        margin=dict(l=60, r=20, t=30, b=40),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
            font=dict(size=10),
        ),
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


# ---------------------------------------------------------------------------
# Data Team Mode — G-force scatter
# ---------------------------------------------------------------------------

def build_gforce_fig(dataframe):
    """Build the G-force scatter figure."""
    dataframe = add_gforce_cols(dataframe.copy())
    valid = dataframe.dropna(subset=["g_lateral", "g_longitudinal"])

    theta = np.linspace(0, 2 * np.pi, 100)
    gfig = go.Figure()
    for radius in [0.05, 0.1, 0.15]:
        gfig.add_trace(go.Scatter(
            x=radius * np.cos(theta), y=radius * np.sin(theta),
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
        max_g_range = max(
            0.2, valid["g_lateral"].abs().max(), valid["g_longitudinal"].abs().max()
        ) * 1.2
    else:
        max_g_range = 0.2

    gfig.update_layout(
        **LAYOUT_COMMON,
        height=450,
        margin=dict(l=50, r=20, t=30, b=50),
        xaxis=dict(
            title="Lateral G", gridcolor=GRID,
            range=[-max_g_range, max_g_range],
            scaleanchor="y", scaleratio=1,
            zeroline=True, zerolinecolor=BORDER,
        ),
        yaxis=dict(
            title="Longitudinal G", gridcolor=GRID,
            range=[-max_g_range, max_g_range],
            zeroline=True, zerolinecolor=BORDER,
        ),
        showlegend=False,
        uirevision="constant",
    )
    return gfig


# ---------------------------------------------------------------------------
# Steering wheel (shared between modes)
# ---------------------------------------------------------------------------

def build_steering_wheel_fig(steer_deg=100, height=320):
    """Steering wheel visualization. steer_deg: 75 (left) – 100 (center) – 125 (right)."""
    rotation_deg = (steer_deg - 100) / 25 * 90
    angle_rad = np.radians(-rotation_deg)

    fig = go.Figure()

    theta = np.linspace(0, 2 * np.pi, 120)
    rim_r = 1.0
    fig.add_trace(go.Scatter(
        x=rim_r * np.cos(theta), y=rim_r * np.sin(theta),
        mode="lines", line=dict(color=CYAN, width=4),
        showlegend=False, hoverinfo="skip",
    ))

    spoke_len = 0.75
    for base_angle in [np.pi / 2, np.pi / 2 + 2 * np.pi / 3, np.pi / 2 + 4 * np.pi / 3]:
        a = base_angle + angle_rad
        fig.add_trace(go.Scatter(
            x=[0, spoke_len * np.cos(a)], y=[0, spoke_len * np.sin(a)],
            mode="lines", line=dict(color=TEXT, width=3),
            showlegend=False, hoverinfo="skip",
        ))

    hub_theta = np.linspace(0, 2 * np.pi, 60)
    hub_r = 0.18
    fig.add_trace(go.Scatter(
        x=hub_r * np.cos(hub_theta), y=hub_r * np.sin(hub_theta),
        mode="lines", fill="toself", fillcolor=CARD_BG,
        line=dict(color=TEXT, width=2),
        showlegend=False, hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=[0], y=[1.2],
        mode="markers", marker=dict(symbol="triangle-down", size=14, color=RED),
        showlegend=False, hoverinfo="skip",
    ))

    if rotation_deg < -2:
        direction, dir_color = "LEFT", CYAN
    elif rotation_deg > 2:
        direction, dir_color = "RIGHT", ORANGE
    else:
        direction, dir_color = "CENTER", GREEN

    fig.update_layout(
        **LAYOUT_COMMON,
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-1.5, 1.5], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-1.5, 1.5]),
        showlegend=False,
        annotations=[
            dict(
                text=f"{steer_deg:.0f} deg",
                x=0, y=0, showarrow=False,
                font=dict(size=16, color=TEXT, family="JetBrains Mono, monospace"),
            ),
            dict(
                text=direction, x=0, y=-1.35, showarrow=False,
                font=dict(
                    size=13, color=dir_color,
                    family="JetBrains Mono, monospace",
                ),
            ),
        ],
        uirevision="constant",
    )
    return fig


# ---------------------------------------------------------------------------
# Driver Mode — throttle gauge
# ---------------------------------------------------------------------------

def build_throttle_gauge(throttle_us=1500):
    """Arc gauge: throttle_us 1500 (0%) to 2000 (100%)."""
    pct = max(0, min(100, (throttle_us - 1500) / 500 * 100))
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        number=dict(suffix="%", font=dict(size=28, color=TEXT, family="JetBrains Mono")),
        gauge=dict(
            axis=dict(
                range=[0, 100], tickcolor=TEXT_DIM, dtick=20,
                tickfont=dict(size=10, color=TEXT_DIM),
            ),
            bar=dict(color=RED),
            bgcolor=CARD_BG,
            bordercolor=BORDER,
            steps=[
                dict(range=[0, 60], color="#1a1e24"),
                dict(range=[60, 80], color="#2a1a10"),
                dict(range=[80, 100], color="#3a1010"),
            ],
            threshold=dict(line=dict(color=GOLD, width=2), thickness=0.8, value=80),
        ),
        title=dict(text="THROTTLE", font=dict(size=11, color=TEXT_DIM)),
    ))
    fig.update_layout(**LAYOUT_COMMON, height=220, margin=dict(l=30, r=30, t=40, b=10))
    return fig


# ---------------------------------------------------------------------------
# Driver Mode — speed display
# ---------------------------------------------------------------------------

def build_speed_figure(speed_kph=0):
    """Large speed number display."""
    fig = go.Figure(go.Indicator(
        mode="number",
        value=speed_kph,
        number=dict(
            suffix=" km/h",
            font=dict(size=48, color=CYAN, family="JetBrains Mono"),
            valueformat=".1f",
        ),
        title=dict(text="SPEED", font=dict(size=11, color=TEXT_DIM)),
    ))
    fig.update_layout(**LAYOUT_COMMON, height=120, margin=dict(l=10, r=10, t=40, b=10))
    return fig


# ---------------------------------------------------------------------------
# Driver Mode — G-force circle (compact, with trail)
# ---------------------------------------------------------------------------

def build_gforce_circle(dataframe, max_samples=40):
    """Compact G-force circle with fading trail for Driver Mode."""
    dataframe = add_gforce_cols(dataframe.copy())
    valid = dataframe.dropna(subset=["g_lateral", "g_longitudinal"])

    theta = np.linspace(0, 2 * np.pi, 80)
    fig = go.Figure()
    for radius in [0.05, 0.1, 0.15]:
        fig.add_trace(go.Scatter(
            x=radius * np.cos(theta), y=radius * np.sin(theta),
            mode="lines", line=dict(color=BORDER, width=1, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

    # Crosshairs
    fig.add_trace(go.Scatter(
        x=[-0.2, 0.2], y=[0, 0], mode="lines",
        line=dict(color=BORDER, width=1), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=[0, 0], y=[-0.2, 0.2], mode="lines",
        line=dict(color=BORDER, width=1), showlegend=False, hoverinfo="skip",
    ))

    if not valid.empty:
        tail = valid.tail(max_samples)
        n = len(tail)
        if n > 1:
            opacities = np.linspace(0.1, 0.6, n - 1).tolist()
            fig.add_trace(go.Scatter(
                x=tail["g_lateral"].values[:-1],
                y=tail["g_longitudinal"].values[:-1],
                mode="markers",
                marker=dict(size=4, color=RED, opacity=opacities),
                showlegend=False, hoverinfo="skip",
            ))
        fig.add_trace(go.Scatter(
            x=[tail["g_lateral"].iloc[-1]],
            y=[tail["g_longitudinal"].iloc[-1]],
            mode="markers",
            marker=dict(size=12, color=RED, line=dict(color="white", width=2)),
            showlegend=False, hoverinfo="skip",
        ))

    fig.update_layout(
        **LAYOUT_COMMON,
        height=280,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-0.22, 0.22], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-0.22, 0.22]),
        showlegend=False,
        uirevision="constant",
    )
    return fig


# ---------------------------------------------------------------------------
# Driver Mode — mini telemetry strip
# ---------------------------------------------------------------------------

def build_mini_strip(dataframe, window_s=10):
    """Compact scrolling throttle + steer traces for Driver Mode footer."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[1, 1],
    )

    if not dataframe.empty:
        t = dataframe["time_s"].values
        t_max = t[-1] if len(t) else 0
        mask = t >= (t_max - window_s)
        df_win = dataframe[mask]
        tw = df_win["time_s"].values
        if "throttle_us" in df_win.columns:
            fig.add_trace(go.Scatter(
                x=tw, y=df_win["throttle_us"], mode="lines",
                line=dict(color=RED, width=1.5), name="Throttle",
                fill="tozeroy", fillcolor="rgba(255,68,68,0.1)",
            ), row=1, col=1)
        if "steer_deg" in df_win.columns:
            fig.add_trace(go.Scatter(
                x=tw, y=df_win["steer_deg"], mode="lines",
                line=dict(color=CYAN, width=1.5), name="Steering",
            ), row=2, col=1)

    fig.update_layout(
        **LAYOUT_COMMON,
        height=160,
        margin=dict(l=50, r=10, t=5, b=20),
        showlegend=False,
        uirevision="constant",
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showgrid=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showgrid=False)
    fig.update_yaxes(title_text="THR", title_font=dict(size=9, color=TEXT_DIM), row=1, col=1)
    fig.update_yaxes(title_text="STR", title_font=dict(size=9, color=TEXT_DIM), row=2, col=1)
    return fig


# ---------------------------------------------------------------------------
# Data Team Mode — FFT
# ---------------------------------------------------------------------------

def build_fft_fig(freqs, magnitudes, channel_name=""):
    """Frequency spectrum plot."""
    fig = go.Figure()
    if len(freqs) > 0:
        fig.add_trace(go.Bar(
            x=freqs, y=magnitudes,
            marker_color=CYAN, opacity=0.8, name="FFT",
        ))
    fig.update_layout(
        **LAYOUT_COMMON,
        height=350,
        margin=dict(l=50, r=20, t=30, b=40),
        xaxis=dict(title="Frequency (Hz)", gridcolor=GRID),
        yaxis=dict(title="Magnitude", gridcolor=GRID),
        title=dict(
            text=f"FFT — {channel_name}" if channel_name else "FFT",
            font=dict(size=12, color=TEXT_DIM),
        ),
        showlegend=False,
        uirevision="fft",
    )
    return fig


# ---------------------------------------------------------------------------
# Data Team Mode — correlation scatter
# ---------------------------------------------------------------------------

def build_correlation_fig(x, y, xlabel, ylabel, title=""):
    """Scatter plot for correlation analysis."""
    fig = go.Figure()
    if len(x) > 0:
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="markers",
            marker=dict(size=4, color=CYAN, opacity=0.5),
        ))
    fig.update_layout(
        **LAYOUT_COMMON,
        height=350,
        margin=dict(l=50, r=20, t=30, b=40),
        xaxis=dict(title=xlabel, gridcolor=GRID),
        yaxis=dict(title=ylabel, gridcolor=GRID),
        title=dict(text=title, font=dict(size=12, color=TEXT_DIM)),
        showlegend=False,
        uirevision="corr",
    )
    return fig
