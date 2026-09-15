"""Causal time--price area feature construction.

The functions in this module deliberately keep the feature engineering layer
independent of the model and UI layers.  Every anchor is selected using data
available at the observation date.  In particular, swing pivots retain both
their originating date and the later date on which they become available.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "close",
    "anchor_date",
    "anchor_price",
    "anchor_type",
    "anchor_confirmation_date",
    "elapsed_sessions",
    "session_pos",
    "log_return",
    "area_raw",
    "area_log",
    "area_signed",
    "area_norm",
    "area_growth",
    "volatility",
    "atr_pct",
    "ret_1",
    "ret_5",
    "ret_10",
    "ret_20",
    "abs_ret_5",
    "abs_ret_20",
    "ma_trend",
]

_OHLC_COLUMNS = ("Open", "High", "Low", "Close")
_VALID_LOOKBACKS = (5, 10, 20, 60)
_VALID_VOL_WINDOWS = (10, 20, 60)
_DEFAULT_HORIZONS = (1, 5, 10, 20)
_ANCHOR_RESET_NOTE = (
    "Future area labels are taken from the feature row at t+h.  That row "
    "uses its own causal anchor (and, for swings, its own confirmation date); "
    "it is not evaluated against the anchor selected at t."
)


def _as_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize the feature configuration."""

    raw = dict(config or {})
    anchor_mode = str(raw.get("anchor_mode", "low20")).strip().lower()
    valid_anchor_modes = {
        "low20",
        "high20",
        "swing_low",
        "swing_high",
        "rolling",
        "fixed",
    }
    if anchor_mode not in valid_anchor_modes:
        raise ValueError(
            f"anchor_mode must be one of {sorted(valid_anchor_modes)}, "
            f"got {anchor_mode!r}"
        )

    try:
        lookback = int(raw.get("lookback", 20))
    except (TypeError, ValueError) as exc:
        raise ValueError("lookback must be one of 5, 10, 20, or 60") from exc
    if lookback not in _VALID_LOOKBACKS:
        raise ValueError("lookback must be one of 5, 10, 20, or 60")

    try:
        pivot_bars = int(raw.get("pivot_bars", 3))
    except (TypeError, ValueError) as exc:
        raise ValueError("pivot_bars must be a positive integer") from exc
    if pivot_bars < 1:
        raise ValueError("pivot_bars must be a positive integer")

    try:
        vol_window = int(raw.get("vol_window", 20))
    except (TypeError, ValueError) as exc:
        raise ValueError("vol_window must be one of 10, 20, or 60") from exc
    if vol_window not in _VALID_VOL_WINDOWS:
        raise ValueError("vol_window must be one of 10, 20, or 60")

    normalization = str(
        raw.get("normalization", "volatility")
    ).strip().lower()
    if normalization not in {"volatility", "none"}:
        raise ValueError("normalization must be 'volatility' or 'none'")

    fixed_anchor = raw.get("fixed_anchor")
    fixed_timestamp: pd.Timestamp | None = None
    if anchor_mode == "fixed":
        if fixed_anchor is None or str(fixed_anchor).strip() == "":
            raise ValueError(
                "fixed_anchor is required when anchor_mode='fixed'"
            )
        try:
            fixed_timestamp = pd.Timestamp(fixed_anchor)
        except (TypeError, ValueError) as exc:
            raise ValueError("fixed_anchor must be an ISO date") from exc
        if pd.isna(fixed_timestamp):
            raise ValueError("fixed_anchor must be an ISO date")

    normalized = dict(raw)
    normalized.update(
        {
            "anchor_mode": anchor_mode,
            "lookback": lookback,
            "pivot_bars": pivot_bars,
            "vol_window": vol_window,
            "normalization": normalization,
        }
    )
    if fixed_timestamp is not None:
        normalized["fixed_anchor"] = fixed_timestamp.isoformat()
    return normalized


def _prepare_ohlc(
    ohlc: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """Copy, order, de-duplicate, and validate an OHLC frame."""

    if not isinstance(ohlc, pd.DataFrame):
        raise TypeError("ohlc must be a pandas DataFrame")
    missing = [column for column in _OHLC_COLUMNS if column not in ohlc]
    if missing:
        raise ValueError(f"ohlc is missing required columns: {missing}")

    frame = ohlc.loc[:, list(_OHLC_COLUMNS)].copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        try:
            converted_index = pd.to_datetime(frame.index, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError("ohlc must have a datetime index") from exc
        if not isinstance(converted_index, pd.DatetimeIndex):
            raise ValueError("ohlc must have a datetime index")
        frame.index = converted_index
    if frame.index.hasnans:
        raise ValueError("ohlc index cannot contain missing datetimes")

    warnings: list[str] = []
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index(kind="mergesort")
        warnings.append("Input datetimes were sorted chronologically.")
    if frame.index.has_duplicates:
        duplicate_count = int(frame.index.duplicated(keep="last").sum())
        # Keeping the last record gives a deterministic result while allowing
        # a corrected/revised upstream bar to supersede an earlier duplicate.
        frame = frame[~frame.index.duplicated(keep="last")]
        warnings.append(
            f"Removed {duplicate_count} duplicate datetime row(s), keeping "
            "the last observation."
        )

    for column in _OHLC_COLUMNS:
        try:
            values = pd.to_numeric(frame[column], errors="coerce").astype(float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"OHLC column {column!r} must be numeric") from exc
        if not np.isfinite(values.to_numpy()).all():
            raise ValueError(
                f"Invalid OHLC: {column} contains missing or non-finite values"
            )
        if (values <= 0).any():
            raise ValueError(
                f"Invalid OHLC: {column} must contain strictly positive prices"
            )
        frame[column] = values

    if (frame["High"] < frame["Low"]).any():
        raise ValueError("Invalid OHLC: every High must be greater than or equal to Low")

    if len(frame) > 1:
        gaps = frame.index.to_series().diff().dropna()
        # A three-day weekend is normal for daily market bars.  Longer gaps
        # are retained but surfaced to callers for data-quality reporting.
        unusual_gaps = gaps[gaps > pd.Timedelta(days=3)]
        if len(unusual_gaps):
            warnings.append(
                f"Found {len(unusual_gaps)} calendar gap(s) longer than "
                "three days in the OHLC index."
            )
    return frame, warnings


def _empty_datetime_series(index: pd.DatetimeIndex) -> pd.Series:
    """Create a NaT series retaining a timezone-aware index dtype if present."""

    return pd.Series(pd.NaT, index=index, dtype=index.dtype)


def _set_anchor(
    anchor_dates: list[Any],
    anchor_prices: np.ndarray,
    anchor_types: list[Any],
    confirmation_dates: list[Any],
    elapsed: np.ndarray,
    row: int,
    anchor_row: int,
    anchor_type: str,
    index: pd.DatetimeIndex,
    close: np.ndarray,
    confirmation_row: int | None = None,
    anchor_price_source: np.ndarray | None = None,
) -> None:
    """Set one causal anchor observation in-place."""

    anchor_dates[row] = index[anchor_row]
    prices = close if anchor_price_source is None else anchor_price_source
    anchor_prices[row] = prices[anchor_row]
    anchor_types[row] = anchor_type
    confirmation_dates[row] = index[
        row if confirmation_row is None else confirmation_row
    ]
    elapsed[row] = row - anchor_row


def _swing_pivots(
    lows: np.ndarray,
    highs: np.ndarray,
    pivot_bars: int,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (origin row, confirmation row) tuples for causal pivots.

    Equality is allowed at a pivot boundary, which is useful for market data
    whose prices are rounded to cents.  Since observations select the latest
    confirmed pivot, tied plateaus resolve deterministically to the latest
    confirmed originating row.
    """

    lows_found: list[tuple[int, int]] = []
    highs_found: list[tuple[int, int]] = []
    n = len(lows)
    k = pivot_bars
    for origin in range(k, n - k):
        window_low = lows[origin - k : origin + k + 1]
        window_high = highs[origin - k : origin + k + 1]
        if lows[origin] <= np.min(window_low):
            lows_found.append((origin, origin + k))
        if highs[origin] >= np.max(window_high):
            highs_found.append((origin, origin + k))
    return lows_found, highs_found


def _normalize_fixed_timestamp(
    timestamp: pd.Timestamp, index: pd.DatetimeIndex
) -> pd.Timestamp:
    """Make a fixed timestamp comparable with the OHLC index timezone."""

    if index.tz is None:
        if timestamp.tzinfo is not None:
            return timestamp.tz_localize(None)
        return timestamp
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(index.tz)
    return timestamp.tz_convert(index.tz)


def _build_anchor_arrays(
    frame: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[list[Any], np.ndarray, list[Any], list[Any], np.ndarray]:
    """Construct anchor metadata using only data available at each row."""

    index = frame.index
    close = frame["Close"].to_numpy(dtype=float)
    n = len(frame)
    mode = str(config["anchor_mode"])
    lookback = int(config["lookback"])
    anchor_dates: list[Any] = [pd.NaT] * n
    anchor_prices = np.full(n, np.nan, dtype=float)
    anchor_types: list[Any] = [None] * n
    confirmation_dates: list[Any] = [pd.NaT] * n
    elapsed = np.full(n, np.nan, dtype=float)

    if mode in {"low20", "high20"}:
        # These rule names deliberately mean exactly twenty closing
        # observations.  ``lookback`` is a control for the separate rolling
        # anchor rule and must not silently redefine a named 20-day rule.
        named_window = 20
        for row in range(named_window - 1, n):
            start = row - named_window + 1
            values = close[start : row + 1]
            extreme = np.min(values) if mode == "low20" else np.max(values)
            # Search from the right so ties always use the most recent bar.
            matches = np.flatnonzero(values == extreme)
            origin = start + int(matches[-1])
            _set_anchor(
                anchor_dates,
                anchor_prices,
                anchor_types,
                confirmation_dates,
                elapsed,
                row,
                origin,
                mode,
                index,
                close,
            )
    elif mode == "rolling":
        # The current N-session window contains rows i-N+1 through i.  Its
        # start is therefore N-1 elapsed sessions before t (and includes t).
        for row in range(lookback - 1, n):
            _set_anchor(
                anchor_dates,
                anchor_prices,
                anchor_types,
                confirmation_dates,
                elapsed,
                row,
                row - lookback + 1,
                mode,
                index,
                close,
            )
    elif mode == "fixed":
        fixed = _normalize_fixed_timestamp(
            pd.Timestamp(config["fixed_anchor"]), index
        )
        available = np.flatnonzero(index >= fixed)
        if len(available):
            origin = int(available[0])
            for row in range(origin, n):
                _set_anchor(
                    anchor_dates,
                    anchor_prices,
                    anchor_types,
                    confirmation_dates,
                    elapsed,
                    row,
                    origin,
                    mode,
                    index,
                    close,
                    confirmation_row=origin,
                )
    else:
        low_prices = frame["Low"].to_numpy(dtype=float)
        high_prices = frame["High"].to_numpy(dtype=float)
        lows, highs = _swing_pivots(
            low_prices,
            high_prices,
            int(config["pivot_bars"]),
        )
        selected = lows if mode == "swing_low" else highs
        swing_prices = low_prices if mode == "swing_low" else high_prices
        # A pivot's confirmation rows are strictly increasing with origin.
        # Selecting the last confirmed tuple therefore selects the most recent
        # available pivot without exposing any unconfirmed candidate.
        latest_origin = -1
        latest_confirmation = -1
        for row in range(n):
            for origin, confirmation in selected:
                if confirmation <= row and confirmation > latest_confirmation:
                    latest_origin = origin
                    latest_confirmation = confirmation
            if latest_origin >= 0:
                _set_anchor(
                    anchor_dates,
                    anchor_prices,
                    anchor_types,
                    confirmation_dates,
                    elapsed,
                    row,
                    latest_origin,
                    mode,
                    index,
                    close,
                    confirmation_row=latest_confirmation,
                    anchor_price_source=swing_prices,
                )

    return (
        anchor_dates,
        anchor_prices,
        anchor_types,
        confirmation_dates,
        elapsed,
    )


def build_features(
    ohlc: pd.DataFrame, config: dict | None = None
) -> pd.DataFrame:
    """Build causal time--price area features from adjusted OHLC data.

    The input is expected to contain completed, adjusted daily bars.  Invalid
    OHLC values raise ``ValueError`` rather than being silently repaired.  A
    few rows at the beginning of each causal rolling calculation are
    intentionally ``NaN`` warmups.
    """

    frame, quality_warnings = _prepare_ohlc(ohlc)
    cfg = _as_config(config)
    index = frame.index
    n = len(frame)
    close = frame["Close"]

    (
        anchor_dates,
        anchor_prices,
        anchor_types,
        confirmation_dates,
        elapsed,
    ) = _build_anchor_arrays(frame, cfg)

    anchor_date_series = pd.Series(anchor_dates, index=index)
    if index.tz is not None:
        anchor_date_series = pd.to_datetime(anchor_date_series, utc=True).dt.tz_convert(
            index.tz
        )
    else:
        anchor_date_series = pd.to_datetime(anchor_date_series)
    confirmation_series = pd.Series(confirmation_dates, index=index)
    if index.tz is not None:
        confirmation_series = pd.to_datetime(
            confirmation_series, utc=True
        ).dt.tz_convert(index.tz)
    else:
        confirmation_series = pd.to_datetime(confirmation_series)

    out = pd.DataFrame(index=index)
    out["close"] = close.astype(float)
    out["anchor_date"] = anchor_date_series
    out["anchor_price"] = pd.Series(anchor_prices, index=index)
    out["anchor_type"] = pd.Series(anchor_types, index=index, dtype="object")
    out["anchor_confirmation_date"] = confirmation_series
    out["elapsed_sessions"] = pd.Series(elapsed, index=index)
    out["session_pos"] = pd.Series(np.arange(n, dtype=np.int64), index=index)

    log_return = np.log(close / close.shift(1))
    out["log_return"] = log_return

    anchor_price = out["anchor_price"]
    relative_log_move = np.log(close / anchor_price)
    area_raw = out["elapsed_sessions"] * (close - anchor_price).abs()
    area_log = out["elapsed_sessions"] * relative_log_move.abs()
    area_signed = out["elapsed_sessions"] * relative_log_move
    out["area_raw"] = area_raw.where(np.isfinite(area_raw), np.nan)
    out["area_log"] = area_log.where(np.isfinite(area_log), np.nan)
    out["area_signed"] = area_signed.where(np.isfinite(area_signed), np.nan)

    vol_window = int(cfg["vol_window"])
    # shift(1) is essential: volatility at t excludes the t return.
    volatility = log_return.shift(1).rolling(
        vol_window, min_periods=vol_window
    ).std(ddof=1)
    volatility = volatility.where(np.isfinite(volatility), np.nan)
    out["volatility"] = volatility

    if cfg["normalization"] == "volatility":
        area_norm = area_log / volatility
        area_norm = area_norm.where(np.isfinite(area_norm), np.nan)
    else:
        # Sensitivity mode retains all raw definitions while making normalized
        # area equal to log area (there is no volatility divisor).
        area_norm = out["area_log"].copy()
    out["area_norm"] = area_norm
    out["area_growth"] = area_norm.diff()

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    # There is no previous close on the first row; its true range is its
    # intrabar range, while all later rows use the full true-range definition.
    if n:
        true_range.iloc[0] = frame["High"].iloc[0] - frame["Low"].iloc[0]
    atr = true_range.rolling(14, min_periods=14).mean()
    out["atr_pct"] = (atr / close).where(np.isfinite(atr / close), np.nan)

    for period in (1, 5, 10, 20):
        out[f"ret_{period}"] = np.log(close / close.shift(period))
    out["abs_ret_5"] = out["ret_5"].abs()
    out["abs_ret_20"] = out["ret_20"].abs()

    short_ma = close.rolling(5, min_periods=5).mean()
    long_ma = close.rolling(20, min_periods=20).mean()
    ma_trend = short_ma / long_ma - 1.0
    out["ma_trend"] = ma_trend.where(np.isfinite(ma_trend), np.nan)

    # Keep the public schema stable even if an implementation detail above
    # changes the insertion order.
    out = out.loc[:, FEATURE_COLUMNS]
    out.attrs["data_quality_warnings"] = quality_warnings
    out.attrs["config"] = dict(cfg)
    out.attrs["anchor_reset_note"] = _ANCHOR_RESET_NOTE
    return out


def _validate_horizons(horizons: Iterable[int] | int | None) -> list[int]:
    if horizons is None:
        values: Iterable[int] = _DEFAULT_HORIZONS
    elif isinstance(horizons, (int, np.integer)) and not isinstance(horizons, bool):
        values = (int(horizons),)
    else:
        try:
            values = list(horizons)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("horizons must be a positive integer iterable") from exc

    result: list[int] = []
    for horizon in values:
        if isinstance(horizon, bool):
            raise ValueError("horizons must contain positive integers")
        try:
            numeric_horizon = int(horizon)
        except (TypeError, ValueError) as exc:
            raise ValueError("horizons must contain positive integers") from exc
        if numeric_horizon != horizon or numeric_horizon < 1:
            raise ValueError("horizons must contain positive integers")
        if numeric_horizon not in result:
            result.append(numeric_horizon)
    if not result:
        raise ValueError("horizons must contain at least one positive integer")
    return result


def add_targets(
    features: pd.DataFrame, horizons: Iterable[int] | int | None = None
) -> pd.DataFrame:
    """Append strictly forward labels to a feature frame.

    ``future_area_*`` values are read from the future row's own causal
    feature construction.  Forward drawdown and favorable movement use the
    minimum/maximum *closing* price from ``t`` through ``t+h`` relative to
    ``P_t``; consequently drawdown is non-positive and favorable movement is
    non-negative.
    """

    if not isinstance(features, pd.DataFrame):
        raise TypeError("features must be a pandas DataFrame")
    missing = [column for column in ("close", "area_norm", "area_log") if column not in features]
    if missing:
        raise ValueError(f"features is missing required columns: {missing}")
    if not isinstance(features.index, pd.DatetimeIndex):
        raise ValueError("features must have a datetime index")
    if not features.index.is_monotonic_increasing or features.index.has_duplicates:
        raise ValueError("features index must be sorted and unique")

    values = _validate_horizons(horizons)
    result = features.copy(deep=True)
    index = features.index
    close = pd.to_numeric(features["close"], errors="coerce").astype(float)
    session_pos = (
        features["session_pos"]
        if "session_pos" in features
        else pd.Series(np.arange(len(features), dtype=np.int64), index=index)
    )

    for horizon in values:
        future_area_norm = features["area_norm"].shift(-horizon)
        future_area_log = features["area_log"].shift(-horizon)
        future_close = close.shift(-horizon)
        signed_return = np.log(future_close / close)
        signed_return = signed_return.where(np.isfinite(signed_return), np.nan)

        result[f"future_area_norm_{horizon}"] = future_area_norm
        result[f"future_area_log_{horizon}"] = future_area_log
        # This is a difference in the log-area variable, not a ratio of areas.
        result[f"future_area_change_{horizon}"] = (
            future_area_log - features["area_log"]
        )
        result[f"future_norm_area_change_{horizon}"] = (
            future_area_norm - features["area_norm"]
        )
        result[f"future_abs_return_{horizon}"] = signed_return.abs()
        result[f"future_signed_return_{horizon}"] = signed_return

        drawdown = np.full(len(features), np.nan, dtype=float)
        favorable = np.full(len(features), np.nan, dtype=float)
        close_values = close.to_numpy(dtype=float)
        for row in range(max(0, len(features) - horizon)):
            path = close_values[row : row + horizon + 1]
            start_price = close_values[row]
            if (
                np.isfinite(start_price)
                and np.isfinite(path).all()
                and start_price > 0
            ):
                drawdown[row] = np.min(path) / start_price - 1.0
                favorable[row] = np.max(path) / start_price - 1.0
        result[f"forward_drawdown_{horizon}"] = pd.Series(
            drawdown, index=index
        )
        result[f"forward_favorable_{horizon}"] = pd.Series(
            favorable, index=index
        )

        target_dates = pd.Series(index, index=index).shift(-horizon)
        result[f"target_date_{horizon}"] = target_dates
        result[f"target_end_pos_{horizon}"] = session_pos.shift(-horizon)

    result.attrs = dict(features.attrs)
    result.attrs["anchor_reset_note"] = _ANCHOR_RESET_NOTE
    result.attrs["target_horizons"] = list(values)
    return result


__all__ = ["FEATURE_COLUMNS", "add_targets", "build_features"]