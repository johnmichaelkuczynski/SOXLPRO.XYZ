"""Historical scorecard for the landing page's daily SOXL signal.

This module deliberately contains no Streamlit code.  It evaluates the signal
shown by :mod:`landing_signal` at each historical close and records what a
conservative next-session entry would have produced later.
"""

from __future__ import annotations

from numbers import Integral

import numpy as np
import pandas as pd

from landing_signal import (
    TIMEFRAMES,
    TIMEFRAME_WEIGHTS,
    display_signal_label,
    signal_from_percentile,
)


ALLOWED_HORIZONS = (5, 21, 63, 126, 252)
RATING_LABELS = (
    "BUY",
    "POSSIBLE BUY",
    "DO NOTHING",
    "POSSIBLE SELL",
    "SELL",
)
HISTORY_COLUMNS = (
    "Rating",
    "Percentile",
    "Rating close",
    "Entry date",
    "Entry close",
    "Exit date",
    "Exit close",
    "Return",
    "Worst drawdown",
    "Status",
)
SUMMARY_COLUMNS = (
    "Rating",
    "Rated days",
    "Completed",
    "Pending",
    "Win rate",
    "Average return",
    "Median return",
    "Worst return",
    "Average drawdown",
    "Win-rate lift",
    "Average-return lift",
)


def _validate_horizon(horizon: int) -> int:
    if isinstance(horizon, bool) or not isinstance(horizon, Integral):
        raise ValueError(f"horizon must be one of {ALLOWED_HORIZONS}")
    horizon = int(horizon)
    if horizon not in ALLOWED_HORIZONS:
        raise ValueError(f"horizon must be one of {ALLOWED_HORIZONS}")
    return horizon


def _empty_closes() -> pd.Series:
    return pd.Series(dtype=float)


def _clean_closes(closes: pd.Series) -> pd.Series:
    """Keep only finite positive closes in chronological, unique-date order."""
    if closes is None:
        return _empty_closes()

    if isinstance(closes, pd.DataFrame):
        if "Close" in closes.columns:
            closes = closes["Close"]
        elif closes.shape[1] == 1:
            closes = closes.iloc[:, 0]
        else:
            return _empty_closes()
    elif not isinstance(closes, pd.Series):
        try:
            closes = pd.Series(closes)
        except (TypeError, ValueError):
            return _empty_closes()

    try:
        index = pd.to_datetime(closes.index, errors="coerce")
        values = pd.to_numeric(closes, errors="coerce").to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError):
        return _empty_closes()

    try:
        if not isinstance(index, pd.DatetimeIndex):
            index = pd.DatetimeIndex(index)
    except (TypeError, ValueError, OverflowError):
        return _empty_closes()
    if index.tz is not None:
        index = index.tz_localize(None)

    valid = (~index.isna()) & np.isfinite(values) & (values > 0)
    if not valid.any():
        return _empty_closes()

    cleaned = pd.Series(values[valid], index=index[valid], dtype=float)
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    return cleaned.sort_index()


def _percentile(values: np.ndarray) -> float:
    """Match landing_signal.price_range_percentile for a valid trailing slice."""
    if len(values) < 2:
        return np.nan
    low = float(np.min(values))
    high = float(np.max(values))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return np.nan
    current = float(values[-1])
    return float(np.clip((current - low) / (high - low) * 100.0, 0.0, 100.0))


def _rating_percentile(values: np.ndarray, position: int) -> float:
    """Calculate the homepage composite using only data available that day."""
    readings = []
    for timeframe, sessions in TIMEFRAMES.items():
        if sessions is None:
            # All Time is expanding, but like the landing page it needs two
            # observations and a non-flat range.
            period = values[: position + 1]
            if len(period) < 2:
                percentile = np.nan
            else:
                percentile = _percentile(period)
        elif position + 1 < sessions:
            # Fixed windows are unavailable until their complete length exists.
            percentile = np.nan
        else:
            period = values[position - sessions + 1 : position + 1]
            percentile = _percentile(period)
        readings.append((timeframe, percentile))

    valid = [(name, value) for name, value in readings if np.isfinite(value)]
    if not valid:
        return np.nan
    weights = np.asarray([TIMEFRAME_WEIGHTS[name] for name, _ in valid], dtype=float)
    percentiles = np.asarray([value for _, value in valid], dtype=float)
    return float(np.average(percentiles, weights=weights))


def _empty_history(horizon: int) -> pd.DataFrame:
    result = pd.DataFrame(columns=HISTORY_COLUMNS)
    result.index = pd.DatetimeIndex([], name="Rating date")
    result.attrs["horizon"] = horizon
    return result


def build_rating_history(
    closes: pd.Series,
    horizon: int = 21,
) -> pd.DataFrame:
    """Build one landing-signal rating and conditional outcome per close date.

    ``closes`` is expected to already represent completed daily sessions.  A
    row is retained for every cleaned close, including early rows whose
    rating is ``INSUFFICIENT HISTORY``.  Outcomes use the next available
    session as entry and require the complete requested horizon after entry.
    """
    horizon = _validate_horizon(horizon)
    cleaned = _clean_closes(closes)
    if cleaned.empty:
        return _empty_history(horizon)

    dates = cleaned.index
    values = cleaned.to_numpy(dtype=float)
    rows = []

    for position, rating_date in enumerate(dates):
        percentile = _rating_percentile(values, position)
        internal_signal = signal_from_percentile(percentile)
        rating = display_signal_label(internal_signal)

        row = {
            "Rating": rating,
            "Percentile": percentile,
            "Rating close": float(values[position]),
            "Entry date": pd.NaT,
            "Entry close": np.nan,
            "Exit date": pd.NaT,
            "Exit close": np.nan,
            "Return": np.nan,
            "Worst drawdown": np.nan,
            "Status": (
                "Insufficient history"
                if rating == "INSUFFICIENT HISTORY"
                else "Awaiting outcome"
            ),
        }

        entry_position = position + 1
        exit_position = entry_position + horizon
        if rating != "INSUFFICIENT HISTORY" and entry_position < len(values):
            row["Entry date"] = dates[entry_position]
            row["Entry close"] = float(values[entry_position])

            if exit_position < len(values):
                row["Exit date"] = dates[exit_position]
                row["Exit close"] = float(values[exit_position])
                path = values[entry_position : exit_position + 1]
                row["Return"] = float(values[exit_position] / values[entry_position] - 1.0)
                row["Worst drawdown"] = float(
                    min(0.0, np.min(path) / values[entry_position] - 1.0)
                )
                row["Status"] = "Completed"

        rows.append(row)

    result = pd.DataFrame(rows, index=dates)
    result.index.name = "Rating date"
    result = result.loc[:, HISTORY_COLUMNS]
    result.attrs["horizon"] = horizon
    return result


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS)


def _finite_completed_returns(rows: pd.DataFrame) -> pd.Series:
    if rows.empty or "Status" not in rows or "Return" not in rows:
        return pd.Series(dtype=float)
    completed = rows.loc[rows["Status"].eq("Completed"), "Return"]
    completed = pd.to_numeric(completed, errors="coerce")
    return completed[np.isfinite(completed.to_numpy(dtype=float))]


def _aggregate(rows: pd.DataFrame, label: str) -> dict:
    rated_days = int(len(rows))
    pending = (
        int(rows["Status"].eq("Awaiting outcome").sum())
        if "Status" in rows
        else 0
    )
    completed_returns = _finite_completed_returns(rows)
    completed = int(len(completed_returns))

    if completed == 0:
        win_rate = average_return = median_return = worst_return = np.nan
        average_drawdown = np.nan
    else:
        values = completed_returns.to_numpy(dtype=float)
        win_rate = float(np.mean(values > 0.0))
        average_return = float(np.mean(values))
        median_return = float(np.median(values))
        worst_return = float(np.min(values))
        if "Worst drawdown" in rows:
            drawdowns = pd.to_numeric(
                rows.loc[rows["Status"].eq("Completed"), "Worst drawdown"],
                errors="coerce",
            )
            drawdowns = drawdowns[
                np.isfinite(drawdowns.to_numpy(dtype=float))
            ]
            average_drawdown = (
                float(np.mean(drawdowns.to_numpy(dtype=float)))
                if len(drawdowns)
                else np.nan
            )
        else:
            average_drawdown = np.nan

    return {
        "Rating": label,
        "Rated days": rated_days,
        "Completed": completed,
        "Pending": pending,
        "Win rate": win_rate,
        "Average return": average_return,
        "Median return": median_return,
        "Worst return": worst_return,
        "Average drawdown": average_drawdown,
    }


def _selected_ratings(history: pd.DataFrame, non_overlapping: bool) -> pd.DataFrame:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    if "Rating" not in history.columns:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    work = history.sort_index()
    eligible = work["Rating"].isin(RATING_LABELS).to_numpy()
    positions = np.flatnonzero(eligible)
    if not non_overlapping:
        return work.iloc[positions]

    raw_horizon = work.attrs.get("horizon", 21)
    horizon = _validate_horizon(raw_horizon)
    selected = []
    next_position = 0
    for position in positions:
        if position < next_position:
            continue
        selected.append(position)
        next_position = position + horizon + 1
    return work.iloc[selected]


def summarize_ratings(
    history: pd.DataFrame,
    non_overlapping: bool = False,
) -> pd.DataFrame:
    """Summarize conditional outcomes by displayed landing-page rating.

    The ``All rated days`` row is the comparator for every lift.  When
    ``non_overlapping`` is true, one schedule is selected before any
    per-rating grouping so each category uses the same unbiased denominator.
    """
    selected = _selected_ratings(history, non_overlapping)
    baseline = _aggregate(selected, "All rated days")
    baseline_win = baseline["Win rate"]
    baseline_return = baseline["Average return"]

    rows = []
    for label in ("All rated days", *RATING_LABELS):
        subset = selected if label == "All rated days" else selected[
            selected["Rating"].eq(label)
        ]
        row = _aggregate(subset, label)
        if np.isfinite(row["Win rate"]) and np.isfinite(baseline_win):
            row["Win-rate lift"] = float(row["Win rate"] - baseline_win)
        else:
            row["Win-rate lift"] = np.nan
        if np.isfinite(row["Average return"]) and np.isfinite(baseline_return):
            row["Average-return lift"] = float(
                row["Average return"] - baseline_return
            )
        else:
            row["Average-return lift"] = np.nan
        rows.append(row)

    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


__all__ = ["build_rating_history", "summarize_ratings"]