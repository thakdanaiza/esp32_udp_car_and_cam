#!/usr/bin/env python3
"""JST Racing Telemetry Dashboard — thin launcher.

Usage:
    python dashboard.py                # auto-find latest log_*.csv
    python dashboard.py log_file.csv   # open specific CSV
    python dashboard.py --live         # live UDP telemetry mode
"""

import sys


def main():
    live_mode = "--live" in sys.argv
    csv_path = None
    if not live_mode:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if args:
            csv_path = args[0]

    from dashboard.app import create_app

    app = create_app(live_mode=live_mode, csv_path=csv_path)
    print("Dashboard ready -> http://localhost:8050")
    app.run(debug=False, port=8050)


if __name__ == "__main__":
    main()
