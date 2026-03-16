"""Reusable Dash UI components and style dicts."""

from dash import html

from .constants import BG, CARD_BG, BORDER, TEXT, TEXT_DIM, RED, GREEN, GOLD

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
card_style = {
    "backgroundColor": CARD_BG,
    "border": f"1px solid {BORDER}",
    "borderRadius": "10px",
    "padding": "18px 24px",
    "flex": "1",
    "margin": "0 8px",
    "textAlign": "center",
}

kpi_value_style = {
    "fontSize": "28px",
    "fontWeight": "700",
    "margin": "0",
    "fontFamily": "JetBrains Mono, monospace",
}

kpi_label_style = {
    "fontSize": "11px",
    "color": TEXT_DIM,
    "margin": "6px 0 0 0",
    "textTransform": "uppercase",
    "letterSpacing": "1px",
}

gforce_label_style = {
    "textAlign": "center",
    "color": TEXT_DIM,
    "fontSize": "11px",
    "letterSpacing": "2px",
    "margin": "10px 0 0 0",
    "fontFamily": "JetBrains Mono, monospace",
}

page_style = {
    "backgroundColor": BG,
    "minHeight": "100vh",
    "fontFamily": "JetBrains Mono, monospace",
    "color": TEXT,
}


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def kpi_card(value, label, color):
    return html.Div(
        [
            html.P(value, style={**kpi_value_style, "color": color}),
            html.P(label, style=kpi_label_style),
        ],
        style=card_style,
    )


def status_led(label, active=False, color_on=GREEN, color_off=TEXT_DIM):
    """Small status indicator: colored dot + label."""
    color = color_on if active else color_off
    return html.Span(
        [
            html.Span(
                style={
                    "display": "inline-block",
                    "width": "8px",
                    "height": "8px",
                    "borderRadius": "50%",
                    "backgroundColor": color,
                    "marginRight": "6px",
                    "verticalAlign": "middle",
                }
            ),
            html.Span(
                label,
                style={
                    "fontSize": "11px",
                    "color": color,
                    "verticalAlign": "middle",
                    "fontFamily": "JetBrains Mono, monospace",
                },
            ),
        ],
        style={"marginRight": "16px"},
    )


def gear_display(gear=0):
    """Large gear indicator for Driver Mode."""
    if gear is None:
        gear = 0
    if gear == -1:
        text = "R"
        color = RED
    elif gear == 0:
        text = "N"
        color = GOLD
    else:
        text = str(gear)
        color = GREEN
    return html.Div(
        [
            html.Div(
                text,
                style={
                    "fontSize": "96px",
                    "fontWeight": "900",
                    "color": color,
                    "fontFamily": "JetBrains Mono, monospace",
                    "lineHeight": "1",
                },
            ),
            html.Div(
                "GEAR",
                style={
                    "fontSize": "11px",
                    "color": TEXT_DIM,
                    "letterSpacing": "3px",
                    "marginTop": "4px",
                },
            ),
        ],
        style={"textAlign": "center"},
    )
