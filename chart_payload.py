"""JSON-safe payload preparation for the interactive historical chart."""

import math


def clean_chart_points(index, values):
    """Return aligned date/value lists containing only finite positive prices."""
    dates = []
    prices = []
    for date, raw_value in zip(index, values):
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        dates.append(date.strftime("%Y-%m-%d"))
        prices.append(value)
    return dates, prices


def normalize_overlay(soxl_df, overlay_df):
    """Scale a clean overlay to SOXL at the first usable common date."""
    dates, actual = clean_chart_points(overlay_df.index, overlay_df["Close"])
    if not dates:
        return [], [], []

    scale = 1.0
    for common_date in soxl_df.index.intersection(overlay_df.index):
        try:
            soxl_start = float(soxl_df.loc[common_date, "Close"])
            overlay_start = float(overlay_df.loc[common_date, "Close"])
        except (TypeError, ValueError):
            continue
        if (
            math.isfinite(soxl_start)
            and math.isfinite(overlay_start)
            and soxl_start > 0
            and overlay_start > 0
        ):
            scale = soxl_start / overlay_start
            break

    scaled = [value * scale for value in actual]
    return dates, scaled, actual
