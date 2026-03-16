"""CSV log file loading with gap insertion."""

import glob
import os

import numpy as np
import pandas as pd


def load_csv(csv_path):
    """Load a telemetry CSV, insert NaN gap rows, return (df, filename)."""
    df = pd.read_csv(csv_path)
    filename = os.path.basename(csv_path)

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

    return df, filename


def find_latest_csv(script_dir=None):
    """Find the most recent log_*.csv in the given directory."""
    if script_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_dir = os.path.dirname(script_dir)  # up from dashboard/
    candidates = sorted(glob.glob(os.path.join(script_dir, "log_*.csv")))
    if not candidates:
        return None
    return candidates[-1]
