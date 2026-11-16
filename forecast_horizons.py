"""Earliest measurable conditional outcome, separate from frozen BUY validation."""
from math import sqrt

import numpy as np
import pandas as pd

from daily_signal_scorecard import _clean_closes
from landing_signal import display_signal_label, signal_from_percentile
from short_term_signal import TEST_END, TEST_START, features


HORIZONS = (
    (1, "1 trading day"), (2, "2 trading days"), (3, "3 trading days"),
    (5, "1 week"), (10, "2 weeks"), (21, "1 month"),
    (42, "2 months"), (63, "3 months"), (126, "6 months"), (252, "1 year"),
)
MIN_OBSERVATIONS = 30


def _wilson(wins, count):
    z = 1.959963984540054
    rate = wins / count
    scale = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / scale
    radius = z * sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / scale
    lower = 0. if wins == 0 else max(0., center - radius)
    upper = 1. if wins == count else min(1., center + radius)
    return lower, upper


def earliest_historical_outlook(
    closes, *, start=TEST_START, end=TEST_END, min_observations=MIN_OBSERVATIONS,
):
    """Choose by horizon and sample count, never by whichever return looks best.

    Rating at t; entry at the next session's close; exit h sessions after entry.
    Choose a common non-overlap schedule before filtering by today's rating.
    The reused historical evaluation period is not a new validation experiment.
    """
    if min_observations < MIN_OBSERVATIONS:
        raise ValueError("At least 30 non-overlapping outcomes are required.")
    closes = _clean_closes(closes)
    result = {"selected": None, "candidates": [], "minimum": min_observations,
              "evaluation_start": start, "evaluation_end": end, "rating": None}
    if len(closes) < 3:
        return result
    frame = features(closes)
    if not np.isfinite(frame["percentile"].iloc[-1]):
        return result
    ratings = frame["percentile"].map(
        lambda value: display_signal_label(signal_from_percentile(value))
    )
    result.update(rating=ratings.iloc[-1], as_of=closes.index[-1].date().isoformat())
    dates = closes.index
    values = closes.to_numpy()
    eligible = np.flatnonzero(
        (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end)) &
        frame["percentile"].notna().to_numpy()
    )
    for horizon, label in HORIZONS:
        selected, next_position = [], 0
        for position in eligible:
            if position < next_position:
                continue
            next_position = position + horizon + 1
            exit_position = position + horizon + 1
            if exit_position < len(closes) and dates[exit_position] <= pd.Timestamp(end):
                selected.append(position)
        positions = np.asarray(selected, dtype=int)
        returns = values[positions + horizon + 1] / values[positions + 1] - 1
        matching = returns[ratings.iloc[positions].to_numpy() == result["rating"]]
        count = len(matching)
        wins = int((matching > 0).sum())
        baseline = float(np.mean(returns > 0) * 100) if len(returns) else None
        frequency = wins / count * 100 if count else None
        interval = _wilson(wins, count) if count else (None, None)
        row = {
            "sessions": horizon, "label": label, "observations": count,
            "wins": wins, "higher_pct": frequency,
            "baseline_observations": len(returns), "baseline_pct": baseline,
            "difference_pp": frequency - baseline if count else None,
            "interval_low_pct": interval[0] * 100 if count else None,
            "interval_high_pct": interval[1] * 100 if count else None,
        }
        result["candidates"].append(row)
        if result["selected"] is None and count >= min_observations:
            result["selected"] = row
    return result
