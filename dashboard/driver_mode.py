"""Driver Mode — F1-inspired, glanceable gauges for real-time driving."""

import base64

import pandas as pd
from dash import html, dcc, Output, Input, State, no_update
from dash.exceptions import PreventUpdate

from .constants import (
    BG, CARD_BG, BORDER, TEXT, TEXT_DIM, RED, CYAN, GREEN,
    SHOW_CAMERA, SHOW_GFORCE, LIVE_UPDATE_MS,
)
from .components import gforce_label_style, gear_display, status_led
from .figures import (
    build_speed_figure, build_throttle_gauge,
    build_steering_wheel_fig, build_gforce_circle,
    build_mini_strip, empty_figure,
)
from .metrics import add_gforce_cols, compute_speed_kph


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def create_layout(live_mode, df=None):
    """Return the Driver Mode layout div (always rendered, toggled via display)."""
    show_camera = SHOW_CAMERA and live_mode
    show_slider = not live_mode and df is not None

    # Camera or placeholder
    if show_camera:
        camera_block = html.Div([
            html.P("CAMERA", style=gforce_label_style),
            html.Img(id="drv-camera-feed", style={
                "width": "100%", "borderRadius": "8px",
                "border": f"1px solid {BORDER}", "display": "block",
            }),
            dcc.Slider(
                id="drv-cam-quality", min=1, max=63, value=48, step=1,
                marks={1: "1 (best)", 32: "32", 63: "63 (fast)"},
                tooltip={"placement": "bottom"},
            ),
        ], style={"flex": "3", "minWidth": "320px"})
    else:
        camera_block = html.Div([
            html.Div(
                "No camera in CSV playback" if not live_mode else "Camera disabled",
                style={
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "height": "300px", "border": f"1px solid {BORDER}",
                    "borderRadius": "8px", "color": TEXT_DIM, "fontSize": "14px",
                    "backgroundColor": CARD_BG,
                },
            ),
        ], style={"flex": "3", "minWidth": "320px"})

    # Right-side gauges column
    gauges_col = html.Div([
        html.Div(id="drv-gear-display", children=gear_display(0)),
        dcc.Graph(
            id="drv-speed", figure=build_speed_figure(0),
            config={"displayModeBar": False, "staticPlot": True},
        ),
        dcc.Graph(
            id="drv-throttle-gauge", figure=build_throttle_gauge(1500),
            config={"displayModeBar": False, "staticPlot": True},
        ),
        html.P("STEERING", style=gforce_label_style),
        dcc.Graph(
            id="drv-steering-wheel", figure=build_steering_wheel_fig(100, height=250),
            config={"displayModeBar": False, "staticPlot": True},
        ),
    ] + ([
        html.P("G-FORCE", style=gforce_label_style),
        dcc.Graph(
            id="drv-gforce-circle", figure=empty_figure(280),
            config={"displayModeBar": False, "staticPlot": True},
        ),
    ] if SHOW_GFORCE else []), style={"flex": "2", "minWidth": "280px"})

    # Status bar
    status_bar = html.Div(
        id="drv-status-bar",
        children=[
            status_led("UDP", active=False),
            status_led("0 pkt/s", active=False),
            status_led("CAM", active=False) if show_camera else html.Span(),
        ],
        style={
            "display": "flex", "alignItems": "center",
            "padding": "8px 20px",
            "backgroundColor": CARD_BG, "borderRadius": "6px",
            "margin": "8px 20px",
            "border": f"1px solid {BORDER}",
        },
    )

    # Mini telemetry strip
    mini_strip = dcc.Graph(
        id="drv-mini-strip",
        figure=build_mini_strip(pd.DataFrame()),
        config={"displayModeBar": False, "staticPlot": True},
        style={"margin": "0 20px"},
    )

    # CSV time slider (only in CSV mode)
    slider_block = []
    if show_slider:
        t_min = float(df["time_s"].min())
        t_max = float(df["time_s"].max())
        slider_block = [
            html.Div([
                html.Span("Time:", style={
                    "fontSize": "11px", "color": TEXT_DIM, "marginRight": "10px",
                }),
                dcc.Slider(
                    id="drv-time-slider",
                    min=t_min, max=t_max, value=t_max, step=0.05,
                    marks={t_min: f"{t_min:.1f}s", t_max: f"{t_max:.1f}s"},
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
            ], style={"padding": "8px 20px"}),
        ]
    else:
        # Hidden placeholder so callbacks don't break
        slider_block = [html.Div(
            dcc.Slider(id="drv-time-slider", min=0, max=1, value=0),
            style={"display": "none"},
        )]

    # Hidden dummy elements for callbacks that reference camera
    hidden = []
    if not show_camera:
        hidden.append(html.Img(id="drv-camera-feed", style={"display": "none"}))
        hidden.append(html.Div(
            dcc.Slider(id="drv-cam-quality", min=1, max=63, value=48),
            style={"display": "none"},
        ))
    if not SHOW_GFORCE:
        hidden.append(dcc.Graph(id="drv-gforce-circle", style={"display": "none"}))

    return html.Div(
        [
            # Row 1: Camera + Gauges
            html.Div(
                [camera_block, gauges_col],
                style={"display": "flex", "padding": "10px 20px", "gap": "12px"},
            ),
            # Row 2: Status
            status_bar,
            # Row 3: Mini strip
            mini_strip,
            # Slider (CSV only)
            *slider_block,
            *hidden,
        ],
        id="driver-container",
        style={"display": "none"},
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def register_callbacks(app, live_mode, tele_buffer=None, cam_buffer=None, df=None):
    """Register all Driver Mode callbacks."""

    if live_mode:
        _register_live_callbacks(app, tele_buffer, cam_buffer)
    else:
        _register_csv_callbacks(app, df)


def _register_live_callbacks(app, tele_buffer, cam_buffer):
    """Live-mode driver callbacks: interval-driven."""

    @app.callback(
        [
            Output("drv-gear-display", "children"),
            Output("drv-speed", "figure"),
            Output("drv-throttle-gauge", "figure"),
            Output("drv-steering-wheel", "figure"),
            Output("drv-mini-strip", "figure"),
            Output("drv-status-bar", "children"),
        ] + ([Output("drv-gforce-circle", "figure")] if SHOW_GFORCE else []),
        Input("live-interval", "n_intervals"),
        State("current-mode", "data"),
        prevent_initial_call=True,
    )
    def update_driver_live(_n, mode):
        if mode != "driver":
            raise PreventUpdate

        snap = tele_buffer.snapshot()
        if snap.empty:
            defaults = [
                gear_display(0),
                build_speed_figure(0),
                build_throttle_gauge(1500),
                build_steering_wheel_fig(100, height=250),
                build_mini_strip(pd.DataFrame()),
                [status_led("UDP", active=False), status_led("0 pkt/s", active=False)],
            ]
            if SHOW_GFORCE:
                defaults.append(empty_figure(280))
            return defaults

        # Extract latest values
        last = snap.iloc[-1]
        throttle = last.get("throttle_us", 1500)
        steer = last.get("steer_deg", 100)
        gear = int(last.get("gear", 0)) if "gear" in snap.columns else 0
        omega = last.get("omega_deg_s", 0)
        speed = compute_speed_kph(omega)

        n_samples = len(snap)
        duration = snap["time_s"].max() - snap["time_s"].min()
        pkt_rate = n_samples / max(duration, 0.1)
        udp_active = n_samples > 0

        results = [
            gear_display(gear),
            build_speed_figure(speed),
            build_throttle_gauge(throttle),
            build_steering_wheel_fig(steer, height=250),
            build_mini_strip(snap, window_s=10),
            [
                status_led("UDP", active=udp_active),
                status_led(f"{pkt_rate:.0f} pkt/s", active=pkt_rate > 5),
            ],
        ]
        if SHOW_GFORCE:
            results.append(build_gforce_circle(snap, max_samples=40))
        return results

    # Camera feed
    if SHOW_CAMERA and cam_buffer is not None:
        @app.callback(
            Output("drv-camera-feed", "src"),
            Input("live-interval", "n_intervals"),
            State("current-mode", "data"),
            State("drv-cam-quality", "value"),
            prevent_initial_call=True,
        )
        def update_driver_camera(_n, mode, quality):
            if mode != "driver":
                raise PreventUpdate
            if quality is not None:
                cam_buffer.quality = max(1, min(63, quality))
            jpeg = cam_buffer.get_latest()
            if jpeg is None:
                return ""
            return f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}"


def _register_csv_callbacks(app, df):
    """CSV-mode driver callbacks: slider-driven."""
    if df is None or df.empty:
        return

    @app.callback(
        [
            Output("drv-gear-display", "children"),
            Output("drv-speed", "figure"),
            Output("drv-throttle-gauge", "figure"),
            Output("drv-steering-wheel", "figure"),
            Output("drv-mini-strip", "figure"),
            Output("drv-status-bar", "children"),
        ] + ([Output("drv-gforce-circle", "figure")] if SHOW_GFORCE else []),
        Input("drv-time-slider", "value"),
        State("current-mode", "data"),
    )
    def update_driver_csv(slider_val, mode):
        if mode != "driver":
            raise PreventUpdate

        # Find closest row to slider value
        idx = (df["time_s"] - slider_val).abs().idxmin()
        row = df.loc[idx]

        throttle = row.get("throttle_us", 1500)
        steer = row.get("steer_deg", 100)
        gear = int(row.get("gear", 0)) if "gear" in df.columns else 0
        omega = row.get("omega_deg_s", 0)
        speed = compute_speed_kph(omega) if not pd.isna(omega) else 0

        # For mini strip, show +-5s around current time
        t_cur = row["time_s"]
        window_df = df[(df["time_s"] >= t_cur - 5) & (df["time_s"] <= t_cur + 5)]

        # For G-force circle, show last 2s
        gforce_df = df[(df["time_s"] >= t_cur - 2) & (df["time_s"] <= t_cur)]

        t_str = f"{t_cur:.1f}s" if not pd.isna(t_cur) else "--"
        results = [
            gear_display(gear),
            build_speed_figure(speed if not pd.isna(speed) else 0),
            build_throttle_gauge(throttle if not pd.isna(throttle) else 1500),
            build_steering_wheel_fig(
                steer if not pd.isna(steer) else 100, height=250,
            ),
            build_mini_strip(window_df, window_s=10),
            [status_led(f"CSV @ {t_str}", active=True)],
        ]
        if SHOW_GFORCE:
            results.append(
                build_gforce_circle(gforce_df, max_samples=40)
                if not gforce_df.empty else empty_figure(280)
            )
        return results
