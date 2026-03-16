"""Derived metrics: G-force, speed, FFT, statistics."""

import numpy as np

from .constants import WHEEL_DIAMETER_MM


def add_gforce_cols(dataframe):
    """Add gravity-corrected G-force columns (modifies in place, returns df)."""
    ax_mean = dataframe["ax"].mean()
    ay_mean = dataframe["ay"].mean()
    az_mean = dataframe["az"].mean()
    dataframe["ax_corr"] = dataframe["ax"] - ax_mean
    dataframe["ay_corr"] = dataframe["ay"] - ay_mean
    dataframe["az_corr"] = dataframe["az"] - az_mean
    dataframe["g_lateral"] = dataframe["ax_corr"] / 9.81
    dataframe["g_longitudinal"] = dataframe["ay_corr"] / 9.81
    dataframe["g_resultant"] = np.sqrt(
        dataframe["ax_corr"] ** 2
        + dataframe["ay_corr"] ** 2
        + dataframe["az_corr"] ** 2
    ) / 9.81
    return dataframe


def compute_speed_kph(omega_deg_s, wheel_dia_mm=WHEEL_DIAMETER_MM):
    """Convert wheel angular velocity (deg/s) to km/h."""
    rpm = np.abs(omega_deg_s) / 360 * 60
    circumference_m = np.pi * wheel_dia_mm / 1000
    return rpm * circumference_m * 60 / 1000


def compute_fft(signal, rate=20):
    """Compute FFT of a signal. Returns (freqs, magnitudes)."""
    signal = np.asarray(signal, dtype=float)
    signal = signal[~np.isnan(signal)]
    if len(signal) < 4:
        return np.array([]), np.array([])
    n = len(signal)
    window = np.hanning(n)
    windowed = (signal - np.mean(signal)) * window
    fft_vals = np.fft.rfft(windowed)
    magnitudes = 2.0 / n * np.abs(fft_vals[: n // 2])
    freqs = np.fft.rfftfreq(n, d=1.0 / rate)[: n // 2]
    return freqs, magnitudes


def rolling_rms(series, window=20):
    """Compute rolling RMS of a pandas Series."""
    return (series ** 2).rolling(window=window, min_periods=1).mean().apply(np.sqrt)


def compute_statistics(df, cols):
    """Compute min/max/mean/std/RMS for each column. Returns dict of dicts."""
    stats = {}
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        stats[col] = {
            "min": float(s.min()),
            "max": float(s.max()),
            "mean": float(s.mean()),
            "std": float(s.std()),
            "rms": float(np.sqrt((s ** 2).mean())),
        }
    return stats
