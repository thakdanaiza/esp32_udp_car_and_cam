"""Dash app factory: header, mode switching, callback registration."""

import sys

import flask
from dash import Dash, html, dcc, Output, Input

from .constants import (
    CARD_BG, BORDER, TEXT, TEXT_DIM,
    LIVE_UPDATE_MS, LIVE_WINDOW_SECONDS, SHOW_CAMERA,
    UDP_RELAY_PORT,
)
from .components import page_style
from .buffers import TelemetryBuffer, CameraBuffer
from .receivers import start_telemetry_receiver, start_camera_receiver
from .csv_loader import load_csv, find_latest_csv
from . import driver_mode, data_mode


def create_app(live_mode=False, csv_path=None):
    """Create and return the configured Dash application."""
    app = Dash(__name__)
    app.title = "JST Racing Telemetry"

    _register_dash4_fix(app)

    # ---- Data setup ----
    df = None
    filename = None
    tele_buffer = None
    cam_buffer = None

    if live_mode:
        tele_buffer = TelemetryBuffer(window_s=LIVE_WINDOW_SECONDS)
        start_telemetry_receiver(tele_buffer, port=UDP_RELAY_PORT)
        print(f"LIVE MODE — Listening for telemetry on UDP port {UDP_RELAY_PORT}")

        if SHOW_CAMERA:
            cam_buffer = CameraBuffer()
            start_camera_receiver(cam_buffer)
    else:
        if csv_path is None:
            csv_path = find_latest_csv()
        if csv_path is None:
            print("Usage: python dashboard.py [log.csv]")
            print("       python dashboard.py --live")
            print("No log_*.csv found in project directory.")
            sys.exit(1)
        print(f"Loading {csv_path} ...")
        df, filename = load_csv(csv_path)

    # ---- Build mode layouts ----
    drv_layout = driver_mode.create_layout(live_mode, df)
    dat_layout = data_mode.create_layout(live_mode, df, filename)

    # ---- Assemble page layout ----
    app.layout = html.Div(
        [
            _build_header(live_mode),
            dcc.Store(id="current-mode", data="data"),
            drv_layout,
            dat_layout,
            dcc.Interval(
                id="live-interval",
                interval=LIVE_UPDATE_MS,
                n_intervals=0,
                disabled=not live_mode,
            ),
        ],
        style=page_style,
    )

    # ---- Clientside callback for instant mode switching ----
    app.clientside_callback(
        """
        function(mode) {
            return [
                mode,
                {display: mode === 'driver' ? 'block' : 'none'},
                {display: mode === 'data' ? 'block' : 'none'}
            ];
        }
        """,
        [
            Output("current-mode", "data"),
            Output("driver-container", "style"),
            Output("data-container", "style"),
        ],
        Input("mode-toggle", "value"),
    )

    # ---- Register mode-specific callbacks ----
    driver_mode.register_callbacks(
        app, live_mode, tele_buffer=tele_buffer, cam_buffer=cam_buffer, df=df,
    )
    data_mode.register_callbacks(
        app, live_mode, tele_buffer=tele_buffer, cam_buffer=cam_buffer, df=df,
    )

    return app


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _build_header(live_mode):
    return html.Div(
        [
            html.H1(
                "JST Racing Telemetry",
                style={
                    "margin": "0",
                    "fontSize": "22px",
                    "fontWeight": "700",
                    "color": TEXT,
                    "fontFamily": "JetBrains Mono, monospace",
                },
            ),
            # Mode toggle
            html.Div(
                [
                    dcc.RadioItems(
                        id="mode-toggle",
                        options=[
                            {"label": "DRIVER", "value": "driver"},
                            {"label": "DATA TEAM", "value": "data"},
                        ],
                        value="data",
                        inline=True,
                        inputStyle={"display": "none"},
                        labelStyle={
                            "display": "inline-block",
                            "padding": "6px 16px",
                            "margin": "0 4px",
                            "borderRadius": "6px",
                            "fontSize": "12px",
                            "fontWeight": "700",
                            "cursor": "pointer",
                            "color": TEXT_DIM,
                            "backgroundColor": CARD_BG,
                            "border": f"1px solid {BORDER}",
                            "fontFamily": "JetBrains Mono, monospace",
                        },
                    ),
                ],
                style={"marginLeft": "20px"},
            ),
        ],
        style={
            "padding": "20px 28px 10px 28px",
            "display": "flex",
            "alignItems": "center",
        },
    )


# ---------------------------------------------------------------------------
# Dash 4 client-side batching fix
# ---------------------------------------------------------------------------

def _register_dash4_fix(app):
    """Work around Dash 4 bug that batches inputs across co-firing callbacks."""

    @app.server.before_request
    def _fix_dash4_input_batching():
        if flask.request.path != "/_dash-update-component" or flask.request.method != "POST":
            return
        body = flask.request.get_json(silent=True)
        if not body:
            return
        cb = app.callback_map.get(body.get("output", ""))
        if not cb:
            return
        all_sent = {}
        for i in body.get("inputs", []):
            all_sent[(i["id"], i["property"])] = i
        for s in body.get("state", []):
            all_sent[(s["id"], s["property"])] = s
        body["inputs"] = [
            all_sent.get(
                (d["id"], d["property"]),
                {"id": d["id"], "property": d["property"], "value": None},
            )
            for d in cb["inputs"]
        ]
        body["state"] = [
            all_sent.get(
                (d["id"], d["property"]),
                {"id": d["id"], "property": d["property"], "value": None},
            )
            for d in cb["state"]
        ]
