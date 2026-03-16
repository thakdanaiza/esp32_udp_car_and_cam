"""Data Team Mode — full engineering plots for analysis."""

import base64

import numpy as np
import pandas as pd
from dash import html, dcc, Output, Input, State
from dash.exceptions import PreventUpdate

from .constants import (
    CARD_BG, BORDER, TEXT, TEXT_DIM,
    RED, CYAN, GOLD, MAGENTA,
    SHOW_CAMERA, SHOW_GFORCE, LIVE_WINDOW_SECONDS, CAM_QUALITY,
)
from .components import kpi_card, gforce_label_style
from .figures import (
    build_timeseries_fig, build_gforce_fig, build_steering_wheel_fig,
    build_fft_fig, build_correlation_fig, empty_figure,
)
from .metrics import add_gforce_cols, compute_fft, compute_statistics


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

IMU_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz", "omega_deg_s"]


def create_layout(live_mode, df=None, filename=None):
    """Return the Data Team Mode layout div."""
    if live_mode:
        return _live_layout()
    else:
        return _csv_layout(df, filename)


def _live_layout():
    """Layout for live telemetry mode."""
    return html.Div([
        # Header controls
        html.Div([
            html.Span("LIVE", style={
                "backgroundColor": RED, "color": "white", "padding": "2px 10px",
                "borderRadius": "4px", "fontSize": "12px", "fontWeight": "700",
                "fontFamily": "JetBrains Mono, monospace",
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
                        "padding": "4px 10px", "margin": "0 3px",
                        "borderRadius": "4px", "fontSize": "11px",
                        "color": TEXT_DIM, "backgroundColor": CARD_BG,
                        "border": f"1px solid {BORDER}",
                        "cursor": "pointer",
                        "fontFamily": "JetBrains Mono, monospace",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "marginLeft": "auto"}),
        ], style={"padding": "0 28px 10px 28px", "display": "flex", "alignItems": "center"}),

        # KPI row
        html.Div(id="data-kpi-container", children=[
            kpi_card("--", "Max Wheel RPM", TEXT_DIM),
            kpi_card("--", "Samples", TEXT_DIM),
            kpi_card("--", "Window", TEXT_DIM),
            kpi_card("--", "Peak G-Force", TEXT_DIM),
            kpi_card("--", "Avg Hz", TEXT_DIM),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "0px"}),

        # Main plots row
        html.Div([
            html.Div([
                dcc.Graph(
                    id="data-timeseries", figure=empty_figure(1100),
                    config={"displayModeBar": True, "scrollZoom": True},
                ),
            ], style={"flex": "3"}),
            html.Div(
                ([
                    html.P("CAMERA", style=gforce_label_style),
                    html.Img(id="data-camera-feed", style={
                        "width": "100%", "borderRadius": "8px",
                        "border": f"1px solid {BORDER}", "display": "block",
                    }),
                    dcc.Slider(
                        id="data-cam-quality", min=1, max=63, value=CAM_QUALITY, step=1,
                        marks={1: "1 (best)", 32: "32", 63: "63 (fast)"},
                        tooltip={"placement": "bottom"},
                    ),
                ] if SHOW_CAMERA else []) + [
                    html.P("STEERING", style=gforce_label_style),
                    dcc.Graph(
                        id="data-steering-wheel",
                        figure=build_steering_wheel_fig(100),
                        config={"displayModeBar": False, "staticPlot": True},
                    ),
                ] + ([
                    html.P("G-FORCE MAP", style=gforce_label_style),
                    dcc.Graph(
                        id="data-gforce-graph", figure=empty_figure(450),
                        config={"displayModeBar": False},
                    ),
                ] if SHOW_GFORCE else []),
                style={"flex": "1", "minWidth": "320px"},
            ),
        ], style={"display": "flex", "padding": "0 20px", "gap": "8px"}),

        # Stats + FFT row
        html.Div([
            # Statistics table
            html.Div([
                html.P("STATISTICS", style=gforce_label_style),
                html.Div(id="data-stats-table", children=_empty_stats_table()),
            ], style={"flex": "1", "minWidth": "400px"}),
            # FFT
            html.Div([
                html.Div([
                    html.P("FFT SPECTRUM", style={**gforce_label_style, "display": "inline"}),
                    dcc.Dropdown(
                        id="data-fft-channel",
                        options=[{"label": c, "value": c} for c in IMU_CHANNELS],
                        value="ax",
                        clearable=False,
                        style={
                            "width": "150px", "display": "inline-block",
                            "marginLeft": "12px", "fontSize": "12px",
                            "backgroundColor": CARD_BG,
                        },
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                dcc.Graph(
                    id="data-fft-graph", figure=build_fft_fig([], [], ""),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1", "minWidth": "400px"}),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "12px"}),

        # Correlation row
        html.Div([
            html.Div([
                dcc.Graph(
                    id="data-corr-steer",
                    figure=build_correlation_fig([], [], "", "", "Steer vs Lateral G"),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1"}),
            html.Div([
                dcc.Graph(
                    id="data-corr-throttle",
                    figure=build_correlation_fig([], [], "", "", "Throttle vs Long G"),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1"}),
        ], style={"display": "flex", "padding": "0 20px", "gap": "12px"}),

        # CSV Export
        html.Div([
            html.Button("Export CSV", id="data-export-btn", n_clicks=0, style={
                "padding": "8px 20px", "backgroundColor": CARD_BG,
                "color": TEXT, "border": f"1px solid {BORDER}",
                "borderRadius": "6px", "cursor": "pointer", "fontSize": "12px",
                "fontFamily": "JetBrains Mono, monospace",
            }),
            dcc.Download(id="data-csv-download"),
        ], style={"padding": "10px 20px"}),

        # Hidden placeholders for elements that don't exist
        *(_live_hidden_placeholders()),
    ], id="data-container", style={"display": "block"})


def _csv_layout(df, filename):
    """Layout for CSV playback mode."""
    if df is None or df.empty:
        return html.Div("No data", id="data-container", style={"display": "block"})

    df = add_gforce_cols(df.copy())
    t = df["time_s"].values
    duration_s = df["time_s"].max() - df["time_s"].min()
    max_rpm = df["omega_deg_s"].abs().max() / 360 * 60
    peak_g = df["g_resultant"].max()
    n_samples = len(df)
    avg_hz = n_samples / max(duration_s, 0.1)

    has_ctrl = "throttle_us" in df.columns and "steer_deg" in df.columns
    ts_fig = build_timeseries_fig(df, has_control_cols=has_ctrl)
    gf_fig = build_gforce_fig(df) if SHOW_GFORCE else None

    # Pre-compute stats
    stat_cols = ["ax", "ay", "az", "gx", "gy", "gz", "omega_deg_s"]
    if has_ctrl:
        stat_cols = ["throttle_us", "steer_deg"] + stat_cols
    stats = compute_statistics(df, stat_cols)

    # Pre-compute default FFT
    freqs, mags = compute_fft(df["ax"].dropna().values, rate=max(1, avg_hz))

    # Pre-compute correlations
    df_valid = df.dropna(subset=["g_lateral", "g_longitudinal"])
    corr1_x, corr1_y = [], []
    corr2_x, corr2_y = [], []
    if has_ctrl and not df_valid.empty:
        corr1_x = df_valid["steer_deg"].values
        corr1_y = df_valid["g_lateral"].values
        corr2_x = df_valid["throttle_us"].values
        corr2_y = df_valid["g_longitudinal"].values

    return html.Div([
        # File info
        html.Div([
            html.P(f"{filename}  |  {duration_s:.1f}s  |  {n_samples} samples  |  {avg_hz:.1f} Hz",
                   style={
                       "margin": "0", "fontSize": "12px", "color": TEXT_DIM,
                       "fontFamily": "JetBrains Mono, monospace",
                       "padding": "0 28px 10px 28px",
                   }),
        ]),

        # KPI row
        html.Div([
            kpi_card(f"{max_rpm:.0f}", "Max Wheel RPM", RED),
            kpi_card(f"{n_samples:,}", "Samples", CYAN),
            kpi_card(f"{duration_s:.1f}s", "Duration", GOLD),
            kpi_card(f"{peak_g:.2f} G", "Peak G-Force", TEXT),
            kpi_card(f"{avg_hz:.1f}", "Avg Hz", MAGENTA),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "0px"}),

        # Main plots row
        html.Div([
            html.Div([
                dcc.Graph(figure=ts_fig, config={"displayModeBar": True, "scrollZoom": True}),
            ], style={"flex": "3"}),
        ] + ([html.Div([
                html.P("G-FORCE MAP", style=gforce_label_style),
                dcc.Graph(figure=gf_fig, config={"displayModeBar": False}),
                html.P("STEERING", style=gforce_label_style),
                dcc.Graph(
                    figure=build_steering_wheel_fig(
                        df["steer_deg"].iloc[-1] if has_ctrl else 100,
                    ),
                    config={"displayModeBar": False, "staticPlot": True},
                ),
            ], style={"flex": "1", "minWidth": "320px"}),
        ] if SHOW_GFORCE else []),
            style={"display": "flex", "padding": "0 20px", "gap": "8px"},
        ),

        # Stats + FFT row
        html.Div([
            html.Div([
                html.P("STATISTICS", style=gforce_label_style),
                _build_stats_table(stats),
            ], style={"flex": "1", "minWidth": "400px"}),
            html.Div([
                html.Div([
                    html.P("FFT SPECTRUM", style={**gforce_label_style, "display": "inline"}),
                    dcc.Dropdown(
                        id="data-fft-channel",
                        options=[{"label": c, "value": c} for c in IMU_CHANNELS],
                        value="ax",
                        clearable=False,
                        style={
                            "width": "150px", "display": "inline-block",
                            "marginLeft": "12px", "fontSize": "12px",
                            "backgroundColor": CARD_BG,
                        },
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
                dcc.Graph(
                    id="data-fft-graph",
                    figure=build_fft_fig(freqs, mags, "ax"),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1", "minWidth": "400px"}),
        ], style={"display": "flex", "padding": "10px 20px", "gap": "12px"}),

        # Correlation row
        html.Div([
            html.Div([
                dcc.Graph(
                    figure=build_correlation_fig(
                        corr1_x, corr1_y, "Steering (deg)", "Lateral G",
                        "Steer vs Lateral G",
                    ),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1"}),
            html.Div([
                dcc.Graph(
                    figure=build_correlation_fig(
                        corr2_x, corr2_y, "Throttle (us)", "Longitudinal G",
                        "Throttle vs Long G",
                    ),
                    config={"displayModeBar": False},
                ),
            ], style={"flex": "1"}),
        ], style={"display": "flex", "padding": "0 20px", "gap": "12px"}),

        # CSV Export
        html.Div([
            html.Button("Export CSV", id="data-export-btn", n_clicks=0, style={
                "padding": "8px 20px", "backgroundColor": CARD_BG,
                "color": TEXT, "border": f"1px solid {BORDER}",
                "borderRadius": "6px", "cursor": "pointer", "fontSize": "12px",
                "fontFamily": "JetBrains Mono, monospace",
            }),
            dcc.Download(id="data-csv-download"),
        ], style={"padding": "10px 20px"}),

        # Hidden placeholders needed by live-mode callbacks
        *_csv_hidden_placeholders(),
    ], id="data-container", style={"display": "block"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_stats_table():
    return html.Div("Waiting for data...", style={"color": TEXT_DIM, "padding": "10px"})


def _build_stats_table(stats):
    """Build an HTML table from stats dict."""
    if not stats:
        return _empty_stats_table()

    header = html.Tr([
        html.Th("Channel", style=_th_style()),
        html.Th("Min", style=_th_style()),
        html.Th("Max", style=_th_style()),
        html.Th("Mean", style=_th_style()),
        html.Th("Std", style=_th_style()),
        html.Th("RMS", style=_th_style()),
    ])

    rows = []
    for col, vals in stats.items():
        rows.append(html.Tr([
            html.Td(col, style=_td_style()),
            html.Td(f"{vals['min']:.3f}", style=_td_style()),
            html.Td(f"{vals['max']:.3f}", style=_td_style()),
            html.Td(f"{vals['mean']:.3f}", style=_td_style()),
            html.Td(f"{vals['std']:.3f}", style=_td_style()),
            html.Td(f"{vals['rms']:.3f}", style=_td_style()),
        ]))

    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        style={
            "width": "100%", "borderCollapse": "collapse",
            "fontSize": "11px", "fontFamily": "JetBrains Mono, monospace",
        },
    )


def _th_style():
    return {
        "padding": "6px 8px", "textAlign": "left", "color": TEXT_DIM,
        "borderBottom": f"1px solid {BORDER}", "fontSize": "10px",
        "textTransform": "uppercase", "letterSpacing": "1px",
    }


def _td_style():
    return {
        "padding": "4px 8px", "borderBottom": f"1px solid {BORDER}",
        "color": TEXT, "fontSize": "11px",
    }


def _live_hidden_placeholders():
    """Placeholders for elements missing in live layout."""
    items = []
    if not SHOW_CAMERA:
        items.append(html.Img(id="data-camera-feed", style={"display": "none"}))
        items.append(html.Div(
            dcc.Slider(id="data-cam-quality", min=1, max=63, value=48),
            style={"display": "none"},
        ))
    return items


def _csv_hidden_placeholders():
    """Placeholders for elements missing in CSV layout."""
    return [
        dcc.RadioItems(id="window-selector", value=60, style={"display": "none"}),
        html.Div(id="data-kpi-container", style={"display": "none"}),
        dcc.Graph(id="data-timeseries", style={"display": "none"}),
        dcc.Graph(id="data-steering-wheel", style={"display": "none"}),
        html.Div(id="data-stats-table", style={"display": "none"}),
        dcc.Graph(id="data-corr-steer", style={"display": "none"}),
        dcc.Graph(id="data-corr-throttle", style={"display": "none"}),
    ] + ([
        dcc.Graph(id="data-gforce-graph", style={"display": "none"}),
    ] if SHOW_GFORCE else []) + ([
        html.Img(id="data-camera-feed", style={"display": "none"}),
        html.Div(
            dcc.Slider(id="data-cam-quality", min=1, max=63, value=48),
            style={"display": "none"},
        ),
    ] if SHOW_CAMERA else [])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def register_callbacks(app, live_mode, tele_buffer=None, cam_buffer=None, df=None):
    """Register all Data Team Mode callbacks."""
    if live_mode:
        _register_live_callbacks(app, tele_buffer, cam_buffer)
    _register_shared_callbacks(app, live_mode, tele_buffer, df)


def _register_live_callbacks(app, tele_buffer, cam_buffer):
    """Live-mode data team callbacks: interval-driven."""

    @app.callback(
        [
            Output("data-timeseries", "figure"),
            Output("data-steering-wheel", "figure"),
            Output("data-kpi-container", "children"),
            Output("data-stats-table", "children"),
        ] + ([Output("data-gforce-graph", "figure")] if SHOW_GFORCE else []),
        Input("live-interval", "n_intervals"),
        [State("current-mode", "data"), State("window-selector", "value")],
        prevent_initial_call=True,
    )
    def update_data_live(_n, mode, window_s):
        if mode != "data":
            raise PreventUpdate

        tele_buffer.window_s = window_s
        snap = tele_buffer.snapshot()
        if snap.empty:
            defaults = [
                empty_figure(1100),
                build_steering_wheel_fig(100),
                [
                    kpi_card("--", "Max Wheel RPM", TEXT_DIM),
                    kpi_card("--", "Samples", TEXT_DIM),
                    kpi_card("--", "Window", TEXT_DIM),
                    kpi_card("--", "Peak G-Force", TEXT_DIM),
                    kpi_card("--", "Avg Hz", TEXT_DIM),
                ],
                _empty_stats_table(),
            ]
            if SHOW_GFORCE:
                defaults.append(empty_figure(450))
            return defaults

        has_ctrl = "throttle_us" in snap.columns and "steer_deg" in snap.columns
        ts_fig = build_timeseries_fig(snap, has_control_cols=has_ctrl)

        steer = int(snap["steer_deg"].iloc[-1]) if has_ctrl else 100
        steer_fig = build_steering_wheel_fig(steer)

        duration = snap["time_s"].max() - snap["time_s"].min()
        max_rpm = snap["omega_deg_s"].abs().max() / 360 * 60
        snap_g = add_gforce_cols(snap.copy())
        peak_g = snap_g["g_resultant"].max()
        avg_hz = len(snap) / max(duration, 0.1)

        kpis = [
            kpi_card(f"{max_rpm:.0f}", "Max Wheel RPM", RED),
            kpi_card(f"{len(snap)}", "Samples", CYAN),
            kpi_card(f"{duration:.1f}s", "Window", GOLD),
            kpi_card(f"{peak_g:.2f} G", "Peak G-Force", TEXT),
            kpi_card(f"{avg_hz:.1f}", "Avg Hz", MAGENTA),
        ]

        stat_cols = ["ax", "ay", "az", "gx", "gy", "gz", "omega_deg_s"]
        if has_ctrl:
            stat_cols = ["throttle_us", "steer_deg"] + stat_cols
        stats = compute_statistics(snap, stat_cols)
        stats_table = _build_stats_table(stats)

        results = [ts_fig, steer_fig, kpis, stats_table]
        if SHOW_GFORCE:
            results.append(build_gforce_fig(snap))
        return results

    # Correlation + FFT update (throttled: every 5th tick = ~1/sec)
    @app.callback(
        [
            Output("data-corr-steer", "figure"),
            Output("data-corr-throttle", "figure"),
        ],
        Input("live-interval", "n_intervals"),
        State("current-mode", "data"),
        prevent_initial_call=True,
    )
    def update_correlations(_n, mode):
        if mode != "data" or _n % 5 != 0:
            raise PreventUpdate

        snap = tele_buffer.snapshot()
        if snap.empty:
            return [
                build_correlation_fig([], [], "", "", "Steer vs Lateral G"),
                build_correlation_fig([], [], "", "", "Throttle vs Long G"),
            ]

        snap_g = add_gforce_cols(snap.copy())
        valid = snap_g.dropna(subset=["g_lateral", "g_longitudinal"])
        has_ctrl = "throttle_us" in snap.columns and "steer_deg" in snap.columns

        if has_ctrl and not valid.empty:
            corr1 = build_correlation_fig(
                valid["steer_deg"].values, valid["g_lateral"].values,
                "Steering (deg)", "Lateral G", "Steer vs Lateral G",
            )
            corr2 = build_correlation_fig(
                valid["throttle_us"].values, valid["g_longitudinal"].values,
                "Throttle (us)", "Longitudinal G", "Throttle vs Long G",
            )
        else:
            corr1 = build_correlation_fig([], [], "", "", "Steer vs Lateral G")
            corr2 = build_correlation_fig([], [], "", "", "Throttle vs Long G")
        return [corr1, corr2]

    # Camera feed (data mode)
    if SHOW_CAMERA and cam_buffer is not None:
        @app.callback(
            Output("data-camera-feed", "src"),
            Input("live-interval", "n_intervals"),
            State("current-mode", "data"),
            State("data-cam-quality", "value"),
            prevent_initial_call=True,
        )
        def update_data_camera(_n, mode, quality):
            if mode != "data":
                raise PreventUpdate
            if quality is not None:
                cam_buffer.quality = max(1, min(63, quality))
            jpeg = cam_buffer.get_latest()
            if jpeg is None:
                return ""
            return f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}"


def _register_shared_callbacks(app, live_mode, tele_buffer, df):
    """Callbacks that work in both live and CSV modes."""

    # FFT channel dropdown (interval always as 2nd Input; disabled in CSV mode)
    @app.callback(
        Output("data-fft-graph", "figure"),
        [Input("data-fft-channel", "value"), Input("live-interval", "n_intervals")],
        State("current-mode", "data"),
        prevent_initial_call=True,
    )
    def update_fft(channel, _n, mode):
        if mode != "data":
            raise PreventUpdate

        if live_mode:
            snap = tele_buffer.snapshot()
            if snap.empty or channel not in snap.columns:
                return build_fft_fig([], [], channel or "")
            duration = snap["time_s"].max() - snap["time_s"].min()
            rate = max(1, len(snap) / max(duration, 0.1))
            signal = snap[channel].dropna().values
        else:
            if df is None or df.empty or channel not in df.columns:
                return build_fft_fig([], [], channel or "")
            duration = df["time_s"].max() - df["time_s"].min()
            rate = max(1, len(df) / max(duration, 0.1))
            signal = df[channel].dropna().values

        freqs, mags = compute_fft(signal, rate=rate)
        return build_fft_fig(freqs, mags, channel)

    # CSV Export
    @app.callback(
        Output("data-csv-download", "data"),
        Input("data-export-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def export_csv(n_clicks):
        if not n_clicks:
            raise PreventUpdate

        if live_mode:
            snap = tele_buffer.snapshot()
            if snap.empty:
                raise PreventUpdate
            export_df = snap
        else:
            if df is None or df.empty:
                raise PreventUpdate
            export_df = df

        csv_str = export_df.to_csv(index=False)
        return dcc.send_string(csv_str, "telemetry_export.csv")
